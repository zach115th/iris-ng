#  IRIS Source Code
#  Copyright (C) 2026 - iris-ng
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3 of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

"""Investigation Flows (iris-ng v2, Phase 3).

Checklists auto-attached at ingest by the shared condition grammar
(business/condition_eval.py). ``evaluate_attachment`` runs in the ingest
post-create pipeline right after clustering, fail-soft:

  - target='alert' flows attach to every matching alert;
  - target='cluster' flows attach to a cluster when the alert that CREATES
    it matches (the triggering alert's view is what conditions see — a
    cluster has no view of its own);
  - target='both' does both. ALL matching flows attach (checklists are not
    exclusive); priority only orders display.

Ingest writes ONLY FlowAttachment rows (one indexed SELECT + inserts + one
relaxed-durability commit). Step states are lazily created on first READ of
a checklist (``ensure_step_states``) so the hot path never fans out per
step. Attachment is idempotent by UNIQUE(flow, anchor), which also makes
``deploy`` (backfill over historic alerts/clusters) a natural no-op where
it already ran.

Required steps are ADVISORY in v1: ``serialize_attachment`` computes
``required_incomplete`` server-side; the UI shows an amber banner, nothing
blocks.
"""

import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app import app as flask_app
from app import celery
from app import db
from app.business.condition_eval import build_alert_view
from app.business.condition_eval import evaluate_tree
from app.models.alerts import Alert
from app.models.alerts import AlertCluster
from app.models.alerts import AlertClusterMember
from app.models.alerts import FlowAttachment
from app.models.alerts import FlowStep
from app.models.alerts import FlowStepState
from app.models.alerts import InvestigationFlow

log = logging.getLogger(__name__)

VALID_STEP_STATES = ('pending', 'done', 'skipped')


def load_enabled_flows():
    return (InvestigationFlow.query
            .filter(InvestigationFlow.enabled.is_(True))
            .order_by(InvestigationFlow.priority.asc(), InvestigationFlow.id.asc())
            .all())


def _relax_commit_durability():
    """Attachments are derived data, recoverable via deploy — same relaxed
    fsync treatment as cluster membership (SET LOCAL = this transaction)."""
    from sqlalchemy import text as _text
    db.session.execute(_text('SET LOCAL synchronous_commit TO OFF'))


def evaluate_attachment(alert: Alert, cluster: AlertCluster = None,
                        cluster_created: bool = False, *, durable: bool = False):
    """Attach every matching enabled flow to the alert (and, when this alert
    just created a cluster, to that cluster). Returns the list of
    FlowAttachment rows created. One commit; caller is fail-soft.

    ``durable=True`` skips the relaxed-fsync SET LOCAL (used by the deploy
    backfill, where wall-clock does not matter).
    """
    flows = load_enabled_flows()
    if not flows:
        return []

    view = build_alert_view(alert)
    matching = [f for f in flows if evaluate_tree(f.match_conditions, view)]
    if not matching:
        return []

    wanted = []   # (flow_id, alert_id, cluster_id)
    for flow in matching:
        if flow.target in ('alert', 'both'):
            wanted.append((flow.id, alert.alert_id, None))
        if flow.target in ('cluster', 'both') and cluster is not None and cluster_created:
            wanted.append((flow.id, None, cluster.id))
    if not wanted:
        return []

    # One SELECT skips anchors already attached (idempotency without
    # tripping the UNIQUEs on the common path).
    flow_ids = list({w[0] for w in wanted})
    existing = set()
    rows = (FlowAttachment.query
            .filter(FlowAttachment.flow_id.in_(flow_ids))
            .filter(db.or_(FlowAttachment.alert_id == alert.alert_id,
                           FlowAttachment.cluster_id == (cluster.id if cluster else -1)))
            .all())
    for r in rows:
        existing.add((r.flow_id, r.alert_id, r.cluster_id))

    created = []
    for flow_id, alert_id, cluster_id in wanted:
        if (flow_id, alert_id, cluster_id) in existing:
            continue
        created.append(FlowAttachment(flow_id=flow_id, alert_id=alert_id,
                                      cluster_id=cluster_id))
    if not created:
        return []

    db.session.add_all(created)
    try:
        if not durable:
            _relax_commit_durability()
        db.session.commit()
    except IntegrityError:
        # Race with a concurrent evaluation — re-run row by row, keeping
        # whatever is insertable. Rare path.
        db.session.rollback()
        kept = []
        for att in created:
            row = FlowAttachment(flow_id=att.flow_id, alert_id=att.alert_id,
                                 cluster_id=att.cluster_id)
            db.session.add(row)
            try:
                db.session.commit()
                kept.append(row)
            except IntegrityError:
                db.session.rollback()
        created = kept

    if created:
        log.info('investigation flows: alert #%s -> %d attachment(s) (%s)',
                 alert.alert_id, len(created),
                 ', '.join(f'flow {a.flow_id}' for a in created))
    return created


# ----------------------------------------------------------- step states

def ensure_step_states(attachment: FlowAttachment):
    """Lazily materialize one FlowStepState per flow step for this
    attachment (pending). Returns states keyed by step_id. Called on READ —
    ingest never touches step states."""
    steps = (FlowStep.query
             .filter(FlowStep.flow_id == attachment.flow_id)
             .order_by(FlowStep.step_order.asc())
             .all())
    states = {s.step_id: s for s in
              FlowStepState.query
              .filter(FlowStepState.attachment_id == attachment.id).all()}
    missing = [FlowStepState(attachment_id=attachment.id, step_id=step.id)
               for step in steps if step.id not in states]
    if missing:
        db.session.add_all(missing)
        try:
            db.session.commit()
        except IntegrityError:
            # Concurrent first-read created them — re-fetch.
            db.session.rollback()
        states = {s.step_id: s for s in
                  FlowStepState.query
                  .filter(FlowStepState.attachment_id == attachment.id).all()}
    return steps, states


def set_step_state(attachment: FlowAttachment, step_id: int, state: str,
                   user_id: int, note: str = None) -> FlowStepState:
    """Update one step's state. done/skipped stamp who + when; returning a
    step to pending clears them. Raises ValueError on bad input."""
    if state not in VALID_STEP_STATES:
        raise ValueError(f'state must be one of {", ".join(VALID_STEP_STATES)}')
    step = db.session.get(FlowStep, step_id)
    if step is None or step.flow_id != attachment.flow_id:
        raise ValueError('step does not belong to this attachment\'s flow')

    ensure_step_states(attachment)
    row = (FlowStepState.query
           .filter(FlowStepState.attachment_id == attachment.id,
                   FlowStepState.step_id == step_id)
           .first())
    row.state = state
    if state == 'pending':
        row.done_by = None
        row.done_at = None
    else:
        row.done_by = user_id
        row.done_at = datetime.utcnow()
    if note is not None:
        row.note = note or None
    db.session.commit()
    return row


def serialize_attachment(attachment: FlowAttachment) -> dict:
    """Checklist payload for one attachment. required_incomplete is
    computed SERVER-SIDE (count rule — the UI banner never counts)."""
    steps, states = ensure_step_states(attachment)
    step_rows = []
    required_incomplete = 0
    for step in steps:
        st = states.get(step.id)
        state = st.state if st else 'pending'
        if step.is_required and state != 'done':
            required_incomplete += 1
        step_rows.append({
            'step_id': step.id,
            'order': step.step_order,
            'title': step.title,
            'description': step.description,
            'is_required': step.is_required,
            'state': state,
            'done_by': (st.done_by_user.name
                        if st and st.done_by_user else None),
            'done_at': (st.done_at.isoformat() + 'Z'
                        if st and st.done_at else None),
            'note': st.note if st else None,
        })
    flow = attachment.flow
    return {
        'attachment_id': attachment.id,
        'flow_id': attachment.flow_id,
        'flow_name': flow.name if flow else None,
        'flow_description': flow.description if flow else None,
        'flow_priority': flow.priority if flow else 100,
        'alert_id': attachment.alert_id,
        'cluster_id': attachment.cluster_id,
        'attached_at': (attachment.attached_at.isoformat() + 'Z'
                        if attachment.attached_at else None),
        'steps': step_rows,
        'steps_total': len(step_rows),
        'steps_done': sum(1 for s in step_rows if s['state'] == 'done'),
        'required_incomplete': required_incomplete,
    }


def attachments_for_alert(alert_id: int):
    atts = (FlowAttachment.query
            .filter(FlowAttachment.alert_id == alert_id)
            .join(InvestigationFlow, InvestigationFlow.id == FlowAttachment.flow_id)
            .order_by(InvestigationFlow.priority.asc(), FlowAttachment.id.asc())
            .all())
    return [serialize_attachment(a) for a in atts]


def attachments_for_cluster(cluster_id: int):
    atts = (FlowAttachment.query
            .filter(FlowAttachment.cluster_id == cluster_id)
            .join(InvestigationFlow, InvestigationFlow.id == FlowAttachment.flow_id)
            .order_by(InvestigationFlow.priority.asc(), FlowAttachment.id.asc())
            .all())
    return [serialize_attachment(a) for a in atts]


# ----------------------------------------------------------------- deploy

def deploy_flows(flow_id: int = None):
    """Backfill: evaluate every enabled flow over historic anchors.
    Idempotent (UNIQUE(flow, anchor)). Alerts are evaluated on their own
    view; clusters on their EARLIEST member's view (the triggering alert of
    an old cluster is unrecorded — the first member is the closest proxy,
    documented). ``flow_id`` is echoed in the summary; evaluation always
    covers all enabled flows so results match what ingest would have done.
    """
    summary = {'flow_id': flow_id, 'alerts_examined': 0, 'clusters_examined': 0,
               'attached': 0, 'errors': 0}
    if not load_enabled_flows():
        return summary

    # Materialize id lists first — committing inside a yield_per() loop
    # kills the server-side named cursor (Phase 2 lesson).
    alert_ids = [r[0] for r in db.session.query(Alert.alert_id)
                 .order_by(Alert.alert_id.asc()).all()]
    for aid in alert_ids:
        summary['alerts_examined'] += 1
        try:
            alert = db.session.get(Alert, aid)
            if alert is None:
                continue
            # durable=True: no SET LOCAL spam on a long batch.
            created = evaluate_attachment(alert, durable=True)
            summary['attached'] += len(created)
        except Exception:
            db.session.rollback()
            summary['errors'] += 1
            log.exception('flow deploy: alert #%s failed', aid)

    cluster_ids = [r[0] for r in db.session.query(AlertCluster.id)
                   .order_by(AlertCluster.id.asc()).all()]
    for cid in cluster_ids:
        summary['clusters_examined'] += 1
        try:
            cluster = db.session.get(AlertCluster, cid)
            if cluster is None:
                continue
            first_member = (db.session.query(Alert)
                            .join(AlertClusterMember,
                                  AlertClusterMember.alert_id == Alert.alert_id)
                            .filter(AlertClusterMember.cluster_id == cid)
                            .order_by(Alert.alert_creation_time.asc(),
                                      Alert.alert_id.asc())
                            .first())
            if first_member is None:
                continue
            created = evaluate_attachment(first_member, cluster=cluster,
                                          cluster_created=True, durable=True)
            summary['attached'] += len(created)
        except Exception:
            db.session.rollback()
            summary['errors'] += 1
            log.exception('flow deploy: cluster #%s failed', cid)
    return summary


@celery.task(bind=True)
def task_deploy_flows(self, flow_id: int = None):
    """Celery entry point for the /deploy endpoint (default queue)."""
    with flask_app.app_context():
        try:
            summary = deploy_flows(flow_id)
            log.info('flow deploy: %s', summary)
            return summary
        except Exception as e:
            db.session.rollback()
            log.exception('flow deploy failed')
            return {'error': str(e)[:500]}

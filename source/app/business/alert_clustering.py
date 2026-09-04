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

"""Alert Clustering (iris-ng v2, Phase 2).

``evaluate_alert(alert)`` runs SYNCHRONOUSLY in the ingest post-create
pipeline (business/alerts_ingest.py) — a celery hop would open window races
between near-simultaneous alerts. Cost per alert is Python condition checks
over an in-memory view plus one indexed SELECT; benchmarked against the
Phase 0 baseline (acceptance: p95 delta < 10 ms).

Semantics:

  - Enabled rules are evaluated ascending by priority; the FIRST rule whose
    match_conditions accept the alert claims it (an alert joins at most one
    cluster — UNIQUE(alert_id) on alert_cluster_member).
  - Fingerprint = sha256(rule_id | customer_id | sorted key=value pairs)
    [:32]. rule_id and customer_id are ALWAYS hashed in — tenant isolation
    by construction, and two rules with identical keys never share clusters.
    Unresolvable correlation keys resolve to '' (stable, documented).
  - Stacking window: if the open cluster's last_alert_at is more than
    window_minutes before this alert's time, that cluster is CLOSED (stale)
    and a fresh one opens. Times are INGEST times (alert_creation_time) —
    source event times arrive out of order and would tear windows apart.
  - Concurrency: the partial unique index (fingerprint WHERE status='open')
    makes creation race-safe — the losing creator gets an IntegrityError,
    rolls back, re-SELECTs and joins (retry once, then give up quietly).

The caller (the ingest pipeline) wraps this fail-soft AND rolls the session
back on failure — a clustering defect must never fail alert ingest, and a
poisoned session must never reach core's next commit (PendingRollbackError
rule).
"""

import hashlib
import logging
from datetime import datetime
from datetime import timedelta

import re as _re

from sqlalchemy.exc import IntegrityError

from app import app as flask_app
from app import celery
from app import db
from app.business.condition_eval import MISSING
from app.business.condition_eval import build_alert_view
from app.business.condition_eval import evaluate_tree
from app.business.condition_eval import resolve_path
from app.models.alerts import Alert
from app.models.alerts import AlertCluster
from app.models.alerts import AlertClusteringRule
from app.models.alerts import AlertClusterMember

log = logging.getLogger(__name__)

# Same safe-substitution rule as mail title templates: named {path} tokens
# only, resolved against the alert view — never str.format (format-spec
# injection). Unresolved tokens render as ''.
_TEMPLATE_TOKEN = _re.compile(r'\{([A-Za-z0-9_.]+)\}')


def load_enabled_rules():
    return (AlertClusteringRule.query
            .filter(AlertClusteringRule.enabled.is_(True))
            .order_by(AlertClusteringRule.priority.asc(),
                      AlertClusteringRule.id.asc())
            .all())


def match_rule_for_alert(alert, rules):
    """Pure first-match: returns (rule, view) or (None, view). Shared by
    live evaluation, the dry-run /test endpoint and the backfill task."""
    view = build_alert_view(alert)
    for rule in rules:
        if evaluate_tree(rule.match_conditions, view):
            return rule, view
    return None, view


def resolve_correlation_values(rule, view) -> dict:
    values = {}
    for key in (rule.correlation_keys or []):
        if not isinstance(key, str):
            continue
        resolved = resolve_path(view, key)
        if resolved is MISSING or resolved is None:
            values[key] = ''
        elif isinstance(resolved, (list, dict)):
            # Lists/dicts are not stable correlation material; refuse rather
            # than fingerprint a repr.
            values[key] = ''
        else:
            values[key] = str(resolved)
    return values


def compute_fingerprint(rule_id: int, customer_id: int, values: dict) -> str:
    material = f'{rule_id}|{customer_id}|' + '|'.join(
        f'{k}={values[k]}' for k in sorted(values))
    return hashlib.sha256(material.encode('utf-8', errors='replace')).hexdigest()[:32]


def render_cluster_title(rule, view, values: dict) -> str:
    if rule.title_template:
        def _sub(m):
            resolved = resolve_path(view, m.group(1))
            if resolved is MISSING or resolved is None or isinstance(resolved, (list, dict)):
                return ''
            return str(resolved)
        title = _TEMPLATE_TOKEN.sub(_sub, rule.title_template).strip()
        if title:
            return title[:500]
    value_part = ', '.join(v for v in values.values() if v)
    return f'{rule.name}: {value_part}'[:500] if value_part else rule.name[:500]


# v3 status vocabulary: these two states accept new members (and back the
# partial unique index's predicate). dismissed/escalated/closed are terminal
# for stacking — a matching alert opens a fresh cluster instead.
ACTIVE_CLUSTER_STATUSES = ('open', 'investigating')


def _find_open_cluster(fingerprint: str):
    return (AlertCluster.query
            .filter(AlertCluster.correlation_fingerprint == fingerprint,
                    AlertCluster.status.in_(ACTIVE_CLUSTER_STATUSES))
            .first())


def _close_cluster(cluster, when: datetime):
    cluster.status = 'closed'
    cluster.closed_at = when
    # closed_by stays NULL: the system closed it (stale window), no analyst.


def _relax_commit_durability():
    """SET LOCAL synchronous_commit TO OFF for the CURRENT transaction only.

    Clustering rows are derived data: a crash losing the last few membership
    writes is fully recoverable via the backfill task, and the fsync wait
    was the largest single cost this feature added to the ingest hot path
    (p95 benchmark). SET LOCAL scopes the relaxation to this transaction —
    the alert itself was committed durably before the pipeline ran.
    """
    from sqlalchemy import text as _text
    db.session.execute(_text('SET LOCAL synchronous_commit TO OFF'))


def evaluate_alert(alert: Alert):
    """Cluster one freshly-created alert. Returns the AlertCluster the alert
    joined, or None (no rule matched / gave up after a race). Commits its own
    work — ONE commit on every path (hot-path cost); raises only on
    unexpected DB failure (caller is fail-soft)."""
    rules = load_enabled_rules()
    if not rules:
        return None

    rule, view = match_rule_for_alert(alert, rules)
    if rule is None:
        return None

    alert_time = alert.alert_creation_time or datetime.utcnow()
    values = resolve_correlation_values(rule, view)
    fingerprint = compute_fingerprint(rule.id, alert.alert_customer_id, values)

    cluster = _find_open_cluster(fingerprint)
    stale = None
    if cluster is not None:
        stale_after = cluster.last_alert_at + timedelta(minutes=rule.window_minutes or 1440)
        if alert_time > stale_after:
            # Close-stale + create-fresh ride the same transaction below —
            # the partial unique index sees both changes atomically.
            stale = cluster
            cluster = None

    if cluster is None:
        if stale is not None:
            _close_cluster(stale, alert_time)
        cluster = AlertCluster(
            rule_id=rule.id,
            customer_id=alert.alert_customer_id,
            correlation_fingerprint=fingerprint,
            correlation_values=values,
            title=render_cluster_title(rule, view, values),
            status='open',
            first_alert_at=alert_time,
            last_alert_at=alert_time,
        )
        db.session.add(cluster)
        try:
            db.session.flush()  # assigns cluster.id; unique-index race raises here
            db.session.add(AlertClusterMember(cluster_id=cluster.id,
                                              alert_id=alert.alert_id))
            _relax_commit_durability()
            db.session.commit()
            # Transient marker for the pipeline: cluster-target investigation
            # flows attach only when the alert CREATED the cluster.
            cluster.freshly_created = True
            log.info('alert clustering: alert #%s -> NEW cluster #%s (%s) via rule %r',
                     alert.alert_id, cluster.id, fingerprint, rule.name)
            return cluster
        except IntegrityError:
            # Lost the open-fingerprint race: someone else created it between
            # our SELECT and COMMIT. Roll back and join theirs (retry once).
            db.session.rollback()
            cluster = _find_open_cluster(fingerprint)
            if cluster is None:
                log.warning('alert clustering: race retry found no open cluster '
                            'for fingerprint %s — giving up on alert #%s',
                            fingerprint, alert.alert_id)
                return None

    # Join path: one INSERT + one UPDATE + one commit.
    db.session.add(AlertClusterMember(cluster_id=cluster.id, alert_id=alert.alert_id))
    if alert_time > cluster.last_alert_at:
        cluster.last_alert_at = alert_time
    try:
        _relax_commit_durability()
        db.session.commit()
    except IntegrityError:
        # UNIQUE(alert_id): the alert is already a member of some cluster
        # (backfill overlap, double-fire). Not an error worth failing on.
        db.session.rollback()
        log.info('alert clustering: alert #%s already belongs to a cluster — skipped',
                 alert.alert_id)
        return cluster

    log.info('alert clustering: alert #%s -> cluster #%s (%s) via rule %r',
             alert.alert_id, cluster.id, fingerprint, rule.name)
    return cluster


def backfill_rules(rule_id: int = None):
    """Run first-match clustering over every alert not yet in a cluster,
    oldest first (window stacking needs chronological order). Full
    first-match — NOT scoped to one rule — so backfill can never violate the
    priority semantics an ingest-time evaluation would have produced;
    ``rule_id`` is only echoed in the summary for the UI.

    Runs inside an app context (celery task below). Returns a summary dict.
    """
    rules = load_enabled_rules()
    summary = {'rule_id': rule_id, 'examined': 0, 'clustered': 0, 'errors': 0}
    if not rules:
        return summary

    # Materialize the id list FIRST: evaluate_alert commits inside the loop,
    # and a commit invalidates the server-side named cursor yield_per() holds
    # open ("named cursor isn't valid anymore"). A list of BigInts is cheap
    # at any realistic alert volume; the per-alert fetch below is indexed.
    alert_ids = [row[0] for row in
                 (db.session.query(Alert.alert_id)
                  .outerjoin(AlertClusterMember,
                             AlertClusterMember.alert_id == Alert.alert_id)
                  .filter(AlertClusterMember.alert_id.is_(None))
                  .order_by(Alert.alert_creation_time.asc(), Alert.alert_id.asc())
                  .all())]

    for alert_id in alert_ids:
        summary['examined'] += 1
        try:
            alert = db.session.get(Alert, alert_id)
            if alert is None:
                continue
            if evaluate_alert(alert) is not None:
                summary['clustered'] += 1
        except Exception:
            db.session.rollback()
            summary['errors'] += 1
            log.exception('alert clustering backfill: alert #%s failed', alert_id)
    return summary


@celery.task(bind=True)
def task_backfill_clustering(self, rule_id: int = None):
    """Celery entry point for the /backfill endpoint. Default queue (light
    DB work, not an AI call). Registered in web + worker because the
    blueprint imports this module."""
    with flask_app.app_context():
        try:
            summary = backfill_rules(rule_id)
            log.info('alert clustering backfill: %s', summary)
            return summary
        except Exception as e:
            db.session.rollback()
            log.exception('alert clustering backfill failed')
            return {'error': str(e)[:500]}

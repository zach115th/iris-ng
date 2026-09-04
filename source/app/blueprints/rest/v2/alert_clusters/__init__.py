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

"""Alert Clusters REST surface (iris-ng v2, Phase 2).

Two permission tiers:
  - clustering RULES are server_administrator (they decide grouping across
    the whole instance — configuration, not case data);
  - CLUSTERS are alerts_read / alerts_write, scoped per-customer via
    user_has_client_access — the same tenant boundary the alerts they
    aggregate live behind. The list derives the customer filter from
    get_user_clients_id (empty ⇒ empty result, NEVER "all" — the
    empty-list-means-nothing fork rule).

v1 has deliberately NO reopen endpoint: the partial unique index allows one
OPEN cluster per fingerprint, and reopening a closed cluster while a newer
open one exists for the same fingerprint would violate it. Close is final;
a matching alert simply opens a fresh cluster.

409s are built via response(409, ...) — response_api_error is 400-only
(project rule).
"""

import marshmallow
from flask import Blueprint
from flask import request
from flask_login import current_user

from app import db
from app.blueprints.access_controls import ac_api_requires
from app.blueprints.rest.endpoints import response
from app.blueprints.rest.endpoints import response_api_created
from app.blueprints.rest.endpoints import response_api_deleted
from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
from app.business.alert_clustering import backfill_rules  # noqa: F401 (re-export for scripts)
from app.business.alert_clustering import match_rule_for_alert
from app.business.alert_clustering import resolve_correlation_values
from app.business.alert_clustering import task_backfill_clustering
from app.business.condition_eval import build_alert_view
from app.business.condition_eval import evaluate_tree
from app.business.condition_eval import validate_tree
from app.datamgmt.manage.manage_access_control_db import get_user_clients_id
from app.datamgmt.manage.manage_access_control_db import user_has_client_access
from app.iris_engine.access_control.utils import ac_current_user_has_permission
from app.iris_engine.utils.tracker import track_activity
from app.models.alerts import Alert
from app.models.alerts import AlertCluster
from app.models.alerts import AlertClusteringRule
from app.models.alerts import AlertClusterMember
from app.models.authorization import Permissions
from app.schema.marshables import AlertClusteringRuleSchema

alert_clusters_blueprint = Blueprint('alert_clusters_rest_v2', __name__)

from datetime import datetime


def _iso(dt) -> str | None:
    """Naive-UTC datetimes must serialize with an explicit Z (project rule —
    a bare isoformat() is read as browser-local time)."""
    if dt is None:
        return None
    return dt.isoformat() + ('Z' if dt.tzinfo is None else '')


# ------------------------------------------------------------ clustering rules

@alert_clusters_blueprint.route('/alert-clustering-rules', methods=['GET'])
@ac_api_requires(Permissions.server_administrator)
def list_clustering_rules():
    rules = (AlertClusteringRule.query
             .order_by(AlertClusteringRule.priority.asc(), AlertClusteringRule.id.asc())
             .all())
    return response_api_success(AlertClusteringRuleSchema(many=True).dump(rules))


@alert_clusters_blueprint.route('/alert-clustering-rules', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def create_clustering_rule():
    try:
        rule = AlertClusteringRuleSchema().load(request.get_json())
    except marshmallow.exceptions.ValidationError as e:
        return response_api_error('Data error', data=e.messages)
    rule.created_by = current_user.id
    db.session.add(rule)
    db.session.commit()
    track_activity(f"created alert clustering rule '{rule.name}'", ctx_less=True)
    return response_api_created(AlertClusteringRuleSchema().dump(rule))


@alert_clusters_blueprint.route('/alert-clustering-rules/<int:rule_id>', methods=['GET'])
@ac_api_requires(Permissions.server_administrator)
def get_clustering_rule(rule_id):
    rule = db.session.get(AlertClusteringRule, rule_id)
    if rule is None:
        return response_api_not_found()
    return response_api_success(AlertClusteringRuleSchema().dump(rule))


@alert_clusters_blueprint.route('/alert-clustering-rules/<int:rule_id>', methods=['PUT'])
@ac_api_requires(Permissions.server_administrator)
def update_clustering_rule(rule_id):
    rule = db.session.get(AlertClusteringRule, rule_id)
    if rule is None:
        return response_api_not_found()
    try:
        rule = AlertClusteringRuleSchema().load(request.get_json(), instance=rule,
                                                partial=True)
    except marshmallow.exceptions.ValidationError as e:
        return response_api_error('Data error', data=e.messages)
    rule.updated_at = datetime.utcnow()
    db.session.commit()
    track_activity(f"updated alert clustering rule '{rule.name}'", ctx_less=True)
    return response_api_success(AlertClusteringRuleSchema().dump(rule))


@alert_clusters_blueprint.route('/alert-clustering-rules/<int:rule_id>', methods=['DELETE'])
@ac_api_requires(Permissions.server_administrator)
def delete_clustering_rule(rule_id):
    rule = db.session.get(AlertClusteringRule, rule_id)
    if rule is None:
        return response_api_not_found()
    name = rule.name
    # Clusters survive (rule_id SET NULL) — deleting a rule never destroys
    # the groupings it built.
    db.session.delete(rule)
    db.session.commit()
    track_activity(f"deleted alert clustering rule '{name}'", ctx_less=True)
    return response_api_deleted()


@alert_clusters_blueprint.route('/alert-clustering-rules/test', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def test_clustering_rule():
    """Dry-run: evaluate a condition tree (inline `conditions` or an existing
    `rule_id`) against `alert_ids` or the newest `last_n` alerts. Nothing is
    written. Returns per-alert match + resolved correlation values."""
    data = request.get_json() or {}

    rule = None
    conditions = data.get('conditions')
    correlation_keys = data.get('correlation_keys')
    if data.get('rule_id') is not None:
        rule = db.session.get(AlertClusteringRule, data['rule_id'])
        if rule is None:
            return response_api_not_found()
        if conditions is None:
            conditions = rule.match_conditions
        if correlation_keys is None:
            correlation_keys = rule.correlation_keys

    problems = validate_tree(conditions)
    if problems:
        return response_api_error('Invalid condition tree', data=problems)

    if data.get('alert_ids'):
        alerts = (Alert.query
                  .filter(Alert.alert_id.in_(list(data['alert_ids'])[:200]))
                  .all())
    else:
        last_n = min(int(data.get('last_n', 20) or 20), 200)
        alerts = (Alert.query
                  .order_by(Alert.alert_creation_time.desc(), Alert.alert_id.desc())
                  .limit(last_n).all())

    from types import SimpleNamespace
    key_proxy = SimpleNamespace(
        correlation_keys=[k for k in (correlation_keys or []) if isinstance(k, str)])

    results = []
    for alert in alerts:
        view = build_alert_view(alert)
        matched = evaluate_tree(conditions, view)
        entry = {'alert_id': alert.alert_id, 'title': alert.alert_title,
                 'matches': matched}
        if matched and key_proxy.correlation_keys:
            entry['correlation_values'] = resolve_correlation_values(key_proxy, view)
        results.append(entry)

    return response_api_success({
        'evaluated': len(results),
        'matched': sum(1 for r in results if r['matches']),
        'results': results,
    })


@alert_clusters_blueprint.route('/alert-clustering-rules/<int:rule_id>/backfill',
                                methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def backfill_clustering_rule(rule_id):
    """Run first-match clustering over every not-yet-clustered alert
    (chronological). Celery, default queue; the rule_id is echoed in the
    summary (evaluation is full first-match, so priority semantics hold)."""
    if db.session.get(AlertClusteringRule, rule_id) is None:
        return response_api_not_found()
    task = task_backfill_clustering.delay(rule_id)
    track_activity(f'started alert clustering backfill (rule #{rule_id})', ctx_less=True)
    return response(202, data={'task_id': task.id, 'state': 'queued'})


# ------------------------------------------------------------------- clusters

# Severity intensity is ranked by NAME, not by severity_id — lookup-table ids
# vary per deployment AND are not intensity-ordered (observed live: Medium=1,
# Critical=6). Unknown names rank lowest rather than failing.
_SEVERITY_RANK = {'unspecified': 0, 'informational': 1, 'low': 2,
                  'medium': 3, 'high': 4, 'critical': 5}

# v3 status vocabulary. 'closed' = window-expiry auto-close / legacy rows;
# the picker offers the first four. Active-for-stacking is defined in
# business/alert_clustering.py (ACTIVE_CLUSTER_STATUSES).
_VALID_CLUSTER_STATUSES = ('open', 'investigating', 'dismissed',
                           'escalated', 'closed')
_TERMINAL_CLUSTER_STATUSES = ('dismissed', 'escalated', 'closed')


def _max_severity_name(names) -> str | None:
    best = None
    for n in names:
        if not n:
            continue
        if best is None or (_SEVERITY_RANK.get(n.lower(), -1)
                            > _SEVERITY_RANK.get(best.lower(), -1)):
            best = n
    return best


def _member_severities(cluster_ids) -> dict:
    """{cluster_id: [severity_name, ...]} for the given clusters, one query."""
    from app.models.alerts import Severity
    if not cluster_ids:
        return {}
    rows = (db.session.query(AlertClusterMember.cluster_id, Severity.severity_name)
            .join(Alert, Alert.alert_id == AlertClusterMember.alert_id)
            .join(Severity, Severity.severity_id == Alert.alert_severity_id)
            .filter(AlertClusterMember.cluster_id.in_(cluster_ids)).all())
    out = {}
    for cid, name in rows:
        out.setdefault(cid, []).append(name)
    return out


def _effective_severity(cluster: AlertCluster, member_names) -> tuple:
    """(name, source) — the override wins while set; else derived max."""
    if cluster.severity_override is not None:
        return cluster.severity_override.severity_name, 'override'
    return _max_severity_name(member_names or []), 'derived'


def _cluster_row(cluster: AlertCluster, alert_count: int,
                 member_severities=None) -> dict:
    severity, severity_source = _effective_severity(cluster, member_severities)
    return {
        'id': cluster.id,
        'cluster_uuid': str(cluster.cluster_uuid),
        'title': cluster.title,
        'status': cluster.status,
        'rule_id': cluster.rule_id,
        'rule_name': cluster.rule.name if cluster.rule else None,
        'customer_id': cluster.customer_id,
        'customer_name': cluster.customer.name if cluster.customer else None,
        'correlation_values': cluster.correlation_values or {},
        'alert_count': alert_count,
        'severity': severity,
        'severity_source': severity_source,
        'severity_override_id': cluster.severity_override_id,
        'owner_id': cluster.owner_id,
        'owner_name': cluster.owner.name if cluster.owner else None,
        'escalated_case_id': cluster.escalated_case_id,
        'first_alert_at': _iso(cluster.first_alert_at),
        'last_alert_at': _iso(cluster.last_alert_at),
        'closed_at': _iso(cluster.closed_at),
        'created_at': _iso(cluster.created_at),
    }


def _get_cluster_checked(cluster_id):
    """Fetch + tenant check. Returns (cluster, error_response)."""
    cluster = db.session.get(AlertCluster, cluster_id)
    if cluster is None:
        return None, response_api_not_found()
    if not user_has_client_access(current_user.id, cluster.customer_id):
        # 404, not 403: existence of another tenant's cluster is itself data.
        return None, response_api_not_found()
    return cluster, None


@alert_clusters_blueprint.route('/alert-clusters', methods=['GET'])
@ac_api_requires(Permissions.alerts_read)
def list_alert_clusters():
    # Same tenant rule user_has_client_access applies per-row: a
    # server_administrator session sees every customer; anyone else sees
    # exactly their UserClient rows — and an EMPTY list means NOTHING,
    # never "all" (fork rule).
    if ac_current_user_has_permission(Permissions.server_administrator):
        query = AlertCluster.query
    else:
        client_ids = get_user_clients_id(current_user.id)
        if not client_ids:
            return response_api_success({'total': 0, 'clusters': []})
        query = AlertCluster.query.filter(AlertCluster.customer_id.in_(client_ids))

    # Header stat on the TENANT scope, before the view filters — "M awaiting
    # triage" is a property of the queue, not of the current filter view.
    awaiting = query.filter(AlertCluster.status == 'open',
                            AlertCluster.owner_id.is_(None)).count()

    status = request.args.get('status')
    if status in _VALID_CLUSTER_STATUSES:
        query = query.filter(AlertCluster.status == status)
    if request.args.get('customer_id'):
        query = query.filter(AlertCluster.customer_id == int(request.args['customer_id']))
    if request.args.get('rule_id'):
        query = query.filter(AlertCluster.rule_id == int(request.args['rule_id']))
    q = (request.args.get('q') or '').strip()
    if q:
        query = query.filter(AlertCluster.title.ilike(f'%{q}%'))

    page = max(int(request.args.get('page', 1) or 1), 1)
    per_page = min(int(request.args.get('per_page', 25) or 25), 100)

    sev_filter = (request.args.get('severity') or '').strip().lower()
    if sev_filter:
        # Severity is DERIVED (override else max member severity), so this
        # filter cannot be a SQL predicate: materialize the candidate set
        # (bounded), derive, filter, then paginate in Python.
        candidates = (query.order_by(AlertCluster.last_alert_at.desc())
                      .limit(2000).all())
        sevs = _member_severities([c.id for c in candidates])
        matched = [c for c in candidates
                   if (_effective_severity(c, sevs.get(c.id))[0] or '').lower()
                   == sev_filter]
        total = len(matched)
        rows = matched[(page - 1) * per_page: page * per_page]
        member_sev = sevs
    else:
        total = query.count()
        rows = (query.order_by(AlertCluster.last_alert_at.desc())
                .offset((page - 1) * per_page).limit(per_page).all())
        member_sev = _member_severities([c.id for c in rows])

    counts = dict(
        db.session.query(AlertClusterMember.cluster_id,
                         db.func.count(AlertClusterMember.alert_id))
        .filter(AlertClusterMember.cluster_id.in_([c.id for c in rows] or [0]))
        .group_by(AlertClusterMember.cluster_id).all())

    return response_api_success({
        'total': total,
        'page': page,
        'per_page': per_page,
        'awaiting_triage': awaiting,
        'clusters': [_cluster_row(c, counts.get(c.id, 0),
                                  member_sev.get(c.id)) for c in rows],
    })


@alert_clusters_blueprint.route('/alert-clusters/<int:cluster_id>', methods=['GET'])
@ac_api_requires(Permissions.alerts_read)
def get_alert_cluster(cluster_id):
    cluster, err = _get_cluster_checked(cluster_id)
    if err is not None:
        return err

    members = (db.session.query(Alert)
               .join(AlertClusterMember, AlertClusterMember.alert_id == Alert.alert_id)
               .filter(AlertClusterMember.cluster_id == cluster.id)
               .order_by(Alert.alert_creation_time.desc(), Alert.alert_id.desc())
               .all())

    detail = _cluster_row(cluster, len(members),
                          [a.severity.severity_name if a.severity else None
                           for a in members])
    detail['summary'] = cluster.summary
    detail['alerts'] = [{
        'alert_id': a.alert_id,
        'title': a.alert_title,
        'description': a.alert_description,
        'severity': a.severity.severity_name if a.severity else None,
        'status': a.status.status_name if a.status else None,
        'source': a.alert_source,
        'source_event_time': _iso(a.alert_source_event_time),
        'creation_time': _iso(a.alert_creation_time),
        'tags': a.alert_tags or '',
    } for a in members]
    # For the escalate deep-link (v1: the alerts page filtered to members).
    detail['alert_ids'] = [a.alert_id for a in members]
    return response_api_success(detail)


@alert_clusters_blueprint.route('/alert-clusters/<int:cluster_id>/close', methods=['POST'])
@ac_api_requires(Permissions.alerts_write)
def close_alert_cluster(cluster_id):
    cluster, err = _get_cluster_checked(cluster_id)
    if err is not None:
        return err
    if cluster.status == 'closed':
        return response_api_success(_cluster_row(cluster, -1))
    cluster.status = 'closed'
    cluster.closed_at = datetime.utcnow()
    cluster.closed_by = current_user.id
    db.session.commit()
    track_activity(f'closed alert cluster #{cluster.id}', ctx_less=True)
    count = AlertClusterMember.query.filter_by(cluster_id=cluster.id).count()
    return response_api_success(_cluster_row(cluster, count))


# ------------------------------------------- v3 parity: triage-field updates

@alert_clusters_blueprint.route('/alert-clusters/<int:cluster_id>', methods=['PUT'])
@ac_api_requires(Permissions.alerts_write)
def update_alert_cluster(cluster_id):
    """Partial update of the v3 triage fields: owner_id (assign/unassign;
    a TRANSITION to a new owner notifies via cluster_assigned),
    severity_override_id (null clears back to derived), summary (the
    analyst-owned Summary-tab document, autosaved by the page)."""
    cluster, err = _get_cluster_checked(cluster_id)
    if err is not None:
        return err
    data = request.get_json() or {}
    changed = []

    if 'status' in data:
        new_status = data['status']
        if new_status not in _VALID_CLUSTER_STATUSES:
            return response_api_error(
                f"status must be one of {', '.join(_VALID_CLUSTER_STATUSES)}")
        if new_status != cluster.status:
            if (new_status not in _TERMINAL_CLUSTER_STATUSES
                    and cluster.status in _TERMINAL_CLUSTER_STATUSES):
                # Reopening: a fresh ACTIVE cluster for the same fingerprint
                # may exist by now — the partial unique index forbids two.
                from app.business.alert_clustering import ACTIVE_CLUSTER_STATUSES
                rival = (AlertCluster.query
                         .filter(AlertCluster.correlation_fingerprint
                                 == cluster.correlation_fingerprint,
                                 AlertCluster.status.in_(ACTIVE_CLUSTER_STATUSES),
                                 AlertCluster.id != cluster.id).first())
                if rival is not None:
                    return response(409, data={
                        'reason': 'active_duplicate',
                        'message': f'Cluster #{rival.id} is already active for '
                                   f'this fingerprint — reopen that one instead.',
                        'cluster_id': rival.id,
                    })
            cluster.status = new_status
            if new_status in _TERMINAL_CLUSTER_STATUSES:
                cluster.closed_at = datetime.utcnow()
                cluster.closed_by = current_user.id
            else:
                # Reopening (open/investigating) clears the terminal stamp.
                cluster.closed_at = None
                cluster.closed_by = None
            changed.append(f'status={new_status}')

    if 'owner_id' in data:
        new_owner = data['owner_id']
        if new_owner is not None:
            from app.models.authorization import User
            if db.session.get(User, int(new_owner)) is None:
                return response_api_error('Unknown owner')
            new_owner = int(new_owner)
        if new_owner != cluster.owner_id:
            cluster.owner_id = new_owner
            changed.append('owner')
            if new_owner is not None:
                from app.business.notifications import notify
                notify('cluster_assigned', [new_owner],
                       f'Alert cluster #{cluster.id} "{cluster.title}" assigned to you',
                       object_type='alert_cluster', object_id=cluster.id,
                       url=f'/alert-clusters/{cluster.id}',
                       actor_id=current_user.id)

    if 'severity_override_id' in data:
        sid = data['severity_override_id']
        if sid is not None:
            from app.models.alerts import Severity
            if db.session.get(Severity, int(sid)) is None:
                return response_api_error('Unknown severity')
            sid = int(sid)
        cluster.severity_override_id = sid
        changed.append('severity')

    if 'summary' in data:
        s = data['summary']
        if s is not None and not isinstance(s, str):
            return response_api_error('summary must be a string')
        cluster.summary = s
        changed.append('summary')

    db.session.commit()
    if changed:
        track_activity(f"updated alert cluster #{cluster.id} "
                       f"({', '.join(changed)})", ctx_less=True)
    count = AlertClusterMember.query.filter_by(cluster_id=cluster.id).count()
    row = _cluster_row(cluster, count,
                       _member_severities([cluster.id]).get(cluster.id))
    row['summary'] = cluster.summary
    return response_api_success(row)


@alert_clusters_blueprint.route(
    '/alert-clusters/<int:cluster_id>/members/<int:alert_id>', methods=['DELETE'])
@ac_api_requires(Permissions.alerts_write)
def remove_cluster_member(cluster_id, alert_id):
    """v3 Alerts-tab trash: detach one alert from the cluster. The alert is
    untouched — only the membership row goes, freeing the alert to be
    clustered again by a future rule match."""
    cluster, err = _get_cluster_checked(cluster_id)
    if err is not None:
        return err
    member = AlertClusterMember.query.filter_by(
        cluster_id=cluster.id, alert_id=alert_id).first()
    if member is None:
        return response_api_not_found()
    db.session.delete(member)
    db.session.commit()
    track_activity(f'removed alert #{alert_id} from alert cluster #{cluster.id}',
                   ctx_less=True)
    return response_api_deleted()


@alert_clusters_blueprint.route('/alert-clusters/<int:cluster_id>/context',
                                methods=['GET'])
@ac_api_requires(Permissions.alerts_read)
def get_cluster_context(cluster_id):
    """One bulk payload feeding the Assets, IOCs, Correlation and Timeline
    tabs: the union of member-alert assets and IOCs plus the per-alert link
    pairs the graph draws its edges from. Two association-table queries —
    never per-alert loops."""
    from app.models.models import CompromiseStatus
    from app.models.models import alert_assets_association
    from app.models.models import alert_iocs_association
    from app.models.models import CaseAssets
    from app.models.models import Ioc

    cluster, err = _get_cluster_checked(cluster_id)
    if err is not None:
        return err

    member_ids = [m.alert_id for m in
                  AlertClusterMember.query.filter_by(cluster_id=cluster.id).all()]
    if not member_ids:
        return response_api_success({'assets': [], 'iocs': [],
                                     'links': {'assets': [], 'iocs': []}})

    asset_links = (db.session.query(alert_assets_association.c.alert_id,
                                    alert_assets_association.c.asset_id)
                   .filter(alert_assets_association.c.alert_id.in_(member_ids))
                   .all())
    ioc_links = (db.session.query(alert_iocs_association.c.alert_id,
                                  alert_iocs_association.c.ioc_id)
                 .filter(alert_iocs_association.c.alert_id.in_(member_ids))
                 .all())

    assets = CaseAssets.query.filter(
        CaseAssets.asset_id.in_({a for _, a in asset_links} or {0})).all()
    iocs = Ioc.query.filter(
        Ioc.ioc_id.in_({i for _, i in ioc_links} or {0})).all()

    def _compromise_name(status_id):
        try:
            return CompromiseStatus(status_id).name if status_id is not None else None
        except ValueError:
            return None

    # COALESCE BY IDENTITY: every alert mints its OWN Ioc/CaseAssets rows at
    # ingest (dedup only happens at case-merge time), so keying on raw ids
    # would render the same indicator once per alert and nothing would ever
    # be a correlation point. Identity mirrors the registry/case rules:
    # IOCs by (lower(value), type_id); assets by (lower(trim(name)),
    # type_id) — the Phase 4 identity, NO domain stripping. The first row
    # seen becomes canonical; links are remapped onto it.
    canon_ioc = {}
    ioc_alias = {}
    for i in iocs:
        key = ((i.ioc_value or '').lower(), i.ioc_type_id)
        if key not in canon_ioc:
            canon_ioc[key] = i
        ioc_alias[i.ioc_id] = canon_ioc[key].ioc_id

    canon_asset = {}
    asset_alias = {}
    for a in assets:
        key = ((a.asset_name or '').strip().lower(), a.asset_type_id)
        if key not in canon_asset:
            canon_asset[key] = a
        asset_alias[a.asset_id] = canon_asset[key].asset_id

    return response_api_success({
        'assets': [{
            'asset_id': a.asset_id,
            'name': a.asset_name,
            'type': a.asset_type.asset_name if a.asset_type else None,
            'ip': a.asset_ip,
            'domain': a.asset_domain,
            'compromise_status': _compromise_name(a.asset_compromise_status_id),
        } for a in canon_asset.values()],
        'iocs': [{
            'ioc_id': i.ioc_id,
            'value': i.ioc_value,
            'description': i.ioc_description,
            'type': i.ioc_type.type_name if i.ioc_type else None,
            'tlp': i.tlp.tlp_name if i.tlp else None,
            'tags': i.ioc_tags or '',
        } for i in canon_ioc.values()],
        'links': {
            'assets': sorted({(aid, asset_alias[sid])
                              for aid, sid in asset_links if sid in asset_alias}),
            'iocs': sorted({(aid, ioc_alias[iid])
                            for aid, iid in ioc_links if iid in ioc_alias}),
        },
    })


# -------------------------------------------- v3 parity: Activity comments

def _comment_row(cm) -> dict:
    return {
        'id': cm.id,
        'user_id': cm.user_id,
        'user_name': cm.user.name if cm.user else None,
        'content': cm.content,
        'created_at': _iso(cm.created_at),
    }


@alert_clusters_blueprint.route('/alert-clusters/<int:cluster_id>/comments',
                                methods=['GET'])
@ac_api_requires(Permissions.alerts_read)
def list_cluster_comments(cluster_id):
    from app.models.alerts import AlertClusterComment
    cluster, err = _get_cluster_checked(cluster_id)
    if err is not None:
        return err
    rows = (AlertClusterComment.query.filter_by(cluster_id=cluster.id)
            .order_by(AlertClusterComment.created_at.desc(),
                      AlertClusterComment.id.desc()).all())
    return response_api_success([_comment_row(c) for c in rows])


@alert_clusters_blueprint.route('/alert-clusters/<int:cluster_id>/comments',
                                methods=['POST'])
@ac_api_requires(Permissions.alerts_write)
def add_cluster_comment(cluster_id):
    from app.models.alerts import AlertClusterComment
    from app.models.authorization import User

    cluster, err = _get_cluster_checked(cluster_id)
    if err is not None:
        return err
    content = ((request.get_json(silent=True) or {}).get('content') or '').strip()
    if not content:
        return response_api_error('Comment content is required')

    comment = AlertClusterComment(cluster_id=cluster.id,
                                  user_id=current_user.id, content=content)
    db.session.add(comment)
    db.session.commit()
    track_activity(f'commented on alert cluster #{cluster.id}', ctx_less=True)

    # @mentions notify like every other comment surface — bounded to users
    # who can actually see this cluster's customer (mentions must not leak
    # activity across the tenant boundary). Small-instance O(users) scan.
    try:
        from app.business.notifications import notify_mentions
        allowed = [u.id for u in User.query.filter(User.active.is_(True)).all()
                   if user_has_client_access(u.id, cluster.customer_id)]
        notify_mentions(content,
                        f'You are mentioned on alert cluster #{cluster.id}',
                        object_type='alert_cluster', object_id=cluster.id,
                        url=f'/alert-clusters/{cluster.id}',
                        actor_id=current_user.id, allowed_user_ids=allowed)
    except Exception:
        pass  # fail-soft: the comment write must survive notify internals

    return response_api_created(_comment_row(comment))


# ------------------------------------------- v3 parity: escalate or merge

@alert_clusters_blueprint.route('/alert-clusters/<int:cluster_id>/escalate',
                                methods=['POST'])
@ac_api_requires(Permissions.alerts_write)
def escalate_alert_cluster(cluster_id):
    """The v3 'Escalate or merge…' action, on the WHOLE cluster.

    mode='new_case': one case from every member alert via the same
    create_case_from_alerts path as /alerts/batch/escalate.
    mode='merge': every member merged into target_case_id via
    merge_alert_in_case — the same code path as /alerts/batch/merge.

    Defaults import ALL member IOCs/assets (escalating a cluster means
    escalating its evidence; explicit uuid lists still narrow it). Either
    way the cluster records provenance (escalated_case_id) and closes.
    """
    from app.datamgmt.alerts.alerts_db import create_case_from_alerts
    from app.datamgmt.alerts.alerts_db import merge_alert_in_case
    from app.datamgmt.case.case_db import get_case
    from app.datamgmt.manage.manage_access_control_db import check_ua_case_client
    from app.iris_engine.access_control.utils import ac_set_new_case_access
    from app.iris_engine.module_handler.module_handler import call_modules_hook
    from app.models.alerts import AlertStatus
    from app.util import add_obj_history_entry

    cluster, err = _get_cluster_checked(cluster_id)
    if err is not None:
        return err
    if cluster.escalated_case_id is not None:
        return response(409, data={
            'reason': 'already_escalated',
            'message': f'Cluster already escalated to case '
                       f'#{cluster.escalated_case_id}.',
            'case_id': cluster.escalated_case_id,
        })

    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'new_case')
    if mode not in ('new_case', 'merge'):
        return response_api_error("mode must be 'new_case' or 'merge'")

    members = (db.session.query(Alert)
               .join(AlertClusterMember,
                     AlertClusterMember.alert_id == Alert.alert_id)
               .filter(AlertClusterMember.cluster_id == cluster.id)
               .order_by(Alert.alert_id.asc()).all())
    if not members:
        return response_api_error('Cluster has no member alerts')

    iocs_list = data.get('iocs_import_list')
    assets_list = data.get('assets_import_list')
    if iocs_list is None:
        iocs_list = [str(i.ioc_uuid) for a in members for i in (a.iocs or [])]
    if assets_list is None:
        assets_list = [str(s.asset_uuid) for a in members for s in (a.assets or [])]
    note = data.get('note')
    import_as_event = bool(data.get('import_as_event', True))
    case_tags = data.get('case_tags') or ''

    if mode == 'merge':
        target_case_id = data.get('target_case_id')
        if not target_case_id:
            return response_api_error('target_case_id is required for merge')
        case = get_case(target_case_id)
        if case is None:
            return response_api_error('Target case not found')
        if not check_ua_case_client(current_user.id, target_case_id):
            return response_api_error('User not entitled to merge into this case')
        merged_status = AlertStatus.query.filter_by(status_name='Merged').first()
        for alert in members:
            alert.alert_status_id = merged_status.status_id
            merge_alert_in_case(alert, case, iocs_list=iocs_list,
                                assets_list=assets_list, note=None,
                                import_as_event=import_as_event,
                                case_tags=case_tags)
            add_obj_history_entry(
                alert, f'Alert merged into case #{case.case_id} '
                       f'with alert cluster #{cluster.id}')
            call_modules_hook('on_postload_alert_merge', data=alert,
                              caseid=case.case_id)
        if note:
            case.description += f'\n\n### Escalation note\n\n{note}\n\n'
        action = 'merged into'
    else:
        merged_status = AlertStatus.query.filter_by(status_name='Merged').first()
        for alert in members:
            alert.alert_status_id = merged_status.status_id
            call_modules_hook('on_postload_alert_escalate', data=alert)
        case = create_case_from_alerts(
            members, iocs_list=iocs_list, assets_list=assets_list,
            note=note, import_as_event=import_as_event, case_tags=case_tags,
            case_title=data.get('case_title') or cluster.title,
            template_id=data.get('case_template_id'))
        if not case:
            return response_api_error('Failed to create case from cluster')
        ac_set_new_case_access(None, case.case_id, case.client_id)
        case = call_modules_hook('on_postload_case_create', data=case)
        add_obj_history_entry(case, 'created')
        for alert in members:
            add_obj_history_entry(
                alert, f'Alert escalated to case #{case.case_id} '
                       f'with alert cluster #{cluster.id}')
        action = 'escalated to'

    cluster.escalated_case_id = case.case_id
    if cluster.status not in _TERMINAL_CLUSTER_STATUSES:
        cluster.status = 'escalated'
        cluster.closed_at = datetime.utcnow()
        cluster.closed_by = current_user.id
    db.session.commit()
    track_activity(f'alert cluster #{cluster.id} {action} case #{case.case_id}',
                   ctx_less=True)
    return response_api_success({
        'case_id': case.case_id,
        'case_name': case.name,
        'mode': mode,
        'alerts_processed': len(members),
    })


# ------------------------------------------------------------------ AI triage

@alert_clusters_blueprint.route('/alert-clusters/<int:cluster_id>/triage', methods=['GET'])
@ac_api_requires(Permissions.alerts_read)
def get_cluster_triage(cluster_id):
    from app.iris_engine.ai.alert_cluster_triage import artifact_to_result
    from app.iris_engine.ai.alert_cluster_triage import get_latest_triage
    cluster, err = _get_cluster_checked(cluster_id)
    if err is not None:
        return err
    art = get_latest_triage(cluster.id)
    if art is None:
        return response_api_not_found()
    return response_api_success(artifact_to_result(art, cached=True))


@alert_clusters_blueprint.route('/alert-clusters/<int:cluster_id>/triage', methods=['POST'])
@ac_api_requires(Permissions.alerts_write)
def generate_cluster_triage_endpoint(cluster_id):
    """Generate the triage narrative. Async by default (202 + task_id, poll
    /api/v2/ai/jobs/<task_id>); ?sync=true runs inline for scripts.

    The manual-edit 409 guard lives HERE (not in the orchestrator) so every
    caller — async queue, scripts, API clients — passes through it: a new
    generation inserts a new row and reads take the newest, so an unguarded
    regen would silently orphan the analyst's edit.
    """
    from app.iris_engine.ai.alert_cluster_triage import ClusterTriageError
    from app.iris_engine.ai.alert_cluster_triage import generate_cluster_triage
    from app.iris_engine.ai.alert_cluster_triage import get_latest_triage

    cluster, err = _get_cluster_checked(cluster_id)
    if err is not None:
        return err

    data = request.get_json(silent=True) or {}
    force = bool(data.get('force', False))
    discard_edit = bool(data.get('discard_edit', False))

    latest = get_latest_triage(cluster.id)
    if latest is not None and latest.is_edited and not discard_edit:
        return response(409, data={
            'reason': 'manual_edit_present',
            'message': 'A manual edit exists on this triage. Pass discard_edit '
                       'to regenerate over it.',
            'artifact_id': latest.id,
        })

    if request.args.get('sync') == 'true':
        try:
            return response_api_success(generate_cluster_triage(cluster.id, force=force))
        except ClusterTriageError as e:
            return response_api_error(str(e))

    from app.iris_engine.ai.ai_jobs import enqueue_ai_job
    job = enqueue_ai_job(feature='alert_cluster_triage', case_id=None,
                         user_id=current_user.id,
                         params={'cluster_id': cluster.id, 'force': force})
    return response(202, data={'task_id': job.task_id, 'state': 'queued'})


@alert_clusters_blueprint.route('/alert-clusters/<int:cluster_id>/triage', methods=['PUT'])
@ac_api_requires(Permissions.alerts_write)
def edit_cluster_triage(cluster_id):
    from app.iris_engine.ai.alert_cluster_triage import ClusterTriageEditError
    from app.iris_engine.ai.alert_cluster_triage import artifact_to_result
    from app.iris_engine.ai.alert_cluster_triage import save_triage_edit
    cluster, err = _get_cluster_checked(cluster_id)
    if err is not None:
        return err
    data = request.get_json() or {}
    try:
        art = save_triage_edit(cluster.id, data.get('suggested_name', ''),
                               data.get('narrative', ''), current_user.id)
    except ClusterTriageEditError as e:
        return response_api_error(str(e))
    track_activity(f'edited AI triage of alert cluster #{cluster.id}', ctx_less=True)
    return response_api_success(artifact_to_result(art, cached=True))


@alert_clusters_blueprint.route('/alert-clusters/<int:cluster_id>/triage/revert',
                                methods=['POST'])
@ac_api_requires(Permissions.alerts_write)
def revert_cluster_triage(cluster_id):
    from app.iris_engine.ai.alert_cluster_triage import ClusterTriageEditError
    from app.iris_engine.ai.alert_cluster_triage import artifact_to_result
    from app.iris_engine.ai.alert_cluster_triage import revert_triage_edit
    cluster, err = _get_cluster_checked(cluster_id)
    if err is not None:
        return err
    try:
        art = revert_triage_edit(cluster.id)
    except ClusterTriageEditError as e:
        return response_api_error(str(e))
    track_activity(f'reverted AI triage edit of alert cluster #{cluster.id}', ctx_less=True)
    return response_api_success(artifact_to_result(art, cached=True))

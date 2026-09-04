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

"""Investigation Flows REST surface (iris-ng v2, Phase 3).

Flow DEFINITIONS are server_administrator (instance-wide config); reading
checklists is alerts_read and ticking steps is alerts_write, both scoped by
user_has_client_access on the anchor's customer. Cross-tenant reads return
404, not 403 (existence is data — same rule as alert clusters).

Steps on PUT are MERGED BY ID, not replaced: a blind replace would
cascade-drop analyst step states on every flow edit. Incoming steps with an
`id` update that step in place (states survive); steps without an id are
created; existing steps missing from the payload are deleted (their states
go with them — that part IS the analyst-visible cost of removing a step,
called out in the settings UI). step_order is assigned from list position
in two phases (negative then final) because UNIQUE(flow_id, step_order) is
non-deferrable and a swap would collide mid-update.
"""

import marshmallow
from datetime import datetime

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
from app.business.condition_eval import build_alert_view
from app.business.condition_eval import evaluate_tree
from app.business.condition_eval import validate_tree
from app.business.investigation_flows import attachments_for_alert
from app.business.investigation_flows import attachments_for_cluster
from app.business.investigation_flows import serialize_attachment
from app.business.investigation_flows import set_step_state
from app.business.investigation_flows import task_deploy_flows
from app.datamgmt.manage.manage_access_control_db import user_has_client_access
from app.iris_engine.utils.tracker import track_activity
from app.models.alerts import Alert
from app.models.alerts import AlertCluster
from app.models.alerts import FlowAttachment
from app.models.alerts import FlowStep
from app.models.alerts import InvestigationFlow
from app.models.authorization import Permissions
from app.schema.marshables import InvestigationFlowSchema

flows_blueprint = Blueprint('flows_rest_v2', __name__)


def _dump_flow(flow: InvestigationFlow) -> dict:
    data = InvestigationFlowSchema().dump(flow)
    data['steps'] = [{
        'id': s.id,
        'order': s.step_order,
        'title': s.title,
        'description': s.description,
        'is_required': s.is_required,
    } for s in flow.steps]
    return data


def _validate_steps_payload(steps):
    """Returns (cleaned, problems). Each step: title required; optional id,
    description, is_required. Order comes from list position."""
    if steps is None:
        return None, []
    if not isinstance(steps, list):
        return None, ['steps must be a list']
    problems = []
    cleaned = []
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            problems.append(f'step #{i + 1} must be an object')
            continue
        title = (s.get('title') or '').strip()
        if not title:
            problems.append(f'step #{i + 1}: title is required')
            continue
        cleaned.append({
            'id': s.get('id'),
            'title': title,
            'description': (s.get('description') or None),
            'is_required': bool(s.get('is_required', False)),
        })
    return cleaned, problems


def _merge_steps(flow: InvestigationFlow, cleaned: list):
    """Merge-by-id (see module docstring). Two-phase step_order assignment
    around the non-deferrable UNIQUE."""
    existing = {s.id: s for s in flow.steps}
    incoming_ids = {s['id'] for s in cleaned if s.get('id') is not None}

    for sid, step in list(existing.items()):
        if sid not in incoming_ids:
            db.session.delete(step)

    # Phase 1: park orders in negative space to avoid UNIQUE collisions.
    for step in flow.steps:
        step.step_order = -step.step_order
    db.session.flush()

    # Phase 2: apply the incoming list order.
    for i, s in enumerate(cleaned):
        order = i + 1
        if s.get('id') is not None and s['id'] in existing:
            step = existing[s['id']]
            step.step_order = order
            step.title = s['title']
            step.description = s['description']
            step.is_required = s['is_required']
        else:
            db.session.add(FlowStep(flow_id=flow.id, step_order=order,
                                    title=s['title'], description=s['description'],
                                    is_required=s['is_required']))
    db.session.flush()


# ------------------------------------------------------------ flow definitions

@flows_blueprint.route('/investigation-flows', methods=['GET'])
@ac_api_requires(Permissions.server_administrator)
def list_flows():
    flows = (InvestigationFlow.query
             .order_by(InvestigationFlow.priority.asc(), InvestigationFlow.id.asc())
             .all())
    return response_api_success([_dump_flow(f) for f in flows])


@flows_blueprint.route('/investigation-flows', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def create_flow():
    data = request.get_json() or {}
    steps = data.pop('steps', None)
    cleaned, problems = _validate_steps_payload(steps)
    if problems:
        return response_api_error('Data error', data=problems)
    try:
        flow = InvestigationFlowSchema().load(data)
    except marshmallow.exceptions.ValidationError as e:
        return response_api_error('Data error', data=e.messages)
    flow.created_by = current_user.id
    db.session.add(flow)
    db.session.flush()
    if cleaned:
        _merge_steps(flow, cleaned)
    db.session.commit()
    track_activity(f"created investigation flow '{flow.name}'", ctx_less=True)
    return response_api_created(_dump_flow(flow))


@flows_blueprint.route('/investigation-flows/<int:flow_id>', methods=['GET'])
@ac_api_requires(Permissions.server_administrator)
def get_flow(flow_id):
    flow = db.session.get(InvestigationFlow, flow_id)
    if flow is None:
        return response_api_not_found()
    return response_api_success(_dump_flow(flow))


@flows_blueprint.route('/investigation-flows/<int:flow_id>', methods=['PUT'])
@ac_api_requires(Permissions.server_administrator)
def update_flow(flow_id):
    flow = db.session.get(InvestigationFlow, flow_id)
    if flow is None:
        return response_api_not_found()
    data = request.get_json() or {}
    steps = data.pop('steps', None)
    cleaned, problems = _validate_steps_payload(steps)
    if problems:
        return response_api_error('Data error', data=problems)
    try:
        flow = InvestigationFlowSchema().load(data, instance=flow, partial=True)
    except marshmallow.exceptions.ValidationError as e:
        return response_api_error('Data error', data=e.messages)
    if cleaned is not None:
        _merge_steps(flow, cleaned)
    flow.updated_at = datetime.utcnow()
    db.session.commit()
    track_activity(f"updated investigation flow '{flow.name}'", ctx_less=True)
    return response_api_success(_dump_flow(flow))


@flows_blueprint.route('/investigation-flows/<int:flow_id>', methods=['DELETE'])
@ac_api_requires(Permissions.server_administrator)
def delete_flow(flow_id):
    flow = db.session.get(InvestigationFlow, flow_id)
    if flow is None:
        return response_api_not_found()
    name = flow.name
    # CASCADE removes attachments + states: deleting a flow deletes its
    # checklists everywhere (deliberate — an orphan checklist with no
    # definition cannot be rendered).
    db.session.delete(flow)
    db.session.commit()
    track_activity(f"deleted investigation flow '{name}'", ctx_less=True)
    return response_api_deleted()


@flows_blueprint.route('/investigation-flows/test', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def test_flow():
    """Dry-run the condition tree against alert_ids or the newest last_n
    alerts. Same shape as the clustering-rule test."""
    data = request.get_json() or {}
    conditions = data.get('conditions')
    if data.get('flow_id') is not None:
        flow = db.session.get(InvestigationFlow, data['flow_id'])
        if flow is None:
            return response_api_not_found()
        if conditions is None:
            conditions = flow.match_conditions

    problems = validate_tree(conditions)
    if problems:
        return response_api_error('Invalid condition tree', data=problems)

    if data.get('alert_ids'):
        alerts = (Alert.query
                  .filter(Alert.alert_id.in_(list(data['alert_ids'])[:200])).all())
    else:
        last_n = min(int(data.get('last_n', 20) or 20), 200)
        alerts = (Alert.query
                  .order_by(Alert.alert_creation_time.desc(), Alert.alert_id.desc())
                  .limit(last_n).all())

    results = [{'alert_id': a.alert_id, 'title': a.alert_title,
                'matches': evaluate_tree(conditions, build_alert_view(a))}
               for a in alerts]
    return response_api_success({
        'evaluated': len(results),
        'matched': sum(1 for r in results if r['matches']),
        'results': results,
    })


@flows_blueprint.route('/investigation-flows/deploy', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def deploy_flows_endpoint():
    data = request.get_json(silent=True) or {}
    flow_id = data.get('flow_id')
    task = task_deploy_flows.delay(flow_id)
    track_activity('started investigation-flow deploy', ctx_less=True)
    return response(202, data={'task_id': task.id, 'state': 'queued'})


# ------------------------------------------------------------------ checklists

def _alert_checked(alert_id):
    alert = db.session.get(Alert, alert_id)
    if alert is None:
        return None, response_api_not_found()
    if not user_has_client_access(current_user.id, alert.alert_customer_id):
        return None, response_api_not_found()
    return alert, None


def _cluster_checked(cluster_id):
    cluster = db.session.get(AlertCluster, cluster_id)
    if cluster is None:
        return None, response_api_not_found()
    if not user_has_client_access(current_user.id, cluster.customer_id):
        return None, response_api_not_found()
    return cluster, None


@flows_blueprint.route('/alerts/<int:alert_id>/flows', methods=['GET'])
@ac_api_requires(Permissions.alerts_read)
def get_alert_flows(alert_id):
    alert, err = _alert_checked(alert_id)
    if err is not None:
        return err
    return response_api_success(attachments_for_alert(alert.alert_id))


@flows_blueprint.route('/alert-clusters/<int:cluster_id>/flows', methods=['GET'])
@ac_api_requires(Permissions.alerts_read)
def get_cluster_flows(cluster_id):
    cluster, err = _cluster_checked(cluster_id)
    if err is not None:
        return err
    return response_api_success(attachments_for_cluster(cluster.id))


@flows_blueprint.route('/flow-attachments/<int:attachment_id>/steps/<int:step_id>',
                       methods=['PUT'])
@ac_api_requires(Permissions.alerts_write)
def put_step_state(attachment_id, step_id):
    att = db.session.get(FlowAttachment, attachment_id)
    if att is None:
        return response_api_not_found()
    # Tenant check through whichever anchor the attachment carries.
    if att.alert_id is not None:
        _, err = _alert_checked(att.alert_id)
    else:
        _, err = _cluster_checked(att.cluster_id)
    if err is not None:
        return err

    data = request.get_json() or {}
    try:
        set_step_state(att, step_id, data.get('state', ''), current_user.id,
                       note=data.get('note'))
    except ValueError as e:
        return response_api_error(str(e))
    return response_api_success(serialize_attachment(att))

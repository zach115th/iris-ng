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

"""War rooms REST surface (iris-ng v2, Phase 6).

Access model: room visibility = membership (server_administrator sees all,
elevated to lead). A NON-member gets 404 on every room route — room existence
is data. A member with an insufficient role gets a 400 with the reason.
No new permission bits (project rule); roles are row-level.

Case attach requires the ACTOR to have access to that case; the room stream
filters case activity per VIEWER by case ACL (membership does not grant case
access — v1 decision).
"""

import json

from flask import Blueprint
from flask import Response
from flask import request
from flask_login import current_user

from app import db
from app.blueprints.access_controls import ac_api_requires
from app.blueprints.rest.endpoints import response
from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
from app.business.errors import BusinessProcessingError
from app.business.war_rooms import ClusterAlreadyPromoted
from app.business.war_rooms import add_member
from app.business.war_rooms import add_message
from app.business.war_rooms import set_room_status
from app.business.war_rooms import promote_cluster_to_room
from app.business.war_rooms import attach_case
from app.business.war_rooms import create_room
from app.business.war_rooms import delete_room
from app.business.war_rooms import create_sitrep
from app.business.war_rooms import delete_sitrep
from app.business.war_rooms import detach_case
from app.business.war_rooms import get_room
from app.business.war_rooms import get_sitrep
from app.business.war_rooms import list_messages
from app.business.war_rooms import list_sitreps
from app.business.war_rooms import publish_sitrep
from app.business.war_rooms import sitrep_revisions
from app.business.war_rooms import update_sitrep
from app.business.war_rooms import remove_member
from app.business.war_rooms import role_at_least
from app.business.war_rooms import room_stream
from app.business.war_rooms import rooms_for_user
from app.business.war_rooms import set_member_role
from app.business.war_rooms import update_room
from app.business.war_rooms import user_room_role
from app.iris_engine.access_control.utils import ac_current_user_has_permission
from app.iris_engine.access_control.utils import ac_fast_check_user_has_case_access
from app.iris_engine.access_control.utils import ac_get_fast_user_cases_access
from app.models.authorization import CaseAccessLevel
from app.models.authorization import Permissions
from app.models.cases import Cases
from app.iris_engine.utils.tracker import track_activity
from app.models.models import WarRoom
from app.models.models import WarRoomCaseLink
from app.models.models import WarRoomMember

war_rooms_blueprint = Blueprint('rest_v2_war_rooms', __name__)


def _iso(dt):
    if dt is None:
        return None
    return dt.isoformat() + ('Z' if dt.tzinfo is None else '')


def _resolve(room_id, min_role):
    """(room, effective_role, error_response). Non-members 404 — existence is
    data; members below min_role get a 400 with the reason (the v2 error
    helper is 400-only by design)."""
    room = get_room(room_id)
    if room is None:
        return None, None, response_api_not_found()
    role = user_room_role(room_id, current_user.id)
    if role is None:
        if ac_current_user_has_permission(Permissions.server_administrator):
            role = 'lead'
        else:
            return None, None, response_api_not_found()
    if not role_at_least(role, min_role):
        return None, None, response_api_error('Insufficient room role')
    return room, role, None


def _room_row(room, role=None):
    return {
        'id': room.id, 'uuid': str(room.room_uuid), 'name': room.name,
        'description': room.description, 'summary': room.summary,
        'status': room.status, 'severity': room.severity,
        'source_cluster_id': room.source_cluster_id,
        'campaign_tag': room.campaign_tag,
        'created_by': room.created_by,
        'created_by_name': room.creator.name if room.creator else None,
        'created_at': _iso(room.created_at),
        'archived_at': _iso(room.archived_at),
        'my_role': role,
        'member_count': WarRoomMember.query.filter_by(room_id=room.id).count(),
        'case_count': WarRoomCaseLink.query.filter_by(room_id=room.id).count(),
    }


def _member_row(m):
    return {
        'user_id': m.user_id,
        'user_name': m.user.name if m.user else 'deleted user',
        'user_login': m.user.user if m.user else None,
        'role': m.role, 'added_at': _iso(m.added_at),
    }


def _message_row(m):
    return {
        'id': m.id, 'user_id': m.user_id,
        'user_name': m.user.name if m.user else 'deleted user',
        'content': m.content, 'created_at': _iso(m.created_at),
        'topic': m.topic, 'msg_kind': m.kind, 'parent_id': m.parent_id,
        'thread_title': m.thread_title, 'pinned': m.pinned,
    }


# ------------------------------------------------------------------- rooms

@war_rooms_blueprint.route('/war-rooms', methods=['GET'])
@ac_api_requires()
def list_war_rooms():
    # Every status is returned; the page filters client-side via the v3
    # chips (All / Open / Active / Standby / Closed).
    all_rooms = ac_current_user_has_permission(Permissions.server_administrator)
    rows = rooms_for_user(current_user.id, all_rooms=all_rooms)
    return response_api_success({
        'rooms': [_room_row(room, role) for room, role in rows],
    })


@war_rooms_blueprint.route('/war-rooms', methods=['POST'])
@ac_api_requires()
def create_war_room():
    data = request.get_json(silent=True) or {}
    try:
        room = create_room(data.get('name'), data.get('description'),
                           current_user.id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success(_room_row(room, 'lead'))


@war_rooms_blueprint.route('/war-rooms/<int:room_id>', methods=['GET'])
@ac_api_requires()
def get_war_room(room_id):
    room, role, err = _resolve(room_id, 'observer')
    if err:
        return err
    out = _room_row(room, role)
    out['viewer_id'] = current_user.id
    out['members'] = [_member_row(m) for m in
                      WarRoomMember.query.filter_by(room_id=room.id).all()]
    out['cases'] = _case_rows(room)
    return response_api_success(out)


@war_rooms_blueprint.route('/war-rooms/<int:room_id>', methods=['PUT'])
@ac_api_requires()
def update_war_room(room_id):
    room, role, err = _resolve(room_id, 'lead')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        update_room(room, name=data.get('name'),
                    description=data.get('description'),
                    summary=data.get('summary'),
                    severity=data.get('severity'))
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success(_room_row(room, role))


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/status', methods=['POST'])
@ac_api_requires()
def set_war_room_status(room_id):
    """Lead sets the room status (open/active/standby/closed — the v3
    four-state model). Closing is the read-only state and frees a promoted
    cluster for re-promotion."""
    room, role, err = _resolve(room_id, 'lead')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        set_room_status(room, data.get('status'))
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success(_room_row(room, role))


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/delete', methods=['POST'])
@ac_api_requires()
def delete_war_room(room_id):
    """Lead-only hard delete for an accidentally created room. Deliberately
    works on a CLOSED room too — the closed-room write guard protects room
    CONTENT, and an accidental room may already have been closed. Everything
    hanging off the room cascades; linked cases are untouched; a promoted
    cluster is freed for re-promotion. See business delete_room."""
    room, role, err = _resolve(room_id, 'lead')
    if err:
        return err
    name, rid = room.name, room.id
    delete_room(room)
    track_activity(f"war room '{name}' (#{rid}) deleted", ctx_less=True)
    return response_api_success({'deleted': rid})


# -------------------------------------------------- discovery promote

def _parse_iso_date(value):
    if not value:
        return None
    from datetime import datetime as _dt
    try:
        return _dt.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@war_rooms_blueprint.route('/war-rooms/promote-cluster', methods=['POST'])
@ac_api_requires()
def promote_cluster():
    """Promote a computed correlation cluster into a war room — explicit
    click only, never automatic (user rule). The report is recomputed
    server-side under the ACTOR's ACL, so a client cannot smuggle case ids;
    a second promote of the same cluster 409s with the existing room."""
    data = request.get_json(silent=True) or {}
    cluster_id = (data.get('cluster_id') or '').strip()
    if not cluster_id:
        return response_api_error('cluster_id is required')
    try:
        min_shared = int(data.get('min_shared') or 2)
    except (TypeError, ValueError):
        min_shared = 2
    try:
        room = promote_cluster_to_room(
            cluster_id, current_user.id, min_shared=min_shared,
            start_date=_parse_iso_date(data.get('start_date')),
            end_date=_parse_iso_date(data.get('end_date')))
    except ClusterAlreadyPromoted as e:
        return response(409, data={
            'reason': 'already_promoted',
            'room_id': e.room.id,
            'message': f'Cluster {cluster_id} was already promoted to war '
                       f'room #{e.room.id}.',
        })
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    track_activity(f'promoted correlation cluster {cluster_id} to war room '
                   f'#{room.id}', ctx_less=True)
    return response_api_success(_room_row(room, 'lead'))


@war_rooms_blueprint.route('/war-rooms/promoted-clusters', methods=['GET'])
@ac_api_requires()
def promoted_clusters():
    """{cluster_id: room_id} for ACTIVE promoted rooms — lets the Discovery
    panel mark clusters that already have a room. Exposes only the room id;
    a non-member still 404s on the room itself."""
    rows = WarRoom.query.filter(
        WarRoom.source_cluster_id.isnot(None),
        WarRoom.status != 'closed').all()
    return response_api_success({
        'promoted': {r.source_cluster_id: r.id for r in rows}})


# ----------------------------------------------------------------- members

@war_rooms_blueprint.route('/war-rooms/<int:room_id>/members', methods=['GET'])
@ac_api_requires()
def list_war_room_members(room_id):
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    members = WarRoomMember.query.filter_by(room_id=room.id).all()
    return response_api_success({'members': [_member_row(m) for m in members]})


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/members', methods=['POST'])
@ac_api_requires()
def add_war_room_member(room_id):
    room, _, err = _resolve(room_id, 'lead')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        member = add_member(room, int(data.get('user_id') or 0),
                            data.get('role') or 'responder', current_user.id)
    except (BusinessProcessingError, ValueError, TypeError) as e:
        return response_api_error(str(e))
    return response_api_success(_member_row(member))


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/members/<int:user_id>',
                           methods=['PUT'])
@ac_api_requires()
def set_war_room_member_role(room_id, user_id):
    room, _, err = _resolve(room_id, 'lead')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        member = set_member_role(room, user_id, data.get('role'))
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success(_member_row(member))


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/members/<int:user_id>',
                           methods=['DELETE'])
@ac_api_requires()
def remove_war_room_member(room_id, user_id):
    # Self-leave needs only membership; removing someone else needs lead.
    min_role = 'observer' if user_id == current_user.id else 'lead'
    room, _, err = _resolve(room_id, min_role)
    if err:
        return err
    try:
        remove_member(room, user_id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'removed': user_id})


# ------------------------------------------------------------------- teams

@war_rooms_blueprint.route('/war-rooms/<int:room_id>/teams', methods=['GET'])
@ac_api_requires()
def list_war_room_teams(room_id):
    from app.business.war_rooms import list_teams
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    return response_api_success({'teams': list_teams(room)})


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/teams', methods=['POST'])
@ac_api_requires()
def create_war_room_team(room_id):
    from app.business.war_rooms import create_team
    from app.business.war_rooms import list_teams
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        create_team(room, data.get('name'), current_user.id,
                    description=data.get('description'),
                    color=data.get('color'))
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'teams': list_teams(room)})


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/teams/<int:team_id>',
                           methods=['DELETE'])
@ac_api_requires()
def delete_war_room_team(room_id, team_id):
    from app.business.war_rooms import delete_team
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    try:
        delete_team(room, team_id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'deleted': team_id})


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/teams/<int:team_id>/members', methods=['POST'])
@ac_api_requires()
def add_war_room_team_member(room_id, team_id):
    from app.business.war_rooms import add_team_member
    from app.business.war_rooms import list_teams
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        add_team_member(room, team_id, int(data.get('user_id') or 0))
    except (ValueError, TypeError):
        return response_api_error('Invalid user_id')
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'teams': list_teams(room)})


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/teams/<int:team_id>/members/<int:user_id>',
    methods=['DELETE'])
@ac_api_requires()
def remove_war_room_team_member(room_id, team_id, user_id):
    from app.business.war_rooms import list_teams
    from app.business.war_rooms import remove_team_member
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    try:
        remove_team_member(room, team_id, user_id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'teams': list_teams(room)})


# ------------------------------------------------------------------- cases

def _case_rows(room):
    """Attached cases. All members see id/name/client (a shared workspace
    names its cases by design); `accessible` marks whether THIS viewer can
    open it — deep links, stream activity, and the ENRICHED fields (state,
    owner, task counts) stay ACL-bound."""
    from sqlalchemy import func
    from app.models.models import CaseTasks
    from app.models.models import TaskStatus
    acl = set(ac_get_fast_user_cases_access(current_user.id) or [])
    links = (db.session.query(WarRoomCaseLink, Cases)
             .join(Cases, Cases.case_id == WarRoomCaseLink.case_id)
             .filter(WarRoomCaseLink.room_id == room.id).all())
    vis = [c.case_id for _, c in links if c.case_id in acl]
    totals, opens = {}, {}
    if vis:
        rows = (db.session.query(
                    CaseTasks.task_case_id, TaskStatus.status_name,
                    func.count())
                .outerjoin(TaskStatus,
                           CaseTasks.task_status_id == TaskStatus.id)
                .filter(CaseTasks.task_case_id.in_(vis))
                .group_by(CaseTasks.task_case_id,
                          TaskStatus.status_name).all())
        for cid, status_name, n in rows:
            totals[cid] = totals.get(cid, 0) + n
            if status_name not in ('Done', 'Canceled'):
                opens[cid] = opens.get(cid, 0) + n
    out = []
    for link, c in links:
        acc = c.case_id in acl
        row = {
            'case_id': c.case_id, 'case_name': c.name,
            'client_name': c.client.name if c.client else None,
            'closed': c.close_date is not None,
            'added_at': _iso(link.added_at),
            'accessible': acc,
            'note': link.note,
        }
        if acc:
            row.update({
                'state_name': c.state.state_name if c.state else None,
                'owner_name': c.owner.name if c.owner else None,
                'open_date': c.open_date.isoformat() if c.open_date else None,
                'tasks_total': totals.get(c.case_id, 0),
                'tasks_open': opens.get(c.case_id, 0),
            })
        out.append(row)
    return out


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/cases', methods=['GET'])
@ac_api_requires()
def list_war_room_cases(room_id):
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    return response_api_success({'cases': _case_rows(room)})


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/cases', methods=['POST'])
@ac_api_requires()
def attach_war_room_case(room_id):
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        case_id = int(data.get('case_id') or 0)
    except (ValueError, TypeError):
        return response_api_error('Invalid case_id')
    # The case must exist AND the actor must be able to see it — a server
    # admin's access check short-circuits True for ANY id, including ids
    # that do not exist, so existence is checked explicitly first.
    if db.session.get(Cases, case_id) is None:
        return response_api_not_found()
    if not ac_fast_check_user_has_case_access(
            current_user.id, case_id,
            [CaseAccessLevel.read_only, CaseAccessLevel.full_access]):
        return response_api_not_found()
    try:
        attach_case(room, case_id, current_user.id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'cases': _case_rows(room)})


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/cases/<int:case_id>/note', methods=['PUT'])
@ac_api_requires()
def set_war_room_case_note(room_id, case_id):
    from app.business.war_rooms import set_case_link_note
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        link = set_case_link_note(room, case_id, data.get('note'))
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'case_id': case_id, 'note': link.note})


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/cases/<int:case_id>/peek', methods=['GET'])
@ac_api_requires()
def peek_war_room_case(room_id, case_id):
    from app.business.war_rooms import case_peek
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    try:
        out = case_peek(room, current_user.id, case_id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    out['open_date'] = out['open_date'].isoformat() if out['open_date'] else None
    out['close_date'] = (out['close_date'].isoformat()
                         if out['close_date'] else None)
    return response_api_success(out)


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/cases/<int:case_id>',
                           methods=['DELETE'])
@ac_api_requires()
def detach_war_room_case(room_id, case_id):
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    try:
        detach_case(room, case_id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'removed': case_id})


# ---------------------------------------------------------------- messages

@war_rooms_blueprint.route('/war-rooms/<int:room_id>/messages', methods=['GET'])
@ac_api_requires()
def list_war_room_messages(room_id):
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    msgs = list_messages(room, before_id=request.args.get('before_id'),
                         limit=request.args.get('limit', 50))
    return response_api_success({'messages': [_message_row(m) for m in msgs]})


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/messages', methods=['POST'])
@ac_api_requires()
def post_war_room_message(room_id):
    """Post to the stream. Optional chat-machinery fields: topic, kind
    (message|note|decision), parent_id (reply — anchors to the thread
    root), thread_title (names a new thread), pinned."""
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        msg = add_message(room, current_user.id, data.get('content'),
                          topic=data.get('topic') or 'main',
                          kind=data.get('kind') or 'message',
                          parent_id=data.get('parent_id'),
                          thread_title=data.get('thread_title'),
                          pinned=bool(data.get('pinned')))
    except (BusinessProcessingError, ValueError, TypeError) as e:
        return response_api_error(str(e))
    return response_api_success(_message_row(msg))


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/messages/<int:message_id>/pin',
    methods=['POST'])
@ac_api_requires()
def pin_war_room_message(room_id, message_id):
    from app.business.war_rooms import set_message_pinned
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        msg = set_message_pinned(room, message_id,
                                 data.get('pinned', True))
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success(_message_row(msg))


# ------------------------------------------------------------------- polls

def _poll_response(poll):
    from app.business.war_rooms import serialize_poll
    out = serialize_poll(poll, current_user.id)
    out['closes_at'] = _iso(out['closes_at'])
    return out


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/polls', methods=['POST'])
@ac_api_requires()
def create_war_room_poll(room_id):
    from app.business.war_rooms import create_poll
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    closes_at = _parse_iso_date(data.get('closes_at'))
    try:
        poll = create_poll(room, current_user.id, data.get('question'),
                           data.get('options'),
                           multiple=bool(data.get('multiple')),
                           anonymous=bool(data.get('anonymous')),
                           closes_at=closes_at)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success(_poll_response(poll))


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/polls/<int:poll_id>/vote', methods=['POST'])
@ac_api_requires()
def vote_war_room_poll(room_id, poll_id):
    """Everyone with room access can vote (v3 wording) — observers included."""
    from app.business.war_rooms import vote_poll
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        poll = vote_poll(room, poll_id, current_user.id,
                         int(data.get('option_id') or 0))
    except (BusinessProcessingError, ValueError, TypeError) as e:
        return response_api_error(str(e))
    return response_api_success(_poll_response(poll))


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/polls/<int:poll_id>/close', methods=['POST'])
@ac_api_requires()
def close_war_room_poll(room_id, poll_id):
    from app.business.war_rooms import close_poll
    room, role, err = _resolve(room_id, 'observer')
    if err:
        return err
    try:
        poll = close_poll(room, poll_id, current_user.id,
                          is_lead=(role == 'lead'))
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success(_poll_response(poll))


# -------------------------------------------------------------- room tasks

def _room_task_row(t):
    return {
        'id': t.id, 'title': t.title, 'status': t.status,
        'description': t.description, 'due_date': _iso(t.due_date),
        'tags': t.tags, 'parent_task_id': t.parent_task_id,
        'assignee_id': t.assignee_id,
        'assignee_name': t.assignee.name if t.assignee else None,
        'created_by_name': t.creator.name if t.creator else None,
        'created_at': _iso(t.created_at), 'done_at': _iso(t.done_at),
    }


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/room-tasks',
                           methods=['GET'])
@ac_api_requires()
def list_war_room_room_tasks(room_id):
    from app.business.war_rooms import list_room_tasks
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    return response_api_success({
        'tasks': [_room_task_row(t) for t in list_room_tasks(room)]})


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/room-tasks',
                           methods=['POST'])
@ac_api_requires()
def create_war_room_room_task(room_id):
    from app.business.war_rooms import add_room_task
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        t = add_room_task(room, data.get('title'), current_user.id,
                          assignee_id=data.get('assignee_id'),
                          description=data.get('description'),
                          status=data.get('status') or 'no_status',
                          due_date=_parse_iso_date(data.get('due_date')),
                          tags=data.get('tags'),
                          parent_task_id=data.get('parent_task_id'))
    except (BusinessProcessingError, ValueError, TypeError) as e:
        return response_api_error(str(e))
    return response_api_success(_room_task_row(t))


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/room-tasks/<int:task_id>', methods=['PUT'])
@ac_api_requires()
def update_war_room_room_task(room_id, task_id):
    from app.business.war_rooms import set_room_task
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    kwargs = {'status': data.get('status')}
    if 'assignee_id' in data:
        kwargs['assignee_id'] = data.get('assignee_id') or 0
    for k in ('title', 'description', 'tags'):
        if k in data:
            kwargs[k] = data.get(k)
    if 'due_date' in data:
        parsed = _parse_iso_date(data.get('due_date'))
        if parsed is not None:
            kwargs['due_date'] = parsed
        else:
            kwargs['clear_due'] = True
    try:
        t = set_room_task(room, task_id, current_user.id, **kwargs)
    except (BusinessProcessingError, ValueError, TypeError) as e:
        return response_api_error(str(e))
    return response_api_success(_room_task_row(t))


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/room-tasks/<int:task_id>', methods=['DELETE'])
@ac_api_requires()
def delete_war_room_room_task(room_id, task_id):
    from app.business.war_rooms import delete_room_task
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    try:
        delete_room_task(room, task_id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'deleted': task_id})


# ----------------------------------------------------------------- sitreps

def _sitrep_row(s, with_content=True):
    out = {
        'id': s.id, 'room_id': s.room_id, 'title': s.title,
        'status': s.status,
        'created_by': s.created_by,
        'created_by_name': s.creator.name if s.creator else None,
        'created_at': _iso(s.created_at), 'updated_at': _iso(s.updated_at),
        'published_at': _iso(s.published_at),
        'published_by_name': s.publisher.name if s.publisher else None,
        'revision_count': len(s.revisions),
        # v3 meta: "v1 · Draft" — the version is the edit generation.
        'version': len(s.revisions) + 1,
    }
    if with_content:
        from app.iris_engine.safe_markdown import render_markdown_safe
        out['content'] = s.content
        out['content_html'] = render_markdown_safe(s.content or '')
    return out


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/sitreps/preview',
                           methods=['POST'])
@ac_api_requires()
def preview_war_room_sitrep(room_id):
    """Stateless markdown preview for the SitRep editor (safe renderer)."""
    from app.iris_engine.safe_markdown import render_markdown_safe
    _, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    return response_api_success(
        {'content_html': render_markdown_safe(data.get('content') or '')})


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/sitreps', methods=['GET'])
@ac_api_requires()
def list_war_room_sitreps(room_id):
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    return response_api_success({
        'sitreps': [_sitrep_row(s, with_content=False)
                    for s in list_sitreps(room)]})


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/sitreps', methods=['POST'])
@ac_api_requires()
def create_war_room_sitrep(room_id):
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        s = create_sitrep(room, data.get('title'), data.get('content'),
                          current_user.id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success(_sitrep_row(s))


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/sitreps/<int:sitrep_id>',
                           methods=['GET'])
@ac_api_requires()
def get_war_room_sitrep(room_id, sitrep_id):
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    s = get_sitrep(room, sitrep_id)
    if s is None:
        return response_api_not_found()
    return response_api_success(_sitrep_row(s))


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/sitreps/<int:sitrep_id>',
                           methods=['PUT'])
@ac_api_requires()
def update_war_room_sitrep(room_id, sitrep_id):
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    s = get_sitrep(room, sitrep_id)
    if s is None:
        return response_api_not_found()
    data = request.get_json(silent=True) or {}
    try:
        update_sitrep(room, s, title=data.get('title'),
                      content=data.get('content'), user_id=current_user.id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success(_sitrep_row(s))


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/sitreps/<int:sitrep_id>',
                           methods=['DELETE'])
@ac_api_requires()
def delete_war_room_sitrep(room_id, sitrep_id):
    room, _, err = _resolve(room_id, 'lead')
    if err:
        return err
    s = get_sitrep(room, sitrep_id)
    if s is None:
        return response_api_not_found()
    try:
        delete_sitrep(room, s)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'deleted': sitrep_id})


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/sitreps/<int:sitrep_id>/publish',
    methods=['POST'])
@ac_api_requires()
def publish_war_room_sitrep(room_id, sitrep_id):
    # Publishing is a lead action — a SitRep is the room's outward report.
    room, _, err = _resolve(room_id, 'lead')
    if err:
        return err
    s = get_sitrep(room, sitrep_id)
    if s is None:
        return response_api_not_found()
    try:
        publish_sitrep(room, s, current_user.id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success(_sitrep_row(s))


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/sitreps/<int:sitrep_id>/revisions',
    methods=['GET'])
@ac_api_requires()
def war_room_sitrep_revisions(room_id, sitrep_id):
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    s = get_sitrep(room, sitrep_id)
    if s is None:
        return response_api_not_found()
    return response_api_success({'revisions': [{
        'revision_number': r.revision_number, 'title': r.title,
        'content': r.content,
        'user_name': r.user.name if r.user else None,
        'revision_timestamp': _iso(r.revision_timestamp),
    } for r in sitrep_revisions(s)]})


# ------------------------------------------- room-scoped correlation + STIX

@war_rooms_blueprint.route('/war-rooms/<int:room_id>/correlation',
                           methods=['GET'])
@ac_api_requires()
def war_room_correlation(room_id):
    """Shared-IOC view scoped to the room's attached cases — the correlation
    ENGINE reused via its additive case_ids filter, never reimplemented.
    Pairs are additionally scoped by the VIEWER's case ACL (membership does
    not grant case access), and the stats block says how many linked cases
    the viewer cannot see so an empty table is never ambiguous."""
    from app.business.ioc_correlation import build_correlation_report
    from app.business.war_rooms import room_case_ids
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    linked = room_case_ids(room.id)
    acl = set(ac_get_fast_user_cases_access(current_user.id) or [])
    accessible = [c for c in linked if c in acl]
    if linked:
        report = build_correlation_report(current_user.id, min_shared=1,
                                          case_ids=linked)
    else:
        report = {'pairs': [], 'case_meta': {}}
    return response_api_success({
        'pairs': report.get('pairs', []),
        'case_meta': report.get('case_meta', {}),
        'campaign_tag': room.campaign_tag,
        'stats': {
            'linked_cases': len(linked),
            'accessible_cases': len(accessible),
            'inaccessible_cases': len(linked) - len(accessible),
            'shared_ioc_count': len(report.get('pairs', [])),
        },
    })


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/stix', methods=['GET'])
@ac_api_requires()
def war_room_stix(room_id):
    """STIX 2.1 bundle for the room's attached cases — same outbound TLP
    gate as the cluster export (only shareable TLPs; withheld count in the
    X-IRIS-TLP-Withheld header, since a file response has no body for a
    warning). The room name + analyst-owned summary become the campaign
    name/description — the summary REACHES THE EXPORT, same authority as an
    analyst-edited cluster narrative on the correlation path."""
    from app.business.ioc_correlation import build_correlation_report
    from app.business.war_rooms import room_case_ids
    from app.iris_engine.stix_export import build_cluster_stix_bundle
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    linked = room_case_ids(room.id)
    if not linked:
        return response_api_error('No cases attached to this room')

    report = build_correlation_report(current_user.id, min_shared=1,
                                      case_ids=linked)
    pairs = report.get('pairs', [])
    tlp_withheld = sum(1 for p in pairs if not p.get('tlp_shareable'))
    pairs = [p for p in pairs if p.get('tlp_shareable')]
    if not pairs:
        return response_api_error(
            f'Nothing to export — all {tlp_withheld} shared indicator(s) in '
            'this room are held back because their TLP does not permit '
            'redistribution. Only TLP:GREEN and TLP:CLEAR are exported; an '
            'indicator with no TLP set is treated as not shareable.')

    cluster_id = room.source_cluster_id or f'war-room-{room.id}'
    cluster = {
        'cluster_id': cluster_id,
        'case_ids': sorted(linked),
        'shared_ioc_count': len(pairs),
        'suggested_campaign_tag': room.campaign_tag
                                  or f'campaign:war-room-{room.id}',
    }
    narrative = ({'suggested_name': room.name, 'narrative': room.summary}
                 if room.summary else None)
    bundle = build_cluster_stix_bundle(
        cluster=cluster, pairs_for_cluster=pairs,
        case_meta=report.get('case_meta', {}), narrative=narrative)

    headers = {'Content-Disposition':
               f'attachment; filename="iris-ng-war-room-{room.id}-stix21.json"'}
    if tlp_withheld:
        headers['X-IRIS-TLP-Withheld'] = str(tlp_withheld)
    return Response(json.dumps(bundle, indent=2, ensure_ascii=False),
                    mimetype='application/json', headers=headers)


# ----------------------------------------------------------- MISP push

@war_rooms_blueprint.route('/war-rooms/<int:room_id>/misp-push',
                           methods=['POST'])
@ac_api_requires()
def war_room_misp_push(room_id):
    """Publish the room to MISP as a single campaign event — the MISP push
    REBASED onto the room's durable id (war_room_misp_link supersedes
    MispClusterLink's comma-separated case_ids hack). Lead action: this
    sends data to a third party.

    Same contract as the cluster push: 409 on repeat, force=true republishes
    into a NEW MISP event and updates the link row; outbound TLP gate via
    the shared _build_ioc_records; entity names redacted by the module
    (every client name + the linked cases' names, derived fresh per push).
    The room name + analyst summary supply the event title/description and
    go through the same redaction — a hand-typed summary carries no prompt
    guarantee, exactly like an analyst-edited narrative."""
    from datetime import datetime as _dt

    from app.blueprints.rest.v2.correlation import _build_ioc_records
    from app.blueprints.rest.v2.correlation import _misp_cluster_module_config
    from app.business.ioc_correlation import build_correlation_report
    from app.business.war_rooms import room_case_ids
    from app.models.cases import Cases
    from app.models.models import Client
    from app.models.models import WarRoomMispLink

    room, _, err = _resolve(room_id, 'lead')
    if err:
        return err
    linked = room_case_ids(room.id)
    if not linked:
        return response_api_error('No cases attached to this room')

    data = request.get_json(silent=True) or {}
    force = str(data.get('force', '')).lower() in ('1', 'true', 'yes')

    existing = WarRoomMispLink.query.filter_by(room_id=room.id).first()
    if existing is not None and not force:
        cfg_url = (_misp_cluster_module_config().get('misp_cluster_url')
                   or '').rstrip('/')
        return response(409, data={
            'message': (f'This room was already published to MISP as event '
                        f'#{existing.misp_event_id}. Re-publishing creates a '
                        f'NEW event — retry with force=true to confirm.'),
            'data': {
                'reason': 'already_published',
                'misp_event_id': existing.misp_event_id,
                'misp_event_url': (f'{cfg_url}/events/view/'
                                   f'{existing.misp_event_id}'
                                   if cfg_url else None),
                'pushed_at': (existing.pushed_at.isoformat()
                              if existing.pushed_at else None),
                'pushed_by': (existing.pushed_by.name
                              if existing.pushed_by else None),
            }})

    report = build_correlation_report(current_user.id, min_shared=1,
                                      case_ids=linked)
    pairs = report.get('pairs', [])
    ioc_records, tlp_withheld = _build_ioc_records(pairs)
    if not ioc_records:
        if tlp_withheld:
            return response_api_error(
                f'No publishable indicators in this room — {tlp_withheld} '
                'indicator(s) are held back because their TLP does not permit '
                'redistribution (only TLP:GREEN and TLP:CLEAR are published; '
                'an indicator with no TLP set is treated as not shareable)')
        return response_api_error(
            'No publishable indicators in this room — no IOC is shared by '
            'two or more attached cases, or every shared IOC type lacks a '
            'MISP attribute-type mapping (IocType.type_taxonomy)')

    redact_terms = [c.name for c in Client.query.all() if c.name]
    for case in Cases.query.filter(Cases.case_id.in_(linked)).all():
        if case.name:
            redact_terms.append(case.name)

    cluster = {
        'cluster_id': room.source_cluster_id or f'war-room-{room.id}',
        'case_ids': sorted(linked),
        'shared_ioc_count': len(pairs),
        'suggested_campaign_tag': room.campaign_tag
                                  or f'campaign:war-room-{room.id}',
    }
    narrative = ({'suggested_name': room.name, 'narrative': room.summary}
                 if room.summary else {'suggested_name': room.name,
                                       'narrative': room.description or ''})

    import iris_misp_cluster_module.IrisMISPClusterInterface as misp_mod
    from app import app as _app
    handler = misp_mod.IrisMISPClusterHandler(
        mod_config=_misp_cluster_module_config(), logger=_app.logger)
    try:
        result = handler.push_cluster(
            cluster=cluster, narrative=narrative, ioc_records=ioc_records,
            campaign_tag=cluster['suggested_campaign_tag'],
            redact_terms=redact_terms)
    except misp_mod.IrisMISPClusterError as exc:
        return response_api_error(str(exc))
    except Exception as exc:
        _app.logger.exception('war_room_misp_push failed')
        return response_api_error(f'MISP push failed: {exc}')

    if existing is not None:
        existing.misp_event_id = result['misp_event_id']
        existing.misp_event_uuid = result.get('misp_event_uuid')
        existing.pushed_at = _dt.utcnow()
        existing.pushed_by_id = current_user.id
    else:
        db.session.add(WarRoomMispLink(
            room_id=room.id,
            misp_event_id=result['misp_event_id'],
            misp_event_uuid=result.get('misp_event_uuid'),
            pushed_by_id=current_user.id))
    db.session.commit()
    track_activity(f'published war room #{room.id} to MISP event '
                   f"#{result['misp_event_id']}", ctx_less=True)

    if tlp_withheld:
        result = dict(result)
        result['tlp_withheld_count'] = tlp_withheld
        result['tlp_withheld_note'] = (
            f'{tlp_withheld} indicator(s) were not published because their '
            'TLP does not permit redistribution. Only TLP:GREEN and '
            'TLP:CLEAR are sent; an indicator with no TLP set is treated as '
            'not shareable.')
    return response_api_success(result)


# ---------------------------------------------------------- AI SitRep draft

@war_rooms_blueprint.route('/war-rooms/<int:room_id>/sitreps/ai-draft',
                           methods=['GET'])
@ac_api_requires()
def get_sitrep_ai_draft(room_id):
    from app.iris_engine.ai.sitrep_draft import SitrepDraftError
    from app.iris_engine.ai.sitrep_draft import artifact_to_result
    from app.iris_engine.ai.sitrep_draft import get_latest_draft
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    art = get_latest_draft(room.id)
    if art is None:
        return response_api_not_found()
    try:
        return response_api_success(artifact_to_result(art, cached=True))
    except SitrepDraftError as e:
        return response_api_error(str(e))


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/sitreps/ai-draft',
                           methods=['POST'])
@ac_api_requires()
def generate_sitrep_ai_draft(room_id):
    """Draft a SitRep with AI. Async by default (202 + task_id, poll
    /api/v2/ai/jobs/<task_id>); ?sync=true runs inline for scripts. The
    result pre-fills the editor — AI NEVER publishes; no 409 guard because
    the artifact is a pure cache (the SitRep editor is the override)."""
    from app.iris_engine.ai.sitrep_draft import SitrepDraftError
    from app.iris_engine.ai.sitrep_draft import generate_sitrep_draft
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    if room.status == 'closed':
        return response_api_error('Room is closed')

    data = request.get_json(silent=True) or {}
    force = bool(data.get('force', False))

    if request.args.get('sync') == 'true':
        try:
            return response_api_success(
                generate_sitrep_draft(room.id, force=force))
        except SitrepDraftError as e:
            return response_api_error(str(e))

    from app.iris_engine.ai.ai_jobs import enqueue_ai_job
    job = enqueue_ai_job(feature='sitrep_draft', case_id=None,
                         user_id=current_user.id,
                         params={'room_id': room.id, 'force': force})
    return response(202, data={'task_id': job.task_id, 'state': 'queued'})


# ------------------------------------- read-only tab aggregations (v3 tabs)

@war_rooms_blueprint.route('/war-rooms/<int:room_id>/timeline', methods=['GET'])
@ac_api_requires()
def war_room_timeline(room_id):
    """Timelines tab payload: read-only CASE events (viewer-ACL) merged with
    the room's own timelines. The case-page timelines are only READ
    (invariant); room timelines are the read-write layer."""
    from app.business.war_rooms import room_timeline
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    out = room_timeline(room, current_user.id,
                        limit=request.args.get('limit', 500))
    for r in out['events']:
        r['event_date'] = _iso(r['event_date'])
    return response_api_success(out)


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/timelines',
                           methods=['POST'])
@ac_api_requires()
def create_war_room_timeline(room_id):
    from app.business.war_rooms import create_room_timeline
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        tl = create_room_timeline(room, data.get('name'), current_user.id,
                                  color=data.get('color'))
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'id': tl.id, 'name': tl.name,
                                 'color': tl.color, 'event_count': 0})


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/timelines/<int:timeline_id>',
    methods=['PUT'])
@ac_api_requires()
def update_war_room_timeline(room_id, timeline_id):
    from app.business.war_rooms import update_room_timeline
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    fields = {k: data.get(k) for k in ('name', 'color') if k in data}
    try:
        tl = update_room_timeline(room, timeline_id, **fields)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'id': tl.id, 'name': tl.name,
                                 'color': tl.color,
                                 'event_count': len(tl.events)})


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/timelines/<int:timeline_id>',
    methods=['DELETE'])
@ac_api_requires()
def delete_war_room_timeline(room_id, timeline_id):
    from app.business.war_rooms import delete_room_timeline
    room, _, err = _resolve(room_id, 'lead')
    if err:
        return err
    try:
        delete_room_timeline(room, timeline_id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'deleted': timeline_id})


def _timeline_event_row(ev):
    return {'id': ev.id, 'timeline_id': ev.timeline_id,
            'event_date': _iso(ev.event_date), 'title': ev.title,
            'content': ev.content, 'category': ev.category,
            'color': ev.color, 'tags': ev.tags}


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/timelines/<int:timeline_id>/events',
    methods=['POST'])
@ac_api_requires()
def create_war_room_timeline_event(room_id, timeline_id):
    from app.business.war_rooms import add_timeline_event
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        ev = add_timeline_event(
            room, timeline_id, current_user.id, data.get('title'),
            _parse_iso_date(data.get('event_date')),
            content=data.get('content'), category=data.get('category'),
            color=data.get('color'), tags=data.get('tags'))
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success(_timeline_event_row(ev))


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/timelines/<int:timeline_id>/events/<int:event_id>',
    methods=['PUT'])
@ac_api_requires()
def update_war_room_timeline_event(room_id, timeline_id, event_id):
    from app.business.war_rooms import update_timeline_event
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    fields = {}
    for k in ('title', 'content', 'category', 'color', 'tags'):
        if k in data:
            fields[k] = data.get(k)
    if 'event_date' in data:
        fields['event_date'] = _parse_iso_date(data.get('event_date'))
    try:
        ev = update_timeline_event(room, timeline_id, event_id, **fields)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success(_timeline_event_row(ev))


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/timelines/<int:timeline_id>/events/<int:event_id>',
    methods=['DELETE'])
@ac_api_requires()
def delete_war_room_timeline_event(room_id, timeline_id, event_id):
    from app.business.war_rooms import delete_timeline_event
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    try:
        delete_timeline_event(room, timeline_id, event_id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'deleted': event_id})


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/tasks', methods=['GET'])
@ac_api_requires()
def war_room_tasks(room_id):
    from app.business.war_rooms import room_tasks
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    rows = room_tasks(room, current_user.id,
                      limit=request.args.get('limit', 200))
    for r in rows:
        r['task_last_update'] = _iso(r['task_last_update'])
    return response_api_success({'tasks': rows})


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/notes', methods=['GET'])
@ac_api_requires()
def war_room_notes(room_id):
    from app.business.war_rooms import room_notes
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    out = room_notes(room, current_user.id,
                     limit=request.args.get('limit', 200))
    for r in out['case_notes']:
        r['note_lastupdate'] = _iso(r['note_lastupdate'])
    for r in out['room_notes']:
        r['updated_at'] = _iso(r['updated_at'])
    return response_api_success(out)


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/notes/folders',
                           methods=['POST'])
@ac_api_requires()
def create_war_room_note_folder(room_id):
    from app.business.war_rooms import create_note_folder
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        f = create_note_folder(room, data.get('name'), current_user.id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'id': f.id, 'name': f.name})


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/notes/folders/<int:folder_id>',
    methods=['PUT'])
@ac_api_requires()
def rename_war_room_note_folder(room_id, folder_id):
    from app.business.war_rooms import rename_note_folder
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        f = rename_note_folder(room, folder_id, data.get('name'))
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'id': f.id, 'name': f.name})


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/notes/folders/<int:folder_id>',
    methods=['DELETE'])
@ac_api_requires()
def delete_war_room_note_folder(room_id, folder_id):
    from app.business.war_rooms import delete_note_folder
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    try:
        delete_note_folder(room, folder_id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'deleted': folder_id})


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/notes/room',
                           methods=['POST'])
@ac_api_requires()
def create_war_room_note(room_id):
    from app.business.war_rooms import create_room_note
    from app.business.war_rooms import serialize_room_note
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        n = create_room_note(room, current_user.id, title=data.get('title'),
                             folder_id=data.get('folder_id'))
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    out = serialize_room_note(n)
    out['updated_at'] = _iso(out['updated_at'])
    return response_api_success(out)


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/notes/room/<int:note_id>',
                           methods=['GET'])
@ac_api_requires()
def get_war_room_note(room_id, note_id):
    from app.business.war_rooms import _get_room_note
    from app.business.war_rooms import serialize_room_note
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    try:
        n = _get_room_note(room, note_id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    out = serialize_room_note(n)
    out['updated_at'] = _iso(out['updated_at'])
    return response_api_success(out)


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/notes/room/<int:note_id>',
                           methods=['PUT'])
@ac_api_requires()
def update_war_room_note(room_id, note_id):
    from app.business.war_rooms import serialize_room_note
    from app.business.war_rooms import update_room_note
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = request.get_json(silent=True) or {}
    fields = {k: data.get(k) for k in ('title', 'content', 'folder_id')
              if k in data}
    try:
        n = update_room_note(room, note_id, current_user.id, **fields)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    out = serialize_room_note(n)
    out['updated_at'] = _iso(out['updated_at'])
    return response_api_success(out)


@war_rooms_blueprint.route('/war-rooms/<int:room_id>/notes/room/<int:note_id>',
                           methods=['DELETE'])
@ac_api_requires()
def delete_war_room_note(room_id, note_id):
    from app.business.war_rooms import delete_room_note
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    try:
        delete_room_note(room, note_id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'deleted': note_id})


@war_rooms_blueprint.route(
    '/war-rooms/<int:room_id>/notes/case/<int:case_id>/<int:note_id>',
    methods=['GET'])
@ac_api_requires()
def get_war_room_case_note(room_id, case_id, note_id):
    from app.business.war_rooms import get_case_note_for_room
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    try:
        out = get_case_note_for_room(room, current_user.id, case_id, note_id)
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    out['updated_at'] = _iso(out['updated_at'])
    return response_api_success(out)


# ------------------------------------------------------------------ stream

@war_rooms_blueprint.route('/war-rooms/<int:room_id>/stream', methods=['GET'])
@ac_api_requires()
def war_room_stream(room_id):
    from app.business.war_rooms import room_topics
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    items = room_stream(room, current_user.id,
                        limit=request.args.get('limit', 50))
    for i in items:
        i['created_at'] = _iso(i['created_at'])
        if i.get('poll'):
            i['poll']['closes_at'] = _iso(i['poll']['closes_at'])
    # Topics come from a DISTINCT over all messages, not the limited window.
    return response_api_success({'stream': items, 'topics': room_topics(room)})

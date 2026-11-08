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

"""War-room Decisions and Board REST (iris-ng 2026-11-07).

  /api/v2/war-rooms/<rid>/decisions                    GET (members + guests) / POST (responder)
  /api/v2/war-rooms/<rid>/decisions/<did>              GET (members + guests) / PATCH / DELETE (lead)
  /api/v2/war-rooms/<rid>/decisions/<did>/vote         POST {verdict} (a named approver)
  /api/v2/war-rooms/<rid>/decisions/<did>/implemented  POST (lead or owner)
  /api/v2/war-rooms/<rid>/decisions/<did>/reopen       POST (lead or owner)
  /api/v2/war-rooms/<rid>/decisions/chat-candidates    GET (responder): /decision messages not registered
  /api/v2/war-rooms/<rid>/decisions/assets             GET ?q= (responder): assets for "Applies to"
  /api/v2/war-rooms/<rid>/board                        GET (members + guests)
  /api/v2/war-rooms/<rid>/board/widgets                PUT {widgets: [...] | null} (lead)
  /api/v2/war-rooms/<rid>/scope/assets                 GET (members; never guests): the Scope tab

Room access is the war rooms' own (_resolve: non-members 404). Guests read the
register and the board and change nothing (maintainer decision 2026-11-07); the
Scope tab lists every asset of the attached cases and is refused to them, like
the room's Vulnerabilities tab.
"""

from flask import Blueprint
from flask import request

from app import db
from app.blueprints.access_controls import ac_room_api_requires
from app.blueprints.responses import response_error
from app.blueprints.rest.endpoints import response_api_created
from app.blueprints.rest.endpoints import response_api_deleted
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
from app.business import war_room_board as wb
from app.business import war_room_decisions as wd
from app.business import war_room_scope as ws
from app.business.war_room_board import BoardError
from app.business.war_room_decisions import DecisionError
from app.business.war_room_scope import ScopeError
from app.iris_engine.utils.tracker import track_activity
from app.models.models import WarRoomDecision

war_room_board_blueprint = Blueprint('war_room_board_rest_v2', __name__)


def _ctx():
    from app.blueprints.rest.v2.war_rooms import _gid
    from app.blueprints.rest.v2.war_rooms import _is_guest
    from app.blueprints.rest.v2.war_rooms import _uid
    return _uid(), _gid(), _is_guest()


def _resolve(room_id, min_role, guests=False):
    from app.blueprints.rest.v2.war_rooms import _resolve as resolve
    return resolve(room_id, min_role, guests=guests)


def _visible(room):
    from app.business.war_rooms import room_visible_case_ids
    uid, _, guest = _ctx()
    return room_visible_case_ids(room.id, uid, guest=guest)


def _err(e):
    return response_error(e.message, data=getattr(e, 'data', None), status=e.status)


def _json():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _decision(room, did):
    d = db.session.get(WarRoomDecision, did)
    return d if d is not None and d.room_id == room.id else None


def _one(room, d, role, detail=True):
    uid, _, guest = _ctx()
    return wd.rows([d], uid, role, guest, _visible(room), detail=detail)[0]


# ================================================================= decisions

@war_room_board_blueprint.route('/war-rooms/<int:room_id>/decisions', methods=['GET'])
@ac_room_api_requires()
def list_room_decisions(room_id):
    room, role, err = _resolve(room_id, 'observer', guests=True)
    if err is not None:
        return err
    try:
        decisions = wd.list_decisions(room.id, request.args)
    except DecisionError as e:
        return _err(e)
    uid, _, guest = _ctx()
    return response_api_success({'decisions': wd.rows(decisions, uid, role, guest, _visible(room)),
                                 'counts': wd.status_counts(room.id, request.args),
                                 'can_propose': (not guest) and role in ('responder', 'lead')
                                 and room.status != 'closed'})


@war_room_board_blueprint.route('/war-rooms/<int:room_id>/decisions/chat-candidates', methods=['GET'])
@ac_room_api_requires()
def room_decision_chat_candidates(room_id):
    room, _, err = _resolve(room_id, 'responder')
    if err is not None:
        return err
    return response_api_success(wd.chat_candidates(room.id))


@war_room_board_blueprint.route('/war-rooms/<int:room_id>/decisions/assets', methods=['GET'])
@ac_room_api_requires()
def room_decision_assets(room_id):
    room, _, err = _resolve(room_id, 'responder')
    if err is not None:
        return err
    uid, _, _ = _ctx()
    return response_api_success(wd.asset_candidates(room.id, uid, request.args.get('q')))


@war_room_board_blueprint.route('/war-rooms/<int:room_id>/decisions/<int:did>', methods=['GET'])
@ac_room_api_requires()
def get_room_decision(room_id, did):
    room, role, err = _resolve(room_id, 'observer', guests=True)
    if err is not None:
        return err
    d = _decision(room, did)
    if d is None:
        return response_api_not_found()
    return response_api_success(_one(room, d, role))


@war_room_board_blueprint.route('/war-rooms/<int:room_id>/decisions', methods=['POST'])
@ac_room_api_requires()
def create_room_decision(room_id):
    room, role, err = _resolve(room_id, 'responder')
    if err is not None:
        return err
    uid, _, _ = _ctx()
    try:
        d, added = wd.create_decision(room, _json(), uid, role)
        db.session.commit()
    except DecisionError as e:
        db.session.rollback()
        return _err(e)
    wd.notify_added_approvers(room, d, added, uid)
    track_activity('proposed decision %s "%s" in war room "%s"' % (wd.ref(d), d.title, room.name), ctx_less=True)
    return response_api_created(_one(room, d, role))


@war_room_board_blueprint.route('/war-rooms/<int:room_id>/decisions/<int:did>', methods=['PATCH'])
@ac_room_api_requires()
def update_room_decision(room_id, did):
    room, role, err = _resolve(room_id, 'observer')
    if err is not None:
        return err
    d = _decision(room, did)
    if d is None:
        return response_api_not_found()
    uid, _, _ = _ctx()
    try:
        added = wd.update_decision(room, d, _json(), uid, role)
        db.session.commit()
    except DecisionError as e:
        db.session.rollback()
        return _err(e)
    wd.notify_added_approvers(room, d, added, uid)
    return response_api_success(_one(room, d, role))


@war_room_board_blueprint.route('/war-rooms/<int:room_id>/decisions/<int:did>/vote', methods=['POST'])
@ac_room_api_requires()
def vote_room_decision(room_id, did):
    room, role, err = _resolve(room_id, 'observer')
    if err is not None:
        return err
    d = _decision(room, did)
    if d is None:
        return response_api_not_found()
    uid, _, _ = _ctx()
    try:
        wd.vote(room, d, uid, _json().get('verdict'))
        db.session.commit()
    except DecisionError as e:
        db.session.rollback()
        return _err(e)
    return response_api_success(_one(room, d, role))


@war_room_board_blueprint.route('/war-rooms/<int:room_id>/decisions/<int:did>/implemented', methods=['POST'])
@ac_room_api_requires()
def implement_room_decision(room_id, did):
    return _implementation(room_id, did, True)


@war_room_board_blueprint.route('/war-rooms/<int:room_id>/decisions/<int:did>/reopen', methods=['POST'])
@ac_room_api_requires()
def reopen_room_decision(room_id, did):
    return _implementation(room_id, did, False)


def _implementation(room_id, did, done):
    room, role, err = _resolve(room_id, 'observer')
    if err is not None:
        return err
    d = _decision(room, did)
    if d is None:
        return response_api_not_found()
    uid, _, _ = _ctx()
    try:
        wd.set_implemented(room, d, uid, role, done=done)
        db.session.commit()
    except DecisionError as e:
        db.session.rollback()
        return _err(e)
    return response_api_success(_one(room, d, role))


@war_room_board_blueprint.route('/war-rooms/<int:room_id>/decisions/<int:did>', methods=['DELETE'])
@ac_room_api_requires()
def delete_room_decision(room_id, did):
    room, _, err = _resolve(room_id, 'lead')
    if err is not None:
        return err
    d = _decision(room, did)
    if d is None:
        return response_api_not_found()
    label = '%s "%s"' % (wd.ref(d), d.title)
    try:
        wd.delete_decision(room, d)
        db.session.commit()
    except DecisionError as e:
        db.session.rollback()
        return _err(e)
    track_activity('deleted decision %s in war room "%s"' % (label, room.name), ctx_less=True)
    return response_api_deleted()


# ================================================================= board

@war_room_board_blueprint.route('/war-rooms/<int:room_id>/board', methods=['GET'])
@ac_room_api_requires()
def get_room_board(room_id):
    room, role, err = _resolve(room_id, 'observer', guests=True)
    if err is not None:
        return err
    uid, _, guest = _ctx()
    return response_api_success(wb.board(room, uid, guest, role))


@war_room_board_blueprint.route('/war-rooms/<int:room_id>/board/widgets', methods=['PUT'])
@ac_room_api_requires()
def set_room_board(room_id):
    room, role, err = _resolve(room_id, 'lead')
    if err is not None:
        return err
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or 'widgets' not in body:
        return response_error('Expected {"widgets": [...]} (null restores the default board).', status=400)
    uid, _, _ = _ctx()
    try:
        wb.set_layout(room, body.get('widgets'), uid)
        db.session.commit()
    except BoardError as e:
        db.session.rollback()
        return _err(e)
    return response_api_success(wb.board(room, uid, False, role))


# ================================================================= scope

@war_room_board_blueprint.route('/war-rooms/<int:room_id>/scope/assets', methods=['GET'])
@ac_room_api_requires()
def get_room_scope_assets(room_id):
    room, _, err = _resolve(room_id, 'observer')
    if err is not None:
        return err
    uid, _, _ = _ctx()
    try:
        return response_api_success(ws.scope_assets(room, uid, request.args))
    except ScopeError as e:
        return _err(e)

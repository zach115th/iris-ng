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

"""REST - the war-room Scope (iris-ng 2026-11-07; the whole workspace since 2026-11-08).

  /api/v2/war-rooms/<rid>/scope/assets                  GET  members: the assets of the attached cases
                                                        POST responder: Add asset (create in several cases)
  /api/v2/war-rooms/<rid>/scope/assets/flags            POST responder: set / remove flags on a selection
  /api/v2/war-rooms/<rid>/scope/assets/status           POST responder: compromise / analysis status
  /api/v2/war-rooms/<rid>/scope/assets/push             POST responder: copy assets to other attached cases
  /api/v2/war-rooms/<rid>/scope/assets/vulnerability    POST responder: record a vulnerability on a selection
  /api/v2/war-rooms/<rid>/scope/iocs                    GET  members: the IOCs, one row per indicator
                                                        POST responder: Add IOC (create in several cases)
  /api/v2/war-rooms/<rid>/scope/iocs/push               POST responder: copy IOCs to the cases missing them
  /api/v2/war-rooms/<rid>/scope/iocs/export             GET  members: ?format=txt|csv|stix&include_red=1
  /api/v2/war-rooms/<rid>/scope/customers               GET  members: the scope per customer
  /api/v2/war-rooms/<rid>/scope/counts                  GET  members: the sub-tabs' figures
  /api/v2/war-rooms/<rid>/scope/vocab                   GET  members: what the Add / staging dialogs offer
  /api/v2/war-rooms/<rid>/scope/staging                 GET  members / POST responder: the staging inbox
  /api/v2/war-rooms/<rid>/scope/staging/<sid>           PATCH / DELETE responder
  /api/v2/war-rooms/<rid>/scope/staging/<sid>/push      POST responder
  /api/v2/war-rooms/<rid>/scope/registry-assets         GET  members / POST responder: Assets Manager attachments
  /api/v2/war-rooms/<rid>/scope/registry-assets/<lid>   PATCH / DELETE responder
  /api/v2/war-rooms/<rid>/scope/registry-assets/<lid>/push   POST responder

Room access is the war rooms' own (_resolve: non-members 404). Guests never get the Scope (refused like the room's
Vulnerabilities). Every change also needs full access to each case it touches - the others come back refused, one
result per object - and a copy across customers needs confirm_cross_customer (409 data.code = cross_customer).
"""

from flask import Blueprint
from flask import Response
from flask import request

from app import db
from app.blueprints.access_controls import ac_room_api_requires
from app.blueprints.rest.endpoints import response_api_created
from app.blueprints.rest.endpoints import response_api_deleted
from app.blueprints.rest.endpoints import response_api_success
from app.blueprints.rest.v2.war_room_board import _ctx
from app.blueprints.rest.v2.war_room_board import _err
from app.blueprints.rest.v2.war_room_board import _json
from app.blueprints.rest.v2.war_room_board import _resolve
from app.business import war_room_scope as ws
from app.business import war_room_scope_iocs as wi
from app.business import war_room_scope_staging as wst
from app.business.war_room_scope import ScopeError

war_room_scope_blueprint = Blueprint('war_room_scope_rest_v2', __name__)


def _admin():
    from app.blueprints.rest.v2.asset_flags import _is_admin
    return _is_admin()


def _read(room_id, run):
    """GET for members (observer and up), never guests."""
    room, _, err = _resolve(room_id, 'observer')
    if err is not None:
        return err
    uid, _, _ = _ctx()
    try:
        return response_api_success(run(room, uid))
    except ScopeError as e:
        return _err(e)


def _change(room_id, run, created=False):
    """A change: responders and leads of the room (the business layer refuses a closed room), never guests."""
    from flask_login import current_user
    room, _, err = _resolve(room_id, 'responder')
    if err is not None:
        return err
    try:
        out = run(room, current_user, _admin(), _json())
    except ScopeError as e:
        db.session.rollback()
        return _err(e)
    return response_api_created(out) if created else response_api_success(out)


# ------------------------------------------------------------------ assets

@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/assets', methods=['GET'])
@ac_room_api_requires()
def get_room_scope_assets(room_id):
    return _read(room_id, lambda room, uid: ws.scope_assets(room, uid, request.args))


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/assets', methods=['POST'])
@ac_room_api_requires()
def scope_assets_create(room_id):
    """{asset: {...}, case_ids, flag_ids, reason, decision_id, confirm_cross_customer}"""
    return _change(room_id, lambda room, user, admin, body: ws.create_assets(room, user, admin, body))


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/assets/flags', methods=['POST'])
@ac_room_api_requires()
def scope_assets_flags(room_id):
    """{asset_ids, flag_ids, action: set|remove, reason, decision_id}"""
    return _change(room_id, lambda room, user, admin, body: ws.bulk_flags(room, user, admin, body))


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/assets/status', methods=['POST'])
@ac_room_api_requires()
def scope_assets_status(room_id):
    """{asset_ids, compromise: <key>, analysis_status_id: <id>}"""
    return _change(room_id, lambda room, user, admin, body: ws.bulk_status(room, user, body))


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/assets/push', methods=['POST'])
@ac_room_api_requires()
def scope_assets_push(room_id):
    """{asset_ids, case_ids, confirm_cross_customer}: copy the assets into those attached cases."""
    return _change(room_id, lambda room, user, admin, body: ws.bulk_push(room, user, body))


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/assets/vulnerability', methods=['POST'])
@ac_room_api_requires()
def scope_assets_vulnerability(room_id):
    """{asset_ids, vulnerability_id | quick, ...the finding's fields}"""
    return _change(room_id, lambda room, user, admin, body: ws.record_vulnerability(room, user, admin, body))


# ------------------------------------------------------------------ IOCs

@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/iocs', methods=['GET'])
@ac_room_api_requires()
def get_room_scope_iocs(room_id):
    return _read(room_id, lambda room, uid: wi.scope_iocs(room, uid, request.args))


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/iocs', methods=['POST'])
@ac_room_api_requires()
def scope_iocs_create(room_id):
    """{ioc: {...}, case_ids, confirm_cross_customer}"""
    return _change(room_id, lambda room, user, admin, body: wi.create_iocs(room, user, body))


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/iocs/push', methods=['POST'])
@ac_room_api_requires()
def scope_iocs_push(room_id):
    """{ioc_ids, case_ids, confirm_cross_customer}"""
    return _change(room_id, lambda room, user, admin, body: wi.push_iocs(room, user, body))


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/iocs/export', methods=['GET'])
@ac_room_api_requires()
def scope_iocs_export(room_id):
    """A file: txt (blocklist) / CSV - every IOC but TLP:RED unless include_red=1; STIX - TLP:GREEN / CLEAR only.
    X-IRIS-TLP-Withheld counts the IOCs left out."""
    room, _, err = _resolve(room_id, 'observer')
    if err is not None:
        return err
    uid, _, _ = _ctx()
    try:
        body, mime, name, withheld = wi.export_iocs(room, uid, request.args.get('format') or '',
                                                    request.args.get('include_red') == '1')
    except ScopeError as e:
        return _err(e)
    headers = {'Content-Disposition': 'attachment; filename="%s"' % name, 'X-IRIS-TLP-Withheld': str(withheld)}
    return Response(body, mimetype=mime, headers=headers)


# ------------------------------------------------------------------ customers, counts, vocabulary

@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/customers', methods=['GET'])
@ac_room_api_requires()
def get_room_scope_customers(room_id):
    return _read(room_id, lambda room, uid: ws.scope_customers(room, uid))


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/counts', methods=['GET'])
@ac_room_api_requires()
def get_room_scope_counts(room_id):
    return _read(room_id, lambda room, uid: ws.scope_counts(room, uid, _admin()))


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/vocab', methods=['GET'])
@ac_room_api_requires()
def get_room_scope_vocab(room_id):
    return _read(room_id, lambda room, uid: ws.scope_vocab(room, uid))


# ------------------------------------------------------------------ staging

def _staged_out(room, uid, s):
    from app.business.war_rooms import room_visible_case_ids
    visible = set(room_visible_case_ids(room.id, uid))
    return wst.staged_row(s, visible, wst._case_names(set(s.target_case_ids or []) & visible))


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/staging', methods=['GET'])
@ac_room_api_requires()
def get_room_scope_staging(room_id):
    return _read(room_id, lambda room, uid: wst.list_staged(room, uid))


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/staging', methods=['POST'])
@ac_room_api_requires()
def scope_staging_create(room_id):
    """{kind: asset|ioc, payload, target_case_ids, note}"""
    return _change(room_id, lambda room, user, admin, body: _staged_out(room, user.id, wst.create_staged(room, user, body)),
                   created=True)


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/staging/<int:sid>', methods=['PATCH'])
@ac_room_api_requires()
def scope_staging_update(room_id, sid):
    return _change(room_id, lambda room, user, admin, body: _staged_out(room, user.id,
                                                                         wst.update_staged(room, user, sid, body)))


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/staging/<int:sid>', methods=['DELETE'])
@ac_room_api_requires()
def scope_staging_delete(room_id, sid):
    room, _, err = _resolve(room_id, 'responder')
    if err is not None:
        return err
    try:
        wst.delete_staged(room, sid)
    except ScopeError as e:
        db.session.rollback()
        return _err(e)
    return response_api_deleted()


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/staging/<int:sid>/push', methods=['POST'])
@ac_room_api_requires()
def scope_staging_push(room_id, sid):
    """{case_ids (default: its targets), confirm_cross_customer}"""
    return _change(room_id, lambda room, user, admin, body: wst.push_staged(room, user, sid, body))


# ------------------------------------------------------------------ Assets Manager attachments

@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/registry-assets', methods=['GET'])
@ac_room_api_requires()
def get_room_scope_registry(room_id):
    return _read(room_id, lambda room, uid: wst.list_registry(room, uid, _admin()))


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/registry-assets', methods=['POST'])
@ac_room_api_requires()
def scope_registry_attach(room_id):
    """{customer_asset_ids, case_id, note}"""
    return _change(room_id, lambda room, user, admin, body: wst.attach_registry(room, user, admin, body))


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/registry-assets/<int:lid>', methods=['PATCH'])
@ac_room_api_requires()
def scope_registry_update(room_id, lid):
    """{case_id (null unlinks), note}"""
    def run(room, user, admin, body):
        wst.update_registry(room, user, admin, lid, body)
        rows, _ = wst.registry_rows(room, user.id, admin)
        return next((r for r in rows if r['id'] == lid), None)
    return _change(room_id, run)


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/registry-assets/<int:lid>', methods=['DELETE'])
@ac_room_api_requires()
def scope_registry_detach(room_id, lid):
    from flask_login import current_user
    room, _, err = _resolve(room_id, 'responder')
    if err is not None:
        return err
    try:
        wst.detach_registry(room, current_user, _admin(), lid)
    except ScopeError as e:
        db.session.rollback()
        return _err(e)
    return response_api_deleted()


@war_room_scope_blueprint.route('/war-rooms/<int:room_id>/scope/registry-assets/<int:lid>/push', methods=['POST'])
@ac_room_api_requires()
def scope_registry_push(room_id, lid):
    """{case_ids, confirm_cross_customer}"""
    return _change(room_id, lambda room, user, admin, body: wst.push_registry(room, user, admin, lid, body))

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

"""Asset flags REST (iris-ng 2026-11-07).

  /api/v2/manage/asset-flags                       GET (any user) / POST (server administrator)
  /api/v2/manage/asset-flags/vocab                 GET
  /api/v2/manage/asset-flags/<id>                  PUT / DELETE (server administrator)
  /api/v2/manage/asset-flags/reorder               POST {ids} (server administrator)
  /api/v2/manage/asset-flags/presets/<preset>      POST (server administrator)
  /api/v2/cases/<cid>/assets/<aid>/flags           GET (case read access)
  /api/v2/cases/<cid>/assets/<aid>/flags/<fid>     PUT {reason, decision_id} / DELETE {reason} (full access)
  /api/v2/cases/<cid>/assets/<aid>/flag-history    GET (case read access)
  /api/v2/cases/<cid>/assets/<aid>/flag-decisions  GET (case read access): decisions a flag may cite

No new permission bit: the catalogue is administration, the flags on an asset
follow case access. A guest (portal) session reaches none of these routes.
"""

from flask import Blueprint
from flask import request
from flask_login import current_user

from app import db
from app.blueprints.access_controls import ac_api_requires
from app.blueprints.access_controls import ac_api_return_access_denied
from app.blueprints.responses import response_error
from app.blueprints.rest.endpoints import response_api_created
from app.blueprints.rest.endpoints import response_api_deleted
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
from app.business import asset_flags as fl
from app.business.asset_flags import FlagError
from app.iris_engine.access_control.utils import ac_current_user_has_permission
from app.iris_engine.access_control.utils import ac_fast_check_current_user_has_case_access
from app.iris_engine.utils.tracker import track_activity
from app.models.authorization import CaseAccessLevel
from app.models.authorization import Permissions
from app.models.models import AssetFlag
from app.models.models import CaseAssets

asset_flags_blueprint = Blueprint('asset_flags_rest_v2', __name__)


def _err(e):
    return response_error(e.message, data=e.data, status=e.status)


def _is_admin():
    return ac_current_user_has_permission(Permissions.server_administrator)


def _json():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _admin_only():
    if not _is_admin():
        return response_error('Only a server administrator can change the asset flags.', status=403)
    return None


# ================================================================= catalogue

@asset_flags_blueprint.route('/manage/asset-flags', methods=['GET'])
@ac_api_requires()
def list_asset_flags():
    return response_api_success(fl.list_flags(with_counts=(request.args.get('counts') or '').lower() == 'true'))


@asset_flags_blueprint.route('/manage/asset-flags/vocab', methods=['GET'])
@ac_api_requires()
def asset_flag_vocab():
    out = fl.vocab()
    out['can_manage'] = bool(_is_admin())
    return response_api_success(out)


@asset_flags_blueprint.route('/manage/asset-flags', methods=['POST'])
@ac_api_requires()
def create_asset_flag():
    denied = _admin_only()
    if denied is not None:
        return denied
    try:
        f = fl.create_flag(_json(), current_user.id)
        db.session.commit()
    except FlagError as e:
        db.session.rollback()
        return _err(e)
    track_activity('created asset flag "%s"' % f.name, ctx_less=True)
    return response_api_created(fl.flag_row(f, 0))


@asset_flags_blueprint.route('/manage/asset-flags/<int:flag_id>', methods=['PUT'])
@ac_api_requires()
def update_asset_flag(flag_id):
    denied = _admin_only()
    if denied is not None:
        return denied
    f = db.session.get(AssetFlag, flag_id)
    if f is None:
        return response_api_not_found()
    try:
        fl.update_flag(f, _json(), current_user.id)
        db.session.commit()
    except FlagError as e:
        db.session.rollback()
        return _err(e)
    track_activity('updated asset flag "%s"' % f.name, ctx_less=True)
    rows = [r for r in fl.list_flags(with_counts=True) if r['id'] == f.id]
    return response_api_success(rows[0])


@asset_flags_blueprint.route('/manage/asset-flags/<int:flag_id>', methods=['DELETE'])
@ac_api_requires()
def delete_asset_flag(flag_id):
    denied = _admin_only()
    if denied is not None:
        return denied
    f = db.session.get(AssetFlag, flag_id)
    if f is None:
        return response_api_not_found()
    name = f.name
    fl.delete_flag(f)
    db.session.commit()
    track_activity('deleted asset flag "%s"' % name, ctx_less=True)
    return response_api_deleted()


@asset_flags_blueprint.route('/manage/asset-flags/reorder', methods=['POST'])
@ac_api_requires()
def reorder_asset_flags():
    denied = _admin_only()
    if denied is not None:
        return denied
    try:
        fl.reorder(_json().get('ids'))
        db.session.commit()
    except FlagError as e:
        db.session.rollback()
        return _err(e)
    return response_api_success(fl.list_flags(with_counts=True))


@asset_flags_blueprint.route('/manage/asset-flags/presets/<preset_id>', methods=['POST'])
@ac_api_requires()
def apply_asset_flag_preset(preset_id):
    denied = _admin_only()
    if denied is not None:
        return denied
    try:
        added = fl.apply_preset(preset_id, current_user.id)
        db.session.commit()
    except FlagError as e:
        db.session.rollback()
        return _err(e)
    if added:
        track_activity('loaded the asset flag preset "%s" (%s)' % (preset_id, ', '.join(added)), ctx_less=True)
    return response_api_success({'flags': fl.list_flags(with_counts=True), 'added': added})


# ================================================================= flags on case assets

def _case_read(cid):
    return ac_fast_check_current_user_has_case_access(cid, [CaseAccessLevel.read_only, CaseAccessLevel.full_access])


def _case_write(cid):
    return ac_fast_check_current_user_has_case_access(cid, [CaseAccessLevel.full_access])


def _asset(cid, aid):
    a = db.session.get(CaseAssets, aid)
    return a if a is not None and a.case_id == cid else None


@asset_flags_blueprint.route('/cases/<int:cid>/assets/<int:aid>/flags', methods=['GET'])
@ac_api_requires()
def list_asset_flags_of_asset(cid, aid):
    if not _case_read(cid):
        return ac_api_return_access_denied(caseid=cid)
    if _asset(cid, aid) is None:
        return response_api_not_found()
    return response_api_success(fl.flags_for_asset(aid))


@asset_flags_blueprint.route('/cases/<int:cid>/assets/<int:aid>/flags/<int:flag_id>', methods=['PUT'])
@ac_api_requires()
def set_asset_flag(cid, aid, flag_id):
    if not _case_write(cid):
        return ac_api_return_access_denied(caseid=cid)
    asset = _asset(cid, aid)
    flag = db.session.get(AssetFlag, flag_id)
    if asset is None or flag is None:
        return response_api_not_found()
    try:
        row, action = fl.set_flag(cid, asset, flag, _json(), current_user, _is_admin())
        db.session.commit()
    except FlagError as e:
        db.session.rollback()
        return _err(e)
    if action:
        track_activity(fl.activity_text(flag, asset.asset_name, action, row.get('reason')), caseid=cid)
    return response_api_success({'flag': row, 'action': action, 'flags': fl.flags_for_asset(aid)})


@asset_flags_blueprint.route('/cases/<int:cid>/assets/<int:aid>/flags/<int:flag_id>', methods=['DELETE'])
@ac_api_requires()
def clear_asset_flag(cid, aid, flag_id):
    if not _case_write(cid):
        return ac_api_return_access_denied(caseid=cid)
    asset = _asset(cid, aid)
    flag = db.session.get(AssetFlag, flag_id)
    if asset is None or flag is None:
        return response_api_not_found()
    payload = _json() or {'reason': request.args.get('reason')}
    try:
        fl.clear_flag(cid, asset, flag, payload, current_user)
        db.session.commit()
    except FlagError as e:
        db.session.rollback()
        return _err(e)
    track_activity(fl.activity_text(flag, asset.asset_name, 'cleared', (payload.get('reason') or '').strip() or None),
                   caseid=cid)
    return response_api_success({'flags': fl.flags_for_asset(aid)})


@asset_flags_blueprint.route('/cases/<int:cid>/assets/<int:aid>/flag-history', methods=['GET'])
@ac_api_requires()
def asset_flag_history(cid, aid):
    if not _case_read(cid):
        return ac_api_return_access_denied(caseid=cid)
    if _asset(cid, aid) is None:
        return response_api_not_found()
    return response_api_success(fl.flag_history(aid))


@asset_flags_blueprint.route('/cases/<int:cid>/assets/<int:aid>/flag-decisions', methods=['GET'])
@ac_api_requires()
def asset_flag_decisions(cid, aid):
    if not _case_read(cid):
        return ac_api_return_access_denied(caseid=cid)
    if _asset(cid, aid) is None:
        return response_api_not_found()
    return response_api_success(fl.decision_candidates(cid, aid, current_user.id, _is_admin()))

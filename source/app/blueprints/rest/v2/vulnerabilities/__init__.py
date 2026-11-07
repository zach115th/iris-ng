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

"""Vulnerability catalogue + findings REST surface (iris-ng 2026-11-07).

  /api/v2/manage/vulnerabilities                       catalogue (any signed-in user reads, creates, edits)
  /api/v2/manage/vulnerabilities/<id>/merge  DELETE    server administrators only
  /api/v2/manage/vulnerabilities/cve-lookup, /<id>/sync  cve.org (Settings -> System switch)
  /api/v2/cases/<cid>/vulnerabilities                  case findings (case read / full access)
  /api/v2/cases/<cid>/vulnerabilities/decisions        decisions a finding on ?asset_id= may cite
  /api/v2/customer-assets/<id>/vulnerabilities         registry findings (customer access)
  /api/v2/war-rooms/<rid>/vulnerabilities              tracked entries (observer reads, responder writes)
  /api/v2/war-rooms/<rid>/scope/vulnerabilities        findings across the room's cases the viewer can open

Guests (portal sessions) are refused on every route, as on correlation.
Exposure and the list counts only count what the viewer may see. POST bodies
carry csrf_token like every v2 POST.
"""

from flask import Blueprint
from flask import request
from flask_login import current_user

from app import db
from app.blueprints.access_controls import ac_api_requires
from app.blueprints.access_controls import ac_api_return_access_denied
from app.blueprints.access_controls import ac_room_api_requires
from app.blueprints.responses import response_error
from app.blueprints.rest.endpoints import response_api_created
from app.blueprints.rest.endpoints import response_api_deleted
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
from app.business import vulnerabilities as vb
from app.business.errors import BusinessProcessingError
from app.business import vulnerability_findings as fb
from app.business.vulnerabilities import VulnError
from app.iris_engine.access_control.utils import ac_current_user_has_permission
from app.iris_engine.access_control.utils import ac_fast_check_current_user_has_case_access
from app.iris_engine.utils.tracker import track_activity
from app.iris_engine.vuln_cve_org import CveOrgError
from app.models.authorization import CaseAccessLevel
from app.models.authorization import Permissions
from app.models.models import Vulnerability
from app.models.models import VulnerabilityFinding

vulnerabilities_blueprint = Blueprint('rest_v2_vulnerabilities', __name__)

_CVE_STATUS = {'disabled': 409, 'invalid': 400, 'not_found': 404, 'unavailable': 502}


def _err(e):
    if isinstance(e, CveOrgError):
        return response_error(e.message, data={'reason': e.kind}, status=_CVE_STATUS.get(e.kind, 400))
    return response_error(e.message, data=e.data, status=e.status)


def _is_admin():
    return ac_current_user_has_permission(Permissions.server_administrator)


def _viewer():
    return vb.Viewer(current_user.id, _is_admin())


def _json():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _vuln_or_404(vid):
    return db.session.get(Vulnerability, vid)


# ================================================================= catalogue

@vulnerabilities_blueprint.route('/manage/vulnerabilities', methods=['GET'])
@ac_api_requires()
def list_vulnerabilities():
    viewer = _viewer()
    try:
        case_id = vb.case_filter(request.args, viewer)
        rows, total, page, per_page = vb.search_vulnerabilities(request.args, viewer, case_id=case_id)
    except VulnError as e:
        return _err(e)
    ids = [v.vulnerability_id for v in rows]
    counts = vb.counts_for(ids, viewer)
    data = [vb.vuln_row(v, counts.get(v.vulnerability_id)) for v in rows]
    if case_id is not None:
        in_case = vb.case_counts_for(ids, case_id)
        for d in data:
            d['case_counts'] = in_case.get(d['vulnerability_id'])
    last = max(1, (total + per_page - 1) // per_page)
    return response_api_success({
        'total': total, 'data': data, 'case': vb.case_label(case_id) if case_id is not None else None,
        'current_page': page, 'last_page': last, 'next_page': page + 1 if page < last else None,
    })


@vulnerabilities_blueprint.route('/manage/vulnerabilities/cases', methods=['GET'])
@ac_api_requires()
def vulnerability_cases():
    """The cases the viewer can open that hold findings (the list's Case filter)."""
    return response_api_success(vb.cases_with_findings(_viewer()))


@vulnerabilities_blueprint.route('/manage/vulnerabilities/vocab', methods=['GET'])
@ac_api_requires()
def vulnerability_vocab():
    from app.iris_engine.vuln_cve_org import lookup_enabled
    out = vb.vocab()
    out['cve_lookup_enabled'] = lookup_enabled()
    out['can_merge'] = _is_admin()
    return response_api_success(out)


@vulnerabilities_blueprint.route('/manage/vulnerabilities/technologies', methods=['GET'])
@ac_api_requires()
def vulnerability_technologies():
    return response_api_success(vb.technologies())


@vulnerabilities_blueprint.route('/manage/vulnerabilities/lookup', methods=['GET'])
@ac_api_requires()
def vulnerability_lookup():
    v = vb.find_by_identifier(request.args.get('identifier'))
    if v is None:
        return response_api_not_found()
    return response_api_success(vb.vuln_row(v, vb.counts_for([v.vulnerability_id], _viewer())[v.vulnerability_id]))


@vulnerabilities_blueprint.route('/manage/vulnerabilities/resolve', methods=['GET'])
@ac_api_requires()
def vulnerability_resolve():
    values = [x for x in (request.args.get('values') or '').split(',') if x.strip()]
    return response_api_success(vb.resolve_values(values))


@vulnerabilities_blueprint.route('/manage/vulnerabilities/cve-lookup', methods=['GET'])
@ac_api_requires()
def vulnerability_cve_lookup():
    try:
        return response_api_success(vb.cve_lookup(request.args.get('identifier') or ''))
    except (CveOrgError, VulnError) as e:
        return _err(e)


@vulnerabilities_blueprint.route('/manage/vulnerabilities', methods=['POST'])
@ac_api_requires()
def create_vulnerability():
    try:
        v = vb.create_vulnerability(_json(), current_user.id)
        db.session.commit()
    except VulnError as e:
        db.session.rollback()
        return _err(e)
    track_activity(f"created vulnerability '{v.identifier}'", ctx_less=True)
    return response_api_created(vb.vuln_row(v, vb.counts_for([v.vulnerability_id], _viewer())[v.vulnerability_id]))


@vulnerabilities_blueprint.route('/manage/vulnerabilities/<int:vid>', methods=['GET'])
@ac_api_requires()
def get_vulnerability(vid):
    v = _vuln_or_404(vid)
    if v is None:
        return response_api_not_found()
    return response_api_success(vb.vuln_row(v, vb.counts_for([vid], _viewer())[vid]))


@vulnerabilities_blueprint.route('/manage/vulnerabilities/<int:vid>', methods=['PUT'])
@ac_api_requires()
def update_vulnerability(vid):
    v = _vuln_or_404(vid)
    if v is None:
        return response_api_not_found()
    try:
        vb.update_vulnerability(v, _json(), current_user.id)
        db.session.commit()
    except VulnError as e:
        db.session.rollback()
        return _err(e)
    track_activity(f"updated vulnerability '{v.identifier}'", ctx_less=True)
    return response_api_success(vb.vuln_row(v, vb.counts_for([vid], _viewer())[vid]))


@vulnerabilities_blueprint.route('/manage/vulnerabilities/<int:vid>', methods=['DELETE'])
@ac_api_requires(Permissions.server_administrator)
def delete_vulnerability(vid):
    v = _vuln_or_404(vid)
    if v is None:
        return response_api_not_found()
    ident = v.identifier
    vb.delete_vulnerability(v)
    db.session.commit()
    track_activity(f"deleted vulnerability '{ident}'", ctx_less=True)
    return response_api_deleted()


@vulnerabilities_blueprint.route('/manage/vulnerabilities/<int:vid>/merge', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def merge_vulnerability(vid):
    source = _vuln_or_404(vid)
    if source is None:
        return response_api_not_found()
    try:
        target = db.session.get(Vulnerability, int(_json().get('target_id')))
    except (TypeError, ValueError):
        target = None
    if target is None:
        return response_error('Choose the entry to merge into.', status=400)
    ident = source.identifier
    try:
        result = vb.merge_vulnerabilities(source, target, current_user.id)
        db.session.commit()
    except VulnError as e:
        db.session.rollback()
        return _err(e)
    track_activity(f"merged vulnerability '{ident}' into '{target.identifier}'", ctx_less=True)
    out = vb.vuln_row(target, vb.counts_for([target.vulnerability_id], _viewer())[target.vulnerability_id])
    out['merge'] = result
    return response_api_success(out)


@vulnerabilities_blueprint.route('/manage/vulnerabilities/<int:vid>/sync', methods=['POST'])
@ac_api_requires()
def sync_vulnerability(vid):
    v = _vuln_or_404(vid)
    if v is None:
        return response_api_not_found()
    try:
        updated, kept = vb.sync_from_cve_org(v, current_user.id, force=bool(_json().get('force')))
        db.session.commit()
    except (CveOrgError, VulnError) as e:
        db.session.rollback()
        return _err(e)
    track_activity(f"synced vulnerability '{v.identifier}' from cve.org", ctx_less=True)
    out = vb.vuln_row(v, vb.counts_for([vid], _viewer())[vid])
    out['updated_fields'], out['kept_fields'] = updated, kept
    return response_api_success(out)


@vulnerabilities_blueprint.route('/manage/vulnerabilities/<int:vid>/exposure', methods=['GET'])
@ac_api_requires()
def vulnerability_exposure(vid):
    v = _vuln_or_404(vid)
    if v is None:
        return response_api_not_found()
    return response_api_success(vb.exposure(v, _viewer()))


# ================================================================= case findings

def _case_read(cid):
    return ac_fast_check_current_user_has_case_access(cid, [CaseAccessLevel.read_only, CaseAccessLevel.full_access])


def _case_write(cid):
    return ac_fast_check_current_user_has_case_access(cid, [CaseAccessLevel.full_access])


def _case_finding(cid, fid):
    f = db.session.get(VulnerabilityFinding, fid)
    if f is None or f.scope != 'case' or f.case_id != cid:
        return None
    return f


@vulnerabilities_blueprint.route('/cases/<int:cid>/vulnerabilities', methods=['GET'])
@ac_api_requires()
def list_case_findings(cid):
    if not _case_read(cid):
        return ac_api_return_access_denied(caseid=cid)
    try:
        return response_api_success(fb.list_case_findings(cid, request.args))
    except VulnError as e:
        return _err(e)


@vulnerabilities_blueprint.route('/cases/<int:cid>/vulnerabilities/assets', methods=['GET'])
@ac_api_requires()
def case_finding_asset_summary(cid):
    """Per-asset counts for the Assets page (tab count + list badge)."""
    if not _case_read(cid):
        return ac_api_return_access_denied(caseid=cid)
    return response_api_success(fb.case_asset_summary(cid))


@vulnerabilities_blueprint.route('/cases/<int:cid>/vulnerabilities/pickers', methods=['GET'])
@ac_api_requires()
def case_finding_pickers(cid):
    if not _case_read(cid):
        return ac_api_return_access_denied(caseid=cid)
    return response_api_success(fb.case_pickers(cid))


@vulnerabilities_blueprint.route('/cases/<int:cid>/vulnerabilities/decisions', methods=['GET'])
@ac_api_requires()
def case_finding_decisions(cid):
    """The approved war-room decisions a finding on `?asset_id=` may cite (the asset-flag rule)."""
    from app.models.models import CaseAssets
    if not _case_read(cid):
        return ac_api_return_access_denied(caseid=cid)
    raw = request.args.get('asset_id') or ''
    asset = db.session.get(CaseAssets, int(raw)) if raw.isdigit() else None
    if asset is None or asset.case_id != cid:
        return response_api_not_found()
    return response_api_success(fb.decision_choices(cid, asset.asset_id, current_user.id, _is_admin()))


@vulnerabilities_blueprint.route('/cases/<int:cid>/vulnerabilities', methods=['POST'])
@ac_api_requires()
def create_case_finding(cid):
    if not _case_write(cid):
        return ac_api_return_access_denied(caseid=cid)
    try:
        f = fb.create_finding('case', _json(), current_user.id, case_id=cid, is_admin=_is_admin())
        db.session.commit()
    except VulnError as e:
        db.session.rollback()
        return _err(e)
    row = fb.finding_row(f)
    where = f" on asset '{row.get('asset_name')}'" if row.get('asset_name') else ''
    track_activity(f"recorded vulnerability {row['vulnerability']['identifier']}{where}", caseid=cid)
    return response_api_created(row)


@vulnerabilities_blueprint.route('/cases/<int:cid>/vulnerabilities/<int:fid>', methods=['GET'])
@ac_api_requires()
def get_case_finding(cid, fid):
    if not _case_read(cid):
        return ac_api_return_access_denied(caseid=cid)
    f = _case_finding(cid, fid)
    if f is None:
        return response_api_not_found()
    return response_api_success(fb.finding_row(f))


@vulnerabilities_blueprint.route('/cases/<int:cid>/vulnerabilities/<int:fid>', methods=['PUT'])
@ac_api_requires()
def update_case_finding(cid, fid):
    if not _case_write(cid):
        return ac_api_return_access_denied(caseid=cid)
    f = _case_finding(cid, fid)
    if f is None:
        return response_api_not_found()
    try:
        fb.update_finding(f, _json(), current_user.id, is_admin=_is_admin())
        db.session.commit()
    except VulnError as e:
        db.session.rollback()
        return _err(e)
    row = fb.finding_row(f)
    track_activity(f"updated vulnerability finding {row['vulnerability']['identifier']}", caseid=cid)
    return response_api_success(row)


@vulnerabilities_blueprint.route('/cases/<int:cid>/vulnerabilities/<int:fid>', methods=['DELETE'])
@ac_api_requires()
def delete_case_finding(cid, fid):
    if not _case_write(cid):
        return ac_api_return_access_denied(caseid=cid)
    f = _case_finding(cid, fid)
    if f is None:
        return response_api_not_found()
    ident = f.vulnerability.identifier
    fb.delete_finding(f)
    db.session.commit()
    track_activity(f"removed vulnerability finding {ident}", caseid=cid)
    return response_api_deleted()


@vulnerabilities_blueprint.route('/cases/<int:cid>/vulnerabilities/<int:fid>/history', methods=['GET'])
@ac_api_requires()
def case_finding_history(cid, fid):
    if not _case_read(cid):
        return ac_api_return_access_denied(caseid=cid)
    f = _case_finding(cid, fid)
    if f is None:
        return response_api_not_found()
    return response_api_success(fb.finding_history(f))


# ================================================================= registry findings

def _registry_asset(asset_id):
    from app.datamgmt.manage.manage_access_control_db import user_has_client_access
    from app.models.models import CustomerAsset
    asset = db.session.get(CustomerAsset, asset_id)
    if asset is None or not user_has_client_access(current_user.id, asset.customer_id):
        return None
    return asset


def _registry_finding(asset_id, fid):
    f = db.session.get(VulnerabilityFinding, fid)
    if f is None or f.scope != 'registry' or f.customer_asset_id != asset_id:
        return None
    return f


@vulnerabilities_blueprint.route('/customer-assets/<int:asset_id>/vulnerabilities', methods=['GET'])
@ac_api_requires()
def list_registry_findings(asset_id):
    if _registry_asset(asset_id) is None:
        return response_api_not_found()
    try:
        return response_api_success(fb.list_registry_findings(asset_id, request.args))
    except VulnError as e:
        return _err(e)


@vulnerabilities_blueprint.route('/customer-assets/<int:asset_id>/vulnerabilities', methods=['POST'])
@ac_api_requires()
def create_registry_finding(asset_id):
    asset = _registry_asset(asset_id)
    if asset is None:
        return response_api_not_found()
    try:
        f = fb.create_finding('registry', _json(), current_user.id, customer_asset_id=asset_id,
                              is_admin=_is_admin())
        db.session.commit()
    except VulnError as e:
        db.session.rollback()
        return _err(e)
    row = fb.finding_row(f)
    track_activity(f"recorded vulnerability {row['vulnerability']['identifier']} on registry asset "
                   f"'{asset.asset_name}'", ctx_less=True)
    return response_api_created(row)


@vulnerabilities_blueprint.route('/customer-assets/<int:asset_id>/vulnerabilities/<int:fid>', methods=['PUT'])
@ac_api_requires()
def update_registry_finding(asset_id, fid):
    if _registry_asset(asset_id) is None:
        return response_api_not_found()
    f = _registry_finding(asset_id, fid)
    if f is None:
        return response_api_not_found()
    try:
        fb.update_finding(f, _json(), current_user.id, is_admin=_is_admin())
        db.session.commit()
    except VulnError as e:
        db.session.rollback()
        return _err(e)
    return response_api_success(fb.finding_row(f))


@vulnerabilities_blueprint.route('/customer-assets/<int:asset_id>/vulnerabilities/<int:fid>', methods=['DELETE'])
@ac_api_requires()
def delete_registry_finding(asset_id, fid):
    if _registry_asset(asset_id) is None:
        return response_api_not_found()
    f = _registry_finding(asset_id, fid)
    if f is None:
        return response_api_not_found()
    fb.delete_finding(f)
    db.session.commit()
    return response_api_deleted()


@vulnerabilities_blueprint.route('/customer-assets/<int:asset_id>/vulnerabilities/<int:fid>/history',
                                 methods=['GET'])
@ac_api_requires()
def registry_finding_history(asset_id, fid):
    if _registry_asset(asset_id) is None:
        return response_api_not_found()
    f = _registry_finding(asset_id, fid)
    if f is None:
        return response_api_not_found()
    return response_api_success(fb.finding_history(f))


# ================================================================= war rooms

def _room(room_id, min_role):
    from app.blueprints.rest.v2.war_rooms import _resolve
    return _resolve(room_id, min_role, guests=False)


def _room_cases(room):
    from app.business.war_rooms import room_visible_case_ids
    return room_visible_case_ids(room.id, current_user.id)


@vulnerabilities_blueprint.route('/war-rooms/<int:room_id>/vulnerabilities', methods=['GET'])
@ac_room_api_requires()
def room_tracked(room_id):
    room, _, err = _room(room_id, 'observer')
    if err is not None:
        return err
    return response_api_success(fb.room_tracked(room.id, _room_cases(room)))


@vulnerabilities_blueprint.route('/war-rooms/<int:room_id>/vulnerabilities', methods=['POST'])
@ac_room_api_requires()
def room_track(room_id):
    from app.business.war_rooms import _assert_writable
    room, _, err = _room(room_id, 'responder')
    if err is not None:
        return err
    try:
        _assert_writable(room)
        t = fb.track(room.id, _json(), current_user.id)
        db.session.commit()
    except VulnError as e:
        db.session.rollback()
        return _err(e)
    except BusinessProcessingError as e:  # a closed room
        db.session.rollback()
        return response_error(e.get_message() if hasattr(e, 'get_message') else str(e), status=400)
    rows = [r for r in fb.room_tracked(room.id, _room_cases(room)) if r['id'] == t.id]
    return response_api_created(rows[0] if rows else {'id': t.id})


@vulnerabilities_blueprint.route('/war-rooms/<int:room_id>/vulnerabilities/<int:vid>', methods=['PATCH'])
@ac_room_api_requires()
def room_track_note(room_id, vid):
    from app.business.war_rooms import _assert_writable
    room, _, err = _room(room_id, 'responder')
    if err is not None:
        return err
    t = fb.tracked_entry(room.id, vid)
    if t is None:
        return response_api_not_found()
    try:
        _assert_writable(room)
        fb.set_note(t, _json().get('note'))
        db.session.commit()
    except VulnError as e:
        db.session.rollback()
        return _err(e)
    except BusinessProcessingError as e:
        db.session.rollback()
        return response_error(e.get_message() if hasattr(e, 'get_message') else str(e), status=400)
    rows = [r for r in fb.room_tracked(room.id, _room_cases(room)) if r['id'] == t.id]
    return response_api_success(rows[0] if rows else {'id': t.id})


@vulnerabilities_blueprint.route('/war-rooms/<int:room_id>/vulnerabilities/<int:vid>', methods=['DELETE'])
@ac_room_api_requires()
def room_untrack(room_id, vid):
    from app.business.war_rooms import _assert_writable
    room, _, err = _room(room_id, 'responder')
    if err is not None:
        return err
    t = fb.tracked_entry(room.id, vid)
    if t is None:
        return response_api_not_found()
    try:
        _assert_writable(room)
    except BusinessProcessingError as e:
        return response_error(e.get_message() if hasattr(e, 'get_message') else str(e), status=400)
    db.session.delete(t)
    db.session.commit()
    return response_api_deleted()


@vulnerabilities_blueprint.route('/war-rooms/<int:room_id>/scope/vulnerabilities', methods=['GET'])
@ac_room_api_requires()
def room_scope(room_id):
    room, _, err = _room(room_id, 'observer')
    if err is not None:
        return err
    try:
        return response_api_success(fb.room_matrix(room.id, _room_cases(room), request.args))
    except VulnError as e:
        return _err(e)

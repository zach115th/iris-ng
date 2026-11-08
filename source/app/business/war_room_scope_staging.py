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

"""The war-room Scope's staging inbox and Assets Manager attachments (iris-ng 2026-11-08).

Staging: an asset or an IOC typed into the room before it lands in a case - kept with the attached cases it is
proposed for (war_room_staged_object), edited, discarded, or pushed: created in its target cases through their own
create paths. The row goes once every target case holds it. Members read the inbox; responders and leads of an
open room change it; guests never get the Scope.

Assets Manager: customer-registry assets put in the room's scope (war_room_registry_asset), with or without one of
the room's cases. A user sees the ones of customers they have access to and a count of the others (decided
2026-11-08); attaching, linking and detaching need that access too. A push copies one into attached cases as a case
asset (name, type, compromise status, and the IP / domain / tags / description of its latest sighting); flags stay on
case assets. Detaching keeps the registry entry.
"""
from datetime import datetime

from app import db
from app.business.war_room_scope import COMPROMISE
from app.business.war_room_scope import ScopeError
from app.business.war_room_scope import _guard
from app.business.war_room_scope import _ids
from app.business.war_room_scope import _iso
from app.business.war_room_scope import _linked_targets
from app.business.war_room_scope import _tally
from app.business.war_room_scope import _writable
from app.business.war_room_scope import case_result
from app.business.war_room_scope import check_cross_customer
from app.business.war_room_scope import clean_asset_payload
from app.business.war_room_scope import clean_ioc_payload
from app.business.war_room_scope import create_in_case
from app.business.war_room_scope import present_in
from app.models import asset_flag_vocab as af


def _user_name(u):
    return (u.name or u.user) if u is not None else None


def _case_names(case_ids):
    from app.business import war_room_board as wb
    return {c: (m or (None,))[0] for c, m in wb._case_meta(list(case_ids)).items()}


# =========================================================================== staging

def _clean(kind, raw):
    return clean_asset_payload(raw) if kind == 'asset' else clean_ioc_payload(raw)


def _staged_targets(room, raw):
    from app.business.war_rooms import room_case_ids
    if raw in (None, []):
        return []
    linked = set(room_case_ids(room.id))
    targets = _ids(raw, 'case', af.SCOPE_STAGED_TARGETS_MAX)
    bad = [c for c in targets if c not in linked]
    if bad:
        raise ScopeError('Case #%d is not attached to this war room.' % bad[0])
    return targets


def _note(raw):
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ScopeError('note is text.')
    raw = raw.strip()
    if len(raw) > 2000:
        raise ScopeError('note is 2000 characters at most.')
    return raw or None


def _staged(room, sid):
    from app.models.models import WarRoomStagedObject
    s = db.session.get(WarRoomStagedObject, sid)
    if s is None or s.room_id != room.id:
        raise ScopeError('Unknown staged object.', status=404)
    return s


def staged_row(s, visible, names):
    """A staged object as the inbox shows it; a target the viewer cannot open is named by its id only."""
    p = s.payload or {}
    targets = []
    for cid in s.target_case_ids or []:
        seen = cid in visible
        targets.append({'case_id': cid, 'case_name': names.get(cid) if seen else None, 'visible': seen,
                        'present': present_in(s.kind, cid, p) if seen else None})
    return {'id': s.id, 'kind': s.kind, 'payload': p,
            'label': p.get('asset_name') if s.kind == 'asset' else p.get('ioc_value'),
            'targets': targets, 'note': s.note, 'created_by': _user_name(s.creator), 'created_at': _iso(s.created_at),
            'updated_by': _user_name(s.editor), 'updated_at': _iso(s.updated_at)}


def list_staged(room, viewer_id):
    from app.business.war_rooms import room_visible_case_ids
    from app.models.models import WarRoomStagedObject
    visible = set(room_visible_case_ids(room.id, viewer_id))
    rows = (WarRoomStagedObject.query.filter(WarRoomStagedObject.room_id == room.id)
            .order_by(WarRoomStagedObject.created_at.desc(), WarRoomStagedObject.id.desc()).all())
    names = _case_names({c for s in rows for c in (s.target_case_ids or [])} & visible)
    return {'staged': [staged_row(s, visible, names) for s in rows], 'max_targets': af.SCOPE_STAGED_TARGETS_MAX}


def create_staged(room, user, body):
    """{kind: asset|ioc, payload, target_case_ids, note}"""
    from app.models.models import WarRoomStagedObject
    _guard(room)
    kind = body.get('kind')
    if kind not in af.SCOPE_STAGED_KINDS:
        raise ScopeError('kind is one of %s.' % ', '.join(af.SCOPE_STAGED_KINDS))
    if WarRoomStagedObject.query.filter(WarRoomStagedObject.room_id == room.id).count() >= af.SCOPE_STAGED_MAX:
        raise ScopeError('The staging inbox holds %d objects at most: push or discard some first.' % af.SCOPE_STAGED_MAX)
    s = WarRoomStagedObject(room_id=room.id, kind=kind, payload=_clean(kind, body.get('payload')),
                            target_case_ids=_staged_targets(room, body.get('target_case_ids')),
                            note=_note(body.get('note')), created_by=user.id)
    db.session.add(s)
    db.session.commit()
    return s


def update_staged(room, user, sid, body):
    """Any of {payload (merged over the stored one), target_case_ids, note}."""
    _guard(room)
    s = _staged(room, sid)
    if 'payload' in body:
        if not isinstance(body['payload'], dict):
            raise ScopeError('payload is an object.')
        s.payload = _clean(s.kind, dict(s.payload or {}, **body['payload']))
    if 'target_case_ids' in body:
        s.target_case_ids = _staged_targets(room, body.get('target_case_ids'))
    if 'note' in body:
        s.note = _note(body.get('note'))
    s.updated_by, s.updated_at = user.id, datetime.utcnow()
    db.session.commit()
    return s


def delete_staged(room, sid):
    _guard(room)
    s = _staged(room, sid)
    db.session.delete(s)
    db.session.commit()


def push_staged(room, user, sid, body):
    """{case_ids (default: its targets), confirm_cross_customer}: creates it in each case; once every target case
    holds it the staged row goes ('removed'). One result per case: created / exists / refused."""
    _guard(room)
    s = _staged(room, sid)
    raw = body.get('case_ids')
    targets = _linked_targets(room, raw if raw not in (None, []) else (s.target_case_ids or None))
    check_cross_customer(targets, body)
    writable = _writable(user.id, targets)
    payload = dict(s.payload or {})
    results = []
    for cid in targets:
        if cid not in writable:
            results.append(case_result(cid, 'refused', 'You cannot change case #%d' % cid))
            continue
        status, oid, err = create_in_case(s.kind, cid, payload)
        results.append(case_result(cid, status, err, object_id=oid))
    wanted = set(s.target_case_ids or []) | set(targets)
    removed = all(present_in(s.kind, c, payload) for c in wanted)
    if removed:
        db.session.delete(s)
    else:
        s.target_case_ids = sorted(wanted)
    db.session.commit()
    return {'results': results, 'counts': _tally(results), 'removed': removed}


# =========================================================================== Assets Manager attachments

def _client_ids(viewer_id, is_admin):
    """None = every customer (a server administrator); otherwise the customers the user has access to."""
    from app.datamgmt.manage.manage_access_control_db import get_user_clients_id
    if is_admin:
        return None
    return set(get_user_clients_id(viewer_id) or [])


def _may(client_ids, customer_id):
    return client_ids is None or customer_id in client_ids


def registry_rows(room, viewer_id, is_admin):
    """(the attachments the viewer may see, how many others there are)."""
    from app.business.war_rooms import room_case_ids
    from app.business.war_rooms import room_visible_case_ids
    from app.models.models import CustomerAsset
    from app.models.models import VulnerabilityFinding
    from app.models.models import WarRoomRegistryAsset
    from app.models import vulnerability_vocab as vv
    links = (WarRoomRegistryAsset.query.filter(WarRoomRegistryAsset.room_id == room.id)
             .order_by(WarRoomRegistryAsset.added_at.desc(), WarRoomRegistryAsset.id.desc()).all())
    if not links:
        return [], 0
    allowed = _client_ids(viewer_id, is_admin)
    assets = {a.id: a for a in CustomerAsset.query.filter(CustomerAsset.id.in_([x.customer_asset_id for x in links]))}
    shown = [x for x in links if x.customer_asset_id in assets and _may(allowed, assets[x.customer_asset_id].customer_id)]
    linked = set(room_case_ids(room.id))
    visible = set(room_visible_case_ids(room.id, viewer_id))
    names = _case_names({x.case_id for x in shown if x.case_id in visible})
    open_by = {}
    if shown:
        for caid, n in (db.session.query(VulnerabilityFinding.customer_asset_id, db.func.count(VulnerabilityFinding.finding_id))
                        .filter(VulnerabilityFinding.scope == 'registry',
                                VulnerabilityFinding.customer_asset_id.in_([x.customer_asset_id for x in shown]),
                                VulnerabilityFinding.remediation_status.in_(vv.REMEDIATION_GROUPS['open']))
                        .group_by(VulnerabilityFinding.customer_asset_id)):
            open_by[caid] = n
    rows = []
    for x in shown:
        a = assets[x.customer_asset_id]
        case = None
        if x.case_id is not None and x.case_id in linked:
            case = {'case_id': x.case_id, 'case_name': names.get(x.case_id) if x.case_id in visible else None,
                    'visible': x.case_id in visible}
        rows.append({'id': x.id, 'customer_asset_id': a.id, 'asset_name': a.asset_name, 'asset_type_id': a.asset_type_id,
                     'asset_type': a.asset_type.asset_name if a.asset_type else None, 'customer_id': a.customer_id,
                     'customer_name': a.customer.name if a.customer else None, 'criticality': a.criticality,
                     'environment': a.environment, 'compromise': COMPROMISE.get(a.compromise_status),
                     'case': case, 'note': x.note, 'added_by': _user_name(x.adder), 'added_at': _iso(x.added_at),
                     'open_findings': open_by.get(a.id, 0), 'href': '/manage/customer-assets?asset=%d' % a.id})
    return rows, len(links) - len(shown)


def list_registry(room, viewer_id, is_admin):
    rows, hidden = registry_rows(room, viewer_id, is_admin)
    return {'assets': rows, 'hidden': hidden, 'max_attach': af.SCOPE_REGISTRY_ATTACH_MAX}


def _case_link(room, raw):
    from app.business.war_rooms import room_case_ids
    if raw in (None, ''):
        return None
    if isinstance(raw, bool) or not str(raw).isdigit():
        raise ScopeError('case_id is a case id.')
    if int(raw) not in set(room_case_ids(room.id)):
        raise ScopeError('Case #%d is not attached to this war room.' % int(raw))
    return int(raw)


def attach_registry(room, user, is_admin, body):
    """{customer_asset_ids, case_id, note}: one result per registry asset - attached / exists / refused (unknown,
    or a customer the user has no access to)."""
    from app.models.models import CustomerAsset
    from app.models.models import WarRoomRegistryAsset
    _guard(room)
    ids = _ids(body.get('customer_asset_ids'), 'registry asset', af.SCOPE_REGISTRY_ATTACH_MAX)
    case_id = _case_link(room, body.get('case_id'))
    note = _note(body.get('note'))
    allowed = _client_ids(user.id, is_admin)
    assets = {a.id: a for a in CustomerAsset.query.filter(CustomerAsset.id.in_(ids))}
    have = {x.customer_asset_id for x in WarRoomRegistryAsset.query.filter(WarRoomRegistryAsset.room_id == room.id,
                                                                           WarRoomRegistryAsset.customer_asset_id.in_(ids))}
    results = []
    for caid in ids:
        a = assets.get(caid)
        if a is None or not _may(allowed, a.customer_id):
            results.append({'customer_asset_id': caid, 'asset_name': None, 'status': 'refused',
                            'error': 'Unknown registry asset'})
            continue
        if caid in have:
            results.append({'customer_asset_id': caid, 'asset_name': a.asset_name, 'status': 'exists', 'error': None})
            continue
        db.session.add(WarRoomRegistryAsset(room_id=room.id, customer_asset_id=caid, case_id=case_id, note=note,
                                            added_by=user.id))
        have.add(caid)
        results.append({'customer_asset_id': caid, 'asset_name': a.asset_name, 'status': 'attached', 'error': None})
    db.session.commit()
    return {'results': results, 'counts': _tally(results)}


def _attachment(room, user_id, is_admin, lid):
    from app.models.models import WarRoomRegistryAsset
    x = db.session.get(WarRoomRegistryAsset, lid)
    if x is None or x.room_id != room.id or x.customer_asset is None \
            or not _may(_client_ids(user_id, is_admin), x.customer_asset.customer_id):
        raise ScopeError('Unknown attachment.', status=404)
    return x


def update_registry(room, user, is_admin, lid, body):
    """Any of {case_id (null unlinks), note}."""
    _guard(room)
    x = _attachment(room, user.id, is_admin, lid)
    if 'case_id' in body:
        x.case_id = _case_link(room, body.get('case_id'))
    if 'note' in body:
        x.note = _note(body.get('note'))
    db.session.commit()
    return x


def detach_registry(room, user, is_admin, lid):
    _guard(room)
    x = _attachment(room, user.id, is_admin, lid)
    db.session.delete(x)
    db.session.commit()


def push_registry(room, user, is_admin, lid, body):
    """{case_ids, confirm_cross_customer}: the registry asset copied into those attached cases as a case asset -
    name, type, compromise status and its latest sighting's IP, domain, tags and description. The registry asset's
    own customer counts in the cross-customer check."""
    from app.datamgmt.manage.customer_assets_db import latest_observation
    _guard(room)
    x = _attachment(room, user.id, is_admin, lid)
    a = x.customer_asset
    targets = _linked_targets(room, body.get('case_ids'))
    check_cross_customer(targets, body, extra={a.customer_id: a.customer.name if a.customer else None})
    seen = latest_observation(a)
    payload = clean_asset_payload({'asset_name': a.asset_name, 'asset_type_id': a.asset_type_id,
                                   'asset_compromise_status_id': a.compromise_status if a.compromise_status in COMPROMISE else 0,
                                   'asset_ip': seen.get('ip'), 'asset_domain': seen.get('domain'),
                                   'asset_tags': seen.get('tags'), 'asset_description': seen.get('description')})
    writable = _writable(user.id, targets)
    results = []
    for cid in targets:
        if cid not in writable:
            results.append(case_result(cid, 'refused', 'You cannot change case #%d' % cid))
            continue
        status, oid, err = create_in_case('asset', cid, payload)
        results.append(case_result(cid, status, err, asset_id=oid))
    return {'results': results, 'counts': _tally(results)}

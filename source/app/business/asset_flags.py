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

"""Asset flags (iris-ng 2026-11-07; Settings -> Asset flags, the case Assets page).

A flag is an administrator-defined status fact set on case assets: a name, a
colour, an icon and a kind - status (a fact), done (nothing left to do; the
war-room Board counts it as done) or exception (an accepted gap; the Board
highlights it). Unlike tags they are a managed list with a history.

Rules:
  * the catalogue is read by every user (the Assets page needs it) and written
    by server administrators only (the routes enforce it - no new permission);
  * names are unique ignoring case; presets add the flags whose name is free;
  * setting (or clearing) a flag that "requires a reason" needs a written
    reason; a flag that "requires a decision" must cite an APPROVED decision of
    a war room the case is attached to, which applies to that room (no case /
    asset chosen), to that case or to that asset - and the person setting it
    must belong to that room (a room's register is room data);
  * every set / update / clear writes a case_asset_flag_change row, an entry in
    the asset's own history and a line in the case log.
The callers (REST routes) check case access before calling anything here.
"""

from datetime import datetime

from sqlalchemy import func

from app import db
from app.models import asset_flag_vocab as af
from app.models.models import AssetFlag
from app.models.models import CaseAssetFlag
from app.models.models import CaseAssetFlagChange


class FlagError(Exception):
    def __init__(self, message, status=400, data=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.data = data


def _iso(value):
    """Stored datetimes are naive UTC: say so."""
    return value.isoformat() + 'Z' if value is not None else None


def _text(value, field, limit, required=False):
    if value is not None and not isinstance(value, str):
        raise FlagError('%s must be text.' % field)
    value = (value or '').strip()
    if required and not value:
        raise FlagError('%s is required.' % field)
    if len(value) > limit:
        raise FlagError('%s is longer than %d characters.' % (field, limit))
    return value or None


def _bool(value, field):
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raise FlagError('%s must be true or false.' % field)


# ---------------------------------------------------------------- catalogue

def flag_row(f, in_use=None):
    d = {'id': f.id, 'name': f.name, 'description': f.description, 'color': f.color, 'icon': f.icon,
         'kind': f.kind, 'requires_reason': bool(f.requires_reason), 'requires_decision': bool(f.requires_decision),
         'sort_order': f.sort_order}
    if in_use is not None:
        d['in_use_count'] = in_use
    return d


def list_flags(with_counts=False):
    flags = AssetFlag.query.order_by(AssetFlag.sort_order, AssetFlag.id).all()
    counts = {}
    if with_counts and flags:
        counts = dict(db.session.query(CaseAssetFlag.flag_id, func.count()).group_by(CaseAssetFlag.flag_id).all())
    return [flag_row(f, counts.get(f.id, 0) if with_counts else None) for f in flags]


def vocab():
    return {
        'colors': list(af.COLORS), 'icons': list(af.ICONS),
        'kinds': [{'value': k, 'label': af.KIND_LABELS[k], 'description': af.KIND_DESCRIPTIONS[k]} for k in af.KINDS],
        'presets': [{'id': p['id'], 'label': p['label'], 'summary': ', '.join(x['name'] for x in p['flags'])}
                    for p in af.PRESETS],
        'name_max': af.NAME_MAX, 'reason_max': af.REASON_MAX,
    }


def _name_taken(name, exclude_id=None):
    q = AssetFlag.query.filter(func.lower(AssetFlag.name) == name.lower())
    if exclude_id is not None:
        q = q.filter(AssetFlag.id != exclude_id)
    return q.first()


def _apply(f, p, creating):
    if not isinstance(p, dict):
        raise FlagError('Expected a JSON object.')
    if creating or 'name' in p:
        name = _text(p.get('name'), 'The name', af.NAME_MAX, required=True)
        other = _name_taken(name, None if creating else f.id)
        if other is not None:
            raise FlagError('A flag named "%s" already exists.' % other.name, status=409,
                            data={'existing_id': other.id})
        f.name = name
    if creating or 'description' in p:
        f.description = _text(p.get('description'), 'The description', 1000)
    for field, values, default in (('color', af.COLORS, 'slate'), ('icon', af.ICONS, 'flag'),
                                   ('kind', af.KINDS, 'status')):
        if creating or field in p:
            v = p.get(field) or default
            if v not in values:
                raise FlagError('Unknown %s %r.' % (field, v))
            setattr(f, field, v)
    for field in ('requires_reason', 'requires_decision'):
        if creating or field in p:
            setattr(f, field, _bool(p.get(field), field.replace('_', ' ').capitalize()))


def create_flag(payload, user_id):
    f = AssetFlag()
    _apply(f, payload, True)
    top = db.session.query(func.max(AssetFlag.sort_order)).scalar()
    f.sort_order = (top if top is not None else -1) + 1
    f.created_by_id = user_id
    db.session.add(f)
    db.session.flush()
    return f


def update_flag(f, payload, user_id):
    _apply(f, payload, False)
    f.updated_at = datetime.utcnow()
    f.updated_by_id = user_id
    db.session.flush()
    return f


def delete_flag(f):
    """Deletes the flag and removes it from every asset (the history keeps its name)."""
    db.session.delete(f)
    db.session.flush()


def reorder(ids):
    if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise FlagError('ids must be a list of flag ids.')
    flags = {f.id: f for f in AssetFlag.query.all()}
    if sorted(ids) != sorted(flags) or len(set(ids)) != len(ids):
        raise FlagError('ids must name every flag exactly once.')
    for n, i in enumerate(ids):
        flags[i].sort_order = n
    db.session.flush()


def apply_preset(preset_id, user_id):
    """Adds the preset's flags whose name is not taken (any letter case); never changes or removes one.
    Returns (the full list, the names added)."""
    preset = next((p for p in af.PRESETS if p['id'] == preset_id), None)
    if preset is None:
        raise FlagError('Unknown preset %r.' % preset_id, status=404)
    added = []
    for spec in preset['flags']:
        if _name_taken(spec['name']) is None:
            create_flag(dict(spec), user_id)
            added.append(spec['name'])
    return added


# ---------------------------------------------------------------- flags on assets

def _decision_ref(d):
    return 'D-%d' % d.number if d is not None else None


def assignment_row(a, flag=None, decisions=None):
    flag = flag or a.flag
    d = None
    if a.decision_id is not None:
        d = (decisions or {}).get(a.decision_id)
        if d is None:
            from app.models.models import WarRoomDecision
            d = db.session.get(WarRoomDecision, a.decision_id)
    return {'flag_id': a.flag_id, 'name': flag.name if flag else None, 'color': flag.color if flag else None,
            'icon': flag.icon if flag else None, 'kind': flag.kind if flag else None,
            'reason': a.reason, 'set_at': _iso(a.set_at), 'set_by_id': a.set_by_id,
            'decision_id': a.decision_id, 'decision_ref': _decision_ref(d),
            'decision_room_id': d.room_id if d is not None else None,
            'decision_title': d.title if d is not None else None}


def flags_for_case(case_id):
    """{asset_id: [assignment rows in the catalogue's order]} - one query for the Assets page."""
    from app.models.models import WarRoomDecision
    rows = (db.session.query(CaseAssetFlag, AssetFlag)
            .join(AssetFlag, AssetFlag.id == CaseAssetFlag.flag_id)
            .filter(CaseAssetFlag.case_id == case_id)
            .order_by(AssetFlag.sort_order, AssetFlag.id).all())
    dec_ids = {a.decision_id for a, _ in rows if a.decision_id is not None}
    decisions = {d.id: d for d in WarRoomDecision.query.filter(WarRoomDecision.id.in_(dec_ids))} if dec_ids else {}
    out = {}
    for a, f in rows:
        out.setdefault(a.asset_id, []).append(assignment_row(a, f, decisions))
    return out


def flags_for_asset(asset_id):
    rows = (db.session.query(CaseAssetFlag, AssetFlag).join(AssetFlag, AssetFlag.id == CaseAssetFlag.flag_id)
            .filter(CaseAssetFlag.asset_id == asset_id).order_by(AssetFlag.sort_order, AssetFlag.id).all())
    return [assignment_row(a, f) for a, f in rows]


def decision_candidates(case_id, asset_id, user_id, is_admin):
    """The approved decisions a flag on this asset may cite: rooms the case is attached to and the user
    belongs to (any room for an administrator), deciding for the whole room, for this case or for this asset."""
    from app.models.models import WarRoom
    from app.models.models import WarRoomCaseLink
    from app.models.models import WarRoomDecision
    from app.models.models import WarRoomDecisionAsset
    from app.models.models import WarRoomDecisionCase
    from app.models.models import WarRoomMember
    room_ids = [r for (r,) in db.session.query(WarRoomCaseLink.room_id).filter(WarRoomCaseLink.case_id == case_id)]
    if not is_admin and room_ids:
        mine = {r for (r,) in db.session.query(WarRoomMember.room_id).filter(
            WarRoomMember.user_id == user_id, WarRoomMember.room_id.in_(room_ids))}
        room_ids = [r for r in room_ids if r in mine]
    if not room_ids:
        return []
    decisions = (WarRoomDecision.query.filter(WarRoomDecision.room_id.in_(room_ids),
                                              WarRoomDecision.status == 'approved')
                 .order_by(WarRoomDecision.room_id, WarRoomDecision.number).all())
    if not decisions:
        return []
    ids = [d.id for d in decisions]
    cases = {}
    for did, cid in db.session.query(WarRoomDecisionCase.decision_id, WarRoomDecisionCase.case_id).filter(
            WarRoomDecisionCase.decision_id.in_(ids)):
        cases.setdefault(did, set()).add(cid)
    assets = {}
    for did, aid in db.session.query(WarRoomDecisionAsset.decision_id, WarRoomDecisionAsset.asset_id).filter(
            WarRoomDecisionAsset.decision_id.in_(ids)):
        assets.setdefault(did, set()).add(aid)
    rooms = {r.id: r.name for r in WarRoom.query.filter(WarRoom.id.in_(room_ids))}
    out = []
    for d in decisions:
        c, a = cases.get(d.id, set()), assets.get(d.id, set())
        if (not c and not a) or case_id in c or asset_id in a:
            scope = 'room' if (not c and not a) else ('asset' if asset_id in a else 'case')
            out.append({'decision_id': d.id, 'ref': _decision_ref(d), 'title': d.title, 'room_id': d.room_id,
                        'room_name': rooms.get(d.room_id), 'applies': scope})
    return out


def _check_decision(flag, decision_id, case_id, asset_id, user_id, is_admin):
    if not flag.requires_decision:
        if decision_id not in (None, ''):
            raise FlagError('"%s" does not take a decision.' % flag.name)
        return None
    if decision_id in (None, ''):
        raise FlagError('"%s" requires an approved war-room decision.' % flag.name)
    try:
        decision_id = int(decision_id)
    except (TypeError, ValueError):
        raise FlagError('Unknown decision.')
    allowed = {c['decision_id']: c for c in decision_candidates(case_id, asset_id, user_id, is_admin)}
    if decision_id not in allowed:
        raise FlagError('The decision must be an approved decision of a war room this case is attached to (and '
                        'you belong to), deciding for the room, this case or this asset.')
    return decision_id


def _record(case_id, asset, flag, action, reason, decision_id, user_id):
    from app.models.models import WarRoomDecision
    d = db.session.get(WarRoomDecision, decision_id) if decision_id else None
    db.session.add(CaseAssetFlagChange(case_id=case_id, asset_id=asset.asset_id, flag_id=flag.id,
                                       flag_name=flag.name, action=action, reason=reason,
                                       decision_id=decision_id, decision_ref=_decision_ref(d),
                                       changed_by=user_id))


def _history_text(flag, action, reason, decision_ref):
    verb = {'set': 'set', 'updated': 'updated', 'cleared': 'cleared'}[action]
    out = 'flag "%s" %s' % (flag.name, verb)
    if decision_ref:
        out += ' (decision %s)' % decision_ref
    if reason:
        out += ': %s' % (reason if len(reason) <= 120 else reason[:117] + '...')
    return out


def set_flag(case_id, asset, flag, payload, user, is_admin):
    """Sets the flag on the asset, or updates its reason / decision when it is already set.
    Returns (assignment row, action or None when nothing changed)."""
    from app.util import add_obj_history_entry
    p = payload if isinstance(payload, dict) else {}
    reason = _text(p.get('reason'), 'The reason', af.REASON_MAX)
    if flag.requires_reason and not reason:
        raise FlagError('"%s" needs a reason.' % flag.name)
    decision_id = _check_decision(flag, p.get('decision_id'), case_id, asset.asset_id, user.id, is_admin)
    a = CaseAssetFlag.query.filter_by(asset_id=asset.asset_id, flag_id=flag.id).first()
    if a is None:
        a = CaseAssetFlag(case_id=case_id, asset_id=asset.asset_id, flag_id=flag.id, reason=reason,
                          decision_id=decision_id, set_at=datetime.utcnow(), set_by_id=user.id)
        db.session.add(a)
        action = 'set'
    elif (a.reason or None) == reason and a.decision_id == decision_id:
        return assignment_row(a, flag), None
    else:
        a.reason, a.decision_id = reason, decision_id
        action = 'updated'
    db.session.flush()
    _record(case_id, asset, flag, action, reason, decision_id, user.id)
    row = assignment_row(a, flag)
    add_obj_history_entry(asset, _history_text(flag, action, reason, row['decision_ref']), user=user)
    db.session.flush()
    return row, action


def clear_flag(case_id, asset, flag, payload, user):
    """Removes the flag from the asset. A flag that requires a reason needs one to be cleared too."""
    from app.util import add_obj_history_entry
    p = payload if isinstance(payload, dict) else {}
    a = CaseAssetFlag.query.filter_by(asset_id=asset.asset_id, flag_id=flag.id).first()
    if a is None:
        raise FlagError('"%s" is not set on this asset.' % flag.name, status=404)
    reason = _text(p.get('reason'), 'The reason', af.REASON_MAX)
    if flag.requires_reason and not reason:
        raise FlagError('Removing "%s" needs a reason.' % flag.name)
    db.session.delete(a)
    db.session.flush()
    _record(case_id, asset, flag, 'cleared', reason, None, user.id)
    add_obj_history_entry(asset, _history_text(flag, 'cleared', reason, None), user=user)
    db.session.flush()


def flag_history(asset_id):
    from app.models.authorization import User
    rows = (db.session.query(CaseAssetFlagChange, User.name)
            .outerjoin(User, User.id == CaseAssetFlagChange.changed_by)
            .filter(CaseAssetFlagChange.asset_id == asset_id)
            .order_by(CaseAssetFlagChange.changed_at.desc(), CaseAssetFlagChange.id.desc()).all())
    return [{'id': c.id, 'flag_id': c.flag_id, 'flag_name': c.flag_name, 'action': c.action, 'reason': c.reason,
             'decision_id': c.decision_id, 'decision_ref': c.decision_ref, 'changed_by': c.changed_by,
             'changed_by_name': name, 'changed_at': _iso(c.changed_at)} for c, name in rows]


def history_counts(case_id):
    """{asset_id: number of flag changes} for the Assets page's "N changes" link."""
    return dict(db.session.query(CaseAssetFlagChange.asset_id, func.count())
                .filter(CaseAssetFlagChange.case_id == case_id).group_by(CaseAssetFlagChange.asset_id).all())


def activity_text(flag, asset_name, action, reason):
    verb = {'set': 'set flag', 'updated': 'updated flag', 'cleared': 'cleared flag'}[action]
    out = '%s "%s" on asset "%s"' % (verb, flag.name, asset_name)
    if reason:
        out += ' (%s)' % (reason if len(reason) <= 80 else reason[:77] + '...')
    return out

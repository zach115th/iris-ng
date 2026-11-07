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

"""War-room decisions (iris-ng 2026-11-07; the room's Decisions tab).

The register of what a war room decided: D-<n> per room, a title, a rationale,
an owner, a target date and time, optional approvers, what it applies to (the
whole room, or chosen cases / assets of the attached cases), its implementation
and the decision it supersedes. Rules:

  * status: proposed -> approved once EVERY named approver approves, rejected as
    soon as one rejects (votes are taken while proposed only); with no approver
    a lead or the owner sets approved / rejected by hand, from proposed only.
    Approved and rejected are final; an approved decision becomes superseded
    when a decision superseding it is approved. Only approved decisions can be
    marked implemented (and reopened), superseded, or cited by an asset flag;
  * proposing needs the responder role; editing is for leads, the owner and the
    proposer; approvers and what it applies to change while proposed only;
    deleting is for leads, and refused while an asset flag cites the decision;
  * approvers and the owner are room members (users); the cases and assets it
    applies to must be attached to the room and readable by whoever chooses them;
    a viewer who cannot read a case sees it as restricted;
  * guests read the register (routes) and never propose, vote or edit;
  * a closed room is read-only; every change writes a trail row
    (war_room_decision_event) that the room stream reads.
"""

import re
from datetime import datetime
from datetime import timezone

from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import text

from app import db
from app.models import asset_flag_vocab as af
from app.models.models import WarRoomDecision
from app.models.models import WarRoomDecisionApprover
from app.models.models import WarRoomDecisionAsset
from app.models.models import WarRoomDecisionCase
from app.models.models import WarRoomDecisionEvent


class DecisionError(Exception):
    def __init__(self, message, status=400, data=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.data = data


def _iso(value):
    return value.isoformat() + 'Z' if value is not None else None


def _now():
    return datetime.utcnow()


def ref(d):
    return 'D-%d' % d.number


def is_open(d):
    return d.status in ('proposed', 'approved') and d.implemented_at is None


def is_overdue(d, now=None):
    return bool(is_open(d) and d.target_at is not None and d.target_at < (now or _now()))


def _writable(room):
    if room.status == 'closed':
        raise DecisionError('Room is closed')


def _members(room_id):
    from app.models.models import WarRoomMember
    return {m for (m,) in db.session.query(WarRoomMember.user_id).filter(WarRoomMember.room_id == room_id)}


def _event(d, action, user_id, detail=None):
    db.session.add(WarRoomDecisionEvent(decision_id=d.id, room_id=d.room_id, action=action, detail=detail,
                                        user_id=user_id, at=_now()))


def _parse_target(value):
    """A target date and time: ISO with an offset or Z, or naive (read as UTC). Stored naive UTC."""
    if value in (None, ''):
        return None
    if not isinstance(value, str):
        raise DecisionError('The target must be a date and time.')
    v = value.strip()
    try:
        dt = datetime.fromisoformat(v[:-1] + '+00:00' if v.endswith('Z') else v)
    except ValueError:
        raise DecisionError('Invalid target date & time.')
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(microsecond=0)


def _ids(value, field):
    if value is None:
        return []
    if not isinstance(value, list):
        raise DecisionError('%s must be a list of ids.' % field)
    out = []
    for v in value:
        try:
            i = int(v)
        except (TypeError, ValueError):
            raise DecisionError('%s must be a list of ids.' % field)
        if i not in out:
            out.append(i)
    return out


def _text(value, field, limit, required=False):
    if value is not None and not isinstance(value, str):
        raise DecisionError('%s must be text.' % field)
    value = (value or '').strip()
    if required and not value:
        raise DecisionError('A title is required' if field == 'The title' else '%s is required.' % field)
    if len(value) > limit:
        raise DecisionError('%s is too long (%d characters max).' % (field, limit))
    return value or None


def _scope_checked(room, case_ids, asset_ids, actor_id):
    """Cases / assets a decision may apply to: attached to the room AND readable by the actor."""
    from app.business.war_rooms import room_visible_case_ids
    from app.models.models import CaseAssets
    visible = set(room_visible_case_ids(room.id, actor_id))
    for c in case_ids:
        if c not in visible:
            raise DecisionError('Case #%d is not attached to this room or you cannot open it.' % c)
    if asset_ids:
        found = {a.asset_id: a.case_id for a in CaseAssets.query.filter(CaseAssets.asset_id.in_(asset_ids))}
        for a in asset_ids:
            if found.get(a) not in visible:
                raise DecisionError('Asset #%d is not in a case of this room you can open.' % a)


def _next_number(room_id):
    # one numbering per room: the room row lock serialises concurrent proposals
    db.session.execute(text('SELECT id FROM war_room WHERE id = :id FOR UPDATE'), {'id': room_id})
    top = db.session.query(func.max(WarRoomDecision.number)).filter(WarRoomDecision.room_id == room_id).scalar()
    return (top or 0) + 1


def _approvers(d):
    return WarRoomDecisionApprover.query.filter_by(decision_id=d.id).all()


def _set_approvers(d, ids, room_id):
    members = _members(room_id)
    for u in ids:
        if u not in members:
            raise DecisionError('Approvers must be members of the war room.')
    current = {a.user_id: a for a in _approvers(d)}
    for u, a in current.items():
        if u not in ids:
            db.session.delete(a)
    added = [u for u in ids if u not in current]
    for u in added:
        db.session.add(WarRoomDecisionApprover(decision_id=d.id, user_id=u, verdict='pending'))
    return added


def _set_scope(d, case_ids, asset_ids):
    WarRoomDecisionCase.query.filter_by(decision_id=d.id).delete()
    WarRoomDecisionAsset.query.filter_by(decision_id=d.id).delete()
    for c in case_ids:
        db.session.add(WarRoomDecisionCase(decision_id=d.id, case_id=c))
    for a in asset_ids:
        db.session.add(WarRoomDecisionAsset(decision_id=d.id, asset_id=a))


def _approve(d, user_id):
    d.status = 'approved'
    d.decided_at = _now()
    _event(d, 'approved', user_id)
    if d.supersedes_id:
        old = db.session.get(WarRoomDecision, d.supersedes_id)
        if old is not None and old.status == 'approved':
            old.status = 'superseded'
            old.updated_at = _now()
            _event(old, 'superseded', user_id, 'by %s' % ref(d))


def _reject(d, user_id):
    d.status = 'rejected'
    d.decided_at = _now()
    _event(d, 'rejected', user_id)


def _evaluate(d, user_id):
    """Every approver approved -> approved; one rejected -> rejected; else still proposed."""
    if d.status != 'proposed':
        return
    verdicts = [a.verdict for a in _approvers(d)]
    if not verdicts:
        return
    if 'rejected' in verdicts:
        _reject(d, user_id)
    elif all(v == 'approved' for v in verdicts):
        _approve(d, user_id)


def _notify_approvers(room, d, user_ids, actor_id):
    if not user_ids:
        return
    from app.business.notifications import notify
    notify('decision_approval_requested', list(user_ids),
           'Decision %s awaits your approval in "%s"' % (ref(d), room.name), body=d.title,
           object_type='war_room', object_id=room.id,
           url='/war-rooms/%d?pane=decisions&d=%d' % (room.id, d.id), actor_id=actor_id)


def _may_edit(d, user_id, role):
    return role == 'lead' or user_id in (d.owner_id, d.created_by_id)


# ---------------------------------------------------------------- writes

def create_decision(room, payload, user_id, role):
    from app.models.models import WarRoomMessage
    _writable(room)
    p = payload if isinstance(payload, dict) else {}
    title = _text(p.get('title'), 'The title', af.DECISION_TITLE_MAX, required=True)
    rationale = _text(p.get('rationale'), 'The rationale', af.DECISION_RATIONALE_MAX)
    target = _parse_target(p.get('target_at'))
    owner = p.get('owner_id')
    owner = user_id if owner in (None, '') else owner
    try:
        owner = int(owner)
    except (TypeError, ValueError):
        raise DecisionError('Unknown owner.')
    if owner not in _members(room.id):
        raise DecisionError('The owner must be a member of the war room.')
    approver_ids = _ids(p.get('approver_ids'), 'approver_ids')
    case_ids = _ids(p.get('case_ids'), 'case_ids')
    asset_ids = _ids(p.get('asset_ids'), 'asset_ids')
    _scope_checked(room, case_ids, asset_ids, user_id)
    supersedes = None
    if p.get('supersedes_id') not in (None, ''):
        supersedes = db.session.get(WarRoomDecision, _ids([p.get('supersedes_id')], 'supersedes_id')[0])
        if supersedes is None or supersedes.room_id != room.id:
            raise DecisionError('Unknown decision to supersede.')
        if supersedes.status != 'approved':
            raise DecisionError('Only an approved decision can be superseded.')
    msg = None
    if p.get('chat_message_id') not in (None, ''):
        msg = db.session.get(WarRoomMessage, _ids([p.get('chat_message_id')], 'chat_message_id')[0])
        if msg is None or msg.room_id != room.id or msg.kind != 'decision':
            raise DecisionError('Only a /decision message of this room can be promoted.')
        if WarRoomDecision.query.filter_by(chat_message_id=msg.id).first() is not None:
            raise DecisionError('This /decision message is already in the register.', status=409)
    d = WarRoomDecision(room_id=room.id, number=_next_number(room.id), title=title, rationale=rationale,
                        status='proposed', owner_id=owner, target_at=target,
                        supersedes_id=supersedes.id if supersedes else None,
                        chat_message_id=msg.id if msg else None, created_by_id=user_id, created_at=_now())
    db.session.add(d)
    db.session.flush()
    added = _set_approvers(d, approver_ids, room.id)
    _set_scope(d, case_ids, asset_ids)
    _event(d, 'promoted' if msg else 'proposed', user_id,
           ('supersedes %s' % ref(supersedes)) if supersedes else None)
    db.session.flush()
    return d, added


def update_decision(room, d, payload, user_id, role):
    """Returns the approver ids added (to notify after the commit)."""
    _writable(room)
    if not _may_edit(d, user_id, role):
        raise DecisionError('Only a lead, the owner or the proposer can change this decision.', status=403)
    if d.status == 'superseded':
        raise DecisionError('A superseded decision cannot be changed.')
    p = payload if isinstance(payload, dict) else {}
    changed, added = [], []
    if 'title' in p:
        v = _text(p.get('title'), 'The title', af.DECISION_TITLE_MAX, required=True)
        if v != d.title:
            d.title = v
            changed.append('title')
    if 'rationale' in p:
        v = _text(p.get('rationale'), 'The rationale', af.DECISION_RATIONALE_MAX)
        if v != d.rationale:
            d.rationale = v
            changed.append('rationale')
    if 'target_at' in p:
        v = _parse_target(p.get('target_at'))
        if v != d.target_at:
            d.target_at = v
            changed.append('target')
    if 'owner_id' in p:
        try:
            v = int(p.get('owner_id'))
        except (TypeError, ValueError):
            raise DecisionError('Unknown owner.')
        if v != d.owner_id:
            if v not in _members(room.id):
                raise DecisionError('The owner must be a member of the war room.')
            d.owner_id = v
            changed.append('owner')
    if any(k in p for k in ('approver_ids', 'case_ids', 'asset_ids')) and d.status != 'proposed':
        raise DecisionError('Approvers and what the decision applies to change while it is proposed only.')
    if 'approver_ids' in p:
        ids = _ids(p.get('approver_ids'), 'approver_ids')
        before = sorted(a.user_id for a in _approvers(d))
        added = _set_approvers(d, ids, room.id)
        if sorted(ids) != before:
            changed.append('approvers')
    if 'case_ids' in p or 'asset_ids' in p:
        case_ids = _ids(p.get('case_ids'), 'case_ids') if 'case_ids' in p else sorted(
            c for (c,) in db.session.query(WarRoomDecisionCase.case_id).filter_by(decision_id=d.id))
        asset_ids = _ids(p.get('asset_ids'), 'asset_ids') if 'asset_ids' in p else sorted(
            a for (a,) in db.session.query(WarRoomDecisionAsset.asset_id).filter_by(decision_id=d.id))
        _scope_checked(room, case_ids, asset_ids, user_id)
        _set_scope(d, case_ids, asset_ids)
        changed.append('applies to')
    status = p.get('status')
    if status not in (None, '', d.status):
        if status not in ('approved', 'rejected'):
            raise DecisionError('The status can only be set to approved or rejected.')
        if d.status != 'proposed':
            raise DecisionError('Only a proposed decision can be approved or rejected.')
        db.session.flush()
        if _approvers(d):
            raise DecisionError('This decision has approvers: their votes decide it.')
        if not (role == 'lead' or user_id == d.owner_id):
            raise DecisionError('Only a lead or the owner can decide it.', status=403)
        _event(d, 'status_set', user_id, status)
        (_approve if status == 'approved' else _reject)(d, user_id)
    if changed:
        _event(d, 'edited', user_id, ', '.join(changed))
    d.updated_at, d.updated_by_id = _now(), user_id
    db.session.flush()
    _evaluate(d, user_id)
    db.session.flush()
    return added


def vote(room, d, user_id, verdict):
    _writable(room)
    if verdict not in ('approved', 'rejected'):
        raise DecisionError('The verdict is approved or rejected.')
    if d.status != 'proposed':
        raise DecisionError('Votes are taken while the decision is proposed.')
    a = WarRoomDecisionApprover.query.filter_by(decision_id=d.id, user_id=user_id).first()
    if a is None:
        raise DecisionError('You are not an approver of this decision.', status=403)
    a.verdict, a.voted_at = verdict, _now()
    _event(d, 'vote_approved' if verdict == 'approved' else 'vote_rejected', user_id)
    db.session.flush()
    _evaluate(d, user_id)
    db.session.flush()


def set_implemented(room, d, user_id, role, done=True):
    _writable(room)
    if not (role == 'lead' or user_id == d.owner_id):
        raise DecisionError('Only a lead or the owner can change the implementation.', status=403)
    if d.status != 'approved':
        raise DecisionError('Only an approved decision is implemented.')
    if done:
        if d.implemented_at is not None:
            raise DecisionError('Already implemented.')
        d.implemented_at, d.implemented_by_id = _now(), user_id
        _event(d, 'implemented', user_id)
    else:
        if d.implemented_at is None:
            raise DecisionError('Not implemented.')
        d.implemented_at, d.implemented_by_id = None, None
        _event(d, 'reopened', user_id)
    db.session.flush()


def cited_by(d):
    from app.models.models import CaseAssetFlag
    return CaseAssetFlag.query.filter_by(decision_id=d.id).count()


def delete_decision(room, d):
    _writable(room)
    n = cited_by(d)
    if n:
        raise DecisionError('%s is cited by %d asset flag(s): clear those flags, or supersede the decision.'
                            % (ref(d), n), status=409, data={'cited_by': n})
    db.session.delete(d)
    db.session.flush()


# ---------------------------------------------------------------- reads

def _names(user_ids):
    from app.models.authorization import User
    ids = {u for u in user_ids if u is not None}
    return {u.id: u.name for u in User.query.filter(User.id.in_(ids))} if ids else {}


def rows(decisions, viewer_id, role, is_guest, visible_case_ids, detail=False):
    """Serialised decisions with the viewer's permissions. `visible_case_ids` decide which cases / assets
    show by name (the rest are restricted)."""
    from app.iris_engine.safe_markdown import render_markdown_safe
    from app.models.cases import Cases
    from app.models.models import CaseAssets
    from app.models.models import CaseAssetFlag
    if not decisions:
        return []
    ids = [d.id for d in decisions]
    approvers, cases, assets = {}, {}, {}
    for a in WarRoomDecisionApprover.query.filter(WarRoomDecisionApprover.decision_id.in_(ids)):
        approvers.setdefault(a.decision_id, []).append(a)
    for c in WarRoomDecisionCase.query.filter(WarRoomDecisionCase.decision_id.in_(ids)):
        cases.setdefault(c.decision_id, []).append(c.case_id)
    for a in WarRoomDecisionAsset.query.filter(WarRoomDecisionAsset.decision_id.in_(ids)):
        assets.setdefault(a.decision_id, []).append(a.asset_id)
    visible = set(visible_case_ids or [])
    all_cases = {c for v in cases.values() for c in v}
    case_names = {c.case_id: c.name for c in Cases.query.filter(Cases.case_id.in_(all_cases))} if all_cases else {}
    all_assets = {a for v in assets.values() for a in v}
    asset_rows = ({a.asset_id: a for a in CaseAssets.query.filter(CaseAssets.asset_id.in_(all_assets))}
                  if all_assets else {})
    by_id = {d.id: d for d in WarRoomDecision.query.filter(WarRoomDecision.room_id == decisions[0].room_id)}
    superseded_by = {}
    for x in by_id.values():
        if x.supersedes_id:
            superseded_by.setdefault(x.supersedes_id, []).append(x)
    cites = dict(db.session.query(CaseAssetFlag.decision_id, func.count()).filter(
        CaseAssetFlag.decision_id.in_(ids)).group_by(CaseAssetFlag.decision_id).all())
    people = _names([d.owner_id for d in decisions] + [d.created_by_id for d in decisions]
                    + [d.implemented_by_id for d in decisions]
                    + [a.user_id for v in approvers.values() for a in v])
    now = _now()
    out = []
    for d in decisions:
        apps = sorted(approvers.get(d.id, []), key=lambda a: people.get(a.user_id, '').lower())
        mine = next((a for a in apps if a.user_id == viewer_id), None)
        editable = not is_guest and d.status != 'superseded' and _may_edit(d, viewer_id, role)
        lead_or_owner = not is_guest and (role == 'lead' or viewer_id == d.owner_id)
        row = {
            'decision_id': d.id, 'room_id': d.room_id, 'number': d.number, 'ref': ref(d), 'title': d.title,
            'status': d.status, 'owner_id': d.owner_id, 'owner_name': people.get(d.owner_id),
            'target_at': _iso(d.target_at), 'is_overdue': is_overdue(d, now), 'is_open': is_open(d),
            'decided_at': _iso(d.decided_at), 'implemented_at': _iso(d.implemented_at),
            'implemented_by_name': people.get(d.implemented_by_id),
            'approvers': [{'user_id': a.user_id, 'name': people.get(a.user_id), 'verdict': a.verdict,
                           'voted_at': _iso(a.voted_at)} for a in apps],
            'case_ids': sorted(cases.get(d.id, [])), 'asset_ids': sorted(assets.get(d.id, [])),
            'cases': [{'case_id': c, 'case_name': case_names.get(c) if c in visible else None,
                       'restricted': c not in visible} for c in sorted(cases.get(d.id, []))],
            'assets': [{'asset_id': a,
                        'asset_name': asset_rows[a].asset_name if a in asset_rows and asset_rows[a].case_id in visible
                        else None,
                        'case_id': asset_rows[a].case_id if a in asset_rows and asset_rows[a].case_id in visible
                        else None,
                        'restricted': not (a in asset_rows and asset_rows[a].case_id in visible)}
                       for a in sorted(assets.get(d.id, []))],
            'whole_room': not cases.get(d.id) and not assets.get(d.id),
            'supersedes': ({'decision_id': d.supersedes_id, 'ref': ref(by_id[d.supersedes_id]),
                            'title': by_id[d.supersedes_id].title} if d.supersedes_id in by_id else None),
            'superseded_by': [{'decision_id': x.id, 'ref': ref(x), 'status': x.status}
                              for x in sorted(superseded_by.get(d.id, []), key=lambda x: x.number)],
            'chat_message_id': d.chat_message_id, 'created_at': _iso(d.created_at),
            'created_by_name': people.get(d.created_by_id), 'cited_by_flags': cites.get(d.id, 0),
            'my_verdict': mine.verdict if mine else None,
            'can': {
                'edit': editable,
                'vote': not is_guest and mine is not None and d.status == 'proposed',
                'set_status': lead_or_owner and d.status == 'proposed' and not apps,
                'implement': lead_or_owner and d.status == 'approved',
                'supersede': not is_guest and role in ('responder', 'lead') and d.status == 'approved',
                'delete': not is_guest and role == 'lead',
            },
        }
        if detail:
            row['rationale'] = d.rationale
            row['rationale_html'] = render_markdown_safe(d.rationale) if d.rationale else ''
            row['trail'] = trail(d)
        out.append(row)
    return out


def trail(d):
    evs = (WarRoomDecisionEvent.query.filter_by(decision_id=d.id)
           .order_by(WarRoomDecisionEvent.at, WarRoomDecisionEvent.id).all())
    names = _names([e.user_id for e in evs])
    return [{'action': e.action, 'detail': e.detail, 'user_name': names.get(e.user_id), 'at': _iso(e.at)}
            for e in evs]


def list_decisions(room_id, args):
    q = WarRoomDecision.query.filter(WarRoomDecision.room_id == room_id)
    st = (args.get('status') or '').strip().lower()
    now = _now()
    if st in af.DECISION_STATUSES:
        q = q.filter(WarRoomDecision.status == st)
    elif st == 'open':
        q = q.filter(WarRoomDecision.status.in_(('proposed', 'approved')), WarRoomDecision.implemented_at.is_(None))
    elif st == 'overdue':
        q = q.filter(WarRoomDecision.status.in_(('proposed', 'approved')), WarRoomDecision.implemented_at.is_(None),
                     WarRoomDecision.target_at < now)
    elif st == 'implemented':
        q = q.filter(WarRoomDecision.implemented_at.isnot(None))
    elif st:
        raise DecisionError('Unknown status filter %r.' % st)
    if args.get('case_id'):
        try:
            cid = int(args['case_id'])
        except ValueError:
            raise DecisionError('case_id must be a number.')
        q = q.filter(WarRoomDecision.id.in_(
            db.session.query(WarRoomDecisionCase.decision_id).filter(WarRoomDecisionCase.case_id == cid)))
    search = (args.get('q') or '').strip()
    if search:
        from app.models.authorization import User
        m = re.match(r'^[Dd]-?(\d+)$', search)
        like = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        conds = [WarRoomDecision.title.ilike(like),
                 WarRoomDecision.owner_id.in_(db.session.query(User.id).filter(User.name.ilike(like)))]
        if m:
            conds.append(WarRoomDecision.number == int(m.group(1)))
        q = q.filter(or_(*conds))
    return q.order_by(WarRoomDecision.number.desc()).all()


def chat_candidates(room_id):
    """/decision chat messages of the room not in the register yet, newest first."""
    from app.business.war_rooms import actor_label
    from app.models.models import WarRoomMessage
    linked = db.session.query(WarRoomDecision.chat_message_id).filter(WarRoomDecision.chat_message_id.isnot(None))
    msgs = (WarRoomMessage.query.filter(WarRoomMessage.room_id == room_id, WarRoomMessage.kind == 'decision',
                                        WarRoomMessage.id.notin_(linked))
            .order_by(WarRoomMessage.id.desc()).limit(200).all())
    return [{'message_id': m.id, 'content': m.content, 'author': actor_label(m.user, m.guest),
             'created_at': _iso(m.created_at)} for m in msgs]


def asset_candidates(room_id, viewer_id, q, guest=False):
    """Assets of the attached cases the viewer can open, matching q (name, IP, domain), for "Applies to"."""
    from app.business.war_rooms import room_visible_case_ids
    from app.models.cases import Cases
    from app.models.models import CaseAssets
    visible = room_visible_case_ids(room_id, viewer_id, guest=guest)
    if not visible:
        return []
    query = (db.session.query(CaseAssets.asset_id, CaseAssets.asset_name, CaseAssets.case_id, Cases.name)
             .join(Cases, Cases.case_id == CaseAssets.case_id).filter(CaseAssets.case_id.in_(visible)))
    q = (q or '').strip()
    if q:
        like = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.filter(or_(CaseAssets.asset_name.ilike(like), CaseAssets.asset_ip.ilike(like),
                                 CaseAssets.asset_domain.ilike(like)))
    return [{'asset_id': a, 'asset_name': n, 'case_id': c, 'case_name': cn}
            for a, n, c, cn in query.order_by(func.lower(CaseAssets.asset_name)).limit(50).all()]


_STREAM_TEXT = {
    'proposed': '%(who)s proposed %(ref)s "%(title)s"',
    'promoted': '%(who)s registered %(ref)s "%(title)s" from a /decision message',
    'approved': '%(ref)s "%(title)s" was approved',
    'rejected': '%(ref)s "%(title)s" was rejected',
    'superseded': '%(ref)s "%(title)s" was superseded %(detail)s',
    'implemented': '%(who)s marked %(ref)s "%(title)s" implemented',
    'reopened': '%(who)s reopened the implementation of %(ref)s "%(title)s"',
}


def stream_items(room_id):
    """The room stream's decision lines (derived from the trail, like every system line)."""
    evs = (db.session.query(WarRoomDecisionEvent, WarRoomDecision)
           .join(WarRoomDecision, WarRoomDecision.id == WarRoomDecisionEvent.decision_id)
           .filter(WarRoomDecisionEvent.room_id == room_id,
                   WarRoomDecisionEvent.action.in_(tuple(_STREAM_TEXT))).all())
    names = _names([e.user_id for e, _ in evs])
    return [{'kind': 'decision', 'decision_id': d.id, 'action': e.action,
             'content': _STREAM_TEXT[e.action] % {'who': names.get(e.user_id) or 'someone', 'ref': ref(d),
                                                  'title': d.title, 'detail': e.detail or ''},
             'created_at': e.at} for e, d in evs]


def notify_added_approvers(room, d, added, actor_id):
    _notify_approvers(room, d, added, actor_id)

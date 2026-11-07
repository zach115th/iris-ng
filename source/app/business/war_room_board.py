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

"""The war-room Board (iris-ng 2026-11-07; the room's Board tab).

A board of widgets over the room: indicators, what needs attention, assets by
flag (the asset-flag kinds: done / exception), one card per attached case, open
decisions, open tasks, vulnerabilities and Markdown notes. A lead sets the
room's layout for everyone (war_room_board; no row = the default board);
anyone can hide or reorder widgets for themselves in their browser.

Every figure is computed by the server from stored rows, over the attached cases
THE VIEWER can read (room_visible_case_ids: a user's case ACL; a guest reads
every attached case). Guests get the board without links into case pages
(their portal session cannot open them) and without "awaiting your vote".
"""

import re
from datetime import datetime

from sqlalchemy import func

from app import db
from app.models import asset_flag_vocab as af
from app.models.models import WarRoomBoard

_ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,39}$')
_OPTIONS = {
    'indicators': {}, 'attention': {}, 'cases': {}, 'decisions': {}, 'vulnerabilities': {},
    'flags': {'of_total': bool},
    'tasks': {'team_ids': list, 'in_progress_only': bool},
    'note': {'text': str},
}


class BoardError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _iso(value):
    return value.isoformat() + 'Z' if value is not None else None


def default_widgets():
    return [{'id': 'w-%s' % t, 'type': t, 'column': col, 'title': None, 'options': {}} for t, col in af.BOARD_DEFAULT]


def widget_types():
    return [{'type': t, 'label': v[0], 'column': v[1], 'description': v[2]} for t, v in af.BOARD_WIDGETS.items()]


def validate_widgets(widgets):
    if not isinstance(widgets, list):
        raise BoardError('widgets must be a list.')
    if len(widgets) > af.BOARD_MAX_WIDGETS:
        raise BoardError('A board holds %d widgets at most.' % af.BOARD_MAX_WIDGETS)
    out, seen = [], set()
    for w in widgets:
        if not isinstance(w, dict):
            raise BoardError('Every widget is an object.')
        wid, typ = w.get('id'), w.get('type')
        if not isinstance(wid, str) or not _ID_RE.match(wid) or wid in seen:
            raise BoardError('Every widget needs a unique id (a-z, 0-9, -).')
        seen.add(wid)
        if typ not in af.BOARD_WIDGETS:
            raise BoardError('Unknown widget type %r.' % typ)
        col = w.get('column') or af.BOARD_WIDGETS[typ][1]
        if col not in af.BOARD_COLUMNS:
            raise BoardError('Unknown column %r.' % col)
        title = w.get('title')
        if title is not None and not isinstance(title, str):
            raise BoardError('A widget title is text.')
        title = (title or '').strip() or None
        if title and len(title) > af.BOARD_TITLE_MAX:
            raise BoardError('A widget title is %d characters at most.' % af.BOARD_TITLE_MAX)
        opts_in = w.get('options') or {}
        if not isinstance(opts_in, dict):
            raise BoardError('Widget options are an object.')
        allowed, opts = _OPTIONS[typ], {}
        for k, v in opts_in.items():
            if k not in allowed:
                raise BoardError('Unknown option %r for a %s widget.' % (k, typ))
            if allowed[k] is bool:
                if not isinstance(v, bool):
                    raise BoardError('%s must be true or false.' % k)
            elif allowed[k] is list:
                if not isinstance(v, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in v):
                    raise BoardError('%s must be a list of ids.' % k)
                v = sorted(set(v))
            elif allowed[k] is str:
                if not isinstance(v, str):
                    raise BoardError('%s must be text.' % k)
                if len(v) > af.BOARD_NOTE_MAX:
                    raise BoardError('A note is %d characters at most.' % af.BOARD_NOTE_MAX)
            opts[k] = v
        out.append({'id': wid, 'type': typ, 'column': col, 'title': title, 'options': opts})
    return out


def get_layout(room_id):
    row = db.session.get(WarRoomBoard, room_id)
    if row is None or not isinstance(row.widgets, list):
        return default_widgets(), True
    return row.widgets, False


def set_layout(room, widgets, user_id):
    """widgets None = back to the default board."""
    if room.status == 'closed':
        raise BoardError('Room is closed')
    row = db.session.get(WarRoomBoard, room.id)
    if widgets is None:
        if row is not None:
            db.session.delete(row)
        db.session.flush()
        return default_widgets(), True
    clean = validate_widgets(widgets)
    if row is None:
        row = WarRoomBoard(room_id=room.id)
        db.session.add(row)
    row.widgets = clean
    row.updated_at, row.updated_by_id = datetime.utcnow(), user_id
    db.session.flush()
    return clean, False


# ---------------------------------------------------------------- the figures

def _assets(case_ids):
    from app.models.models import CaseAssets
    if not case_ids:
        return []
    return (db.session.query(CaseAssets.asset_id, CaseAssets.asset_name, CaseAssets.case_id,
                             CaseAssets.asset_compromise_status_id)
            .filter(CaseAssets.case_id.in_(case_ids)).all())


def _flag_rows(asset_ids):
    from app.models.models import AssetFlag
    from app.models.models import CaseAssetFlag
    if not asset_ids:
        return []
    return (db.session.query(CaseAssetFlag.asset_id, CaseAssetFlag.reason, AssetFlag)
            .join(AssetFlag, AssetFlag.id == CaseAssetFlag.flag_id)
            .filter(CaseAssetFlag.asset_id.in_(asset_ids)).all())


def _vuln_figures(case_ids):
    from app.models import vulnerability_vocab as vv
    from app.models.models import Vulnerability
    from app.models.models import VulnerabilityFinding
    per_case = {c: {'open': 0, 'exploited_open': 0} for c in case_ids}
    tot = {'open': 0, 'exploited_open': 0, 'overdue': 0, 'kev_open': 0, 'vulnerable_assets': 0}
    if not case_ids:
        return tot, per_case
    rows = (db.session.query(VulnerabilityFinding.case_id, VulnerabilityFinding.asset_id,
                             VulnerabilityFinding.exploitation_status, VulnerabilityFinding.due_date, Vulnerability.kev)
            .join(Vulnerability, Vulnerability.vulnerability_id == VulnerabilityFinding.vulnerability_id)
            .filter(VulnerabilityFinding.scope == 'case', VulnerabilityFinding.case_id.in_(case_ids),
                    VulnerabilityFinding.remediation_status.in_(vv.REMEDIATION_GROUPS['open'])).all())
    today = datetime.utcnow().date()
    assets = set()
    for cid, aid, exploitation, due, kev in rows:
        tot['open'] += 1
        per_case[cid]['open'] += 1
        assets.add(aid)
        if exploitation == 'exploited':
            tot['exploited_open'] += 1
            per_case[cid]['exploited_open'] += 1
        if due is not None and due < today:
            tot['overdue'] += 1
        if kev:
            tot['kev_open'] += 1
    tot['vulnerable_assets'] = len(assets)
    return tot, per_case


def _tasks(room_id):
    from app.business.war_rooms import actor_label
    from app.models.models import WarRoomTask
    from app.models.models import WarRoomTeam
    from app.models.models import WarRoomTeamGuest
    from app.models.models import WarRoomTeamMember
    teams = WarRoomTeam.query.filter_by(room_id=room_id).order_by(func.lower(WarRoomTeam.name)).all()
    team_of_user, team_of_guest = {}, {}
    if teams:
        tids = [t.id for t in teams]
        for m in WarRoomTeamMember.query.filter(WarRoomTeamMember.team_id.in_(tids)):
            team_of_user.setdefault(m.user_id, []).append(m.team_id)
        for g in WarRoomTeamGuest.query.filter(WarRoomTeamGuest.team_id.in_(tids)):
            team_of_guest.setdefault(g.guest_id, []).append(g.team_id)
    now = datetime.utcnow()
    tasks = (WarRoomTask.query.filter(WarRoomTask.room_id == room_id,
                                      WarRoomTask.status.notin_(('done', 'cancelled'))).all())
    rows = []
    for t in tasks:
        team_ids = sorted(team_of_user.get(t.assignee_id, []) if t.assignee_id else
                          team_of_guest.get(t.assignee_guest_id, []) if t.assignee_guest_id else [])
        rows.append({'id': t.id, 'title': t.title, 'status': t.status,
                     'assignee': actor_label(t.assignee, t.assignee_guest, None),
                     'due_date': _iso(t.due_date), 'overdue': bool(t.due_date and t.due_date < now),
                     'team_ids': team_ids})
    rows.sort(key=lambda r: (r['status'] != 'in_progress', not r['overdue'], r['due_date'] or '9999', r['id']))
    return rows, [{'id': t.id, 'name': t.name, 'color': t.color} for t in teams]


def board_data(room, viewer_id, is_guest):
    from app.business import war_room_decisions as wd
    from app.business.war_rooms import room_visible_case_ids
    from app.models.cases import Cases
    from app.models.cases import CaseState
    from app.models.models import AssetFlag
    from app.models.models import WarRoomDecision
    from app.models.models import WarRoomDecisionApprover
    visible = room_visible_case_ids(room.id, viewer_id, guest=is_guest)
    assets = _assets(visible)
    flags_by_asset = {}
    for aid, reason, f in _flag_rows([a[0] for a in assets]):
        flags_by_asset.setdefault(aid, []).append((f, reason))
    catalogue = AssetFlag.query.order_by(AssetFlag.sort_order, AssetFlag.id).all()
    by_flag = {f.id: 0 for f in catalogue}
    totals = {'assets': len(assets), 'done': 0, 'exceptions': 0, 'no_flag': 0, 'compromised': 0}
    per_case = {c: {'assets': 0, 'done': 0, 'exceptions': 0, 'compromised': 0} for c in visible}
    attention = []

    def link(**kw):
        return None if is_guest else kw

    case_names = {c.case_id: c.name for c in Cases.query.filter(Cases.case_id.in_(visible))} if visible else {}
    for aid, name, cid, comp in assets:
        fl = flags_by_asset.get(aid, [])
        kinds = {f.kind for f, _ in fl}
        done, exc = 'done' in kinds, 'exception' in kinds
        pc = per_case[cid]
        pc['assets'] += 1
        for f, _ in fl:
            by_flag[f.id] = by_flag.get(f.id, 0) + 1
        if done:
            totals['done'] += 1
            pc['done'] += 1
        if exc:
            totals['exceptions'] += 1
            pc['exceptions'] += 1
            for f, reason in fl:
                if f.kind == 'exception':
                    attention.append({'type': 'asset_exception', 'severity': 'warning',
                                      'text': '%s: %s%s' % (name, f.name, (' - %s' % reason) if reason else ''),
                                      'case_name': case_names.get(cid),
                                      'link': link(href='/case/assets?cid=%d&asset=%d&tab=details' % (cid, aid))})
        if not fl:
            totals['no_flag'] += 1
        if comp == 1 and not done:
            totals['compromised'] += 1
            pc['compromised'] += 1
            attention.append({'type': 'asset_compromised', 'severity': 'danger',
                              'text': '%s is compromised and not done yet' % name, 'case_name': case_names.get(cid),
                              'link': link(href='/case/assets?cid=%d&asset=%d&tab=details' % (cid, aid))})

    vtot, vper = _vuln_figures(visible)
    for cid in visible:
        if vper[cid]['exploited_open']:
            attention.append({'type': 'vulnerabilities_exploited', 'severity': 'danger',
                              'text': '%d exploited vulnerabilit%s not fixed yet' % (
                                  vper[cid]['exploited_open'], 'y' if vper[cid]['exploited_open'] == 1 else 'ies'),
                              'case_name': case_names.get(cid), 'link': link(href='/vulnerabilities?case=%d' % cid)})

    now = datetime.utcnow()
    decisions = (WarRoomDecision.query.filter(WarRoomDecision.room_id == room.id,
                                              WarRoomDecision.status.in_(('proposed', 'approved')),
                                              WarRoomDecision.implemented_at.is_(None)).all())
    pending_mine = set()
    if not is_guest and decisions:
        pending_mine = {a.decision_id for a in WarRoomDecisionApprover.query.filter(
            WarRoomDecisionApprover.decision_id.in_([d.id for d in decisions]),
            WarRoomDecisionApprover.user_id == viewer_id, WarRoomDecisionApprover.verdict == 'pending')}
    owners = wd._names([d.owner_id for d in decisions])
    dec_rows = []
    for d in decisions:
        over = wd.is_overdue(d, now)
        mine = d.id in pending_mine and d.status == 'proposed'
        dec_rows.append({'decision_id': d.id, 'ref': wd.ref(d), 'title': d.title, 'status': d.status,
                         'target_at': _iso(d.target_at), 'is_overdue': over, 'owner_name': owners.get(d.owner_id),
                         'awaiting_me': mine})
        if over:
            attention.append({'type': 'decision_overdue', 'severity': 'danger',
                              'text': '%s "%s" is past its target' % (wd.ref(d), d.title),
                              'link': {'pane': 'decisions', 'decision_id': d.id}})
        if mine:
            attention.append({'type': 'decision_vote', 'severity': 'info',
                              'text': '%s "%s" awaits your vote' % (wd.ref(d), d.title),
                              'link': {'pane': 'decisions', 'decision_id': d.id}})
    dec_rows.sort(key=lambda r: (not r['is_overdue'], r['target_at'] or '9999', -r['decision_id']))

    tasks, teams = _tasks(room.id)
    for t in tasks:
        if t['overdue']:
            attention.append({'type': 'task_overdue', 'severity': 'warning',
                              'text': 'Task "%s" is past its due date' % t['title'],
                              'link': {'pane': 'tasks'}})
    order = {'danger': 0, 'warning': 1, 'info': 2}
    attention.sort(key=lambda a: order[a['severity']])

    states = {}
    if visible:
        for c, sname in (db.session.query(Cases.case_id, CaseState.state_name)
                         .outerjoin(CaseState, CaseState.state_id == Cases.state_id)
                         .filter(Cases.case_id.in_(visible))):
            states[c] = sname
    cases = [{'case_id': c, 'case_name': case_names.get(c), 'state_name': states.get(c),
              'assets': per_case[c]['assets'], 'done': per_case[c]['done'], 'exceptions': per_case[c]['exceptions'],
              'compromised': per_case[c]['compromised'], 'vulnerabilities_open': vper[c]['open'],
              'vulnerabilities_exploited_open': vper[c]['exploited_open'],
              'href': None if is_guest else '/case/assets?cid=%d' % c}
             for c in sorted(visible)]

    return {
        'indicators': {
            'open_decisions': len(dec_rows), 'overdue_decisions': sum(1 for r in dec_rows if r['is_overdue']),
            'open_tasks': len(tasks), 'tasks_in_progress': sum(1 for t in tasks if t['status'] == 'in_progress'),
            'assets': totals['assets'], 'assets_done': totals['done'], 'exceptions': totals['exceptions'],
            'compromised': totals['compromised'], 'vulnerabilities_open': vtot['open'],
            'vulnerabilities_exploited_open': vtot['exploited_open'],
        },
        'attention': attention[:30],
        'flags': {'total': totals['assets'], 'done': totals['done'], 'exceptions': totals['exceptions'],
                  'no_flag': totals['no_flag'], 'compromised': totals['compromised'],
                  'by_flag': [{'flag_id': f.id, 'name': f.name, 'color': f.color, 'icon': f.icon, 'kind': f.kind,
                               'assets': by_flag.get(f.id, 0)} for f in catalogue]},
        'cases': cases,
        'decisions': dec_rows,
        'tasks': tasks,
        'teams': teams,
        'vulnerabilities': vtot,
        'case_count': len(visible),
    }


def board(room, viewer_id, is_guest, role):
    from app.iris_engine.safe_markdown import render_markdown_safe
    widgets, is_default = get_layout(room.id)
    notes = {w['id']: render_markdown_safe(w.get('options', {}).get('text') or '')
             for w in widgets if w.get('type') == 'note'}
    return {'widgets': widgets, 'is_default': is_default, 'widget_types': widget_types(),
            'can_edit': (not is_guest) and role == 'lead' and room.status != 'closed',
            'data': board_data(room, viewer_id, is_guest), 'notes': notes,
            'generated_at': _iso(datetime.utcnow())}

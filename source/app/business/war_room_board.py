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

Three zones of widgets: a row of indicator TILES (compromised assets, open
decisions, exceptions, open tasks, the flags tile, five vulnerability figures),
then a wide MAIN column and a narrow SIDE column of PANELS (cases, open
decisions, needs attention, tasks, Markdown notes). A lead sets the room's
layout for everyone (war_room_board; no row = the default board); anyone can
hide, reorder or move panels for themselves in their browser.

Every figure is computed by the server from stored rows, over the attached cases
THE VIEWER can read (room_visible_case_ids: a user's case ACL; a guest reads
every attached case). An attached case a user cannot open is named on a locked
card (the room's Cases tab names it too) and counted in no figure. Guests get
the board without links into case pages (their portal session cannot open
them), without "awaiting your vote" and without per-finding lines.

Needs attention lists what nobody has triaged yet: a compromised asset with no
flag at all, an exception flag that cites no decision, a decision past its
target / due within 24 h / awaiting the viewer's vote, an exploited open finding
(or an overdue one), an overdue war-room task.
"""

import re
from datetime import datetime
from datetime import timedelta

from sqlalchemy import func

from app import db
from app.models import asset_flag_vocab as af
from app.models.models import WarRoomBoard

_ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,39}$')
_OPTIONS = {t: {} for t in af.BOARD_WIDGETS}
_OPTIONS['tasks'] = {'team_ids': list, 'in_progress_only': bool}
_OPTIONS['note'] = {'text': str}
COMPROMISED = 1  # CompromiseStatus.compromised


class BoardError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _iso(value):
    return value.isoformat() + 'Z' if value is not None else None


def _zone(typ):
    return af.BOARD_WIDGETS[typ][1]


def _wid(typ):
    return 'w-%s' % typ.replace('_', '-')


def _widget(typ, wid=None, column=None, title=None, options=None):
    col = (column or af.BOARD_WIDGETS[typ][2]) if _zone(typ) == 'panel' else None
    return {'id': wid or _wid(typ), 'type': typ, 'column': col, 'title': title, 'options': options or {}}


def default_widgets():
    return [_widget(t) for t in af.BOARD_DEFAULT]


def widget_types():
    return [{'type': t, 'label': v[0], 'zone': v[1], 'column': v[2], 'description': v[3],
             'wide': t in af.BOARD_WIDE_TILES} for t, v in af.BOARD_WIDGETS.items()]


def upgrade_widgets(widgets):
    """A stored layout of the first Board: its Indicators / Vulnerabilities widgets become the tiles that
    replaced them, its flags panel the flags tile; a type this code does not know is dropped. Ids stay
    unique; the result passes validate_widgets."""
    if not isinstance(widgets, list):
        return default_widgets()
    out, seen = [], set()

    def add(w):
        if w['id'] in seen:
            n = 2
            while '%s-%d' % (w['id'][:36], n) in seen:
                n += 1
            w['id'] = '%s-%d' % (w['id'][:36], n)
        seen.add(w['id'])
        out.append(w)

    for w in widgets:
        if not isinstance(w, dict):
            continue
        typ = w.get('type')
        if typ in af.BOARD_LEGACY:
            for t in af.BOARD_LEGACY[typ]:
                add(_widget(t))
            continue
        if typ not in af.BOARD_WIDGETS:
            continue
        wid = w.get('id') if isinstance(w.get('id'), str) and _ID_RE.match(w.get('id')) else _wid(typ)
        opts = w.get('options') if isinstance(w.get('options'), dict) else {}
        opts = {k: v for k, v in opts.items() if k in _OPTIONS[typ]}
        col = w.get('column') if w.get('column') in af.BOARD_COLUMNS else None
        title = w.get('title') if isinstance(w.get('title'), str) else None
        add(_widget(typ, wid, col, title, opts))
    return out[:af.BOARD_MAX_WIDGETS]


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
        col = w.get('column')
        if col is not None and col not in af.BOARD_COLUMNS:
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
        out.append(_widget(typ, wid, col, title, opts))
    return out


def get_layout(room_id):
    row = db.session.get(WarRoomBoard, room_id)
    if row is None or not isinstance(row.widgets, list):
        return default_widgets(), True
    return upgrade_widgets(row.widgets), False


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


# ---------------------------------------------------------------- shared loaders (the Board and the Scope tab)

def assets_of(case_ids):
    """(asset_id, asset_name, case_id, compromise status id, type name, ip, domain) of the cases' assets."""
    from app.models.models import AssetsType
    from app.models.models import CaseAssets
    if not case_ids:
        return []
    return (db.session.query(CaseAssets.asset_id, CaseAssets.asset_name, CaseAssets.case_id,
                             CaseAssets.asset_compromise_status_id, AssetsType.asset_name,
                             CaseAssets.asset_ip, CaseAssets.asset_domain)
            .outerjoin(AssetsType, AssetsType.asset_id == CaseAssets.asset_type_id)
            .filter(CaseAssets.case_id.in_(case_ids)).all())


def flags_by_asset(asset_ids):
    """{asset_id: [(AssetFlag, reason, decision_id)]} in the catalogue's order."""
    from app.models.models import AssetFlag
    from app.models.models import CaseAssetFlag
    out = {}
    if not asset_ids:
        return out
    rows = (db.session.query(CaseAssetFlag.asset_id, CaseAssetFlag.reason, CaseAssetFlag.decision_id, AssetFlag)
            .join(AssetFlag, AssetFlag.id == CaseAssetFlag.flag_id)
            .filter(CaseAssetFlag.asset_id.in_(asset_ids))
            .order_by(AssetFlag.sort_order, AssetFlag.id).all())
    for aid, reason, did, f in rows:
        out.setdefault(aid, []).append((f, reason, did))
    return out


def open_findings(case_ids):
    """The OPEN case findings of these cases: (finding_id, case_id, asset_id, identifier, exploited, overdue, kev)."""
    from app.models import vulnerability_vocab as vv
    from app.models.models import Vulnerability
    from app.models.models import VulnerabilityFinding
    if not case_ids:
        return []
    today = datetime.utcnow().date()
    rows = (db.session.query(VulnerabilityFinding.finding_id, VulnerabilityFinding.case_id,
                             VulnerabilityFinding.asset_id, Vulnerability.identifier,
                             VulnerabilityFinding.exploitation_status, VulnerabilityFinding.due_date, Vulnerability.kev)
            .join(Vulnerability, Vulnerability.vulnerability_id == VulnerabilityFinding.vulnerability_id)
            .filter(VulnerabilityFinding.scope == 'case', VulnerabilityFinding.case_id.in_(case_ids),
                    VulnerabilityFinding.remediation_status.in_(vv.REMEDIATION_GROUPS['open']))
            .order_by(VulnerabilityFinding.finding_id).all())
    return [(fid, cid, aid, ident, exp == 'exploited', due is not None and due < today, bool(kev))
            for fid, cid, aid, ident, exp, due, kev in rows]


def _case_meta(case_ids):
    """{case_id: (name, customer, owner, state, severity, closed)}."""
    from app.models.alerts import Severity
    from app.models.authorization import User
    from app.models.cases import Cases
    from app.models.cases import CaseState
    from app.models.models import Client
    if not case_ids:
        return {}
    rows = (db.session.query(Cases.case_id, Cases.name, Client.name, User.name, CaseState.state_name,
                             Severity.severity_name, Cases.close_date)
            .outerjoin(Client, Client.client_id == Cases.client_id)
            .outerjoin(User, User.id == Cases.owner_id)
            .outerjoin(CaseState, CaseState.state_id == Cases.state_id)
            .outerjoin(Severity, Severity.severity_id == Cases.severity_id)
            .filter(Cases.case_id.in_(case_ids)).all())
    return {r[0]: r[1:] for r in rows}


def _case_tasks(case_ids):
    from app.models.models import CaseTasks
    from app.models.models import TaskStatus
    out = {c: {'open': 0, 'in_progress': 0} for c in case_ids}
    if not case_ids:
        return out
    rows = (db.session.query(CaseTasks.task_case_id, TaskStatus.status_name, func.count())
            .outerjoin(TaskStatus, CaseTasks.task_status_id == TaskStatus.id)
            .filter(CaseTasks.task_case_id.in_(case_ids))
            .group_by(CaseTasks.task_case_id, TaskStatus.status_name).all())
    for cid, status_name, n in rows:
        if status_name in ('Done', 'Canceled'):
            continue
        out[cid]['open'] += n
        if status_name == 'In progress':
            out[cid]['in_progress'] += n
    return out


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


# ---------------------------------------------------------------- the figures

def _attention(type_, severity, label, link=None, action=None, **ids):
    item = {'type': type_, 'severity': severity, 'label': label, 'case_id': None, 'asset_id': None,
            'decision_id': None, 'task_id': None, 'finding_id': None, 'link': link, 'action': action if link else None}
    item.update(ids)
    return item


def board_data(room, viewer_id, is_guest):
    from app.business import war_room_decisions as wd
    from app.business.war_rooms import room_case_ids
    from app.business.war_rooms import room_visible_case_ids
    from app.models.cases import Cases
    from app.models.models import AssetFlag
    from app.models.models import WarRoomDecision
    from app.models.models import WarRoomDecisionApprover
    linked = room_case_ids(room.id)
    visible = room_visible_case_ids(room.id, viewer_id, guest=is_guest)
    vis_set = set(visible)
    assets = assets_of(visible)
    fl_of = flags_by_asset([a[0] for a in assets])
    catalogue = AssetFlag.query.order_by(AssetFlag.sort_order, AssetFlag.id).all()
    meta = _case_meta(visible)
    names = {c: m[0] for c, m in meta.items()}
    attention = []

    def case_link(href):
        return None if is_guest else {'href': href}

    by_flag = {f.id: 0 for f in catalogue}
    k = {'assets': len(assets), 'done': 0, 'exceptions': 0, 'no_flag': 0, 'compromised': 0, 'unflagged': 0}
    per_case = {c: {'assets': 0, 'done': 0, 'exceptions': 0, 'compromised': 0, 'by_flag': {}} for c in visible}
    asset_names = {}
    for aid, name, cid, comp, _, _, _ in assets:
        asset_names[aid] = name
        fl = fl_of.get(aid, [])
        kinds = {f.kind for f, _, _ in fl}
        pc = per_case[cid]
        pc['assets'] += 1
        for f, _, _ in fl:
            by_flag[f.id] = by_flag.get(f.id, 0) + 1
            pc['by_flag'][str(f.id)] = pc['by_flag'].get(str(f.id), 0) + 1
        if not fl:
            k['no_flag'] += 1
            pc['by_flag']['none'] = pc['by_flag'].get('none', 0) + 1
        if 'done' in kinds:
            k['done'] += 1
            pc['done'] += 1
        if 'exception' in kinds:
            k['exceptions'] += 1
            pc['exceptions'] += 1
            for f, reason, did in fl:
                if f.kind == 'exception' and did is None:
                    attention.append(_attention(
                        'exception_without_decision', 'medium',
                        '%s: exception "%s" cites no decision%s' % (name, f.name, (' - %s' % reason) if reason else ''),
                        case_link('/case/assets?cid=%d&asset=%d&tab=details' % (cid, aid)), 'Open',
                        case_id=cid, asset_id=aid))
        if comp == COMPROMISED:
            k['compromised'] += 1
            pc['compromised'] += 1
            if not fl:
                k['unflagged'] += 1
                attention.append(_attention(
                    'compromised_unflagged', 'high', '%s is compromised and has no flag' % name,
                    case_link('/case/assets?cid=%d&asset=%d&tab=details' % (cid, aid)), 'Open',
                    case_id=cid, asset_id=aid))

    findings = open_findings(visible)
    vtot = {'open': 0, 'exploited_open': 0, 'overdue': 0, 'kev_open': 0, 'vulnerable_assets': 0}
    vper = {c: {'open': 0, 'exploited_open': 0} for c in visible}
    vuln_assets = set()
    for fid, cid, aid, ident, exploited, overdue, kev in findings:
        vtot['open'] += 1
        vper[cid]['open'] += 1
        vuln_assets.add(aid)
        vtot['exploited_open'] += exploited
        vper[cid]['exploited_open'] += exploited
        vtot['overdue'] += overdue
        vtot['kev_open'] += kev
        if is_guest or not (exploited or overdue):
            continue
        aname = asset_names.get(aid) or 'an asset'
        href = '/case/assets?cid=%d&asset=%d&tab=vulns' % (cid, aid)
        if exploited:
            attention.append(_attention('vulnerability_exploited_open', 'high',
                                        '%s is exploited and still open on %s' % (ident, aname),
                                        {'href': href}, 'Review', case_id=cid, asset_id=aid, finding_id=fid))
        else:
            attention.append(_attention('vulnerability_overdue', 'medium',
                                        '%s on %s is past its due date' % (ident, aname),
                                        {'href': href}, 'Review', case_id=cid, asset_id=aid, finding_id=fid))
    vtot['vulnerable_assets'] = len(vuln_assets)

    now = datetime.utcnow()
    soon = now + timedelta(hours=af.BOARD_DUE_SOON_HOURS)
    decisions = (WarRoomDecision.query.filter(WarRoomDecision.room_id == room.id,
                                              WarRoomDecision.status.in_(('proposed', 'approved')),
                                              WarRoomDecision.implemented_at.is_(None)).all())
    pending, pending_mine = {}, set()
    if decisions:
        for a in WarRoomDecisionApprover.query.filter(
                WarRoomDecisionApprover.decision_id.in_([d.id for d in decisions]),
                WarRoomDecisionApprover.verdict == 'pending'):
            pending[a.decision_id] = pending.get(a.decision_id, 0) + 1
            if not is_guest and a.user_id == viewer_id:
                pending_mine.add(a.decision_id)
    owners = wd._names([d.owner_id for d in decisions])
    dec_rows = []
    for d in decisions:
        over = wd.is_overdue(d, now)
        due_soon = bool(not over and d.target_at is not None and d.target_at < soon)
        mine = d.id in pending_mine and d.status == 'proposed'
        link = {'pane': 'decisions', 'decision_id': d.id}
        dec_rows.append({'decision_id': d.id, 'ref': wd.ref(d), 'title': d.title, 'status': d.status,
                         'target_at': _iso(d.target_at), 'is_overdue': over, 'due_soon': due_soon,
                         'owner_name': owners.get(d.owner_id), 'awaiting_me': mine,
                         'pending_approvers': pending.get(d.id, 0) if d.status == 'proposed' else 0})
        if over:
            attention.append(_attention('decision_overdue', 'high', '%s "%s" is past its target' % (wd.ref(d), d.title),
                                        link, 'Review', decision_id=d.id))
        elif due_soon:
            attention.append(_attention('decision_due_soon', 'medium',
                                        '%s "%s" is due within %d h' % (wd.ref(d), d.title, af.BOARD_DUE_SOON_HOURS),
                                        link, 'Review', decision_id=d.id))
        if mine:
            attention.append(_attention('decision_pending_vote', 'medium',
                                        '%s "%s" awaits your vote' % (wd.ref(d), d.title), link, 'Review',
                                        decision_id=d.id))
    dec_rows.sort(key=lambda r: (not r['is_overdue'], r['target_at'] or '9999', -r['decision_id']))

    tasks, teams = _tasks(room.id)
    for t in tasks:
        if t['overdue']:
            attention.append(_attention('task_overdue', 'medium', 'Task "%s" is past its due date' % t['title'],
                                        {'pane': 'tasks'}, 'Open', task_id=t['id']))
    rank = {s: i for i, s in enumerate(af.BOARD_SEVERITIES)}
    attention.sort(key=lambda a: rank[a['severity']])

    ctasks = _case_tasks(visible)
    cards = []
    for c in visible:
        name, customer, owner, state, severity, closed = meta.get(c, (None,) * 6)
        pc = per_case[c]
        cards.append({'case_id': c, 'accessible': True, 'case_name': name, 'customer_name': customer,
                      'owner_name': owner, 'state_name': state, 'severity_name': severity, 'closed': closed is not None,
                      'assets_total': pc['assets'], 'done': pc['done'], 'exceptions': pc['exceptions'],
                      'assets_compromised': pc['compromised'], 'by_flag': pc['by_flag'],
                      'tasks_open': ctasks[c]['open'], 'tasks_in_progress': ctasks[c]['in_progress'],
                      'vulnerabilities_open': vper[c]['open'],
                      'vulnerabilities_exploited_open': vper[c]['exploited_open'],
                      'href': None if is_guest else '/case?cid=%d' % c,
                      'assets_href': None if is_guest else '/case/assets?cid=%d' % c})
    restricted = [c for c in linked if c not in vis_set]
    if restricted and not is_guest:
        for cid, name in db.session.query(Cases.case_id, Cases.name).filter(Cases.case_id.in_(restricted)):
            cards.append({'case_id': cid, 'accessible': False, 'case_name': name})
    cards.sort(key=lambda x: (not x['accessible'], -x.get('assets_compromised', 0), x['case_id']))

    return {
        'kpis': {
            'compromised': k['compromised'], 'unflagged': k['unflagged'],
            'decisions_open': len(dec_rows), 'decisions_overdue': sum(1 for r in dec_rows if r['is_overdue']),
            'decisions_due_24h': sum(1 for r in dec_rows if r['due_soon']),
            'exceptions': k['exceptions'],
            'tasks_open': len(tasks), 'tasks_in_progress': sum(1 for t in tasks if t['status'] == 'in_progress'),
            'tasks_overdue': sum(1 for t in tasks if t['overdue']),
            'assets': k['assets'], 'done': k['done'],
        },
        'attention': attention[:af.BOARD_ATTENTION_MAX],
        'attention_total': len(attention),
        'flags': {'assets': k['assets'], 'done': k['done'], 'exceptions': k['exceptions'], 'none': k['no_flag'],
                  'by_flag': [{'flag_id': f.id, 'name': f.name, 'color': f.color, 'icon': f.icon, 'kind': f.kind,
                               'assets': by_flag.get(f.id, 0)} for f in catalogue]},
        'vulnerabilities': vtot,
        'cases': cards,
        'decisions': dec_rows,
        'tasks': tasks,
        'teams': teams,
        'case_count': len(visible),
        'cases_total': len(linked) if not is_guest else len(visible),
    }


def board(room, viewer_id, is_guest, role):
    from app.iris_engine.safe_markdown import render_markdown_safe
    widgets, is_default = get_layout(room.id)
    notes = {w['id']: render_markdown_safe(w.get('options', {}).get('text') or '')
             for w in widgets if w.get('type') == 'note'}
    return {'widgets': widgets, 'is_default': is_default, 'widget_types': widget_types(),
            'can_edit': (not is_guest) and role == 'lead' and room.status != 'closed',
            'scope': not is_guest,
            'data': board_data(room, viewer_id, is_guest), 'notes': notes,
            'generated_at': _iso(datetime.utcnow())}

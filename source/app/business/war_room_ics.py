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

"""ICS (Incident Command System) room-note templates for war rooms.

Maintainer decisions (2026-09-16, extended 2026-09-17): seed the ICS forms
as room notes in an "ICS" folder, ONE set per room, on the first case
attach; prefill the fields we can fill honestly from room + case data;
templates are BUNDLED (admin-editable templates are on the backlog).
The set is the seven forms a cyber incident reports with: 201 Incident
Briefing, 202 Incident Objectives, 203 Organization Assignment List, 204
Assignment List, 205A Communications List, 209 Incident Status Summary and
214 Activity Log. Block numbers follow FEMA's, so each note maps 1:1 onto
the official fillable PDF (business/war_room_ics_pdf.py).

Rules:
* Idempotent BY TITLE per room, not by folder: deleting the ICS folder moves
  its notes to the root (folder delete never deletes content), so folder
  presence is not evidence the forms exist. A note that was deleted is
  re-seeded on the next run; one that exists is never touched — once seeded,
  the text belongs to the analyst. A room seeded before a form existed gets
  the new form on its next seed (attach or the rail button), nothing else.
* Prefill is deterministic and only from data in hand: room name/id/status/
  severity/summary, attached cases (name, customer, severity, state, opened,
  owner, classification), server-computed counts, members with roles (lead
  → Incident Commander, responders → Operations Section, observers →
  Agency/Organization Representatives) and their account e-mail as the
  method of contact, room + case tasks as work assignments, and the room
  stream as the activity log. No AI, so a seeded form never carries a
  fabricated claim.
* Placeholders are `{{name}}` tokens replaced by plain substitution — NOT a
  template engine, so a room or case NAME containing `{{`, `{%` or `#` is
  inserted as text, never evaluated. Values that land in a markdown table
  cell have `|` escaped and newlines flattened so analyst text cannot break
  the table. The display path renders through render_markdown_safe.
* The attach-route hook is fail-soft: a seeding problem is logged and the
  attach still succeeds — the forms are a convenience, the attachment is
  the analyst's action.
"""
import logging
import os
import re
from datetime import date
from datetime import datetime

from app import db
from app.business.errors import BusinessProcessingError
from app.models.cases import Cases
from app.models.cases import CasesEvent
from app.models.models import CaseAssets
from app.models.models import CaseReceivedFile
from app.models.models import CaseTasks
from app.models.models import Ioc
from app.models.models import WarRoomCaseLink
from app.models.models import WarRoomMember
from app.models.models import WarRoomNote
from app.models.models import WarRoomNoteFolder
from app.models.models import WarRoomTask

log = logging.getLogger(__name__)

ICS_FOLDER_NAME = 'ICS'
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'resources', 'ics_note_templates')

# (note title, template file). Order = order the notes are created in. The
# title is the KEY the seeder, the AI pass and the PDF export all match on.
ICS_FORMS = (
    ('ICS 201 - Incident Briefing', 'ics_201.md'),
    ('ICS 202 - Incident Objectives', 'ics_202.md'),
    ('ICS 203 - Organization Assignment List', 'ics_203.md'),
    ('ICS 204 - Assignment List', 'ics_204.md'),
    ('ICS 205A - Communications List', 'ics_205a.md'),
    ('ICS 209 - Incident Status Summary', 'ics_209.md'),
    ('ICS 214 - Activity Log', 'ics_214.md'),
)

_PLACEHOLDER_RE = re.compile(r'\{\{\s*([a-z0-9_]+)\s*\}\}')
_ROLE_TO_ICS = {
    'lead': 'Incident Commander',
    'responder': 'Operations Section',
    'observer': 'Agency / Organization Representative',
}
# Caps on what the seed writes into a note — a note is for people to read.
_LOG_ROWS_CAP = 200
_LOG_CELL_CAP = 300
_TASKS_CAP = 60
_CLOSED_TASK_STATES = {'done', 'cancelled', 'canceled'}


def form_number(title: str) -> str | None:
    """'ICS 205A - Communications List' -> '205A'; None for a non-ICS title."""
    m = re.match(r'^ICS (\d{3}[A-Z]?) - ', title or '')
    return m.group(1) if m else None


def _cell(value) -> str:
    """Make analyst text safe inside a markdown table cell."""
    s = '' if value is None else str(value)
    s = s.replace('\r', ' ').replace('\n', ' ').replace('|', '\\|').strip()
    return s or '—'


def case_label(case_id, name) -> str:
    """`#id name`, unless the stored name already starts with `#id` — the
    legacy create route and alert escalation store names as `#<id> - <name>`,
    so a blind prefix would render `#39 #39 - ...` (same trap as the IOC
    cross-case cards). Table-cell safe."""
    n = _cell(name)
    if n.startswith('#%d' % case_id):
        return n
    return '#%d %s' % (case_id, n)


def _iso_minute(dt) -> str:
    if not dt:
        return '—'
    if isinstance(dt, datetime):
        return dt.strftime('%Y-%m-%d %H:%M')
    if isinstance(dt, date):
        return dt.isoformat()
    return str(dt)


def _plural(n: int, one: str, many: str | None = None) -> str:
    return '%d %s' % (n, one if n == 1 else (many or one + 's'))


def _uname(u) -> str:
    return ((u.name or u.user) if u else None) or '—'


def build_ics_context(room, actor_id=None) -> dict:
    """Placeholder values for every ICS template, computed from data in hand."""
    from app.business.war_rooms import room_stream
    from app.models.authorization import User

    prepared_at = datetime.utcnow()
    actor = db.session.get(User, actor_id) if actor_id else None
    prepared_by = (actor.name or actor.user) if actor else '—'

    members = (WarRoomMember.query.filter_by(room_id=room.id)
               .order_by(WarRoomMember.added_at.asc(), WarRoomMember.id.asc()).all())
    leads = [m for m in members if m.role == 'lead']
    responders = [m for m in members if m.role == 'responder']
    observers = [m for m in members if m.role == 'observer']

    def _mname(m):
        return _uname(m.user)

    def _mlogin(m):
        return m.user.user if m.user else '—'

    def _mcontact(m):
        return (m.user.email if m.user and m.user.email else None) or '—'

    def _mics(m):
        return _ROLE_TO_ICS.get(m.role, m.role)

    ic_names = ', '.join(_cell(_mname(m)) for m in leads) or '—'
    members_table = '\n'.join(
        '| %s | %s | %s (%s) |' % (_cell(_mname(m)), _cell(_mlogin(m)), _cell(m.role), _mics(m))
        for m in members) or '| — | — | — |'
    responders_table = '\n'.join(
        '| — | %s |' % _cell(_mname(m)) for m in responders) or '| — | — |'
    observers_table = '\n'.join(
        '| — | %s |' % _cell(_mname(m)) for m in observers) or '| — | — |'

    # ICS 204 §5: one resource per responder; §8: who to reach and how.
    resources_204_table = '\n'.join(
        '| %s | %s | 1 | %s | Room role: responder |' % (
            _cell(_mlogin(m)), _cell(_mname(m)), _cell(_mcontact(m)))
        for m in responders) or '| — | — | — | — | — |'
    comms_table = '\n'.join(
        '| %s (%s) | %s |' % (_cell(_mname(m)), _mics(m), _cell(_mcontact(m)))
        for m in members if m.role in ('lead', 'responder')) or '| — | — |'
    # ICS 205A §3: alphabetized by display name, position from the room role.
    contacts_table = '\n'.join(
        '| %s | %s | %s |' % (_mics(m), _cell(_mname(m)), _cell(_mcontact(m)))
        for m in sorted(members, key=lambda m: _mname(m).lower())) or '| — | — | — |'
    # ICS 214 §6: the unit's resources.
    resources_214_table = '\n'.join(
        '| %s | %s | — |' % (_cell(_mname(m)), _mics(m)) for m in members) or '| — | — | — |'

    links = (db.session.query(WarRoomCaseLink, Cases)
             .join(Cases, Cases.case_id == WarRoomCaseLink.case_id)
             .filter(WarRoomCaseLink.room_id == room.id)
             .order_by(WarRoomCaseLink.added_at.asc(), Cases.case_id.asc()).all())
    case_rows = []
    inline = []
    case_ids = []
    customers = []
    classifications = []
    earliest_open = None
    for _link, c in links:
        customer = c.client.name if c.client else None
        severity = c.severity.severity_name if c.severity else None
        state = c.state.state_name if c.state else None
        owner = _uname(c.owner) if c.owner else None
        label = case_label(c.case_id, c.name)
        case_rows.append('| %s | %s | %s | %s | %s | %s |' % (
            label, _cell(customer), _cell(severity), _cell(state),
            _cell(c.open_date.isoformat() if c.open_date else None), _cell(owner)))
        inline.append(label)
        case_ids.append(c.case_id)
        if customer and customer not in customers:
            customers.append(customer)
        cls = c.classification.name if c.classification else None
        if cls and cls not in classifications:
            classifications.append(cls)
        if c.open_date and (earliest_open is None or c.open_date < earliest_open):
            earliest_open = c.open_date

    # Server-computed counts (ICS 209 §7 "size" of a cyber incident).
    if case_ids:
        n_assets = CaseAssets.query.filter(CaseAssets.case_id.in_(case_ids)).count()
        n_iocs = Ioc.query.filter(Ioc.case_id.in_(case_ids)).count()
        n_evidence = CaseReceivedFile.query.filter(CaseReceivedFile.case_id.in_(case_ids)).count()
        n_events = CasesEvent.query.filter(CasesEvent.case_id.in_(case_ids)).count()
    else:
        n_assets = n_iocs = n_evidence = n_events = 0
    scope_line = ' · '.join([
        _plural(len(case_ids), 'case'), _plural(n_assets, 'asset'),
        _plural(n_iocs, 'IOC'), _plural(n_evidence, 'evidence item'),
        _plural(n_events, 'timeline event'),
    ])

    # ICS 204 §6: open room tasks, then open case tasks. A snapshot.
    work = []
    room_tasks = (WarRoomTask.query.filter_by(room_id=room.id)
                  .order_by(WarRoomTask.id.asc()).all())
    for t in room_tasks:
        if (t.status or '') in _CLOSED_TASK_STATES:
            continue
        who = (' → ' + _cell(_uname(t.assignee))) if t.assignee else ''
        work.append('- [%s] %s%s (room task)' % (
            (t.status or 'no_status').replace('_', ' '), _cell(t.title), who))
    if case_ids:
        ctasks = (CaseTasks.query.filter(CaseTasks.task_case_id.in_(case_ids))
                  .order_by(CaseTasks.id.asc()).all())
        for t in ctasks:
            sname = t.status.status_name if t.status else None
            if (sname or '').lower() in _CLOSED_TASK_STATES:
                continue
            work.append('- [%s] %s (case #%d)' % (
                _cell(sname or 'no status'), _cell(t.task_title), t.task_case_id))
    truncated = len(work) - _TASKS_CAP
    work = work[:_TASKS_CAP]
    if truncated > 0:
        work.append('- … and %d more open tasks (see the Tasks tab)' % truncated)
    work_assignments = '\n'.join(work) or '- —'

    # ICS 214 §7: the room stream, oldest first — room-level events only
    # (messages, decisions, cases attached, members added, tasks, SitReps,
    # polls). Per-case audit activity stays on the case pages: it is per
    # action, not per decision, and would bury the log.
    log_rows = []
    try:
        stream = room_stream(room, actor_id, limit=300)
    except Exception as exc:  # noqa: BLE001 - the log is a convenience
        log.warning('ICS 214 seed: stream unavailable for room %s: %s', room.id, exc)
        stream = []
    for item in reversed(stream):
        if item.get('kind') == 'case_activity':
            continue
        content = item.get('content') or ''
        if item.get('kind') == 'message':
            who = item.get('user_name') or 'someone'
            mk = item.get('msg_kind')
            tag = {'decision': 'DECISION', 'note': 'NOTE'}.get(mk)
            content = '%s%s: %s' % (('[%s] ' % tag) if tag else '', who, content)
        if len(content) > _LOG_CELL_CAP:
            content = content[:_LOG_CELL_CAP - 1] + '…'
        log_rows.append('| %s | %s |' % (_iso_minute(item.get('created_at')), _cell(content)))
    overflow = len(log_rows) - _LOG_ROWS_CAP
    log_rows = log_rows[:_LOG_ROWS_CAP]
    if overflow > 0:
        log_rows.append('| — | … and %d earlier entries not carried into this snapshot |' % overflow)
    activity_log_table = '\n'.join(log_rows) or '| — | — |'

    incident_number = 'WR#%d' % room.id
    if case_ids:
        incident_number += ' (cases %s)' % ', '.join('#%d' % i for i in case_ids)

    return {
        'room_name': _cell(room.name),
        'room_id': str(room.id),
        'room_status': _cell(room.status),
        'room_severity': _cell(room.severity) if room.severity else 'unset',
        'room_summary': (room.summary or '').strip() or '_No room summary yet._',
        'room_created_at': _iso_minute(room.created_at),
        'prepared_at': _iso_minute(prepared_at),
        'prepared_by': _cell(prepared_by),
        'ic_names': ic_names,
        'members_count': str(len(members)),
        'members_table': members_table,
        'responders_table': responders_table,
        'observers_table': observers_table,
        'cases_table': '\n'.join(case_rows) or '| — | — | — | — | — | — |',
        'cases_inline': ', '.join(inline) or '—',
        'cases_count': str(len(case_rows)),
        'incident_number': incident_number,
        'incident_start': _iso_minute(earliest_open or room.created_at),
        'scope_line': scope_line,
        'classifications_inline': ', '.join(_cell(x) for x in classifications) or '—',
        'customers_inline': ', '.join(_cell(x) for x in customers) or '—',
        'resources_204_table': resources_204_table,
        'work_assignments': work_assignments,
        'comms_table': comms_table,
        'contacts_table': contacts_table,
        'resources_214_table': resources_214_table,
        'activity_log_table': activity_log_table,
    }


def load_template(filename: str) -> str:
    path = os.path.join(TEMPLATE_DIR, filename)
    with open(path, 'r', encoding='utf-8') as fh:
        return fh.read()


def render_ics(template_text: str, ctx: dict) -> str:
    """Plain token substitution. An unknown token is left verbatim so a
    template/context mismatch is visible in the note rather than silently
    blanked — the suite asserts none survive."""
    def _sub(m):
        key = m.group(1)
        return ctx[key] if key in ctx else m.group(0)
    return _PLACEHOLDER_RE.sub(_sub, template_text)


def ics_state(room) -> dict:
    """Which ICS forms exist in this room (by title, any folder)."""
    titles = {t for (t, _f) in ICS_FORMS}
    present = {n.title: n.id for n in WarRoomNote.query.filter(
        WarRoomNote.room_id == room.id, WarRoomNote.title.in_(titles)).all()}
    return {
        'present': [t for (t, _f) in ICS_FORMS if t in present],
        'missing': [t for (t, _f) in ICS_FORMS if t not in present],
        'note_ids': present,
    }


def _ics_folder(room, actor_id):
    f = (WarRoomNoteFolder.query.filter_by(room_id=room.id, name=ICS_FOLDER_NAME)
         .order_by(WarRoomNoteFolder.id.asc()).first())
    if f is None:
        f = WarRoomNoteFolder(room_id=room.id, name=ICS_FOLDER_NAME, created_by=actor_id)
        db.session.add(f)
        db.session.flush()
    return f


def seed_ics_notes(room, actor_id) -> dict:
    """Create the missing ICS forms for a room. Idempotent by title.

    Returns {'created': [titles], 'skipped': [titles], 'folder_id': int|None,
             'note_ids': {title: id}}. Raises BusinessProcessingError only
    when the room is closed (read-only).
    """
    if room.status == 'closed':
        raise BusinessProcessingError('Room is closed')

    state = ics_state(room)
    if not state['missing']:
        return {'created': [], 'skipped': state['present'], 'folder_id': None,
                'note_ids': state['note_ids']}

    ctx = build_ics_context(room, actor_id)
    folder = _ics_folder(room, actor_id)
    created = []
    note_ids = dict(state['note_ids'])
    for title, filename in ICS_FORMS:
        if title in note_ids:
            continue
        content = render_ics(load_template(filename), ctx)
        n = WarRoomNote(room_id=room.id, title=title, folder_id=folder.id,
                        content=content, created_by=actor_id)
        db.session.add(n)
        db.session.flush()
        note_ids[title] = n.id
        created.append(title)
    db.session.commit()
    return {'created': created, 'skipped': state['present'],
            'folder_id': folder.id, 'note_ids': note_ids}


def seed_ics_notes_soft(room, actor_id) -> dict:
    """The attach-route hook: never raises. A seeding failure must not undo
    or fail the case attachment that triggered it."""
    try:
        return seed_ics_notes(room, actor_id)
    except Exception as exc:  # noqa: BLE001 - deliberately broad, logged
        log.warning('ICS note seeding skipped for war room %s: %s', getattr(room, 'id', '?'), exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover
            pass
        return {'created': [], 'skipped': [], 'folder_id': None, 'note_ids': {},
                'error': str(exc)}

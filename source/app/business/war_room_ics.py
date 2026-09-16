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

Maintainer decisions (2026-09-16): seed ICS 201 / 202 / 203 as room notes
in an "ICS" folder, ONE set per room, on the first case attach; prefill the
fields we can fill honestly from room + case data; templates are BUNDLED
(admin-editable templates are on the backlog).

Rules:
* Idempotent BY TITLE per room, not by folder: deleting the ICS folder moves
  its notes to the root (folder delete never deletes content), so folder
  presence is not evidence the forms exist. A note that was deleted is
  re-seeded on the next run; one that exists is never touched — once seeded,
  the text belongs to the analyst.
* Prefill is deterministic and only from data in hand: room name/id/status/
  severity/summary, attached cases (name, customer, severity, state, opened,
  owner), members with roles (lead → Incident Commander, responders →
  Operations Section, observers → Agency/Organization Representatives). No AI,
  so a seeded form never carries a fabricated claim.
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
from datetime import datetime

from app import db
from app.business.errors import BusinessProcessingError
from app.models.cases import Cases
from app.models.models import WarRoomCaseLink
from app.models.models import WarRoomMember
from app.models.models import WarRoomNote
from app.models.models import WarRoomNoteFolder

log = logging.getLogger(__name__)

ICS_FOLDER_NAME = 'ICS'
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'resources', 'ics_note_templates')

# (note title, template file). Order = order the notes are created in.
ICS_FORMS = (
    ('ICS 201 - Incident Briefing', 'ics_201.md'),
    ('ICS 202 - Incident Objectives', 'ics_202.md'),
    ('ICS 203 - Organization Assignment List', 'ics_203.md'),
)

_PLACEHOLDER_RE = re.compile(r'\{\{\s*([a-z_]+)\s*\}\}')
_ROLE_TO_ICS = {
    'lead': 'Incident Commander',
    'responder': 'Operations Section',
    'observer': 'Agency / Organization Representative',
}


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
    return str(dt)


def build_ics_context(room, actor_id=None) -> dict:
    """Placeholder values for every ICS template, computed from data in hand."""
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
        u = m.user
        return (u.name or u.user) if u else '—'

    def _mlogin(m):
        return m.user.user if m.user else '—'

    ic_names = ', '.join(_cell(_mname(m)) for m in leads) or '—'
    members_table = '\n'.join(
        '| %s | %s | %s (%s) |' % (_cell(_mname(m)), _cell(_mlogin(m)), _cell(m.role),
                                 _ROLE_TO_ICS.get(m.role, m.role))
        for m in members) or '| — | — | — |'
    responders_table = '\n'.join(
        '| — | %s |' % _cell(_mname(m)) for m in responders) or '| — | — |'
    observers_table = '\n'.join(
        '| — | %s |' % _cell(_mname(m)) for m in observers) or '| — | — |'

    links = (db.session.query(WarRoomCaseLink, Cases)
             .join(Cases, Cases.case_id == WarRoomCaseLink.case_id)
             .filter(WarRoomCaseLink.room_id == room.id)
             .order_by(WarRoomCaseLink.added_at.asc(), Cases.case_id.asc()).all())
    case_rows = []
    inline = []
    for _link, c in links:
        customer = c.client.name if c.client else None
        severity = c.severity.severity_name if c.severity else None
        state = c.state.state_name if c.state else None
        owner = (c.owner.name or c.owner.user) if c.owner else None
        label = case_label(c.case_id, c.name)
        case_rows.append('| %s | %s | %s | %s | %s | %s |' % (
            label, _cell(customer), _cell(severity), _cell(state),
            _cell(c.open_date.isoformat() if c.open_date else None), _cell(owner)))
        inline.append(label)

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

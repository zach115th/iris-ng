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

"""AI pass over the ICS room-note forms (war rooms).

Three passes, in this order (maintainer decision, 2026-09-16):

  1. DETERMINISTIC seed — business/war_room_ics.py fills every field the
     database answers directly (incident name, dates, attached cases, the
     lead as Incident Commander, members). Runs on the first case attach.
  2. THIS AI pass — proposes text for the fields still at their seeded `—`
     from the attached cases' material (descriptions, cached executive
     summaries, tasks, activity). Runs automatically right after the seed
     and on demand from the Notes rail.
  3. The HUMAN pass — the Incident Commander reviews and edits.

Rules that make pass 2 safe to run unattended:

  * It fills ONLY fields still in their seeded empty state. Anything the
    seed or an analyst wrote is never touched, so running it twice, or
    after the IC has started editing, changes nothing they own. Detection
    is by the exact empty markers the templates use (`—` cells, `- —`
    bullets, the `_No room summary yet._` sentinel), located under the
    template's own section headings; a renamed or deleted heading simply
    makes that field unfillable, and the run reports it.
  * Every fill is MARKED: a blockquote line at the top of the note lists
    what the AI filled, and each filled prose/list/table carries an
    "AI draft" line the IC deletes once reviewed. A form never carries an
    unlabelled machine-written claim.
  * ICS 203 names are VALIDATED AND RE-DERIVED against a candidate list the
    server built (room members + owners of the attached cases): a name the
    model invents is dropped, a match is rewritten to the stored display
    name. Every count the model can cite is computed server-side.
  * A failed or unparseable AI call is NEVER persisted (project rule). The
    parsed proposal is cached on an AiArtifact (anchor_type='war_room',
    kind='ics_draft', input-hash keyed) so a re-run over unchanged data
    costs no model call; the MERGE is re-executed on every run because it
    depends on the notes' current text, not on the proposal.
  * The auto-run hook is fail-soft: no AI backend, no broker, any error —
    the attach/seed that triggered it still succeeds.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from typing import Any

from app import db
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import OpenAIClient
from app.iris_engine.ai.openai_client import build_default_client
from app.models.cases import Cases
from app.models.cases import CasesEvent
from app.models.models import AiArtifact
from app.models.models import CaseAssets
from app.models.models import CaseReceivedFile
from app.models.models import CaseTasks
from app.models.models import Ioc
from app.models.models import WarRoom
from app.models.models import WarRoomCaseLink
from app.models.models import WarRoomMember
from app.models.models import WarRoomNote

log = logging.getLogger(__name__)

PROMPT_ID = 'IcsDraftSystemPrompt-v1'
FEATURE_KEY = 'ics_draft'
KIND = 'ics_draft'
ANCHOR_TYPE = 'war_room'

_PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), '..', '..', 'resources', 'ai_prompts',
    'ics_draft.md')

MARK = '_AI draft — review before relying on it._'

# Caps on what the model may hand back — bounded output for a note body.
_PROSE_CAP = 4000
_ITEM_CAP = 300
_LIST_CAP = 8
_ROWS_CAP = 12
_DESC_CAP = 3000
_TASKS_CAP = 25

_FORM_KEYS = {
    'ICS 201 - Incident Briefing': 'ics_201',
    'ICS 202 - Incident Objectives': 'ics_202',
    'ICS 203 - Organization Assignment List': 'ics_203',
}

# ICS 203 positions the model may propose → (section heading, table row
# label, label reported/marked — "Chief" alone names two positions).
_203_POSITIONS = {
    'deputy_ic': ('Incident Commander(s) and Command Staff', 'Deputy', 'Deputy IC'),
    'liaison_officer': ('Incident Commander(s) and Command Staff', 'Liaison Officer', 'Liaison Officer'),
    'planning_chief': ('Planning Section', 'Chief', 'Planning Section Chief'),
    'situation_unit': ('Planning Section', 'Situation Unit', 'Situation Unit'),
    'documentation_unit': ('Planning Section', 'Documentation Unit', 'Documentation Unit'),
    'technical_specialists': ('Planning Section', 'Technical Specialists', 'Technical Specialists'),
    'operations_chief': ('Operations Section', 'Chief', 'Operations Section Chief'),
}


class IcsDraftError(Exception):
    """Raised when the pass cannot run or the model output is unusable —
    never persisted; the endpoint renders it as a transient error."""


# --------------------------------------------------------------- payload

def _load_system_prompt() -> str:
    with open(_PROMPT_PATH, encoding='utf-8') as fh:
        return fh.read()


def _uname(u) -> str | None:
    if u is None:
        return None
    return (u.name or u.user or '').strip() or None


def build_ics_payload(room: WarRoom) -> dict[str, Any]:
    """The SitRep payload (room, server stats, cases + cached summaries,
    recent activity) extended with what the ICS forms need: case
    descriptions, tags, server-computed per-case counts, open tasks, the
    members with roles, and the CANDIDATE list for ICS 203 names."""
    from app.iris_engine.ai.sitrep_draft import build_sitrep_payload

    payload = build_sitrep_payload(room)
    payload['room']['severity'] = room.severity
    payload['room']['status'] = room.status

    case_ids = [r.case_id for r in
                WarRoomCaseLink.query.filter_by(room_id=room.id).all()]
    cases = {c.case_id: c for c in
             (Cases.query.filter(Cases.case_id.in_(case_ids)).all()
              if case_ids else [])}

    owners: dict[int, dict] = {}
    for entry in payload['cases']:
        c = cases.get(entry['case_id'])
        if c is None:
            continue
        entry['description'] = (c.description or '')[:_DESC_CAP] or None
        entry['tags'] = [t.tag_title for t in (c.tags or [])][:20]
        entry['owner'] = _uname(c.owner)
        entry['state'] = c.state.state_name if c.state else None
        entry['counts'] = {
            'iocs': Ioc.query.filter(Ioc.case_id == c.case_id).count(),
            'assets': CaseAssets.query.filter(CaseAssets.case_id == c.case_id).count(),
            'evidence': CaseReceivedFile.query.filter(
                CaseReceivedFile.case_id == c.case_id).count(),
            'tasks': CaseTasks.query.filter(CaseTasks.task_case_id == c.case_id).count(),
            'timeline_events': CasesEvent.query.filter(
                CasesEvent.case_id == c.case_id).count(),
        }
        tasks = (CaseTasks.query.filter(CaseTasks.task_case_id == c.case_id)
                 .order_by(CaseTasks.id.asc()).limit(_TASKS_CAP).all())
        entry['tasks'] = [{
            'title': (t.task_title or '')[:200],
            'status': t.status.status_name if t.status else None,
        } for t in tasks]
        if c.owner is not None and c.owner.id not in owners:
            owners[c.owner.id] = {'name': _uname(c.owner), 'login': c.owner.user,
                                  'source': 'case owner', 'cases': []}
        if c.owner is not None:
            owners[c.owner.id]['cases'].append(c.case_id)

    members = (WarRoomMember.query.filter_by(room_id=room.id)
               .order_by(WarRoomMember.added_at.asc(), WarRoomMember.id.asc()).all())
    payload['members'] = [{
        'name': _uname(m.user), 'login': m.user.user if m.user else None,
        'role': m.role,
    } for m in members]

    # ICS 203 candidates: room members + owners of the attached cases. A
    # LEAD is already the Incident Commander (deterministic pass) and is not
    # a candidate for any other position — on a one-member room the only
    # honest 203 is one with every other position still `—`.
    candidates: list[dict] = []
    seen: set[int] = set()
    for m in members:
        if m.user is None or m.user_id in seen or m.role == 'lead':
            continue
        seen.add(m.user_id)
        candidates.append({
            'name': _uname(m.user), 'login': m.user.user,
            'source': 'room member (%s)' % m.role,
            'cases': owners.get(m.user_id, {}).get('cases', []),
        })
    lead_ids = {m.user_id for m in members if m.role == 'lead'}
    for uid, o in owners.items():
        if uid in seen or uid in lead_ids:
            continue
        seen.add(uid)
        candidates.append(o)
    payload['candidates'] = [c for c in candidates if c.get('name')]
    return payload


def _compute_input_hash(payload: dict, system_prompt: str, model: str) -> str:
    canon = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    h = hashlib.md5()
    h.update(model.encode('utf-8'))
    h.update(b'\x00')
    h.update(system_prompt.encode('utf-8'))
    h.update(b'\x00')
    h.update(canon.encode('utf-8'))
    return h.hexdigest()


def _find_cache_hit(room_id: int, input_hash: str) -> AiArtifact | None:
    return (AiArtifact.query
            .filter(AiArtifact.anchor_type == ANCHOR_TYPE,
                    AiArtifact.anchor_id == room_id,
                    AiArtifact.kind == KIND,
                    AiArtifact.input_hash == input_hash)
            .order_by(AiArtifact.generated_at.desc())
            .first())


# ------------------------------------------------ response normalisation

def _prose(value, cap=_PROSE_CAP) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s == '—':
        return None
    # A heading inside a filled field would split the note's sections and
    # break the next run's locate step — demote to plain text.
    s = re.sub(r'^#+\s*', '', s, flags=re.M)
    return s[:cap]


def _item(value) -> str | None:
    s = _prose(value, _ITEM_CAP)
    if s is None:
        return None
    return s.replace('\r', ' ').replace('\n', ' ').strip()


def _str_list(value, cap=_LIST_CAP) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return None
    out = [x for x in (_item(v) for v in value) if x]
    return out[:cap] or None


def _cell(value) -> str:
    s = '' if value is None else str(value)
    s = s.replace('\r', ' ').replace('\n', ' ').replace('|', '\\|').strip()
    return s or '—'


def _candidate_name(value, candidates: list[dict]) -> str | None:
    """Validate AND re-derive: a proposed name must match a candidate's
    display name or login (case-insensitive); the stored display name is
    what lands in the form. Anything else is dropped."""
    if value is None:
        return None
    key = str(value).strip().lower()
    if not key:
        return None
    for c in candidates:
        for k in (c.get('name'), c.get('login')):
            if k and str(k).strip().lower() == key:
                return c['name']
    return None


def _parse_response(raw: str, candidates: list[dict]) -> dict[str, Any]:
    """Extract, validate and normalise the JSON proposal. RAISES on failure —
    an unparseable response must never be persisted. Every field is
    optional; `None` means "leave the `—` for the human"."""
    cleaned = re.sub(r'```(?:json)?\s*', '', raw or '').strip().rstrip('`').strip()
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if not match:
        raise IcsDraftError('AI backend returned no JSON object')
    try:
        obj = json.loads(match.group())
    except json.JSONDecodeError as exc:
        raise IcsDraftError(f'AI backend returned invalid JSON: {exc}')
    if not isinstance(obj, dict) or not any(
            isinstance(obj.get(k), dict) for k in ('ics_201', 'ics_202', 'ics_203')):
        raise IcsDraftError('AI backend returned no ICS form object')

    f1 = obj.get('ics_201') if isinstance(obj.get('ics_201'), dict) else {}
    f2 = obj.get('ics_202') if isinstance(obj.get('ics_202'), dict) else {}
    f3 = obj.get('ics_203') if isinstance(obj.get('ics_203'), dict) else {}

    actions = None
    if isinstance(f1.get('actions'), list):
        rows = []
        for a in f1['actions']:
            if isinstance(a, dict):
                act = _item(a.get('action'))
                if act:
                    rows.append({'time': _item(a.get('time')), 'action': act})
            else:
                act = _item(a)
                if act:
                    rows.append({'time': None, 'action': act})
        actions = rows[:_ROWS_CAP] or None

    resources = None
    if isinstance(f1.get('resources'), list):
        rows = []
        for r in f1['resources']:
            if isinstance(r, dict):
                res = _item(r.get('resource'))
                if res:
                    rows.append({'resource': res, 'identifier': _item(r.get('identifier')),
                                 'notes': _item(r.get('notes'))})
            else:
                res = _item(r)
                if res:
                    rows.append({'resource': res, 'identifier': None, 'notes': None})
        resources = rows[:_ROWS_CAP] or None

    ssp = f2.get('site_safety_plan_required')
    ssp = {'yes': 'Yes', 'no': 'No'}.get(str(ssp).strip().lower()) if ssp is not None else None

    dropped: list[str] = []

    def _name(v):
        n = _candidate_name(v, candidates)
        if n is None and v not in (None, ''):
            dropped.append(str(v)[:80])
        return n

    # One person, one position: a small model handed a single candidate
    # proposes that name for every slot. First placement in this priority
    # order wins; later ones are dropped. Technical Specialists may list
    # anyone not otherwise placed.
    placed: set[str] = set()
    positions: dict[str, str | None] = {}
    for key in ('operations_chief', 'planning_chief', 'liaison_officer',
                'deputy_ic', 'situation_unit', 'documentation_unit'):
        n = _name(f3.get(key))
        if n is not None and n in placed:
            n = None
        if n is not None:
            placed.add(n)
        positions[key] = n

    specialists = None
    if f3.get('technical_specialists') is not None:
        raw_list = f3['technical_specialists']
        if isinstance(raw_list, str):
            raw_list = [raw_list]
        if isinstance(raw_list, list):
            names = []
            for v in raw_list:
                n = _name(v)
                if n and n not in names and n not in placed:
                    names.append(n)
            specialists = names[:_LIST_CAP] or None

    return {
        'ics_201': {
            'situation_summary': _prose(f1.get('situation_summary')),
            'health_safety': _prose(f1.get('health_safety'), 1200),
            'objectives': _str_list(f1.get('objectives')),
            'actions': actions,
            'resources': resources,
        },
        'ics_202': {
            'objectives': _str_list(f2.get('objectives')),
            'command_emphasis': _prose(f2.get('command_emphasis')),
            'site_safety_plan_required': ssp,
        },
        'ics_203': dict(positions, technical_specialists=specialists),
        'dropped_names': dropped,
    }


# --------------------------------------------------------------- merging
#
# Every filler takes a SECTION BODY (the text between one `## N. Heading`
# and the next `## `) and returns (new_body, filled). A filler that finds
# its empty marker absent — because the seed, an analyst, or a previous run
# already wrote there — returns the body unchanged. The empty markers are
# the templates' own.

def _section_span(text: str, heading: str):
    m = re.search(r'^## \d+\. ' + re.escape(heading) + r'[ \t]*$', text, re.M)
    if not m:
        return None
    start = m.end()
    nxt = re.search(r'^## ', text[start:], re.M)
    end = start + nxt.start() if nxt else len(text)
    return start, end


def _replace_line(body: str, pattern: str, replacement: str):
    """Replace the FIRST line matching `pattern` (full-line, multiline)."""
    m = re.search(pattern, body, re.M)
    if not m:
        return body, False
    return body[:m.start()] + replacement + body[m.end():], True


def _fill_sentinel(body, sentinel, text):
    if text is None:
        return body, False
    return _replace_line(body, r'^' + re.escape(sentinel) + r'[ \t]*$',
                         text + '\n\n' + MARK)


def _fill_health_safety(body, text):
    if text is None:
        return body, False
    m = re.search(r'^_Health & safety \((.*?)\): —_[ \t]*$', body, re.M)
    if not m:
        return body, False
    line = '_Health & safety (%s):_ %s\n\n%s' % (m.group(1), text.replace('\n', ' '), MARK)
    return body[:m.start()] + line + body[m.end():], True


def _fill_bullets(body, items, numbered=False):
    """Fill a list whose every item is still `—`. A list with ONE real item
    is the analyst's — left alone."""
    if not items:
        return body, False
    if numbered:
        item_re = r'^\d+\. (.*)$'
        empty_re = r'(?:^\d+\. —[ \t]*$\n?)+'
        render = '\n'.join('%d. %s' % (i + 1, it) for i, it in enumerate(items))
    else:
        item_re = r'^- (.*)$'
        empty_re = r'(?:^- —[ \t]*$\n?)+'
        render = '\n'.join('- ' + it for it in items)
    existing = [x.strip() for x in re.findall(item_re, body, re.M)]
    if not existing or any(x != '—' for x in existing):
        return body, False
    m = re.search(empty_re, body, re.M)
    if not m:
        return body, False
    return body[:m.start()] + render + '\n\n' + MARK + '\n' + body[m.end():], True


def _fill_table(body, empty_row, rows):
    """Replace the template's all-dash row with real rows. The dash row is
    the empty marker; rows an analyst added above it stay."""
    if not rows:
        return body, False
    return _replace_line(body, r'^' + re.escape(empty_row) + r'[ \t]*$',
                         '\n'.join(rows) + '\n\n' + MARK)


def _fill_position(body, position, name):
    if not name:
        return body, False
    return _replace_line(body, r'^\| ' + re.escape(position) + r' \| — \|[ \t]*$',
                         '| %s | %s |' % (position, _cell(name)))


def _apply_201(content: str, f: dict) -> tuple[str, list[str]]:
    filled: list[str] = []

    def _in_section(heading, label, fn):
        nonlocal content
        span = _section_span(content, heading)
        if span is None:
            return
        body, ok = fn(content[span[0]:span[1]])
        if ok:
            content = content[:span[0]] + body + content[span[1]:]
            filled.append(label)

    def _s4(body):
        b, ok1 = _fill_sentinel(body, '_No room summary yet._', f.get('situation_summary'))
        b, ok2 = _fill_health_safety(b, f.get('health_safety'))
        return b, ok1 or ok2

    _in_section('Situation Summary and Health & Safety Briefing', '§4 situation', _s4)
    _in_section('Current and Planned Objectives', '§6 objectives',
                lambda b: _fill_bullets(b, f.get('objectives')))
    _in_section('Current and Planned Actions, Strategies and Tactics', '§7 actions',
                lambda b: _fill_table(b, '| — | — |', [
                    '| %s | %s |' % (_cell(a.get('time')), _cell(a.get('action')))
                    for a in (f.get('actions') or [])]))
    _in_section('Resource Summary', '§9 resources',
                lambda b: _fill_table(b, '| — | — | — | — | — | — |', [
                    '| %s | %s | — | — | — | %s |' % (
                        _cell(r.get('resource')), _cell(r.get('identifier')), _cell(r.get('notes')))
                    for r in (f.get('resources') or [])]))
    return content, filled


def _apply_202(content: str, f: dict) -> tuple[str, list[str]]:
    filled: list[str] = []

    def _in_section(heading, label, fn):
        nonlocal content
        span = _section_span(content, heading)
        if span is None:
            return
        body, ok = fn(content[span[0]:span[1]])
        if ok:
            content = content[:span[0]] + body + content[span[1]:]
            filled.append(label)

    _in_section('Objective(s)', '§3 objectives',
                lambda b: _fill_bullets(b, f.get('objectives'), numbered=True))

    def _s4(body):
        ok1 = ok2 = False
        if f.get('command_emphasis'):
            body, ok1 = _replace_line(body, r'^—[ \t]*$',
                                      f['command_emphasis'] + '\n\n' + MARK)
        body, ok2 = _fill_sentinel(body, '_No room summary yet._',
                                   f.get('situation_summary'))
        return body, ok1 or ok2

    _in_section('Operational Period Command Emphasis', '§4 command emphasis', _s4)

    def _s5(body):
        v = f.get('site_safety_plan_required')
        if not v:
            return body, False
        return _replace_line(body, r'^— \(Yes / No\)(.*)$',
                             '%s (Yes / No)\\1 · %s' % (v, MARK))

    _in_section('Site Safety Plan Required?', '§5 site safety plan', _s5)
    return content, filled


def _apply_203(content: str, f: dict) -> tuple[str, list[str]]:
    filled: list[str] = []
    for key, (heading, position, label) in _203_POSITIONS.items():
        value = f.get(key)
        if isinstance(value, list):
            value = ', '.join(value)
        if not value:
            continue
        span = _section_span(content, heading)
        if span is None:
            continue
        body, ok = _fill_position(content[span[0]:span[1]], position, value)
        if ok:
            content = content[:span[0]] + body + content[span[1]:]
            filled.append(label)
    if filled:
        # One marker per form for cell fills — a marker inside a table cell
        # would be noise, and the header line names the positions.
        span = _section_span(content, 'Prepared By')
        if span is not None:
            content = content[:span[0]] + '\n' + MARK + '\n' + content[span[0]:]
    return content, filled


def _header_line(model: str, labels: list[str]) -> str:
    return ('> AI pass (%s, %s UTC) filled: %s. Each filled field carries an '
            '"AI draft" line — review it and delete the line.' % (
                model or 'model', datetime.utcnow().strftime('%Y-%m-%d %H:%M'),
                ', '.join(labels)))


def _insert_header(content: str, line: str) -> str:
    """After the seeded intro blockquote when it is still there, else at the
    very top — the header is what tells the reader which fields a machine
    wrote."""
    m = re.search(r'^> .*$', content, re.M)
    if m:
        return content[:m.end()] + '\n' + line + content[m.end():]
    return line + '\n\n' + content


def apply_ics_draft(room: WarRoom, proposal: dict, actor_id: int | None,
                    model: str) -> dict[str, Any]:
    """Merge a (validated) proposal into the room's ICS notes: fill only the
    empty fields, mark every fill, commit. Returns what happened per form."""
    from app.business.war_room_ics import ICS_FORMS

    appliers = {'ics_201': (_apply_201, proposal.get('ics_201') or {}),
                'ics_202': (_apply_202, dict(proposal.get('ics_202') or {},
                                             situation_summary=(proposal.get('ics_201') or {}).get('situation_summary'))),
                'ics_203': (_apply_203, proposal.get('ics_203') or {})}
    filled: dict[str, list[str]] = {}
    untouched: list[str] = []
    missing: list[str] = []
    note_ids: dict[str, int] = {}
    now = datetime.utcnow()
    for title, _file in ICS_FORMS:
        note = (WarRoomNote.query.filter_by(room_id=room.id, title=title)
                .order_by(WarRoomNote.id.asc()).first())
        if note is None:
            missing.append(title)
            continue
        note_ids[title] = note.id
        fn, fields = appliers[_FORM_KEYS[title]]
        new_content, labels = fn(note.content or '', fields)
        if not labels:
            untouched.append(title)
            continue
        note.content = _insert_header(new_content, _header_line(model, labels))
        note.updated_at = now
        note.updated_by = actor_id
        filled[title] = labels
    db.session.commit()
    return {'filled': filled, 'untouched': untouched, 'missing': missing,
            'note_ids': note_ids}


# -------------------------------------------------------------- orchestration

# Budget = thinking + output: reasoning models spend tokens before the JSON.
_MAX_TOKENS = 6000
_COMPACT_SUMMARY_CAP = 1500
_COMPACT_ACTIVITY_CAP = 15


def _chat(client: OpenAIClient, system_prompt: str, payload: dict) -> tuple[str, str | None]:
    """One model call. Returns (extracted content, finish_reason)."""
    messages = [
        {'role': 'system',
         'content': system_prompt + '\n\n' + json.dumps(payload, indent=2,
                                                        default=str)},
        {'role': 'user',
         'content': 'Complete the ICS forms for the war room above. Output '
                    'ONLY the JSON object — no prose, no markdown fences.'},
    ]
    resp = client.chat(messages, max_tokens=_MAX_TOKENS)
    raw = OpenAIClient.extract_content(resp)
    try:
        finish = (resp.get('choices') or [{}])[0].get('finish_reason')
    except (AttributeError, IndexError, TypeError):
        finish = None
    return raw, finish


def _compact_payload(payload: dict) -> dict:
    """The same facts, less prose: summaries capped, activity trimmed to the
    newest few items. Counts, cases, members and candidates are untouched —
    a compact payload must not change what the model may claim."""
    p = json.loads(json.dumps(payload, default=str))
    for c in p.get('cases', []):
        if c.get('summary'):
            c['summary'] = c['summary'][:_COMPACT_SUMMARY_CAP]
        c['tasks'] = (c.get('tasks') or [])[:10]
    ra = p.get('recent_activity') or {}
    ra['messages'] = (ra.get('messages') or [])[:_COMPACT_ACTIVITY_CAP]
    ra['case_activity'] = (ra.get('case_activity') or [])[:_COMPACT_ACTIVITY_CAP]
    p['recent_activity'] = ra
    return p


def run_ics_draft(room_id: int, actor_id: int | None, *, force: bool = False) -> dict[str, Any]:
    """Generate (or reuse the cached) proposal, then merge it into the
    room's ICS notes. The merge runs on every call — it reads the notes'
    CURRENT text, so a cached proposal still fills a form that was
    re-seeded or had a field cleared since."""
    from app.business.war_room_ics import ics_state

    room = db.session.get(WarRoom, room_id)
    if room is None:
        raise IcsDraftError(f'War room #{room_id} not found')
    if room.status == 'closed':
        raise IcsDraftError('Room is closed')
    st = ics_state(room)
    if st['missing']:
        raise IcsDraftError('ICS forms are not seeded in this room: '
                            + ', '.join(st['missing']))

    client: OpenAIClient | None = build_default_client(
        feature=FEATURE_KEY, timeout=240.0, default_max_tokens=_MAX_TOKENS)
    if client is None:
        raise IcsDraftError(
            'AI backend is not configured. Enable it in Manage → Settings → AI.')

    system_prompt = _load_system_prompt()
    payload = build_ics_payload(room)
    input_hash = _compute_input_hash(payload, system_prompt, client.model)

    art = None if force else _find_cache_hit(room_id, input_hash)
    cached = art is not None
    if art is not None:
        try:
            proposal = json.loads(art.content)
        except (TypeError, ValueError):
            art, proposal = None, None
    if art is None:
        try:
            raw, finish = _chat(client, system_prompt, payload)
            if not raw.strip() and finish == 'length':
                # A reasoning model can spend the whole budget thinking and
                # emit nothing (observed: 3000 reasoning tokens, 0 content on
                # a 16 KB payload). One retry on a compact payload — the
                # material the forms need most, less to reason over.
                log.warning('ics_draft: empty reply at the token limit from %s '
                            '(room=%s) — retrying with a compact payload',
                            client.model, room_id)
                raw, finish = _chat(client, system_prompt, _compact_payload(payload))
        except AIClientError as exc:
            log.error('ics_draft: AI call failed — %s', exc)
            raise IcsDraftError(str(exc))
        try:
            proposal = _parse_response(raw, payload['candidates'])
        except IcsDraftError:
            # The reply is not persisted; keep its head in the log so an
            # operator can tell a truncated JSON from a model that chatted.
            log.warning('ics_draft: unusable reply from %s (room=%s): %r',
                        client.model, room_id, (raw or '')[:400])
            raise
        art = AiArtifact(
            anchor_type=ANCHOR_TYPE, anchor_id=room_id, kind=KIND,
            prompt_id=PROMPT_ID, model=client.model, input_hash=input_hash,
            content=json.dumps(proposal, ensure_ascii=False), confidence=None)
        db.session.add(art)
        db.session.commit()
        cached = False
        log.info('ics_draft: persisted proposal (room=%s, artifact=%s)', room_id, art.id)

    merged = apply_ics_draft(room, proposal, actor_id, client.model)
    merged.update({
        'cached': cached, 'model': client.model, 'prompt_id': PROMPT_ID,
        'artifact_id': art.id, 'room_id': room_id,
        'dropped_names': proposal.get('dropped_names') or [],
    })
    return merged


def enqueue_ics_draft_soft(room: WarRoom, actor_id: int) -> str | None:
    """Queue the AI pass after a seed. NEVER raises: no backend configured,
    broker down, anything — the attach/seed that triggered it must still
    succeed. Returns the job task_id, or None when nothing was queued."""
    try:
        if room.status == 'closed':
            return None
        if build_default_client(feature=FEATURE_KEY) is None:
            return None
        from app.iris_engine.ai.ai_jobs import enqueue_ai_job
        job = enqueue_ai_job(feature=FEATURE_KEY, case_id=None, user_id=actor_id,
                             params={'room_id': room.id, 'actor_id': actor_id,
                                     'force': False})
        return job.task_id
    except Exception as exc:  # noqa: BLE001 - deliberately broad, logged
        log.warning('ics_draft: auto-run not queued for war room %s: %s',
                    getattr(room, 'id', '?'), exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover
            pass
        return None

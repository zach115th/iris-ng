#!/usr/bin/env python3
#
#  IRIS Source Code
#  Copyright (C) 2026 - IRIS-NG contributors
#  contact@dfir-iris.org
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

"""War-room operational summary (iris-ng v2): an ongoing, AI-maintained,
analyst-editable summary of a room's cases at ICS / ESF operational level.

Design (maintainer decisions, 2026-09-29):

  - It is its OWN artifact (`AiArtifact` anchor_type='war_room',
    kind='room_summary'). `WarRoom.summary` — the short analyst blurb that
    reaches the STIX export and the MISP push as the campaign description —
    is untouched: operational text names counties, utilities and agencies
    and must never leave through those paths.
  - Fixed ICS-209-shaped sections (see SECTIONS). Emergency Support Functions
    are DERIVED on the server from the attached cases' sector tags through
    `resources/ca_esf_map.json` (California ESF list; a deployment swaps the
    file); the model quotes them, never invents them.
  - "Ongoing" = event-driven while untouched, frozen once edited: case
    attach/detach, SitRep publish, ICS note save and status change call
    `auto_refresh()`, which enqueues a regeneration ONLY when a summary
    already exists (the first Generate is the per-room opt-in), no analyst
    edit is present, the room is not closed and no job is already queued. A
    server-computed `stale` flag (input hash) tells the tab when the inputs
    moved on, whatever the mode.
  - The summary and the SitRep drafter pull from the same stored rows but
    NEVER from each other (circular reporting): this payload carries no
    SitRep, and `sitrep_draft` never reads this artifact.
  - The manual edit uses `AiOverrideMixin` like every other AI surface:
    the original stays in `content`, the edit in `edited_content`, and a
    regeneration answers 409 `manual_edit_present` unless the caller says
    `discard_edit`.
  - A reply that is not the contract (no JSON, empty situation) is an ERROR
    and is never persisted; the budget covers a reasoning model's thinking
    step, with one compact retry on an empty `length` reply.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from typing import Any

from sqlalchemy import desc

from app import db
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import OpenAIClient
from app.iris_engine.ai.openai_client import build_default_client
from app.models.authorization import User
from app.models.cases import Cases
from app.models.models import AiArtifact
from app.models.models import AiJob
from app.models.models import CaseAiArtifact
from app.models.models import CaseTasks
from app.models.models import SectorCatalog
from app.models.models import UserActivity
from app.models.models import WarRoom
from app.models.models import WarRoomCaseLink
from app.models.models import WarRoomMessage
from app.models.models import WarRoomNote
from app.models.models import WarRoomTask

log = logging.getLogger(__name__)

PROMPT_ID = 'RoomSummarySystemPrompt-v1'
FEATURE_KEY = 'room_summary'
KIND = 'room_summary'
ANCHOR_TYPE = 'war_room'
MANUAL_MODEL = 'manual'

_RES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'resources')
_PROMPT_PATH = os.path.join(_RES_DIR, 'ai_prompts', 'room_summary.md')
ESF_MAP_PATH = os.path.join(_RES_DIR, 'ca_esf_map.json')

# Reasoning models spend tokens thinking before the first visible character;
# the budget covers both (chat / task suggester / tag suggester precedent).
ROOM_SUMMARY_MAX_TOKENS = 6000
COMPACT_RETRY_SUFFIX = (
    '\n\nAnswer NOW with the JSON object only. Keep every section short (at '
    'most four bullets or two paragraphs). No reasoning before the answer.'
)

# (key, heading) — the ICS 209 shape the maintainer chose. Order = render order.
SECTIONS: tuple[tuple[str, str], ...] = (
    ('situation', 'Situation'),
    ('significant_events', 'Significant events this period'),
    ('life_safety_threat', 'Life safety and threat'),
    ('projected_activity', 'Projected activity'),
    ('objectives', 'Current objectives'),
    ('resource_needs', 'Critical resource needs'),
    ('planned_actions', 'Planned actions'),
    ('cooperating_agencies', 'Cooperating agencies and ESFs'),
)
_PARAGRAPH_SECTIONS = {'situation', 'life_safety_threat', 'projected_activity'}

_ICS_FORMS_FOR_SUMMARY = ('201', '202', '209')
_CASE_SUMMARY_CHAR_CAP = 6000
_ICS_CHAR_CAP = 4000
_ACTIVITY_CAP = 60
_ROOM_TASK_CAP = 40
_CLOSED_TASK_NAMES = {'done', 'canceled', 'cancelled'}
_CLOSED_ROOM_TASK_STATES = {'done', 'cancelled', 'canceled'}


class RoomSummaryError(Exception):
    """Raised for every failure the caller must surface; nothing is persisted."""


# ---------------------------------------------------------------- ESF table

_esf_cache: dict | None = None


def load_esf_map() -> dict:
    """The deployment's ESF table (California list shipped; a deployment
    swaps the file). Cached per process; fail-loud on a malformed file."""
    global _esf_cache
    if _esf_cache is None:
        with open(ESF_MAP_PATH, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        for key in ('list', 'functions', 'always', 'sectors'):
            if key not in data:
                raise RoomSummaryError(f'ESF map is missing "{key}"')
        _esf_cache = data
    return _esf_cache


def derive_esfs(sector_slugs) -> list[dict[str, Any]]:
    """Server-derived ESF list: the `always` entries (CA-ESF 18 Cybersecurity
    for every room) plus every function the attached sectors map to, ordered
    by number, each with the sectors that triggered it."""
    table = load_esf_map()
    funcs = table['functions']
    by_id: dict[int, set[str]] = {}
    for n in table.get('always') or []:
        by_id.setdefault(int(n), set())
    for slug in sector_slugs or []:
        for n in table['sectors'].get(slug) or []:
            by_id.setdefault(int(n), set()).add(slug)
    out = []
    for n in sorted(by_id):
        name = funcs.get(str(n))
        if not name:
            continue  # a sector row pointing at a function the list lacks
        out.append({'id': n, 'label': f'{table["list"]} {n}', 'name': name,
                    'from_sectors': sorted(by_id[n])})
    return out


def _sector_lookup() -> dict[str, str]:
    """Normalised machine-tag -> slug from the catalog (every row, enabled or
    not — recognition must never orphan a historical tag)."""
    out = {}
    for row in SectorCatalog.query.with_entities(SectorCatalog.tag, SectorCatalog.slug).all():
        out[_norm_tag(row.tag)] = row.slug
    return out


def _norm_tag(title: str) -> str:
    return (title or '').replace('"', '').replace("'", '').strip().lower()


def case_sector_slugs(case, lookup: dict[str, str] | None = None) -> list[str]:
    lookup = lookup if lookup is not None else _sector_lookup()
    slugs = []
    for t in (case.tags or []):
        slug = lookup.get(_norm_tag(getattr(t, 'tag_title', '')))
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs


def room_sector_slugs(room) -> list[str]:
    lookup = _sector_lookup()
    slugs: list[str] = []
    for c in _room_cases(room):
        for s in case_sector_slugs(c, lookup):
            if s not in slugs:
                slugs.append(s)
    return slugs


# ------------------------------------------------------------------ payload

def _load_system_prompt() -> str:
    with open(_PROMPT_PATH, 'r', encoding='utf-8') as fh:
        return fh.read()


def _room_cases(room) -> list:
    case_ids = [r.case_id for r in
                WarRoomCaseLink.query.filter_by(room_id=room.id).all()]
    if not case_ids:
        return []
    return Cases.query.filter(Cases.case_id.in_(case_ids)).order_by(Cases.case_id).all()


def _latest_case_summary(case_id: int) -> str | None:
    art = (CaseAiArtifact.query
           .filter(CaseAiArtifact.case_id == case_id,
                   CaseAiArtifact.kind == 'case_summary')
           .order_by(CaseAiArtifact.generated_at.desc())
           .first())
    if art is None:
        return None
    text = (art.display_content or '').strip()
    return text[:_CASE_SUMMARY_CHAR_CAP] if text else None


def _case_task_counts(case_id: int) -> dict[str, int]:
    rows = (CaseTasks.query.filter(CaseTasks.task_case_id == case_id).all())
    total = len(rows)
    closed = sum(1 for t in rows
                 if t.status and (t.status.status_name or '').strip().lower() in _CLOSED_TASK_NAMES)
    return {'open': total - closed, 'total': total}


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def build_room_summary_payload(room: WarRoom) -> dict[str, Any]:
    """Assemble the prompt payload purely from stored rows. NO SitRep is read
    here — the summary and the SitRep drafter must never feed each other."""
    from app.business.war_room_ics import form_number  # pure helper, no cycle

    lookup = _sector_lookup()
    cases = _room_cases(room)
    case_entries = []
    all_slugs: list[str] = []
    summaries_available = 0
    for c in cases:
        slugs = case_sector_slugs(c, lookup)
        for s in slugs:
            if s not in all_slugs:
                all_slugs.append(s)
        summary = _latest_case_summary(c.case_id)
        if summary:
            summaries_available += 1
        case_entries.append({
            'case_id': c.case_id,
            'name': c.name,
            'client': c.client.name if c.client else None,
            'classification': c.classification.name if c.classification else None,
            'severity': c.severity.severity_name if c.severity else None,
            'open_date': _iso(c.open_date),
            'closed': c.close_date is not None,
            'sectors': slugs,
            'tasks': _case_task_counts(c.case_id),
            'summary': summary,
        })

    room_tasks = (WarRoomTask.query.filter_by(room_id=room.id)
                  .order_by(desc(WarRoomTask.id)).all())
    open_room_tasks = [t for t in room_tasks
                       if (t.status or '') not in _CLOSED_ROOM_TASK_STATES]
    task_entries = [{
        'title': t.title,
        'status': t.status,
        'assignee': (t.assignee.name if getattr(t, 'assignee', None) else None),
    } for t in open_room_tasks[:_ROOM_TASK_CAP]]

    ics_entries = []
    for n in (WarRoomNote.query.filter_by(room_id=room.id)
              .order_by(WarRoomNote.id).all()):
        num = form_number(n.title)
        if num in _ICS_FORMS_FOR_SUMMARY and (n.content or '').strip():
            ics_entries.append({'form': num, 'title': n.title,
                                'content': (n.content or '')[:_ICS_CHAR_CAP]})

    case_ids = [c.case_id for c in cases]
    msgs = (WarRoomMessage.query.filter_by(room_id=room.id)
            .order_by(desc(WarRoomMessage.id)).limit(_ACTIVITY_CAP).all())
    acts = ((UserActivity.query
             .filter(UserActivity.case_id.in_(case_ids),
                     UserActivity.display_in_ui.is_(True))
             .order_by(desc(UserActivity.activity_date))
             .limit(_ACTIVITY_CAP).all()) if case_ids else [])

    esf = derive_esfs(all_slugs)
    table = load_esf_map()
    return {
        'room': {
            'name': room.name,
            'description': room.description,
            'analyst_description': room.summary,
            'status': room.status,
            'severity': room.severity,
            'campaign_tag': room.campaign_tag,
            'created_at': _iso(room.created_at),
        },
        'esf_list': table['list'],
        'esf': esf,
        'stats': {
            'attached_cases': len(case_entries),
            'open_cases': sum(1 for e in case_entries if not e['closed']),
            'closed_cases': sum(1 for e in case_entries if e['closed']),
            'cases_with_summary': summaries_available,
            'open_room_tasks': len(open_room_tasks),
            'ics_forms_present': [e['form'] for e in ics_entries],
            'chat_messages_in_window': len(msgs),
            'case_activities_in_window': len(acts),
        },
        'cases': case_entries,
        'room_tasks': task_entries,
        'ics_forms': ics_entries,
        'recent_activity': {
            'messages': [{
                'user': m.user.name if m.user else 'deleted user',
                'at': _iso(m.created_at),
                'content': (m.content or '')[:400],
            } for m in msgs],
            'case_activity': [{
                'case_id': a.case_id,
                'at': _iso(a.activity_date),
                'description': (a.activity_desc or '')[:300],
            } for a in acts],
        },
    }


def _compute_input_hash(payload: dict, system_prompt: str, model: str) -> str:
    canon = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    h = hashlib.md5()
    h.update(model.encode('utf-8'))
    h.update(b'\x00')
    h.update(system_prompt.encode('utf-8'))
    h.update(b'\x00')
    h.update(canon.encode('utf-8'))
    return h.hexdigest()


# ---------------------------------------------------------------- artifacts

def get_latest(room_id: int) -> AiArtifact | None:
    return (AiArtifact.query
            .filter(AiArtifact.anchor_type == ANCHOR_TYPE,
                    AiArtifact.anchor_id == room_id,
                    AiArtifact.kind == KIND)
            .order_by(AiArtifact.generated_at.desc(), AiArtifact.id.desc())
            .first())


def _find_cache_hit(room_id: int, input_hash: str) -> AiArtifact | None:
    return (AiArtifact.query
            .filter(AiArtifact.anchor_type == ANCHOR_TYPE,
                    AiArtifact.anchor_id == room_id,
                    AiArtifact.kind == KIND,
                    AiArtifact.input_hash == input_hash)
            .order_by(AiArtifact.generated_at.desc(), AiArtifact.id.desc())
            .first())


def is_stale(room: WarRoom, art: AiArtifact | None) -> bool | None:
    """True when the room's inputs no longer hash to what `art` was built
    from; None when there is nothing to compare (no artifact, or a manual
    row that was never generated)."""
    if art is None or art.model == MANUAL_MODEL:
        return None
    payload = build_room_summary_payload(room)
    return _compute_input_hash(payload, _load_system_prompt(), art.model) != art.input_hash


def compose_markdown(sections: dict[str, Any]) -> str:
    """One Markdown body from the stored sections, in SECTIONS order; the
    server appends the derived ESF lines so a cached read renders them too."""
    parts = []
    for key, heading in SECTIONS:
        body = (sections.get(key) or '').strip()
        if not body and key != 'situation':
            continue
        parts += [f'## {heading}', body or '_not yet established_', '']
    esf = sections.get('esf') or []
    if esf:
        parts += ['## Emergency Support Functions (server-derived)']
        for e in esf:
            src = (', from ' + ', '.join(e['from_sectors'])) if e.get('from_sectors') else ''
            parts.append(f'- **{e["label"]} {e["name"]}**{src}')
        parts.append('')
    return '\n'.join(parts).strip() + '\n'


def artifact_to_result(room: WarRoom, art: AiArtifact, *, cached: bool,
                       stale: bool | None = None) -> dict[str, Any]:
    from app.iris_engine.safe_markdown import render_markdown_safe
    try:
        obj = json.loads(art.content)
    except (TypeError, ValueError):
        raise RoomSummaryError('Stored summary is unreadable — regenerate')
    ai_markdown = compose_markdown(obj)
    shown = art.edited_content if art.is_edited else ai_markdown
    return {
        'artifact_id': art.id,
        'room_id': room.id,
        'sections': {k: obj.get(k, '') for k, _ in SECTIONS},
        'esf': obj.get('esf') or [],
        'esf_list': obj.get('esf_list'),
        'markdown': shown,
        'ai_markdown': ai_markdown,
        'content_html': render_markdown_safe(shown),
        'edited': art.is_edited,
        'edited_by_name': (art.edited_by.name if art.edited_by else None),
        'edited_at': _iso(art.edited_at),
        'manual': art.model == MANUAL_MODEL,
        'prompt_id': art.prompt_id,
        'model': art.model,
        'generated_at': _iso(art.generated_at),
        'cached': cached,
        'stale': stale,
        'auto_refresh': auto_refresh_state(room, art),
    }


def auto_refresh_state(room: WarRoom, art: AiArtifact | None) -> str:
    """What the tab tells the analyst about automatic regeneration."""
    if room.status == 'closed':
        return 'off_closed'
    if art is None:
        return 'off_never_generated'
    if art.is_edited:
        return 'paused_edited'
    return 'active'


# --------------------------------------------------------------- generation

def _section_text(value: Any, joiner: str = '\n') -> str:
    """A section is a Markdown STRING in the contract, but small models hand
    back arrays for bullet sections — one bullet per item (paragraphs for
    the prose sections); an empty array is an empty section."""
    if value is None:
        return ''
    if isinstance(value, dict):
        value = [f'{k}: {v}' for k, v in value.items()]
    if isinstance(value, (list, tuple)):
        items = [str(x).strip() for x in value if str(x or '').strip()]
        if joiner == '\n':
            items = [x if re.match(r'^\s*(?:[-*+]|\d+[.)])\s', x) else '- ' + x
                     for x in items]
        return joiner.join(items)
    return str(value).strip()


def _parse_response(raw: str) -> dict[str, str]:
    """Extract and validate the JSON object. RAISES on failure — a reply that
    is not the contract is never persisted."""
    cleaned = re.sub(r'```(?:json)?\s*', '', raw or '').strip().rstrip('`').strip()
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if not match:
        raise RoomSummaryError('AI backend returned no JSON object')
    try:
        obj = json.loads(match.group())
    except json.JSONDecodeError as exc:
        raise RoomSummaryError(f'AI backend returned invalid JSON: {exc}')
    if not isinstance(obj, dict):
        raise RoomSummaryError('AI backend returned a JSON value that is not an object')
    out = {}
    for key, _ in SECTIONS:
        out[key] = _section_text(obj.get(key), '\n\n' if key in _PARAGRAPH_SECTIONS else '\n')
    if not out['situation']:
        raise RoomSummaryError('AI backend returned an empty situation section')
    return out


def generate_room_summary(room_id: int, *, force: bool = False) -> dict[str, Any]:
    """Generate (or return the cached) operational summary for one room."""
    room = db.session.get(WarRoom, room_id)
    if room is None:
        raise RoomSummaryError(f'War room #{room_id} not found')

    client: OpenAIClient | None = build_default_client(
        feature=FEATURE_KEY, timeout=180.0, default_max_tokens=ROOM_SUMMARY_MAX_TOKENS)
    if client is None:
        raise RoomSummaryError(
            'AI backend is not configured. Enable it in Manage → Settings → AI.')

    system_prompt = _load_system_prompt()
    payload = build_room_summary_payload(room)
    input_hash = _compute_input_hash(payload, system_prompt, client.model)

    if not force:
        cached = _find_cache_hit(room_id, input_hash)
        if cached is not None:
            log.info('room_summary: cache hit (room=%s, artifact=%s)', room_id, cached.id)
            return artifact_to_result(room, cached, cached=True, stale=False)

    user_prompt = ('Write the operational summary for the war room above. Output ONLY '
                   'the JSON object — no prose, no markdown fences.')

    def _ask(prompt: str):
        try:
            resp = client.chat([
                {'role': 'system',
                 'content': system_prompt + '\n\n' + json.dumps(payload, indent=2, default=str)},
                {'role': 'user', 'content': prompt},
            ], max_tokens=ROOM_SUMMARY_MAX_TOKENS)
        except AIClientError as exc:
            log.error('room_summary: AI call failed — %s', exc)
            raise RoomSummaryError(str(exc)) from exc
        finish = (resp.get('choices') or [{}])[0].get('finish_reason')
        return resp, (OpenAIClient.extract_content(resp) or '').strip(), finish

    resp, raw, finish = _ask(user_prompt)
    if not raw and finish == 'length':
        # The whole budget went to the thinking step. One retry asking for
        # the answer first; the cap stays — the instruction is what moves a
        # reasoning model.
        log.warning('room_summary: empty reply at finish_reason=length (room=%s, usage=%s); '
                    'retrying with a compact instruction', room_id, json.dumps(resp.get('usage')))
        resp, raw, finish = _ask(user_prompt + COMPACT_RETRY_SUFFIX)
    if not raw:
        if finish == 'length':
            raise RoomSummaryError(
                'AI backend exhausted its output budget before answering (finish_reason=length, '
                'twice): the model spent the whole budget reasoning. Point the room summary\'s '
                'Settings override at a non-reasoning model.')
        raise RoomSummaryError(f'AI backend returned an empty response (finish_reason={finish})')

    sections = _parse_response(raw)
    stored = dict(sections)
    stored['esf'] = payload['esf']
    stored['esf_list'] = payload['esf_list']
    stored['stats'] = payload['stats']
    stored['truncated'] = finish == 'length'

    art = AiArtifact(
        anchor_type=ANCHOR_TYPE,
        anchor_id=room_id,
        kind=KIND,
        prompt_id=PROMPT_ID,
        model=client.model,
        input_hash=input_hash,
        content=json.dumps(stored, ensure_ascii=False),
        confidence=None,
    )
    db.session.add(art)
    db.session.commit()
    log.info('room_summary: persisted (room=%s, artifact=%s, truncated=%s)',
             room_id, art.id, stored['truncated'])
    return artifact_to_result(room, art, cached=False, stale=False)


# -------------------------------------------------------------- manual edit

def set_manual_edit(room: WarRoom, text: str, user_id: int) -> AiArtifact:
    """Store the analyst's text as the edit on the newest artifact. A room
    with no generated summary yet gets a MANUAL row (model='manual') so the
    analyst can write before an AI backend exists; a later Generate is an
    ordinary regeneration behind the 409 guard."""
    text = (text or '').strip()
    if not text:
        raise RoomSummaryError('Summary text is empty')
    art = get_latest(room.id)
    if art is None:
        empty = {k: '' for k, _ in SECTIONS}
        empty['esf'] = derive_esfs(room_sector_slugs(room))
        empty['esf_list'] = load_esf_map()['list']
        art = AiArtifact(anchor_type=ANCHOR_TYPE, anchor_id=room.id, kind=KIND,
                         prompt_id=MANUAL_MODEL, model=MANUAL_MODEL,
                         input_hash=MANUAL_MODEL,
                         content=json.dumps(empty, ensure_ascii=False),
                         confidence=None)
        db.session.add(art)
        db.session.flush()
    art.edited_content = text
    art.edited_by_id = user_id
    art.edited_at = datetime.utcnow()
    db.session.commit()
    return art


def revert_edit(room: WarRoom) -> AiArtifact:
    art = get_latest(room.id)
    if art is None:
        raise RoomSummaryError('No summary to revert')
    if art.model == MANUAL_MODEL:
        raise RoomSummaryError('This summary was written by hand — there is no AI original to revert to')
    art.edited_content = None
    art.edited_by_id = None
    art.edited_at = None
    db.session.commit()
    return art


# ------------------------------------------------------------- auto refresh

def _job_pending(room_id: int) -> bool:
    rows = (AiJob.query.filter(AiJob.feature == FEATURE_KEY,
                               AiJob.state.in_(('queued', 'running'))).all())
    for j in rows:
        try:
            if int((json.loads(j.params or '{}') or {}).get('room_id', -1)) == int(room_id):
                return True
        except (TypeError, ValueError):
            continue
    return False


def auto_refresh(room: WarRoom, actor_id: int | None, reason: str) -> str | None:
    """Event hook (post-commit, fail-soft): queue a regeneration when the
    room already has a summary, nobody has edited it, the room is not closed
    and no job is pending. Returns the task id or None (the reason why not
    is logged at debug level; a hook must never raise into its caller)."""
    try:
        if room is None or room.status == 'closed':
            return None
        art = get_latest(room.id)
        if art is None or art.is_edited:
            return None
        if _job_pending(room.id):
            return None
        user_id = actor_id or room.created_by
        if user_id is None:
            user_id = (User.query.with_entities(User.id).order_by(User.id).first() or [None])[0]
        if user_id is None:
            return None
        from app.iris_engine.ai.ai_jobs import enqueue_ai_job
        job = enqueue_ai_job(feature=FEATURE_KEY, case_id=None, user_id=int(user_id),
                             params={'room_id': room.id, 'force': False, 'reason': reason})
        log.info('room_summary: auto-refresh queued (room=%s, reason=%s, task=%s)',
                 room.id, reason, job.task_id)
        return job.task_id
    except Exception:  # noqa: BLE001 — a hook never breaks the write it follows
        log.exception('room_summary: auto-refresh hook failed (room=%s, reason=%s)',
                      getattr(room, 'id', None), reason)
        return None

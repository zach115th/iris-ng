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

"""AI SitRep draft (iris-ng v2, Phase 6).

Drafts a four-section situation report for a war room from: the room's own
summary, the attached cases (their latest CACHED executive summaries), and
the room stream since the last published SitRep. The draft PRE-FILLS the
SitRep editor — the analyst reviews, edits, and publishes; AI never
publishes anything.

Deliberate deviations from the earlier design sketch, both documented:

  - The map stage uses the latest cached case_summary artifact per attached
    case (or a compact server-built digest when none exists) instead of
    force-regenerating summaries: a full 5-specialist regeneration costs
    75-100s per case on cloud backends and would make a pre-fill draft
    unusable for a multi-case room. Regenerate-in-map is a flagged v2 item.
  - No manual-override machinery on the artifact: the SitRep EDITOR is the
    override — the analyst's version is saved as the SitRep row itself, so
    there is no artifact edit to orphan and no 409 guard to need. The
    artifact is a pure input-hash cache (AiArtifact anchor_type='war_room').

Load-bearing rules honoured:
  - every count the model can cite is computed server-side (stats block);
  - a failed or unparseable AI call is NEVER persisted (raise instead);
  - nothing wall-clock-derived lands in the hashed payload — the
    "since last published" window derives from stored rows (published_at),
    and the no-publish fallback is a fixed item cap, not a time window.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any

from sqlalchemy import desc

from app import db
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import OpenAIClient
from app.iris_engine.ai.openai_client import build_default_client
from app.models.cases import Cases
from app.models.models import AiArtifact
from app.models.models import CaseAiArtifact
from app.models.models import SitRep
from app.models.models import UserActivity
from app.models.models import WarRoom
from app.models.models import WarRoomCaseLink
from app.models.models import WarRoomMessage

log = logging.getLogger(__name__)

PROMPT_ID = 'SitrepDraftSystemPrompt-v1'
FEATURE_KEY = 'sitrep_draft'
KIND = 'sitrep_draft'
ANCHOR_TYPE = 'war_room'

_PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), '..', '..', 'resources', 'ai_prompts',
    'sitrep_draft.md')

# Stream items included when no SitRep was ever published — a fixed cap on
# row-derived data, NOT a time window (a time window would fold wall-clock
# into the input hash and the cache would never hit).
_FALLBACK_ITEM_CAP = 60
_ACTIVITY_CAP = 80
_SUMMARY_CHAR_CAP = 6000


class SitrepDraftError(Exception):
    """Raised when the draft cannot run or the model output is unusable —
    never persisted; the endpoint renders it as a transient error."""


def _load_system_prompt() -> str:
    with open(_PROMPT_PATH, encoding='utf-8') as fh:
        return fh.read()


def _latest_case_summary(case_id: int) -> str | None:
    art = (CaseAiArtifact.query
           .filter(CaseAiArtifact.case_id == case_id,
                   CaseAiArtifact.kind == 'case_summary')
           .order_by(CaseAiArtifact.generated_at.desc())
           .first())
    if art is None:
        return None
    return (art.display_content or '')[:_SUMMARY_CHAR_CAP]


def build_sitrep_payload(room: WarRoom) -> dict[str, Any]:
    """Assemble the prompt payload purely from stored rows."""
    case_ids = [r.case_id for r in
                WarRoomCaseLink.query.filter_by(room_id=room.id).all()]
    cases = (Cases.query.filter(Cases.case_id.in_(case_ids)).all()
             if case_ids else [])

    last_pub = (SitRep.query
                .filter(SitRep.room_id == room.id,
                        SitRep.status == 'published')
                .order_by(desc(SitRep.published_at))
                .first())

    msg_q = WarRoomMessage.query.filter_by(room_id=room.id)
    act_q = (UserActivity.query
             .filter(UserActivity.case_id.in_(case_ids),
                     UserActivity.display_in_ui.is_(True))
             if case_ids else None)
    if last_pub is not None and last_pub.published_at is not None:
        msg_q = msg_q.filter(WarRoomMessage.created_at > last_pub.published_at)
        if act_q is not None:
            act_q = act_q.filter(
                UserActivity.activity_date > last_pub.published_at)
        msgs = msg_q.order_by(desc(WarRoomMessage.id)).limit(_ACTIVITY_CAP).all()
        acts = (act_q.order_by(desc(UserActivity.activity_date))
                .limit(_ACTIVITY_CAP).all()) if act_q is not None else []
    else:
        msgs = (msg_q.order_by(desc(WarRoomMessage.id))
                .limit(_FALLBACK_ITEM_CAP).all())
        acts = (act_q.order_by(desc(UserActivity.activity_date))
                .limit(_FALLBACK_ITEM_CAP).all()) if act_q is not None else []

    case_entries = []
    summaries_available = 0
    for c in cases:
        summary = _latest_case_summary(c.case_id)
        if summary:
            summaries_available += 1
        case_entries.append({
            'case_id': c.case_id,
            'name': c.name,
            'client': c.client.name if c.client else None,
            'classification': (c.classification.name
                               if c.classification else None),
            'severity': c.severity.severity_name if c.severity else None,
            'open_date': c.open_date.isoformat() if c.open_date else None,
            'closed': c.close_date is not None,
            'summary': summary,
        })

    published_count = SitRep.query.filter(
        SitRep.room_id == room.id, SitRep.status == 'published').count()

    return {
        'room': {
            'name': room.name,
            'description': room.description,
            'summary': room.summary,
            'campaign_tag': room.campaign_tag,
        },
        'stats': {
            'attached_cases': len(case_entries),
            'cases_with_summary': summaries_available,
            'open_cases': sum(1 for e in case_entries if not e['closed']),
            'closed_cases': sum(1 for e in case_entries if e['closed']),
            'published_sitreps': published_count,
            'chat_messages_in_window': len(msgs),
            'case_activities_in_window': len(acts),
        },
        'cases': case_entries,
        'recent_activity': {
            'messages': [{
                'user': m.user.name if m.user else 'deleted user',
                'at': m.created_at.isoformat() if m.created_at else None,
                'content': (m.content or '')[:600],
            } for m in msgs],
            'case_activity': [{
                'case_id': a.case_id,
                'at': a.activity_date.isoformat() if a.activity_date else None,
                'description': (a.activity_desc or '')[:400],
            } for a in acts],
        },
        'last_published_sitrep': ({
            'title': last_pub.title,
            'published_at': (last_pub.published_at.isoformat()
                             if last_pub.published_at else None),
        } if last_pub is not None else None),
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


def get_latest_draft(room_id: int) -> AiArtifact | None:
    return (AiArtifact.query
            .filter(AiArtifact.anchor_type == ANCHOR_TYPE,
                    AiArtifact.anchor_id == room_id,
                    AiArtifact.kind == KIND)
            .order_by(AiArtifact.generated_at.desc())
            .first())


def _find_cache_hit(room_id: int, input_hash: str) -> AiArtifact | None:
    return (AiArtifact.query
            .filter(AiArtifact.anchor_type == ANCHOR_TYPE,
                    AiArtifact.anchor_id == room_id,
                    AiArtifact.kind == KIND,
                    AiArtifact.input_hash == input_hash)
            .order_by(AiArtifact.generated_at.desc())
            .first())


def _compose_content(sections: dict[str, str]) -> str:
    """The editor holds one markdown body — compose the four sections."""
    parts = ['## Situation', sections['situation']]
    if sections['actions_taken']:
        parts += ['', '## Actions taken', sections['actions_taken']]
    if sections['decisions_needed']:
        parts += ['', '## Decisions needed', sections['decisions_needed']]
    if sections['next_steps']:
        parts += ['', '## Next steps', sections['next_steps']]
    return '\n'.join(parts)


def artifact_to_result(art: AiArtifact, *, cached: bool) -> dict[str, Any]:
    try:
        obj = json.loads(art.content)
    except (TypeError, ValueError):
        raise SitrepDraftError('Stored draft is unreadable — regenerate')
    return {
        'title': obj.get('title', 'SitRep draft'),
        'content': _compose_content(obj),
        'sections': obj,
        'prompt_id': art.prompt_id,
        'model': art.model,
        'room_id': art.anchor_id,
        'cached': cached,
        'generated_at': (art.generated_at.isoformat()
                         if art.generated_at else None),
        'artifact_id': art.id,
    }


def _parse_response(raw: str) -> dict[str, Any]:
    """Extract and validate the JSON object. RAISES on failure — an
    unparseable response must never be persisted."""
    cleaned = re.sub(r'```(?:json)?\s*', '', raw or '').strip().rstrip('`').strip()
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if not match:
        raise SitrepDraftError('AI backend returned no JSON object')
    try:
        obj = json.loads(match.group())
    except json.JSONDecodeError as exc:
        raise SitrepDraftError(f'AI backend returned invalid JSON: {exc}')

    situation = str(obj.get('situation', '')).strip()
    if not situation:
        raise SitrepDraftError('AI backend returned an empty situation section')
    return {
        'title': (str(obj.get('title', '')).strip() or 'SitRep draft')[:80],
        'situation': situation,
        'actions_taken': str(obj.get('actions_taken', '')).strip(),
        'decisions_needed': str(obj.get('decisions_needed', '')).strip(),
        'next_steps': str(obj.get('next_steps', '')).strip(),
    }


def generate_sitrep_draft(room_id: int, *, force: bool = False) -> dict[str, Any]:
    """Generate (or return cached) a SitRep draft for one room."""
    room = db.session.get(WarRoom, room_id)
    if room is None:
        raise SitrepDraftError(f'War room #{room_id} not found')

    client: OpenAIClient | None = build_default_client(
        feature=FEATURE_KEY, timeout=180.0, default_max_tokens=2500)
    if client is None:
        raise SitrepDraftError(
            'AI backend is not configured. Enable it in Manage → Settings → AI.')

    system_prompt = _load_system_prompt()
    payload = build_sitrep_payload(room)
    input_hash = _compute_input_hash(payload, system_prompt, client.model)

    if not force:
        cached = _find_cache_hit(room_id, input_hash)
        if cached is not None:
            log.info('sitrep_draft: cache hit (room=%s, artifact=%s)',
                     room_id, cached.id)
            return artifact_to_result(cached, cached=True)

    messages = [
        {'role': 'system',
         'content': system_prompt + '\n\n' + json.dumps(payload, indent=2,
                                                        default=str)},
        {'role': 'user',
         'content': 'Draft the SitRep for the war room above. Output ONLY '
                    'the JSON object — no prose, no markdown fences.'},
    ]

    try:
        resp = client.chat(messages, max_tokens=2500)
        raw = OpenAIClient.extract_content(resp)
    except AIClientError as exc:
        log.error('sitrep_draft: AI call failed — %s', exc)
        raise SitrepDraftError(str(exc))

    result = _parse_response(raw)

    art = AiArtifact(
        anchor_type=ANCHOR_TYPE,
        anchor_id=room_id,
        kind=KIND,
        prompt_id=PROMPT_ID,
        model=client.model,
        input_hash=input_hash,
        content=json.dumps(result, ensure_ascii=False),
        confidence=None,
    )
    db.session.add(art)
    db.session.commit()
    log.info('sitrep_draft: persisted (room=%s, artifact=%s)', room_id, art.id)

    return artifact_to_result(art, cached=False)

#  IRIS Source Code
#
#  Tier-1 single-event AI analysis. Triggered when an analyst clicks the
#  body of a timeline event card; produces a short focused interpretation
#  in a side drawer.
#
#  Cached per (case_id, event_id) in case_ai_artifact using
#  kind = 'event_analysis:<event_id>' so the lookup is trivial without
#  needing a new column.

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app import app
from app import db
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client
from app.models.cases import Cases
from app.models.cases import CasesEvent
from app.models.models import CaseAiArtifact
from app.models.models import CaseAssets
from app.models.models import Ioc


EVENT_ANALYSIS_KIND_PREFIX = "event_analysis:"
EVENT_ANALYSIS_PROMPT_ID = "EventAnalysisSystemPrompt-v1"

PROMPT_PATH = Path(__file__).parent.parent.parent / "resources" / "ai_prompts" / "event_analysis.md"


class EventAnalysisError(Exception):
    """Raised when single-event analysis can't proceed."""


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[:limit] + " […]"


def _kind_for_event(event_id: int) -> str:
    return f"{EVENT_ANALYSIS_KIND_PREFIX}{event_id}"


def build_event_payload(case: Cases, event: CasesEvent) -> dict[str, Any]:
    """Two-section payload: the target event in detail + a trimmed case context."""
    case_id = case.case_id

    target = {
        "id": event.event_id,
        "date": event.event_date.isoformat() if event.event_date else None,
        "title": event.event_title,
        "tags": event.event_tags or None,
        "content": _truncate(event.event_content, 4000),
        "source": _truncate(event.event_source, 400),
        "is_flagged": bool(event.event_is_flagged),
        "in_summary": bool(event.event_in_summary),
    }

    other_events = (
        CasesEvent.query
        .filter(CasesEvent.case_id == case_id, CasesEvent.event_id != event.event_id)
        .order_by(CasesEvent.event_date.asc())
        .limit(80)
        .all()
    )
    timeline_brief = [
        {
            "date": e.event_date.isoformat() if e.event_date else None,
            "title": e.event_title,
            "tags": e.event_tags or None,
        }
        for e in other_events
    ]

    iocs = [
        {
            "value": i.ioc_value,
            "type": getattr(i.ioc_type, "type_name", None) if getattr(i, "ioc_type", None) else None,
            "tlp": getattr(i.tlp, "tlp_name", None) if getattr(i, "tlp", None) else None,
            "description": _truncate(i.ioc_description, 300),
            "tags": i.ioc_tags or None,
        }
        for i in Ioc.query.filter(Ioc.case_id == case_id).all()
    ]

    assets = [
        {
            "name": a.asset_name,
            "type": getattr(a.asset_type, "asset_name", None) if getattr(a, "asset_type", None) else None,
            "ip": a.asset_ip or None,
            "domain": a.asset_domain or None,
            "compromise_status_id": a.asset_compromise_status_id,
        }
        for a in CaseAssets.query.filter(CaseAssets.case_id == case_id).all()
    ]

    return {
        "target_event": target,
        "case_context": {
            "case": {
                "id": case.case_id,
                "name": case.name,
                "soc_id": case.soc_id,
            },
            "other_timeline_events": timeline_brief,
            "iocs": iocs,
            "assets": assets,
        },
    }


def compute_input_hash(payload: dict[str, Any], system_prompt: str, model: str) -> str:
    canon = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    h = hashlib.md5()
    h.update(model.encode("utf-8"))
    h.update(b"\n")
    h.update(system_prompt.encode("utf-8"))
    h.update(b"\n")
    h.update(canon.encode("utf-8"))
    return h.hexdigest()


def get_cached_event_analysis(case_id: int, event_id: int) -> CaseAiArtifact | None:
    return (
        CaseAiArtifact.query
        .filter(
            CaseAiArtifact.case_id == case_id,
            CaseAiArtifact.kind == _kind_for_event(event_id)
        )
        .order_by(CaseAiArtifact.generated_at.desc())
        .first()
    )


def find_cache_hit(case_id: int, event_id: int, input_hash: str) -> CaseAiArtifact | None:
    return (
        CaseAiArtifact.query
        .filter(
            CaseAiArtifact.case_id == case_id,
            CaseAiArtifact.kind == _kind_for_event(event_id),
            CaseAiArtifact.input_hash == input_hash
        )
        .order_by(CaseAiArtifact.generated_at.desc())
        .first()
    )


def generate_event_analysis(
    case_id: int,
    event_id: int,
    *,
    force: bool = False
) -> CaseAiArtifact:
    case = Cases.query.filter(Cases.case_id == case_id).first()
    if case is None:
        raise EventAnalysisError(f"Case #{case_id} not found")

    event = CasesEvent.query.filter(
        CasesEvent.case_id == case_id, CasesEvent.event_id == event_id
    ).first()
    if event is None:
        raise EventAnalysisError(f"Event #{event_id} not found in case #{case_id}")

    client = build_default_client(timeout=120.0, default_max_tokens=2000)
    if client is None:
        raise EventAnalysisError(
            "AI backend is not configured (set AI_BACKEND_URL and AI_BACKEND_MODEL)"
        )

    system_prompt = load_system_prompt()
    payload = build_event_payload(case, event)
    input_hash = compute_input_hash(payload, system_prompt, client.model)

    if not force:
        cached = find_cache_hit(case_id, event_id, input_hash)
        if cached is not None:
            app.logger.info(
                f"Case #{case_id} event #{event_id}: returning cached analysis "
                f"(generated_at={cached.generated_at.isoformat()})"
            )
            return cached

    user_prompt = (
        "Analyze the target_event using the case_context for cross-reference.\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
    )

    app.logger.info(
        f"Case #{case_id} event #{event_id}: generating fresh analysis "
        f"(model={client.model})"
    )

    try:
        response = client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])
    except AIClientError as exc:
        raise EventAnalysisError(f"AI backend call failed: {exc}") from exc

    content = client.extract_content(response).strip()
    if not content:
        raise EventAnalysisError(
            "AI backend returned an empty response "
            f"(finish_reason={response.get('choices', [{}])[0].get('finish_reason')})"
        )

    artifact = CaseAiArtifact(
        case_id=case_id,
        kind=_kind_for_event(event_id),
        prompt_id=EVENT_ANALYSIS_PROMPT_ID,
        model=client.model,
        input_hash=input_hash,
        content=content,
        confidence=None
    )
    db.session.add(artifact)
    db.session.commit()

    app.logger.info(
        f"Case #{case_id} event #{event_id}: analysis persisted "
        f"(artifact_id={artifact.id}, len={len(content)} chars)"
    )

    return artifact

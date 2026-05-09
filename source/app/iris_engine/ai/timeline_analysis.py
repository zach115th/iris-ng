#  IRIS Source Code
#
#  Tier-1 timeline-focused technical analysis. Single-shot LLM call producing
#  a structured analyst-grade narrative of the case from the timeline's
#  perspective: what is evidenced, what is suspected, where the gaps are,
#  and what to investigate next.
#
#  Distinct from the lightweight executive case summary — that one is for
#  leadership handoff (CaseSummarizationSystemPrompt). This one is for the
#  responding analyst (CaseAnalysisSystemPrompt).

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


TIMELINE_ANALYSIS_KIND = "timeline_analysis"
TIMELINE_ANALYSIS_PROMPT_ID = "TimelineNarrativeSystemPrompt-v3"

PROMPT_PATH = Path(__file__).parent.parent.parent / "resources" / "ai_prompts" / "timeline_analysis.md"


class TimelineAnalysisError(Exception):
    """Raised when timeline analysis can't proceed."""


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[:limit] + " […]"


def build_timeline_payload(case: Cases) -> dict[str, Any]:
    """Timeline-centric payload — strictly the master timeline events plus
    case metadata. Per user design rule (2026-05-09): the timeline analysis
    panel must reason ONLY from what's on the timeline, not the broader IOC
    or asset catalog. Observables referenced in event content/title/tags
    are still available to the model — they're just not enumerated as a
    separate top-level section that could pull in IOCs the analyst hasn't
    yet linked to a timeline event.
    """
    case_id = case.case_id

    timeline_q = (
        CasesEvent.query
        .filter(CasesEvent.case_id == case_id)
        .order_by(CasesEvent.event_date.asc())
        .limit(150)
        .all()
    )
    timeline = [
        {
            "date": e.event_date.isoformat() if e.event_date else None,
            "title": e.event_title,
            "tags": e.event_tags or None,
            "content": _truncate(e.event_content, 2000),
            "source": _truncate(e.event_source, 300),
            "is_flagged": bool(e.event_is_flagged),
            "in_summary": bool(e.event_in_summary),
        }
        for e in timeline_q
    ]

    return {
        "case": {
            "id": case.case_id,
            "name": case.name,
            "soc_id": case.soc_id,
            "open_date": case.open_date.isoformat() if case.open_date else None,
            "description": _truncate(case.description, 1500),
        },
        "counts": {
            "timeline_events": len(timeline),
        },
        "timeline": timeline,
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


def get_cached_analysis(case_id: int) -> CaseAiArtifact | None:
    return (
        CaseAiArtifact.query
        .filter(
            CaseAiArtifact.case_id == case_id,
            CaseAiArtifact.kind == TIMELINE_ANALYSIS_KIND
        )
        .order_by(CaseAiArtifact.generated_at.desc())
        .first()
    )


def find_cache_hit(case_id: int, input_hash: str) -> CaseAiArtifact | None:
    return (
        CaseAiArtifact.query
        .filter(
            CaseAiArtifact.case_id == case_id,
            CaseAiArtifact.kind == TIMELINE_ANALYSIS_KIND,
            CaseAiArtifact.input_hash == input_hash
        )
        .order_by(CaseAiArtifact.generated_at.desc())
        .first()
    )


def generate_timeline_analysis(case_id: int, *, force: bool = False) -> CaseAiArtifact:
    case = Cases.query.filter(Cases.case_id == case_id).first()
    if case is None:
        raise TimelineAnalysisError(f"Case #{case_id} not found")

    client = build_default_client(timeout=240.0, default_max_tokens=6000)
    if client is None:
        raise TimelineAnalysisError(
            "AI backend is not configured (set AI_BACKEND_URL and AI_BACKEND_MODEL)"
        )

    system_prompt = load_system_prompt()
    payload = build_timeline_payload(case)
    input_hash = compute_input_hash(payload, system_prompt, client.model)

    if not force:
        cached = find_cache_hit(case_id, input_hash)
        if cached is not None:
            app.logger.info(
                f"Case #{case_id}: returning cached timeline analysis "
                f"(generated_at={cached.generated_at.isoformat()}, model={cached.model})"
            )
            return cached

    user_prompt = (
        "Write the narrative analysis of the timeline below. Three sections:"
        " what it tells us, what's still uncertain, where to dig next."
        " Prose, no tables, no TLP, no risk score.\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
    )

    app.logger.info(
        f"Case #{case_id}: generating fresh timeline analysis "
        f"(model={client.model}, payload counts={payload['counts']})"
    )

    try:
        response = client.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
    except AIClientError as exc:
        raise TimelineAnalysisError(f"AI backend call failed: {exc}") from exc

    content = client.extract_content(response).strip()
    if not content:
        raise TimelineAnalysisError(
            f"AI backend returned an empty response (finish_reason={response.get('choices', [{}])[0].get('finish_reason')})"
        )

    artifact = CaseAiArtifact(
        case_id=case_id,
        kind=TIMELINE_ANALYSIS_KIND,
        prompt_id=TIMELINE_ANALYSIS_PROMPT_ID,
        model=client.model,
        input_hash=input_hash,
        content=content,
        confidence=None
    )
    db.session.add(artifact)
    db.session.commit()

    app.logger.info(
        f"Case #{case_id}: timeline analysis persisted "
        f"(artifact_id={artifact.id}, len={len(content)} chars, "
        f"usage={response.get('usage')})"
    )

    return artifact

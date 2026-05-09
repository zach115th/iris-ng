"""Inline AI explanation for a single working-timeline event.

Triggered when the analyst clicks ✨ Explain on a card in the
right-side working timeline panel. Returns 3 short paragraphs
(detection / interpretation / triage hint) so the analyst can decide
promote vs reject without flipping out of the panel.

Cached per (case_id, working_event_id) in case_ai_artifact using
kind = 'working_event_explain:<id>'. Re-running with identical inputs
short-circuits to the cached row.

Differs from event_analysis.py (which does a 4-section drawer for
already-promoted events): this is a tighter, decision-support read
designed to fit inline under Promote/Reject without scrolling.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app import app
from app import db
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client
from app.models.cases import CaseWorkingEvent
from app.models.models import CaseAiArtifact


WORKING_EXPLAIN_KIND_PREFIX = "working_event_explain:"
WORKING_EXPLAIN_PROMPT_ID = "WorkingEventExplainerSystemPrompt-v1"

PROMPT_PATH = Path(__file__).parent.parent.parent / "resources" / "ai_prompts" / "working_event_explainer.md"


class WorkingEventExplainerError(Exception):
    """Raised when the explainer can't proceed."""


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _kind_for(working_id: int) -> str:
    return f"{WORKING_EXPLAIN_KIND_PREFIX}{working_id}"


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[:limit] + " […]"


def build_payload(ev: CaseWorkingEvent) -> dict[str, Any]:
    """Compact payload — just what the analyst sees on the card, plus
    the structured per-rule metadata from event_raw so the model can
    talk about *what* the rule detects rather than just the title."""
    raw = ev.event_raw or {}
    return {
        "headline": ev.event_title,
        "severity": ev.severity,
        "source": ev.source,
        "host": ev.event_source_host,
        "external_id": ev.external_id,
        "tags": ev.event_tags,
        "mitre_techniques": ev.mitre_techniques,
        "evtx_file": raw.get("evtx_file"),
        "windows_provider": raw.get("provider"),
        "matched_rules": raw.get("matched_rules") or [],
        "evidence": _truncate(ev.event_description, 4000),
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


def get_cached(case_id: int, working_id: int) -> CaseAiArtifact | None:
    return (
        CaseAiArtifact.query
        .filter(
            CaseAiArtifact.case_id == case_id,
            CaseAiArtifact.kind == _kind_for(working_id)
        )
        .order_by(CaseAiArtifact.generated_at.desc())
        .first()
    )


def find_cache_hit(case_id: int, working_id: int, input_hash: str) -> CaseAiArtifact | None:
    return (
        CaseAiArtifact.query
        .filter(
            CaseAiArtifact.case_id == case_id,
            CaseAiArtifact.kind == _kind_for(working_id),
            CaseAiArtifact.input_hash == input_hash
        )
        .order_by(CaseAiArtifact.generated_at.desc())
        .first()
    )


def explain_working_event(
    case_id: int,
    working_id: int,
    *,
    force: bool = False,
) -> CaseAiArtifact:
    ev = CaseWorkingEvent.query.filter(
        CaseWorkingEvent.case_id == case_id,
        CaseWorkingEvent.id == working_id,
    ).first()
    if ev is None:
        raise WorkingEventExplainerError(
            f"Working event #{working_id} not found in case #{case_id}"
        )

    client = build_default_client(timeout=90.0, default_max_tokens=900)
    if client is None:
        raise WorkingEventExplainerError(
            "AI backend is not configured (set AI_BACKEND_URL and AI_BACKEND_MODEL)"
        )

    system_prompt = load_system_prompt()
    payload = build_payload(ev)
    input_hash = compute_input_hash(payload, system_prompt, client.model)

    if not force:
        cached = find_cache_hit(case_id, working_id, input_hash)
        if cached is not None:
            app.logger.info(
                f"Case #{case_id} working #{working_id}: returning cached "
                f"explanation (generated_at={cached.generated_at.isoformat()})"
            )
            return cached

    user_prompt = (
        "Explain this tool-ingested working-timeline event for an analyst "
        "who is about to decide promote-to-real-event vs reject-as-noise. "
        "Follow the three-paragraph format from the system prompt exactly.\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
    )

    app.logger.info(
        f"Case #{case_id} working #{working_id}: generating fresh explanation "
        f"(model={client.model})"
    )

    try:
        response = client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])
    except AIClientError as exc:
        raise WorkingEventExplainerError(f"AI backend call failed: {exc}") from exc

    content = client.extract_content(response).strip()
    if not content:
        raise WorkingEventExplainerError(
            "AI backend returned an empty response "
            f"(finish_reason={response.get('choices', [{}])[0].get('finish_reason')})"
        )

    artifact = CaseAiArtifact(
        case_id=case_id,
        kind=_kind_for(working_id),
        prompt_id=WORKING_EXPLAIN_PROMPT_ID,
        model=client.model,
        input_hash=input_hash,
        content=content,
        confidence=None
    )
    db.session.add(artifact)
    db.session.commit()

    app.logger.info(
        f"Case #{case_id} working #{working_id}: explanation persisted "
        f"(artifact_id={artifact.id}, len={len(content)} chars)"
    )

    return artifact

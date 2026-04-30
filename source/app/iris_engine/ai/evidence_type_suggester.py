#  IRIS Source Code
#
#  Tier-1 evidence-type suggester. Triggered by the `✨ Suggest type` pill
#  in the Register Evidence modal. Takes file metadata (filename, size,
#  hash, first 4 KB magic-bytes hex) + an optional analyst description
#  and returns a single best-fitting EvidenceTypes catalog entry with
#  confidence + one-line reason.
#
#  Stateless: not persisted in case_ai_artifact. Same input → same output
#  at temperature=0.0; the analyst either accepts the suggestion (which
#  selects the dropdown option) or dismisses. No round-trip through
#  artifact storage.
#
#  Server-side validation:
#  - The model returns a `type_id`; the orchestrator confirms the id
#    exists in the EvidenceTypes catalog and replaces the model's
#    `type_name` with the canonical DB name (so a typo or stale name
#    can't slip through to the UI).
#  - Confidence ≥ 0.0 ≤ 1.0; values outside dropped.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app import app
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client
from app.models.models import EvidenceTypes


EVIDENCE_TYPE_SUGGESTER_PROMPT_ID = "EvidenceTypeSuggesterSystemPrompt-v1"
PROMPT_PATH = Path(__file__).parent.parent.parent / "resources" / "ai_prompts" / "evidence_type_suggester.md"

# Cap how much magic-bytes hex we send to the model. 4 KB → 8192 hex chars
# is plenty for filesystem / file-format magic numbers, which all live in
# the first ~256 bytes; we send 4 KB to also catch nested magic in
# wrappers (e.g. zip-of-zips, OOXML core.xml header location).
MAX_MAGIC_HEX = 8192  # 4 KB worth of hex


class EvidenceTypeSuggesterError(Exception):
    """Raised when evidence-type suggestion can't proceed."""


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[:limit] + " […]"


def _extract_json_block(content: str) -> str:
    """Strip optional ```json … ``` fences before parsing."""
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9]*\n?", "", stripped)
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


def _build_catalog() -> list[dict[str, Any]]:
    """Snapshot the EvidenceTypes table for the prompt.

    Pass the catalog as a JSON list in the user message rather than baking
    it into the system prompt — the catalog can grow (admin-managed) and
    we want suggestions to track the live DB state without prompt edits.
    """
    rows = EvidenceTypes.query.order_by(EvidenceTypes.id).all()
    return [
        {
            "id": int(r.id),
            "name": r.name,
            "description": r.description or "",
        }
        for r in rows
    ]


def _validate_suggestion(item: Any, catalog: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Coerce the model's response to a known-good catalog entry.

    The orchestrator owns name/description — replace whatever the model
    returned with the canonical DB row to prevent typo / hallucinated
    name slipping through. The model is only authoritative for `id`.
    """
    if not isinstance(item, dict):
        return None
    type_id = item.get("type_id")
    if not isinstance(type_id, int):
        return None
    catalog_by_id = {row["id"]: row for row in catalog}
    matched = catalog_by_id.get(type_id)
    if matched is None:
        return None
    confidence = item.get("confidence")
    if not isinstance(confidence, (int, float)):
        return None
    if confidence < 0.0 or confidence > 1.0:
        return None
    reason = item.get("reason")
    return {
        "type_id": matched["id"],
        "type_name": matched["name"],  # canonical from DB, not the model
        "type_description": matched["description"],
        "confidence": float(confidence),
        "reason": reason if isinstance(reason, str) else None,
    }


def suggest_evidence_type(
    *,
    filename: str,
    size_bytes: int | None = None,
    file_hash: str | None = None,
    magic_hex: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Call the AI backend and return one validated EvidenceTypes suggestion.

    Returns:
        {
          'suggestion': {type_id, type_name, type_description, confidence, reason} | None,
          'model':       str,
          'catalog_size': int,   # how many entries the model picked from
        }
    """
    filename = (filename or "").strip()
    if not filename and not (magic_hex or "").strip():
        raise EvidenceTypeSuggesterError("Need at least a filename or magic bytes to suggest a type")

    client = build_default_client(timeout=60.0, default_max_tokens=600)
    if client is None:
        raise EvidenceTypeSuggesterError(
            "AI backend is not configured (set AI_BACKEND_URL and AI_BACKEND_MODEL "
            "or configure it in Server Settings)"
        )

    catalog = _build_catalog()
    if not catalog:
        raise EvidenceTypeSuggesterError("EvidenceTypes catalog is empty")

    # Trim magic hex to the cap; strip whitespace just in case.
    if magic_hex:
        magic_hex = magic_hex.strip().replace(" ", "").replace("\n", "")
        if len(magic_hex) > MAX_MAGIC_HEX:
            magic_hex = magic_hex[:MAX_MAGIC_HEX]

    system_prompt = load_system_prompt()

    payload = {
        "file": {
            "filename": _truncate(filename, 400),
            "size_bytes": size_bytes,
            "hash": _truncate(file_hash, 256),
            "magic_hex_first_4k": magic_hex,
        },
        "analyst_description": _truncate(description, 4000),
        "catalog": catalog,
    }
    user_prompt = (
        "Pick the single best-fitting `id` from the catalog for the file below.\n\n"
        f"```json\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n```"
    )

    app.logger.info(
        f"EvidenceTypeSuggester: requesting suggestion (model={client.model}, "
        f"filename={filename[:80]!r}, size={size_bytes}, "
        f"magic_hex_chars={len(magic_hex or '')}, catalog_size={len(catalog)})"
    )

    try:
        response = client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])
    except AIClientError as exc:
        raise EvidenceTypeSuggesterError(f"AI backend call failed: {exc}") from exc

    raw = client.extract_content(response).strip()
    if not raw:
        raise EvidenceTypeSuggesterError(
            "AI backend returned an empty response "
            f"(finish_reason={response.get('choices', [{}])[0].get('finish_reason')})"
        )

    try:
        parsed = json.loads(_extract_json_block(raw))
    except json.JSONDecodeError as exc:
        app.logger.warning(f"EvidenceTypeSuggester: model returned non-JSON content: {raw[:300]}")
        raise EvidenceTypeSuggesterError(
            f"AI backend returned non-JSON content (parse error: {exc})"
        ) from exc

    suggestion = _validate_suggestion(parsed, catalog)

    if suggestion is None:
        app.logger.info("EvidenceTypeSuggester: model returned a suggestion that did not validate")
    else:
        app.logger.info(
            f"EvidenceTypeSuggester: returned id={suggestion['type_id']} "
            f"name={suggestion['type_name']!r} conf={suggestion['confidence']}"
        )

    return {
        "suggestion": suggestion,
        "model": client.model,
        "catalog_size": len(catalog),
    }

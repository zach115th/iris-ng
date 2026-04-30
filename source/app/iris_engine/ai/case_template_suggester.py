#  IRIS Source Code
#
#  Tier-1 case-template suggester. Triggered when an analyst opens the
#  "Escalate alert to case" modal — the alert id is read from the modal,
#  the alert's salient fields (title, description, source, severity,
#  classification, tags, attached IOCs, attached assets) are bundled into
#  a payload alongside a snapshot of the live `CaseTemplate` catalog, and
#  the model is asked to pick a single best-fitting template id.
#
#  Stateless: not persisted in case_ai_artifact (the case doesn't exist
#  yet at suggestion time — escalation hasn't happened). Same input →
#  same output at temperature=0.0; the analyst either accepts the
#  suggestion (which auto-selects the dropdown option) or dismisses.
#
#  Server-side validation:
#  - The model returns a `template_id`; the orchestrator confirms the id
#    exists in the CaseTemplate catalog and replaces the model's
#    `template_name` with the canonical DB display_name (so a typo or
#    stale name can't slip through to the UI).
#  - Confidence ≥ 0.0 ≤ 1.0; values outside dropped.
#
#  Catalog snapshot at request time — admin-managed templates are picked
#  up automatically without prompt edits, same pattern as
#  evidence_type_suggester.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app import app
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client
from app.models.alerts import Alert
from app.models.models import CaseTemplate

CASE_TEMPLATE_SUGGESTER_PROMPT_ID = "CaseTemplateSuggesterSystemPrompt-v1"
PROMPT_PATH = Path(__file__).parent.parent.parent / "resources" / "ai_prompts" / "case_template_suggester.md"

# Cap how many alert IOCs / assets we send to the model — keeps the prompt
# under the token budget on busy alerts (some EDR rules attach hundreds of
# IOCs). The first N are usually the ones the analyst is acting on.
MAX_IOCS = 20
MAX_ASSETS = 20

# Per-template description and tags can be long-form prose. Trim each so
# one bloated entry can't push the catalog past the token budget.
MAX_TEMPLATE_DESC_CHARS = 600


class CaseTemplateSuggesterError(Exception):
    """Raised when case-template suggestion can't proceed."""


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
    """Snapshot the CaseTemplate table for the prompt.

    `tags` is JSON; serialize to a compact comma-joined string so the model
    sees them as keyword hints rather than a nested structure.
    """
    rows = CaseTemplate.query.order_by(CaseTemplate.id).all()
    catalog = []
    for r in rows:
        # tags column is JSON — could be a list, a dict, or None depending
        # on how the template was authored.
        if isinstance(r.tags, list):
            tags = ", ".join(str(t) for t in r.tags if t)
        elif isinstance(r.tags, dict):
            tags = ", ".join(f"{k}={v}" for k, v in r.tags.items())
        elif isinstance(r.tags, str):
            tags = r.tags
        else:
            tags = ""
        catalog.append({
            "id": int(r.id),
            "name": r.name or "",
            "display_name": r.display_name or r.name or "",
            "description": _truncate(r.description, MAX_TEMPLATE_DESC_CHARS) or "",
            "classification": r.classification or "",
            "tags": tags,
        })
    return catalog


def _build_alert_payload(alert: Alert) -> dict[str, Any]:
    """Pull the alert fields the model actually uses for classification.

    Skip `alert_source_content` (raw upstream payload — verbose and noisy)
    unless we ever need it; the structured fields IRIS extracts are what
    a human analyst would read.
    """
    severity = getattr(alert.severity, "severity_name", None) if alert.severity else None
    classification = getattr(alert.classification, "name", None) if alert.classification else None
    source_event_time = alert.alert_source_event_time.isoformat() if alert.alert_source_event_time else None

    iocs = []
    for ioc in (alert.iocs or [])[:MAX_IOCS]:
        ioc_type = getattr(getattr(ioc, "ioc_type", None), "type_name", None)
        iocs.append({
            "value": _truncate(ioc.ioc_value, 400),
            "type": ioc_type,
            "description": _truncate(ioc.ioc_description, 300),
        })

    assets = []
    for asset in (alert.assets or [])[:MAX_ASSETS]:
        asset_type = getattr(getattr(asset, "asset_type", None), "asset_name", None)
        assets.append({
            "name": _truncate(asset.asset_name, 200),
            "type": asset_type,
            "description": _truncate(asset.asset_description, 300),
            "domain": _truncate(asset.asset_domain, 200),
            "ip": _truncate(asset.asset_ip, 200),
        })

    return {
        "title": _truncate(alert.alert_title, 600),
        "description": _truncate(alert.alert_description, 4000),
        "source": _truncate(alert.alert_source, 200),
        "severity": severity,
        "classification": classification,
        "tags": _truncate(alert.alert_tags, 600),
        "source_event_time": source_event_time,
        "iocs": iocs,
        "assets": assets,
        "iocs_truncated": len(alert.iocs or []) > MAX_IOCS,
        "assets_truncated": len(alert.assets or []) > MAX_ASSETS,
    }


def _validate_suggestion(item: Any, catalog: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Coerce the model's response to a known-good catalog entry."""
    if not isinstance(item, dict):
        return None
    template_id = item.get("template_id")
    if not isinstance(template_id, int):
        return None
    catalog_by_id = {row["id"]: row for row in catalog}
    matched = catalog_by_id.get(template_id)
    if matched is None:
        return None
    confidence = item.get("confidence")
    if not isinstance(confidence, (int, float)):
        return None
    if confidence < 0.0 or confidence > 1.0:
        return None
    reason = item.get("reason")
    return {
        "template_id": matched["id"],
        "template_name": matched["display_name"],  # canonical from DB
        "template_description": matched["description"],
        "confidence": float(confidence),
        "reason": reason if isinstance(reason, str) else None,
    }


def suggest_case_template(*, alert: Alert) -> dict[str, Any]:
    """Call the AI backend and return one validated CaseTemplate suggestion.

    Returns:
        {
          'suggestion': {template_id, template_name, template_description, confidence, reason} | None,
          'model':       str,
          'catalog_size': int,
        }
    """
    if alert is None:
        raise CaseTemplateSuggesterError("Alert is required")

    client = build_default_client(timeout=60.0, default_max_tokens=600)
    if client is None:
        raise CaseTemplateSuggesterError(
            "AI backend is not configured (set AI_BACKEND_URL and AI_BACKEND_MODEL "
            "or configure it in Server Settings)"
        )

    catalog = _build_catalog()
    if not catalog:
        raise CaseTemplateSuggesterError(
            "Case template catalog is empty — create at least one template under /manage/case-templates"
        )

    system_prompt = load_system_prompt()
    payload = {
        "alert": _build_alert_payload(alert),
        "catalog": catalog,
    }
    user_prompt = (
        "Pick the single best-fitting `id` from the catalog for the alert below.\n\n"
        f"```json\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n```"
    )

    app.logger.info(
        f"CaseTemplateSuggester: requesting suggestion (model={client.model}, "
        f"alert_id={alert.alert_id}, catalog_size={len(catalog)})"
    )

    try:
        response = client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])
    except AIClientError as exc:
        raise CaseTemplateSuggesterError(f"AI backend call failed: {exc}") from exc

    raw = client.extract_content(response).strip()
    if not raw:
        raise CaseTemplateSuggesterError(
            "AI backend returned an empty response "
            f"(finish_reason={response.get('choices', [{}])[0].get('finish_reason')})"
        )

    try:
        parsed = json.loads(_extract_json_block(raw))
    except json.JSONDecodeError as exc:
        app.logger.warning(f"CaseTemplateSuggester: model returned non-JSON content: {raw[:300]}")
        raise CaseTemplateSuggesterError(
            f"AI backend returned non-JSON content (parse error: {exc})"
        ) from exc

    suggestion = _validate_suggestion(parsed, catalog)

    if suggestion is None:
        app.logger.info("CaseTemplateSuggester: model returned a suggestion that did not validate")
    else:
        app.logger.info(
            f"CaseTemplateSuggester: returned id={suggestion['template_id']} "
            f"name={suggestion['template_name']!r} conf={suggestion['confidence']}"
        )

    return {
        "suggestion": suggestion,
        "model": client.model,
        "catalog_size": len(catalog),
    }

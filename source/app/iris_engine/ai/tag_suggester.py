#  IRIS Source Code
#
#  Object-agnostic AI tag suggester.
#
#  Given any case object (IOC, asset, task, case, event), build a context
#  payload from the object's salient fields, ask the configured AI backend
#  for 3-7 MISP-shaped tags, validate each suggestion against the bundled
#  MISP taxonomy + galaxy catalog, and return the surviving suggestions
#  with kind / expanded label / description / reason / confidence.
#
#  Validation rules:
#  - Tag must exist verbatim in `misp_tag_catalog`, OR
#  - Tag's predicate-or-galaxy-value must match a known synonym (galaxies)
#  - Confidence must be a number in [0, 1]
#  - Confidence < 0.5 dropped (matches case-template-suggester / IOC extractor)
#
#  Stateless: not cached. Tags change as analysts add evidence — every click
#  on the "Suggest tags" pill re-asks the model with the latest object state.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app import app
from app.iris_engine import misp_tag_catalog
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client


TAG_SUGGESTER_PROMPT_ID = "TagSuggesterSystemPrompt-v1"
PROMPT_PATH = Path(__file__).parent.parent.parent / "resources" / "ai_prompts" / "tag_suggester.md"

VALID_OBJECT_TYPES = ("ioc", "asset", "task", "case", "event")
DEFAULT_CONFIDENCE_FLOOR = 0.5
MAX_SUGGESTIONS = 7


class TagSuggesterError(Exception):
    """Raised when tag suggestion can't proceed."""


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[:limit] + " […]"


def _extract_json_block(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9]*\n?", "", stripped)
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


# --- Object payload builders ---------------------------------------------

def _ioc_payload(ioc) -> dict[str, Any]:
    ioc_type = getattr(getattr(ioc, "ioc_type", None), "type_name", None)
    tlp = getattr(getattr(ioc, "tlp", None), "tlp_name", None)
    return {
        "kind": "ioc",
        "type": ioc_type,
        "value": _truncate(ioc.ioc_value, 400),
        "description": _truncate(ioc.ioc_description, 4000),
        "tlp": tlp,
        "current_tags": _current_tags_csv(getattr(ioc, "ioc_tags", None)),
    }


def _asset_payload(asset) -> dict[str, Any]:
    asset_type = getattr(getattr(asset, "asset_type", None), "asset_name", None)
    return {
        "kind": "asset",
        "name": _truncate(asset.asset_name, 200),
        "type": asset_type,
        "description": _truncate(asset.asset_description, 4000),
        "ip": _truncate(asset.asset_ip, 200),
        "domain": _truncate(asset.asset_domain, 200),
        # `asset_compromise_status_id` is a bare int FK; resolve via lookup if needed.
        "current_tags": _current_tags_csv(getattr(asset, "asset_tags", None)),
    }


def _task_payload(task) -> dict[str, Any]:
    status = getattr(getattr(task, "status", None), "status_name", None)
    return {
        "kind": "task",
        "title": _truncate(task.task_title, 400),
        "description": _truncate(task.task_description, 4000),
        "status": status,
        "current_tags": _current_tags_csv(getattr(task, "task_tags", None)),
    }


def _case_payload(case) -> dict[str, Any]:
    classification = getattr(getattr(case, "classification", None), "name", None)
    return {
        "kind": "case",
        "name": _truncate(case.name, 400),
        "description": _truncate(case.description, 6000),
        "soc_id": _truncate(case.soc_id, 200),
        "classification": classification,
        "current_tags": _current_tags_csv(getattr(case, "case_tags", None)),
    }


def _event_payload(event) -> dict[str, Any]:
    category = getattr(getattr(event, "category", None), "name", None)
    return {
        "kind": "event",
        "title": _truncate(event.event_title, 400),
        "description": _truncate(event.event_content, 4000),
        "raw": _truncate(event.event_raw, 2000),
        "source": _truncate(event.event_source, 400),
        "category": category,
        "current_tags": _current_tags_csv(getattr(event, "event_tags", None)),
    }


def _current_tags_csv(value) -> list[str]:
    """Most IRIS object models store tags as a CSV string in `<thing>_tags`."""
    if not value:
        return []
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    if isinstance(value, list):
        return [str(t).strip() for t in value if t]
    return []


def _current_tags_objects(value) -> list[str]:
    """A few IRIS objects (assets) carry tags as Tag-model relationships."""
    if not value:
        return []
    out = []
    for t in value:
        title = getattr(t, "tag_title", None) or str(t)
        if title:
            out.append(title)
    return out


# --- Validation ----------------------------------------------------------

def _build_lookups() -> tuple[dict[str, dict], dict[str, dict]]:
    """Return (tags_by_exact, tags_by_synonym_lower).

    Both maps point at the catalog record. Synonyms only exist for galaxy
    records (taxonomies don't carry synonyms).
    """
    catalog = misp_tag_catalog._ensure_catalog()
    by_exact: dict[str, dict] = {}
    by_syn: dict[str, dict] = {}
    for record in catalog:
        tag = record.get("tag")
        if tag:
            by_exact[tag] = record
        for syn in record.get("synonyms") or []:
            if isinstance(syn, str) and syn.strip():
                by_syn.setdefault(syn.strip().lower(), record)
    return by_exact, by_syn


def _validate_suggestion(item: Any, by_exact: dict, by_syn: dict) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    raw_tag = item.get("tag")
    if not isinstance(raw_tag, str) or not raw_tag.strip():
        return None
    raw_tag = raw_tag.strip()

    confidence = item.get("confidence")
    if not isinstance(confidence, (int, float)):
        return None
    confidence = float(confidence)
    if confidence < 0.0 or confidence > 1.0:
        return None
    if confidence < DEFAULT_CONFIDENCE_FLOOR:
        return None

    record = by_exact.get(raw_tag)
    matched_synonym: str | None = None

    # Synonym fallback for galaxy tags. Pull the canonical tag out of the
    # record we'd matched on — synonym entries point at the same catalog
    # record so the canonical `tag` is right there.
    if record is None:
        m = re.match(r'^(misp-galaxy:[^=]+)=("?)(.+?)(\2)$', raw_tag)
        if m:
            value = m.group(3).strip().lower()
            syn_record = by_syn.get(value)
            if syn_record is not None:
                # confirm it's the same galaxy type — don't rewrite
                # `misp-galaxy:tool="Sednit"` to a threat-actor tag just
                # because Sednit is an APT28 synonym.
                if syn_record.get("namespace") == "misp-galaxy" and \
                   m.group(1).split(":", 1)[1] == syn_record.get("galaxy_type"):
                    record = syn_record
                    matched_synonym = m.group(3)

    if record is None:
        return None

    reason = item.get("reason")
    return {
        "tag": record["tag"],                       # canonical from catalog
        "kind": record["kind"],
        "expanded": record.get("expanded"),
        "description": record.get("description") or "",
        "reason": reason if isinstance(reason, str) else None,
        "confidence": confidence,
        "matched_synonym": matched_synonym,
    }


# --- Object loaders -------------------------------------------------------

def _load_object(case_id: int, object_type: str, object_id: int):
    """Resolve (object_type, object_id) to the live ORM row, scoped to a case.

    Imports happen lazily inside the function to keep this module's import
    graph small and avoid surprises at app boot.
    """
    if object_type == "ioc":
        from app.models.models import Ioc
        # IOC -> case linkage runs through IocLink; but the simpler path is
        # to just trust the ioc_id and rely on the route's @ac_case_requires
        # to enforce case access.
        return Ioc.query.get(object_id)
    if object_type == "asset":
        from app.models.models import CaseAssets
        return CaseAssets.query.filter_by(asset_id=object_id, case_id=case_id).first()
    if object_type == "task":
        from app.models.models import CaseTasks
        return CaseTasks.query.filter_by(id=object_id, task_case_id=case_id).first()
    if object_type == "case":
        from app.models.cases import Cases
        return Cases.query.filter_by(case_id=case_id).first()
    if object_type == "event":
        from app.models.cases import CasesEvent
        return CasesEvent.query.filter_by(event_id=object_id, case_id=case_id).first()
    return None


def _build_object_payload(obj, object_type: str) -> dict[str, Any]:
    if object_type == "ioc":
        return _ioc_payload(obj)
    if object_type == "asset":
        return _asset_payload(obj)
    if object_type == "task":
        return _task_payload(obj)
    if object_type == "case":
        return _case_payload(obj)
    if object_type == "event":
        return _event_payload(obj)
    raise TagSuggesterError(f"Unknown object_type: {object_type!r}")


# --- Public entry point ---------------------------------------------------

def suggest_tags(*, case_id: int, object_type: str, object_id: int) -> dict[str, Any]:
    """Return validated MISP tag suggestions for the given case object.

    Returns:
      {
        "suggestions": [
          {tag, kind, expanded, description, reason, confidence, matched_synonym}
        ],
        "model": "<model id>",
        "object_type": "<type>",
        "object_id": <id>,
        "catalog_size": <int>,
      }
    """
    if object_type not in VALID_OBJECT_TYPES:
        raise TagSuggesterError(
            f"object_type must be one of {VALID_OBJECT_TYPES}, got {object_type!r}"
        )

    client = build_default_client(timeout=60.0, default_max_tokens=1200)
    if client is None:
        raise TagSuggesterError(
            "AI backend is not configured (set AI_BACKEND_URL / AI_BACKEND_MODEL "
            "or configure it in Server Settings)"
        )

    obj = _load_object(case_id, object_type, object_id)
    if obj is None:
        raise TagSuggesterError(
            f"{object_type} #{object_id} not found in case #{case_id}"
        )

    payload = _build_object_payload(obj, object_type)
    by_exact, by_syn = _build_lookups()

    system_prompt = load_system_prompt()
    user_prompt = (
        "## Object\n\n"
        f"```json\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n```\n\n"
        "Suggest 3-7 MISP machine tags for this object. Return JSON only."
    )

    app.logger.info(
        f"TagSuggester: requesting suggestions (model={client.model}, "
        f"case_id={case_id}, type={object_type}, id={object_id}, "
        f"catalog_size={len(by_exact)})"
    )

    try:
        response = client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])
    except AIClientError as exc:
        raise TagSuggesterError(f"AI backend call failed: {exc}") from exc

    raw = client.extract_content(response).strip()
    if not raw:
        finish = response.get("choices", [{}])[0].get("finish_reason")
        raise TagSuggesterError(f"AI backend returned empty response (finish_reason={finish})")

    try:
        parsed = json.loads(_extract_json_block(raw))
    except json.JSONDecodeError as exc:
        app.logger.warning(f"TagSuggester: model returned non-JSON: {raw[:300]}")
        raise TagSuggesterError(f"AI backend returned non-JSON: {exc}") from exc

    items = parsed.get("tags") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        raise TagSuggesterError("AI response missing 'tags' array")

    seen: set[str] = set()
    # exclude tags already on the object — model is told not to but defend.
    current = {t for t in payload.get("current_tags") or [] if isinstance(t, str)}

    validated: list[dict[str, Any]] = []
    for item in items:
        v = _validate_suggestion(item, by_exact, by_syn)
        if v is None:
            continue
        if v["tag"] in seen or v["tag"] in current:
            continue
        seen.add(v["tag"])
        validated.append(v)
        if len(validated) >= MAX_SUGGESTIONS:
            break

    app.logger.info(
        f"TagSuggester: kept {len(validated)}/{len(items)} suggestions for "
        f"{object_type}#{object_id}"
    )

    return {
        "suggestions": validated,
        "model": client.model,
        "object_type": object_type,
        "object_id": object_id,
        "catalog_size": len(by_exact),
    }

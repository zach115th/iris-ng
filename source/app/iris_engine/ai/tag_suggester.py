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
from app import db
from app.iris_engine import misp_tag_catalog
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client


TAG_SUGGESTER_PROMPT_ID = "TagSuggesterSystemPrompt-v2"
PROMPT_PATH = Path(__file__).parent.parent.parent / "resources" / "ai_prompts" / "tag_suggester.md"

VALID_OBJECT_TYPES = ("ioc", "asset", "task", "case", "event", "note")
DEFAULT_CONFIDENCE_FLOOR = 0.5
MAX_SUGGESTIONS = 7
CASE_VOCABULARY_CAP = 80
# A reasoning model spends tokens before its first visible character: seen
# live 2026-09-27 (lfm-2.5-2.6b), the old 1200 cap was consumed entirely by
# reasoning tokens and the reply was empty at finish_reason=length. Same
# budget as the case chat / task suggester / ICS draft (6000).
TAG_SUGGESTER_MAX_TOKENS = 6000
COMPACT_RETRY_SUFFIX = (
    "\n\nBe compact: answer with the JSON immediately, reasons at most ten words each, "
    "no deliberation before the answer."
)


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
        # Cases carry Tag rows on `.tags` (there is no `case_tags` attribute —
        # the old read returned [] for every case, so nothing was excluded).
        "current_tags": _current_tags_objects(getattr(case, "tags", None)),
    }


def _note_payload(note) -> dict[str, Any]:
    """iris-ng #129. Notes are narrative, so besides the catalog the model may
    reuse the labels already in use across this case (`case_vocabulary`)."""
    directory = getattr(getattr(note, "directory", None), "name", None)
    return {
        "kind": "note",
        "title": _truncate(note.note_title, 400),
        "directory": directory,
        "content": _truncate(note.note_content, 6000),
        "current_tags": _current_tags_csv(getattr(note, "note_tags", None)),
        "case_vocabulary": case_vocabulary(note.note_case_id),
    }


def case_vocabulary(case_id: int, cap: int = CASE_VOCABULARY_CAP) -> list[str]:
    """Every tag already used somewhere in this case — the case itself, its
    notes, IOCs, assets, tasks and timeline events — first-seen order, deduped
    case-insensitively, capped. `[]` = the case has no tags anywhere."""
    from app.models.cases import Cases, CasesEvent
    from app.models.models import CaseAssets, CaseTasks, Ioc, Notes

    seen: set[str] = set()
    out: list[str] = []

    def take(tags: list[str]) -> None:
        for t in tags:
            key = t.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(t)

    case = Cases.query.filter_by(case_id=case_id).first()
    if case is not None:
        take(_current_tags_objects(getattr(case, "tags", None)))
    sources = (
        (Notes.note_tags, Notes.note_case_id == case_id),
        (Ioc.ioc_tags, Ioc.case_id == case_id),
        (CaseAssets.asset_tags, CaseAssets.case_id == case_id),
        (CaseTasks.task_tags, CaseTasks.task_case_id == case_id),
        (CasesEvent.event_tags, CasesEvent.case_id == case_id),
    )
    for column, predicate in sources:
        rows = db.session.query(column).filter(predicate, column.isnot(None), column != "").all()
        for (value,) in rows:
            take(_current_tags_csv(value))
        if len(out) >= cap:
            break
    return out[:cap]


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
    """Cases carry tags as Tag-model rows (`Cases.tags`). A row without a title
    is skipped — the old `str(t)` fallback leaked the ORM repr (`<Tags 6>`)
    into the vocabulary offered to the model (seen live 2026-09-27)."""
    if not value:
        return []
    out = []
    for t in value:
        title = getattr(t, "tag_title", None)
        if isinstance(title, str) and title.strip():
            out.append(title.strip())
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


def _validate_suggestion(item: Any, by_exact: dict, by_syn: dict,
                         vocabulary: dict[str, str] | None = None) -> dict[str, Any] | None:
    """`vocabulary` maps lower-cased tag -> canonical spelling of tags already
    used in the case; a suggestion equal to one of them (case-insensitively) is
    accepted with kind 'case' even when it is not a MISP catalog tag."""
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

    if record is None and vocabulary:
        canonical = vocabulary.get(raw_tag.lower())
        if canonical:
            reason = item.get("reason")
            return {
                "tag": canonical,
                "kind": "case",
                "expanded": None,
                "description": "Already used in this case",
                "reason": reason if isinstance(reason, str) else None,
                "confidence": confidence,
                "matched_synonym": None,
            }

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
    if object_type == "note":
        from app.models.models import Notes
        return Notes.query.filter_by(note_id=object_id, note_case_id=case_id).first()
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
    if object_type == "note":
        return _note_payload(obj)
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

    client = build_default_client(timeout=180.0, default_max_tokens=TAG_SUGGESTER_MAX_TOKENS,
                                  feature='tag_suggester')
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
    vocabulary: dict[str, str] = {}
    if object_type == "note":
        vocabulary = {t.lower(): t for t in payload.get("case_vocabulary") or [] if isinstance(t, str)}
    user_prompt = (
        "## Object\n\n"
        f"```json\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n```\n\n"
        + ("Suggest 3-7 tags for this note: MISP machine tags, or any `case_vocabulary` "
           "entry copied verbatim. Return JSON only."
           if object_type == "note" else
           "Suggest 3-7 MISP machine tags for this object. Return JSON only.")
    )

    app.logger.info(
        f"TagSuggester: requesting suggestions (model={client.model}, "
        f"case_id={case_id}, type={object_type}, id={object_id}, "
        f"catalog_size={len(by_exact)})"
    )

    def _ask(prompt: str):
        try:
            resp = client.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ])
        except AIClientError as exc:
            raise TagSuggesterError(f"AI backend call failed: {exc}") from exc
        return resp, client.extract_content(resp).strip(), resp.get("choices", [{}])[0].get("finish_reason")

    response, raw, finish = _ask(user_prompt)
    if not raw and finish == "length":
        # The whole budget went to the thinking step (no visible output). One
        # retry asking for the answer first; the budget is unchanged on purpose
        # — the instruction, not the cap, is what moves a reasoning model.
        app.logger.warning(
            f"TagSuggester: empty reply at finish_reason=length for {object_type}#{object_id} "
            f"(usage={json.dumps(response.get('usage'))}); retrying with a compact instruction"
        )
        response, raw, finish = _ask(user_prompt + COMPACT_RETRY_SUFFIX)

    if not raw:
        if finish == "length":
            raise TagSuggesterError(
                "AI backend exhausted its output budget before answering (finish_reason=length, "
                "twice): the model spent the whole budget reasoning. Raise the tag suggester's "
                "budget or point its Settings override at a non-reasoning model."
            )
        raise TagSuggesterError(f"AI backend returned empty response (finish_reason={finish})")

    try:
        parsed = json.loads(_extract_json_block(raw))
    except json.JSONDecodeError as exc:
        app.logger.warning(f"TagSuggester: model returned non-JSON (finish_reason={finish}): {raw[:300]}")
        _detail = ' '.join((raw or '').split())[:200] or '<empty response>'
        if finish == "length":
            raise TagSuggesterError(
                f"AI backend reply was truncated (finish_reason=length) before the JSON closed. "
                f"Reply began: {_detail}"
            ) from exc
        raise TagSuggesterError(
            f"AI backend did not return JSON. Backend said: {_detail}"
        ) from exc

    items = parsed.get("tags") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        raise TagSuggesterError("AI response missing 'tags' array")

    seen: set[str] = set()
    # exclude tags already on the object — model is told not to but defend.
    current = {t for t in payload.get("current_tags") or [] if isinstance(t, str)}

    validated: list[dict[str, Any]] = []
    for item in items:
        v = _validate_suggestion(item, by_exact, by_syn, vocabulary or None)
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

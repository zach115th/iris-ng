#  IRIS Source Code
#
#  Indicator profile: a short AI reading of one IOC built from the indicator
#  itself AND everything tied to it — the other cases it appears in, the
#  notes that cite it, the assets it is linked to, and the timeline events
#  it is attached to.
#
#  Sibling of asset_profile.py; same conventions, same cache idiom
#  (kind = 'ioc_profile:<ioc_id>'), same two hard rules: counts are computed
#  here rather than asked of the model, and a failed generation is NEVER
#  persisted.
#
#  The cross-case section is the reason this is worth more for indicators
#  than for assets: an IOC is the thing that actually spans cases.

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app import app
from app import db
from app.datamgmt.case.case_iocs_db import get_ioc_links_bulk
from app.datamgmt.case.case_iocs_db import get_iocs_asset_links
from app.datamgmt.case.case_iocs_db import get_iocs_note_links
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client
from app.models.cases import Cases
from app.models.cases import CasesEvent
from app.models.models import CaseAiArtifact
from app.models.models import CaseEventsIoc
from app.models.models import Comments
from app.models.models import Ioc
from app.models.models import IocComments


IOC_PROFILE_KIND_PREFIX = "ioc_profile:"
IOC_PROFILE_PROMPT_ID = "IocProfileSystemPrompt-v1"

PROMPT_PATH = (Path(__file__).parent.parent.parent / "resources"
               / "ai_prompts" / "ioc_profile.md")

MAX_EVENTS = 60
MAX_COMMENTS = 30


class IocProfileError(Exception):
    """Raised when an indicator profile can't be produced."""


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[:limit] + " […]"


def _kind_for_ioc(ioc_id: int) -> str:
    return f"{IOC_PROFILE_KIND_PREFIX}{ioc_id}"


def _split_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in str(raw).replace("|", ",").split(",")
            if t.strip()]


def build_ioc_payload(case: Cases, ioc: Ioc) -> dict[str, Any]:
    """The indicator plus everything tied to it, with counts computed here."""
    ioc_id = ioc.ioc_id

    notes = get_iocs_note_links([ioc_id]).get(ioc_id, [])
    assets = get_iocs_asset_links([ioc_id]).get(ioc_id, [])

    # Cross-case links are ACL-scoped to the REQUESTING user — which is what
    # we want (a profile must never surface a case the reader cannot see),
    # but it means the helper needs current_user. In a worker context there
    # is none, and the same is true of any future async path.
    #
    # On failure the section is None, NOT [] — an empty list would tell the
    # model "this appears in no other case", which is a claim we cannot
    # support. None means "not looked up", and the prompt handles it.
    try:
        other_cases = get_ioc_links_bulk([ioc_id]).get(ioc_id, [])
    except Exception as exc:  # no authenticated user, ACL unavailable
        app.logger.warning(
            f"ioc_profile: cross-case lookup unavailable for ioc #{ioc_id} "
            f"({exc.__class__.__name__}); reporting it as unknown"
        )
        other_cases = None

    events = (
        db.session.query(CasesEvent)
        .join(CaseEventsIoc, CaseEventsIoc.event_id == CasesEvent.event_id)
        .filter(CaseEventsIoc.ioc_id == ioc_id,
                CasesEvent.case_id == case.case_id)
        .order_by(CasesEvent.event_date.asc())
        .all()
    )
    ev_rows = [{
        "date": e.event_date.isoformat() if e.event_date else None,
        "title": _truncate(e.event_title, 300),
        "content": _truncate(e.event_content, 600),
        "verdict": getattr(e, "event_verdict", None),
    } for e in events[:MAX_EVENTS]]

    comments = (
        db.session.query(Comments)
        .join(IocComments, IocComments.comment_id == Comments.comment_id)
        .filter(IocComments.comment_ioc_id == ioc_id)
        .order_by(Comments.comment_date.asc())
        .all()
    )
    c_rows = [{
        "date": c.comment_date.isoformat() if c.comment_date else None,
        "text": _truncate(c.comment_text, 800),
    } for c in comments[:MAX_COMMENTS]]

    # cross-case rows come back as row objects from the bulk self-join
    case_rows = None if other_cases is None else []
    for oc in (other_cases or []):
        case_rows.append({
            "case_id": getattr(oc, "case_id", None)
            if not isinstance(oc, dict) else oc.get("case_id"),
            "case_name": getattr(oc, "case_name", None)
            if not isinstance(oc, dict) else oc.get("case_name"),
            "client_name": getattr(oc, "client_name", None)
            if not isinstance(oc, dict) else oc.get("client_name"),
        })

    return {
        "indicator": {
            "id": ioc_id,
            "value": ioc.ioc_value,
            "type": ioc.ioc_type.type_name if ioc.ioc_type else None,
            "type_taxonomy": (ioc.ioc_type.type_taxonomy
                              if ioc.ioc_type else None),
            "description": _truncate(ioc.ioc_description, 2000),
            "tags": _split_tags(ioc.ioc_tags),
            "tlp": ioc.tlp.tlp_name if getattr(ioc, "tlp", None) else None,
        },
        "also_in_cases": case_rows,
        "linked_assets": assets,
        "citing_notes": notes,
        "timeline_events": ev_rows,
        "analyst_comments": c_rows,
        "counts": {
            # null, not 0 — see the cross-case note above
            "also_in_cases": None if case_rows is None else len(case_rows),
            "linked_assets": len(assets),
            "citing_notes": len(notes),
            "timeline_events": len(events),
            "analyst_comments": len(comments),
            "shown": {
                "timeline_events": len(ev_rows),
                "analyst_comments": len(c_rows),
            },
        },
        "case_context": {
            "id": case.case_id,
            "name": case.name,
            "classification": (case.classification.name
                               if getattr(case, "classification", None)
                               else None),
        },
    }


def compute_input_hash(payload: dict[str, Any], system_prompt: str,
                       model: str) -> str:
    blob = json.dumps(
        {"payload": payload, "prompt": system_prompt, "model": model},
        sort_keys=True, default=str
    )
    return hashlib.md5(blob.encode("utf-8")).hexdigest()


def get_cached_ioc_profile(case_id: int, ioc_id: int) -> CaseAiArtifact | None:
    return (
        CaseAiArtifact.query
        .filter(CaseAiArtifact.case_id == case_id,
                CaseAiArtifact.kind == _kind_for_ioc(ioc_id))
        .order_by(CaseAiArtifact.generated_at.desc())
        .first()
    )


def find_cache_hit(case_id: int, ioc_id: int,
                   input_hash: str) -> CaseAiArtifact | None:
    return (
        CaseAiArtifact.query
        .filter(CaseAiArtifact.case_id == case_id,
                CaseAiArtifact.kind == _kind_for_ioc(ioc_id),
                CaseAiArtifact.input_hash == input_hash)
        .order_by(CaseAiArtifact.generated_at.desc())
        .first()
    )


def generate_ioc_profile(case_id: int, ioc_id: int, *,
                         force: bool = False) -> CaseAiArtifact:
    case = Cases.query.filter(Cases.case_id == case_id).first()
    if case is None:
        raise IocProfileError(f"Case #{case_id} not found")

    ioc = Ioc.query.filter(Ioc.ioc_id == ioc_id,
                           Ioc.case_id == case_id).first()
    if ioc is None:
        raise IocProfileError(f"Indicator #{ioc_id} not found in case #{case_id}")

    client = build_default_client(timeout=600.0, default_max_tokens=2000,
                                  feature='ioc_profile')
    if client is None:
        raise IocProfileError(
            "AI backend is not configured (set AI_BACKEND_URL and AI_BACKEND_MODEL)"
        )

    system_prompt = load_system_prompt()
    payload = build_ioc_payload(case, ioc)
    input_hash = compute_input_hash(payload, system_prompt, client.model)

    if not force:
        cached = find_cache_hit(case_id, ioc_id, input_hash)
        if cached is not None:
            app.logger.info(
                f"Case #{case_id} ioc #{ioc_id}: returning cached profile "
                f"(generated_at={cached.generated_at.isoformat()})"
            )
            return cached

    user_prompt = (
        "Profile this indicator using everything below. Sections that are "
        "empty are empty in the case data — say so rather than inventing "
        f"content.\n\n```json\n{json.dumps(payload, indent=2, default=str)}\n```"
    )

    app.logger.info(
        f"Case #{case_id} ioc #{ioc_id}: generating fresh profile "
        f"(model={client.model})"
    )

    try:
        response = client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
    except AIClientError as exc:
        raise IocProfileError(f"AI backend call failed: {exc}") from exc

    content = client.extract_content(response).strip()
    if not content:
        raise IocProfileError("AI backend returned an empty response")

    artifact = CaseAiArtifact(
        case_id=case_id,
        kind=_kind_for_ioc(ioc_id),
        prompt_id=IOC_PROFILE_PROMPT_ID,
        model=client.model,
        input_hash=input_hash,
        content=content,
        confidence=None,
    )
    db.session.add(artifact)
    db.session.commit()

    app.logger.info(
        f"Case #{case_id} ioc #{ioc_id}: profile persisted "
        f"(artifact_id={artifact.id}, len={len(content)} chars)"
    )
    return artifact

#  IRIS Source Code
#
#  Asset profile: a short AI reading of one case asset built from everything
#  recorded about it AND everything linked to it — indicators, evidence,
#  timeline events, analyst comments — plus a trimmed case context.
#
#  Cached per (case_id, asset_id) in case_ai_artifact using
#  kind = 'asset_profile:<asset_id>', the same discriminator idiom as
#  event_analysis, so no new column is needed.
#
#  Two rules this file exists to honour:
#    * counts are computed HERE and handed to the model — never asked of it;
#    * a failed or empty generation is NEVER persisted (a cached error
#      outlives its cause and reads as a live failure).

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
from app.models.models import AnalysisStatus
from app.models.models import AssetComments
from app.models.models import AssetsType
from app.models.models import CaseAiArtifact
from app.models.models import CaseAssets
from app.models.models import CaseEventsAssets
from app.models.models import CaseReceivedFile
from app.models.models import Comments
from app.models.models import EvidenceAssetLink
from app.models.models import Ioc
from app.models.models import IocAssetLink


ASSET_PROFILE_KIND_PREFIX = "asset_profile:"
ASSET_PROFILE_PROMPT_ID = "AssetProfileSystemPrompt-v1"

PROMPT_PATH = (Path(__file__).parent.parent.parent / "resources"
               / "ai_prompts" / "asset_profile.md")

# Caps keep a busy asset's payload bounded. They are deliberately generous —
# an asset with 200 timeline events is exactly the one worth summarising.
MAX_EVENTS = 60
MAX_IOCS = 60
MAX_EVIDENCE = 30
MAX_COMMENTS = 30

COMPROMISE_LABELS = {
    0: "to be determined",
    1: "compromised",
    2: "not compromised",
    3: "unknown",
}


class AssetProfileError(Exception):
    """Raised when an asset profile can't be produced."""


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[:limit] + " […]"


def _kind_for_asset(asset_id: int) -> str:
    return f"{ASSET_PROFILE_KIND_PREFIX}{asset_id}"


def _split_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in str(raw).replace("|", ",").split(",") if t.strip()]


def build_asset_payload(case: Cases, asset: CaseAssets) -> dict[str, Any]:
    """Everything recorded about the asset, plus everything linked to it.

    Every section is present even when empty, and `counts` is computed here
    so the model never has to count anything — the same rule the case-summary
    evidence specialist follows.
    """
    case_id = case.case_id
    asset_id = asset.asset_id

    a_type = db.session.get(AssetsType, asset.asset_type_id) if asset.asset_type_id else None
    a_status = (db.session.get(AnalysisStatus, asset.analysis_status_id)
                if asset.analysis_status_id else None)

    # ---- linked indicators
    iocs = (
        db.session.query(Ioc)
        .join(IocAssetLink, IocAssetLink.ioc_id == Ioc.ioc_id)
        .filter(IocAssetLink.asset_id == asset_id)
        .all()
    )
    ioc_rows = [{
        "value": i.ioc_value,
        "type": i.ioc_type.type_name if i.ioc_type else None,
        "description": _truncate(i.ioc_description, 400),
        "tags": _split_tags(i.ioc_tags),
    } for i in iocs[:MAX_IOCS]]

    # ---- linked evidence
    evidence = (
        db.session.query(CaseReceivedFile)
        .join(EvidenceAssetLink,
              EvidenceAssetLink.evidence_id == CaseReceivedFile.id)
        .filter(EvidenceAssetLink.asset_id == asset_id)
        .all()
    )
    ev_rows = [{
        "filename": e.filename,
        "type": e.type.name if e.type else None,
        "size_bytes": e.file_size,
        # whether it is hashed is a finding; the hash itself adds nothing here
        "hashed": bool(e.file_hash),
        "description": _truncate(e.file_description, 300),
    } for e in evidence[:MAX_EVIDENCE]]

    # ---- timeline events this asset appears in
    events = (
        db.session.query(CasesEvent)
        .join(CaseEventsAssets,
              CaseEventsAssets.event_id == CasesEvent.event_id)
        .filter(CaseEventsAssets.asset_id == asset_id,
                CasesEvent.case_id == case_id)
        .order_by(CasesEvent.event_date.asc())
        .all()
    )
    ev_tl = [{
        "date": e.event_date.isoformat() if e.event_date else None,
        "title": _truncate(e.event_title, 300),
        "content": _truncate(e.event_content, 600),
        "source": e.event_source,
        # the analyst's triage call, so the model can weigh a dismissed event
        "verdict": getattr(e, "event_verdict", None),
    } for e in events[:MAX_EVENTS]]

    # ---- analyst comments on the asset
    comments = (
        db.session.query(Comments)
        .join(AssetComments, AssetComments.comment_id == Comments.comment_id)
        .filter(AssetComments.comment_asset_id == asset_id)
        .order_by(Comments.comment_date.asc())
        .all()
    )
    c_rows = [{
        "date": c.comment_date.isoformat() if c.comment_date else None,
        "text": _truncate(c.comment_text, 800),
    } for c in comments[:MAX_COMMENTS]]

    return {
        "asset": {
            "id": asset_id,
            "name": asset.asset_name,
            "type": a_type.asset_name if a_type else None,
            "description": _truncate(asset.asset_description, 2000),
            "ip": asset.asset_ip,
            "domain": asset.asset_domain,
            "additional_info": _truncate(asset.asset_info, 1000),
            "tags": _split_tags(asset.asset_tags),
            "compromise_status": COMPROMISE_LABELS.get(
                asset.asset_compromise_status_id
                if asset.asset_compromise_status_id is not None else 0,
                "to be determined"),
            "analysis_status": a_status.name if a_status else None,
        },
        "linked_iocs": ioc_rows,
        "linked_evidence": ev_rows,
        "timeline_events": ev_tl,
        "analyst_comments": c_rows,
        # Server-computed: totals BEFORE the caps above, so the model can say
        # "38 events, 60 shown" instead of miscounting a truncated list.
        "counts": {
            "linked_iocs": len(iocs),
            "linked_evidence": len(evidence),
            "timeline_events": len(events),
            "analyst_comments": len(comments),
            "shown": {
                "linked_iocs": len(ioc_rows),
                "linked_evidence": len(ev_rows),
                "timeline_events": len(ev_tl),
                "analyst_comments": len(c_rows),
            },
        },
        "case_context": {
            "id": case_id,
            "name": case.name,
            "classification": (case.classification.name
                               if getattr(case, "classification", None) else None),
        },
    }


def compute_input_hash(payload: dict[str, Any], system_prompt: str,
                       model: str) -> str:
    """Hash only what changes when the DATA changes.

    Nothing wall-clock-derived goes in — that was the case-summary cache bug
    where every view produced a fresh hash and the cache never hit.
    """
    blob = json.dumps(
        {"payload": payload, "prompt": system_prompt, "model": model},
        sort_keys=True, default=str
    )
    return hashlib.md5(blob.encode("utf-8")).hexdigest()


def get_cached_asset_profile(case_id: int, asset_id: int) -> CaseAiArtifact | None:
    return (
        CaseAiArtifact.query
        .filter(CaseAiArtifact.case_id == case_id,
                CaseAiArtifact.kind == _kind_for_asset(asset_id))
        .order_by(CaseAiArtifact.generated_at.desc())
        .first()
    )


def find_cache_hit(case_id: int, asset_id: int,
                   input_hash: str) -> CaseAiArtifact | None:
    return (
        CaseAiArtifact.query
        .filter(CaseAiArtifact.case_id == case_id,
                CaseAiArtifact.kind == _kind_for_asset(asset_id),
                CaseAiArtifact.input_hash == input_hash)
        .order_by(CaseAiArtifact.generated_at.desc())
        .first()
    )


def generate_asset_profile(case_id: int, asset_id: int, *,
                           force: bool = False) -> CaseAiArtifact:
    case = Cases.query.filter(Cases.case_id == case_id).first()
    if case is None:
        raise AssetProfileError(f"Case #{case_id} not found")

    asset = CaseAssets.query.filter(
        CaseAssets.case_id == case_id, CaseAssets.asset_id == asset_id
    ).first()
    if asset is None:
        raise AssetProfileError(
            f"Asset #{asset_id} not found in case #{case_id}")

    client = build_default_client(timeout=600.0, default_max_tokens=2000,
                                  feature='asset_profile')
    if client is None:
        raise AssetProfileError(
            "AI backend is not configured (set AI_BACKEND_URL and AI_BACKEND_MODEL)"
        )

    system_prompt = load_system_prompt()
    payload = build_asset_payload(case, asset)
    input_hash = compute_input_hash(payload, system_prompt, client.model)

    if not force:
        cached = find_cache_hit(case_id, asset_id, input_hash)
        if cached is not None:
            app.logger.info(
                f"Case #{case_id} asset #{asset_id}: returning cached profile "
                f"(generated_at={cached.generated_at.isoformat()})"
            )
            return cached

    user_prompt = (
        "Profile this asset using everything below. Sections that are empty "
        "are empty in the case data — say so rather than inventing content.\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
    )

    app.logger.info(
        f"Case #{case_id} asset #{asset_id}: generating fresh profile "
        f"(model={client.model})"
    )

    try:
        response = client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
    except AIClientError as exc:
        # raise — never persist the failure as if it were a profile
        raise AssetProfileError(f"AI backend call failed: {exc}") from exc

    content = client.extract_content(response).strip()
    if not content:
        raise AssetProfileError("AI backend returned an empty response")

    artifact = CaseAiArtifact(
        case_id=case_id,
        kind=_kind_for_asset(asset_id),
        prompt_id=ASSET_PROFILE_PROMPT_ID,
        model=client.model,
        input_hash=input_hash,
        content=content,
        confidence=None,
    )
    db.session.add(artifact)
    db.session.commit()

    app.logger.info(
        f"Case #{case_id} asset #{asset_id}: profile persisted "
        f"(artifact_id={artifact.id}, len={len(content)} chars)"
    )
    return artifact

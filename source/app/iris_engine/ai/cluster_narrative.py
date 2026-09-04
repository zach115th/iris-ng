#  IRIS Source Code
#
#  AI cluster narrative generator (docs/19 §19 — Dashboard Correlation tab).
#
#  Given a correlation cluster (case IDs + shared IOCs + case metadata),
#  generates a campaign narrative + suggested human-readable name.
#
#  Caching: stored in `case_ai_artifact` with kind='cluster_narrative:<cluster_id>'
#  and case_id=min(cluster.case_ids) (clusters span multiple cases; anchoring to
#  the smallest member case_id is stable and requires no schema change).
#  Cache key = input_hash of (payload JSON + prompt text + model name).
#  force=True bypasses the cache (same pattern as other orchestrators).
#
#  Prompt: source/app/resources/ai_prompts/cluster_narrative.md

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from typing import Any

from app import app, db
from app.iris_engine.ai.openai_client import AIClientError, OpenAIClient, build_default_client
from app.models.models import CaseAiArtifact

log = logging.getLogger(__name__)

PROMPT_ID = "ClusterNarrativeSystemPrompt-v2"
_PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "resources", "ai_prompts", "cluster_narrative.md"
)


def _load_system_prompt() -> str:
    with open(_PROMPT_PATH, encoding="utf-8") as fh:
        return fh.read()


def _build_payload(cluster: dict, case_meta: dict) -> dict[str, Any]:
    """Build the hashable payload dict for the prompt."""
    cases_detail = []
    for cid in cluster.get("case_ids", []):
        meta = case_meta.get(str(cid)) or case_meta.get(cid) or {}
        cases_detail.append({
            "case_id": cid,
            "name": meta.get("name", ""),
            "client": meta.get("client", ""),
            "open_date": meta.get("open_date", ""),
            "close_date": meta.get("close_date", ""),
            "classification": meta.get("classification", ""),
            "severity": meta.get("severity", ""),
            "case_tags": meta.get("case_tags", []),
        })

    return {
        "cluster_id": cluster.get("cluster_id", ""),
        "case_count": len(cluster.get("case_ids", [])),
        "shared_ioc_count": cluster.get("shared_ioc_count", 0),
        "shared_ioc_values": cluster.get("shared_iocs", []),
        "suggested_campaign_tag": cluster.get("suggested_campaign_tag", ""),
        "cases": cases_detail,
    }


def _compute_input_hash(payload: dict, system_prompt: str, model: str) -> str:
    canon = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    h = hashlib.md5()
    h.update(model.encode("utf-8"))
    h.update(b"\x00")
    h.update(system_prompt.encode("utf-8"))
    h.update(b"\x00")
    h.update(canon.encode("utf-8"))
    return h.hexdigest()


def _kind(cluster_id: str) -> str:
    return f"cluster_narrative:{cluster_id}"


def _find_cache_hit(anchor_case_id: int, kind: str, input_hash: str) -> CaseAiArtifact | None:
    return (
        CaseAiArtifact.query
        .filter(
            CaseAiArtifact.case_id == anchor_case_id,
            CaseAiArtifact.kind == kind,
            CaseAiArtifact.input_hash == input_hash,
        )
        .order_by(CaseAiArtifact.generated_at.desc())
        .first()
    )


def _artifact_to_result(art: CaseAiArtifact, *, cached: bool) -> dict[str, Any]:
    """Deserialise a CaseAiArtifact row into the public result dict.

    Reads `display_content`, so an analyst correction supersedes the model text
    for every consumer — the Correlation panel AND the STIX export.
    """
    try:
        obj = json.loads(art.display_content)
    except (TypeError, ValueError):
        obj = {"narrative": art.display_content, "suggested_name": "Cluster analysis", "confidence": "low"}
    obj["prompt_id"] = art.prompt_id
    obj["model"] = art.model
    obj["cluster_id"] = art.kind.split(":", 1)[1] if ":" in art.kind else ""
    obj["cached"] = cached
    obj["generated_at"] = art.generated_at.isoformat() if art.generated_at else None
    obj["artifact_id"] = art.id
    obj["is_edited"] = art.is_edited
    obj["edited_at"] = art.edited_at.isoformat() if art.edited_at else None
    obj["edited_by"] = art.edited_by.name if art.edited_by else None
    if art.is_edited:
        # Backs "View AI original" without a second round-trip.
        try:
            ai_obj = json.loads(art.content)
        except (TypeError, ValueError):
            ai_obj = {"narrative": art.content, "suggested_name": "Cluster analysis"}
        obj["ai_narrative"] = ai_obj.get("narrative", "")
        obj["ai_suggested_name"] = ai_obj.get("suggested_name", "")
    return obj


class ClusterNarrativeEditError(Exception):
    """Raised when a manual narrative edit cannot be saved or reverted."""


def get_latest_cluster_narrative(anchor_case_id: int, cluster_id: str) -> CaseAiArtifact | None:
    """Newest stored narrative for a cluster, regardless of input hash.

    The hash-matched `_find_cache_hit` is the generation cache; edit/revert
    need "whatever the analyst is currently looking at" instead.
    """
    return (
        CaseAiArtifact.query
        .filter(
            CaseAiArtifact.case_id == anchor_case_id,
            CaseAiArtifact.kind == _kind(cluster_id),
        )
        .order_by(CaseAiArtifact.generated_at.desc())
        .first()
    )


def save_cluster_narrative_edit(
    anchor_case_id: int,
    cluster_id: str,
    suggested_name: str,
    narrative: str,
    user_id: int,
) -> CaseAiArtifact:
    """Store an analyst correction over a generated cluster narrative.

    Keeps the model's `confidence` from the original — it grades the underlying
    correlation data, not the wording, and an analyst-authored confidence on a
    partly-AI narrative is hard to interpret later. The edit badge carries the
    human-correction signal instead.
    """
    art = get_latest_cluster_narrative(anchor_case_id, cluster_id)
    if art is None:
        raise ClusterNarrativeEditError(
            f"Cluster {cluster_id} has no generated narrative to edit — run Analyze cluster first"
        )

    name = (suggested_name or "").strip()
    body = (narrative or "").strip()
    if not body:
        raise ClusterNarrativeEditError("Narrative cannot be empty")
    if not name:
        raise ClusterNarrativeEditError("Campaign title cannot be empty")

    try:
        original = json.loads(art.content)
    except (TypeError, ValueError):
        original = {}

    art.edited_content = json.dumps(
        {
            "suggested_name": name,
            "narrative": body,
            "confidence": original.get("confidence", "low"),
        },
        ensure_ascii=False,
    )
    art.edited_by_id = user_id
    art.edited_at = datetime.utcnow()
    db.session.commit()

    log.info(
        "cluster_narrative: cluster %s manually edited by user %s (artifact_id=%s)",
        cluster_id, user_id, art.id,
    )
    return art


def revert_cluster_narrative_edit(anchor_case_id: int, cluster_id: str) -> CaseAiArtifact:
    """Drop the analyst override, restoring the original model output."""
    art = get_latest_cluster_narrative(anchor_case_id, cluster_id)
    if art is None:
        raise ClusterNarrativeEditError(f"Cluster {cluster_id} has no stored narrative")

    if art.is_edited:
        art.edited_content = None
        art.edited_by_id = None
        art.edited_at = None
        db.session.commit()
        log.info("cluster_narrative: cluster %s edit reverted (artifact_id=%s)", cluster_id, art.id)
    return art


def _parse_response(raw: str) -> dict[str, Any]:
    """Extract the JSON object from the model output, or raise.

    This function used to return `{"narrative": raw}` on any parse failure,
    which made EVERY failure mode look like a successful generation:
    a backend auth error, a truncated reply, or an LFM tool call became a
    "narrative", got persisted to case_ai_artifact, outlived the outage
    (reads take the newest row) and — because cluster narratives feed the
    STIX export and the MISP push — reached third parties. That is the
    documented 2026-08-24 incident, whose fix note said "only persist
    output that parsed into the expected shape". This is that fix.

    Raising is safe for callers: the endpoint already maps AIClientError to
    an error response, so the panel renders it as a transient failure with
    a Re-run affordance instead of caching it as content.
    """
    if not raw or not raw.strip():
        raise AIClientError(
            "AI backend returned no usable content for the cluster narrative"
        )

    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        log.warning("cluster_narrative: no JSON object in response — refusing to persist")
        raise AIClientError(
            "AI backend returned no JSON object for the cluster narrative "
            f"(first 200 chars: {cleaned[:200]!r})"
        )
    try:
        obj = json.loads(match.group())
    except json.JSONDecodeError as exc:
        log.warning("cluster_narrative: JSON parse error — refusing to persist — %s", exc)
        raise AIClientError(
            f"AI backend returned malformed JSON for the cluster narrative: {exc}"
        ) from exc

    narrative = str(obj.get("narrative", "")).strip()
    if not narrative:
        raise AIClientError(
            "AI backend returned a cluster narrative with no narrative text"
        )

    return {
        "suggested_name": str(obj.get("suggested_name", "")).strip() or "Cluster analysis",
        "narrative": narrative,
        "confidence": obj.get("confidence", "low") if obj.get("confidence") in ("high", "medium", "low") else "low",
    }


def generate_cluster_narrative(
    cluster: dict,
    case_meta: dict,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """
    Generate (or return cached) a campaign narrative for the given correlation cluster.

    Args:
        cluster: A cluster dict from build_correlation_report() —
                 {cluster_id, case_ids, shared_ioc_count, shared_iocs, suggested_campaign_tag}
        case_meta: The case_meta dict from the same report, keyed by case_id (int or str).
        force: If True, bypass the cache and regenerate.

    Returns:
        {suggested_name, narrative, confidence, prompt_id, cluster_id,
         cached, generated_at, artifact_id}
    """
    cluster_id = cluster.get("cluster_id", "")
    case_ids = sorted(cluster.get("case_ids", []))
    if not case_ids:
        raise AIClientError("cluster.case_ids must be non-empty")

    # Anchor to the smallest case_id — stable across re-renders, no migration needed
    anchor_case_id = case_ids[0]
    kind = _kind(cluster_id)

    client: OpenAIClient | None = build_default_client(
        feature="cluster_narrative",
        timeout=120.0,
        default_max_tokens=800,
    )
    if client is None:
        raise AIClientError("AI backend is not configured. Enable it in Manage → Settings → AI.")

    system_prompt = _load_system_prompt()
    payload = _build_payload(cluster, case_meta)
    input_hash = _compute_input_hash(payload, system_prompt, client.model)

    if not force:
        cached = _find_cache_hit(anchor_case_id, kind, input_hash)
        if cached is not None:
            app.logger.info(
                f"cluster_narrative: cache hit (cluster={cluster_id}, artifact_id={cached.id})"
            )
            return _artifact_to_result(cached, cached=True)

    payload_json = json.dumps(payload, indent=2, default=str)
    messages = [
        {
            "role": "system",
            "content": system_prompt + "\n\n" + payload_json,
        },
        {
            "role": "user",
            "content": (
                "Analyse the cluster above. "
                "Output ONLY the JSON object — no prose, no markdown fences."
            ),
        },
    ]

    try:
        resp = client.chat(messages, max_tokens=800)
        raw = OpenAIClient.extract_content(resp)
    except AIClientError as exc:
        log.error("cluster_narrative: AI call failed — %s", exc)
        raise

    result = _parse_response(raw)

    # Persist to case_ai_artifact
    art = CaseAiArtifact(
        case_id=anchor_case_id,
        kind=kind,
        prompt_id=PROMPT_ID,
        model=client.model,
        input_hash=input_hash,
        content=json.dumps(result, ensure_ascii=False),
        confidence=None,
    )
    db.session.add(art)
    db.session.commit()

    app.logger.info(
        f"cluster_narrative: persisted (cluster={cluster_id}, artifact_id={art.id}, "
        f"len={len(raw)} chars)"
    )

    result["prompt_id"] = PROMPT_ID
    result["model"] = client.model
    result["cluster_id"] = cluster_id
    result["cached"] = False
    result["generated_at"] = art.generated_at.isoformat() if art.generated_at else None
    result["artifact_id"] = art.id
    return result

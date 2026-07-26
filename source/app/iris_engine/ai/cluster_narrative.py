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
    """Deserialise a CaseAiArtifact row into the public result dict."""
    try:
        obj = json.loads(art.content)
    except (TypeError, ValueError):
        obj = {"narrative": art.content, "suggested_name": "Cluster analysis", "confidence": "low"}
    obj["prompt_id"] = art.prompt_id
    obj["model"] = art.model
    obj["cluster_id"] = art.kind.split(":", 1)[1] if ":" in art.kind else ""
    obj["cached"] = cached
    obj["generated_at"] = art.generated_at.isoformat() if art.generated_at else None
    obj["artifact_id"] = art.id
    return obj


def _parse_response(raw: str) -> dict[str, Any]:
    """Extract the JSON object from the model output. Returns defaults on parse failure."""
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        log.warning("cluster_narrative: no JSON object found in response — returning raw as narrative")
        return {
            "suggested_name": "Cluster analysis",
            "narrative": raw.strip(),
            "confidence": "low",
        }
    try:
        obj = json.loads(match.group())
    except json.JSONDecodeError as exc:
        log.warning("cluster_narrative: JSON parse error — %s", exc)
        return {
            "suggested_name": "Cluster analysis",
            "narrative": raw.strip(),
            "confidence": "low",
        }
    return {
        "suggested_name": str(obj.get("suggested_name", "")).strip() or "Cluster analysis",
        "narrative": str(obj.get("narrative", "")).strip(),
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

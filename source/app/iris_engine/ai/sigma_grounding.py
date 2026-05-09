#  IRIS Source Code
#
#  Sigma-rule grounding for the AI features. Given an event title +
#  description (or any free-text hunting prompt), find the top-K matching
#  Sigma detection rules from the user's Pinecone index and extract their
#  ATT&CK technique mappings.
#
#  Two callers today:
#  - attack_suggester.py — feeds the matches into the LM Studio prompt as
#    "Sigma evidence", so the model picks ATT&CK techniques from grounded
#    candidates instead of free-form generation.
#  - (planned) per-event analysis drawer — surfaces matching Sigma rules
#    as chips below the AI analysis so analysts see "here's what detection
#    engineers think this looks like."
#
#  The Sigma index metadata fields we consume (best-effort — different
#  Sigma corpora use different field names):
#    - title         — short rule name
#    - description   — what the rule detects
#    - tags          — list/string of MITRE ATT&CK tags + product tags
#    - level         — informational / low / medium / high / critical
#    - logsource     — product/category/service the rule fires on
#    - id            — Sigma rule UUID
#    - rule_name     — sometimes the YAML filename
#
#  We don't fail if any field is missing — the orchestrator just emits what
#  it has. RAG is an enhancement, not a contract.

from __future__ import annotations

import re
from typing import Any

from app import app
from app.iris_engine.ai.pinecone_client import _config as _pinecone_config
from app.iris_engine.ai.pinecone_client import is_configured
from app.iris_engine.ai.pinecone_client import search_text


# T1059, T1059.001 — same regex as attack_suggester. Tags in Sigma rules
# usually look like `attack.t1059.001` or `attack.execution`; we extract
# only the technique IDs, not the tactic names.
TECHNIQUE_TAG_RE = re.compile(r"\battack\.(t\d{4}(?:\.\d{3})?)\b", re.IGNORECASE)
TECHNIQUE_RAW_RE = re.compile(r"\b(T\d{4}(?:\.\d{3})?)\b")


def _sigma_host() -> str:
    # Pull from the merged DB-first / env-fallback view so the admin UI
    # toggle on /manage/settings actually drives this caller.
    return _pinecone_config().get("sigma_host", "")


def _extract_techniques(metadata: dict[str, Any]) -> list[str]:
    """Pull MITRE technique IDs out of a Sigma rule's metadata.

    Looks at `tags` (the canonical Sigma field) plus a couple fallback
    fields. Returns deduped, uppercase IDs in input order.
    """
    found: list[str] = []
    seen: set[str] = set()

    candidates: list[str] = []
    tags = metadata.get("tags")
    if isinstance(tags, list):
        candidates.extend(str(t) for t in tags if t)
    elif isinstance(tags, str):
        candidates.append(tags)
    # Some corpora put techniques under their own field
    for extra_field in ("attack_techniques", "techniques", "mitre_techniques"):
        v = metadata.get(extra_field)
        if isinstance(v, list):
            candidates.extend(str(t) for t in v if t)
        elif isinstance(v, str):
            candidates.append(v)

    for raw in candidates:
        # Try the `attack.tNNNN` form first (case-insensitive)
        for match in TECHNIQUE_TAG_RE.finditer(raw):
            tid = match.group(1).upper()
            if tid not in seen:
                seen.add(tid)
                found.append(tid)
        # Then the bare `T1059` form (already uppercase by regex)
        for match in TECHNIQUE_RAW_RE.finditer(raw):
            tid = match.group(1)
            if tid not in seen:
                seen.add(tid)
                found.append(tid)
    return found


def _shape_match(match: dict[str, Any]) -> dict[str, Any]:
    """Trim a Pinecone match to the fields our callers actually use."""
    metadata = match.get("metadata") or {}
    techniques = _extract_techniques(metadata)
    return {
        "id": match.get("id"),
        "score": match.get("score"),
        "title": metadata.get("title") or metadata.get("rule_name") or metadata.get("name"),
        "description": metadata.get("description"),
        "level": metadata.get("level"),
        "logsource": metadata.get("logsource") or metadata.get("source"),
        "techniques": techniques,
        "raw_metadata": metadata,  # callers can dig in if they need more
    }


def find_matching_sigma_rules(
    *,
    query_text: str,
    top_k: int = 5,
    min_score: float = 0.35,
) -> list[dict[str, Any]]:
    """Semantic-search the Sigma index and return shaped matches.

    Args:
        query_text: free-text query (event title + description, hunting prompt, etc.)
        top_k: how many matches to return.
        min_score: cosine-similarity floor; matches below this are dropped.
            Pinecone scores are dot-product / cosine depending on the index;
            for llama-text-embed-v2 typical strong matches sit at 0.5-0.85.
            0.35 is a permissive floor that still cuts random noise.

    Returns: list of `{id, score, title, description, level, logsource, techniques, raw_metadata}`
             sorted by score desc. Empty if Pinecone isn't configured, the
             call fails, or nothing matches above min_score.
    """
    if not is_configured():
        return []
    host = _sigma_host()
    if not host:
        return []
    text = (query_text or "").strip()
    if not text:
        return []

    matches = search_text(host=host, text=text, top_k=top_k)
    shaped = [_shape_match(m) for m in matches]

    # Pinecone returns matches sorted by score already, but the score floor
    # cut may shrink the list — re-sort defensively.
    filtered = [m for m in shaped if isinstance(m["score"], (int, float)) and m["score"] >= min_score]
    filtered.sort(key=lambda m: m["score"], reverse=True)

    top_score = filtered[0]["score"] if filtered else 0.0
    app.logger.info(
        f"sigma_grounding: '{text[:60]}…' → "
        f"{len(filtered)}/{len(matches)} matches above {min_score} "
        f"(top score={top_score:.3f})"
    )
    return filtered


def aggregate_techniques(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Roll up technique IDs across N Sigma matches with weighted votes.

    Returns: [{technique_id, weight, source_count, max_score, sources: [{rule_title, score}, ...]}]
    sorted by weight descending. Weight = sum(score) over the matches that
    cited the technique — gives techniques mentioned by multiple
    high-scoring rules a confidence boost over those mentioned once.
    """
    bag: dict[str, dict[str, Any]] = {}
    for m in matches:
        score = m.get("score") or 0.0
        title = m.get("title") or m.get("id") or "<unknown>"
        for tid in m.get("techniques") or []:
            if tid not in bag:
                bag[tid] = {
                    "technique_id": tid,
                    "weight": 0.0,
                    "source_count": 0,
                    "max_score": 0.0,
                    "sources": [],
                }
            bag[tid]["weight"] += float(score)
            bag[tid]["source_count"] += 1
            if score > bag[tid]["max_score"]:
                bag[tid]["max_score"] = float(score)
            bag[tid]["sources"].append({"rule_title": title, "score": float(score)})

    out = list(bag.values())
    out.sort(key=lambda t: (t["weight"], t["max_score"]), reverse=True)
    return out

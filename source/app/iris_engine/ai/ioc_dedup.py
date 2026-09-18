#  IRIS Source Code
#
#  AI pass for IOC deduplication (#83). Judges one case's indicator list
#  and proposes pairs that are very likely the same indicator in two
#  notations — what a string comparison misses. ADVISORY ONLY: the result
#  is rendered in the dedup modal for the analyst to keep A / keep B /
#  merge / keep both; nothing is applied here.
#
#  Stateless (no case_ai_artifact row): the input is the live IOC list, the
#  result is consumed once by the modal, and a stale cached verdict about a
#  list that has since been merged would be worse than a fresh call.
#  Runs on the async queue (FEATURES['ioc_dedup']) — a few hundred rows can
#  take a small model a while.
#
#  Server-side validation: every id must exist in the case, a != b, pairs
#  are unordered-unique, exact duplicates (already handled) are dropped,
#  confidence is clamped to [0, 1]; the model is authoritative for nothing
#  but the pairing itself.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app import app
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client
from app.iris_engine.utils.ioc_normalise import normalise_ioc_value

IOC_DEDUP_PROMPT_ID = "IocDedupSystemPrompt-v1"
PROMPT_PATH = Path(__file__).parent.parent.parent / "resources" / "ai_prompts" / "ioc_dedup.md"

MAX_IOCS = 400          # rows sent to the model (lowest ids first)
MAX_PAIRS = 50
DESCRIPTION_CHARS = 120


class IocDedupError(Exception):
    """Raised when the AI pass cannot proceed."""


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _extract_json_block(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9]*\n?", "", stripped)
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


def build_payload(iocs: list, type_names: dict[int, str]) -> tuple[list[dict[str, Any]], bool]:
    rows = sorted(iocs, key=lambda i: i.ioc_id)
    truncated = len(rows) > MAX_IOCS
    out = []
    for i in rows[:MAX_IOCS]:
        desc = (i.ioc_description or "").strip()
        out.append({
            "id": int(i.ioc_id),
            "type": type_names.get(i.ioc_type_id, "?"),
            "value": normalise_ioc_value(i.ioc_value),
            "description": desc[:DESCRIPTION_CHARS] + (" […]" if len(desc) > DESCRIPTION_CHARS else ""),
        })
    return out, truncated


def validate_pairs(parsed: Any, iocs: list) -> list[dict[str, Any]]:
    """Coerce the model's answer to pairs of REAL ids in this case, minus
    exact duplicates, unordered-unique, confidence in [0, 1], capped."""
    if not isinstance(parsed, dict):
        return []
    raw = parsed.get("pairs")
    if not isinstance(raw, list):
        return []
    by_id = {int(i.ioc_id): i for i in iocs}
    keys = {int(i.ioc_id): (i.ioc_type_id, normalise_ioc_value(i.ioc_value)) for i in iocs}
    seen: set[tuple[int, int]] = set()
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        a, b = item.get("a"), item.get("b")
        if not isinstance(a, int) or not isinstance(b, int) or isinstance(a, bool) or isinstance(b, bool):
            continue
        if a == b or a not in by_id or b not in by_id:
            continue
        pk = (min(a, b), max(a, b))
        if pk in seen:
            continue
        if keys[a] == keys[b]:
            continue   # exact — find_exact owns it
        conf = item.get("confidence")
        if not isinstance(conf, (int, float)) or isinstance(conf, bool):
            continue
        conf = max(0.0, min(1.0, float(conf)))
        reason = item.get("reason")
        seen.add(pk)
        out.append({"a": pk[0], "b": pk[1], "confidence": round(conf, 3),
                    "reason": reason.strip()[:300] if isinstance(reason, str) else None})
    out.sort(key=lambda p: (-p["confidence"], p["a"], p["b"]))
    return out[:MAX_PAIRS]


def suggest_ioc_duplicates(case_id: int) -> dict[str, Any]:
    """Run the AI pass for one case. Returns
    {'pairs': [{ioc_a, ioc_b, confidence, reason}], 'model', 'ioc_count',
     'sent', 'truncated'} — ioc_a/ioc_b are the modal's brief rows."""
    from app.business.ioc_dedup import load_case_iocs
    from app.business.ioc_dedup import serialize_iocs
    from app.models.models import IocType

    iocs = load_case_iocs(case_id)
    if len(iocs) < 2:
        return {"pairs": [], "model": None, "ioc_count": len(iocs), "sent": len(iocs),
                "truncated": False}

    client = build_default_client(timeout=600.0, default_max_tokens=3000, feature='ioc_dedup')
    if client is None:
        raise IocDedupError(
            "AI backend is not configured (set AI_BACKEND_URL and AI_BACKEND_MODEL "
            "or configure it in Server Settings)")

    type_names = {t.type_id: t.type_name for t in IocType.query.all()}
    payload, truncated = build_payload(iocs, type_names)
    user_prompt = (
        "Find the pairs that are the same indicator in two notations. Exact duplicates "
        "are already removed from this list.\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"
    )
    app.logger.info(f"IocDedup: case #{case_id} requesting AI pass "
                    f"(model={client.model}, rows={len(payload)}, truncated={truncated})")
    try:
        response = client.chat([
            {"role": "system", "content": load_system_prompt()},
            {"role": "user", "content": user_prompt},
        ])
    except AIClientError as exc:
        raise IocDedupError(f"AI backend call failed: {exc}") from exc

    raw = client.extract_content(response).strip()
    if not raw:
        raise IocDedupError(
            "AI backend returned an empty response "
            f"(finish_reason={response.get('choices', [{}])[0].get('finish_reason')})")
    try:
        parsed = json.loads(_extract_json_block(raw))
    except json.JSONDecodeError as exc:
        detail = ' '.join(raw.split())[:200] or '<empty response>'
        raise IocDedupError(f"AI backend did not return JSON. Backend said: {detail}") from exc

    sent_ids = {p["id"] for p in payload}
    pairs = validate_pairs(parsed, [i for i in iocs if int(i.ioc_id) in sent_ids])
    ser = serialize_iocs(iocs)
    out_pairs = [{"ioc_a": ser[p["a"]], "ioc_b": ser[p["b"]],
                  "confidence": p["confidence"], "reason": p["reason"]}
                 for p in pairs]
    app.logger.info(f"IocDedup: case #{case_id} model proposed {len(out_pairs)} pair(s)")
    return {"pairs": out_pairs, "model": client.model, "ioc_count": len(iocs),
            "sent": len(payload), "truncated": truncated, "prompt_id": IOC_DEDUP_PROMPT_ID}

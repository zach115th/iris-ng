#  IRIS Source Code
#
#  Tier-1 MITRE ATT&CK technique-suggestion endpoint. Takes the free-text
#  content of a timeline event (title / description / source / category /
#  existing tags) and returns a small JSON list of suggested technique IDs
#  with confidence + one-sentence rationale per item.
#
#  Stateless: not persisted in case_ai_artifact. The analyst either accepts
#  the suggestion (which lands in event_tags as comma-separated technique
#  IDs and saves with the event) or discards it. Same input twice returns
#  the same model output (temperature=0.0); no DB cache needed.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app import app
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client


ATTACK_SUGGESTER_PROMPT_ID = "AttackSuggesterSystemPrompt-v2"  # v2: UKC phase added 2026-04-29
PROMPT_PATH = Path(__file__).parent.parent.parent / "resources" / "ai_prompts" / "attack_suggester.md"

# T1059, T1059.001, T1566.002, etc. Reject anything that isn't a real-shape
# Enterprise technique ID — guards against the model hallucinating tactic IDs
# (TA0001) or pasting platform names.
TECHNIQUE_ID_RE = re.compile(r"^T\d{4}(?:\.\d{3})?$")

# Unified Kill Chain v1.3 phase reference. Used to validate the model's
# `ukc_phase` output server-side: number must map to the canonical name,
# and the stage label must match. See docs/21-unified-kill-chain.md.
UKC_PHASES: dict[int, tuple[str, str]] = {
    1:  ("Reconnaissance",        "In"),
    2:  ("Resource Development",  "In"),
    3:  ("Delivery",              "In"),
    4:  ("Social Engineering",    "In"),
    5:  ("Exploitation",          "In"),
    6:  ("Persistence",           "In"),
    7:  ("Defense Evasion",       "In"),
    8:  ("Command & Control",     "In"),
    9:  ("Pivoting",              "Through"),
    10: ("Discovery",             "Through"),
    11: ("Privilege Escalation",  "Through"),
    12: ("Execution",             "Through"),
    13: ("Credential Access",     "Through"),
    14: ("Lateral Movement",      "Through"),
    15: ("Collection",            "Out"),
    16: ("Exfiltration",          "Out"),
    17: ("Impact",                "Out"),
    18: ("Objectives",            "Out"),
}


class AttackSuggesterError(Exception):
    """Raised when ATT&CK suggestion can't proceed."""


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[:limit] + " […]"


def _extract_json_block(content: str) -> str:
    """Strip optional ```json … ``` fences before parsing.

    Prompt forbids fences but the model occasionally adds them anyway.
    """
    stripped = content.strip()
    if stripped.startswith("```"):
        # Drop opening fence (with or without language tag) and trailing fence.
        stripped = re.sub(r"^```[a-zA-Z0-9]*\n?", "", stripped)
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


def _validate_technique(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    tid = item.get("id")
    if not isinstance(tid, str) or not TECHNIQUE_ID_RE.match(tid):
        return None
    confidence = item.get("confidence")
    if not isinstance(confidence, (int, float)):
        return None
    if confidence < 0.0 or confidence > 1.0:
        return None
    if confidence < 0.5:
        # Prompt says don't return below 0.5; enforce it server-side too.
        return None
    name = item.get("name")
    reason = item.get("reason")
    return {
        "id": tid,
        "name": name if isinstance(name, str) else None,
        "confidence": float(confidence),
        "reason": reason if isinstance(reason, str) else None,
    }


def _validate_ukc_phase(item: Any) -> dict[str, Any] | None:
    """Coerce the model's ukc_phase output to a known-good UKC entry.

    Trusts the canonical UKC_PHASES table for the name + stage; the model
    only has to get the number right. Anything outside 1–18 is dropped.
    """
    if not isinstance(item, dict):
        return None
    number = item.get("number")
    if not isinstance(number, int) or number not in UKC_PHASES:
        return None
    canonical_name, canonical_stage = UKC_PHASES[number]
    confidence = item.get("confidence")
    if isinstance(confidence, (int, float)) and 0.0 <= confidence <= 1.0:
        confidence = float(confidence)
    else:
        confidence = None
    reason = item.get("reason")
    return {
        "number": number,
        "name": canonical_name,
        "stage": canonical_stage,
        "confidence": confidence,
        "reason": reason if isinstance(reason, str) else None,
    }


def suggest_attack_techniques(
    *,
    title: str,
    content: str | None = None,
    source: str | None = None,
    category: str | None = None,
    existing_tags: str | None = None,
) -> dict[str, Any]:
    """Call the AI backend and return validated ATT&CK technique suggestions.

    Returns:
        {
          'techniques': [
            {'id': 'T1078', 'name': 'Valid Accounts', 'confidence': 0.85, 'reason': '…'},
            …
          ],
          'rationale': '…',
          'tags_string': 'T1078, T1059.001',  # ready to paste into event_tags
          'model': 'gpt-oss-20b',
        }
    """
    title = (title or "").strip()
    if not title and not (content or "").strip():
        raise AttackSuggesterError("Need at least a title or description to suggest techniques")

    client = build_default_client(timeout=60.0, default_max_tokens=800)
    if client is None:
        raise AttackSuggesterError(
            "AI backend is not configured (set AI_BACKEND_URL and AI_BACKEND_MODEL "
            "or configure it in Server Settings)"
        )

    system_prompt = load_system_prompt()

    payload = {
        "title": _truncate(title, 400),
        "description": _truncate(content, 4000),
        "source": _truncate(source, 400),
        "category": _truncate(category, 200),
        "existing_tags": _truncate(existing_tags, 400),
    }
    user_prompt = (
        "Event to map to MITRE ATT&CK Enterprise techniques.\n\n"
        f"```json\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n```"
    )

    app.logger.info(
        f"AttackSuggester: requesting suggestions (model={client.model}, "
        f"title_chars={len(payload['title'] or '')}, "
        f"desc_chars={len(payload['description'] or '')})"
    )

    try:
        response = client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])
    except AIClientError as exc:
        raise AttackSuggesterError(f"AI backend call failed: {exc}") from exc

    raw = client.extract_content(response).strip()
    if not raw:
        raise AttackSuggesterError(
            "AI backend returned an empty response "
            f"(finish_reason={response.get('choices', [{}])[0].get('finish_reason')})"
        )

    try:
        parsed = json.loads(_extract_json_block(raw))
    except json.JSONDecodeError as exc:
        app.logger.warning(f"AttackSuggester: model returned non-JSON content: {raw[:300]}")
        raise AttackSuggesterError(
            f"AI backend returned non-JSON content (parse error: {exc})"
        ) from exc

    raw_techs = parsed.get("techniques") if isinstance(parsed, dict) else None
    techniques: list[dict[str, Any]] = []
    if isinstance(raw_techs, list):
        seen_ids: set[str] = set()
        for item in raw_techs:
            validated = _validate_technique(item)
            if validated is None:
                continue
            if validated["id"] in seen_ids:
                continue
            seen_ids.add(validated["id"])
            techniques.append(validated)

    techniques.sort(key=lambda t: t["confidence"], reverse=True)
    techniques = techniques[:4]

    rationale = parsed.get("rationale") if isinstance(parsed, dict) else None
    if not isinstance(rationale, str):
        rationale = None

    ukc_phase = _validate_ukc_phase(parsed.get("ukc_phase")) if isinstance(parsed, dict) else None

    tags_string = ", ".join(t["id"] for t in techniques)

    ukc_summary = (
        f"UKC #{ukc_phase['number']} {ukc_phase['name']}" if ukc_phase else "UKC=none"
    )
    app.logger.info(
        f"AttackSuggester: returned {len(techniques)} techniques "
        f"({', '.join(t['id'] for t in techniques) or 'none'}); {ukc_summary}"
    )

    return {
        "techniques": techniques,
        "ukc_phase": ukc_phase,
        "rationale": rationale,
        "tags_string": tags_string,
        "model": client.model,
    }

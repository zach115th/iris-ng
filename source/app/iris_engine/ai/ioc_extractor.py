#  IRIS Source Code
#
#  Tier-1 IOC extraction. Takes the free-text body of a case note (or
#  any other free text) and returns suggested IOCs ready to be promoted
#  into the case's IOC inventory via POST /api/v2/cases/{id}/iocs.
#
#  Stateless: not persisted in case_ai_artifact. Same input twice → same
#  output (temperature=0.0); the analyst either accepts (creates a real
#  Ioc row) or dismisses. No round-trip through artifact storage.
#
#  Server-side validation:
#  - IOC type name must resolve to an IocType row (gives us type_id).
#  - Value must pass a per-type regex sanity check so the model can't
#    label `WS-FIN-07` as `ip-dst`.
#  - Confidence ≥ 0.5 (prompt says don't return below; we enforce too).
#  - Cap at 10 IOCs.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app import app
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client
from app.models.models import Ioc
from app.models.models import IocType
from app.models.models import Tlp


IOC_EXTRACTOR_PROMPT_ID = "IocExtractorSystemPrompt-v1"
PROMPT_PATH = Path(__file__).parent.parent.parent / "resources" / "ai_prompts" / "ioc_extractor.md"

# Default TLP for AI-suggested IOCs. Amber matches the IRIS GUI default
# for manually-created IOCs and is the safe-by-default choice for
# unreviewed indicators.
DEFAULT_TLP_NAME = "amber"

MAX_IOCS_RETURNED = 10
MIN_CONFIDENCE = 0.5

# Per-type regex sanity checks. Not exhaustive — misses are fine because
# the prompt also constrains the model — but catches obvious miscat
# (e.g. `WS-FIN-07` claimed as `ip-dst`). Types that map to free text
# (`text`, `other`, `account`, `target-*`) skip regex validation.
_IPV4 = r"(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)"
_IPV6 = r"(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}"
_IP = rf"(?:{_IPV4}|{_IPV6})"
_HOSTNAME_RE = r"(?=.{1,253}$)([a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)(?:\.(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?))+"

TYPE_VALIDATORS: dict[str, re.Pattern[str]] = {
    "ip-src":         re.compile(rf"^{_IP}$"),
    "ip-dst":         re.compile(rf"^{_IP}$"),
    "ip-any":         re.compile(rf"^{_IP}$"),
    "ip-src|port":    re.compile(rf"^{_IP}\|\d{{1,5}}$"),
    "ip-dst|port":    re.compile(rf"^{_IP}\|\d{{1,5}}$"),
    "domain":         re.compile(rf"^{_HOSTNAME_RE}$"),
    "hostname":       re.compile(rf"^{_HOSTNAME_RE}$"),
    "hostname|port":  re.compile(rf"^{_HOSTNAME_RE}\|\d{{1,5}}$"),
    "url":            re.compile(r"^https?://\S+$", re.IGNORECASE),
    "uri":            re.compile(r"^\S+$"),
    "email":          re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    "email-src":      re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    "email-dst":      re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    "md5":            re.compile(r"^[a-fA-F0-9]{32}$"),
    "sha1":           re.compile(r"^[a-fA-F0-9]{40}$"),
    "sha256":         re.compile(r"^[a-fA-F0-9]{64}$"),
    "sha512":         re.compile(r"^[a-fA-F0-9]{128}$"),
    "imphash":        re.compile(r"^[a-fA-F0-9]{32}$"),
    "pehash":         re.compile(r"^[a-fA-F0-9]{40}$"),
    "mac-address":    re.compile(r"^([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$"),
    "port":           re.compile(r"^\d{1,5}$"),
}


class IocExtractorError(Exception):
    """Raised when IOC extraction can't proceed."""


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


def _build_type_index() -> dict[str, int]:
    """{type_name: type_id} for every IocType row, lower-cased keys."""
    return {row.type_name.lower(): row.type_id for row in IocType.query.all()}


def _resolve_default_tlp_id() -> int | None:
    row = Tlp.query.filter(Tlp.tlp_name.ilike(DEFAULT_TLP_NAME)).first()
    return row.tlp_id if row else None


def _build_existing_set(case_id: int | None) -> set[tuple[int, str]]:
    """Existing case IOCs as {(type_id, value)} so we can flag duplicates.

    Matches the dedup key used by case_iocs_db.case_iocs_db_exists, which is
    case-sensitive on ioc_value. If `case_id` is None (caller is the bare
    orchestrator from a script), return an empty set — no dedup is fine.
    """
    if case_id is None:
        return set()
    rows = Ioc.query.with_entities(Ioc.ioc_type_id, Ioc.ioc_value).filter(
        Ioc.case_id == case_id
    ).all()
    return {(int(t), v) for t, v in rows if t is not None and v is not None}


def _validate_ioc(item: Any, type_index: dict[str, int]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    value = item.get("value")
    type_name = item.get("type")
    confidence = item.get("confidence")
    if not isinstance(value, str) or not value.strip():
        return None
    if not isinstance(type_name, str) or not type_name.strip():
        return None
    if not isinstance(confidence, (int, float)):
        return None
    if confidence < MIN_CONFIDENCE or confidence > 1.0:
        return None

    value = value.strip()
    type_lower = type_name.strip().lower()

    type_id = type_index.get(type_lower)
    if type_id is None:
        # Unknown IOC type → drop. Prompt explicitly says omit unsupported.
        return None

    validator = TYPE_VALIDATORS.get(type_lower)
    if validator is not None and not validator.match(value):
        # Shape mismatch — prompt says don't classify `WS-FIN-07` as an IP.
        return None

    return {
        "value": value,
        "type": type_lower,
        "type_id": type_id,
        "confidence": float(confidence),
        "reason": item.get("reason") if isinstance(item.get("reason"), str) else None,
        "noise_flag": item.get("noise_flag") if isinstance(item.get("noise_flag"), str) else None,
        "tags": item.get("tags") if isinstance(item.get("tags"), str) else "",
    }


def extract_iocs(text: str, case_id: int | None = None) -> dict[str, Any]:
    """Call the AI backend and return validated IOC suggestions.

    If `case_id` is given, each suggestion is also marked with
    `already_in_case: bool` by cross-checking against the case's existing
    `Ioc` rows on the same `(type_id, value)` key IRIS uses elsewhere.
    The UI is expected to disable / grey-out the `+ add` action for
    rows where this is True so the analyst doesn't trigger the
    `IOC with same value and type already exists` 400 from the
    downstream IOC create endpoint.

    Returns:
        {
          'iocs': [
            {value, type, type_id, tlp_id, tlp_name, confidence, reason,
             noise_flag, tags, already_in_case},
            ...  # 0..MAX_IOCS_RETURNED entries, sorted by confidence desc
          ],
          'rationale': str | None,
          'model': str,
          'default_tlp': {'id': int, 'name': str},
        }
    """
    text = (text or "").strip()
    if not text:
        raise IocExtractorError("Need note text to extract IOCs from")

    client = build_default_client(timeout=90.0, default_max_tokens=1500)
    if client is None:
        raise IocExtractorError(
            "AI backend is not configured (set AI_BACKEND_URL and AI_BACKEND_MODEL "
            "or configure it in Server Settings)"
        )

    system_prompt = load_system_prompt()

    payload_text = _truncate(text, 12000)
    user_prompt = (
        "Extract IOCs from the following note text.\n\n"
        f"```\n{payload_text}\n```"
    )

    app.logger.info(
        f"IocExtractor: requesting suggestions (model={client.model}, "
        f"text_chars={len(payload_text or '')})"
    )

    try:
        response = client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])
    except AIClientError as exc:
        raise IocExtractorError(f"AI backend call failed: {exc}") from exc

    raw = client.extract_content(response).strip()
    if not raw:
        raise IocExtractorError(
            "AI backend returned an empty response "
            f"(finish_reason={response.get('choices', [{}])[0].get('finish_reason')})"
        )

    try:
        parsed = json.loads(_extract_json_block(raw))
    except json.JSONDecodeError as exc:
        app.logger.warning(f"IocExtractor: model returned non-JSON content: {raw[:300]}")
        raise IocExtractorError(
            f"AI backend returned non-JSON content (parse error: {exc})"
        ) from exc

    type_index = _build_type_index()
    default_tlp_id = _resolve_default_tlp_id()
    existing = _build_existing_set(case_id)

    raw_iocs = parsed.get("iocs") if isinstance(parsed, dict) else None
    iocs: list[dict[str, Any]] = []
    if isinstance(raw_iocs, list):
        seen: set[tuple[str, str]] = set()
        for item in raw_iocs:
            validated = _validate_ioc(item, type_index)
            if validated is None:
                continue
            # In-response dedup (model returned the same IOC twice).
            in_response_key = (validated["type"], validated["value"].lower())
            if in_response_key in seen:
                continue
            seen.add(in_response_key)
            validated["tlp_id"] = default_tlp_id
            validated["tlp_name"] = DEFAULT_TLP_NAME if default_tlp_id else None
            # Cross-case dedup — match IRIS's case-sensitive (type_id, value).
            validated["already_in_case"] = (
                (validated["type_id"], validated["value"]) in existing
            )
            iocs.append(validated)

    iocs.sort(key=lambda i: i["confidence"], reverse=True)
    iocs = iocs[:MAX_IOCS_RETURNED]

    rationale = parsed.get("rationale") if isinstance(parsed, dict) else None
    if not isinstance(rationale, str):
        rationale = None

    dup_count = sum(1 for i in iocs if i.get("already_in_case"))
    app.logger.info(
        f"IocExtractor: returned {len(iocs)} IOCs "
        f"({dup_count} already in case) "
        f"({', '.join(i['value'] for i in iocs[:5]) or 'none'}"
        f"{'...' if len(iocs) > 5 else ''})"
    )

    return {
        "iocs": iocs,
        "rationale": rationale,
        "model": client.model,
        "default_tlp": {"id": default_tlp_id, "name": DEFAULT_TLP_NAME} if default_tlp_id else None,
    }

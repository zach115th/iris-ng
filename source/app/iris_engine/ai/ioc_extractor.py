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
from app.iris_engine.ai.sigma_grounding import find_matching_sigma_rules
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

# Route IOC extraction to a faster sibling model when the configured
# backend is a Claude family. IOC extraction is regex-validated structured
# output where Sigma RAG provides most of the context — Haiku handles it
# well at ~3-5x Sonnet's wall-clock. Same pattern as case_summary.py's
# SYNTHESIZER_FAST_MODEL_MAP. Backends not listed here pass through
# unchanged (LM Studio, OpenAI, etc.).
_IOC_EXTRACT_FAST_MODEL_MAP: dict[str, str] = {
    "claude-opus-4-7":   "claude-haiku-4-5",
    "claude-sonnet-4-6": "claude-haiku-4-5",
}

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

    # Pick a faster sibling for the IOC extraction call. IOC extraction is
    # a structured-output task (regex-validated per type) where Sigma-RAG
    # grounding does the heavy lifting — Haiku handles it well at ~3-5x the
    # speed of Sonnet. Same pattern as the case-summary synthesizer routing
    # in case_summary.py (SYNTHESIZER_FAST_MODEL_MAP). LM Studio / other
    # backends pass through unchanged.
    call_model = _IOC_EXTRACT_FAST_MODEL_MAP.get(client.model, client.model)

    system_prompt = load_system_prompt()

    payload_text = _truncate(text, 12000)

    # Sigma RAG grounding — pull matching detection rules so the model can
    # use the rules' `falsepositives` field to inform noise_flag decisions
    # ("rule says public DNS resolvers are common false positives" → flag
    # 8.8.8.8 / 1.1.1.1 as noise). The technique mix also hints at what
    # KIND of IOCs we expect (C2 rule → expect C2 domains/IPs; ransomware
    # rule → expect file-paths and ransom note titles; phishing rule →
    # expect lookalike domains and email addresses). Best-effort: empty
    # block if Pinecone isn't configured.
    sigma_matches = find_matching_sigma_rules(query_text=payload_text, top_k=4) if payload_text else []

    sigma_block = ""
    if sigma_matches:
        lines = [
            "## Sigma context (semantic-search matches from the Sigma rule index)",
            "",
            "These detection rules describe the activity in the note. Use them to:",
            "1. Bias noise_flag — if a Sigma rule's `falsepositives` field mentions",
            "   the IOC type as a known FP (CDN, public DNS, sinkhole, parked, RFC1918,",
            "   software-update endpoint), flag the candidate IOC accordingly.",
            "2. Inform what KIND of IOCs to look for (C2 → IPs/domains; ransomware →",
            "   file paths + ransom note names; phishing → lookalike domains + emails).",
            "",
        ]
        for i, m in enumerate(sigma_matches, 1):
            techs = ", ".join(m["techniques"]) if m["techniques"] else "(no ATT&CK tags)"
            title_str = m.get("title") or m.get("id") or "<unknown>"
            score = m.get("score") or 0.0
            lines.append(f"{i}. score={score:.3f}  {title_str}  →  {techs}")
            desc = m.get("description")
            if isinstance(desc, str) and desc.strip():
                lines.append(f"   desc: {_truncate(desc.strip(), 200)}")
            # The falsepositives field is the critical noise_flag signal.
            raw_meta = m.get("raw_metadata") or {}
            fps = raw_meta.get("falsepositives")
            if fps:
                if isinstance(fps, list):
                    fp_text = "; ".join(str(f) for f in fps if f)
                else:
                    fp_text = str(fps)
                if fp_text.strip():
                    lines.append(f"   falsepositives: {_truncate(fp_text.strip(), 240)}")
        sigma_block = "\n".join(lines) + "\n\n"

    user_prompt = (
        f"{sigma_block}"
        "## Note text — extract IOCs\n\n"
        f"```\n{payload_text}\n```"
    )

    app.logger.info(
        f"IocExtractor: requesting suggestions (configured_model={client.model}, "
        f"call_model={call_model}, text_chars={len(payload_text or '')}, "
        f"sigma_matches={len(sigma_matches)})"
    )

    try:
        response = client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ], model=call_model if call_model != client.model else None)
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
        "sigma_matches": [
            {
                "title": m.get("title"),
                "score": m.get("score"),
                "level": m.get("level"),
                "techniques": m.get("techniques"),
            }
            for m in sigma_matches
        ],
    }

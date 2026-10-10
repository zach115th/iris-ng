#  IRIS Source Code
#
#  LLM verifier for the verified executive summary (iris-ng, 2026-10-09).
#
#  Two passes over the writer's claims, both through json_reply.ask_json:
#    claims   - batches of claims, each with ONLY the case objects it cites;
#               the model returns supported / partially_supported /
#               unsupported / contradicted + whether the tier is overstated
#    document - every claim without sources + the chosen status; the model
#               returns internal contradictions and the known failure
#               patterns (a download described as a file, one IP as one
#               actor, a third-party figure as confirmed, an unsourced impact
#               number outside the impact section, relative time, a status
#               the claims do not support)
#  The verifier never edits a claim. Its verdicts become flags with the
#  severity table of summary_checks; the analyst resolves or dismisses them.
#  Nothing is ever recorded as verified by default: no backend for the role
#  -> `verifier_unavailable`, a transport error or a non-contract reply ->
#  `verifier_failed`, each with a HIGH pipeline flag. Batches that succeeded
#  keep their flags.
#
#  The role is the per-feature override `case_summary_verifier` (Settings ->
#  AI). With no pin the active backend verifies its own writer, which is a
#  weaker check; pin a different backend.

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from pathlib import Path
from typing import Any

from app import app
from app.iris_engine.ai.json_reply import ask_json
from app.iris_engine.ai.json_reply import truncation_hint
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client
from app.iris_engine.ai.summary_checks import DOCUMENT_PATTERN_CODES
from app.iris_engine.ai.summary_checks import Flag
from app.iris_engine.ai.summary_checks import RECORD_KEYS
from app.iris_engine.ai.summary_checks import make_flag

VERIFIER_FEATURE = "case_summary_verifier"
VERIFIER_CLAIMS_PROMPT_ID = "CaseSummaryVerifierClaims-v1"
VERIFIER_DOCUMENT_PROMPT_ID = "CaseSummaryVerifierDocument-v1"
# Budget = thinking + output: ten verdicts of one sentence each fit easily;
# a reasoning model spends ~2 800 tokens before its first word.
VERIFIER_MAX_TOKENS = 6000
BATCH_CLAIMS = 10
SOURCE_CHAR_CAP = 8000
BATCH_CHAR_CAP = 40000
VERDICTS = ("supported", "partially_supported", "unsupported", "contradicted")
VERDICT_CODES = {
    "contradicted": "CLAIM_CONTRADICTED",
    "unsupported": "CLAIM_UNSUPPORTED",
    "partially_supported": "CLAIM_PARTIALLY_SUPPORTED",
}
STATUS_VERIFIED = "verified"
STATUS_FAILED = "verifier_failed"
STATUS_UNAVAILABLE = "verifier_unavailable"
STATUS_DISABLED = "disabled"


def verifier_enabled() -> bool:
    """Settings > AI, "Verify executive summaries": NULL (a fresh install, a row
    that predates the column) and True mean on; only an explicit False is off.
    A missing settings row or table reads as on."""
    try:
        from app.models.models import ServerSettings
        row = ServerSettings.query.first()
    except Exception:
        return True
    if row is None:
        return True
    value = getattr(row, "ai_summary_verify", None)
    return True if value is None else bool(value)

PROMPTS_DIR = Path(__file__).parent.parent.parent / "resources" / "ai_prompts"

CLAIMS_COMPACT_SUFFIX = (
    "\n\nYour previous reply was cut off by the output limit before the JSON closed. "
    "Answer NOW with the JSON object only: one verdict per claim id, each reason at most "
    "ten words. No reasoning before the answer."
)
DOCUMENT_COMPACT_SUFFIX = (
    "\n\nYour previous reply was cut off by the output limit before the JSON closed. "
    "Answer NOW with the JSON object only: at most five contradictions and five patterns, "
    "each message at most ten words. No reasoning before the answer."
)


@dataclass
class VerifierResult:
    status: str
    flags: list[Flag] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def _load_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8")


def parse_json_object(raw: str) -> dict:
    """Fence-tolerant JSON object parse; raises when the text is not one."""
    text = (raw or "").strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("not a JSON object")
    return obj


def step_record(name: str, client, prompt_id: str | None, started: datetime, *, outcome: str = "ok",
                error: str | None = None, usage: Any = None, artifact_id: int | None = None,
                cached: bool = False, model: str | None = None) -> dict:
    """One audit row for case_summary_step, as a dict (the orchestrator
    persists every step of a pass in one transaction)."""
    return {
        "step": name,
        "provider": getattr(client, "provider", None) if client is not None else None,
        "backend_id": getattr(client, "backend_id", None) if client is not None else None,
        "backend_label": getattr(client, "backend_label", None) if client is not None else None,
        "model": model or (getattr(client, "model", None) if client is not None else None),
        "prompt_id": prompt_id,
        "artifact_id": artifact_id,
        "cached": bool(cached),
        "outcome": outcome,
        "error": (error or None) and str(error)[:4000],
        "usage_json": json.dumps(usage, default=str) if usage is not None else None,
        "started_at": started,
        "finished_at": datetime.utcnow(),
    }


def existing_refs(claim: dict, record: dict) -> list[dict]:
    out = []
    for ref in claim.get("source_refs") or []:
        bucket = record.get(RECORD_KEYS.get(ref.get("type"), ""), {}) or {}
        if ref.get("id") in bucket:
            out.append({"type": ref["type"], "id": ref["id"]})
    return out


def source_entry(ref: dict, record: dict) -> dict:
    src = record[RECORD_KEYS[ref["type"]]][ref["id"]]
    text = str(src.get("text") or src.get("search") or "")
    if len(text) > SOURCE_CHAR_CAP:
        text = text[:SOURCE_CHAR_CAP] + " […]"
    return {"type": ref["type"], "id": ref["id"], "label": src.get("label"), "text": text}


def claim_batches(claims: list[dict], record: dict) -> list[tuple[list[dict], dict[str, dict]]]:
    """[(claims, sources)] - only claims with at least one existing ref, at most
    BATCH_CLAIMS per batch, sources deduplicated per batch and the batch's
    source text capped at BATCH_CHAR_CAP (a claim whose sources alone exceed
    the cap still ships, alone)."""
    batches: list[tuple[list[dict], dict[str, dict]]] = []
    cur: list[dict] = []
    cur_sources: dict[str, dict] = {}
    cur_chars = 0
    for claim in claims:
        refs = existing_refs(claim, record)
        if not refs:
            continue
        entries = {f"{r['type']}:{r['id']}": source_entry(r, record) for r in refs}
        added = sum(len(e["text"]) for k, e in entries.items() if k not in cur_sources)
        if cur and (len(cur) >= BATCH_CLAIMS or cur_chars + added > BATCH_CHAR_CAP):
            batches.append((cur, cur_sources))
            cur, cur_sources, cur_chars = [], {}, 0
            added = sum(len(e["text"]) for e in entries.values())
        cur.append({"id": claim["id"], "section": claim.get("section"), "text": claim.get("text"),
                    "tier": claim.get("tier"), "source_refs": refs})
        for k, e in entries.items():
            if k not in cur_sources:
                cur_sources[k] = e
        cur_chars += added
    if cur:
        batches.append((cur, cur_sources))
    return batches


def claim_flags(claim: dict, verdict: Any, refs: list[dict]) -> list[Flag]:
    cid = claim.get("id")
    if not isinstance(verdict, dict):
        return [make_flag("VERIFIER_NO_VERDICT", cid, "The verifier returned no verdict for this claim",
                          source_refs=refs, source="verifier")]
    kind = str(verdict.get("verdict") or "").strip().lower()
    reason = str(verdict.get("reason") or "").strip()
    out: list[Flag] = []
    if kind not in VERDICTS:
        out.append(make_flag("VERIFIER_NO_VERDICT", cid, f"The verifier returned an unknown verdict \"{kind}\"",
                             source_refs=refs, source="verifier", detail={"verdict": verdict}))
        return out
    code = VERDICT_CODES.get(kind)
    if code:
        out.append(make_flag(code, cid, reason or f"The verifier judged this claim {kind.replace('_', ' ')}",
                             source_refs=refs, source="verifier", detail={"verdict": kind, "reason": reason}))
    if verdict.get("tier_overstated") is True:
        severity = "high" if claim.get("tier") == "confirmed" else "medium"
        out.append(make_flag("TIER_OVERSTATED", cid,
                             f"The tier \"{claim.get('tier')}\" overstates what the cited sources support"
                             + (f": {reason}" if reason and not code else ""),
                             source_refs=refs, source="verifier", severity=severity,
                             detail={"tier": claim.get("tier"), "reason": reason}))
    return out


def document_flags(parsed: dict, claims_by_id: dict[str, dict], record: dict) -> list[Flag]:
    out: list[Flag] = []

    def refs_for(ids: list[str]) -> list[dict]:
        seen, refs = set(), []
        for i in ids:
            for r in existing_refs(claims_by_id.get(i, {}), record):
                key = (r["type"], r["id"])
                if key not in seen:
                    seen.add(key)
                    refs.append(r)
        return refs

    def ids_of(entry: dict) -> list[str]:
        raw = entry.get("claim_ids")
        if isinstance(raw, str):
            raw = [raw]
        return [str(i) for i in (raw or []) if str(i) in claims_by_id]

    for entry in parsed.get("contradictions") or []:
        if not isinstance(entry, dict):
            continue
        ids = ids_of(entry)
        message = str(entry.get("message") or "Two claims contradict each other").strip()
        out.append(make_flag("DOC_CONTRADICTION", ids[0] if len(ids) == 1 else None,
                             message + (f" (claims {', '.join(ids)})" if len(ids) > 1 else ""),
                             source_refs=refs_for(ids), source="verifier", detail={"claim_ids": ids}))
    for entry in parsed.get("patterns") or []:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip().upper()
        if code not in DOCUMENT_PATTERN_CODES:
            app.logger.warning("Summary verifier emitted an unknown pattern code %r; ignored", code)
            continue
        ids = ids_of(entry)
        message = str(entry.get("message") or code.replace("_", " ").capitalize()).strip()
        if not ids:
            out.append(make_flag(code, None, message, source="verifier", detail={"claim_ids": []}))
            continue
        for i in ids:
            out.append(make_flag(code, i, message, source_refs=refs_for([i]), source="verifier",
                                 detail={"claim_ids": ids}))
    return out


def verify_summary(claims: list[dict], record: dict, *, status: str, is_closed: bool,
                   label: str = "case summary") -> VerifierResult:
    """Both verifier passes. Never raises for model trouble: the result's
    status and pipeline flags carry it."""
    started = datetime.utcnow()
    if not verifier_enabled():
        # Off is a decision, not a failure: no flag, the deterministic checks
        # still gate, and the run says so in its status + two skipped steps.
        err = "verifier switched off in Settings > AI"
        return VerifierResult(
            STATUS_DISABLED,
            flags=[],
            steps=[step_record("verifier:claims", None, VERIFIER_CLAIMS_PROMPT_ID, started, outcome="skipped", error=err),
                   step_record("verifier:document", None, VERIFIER_DOCUMENT_PROMPT_ID, started, outcome="skipped", error=err)],
            raw={"disabled": True})
    client = build_default_client(timeout=600.0, default_max_tokens=VERIFIER_MAX_TOKENS, feature=VERIFIER_FEATURE)
    if client is None:
        msg = ("No AI backend is available for the verifier role; the claims were not verified. "
               "Configure a backend (Settings > AI) and regenerate, or dismiss this flag with a reason.")
        return VerifierResult(
            STATUS_UNAVAILABLE,
            flags=[make_flag("VERIFIER_UNAVAILABLE", None, msg, source="pipeline")],
            steps=[step_record("verifier:claims", None, VERIFIER_CLAIMS_PROMPT_ID, started, outcome="skipped",
                               error="no backend for the verifier role"),
                   step_record("verifier:document", None, VERIFIER_DOCUMENT_PROMPT_ID, started, outcome="skipped",
                               error="no backend for the verifier role")],
            raw={})

    claims_by_id = {c["id"]: c for c in claims}
    flags: list[Flag] = []
    steps: list[dict] = []
    raw_claims: dict[str, Any] = {}
    raw_doc: Any = None
    failures: list[str] = []

    system_claims = _load_prompt("case_summary_verifier_claims.md")
    for batch_no, (batch, sources) in enumerate(claim_batches(claims, record), start=1):
        t0 = datetime.utcnow()
        user = ("Judge every claim below against ONLY its cited sources.\n\n```json\n"
                + json.dumps({"claims": batch, "sources": sources}, indent=2, ensure_ascii=False, default=str)
                + "\n```")
        try:
            reply = ask_json(client, [{"role": "system", "content": system_claims}, {"role": "user", "content": user}],
                             max_tokens=VERIFIER_MAX_TOKENS, compact_suffix=CLAIMS_COMPACT_SUFFIX,
                             parse=parse_json_object, log=app.logger,
                             label=f"{label}: verifier claims batch {batch_no}")
        except AIClientError as exc:
            failures.append(f"claims batch {batch_no}: {exc}")
            steps.append(step_record("verifier:claims", client, VERIFIER_CLAIMS_PROMPT_ID, t0, outcome="failed",
                                     error=str(exc)))
            continue
        verdicts = reply.parsed.get("verdicts") if isinstance(reply.parsed, dict) else None
        if not isinstance(verdicts, dict):
            err = "reply is not the verdict contract" + truncation_hint("Case Summary verifier", reply)
            failures.append(f"claims batch {batch_no}: {err}")
            steps.append(step_record("verifier:claims", client, VERIFIER_CLAIMS_PROMPT_ID, t0, outcome="failed",
                                     error=err, usage=reply.response.get("usage")))
            continue
        steps.append(step_record("verifier:claims", client, VERIFIER_CLAIMS_PROMPT_ID, t0,
                                 usage=reply.response.get("usage")))
        for c in batch:
            v = verdicts.get(c["id"])
            raw_claims[c["id"]] = v
            flags.extend(claim_flags(claims_by_id[c["id"]], v, c["source_refs"]))

    t0 = datetime.utcnow()
    system_doc = _load_prompt("case_summary_verifier_document.md")
    doc_payload = {
        "status": status,
        "is_closed": bool(is_closed),
        "claims": [{"id": c["id"], "section": c.get("section"), "text": c.get("text"), "tier": c.get("tier")}
                   for c in claims],
    }
    user = ("Read the whole briefing below for contradictions and the listed patterns.\n\n```json\n"
            + json.dumps(doc_payload, indent=2, ensure_ascii=False, default=str) + "\n```")
    try:
        reply = ask_json(client, [{"role": "system", "content": system_doc}, {"role": "user", "content": user}],
                         max_tokens=VERIFIER_MAX_TOKENS, compact_suffix=DOCUMENT_COMPACT_SUFFIX,
                         parse=parse_json_object, log=app.logger, label=f"{label}: verifier document pass")
        parsed = reply.parsed
        if (not isinstance(parsed, dict) or not isinstance(parsed.get("contradictions"), list)
                or not isinstance(parsed.get("patterns"), list)):
            err = "reply is not the document contract" + truncation_hint("Case Summary verifier", reply)
            failures.append(f"document pass: {err}")
            steps.append(step_record("verifier:document", client, VERIFIER_DOCUMENT_PROMPT_ID, t0, outcome="failed",
                                     error=err, usage=reply.response.get("usage")))
        else:
            raw_doc = parsed
            steps.append(step_record("verifier:document", client, VERIFIER_DOCUMENT_PROMPT_ID, t0,
                                     usage=reply.response.get("usage")))
            flags.extend(document_flags(parsed, claims_by_id, record))
    except AIClientError as exc:
        failures.append(f"document pass: {exc}")
        steps.append(step_record("verifier:document", client, VERIFIER_DOCUMENT_PROMPT_ID, t0, outcome="failed",
                                 error=str(exc)))

    if failures:
        flags.append(make_flag("VERIFIER_FAILED", None,
                               "The verifier did not complete: " + "; ".join(failures)[:1500]
                               + ". Regenerate, or dismiss this flag with a reason.",
                               source="pipeline", detail={"failures": failures}))
        return VerifierResult(STATUS_FAILED, flags=flags, steps=steps,
                              raw={"claims": raw_claims, "document": raw_doc, "failures": failures})
    return VerifierResult(STATUS_VERIFIED, flags=flags, steps=steps, raw={"claims": raw_claims, "document": raw_doc})


__all__ = ["VERIFIER_FEATURE", "VERIFIER_CLAIMS_PROMPT_ID", "VERIFIER_DOCUMENT_PROMPT_ID", "VERIFIER_MAX_TOKENS",
           "BATCH_CLAIMS", "SOURCE_CHAR_CAP", "BATCH_CHAR_CAP", "VERDICTS", "VERDICT_CODES", "STATUS_VERIFIED",
           "STATUS_FAILED", "STATUS_UNAVAILABLE", "STATUS_DISABLED", "verifier_enabled", "VerifierResult",
           "parse_json_object", "step_record",
           "existing_refs", "claim_batches", "claim_flags", "document_flags", "verify_summary"]

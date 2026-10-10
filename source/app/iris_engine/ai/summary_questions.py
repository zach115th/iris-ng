#  IRIS Source Code
#
#  Review questions for the verified executive summary (iris-ng, 2026-10-09).
#
#  Every flag a pass raises (deterministic check, verifier verdict, pipeline
#  note) is asked to the analyst as a QUESTION with concrete OPTIONS instead
#  of a blank reason box:
#    - one LLM call per pass on the verifier role (batched like the verifier)
#      proposes up to three options per flag, each an action the server can
#      apply exactly: rewrite the claim to a given sentence, lower its tier,
#      or drop it (for a document-level flag the option names the claim);
#    - the server appends the two fixed options "Keep as written" and
#      "Other" (free text), so free text is the last resort, never the default;
#    - with the verifier switched off, or when the call fails, a flag gets the
#      fixed options plus the code-only ones (lower the tier, drop).
#  `apply_answers()` is the pure core of the answers pass: it edits the claim
#  list exactly as answered, returns the instructions that need the writer
#  ("Other" answers) and the (claim, code) pairs the analyst confirmed so the
#  same deterministic flag is not asked twice.

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app import app
from app.iris_engine.ai.json_reply import ask_json
from app.iris_engine.ai.json_reply import truncation_hint
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client
from app.iris_engine.ai.summary_checks import TIERS
from app.iris_engine.ai.summary_verifier import SOURCE_CHAR_CAP
from app.iris_engine.ai.summary_verifier import VERIFIER_FEATURE
from app.iris_engine.ai.summary_verifier import VERIFIER_MAX_TOKENS
from app.iris_engine.ai.summary_verifier import existing_refs
from app.iris_engine.ai.summary_verifier import parse_json_object
from app.iris_engine.ai.summary_verifier import source_entry
from app.iris_engine.ai.summary_verifier import step_record
from app.iris_engine.ai.summary_verifier import verifier_enabled

QUESTIONS_PROMPT_ID = "CaseSummaryQuestions-v1"
QUESTIONS_MAX_TOKENS = VERIFIER_MAX_TOKENS
BATCH_FLAGS = 8
MAX_LLM_OPTIONS = 3
MAX_OPTION_CHARS = 600
LLM_ACTIONS = ("rewrite", "retier", "drop")
ACTIONS = LLM_ACTIONS + ("keep", "other")
TIER_RANK = {t: i for i, t in enumerate(TIERS)}          # confirmed < suspected < unverified < third_party_reported
PROMPTS_DIR = Path(__file__).parent.parent.parent / "resources" / "ai_prompts"

KEEP_OPTION = {"id": "keep", "action": "keep", "label": "Keep as written (I confirm it)"}
OTHER_OPTION = {"id": "other", "action": "other", "label": "Other (describe the change)"}

QUESTIONS_COMPACT_SUFFIX = (
    "\n\nYour previous reply was cut off by the output limit before the JSON closed. "
    "Answer NOW with the JSON object only: one question per flag id, at most two options each, "
    "every label and rewrite at most fifteen words. No reasoning before the answer."
)


class QuestionsResult:
    def __init__(self, questions: dict[int, dict[str, Any]], steps: list[dict], status: str, failures: list[str]):
        self.questions = questions      # flag_id -> {"question": str, "options": [...]}
        self.steps = steps
        self.status = status            # ok | failed | disabled | unavailable
        self.failures = failures


def _load_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _lower_tiers(tier: str | None) -> list[str]:
    rank = TIER_RANK.get(tier or "", -1)
    return [t for t in TIERS if TIER_RANK[t] > rank]


def fallback_question(flag: dict[str, Any], claim: dict[str, Any] | None) -> dict[str, Any]:
    """The question a flag gets without the model: the flag's message, and
    the code-only options (lower the tier, drop the claim) before the fixed
    two. A document-level flag gets the fixed two only."""
    options: list[dict[str, Any]] = []
    if claim is not None:
        lower = _lower_tiers(claim.get("tier"))
        if lower:
            options.append({"id": "o1", "action": "retier", "tier": lower[0],
                            "label": f"Lower the tier to {lower[0].replace('_', ' ')}"})
        options.append({"id": f"o{len(options) + 1}", "action": "drop", "label": "Drop this claim from the summary"})
    question = str(flag.get("message") or flag.get("code") or "").strip()
    if claim is not None:
        question += " How should this claim be handled?"
    else:
        question += " How should this be handled?"
    return {"question": question, "options": options + [dict(KEEP_OPTION), dict(OTHER_OPTION)]}


def validate_options(raw: Any, claim: dict[str, Any] | None, claims_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The model's options -> the server's contract. Unknown actions, empty
    rewrites, a tier that is not lower, an unknown claim id: dropped. At most
    MAX_LLM_OPTIONS survive, ids o1..oN; the fixed two are appended after."""
    out: list[dict[str, Any]] = []
    for item in (raw if isinstance(raw, list) else []):
        if not isinstance(item, dict) or len(out) >= MAX_LLM_OPTIONS:
            continue
        action = str(item.get("action") or "").strip().lower()
        if action not in LLM_ACTIONS:
            continue
        target_id = item.get("claim_id") if claim is None else claim.get("id")
        if claim is None:
            target_id = str(target_id or "").strip()
            if target_id not in claims_by_id:
                continue
        target = claims_by_id.get(target_id) if target_id else None
        label = " ".join(str(item.get("label") or "").split())[:MAX_OPTION_CHARS]
        opt: dict[str, Any] = {"action": action}
        if claim is None:
            opt["claim_id"] = target_id
        if action == "rewrite":
            text = " ".join(str(item.get("text") or "").split())[:MAX_OPTION_CHARS]
            if not text:
                continue
            opt["text"] = text
            opt["label"] = label or f"Rewrite as: {text}"
        elif action == "retier":
            tier = str(item.get("tier") or "").strip().lower()
            if target is None or tier not in _lower_tiers(target.get("tier")):
                continue
            opt["tier"] = tier
            opt["label"] = label or f"Lower the tier to {tier.replace('_', ' ')}"
        else:
            opt["label"] = label or "Drop this claim from the summary"
        opt["id"] = f"o{len(out) + 1}"
        out.append(opt)
    return out


def _flag_payload(flag: dict[str, Any], claim: dict[str, Any] | None, record: dict[str, Any]) -> dict[str, Any]:
    sources: dict[str, dict] = {}
    if claim is not None:
        for r in existing_refs(claim, record):
            sources[f"{r['type']}:{r['id']}"] = source_entry(r, record)
    detail = flag.get("detail") or {}
    return {
        "id": str(flag["id"]),
        "code": flag.get("code"),
        "severity": flag.get("severity"),
        "message": flag.get("message"),
        "related_claim_ids": detail.get("claim_ids") if isinstance(detail, dict) else None,
        "claim": ({"id": claim.get("id"), "section": claim.get("section"), "text": claim.get("text"),
                   "tier": claim.get("tier")} if claim is not None else None),
        "sources": sources,
    }


def build_questions(flags: list[dict[str, Any]], claims: list[dict[str, Any]], record: dict[str, Any], *,
                    label: str = "case summary") -> QuestionsResult:
    """One question + options per flag. `flags` are dicts with the persisted
    `id`, `code`, `severity`, `message`, `claim_id`, `detail`. Never raises for
    model trouble: a flag the model did not answer, a failed batch, a disabled
    or missing verifier role all fall back to fallback_question()."""
    started = datetime.utcnow()
    claims_by_id = {c["id"]: c for c in claims}
    questions: dict[int, dict[str, Any]] = {}
    steps: list[dict] = []
    failures: list[str] = []
    if not flags:
        return QuestionsResult({}, [], "ok", [])

    def fallback_all(status: str, err: str) -> QuestionsResult:
        for f in flags:
            questions[f["id"]] = fallback_question(f, claims_by_id.get(f.get("claim_id") or ""))
        steps.append(step_record("questions", None, QUESTIONS_PROMPT_ID, started, outcome="skipped", error=err))
        return QuestionsResult(questions, steps, status, [err])

    if not verifier_enabled():
        return fallback_all("disabled", "verifier switched off in Settings > AI; fixed options only")
    client = build_default_client(timeout=600.0, default_max_tokens=QUESTIONS_MAX_TOKENS, feature=VERIFIER_FEATURE)
    if client is None:
        return fallback_all("unavailable", "no backend for the verifier role; fixed options only")

    system = _load_prompt("case_summary_questions.md")
    for i in range(0, len(flags), BATCH_FLAGS):
        batch = flags[i:i + BATCH_FLAGS]
        t0 = datetime.utcnow()
        payload = {"flags": [_flag_payload(f, claims_by_id.get(f.get("claim_id") or ""), record) for f in batch],
                   "claims": [{"id": c["id"], "section": c.get("section"), "text": c.get("text"), "tier": c.get("tier")}
                              for c in claims]}
        user = ("Write one review question with concrete options for every flag below.\n\n```json\n"
                + json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n```")
        parsed = None
        try:
            reply = ask_json(client, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                             max_tokens=QUESTIONS_MAX_TOKENS, compact_suffix=QUESTIONS_COMPACT_SUFFIX,
                             parse=parse_json_object, log=app.logger,
                             label=f"{label}: questions batch {i // BATCH_FLAGS + 1}")
            parsed = reply.parsed.get("questions") if isinstance(reply.parsed, dict) else None
            if not isinstance(parsed, dict):
                err = "reply is not the questions contract" + truncation_hint("Case Summary questions", reply)
                failures.append(err)
                steps.append(step_record("questions", client, QUESTIONS_PROMPT_ID, t0, outcome="failed", error=err,
                                         usage=reply.response.get("usage")))
                parsed = None
            else:
                steps.append(step_record("questions", client, QUESTIONS_PROMPT_ID, t0, usage=reply.response.get("usage")))
        except AIClientError as exc:
            failures.append(str(exc))
            steps.append(step_record("questions", client, QUESTIONS_PROMPT_ID, t0, outcome="failed", error=str(exc)))
        for f in batch:
            claim = claims_by_id.get(f.get("claim_id") or "")
            entry = parsed.get(str(f["id"])) if parsed else None
            if not isinstance(entry, dict):
                questions[f["id"]] = fallback_question(f, claim)
                continue
            question = " ".join(str(entry.get("question") or "").split())[:MAX_OPTION_CHARS]
            options = validate_options(entry.get("options"), claim, claims_by_id)
            if not question or not options:
                fb = fallback_question(f, claim)
                question = question or fb["question"]
                options = options or fb["options"][:-2]
            questions[f["id"]] = {"question": question, "options": options + [dict(KEEP_OPTION), dict(OTHER_OPTION)]}
    return QuestionsResult(questions, steps, "failed" if failures else "ok", failures)


# ----- answers -------------------------------------------------------------------


def resolve_answer(options: list[dict[str, Any]], option_id: str, text: str | None,
                   claim_id: str | None) -> dict[str, Any]:
    """The stored answer for a chosen option. Raises ValueError for an unknown
    option, a missing text on "other", or a missing claim for an action that
    needs one."""
    opt = next((o for o in options if o.get("id") == option_id), None)
    if opt is None:
        raise ValueError(f"unknown option {option_id!r}")
    text = " ".join(str(text or "").split())
    answer: dict[str, Any] = {"option_id": option_id, "action": opt["action"], "label": opt.get("label")}
    target = opt.get("claim_id") or claim_id
    if opt["action"] == "other":
        if not text:
            raise ValueError("'Other' needs a short description of the change")
        answer["text"] = text
        answer["claim_id"] = target
    elif opt["action"] == "keep":
        if text:
            answer["note"] = text
    else:
        if not target:
            raise ValueError("this option needs a claim")
        answer["claim_id"] = target
        if opt["action"] == "rewrite":
            answer["text"] = opt["text"]
        elif opt["action"] == "retier":
            answer["tier"] = opt["tier"]
        if text:
            answer["note"] = text
    return answer


def apply_answers(claims: list[dict[str, Any]], answered: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure: the claim list after the answers, in flag order. Returns
    {claims, instructions, confirmed, changes}: `instructions` are the "Other"
    answers the writer must word ([{claim_id, text, flag_id}]); `confirmed` the
    (claim_id, code) pairs answered "keep" (the same deterministic flag is not
    asked again); `changes` a log line per applied answer. A later answer on
    the same claim wins over an earlier one; an answer on a dropped claim is
    ignored (logged)."""
    by_id = {c["id"]: json.loads(json.dumps(c)) for c in claims}
    order = [c["id"] for c in claims]
    dropped: set[str] = set()
    instructions: list[dict[str, Any]] = []
    confirmed: set[tuple[str | None, str]] = set()
    changes: list[dict[str, Any]] = []
    for f in answered:
        a = f.get("answer") or {}
        action = a.get("action")
        cid = a.get("claim_id") or f.get("claim_id")
        entry = {"flag_id": f.get("id"), "code": f.get("code"), "claim_id": cid, "action": action}
        if action == "keep":
            confirmed.add((f.get("claim_id"), f.get("code")))
            changes.append(entry)
            continue
        if action == "other":
            if cid and cid in dropped:
                changes.append({**entry, "skipped": "claim dropped by another answer"})
                continue
            instructions.append({"flag_id": f.get("id"), "claim_id": cid, "text": a.get("text"),
                                 "flag_message": f.get("message")})
            changes.append(entry)
            continue
        if not cid or cid not in by_id:
            changes.append({**entry, "skipped": "claim not in this pass"})
            continue
        if cid in dropped:
            changes.append({**entry, "skipped": "claim dropped by another answer"})
            continue
        if action == "rewrite":
            by_id[cid]["text"] = a.get("text") or by_id[cid]["text"]
        elif action == "retier":
            by_id[cid]["tier"] = a.get("tier") or by_id[cid]["tier"]
        elif action == "drop":
            dropped.add(cid)
        changes.append(entry)
    new_claims = [by_id[i] for i in order if i not in dropped]
    return {"claims": new_claims, "instructions": instructions, "confirmed": confirmed, "changes": changes,
            "dropped": sorted(dropped)}


__all__ = ["QUESTIONS_PROMPT_ID", "QUESTIONS_MAX_TOKENS", "BATCH_FLAGS", "MAX_LLM_OPTIONS", "ACTIONS", "LLM_ACTIONS",
           "KEEP_OPTION", "OTHER_OPTION", "QuestionsResult", "fallback_question", "validate_options",
           "build_questions", "resolve_answer", "apply_answers"]

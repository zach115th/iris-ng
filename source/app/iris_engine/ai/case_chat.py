#  IRIS Source Code
#
#  Tier-1 case-scoped chat assistant. Single-turn-or-multi-turn Q&A bound
#  to one case's data. The analyst asks free-form questions; the model
#  answers grounded in the case context (timeline, IOCs, assets).
#
#  Stateless on the server side for v0: each request carries any prior
#  conversation history from the client. No persistence yet — we may add a
#  case_ai_artifact row per turn (kind='chat_qa') for audit later.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app import app
from app.iris_engine.ai.case_summary import build_case_payload
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client
from app.models.cases import Cases


CHAT_PROMPT_DIR = Path(__file__).parent.parent.parent / "resources" / "ai_prompts"
DEFAULT_CHAT_PROMPT = CHAT_PROMPT_DIR / "case_chat.md"

# Explicit allowlist: variant key → fixed Path. User input is used only as a
# dict key — no path construction from tainted data, so py/path-injection is
# not applicable. Add an entry here when shipping a new tab-specific prompt.
_PROMPT_BY_VARIANT: dict[str, Path] = {
    "notes":    CHAT_PROMPT_DIR / "case_chat_notes.md",
    "timeline": CHAT_PROMPT_DIR / "case_chat_timeline.md",
    "ioc":      CHAT_PROMPT_DIR / "case_chat_ioc.md",
    "assets":   CHAT_PROMPT_DIR / "case_chat_assets.md",
    "tasks":    CHAT_PROMPT_DIR / "case_chat_tasks.md",
    "evidence": CHAT_PROMPT_DIR / "case_chat_evidence.md",
}


# Shared suffix appended to every variant: asks the model to close its reply
# with a delimited follow-up block, which split_followups() lifts out of the
# answer. One file, so the contract is stated once for all seven prompts.
FOLLOWUPS_PROMPT = CHAT_PROMPT_DIR / "case_chat_followups.md"
FOLLOWUPS_MARKER = "<<<FOLLOWUPS>>>"
# Reasoning models spend tokens BEFORE the visible answer (lfm-2.5 measured at
# ~1900 on a 43-IOC case, which left 88 of the old 2000 for the reply). Same
# budget the ICS draft pass settled on.
CHAT_MAX_TOKENS = 6000
MAX_FOLLOWUPS = 3
MAX_FOLLOWUP_LEN = 140

_FOLLOWUP_BULLET_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")
# Small models miscount the brackets (lfm-2.5-2.6b writes `<<<FOLLOWUPS>>`),
# so the marker is matched by shape, not byte-for-byte.
_FOLLOWUPS_MARKER_RE = re.compile(r"<{2,}\s*FOLLOW[-_ ]?UPS?\s*>{2,}", re.IGNORECASE)
# The contract at the top of the system prompt sits ~8k tokens of case JSON
# away from the question; measured on lfm-2.5-2.6b it is ignored there and
# honoured when restated on the current turn. Server-side only: the client's
# history keeps the analyst's own words.
FOLLOWUPS_REMINDER = (
    "\n\n(After your answer, finish with the " + FOLLOWUPS_MARKER + " block: that marker "
    "on its own line, then up to three follow-up questions I might ask you next about "
    "this case, one per line starting with \"- \".)"
)


class CaseChatError(Exception):
    """Raised when the chat assistant can't produce an answer."""


def load_system_prompt(variant: str | None = None) -> str:
    prompt = None
    if variant:
        v = variant.strip().lower()
        candidate = _PROMPT_BY_VARIANT.get(v)
        if candidate is not None and candidate.is_file():
            prompt = candidate.read_text(encoding="utf-8")
    if prompt is None:
        prompt = DEFAULT_CHAT_PROMPT.read_text(encoding="utf-8")
    if FOLLOWUPS_PROMPT.is_file():
        prompt = prompt.rstrip() + "\n" + FOLLOWUPS_PROMPT.read_text(encoding="utf-8")
    return prompt


def split_followups(
    content: str,
    *,
    asked: list[str] | None = None,
    truncated: bool = False
) -> tuple[str, list[str]]:
    """Split a chat reply into (answer, follow-up questions).

    The follow-up block is advisory chrome: a reply without the marker, with
    an empty block, or with nothing usable in it returns the answer untouched
    and an empty list. `asked` holds questions already put in this
    conversation (never offered again). `truncated` means the backend stopped
    on the token limit, so the last line may be cut mid-sentence — drop it.
    """
    text = content or ""
    markers = list(_FOLLOWUPS_MARKER_RE.finditer(text))
    if not markers:
        return text.strip(), []
    marker = markers[-1]

    answer = text[:marker.start()].rstrip()
    # The model often rules off the block; that rule belongs to the block.
    answer = re.sub(r"\n\s*(?:---+|\*\*\*+|___+)\s*$", "", answer).rstrip()

    lines = [ln for ln in text[marker.end():].splitlines() if ln.strip()]
    if truncated and lines:
        lines = lines[:-1]

    seen = {(q or "").strip().casefold() for q in (asked or [])}
    followups: list[str] = []
    for line in lines:
        # Chips render as plain text, so inline markdown would show literally.
        question = _FOLLOWUP_BULLET_RE.sub("", line).replace("`", "").replace("**", "")
        question = question.strip().strip("*_").strip()
        if not question or len(question) > MAX_FOLLOWUP_LEN:
            continue
        key = question.casefold()
        if key in seen:
            continue
        seen.add(key)
        followups.append(question)
        if len(followups) >= MAX_FOLLOWUPS:
            break

    return answer, followups


def _normalize_history(history: Any) -> list[dict[str, str]]:
    """Coerce a client-supplied history list into a clean role/content shape."""
    if not isinstance(history, list):
        return []
    out: list[dict[str, str]] = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role", "")).strip().lower()
        content = entry.get("content")
        if role not in ("user", "assistant"):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        # Cap any single message at ~8 KB to bound the prompt
        out.append({"role": role, "content": content[:8000]})
    # Cap total history at the most recent 10 turns
    return out[-10:]


def ask_case(
    case_id: int,
    question: str,
    *,
    history: list[dict[str, str]] | None = None,
    variant: str | None = None
) -> dict[str, Any]:
    """Ask the AI a question about a case. Returns a dict with the answer
    and the metadata needed by the UI (model, usage, generated_at).

    `variant` selects a tab-specific system prompt (e.g. 'notes', 'timeline',
    'iocs'). Falls back to the general case-chat prompt if the variant-specific
    file doesn't exist.
    """
    case = Cases.query.filter(Cases.case_id == case_id).first()
    if case is None:
        raise CaseChatError(f"Case #{case_id} not found")

    question = (question or "").strip()
    if not question:
        raise CaseChatError("Question is empty")

    client = build_default_client(timeout=600.0, default_max_tokens=CHAT_MAX_TOKENS, feature='case_chat')
    if client is None:
        raise CaseChatError(
            "AI backend is not configured (set AI_BACKEND_URL and AI_BACKEND_MODEL)"
        )

    system_prompt = load_system_prompt(variant)
    # Use the rich full-case payload — assets, IOCs, timeline, tasks AND notes
    # — so the analyst can ask about any of them. The earlier timeline-only
    # payload meant questions like "summarize the notes" returned a generic
    # case summary because notes were never in the prompt context.
    case_context = build_case_payload(case)
    case_context_json = json.dumps(case_context, indent=2, default=str)

    # Build the full message list:
    #   1) system prompt
    #   2) hidden anchor message containing the case JSON, framed as "context"
    #   3) prior conversation turns
    #   4) the new user question
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "system",
            "content": (
                "Below is the case context (JSON). Treat it as the only source of "
                "evidence. If the user asks something the context cannot answer, "
                "say so explicitly rather than speculating.\n\n"
                f"```json\n{case_context_json}\n```"
            )
        }
    ]
    messages.extend(_normalize_history(history))
    messages.append({"role": "user", "content": question[:8000] + FOLLOWUPS_REMINDER})

    app.logger.info(
        f"Case #{case_id}: chat question (model={client.model}, "
        f"variant={variant or 'default'}, "
        f"history_turns={len(_normalize_history(history))}, q_len={len(question)})"
    )

    try:
        response = client.chat(messages, max_tokens=CHAT_MAX_TOKENS)
    except AIClientError as exc:
        raise CaseChatError(f"AI backend call failed: {exc}") from exc

    finish_reason = response.get('choices', [{}])[0].get('finish_reason')
    asked = [h["content"] for h in _normalize_history(history) if h["role"] == "user"]
    asked.append(question)
    answer, followups = split_followups(
        client.extract_content(response),
        asked=asked,
        truncated=(finish_reason == "length")
    )
    if not answer:
        raise CaseChatError(
            "AI backend returned an empty response "
            f"(finish_reason={finish_reason})"
        )

    return {
        "case_id": case_id,
        "question": question,
        "answer": answer,
        "followups": followups,
        # The backend stopped on the token limit: the answer is incomplete and
        # the UI must say so rather than end mid-sentence.
        "truncated": finish_reason == "length",
        "model": client.model,
        "usage": response.get("usage"),
    }

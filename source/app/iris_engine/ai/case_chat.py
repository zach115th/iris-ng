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
from pathlib import Path
from typing import Any

from app import app
from app.iris_engine.ai.case_summary import build_case_payload
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client
from app.models.cases import Cases


CHAT_PROMPT_DIR = Path(__file__).parent.parent.parent / "resources" / "ai_prompts"
DEFAULT_CHAT_PROMPT = CHAT_PROMPT_DIR / "case_chat.md"

# Variant → prompt-file lookup. Each case-detail tab the chat bar is mounted
# on can supply its own variant; we load `case_chat_<variant>.md` and fall back
# to the general `case_chat.md` if the variant-specific file doesn't exist.
# Keep variant names simple, lowercase, no special chars — they're sanitized
# below before being used in a path.
_VARIANT_RE = __import__('re').compile(r'^[a-z][a-z0-9_-]{0,31}$')


class CaseChatError(Exception):
    """Raised when the chat assistant can't produce an answer."""


def load_system_prompt(variant: str | None = None) -> str:
    if variant:
        v = variant.strip().lower()
        if _VARIANT_RE.match(v):
            candidate = CHAT_PROMPT_DIR / f"case_chat_{v}.md"
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8")
    return DEFAULT_CHAT_PROMPT.read_text(encoding="utf-8")


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

    client = build_default_client(timeout=120.0, default_max_tokens=2000)
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
    messages.append({"role": "user", "content": question[:8000]})

    app.logger.info(
        f"Case #{case_id}: chat question (model={client.model}, "
        f"variant={variant or 'default'}, "
        f"history_turns={len(_normalize_history(history))}, q_len={len(question)})"
    )

    try:
        response = client.chat(messages, max_tokens=2000)
    except AIClientError as exc:
        raise CaseChatError(f"AI backend call failed: {exc}") from exc

    answer = client.extract_content(response).strip()
    if not answer:
        raise CaseChatError(
            "AI backend returned an empty response "
            f"(finish_reason={response.get('choices', [{}])[0].get('finish_reason')})"
        )

    return {
        "case_id": case_id,
        "question": question,
        "answer": answer,
        "model": client.model,
        "usage": response.get("usage"),
    }

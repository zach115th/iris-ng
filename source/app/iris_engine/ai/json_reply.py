#  IRIS Source Code
#
#  One chat call for a JSON-contract AI surface, with ONE compact retry when the
#  output limit cut the reply before its JSON closed (iris-ng, 2026-10-07).
#
#  Reasoning models (Kimi K3 on Bedrock, gpt-oss, DeepSeek R1) spend part of the
#  output budget thinking before they write. Two shapes follow from a budget
#  that is too small for the day's case: an EMPTY reply (the whole budget went
#  to thinking) and a NON-EMPTY reply whose JSON is cut mid-string. Several
#  orchestrators handled the first and reported the second as a plain parse
#  error ("did not return JSON", "returned no JSON object"). This helper treats
#  both the same way: finish_reason=length + no parseable JSON -> one retry
#  with a compact instruction appended to the user turn (answer first, fewer
#  and shorter items), same budget. A length stop whose JSON still closes is
#  an answer and is not retried; a non-JSON reply at a normal stop is a
#  refusal or prose and is an error straight away -- the two never share a
#  code path (CLAUDE.md, AI layer). The caller decides the error text; this
#  only reports what happened.

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import OpenAIClient

ParseFn = Callable[[str], Any]


@dataclass
class JsonReply:
    response: dict[str, Any]
    raw: str
    finish: str | None
    parsed: Any            # the parse function's result, or None when it did not parse
    retried: bool

    @property
    def truncated(self) -> bool:
        return self.finish == "length"


def parse_or_none(raw: str, parse: ParseFn) -> Any:
    """`parse(raw)`, or None when raw is empty or the parse raises anything."""
    if not raw:
        return None
    try:
        return parse(raw)
    except Exception:
        return None


def ask_json(
    client: OpenAIClient,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    compact_suffix: str,
    parse: ParseFn,
    log: logging.Logger,
    label: str,
) -> JsonReply:
    """Call `client.chat(messages, max_tokens=)`; retry ONCE with `compact_suffix`
    appended to the last user message when the output limit cut the reply before
    its JSON parsed (empty or truncated). Transport errors propagate as
    AIClientError for the caller to wrap in its own error type.
    """
    def _ask(msgs: list[dict[str, str]]) -> tuple[dict[str, Any], str, str | None, Any]:
        resp = client.chat(msgs, max_tokens=max_tokens)
        # The static method: every client (and every suite's fake) returns the
        # chat-completions envelope, so no instance method is needed to read it.
        raw = (OpenAIClient.extract_content(resp) or "").strip()
        finish = (resp.get("choices") or [{}])[0].get("finish_reason")
        return resp, raw, finish, parse_or_none(raw, parse)

    response, raw, finish, parsed = _ask(messages)
    retried = False
    if finish == "length" and parsed is None:
        log.warning(
            "%s: reply hit the output limit before the JSON closed (visible_chars=%d, usage=%s); "
            "retrying once with a compact instruction",
            label, len(raw), json.dumps(response.get("usage")),
        )
        response, raw, finish, parsed = _ask(with_compact_suffix(messages, compact_suffix))
        retried = True
    return JsonReply(response=response, raw=raw, finish=finish, parsed=parsed, retried=retried)


def with_compact_suffix(messages: list[dict[str, str]], suffix: str) -> list[dict[str, str]]:
    """A copy of `messages` with `suffix` appended to the LAST user turn -- the
    instruction has to sit on the current turn to move a reasoning model
    (CLAUDE.md: "a structured TAIL ... needs the instruction restated on the
    CURRENT turn"). With no user turn, a new one is appended."""
    out = [dict(m) for m in messages]
    for message in reversed(out):
        if message.get("role") == "user":
            message["content"] = (message.get("content") or "") + suffix
            return out
    out.append({"role": "user", "content": suffix.strip()})
    return out


def truncation_hint(surface: str, reply: JsonReply) -> str:
    """The parenthetical a caller appends to its parse error when the reply was
    cut by the output limit: names the retry when one happened and the lever
    (the per-feature Settings override) when both attempts truncated."""
    if reply.finish != "length":
        return ""
    if reply.retried:
        return (" (the reply hit the output limit twice, even with a compact instruction: point the "
                f"{surface}'s Settings override at a non-reasoning model)")
    return " (the reply hit the output limit)"


__all__ = ["AIClientError", "JsonReply", "ask_json", "parse_or_none", "truncation_hint", "with_compact_suffix"]

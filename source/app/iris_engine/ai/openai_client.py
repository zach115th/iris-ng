#  IRIS Source Code
#
#  OpenAI-compatible chat-completions client used by Tier-1 AI features.
#  urllib stdlib only — no new dependencies. Mirrors the pattern in
#  iris_misp_sync_module.ai_type_resolver but is generic (no allow-list,
#  no JSON-output validation) so any feature can call it.

from __future__ import annotations

import json
import logging
import re
from typing import Any
import urllib.error
import urllib.request

log = logging.getLogger(__name__)


class AIClientError(Exception):
    """Raised when the AI backend returns an error or unexpected response."""


class OpenAIClient:
    """Minimal OpenAI-compatible chat-completions client."""

    # ------------------------------------------------------------------
    # LFM (Liquid Foundation Model) control tokens — lfm-2.5 / lfm2.
    #
    # LFM frames its tool machinery with these sentinels. A small LFM
    # (2.6b) handed a JSON payload and asked to analyse it will often
    # decide the right move is to CALL A FUNCTION on that payload, and
    # emits e.g.
    #
    #   <|tool_call_start|>[analyze_target_event(target_event={...})]<|tool_call_end|>
    #
    # — even though no tools were offered in the request. That is not an
    # answer, it is the model echoing its own input back inside a call it
    # invented, and it must never reach an analyst or a cached artifact.
    #
    # Same treatment as the Gemma-4 channel markers and <think> blocks
    # below: strip here, in ONE place, so no orchestrator needs to know
    # which backend it is talking to.
    # ------------------------------------------------------------------
    _LFM_TOOL_BLOCK_RE = re.compile(
        r"<\|tool_(?:call|list|response)_start\|>.*?<\|tool_(?:call|list|response)_end\|>",
        re.DOTALL
    )
    # Truncated mid-call (hit max_tokens before the closing sentinel).
    _LFM_TOOL_OPEN_RE = re.compile(
        r"<\|tool_(?:call|list|response)_start\|>.*", re.DOTALL
    )
    # Chat-template framing that can leak into content on some hosts.
    _LFM_FRAME_RE = re.compile(r"<\|(?:im_start|im_end|startoftext|endoftext)\|>")

    _NO_TOOLS_NUDGE = (
        "No tools, functions or APIs are available to you. Do not emit tool "
        "calls or control tokens such as <|tool_call_start|>. Reply with the "
        "requested content directly, as plain text."
    )

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float = 600.0,
        default_max_tokens: int = 4000,
        default_temperature: float = 0.0
    ):
        if not base_url:
            raise AIClientError("AI base_url is empty")
        if not model:
            raise AIClientError("AI model is empty")

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.timeout = timeout
        self.default_max_tokens = default_max_tokens
        self.default_temperature = default_temperature

    def _post_chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        model: str | None = None
    ) -> dict[str, Any]:
        """One chat-completions round trip. Returns the raw envelope.

        `chat()` wraps this to add the tool-call retry; call this directly
        only when a retry would be wrong.

        `model` overrides the client's configured model for this call only —
        useful for caller-specific routing (e.g. case_summary uses Haiku for
        the synthesizer stage to skip Sonnet's slower per-token throughput
        on the 8-9 KB synthesis output, while keeping Sonnet for the
        specialist analyses upstream).        """
        body = json.dumps({
            "model": model if model is not None else self.model,
            "messages": messages,
            "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
            "temperature": temperature if temperature is not None else self.default_temperature
        }).encode("utf-8")

        request = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                err_body = exc.read().decode("utf-8")
            except Exception:
                err_body = ""
            raise AIClientError(
                f"AI backend returned HTTP {exc.code}: {err_body[:500]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise AIClientError(f"AI backend request failed: {exc}") from exc
        except TimeoutError as exc:
            # urllib only wraps a connection-establishment timeout as
            # URLError; a timeout while reading the response (backend
            # accepted the request but took too long to reply) raises a
            # bare TimeoutError that would otherwise escape uncaught here,
            # skip every caller's `except AIClientError`, and crash Flask
            # into its default HTML error page instead of a JSON error.
            raise AIClientError(f"AI backend request timed out after {self.timeout}s") from exc
        except json.JSONDecodeError as exc:
            raise AIClientError(f"AI backend returned non-JSON response: {exc}") from exc

        return payload

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        model: str | None = None
    ) -> dict[str, Any]:
        """Send a chat-completions request and return the parsed envelope.

        Retries ONCE when the model answered with nothing but a tool call.
        Small LFM models do this readily (see the control-token comment on
        the class): the reply is syntactically fine and semantically empty,
        so without the retry the surface either shows the raw call to an
        analyst or caches an artifact that contains no analysis. The retry
        is self-limiting — it only fires on a reply that already had no
        usable content, so the cost is bounded to one extra call on a
        response that was going to be discarded anyway.
        """
        payload = self._post_chat(
            messages, max_tokens=max_tokens, temperature=temperature, model=model
        )

        if self.is_tool_call_only(payload):
            log.warning(
                "AI backend (model=%s) replied with a tool call and no content; "
                "retrying once with tools explicitly disallowed",
                model if model is not None else self.model
            )
            payload = self._post_chat(
                self._with_no_tools_nudge(messages),
                max_tokens=max_tokens, temperature=temperature, model=model
            )

        return payload

    @classmethod
    def _with_no_tools_nudge(cls, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """Append the no-tools instruction to the first system message.

        Appending rather than inserting a trailing system message keeps the
        role ordering the backend was given originally — some OpenAI-compat
        hosts are strict about a system turn arriving last.
        """
        out = [dict(m) for m in messages]
        for message in out:
            if message.get("role") == "system":
                existing = message.get("content") or ""
                message["content"] = (existing + "\n\n" + cls._NO_TOOLS_NUDGE).strip()
                return out
        return [{"role": "system", "content": cls._NO_TOOLS_NUDGE}] + out

    @classmethod
    def is_tool_call_only(cls, payload: dict[str, Any]) -> bool:
        """True when the reply was a tool call carrying no usable content.

        Deliberately NOT "contains a tool call": a model that emits a call
        and then answers anyway has answered, and stripping leaves the
        answer behind. Only a reply that reduces to nothing is a non-answer.
        """
        try:
            raw = payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return False
        if "<|tool_" not in raw:
            return False
        try:
            return not cls.extract_content(payload)
        except AIClientError:
            return False

    @staticmethod
    def extract_content(payload: dict[str, Any]) -> str:
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise AIClientError(
                f"AI backend returned an unexpected envelope: {json.dumps(payload)[:500]}"
            ) from exc

        if content is None:
            content = ""

        # Strip reasoning/thinking blocks before returning to callers.
        #
        # Gemma-4 channel format: <|channel>thought … <|channel>output
        #   The model emits thinking in a "thought" channel then switches to
        #   an "output" channel for the actual response. Take everything after
        #   the last <|channel>output marker. If the output channel is empty
        #   (model finished thinking but produced no output tokens), fall back
        #   to scanning the thought channel for the last {...} JSON object —
        #   some Gemma-4 variants embed the final answer inside the thought.
        if "<|channel>output" in content:
            parts = content.split("<|channel>output")
            output_part = parts[-1].strip()
            if output_part:
                content = output_part
            else:
                # Output channel empty — scan thought content for JSON.
                thought = parts[0]
                if "<|channel>thought" in thought:
                    thought = thought.split("<|channel>thought", 1)[1]
                content = OpenAIClient._last_json_object(thought)
        elif content.strip().startswith("<|channel>"):
            # Truncated before reaching output channel; scan thought for JSON.
            thought = content
            if "<|channel>thought" in thought:
                thought = thought.split("<|channel>thought", 1)[1]
            content = OpenAIClient._last_json_object(thought)

        # DeepSeek R1 / Qwen-thinking / some Gemma variants: <think>…</think>
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
        # Unclosed <think> block (truncated mid-thinking).
        content = re.sub(r"<think>.*", "", content, flags=re.DOTALL)

        # LFM-2.5 / LFM2 tool framing. A call the model invented is not an
        # answer, so it comes out; anything it wrote alongside stays. When
        # the whole reply was a call this leaves "", which every caller
        # already treats as a failed generation — which is the point: it
        # must not be persisted as a cached artifact.
        content = OpenAIClient._LFM_TOOL_BLOCK_RE.sub("", content)
        content = OpenAIClient._LFM_TOOL_OPEN_RE.sub("", content)
        content = OpenAIClient._LFM_FRAME_RE.sub("", content)

        return content.strip()

    @staticmethod
    def _last_json_object(text: str) -> str:
        """Return the last balanced {...} block in text, or empty string.

        Used to extract a JSON object from reasoning-model thought channels
        that embed the final answer at the end of the thinking block rather
        than emitting it in a separate output channel.
        """
        # Walk backwards from the last } to find its matching {.
        pos = len(text) - 1
        while pos >= 0:
            if text[pos] == '}':
                depth = 0
                for i in range(pos, -1, -1):
                    if text[i] == '}':
                        depth += 1
                    elif text[i] == '{':
                        depth -= 1
                        if depth == 0:
                            return text[i:pos + 1]
                break
            pos -= 1
        return ""


def build_default_client(
    *,
    timeout: float = 600.0,
    default_max_tokens: int = 4000,
    feature: str | None = None
) -> OpenAIClient | None:
    """Construct a client from the active AI backend configuration.

    Resolution order (first non-empty wins):
      1. ServerSettings table (admin-editable via /manage/settings).
         If `feature` is given, check ai_feature_overrides[feature] for a
         per-feature slot override ('primary'|'alt') before falling back to
         the global ai_backend_active_slot radio.
         Slot-1 columns are ai_backend_{url,api_key,model}; slot-2 columns
         are ai_backend_alt_{url,api_key,model}.
      2. app.config (env vars at startup — bootstrap fallback before the
         settings row is populated; only seeds slot-1).

    Returns None when the AI backend is disabled or the active slot is not
    configured. Caller decides whether that's an error or a graceful skip.
    """
    from app import app

    enabled, base_url, api_key, model = _read_settings_row(feature=feature)

    if base_url is None or model is None:
        cfg = app.config
        base_url = base_url or (cfg.get("AI_BACKEND_URL") or "")
        api_key = api_key or (cfg.get("AI_BACKEND_API_KEY") or "")
        model = model or (cfg.get("AI_BACKEND_MODEL") or "")
        if enabled is None:
            enabled = bool(base_url and model)

    if not enabled or not base_url or not model:
        return None

    return OpenAIClient(
        base_url=base_url,
        api_key=api_key or "",
        model=model,
        timeout=timeout,
        default_max_tokens=default_max_tokens
    )


def _read_settings_row(
    feature: str | None = None
) -> tuple[bool | None, str | None, str | None, str | None]:
    """Pull AI backend config from the ServerSettings row.

    If `feature` is given and ai_feature_overrides[feature] is set to
    'primary' or 'alt', that slot takes precedence over the global
    ai_backend_active_slot radio. This lets admins route individual surfaces
    (e.g. 'case_summary') to a different backend without touching the global
    default.

    Returns (enabled, url, api_key, model). Any field can be None if the row
    or column doesn't exist yet (covers fresh installs / pre-migration boot)
    or if the selected slot has empty URL/model.
    """
    try:
        from app.models.models import ServerSettings
        row = ServerSettings.query.first()
    except Exception:
        return (None, None, None, None)

    if row is None:
        return (None, None, None, None)

    global_slot = (getattr(row, 'ai_backend_active_slot', None) or 'primary').strip().lower()

    # Per-feature override: if the admin pinned this feature to a specific slot,
    # use it; otherwise fall back to the global radio selection.
    slot = global_slot
    if feature:
        overrides = getattr(row, 'ai_feature_overrides', None) or {}
        feature_slot = (overrides.get(feature) or '').strip().lower()
        if feature_slot in ('primary', 'alt'):
            slot = feature_slot

    if slot == 'alt':
        url_attr, key_attr, model_attr = (
            'ai_backend_alt_url', 'ai_backend_alt_api_key', 'ai_backend_alt_model',
        )
    else:
        url_attr, key_attr, model_attr = (
            'ai_backend_url', 'ai_backend_api_key', 'ai_backend_model',
        )

    return (
        getattr(row, 'ai_backend_enabled', None),
        (getattr(row, url_attr, None) or '').strip() or None,
        (getattr(row, key_attr, None) or '').strip() or None,
        (getattr(row, model_attr, None) or '').strip() or None,
    )

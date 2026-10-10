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

# Backend providers a settings slot can name (ServerSettings.ai_backend_provider /
# ai_backend_alt_provider). NULL / unknown reads as PROVIDER_OPENAI so rows that
# predate the column keep their behaviour. The Bedrock adapter lives in
# bedrock_client.py and subclasses OpenAIClient so every orchestrator keeps
# consuming the chat-completions envelope.
#
# 'openai' is the OpenAI-COMPATIBLE shape (LM Studio, OpenRouter, vLLM, Ollama):
# `max_tokens` + `temperature`. 'openai_api' is OpenAI's own API (iris-ng,
# 2026-10-09): its current models reject `max_tokens` ("Use
# 'max_completion_tokens' instead") and its reasoning models reject any
# temperature but the default, so that subclass sends `max_completion_tokens`
# from the first call. Both shapes also self-heal: a 400 that names one of the
# two fields is retried once with the field swapped / dropped and the lesson is
# remembered per (base_url, model) for the life of the process (see
# learned_adaptations), so a gateway that fronts OpenAI works without the admin
# knowing which shape it wants.
PROVIDER_OPENAI = "openai"
PROVIDER_OPENAI_API = "openai_api"
PROVIDER_BEDROCK = "bedrock"
KNOWN_PROVIDERS = (PROVIDER_OPENAI, PROVIDER_OPENAI_API, PROVIDER_BEDROCK)

# Request-shape adaptations learned from a backend's 400s. Clients are built
# per request, so a per-instance memory (what the Bedrock adapter keeps for its
# temperature rejection) would re-pay one wasted call per specialist on every
# summary; this map is process-wide (one per gunicorn / celery worker), keyed by
# (base_url, effective model), bounded, and cleared only by a restart or
# forget_adaptations() (suites).
ADAPT_MAX_COMPLETION_TOKENS = "max_completion_tokens"
ADAPT_NO_TEMPERATURE = "no_temperature"
_LEARNED_ADAPTATIONS: dict[tuple[str, str], frozenset[str]] = {}
_LEARNED_CAP = 256


def learned_adaptations(base_url: str, model: str) -> frozenset[str]:
    """The adaptation flags learned for this (base_url, model) in this process."""
    return _LEARNED_ADAPTATIONS.get((base_url, model), frozenset())


def remember_adaptation(base_url: str, model: str, flag: str) -> bool:
    """Record `flag` for (base_url, model); True when it is new. The map is
    bounded: a new key beyond the cap starts the map over (a bound, not an LRU --
    a worker talks to a handful of backends, the cap exists so a hostile model
    list cannot grow it without limit)."""
    key = (base_url, model)
    have = _LEARNED_ADAPTATIONS.get(key, frozenset())
    if flag in have:
        return False
    if key not in _LEARNED_ADAPTATIONS and len(_LEARNED_ADAPTATIONS) >= _LEARNED_CAP:
        _LEARNED_ADAPTATIONS.clear()
    _LEARNED_ADAPTATIONS[key] = have | {flag}
    return True


def forget_adaptations() -> None:
    """Drop every learned adaptation (suites; a restart does the same)."""
    _LEARNED_ADAPTATIONS.clear()


_ERR_PARAM_RE = re.compile(r'"param"\s*:\s*"([^"]*)"')
_ERR_MESSAGE_RE = re.compile(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)')
_HTTP_400_PREFIX = "AI backend returned HTTP 400"


def classify_rejection(exc: AIClientError) -> str | None:
    """Which request field a backend's 400 rejected: 'max_tokens' (the backend
    wants `max_completion_tokens`), 'temperature' (the model takes only its
    default), or None for every other error.

    Reads the chat-completions error envelope OpenAI and the gateways that
    front it return ({"error": {"message", "type", "param", "code"}}) out of the
    AIClientError text http_json builds (`HTTP 400: <body[:500]>`) with regexes,
    so a truncated body still classifies. Only a 400 qualifies: a 5xx or a
    transport error that happens to mention a field is not a rejection of it.
    """
    text = str(exc)
    if not text.startswith(_HTTP_400_PREFIX):
        return None
    param_match = _ERR_PARAM_RE.search(text)
    param = param_match.group(1) if param_match else ""
    message_match = _ERR_MESSAGE_RE.search(text)
    message = message_match.group(1) if message_match else ""
    if param == "max_tokens" or "'max_tokens' is not supported" in message:
        if "max_completion_tokens" in message:
            return "max_tokens"
    if param == "temperature" or re.search(r"'temperature'[^\"]*(?:not support|unsupported)", message):
        return "temperature"
    return None


class AIClientError(Exception):
    """Raised when the AI backend returns an error or unexpected response."""


def http_post_json(url: str, headers: dict[str, str], body: bytes, timeout: float) -> dict[str, Any]:
    """POST a JSON body and return the parsed JSON reply (see http_json)."""
    return http_json("POST", url, headers, body, timeout)


def http_json(method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> dict[str, Any]:
    """One JSON round trip and the parsed reply.

    The one place transport errors become AIClientError, shared by the
    chat-completions client and the Bedrock adapter (Converse POSTs and the
    inference-profile listing GETs) so every caller sees the same message
    shapes.
    """
    request = urllib.request.Request(url=url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
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
        raise AIClientError(f"AI backend request timed out after {timeout}s") from exc
    except json.JSONDecodeError as exc:
        raise AIClientError(f"AI backend returned non-JSON response: {exc}") from exc


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
        # Provenance of the configured backend this client was built from:
        # build_default_client() fills them in, a hand-built client keeps None.
        # The verified-summary audit trail records them per pipeline step.
        self.backend_id: int | None = None
        self.backend_label: str | None = None
        self.provider: str | None = None

    # The output-limit field this shape sends by default. The OpenAI-compatible
    # shape says `max_tokens`; OpenAIApiClient says `max_completion_tokens`.
    # Either way a learned adaptation for the (base_url, model) wins.
    MAX_TOKENS_PARAM = "max_tokens"

    def request_shape(self, model: str) -> tuple[str, bool]:
        """(output-limit field name, whether to send temperature) for `model`
        on this base_url: the class default, then what this process learned."""
        learned = learned_adaptations(self.base_url, model)
        tokens_param = (
            ADAPT_MAX_COMPLETION_TOKENS
            if (self.MAX_TOKENS_PARAM == ADAPT_MAX_COMPLETION_TOKENS or ADAPT_MAX_COMPLETION_TOKENS in learned)
            else "max_tokens"
        )
        return tokens_param, ADAPT_NO_TEMPERATURE not in learned

    def _send(self, body: dict[str, Any]) -> dict[str, Any]:
        return http_post_json(
            f"{self.base_url}/chat/completions",
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            json.dumps(body).encode("utf-8"),
            self.timeout
        )

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
        specialist analyses that feed it).

        Self-healing request shape (2026-10-09): OpenAI's current models
        reject `max_tokens` (they want `max_completion_tokens`) and its
        reasoning models reject any temperature but the default. A 400 that
        names one of those fields is retried once with the field swapped /
        dropped -- at most one retry per field, so at most two extra calls
        -- and the lesson is remembered process-wide for the (base_url,
        model) so the next client built for it sends the right shape first.
        Every other error is raised as-is.
        """
        model_id = model if model is not None else self.model
        limit = max_tokens if max_tokens is not None else self.default_max_tokens
        temp = temperature if temperature is not None else self.default_temperature
        tokens_param, send_temperature = self.request_shape(model_id)
        while True:
            body: dict[str, Any] = {"model": model_id, "messages": messages, tokens_param: limit}
            if send_temperature:
                body["temperature"] = temp
            try:
                return self._send(body)
            except AIClientError as exc:
                rejected = classify_rejection(exc)
                if rejected == "max_tokens" and tokens_param == "max_tokens":
                    tokens_param = ADAPT_MAX_COMPLETION_TOKENS
                    remember_adaptation(self.base_url, model_id, ADAPT_MAX_COMPLETION_TOKENS)
                    log.warning(
                        "AI backend (model=%s) rejected max_tokens; resending with "
                        "max_completion_tokens and remembering it for this backend", model_id
                    )
                    continue
                if rejected == "temperature" and send_temperature:
                    send_temperature = False
                    remember_adaptation(self.base_url, model_id, ADAPT_NO_TEMPERATURE)
                    log.warning(
                        "AI backend (model=%s) rejected an explicit temperature; resending "
                        "without it and remembering it for this backend", model_id
                    )
                    continue
                raise

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

    The slot's provider picks the class: 'openai' (default) builds this
    chat-completions client, 'bedrock' the Converse adapter. Both expose the
    same chat()/extract_content() contract and the same envelope.
    """
    from app import app

    enabled, backend = _resolve_backend(feature=feature)
    base_url, api_key, model, provider = _backend_fields(backend)
    backend_id = backend.id if backend is not None else None
    backend_label = ((backend.label or '').strip() or None) if backend is not None else None

    if base_url is None or model is None:
        cfg = app.config
        base_url = base_url or (cfg.get("AI_BACKEND_URL") or "")
        api_key = api_key or (cfg.get("AI_BACKEND_API_KEY") or "")
        model = model or (cfg.get("AI_BACKEND_MODEL") or "")
        if enabled is None:
            enabled = bool(base_url and model)

    if not enabled or not base_url or not model:
        return None

    client = client_class_for(provider)(
        base_url=base_url,
        api_key=api_key or "",
        model=model,
        timeout=timeout,
        default_max_tokens=default_max_tokens
    )
    # Provenance for audit trails: the row's id + label, or 'config' when the
    # bootstrap env vars built the client (no row yet).
    client.backend_id = backend_id
    client.backend_label = backend_label if backend is not None else 'config'
    client.provider = (provider or PROVIDER_OPENAI).strip().lower()
    return client


def client_class_for(provider: str | None) -> type[OpenAIClient]:
    """Map a slot's provider value to the client class.

    NULL / empty = the chat-completions client (rows that predate the
    provider column). An unknown value cannot reach the DB through the
    schema's OneOf, so it is a hand-edited row: fall back to the default and
    say so in the log rather than fail every AI surface.
    """
    key = (provider or PROVIDER_OPENAI).strip().lower()
    if key == PROVIDER_BEDROCK:
        from app.iris_engine.ai.bedrock_client import BedrockConverseClient
        return BedrockConverseClient
    if key == PROVIDER_OPENAI_API:
        return OpenAIApiClient
    if key != PROVIDER_OPENAI:
        log.warning("Unknown AI backend provider %r; using the OpenAI-compatible client", provider)
    return OpenAIClient


class OpenAIApiClient(OpenAIClient):
    """OpenAI's own API (api.openai.com and its regional hosts): the same
    chat-completions envelope, but the output limit is `max_completion_tokens`
    from the first call -- OpenAI's current models reject `max_tokens`. The
    temperature fallback is inherited: the reasoning models reject any value
    but their default, the first 400 teaches the process to drop the field.
    Like Bedrock's `maxTokens`, `max_completion_tokens` counts reasoning
    tokens, which is what json_reply.ask_json's budgets and compact retry are
    sized for."""

    MAX_TOKENS_PARAM = ADAPT_MAX_COMPLETION_TOKENS


def _resolve_backend(
    feature: str | None = None
):
    """(enabled, AiBackend row | None) for a feature (iris-ng, 2026-10-09).

    The backend is ai_backend_active_id unless `feature` is given and
    ai_feature_overrides[feature] names another existing backend id (an id that
    no longer exists falls back to the active one; the delete route clears such
    pins, this is belt and braces). This lets admins route individual surfaces
    (e.g. 'case_summary', 'case_summary_verifier') to a different backend
    without touching the global default.

    `enabled` is None when the settings row / table / column does not exist yet
    (fresh installs, pre-migration boot); the row is None when no backend is
    configured or the lookup failed.
    """
    try:
        from app.models.models import AiBackend
        from app.models.models import ServerSettings
        row = ServerSettings.query.first()
    except Exception:
        return (None, None)

    if row is None:
        return (None, None)

    enabled = getattr(row, 'ai_backend_enabled', None)
    backend = None
    try:
        if feature:
            overrides = getattr(row, 'ai_feature_overrides', None) or {}
            pinned = _backend_id(overrides.get(feature))
            if pinned is not None:
                backend = AiBackend.query.get(pinned)
        if backend is None:
            active = _backend_id(getattr(row, 'ai_backend_active_id', None))
            if active is not None:
                backend = AiBackend.query.get(active)
    except Exception:
        return (enabled, None)
    return (enabled, backend)


def _backend_fields(backend) -> tuple[str | None, str | None, str | None, str | None]:
    """(url, api_key, model, provider) of a row, each None when blank or when
    there is no row."""
    if backend is None:
        return (None, None, None, None)
    return (
        (backend.url or '').strip() or None,
        (backend.api_key or '').strip() or None,
        (backend.model or '').strip() or None,
        (backend.provider or '').strip().lower() or None,
    )


def _read_settings_row(
    feature: str | None = None
) -> tuple[bool | None, str | None, str | None, str | None, str | None]:
    """(enabled, url, api_key, model, provider) -- the 5-tuple contract every
    orchestrator and suite knows, now a thin wrapper over _resolve_backend()."""
    enabled, backend = _resolve_backend(feature=feature)
    return (enabled, *_backend_fields(backend))


def _backend_id(value) -> int | None:
    """An ai_backend id out of an override / pointer value: int or digit string;
    anything else (None, '', the legacy 'primary' / 'alt') is None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None

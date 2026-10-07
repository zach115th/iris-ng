#  IRIS Source Code
#
#  AWS Bedrock adapter for the Tier-1 AI features (iris-ng, 2026-10-07).
#
#  Bedrock's OpenAI-compatible route (/openai/v1/chat/completions) does not
#  serve Anthropic models on bedrock-runtime (the model cards list Chat
#  Completions as not supported), so the one HTTP surface that covers every
#  provider an admin can put behind an inference profile -- Claude, GLM, Kimi,
#  Qwen, GPT -- is the Converse API:
#
#      POST https://bedrock-runtime.<region>.amazonaws.com/model/<modelId>/converse
#      Authorization: Bearer <Bedrock API key>
#
#  This adapter subclasses OpenAIClient and overrides ONE method, the round
#  trip. Request: the chat-completions message list becomes Converse's
#  `system` array + alternating `messages` with text blocks; max_tokens /
#  temperature become `inferenceConfig`. Response: Converse's
#  `output.message.content[].text` + `stopReason` + `usage` are folded back
#  into the chat-completions envelope ({choices[0].message.content,
#  finish_reason, usage}) so the twenty orchestrators that read that shape --
#  and OpenAIClient.extract_content(), the tool-call retry, the reasoning-block
#  stripping -- stay untouched.
#
#  No `guardrailConfig` is ever sent: IRIS applies no Bedrock Guardrail of its
#  own. A `guardrail_intervened` stop can therefore only come from an
#  account-level policy; it and the provider's own `content_filtered` are
#  raised as errors, never returned as content, so a refusal is never cached
#  as an artifact (feedback_never_cache_failed_ai_calls).
#
#  urllib stdlib only -- no boto3, no SigV4. Credentials are a Bedrock API key
#  (long-term for an unattended server; short-term keys expire within 12 h).

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote, unquote, urlencode, urlsplit

from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import OpenAIClient
from app.iris_engine.ai.openai_client import PROVIDER_BEDROCK
from app.iris_engine.ai.openai_client import http_json
from app.iris_engine.ai.openai_client import http_post_json

log = logging.getLogger(__name__)

# An AWS region code: us-west-2, us-gov-west-1, ap-southeast-7, eu-central-2.
REGION_RE = re.compile(r"^[a-z]{2}(?:-[a-z]+)+-\d$")

# Inference-profile catalog entry shape persisted in
# ServerSettings.ai_backend_model_catalog / ai_backend_alt_model_catalog:
#   {"id": <what goes in the Converse path>, "name": <inferenceProfileName>,
#    "type": "APPLICATION" | "SYSTEM_DEFINED", "model": <foundation model id>}
CATALOG_TYPES = ("APPLICATION", "SYSTEM_DEFINED")


def resolve_endpoint(value: str) -> tuple[str, str | None, str | None]:
    """The slot's URL/Region field -> (runtime base URL, control-plane base URL, region).

    A bare region ("us-west-2") builds both AWS hosts; a full URL is taken
    as the runtime base verbatim (VPC / private endpoints) and the control
    plane is derived only when the host follows the public
    `bedrock-runtime.<region>.<suffix>` pattern -- otherwise None, and the
    catalog listing reports that it needs a region. Garbage raises.
    """
    raw = (value or "").strip().rstrip("/")
    if not raw:
        raise AIClientError("Bedrock region is empty")
    if "://" not in raw:
        region = raw.lower()
        if not REGION_RE.match(region):
            raise AIClientError(
                f"'{raw}' is neither an AWS region code (e.g. us-west-2) nor an https:// endpoint URL"
            )
        return (f"https://bedrock-runtime.{region}.amazonaws.com",
                f"https://bedrock.{region}.amazonaws.com",
                region)
    parts = urlsplit(raw)
    if parts.scheme not in ("https", "http") or not parts.netloc:
        raise AIClientError(f"'{raw}' is not a usable Bedrock endpoint URL")
    host = parts.netloc.lower()
    m = re.match(r"^bedrock-runtime\.([a-z0-9-]+)\.(.+)$", host)
    if m:
        region = m.group(1)
        control = f"{parts.scheme}://bedrock.{region}.{m.group(2)}"
        return (raw, control, region)
    return (raw, None, None)


def list_inference_profiles(region_or_url: str, api_key: str, *, timeout: float = 30.0) -> list[dict[str, Any]]:
    """Every inference profile the key can see, application profiles first.

    GET {control}/inference-profiles?typeEquals=APPLICATION|SYSTEM_DEFINED,
    paginated on nextToken. Application profiles are addressed by ARN (the
    short id alone does not route), system-defined ones by their id
    (`us.anthropic.claude-sonnet-5-5`) -- both are valid Converse modelIds.
    `model` is the foundation model behind the profile, for display.
    """
    _, control, _ = resolve_endpoint(region_or_url)
    if not control:
        raise AIClientError(
            "Listing inference profiles needs a region (or a public bedrock-runtime.<region> URL)"
        )
    if not (api_key or "").strip():
        raise AIClientError("Bedrock API key is empty")
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    out: list[dict[str, Any]] = []
    for ptype in CATALOG_TYPES:
        token = None
        while True:
            params = {"maxResults": "1000", "typeEquals": ptype}
            if token:
                params["nextToken"] = token
            page = http_json("GET", f"{control}/inference-profiles?{urlencode(params)}", headers, None, timeout)
            for s in page.get("inferenceProfileSummaries") or []:
                if not isinstance(s, dict):
                    continue
                arn = s.get("inferenceProfileArn") or ""
                pid = s.get("inferenceProfileId") or ""
                ident = arn if ptype == "APPLICATION" else (pid or arn)
                if not ident:
                    continue
                models = s.get("models") or []
                model_arn = (models[0].get("modelArn") if models and isinstance(models[0], dict) else "") or ""
                out.append({
                    "id": ident,
                    "name": s.get("inferenceProfileName") or pid or ident,
                    "type": ptype,
                    "model": model_arn.rsplit("/", 1)[-1] if model_arn else None,
                })
            token = page.get("nextToken")
            if not token:
                break
    return out


class BedrockConverseClient(OpenAIClient):
    """Converse-API round trip behind the OpenAIClient contract."""

    PROVIDER = PROVIDER_BEDROCK

    def __init__(self, base_url: str, api_key: str, model: str, **kwargs):
        # The slot's URL field holds a region OR a full endpoint URL.
        runtime, _, region = resolve_endpoint(base_url)
        super().__init__(runtime, api_key, model, **kwargs)
        self.region = region
        # Set once a model has rejected `temperature` (Kimi K3: "This model
        # doesn't support the temperature field"; Claude with thinking on).
        # Later calls on this client omit it up front instead of paying the
        # 400 + retry on every request -- an orchestrator reuses one client
        # across its specialist calls, so this is one retry per job, not six.
        self._omit_temperature = False

    # Converse stopReason -> chat-completions finish_reason. Values not listed
    # pass through unchanged so a log line still names what Bedrock said.
    _STOP_REASON_MAP = {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "model_context_window_exceeded": "length",
        "tool_use": "tool_calls",
    }
    # Stops that mean "there is no answer": raised, never returned.
    _REFUSAL_STOP_REASONS = ("guardrail_intervened", "content_filtered")
    _MALFORMED_STOP_REASONS = ("malformed_model_output", "malformed_tool_use")

    # ------------------------------------------------------------------ URL

    @staticmethod
    def normalise_model_id(model: str) -> str:
        """Accept a model id / inference profile id / ARN as the console shows
        it OR already URL-encoded (the Bedrock console's copy buttons hand out
        `arn%3Aaws%3Abedrock%3A...%2F...`). Decoding first means the id is
        encoded exactly once whichever form the admin pasted.
        """
        value = (model or "").strip()
        if "%" in value:
            value = unquote(value)
        return value

    def converse_url(self, model: str | None = None) -> str:
        model_id = self.normalise_model_id(model if model is not None else self.model)
        if not model_id:
            raise AIClientError("AI model is empty")
        # safe='' so the ARN's ':' and '/' are encoded -- an unencoded '/'
        # would split the path and Bedrock answers 404 ResourceNotFound.
        return f"{self.base_url}/model/{quote(model_id, safe='')}/converse"

    # ----------------------------------------------------------------- body

    @staticmethod
    def build_body(
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float | None
    ) -> dict[str, Any]:
        """Chat-completions messages -> Converse request body.

        Converse wants system prompts in their own array and strictly
        alternating user/assistant turns whose content is a list of blocks.
        Consecutive same-role messages are therefore merged into one turn
        with several text blocks (same tokens, valid shape); empty messages
        are dropped because an empty text block is a ValidationException.
        """
        system: list[dict[str, str]] = []
        turns: list[dict[str, Any]] = []
        for message in messages:
            role = (message.get("role") or "user").strip().lower()
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            if role == "system":
                system.append({"text": content})
                continue
            if role not in ("user", "assistant"):
                role = "user"
            if turns and turns[-1]["role"] == role:
                turns[-1]["content"].append({"text": content})
            else:
                turns.append({"role": role, "content": [{"text": content}]})

        if not turns:
            raise AIClientError("Bedrock Converse needs at least one non-empty user message")
        if turns[0]["role"] != "user":
            raise AIClientError("Bedrock Converse requires the first message to be a user turn")

        inference: dict[str, Any] = {"maxTokens": int(max_tokens)}
        if temperature is not None:
            inference["temperature"] = float(temperature)
        body: dict[str, Any] = {"messages": turns, "inferenceConfig": inference}
        if system:
            body["system"] = system
        return body

    # ------------------------------------------------------------- response

    @classmethod
    def to_openai_envelope(cls, raw: dict[str, Any], *, model: str) -> dict[str, Any]:
        """Converse response -> chat-completions envelope.

        Only `text` blocks become content. `reasoningContent` blocks (Kimi,
        GLM, Claude with thinking) are the model's chain of thought and are
        dropped here, structurally -- the regex stripping in extract_content()
        stays as the second line for hosts that inline it.
        """
        stop = raw.get("stopReason") if isinstance(raw, dict) else None
        if stop in cls._REFUSAL_STOP_REASONS:
            raise AIClientError(
                f"AI backend withheld the response (Bedrock stopReason={stop})"
            )
        if stop in cls._MALFORMED_STOP_REASONS:
            raise AIClientError(
                f"AI backend produced malformed output (Bedrock stopReason={stop})"
            )
        try:
            blocks = raw["output"]["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise AIClientError(
                f"AI backend returned an unexpected envelope: {json.dumps(raw)[:500]}"
            ) from exc
        if not isinstance(blocks, list):
            raise AIClientError(
                f"AI backend returned an unexpected envelope: {json.dumps(raw)[:500]}"
            )

        text = "".join(
            block["text"] for block in blocks
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        # Bedrock reports prompt tokens served from the prompt cache OUTSIDE
        # inputTokens (a cached 4.5 KB synthesis prompt logged as 7 tokens).
        # The chat-completions shape counts them inside prompt_tokens and
        # details the cached share, so fold them back in the same way.
        cached = cls._int_or_zero(usage.get("cacheReadInputTokens"))
        written = cls._int_or_zero(usage.get("cacheWriteInputTokens"))
        prompt = usage.get("inputTokens")
        if prompt is not None and (cached or written):
            prompt = cls._int_or_zero(prompt) + cached + written
        return {
            "object": "chat.completion",
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": cls._STOP_REASON_MAP.get(stop, stop),
            }],
            "usage": {
                "prompt_tokens": prompt,
                "completion_tokens": usage.get("outputTokens"),
                "total_tokens": usage.get("totalTokens"),
                "prompt_tokens_details": {"cached_tokens": cached},
            },
            # Kept verbatim for logs and probes; no orchestrator reads it.
            "bedrock": {
                "stopReason": stop,
                "usage": usage,
                "metrics": raw.get("metrics"),
            },
        }

    @staticmethod
    def _int_or_zero(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    # ----------------------------------------------------------- round trip

    @staticmethod
    def _is_temperature_rejection(exc: AIClientError) -> bool:
        text = str(exc)
        return "HTTP 400" in text and "temperature" in text.lower()

    def _send(self, model: str, body: dict[str, Any]) -> dict[str, Any]:
        return http_post_json(
            self.converse_url(model),
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
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
        """One Converse round trip, returned as a chat-completions envelope.

        Models whose thinking is on by default (Claude 5.x adaptive thinking)
        may reject an explicit temperature with a 400 ValidationException.
        That case is retried once without the field; every other error is
        raised as-is.
        """
        model_id = model if model is not None else self.model
        temp = temperature if temperature is not None else self.default_temperature
        if self._omit_temperature:
            temp = None
        body = self.build_body(
            messages,
            max_tokens=max_tokens if max_tokens is not None else self.default_max_tokens,
            temperature=temp,
        )
        try:
            raw = self._send(model_id, body)
        except AIClientError as exc:
            if "temperature" in body["inferenceConfig"] and self._is_temperature_rejection(exc):
                log.warning(
                    "Bedrock (model=%s) rejected an explicit temperature; retrying without it "
                    "and omitting it for the rest of this client's calls",
                    model_id
                )
                self._omit_temperature = True
                body["inferenceConfig"].pop("temperature")
                raw = self._send(model_id, body)
            else:
                raise
        return self.to_openai_envelope(raw, model=model_id)

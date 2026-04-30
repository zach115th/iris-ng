#  IRIS Source Code
#
#  OpenAI-compatible chat-completions client used by Tier-1 AI features.
#  urllib stdlib only — no new dependencies. Mirrors the pattern in
#  iris_misp_sync_module.ai_type_resolver but is generic (no allow-list,
#  no JSON-output validation) so any feature can call it.

from __future__ import annotations

import json
from typing import Any
import urllib.error
import urllib.request


class AIClientError(Exception):
    """Raised when the AI backend returns an error or unexpected response."""


class OpenAIClient:
    """Minimal OpenAI-compatible chat-completions client."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float = 120.0,
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

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None
    ) -> dict[str, Any]:
        """Send a chat-completions request and return the parsed envelope.

        Returns the raw OpenAI-compat envelope. Use `extract_content` for
        the assistant message body.
        """
        body = json.dumps({
            "model": self.model,
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
        except json.JSONDecodeError as exc:
            raise AIClientError(f"AI backend returned non-JSON response: {exc}") from exc

        return payload

    @staticmethod
    def extract_content(payload: dict[str, Any]) -> str:
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise AIClientError(
                f"AI backend returned an unexpected envelope: {json.dumps(payload)[:500]}"
            ) from exc


def build_default_client(
    *,
    timeout: float = 120.0,
    default_max_tokens: int = 4000
) -> OpenAIClient | None:
    """Construct a client from the active AI backend configuration.

    Resolution order (first non-empty wins):
      1. ServerSettings table (admin-editable via /manage/settings)
      2. app.config (env vars at startup — bootstrap fallback before the
         settings row is populated)

    Returns None when the AI backend is disabled or not configured. Caller
    decides whether that's an error or a graceful skip.
    """
    from app import app

    enabled, base_url, api_key, model = _read_settings_row()

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


def _read_settings_row() -> tuple[bool | None, str | None, str | None, str | None]:
    """Pull AI backend config from the ServerSettings row.

    Returns (enabled, url, api_key, model). Any field can be None if the row
    or column doesn't exist yet (covers fresh installs / pre-migration boot).
    """
    try:
        from app.models.models import ServerSettings
        row = ServerSettings.query.first()
    except Exception:
        return (None, None, None, None)

    if row is None:
        return (None, None, None, None)

    return (
        getattr(row, 'ai_backend_enabled', None),
        (getattr(row, 'ai_backend_url', None) or '').strip() or None,
        (getattr(row, 'ai_backend_api_key', None) or '').strip() or None,
        (getattr(row, 'ai_backend_model', None) or '').strip() or None,
    )

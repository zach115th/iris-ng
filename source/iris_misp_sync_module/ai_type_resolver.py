#!/usr/bin/env python3
#
#  IRIS MISP Sync Module Source Code
#
#  AI-driven fallback for IRIS IOC types that have no direct MISP attribute-type
#  mapping (account, file-path, ip-any). Inherits the proven n8n decision rules
#  and tightens them with hard allow-lists per IRIS-local raw type.
#

from __future__ import annotations

import json
import re
from typing import Any, Iterable
import urllib.error
import urllib.request


ALLOWED_OUTPUTS: dict[str, list[str]] = {
    "account": ["email", "iban", "target-user", "text", "other"],
    "ip-any": ["ip-src", "ip-dst", "other"],
    "file-path": ["filename", "regkey", "target-user", "other"],
}


SYSTEM_PROMPT = "Return only valid JSON. No markdown. No prose."


PROMPT_TEMPLATE = """You map DFIR-IRIS IOC records to the best-fit MISP attribute type.

Allowed output values for raw_type {raw_type}:
{allowed_list}

Rules:
- Use the IOC raw_type, value, description, tags, and TLP.
- For raw_type=account:
  - choose email if the value is clearly an email address
  - choose iban if the value is clearly an IBAN
  - choose target-user if it looks like a username, AD account, SID, or service principal
  - choose text if it is account context but not a structured identifier
  - otherwise choose other
- For raw_type=ip-any:
  - choose ip-src if the description/tags/context indicate source, attacker, or origin
  - choose ip-dst if the description/tags/context indicate destination, C2, callback, beacon, or remote endpoint
  - otherwise choose other
- For raw_type=file-path:
  - choose filename if the value is just a file name or has no path separators
  - choose regkey if the value starts with HKEY_, HKLM, HKCU, HKCR, or HKU
  - choose target-user if the path is a user home directory (e.g. /home/<name>, C:\\Users\\<name>)
  - otherwise choose other
- Do not invent types outside the allow-list.
- Return JSON only.

Input:
raw_type: {raw_type}
value: {value}
description: {description}
tags: {tags}
tlp: {tlp}

Return:
{{
  "mapped_type": "one allowed value",
  "confidence": 0.0,
  "reason": "brief reason"
}}"""


class AITypeResolverError(Exception):
    """Raised when the AI fallback cannot produce a valid type mapping."""


class AITypeResolver:
    """OpenAI-compatible AI client for resolving unmapped IRIS IOC types."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float = 30.0,
        max_tokens: int = 400,
        temperature: float = 0.0
    ):
        if not base_url:
            raise AITypeResolverError("AI base_url is empty")
        if not model:
            raise AITypeResolverError("AI model is empty")

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature

    @staticmethod
    def supports(raw_type: str) -> bool:
        return raw_type in ALLOWED_OUTPUTS

    @staticmethod
    def allowed_for(raw_type: str) -> list[str]:
        return list(ALLOWED_OUTPUTS.get(raw_type, []))

    def resolve(
        self,
        raw_type: str,
        value: str,
        *,
        description: str = "",
        tags: Iterable[str] | str = "",
        tlp: str = ""
    ) -> dict[str, Any]:
        if not self.supports(raw_type):
            raise AITypeResolverError(
                f"AI type resolution is not configured for raw_type={raw_type!r}"
            )

        allowed = ALLOWED_OUTPUTS[raw_type]
        if not isinstance(tags, str):
            tags = ", ".join(t for t in tags if t)

        prompt = PROMPT_TEMPLATE.format(
            raw_type=raw_type,
            allowed_list="\n".join(allowed),
            value=value or "",
            description=description or "",
            tags=tags or "",
            tlp=tlp or ""
        )

        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature
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
        except urllib.error.URLError as exc:
            raise AITypeResolverError(f"AI backend request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise AITypeResolverError(f"AI backend returned non-JSON response: {exc}") from exc

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise AITypeResolverError(
                f"AI backend returned an unexpected envelope: {json.dumps(payload)[:500]}"
            ) from exc

        result = self._parse_response(content)
        mapped = str(result.get("mapped_type", "")).strip()
        if mapped not in allowed:
            raise AITypeResolverError(
                f"AI returned mapped_type={mapped!r}, which is not in the allow-list "
                f"for {raw_type}: {allowed}"
            )

        try:
            confidence = float(result.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        return {
            "mapped_type": mapped,
            "confidence": confidence,
            "reason": str(result.get("reason", "")).strip() or None,
            "raw_type": raw_type,
            "model": self.model
        }

    @staticmethod
    def _parse_response(content: str) -> dict[str, Any]:
        cleaned = content.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise AITypeResolverError(
                f"AI response did not contain a JSON object: {content[:500]}"
            )

        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as exc:
            raise AITypeResolverError(
                f"AI response JSON decode failed: {content[:500]}"
            ) from exc

#!/usr/bin/env python3
#
#  IRIS MISP Sync Module Source Code
#

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests


class MispSyncClientError(Exception):
    """Raised when the MISP sync client encounters an API or decoding error."""


class MispSyncClient:
    """Small MISP REST client for the Phase 1 event and attribute sync paths."""

    def __init__(self, base_url: str, api_key: str, verify_tls: bool = True,
                 proxies: dict[str, str] | None = None, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.verify_tls = verify_tls
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "iris-next-misp-sync/0.1"
        })
        if proxies:
            self.session.proxies.update(proxies)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.request(
            method=method,
            url=f"{self.base_url}/{path.lstrip('/')}",
            json=payload,
            verify=self.verify_tls,
            timeout=self.timeout
        )

        try:
            body = response.json() if response.content else {}
        except ValueError as exc:
            raise MispSyncClientError(
                f"MISP returned a non-JSON response for {method} {path}: {response.text[:200]}"
            ) from exc

        if not response.ok:
            raise MispSyncClientError(
                f"MISP API call failed for {method} {path}: {response.status_code} {body}"
            )

        return body

    def create_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "events/add", payload)

    def get_server_version(self) -> dict[str, Any]:
        return self._request("GET", "servers/getVersion")

    def get_current_user(self) -> dict[str, Any]:
        return self._request("GET", "users/view/me")

    def update_event(self, event_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"events/edit/{event_id}", payload)

    def delete_event(self, event_id: int) -> dict[str, Any]:
        return self._request("DELETE", f"events/delete/{event_id}")

    def add_attribute(self, event_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"attributes/add/{event_id}", payload)

    def update_attribute(self, attribute_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"attributes/edit/{attribute_id}", payload)

    def search_attributes(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "attributes/restSearch", payload)

    def describe_types(self) -> dict[str, Any]:
        return self._request("GET", "attributes/describeTypes")

    def create_tag(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "tags/add", payload)

    def search_tags(self, search_term: str) -> dict[str, Any]:
        return self._request("GET", f"tags/search/{quote(search_term, safe='')}")

    def add_event_tag(self, event_id: int, tag_id: int, local: bool = False) -> dict[str, Any]:
        return self._request("POST", f"events/addTag/{event_id}/{tag_id}/local:{1 if local else 0}")

    def add_attribute_tag(self, attribute_id: int, tag_id: int, local: bool = False) -> dict[str, Any]:
        return self._request("POST", f"attributes/addTag/{attribute_id}/{tag_id}/local:{1 if local else 0}")

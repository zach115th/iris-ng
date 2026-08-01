#!/usr/bin/env python3
#
#  IRIS MISP Sync Module Source Code
#

from __future__ import annotations

from typing import Any

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

    def add_event_report(self, event_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """Attach a MISP Event Report (first-class Markdown document).

        Prose belongs here rather than in a `type=comment` attribute: reports
        render Markdown, are versioned, and keep the attribute list to actual
        indicators. Body: {name, content, distribution}.
        """
        return self._request("POST", f"eventReports/add/{event_id}", payload)

    def add_analyst_note(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Attach a MISP analyst Note to any UUID-addressable object.

        Two shape requirements MISP does not document clearly, both found by
        probing a live 2.5.34 instance:
          - the body MUST be wrapped as {"Note": {...}}; a flat body returns
            403 "Could not add analyst_data",
          - `distribution` MUST be 0-3. Unlike attributes and event reports,
            analyst data rejects 5 ("inherit event") with the same 403, so a
            caller cannot simply mirror the event's setting.

        Inner keys: object_type, object_uuid, note, distribution[, language].
        """
        return self._request("POST", "analyst_data/add/Note", {"Note": payload})

    def create_tag(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "tags/add", payload)

    def search_tags(self, search_term: str) -> dict[str, Any]:
        # POST /tags/index with searchall handles colon-containing names (e.g. tlp:green)
        # correctly; GET /tags/search/<term> silently returns [] for those.
        return self._request("POST", "tags/index", {"searchall": search_term})

    def add_event_tag(self, event_id: int, tag_id: int, local: bool = False) -> dict[str, Any]:
        return self._request("POST", f"events/addTag/{event_id}/{tag_id}/local:{1 if local else 0}")

    def add_attribute_tag(self, attribute_id: int, tag_id: int, local: bool = False) -> dict[str, Any]:
        return self._request("POST", f"attributes/addTag/{attribute_id}/{tag_id}/local:{1 if local else 0}")

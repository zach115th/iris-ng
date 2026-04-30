#!/usr/bin/env python3
"""
Validate MISP connectivity and the core event/attribute write path used by
iris_misp_sync_module without embedding credentials in repo files.

Environment variables:
  MISP_URL          Required
  MISP_API_KEY      Required
  MISP_VERIFY_TLS   Optional, default true
  MISP_HTTP_PROXY   Optional
  MISP_HTTPS_PROXY  Optional
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "source"
sys.path.insert(0, str(SOURCE_ROOT))

from iris_misp_sync_module.misp_sync_client import MispSyncClient  # noqa: E402
from iris_misp_sync_module.misp_sync_client import MispSyncClientError  # noqa: E402


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _build_client() -> MispSyncClient:
    base_url = os.getenv("MISP_URL")
    api_key = os.getenv("MISP_API_KEY")

    if not base_url or not api_key:
        raise SystemExit("MISP_URL and MISP_API_KEY must be set in the environment.")

    proxies = {}
    if os.getenv("MISP_HTTP_PROXY"):
        proxies["http"] = os.getenv("MISP_HTTP_PROXY")
    if os.getenv("MISP_HTTPS_PROXY"):
        proxies["https"] = os.getenv("MISP_HTTPS_PROXY")

    return MispSyncClient(
        base_url=base_url,
        api_key=api_key,
        verify_tls=_env_bool("MISP_VERIFY_TLS", True),
        proxies=proxies or None
    )


def _env_int(name: str, default: int | None = None) -> int | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _extract_event_id(payload: dict) -> int:
    event = payload.get("Event") or payload.get("response", {}).get("Event") or payload
    return int(event["id"])


def _extract_attribute_id(payload: dict) -> int:
    attribute = payload.get("Attribute") or payload.get("response", {}).get("Attribute") or payload
    if isinstance(attribute, list):
        attribute = attribute[0]
    return int(attribute["id"])


def run_read_only_validation(client: MispSyncClient):
    version = client.get_server_version()
    describe = client.describe_types()
    me = client.get_current_user()

    sane_defaults = describe.get("result", {}).get("sane_defaults", {})
    summary = {
        "misp_version": version.get("version"),
        "pymisp_recommended_version": version.get("pymisp_recommended_version"),
        "current_user_email": me.get("User", {}).get("email"),
        "current_user_role_id": me.get("User", {}).get("role_id"),
        "type_count": len(sane_defaults),
        "sample_types": {
            key: sane_defaults.get(key)
            for key in ["domain", "ip-src", "ip-dst", "md5", "sha256", "url"]
        }
    }
    print(json.dumps(summary, indent=2))


def run_write_validation(client: MispSyncClient):
    timestamp = int(time.time())
    distribution = _env_int("MISP_EVENT_DISTRIBUTION", 4)
    sharing_group_id = _env_int("MISP_SHARING_GROUP_ID", 1 if distribution == 4 else None)
    threat_level_id = _env_int("MISP_EVENT_THREAT_LEVEL_ID", 2)
    analysis = _env_int("MISP_EVENT_ANALYSIS", 1)

    event_payload = {
        "info": f"iris-next validation event {timestamp}",
        "date": date.today().isoformat(),
        "distribution": distribution,
        "sharing_group_id": sharing_group_id,
        "threat_level_id": threat_level_id,
        "analysis": analysis,
        "published": False
    }
    event_payload = {k: v for k, v in event_payload.items() if v is not None}

    created_event = client.create_event(event_payload)
    event_id = _extract_event_id(created_event)
    print(f"Created event {event_id}")

    try:
        attribute_payload = {
            "type": "domain",
            "category": "Network activity",
            "value": f"validation-{timestamp}.example.com",
            "to_ids": True,
            "comment": f"iris-next validation attribute {timestamp}",
            "distribution": 5
        }
        created_attr = client.add_attribute(event_id, attribute_payload)
        attr_id = _extract_attribute_id(created_attr)
        print(f"Created attribute {attr_id}")

        updated_attr = client.update_attribute(attr_id, {
            **attribute_payload,
            "value": f"validation-updated-{timestamp}.example.com",
            "comment": f"iris-next validation attribute updated {timestamp}"
        })
        updated_attr_id = _extract_attribute_id(updated_attr)
        print(f"Updated attribute {updated_attr_id}")

    finally:
        client.delete_event(event_id)
        print(f"Deleted event {event_id}")


def main():
    parser = argparse.ArgumentParser(description="Validate MISP connectivity for iris-next.")
    parser.add_argument(
        "--write-test",
        action="store_true",
        help="Create, update, and delete a temporary event/attribute to validate the write path."
    )
    args = parser.parse_args()

    client = _build_client()
    try:
        run_read_only_validation(client)
        if args.write_test:
            run_write_validation(client)
    except MispSyncClientError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Local dev helper for configuring, validating, and maintaining IrisMISPSync in
the docker-compose.dev stack.

This script is intentionally opinionated toward the local iris-next workflow:
it can mint a temporary API key for the bootstrap administrator account inside
the app container, configure the IRIS module from local MISP environment
variables, run an end-to-end case/IOC sync smoke test, clean up throwaway
validation cases, and keep Case #3 populated as a stable known-good fixture for
backend and UI work.

It reads MISP_* defaults from the project .env file when present.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
DEFAULT_APP_CONTAINER = "iriswebapp_app"
DEFAULT_DB_CONTAINER = "iriswebapp_db"
DEFAULT_DB_NAME = "iris_db"
DEFAULT_DB_USER = "postgres"
DEFAULT_IRIS_URL = "http://localhost:8000"
DEFAULT_MODULE_NAME = "IrisMISPSync"
DEFAULT_SMOKE_CASE_SOC_PREFIX = "iris-next-sync-"
DEFAULT_KNOWN_GOOD_CASE_ID = 3
DEFAULT_ASSIGNEE_LOGIN = "administrator"
DEFAULT_TLP_POLICY = """{
  "clear": 5,
  "green": 5,
  "white": 5,
  "amber": 0,
  "amber+strict": 0,
  "red": 0
}"""

KNOWN_GOOD_CASE_NAME = "IRIS Next Known-Good Validation Case"
KNOWN_GOOD_CASE_SOC_ID = "iris-next-known-good-case-3"
KNOWN_GOOD_CASE_TAGS = "known-good,misp-sync,ui-fixture"
KNOWN_GOOD_IOC_VALUE = "secure-helpdesk-login.example.net"
KNOWN_GOOD_IOC_MARKER = "known-good-primary"
KNOWN_GOOD_ASSET_NAME = "WS-FIN-07"
KNOWN_GOOD_CASE_DESCRIPTION = """Known-good validation case for iris-next UI and native MISP sync.

On 2026-04-28, a finance user reported a suspicious browser prompt that asked
them to re-verify access through `secure-helpdesk-login.example.net`. Local
validation confirmed the prompt was not part of a sanctioned workflow, the
workstation was isolated, and evidence collection remained in progress.

Use this case as the stable dev fixture for UI work, API checks, and regression
testing of IRIS-to-MISP synchronization.
"""

KNOWN_GOOD_NOTE_CONTENT = {
    "Initial summary": """## Situation

On 2026-04-28, the finance user assigned to **WS-FIN-07** reported a browser
prompt that requested an urgent access re-verification through
`secure-helpdesk-login.example.net`.

## Current status

- User report captured and summarized
- IOC synced to the linked MISP event
- Workstation isolated pending additional review
- Timeline and tasks maintained as a reusable UI fixture
""",
    "Business impact": """## Impact snapshot

- A single finance workstation was involved in the report
- No confirmed server-side disruption has been observed
- Potential credential exposure remains under review

## Operational note

This case is intentionally maintained as a stable local validation fixture. It
should stay realistic enough for analyst workflows without depending on live
production data.
""",
    "Scope and affected systems": """## In-scope systems

| Item | Status | Notes |
| --- | --- | --- |
| WS-FIN-07 | Isolated | Finance workstation kept for analyst review |
| secure-helpdesk-login.example.net | Tracked IOC | Domain synced to MISP for linkage validation |

## Boundaries

- Scope is currently limited to the reporting endpoint and the observed domain
- No additional hosts have been confirmed as affected in this local validation case
"""
}

KNOWN_GOOD_TASKS = [
    {
        "title": "Review linked MISP event for Case #3",
        "description": "Confirm the Case #3 event title, tags, and linked attribute state remain aligned after local updates.",
        "status_name": "Done",
        "tags": "known-good,validation,misp"
    },
    {
        "title": "Confirm user activity timeline on WS-FIN-07",
        "description": "Validate the timeline narrative and supporting notes before UI work starts on the case workspace.",
        "status_name": "In progress",
        "tags": "known-good,investigation,ui-fixture"
    }
]

KNOWN_GOOD_EVENTS = [
    {
        "title": "User reported suspicious login verification prompt",
        "date": "2026-04-28T08:13:00.000000",
        "category_name": "Initial Access",
        "color": "#FFAD4699",
        "tags": "known-good,report,phishing-theme",
        "content": """The finance user on **WS-FIN-07** reported a browser prompt asking
for an immediate access re-verification through
`secure-helpdesk-login.example.net`.

The user did not submit credentials and escalated the prompt for review.
""",
        "include_ioc": True,
        "event_in_summary": True,
        "event_in_graph": True
    },
    {
        "title": "Analyst correlated outbound lookup to reported domain",
        "date": "2026-04-28T08:27:00.000000",
        "category_name": "Discovery",
        "color": "#1572E899",
        "tags": "known-good,dns,triage",
        "content": """Local review tied the reported prompt to an outbound lookup for
`secure-helpdesk-login.example.net` from **WS-FIN-07**.

The IOC remained in-scope and suitable for MISP attribute sync validation.
""",
        "include_ioc": True,
        "event_in_summary": False,
        "event_in_graph": True
    },
    {
        "title": "Endpoint isolated from network while triage continued",
        "date": "2026-04-28T09:05:00.000000",
        "category_name": "Remediation",
        "color": "#31CE3699",
        "tags": "known-good,containment,endpoint",
        "content": """The workstation **WS-FIN-07** was isolated from the network while
evidence collection and analyst review continued.

No additional hosts were added to scope during this local validation step.
""",
        "include_ioc": False,
        "event_in_summary": True,
        "event_in_graph": True
    }
]


class DevScriptError(Exception):
    """Raised when the local dev helper cannot complete its requested action."""


def load_env_file(path: Path):
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int | None = None) -> int | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def run_command(command: list[str], *, stdin: str | None = None) -> str:
    proc = subprocess.run(
        command,
        input=stdin,
        capture_output=True,
        text=True,
        check=False
    )
    if proc.returncode != 0:
        raise DevScriptError(
            f"Command failed ({proc.returncode}): {' '.join(command)}\n{proc.stderr.strip()}"
        )
    return proc.stdout


def mint_local_admin_api_key(app_container: str) -> str:
    py_script = """
import secrets
from app import app, db
from app.models.authorization import User
with app.app_context():
    user = User.query.filter_by(user='administrator').first()
    user.api_key = secrets.token_urlsafe(nbytes=64)
    db.session.commit()
    print(user.api_key)
"""
    output = run_command(
        [
            "docker", "exec", "-i", app_container,
            "/bin/bash", "-lc", "/opt/venv/bin/python -"
        ],
        stdin=py_script
    )

    token_pattern = re.compile(r"^[A-Za-z0-9_-]{60,}$")
    for line in output.splitlines():
        candidate = line.strip()
        if token_pattern.match(candidate):
            return candidate

    raise DevScriptError("Unable to extract a temporary IRIS API key from docker exec output")


def iris_request(
    method: str,
    base_url: str,
    api_key: str,
    path: str,
    payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = requests.request(
        method=method,
        url=f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=30
    )

    try:
        body = response.json() if response.content else {}
    except ValueError as exc:
        raise DevScriptError(
            f"IRIS returned a non-JSON response for {method} {path}: {response.text[:200]}"
        ) from exc

    if not response.ok:
        raise DevScriptError(f"IRIS API call failed for {method} {path}: {response.status_code} {body}")

    status = body.get("status")
    if status and status != "success":
        raise DevScriptError(f"IRIS API call failed for {method} {path}: {body}")

    return body


def misp_request(
    method: str,
    base_url: str,
    api_key: str,
    path: str,
    payload: dict[str, Any] | None = None,
    verify_tls: bool = True
) -> dict[str, Any]:
    response = requests.request(
        method=method,
        url=f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        headers={
            "Authorization": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "iris-next-misp-sync-dev/0.1"
        },
        json=payload,
        timeout=30,
        verify=verify_tls
    )

    try:
        body = response.json() if response.content else {}
    except ValueError as exc:
        raise DevScriptError(
            f"MISP returned a non-JSON response for {method} {path}: {response.text[:200]}"
        ) from exc

    if not response.ok:
        raise DevScriptError(f"MISP API call failed for {method} {path}: {response.status_code} {body}")

    return body


def db_query(
    db_container: str,
    sql: str,
    *,
    db_name: str,
    db_user: str,
    tuples_only: bool = True
) -> str:
    command = [
        "docker", "exec", db_container,
        "psql", "-U", db_user, "-d", db_name
    ]
    if tuples_only:
        command.extend(["-t", "-A"])
    command.extend(["-c", sql])
    return run_command(command).strip()


def wait_for_db_value(
    db_container: str,
    sql: str,
    *,
    db_name: str,
    db_user: str,
    timeout_seconds: int = 40
) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        value = db_query(
            db_container,
            sql,
            db_name=db_name,
            db_user=db_user,
            tuples_only=True
        ).strip()
        if value:
            return value
        time.sleep(2)

    raise DevScriptError(f"Timed out waiting for DB value from query: {sql}")


def get_misp_env(*, required: bool = False) -> dict[str, Any] | None:
    misp_url = os.getenv("MISP_URL")
    misp_api_key = os.getenv("MISP_API_KEY")
    if required and (not misp_url or not misp_api_key):
        raise DevScriptError("MISP_URL and MISP_API_KEY must be available via environment or .env")
    if not misp_url or not misp_api_key:
        return None

    return {
        "url": misp_url,
        "api_key": misp_api_key,
        "verify_tls": env_bool("MISP_VERIFY_TLS", True)
    }


def get_ai_env() -> dict[str, Any] | None:
    ai_url = os.getenv("AI_BACKEND_URL")
    ai_model = os.getenv("AI_BACKEND_MODEL")
    if not ai_url or not ai_model:
        return None
    return {
        "url": ai_url,
        "api_key": os.getenv("AI_BACKEND_API_KEY") or "",
        "model": ai_model,
        "confidence_threshold": float(os.getenv("AI_BACKEND_CONFIDENCE_THRESHOLD", "0.70"))
    }


def get_misp_defaults(misp_url: str, misp_api_key: str, verify_tls: bool) -> dict[str, int | None]:
    me = misp_request("GET", misp_url, misp_api_key, "users/view/me", verify_tls=verify_tls)
    sharing_groups = misp_request("GET", misp_url, misp_api_key, "sharing_groups", verify_tls=verify_tls)

    sharing_group_id = None
    response_rows = sharing_groups.get("response", [])
    if response_rows:
        sharing_group_id = int(response_rows[0]["SharingGroup"]["id"])

    return {
        "org_id": int(me["User"]["org_id"]),
        "sharing_group_id": sharing_group_id
    }


def find_module(modules: list[dict[str, Any]], module_name: str) -> dict[str, Any]:
    for module in modules:
        if module.get("module_human_name") == module_name:
            return module
    raise DevScriptError(f"Unable to find IRIS module {module_name}")


def build_module_config(
    *,
    misp_url: str,
    misp_api_key: str,
    verify_tls: bool,
    org_id: int,
    sharing_group_id: int | None,
    distribution: int,
    threat_level_id: int,
    analysis: int,
    ai_env: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    config = [
        {"param_name": "misp_sync_url", "value": misp_url},
        {"param_name": "misp_sync_api_key", "value": misp_api_key},
        {"param_name": "misp_sync_verify_tls", "value": verify_tls},
        {"param_name": "misp_sync_org_id", "value": org_id},
        {"param_name": "misp_sync_distribution", "value": distribution},
        {"param_name": "misp_sync_sharing_group_id", "value": sharing_group_id},
        {"param_name": "misp_sync_threat_level_id", "value": threat_level_id},
        {"param_name": "misp_sync_analysis", "value": analysis},
        {"param_name": "misp_sync_attribute_to_ids", "value": True},
        {"param_name": "misp_sync_tlp_distribution_policy", "value": DEFAULT_TLP_POLICY},
        {"param_name": "misp_sync_tag_sync_enabled", "value": True},
        {"param_name": "misp_sync_case_create_enabled", "value": True},
        {"param_name": "misp_sync_case_update_enabled", "value": True},
        {"param_name": "misp_sync_ioc_create_enabled", "value": True},
        {"param_name": "misp_sync_ioc_update_enabled", "value": True}
    ]

    if ai_env:
        config.extend([
            {"param_name": "misp_sync_ai_enabled", "value": True},
            {"param_name": "misp_sync_ai_url", "value": ai_env["url"]},
            {"param_name": "misp_sync_ai_api_key", "value": ai_env["api_key"]},
            {"param_name": "misp_sync_ai_model", "value": ai_env["model"]},
            {"param_name": "misp_sync_ai_confidence_threshold", "value": ai_env["confidence_threshold"]}
        ])

    return config


def refresh_module_schema(args: argparse.Namespace) -> dict[str, Any]:
    """Refresh the module's stored config schema from IrisMISPSyncConfig.module_configuration.

    IRIS caches the schema in iris_module.module_config at registration time. When new
    config params are added in source, existing records remain on the old schema and reject
    values for unknown params. This function merges the new schema with existing values.
    """
    py_script = f"""
import json
from app import app, db
from app.models.models import IrisModule
import iris_misp_sync_module.IrisMISPSyncConfig as cfg

with app.app_context():
    module = IrisModule.query.filter_by(module_human_name={args.module_name!r}).first()
    if module is None:
        print(json.dumps({{'ok': False, 'error': 'module not found'}}))
        raise SystemExit(0)

    existing_values = {{
        entry['param_name']: entry.get('value')
        for entry in (module.module_config or [])
        if isinstance(entry, dict) and 'param_name' in entry
    }}

    refreshed = []
    added = []
    for entry in cfg.module_configuration:
        merged = dict(entry)
        if entry['param_name'] in existing_values:
            merged['value'] = existing_values[entry['param_name']]
        else:
            added.append(entry['param_name'])
        refreshed.append(merged)

    module.module_config = refreshed
    db.session.commit()
    print(json.dumps({{
        'ok': True,
        'param_count': len(refreshed),
        'added_param_names': added
    }}))
"""
    output = run_command(
        [
            "docker", "exec", "-i", args.app_container,
            "/bin/bash", "-lc", "/opt/venv/bin/python -"
        ],
        stdin=py_script
    ).strip()

    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise DevScriptError(
            f"Unable to parse schema-refresh output from app container: {output[:500]}"
        ) from exc


def configure_module(args: argparse.Namespace, api_key: str) -> dict[str, Any]:
    misp_env = get_misp_env(required=True)

    verify_tls = misp_env["verify_tls"]
    defaults = get_misp_defaults(misp_env["url"], misp_env["api_key"], verify_tls=verify_tls)
    distribution = env_int("MISP_EVENT_DISTRIBUTION", 4)
    sharing_group_id = env_int("MISP_SHARING_GROUP_ID", defaults["sharing_group_id"])
    threat_level_id = env_int("MISP_EVENT_THREAT_LEVEL_ID", 2)
    analysis = env_int("MISP_EVENT_ANALYSIS", 1)
    org_id = env_int("MISP_ORG_ID", defaults["org_id"])

    modules = iris_request("GET", args.iris_url, api_key, "manage/modules/list")
    module = find_module(modules["data"], args.module_name)
    module_id = int(module["id"])

    # Refresh schema in case IrisMISPSyncConfig.module_configuration grew new params
    schema_refresh = refresh_module_schema(args)

    ai_env = get_ai_env()

    payload = {
        "module_configuration": build_module_config(
            misp_url=misp_env["url"],
            misp_api_key=misp_env["api_key"],
            verify_tls=verify_tls,
            org_id=org_id,
            sharing_group_id=sharing_group_id,
            distribution=distribution,
            threat_level_id=threat_level_id,
            analysis=analysis,
            ai_env=ai_env
        )
    }

    imported = iris_request(
        "POST",
        args.iris_url,
        api_key,
        f"manage/modules/import-config/{module_id}",
        payload
    )
    enabled = iris_request(
        "POST",
        args.iris_url,
        api_key,
        f"manage/modules/enable/{module_id}"
    )
    refreshed_modules = iris_request("GET", args.iris_url, api_key, "manage/modules/list")
    refreshed = find_module(refreshed_modules["data"], args.module_name)

    return {
        "module_id": module_id,
        "import": imported,
        "enable": enabled,
        "module": refreshed,
        "resolved_defaults": {
            "misp_url": misp_env["url"],
            "verify_tls": verify_tls,
            "org_id": org_id,
            "distribution": distribution,
            "sharing_group_id": sharing_group_id,
            "threat_level_id": threat_level_id,
            "analysis": analysis
        }
    }


def get_tlp_id(args: argparse.Namespace, api_key: str, tlp_name: str) -> int:
    tlps = iris_request("GET", args.iris_url, api_key, "manage/tlp/list")
    for tlp in tlps["data"]:
        if tlp["tlp_name"].lower() == tlp_name.lower():
            return int(tlp["tlp_id"])
    raise DevScriptError(f"Unable to resolve TLP named {tlp_name}")


def smoke_test(args: argparse.Namespace, api_key: str) -> dict[str, Any]:
    configure_summary = None
    if not args.skip_configure:
        configure_summary = configure_module(args, api_key)

    misp_env = get_misp_env(required=True)

    tlp_id = get_tlp_id(args, api_key, args.tlp_name)
    suffix = time.strftime("%Y%m%d-%H%M%S")

    case_payload = {
        "case_name": f"IRIS MISP Sync Validation {suffix}",
        "case_description": f"Runtime validation case for native MISP sync at {suffix}",
        "case_soc_id": f"iris-next-sync-{suffix}",
        "case_customer": args.customer_id,
        "case_tags": "sync-test,iris-next"
    }
    created_case = iris_request("POST", args.iris_url, api_key, "manage/cases/add", case_payload)
    case_data = created_case["data"]
    case_id = int(case_data["case_id"])
    event_id = wait_for_db_value(
        args.db_container,
        f"select misp_event_id from misp_event_link where case_id = {case_id};",
        db_name=args.db_name,
        db_user=args.db_user,
        timeout_seconds=args.timeout_seconds
    )

    event_link = db_query(
        args.db_container,
        f"select row_to_json(t) from ("
        f"select case_id, misp_event_id, misp_event_uuid, misp_org_id, misp_distribution, "
        f"misp_sharing_group_id, last_synced_at from misp_event_link where case_id = {case_id}"
        f") t;",
        db_name=args.db_name,
        db_user=args.db_user,
        tuples_only=True
    )
    misp_event = misp_request(
        "GET",
        misp_env["url"],
        misp_env["api_key"],
        f"events/view/{event_id}",
        verify_tls=misp_env["verify_tls"]
    )
    if misp_event["Event"]["info"] != case_data["case_name"]:
        raise DevScriptError("MISP event title does not match the created IRIS case name")

    ioc_payload = {
        "ioc_value": f"sync-{suffix}.example.org",
        "ioc_type_id": args.ioc_type_id,
        "ioc_description": "Initial IOC create validation for native MISP sync",
        "ioc_tlp_id": tlp_id,
        "ioc_tags": "sync-test,iris-next"
    }
    created_ioc = iris_request("POST", args.iris_url, api_key, f"case/ioc/add?cid={case_id}", ioc_payload)
    ioc_data = created_ioc["data"]
    ioc_id = int(ioc_data["ioc_id"])
    attribute_id = wait_for_db_value(
        args.db_container,
        f"select misp_attribute_id from misp_attribute_link where ioc_id = {ioc_id};",
        db_name=args.db_name,
        db_user=args.db_user,
        timeout_seconds=args.timeout_seconds
    )

    attribute_link = db_query(
        args.db_container,
        f"select row_to_json(t) from ("
        f"select ioc_id, misp_attribute_id, misp_attribute_uuid, last_synced_at "
        f"from misp_attribute_link where ioc_id = {ioc_id}"
        f") t;",
        db_name=args.db_name,
        db_user=args.db_user,
        tuples_only=True
    )
    ioc_row_before = db_query(
        args.db_container,
        f"select row_to_json(t) from ("
        f"select ioc_id, ioc_value, ioc_misp, ioc_tags, ioc_tlp_id, case_id from ioc where ioc_id = {ioc_id}"
        f") t;",
        db_name=args.db_name,
        db_user=args.db_user,
        tuples_only=True
    )
    misp_attribute_before = misp_request(
        "GET",
        misp_env["url"],
        misp_env["api_key"],
        f"attributes/view/{attribute_id}",
        verify_tls=misp_env["verify_tls"]
    )

    expected_tlp_tag = f"tlp:{args.tlp_name.lower()}"
    actual_tags_before = [tag["name"] for tag in misp_attribute_before["Attribute"].get("Tag", [])]
    if expected_tlp_tag not in actual_tags_before:
        raise DevScriptError(
            f"Expected MISP attribute to carry tag {expected_tlp_tag}, got {actual_tags_before}"
        )

    update_payload = {
        "ioc_value": f"sync-updated-{suffix}.example.org",
        "ioc_type_id": args.ioc_type_id,
        "ioc_description": "Updated IOC validation for native MISP sync",
        "ioc_tlp_id": tlp_id,
        "ioc_tags": "sync-test,iris-next,updated"
    }
    updated_ioc = iris_request(
        "POST",
        args.iris_url,
        api_key,
        f"case/ioc/update/{ioc_id}?cid={case_id}",
        update_payload
    )
    time.sleep(4)

    ioc_row_after = db_query(
        args.db_container,
        f"select row_to_json(t) from ("
        f"select ioc_id, ioc_value, ioc_misp, ioc_tags, ioc_tlp_id, case_id from ioc where ioc_id = {ioc_id}"
        f") t;",
        db_name=args.db_name,
        db_user=args.db_user,
        tuples_only=True
    )
    misp_attribute_after = misp_request(
        "GET",
        misp_env["url"],
        misp_env["api_key"],
        f"attributes/view/{attribute_id}",
        verify_tls=misp_env["verify_tls"]
    )
    actual_tags_after = [tag["name"] for tag in misp_attribute_after["Attribute"].get("Tag", [])]
    if "updated" not in actual_tags_after:
        raise DevScriptError("Expected updated IOC tag to be present on the MISP attribute")

    return {
        "configure": configure_summary,
        "case": case_data,
        "misp_event_id": int(event_id),
        "misp_event": {
            "id": int(misp_event["Event"]["id"]),
            "uuid": misp_event["Event"]["uuid"],
            "info": misp_event["Event"]["info"],
            "distribution": int(misp_event["Event"]["distribution"]),
            "sharing_group_id": int(misp_event["Event"]["sharing_group_id"]),
            "attribute_count": int(misp_event["Event"]["attribute_count"])
        },
        "misp_event_link": json.loads(event_link),
        "ioc_create": ioc_data,
        "misp_attribute_id": int(attribute_id),
        "misp_attribute_before_update": {
            "id": int(misp_attribute_before["Attribute"]["id"]),
            "uuid": misp_attribute_before["Attribute"]["uuid"],
            "value": misp_attribute_before["Attribute"]["value"],
            "distribution": int(misp_attribute_before["Attribute"]["distribution"]),
            "tags": actual_tags_before
        },
        "misp_attribute_link": json.loads(attribute_link),
        "ioc_row_before_update": json.loads(ioc_row_before),
        "ioc_update": updated_ioc["data"],
        "misp_attribute_after_update": {
            "id": int(misp_attribute_after["Attribute"]["id"]),
            "uuid": misp_attribute_after["Attribute"]["uuid"],
            "value": misp_attribute_after["Attribute"]["value"],
            "distribution": int(misp_attribute_after["Attribute"]["distribution"]),
            "tags": actual_tags_after
        },
        "ioc_row_after_update": json.loads(ioc_row_after),
        "expected_tlp_tag": expected_tlp_tag
    }


def build_tag_string(*tag_groups: str) -> str:
    seen: set[str] = set()
    tags: list[str] = []
    for group in tag_groups:
        if not group:
            continue
        for raw_tag in group.split(","):
            tag = raw_tag.strip()
            if not tag:
                continue
            key = tag.lower()
            if key in seen:
                continue
            seen.add(key)
            tags.append(tag)
    return ",".join(tags)


def parse_json_row(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    return json.loads(raw)


def list_cases(args: argparse.Namespace, api_key: str) -> list[dict[str, Any]]:
    return iris_request("GET", args.iris_url, api_key, "manage/cases/list")["data"]


def get_case_details(args: argparse.Namespace, api_key: str, case_id: int) -> dict[str, Any]:
    return iris_request("GET", args.iris_url, api_key, f"manage/cases/{case_id}")["data"]


def list_case_iocs(args: argparse.Namespace, api_key: str, case_id: int) -> list[dict[str, Any]]:
    return iris_request("GET", args.iris_url, api_key, f"case/ioc/list?cid={case_id}")["data"]["ioc"]


def list_case_assets(args: argparse.Namespace, api_key: str, case_id: int) -> list[dict[str, Any]]:
    return iris_request("GET", args.iris_url, api_key, f"case/assets/list?cid={case_id}")["data"]["assets"]


def list_case_tasks(args: argparse.Namespace, api_key: str, case_id: int) -> list[dict[str, Any]]:
    return iris_request("GET", args.iris_url, api_key, f"case/tasks/list?cid={case_id}")["data"]["tasks"]


def list_note_directories(args: argparse.Namespace, api_key: str, case_id: int) -> list[dict[str, Any]]:
    return iris_request("GET", args.iris_url, api_key, f"case/notes/directories/filter?cid={case_id}")["data"]


def list_case_timeline(args: argparse.Namespace, api_key: str, case_id: int) -> list[dict[str, Any]]:
    return iris_request("GET", args.iris_url, api_key, f"case/timeline/events/list?cid={case_id}")["data"]["timeline"]


def get_note_details(args: argparse.Namespace, api_key: str, case_id: int, note_id: int) -> dict[str, Any]:
    return iris_request("GET", args.iris_url, api_key, f"case/notes/{note_id}?cid={case_id}")["data"]


def get_lookup_rows(args: argparse.Namespace, api_key: str, path: str) -> list[dict[str, Any]]:
    return iris_request("GET", args.iris_url, api_key, path)["data"]


def resolve_named_id(
    rows: list[dict[str, Any]],
    wanted_name: str,
    *,
    name_keys: tuple[str, ...],
    id_keys: tuple[str, ...]
) -> int:
    wanted = wanted_name.strip().lower()
    for row in rows:
        for name_key in name_keys:
            value = row.get(name_key)
            if value is not None and str(value).strip().lower() == wanted:
                for id_key in id_keys:
                    if row.get(id_key) is not None:
                        return int(row[id_key])
    raise DevScriptError(f"Unable to resolve lookup id for {wanted_name}")


def find_directory(directories: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    wanted = name.strip().lower()
    for directory in directories:
        if directory.get("name", "").strip().lower() == wanted:
            return directory
    return None


def find_note(directory: dict[str, Any], title: str) -> dict[str, Any] | None:
    wanted = title.strip().lower()
    for note in directory.get("notes", []):
        if note.get("title", "").strip().lower() == wanted:
            return note
    return None


def find_task(tasks: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    wanted = title.strip().lower()
    for task in tasks:
        if task.get("task_title", "").strip().lower() == wanted:
            return task
    return None


def find_asset(assets: list[dict[str, Any]], asset_name: str) -> dict[str, Any] | None:
    wanted = asset_name.strip().lower()
    for asset in assets:
        if asset.get("asset_name", "").strip().lower() == wanted:
            return asset
    return None


def find_event(events: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    wanted = title.strip().lower()
    for event in events:
        if event.get("event_title", "").strip().lower() == wanted:
            return event
    return None


def find_primary_ioc(iocs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for ioc in iocs:
        if KNOWN_GOOD_IOC_MARKER in (ioc.get("ioc_tags") or ""):
            return ioc
    for ioc in iocs:
        if ioc.get("ioc_value") == KNOWN_GOOD_IOC_VALUE:
            return ioc
    for ioc in iocs:
        if ioc.get("ioc_misp"):
            return ioc
    if iocs:
        return iocs[0]
    return None


def ensure_case_info(args: argparse.Namespace, api_key: str, case_id: int) -> dict[str, Any]:
    payload = {
        "case_name": KNOWN_GOOD_CASE_NAME,
        "case_description": KNOWN_GOOD_CASE_DESCRIPTION,
        "case_soc_id": KNOWN_GOOD_CASE_SOC_ID,
        "case_tags": KNOWN_GOOD_CASE_TAGS
    }
    iris_request("POST", args.iris_url, api_key, f"manage/cases/update/{case_id}", payload)
    return get_case_details(args, api_key, case_id)


def ensure_primary_ioc(
    args: argparse.Namespace,
    api_key: str,
    case_id: int,
    *,
    ioc_type_id: int,
    tlp_id: int
) -> dict[str, Any]:
    iocs = list_case_iocs(args, api_key, case_id)
    existing = find_primary_ioc(iocs)
    payload = {
        "ioc_value": KNOWN_GOOD_IOC_VALUE,
        "ioc_type_id": ioc_type_id,
        "ioc_description": (
            "User reported a suspicious verification prompt that referenced this domain during "
            "local validation of the workflow."
        ),
        "ioc_tlp_id": tlp_id,
        "ioc_tags": build_tag_string("known-good,misp-sync,ui-fixture", KNOWN_GOOD_IOC_MARKER)
    }
    if existing:
        iris_request("POST", args.iris_url, api_key, f"case/ioc/update/{existing['ioc_id']}?cid={case_id}", payload)
    else:
        iris_request("POST", args.iris_url, api_key, f"case/ioc/add?cid={case_id}", payload)

    refreshed = list_case_iocs(args, api_key, case_id)
    primary = find_primary_ioc(refreshed)
    if not primary:
        raise DevScriptError("Unable to locate the known-good IOC after create/update")
    return primary


def ensure_asset(
    args: argparse.Namespace,
    api_key: str,
    case_id: int,
    *,
    asset_type_id: int,
    analysis_status_id: int,
    compromise_status_id: int,
    linked_ioc_ids: list[int]
) -> dict[str, Any]:
    assets = list_case_assets(args, api_key, case_id)
    existing = find_asset(assets, KNOWN_GOOD_ASSET_NAME)
    payload = {
        "asset_name": KNOWN_GOOD_ASSET_NAME,
        "asset_type_id": asset_type_id,
        "asset_description": "Finance workstation preserved as the stable local validation endpoint.",
        "asset_ip": "10.20.30.45",
        "asset_domain": "corp.example.local",
        "asset_tags": "known-good,finance,ui-fixture",
        "analysis_status_id": analysis_status_id,
        "asset_compromise_status_id": compromise_status_id,
        "ioc_links": linked_ioc_ids
    }
    if existing:
        iris_request("POST", args.iris_url, api_key, f"case/assets/update/{existing['asset_id']}?cid={case_id}", payload)
    else:
        iris_request("POST", args.iris_url, api_key, f"case/assets/add?cid={case_id}", payload)

    refreshed = list_case_assets(args, api_key, case_id)
    asset = find_asset(refreshed, KNOWN_GOOD_ASSET_NAME)
    if not asset:
        raise DevScriptError("Unable to locate the known-good asset after create/update")
    return asset


def ensure_task(
    args: argparse.Namespace,
    api_key: str,
    case_id: int,
    *,
    title: str,
    description: str,
    status_id: int,
    assignee_id: int,
    tags: str
) -> dict[str, Any]:
    tasks = list_case_tasks(args, api_key, case_id)
    existing = find_task(tasks, title)
    payload = {
        "task_title": title,
        "task_description": description,
        "task_status_id": status_id,
        "task_assignees_id": [assignee_id],
        "task_tags": tags
    }
    if existing:
        iris_request("POST", args.iris_url, api_key, f"case/tasks/update/{existing['task_id']}?cid={case_id}", payload)
    else:
        iris_request("POST", args.iris_url, api_key, f"case/tasks/add?cid={case_id}", payload)

    refreshed = list_case_tasks(args, api_key, case_id)
    task = find_task(refreshed, title)
    if not task:
        raise DevScriptError(f"Unable to locate task {title} after create/update")
    return task


def ensure_directory(args: argparse.Namespace, api_key: str, case_id: int, name: str) -> dict[str, Any]:
    directories = list_note_directories(args, api_key, case_id)
    existing = find_directory(directories, name)
    if existing:
        return existing

    payload = {
        "name": name,
        "description": "",
        "parent_id": None
    }
    iris_request("POST", args.iris_url, api_key, f"case/notes/directories/add?cid={case_id}", payload)
    refreshed = list_note_directories(args, api_key, case_id)
    directory = find_directory(refreshed, name)
    if not directory:
        raise DevScriptError(f"Unable to locate note directory {name} after creation")
    return directory


def ensure_note(
    args: argparse.Namespace,
    api_key: str,
    case_id: int,
    *,
    directory_name: str,
    note_title: str,
    note_content: str
) -> dict[str, Any]:
    directory = ensure_directory(args, api_key, case_id, directory_name)
    existing = find_note(directory, note_title)
    payload = {
        "directory_id": int(directory["id"]),
        "note_title": note_title,
        "note_content": note_content
    }
    if existing:
        iris_request("POST", args.iris_url, api_key, f"case/notes/update/{existing['id']}?cid={case_id}", payload)
        note_id = int(existing["id"])
    else:
        created = iris_request("POST", args.iris_url, api_key, f"case/notes/add?cid={case_id}", payload)
        note_id = int(created["data"]["note_id"])

    return get_note_details(args, api_key, case_id, note_id)


def ensure_event(
    args: argparse.Namespace,
    api_key: str,
    case_id: int,
    *,
    title: str,
    event_date: str,
    category_id: int,
    color: str,
    tags: str,
    content: str,
    asset_ids: list[int],
    ioc_ids: list[int],
    event_in_summary: bool,
    event_in_graph: bool
) -> dict[str, Any]:
    events = list_case_timeline(args, api_key, case_id)
    existing = find_event(events, title)
    payload = {
        "event_title": title,
        "event_date": event_date,
        "event_tz": "+00:00",
        "event_category_id": category_id,
        "event_assets": asset_ids,
        "event_iocs": ioc_ids,
        "event_content": content,
        "event_tags": tags,
        "event_color": color,
        "event_source": "iris-next known-good seed",
        "event_in_summary": event_in_summary,
        "event_in_graph": event_in_graph
    }
    if existing:
        iris_request(
            "POST",
            args.iris_url,
            api_key,
            f"case/timeline/events/update/{existing['event_id']}?cid={case_id}",
            payload
        )
    else:
        iris_request("POST", args.iris_url, api_key, f"case/timeline/events/add?cid={case_id}", payload)

    refreshed = list_case_timeline(args, api_key, case_id)
    event = find_event(refreshed, title)
    if not event:
        raise DevScriptError(f"Unable to locate timeline event {title} after create/update")
    return event


def build_known_good_lookup_ids(args: argparse.Namespace, api_key: str) -> dict[str, int]:
    users = get_lookup_rows(args, api_key, "manage/users/list")
    tlps = get_lookup_rows(args, api_key, "manage/tlp/list")
    ioc_types = get_lookup_rows(args, api_key, "manage/ioc-types/list")
    asset_types = get_lookup_rows(args, api_key, "manage/asset-type/list")
    analysis_status = get_lookup_rows(args, api_key, "manage/analysis-status/list")
    compromise_status = get_lookup_rows(args, api_key, "manage/compromise-status/list")
    task_status = get_lookup_rows(args, api_key, "manage/task-status/list")
    event_categories = get_lookup_rows(args, api_key, "manage/event-categories/list")

    return {
        "assignee_id": resolve_named_id(
            users,
            args.assignee_login,
            name_keys=("user_login", "user_name"),
            id_keys=("user_id",)
        ),
        "tlp_green_id": resolve_named_id(
            tlps,
            "green",
            name_keys=("tlp_name",),
            id_keys=("tlp_id",)
        ),
        "ioc_domain_id": resolve_named_id(
            ioc_types,
            "domain",
            name_keys=("type_name",),
            id_keys=("type_id",)
        ),
        "asset_windows_computer_id": resolve_named_id(
            asset_types,
            "Windows - Computer",
            name_keys=("asset_name",),
            id_keys=("asset_id",)
        ),
        "analysis_pending_id": resolve_named_id(
            analysis_status,
            "Pending",
            name_keys=("name",),
            id_keys=("id",)
        ),
        "compromise_compromised_id": resolve_named_id(
            compromise_status,
            "Compromised",
            name_keys=("name",),
            id_keys=("value",)
        ),
        "task_done_id": resolve_named_id(
            task_status,
            "Done",
            name_keys=("status_name",),
            id_keys=("id",)
        ),
        "task_in_progress_id": resolve_named_id(
            task_status,
            "In progress",
            name_keys=("status_name",),
            id_keys=("id",)
        ),
        "category_initial_access_id": resolve_named_id(
            event_categories,
            "Initial Access",
            name_keys=("name",),
            id_keys=("id",)
        ),
        "category_discovery_id": resolve_named_id(
            event_categories,
            "Discovery",
            name_keys=("name",),
            id_keys=("id",)
        ),
        "category_remediation_id": resolve_named_id(
            event_categories,
            "Remediation",
            name_keys=("name",),
            id_keys=("id",)
        )
    }


def get_case_and_ioc_misp_state(
    args: argparse.Namespace,
    *,
    case_id: int,
    ioc_id: int
) -> dict[str, Any]:
    event_link = parse_json_row(
        db_query(
            args.db_container,
            "select row_to_json(t) from ("
            f"select case_id, misp_event_id, misp_event_uuid, misp_org_id, misp_distribution, "
            f"misp_sharing_group_id, last_synced_at from misp_event_link where case_id = {case_id}"
            ") t;",
            db_name=args.db_name,
            db_user=args.db_user,
            tuples_only=True
        )
    )
    attribute_link = parse_json_row(
        db_query(
            args.db_container,
            "select row_to_json(t) from ("
            f"select ioc_id, misp_attribute_id, misp_attribute_uuid, last_synced_at "
            f"from misp_attribute_link where ioc_id = {ioc_id}"
            ") t;",
            db_name=args.db_name,
            db_user=args.db_user,
            tuples_only=True
        )
    )

    output: dict[str, Any] = {
        "event_link": event_link,
        "attribute_link": attribute_link
    }

    misp_env = get_misp_env(required=False)
    if misp_env and event_link and event_link.get("misp_event_id"):
        event_id = int(event_link["misp_event_id"])
        event = misp_request(
            "GET",
            misp_env["url"],
            misp_env["api_key"],
            f"events/view/{event_id}",
            verify_tls=misp_env["verify_tls"]
        )
        output["misp_event"] = {
            "id": int(event["Event"]["id"]),
            "uuid": event["Event"]["uuid"],
            "info": event["Event"]["info"],
            "distribution": int(event["Event"]["distribution"]),
            "sharing_group_id": int(event["Event"]["sharing_group_id"]),
            "attribute_count": int(event["Event"]["attribute_count"])
        }

    if misp_env and attribute_link and attribute_link.get("misp_attribute_id"):
        attribute_id = int(attribute_link["misp_attribute_id"])
        attribute = misp_request(
            "GET",
            misp_env["url"],
            misp_env["api_key"],
            f"attributes/view/{attribute_id}",
            verify_tls=misp_env["verify_tls"]
        )
        output["misp_attribute"] = {
            "id": int(attribute["Attribute"]["id"]),
            "uuid": attribute["Attribute"]["uuid"],
            "value": attribute["Attribute"]["value"],
            "distribution": int(attribute["Attribute"]["distribution"]),
            "tags": [tag["name"] for tag in attribute["Attribute"].get("Tag", [])]
        }

    return output


def seed_known_good_case(args: argparse.Namespace, api_key: str) -> dict[str, Any]:
    case_details = get_case_details(args, api_key, args.case_id)
    if not case_details:
        raise DevScriptError(f"Unable to load case {args.case_id}")

    lookups = build_known_good_lookup_ids(args, api_key)
    case_details = ensure_case_info(args, api_key, args.case_id)
    primary_ioc = ensure_primary_ioc(
        args,
        api_key,
        args.case_id,
        ioc_type_id=lookups["ioc_domain_id"],
        tlp_id=lookups["tlp_green_id"]
    )
    asset = ensure_asset(
        args,
        api_key,
        args.case_id,
        asset_type_id=lookups["asset_windows_computer_id"],
        analysis_status_id=lookups["analysis_pending_id"],
        compromise_status_id=lookups["compromise_compromised_id"],
        linked_ioc_ids=[int(primary_ioc["ioc_id"])]
    )

    ensured_notes = []
    for directory_name, note_content in KNOWN_GOOD_NOTE_CONTENT.items():
        ensured_notes.append(
            ensure_note(
                args,
                api_key,
                args.case_id,
                directory_name=directory_name,
                note_title=directory_name,
                note_content=note_content
            )
        )

    ensured_tasks = []
    for task_definition in KNOWN_GOOD_TASKS:
        status_key = "task_done_id" if task_definition["status_name"] == "Done" else "task_in_progress_id"
        ensured_tasks.append(
            ensure_task(
                args,
                api_key,
                args.case_id,
                title=task_definition["title"],
                description=task_definition["description"],
                status_id=lookups[status_key],
                assignee_id=lookups["assignee_id"],
                tags=task_definition["tags"]
            )
        )

    ensured_events = []
    for event_definition in KNOWN_GOOD_EVENTS:
        category_key = {
            "Initial Access": "category_initial_access_id",
            "Discovery": "category_discovery_id",
            "Remediation": "category_remediation_id"
        }[event_definition["category_name"]]
        ensured_events.append(
            ensure_event(
                args,
                api_key,
                args.case_id,
                title=event_definition["title"],
                event_date=event_definition["date"],
                category_id=lookups[category_key],
                color=event_definition["color"],
                tags=event_definition["tags"],
                content=event_definition["content"],
                asset_ids=[int(asset["asset_id"])],
                ioc_ids=[int(primary_ioc["ioc_id"])] if event_definition["include_ioc"] else [],
                event_in_summary=bool(event_definition["event_in_summary"]),
                event_in_graph=bool(event_definition["event_in_graph"])
            )
        )

    time.sleep(2)

    case_refresh = get_case_details(args, api_key, args.case_id)
    iocs = list_case_iocs(args, api_key, args.case_id)
    assets = list_case_assets(args, api_key, args.case_id)
    tasks = list_case_tasks(args, api_key, args.case_id)
    directories = list_note_directories(args, api_key, args.case_id)
    timeline = list_case_timeline(args, api_key, args.case_id)
    misp_state = get_case_and_ioc_misp_state(args, case_id=args.case_id, ioc_id=int(primary_ioc["ioc_id"]))

    return {
        "case": {
            "case_id": int(case_refresh["case_id"]),
            "case_name": case_refresh["case_name"],
            "case_soc_id": case_refresh["case_soc_id"],
            "case_tags": case_refresh.get("case_tags"),
            "case_description": case_refresh["case_description"]
        },
        "primary_ioc": primary_ioc,
        "asset": asset,
        "notes_seeded": [
            {
                "directory_id": int(note["directory_id"]),
                "note_id": int(note["note_id"]),
                "note_title": note["note_title"]
            }
            for note in ensured_notes
        ],
        "tasks_seeded": [
            {
                "task_id": int(task["task_id"]),
                "task_title": task["task_title"],
                "task_status_id": int(task["task_status_id"])
            }
            for task in ensured_tasks
        ],
        "timeline_seeded": [
            {
                "event_id": int(event["event_id"]),
                "event_title": event["event_title"],
                "event_category_id": int(event["event_category_id"])
            }
            for event in ensured_events
        ],
        "case_state": {
            "ioc_count": len(iocs),
            "asset_count": len(assets),
            "task_count": len(tasks),
            "note_directory_count": len(directories),
            "timeline_event_count": len(timeline)
        },
        "misp_state": misp_state
    }


def cleanup_smoke_cases(args: argparse.Namespace, api_key: str) -> dict[str, Any]:
    cases = list_cases(args, api_key)
    preserve_case_ids = set(args.preserve_case_ids or [])
    preserve_case_ids.add(args.case_id)

    misp_env = get_misp_env(required=False)
    deleted_cases: list[dict[str, Any]] = []
    skipped_cases: list[dict[str, Any]] = []

    for case in cases:
        case_id = int(case["case_id"])
        case_soc_id = case.get("case_soc_id") or ""
        if case_id in preserve_case_ids or not case_soc_id.startswith(args.soc_prefix):
            skipped_cases.append({
                "case_id": case_id,
                "case_name": case["case_name"],
                "reason": "preserved-or-not-smoke"
            })
            continue

        event_id_raw = db_query(
            args.db_container,
            f"select misp_event_id from misp_event_link where case_id = {case_id};",
            db_name=args.db_name,
            db_user=args.db_user,
            tuples_only=True
        ).strip()

        if event_id_raw and not misp_env:
            skipped_cases.append({
                "case_id": case_id,
                "case_name": case["case_name"],
                "reason": "linked-misp-event-but-no-misp-credentials"
            })
            continue

        if event_id_raw and misp_env:
            try:
                misp_request(
                    "DELETE",
                    misp_env["url"],
                    misp_env["api_key"],
                    f"events/delete/{int(event_id_raw)}",
                    verify_tls=misp_env["verify_tls"]
                )
            except DevScriptError as exc:
                try:
                    misp_request(
                        "GET",
                        misp_env["url"],
                        misp_env["api_key"],
                        f"events/view/{int(event_id_raw)}",
                        verify_tls=misp_env["verify_tls"]
                    )
                except DevScriptError:
                    pass
                else:
                    skipped_cases.append({
                        "case_id": case_id,
                        "case_name": case["case_name"],
                        "reason": f"misp-delete-failed: {exc}"
                    })
                    continue

        db_query(
            args.db_container,
            (
                "delete from misp_attribute_link "
                f"where ioc_id in (select ioc_id from ioc where case_id = {case_id});"
            ),
            db_name=args.db_name,
            db_user=args.db_user,
            tuples_only=False
        )
        db_query(
            args.db_container,
            f"delete from misp_event_link where case_id = {case_id};",
            db_name=args.db_name,
            db_user=args.db_user,
            tuples_only=False
        )
        iris_request("POST", args.iris_url, api_key, f"manage/cases/delete/{case_id}")
        deleted_cases.append({
            "case_id": case_id,
            "case_name": case["case_name"],
            "case_soc_id": case_soc_id,
            "misp_event_id": int(event_id_raw) if event_id_raw else None
        })

    return {
        "deleted_cases": deleted_cases,
        "skipped_cases": skipped_cases
    }


def test_ai_fallback(args: argparse.Namespace) -> dict[str, Any]:
    ai_env = get_ai_env()
    if ai_env is None:
        raise DevScriptError("AI_BACKEND_URL and AI_BACKEND_MODEL must be available via environment or .env")

    py_script = f"""
import json
from iris_misp_sync_module.ai_type_resolver import AITypeResolver, AITypeResolverError

resolver = AITypeResolver(
    base_url={ai_env['url']!r},
    api_key={ai_env['api_key']!r},
    model={ai_env['model']!r}
)
try:
    suggestion = resolver.resolve(
        raw_type={args.type!r},
        value={args.value!r},
        description={(args.description or '')!r},
        tags={(args.tags or '')!r},
        tlp={(args.tlp or '')!r}
    )
    print(json.dumps({{
        'ok': True,
        'threshold': {ai_env['confidence_threshold']},
        'accepted': suggestion['confidence'] >= {ai_env['confidence_threshold']},
        **suggestion
    }}, indent=2))
except AITypeResolverError as exc:
    print(json.dumps({{'ok': False, 'error': str(exc)}}, indent=2))
"""
    output = run_command(
        [
            "docker", "exec", "-i", args.app_container,
            "/bin/bash", "-lc", "/opt/venv/bin/python -"
        ],
        stdin=py_script
    ).strip()

    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise DevScriptError(
            f"Unable to parse AI fallback output from app container: {output[:500]}"
        ) from exc


def resync_ioc(args: argparse.Namespace) -> dict[str, Any]:
    """Re-sync a single IOC to MISP by calling IrisMISPSyncHandler.sync_ioc
    inline inside the app container's Flask context. Use this to recover
    IOCs that the on_postload_ioc_create hook silently dropped (e.g. the
    pre-fork-safety-fix concurrency bug, or a transient MISP outage).

    Bypasses celery entirely — the handler runs in the same process as
    this exec, so the prefork-fork-safety risk that's documented in
    `IrisMISPSyncInterface.hooks_handler` doesn't apply here.

    Returns a JSON summary including before/after misp_attribute_link
    state for the IOC, so it's obvious whether the call changed anything.
    """
    py_script = f"""
import json, logging
from app import app, db
from app.models.models import Ioc, IrisModule
from iris_misp_sync_module.IrisMISPSyncInterface import IrisMISPSyncHandler

ioc_id = {int(args.ioc_id)}
log = logging.getLogger("resync_ioc")

with app.app_context():
    ioc = Ioc.query.filter(Ioc.ioc_id == ioc_id).first()
    if ioc is None:
        print(json.dumps({{"ok": False, "error": f"IOC #{{ioc_id}} not found"}}))
        raise SystemExit
    if not ioc.case_id:
        print(json.dumps({{"ok": False, "error": f"IOC #{{ioc_id}} not attached to a case"}}))
        raise SystemExit

    before = db.session.execute(
        db.text("SELECT id, misp_attribute_id, misp_attribute_uuid, last_synced_at "
                "FROM misp_attribute_link WHERE ioc_id = :i"),
        {{"i": ioc_id}}
    ).fetchone()

    mod = IrisModule.query.filter(IrisModule.module_name == "iris_misp_sync_module").first()
    if mod is None:
        print(json.dumps({{"ok": False, "error": "iris_misp_sync_module not registered"}}))
        raise SystemExit
    cfg = {{p["param_name"]: p["value"] for p in (mod.module_config or [])}}

    handler = IrisMISPSyncHandler(mod_config=cfg, logger=log)
    try:
        handler.sync_ioc(ioc)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        print(json.dumps({{"ok": False, "error": f"sync_ioc raised: {{type(exc).__name__}}: {{exc}}"}}))
        raise SystemExit

    after = db.session.execute(
        db.text("SELECT id, misp_attribute_id, misp_attribute_uuid, last_synced_at "
                "FROM misp_attribute_link WHERE ioc_id = :i"),
        {{"i": ioc_id}}
    ).fetchone()

    def fmt(row):
        if row is None: return None
        return {{
            "id": row[0],
            "misp_attribute_id": row[1],
            "misp_attribute_uuid": row[2],
            "last_synced_at": row[3].isoformat() if row[3] else None,
        }}

    print(json.dumps({{
        "ok": True,
        "ioc_id": ioc_id,
        "ioc_value": ioc.ioc_value,
        "ioc_type_id": ioc.ioc_type_id,
        "case_id": ioc.case_id,
        "before": fmt(before),
        "after": fmt(after),
        "changed": (before is None) or (before[1] != after[1]) or (before[3] != after[3]),
    }}))
"""
    output = run_command(
        [
            "docker", "exec", "-i", args.app_container,
            "/bin/bash", "-lc", "/opt/venv/bin/python -"
        ],
        stdin=py_script
    ).strip()

    # The script prints a single JSON object on its last line. Logs from
    # IRIS's own logger may interleave above; pull just the JSON block.
    last_line = output.splitlines()[-1] if output else ""
    try:
        summary = json.loads(last_line)
    except json.JSONDecodeError as exc:
        raise DevScriptError(
            f"Unable to parse resync-ioc output from app container "
            f"(last line: {last_line[:300]!r})"
        ) from exc

    if not summary.get("ok"):
        raise DevScriptError(summary.get("error", "resync-ioc failed for unknown reasons"))
    return summary


def backfill_type_taxonomy(args: argparse.Namespace) -> dict[str, Any]:
    py_script = """
import json
from app import app
from app.misp_ioc_taxonomy import backfill_ioc_type_taxonomy
with app.app_context():
    print(json.dumps(backfill_ioc_type_taxonomy(), indent=2))
"""
    output = run_command(
        [
            "docker", "exec", "-i", args.app_container,
            "/bin/bash", "-lc", "/opt/venv/bin/python -"
        ],
        stdin=py_script
    ).strip()

    try:
        summary = json.loads(output)
    except json.JSONDecodeError as exc:
        raise DevScriptError(
            f"Unable to parse taxonomy backfill output from app container: {output[:300]}"
        ) from exc

    ioc_types = iris_request("GET", args.iris_url, args.iris_api_key, "manage/ioc-types/list")["data"]
    populated = [row for row in ioc_types if (row.get("type_taxonomy") or "").strip()]
    unresolved = [row["type_name"] for row in ioc_types if not (row.get("type_taxonomy") or "").strip()]

    summary["verification"] = {
        "populated_count": len(populated),
        "unresolved_count": len(unresolved),
        "unresolved_types": unresolved[:20]
    }
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local dev helper for configuring, validating, and maintaining IrisMISPSync."
    )
    parser.add_argument("--iris-url", default=DEFAULT_IRIS_URL, help="Base URL for the local IRIS app")
    parser.add_argument("--module-name", default=DEFAULT_MODULE_NAME, help="IRIS module human name")
    parser.add_argument("--app-container", default=DEFAULT_APP_CONTAINER, help="Docker app container name")
    parser.add_argument("--db-container", default=DEFAULT_DB_CONTAINER, help="Docker DB container name")
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME, help="PostgreSQL database name")
    parser.add_argument("--db-user", default=DEFAULT_DB_USER, help="PostgreSQL user")
    parser.add_argument(
        "--iris-api-key",
        default=None,
        help="Existing IRIS API key. If omitted, a temporary local admin key is minted from the app container."
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=40,
        help="How long to wait for async module work to land in the DB"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "configure",
        help="Configure and enable the IrisMISPSync module from local MISP settings"
    )

    smoke = subparsers.add_parser(
        "smoke-test",
        help="Run a local end-to-end IRIS case/IOC to MISP event/attribute validation"
    )
    smoke.add_argument("--customer-id", type=int, default=1, help="IRIS customer id for the test case")
    smoke.add_argument("--ioc-type-id", type=int, default=20, help="IRIS IOC type id for the test IOC")
    smoke.add_argument("--tlp-name", default="green", help="IRIS TLP name for the test IOC")
    smoke.add_argument(
        "--skip-configure",
        action="store_true",
        help="Skip module configuration and only run the smoke test"
    )

    cleanup = subparsers.add_parser(
        "cleanup-smoke",
        help="Delete throwaway iris-next smoke-test cases and their linked MISP events"
    )
    cleanup.add_argument(
        "--soc-prefix",
        default=DEFAULT_SMOKE_CASE_SOC_PREFIX,
        help="Case SOC id prefix that identifies throwaway smoke-test cases"
    )
    cleanup.add_argument(
        "--case-id",
        type=int,
        default=DEFAULT_KNOWN_GOOD_CASE_ID,
        help="Case id to preserve as the stable known-good case"
    )
    cleanup.add_argument(
        "--preserve-case-id",
        dest="preserve_case_ids",
        type=int,
        action="append",
        default=[],
        help="Additional case id to preserve. May be specified multiple times."
    )

    known_good = subparsers.add_parser(
        "seed-known-good",
        help="Populate Case #3 as the stable known-good local validation case"
    )
    known_good.add_argument(
        "--case-id",
        type=int,
        default=DEFAULT_KNOWN_GOOD_CASE_ID,
        help="Case id to turn into the stable known-good case"
    )
    known_good.add_argument(
        "--assignee-login",
        default=DEFAULT_ASSIGNEE_LOGIN,
        help="IRIS user login to assign the known-good tasks to"
    )

    subparsers.add_parser(
        "backfill-type-taxonomy",
        help="Backfill IocType.type_taxonomy from the bundled MISP attribute-type catalog"
    )

    resync = subparsers.add_parser(
        "resync-ioc",
        help="Re-sync one IOC to MISP via IrisMISPSyncHandler.sync_ioc — recovers from celery hook failures, MISP outages, or fork-safety crashes"
    )
    resync.add_argument(
        "--ioc-id",
        type=int,
        required=True,
        help="Ioc.ioc_id of the IOC to re-sync"
    )

    ai_test = subparsers.add_parser(
        "test-ai-fallback",
        help="Send a single IRIS-local IOC type to the configured AI backend and print the suggested MISP attribute type"
    )
    ai_test.add_argument(
        "--type",
        required=True,
        choices=["account", "file-path", "ip-any"],
        help="IRIS-local IOC type with no direct MISP mapping"
    )
    ai_test.add_argument("--value", required=True, help="IOC value to classify")
    ai_test.add_argument("--description", default="", help="Optional IOC description / context")
    ai_test.add_argument("--tags", default="", help="Optional comma-separated IOC tags")
    ai_test.add_argument("--tlp", default="", help="Optional IOC TLP name (e.g. amber)")

    return parser


def main():
    load_env_file(ENV_FILE)
    parser = build_parser()
    args = parser.parse_args()

    api_key = args.iris_api_key or mint_local_admin_api_key(args.app_container)

    try:
        if args.command == "configure":
            summary = configure_module(args, api_key)
        elif args.command == "smoke-test":
            summary = smoke_test(args, api_key)
        elif args.command == "cleanup-smoke":
            summary = cleanup_smoke_cases(args, api_key)
        elif args.command == "seed-known-good":
            summary = seed_known_good_case(args, api_key)
        elif args.command == "backfill-type-taxonomy":
            args.iris_api_key = api_key
            summary = backfill_type_taxonomy(args)
        elif args.command == "resync-ioc":
            summary = resync_ioc(args)
        elif args.command == "test-ai-fallback":
            summary = test_ai_fallback(args)
        else:
            raise DevScriptError(f"Unsupported command {args.command}")
    except DevScriptError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Seed a backdated 2025 test case for metrics/correlation/bar-chart testing.

Creates a realistic ransomware incident case with:
  - open_date backdated to 2025-11-04 (via direct DB update after create)
  - 4 IOCs  (domain + 2 IPs + file hash)
  - 2 assets (Windows server + workstation)
  - 4 timeline events (all in November 2025)
  - 1 note directory with a triage note
  - 2 tasks
  - DHS CIIP sector tag: healthcare
  - Case tags: ransomware, threat-actor, 2025-backfill

Usage:
    python scripts/seed_2025_test_case.py [--iris-url URL] [--dry-run]

The script mints a temporary API key for the local administrator account, calls
the IRIS API to create and populate the case, then patches open_date in Postgres
via docker exec.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APP_CONTAINER = "iriswebapp_app"
DEFAULT_DB_CONTAINER  = "iriswebapp_db"
DEFAULT_DB_NAME       = "iris_db"
DEFAULT_DB_USER       = "postgres"
DEFAULT_IRIS_URL      = "http://localhost:8000"

CASE_OPEN_DATE        = "2025-11-04"   # backdated open_date (DB patch)

# ---------------------------------------------------------------------------
# Case-level data
# ---------------------------------------------------------------------------

CASE_NAME        = "Ransomware Deployment — Healthcare PoC (2025 Backfill)"
CASE_SOC_ID      = "iris-next-2025-backfill-001"
CASE_DESCRIPTION = """\
On 2025-11-04, the security operations team detected encrypted file extensions and
ransom notes across the file shares at Healthbridge Medical Imaging.

Initial indicators pointed to a LockBit 3.0 affiliate using a stolen VPN credential
(MFA bypass) for initial access. Lateral movement to the domain controller was
confirmed within four hours. Data exfiltration to a known BleepingComputer-reported
C2 address preceded encryption by approximately 90 minutes.

This case is a backdated 2025 fixture for metrics, correlation, and bar-chart testing.
"""
CASE_TAGS = (
    "dhs-ciip-sectors:DHS-critical-sectors=\"Healthcare and Public Health\","
    "ransomware,lockbit,data-exfiltration,2025-backfill"
)
CASE_CUSTOMER_ID = 3   # 'Healthbridge Medical Imaging' — IrisInitialClient (1) is excluded from metrics

# ---------------------------------------------------------------------------
# IOC data
# ---------------------------------------------------------------------------

IOCS = [
    {
        "ioc_value": "hbr-file-shares.healthbridge-imaging.com",
        "ioc_type_name": "domain",
        "ioc_description": "Ransom note instructed victims to contact the attacker via this domain. Observed in LockBit 3.0 campaigns Q4 2025.",
        "ioc_tlp_name": "green",
        "ioc_tags": "ransomware,lockbit,c2",
    },
    {
        "ioc_value": "185.220.101.47",
        "ioc_type_name": "ip-dst",
        "ioc_description": "Exfiltration target confirmed in firewall logs. Associated with Tor exit node cluster used by LockBit affiliates.",
        "ioc_tlp_name": "green",
        "ioc_tags": "ransomware,exfiltration,tor-exit",
    },
    {
        "ioc_value": "10.20.30.5",
        "ioc_type_name": "ip-src",
        "ioc_description": "Domain controller (DC01) internal address. Lateral movement pivot point after initial VPN access.",
        "ioc_tlp_name": "green",
        "ioc_tags": "internal,lateral-movement,pivot",
    },
    {
        "ioc_value": "a3f2c1d8e9b740561e2f8a3c4d5e6f70",
        "ioc_type_name": "md5",
        "ioc_description": "LockBit 3.0 encryptor binary recovered from VPN jump host C:\\Windows\\Temp\\svchost32.exe.",
        "ioc_tlp_name": "green",
        "ioc_tags": "ransomware,malware,lockbit,encryptor",
    },
]

# ---------------------------------------------------------------------------
# Asset data
# ---------------------------------------------------------------------------

ASSETS = [
    {
        "asset_name": "DC01",
        "asset_type_name": "Windows - DC",
        "asset_ip": "10.20.30.5",
        "asset_domain": "healthbridge.local",
        "asset_description": "Primary domain controller. LockBit lateral movement pivot from VPN jump host.",
        "asset_tags": "critical,dc,lateral-movement,2025-backfill",
        "analysis_status_name": "Done",
        "compromise_status_name": "Compromised",
    },
    {
        "asset_name": "WS-RADIOLOGY-03",
        "asset_type_name": "Windows - Computer",
        "asset_ip": "10.20.30.88",
        "asset_domain": "healthbridge.local",
        "asset_description": "Radiology workstation. Encrypted files confirmed on local C:\\ and mapped share.",
        "asset_tags": "endpoint,encrypted,radiology,2025-backfill",
        "analysis_status_name": "Pending",
        "compromise_status_name": "Compromised",
    },
]

# ---------------------------------------------------------------------------
# Timeline events (all November 2025)
# ---------------------------------------------------------------------------

EVENTS = [
    {
        "event_title": "VPN authentication from unknown IP — MFA bypass suspected",
        "event_date": "2025-11-04T06:17:00.000000",
        "event_category_name": "Initial Access",
        "event_color": "#FFAD4699",
        "event_tags": "vpn,initial-access,mfa-bypass,lockbit",
        "event_content": (
            "Azure AD Conditional Access logged a successful authentication for "
            "`svc.imaging@healthbridge.local` from **185.220.101.47** (Tor exit). "
            "MFA was satisfied via a legacy RADIUS bypass that was not enforced on "
            "the VPN gateway.\n\n"
            "The session was the entry point for all subsequent attacker activity."
        ),
        "event_source": "Azure AD Sign-in logs",
        "asset_name": "DC01",
        "ioc_value": "185.220.101.47",
    },
    {
        "event_title": "Lateral movement to DC01 via PsExec",
        "event_date": "2025-11-04T08:44:00.000000",
        "event_category_name": "Lateral Movement",
        "event_color": "#F2596199",
        "event_tags": "lateral-movement,psexec,dc,lockbit",
        "event_content": (
            "Sysmon Event ID 1 on **DC01** recorded `psexec.exe` spawning "
            "`cmd.exe` under the `SYSTEM` account from the VPN jump host. "
            "The attacker used domain admin credentials obtained from the "
            "VPN gateway LSASS dump.\n\n"
            "Timestamp correlation places this 2h 27m after initial VPN login."
        ),
        "event_source": "Sysmon / Windows Security",
        "asset_name": "DC01",
        "ioc_value": "10.20.30.5",
    },
    {
        "event_title": "Data exfiltration to Tor exit node detected",
        "event_date": "2025-11-04T10:11:00.000000",
        "event_category_name": "Exfiltration",
        "event_color": "#F2596199",
        "event_tags": "exfiltration,tor,lockbit,data-theft",
        "event_content": (
            "Palo Alto firewall logged a sustained 4.2 GB outbound transfer from "
            "**DC01** to **185.220.101.47** over port 443. Traffic matched the "
            "LockBit 3.0 StealBit exfiltration profile (chunked encrypted blobs, "
            "no TLS SNI, 5-minute keep-alives).\n\n"
            "The transfer preceded file encryption by approximately 90 minutes."
        ),
        "event_source": "Palo Alto firewall",
        "asset_name": "DC01",
        "ioc_value": "185.220.101.47",
    },
    {
        "event_title": "LockBit encryptor deployed — file encryption begins",
        "event_date": "2025-11-04T11:47:00.000000",
        "event_category_name": "Impact",
        "event_color": "#E8461299",
        "event_tags": "encryption,ransomware,lockbit,impact",
        "event_content": (
            "EDR on **WS-RADIOLOGY-03** flagged mass file rename with `.lockbit3` "
            "extension. Recovery of `C:\\Windows\\Temp\\svchost32.exe` "
            "(MD5 `a3f2c1d8e9b740561e2f8a3c4d5e6f70`) confirmed the LockBit 3.0 encryptor.\n\n"
            "Ransom note `!!README.txt` dropped in every directory. Attacker "
            "contact domain: `hbr-file-shares.healthbridge-imaging.com`."
        ),
        "event_source": "CrowdStrike EDR",
        "asset_name": "WS-RADIOLOGY-03",
        "ioc_value": "a3f2c1d8e9b740561e2f8a3c4d5e6f70",
    },
]

# ---------------------------------------------------------------------------
# Note
# ---------------------------------------------------------------------------

NOTE_DIRECTORY = "Initial Triage"
NOTE_TITLE     = "Initial Triage"
NOTE_CONTENT   = """\
## Initial Triage Summary

| Field | Value |
|---|---|
| Case opened | 2025-11-04 06:30 UTC |
| Reported by | SOC Tier-2 on-call |
| Severity | Critical |
| Affected systems | DC01, file shares, 3+ workstations (radiology wing) |
| Ransomware family | LockBit 3.0 |

## IOC Status

| IOC | Type | Status | Source |
|---|---|---|---|
| hbr-file-shares.healthbridge-imaging.com | Domain | Active | Ransom note |
| 185[.]220[.]101[.]47 | IP (C2 / exfil) | Blocked | Firewall |
| 10[.]20[.]30[.]5 | IP (DC01) | Monitored | Internal |
| a3f2c1d8e9b740561e2f8a3c4d5e6f70 | MD5 | Isolated | EDR quarantine |

## Next Steps

- [ ] Pull full EVTX from DC01 and VPN gateway
- [ ] Confirm scope of encrypted shares (enumerate shares on DC01)
- [ ] Review MFA bypass configuration on Cisco AnyConnect gateway
- [ ] Submit LockBit binary to sandbox + VirusTotal
- [ ] Notify healthcare ISAC per DHS CIIP Healthcare reporting requirements

## Analyst Notes

MFA bypass via legacy RADIUS on the VPN is the root cause of initial access.
Recommend immediate remediation of the bypass before containment is lifted.

**Do not** restore from backup until the VPN gap is closed — LockBit affiliates
are known to re-enter via the same vector within 24h if the initial access path
remains open.
"""

# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

TASKS = [
    {
        "task_title": "Collect forensic images from DC01",
        "task_description": (
            "Mount and image DC01 C:\\ and SYSVOL before any remediation. "
            "Use KAPE with the !KAPE target for a triage collect, then a full E01 image. "
            "Preserve LSASS dump if still available in memory."
        ),
        "task_status_name": "Done",
        "task_tags": "forensics,dc,kape,2025-backfill",
    },
    {
        "task_title": "Enumerate encrypted file scope across file shares",
        "task_description": (
            "Run a PowerShell find across all DFS share mount points for `.lockbit3` extensions. "
            "Export to CSV for insurance / regulatory notification scope. "
            "Flag any shares containing PHI for mandatory breach notification assessment."
        ),
        "task_status_name": "In progress",
        "task_tags": "scope,phi,breach-notification,2025-backfill",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class SeedError(Exception):
    pass


def run_command(command: list[str], *, stdin: str | None = None) -> str:
    proc = subprocess.run(command, input=stdin, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SeedError(f"Command failed ({proc.returncode}): {' '.join(command)}\n{proc.stderr.strip()}")
    return proc.stdout


def mint_api_key(app_container: str) -> str:
    py_script = (
        "import secrets\n"
        "from app import app, db\n"
        "from app.models.authorization import User\n"
        "with app.app_context():\n"
        "    user = User.query.filter_by(user='administrator').first()\n"
        "    user.api_key = secrets.token_urlsafe(nbytes=64)\n"
        "    db.session.commit()\n"
        "    print(user.api_key)\n"
    )
    output = run_command(
        ["docker", "exec", "-i", app_container, "/bin/bash", "-lc", "/opt/venv/bin/python -"],
        stdin=py_script
    )
    pat = re.compile(r"^[A-Za-z0-9_-]{60,}$")
    for line in output.splitlines():
        candidate = line.strip()
        if pat.match(candidate):
            return candidate
    raise SeedError(f"Could not extract API key from: {output[:400]}")


def api(
    method: str,
    base_url: str,
    api_key: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    dry_run: bool = False,
    skip_status_check: bool = False,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    if dry_run and method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
        print(f"  [DRY-RUN] {method.upper()} {url}")
        if payload:
            print(f"            {json.dumps(payload, indent=2)[:400]}")
        return {}
    resp = requests.request(
        method=method,
        url=url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    try:
        body = resp.json() if resp.content else {}
    except ValueError as exc:
        raise SeedError(f"Non-JSON response from {method} {path}: {resp.text[:200]}") from exc
    if not resp.ok:
        raise SeedError(f"HTTP {resp.status_code} from {method} {path}: {body}")
    if not skip_status_check:
        status = body.get("status")
        if status and status != "success":
            raise SeedError(f"API error from {method} {path}: {body}")
    return body


def db_update(db_container: str, sql: str, db_name: str, db_user: str) -> None:
    run_command([
        "docker", "exec", db_container,
        "psql", "-U", db_user, "-d", db_name, "-c", sql
    ])


def lookup_rows(base_url: str, api_key: str, path: str) -> list[dict[str, Any]]:
    body = api("GET", base_url, api_key, path)
    data = body.get("data", body)
    if isinstance(data, dict):
        # some list endpoints return {id: {...}, ...}
        return list(data.values())
    return data or []


def resolve_id(
    rows: list[dict[str, Any]],
    value: str,
    *,
    name_keys: tuple[str, ...],
    id_keys: tuple[str, ...],
    case_insensitive: bool = True,
) -> int | None:
    target = value.lower() if case_insensitive else value
    for row in rows:
        for nk in name_keys:
            rv = str(row.get(nk, ""))
            if case_insensitive:
                rv = rv.lower()
            if rv == target:
                for ik in id_keys:
                    if row.get(ik) is not None:
                        return int(row[ik])
    return None


def require_id(rows, value, *, name_keys, id_keys, label) -> int:
    result = resolve_id(rows, value, name_keys=name_keys, id_keys=id_keys)
    if result is None:
        available = [str(row.get(name_keys[0], "?")) for row in rows[:20]]
        raise SeedError(f"Could not find {label}={value!r}. Available: {available}")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    print("Minting API key ...")
    api_key = mint_api_key(args.app_container)
    print(f"  API key minted (length: {len(api_key)})")

    # ----- Lookup tables -----
    print("Loading lookup tables ...")
    tlps              = lookup_rows(args.iris_url, api_key, "manage/tlp/list")
    ioc_types         = lookup_rows(args.iris_url, api_key, "manage/ioc-types/list")
    asset_types       = lookup_rows(args.iris_url, api_key, "manage/asset-type/list")
    analysis_statuses = lookup_rows(args.iris_url, api_key, "manage/analysis-status/list")
    compromise_statuses = lookup_rows(args.iris_url, api_key, "manage/compromise-status/list")
    task_statuses     = lookup_rows(args.iris_url, api_key, "manage/task-status/list")
    event_cats        = lookup_rows(args.iris_url, api_key, "manage/event-categories/list")
    users             = lookup_rows(args.iris_url, api_key, "manage/users/list")

    tlp_green_id = require_id(tlps, "green", name_keys=("tlp_name",), id_keys=("tlp_id",), label="TLP")
    assignee_id  = require_id(users, "administrator", name_keys=("user_login", "user_name"), id_keys=("user_id",), label="user")

    def ioc_type_id(name: str) -> int:
        return require_id(ioc_types, name, name_keys=("type_name",), id_keys=("type_id",), label="ioc_type")

    def asset_type_id(name: str) -> int:
        return require_id(asset_types, name, name_keys=("asset_name",), id_keys=("asset_id",), label="asset_type")

    def analysis_status_id(name: str) -> int:
        return require_id(analysis_statuses, name, name_keys=("name",), id_keys=("id",), label="analysis_status")

    def compromise_status_id(name: str) -> int:
        return require_id(compromise_statuses, name, name_keys=("name",), id_keys=("value",), label="compromise_status")

    def task_status_id(name: str) -> int:
        # The manage/task-status/list endpoint returns rows with 'status_name' (DB column name).
        return require_id(task_statuses, name, name_keys=("status_name", "task_status_name"), id_keys=("id",), label="task_status")

    def event_cat_id(name: str) -> int:
        return require_id(event_cats, name, name_keys=("name",), id_keys=("id",), label="event_category")

    # ----- Create case -----
    print(f"\nCreating case: {CASE_NAME!r} ...")
    created = api(
        "POST", args.iris_url, api_key,
        "manage/cases/add",
        {
            "case_name": CASE_NAME,
            "case_description": CASE_DESCRIPTION,
            "case_soc_id": CASE_SOC_ID,
            "case_customer": CASE_CUSTOMER_ID,
            "case_tags": CASE_TAGS,
        },
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print("  [DRY-RUN] Skipping all subsequent steps.")
        return

    case_data = created.get("data", {})
    case_id   = int(case_data["case_id"])
    print(f"  Created case #{case_id}")

    # ----- Backdate open_date in DB -----
    print(f"\nBackdating open_date to {CASE_OPEN_DATE} in Postgres ...")
    db_update(
        args.db_container,
        f"UPDATE cases SET open_date = '{CASE_OPEN_DATE}' WHERE case_id = {case_id};",
        args.db_name,
        args.db_user,
    )
    print("  Done.")

    # ----- IOCs -----
    print("\nAdding IOCs ...")
    ioc_id_map: dict[str, int] = {}
    for ioc_def in IOCS:
        body = api(
            "POST", args.iris_url, api_key,
            f"case/ioc/add?cid={case_id}",
            {
                "ioc_value": ioc_def["ioc_value"],
                "ioc_type_id": ioc_type_id(ioc_def["ioc_type_name"]),
                "ioc_description": ioc_def["ioc_description"],
                "ioc_tlp_id": tlp_green_id,
                "ioc_tags": ioc_def["ioc_tags"],
            },
        )
        ioc_obj = body.get("data", {}).get("ioc", body.get("data", {}))
        ioc_id_val = ioc_obj.get("ioc_id")
        if ioc_id_val:
            ioc_id_map[ioc_def["ioc_value"]] = int(ioc_id_val)
            print(f"  IOC #{ioc_id_val}: {ioc_def['ioc_value']}")
        else:
            print(f"  WARNING: no ioc_id returned for {ioc_def['ioc_value']}: {body}")

    # ----- Assets -----
    print("\nAdding assets ...")
    asset_id_map: dict[str, int] = {}
    for ast_def in ASSETS:
        body = api(
            "POST", args.iris_url, api_key,
            f"case/assets/add?cid={case_id}",
            {
                "asset_name": ast_def["asset_name"],
                "asset_type_id": asset_type_id(ast_def["asset_type_name"]),
                "asset_ip": ast_def["asset_ip"],
                "asset_domain": ast_def["asset_domain"],
                "asset_description": ast_def["asset_description"],
                "asset_tags": ast_def["asset_tags"],
                "analysis_status_id": analysis_status_id(ast_def["analysis_status_name"]),
                "asset_compromise_status_id": compromise_status_id(ast_def["compromise_status_name"]),
            },
        )
        asset_obj = body.get("data", {}).get("asset", body.get("data", {}))
        aid = asset_obj.get("asset_id")
        if aid:
            asset_id_map[ast_def["asset_name"]] = int(aid)
            print(f"  Asset #{aid}: {ast_def['asset_name']}")
        else:
            print(f"  WARNING: no asset_id returned for {ast_def['asset_name']}: {body}")

    # ----- Timeline events -----
    print("\nAdding timeline events ...")
    for ev in EVENTS:
        linked_asset_ids = [asset_id_map[ev["asset_name"]]] if ev["asset_name"] in asset_id_map else []
        linked_ioc_ids   = [ioc_id_map[ev["ioc_value"]]]   if ev["ioc_value"]   in ioc_id_map   else []
        body = api(
            "POST", args.iris_url, api_key,
            f"case/timeline/events/add?cid={case_id}",
            {
                "event_title":       ev["event_title"],
                "event_date":        ev["event_date"],
                "event_tz":          "+00:00",
                "event_category_id": event_cat_id(ev["event_category_name"]),
                "event_color":       ev["event_color"],
                "event_tags":        ev["event_tags"],
                "event_content":     ev["event_content"],
                "event_source":      ev["event_source"],
                "event_assets":      linked_asset_ids,
                "event_iocs":        linked_ioc_ids,
                "event_in_summary":  True,
                "event_in_graph":    True,
            },
        )
        ev_data = body.get("data", {})
        ev_id = ev_data.get("event_id")
        print(f"  Event #{ev_id}: {ev['event_title'][:60]}")

    # ----- Note -----
    print("\nAdding triage note ...")
    # Create the note directory first
    dir_body = api(
        "POST", args.iris_url, api_key,
        f"case/notes/directories/add?cid={case_id}",
        {"name": NOTE_DIRECTORY},
    )
    dir_data = dir_body.get("data", {})
    directory_id = dir_data.get("id") or dir_data.get("directory_id")

    if directory_id:
        note_body = api(
            "POST", args.iris_url, api_key,
            f"case/notes/add?cid={case_id}",
            {
                "note_title":   NOTE_TITLE,
                "note_content": NOTE_CONTENT,
                "directory_id": int(directory_id),
            },
        )
        note_id = note_body.get("data", {}).get("note_id")
        print(f"  Note #{note_id}: {NOTE_TITLE!r} in directory #{directory_id}")
    else:
        print(f"  WARNING: could not create note directory. Response: {dir_body}")

    # ----- Tasks -----
    print("\nAdding tasks ...")
    for task_def in TASKS:
        body = api(
            "POST", args.iris_url, api_key,
            f"case/tasks/add?cid={case_id}",
            {
                "task_title":        task_def["task_title"],
                "task_description":  task_def["task_description"],
                "task_status_id":    task_status_id(task_def["task_status_name"]),
                "task_assignees_id": [assignee_id],
                "task_tags":         task_def["task_tags"],
            },
        )
        task_id = body.get("data", {}).get("task_id")
        print(f"  Task #{task_id}: {task_def['task_title'][:60]}")

    # ----- Summary -----
    print(f"""
Done.
  Case #{case_id}: {CASE_NAME}
  SOC ID:  {CASE_SOC_ID}
  open_date: {CASE_OPEN_DATE}  (DB-patched)
  IOCs:    {len(ioc_id_map)}  Assets: {len(asset_id_map)}
  Events:  {len(EVENTS)}  Tasks: {len(TASKS)}
  URL: {args.iris_url.rstrip('/')}/case?cid={case_id}
""")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--iris-url",      default=DEFAULT_IRIS_URL,      help="Base URL for the local IRIS app")
    parser.add_argument("--app-container", default=DEFAULT_APP_CONTAINER, help="Docker container name for the app")
    parser.add_argument("--db-container",  default=DEFAULT_DB_CONTAINER,  help="Docker container name for Postgres")
    parser.add_argument("--db-name",       default=DEFAULT_DB_NAME)
    parser.add_argument("--db-user",       default=DEFAULT_DB_USER)
    parser.add_argument("--dry-run",       action="store_true",           help="Print API calls without executing them")
    args = parser.parse_args()

    try:
        run(args)
    except SeedError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Seed the dev environment with demo data for the customer "Wayne Enterprises".

Creates one customer and four backdated, interlinked incident cases so that the
dashboard Metrics tab, the IOC Correlation tab, and the case surfaces all have
realistic data to render.

  Customer  Wayne Enterprises   (sectors: critical-manufacturing, dib)
  Case 1    2026-03-12  Spear-phishing -> credential harvest (Applied Sciences)
  Case 2    2026-04-22  Cobalt Strike beacon on the manufacturing VLAN
  Case 3    2026-05-30  Insider exfiltration of WayneTech prototype schematics
  Case 4    2026-06-18  Business email compromise / wire-fraud attempt

Each case gets IOCs, assets, timeline events, a structured-Markdown triage note
and tasks. Several IOCs are deliberately shared between cases so the Correlation
tab forms a single four-case campaign cluster at the DEFAULT threshold:

  203.0.113.88              all four cases   (actor staging server)
  203.0.113.47              cases 1, 2, 4
  wayne-sso-verify.example  cases 1, 4
  <beacon sha256>           cases 2, 3

Correlation weights an edge by how many distinct IOC values a case PAIR shares
(min_shared, default 2) -- not by how many cases a single IOC appears in. The
staging-server indicator is what lifts every adjacent pair to weight 2.

All IOCs are written at TLP:GREEN because IOC correlation only considers
TLP green/clear (see business/ioc_correlation.py::_CORRELATABLE_TLP_IDS) --
seeding at the amber default would leave the Correlation tab empty.

All indicators are fictional and use reserved ranges (RFC 5737 TEST-NET
addresses and .example domains), so nothing here resolves or routes.

Usage:
    python scripts/seed_wayne_demo.py [--iris-url URL] [--dry-run]

Re-running is safe for the customer (it is looked up by name and reused), but
cases are always created fresh -- run it once, or delete the cases in between.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any

import requests

DEFAULT_APP_CONTAINER = "iriswebapp_app"
DEFAULT_DB_CONTAINER = "iriswebapp_db"
DEFAULT_DB_NAME = "iris_db"
DEFAULT_DB_USER = "postgres"
# docker-compose.dev.yml publishes the app container's 8000 on 127.0.0.1:18000.
# Override with --iris-url if your stack maps it elsewhere.
DEFAULT_IRIS_URL = "http://localhost:18000"

# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------

CUSTOMER_NAME = "Wayne Enterprises"
CUSTOMER_DESCRIPTION = (
    "Global conglomerate headquartered in Gotham City. In scope for IR: the "
    "Applied Sciences division, WayneTech R&D, and the Advanced Manufacturing "
    "plants. Demo customer -- all data is fictional."
)
CUSTOMER_SLA = "P1 response 30m / P2 response 4h, 24x7 retained IR."
# Slugs come from the sector picker in modal_add_customer.html; new cases
# inherit these as dhs-ciip-sectors machine-tags via business/cases.py.
CUSTOMER_SECTORS = "critical-manufacturing,dib"

# ---------------------------------------------------------------------------
# Shared indicators -- these are what make the correlation cluster form
# ---------------------------------------------------------------------------

SHARED_C2_IP = "203.0.113.47"
SHARED_PHISH_DOMAIN = "wayne-sso-verify.example"
SHARED_BEACON_SHA256 = "9f2c4a1e7b83d05f6a1c8e3b47d92f05ac6e18b3d47f2019c5ab83e6d17f40b2"
# Actor staging server seen in ALL four incidents. This one matters for the demo:
# correlation weights an edge by how many distinct IOC values a CASE PAIR shares
# (min_shared, default 2) -- NOT by how many cases an IOC appears in. Without a
# second indicator in common, most pairs sit at weight 1 and no cluster forms at
# the default threshold. With it, every adjacent pair reaches 2 and cases 1-4
# collapse into a single campaign cluster.
SHARED_STAGING_IP = "203.0.113.88"

STAGING_IOC = {
    "value": SHARED_STAGING_IP,
    "type": "ip-dst",
    "description": "Actor staging server; observed across all four Wayne Enterprises incidents.",
    "tags": "c2,staging,campaign-infrastructure",
}

# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

CASES: list[dict[str, Any]] = [
    {
        "name": "Spear-Phishing Campaign - Applied Sciences Credential Harvest",
        "soc_id": "WE-2026-0312-001",
        "open_date": "2026-03-12",
        "tags": ["phishing", "credential-access", "applied-sciences"],
        "description": (
            "On 2026-03-12 a targeted spear-phishing wave landed in 14 mailboxes "
            "across the Applied Sciences division. The lure impersonated the Wayne "
            "single sign-on portal and harvested credentials via a lookalike domain. "
            "Two users submitted credentials before the campaign was contained; one "
            "session was replayed from an external address the same evening."
        ),
        "iocs": [
            {"value": SHARED_PHISH_DOMAIN, "type": "domain",
             "description": "Lookalike SSO portal used to harvest Applied Sciences credentials.",
             "tags": "phishing,credential-harvest"},
            {"value": f"https://{SHARED_PHISH_DOMAIN}/auth/session/verify", "type": "url",
             "description": "Landing page linked from the phishing lure.",
             "tags": "phishing,landing-page"},
            {"value": SHARED_C2_IP, "type": "ip-dst",
             "description": "Source address that replayed the harvested session cookie.",
             "tags": "credential-access,session-replay"},
            {"value": "it-support@wayne-sso-verify.example", "type": "email-src",
             "description": "Sender address used across all 14 lures.",
             "tags": "phishing,sender"},
        ],
        "assets": [
            {"name": "WE-WKS-4471", "type": "Windows - Computer", "ip": "10.20.14.71",
             "domain": "corp.wayne-ent.example", "description": "Applied Sciences analyst workstation; first credential submission.",
             "tags": "applied-sciences,endpoint", "analysis": "Done", "compromise": "compromised"},
            {"name": "lfox@wayne-ent.example", "type": "Windows Account - AD", "ip": "",
             "domain": "corp.wayne-ent.example", "description": "Credentials submitted to the phishing portal; session later replayed.",
             "tags": "credential-access", "analysis": "Done", "compromise": "compromised"},
        ],
        "events": [
            {"title": "Phishing wave delivered to 14 Applied Sciences mailboxes",
             "date": "2026-03-12T08:41:00", "category": "Delivery", "color": "#ef4444",
             "source": "Proofpoint TAP", "tags": "phishing,delivery",
             "content": "14 near-identical messages impersonating the Wayne SSO portal. Sender domain registered 39 hours before delivery.",
             "asset": None, "ioc": "it-support@wayne-sso-verify.example"},
            {"title": "User clicked lure and reached the lookalike portal",
             "date": "2026-03-12T09:07:00", "category": "Social Engineering", "color": "#f97316",
             "source": "Zscaler proxy", "tags": "phishing,click",
             "content": "Proxy logged a GET to the fake SSO landing page from WE-WKS-4471.",
             "asset": "WE-WKS-4471", "ioc": f"https://{SHARED_PHISH_DOMAIN}/auth/session/verify"},
            {"title": "Credentials submitted to attacker-controlled portal",
             "date": "2026-03-12T09:08:00", "category": "Credential Access", "color": "#dc2626",
             "source": "Zscaler proxy", "tags": "credential-access",
             "content": "POST to the lookalike portal carrying form data. Account lfox confirmed as submitting user.",
             "asset": "lfox@wayne-ent.example", "ioc": SHARED_PHISH_DOMAIN},
            {"title": "Harvested session replayed from external address",
             "date": "2026-03-12T21:52:00", "category": "Initial Access", "color": "#dc2626",
             "source": "Entra ID sign-in logs", "tags": "session-replay,impossible-travel",
             "content": "Successful sign-in for lfox from 203.0.113.47 with a session token issued during the phishing window. Impossible-travel alert raised.",
             "asset": "lfox@wayne-ent.example", "ioc": SHARED_C2_IP},
        ],
        "note_dir": "Triage",
        "note_title": "Initial summary",
        "note": """\
## Summary

Targeted spear-phishing against the Applied Sciences division. 14 recipients,
2 credential submissions, 1 confirmed session replay. Contained within 14 hours
of first delivery.

## Indicators

| Indicator | Type | Notes |
| --- | --- | --- |
| `wayne-sso-verify[.]example` | domain | Lookalike SSO portal, registered 39h pre-delivery |
| `hxxps://wayne-sso-verify[.]example/auth/session/verify` | url | Credential-harvest landing page |
| `203.0.113[.]47` | ip-dst | Replayed the harvested session cookie |

## Assessment

Sender infrastructure and the replay address are shared with later Wayne
incidents -- see the correlation cluster. Treat as the same actor until ruled out.

## Next steps

- Force password reset + token revocation for all 14 recipients (done for lfox)
- Hunt for the replay address across the estate
- Submit the lookalike domain for takedown
""",
        "tasks": [
            {"title": "Revoke sessions and reset credentials for all lure recipients",
             "description": "All 14 recipients, not just the 2 confirmed submissions.",
             "status": "Done", "tags": "containment"},
            {"title": "Hunt 203.0.113.47 across VPN, Entra ID and proxy logs",
             "description": "Look for any other successful authentication from this address.",
             "status": "In progress", "tags": "hunting"},
            {"title": "Submit wayne-sso-verify.example for takedown",
             "description": "Registrar abuse contact + brand protection vendor.",
             "status": "To do", "tags": "remediation"},
        ],
    },
    {
        "name": "Cobalt Strike Beacon - Manufacturing VLAN",
        "soc_id": "WE-2026-0422-002",
        "open_date": "2026-04-22",
        "tags": ["cobalt-strike", "lateral-movement", "manufacturing"],
        "description": (
            "EDR flagged a beaconing implant on a manufacturing execution system "
            "host in the Advanced Manufacturing plant. The beacon called back to an "
            "address already seen in the March phishing incident. Lateral movement "
            "to a domain controller was attempted within six hours of first callback."
        ),
        "iocs": [
            {"value": SHARED_C2_IP, "type": "ip-dst",
             "description": "Beacon command-and-control endpoint; also seen in the March phishing case.",
             "tags": "c2,cobalt-strike"},
            {"value": SHARED_BEACON_SHA256, "type": "sha256",
             "description": "Cobalt Strike beacon loader dropped on the MES host.",
             "tags": "cobalt-strike,loader"},
            {"value": "cdn-wayne-updates.example", "type": "domain",
             "description": "Malleable C2 profile domain fronting the beacon traffic.",
             "tags": "c2,domain-fronting"},
        ],
        "assets": [
            {"name": "WE-SRV-MES02", "type": "Windows - Server", "ip": "10.40.8.12",
             "domain": "plant.wayne-ent.example", "description": "Manufacturing execution system host; beacon origin.",
             "tags": "manufacturing,ot-adjacent", "analysis": "Done", "compromise": "compromised"},
            {"name": "WE-SRV-DC01", "type": "Windows - DC", "ip": "10.40.1.10",
             "domain": "plant.wayne-ent.example", "description": "Plant domain controller; target of lateral movement attempt.",
             "tags": "domain-controller", "analysis": "Started", "compromise": "not_compromised"},
        ],
        "events": [
            {"title": "EDR flagged beaconing process on WE-SRV-MES02",
             "date": "2026-04-22T03:14:00", "category": "Command and Control", "color": "#dc2626",
             "source": "CrowdStrike Falcon", "tags": "cobalt-strike,beacon",
             "content": "Regular-interval callbacks with jitter consistent with a Cobalt Strike malleable profile.",
             "asset": "WE-SRV-MES02", "ioc": SHARED_C2_IP},
            {"title": "Beacon loader written to disk",
             "date": "2026-04-22T03:11:00", "category": "Execution", "color": "#f97316",
             "source": "CrowdStrike Falcon", "tags": "cobalt-strike,loader",
             "content": "Loader written to C:\\\\ProgramData\\\\Intel\\\\mesupd.dll and side-loaded by a signed binary.",
             "asset": "WE-SRV-MES02", "ioc": SHARED_BEACON_SHA256},
            {"title": "Credential dumping attempt against LSASS",
             "date": "2026-04-22T06:38:00", "category": "Credential Access", "color": "#dc2626",
             "source": "Sysmon EID 10", "tags": "lsass,credential-access",
             "content": "Handle request to lsass.exe from the beacon process. Blocked by attack-surface-reduction rule.",
             "asset": "WE-SRV-MES02", "ioc": None},
            {"title": "SMB lateral movement attempt to plant domain controller",
             "date": "2026-04-22T09:02:00", "category": "Lateral Movement", "color": "#dc2626",
             "source": "Windows Security 5145", "tags": "smb,lateral-movement",
             "content": "Repeated ADMIN$ share access attempts against WE-SRV-DC01. Denied -- the account lacked local admin on the DC.",
             "asset": "WE-SRV-DC01", "ioc": None},
        ],
        "note_dir": "Triage",
        "note_title": "Initial summary",
        "note": """\
## Summary

Cobalt Strike beacon on a manufacturing execution system host, calling back to
`203.0.113[.]47` -- the same address that replayed a harvested session in the
March Applied Sciences phishing case. Lateral movement to the plant DC was
attempted and failed.

## Indicators

| Indicator | Type | Notes |
| --- | --- | --- |
| `203.0.113[.]47` | ip-dst | Beacon C2; shared with WE-2026-0312-001 |
| `9f2c4a1e...f40b2` | sha256 | Beacon loader, side-loaded via signed binary |
| `cdn-wayne-updates[.]example` | domain | Malleable C2 profile domain |

## Assessment

Shared C2 infrastructure with the March incident raises confidence that
credential theft in March enabled this access. The MES host sits adjacent to the
OT boundary -- treat containment as time-critical.

## Next steps

- Isolate WE-SRV-MES02 and image before reboot
- Confirm no OT-side traversal past the plant boundary firewall
- Correlate the loader hash against the WayneTech R&D estate
""",
        "tasks": [
            {"title": "Isolate and image WE-SRV-MES02",
             "description": "Memory capture before any reboot; beacon is memory-resident.",
             "status": "Done", "tags": "containment,forensics"},
            {"title": "Verify OT boundary firewall was not traversed",
             "description": "Review plant boundary logs for the full beacon window.",
             "status": "In progress", "tags": "ot,scoping"},
            {"title": "Sweep estate for the beacon loader hash",
             "description": "EDR retro-hunt across all Wayne subsidiaries.",
             "status": "In progress", "tags": "hunting"},
        ],
    },
    {
        "name": "Insider Exfiltration - WayneTech Prototype Schematics",
        "soc_id": "WE-2026-0530-003",
        "open_date": "2026-05-30",
        "tags": ["insider-threat", "exfiltration", "waynetech"],
        "description": (
            "DLP flagged a departing WayneTech R&D engineer staging and uploading "
            "prototype schematics to an anonymous file-sharing service in the two "
            "weeks before their resignation took effect. The same loader hash from "
            "the April beacon incident was later found on the engineer's workstation, "
            "leaving deliberate insider action versus compromised endpoint unresolved."
        ),
        "iocs": [
            {"value": "filedrop-anon.example", "type": "domain",
             "description": "Anonymous file-sharing service used for the upload.",
             "tags": "exfiltration,file-sharing"},
            {"value": SHARED_BEACON_SHA256, "type": "sha256",
             "description": "Same loader hash seen on the manufacturing beacon host -- attribution unresolved.",
             "tags": "cobalt-strike,loader,unresolved"},
            {"value": "rsionis@wayne-ent.example", "type": "account",
             "description": "Departing R&D engineer; subject of the DLP alerts.",
             "tags": "insider-threat"},
        ],
        "assets": [
            {"name": "WE-WKS-2210", "type": "Windows - Computer", "ip": "10.30.22.10",
             "domain": "rnd.wayne-ent.example", "description": "R&D engineering workstation used to stage the archive.",
             "tags": "waynetech,endpoint", "analysis": "Started", "compromise": "to_be_determined"},
            {"name": "WE-FS-RND01", "type": "Windows - Server", "ip": "10.30.1.40",
             "domain": "rnd.wayne-ent.example", "description": "R&D file server holding the prototype schematics.",
             "tags": "waynetech,file-server", "analysis": "Done", "compromise": "not_compromised"},
        ],
        "events": [
            {"title": "Bulk access to prototype schematics share",
             "date": "2026-05-18T17:22:00", "category": "Collection", "color": "#f97316",
             "source": "Windows Security 5145", "tags": "collection,dlp",
             "content": "412 files read from the restricted schematics share in under 9 minutes -- far outside the user's baseline.",
             "asset": "WE-FS-RND01", "ioc": "rsionis@wayne-ent.example"},
            {"title": "Archive staged to local disk",
             "date": "2026-05-18T17:36:00", "category": "Collection", "color": "#f59e0b",
             "source": "Sysmon EID 11", "tags": "staging",
             "content": "Encrypted 7z archive written to the user profile temp directory.",
             "asset": "WE-WKS-2210", "ioc": None},
            {"title": "Upload to anonymous file-sharing service",
             "date": "2026-05-18T18:04:00", "category": "Exfiltration", "color": "#dc2626",
             "source": "Zscaler proxy", "tags": "exfiltration",
             "content": "1.8 GB HTTPS POST to filedrop-anon[.]example. DLP alerted on archive signature.",
             "asset": "WE-WKS-2210", "ioc": "filedrop-anon.example"},
            {"title": "April beacon loader hash found on the same workstation",
             "date": "2026-05-30T11:15:00", "category": "Discovery", "color": "#dc2626",
             "source": "CrowdStrike retro-hunt", "tags": "cobalt-strike,unresolved",
             "content": "Retro-hunt matched the WE-2026-0422-002 loader hash on WE-WKS-2210, predating the exfiltration by 11 days. Insider action versus prior compromise is unresolved.",
             "asset": "WE-WKS-2210", "ioc": SHARED_BEACON_SHA256},
        ],
        "note_dir": "Triage",
        "note_title": "Initial summary",
        "note": """\
## Summary

Departing WayneTech R&D engineer staged and uploaded 1.8 GB of prototype
schematics to `filedrop-anon[.]example` on 2026-05-18. A retro-hunt on
2026-05-30 then matched the April beacon loader hash on the same workstation,
predating the upload by 11 days.

## Indicators

| Indicator | Type | Notes |
| --- | --- | --- |
| `filedrop-anon[.]example` | domain | Anonymous upload destination |
| `9f2c4a1e...f40b2` | sha256 | Same loader as WE-2026-0422-002 |
| `rsionis@wayne-ent[.]example` | account | Departing engineer, DLP subject |

## Assessment

**Deliberate insider action versus compromised endpoint is unresolved.** The
loader predates the exfiltration, which is consistent with an external actor
using the engineer's host -- but it does not rule out the engineer installing it.
Do not characterise intent in reporting until the timeline gap is closed.

## Next steps

- Legal hold on WE-WKS-2210 and the user's mailbox
- Full disk image and manual review of the 11-day gap
- Preservation request to the file-sharing service
""",
        "tasks": [
            {"title": "Legal hold on workstation and mailbox",
             "description": "Coordinate with Wayne Legal before any further user contact.",
             "status": "Done", "tags": "legal,preservation"},
            {"title": "Close the 11-day gap between loader and exfiltration",
             "description": "Determine whether the loader or the user drove the collection activity.",
             "status": "In progress", "tags": "forensics,attribution"},
            {"title": "Preservation request to filedrop-anon.example",
             "description": "Via counsel; include upload timestamp and archive size.",
             "status": "To do", "tags": "legal"},
        ],
    },
    {
        "name": "Business Email Compromise - Wayne Foundation Wire Fraud Attempt",
        "soc_id": "WE-2026-0618-004",
        "open_date": "2026-06-18",
        "tags": ["bec", "wire-fraud", "wayne-foundation"],
        "description": (
            "A Wayne Foundation finance controller received a wire-transfer request "
            "impersonating the CFO, sent from infrastructure previously used in the "
            "March phishing campaign. The transfer was halted at the callback-"
            "verification step; no funds left the account."
        ),
        "iocs": [
            {"value": SHARED_PHISH_DOMAIN, "type": "domain",
             "description": "Same lookalike domain used in the March credential-harvest campaign.",
             "tags": "bec,phishing"},
            {"value": SHARED_C2_IP, "type": "ip-dst",
             "description": "Sending infrastructure; shared with the March and April incidents.",
             "tags": "bec,c2"},
            {"value": "198.51.100.23", "type": "ip-dst",
             "description": "Secondary sender address used for the follow-up pressure email.",
             "tags": "bec,sender"},
        ],
        "assets": [
            {"name": "afreeze@wayne-ent.example", "type": "Windows Account - AD", "ip": "",
             "domain": "foundation.wayne-ent.example", "description": "Wayne Foundation finance controller; BEC target.",
             "tags": "wayne-foundation,finance", "analysis": "Done", "compromise": "not_compromised"},
            {"name": "WE-WKS-8802", "type": "Windows - Computer", "ip": "10.50.6.2",
             "domain": "foundation.wayne-ent.example", "description": "Controller workstation; no compromise identified.",
             "tags": "wayne-foundation,endpoint", "analysis": "Done", "compromise": "not_compromised"},
        ],
        "events": [
            {"title": "Wire-transfer request impersonating the CFO received",
             "date": "2026-06-18T10:12:00", "category": "Social Engineering", "color": "#f97316",
             "source": "Microsoft Defender for Office 365", "tags": "bec,impersonation",
             "content": "Display-name impersonation of the CFO requesting a same-day USD 480,000 transfer to a new beneficiary.",
             "asset": "afreeze@wayne-ent.example", "ioc": SHARED_PHISH_DOMAIN},
            {"title": "Follow-up pressure email from secondary address",
             "date": "2026-06-18T10:41:00", "category": "Social Engineering", "color": "#f59e0b",
             "source": "Microsoft Defender for Office 365", "tags": "bec,pressure",
             "content": "Second message urging same-day settlement and discouraging verbal confirmation.",
             "asset": "afreeze@wayne-ent.example", "ioc": "198.51.100.23"},
            {"title": "Controller triggered out-of-band callback verification",
             "date": "2026-06-18T11:03:00", "category": "Remediation", "color": "#22c55e",
             "source": "Analyst account", "tags": "bec,contained",
             "content": "Controller followed policy and called the CFO on a known-good number. Request confirmed fraudulent; transfer halted before release.",
             "asset": "afreeze@wayne-ent.example", "ioc": None},
            {"title": "Sender infrastructure linked to March campaign",
             "date": "2026-06-18T14:20:00", "category": "Discovery", "color": "#dc2626",
             "source": "Analyst account", "tags": "correlation",
             "content": "Sending domain and address both match indicators from WE-2026-0312-001.",
             "asset": None, "ioc": SHARED_C2_IP},
        ],
        "note_dir": "Triage",
        "note_title": "Initial summary",
        "note": """\
## Summary

BEC wire-fraud attempt against the Wayne Foundation. USD 480,000 transfer
requested via CFO display-name impersonation; halted at callback verification.
**No funds left the account.**

## Indicators

| Indicator | Type | Notes |
| --- | --- | --- |
| `wayne-sso-verify[.]example` | domain | Same lookalike as WE-2026-0312-001 |
| `203.0.113[.]47` | ip-dst | Shared with March and April incidents |
| `198.51.100[.]23` | ip-dst | Secondary pressure-email sender |

## Assessment

Third Wayne incident using `203.0.113[.]47`. The actor has now been observed in
credential harvesting, hands-on-keyboard intrusion, and financial fraud against
the same parent organisation -- consistent with one campaign rather than three
unrelated events.

## Next steps

- Brief the Foundation board on the callback control that worked
- Add both sender addresses to the mail gateway block list
- Feed the full indicator set to the campaign cluster
""",
        "tasks": [
            {"title": "Block sender infrastructure at the mail gateway",
             "description": "Both sending addresses plus the lookalike domain.",
             "status": "Done", "tags": "containment"},
            {"title": "Brief Foundation leadership on the successful callback control",
             "description": "The out-of-band verification policy is what stopped this.",
             "status": "To do", "tags": "reporting"},
        ],
    },
]


class SeedError(RuntimeError):
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
        stdin=py_script,
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
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    if dry_run and method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
        print(f"  [DRY-RUN] {method.upper()} {url}")
        if payload:
            print(f"            {json.dumps(payload)[:200]}")
        return {}
    resp = requests.request(
        method=method,
        url=url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    try:
        body = resp.json() if resp.content else {}
    except ValueError as exc:
        raise SeedError(f"Non-JSON response from {method} {path}: {resp.text[:200]}") from exc
    if not resp.ok:
        raise SeedError(f"HTTP {resp.status_code} from {method} {path}: {body}")
    status = body.get("status")
    if status and status != "success":
        raise SeedError(f"API error from {method} {path}: {body}")
    return body


def db_update(db_container: str, sql: str, db_name: str, db_user: str) -> None:
    run_command(["docker", "exec", db_container, "psql", "-U", db_user, "-d", db_name, "-c", sql])


def lookup_rows(base_url: str, api_key: str, path: str) -> list[dict[str, Any]]:
    body = api("GET", base_url, api_key, path)
    data = body.get("data", body)
    if isinstance(data, dict):
        for key in ("data", "customers", "rows"):
            if isinstance(data.get(key), list):
                return data[key]
        return []
    return data if isinstance(data, list) else []


def require_id(rows, value, *, name_keys, id_keys, label) -> int:
    """Resolve a lookup-table row by name -> id. Never hardcode these ids: they
    differ per deployment."""
    target = str(value).strip().lower()
    for row in rows:
        for nk in name_keys:
            if nk in row and str(row[nk]).strip().lower() == target:
                for ik in id_keys:
                    if ik in row and row[ik] is not None:
                        return int(row[ik])
    raise SeedError(f"Could not resolve {label} named {value!r}. Available: "
                    f"{[r.get(name_keys[0]) for r in rows][:20]}")


def ensure_customer(base_url: str, api_key: str, *, dry_run: bool) -> int:
    """Look the customer up by name and reuse it; create only if absent."""
    existing = lookup_rows(base_url, api_key, "manage/customers/list")
    for row in existing:
        name = row.get("customer_name") or row.get("name")
        if name and name.strip().lower() == CUSTOMER_NAME.lower():
            cid = row.get("customer_id") or row.get("client_id")
            print(f"  Customer already exists: #{cid} {CUSTOMER_NAME!r} (reusing)")
            return int(cid)

    body = api(
        "POST", base_url, api_key, "manage/customers/add",
        {
            "customer_name": CUSTOMER_NAME,
            "customer_description": CUSTOMER_DESCRIPTION,
            "customer_sla": CUSTOMER_SLA,
            "customer_dhs_sectors": CUSTOMER_SECTORS,
        },
        dry_run=dry_run,
    )
    if dry_run:
        return -1
    data = body.get("data", {})
    cid = data.get("customer_id") or data.get("client_id")
    if not cid:
        raise SeedError(f"No customer id returned: {body}")
    print(f"  Created customer #{cid}: {CUSTOMER_NAME}")
    return int(cid)


def run(args: argparse.Namespace) -> None:
    print("Minting API key ...")
    api_key = mint_api_key(args.app_container)
    print(f"  API key minted (length: {len(api_key)})")

    print("\nLoading lookup tables ...")
    tlps = lookup_rows(args.iris_url, api_key, "manage/tlp/list")
    ioc_types = lookup_rows(args.iris_url, api_key, "manage/ioc-types/list")
    asset_types = lookup_rows(args.iris_url, api_key, "manage/asset-type/list")
    analysis_statuses = lookup_rows(args.iris_url, api_key, "manage/analysis-status/list")
    compromise_statuses = lookup_rows(args.iris_url, api_key, "manage/compromise-status/list")
    task_statuses = lookup_rows(args.iris_url, api_key, "manage/task-status/list")
    event_cats = lookup_rows(args.iris_url, api_key, "manage/event-categories/list")
    users = lookup_rows(args.iris_url, api_key, "manage/users/list")

    # TLP:GREEN -- required for the IOC Correlation tab to consider these IOCs.
    tlp_green_id = require_id(tlps, "green", name_keys=("tlp_name",), id_keys=("tlp_id",), label="TLP")
    assignee_id = require_id(users, "administrator",
                             name_keys=("user_login", "user_name", "user"), id_keys=("user_id", "id"), label="user")

    def ioc_type_id(name):
        return require_id(ioc_types, name, name_keys=("type_name",), id_keys=("type_id",), label="ioc_type")

    def asset_type_id(name):
        return require_id(asset_types, name, name_keys=("asset_name",), id_keys=("asset_id",), label="asset_type")

    def analysis_status_id(name):
        return require_id(analysis_statuses, name, name_keys=("name",), id_keys=("id",), label="analysis_status")

    def compromise_status_id(name):
        # The API returns display names ("Not compromised"), while the model enum
        # uses snake_case ("not_compromised"). Accept either.
        return require_id(compromise_statuses, name.replace("_", " "),
                          name_keys=("name",), id_keys=("value", "id"), label="compromise_status")

    def task_status_id(name):
        return require_id(task_statuses, name, name_keys=("status_name", "task_status_name"), id_keys=("id",), label="task_status")

    def event_cat_id(name):
        return require_id(event_cats, name, name_keys=("name",), id_keys=("id",), label="event_category")

    print(f"\nEnsuring customer {CUSTOMER_NAME!r} ...")
    customer_id = ensure_customer(args.iris_url, api_key, dry_run=args.dry_run)

    created_cases: list[tuple[int, str]] = []

    for spec in CASES:
        print(f"\n=== {spec['name']} ===")
        created = api(
            "POST", args.iris_url, api_key, "manage/cases/add",
            {
                "case_name": spec["name"],
                "case_description": spec["description"],
                "case_soc_id": spec["soc_id"],
                "case_customer": customer_id,
                "case_tags": ",".join(spec["tags"]),
            },
            dry_run=args.dry_run,
        )
        if args.dry_run:
            print("  [DRY-RUN] skipping child objects for this case")
            continue

        case_id = int(created.get("data", {})["case_id"])
        created_cases.append((case_id, spec["name"]))
        print(f"  Created case #{case_id}")

        # open_date drives the Metrics tab's time buckets; the API always stamps
        # "now", so backdate it directly.
        db_update(args.db_container,
                  f"UPDATE cases SET open_date = '{spec['open_date']}' WHERE case_id = {case_id};",
                  args.db_name, args.db_user)
        print(f"  Backdated open_date -> {spec['open_date']}")

        ioc_ids: dict[str, int] = {}
        # STAGING_IOC is appended to every case on purpose -- see its definition.
        for ioc in spec["iocs"] + [STAGING_IOC]:
            body = api("POST", args.iris_url, api_key, f"case/ioc/add?cid={case_id}",
                       {
                           "ioc_value": ioc["value"],
                           "ioc_type_id": ioc_type_id(ioc["type"]),
                           "ioc_description": ioc["description"],
                           "ioc_tlp_id": tlp_green_id,
                           "ioc_tags": ioc["tags"],
                       })
            obj = body.get("data", {}).get("ioc", body.get("data", {}))
            if obj.get("ioc_id"):
                ioc_ids[ioc["value"]] = int(obj["ioc_id"])
        print(f"  IOCs: {len(ioc_ids)}")

        asset_ids: dict[str, int] = {}
        for ast in spec["assets"]:
            body = api("POST", args.iris_url, api_key, f"case/assets/add?cid={case_id}",
                       {
                           "asset_name": ast["name"],
                           "asset_type_id": asset_type_id(ast["type"]),
                           "asset_ip": ast["ip"],
                           "asset_domain": ast["domain"],
                           "asset_description": ast["description"],
                           "asset_tags": ast["tags"],
                           "analysis_status_id": analysis_status_id(ast["analysis"]),
                           "asset_compromise_status_id": compromise_status_id(ast["compromise"]),
                       })
            obj = body.get("data", {}).get("asset", body.get("data", {}))
            if obj.get("asset_id"):
                asset_ids[ast["name"]] = int(obj["asset_id"])
        print(f"  Assets: {len(asset_ids)}")

        n_events = 0
        for ev in spec["events"]:
            api("POST", args.iris_url, api_key, f"case/timeline/events/add?cid={case_id}",
                {
                    "event_title": ev["title"],
                    # CaseEventsSchema requires "%Y-%m-%dT%H:%M:%S.%f" -- the
                    # microseconds are not optional, a bare seconds timestamp 400s.
                    "event_date": ev["date"] if "." in ev["date"] else f"{ev['date']}.000000",
                    "event_tz": "+00:00",
                    "event_category_id": event_cat_id(ev["category"]),
                    "event_color": ev["color"],
                    "event_tags": ev["tags"],
                    "event_content": ev["content"],
                    "event_source": ev["source"],
                    "event_assets": [asset_ids[ev["asset"]]] if ev.get("asset") in asset_ids else [],
                    "event_iocs": [ioc_ids[ev["ioc"]]] if ev.get("ioc") in ioc_ids else [],
                    "event_in_summary": True,
                    "event_in_graph": True,
                })
            n_events += 1
        print(f"  Timeline events: {n_events}")

        dir_body = api("POST", args.iris_url, api_key,
                       f"case/notes/directories/add?cid={case_id}", {"name": spec["note_dir"]})
        dir_data = dir_body.get("data", {})
        directory_id = dir_data.get("id") or dir_data.get("directory_id")
        if directory_id:
            api("POST", args.iris_url, api_key, f"case/notes/add?cid={case_id}",
                {
                    "note_title": spec["note_title"],
                    "note_content": spec["note"],
                    "directory_id": int(directory_id),
                })
            print(f"  Note: {spec['note_title']!r} in {spec['note_dir']!r}")
        else:
            print(f"  WARNING: could not create note directory: {dir_body}")

        for task in spec["tasks"]:
            api("POST", args.iris_url, api_key, f"case/tasks/add?cid={case_id}",
                {
                    "task_title": task["title"],
                    "task_description": task["description"],
                    "task_status_id": task_status_id(task["status"]),
                    "task_assignees_id": [assignee_id],
                    "task_tags": task["tags"],
                })
        print(f"  Tasks: {len(spec['tasks'])}")

    if args.dry_run:
        print("\n[DRY-RUN] No changes were made.")
        return

    print("\n" + "=" * 68)
    print(f"Seeded customer {CUSTOMER_NAME!r} (#{customer_id}) with {len(created_cases)} cases:")
    for cid, name in created_cases:
        print(f"  #{cid:<4} {name}")
    print(f"""
Shared indicators (should form ONE four-case correlation cluster):
  {SHARED_STAGING_IP:<26} all four cases
  {SHARED_C2_IP:<26} cases 1, 2, 4
  {SHARED_PHISH_DOMAIN:<26} cases 1, 4
  {SHARED_BEACON_SHA256[:16]}...      cases 2, 3

Check it: {args.iris_url.rstrip('/')}/dashboard  ->  Correlation tab
          {args.iris_url.rstrip('/')}/dashboard  ->  Metrics tab (Mar-Jun 2026)
""")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--iris-url", default=DEFAULT_IRIS_URL)
    parser.add_argument("--app-container", default=DEFAULT_APP_CONTAINER)
    parser.add_argument("--db-container", default=DEFAULT_DB_CONTAINER)
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME)
    parser.add_argument("--db-user", default=DEFAULT_DB_USER)
    parser.add_argument("--dry-run", action="store_true", help="Print API calls without executing them")
    args = parser.parse_args()

    try:
        run(args)
    except SeedError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

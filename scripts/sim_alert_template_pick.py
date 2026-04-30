"""Regression / playground harness for the case-template suggester.

Inserts a synthetic Alert from a named scenario, runs the suggester
against the live CaseTemplate catalog, prints the top pick + reason,
then deletes the Alert. The CaseTemplate catalog is left untouched, so
this is safe to run against the dev DB at any time.

Use it to:
  - Smoke a new prompt revision: run all scenarios with `--all` and
    eyeball the picks before shipping the prompt edit.
  - Spot-check a single scenario: `--scenario malware`.
  - Add a new scenario by appending to SCENARIOS — that's the closest
    thing to a regression suite for this orchestrator.

Run inside iriswebapp_app:

    PYTHONPATH=/iriswebapp python /iriswebapp/scripts/sim_alert_template_pick.py [--scenario NAME]
    PYTHONPATH=/iriswebapp python /iriswebapp/scripts/sim_alert_template_pick.py --list
    PYTHONPATH=/iriswebapp python /iriswebapp/scripts/sim_alert_template_pick.py --all
"""
import argparse
import sys

from app import app, db
from app.iris_engine.ai.case_template_suggester import (
    CaseTemplateSuggesterError,
    suggest_case_template,
)
from app.models.alerts import Alert, AlertStatus, Severity
from app.models.authorization import User
from app.models.cases import Client
from app.models.models import CaseTemplate


SCENARIOS = {
    "ransomware": {
        "title": "LockBit ransom note dropped on FS-CORP-01",
        "description": (
            "EDR flagged creation of `Restore-My-Files.txt` in 47 directories on FS-CORP-01 within 90 "
            "seconds. AES-encrypted siblings observed for .docx/.xlsx/.pdf files. Outbound connection "
            "to a known LockBit C2 (185.x.x.x) preceded the encryption burst by 4 minutes; analyst "
            "suspects exfil via rclone before encryption."
        ),
        "source": "CrowdStrike Falcon",
        "tags": "ransomware, lockbit, fs-corp-01",
        "severity": "Critical",
        "expected_substrings": ["ransom"],
    },
    "bec": {
        "title": "Suspicious mailbox forwarding rule on cfo@acme.com",
        "description": (
            "M365 Audit detected a new inbox rule forwarding all mail matching `wire|invoice|payment` "
            "to an external mailbox `acme-archive@protonmail.com`. Rule was created 03:14 UTC from a "
            "Tor exit node IP. The CFO's account had a successful sign-in 38 minutes earlier from the "
            "same IP, no MFA challenge (legacy auth used)."
        ),
        "source": "Microsoft Defender for Office 365",
        "tags": "bec, mailbox-rule, cfo, m365",
        "severity": "High",
        "expected_substrings": ["bec", "business email"],
    },
    "phishing": {
        "title": "User reported phishing — Microsoft 365 fake login",
        "description": (
            "Three employees forwarded a phishing email to abuse@. The mail impersonates IT, links to "
            "`microsoft365-secure-login[.]com/auth?redirect=acme.com`, and prompts for username + "
            "password. Two of the three confirmed they entered credentials. Sign-in logs show one of "
            "those accounts had a foreign-country sign-in 12 minutes after the click."
        ),
        "source": "User report (abuse@)",
        "tags": "phishing, credential-harvest, microsoft365",
        "severity": "High",
        "expected_substrings": ["phish"],
    },
    "intrusion": {
        "title": "Hands-on-keyboard activity on DC-CORP-01",
        "description": (
            "EDR observed `mimikatz.exe` execution under svc-backup, followed by `wmic /node:WS-FIN-07 "
            "process call create` and `psexec \\\\WS-FIN-07`. Analyst correlated this to a successful "
            "RDP from a compromised jumpbox 8 minutes earlier. No encryption activity yet — looks like "
            "an active intruder still in pre-impact stage."
        ),
        "source": "SentinelOne",
        "tags": "intrusion, lateral-movement, mimikatz, psexec",
        "severity": "Critical",
        "expected_substrings": ["intrusion", "unauthorized"],
    },
    "exfil": {
        "title": "Large rclone upload to Mega.nz from FS-DESIGN-02",
        "description": (
            "Network sensor flagged 47 GB outbound to `mega.nz` over the past 90 minutes from "
            "FS-DESIGN-02. Process tree shows `rclone.exe` running under user `j.smith` (departing "
            "employee, last day Friday). Files staged at `C:\\Users\\j.smith\\AppData\\Local\\Temp\\zipped\\` "
            "include the `Designs\\2026\\` share."
        ),
        "source": "Zeek",
        "tags": "data-exfil, rclone, mega, departing-employee",
        "severity": "High",
        "expected_substrings": ["data breach", "insider", "exfil"],
    },
    "ddos": {
        "title": "Sustained 480 Gbps UDP flood targeting api.acme.com",
        "description": (
            "CloudFlare DDoS dashboard reports a 480 Gbps UDP reflection flood (NTP / memcached) "
            "targeting `api.acme.com` since 14:02 UTC. Origin pool unreachable; CloudFlare absorbed "
            "but legitimate traffic latency p99 spiked to 8 seconds. No exploitation observed — pure "
            "availability attack."
        ),
        "source": "CloudFlare",
        "tags": "ddos, availability, udp-reflection",
        "severity": "Critical",
        "expected_substrings": ["ddos"],
    },
    "supply-chain": {
        "title": "3CX desktop app calling unknown C2 — confirmed supply chain",
        "description": (
            "EDR flagged `3CXDesktopApp.exe` (signed by 3CX) beaconing to `azureonlinestorage[.]com`. "
            "Hash matches the trojanized installer described in the 3CX advisory. Affects 218 hosts "
            "across 4 sites; all have the affected version installed via the standard MSI rolled out "
            "two weeks ago."
        ),
        "source": "Microsoft Defender for Endpoint",
        "tags": "supply-chain, 3cx, c2-beacon",
        "severity": "Critical",
        "expected_substrings": ["supply chain"],
    },
    "stolen-laptop": {
        "title": "Lost device report — MBP-EXEC-04 left in airport taxi",
        "description": (
            "Executive J. Doe reported leaving a corporate MacBook Pro (MBP-EXEC-04, asset tag #4129) "
            "in a taxi at LAX. Device contains email, SSO refresh tokens, and likely one cached "
            "BitLocker recovery key. No remote-wipe yet; FileVault is enabled. Need to scope what the "
            "device had access to and revoke."
        ),
        "source": "User report",
        "tags": "lost-device, macbook, executive",
        "severity": "Medium",
        "expected_substrings": ["lost", "stolen", "device"],
    },
    "webapp": {
        "title": "SQL injection POSTs against /api/orders — auth bypassed",
        "description": (
            "WAF logged 1,800 `' OR 1=1 --` style payloads targeting `POST /api/orders/search` from "
            "a single IP over 30 minutes. 14 of those requests returned 200 with a response size "
            "consistent with the full orders table. App logs show the auth filter was skipped because "
            "the endpoint lacked `@RequireAuth` — likely OWASP A01."
        ),
        "source": "Cloudflare WAF",
        "tags": "webapp, sqli, owasp-a01, api",
        "severity": "High",
        "expected_substrings": ["web application", "webapp"],
    },
    "cloud-breach": {
        "title": "S3 bucket acme-customer-pii made world-readable",
        "description": (
            "AWS Config detected `acme-customer-pii` switched to public-read at 22:14 UTC by an IAM "
            "user that had its access key leaked on a public GitHub gist 6 hours earlier. Bucket "
            "contains ~2.4M customer records (name + email + last4 + DOB). CloudTrail shows GetObject "
            "calls from 11 distinct IPs in the past hour."
        ),
        "source": "AWS Config",
        "tags": "cloud, aws-s3, data-breach, leaked-iam-key",
        "severity": "Critical",
        "expected_substrings": ["cloud", "data breach"],
    },
    "idp-compromise": {
        "title": "Okta admin account modified all MFA factors at 03:11 UTC",
        "description": (
            "Okta admin user `breakglass-2` removed all MFA factors and added a new TOTP for a privileged "
            "service account at 03:11 UTC. Sign-in came from a new device + new ASN. Analyst is treating "
            "this as a compromised IdP admin — the breakglass-2 password was last rotated 14 months ago "
            "and is shared on an internal wiki page."
        ),
        "source": "Okta System Log",
        "tags": "idp, okta, mfa-removal, privileged-access",
        "severity": "Critical",
        "expected_substrings": ["identity", "idp"],
    },
    "insider": {
        "title": "Departing engineer cloned 200 internal repos to personal device",
        "description": (
            "GitHub audit log: user `eve.green` cloned 200 private repositories over 3 hours, all on "
            "the day after submitting her resignation. Cloning IP matches her home VPN; user-agent is "
            "`git/2.43 macOS personal MacBook` (not the corp managed device). HR confirmed she gave "
            "two weeks' notice yesterday."
        ),
        "source": "GitHub audit log",
        "tags": "insider, departing-employee, ip-theft",
        "severity": "High",
        "expected_substrings": ["insider"],
    },
    "malware": {
        "title": "Emotet macro execution from finance@ inbox attachment",
        "description": (
            "AV detonated `Invoice-March.docm` from finance@'s mailbox; macro spawns `powershell.exe -enc <b64>` "
            "which downloads from `bizinvoice[.]top`. Hash matches Emotet TR campaign from yesterday's CTI feed. "
            "Endpoint quarantined the dropper before execution but the email was forwarded to 4 other users."
        ),
        "source": "Trend Micro",
        "tags": "malware, emotet, macro, finance",
        "severity": "High",
        "expected_substrings": ["malware"],
    },
}


def _run_scenario(name: str, sc: dict, *, admin, customer, verbose: bool = True) -> tuple[str, dict | None]:
    """Insert a synthetic Alert, run the suggester, delete the Alert, return
    (verdict, suggestion). Verdict is one of MATCH / WARN / FAIL / NULL."""
    severity = (
        db.session.query(Severity).filter(Severity.severity_name == sc["severity"]).first()
        or db.session.query(Severity).first()
    )
    status = (
        db.session.query(AlertStatus).filter(AlertStatus.status_name == "New").first()
        or db.session.query(AlertStatus).first()
    )
    alert = Alert(
        alert_title=sc["title"],
        alert_description=sc["description"],
        alert_source=sc["source"],
        alert_tags=sc["tags"],
        alert_severity_id=severity.severity_id,
        alert_status_id=status.status_id,
        alert_customer_id=customer.client_id,
        alert_owner_id=admin.id,
    )
    db.session.add(alert)
    db.session.commit()
    cleanup_alert_id = alert.alert_id

    if verbose:
        print()
        print(f"=== Simulated alert ({name}) ===")
        print(f"  id:       {alert.alert_id}")
        print(f"  title:    {alert.alert_title}")
        print(f"  source:   {alert.alert_source} (severity={sc['severity']})")
        print(f"  tags:     {alert.alert_tags}")

    try:
        result = suggest_case_template(alert=alert)
    except CaseTemplateSuggesterError as e:
        print(f"FAIL ({name}): {e}")
        return ("FAIL", None)
    finally:
        db.session.query(Alert).filter(Alert.alert_id == cleanup_alert_id).delete()
        db.session.commit()

    s = result["suggestion"]
    if verbose:
        print(f"=== Suggestion ({name}) ===")
        print(f"  model:        {result['model']}")
        print(f"  catalog_size: {result['catalog_size']}")
    if s is None:
        if verbose:
            print("  suggestion:   None")
        return ("NULL", None)
    if verbose:
        print(f"  template_id:    {s['template_id']}")
        print(f"  template_name:  {s['template_name']}")
        print(f"  confidence:     {s['confidence']:.2f}")
        print(f"  reason:         {s['reason']}")

    expected = sc.get("expected_substrings") or []
    template_name = (s.get("template_name") or "").lower()
    if expected and not any(e in template_name for e in expected):
        if verbose:
            print(f"WARN ({name}): picked {s['template_name']!r}, expected one of {expected}")
        return ("WARN", s)
    if verbose:
        print(f"MATCH ({name})")
    return ("MATCH", s)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS.keys()),
        default="ransomware",
        help="Which preset alert to feed the suggester (default: ransomware).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List the available scenarios and exit.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run every scenario in turn and print a summary table.",
    )
    args = parser.parse_args()

    if args.list:
        for name, sc in SCENARIOS.items():
            print(f"  {name:14s}  {sc['title']}")
        return

    with app.app_context():
        templates = (
            db.session.query(CaseTemplate)
            .order_by(CaseTemplate.id)
            .all()
        )
        if not args.all:
            print(f"=== Catalog ({len(templates)} templates) ===")
            for t in templates:
                print(f"  #{t.id:>3}  {t.display_name or t.name}")
        if not templates:
            print("FAIL: no templates — import them under /manage/case-templates first")
            sys.exit(1)

        admin = db.session.query(User).order_by(User.id.asc()).first()
        customer = db.session.query(Client).order_by(Client.client_id.asc()).first()
        if not admin or not customer:
            print("FAIL: missing baseline rows (admin/customer)")
            sys.exit(1)

        if args.all:
            print(f"=== Sweeping {len(SCENARIOS)} scenarios against {len(templates)} templates ===")
            results: list[tuple[str, str, dict | None]] = []
            for name, sc in SCENARIOS.items():
                verdict, suggestion = _run_scenario(name, sc, admin=admin, customer=customer, verbose=False)
                results.append((name, verdict, suggestion))
                # Compact one-line output per scenario
                if suggestion is None:
                    print(f"  {verdict:5s}  {name:14s}  (no suggestion)")
                else:
                    print(
                        f"  {verdict:5s}  {name:14s}  "
                        f"→ {suggestion['template_name']!r:50s}  "
                        f"conf={suggestion['confidence']:.2f}"
                    )
            print()
            counts: dict[str, int] = {}
            for _, v, _ in results:
                counts[v] = counts.get(v, 0) + 1
            print("Summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
            # Exit non-zero if any scenario didn't match — useful in CI / pre-commit.
            if any(v != "MATCH" for _, v, _ in results):
                sys.exit(2)
            return

        sc = SCENARIOS[args.scenario]
        verdict, _ = _run_scenario(args.scenario, sc, admin=admin, customer=customer, verbose=True)
        if verdict == "FAIL":
            sys.exit(1)
        if verdict == "NULL":
            sys.exit(2)


if __name__ == "__main__":
    main()

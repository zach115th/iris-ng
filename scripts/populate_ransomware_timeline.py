#!/usr/bin/env python3
"""
Populate a ransomware incident timeline for case testing.
Usage: python populate_ransomware_timeline.py --case-id 40 [--host https://localhost]
"""

import argparse
import json
import requests
from urllib3.exceptions import InsecureRequestWarning

# Suppress SSL warnings for local dev
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Category ID mapping (from database query)
CATEGORIES = {
    "Delivery": 18,
    "Exploitation": 20,
    "Command and Control": 13,
    "Pivoting": 21,
    "Objectives": 22,
    "Reconnaissance": 16,
}

# Timeline events for a realistic ransomware incident
RANSOMWARE_TIMELINE = [
    ("2026-07-10T02:15:00.000000", "Initial Access - Phishing Email Delivery", "Delivery",
     "Phishing email with malicious Excel attachment (Invoice_2026.xlsx) delivered to finance@company.com via public email gateway.",
     {"source": "Email Gateway Logs", "sender": "billing-update@fakecompany.net", "recipients": ["finance@company.com"], "attachment": "Invoice_2026.xlsx"},
     "Email Gateway"),

    ("2026-07-10T09:30:00.000000", "Macro Execution on Finance Workstation", "Exploitation",
     "User opened malicious Excel file. VBA macro executed, downloading Emotet dropper payload from attacker C2.",
     {"source": "Sysmon Process Creation", "process": "EXCEL.EXE", "parent": "explorer.exe", "child_process": "powershell.exe"},
     "Sysmon"),

    ("2026-07-10T10:15:00.000000", "Emotet C2 Callback", "Command and Control",
     "Emotet malware established callback to C2 server 185.214.119.22:443 (confirmed by DNS query and SSL certificate analysis).",
     {"source": "Network Traffic Analysis", "protocol": "HTTPS", "src_ip": "10.0.50.15", "dst_ip": "185.214.119.22", "dst_port": 443},
     "Network IDS"),

    ("2026-07-10T10:45:00.000000", "Lateral Movement - Credential Harvesting", "Exploitation",
     "Emotet downloaded Mimikatz variant to harvest credentials from LSASS memory. Credentials dumped for domain account CORP\\admin_bkup (gp-server admin).",
     {"source": "Sysmon Process Access", "target_process": "lsass.exe", "requesting_process": "mimikatz.exe", "access_type": "PROCESS_VM_READ"},
     "Sysmon"),

    ("2026-07-10T11:30:00.000000", "Lateral Movement - RDP to DC", "Pivoting",
     "Attacker used harvested admin credentials to RDP into domain controller DC-01 from WS-FIN-01 (RDP session ID 2).",
     {"source": "Windows Security Event 4648", "source_account": "CORP\\admin_bkup", "target_server": "DC-01", "logon_type": 10, "source_ip": "10.0.50.15"},
     "Windows Security"),

    ("2026-07-10T12:00:00.000000", "Ransomware Payload Download", "Delivery",
     "Emotet downloaded LockBit ransomware sample (lockbit_v3_payload.exe) to DC-01 admin temp folder.",
     {"source": "File Monitoring / EDR", "filename": "lockbit_v3_payload.exe", "path": "C:\\Windows\\Temp\\", "md5": "d41d8cd98f00b204e9800998ecf8427e", "size_bytes": 2851840},
     "EDR"),

    ("2026-07-10T12:15:00.000000", "Ransomware Execution on Domain Controller", "Exploitation",
     "LockBit ransomware executed on DC-01 with SYSTEM privileges via RunAs using harvested admin credentials.",
     {"source": "Sysmon Process Creation", "process": "lockbit_v3_payload.exe", "parent": "powershell.exe", "command_line": "lockbit_v3_payload.exe /full", "user": "NT AUTHORITY\\SYSTEM"},
     "Sysmon"),

    ("2026-07-10T12:20:00.000000", "Domain-Wide Encryption Campaign Begins", "Objectives",
     "LockBit enumerated all domain-joined systems via LDAP and initiated encryption across 127 systems including file servers FS-01, FS-02, and backup servers.",
     {"source": "Network Traffic Analysis", "traffic_pattern": "SMB broadcast enumeration", "targets_encrypted": 127, "encryption_algorithm": "ChaCha20"},
     "Network Analysis"),

    ("2026-07-10T13:00:00.000000", "Ransom Note Discovered", "Objectives",
     "LockBit ransom note (README.txt) created on all encrypted systems. Demands $2.5M in Bitcoin. 72-hour deadline before data sale.",
     {"source": "File System Analysis", "ransom_amount_usd": 2500000, "deadline_hours": 72, "leak_site": "http://lockbitonion.onion/corporate/company-xyz"},
     "File Analysis"),

    ("2026-07-10T14:30:00.000000", "Data Exfiltration Detected", "Objectives",
     "Analysis of network traffic shows ~450 GB of data transferred from FS-01/FS-02 to attacker IP 103.145.23.88:443 (SFTP over TLS tunnel)",
     {"source": "Network DLP / SIEM", "exfiltration_volume_gb": 450, "duration_minutes": 85, "destination_ip": "103.145.23.88", "destination_port": 443},
     "Network DLP"),

    ("2026-07-10T15:45:00.000000", "Incident Response Initiated", "Reconnaissance",
     "IT discovered encryption on non-critical file servers. Incident response team activated. All domain controllers isolated from production network. Backup systems verified offline (last sync 2026-07-08).",
     {"source": "IR Incident Ticket", "ticket_id": "INC-2026-0847", "severity": "P1-Critical", "backup_status": "Last sync 2026-07-08 (2 days old)"},
     "IR Log"),
]


def add_timeline_event(session, case_id, event_date, title, category, content, raw_data, source, base_url):
    """Add a single timeline event to the case."""
    endpoint = f"{base_url}/case/timeline/events/add"

    payload = {
        "cid": case_id,
        "event_date": event_date,
        "event_tz": "Z",
        "event_title": title,
        "event_category_id": CATEGORIES.get(category, 1),
        "event_content": content,
        "event_raw": json.dumps(raw_data),
        "event_source": source,
        "event_assets": [],
        "event_iocs": [],
    }

    response = session.post(endpoint, json=payload, verify=False)

    if response.status_code in [200, 201, 202]:
        print(f"✓ Added: {title}")
        return True
    else:
        print(f"✗ Failed ({response.status_code}): {title}")
        if response.text:
            try:
                error_data = response.json()
                print(f"  Error: {error_data}")
            except:
                print(f"  Response: {response.text[:200]}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Populate ransomware incident timeline for IRIS-NG case"
    )
    parser.add_argument("--case-id", type=int, default=40, help="Case ID to populate")
    parser.add_argument("--host", default="https://localhost", help="IRIS-NG base URL")
    parser.add_argument("--api-key", help="API key for authentication (optional)")

    args = parser.parse_args()

    session = requests.Session()
    session.verify = False

    if args.api_key:
        session.headers.update({"Authorization": f"Bearer {args.api_key}"})

    print(f"\n{'='*70}")
    print(f"Populating Ransomware Timeline for Case #{args.case_id}")
    print(f"{'='*70}\n")

    added = 0
    failed = 0

    for event_date, title, category, content, raw_data, source in RANSOMWARE_TIMELINE:
        if add_timeline_event(session, args.case_id, event_date, title, category, content, raw_data, source, args.host):
            added += 1
        else:
            failed += 1

    print(f"\n{'='*70}")
    print(f"Complete: {added} events added, {failed} failed")
    print(f"{'='*70}\n")

    print(f"View timeline: {args.host}/case/timeline?cid={args.case_id}")
    print()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Replicate phishing case 31 to cases 32-35 via API.
- Keep IOCs identical
- Create new assets per case (per customer)
- Adapt notes to customer context
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

# Configuration
ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
DEFAULT_IRIS_URL = "http://localhost:18000"  # Docker port mapping: 127.0.0.1:18000->8000

# Asset patterns per case
ASSET_PATTERNS = {
    32: {
        "computers": ["WKS-001", "WKS-002", "WKS-003", "WKS-004", "WKS-005"],
        "users": ["jsmith", "bwilson", "clee", "djones"]
    },
    33: {
        "computers": ["DEV-100", "DEV-101", "DEV-102", "DEV-103", "DEV-104"],
        "users": ["analyst_1", "analyst_2", "analyst_3", "analyst_4"]
    },
    34: {
        "computers": ["LAB-201", "LAB-202", "LAB-203", "LAB-204", "LAB-205"],
        "users": ["tech_alpha", "tech_beta", "tech_gamma", "tech_delta"]
    },
    35: {
        "computers": ["SYS-401", "SYS-402", "SYS-403", "SYS-404", "SYS-405"],
        "users": ["admin_a", "admin_b", "admin_c", "admin_d"]
    }
}

class IrisClient:
    def __init__(self, base_url, api_key):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        })

    def get(self, path, **kwargs):
        """GET request."""
        url = f"{self.base_url}{path}"
        resp = self.session.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def post(self, path, data=None, **kwargs):
        """POST request."""
        url = f"{self.base_url}{path}"
        resp = self.session.post(url, json=data, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def put(self, path, data=None, **kwargs):
        """PUT request."""
        url = f"{self.base_url}{path}"
        resp = self.session.put(url, json=data, **kwargs)
        resp.raise_for_status()
        return resp.json()

def get_api_key():
    """Get API key for the bootstrap administrator."""
    # Read from .env if available
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                if line.startswith("IRIS_ADMIN_API_KEY="):
                    return line.split('=', 1)[1].strip().strip('"\'')

    # Fallback: ask user
    key = input("Enter IRIS API key for administrator: ").strip()
    if not key:
        print("ERROR: API key required")
        sys.exit(1)
    return key

def replicate_case(client, case_id, source_case_id=31):
    """Replicate case 31's IOCs, notes, and assets to another case."""

    print(f"\n{'='*60}")
    print(f"Replicating case {source_case_id} → case {case_id}")
    print(f"{'='*60}")

    # Get source case details
    try:
        source_case = client.get(f"/api/v2/cases/{source_case_id}")
    except Exception as e:
        print(f"ERROR: Cannot fetch case {source_case_id}: {e}")
        return False

    try:
        target_case = client.get(f"/api/v2/cases/{case_id}")
    except Exception as e:
        print(f"ERROR: Cannot fetch case {case_id}: {e}")
        return False

    print(f"Source: {source_case.get('case_name', 'N/A')}")
    print(f"Target: {target_case.get('case_name', 'N/A')}")

    # Build asset mapping for target case
    print(f"\n[1] Building asset mapping for case {case_id}...")
    asset_map = {}
    patterns = ASSET_PATTERNS.get(case_id, ASSET_PATTERNS[32])
    computers = patterns["computers"].copy()
    users = patterns["users"].copy()

    idx_computer = 0
    idx_user = 0

    try:
        target_assets = client.get(f"/api/v2/cases/{case_id}/assets")
        if isinstance(target_assets, dict) and 'data' in target_assets:
            target_assets = target_assets['data']
    except Exception:
        target_assets = []

    for asset in target_assets:
        asset_type_name = asset.get('asset_type', {}).get('asset_type_name', 'Computer') if isinstance(asset.get('asset_type'), dict) else 'Computer'

        if "User" in asset_type_name or "Account" in asset_type_name:
            new_name = users[idx_user % len(users)]
            idx_user += 1
        else:
            new_name = computers[idx_computer % len(computers)]
            idx_computer += 1

        asset_map[asset.get('asset_name', '')] = new_name

    print(f"  Asset map: {len(asset_map)} mappings")
    for old, new in list(asset_map.items())[:3]:
        print(f"    {old:20} → {new}")

    # 1. COPY IOCs
    print(f"\n[2] Adding IOCs to case {case_id}...")
    ioc_count = 0

    try:
        source_iocs = client.get(f"/api/v2/cases/{source_case_id}/iocs")
        if isinstance(source_iocs, dict) and 'data' in source_iocs:
            source_iocs = source_iocs['data']
    except Exception:
        print("  ERROR: Cannot fetch source IOCs")
        source_iocs = []

    for source_ioc in source_iocs:
        # Check if IOC already exists
        try:
            client.get(f"/api/v2/cases/{case_id}/iocs/{source_ioc.get('ioc_id')}")
            print(f"  IOC already exists: {source_ioc.get('ioc_value', 'N/A')}")
        except:
            # Create new IOC
            try:
                new_ioc = {
                    "ioc_type_id": source_ioc.get('ioc_type_id'),
                    "ioc_value": source_ioc.get('ioc_value'),
                    "ioc_description": source_ioc.get('ioc_description', ''),
                    "ioc_tlp_id": source_ioc.get('ioc_tlp_id', 2),
                    "ioc_tags": source_ioc.get('ioc_tags', '')
                }
                client.post(f"/api/v2/cases/{case_id}/iocs", new_ioc)
                print(f"  + Added: {source_ioc.get('ioc_value')}")
                ioc_count += 1
            except Exception as e:
                print(f"  ERROR adding IOC: {e}")

    print(f"  Total IOCs added: {ioc_count}")

    # 2. COPY NOTES (with adaptation)
    print(f"\n[3] Copying and adapting notes...")

    try:
        source_notes = client.get(f"/api/v2/cases/{source_case_id}/notes")
        if isinstance(source_notes, dict) and 'data' in source_notes:
            source_notes = source_notes['data']
    except Exception:
        print("  ERROR: Cannot fetch source notes")
        source_notes = []

    note_count = 0
    for source_note in source_notes:
        note_title = source_note.get('note_title', '')
        note_content = source_note.get('note_content', '')

        # Adapt note content
        for old_name, new_name in asset_map.items():
            note_content = note_content.replace(old_name, new_name)

        # Adapt customer names
        source_customer = source_case.get('client', {}).get('client_name', 'RAND')
        target_customer = target_case.get('client', {}).get('client_name', 'TARG')
        note_content = note_content.replace(source_customer, target_customer)
        note_content = note_content.replace("RAND", target_customer[:4].upper())

        try:
            client.post(f"/api/v2/cases/{case_id}/notes", {
                "note_title": note_title,
                "note_content": note_content
            })
            print(f"  + Copied: {note_title}")
            note_count += 1
        except Exception as e:
            print(f"  Note already exists or error: {note_title}")

    print(f"\n✓ Case {case_id} replication complete")
    print(f"  - IOCs: {ioc_count} added")
    print(f"  - Notes: {note_count} copied")
    print(f"  - Assets: {len(asset_map)} mapped")

    return True

if __name__ == "__main__":
    import sys
    iris_url = DEFAULT_IRIS_URL

    # Allow API key to be passed as first argument
    if len(sys.argv) > 1:
        api_key = sys.argv[1]
    else:
        api_key = get_api_key()

    print("\n" + "="*60)
    print("PHISHING CASE REPLICATION VIA API")
    print("="*60)

    client = IrisClient(iris_url, api_key)

    for case_id in [32, 33, 34, 35]:
        try:
            replicate_case(client, case_id)
        except Exception as e:
            print(f"\nERROR in case {case_id}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "="*60)
    print("NEXT STEPS:")
    print("="*60)
    print("1. Generate adapted timelines:")
    print("   python scripts/generate_phishing_timelines.py")
    print("2. Import timelines via UI or API")

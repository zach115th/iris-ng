#!/usr/bin/env python3
"""Import adapted timeline CSVs for cases 32-35 via API."""

import sys
import json
from pathlib import Path
from datetime import datetime

import requests

# Configuration
ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
DEFAULT_IRIS_URL = "http://localhost:18000"

class IrisClient:
    def __init__(self, base_url, api_key):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_key}',
        })

    def get(self, path, **kwargs):
        """GET request."""
        url = f"{self.base_url}{path}"
        resp = self.session.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def post_multipart(self, path, files=None, data=None, **kwargs):
        """POST multipart request (for file uploads)."""
        url = f"{self.base_url}{path}"
        # Remove Content-Type header for multipart (requests will set it with boundary)
        headers = dict(self.session.headers)
        if 'Content-Type' in headers:
            del headers['Content-Type']

        resp = self.session.post(url, files=files, data=data, headers=headers, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.text else {}

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

def import_timeline(client, case_id, csv_file):
    """Import a timeline CSV to a case's working timeline."""

    if not csv_file.exists():
        print(f"  ERROR: File not found: {csv_file}")
        return False

    print(f"\n[{case_id}] Importing timeline from {csv_file.name}...")

    try:
        # Read CSV file
        with open(csv_file, 'rb') as f:
            files = {'file': (csv_file.name, f, 'text/csv')}
            data = {'begin_date': '', 'end_date': ''}  # No date filtering

            resp = client.post_multipart(
                f"/api/v2/cases/{case_id}/working-timeline/import/master-csv",
                files=files,
                data=data
            )

        # Check response
        if isinstance(resp, dict):
            # Check for imported count (successful response includes 'imported' key)
            if 'imported' in resp:
                events = resp.get('imported', '?')
                print(f"  [OK] Imported {events} events to case {case_id}")
                return True
            else:
                status = resp.get('status', 'unknown')
                if status == 'success' or 'success' in str(resp).lower():
                    events = resp.get('events_imported', resp.get('count', '?'))
                    print(f"  [OK] Imported {events} events to case {case_id}")
                    return True
                else:
                    print(f"  ERROR: {resp.get('message', str(resp))}")
                    return False
        else:
            print(f"  [OK] Timeline imported (response: {resp})")
            return True

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Allow API key to be passed as first argument
    if len(sys.argv) > 1:
        api_key = sys.argv[1]
    else:
        api_key = get_api_key()

    print("\n" + "="*60)
    print("IMPORTING TIMELINE CSVs FOR CASES 32-35")
    print("="*60)

    iris_url = DEFAULT_IRIS_URL
    client = IrisClient(iris_url, api_key)

    results = {}
    for case_id in [32, 33, 34, 35]:
        csv_file = ROOT / f"case-{case_id}-timeline.csv"
        success = import_timeline(client, case_id, csv_file)
        results[case_id] = success

    print("\n" + "="*60)
    print("IMPORT SUMMARY")
    print("="*60)

    for case_id in [32, 33, 34, 35]:
        status = "[OK] SUCCESS" if results[case_id] else "[FAIL]"
        print(f"Case {case_id}: {status}")

    print("\n" + "="*60)
    print("NEXT STEPS:")
    print("="*60)
    print("1. Review imported events in the working-timeline panels")
    print("2. Promote 7 key milestone events to master timeline:")
    print("   - Phishing email received")
    print("   - User opens malicious attachment")
    print("   - Macro execution detected")
    print("   - C2 callback established")
    print("   - Lateral movement to secondary system")
    print("   - Additional compromised accounts identified")
    print("   - Incident response initiated")
    print("\n3. Optionally copy notes from case 31:")
    print("   python scripts/copy_notes_to_phishing_cases.py")

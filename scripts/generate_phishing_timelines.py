#!/usr/bin/env python3
"""
Generate adapted timeline CSVs for phishing cases 32-35.
Reads case 31's timeline and swaps asset names per case.
"""

import csv
import os
from pathlib import Path

# Asset patterns (same as replicate script)
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

# Case 31 assets that will be mapped to each new case
CASE_31_ASSETS = {
    "RAND-LT-0355": 0,  # primary workstation
    "RAND-LT-0231": 1,  # secondary workstation
    "RAND-LT-0198": 2,  # tertiary workstation
    "RAND-DT-0410": 3,  # desktop
    "rbeaumont": 0,     # primary user
    "dpatel": 1,        # secondary user
    "mschwartz": 2,     # tertiary user
    "tokafor": 3        # admin user
}

def build_asset_map(case_id):
    """Build asset name mapping for a specific case."""
    patterns = ASSET_PATTERNS.get(case_id, ASSET_PATTERNS[32])
    computers = patterns["computers"]
    users = patterns["users"]

    asset_map = {}

    # Map case 31 assets to new case assets
    for case31_asset, idx in CASE_31_ASSETS.items():
        if case31_asset.startswith("RAND"):
            # Computer asset
            new_name = computers[idx % len(computers)]
        else:
            # User asset
            new_name = users[idx % len(users)]

        asset_map[case31_asset] = new_name

    return asset_map

def adapt_timeline_for_case(source_csv, case_id, target_csv):
    """Adapt case 31's timeline CSV for a target case."""

    # Build asset mapping
    asset_map = build_asset_map(case_id)

    print(f"\nGenerating timeline for case {case_id}...")
    print(f"  Asset map ({len(asset_map)} mappings):")
    for old, new in sorted(asset_map.items())[:5]:
        print(f"    {old:20} → {new}")
    if len(asset_map) > 5:
        print(f"    ... and {len(asset_map) - 5} more")

    # Read source CSV and write adapted version
    with open(source_csv, 'r', encoding='utf-8') as infile, \
         open(target_csv, 'w', encoding='utf-8', newline='') as outfile:

        reader = csv.DictReader(infile)
        writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)
        writer.writeheader()

        for row in reader:
            # Adapt event_assets (semicolon-separated)
            if row.get('event_assets'):
                assets = [a.strip() for a in row['event_assets'].split(';')]
                adapted_assets = [asset_map.get(a, a) for a in assets]
                row['event_assets'] = ';'.join(adapted_assets)

            # Adapt event_content and event_raw (swap all asset names)
            for old_name, new_name in asset_map.items():
                row['event_content'] = row['event_content'].replace(old_name, new_name)
                row['event_raw'] = row['event_raw'].replace(old_name, new_name)

            writer.writerow(row)

    print(f"  ✓ Saved to {target_csv}")

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    source_csv = root / "case-31-timeline.csv"

    if not source_csv.exists():
        print(f"ERROR: Source timeline not found: {source_csv}")
        exit(1)

    print("\n" + "="*60)
    print("GENERATING ADAPTED TIMELINES FOR CASES 32-35")
    print("="*60)

    for case_id in [32, 33, 34, 35]:
        target_csv = root / f"case-{case_id}-timeline.csv"
        try:
            adapt_timeline_for_case(str(source_csv), case_id, str(target_csv))
        except Exception as e:
            print(f"ERROR generating case {case_id}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "="*60)
    print("TIMELINE FILES GENERATED")
    print("="*60)
    print("\nNext: import each CSV via the UI or API:")
    print("  POST /api/v2/cases/<cid>/working-timeline/import/master-csv")
    print("\nThen promote key milestone events to master timeline:")
    print("  1. Phishing email received")
    print("  2. User opens malicious attachment")
    print("  3. Macro execution detected")
    print("  4. C2 callback established")
    print("  5. Lateral movement to secondary system")
    print("  6. Additional compromised accounts identified")
    print("  7. Incident response initiated")

#!/usr/bin/env python3
"""Copy and adapt notes and evidence from case 31 to cases 32-35 via direct SQL."""

import subprocess
import sys
from pathlib import Path

# Asset patterns per case
ASSET_PATTERNS = {
    31: {
        "computers": ["RAND-LT-0355", "RAND-LT-0231", "RAND-LT-0198", "RAND-DT-0410"],
        "users": ["rbeaumont", "dpatel", "mschwartz", "tokafor"]
    },
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
    },
    36: {
        "computers": ["CORP-W01", "CORP-W02", "CORP-W03", "CORP-W04", "CORP-W05"],
        "users": ["user_01", "user_02", "user_03", "user_04"]
    },
    37: {
        "computers": ["NET-LT-001", "NET-LT-002", "NET-LT-003", "NET-LT-004", "NET-LT-005"],
        "users": ["netadmin_a", "netadmin_b", "netadmin_c", "netadmin_d"]
    },
    38: {
        "computers": ["SEC-WS-101", "SEC-WS-102", "SEC-WS-103", "SEC-WS-104", "SEC-WS-105"],
        "users": ["security_1", "security_2", "security_3", "security_4"]
    },
    39: {
        "computers": ["OPS-HT-01", "OPS-HT-02", "OPS-HT-03", "OPS-HT-04", "OPS-HT-05"],
        "users": ["ops_alpha", "ops_beta", "ops_gamma", "ops_delta"]
    }
}

# Customer mapping (case ID -> customer name)
CUSTOMER_NAMES = {
    31: "Rand Corporation",
    32: "TechCorp Solutions",
    33: "DevOps Inc",
    34: "LabTech Research",
    35: "SysAdmin Consulting",
    36: "CorporateNet Ltd",
    37: "Network Systems Group",
    38: "SecureOps Holdings",
    39: "Operations Tech Inc"
}

def run_psql(query):
    """Execute a psql query via docker exec."""
    cmd = [
        "docker", "exec", "iriswebapp_db", "psql", "-U", "raptor", "-d", "iris_db",
        "-c", query
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"ERROR: {e.stderr}")
        return None

def build_asset_map(from_case_id, to_case_id):
    """Build a mapping from source case assets to target case assets."""
    src_patterns = ASSET_PATTERNS.get(from_case_id, ASSET_PATTERNS[31])
    dst_patterns = ASSET_PATTERNS.get(to_case_id, ASSET_PATTERNS[32])

    asset_map = {}

    # Map computers (order-preserving)
    for i, src_comp in enumerate(src_patterns["computers"]):
        dst_comp = dst_patterns["computers"][i % len(dst_patterns["computers"])]
        asset_map[src_comp] = dst_comp

    # Map users (order-preserving)
    for i, src_user in enumerate(src_patterns["users"]):
        dst_user = dst_patterns["users"][i % len(dst_patterns["users"])]
        asset_map[src_user] = dst_user

    return asset_map

def adapt_content(content, asset_map, source_customer, target_customer):
    """Adapt note content by replacing assets and customer names."""
    adapted = content

    # Replace asset names
    for old_name, new_name in asset_map.items():
        adapted = adapted.replace(old_name, new_name)

    # Replace customer name
    adapted = adapted.replace(source_customer, target_customer)

    # Replace customer abbreviation
    src_abbr = source_customer.split()[0].upper()[:4]
    dst_abbr = target_customer.split()[0].upper()[:4]
    adapted = adapted.replace(src_abbr, dst_abbr)

    return adapted

def copy_notes(source_case_id, target_case_id):
    """Copy and adapt notes from source case to target case."""
    print(f"\n[NOTES] Copying from case {source_case_id} -> case {target_case_id}...")

    source_customer = CUSTOMER_NAMES[source_case_id]
    target_customer = CUSTOMER_NAMES[target_case_id]
    asset_map = build_asset_map(source_case_id, target_case_id)

    # Fetch source notes
    query = f"""
        SELECT note_id, note_title, note_content, note_creationdate
        FROM notes
        WHERE note_case_id = {source_case_id}
        ORDER BY note_id
    """
    result = run_psql(query)
    if not result:
        print(f"  ERROR: Could not fetch notes from case {source_case_id}")
        return 0

    # Parse the result (psql output is text-based)
    lines = result.split('\n')

    # Extract note data more carefully
    query = f"""
        SELECT note_id, note_title
        FROM notes
        WHERE note_case_id = {source_case_id}
        ORDER BY note_id
    """
    result = run_psql(query)
    if not result:
        print(f"  ERROR: Could not fetch note titles from case {source_case_id}")
        return 0

    note_ids = []
    for line in result.split('\n'):
        if '|' in line and not line.startswith('-'):
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 2 and parts[0].isdigit():
                note_ids.append(int(parts[0]))

    if not note_ids:
        print(f"  WARNING: No notes found in case {source_case_id}")
        return 0

    copied = 0
    for note_id in note_ids:
        # Fetch individual note
        query = f"""
            SELECT note_title, note_content
            FROM notes
            WHERE note_case_id = {source_case_id} AND note_id = {note_id}
        """

        # Use a simpler approach: fetch without pretty-printing
        cmd = [
            "docker", "exec", "iriswebapp_db", "psql", "-U", "raptor", "-d", "iris_db",
            "-t", "-A", "-F|",
            "-c", query
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            output = result.stdout.strip()
            if '|' in output:
                parts = output.split('|', 1)
                note_title = parts[0].strip()
                note_content = parts[1].strip() if len(parts) > 1 else ""

                # Adapt content
                adapted_content = adapt_content(note_content, asset_map, source_customer, target_customer)

                # Escape single quotes for SQL
                adapted_content = adapted_content.replace("'", "''")
                note_title = note_title.replace("'", "''")

                # Insert adapted note
                insert_query = f"""
                    INSERT INTO notes (note_case_id, note_title, note_content, note_creationdate, note_user_id)
                    SELECT {target_case_id}, '{note_title}', '{adapted_content}', NOW(), note_user_id
                    FROM notes
                    WHERE note_case_id = {source_case_id} AND note_id = {note_id}
                    LIMIT 1
                """

                run_psql(insert_query)
                print(f"  + Copied: {note_title}")
                copied += 1
        except subprocess.CalledProcessError as e:
            print(f"  ERROR fetching note {note_id}: {e.stderr}")

    return copied

def check_evidence(case_id):
    """Check if case has evidence."""
    query = f"""
        SELECT COUNT(*), string_agg(file_name, ', ')
        FROM case_received_file
        WHERE file_case_id = {case_id}
    """
    result = run_psql(query)
    if result:
        lines = result.strip().split('\n')
        for line in lines:
            if '|' in line:
                parts = [p.strip() for p in line.split('|')]
                if parts[0].isdigit():
                    count = int(parts[0])
                    files = parts[1] if len(parts) > 1 else ""
                    return count, files
    return 0, ""

if __name__ == "__main__":
    print("\n" + "="*60)
    print("ADAPTING CASE DETAILS FOR CASES 32-35")
    print("="*60)

    # Check source case
    print("\n[SOURCE] Checking case 31...")
    note_count, _ = check_evidence(31)
    print(f"  Evidence files: {note_count}")

    # Copy notes to target cases
    for case_id in [32, 33, 34, 35, 36, 37, 38, 39]:
        copied = copy_notes(31, case_id)
        print(f"  Total notes copied: {copied}")

    # Check evidence status
    print("\n[EVIDENCE] Current status:")
    for case_id in [31, 32, 33, 34, 35, 36, 37, 38, 39]:
        count, files = check_evidence(case_id)
        status = f"{count} file(s)" if count > 0 else "None"
        print(f"  Case {case_id}: {status}")

    print("\n" + "="*60)
    print("ADAPT COMPLETE")
    print("="*60)

#!/usr/bin/env python3
"""Copy and adapt notes from case 31 to cases 32-35."""

import sys
sys.path.insert(0, '/iriswebapp/source')
import os
os.environ['FLASK_ENV'] = 'development'

from app import app, db
from app.models.cases import Cases
from app.models.models import CaseNotes
from datetime import datetime

CASE_31_ASSETS = {'RAND-LT-0355': 0, 'RAND-LT-0231': 1, 'RAND-LT-0198': 2, 'RAND-DT-0410': 3, 'rbeaumont': 0, 'dpatel': 1, 'mschwartz': 2, 'tokafor': 3}

ASSET_PATTERNS = {
    32: {'computers': ['WKS-001', 'WKS-002', 'WKS-003', 'WKS-004', 'WKS-005'], 'users': ['jsmith', 'bwilson', 'clee', 'djones']},
    33: {'computers': ['DEV-100', 'DEV-101', 'DEV-102', 'DEV-103', 'DEV-104'], 'users': ['analyst_1', 'analyst_2', 'analyst_3', 'analyst_4']},
    34: {'computers': ['LAB-201', 'LAB-202', 'LAB-203', 'LAB-204', 'LAB-205'], 'users': ['tech_alpha', 'tech_beta', 'tech_gamma', 'tech_delta']},
    35: {'computers': ['SYS-401', 'SYS-402', 'SYS-403', 'SYS-404', 'SYS-405'], 'users': ['admin_a', 'admin_b', 'admin_c', 'admin_d']}
}

print("\n" + "="*60)
print("COPYING NOTES TO PHISHING CASES 32-35")
print("="*60)

for case_id in [32, 33, 34, 35]:
    with app.app_context():
        source_case = db.session.get(Cases, 31)
        target_case = db.session.get(Cases, case_id)
        if not source_case or not target_case:
            print(f'ERROR: case not found')
            continue

        print(f'\nCase #{case_id}: {target_case.case_name}')

        patterns = ASSET_PATTERNS[case_id]
        computers = patterns['computers']
        users = patterns['users']

        asset_map = {}
        for asset31, idx in CASE_31_ASSETS.items():
            if asset31.startswith('RAND'):
                asset_map[asset31] = computers[idx % len(computers)]
            else:
                asset_map[asset31] = users[idx % len(users)]

        source_notes = db.session.query(CaseNotes).filter_by(case_id=31).all()
        copied = 0

        for note in source_notes:
            content = note.note_content
            for old, new in asset_map.items():
                content = content.replace(old, new)

            source_cust = source_case.client.client_name if source_case.client else 'RAND'
            target_cust = target_case.client.client_name if target_case.client else 'TARG'
            content = content.replace(source_cust, target_cust)
            content = content.replace('RAND-', f'{target_cust[:3].upper()}-')

            new_note = CaseNotes(case_id=case_id, note_title=note.note_title, note_content=content, note_creationdate=datetime.utcnow())
            db.session.add(new_note)
            copied += 1

        db.session.commit()
        print(f'  ✓ Copied {copied} notes')

print("\n" + "="*60)
print("NOTES COPY COMPLETE")
print("="*60)

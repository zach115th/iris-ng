"""Smoke-test the Hayabusa parser against a real CSV fixture.

Run inside the iriswebapp_app container, where the iris-next package is
on PYTHONPATH:

    docker exec iriswebapp_app python /iriswebapp/scripts/_test_hayabusa_parser.py /tmp/hayabusa.csv
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, '/iriswebapp')
from app.iris_engine.working_timeline.hayabusa_parser import parse_hayabusa_csv  # noqa: E402


def main(csv_path: str) -> int:
    raw = Path(csv_path).read_bytes()
    print(f'== Parsing {csv_path} ({len(raw)} bytes) ==')
    batch_id, events = parse_hayabusa_csv(raw, case_id=999)
    print(f'batch_id      = {batch_id}')
    print(f'event count   = {len(events)}')
    print()
    sevs = {}
    sources = {}
    for e in events:
        sevs[e['severity']] = sevs.get(e['severity'], 0) + 1
        sources[e['event_source_host']] = sources.get(e['event_source_host'], 0) + 1
    print(f'by severity   = {sevs}')
    print(f'by host       = {sources}')
    print()
    if events:
        print('=== first event ===')
        sample = dict(events[0])
        sample['event_date'] = sample['event_date'].isoformat()
        sample['import_batch_id'] = str(sample['import_batch_id'])
        # Trim noisy fields for printing
        sample['event_description'] = sample['event_description'][:600] + ' …(trim)' if len(sample['event_description']) > 600 else sample['event_description']
        print(json.dumps(sample, indent=2, default=str))
        print()
        print('=== last event ===')
        sample = dict(events[-1])
        sample['event_date'] = sample['event_date'].isoformat()
        sample['import_batch_id'] = str(sample['import_batch_id'])
        sample['event_description'] = sample['event_description'][:600] + ' …(trim)' if len(sample['event_description']) > 600 else sample['event_description']
        print(json.dumps(sample, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else '/tmp/hayabusa.csv'))

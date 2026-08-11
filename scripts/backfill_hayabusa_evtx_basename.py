"""Backfill: shorten the `EvtxFile:` line on existing Hayabusa working-timeline
rows to the filename only (drop the long collection path).

Newly imported Hayabusa events already render the basename (see
`hayabusa_parser._build_description`). This one-off rewrites the
`event_description` of rows imported BEFORE that change so events already on
screen update too. Idempotent — re-running is a no-op once shortened.

Run inside the app container (scripts/ is mounted read-only at
/iriswebapp/scripts/):

    docker exec iriswebapp_app python /iriswebapp/scripts/backfill_hayabusa_evtx_basename.py            # dry-run
    docker exec iriswebapp_app python /iriswebapp/scripts/backfill_hayabusa_evtx_basename.py --apply     # commit
    docker exec iriswebapp_app python /iriswebapp/scripts/backfill_hayabusa_evtx_basename.py --apply --case-id 3
"""
from __future__ import annotations

import argparse
import os
import re
import sys

# Make the `app` package importable regardless of cwd. In the container the
# app lives at /iriswebapp/app; this script is mounted at /iriswebapp/scripts.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, '/iriswebapp')

# Matches the rendered header line:  **EvtxFile:** `<path>`
# Captures the backticked value so we can rewrite just the path inside it.
_EVTX_LINE = re.compile(r'(\*\*EvtxFile:\*\*\s*`)([^`]+)(`)')


def _basename(path: str) -> str:
    """Last path component, splitting on both separators.

    EVTX paths are Windows-native (backslashes); os.path.basename won't split
    on '\\' under Linux, so split on the character class explicitly.
    """
    return re.split(r'[\\/]', path)[-1].strip() or path


def _shorten(desc: str) -> tuple[str, bool]:
    changed = False

    def repl(m: re.Match) -> str:
        nonlocal changed
        full = m.group(2)
        short = _basename(full)
        if short != full:
            changed = True
        return f'{m.group(1)}{short}{m.group(3)}'

    return _EVTX_LINE.sub(repl, desc), changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='commit changes (default: dry-run)')
    ap.add_argument('--case-id', type=int, default=None, help='limit to one case')
    args = ap.parse_args()

    from app import app, db
    from app.models.cases import CaseWorkingEvent

    with app.app_context():
        q = CaseWorkingEvent.query.filter(CaseWorkingEvent.source == 'hayabusa')
        if args.case_id is not None:
            q = q.filter(CaseWorkingEvent.case_id == args.case_id)

        rows = q.all()
        total = len(rows)
        updated = 0

        for row in rows:
            desc = row.event_description or ''
            if '**EvtxFile:**' not in desc:
                continue
            new_desc, changed = _shorten(desc)
            if changed:
                updated += 1
                if args.apply:
                    row.event_description = new_desc

        if args.apply:
            db.session.commit()
            print(f'[apply] hayabusa rows scanned={total}  updated={updated}')
        else:
            print(f'[dry-run] hayabusa rows scanned={total}  would-update={updated}')
            print('         re-run with --apply to commit')

    return 0


if __name__ == '__main__':
    sys.exit(main())

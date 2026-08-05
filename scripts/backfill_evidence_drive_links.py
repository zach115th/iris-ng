#!/usr/bin/env python3
#  IRIS-NG helper
#
#  One-time / repeatable backfill: link evidence items (case_received_file) to
#  physical drives (evidence_drive) when the item's custody `barcode` field
#  matches a drive's barcode but `drive_id` is still NULL.
#
#  This is the same reconciliation `add_rfile`/`update_rfile` now do on save
#  (_reconcile_evidence_drive), applied retroactively to rows created before the
#  drive picker existed (or saved without selecting the drive).
#
#  Mounted read-only into the app + worker at /iriswebapp/scripts/. Run:
#     docker exec iriswebapp_app python /iriswebapp/scripts/backfill_evidence_drive_links.py [--apply]
#  Default is a DRY RUN; pass --apply to commit the links.

import sys

# `from app import app` resolves with /iriswebapp/app on the path (app/__init__.py
# is the package). Running a script by absolute path puts the script's own dir
# first, not the app root, so add it explicitly.
sys.path.insert(0, '/iriswebapp/app')
sys.path.insert(0, '/iriswebapp')

from app import app  # noqa: E402


def main(apply_changes: bool) -> int:
    with app.app_context():
        from app import db
        from app.models.models import CaseReceivedFile, EvidenceDrive

        drives = EvidenceDrive.query.all()
        by_exact = {d.barcode: d for d in drives if d.barcode}
        by_lower = {d.barcode.lower(): d for d in drives if d.barcode}

        cands = CaseReceivedFile.query.filter(
            CaseReceivedFile.barcode.isnot(None),
            CaseReceivedFile.drive_id.is_(None),
        ).all()

        linked = 0
        for e in cands:
            bc = (e.barcode or '').strip()
            if not bc:
                continue
            drive = by_exact.get(bc) or by_lower.get(bc.lower())
            if drive is None:
                continue
            print(f"  ev id={e.id} case={e.case_id} barcode={bc!r} -> drive id={drive.id} "
                  f"({drive.label or drive.barcode})")
            if apply_changes:
                e.drive_id = drive.id
            linked += 1

        if apply_changes and linked:
            db.session.commit()

        verb = 'linked' if apply_changes else 'would link (dry run)'
        print(f"\n{linked} evidence item(s) {verb}.")
        if not apply_changes and linked:
            print("Re-run with --apply to commit.")
    return 0


if __name__ == '__main__':
    main('--apply' in sys.argv)

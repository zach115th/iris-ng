#!/usr/bin/env python3
"""Backfill ioc_note_link rows by substring-matching IOC values against
note text inside one or more cases.

Use cases:
- After adding the `ioc_note_link` table on an existing deployment, populate
  it from the note bodies that already mention the IOCs.
- After importing IOCs from an external source (alert ingest, MISP pull),
  link them to any existing notes that already reference them.

The matcher is intentionally conservative:
- Lowercases both sides.
- Refangs common defang patterns (`[.]`, `[:]`, `[/]`, `(.)`, `hxxp://`).
- Requires an exact substring hit on the IOC's stored value. Won't catch
  paraphrased mentions or partial-string IOCs (e.g. truncated hashes).

Idempotent — duplicates are skipped (the unique constraint on
`(ioc_id, note_id)` would reject them anyway).

Usage (must run inside the iriswebapp_app container so the DB is reachable):

    docker exec iriswebapp_app python /iriswebapp/scripts/backfill_ioc_note_links.py --case 3
    docker exec iriswebapp_app python /iriswebapp/scripts/backfill_ioc_note_links.py --all-cases
    docker exec iriswebapp_app python /iriswebapp/scripts/backfill_ioc_note_links.py --case 3 --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Iterable

# These imports require the iris-next Flask app context, so this script must
# run from inside the iriswebapp_app container (or with PYTHONPATH and env
# pointing at a live iris-next checkout).
from app import app, db
from app.models.models import Ioc, IocNoteLink, Notes


DEFANG_RULES = [
    (re.compile(r"\[\.\]"), "."),
    (re.compile(r"\[:\]"), ":"),
    (re.compile(r"\[/\]"), "/"),
    (re.compile(r"\(\.\)"), "."),
    (re.compile(r"hxxps?://", re.IGNORECASE),
     lambda m: m.group(0).replace("xxp", "ttp").replace("XXP", "TTP")),
]


def refang(s: str) -> str:
    for rx, repl in DEFANG_RULES:
        s = rx.sub(repl, s)
    return s


def backfill_case(case_id: int, *, dry_run: bool, source_label: str) -> tuple[int, int]:
    notes = Notes.query.filter(Notes.note_case_id == case_id).all()
    iocs = Ioc.query.filter(Ioc.case_id == case_id).all()
    if not notes:
        print(f"  case {case_id}: no notes — skipping")
        return (0, 0)
    if not iocs:
        print(f"  case {case_id}: no IOCs — skipping")
        return (0, 0)

    matches = 0
    skipped_existing = 0
    print(f"  case {case_id}: {len(notes)} notes, {len(iocs)} IOCs")

    for n in notes:
        text_lower = refang(n.note_content or "").lower()
        if not text_lower:
            continue
        for i in iocs:
            v = (i.ioc_value or "").strip().lower()
            if not v or v not in text_lower:
                continue
            existing = IocNoteLink.query.filter(
                IocNoteLink.ioc_id == i.ioc_id,
                IocNoteLink.note_id == n.note_id,
            ).first()
            if existing is not None:
                skipped_existing += 1
                continue
            label = i.ioc_value if len(i.ioc_value) <= 40 else i.ioc_value[:37] + "..."
            print(f"    + IOC #{i.ioc_id:>4} ({label:<40}) -> Note #{n.note_id} '{n.note_title}'")
            if dry_run:
                continue
            link = IocNoteLink(
                ioc_id=i.ioc_id,
                note_id=n.note_id,
                case_id=case_id,
                source=source_label,
            )
            db.session.add(link)
            matches += 1

    if not dry_run and matches:
        db.session.commit()

    return (matches, skipped_existing)


def main(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--case", type=int, help="Backfill a single case_id.")
    g.add_argument("--all-cases", action="store_true", help="Backfill every case.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be linked but don't write.")
    parser.add_argument("--source", default="backfill_substring_refanged",
                        help="Value for the ioc_note_link.source column "
                             "(default: backfill_substring_refanged).")
    args = parser.parse_args(list(argv))

    with app.app_context():
        from app.models.cases import Cases  # local import — avoids unused-symbol noise on top

        if args.all_cases:
            case_ids = [c.case_id for c in Cases.query.all()]
        else:
            case_ids = [args.case]

        total_created = 0
        total_existing = 0
        for cid in case_ids:
            created, existing = backfill_case(cid, dry_run=args.dry_run, source_label=args.source)
            total_created += created
            total_existing += existing

        verb = "would create" if args.dry_run else "created"
        print()
        print(f"{verb} {total_created} new link rows; {total_existing} already linked (skipped).")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

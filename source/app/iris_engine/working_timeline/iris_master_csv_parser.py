"""IRIS-NG master-timeline CSV → CaseWorkingEvent rows.

Parses a CSV produced by the master-timeline "Download as CSV" export and
stages the rows as pending working events so they can be reviewed and
selectively promoted back (e.g. after importing a saved timeline dump).

Expected header (canonical round-trip format):
    event_date,event_tz,event_title,event_category,event_content,
    event_raw,event_source,event_assets,event_iocs,event_tags

Column mapping to CaseWorkingEvent:
    event_date       → event_date  (ISO datetime, parsed to naive UTC)
    event_tz         → stored in event_raw for reference
    event_title      → event_title
    event_category   → stored in event_raw (no equivalent column on CWE)
    event_content    → event_description
    event_raw        → event_raw (merged with tz/category metadata)
    event_source     → event_source_host  (closest analogue on CWE)
    event_assets     → stored in event_raw (assets don't auto-resolve at import;
                        analyst reviews and promotes, then links via normal flow)
    event_iocs       → stored in event_raw
    event_tags       → event_tags (pipe-separated → comma-separated)
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime


REQUIRED_FIELDS = {
    'event_date', 'event_tz', 'event_title', 'event_category',
    'event_content', 'event_raw', 'event_source', 'event_assets',
    'event_iocs', 'event_tags',
}


class MasterCsvParseError(Exception):
    """Raised when the CSV is unrecognized, malformed, or empty."""


def _parse_event_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip().rstrip('Z')
    for fmt in (
        '%Y-%m-%dT%H:%M:%S.%f',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d %H:%M:%S.%f',
        '%Y-%m-%d %H:%M:%S',
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_master_csv(
    csv_bytes: bytes | str,
    case_id: int,
) -> tuple[uuid.UUID, list[dict]]:
    """Parse a master-timeline CSV export into CaseWorkingEvent dicts.

    Returns ``(batch_id, rows)`` where each row is a dict ready to be
    passed to the ``CaseWorkingEvent`` constructor.

    Raises :class:`MasterCsvParseError` on bad input.
    """
    if isinstance(csv_bytes, bytes):
        text = csv_bytes.decode('utf-8-sig', errors='replace')
    else:
        text = csv_bytes

    text = text.strip()
    if not text:
        raise MasterCsvParseError('The uploaded CSV file is empty.')

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise MasterCsvParseError('Could not read CSV header row.')

    header = {f.strip().lower() for f in reader.fieldnames}
    missing = REQUIRED_FIELDS - header
    if missing:
        raise MasterCsvParseError(
            f'Unrecognised CSV format — missing column(s): {", ".join(sorted(missing))}. '
            f'Expected a master-timeline export with columns: '
            f'{", ".join(sorted(REQUIRED_FIELDS))}.'
        )

    batch_id = uuid.uuid4()
    rows: list[dict] = []

    for raw_row in reader:
        # Strip whitespace from all keys
        row = {k.strip().lower(): (v or '').strip() for k, v in raw_row.items() if k}

        event_date = _parse_event_date(row.get('event_date'))
        if event_date is None:
            # Keep rows with unparseable timestamps — same contract as other parsers
            pass

        title = row.get('event_title') or '(no title)'

        # Tags: master timeline uses pipe separator
        raw_tags = row.get('event_tags', '')
        tags = ','.join(t.strip() for t in raw_tags.split('|') if t.strip())

        # Pack original master-timeline fields that have no direct CWE column
        # into event_raw so nothing is lost after promote.
        event_raw = {
            'iris_master_csv_source': True,
            'event_tz': row.get('event_tz', ''),
            'event_category': row.get('event_category', ''),
            'event_raw_original': row.get('event_raw', ''),
            'event_assets': row.get('event_assets', ''),
            'event_iocs': row.get('event_iocs', ''),
        }

        rows.append({
            'case_id': case_id,
            'source': 'master-csv',
            'event_date': event_date,
            'event_title': title,
            'event_description': row.get('event_content', ''),
            'event_source_host': row.get('event_source', ''),
            'severity': None,
            'event_tags': tags or None,
            'mitre_techniques': None,
            'external_id': None,
            'event_raw': event_raw,
            'import_batch_id': batch_id,
        })

    if not rows:
        raise MasterCsvParseError('The CSV contained no data rows.')

    return batch_id, rows

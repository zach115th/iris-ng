"""IRIS-NG master-timeline CSV → CaseWorkingEvent rows.

Parses a CSV produced by the master-timeline "Download as CSV" export and
stages the rows as pending working events so they can be reviewed and
selectively promoted back (e.g. after importing a saved timeline dump).

Expected header (canonical round-trip format):
    event_date,event_tz,event_title,event_category,event_content,
    event_raw,event_source,event_assets,event_iocs,event_tags

Column mapping to CaseWorkingEvent:
    event_date       → event_date  (the time in event_tz, stored as naive UTC)
    event_tz         → applied to event_date, and kept in event_raw for reference
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
import re
from datetime import datetime
from datetime import timedelta
from datetime import timezone


REQUIRED_FIELDS = {
    'event_date', 'event_tz', 'event_title', 'event_category',
    'event_content', 'event_raw', 'event_source', 'event_assets',
    'event_iocs', 'event_tags',
}


class MasterCsvParseError(Exception):
    """Raised when the CSV is unrecognized, malformed, or empty."""


_OFFSET_RE = re.compile(r'^([+-])(\d{2}):?(\d{2})?$')


def _parse_offset(value: str | None) -> timedelta | None:
    """'+02:00' / '-0700' / '+05' -> timedelta; blank, Z or UTC -> zero;
    anything else -> None (the time is then read as UTC)."""
    value = (value or '').strip()
    if not value or value.upper() in ('Z', 'UTC', 'GMT'):
        return timedelta(0)
    m = _OFFSET_RE.match(value)
    if not m:
        return None
    delta = timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0))
    return delta if m.group(1) == '+' else -delta


def _event_utc(value: str | None, tz: str | None) -> datetime | None:
    """The row's instant as naive UTC (iris-ng 2026-10-30). event_date is the
    time in event_tz - the master-timeline import reads the same file the same
    way. This parser used to keep event_tz only as a note and take event_date
    as UTC, so the two importers disagreed. A date that carries its own
    offset (or Z) is converted with that offset instead."""
    if not value:
        return None
    text = value.strip()
    own = re.search(r'(Z|[+-]\d{2}:?\d{2})$', text)
    if own and re.search(r'\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$', text):
        try:
            aware = datetime.fromisoformat(text.replace('Z', '+00:00'))
            if aware.tzinfo is not None:
                return aware.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            pass
    local = _parse_event_date(text)
    if local is None:
        return None
    offset = _parse_offset(tz)
    return local - offset if offset is not None else local


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

        event_date = _event_utc(row.get('event_date'), row.get('event_tz'))
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

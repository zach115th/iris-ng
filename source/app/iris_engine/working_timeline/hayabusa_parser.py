"""Hayabusa CSV → CaseWorkingEvent rows.

Hayabusa (https://github.com/Yamato-Security/hayabusa) emits one row per
sigma rule that matched a given EVTX event, so a single Windows EID
typically fans out into 3-5 rows ("Proc Exec", "Possible LOLBIN",
"Scheduled Task Creation Via Schtasks.EXE", …). Without grouping you
end up with a working timeline that's mostly duplicates.

We collapse on the natural key (Timestamp, Computer, Channel, EventID,
RecordID) and keep the highest-severity rule's title as the headline.
All matched rule titles are appended to the description so analysts
can see every sigma signal that fired on the same underlying event.

Reference: Hayabusa2SANSTimeline.ps1 (Zach Mathis), which does a 1:1
row passthrough with no grouping. The PS shape is good for SANS
spreadsheet review; for IRIS-NG we want analyst-reviewable cards, so
we collapse.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import datetime
from typing import Any, Iterable

# Hayabusa's `Level` values, in ascending order so we can pick the
# highest-severity rule title as the canonical headline for a group.
_SEVERITY_RANK = {
    'info': 0,
    'low': 1,
    'med': 2,
    'medium': 2,
    'high': 3,
    'crit': 4,
    'critical': 4,
}

_TIMESTAMP_RE = re.compile(r'^\s*(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2}(?:\.\d+)?)')

# Hayabusa uses 4-letter shortcodes for the EVTX channel. Map back to the
# canonical Windows log name so the promoted event's Event Source field
# reads like a Windows analyst would write it (e.g., "Windows Security 4688")
# rather than Hayabusa's terse "Sec/4688".
HAYABUSA_CHANNEL_LONG: dict[str, str] = {
    'Sec':           'Security',
    'Sys':           'System',
    'App':           'Application',
    'Defender':      'Microsoft-Windows-Windows Defender/Operational',
    'PwSh':          'Microsoft-Windows-PowerShell/Operational',
    'PwShClassic':   'Windows PowerShell',
    'Sysmon':        'Microsoft-Windows-Sysmon/Operational',
    'Setup':         'Setup',
    'TaskSch':       'Microsoft-Windows-TaskScheduler/Operational',
    'TermSrv-LSM':   'Microsoft-Windows-TerminalServices-LocalSessionManager/Operational',
    'TermSrv-RCM':   'Microsoft-Windows-TerminalServices-RemoteConnectionManager/Operational',
    'TermSrv-RDPCli':'Microsoft-Windows-TerminalServices-RDPClient/Operational',
    'WMI':           'Microsoft-Windows-WMI-Activity/Operational',
    'Bits-Cli':      'Microsoft-Windows-Bits-Client/Operational',
    'CodeInteg':     'Microsoft-Windows-CodeIntegrity/Operational',
    'Dns-Cli':       'Microsoft-Windows-DNS-Client/Operational',
    'AppLocker':     'Microsoft-Windows-AppLocker/EXE and DLL',
    'Smb-Cli-Sec':   'Microsoft-Windows-SmbClient/Security',
    'Smb-Srv-Sec':   'Microsoft-Windows-SMBServer/Security',
}


def channel_to_long_name(short: str | None) -> str:
    """Return the human-readable Windows log name for a Hayabusa channel
    shortcode. Falls back to the shortcode itself if unmapped."""
    if not short:
        return ''
    return HAYABUSA_CHANNEL_LONG.get(short.strip(), short.strip())


def format_event_source(channel: str | None, event_id: str | None) -> str:
    """Build the IRIS-NG Event Source string from a Hayabusa channel/EID
    pair. Style: 'Windows <Channel> <EventID>' — matches how a Windows
    analyst would describe an EVTX event in prose."""
    chan = channel_to_long_name(channel)
    eid = (event_id or '').strip()
    parts: list[str] = []
    if chan:
        parts.append(chan)
    if eid:
        parts.append(eid)
    if not parts:
        return ''
    # Prefix with "Windows" unless the channel already contains "Windows"
    # (avoids "Windows Microsoft-Windows-…" duplication).
    if 'Windows' in chan:
        return ' '.join(parts)
    return 'Windows ' + ' '.join(parts)


# Subject extraction — pulls structured (host / user / domain) from the
# Hayabusa Details and ExtraFieldInfo blocks so the promote-to-event flow
# can ensure CaseAssets rows for them.
_USER_LINE_RE = re.compile(r'^\s*User\s*:\s*(.+?)\s*$', re.MULTILINE)
_KV_RE = re.compile(r'^\s*([A-Za-z][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$', re.MULTILINE)


def _is_meaningful(value: str | None) -> bool:
    """Hayabusa fills missing fields with '-' or '0x0' or 'S-1-0-0'.
    Skip those when extracting subject info."""
    if not value:
        return False
    v = value.strip()
    if not v or v in ('-', '0x0', 'S-1-0-0', 'NULL', 'null', '(null)'):
        return False
    return True


def _split_domain_user(raw: str) -> tuple[str | None, str]:
    """`OFFSEC\\admmig` → ('OFFSEC', 'admmig'). Bare names → (None, name)."""
    raw = raw.strip()
    if '\\' in raw:
        domain, user = raw.split('\\', 1)
        return (domain.strip() or None, user.strip())
    return (None, raw)


def _extract_subjects(head: dict[str, str]) -> dict[str, Any]:
    """Pull subject/target user + domain out of Details + ExtraFieldInfo.

    Returns a dict shaped for downstream asset-creation:
        {
            'host': 'jump01.offsec.lan',
            'subject_user': 'lambda-user',
            'subject_domain': 'OFFSEC' | None,
            'target_user': 'admmig' | None,
            'target_domain': 'OFFSEC' | None,
        }

    All fields are None when unparseable. The caller decides which assets
    to materialize (today: the host always; the subject user always; the
    target user only when present)."""
    out: dict[str, Any] = {
        'host': (head.get('Computer') or '').strip() or None,
        'subject_user': None,
        'subject_domain': None,
        'target_user': None,
        'target_domain': None,
    }

    # Subject user lives in Details as a bare `User: <value>` line. The
    # value may already be DOMAIN\user (Defender events) or bare (Sec
    # 4688 events with SubjectDomainName in ExtraFieldInfo).
    details = head.get('Details') or ''
    m = _USER_LINE_RE.search(details)
    if m and _is_meaningful(m.group(1)):
        domain, user = _split_domain_user(m.group(1))
        if user:
            out['subject_user'] = user
        if domain:
            out['subject_domain'] = domain

    # ExtraFieldInfo has the structured form (SubjectDomainName,
    # TargetUserName, TargetDomainName). Use these to fill gaps and to
    # detect a separate target principal (lateral movement signal).
    extra = head.get('ExtraFieldInfo') or ''
    kvs: dict[str, str] = {}
    for km in _KV_RE.finditer(extra):
        kvs[km.group(1)] = km.group(2)

    if not out['subject_domain'] and _is_meaningful(kvs.get('SubjectDomainName')):
        out['subject_domain'] = kvs['SubjectDomainName'].strip()

    if _is_meaningful(kvs.get('TargetUserName')):
        out['target_user'] = kvs['TargetUserName'].strip()
    if _is_meaningful(kvs.get('TargetDomainName')):
        out['target_domain'] = kvs['TargetDomainName'].strip()

    return out


class HayabusaParseError(Exception):
    """Raised when the Hayabusa CSV is malformed or empty."""


def _normalize_severity(level: str | None) -> str | None:
    if not level:
        return None
    lvl = level.strip().lower()
    return lvl if lvl in _SEVERITY_RANK else None


def _parse_timestamp(value: str) -> datetime | None:
    """Parse Hayabusa's ``YYYY-MM-DD HH:MM:SS.fff +HH:MM`` timestamp.

    We strip the offset and treat as UTC — Hayabusa always emits in
    the timezone you ran it under, and the fixture files we see have
    been ``--UTC``-flagged. If that assumption breaks for some user
    we'll add a per-import tz override later.
    """
    if not value:
        return None
    m = _TIMESTAMP_RE.match(value)
    if not m:
        return None
    date_part, time_part = m.group(1), m.group(2)
    try:
        if '.' in time_part:
            return datetime.strptime(f'{date_part} {time_part}', '%Y-%m-%d %H:%M:%S.%f')
        return datetime.strptime(f'{date_part} {time_part}', '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None


def _split_multi(value: str | None) -> list[str]:
    """Hayabusa joins multi-value cells with newlines; split + clean."""
    if not value:
        return []
    parts = re.split(r'[\n,;]+', value)
    return [p.strip() for p in parts if p and p.strip()]


def _collapse_whitespace(value: str | None) -> str:
    if not value:
        return ''
    return re.sub(r'\s+', ' ', value).strip()


def _group_key(row: dict[str, str]) -> tuple:
    """Natural key for collapsing fan-out rows."""
    return (
        row.get('Timestamp', '').strip(),
        row.get('Computer', '').strip(),
        row.get('Channel', '').strip(),
        row.get('EventID', '').strip(),
        row.get('RecordID', '').strip(),
    )


def _build_description(grouped_rows: list[dict[str, str]]) -> str:
    """Compose the card body from all rules that fired on this event.

    Layout:
        **Channel/EID** Sec/4688  ·  **RID:** 2774613  ·  **EvtxFile:** ...

        **Sigma matches:**
        - [info] Proc Exec
        - [low] Possible LOLBIN
        - [low] Scheduled Task Creation Via Schtasks.EXE

        **Details:** Cmdline: schtasks /create /s fs02 /tn ...

        **Extra:** ParentProcessName: cmd.exe …
    """
    head = grouped_rows[0]
    parts: list[str] = []

    # Header line — the deterministic facts about the underlying EVTX event.
    chan = head.get('Channel', '').strip() or '?'
    eid = head.get('EventID', '').strip() or '?'
    rid = head.get('RecordID', '').strip()
    evtx = head.get('EvtxFile', '').strip()
    provider = head.get('Provider', '').strip()

    header_bits = [f'**Channel/EID** `{chan}/{eid}`']
    if rid:
        header_bits.append(f'**RID:** `{rid}`')
    if provider:
        header_bits.append(f'**Provider:** `{provider}`')
    parts.append(' · '.join(header_bits))
    if evtx:
        parts.append(f'**EvtxFile:** `{evtx}`')

    # Sigma matches — every rule that fired on this underlying event.
    matches: list[str] = []
    for r in grouped_rows:
        title = (r.get('RuleTitle') or '').strip()
        if not title:
            continue
        lvl = (r.get('Level') or '').strip().lower() or 'info'
        matches.append(f'- [{lvl}] {title}')
    if matches:
        parts.append('**Sigma matches:**')
        parts.append('\n'.join(matches))

    # Details + ExtraFieldInfo are the same across all rows in a group
    # (they describe the underlying event, not the rule), so emit once.
    details = (head.get('Details') or '').strip()
    if details:
        parts.append(f'**Details:**\n```\n{details}\n```')

    extra = (head.get('ExtraFieldInfo') or '').strip()
    if extra:
        # ExtraFieldInfo can be very long (full XML for task creation),
        # cap so a card stays scannable.
        if len(extra) > 1500:
            extra = extra[:1500] + ' …(truncated)'
        parts.append(f'**Extra:**\n```\n{extra}\n```')

    return '\n\n'.join(parts)


def _build_tags(grouped_rows: list[dict[str, str]]) -> str:
    """Comma-separated tag string for the event_tags column.

    Includes ``hayabusa`` source tag, severity, computer hostname,
    plus every distinct OtherTags value across the group (lolbas,
    detection.threat-hunting, malware, etc.).
    """
    tags: list[str] = ['hayabusa']
    head = grouped_rows[0]

    # Severity = highest level seen across the group.
    best_lvl = max(
        (r.get('Level', '').strip().lower() for r in grouped_rows),
        key=lambda l: _SEVERITY_RANK.get(l, -1),
        default=''
    )
    if best_lvl:
        tags.append(f'sigma:{best_lvl}')

    computer = (head.get('Computer') or '').strip()
    if computer:
        tags.append(f'host:{computer}')

    # OtherTags can have lolbas / car.* / detection.threat-hunting / malware ...
    other: set[str] = set()
    for r in grouped_rows:
        for t in _split_multi(r.get('OtherTags')):
            other.add(t)
    tags.extend(sorted(other))
    return ','.join(tags)


def _build_mitre_techniques(grouped_rows: list[dict[str, str]]) -> str:
    """Extract MITRE technique IDs (T1003, T1053.005, S0002…) across the group."""
    techs: set[str] = set()
    for r in grouped_rows:
        for t in _split_multi(r.get('MitreTags')):
            techs.add(t)
    return ','.join(sorted(techs))


def _pick_headline(grouped_rows: list[dict[str, str]]) -> str:
    """Headline = the highest-severity rule's title.

    Tie-break: stable order (first row of the highest level wins).
    Falls back to a synthetic headline if no rule title is present.
    """
    best: tuple[int, str] = (-1, '')
    for r in grouped_rows:
        lvl = (r.get('Level') or '').strip().lower()
        rank = _SEVERITY_RANK.get(lvl, -1)
        title = (r.get('RuleTitle') or '').strip()
        if not title:
            continue
        if rank > best[0]:
            best = (rank, title)

    if best[1]:
        head = grouped_rows[0]
        lvl = max(
            (r.get('Level', '').strip().lower() for r in grouped_rows),
            key=lambda l: _SEVERITY_RANK.get(l, -1),
            default=''
        )
        host = (head.get('Computer') or '').strip()
        n = len(grouped_rows)
        prefix = f'[{lvl}] ' if lvl else ''
        suffix = f' ({n} rules)' if n > 1 else ''
        host_part = f' on {host}' if host else ''
        return f'{prefix}{best[1]}{host_part}{suffix}'

    head = grouped_rows[0]
    return (
        f"Sigma match — {head.get('Channel', '?')}/{head.get('EventID', '?')} "
        f"on {head.get('Computer') or 'unknown'}"
    )


def parse_hayabusa_csv(csv_bytes: bytes | str, case_id: int) -> tuple[uuid.UUID, list[dict[str, Any]]]:
    """Parse a Hayabusa CSV into CaseWorkingEvent-shaped dicts.

    Args:
        csv_bytes: Raw CSV (bytes from upload, or already-decoded str).
        case_id: Target case for FK.

    Returns:
        ``(import_batch_id, [event_dict, …])``. The batch id lets the UI
        show "Last import: 23 events from foo.csv" and lets us delete a
        bad import in one shot.

    Raises:
        HayabusaParseError: malformed CSV, empty CSV, or no usable rows.
    """
    if isinstance(csv_bytes, bytes):
        # Hayabusa writes UTF-8 BOM by default.
        text = csv_bytes.decode('utf-8-sig', errors='replace')
    else:
        text = csv_bytes

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    required = {'Timestamp', 'RuleTitle', 'Level', 'Computer', 'Channel', 'EventID'}
    missing = required - set(fieldnames)
    if missing:
        raise HayabusaParseError(
            f"CSV is missing expected Hayabusa columns: {sorted(missing)}. "
            f"Got columns: {fieldnames}"
        )

    # Group fan-out rows by natural key.
    groups: dict[tuple, list[dict[str, str]]] = {}
    skipped = 0
    for row in reader:
        # Skip the empty-row padding Hayabusa frequently emits at EOF.
        if not any(v and v.strip() for v in row.values()):
            continue
        if not row.get('Timestamp'):
            skipped += 1
            continue
        key = _group_key(row)
        groups.setdefault(key, []).append(row)

    if not groups:
        raise HayabusaParseError(
            f"No usable rows found in CSV (skipped {skipped} blank/headerless rows)."
        )

    batch_id = uuid.uuid4()
    out: list[dict[str, Any]] = []
    for key, rows in groups.items():
        ts = _parse_timestamp(key[0])
        if ts is None:
            continue
        head = rows[0]
        external_id = (
            f"{(head.get('Channel') or '?').strip()}/"
            f"{(head.get('EventID') or '?').strip()}"
            f"/RID:{(head.get('RecordID') or '').strip()}"
        )
        # Pick the highest-severity Level for the group.
        best_lvl = max(
            (r.get('Level', '').strip().lower() for r in rows),
            key=lambda l: _SEVERITY_RANK.get(l, -1),
            default=''
        )
        channel = (head.get('Channel') or '').strip()
        eid = (head.get('EventID') or '').strip()
        subjects = _extract_subjects(head)
        out.append({
            'case_id': case_id,
            'source': 'hayabusa',
            'event_date': ts,
            'event_title': _pick_headline(rows),
            'event_description': _build_description(rows),
            'event_source_host': _collapse_whitespace(head.get('Computer')),
            'severity': _normalize_severity(best_lvl),
            'event_tags': _build_tags(rows),
            'mitre_techniques': _build_mitre_techniques(rows),
            'external_id': external_id,
            'event_raw': {
                'matched_rules': [
                    {
                        'title': r.get('RuleTitle'),
                        'level': r.get('Level'),
                        'rule_id': r.get('RuleID'),
                        'rule_file': r.get('RuleFile'),
                        'rule_author': r.get('RuleAuthor'),
                    }
                    for r in rows
                ],
                'evtx_file': head.get('EvtxFile'),
                'provider': head.get('Provider'),
                # Channel + EventID kept verbatim in case downstream needs
                # them separately from the formatted Event Source string
                # (e.g. Sigma cross-check, IDS feed lookups).
                'channel': channel,
                'event_id_evtx': eid,
                # Pre-formatted Event Source string ready for the promoted
                # cases_event row's event_source field.
                'windows_event_source': format_event_source(channel, eid),
                # Structured subjects so the promote endpoint can ensure
                # CaseAssets rows for the host + users involved.
                'subjects': subjects,
            },
            'import_batch_id': batch_id,
            'status': 'pending',
        })

    out.sort(key=lambda e: e['event_date'])
    return batch_id, out

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

# Hayabusa abbreviates the EVTX channel. Map back to the canonical Windows
# log name so the promoted event's Event Source field reads like a Windows
# analyst would write it (e.g., "Windows Security 4688") rather than
# Hayabusa's terse "Sec/4688".
#
# The table mirrors hayabusa-rules/config/channel_abbreviations.txt (the
# file Hayabusa itself reads). Older spellings this parser accepted before
# it was aligned with that table (TermSrv-*, Bits-Cli, Smb-*-Sec, Dns-Cli)
# are kept so a CSV produced under either naming resolves the same way.
HAYABUSA_CHANNEL_LONG: dict[str, str] = {
    'Sec':           'Security',
    'Sys':           'System',
    'App':           'Application',
    'Setup':         'Setup',
    'Defender':      'Microsoft-Windows-Windows Defender/Operational',
    'PwSh':          'Microsoft-Windows-PowerShell/Operational',
    'PwShClassic':   'Windows PowerShell',
    'PwShCore':      'PowerShellCore',
    'Sysmon':        'Microsoft-Windows-Sysmon/Operational',
    'TaskSch':       'Microsoft-Windows-TaskScheduler/Operational',
    'WMI':           'Microsoft-Windows-WMI-Activity/Operational',
    'WinRM':         'Microsoft-Windows-WinRM/Operational',
    'NTLM':          'Microsoft-Windows-NTLM/Operational',
    'CodeInteg':     'Microsoft-Windows-CodeIntegrity/Operational',
    'AppLocker':     'Microsoft-Windows-AppLocker/EXE and DLL',
    'Firewall':      'Microsoft-Windows-Windows Firewall With Advanced Security/Firewall',
    'BitsCli':       'Microsoft-Windows-Bits-Client/Operational',
    'Bits-Cli':      'Microsoft-Windows-Bits-Client/Operational',
    'SmbCliSec':     'Microsoft-Windows-SmbClient/Security',
    'Smb-Cli-Sec':   'Microsoft-Windows-SmbClient/Security',
    'Smb-Srv-Sec':   'Microsoft-Windows-SMBServer/Security',
    'Dns-Cli':       'Microsoft-Windows-DNS-Client/Operational',
    'DNS-Svr':       'DNS Server',
    'DHCP-Svr':      'Microsoft-Windows-DHCP-Server/Operational',
    'LDAP-Cli':      'Microsoft-Windows-LDAP-Client/Debug',
    'KeyMgtSvc':     'Key Management Service',
    'SvcBusCli':     'Microsoft-ServiceBus-Client',
    'DvrFmwk':       'Microsoft-Windows-DriverFrameworks-UserMode/Operational',
    'SecMitig':      'Microsoft-Windows-Security-Mitigations/KernelMode',
    'PrintAdm':      'Microsoft-Windows-PrintService/Admin',
    'PrintOp':       'Microsoft-Windows-PrintService/Operational',
    'Exchange':      'MSExchange Management',
    'OpenSSH':       'OpenSSH/Operational',
    'RDS-LSM':       'Microsoft-Windows-TerminalServices-LocalSessionManager/Operational',
    'RDS-RCM':       'Microsoft-Windows-TerminalServices-RemoteConnectionManager/Operational',
    'RDS-GTW':       'Microsoft-Windows-TerminalServices-Gateway/Operational',
    'RDP-Cli':       'Microsoft-Windows-TerminalServices-RDPClient/Operational',
    'RDP-CoreTS':    'Microsoft-Windows-RemoteDesktopServices-RdpCoreTS/Operational',
    'TermSrv-LSM':   'Microsoft-Windows-TerminalServices-LocalSessionManager/Operational',
    'TermSrv-RCM':   'Microsoft-Windows-TerminalServices-RemoteConnectionManager/Operational',
    'TermSrv-RDPCli':'Microsoft-Windows-TerminalServices-RDPClient/Operational',
    'GroupPolicy':   'Microsoft-Windows-GroupPolicy/Operational',
    'UserProfileSvc':'Microsoft-Windows-User Profile Service/Operational',
    'Forwarding':    'Microsoft-Windows-Forwarding/Operational',
}

# Channels without a table entry are shortened generically by Hayabusa
# ("Microsoft-Windows-Ntfs/Operational" -> "MS-Win-Ntfs/Op"); the two
# generic pieces are reversed in channel_to_long_name().


def channel_to_long_name(short: str | None) -> str:
    """Return the human-readable Windows log name for a Hayabusa channel
    abbreviation. Table entries win; generic abbreviations are reversed;
    anything else falls back to the value itself."""
    if not short:
        return ''
    s = short.strip()
    if s in HAYABUSA_CHANNEL_LONG:
        return HAYABUSA_CHANNEL_LONG[s]
    out = s
    if out.startswith('MS-Win-'):
        out = 'Microsoft-Windows-' + out[len('MS-Win-'):]
    if out.endswith('/Op'):
        out = out[:-len('/Op')] + '/Operational'
    return out


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
    """Natural key for collapsing fan-out rows.

    ``or ''`` because csv.DictReader fills the cells a SHORT row lacks with
    None — a truncated last line must group as best it can, not raise."""
    return (
        (row.get('Timestamp') or '').strip(),
        (row.get('Computer') or '').strip(),
        (row.get('Channel') or '').strip(),
        (row.get('EventID') or '').strip(),
        (row.get('RecordID') or '').strip(),
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
        # Display the source EVTX filename only — the analyst doesn't need
        # the (often very long) collection path inline on the card. Split on
        # both separators since EVTX paths are Windows-native (backslashes)
        # but the parser runs in a Linux container where os.path.basename
        # won't split on '\'.
        evtx_name = re.split(r'[\\/]', evtx)[-1].strip() or evtx
        parts.append(f'**EvtxFile:** `{evtx_name}`')

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


# Canonical level names (what Hayabusa writes in `Level`) plus the aliases a
# caller may reasonably send. Filtering works on the canonical name.
LEVELS: tuple[str, ...] = ('info', 'low', 'med', 'high', 'crit')
_LEVEL_ALIASES = {'medium': 'med', 'critical': 'crit', 'informational': 'info'}

# A Hayabusa run over a full host yields hundreds of thousands of events
# (1.5 M on a 900 MB CSV, 99.9 % of them info); the working timeline is an
# analyst-review surface, not an archive. Same ceiling as the EZ Tools
# import. Narrow the date window or the levels to get under it.
MAX_EVENTS_PER_IMPORT = 25_000

_REQUIRED_COLUMNS = {'Timestamp', 'RuleTitle', 'Level', 'Computer', 'Channel', 'EventID'}


def normalize_levels(levels: Iterable[str] | None) -> set[str] | None:
    """Turn a caller-supplied level list into canonical names.

    ``None`` (or an empty iterable) means "no level filter". Unknown names
    raise ``ValueError`` naming the offender — a typo must not silently
    import everything or nothing.
    """
    if levels is None:
        return None
    out: set[str] = set()
    for raw in levels:
        if raw is None:
            continue
        name = str(raw).strip().lower()
        if not name:
            continue
        name = _LEVEL_ALIASES.get(name, name)
        if name not in LEVELS:
            raise ValueError(
                f"Unknown Hayabusa level {raw!r}. Expected one of: {', '.join(LEVELS)}."
            )
        out.add(name)
    return out or None


def _open_text(source: Any) -> io.TextIOBase:
    """Wrap whatever the caller handed us (bytes, str, binary or text
    stream) as a text stream the csv module can iterate lazily.

    A 900 MB upload must never be decoded into one Python string: with the
    upload spooled to disk by the form parser, streaming keeps peak memory
    at roughly the rows of a single timestamp plus the accepted events.
    """
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    if isinstance(source, str):
        return io.StringIO(source, newline='')
    if isinstance(source, io.TextIOBase):
        return source
    # Binary file-like (werkzeug FileStorage.stream, BytesIO, open(..., 'rb')).
    # Hayabusa writes a UTF-8 BOM by default; utf-8-sig strips it when present.
    return io.TextIOWrapper(source, encoding='utf-8-sig', errors='replace', newline='')


def _group_to_event(rows: list[dict[str, str]], ts: datetime, case_id: int,
                    batch_id: uuid.UUID) -> dict[str, Any]:
    head = rows[0]
    external_id = (
        f"{(head.get('Channel') or '?').strip()}/"
        f"{(head.get('EventID') or '?').strip()}"
        f"/RID:{(head.get('RecordID') or '').strip()}"
    )
    best_lvl = _group_level(rows)
    channel = (head.get('Channel') or '').strip()
    eid = (head.get('EventID') or '').strip()
    subjects = _extract_subjects(head)
    return {
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
    }


def _group_level(rows: list[dict[str, str]]) -> str:
    """Highest Level across the rules that fired on one event ('' if none)."""
    return max(
        (r.get('Level', '').strip().lower() for r in rows),
        key=lambda l: _SEVERITY_RANK.get(l, -1),
        default='',
    )


def parse_hayabusa_csv_ex(
    source: Any,
    case_id: int,
    *,
    levels: Iterable[str] | None = None,
    begin_dt: datetime | None = None,
    end_dt: datetime | None = None,
    max_events: int | None = -1,
) -> tuple[uuid.UUID, list[dict[str, Any]], dict[str, Any]]:
    """Stream a Hayabusa CSV into CaseWorkingEvent-shaped dicts.

    Args:
        source: Raw CSV as bytes, str, a binary stream (the upload's
            ``.stream``) or a text stream. Streams are read lazily.
        case_id: Target case for FK.
        levels: Keep only events whose highest rule level is in this set
            (canonical or alias names; see ``normalize_levels``). ``None``
            keeps every level. The filter is per EVENT, not per rule: a card
            keeps every rule that fired on it, and is dropped only when its
            highest level is excluded.
        begin_dt / end_dt: Inclusive timestamp window. Applied before the
            cap so out-of-window rows never consume it.
        max_events: Stop once this many events have been accepted (``None``
            = no cap; the default ``-1`` = ``MAX_EVENTS_PER_IMPORT`` as it
            is at call time). The remainder of the file is NOT scanned, so
            ``stats['truncated']`` says that the cap was hit, not how much
            was left.

    Returns:
        ``(import_batch_id, [event_dict, …], stats)`` with stats keys
        ``rows`` (data rows read), ``events`` (accepted), ``skipped_by_level``,
        ``skipped_out_of_range`` (events, not rows), ``skipped_no_timestamp``
        (rows), ``truncated`` (bool), ``cap``.

    Grouping: Hayabusa emits one row per sigma rule that matched an EVTX
    event, and writes its CSV sorted by Timestamp, so every row of one
    event is adjacent to its siblings. Groups are therefore flushed when
    the Timestamp changes — bounded memory regardless of file size. A CSV
    that is NOT sorted still parses; an event whose rows are separated by
    a different timestamp simply becomes two cards.

    Raises:
        HayabusaParseError: malformed CSV, empty CSV, or no usable rows.
        ValueError: an unknown level name.
    """
    level_set = normalize_levels(levels)
    if max_events == -1:
        max_events = MAX_EVENTS_PER_IMPORT
    text_stream = _open_text(source)
    reader = csv.DictReader(text_stream)
    fieldnames = reader.fieldnames or []
    missing = _REQUIRED_COLUMNS - set(fieldnames)
    if missing:
        raise HayabusaParseError(
            f"CSV is missing expected Hayabusa columns: {sorted(missing)}. "
            f"Got columns: {fieldnames}"
        )

    batch_id = uuid.uuid4()
    out: list[dict[str, Any]] = []
    stats: dict[str, Any] = {
        'rows': 0,
        'events': 0,
        'skipped_by_level': 0,
        'skipped_out_of_range': 0,
        'skipped_no_timestamp': 0,
        'truncated': False,
        'cap': max_events,
    }

    # Pending groups for the CURRENT timestamp only, keyed by natural key.
    pending: dict[tuple, list[dict[str, str]]] = {}
    pending_ts: str | None = None

    def _flush() -> bool:
        """Emit every pending group. Returns False once the cap is hit."""
        for key, rows in pending.items():
            ts = _parse_timestamp(key[0])
            if ts is None:
                stats['skipped_no_timestamp'] += len(rows)
                continue
            if (begin_dt and ts < begin_dt) or (end_dt and ts > end_dt):
                stats['skipped_out_of_range'] += 1
                continue
            if level_set is not None and _group_level(rows) not in level_set:
                stats['skipped_by_level'] += 1
                continue
            if max_events is not None and len(out) >= max_events:
                stats['truncated'] = True
                return False
            out.append(_group_to_event(rows, ts, case_id, batch_id))
        pending.clear()
        return True

    stopped = False
    for row in reader:
        # Skip the empty-row padding Hayabusa frequently emits at EOF.
        if not any(v and v.strip() for v in row.values() if isinstance(v, str)):
            continue
        stats['rows'] += 1
        # Hayabusa 3.x wrote multi-line cells (Details, ExtraFieldInfo,
        # multi-author RuleAuthor) with LF; 4.x keeps the raw CR/LF. Normalise
        # here so a card built from either version is byte-identical and no
        # bare CR reaches the stored description.
        # A SHORT row (fewer cells than the header) gets None for the cells
        # it lacks; every field reader below does `.get(k, '')`, which
        # returns that None, so blank them here once.
        for k, v in row.items():
            if v is None:
                row[k] = ''
            elif isinstance(v, str) and '\r' in v:
                row[k] = v.replace('\r\n', '\n').replace('\r', '\n')
        ts_raw = (row.get('Timestamp') or '').strip()
        if not ts_raw:
            stats['skipped_no_timestamp'] += 1
            continue
        if pending_ts is not None and ts_raw != pending_ts:
            if not _flush():
                stopped = True
                break
        pending_ts = ts_raw
        pending.setdefault(_group_key(row), []).append(row)

    if not stopped and pending:
        _flush()

    if stats['rows'] == 0:
        raise HayabusaParseError(
            f"No usable rows found in CSV (skipped {stats['skipped_no_timestamp']} blank/headerless rows)."
        )

    stats['events'] = len(out)
    out.sort(key=lambda e: e['event_date'])
    return batch_id, out, stats


def parse_hayabusa_csv(csv_bytes: bytes | str, case_id: int) -> tuple[uuid.UUID, list[dict[str, Any]]]:
    """Parse a Hayabusa CSV into CaseWorkingEvent-shaped dicts.

    Compatibility wrapper around ``parse_hayabusa_csv_ex`` with no level
    filter, no date window and the default event cap. Returns
    ``(import_batch_id, [event_dict, …])``.
    """
    batch_id, out, _stats = parse_hayabusa_csv_ex(csv_bytes, case_id)
    return batch_id, out

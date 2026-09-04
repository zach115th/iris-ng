"""Eric Zimmerman tools CSV → CaseWorkingEvent rows.

The EZ Tools suite (MFTECmd, EvtxECmd, PECmd, AppCompatCacheParser,
AmcacheParser, RBCmd, LECmd, JLECmd, SBECmd, RECmd) emits one CSV per
artifact type. KAPE bundles them into per-category subfolders
(ProgramExecution / FileSystem / EventLogs / FileDeletion / FileFolderAccess /
Registry). Analysts upload one CSV at a time; this parser auto-detects which
sub-format the CSV is by inspecting the column header, then maps rows to
working timeline events.

The supported sub-formats are listed in DETECTORS below. Each carries:
  signature: header-column set that uniquely identifies the CSV shape.
  kind:      stable identifier persisted into event_raw.eztools_kind.
  parser:    function (rows, batch_id, case_id) → list[dict].

A CSV that matches no detector is rejected — the caller surfaces the error
in the import modal so the analyst knows to upload a recognized format.
"""
from __future__ import annotations

import csv
import io
import re
import sys
import uuid
from datetime import datetime
from typing import Any, Callable, Iterable

# PECmd_Output.csv's Files / Directories columns concatenate every file and
# directory the prefetch references — for chromium-style binaries this
# routinely exceeds Python csv's default 128 KB per-field limit (raises
# `_csv.Error: field larger than field limit (131072)`). EZ Tools also
# emits huge MapDescription cells on some EvtxECmd events. Bump to the
# max int. This is module-level, so it persists across requests within
# the worker.
csv.field_size_limit(sys.maxsize)


# Cap per-CSV row count so a 5M-row $J doesn't OOM the worker. The analyst
# can re-run EZ Tools with a date-range filter if they need more — but 25k
# events per import covers the typical triage CSVs.
MAX_ROWS_PER_IMPORT = 25_000


class EztoolsParseError(Exception):
    """Raised when the CSV is unrecognized, malformed, or empty."""


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

# EZ Tools timestamps come in two common shapes:
#   1.  "2026-05-11 04:44:09.4536002"      (most parsers, .NET DateTime ticks)
#   2.  "2026-04-20 19:03:39"              (no fractional seconds)
# We strip any TZ offset (parsers emit local-of-host time) and parse as UTC.
_EZ_TS_RE = re.compile(
    r'^\s*(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?'
)


def _parse_ez_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    m = _EZ_TS_RE.match(value)
    if not m:
        return None
    date_part, time_part, frac = m.group(1), m.group(2), m.group(3)
    try:
        if frac:
            # .NET DateTime ticks can be up to 7 digits; Python wants ≤6.
            frac = (frac + '000000')[:6]
            return datetime.strptime(
                f'{date_part} {time_part}.{frac}', '%Y-%m-%d %H:%M:%S.%f'
            )
        return datetime.strptime(f'{date_part} {time_part}', '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None


def _truncate(value: str | None, limit: int = 1500) -> str:
    if not value:
        return ''
    value = str(value)
    if len(value) <= limit:
        return value
    return value[:limit] + ' …(truncated)'


def _clean(value: str | None) -> str:
    if value is None:
        return ''
    return str(value).strip()


def _basename(path: str | None) -> str:
    """Last path segment of a Windows or POSIX path.

    Handles `\\VOLUME{guid}\\PROGRAM FILES\\...\\foo.exe` style EZ Tools
    outputs as well as plain `C:\\Users\\X\\foo.exe`. Used to keep card
    titles + external_ids scannable when the full path is multi-hundred
    characters; the full path stays in the description body so the
    analyst can still see it on card expand.
    """
    if not path:
        return ''
    p = str(path).rstrip('\\/').strip()
    if not p:
        return ''
    for sep in ('\\', '/'):
        idx = p.rfind(sep)
        if idx >= 0:
            seg = p[idx + 1:]
            if seg:
                return seg
    return p


def _row_event_raw(row: dict[str, str], kind: str, *, drop_empty: bool = True) -> dict[str, Any]:
    """Build event_raw with the source row preserved + a kind discriminator."""
    out: dict[str, Any] = {'eztools_kind': kind}
    if drop_empty:
        out['row'] = {k: v for k, v in row.items() if v not in (None, '')}
    else:
        out['row'] = dict(row)
    return out


# --------------------------------------------------------------------------
# Sub-parsers — one per recognised EZ Tools CSV shape.
# Each returns a list of CaseWorkingEvent-shaped dicts (no batch_id /
# status yet — the wrapper adds those at the end).
# --------------------------------------------------------------------------

def _parse_evtxecmd(rows: Iterable[dict[str, str]], case_id: int) -> list[dict[str, Any]]:
    """EvtxECmd output: parsed Windows event log records."""
    out: list[dict[str, Any]] = []
    for row in rows:
        ts = _parse_ez_ts(row.get('TimeCreated'))
        if ts is None:
            continue
        eid = _clean(row.get('EventId'))
        channel = _clean(row.get('Channel'))
        provider = _clean(row.get('Provider'))
        computer = _clean(row.get('Computer'))
        level = (_clean(row.get('Level')) or 'info').lower()
        map_desc = _clean(row.get('MapDescription'))
        payload1 = _clean(row.get('PayloadData1'))
        record_id = _clean(row.get('EventRecordId') or row.get('RecordNumber'))

        title_parts = []
        if channel:
            title_parts.append(channel)
        if eid:
            title_parts.append(f'EID {eid}')
        if map_desc:
            title_parts.append(map_desc)
        title = ' · '.join(title_parts) or 'Windows event'
        if computer:
            title = f'{title} on {computer}'

        # Description: structured table + truncated payload.
        desc_lines = []
        for field in ('Channel', 'EventId', 'Provider', 'Level', 'Computer',
                      'UserName', 'UserId', 'ProcessId', 'MapDescription'):
            val = _clean(row.get(field))
            if val:
                desc_lines.append(f'- **{field}:** `{val}`')
        if desc_lines:
            desc_lines.insert(0, '**Event metadata:**')
        for field in ('PayloadData1', 'PayloadData2', 'PayloadData3',
                      'PayloadData4', 'PayloadData5', 'PayloadData6'):
            val = _clean(row.get(field))
            if val:
                desc_lines.append(f'- **{field}:** {val}')
        payload = _clean(row.get('Payload'))
        if payload:
            desc_lines.append('\n**Payload:**\n```\n' + _truncate(payload, 1500) + '\n```')
        description = '\n'.join(desc_lines)

        source_file = _clean(row.get('SourceFile'))
        if source_file:
            description = f'**SourceFile:** `{source_file}`\n\n' + description

        external_id = f'EvtxECmd/{channel or "?"}/{eid or "?"}/RID:{record_id}'
        raw = _row_event_raw(row, 'evtxecmd')
        raw['windows_event_source'] = (
            f'Windows {channel} {eid}'.strip()
            if channel else (eid or '')
        )

        out.append({
            'case_id': case_id,
            'source': 'eztools',
            'event_date': ts,
            'event_title': title,
            'event_description': description,
            'event_source_host': computer or None,
            'severity': _normalize_evtx_level(level),
            'event_tags': _tags_for('eztools', 'evtxecmd', host=computer,
                                    extras=[f'channel:{channel}'] if channel else None),
            'mitre_techniques': '',
            'external_id': external_id,
            'event_raw': raw,
        })
    return out


def _normalize_evtx_level(level: str) -> str | None:
    return {'info': 'info', 'information': 'info', 'verbose': 'info',
            'warning': 'med', 'error': 'high', 'critical': 'crit'}.get(level)


def _parse_mft_usn(rows: Iterable[dict[str, str]], case_id: int) -> list[dict[str, Any]]:
    """MFTECmd $J output: USN journal records (file create/rename/delete)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        ts = _parse_ez_ts(row.get('UpdateTimestamp'))
        if ts is None:
            continue
        name = _clean(row.get('Name'))
        parent_path = _clean(row.get('ParentPath'))
        reasons = _clean(row.get('UpdateReasons'))
        usn = _clean(row.get('UpdateSequenceNumber'))
        attrs = _clean(row.get('FileAttributes'))

        full_path = f'{parent_path}\\{name}' if parent_path else name
        title = f'USN: {reasons or "?"} — {name or "<unknown>"}'

        desc_lines = []
        if full_path:
            desc_lines.append(f'**Path:** `{full_path}`')
        if reasons:
            desc_lines.append(f'**Reasons:** `{reasons}`')
        if attrs:
            desc_lines.append(f'**Attributes:** `{attrs}`')
        if usn:
            desc_lines.append(f'**USN:** `{usn}`')
        source_file = _clean(row.get('SourceFile'))
        if source_file:
            desc_lines.append(f'**SourceFile:** `{source_file}`')

        sev = _usn_severity(reasons, full_path)
        external_id = f'USN/{usn}' if usn else f'USN/{ts.isoformat()}/{name}'

        out.append({
            'case_id': case_id,
            'source': 'eztools',
            'event_date': ts,
            'event_title': title,
            'event_description': '\n'.join(desc_lines),
            'event_source_host': None,
            'severity': sev,
            'event_tags': _tags_for('eztools', 'mft-usn',
                                    extras=[f'reason:{r}' for r in reasons.split(',') if r]),
            'mitre_techniques': '',
            'external_id': external_id,
            'event_raw': _row_event_raw(row, 'mft-usn'),
        })
    return out


def _usn_severity(reasons: str, path: str) -> str | None:
    """Light severity heuristic for $J entries."""
    r = (reasons or '').lower()
    p = (path or '').lower()
    if 'filedelete' in r or 'rename' in r:
        if any(s in p for s in ('\\temp\\', '\\appdata\\', '\\downloads\\',
                                 '$recycle.bin', '\\public\\')):
            return 'low'
        return 'info'
    return 'info'


def _parse_mft_full(rows: Iterable[dict[str, str]], case_id: int) -> list[dict[str, Any]]:
    """MFTECmd $MFT output: file system records keyed by Created0x10.

    Limits to records with a parseable Created0x10 — the goal is a
    timeline of *creates*, not every MFT record (which would explode
    way past MAX_ROWS_PER_IMPORT).
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        ts = _parse_ez_ts(row.get('Created0x10'))
        if ts is None:
            continue
        if _clean(row.get('IsDirectory')).lower() == 'true':
            continue  # directories are noise; keep to file creates
        name = _clean(row.get('FileName'))
        parent_path = _clean(row.get('ParentPath'))
        full_path = f'{parent_path}\\{name}' if parent_path else name
        size = _clean(row.get('FileSize'))
        in_use = _clean(row.get('InUse'))

        title = f'MFT create: {name or "<unknown>"}'
        desc_lines = []
        if full_path:
            desc_lines.append(f'**Path:** `{full_path}`')
        if size:
            desc_lines.append(f'**Size:** {size}')
        if in_use:
            desc_lines.append(f'**InUse:** {in_use}')
        for f in ('SI<FN', 'uSecZeros', 'Copied', 'ZoneIdContents'):
            val = _clean(row.get(f))
            if val:
                desc_lines.append(f'**{f}:** `{val}`')

        external_id = f'MFT/{_clean(row.get("EntryNumber"))}/{_clean(row.get("SequenceNumber"))}'
        out.append({
            'case_id': case_id,
            'source': 'eztools',
            'event_date': ts,
            'event_title': title,
            'event_description': '\n'.join(desc_lines),
            'event_source_host': None,
            'severity': None,
            'event_tags': _tags_for('eztools', 'mft'),
            'mitre_techniques': '',
            'external_id': external_id,
            'event_raw': _row_event_raw(row, 'mft'),
        })
    return out


def _parse_pecmd_timeline(rows: Iterable[dict[str, str]], case_id: int) -> list[dict[str, Any]]:
    """PECmd timeline output: one row per (prefetch, run) — file last-N runs."""
    out: list[dict[str, Any]] = []
    for row in rows:
        ts = _parse_ez_ts(row.get('RunTime'))
        if ts is None:
            continue
        exe = _clean(row.get('ExecutableName'))
        exe_short = _basename(exe) or '<unknown>'
        title = f'{exe_short} ran'
        # Keep the full path on its own line so wrap is friendly even on
        # tight panel widths.
        desc = f'**Executable:** `{exe_short}`\n\n**Full path:** `{exe}`' if exe else ''
        # Hayabusa-style dot separation. The card's own time field already
        # carries the timestamp, so the external_id doesn't need to repeat
        # it — (event_date, external_id) together stay unique per row.
        external_id = f'PrefetchRun · {exe_short}'
        out.append({
            'case_id': case_id,
            'source': 'eztools',
            'event_date': ts,
            'event_title': title,
            'event_description': desc,
            'event_source_host': None,
            'severity': None,
            'event_tags': _tags_for('eztools', 'prefetch-run'),
            'mitre_techniques': '',
            'external_id': external_id,
            'event_raw': _row_event_raw(row, 'prefetch-run'),
        })
    return out


def _parse_pecmd_full(rows: Iterable[dict[str, str]], case_id: int) -> list[dict[str, Any]]:
    """PECmd per-prefetch summary — one card per prefetch, keyed on LastRun.

    Each .pf file records up to 9 timestamps: ``LastRun`` (most recent) plus
    ``PreviousRun0`` … ``PreviousRun7`` (older). One working event per
    prefetch, with the historical runs listed in the description so the
    analyst can see the full execution history of the binary without
    flooding the timeline with one card per run. (Use the
    ``_Output_Timeline.csv`` variant if you want one card per run.)
    """
    out: list[dict[str, Any]] = []
    previous_slots = ('PreviousRun0', 'PreviousRun1', 'PreviousRun2',
                      'PreviousRun3', 'PreviousRun4', 'PreviousRun5',
                      'PreviousRun6', 'PreviousRun7')
    for row in rows:
        ts = _parse_ez_ts(row.get('LastRun'))
        if ts is None:
            continue
        exe = _clean(row.get('ExecutableName'))
        exe_short = _basename(exe) or '<unknown>'
        run_count = _clean(row.get('RunCount'))

        desc_lines = [f'**Executable:** `{exe_short}`']
        if exe and exe != exe_short:
            desc_lines.append(f'**Full path:** `{exe}`')
        if run_count:
            desc_lines.append(f'**RunCount:** `{run_count}`')
        for f in ('SourceFilename', 'SourceCreated', 'SourceModified',
                  'Hash', 'Version', 'FileSize'):
            val = _clean(row.get(f))
            if val:
                desc_lines.append(f'**{f}:** `{val}`')

        # Always show LastRun explicitly so the headline timestamp is
        # discoverable inside the body too (matches the card-top time).
        desc_lines.append(f'**LastRun:** `{_clean(row.get("LastRun"))}`')

        # Collect the previous-run timestamps that actually exist on this
        # row. Render newest-to-oldest so the body reads "most recent
        # historical run first" alongside the LastRun headline.
        previous_runs: list[str] = []
        for slot in previous_slots:
            val = _clean(row.get(slot))
            if val and _parse_ez_ts(val) is not None:
                previous_runs.append(f'- `{val}`  *(from {slot})*')
        if previous_runs:
            desc_lines.append('')
            desc_lines.append(f'**Previous runs ({len(previous_runs)}):**')
            desc_lines.extend(previous_runs)

        out.append({
            'case_id': case_id,
            'source': 'eztools',
            'event_date': ts,
            'event_title': f'{exe_short} ran',
            'event_description': '\n'.join(desc_lines),
            'event_source_host': None,
            'severity': None,
            'event_tags': _tags_for('eztools', 'prefetch'),
            'mitre_techniques': '',
            'external_id': f'Prefetch · {exe_short}',
            'event_raw': _row_event_raw(row, 'prefetch'),
        })
    return out


def _parse_appcompat(rows: Iterable[dict[str, str]], case_id: int) -> list[dict[str, Any]]:
    """AppCompatCache (Shimcache) — LastModifiedTimeUTC reflects the file's
    MFT modification time, NOT a last-execution time. Entries indicate the
    file was *present* on the system (queried by the kernel for shim lookup
    on enumeration), not that it executed. The `Executed` column emitted by
    AppCompatCacheParser is unreliable on modern Windows (Win10+) and is
    intentionally NOT surfaced as a triage signal here — the analyst should
    confirm execution via Prefetch / Amcache / EventLogs (4688) / AppCompat
    process telemetry, not Shimcache alone.
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        ts = _parse_ez_ts(row.get('LastModifiedTimeUTC'))
        if ts is None:
            continue
        path = _clean(row.get('Path'))
        path_short = _basename(path) or '<unknown>'
        duplicate = _clean(row.get('Duplicate'))
        position = _clean(row.get('CacheEntryPosition'))
        title = f'{path_short} present on disk'
        desc_lines = [
            f'**Image:** `{path_short}`',
        ]
        if path and path != path_short:
            desc_lines.append(f'**Full path:** `{path}`')
        if position:
            desc_lines.append(f'**Cache entry position:** `{position}` (lower = more recent)')
        desc_lines.append('')
        desc_lines.append(
            '_AppCompatCache (Shimcache) indicates the file **existed** '
            'on the system, not that it executed. The timestamp shown is '
            'the file\'s **MFT $STANDARD_INFORMATION ModifiedTimeUTC**, '
            'not a last-run time. Confirm execution via Prefetch / Security 4688 / Sysmon 1._'
        )
        desc_lines.append('')
        if duplicate:
            desc_lines.append(f'**Duplicate:** `{duplicate}`')
        source_file = _clean(row.get('SourceFile'))
        if source_file:
            desc_lines.append(f'**SourceFile:** `{source_file}`')
        # No severity inference from AppCompatCache — presence alone is
        # not a triage signal, and `Executed=Yes` is unreliable on
        # Win10+. Let the analyst (or the AI Explain pill) decide.
        sev = None
        external_id = f'AppCompatCache · {path_short}'
        out.append({
            'case_id': case_id,
            'source': 'eztools',
            'event_date': ts,
            'event_title': title,
            'event_description': '\n'.join(desc_lines),
            'event_source_host': None,
            'severity': sev,
            'event_tags': _tags_for('eztools', 'appcompat'),
            'mitre_techniques': '',
            'external_id': external_id,
            'event_raw': _row_event_raw(row, 'appcompat'),
        })
    return out


def _parse_amcache_unassociated(rows: Iterable[dict[str, str]], case_id: int) -> list[dict[str, Any]]:
    """Amcache UnassociatedFileEntries — keyed by FileKeyLastWriteTimestamp."""
    out: list[dict[str, Any]] = []
    for row in rows:
        ts = _parse_ez_ts(row.get('FileKeyLastWriteTimestamp'))
        if ts is None:
            continue
        name = _clean(row.get('Name')) or _basename(row.get('FullPath'))
        full_path = _clean(row.get('FullPath'))
        sha1 = _clean(row.get('SHA1'))
        size = _clean(row.get('Size'))
        title = f'Amcache: {name or "<unknown>"} (unassociated)'
        desc_lines = []
        if full_path:
            desc_lines.append(f'**Full path:** `{full_path}`')
        if sha1:
            desc_lines.append(f'**SHA1:** `{sha1}`')
        if size:
            desc_lines.append(f'**Size:** {size}')
        for f in ('ProductName', 'Version', 'ProductVersion', 'IsPeFile',
                  'BinaryType', 'LinkDate'):
            val = _clean(row.get(f))
            if val:
                desc_lines.append(f'**{f}:** `{val}`')
        external_id = f'AmcacheUnassoc/{sha1 or full_path}'
        out.append({
            'case_id': case_id,
            'source': 'eztools',
            'event_date': ts,
            'event_title': title,
            'event_description': '\n'.join(desc_lines),
            'event_source_host': None,
            'severity': None,
            'event_tags': _tags_for('eztools', 'amcache-unassoc'),
            'mitre_techniques': '',
            'external_id': external_id,
            'event_raw': _row_event_raw(row, 'amcache-unassoc'),
        })
    return out


def _parse_amcache_program(rows: Iterable[dict[str, str]], case_id: int) -> list[dict[str, Any]]:
    """Amcache ProgramEntries — keyed by InstallDate (fallback KeyLastWriteTimestamp)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        ts = (_parse_ez_ts(row.get('InstallDate'))
              or _parse_ez_ts(row.get('KeyLastWriteTimestamp')))
        if ts is None:
            continue
        name = _clean(row.get('Name'))
        version = _clean(row.get('Version'))
        publisher = _clean(row.get('Publisher'))
        title = f'Amcache program: {name or "<unknown>"}'
        if version:
            title += f' v{version}'
        desc_lines = []
        if publisher:
            desc_lines.append(f'**Publisher:** `{publisher}`')
        for f in ('ProgramId', 'OSVersionAtInstallTime', 'InstallDate',
                  'InstallDateArpLastModified', 'Source', 'Type', 'RegistryKeyPath',
                  'RootDirPath', 'UninstallString'):
            val = _clean(row.get(f))
            if val:
                desc_lines.append(f'**{f}:** `{val}`')
        external_id = f'AmcacheProg/{_clean(row.get("ProgramId")) or name}'
        out.append({
            'case_id': case_id,
            'source': 'eztools',
            'event_date': ts,
            'event_title': title,
            'event_description': '\n'.join(desc_lines),
            'event_source_host': None,
            'severity': None,
            'event_tags': _tags_for('eztools', 'amcache-prog'),
            'mitre_techniques': '',
            'external_id': external_id,
            'event_raw': _row_event_raw(row, 'amcache-prog'),
        })
    return out


def _parse_rbcmd(rows: Iterable[dict[str, str]], case_id: int) -> list[dict[str, Any]]:
    """RBCmd output — Recycle Bin entries (file deletion timeline)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        ts = _parse_ez_ts(row.get('DeletedOn'))
        if ts is None:
            continue
        filename = _clean(row.get('FileName'))
        filename_short = _basename(filename) or '<unknown>'
        file_size = _clean(row.get('FileSize'))
        file_type = _clean(row.get('FileType'))
        source_name = _clean(row.get('SourceName'))
        title = f'Recycle bin: deleted {filename_short}'
        desc_lines = []
        if filename:
            desc_lines.append(f'**Original path:** `{filename}`')
        if file_size:
            desc_lines.append(f'**Size:** {file_size}')
        if file_type:
            desc_lines.append(f'**FileType:** `{file_type}`')
        if source_name:
            desc_lines.append(f'**$I/$R path:** `{source_name}`')
        external_id = f'RecycleBin/{source_name}'
        out.append({
            'case_id': case_id,
            'source': 'eztools',
            'event_date': ts,
            'event_title': title,
            'event_description': '\n'.join(desc_lines),
            'event_source_host': None,
            'severity': 'low',
            'event_tags': _tags_for('eztools', 'recycle-bin'),
            'mitre_techniques': '',
            'external_id': external_id,
            'event_raw': _row_event_raw(row, 'recycle-bin'),
        })
    return out


def _parse_lecmd(rows: Iterable[dict[str, str]], case_id: int) -> list[dict[str, Any]]:
    """LECmd output — parsed LNK files (file/folder access evidence)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        ts = (_parse_ez_ts(row.get('TargetAccessed'))
              or _parse_ez_ts(row.get('TargetModified'))
              or _parse_ez_ts(row.get('SourceAccessed'))
              or _parse_ez_ts(row.get('SourceModified')))
        if ts is None:
            continue
        local_path = _clean(row.get('LocalPath'))
        network_path = _clean(row.get('NetworkPath'))
        relative_path = _clean(row.get('RelativePath'))
        arguments = _clean(row.get('Arguments'))
        target = local_path or network_path or relative_path or '<unknown>'
        target_short = _basename(target) if target != '<unknown>' else '<unknown>'
        title = f'LNK: {target_short}'
        desc_lines = []
        if target and target != target_short:
            desc_lines.append(f'**Target:** `{target}`')
        if local_path:
            desc_lines.append(f'**LocalPath:** `{local_path}`')
        if network_path:
            desc_lines.append(f'**NetworkPath:** `{network_path}`')
        if relative_path:
            desc_lines.append(f'**RelativePath:** `{relative_path}`')
        if arguments:
            desc_lines.append(f'**Arguments:** `{arguments}`')
        for f in ('SourceCreated', 'SourceModified', 'SourceAccessed',
                  'TargetCreated', 'TargetModified', 'TargetAccessed',
                  'FileSize', 'VolumeSerialNumber', 'VolumeLabel',
                  'MachineID', 'MachineMACAddress', 'WorkingDirectory'):
            val = _clean(row.get(f))
            if val:
                desc_lines.append(f'**{f}:** `{val}`')
        source_file = _clean(row.get('SourceFile'))
        external_id = (
            f'LECmd/{_basename(source_file)}' if source_file else f'LECmd/{target_short}'
        )
        out.append({
            'case_id': case_id,
            'source': 'eztools',
            'event_date': ts,
            'event_title': title,
            'event_description': '\n'.join(desc_lines),
            'event_source_host': None,
            'severity': None,
            'event_tags': _tags_for('eztools', 'lnk'),
            'mitre_techniques': '',
            'external_id': external_id,
            'event_raw': _row_event_raw(row, 'lnk'),
        })
    return out


def _parse_jlecmd_dest(rows: Iterable[dict[str, str]], case_id: int) -> list[dict[str, Any]]:
    """JLECmd AutomaticDestinations / CustomDestinations — jump list entries."""
    out: list[dict[str, Any]] = []
    for row in rows:
        ts = (_parse_ez_ts(row.get('LastModified'))
              or _parse_ez_ts(row.get('CreationTime'))
              or _parse_ez_ts(row.get('TargetAccessed'))
              or _parse_ez_ts(row.get('TargetModified')))
        if ts is None:
            continue
        path = _clean(row.get('Path'))
        app_id = _clean(row.get('AppId'))
        app_desc = _clean(row.get('AppIdDescription'))
        target = path or _clean(row.get('LocalPath')) or '<unknown>'
        target_short = _basename(target) if target != '<unknown>' else '<unknown>'
        title = f'JumpList: {target_short}'
        if app_desc:
            title += f' ({app_desc})'
        desc_lines = []
        if path:
            desc_lines.append(f'**Full path:** `{path}`')
        if app_id:
            desc_lines.append(f'**AppId:** `{app_id}`')
        if app_desc:
            desc_lines.append(f'**AppIdDescription:** `{app_desc}`')
        for f in ('Hostname', 'MacAddress', 'CreationTime', 'LastModified',
                  'InteractionCount', 'PinStatus', 'TargetCreated',
                  'TargetModified', 'TargetAccessed', 'FileSize'):
            val = _clean(row.get(f))
            if val:
                desc_lines.append(f'**{f}:** `{val}`')
        external_id = f'JumpList/{app_id}/{_clean(row.get("EntryNumber"))}'
        out.append({
            'case_id': case_id,
            'source': 'eztools',
            'event_date': ts,
            'event_title': title,
            'event_description': '\n'.join(desc_lines),
            'event_source_host': _clean(row.get('Hostname')) or None,
            'severity': None,
            'event_tags': _tags_for('eztools', 'jumplist',
                                    extras=[f'app:{app_desc}'] if app_desc else None),
            'mitre_techniques': '',
            'external_id': external_id,
            'event_raw': _row_event_raw(row, 'jumplist'),
        })
    return out


def _tags_for(*sources: str, host: str | None = None,
              extras: Iterable[str | None] | None = None) -> str:
    """Comma-separated tag string. `eztools` is always first."""
    tags: list[str] = list(sources)
    if host:
        tags.append(f'host:{host}')
    if extras:
        for e in extras:
            if e:
                tags.append(e)
    # de-dupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t and t not in seen:
            out.append(t)
            seen.add(t)
    return ','.join(out)


# --------------------------------------------------------------------------
# Auto-detection: match by header column set
# --------------------------------------------------------------------------
#
# Each detector lists the *required* columns that must all be present for
# the CSV to be recognised as that sub-format. Detectors are evaluated in
# the order listed; the first match wins. Order matters for sub-formats
# with overlapping columns (e.g. PECmd_Timeline vs full PECmd output).

DETECTORS: list[tuple[str, set[str], Callable[[Iterable[dict[str, str]], int], list[dict[str, Any]]]]] = [
    ('evtxecmd',
     {'RecordNumber', 'EventRecordId', 'TimeCreated', 'EventId', 'Channel', 'Provider'},
     _parse_evtxecmd),
    ('mft-usn',
     {'UpdateSequenceNumber', 'UpdateTimestamp', 'UpdateReasons',
      'EntryNumber', 'ParentEntryNumber', 'Name'},
     _parse_mft_usn),
    ('mft-full',
     {'EntryNumber', 'SequenceNumber', 'ParentEntryNumber', 'ParentPath',
      'FileName', 'FileSize', 'IsDirectory', 'Created0x10'},
     _parse_mft_full),
    ('prefetch-timeline',
     {'RunTime', 'ExecutableName'},
     _parse_pecmd_timeline),
    ('prefetch-full',
     {'LastRun', 'ExecutableName', 'RunCount'},
     _parse_pecmd_full),
    ('appcompat',
     {'ControlSet', 'CacheEntryPosition', 'Path', 'LastModifiedTimeUTC', 'Executed'},
     _parse_appcompat),
    ('amcache-unassoc',
     {'ApplicationName', 'ProgramId', 'FileKeyLastWriteTimestamp', 'SHA1', 'FullPath'},
     _parse_amcache_unassociated),
    ('amcache-prog',
     {'ProgramId', 'KeyLastWriteTimestamp', 'Name', 'Version', 'Publisher', 'InstallDate'},
     _parse_amcache_program),
    ('recycle-bin',
     {'SourceName', 'FileType', 'FileName', 'FileSize', 'DeletedOn'},
     _parse_rbcmd),
    # jumplist must come BEFORE lnk — JumpList CSVs contain every column
    # LECmd has, plus AppId/AppIdDescription/EntryNumber/Hostname. If lnk
    # is evaluated first, JumpLists get mis-detected as plain LNK files.
    ('jumplist',
     {'AppId', 'AppIdDescription', 'EntryNumber', 'TargetCreated', 'TargetModified'},
     _parse_jlecmd_dest),
    ('lnk',
     {'SourceFile', 'TargetCreated', 'TargetModified', 'TargetAccessed',
      'LocalPath', 'RelativePath'},
     _parse_lecmd),
]


def _detect(fieldnames: list[str]) -> tuple[str, Callable[[Iterable[dict[str, str]], int], list[dict[str, Any]]]] | None:
    cols = set(fieldnames or [])
    for kind, required, parser in DETECTORS:
        if required.issubset(cols):
            return kind, parser
    return None


def parse_eztools_csv(csv_bytes: bytes | str, case_id: int) -> tuple[uuid.UUID, str, list[dict[str, Any]]]:
    """Parse an EZ Tools CSV → CaseWorkingEvent-shaped dicts.

    Returns:
        ``(import_batch_id, detected_kind, [event_dict, …])``. The kind
        is also stored in ``event_raw.eztools_kind`` for each row.

    Raises:
        EztoolsParseError: empty / malformed CSV, unrecognized header,
            or zero usable rows.
    """
    # Stream-decode so a huge CSV (e.g. 800+ MB EvtxECmd) doesn't materialise
    # as a single Python string. We still hold the upload bytes in RAM (Flask
    # already buffered them), but lazy text decoding + the 25k row cap keep
    # peak memory bounded.
    if isinstance(csv_bytes, bytes):
        text_stream = io.TextIOWrapper(
            io.BytesIO(csv_bytes), encoding='utf-8-sig', errors='replace'
        )
    else:
        text_stream = io.StringIO(csv_bytes)

    reader = csv.DictReader(text_stream)
    fieldnames = list(reader.fieldnames or [])
    if not fieldnames:
        raise EztoolsParseError("CSV appears empty or has no header row.")

    detected = _detect(fieldnames)
    if detected is None:
        raise EztoolsParseError(
            "CSV header doesn't match any supported EZ Tools format. "
            f"Got columns: {fieldnames[:12]}{'…' if len(fieldnames) > 12 else ''}. "
            "Supported: EvtxECmd, MFTECmd ($J/$MFT), PECmd, AppCompatCache, "
            "Amcache, RBCmd, LECmd, JLECmd."
        )

    kind, parser = detected

    # Stream rows up to the cap.
    rows: list[dict[str, str]] = []
    for i, row in enumerate(reader):
        if i >= MAX_ROWS_PER_IMPORT:
            break
        if not any(v and str(v).strip() for v in row.values()):
            continue
        rows.append(row)
    if not rows:
        raise EztoolsParseError(
            f"CSV recognized as {kind} but contains no data rows."
        )

    parsed = parser(rows, case_id)
    if not parsed:
        raise EztoolsParseError(
            f"CSV recognized as {kind} but no rows had a parseable timestamp. "
            "Check that the CSV is the latest EZ Tools format."
        )

    batch_id = uuid.uuid4()
    for ev in parsed:
        ev['import_batch_id'] = batch_id
        ev['status'] = 'pending'

    parsed.sort(key=lambda e: e['event_date'])
    return batch_id, kind, parsed

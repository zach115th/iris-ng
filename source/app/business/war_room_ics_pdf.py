#  IRIS Source Code
#  Copyright (C) 2026 - iris-ng
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3 of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.

"""Fill the official FEMA ICS PDF forms from a war room's ICS notes.

Maintainer decision (2026-09-17): the export IS the official form. FEMA
publishes the ICS forms as fillable PDFs (US government works, public
domain); a copy of each is bundled under resources/ics_forms/ and the
export fills its named fields from the markdown note — the note keeps
FEMA's block numbering, so each `## N. Heading` maps onto the block with
that number. Rendering a look-alike (DOCX or otherwise) was rejected: a
filled original is exact by definition.

What the reader of the PDF gets, and does not get:

* Field text is the note's text with the markdown taken off (headings,
  emphasis, links, code marks); lists keep their markers, tables become one
  line per row. The seeded `—` placeholders export as EMPTY fields, never
  as dashes. Template hint lines (a whole line in _italics_) are guidance
  for the analyst and are not exported.
* The AI pass marks every field it filled with an "AI draft" line. Those
  marker lines are NOT printed on the form, and their count is reported
  back (`unreviewed_ai_fields`) so the UI can say that the PDF carries
  machine-drafted text nobody has signed off — the reviewer is the human
  pass, and a form handed upward must not hide that it skipped one.
* A table with more rows than the form has lines fills what fits, in
  order, and reports the remainder (`overflow`) — a partial export must
  never look complete. The form's own remarks/continuation block takes the
  overflow where one exists (ICS 209 block 47).
* Sections the analyst added that no FEMA block accepts are reported
  (`unmapped`), not silently dropped.
* FEMA's instruction pages (the ones with no fields) are removed, so the
  download is the form alone. Signature fields are left for a signature.
* Field names are FEMA's own — inconsistent, sometimes duplicated across
  pages (`_2`, `Row4`…), so each form's map is written against the real
  names and the suite asserts every map entry resolves to at least one
  field in the bundled PDF. Two ICS 209 blocks (38, 39) share ONE field
  across five widgets in FEMA's file, so a value would print five times;
  they are routed into block 47 instead.
"""
from __future__ import annotations

import io
import os
import re
from typing import Callable

from pypdf import PdfReader
from pypdf import PdfWriter

FORM_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'resources', 'ics_forms')

AI_MARK = '_AI draft — review before relying on it._'
EMPTY = '—'
_HORIZONS = (('12 hours', '12hour'), ('24 hours', '24hour'), ('48 hours', '48hour'),
             ('72 hours', '72hour'), ('Beyond 72 hours', 'after 72hour'))


class IcsPdfError(Exception):
    """A form that cannot be exported (unknown form, missing PDF)."""


# ------------------------------------------------------------ note parsing

_HEADING_RE = re.compile(r'^## (\d+)\. (.+?)[ \t]*$', re.M)
_DT_RE = re.compile(r'(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})')


def _norm(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '').strip()).lower()


def parse_sections(content: str) -> dict[str, str]:
    """{normalised heading text: body} for every `## N. Heading` block. The
    number is deliberately NOT the key — a note seeded before a renumbering
    still exports by its heading names (aliases in each form's map)."""
    out: dict[str, str] = {}
    matches = list(_HEADING_RE.finditer(content or ''))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        out[_norm(m.group(2))] = content[start:end]
    return out


def _strip_inline(s: str) -> str:
    s = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', s)          # [text](url) -> text
    s = re.sub(r'(\*\*|__)(.*?)\1', r'\2', s)               # bold
    s = re.sub(r'(?<!\w)(\*|_)(?!\s)(.*?)(?<!\s)\1(?!\w)', r'\2', s)  # italic
    s = re.sub(r'`([^`]*)`', r'\1', s)                      # code
    s = s.replace('\\|', '|')
    return s.strip()


def _is_hint_line(line: str) -> bool:
    t = line.strip()
    return len(t) > 2 and t.startswith('_') and t.endswith('_') and not t.startswith('__')


def _table_rows(body: str) -> list[list[str]]:
    """Data rows of the first markdown table in `body` (header + separator
    skipped), cells unescaped; an all-empty/all-dash row is dropped."""
    rows: list[list[str]] = []
    in_table = False
    for line in (body or '').splitlines():
        t = line.strip()
        if not t.startswith('|'):
            if in_table:
                break
            continue
        if re.match(r'^\|(\s*:?-+:?\s*\|)+\s*$', t):
            in_table = True
            continue
        if not in_table:
            continue  # header row
        cells = [c.strip() for c in re.split(r'(?<!\\)\|', t.strip('|'))]
        cells = ['' if _strip_inline(c) == EMPTY else _strip_inline(c) for c in cells]
        if any(cells):
            rows.append(cells)
    return rows


def _split_marks(body: str) -> tuple[str, int]:
    """Remove the AI marker lines; return (body, count)."""
    n = 0
    kept = []
    for line in (body or '').splitlines():
        if line.strip() == AI_MARK:
            n += 1
            continue
        kept.append(line)
    return '\n'.join(kept), n


def md_to_text(body: str) -> str:
    """Section body -> plain text for a PDF text field."""
    body, _ = _split_marks(body)
    out: list[str] = []
    table: list[str] = []
    header: list[str] | None = None

    def _flush_table():
        nonlocal header
        out.extend(table)
        table.clear()
        header = None

    for line in body.splitlines():
        t = line.strip()
        if t.startswith('|'):
            if re.match(r'^\|(\s*:?-+:?\s*\|)+\s*$', t):
                continue
            cells = [_strip_inline(c) for c in re.split(r'(?<!\\)\|', t.strip('|'))]
            if header is None:
                header = cells
                continue
            cells = ['' if c == EMPTY else c for c in cells]
            # A row that carries only its label (every value cell still
            # empty) is an unfilled field, not text.
            if not any(cells) or (len(cells) > 1 and not any(cells[1:])):
                continue
            if len(cells) == 2 and len(header) == 2:
                table.append('%s: %s' % (cells[0], cells[1]) if cells[0] else cells[1])
            else:
                table.append(' | '.join(c for c in cells))
            continue
        if table or header is not None:
            _flush_table()
        if not t:
            if out and out[-1] != '':
                out.append('')
            continue
        if _is_hint_line(t):
            continue
        t = re.sub(r'^#+\s*', '', t)
        t = re.sub(r'^>\s?', '', t)
        # The FEMA fields draw with WinAnsi Helvetica: no box or arrow
        # glyphs, so list markers stay ASCII.
        m = re.match(r'^[-*] \[([ xX])\] (.*)$', t)
        if m:
            t = ('[x] ' if m.group(1).strip() else '[ ] ') + m.group(2)
        else:
            m = re.match(r'^[-*] (.*)$', t)
            if m:
                t = '- ' + m.group(1)
        t = _strip_inline(t)
        if t == EMPTY:
            continue
        # A "label: —" pair with nothing filled is an empty field, not text.
        t = re.sub(r':\s*—\s*(·|$)', r': \1', t).strip(' ·')
        if t:
            out.append(t)
    if table or header is not None:
        _flush_table()
    while out and out[-1] == '':
        out.pop()
    return '\n'.join(out)


def _bullets(body: str) -> list[str]:
    body, _ = _split_marks(body)
    items = []
    for line in body.splitlines():
        m = re.match(r'^\s*(?:[-*]|\d+\.)\s+(.*)$', line)
        if m:
            v = _strip_inline(m.group(1))
            if v and v != EMPTY:
                items.append(v)
    return items


def _checklist(body: str) -> list[tuple[bool, str]]:
    out = []
    for line in (body or '').splitlines():
        m = re.match(r'^\s*[-*] \[([ xX])\] (.*)$', line)
        if m:
            out.append((bool(m.group(1).strip()), _strip_inline(m.group(2))))
    return out


def _kv(body: str) -> dict[str, str]:
    """'Date/time from: X · Date/time to: Y' -> {'date/time from': 'X', ...}.
    Reads the first non-hint, non-blank line of the section."""
    body, _ = _split_marks(body)
    for line in body.splitlines():
        t = line.strip()
        if not t or _is_hint_line(t) or t.startswith('|'):
            continue
        out = {}
        for part in re.split(r'\s+·\s+', _strip_inline(t)):
            if ':' in part:
                k, v = part.split(':', 1)
                v = v.strip()
                out[_norm(k)] = '' if v == EMPTY else v
        return out
    return {}


def _positions(body: str) -> dict[str, list[str]]:
    """2+-column `| Position | Name | ... |` table -> {position: [cells]}."""
    out: dict[str, list[str]] = {}
    for row in _table_rows(body):
        if row and row[0]:
            out[_norm(row[0])] = row[1:]
    return out


def _first_dt(text: str) -> tuple[str, str]:
    m = _DT_RE.search(text or '')
    return (m.group(1), m.group(2)) if m else (('' if not text else text.strip()), '')


def _lead_text(body: str) -> str:
    """The section's text with the placeholders gone (for one-line blocks)."""
    return md_to_text(body).replace('\n', ' ').strip()


# ------------------------------------------------------------- the maps
#
# A map is a function (sections, ctx) -> None that writes into ctx:
#   ctx.text(name_or_regex, value)     one value into every matching field
#   ctx.rows(label, [(regex_with_row_group, [values...]), ...])
#                                     row series; reports the overflow
#   ctx.check(name_or_regex, bool)     a checkbox
# `sections.get(*aliases)` returns the first present section body.


class _Sections:
    def __init__(self, parsed: dict[str, str]):
        self._p = parsed
        self.used: set[str] = set()

    def get(self, *aliases: str) -> str | None:
        for a in aliases:
            k = _norm(a)
            if k in self._p:
                self.used.add(k)
                return self._p[k]
        return None

    def unused(self) -> list[str]:
        return [k for k in self._p if k not in self.used]


_PDF_CHARS = {'→': '->', '←': '<-', '✓': 'x', '✔': 'x', '☑': '[x]',
              '☐': '[ ]', '•': '-', '…': '...', '‘': "'", '’': "'",
              '“': '"', '”': '"', ' ': ' '}


def pdf_safe(value: str) -> str:
    """FEMA's fields draw with WinAnsi Helvetica. Symbols the note uses that
    the encoding lacks are transliterated; anything else outside cp1252 is
    replaced with '?' rather than silently dropped."""
    s = ''.join(_PDF_CHARS.get(ch, ch) for ch in (value or ''))
    return s.encode('cp1252', errors='replace').decode('cp1252')


class _Ctx:
    def __init__(self):
        self.texts: list[tuple[str | re.Pattern, str]] = []
        self.checks: list[tuple[str | re.Pattern, bool]] = []
        self.series: list[tuple[str, re.Pattern, list[str]]] = []
        self.overflow: dict[str, int] = {}
        self.unreviewed = 0

    def text(self, name, value):
        if value is None:
            return
        v = pdf_safe(str(value)).strip()
        if v and v != EMPTY:
            self.texts.append((name, v))

    def check(self, name, on: bool):
        self.checks.append((name, bool(on)))

    def rows(self, label: str, columns: list[tuple[str, list[str]]]):
        for pattern, values in columns:
            self.series.append((label, re.compile(pattern),
                                [pdf_safe(v) for v in values]))

    def count_marks(self, *bodies: str | None):
        for b in bodies:
            if b:
                self.unreviewed += _split_marks(b)[1]


def _prepared_by(ctx: _Ctx, body: str | None):
    """'Name · YYYY-MM-DD HH:MM UTC' (any form) -> the Prepared-by family."""
    if body is None:
        return
    line = _lead_text(body)
    if not line:
        return
    parts = [p.strip() for p in re.split(r'\s+·\s+', line)]
    name = parts[0] if parts else ''
    position = ''
    when = ''
    for p in parts[1:]:
        if p.lower().startswith('position:'):
            position = p.split(':', 1)[1].strip()
        elif _DT_RE.search(p):
            when = p
    if not when:
        m = _DT_RE.search(line)
        when = ('%s %s UTC' % m.groups()) if m else ''
    ctx.text(re.compile(r'^\d+ Prepared by Name(_\d+)?$'), name)
    ctx.text(re.compile(r'^PositionTitle(_\d+)?$'), position)
    ctx.text(re.compile(r'^DateTime(_\d+)?$'), when)


def _op_period(ctx: _Ctx, body: str | None):
    kv = _kv(body or '')
    d1, t1 = _first_dt(kv.get('date/time from', ''))
    d2, t2 = _first_dt(kv.get('date/time to', ''))
    ctx.text('Date From', d1)
    ctx.text('Time From', t1)
    ctx.text('Date To', d2)
    ctx.text('Time To', t2)


def _map_201(s: _Sections, ctx: _Ctx):
    ctx.text('Incident Name', _lead_text(s.get('Incident Name') or ''))
    ctx.text('Incident Number', _lead_text(s.get('Incident Number') or ''))
    d, t = _first_dt(_lead_text(s.get('Date/Time Initiated') or ''))
    ctx.text('Date', d)
    ctx.text('Time', (t + ' UTC') if t else '')
    b4 = s.get('Map/Sketch — Affected Environment / Scope', 'Affected Environment / Scope')
    ctx.text(re.compile(r'^4 MapSketch'), md_to_text(b4 or ''))
    b5 = s.get('Situation Summary and Health & Safety Briefing')
    if b5 is not None:
        body, _ = _split_marks(b5)
        hs = ''
        m = re.search(r'^_Health & safety \((.*?)\):_?\s*(.*?)_?[ \t]*$', body, re.M)
        if m and _strip_inline(m.group(2)) not in ('', EMPTY):
            hs = 'Health & safety: ' + _strip_inline(m.group(2))
            body = body[:m.start()] + body[m.end():]
        text = md_to_text(body)
        ctx.text(re.compile(r'^5 Situation Summary'), (text + ('\n\n' + hs if hs else '')).strip())
    _prepared_by(ctx, s.get('Prepared By'))
    ctx.text('7 Current and Planned Objectives',
             '\n'.join(_bullets(s.get('Current and Planned Objectives') or '')))
    rows = _table_rows(s.get('Current and Planned Actions, Strategies and Tactics') or '')
    ctx.rows('8 actions', [(r'^TimeRow(\d+)$', [r[0] for r in rows]),
                           (r'^ActionsRow(\d+)$', [r[1] if len(r) > 1 else '' for r in rows])])
    b9 = s.get('Current Organization') or ''
    pos = _positions(b9)

    def _p(key):
        v = pos.get(_norm(key))
        return v[0] if v else ''
    ctx.text('Incident Commanders', _p('Incident Commander'))
    ctx.text('Safety Officer', _p('Safety Officer'))
    ctx.text('Public Information Officer', _p('Public Information Officer'))
    ctx.text('Liaison Officer', _p('Liaison Officer'))
    ctx.text('Operations Section Chief_2', _p('Operations Section Chief'))
    ctx.text('Planning Section Chief_2', _p('Planning Section Chief'))
    ctx.text('Logistics Section Chief', _p('Logistics Section Chief'))
    ctx.text('FinanceAdministration Section Chief', _p('Finance/Admin Section Chief'))
    # The members table (second table of §9) goes into the free-text
    # organisation block below the chart.
    tables = re.split(r'\n\s*\n', b9)
    members = [t for t in tables if 'Member' in t and '| Login |' in t]
    if members:
        ctx.text(re.compile(r'^9 Current Organization'), md_to_text(members[0]))
    rows = _table_rows(s.get('Resource Summary') or '')
    pad = lambda r, i: r[i] if len(r) > i else ''  # noqa: E731
    ctx.rows('10 resources', [
        (r'^ResourceRow(\d+)$', [pad(r, 0) for r in rows]),
        (r'^Resource IdentifierRow(\d+)$', [pad(r, 1) for r in rows]),
        (r'^DateTime OrderedRow(\d+)$', [pad(r, 2) for r in rows]),
        (r'^ETARow(\d+)$', [pad(r, 3) for r in rows]),
        (r'^Notes locationassignmentstatus(?:_(\d+)|Row(\d+))?$', [pad(r, 5) for r in rows]),
    ])
    for i, r in enumerate(rows):
        if re.match(r'^(yes|y|x|✓|✔|arrived)$', pad(r, 4).strip().lower()):
            ctx.check('Check Box%d' % (i + 1), True)
    ctx.count_marks(b4, b5, s.get('Current and Planned Objectives'),
                    s.get('Current and Planned Actions, Strategies and Tactics'),
                    s.get('Resource Summary'))


def _map_202(s: _Sections, ctx: _Ctx):
    ctx.text(re.compile(r'^1 Incident Name(_\d+)?$'), _lead_text(s.get('Incident Name') or ''))
    _op_period(ctx, s.get('Operational Period'))
    ctx.text('3 Objectives', '\n'.join(_bullets(s.get('Objective(s)') or '')))
    b4 = s.get('Operational Period Command Emphasis') or ''
    body4, _ = _split_marks(b4)
    parts = re.split(r'^\*\*General situational awareness\*\*.*$', body4, maxsplit=1, flags=re.M)
    ctx.text('4 Operational Period Command Emphasis', md_to_text(parts[0]))
    if len(parts) > 1:
        ctx.text('General Situational Awareness', md_to_text(parts[1]))
    b5 = _lead_text(s.get('Site Safety Plan Required?') or '')
    m = re.match(r'^(Yes|No)\b', b5, re.I)
    if m:
        ctx.check('Yes', m.group(1).lower() == 'yes')
        ctx.check('No', m.group(1).lower() == 'no')
    m = re.search(r'located at:\s*(.*)$', b5, re.I)
    if m:
        ctx.text(re.compile(r'^5 Site Safety Plan Required'), m.group(1).strip(' ·'))
    others = []
    for on, label in _checklist(s.get('Incident Action Plan') or ''):
        key = label.split('—')[0].strip()
        m = re.match(r'^(ICS \d{3}A?)\b', key)
        if m:
            ctx.check(m.group(1), on)
        elif key.lower().startswith('map/chart'):
            ctx.check('Map/Chart', on)
        elif key.lower().startswith('weather'):
            ctx.check('Weather Forecast/Tides/Current', on)
        elif key.lower().startswith('other attachments'):
            rest = label.split(':', 1)[1] if ':' in label else ''
            for item in [x.strip() for x in rest.split(';') if x.strip() and x.strip() != EMPTY]:
                others.append((on, item))
    for i, (on, item) in enumerate(others[:4]):
        ctx.check('Check %d' % (i + 1), on)
        ctx.text('Other Attachments %d' % (i + 1), item)
    if len(others) > 4:
        ctx.overflow['6 other attachments'] = len(others) - 4
    _prepared_by(ctx, s.get('Prepared By'))
    b8 = _lead_text(s.get('Approved By Incident Commander') or '')
    m = re.match(r'^Name:\s*(.*?)(?:\s+·\s+Signature.*)?$', b8)
    ctx.text('8 Approved by Incident Commander Name', m.group(1).strip() if m else b8)
    ctx.count_marks(s.get('Objective(s)'), b4, s.get('Site Safety Plan Required?'))


def _map_203(s: _Sections, ctx: _Ctx):
    ctx.text('1 Incident Name', _lead_text(s.get('Incident Name') or ''))
    _op_period(ctx, s.get('Operational Period'))
    pos = _positions(s.get('Incident Commander(s) and Command Staff') or '')

    def _p(d, key):
        v = d.get(_norm(key))
        return v[0] if v else ''
    ics = [x.strip() for x in _p(pos, 'Incident Commander / Unified Command').split(',') if x.strip()]
    ctx.text('ICUCs', ics[0] if ics else '')
    for i, n in enumerate(ics[1:3]):
        ctx.text('3 Incident Commanders and Command StaffRow%d' % (i + 2), n)
        ctx.text('ICUCsRow%d' % (i + 1), 'Incident Commander / Unified Command')
    if len(ics) > 3:
        ctx.overflow['3 incident commanders'] = len(ics) - 3
    ctx.text('Deputy_2', _p(pos, 'Deputy'))
    ctx.text('Safety Officer_3', _p(pos, 'Safety Officer'))
    ctx.text('Public Info Officer', _p(pos, 'Public Information Officer'))
    ctx.text('Liaison Officer_2', _p(pos, 'Liaison Officer'))
    rows = _table_rows(s.get('Agency / Organization Representatives') or '')
    ctx.rows('4 agency representatives', [
        (r'^AgencyOrganizationRow(\d+)$', [r[0] for r in rows]),
        (r'^NameRow(\d+)$', [r[1] if len(r) > 1 else '' for r in rows])])
    pl = _positions(s.get('Planning Section') or '')
    for key, field in (('Chief', 'Planning Section Chief'), ('Deputy', 'Planning Section Deputy'),
                       ('Resources Unit', 'Planning Section Resources Unit'),
                       ('Situation Unit', 'Planning Section Situation Unit'),
                       ('Documentation Unit', 'Planning Section Documentation Unit'),
                       ('Demobilization Unit', 'Planning Section Demobilization Unit')):
        ctx.text(field, _p(pl, key))
    specs = [x.strip() for x in _p(pl, 'Technical Specialists').split(',') if x.strip()]
    ctx.text('Planning Section Technical Specialists', specs[0] if specs else '')
    for i, n in enumerate(specs[1:4]):
        ctx.text('Technical SpecialistsRow%d' % (i + 1), 'Technical Specialist')
        ctx.text('5 Planning SectionRow%d' % (i + 8), n)
    if len(specs) > 4:
        ctx.overflow['5 technical specialists'] = len(specs) - 4
    lg = _positions(s.get('Logistics Section') or '')
    for key, field in (('Chief', 'Logistics Section Chief'), ('Deputy', 'Logistics Section Deputy'),
                       ('Support Branch Director', 'Support Branch Director'),
                       ('Supply Unit', 'Support Branch Supply Unit'),
                       ('Facilities Unit', 'Support Branch Facilities Unit'),
                       ('Ground Support Unit', 'Support Branch Ground Support Unit'),
                       ('Service Branch Director', 'Service Branch Director'),
                       ('Communications Unit', 'Service Branch Communications Unit'),
                       ('Medical Unit', 'Service Branch Medical Unit'),
                       ('Food Unit', 'Service Branch Food Unit')):
        ctx.text(field, _p(lg, key))
    b7 = s.get('Operations Section') or ''
    op = _positions(b7)
    ctx.text('Operations Section Chief 1', _p(op, 'Chief'))
    ctx.text('Operations Section Deputy 1', _p(op, 'Deputy'))
    ctx.text('Operations Section Staging Area 1', _p(op, 'Staging Area'))
    tables = re.split(r'\n\s*\n', b7)
    branch_rows = []
    for t in tables:
        if 'Branch / Division / Group' in t:
            branch_rows = _table_rows(t)
    ctx.rows('7 operations branches/divisions', [
        (r'^Division/?Group\s+Identifier (\d+)$', [r[0] for r in branch_rows]),
        (r'^DivisionGroup Name (\d+)$', [r[1] if len(r) > 1 else '' for r in branch_rows])])
    fa = _positions(s.get('Finance / Administration Section') or '')
    for key, field in (('Chief', 'Finance/Adminsitration Section Chief'),
                       ('Deputy', 'Finance/Adminsitration Section Deputy'),
                       ('Time Unit', 'Finance/Adminsitration Section Time Unit'),
                       ('Procurement Unit', 'Finance/Adminsitration Section Procurement Unit'),
                       ('Compensation/Claims Unit', 'Finance/Adminsitration Section CompClaims Unit'),
                       ('Cost Unit', 'Finance/Adminsitration Section Cost Unit')):
        ctx.text(field, _p(fa, key))
    _prepared_by(ctx, s.get('Prepared By'))
    ctx.count_marks(s.get('Incident Commander(s) and Command Staff'), s.get('Planning Section'),
                    b7, s.get('Prepared By'))


def _map_204(s: _Sections, ctx: _Ctx):
    ctx.text(re.compile(r'^1 Incident Name(_\d+)?$'), _lead_text(s.get('Incident Name') or ''))
    _op_period(ctx, s.get('Operational Period'))
    kv = _kv(s.get('Branch / Division / Group / Staging Area') or '')
    ctx.text('3 Branch', kv.get('branch', ''))
    ctx.text('3 Division', kv.get('division', ''))
    ctx.text('3 Group', kv.get('group', ''))
    ctx.text('3 Staging Area', kv.get('staging area', ''))
    pos = _positions(s.get('Operations Personnel') or '')

    def _nc(key):
        v = pos.get(_norm(key)) or []
        name = v[0] if v else ''
        contact = v[1] if len(v) > 1 else ''
        return ('%s — %s' % (name, contact)) if name and contact else name
    ctx.text('Operations Section Chief_3', _nc('Operations Section Chief'))
    ctx.text('Branch Director_4', _nc('Branch Director'))
    ctx.text('DivisionGroup Supervisor', _nc('Division/Group Supervisor'))
    rows = _table_rows(s.get('Resources Assigned') or '')
    pad = lambda r, i: r[i] if len(r) > i else ''  # noqa: E731
    ctx.rows('5 resources', [
        (r'^Resource IdentifierRow(\d+)_2$', [pad(r, 0) for r in rows]),
        (r'^LeaderRow(\d+)$', [pad(r, 1) for r in rows]),
        (r'^Number of Persons, Row (\d+)$', [pad(r, 2) for r in rows]),
        (r'^Contact eg phone pager radio frequency etc(?:_(\d+)|Row(\d+))?$', [pad(r, 3) for r in rows]),
        (r'^Reporting Location .*Information(?:_(\d+)|Row(\d+))?$', [pad(r, 4) for r in rows]),
    ])
    ctx.text('6 Work Assignments', md_to_text(s.get('Work Assignments') or ''))
    ctx.text('7 Special Instructions', md_to_text(s.get('Special Instructions') or ''))
    rows = _table_rows(s.get('Communications') or '')
    ctx.rows('8 communications', [
        (r'^Name/Function(\d+)$', [pad(r, 0) for r in rows]),
        (r'^Primary Contact .* (\d+)$', [pad(r, 1) for r in rows])])
    _prepared_by(ctx, s.get('Prepared By'))
    ctx.count_marks(s.get('Work Assignments'), s.get('Special Instructions'))


def _map_205a(s: _Sections, ctx: _Ctx):
    ctx.text(re.compile(r'^1 Incident Name(_\d+)?$'), _lead_text(s.get('Incident Name') or ''))
    _op_period(ctx, s.get('Operational Period'))
    rows = _table_rows(s.get('Basic Local Communications Information') or '')
    pad = lambda r, i: r[i] if len(r) > i else ''  # noqa: E731
    ctx.rows('3 contacts', [
        (r'^Incident Assigned PositionRow(\d+)$', [pad(r, 0) for r in rows]),
        (r'^Name AlphabetizedRow(\d+)$', [pad(r, 1) for r in rows]),
        (r'^Methods of Contact phone pager cell etcRow(\d+)$', [pad(r, 2) for r in rows])])
    _prepared_by(ctx, s.get('Prepared By'))


def _map_209(s: _Sections, ctx: _Ctx):
    ctx.text('Incident Name', _lead_text(s.get('Incident Name') or ''))
    ctx.text('Incident Number', _lead_text(s.get('Incident Number') or ''))
    b3 = s.get('Report Version') or ''
    for on, label in _checklist(b3):
        key = label.strip().lower()
        if key == 'initial':
            ctx.check('Check Box Report Version - Initial', on)
        elif key == 'update':
            ctx.check('Check Box Report Version -Update', on)
        elif key == 'final':
            ctx.check('Check Box Report Version - Final', on)
    m = re.search(r'Report number \(if used\):\s*(.*)$', b3, re.M | re.I)
    if m:
        ctx.text('Report Number (if used)', _strip_inline(m.group(1)) if _strip_inline(m.group(1)) != EMPTY else '')
    ctx.text('4 Incident Commanders  Agency or Organization',
             md_to_text(s.get('Incident Commander(s) and Agency or Organization') or ''))
    ctx.text('5 Incident Management Organization', md_to_text(s.get('Incident Management Organization') or ''))
    d, t = _first_dt(_lead_text(s.get('Incident Start Date/Time') or ''))
    ctx.text('Date', d)
    ctx.text('Time', t)
    ctx.text('Time Zone', 'UTC' if d else '')
    ctx.text(re.compile(r'^7 Current Incident Size'), _lead_text(s.get('Current Incident Size or Area Involved') or ''))
    kv = _kv(s.get('Percent Contained / Completed') or '')
    ctx.text('Percent Contained', kv.get('contained', '').replace('%', '').strip())
    ctx.text('Percent Completed', kv.get('completed', '').replace('%', '').strip())
    ctx.text('9 Incident Definition', md_to_text(s.get('Incident Definition') or ''))
    ctx.text('10 Incident Complexity Level', md_to_text(s.get('Incident Complexity Level') or ''))
    kv = _kv(s.get('For Time Period') or '')
    ctx.text('From DateTime', kv.get('date/time from', ''))
    ctx.text('To DateTime', kv.get('date/time to', ''))
    parts = [p.strip() for p in re.split(r'\s+·\s+', _lead_text(s.get('Prepared By') or ''))]
    if parts and parts[0]:
        ctx.text('Print Name', parts[0])
        for p in parts[1:]:
            if p.lower().startswith('position:'):
                ctx.text('ICS Position', p.split(':', 1)[1].strip())
            elif _DT_RE.search(p):
                ctx.text('DateTime Prepared_2', p)
    ctx.text('13 DateTime Submitted Time Zone', _lead_text(s.get('Date/Time Submitted') or ''))
    parts = [p.strip() for p in re.split(r'\s+·\s+', _lead_text(s.get('Approved By') or ''))]
    if parts and parts[0]:
        ctx.text('Print Name_2', parts[0])
        for p in parts[1:]:
            if p.lower().startswith('position:'):
                ctx.text('ICS Position_2', p.split(':', 1)[1].strip())
    ctx.text('15 Primary Location Organization or Agency Sent To',
             _lead_text(s.get('Primary Location, Organization, or Agency Sent To') or ''))
    ctx.text('16 State', _lead_text(s.get('State') or ''))
    ctx.text('17 CountyParishBorough', _lead_text(s.get('County / Parish / Borough') or ''))
    ctx.text('18 City', _lead_text(s.get('City') or ''))
    ctx.text('20 Incident Jurisdiction', md_to_text(s.get('Incident Jurisdiction') or ''))
    ctx.text(re.compile(r'^25 Short Location'), md_to_text(s.get('Short Location or Area Description') or ''))
    ctx.text(re.compile(r'^28 Significant Events'), md_to_text(s.get('Significant Events for the Time Period Reported') or ''))
    ctx.text(re.compile(r'^29 Primary Materials'), md_to_text(s.get('Primary Materials or Hazards Involved') or ''))
    ctx.text(re.compile(r'^33 Life Safety'), md_to_text(s.get('Life Safety and Health Status / Threat Remarks') or ''))
    b36 = s.get('Projected Incident Activity, Potential, Movement, Escalation, or Spread') or ''
    proj = {_norm(r[0]): (r[1] if len(r) > 1 else '') for r in _table_rows(b36)}
    for label, key in _HORIZONS:
        ctx.text(re.compile(r'^Projected Incident Activity.*' + re.escape(key)), proj.get(_norm(label), ''))
    ctx.text(re.compile(r'^37 Strategic Objectives'), '\n'.join(_bullets(s.get('Strategic Objectives') or '')))
    # Blocks 38 and 39 share one field across five widgets in FEMA's PDF
    # (a value would print five times) — carried in block 47 instead.
    extra = []
    b38 = s.get('Current Incident Threat Summary and Risk Information') or ''
    t38 = md_to_text(b38)
    if t38:
        extra.append('38. Current Incident Threat Summary and Risk Information:\n' + t38)
    b39 = s.get('Critical Resource Needs') or ''
    t39 = '\n'.join('• ' + x for x in _bullets(b39))
    if t39:
        extra.append('39. Critical Resource Needs:\n' + t39)
    ctx.text(re.compile(r'^40 Strategic Discussion'), md_to_text(s.get('Strategic Discussion') or ''))
    ctx.text('41 Planned Actions for Next Operational Period',
             '\n'.join('• ' + x for x in _bullets(s.get('Planned Actions for Next Operational Period') or '')))
    ctx.text('43 Anticipated Incident Management Completion Date',
             _lead_text(s.get('Anticipated Incident Management Completion Date') or ''))
    remarks = md_to_text(s.get('Remarks') or '')
    ctx.text(re.compile(r'^47 Remarks'), '\n\n'.join([x for x in [remarks] + extra if x]))
    rows = _table_rows(s.get('Agency or Organization') or '')
    ctx.rows('48 agencies', [
        (r'^(?:48 )?Agency or OrganizationRow(\d+)$', [r[0] for r in rows]),
        (r'^51 Total Personnel .*overhead(?:_(\d+)|Row(\d+))?$', [r[1] if len(r) > 1 else '' for r in rows])])
    ctx.text(re.compile(r'^53 Additional Cooperating'),
             md_to_text(s.get('Additional Cooperating and Assisting Organizations Not Listed Above') or ''))
    ctx.count_marks(s.get('Significant Events for the Time Period Reported'), b36,
                    s.get('Strategic Objectives'), b38, b39, s.get('Strategic Discussion'),
                    s.get('Planned Actions for Next Operational Period'), s.get('Incident Definition'))


def _map_214(s: _Sections, ctx: _Ctx):
    ctx.text(re.compile(r'^1 Incident Name(_\d+)?$'), _lead_text(s.get('Incident Name') or ''))
    _op_period(ctx, s.get('Operational Period'))
    ctx.text('3 Name', _lead_text(s.get('Name') or ''))
    ctx.text('4 ICS Position', _lead_text(s.get('ICS Position') or ''))
    ctx.text('5 Home Agency and Unit', _lead_text(s.get('Home Agency (and Unit)') or ''))
    rows = _table_rows(s.get('Resources Assigned') or '')
    pad = lambda r, i: r[i] if len(r) > i else ''  # noqa: E731
    ctx.rows('6 resources', [
        (r'^NameRow(\d+)(?:_3)?$', [pad(r, 0) for r in rows]),
        (r'^ICS PositionRow(\d+)$', [pad(r, 1) for r in rows]),
        (r'^Home Agency and UnitRow(\d+)$', [pad(r, 2) for r in rows])])
    rows = _table_rows(s.get('Activity Log') or '')
    # 60 lines in three runs of FEMA's numbering: page 1 = Row1..Row24,
    # page 2 = Row1_2..Row24_2 then Row25..Row36 (no suffix). The last run
    # is the one that reports the overflow.
    times = [pad(r, 0) for r in rows]
    acts = [pad(r, 1) for r in rows]
    ctx.rows('7 activity log', [
        (r'^DateTimeRow([1-9]|1\d|2[0-4])$', times[:24]),
        (r'^Notable ActivitiesRow([1-9]|1\d|2[0-4])$', acts[:24]),
        (r'^DateTimeRow(\d+)_2$', times[24:48]),
        (r'^Notable ActivitiesRow(\d+)_2$', acts[24:48]),
        (r'^DateTimeRow(2[5-9]|3[0-6])$', times[48:]),
        (r'^Notable ActivitiesRow(2[5-9]|3[0-6])$', acts[48:])])
    _prepared_by(ctx, s.get('Prepared By'))


FORM_MAPS: dict[str, Callable[[_Sections, _Ctx], None]] = {
    '201': _map_201, '202': _map_202, '203': _map_203, '204': _map_204,
    '205A': _map_205a, '209': _map_209, '214': _map_214,
}


def form_pdf_path(number: str) -> str:
    return os.path.join(FORM_DIR, 'ics_%s.pdf' % number.lower())


# --------------------------------------------------------------- filling

def _widgets(doc) -> list[tuple[int, str, object]]:
    """(page index, field name, annotation) for every widget of a reader or
    writer. Names are matched STRIPPED — two ICS 209 field names start with
    a space in FEMA's file."""
    out = []
    for pi, page in enumerate(doc.pages):
        for a in (page.get('/Annots') or []):
            a = a.get_object()
            if a.get('/Subtype') != '/Widget':
                continue
            name = a.get('/T')
            parent = a.get('/Parent')
            if name is None and parent is not None:
                name = parent.get_object().get('/T')
            if name is None:
                continue
            out.append((pi, str(name), a))
    return out


def _field_type(a) -> str | None:
    ft = a.get('/FT')
    if ft is None and a.get('/Parent') is not None:
        ft = a['/Parent'].get_object().get('/FT')
    return str(ft) if ft is not None else None


def _on_state(a) -> str:
    try:
        for k in a['/AP']['/N'].keys():
            if k != '/Off':
                return str(k)
    except (KeyError, AttributeError, TypeError):
        pass
    return '/Yes'


def _matches(key, name: str) -> bool:
    if isinstance(key, re.Pattern):
        return key.search(name.strip()) is not None
    return name.strip() == key


def _row_of(pattern: re.Pattern, name: str) -> int:
    m = pattern.search(name.strip())
    if not m:
        return 0
    for g in m.groups():
        if g:
            return int(g)
    return 1


def build_field_values(number: str, content: str) -> dict:
    """The values the export will write, keyed by exact field name, plus
    the report — computed without touching the PDF beyond reading its field
    names. This is what the JSON variant of the endpoint returns."""
    if number not in FORM_MAPS:
        raise IcsPdfError('No FEMA form mapping for ICS %s' % number)
    path = form_pdf_path(number)
    if not os.path.exists(path):
        raise IcsPdfError('Bundled FEMA form missing: %s' % os.path.basename(path))
    sections = _Sections(parse_sections(content or ''))
    ctx = _Ctx()
    FORM_MAPS[number](sections, ctx)

    widgets = _widgets(PdfReader(path))
    names = sorted({n.strip() for (_p, n, _a) in widgets})
    types = {}
    for _p, n, a in widgets:
        types.setdefault(n.strip(), _field_type(a))

    values: dict[str, str] = {}
    checks: dict[str, bool] = {}
    unresolved: list[str] = []
    for key, value in ctx.texts:
        hit = [n for n in names if _matches(key, n) and types.get(n) == '/Tx']
        if not hit:
            unresolved.append(key.pattern if isinstance(key, re.Pattern) else key)
        for n in hit:
            values[n] = value
    for key, on in ctx.checks:
        hit = [n for n in names if _matches(key, n) and types.get(n) == '/Btn']
        if not hit:
            unresolved.append(key.pattern if isinstance(key, re.Pattern) else key)
        for n in hit:
            checks[n] = on
    overflow = dict(ctx.overflow)
    for label, pattern, row_values in ctx.series:
        slots = sorted({(_row_of(pattern, n), n) for n in names
                        if pattern.search(n) and types.get(n) == '/Tx'})
        if not slots:
            unresolved.append(pattern.pattern)
            continue
        for i, v in enumerate(row_values):
            if i >= len(slots):
                overflow[label] = max(overflow.get(label, 0), len(row_values) - len(slots))
                break
            if v:
                values[slots[i][1]] = v
    return {
        'form': number,
        'values': values,
        'checks': checks,
        'overflow': overflow,
        'unreviewed_ai_fields': ctx.unreviewed,
        'unmapped': sections.unused(),
        'unresolved': unresolved,
    }


def render_ics_pdf(number: str, content: str) -> tuple[bytes, dict]:
    """Fill the bundled FEMA form for `number` from the note `content`.
    Returns (pdf bytes, report) — see build_field_values for the report."""
    report = build_field_values(number, content)
    reader = PdfReader(form_pdf_path(number))
    # Only the pages that carry a field: FEMA's instruction pages are the
    # ones with none. Appending (rather than cloning and removing) keeps the
    # AcroForm, its fonts and every field, at half the size.
    keep = sorted({pi for (pi, _n, _a) in _widgets(reader)})
    writer = PdfWriter()
    writer.append(reader, pages=keep)
    by_page: dict[int, dict[str, str]] = {}
    for pi, name, a in _widgets(writer):
        key = name.strip()
        if key in report['values']:
            by_page.setdefault(pi, {})[name] = report['values'][key]
        elif key in report['checks']:
            by_page.setdefault(pi, {})[name] = _on_state(a) if report['checks'][key] else '/Off'
    for pi, fields in by_page.items():
        writer.update_page_form_field_values(writer.pages[pi], fields, auto_regenerate=False)
    # Viewers regenerate the appearance streams from the values (long text
    # wraps in the viewer, not in pypdf's minimal appearance).
    writer.set_need_appearances_writer(True)
    writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
    buf = io.BytesIO()
    writer.write(buf)
    report['pages'] = len(writer.pages)
    return buf.getvalue(), report

#  IRIS-NG Source Code
#  contact@dfir-iris.org
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3 of the License, or (at your option) any later version.
"""Post-render repair for docx reports produced by docx_generator/docxtpl.

Two defects make a rendered report fail to open in Microsoft Word even though
the file is a valid ZIP whose XML is well-formed (python-docx opens it fine),
producing the generic:

    "Word experienced an error trying to open the file."

1. XML declaration quoting (the load-bearing one). docx_generator re-serialises
   every package part through lxml, which emits the XML declaration with SINGLE
   quotes and a bare ``\n``::

       <?xml version='1.0' encoding='UTF-8' standalone='yes'?>

   Word's OPC parser is strict and expects the canonical Office form with DOUBLE
   quotes and ``\r\n``::

       <?xml version="1.0" encoding="UTF-8" standalone="yes"?>

   Word rejects the package outright when the relationship parts (``.rels``) and
   ``[Content_Types].xml`` carry the single-quoted declaration. This affects
   EVERY part, including parts no other repair step touches.

2. Unbalanced bookmarks. docxtpl's Jinja rendering can drop a ``<w:bookmarkEnd>``
   whose matching ``<w:bookmarkStart>`` survives (typically Table-of-Contents
   ``_Toc`` anchors inside headings carrying template fields), leaving an
   orphaned anchor that Word also rejects. Removing a half-anchored bookmark is
   safe: it marks nothing, so deleting it changes no visible content.

``repair_docx_for_word`` normalises both, rewriting the package in place. It is
defensive: it never raises on a structurally-valid docx and leaves the file
untouched on any unexpected error, so report generation is never broken by the
repair step itself.
"""

import logging
import os
import re
import shutil
import tempfile
import zipfile

log = logging.getLogger(__name__)

# Parts that may carry bookmarks. document.xml is the common case; headers /
# footers / notes can host them too.
_BOOKMARK_PARTS = re.compile(r'^word/(document|header\d+|footer\d+|footnotes|endnotes)\.xml$')

_RE_BM_START = re.compile(r'<w:bookmarkStart\b[^>]*\bw:id="([^"]+)"[^>]*/?>')
_RE_BM_END = re.compile(r'<w:bookmarkEnd\b[^>]*\bw:id="([^"]+)"[^>]*/?>')

# The canonical Office XML declaration Word expects.
_CANONICAL_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
# Matches any leading XML declaration regardless of quote style / spacing.
_RE_DECL = re.compile(r'^\s*<\?xml[^>]*\?>\s*', re.IGNORECASE)

# docx_generator re-serialises docProps/core.xml and appends empty metadata
# elements (notably <dc:identifier></dc:identifier> and <dc:language></dc:language>)
# AFTER <cp:category>. Word reads core.xml very early and enforces the OPC
# core-properties element order strictly; these out-of-place trailing elements
# make Word reject the whole package with "Word experienced an error trying to
# open the file" (offering the Text Recovery converter), regardless of the body
# content or which case is exported. They are empty and optional, so the safe
# repair is to drop them entirely, restoring core.xml to its template shape.
_RE_EMPTY_CORE_PROPS = re.compile(
    r'<(dc:identifier|dc:language)\b[^>]*>\s*</\1>'  # <dc:identifier></dc:identifier>
    r'|<(dc:identifier|dc:language)\b[^>]*/>'        # <dc:identifier/>
)


def _sanitize_core_props(raw: bytes) -> tuple[bytes, bool]:
    """Strip empty out-of-order dc:identifier/dc:language from docProps/core.xml."""
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw, False
    new_text = _RE_EMPTY_CORE_PROPS.sub('', text)
    if new_text == text:
        return raw, False
    return new_text.encode('utf-8'), True


def _normalize_declaration(raw: bytes) -> tuple[bytes, bool]:
    """Return (data, changed) with the XML declaration normalised to Office form.

    Operates on bytes so non-XML members are left untouched. Only rewrites parts
    that actually start with an XML declaration.
    """
    # Cheap guard: must begin with an XML declaration (optionally BOM-prefixed).
    head = raw[:8].lstrip(b'\xef\xbb\xbf')
    if not head.startswith(b'<?xml'):
        return raw, False
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw, False
    text = text.lstrip('﻿')
    new_text = _RE_DECL.sub(_CANONICAL_DECL, text, count=1)
    if new_text == text:
        return raw, False
    return new_text.encode('utf-8'), True


def _balance_bookmarks_in_xml(xml: str) -> tuple[str, int]:
    """Return (repaired_xml, removed_count) with unbalanced bookmarks dropped."""
    start_ids = _RE_BM_START.findall(xml)
    end_ids = _RE_BM_END.findall(xml)
    if not start_ids and not end_ids:
        return xml, 0

    orphan_starts = set(start_ids) - set(end_ids)
    orphan_ends = set(end_ids) - set(start_ids)
    if not orphan_starts and not orphan_ends:
        return xml, 0

    removed = 0

    def _drop_start(m: 're.Match') -> str:
        nonlocal removed
        if m.group(1) in orphan_starts:
            removed += 1
            return ''
        return m.group(0)

    def _drop_end(m: 're.Match') -> str:
        nonlocal removed
        if m.group(1) in orphan_ends:
            removed += 1
            return ''
        return m.group(0)

    xml = _RE_BM_START.sub(_drop_start, xml)
    xml = _RE_BM_END.sub(_drop_end, xml)
    return xml, removed


# A <w:t> (text element) is character-data only — it must never contain child
# elements. docx_generator's markdown filter (mistletoe DocxRenderer, 2021)
# returns block-level WordprocessingML (full <w:p>...</w:p> markup); the IRIS-NG
# report template embeds that filter inside a run (<w:r><w:t>{{ ... }}</w:t></w:r>),
# so the block output lands *inside* a <w:t>, producing <w:t><w:p>...</w:p></w:t>
# and similar illegal nesting. The result is well-formed XML but invalid OOXML,
# and Word rejects the whole document ("Word experienced an error... use the
# Text Recovery converter").
#
# We repair this with a real XML parse (lxml): any <w:t> that has element
# children is collapsed to the concatenated visible text it carries, dropping
# the injected markup tags. This recovers the analyst's prose; only the broken
# inline formatting the renderer tried (and failed) to express is lost.
_W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
_W = '{%s}' % _W_NS
_XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'


def _flatten_invalid_text_runs(xml: str) -> tuple[str, int]:
    """Flatten any <w:t> that illegally contains child elements. Returns (xml, n).

    Uses lxml so deeply / irregularly nested renderer output is handled correctly
    (manual tag-walking is too fragile for the interleaved <w:p>/<w:r>/<w:t> the
    renderer emits). Returns the original string unchanged on parse failure.
    """
    try:
        from lxml import etree
    except Exception:
        return xml, 0
    try:
        root = etree.fromstring(xml.encode('utf-8'))
    except Exception:
        return xml, 0

    fixed = 0
    for t in root.iter(_W + 't'):
        if len(t) == 0:
            continue  # no element children — already valid
        # Concatenate all visible text in document order, then strip children.
        text = ''.join(t.itertext())
        for child in list(t):
            t.remove(child)
        t.text = text
        t.set(_XML_SPACE, 'preserve')
        fixed += 1

    if fixed == 0:
        return xml, 0

    # Preserve the original XML declaration; lxml's tostring can re-add one.
    body = etree.tostring(root, xml_declaration=False, encoding='unicode')
    return body, fixed


def repair_docx_for_word(docx_path: str) -> dict:
    """Normalise a rendered .docx so Word will open it, rewriting it in place.

    Returns a dict of what was repaired:
        {'decl_fixed': <n parts>, 'bookmarks_removed': <n anchors>}
    Never raises on a structurally-valid docx; logs and leaves the file
    untouched on any unexpected error.
    """
    result = {'decl_fixed': 0, 'bookmarks_removed': 0, 'core_props_fixed': 0, 'text_runs_flattened': 0}
    try:
        if not zipfile.is_zipfile(docx_path):
            return result

        with zipfile.ZipFile(docx_path, 'r') as zin:
            infos = zin.infolist()
            contents = {info.filename: zin.read(info.filename) for info in infos}

        changed = False

        # 1) Normalise the XML declaration on every XML/rels part.
        for name in list(contents.keys()):
            if not (name.endswith('.xml') or name.endswith('.rels')):
                continue
            new_data, did = _normalize_declaration(contents[name])
            if did:
                contents[name] = new_data
                result['decl_fixed'] += 1
                changed = True

        # 1b) Strip the schema-invalid empty core-properties docx_generator adds.
        if 'docProps/core.xml' in contents:
            new_data, did = _sanitize_core_props(contents['docProps/core.xml'])
            if did:
                contents['docProps/core.xml'] = new_data
                result['core_props_fixed'] += 1
                changed = True

        # 2) Flatten <w:t> elements that illegally contain child markup, then
        #    rebalance bookmarks, on every body-like part.
        for name in list(contents.keys()):
            if not _BOOKMARK_PARTS.match(name):
                continue
            try:
                xml = contents[name].decode('utf-8')
            except UnicodeDecodeError:
                continue

            xml, flattened = _flatten_invalid_text_runs(xml)
            if flattened:
                result['text_runs_flattened'] += flattened
                changed = True

            xml, removed = _balance_bookmarks_in_xml(xml)
            if removed:
                result['bookmarks_removed'] += removed
                changed = True

            if flattened or removed:
                contents[name] = xml.encode('utf-8')

        if not changed:
            return result

        # Rewrite the package atomically, preserving member order/metadata.
        fd, tmp_path = tempfile.mkstemp(suffix='.docx', dir=os.path.dirname(docx_path) or None)
        os.close(fd)
        with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zout:
            for info in infos:
                data = contents[info.filename]
                zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                zi.compress_type = info.compress_type
                zi.external_attr = info.external_attr
                zi.internal_attr = info.internal_attr
                zi.create_system = info.create_system
                zout.writestr(zi, data)

        shutil.move(tmp_path, docx_path)
        log.info('Repaired docx for Word (%s): decl_fixed=%d bookmarks_removed=%d core_props_fixed=%d '
                 'text_runs_flattened=%d', os.path.basename(docx_path), result['decl_fixed'],
                 result['bookmarks_removed'], result['core_props_fixed'], result['text_runs_flattened'])
        return result

    except Exception as exc:  # never let the repair break report generation
        log.error('docx repair skipped for %s: %s', docx_path, exc)
        return result


# Backwards-compatible alias.
def repair_docx_bookmarks(docx_path: str) -> int:
    return repair_docx_for_word(docx_path)['bookmarks_removed']

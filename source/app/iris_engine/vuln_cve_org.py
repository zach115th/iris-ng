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
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

"""cve.org lookups for the vulnerability catalogue (iris-ng 2026-11-07).

One outbound request per lookup, on demand only: GET
https://cveawg.mitre.org/api/cve/<CVE-ID> (the CVE Services record behind
cve.org), through the proxies configured on Settings -> General. Only the CVE
id leaves the instance. Settings -> System "Look up CVEs on cve.org"
(server_settings.enable_cve_lookup, NULL = on) turns it off.

`map_record()` turns a CVE JSON 5 record into catalogue fields: the CNA's
title, English description, CVSS (the newest version the CNA - or failing
that an ADP such as CISA - published), CWEs, affected products with their
version ranges, references, publication dates, and from CISA's ADP container
the KEV listing and the SSVC "Exploitation" value (active -> in the wild,
poc -> proof of concept, none -> none known).

`sync_plan()` decides field by field what a sync changes: a value equal to
what the previous sync stored (or still empty) follows cve.org; a value the
analyst changed since is kept unless the sync is forced.
"""

import re
from datetime import datetime

import requests

from app import app

API_URL = 'https://cveawg.mitre.org/api/cve/{}'
REQUEST_TIMEOUT = 15
CVE_RE = re.compile(r'^CVE-\d{4}-\d{4,}$', re.IGNORECASE)

# What a sync can update, as (field label, columns it covers).
SYNC_FIELDS = (
    ('title', ('title',)),
    ('description', ('description',)),
    ('cvss', ('cvss_version', 'cvss_vector', 'cvss_score')),
    ('cwes', ('cwes',)),
    ('affected_products', ('affected_products',)),
    ('reference_urls', ('reference_urls',)),
    ('published_at', ('published_at',)),
    ('modified_at', ('modified_at',)),
    ('kev', ('kev',)),
    ('kev_date_added', ('kev_date_added',)),
    ('exploit_maturity', ('exploit_maturity',)),
)
SYNC_COLUMNS = tuple(c for _, cols in SYNC_FIELDS for c in cols)


class CveOrgError(Exception):
    """kind: 'disabled' | 'invalid' | 'not_found' | 'unavailable'."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind
        self.message = message


def is_cve_id(identifier):
    return bool(CVE_RE.match((identifier or '').strip()))


def lookup_enabled():
    try:
        from app.datamgmt.manage.manage_srv_settings_db import get_srv_settings
        settings = get_srv_settings()
        return settings is None or settings.enable_cve_lookup is not False
    except Exception:
        return True


def _proxies():
    from app.iris_engine.update_check import _proxies as configured
    return configured()


def fetch_record(identifier):
    """The raw CVE JSON 5 record. Raises CveOrgError. Suites patch this
    function (module attribute) to stay offline."""
    ident = (identifier or '').strip().upper()
    if not is_cve_id(ident):
        raise CveOrgError('invalid', 'cve.org lookups take a CVE id such as CVE-2024-3400.')
    try:
        r = requests.get(API_URL.format(ident), timeout=REQUEST_TIMEOUT, proxies=_proxies(), headers={
            'Accept': 'application/json',
            'User-Agent': 'iris-ng/%s' % app.config.get('IRIS_VERSION'),
        })
    except requests.RequestException as e:
        raise CveOrgError('unavailable', 'cve.org could not be reached (%s).' % e.__class__.__name__)
    if r.status_code == 404:
        raise CveOrgError('not_found', 'cve.org has no record for %s.' % ident)
    if r.status_code != 200:
        raise CveOrgError('unavailable', 'cve.org answered HTTP %d.' % r.status_code)
    try:
        return r.json()
    except ValueError:
        raise CveOrgError('unavailable', 'cve.org did not return JSON.')


# ---------------------------------------------------------------- mapping

_METRIC_KEYS = (('cvssV4_0', '4.0'), ('cvssV3_1', '3.1'), ('cvssV3_0', '3.0'), ('cvssV2_0', '2.0'))


def _date(value):
    if not value or not isinstance(value, str):
        return None
    m = re.match(r'^(\d{4}-\d{2}-\d{2})', value)
    return m.group(1) if m else None


def _english(items):
    items = [d for d in (items or []) if isinstance(d, dict) and isinstance(d.get('value'), str)]
    for d in items:
        if str(d.get('lang', '')).lower().startswith('en'):
            return d['value'].strip()
    return items[0]['value'].strip() if items else None


def _best_cvss(containers):
    """(version, vector, score) from the newest metric version found, CNA first."""
    for container in containers:
        found = {}
        for metric in (container or {}).get('metrics') or []:
            if not isinstance(metric, dict):
                continue
            for key, version in _METRIC_KEYS:
                m = metric.get(key)
                if isinstance(m, dict) and version not in found:
                    found[version] = m
        for _, version in _METRIC_KEYS:
            m = found.get(version)
            if m is None:
                continue
            score = m.get('baseScore')
            try:
                score = float(score) if score is not None else None
            except (TypeError, ValueError):
                score = None
            vector = m.get('vectorString') if isinstance(m.get('vectorString'), str) else None
            return version, vector, score
    return None, None, None


def _versions_text(affected):
    parts = []
    for v in affected.get('versions') or []:
        if not isinstance(v, dict) or v.get('status') != 'affected':
            continue
        start = str(v.get('version') or '').strip()
        if v.get('lessThan'):
            end = '< %s' % v['lessThan']
        elif v.get('lessThanOrEqual'):
            end = '<= %s' % v['lessThanOrEqual']
        else:
            end = None
        if end:
            parts.append(end if start in ('', '0', '*', 'n/a') else '%s to %s' % (start, end))
        elif start and start not in ('*', 'n/a'):
            parts.append(start)
    if not parts and affected.get('defaultStatus') == 'affected':
        return 'all versions'
    return ', '.join(parts) or None


def _products(cna):
    out, seen = [], set()
    for a in cna.get('affected') or []:
        if not isinstance(a, dict):
            continue
        product = str(a.get('product') or '').strip()
        vendor = str(a.get('vendor') or '').strip()
        if not product or product.lower() == 'n/a':
            continue
        if vendor.lower() == 'n/a':
            vendor = ''
        entry = {'product': product}
        if vendor:
            entry['vendor'] = vendor
        versions = _versions_text(a)
        if versions:
            entry['versions'] = versions
        key = (vendor.lower(), product.lower(), versions or '')
        if key not in seen:
            seen.add(key)
            out.append(entry)
    return out[:200]


def _cwes(cna):
    out = []
    for pt in cna.get('problemTypes') or []:
        for d in (pt or {}).get('descriptions') or []:
            cwe = str((d or {}).get('cweId') or '').strip().upper()
            if re.match(r'^CWE-\d+$', cwe) and cwe not in out:
                out.append(cwe)
    return out[:50]


def _references(cna):
    out = []
    for ref in cna.get('references') or []:
        url = str((ref or {}).get('url') or '').strip()
        if re.match(r'^https?://\S+$', url, re.IGNORECASE) and url not in out:
            out.append(url)
    return out[:100]


def _cisa(adps):
    """(kev listed, kev date added, ssvc exploitation) from the ADP containers."""
    kev, kev_date, exploitation = False, None, None
    for adp in adps:
        for metric in (adp or {}).get('metrics') or []:
            other = (metric or {}).get('other') or {}
            content = other.get('content') or {}
            if other.get('type') == 'kev':
                kev = True
                kev_date = _date(content.get('dateAdded')) or kev_date
            elif other.get('type') == 'ssvc':
                for opt in content.get('options') or []:
                    if isinstance(opt, dict) and 'Exploitation' in opt:
                        exploitation = str(opt['Exploitation']).lower()
    return kev, kev_date, exploitation


def map_record(record):
    """{'state', 'assigner', 'date_updated', 'values': {column: value}} for a CVE JSON 5 record.
    'values' holds only what the record states (no key = no information)."""
    if not isinstance(record, dict) or not isinstance(record.get('cveMetadata'), dict):
        raise CveOrgError('unavailable', 'cve.org returned a record this version cannot read.')
    meta = record['cveMetadata']
    containers = record.get('containers') or {}
    cna = containers.get('cna') or {}
    adps = [a for a in containers.get('adp') or [] if isinstance(a, dict)]
    values = {}

    description = _english(cna.get('descriptions'))
    if description:
        values['description'] = description
    title = str(cna.get('title') or '').strip()
    if not title and description:
        first = re.split(r'(?<=[.!?])\s', description, maxsplit=1)[0]
        title = first if len(first) <= 160 else first[:157].rstrip() + '...'
    if title:
        values['title'] = title

    version, vector, score = _best_cvss([cna] + adps)
    if version:
        values['cvss_version'] = version
        values['cvss_vector'] = vector
        values['cvss_score'] = score

    cwes = _cwes(cna)
    if cwes:
        values['cwes'] = cwes
    products = _products(cna)
    if products:
        values['affected_products'] = products
    refs = _references(cna)
    if refs:
        values['reference_urls'] = refs
    if _date(meta.get('datePublished')):
        values['published_at'] = _date(meta.get('datePublished'))
    if _date(meta.get('dateUpdated')):
        values['modified_at'] = _date(meta.get('dateUpdated'))

    kev, kev_date, exploitation = _cisa(adps)
    values['kev'] = kev
    if kev_date:
        values['kev_date_added'] = kev_date
    if kev or exploitation == 'active':
        values['exploit_maturity'] = 'in-the-wild'
    elif exploitation == 'poc':
        values['exploit_maturity'] = 'poc'
    elif exploitation == 'none':
        values['exploit_maturity'] = 'none'

    return {
        'identifier': str(meta.get('cveId') or '').upper() or None,
        'state': meta.get('state'),
        'assigner': meta.get('assignerShortName'),
        'date_updated': meta.get('dateUpdated'),
        'values': values,
    }


def lookup(identifier):
    """fetch + map, honouring the Settings switch. Raises CveOrgError."""
    if not lookup_enabled():
        raise CveOrgError('disabled', 'cve.org lookups are turned off (Settings -> System).')
    return map_record(fetch_record(identifier))


def enrichment_block(mapped):
    """What an entry stores as enrichment.cve_org after a lookup or a sync."""
    return {
        'state': mapped.get('state'),
        'assigner': mapped.get('assigner'),
        'date_updated': mapped.get('date_updated'),
        'synced_at': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
        'values': dict(mapped.get('values') or {}),
    }


def _empty(value):
    return value is None or value == '' or value == [] or value == {}


def sync_plan(current, baseline, new_values, force=False):
    """(updates {column: value}, updated_fields, kept_fields).

    current: the entry's present values by column; baseline: the values the
    previous sync stored (None = never synced); new_values: map_record values.
    A field cve.org says nothing about is left alone."""
    updates, updated, kept = {}, [], []
    for label, cols in SYNC_FIELDS:
        if not any(c in new_values for c in cols):
            continue
        new = {c: new_values.get(c) for c in cols}
        cur = {c: current.get(c) for c in cols}
        if all(_empty(v) for v in new.values()):
            continue
        if cur == new:
            continue
        cur_empty = all(_empty(v) or v is False for v in cur.values())
        if baseline is None:
            local_edit = not cur_empty
        else:
            base = {c: baseline.get(c) for c in cols}
            local_edit = not cur_empty and cur != base
        if local_edit and not force:
            kept.append(label)
            continue
        updates.update(new)
        updated.append(label)
    return updates, updated, kept

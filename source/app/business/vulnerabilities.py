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

"""The vulnerability catalogue (iris-ng 2026-11-07; sidebar Intel -> Vulnerabilities).

Entries are global (not case data): every signed-in user reads them and may
create or edit them; merge and delete are for server administrators (the
routes enforce that - no new permission bit). What an entry is EXPOSED on is
case and registry data, so exposure and the per-row counts only ever count
cases the viewer can open and registry entries of customers the viewer is
associated with.

Rules worth knowing:
  * the identifier is unique ignoring case, and no identifier may be the
    identifier or an alias of another entry (a merge turns the merged entry's
    identifier into an alias of the survivor);
  * private entries get IRIS-VULN-<year>-<NNNN> under an advisory lock, never
    re-using a number still present as an identifier or alias;
  * a CVSS vector sets the version and, unless a score is given, the score
    (the `cvss` library, CVSS 2.0 / 3.0 / 3.1 / 4.0 base scores); the severity
    follows the score unless it was set by hand;
  * CVE IOCs (IOC type `vulnerability`) link to an entry when their value is
    the entry's identifier or one of its aliases - derived, nothing stored.
"""

import re
import uuid
from datetime import date
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import Text
from sqlalchemy import case as sa_case
from sqlalchemy import cast
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import text

from app import db
from app.iris_engine import vuln_cve_org
from app.models import vulnerability_vocab as vv
from app.models.models import Tlp
from app.models.models import Vulnerability
from app.models.models import VulnerabilityFinding
from app.models.models import VulnerabilityFindingChange
from app.models.models import WarRoomVulnerability

MAX_PER_PAGE = 100
_IDENT_RE = re.compile(r'^\S{1,128}$')
_PRIVATE_RE = re.compile(r'^IRIS-VULN-(\d{4})-(\d+)$', re.IGNORECASE)
_CWE_RE = re.compile(r'^(CWE-\d+|NVD-CWE-[A-Za-z]+)$')
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class VulnError(Exception):
    def __init__(self, message, status=400, data=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.data = data


# ---------------------------------------------------------------- helpers

def _iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _str(value, field, limit, required=False):
    if value is None:
        value = ''
    if not isinstance(value, str):
        raise VulnError('%s must be text.' % field)
    value = value.strip()
    if required and not value:
        raise VulnError('%s is required.' % field)
    if len(value) > limit:
        raise VulnError('%s is longer than %d characters.' % (field, limit))
    return value or None


def _date_value(value, field):
    if value in (None, ''):
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()[:10]):
        raise VulnError('%s must be a date (YYYY-MM-DD).' % field)
    try:
        return datetime.strptime(value.strip()[:10], '%Y-%m-%d').date()
    except ValueError:
        raise VulnError('%s is not a valid date.' % field)


def _fraction(value, field):
    if value in (None, ''):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise VulnError('%s must be a number between 0 and 1.' % field)
    if not 0 <= f <= 1:
        raise VulnError('%s must be between 0 and 1.' % field)
    return round(f, 6)


def _score(value):
    if value in (None, ''):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise VulnError('The CVSS score must be a number between 0.0 and 10.0.')
    if not 0 <= f <= 10:
        raise VulnError('The CVSS score must be between 0.0 and 10.0.')
    return round(f, 1)


def _bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


def _split(value, pattern=r'[,\n]+'):
    if value is None:
        return []
    if isinstance(value, str):
        return [p.strip() for p in re.split(pattern, value) if p.strip()]
    if isinstance(value, (list, tuple)):
        out = []
        for p in value:
            if not isinstance(p, str):
                raise VulnError('Expected a list of text values.')
            if p.strip():
                out.append(p.strip())
        return out
    raise VulnError('Expected a list or comma-separated text.')


def normalise_identifier(value):
    ident = (value or '').strip()
    if vuln_cve_org.is_cve_id(ident) or re.match(r'^GHSA-', ident, re.IGNORECASE):
        ident = ident.upper()
        if ident.startswith('GHSA-'):
            ident = 'GHSA-' + ident[5:].lower()
    return ident


def severity_for_score(score):
    if score is None:
        return 'unknown'
    if score == 0:
        return 'none'
    if score < 4.0:
        return 'low'
    if score < 7.0:
        return 'medium'
    if score < 9.0:
        return 'high'
    return 'critical'


def score_vector(vector):
    """(version, base score) of a CVSS vector. Raises VulnError."""
    from cvss import CVSS2, CVSS3, CVSS4
    v = vector.strip()
    try:
        if v.upper().startswith('CVSS:4.0/'):
            return '4.0', round(float(CVSS4(v).base_score), 1)
        if v.upper().startswith('CVSS:3.1/') or v.upper().startswith('CVSS:3.0/'):
            c = CVSS3(v)
            return v[5:8], round(float(c.base_score), 1)
        if v.upper().startswith('CVSS:'):
            raise VulnError('Unknown CVSS version in the vector (2.0, 3.0, 3.1 and 4.0 are supported).')
        return '2.0', round(float(CVSS2(v).base_score), 1)
    except VulnError:
        raise
    except Exception as e:  # cvss raises its own CVSSError subclasses
        raise VulnError('The CVSS vector is not valid: %s' % (str(e) or e.__class__.__name__))


def auto_kind(identifier, is_private):
    if is_private:
        return 'other'
    return 'cve' if vuln_cve_org.is_cve_id(identifier) else 'advisory'


def _products(value):
    if value is None:
        return []
    items = []
    if isinstance(value, str):
        for line in value.splitlines():
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split('|')]
            if len(parts) == 1:
                items.append({'product': parts[0]})
            elif len(parts) == 2:
                items.append({'vendor': parts[0], 'product': parts[1]})
            else:
                items.append({'vendor': parts[0], 'product': parts[1], 'versions': '|'.join(parts[2:]).strip()})
    elif isinstance(value, list):
        items = value
    else:
        raise VulnError('Affected products must be a list.')
    out = []
    for it in items:
        if not isinstance(it, dict):
            raise VulnError('Every affected product must be an object with a product name.')
        product = _str(it.get('product'), 'An affected product name', 300)
        if not product:
            raise VulnError('Every affected product needs a product name.')
        entry = {'product': product}
        vendor = _str(it.get('vendor'), 'An affected product vendor', 300)
        if vendor:
            entry['vendor'] = vendor
        versions = _str(it.get('versions'), 'An affected product versions', 2000)
        if versions:
            entry['versions'] = versions
        out.append(entry)
    if len(out) > 200:
        raise VulnError('At most 200 affected products.')
    return out


def _references(value):
    out = []
    for url in _split(value, r'[\n]+|,(?=\s*https?://)'):
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ('http', 'https') or not parsed.netloc or len(url) > 2048 or ' ' in url:
            raise VulnError('References must be http(s) URLs (%s).' % url[:80])
        if url not in out:
            out.append(url)
    if len(out) > 100:
        raise VulnError('At most 100 references.')
    return out


def _cwes(value):
    out = []
    for raw in _split(value, r'[,\s]+'):
        c = raw.upper()
        if c.isdigit():
            c = 'CWE-' + c
        if c.startswith('NVD-CWE-'):
            c = 'NVD-CWE-' + raw[8:]
        if not _CWE_RE.match(c):
            raise VulnError('%s is not a CWE id (CWE-79, 79).' % raw[:40])
        if c not in out:
            out.append(c)
    return out[:50]


def _tags(value):
    out = []
    for t in _split(value, r'[,|\n]+'):
        if len(t) > 64:
            raise VulnError('A tag is longer than 64 characters.')
        if t not in out:
            out.append(t)
    if len(out) > 30:
        raise VulnError('At most 30 tags.')
    return ','.join(out) or None


# ---------------------------------------------------------------- identity

def find_by_identifier(identifier, exclude_id=None):
    """The entry whose identifier OR alias equals `identifier` (ignoring case)."""
    ident = (identifier or '').strip().upper()
    if not ident:
        return None
    q = Vulnerability.query.filter(or_(
        func.upper(Vulnerability.identifier) == ident,
        text("EXISTS (SELECT 1 FROM jsonb_array_elements_text(vulnerability.aliases) a"
             " WHERE upper(a) = :ident)").bindparams(ident=ident)))
    if exclude_id is not None:
        q = q.filter(Vulnerability.vulnerability_id != exclude_id)
    return q.order_by(Vulnerability.vulnerability_id).first()


def _ensure_free(identifier, exclude_id, what):
    other = find_by_identifier(identifier, exclude_id=exclude_id)
    if other is not None:
        raise VulnError('%s %s already belongs to %s.' % (what, identifier, other.identifier), status=409,
                        data={'existing_id': other.vulnerability_id, 'existing_identifier': other.identifier})


def allocate_private_identifier(year=None):
    year = year or datetime.utcnow().year
    db.session.execute(text("SELECT pg_advisory_xact_lock(hashtext('iris_vulnerability_private_id'))"))
    rows = db.session.execute(text(
        "SELECT upper(identifier) FROM vulnerability WHERE upper(identifier) LIKE :p"
        " UNION SELECT upper(a) FROM vulnerability, jsonb_array_elements_text(aliases) a WHERE upper(a) LIKE :p"),
        {'p': 'IRIS-VULN-%d-%%' % year}).scalars().all()
    top = 0
    for ident in rows:
        m = _PRIVATE_RE.match(ident or '')
        if m and int(m.group(1)) == year:
            top = max(top, int(m.group(2)))
    return 'IRIS-VULN-%d-%04d' % (year, top + 1)


# ---------------------------------------------------------------- write

_ENRICHMENT_VALUE_KEYS = set(vuln_cve_org.SYNC_COLUMNS)


def _clean_cve_enrichment(block):
    if not isinstance(block, dict):
        return None
    values = block.get('values') if isinstance(block.get('values'), dict) else {}
    clean = {k: values[k] for k in values if k in _ENRICHMENT_VALUE_KEYS}
    out = {'values': clean}
    for k in ('state', 'assigner', 'date_updated', 'synced_at'):
        if isinstance(block.get(k), str):
            out[k] = block[k][:64]
    return out


def apply_payload(v, payload, creating, user_id):
    """Validate `payload` and write it onto `v` (keys absent = unchanged)."""
    if not isinstance(payload, dict):
        raise VulnError('Expected a JSON object.')
    p = payload

    if creating:
        v.is_private = _bool(p.get('is_private', False))
        if v.is_private:
            v.identifier = allocate_private_identifier()
        else:
            ident = normalise_identifier(_str(p.get('identifier'), 'The identifier', 128) or '')
            if not ident:
                raise VulnError('A public entry needs an identifier (e.g. CVE-2024-3400), or mark it private.')
            if not _IDENT_RE.match(ident):
                raise VulnError('The identifier cannot contain spaces.')
            if ident.upper().startswith(vv.PRIVATE_PREFIX):
                raise VulnError('%s... identifiers are given to private entries only.' % vv.PRIVATE_PREFIX)
            _ensure_free(ident, None, 'The identifier')
            v.identifier = ident
    elif 'identifier' in p and not v.is_private:
        ident = normalise_identifier(_str(p.get('identifier'), 'The identifier', 128) or '')
        if not ident:
            raise VulnError('The identifier cannot be empty.')
        if not _IDENT_RE.match(ident):
            raise VulnError('The identifier cannot contain spaces.')
        if ident.upper().startswith(vv.PRIVATE_PREFIX):
            raise VulnError('%s... identifiers are given to private entries only.' % vv.PRIVATE_PREFIX)
        if ident.upper() != (v.identifier or '').upper():
            _ensure_free(ident, v.vulnerability_id, 'The identifier')
        v.identifier = ident

    if creating or 'title' in p:
        v.title = _str(p.get('title'), 'A title', 500, required=not creating or 'title' in p) or v.identifier

    if creating or 'kind' in p:
        kind = p.get('kind')
        if kind in (None, '', 'auto'):
            v.kind = auto_kind(v.identifier, v.is_private)
        elif kind not in vv.KINDS:
            raise VulnError('Unknown kind %r.' % kind)
        else:
            v.kind = kind

    if 'description' in p:
        v.description = _str(p.get('description'), 'The description', 20000)

    # CVSS: a vector decides the version and (unless a score is given) the score.
    if 'cvss_vector' in p:
        vector = _str(p.get('cvss_vector'), 'The CVSS vector', 300)
        if vector:
            version, computed = score_vector(vector)
            v.cvss_vector = vector
            v.cvss_version = version
            given = _score(p.get('cvss_score')) if 'cvss_score' in p else None
            v.cvss_score = given if given is not None else computed
        else:
            v.cvss_vector = None
            if 'cvss_version' in p:
                ver = p.get('cvss_version') or None
                if ver is not None and ver not in vv.CVSS_VERSIONS:
                    raise VulnError('Unknown CVSS version %r.' % ver)
                v.cvss_version = ver
            if 'cvss_score' in p:
                v.cvss_score = _score(p.get('cvss_score'))
    else:
        if 'cvss_score' in p:
            v.cvss_score = _score(p.get('cvss_score'))
        if 'cvss_version' in p and not v.cvss_vector:
            ver = p.get('cvss_version') or None
            if ver is not None and ver not in vv.CVSS_VERSIONS:
                raise VulnError('Unknown CVSS version %r.' % ver)
            v.cvss_version = ver

    if 'severity' in p:
        sev = p.get('severity')
        if sev in (None, '', 'auto'):
            v.severity_auto = True
        elif sev not in vv.SEVERITIES:
            raise VulnError('Unknown severity %r.' % sev)
        else:
            v.severity_auto = False
            v.severity = sev
    elif creating:
        v.severity_auto = True
    if v.severity_auto:
        v.severity = severity_for_score(v.cvss_score)

    if 'epss_score' in p:
        v.epss_score = _fraction(p.get('epss_score'), 'EPSS')
    if 'epss_percentile' in p:
        v.epss_percentile = _fraction(p.get('epss_percentile'), 'The EPSS percentile')
    if 'epss_date' in p:
        v.epss_date = _date_value(p.get('epss_date'), 'The EPSS date')

    if 'kev' in p:
        v.kev = _bool(p.get('kev'))
    if 'kev_date_added' in p:
        v.kev_date_added = _date_value(p.get('kev_date_added'), 'The KEV date added')
    if 'kev_due_date' in p:
        v.kev_due_date = _date_value(p.get('kev_due_date'), 'The KEV due date')
    if 'kev_ransomware' in p:
        v.kev_ransomware = _bool(p.get('kev_ransomware'))
    if not v.kev:
        v.kev_date_added = None
        v.kev_due_date = None
        v.kev_ransomware = False

    if creating or 'exploit_maturity' in p:
        em = p.get('exploit_maturity') or 'unknown'
        if em not in vv.EXPLOIT_MATURITIES:
            raise VulnError('Unknown exploit maturity %r.' % em)
        v.exploit_maturity = em
    if creating or 'patch_availability' in p:
        pa = p.get('patch_availability') or 'unknown'
        if pa not in vv.PATCH_AVAILABILITIES:
            raise VulnError('Unknown patch availability %r.' % pa)
        v.patch_availability = pa

    if 'cwes' in p:
        v.cwes = _cwes(p.get('cwes'))
    if 'affected_products' in p:
        v.affected_products = _products(p.get('affected_products'))
    if 'reference_urls' in p:
        v.reference_urls = _references(p.get('reference_urls'))
    if 'published_at' in p:
        v.published_at = _date_value(p.get('published_at'), 'The published date')
    if 'modified_at' in p:
        v.modified_at = _date_value(p.get('modified_at'), 'The modified date')
    if 'tags' in p:
        v.tags = _tags(p.get('tags'))
    if 'tlp_id' in p:
        tlp = p.get('tlp_id')
        if tlp in (None, ''):
            v.tlp_id = None
        else:
            try:
                tlp = int(tlp)
            except (TypeError, ValueError):
                raise VulnError('Unknown TLP.')
            if db.session.get(Tlp, tlp) is None:
                raise VulnError('Unknown TLP.')
            v.tlp_id = tlp

    if 'aliases' in p:
        aliases = []
        for a in _split(p.get('aliases'), r'[,\s]+'):
            a = normalise_identifier(a)
            if len(a) > 128:
                raise VulnError('An alias is longer than 128 characters.')
            if a.upper() == (v.identifier or '').upper() or a.upper() in [x.upper() for x in aliases]:
                continue
            _ensure_free(a, v.vulnerability_id, 'The alias')
            aliases.append(a)
        v.aliases = aliases[:100]

    if creating and isinstance(p.get('enrichment'), dict) and not v.is_private:
        block = _clean_cve_enrichment(p['enrichment'].get('cve_org'))
        if block is not None:
            v.enrichment = {'cve_org': block}
            v.source = 'cve.org'
    if creating:
        v.created_by_id = user_id
    v.updated_at = datetime.utcnow()
    v.updated_by_id = user_id


def create_vulnerability(payload, user_id):
    v = Vulnerability()
    v.vulnerability_uuid = uuid.uuid4()
    v.source = 'manual'
    v.enrichment = {}
    v.cwes, v.affected_products, v.reference_urls, v.aliases = [], [], [], []
    apply_payload(v, payload, True, user_id)
    db.session.add(v)
    db.session.flush()
    return v


def quick_create(identifier, title, user_id):
    """The finding forms' "Quick add": a new public entry from an identifier."""
    payload = {'identifier': identifier}
    if title and title.strip():
        payload['title'] = title
    return create_vulnerability(payload, user_id)


def update_vulnerability(v, payload, user_id):
    apply_payload(v, payload, False, user_id)
    db.session.flush()
    return v


def delete_vulnerability(v):
    counts = {
        'findings': VulnerabilityFinding.query.filter_by(vulnerability_id=v.vulnerability_id).count(),
        'war_rooms': WarRoomVulnerability.query.filter_by(vulnerability_id=v.vulnerability_id).count(),
    }
    db.session.delete(v)
    db.session.flush()
    return counts


def merge_vulnerabilities(source, target, user_id):
    """Move `source`'s findings and war-room entries to `target`, make its
    identifier and aliases aliases of `target`, delete it. A finding on an
    anchor `target` already covers is folded into target's finding (its
    status and notes are appended to the target's notes, its event / IOC
    links added) instead of being duplicated."""
    from app.models.models import VulnerabilityFindingEvent
    from app.models.models import VulnerabilityFindingIoc
    if source.vulnerability_id == target.vulnerability_id:
        raise VulnError('An entry cannot be merged into itself.')

    def anchor(f):
        # A case finding always names its asset (the anchor CHECK), so the asset or the registry entry is the anchor.
        return (f.scope, f.asset_id, f.customer_asset_id)

    existing = {anchor(f): f for f in VulnerabilityFinding.query.filter_by(
        vulnerability_id=target.vulnerability_id).all()}
    moved = folded = 0
    now = datetime.utcnow()
    for f in VulnerabilityFinding.query.filter_by(vulnerability_id=source.vulnerability_id).all():
        twin = existing.get(anchor(f))
        if twin is None:
            f.vulnerability_id = target.vulnerability_id
            f.updated_at, f.updated_by_id = now, user_id
            db.session.add(VulnerabilityFindingChange(finding_id=f.finding_id, field='vulnerability',
                                                      old_value=source.identifier, new_value=target.identifier,
                                                      changed_by=user_id))
            moved += 1
            continue
        line = 'Merged from %s: %s%s' % (source.identifier, vv.REMEDIATION_LABELS.get(f.remediation_status),
                                         (' - ' + f.notes) if f.notes else '')
        twin.notes = (twin.notes + '\n' + line) if twin.notes else line
        twin.updated_at, twin.updated_by_id = now, user_id
        for model, col in ((VulnerabilityFindingEvent, 'event_id'), (VulnerabilityFindingIoc, 'ioc_id')):
            have = {getattr(r, col) for r in model.query.filter_by(finding_id=twin.finding_id).all()}
            for r in model.query.filter_by(finding_id=f.finding_id).all():
                if getattr(r, col) not in have:
                    db.session.add(model(finding_id=twin.finding_id, **{col: getattr(r, col)}))
        db.session.add(VulnerabilityFindingChange(finding_id=twin.finding_id, field='merged',
                                                  old_value=source.identifier, new_value=line[:2000],
                                                  changed_by=user_id))
        db.session.delete(f)
        folded += 1

    rooms = {r.room_id: r for r in WarRoomVulnerability.query.filter_by(vulnerability_id=target.vulnerability_id)}
    moved_rooms = 0
    for r in WarRoomVulnerability.query.filter_by(vulnerability_id=source.vulnerability_id).all():
        twin = rooms.get(r.room_id)
        if twin is None:
            r.vulnerability_id = target.vulnerability_id
            moved_rooms += 1
        else:
            if r.note and r.note != twin.note:
                twin.note = (twin.note + '\n' + r.note) if twin.note else r.note
            db.session.delete(r)

    aliases = list(target.aliases or [])
    for a in [source.identifier] + list(source.aliases or []):
        if a.upper() != target.identifier.upper() and a.upper() not in [x.upper() for x in aliases]:
            aliases.append(a)
    db.session.flush()
    db.session.delete(source)
    db.session.flush()
    target.aliases = aliases[:100]
    target.updated_at, target.updated_by_id = now, user_id
    db.session.flush()
    return {'moved_findings': moved, 'folded_findings': folded, 'moved_war_rooms': moved_rooms}


# ---------------------------------------------------------------- cve.org

def _current_for_sync(v):
    cur = {}
    for col in vuln_cve_org.SYNC_COLUMNS:
        cur[col] = _iso(getattr(v, col))
    if (cur.get('title') or '').strip().upper() == (v.identifier or '').upper():
        cur['title'] = None
    if cur.get('exploit_maturity') == 'unknown':
        cur['exploit_maturity'] = None
    return cur


def sync_from_cve_org(v, user_id, force=False):
    """Refresh a public CVE entry from cve.org. Returns (updated_fields, kept_fields)."""
    if v.is_private or not vuln_cve_org.is_cve_id(v.identifier):
        raise VulnError('Only public CVE entries can be synced from cve.org.')
    mapped = vuln_cve_org.lookup(v.identifier)
    previous = ((v.enrichment or {}).get('cve_org') or {})
    baseline = previous.get('values') if isinstance(previous.get('values'), dict) else None
    updates, updated, kept = vuln_cve_org.sync_plan(_current_for_sync(v), baseline, mapped['values'], force=force)
    payload = dict(updates)
    if 'cvss_vector' in payload and not payload.get('cvss_vector'):
        payload.pop('cvss_vector')
    apply_payload(v, payload, False, user_id)
    if 'cvss_version' in updates and not updates.get('cvss_vector'):
        v.cvss_vector = None
        v.cvss_version = updates.get('cvss_version')
        v.cvss_score = updates.get('cvss_score')
        if v.severity_auto:
            v.severity = severity_for_score(v.cvss_score)
    enrichment = dict(v.enrichment or {})
    enrichment['cve_org'] = vuln_cve_org.enrichment_block(mapped)
    v.enrichment = enrichment
    db.session.flush()
    return updated, kept


def cve_lookup(identifier):
    """The cve.org prefill for the New vulnerability form."""
    mapped = vuln_cve_org.lookup(identifier)
    ident = mapped.get('identifier') or identifier.strip().upper()
    existing = find_by_identifier(ident)
    out = {
        'identifier': ident,
        'state': mapped.get('state'),
        'assigner': mapped.get('assigner'),
        'date_updated': mapped.get('date_updated'),
        'values': mapped['values'],
        'existing_id': existing.vulnerability_id if existing else None,
        'existing_identifier': existing.identifier if existing else None,
    }
    out['enrichment'] = {'cve_org': vuln_cve_org.enrichment_block(mapped)}
    return out


# ---------------------------------------------------------------- visibility + counts

class Viewer:
    """What one user may count: cases they can open, customers they belong to."""

    def __init__(self, user_id, is_admin):
        from app.iris_engine.access_control.utils import ac_get_fast_user_cases_access
        from app.datamgmt.manage.manage_access_control_db import get_user_clients_id
        self.user_id = user_id
        self.is_admin = is_admin
        self.case_ids = set(ac_get_fast_user_cases_access(user_id) or [])
        self.client_ids = None if is_admin else set(get_user_clients_id(user_id) or [])

    def sees_case(self, case_id):
        return case_id in self.case_ids

    def sees_client(self, client_id):
        return self.client_ids is None or client_id in self.client_ids

    def finding_filter(self):
        """SQL condition over vulnerability_finding (aliased f) + customer_asset (ca)."""
        conds, params = [], {}
        if self.case_ids:
            conds.append("f.case_id = ANY(:vis_cases)")
            params['vis_cases'] = list(self.case_ids)
        if self.client_ids is None:
            conds.append("f.customer_asset_id IS NOT NULL")
        elif self.client_ids:
            conds.append("(f.customer_asset_id IS NOT NULL AND ca.customer_id = ANY(:vis_clients))")
            params['vis_clients'] = list(self.client_ids)
        if not conds:
            return "false", {}
        # Only the parameters the condition names: text().bindparams() refuses the others.
        return "(" + " OR ".join(conds) + ")", params


def _empty_counts():
    return {'findings': 0, 'open': 0, 'fixed': 0, 'dismissed': 0, 'exploited': 0, 'cases': 0,
            'registry_assets': 0}


def counts_for(vuln_ids, viewer):
    """{vulnerability_id: counts} over the findings the viewer may see."""
    out = {vid: _empty_counts() for vid in vuln_ids}
    if not vuln_ids:
        return out
    cond, params = viewer.finding_filter()
    params['ids'] = list(vuln_ids)
    rows = db.session.execute(text(
        "SELECT f.vulnerability_id, f.case_id, f.customer_asset_id, f.remediation_status, f.exploitation_status"
        " FROM vulnerability_finding f LEFT JOIN customer_asset ca ON ca.id = f.customer_asset_id"
        " WHERE f.vulnerability_id = ANY(:ids) AND " + cond), params).all()
    cases = {}
    for vid, case_id, ca_id, status, exploitation in rows:
        c = out[vid]
        c['findings'] += 1
        c[vv.status_group(status)] += 1
        if exploitation == 'exploited':
            c['exploited'] += 1
        if case_id is not None:
            cases.setdefault(vid, set()).add(case_id)
        if ca_id is not None:
            c['registry_assets'] += 1
    for vid, s in cases.items():
        out[vid]['cases'] = len(s)
    return out


# ---------------------------------------------------------------- read

def summary_row(v):
    return {
        'vulnerability_id': v.vulnerability_id, 'identifier': v.identifier, 'is_private': v.is_private,
        'kind': v.kind, 'title': v.title, 'cvss_score': v.cvss_score, 'cvss_version': v.cvss_version,
        'severity': v.severity, 'kev': v.kev, 'kev_ransomware': v.kev_ransomware,
        'exploit_maturity': v.exploit_maturity, 'patch_availability': v.patch_availability,
    }


def vuln_row(v, counts=None):
    d = {
        'vulnerability_id': v.vulnerability_id, 'vulnerability_uuid': str(v.vulnerability_uuid),
        'identifier': v.identifier, 'is_private': v.is_private, 'kind': v.kind, 'title': v.title,
        'description': v.description, 'cvss_version': v.cvss_version, 'cvss_vector': v.cvss_vector,
        'cvss_score': v.cvss_score, 'severity': v.severity, 'severity_auto': v.severity_auto,
        'epss_score': v.epss_score, 'epss_percentile': v.epss_percentile, 'epss_date': _iso(v.epss_date),
        'kev': v.kev, 'kev_date_added': _iso(v.kev_date_added), 'kev_due_date': _iso(v.kev_due_date),
        'kev_ransomware': v.kev_ransomware, 'exploit_maturity': v.exploit_maturity,
        'patch_availability': v.patch_availability, 'cwes': list(v.cwes or []),
        'affected_products': list(v.affected_products or []), 'reference_urls': list(v.reference_urls or []),
        'aliases': list(v.aliases or []), 'published_at': _iso(v.published_at),
        'modified_at': _iso(v.modified_at), 'tlp_id': v.tlp_id,
        'tlp_name': v.tlp.tlp_name if v.tlp is not None else None,
        'tags': [t for t in (v.tags or '').split(',') if t], 'source': v.source,
        'enrichment': v.enrichment or {}, 'created_at': _iso(v.created_at), 'updated_at': _iso(v.updated_at),
        'created_by_id': v.created_by_id,
        'created_by_name': v.created_by.name if v.created_by is not None else None,
        'updated_by_id': v.updated_by_id,
        'updated_by_name': v.updated_by.name if v.updated_by is not None else None,
    }
    if counts is not None:
        d['counts'] = counts
    return d


_SORTS = {
    'identifier': func.upper(Vulnerability.identifier),
    'title': func.lower(Vulnerability.title),
    'severity': sa_case({s: r for s, r in vv.SEVERITY_RANK.items()}, value=Vulnerability.severity, else_=0),
    'cvss_score': Vulnerability.cvss_score,
    'epss_score': Vulnerability.epss_score,
    'updated_at': func.coalesce(Vulnerability.updated_at, Vulnerability.created_at),
}


def case_filter(args, viewer):
    """The list's `case_id` filter: None when absent, else the id of a case the
    viewer can open. A case the viewer cannot open answers like a case that does
    not exist (404), so the filter never tells that a case exists."""
    raw = args.get('case_id')
    if raw in (None, ''):
        return None
    try:
        case_id = int(raw)
    except (TypeError, ValueError):
        raise VulnError('case_id must be a number.')
    if not viewer.sees_case(case_id):
        raise VulnError('Case not found.', status=404)
    return case_id


def case_label(case_id):
    from app.models.cases import Cases
    c = db.session.get(Cases, case_id)
    return {'case_id': case_id, 'case_name': c.name if c else None}


def case_counts_for(vuln_ids, case_id):
    """{vulnerability_id: {'findings', 'open', 'assets'}} inside one case (the
    list's Exposure column while the case filter is on)."""
    out = {vid: {'findings': 0, 'open': 0, 'assets': 0} for vid in vuln_ids}
    if not vuln_ids:
        return out
    rows = (db.session.query(VulnerabilityFinding.vulnerability_id, VulnerabilityFinding.asset_id,
                             VulnerabilityFinding.remediation_status)
            .filter(VulnerabilityFinding.scope == 'case', VulnerabilityFinding.case_id == case_id,
                    VulnerabilityFinding.vulnerability_id.in_(list(vuln_ids))).all())
    assets = {}
    for vid, asset_id, status in rows:
        out[vid]['findings'] += 1
        if vv.status_group(status) == 'open':
            out[vid]['open'] += 1
        assets.setdefault(vid, set()).add(asset_id)
    for vid, s in assets.items():
        out[vid]['assets'] = len(s)
    return out


def cases_with_findings(viewer):
    """The cases the viewer can open that hold at least one finding, newest
    case first, with their finding / open counts - the list's Case filter."""
    from app.models.cases import Cases
    if not viewer.case_ids:
        return []
    rows = (db.session.query(VulnerabilityFinding.case_id, VulnerabilityFinding.remediation_status)
            .filter(VulnerabilityFinding.scope == 'case',
                    VulnerabilityFinding.case_id.in_(list(viewer.case_ids))).all())
    counts = {}
    for case_id, status in rows:
        c = counts.setdefault(case_id, {'findings': 0, 'open': 0})
        c['findings'] += 1
        if vv.status_group(status) == 'open':
            c['open'] += 1
    if not counts:
        return []
    names = {c.case_id: c.name for c in Cases.query.filter(Cases.case_id.in_(list(counts))).all()}
    return [{'case_id': cid, 'case_name': names.get(cid), 'findings': c['findings'], 'open': c['open']}
            for cid, c in sorted(counts.items(), key=lambda kv: -kv[0])]


def search_vulnerabilities(args, viewer, case_id=None):
    """(rows, total, page, per_page) for the catalogue list. `case_id` (already
    checked by case_filter) keeps the entries with a finding in that case; with
    `affected=true` as well, an OPEN finding in that case."""
    q = Vulnerability.query
    search = (args.get('search') or '').strip()
    if search:
        like = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        q = q.filter(or_(Vulnerability.identifier.ilike(like), Vulnerability.title.ilike(like),
                         Vulnerability.tags.ilike(like), cast(Vulnerability.aliases, Text).ilike(like),
                         cast(Vulnerability.affected_products, Text).ilike(like),
                         Vulnerability.description.ilike(like)))
    sev = [s for s in (args.get('severity') or '').split(',') if s in vv.SEVERITIES]
    if sev:
        q = q.filter(Vulnerability.severity.in_(sev))
    kinds = [k for k in (args.get('kind') or '').split(',') if k in vv.KINDS]
    if kinds:
        q = q.filter(Vulnerability.kind.in_(kinds))
    if args.get('vendor'):
        q = q.filter(Vulnerability.affected_products.contains([{'vendor': args['vendor']}]))
    if args.get('product'):
        q = q.filter(Vulnerability.affected_products.contains([{'product': args['product']}]))
    for key, col in (('kev', Vulnerability.kev), ('private', Vulnerability.is_private)):
        val = (args.get(key) or '').strip().lower()
        if val in ('true', 'false'):
            q = q.filter(col.is_(val == 'true'))
    affected = (args.get('affected') or '').lower() == 'true'
    if case_id is not None:
        in_case = db.session.query(VulnerabilityFinding.vulnerability_id).filter(
            VulnerabilityFinding.scope == 'case', VulnerabilityFinding.case_id == case_id)
        if affected:
            in_case = in_case.filter(VulnerabilityFinding.remediation_status.in_(vv.REMEDIATION_GROUPS['open']))
        q = q.filter(Vulnerability.vulnerability_id.in_(in_case))
    elif affected:
        cond, params = viewer.finding_filter()
        params['open_statuses'] = list(vv.REMEDIATION_GROUPS['open'])
        q = q.filter(text(
            "EXISTS (SELECT 1 FROM vulnerability_finding f LEFT JOIN customer_asset ca"
            " ON ca.id = f.customer_asset_id WHERE f.vulnerability_id = vulnerability.vulnerability_id"
            " AND f.remediation_status = ANY(:open_statuses) AND " + cond + ")").bindparams(**params))
    order = args.get('order_by') if args.get('order_by') in _SORTS else 'updated_at'
    direction = (args.get('sort_dir') or ('desc' if order in ('updated_at', 'severity', 'cvss_score',
                                                              'epss_score') else 'asc')).lower()
    col = _SORTS[order]
    col = col.desc().nulls_last() if direction == 'desc' else col.asc().nulls_last()
    q = q.order_by(col, Vulnerability.vulnerability_id.desc())
    try:
        page = max(1, int(args.get('page') or 1))
        per_page = min(MAX_PER_PAGE, max(1, int(args.get('per_page') or 25)))
    except ValueError:
        raise VulnError('page and per_page must be numbers.')
    total = q.order_by(None).count()
    rows = q.offset((page - 1) * per_page).limit(per_page).all()
    return rows, total, page, per_page


def technologies():
    rows = db.session.execute(text(
        "SELECT p->>'vendor' AS vendor, p->>'product' AS product, count(DISTINCT v.vulnerability_id)"
        " FROM vulnerability v, jsonb_array_elements(v.affected_products) p"
        " WHERE coalesce(p->>'product', '') <> ''"
        " GROUP BY 1, 2 ORDER BY lower(coalesce(p->>'vendor', '')), lower(p->>'product')")).all()
    return [{'vendor': r[0], 'product': r[1], 'vulnerabilities': r[2]} for r in rows]


def exposure(v, viewer):
    """Where this entry is recorded, limited to what the viewer may see."""
    from app.models.cases import Cases
    from app.models.models import CaseAssets
    from app.models.models import Client
    from app.models.models import CustomerAsset
    from app.models.models import Ioc
    from app.models.models import IocType
    today = date.today()
    cases, registry = {}, []
    findings = VulnerabilityFinding.query.filter_by(vulnerability_id=v.vulnerability_id).all()
    case_names = {}
    for f in findings:
        if f.scope == 'case' and viewer.sees_case(f.case_id):
            if f.case_id not in case_names:
                c = db.session.get(Cases, f.case_id)
                client = db.session.get(Client, c.client_id) if c is not None else None
                case_names[f.case_id] = (c.name if c else None, client.name if client else None)
            entry = cases.setdefault(f.case_id, {
                'case_id': f.case_id, 'case_name': case_names[f.case_id][0],
                'client_name': case_names[f.case_id][1], 'findings': [], 'open': 0, 'exploited': 0})
            asset = db.session.get(CaseAssets, f.asset_id) if f.asset_id else None
            grp = vv.status_group(f.remediation_status)
            entry['findings'].append({
                'finding_id': f.finding_id, 'asset_id': f.asset_id,
                'asset_name': asset.asset_name if asset else None,
                'remediation_status': f.remediation_status, 'status_group': grp,
                'exploitation_status': f.exploitation_status, 'due_date': _iso(f.due_date),
                'overdue': bool(f.due_date and f.due_date < today and grp == 'open')})
            entry['open'] += 1 if grp == 'open' else 0
            entry['exploited'] += 1 if f.exploitation_status == 'exploited' else 0
        elif f.scope == 'registry':
            ca = db.session.get(CustomerAsset, f.customer_asset_id)
            if ca is None or not viewer.sees_client(ca.customer_id):
                continue
            client = db.session.get(Client, ca.customer_id)
            grp = vv.status_group(f.remediation_status)
            registry.append({
                'finding_id': f.finding_id, 'customer_asset_id': ca.id, 'asset_name': ca.asset_name,
                'customer_id': ca.customer_id, 'customer_name': client.name if client else None,
                'criticality': ca.criticality, 'remediation_status': f.remediation_status,
                'status_group': grp, 'exploitation_status': f.exploitation_status,
                'due_date': _iso(f.due_date),
                'overdue': bool(f.due_date and f.due_date < today and grp == 'open')})

    idents = [v.identifier.upper()] + [a.upper() for a in (v.aliases or [])]
    mentions = []
    if viewer.case_ids:
        rows = (db.session.query(Ioc.ioc_id, Ioc.ioc_value, Ioc.case_id, Cases.name)
                .join(IocType, IocType.type_id == Ioc.ioc_type_id)
                .join(Cases, Cases.case_id == Ioc.case_id)
                .filter(func.lower(IocType.type_name) == 'vulnerability',
                        func.upper(func.trim(Ioc.ioc_value)).in_(idents),
                        Ioc.case_id.in_(list(viewer.case_ids)))
                .order_by(Ioc.case_id, Ioc.ioc_id).all())
        mentions = [{'ioc_id': r[0], 'ioc_value': r[1], 'case_id': r[2], 'case_name': r[3]} for r in rows]

    case_list = sorted(cases.values(), key=lambda c: c['case_id'])
    all_findings = [x for c in case_list for x in c['findings']] + registry
    return {
        'vulnerability_id': v.vulnerability_id, 'identifier': v.identifier,
        'cases': case_list, 'registry': registry, 'ioc_mentions': mentions,
        'totals': {
            'cases': len(case_list),
            'case_findings': sum(len(c['findings']) for c in case_list),
            'registry_assets': len(registry),
            'open': sum(1 for x in all_findings if x['status_group'] == 'open'),
            'exploited': sum(1 for x in all_findings if x['exploitation_status'] == 'exploited'),
            'ioc_cases': len({m['case_id'] for m in mentions}),
        },
    }


def resolve_values(values):
    """{UPPER(value): summary_row} for the values that name a catalogue entry
    (identifier or alias) - the IOC page's CVE links."""
    wanted = sorted({(x or '').strip().upper() for x in values if (x or '').strip()})[:500]
    if not wanted:
        return {}
    out = {}
    for v in Vulnerability.query.filter(or_(
            func.upper(Vulnerability.identifier).in_(wanted),
            text("EXISTS (SELECT 1 FROM jsonb_array_elements_text(vulnerability.aliases) a"
                 " WHERE upper(a) = ANY(:wanted))").bindparams(wanted=wanted))).all():
        for key in [v.identifier.upper()] + [a.upper() for a in (v.aliases or [])]:
            if key in wanted and key not in out:
                out[key] = summary_row(v)
    return out


def vocab():
    return vv.all_labels()


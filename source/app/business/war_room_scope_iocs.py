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

"""The war-room Scope's IOCs sub-tab (iris-ng 2026-11-08): every IOC of the attached cases THE VIEWER can open,
deduplicated - one row per indicator (type + the dedup key of iris_engine/utils/ioc_normalise.py) with the cases
holding it - and the copies: Add IOC (one IOC created in several attached cases), push (existing IOCs copied into
the cases missing them) and the export.

Export (decided 2026-11-08): txt (a blocklist, one value per line) and CSV carry every IOC except TLP:RED unless
include_red=1 asks for it - an IOC with no TLP is not RED and goes out; STIX 2.1 keeps the outbound gate of every
other export: TLP:GREEN / TLP:CLEAR only (no TLP = not shareable). A row's TLP is the most restrictive of its cases'.
The number of IOCs left out is returned (X-IRIS-TLP-Withheld).
"""
import csv
import io
import json
from datetime import datetime
from datetime import timezone

from app import db
from app.business.war_room_scope import ScopeError
from app.business.war_room_scope import _guard
from app.business.war_room_scope import _ids
from app.business.war_room_scope import _linked_targets
from app.business.war_room_scope import _tally
from app.business.war_room_scope import _writable
from app.business.war_room_scope import case_customers
from app.business.war_room_scope import case_result
from app.business.war_room_scope import check_cross_customer
from app.business.war_room_scope import clean_ioc_payload
from app.business.war_room_scope import create_in_case
from app.models import asset_flag_vocab as af


def _key(type_id, value):
    from app.iris_engine.utils.ioc_normalise import normalise_ioc_value
    norm = normalise_ioc_value(value) or (value or '').strip().lower()
    return '%s|%s' % (type_id, norm)


def ioc_groups(case_ids):
    """The IOCs of these cases grouped by indicator: [{key, ioc_value (the oldest row's), ioc_type_id, ioc_type,
    tlp_ids (one per row), cases: {case_id: ioc_id (the oldest)}, ioc_description, ioc_tags}], oldest first."""
    from app.models.models import Ioc
    from app.models.models import IocType
    if not case_ids:
        return []
    rows = (db.session.query(Ioc.ioc_id, Ioc.case_id, Ioc.ioc_value, Ioc.ioc_type_id, IocType.type_name,
                             Ioc.ioc_tlp_id, Ioc.ioc_description, Ioc.ioc_tags)
            .outerjoin(IocType, IocType.type_id == Ioc.ioc_type_id)
            .filter(Ioc.case_id.in_(list(case_ids))).order_by(Ioc.ioc_id).all())
    groups, order = {}, []
    for iid, cid, value, tid, tname, tlp, desc, tags in rows:
        k = _key(tid, value)
        g = groups.get(k)
        if g is None:
            g = groups[k] = {'key': k, 'ioc_value': value, 'ioc_type_id': tid, 'ioc_type': tname, 'tlp_ids': [],
                             'cases': {}, 'ioc_description': desc, 'ioc_tags': tags}
            order.append(k)
        g['tlp_ids'].append(tlp)
        g['cases'].setdefault(cid, iid)
    return [groups[k] for k in order]


def iocs_per_case(case_ids):
    """{case_id: distinct indicators} - the Customers sub-tab sums these."""
    out = {}
    for g in ioc_groups(case_ids):
        for cid in g['cases']:
            out[cid] = out.get(cid, 0) + 1
    return out


def _tlp(tlp_ids):
    from app.business.ioc_correlation import _most_restrictive_tlp
    tid, name = _most_restrictive_tlp(tlp_ids)
    return {'id': tid, 'name': name}


def scope_iocs(room, viewer_id, args):
    """GET .../scope/iocs?q=&case_id=&page=&per_page=: one row per indicator, with the cases holding it (case id ->
    IOC id), its most restrictive TLP and its customers; plus the case columns (the attached cases the viewer can
    open, whether they may change each) - a missing cell is a push target."""
    from app.business.war_room_scope import _int
    from app.business.war_rooms import room_case_ids
    from app.business.war_rooms import room_visible_case_ids
    from app.business import war_room_board as wb
    linked = room_case_ids(room.id)
    visible = room_visible_case_ids(room.id, viewer_id)
    q = (args.get('q') or '').strip().lower()[:200]
    case_id = _int(args, 'case_id')
    page = _int(args, 'page', 1, 1)
    per_page = _int(args, 'per_page', af.SCOPE_PER_PAGE, 1, af.SCOPE_PER_PAGE_MAX)
    customers = case_customers(visible)
    rows = []
    for g in ioc_groups(visible):
        if case_id is not None and case_id not in g['cases']:
            continue
        if q and q not in ' '.join(str(x or '') for x in (g['ioc_value'], g['ioc_type'], g['ioc_tags'],
                                                          g['ioc_description'])).lower():
            continue
        names = sorted({customers.get(c, (None, None))[1] or '' for c in g['cases']} - {''})
        rows.append({'key': g['key'], 'ioc_value': g['ioc_value'], 'ioc_type_id': g['ioc_type_id'],
                     'ioc_type': g['ioc_type'], 'tlp': _tlp(g['tlp_ids']), 'ioc_description': g['ioc_description'],
                     'ioc_tags': g['ioc_tags'], 'customers': names,
                     'cases': {str(c): i for c, i in g['cases'].items()}, 'present': len(g['cases'])})
    start = (page - 1) * per_page
    meta = wb._case_meta(visible)
    writable = _writable(viewer_id, visible)
    return {'iocs': rows[start:start + per_page], 'total': len(rows), 'page': page, 'per_page': per_page,
            'cases': [{'case_id': c, 'case_name': (meta.get(c) or (None,))[0],
                       'customer_name': customers.get(c, (None, None))[1], 'can_write': c in writable}
                      for c in sorted(visible)],
            'case_count': len(visible), 'cases_restricted': len([c for c in linked if c not in set(visible)])}


def create_iocs(room, user, body):
    """Add IOC: one IOC created in several attached cases at once - {ioc: {ioc_value, ioc_type_id, ioc_tlp_id,
    ioc_description, ioc_tags}, case_ids, confirm_cross_customer}. Through each case's own create path; a case that
    already holds the indicator (same type, same dedup key) is skipped. One result per case."""
    _guard(room)
    payload = clean_ioc_payload(body.get('ioc'))
    targets = _linked_targets(room, body.get('case_ids'))
    check_cross_customer(targets, body)
    writable = _writable(user.id, targets)
    results = []
    for cid in targets:
        if cid not in writable:
            results.append(case_result(cid, 'refused', 'You cannot change case #%d' % cid))
            continue
        status, oid, err = create_in_case('ioc', cid, payload)
        results.append(case_result(cid, status, err, ioc_id=oid))
    return {'results': results, 'counts': _tally(results)}


def push_iocs(room, user, body):
    """Copy IOCs into other attached cases: {ioc_ids, case_ids, confirm_cross_customer}. Copies value, type, TLP,
    description and tags through the case's own create path; never into the IOC's own case. One result per (IOC,
    target case): created / exists / refused."""
    from app.business.war_rooms import room_visible_case_ids
    from app.models.models import Ioc
    _guard(room)
    targets = _linked_targets(room, body.get('case_ids'))
    writable = _writable(user.id, targets)
    visible = set(room_visible_case_ids(room.id, user.id))
    ids = _ids(body.get('ioc_ids'), 'IOC', af.SCOPE_BULK_MAX)
    sources = {i.ioc_id: i for i in Ioc.query.filter(Ioc.ioc_id.in_(ids)).all() if i.case_id in visible}
    check_cross_customer({i.case_id for i in sources.values()} | set(targets), body)
    results = []
    for iid in ids:
        src = sources.get(iid)
        if src is None:
            results.append({'ioc_id': iid, 'ioc_value': None, 'case_id': None, 'status': 'refused',
                            'error': 'Not an IOC of this war room\'s cases you can open'})
            continue
        payload = {'ioc_value': src.ioc_value, 'ioc_type_id': src.ioc_type_id, 'ioc_tlp_id': src.ioc_tlp_id,
                   'ioc_description': src.ioc_description, 'ioc_tags': src.ioc_tags}
        for cid in targets:
            if cid == src.case_id:
                continue
            base = {'ioc_id': iid, 'ioc_value': src.ioc_value, 'case_id': src.case_id, 'target_case_id': cid}
            if cid not in writable:
                results.append(dict(base, status='refused', error='You cannot change case #%d' % cid))
                continue
            status, oid, err = create_in_case('ioc', cid, payload)
            results.append(dict(base, status=status, error=err, **({'new_ioc_id': oid} if status == 'created' else {})))
    return {'results': results, 'counts': _tally(results)}


# =========================================================================== export

def _export_rows(room, viewer_id):
    from app.business.war_rooms import room_visible_case_ids
    visible = room_visible_case_ids(room.id, viewer_id)
    customers = case_customers(visible)
    out = []
    for g in ioc_groups(visible):
        t = _tlp(g['tlp_ids'])
        out.append(dict(g, tlp=t, customers=sorted({customers.get(c, (None, None))[1] or '' for c in g['cases']} - {''})))
    return out, visible


def export_iocs(room, viewer_id, fmt, include_red):
    """Returns (body text, mimetype, filename, withheld count). Refused (400) when nothing is left to export."""
    from app.business.ioc_correlation import is_shareable_tlp
    if fmt not in af.SCOPE_EXPORT_FORMATS:
        raise ScopeError('format is one of %s.' % ', '.join(af.SCOPE_EXPORT_FORMATS))
    rows, visible = _export_rows(room, viewer_id)
    if fmt == 'stix':
        kept = [r for r in rows if is_shareable_tlp(r['tlp']['id'])]
        rule = 'Only TLP:GREEN and TLP:CLEAR go into STIX; an IOC with no TLP is not shareable.'
    else:
        kept = [r for r in rows if include_red or r['tlp']['id'] != af.SCOPE_TLP_RED]
        rule = 'TLP:RED IOCs are left out unless Include TLP:RED is ticked.'
    withheld = len(rows) - len(kept)
    if not kept:
        raise ScopeError('Nothing to export: %d IOC%s, %d left out. %s'
                         % (len(rows), '' if len(rows) == 1 else 's', withheld, rule),
                         data={'total': len(rows), 'withheld': withheld})
    stem = 'war-room-%d' % room.id
    if fmt == 'txt':
        seen, lines = set(), []
        for r in kept:
            if r['ioc_value'] not in seen:
                seen.add(r['ioc_value'])
                lines.append(r['ioc_value'].replace('\r', ' ').replace('\n', ' '))
        return '\n'.join(lines) + '\n', 'text/plain', stem + '-blocklist.txt', withheld
    if fmt == 'csv':
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator='\n')
        w.writerow(['value', 'type', 'tlp', 'description', 'tags', 'cases', 'customers'])
        for r in kept:
            w.writerow([r['ioc_value'], r['ioc_type'] or '', r['tlp']['name'], r['ioc_description'] or '',
                        r['ioc_tags'] or '', ' '.join('#%d' % c for c in sorted(r['cases'])), '; '.join(r['customers'])])
        return buf.getvalue(), 'text/csv', stem + '-iocs.csv', withheld
    return json.dumps(_stix(room, kept, visible), indent=2, ensure_ascii=False), 'application/json', \
        stem + '-iocs-stix21.json', withheld


def _stix(room, rows, visible):
    from app.iris_engine.stix_export import build_cluster_stix_bundle
    from app.models.cases import Cases
    meta = {c.case_id: {'open_date': c.open_date.isoformat() if c.open_date else None}
            for c in Cases.query.filter(Cases.case_id.in_(list(visible))).all()} if visible else {}
    pairs = [{'ioc_value': r['ioc_value'], 'ioc_type_name': r['ioc_type'] or 'unknown',
              'case_ids': sorted(r['cases']), 'case_count': len(r['cases'])} for r in rows]
    cluster = {'cluster_id': 'war-room-%d-scope' % room.id, 'case_ids': sorted(visible), 'shared_ioc_count': len(pairs),
               'suggested_campaign_tag': room.campaign_tag or 'campaign:war-room-%d' % room.id}
    narrative = {'suggested_name': room.name, 'narrative': room.summary} if room.summary else None
    return build_cluster_stix_bundle(cluster=cluster, pairs_for_cluster=pairs, case_meta=meta,
                                     now_utc=datetime.now(timezone.utc), narrative=narrative)

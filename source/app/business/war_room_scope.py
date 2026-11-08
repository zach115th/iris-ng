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

"""The war-room Scope tab (iris-ng 2026-11-07; a workspace since 2026-11-08): every asset of the attached
cases THE VIEWER can open, with its type, IP, customer, compromise and analysis status, flags, linked IOCs, open
findings and last update, filtered and paged by the server; and changes made over a selection - flags set or
removed, the compromise or analysis status set, a vulnerability recorded, assets pushed (copied) to other attached
cases. Add asset creates one asset in several attached cases at once; the Customers sub-tab sums the scope per
customer. The IOCs sub-tab and the export are war_room_scope_iocs.py; the staging inbox and the Assets Manager
attachments are war_room_scope_staging.py; the shared rules for copies (payload checks, the per-case create, the
cross-customer confirmation) live here.

A copy that spans several customers (a push, an add to several cases, a staged object or a registry asset pushed
into another customer's case) is refused with 409 / data.code = cross_customer, naming the customers, until the
request carries confirm_cross_customer: true.

Membership never grants case access: a user sees the assets of the attached cases their case ACL lets them read
(a count of the others), and changes only the assets of cases they hold FULL access to - every other one comes
back refused, one result per asset, so a selection spanning cases partly succeeds. Guests never get the tab.

Filters (query string): q (name, IP, domain, type, tags), case_id, customer_id, compromised=1,
flag=<flag id>|none, kind=status|done|exception (holds a flag of that kind),
vulnerable=open|exploited|kev|overdue|none, vuln=<identifier> (an open finding of it); sort=case|name|findings|
compromise|updated, dir=asc|desc; page, per_page.
"""
from datetime import datetime

from sqlalchemy import func

from app import db
from app.business import war_room_board as wb
from app.models import asset_flag_vocab as af
from app.models.models import AssetFlag

COMPROMISE = {0: 'to_be_determined', 1: 'compromised', 2: 'not_compromised', 3: 'unknown'}
COMPROMISE_ID = {v: k for k, v in COMPROMISE.items()}


class ScopeError(Exception):
    def __init__(self, message, status=400, data=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.data = data


def _int(args, key, default=None, minimum=None, maximum=None):
    raw = args.get(key)
    if raw in (None, ''):
        return default
    if not str(raw).isdigit():
        raise ScopeError('%s must be a whole number.' % key)
    v = int(raw)
    if minimum is not None and v < minimum:
        raise ScopeError('%s is %d at least.' % (key, minimum))
    if maximum is not None and v > maximum:
        v = maximum
    return v


def parse_filters(args):
    """The query string -> clean filters; 400 on a malformed value."""
    f = {'q': (args.get('q') or '').strip().lower()[:200] or None,
         'case_id': _int(args, 'case_id'), 'customer_id': _int(args, 'customer_id'),
         'compromised': None, 'flag': None, 'kind': None, 'vulnerable': None,
         'vuln': (args.get('vuln') or '').strip().upper()[:64] or None,
         'sort': args.get('sort') or 'case', 'dir': args.get('dir') or 'asc',
         'page': _int(args, 'page', 1, 1), 'per_page': _int(args, 'per_page', af.SCOPE_PER_PAGE, 1,
                                                          af.SCOPE_PER_PAGE_MAX)}
    comp = args.get('compromised')
    if comp not in (None, ''):
        if comp != '1':
            raise ScopeError('compromised takes 1.')
        f['compromised'] = True
    flag = args.get('flag')
    if flag not in (None, ''):
        if flag == 'none':
            f['flag'] = 'none'
        elif str(flag).isdigit():
            f['flag'] = int(flag)
        else:
            raise ScopeError('flag is a flag id or none.')
    kind = args.get('kind')
    if kind not in (None, ''):
        if kind not in af.SCOPE_KINDS:
            raise ScopeError('kind is one of %s.' % ', '.join(af.SCOPE_KINDS))
        f['kind'] = kind
    vul = args.get('vulnerable')
    if vul not in (None, ''):
        if vul not in af.SCOPE_VULNERABLE:
            raise ScopeError('vulnerable is one of %s.' % ', '.join(af.SCOPE_VULNERABLE))
        f['vulnerable'] = vul
    if f['sort'] not in af.SCOPE_SORTS:
        raise ScopeError('sort is one of %s.' % ', '.join(af.SCOPE_SORTS))
    if f['dir'] not in ('asc', 'desc'):
        raise ScopeError('dir is asc or desc.')
    return f


def _keep(r, f):
    if f['case_id'] is not None and r['case_id'] != f['case_id']:
        return False
    if f['customer_id'] is not None and r['customer_id'] != f['customer_id']:
        return False
    if f['compromised'] and r['compromise'] != 'compromised':
        return False
    if f['flag'] == 'none' and r['flags']:
        return False
    if isinstance(f['flag'], int) and not any(x['flag_id'] == f['flag'] for x in r['flags']):
        return False
    if f['kind'] and not any(x['kind'] == f['kind'] for x in r['flags']):
        return False
    v = r['findings']
    if f['vulnerable'] == 'open' and not v['open']:
        return False
    if f['vulnerable'] == 'exploited' and not v['exploited_open']:
        return False
    if f['vulnerable'] == 'kev' and not v['kev_open']:
        return False
    if f['vulnerable'] == 'overdue' and not v['overdue']:
        return False
    if f['vulnerable'] == 'none' and v['open']:
        return False
    if f['vuln'] and f['vuln'] not in [i.upper() for i in r['vulns']]:
        return False
    if f['q']:
        hay = ' '.join(str(x or '') for x in (r['asset_name'], r['asset_ip'], r['asset_domain'], r['asset_type'],
                                              r['asset_tags'])).lower()
        if f['q'] not in hay:
            return False
    return True


_SORT = {
    'case': lambda r: (r['case_id'], (r['asset_name'] or '').lower(), r['asset_id']),
    'name': lambda r: ((r['asset_name'] or '').lower(), r['case_id'], r['asset_id']),
    'findings': lambda r: (r['findings']['exploited_open'], r['findings']['open'], -r['asset_id']),
    'compromise': lambda r: (r['compromise'] == 'compromised', not r['flags'], -r['asset_id']),
    'updated': lambda r: (r['updated_at'] or '', r['asset_id']),
}


def _iso(dt):
    return dt.isoformat() + 'Z' if dt else None


def _rows_of(case_ids):
    """Every column the table shows, one query (+ customers, IOC counts)."""
    from app.models.cases import Cases
    from app.models.models import AnalysisStatus
    from app.models.models import AssetsType
    from app.models.models import CaseAssets
    from app.models.models import Client
    from app.models.models import IocAssetLink
    if not case_ids:
        return [], {}, {}
    rows = (db.session.query(CaseAssets.asset_id, CaseAssets.asset_name, CaseAssets.case_id,
                             CaseAssets.asset_compromise_status_id, AssetsType.asset_name, CaseAssets.asset_ip,
                             CaseAssets.asset_domain, CaseAssets.asset_tags, CaseAssets.analysis_status_id,
                             AnalysisStatus.name, CaseAssets.date_update, CaseAssets.date_added)
            .outerjoin(AssetsType, AssetsType.asset_id == CaseAssets.asset_type_id)
            .outerjoin(AnalysisStatus, AnalysisStatus.id == CaseAssets.analysis_status_id)
            .filter(CaseAssets.case_id.in_(case_ids)).all())
    customers = {cid: (client_id, name) for cid, client_id, name in
                 db.session.query(Cases.case_id, Cases.client_id, Client.name)
                 .outerjoin(Client, Client.client_id == Cases.client_id)
                 .filter(Cases.case_id.in_(case_ids)).all()}
    ids = [r[0] for r in rows]
    iocs = dict(db.session.query(IocAssetLink.asset_id, func.count(func.distinct(IocAssetLink.ioc_id)))
                .filter(IocAssetLink.asset_id.in_(ids)).group_by(IocAssetLink.asset_id).all()) if ids else {}
    return rows, customers, iocs


def _writable(user_id, case_ids):
    from app.iris_engine.access_control.utils import ac_fast_check_user_has_case_access
    from app.models.authorization import CaseAccessLevel
    return {c for c in case_ids if user_id and ac_fast_check_user_has_case_access(user_id, c,
                                                                                   [CaseAccessLevel.full_access])}


def _build_rows(visible, viewer_id):
    """Every asset row of the cases `visible`, with the columns the table shows; and per asset the open
    vulnerability identifiers. Returns (rows, case meta, {case_id: (customer_id, name)}, writable case ids,
    {asset_id: [identifiers]})."""
    from app.business import war_room_decisions as wd
    from app.models.models import WarRoomDecision
    meta = wb._case_meta(visible)
    assets, customers, iocs = _rows_of(visible)
    writable = _writable(viewer_id, visible)
    fl_of = wb.flags_by_asset([a[0] for a in assets])
    dids = {did for fl in fl_of.values() for _, _, did in fl if did is not None}
    refs = {d.id: wd.ref(d) for d in WarRoomDecision.query.filter(WarRoomDecision.id.in_(dids))} if dids else {}
    per_asset, idents = {}, {}
    for fid, cid, aid, ident, exploited, overdue, kev in wb.open_findings(visible):
        v = per_asset.setdefault(aid, {'open': 0, 'exploited_open': 0, 'kev_open': 0, 'overdue': 0})
        v['open'] += 1
        v['exploited_open'] += exploited
        v['kev_open'] += kev
        v['overdue'] += overdue
        if ident and ident not in idents.setdefault(aid, []):
            idents[aid].append(ident)
    rows = []
    for aid, name, cid, comp, typ, ip, domain, tags, an_id, an_name, upd, added in assets:
        fl = fl_of.get(aid, [])
        cust = customers.get(cid, (None, None))
        rows.append({
            'asset_id': aid, 'asset_name': name, 'asset_type': typ, 'asset_ip': ip, 'asset_domain': domain,
            'asset_tags': tags, 'case_id': cid, 'case_name': (meta.get(cid) or (None,))[0],
            'customer_id': cust[0], 'customer_name': cust[1],
            'compromise': COMPROMISE.get(comp), 'analysis_status_id': an_id, 'analysis': an_name,
            'flags': [{'flag_id': x.id, 'name': x.name, 'color': x.color, 'icon': x.icon, 'kind': x.kind,
                       'reason': reason, 'decision_id': did, 'decision_ref': refs.get(did)} for x, reason, did in fl],
            'findings': per_asset.get(aid, {'open': 0, 'exploited_open': 0, 'kev_open': 0, 'overdue': 0}),
            'vulns': sorted(idents.get(aid, [])), 'ioc_count': iocs.get(aid, 0),
            'updated_at': _iso(upd or added), 'can_write': cid in writable,
            'href': '/case/assets?cid=%d&asset=%d&tab=details' % (cid, aid),
            'vulns_href': '/case/assets?cid=%d&asset=%d&tab=vulns' % (cid, aid),
        })
    return rows, meta, customers, writable, idents


def scope_assets(room, viewer_id, args):
    from app.business.war_rooms import room_case_ids
    from app.business.war_rooms import room_visible_case_ids
    from app.models.models import AnalysisStatus
    f = parse_filters(args)
    linked = room_case_ids(room.id)
    visible = room_visible_case_ids(room.id, viewer_id)
    rows, meta, customers, writable, idents = _build_rows(visible, viewer_id)
    by_flag = {}
    for r in rows:
        for x in r['flags']:
            by_flag[x['flag_id']] = by_flag.get(x['flag_id'], 0) + 1
    by_customer = {}
    for r in rows:
        if r['customer_id'] is not None:
            c = by_customer.setdefault(r['customer_id'], {'customer_id': r['customer_id'], 'name': r['customer_name'],
                                                         'assets': 0})
            c['assets'] += 1
    summary = {
        'assets': len(rows),
        'compromised': sum(1 for r in rows if r['compromise'] == 'compromised'),
        'unflagged': sum(1 for r in rows if r['compromise'] == 'compromised' and not r['flags']),
        'no_flag': sum(1 for r in rows if not r['flags']),
        'done': sum(1 for r in rows if any(x['kind'] == 'done' for x in r['flags'])),
        'exceptions': sum(1 for r in rows if any(x['kind'] == 'exception' for x in r['flags'])),
        'vulnerable': sum(1 for r in rows if r['findings']['open']),
        'exploited': sum(1 for r in rows if r['findings']['exploited_open']),
        'kev': sum(1 for r in rows if r['findings']['kev_open']),
        'overdue': sum(1 for r in rows if r['findings']['overdue']),
    }
    kept = [r for r in rows if _keep(r, f)]
    kept.sort(key=_SORT[f['sort']], reverse=f['dir'] == 'desc')
    start = (f['page'] - 1) * f['per_page']
    catalogue = AssetFlag.query.order_by(AssetFlag.sort_order, AssetFlag.id).all()
    return {
        'assets': kept[start:start + f['per_page']],
        'total': len(kept),
        'page': f['page'], 'per_page': f['per_page'],
        'filters': {k: f[k] for k in ('q', 'case_id', 'customer_id', 'compromised', 'flag', 'kind', 'vulnerable',
                                      'vuln', 'sort', 'dir')},
        'summary': summary,
        'flags': [{'flag_id': x.id, 'name': x.name, 'color': x.color, 'icon': x.icon, 'kind': x.kind,
                   'description': x.description, 'requires_reason': bool(x.requires_reason),
                   'requires_decision': bool(x.requires_decision), 'assets': by_flag.get(x.id, 0)} for x in catalogue],
        'cases': [{'case_id': c, 'case_name': (meta.get(c) or (None,))[0],
                   'customer_name': customers.get(c, (None, None))[1], 'can_write': c in writable}
                  for c in sorted(visible)],
        'customers': sorted(by_customer.values(), key=lambda c: (c['name'] or '').lower()),
        'identifiers': sorted({i for ids in idents.values() for i in ids}),
        'analysis_statuses': [{'id': a.id, 'name': a.name} for a in AnalysisStatus.query.order_by(AnalysisStatus.id)],
        'compromise_statuses': [{'key': k, 'label': lbl} for k, lbl in af.SCOPE_COMPROMISE],
        'case_count': len(visible),
        'cases_restricted': len([c for c in linked if c not in set(visible)]),
    }


# =========================================================================== changes over a selection

def _ids(raw, what, cap):
    if not isinstance(raw, list) or not raw:
        raise ScopeError('Pick at least one %s.' % what)
    out = []
    for v in raw:
        if isinstance(v, bool) or not isinstance(v, (int, str)) or not str(v).isdigit():
            raise ScopeError('%s ids are whole numbers.' % what.capitalize())
        if int(v) not in out:
            out.append(int(v))
    if len(out) > cap:
        raise ScopeError('At most %d %ss at once.' % (cap, what))
    return out


def _guard(room):
    from app.business.war_rooms import _assert_writable
    from app.business.errors import BusinessProcessingError
    try:
        _assert_writable(room)
    except BusinessProcessingError as e:
        raise ScopeError(e.get_message())


def _targets(room, user_id, raw_ids):
    """The selected assets: (asset or None, refusal) per id, in the order given. An asset outside the room's
    attached cases or in a case the user cannot change is refused."""
    from app.business.war_rooms import room_case_ids
    from app.models.models import CaseAssets
    linked = set(room_case_ids(room.id))
    ids = _ids(raw_ids, 'asset', af.SCOPE_BULK_MAX)
    assets = {a.asset_id: a for a in CaseAssets.query.filter(CaseAssets.asset_id.in_(ids)).all()}
    writable = _writable(user_id, {a.case_id for a in assets.values() if a.case_id in linked})
    out = []
    for aid in ids:
        a = assets.get(aid)
        if a is None or a.case_id not in linked:
            out.append((aid, None, 'Not an asset of this war room\'s cases'))
        elif a.case_id not in writable:
            out.append((aid, None, 'You cannot change case #%d' % a.case_id))
        else:
            out.append((aid, a, None))
    return out


def _result(aid, asset, status, error=None, **extra):
    r = {'asset_id': aid, 'asset_name': asset.asset_name if asset is not None else None,
         'case_id': asset.case_id if asset is not None else None, 'status': status, 'error': error}
    r.update(extra)
    return r


def _tally(results):
    out = {}
    for r in results:
        out[r['status']] = out.get(r['status'], 0) + 1
    return out


# =========================================================================== copies across cases
# Shared by the asset push, Add asset / Add IOC, the IOC push, the staging inbox and the Assets Manager.

def _linked_targets(room, raw):
    """The target cases a copy names: attached to the room, at most SCOPE_PUSH_CASES_MAX."""
    from app.business.war_rooms import room_case_ids
    linked = set(room_case_ids(room.id))
    targets = _ids(raw, 'case', af.SCOPE_PUSH_CASES_MAX)
    bad = [c for c in targets if c not in linked]
    if bad:
        raise ScopeError('Case #%d is not attached to this war room.' % bad[0])
    return targets


def case_customers(case_ids):
    """{case_id: (customer_id, customer name)} of the given cases."""
    from app.models.cases import Cases
    from app.models.models import Client
    ids = sorted({int(c) for c in case_ids if c is not None})
    if not ids:
        return {}
    rows = (db.session.query(Cases.case_id, Cases.client_id, Client.name)
            .outerjoin(Client, Client.client_id == Cases.client_id).filter(Cases.case_id.in_(ids)).all())
    return {cid: (client_id, name) for cid, client_id, name in rows}


def check_cross_customer(case_ids, body, extra=None):
    """Refuses a copy that spans several customers - 409, data {code: cross_customer, customers: [names]} - unless
    the request says it was confirmed (confirm_cross_customer: true). `extra` = {customer_id: name} of customers
    that are not a case's (a registry asset's own customer)."""
    names = {}
    for client_id, name in case_customers(case_ids).values():
        names[client_id] = name
    for client_id, name in (extra or {}).items():
        names[client_id] = name
    if len(names) > 1 and body.get('confirm_cross_customer') is not True:
        listed = sorted((n or 'Customer #%s' % k) for k, n in names.items())
        raise ScopeError('This spans %d customers (%s). Make sure the data may be shared between them, then confirm.'
                         % (len(listed), ', '.join(listed)), status=409,
                         data={'code': 'cross_customer', 'customers': listed})


def _text(raw, key, cap):
    v = raw.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ScopeError('%s is text.' % key)
    v = v.strip()
    if len(v) > cap:
        raise ScopeError('%s is %d characters at most.' % (key, cap))
    return v or None


def _ref(raw, key, model, what, required=True):
    v = raw.get(key)
    if v in (None, ''):
        if required:
            raise ScopeError('Pick %s.' % what)
        return None
    if isinstance(v, bool) or not str(v).isdigit() or db.session.get(model, int(v)) is None:
        raise ScopeError('Unknown %s.' % what.split(' ', 1)[-1])
    return int(v)


_ASSET_TEXT = (('asset_description', 20000), ('asset_ip', 255), ('asset_domain', 255), ('asset_tags', 1024))
_IOC_TEXT = (('ioc_description', 20000), ('ioc_tags', 1024))


def clean_asset_payload(raw):
    """The fields a case asset is created from, checked: a name, an asset type; description, IP, domain, tags;
    compromise status (0 to be determined by default) and analysis status (Unspecified by default)."""
    from app.datamgmt.case.case_assets_db import get_unspecified_analysis_status_id
    from app.models.models import AnalysisStatus
    from app.models.models import AssetsType
    if not isinstance(raw, dict):
        raise ScopeError('asset is an object.')
    name = raw.get('asset_name')
    if not isinstance(name, str) or not name.strip():
        raise ScopeError('Name the asset.')
    if len(name.strip()) > 512:
        raise ScopeError('asset_name is 512 characters at most.')
    out = {'asset_name': name.strip(), 'asset_type_id': _ref(raw, 'asset_type_id', AssetsType, 'an asset type')}
    for key, cap in _ASSET_TEXT:
        out[key] = _text(raw, key, cap)
    comp = raw.get('asset_compromise_status_id')
    if comp in (None, ''):
        comp = 0
    if isinstance(comp, bool) or not str(comp).isdigit() or int(comp) not in COMPROMISE:
        raise ScopeError('asset_compromise_status_id is one of %s.' % ', '.join(str(k) for k in sorted(COMPROMISE)))
    out['asset_compromise_status_id'] = int(comp)
    an = _ref(raw, 'analysis_status_id', AnalysisStatus, 'an analysis status', required=False)
    out['analysis_status_id'] = an if an is not None else get_unspecified_analysis_status_id()
    return out


def clean_ioc_payload(raw):
    """The fields a case IOC is created from, checked: a value, an IOC type, a TLP; description and tags."""
    from app.models.models import IocType
    from app.models.models import Tlp
    if not isinstance(raw, dict):
        raise ScopeError('ioc is an object.')
    value = raw.get('ioc_value')
    if not isinstance(value, str) or not value.strip():
        raise ScopeError('Give the IOC value.')
    if len(value.strip()) > 4096:
        raise ScopeError('ioc_value is 4096 characters at most.')
    out = {'ioc_value': value.strip(), 'ioc_type_id': _ref(raw, 'ioc_type_id', IocType, 'an IOC type'),
           'ioc_tlp_id': _ref(raw, 'ioc_tlp_id', Tlp, 'a TLP')}
    for key, cap in _IOC_TEXT:
        out[key] = _text(raw, key, cap)
    return out


def asset_in_case(case_id, payload):
    """The case's asset with this name (any letter case) and type - the case's own duplicate rule - or None."""
    from app.models.models import CaseAssets
    return (CaseAssets.query.filter(CaseAssets.case_id == case_id,
                                    func.lower(CaseAssets.asset_name) == payload['asset_name'].lower(),
                                    CaseAssets.asset_type_id == payload['asset_type_id'])
            .order_by(CaseAssets.asset_id).first())


def ioc_in_case(case_id, payload):
    """The case's IOC that is the same indicator (type + normalised value, the dedup key) - or None."""
    from app.datamgmt.case.case_iocs_db import find_existing_ioc
    return find_existing_ioc(case_id, payload['ioc_type_id'], payload['ioc_value'])


def present_in(kind, case_id, payload):
    return (asset_in_case(case_id, payload) if kind == 'asset' else ioc_in_case(case_id, payload)) is not None


def create_in_case(kind, case_id, payload):
    """Creates an asset or an IOC in the case through the case's own create path (hooks, history, the case
    activity). Returns (status, object id, error): created / exists (the case holds it already) / refused."""
    from app.business.assets import assets_create
    from app.business.errors import BusinessProcessingError
    from app.business.iocs import iocs_create
    found = asset_in_case(case_id, payload) if kind == 'asset' else ioc_in_case(case_id, payload)
    if found is not None:
        return 'exists', (found.asset_id if kind == 'asset' else found.ioc_id), None
    data = {k: v for k, v in payload.items() if v is not None}
    try:
        if kind == 'asset':
            _, created = assets_create(case_id, data)
            return 'created', created.asset_id, None
        created, _ = iocs_create(data, case_id)
        return 'created', created.ioc_id, None
    except BusinessProcessingError as e:
        db.session.rollback()
        msg = e.get_message() or 'The case refused it.'
        if 'already exists' in msg:
            return 'exists', None, None
        return 'refused', None, msg


def case_result(case_id, status, error=None, **extra):
    r = {'case_id': case_id, 'status': status, 'error': error}
    r.update(extra)
    return r


def bulk_flags(room, user, is_admin, body):
    """Set or remove flags on the selected assets: {asset_ids, flag_ids, action: set|remove, reason, decision_id}.
    One result per (asset, flag): set / updated / unchanged / cleared / not_set / refused."""
    from app.business import asset_flags as fl
    from app.business.asset_flags import FlagError
    from app.iris_engine.utils.tracker import track_activity
    _guard(room)
    action = body.get('action')
    if action not in ('set', 'remove'):
        raise ScopeError('action is set or remove.')
    flag_ids = _ids(body.get('flag_ids'), 'flag', 50)
    flags = {f.id: f for f in AssetFlag.query.filter(AssetFlag.id.in_(flag_ids)).all()}
    if len(flags) != len(flag_ids):
        raise ScopeError('A picked flag does not exist.', status=404)
    results, changes = [], []
    for aid, asset, refused in _targets(room, user.id, body.get('asset_ids')):
        if refused:
            results.append(_result(aid, None, 'refused', refused))
            continue
        for fid in flag_ids:
            flag = flags[fid]
            sp = db.session.begin_nested()
            try:
                if action == 'set':
                    row, act = fl.set_flag(asset.case_id, asset, flag, body, user, is_admin)
                    status, reason = act or 'unchanged', row.get('reason')
                else:
                    fl.clear_flag(asset.case_id, asset, flag, body, user)
                    status, act, reason = 'cleared', 'cleared', (body.get('reason') or '').strip() or None
                sp.commit()
            except FlagError as e:
                sp.rollback()
                results.append(_result(aid, asset, 'not_set' if e.status == 404 else 'refused', e.message, flag_id=fid))
                continue
            results.append(_result(aid, asset, status, flag_id=fid))
            if status != 'unchanged':
                changes.append((asset.case_id, fl.activity_text(flag, asset.asset_name, act, reason)))
    db.session.commit()
    for cid, text in changes:
        track_activity(text, caseid=cid)
    return {'results': results, 'counts': _tally(results)}


_ASSET_FIELDS = ('asset_name', 'asset_type_id', 'asset_description', 'asset_domain', 'asset_ip', 'asset_info',
                 'asset_compromise_status_id', 'asset_tags', 'analysis_status_id')


def _payload(asset):
    return {k: getattr(asset, k) for k in _ASSET_FIELDS}


def bulk_status(room, user, body):
    """Set the compromise status and / or the analysis status of the selected assets:
    {asset_ids, compromise: <key>, analysis_status_id: <id>}. Through the assets' own update path (hooks, history,
    the registry sync). One result per asset: changed / unchanged / refused."""
    from app.business.assets import assets_update
    from app.business.errors import BusinessProcessingError
    from app.models.models import AnalysisStatus
    _guard(room)
    comp = body.get('compromise')
    if comp is not None and comp not in COMPROMISE_ID:
        raise ScopeError('compromise is one of %s.' % ', '.join(COMPROMISE_ID))
    an = body.get('analysis_status_id')
    if an is not None:
        if isinstance(an, bool) or not str(an).isdigit() or db.session.get(AnalysisStatus, int(an)) is None:
            raise ScopeError('analysis_status_id is not an analysis status.')
        an = int(an)
    if comp is None and an is None:
        raise ScopeError('Set a compromise status, an analysis status or both.')
    results = []
    for aid, asset, refused in _targets(room, user.id, body.get('asset_ids')):
        if refused:
            results.append(_result(aid, None, 'refused', refused))
            continue
        want = {}
        if comp is not None and asset.asset_compromise_status_id != COMPROMISE_ID[comp]:
            want['asset_compromise_status_id'] = COMPROMISE_ID[comp]
        if an is not None and asset.analysis_status_id != an:
            want['analysis_status_id'] = an
        if not want:
            results.append(_result(aid, asset, 'unchanged'))
            continue
        payload = _payload(asset)
        payload.update(want)
        try:
            assets_update(asset, payload)
            results.append(_result(aid, asset, 'changed'))
        except BusinessProcessingError as e:
            db.session.rollback()
            results.append(_result(aid, asset, 'refused', e.get_message()))
    return {'results': results, 'counts': _tally(results)}


_PUSH_FIELDS = ('asset_name', 'asset_type_id', 'asset_description', 'asset_domain', 'asset_ip', 'asset_tags',
                'asset_compromise_status_id', 'analysis_status_id')


def bulk_push(room, user, body):
    """Copy the selected assets into other attached cases: {asset_ids, case_ids, confirm_cross_customer}. Copies
    name, type, description, IP, domain, tags, compromise and analysis status (never the flags), through the case's
    own create path. One result per (asset, target case): created / exists / refused."""
    from app.business.war_rooms import room_visible_case_ids
    from app.models.models import CaseAssets
    _guard(room)
    targets = _linked_targets(room, body.get('case_ids'))
    writable = _writable(user.id, targets)
    visible = set(room_visible_case_ids(room.id, user.id))
    ids = _ids(body.get('asset_ids'), 'asset', af.SCOPE_BULK_MAX)
    sources = {a.asset_id: a for a in CaseAssets.query.filter(CaseAssets.asset_id.in_(ids)).all()}
    usable = {aid: a for aid, a in sources.items() if a.case_id in visible}
    check_cross_customer({a.case_id for a in usable.values()} | set(targets), body)
    results = []
    for aid in ids:
        src = usable.get(aid)
        if src is None:
            results.append(_result(aid, None, 'refused', 'Not an asset of this war room\'s cases you can open'))
            continue
        payload = {k: getattr(src, k) for k in _PUSH_FIELDS}
        for cid in targets:
            if cid == src.case_id:
                continue
            if cid not in writable:
                results.append(_result(aid, src, 'refused', 'You cannot change case #%d' % cid, target_case_id=cid))
                continue
            status, oid, err = create_in_case('asset', cid, payload)
            extra = {'new_asset_id': oid} if status == 'created' else {}
            results.append(_result(aid, src, status, err, target_case_id=cid, **extra))
    return {'results': results, 'counts': _tally(results), 'at': _iso(datetime.utcnow())}


def create_assets(room, user, is_admin, body):
    """Add asset: one asset created in several attached cases at once - {asset: {...}, case_ids, flag_ids, reason,
    decision_id, confirm_cross_customer}. Through each case's own create path; a case that already holds it is
    skipped (exists); the initial flags are set on every asset created (a flag refused there is reported, the asset
    stays). One result per case: created / exists / refused."""
    from app.business import asset_flags as fl
    from app.business.asset_flags import FlagError
    from app.iris_engine.utils.tracker import track_activity
    from app.models.models import CaseAssets
    _guard(room)
    payload = clean_asset_payload(body.get('asset'))
    targets = _linked_targets(room, body.get('case_ids'))
    flag_ids = _ids(body.get('flag_ids'), 'flag', 50) if body.get('flag_ids') else []
    flags = {f.id: f for f in AssetFlag.query.filter(AssetFlag.id.in_(flag_ids)).all()} if flag_ids else {}
    if len(flags) != len(flag_ids):
        raise ScopeError('A picked flag does not exist.', status=404)
    if any(f.requires_reason for f in flags.values()) and not (body.get('reason') or '').strip():
        raise ScopeError('A picked flag requires a reason.')
    check_cross_customer(targets, body)
    writable = _writable(user.id, targets)
    results, changes = [], []
    for cid in targets:
        if cid not in writable:
            results.append(case_result(cid, 'refused', 'You cannot change case #%d' % cid))
            continue
        status, oid, err = create_in_case('asset', cid, payload)
        r = case_result(cid, status, err, asset_id=oid)
        if status == 'created' and flag_ids:
            asset = db.session.get(CaseAssets, oid)
            r['flags'] = []
            for fid in flag_ids:
                sp = db.session.begin_nested()
                try:
                    row, act = fl.set_flag(cid, asset, flags[fid], body, user, is_admin)
                    sp.commit()
                except FlagError as e:
                    sp.rollback()
                    r['flags'].append({'flag_id': fid, 'status': 'refused', 'error': e.message})
                    continue
                r['flags'].append({'flag_id': fid, 'status': act or 'unchanged'})
                changes.append((cid, fl.activity_text(flags[fid], asset.asset_name, act, row.get('reason'))))
            db.session.commit()
        results.append(r)
    for cid, text in changes:
        track_activity(text, caseid=cid)
    return {'results': results, 'counts': _tally(results)}


def record_vulnerability(room, user, is_admin, body):
    """Record one vulnerability on the selected assets: {asset_ids, vulnerability_id | quick: {identifier, title},
    remediation_status, ...the finding's fields}. A case finding per asset through the finding rules (an asset in a
    case the user cannot change is refused; one already carrying it is 'exists'). Nothing is resolved - and no
    quick-add entry is created - when every asset is refused."""
    from app.business import vulnerability_findings as fb
    from app.business.vulnerabilities import VulnError
    from app.iris_engine.utils.tracker import track_activity
    _guard(room)
    targets = _targets(room, user.id, body.get('asset_ids'))
    results = [_result(aid, None, 'refused', refused) for aid, asset, refused in targets if refused]
    accepted = [(aid, asset) for aid, asset, refused in targets if not refused]
    if not accepted:
        return {'results': results, 'counts': _tally(results), 'vulnerability': None}
    fields = {k: v for k, v in body.items() if k not in ('asset_ids', 'asset_id', 'csrf_token')}
    try:
        v = fb.resolve_vulnerability(fields, user.id)
    except VulnError as e:
        db.session.rollback()
        raise ScopeError(e.message, status=e.status)
    fields['vulnerability_id'] = v.vulnerability_id
    fields.pop('quick', None)
    done = []
    for aid, asset in accepted:
        sp = db.session.begin_nested()
        try:
            f = fb.create_finding('case', dict(fields, asset_id=aid), user.id, case_id=asset.case_id,
                                  is_admin=is_admin)
            sp.commit()
        except VulnError as e:
            sp.rollback()
            extra = {'finding_id': (e.data or {}).get('existing_finding_id')} if e.status == 409 else {}
            results.append(_result(aid, asset, 'exists' if e.status == 409 else 'refused', e.message, **extra))
            continue
        results.append(_result(aid, asset, 'created', finding_id=f.finding_id))
        done.append((asset.case_id, asset.asset_name))
    db.session.commit()
    for cid, name in done:
        track_activity("recorded vulnerability %s on asset '%s'" % (v.identifier, name), caseid=cid)
    return {'results': results, 'counts': _tally(results),
            'vulnerability': {'vulnerability_id': v.vulnerability_id, 'identifier': v.identifier}}


# =========================================================================== customers, counts, vocabulary

def scope_customers(room, viewer_id):
    """The Customers sub-tab: per customer of the attached cases the viewer can open - its cases, assets,
    compromised assets, assets with a done flag, IOCs (distinct per case, summed) and open findings."""
    from app.business.war_room_scope_iocs import iocs_per_case
    from app.business.war_rooms import room_case_ids
    from app.business.war_rooms import room_visible_case_ids
    linked = room_case_ids(room.id)
    visible = room_visible_case_ids(room.id, viewer_id)
    rows, meta, customers, _, _ = _build_rows(visible, viewer_id)
    per_case = iocs_per_case(visible)
    out = {}
    for cid in sorted(visible):
        client_id, name = customers.get(cid, (None, None))
        c = out.setdefault(client_id, {'customer_id': client_id, 'name': name, 'cases': [], 'assets': 0,
                                       'compromised': 0, 'done': 0, 'iocs': 0, 'vuln_open': 0,
                                       'vuln_exploited_open': 0})
        c['cases'].append({'case_id': cid, 'case_name': (meta.get(cid) or (None,))[0]})
        c['iocs'] += per_case.get(cid, 0)
    for r in rows:
        c = out.get(r['customer_id'])
        if c is None:
            continue
        c['assets'] += 1
        c['compromised'] += r['compromise'] == 'compromised'
        c['done'] += any(x['kind'] == 'done' for x in r['flags'])
        c['vuln_open'] += r['findings']['open']
        c['vuln_exploited_open'] += r['findings']['exploited_open']
    return {'customers': sorted(out.values(), key=lambda c: (c['name'] or '').lower()),
            'case_count': len(visible), 'cases_restricted': len([c for c in linked if c not in set(visible)])}


def scope_counts(room, viewer_id, is_admin):
    """The figures on the Scope's sub-tabs: assets (case assets + the Assets Manager attachments the viewer may
    see), distinct IOCs, customers, vulnerability entries (tracked by the room or found open in its cases) and
    staged objects."""
    from app.business.war_room_scope_iocs import ioc_groups
    from app.business.war_room_scope_staging import registry_rows
    from app.business.war_rooms import room_visible_case_ids
    from app.models.models import CaseAssets
    from app.models.models import Vulnerability
    from app.models.models import WarRoomStagedObject
    from app.models.models import WarRoomVulnerability
    visible = room_visible_case_ids(room.id, viewer_id)
    n_assets = CaseAssets.query.filter(CaseAssets.case_id.in_(visible)).count() if visible else 0
    reg, _ = registry_rows(room, viewer_id, is_admin)
    tracked = {v for (v,) in db.session.query(WarRoomVulnerability.vulnerability_id)
               .filter(WarRoomVulnerability.room_id == room.id)}
    found = {ident for _, _, _, ident, _, _, _ in wb.open_findings(visible)} if visible else set()
    found_ids = {v for (v,) in db.session.query(Vulnerability.vulnerability_id)
                 .filter(Vulnerability.identifier.in_(found))} if found else set()
    return {'assets': n_assets + len(reg), 'iocs': len(ioc_groups(visible)),
            'customers': len({c for c, _ in case_customers(visible).values()}),
            'vulnerabilities': len(tracked | found_ids),
            'staging': WarRoomStagedObject.query.filter(WarRoomStagedObject.room_id == room.id).count()}


def scope_vocab(room, viewer_id):
    """What the Add asset / Add IOC / staging dialogs offer: asset and IOC types, TLPs, analysis and compromise
    statuses, the attached cases the viewer can open (and may change), the flag catalogue and the limits."""
    from app.business.war_rooms import room_visible_case_ids
    from app.models.models import AnalysisStatus
    from app.models.models import AssetsType
    from app.models.models import IocType
    from app.models.models import Tlp
    visible = room_visible_case_ids(room.id, viewer_id)
    meta = wb._case_meta(visible)
    customers = case_customers(visible)
    writable = _writable(viewer_id, visible)
    return {
        'asset_types': [{'id': t.asset_id, 'name': t.asset_name}
                        for t in AssetsType.query.order_by(func.lower(AssetsType.asset_name))],
        'ioc_types': [{'id': t.type_id, 'name': t.type_name} for t in IocType.query.order_by(func.lower(IocType.type_name))],
        'tlps': [{'id': t.tlp_id, 'name': t.tlp_name} for t in Tlp.query.order_by(Tlp.tlp_id)],
        'analysis_statuses': [{'id': a.id, 'name': a.name} for a in AnalysisStatus.query.order_by(AnalysisStatus.id)],
        'compromise_statuses': [{'id': COMPROMISE_ID[k], 'key': k, 'label': lbl} for k, lbl in af.SCOPE_COMPROMISE],
        'cases': [{'case_id': c, 'case_name': (meta.get(c) or (None,))[0],
                   'customer_id': customers.get(c, (None, None))[0], 'customer_name': customers.get(c, (None, None))[1],
                   'can_write': c in writable} for c in sorted(visible)],
        'flags': [{'flag_id': x.id, 'name': x.name, 'color': x.color, 'icon': x.icon, 'kind': x.kind,
                   'description': x.description, 'requires_reason': bool(x.requires_reason),
                   'requires_decision': bool(x.requires_decision)}
                  for x in AssetFlag.query.order_by(AssetFlag.sort_order, AssetFlag.id)],
        'limits': {'targets': af.SCOPE_PUSH_CASES_MAX, 'staged_targets': af.SCOPE_STAGED_TARGETS_MAX,
                   'attach': af.SCOPE_REGISTRY_ATTACH_MAX},
    }

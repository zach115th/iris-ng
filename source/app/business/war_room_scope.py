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
removed, the compromise or analysis status set, assets pushed (copied) to other attached cases.

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
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


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


def scope_assets(room, viewer_id, args):
    from app.business import war_room_decisions as wd
    from app.business.war_rooms import room_case_ids
    from app.business.war_rooms import room_visible_case_ids
    from app.models.models import AnalysisStatus
    from app.models.models import WarRoomDecision
    f = parse_filters(args)
    linked = room_case_ids(room.id)
    visible = room_visible_case_ids(room.id, viewer_id)
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


def bulk_push(room, user, body):
    """Copy the selected assets into other attached cases: {asset_ids, case_ids}. Copies name, type, description,
    IP, domain, tags, compromise and analysis status (never the flags), through the case's own create path. One
    result per (asset, target case): created / exists / refused."""
    from app.business.assets import assets_create
    from app.business.errors import BusinessProcessingError
    from app.business.war_rooms import room_case_ids
    from app.business.war_rooms import room_visible_case_ids
    from app.models.models import CaseAssets
    _guard(room)
    linked = set(room_case_ids(room.id))
    targets = _ids(body.get('case_ids'), 'case', af.SCOPE_PUSH_CASES_MAX)
    bad = [c for c in targets if c not in linked]
    if bad:
        raise ScopeError('Case #%d is not attached to this war room.' % bad[0])
    writable = _writable(user.id, targets)
    visible = set(room_visible_case_ids(room.id, user.id))
    ids = _ids(body.get('asset_ids'), 'asset', af.SCOPE_BULK_MAX)
    sources = {a.asset_id: a for a in CaseAssets.query.filter(CaseAssets.asset_id.in_(ids)).all()}
    results = []
    for aid in ids:
        src = sources.get(aid)
        if src is None or src.case_id not in visible:
            results.append(_result(aid, None, 'refused', 'Not an asset of this war room\'s cases you can open'))
            continue
        payload = {k: getattr(src, k) for k in ('asset_name', 'asset_type_id', 'asset_description', 'asset_domain',
                                                  'asset_ip', 'asset_tags', 'asset_compromise_status_id',
                                                  'analysis_status_id')}
        for cid in targets:
            if cid == src.case_id:
                continue
            if cid not in writable:
                results.append(_result(aid, src, 'refused', 'You cannot change case #%d' % cid, target_case_id=cid))
                continue
            try:
                _, created = assets_create(cid, dict(payload))
                results.append(_result(aid, src, 'created', target_case_id=cid, new_asset_id=created.asset_id))
            except BusinessProcessingError as e:
                db.session.rollback()
                exists = 'already exists' in (e.get_message() or '')
                results.append(_result(aid, src, 'exists' if exists else 'refused', None if exists else e.get_message(),
                                       target_case_id=cid))
    return {'results': results, 'counts': _tally(results), 'at': _iso(datetime.utcnow())}

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

"""The war-room Scope tab (iris-ng 2026-11-07): every asset of the attached
cases THE VIEWER can open, with its compromise status, its flags and its open
findings, filtered and paged by the server. The Board's tiles and flag legend
open it filtered.

Membership never grants case access: a user sees the assets of the attached
cases their case ACL lets them read, and only a count of the others. Guests
never get the tab (the room's Vulnerabilities tab refuses them too).

Filters (query string): q (name, IP, domain, type), case_id, compromised=1,
flag=<flag id>|none, kind=status|done|exception (holds a flag of that kind),
vulnerable=open|exploited|kev|overdue; sort=case|name|findings|compromise,
dir=asc|desc; page, per_page.
"""

from app.business import war_room_board as wb
from app.models import asset_flag_vocab as af
from app.models.models import AssetFlag

COMPROMISE = {0: 'to_be_determined', 1: 'compromised', 2: 'not_compromised', 3: 'unknown'}


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
         'case_id': _int(args, 'case_id'),
         'compromised': None, 'flag': None, 'kind': None, 'vulnerable': None,
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
    if f['q']:
        hay = ' '.join(str(x or '') for x in (r['asset_name'], r['asset_ip'], r['asset_domain'], r['asset_type'])).lower()
        if f['q'] not in hay:
            return False
    return True


_SORT = {
    'case': lambda r: (r['case_id'], (r['asset_name'] or '').lower(), r['asset_id']),
    'name': lambda r: ((r['asset_name'] or '').lower(), r['case_id'], r['asset_id']),
    'findings': lambda r: (r['findings']['exploited_open'], r['findings']['open'], -r['asset_id']),
    'compromise': lambda r: (r['compromise'] == 'compromised', not r['flags'], -r['asset_id']),
}


def scope_assets(room, viewer_id, args):
    from app.business import war_room_decisions as wd
    from app.business.war_rooms import room_case_ids
    from app.business.war_rooms import room_visible_case_ids
    from app.models.models import WarRoomDecision
    f = parse_filters(args)
    linked = room_case_ids(room.id)
    visible = room_visible_case_ids(room.id, viewer_id)
    meta = wb._case_meta(visible)
    assets = wb.assets_of(visible)
    fl_of = wb.flags_by_asset([a[0] for a in assets])
    dids = {did for fl in fl_of.values() for _, _, did in fl if did is not None}
    refs = {d.id: wd.ref(d) for d in WarRoomDecision.query.filter(WarRoomDecision.id.in_(dids))} if dids else {}
    per_asset = {}
    for fid, cid, aid, ident, exploited, overdue, kev in wb.open_findings(visible):
        v = per_asset.setdefault(aid, {'open': 0, 'exploited_open': 0, 'kev_open': 0, 'overdue': 0})
        v['open'] += 1
        v['exploited_open'] += exploited
        v['kev_open'] += kev
        v['overdue'] += overdue
    rows = []
    for aid, name, cid, comp, typ, ip, domain in assets:
        fl = fl_of.get(aid, [])
        rows.append({
            'asset_id': aid, 'asset_name': name, 'asset_type': typ, 'asset_ip': ip, 'asset_domain': domain,
            'case_id': cid, 'case_name': (meta.get(cid) or (None,))[0],
            'compromise': COMPROMISE.get(comp),
            'flags': [{'flag_id': x.id, 'name': x.name, 'color': x.color, 'icon': x.icon, 'kind': x.kind,
                       'reason': reason, 'decision_id': did, 'decision_ref': refs.get(did)} for x, reason, did in fl],
            'findings': per_asset.get(aid, {'open': 0, 'exploited_open': 0, 'kev_open': 0, 'overdue': 0}),
            'href': '/case/assets?cid=%d&asset=%d&tab=details' % (cid, aid),
            'vulns_href': '/case/assets?cid=%d&asset=%d&tab=vulns' % (cid, aid),
        })
    by_flag = {}
    for r in rows:
        for x in r['flags']:
            by_flag[x['flag_id']] = by_flag.get(x['flag_id'], 0) + 1
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
        'filters': {k: f[k] for k in ('q', 'case_id', 'compromised', 'flag', 'kind', 'vulnerable', 'sort', 'dir')},
        'summary': summary,
        'flags': [{'flag_id': x.id, 'name': x.name, 'color': x.color, 'icon': x.icon, 'kind': x.kind,
                   'assets': by_flag.get(x.id, 0)} for x in catalogue],
        'cases': [{'case_id': c, 'case_name': (meta.get(c) or (None,))[0]} for c in sorted(visible)],
        'case_count': len(visible),
        'cases_restricted': len([c for c in linked if c not in set(visible)]),
    }

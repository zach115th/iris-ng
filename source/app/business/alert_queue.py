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

"""The alert queue (iris-ng, 2026-11-09): the Alerts page's list, board and detail.

  parse_args(args)                the request's query -> parameters (QueueError on a bad parameter or search)
  queue_page(user, params)        one page of entries: a cluster (its matching alerts grouped, a few shown) or an alert
  cluster_alerts(user, cid, ...)  more of one cluster's matching alerts
  board(user, params)             the board's columns
  tab_counts(user)                the quick tabs' figures
  detail(user, alert_id)          everything the detail pane shows
  page_state(user, args)          what the page draws in its first frame

The search bar's language is business.alert_query; the Filter panel's fields are the same filter every other alert
list uses (datamgmt.alerts.alerts_db.build_alert_filter), so the access rule and the saved filters are shared. Nothing
here changes an alert: the page saves through the existing /alerts routes.
"""

import math
import re
from datetime import datetime
from functools import wraps

from flask_login import current_user
from sqlalchemy import case as sa_case
from sqlalchemy import func
from sqlalchemy import literal_column
from sqlalchemy import select
from sqlalchemy.exc import DataError
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import selectinload

from app import db
from app.business import alert_query as aq
from app.datamgmt.alerts.alerts_db import build_alert_filter
from app.datamgmt.alerts.alerts_db import combine_conditions
from app.datamgmt.alerts.alerts_db import CustomConditionsError
from app.datamgmt.alerts.alerts_db import get_alert_by_id
from app.datamgmt.manage.manage_access_control_db import get_user_clients_id
from app.datamgmt.manage.manage_access_control_db import user_has_client_access
from app.datamgmt.manage.manage_users_db import get_users_list_restricted
from app.iris_engine.access_control.utils import ac_current_user_has_permission
from app.iris_engine.safe_markdown import render_markdown_safe
from app.models import alert_queue_vocab as av
from app.models.alerts import Alert
from app.models.alerts import AlertCluster
from app.models.alerts import AlertClusterMember
from app.models.alerts import AlertResolutionStatus
from app.models.alerts import AlertStatus
from app.models.alerts import Severity
from app.models.authorization import Permissions
from app.models.models import CaseClassification
from app.models.models import Client
from app.schema.marshables import AlertSchema


class QueueError(Exception):
    def __init__(self, message, status=400, query_error=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.query_error = query_error


def _refused_by_database(fn):
    """A custom condition can name a value its column cannot hold; only the database knows, when the list runs."""
    @wraps(fn)
    def inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (DataError, ProgrammingError):
            db.session.rollback()
            raise QueueError('The custom conditions cannot be applied to these values.')
    return inner


def _iso(moment):
    return moment.replace(microsecond=0).isoformat() + 'Z' if moment else None


def _is_admin():
    return bool(ac_current_user_has_permission(Permissions.server_administrator))


class Lookups:
    """Names -> ids for one request; a value of the search resolves here."""

    def __init__(self, user):
        self.user_id = user.id
        self._maps = {}
        self._severities = None
        self._finished = None

    def _map(self, field):
        if field in self._maps:
            return self._maps[field]
        out = {}

        def add(name, row_id):
            if name:
                out.setdefault(name.strip().lower(), set()).add(row_id)

        if field == 'status':
            for s in AlertStatus.query.all():
                add(s.status_name, s.status_id)
        elif field == 'severity':
            for s in Severity.query.all():
                add(s.severity_name, s.severity_id)
        elif field == 'resolution':
            for s in AlertResolutionStatus.query.all():
                add(s.resolution_status_name, s.resolution_status_id)
        elif field == 'classification':
            for c in CaseClassification.query.all():
                add(c.name, c.id)
                add(c.name_expanded, c.id)
        elif field == 'customer':
            for c in visible_customers():
                add(c['name'], c['id'])
        elif field == 'owner':
            for u in owners():
                add(u['name'], u['id'])
                add(u['login'], u['id'])
        self._maps[field] = out
        return out

    def ids_for(self, field, low_name):
        return sorted(self._map(field).get(low_name, ()))

    def severities(self):
        if self._severities is None:
            rows = Severity.query.all()
            self._severities = [(s.severity_id, s.severity_name, severity_rank_of(s.severity_name)) for s in rows]
        return self._severities

    def severity_rank(self, text):
        low = text.strip().lower()
        for _sid, name, rank in self.severities():
            if name.lower() == low:
                return rank
        return None

    def severities_where(self, op, rank):
        test = {'>=': lambda r: r >= rank, '<=': lambda r: r <= rank, '>': lambda r: r > rank, '<': lambda r: r < rank}[op]
        return [sid for sid, _name, r in self.severities() if test(r)]

    @property
    def finished_ids(self):
        if self._finished is None:
            wanted = [n.lower() for n in av.FINISHED_STATUSES]
            self._finished = [s.status_id for s in AlertStatus.query.all() if s.status_name.lower() in wanted]
        return self._finished


def severity_rank_of(name):
    low = (name or '').lower()
    for i, n in enumerate(av.SEVERITY_ORDER):
        if n.lower() == low:
            return i
    return -1


def status_rank_of(name):
    low = (name or '').lower()
    for i, n in enumerate(av.STATUS_ORDER):
        if n.lower() == low:
            return i
    return len(av.STATUS_ORDER)


def visible_customers():
    """The customers whose alerts the caller can see, by name."""
    query = db.session.query(Client.client_id, Client.name)
    if not _is_admin():
        query = query.filter(Client.client_id.in_(get_user_clients_id(current_user.id) or [0]))
    return [{'id': cid, 'name': name or '#%d' % cid} for cid, name in query.order_by(func.lower(Client.name)).all()]


def owners():
    return [{'id': u['user_id'], 'name': u.get('user_name') or u.get('user_login'), 'login': u.get('user_login'),
             'active': bool(u.get('user_active', True))} for u in get_users_list_restricted()]


# ------------------------------------------------------------------ the request

def _int_param(args, name):
    raw = args.get(name)
    if raw in (None, ''):
        return None
    text = str(raw).strip()
    if not re.fullmatch(r'-?\d{1,18}', text):
        raise QueueError('%s must be a number.' % name)
    return int(text)


def _list_param(args, name, numbers=False):
    raw = args.get(name)
    if raw in (None, ''):
        return None
    parts = [p.strip() for p in str(raw).split(',') if p.strip()]
    if numbers:
        if not all(re.fullmatch(r'\d{1,18}', p) for p in parts):
            raise QueueError('%s must be a comma-separated list of numbers.' % name)
        return [int(p) for p in parts]
    return parts


def parse_args(args):
    """The list's query string -> validated parameters."""
    params = {'filters': {}}
    for name in av.FILTER_TEXT + av.FILTER_DATES:
        value = args.get(name)
        if value not in (None, ''):
            params['filters'][name] = str(value)
    for name in av.FILTER_INT:
        value = _int_param(args, name)
        if value is not None:
            params['filters'][name] = value
    params['filters'].update({k: v for k, v in (('alert_ids', _list_param(args, 'alert_ids', numbers=True)),
                                                ('alert_assets', _list_param(args, 'alert_assets')),
                                                ('alert_iocs', _list_param(args, 'alert_iocs'))) if v is not None})
    custom = args.get('custom_conditions')
    if custom not in (None, ''):
        params['filters']['custom_conditions'] = str(custom)

    if 'q' in args:
        params['q'] = str(args.get('q') or '')
    else:
        params['q'] = '' if params['filters'] else av.DEFAULT_QUERY

    order_by = args.get('order_by')
    params['order_by'] = order_by if order_by in av.SORTS else av.DEFAULT_SORT[0]
    sort = args.get('sort')
    params['sort'] = sort if sort in av.DIRECTIONS else av.SORTS[params['order_by']][1]
    page = _int_param(args, 'page') or 1
    params['page'] = max(page, 1)
    per_page = _int_param(args, 'per_page') or av.DEFAULT_PAGE_SIZE
    params['per_page'] = per_page if per_page in av.PAGE_SIZES else av.DEFAULT_PAGE_SIZE
    params['group'] = str(args.get('group', '1')) != '0' and not (
        params['filters'].get('alert_ids') or params['filters'].get('cluster_id') is not None)
    board_group = args.get('board')
    params['board'] = board_group if board_group in av.BOARD_GROUPS else av.DEFAULT_BOARD_GROUP
    return params


def _describe_query(text):
    """-> (the tree, {text, clauses, tab}); a fault raises QueueError with its position."""
    try:
        node = aq.parse(text)
    except aq.QueryError as exc:
        raise QueueError(exc.message, query_error=exc.as_dict())
    return node, {'text': text, 'clauses': aq.clauses(text, node), 'tab': aq.tab_of(node)}


def _matching(user, params, lookups, extra=None):
    """-> (the query of matching alert ids, the search's description)."""
    node, described = _describe_query(params['q'])
    try:
        clause = aq.compile_query(node, lookups)
    except aq.QueryError as exc:
        raise QueueError(exc.message, query_error=exc.as_dict())
    f = params['filters']
    try:
        query, conditions = build_alert_filter(
            start_date=f.get('creation_start_date'), end_date=f.get('creation_end_date'),
            source_start_date=f.get('source_start_date'), source_end_date=f.get('source_end_date'),
            title=f.get('alert_title'), description=f.get('alert_description'), status=f.get('alert_status_id'),
            severity=f.get('alert_severity_id'), owner=f.get('alert_owner_id'), source=f.get('alert_source'),
            tags=f.get('alert_tags'), case_id=f.get('case_id'), client=f.get('alert_customer_id'),
            classification=f.get('alert_classification_id'), alert_ids=f.get('alert_ids'),
            assets=f.get('alert_assets'), iocs=f.get('alert_iocs'), resolution_status=f.get('alert_resolution_id'),
            current_user_id=user.id, source_reference=f.get('source_reference'),
            custom_conditions=f.get('custom_conditions'))
    except CustomConditionsError as exc:
        raise QueueError(str(exc))
    except (ValueError, KeyError, TypeError, AttributeError, NotImplementedError) as exc:
        raise QueueError('The custom conditions cannot be applied: %s' % str(exc)[:200])
    if clause is not None:
        conditions.append(clause)
    cluster_id = f.get('cluster_id')
    if cluster_id is not None:
        members = select(AlertClusterMember.alert_id)
        if cluster_id == -1:
            conditions.append(Alert.alert_id.notin_(members))
        else:
            conditions.append(Alert.alert_id.in_(members.where(AlertClusterMember.cluster_id == cluster_id)))
    if extra is not None:
        conditions.append(extra)
    combined = combine_conditions(conditions, 'and')
    if combined is not None:
        query = query.filter(combined)
    return query.with_entities(Alert.alert_id), described


# ------------------------------------------------------------------ rows

def _pair(row_id, name):
    return {'id': row_id, 'name': name} if row_id is not None else None


def _tags(text):
    return [t.strip() for t in (text or '').split(',') if t.strip()]


def row(alert, cluster, lookups):
    finished = lookups.finished_ids
    return {
        'alert_id': alert.alert_id,
        'title': alert.alert_title,
        'severity': _pair(alert.alert_severity_id, alert.severity.severity_name if alert.severity else None),
        'status': _pair(alert.alert_status_id, alert.status.status_name if alert.status else None),
        'customer': _pair(alert.alert_customer_id, alert.customer.name if alert.customer else None),
        'owner': _pair(alert.alert_owner_id, (alert.owner.name or alert.owner.user) if alert.owner else None),
        'resolution': _pair(alert.alert_resolution_status_id,
                            alert.resolution_status.resolution_status_name if alert.resolution_status else None),
        'classification': _pair(alert.alert_classification_id,
                                (alert.classification.name_expanded or alert.classification.name) if alert.classification else None),
        'tags': _tags(alert.alert_tags),
        'source': alert.alert_source,
        'event_time': _iso(alert.alert_source_event_time),
        'created': _iso(alert.alert_creation_time),
        'cases': [c.case_id for c in alert.cases],
        'cluster': cluster,
        'is_open': alert.alert_status_id not in finished,
    }


def _rows_by_id(ids, lookups):
    """{alert id: row} for these ids."""
    if not ids:
        return {}
    alerts = (Alert.query.options(selectinload(Alert.severity), selectinload(Alert.status), selectinload(Alert.customer),
                                  selectinload(Alert.owner), selectinload(Alert.resolution_status),
                                  selectinload(Alert.classification), selectinload(Alert.cases))
              .filter(Alert.alert_id.in_(ids)).all())
    clusters = dict(db.session.execute(select(AlertClusterMember.alert_id, AlertClusterMember.cluster_id)
                                       .where(AlertClusterMember.alert_id.in_(ids))).all())
    titles = dict(db.session.execute(select(AlertCluster.id, AlertCluster.title)
                                     .where(AlertCluster.id.in_(set(clusters.values())))).all()) if clusters else {}
    out = {}
    for a in alerts:
        cid = clusters.get(a.alert_id)
        out[a.alert_id] = row(a, {'id': cid, 'title': titles.get(cid)} if cid else None, lookups)
    return out


def _sort_expr(order_by, lookups):
    if order_by == 'title':
        return func.lower(Alert.alert_title)
    if order_by == 'customer_name':
        return func.lower(Client.name)
    if order_by == 'severity':
        return sa_case(*[(Alert.alert_severity_id == sid, rank) for sid, _n, rank in lookups.severities()], else_=-1)
    if order_by == 'status':
        ranks = [(s.status_id, status_rank_of(s.status_name)) for s in AlertStatus.query.all()]
        return sa_case(*[(Alert.alert_status_id == sid, rank) for sid, rank in ranks], else_=len(av.STATUS_ORDER))
    return Alert.alert_source_event_time


def _from(stmt, order_by):
    stmt = stmt.select_from(Alert)
    return stmt.join(Client, Client.client_id == Alert.alert_customer_id) if order_by == 'customer_name' else stmt


def _clamp(page, per_page, total):
    last = max(1, math.ceil(total / per_page)) if total else 1
    return min(page, last), last


@_refused_by_database
def queue_page(user, params):
    """One page of entries. Grouped: a cluster's matching alerts are one entry, sorted by their newest (or highest)."""
    lookups = Lookups(user)
    matching, described = _matching(user, params, lookups)
    ids = matching.subquery()
    id_sel = select(ids.c.alert_id)
    order_by, sort = params['order_by'], params['sort']
    expr = _sort_expr(order_by, lookups)
    descending = sort == 'desc'
    total = db.session.execute(select(func.count()).select_from(ids)).scalar() or 0

    if params['group']:
        key = func.coalesce(AlertClusterMember.cluster_id, -Alert.alert_id).label('k')
        agg = (func.max(expr) if descending else func.min(expr)).label('s')
        base = _from(select(key, agg, func.count().label('n')), order_by).outerjoin(
            AlertClusterMember, AlertClusterMember.alert_id == Alert.alert_id).where(
            Alert.alert_id.in_(id_sel)).group_by(literal_column('k'))
    else:
        key = Alert.alert_id.label('k')
        agg = expr.label('s')
        base = _from(select(key, agg, func.count().label('n')), order_by).where(Alert.alert_id.in_(id_sel)).group_by(
            Alert.alert_id, *([Client.name] if order_by == 'customer_name' else []))

    sub = base.subquery()
    entries_total = db.session.execute(select(func.count()).select_from(sub)).scalar() or 0
    page, last_page = _clamp(params['page'], params['per_page'], entries_total)
    order = sub.c.s.desc().nulls_last() if descending else sub.c.s.asc().nulls_last()
    tie = sub.c.k.desc() if descending else sub.c.k.asc()
    picked = db.session.execute(select(sub.c.k, sub.c.n).order_by(order, tie)
                                .limit(params['per_page']).offset((page - 1) * params['per_page'])).all()

    cluster_counts = {k: n for k, n in picked if params['group'] and k > 0}
    single_alert_ids = [-k for k in (k for k, _n in picked) if params['group'] and k < 0] if params['group'] else [k for k, _n in picked]
    member_ids = {}
    if cluster_counts:
        rank = func.row_number().over(partition_by=AlertClusterMember.cluster_id,
                                      order_by=(expr.desc().nulls_last() if descending else expr.asc().nulls_last(),
                                                Alert.alert_id.desc() if descending else Alert.alert_id.asc())).label('rn')
        ranked = _from(select(Alert.alert_id.label('aid'), AlertClusterMember.cluster_id.label('cid'), rank), order_by).join(
            AlertClusterMember, AlertClusterMember.alert_id == Alert.alert_id).where(
            AlertClusterMember.cluster_id.in_(list(cluster_counts)), Alert.alert_id.in_(id_sel)).subquery()
        for aid, cid, rn in db.session.execute(select(ranked.c.aid, ranked.c.cid, ranked.c.rn).where(
                ranked.c.rn <= av.CLUSTER_PREVIEW).order_by(ranked.c.cid, ranked.c.rn)).all():
            member_ids.setdefault(cid, []).append(aid)
    every = list(single_alert_ids)
    for lst in member_ids.values():
        every.extend(lst)
    rows = _rows_by_id(every, lookups)
    clusters = {c.id: c for c in AlertCluster.query.filter(AlertCluster.id.in_(list(cluster_counts))).all()} if cluster_counts else {}

    entries = []
    for k, n in picked:
        if params['group'] and k > 0:
            members = [rows[a] for a in member_ids.get(k, []) if a in rows]
            if n == 1 and members:
                entries.append({'kind': 'alert', 'key': 'a%d' % members[0]['alert_id'], 'alert': members[0]})
                continue
            c = clusters.get(k)
            entries.append({'kind': 'cluster', 'key': 'c%d' % k, 'count': n, 'alerts': members, 'more': n - len(members),
                            'cluster': {'id': k, 'title': c.title if c else '#%d' % k, 'status': c.status if c else None}})
        else:
            aid = -k if params['group'] else k
            if aid in rows:
                entries.append({'kind': 'alert', 'key': 'a%d' % aid, 'alert': rows[aid]})
    return {'total': total, 'entries_total': entries_total, 'page': page, 'per_page': params['per_page'], 'last_page': last_page,
            'order_by': order_by, 'sort': sort, 'grouped': params['group'], 'entries': entries, 'query': described}


@_refused_by_database
def cluster_alerts(user, cluster_id, params, offset=0, limit=None):
    """More of one cluster's matching alerts."""
    lookups = Lookups(user)
    matching, _described = _matching(user, params, lookups)
    ids = matching.subquery()
    order_by, sort = params['order_by'], params['sort']
    expr = _sort_expr(order_by, lookups)
    descending = sort == 'desc'
    limit = min(max(limit or av.CLUSTER_PAGE, 1), 100)
    stmt = _from(select(Alert.alert_id), order_by).join(AlertClusterMember, AlertClusterMember.alert_id == Alert.alert_id).where(
        AlertClusterMember.cluster_id == cluster_id, Alert.alert_id.in_(select(ids.c.alert_id)))
    total = db.session.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    picked = [r[0] for r in db.session.execute(stmt.order_by(
        expr.desc().nulls_last() if descending else expr.asc().nulls_last(),
        Alert.alert_id.desc() if descending else Alert.alert_id.asc()).limit(limit).offset(max(offset, 0))).all()]
    rows = _rows_by_id(picked, lookups)
    return {'total': total, 'offset': max(offset, 0), 'alerts': [rows[a] for a in picked if a in rows]}


def tab_counts(user):
    """Each quick tab's count over everything the caller can see, whatever is being searched."""
    lookups = Lookups(user)
    out = {}
    for key, _label, query in av.TABS:
        matching, _d = _matching(user, {'q': query, 'filters': {}}, lookups)
        out[key] = db.session.execute(select(func.count()).select_from(matching.subquery())).scalar() or 0
    return out


@_refused_by_database
def board(user, params):
    """The board: open alerts only. severity = unowned alerts per severity; status = owned alerts per status."""
    lookups = Lookups(user)
    group = params['board']
    finished = lookups.finished_ids
    owned = Alert.alert_owner_id.isnot(None) if group == 'status' else Alert.alert_owner_id.is_(None)
    extra = owned if not finished else (Alert.alert_status_id.notin_(finished) & owned)
    matching, described = _matching(user, params, lookups, extra=extra)
    ids = matching.subquery()
    if group == 'severity':
        cols = sorted(((sid, name, rank) for sid, name, rank in lookups.severities()), key=lambda x: -x[2])
        columns = [{'id': sid, 'name': name} for sid, name, _r in cols]
        column_of = Alert.alert_severity_id
    else:
        statuses = [s for s in AlertStatus.query.all() if s.status_id not in finished]
        statuses.sort(key=lambda s: status_rank_of(s.status_name))
        columns = [{'id': s.status_id, 'name': s.status_name} for s in statuses]
        column_of = Alert.alert_status_id
    rank = func.row_number().over(partition_by=column_of, order_by=(Alert.alert_source_event_time.desc(), Alert.alert_id.desc())).label('rn')
    ranked = select(Alert.alert_id.label('aid'), column_of.label('col'), rank).where(Alert.alert_id.in_(select(ids.c.alert_id))).subquery()
    counts = dict(db.session.execute(select(column_of, func.count()).where(Alert.alert_id.in_(select(ids.c.alert_id))).group_by(column_of)).all())
    picked = db.session.execute(select(ranked.c.aid, ranked.c.col, ranked.c.rn).where(ranked.c.rn <= av.BOARD_COLUMN_LIMIT).order_by(ranked.c.rn)).all()
    rows = _rows_by_id([p[0] for p in picked], lookups)
    by_col = {}
    for aid, col, _rn in picked:
        if aid in rows:
            by_col.setdefault(col, []).append(rows[aid])
    for c in columns:
        c['total'] = counts.get(c['id'], 0)
        c['alerts'] = by_col.get(c['id'], [])
    return {'group': group, 'columns': columns, 'column_limit': av.BOARD_COLUMN_LIMIT, 'query': described,
            'total': sum(c['total'] for c in columns)}


# ------------------------------------------------------------------ the detail pane

def _history(alert):
    """The change history, newest first: [{when, user, action}]."""
    out = []
    for stamp, entry in (alert.modification_history or {}).items():
        try:
            when = datetime.utcfromtimestamp(float(stamp))
        except (TypeError, ValueError, OverflowError):
            continue
        if isinstance(entry, dict):
            out.append({'when': _iso(when), 'user': entry.get('user'), 'action': entry.get('action')})
    out.sort(key=lambda e: e['when'], reverse=True)
    return out


def _cluster_summary(alert, lookups):
    member = AlertClusterMember.query.filter(AlertClusterMember.alert_id == alert.alert_id).first()
    if member is None:
        return None
    cluster = db.session.get(AlertCluster, member.cluster_id)
    count = AlertClusterMember.query.filter(AlertClusterMember.cluster_id == cluster.id).count()
    ids = [r[0] for r in db.session.execute(
        select(Alert.alert_id).join(AlertClusterMember, AlertClusterMember.alert_id == Alert.alert_id).where(
            AlertClusterMember.cluster_id == cluster.id).order_by(Alert.alert_source_event_time.desc(), Alert.alert_id.desc())
        .limit(av.CLUSTER_MEMBERS_IN_DETAIL)).all()]
    rows = _rows_by_id(ids, lookups)
    return {'id': cluster.id, 'title': cluster.title, 'status': cluster.status, 'count': count,
            'rule': cluster.rule.name if cluster.rule else None,
            'correlation_values': cluster.correlation_values or {},
            'first_alert_at': _iso(cluster.first_alert_at), 'last_alert_at': _iso(cluster.last_alert_at),
            'members': [rows[a] for a in ids if a in rows]}


def detail(user, alert_id):
    """The detail pane's data, or None when the alert is missing or the caller may not see it."""
    alert = get_alert_by_id(alert_id)
    if alert is None or not user_has_client_access(user.id, alert.alert_customer_id):
        return None
    lookups = Lookups(user)
    out = AlertSchema().dump(alert)
    out.update({
        'description_html': render_markdown_safe(alert.alert_description) if alert.alert_description else '',
        'note_html': render_markdown_safe(alert.alert_note) if alert.alert_note else '',
        'tags': _tags(alert.alert_tags),
        'event_time': _iso(alert.alert_source_event_time),
        'created': _iso(alert.alert_creation_time),
        'is_open': alert.alert_status_id not in lookups.finished_ids,
        'history': _history(alert),
        'cluster': _cluster_summary(alert, lookups),
    })
    return out


# ------------------------------------------------------------------ the page

def options():
    severities = sorted(Severity.query.all(), key=lambda s: -severity_rank_of(s.severity_name))
    return {
        'statuses': [{'id': s.status_id, 'name': s.status_name}
                     for s in sorted(AlertStatus.query.all(), key=lambda x: (status_rank_of(x.status_name), x.status_name))],
        'severities': [{'id': s.severity_id, 'name': s.severity_name} for s in severities],
        'resolutions': [{'id': r.resolution_status_id, 'name': r.resolution_status_name}
                        for r in AlertResolutionStatus.query.order_by(AlertResolutionStatus.resolution_status_id).all()],
        'classifications': [{'id': c.id, 'name': c.name_expanded or c.name}
                            for c in CaseClassification.query.order_by(CaseClassification.name).all()],
        'customers': visible_customers(),
        'users': owners(),
    }


def permissions():
    return {'write': bool(ac_current_user_has_permission(Permissions.alerts_write)),
            'delete': bool(ac_current_user_has_permission(Permissions.alerts_delete))}


def _echo(params):
    """The request as the page keeps it."""
    return {'q': params['q'], 'filters': params['filters'], 'order_by': params['order_by'], 'sort': params['sort'],
            'page': params['page'], 'per_page': params['per_page'], 'board': params['board']}


def _selected_id(args, params):
    raw = args.get('alert')
    if raw and re.fullmatch(r'\d{1,18}', str(raw)):
        return int(raw)
    ids = params['filters'].get('alert_ids') or []
    return ids[0] if len(ids) == 1 else None


def page_state(user, args):
    """Everything the page draws first. A bad search or filter still gives a page: the error, no list."""
    state = {'vocab': av.client_vocab(), 'options': options(), 'me': {'id': user.id, 'name': user.name or user.user},
             'permissions': permissions(), 'error': None, 'query_error': None, 'params': None, 'result': None, 'board': None,
             'detail': None, 'tab_counts': tab_counts(user), 'view': args.get('view') if args.get('view') in av.VIEWS else None}
    try:
        params = parse_args(args)
    except QueueError as exc:
        state['error'] = exc.message
        params = parse_args({'q': av.DEFAULT_QUERY})
    state['params'] = _echo(params)
    try:
        if state['view'] == 'board':
            state['board'] = board(user, params)
        else:
            state['result'] = queue_page(user, params)
    except QueueError as exc:
        state['error'] = exc.message
        state['query_error'] = exc.query_error
    selected = _selected_id(args, params)
    if selected is not None:
        state['detail'] = detail(user, selected)
    return state

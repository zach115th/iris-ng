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

"""The case queue (iris-ng, 2026-11-08): the Overview page's list of cases.

One page of the cases a user can open (any access but deny_all, the old Overview's rule), filtered by a tree of
conditions (models.case_queue_vocab), searched, sorted and counted IN THE DATABASE - the page never loads every case.

  parse_args(args)          the request's query -> validated parameters (QueueError on a bad filter)
  queue_page(uid, params)   {total, page, per_page, last_page, sort, dir, data}
  kpis(uid)                 the four chips' figures; kpi_trees(uid) the filters behind them (the same clauses)
  case_detail(cid, ...)     the side panel: tasks, the summary (cached executive summary, else the description)
  page_state(user, args)    everything the page draws in its first frame

"Last activity" is the newest entry of the case's activity log (user_activity) - any change to the case or what it
holds - else the open date. Nothing here changes a case: the stage track saves through PUT /api/v2/cases/<id>.
"""

import json
import math
import re
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta

from sqlalchemy import and_
from sqlalchemy import case as sa_case
from sqlalchemy import cast
from sqlalchemy import DateTime
from sqlalchemy import func
from sqlalchemy import not_
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import aliased
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import selectinload

from app import db
from app.iris_engine.access_control.utils import ac_fast_check_current_user_has_case_access
from app.iris_engine.safe_markdown import render_markdown_safe
from app.models import case_queue_vocab as qv
from app.models.alerts import Severity
from app.models.authorization import CaseAccessLevel
from app.models.authorization import User
from app.models.authorization import UserCaseEffectiveAccess
from app.models.cases import Cases
from app.models.cases import CaseState
from app.models.cases import CaseTags
from app.models.models import CaseClassification
from app.models.models import CaseTasks
from app.models.models import Client
from app.models.models import ReviewStatus
from app.models.models import SavedFilter
from app.models.models import Tags
from app.models.models import TaskStatus
from app.models.models import UserActivity
from app.schema.marshables import executive_summaries_for

_TITLE_PREFIX = re.compile(r'^\s*#\d+ - ')
_OUTCOMES = dict(qv.OUTCOMES)


class QueueError(Exception):
    def __init__(self, message, status=400, data=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.data = data


# ------------------------------------------------------------------ validation

def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text_ = value.strip()  # trimmed here, not with \s* in the pattern (code scanning #51)
        if re.fullmatch(r'\d{1,12}', text_):
            return int(text_)
    return None


def _value(field, op, value):
    label, ftype, _source, _nullable = qv.FIELDS[field]
    if op in qv.DAY_OPS:
        days = _int(value)
        if days is None or days > qv.MAX_DAYS:
            raise QueueError('%s: give a number of days from 0 to %d.' % (label, qv.MAX_DAYS))
        return days
    if ftype in ('number', 'choice'):
        number = _int(value)
        if number is None:
            raise QueueError('%s: pick a value.' % label)
        return number
    if ftype == 'date':
        try:
            return date.fromisoformat(str(value).strip()).isoformat()
        except (TypeError, ValueError):
            raise QueueError('%s: give a date as YYYY-MM-DD.' % label)
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise QueueError('%s needs a value.' % label)
    text = str(value).strip()
    if not text:
        raise QueueError('%s needs a value.' % label)
    if len(text) > qv.MAX_VALUE_LEN:
        raise QueueError('%s: a value is at most %d characters.' % (label, qv.MAX_VALUE_LEN))
    return text


def _leaf(item, count):
    if not isinstance(item, dict):
        raise QueueError('A filter condition must be an object.')
    field, op = item.get('field'), item.get('op')
    if not isinstance(field, str) or field not in qv.FIELDS:
        raise QueueError('Unknown filter field: %s' % str(field)[:40])
    if op not in qv.field_ops(field):
        raise QueueError('%s cannot use the operator "%s".' % (qv.FIELDS[field][0], str(op)[:30]))
    count[0] += 1
    if count[0] > qv.MAX_CONDITIONS:
        raise QueueError('A filter holds at most %d conditions.' % qv.MAX_CONDITIONS)
    if op in qv.NO_VALUE_OPS:
        return {'field': field, 'op': op, 'value': None}
    return {'field': field, 'op': op, 'value': _value(field, op, item.get('value'))}


def _group(node, depth, count):
    if not isinstance(node, dict):
        raise QueueError('A filter group must be an object.')
    logic = node.get('logic', 'and')
    if logic not in ('and', 'or'):
        raise QueueError('A filter group matches "and" or "or".')
    items = node.get('items', [])
    if not isinstance(items, list):
        raise QueueError('A filter group holds a list of items.')
    out = []
    for item in items:
        if isinstance(item, dict) and 'items' in item:
            if depth + 1 >= qv.MAX_DEPTH:
                raise QueueError('Sub-groups nest at most %d levels deep.' % (qv.MAX_DEPTH - 1))
            sub = _group(item, depth + 1, count)
            if sub['items']:
                out.append(sub)
        else:
            out.append(_leaf(item, count))
    return {'logic': logic, 'items': out}


def validate_tree(tree):
    """A filter as the browser or a saved filter sends it -> the normalised tree (empty sub-groups dropped)."""
    if tree is None or tree == '' or tree == {}:
        return {'logic': 'and', 'items': []}
    if isinstance(tree, str):
        try:
            tree = json.loads(tree)
        except ValueError:
            raise QueueError('The filter is not valid JSON.')
    return _group(tree, 0, [0])


# ------------------------------------------------------------------ clauses

def _like(text):
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _title_sql():
    """The case name without the '#<id> - ' prefix every case name carries (trimmed: some carry two spaces)."""
    return func.btrim(func.regexp_replace(func.coalesce(Cases.name, ''), r'^\s*#[0-9]+ - ', ''))


def display_title(name, case_id=None):
    return _TITLE_PREFIX.sub('', name or '', count=1).strip()


_TEXT_COLS = {
    'title': _title_sql,
    'soc_id': lambda: Cases.soc_id,
    'description': lambda: Cases.description,
    'closing_note': lambda: Cases.closing_note,
}
_CHOICE_COLS = {
    'customer': Cases.client_id,
    'severity': Cases.severity_id,
    'state': Cases.state_id,
    'classification': Cases.classification_id,
    'outcome': Cases.status_id,
    'owner': Cases.owner_id,
    'opened_by': Cases.user_id,
    'reviewer': Cases.reviewer_id,
    'review_status': Cases.review_status_id,
}
_DATE_COLS = {'open_date': Cases.open_date, 'close_date': Cases.close_date}
_PATTERNS = {'contains': '%{}%', 'starts_with': '{}%', 'ends_with': '%{}'}


def _text_clause(column, op, value):
    col = func.coalesce(column, '')
    if op == 'empty':
        return func.trim(col) == ''
    if op == 'not_empty':
        return func.trim(col) != ''
    negate = op.startswith('not_')
    base = op[4:] if negate else op
    if base == 'equals':
        expr = func.lower(col) == value.lower()
    else:
        expr = col.ilike(_PATTERNS[base].format(_like(value)), escape='\\')
    return not_(expr) if negate else expr


def _tags_exist(condition=None):
    sub = (select(CaseTags.case_id)
           .join(Tags, Tags.id == CaseTags.tag_id)
           .where(CaseTags.case_id == Cases.case_id))
    if condition is not None:
        sub = sub.where(condition)
    return sub.exists()


def _today():
    return datetime.utcnow().date()


def _leaf_clause(leaf, today=None):
    field, op, value = leaf['field'], leaf['op'], leaf['value']
    ftype = qv.FIELDS[field][1]
    if ftype == 'text':
        return _text_clause(_TEXT_COLS[field](), op, value)
    if ftype == 'number':
        col = Cases.case_id
        return {'equals': col == value, 'not_equals': col != value, 'greater': col > value, 'less': col < value}[op]
    if ftype == 'choice':
        col = _CHOICE_COLS[field]
        if op == 'equals':
            return col == value
        if op == 'not_equals':
            return or_(col.is_(None), col != value)
        return col.is_(None) if op == 'empty' else col.isnot(None)
    if ftype == 'date':
        col = _DATE_COLS[field]
        if op == 'empty':
            return col.is_(None)
        if op == 'not_empty':
            return col.isnot(None)
        if op in qv.DAY_OPS:
            edge = (today or _today()) - timedelta(days=value)
            return col < edge if op == 'older_than' else col >= edge
        day = date.fromisoformat(value)
        return {'on': col == day, 'before': col < day, 'after': col > day}[op]
    # tags
    if op == 'empty':
        return not_(_tags_exist())
    if op == 'not_empty':
        return _tags_exist()
    negate = op in ('has_not', 'not_contains')
    if op in ('has', 'has_not'):
        expr = _tags_exist(func.lower(Tags.tag_title) == value.lower())
    else:
        expr = _tags_exist(Tags.tag_title.ilike('%' + _like(value) + '%', escape='\\'))
    return not_(expr) if negate else expr


def condition(tree, today=None):
    """The SQL clause of a validated tree, or None when it holds no condition."""
    clauses = []
    for item in tree.get('items', []):
        clause = condition(item, today) if 'items' in item else _leaf_clause(item, today)
        if clause is not None:
            clauses.append(clause)
    if not clauses:
        return None
    return and_(*clauses) if tree.get('logic', 'and') == 'and' else or_(*clauses)


def _search_clause(text):
    text = (text or '').strip()[:qv.SEARCH_MAX]
    if not text:
        return None
    pattern = '%' + _like(text) + '%'
    parts = [
        _title_sql().ilike(pattern, escape='\\'),
        func.coalesce(Cases.soc_id, '').ilike(pattern, escape='\\'),
        _tags_exist(Tags.tag_title.ilike(pattern, escape='\\')),
        select(Client.client_id).where(Client.client_id == Cases.client_id,
                                       Client.name.ilike(pattern, escape='\\')).exists(),
    ]
    number = re.fullmatch(r'#?(\d{1,12})', text)
    if number:
        parts.append(Cases.case_id == int(number.group(1)))
    return or_(*parts)


# ------------------------------------------------------------------ the queue

def _accessible(user_id):
    return (select(UserCaseEffectiveAccess.case_id)
            .where(UserCaseEffectiveAccess.user_id == user_id,
                   UserCaseEffectiveAccess.access_level != CaseAccessLevel.deny_all.value))


def _base(user_id, closed):
    query = Cases.query.filter(Cases.case_id.in_(_accessible(user_id)))
    if not closed:
        query = query.filter(Cases.close_date.is_(None))
    return query


def parse_args(args):
    """The list request's query string -> parameters. A bad filter is a QueueError (400)."""
    sort = args.get('sort')
    if sort not in qv.SORTS:
        sort = qv.DEFAULT_SORT[0]
    direction = args.get('dir')
    if direction not in qv.DIRECTIONS:
        direction = qv.SORTS[sort][1]
    per_page = _int(args.get('per_page'))
    if per_page not in qv.PAGE_SIZES:
        per_page = qv.DEFAULT_PAGE_SIZE
    page = _int(args.get('page')) or 1
    return {
        'q': (args.get('q') or '')[:qv.SEARCH_MAX],
        'closed': str(args.get('closed', '')).lower() in ('1', 'true', 'yes', 'on'),
        'page': max(1, page),
        'per_page': per_page,
        'sort': sort,
        'dir': direction,
        'tree': validate_tree(args.get('filter')),
    }


def _last_activity_subquery():
    return (select(UserActivity.case_id.label('case_id'),
                   func.max(UserActivity.activity_date).label('last'))
            .where(UserActivity.case_id.isnot(None))
            .group_by(UserActivity.case_id)
            .subquery())


def _sorted(query, sort, direction):
    """ORDER BY for a sort key. Age and Idle sort the MOMENT underneath: the youngest case has the newest open
    date, the most idle the oldest last activity."""
    reverse = False
    if sort == 'case':
        keys = [func.lower(_title_sql())]
    elif sort == 'stage':
        query = query.outerjoin(CaseState, CaseState.state_id == Cases.state_id)
        keys = [sa_case(*[(func.lower(CaseState.state_name) == s.lower(), i) for i, s in enumerate(qv.STAGES)],
                        else_=-1)]
    elif sort == 'owner':
        owner = aliased(User)
        query = query.outerjoin(owner, owner.id == Cases.owner_id)
        keys = [func.lower(func.coalesce(owner.name, owner.user, ''))]
    elif sort == 'idle':
        last = _last_activity_subquery()
        query = query.outerjoin(last, last.c.case_id == Cases.case_id)
        keys = [func.coalesce(last.c.last, cast(Cases.open_date, DateTime))]
        reverse = True
    else:  # age
        keys = [Cases.open_date]
        reverse = True
    descending = (direction == 'desc') != reverse
    order = [k.desc().nulls_last() if descending else k.asc().nulls_last() for k in keys]
    order.append(Cases.case_id.desc() if descending else Cases.case_id.asc())
    return query.order_by(*order)


def last_activity_for(case_ids):
    """{case_id: newest activity_date} of the given cases (absent when the log holds nothing for one)."""
    ids = [i for i in case_ids if i is not None]
    if not ids:
        return {}
    rows = (db.session.query(UserActivity.case_id, func.max(UserActivity.activity_date))
            .filter(UserActivity.case_id.in_(ids))
            .group_by(UserActivity.case_id).all())
    return {cid: when for cid, when in rows if when is not None}


def _iso(moment):
    return moment.replace(microsecond=0).isoformat() + 'Z' if moment else None


def _user(user):
    if user is None:
        return None
    return {'id': user.id, 'name': user.name or user.user, 'login': user.user}


def row(case, last=None, now=None):
    now = now or datetime.utcnow()
    opened = case.open_date
    moment = last or (datetime.combine(opened, time()) if opened else None)
    state, severity = case.state, case.severity
    tags = [t.tag_title for t in (case.tags or []) if t.tag_title]
    return {
        'case_id': case.case_id,
        'title': display_title(case.name, case.case_id),
        'soc_id': case.soc_id or '',
        'customer': {'id': case.client_id, 'name': case.client.name if case.client else ''},
        'state': ({'id': state.state_id, 'name': state.state_name, 'stage': qv.stage_index(state.state_name)}
                  if state else None),
        'severity': {'id': severity.severity_id, 'name': severity.severity_name} if severity else None,
        'owner': _user(case.owner),
        'tags': tags,
        'open_date': opened.isoformat() if opened else None,
        'close_date': case.close_date.isoformat() if case.close_date else None,
        'closed': case.close_date is not None,
        'age_days': (now.date() - opened).days if opened else None,
        'last_activity': _iso(last),
        'idle_days': max(0, (now - moment).days) if moment else None,
    }


def queue_page(user_id, params, now=None):
    now = now or datetime.utcnow()
    query = _base(user_id, params['closed'])
    clause = condition(params['tree'], now.date())
    if clause is not None:
        query = query.filter(clause)
    search = _search_clause(params['q'])
    if search is not None:
        query = query.filter(search)
    total = query.order_by(None).count()
    per_page = params['per_page']
    last_page = max(1, math.ceil(total / per_page))
    page = min(params['page'], last_page)
    cases = (_sorted(query, params['sort'], params['dir'])
             .options(joinedload(Cases.client), joinedload(Cases.owner), joinedload(Cases.state),
                      joinedload(Cases.severity), selectinload(Cases.tags))
             .offset((page - 1) * per_page).limit(per_page).all())
    activity = last_activity_for([c.case_id for c in cases])
    return {
        'total': total, 'page': page, 'per_page': per_page, 'last_page': last_page,
        'sort': params['sort'], 'dir': params['dir'],
        'data': [row(c, activity.get(c.case_id), now) for c in cases],
    }


def _critical_severity_id():
    sev = Severity.query.filter(func.lower(Severity.severity_name) == 'critical').first()
    return sev.severity_id if sev else None


def kpi_trees(user_id):
    """The filter each chip applies - the same clauses kpis() counts with, so a chip's figure is the list it shows.
    'open' is no filter at all; a deployment without a Critical severity gets no Critical chip filter."""
    critical = _critical_severity_id()

    def one(leaf):
        return {'logic': 'and', 'items': [leaf]}

    return {
        'open': {'logic': 'and', 'items': []},
        'critical': one({'field': 'severity', 'op': 'equals', 'value': critical}) if critical is not None else None,
        'stalled': one({'field': 'open_date', 'op': 'older_than', 'value': qv.STALL_DAYS}),
        'mine': one({'field': 'owner', 'op': 'equals', 'value': user_id}),
    }


def kpis(user_id, now=None):
    today = (now or datetime.utcnow()).date()
    out = {}
    for key, tree in kpi_trees(user_id).items():
        if tree is None:
            out[key] = None
            continue
        query = _base(user_id, False)
        clause = condition(tree, today)
        if clause is not None:
            query = query.filter(clause)
        out[key] = query.order_by(None).count()
    return out


# ------------------------------------------------------------------ the side panel

def _tasks(case_id):
    rows = (db.session.query(TaskStatus.status_name, func.count(CaseTasks.id))
            .outerjoin(TaskStatus, TaskStatus.id == CaseTasks.task_status_id)
            .filter(CaseTasks.task_case_id == case_id)
            .group_by(TaskStatus.status_name).all())
    total = done = canceled = 0
    for name, n in rows:
        total += n
        low = (name or '').strip().lower()
        if low == 'done':
            done += n
        elif low == 'canceled':
            canceled += n
    return {'open': total - done - canceled, 'done': done, 'total': total}


def _summary(case):
    """The cached executive summary (the analyst's edit over the model's text) when there is one, else the
    description. Never generates anything."""
    text = executive_summaries_for([case.case_id]).get(case.case_id)
    if text and text.strip():
        return {'kind': 'executive', 'html': render_markdown_safe(text)}
    if case.description and case.description.strip():
        return {'kind': 'description', 'html': render_markdown_safe(case.description)}
    return None


def case_detail(case_id, can_edit, now=None):
    """The panel for one case; the caller has checked that the user may read it."""
    now = now or datetime.utcnow()
    case = db.session.get(Cases, case_id)
    last = last_activity_for([case_id]).get(case_id)
    out = row(case, last, now)
    classification = case.classification
    note = (case.closing_note or '').strip()
    out.update({
        'name': case.name or '',
        'classification': ({'id': classification.id, 'name': classification.name_expanded or classification.name}
                           if classification else None),
        'outcome': {'id': case.status_id, 'name': _OUTCOMES.get(case.status_id, 'Unknown')},
        'reviewer': _user(case.reviewer),
        'review_status': case.review_status.status_name if case.review_status else None,
        'opened_by': _user(case.user),
        'tasks': _tasks(case_id),
        'summary': _summary(case),
        'closing_note': case.closing_note or '',
        'closing_note_html': render_markdown_safe(note) if case.close_date is not None and note else None,
        'stalled': (case.close_date is None and out['idle_days'] is not None
                    and out['idle_days'] > qv.STALL_DAYS),
        'can_edit': bool(can_edit),
    })
    return out


# ------------------------------------------------------------------ the page

def options(user_id):
    """What the filter's choice fields pick from. Customers: only those of cases the user can open."""
    customers = (db.session.query(Client.client_id, Client.name)
                 .filter(Client.client_id.in_(select(Cases.client_id).where(Cases.case_id.in_(_accessible(user_id)))))
                 .order_by(func.lower(Client.name)).all())
    users = User.query.order_by(func.lower(func.coalesce(User.name, User.user))).all()
    states = CaseState.query.order_by(CaseState.state_id).all()
    return {
        'customers': [{'id': cid, 'name': name or ('#%d' % cid)} for cid, name in customers],
        'severities': [{'id': s.severity_id, 'name': s.severity_name}
                       for s in Severity.query.order_by(Severity.severity_id).all()],
        'states': [{'id': s.state_id, 'name': s.state_name, 'stage': qv.stage_index(s.state_name)} for s in states],
        'classifications': [{'id': c.id, 'name': c.name_expanded or c.name}
                            for c in CaseClassification.query.order_by(CaseClassification.name).all()],
        'outcomes': [{'id': i, 'name': n} for i, n in qv.OUTCOMES],
        'users': [{'id': u.id, 'name': u.name or u.user, 'login': u.user, 'active': bool(u.active)} for u in users],
        'review_statuses': [{'id': r.id, 'name': r.status_name}
                            for r in ReviewStatus.query.order_by(ReviewStatus.id).all()],
    }


def stage_states():
    """{stage name: case_state id} for the track; a stage the deployment lacks is absent."""
    out = {}
    for state in CaseState.query.all():
        idx = qv.stage_index(state.state_name)
        if idx is not None and qv.STAGES[idx] not in out:
            out[qv.STAGES[idx]] = state.state_id
    return out


def saved_filter(filter_id, user_id):
    """A saved queue filter the user may see (shared, or their own private one), or None."""
    row_ = db.session.get(SavedFilter, filter_id) if filter_id else None
    if row_ is None or row_.filter_type != qv.SAVED_FILTER_TYPE:
        return None
    if row_.filter_is_private and row_.created_by != user_id:
        return None
    return row_


def page_state(user, args, now=None):
    """The page's first frame: vocabulary, options, the URL's query and its first page. A bad filter in the URL is
    reported, not raised - the page shows it and offers to clear it."""
    now = now or datetime.utcnow()
    args = dict(args.items()) if hasattr(args, 'items') else dict(args or {})
    sf_id = _int(args.get('sf'))
    sf = saved_filter(sf_id, user.id)
    if sf is not None and not args.get('filter'):
        data = sf.filter_data if isinstance(sf.filter_data, dict) else {}
        args['filter'] = json.dumps(data.get('group') or {'logic': 'and', 'items': []})
        if 'closed' not in args and data.get('showClosed'):
            args['closed'] = '1'
        if 'q' not in args and data.get('search'):
            args['q'] = str(data.get('search'))
    state = {
        'vocab': qv.client_vocab(),
        'options': options(user.id),
        'stage_states': stage_states(),
        'kpi_trees': kpi_trees(user.id),
        'me': {'id': user.id, 'login': user.user, 'name': user.name or user.user},
        'saved_filter_id': sf.filter_id if sf is not None else None,
        'error': None,
        'query': None,
        'result': None,
        'detail': None,
        'kpis': kpis(user.id, now),
    }
    try:
        params = parse_args(args)
    except QueueError as exc:
        state['error'] = exc.message
        return state
    state['query'] = {k: params[k] for k in ('q', 'closed', 'page', 'per_page', 'sort', 'dir')}
    state['query']['filter'] = params['tree']
    state['result'] = queue_page(user.id, params, now)
    state['detail'] = _embedded_detail(args, state['result'], now)
    return state


def _embedded_detail(args, result, now):
    """The side panel of the URL's case (?case=) or the first row, so the panel too is in the first frame."""
    wanted = _int(args.get('case'))
    rows = result['data']
    case_id = wanted if wanted is not None else (rows[0]['case_id'] if rows else None)
    if case_id is None or db.session.get(Cases, case_id) is None:
        return None
    if not ac_fast_check_current_user_has_case_access(case_id, [CaseAccessLevel.read_only,
                                                                CaseAccessLevel.full_access]):
        return None
    can_edit = ac_fast_check_current_user_has_case_access(case_id, [CaseAccessLevel.full_access])
    return case_detail(case_id, can_edit, now)

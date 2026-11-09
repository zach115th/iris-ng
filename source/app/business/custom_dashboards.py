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

"""Custom dashboards (iris-ng, 2026-11-09): stored dashboards of widgets, compiled to SQL the server writes.

  validate_payload(payload)        a dashboard as the browser sends it -> normalised; DashboardError with `issues`
  validate_definition(defn)        sections / filter bar / default range -> (normalised, issues)
  render(user, definition, params) every widget's figures FOR ONE VIEWER: {range, widgets: {id: result}}
  parse_render_args(args, defn)    the view's query string -> render parameters
  list_dashboards / get_view / create / update / delete / clone
  schema(user)                     the vocabulary + the option lists the editor and the filter bar pick from
  presets()                        widget templates, with this deployment's lookup ids
  system_definition(key)           the built-in dashboards (Statistics) - code, never rows

A widget never names a table or a column: it names a source and fields of models.custom_dashboard_vocab, and this
module maps them to SQL. Every widget counts only rows the viewer may open: cases with any access but deny_all (the
case queue's rule) and what those cases hold; alerts of the viewer's customers (every alert for a server
administrator). A shared dashboard therefore shows each viewer their own figures.
"""

import copy
import json
import re
import uuid as _uuid
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import and_
from sqlalchemy import case as sa_case
from sqlalchemy import cast
from sqlalchemy import DateTime
from sqlalchemy import func
from sqlalchemy import literal
from sqlalchemy import literal_column
from sqlalchemy import not_
from sqlalchemy import null
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import text

from app import app
from app import db
from app.business import case_queue as cq
from app.iris_engine.access_control.utils import ac_user_has_permission
from app.models import custom_dashboard_vocab as dv
from app.models.alerts import Alert
from app.models.alerts import AlertCaseAssociation
from app.models.alerts import AlertResolutionStatus
from app.models.alerts import AlertStatus
from app.models.alerts import Severity
from app.models.authorization import Permissions
from app.models.authorization import User
from app.models.authorization import UserClient
from app.models.cases import Cases
from app.models.cases import CasesEvent
from app.models.cases import CaseState
from app.models.cases import CaseTags
from app.models.models import AnalysisStatus
from app.models.models import AssetsType
from app.models.models import CaseAssets
from app.models.models import CaseClassification
from app.models.models import CaseEventCategory
from app.models.models import CaseReceivedFile
from app.models.models import CaseTasks
from app.models.models import CaseTimeEntry
from app.models.models import Client
from app.models.models import CustomDashboard
from app.models.models import EventCategory
from app.models.models import EvidenceTypes
from app.models.models import Ioc
from app.models.models import IocType
from app.models.models import Notes
from app.models.models import ReviewStatus
from app.models.models import Tags
from app.models.models import TaskAssignee
from app.models.models import TaskStatus
from app.models.models import Tlp

L = dv.LIMITS
_ID = re.compile(r'^[A-Za-z0-9_-]{1,40}$')
_COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')
_TAG_VALUE = re.compile(r'^[^:"]+:[^="]+="(.*)"$')
STATEMENT_TIMEOUT_MS = 15000


class DashboardError(Exception):
    def __init__(self, message, status=400, issues=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.issues = issues or []


def _now():
    return datetime.utcnow()


def _iso(moment):
    if moment is None:
        return None
    if isinstance(moment, datetime):
        return moment.replace(microsecond=0).isoformat() + 'Z'
    return moment.isoformat()


def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r'\s*\d{1,12}\s*', value):
        return int(value)
    return None


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if value == value and abs(value) < 1e15 else None
    if isinstance(value, str) and re.fullmatch(r'\s*-?\d{1,15}(\.\d{1,6})?\s*', value):
        text_ = value.strip()
        return float(text_) if '.' in text_ else int(text_)
    return None


def _plain(value):
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        return round(value, 4)
    return value


# ------------------------------------------------------------------ the SQL each field maps to

class _Spec:
    """A source in SQL: its table, primary key, the column holding its case (None for alerts), whether its
    statements join cases (for the customer), and field -> expression for the single-valued fields."""

    def __init__(self, model, pk, case_col, join_case, cols, csv=None, date_only=()):
        self.model = model
        self.pk = pk
        self.case_col = case_col
        self.join_case = join_case
        self.cols = cols
        self.csv = csv or {}
        self.date_only = set(date_only)


def _case_cols(case_col):
    return {'case': lambda: case_col, 'customer': lambda: Cases.client_id}


def _verdict_expr():
    return sa_case(*[(CasesEvent.event_verdict == code, n) for n, code, _label in dv.VERDICTS], else_=0)


_SPECS = {}


def _spec(source):
    if not _SPECS:
        _SPECS.update(_build_specs())
    return _SPECS[source]


def _build_specs():
    specs = {
        'cases': _Spec(Cases, Cases.case_id, Cases.case_id, False, {
            'title': cq._title_sql,
            'soc_id': lambda: Cases.soc_id,
            'case': lambda: Cases.case_id,
            'customer': lambda: Cases.client_id,
            'severity': lambda: Cases.severity_id,
            'state': lambda: Cases.state_id,
            'classification': lambda: Cases.classification_id,
            'outcome': lambda: Cases.status_id,
            'owner': lambda: Cases.owner_id,
            'opened_by': lambda: Cases.user_id,
            'reviewer': lambda: Cases.reviewer_id,
            'review_status': lambda: Cases.review_status_id,
            'closed': lambda: Cases.close_date.isnot(None),
            'open_date': lambda: Cases.open_date,
            'close_date': lambda: Cases.close_date,
            'age_days': lambda: func.coalesce(Cases.close_date, literal(datetime.utcnow().date())) - Cases.open_date,
            'resolve_days': lambda: sa_case((Cases.close_date.isnot(None), Cases.close_date - Cases.open_date),
                                            else_=null()),
        }, date_only=('open_date', 'close_date')),
        'alerts': _Spec(Alert, Alert.alert_id, None, False, {
            'title': lambda: Alert.alert_title,
            'source': lambda: Alert.alert_source,
            'customer': lambda: Alert.alert_customer_id,
            'severity': lambda: Alert.alert_severity_id,
            'status': lambda: Alert.alert_status_id,
            'resolution': lambda: Alert.alert_resolution_status_id,
            'classification': lambda: Alert.alert_classification_id,
            'owner': lambda: Alert.alert_owner_id,
            'escalated': lambda: select(AlertCaseAssociation.alert_id)
                                 .where(AlertCaseAssociation.alert_id == Alert.alert_id).exists(),
            'created': lambda: Alert.alert_creation_time,
            'event_time': lambda: Alert.alert_source_event_time,
            'detect_minutes': lambda: func.extract('epoch', Alert.alert_creation_time
                                                   - Alert.alert_source_event_time) / 60.0,
        }, csv={'tags': lambda: Alert.alert_tags}),
        'iocs': _Spec(Ioc, Ioc.ioc_id, Ioc.case_id, True, dict(_case_cols(Ioc.case_id), **{
            'value': lambda: Ioc.ioc_value,
            'type': lambda: Ioc.ioc_type_id,
            'tlp': lambda: Ioc.ioc_tlp_id,
            'case_open_date': lambda: Cases.open_date,
        }), csv={'tags': lambda: Ioc.ioc_tags}, date_only=('case_open_date',)),
        'assets': _Spec(CaseAssets, CaseAssets.asset_id, CaseAssets.case_id, True, dict(_case_cols(CaseAssets.case_id), **{
            'name': lambda: CaseAssets.asset_name,
            'ip': lambda: CaseAssets.asset_ip,
            'type': lambda: CaseAssets.asset_type_id,
            'compromise': lambda: CaseAssets.asset_compromise_status_id,
            'analysis': lambda: CaseAssets.analysis_status_id,
            'added': lambda: CaseAssets.date_added,
        }), csv={'tags': lambda: CaseAssets.asset_tags}),
        'tasks': _Spec(CaseTasks, CaseTasks.id, CaseTasks.task_case_id, True, dict(_case_cols(CaseTasks.task_case_id), **{
            'title': lambda: CaseTasks.task_title,
            'status': lambda: CaseTasks.task_status_id,
            'opened_by': lambda: CaseTasks.task_userid_open,
            'opened': lambda: CaseTasks.task_open_date,
        }), csv={'tags': lambda: CaseTasks.task_tags}),
        'events': _Spec(CasesEvent, CasesEvent.event_id, CasesEvent.case_id, True, dict(_case_cols(CasesEvent.case_id), **{
            'title': lambda: CasesEvent.event_title,
            'category': lambda: select(CaseEventCategory.category_id)
                                .where(CaseEventCategory.event_id == CasesEvent.event_id).limit(1).scalar_subquery(),
            'verdict': _verdict_expr,
            'flagged': lambda: func.coalesce(CasesEvent.event_is_flagged, False),
            'in_summary': lambda: func.coalesce(CasesEvent.event_in_summary, True),
            'source': lambda: CasesEvent.event_source,
            'added_by': lambda: CasesEvent.user_id,
            'event_date': lambda: CasesEvent.event_date,
            'added': lambda: CasesEvent.event_added,
        }), csv={'tags': lambda: CasesEvent.event_tags}),
        'evidence': _Spec(CaseReceivedFile, CaseReceivedFile.id, CaseReceivedFile.case_id, True,
                          dict(_case_cols(CaseReceivedFile.case_id), **{
                              'filename': lambda: CaseReceivedFile.filename,
                              'type': lambda: CaseReceivedFile.type_id,
                              'added_by': lambda: CaseReceivedFile.user_id,
                              'size': lambda: CaseReceivedFile.file_size,
                              'added': lambda: CaseReceivedFile.date_added,
                              'acquired': lambda: CaseReceivedFile.acquisition_date,
                          })),
        'notes': _Spec(Notes, Notes.note_id, Notes.note_case_id, True, dict(_case_cols(Notes.note_case_id), **{
            'title': lambda: Notes.note_title,
            'author': lambda: Notes.note_user,
            'created': lambda: Notes.note_creationdate,
            'updated': lambda: Notes.note_lastupdate,
        }), csv={'tags': lambda: Notes.note_tags}),
        'time_entries': _Spec(CaseTimeEntry, CaseTimeEntry.id, CaseTimeEntry.case_id, True,
                              dict(_case_cols(CaseTimeEntry.case_id), **{
                                  'user': lambda: CaseTimeEntry.user_id,
                                  'minutes': lambda: CaseTimeEntry.minutes,
                                  'date': lambda: CaseTimeEntry.activity_date,
                              }), date_only=('date',)),
    }
    return specs


def _many(source, field):
    """A field a row holds several values of: the case tags, a comma-separated tag column, task assignees."""
    if source == 'cases' and field == 'tags':
        return 'case_tags'
    if source == 'tasks' and field == 'assignee':
        return 'assignee'
    if field in _spec(source).csv:
        return 'csv'
    return None


def _col(source, field):
    return _spec(source).cols[field]()


# ------------------------------------------------------------------ filters (the case queue's tree, per source)

def _filter_value(source, field, op, value):
    f = dv.FIELDS[source][field]
    label, kind = f['label'], f['kind']
    if op in dv.DAY_OPS:
        days = _int(value)
        if days is None or days > L['days']:
            raise DashboardError('%s: give a number of days from 0 to %d.' % (label, L['days']))
        return days
    if kind == 'choice':
        if f['options'] == 'users' and value == dv.ME:
            return dv.ME
        number = _int(value)
        if number is None:
            raise DashboardError('%s: pick a value.' % label)
        return number
    if kind == 'number':
        number = _number(value)
        if number is None:
            raise DashboardError('%s: give a number.' % label)
        return number
    if kind == 'date':
        try:
            return date.fromisoformat(str(value).strip()).isoformat()
        except (TypeError, ValueError):
            raise DashboardError('%s: give a date as YYYY-MM-DD.' % label)
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise DashboardError('%s needs a value.' % label)
    text_ = str(value).strip()
    if not text_:
        raise DashboardError('%s needs a value.' % label)
    if len(text_) > L['value']:
        raise DashboardError('%s: a value is at most %d characters.' % (label, L['value']))
    if kind == 'csv' and op in ('has', 'has_not') and ',' in text_:
        raise DashboardError('%s: a tag holds no comma.' % label)
    return text_


def _leaf(source, item, count):
    if not isinstance(item, dict):
        raise DashboardError('A filter condition must be an object.')
    field, op = item.get('field'), item.get('op')
    if not isinstance(field, str) or field not in dv.FIELDS[source]:
        raise DashboardError('Unknown field for %s: %s' % (dv.SOURCES[source][0], str(field)[:40]))
    if op not in dv.field_ops(source, field):
        raise DashboardError('%s cannot use the operator "%s".' % (dv.FIELDS[source][field]['label'], str(op)[:30]))
    count[0] += 1
    if count[0] > L['conditions']:
        raise DashboardError('A filter holds at most %d conditions.' % L['conditions'])
    if op in dv.NO_VALUE_OPS:
        return {'field': field, 'op': op, 'value': None}
    return {'field': field, 'op': op, 'value': _filter_value(source, field, op, item.get('value'))}


def _group(source, node, depth, count):
    if not isinstance(node, dict):
        raise DashboardError('A filter group must be an object.')
    logic = node.get('logic', 'and')
    if logic not in ('and', 'or'):
        raise DashboardError('A filter group matches "and" or "or".')
    items = node.get('items', [])
    if not isinstance(items, list):
        raise DashboardError('A filter group holds a list of items.')
    out = []
    for item in items:
        if isinstance(item, dict) and 'items' in item:
            if depth + 1 >= L['depth']:
                raise DashboardError('Sub-groups nest at most %d levels deep.' % (L['depth'] - 1))
            sub = _group(source, item, depth + 1, count)
            if sub['items']:
                out.append(sub)
        else:
            out.append(_leaf(source, item, count))
    return {'logic': logic, 'items': out}


def validate_filter(source, tree):
    """A filter tree for one source -> normalised (empty sub-groups dropped). DashboardError on the first fault."""
    if tree is None or tree == {}:
        return {'logic': 'and', 'items': []}
    return _group(source, tree, 0, [0])


def _date_bounds(day, date_only):
    """A day as the column compares it: (start, end-exclusive)."""
    if date_only:
        return day, day + timedelta(days=1)
    start = datetime.combine(day, time.min)
    return start, start + timedelta(days=1)


def _csv_norm(column):
    return literal(',') + func.regexp_replace(func.lower(func.btrim(func.coalesce(column, ''))),
                                              r'\s*,\s*', ',', 'g') + literal(',')


def _many_exists(source, field, condition=None):
    """EXISTS a value of a many-valued field (optionally one matching `condition` on `v`)."""
    kind = _many(source, field)
    if kind == 'case_tags':
        sub = (select(CaseTags.case_id).join(Tags, Tags.id == CaseTags.tag_id)
               .where(CaseTags.case_id == Cases.case_id))
        if condition is not None:
            sub = sub.where(condition(Tags.tag_title))
        return sub.exists()
    if kind == 'assignee':
        sub = select(TaskAssignee.task_id).where(TaskAssignee.task_id == CaseTasks.id)
        if condition is not None:
            sub = sub.where(condition(TaskAssignee.user_id))
        return sub.exists()
    raise ValueError(kind)


def _leaf_clause(source, leaf, ctx):
    field, op, value = leaf['field'], leaf['op'], leaf['value']
    f = dv.FIELDS[source][field]
    kind = f['kind']
    spec = _spec(source)
    many = _many(source, field)
    if value == dv.ME:
        value = ctx['uid']
    if many == 'assignee':
        if op == 'equals':
            return _many_exists(source, field, lambda c: c == value)
        if op == 'not_equals':
            return not_(_many_exists(source, field, lambda c: c == value))
        return _many_exists(source, field) if op == 'not_empty' else not_(_many_exists(source, field))
    if kind in ('tags', 'csv'):
        if many == 'case_tags':
            if op == 'empty':
                return not_(_many_exists(source, field))
            if op == 'not_empty':
                return _many_exists(source, field)
            if op in ('has', 'has_not'):
                expr = _many_exists(source, field, lambda c: func.lower(c) == value.lower())
            else:
                expr = _many_exists(source, field, lambda c: c.ilike('%' + cq._like(value) + '%', escape='\\'))
            return not_(expr) if op in ('has_not', 'not_contains') else expr
        column = spec.csv[field]()
        if op == 'empty':
            return func.btrim(func.replace(func.coalesce(column, ''), ',', '')) == ''
        if op == 'not_empty':
            return func.btrim(func.replace(func.coalesce(column, ''), ',', '')) != ''
        if op in ('has', 'has_not'):
            expr = _csv_norm(column).like('%,' + cq._like(value.lower()) + ',%', escape='\\')
        else:
            expr = func.coalesce(column, '').ilike('%' + cq._like(value) + '%', escape='\\')
        return not_(expr) if op in ('has_not', 'not_contains') else expr
    column = _col(source, field)
    if kind == 'text':
        return cq._text_clause(column, op, value)
    if kind == 'bool':
        return column.is_(True) if op == 'is_true' else or_(column.is_(False), column.is_(None))
    if kind == 'number':
        if op == 'empty':
            return column.is_(None)
        if op == 'not_empty':
            return column.isnot(None)
        if op == 'not_equals':
            return or_(column.is_(None), column != value)
        return {'equals': column == value, 'greater': column > value, 'less': column < value}[op]
    if kind == 'choice':
        if op == 'equals':
            return column == value
        if op == 'not_equals':
            return or_(column.is_(None), column != value)
        return column.is_(None) if op == 'empty' else column.isnot(None)
    # date
    date_only = field in spec.date_only
    if op == 'empty':
        return column.is_(None)
    if op == 'not_empty':
        return column.isnot(None)
    if op in dv.DAY_OPS:
        edge = (ctx['today'] - timedelta(days=value)) if date_only else (ctx['now'] - timedelta(days=value))
        return column < edge if op == 'older_than' else column >= edge
    lo, hi = _date_bounds(date.fromisoformat(value), date_only)
    return {'on': and_(column >= lo, column < hi), 'before': column < lo, 'after': column >= hi}[op]


def _condition(source, tree, ctx):
    clauses = []
    for item in (tree or {}).get('items', []):
        clause = _condition(source, item, ctx) if 'items' in item else _leaf_clause(source, item, ctx)
        if clause is not None:
            clauses.append(clause)
    if not clauses:
        return None
    return and_(*clauses) if tree.get('logic', 'and') == 'and' else or_(*clauses)


# ------------------------------------------------------------------ validation

def _text(value, limit, required=False):
    if value is None:
        value = ''
    if not isinstance(value, str):
        return None
    value = value.strip()
    if required and not value:
        return None
    return value[:limit] if len(value) <= limit else None


def _widget(raw, path, issues, seen):
    def bad(msg):
        issues.append('%s: %s' % (path, msg))

    if not isinstance(raw, dict):
        bad('a widget must be an object.')
        return None
    wid = raw.get('id')
    if not isinstance(wid, str) or not _ID.match(wid) or wid in seen:
        wid = 'w' + _uuid.uuid4().hex[:10]
    seen.add(wid)
    name = _text(raw.get('name'), L['widget_name'], required=True)
    if name is None:
        bad('a name is required (at most %d characters).' % L['widget_name'])
        name = 'Widget'
    source = raw.get('source')
    if source not in dv.SOURCES:
        bad('the source must be one of %s.' % ', '.join(dv.SOURCES))
        return None
    fields = dv.FIELDS[source]

    measure = raw.get('measure') or {'type': 'count'}
    if isinstance(measure, str):
        measure = {'type': measure}
    mtype = measure.get('type') if isinstance(measure, dict) else None
    if mtype not in dv.MEASURES:
        bad('the measure must be one of %s.' % ', '.join(dv.MEASURES))
        return None
    m = {'type': mtype, 'field': None, 'filter': None}
    if mtype in dv.NUMBER_MEASURES:
        if measure.get('field') not in dv.numeric(source):
            bad('%s needs a number field of %s (%s).' % (dv.MEASURES[mtype], dv.SOURCES[source][0],
                                                         ', '.join(dv.numeric(source)) or 'none'))
            return None
        m['field'] = measure['field']
    elif mtype == 'distinct':
        if measure.get('field') not in dv.distinctable(source):
            bad('Count distinct needs a field of %s (%s).' % (dv.SOURCES[source][0], ', '.join(dv.distinctable(source))))
            return None
        m['field'] = measure['field']
    elif mtype == 'share':
        try:
            m['filter'] = validate_filter(source, measure.get('filter'))
        except DashboardError as exc:
            bad('the share filter: %s' % exc.message)
            return None
        if not m['filter']['items']:
            bad('a share needs a filter: the rows it counts as matching.')
            return None

    chart = raw.get('chart', 'number')
    if chart not in dv.CHARTS:
        bad('the chart must be one of %s.' % ', '.join(dv.CHARTS))
        return None
    group_by = raw.get('group_by') or None
    split_by = raw.get('split_by') or None
    if mtype == 'rows':
        if chart != 'table':
            bad('a list of rows shows as a table.')
            chart = 'table'
        group_by = split_by = None
    if group_by is not None and group_by not in dv.groupable(source):
        bad('group by one of %s.' % ', '.join(dv.groupable(source)))
        return None
    if chart == 'number':
        if group_by or split_by:
            bad('a number shows one figure: no group by.')
            group_by = split_by = None
    elif mtype != 'rows' and group_by is None:
        bad('a %s needs a field to group by.' % dv.CHARTS[chart].lower())
        return None
    bucket = None
    if group_by and fields[group_by]['kind'] == 'date':
        bucket = raw.get('bucket') or 'auto'
        if bucket not in dv.TIME_BUCKETS:
            bad('the time bucket must be one of %s.' % ', '.join(dv.TIME_BUCKETS))
            bucket = 'auto'
    if split_by is not None:
        if chart not in dv.SPLIT_CHARTS:
            bad('only %s charts split into series.' % '/'.join(dv.SPLIT_CHARTS))
            split_by = None
        elif split_by not in dv.groupable(source) or fields[split_by]['kind'] == 'date' or split_by == group_by:
            bad('split by another non-date field one can group by.')
            split_by = None

    try:
        flt = validate_filter(source, raw.get('filter'))
    except DashboardError as exc:
        bad('the filter: %s' % exc.message)
        flt = {'logic': 'and', 'items': []}

    wrange = raw.get('range', 'dashboard')
    if wrange not in dv.WIDGET_RANGES:
        bad('the range must be one of %s.' % ', '.join(dv.WIDGET_RANGES))
        wrange = 'dashboard'
    width = raw.get('width', 'half')
    if width not in dv.WIDTHS:
        bad('the width must be one of %s.' % ', '.join(dv.WIDTHS))
        width = 'half'

    out = {'id': wid, 'name': name, 'source': source, 'measure': m, 'group_by': group_by, 'bucket': bucket,
           'split_by': split_by, 'filter': flt, 'range': wrange, 'chart': chart, 'width': width,
           'order': None, 'limit': None, 'columns': None, 'sort': None, 'options': {}}

    if mtype == 'rows':
        cols = raw.get('columns') or []
        if not isinstance(cols, list):
            bad('columns must be a list of fields.')
            cols = []
        title = dv.ROW_TITLE[source]
        clean = [title]
        for c in cols:
            if c in fields and c not in clean:
                clean.append(c)
            elif c not in fields:
                bad('unknown column for %s: %s' % (dv.SOURCES[source][0], str(c)[:40]))
        if len(clean) > L['columns']:
            bad('a table shows at most %d columns.' % L['columns'])
            clean = clean[:L['columns']]
        out['columns'] = clean
        sort = raw.get('sort') or {}
        sfield = sort.get('field') if isinstance(sort, dict) else None
        sdir = sort.get('dir') if isinstance(sort, dict) else None
        default_sort = dv.SOURCES[source][1]
        if sfield is None:
            sfield = default_sort
        if sfield not in fields or _many(source, sfield):
            bad('sort by a single-valued field of %s.' % dv.SOURCES[source][0])
            sfield = default_sort
        out['sort'] = {'field': sfield, 'dir': sdir if sdir in ('asc', 'desc') else 'desc'}
        limit = _int(raw.get('limit')) if raw.get('limit') is not None else 10
        if limit is None or not 1 <= limit <= L['rows']:
            bad('list 1 to %d rows.' % L['rows'])
            limit = 10
        out['limit'] = limit
    elif group_by and bucket is None:
        order = raw.get('order') or 'value_desc'
        if order not in dv.SORTS:
            bad('the order must be one of %s.' % ', '.join(dv.SORTS))
            order = 'value_desc'
        out['order'] = order
        limit = _int(raw.get('limit')) if raw.get('limit') is not None else L['default_groups']
        if limit is None or not 1 <= limit <= L['groups']:
            bad('show 1 to %d groups.' % L['groups'])
            limit = L['default_groups']
        out['limit'] = limit

    opts = raw.get('options') or {}
    if not isinstance(opts, dict):
        bad('options must be an object.')
        opts = {}
    clean_opts = {}
    color = opts.get('color')
    if color not in (None, ''):
        if isinstance(color, str) and _COLOR.match(color):
            clean_opts['color'] = color.lower()
        else:
            bad('a colour is #rrggbb.')
    thresholds = opts.get('thresholds') or []
    if not isinstance(thresholds, list) or len(thresholds) > L['thresholds']:
        bad('at most %d thresholds.' % L['thresholds'])
        thresholds = []
    clean_t = []
    for i, t in enumerate(thresholds):
        if not isinstance(t, dict) or t.get('op') not in dv.THRESHOLD_OPS or _number(t.get('value')) is None \
                or not (isinstance(t.get('color'), str) and _COLOR.match(t.get('color'))):
            bad('threshold %d: {op: gte|lte, value: a number, color: #rrggbb}.' % (i + 1))
            continue
        clean_t.append({'op': t['op'], 'value': _number(t['value']), 'color': t['color'].lower()})
    if clean_t:
        clean_opts['thresholds'] = clean_t
    if group_by and bucket is None and mtype != 'rows':
        clean_opts['other'] = opts.get('other', True) is not False
    if group_by and mtype != 'rows' and opts.get('hide_none') is True:
        clean_opts['hide_none'] = True
    if group_by and fields[group_by]['kind'] in ('tags', 'csv'):
        for key in ('match', 'exclude'):
            v = opts.get(key)
            if v not in (None, ''):
                v = _text(v, L['match_text'])
                if v:
                    clean_opts[key] = v
                else:
                    bad('%s is text of at most %d characters.' % (key, L['match_text']))
    out['options'] = clean_opts
    return out


def validate_definition(defn):
    """-> (normalised definition, issues). Faulty widgets are dropped from the normalised copy."""
    issues = []
    if defn is None:
        defn = {}
    if not isinstance(defn, dict):
        return blank_definition(), ['The definition must be an object.']
    sections_raw = defn.get('sections', [])
    if not isinstance(sections_raw, list):
        issues.append('sections must be a list.')
        sections_raw = []
    if len(sections_raw) > L['sections']:
        issues.append('A dashboard holds at most %d sections.' % L['sections'])
        sections_raw = sections_raw[:L['sections']]
    seen_w, seen_s, sections, total = set(), set(), [], 0
    for si, s in enumerate(sections_raw):
        path = 'sections[%d]' % si
        if not isinstance(s, dict):
            issues.append('%s must be an object.' % path)
            continue
        sid = s.get('id')
        if not isinstance(sid, str) or not _ID.match(sid) or sid in seen_s:
            sid = 's' + _uuid.uuid4().hex[:10]
        seen_s.add(sid)
        title = _text(s.get('title'), L['section_title'])
        if title is None:
            issues.append('%s.title: at most %d characters.' % (path, L['section_title']))
            title = ''
        desc = _text(s.get('description'), L['description'])
        if desc is None:
            issues.append('%s.description: at most %d characters.' % (path, L['description']))
            desc = ''
        widgets_raw = s.get('widgets', [])
        if not isinstance(widgets_raw, list):
            issues.append('%s.widgets must be a list.' % path)
            widgets_raw = []
        widgets = []
        for wi, w in enumerate(widgets_raw):
            total += 1
            if total > L['widgets']:
                issues.append('A dashboard holds at most %d widgets.' % L['widgets'])
                break
            clean = _widget(w, '%s.widgets[%d]' % (path, wi), issues, seen_w)
            if clean is not None:
                widgets.append(clean)
        sections.append({'id': sid, 'title': title, 'description': desc, 'widgets': widgets})

    bar_raw = defn.get('filter_bar', [])
    if not isinstance(bar_raw, list):
        issues.append('filter_bar must be a list.')
        bar_raw = []
    bar, keys = [], set()
    for i, e in enumerate(bar_raw):
        key = e.get('key') if isinstance(e, dict) else None
        if key not in dv.FILTER_BAR:
            issues.append('filter_bar[%d].key must be one of %s.' % (i, ', '.join(dv.FILTER_BAR)))
            continue
        if key in keys:
            issues.append('filter_bar[%d]: %s is already in the filter bar.' % (i, key))
            continue
        label = _text(e.get('label'), 60) or dv.FILTER_BAR[key][0]
        keys.add(key)
        bar.append({'key': key, 'label': label})
    if len(bar) > L['filter_bar']:
        issues.append('The filter bar holds at most %d entries.' % L['filter_bar'])
        bar = bar[:L['filter_bar']]
    default_range = defn.get('default_range', dv.DEFAULT_RANGE)
    if default_range not in [k for k, _l, _d in dv.RANGES]:
        issues.append('default_range must be one of %s.' % ', '.join(k for k, _l, _d in dv.RANGES))
        default_range = dv.DEFAULT_RANGE
    return {'sections': sections, 'filter_bar': bar, 'default_range': default_range}, issues


def blank_definition():
    return {'sections': [], 'filter_bar': [], 'default_range': dv.DEFAULT_RANGE}


def validate_payload(payload, partial=False):
    """{name, description, is_shared, definition} -> normalised; DashboardError (with every issue) when faulty.
    `partial`: absent keys stay absent (an update)."""
    if not isinstance(payload, dict):
        raise DashboardError('The dashboard must be an object.')
    try:
        size = len(json.dumps(payload))
    except (TypeError, ValueError):
        raise DashboardError('The dashboard is not valid JSON.')
    if size > L['definition_bytes']:
        raise DashboardError('The dashboard is too large (at most %d bytes).' % L['definition_bytes'])
    out, issues = {}, []
    if not partial or 'name' in payload:
        name = _text(payload.get('name'), L['name'], required=True)
        if name is None:
            issues.append('name: required, at most %d characters.' % L['name'])
        out['name'] = name
    if not partial or 'description' in payload:
        desc = _text(payload.get('description'), L['description'])
        if desc is None:
            issues.append('description: at most %d characters.' % L['description'])
        out['description'] = desc or None
    if not partial or 'is_shared' in payload:
        shared = payload.get('is_shared', False)
        if not isinstance(shared, bool):
            issues.append('is_shared: true or false.')
            shared = False
        out['is_shared'] = shared
    if not partial or 'definition' in payload:
        out['definition'], more = validate_definition(payload.get('definition'))
        issues.extend(more)
    if issues:
        raise DashboardError('The dashboard has %d problem%s.' % (len(issues), '' if len(issues) == 1 else 's'),
                             issues=issues)
    return out


# ------------------------------------------------------------------ labels

_LOOKUPS = {
    'customers': lambda: (Client.client_id, Client.name),
    'users': lambda: (User.id, func.coalesce(func.nullif(User.name, ''), User.user)),
    'severities': lambda: (Severity.severity_id, Severity.severity_name),
    'states': lambda: (CaseState.state_id, CaseState.state_name),
    'classifications': lambda: (CaseClassification.id, func.coalesce(CaseClassification.name_expanded,
                                                                      CaseClassification.name)),
    'review_statuses': lambda: (ReviewStatus.id, ReviewStatus.status_name),
    'alert_statuses': lambda: (AlertStatus.status_id, AlertStatus.status_name),
    'alert_resolutions': lambda: (AlertResolutionStatus.resolution_status_id,
                                  AlertResolutionStatus.resolution_status_name),
    'ioc_types': lambda: (IocType.type_id, IocType.type_name),
    'tlps': lambda: (Tlp.tlp_id, Tlp.tlp_name),
    'asset_types': lambda: (AssetsType.asset_id, AssetsType.asset_name),
    'analysis_statuses': lambda: (AnalysisStatus.id, AnalysisStatus.name),
    'task_statuses': lambda: (TaskStatus.id, TaskStatus.status_name),
    'event_categories': lambda: (EventCategory.id, EventCategory.name),
    'evidence_types': lambda: (EvidenceTypes.id, EvidenceTypes.name),
}
_FIXED = {
    'outcomes': lambda: dict(dv.OUTCOMES),
    'compromise_statuses': lambda: dict(dv.COMPROMISE_STATUSES),
    'verdicts': lambda: {n: label for n, _code, label in dv.VERDICTS},
}


def _labels(options_source, ids):
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    if options_source in _FIXED:
        table = _FIXED[options_source]()
        return {i: table.get(i, '#%s' % i) for i in ids}
    if options_source == 'cases':
        rows = db.session.execute(select(Cases.case_id, Cases.name).where(Cases.case_id.in_(ids))).all()
        return {cid: '#%d %s' % (cid, cq.display_title(name)) for cid, name in rows}
    id_col, name_col = _LOOKUPS[options_source]()
    rows = db.session.execute(select(id_col, name_col).where(id_col.in_(ids))).all()
    found = {i: (n or '#%s' % i) for i, n in rows}
    return {i: found.get(i, '#%s' % i) for i in ids}


def _tag_label(tag):
    m = _TAG_VALUE.match(tag or '')
    return m.group(1) if m else tag


def _value_labels(source, field, keys):
    """Display labels for group keys of a field."""
    f = dv.FIELDS[source][field]
    if f['kind'] == 'choice':
        table = _labels(f['options'], keys)
        return {k: (table.get(k) if k is not None else dv.NONE_LABEL) for k in keys}
    if f['kind'] == 'bool':
        yes, no = dv.BOOL_LABELS.get(field, ('Yes', 'No'))
        return {k: (yes if k else no) for k in keys}
    if f['kind'] in ('tags', 'csv'):
        return {k: (_tag_label(k) if k else dv.NONE_LABEL) for k in keys}
    return {k: ((str(k) if k not in (None, '') else dv.NONE_LABEL)) for k in keys}


# ------------------------------------------------------------------ time buckets

_BUCKET_ORDER = ('hour', 'day', 'week', 'month', 'quarter', 'year')


def _floor(moment, bucket):
    if bucket == 'hour':
        return moment.replace(minute=0, second=0, microsecond=0)
    day = datetime(moment.year, moment.month, moment.day)
    if bucket == 'day':
        return day
    if bucket == 'week':
        return day - timedelta(days=day.weekday())
    if bucket == 'month':
        return datetime(moment.year, moment.month, 1)
    if bucket == 'quarter':
        return datetime(moment.year, 3 * ((moment.month - 1) // 3) + 1, 1)
    return datetime(moment.year, 1, 1)


def _next(moment, bucket):
    if bucket == 'hour':
        return moment + timedelta(hours=1)
    if bucket == 'day':
        return moment + timedelta(days=1)
    if bucket == 'week':
        return moment + timedelta(days=7)
    months = {'month': 1, 'quarter': 3, 'year': 12}[bucket]
    total = moment.year * 12 + (moment.month - 1) + months
    return datetime(total // 12, total % 12 + 1, 1)


def _bucket_label(moment, bucket):
    if bucket == 'hour':
        return moment.strftime('%Y-%m-%d %H:00')
    if bucket in ('day', 'week'):
        return moment.strftime('%Y-%m-%d')
    if bucket == 'month':
        return moment.strftime('%Y-%m')
    if bucket == 'quarter':
        return '%d-Q%d' % (moment.year, (moment.month - 1) // 3 + 1)
    return moment.strftime('%Y')


def _points(lo, hi, bucket):
    n, cur, end = 0, _floor(lo, bucket), _floor(hi, bucket)
    while cur <= end:
        n += 1
        if n > dv.MAX_POINTS:
            return n
        cur = _next(cur, bucket)
    return n


def choose_bucket(bucket, lo, hi):
    """The bucket a time axis uses: `auto` picks by the span; any bucket steps up while the axis would hold more than
    MAX_POINTS points."""
    if lo is None or hi is None:
        return 'day' if bucket == 'auto' else bucket
    if bucket == 'auto':
        span = (hi - lo).total_seconds() / 86400.0
        bucket = 'year'
        for days, name in dv.AUTO_BUCKETS:
            if span <= days:
                bucket = name
                break
    i = _BUCKET_ORDER.index(bucket)
    while i < len(_BUCKET_ORDER) - 1 and _points(lo, hi, _BUCKET_ORDER[i]) > dv.MAX_POINTS:
        i += 1
    return _BUCKET_ORDER[i]


def _as_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.min)


# ------------------------------------------------------------------ rendering

def _is_admin(user):
    try:
        return bool(ac_user_has_permission(user, Permissions.server_administrator))
    except Exception:  # noqa: BLE001 - a viewer whose permissions cannot be read is not an administrator
        return False


def _scope(source, ctx):
    spec = _spec(source)
    if source == 'alerts':
        if ctx['admin']:
            return None
        return Alert.alert_customer_id.in_(select(UserClient.client_id).where(UserClient.user_id == ctx['uid']))
    return spec.case_col.in_(cq._accessible(ctx['uid']))


def _range_clause(source, widget, ctx):
    if widget['range'] == 'all' or (ctx['start'] is None and ctx['end'] is None):
        return None
    field = dv.SOURCES[source][1]
    spec = _spec(source)
    column = _col(source, field)
    date_only = field in spec.date_only
    parts = []
    if ctx['start'] is not None:
        parts.append(column >= (ctx['start'].date() if date_only else ctx['start']))
    if ctx['end'] is not None:
        parts.append(column <= (ctx['end'].date() if date_only else ctx['end']))
    return and_(*parts)


def _bar_clauses(source, ctx):
    clauses, ignored = [], []
    for key, value in ctx['bar'].items():
        field = dv.FILTER_BAR[key][2].get(source)
        if field is None:
            ignored.append(key)
            continue
        clauses.append(_leaf_clause(source, {'field': field, 'op': 'equals', 'value': value}, ctx))
    return clauses, ignored


def _ids(widget, ctx):
    source = widget['source']
    spec = _spec(source)
    stmt = select(spec.pk).select_from(spec.model)
    if spec.join_case:
        stmt = stmt.join(Cases, Cases.case_id == spec.case_col)
    where = [_scope(source, ctx), _range_clause(source, widget, ctx), _condition(source, widget['filter'], ctx)]
    bar, ignored = _bar_clauses(source, ctx)
    where.extend(bar)
    stmt = stmt.where(*[w for w in where if w is not None])
    return stmt, ignored


def _dimension(widget, field, ids, bucket):
    """(expression, joins) of a group / split field. Many-valued fields join a (pk, v) subquery, outer, so rows
    without a value land in the '(none)' group."""
    source = widget['source']
    spec = _spec(source)
    kind = _many(source, field)
    opts = widget.get('options') or {}
    if kind is None:
        expr = _col(source, field)
        if dv.FIELDS[source][field]['kind'] == 'date':
            expr = func.date_trunc(bucket, cast(expr, DateTime))
        return expr, []
    if kind == 'case_tags':
        sub = select(CaseTags.case_id.label('pk'), Tags.tag_title.label('v')).join(Tags, Tags.id == CaseTags.tag_id)
        sub = sub.where(CaseTags.case_id.in_(ids), func.btrim(func.coalesce(Tags.tag_title, '')) != '').distinct()
        vcol = Tags.tag_title
    elif kind == 'assignee':
        sub = select(TaskAssignee.task_id.label('pk'), TaskAssignee.user_id.label('v')).where(
            TaskAssignee.task_id.in_(ids)).distinct()
        vcol = None
    else:
        raw = (select(spec.pk.label('pk'),
                      func.btrim(func.unnest(func.string_to_array(spec.csv[field](), ','))).label('v'))
               .where(spec.pk.in_(ids))).subquery()
        sub = select(raw.c.pk, raw.c.v).where(raw.c.v != '').distinct()
        vcol = raw.c.v
    if vcol is not None:
        if opts.get('match'):
            sub = sub.where(vcol.ilike('%' + cq._like(opts['match']) + '%', escape='\\'))
        if opts.get('exclude'):
            sub = sub.where(not_(vcol.ilike('%' + cq._like(opts['exclude']) + '%', escape='\\')))
    sub = sub.subquery()
    return sub.c.v, [lambda stmt, s=sub: stmt.outerjoin(s, s.c.pk == spec.pk)]


def _measure(widget, ctx):
    """(expression, joins) of the widget's measure."""
    source = widget['source']
    spec = _spec(source)
    m = widget['measure']
    if m['type'] == 'count':
        return func.count(func.distinct(spec.pk)), []
    if m['type'] == 'share':
        cond = _condition(source, m['filter'], ctx)
        return (literal(100.0) * func.count(func.distinct(sa_case((cond, spec.pk), else_=null())))
                / func.nullif(func.count(func.distinct(spec.pk)), 0)), []
    if m['type'] == 'distinct' and _many(source, m['field']) == 'assignee':
        sub = select(TaskAssignee.task_id.label('pk'), TaskAssignee.user_id.label('v')).subquery()
        return func.count(func.distinct(sub.c.v)), [lambda stmt, s=sub: stmt.outerjoin(s, s.c.pk == spec.pk)]
    expr = _col(source, m['field'])
    if m['type'] == 'distinct':
        return func.count(func.distinct(expr)), []
    if m['type'] == 'median':
        return func.percentile_cont(0.5).within_group(expr), []
    return getattr(func, m['type'])(expr), []


def _unit(widget):
    m = widget['measure']
    if m['type'] in ('count', 'distinct', 'rows'):
        return 'count'
    if m['type'] == 'share':
        return 'percent'
    return dv.FIELDS[widget['source']][m['field']]['unit'] or 'count'


def _aggregate(widget, ids, ctx, dims, where_extra=None, extra_joins=()):
    """Run the measure grouped by `dims` [(expr, joins)] over the rows `ids` -> list of rows (dims..., value).
    Grouped by the output columns' NAMES: a time bucket's name is a bound parameter and a field can be a
    correlated subquery, and PostgreSQL matches neither between the select list and GROUP BY."""
    source = widget['source']
    spec = _spec(source)
    mexpr, mjoins = _measure(widget, ctx)
    exprs = [d[0] for d in dims]
    stmt = select(*[e.label('g%d' % i) for i, e in enumerate(exprs)], mexpr.label('m')).select_from(spec.model)
    if spec.join_case:
        stmt = stmt.join(Cases, Cases.case_id == spec.case_col)
    for _e, joins in dims:
        for j in joins:
            stmt = j(stmt)
    for j in list(mjoins) + list(extra_joins):
        stmt = j(stmt)
    stmt = stmt.where(spec.pk.in_(ids))
    if where_extra is not None:
        stmt = stmt.where(where_extra)
    if exprs:
        stmt = stmt.group_by(*[literal_column('g%d' % i) for i in range(len(exprs))])
    return db.session.execute(stmt).all()


def _number_result(widget, ids, ctx):
    rows = _aggregate(widget, ids, ctx, [])
    value = rows[0][0] if rows else None
    return {'kind': 'number', 'value': _plain(value)}


def _sort_groups(keys, totals, labels, order):
    if order == 'value_asc':
        return sorted(keys, key=lambda k: (totals.get(k) is None, totals.get(k) or 0, str(labels.get(k))))
    if order == 'label_asc':
        return sorted(keys, key=lambda k: str(labels.get(k)).lower())
    if order == 'label_desc':
        return sorted(keys, key=lambda k: str(labels.get(k)).lower(), reverse=True)
    return sorted(keys, key=lambda k: (totals.get(k) is None, -(totals.get(k) or 0), str(labels.get(k)).lower()))


def _time_span(widget, ids, ctx, field):
    """The axis of a time grouping: the dashboard's range, else the data's own first and last moment."""
    if widget['range'] == 'dashboard' and ctx['start'] is not None:
        return ctx['start'], ctx['end'] or ctx['now']
    source = widget['source']
    spec = _spec(source)
    column = _col(source, field)
    stmt = select(func.min(column), func.max(column)).select_from(spec.model)
    if spec.join_case:
        stmt = stmt.join(Cases, Cases.case_id == spec.case_col)
    lo, hi = db.session.execute(stmt.where(spec.pk.in_(ids))).one()
    return _as_datetime(lo), _as_datetime(hi)


def _grouped_result(widget, ids, ctx):
    source = widget['source']
    gfield, sfield = widget['group_by'], widget['split_by']
    is_time = dv.FIELDS[source][gfield]['kind'] == 'date'
    bucket = None
    if is_time:
        lo, hi = _time_span(widget, ids, ctx, gfield)
        bucket = choose_bucket(widget['bucket'], lo, hi)
    gdim = _dimension(widget, gfield, ids, bucket)
    dims = [gdim]
    if sfield:
        dims.append(_dimension(widget, sfield, ids, None))
    rows = _aggregate(widget, ids, ctx, dims)

    # values[group][series]
    values, series_keys = {}, []
    for r in rows:
        g = r[0]
        s = r[1] if sfield else None
        if is_time:
            g = _floor(_as_datetime(g), bucket) if g is not None else None
        values.setdefault(g, {})[s] = _plain(r[-1])
        if s not in series_keys:
            series_keys.append(s)

    if widget['options'].get('hide_none'):
        values.pop(None, None)
    other = False
    if is_time:
        keys = []
        if lo is not None and hi is not None:
            cur, end = _floor(lo, bucket), _floor(hi, bucket)
            while cur <= end and len(keys) <= dv.MAX_POINTS:
                keys.append(cur)
                cur = _next(cur, bucket)
        keys += sorted(k for k in values if k is not None and k not in keys)
        if None in values:
            keys.append(None)
        labels = {k: (_bucket_label(k, bucket) if k is not None else dv.NONE_LABEL) for k in keys}
        fill = 0 if widget['measure']['type'] in ('count', 'distinct') else None
    else:
        labels = _value_labels(source, gfield, list(values))
        totals = {k: sum(v for v in values[k].values() if v is not None) if any(
            v is not None for v in values[k].values()) else None for k in values}
        ordered = _sort_groups(list(values), totals, labels, widget['order'])
        keys = ordered[:widget['limit']]
        rest = ordered[widget['limit']:]
        fill = 0 if widget['measure']['type'] in ('count', 'distinct') else None
        if rest and widget['options'].get('other', True):
            gexpr = gdim[0]
            top = [k for k in keys if k is not None]
            cond = gexpr.notin_(top) if top else None
            if None in keys or widget['options'].get('hide_none'):
                cond = and_(gexpr.isnot(None), cond) if cond is not None else gexpr.isnot(None)
            else:
                cond = or_(gexpr.is_(None), cond) if cond is not None else None
            orows = _aggregate(widget, ids, ctx, dims[1:], where_extra=cond, extra_joins=gdim[1])
            okey = ('__other__',)
            values[okey] = {}
            for r in orows:
                values[okey][r[0] if sfield else None] = _plain(r[-1])
            keys.append(okey)
            labels[okey] = dv.OTHER_LABEL
            other = True

    # series: one per split value (the largest first), else one
    if sfield:
        stotal = {s: sum((values[g].get(s) or 0) for g in values) for s in series_keys}
        series_keys.sort(key=lambda s: (-stotal[s], str(s)))
        truncated = len(series_keys) > L['series']
        series_keys = series_keys[:L['series']]
        slabels = _value_labels(source, sfield, series_keys)
    else:
        truncated = False
        slabels = {None: dv.MEASURES[widget['measure']['type']]}
        series_keys = [None]
    series = [{'label': slabels.get(s, dv.NONE_LABEL), 'values': [values.get(k, {}).get(s, fill) for k in keys]}
              for s in series_keys]
    return {'kind': 'groups', 'time': is_time, 'bucket': bucket, 'labels': [labels[k] for k in keys],
            'series': series, 'other': other, 'series_truncated': truncated}


def _cell(source, field, value, names):
    f = dv.FIELDS[source][field]
    kind = f['kind']
    if value is None:
        return None
    if kind == 'choice':
        return names.get(field, {}).get(value, '#%s' % value)
    if kind == 'bool':
        yes, no = dv.BOOL_LABELS.get(field, ('Yes', 'No'))
        return yes if value else no
    if kind == 'date':
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d %H:%M')
        return value.isoformat()
    if kind in ('tags', 'csv'):
        return [x for x in value if x]
    if kind == 'number':
        return _plain(value)
    if field == 'title' and source == 'cases':
        return cq.display_title(value)
    return str(value)[:L['value']]


def _link(source, row_id, case_id):
    target = dv.SOURCES[source][2]
    if target == 'alert':
        return '/alerts?alert_ids=%d' % int(row_id)
    if case_id is None:
        return None
    page = {'case': '/case', 'case_iocs': '/case/ioc', 'case_assets': '/case/assets', 'case_tasks': '/case/tasks',
            'case_timeline': '/case/timeline', 'case_evidence': '/case/evidences', 'case_notes': '/case/notes'}[target]
    return '%s?cid=%d' % (page, int(case_id))


def _rows_result(widget, ids, ctx):
    source = widget['source']
    spec = _spec(source)
    cols = widget['columns']
    single = [c for c in cols if not _many(source, c)]
    exprs = [_col(source, c).label('c_' + c) for c in single]
    csv_cols = [c for c in cols if _many(source, c) == 'csv']
    exprs += [spec.csv[c]().label('c_' + c) for c in csv_cols]
    case_expr = spec.case_col.label('case_id') if spec.case_col is not None else literal(None).label('case_id')
    stmt = select(spec.pk.label('pk'), case_expr, *exprs).select_from(spec.model)
    if spec.join_case:
        stmt = stmt.join(Cases, Cases.case_id == spec.case_col)
    sexpr = _col(source, widget['sort']['field'])
    sexpr = sexpr.asc().nulls_last() if widget['sort']['dir'] == 'asc' else sexpr.desc().nulls_last()
    tie = spec.pk.asc() if widget['sort']['dir'] == 'asc' else spec.pk.desc()
    stmt = stmt.where(spec.pk.in_(ids)).order_by(sexpr, tie).limit(widget['limit'])
    found = db.session.execute(stmt).all()
    total = db.session.execute(select(func.count()).select_from(ids.subquery())).scalar() or 0
    pks = [r.pk for r in found]

    many_vals = {}
    for c in cols:
        kind = _many(source, c)
        if kind == 'case_tags' and pks:
            vals = {}
            for cid, title in db.session.execute(
                    select(CaseTags.case_id, Tags.tag_title).join(Tags, Tags.id == CaseTags.tag_id)
                    .where(CaseTags.case_id.in_(pks)).order_by(Tags.tag_title)).all():
                vals.setdefault(cid, []).append(title)
            many_vals[c] = vals
        elif kind == 'assignee' and pks:
            vals = {}
            for tid, uid in db.session.execute(select(TaskAssignee.task_id, TaskAssignee.user_id)
                                               .where(TaskAssignee.task_id.in_(pks))).all():
                vals.setdefault(tid, []).append(uid)
            many_vals[c] = vals
    names = {}
    for c in cols:
        f = dv.FIELDS[source][c]
        if f['kind'] != 'choice':
            continue
        if c in many_vals:
            ids_ = {u for lst in many_vals[c].values() for u in lst}
        else:
            ids_ = {getattr(r, 'c_' + c) for r in found}
        names[c] = _labels(f['options'], ids_)

    out_rows = []
    for r in found:
        cells = []
        for c in cols:
            kind = _many(source, c)
            if kind == 'case_tags':
                cells.append([_tag_label(t) for t in many_vals.get(c, {}).get(r.pk, []) if (t or '').strip()])
            elif kind == 'assignee':
                cells.append(', '.join(names[c].get(u, '#%s' % u) for u in many_vals.get(c, {}).get(r.pk, []))
                             or None)
            elif kind == 'csv':
                raw = getattr(r, 'c_' + c) or ''
                cells.append([x.strip() for x in raw.split(',') if x.strip()])
            else:
                cells.append(_cell(source, c, getattr(r, 'c_' + c), names))
        out_rows.append({'id': r.pk, 'link': _link(source, r.pk, r.case_id), 'cells': cells})
    return {'kind': 'rows', 'columns': [{'key': c, 'label': dv.FIELDS[source][c]['label'],
                                         'kind': dv.FIELDS[source][c]['kind']} for c in cols],
            'rows': out_rows, 'total': total}


def render_widget(widget, ctx):
    ids, ignored = _ids(widget, ctx)
    if widget['measure']['type'] == 'rows':
        result = _rows_result(widget, ids, ctx)
    elif widget['group_by']:
        result = _grouped_result(widget, ids, ctx)
    else:
        result = _number_result(widget, ids, ctx)
    result.update({'ok': True, 'unit': _unit(widget), 'ignored_filters': ignored})
    return result


def _context(user, params):
    now = _now()
    return {'uid': user.id, 'admin': _is_admin(user), 'now': now, 'today': now.date(),
            'start': params.get('start'), 'end': params.get('end'), 'bar': params.get('bar') or {}}


def render(user, definition, params):
    """Every widget of a (validated) definition for one viewer. A widget that fails is {ok: false, error} - the
    others still draw. Read-only: each widget runs in a savepoint under a statement timeout."""
    ctx = _context(user, params)
    out = {}
    try:
        db.session.execute(text("SET LOCAL statement_timeout = %d" % STATEMENT_TIMEOUT_MS))
    except Exception:  # noqa: BLE001 - not PostgreSQL / no transaction: render without the timeout
        db.session.rollback()
    for section in definition.get('sections', []):
        for widget in section.get('widgets', []):
            try:
                with db.session.begin_nested():
                    out[widget['id']] = render_widget(widget, ctx)
            except Exception as exc:  # noqa: BLE001 - one widget's failure never sinks the dashboard
                app.logger.warning('Dashboard widget %s failed: %s', widget.get('id'), exc)
                out[widget['id']] = {'ok': False, 'error': 'This widget could not be computed.'}
    db.session.rollback()
    return {'range': {'key': params.get('range_key'), 'start': _iso(ctx['start']), 'end': _iso(ctx['end'])},
            'widgets': out}


def _parse_moment(value):
    if value in (None, ''):
        return None
    text_ = str(value).strip().replace('Z', '')
    try:
        moment = datetime.fromisoformat(text_)
    except ValueError:
        raise DashboardError('A date is YYYY-MM-DD or YYYY-MM-DDTHH:MM.')
    return moment.replace(tzinfo=None)


def parse_render_args(args, definition, now=None):
    """The view's query: ?range=<key> | ?start=&end= (UTC), ?f_<filter bar key>=<id | @me>."""
    now = now or _now()
    keys = [k for k, _l, _d in dv.RANGES]
    rkey = args.get('range')
    start, end = _parse_moment(args.get('start')), _parse_moment(args.get('end'))
    if start is not None or end is not None:
        rkey = 'custom'
        if start is not None and end is not None and start > end:
            start, end = end, start
        if end is not None and args.get('end') and len(str(args.get('end')).strip()) <= 10:
            end = end + timedelta(days=1) - timedelta(seconds=1)
    else:
        if rkey not in keys:
            rkey = definition.get('default_range', dv.DEFAULT_RANGE)
        days = dv.range_days(rkey)
        if days is not None:
            start, end = now - timedelta(days=days), now
    bar = {}
    allowed = {e['key'] for e in definition.get('filter_bar', [])}
    for key in allowed:
        raw = args.get('f_' + key)
        if raw in (None, ''):
            continue
        if raw == dv.ME and dv.FILTER_BAR[key][1] == 'users':
            bar[key] = dv.ME
            continue
        value = _int(raw)
        if value is None:
            raise DashboardError('%s: pick a value.' % dv.FILTER_BAR[key][0])
        bar[key] = value
    return {'range_key': rkey, 'start': start, 'end': end, 'bar': bar}


# ------------------------------------------------------------------ the option lists

def _customers(user, admin):
    if admin:
        rows = db.session.execute(select(Client.client_id, Client.name).order_by(func.lower(Client.name))).all()
    else:
        rows = db.session.execute(
            select(Client.client_id, Client.name)
            .where(or_(Client.client_id.in_(select(Cases.client_id).where(Cases.case_id.in_(cq._accessible(user.id)))),
                       Client.client_id.in_(select(UserClient.client_id).where(UserClient.user_id == user.id))))
            .order_by(func.lower(Client.name))).all()
    return [{'id': cid, 'name': name or '#%d' % cid} for cid, name in rows]


def options(user):
    """What choice fields pick from. Customers and cases: only those the viewer may see."""
    admin = _is_admin(user)
    out = {'customers': _customers(user, admin)}
    cases = db.session.execute(select(Cases.case_id, Cases.name).where(Cases.case_id.in_(cq._accessible(user.id)))
                               .order_by(Cases.case_id.desc()).limit(1000)).all()
    out['cases'] = [{'id': cid, 'name': '#%d %s' % (cid, cq.display_title(name))} for cid, name in cases]
    out['users'] = [{'id': u.id, 'name': u.name or u.user, 'active': bool(u.active)}
                    for u in User.query.order_by(func.lower(func.coalesce(User.name, User.user))).all()]
    for key, getter in _LOOKUPS.items():
        if key in ('customers', 'users'):
            continue
        id_col, name_col = getter()
        out[key] = [{'id': i, 'name': n} for i, n in db.session.execute(select(id_col, name_col).order_by(id_col)).all()]
    for key, getter in _FIXED.items():
        out[key] = [{'id': i, 'name': n} for i, n in sorted(getter().items())]
    return out


def schema(user):
    return {'vocab': dv.client_vocab(), 'options': options(user), 'me': {'id': user.id, 'name': user.name or user.user}}


# ------------------------------------------------------------------ presets and the built-in dashboards

def _by_name(options_source, name):
    id_col, name_col = _LOOKUPS[options_source]()
    row = db.session.execute(select(id_col).where(func.lower(name_col) == name.lower()).order_by(id_col)).first()
    return row[0] if row else None


def _w(name, source, chart='number', width='quarter', measure='count', field=None, **kw):
    w = {'name': name, 'source': source, 'chart': chart, 'width': width,
         'measure': {'type': measure, 'field': field, 'filter': kw.pop('share', None)}}
    w.update(kw)
    return w


def _leafs(*items, logic='and'):
    return {'logic': logic, 'items': [i for i in items if i is not None]}


def _preset_table():
    """key -> (description, widget); a widget that needs a lookup this deployment lacks is left out."""
    fp = _by_name('alert_resolutions', 'False Positive')
    critical = _by_name('severities', 'Critical')
    done, canceled = _by_name('task_statuses', 'Done'), _by_name('task_statuses', 'Canceled')
    finished_alert = [_by_name('alert_statuses', n) for n in ('Closed', 'Merged', 'Escalated')]
    open_tasks = _leafs(*[{'field': 'status', 'op': 'not_equals', 'value': s} for s in (done, canceled) if s])
    open_alerts = _leafs(*[{'field': 'status', 'op': 'not_equals', 'value': s} for s in finished_alert if s])
    table = {
        'total_alerts': ('Alerts created in the range.', _w('Total alerts', 'alerts')),
        'total_cases': ('Cases opened in the range.', _w('Total cases', 'cases')),
        'mttd': ('Average time from an alert\'s event to its creation in IRIS.',
                 _w('Mean time to detect', 'alerts', measure='avg', field='detect_minutes')),
        'mttr': ('Average days from open to close, over cases opened in the range and closed since.',
                 _w('Mean time to resolve', 'cases', measure='avg', field='resolve_days')),
        'open_cases_now': ('Every case not closed, whenever it was opened.',
                           _w('Open cases', 'cases', range='all',
                              filter=_leafs({'field': 'closed', 'op': 'is_false'}))),
        'open_alerts_now': ('Alerts not closed, merged or escalated, whenever they arrived.',
                            _w('Open alerts', 'alerts', range='all', filter=open_alerts)),
        'escalation_rate': ('The share of alerts linked to a case.',
                            _w('Escalation rate', 'alerts', measure='share',
                               share=_leafs({'field': 'escalated', 'op': 'is_true'}))),
        'alerts_by_status': ('', _w('Alerts by status', 'alerts', 'donut', 'half', group_by='status')),
        'alerts_by_severity': ('', _w('Alerts by severity', 'alerts', 'donut', 'half', group_by='severity')),
        'alerts_by_customer': ('', _w('Alerts by customer', 'alerts', 'hbar', 'half', group_by='customer')),
        'alerts_by_source': ('', _w('Alerts by source', 'alerts', 'hbar', 'half', group_by='source')),
        'alerts_over_time': ('', _w('Alerts over time', 'alerts', 'line', 'full', group_by='created')),
        'cases_by_classification': ('', _w('Cases by classification', 'cases', 'bar', 'half',
                                           group_by='classification')),
        'cases_by_state': ('', _w('Cases by state', 'cases', 'bar', 'half', group_by='state')),
        'cases_by_customer': ('', _w('Cases by customer', 'cases', 'hbar', 'half', group_by='customer')),
        'cases_over_time': ('Cases opened per period, one series per severity.',
                            _w('Cases opened over time', 'cases', 'bar', 'full', group_by='open_date',
                               split_by='severity')),
        'cases_by_sector': ('Cases per sector tag; "(none)" counts cases without one.',
                            _w('Cases by sector', 'cases', 'hbar', 'half', group_by='tags', limit=20,
                               options={'match': 'sectors'})),
        'top_case_tags': ('The most used case tags, TLP tags left out.',
                          _w('Top case tags', 'cases', 'hbar', 'half', group_by='tags', limit=15,
                             options={'exclude': 'tlp:', 'other': False, 'hide_none': True})),
        'my_open_cases': ('Open cases owned by whoever views the dashboard.',
                          _w('My open cases', 'cases', 'table', 'full', measure='rows', range='all',
                             columns=['severity', 'state', 'customer', 'open_date'],
                             sort={'field': 'open_date', 'dir': 'asc'}, limit=10,
                             filter=_leafs({'field': 'owner', 'op': 'equals', 'value': dv.ME},
                                           {'field': 'closed', 'op': 'is_false'}))),
        'evidence_by_type': ('', _w('Evidence by type', 'evidence', 'bar', 'half', group_by='type')),
        'iocs_by_type': ('', _w('IOCs by type', 'iocs', 'donut', 'half', group_by='type')),
        'iocs_by_tlp': ('', _w('IOCs by TLP', 'iocs', 'donut', 'half', group_by='tlp')),
        'assets_by_compromise': ('', _w('Assets by compromise status', 'assets', 'donut', 'half',
                                        group_by='compromise')),
        'tasks_by_status': ('', _w('Tasks by status', 'tasks', 'donut', 'half', group_by='status')),
        'open_tasks_by_assignee': ('Tasks neither done nor canceled, per assignee.',
                                   _w('Open tasks by assignee', 'tasks', 'hbar', 'half', group_by='assignee',
                                      range='all', filter=open_tasks)),
        'events_by_category': ('', _w('Timeline events by category', 'events', 'bar', 'half',
                                      group_by='category')),
        'time_by_analyst': ('Time logged per analyst in the range.',
                            _w('Time logged by analyst', 'time_entries', 'hbar', 'half', measure='sum',
                               field='minutes', group_by='user')),
    }
    if fp:
        table['false_positive_rate'] = ('The share of alerts resolved as false positives.',
                                        _w('False positive rate', 'alerts', measure='share',
                                           share=_leafs({'field': 'resolution', 'op': 'equals', 'value': fp})))
    if critical:
        table['recent_critical_alerts'] = ('The newest critical alerts.',
                                           _w('Recent critical alerts', 'alerts', 'table', 'full', measure='rows',
                                              columns=['status', 'customer', 'owner', 'created'],
                                              sort={'field': 'created', 'dir': 'desc'}, limit=10,
                                              filter=_leafs({'field': 'severity', 'op': 'equals',
                                                             'value': critical})))
    return table


PRESET_ORDER = ('total_alerts', 'total_cases', 'open_cases_now', 'open_alerts_now', 'mttd', 'mttr',
                'false_positive_rate', 'escalation_rate', 'alerts_by_status', 'alerts_by_severity',
                'alerts_by_customer', 'alerts_by_source', 'alerts_over_time', 'cases_by_classification',
                'cases_by_state', 'cases_by_customer', 'cases_over_time', 'cases_by_sector', 'top_case_tags',
                'my_open_cases', 'recent_critical_alerts', 'evidence_by_type', 'iocs_by_type', 'iocs_by_tlp',
                'assets_by_compromise', 'tasks_by_status', 'open_tasks_by_assignee', 'events_by_category',
                'time_by_analyst')


def presets():
    """[{key, name, description, widget}] - each widget validated (an invalid one is left out and logged)."""
    table = _preset_table()
    out = []
    for key in PRESET_ORDER:
        if key not in table:
            continue
        desc, raw = table[key]
        raw = dict(raw, id='p_' + key)
        issues = []
        clean = _widget(raw, key, issues, set())
        if clean is None or issues:
            app.logger.warning('Dashboard preset %s left out: %s', key, issues)
            continue
        out.append({'key': key, 'name': clean['name'], 'description': desc, 'widget': clean})
    return out


_STATISTICS = (
    ('Key indicators', 'Headline volumes and response times over the selected window.',
     ('total_alerts', 'total_cases', 'mttd', 'mttr')),
    ('Triage quality', 'How the analyst pipeline is handling incoming signal.',
     ('false_positive_rate', 'escalation_rate', 'alerts_by_status')),
    ('Distributions', 'How alerts, cases and evidence break down across the selected window.',
     ('alerts_by_severity', 'cases_by_classification', 'cases_by_state', 'evidence_by_type')),
    ('Trends', 'Volume of alerts and cases over the selected window.',
     ('alerts_over_time', 'cases_over_time')),
)


def system_definition(key):
    if key != 'statistics':
        return None
    by_key = {p['key']: p['widget'] for p in presets()}
    sections = []
    for i, (title, desc, keys) in enumerate(_STATISTICS):
        widgets = []
        for k in keys:
            if k in by_key:
                w = copy.deepcopy(by_key[k])
                w['id'] = 'st_' + k
                widgets.append(w)
        sections.append({'id': 'st%d' % i, 'title': title, 'description': desc, 'widgets': widgets})
    return {'sections': sections, 'filter_bar': [{'key': 'customer', 'label': 'Customer'}],
            'default_range': dv.DEFAULT_RANGE}


# ------------------------------------------------------------------ stored dashboards

def _parse_key(key):
    if key in dv.SYSTEM:
        return 'system', key
    try:
        return 'row', _uuid.UUID(str(key))
    except (ValueError, TypeError, AttributeError):
        return None, None


def _row(key):
    kind, value = _parse_key(key)
    if kind != 'row':
        return None
    return CustomDashboard.query.filter(CustomDashboard.dashboard_uuid == value).first()


def _user_name(user):
    return (user.name or user.user) if user is not None else None


def _summary(row, user, admin):
    widgets = sum(len(s.get('widgets', [])) for s in (row.definition or {}).get('sections', []))
    mine = row.owner_id == user.id
    return {'key': str(row.dashboard_uuid), 'name': row.name, 'description': row.description or '',
            'is_shared': bool(row.is_shared), 'system': False, 'mine': mine, 'can_edit': mine or admin,
            'owner': {'id': row.owner_id, 'name': _user_name(row.owner)},
            'updated_at': _iso(row.updated_at), 'created_at': _iso(row.created_at), 'widgets': widgets}


def _system_summary(key):
    name, desc = dv.SYSTEM[key]
    widgets = sum(len(s['widgets']) for s in system_definition(key)['sections'])
    return {'key': key, 'name': name, 'description': desc, 'is_shared': True, 'system': True, 'mine': False,
            'can_edit': False, 'owner': None, 'updated_at': None, 'created_at': None, 'widgets': widgets}


def list_dashboards(user):
    admin = _is_admin(user)
    rows = (CustomDashboard.query
            .filter(or_(CustomDashboard.owner_id == user.id, CustomDashboard.is_shared.is_(True)))
            .order_by(CustomDashboard.updated_at.desc(), CustomDashboard.id.desc()).all())
    return {'system': [_system_summary(k) for k in dv.SYSTEM],
            'dashboards': [_summary(r, user, admin) for r in rows]}


def _visible(row, user, admin):
    return row is not None and (row.owner_id == user.id or row.is_shared or admin)


def get_dashboard(user, key):
    """{..summary, definition} for a dashboard the user may see, else None (missing and hidden read the same)."""
    kind, value = _parse_key(key)
    if kind == 'system':
        out = _system_summary(value)
        out['definition'] = system_definition(value)
        return out
    row = _row(key)
    admin = _is_admin(user)
    if not _visible(row, user, admin):
        return None
    out = _summary(row, user, admin)
    definition, _issues = validate_definition(row.definition)
    out['definition'] = definition
    return out


def _check_quota(user):
    if CustomDashboard.query.filter(CustomDashboard.owner_id == user.id).count() >= L['dashboards']:
        raise DashboardError('You have %d dashboards, the most one user keeps.' % L['dashboards'])


def create(user, payload):
    clean = validate_payload(payload)
    _check_quota(user)
    now = _now()
    row = CustomDashboard(name=clean['name'], description=clean['description'], owner_id=user.id,
                          is_shared=clean['is_shared'], definition=clean['definition'], created_at=now, updated_at=now)
    db.session.add(row)
    db.session.commit()
    return get_dashboard(user, str(row.dashboard_uuid))


def _editable(user, key):
    kind, _value = _parse_key(key)
    if kind == 'system':
        raise DashboardError('A built-in dashboard cannot be changed: clone it.', status=403)
    row = _row(key)
    admin = _is_admin(user)
    if not _visible(row, user, admin):
        raise DashboardError('Dashboard not found.', status=404)
    if row.owner_id != user.id and not admin:
        raise DashboardError('Only its owner (or an administrator) changes a dashboard. Clone it to customise.',
                             status=403)
    return row


def update(user, key, payload):
    row = _editable(user, key)
    clean = validate_payload(payload, partial=True)
    for field in ('name', 'description', 'is_shared', 'definition'):
        if field in clean:
            setattr(row, field, clean[field])
    row.updated_at = _now()
    db.session.commit()
    return get_dashboard(user, key)


def delete(user, key):
    row = _editable(user, key)
    db.session.delete(row)
    db.session.commit()


def clone(user, key):
    source = get_dashboard(user, key)
    if source is None:
        raise DashboardError('Dashboard not found.', status=404)
    name = source['name'] + ' (copy)'
    if len(name) > L['name']:
        name = source['name'][:L['name'] - 7] + ' (copy)'
    return create(user, {'name': name, 'description': source['description'], 'is_shared': False,
                         'definition': source['definition']})


# ------------------------------------------------------------------ what the pages embed

def list_state(user):
    return list_dashboards(user)


def view_state(user, key, args):
    """The view page's first frame: the dashboard and its first render; None when the user may not see it.
    A bad query string keeps the dashboard and reports the error."""
    dash = get_dashboard(user, key)
    if dash is None:
        return None
    state = {'dashboard': dash, 'schema': {'vocab': dv.client_vocab(), 'options': _bar_options(user, dash)},
             'error': None, 'data': None, 'params': None, 'me': {'id': user.id, 'name': user.name or user.user}}
    try:
        params = parse_render_args(args, dash['definition'])
    except DashboardError as exc:
        state['error'] = exc.message
        params = parse_render_args({}, dash['definition'])
    state['params'] = {'range': params['range_key'], 'start': _iso(params['start']), 'end': _iso(params['end']),
                       'bar': params['bar']}
    state['data'] = render(user, dash['definition'], params)
    return state


def _bar_options(user, dash):
    """Only the option lists the dashboard's filter bar needs."""
    wanted = {dv.FILTER_BAR[e['key']][1] for e in dash['definition'].get('filter_bar', [])}
    if not wanted:
        return {}
    every = options(user)
    return {k: v for k, v in every.items() if k in wanted}


def edit_state(user, key):
    """The editor's first frame. key None = a new dashboard. None when the user may not edit it."""
    if key is None:
        dash = {'key': None, 'name': 'Untitled dashboard', 'description': '', 'is_shared': False, 'system': False,
                'can_edit': True, 'definition': {'sections': [{'id': 's1', 'title': 'Overview', 'description': '',
                                                               'widgets': []}],
                                                 'filter_bar': [], 'default_range': dv.DEFAULT_RANGE}}
    else:
        dash = get_dashboard(user, key)
        if dash is None or not dash['can_edit']:
            return None
    return {'dashboard': dash, 'schema': schema(user), 'presets': presets()}

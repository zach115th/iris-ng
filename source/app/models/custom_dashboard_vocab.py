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

"""Custom dashboards' vocabulary (iris-ng, 2026-11-09): the field catalogue widgets are built from.

Import-free on purpose: the business module compiles widgets against it, the REST layer and the pages hand it to
the browser as it is, and the suite derives its checks from it.

A dashboard definition:

    {"sections": [{"id", "title", "description", "widgets": [<widget>, ...]}, ...],
     "filter_bar": [{"key": "customer" | "case" | "severity" | "owner", "label"}],
     "default_range": "30d"}

A widget picks a SOURCE (what rows it counts), a MEASURE (count, count distinct, sum / average / median / min / max
of a number, the share of rows matching a filter, or a list of rows), optionally a field to GROUP BY (a date field
groups by a time bucket) and a field to SPLIT BY (one series per value), a filter (the case queue's tree:
{"logic": "and" | "or", "items": [...]}) and a chart. Every widget counts only what the viewer may open: cases they
have any access to but deny_all (and what those cases hold), alerts of the customers they belong to (every alert for
a server administrator).

Choice fields compare IDS; a user field also takes ME ("@me" - whoever views the dashboard).
"""

# ------------------------------------------------------------------ fields

ME = '@me'

KINDS = ('text', 'number', 'choice', 'date', 'bool', 'tags', 'csv')

OPERATORS = {
    'contains': 'Contains',
    'not_contains': "Doesn't contain",
    'equals': 'Equals',
    'not_equals': "Doesn't equal",
    'starts_with': 'Starts with',
    'not_starts_with': "Doesn't start with",
    'ends_with': 'Ends with',
    'not_ends_with': "Doesn't end with",
    'empty': 'Is empty',
    'not_empty': 'Is not empty',
    'greater': 'Greater than',
    'less': 'Less than',
    'on': 'On',
    'before': 'Before',
    'after': 'After',
    'older_than': 'More than N days ago',
    'within': 'In the last N days',
    'has': 'Has the tag',
    'has_not': "Doesn't have the tag",
    'is_true': 'Is yes',
    'is_false': 'Is no',
}
NO_VALUE_OPS = ('empty', 'not_empty', 'is_true', 'is_false')
DAY_OPS = ('older_than', 'within')
TEXT_OPS = ('contains', 'not_contains', 'equals', 'not_equals', 'starts_with', 'not_starts_with', 'ends_with',
            'not_ends_with', 'empty', 'not_empty')
TAG_OPS = ('has', 'has_not', 'contains', 'not_contains', 'empty', 'not_empty')
OPS_BY_KIND = {
    'text': TEXT_OPS,
    'number': ('equals', 'not_equals', 'greater', 'less', 'empty', 'not_empty'),
    'choice': ('equals', 'not_equals', 'empty', 'not_empty'),
    'date': ('on', 'before', 'after', 'older_than', 'within', 'empty', 'not_empty'),
    'bool': ('is_true', 'is_false'),
    'tags': TAG_OPS,
    'csv': TAG_OPS,
}
# The filter builder in the browser draws these kinds' value inputs as one of its own types.
BUILDER_TYPE = {'text': 'text', 'number': 'number', 'choice': 'choice', 'date': 'date', 'bool': 'text',
                'tags': 'tags', 'csv': 'tags'}

# Number units: how a figure is written (minutes and days read as durations).
UNITS = ('count', 'days', 'minutes', 'bytes', 'percent')


def _f(label, kind, options=None, nullable=True, unit=None, group=None):
    """One field. `group` marks a text field one can group by (its distinct values); choice, bool, date and tag
    fields always can, a number never."""
    return {'label': label, 'kind': kind, 'options': options, 'nullable': nullable, 'unit': unit,
            'group': bool(group) if kind == 'text' else kind in ('choice', 'bool', 'date', 'tags', 'csv')}


_CUSTOMER = _f('Customer', 'choice', 'customers', nullable=False)
_CASE = _f('Case', 'choice', 'cases', nullable=False)

# source -> its fields, in the order the editor lists them.
FIELDS = {
    'cases': {
        'title': _f('Title', 'text'),
        'soc_id': _f('SOC ID', 'text'),
        'case': _CASE,
        'customer': _CUSTOMER,
        'severity': _f('Severity', 'choice', 'severities'),
        'state': _f('State', 'choice', 'states'),
        'classification': _f('Classification', 'choice', 'classifications'),
        'outcome': _f('Outcome', 'choice', 'outcomes', nullable=False),
        'owner': _f('Owner', 'choice', 'users'),
        'opened_by': _f('Opened by', 'choice', 'users'),
        'reviewer': _f('Reviewer', 'choice', 'users'),
        'review_status': _f('Review status', 'choice', 'review_statuses'),
        'tags': _f('Tags', 'tags'),
        'closed': _f('Closed', 'bool', nullable=False),
        'open_date': _f('Open date', 'date'),
        'close_date': _f('Close date', 'date'),
        'age_days': _f('Days open', 'number', unit='days'),
        'resolve_days': _f('Days to close', 'number', unit='days'),
    },
    'alerts': {
        'title': _f('Title', 'text'),
        'source': _f('Source', 'text', group=True),
        'customer': _CUSTOMER,
        'severity': _f('Severity', 'choice', 'severities', nullable=False),
        'status': _f('Status', 'choice', 'alert_statuses', nullable=False),
        'resolution': _f('Resolution', 'choice', 'alert_resolutions'),
        'classification': _f('Classification', 'choice', 'classifications'),
        'owner': _f('Owner', 'choice', 'users'),
        'tags': _f('Tags', 'csv'),
        'escalated': _f('Linked to a case', 'bool', nullable=False),
        'created': _f('Created', 'date', nullable=False),
        'event_time': _f('Event time', 'date', nullable=False),
        'detect_minutes': _f('Minutes to detect', 'number', unit='minutes'),
    },
    'iocs': {
        'value': _f('Value', 'text'),
        'type': _f('Type', 'choice', 'ioc_types'),
        'tlp': _f('TLP', 'choice', 'tlps'),
        'tags': _f('Tags', 'csv'),
        'case': _CASE,
        'customer': _CUSTOMER,
        'case_open_date': _f('Case open date', 'date'),
    },
    'assets': {
        'name': _f('Name', 'text'),
        'ip': _f('IP', 'text'),
        'type': _f('Type', 'choice', 'asset_types'),
        'compromise': _f('Compromise status', 'choice', 'compromise_statuses'),
        'analysis': _f('Analysis status', 'choice', 'analysis_statuses'),
        'tags': _f('Tags', 'csv'),
        'case': _CASE,
        'customer': _CUSTOMER,
        'added': _f('Added', 'date'),
    },
    'tasks': {
        'title': _f('Title', 'text'),
        'status': _f('Status', 'choice', 'task_statuses'),
        'assignee': _f('Assignee', 'choice', 'users'),
        'opened_by': _f('Opened by', 'choice', 'users'),
        'tags': _f('Tags', 'csv'),
        'case': _CASE,
        'customer': _CUSTOMER,
        'opened': _f('Opened', 'date'),
    },
    'events': {
        'title': _f('Title', 'text'),
        'category': _f('Category', 'choice', 'event_categories'),
        'verdict': _f('Verdict', 'choice', 'verdicts'),
        'flagged': _f('Flagged', 'bool', nullable=False),
        'in_summary': _f('In the summary', 'bool', nullable=False),
        'source': _f('Source', 'text', group=True),
        'tags': _f('Tags', 'csv'),
        'added_by': _f('Added by', 'choice', 'users'),
        'case': _CASE,
        'customer': _CUSTOMER,
        'event_date': _f('Event date', 'date'),
        'added': _f('Added', 'date'),
    },
    'evidence': {
        'filename': _f('File name', 'text'),
        'type': _f('Type', 'choice', 'evidence_types'),
        'added_by': _f('Added by', 'choice', 'users'),
        'size': _f('Size', 'number', unit='bytes'),
        'case': _CASE,
        'customer': _CUSTOMER,
        'added': _f('Added', 'date'),
        'acquired': _f('Acquired', 'date'),
    },
    'notes': {
        'title': _f('Title', 'text'),
        'author': _f('Author', 'choice', 'users'),
        'tags': _f('Tags', 'csv'),
        'case': _CASE,
        'customer': _CUSTOMER,
        'created': _f('Created', 'date'),
        'updated': _f('Last updated', 'date'),
    },
    'time_entries': {
        'user': _f('Analyst', 'choice', 'users'),
        'minutes': _f('Minutes', 'number', nullable=False, unit='minutes'),
        'case': _CASE,
        'customer': _CUSTOMER,
        'date': _f('Date', 'date', nullable=False),
    },
}

# source -> (label, the date field the dashboard's range applies to, what a listed row links to)
SOURCES = {
    'cases': ('Cases', 'open_date', 'case'),
    'alerts': ('Alerts', 'created', 'alert'),
    'iocs': ('IOCs', 'case_open_date', 'case_iocs'),
    'assets': ('Assets', 'added', 'case_assets'),
    'tasks': ('Tasks', 'opened', 'case_tasks'),
    'events': ('Timeline events', 'added', 'case_timeline'),
    'evidence': ('Evidence', 'added', 'case_evidence'),
    'notes': ('Notes', 'created', 'case_notes'),
    'time_entries': ('Time entries', 'date', 'case'),
}

# Fields a row holds several values of (besides the tag fields): grouping counts the row once per value, and a
# list cannot sort by them.
MANY_FIELDS = (('tasks', 'assignee'),)


def is_many(source, key):
    return FIELDS[source][key]['kind'] in ('tags', 'csv') or (source, key) in MANY_FIELDS


# What a listed row shows first (always a column) and links to.
ROW_TITLE = {'cases': 'title', 'alerts': 'title', 'iocs': 'value', 'assets': 'name', 'tasks': 'title',
             'events': 'title', 'evidence': 'filename', 'notes': 'title', 'time_entries': 'user'}

# The fixed vocabularies of choice fields that are not lookup tables. Event verdicts are stored as text; the
# dashboards number them so every choice compares ids.
OUTCOMES = (
    (0, 'Unknown'),
    (1, 'False positive'),
    (2, 'True positive with impact'),
    (3, 'Not applicable'),
    (4, 'True positive without impact'),
    (5, 'Legitimate'),
)
COMPROMISE_STATUSES = (
    (0, 'To be determined'),
    (1, 'Compromised'),
    (2, 'Not compromised'),
    (3, 'Unknown'),
)
VERDICTS = (
    (0, 'to_be_determined', 'To be determined'),
    (1, 'true_positive', 'True positive'),
    (2, 'false_positive', 'False positive'),
)
# What a yes / no field's two values read as in a chart: field -> (yes, no).
BOOL_LABELS = {
    'closed': ('Closed', 'Open'),
    'escalated': ('Linked to a case', 'Not linked'),
    'flagged': ('Flagged', 'Not flagged'),
    'in_summary': ('In the summary', 'Left out'),
}
NONE_LABEL = '(none)'
OTHER_LABEL = 'Other'

# ------------------------------------------------------------------ measures, charts, layout

MEASURES = {
    'count': 'Count',
    'distinct': 'Count distinct',
    'sum': 'Sum',
    'avg': 'Average',
    'median': 'Median',
    'min': 'Minimum',
    'max': 'Maximum',
    'share': 'Share matching a filter',
    'rows': 'List rows',
}
NUMBER_MEASURES = ('sum', 'avg', 'median', 'min', 'max')

CHARTS = {
    'number': 'Number',
    'donut': 'Donut',
    'pie': 'Pie',
    'bar': 'Bar',
    'hbar': 'Horizontal bar',
    'line': 'Line',
    'table': 'Table',
}
GROUPED_CHARTS = ('donut', 'pie', 'bar', 'hbar', 'line', 'table')
SPLIT_CHARTS = ('bar', 'hbar', 'line')

WIDTHS = {'full': 12, 'half': 6, 'third': 4, 'quarter': 3}

TIME_BUCKETS = ('auto', 'hour', 'day', 'week', 'month', 'quarter', 'year')
# "auto": the finest bucket whose point count stays within MAX_POINTS, starting from these spans (days).
AUTO_BUCKETS = ((2, 'hour'), (62, 'day'), (550, 'week'), (3660, 'month'))
MAX_POINTS = 400

SORTS = ('value_desc', 'value_asc', 'label_asc', 'label_desc')

# The range a dashboard opens with, and the view page's preset chips. None = all time.
RANGES = (
    ('24h', 'Last 24 hours', 1),
    ('7d', 'Last 7 days', 7),
    ('30d', 'Last 30 days', 30),
    ('90d', 'Last 90 days', 90),
    ('6m', 'Last 6 months', 182),
    ('1y', 'Last year', 365),
    ('2y', 'Last 2 years', 730),
    ('5y', 'Last 5 years', 1826),
    ('all', 'All time', None),
)
DEFAULT_RANGE = '30d'
# A widget either follows the dashboard's range or ignores it.
WIDGET_RANGES = ('dashboard', 'all')

# Dashboard-level filters: key -> (label, option list, the field each source applies it to; absent = not applied).
FILTER_BAR = {
    'customer': ('Customer', 'customers', {s: 'customer' for s in FIELDS}),
    'case': ('Case', 'cases', {s: 'case' for s in FIELDS if 'case' in FIELDS[s]}),
    'severity': ('Severity', 'severities', {'cases': 'severity', 'alerts': 'severity'}),
    'owner': ('Owner', 'users', {'cases': 'owner', 'alerts': 'owner'}),
}

# Colours a widget or a threshold may take (#rrggbb); series take the palette in order.
PALETTE = ('#5464d8', '#2bb0a0', '#f6c344', '#f5365c', '#8b5cf6', '#48abf7', '#fb6340', '#31ce36', '#e83e8c',
           '#a0a0b0')
THRESHOLD_OPS = ('gte', 'lte')

LIMITS = {
    'sections': 20,
    'widgets': 60,
    'filter_bar': 4,
    'name': 120,
    'description': 500,
    'section_title': 120,
    'widget_name': 120,
    'columns': 8,
    'rows': 100,
    'groups': 50,
    'default_groups': 10,
    'series': 8,
    'thresholds': 5,
    'depth': 3,
    'conditions': 40,
    'value': 200,
    'days': 36500,
    'dashboards': 200,
    'definition_bytes': 200000,
    'match_text': 80,
}

# The built-in dashboards: never stored, never editable, cloneable. key -> (name, description)
SYSTEM = {
    'statistics': ('Statistics', 'Built-in statistics dashboard. Clone it to customise.'),
}


def field_ops(source, key):
    """The operators a field offers: its kind's, without the empty tests on a field that is never empty."""
    f = FIELDS[source][key]
    ops = OPS_BY_KIND[f['kind']]
    if not f['nullable']:
        ops = tuple(o for o in ops if o not in ('empty', 'not_empty'))
    return ops


def groupable(source):
    return [k for k, f in FIELDS[source].items() if f['group']]


def numeric(source):
    return [k for k, f in FIELDS[source].items() if f['kind'] == 'number']


def distinctable(source):
    return [k for k, f in FIELDS[source].items() if f['kind'] in ('choice', 'text', 'bool')]


def range_days(key):
    for k, _label, days in RANGES:
        if k == key:
            return days
    raise KeyError(key)


def client_vocab():
    """What the pages' editors and filter builders need, as plain data."""
    return {
        'me': ME,
        'operators': dict(OPERATORS),
        'no_value_ops': list(NO_VALUE_OPS),
        'day_ops': list(DAY_OPS),
        'sources': [{'key': s, 'label': v[0], 'date_field': v[1], 'title_field': ROW_TITLE[s],
                     'fields': [{'key': k, 'label': f['label'], 'kind': f['kind'],
                                 'type': BUILDER_TYPE[f['kind']], 'options': f['options'], 'unit': f['unit'],
                                 'group': f['group'], 'many': is_many(s, k), 'ops': list(field_ops(s, k))}
                                for k, f in FIELDS[s].items()]}
                    for s, v in SOURCES.items()],
        'measures': [{'key': k, 'label': v} for k, v in MEASURES.items()],
        'number_measures': list(NUMBER_MEASURES),
        'charts': [{'key': k, 'label': v} for k, v in CHARTS.items()],
        'grouped_charts': list(GROUPED_CHARTS),
        'split_charts': list(SPLIT_CHARTS),
        'widths': [{'key': k, 'cols': v} for k, v in WIDTHS.items()],
        'time_buckets': list(TIME_BUCKETS),
        'sorts': list(SORTS),
        'ranges': [{'key': k, 'label': label, 'days': days} for k, label, days in RANGES],
        'default_range': DEFAULT_RANGE,
        'widget_ranges': list(WIDGET_RANGES),
        'filter_bar': [{'key': k, 'label': v[0], 'options': v[1], 'sources': sorted(v[2])}
                       for k, v in FILTER_BAR.items()],
        'palette': list(PALETTE),
        'threshold_ops': list(THRESHOLD_OPS),
        'limits': dict(LIMITS),
        'system': [{'key': k, 'name': v[0], 'description': v[1]} for k, v in SYSTEM.items()],
    }

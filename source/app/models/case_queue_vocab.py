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

"""The case queue's vocabulary (iris-ng, 2026-11-08): the Overview page's fields, operators, sorts and limits.

Import-free on purpose: the business module validates filters against it, the REST layer and the page hand it to
the browser as it is, and the suite derives its checks from it. A filter is a tree of groups and conditions:

    {"logic": "and" | "or", "items": [ {"field": <key>, "op": <operator>, "value": <value>} | <group>, ... ]}

Choice fields compare IDS (a renamed customer or user still matches); dates are ISO days; "older_than" / "within"
take a number of days.
"""

# The stage track, in order. Matched to case_state rows BY NAME: lookup-table ids vary per deployment. A case in
# any other state ("Unspecified", "In progress") sits on no step.
STAGES = ('Open', 'Containment', 'Eradication', 'Recovery', 'Post-Incident', 'Reporting', 'Closed')
CLOSED_STAGE = 'Closed'

# "Opened > 7d" counts open cases opened more than this many days ago; a case idle longer reads "Stalled".
STALL_DAYS = 7

PAGE_SIZES = (10, 25, 50, 100)
DEFAULT_PAGE_SIZE = 25
SEARCH_MAX = 200
TAGS_IN_ROW = 3

# sort key -> (label, the direction a first click picks). Age runs from the youngest case; Idle from the most idle.
SORTS = {
    'case': ('Case', 'asc'),
    'stage': ('Stage', 'asc'),
    'owner': ('Owner', 'asc'),
    'age': ('Age', 'asc'),
    'idle': ('Idle', 'desc'),
}
DEFAULT_SORT = ('age', 'asc')
DIRECTIONS = ('asc', 'desc')

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
}
NO_VALUE_OPS = ('empty', 'not_empty')
DAY_OPS = ('older_than', 'within')

TEXT_OPS = ('contains', 'not_contains', 'equals', 'not_equals', 'starts_with', 'not_starts_with', 'ends_with',
            'not_ends_with', 'empty', 'not_empty')
OPS_BY_TYPE = {
    'text': TEXT_OPS,
    'number': ('equals', 'not_equals', 'greater', 'less'),
    'choice': ('equals', 'not_equals', 'empty', 'not_empty'),
    'date': ('on', 'before', 'after', 'older_than', 'within', 'empty', 'not_empty'),
    'tags': ('has', 'has_not', 'contains', 'not_contains', 'empty', 'not_empty'),
}

# key -> (label, type, the option list a choice field picks from, nullable). A field that can never be empty offers
# no "Is empty" / "Is not empty".
FIELDS = {
    'title': ('Title', 'text', None, True),
    'case_id': ('Case ID', 'number', None, False),
    'soc_id': ('SOC ID', 'text', None, True),
    'description': ('Description', 'text', None, True),
    'customer': ('Customer', 'choice', 'customers', False),
    'severity': ('Severity', 'choice', 'severities', True),
    'state': ('Stage', 'choice', 'states', True),
    'classification': ('Classification', 'choice', 'classifications', True),
    'outcome': ('Outcome', 'choice', 'outcomes', False),
    'owner': ('Owner', 'choice', 'users', True),
    'opened_by': ('Opened by', 'choice', 'users', True),
    'reviewer': ('Reviewer', 'choice', 'users', True),
    'review_status': ('Review status', 'choice', 'review_statuses', True),
    'tags': ('Tags', 'tags', None, True),
    'open_date': ('Open date', 'date', None, True),
    'close_date': ('Close date', 'date', None, True),
    'closing_note': ('Closing note', 'text', None, True),
}

# A case's outcome (cases.status_id) - the values of models.CaseStatus, labelled.
OUTCOMES = (
    (0, 'Unknown'),
    (1, 'False positive'),
    (2, 'True positive with impact'),
    (3, 'Not applicable'),
    (4, 'True positive without impact'),
    (5, 'Legitimate'),
)

MAX_DEPTH = 3          # the root group plus two levels of sub-groups
MAX_CONDITIONS = 40
MAX_VALUE_LEN = 200
MAX_DAYS = 36500

# The quick-filter chips above the queue, counted over the open cases the viewer can open.
KPIS = (
    ('open', 'Open'),
    ('critical', 'Critical'),
    ('stalled', 'Opened > %dd' % STALL_DAYS),
    ('mine', 'Assigned to me'),
)

# saved_filters.filter_type of the queue's saved filters (private or shared, the table's own rule).
SAVED_FILTER_TYPE = 'cases'


def field_ops(key):
    """The operators a field offers: its type's, without the empty tests on a field that is never empty."""
    label, ftype, _source, nullable = FIELDS[key]
    ops = OPS_BY_TYPE[ftype]
    if not nullable:
        ops = tuple(o for o in ops if o not in NO_VALUE_OPS)
    return ops


def stage_index(state_name):
    """The step of the track a state sits on, or None."""
    name = (state_name or '').strip().lower()
    for i, stage in enumerate(STAGES):
        if stage.lower() == name:
            return i
    return None


def client_vocab():
    """What the page's builder needs, as plain data."""
    return {
        'stages': list(STAGES),
        'closed_stage': CLOSED_STAGE,
        'stall_days': STALL_DAYS,
        'page_sizes': list(PAGE_SIZES),
        'default_page_size': DEFAULT_PAGE_SIZE,
        'sorts': {k: {'label': v[0], 'first': v[1]} for k, v in SORTS.items()},
        'default_sort': {'key': DEFAULT_SORT[0], 'dir': DEFAULT_SORT[1]},
        'operators': dict(OPERATORS),
        'no_value_ops': list(NO_VALUE_OPS),
        'day_ops': list(DAY_OPS),
        'fields': [{'key': k, 'label': v[0], 'type': v[1], 'options': v[2], 'ops': list(field_ops(k))}
                   for k, v in FIELDS.items()],
        'limits': {'depth': MAX_DEPTH, 'conditions': MAX_CONDITIONS, 'value': MAX_VALUE_LEN, 'days': MAX_DAYS,
                   'search': SEARCH_MAX},
        'kpis': [{'key': k, 'label': v} for k, v in KPIS],
        'tags_in_row': TAGS_IN_ROW,
        'saved_filter_type': SAVED_FILTER_TYPE,
    }

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

"""The alert queue's vocabulary (iris-ng, 2026-11-09): the Alerts page's search fields, tabs, views and limits.

Import-free on purpose: business.alert_query parses and compiles against it, the REST layer and the page hand it to the
browser as it is, and the suite derives its checks from it.

The search language, in short:

    is:open owner:none severity:>=High title:"credential dumping"
    (tag:phishing OR tag:malware) NOT status:Pending  -source:EDR
    created:[2026-10-01 TO 2026-10-31]  event_time:>=2026-11-01

Terms side by side are ANDed; OR joins everything written before it with everything after it. A word without a field
searches the title, description, source, source reference and tags.
"""

# Looked up BY NAME: lookup-table ids vary per deployment. A finished alert is out of every open queue.
FINISHED_STATUSES = ('Closed', 'Merged', 'Escalated')
ESCALATED_STATUS = 'Escalated'

# Lowest first. A severity the deployment added sits below all of these.
SEVERITY_ORDER = ('Unspecified', 'Informational', 'Low', 'Medium', 'High', 'Critical')
# The board's columns and the status sort, by name; anything else after them.
STATUS_ORDER = ('New', 'Assigned', 'In progress', 'Pending', 'Unspecified')

VIEWS = ('split', 'list', 'board')
DEFAULT_VIEW = 'split'
BOARD_GROUPS = {
    'severity': ('Unassigned by severity', 'Alerts nobody owns yet, one column per severity'),
    'status': ('Assigned by status', 'Alerts that have an owner, one column per status'),
}
DEFAULT_BOARD_GROUP = 'severity'
BOARD_COLUMN_LIMIT = 50

# tab -> the query it stands for. A tab rewrites these clauses and leaves the rest of the search alone.
TABS = (
    ('mine', 'My queue', 'is:open owner:me'),
    ('unassigned', 'Unassigned', 'is:open owner:none'),
    ('escalated', 'Escalated', 'status:Escalated'),
    ('open', 'All open', 'is:open'),
)
DEFAULT_QUERY = 'is:open'

# sort key -> (label, the direction a first click picks)
SORTS = {
    'severity': ('Severity', 'desc'),
    'title': ('Alert', 'asc'),
    'customer_name': ('Customer', 'asc'),
    'status': ('Status', 'asc'),
    'event_time': ('Event time', 'desc'),
}
DEFAULT_SORT = ('event_time', 'desc')
DIRECTIONS = ('asc', 'desc')

PAGE_SIZES = (10, 25, 50, 100)
DEFAULT_PAGE_SIZE = 25
# How many of a cluster's matching alerts the queue shows before "more".
CLUSTER_PREVIEW = 5
CLUSTER_PAGE = 25
CLUSTER_MEMBERS_IN_DETAIL = 25

MAX_QUERY = 2000
MAX_TERMS = 100
MAX_DEPTH = 12
MAX_VALUE_LEN = 200

# alias -> (kind, option list, synonyms, what it looks at). Kinds: text (contains; * and ? anchor and wildcard),
# tag (an exact tag; wildcards allowed), asset / ioc (any attached one's name / value contains), choice (by name; "none"
# on a field that can be empty), date, id / case / cluster (numbers; cluster:none), is (open / closed).
QUERY_FIELDS = {
    'title': ('text', None, (), 'Title'),
    'description': ('text', None, ('desc',), 'Description'),
    'source': ('text', None, (), 'Source'),
    'ref': ('text', None, ('source_ref',), 'Source reference'),
    'note': ('text', None, (), 'Alert note'),
    'tag': ('tag', None, ('tags',), 'A tag'),
    'asset': ('asset', None, (), 'An attached asset'),
    'ioc': ('ioc', None, (), 'An attached IOC'),
    'status': ('choice', 'statuses', (), 'Status'),
    'severity': ('choice', 'severities', (), 'Severity (also >=, <=, >, <)'),
    'classification': ('choice', 'classifications', (), 'Classification'),
    'resolution': ('choice', 'resolutions', (), 'Resolution'),
    'customer': ('choice', 'customers', ('client',), 'Customer'),
    'owner': ('choice', 'users', ('assignee',), 'Owner: me, none or a name'),
    'event_time': ('date', None, ('seen',), 'Event time'),
    'created': ('date', None, (), 'Created'),
    'id': ('id', None, (), 'Alert ID'),
    'case': ('case', None, (), 'A linked case ID'),
    'cluster': ('cluster', None, (), 'Cluster ID, or none'),
    'is': ('is', None, (), 'open or closed'),
}
IS_VALUES = ('open', 'closed')
# Choice fields that can be empty take the value "none".
NULLABLE_CHOICES = ('owner', 'resolution', 'classification')
ME = 'me'
NONE = 'none'

# The Filter panel: the old form's field names, so saved filters and links keep working.
FILTER_TEXT = ('alert_title', 'alert_description', 'alert_source', 'alert_tags', 'source_reference')
FILTER_INT = ('alert_status_id', 'alert_severity_id', 'alert_owner_id', 'alert_classification_id',
              'alert_resolution_id', 'case_id', 'alert_customer_id', 'cluster_id')
FILTER_DATES = ('creation_start_date', 'creation_end_date', 'source_start_date', 'source_end_date')
FILTER_LISTS = ('alert_ids', 'alert_assets', 'alert_iocs')
FILTER_PARAMS = FILTER_TEXT + FILTER_INT + FILTER_DATES + FILTER_LISTS + ('custom_conditions',)
SAVED_FILTER_TYPE = 'alerts'


def canonical_field(name):
    """A field name or synonym, in any case -> its alias, else None."""
    low = (name or '').lower()
    for alias, spec in QUERY_FIELDS.items():
        if low == alias or low in spec[2]:
            return alias
    return None


def client_vocab():
    return {
        'finished_statuses': list(FINISHED_STATUSES),
        'severity_order': list(SEVERITY_ORDER),
        'views': list(VIEWS),
        'default_view': DEFAULT_VIEW,
        'board_groups': [{'key': k, 'label': v[0], 'description': v[1]} for k, v in BOARD_GROUPS.items()],
        'default_board_group': DEFAULT_BOARD_GROUP,
        'tabs': [{'key': k, 'label': label, 'query': q} for k, label, q in TABS],
        'default_query': DEFAULT_QUERY,
        'sorts': {k: {'label': v[0], 'first': v[1]} for k, v in SORTS.items()},
        'default_sort': {'key': DEFAULT_SORT[0], 'dir': DEFAULT_SORT[1]},
        'page_sizes': list(PAGE_SIZES),
        'default_page_size': DEFAULT_PAGE_SIZE,
        'cluster_preview': CLUSTER_PREVIEW,
        'query_fields': [{'key': k, 'kind': v[0], 'options': v[1], 'synonyms': list(v[2]), 'label': v[3]}
                         for k, v in QUERY_FIELDS.items()],
        'is_values': list(IS_VALUES),
        'nullable_choices': list(NULLABLE_CHOICES),
        'max_query': MAX_QUERY,
        'filter_params': list(FILTER_PARAMS),
        'saved_filter_type': SAVED_FILTER_TYPE,
    }

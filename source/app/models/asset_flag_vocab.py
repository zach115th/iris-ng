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

"""The one vocabulary of asset flags, war-room decisions and the war-room Board
(iris-ng 2026-11-07).

The ORM CHECK constraints, the migration, the business validation and the
GET .../vocab answers all read these tuples - add a value here and nowhere
else. Import-free on purpose (the migration imports it).
"""

# ------------------------------------------------------------------ asset flags

# Colour names (the UI maps each to a hex value in asset_flags.js).
COLORS = ('slate', 'gray', 'red', 'orange', 'amber', 'yellow', 'lime', 'green', 'emerald', 'teal', 'cyan',
          'sky', 'blue', 'indigo', 'violet', 'purple', 'fuchsia', 'pink', 'rose')

# Lucide icon names (ISC); the SVGs are drawn by asset_flags.js.
ICONS = ('unplug', 'key-round', 'wrench', 'hard-drive', 'eye', 'circle-check', 'shield-off', 'octagon-x',
         'shield', 'shield-check', 'triangle-alert', 'scan-search', 'microscope', 'rotate-ccw', 'circle-dot',
         'bug', 'ban', 'flag', 'hourglass')

KINDS = ('status', 'done', 'exception')
KIND_LABELS = {'status': 'Status', 'done': 'Done', 'exception': 'Exception'}
KIND_DESCRIPTIONS = {
    'status': 'A fact about the asset (isolated, credentials reset...).',
    'done': 'Nothing left to do on the asset. Counted as done on the war-room Board.',
    'exception': 'An accepted gap. Highlighted on the war-room Board.',
}

NAME_MAX = 64
REASON_MAX = 4000
FLAG_ACTIONS = ('set', 'updated', 'cleared')

# Starter sets an administrator can load in Settings -> Asset flags. Loading
# adds the flags whose name is not taken yet (any letter case); it never
# changes or removes a flag.
PRESETS = (
    {'id': 'incident', 'label': 'Incident response (default)', 'flags': (
        {'name': 'Isolated', 'icon': 'unplug', 'color': 'orange', 'kind': 'status',
         'description': 'Asset is contained (network isolation, account disabled, ...)'},
        {'name': 'Credentials reset', 'icon': 'key-round', 'color': 'sky', 'kind': 'status',
         'description': "The asset's passwords, keys and tokens were rotated"},
        {'name': 'Patched', 'icon': 'wrench', 'color': 'indigo', 'kind': 'status',
         'description': 'Root cause is fixed (patch or configuration change)'},
        {'name': 'Reimaged', 'icon': 'hard-drive', 'color': 'violet', 'kind': 'status',
         'description': 'Rebuilt from a known-good image'},
        {'name': 'Monitored', 'icon': 'eye', 'color': 'cyan', 'kind': 'status',
         'description': 'Under enhanced monitoring'},
        {'name': 'Restored', 'icon': 'circle-check', 'color': 'green', 'kind': 'done',
         'description': 'Asset is back in normal operation'},
        {'name': "Can't be patched", 'icon': 'shield-off', 'color': 'amber', 'kind': 'exception',
         'requires_reason': True, 'description': 'Accepted exception: the asset cannot be fixed for now'},
        {'name': 'Blocked', 'icon': 'octagon-x', 'color': 'red', 'kind': 'exception',
         'requires_reason': True, 'description': 'Work on the asset is blocked'},
    )},
    {'id': 'vulnerability', 'label': 'Vulnerability', 'flags': (
        {'name': 'Mitigated', 'icon': 'shield', 'color': 'amber', 'kind': 'status',
         'description': 'A workaround reduces the risk; the fix is still due'},
        {'name': 'Patched', 'icon': 'wrench', 'color': 'indigo', 'kind': 'done',
         'description': 'The fix is applied'},
        {'name': 'Not affected', 'icon': 'circle-check', 'color': 'green', 'kind': 'done',
         'description': 'The asset is not vulnerable'},
        {'name': "Can't be patched", 'icon': 'shield-off', 'color': 'amber', 'kind': 'exception',
         'requires_reason': True, 'description': 'Accepted exception: the asset cannot be fixed for now'},
        {'name': 'Accepted risk', 'icon': 'triangle-alert', 'color': 'orange', 'kind': 'exception',
         'requires_reason': True, 'requires_decision': True,
         'description': 'Left as it is by a recorded war-room decision'},
    )},
)

# ------------------------------------------------------------------ war-room decisions

DECISION_STATUSES = ('proposed', 'approved', 'rejected', 'superseded')
DECISION_STATUS_LABELS = {'proposed': 'Proposed', 'approved': 'Approved', 'rejected': 'Rejected',
                          'superseded': 'Superseded'}
VERDICTS = ('pending', 'approved', 'rejected')
DECISION_TITLE_MAX = 256
DECISION_RATIONALE_MAX = 20000
DECISION_EVENTS = ('proposed', 'promoted', 'edited', 'vote_approved', 'vote_rejected', 'approved', 'rejected',
                   'status_set', 'superseded', 'implemented', 'reopened')

# ------------------------------------------------------------------ war-room Board

# Three zones: a row of indicator TILES across the top, then two columns of PANELS
# (main = wide, side = narrow). A tile has no column; a panel lives in one.
BOARD_ZONES = ('tile', 'panel')
BOARD_COLUMNS = ('main', 'side')
# type: (label, zone, default column of a panel - None for a tile, description)
BOARD_WIDGETS = {
    'kpi_compromised': ('Compromised', 'tile', None, 'Compromised assets and the ones without a flag'),
    'kpi_decisions': ('Open decisions', 'tile', None, 'Open, overdue and due-soon decisions'),
    'kpi_exceptions': ('Exceptions', 'tile', None, 'Assets with an exception flag'),
    'kpi_tasks': ('Open tasks', 'tile', None, 'Open war-room tasks'),
    'flags': ('Flags', 'tile', None, 'Progress and assets by flag'),
    'vuln_open': ('Open vulnerabilities', 'tile', None, 'Open findings on case assets'),
    'vuln_exploited': ('Exploited & open', 'tile', None, 'Exploited findings not fixed yet'),
    'vuln_overdue': ('Overdue vulnerabilities', 'tile', None, 'Open findings past their due date'),
    'vuln_kev': ('KEV open', 'tile', None, 'Open findings listed in CISA KEV'),
    'vuln_assets': ('Vulnerable assets', 'tile', None, 'Assets with an open finding'),
    'cases': ('Cases', 'panel', 'main', 'One card per attached case'),
    'decisions': ('Open decisions list', 'panel', 'side', 'The open decisions and their targets'),
    'attention': ('Needs attention', 'panel', 'side', 'What needs a look now'),
    'tasks': ('Tasks', 'panel', 'side', 'Open war-room tasks, the ones in progress first'),
    'note': ('Note', 'panel', 'side', 'A Markdown note for everyone in the room'),
}
# a wide tile takes two tracks of the tile row
BOARD_WIDE_TILES = ('flags',)
BOARD_DEFAULT = ('kpi_compromised', 'kpi_decisions', 'kpi_exceptions', 'kpi_tasks', 'flags',
                 'vuln_open', 'vuln_exploited', 'vuln_overdue', 'vuln_kev', 'vuln_assets',
                 'cases', 'decisions', 'attention', 'tasks')
# Widgets of the first Board (2026-11-07, never released) that a saved layout may still name:
# each becomes the tiles that replaced it when the layout is read.
BOARD_LEGACY = {
    'indicators': ('kpi_compromised', 'kpi_decisions', 'kpi_exceptions', 'kpi_tasks'),
    'vulnerabilities': ('vuln_open', 'vuln_exploited', 'vuln_overdue', 'vuln_kev', 'vuln_assets'),
}
BOARD_MAX_WIDGETS = 40
BOARD_TITLE_MAX = 80
BOARD_NOTE_MAX = 10000
# a decision is "due soon" when its target falls within this many hours
BOARD_DUE_SOON_HOURS = 24
# Needs attention lists at most this many lines (the reply says how many there were)
BOARD_ATTENTION_MAX = 50
# attention severities, most urgent first
BOARD_SEVERITIES = ('high', 'medium', 'low')

# ------------------------------------------------------------------ war-room Scope

# The Scope tab's filters (every asset of the attached cases the viewer can open).
SCOPE_KINDS = KINDS
SCOPE_VULNERABLE = ('open', 'exploited', 'kev', 'overdue', 'none')
SCOPE_SORTS = ('case', 'name', 'findings', 'compromise', 'updated')
# iris-ng 2026-11-08: the Scope as a workspace - bulk changes and pushes over selected assets.
SCOPE_GROUPS = ('case', 'vulnerability', 'none')
SCOPE_BULK_MAX = 500          # assets one bulk change or push may name
SCOPE_PUSH_CASES_MAX = 50     # target cases one push may name
SCOPE_COMPROMISE = (('to_be_determined', 'To be determined'), ('compromised', 'Compromised'),
                    ('not_compromised', 'Not compromised'), ('unknown', 'Unknown'))
SCOPE_PER_PAGE = 100
SCOPE_PER_PAGE_MAX = 500
# iris-ng 2026-11-08: the rest of the Scope - IOCs, customers, staging, the Assets Manager, export.
SCOPE_STAGED_KINDS = ('asset', 'ioc')     # what a war room's staging inbox holds
SCOPE_STAGED_TARGETS_MAX = 50             # target cases a staged object proposes
SCOPE_STAGED_MAX = 500                    # staged objects one room keeps
SCOPE_REGISTRY_ATTACH_MAX = 100           # registry assets one attach may name
SCOPE_EXPORT_FORMATS = ('txt', 'csv', 'stix')
SCOPE_TLP_RED = 1                         # ioc_tlp_id of TLP:RED (txt / CSV leave it out unless asked)


def sql_in(column, values):
    """`column IN ('a', 'b')` for a CHECK constraint (the values are code constants)."""
    return "%s IN (%s)" % (column, ", ".join("'%s'" % v.replace("'", "''") for v in values))

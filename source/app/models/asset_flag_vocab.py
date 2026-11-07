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

BOARD_COLUMNS = ('main', 'side')
# type: (label, default column, description)
BOARD_WIDGETS = {
    'indicators': ('Indicators', 'main', 'Figures in a row of tiles'),
    'attention': ('Needs attention', 'main', 'What needs a look now'),
    'flags': ('Assets by flag', 'main', 'Progress and assets by status flag'),
    'cases': ('Cases', 'main', 'One card per attached case'),
    'decisions': ('Open decisions', 'side', 'The open decisions and their targets'),
    'tasks': ('Open tasks', 'side', 'Open war-room tasks, the ones in progress first'),
    'vulnerabilities': ('Vulnerabilities', 'side', 'Open findings on the assets of the attached cases'),
    'note': ('Note', 'side', 'A Markdown note for everyone in the room'),
}
BOARD_DEFAULT = (('indicators', 'main'), ('attention', 'main'), ('flags', 'main'), ('cases', 'main'),
                 ('decisions', 'side'), ('tasks', 'side'), ('vulnerabilities', 'side'))
BOARD_MAX_WIDGETS = 24
BOARD_TITLE_MAX = 80
BOARD_NOTE_MAX = 10000


def sql_in(column, values):
    """`column IN ('a', 'b')` for a CHECK constraint (the values are code constants)."""
    return "%s IN (%s)" % (column, ", ".join("'%s'" % v.replace("'", "''") for v in values))

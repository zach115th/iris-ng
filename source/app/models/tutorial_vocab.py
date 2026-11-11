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

"""Tutorials (iris-ng 2026-11-10): the ONE vocabulary. Import-free on purpose: the model's CHECKs, the migration,
the validation in business.tutorials, the editor (through GET /api/v2/manage/tutorials/vocab) and the suites all
read these names and limits from here.

A tutorial file:

    {"format": FORMAT, "title": ..., "summary": ..., "duration": "~5 min", "audience": "everyone" | "admins",
     "steps": [{"title": ..., "body": ...,                     # **bold**, `code`, {var}
                "anchor": ["case-quick-add", "#css .selector"],  # a data-tour name or a CSS selector per entry;
                                                               # the first one visible on the page is highlighted
                "goTo": "/case/ioc?cid={caseId}",              # "Take me there", a path on this server
                "fills": [{"label": ..., "anchor": ..., "value": ...}],
                "waitFor": {"kind": "element", "anchor": ...}  # absent = the learner clicks Next
                         | {"kind": "page", "path": "/case/ioc?cid={caseId}", "capture": {"caseId": "cid"}}
                         | {"kind": "request", "method": "POST", "path": "/api/v2/cases",
                            "capture": {"caseId": "case_id"}},
                "cleanup": [{"kind": "case", "var": "caseId"}]}]}

`{name}` in a body, anchor, path or fill value is a value captured earlier in the same run. A page path's `*` matches
any one path segment or any query value; a request path matches the URL path only (its query is not compared)."""

FORMAT = 'iris-ng-tutorial/1'

AUDIENCES = ('everyone', 'admins')
AUDIENCE_LABELS = {'everyone': 'Everyone', 'admins': 'Administrators'}

# How a step knows it is done. 'next' is the absence of waitFor; it is listed so the editor offers it.
DONE_WHEN = ('next', 'element', 'page', 'request')
DONE_WHEN_LABELS = {
    'next': 'The learner clicks Next',
    'element': 'Something appears on the page',
    'page': 'A page opens',
    'request': 'IRIS saves something (a request succeeds)',
}
METHODS = ('POST', 'PUT', 'DELETE', 'GET')

# What a step may offer to delete: only what the learner created during this run (business.tutorials.cleanup),
# with the normal right to delete it (a catalogue entry: server administrators only).
CLEANUP_KINDS = ('case', 'war_room', 'vulnerability')
CLEANUP_LABELS = {'case': 'Delete the case', 'war_room': 'Delete the war room',
                  'vulnerability': 'Delete the catalogue vulnerability'}

LIMITS = {
    'title': 120,
    'summary': 400,
    'duration': 24,
    'steps': 40,
    'step_title': 120,
    'body': 1500,
    'anchors': 4,
    'anchor': 300,
    'fills': 4,
    'fill_label': 60,
    'fill_value': 2000,
    'path': 300,
    'captures': 4,
    'cleanup': 3,
    'run_vars': 12,
    'var_value': 200,
    'team_tutorials': 200,
    'file_bytes': 262144,
}

# A data-tour name; any other anchor text is a CSS selector.
ANCHOR_NAME_RE = r'^[a-z0-9][a-z0-9-]{0,63}$'
VAR_RE = r'^[A-Za-z][A-Za-z0-9_]{0,31}$'
# Where a request capture reads in the JSON reply (dots walk objects, digits index lists) or a page capture's query
# parameter name.
CAPTURE_PATH_RE = r'^[A-Za-z0-9_\-]{1,40}(\.[A-Za-z0-9_\-]{1,40}){0,5}$'
# A path on this server: one leading slash (never two, never a scheme), then the characters of a path + query,
# {var} placeholders and the * wildcard.
PATH_RE = r'^/(?![/\\])[A-Za-z0-9\-._~/?=&%{}*:+,]*$'
VAR_REF_RE = r'\{([A-Za-z][A-Za-z0-9_]{0,31})\}'

# The built-in tutorials, in list order (files resources/tutorials/<key>.json).
BUILTIN_KEYS = ('first-investigation', 'alert-triage', 'hand-over', 'vulnerability-crisis', 'write-a-tutorial')

# Run references: a built-in by key, a team tutorial by id, and each user's one preview ("Try it" in the editor).
REF_RE = r'^(builtin-[a-z0-9-]{1,60}|team-[0-9]{1,9})$'
PREVIEW_REF = 'preview'

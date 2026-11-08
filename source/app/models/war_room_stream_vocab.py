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

"""The war-room Stream's vocabulary (iris-ng, 2026-11-08).

Import-free on purpose: the ORM CHECKs, the migration, the API validation and the page
(`GET /api/v2/war-rooms/<id>/stream/vocab`) all read these tuples, so one edit here moves every
layer. A new value in a CHECKed tuple still needs a migration that swaps the CHECK on existing
databases.
"""
import re
import unicodedata

# ------------------------------------------------------------------ stream item kinds
# Every item the stream returns carries one of these `kind`s.
KINDS = (
    'message',            # a chat message (a reply lives in its thread, not in the chat)
    'poll',               # a poll
    'priority',           # the room's priority (severity) was set
    'note',               # a room note was created (Notes tab)
    'pin',                # a message was pinned
    'decision',           # a decision of the register moved (derived from its trail)
    'sitrep_published',   # a SitRep was published
    'case_attached',
    'case_detached',
    'case_activity',      # activity on an attached case the viewer can open
    'war_room_activity',  # any other change in the room (members, teams, notes, tasks, timelines...)
    'task_assigned',
    'task_completed',
    'system',             # the room itself: created, its state, a guest joining through the portal
)

# Kinds that never leave the chat, whatever a person's settings say.
ALWAYS_CHAT = ('message', 'poll', 'priority')

# The kinds the room activity log (`war_room_activity.kind`) stores.
ACTIVITY_KINDS = ('priority', 'note', 'pin', 'sitrep_published', 'case_attached', 'case_detached',
                  'war_room_activity', 'task_assigned', 'task_completed', 'system')

# Lanes a person routes to the Activity panel ("rail"), the chat, or nowhere ("off"):
# (key, label, kinds, default route).
LANES = (
    ('case_activity', 'Case activity', ('case_activity',), 'rail'),
    ('room_activity', 'War-room activity', ('war_room_activity',), 'rail'),
    ('tasks', 'Tasks', ('task_assigned', 'task_completed'), 'rail'),
    ('system', 'System', ('system',), 'rail'),
    ('notes', 'Notes / Pins', ('note', 'pin'), 'chat'),
    ('decisions', 'Decisions', ('decision',), 'chat'),
    ('sitreps', 'SitReps', ('sitrep_published',), 'chat'),
    ('case_link', 'Case attached / detached', ('case_attached', 'case_detached'), 'chat'),
)
LANE_KEYS = tuple(k for k, _, _, _ in LANES)
ROUTES = ('rail', 'chat', 'off')

# War-room activity families: the part of `activity_type` before the dot.
FAMILIES = (
    ('room', 'War room'),
    ('member', 'Members'),
    ('team', 'Teams'),
    ('topic', 'Topics'),
    ('note', 'Notes'),
    ('folder', 'Note folders'),
    ('task', 'Tasks'),
    ('timeline', 'Timelines'),
    ('event', 'Timeline events'),
    ('sitrep', 'SitReps'),
    ('vulnerability', 'Vulnerabilities'),
    ('system', 'System'),
)
FAMILY_KEYS = tuple(k for k, _ in FAMILIES)

# Case activity types (slug = `<object>.<verb>`), grouped as the settings list them.
CASE_ACTIVITY = (
    ('notes', 'Notes', (('note.created', 'Created'), ('note.updated', 'Updated'), ('note.deleted', 'Deleted'),
                        ('directory.created', 'Folder created'), ('directory.updated', 'Folder updated'),
                        ('directory.deleted', 'Folder deleted'))),
    ('iocs', 'IOCs', (('ioc.created', 'Created'), ('ioc.updated', 'Updated'), ('ioc.deleted', 'Deleted'))),
    ('assets', 'Assets', (('asset.created', 'Created'), ('asset.updated', 'Updated'),
                          ('asset.deleted', 'Deleted'))),
    ('evidence', 'Evidence', (('evidence.created', 'Added'), ('evidence.updated', 'Updated'),
                              ('evidence.deleted', 'Deleted'))),
    ('datastore', 'Datastore', (('datastore.created', 'Added'), ('datastore.updated', 'Updated'),
                                ('datastore.deleted', 'Deleted'))),
    ('tasks', 'Tasks', (('task.created', 'Added'), ('task.updated', 'Updated'), ('task.deleted', 'Deleted'))),
    ('events', 'Timeline events', (('event.created', 'Added'), ('event.updated', 'Updated'),
                                   ('event.deleted', 'Deleted'))),
    ('case', 'Case lifecycle', (('case.created', 'Created'), ('case.closed', 'Closed'),
                                ('case.reopened', 'Re-opened'), ('case.updated', 'Updated'),
                                ('case.reviewer_changed', 'Reviewer changed'),
                                ('alert.linked', 'Alert linked / unlinked'))),
    ('other', 'Other', (('case.other', 'Uncategorised'),)),
)
CASE_ACTIVITY_SLUGS = tuple(s for _, _, slugs in CASE_ACTIVITY for s, _ in slugs)

# --------------------------------------------------------------------------- limits
MESSAGE_MAX = 20000
TOPIC_NAME_MAX = 64
THREAD_TITLE_MAX = 200
REACTIONS_PER_MESSAGE = 20
EMOJI_MAX_LEN = 32
PAGE_DEFAULT = 50
PAGE_MAX = 300
THREADS_MAX = 200
INDEX_MAX = 300
FILE_MAX_BYTES = 25 * 1024 * 1024
FILE_NAME_MAX = 200
FILES_PER_MESSAGE = 10
# An edit of the same object by the same person within this window updates the previous log line
# instead of adding one (a note saved every few seconds stays one "Updated note" line).
COALESCE_MINUTES = 10
RAIL_WIDTH = (260, 640, 340)        # min, max, default (px)
EXCLUDED_CASES_MAX = 500

# A file token in a message: #[file:<id>|<name>] (the picker inserts it; the server validates the id).
FILE_TOKEN_RE = re.compile(r'#\[file:(\d{1,18})\|([^\]\n]{1,%d})\]' % FILE_NAME_MAX)

# Raster images shown inline, recognised by their first bytes only (never by name or declared type).
IMAGE_MAGIC = (
    (b'\x89PNG\r\n\x1a\n', 'image/png'),
    (b'\xff\xd8\xff', 'image/jpeg'),
    (b'GIF87a', 'image/gif'),
    (b'GIF89a', 'image/gif'),
)


def image_type(head):
    """The image MIME type of a file from its first bytes, or None (WebP: RIFF....WEBP)."""
    if not head:
        return None
    for magic, mime in IMAGE_MAGIC:
        if head.startswith(magic):
            return mime
    if len(head) >= 12 and head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp'
    return None


def sql_in(column, values):
    """`column IN ('a', 'b')` for a CHECK constraint (the values are code constants)."""
    return "%s IN (%s)" % (column, ", ".join("'%s'" % v.replace("'", "''") for v in values))


def lane_of(kind):
    """The lane a kind belongs to, or None for the kinds that always stay in the chat."""
    for key, _, kinds, _ in LANES:
        if kind in kinds:
            return key
    return None


def family_of(activity_type):
    """The war-room activity family of `<family>.<verb>`; anything unknown reads as 'room'."""
    fam = (activity_type or '').split('.', 1)[0]
    return fam if fam in FAMILY_KEYS else 'room'


# ----------------------------------------------------------------------------- emoji
# A reaction is one emoji: pictographic code points plus the joiners and modifiers that build one.
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2300, 0x23FF), (0x2B00, 0x2BFF), (0x2190, 0x21FF),
    (0x25A0, 0x25FF), (0x2900, 0x297F), (0x3030, 0x3030), (0x303D, 0x303D), (0x3297, 0x3297),
    (0x3299, 0x3299), (0x00A9, 0x00A9), (0x00AE, 0x00AE), (0x203C, 0x203C), (0x2049, 0x2049),
    (0x2122, 0x2122), (0x2139, 0x2139), (0x24C2, 0x24C2),
)
_EMOJI_JOINERS = {0x200D, 0xFE0F, 0xFE0E, 0x20E3}
_EMOJI_TAGS = (0xE0020, 0xE007F)


def _pictographic(cp):
    return any(a <= cp <= b for a, b in _EMOJI_RANGES)


def is_emoji(value):
    """True when `value` is ONE emoji: a pictograph, optionally joined (ZWJ) to more pictographs, with its
    variation selector, keycap or tag characters; a flag is a pair of regional indicators. No letters,
    digits, spaces or markup, and never two emoji side by side."""
    if not isinstance(value, str) or not value or len(value) > EMOJI_MAX_LEN:
        return False
    if unicodedata.normalize('NFC', value) != value:
        return False
    starts, prev, open_flag = 0, None, False
    for ch in value:
        cp = ord(ch)
        if _pictographic(cp):
            if 0x1F1E6 <= cp <= 0x1F1FF:          # regional indicator: two make one flag
                if open_flag:
                    open_flag, prev = False, cp
                    continue
                open_flag = True
            if prev != 0x200D:
                starts += 1
        elif not (cp in _EMOJI_JOINERS or _EMOJI_TAGS[0] <= cp <= _EMOJI_TAGS[1]):
            return False
        prev = cp
    return starts == 1


# ------------------------------------------------------------------------ preferences
def default_prefs():
    return {
        'routes': {key: route for key, _, _, route in LANES},
        'foldBursts': True,
        'quietMode': False,
        'railOpen': True,
        'railWidth': RAIL_WIDTH[2],
        'excludedCases': [],
        'excludedCaseActivities': {},
        'excludedRoomActivities': [],
    }


def _int_list(values, cap):
    out = []
    for v in values if isinstance(values, list) else []:
        if isinstance(v, bool):
            continue
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n > 0 and n not in out:
            out.append(n)
        if len(out) >= cap:
            break
    return out


def normalise_prefs(raw):
    """A person's Activity settings, every unknown key or value dropped and every missing one defaulted."""
    out = default_prefs()
    if not isinstance(raw, dict):
        return out
    routes = raw.get('routes')
    if isinstance(routes, dict):
        for key in LANE_KEYS:
            if routes.get(key) in ROUTES:
                out['routes'][key] = routes[key]
    for key in ('foldBursts', 'quietMode', 'railOpen'):
        if isinstance(raw.get(key), bool):
            out[key] = raw[key]
    width = raw.get('railWidth')
    if isinstance(width, int) and not isinstance(width, bool):
        out['railWidth'] = max(RAIL_WIDTH[0], min(RAIL_WIDTH[1], width))
    out['excludedCases'] = _int_list(raw.get('excludedCases'), EXCLUDED_CASES_MAX)
    per_case = raw.get('excludedCaseActivities')
    if isinstance(per_case, dict):
        for case_key, slugs in list(per_case.items())[:EXCLUDED_CASES_MAX]:
            ids = _int_list([case_key], 1)
            if not ids or not isinstance(slugs, list):
                continue
            kept = [s for s in dict.fromkeys(slugs) if s in CASE_ACTIVITY_SLUGS]
            if kept:
                out['excludedCaseActivities'][str(ids[0])] = kept
    fams = raw.get('excludedRoomActivities')
    if isinstance(fams, list):
        out['excludedRoomActivities'] = [f for f in dict.fromkeys(fams) if f in FAMILY_KEYS]
    return out


def as_dict():
    """The vocabulary the page reads."""
    return {
        'kinds': list(KINDS),
        'always_chat': list(ALWAYS_CHAT),
        'lanes': [{'key': k, 'label': lbl, 'kinds': list(kinds), 'route': route} for k, lbl, kinds, route in LANES],
        'routes': list(ROUTES),
        'families': [{'key': k, 'label': lbl} for k, lbl in FAMILIES],
        'case_activity': [{'key': k, 'label': lbl, 'slugs': [{'slug': s, 'label': sl} for s, sl in slugs]}
                          for k, lbl, slugs in CASE_ACTIVITY],
        'defaults': default_prefs(),
        'limits': {'message_max': MESSAGE_MAX, 'topic_name_max': TOPIC_NAME_MAX,
                   'thread_title_max': THREAD_TITLE_MAX, 'file_max_bytes': FILE_MAX_BYTES,
                   'files_per_message': FILES_PER_MESSAGE, 'page': PAGE_DEFAULT,
                   'rail_width': list(RAIL_WIDTH)},
    }

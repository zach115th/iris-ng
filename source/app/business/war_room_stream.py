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

"""The war-room Stream (iris-ng, 2026-11-08): one paged feed over the room's messages, polls, activity
log, the attached cases' activity and the decision trail, plus threads, reactions, edits, topics, the
Decisions & Pins index, files attached in the chat and each person's Activity settings.

The page asks for the kinds it shows in one place (the chat, or the Activity panel - a person's settings
route each lane) and pages backwards with an opaque cursor: items are ordered by (time, source, id),
newest first, and every source is cut at the cursor in SQL, so no item is skipped or repeated at a page
boundary even when many share a timestamp.
"""
import hashlib
import os
import re
import shutil
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import and_
from sqlalchemy import desc
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

import app
from app import db
from app.business.errors import BusinessProcessingError
from app.models import war_room_stream_vocab as sv
from app.models.authorization import User
from app.models.models import UserActivity
from app.models.models import WarRoomActivity
from app.models.models import WarRoomDecision
from app.models.models import WarRoomDecisionEvent
from app.models.models import WarRoomFile
from app.models.models import WarRoomGuest
from app.models.models import WarRoomMessage
from app.models.models import WarRoomMessageReaction
from app.models.models import WarRoomNote
from app.models.models import WarRoomPoll
from app.models.models import WarRoomStreamPref
from app.models.models import WarRoomThreadFollow
from app.models.models import WarRoomTopic

# Source order inside one timestamp (part of the cursor).
_SRC = {'message': 1, 'poll': 2, 'activity': 3, 'case_activity': 4, 'decision': 5}


class StreamError(BusinessProcessingError):
    """A refused stream request; `status` is the HTTP status the route answers with."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.utcnow()


def _like(q):
    return '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def _clip(text, n):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= n else text[:n - 1] + '…'


def _writable(room):
    from app.business.war_rooms import _assert_writable
    _assert_writable(room)


def _names(user_ids=(), guest_ids=()):
    users = {i for i in user_ids if i}
    guests = {i for i in guest_ids if i}
    u = {x.id: x.name for x in User.query.filter(User.id.in_(users))} if users else {}
    g = {x.id: x.label for x in WarRoomGuest.query.filter(WarRoomGuest.id.in_(guests))} if guests else {}
    return u, g


# ---------------------------------------------------------------------------- cursor

def encode_cursor(ts, src, oid):
    return '%s~%d~%d' % (ts.isoformat(), src, oid)


def parse_cursor(raw):
    if raw in (None, ''):
        return None
    try:
        ts, src, oid = str(raw).split('~')
        return datetime.fromisoformat(ts), int(src), int(oid)
    except (ValueError, TypeError):
        raise StreamError('Invalid cursor')


def _keyset(col_ts, col_id, src, cur):
    if cur is None:
        return None
    ts, csrc, cid = cur
    if src < csrc:
        return col_ts <= ts
    if src > csrc:
        return col_ts < ts
    return or_(col_ts < ts, and_(col_ts == ts, col_id < cid))


def _cut(query, col_ts, col_id, src, cur, limit):
    cond = _keyset(col_ts, col_id, src, cur)
    if cond is not None:
        query = query.filter(cond)
    return query.order_by(desc(col_ts), desc(col_id)).limit(limit + 1).all()


# ------------------------------------------------------------------- case activity types
_QUOTED = re.compile(r'"[^"]*"|\'[^\']*\'')
_FAMILY_SLUG = {'timeline': 'event', 'ioc': 'ioc', 'asset': 'asset', 'note': 'note', 'task': 'task',
                'evidence': 'evidence', 'datastore': 'datastore'}


def case_activity_type(description):
    """`<object>.<verb>` for one case activity line (they are text only). The object comes from the
    shared classifier the case log uses; anything it cannot place is `case.other`."""
    from app.datamgmt.case.case_notifications_db import classify_activity
    text = _QUOTED.sub('""', description or '').lower()
    category = classify_activity(description)
    if category is None:
        return 'case.other'
    if category == 'case':
        if 'alert' in text:
            return 'alert.linked'
        if re.search(r'\breopen', text):
            return 'case.reopened'
        if re.search(r'\bclos', text):
            return 'case.closed'
        if 'review' in text:
            return 'case.reviewer_changed'
        if re.search(r'\b(created|opened)\b', text):
            return 'case.created'
        return 'case.updated'
    family = _FAMILY_SLUG[category]
    if family == 'note' and re.search(r'\bdirector', text):
        family = 'directory'
    if re.search(r'\b(deleted|removed|unlinked)\b', text):
        verb = 'deleted'
    elif re.search(r'\b(added|created|uploaded|imported|new)\b', text):
        verb = 'created'
    else:
        verb = 'updated'
    return '%s.%s' % (family, verb)


# --------------------------------------------------------------------------- messages
def _files_by_message(room_id, msgs):
    wanted = {}
    for m in msgs:
        ids = [int(x.group(1)) for x in sv.FILE_TOKEN_RE.finditer(m.content or '')]
        if ids:
            wanted[m.id] = ids
    if not wanted:
        return {}
    every = {i for ids in wanted.values() for i in ids}
    rows = {f.id: f for f in WarRoomFile.query.filter(WarRoomFile.room_id == room_id, WarRoomFile.id.in_(every))}
    return {mid: [file_row(rows[i]) for i in dict.fromkeys(ids) if i in rows] for mid, ids in wanted.items()}


def file_row(f):
    return {'id': f.id, 'filename': f.filename, 'size': f.size, 'mime_type': f.mime_type,
            'is_image': f.mime_type.startswith('image/'), 'created_at': f.created_at}


def reactions_for(message_ids, viewer_id=None, viewer_guest_id=None):
    """{message_id: [{emoji, count, mine, names}]} in first-reaction order."""
    if not message_ids:
        return {}
    rows = (WarRoomMessageReaction.query.filter(WarRoomMessageReaction.message_id.in_(list(message_ids)))
            .order_by(WarRoomMessageReaction.created_at, WarRoomMessageReaction.id).all())
    users, guests = _names([r.user_id for r in rows], [r.guest_id for r in rows])
    out = {}
    for r in rows:
        per = out.setdefault(r.message_id, {})
        e = per.setdefault(r.emoji, {'emoji': r.emoji, 'count': 0, 'mine': False, 'names': []})
        e['count'] += 1
        if (viewer_guest_id and r.guest_id == viewer_guest_id) or (
                viewer_id and not viewer_guest_id and r.user_id == viewer_id):
            e['mine'] = True
        if len(e['names']) < 12:
            e['names'].append(users.get(r.user_id) if r.user_id else guests.get(r.guest_id, 'a guest'))
    return {mid: list(per.values()) for mid, per in out.items()}


def _reply_stats(root_ids):
    if not root_ids:
        return {}
    rows = (db.session.query(WarRoomMessage.parent_id, func.count(WarRoomMessage.id), func.max(WarRoomMessage.created_at))
            .filter(WarRoomMessage.parent_id.in_(list(root_ids)), WarRoomMessage.deleted_at.is_(None))
            .group_by(WarRoomMessage.parent_id).all())
    return {pid: (n, last) for pid, n, last in rows}


def message_items(room, msgs, viewer_id=None, viewer_guest_id=None):
    from app.business.war_rooms import actor_label
    ids = [m.id for m in msgs]
    reactions = reactions_for(ids, viewer_id, viewer_guest_id)
    files = _files_by_message(room.id, msgs)
    stats = _reply_stats([m.id for m in msgs if m.parent_id is None])
    out = []
    for m in msgs:
        n, last = stats.get(m.id, (0, None))
        out.append({
            'kind': 'message', 'key': 'message:%d' % m.id, 'id': m.id, 'created_at': m.created_at,
            'user_id': m.user_id, 'user_name': actor_label(m.user, m.guest), 'guest_id': m.guest_id,
            'is_guest': m.guest_id is not None, 'content': m.content, 'topic': m.topic, 'msg_kind': m.kind,
            'parent_id': m.parent_id, 'thread_title': m.thread_title, 'pinned': m.pinned,
            'edited_at': m.edited_at, 'reply_count': n, 'last_reply_at': last,
            'reactions': reactions.get(m.id, []), 'files': files.get(m.id, []),
        })
    return out


def _message_query(room):
    return (WarRoomMessage.query.options(joinedload(WarRoomMessage.user), joinedload(WarRoomMessage.guest))
            .filter(WarRoomMessage.room_id == room.id, WarRoomMessage.deleted_at.is_(None)))


# ------------------------------------------------------------------------------- feed
def parse_kinds(raw):
    if raw in (None, ''):
        return list(sv.KINDS)
    kinds = [k.strip() for k in str(raw).split(',') if k.strip()]
    bad = [k for k in kinds if k not in sv.KINDS]
    if bad:
        raise StreamError('Unknown stream kind: %s' % ', '.join(sorted(set(bad)))[:200])
    return list(dict.fromkeys(kinds))


def parse_limit(raw):
    if raw in (None, ''):
        return sv.PAGE_DEFAULT
    try:
        n = int(raw)
    except (TypeError, ValueError):
        raise StreamError('Invalid limit')
    return max(1, min(sv.PAGE_MAX, n))


def stream_page(room, viewer_id, viewer_guest_id=None, kinds=None, before=None, limit=None, topics=None,
                q=None, include_replies=False):
    """{items, next_cursor} - newest first, `limit` items at most, older than `before`."""
    from app.business.war_rooms import room_visible_case_ids
    from app.business.war_rooms import serialize_poll
    from app.business import war_room_decisions as wd
    kinds = parse_kinds(','.join(kinds) if isinstance(kinds, (list, tuple)) else kinds)
    cur = parse_cursor(before)
    limit = parse_limit(limit)
    q = (q or '').strip()[:200]
    pat = _like(q) if q else None
    entries = []      # (ts, src, id, item)

    if 'message' in kinds:
        mq = _message_query(room)
        if not include_replies:
            mq = mq.filter(WarRoomMessage.parent_id.is_(None))
        if topics:
            mq = mq.filter(WarRoomMessage.topic.in_(list(topics)))
        if pat:
            mq = mq.filter(or_(WarRoomMessage.content.ilike(pat, escape='\\'),
                               WarRoomMessage.thread_title.ilike(pat, escape='\\')))
        msgs = _cut(mq, WarRoomMessage.created_at, WarRoomMessage.id, _SRC['message'], cur, limit)
        for item in message_items(room, msgs, viewer_id, viewer_guest_id):
            entries.append((item['created_at'], _SRC['message'], item['id'], item))

    if 'poll' in kinds:
        pq = WarRoomPoll.query.filter(WarRoomPoll.room_id == room.id)
        if pat:
            pq = pq.filter(WarRoomPoll.question.ilike(pat, escape='\\'))
        polls = _cut(pq, WarRoomPoll.created_at, WarRoomPoll.id, _SRC['poll'], cur, limit)
        users, guests = _names([p.created_by for p in polls], [p.created_by_guest_id for p in polls])
        for p in polls:
            entries.append((p.created_at, _SRC['poll'], p.id, {
                'kind': 'poll', 'key': 'poll:%d' % p.id, 'id': p.id, 'created_at': p.created_at,
                'content': p.question, 'poll': serialize_poll(p, viewer_id, viewer_guest_id),
                'user_name': users.get(p.created_by) or guests.get(p.created_by_guest_id) or 'someone'}))

    act_kinds = [k for k in kinds if k in sv.ACTIVITY_KINDS]
    if act_kinds:
        aq = WarRoomActivity.query.filter(WarRoomActivity.room_id == room.id, WarRoomActivity.kind.in_(act_kinds))
        if pat:
            aq = aq.filter(WarRoomActivity.body.ilike(pat, escape='\\'))
        acts = _cut(aq, WarRoomActivity.created_at, WarRoomActivity.id, _SRC['activity'], cur, limit)
        users, guests = _names([a.actor_id for a in acts], [a.actor_guest_id for a in acts])
        for a in acts:
            entries.append((a.created_at, _SRC['activity'], a.id, {
                'kind': a.kind, 'key': 'activity:%d' % a.id, 'id': a.id, 'created_at': a.created_at,
                'activity_type': a.activity_type, 'family': sv.family_of(a.activity_type), 'content': a.body,
                'actor_name': (users.get(a.actor_id) if a.actor_id else guests.get(a.actor_guest_id))
                or ('IRIS' if not (a.actor_id or a.actor_guest_id) else 'someone'),
                'actor_is_guest': a.actor_guest_id is not None, 'ref_type': a.ref_type, 'ref_id': a.ref_id,
                'case_id': a.ref_case_id}))

    if 'case_activity' in kinds:
        visible = room_visible_case_ids(room.id, viewer_id, guest=viewer_guest_id is not None)
        if visible:
            cq = UserActivity.query.filter(UserActivity.case_id.in_(visible), UserActivity.display_in_ui.is_(True))
            if pat:
                cq = cq.filter(UserActivity.activity_desc.ilike(pat, escape='\\'))
            rows = _cut(cq, UserActivity.activity_date, UserActivity.id, _SRC['case_activity'], cur, limit)
            users, _ = _names([r.user_id for r in rows])
            for r in rows:
                entries.append((r.activity_date, _SRC['case_activity'], r.id, {
                    'kind': 'case_activity', 'key': 'case_activity:%d' % r.id, 'id': r.id,
                    'created_at': r.activity_date, 'case_id': r.case_id, 'content': r.activity_desc,
                    'actor_name': users.get(r.user_id) or 'IRIS',
                    'activity_type': case_activity_type(r.activity_desc)}))

    if 'decision' in kinds:
        dq = (db.session.query(WarRoomDecisionEvent, WarRoomDecision)
              .join(WarRoomDecision, WarRoomDecision.id == WarRoomDecisionEvent.decision_id)
              .filter(WarRoomDecisionEvent.room_id == room.id,
                      WarRoomDecisionEvent.action.in_(tuple(wd._STREAM_TEXT))))
        if pat:
            dq = dq.filter(WarRoomDecision.title.ilike(pat, escape='\\'))
        evs = _cut(dq, WarRoomDecisionEvent.at, WarRoomDecisionEvent.id, _SRC['decision'], cur, limit)
        names = wd._names([e.user_id for e, _ in evs])
        for e, d in evs:
            entries.append((e.at, _SRC['decision'], e.id, {
                'kind': 'decision', 'key': 'decision:%d' % e.id, 'id': e.id, 'created_at': e.at,
                'decision_id': d.id, 'action': e.action,
                'content': wd._STREAM_TEXT[e.action] % {'who': names.get(e.user_id) or 'someone', 'ref': wd.ref(d),
                                                        'title': d.title, 'detail': e.detail or ''}}))

    entries.sort(key=lambda x: (x[0] or datetime.min, x[1], x[2]), reverse=True)
    page = entries[:limit]
    more = len(entries) > limit
    nxt = encode_cursor(page[-1][0] or datetime.min, page[-1][1], page[-1][2]) if (more and page) else None
    return {'items': [e[3] for e in page], 'next_cursor': nxt}


# ------------------------------------------------------------------------------ topics
_TOPIC_RE = re.compile(r'^[^\s#\x00-\x1f\x7f][^\x00-\x1f\x7f]{0,%d}$' % (sv.TOPIC_NAME_MAX - 1))


def clean_topic_name(name):
    name = (name or '').strip().lstrip('#').strip()
    if not name or not _TOPIC_RE.match(name):
        raise StreamError('A topic name is 1 to %d characters, without line breaks' % sv.TOPIC_NAME_MAX)
    return name


def get_topic_row(room, name):
    return WarRoomTopic.query.filter_by(room_id=room.id, name=name).first()


def ensure_topic(room, name, user_id=None, guest_id=None):
    """The topic's row, created when a message first uses the name (no commit)."""
    row = get_topic_row(room, name)
    if row is None:
        row = WarRoomTopic(room_id=room.id, name=name, created_by=user_id, created_by_guest_id=guest_id)
        db.session.add(row)
        db.session.flush()
    return row


def topic_rows(room):
    """Every topic, # Main first, with message counts; archived ones carry `archived_at`."""
    rows = WarRoomTopic.query.filter_by(room_id=room.id).all()
    stats = dict((t, (n, last)) for t, n, last in db.session.query(
        WarRoomMessage.topic, func.count(WarRoomMessage.id), func.max(WarRoomMessage.created_at))
        .filter(WarRoomMessage.room_id == room.id, WarRoomMessage.deleted_at.is_(None))
        .group_by(WarRoomMessage.topic).all())
    by_name = {r.name: r for r in rows}
    users, guests = _names([r.created_by for r in rows] + [r.archived_by for r in rows],
                           [r.created_by_guest_id for r in rows] + [r.archived_by_guest_id for r in rows])
    out = []
    for name in set(by_name) | set(stats) | {'main'}:
        r = by_name.get(name)
        n, last = stats.get(name, (0, None))
        out.append({
            'id': r.id if r else None, 'name': name, 'is_main': name == 'main',
            'archived': bool(r and r.archived_at), 'archived_at': r.archived_at if r else None,
            'archived_by_name': (users.get(r.archived_by) or guests.get(r.archived_by_guest_id)) if r else None,
            'created_by': r.created_by if r else None, 'created_by_guest_id': r.created_by_guest_id if r else None,
            'created_by_name': (users.get(r.created_by) or guests.get(r.created_by_guest_id)) if r else None,
            'message_count': n, 'last_message_at': last})
    out.sort(key=lambda t: (not t['is_main'], t['archived'], t['name'].lower()))
    return out


def create_topic(room, name, user_id=None, guest_id=None):
    _writable(room)
    name = clean_topic_name(name)
    existing = get_topic_row(room, name)
    if existing is not None:
        raise StreamError('Topic #%s is archived - restore it instead' % name if existing.archived_at
                          else 'Topic #%s already exists' % name, status=409)
    row = WarRoomTopic(room_id=room.id, name=name, created_by=user_id, created_by_guest_id=guest_id)
    db.session.add(row)
    db.session.commit()
    return row


def set_topic_archived(room, topic_id, archived, user_id=None, guest_id=None, is_lead=False):
    _writable(room)
    row = db.session.get(WarRoomTopic, int(topic_id))
    if row is None or row.room_id != room.id:
        raise StreamError('Topic not found', status=404)
    if row.name == 'main':
        raise StreamError('# Main cannot be archived')
    own = (user_id and row.created_by == user_id) or (guest_id and row.created_by_guest_id == guest_id)
    if not (is_lead or own):
        raise StreamError('Only a lead or the person who created the topic can archive or restore it', status=403)
    if archived and row.archived_at is None:
        row.archived_at, row.archived_by, row.archived_by_guest_id = _now(), user_id, guest_id
    elif not archived and row.archived_at is not None:
        row.archived_at = row.archived_by = row.archived_by_guest_id = None
    db.session.commit()
    return row


def assert_topic_open(room, name):
    row = get_topic_row(room, name)
    if row is not None and row.archived_at is not None:
        raise StreamError('Topic #%s is archived - it is read-only' % name)


# ------------------------------------------------------------------------- the messages
def get_message(room, message_id, allow_deleted=False):
    try:
        msg = db.session.get(WarRoomMessage, int(message_id))
    except (TypeError, ValueError):
        msg = None
    if msg is None or msg.room_id != room.id or (msg.deleted_at is not None and not allow_deleted):
        raise StreamError('Message not found', status=404)
    return msg


def _is_author(msg, user_id, guest_id):
    if guest_id:
        return msg.guest_id == guest_id
    return bool(user_id) and msg.user_id == user_id and msg.guest_id is None


def check_message_files(room, content):
    """Every #[file:id|name] token of a message must name a file of this room."""
    ids = list(dict.fromkeys(int(m.group(1)) for m in sv.FILE_TOKEN_RE.finditer(content or '')))
    if not ids:
        return []
    if len(ids) > sv.FILES_PER_MESSAGE:
        raise StreamError('At most %d attachments per message' % sv.FILES_PER_MESSAGE)
    found = {f.id for f in WarRoomFile.query.filter(WarRoomFile.room_id == room.id, WarRoomFile.id.in_(ids))}
    if len(found) != len(ids):
        raise StreamError('An attachment is not a file of this room')
    return ids


def edit_message(room, message_id, content, user_id=None, guest_id=None):
    _writable(room)
    msg = get_message(room, message_id)
    if not _is_author(msg, user_id, guest_id):
        raise StreamError('Only the author can edit a message', status=403)
    assert_topic_open(room, msg.topic)
    content = (content or '').strip()
    if not content:
        raise StreamError('Empty message')
    if len(content) > sv.MESSAGE_MAX:
        raise StreamError('Message is too long')
    check_message_files(room, content)
    if content != msg.content:
        msg.content = content
        msg.edited_at = _now()
        db.session.commit()
    return msg


def delete_message(room, message_id, user_id=None, guest_id=None, is_lead=False):
    _writable(room)
    msg = get_message(room, message_id)
    if not (_is_author(msg, user_id, guest_id) or is_lead):
        raise StreamError('Only the author or a lead can delete a message', status=403)
    msg.deleted_at = _now()
    msg.deleted_by, msg.deleted_by_guest_id = (None, guest_id) if guest_id else (user_id, None)
    msg.pinned = False
    db.session.commit()
    return msg


def toggle_reaction(room, message_id, emoji, user_id=None, guest_id=None):
    _writable(room)
    msg = get_message(room, message_id)
    if not sv.is_emoji(emoji):
        raise StreamError('A reaction is one emoji')
    who = {'guest_id': guest_id} if guest_id else {'user_id': user_id}
    row = WarRoomMessageReaction.query.filter_by(message_id=msg.id, emoji=emoji, **who).first()
    if row is not None:
        db.session.delete(row)
    else:
        distinct = {e for (e,) in db.session.query(WarRoomMessageReaction.emoji)
                    .filter(WarRoomMessageReaction.message_id == msg.id).distinct()}
        if emoji not in distinct and len(distinct) >= sv.REACTIONS_PER_MESSAGE:
            raise StreamError('This message already has %d different reactions' % sv.REACTIONS_PER_MESSAGE)
        db.session.add(WarRoomMessageReaction(message_id=msg.id, emoji=emoji, **who))
    db.session.commit()
    return reactions_for([msg.id], user_id, guest_id).get(msg.id, [])


# ------------------------------------------------------------------------------ threads
def get_root(room, message_id):
    msg = get_message(room, message_id)
    if msg.parent_id is not None:
        raise StreamError('Not the first message of a thread')
    return msg


def _follow_row(root_id, user_id=None, guest_id=None):
    who = {'guest_id': guest_id} if guest_id else {'user_id': user_id}
    return WarRoomThreadFollow.query.filter_by(message_id=root_id, **who).first()


def ensure_follow(root_id, user_id=None, guest_id=None):
    """Follow a thread unless the person already chose (an explicit unfollow is kept). No commit."""
    if not (user_id or guest_id) or _follow_row(root_id, user_id, guest_id) is not None:
        return
    who = {'guest_id': guest_id} if guest_id else {'user_id': user_id}
    db.session.add(WarRoomThreadFollow(message_id=root_id, following=True, **who))


def set_follow(room, message_id, following, user_id=None, guest_id=None):
    _writable(room)
    root = get_root(room, message_id)
    row = _follow_row(root.id, user_id, guest_id)
    if row is None:
        who = {'guest_id': guest_id} if guest_id else {'user_id': user_id}
        row = WarRoomThreadFollow(message_id=root.id, **who)
        db.session.add(row)
    row.following = bool(following)
    row.updated_at = _now()
    db.session.commit()
    return row.following


def is_following(root_id, user_id=None, guest_id=None):
    row = _follow_row(root_id, user_id, guest_id)
    return bool(row and row.following)


def set_thread_title(room, message_id, title, user_id=None, guest_id=None, is_lead=False):
    _writable(room)
    root = get_root(room, message_id)
    if not (_is_author(root, user_id, guest_id) or is_lead):
        raise StreamError('Only the author or a lead can rename a thread', status=403)
    title = ' '.join((title or '').split())[:sv.THREAD_TITLE_MAX]
    root.thread_title = title or None
    db.session.commit()
    return root


def list_threads(room, viewer_id=None, viewer_guest_id=None):
    from app.business.war_rooms import actor_label
    agg = (db.session.query(WarRoomMessage.parent_id.label('pid'), func.count(WarRoomMessage.id).label('n'),
                            func.max(WarRoomMessage.created_at).label('last'))
           .filter(WarRoomMessage.room_id == room.id, WarRoomMessage.parent_id.isnot(None),
                   WarRoomMessage.deleted_at.is_(None))
           .group_by(WarRoomMessage.parent_id).subquery())
    rows = (db.session.query(WarRoomMessage, agg.c.n, agg.c.last)
            .options(joinedload(WarRoomMessage.user), joinedload(WarRoomMessage.guest))
            .outerjoin(agg, agg.c.pid == WarRoomMessage.id)
            .filter(WarRoomMessage.room_id == room.id, WarRoomMessage.parent_id.is_(None),
                    WarRoomMessage.deleted_at.is_(None),
                    or_(WarRoomMessage.thread_title.isnot(None), agg.c.n > 0))
            .order_by(desc(func.coalesce(agg.c.last, WarRoomMessage.created_at)), desc(WarRoomMessage.id))
            .limit(sv.THREADS_MAX).all())
    ids = [m.id for m, _, _ in rows]
    who = {'guest_id': viewer_guest_id} if viewer_guest_id else {'user_id': viewer_id}
    follows = {f.message_id: f.following for f in WarRoomThreadFollow.query.filter(
        WarRoomThreadFollow.message_id.in_(ids)).filter_by(**who)} if ids and (viewer_id or viewer_guest_id) else {}
    return [{'root_id': m.id, 'title': m.thread_title or _clip(m.content, 60), 'named': bool(m.thread_title),
             'author_name': actor_label(m.user, m.guest), 'topic': m.topic, 'created_at': m.created_at,
             'reply_count': n or 0, 'last_reply_at': last, 'following': bool(follows.get(m.id))}
            for m, n, last in rows]


def thread(room, message_id, viewer_id=None, viewer_guest_id=None):
    root = get_root(room, message_id)
    replies = (_message_query(room).filter(WarRoomMessage.parent_id == root.id)
               .order_by(WarRoomMessage.created_at, WarRoomMessage.id).all())
    items = message_items(room, [root] + replies, viewer_id, viewer_guest_id)
    return {'root': items[0], 'replies': items[1:],
            'following': is_following(root.id, viewer_id, viewer_guest_id)}


def notify_thread_reply(room, root, reply, author_name, actor_id=None, actor_guest_id=None):
    """Followers hear about a reply: users in the bell (event war_room_thread_reply, still room members),
    guests by email. Fail-soft."""
    try:
        from app.business.notifications import notify
        from app.business.war_rooms import member_user_ids
        rows = WarRoomThreadFollow.query.filter_by(message_id=root.id, following=True).all()
        members = set(member_user_ids(room.id))
        users = [r.user_id for r in rows if r.user_id and r.user_id != actor_id and r.user_id in members]
        title = '%s replied in the thread "%s" of war room "%s"' % (
            author_name, _clip(root.thread_title or root.content, 60), room.name)
        url = '/war-rooms/%d?pane=stream&thread=%d' % (room.id, root.id)
        if users:
            notify('war_room_thread_reply', users, title, body=(reply.content or '')[:280], object_type='war_room',
                   object_id=room.id, url=url, actor_id=actor_id)
        guest_ids = [r.guest_id for r in rows if r.guest_id and r.guest_id != actor_guest_id]
        if guest_ids:
            from app.business import war_room_guests as wg
            addr = wg.room_portal_address(room)
            for g in WarRoomGuest.query.filter(WarRoomGuest.id.in_(guest_ids)).all():
                if wg.guest_is_active(g, room):
                    wg.queue_guest_email(g, '[IRIS-NG] %s' % title, '%s\n\n%s\n\n%s' % (
                        title, (reply.content or '')[:500], ('Room address: %s\n' % addr) if addr else ''))
    except Exception:  # noqa: BLE001
        app.app.logger.exception('thread reply notify failed')


# ------------------------------------------------------------------ decisions & pins index
def room_index(room):
    """The Conversation rail's Decisions & Pins: the register's decisions, pinned messages and the room's
    notes, newest first."""
    from app.business import war_room_decisions as wd
    from app.business.war_rooms import actor_label
    items = []
    for d in WarRoomDecision.query.filter_by(room_id=room.id).order_by(desc(WarRoomDecision.id)).limit(sv.INDEX_MAX):
        items.append({'type': 'decision', 'id': d.id, 'title': '%s %s' % (wd.ref(d), d.title), 'status': d.status,
                      'created_at': d.created_at, 'author_name': None})
    pins = (_message_query(room).filter(WarRoomMessage.pinned.is_(True))
            .order_by(desc(WarRoomMessage.id)).limit(sv.INDEX_MAX).all())
    for m in pins:
        items.append({'type': 'pin', 'id': m.id, 'title': _clip(m.thread_title or m.content, 120),
                      'msg_kind': m.kind, 'topic': m.topic, 'parent_id': m.parent_id,
                      'created_at': m.created_at, 'author_name': actor_label(m.user, m.guest)})
    notes = WarRoomNote.query.filter_by(room_id=room.id).order_by(desc(WarRoomNote.id)).limit(sv.INDEX_MAX).all()
    users, guests = _names([n.created_by for n in notes], [n.created_by_guest_id for n in notes])
    for n in notes:
        items.append({'type': 'note', 'id': n.id, 'title': _clip(n.title, 120), 'created_at': n.created_at,
                      'author_name': users.get(n.created_by) or guests.get(n.created_by_guest_id)})
    items.sort(key=lambda i: i['created_at'] or datetime.min, reverse=True)
    return items[:sv.INDEX_MAX]


# -------------------------------------------------------------------------------- files
def room_files_dir(room_id):
    return Path(app.app.config['DATASTORE_PATH']) / 'war-rooms' / ('room-%d' % int(room_id))


def file_path(f):
    return room_files_dir(f.room_id) / ('wrf-%s' % f.file_uuid)


def clean_filename(name):
    name = (name or '').replace('\\', '/').rsplit('/', 1)[-1]
    name = ''.join(ch for ch in name if not unicodedata.category(ch).startswith('C'))
    name = name.replace(']', ')').replace('[', '(').strip().strip('.') or 'file'
    if len(name) > sv.FILE_NAME_MAX:
        stem, dot, ext = name.rpartition('.')
        name = (stem[:sv.FILE_NAME_MAX - len(ext) - 1] + '.' + ext) if dot and len(ext) <= 16 \
            else name[:sv.FILE_NAME_MAX]
    return name


def save_upload(room, upload, user_id=None, guest_id=None):
    """Store one uploaded file (a werkzeug FileStorage) in the room's folder; 25 MB at most."""
    _writable(room)
    if upload is None:
        raise StreamError('No file')
    name = clean_filename(upload.filename)
    folder = room_files_dir(room.id)
    folder.mkdir(parents=True, exist_ok=True)
    fid = uuid.uuid4()
    tmp = folder / ('.upload-%s' % fid)
    digest, size, head = hashlib.sha256(), 0, b''
    try:
        with open(tmp, 'wb') as out:
            while True:
                chunk = upload.stream.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > sv.FILE_MAX_BYTES:
                    raise StreamError('A file can be %d MB at most' % (sv.FILE_MAX_BYTES // (1024 * 1024)),
                                      status=413)
                if len(head) < 16:
                    head += chunk[:16 - len(head)]
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise StreamError('The file is empty')
        final = folder / ('wrf-%s' % fid)
        os.replace(tmp, final)
    finally:
        if tmp.exists():
            tmp.unlink()
    row = WarRoomFile(room_id=room.id, file_uuid=fid, filename=name, mime_type=sv.image_type(head) or
                      'application/octet-stream', size=size, sha256=digest.hexdigest(), uploaded_by=user_id,
                      uploaded_by_guest_id=guest_id)
    db.session.add(row)
    db.session.commit()
    return row


def get_file(room, file_id):
    try:
        f = db.session.get(WarRoomFile, int(file_id))
    except (TypeError, ValueError):
        f = None
    if f is None or f.room_id != room.id or not file_path(f).is_file():
        raise StreamError('File not found', status=404)
    return f


def delete_room_files(room_id):
    try:
        folder = room_files_dir(room_id)
        root = Path(app.app.config['DATASTORE_PATH']).resolve()
        if folder.is_dir() and root in folder.resolve().parents:
            shutil.rmtree(folder, ignore_errors=True)
    except Exception:  # noqa: BLE001
        app.app.logger.exception('war-room files of room %s not removed', room_id)


# ---------------------------------------------------------------------------- settings
def get_prefs(user_id):
    row = db.session.get(WarRoomStreamPref, user_id) if user_id else None
    return sv.normalise_prefs(row.prefs if row is not None else None)


def save_prefs(user_id, raw):
    if not isinstance(raw, dict):
        raise StreamError('Settings must be an object')
    prefs = sv.normalise_prefs(raw)
    row = db.session.get(WarRoomStreamPref, user_id)
    if row is None:
        row = WarRoomStreamPref(user_id=user_id)
        db.session.add(row)
    row.prefs = prefs
    row.updated_at = _now()
    db.session.commit()
    return prefs

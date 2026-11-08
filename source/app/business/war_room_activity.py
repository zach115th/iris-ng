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

"""The war room's activity log (iris-ng, 2026-11-08).

Every change to a room's own objects - members, guests, teams, notes and folders, tasks, timelines and
their events, SitReps, attached cases, tracked vulnerabilities, topics, pins, the room's state and
priority, the Board layout - writes one `war_room_activity` row with who made it, in the transaction
that made the change. A session listener does the writing, so no route can forget it: `before_flush`
reads what the flush is about to do (new, changed and deleted rows of the models in HANDLERS) and
`after_flush` inserts the lines with the ids the flush assigned.

The actor is the request's room principal (a user or a guest), else the signed-in user; outside a
request (a worker) it is NULL and the line reads as IRIS. An edit of the same object by the same person
within COALESCE_MINUTES moves the previous line forward instead of adding one. A room being deleted
writes nothing.

Decisions are not logged here: the register's trail already feeds its own lane.
"""
from sqlalchemy import event
from sqlalchemy import inspect
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.models import war_room_stream_vocab as sv
from app.models.authorization import User
from app.models.models import SitRep
from app.models.models import WarRoom
from app.models.models import WarRoomActivity
from app.models.models import WarRoomBoard
from app.models.models import WarRoomCaseLink
from app.models.models import WarRoomGuest
from app.models.models import WarRoomMember
from app.models.models import WarRoomMessage
from app.models.models import WarRoomNote
from app.models.models import WarRoomNoteFolder
from app.models.models import WarRoomTask
from app.models.models import WarRoomTeam
from app.models.models import WarRoomTeamGuest
from app.models.models import WarRoomTeamMember
from app.models.models import WarRoomTimeline
from app.models.models import WarRoomTimelineEvent
from app.models.models import WarRoomTopic
from app.models.models import WarRoomVulnerability

_PENDING = 'iris_wr_activity_pending'
_OFF = 'iris_wr_activity_off'

_TASK_STATUS = {'no_status': 'No status', 'todo': 'To do', 'in_progress': 'In progress', 'on_hold': 'On hold',
                'done': 'Done', 'cancelled': 'Cancelled'}


class Line:
    """One activity line waiting for its flush. `room` / `ref` may be ORM objects whose ids the flush
    assigns; they are read in after_flush."""
    __slots__ = ('room', 'kind', 'activity_type', 'body', 'ref_type', 'ref', 'ref_case_id', 'actor',
                 'coalesce')

    def __init__(self, room, kind, activity_type, body, ref_type=None, ref=None, ref_case_id=None, actor=None,
                 coalesce=False):
        self.room, self.kind, self.activity_type, self.body = room, kind, activity_type, body
        self.ref_type, self.ref, self.ref_case_id = ref_type, ref, ref_case_id
        self.actor, self.coalesce = actor, coalesce


def _id(value):
    if value is None or isinstance(value, int):
        return value
    return getattr(value, 'id', None)


def _clip(text, n=160):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= n else text[:n - 1] + '…'


def current_actor():
    """(user_id, guest_id) of whoever is acting in this request; (None, None) outside one."""
    try:
        from flask import g
        from flask import has_request_context
        if not has_request_context():
            return None, None
        p = getattr(g, 'room_principal', None)
        if p is not None:
            return (None, p.guest_id) if getattr(p, 'is_guest', False) else (p.user_id, None)
        from flask_login import current_user
        if current_user is not None and getattr(current_user, 'is_authenticated', False):
            return current_user.id, None
    except Exception:  # noqa: BLE001 - an actor is a nicety, never a reason to fail a write
        pass
    return None, None


def _changed(obj):
    """Names of the column attributes the flush will change on `obj`."""
    state = inspect(obj)
    out = set()
    for attr in state.mapper.column_attrs:
        hist = state.attrs[attr.key].history
        if hist.has_changes():
            out.add(attr.key)
    return out


def _was_unset(obj, key):
    """True when the attribute had no value before this change - or none the session knew of (an object
    inserted earlier in the same transaction carries no loaded previous value)."""
    hist = inspect(obj).attrs[key].history
    return not hist.deleted or hist.deleted[0] is None


def _user_name(session, uid):
    if not uid:
        return 'a user'
    with session.no_autoflush:
        u = session.get(User, uid)
    return u.name if u is not None else 'a user'


def _guest_label(session, gid):
    if not gid:
        return 'a guest'
    with session.no_autoflush:
        g = session.get(WarRoomGuest, gid)
    return g.label if g is not None else 'a guest'


def _parent(session, model, pid):
    if pid is None:
        return None
    with session.no_autoflush:
        return session.get(model, pid)


# ----------------------------------------------------------------------------- handlers
# Each handler(session, obj, op, changed, deleting) returns a list of Lines. `op` is 'insert', 'update' or
# 'delete'; `changed` the changed column names on an update; `deleting` the set of objects this flush deletes.

def _room(session, obj, op, changed, deleting):
    if op == 'insert':
        return [Line(obj, 'system', 'system.room_created', 'Created the war room', 'room', obj)]
    if op != 'update':
        return []
    if 'slug' in changed and _was_unset(obj, 'slug'):
        changed = changed - {'slug'}     # create_room assigns the first slug right after the insert
    out = []
    if 'status' in changed:
        out.append(Line(obj, 'system', 'system.status', 'Set the state to %s' % obj.status, 'room', obj))
    if 'severity' in changed:
        out.append(Line(obj, 'priority', 'room.priority',
                        'Set the priority to %s' % obj.severity if obj.severity else 'Cleared the priority',
                        'room', obj))
    if 'name' in changed:
        out.append(Line(obj, 'war_room_activity', 'room.renamed', 'Renamed the room to %s' % _clip(obj.name),
                        'room', obj))
    if changed & {'description', 'summary', 'slug', 'campaign_tag'}:
        out.append(Line(obj, 'war_room_activity', 'room.updated', 'Updated the room details', 'room', obj,
                        coalesce=True))
    return out


def _member(session, obj, op, changed, deleting):
    name = _user_name(session, obj.user_id)
    if op == 'insert':
        return [Line(obj.room_id, 'war_room_activity', 'member.added', 'Added %s as %s' % (name, obj.role),
                     'member', obj.user_id)]
    if op == 'update' and 'role' in changed:
        return [Line(obj.room_id, 'war_room_activity', 'member.role', "Changed %s's role to %s" % (name, obj.role),
                     'member', obj.user_id)]
    if op == 'delete':
        return [Line(obj.room_id, 'war_room_activity', 'member.removed', 'Removed %s' % name, 'member',
                     obj.user_id)]
    return []


def _guest(session, obj, op, changed, deleting):
    label = obj.label
    if op == 'insert':
        return [Line(obj.room_id, 'war_room_activity', 'member.guest_invited', 'Invited guest %s' % label,
                     'guest', obj)]
    if op == 'delete':
        return [Line(obj.room_id, 'war_room_activity', 'member.guest_removed', 'Removed guest %s' % label,
                     'guest', obj)]
    out = []
    if 'first_seen_at' in changed and obj.first_seen_at is not None and _was_unset(obj, 'first_seen_at'):
        out.append(Line(obj.room_id, 'system', 'system.guest_joined', 'Joined through the guest portal', 'guest',
                        obj, actor=(None, obj.id)))
    if 'revoked_at' in changed:
        out.append(Line(obj.room_id, 'war_room_activity',
                        'member.guest_revoked' if obj.revoked_at else 'member.guest_restored',
                        ('Revoked guest %s' if obj.revoked_at else 'Restored guest %s') % label, 'guest', obj))
    if 'expires_at' in changed:
        out.append(Line(obj.room_id, 'war_room_activity', 'member.guest_extended',
                        "Changed guest %s's access end" % label, 'guest', obj))
    if changed & {'display_name', 'organisation', 'handle', 'email'}:
        out.append(Line(obj.room_id, 'war_room_activity', 'member.guest_updated', 'Updated guest %s' % label,
                        'guest', obj, coalesce=True))
    return out


def _case_link(session, obj, op, changed, deleting):
    if op == 'insert':
        return [Line(obj.room_id, 'case_attached', 'case.attached', 'Attached case #%s' % obj.case_id, 'case',
                     obj.case_id, ref_case_id=obj.case_id)]
    if op == 'delete':
        return [Line(obj.room_id, 'case_detached', 'case.detached', 'Detached case #%s' % obj.case_id, 'case',
                     obj.case_id, ref_case_id=obj.case_id)]
    if 'note' in changed:
        return [Line(obj.room_id, 'war_room_activity', 'room.case_note',
                     'Updated the note on case #%s' % obj.case_id, 'case', obj.case_id, ref_case_id=obj.case_id,
                     coalesce=True)]
    return []


def _team(session, obj, op, changed, deleting):
    if op == 'insert':
        return [Line(obj.room_id, 'war_room_activity', 'team.created', 'Created team @%s' % obj.name, 'team', obj)]
    if op == 'delete':
        return [Line(obj.room_id, 'war_room_activity', 'team.deleted', 'Deleted team @%s' % obj.name, 'team', obj)]
    if changed & {'name', 'description', 'color'}:
        return [Line(obj.room_id, 'war_room_activity', 'team.updated', 'Updated team @%s' % obj.name, 'team', obj,
                     coalesce=True)]
    return []


def _team_link(session, obj, op, changed, deleting):
    team = obj.team if obj.team is not None else _parent(session, WarRoomTeam, obj.team_id)
    if team is None or team in deleting or op == 'update':
        return []
    who = (_user_name(session, obj.user_id) if isinstance(obj, WarRoomTeamMember)
           else _guest_label(session, obj.guest_id))
    if op == 'insert':
        return [Line(team.room_id, 'war_room_activity', 'team.member_added',
                     'Added %s to team @%s' % (who, team.name), 'team', team)]
    return [Line(team.room_id, 'war_room_activity', 'team.member_removed',
                 'Removed %s from team @%s' % (who, team.name), 'team', team)]


def _note(session, obj, op, changed, deleting):
    title = _clip(obj.title, 120)
    if op == 'insert':
        return [Line(obj.room_id, 'note', 'note.created', 'Created note: %s' % title, 'note', obj)]
    if op == 'delete':
        return [Line(obj.room_id, 'war_room_activity', 'note.deleted', 'Deleted note: %s' % title, 'note', obj)]
    if changed & {'title', 'content'}:
        return [Line(obj.room_id, 'war_room_activity', 'note.updated', 'Updated note: %s' % title, 'note', obj,
                     coalesce=True)]
    if 'folder_id' in changed:
        return [Line(obj.room_id, 'war_room_activity', 'note.moved', 'Moved note: %s' % title, 'note', obj)]
    return []


def _folder(session, obj, op, changed, deleting):
    name = _clip(obj.name, 120)
    if op == 'insert':
        return [Line(obj.room_id, 'war_room_activity', 'folder.created', 'Created note folder: %s' % name,
                     'folder', obj)]
    if op == 'delete':
        return [Line(obj.room_id, 'war_room_activity', 'folder.deleted', 'Deleted note folder: %s' % name,
                     'folder', obj)]
    if 'name' in changed:
        return [Line(obj.room_id, 'war_room_activity', 'folder.renamed', 'Renamed note folder to %s' % name,
                     'folder', obj)]
    return []


def _assignee(session, obj):
    if obj.assignee_id:
        return _user_name(session, obj.assignee_id)
    if obj.assignee_guest_id:
        return _guest_label(session, obj.assignee_guest_id)
    return None


def _task(session, obj, op, changed, deleting):
    title = _clip(obj.title, 120)
    if op == 'insert':
        out = [Line(obj.room_id, 'war_room_activity', 'task.created', 'Created task: %s' % title, 'task', obj)]
        who = _assignee(session, obj)
        if who:
            out.append(Line(obj.room_id, 'task_assigned', 'task.assigned', 'Assigned task %s to %s' % (title, who),
                            'task', obj))
        return out
    if op == 'delete':
        return [Line(obj.room_id, 'war_room_activity', 'task.deleted', 'Deleted task: %s' % title, 'task', obj)]
    out = []
    if 'status' in changed and obj.status == 'done':
        out.append(Line(obj.room_id, 'task_completed', 'task.completed', 'Completed task: %s' % title, 'task', obj))
    elif 'status' in changed:
        out.append(Line(obj.room_id, 'war_room_activity', 'task.status',
                        'Moved task %s to %s' % (title, _TASK_STATUS.get(obj.status, obj.status)), 'task', obj))
    if changed & {'assignee_id', 'assignee_guest_id'}:
        who = _assignee(session, obj)
        if who:
            out.append(Line(obj.room_id, 'task_assigned', 'task.assigned', 'Assigned task %s to %s' % (title, who),
                            'task', obj))
        else:
            out.append(Line(obj.room_id, 'war_room_activity', 'task.unassigned', 'Unassigned task: %s' % title,
                            'task', obj))
    if changed & {'title', 'description', 'due_date', 'tags', 'parent_task_id'}:
        out.append(Line(obj.room_id, 'war_room_activity', 'task.updated', 'Updated task: %s' % title, 'task', obj,
                        coalesce=True))
    return out


def _timeline(session, obj, op, changed, deleting):
    name = _clip(obj.name, 120)
    if op == 'insert':
        return [Line(obj.room_id, 'war_room_activity', 'timeline.created', 'Created timeline: %s' % name,
                     'timeline', obj)]
    if op == 'delete':
        return [Line(obj.room_id, 'war_room_activity', 'timeline.deleted', 'Deleted timeline: %s' % name,
                     'timeline', obj)]
    if changed & {'name', 'color'}:
        return [Line(obj.room_id, 'war_room_activity', 'timeline.updated', 'Updated timeline: %s' % name,
                     'timeline', obj, coalesce=True)]
    return []


def _event(session, obj, op, changed, deleting):
    tl = obj.timeline if obj.timeline is not None else _parent(session, WarRoomTimeline, obj.timeline_id)
    if tl is None or tl in deleting:
        return []
    title = _clip(obj.title, 120)
    if op == 'insert':
        return [Line(tl.room_id, 'war_room_activity', 'event.created', 'Added timeline event: %s' % title,
                     'event', obj)]
    if op == 'delete':
        return [Line(tl.room_id, 'war_room_activity', 'event.deleted', 'Deleted timeline event: %s' % title,
                     'event', obj)]
    if changed - {'updated_at'}:
        return [Line(tl.room_id, 'war_room_activity', 'event.updated', 'Updated timeline event: %s' % title,
                     'event', obj, coalesce=True)]
    return []


def _sitrep(session, obj, op, changed, deleting):
    title = _clip(obj.title, 120)
    if op == 'insert':
        if obj.status == 'published':
            return [Line(obj.room_id, 'sitrep_published', 'sitrep.published', 'Published SitRep: %s' % title,
                         'sitrep', obj)]
        return [Line(obj.room_id, 'war_room_activity', 'sitrep.created', 'Started SitRep draft: %s' % title,
                     'sitrep', obj)]
    if op == 'delete':
        return [Line(obj.room_id, 'war_room_activity', 'sitrep.deleted', 'Deleted SitRep: %s' % title, 'sitrep',
                     obj)]
    out = []
    if 'status' in changed and obj.status == 'published':
        out.append(Line(obj.room_id, 'sitrep_published', 'sitrep.published', 'Published SitRep: %s' % title,
                        'sitrep', obj))
    elif changed & {'title', 'content'}:
        out.append(Line(obj.room_id, 'war_room_activity', 'sitrep.updated', 'Updated SitRep: %s' % title, 'sitrep',
                        obj, coalesce=True))
    return out


def _vulnerability(session, obj, op, changed, deleting):
    vuln = obj.vulnerability
    if vuln is None and obj.vulnerability_id:
        from app.models.models import Vulnerability
        vuln = _parent(session, Vulnerability, obj.vulnerability_id)
    ident = vuln.identifier if vuln is not None else 'a vulnerability'
    if op == 'insert':
        return [Line(obj.room_id, 'war_room_activity', 'vulnerability.tracked', 'Started tracking %s' % ident,
                     'vulnerability', obj)]
    if op == 'delete':
        return [Line(obj.room_id, 'war_room_activity', 'vulnerability.untracked', 'Stopped tracking %s' % ident,
                     'vulnerability', obj)]
    if 'note' in changed:
        return [Line(obj.room_id, 'war_room_activity', 'vulnerability.updated', 'Updated the note on %s' % ident,
                     'vulnerability', obj, coalesce=True)]
    return []


def _board(session, obj, op, changed, deleting):
    if op == 'delete':
        return [Line(obj.room_id, 'war_room_activity', 'room.board', 'Reset the Board layout', 'room', obj.room_id)]
    if op == 'insert' or 'widgets' in changed:
        return [Line(obj.room_id, 'war_room_activity', 'room.board', 'Updated the Board layout', 'room', obj.room_id,
                     coalesce=True)]
    return []


def _topic(session, obj, op, changed, deleting):
    if obj.name == 'main':
        return []
    if op == 'insert':
        return [Line(obj.room_id, 'war_room_activity', 'topic.created', 'Created topic #%s' % obj.name, 'topic',
                     obj)]
    if op == 'update' and 'archived_at' in changed:
        if obj.archived_at is not None:
            return [Line(obj.room_id, 'war_room_activity', 'topic.archived', 'Archived topic #%s' % obj.name,
                         'topic', obj)]
        return [Line(obj.room_id, 'war_room_activity', 'topic.restored', 'Restored topic #%s' % obj.name, 'topic',
                     obj)]
    return []


def _message(session, obj, op, changed, deleting):
    if op != 'update' or 'pinned' not in changed or obj.deleted_at is not None:
        return []
    snippet = _clip(obj.thread_title or obj.content, 80)
    if obj.pinned:
        return [Line(obj.room_id, 'pin', 'pin.added', 'Pinned a message: %s' % snippet, 'message', obj)]
    return [Line(obj.room_id, 'war_room_activity', 'room.unpinned', 'Unpinned a message: %s' % snippet, 'message',
                 obj)]


HANDLERS = {
    WarRoom: _room,
    WarRoomMember: _member,
    WarRoomGuest: _guest,
    WarRoomCaseLink: _case_link,
    WarRoomTeam: _team,
    WarRoomTeamMember: _team_link,
    WarRoomTeamGuest: _team_link,
    WarRoomNote: _note,
    WarRoomNoteFolder: _folder,
    WarRoomTask: _task,
    WarRoomTimeline: _timeline,
    WarRoomTimelineEvent: _event,
    SitRep: _sitrep,
    WarRoomVulnerability: _vulnerability,
    WarRoomBoard: _board,
    WarRoomTopic: _topic,
    WarRoomMessage: _message,
}


# ------------------------------------------------------------------------------ listener

def _before_flush(session, flush_context, instances):
    if session.info.get(_OFF):
        return
    deleting = set(session.deleted)
    gone_rooms = {o.id for o in deleting if isinstance(o, WarRoom)}
    lines = []
    for op, objs in (('insert', session.new), ('update', session.dirty), ('delete', session.deleted)):
        for obj in list(objs):
            handler = HANDLERS.get(type(obj))
            if handler is None:
                continue
            if op == 'update':
                if not session.is_modified(obj, include_collections=False):
                    continue
                changed = _changed(obj)
                if not changed:
                    continue
            else:
                changed = set()
            try:
                produced = handler(session, obj, op, changed, deleting)
            except Exception:  # noqa: BLE001 - the log never blocks the change it records
                import app
                app.app.logger.exception('war-room activity: %s %s not logged', op, type(obj).__name__)
                continue
            for line in produced:
                if _id(line.room) in gone_rooms:
                    continue
                lines.append(line)
    if lines:
        actor = current_actor()
        for line in lines:
            if line.actor is None:
                line.actor = actor
        session.info.setdefault(_PENDING, []).extend(lines)


def _after_flush(session, flush_context):
    lines = session.info.pop(_PENDING, None)
    if not lines:
        return
    conn = session.connection()
    for line in lines:
        room_id = _id(line.room)
        if room_id is None:
            continue
        row = {'room_id': room_id, 'kind': line.kind, 'atype': line.activity_type, 'body': _clip(line.body, 400),
               'actor': line.actor[0], 'guest': line.actor[1], 'rtype': line.ref_type, 'ref': _id(line.ref),
               'case': line.ref_case_id}
        if line.coalesce and row['ref'] is not None:
            moved = conn.execute(sa_text(
                "UPDATE war_room_activity SET created_at = now(), body = :body WHERE id = ("
                " SELECT id FROM war_room_activity WHERE room_id = :room_id AND activity_type = :atype"
                " AND ref_type IS NOT DISTINCT FROM :rtype AND ref_id = :ref"
                " AND actor_id IS NOT DISTINCT FROM :actor AND actor_guest_id IS NOT DISTINCT FROM :guest"
                " AND created_at > now() - make_interval(mins => :mins) ORDER BY id DESC LIMIT 1) RETURNING id"),
                dict(row, mins=sv.COALESCE_MINUTES)).first()
            if moved is not None:
                continue
        conn.execute(WarRoomActivity.__table__.insert().values(
            room_id=row['room_id'], kind=row['kind'], activity_type=row['atype'], body=row['body'],
            actor_id=row['actor'], actor_guest_id=row['guest'], ref_type=row['rtype'], ref_id=row['ref'],
            ref_case_id=row['case']))


def _after_rollback(session):
    session.info.pop(_PENDING, None)


class quiet:
    """`with quiet(session):` - changes made inside write no activity lines (bulk maintenance)."""

    def __init__(self, session):
        self.session = session

    def __enter__(self):
        self.session.info[_OFF] = True
        return self

    def __exit__(self, *exc):
        self.session.info.pop(_OFF, None)
        return False


def install():
    """Attach the listener once per process (imported by app.business.war_rooms at boot)."""
    if not event.contains(Session, 'before_flush', _before_flush):
        event.listen(Session, 'before_flush', _before_flush)
        event.listen(Session, 'after_flush', _after_flush)
        event.listen(Session, 'after_soft_rollback', lambda s, t: _after_rollback(s))


install()

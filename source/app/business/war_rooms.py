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

"""War rooms slim v1 (iris-ng v2, Phase 6).

Roles: lead > responder > observer. Membership does NOT grant case access —
the room stream filters case activity per viewer by case ACL (v1 decision,
flagged for revisit). Rooms close rather than delete (v3 four-state model:
open/active/standby/closed); closed rooms reject writes, reads stay.

Chat transport is REST + short polling by DESIGN, not omission: the upstream
socket_io_event_handlers package is dead code — it is imported nowhere, and a
runtime probe of the running app shows the ONLY registered socket.io
namespace is /server-updates (updater.py). Client->server events (join/save/
change) have never worked in this tree, so there is no working precedent to
extend; a live socket layer is a deliberate later step.
"""

from datetime import datetime

from sqlalchemy import desc

import app
from app import db
from app.business.errors import BusinessProcessingError
from app.business.notifications import notify
from app.business.notifications import notify_mentions
from app.iris_engine.access_control.utils import ac_get_fast_user_cases_access
from app.models.authorization import User
from app.models.models import AiArtifact
from app.models.models import SitRep
from app.models.models import SitRepRevision
from app.models.models import UserActivity
from app.models.models import WarRoom
from app.models.models import WarRoomCaseLink
from app.models.models import WarRoomMember
from app.models.models import WarRoomMessage
from app.models.models import WarRoomPoll
from app.models.models import WarRoomPollOption
from app.models.models import WarRoomPollVote
from app.models.models import WarRoomNote
from app.models.models import WarRoomNoteFolder
from app.models.models import WarRoomTask
from app.models.models import WarRoomTeam
from app.models.models import WarRoomTeamMember
from app.models.models import WarRoomTimeline
from app.models.models import WarRoomTimelineEvent

log = app.app.logger

ROLE_RANK = {'observer': 1, 'responder': 2, 'lead': 3}

# v3 four-state model (maintainer decision). Only 'closed' is read-only;
# open/active/standby differ in meaning, not in what they permit.
ROOM_STATUSES = ('open', 'active', 'standby', 'closed')
ROOM_SEVERITIES = ('low', 'medium', 'high', 'critical')


def get_room(room_id):
    return db.session.get(WarRoom, room_id)


def user_room_role(room_id, user_id):
    """Membership role or None. Admin elevation is the REST layer's call —
    this answers only about actual membership."""
    m = WarRoomMember.query.filter_by(room_id=room_id, user_id=user_id).first()
    return m.role if m else None


def role_at_least(role, min_role):
    return ROLE_RANK.get(role, 0) >= ROLE_RANK.get(min_role, 99)


def rooms_for_user(user_id, all_rooms=False):
    """Rooms the user is a member of (all_rooms=True for server admins),
    every status included — the list page filters client-side via the v3
    chips. Returns (room, role|None) tuples, newest first."""
    if all_rooms:
        q = db.session.query(WarRoom, WarRoomMember.role).outerjoin(
            WarRoomMember, (WarRoomMember.room_id == WarRoom.id)
            & (WarRoomMember.user_id == user_id))
    else:
        q = db.session.query(WarRoom, WarRoomMember.role).join(
            WarRoomMember, (WarRoomMember.room_id == WarRoom.id)
            & (WarRoomMember.user_id == user_id))
    return q.order_by(desc(WarRoom.id)).all()


def create_room(name, description, creator_id):
    name = (name or '').strip()
    if not name:
        raise BusinessProcessingError('Room name is required')
    room = WarRoom(name=name, description=description or None,
                   created_by=creator_id)
    db.session.add(room)
    db.session.flush()
    db.session.add(WarRoomMember(room_id=room.id, user_id=creator_id,
                                 role='lead', added_by=creator_id))
    db.session.commit()
    return room


def update_room(room, name=None, description=None, summary=None,
                severity=None):
    if name is not None:
        name = name.strip()
        if not name:
            raise BusinessProcessingError('Room name cannot be empty')
        room.name = name
    if description is not None:
        room.description = description or None
    if summary is not None:
        room.summary = summary or None
    if severity is not None:
        # '' clears the severity; anything else must be in the catalog.
        if severity == '':
            room.severity = None
        elif severity in ROOM_SEVERITIES:
            room.severity = severity
        else:
            raise BusinessProcessingError('Invalid severity')
    db.session.commit()
    return room


def set_room_status(room, status):
    if status not in ROOM_STATUSES:
        raise BusinessProcessingError('Invalid status')
    room.status = status
    room.archived_at = datetime.utcnow() if status == 'closed' else None
    db.session.commit()
    return room


def delete_room(room):
    """Hard delete for an accidentally created room (lead-only at the
    endpoint). Every child table's room FK is ondelete=CASCADE — members,
    case links, teams + team members, messages, tasks, sitreps + revisions,
    polls + options + votes, timelines + events, notes + folders and the
    MISP link all go with the row, while linked CASES are untouched (the
    LINK cascades, the case does not). The bulk query DELETE bypasses ORM
    relationship handling on purpose so the database does the cascading.

    A room promoted from a correlation cluster frees the cluster by
    construction: the promoted-clusters map and the duplicate-promote guard
    only consult live rooms. Cached AI artifacts (sitrep drafts) are
    anchored WITHOUT an FK, so they are cleared explicitly rather than left
    as orphan cache rows.
    """
    AiArtifact.query.filter_by(anchor_type='war_room',
                               anchor_id=room.id).delete()
    WarRoom.query.filter_by(id=room.id).delete()
    db.session.commit()


def _assert_writable(room):
    if room.status == 'closed':
        raise BusinessProcessingError('Room is closed')


def _lead_count(room_id):
    return WarRoomMember.query.filter_by(room_id=room_id, role='lead').count()


def add_member(room, user_id, role, actor_id):
    _assert_writable(room)
    if role not in ROLE_RANK:
        raise BusinessProcessingError('Invalid role')
    target = db.session.get(User, user_id)
    if target is None or not target.active:
        raise BusinessProcessingError('Invalid user')
    existing = WarRoomMember.query.filter_by(room_id=room.id,
                                             user_id=user_id).first()
    if existing:
        raise BusinessProcessingError('User is already a member')
    member = WarRoomMember(room_id=room.id, user_id=user_id, role=role,
                           added_by=actor_id)
    db.session.add(member)
    db.session.commit()
    # Post-commit, fail-soft by notify()'s contract. Actor-drop applies, so
    # the creator's own lead row (room creation) never self-notifies.
    notify('war_room_added', [user_id],
           f'You were added to war room "{room.name}"',
           object_type='war_room', object_id=room.id,
           url=f'/war-rooms/{room.id}', actor_id=actor_id)
    return member


def set_member_role(room, user_id, role):
    _assert_writable(room)
    if role not in ROLE_RANK:
        raise BusinessProcessingError('Invalid role')
    member = WarRoomMember.query.filter_by(room_id=room.id,
                                           user_id=user_id).first()
    if member is None:
        raise BusinessProcessingError('Not a member')
    # A room must always keep at least one lead.
    if member.role == 'lead' and role != 'lead' and _lead_count(room.id) <= 1:
        raise BusinessProcessingError('Cannot demote the last lead')
    member.role = role
    db.session.commit()
    return member


def remove_member(room, user_id):
    _assert_writable(room)
    member = WarRoomMember.query.filter_by(room_id=room.id,
                                           user_id=user_id).first()
    if member is None:
        raise BusinessProcessingError('Not a member')
    if member.role == 'lead' and _lead_count(room.id) <= 1:
        raise BusinessProcessingError('Cannot remove the last lead')
    db.session.delete(member)
    db.session.commit()


def room_case_ids(room_id):
    return [r.case_id for r in
            WarRoomCaseLink.query.filter_by(room_id=room_id).all()]


def attach_case(room, case_id, actor_id):
    """Caller has already verified the ACTOR's access to the case — attaching
    exposes case identity (name) to room members via the stream."""
    _assert_writable(room)
    existing = WarRoomCaseLink.query.filter_by(room_id=room.id,
                                               case_id=case_id).first()
    if existing:
        return existing
    link = WarRoomCaseLink(room_id=room.id, case_id=case_id,
                           added_by=actor_id)
    db.session.add(link)
    db.session.commit()
    return link


def detach_case(room, case_id):
    _assert_writable(room)
    WarRoomCaseLink.query.filter_by(room_id=room.id, case_id=case_id).delete()
    db.session.commit()


def set_case_link_note(room, case_id, note):
    """The attachment note is a property of the case-in-this-room
    relationship (v3's "Primary case for this room")."""
    _assert_writable(room)
    link = WarRoomCaseLink.query.filter_by(room_id=room.id,
                                           case_id=case_id).first()
    if link is None:
        raise BusinessProcessingError('Case is not attached')
    link.note = (note or '').strip()[:500] or None
    db.session.commit()
    return link


def case_peek(room, viewer_id, case_id):
    """v3's click-to-peek modal: full case tiles + safe-rendered
    description. ACL-checked against the VIEWER — membership does not
    grant case access."""
    from app.business.cases import case_peek_payload
    link = WarRoomCaseLink.query.filter_by(room_id=room.id,
                                           case_id=int(case_id)).first()
    if link is None:
        raise BusinessProcessingError('Case is not attached')
    if int(case_id) not in room_visible_case_ids(room.id, viewer_id):
        raise BusinessProcessingError('Case is outside your access')
    # the tiles + summary come from the shared builder; the room adds only
    # what is room-specific (the per-attachment note)
    out = case_peek_payload(case_id)
    if out is None:
        raise BusinessProcessingError('Case is not attached')
    out['note'] = link.note
    return out


def member_user_ids(room_id):
    return [m.user_id for m in
            WarRoomMember.query.filter_by(room_id=room_id).all()]


# ------------------------------------------------------------------- teams

# The team name is what people type after @ — same charset as the mention
# regex so a team token scans exactly like a login token.
_TEAM_NAME_RE = None


def _valid_team_name(name):
    global _TEAM_NAME_RE
    if _TEAM_NAME_RE is None:
        import re as _re
        _TEAM_NAME_RE = _re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
    return bool(name) and bool(_TEAM_NAME_RE.match(name))


def list_teams(room):
    out = []
    for t in (WarRoomTeam.query.filter_by(room_id=room.id)
              .order_by(WarRoomTeam.name).all()):
        out.append({
            'id': t.id, 'name': t.name, 'description': t.description,
            'color': t.color,
            'members': [{'user_id': m.user_id,
                         'user_name': m.user.name if m.user else 'deleted user'}
                        for m in t.members],
        })
    return out


def create_team(room, name, user_id, description=None, color=None):
    _assert_writable(room)
    name = (name or '').strip().lstrip('@').lower()
    if not _valid_team_name(name):
        raise BusinessProcessingError(
            'Team name must be letters/digits/._- (e.g. ir-leads)')
    if WarRoomTeam.query.filter_by(room_id=room.id, name=name).first():
        raise BusinessProcessingError('A team with that name already exists')
    t = WarRoomTeam(room_id=room.id, name=name,
                    description=(description or '').strip()[:500] or None,
                    color=color if _valid_color(color) else None,
                    created_by=user_id)
    db.session.add(t)
    db.session.commit()
    return t


def _get_team(room, team_id):
    t = db.session.get(WarRoomTeam, int(team_id))
    if t is None or t.room_id != room.id:
        raise BusinessProcessingError('Invalid team')
    return t


def delete_team(room, team_id):
    _assert_writable(room)
    t = _get_team(room, team_id)
    db.session.delete(t)
    db.session.commit()


def add_team_member(room, team_id, user_id):
    """Teams group ROOM members only — being in a team grants nothing."""
    _assert_writable(room)
    t = _get_team(room, team_id)
    if user_room_role(room.id, user_id) is None:
        raise BusinessProcessingError('User is not a member of this room')
    if not WarRoomTeamMember.query.filter_by(team_id=t.id,
                                             user_id=user_id).first():
        db.session.add(WarRoomTeamMember(team_id=t.id, user_id=user_id))
        db.session.commit()
    return t


def remove_team_member(room, team_id, user_id):
    _assert_writable(room)
    t = _get_team(room, team_id)
    WarRoomTeamMember.query.filter_by(team_id=t.id, user_id=user_id).delete()
    db.session.commit()


def _notify_team_mentions(room, content, title, body, actor_id):
    """@team-name in a message notifies every member of that team (v3).
    Recipients are intersected with CURRENT room members at send time —
    someone who left the room stops receiving team pings. Fail-soft."""
    try:
        import re as _re
        teams = WarRoomTeam.query.filter_by(room_id=room.id).all()
        if not teams:
            return
        tokens = {t.lower() for t in
                  _re.findall(r'@([A-Za-z0-9][A-Za-z0-9._-]{0,63})',
                              content or '')}
        if not tokens:
            return
        members = set(member_user_ids(room.id))
        recipients = set()
        for t in teams:
            if t.name.lower() in tokens:
                recipients |= {m.user_id for m in t.members}
        recipients &= members
        if recipients:
            notify('mention', list(recipients), title, body=body,
                   object_type='war_room', object_id=room.id,
                   url=f'/war-rooms/{room.id}', actor_id=actor_id,
                   keep_actor=True)
    except Exception:
        app.app.logger.exception('team mention notify failed')


MESSAGE_KINDS = ('message', 'note', 'decision')


def add_message(room, user_id, content, topic='main', kind='message',
                parent_id=None, thread_title=None, pinned=False):
    _assert_writable(room)
    content = (content or '').strip()
    if not content:
        raise BusinessProcessingError('Empty message')
    if kind not in MESSAGE_KINDS:
        raise BusinessProcessingError('Invalid message kind')
    topic = (topic or 'main').strip()[:64] or 'main'
    root_id = None
    if parent_id:
        parent = db.session.get(WarRoomMessage, int(parent_id))
        # A reply is only valid inside its own room, and always anchors to
        # the ROOT of the thread (one-level threading, replies to a reply
        # re-anchor to the same root).
        if parent is None or parent.room_id != room.id:
            raise BusinessProcessingError('Invalid reply target')
        root_id = parent.parent_id or parent.id
    msg = WarRoomMessage(room_id=room.id, user_id=user_id, content=content,
                         topic=topic, kind=kind, parent_id=root_id,
                         thread_title=(thread_title or '').strip() or None,
                         pinned=bool(pinned))
    db.session.add(msg)
    db.session.commit()
    # Post-commit, both fail-soft by contract. war_room_message is
    # QUIET-BY-DEFAULT (per-event code default in notifications.py) so
    # emitting on every message is safe — only opted-in members get rows.
    # Mentions ride the normal 'mention' event, restricted to members.
    members = member_user_ids(room.id)
    author = db.session.get(User, user_id)
    author_name = author.name if author else 'someone'
    notify('war_room_message', members,
           f'{author_name} in war room "{room.name}"',
           body=content[:280], object_type='war_room', object_id=room.id,
           url=f'/war-rooms/{room.id}', actor_id=user_id)
    notify_mentions(content,
                    f'{author_name} mentioned you in war room "{room.name}"',
                    body=content[:280], object_type='war_room',
                    object_id=room.id, url=f'/war-rooms/{room.id}',
                    actor_id=user_id, allowed_user_ids=members)
    _notify_team_mentions(
        room, content,
        f'{author_name} mentioned your team in war room "{room.name}"',
        content[:280], user_id)
    return msg


def set_message_pinned(room, message_id, pinned):
    _assert_writable(room)
    msg = db.session.get(WarRoomMessage, int(message_id))
    if msg is None or msg.room_id != room.id:
        raise BusinessProcessingError('Invalid message')
    msg.pinned = bool(pinned)
    db.session.commit()
    return msg


# --------------------------------------------------------------- room tasks

def list_room_tasks(room):
    return (WarRoomTask.query.filter_by(room_id=room.id)
            .order_by(WarRoomTask.status.desc(), desc(WarRoomTask.id)).all())


ROOM_TASK_STATUSES = ('no_status', 'todo', 'in_progress', 'on_hold',
                      'done', 'cancelled')


def _check_assignee(assignee_id):
    if assignee_id is None:
        return None
    target = db.session.get(User, int(assignee_id))
    if target is None or not target.active:
        raise BusinessProcessingError('Invalid assignee')
    return int(assignee_id)


def add_room_task(room, title, actor_id, assignee_id=None, description=None,
                  status='no_status', due_date=None, tags=None,
                  parent_task_id=None):
    _assert_writable(room)
    title = (title or '').strip()
    if not title:
        raise BusinessProcessingError('Task title is required')
    status = status or 'no_status'
    if status not in ROOM_TASK_STATUSES:
        raise BusinessProcessingError('Invalid status')
    assignee_id = _check_assignee(assignee_id)
    if parent_task_id:
        parent = db.session.get(WarRoomTask, int(parent_task_id))
        # One-level subtasks: parent must be a top-level task in this room.
        if (parent is None or parent.room_id != room.id
                or parent.parent_task_id is not None):
            raise BusinessProcessingError('Invalid parent task')
        parent_task_id = parent.id
    task = WarRoomTask(room_id=room.id, title=title,
                       description=(description or '').strip() or None,
                       assignee_id=assignee_id, status=status,
                       due_date=due_date,
                       tags=(tags or '').strip() or None,
                       parent_task_id=parent_task_id, created_by=actor_id)
    if status == 'done':
        task.done_at = datetime.utcnow()
        task.done_by = actor_id
    db.session.add(task)
    db.session.commit()
    if assignee_id and int(assignee_id) != int(actor_id):
        # Room tasks ride the existing task_assigned event (post-commit,
        # fail-soft by notify()'s contract).
        notify('task_assigned', [assignee_id],
               f'Task "{title}" assigned to you in war room "{room.name}"',
               object_type='war_room', object_id=room.id,
               url=f'/war-rooms/{room.id}', actor_id=actor_id)
    return task


def set_room_task(room, task_id, actor_id, status=None, assignee_id=None,
                  title=None, description=None, due_date=None, tags=None,
                  clear_due=False):
    _assert_writable(room)
    task = db.session.get(WarRoomTask, int(task_id))
    if task is None or task.room_id != room.id:
        raise BusinessProcessingError('Invalid task')
    if title is not None:
        t = title.strip()
        if not t:
            raise BusinessProcessingError('Task title cannot be empty')
        task.title = t
    if description is not None:
        task.description = description.strip() or None
    if status is not None:
        if status not in ROOM_TASK_STATUSES:
            raise BusinessProcessingError('Invalid status')
        was_done = task.status == 'done'
        task.status = status
        if status == 'done' and not was_done:
            task.done_at = datetime.utcnow()
            task.done_by = actor_id
        elif status != 'done':
            task.done_at = None
            task.done_by = None
    if assignee_id is not None:
        new_assignee = _check_assignee(assignee_id) if assignee_id else None
        changed = new_assignee != task.assignee_id
        task.assignee_id = new_assignee
        if (changed and new_assignee
                and int(new_assignee) != int(actor_id)):
            notify('task_assigned', [new_assignee],
                   f'Task "{task.title}" assigned to you in war room '
                   f'"{room.name}"',
                   object_type='war_room', object_id=room.id,
                   url=f'/war-rooms/{room.id}', actor_id=actor_id)
    if due_date is not None:
        task.due_date = due_date
    elif clear_due:
        task.due_date = None
    if tags is not None:
        task.tags = tags.strip() or None
    db.session.commit()
    return task


def delete_room_task(room, task_id):
    _assert_writable(room)
    task = db.session.get(WarRoomTask, int(task_id))
    if task is None or task.room_id != room.id:
        raise BusinessProcessingError('Invalid task')
    db.session.delete(task)   # CASCADE removes subtasks
    db.session.commit()


# -------------------------------------------------------------------- polls

def poll_is_closed(poll):
    if poll.closed:
        return True
    return poll.closes_at is not None and poll.closes_at < datetime.utcnow()


def create_poll(room, user_id, question, options, multiple=False,
                anonymous=False, closes_at=None):
    _assert_writable(room)
    question = (question or '').strip()
    if not question:
        raise BusinessProcessingError('Poll question is required')
    texts = [str(o).strip() for o in (options or []) if str(o).strip()]
    if len(texts) < 2 or len(texts) > 20:
        raise BusinessProcessingError('A poll needs 2 to 20 options')
    poll = WarRoomPoll(room_id=room.id, question=question,
                       multiple=bool(multiple), anonymous=bool(anonymous),
                       closes_at=closes_at, created_by=user_id)
    db.session.add(poll)
    db.session.flush()
    for pos, txt in enumerate(texts):
        db.session.add(WarRoomPollOption(poll_id=poll.id, text=txt,
                                         position=pos))
    db.session.commit()
    return poll


def _get_room_poll(room, poll_id):
    poll = db.session.get(WarRoomPoll, int(poll_id))
    if poll is None or poll.room_id != room.id:
        raise BusinessProcessingError('Invalid poll')
    return poll


def vote_poll(room, poll_id, user_id, option_id):
    """Toggle a vote. Everyone with room access may vote (v3 wording), so
    the endpoint gates at observer. Single-choice polls replace the voter's
    previous vote."""
    _assert_writable(room)
    poll = _get_room_poll(room, poll_id)
    if poll_is_closed(poll):
        raise BusinessProcessingError('Poll is closed')
    opt = db.session.get(WarRoomPollOption, int(option_id))
    if opt is None or opt.poll_id != poll.id:
        raise BusinessProcessingError('Invalid option')
    existing = WarRoomPollVote.query.filter_by(
        option_id=opt.id, user_id=user_id).first()
    if existing is not None:
        db.session.delete(existing)
    else:
        if not poll.multiple:
            WarRoomPollVote.query.filter_by(
                poll_id=poll.id, user_id=user_id).delete()
        db.session.add(WarRoomPollVote(poll_id=poll.id, option_id=opt.id,
                                       user_id=user_id))
    db.session.commit()
    return poll


def close_poll(room, poll_id, user_id, is_lead):
    poll = _get_room_poll(room, poll_id)
    if poll.created_by != user_id and not is_lead:
        raise BusinessProcessingError(
            'Only the poll creator or a lead can close a poll')
    poll.closed = True
    db.session.commit()
    return poll


def serialize_poll(poll, viewer_id):
    votes = WarRoomPollVote.query.filter_by(poll_id=poll.id).all()
    by_opt = {}
    for v in votes:
        by_opt.setdefault(v.option_id, []).append(v)
    voters_total = len({v.user_id for v in votes})
    return {
        'id': poll.id, 'question': poll.question,
        'multiple': poll.multiple, 'anonymous': poll.anonymous,
        'closed': poll_is_closed(poll),
        'closes_at': poll.closes_at,
        'created_by': poll.created_by,
        'created_by_name': poll.creator.name if poll.creator else None,
        'total_voters': voters_total,
        'options': [{
            'id': o.id, 'text': o.text,
            'count': len(by_opt.get(o.id, [])),
            'voted': any(v.user_id == viewer_id
                         for v in by_opt.get(o.id, [])),
            # Voter names are withheld on anonymous polls BY THE SERVER —
            # never rely on the client to hide them.
            'voters': ([] if poll.anonymous else
                       [v.user.name if v.user else 'deleted user'
                        for v in by_opt.get(o.id, [])]),
        } for o in poll.options],
    }


# ------------------------------------------------------------------- topics

def room_topics(room):
    """Distinct topics, 'main' always first."""
    rows = (db.session.query(WarRoomMessage.topic)
            .filter_by(room_id=room.id).distinct().all())
    topics = {r[0] for r in rows}
    topics.add('main')
    return ['main'] + sorted(t for t in topics if t != 'main')


def list_messages(room, before_id=None, limit=50):
    """Keyset pagination on the (room_id, id) index, newest first."""
    limit = min(int(limit or 50), 100)
    q = WarRoomMessage.query.filter_by(room_id=room.id)
    if before_id:
        q = q.filter(WarRoomMessage.id < int(before_id))
    return q.order_by(desc(WarRoomMessage.id)).limit(limit).all()


# --------------------------------------------------- promote from discovery

class ClusterAlreadyPromoted(BusinessProcessingError):
    """The cluster already has an active room — carry it for the 409."""
    def __init__(self, room):
        super().__init__('Cluster already promoted')
        self.room = room


def promote_cluster_to_room(cluster_id, user_id, min_shared=2,
                            start_date=None, end_date=None):
    """Promote a COMPUTED correlation cluster into a war room. Rooms are
    NEVER auto-created (user rule) — this runs only on an explicit click.

    The report is recomputed server-side under the ACTOR's ACL (never trust
    a client-supplied case list), the analyst-edited cluster narrative
    (display_content) seeds the room summary AND the first SitRep draft,
    and the campaign tag + cluster hash ride along as provenance. The
    correlation ENGINE is reused, not reimplemented."""
    from app.business.ioc_correlation import build_correlation_report

    report = build_correlation_report(user_id, min_shared=min_shared,
                                      start_date=start_date,
                                      end_date=end_date)
    cluster = next((c for c in report.get('clusters', [])
                    if c.get('cluster_id') == cluster_id), None)
    if cluster is None:
        raise BusinessProcessingError(
            'Cluster not found in the current report — it may have changed '
            'with the filters')

    # Any non-closed room occupies the cluster; closing it frees the
    # cluster for re-promotion.
    existing = WarRoom.query.filter(
        WarRoom.source_cluster_id == cluster_id,
        WarRoom.status != 'closed').first()
    if existing is not None:
        raise ClusterAlreadyPromoted(existing)

    # Narrative seed is best-effort: promote must work without one.
    name = f'Cluster {cluster_id}'
    narrative_prose = None
    try:
        import json as _json
        from app.iris_engine.ai.cluster_narrative import get_latest_cluster_narrative
        art = get_latest_cluster_narrative(min(cluster['case_ids']), cluster_id)
        if art is not None:
            obj = _json.loads(art.display_content)
            if obj.get('suggested_name'):
                name = str(obj['suggested_name'])[:120]
            narrative_prose = (obj.get('narrative') or '').strip() or None
    except Exception:
        log.exception('promote: narrative seed failed for cluster %s '
                      '(promoting without it)', cluster_id)

    room = WarRoom(
        name=name,
        description=f'Promoted from correlation cluster {cluster_id}',
        summary=narrative_prose,
        source_cluster_id=cluster_id,
        campaign_tag=cluster.get('suggested_campaign_tag'),
        created_by=user_id)
    db.session.add(room)
    db.session.flush()
    db.session.add(WarRoomMember(room_id=room.id, user_id=user_id,
                                 role='lead', added_by=user_id))
    for cid in cluster['case_ids']:
        db.session.add(WarRoomCaseLink(room_id=room.id, case_id=cid,
                                       added_by=user_id))
    if narrative_prose:
        db.session.add(SitRep(
            room_id=room.id, title=f'Initial situation — {name}'[:255],
            content=narrative_prose, created_by=user_id))
    db.session.commit()
    return room


# ------------------------------------------------------------------ sitreps

def list_sitreps(room):
    return (SitRep.query.filter_by(room_id=room.id)
            .order_by(desc(SitRep.id)).all())


def get_sitrep(room, sitrep_id):
    s = db.session.get(SitRep, sitrep_id)
    # A sitrep is only reachable through its own room.
    if s is None or s.room_id != room.id:
        return None
    return s


def create_sitrep(room, title, content, user_id):
    _assert_writable(room)
    title = (title or '').strip()
    if not title:
        raise BusinessProcessingError('SitRep title is required')
    s = SitRep(room_id=room.id, title=title, content=content or None,
               created_by=user_id)
    db.session.add(s)
    db.session.commit()
    return s


def update_sitrep(room, sitrep, title=None, content=None, user_id=None):
    """Snapshot the CURRENT state as a revision, then apply the edit
    (NoteRevisions pattern). Published sitreps stay editable — the revision
    trail is what makes that safe."""
    _assert_writable(room)
    if title is not None and not title.strip():
        raise BusinessProcessingError('SitRep title cannot be empty')
    last = (SitRepRevision.query.filter_by(sitrep_id=sitrep.id)
            .order_by(desc(SitRepRevision.revision_number)).first())
    db.session.add(SitRepRevision(
        sitrep_id=sitrep.id,
        revision_number=(last.revision_number + 1) if last else 1,
        title=sitrep.title, content=sitrep.content, user_id=user_id))
    if title is not None:
        sitrep.title = title.strip()
    if content is not None:
        sitrep.content = content or None
    sitrep.updated_at = datetime.utcnow()
    db.session.commit()
    return sitrep


def publish_sitrep(room, sitrep, user_id):
    _assert_writable(room)
    if sitrep.status == 'published':
        raise BusinessProcessingError('SitRep is already published')
    sitrep.status = 'published'
    sitrep.published_at = datetime.utcnow()
    sitrep.published_by = user_id
    db.session.commit()
    # Post-commit, fail-soft by notify()'s contract.
    notify('sitrep_published', member_user_ids(room.id),
           f'SitRep "{sitrep.title}" published in war room "{room.name}"',
           body=(sitrep.content or '')[:280],
           object_type='war_room', object_id=room.id,
           url=f'/war-rooms/{room.id}', actor_id=user_id)
    return sitrep


def delete_sitrep(room, sitrep):
    """Lead-only at the REST layer. v3 parity (maintainer decision
    2026-08-26): published SitReps are deletable too — supersedes the
    earlier published-undeletable rule."""
    _assert_writable(room)
    db.session.delete(sitrep)
    db.session.commit()


def sitrep_revisions(sitrep):
    return (SitRepRevision.query.filter_by(sitrep_id=sitrep.id)
            .order_by(desc(SitRepRevision.revision_number)).all())


def room_stream(room, viewer_id, limit=50):
    """The unified stream. Kinds (matching the v3 stream lanes):

      message       chat (incl. /note + /decision via `kind` sub-field,
                    replies via parent_id, named threads via thread_title)
      task_event    room-task created/completed (derived from WarRoomTask)
      sitrep        SitRep published (derived from SitRep rows)
      system        member added (derived from WarRoomMember rows)
      case_link     case attached (derived from WarRoomCaseLink rows —
                    v3's "Case attached / detached" lane)
      case_activity activity on linked cases, FILTERED to cases the VIEWER
                    can access (membership does not grant case access)

    Everything except messages and case activity is DERIVED from stored
    rows — no event log table. Newest-first."""
    limit = min(int(limit or 50), 300)
    items = []
    msgs = list_messages(room, limit=limit)
    root_snippets = {m.id: (m.thread_title or (m.content or '')[:60])
                     for m in msgs}
    for m in msgs:
        items.append({
            'kind': 'message', 'id': m.id, 'user_id': m.user_id,
            'user_name': m.user.name if m.user else 'deleted user',
            'content': m.content, 'created_at': m.created_at,
            'topic': m.topic, 'msg_kind': m.kind,
            'parent_id': m.parent_id,
            'parent_snippet': root_snippets.get(m.parent_id),
            'thread_title': m.thread_title, 'pinned': m.pinned,
        })
    linked = room_case_ids(room.id)
    acl = set(ac_get_fast_user_cases_access(viewer_id) or [])
    visible = [c for c in linked if c in acl]
    if visible:
        acts = (UserActivity.query.filter(
                    UserActivity.case_id.in_(visible),
                    UserActivity.display_in_ui.is_(True))
                .order_by(desc(UserActivity.activity_date))
                .limit(limit).all())
        for a in acts:
            items.append({
                'kind': 'case_activity', 'id': a.id, 'case_id': a.case_id,
                'content': a.activity_desc, 'created_at': a.activity_date,
            })

    def _uname(uid):
        u = db.session.get(User, uid) if uid else None
        return u.name if u else 'someone'

    for link in WarRoomCaseLink.query.filter_by(room_id=room.id).all():
        c = link.case
        items.append({
            'kind': 'case_link', 'case_id': link.case_id,
            'content': (f'{_uname(link.added_by)} attached case '
                        f'"{c.name}"' if c else
                        f'{_uname(link.added_by)} attached case '
                        f'#{link.case_id}'),
            'created_at': link.added_at,
        })
    for m in WarRoomMember.query.filter_by(room_id=room.id).all():
        items.append({
            'kind': 'system',
            'content': (f'{_uname(m.added_by)} added '
                        f'{m.user.name if m.user else "a user"} '
                        f'as {m.role}'),
            'created_at': m.added_at,
        })
    for s in SitRep.query.filter(SitRep.room_id == room.id,
                                 SitRep.status == 'published').all():
        items.append({
            'kind': 'sitrep',
            'content': (f'{s.publisher.name if s.publisher else "someone"} '
                        f'published SitRep "{s.title}"'),
            'created_at': s.published_at,
        })
    for p in WarRoomPoll.query.filter_by(room_id=room.id).all():
        items.append({
            'kind': 'poll', 'content': p.question,
            'created_at': p.created_at,
            'poll': serialize_poll(p, viewer_id),
        })
    for t in WarRoomTask.query.filter_by(room_id=room.id).all():
        assignee = f' → {t.assignee.name}' if t.assignee else ''
        items.append({
            'kind': 'task_event',
            'content': (f'{_uname(t.created_by)} created task '
                        f'"{t.title}"{assignee}'),
            'created_at': t.created_at,
        })
        if t.status == 'done' and t.done_at:
            items.append({
                'kind': 'task_event',
                'content': f'{_uname(t.done_by)} completed task "{t.title}"',
                'created_at': t.done_at,
            })
    items.sort(key=lambda i: (i['created_at'] or datetime.min), reverse=True)
    return items[:limit]


# --------------------------------------------- read-only tab aggregations

def room_visible_case_ids(room_id, viewer_id):
    linked = room_case_ids(room_id)
    acl = set(ac_get_fast_user_cases_access(viewer_id) or [])
    return [c for c in linked if c in acl]


def room_timeline(room, viewer_id, limit=500):
    """The Timelines tab payload: read-only CASE events (linked cases the
    VIEWER can access — the case-page timelines are only READ, invariant)
    merged with the room's OWN timelines (read-write coordination
    annotations, maintainer decision). Enriched for the v3 card layout:
    category, colour, tags, parent (tree view), asset/IOC counts (bulk
    queries — never per-row)."""
    from sqlalchemy import func
    from app.models.cases import CasesEvent
    from app.models.models import CaseEventCategory
    from app.models.models import CaseEventsAssets
    from app.models.models import CaseEventsIoc
    from app.models.models import EventCategory
    visible = room_visible_case_ids(room.id, viewer_id)
    events = []
    if visible:
        rows = (CasesEvent.query
                .filter(CasesEvent.case_id.in_(visible))
                .order_by(desc(CasesEvent.event_date))
                .limit(min(int(limit or 500), 1000)).all())
        ids = [e.event_id for e in rows]
        asset_counts = dict(
            db.session.query(CaseEventsAssets.event_id, func.count())
            .filter(CaseEventsAssets.event_id.in_(ids))
            .group_by(CaseEventsAssets.event_id).all()) if ids else {}
        ioc_counts = dict(
            db.session.query(CaseEventsIoc.event_id, func.count())
            .filter(CaseEventsIoc.event_id.in_(ids))
            .group_by(CaseEventsIoc.event_id).all()) if ids else {}
        cats = dict(
            db.session.query(CaseEventCategory.event_id, EventCategory.name)
            .join(EventCategory,
                  CaseEventCategory.category_id == EventCategory.id)
            .filter(CaseEventCategory.event_id.in_(ids)).all()) if ids else {}
        for e in rows:
            events.append({
                'source': 'case', 'event_id': e.event_id,
                'case_id': e.case_id,
                'event_date': e.event_date, 'event_title': e.event_title,
                'event_content': (e.event_content or '')[:400],
                'category': cats.get(e.event_id),
                'color': e.event_color,
                'tags': e.event_tags or '',
                'parent_event_id': e.parent_event_id,
                'asset_count': asset_counts.get(e.event_id, 0),
                'ioc_count': ioc_counts.get(e.event_id, 0),
            })

    timelines = []
    for tl in (WarRoomTimeline.query.filter_by(room_id=room.id)
               .order_by(WarRoomTimeline.id).all()):
        timelines.append({'id': tl.id, 'name': tl.name, 'color': tl.color,
                          'event_count': len(tl.events)})
        for e in tl.events:
            events.append({
                'source': 'room', 'event_id': e.id,
                'timeline_id': tl.id, 'timeline_name': tl.name,
                'event_date': e.event_date, 'event_title': e.title,
                'event_content': (e.content or '')[:400],
                # Events without their own colour inherit the timeline's
                # (v3 behaviour — the swatch on the New-timeline modal).
                'category': e.category, 'color': e.color or tl.color,
                'tags': e.tags or '', 'parent_event_id': None,
                'asset_count': 0, 'ioc_count': 0,
            })
    events.sort(key=lambda x: x['event_date'] or datetime.min, reverse=True)
    return {'timelines': timelines, 'events': events,
            'visible_cases': len(visible)}


# ------------------------------------------------------- room timelines

_COLOR_RE = None


def _valid_color(color):
    """Colours land in a style attribute — validate the shape server-side,
    never trust free text into CSS."""
    global _COLOR_RE
    if _COLOR_RE is None:
        import re as _re
        _COLOR_RE = _re.compile(r'^#[0-9a-fA-F]{3,8}$')
    return bool(color) and bool(_COLOR_RE.match(color))


def create_room_timeline(room, name, user_id, color=None):
    _assert_writable(room)
    name = (name or '').strip()
    if not name:
        raise BusinessProcessingError('Timeline name is required')
    tl = WarRoomTimeline(room_id=room.id, name=name[:120],
                         color=color if _valid_color(color) else None,
                         created_by=user_id)
    db.session.add(tl)
    db.session.commit()
    return tl


def _get_room_timeline(room, timeline_id):
    tl = db.session.get(WarRoomTimeline, int(timeline_id))
    if tl is None or tl.room_id != room.id:
        raise BusinessProcessingError('Invalid timeline')
    return tl


def update_room_timeline(room, timeline_id, **fields):
    _assert_writable(room)
    tl = _get_room_timeline(room, timeline_id)
    if 'name' in fields and fields['name'] is not None:
        n = (fields['name'] or '').strip()
        if not n:
            raise BusinessProcessingError('Timeline name cannot be empty')
        tl.name = n[:120]
    if 'color' in fields:
        tl.color = fields['color'] if _valid_color(fields['color']) else None
    db.session.commit()
    return tl


def delete_room_timeline(room, timeline_id):
    _assert_writable(room)
    tl = _get_room_timeline(room, timeline_id)
    db.session.delete(tl)
    db.session.commit()


def add_timeline_event(room, timeline_id, user_id, title, event_date,
                       content=None, category=None, color=None, tags=None):
    _assert_writable(room)
    tl = _get_room_timeline(room, timeline_id)
    title = (title or '').strip()
    if not title:
        raise BusinessProcessingError('Event title is required')
    if event_date is None:
        raise BusinessProcessingError('Event date is required')
    ev = WarRoomTimelineEvent(
        timeline_id=tl.id, event_date=event_date, title=title,
        content=content or None, category=(category or '').strip()[:64] or None,
        color=color if _valid_color(color) else None,
        tags=(tags or '').strip() or None, created_by=user_id)
    db.session.add(ev)
    db.session.commit()
    return ev


def _get_timeline_event(room, timeline_id, event_id):
    tl = _get_room_timeline(room, timeline_id)
    ev = db.session.get(WarRoomTimelineEvent, int(event_id))
    if ev is None or ev.timeline_id != tl.id:
        raise BusinessProcessingError('Invalid event')
    return ev


def update_timeline_event(room, timeline_id, event_id, **fields):
    _assert_writable(room)
    ev = _get_timeline_event(room, timeline_id, event_id)
    if 'title' in fields and fields['title'] is not None:
        t = fields['title'].strip()
        if not t:
            raise BusinessProcessingError('Event title cannot be empty')
        ev.title = t
    if 'event_date' in fields and fields['event_date'] is not None:
        ev.event_date = fields['event_date']
    if 'content' in fields:
        ev.content = fields['content'] or None
    if 'category' in fields:
        ev.category = (fields['category'] or '').strip()[:64] or None
    if 'color' in fields:
        ev.color = fields['color'] if _valid_color(fields['color']) else None
    if 'tags' in fields:
        ev.tags = (fields['tags'] or '').strip() or None
    ev.updated_at = datetime.utcnow()
    db.session.commit()
    return ev


def delete_timeline_event(room, timeline_id, event_id):
    _assert_writable(room)
    ev = _get_timeline_event(room, timeline_id, event_id)
    db.session.delete(ev)
    db.session.commit()


def room_tasks(room, viewer_id, limit=200):
    """Aggregated case tasks across linked, viewer-accessible cases."""
    from app.models.models import CaseTasks
    from app.models.models import TaskStatus
    visible = room_visible_case_ids(room.id, viewer_id)
    if not visible:
        return []
    rows = (db.session.query(CaseTasks, TaskStatus.status_name)
            .outerjoin(TaskStatus, CaseTasks.task_status_id == TaskStatus.id)
            .filter(CaseTasks.task_case_id.in_(visible))
            .order_by(desc(CaseTasks.task_last_update))
            .limit(min(int(limit or 200), 500)).all())
    return [{
        'task_id': t.id, 'case_id': t.task_case_id,
        'task_title': t.task_title, 'status_name': status_name,
        'task_last_update': t.task_last_update,
    } for t, status_name in rows]


def room_notes(room, viewer_id, limit=200):
    """The Notes tab payload: read-write ROOM notes + folders, plus
    read-only note titles across linked, viewer-accessible cases (the
    case-page notes are only READ by the room — invariant)."""
    from app.models.models import Notes
    folders = [{'id': f.id, 'name': f.name}
               for f in (WarRoomNoteFolder.query
                         .filter_by(room_id=room.id)
                         .order_by(WarRoomNoteFolder.name).all())]
    own = [{
        'id': n.id, 'title': n.title, 'folder_id': n.folder_id,
        'updated_at': n.updated_at or n.created_at,
        'updated_by_name': (n.editor.name if n.editor
                            else (n.creator.name if n.creator else None)),
    } for n in (WarRoomNote.query.filter_by(room_id=room.id)
                .order_by(WarRoomNote.title).all())]
    visible = room_visible_case_ids(room.id, viewer_id)
    case_rows = []
    if visible:
        rows = (Notes.query
                .filter(Notes.note_case_id.in_(visible))
                .order_by(desc(Notes.note_lastupdate))
                .limit(min(int(limit or 200), 500)).all())
        case_rows = [{
            'note_id': n.note_id, 'case_id': n.note_case_id,
            'note_title': n.note_title,
            'note_lastupdate': n.note_lastupdate,
        } for n in rows]
    return {'folders': folders, 'room_notes': own, 'case_notes': case_rows}


def get_case_note_for_room(room, viewer_id, case_id, note_id):
    """One linked-case note, read-only, ACL-checked against the VIEWER.
    Content is returned server-rendered (render_markdown_safe) only —
    the room never edits case notes."""
    from app.iris_engine.safe_markdown import render_markdown_safe
    from app.models.models import Notes
    visible = room_visible_case_ids(room.id, viewer_id)
    if int(case_id) not in visible:
        raise BusinessProcessingError('Invalid note')
    n = db.session.get(Notes, int(note_id))
    if n is None or n.note_case_id != int(case_id):
        raise BusinessProcessingError('Invalid note')
    return {
        'note_id': n.note_id, 'case_id': n.note_case_id,
        'title': n.note_title,
        'content_html': render_markdown_safe(n.note_content or ''),
        'updated_at': n.note_lastupdate,
    }


def create_note_folder(room, name, user_id):
    _assert_writable(room)
    name = (name or '').strip()
    if not name:
        raise BusinessProcessingError('Folder name is required')
    f = WarRoomNoteFolder(room_id=room.id, name=name[:120],
                          created_by=user_id)
    db.session.add(f)
    db.session.commit()
    return f


def _get_note_folder(room, folder_id):
    f = db.session.get(WarRoomNoteFolder, int(folder_id))
    if f is None or f.room_id != room.id:
        raise BusinessProcessingError('Invalid folder')
    return f


def rename_note_folder(room, folder_id, name):
    _assert_writable(room)
    f = _get_note_folder(room, folder_id)
    name = (name or '').strip()
    if not name:
        raise BusinessProcessingError('Folder name cannot be empty')
    f.name = name[:120]
    db.session.commit()
    return f


def delete_note_folder(room, folder_id):
    """Deleting a folder MOVES its notes to the root — never deletes
    content (FK is SET NULL; made explicit here so ORM state agrees)."""
    _assert_writable(room)
    f = _get_note_folder(room, folder_id)
    WarRoomNote.query.filter_by(room_id=room.id, folder_id=f.id).update(
        {'folder_id': None})
    db.session.delete(f)
    db.session.commit()


def create_room_note(room, user_id, title=None, folder_id=None):
    _assert_writable(room)
    title = (title or '').strip() or 'New note'
    if folder_id:
        _get_note_folder(room, folder_id)
    n = WarRoomNote(room_id=room.id, title=title[:255],
                    folder_id=folder_id or None, content='',
                    created_by=user_id)
    db.session.add(n)
    db.session.commit()
    return n


def _get_room_note(room, note_id):
    n = db.session.get(WarRoomNote, int(note_id))
    if n is None or n.room_id != room.id:
        raise BusinessProcessingError('Invalid note')
    return n


def serialize_room_note(n):
    from app.iris_engine.safe_markdown import render_markdown_safe
    return {
        'id': n.id, 'title': n.title, 'folder_id': n.folder_id,
        'content': n.content or '',
        'content_html': render_markdown_safe(n.content or ''),
        'updated_at': n.updated_at or n.created_at,
        'updated_by_name': (n.editor.name if n.editor
                            else (n.creator.name if n.creator else None)),
    }


def update_room_note(room, note_id, user_id, **fields):
    _assert_writable(room)
    n = _get_room_note(room, note_id)
    if 'title' in fields and fields['title'] is not None:
        t = (fields['title'] or '').strip()
        if not t:
            raise BusinessProcessingError('Note title cannot be empty')
        n.title = t[:255]
    if 'content' in fields:
        n.content = fields['content'] or ''
    if 'folder_id' in fields:
        fid = fields['folder_id']
        if fid:
            _get_note_folder(room, fid)
        n.folder_id = fid or None
    n.updated_at = datetime.utcnow()
    n.updated_by = user_id
    db.session.commit()
    return n


def delete_room_note(room, note_id):
    _assert_writable(room)
    n = _get_room_note(room, note_id)
    db.session.delete(n)
    db.session.commit()

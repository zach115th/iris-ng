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

"""The war-room Stream: activity log, Activity settings, topics, reactions, threads, files (iris-ng, 2026-11-08)

Creates `war_room_activity` (the room's activity log), `war_room_stream_pref` (each user's Activity
settings), `war_room_topic` (chat topics and their archived state), `war_room_message_reaction`,
`war_room_thread_follow` and `war_room_file` (files attached in the chat), and adds
`war_room_message.edited_at` / `deleted_at` / `deleted_by` / `deleted_by_guest_id`. Additive only.

Data: every room gets its # Main topic and a row for each topic its messages already use, and - once,
while the log is empty - the activity log is filled from the rows that record past changes (room
created, members added, guests invited / joined / revoked, cases attached, tasks created / assigned /
completed, notes, folders, timelines, timeline events, teams, SitReps drafted / published), with their
own timestamps and authors, so a room keeps its history in the Activity panel.

Guarded: db.create_all() runs before alembic at boot and already creates the tables, constraints and
indexes from the ORM; the new COLUMNS exist only through this migration.

Revision ID: e1d7b4a9c3f6
Revises: c5e9a2f7d4b8
Create Date: 2026-11-08
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.alembic.alembic_utils import _has_table
from app.alembic.alembic_utils import _table_has_column
from app.alembic.alembic_utils import index_exists
from app.models import war_room_stream_vocab as sv

revision = 'e1d7b4a9c3f6'
down_revision = 'c5e9a2f7d4b8'
branch_labels = None
depends_on = None


def _fk(name, table, ondelete='SET NULL'):
    return sa.Column(name, sa.BigInteger(), sa.ForeignKey('%s.id' % table, ondelete=ondelete), nullable=True)


def _activity():
    op.create_table(
        'war_room_activity',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('room_id', sa.BigInteger(), sa.ForeignKey('war_room.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('activity_type', sa.String(48), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        _fk('actor_id', 'user'),
        _fk('actor_guest_id', 'war_room_guest'),
        sa.Column('ref_type', sa.String(32), nullable=True),
        sa.Column('ref_id', sa.BigInteger(), nullable=True),
        sa.Column('ref_case_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sv.sql_in('kind', sv.ACTIVITY_KINDS), name='ck_war_room_activity_kind'),
    )


def _pref():
    op.create_table(
        'war_room_stream_pref',
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('prefs', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )


def _topic():
    op.create_table(
        'war_room_topic',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('room_id', sa.BigInteger(), sa.ForeignKey('war_room.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(64), nullable=False),
        _fk('created_by', 'user'),
        _fk('created_by_guest_id', 'war_room_guest'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        _fk('archived_by', 'user'),
        _fk('archived_by_guest_id', 'war_room_guest'),
        sa.UniqueConstraint('room_id', 'name', name='uq_war_room_topic_room_name'),
    )


def _actor_cols():
    return [_fk('user_id', 'user', 'CASCADE'), _fk('guest_id', 'war_room_guest', 'CASCADE')]


def _reaction():
    op.create_table(
        'war_room_message_reaction',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('message_id', sa.BigInteger(), sa.ForeignKey('war_room_message.id', ondelete='CASCADE'),
                  nullable=False),
        *_actor_cols(),
        sa.Column('emoji', sa.String(32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('message_id', 'user_id', 'emoji', name='uq_war_room_message_reaction_user'),
        sa.CheckConstraint('(user_id IS NULL) <> (guest_id IS NULL)', name='ck_war_room_message_reaction_actor'),
    )


def _follow():
    op.create_table(
        'war_room_thread_follow',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('message_id', sa.BigInteger(), sa.ForeignKey('war_room_message.id', ondelete='CASCADE'),
                  nullable=False),
        *_actor_cols(),
        sa.Column('following', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('message_id', 'user_id', name='uq_war_room_thread_follow_user'),
        sa.CheckConstraint('(user_id IS NULL) <> (guest_id IS NULL)', name='ck_war_room_thread_follow_actor'),
    )


def _file():
    op.create_table(
        'war_room_file',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('room_id', sa.BigInteger(), sa.ForeignKey('war_room.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_uuid', postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('filename', sa.Text(), nullable=False),
        sa.Column('mime_type', sa.String(128), nullable=False),
        sa.Column('size', sa.BigInteger(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        _fk('uploaded_by', 'user'),
        _fk('uploaded_by_guest_id', 'war_room_guest'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )


TABLES = (('war_room_activity', _activity), ('war_room_stream_pref', _pref), ('war_room_topic', _topic),
          ('war_room_message_reaction', _reaction), ('war_room_thread_follow', _follow),
          ('war_room_file', _file))

# name: (table, columns, unique, partial WHERE or None)
INDEXES = {
    'ix_war_room_activity_room_created': ('war_room_activity', ['room_id', 'created_at'], False, None),
    'ix_war_room_message_reaction_message_id': ('war_room_message_reaction', ['message_id'], False, None),
    'uq_war_room_message_reaction_guest': ('war_room_message_reaction', ['message_id', 'guest_id', 'emoji'],
                                           True, 'guest_id IS NOT NULL'),
    'ix_war_room_thread_follow_message_id': ('war_room_thread_follow', ['message_id'], False, None),
    'uq_war_room_thread_follow_guest': ('war_room_thread_follow', ['message_id', 'guest_id'], True,
                                        'guest_id IS NOT NULL'),
    'ix_war_room_file_room_id': ('war_room_file', ['room_id'], False, None),
}

MESSAGE_COLUMNS = (
    ('edited_at', lambda: sa.Column('edited_at', sa.DateTime(), nullable=True)),
    ('deleted_at', lambda: sa.Column('deleted_at', sa.DateTime(), nullable=True)),
    ('deleted_by', lambda: _fk('deleted_by', 'user')),
    ('deleted_by_guest_id', lambda: _fk('deleted_by_guest_id', 'war_room_guest')),
)

_GUEST_LABEL = ("CASE WHEN g.organisation IS NOT NULL AND g.organisation <> '' "
                "THEN g.display_name || ' (' || g.organisation || ')' ELSE g.display_name END")

# One INSERT ... SELECT per kind of past change: (kind, activity_type, ref_type, SELECT of
# room_id, body, actor_id, actor_guest_id, ref_id, ref_case_id, created_at).
BACKFILL = (
    ('system', 'system.room_created', 'room',
     "SELECT r.id, 'Created the war room', r.created_by, NULL, r.id, NULL, r.created_at FROM war_room r"),
    ('war_room_activity', 'member.added', 'member',
     "SELECT m.room_id, 'Added ' || COALESCE(u.name, 'a user') || ' as ' || m.role, m.added_by, NULL, m.user_id, "
     "NULL, m.added_at FROM war_room_member m LEFT JOIN \"user\" u ON u.id = m.user_id"),
    ('war_room_activity', 'member.guest_invited', 'guest',
     "SELECT g.room_id, 'Invited guest ' || " + _GUEST_LABEL + ", g.invited_by, NULL, g.id, NULL, g.created_at "
     "FROM war_room_guest g"),
    ('system', 'system.guest_joined', 'guest',
     "SELECT g.room_id, 'Joined through the guest portal', NULL, g.id, g.id, NULL, g.first_seen_at "
     "FROM war_room_guest g WHERE g.first_seen_at IS NOT NULL"),
    ('war_room_activity', 'member.guest_revoked', 'guest',
     "SELECT g.room_id, 'Revoked guest ' || " + _GUEST_LABEL + ", NULL, NULL, g.id, NULL, g.revoked_at "
     "FROM war_room_guest g WHERE g.revoked_at IS NOT NULL"),
    ('case_attached', 'case.attached', 'case',
     "SELECT l.room_id, 'Attached case #' || l.case_id, l.added_by, NULL, l.case_id, l.case_id, l.added_at "
     "FROM war_room_case_link l"),
    ('war_room_activity', 'task.created', 'task',
     "SELECT t.room_id, 'Created task: ' || t.title, t.created_by, t.created_by_guest_id, t.id, NULL, t.created_at "
     "FROM war_room_task t"),
    ('task_assigned', 'task.assigned', 'task',
     "SELECT t.room_id, 'Assigned task ' || t.title || ' to ' || COALESCE(u.name, " + _GUEST_LABEL + ", 'someone'), "
     "t.created_by, t.created_by_guest_id, t.id, NULL, t.created_at FROM war_room_task t "
     "LEFT JOIN \"user\" u ON u.id = t.assignee_id LEFT JOIN war_room_guest g ON g.id = t.assignee_guest_id "
     "WHERE t.assignee_id IS NOT NULL OR t.assignee_guest_id IS NOT NULL"),
    ('task_completed', 'task.completed', 'task',
     "SELECT t.room_id, 'Completed task: ' || t.title, t.done_by, t.done_by_guest_id, t.id, NULL, t.done_at "
     "FROM war_room_task t WHERE t.status = 'done' AND t.done_at IS NOT NULL"),
    ('note', 'note.created', 'note',
     "SELECT n.room_id, 'Created note: ' || n.title, n.created_by, n.created_by_guest_id, n.id, NULL, n.created_at "
     "FROM war_room_note n"),
    ('war_room_activity', 'folder.created', 'folder',
     "SELECT f.room_id, 'Created note folder: ' || f.name, f.created_by, NULL, f.id, NULL, f.created_at "
     "FROM war_room_note_folder f"),
    ('war_room_activity', 'timeline.created', 'timeline',
     "SELECT t.room_id, 'Created timeline: ' || t.name, t.created_by, t.created_by_guest_id, t.id, NULL, "
     "t.created_at FROM war_room_timeline t"),
    ('war_room_activity', 'event.created', 'event',
     "SELECT t.room_id, 'Added timeline event: ' || e.title, e.created_by, e.created_by_guest_id, e.id, NULL, "
     "e.created_at FROM war_room_timeline_event e JOIN war_room_timeline t ON t.id = e.timeline_id"),
    ('war_room_activity', 'team.created', 'team',
     "SELECT t.room_id, 'Created team @' || t.name, t.created_by, t.created_by_guest_id, t.id, NULL, t.created_at "
     "FROM war_room_team t"),
    ('war_room_activity', 'sitrep.created', 'sitrep',
     "SELECT s.room_id, 'Started SitRep draft: ' || s.title, s.created_by, s.created_by_guest_id, s.id, NULL, "
     "s.created_at FROM sitrep s"),
    ('sitrep_published', 'sitrep.published', 'sitrep',
     "SELECT s.room_id, 'Published SitRep: ' || s.title, s.published_by, NULL, s.id, NULL, s.published_at "
     "FROM sitrep s WHERE s.status = 'published' AND s.published_at IS NOT NULL"),
)


def _backfill_activity(bind):
    for kind, activity_type, ref_type, select in BACKFILL:
        bind.execute(sa.text(
            "INSERT INTO war_room_activity (room_id, kind, activity_type, ref_type, body, actor_id, actor_guest_id, "
            "ref_id, ref_case_id, created_at) "
            "SELECT s.room_id, :kind, :atype, :rtype, s.body, s.actor_id::bigint, s.actor_guest_id::bigint, "
            "s.ref_id::bigint, s.ref_case_id::integer, s.created_at FROM (" + select + ") AS s(room_id, body, actor_id, actor_guest_id, ref_id, ref_case_id, "
            "created_at) WHERE s.created_at IS NOT NULL"),
            {'kind': kind, 'atype': activity_type, 'rtype': ref_type})


def _backfill_topics(bind):
    bind.execute(sa.text(
        "INSERT INTO war_room_topic (room_id, name, created_by, created_at) "
        "SELECT r.id, 'main', r.created_by, r.created_at FROM war_room r "
        "ON CONFLICT (room_id, name) DO NOTHING"))
    bind.execute(sa.text(
        "INSERT INTO war_room_topic (room_id, name, created_at) "
        "SELECT m.room_id, m.topic, MIN(m.created_at) FROM war_room_message m "
        "WHERE m.topic IS NOT NULL AND m.topic <> '' GROUP BY m.room_id, m.topic "
        "ON CONFLICT (room_id, name) DO NOTHING"))


def upgrade():
    if not _has_table('war_room') or not _has_table('war_room_message'):
        return
    for table, create in TABLES:
        if not _has_table(table):
            create()
    for name, (table, columns, unique, where) in INDEXES.items():
        if not index_exists(table, name):
            kw = {'postgresql_where': sa.text(where)} if where else {}
            op.create_index(name, table, columns, unique=unique, **kw)
    for column, make in MESSAGE_COLUMNS:
        if not _table_has_column('war_room_message', column):
            op.add_column('war_room_message', make())
    bind = op.get_bind()
    _backfill_topics(bind)
    if bind.execute(sa.text('SELECT COUNT(*) FROM war_room_activity')).scalar() == 0:
        _backfill_activity(bind)


def downgrade():
    pass

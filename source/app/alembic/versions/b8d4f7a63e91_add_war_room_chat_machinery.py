"""War-room chat machinery (iris-ng v2, Phase 6 stream completion)

Activates the placeholder features as real ones: topics, full reply-to
threads, notes/decisions/pins as message kinds, and ROOM-LEVEL tasks
(maintainer decision: /task creates a war-room task, not a case task).

Column-adds are guarded (create_all never adds columns to an existing
table); the new table is guarded like every other.

Revision ID: b8d4f7a63e91
Revises: a6e8b3f91c27
Create Date: 2026-08-26

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table
from app.alembic.alembic_utils import _table_has_column

revision = 'b8d4f7a63e91'
down_revision = 'a6e8b3f91c27'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('war_room_message', 'topic'):
        op.add_column('war_room_message',
                      sa.Column('topic', sa.String(64), nullable=False,
                                server_default=sa.text("'main'")))
    if not _table_has_column('war_room_message', 'kind'):
        op.add_column('war_room_message',
                      sa.Column('kind', sa.String(16), nullable=False,
                                server_default=sa.text("'message'")))
        op.execute("ALTER TABLE war_room_message ADD CONSTRAINT "
                   "ck_war_room_message_kind CHECK "
                   "(kind IN ('message','note','decision'))")
    if not _table_has_column('war_room_message', 'parent_id'):
        op.add_column('war_room_message',
                      sa.Column('parent_id', sa.BigInteger(), nullable=True))
        op.create_foreign_key('fk_war_room_message_parent',
                              'war_room_message', 'war_room_message',
                              ['parent_id'], ['id'], ondelete='CASCADE')
    if not _table_has_column('war_room_message', 'thread_title'):
        op.add_column('war_room_message',
                      sa.Column('thread_title', sa.Text(), nullable=True))
    if not _table_has_column('war_room_message', 'pinned'):
        op.add_column('war_room_message',
                      sa.Column('pinned', sa.Boolean(), nullable=False,
                                server_default=sa.text('false')))

    if not _has_table('war_room_task'):
        op.create_table(
            'war_room_task',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('room_id', sa.BigInteger(), nullable=False, index=True),
            sa.Column('title', sa.Text(), nullable=False),
            sa.Column('assignee_id', sa.BigInteger(), nullable=True),
            sa.Column('status', sa.String(16), nullable=False,
                      server_default=sa.text("'open'")),
            sa.Column('created_by', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(),
                      server_default=sa.text('now()'), nullable=False),
            sa.Column('done_at', sa.DateTime(), nullable=True),
            sa.Column('done_by', sa.BigInteger(), nullable=True),
            sa.ForeignKeyConstraint(['room_id'], ['war_room.id'],
                                    ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['assignee_id'], ['user.id'],
                                    ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['created_by'], ['user.id'],
                                    ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['done_by'], ['user.id'],
                                    ondelete='SET NULL'),
            sa.CheckConstraint("status IN ('open','done')",
                               name='ck_war_room_task_status'),
        )


def downgrade():
    pass

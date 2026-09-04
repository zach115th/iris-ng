"""Extend war-room tasks to the v3 shape (iris-ng v2, Phase 6 Tasks tab)

v3 room tasks carry description, status (beyond open/done), due date, tags
and subtasks. Status set: no_status / todo / in_progress / done / cancelled.
Existing 'open' rows become 'todo' — data BEFORE the CHECK swap (rows must
satisfy the new constraint at ADD time).

Revision ID: e2c8f5b91a37
Revises: d7f3b9c58a24
Create Date: 2026-08-26

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

revision = 'e2c8f5b91a37'
down_revision = 'd7f3b9c58a24'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('war_room_task', 'description'):
        op.add_column('war_room_task',
                      sa.Column('description', sa.Text(), nullable=True))
    if not _table_has_column('war_room_task', 'due_date'):
        op.add_column('war_room_task',
                      sa.Column('due_date', sa.DateTime(), nullable=True))
    if not _table_has_column('war_room_task', 'tags'):
        op.add_column('war_room_task',
                      sa.Column('tags', sa.Text(), nullable=True))
    if not _table_has_column('war_room_task', 'parent_task_id'):
        op.add_column('war_room_task',
                      sa.Column('parent_task_id', sa.BigInteger(),
                                nullable=True))
        op.create_foreign_key('fk_war_room_task_parent', 'war_room_task',
                              'war_room_task', ['parent_task_id'], ['id'],
                              ondelete='CASCADE')
    op.execute("UPDATE war_room_task SET status='todo' WHERE status='open'")
    op.execute("ALTER TABLE war_room_task DROP CONSTRAINT IF EXISTS "
               "ck_war_room_task_status")
    op.execute("ALTER TABLE war_room_task ADD CONSTRAINT "
               "ck_war_room_task_status CHECK (status IN "
               "('no_status','todo','in_progress','done','cancelled'))")
    op.execute("ALTER TABLE war_room_task ALTER COLUMN status "
               "SET DEFAULT 'no_status'")


def downgrade():
    pass

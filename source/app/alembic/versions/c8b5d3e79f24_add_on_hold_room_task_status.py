"""Add v3's ON HOLD status to war-room tasks (iris-ng v2, Phase 6 board)

v3's task board has six columns; on_hold was missing from the status set.
Pure CHECK widening — no data migration needed (no existing rows can carry
the new value).

Revision ID: c8b5d3e79f24
Revises: a3d8f6c92b41
Create Date: 2026-08-26

"""
from alembic import op

revision = 'c8b5d3e79f24'
down_revision = 'a3d8f6c92b41'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE war_room_task DROP CONSTRAINT IF EXISTS "
               "ck_war_room_task_status")
    op.execute("ALTER TABLE war_room_task ADD CONSTRAINT "
               "ck_war_room_task_status CHECK (status IN "
               "('no_status','todo','in_progress','on_hold','done',"
               "'cancelled'))")


def downgrade():
    pass

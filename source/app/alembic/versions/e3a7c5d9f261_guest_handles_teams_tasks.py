"""Guest handles, guests in teams, room tasks assigned to guests (iris-ng, 2026-09-30)

Guests can be @-mentioned (a per-room handle), grouped into @-mention teams
(own link table beside the user link) and assigned room tasks. Every op is
guarded so a re-run is a no-op; the new table also comes from create_all.

Revision ID: e3a7c5d9f261
Revises: d2f6a8c4e957
Create Date: 2026-09-30

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table
from app.alembic.alembic_utils import _table_has_column
from app.alembic.alembic_utils import index_exists

revision = 'e3a7c5d9f261'
down_revision = 'd2f6a8c4e957'
branch_labels = None
depends_on = None


def _constraint_exists(name):
    row = op.get_bind().execute(sa.text("SELECT 1 FROM pg_constraint WHERE conname = :n"),
                                {"n": name}).first()
    return row is not None


def upgrade():
    if not _table_has_column('war_room_guest', 'handle'):
        op.add_column('war_room_guest', sa.Column('handle', sa.String(64), nullable=True))
    if not index_exists('war_room_guest', 'uq_war_room_guest_room_handle'):
        op.create_unique_constraint('uq_war_room_guest_room_handle', 'war_room_guest',
                                    ['room_id', 'handle'])

    if not _has_table('war_room_team_guest'):
        op.create_table(
            'war_room_team_guest',
            sa.Column('team_id', sa.BigInteger(),
                      sa.ForeignKey('war_room_team.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('guest_id', sa.BigInteger(),
                      sa.ForeignKey('war_room_guest.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('added_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        )

    if not _table_has_column('war_room_task', 'assignee_guest_id'):
        op.add_column('war_room_task', sa.Column(
            'assignee_guest_id', sa.BigInteger(),
            sa.ForeignKey('war_room_guest.id', ondelete='SET NULL'), nullable=True))
    if not _constraint_exists('ck_war_room_task_one_assignee'):
        op.create_check_constraint('ck_war_room_task_one_assignee', 'war_room_task',
                                   'assignee_id IS NULL OR assignee_guest_id IS NULL')


def downgrade():
    pass

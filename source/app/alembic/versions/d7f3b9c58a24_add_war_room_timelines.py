"""Room-level timelines (iris-ng v2, Phase 6 Timelines tab)

Maintainer decision: the Timelines tab toggles read-only linked CASE
timelines on/off AND supports read-write ROOM-level timelines. Room
timeline events are coordination annotations owned by the room — the
case-page timelines remain the forensic source of truth and are never
written from here (invariant).

Revision ID: d7f3b9c58a24
Revises: c9e5a8b47d12
Create Date: 2026-08-26

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

revision = 'd7f3b9c58a24'
down_revision = 'c9e5a8b47d12'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('war_room_timeline'):
        op.create_table(
            'war_room_timeline',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('room_id', sa.BigInteger(), nullable=False, index=True),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('created_by', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(),
                      server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['room_id'], ['war_room.id'],
                                    ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['created_by'], ['user.id'],
                                    ondelete='SET NULL'),
        )
    if not _has_table('war_room_timeline_event'):
        op.create_table(
            'war_room_timeline_event',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('timeline_id', sa.BigInteger(), nullable=False,
                      index=True),
            sa.Column('event_date', sa.DateTime(), nullable=False),
            sa.Column('title', sa.Text(), nullable=False),
            sa.Column('content', sa.Text(), nullable=True),
            sa.Column('category', sa.String(64), nullable=True),
            sa.Column('color', sa.String(16), nullable=True),
            sa.Column('tags', sa.Text(), nullable=True),
            sa.Column('created_by', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(),
                      server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['timeline_id'], ['war_room_timeline.id'],
                                    ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['created_by'], ['user.id'],
                                    ondelete='SET NULL'),
        )


def downgrade():
    pass

"""War-room polls (iris-ng v2, Phase 6 stream completion)

v3's composer poll builder: question + 2-20 options, optional multiple
selections, anonymous voting, auto-close time. Votes are one row per
(option, user); single-choice polls enforce one vote per poll in the
business layer.

Revision ID: c9e5a8b47d12
Revises: b8d4f7a63e91
Create Date: 2026-08-26

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

revision = 'c9e5a8b47d12'
down_revision = 'b8d4f7a63e91'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('war_room_poll'):
        op.create_table(
            'war_room_poll',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('room_id', sa.BigInteger(), nullable=False, index=True),
            sa.Column('question', sa.Text(), nullable=False),
            sa.Column('multiple', sa.Boolean(), nullable=False,
                      server_default=sa.text('false')),
            sa.Column('anonymous', sa.Boolean(), nullable=False,
                      server_default=sa.text('false')),
            sa.Column('closes_at', sa.DateTime(), nullable=True),
            sa.Column('closed', sa.Boolean(), nullable=False,
                      server_default=sa.text('false')),
            sa.Column('created_by', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(),
                      server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['room_id'], ['war_room.id'],
                                    ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['created_by'], ['user.id'],
                                    ondelete='SET NULL'),
        )
    if not _has_table('war_room_poll_option'):
        op.create_table(
            'war_room_poll_option',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('poll_id', sa.BigInteger(), nullable=False, index=True),
            sa.Column('text', sa.Text(), nullable=False),
            sa.Column('position', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(['poll_id'], ['war_room_poll.id'],
                                    ondelete='CASCADE'),
        )
    if not _has_table('war_room_poll_vote'):
        op.create_table(
            'war_room_poll_vote',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('poll_id', sa.BigInteger(), nullable=False, index=True),
            sa.Column('option_id', sa.BigInteger(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('created_at', sa.DateTime(),
                      server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['poll_id'], ['war_room_poll.id'],
                                    ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['option_id'], ['war_room_poll_option.id'],
                                    ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'],
                                    ondelete='CASCADE'),
            sa.UniqueConstraint('option_id', 'user_id',
                                name='uq_war_room_poll_vote_option_user'),
        )


def downgrade():
    pass

"""War-room teams (iris-ng v2, Phase 6 Teams tab)

v3: per-room groups whose name is what people type after @ — mentioning
a team in chat notifies every member. Teams group ROOM members only;
membership in a team never grants anything (the room ACL is what admits).

Revision ID: f6c9e5a84b72
Revises: e5b8d4f97a63
Create Date: 2026-08-26

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

revision = 'f6c9e5a84b72'
down_revision = 'e5b8d4f97a63'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('war_room_team'):
        op.create_table(
            'war_room_team',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('room_id', sa.BigInteger(), nullable=False, index=True),
            sa.Column('name', sa.String(64), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('color', sa.String(16), nullable=True),
            sa.Column('created_by', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(),
                      server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['room_id'], ['war_room.id'],
                                    ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['created_by'], ['user.id'],
                                    ondelete='SET NULL'),
            sa.UniqueConstraint('room_id', 'name',
                                name='uq_war_room_team_name'),
        )
    if not _has_table('war_room_team_member'):
        op.create_table(
            'war_room_team_member',
            sa.Column('team_id', sa.BigInteger(), primary_key=True),
            sa.Column('user_id', sa.BigInteger(), primary_key=True),
            sa.Column('added_at', sa.DateTime(),
                      server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['team_id'], ['war_room_team.id'],
                                    ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'],
                                    ondelete='CASCADE'),
        )


def downgrade():
    pass

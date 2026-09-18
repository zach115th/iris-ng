"""Add war_room_team_template (iris-ng v2, Settings > War Room Teams, #115)

Org-wide default @-mention teams seeded, empty, into every NEW war room in
sort order. Guarded create: db.create_all() runs before alembic on every
boot and will usually have created the table already — this migration is
the chain record so a database upgraded without a create_all pass is also
correct, and to advance the version.

Revision ID: d6a2f8c47b19
Revises: f8b3c62d94a7
Create Date: 2026-09-18

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

revision = 'd6a2f8c47b19'
down_revision = 'f8b3c62d94a7'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('war_room_team_template'):
        op.create_table(
            'war_room_team_template',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(64), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('color', sa.String(16), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'),
                      nullable=True),
            sa.UniqueConstraint('name', name='uq_war_room_team_template_name'),
        )


def downgrade():
    if _has_table('war_room_team_template'):
        op.drop_table('war_room_team_template')

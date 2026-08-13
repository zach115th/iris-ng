"""add skill + user_skill tables

iris-next: catalog of cyber-security / DFIR skills (`skill`) + per-user enabled
skills (`user_skill`, presence = enabled). First use is the user-edit modal's
Skills tab; groundwork for team-building + skill-based case assignment.

Guarded with `_has_table` because db.create_all() runs from the ORM models
BEFORE alembic on fresh boot and pre-creates the tables — an unguarded
create_table would then fail. CHECK/UNIQUE constraints live on the ORM
`__table_args__` (fork rule) so they land via db.create_all too.

Revision ID: e1b6c4d83a92
Revises: d9a3b7e25f41
Create Date: 2026-06-11 20:45:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

# revision identifiers, used by Alembic.
revision = 'e1b6c4d83a92'
down_revision = 'd9a3b7e25f41'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('skill'):
        op.create_table(
            'skill',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('skill_slug', sa.String(length=80), nullable=False),
            sa.Column('skill_name', sa.String(length=120), nullable=False),
            sa.Column('skill_category', sa.String(length=80), nullable=False),
            sa.Column('skill_description', sa.Text(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.UniqueConstraint('skill_slug', name='uq_skill_slug'),
        )

    if not _has_table('user_skill'):
        op.create_table(
            'user_skill',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('skill_id', sa.BigInteger(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['skill_id'], ['skill.id'], ondelete='CASCADE'),
            sa.UniqueConstraint('user_id', 'skill_id', name='uq_user_skill'),
        )


def downgrade():
    op.drop_table('user_skill')
    op.drop_table('skill')

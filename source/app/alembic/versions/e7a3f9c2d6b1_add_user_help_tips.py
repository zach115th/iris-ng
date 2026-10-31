"""Per-user switch for the (i) help icons (iris-ng, 2026-10-30)

Adds `user.has_help_tips` (nullable boolean, NULL = icons shown; Profile ->
"Show help icons" stores False to hide them). Additive only; existing users
read as NULL and keep seeing the icons.

Revision ID: e7a3f9c2d6b1
Revises: c4d9a2e7f1b3
Create Date: 2026-10-30
"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

revision = 'e7a3f9c2d6b1'
down_revision = 'c4d9a2e7f1b3'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('user', 'has_help_tips'):
        op.add_column('user', sa.Column('has_help_tips', sa.Boolean(), nullable=True))


def downgrade():
    pass

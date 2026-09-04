"""Add announcement_banner (iris-ng v2, Settings > Banners)

Top-of-app announcement banners published to every authenticated user
while active (v3 parity). Guarded create: db.create_all() runs before
alembic on every boot and will usually have created the table already —
this migration exists so the schema is also correct on databases that
upgrade without a create_all pass, and to advance the version.

Revision ID: c3e8f5a92d47
Revises: b4e7a2c95d18
Create Date: 2026-08-31

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

revision = 'c3e8f5a92d47'
down_revision = 'b4e7a2c95d18'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('announcement_banner'):
        op.create_table(
            'announcement_banner',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('level', sa.Text(), nullable=False, server_default='info'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
            sa.CheckConstraint("level IN ('info', 'warning', 'danger')",
                               name='ck_announcement_banner_level'),
        )


def downgrade():
    pass

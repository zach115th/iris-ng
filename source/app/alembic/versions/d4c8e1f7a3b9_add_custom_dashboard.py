"""Custom dashboards (iris-ng, 2026-11-09)

Creates `custom_dashboard`: a user's dashboard of widgets (name, description, owner, shared flag and the JSONB
definition - sections of widgets, a filter bar, a default range; models.custom_dashboard_vocab). The built-in
Statistics dashboard is code, never a row. Additive only, no data to move.

Guarded: db.create_all() runs before alembic at boot and already creates the table from the ORM.

Revision ID: d4c8e1f7a3b9
Revises: b2d7f4a9c1e6
Create Date: 2026-11-09
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.alembic.alembic_utils import _has_table

revision = 'd4c8e1f7a3b9'
down_revision = 'b2d7f4a9c1e6'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('custom_dashboard'):
        op.create_table(
            'custom_dashboard',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('dashboard_uuid', postgresql.UUID(as_uuid=True), nullable=False, unique=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('owner_id', sa.BigInteger(), sa.ForeignKey('user.id'), nullable=False, index=True),
            sa.Column('is_shared', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('definition', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        )


def downgrade():
    pass

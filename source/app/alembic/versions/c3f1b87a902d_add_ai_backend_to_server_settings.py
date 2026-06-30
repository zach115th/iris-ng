"""add ai backend columns to server settings

Revision ID: c3f1b87a902d
Revises: b2e0d6c8a4f1
Create Date: 2026-04-29 03:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

# revision identifiers, used by Alembic.
revision = 'c3f1b87a902d'
down_revision = 'b2e0d6c8a4f1'
branch_labels = None
depends_on = None


def upgrade():
    # iris-ng runs `db.create_all()` BEFORE alembic on first boot, so on a
    # fresh install the columns this migration adds may already exist (the
    # ORM models declare them). Guard each op.add_column the same way
    # _has_table guards op.create_table.
    if not _table_has_column('server_settings', 'ai_backend_enabled'):
        op.add_column(
            'server_settings',
            sa.Column('ai_backend_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false'))
        )
    if not _table_has_column('server_settings', 'ai_backend_url'):
        op.add_column('server_settings', sa.Column('ai_backend_url', sa.Text(), nullable=True))
    if not _table_has_column('server_settings', 'ai_backend_api_key'):
        op.add_column('server_settings', sa.Column('ai_backend_api_key', sa.Text(), nullable=True))
    if not _table_has_column('server_settings', 'ai_backend_model'):
        op.add_column('server_settings', sa.Column('ai_backend_model', sa.Text(), nullable=True))
    if not _table_has_column('server_settings', 'ai_backend_confidence_threshold'):
        op.add_column('server_settings', sa.Column('ai_backend_confidence_threshold', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('server_settings', 'ai_backend_confidence_threshold')
    op.drop_column('server_settings', 'ai_backend_model')
    op.drop_column('server_settings', 'ai_backend_api_key')
    op.drop_column('server_settings', 'ai_backend_url')
    op.drop_column('server_settings', 'ai_backend_enabled')

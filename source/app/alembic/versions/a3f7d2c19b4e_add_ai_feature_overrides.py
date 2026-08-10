"""add ai_feature_overrides to server settings

Stores per-feature AI backend slot overrides as a JSONB dict so admins can
route individual AI surfaces (e.g. case_summary) to a different backend slot
than the global default without creating separate URL/key/model columns per
feature.

Schema: {"feature_key": "primary"|"alt"}
Missing key or null value = use the global ai_backend_active_slot default.

Revision ID: a3f7d2c19b4e
Revises: e1b6c4d83a92
Create Date: 2026-06-26 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from app.alembic.alembic_utils import _table_has_column

revision = 'a3f7d2c19b4e'
down_revision = 'e1b6c4d83a92'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('server_settings', 'ai_feature_overrides'):
        op.add_column(
            'server_settings',
            sa.Column('ai_feature_overrides', JSONB, nullable=True)
        )


def downgrade():
    op.drop_column('server_settings', 'ai_feature_overrides')

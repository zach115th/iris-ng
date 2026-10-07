"""AI backend slots name their transport provider + cache a Bedrock model catalog (iris-ng, 2026-10-07)

`server_settings.ai_backend_provider` / `ai_backend_alt_provider`
('openai' | 'bedrock', nullable). NULL reads as 'openai' -- the
chat-completions client every existing row was using -- so no backfill is
needed. 'bedrock' routes the slot through the AWS Bedrock Converse adapter
(iris_engine/ai/bedrock_client.py).

`ai_backend_model_catalog` / `ai_backend_alt_model_catalog` (JSONB, nullable)
hold the slot's last inference-profile listing ([{id, name, type, model}])
so the Settings page can offer the profiles by their friendly names; the
chosen entry's id is what `ai_backend_model` stores. Guarded so a re-run is a
no-op.

Revision ID: a7c2d9e4f1b6
Revises: f4b8d2e6a913
Create Date: 2026-10-07
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from app.alembic.alembic_utils import _table_has_column

revision = 'a7c2d9e4f1b6'
down_revision = 'f4b8d2e6a913'
branch_labels = None
depends_on = None


def upgrade():
    for column in ('ai_backend_provider', 'ai_backend_alt_provider'):
        if not _table_has_column('server_settings', column):
            op.add_column('server_settings', sa.Column(column, sa.String(32), nullable=True))
    for column in ('ai_backend_model_catalog', 'ai_backend_alt_model_catalog'):
        if not _table_has_column('server_settings', column):
            op.add_column('server_settings', sa.Column(column, JSONB(), nullable=True))


def downgrade():
    pass

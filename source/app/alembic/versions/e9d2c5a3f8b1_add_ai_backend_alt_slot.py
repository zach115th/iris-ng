"""add ai backend alternate slot to server settings

Adds a second AI backend configuration slot so admins can keep two backends
defined (e.g. LM Studio + a hosted OpenAI-compatible endpoint) and switch the active one from the
admin UI without retyping the URL/key/model fields each time.

Revision ID: e9d2c5a3f8b1
Revises: b9e1f4a72c83
Create Date: 2026-05-09 17:10:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e9d2c5a3f8b1'
down_revision = 'b9e1f4a72c83'
branch_labels = None
depends_on = None


def upgrade():
    # Slot-1 (primary) gets a free-text label so admins can name it
    # ("LM Studio", "OpenAI", etc.). Slot-2 (alt) mirrors the primary
    # column shape plus its own label.
    op.add_column('server_settings', sa.Column('ai_backend_label', sa.Text(), nullable=True))
    op.add_column('server_settings', sa.Column('ai_backend_alt_url', sa.Text(), nullable=True))
    op.add_column('server_settings', sa.Column('ai_backend_alt_api_key', sa.Text(), nullable=True))
    op.add_column('server_settings', sa.Column('ai_backend_alt_model', sa.Text(), nullable=True))
    op.add_column('server_settings', sa.Column('ai_backend_alt_label', sa.Text(), nullable=True))
    # Active-slot pointer. 'primary' or 'alt'. NOT NULL with a server
    # default so existing rows stay on their current (primary-slot) config
    # without needing a backfill pass.
    op.add_column(
        'server_settings',
        sa.Column('ai_backend_active_slot', sa.String(16), nullable=False, server_default=sa.text("'primary'"))
    )


def downgrade():
    op.drop_column('server_settings', 'ai_backend_active_slot')
    op.drop_column('server_settings', 'ai_backend_alt_label')
    op.drop_column('server_settings', 'ai_backend_alt_model')
    op.drop_column('server_settings', 'ai_backend_alt_api_key')
    op.drop_column('server_settings', 'ai_backend_alt_url')
    op.drop_column('server_settings', 'ai_backend_label')

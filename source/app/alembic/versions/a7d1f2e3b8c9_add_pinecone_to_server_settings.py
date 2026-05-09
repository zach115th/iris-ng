"""add pinecone vector-db columns to server settings

Revision ID: a7d1f2e3b8c9
Revises: f6c83a91d201
Create Date: 2026-05-05 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a7d1f2e3b8c9'
down_revision = 'f6c83a91d201'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'server_settings',
        sa.Column('pinecone_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false'))
    )
    op.add_column('server_settings', sa.Column('pinecone_api_key', sa.Text(), nullable=True))
    op.add_column('server_settings', sa.Column('pinecone_embed_model', sa.Text(), nullable=True))
    op.add_column('server_settings', sa.Column('pinecone_sigma_host', sa.Text(), nullable=True))
    op.add_column('server_settings', sa.Column('pinecone_attack_host', sa.Text(), nullable=True))
    op.add_column('server_settings', sa.Column('pinecone_atomic_host', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('server_settings', 'pinecone_atomic_host')
    op.drop_column('server_settings', 'pinecone_attack_host')
    op.drop_column('server_settings', 'pinecone_sigma_host')
    op.drop_column('server_settings', 'pinecone_embed_model')
    op.drop_column('server_settings', 'pinecone_api_key')
    op.drop_column('server_settings', 'pinecone_enabled')

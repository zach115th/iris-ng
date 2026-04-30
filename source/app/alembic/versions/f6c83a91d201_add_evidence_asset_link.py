"""add evidence_asset_link table

Many-to-many link between case evidence (`case_received_file`) and case
assets (`case_assets`), so analysts can record which evidence files
contain or pertain to which assets — symmetric to the existing
`Related IOC` relationship on the asset modal.

Revision ID: f6c83a91d201
Revises: e5b239c0d128
Create Date: 2026-04-29 22:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

# revision identifiers, used by Alembic.
revision = 'f6c83a91d201'
down_revision = 'e5b239c0d128'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('evidence_asset_link'):
        op.create_table(
            'evidence_asset_link',
            sa.Column('id', sa.BigInteger(), nullable=False),
            sa.Column('asset_id', sa.Integer(), nullable=False),
            sa.Column('evidence_id', sa.BigInteger(), nullable=False),
            sa.ForeignKeyConstraint(['asset_id'], ['case_assets.asset_id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['evidence_id'], ['case_received_file.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('asset_id', 'evidence_id', name='uq_evidence_asset_link_pair'),
        )
        op.create_index('ix_evidence_asset_link_asset', 'evidence_asset_link', ['asset_id'])
        op.create_index('ix_evidence_asset_link_evidence', 'evidence_asset_link', ['evidence_id'])


def downgrade():
    op.drop_index('ix_evidence_asset_link_evidence', table_name='evidence_asset_link')
    op.drop_index('ix_evidence_asset_link_asset', table_name='evidence_asset_link')
    op.drop_table('evidence_asset_link')

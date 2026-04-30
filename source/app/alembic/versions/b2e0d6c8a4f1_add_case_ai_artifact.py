"""add case ai artifact table

Revision ID: b2e0d6c8a4f1
Revises: a1d9f5d4c2e8
Create Date: 2026-04-28 16:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

# revision identifiers, used by Alembic.
revision = 'b2e0d6c8a4f1'
down_revision = 'a1d9f5d4c2e8'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('case_ai_artifact'):
        op.create_table(
            'case_ai_artifact',
            sa.Column('id', sa.BigInteger(), nullable=False),
            sa.Column('case_id', sa.BigInteger(), nullable=False),
            sa.Column('kind', sa.String(64), nullable=False),
            sa.Column('prompt_id', sa.String(128), nullable=False),
            sa.Column('model', sa.String(128), nullable=False),
            sa.Column('input_hash', sa.String(64), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('confidence', sa.Float(), nullable=True),
            sa.Column('generated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(['case_id'], ['cases.case_id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            'ix_case_ai_artifact_case_id',
            'case_ai_artifact',
            ['case_id']
        )
        op.create_index(
            'ix_case_ai_artifact_input_hash',
            'case_ai_artifact',
            ['input_hash']
        )
        op.create_index(
            'ix_case_ai_artifact_case_kind',
            'case_ai_artifact',
            ['case_id', 'kind']
        )


def downgrade():
    op.drop_index('ix_case_ai_artifact_case_kind', table_name='case_ai_artifact')
    op.drop_index('ix_case_ai_artifact_input_hash', table_name='case_ai_artifact')
    op.drop_index('ix_case_ai_artifact_case_id', table_name='case_ai_artifact')
    op.drop_table('case_ai_artifact')

"""Add analyst manual-override columns to case_ai_artifact

Lets an analyst correct a generated AI artifact (currently the executive case
summary) without losing the original model output. `content` keeps the AI text
verbatim; `edited_content` holds the analyst's version and takes display
precedence while it is non-NULL.

Revision ID: d3b8f5a1c674
Revises: c2e1f4d9b3a7
Create Date: 2026-07-31

"""
from alembic import op
import sqlalchemy as sa

from app.alembic.alembic_utils import _table_has_column


revision = 'd3b8f5a1c674'
down_revision = 'c2e1f4d9b3a7'
branch_labels = None
depends_on = None


def upgrade():
    # Guarded adds — db.create_all() runs from the ORM models before alembic,
    # so on a fresh install these columns already exist.
    if not _table_has_column('case_ai_artifact', 'edited_content'):
        op.add_column(
            'case_ai_artifact',
            sa.Column('edited_content', sa.Text(), nullable=True)
        )

    if not _table_has_column('case_ai_artifact', 'edited_by_id'):
        op.add_column(
            'case_ai_artifact',
            sa.Column('edited_by_id', sa.Integer(), nullable=True)
        )
        op.create_foreign_key(
            'fk_case_ai_artifact_edited_by_id',
            'case_ai_artifact', 'user',
            ['edited_by_id'], ['id'],
            ondelete='SET NULL'
        )

    if not _table_has_column('case_ai_artifact', 'edited_at'):
        op.add_column(
            'case_ai_artifact',
            sa.Column('edited_at', sa.DateTime(), nullable=True)
        )


def downgrade():
    if _table_has_column('case_ai_artifact', 'edited_at'):
        op.drop_column('case_ai_artifact', 'edited_at')

    if _table_has_column('case_ai_artifact', 'edited_by_id'):
        op.drop_constraint(
            'fk_case_ai_artifact_edited_by_id',
            'case_ai_artifact',
            type_='foreignkey'
        )
        op.drop_column('case_ai_artifact', 'edited_by_id')

    if _table_has_column('case_ai_artifact', 'edited_content'):
        op.drop_column('case_ai_artifact', 'edited_content')

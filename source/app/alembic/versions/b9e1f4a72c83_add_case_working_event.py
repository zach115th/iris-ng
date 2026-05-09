"""add case_working_event table for dual-timeline / Hayabusa imports

Tool-ingested timeline rows (Hayabusa, KAPE, EZTools, Cybertriage, …)
land here as `pending` before an analyst reviews them. Promote → spawns
a real `cases_events` row (status `true_positive`, `promoted_event_id`
back-references it). Reject → status `false_positive`. Architecture in
docs/19-ux-ai-design.md §5b.1.

Designed to live alongside the existing analyst-curated `cases_events`
table — the right-hand "working timeline" rail in the case timeline page
reads from this table, the left-hand rail keeps reading from the
existing one.

Revision ID: b9e1f4a72c83
Revises: a7d1f2e3b8c9
Create Date: 2026-05-05 16:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID

from app.alembic.alembic_utils import _has_table

# revision identifiers, used by Alembic.
revision = 'b9e1f4a72c83'
down_revision = 'a7d1f2e3b8c9'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('case_working_event'):
        op.create_table(
            'case_working_event',
            sa.Column('id', sa.BigInteger(), nullable=False),
            sa.Column('case_id', sa.BigInteger(), nullable=False),
            sa.Column('source', sa.String(32), nullable=False),
            sa.Column('event_date', sa.DateTime(), nullable=False),
            sa.Column('event_title', sa.Text(), nullable=False),
            sa.Column('event_description', sa.Text(), nullable=True),
            sa.Column('event_source_host', sa.Text(), nullable=True),
            sa.Column('severity', sa.String(16), nullable=True),
            sa.Column('event_tags', sa.Text(), nullable=True),
            sa.Column('mitre_techniques', sa.Text(), nullable=True),
            sa.Column('external_id', sa.Text(), nullable=True),
            sa.Column('event_raw', JSONB(), nullable=True),
            sa.Column('import_batch_id', UUID(as_uuid=True), nullable=True),
            sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
            sa.Column('promoted_event_id', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('created_by', sa.Integer(), nullable=True),
            sa.Column('reviewed_at', sa.DateTime(), nullable=True),
            sa.Column('reviewed_by', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['case_id'], ['cases.case_id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['promoted_event_id'], ['cases_events.event_id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['created_by'], ['user.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['reviewed_by'], ['user.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.CheckConstraint(
                "status IN ('pending', 'true_positive', 'false_positive')",
                name='ck_case_working_event_status'
            ),
        )
        op.create_index('ix_case_working_event_case', 'case_working_event', ['case_id'])
        op.create_index('ix_case_working_event_status', 'case_working_event', ['status'])
        op.create_index('ix_case_working_event_batch', 'case_working_event', ['import_batch_id'])
        op.create_index('ix_case_working_event_date', 'case_working_event', ['case_id', 'event_date'])


def downgrade():
    op.drop_index('ix_case_working_event_date', table_name='case_working_event')
    op.drop_index('ix_case_working_event_batch', table_name='case_working_event')
    op.drop_index('ix_case_working_event_status', table_name='case_working_event')
    op.drop_index('ix_case_working_event_case', table_name='case_working_event')
    op.drop_table('case_working_event')

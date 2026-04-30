"""add case_task_link table

Jira-style directed task relationships within a single case. v1 supports
two link types — `blocks` and `depends_on` — each rendered with a forward
and inverse name in the UI:

    blocks       <->  is blocked by
    depends_on   <->  is depended on by

Stored once per pair (forward direction). Inverse views are computed at
read time from the same row, which keeps the data canonical and makes
"swap direction" or "rename link type" trivial.

Revision ID: e5b239c0d128
Revises: d4f12a87bc56
Create Date: 2026-04-29 17:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

# revision identifiers, used by Alembic.
revision = 'e5b239c0d128'
down_revision = 'd4f12a87bc56'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('case_task_link'):
        op.create_table(
            'case_task_link',
            sa.Column('id', sa.BigInteger(), nullable=False),
            sa.Column('from_task_id', sa.BigInteger(), nullable=False),
            sa.Column('to_task_id', sa.BigInteger(), nullable=False),
            sa.Column('link_type', sa.String(32), nullable=False),
            sa.Column('case_id', sa.BigInteger(), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('created_by', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['from_task_id'], ['case_tasks.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['to_task_id'], ['case_tasks.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['case_id'], ['cases.case_id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['created_by'], ['user.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('from_task_id', 'to_task_id', 'link_type', name='uq_case_task_link_triple'),
            sa.CheckConstraint('from_task_id <> to_task_id', name='ck_case_task_link_no_self'),
            sa.CheckConstraint("link_type IN ('blocks', 'depends_on')", name='ck_case_task_link_type'),
        )
        op.create_index('ix_case_task_link_from', 'case_task_link', ['from_task_id'])
        op.create_index('ix_case_task_link_to', 'case_task_link', ['to_task_id'])
        op.create_index('ix_case_task_link_case', 'case_task_link', ['case_id'])


def downgrade():
    op.drop_index('ix_case_task_link_case', table_name='case_task_link')
    op.drop_index('ix_case_task_link_to', table_name='case_task_link')
    op.drop_index('ix_case_task_link_from', table_name='case_task_link')
    op.drop_table('case_task_link')

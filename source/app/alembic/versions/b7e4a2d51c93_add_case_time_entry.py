"""add case_time_entry table

iris-next: analyst time tracking in 15-minute increments.

Stores only (case, analyst, minutes, date, optional note/task). Sector and
incident-type breakdowns are derived at report time by joining through the
case (Client.dhs_sectors / case tag, Cases.classification_id) — they are NOT
columns here, so analysts never enter them and reports self-correct on
reclassification.

CHECK(minutes > 0 AND minutes % 15 = 0) mirrors the ORM model's
__table_args__ (db.create_all runs before alembic, so the CHECK must live on
the model too — this migration's copy is the belt-and-braces path for an
upgrade where the table doesn't yet exist).

Revision ID: b7e4a2d51c93
Revises: a7c4e1f90d35
Create Date: 2026-06-09 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

# revision identifiers, used by Alembic.
revision = 'b7e4a2d51c93'
down_revision = 'a7c4e1f90d35'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('case_time_entry'):
        op.create_table(
            'case_time_entry',
            sa.Column('id', sa.BigInteger(), nullable=False),
            sa.Column('case_id', sa.BigInteger(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=True),
            sa.Column('task_id', sa.BigInteger(), nullable=True),
            sa.Column('minutes', sa.Integer(), nullable=False),
            sa.Column('activity_date', sa.Date(), nullable=False),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(['case_id'], ['cases.case_id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['task_id'], ['case_tasks.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.CheckConstraint('minutes > 0 AND minutes % 15 = 0', name='ck_case_time_entry_increment'),
        )
        op.create_index('ix_case_time_entry_case', 'case_time_entry', ['case_id'])
        op.create_index('ix_case_time_entry_user', 'case_time_entry', ['user_id'])
        op.create_index('ix_case_time_entry_task', 'case_time_entry', ['task_id'])


def downgrade():
    op.drop_index('ix_case_time_entry_task', table_name='case_time_entry')
    op.drop_index('ix_case_time_entry_user', table_name='case_time_entry')
    op.drop_index('ix_case_time_entry_case', table_name='case_time_entry')
    op.drop_table('case_time_entry')

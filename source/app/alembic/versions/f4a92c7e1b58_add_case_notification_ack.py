"""Add case_notification_ack for the per-case updates bell

Revision ID: f4a92c7e1b58
Revises: e7c1a94d2f38
Create Date: 2026-07-31

Stores one read watermark per (user, case) so the notification bell can scope
"what changed since you last acknowledged" to the case the analyst is currently
in. Purely additive - no existing table or column is touched.
"""
from alembic import op
import sqlalchemy as sa

from app.alembic.alembic_utils import _has_table

revision = 'f4a92c7e1b58'
down_revision = 'e7c1a94d2f38'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('case_notification_ack'):
        op.create_table(
            'case_notification_ack',
            sa.Column('id', sa.BigInteger(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('case_id', sa.Integer(), nullable=False),
            sa.Column('last_ack_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['case_id'], ['cases.case_id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'case_id',
                                name='uq_case_notification_ack_user_case'),
        )
        op.create_index('ix_case_notification_ack_user_id',
                        'case_notification_ack', ['user_id'])
        op.create_index('ix_case_notification_ack_case_id',
                        'case_notification_ack', ['case_id'])


def downgrade():
    if _has_table('case_notification_ack'):
        op.drop_table('case_notification_ack')

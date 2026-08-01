"""add retention_months to server_settings

Data-retention policy for the physical evidence-drive inventory. When set,
drives with status='in_use' and date_assigned older than (retention_months × 30)
days receive an 'overdue' indicator on the Inventory dashboard tab, prompting
the evidence custodian to initiate a wipe-and-rotate cycle.

Revision ID: f2a8c6d1e4b9
Revises: b1c3e7f94d20
Create Date: 2026-07-15 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

revision = 'f2a8c6d1e4b9'
down_revision = 'b1c3e7f94d20'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('server_settings', 'retention_months'):
        op.add_column(
            'server_settings',
            sa.Column('retention_months', sa.Integer(), nullable=True)
        )


def downgrade():
    op.drop_column('server_settings', 'retention_months')

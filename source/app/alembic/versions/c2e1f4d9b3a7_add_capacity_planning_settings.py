"""add capacity planning settings

Adds capacity_planning_window_months and capacity_planning_target_months to
server_settings. Both nullable — when NULL the UI defaults apply (3-month
rolling window, 2-month target runway). The capacity-planning indicator on
the Inventory tab uses these to compute effective drive supply and surface
an order recommendation when runway falls below the target threshold.

Revision ID: c2e1f4d9b3a7
Revises: f2a8c6d1e4b9
Create Date: 2026-07-17 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

revision = 'c2e1f4d9b3a7'
down_revision = 'f2a8c6d1e4b9'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('server_settings', 'capacity_planning_window_months'):
        op.add_column(
            'server_settings',
            sa.Column('capacity_planning_window_months', sa.Integer(), nullable=True)
        )
    if not _table_has_column('server_settings', 'capacity_planning_target_months'):
        op.add_column(
            'server_settings',
            sa.Column('capacity_planning_target_months', sa.Integer(), nullable=True)
        )


def downgrade():
    op.drop_column('server_settings', 'capacity_planning_target_months')
    op.drop_column('server_settings', 'capacity_planning_window_months')

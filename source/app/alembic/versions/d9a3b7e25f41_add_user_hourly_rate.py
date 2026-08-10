"""add hourly_rate to user

iris-next: analyst billing rate (currency-units per hour) used to estimate
case cost from logged time. Nullable — unset means "unpriced" (counts as 0 in
cost totals but is flagged in the UI so the figure isn't silently understated).

Guarded with _table_has_column because db.create_all() runs from the ORM models
BEFORE alembic on fresh boot and pre-creates the column — an unguarded
ADD COLUMN would then fail with DuplicateColumn.

Revision ID: d9a3b7e25f41
Revises: c8f1a96b3d27
Create Date: 2026-06-11 19:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

# revision identifiers, used by Alembic.
revision = 'd9a3b7e25f41'
down_revision = 'c8f1a96b3d27'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('user', 'hourly_rate'):
        op.add_column(
            'user',
            sa.Column('hourly_rate', sa.Numeric(10, 2), nullable=True),
        )


def downgrade():
    op.drop_column('user', 'hourly_rate')

"""add time_tracking_nudge_enabled to server_settings

iris-next: opt-in flag for the time-tracking "you logged 0 time on cases you
touched this week" nudge. OFF by default so it never adds analyst overhead
unless an admin enables it on /manage/settings.

Guarded with _table_has_column because db.create_all() runs from the ORM
models BEFORE alembic on fresh boot and pre-creates the column — an unguarded
ADD COLUMN would then fail with DuplicateColumn.

Revision ID: c8f1a96b3d27
Revises: b7e4a2d51c93
Create Date: 2026-06-09 10:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

# revision identifiers, used by Alembic.
revision = 'c8f1a96b3d27'
down_revision = 'b7e4a2d51c93'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('server_settings', 'time_tracking_nudge_enabled'):
        op.add_column(
            'server_settings',
            sa.Column('time_tracking_nudge_enabled', sa.Boolean(),
                      nullable=False, server_default=sa.text('false')),
        )


def downgrade():
    op.drop_column('server_settings', 'time_tracking_nudge_enabled')

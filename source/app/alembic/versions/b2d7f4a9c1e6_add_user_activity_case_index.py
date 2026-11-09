"""Index the activity log by case (iris-ng, 2026-11-08)

The Overview page's case queue shows each case's last activity - the newest `user_activity` row of the case - and
can sort the queue by it. Adds `ix_user_activity_case_date` on (case_id, activity_date) so that read is an index scan
instead of a pass over the whole log. Additive only, no data change.

db.create_all() at boot creates the index on a new database (it is on the ORM's __table_args__) but never on an
existing table, so this migration does (guarded).

Revision ID: b2d7f4a9c1e6
Revises: f3b8d6a1c9e4
Create Date: 2026-11-08
"""
from alembic import op

from app.alembic.alembic_utils import _has_table
from app.alembic.alembic_utils import index_exists

# revision identifiers, used by Alembic.
revision = 'b2d7f4a9c1e6'
down_revision = 'f3b8d6a1c9e4'
branch_labels = None
depends_on = None

INDEX = 'ix_user_activity_case_date'


def upgrade():
    if _has_table('user_activity') and not index_exists('user_activity', INDEX):
        op.create_index(INDEX, 'user_activity', ['case_id', 'activity_date'])


def downgrade():
    pass

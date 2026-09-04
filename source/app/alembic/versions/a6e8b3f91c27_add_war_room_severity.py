"""Add war_room.severity (iris-ng v2, Phase 6 v3-parity)

v3's room header carries a severity chip next to the status. Nullable —
unset renders nothing. Column-adds are NOT covered by create_all on
existing databases, hence the guarded ADD COLUMN.

Revision ID: a6e8b3f91c27
Revises: e3b7a94c25d8
Create Date: 2026-08-26

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

revision = 'a6e8b3f91c27'
down_revision = 'e3b7a94c25d8'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('war_room', 'severity'):
        op.add_column('war_room',
                      sa.Column('severity', sa.String(16), nullable=True))
        op.execute("ALTER TABLE war_room ADD CONSTRAINT ck_war_room_severity "
                   "CHECK (severity IN ('low','medium','high','critical'))")


def downgrade():
    pass

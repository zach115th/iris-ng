"""Add a color to war-room timelines (iris-ng v2, Phase 6 Timelines tab)

v3's New-timeline modal carries a colour swatch: the timeline itself has a
colour, used for the rail dot and as the default colour of its events.
Nullable — existing timelines keep the UI default.

Revision ID: a3d8f6c92b41
Revises: e2c8f5b91a37
Create Date: 2026-08-26

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

revision = 'a3d8f6c92b41'
down_revision = 'e2c8f5b91a37'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('war_room_timeline', 'color'):
        op.add_column('war_room_timeline',
                      sa.Column('color', sa.String(16), nullable=True))


def downgrade():
    pass

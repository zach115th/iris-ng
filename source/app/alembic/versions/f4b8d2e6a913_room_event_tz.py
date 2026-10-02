"""Room timeline events remember the UTC offset they were entered in (iris-ng, 2026-10-02)

`war_room_timeline_event.event_tz` (`+HH:MM`, nullable) mirrors the case
timeline's `event_tz`: `event_date` holds the instant in UTC, `event_tz` how
the analyst entered it. Existing rows keep their stored value as UTC with no
offset recorded (read as +00:00) -- that is what the API has always declared
and what sorting used. Guarded so a re-run is a no-op.

Revision ID: f4b8d2e6a913
Revises: e3a7c5d9f261
Create Date: 2026-10-02
"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

revision = 'f4b8d2e6a913'
down_revision = 'e3a7c5d9f261'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('war_room_timeline_event', 'event_tz'):
        op.add_column('war_room_timeline_event',
                      sa.Column('event_tz', sa.String(6), nullable=True))


def downgrade():
    pass

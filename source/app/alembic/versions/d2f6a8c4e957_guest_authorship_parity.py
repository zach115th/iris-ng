"""Guest authorship parity (iris-ng, 2026-09-30, second guest pass)

Guests take part at full responder level (maintainer decision): polls,
SitRep drafts and edits, room timelines and their events, teams and ICS
seeding. Each of those rows gains a guest FK beside its user FK so the
author renders as "Name (Organisation)" instead of "someone". Every op is
guarded so a re-run is a no-op.

Revision ID: d2f6a8c4e957
Revises: c1e5f7a2b348
Create Date: 2026-09-30

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

revision = 'd2f6a8c4e957'
down_revision = 'c1e5f7a2b348'
branch_labels = None
depends_on = None

COLUMNS = (
    ('war_room_poll', 'created_by_guest_id'),
    ('sitrep', 'created_by_guest_id'),
    ('sitrep_revision', 'guest_id'),
    ('war_room_timeline', 'created_by_guest_id'),
    ('war_room_timeline_event', 'created_by_guest_id'),
    ('war_room_team', 'created_by_guest_id'),
    ('war_room_task', 'done_by_guest_id'),
)


def upgrade():
    for table, column in COLUMNS:
        if not _table_has_column(table, column):
            op.add_column(table, sa.Column(
                column, sa.BigInteger(),
                sa.ForeignKey('war_room_guest.id', ondelete='SET NULL'),
                nullable=True))


def downgrade():
    pass

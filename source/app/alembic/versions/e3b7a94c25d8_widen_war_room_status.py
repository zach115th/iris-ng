"""Widen war_room.status to the v3 four-state model (iris-ng v2, Phase 6)

open / active / standby / closed — maintainer decision for v3 parity.
'closed' takes over 'archived' semantics (read-only, frees a promoted
cluster); open/active/standby are all writable. New rooms start 'open'.

The DROP/ADD is safe on a fresh install too: db.create_all() has already
built the table with the NEW check from the ORM __table_args__, so the
statements just recreate an identical constraint.

Revision ID: e3b7a94c25d8
Revises: c7d9e4a82f51
Create Date: 2026-08-26

"""
from alembic import op

from app.alembic.alembic_utils import _has_table

revision = 'e3b7a94c25d8'
down_revision = 'c7d9e4a82f51'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('war_room'):
        return
    # Data first, constraint second — rows must satisfy the new CHECK.
    op.execute("UPDATE war_room SET status='closed' WHERE status='archived'")
    op.execute("ALTER TABLE war_room DROP CONSTRAINT IF EXISTS ck_war_room_status")
    op.execute("ALTER TABLE war_room ADD CONSTRAINT ck_war_room_status "
               "CHECK (status IN ('open','active','standby','closed'))")
    op.execute("ALTER TABLE war_room ALTER COLUMN status SET DEFAULT 'open'")


def downgrade():
    pass

"""Backfill evidence-drive case associations (iris-ng v2)

Linking evidence to a drive now claims the drive for the evidence's case
(datamgmt _sync_drive_assignment) — but rows linked BEFORE that rule
shipped left drives with evidence and no case. This claims the case for
every NULL-case drive whose linked evidence all belongs to ONE case (the
maintainer rule: a drive holds evidence from one case only), and flips a
claimed 'wiped' (in-rotation) drive to 'in_use' in the same statement.
Drives whose linked evidence spans several cases predate the rule and
cannot be resolved mechanically — they are left untouched. Statuses are
otherwise never rewritten (maintainer decision: no vocabulary migration
of existing rows).

Revision ID: b4e7a2c95d18
Revises: f6c9e5a84b72
Create Date: 2026-08-28

"""
from alembic import op

from app.alembic.alembic_utils import _has_table

revision = 'b4e7a2c95d18'
down_revision = 'f6c9e5a84b72'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('evidence_drive') or not _has_table('case_received_file'):
        return
    op.execute("""
        UPDATE evidence_drive d
        SET case_id = sub.the_case,
            status = CASE WHEN d.status = 'wiped'
                          THEN 'in_use' ELSE d.status END,
            date_assigned = COALESCE(d.date_assigned, now())
        FROM (
            SELECT drive_id, MIN(case_id) AS the_case
            FROM case_received_file
            WHERE drive_id IS NOT NULL
            GROUP BY drive_id
            HAVING COUNT(DISTINCT case_id) = 1
        ) sub
        WHERE d.id = sub.drive_id
          AND d.case_id IS NULL
    """)


def downgrade():
    # Data backfill — the claimed associations are correct either way;
    # nothing to undo.
    pass

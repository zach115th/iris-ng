"""add evidence_drive (physical drive inventory) + drive_id on evidence

iris-next: Inventory tab. A physical drive is the barcoded item that holds
digital evidence; `evidence_drive` tracks it (barcode, label, physical_location,
status lifecycle, current case). `case_received_file.drive_id` links each logical
evidence item to the drive it lives on. One drive → one current case, reusable
across its lifecycle (assigned → in_use → wiped → available). Wiping clears
case_id + unlinks evidence items but keeps the evidence rows (case history must
survive), hence ondelete=SET NULL on both FKs.

Revision ID: b4d7e2f93a18
Revises: a8e3f1c64b27
Create Date: 2026-05-28 19:15:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.alembic.alembic_utils import _has_table, _table_has_column


revision = 'b4d7e2f93a18'
down_revision = 'a8e3f1c64b27'
branch_labels = None
depends_on = None


def upgrade():
    # iris-ng runs db.create_all() BEFORE alembic, so on a fresh install the
    # table + column may already exist — guard both.
    if not _has_table('evidence_drive'):
        op.create_table(
            'evidence_drive',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('drive_uuid', postgresql.UUID(as_uuid=True),
                      server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.Column('barcode', sa.Text(), nullable=False),
            sa.Column('label', sa.Text(), nullable=True),
            sa.Column('physical_location', sa.Text(), nullable=True),
            sa.Column('status', sa.Text(), server_default=sa.text("'available'"), nullable=False),
            sa.Column('capacity', sa.Text(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_by', sa.Text(), nullable=True),
            sa.Column('case_id', sa.Integer(), nullable=True),
            sa.Column('date_added', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
            sa.Column('date_assigned', sa.DateTime(), nullable=True),
            sa.Column('date_wiped', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['case_id'], ['cases.case_id'], ondelete='SET NULL'),
            sa.UniqueConstraint('barcode', name='uq_evidence_drive_barcode'),
        )

    if not _table_has_column('case_received_file', 'drive_id'):
        op.add_column('case_received_file', sa.Column('drive_id', sa.BigInteger(), nullable=True))
        op.create_foreign_key(
            'fk_case_received_file_drive_id', 'case_received_file',
            'evidence_drive', ['drive_id'], ['id'], ondelete='SET NULL'
        )


def downgrade():
    op.drop_constraint('fk_case_received_file_drive_id', 'case_received_file', type_='foreignkey')
    op.drop_column('case_received_file', 'drive_id')
    op.drop_table('evidence_drive')

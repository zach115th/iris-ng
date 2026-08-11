"""add created_by, barcode, physical_location to evidence

iris-next: physical chain-of-custody metadata on case evidence
(`case_received_file`). `user_id` already records the IRIS account that
registered the evidence; these add the physical custodian / collector
(`created_by`, free text — may be an IRIS username or an external party), the
evidence bag/item bar code (`barcode`), and where the physical item is stored
(`physical_location`). All nullable — drop-in safe for existing rows + clients.

Revision ID: a8e3f1c64b27
Revises: f1a4c8b97e23
Create Date: 2026-05-28 18:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column


revision = 'a8e3f1c64b27'
down_revision = 'f1a4c8b97e23'
branch_labels = None
depends_on = None


def upgrade():
    # iris-ng runs `db.create_all()` BEFORE alembic on first boot, so on a
    # fresh install these columns may already exist — guard each ADD COLUMN.
    if not _table_has_column('case_received_file', 'created_by'):
        op.add_column('case_received_file', sa.Column('created_by', sa.Text(), nullable=True))
    if not _table_has_column('case_received_file', 'barcode'):
        op.add_column('case_received_file', sa.Column('barcode', sa.Text(), nullable=True))
    if not _table_has_column('case_received_file', 'physical_location'):
        op.add_column('case_received_file', sa.Column('physical_location', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('case_received_file', 'physical_location')
    op.drop_column('case_received_file', 'barcode')
    op.drop_column('case_received_file', 'created_by')

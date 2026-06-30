"""add serial_number to evidence_drive

iris-next: physical drives in the Inventory tab now record a serial number
(nullable free text) alongside barcode/label/capacity.

Revision ID: c5a9e16d3072
Revises: b4d7e2f93a18
Create Date: 2026-05-28 20:10:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column


revision = 'c5a9e16d3072'
down_revision = 'b4d7e2f93a18'
branch_labels = None
depends_on = None


def upgrade():
    # iris-ng runs db.create_all() BEFORE alembic on first boot — guard the ADD.
    if not _table_has_column('evidence_drive', 'serial_number'):
        op.add_column('evidence_drive', sa.Column('serial_number', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('evidence_drive', 'serial_number')

"""add dhs_sectors to client

iris-next: customers (clients) now carry a comma-separated list of DHS CIIP
sector slugs (e.g. "financial-services,it"). New cases created for the
customer inherit these as `dhs-ciip-sectors:DHS-critical-sectors="<slug>"`
tags when the case create payload doesn't already include a sector tag.

Revision ID: f1a4c8b97e23
Revises: e9d2c5a3f8b1
Create Date: 2026-05-13 17:50:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column


revision = 'f1a4c8b97e23'
down_revision = 'e9d2c5a3f8b1'
branch_labels = None
depends_on = None


def upgrade():
    # iris-ng runs `db.create_all()` BEFORE alembic on first boot, so on a
    # fresh install the column may already exist.
    if not _table_has_column('client', 'dhs_sectors'):
        op.add_column('client', sa.Column('dhs_sectors', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('client', 'dhs_sectors')

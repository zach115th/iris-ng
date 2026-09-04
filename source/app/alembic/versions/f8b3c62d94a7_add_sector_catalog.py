"""Sector catalog — admin-editable sectors as a case object (iris-ng v2)

New sector_catalog table backing Case Objects > Sectors. Replaces the
hardcoded sector picker options in modal_add_case.html /
modal_add_customer.html and the recognition dicts in business/cases.py +
business/dashboard_metrics.py. Seeded at boot (post_init.create_safe_sectors,
slug-keyed upsert) with the 16 DHS CIIP sectors + threatmatch Education.

Guarded create: db.create_all() runs before alembic and creates the table on
upgraded instances; this migration is the chain record (fork rule).

Revision ID: f8b3c62d94a7
Revises: e5c8a73f92d4
Create Date: 2026-09-02

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

revision = 'f8b3c62d94a7'
down_revision = 'e5c8a73f92d4'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('sector_catalog'):
        op.create_table(
            'sector_catalog',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('slug', sa.Text(), nullable=False),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('tag', sa.Text(), nullable=False),
            sa.Column('enabled', sa.Boolean(), nullable=False,
                      server_default=sa.text('true')),
            sa.Column('creation_date', sa.DateTime(), nullable=True,
                      server_default=sa.text('now()')),
            sa.UniqueConstraint('slug', name='uq_sector_catalog_slug'),
        )


def downgrade():
    if _has_table('sector_catalog'):
        op.drop_table('sector_catalog')

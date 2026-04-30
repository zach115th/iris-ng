"""add misp sync link tables

Revision ID: a1d9f5d4c2e8
Revises: d5a720d1b99b
Create Date: 2026-04-28 14:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

# revision identifiers, used by Alembic.
revision = 'a1d9f5d4c2e8'
down_revision = 'd5a720d1b99b'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('misp_event_link'):
        op.create_table(
            'misp_event_link',
            sa.Column('id', sa.BigInteger(), nullable=False),
            sa.Column('case_id', sa.BigInteger(), nullable=False),
            sa.Column('misp_event_id', sa.BigInteger(), nullable=False),
            sa.Column('misp_event_uuid', sa.Text(), nullable=True),
            sa.Column('misp_org_id', sa.Integer(), nullable=True),
            sa.Column('misp_distribution', sa.Integer(), nullable=True),
            sa.Column('misp_sharing_group_id', sa.Integer(), nullable=True),
            sa.Column('date_created', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.Column('last_synced_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['case_id'], ['cases.case_id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('case_id'),
            sa.UniqueConstraint('misp_event_id'),
            sa.UniqueConstraint('misp_event_uuid'),
        )

    if not _has_table('misp_attribute_link'):
        op.create_table(
            'misp_attribute_link',
            sa.Column('id', sa.BigInteger(), nullable=False),
            sa.Column('event_link_id', sa.BigInteger(), nullable=False),
            sa.Column('ioc_id', sa.BigInteger(), nullable=False),
            sa.Column('misp_attribute_id', sa.BigInteger(), nullable=False),
            sa.Column('misp_attribute_uuid', sa.Text(), nullable=True),
            sa.Column('date_created', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.Column('last_synced_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['event_link_id'], ['misp_event_link.id']),
            sa.ForeignKeyConstraint(['ioc_id'], ['ioc.ioc_id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('ioc_id'),
            sa.UniqueConstraint('misp_attribute_id'),
            sa.UniqueConstraint('misp_attribute_uuid'),
        )


def downgrade():
    if _has_table('misp_attribute_link'):
        op.drop_table('misp_attribute_link')

    if _has_table('misp_event_link'):
        op.drop_table('misp_event_link')

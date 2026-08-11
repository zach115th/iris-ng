"""Add misp_cluster_link for the MISP cluster publisher

Records which correlation clusters have been published to MISP as campaign
events, so a repeat "Push to MISP" cannot silently create a duplicate event.

Revision ID: e7c1a94d2f38
Revises: d3b8f5a1c674
Create Date: 2026-07-31

"""
from alembic import op
import sqlalchemy as sa

from app.alembic.alembic_utils import _has_table


revision = 'e7c1a94d2f38'
down_revision = 'd3b8f5a1c674'
branch_labels = None
depends_on = None


def upgrade():
    # db.create_all() runs from the ORM models before alembic, so on a fresh
    # install the table (and its UNIQUE, which is declared on __table_args__)
    # already exists.
    if _has_table('misp_cluster_link'):
        return

    op.create_table(
        'misp_cluster_link',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('cluster_id', sa.String(length=64), nullable=False),
        sa.Column('misp_event_id', sa.Integer(), nullable=False),
        sa.Column('misp_event_uuid', sa.String(length=80), nullable=True),
        sa.Column('case_ids', sa.Text(), nullable=True),
        sa.Column('pushed_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('pushed_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['pushed_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cluster_id', name='uq_misp_cluster_link_cluster_id'),
    )
    op.create_index(
        op.f('ix_misp_cluster_link_cluster_id'),
        'misp_cluster_link', ['cluster_id'], unique=False
    )


def downgrade():
    if not _has_table('misp_cluster_link'):
        return
    op.drop_index(op.f('ix_misp_cluster_link_cluster_id'), table_name='misp_cluster_link')
    op.drop_table('misp_cluster_link')

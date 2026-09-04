"""Add customer_asset + customer_asset_change (iris-ng v2, Phase 4)

Org-wide asset registry: one row per (customer, lower(trim(name)), type) —
the identity rule that existed as dead code in
CaseAssetsSchema.is_unique_for_customer, now enforced by a UNIQUE. Sync
advances last_seen and raises compromise status only from unassessed;
analyst curation fields are never overwritten. customer_asset_change holds
dedicated audit rows (cross-asset queryable, unlike a JSON blob).

CHECK/UNIQUE constraints are declared on the ORM __table_args__ as well —
db.create_all() runs before alembic on a fresh install and the guarded
creates below are skipped.

Revision ID: e8a4c95d17f3
Revises: d2f7b83c46a1
Create Date: 2026-08-25

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

revision = 'e8a4c95d17f3'
down_revision = 'd2f7b83c46a1'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('customer_asset'):
        op.create_table(
            'customer_asset',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('customer_id', sa.BigInteger(), nullable=False),
            sa.Column('asset_name', sa.Text(), nullable=False),
            sa.Column('asset_name_norm', sa.Text(), nullable=False),
            sa.Column('asset_type_id', sa.Integer(), nullable=False),
            sa.Column('criticality', sa.String(16), nullable=True),
            sa.Column('environment', sa.Text(), nullable=True),
            sa.Column('owner', sa.Text(), nullable=True),
            sa.Column('compromise_status', sa.Integer(), nullable=True),
            sa.Column('compromise_since', sa.DateTime(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('first_seen', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.Column('last_seen', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.Column('created_by', sa.BigInteger(), nullable=True),
            sa.ForeignKeyConstraint(['customer_id'], ['client.client_id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['asset_type_id'], ['assets_type.asset_id']),
            sa.ForeignKeyConstraint(['created_by'], ['user.id']),
            sa.UniqueConstraint('customer_id', 'asset_name_norm', 'asset_type_id',
                                name='uq_customer_asset_identity'),
            sa.CheckConstraint("criticality IN ('low', 'medium', 'high', 'critical')",
                               name='ck_customer_asset_criticality'),
        )
        op.create_index(op.f('ix_customer_asset_customer_id'), 'customer_asset',
                        ['customer_id'])

    if not _has_table('customer_asset_change'):
        op.create_table(
            'customer_asset_change',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('customer_asset_id', sa.BigInteger(), nullable=False),
            sa.Column('field', sa.String(64), nullable=False),
            sa.Column('old_value', sa.Text(), nullable=True),
            sa.Column('new_value', sa.Text(), nullable=True),
            sa.Column('changed_by', sa.BigInteger(), nullable=True),
            sa.Column('changed_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['customer_asset_id'], ['customer_asset.id'],
                                    ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['changed_by'], ['user.id']),
        )
        op.create_index(op.f('ix_customer_asset_change_customer_asset_id'),
                        'customer_asset_change', ['customer_asset_id'])


def downgrade():
    if _has_table('customer_asset_change'):
        op.drop_table('customer_asset_change')
    if _has_table('customer_asset'):
        op.drop_table('customer_asset')

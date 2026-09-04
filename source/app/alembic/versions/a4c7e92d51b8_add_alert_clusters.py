"""Add alert_clustering_rule + alert_cluster + alert_cluster_member (iris-ng v2, Phase 2)

alert_clustering_rule: priority-ordered rules whose JSON condition tree is
evaluated in Python at ingest time; correlation_keys (dotted alert_view paths)
plus rule id + customer id are hashed into a cluster fingerprint.
alert_cluster: one group of stacked alerts; the PARTIAL unique index on
(correlation_fingerprint) WHERE status='open' is the concurrency contract —
at most one open cluster per fingerprint, racing creators lose with an
IntegrityError and re-SELECT to join. alert_cluster_member: (cluster, alert)
with UNIQUE(alert_id) — v1: an alert belongs to at most one cluster.

CHECK/UNIQUE constraints and the partial index are declared on the ORM
__table_args__ as well — on a fresh install db.create_all() creates these
tables before alembic runs, and the guarded creates below are skipped.

Revision ID: a4c7e92d51b8
Revises: b3e9d47a51c2
Create Date: 2026-08-25

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.alembic.alembic_utils import _has_table

revision = 'a4c7e92d51b8'
down_revision = 'b3e9d47a51c2'
branch_labels = None
depends_on = None


def upgrade():
    # iris-ng runs db.create_all() BEFORE alembic, so on a fresh install the
    # tables already exist — guard every create.
    if not _has_table('alert_clustering_rule'):
        op.create_table(
            'alert_clustering_rule',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('rule_uuid', postgresql.UUID(as_uuid=True),
                      server_default=sa.text('gen_random_uuid()'), nullable=False, unique=True),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('priority', sa.Integer(), server_default=sa.text('100'), nullable=False),
            sa.Column('match_conditions', postgresql.JSON(),
                      server_default=sa.text("'{}'::json"), nullable=False),
            sa.Column('correlation_keys', postgresql.JSON(),
                      server_default=sa.text("'[]'::json"), nullable=False),
            sa.Column('window_minutes', sa.Integer(), server_default=sa.text('1440'), nullable=False),
            sa.Column('title_template', sa.Text(), nullable=True),
            sa.Column('created_by', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['created_by'], ['user.id']),
            sa.CheckConstraint('window_minutes > 0',
                               name='ck_alert_clustering_rule_window'),
        )

    if not _has_table('alert_cluster'):
        op.create_table(
            'alert_cluster',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('cluster_uuid', postgresql.UUID(as_uuid=True),
                      server_default=sa.text('gen_random_uuid()'), nullable=False, unique=True),
            sa.Column('rule_id', sa.BigInteger(), nullable=True),
            sa.Column('customer_id', sa.BigInteger(), nullable=False),
            sa.Column('correlation_fingerprint', sa.String(64), nullable=False),
            sa.Column('correlation_values', postgresql.JSON(), nullable=True),
            sa.Column('title', sa.Text(), nullable=False),
            sa.Column('status', sa.String(16), server_default=sa.text("'open'"), nullable=False),
            sa.Column('first_alert_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.Column('last_alert_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.Column('closed_at', sa.DateTime(), nullable=True),
            sa.Column('closed_by', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['rule_id'], ['alert_clustering_rule.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['customer_id'], ['client.client_id']),
            sa.ForeignKeyConstraint(['closed_by'], ['user.id']),
            sa.CheckConstraint("status IN ('open', 'closed')",
                               name='ck_alert_cluster_status'),
        )
        op.create_index('uq_alert_cluster_open_fingerprint', 'alert_cluster',
                        ['correlation_fingerprint'], unique=True,
                        postgresql_where=sa.text("status = 'open'"))
        op.create_index('idx_alert_cluster_customer', 'alert_cluster', ['customer_id'])

    if not _has_table('alert_cluster_member'):
        op.create_table(
            'alert_cluster_member',
            sa.Column('cluster_id', sa.BigInteger(), primary_key=True, nullable=False),
            sa.Column('alert_id', sa.BigInteger(), primary_key=True, nullable=False),
            sa.Column('added_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['cluster_id'], ['alert_cluster.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['alert_id'], ['alerts.alert_id'], ondelete='CASCADE'),
            sa.UniqueConstraint('alert_id', name='uq_alert_cluster_member_alert'),
        )
        op.create_index(op.f('ix_alert_cluster_member_alert_id'),
                        'alert_cluster_member', ['alert_id'])


def downgrade():
    if _has_table('alert_cluster_member'):
        op.drop_table('alert_cluster_member')
    if _has_table('alert_cluster'):
        op.drop_table('alert_cluster')
    if _has_table('alert_clustering_rule'):
        op.drop_table('alert_clustering_rule')

"""Add investigation flows (iris-ng v2, Phase 3)

investigation_flow: checklists auto-attached at ingest to alerts (and/or to
clusters via the alert that creates them) by the shared condition grammar.
investigation_flow_step: ordered steps, is_required advisory in v1.
flow_attachment: one flow instance per anchor (alert XOR cluster, CHECK;
UNIQUE(flow, anchor) makes deploys idempotent) — ingest writes only this.
flow_step_state: lazily created on first read; pending|done|skipped.

CHECK/UNIQUE constraints are declared on the ORM __table_args__ as well —
db.create_all() runs before alembic on a fresh install and the guarded
creates below are skipped.

Revision ID: d2f7b83c46a1
Revises: c6d84f3a217e
Create Date: 2026-08-25

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.alembic.alembic_utils import _has_table

revision = 'd2f7b83c46a1'
down_revision = 'c6d84f3a217e'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('investigation_flow'):
        op.create_table(
            'investigation_flow',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('flow_uuid', postgresql.UUID(as_uuid=True),
                      server_default=sa.text('gen_random_uuid()'), nullable=False, unique=True),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('priority', sa.Integer(), server_default=sa.text('100'), nullable=False),
            sa.Column('target', sa.String(16), server_default=sa.text("'alert'"), nullable=False),
            sa.Column('match_conditions', postgresql.JSON(),
                      server_default=sa.text("'{}'::json"), nullable=False),
            sa.Column('created_by', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['created_by'], ['user.id']),
            sa.CheckConstraint("target IN ('alert', 'cluster', 'both')",
                               name='ck_investigation_flow_target'),
        )

    if not _has_table('investigation_flow_step'):
        op.create_table(
            'investigation_flow_step',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('flow_id', sa.BigInteger(), nullable=False),
            sa.Column('step_order', sa.Integer(), nullable=False),
            sa.Column('title', sa.Text(), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('is_required', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.ForeignKeyConstraint(['flow_id'], ['investigation_flow.id'], ondelete='CASCADE'),
            sa.UniqueConstraint('flow_id', 'step_order', name='uq_flow_step_order'),
        )
        op.create_index(op.f('ix_investigation_flow_step_flow_id'),
                        'investigation_flow_step', ['flow_id'])

    if not _has_table('flow_attachment'):
        op.create_table(
            'flow_attachment',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('flow_id', sa.BigInteger(), nullable=False),
            sa.Column('alert_id', sa.BigInteger(), nullable=True),
            sa.Column('cluster_id', sa.BigInteger(), nullable=True),
            sa.Column('attached_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['flow_id'], ['investigation_flow.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['alert_id'], ['alerts.alert_id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['cluster_id'], ['alert_cluster.id'], ondelete='CASCADE'),
            sa.CheckConstraint('(alert_id IS NULL) != (cluster_id IS NULL)',
                               name='ck_flow_attachment_one_anchor'),
            sa.UniqueConstraint('flow_id', 'alert_id', name='uq_flow_attachment_alert'),
            sa.UniqueConstraint('flow_id', 'cluster_id', name='uq_flow_attachment_cluster'),
        )
        op.create_index(op.f('ix_flow_attachment_flow_id'), 'flow_attachment', ['flow_id'])
        op.create_index(op.f('ix_flow_attachment_alert_id'), 'flow_attachment', ['alert_id'])
        op.create_index(op.f('ix_flow_attachment_cluster_id'), 'flow_attachment', ['cluster_id'])

    if not _has_table('flow_step_state'):
        op.create_table(
            'flow_step_state',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('attachment_id', sa.BigInteger(), nullable=False),
            sa.Column('step_id', sa.BigInteger(), nullable=False),
            sa.Column('state', sa.String(16), server_default=sa.text("'pending'"), nullable=False),
            sa.Column('done_by', sa.BigInteger(), nullable=True),
            sa.Column('done_at', sa.DateTime(), nullable=True),
            sa.Column('note', sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(['attachment_id'], ['flow_attachment.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['step_id'], ['investigation_flow_step.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['done_by'], ['user.id']),
            sa.CheckConstraint("state IN ('pending', 'done', 'skipped')",
                               name='ck_flow_step_state'),
            sa.UniqueConstraint('attachment_id', 'step_id', name='uq_flow_step_state'),
        )
        op.create_index(op.f('ix_flow_step_state_attachment_id'),
                        'flow_step_state', ['attachment_id'])
        op.create_index(op.f('ix_flow_step_state_step_id'), 'flow_step_state', ['step_id'])


def downgrade():
    for table in ('flow_step_state', 'flow_attachment',
                  'investigation_flow_step', 'investigation_flow'):
        if _has_table(table):
            op.drop_table(table)

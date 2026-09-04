"""Add mail_rule + mail_ingest_log (iris-ng v2, Phase 1)

mail_rule: ordered first-match rules turning ingested email into alerts (or
dropping it), with per-rule alert defaults (customer/severity/classification/
source/title template) and an explicit is_fallback flag evaluated after every
non-fallback rule. mail_ingest_log: one row per processed message whatever the
outcome — the audit trail and the Message-ID dedup barrier (unique; Postgres
permits multiple NULLs, code falls back to (imap_uid, folder) for those).

CHECK/UNIQUE constraints are declared on the ORM __table_args__ as well — on a
fresh install db.create_all() creates these tables before alembic runs, and the
guarded creates below are skipped.

Revision ID: b3e9d47a51c2
Revises: f7a3c58d21e6
Create Date: 2026-08-25

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.alembic.alembic_utils import _has_table

revision = 'b3e9d47a51c2'
down_revision = 'f7a3c58d21e6'
branch_labels = None
depends_on = None


def upgrade():
    # iris-ng runs db.create_all() BEFORE alembic, so on a fresh install the
    # tables already exist — guard both creates.
    if not _has_table('mail_rule'):
        op.create_table(
            'mail_rule',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('rule_uuid', postgresql.UUID(as_uuid=True),
                      server_default=sa.text('gen_random_uuid()'), nullable=False, unique=True),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('priority', sa.Integer(), server_default=sa.text('100'), nullable=False),
            sa.Column('conditions', postgresql.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
            sa.Column('action', sa.String(32), server_default=sa.text("'create_alert'"), nullable=False),
            sa.Column('is_fallback', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('customer_id', sa.BigInteger(), nullable=False),
            sa.Column('severity_id', sa.Integer(), nullable=True),
            sa.Column('classification_id', sa.Integer(), nullable=True),
            sa.Column('alert_source', sa.Text(), server_default=sa.text("'Mail'"), nullable=False),
            sa.Column('title_template', sa.Text(), nullable=True),
            sa.Column('created_by', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['customer_id'], ['client.client_id']),
            sa.ForeignKeyConstraint(['severity_id'], ['severities.severity_id']),
            sa.ForeignKeyConstraint(['classification_id'], ['case_classification.id']),
            sa.ForeignKeyConstraint(['created_by'], ['user.id']),
            sa.CheckConstraint("action IN ('create_alert', 'ignore')",
                               name='ck_mail_rule_action'),
        )

    if not _has_table('mail_ingest_log'):
        op.create_table(
            'mail_ingest_log',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('message_id', sa.Text(), nullable=True),
            sa.Column('imap_uid', sa.Text(), nullable=True),
            sa.Column('folder', sa.Text(), nullable=True),
            sa.Column('from_addr', sa.Text(), nullable=True),
            sa.Column('subject', sa.Text(), nullable=True),
            sa.Column('received_at', sa.DateTime(), nullable=True),
            sa.Column('processed_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.Column('rule_id', sa.BigInteger(), nullable=True),
            sa.Column('outcome', sa.String(32), nullable=False),
            sa.Column('alert_id', sa.BigInteger(), nullable=True),
            sa.Column('error', sa.Text(), nullable=True),
            sa.Column('ai_triage', postgresql.JSON(), nullable=True),
            sa.ForeignKeyConstraint(['rule_id'], ['mail_rule.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['alert_id'], ['alerts.alert_id'], ondelete='SET NULL'),
            sa.UniqueConstraint('message_id', name='uq_mail_ingest_message_id'),
            sa.CheckConstraint(
                "outcome IN ('alert_created', 'ignored', 'no_match', 'duplicate', 'error')",
                name='ck_mail_ingest_outcome'),
        )
        op.create_index('idx_mail_ingest_processed_at', 'mail_ingest_log', ['processed_at'])


def downgrade():
    if _has_table('mail_ingest_log'):
        op.drop_table('mail_ingest_log')
    if _has_table('mail_rule'):
        op.drop_table('mail_rule')

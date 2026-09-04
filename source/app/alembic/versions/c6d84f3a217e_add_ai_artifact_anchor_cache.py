"""Add ai_artifact — generic non-case AI cache (iris-ng v2, Phase 2)

Same (kind, input_hash, content, manual-override) contract as
case_ai_artifact, keyed by (anchor_type, anchor_id) instead of a case FK.
First anchors: alert_cluster (Phase 2 AI cluster triage) and war_room
(Phase 6 SitRep drafts). anchor_id carries no FK on purpose (polymorphic);
reads always take the newest row per anchor, orphans are harmless cache.

CHECK constraint + index are declared on the ORM __table_args__ as well —
on a fresh install db.create_all() creates this table before alembic runs
and the guarded create below is skipped.

Revision ID: c6d84f3a217e
Revises: a4c7e92d51b8
Create Date: 2026-08-25

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

revision = 'c6d84f3a217e'
down_revision = 'a4c7e92d51b8'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('ai_artifact'):
        op.create_table(
            'ai_artifact',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('anchor_type', sa.String(32), nullable=False),
            sa.Column('anchor_id', sa.BigInteger(), nullable=False),
            sa.Column('kind', sa.String(64), nullable=False),
            sa.Column('prompt_id', sa.String(128), nullable=False),
            sa.Column('model', sa.String(128), nullable=False),
            sa.Column('input_hash', sa.String(64), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('confidence', sa.Float(), nullable=True),
            sa.Column('generated_at', sa.DateTime(), server_default=sa.text('now()'),
                      nullable=False),
            sa.Column('edited_content', sa.Text(), nullable=True),
            sa.Column('edited_by_id', sa.BigInteger(), nullable=True),
            sa.Column('edited_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['edited_by_id'], ['user.id']),
            sa.CheckConstraint("anchor_type IN ('alert_cluster', 'war_room')",
                               name='ck_ai_artifact_anchor_type'),
        )
        op.create_index('idx_ai_artifact_anchor', 'ai_artifact',
                        ['anchor_type', 'anchor_id', 'kind'])


def downgrade():
    if _has_table('ai_artifact'):
        op.drop_table('ai_artifact')

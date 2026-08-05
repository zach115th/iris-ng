"""add ai_job (async AI request queue)

iris-next: async AI queue (docs/19 §5b.3). One row per enqueued AI request.
The POST endpoints enqueue a celery task on the dedicated `ai_queue`
(worker_concurrency=1, bounds GPU load on the single LM Studio stream),
return 202 + task_id, and the client polls GET /api/v2/ai/jobs/<task_id>.

Two result shapes: artifact-returning features (summary) populate
artifact_id; dict-returning features (chat) populate result_json.

Revision ID: a7c4e1f90d35
Revises: c5a9e16d3072
Create Date: 2026-06-02 16:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table


revision = 'a7c4e1f90d35'
down_revision = 'c5a9e16d3072'
branch_labels = None
depends_on = None


def upgrade():
    # iris-ng runs db.create_all() BEFORE alembic, so on a fresh install the
    # table may already exist — guard it.
    if not _has_table('ai_job'):
        op.create_table(
            'ai_job',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('task_id', sa.String(length=36), nullable=False),
            sa.Column('case_id', sa.Integer(), nullable=True),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('feature', sa.String(length=64), nullable=False),
            sa.Column('params', sa.Text(), nullable=True),
            sa.Column('priority', sa.Integer(), server_default=sa.text('5'), nullable=False),
            sa.Column('state', sa.String(length=16), server_default=sa.text("'queued'"), nullable=False),
            sa.Column('submitted_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('finished_at', sa.DateTime(), nullable=True),
            sa.Column('artifact_id', sa.BigInteger(), nullable=True),
            sa.Column('result_json', sa.Text(), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(['case_id'], ['cases.case_id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['user.id']),
            sa.ForeignKeyConstraint(['artifact_id'], ['case_ai_artifact.id'], ondelete='SET NULL'),
            sa.UniqueConstraint('task_id', name='uq_ai_job_task_id'),
        )
        op.create_index('ix_ai_job_task_id', 'ai_job', ['task_id'])
        op.create_index('ix_ai_job_case_id', 'ai_job', ['case_id'])
        op.create_index('ix_ai_job_state', 'ai_job', ['state'])


def downgrade():
    op.drop_table('ai_job')

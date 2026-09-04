"""Add runtime_secret table

Backs the first-boot generation of IRIS_SECRET_KEY, so an install that never
changed the shipped placeholder does not sign session cookies with a value that
is public in the repository.

Guarded with _has_table because db.create_all() runs from the ORM models before
alembic, so on a fresh install the table already exists by the time this runs.

Revision ID: c9f1e4b28a37
Revises: f4a92c7e1b58
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

from app.alembic.alembic_utils import _has_table

revision = 'c9f1e4b28a37'
down_revision = 'f4a92c7e1b58'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('runtime_secret'):
        op.create_table(
            'runtime_secret',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('value', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
            # Also declared on the ORM model. This is what makes concurrent
            # first-boot generation safe: the first INSERT wins and every other
            # process re-reads the stored value instead of overwriting it.
            sa.UniqueConstraint('name', name='uq_runtime_secret_name'),
        )


def downgrade():
    if _has_table('runtime_secret'):
        op.drop_table('runtime_secret')

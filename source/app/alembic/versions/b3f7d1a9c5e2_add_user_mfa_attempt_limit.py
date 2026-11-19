"""The second-factor attempt limit and TOTP replay guard (iris-ng, 2026-11-15)

Adds three columns to `user`: `mfa_failed_attempts` (integer, NOT NULL, default 0),
`mfa_locked_until` (timestamp, nullable) and `mfa_last_timestep` (bigint, nullable), read and
written by business/mfa_attempts.py. Additive only; existing users start with no failed attempts,
no lock and no remembered code.

Revision ID: b3f7d1a9c5e2
Revises: e4b9c2a7f5d1
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

revision = 'b3f7d1a9c5e2'
down_revision = 'e4b9c2a7f5d1'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('user', 'mfa_failed_attempts'):
        op.add_column('user', sa.Column('mfa_failed_attempts', sa.Integer(), nullable=False,
                                        server_default=sa.text('0')))
    if not _table_has_column('user', 'mfa_locked_until'):
        op.add_column('user', sa.Column('mfa_locked_until', sa.DateTime(), nullable=True))
    if not _table_has_column('user', 'mfa_last_timestep'):
        op.add_column('user', sa.Column('mfa_last_timestep', sa.BigInteger(), nullable=True))


def downgrade():
    pass

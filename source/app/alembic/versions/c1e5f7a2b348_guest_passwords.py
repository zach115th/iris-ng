"""Guest passwords (iris-ng, 2026-09-30)

`war_room_guest` gains a bcrypt password hash, when it was set, and the
lockout counters. Every op is guarded.

Revision ID: c1e5f7a2b348
Revises: b9d4e6f0a123
Create Date: 2026-09-30

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

revision = 'c1e5f7a2b348'
down_revision = 'b9d4e6f0a123'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('war_room_guest', 'password_hash'):
        op.add_column('war_room_guest', sa.Column('password_hash', sa.Text(), nullable=True))
    if not _table_has_column('war_room_guest', 'password_set_at'):
        op.add_column('war_room_guest', sa.Column('password_set_at', sa.DateTime(), nullable=True))
    if not _table_has_column('war_room_guest', 'failed_logins'):
        op.add_column('war_room_guest', sa.Column('failed_logins', sa.Integer(), nullable=False,
                                                  server_default=sa.text('0')))
    if not _table_has_column('war_room_guest', 'locked_until'):
        op.add_column('war_room_guest', sa.Column('locked_until', sa.DateTime(), nullable=True))


def downgrade():
    pass

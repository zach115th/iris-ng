"""Add notification + user_notification_preference (iris-ng v2, Phase 5)

Addressed-to-me notifications: event-typed rows per recipient (mentions,
assignments, escalations), distinct in scope from the per-case bell which
reads user_activity. Channel resolution is user override -> org default
(server_settings.notification_defaults JSONB, added here) -> code default
(in-app on, email off).

CHECK/UNIQUE constraints are declared on the ORM __table_args__ as well —
db.create_all() runs before alembic on a fresh install and the guarded
creates below are skipped.

Revision ID: a9d1e83f47c2
Revises: e8a4c95d17f3
Create Date: 2026-08-25

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from app.alembic.alembic_utils import _has_table
from app.alembic.alembic_utils import _table_has_column

revision = 'a9d1e83f47c2'
down_revision = 'e8a4c95d17f3'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('notification'):
        op.create_table(
            'notification',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('event_type', sa.String(64), nullable=False),
            sa.Column('title', sa.Text(), nullable=False),
            sa.Column('body', sa.Text(), nullable=True),
            sa.Column('object_type', sa.String(32), nullable=True),
            sa.Column('object_id', sa.BigInteger(), nullable=True),
            sa.Column('case_id', sa.BigInteger(), nullable=True),
            sa.Column('url', sa.Text(), nullable=True),
            sa.Column('is_read', sa.Boolean(), server_default=sa.text('false'),
                      nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'),
                      nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        )
        op.create_index('idx_notification_user_read_created', 'notification',
                        ['user_id', 'is_read', 'created_at'])

    if not _has_table('user_notification_preference'):
        op.create_table(
            'user_notification_preference',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('event_type', sa.String(64), nullable=False),
            sa.Column('in_app', sa.Boolean(), nullable=True),
            sa.Column('email', sa.Boolean(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
            sa.UniqueConstraint('user_id', 'event_type',
                                name='uq_user_notification_pref_user_event'),
        )

    # Column add on an existing table: create_all never does this — the
    # migration is the only path (project rule).
    if not _table_has_column('server_settings', 'notification_defaults'):
        op.add_column('server_settings',
                      sa.Column('notification_defaults', JSONB, nullable=True))


def downgrade():
    pass

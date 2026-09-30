"""War-room guests (iris-ng, 2026-09-30)

Guest participants of a war room: `war_room_guest` (never a `user` row),
guest authorship columns beside the user FKs on messages, poll votes, tasks
and notes, and `server_settings.portal_public_url` (the invitation link's
base URL). Poll votes become user-OR-guest: `user_id` turns nullable, a
partial unique index stops guest double-votes (NULLs are distinct under the
existing UNIQUE), and a CHECK keeps exactly one voter kind set.

The table itself is created by `db.create_all()` at boot; every op here is
guarded so a re-run is a no-op.

Revision ID: a8c3d5e7f912
Revises: f1c4e7a92b38
Create Date: 2026-09-30

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table
from app.alembic.alembic_utils import _table_has_column
from app.alembic.alembic_utils import index_exists

revision = 'a8c3d5e7f912'
down_revision = 'f1c4e7a92b38'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('war_room_guest'):
        op.create_table(
            'war_room_guest',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('room_id', sa.BigInteger(),
                      sa.ForeignKey('war_room.id', ondelete='CASCADE'), nullable=False),
            sa.Column('email', sa.Text(), nullable=False),
            sa.Column('display_name', sa.Text(), nullable=False),
            sa.Column('organisation', sa.Text(), nullable=True),
            sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
            sa.Column('invited_by', sa.BigInteger(),
                      sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('revoked_at', sa.DateTime(), nullable=True),
            sa.Column('invite_sent_at', sa.DateTime(), nullable=True),
            sa.Column('first_seen_at', sa.DateTime(), nullable=True),
            sa.Column('last_seen_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('room_id', 'email', name='uq_war_room_guest_room_email'),
        )
        op.create_index('ix_war_room_guest_room_id', 'war_room_guest', ['room_id'])

    guest_fk = sa.ForeignKey('war_room_guest.id', ondelete='SET NULL')
    if not _table_has_column('war_room_message', 'guest_id'):
        op.add_column('war_room_message',
                      sa.Column('guest_id', sa.BigInteger(), guest_fk, nullable=True))
    if not _table_has_column('war_room_task', 'created_by_guest_id'):
        op.add_column('war_room_task',
                      sa.Column('created_by_guest_id', sa.BigInteger(),
                                sa.ForeignKey('war_room_guest.id', ondelete='SET NULL'),
                                nullable=True))
    if not _table_has_column('war_room_note', 'created_by_guest_id'):
        op.add_column('war_room_note',
                      sa.Column('created_by_guest_id', sa.BigInteger(),
                                sa.ForeignKey('war_room_guest.id', ondelete='SET NULL'),
                                nullable=True))
    if not _table_has_column('war_room_note', 'updated_by_guest_id'):
        op.add_column('war_room_note',
                      sa.Column('updated_by_guest_id', sa.BigInteger(),
                                sa.ForeignKey('war_room_guest.id', ondelete='SET NULL'),
                                nullable=True))

    # Poll votes: user OR guest.
    if not _table_has_column('war_room_poll_vote', 'guest_id'):
        op.add_column('war_room_poll_vote',
                      sa.Column('guest_id', sa.BigInteger(),
                                sa.ForeignKey('war_room_guest.id', ondelete='CASCADE'),
                                nullable=True))
    op.alter_column('war_room_poll_vote', 'user_id', existing_type=sa.BigInteger(),
                    nullable=True)
    if not index_exists('war_room_poll_vote', 'uq_war_room_poll_vote_option_guest'):
        op.create_index('uq_war_room_poll_vote_option_guest', 'war_room_poll_vote',
                        ['option_id', 'guest_id'], unique=True,
                        postgresql_where=sa.text('guest_id IS NOT NULL'))
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_war_room_poll_vote_voter') THEN "
        "ALTER TABLE war_room_poll_vote ADD CONSTRAINT ck_war_room_poll_vote_voter "
        "CHECK ((user_id IS NOT NULL) OR (guest_id IS NOT NULL)); "
        "END IF; END $$;"
    )

    if not _table_has_column('server_settings', 'portal_public_url'):
        op.add_column('server_settings', sa.Column('portal_public_url', sa.Text(), nullable=True))


def downgrade():
    pass

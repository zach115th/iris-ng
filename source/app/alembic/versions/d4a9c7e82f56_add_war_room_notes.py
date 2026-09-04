"""Room-level notes + one-level folders (iris-ng v2, Phase 6 Notes tab)

Maintainer decision: the Notes tab mirrors the timelines pattern —
read-only linked CASE notes plus read-write ROOM-level notes, organised in
one-level folders like v3. Deleting a folder moves its notes to the root
(SET NULL), never deletes content. No revisions in v1 (autosave,
last-write-wins).

Revision ID: d4a9c7e82f56
Revises: c8b5d3e79f24
Create Date: 2026-08-26

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

revision = 'd4a9c7e82f56'
down_revision = 'c8b5d3e79f24'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('war_room_note_folder'):
        op.create_table(
            'war_room_note_folder',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('room_id', sa.BigInteger(), nullable=False, index=True),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('created_by', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(),
                      server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['room_id'], ['war_room.id'],
                                    ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['created_by'], ['user.id'],
                                    ondelete='SET NULL'),
        )
    if not _has_table('war_room_note'):
        op.create_table(
            'war_room_note',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('room_id', sa.BigInteger(), nullable=False, index=True),
            sa.Column('folder_id', sa.BigInteger(), nullable=True),
            sa.Column('title', sa.Text(), nullable=False),
            sa.Column('content', sa.Text(), nullable=True),
            sa.Column('created_by', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(),
                      server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('updated_by', sa.BigInteger(), nullable=True),
            sa.ForeignKeyConstraint(['room_id'], ['war_room.id'],
                                    ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['folder_id'],
                                    ['war_room_note_folder.id'],
                                    ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['created_by'], ['user.id'],
                                    ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['updated_by'], ['user.id'],
                                    ondelete='SET NULL'),
        )


def downgrade():
    pass

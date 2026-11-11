#  IRIS Source Code
#  Copyright (C) 2026 - iris-ng
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3 of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

"""Tutorials (iris-ng, 2026-11-10)

Creates `tutorial` (this server's own tutorials and its versions of the built-in ones; models.tutorial_vocab) and
`tutorial_progress` (per user: completed, and the running step with what the run captured). The built-in tutorials
are files (resources/tutorials), never rows. Additive only, no data to move.

Guarded: db.create_all() runs before alembic at boot and already creates both tables from the ORM, with their
constraints and the partial unique index; on a database where a table exists without them, they are added here.

Revision ID: e4b9c2a7f5d1
Revises: b7e2c9f4a1d6
Create Date: 2026-11-10
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.alembic.alembic_utils import _has_table
from app.alembic.alembic_utils import index_exists

revision = 'e4b9c2a7f5d1'
down_revision = 'b7e2c9f4a1d6'
branch_labels = None
depends_on = None

_AUDIENCES = ('everyone', 'admins')  # models.tutorial_vocab.AUDIENCES at the time of this revision


def _has_constraint(table, name):
    bind = op.get_bind()
    row = bind.execute(sa.text(
        "SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
        "WHERE t.relname = :t AND c.conname = :n"), {'t': table, 'n': name}).first()
    return row is not None


def upgrade():
    if not _has_table('tutorial'):
        op.create_table(
            'tutorial',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('builtin_key', sa.String(64), nullable=True),
            sa.Column('title', sa.Text(), nullable=False),
            sa.Column('summary', sa.Text(), nullable=True),
            sa.Column('duration', sa.String(24), nullable=True),
            sa.Column('audience', sa.String(16), nullable=False, server_default=sa.text("'everyone'")),
            sa.Column('steps', postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column('published', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
            sa.Column('updated_by', sa.BigInteger(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        )
    if not _has_constraint('tutorial', 'uq_tutorial_builtin_key'):
        op.create_unique_constraint('uq_tutorial_builtin_key', 'tutorial', ['builtin_key'])
    if not _has_constraint('tutorial', 'ck_tutorial_audience'):
        op.create_check_constraint('ck_tutorial_audience', 'tutorial',
                                   "audience IN (%s)" % ', '.join("'%s'" % a for a in _AUDIENCES))

    if not _has_table('tutorial_progress'):
        op.create_table(
            'tutorial_progress',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False,
                      index=True),
            sa.Column('tutorial_ref', sa.String(80), nullable=False),
            sa.Column('running', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('minimized', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('run_seq', sa.Integer(), nullable=False, server_default=sa.text('0')),
            sa.Column('step', sa.Integer(), nullable=False, server_default=sa.text('0')),
            sa.Column('vars', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column('snapshot', postgresql.JSONB(), nullable=True),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
        )
    if not _has_constraint('tutorial_progress', 'uq_tutorial_progress_user_ref'):
        op.create_unique_constraint('uq_tutorial_progress_user_ref', 'tutorial_progress', ['user_id', 'tutorial_ref'])
    if not index_exists('tutorial_progress', 'uq_tutorial_progress_running'):
        op.create_index('uq_tutorial_progress_running', 'tutorial_progress', ['user_id'], unique=True,
                        postgresql_where=sa.text('running'))


def downgrade():
    pass

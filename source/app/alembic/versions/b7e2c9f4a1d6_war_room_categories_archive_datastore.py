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

"""War-room categories, archive and datastore (iris-ng, 2026-11-10)

Creates `war_room_category` (one shared list, names unique ignoring case), `war_room_ds_folder` and
`war_room_ds_file` (a room's own datastore), and adds three columns to `war_room`: `archived_on` + `archived_by`
(archiving is a flag beside the state) and `category_id`. Additive only: no row changes; the existing
`war_room.archived_at` keeps recording when a room was closed.

Guarded: db.create_all() runs before alembic at boot and creates the new TABLES from the ORM (with their unique
index); the COLUMNS on the existing table exist only through this migration.

Revision ID: b7e2c9f4a1d6
Revises: d4c8e1f7a3b9
Create Date: 2026-11-10
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.alembic.alembic_utils import _has_table
from app.alembic.alembic_utils import _table_has_column
from app.alembic.alembic_utils import index_exists

revision = 'b7e2c9f4a1d6'
down_revision = 'd4c8e1f7a3b9'
branch_labels = None
depends_on = None

CATEGORY_NAME_INDEX = 'uq_war_room_category_name_lower'
ROOM_CATEGORY_INDEX = 'ix_war_room_category_id'


def upgrade():
    if not _has_table('war_room_category'):
        op.create_table(
            'war_room_category',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        )
    if not index_exists('war_room_category', CATEGORY_NAME_INDEX):
        op.create_index(CATEGORY_NAME_INDEX, 'war_room_category', [sa.text('lower(name)')], unique=True)

    if not _table_has_column('war_room', 'archived_on'):
        op.add_column('war_room', sa.Column('archived_on', sa.DateTime(), nullable=True))
    if not _table_has_column('war_room', 'archived_by'):
        op.add_column('war_room', sa.Column('archived_by', sa.BigInteger(),
                                            sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True))
    if not _table_has_column('war_room', 'category_id'):
        op.add_column('war_room', sa.Column('category_id', sa.BigInteger(),
                                            sa.ForeignKey('war_room_category.id', ondelete='SET NULL'),
                                            nullable=True))
    if not index_exists('war_room', ROOM_CATEGORY_INDEX):
        op.create_index(ROOM_CATEGORY_INDEX, 'war_room', ['category_id'])

    if not _has_table('war_room_ds_folder'):
        op.create_table(
            'war_room_ds_folder',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('room_id', sa.BigInteger(), sa.ForeignKey('war_room.id', ondelete='CASCADE'), nullable=False,
                      index=True),
            sa.Column('parent_id', sa.BigInteger(), sa.ForeignKey('war_room_ds_folder.id', ondelete='SET NULL'),
                      nullable=True),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
            sa.Column('created_by_guest_id', sa.BigInteger(),
                      sa.ForeignKey('war_room_guest.id', ondelete='SET NULL'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        )
    if not _has_table('war_room_ds_file'):
        op.create_table(
            'war_room_ds_file',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('room_id', sa.BigInteger(), sa.ForeignKey('war_room.id', ondelete='CASCADE'), nullable=False,
                      index=True),
            sa.Column('folder_id', sa.BigInteger(), sa.ForeignKey('war_room_ds_folder.id', ondelete='SET NULL'),
                      nullable=True, index=True),
            sa.Column('file_uuid', postgresql.UUID(as_uuid=True), nullable=False,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('filename', sa.Text(), nullable=False),
            sa.Column('mime_type', sa.String(128), nullable=False),
            sa.Column('size', sa.BigInteger(), nullable=False),
            sa.Column('sha256', sa.String(64), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('tags', sa.Text(), nullable=True),
            sa.Column('uploaded_by', sa.BigInteger(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
            sa.Column('uploaded_by_guest_id', sa.BigInteger(),
                      sa.ForeignKey('war_room_guest.id', ondelete='SET NULL'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('updated_by', sa.BigInteger(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
            sa.Column('updated_by_guest_id', sa.BigInteger(),
                      sa.ForeignKey('war_room_guest.id', ondelete='SET NULL'), nullable=True),
        )


def downgrade():
    pass

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

"""The war-room Scope's staging inbox and Assets Manager attachments (iris-ng, 2026-11-08)

Creates `war_room_staged_object` (an asset or IOC waiting in a room's staging inbox with the cases it is
proposed for) and `war_room_registry_asset` (a customer-registry asset put in a room's scope, with or without
one of its cases). Additive only; no data to move.

Guarded: db.create_all() runs before alembic at boot and already creates the tables from the ORM; on a database
where a table exists without its constraint, the constraint is added here.

Revision ID: f3b8d6a1c9e4
Revises: e1d7b4a9c3f6
Create Date: 2026-11-08
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.alembic.alembic_utils import _has_table
from app.models import asset_flag_vocab as af

revision = 'f3b8d6a1c9e4'
down_revision = 'e1d7b4a9c3f6'
branch_labels = None
depends_on = None


def _constraint_exists(name):
    bind = op.get_bind()
    return bind.execute(sa.text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {'n': name}).first() is not None


def upgrade():
    if not _has_table('war_room_staged_object'):
        op.create_table(
            'war_room_staged_object',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('room_id', sa.BigInteger(), sa.ForeignKey('war_room.id', ondelete='CASCADE'), nullable=False,
                      index=True),
            sa.Column('kind', sa.String(8), nullable=False),
            sa.Column('payload', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column('target_case_ids', postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('user.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
            sa.Column('updated_by', sa.BigInteger(), sa.ForeignKey('user.id'), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.CheckConstraint(af.sql_in('kind', af.SCOPE_STAGED_KINDS), name='ck_war_room_staged_object_kind'),
        )
    elif not _constraint_exists('ck_war_room_staged_object_kind'):
        op.create_check_constraint('ck_war_room_staged_object_kind', 'war_room_staged_object',
                                   af.sql_in('kind', af.SCOPE_STAGED_KINDS))
    if not _has_table('war_room_registry_asset'):
        op.create_table(
            'war_room_registry_asset',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('room_id', sa.BigInteger(), sa.ForeignKey('war_room.id', ondelete='CASCADE'), nullable=False,
                      index=True),
            sa.Column('customer_asset_id', sa.BigInteger(), sa.ForeignKey('customer_asset.id', ondelete='CASCADE'),
                      nullable=False, index=True),
            sa.Column('case_id', sa.BigInteger(), sa.ForeignKey('cases.case_id', ondelete='SET NULL'), nullable=True),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('added_by', sa.BigInteger(), sa.ForeignKey('user.id'), nullable=True),
            sa.Column('added_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
            sa.UniqueConstraint('room_id', 'customer_asset_id', name='uq_war_room_registry_asset'),
        )
    elif not _constraint_exists('uq_war_room_registry_asset'):
        op.create_unique_constraint('uq_war_room_registry_asset', 'war_room_registry_asset',
                                    ['room_id', 'customer_asset_id'])


def downgrade():
    pass

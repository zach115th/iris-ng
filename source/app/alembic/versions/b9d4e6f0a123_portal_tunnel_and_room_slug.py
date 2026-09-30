"""Guest portal tunnel settings + room slug (iris-ng, 2026-09-30)

`war_room.slug` (unique when set; the guest portal's friendly path) and the
tunnel settings the portal agent reads: `server_settings.portal_tunnel_mode`
(quick | named), the write-only `portal_tunnel_token`, and the agent's last
reported `portal_tunnel_status` (JSONB). Every op is guarded.

Revision ID: b9d4e6f0a123
Revises: a8c3d5e7f912
Create Date: 2026-09-30

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from app.alembic.alembic_utils import _table_has_column
from app.alembic.alembic_utils import index_exists

revision = 'b9d4e6f0a123'
down_revision = 'a8c3d5e7f912'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('war_room', 'slug'):
        op.add_column('war_room', sa.Column('slug', sa.Text(), nullable=True))
    if not index_exists('war_room', 'uq_war_room_slug'):
        op.create_index('uq_war_room_slug', 'war_room', ['slug'], unique=True)
    if not _table_has_column('server_settings', 'portal_tunnel_mode'):
        op.add_column('server_settings', sa.Column('portal_tunnel_mode', sa.String(16),
                                                   nullable=False, server_default=sa.text("'quick'")))
    if not _table_has_column('server_settings', 'portal_tunnel_token'):
        op.add_column('server_settings', sa.Column('portal_tunnel_token', sa.Text(), nullable=True))
    if not _table_has_column('server_settings', 'portal_tunnel_status'):
        op.add_column('server_settings', sa.Column('portal_tunnel_status', JSONB, nullable=True))


def downgrade():
    pass

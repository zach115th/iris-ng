"""Per-attachment note on room case links (iris-ng v2, Phase 6 Cases tab)

v3 rows carry an attachment note ("Primary case for this room") — a
property of the case-in-this-room relationship, so it lives on the link.

Revision ID: e5b8d4f97a63
Revises: d4a9c7e82f56
Create Date: 2026-08-26

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

revision = 'e5b8d4f97a63'
down_revision = 'd4a9c7e82f56'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('war_room_case_link', 'note'):
        op.add_column('war_room_case_link',
                      sa.Column('note', sa.Text(), nullable=True))


def downgrade():
    pass

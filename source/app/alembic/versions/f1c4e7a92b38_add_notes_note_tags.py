"""Tags on case notes (iris-ng #129)

`notes.note_tags` is a comma-separated text column, the same storage every
other case object uses (ioc_tags, asset_tags, task_tags, event_tags). Every
tag is also registered in `tags` by the note schema so autocomplete offers it.

Revision ID: f1c4e7a92b38
Revises: d6a2f8c47b19
Create Date: 2026-09-27

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

revision = 'f1c4e7a92b38'
down_revision = 'd6a2f8c47b19'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('notes', 'note_tags'):
        op.add_column('notes', sa.Column('note_tags', sa.Text(), nullable=True))


def downgrade():
    pass

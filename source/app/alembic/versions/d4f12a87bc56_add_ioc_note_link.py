"""add ioc_note_link table

Provenance link from an Ioc row to one or more Notes the analyst (or AI
extractor) sourced it from. Many-to-many — a single IOC can be cited by
several notes, and a note can yield multiple IOCs. Used by the AI IOC
extractor to record where each suggestion originated, surfaced on the
Edit IOC modal as a "Linked Notes" section, and reusable later for
analyst search, LLM grounding, and the pinned mind-map / dual-timeline
features.

Revision ID: d4f12a87bc56
Revises: c3f1b87a902d
Create Date: 2026-04-29 16:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

# revision identifiers, used by Alembic.
revision = 'd4f12a87bc56'
down_revision = 'c3f1b87a902d'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('ioc_note_link'):
        op.create_table(
            'ioc_note_link',
            sa.Column('id', sa.BigInteger(), nullable=False),
            sa.Column('ioc_id', sa.BigInteger(), nullable=False),
            sa.Column('note_id', sa.BigInteger(), nullable=False),
            sa.Column('case_id', sa.BigInteger(), nullable=False),
            sa.Column('source', sa.String(32), nullable=False, server_default='ai_extractor'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(['ioc_id'], ['ioc.ioc_id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['note_id'], ['notes.note_id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['case_id'], ['cases.case_id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('ioc_id', 'note_id', name='uq_ioc_note_link_pair'),
        )
        op.create_index('ix_ioc_note_link_ioc_id', 'ioc_note_link', ['ioc_id'])
        op.create_index('ix_ioc_note_link_note_id', 'ioc_note_link', ['note_id'])
        op.create_index('ix_ioc_note_link_case_id', 'ioc_note_link', ['case_id'])


def downgrade():
    op.drop_index('ix_ioc_note_link_case_id', table_name='ioc_note_link')
    op.drop_index('ix_ioc_note_link_note_id', table_name='ioc_note_link')
    op.drop_index('ix_ioc_note_link_ioc_id', table_name='ioc_note_link')
    op.drop_table('ioc_note_link')

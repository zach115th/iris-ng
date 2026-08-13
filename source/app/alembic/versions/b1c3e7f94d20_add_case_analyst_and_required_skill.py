"""add case_analyst_link + case_required_skill tables

iris-next: two join tables that power per-case ad-hoc team assembly.
  case_analyst_link  — analysts assigned to a case (lead / analyst role)
  case_required_skill — skills the case needs (used by the team-suggestion scorer)

Guarded with _has_table because db.create_all() runs from ORM models BEFORE
alembic on fresh boot. Constraints live on the ORM __table_args__ (fork rule).

Revision ID: b1c3e7f94d20
Revises: a3f7d2c19b4e
Create Date: 2026-06-26 18:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

revision = 'b1c3e7f94d20'
down_revision = 'a3f7d2c19b4e'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('case_analyst_link'):
        op.create_table(
            'case_analyst_link',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('case_id', sa.BigInteger(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('role', sa.String(length=20), nullable=False,
                      server_default='analyst'),
            sa.ForeignKeyConstraint(['case_id'], ['cases.case_id'],
                                    ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'],
                                    ondelete='CASCADE'),
            sa.UniqueConstraint('case_id', 'user_id', name='uq_case_analyst'),
        )

    if not _has_table('case_required_skill'):
        op.create_table(
            'case_required_skill',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('case_id', sa.BigInteger(), nullable=False),
            sa.Column('skill_id', sa.BigInteger(), nullable=False),
            sa.ForeignKeyConstraint(['case_id'], ['cases.case_id'],
                                    ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['skill_id'], ['skill.id'],
                                    ondelete='CASCADE'),
            sa.UniqueConstraint('case_id', 'skill_id',
                                name='uq_case_required_skill'),
        )


def downgrade():
    op.drop_table('case_required_skill')
    op.drop_table('case_analyst_link')

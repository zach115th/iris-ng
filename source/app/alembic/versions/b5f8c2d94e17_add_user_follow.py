"""Add user_follow (iris-ng v2, Phase 5)

Following: a user stars a case or alert; the home page's following feed
reads activity on followed objects. No FK on object_id — case and alert ids
live in different tables; rows for deleted objects are skipped at read time.

CHECK/UNIQUE constraints are declared on the ORM __table_args__ as well —
db.create_all() runs before alembic on a fresh install and the guarded
create below is skipped.

Revision ID: b5f8c2d94e17
Revises: a9d1e83f47c2
Create Date: 2026-08-25

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table

revision = 'b5f8c2d94e17'
down_revision = 'a9d1e83f47c2'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('user_follow'):
        op.create_table(
            'user_follow',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('object_type', sa.String(16), nullable=False),
            sa.Column('object_id', sa.BigInteger(), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'),
                      nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
            sa.UniqueConstraint('user_id', 'object_type', 'object_id',
                                name='uq_user_follow_user_object'),
            sa.CheckConstraint("object_type IN ('case', 'alert')",
                               name='ck_user_follow_object_type'),
        )


def downgrade():
    pass

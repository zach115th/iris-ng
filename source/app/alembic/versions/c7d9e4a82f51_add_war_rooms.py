"""Add war rooms (iris-ng v2, Phase 6)

War rooms slim v1: room + members (lead/responder/observer) + attached cases
+ flat chat + versioned SitReps + MISP-push link. Seven tables in one
migration — the whole phase's schema.

CHECK/UNIQUE constraints are declared on the ORM __table_args__ as well —
db.create_all() runs before alembic on a fresh install and the guarded
creates below are skipped.

Revision ID: c7d9e4a82f51
Revises: b5f8c2d94e17
Create Date: 2026-08-26

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from app.alembic.alembic_utils import _has_table

revision = 'c7d9e4a82f51'
down_revision = 'b5f8c2d94e17'
branch_labels = None
depends_on = None


def upgrade():
    if not _has_table('war_room'):
        op.create_table(
            'war_room',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('room_uuid', UUID(as_uuid=True),
                      server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('summary', sa.Text(), nullable=True),
            sa.Column('status', sa.String(16), nullable=False,
                      server_default=sa.text("'active'")),
            sa.Column('source_cluster_id', sa.String(64), nullable=True),
            sa.Column('campaign_tag', sa.Text(), nullable=True),
            sa.Column('created_by', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(),
                      server_default=sa.text('now()'), nullable=False),
            sa.Column('archived_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['created_by'], ['user.id'], ondelete='SET NULL'),
            sa.CheckConstraint("status IN ('active', 'archived')",
                               name='ck_war_room_status'),
        )

    if not _has_table('war_room_member'):
        op.create_table(
            'war_room_member',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('room_id', sa.BigInteger(), nullable=False, index=True),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('role', sa.String(16), nullable=False),
            sa.Column('added_at', sa.DateTime(),
                      server_default=sa.text('now()'), nullable=False),
            sa.Column('added_by', sa.BigInteger(), nullable=True),
            sa.ForeignKeyConstraint(['room_id'], ['war_room.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['added_by'], ['user.id'], ondelete='SET NULL'),
            sa.UniqueConstraint('room_id', 'user_id',
                                name='uq_war_room_member_room_user'),
            sa.CheckConstraint("role IN ('lead', 'responder', 'observer')",
                               name='ck_war_room_member_role'),
        )

    if not _has_table('war_room_case_link'):
        op.create_table(
            'war_room_case_link',
            sa.Column('room_id', sa.BigInteger(), primary_key=True),
            sa.Column('case_id', sa.BigInteger(), primary_key=True),
            sa.Column('added_at', sa.DateTime(),
                      server_default=sa.text('now()'), nullable=False),
            sa.Column('added_by', sa.BigInteger(), nullable=True),
            sa.ForeignKeyConstraint(['room_id'], ['war_room.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['case_id'], ['cases.case_id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['added_by'], ['user.id'], ondelete='SET NULL'),
        )

    if not _has_table('war_room_message'):
        op.create_table(
            'war_room_message',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('room_id', sa.BigInteger(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=True),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(),
                      server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['room_id'], ['war_room.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='SET NULL'),
        )
        op.create_index('idx_war_room_message_room_id_id', 'war_room_message',
                        ['room_id', 'id'])

    if not _has_table('sitrep'):
        op.create_table(
            'sitrep',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('room_id', sa.BigInteger(), nullable=False, index=True),
            sa.Column('title', sa.Text(), nullable=False),
            sa.Column('content', sa.Text(), nullable=True),
            sa.Column('status', sa.String(16), nullable=False,
                      server_default=sa.text("'draft'")),
            sa.Column('created_by', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.DateTime(),
                      server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('published_at', sa.DateTime(), nullable=True),
            sa.Column('published_by', sa.BigInteger(), nullable=True),
            sa.ForeignKeyConstraint(['room_id'], ['war_room.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['created_by'], ['user.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['published_by'], ['user.id'], ondelete='SET NULL'),
            sa.CheckConstraint("status IN ('draft', 'published')",
                               name='ck_sitrep_status'),
        )

    if not _has_table('sitrep_revision'):
        op.create_table(
            'sitrep_revision',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('sitrep_id', sa.BigInteger(), nullable=False, index=True),
            sa.Column('revision_number', sa.Integer(), nullable=False),
            sa.Column('title', sa.Text(), nullable=True),
            sa.Column('content', sa.Text(), nullable=True),
            sa.Column('user_id', sa.BigInteger(), nullable=True),
            sa.Column('revision_timestamp', sa.DateTime(),
                      server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['sitrep_id'], ['sitrep.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='SET NULL'),
        )

    if not _has_table('war_room_misp_link'):
        op.create_table(
            'war_room_misp_link',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('room_id', sa.BigInteger(), nullable=False),
            sa.Column('misp_event_id', sa.Integer(), nullable=False),
            sa.Column('misp_event_uuid', sa.String(80), nullable=True),
            sa.Column('pushed_at', sa.DateTime(),
                      server_default=sa.text('now()'), nullable=False),
            sa.Column('pushed_by_id', sa.BigInteger(), nullable=True),
            sa.ForeignKeyConstraint(['room_id'], ['war_room.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['pushed_by_id'], ['user.id'], ondelete='SET NULL'),
            sa.UniqueConstraint('room_id', name='uq_war_room_misp_link_room'),
        )


def downgrade():
    pass

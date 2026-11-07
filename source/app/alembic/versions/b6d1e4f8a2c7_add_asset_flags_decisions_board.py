"""Asset flags, war-room decisions and the war-room Board (iris-ng, 2026-11-07)

Creates `asset_flag` (the flags an administrator defines: name, colour, icon,
kind status / done / exception, reason / decision requirements, order),
`case_asset_flag` (a flag set on a case asset, with its reason and the war-room
decision it cites) and `case_asset_flag_change` (their history);
`war_room_decision` (a room's decision register, D-<n> per room) with
`war_room_decision_approver` (approvers and verdicts), `war_room_decision_case`
/ `war_room_decision_asset` (what a decision applies to) and
`war_room_decision_event` (the trail the room stream reads); and
`war_room_board` (a room's Board layout). Additive only.

Guarded: db.create_all() runs before alembic at boot and already creates the
tables, constraints and indexes from the ORM (app/models/models.py); this
migration is the chain's record and covers installs where that did not
happen. The CHECK vocabularies come from app.models.asset_flag_vocab, the same
tuples the ORM and the API use.

Revision ID: b6d1e4f8a2c7
Revises: 58207f87c9e2
Create Date: 2026-11-07
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.alembic.alembic_utils import _has_table
from app.alembic.alembic_utils import index_exists
from app.models import asset_flag_vocab as af

revision = 'b6d1e4f8a2c7'
down_revision = '58207f87c9e2'
branch_labels = None
depends_on = None


def _user_fk(name):
    return sa.Column(name, sa.BigInteger(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)


def _asset_flag():
    op.create_table(
        'asset_flag',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('color', sa.String(16), nullable=False, server_default=sa.text("'slate'")),
        sa.Column('icon', sa.String(32), nullable=False, server_default=sa.text("'flag'")),
        sa.Column('kind', sa.String(16), nullable=False, server_default=sa.text("'status'")),
        sa.Column('requires_reason', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('requires_decision', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        _user_fk('created_by_id'),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        _user_fk('updated_by_id'),
        sa.CheckConstraint(af.sql_in('color', af.COLORS), name='ck_asset_flag_color'),
        sa.CheckConstraint(af.sql_in('icon', af.ICONS), name='ck_asset_flag_icon'),
        sa.CheckConstraint(af.sql_in('kind', af.KINDS), name='ck_asset_flag_kind'),
    )


def _decision():
    op.create_table(
        'war_room_decision',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('room_id', sa.BigInteger(), sa.ForeignKey('war_room.id', ondelete='CASCADE'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(256), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default=sa.text("'proposed'")),
        _user_fk('owner_id'),
        sa.Column('target_at', sa.DateTime(), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('implemented_at', sa.DateTime(), nullable=True),
        _user_fk('implemented_by_id'),
        sa.Column('supersedes_id', sa.BigInteger(), sa.ForeignKey('war_room_decision.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('chat_message_id', sa.BigInteger(), sa.ForeignKey('war_room_message.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        _user_fk('created_by_id'),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        _user_fk('updated_by_id'),
        sa.UniqueConstraint('room_id', 'number', name='uq_war_room_decision_number'),
        sa.CheckConstraint(af.sql_in('status', af.DECISION_STATUSES), name='ck_war_room_decision_status'),
    )


def _case_asset_flag():
    op.create_table(
        'case_asset_flag',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('case_id', sa.BigInteger(), sa.ForeignKey('cases.case_id', ondelete='CASCADE'), nullable=False),
        sa.Column('asset_id', sa.BigInteger(), sa.ForeignKey('case_assets.asset_id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('flag_id', sa.BigInteger(), sa.ForeignKey('asset_flag.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('decision_id', sa.BigInteger(), sa.ForeignKey('war_room_decision.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('set_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        _user_fk('set_by_id'),
        sa.UniqueConstraint('asset_id', 'flag_id', name='uq_case_asset_flag'),
    )


def _flag_change():
    op.create_table(
        'case_asset_flag_change',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('case_id', sa.BigInteger(), sa.ForeignKey('cases.case_id', ondelete='CASCADE'), nullable=False),
        sa.Column('asset_id', sa.BigInteger(), sa.ForeignKey('case_assets.asset_id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('flag_id', sa.BigInteger(), sa.ForeignKey('asset_flag.id', ondelete='SET NULL'), nullable=True),
        sa.Column('flag_name', sa.String(64), nullable=False),
        sa.Column('action', sa.String(16), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('decision_id', sa.BigInteger(), nullable=True),
        sa.Column('decision_ref', sa.String(32), nullable=True),
        _user_fk('changed_by'),
        sa.Column('changed_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(af.sql_in('action', af.FLAG_ACTIONS), name='ck_case_asset_flag_change_action'),
    )


def _approver():
    op.create_table(
        'war_room_decision_approver',
        sa.Column('decision_id', sa.BigInteger(), sa.ForeignKey('war_room_decision.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('verdict', sa.String(16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column('voted_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint(af.sql_in('verdict', af.VERDICTS), name='ck_war_room_decision_approver_verdict'),
    )


def _decision_case():
    op.create_table(
        'war_room_decision_case',
        sa.Column('decision_id', sa.BigInteger(), sa.ForeignKey('war_room_decision.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('case_id', sa.BigInteger(), sa.ForeignKey('cases.case_id', ondelete='CASCADE'), primary_key=True),
    )


def _decision_asset():
    op.create_table(
        'war_room_decision_asset',
        sa.Column('decision_id', sa.BigInteger(), sa.ForeignKey('war_room_decision.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('asset_id', sa.BigInteger(), sa.ForeignKey('case_assets.asset_id', ondelete='CASCADE'),
                  primary_key=True),
    )


def _decision_event():
    op.create_table(
        'war_room_decision_event',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('decision_id', sa.BigInteger(), sa.ForeignKey('war_room_decision.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('room_id', sa.BigInteger(), sa.ForeignKey('war_room.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action', sa.String(24), nullable=False),
        sa.Column('detail', sa.Text(), nullable=True),
        _user_fk('user_id'),
        sa.Column('at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(af.sql_in('action', af.DECISION_EVENTS), name='ck_war_room_decision_event_action'),
    )


def _board():
    op.create_table(
        'war_room_board',
        sa.Column('room_id', sa.BigInteger(), sa.ForeignKey('war_room.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('widgets', postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        _user_fk('updated_by_id'),
    )


TABLES = (('asset_flag', _asset_flag), ('war_room_decision', _decision), ('case_asset_flag', _case_asset_flag),
          ('case_asset_flag_change', _flag_change), ('war_room_decision_approver', _approver),
          ('war_room_decision_case', _decision_case), ('war_room_decision_asset', _decision_asset),
          ('war_room_decision_event', _decision_event), ('war_room_board', _board))

# name: (table, columns, unique)
INDEXES = {
    'uq_asset_flag_name': ('asset_flag', [sa.text('lower(name)')], True),
    'ix_case_asset_flag_case_id': ('case_asset_flag', ['case_id'], False),
    'ix_case_asset_flag_asset_id': ('case_asset_flag', ['asset_id'], False),
    'ix_case_asset_flag_flag_id': ('case_asset_flag', ['flag_id'], False),
    'ix_case_asset_flag_decision_id': ('case_asset_flag', ['decision_id'], False),
    'ix_case_asset_flag_change_case_id': ('case_asset_flag_change', ['case_id'], False),
    'ix_case_asset_flag_change_asset_id': ('case_asset_flag_change', ['asset_id'], False),
    'ix_war_room_decision_room_id': ('war_room_decision', ['room_id'], False),
    'ix_war_room_decision_chat_message_id': ('war_room_decision', ['chat_message_id'], False),
    'ix_war_room_decision_case_case_id': ('war_room_decision_case', ['case_id'], False),
    'ix_war_room_decision_asset_asset_id': ('war_room_decision_asset', ['asset_id'], False),
    'ix_war_room_decision_event_decision_id': ('war_room_decision_event', ['decision_id'], False),
    'ix_war_room_decision_event_room_id': ('war_room_decision_event', ['room_id'], False),
}


def upgrade():
    for table, create in TABLES:
        if not _has_table(table):
            create()
    for name, (table, columns, unique) in INDEXES.items():
        if _has_table(table) and not index_exists(table, name):
            op.create_index(name, table, columns, unique=unique)


def downgrade():
    pass

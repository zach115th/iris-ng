"""Verified executive summary: run / step / flag tables + the verifier switch (iris-ng, 2026-10-09)

Creates `case_summary_run` (one row per pass, hung off the `case_summary`
artifact), `case_summary_step` (the audit trail: provider, backend id + label,
model, prompt id, cached, outcome, timestamps per pipeline step) and
`case_summary_flag` (deterministic-check and verifier findings asked to the
analyst as review questions, with the options offered and the answer given),
plus `server_settings.ai_summary_verify` (NULL = on). Additive only: the
summary text stays in `case_ai_artifact`, every legacy summary reads as
`draft`. Guarded - db.create_all() runs before alembic at boot and already
creates the tables, constraints and indexes from the ORM; this migration
exists for installs where that did not happen and as the chain's record. The
`_settle_*` steps bring a database that booted an earlier, unreleased shape of
these tables (2026-10-09, the same day) to the released one.

Revision ID: c4d9a2e7f1b3
Revises: b8e3f1a7c2d5
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from app.alembic.alembic_utils import _has_table
from app.alembic.alembic_utils import _table_has_column
from app.alembic.alembic_utils import index_exists

revision = 'c4d9a2e7f1b3'
down_revision = 'b8e3f1a7c2d5'
branch_labels = None
depends_on = None

VERIFIER_STATES = ('verified', 'skipped', 'verifier_failed', 'verifier_unavailable', 'disabled', 'carried')
PASS_KINDS = ('draft', 'revise', 'answers')
STEP_NAMES = ('specialist:notes', 'specialist:timeline', 'specialist:iocs', 'specialist:assets', 'specialist:evidence',
              'writer', 'checks', 'verifier:claims', 'verifier:document', 'questions', 'apply')
FLAG_STATES = ('open', 'answered')


def _in(column, values):
    return "%s IN (%s)" % (column, ", ".join("'%s'" % v for v in values))


CHECKS = {
    # name: (table, expression, a token every up-to-date definition contains)
    'ck_case_summary_run_pass_no': ('case_summary_run', "pass_no >= 1", ">="),
    'ck_case_summary_run_pass_kind': ('case_summary_run', _in('pass_kind', PASS_KINDS), 'answers'),
    'ck_case_summary_run_verifier_status': ('case_summary_run', _in('verifier_status', VERIFIER_STATES), 'carried'),
    'ck_case_summary_step_step': ('case_summary_step', _in('step', STEP_NAMES), 'apply'),
    'ck_case_summary_flag_status': ('case_summary_flag', _in('status', FLAG_STATES), 'answered'),
}


def _constraint_def(name):
    return op.get_bind().execute(text(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"), {"n": name}).scalar()


def _settle_checks():
    """Recreate every CHECK whose current definition predates the released
    vocabulary; create the ones a pre-release table lacks. Order matters for
    the flag status: drop the stale constraint, move the rows to the new
    vocabulary (_settle_rows), then create the new one."""
    todo = []
    for name, (table, expr, token) in CHECKS.items():
        if not _has_table(table):
            continue
        current = _constraint_def(name)
        if current is None:
            if name == 'ck_case_summary_run_pass_kind' and not _table_has_column(table, 'pass_kind'):
                continue
            todo.append((name, table, expr))
        elif token not in current:
            op.drop_constraint(name, table, type_='check')
            todo.append((name, table, expr))
    _settle_rows()
    for name, table, expr in todo:
        op.create_check_constraint(name, table, expr)


def _settle_columns():
    """Columns the pre-release shape lacked / carried: add the question and
    answer columns, the pass kind, the answers payload; drop the "final" label
    (replaced by the answered questions) and the free-text resolution."""
    if _has_table('case_summary_run'):
        if not _table_has_column('case_summary_run', 'pass_kind'):
            op.add_column('case_summary_run', sa.Column('pass_kind', sa.String(16), nullable=False,
                                                        server_default=text("'draft'")))
        if not _table_has_column('case_summary_run', 'answers_json'):
            op.add_column('case_summary_run', sa.Column('answers_json', sa.Text(), nullable=True))
        for old in ('final_at', 'final_by_id'):
            if _table_has_column('case_summary_run', old):
                op.drop_column('case_summary_run', old)
    if _has_table('case_summary_flag'):
        if _table_has_column('case_summary_flag', 'resolved_by_id') and not _table_has_column('case_summary_flag', 'answered_by_id'):
            op.alter_column('case_summary_flag', 'resolved_by_id', new_column_name='answered_by_id')
        if _table_has_column('case_summary_flag', 'resolved_at') and not _table_has_column('case_summary_flag', 'answered_at'):
            op.alter_column('case_summary_flag', 'resolved_at', new_column_name='answered_at')
        if _table_has_column('case_summary_flag', 'resolution_reason'):
            op.drop_column('case_summary_flag', 'resolution_reason')
        for col in ('question', 'options_json', 'answer_json'):
            if not _table_has_column('case_summary_flag', col):
                op.add_column('case_summary_flag', sa.Column(col, sa.Text(), nullable=True))


def _settle_rows():
    """Rows of the pre-release vocabulary: resolved / dismissed were answers.
    Runs AFTER _settle_checks, which admits 'answered'."""
    if _has_table('case_summary_flag'):
        op.get_bind().execute(text(
            "UPDATE case_summary_flag SET status = 'answered' WHERE status IN ('resolved', 'dismissed')"))
    if _has_table('case_summary_run') and _table_has_column('case_summary_run', 'pass_kind'):
        # pre-release runs carried no kind: pass 2 was always the automatic revise
        op.get_bind().execute(text("UPDATE case_summary_run SET pass_kind = 'revise' WHERE pass_no = 2 AND pass_kind = 'draft'"))


def upgrade():
    if not _has_table('case_summary_run'):
        op.create_table(
            'case_summary_run',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('case_id', sa.Integer(), sa.ForeignKey('cases.case_id', ondelete='CASCADE'), nullable=False),
            sa.Column('artifact_id', sa.BigInteger(), sa.ForeignKey('case_ai_artifact.id', ondelete='CASCADE'),
                      nullable=False, unique=True),
            sa.Column('pass_no', sa.Integer(), nullable=False, server_default=text('1')),
            sa.Column('pass_kind', sa.String(16), nullable=False, server_default=text("'draft'")),
            sa.Column('parent_run_id', sa.BigInteger(), sa.ForeignKey('case_summary_run.id', ondelete='SET NULL'),
                      nullable=True),
            sa.Column('input_hash', sa.String(64), nullable=False),
            sa.Column('pipeline_version', sa.String(32), nullable=False),
            sa.Column('claims_json', sa.Text(), nullable=False),
            sa.Column('writer_meta_json', sa.Text(), nullable=True),
            sa.Column('checks_json', sa.Text(), nullable=True),
            sa.Column('verifier_status', sa.String(24), nullable=False, server_default=text("'skipped'")),
            sa.Column('verifier_json', sa.Text(), nullable=True),
            sa.Column('answers_json', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('now()')),
            sa.CheckConstraint(CHECKS['ck_case_summary_run_pass_no'][1], name='ck_case_summary_run_pass_no'),
            sa.CheckConstraint(CHECKS['ck_case_summary_run_pass_kind'][1], name='ck_case_summary_run_pass_kind'),
            sa.CheckConstraint(CHECKS['ck_case_summary_run_verifier_status'][1], name='ck_case_summary_run_verifier_status'),
        )
    if not index_exists('case_summary_run', 'ix_case_summary_run_case_hash'):
        op.create_index('ix_case_summary_run_case_hash', 'case_summary_run', ['case_id', 'input_hash'])

    if not _has_table('case_summary_step'):
        op.create_table(
            'case_summary_step',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('run_id', sa.BigInteger(), sa.ForeignKey('case_summary_run.id', ondelete='CASCADE'),
                      nullable=False),
            sa.Column('step', sa.String(32), nullable=False),
            sa.Column('provider', sa.String(32), nullable=True),
            sa.Column('backend_id', sa.BigInteger(), nullable=True),
            sa.Column('backend_label', sa.Text(), nullable=True),
            sa.Column('model', sa.Text(), nullable=True),
            sa.Column('prompt_id', sa.String(96), nullable=True),
            sa.Column('artifact_id', sa.BigInteger(), sa.ForeignKey('case_ai_artifact.id', ondelete='SET NULL'),
                      nullable=True),
            sa.Column('cached', sa.Boolean(), nullable=False, server_default=text('false')),
            sa.Column('outcome', sa.String(16), nullable=False, server_default=text("'ok'")),
            sa.Column('error', sa.Text(), nullable=True),
            sa.Column('usage_json', sa.Text(), nullable=True),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('finished_at', sa.DateTime(), nullable=True),
            sa.CheckConstraint(CHECKS['ck_case_summary_step_step'][1], name='ck_case_summary_step_step'),
            sa.CheckConstraint("outcome IN ('ok', 'failed', 'skipped')", name='ck_case_summary_step_outcome'),
        )
    if not index_exists('case_summary_step', 'ix_case_summary_step_run_id'):
        op.create_index('ix_case_summary_step_run_id', 'case_summary_step', ['run_id'])

    if not _has_table('case_summary_flag'):
        op.create_table(
            'case_summary_flag',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('run_id', sa.BigInteger(), sa.ForeignKey('case_summary_run.id', ondelete='CASCADE'),
                      nullable=False),
            sa.Column('claim_id', sa.String(16), nullable=True),
            sa.Column('code', sa.String(48), nullable=False),
            sa.Column('severity', sa.String(8), nullable=False),
            sa.Column('source', sa.String(16), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('detail_json', sa.Text(), nullable=True),
            sa.Column('source_refs_json', sa.Text(), nullable=True),
            sa.Column('question', sa.Text(), nullable=True),
            sa.Column('options_json', sa.Text(), nullable=True),
            sa.Column('status', sa.String(16), nullable=False, server_default=text("'open'")),
            sa.Column('answer_json', sa.Text(), nullable=True),
            sa.Column('answered_by_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
            sa.Column('answered_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('now()')),
            sa.CheckConstraint("severity IN ('high', 'medium', 'low')", name='ck_case_summary_flag_severity'),
            sa.CheckConstraint("source IN ('checks', 'verifier', 'pipeline')", name='ck_case_summary_flag_source'),
            sa.CheckConstraint(CHECKS['ck_case_summary_flag_status'][1], name='ck_case_summary_flag_status'),
        )
    if not index_exists('case_summary_flag', 'ix_case_summary_flag_run_status_sev'):
        op.create_index('ix_case_summary_flag_run_status_sev', 'case_summary_flag', ['run_id', 'status', 'severity'])

    _settle_columns()   # add / drop / rename columns first (the pass_kind CHECK needs its column)
    _settle_checks()    # drop stale CHECKs, move the rows ('resolved' -> 'answered'), create the new CHECKs

    # Settings > AI: run the LLM verifier on executive summaries. NULL = on, so
    # every existing install keeps verifying until an admin switches it off.
    if not _table_has_column('server_settings', 'ai_summary_verify'):
        op.add_column('server_settings', sa.Column('ai_summary_verify', sa.Boolean(), nullable=True))


def downgrade():
    pass

"""Add cases_events.event_verdict (analyst triage verdict)

Replaces the "Add to summary" / "Display in graph" checkbox pair with a single
verdict that drives both flags and the card colour. The column is required
rather than derived because 'to_be_determined' and 'true_positive' carry the
same boolean state.

Revision ID: b8f4e2a71c93
Revises: d1a7c93f5e64
Create Date: 2026-08-24
"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

revision = 'b8f4e2a71c93'
down_revision = 'd1a7c93f5e64'
branch_labels = None
depends_on = None

_VALID = ('to_be_determined', 'true_positive', 'false_positive')
_COLORS = {
    'to_be_determined': '#8B5CF699',
    'true_positive': '#31CE3699',
    'false_positive': '#F2596199',
}


def upgrade():
    if not _table_has_column('cases_events', 'event_verdict'):
        op.add_column(
            'cases_events',
            sa.Column('event_verdict', sa.Text(), nullable=True,
                      server_default=sa.text("'to_be_determined'"))
        )

    conn = op.get_bind()

    # Backfill. Only an explicit both-off becomes false positive -- that is the
    # one state an analyst could previously express to mean "keep this out of
    # the summary and the graph". Everything else, including mixed states and
    # the NULLs left by events created before either flag was used, becomes
    # to-be-determined, which is neutral and leaves the flags where they are.
    conn.execute(sa.text("""
        UPDATE cases_events
           SET event_verdict = CASE
                 WHEN event_in_summary IS FALSE AND event_in_graph IS FALSE
                      THEN 'false_positive'
                 ELSE 'to_be_determined'
               END
         WHERE event_verdict IS NULL
    """))

    # Bring the flags and the colour into line with the verdict, so the
    # invariant "verdict determines all three" holds from the first boot.
    # Rows that were mixed (one flag on, one off) are normalised here -- that is
    # deliberate: a mixed state is no longer expressible in the UI, and leaving
    # it would render a card whose colour contradicts its own filtering.
    for verdict, color in _COLORS.items():
        in_summary = verdict != 'false_positive'
        conn.execute(
            sa.text("""
                UPDATE cases_events
                   SET event_in_summary = :in_summary,
                       event_in_graph   = :in_graph,
                       event_color      = :color
                 WHERE event_verdict = :verdict
            """),
            {'in_summary': in_summary, 'in_graph': in_summary,
             'color': color, 'verdict': verdict}
        )

    op.alter_column('cases_events', 'event_verdict', nullable=False)

    # Guarded: db.create_all() runs before alembic, so on a fresh database the
    # ORM __table_args__ has already created this constraint and adding it again
    # would fail.
    existing = conn.execute(sa.text("""
        SELECT 1 FROM pg_constraint WHERE conname = 'check_event_verdict_valid'
    """)).scalar()
    if not existing:
        op.create_check_constraint(
            'check_event_verdict_valid', 'cases_events',
            "event_verdict IN ('to_be_determined', 'true_positive', 'false_positive')"
        )


def downgrade():
    # The flags are left as the verdict set them. Restoring the pre-upgrade
    # mixed states is not possible -- they were normalised on the way up -- and
    # inventing values would be worse than leaving a consistent state behind.
    conn = op.get_bind()
    existing = conn.execute(sa.text("""
        SELECT 1 FROM pg_constraint WHERE conname = 'check_event_verdict_valid'
    """)).scalar()
    if existing:
        op.drop_constraint('check_event_verdict_valid', 'cases_events', type_='check')
    if _table_has_column('cases_events', 'event_verdict'):
        op.drop_column('cases_events', 'event_verdict')

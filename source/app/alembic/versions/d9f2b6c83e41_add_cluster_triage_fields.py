"""Alert-cluster triage fields + comments (iris-ng v2, v3 parity)

alert_cluster gains severity_override_id (NULL = severity derived live from
member alerts), owner_id, summary (analyst-owned Summary-tab document) and
escalated_case_id (provenance of a full-cluster escalate/merge; SET NULL so
deleting the case never destroys cluster history). New alert_cluster_comment
table backs the v3 Activity tab's analyst comment feed — a dedicated table,
NOT a column on Comments, so the public CommentSchema is untouched.

Guarded adds: db.create_all() runs before alembic and creates the new TABLE
on upgraded instances, but never new COLUMNS on the existing alert_cluster
table — the column adds here are the operative part (fork rule).

Revision ID: d9f2b6c83e41
Revises: c3e8f5a92d47
Create Date: 2026-09-01

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _has_table
from app.alembic.alembic_utils import _table_has_column

revision = 'd9f2b6c83e41'
down_revision = 'c3e8f5a92d47'
branch_labels = None
depends_on = None


def upgrade():
    if not _table_has_column('alert_cluster', 'severity_override_id'):
        op.add_column('alert_cluster',
                      sa.Column('severity_override_id', sa.BigInteger(),
                                sa.ForeignKey('severities.severity_id'),
                                nullable=True))
    if not _table_has_column('alert_cluster', 'owner_id'):
        op.add_column('alert_cluster',
                      sa.Column('owner_id', sa.BigInteger(),
                                sa.ForeignKey('user.id'), nullable=True))
    if not _table_has_column('alert_cluster', 'summary'):
        op.add_column('alert_cluster', sa.Column('summary', sa.Text(), nullable=True))
    if not _table_has_column('alert_cluster', 'escalated_case_id'):
        op.add_column('alert_cluster',
                      sa.Column('escalated_case_id', sa.BigInteger(),
                                sa.ForeignKey('cases.case_id', ondelete='SET NULL'),
                                nullable=True))

    if not _has_table('alert_cluster_comment'):
        op.create_table(
            'alert_cluster_comment',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('cluster_id', sa.BigInteger(),
                      sa.ForeignKey('alert_cluster.id', ondelete='CASCADE'),
                      nullable=False, index=True),
            sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('user.id'),
                      nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False,
                      server_default=sa.text('now()')),
        )


def downgrade():
    pass

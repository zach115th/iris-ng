"""Widen alert_cluster status to the v3 vocabulary (iris-ng v2, v3 parity)

open | investigating | dismissed | escalated | closed. 'closed' is kept for
window-expiry auto-closes and legacy rows (not offered in the v3 picker).
The ACTIVE set — clusters that accept new members, and the partial unique
index's predicate — becomes ('open','investigating'): an analyst marking a
cluster Investigating must NOT cause the next matching alert to mint a
parallel duplicate cluster.

No data migration needed: existing rows are all 'open'/'closed', a subset of
the new vocabulary. CHECK swap is therefore safe in either order; the index
is recreated under the SAME NAME so the ORM declaration keeps matching.

Revision ID: e5c8a73f92d4
Revises: d9f2b6c83e41
Create Date: 2026-09-01

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import index_exists

revision = 'e5c8a73f92d4'
down_revision = 'd9f2b6c83e41'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE alert_cluster DROP CONSTRAINT IF EXISTS '
               'ck_alert_cluster_status')
    op.execute("ALTER TABLE alert_cluster ADD CONSTRAINT ck_alert_cluster_status "
               "CHECK (status IN ('open', 'investigating', 'dismissed', "
               "'escalated', 'closed'))")

    if index_exists('alert_cluster', 'uq_alert_cluster_open_fingerprint'):
        op.execute('DROP INDEX uq_alert_cluster_open_fingerprint')
    op.execute("CREATE UNIQUE INDEX uq_alert_cluster_open_fingerprint "
               "ON alert_cluster (correlation_fingerprint) "
               "WHERE status IN ('open', 'investigating')")


def downgrade():
    pass

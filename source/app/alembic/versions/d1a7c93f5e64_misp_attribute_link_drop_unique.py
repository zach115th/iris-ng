"""misp_attribute_link: drop UNIQUE on misp_attribute_id / misp_attribute_uuid

Revision ID: d1a7c93f5e64
Revises: c9f1e4b28a37
Create Date: 2026-08-20

The link table carried `unique=True` on both `misp_attribute_id` and
`misp_attribute_uuid`, which says a MISP attribute belongs to exactly one IRIS
IOC. MISP does not work that way: it deduplicates attributes within an event by
(type, value, category), so it returns the SAME attribute id for two different
IRIS IOCs that share a value and type in one case — and for an IOC that was
deleted and recreated, since that mints a new ioc_id *and* a new ioc_uuid while
MISP still holds the original attribute.

Observed on production as:

    duplicate key value violates unique constraint
    "misp_attribute_link_misp_attribute_id_key"

raised during `on_postload_ioc_update`, which then poisoned the session and took
down the whole hook task.

`ioc_id` stays UNIQUE — one IRIS IOC still has at most one MISP attribute. Only
the reverse direction is relaxed, so the table now models many-IOCs-to-one-
attribute, which is what MISP actually expresses.

Both columns become plain indexes: the sync path now looks a link up by
`misp_attribute_id`, so the index the UNIQUE was providing is still wanted.

Constraint names are the PostgreSQL defaults for column-level UNIQUE
(`<table>_<column>_key`). This table is created by `db.create_all()` on fresh
installs, so those defaults are what exists in practice, and the production
error message confirms the name verbatim. `IF EXISTS` covers any install whose
table was built some other way — the migration must not fail on a database that
never had the constraint.
"""
from alembic import op


revision = 'd1a7c93f5e64'
down_revision = 'c9f1e4b28a37'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        'ALTER TABLE misp_attribute_link '
        'DROP CONSTRAINT IF EXISTS misp_attribute_link_misp_attribute_id_key'
    )
    op.execute(
        'ALTER TABLE misp_attribute_link '
        'DROP CONSTRAINT IF EXISTS misp_attribute_link_misp_attribute_uuid_key'
    )
    # Dropping the constraint drops the index it was backed by, and the sync
    # path queries on misp_attribute_id, so put a plain index back.
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_misp_attribute_link_misp_attribute_id '
        'ON misp_attribute_link (misp_attribute_id)'
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_misp_attribute_link_misp_attribute_uuid '
        'ON misp_attribute_link (misp_attribute_uuid)'
    )


def downgrade():
    # Deliberately not restoring the UNIQUE constraints. Re-adding them would
    # fail on any database that has since stored the duplicate rows this
    # migration exists to permit, so a downgrade that "worked" would only do so
    # on data that never exercised the fix.
    op.execute('DROP INDEX IF EXISTS ix_misp_attribute_link_misp_attribute_id')
    op.execute('DROP INDEX IF EXISTS ix_misp_attribute_link_misp_attribute_uuid')

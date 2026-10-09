"""Any number of AI backends: the `ai_backend` table replaces the two ServerSettings slots (iris-ng, 2026-10-09)

Creates `ai_backend` (id, label, provider, url, api_key, model, model_catalog,
position, created_at, updated_at; unique index on lower(label)) and
`server_settings.ai_backend_active_id` (FK, ON DELETE SET NULL), then imports
the two legacy slots ONCE: every slot that carries a URL or a model becomes a
row (label = the slot's label or Primary / Alternate, the second de-duplicated
with " (2)"), `ai_backend_active_slot` becomes the active id, and every
`ai_feature_overrides` value "primary" / "alt" becomes that row's id (a slot
that produced no row resets the override to null). The twelve legacy columns
stay in place, unread. Guarded so a re-run is a no-op: the DDL checks what
exists (db.create_all() runs before this and already creates the table and its
index at boot), the import runs only while `ai_backend` is empty.

Revision ID: b8e3f1a7c2d5
Revises: a7c2d9e4f1b6
Create Date: 2026-10-09
"""
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB

from app.alembic.alembic_utils import _has_table
from app.alembic.alembic_utils import _table_has_column
from app.alembic.alembic_utils import index_exists

revision = 'b8e3f1a7c2d5'
down_revision = 'a7c2d9e4f1b6'
branch_labels = None
depends_on = None

SLOTS = (
    # (slot name, column prefix, default label, position)
    ('primary', 'ai_backend_', 'Primary', 0),
    ('alt', 'ai_backend_alt_', 'Alternate', 1),
)


def upgrade():
    if not _has_table('ai_backend'):
        op.create_table(
            'ai_backend',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('label', sa.Text(), nullable=False),
            sa.Column('provider', sa.String(32), nullable=False, server_default=text("'openai'")),
            sa.Column('url', sa.Text(), nullable=True),
            sa.Column('api_key', sa.Text(), nullable=True),
            sa.Column('model', sa.Text(), nullable=True),
            sa.Column('model_catalog', JSONB(), nullable=True),
            sa.Column('position', sa.Integer(), nullable=False, server_default=text('0')),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('now()')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=text('now()')),
        )
    if not index_exists('ai_backend', 'ix_ai_backend_label_lower'):
        op.create_index('ix_ai_backend_label_lower', 'ai_backend', [text('lower(label)')], unique=True)
    if not _table_has_column('server_settings', 'ai_backend_active_id'):
        op.add_column('server_settings', sa.Column(
            'ai_backend_active_id', sa.BigInteger(),
            sa.ForeignKey('ai_backend.id', ondelete='SET NULL'), nullable=True))
    import_slots(op.get_bind())


def import_slots(conn) -> int:
    """Copy the two legacy slots into `ai_backend` rows and repoint the active
    slot + the per-feature overrides. Returns the number of rows created; 0
    (and no change) when the table already holds rows or no slot is filled.
    A plain function so the suite can prove the no-op on a populated table."""
    if conn.execute(text("SELECT count(*) FROM ai_backend")).scalar():
        return 0
    row = conn.execute(text(
        "SELECT id, ai_backend_active_slot, ai_feature_overrides, "
        "ai_backend_url, ai_backend_api_key, ai_backend_model, ai_backend_label, ai_backend_provider, "
        "ai_backend_model_catalog, ai_backend_alt_url, ai_backend_alt_api_key, ai_backend_alt_model, "
        "ai_backend_alt_label, ai_backend_alt_provider, ai_backend_alt_model_catalog "
        "FROM server_settings ORDER BY id LIMIT 1")).mappings().first()
    if row is None:
        return 0

    ids: dict[str, int] = {}
    labels_taken: set[str] = set()
    for slot, prefix, default_label, position in SLOTS:
        url = (row[prefix + 'url'] or '').strip()
        model = (row[prefix + 'model'] or '').strip()
        if not url and not model:
            continue
        label = (row[prefix + 'label'] or '').strip() or default_label
        if label.lower() in labels_taken:
            label = label + ' (2)'
        labels_taken.add(label.lower())
        catalog = row[prefix + 'model_catalog']
        new_id = conn.execute(text(
            "INSERT INTO ai_backend (label, provider, url, api_key, model, model_catalog, position) "
            "VALUES (:label, :provider, :url, :api_key, :model, CAST(:catalog AS jsonb), :position) RETURNING id"
        ), {
            'label': label,
            'provider': ((row[prefix + 'provider'] or '').strip().lower() or 'openai'),
            'url': url or None,
            'api_key': (row[prefix + 'api_key'] or '').strip() or None,
            'model': model or None,
            'catalog': json.dumps(catalog) if catalog is not None else None,
            'position': position,
        }).scalar()
        ids[slot] = int(new_id)

    active_slot = (row['ai_backend_active_slot'] or 'primary').strip().lower()
    active_id = ids.get(active_slot) or ids.get('primary') or ids.get('alt')
    overrides = row['ai_feature_overrides']
    if isinstance(overrides, str):
        overrides = json.loads(overrides)
    new_overrides = None
    if isinstance(overrides, dict):
        new_overrides = {}
        for feature, value in overrides.items():
            slot_key = (value or '').strip().lower() if isinstance(value, str) else None
            new_overrides[feature] = ids.get(slot_key) if slot_key in ids else None
    conn.execute(text(
        "UPDATE server_settings SET ai_backend_active_id = :active, "
        "ai_feature_overrides = CAST(:overrides AS jsonb) WHERE id = :id"
    ), {
        'active': active_id,
        'overrides': json.dumps(new_overrides) if new_overrides is not None else None,
        'id': row['id'],
    })
    return len(ids)


def downgrade():
    pass

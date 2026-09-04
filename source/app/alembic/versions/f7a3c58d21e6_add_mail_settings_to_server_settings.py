"""Add mail ingest + SMTP settings to server_settings (iris-ng v2, Phase 1)

Sixteen columns backing the Mail settings tab: the IMAP mailbox the mail-rule
poller reads (host/port/ssl/credentials/folder + poll interval, NULL interval =
polling off), the outbound SMTP relay (host/port/security/credentials/from,
consumed by the Phase 5 notification email channel), and three feature toggles
(mail_ingest_enabled, mail_ai_triage_enabled, email_notifications_enabled).

The two password columns are write-only through the API: ServerSettingsSchema
marks them load_only and dumps mail_*_password_set booleans instead, so a
settings GET never returns a stored secret. Column-adds on an existing table
depend on this migration committing (db.create_all only creates missing
TABLES), hence the guarded adds below.

Revision ID: f7a3c58d21e6
Revises: b8f4e2a71c93
Create Date: 2026-08-25

"""
import sqlalchemy as sa
from alembic import op

from app.alembic.alembic_utils import _table_has_column

revision = 'f7a3c58d21e6'
down_revision = 'b8f4e2a71c93'
branch_labels = None
depends_on = None


_COLUMNS = [
    sa.Column('mail_ingest_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    sa.Column('mail_imap_host', sa.Text(), nullable=True),
    sa.Column('mail_imap_port', sa.Integer(), nullable=True),
    sa.Column('mail_imap_ssl', sa.Boolean(), nullable=False, server_default=sa.text('true')),
    sa.Column('mail_imap_username', sa.Text(), nullable=True),
    sa.Column('mail_imap_password', sa.Text(), nullable=True),
    sa.Column('mail_imap_folder', sa.Text(), nullable=False, server_default=sa.text("'INBOX'")),
    sa.Column('mail_poll_interval_minutes', sa.Integer(), nullable=True),
    sa.Column('mail_smtp_host', sa.Text(), nullable=True),
    sa.Column('mail_smtp_port', sa.Integer(), nullable=True),
    sa.Column('mail_smtp_security', sa.String(16), nullable=False, server_default=sa.text("'tls'")),
    sa.Column('mail_smtp_username', sa.Text(), nullable=True),
    sa.Column('mail_smtp_password', sa.Text(), nullable=True),
    sa.Column('mail_smtp_from_addr', sa.Text(), nullable=True),
    sa.Column('mail_ai_triage_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    sa.Column('email_notifications_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
]


def upgrade():
    # Each Column object is attached at most once (one add_column per boot),
    # so no copy is needed — Column.copy() is deprecated in SQLAlchemy 2.x.
    for col in _COLUMNS:
        if not _table_has_column('server_settings', col.name):
            op.add_column('server_settings', col)


def downgrade():
    for col in _COLUMNS:
        if _table_has_column('server_settings', col.name):
            op.drop_column('server_settings', col.name)

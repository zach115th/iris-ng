from alembic import op
import sqlalchemy as sa


# iris-ng (2026-05-19): rewrote these helpers to use op.get_bind() instead of
# spinning up a fresh engine_from_config(...).engine.connect() each call.
#
# Why: the upstream pattern creates a brand-new engine + connection pool for
# every probe. The pool keeps the connection open after .close() returns it
# (it's "closed" only from SQLAlchemy's perspective), and on PostgreSQL the
# implicit transaction from the probe SELECT holds an AccessShareLock on the
# probed table. The next op.add_column then needs AccessExclusiveLock for the
# ALTER TABLE — which BLOCKS waiting for the AccessShareLock to release. The
# migration hangs indefinitely.
#
# This bit a vanilla DFIR-IRIS → iris-ng import where 5 sequential
# _table_has_column calls inside c3f1b87a902d_add_ai_backend_to_server_settings
# leaked enough idle-in-transaction connections that the very first ALTER
# TABLE got stuck waiting on its predecessor's lock.
#
# op.get_bind() returns alembic's own already-open migration connection — same
# transactional context as the op.add_column / op.create_table that follows.
# No new engine, no leak, no contention.


def _table_has_column(table, column):
    """Return True iff `column` exists on `table` in the database alembic is
    currently migrating. Returns False if the table doesn't exist."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    try:
        cols = [c['name'] for c in inspector.get_columns(table)]
    except Exception:
        return False
    return column in cols


def _has_table(table_name):
    """Return True iff `table_name` exists in the database alembic is
    currently migrating."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def index_exists(table_name, index_name):
    """Return True iff `index_name` exists on `table_name`."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    try:
        indexes = inspector.get_indexes(table_name)
    except Exception:
        return False
    return any(idx['name'] == index_name for idx in indexes)

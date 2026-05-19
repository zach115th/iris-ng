"""Reconcile an imported vanilla DFIR-IRIS schema against iris-ng's ORM models.

After importing a vanilla v2.4.x DB via scripts/import_vanilla_db.sh, some
columns may be silently missing from the schema because upstream's broken
alembic env.py (begin_transaction commented out for an unknown stretch of
time) caused ADD COLUMN migrations to log "Running upgrade ..." but never
actually commit. The alembic_version table was advanced regardless, so on
the iris-ng side:

  * db.create_all() doesn't add the missing columns (it only creates tables
    that don't exist; it never touches existing tables).
  * Alembic doesn't re-run the broken migrations (alembic_version says
    they're already applied).

Result: the schema is missing columns that the iris-ng ORM expects, and any
query that references them returns "column ... does not exist". First place
this bites: dashboard /metrics tab (ioc.case_id), /case/assets/filter
(asset_compromise_status_id), and so on for any other vanilla install that
hit the same silent-no-commit window.

This script:
  1. Walks every iris-ng ORM model
  2. For every table that DOES exist in the live DB, diffs declared columns
     against actual columns
  3. Emits `ALTER TABLE <t> ADD COLUMN <c> <type>` for each missing column
  4. NOT NULL columns are added as NULL-able first to avoid backfill failures
     (caller can tighten later via a separate migration if needed)
  5. Foreign-key constraints in the column definition are NOT replayed —
     they can be added in a second pass if a future feature needs them
     enforced. None of the silent-no-commit columns observed so far rely
     on FK enforcement to function.

Run inside the app container after pg_restore but before alembic upgrade:

    docker compose -f docker-compose.dev.yml run --rm --no-deps app \
        python /iriswebapp/scripts/reconcile_vanilla_schema.py

(import_vanilla_db.sh calls this automatically during the import flow.)
"""
import sys

from app import app, db
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql


def _column_ddl_fragment(col):
    """Return `<type> [DEFAULT <expr>]` for an ALTER TABLE ADD COLUMN clause.
    Skips NOT NULL — we always add columns NULL-able first so existing rows
    don't trip a backfill failure. Caller can tighten later."""
    col_type = col.type.compile(dialect=postgresql.dialect())
    default = ""
    if col.server_default is not None:
        # server_default.arg can be a string, ClauseElement, or text() object
        default_arg = col.server_default.arg
        if hasattr(default_arg, "text"):
            default_arg = default_arg.text
        default = f" DEFAULT {default_arg}"
    return f"{col_type}{default}"


def reconcile():
    with app.app_context():
        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())

        added = []
        skipped_missing_tables = []
        failed = []

        # db.metadata holds every Table declared by an ORM model that's been
        # imported by `from app import db`. iris-ng imports all of them
        # transitively via post_init.
        for table_name, table in db.metadata.tables.items():
            if table_name not in existing_tables:
                # Table doesn't exist in the imported DB. db.create_all will
                # add it on next app boot; nothing for us to do here.
                skipped_missing_tables.append(table_name)
                continue

            existing_col_names = {c["name"] for c in inspector.get_columns(table_name)}

            for col in table.columns:
                if col.name in existing_col_names:
                    continue
                # Build the bare ADD COLUMN statement — no FK, no NOT NULL,
                # just type + optional server default.
                ddl = _column_ddl_fragment(col)
                stmt = f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{col.name}" {ddl}'
                try:
                    db.session.execute(text(stmt))
                    db.session.commit()
                    added.append((table_name, col.name, ddl))
                    print(f"  + {table_name}.{col.name}  ({ddl})")
                except Exception as exc:
                    db.session.rollback()
                    failed.append((table_name, col.name, str(exc)))
                    print(f"  ! {table_name}.{col.name}  FAILED: {exc}", file=sys.stderr)

        print("")
        print(f"=== Reconciliation summary ===")
        print(f"  Tables in DB:                  {len(existing_tables)}")
        print(f"  Tables missing (deferred to db.create_all): {len(skipped_missing_tables)}")
        print(f"  Columns added:                 {len(added)}")
        print(f"  Columns failed:                {len(failed)}")
        if failed:
            print("\nFailures:")
            for t, c, err in failed:
                print(f"  {t}.{c}: {err}")
            sys.exit(1)


if __name__ == "__main__":
    reconcile()

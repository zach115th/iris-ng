#!/usr/bin/env bash
# Upgrade the iris-ng database from PostgreSQL 12 to PostgreSQL 17.
#
# Two-phase — dump first (while pg12 is still running), then restore after
# the image swap. The script prints the exact steps between phases.
#
# Usage:
#
#   # Phase 1 — with the pg12 stack running:
#   bash scripts/migrate_postgres_17.sh dump
#
#   # Follow the printed instructions (edit Dockerfile, swap volume, rebuild db).
#
#   # Phase 2 — after the pg17 db container is up and fresh:
#   bash scripts/migrate_postgres_17.sh restore [backup-file]
#
# The pg_dumpall format is version-independent — this script jumps directly
# from pg12 to pg17 with no intermediate steps.

set -euo pipefail

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
IRIS_NG_COMPOSE="docker-compose.dev.yml"
IRIS_NG_DB_CONTAINER="iriswebapp_db"

# Spot-check tables after restore — both upstream tables and iris-ng additions.
VERIFY_TABLES=("cases" "alerts" "ioc" "case_assets" "cases_events"
               "user" "alembic_version"
               "case_ai_artifact" "misp_event_link" "case_working_event"
               "case_time_entry" "ai_job")

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
log()  { printf '\033[0;32m[pg-upgrade]\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m[pg-upgrade] WARN:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[0;31m[pg-upgrade] FATAL:\033[0m %s\n' "$*" >&2; exit 1; }
step() { printf '\n\033[1;34m>>> %s\033[0m\n' "$*"; }

compose_project_name() {
    if [[ -n "${COMPOSE_PROJECT_NAME:-}" ]]; then
        echo "$COMPOSE_PROJECT_NAME"
        return
    fi
    if [[ -f ".env" ]] && grep -q '^COMPOSE_PROJECT_NAME=' .env; then
        grep '^COMPOSE_PROJECT_NAME=' .env | head -1 | cut -d= -f2-
        return
    fi
    basename "$PWD"
}

# ---------------------------------------------------------------------------
# PHASE 1 — dump
# ---------------------------------------------------------------------------
cmd_dump() {
    local backup_file
    backup_file="iris-pg12-backup-$(date +%Y%m%d-%H%M%S).sql"

    step "Checking pg12 container..."
    docker inspect "$IRIS_NG_DB_CONTAINER" >/dev/null 2>&1 || \
        die "Container '$IRIS_NG_DB_CONTAINER' is not running. Start the stack first."

    local pg_ver
    pg_ver=$(docker exec "$IRIS_NG_DB_CONTAINER" psql -U postgres -tAc \
             "SHOW server_version;" 2>/dev/null || echo "unknown")
    log "PostgreSQL version in container: $pg_ver"
    if [[ "$pg_ver" != 12* ]]; then
        warn "Expected pg12 — got $pg_ver. Are you running the right container?"
        warn "Continuing anyway — the dump may still work."
    fi

    step "Dumping all databases..."
    docker exec "$IRIS_NG_DB_CONTAINER" pg_dumpall -U postgres > "$backup_file"

    local line_count
    line_count=$(wc -l < "$backup_file")
    [[ "$line_count" -lt 100 ]] && \
        die "Backup looks too small ($line_count lines) — something went wrong. Check container logs."

    log "Backup written: $backup_file ($line_count lines, $(du -sh "$backup_file" | cut -f1))"

    local project
    project=$(compose_project_name)
    local vol_name="${project}_db_data"

    cat <<NEXT

==========================================================
  DUMP COMPLETE. Follow these steps in order:
==========================================================

1. Edit docker/db/Dockerfile:
     FROM postgres:12-alpine  →  FROM postgres:17-alpine

2. Stop the stack:
     docker compose -f ${IRIS_NG_COMPOSE} down

3. Remove the old data volume (the backup above is your safety net):
     docker volume rm ${vol_name}
   Not sure of the exact name? Run: docker volume ls | grep db_data

4. Rebuild and start only the db service:
     docker compose -f ${IRIS_NG_COMPOSE} up -d --build --no-deps db

5. Wait ~10s for pg17 to initialize, then run the restore:
     bash scripts/migrate_postgres_17.sh restore ${backup_file}

6. Bring up the rest of the stack:
     docker compose -f ${IRIS_NG_COMPOSE} up -d --force-recreate

==========================================================
  Backup file to keep: ${backup_file}
==========================================================
NEXT
}

# ---------------------------------------------------------------------------
# PHASE 2 — restore
# ---------------------------------------------------------------------------
cmd_restore() {
    local backup_file="${1:-}"

    # Auto-find the most recent backup if not specified.
    if [[ -z "$backup_file" ]]; then
        backup_file=$(ls -t iris-pg12-backup-*.sql 2>/dev/null | head -1 || true)
        [[ -z "$backup_file" ]] && \
            die "No backup file found. Pass the path explicitly: restore <file>"
        log "Using most recent backup: $backup_file"
    fi

    [[ -f "$backup_file" ]] || die "Backup file not found: $backup_file"

    step "Checking pg17 container..."
    docker inspect "$IRIS_NG_DB_CONTAINER" >/dev/null 2>&1 || \
        die "Container '$IRIS_NG_DB_CONTAINER' is not running. Start the db service first."

    local pg_ver
    pg_ver=$(docker exec "$IRIS_NG_DB_CONTAINER" psql -U postgres -tAc \
             "SHOW server_version;" 2>/dev/null || echo "unknown")
    log "PostgreSQL version in container: $pg_ver"
    [[ "$pg_ver" == 17* ]] || \
        die "Expected pg17 — got '$pg_ver'. Did you rebuild the db image and recreate the container?"

    step "Restoring from $backup_file..."
    docker exec -i "$IRIS_NG_DB_CONTAINER" psql -U postgres < "$backup_file"

    step "Verifying restore..."
    local all_ok=1
    for t in "${VERIFY_TABLES[@]}"; do
        local found
        found=$(docker exec "$IRIS_NG_DB_CONTAINER" psql -U postgres -d iris_db -tAc \
                "SELECT 1 FROM information_schema.tables WHERE table_name='${t}';" \
                2>/dev/null || echo "")
        if [[ "$found" == "1" ]]; then
            log "  OK  $t"
        else
            warn "  MISSING  $t — check output above for errors"
            all_ok=0
        fi
    done

    if [[ "$all_ok" -eq 1 ]]; then
        log "All spot-check tables present."
    else
        warn "One or more tables missing. Review restore output before proceeding."
    fi

    # ---------------------------------------------------------------------------
    # Re-issue passwords as scram-sha-256.
    #
    # pg12 stores passwords as MD5 hashes; pg17 defaults to scram-sha-256 auth
    # for remote connections (pg_hba.conf: "host all all all scram-sha-256").
    # A restored MD5-hashed password is incompatible with scram-sha-256 auth —
    # the app container cannot connect until the passwords are re-issued in
    # plaintext so pg17 can hash them with scram-sha-256.
    # ---------------------------------------------------------------------------
    step "Re-issuing passwords as scram-sha-256..."

    local env_file=".env"
    [[ -f "$env_file" ]] || die ".env not found in $(pwd) — run this script from the iris-ng root."

    # Parse the four relevant fields from .env (ignore comments, handle quotes).
    _env_val() { grep -E "^${1}=" "$env_file" | head -1 | cut -d= -f2- | tr -d "\"'"; }

    local pg_user pg_pass pg_admin_user pg_admin_pass
    pg_user=$(       _env_val POSTGRES_USER)
    pg_pass=$(       _env_val POSTGRES_PASSWORD)
    pg_admin_user=$( _env_val POSTGRES_ADMIN_USER)
    pg_admin_pass=$( _env_val POSTGRES_ADMIN_PASSWORD)

    [[ -n "$pg_user"       ]] || die "POSTGRES_USER not found in $env_file"
    [[ -n "$pg_pass"       ]] || die "POSTGRES_PASSWORD not found in $env_file"
    [[ -n "$pg_admin_user" ]] || die "POSTGRES_ADMIN_USER not found in $env_file"
    [[ -n "$pg_admin_pass" ]] || die "POSTGRES_ADMIN_PASSWORD not found in $env_file"

    docker exec "$IRIS_NG_DB_CONTAINER" psql -U postgres -c \
        "ALTER USER \"${pg_user}\" PASSWORD '${pg_pass}';" && \
        log "  OK  ${pg_user} → scram-sha-256"

    docker exec "$IRIS_NG_DB_CONTAINER" psql -U postgres -c \
        "ALTER USER \"${pg_admin_user}\" PASSWORD '${pg_admin_pass}';" && \
        log "  OK  ${pg_admin_user} → scram-sha-256"

    cat <<DONE

==========================================================
  RESTORE COMPLETE. Bring up the rest of the stack:

    docker compose -f ${IRIS_NG_COMPOSE} up -d --force-recreate

  The --force-recreate flag is required — without it, app/worker
  containers may stay on the old image with stale import caches.
==========================================================
DONE
}

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
COMMAND="${1:-help}"
shift || true

case "$COMMAND" in
    dump)    cmd_dump    "$@" ;;
    restore) cmd_restore "$@" ;;
    *)
        cat <<USAGE
Usage: bash scripts/migrate_postgres_17.sh <command>

Commands:
  dump              Dump the pg12 database to a timestamped .sql file and
                    print the exact next steps. Run while the pg12 stack is up.

  restore [file]    Restore a dump into the running pg17 container. Defaults
                    to the most recent iris-pg12-backup-*.sql in the cwd.

Example — full upgrade flow:
  1.  bash scripts/migrate_postgres_17.sh dump
  2.  (follow printed instructions: edit Dockerfile, remove volume, rebuild db)
  3.  bash scripts/migrate_postgres_17.sh restore
  4.  docker compose -f docker-compose.dev.yml up -d --force-recreate
USAGE
        exit 1
        ;;
esac

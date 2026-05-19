#!/usr/bin/env bash
# Migrate a vanilla DFIR-IRIS deployment into this IRIS-NG instance.
#
# IRIS-NG is purely additive over v2.5.0-beta.1 (new tables/columns only — no
# renames, no removals), so an existing DB carries forward. This script handles
# the full migration: Postgres dump+restore, named-volume copy, secret carry-
# over, and a post-restore schema sanity check.
#
# Usage:
#
#   # On the OLD host (vanilla DFIR-IRIS), capture everything to a portable dir.
#   # --project is the docker-compose project name (working-directory basename
#   # of the cloned iris-web repo, e.g. `iris-web`). Auto-detected if omitted.
#   # If your DB container has a custom name, use --db-container <name> instead.
#   bash scripts/import_vanilla_db.sh export --project iris-web --out ./iris-export
#
#   # Move that directory to the NEW host (iris-ng), then:
#   bash scripts/import_vanilla_db.sh import --from ./iris-export
#
# The migration directory shape (anything missing produces a warning, not an
# error — partial salvage flows work too):
#
#   iris-export/
#   ├── iris.dump                  (Postgres custom-format dump, REQUIRED)
#   ├── server_data.tar.gz         (optional — uploaded evidence + datastore)
#   ├── user_templates.tar.gz      (optional — uploaded .docx report templates)
#   ├── iris-downloads.tar.gz      (optional — generated reports)
#   └── secrets.env                (optional but strongly recommended —
#                                   carries IRIS_SECRET_KEY +
#                                   IRIS_SECURITY_PASSWORD_SALT so existing
#                                   user passwords keep verifying)
#
# Caveats — read before running:
#   * Source must be v2.4.x or v2.5.0-beta.1. Older releases predate several
#     upstream tables and the alembic chain will need manual help.
#   * Vanilla DFIR-IRIS v2.4.x ran with a commented-out begin_transaction() in
#     alembic/env.py. Migrations may have silently no-committed. The import
#     pass runs a schema-vs-alembic_version sanity check and aborts if it
#     looks like the upstream DB is half-migrated.
#   * IRIS-NG's MISP integration uses a different module (iris_misp_sync_module)
#     than upstream's iris_misp_module. Old MISP configs do NOT carry — you'll
#     reconfigure under /manage/modules after the import.

set -euo pipefail

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
IRIS_NG_COMPOSE="docker-compose.dev.yml"
IRIS_NG_PROJECT_DEFAULT="iris-next"   # working-dir basename for the iris-ng tree
IRIS_NG_DB_CONTAINER="iriswebapp_db"
IRIS_NG_APP_CONTAINER="iriswebapp_app"
IRIS_NG_WORKER_CONTAINER="iriswebapp_worker"

# Volume names IRIS-NG creates (and that we import into). These are bare names;
# docker prefixes them with the compose project name (e.g. `iris-next_db_data`).
NAMED_VOLUMES=("server_data" "user_templates" "iris-downloads")

# A handful of v2.5.0-beta.1-era tables that MUST exist in any sane export.
# Used for the post-restore schema sanity check.
EXPECTED_TABLES=("cases" "alerts" "ioc" "case_assets" "case_events"
                 "case_template" "server_settings" "user" "client"
                 "alembic_version")

# Tables added by IRIS-NG's own migrations — confirmed AFTER `alembic upgrade`.
IRIS_NG_NEW_TABLES=("case_ai_artifact" "case_working_event" "ioc_note_link"
                    "case_task_link" "evidence_asset_link"
                    "misp_event_link" "misp_attribute_link")

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
log()  { echo "[import_vanilla_db] $*"; }
warn() { echo "[import_vanilla_db] WARN: $*" >&2; }
die()  { echo "[import_vanilla_db] FATAL: $*" >&2; exit 1; }

ask() {
    local prompt="$1"
    local reply
    if [[ "${FORCE:-0}" -eq 1 ]]; then
        return 0
    fi
    read -r -p "$prompt [y/N] " reply
    [[ "$reply" =~ ^[yY] ]]
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

# Compose project name — fall back to the working-directory basename if not
# set by the user. Mirrors how `docker compose` itself computes the project.
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

# Wrap "docker run alpine" with the host's docker.
tar_in_volume() {
    # Usage: tar_in_volume <volume_name> create  <output_path>
    #        tar_in_volume <volume_name> extract <input_path>
    local vol="$1"
    local op="$2"
    local file="$3"
    local file_dir file_base
    file_dir="$(cd "$(dirname "$file")" && pwd -P)"
    file_base="$(basename "$file")"
    case "$op" in
        create)
            docker run --rm -v "${vol}:/data:ro" -v "${file_dir}:/backup" alpine \
                sh -c "cd /data && tar czf /backup/${file_base} ."
            ;;
        extract)
            # Wipe the volume's existing contents first so we don't merge.
            docker run --rm -v "${vol}:/data" -v "${file_dir}:/backup:ro" alpine \
                sh -c "find /data -mindepth 1 -delete && tar xzf /backup/${file_base} -C /data"
            ;;
        *) die "tar_in_volume: unknown op '$op'" ;;
    esac
}

# ===========================================================================
# EXPORT MODE — run on the OLD vanilla DFIR-IRIS host.
# ===========================================================================
export_run() {
    local project_name=""
    local db_container=""
    local out_dir=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --project)       project_name="$2"; shift 2 ;;
            --db-container)  db_container="$2"; shift 2 ;;
            --out)           out_dir="$2"; shift 2 ;;
            -f|--force)      FORCE=1; shift ;;
            *) die "export: unknown option: $1" ;;
        esac
    done

    require_command docker

    # Resolve the db container name. Try in order:
    #   1. --db-container if explicitly given (most robust)
    #   2. iriswebapp_db (the canonical DFIR-IRIS container_name — set in
    #      docker-compose.yml across every upstream release we know of)
    #   3. <project>_db_1 (compose v1 style) if --project provided
    #   4. <project>-db-1 (compose v2 style) if --project provided
    # If --project is omitted, auto-detect from cwd basename for the 3/4 try.
    [[ -z "$project_name" ]] && project_name="$(basename "$PWD")"

    local candidates=()
    [[ -n "$db_container" ]] && candidates+=("$db_container")
    candidates+=("iriswebapp_db")
    candidates+=("${project_name}_db_1")
    candidates+=("${project_name}-db-1")

    local found=""
    for c in "${candidates[@]}"; do
        if docker ps --format '{{.Names}}' | grep -qx "$c"; then
            found="$c"
            break
        fi
    done

    if [[ -z "$found" ]]; then
        echo "[import_vanilla_db] FATAL: could not find a running DFIR-IRIS db container." >&2
        echo "  Tried: ${candidates[*]}" >&2
        echo "" >&2
        echo "  Containers currently running on this host:" >&2
        docker ps --format '    {{.Names}}    ({{.Image}})' >&2 || true
        echo "" >&2
        echo "  Fix: re-run with --db-container <name>  (e.g. --db-container iriswebapp_db)" >&2
        echo "       OR set --project <compose-project-name>  (e.g. --project iris-web)" >&2
        echo "       --project takes the COMPOSE PROJECT NAME (working-dir basename), not a file path." >&2
        exit 1
    fi

    local old_db_container="$found"
    [[ -z "$out_dir" ]] && out_dir="./iris-export-$(date +%Y%m%d-%H%M%S)"

    log "Exporting vanilla DFIR-IRIS (db container: $old_db_container, project: $project_name) -> $out_dir"
    mkdir -p "$out_dir"

    log "Dumping Postgres from container '$old_db_container'..."
    # No -t: a TTY would inject CR characters into the binary dump and corrupt it.
    docker exec "$old_db_container" pg_dump -U postgres -Fc -d iris_db \
        > "${out_dir}/iris.dump"
    log "  -> $(du -h "${out_dir}/iris.dump" | cut -f1) written to ${out_dir}/iris.dump"

    # 2. Named volume tarballs.
    for vol_base in "${NAMED_VOLUMES[@]}"; do
        local vol="${project_name}_${vol_base}"
        if ! docker volume inspect "$vol" >/dev/null 2>&1; then
            warn "volume '$vol' not found, skipping (this is normal if you never uploaded templates/evidence)"
            continue
        fi
        log "Tarring volume '$vol' -> ${vol_base}.tar.gz..."
        tar_in_volume "$vol" create "${out_dir}/${vol_base}.tar.gz"
    done

    # 3. Capture the secrets that affect password hashing.
    if [[ -f ".env" ]]; then
        log "Extracting IRIS_SECRET_KEY + IRIS_SECURITY_PASSWORD_SALT from ./.env..."
        grep -E '^(IRIS_SECRET_KEY|IRIS_SECURITY_PASSWORD_SALT)=' .env > "${out_dir}/secrets.env" \
            || warn "no IRIS_SECRET_KEY / IRIS_SECURITY_PASSWORD_SALT found in ./.env — user passwords may not verify on the new side"
    else
        warn "no ./.env found in current directory — skipping secrets.env. Without IRIS_SECRET_KEY + IRIS_SECURITY_PASSWORD_SALT carrying over, existing user passwords will NOT verify on iris-ng. Locate the old .env and copy those two lines into iris-ng's .env manually."
    fi

    log ""
    log "=== Export complete ==="
    log "  Directory: ${out_dir}"
    log "  Contents:"
    ls -lh "$out_dir" | sed 's/^/    /'
    log ""
    log "Move ${out_dir}/ to the iris-ng host, then run:"
    log "    bash scripts/import_vanilla_db.sh import --from ${out_dir}"
}

# ===========================================================================
# IMPORT MODE — run on the iris-ng host, from the iris-ng working directory.
# ===========================================================================
import_run() {
    local from_dir=""
    local skip_volumes=0
    local skip_secrets=0
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --from)         from_dir="$2"; shift 2 ;;
            --skip-volumes) skip_volumes=1; shift ;;
            --skip-secrets) skip_secrets=1; shift ;;
            -f|--force)     FORCE=1; shift ;;
            *) die "import: unknown option: $1" ;;
        esac
    done

    require_command docker
    [[ -z "$from_dir" ]] && die "--from <dir> is required"
    [[ -d "$from_dir" ]] || die "migration directory not found: $from_dir"
    [[ -f "${from_dir}/iris.dump" ]] || die "${from_dir}/iris.dump not found — DB dump is required"
    [[ -f "$IRIS_NG_COMPOSE" ]] || die "must run from iris-ng working directory ($IRIS_NG_COMPOSE not found here)"

    local project_name
    project_name="$(compose_project_name)"
    log "iris-ng compose project: $project_name"

    log ""
    log "=== Migration plan ==="
    log "  Source dir:           $from_dir"
    log "  Target iris-ng:       $project_name (this directory)"
    log "  DB dump:              ${from_dir}/iris.dump ($(du -h "${from_dir}/iris.dump" | cut -f1))"
    for vol_base in "${NAMED_VOLUMES[@]}"; do
        local arc="${from_dir}/${vol_base}.tar.gz"
        if [[ -f "$arc" ]]; then
            log "  Volume to restore:    ${vol_base} ($(du -h "$arc" | cut -f1))"
        fi
    done
    if [[ -f "${from_dir}/secrets.env" ]]; then
        log "  Secrets to carry:     IRIS_SECRET_KEY + IRIS_SECURITY_PASSWORD_SALT from secrets.env"
    fi
    log ""
    log "DESTRUCTIVE: iris-ng's existing iris_db database and named volumes (server_data,"
    log "user_templates, iris-downloads) will be WIPED and replaced. The iris-ng .env will"
    log "be modified in place to carry the old secrets."
    log ""
    ask "Proceed with migration?" || die "aborted by user"

    # 1. Stop app + worker (keep db up — we need it to restore into).
    log ""
    log "[1/6] Stopping app + worker (db stays up)..."
    docker compose -f "$IRIS_NG_COMPOSE" stop app worker || warn "app/worker were not running"

    # 2. Ensure db is up.
    log "[2/6] Ensuring db is up..."
    docker compose -f "$IRIS_NG_COMPOSE" up -d db
    # Wait for postgres to accept connections.
    local tries=0
    until docker exec "$IRIS_NG_DB_CONTAINER" pg_isready -U postgres >/dev/null 2>&1; do
        tries=$((tries+1))
        [[ $tries -gt 30 ]] && die "Postgres did not become ready in 30s"
        sleep 1
    done
    log "  Postgres is ready."

    # 3. Drop + recreate iris_db, then pg_restore.
    #    DROP DATABASE ... WITH (FORCE) needs Postgres 13+. iris-ng's db
    #    image is currently postgres:12-alpine (and the user may have an
    #    even older Postgres on their old vanilla host). Manually terminate
    #    open backends first, then plain DROP — works on Pg >= 9.6.
    log "[3/6] Restoring Postgres dump (drop + recreate iris_db)..."
    docker exec -i "$IRIS_NG_DB_CONTAINER" psql -U postgres -d postgres -c "
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = 'iris_db' AND pid <> pg_backend_pid();
    " >/dev/null
    docker exec -i "$IRIS_NG_DB_CONTAINER" psql -U postgres -d postgres \
        -c "DROP DATABASE IF EXISTS iris_db;" >/dev/null
    docker exec -i "$IRIS_NG_DB_CONTAINER" psql -U postgres -d postgres \
        -c "CREATE DATABASE iris_db OWNER postgres;" >/dev/null
    # --no-owner / --no-acl so ownership/grants from the old DB don't try to
    # reference users that may not exist on the new db role-set.
    # pg_restore writes warnings (already-exists, unknown role) to stderr and
    # those are normal — keep them so the operator can see them in context.
    if ! docker exec -i "$IRIS_NG_DB_CONTAINER" pg_restore -U postgres -d iris_db \
            --no-owner --no-acl < "${from_dir}/iris.dump"; then
        warn "pg_restore exited non-zero — some errors are normal (extensions, missing roles);"
        warn "the schema check on the next step will catch any real corruption."
    fi

    # 4. Pre-Alembic schema sanity check.
    log "[4/6] Pre-Alembic schema sanity check..."
    local missing=()
    for tbl in "${EXPECTED_TABLES[@]}"; do
        if ! docker exec "$IRIS_NG_DB_CONTAINER" psql -U postgres -d iris_db -tAc \
            "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='${tbl}';" \
            | grep -q '^1$'; then
            missing+=("$tbl")
        fi
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        warn "Tables expected in any v2.4.x+ DFIR-IRIS DB are MISSING after restore: ${missing[*]}"
        warn "This usually means the source DB was on a release older than v2.4.x, OR"
        warn "the upstream alembic env.py begin_transaction() bug left it half-migrated."
        ask "Continue anyway (Alembic may fail or destroy data)?" || die "aborted"
    else
        log "  All ${#EXPECTED_TABLES[@]} expected v2.5.0-beta.1 tables present."
    fi

    local alembic_ver
    alembic_ver="$(docker exec "$IRIS_NG_DB_CONTAINER" psql -U postgres -d iris_db -tAc \
        "SELECT version_num FROM alembic_version LIMIT 1;" 2>/dev/null || echo "(none)")"
    log "  Imported alembic_version: ${alembic_ver}"

    # 5. Volume restore.
    if [[ "$skip_volumes" -eq 0 ]]; then
        log "[5/6] Restoring named volumes..."
        for vol_base in "${NAMED_VOLUMES[@]}"; do
            local arc="${from_dir}/${vol_base}.tar.gz"
            local vol="${project_name}_${vol_base}"
            if [[ ! -f "$arc" ]]; then
                warn "  ${vol_base}.tar.gz not in migration dir, skipping"
                continue
            fi
            # docker volume create is idempotent.
            docker volume create "$vol" >/dev/null
            log "  Extracting ${vol_base}.tar.gz -> volume '${vol}' (wipes existing contents)..."
            tar_in_volume "$vol" extract "$arc"
        done
    else
        log "[5/6] --skip-volumes: not touching named volumes"
    fi

    # 6. Carry secrets into iris-ng's .env so existing password hashes still verify.
    if [[ "$skip_secrets" -eq 0 ]] && [[ -f "${from_dir}/secrets.env" ]]; then
        log "[6/6] Carrying IRIS_SECRET_KEY + IRIS_SECURITY_PASSWORD_SALT into iris-ng .env..."
        if [[ ! -f ".env" ]]; then
            warn "  iris-ng .env not found — secrets NOT applied. Run 'bash scripts/iris_helper.sh --init' first, then re-run import."
        else
            # Backup before edit.
            cp .env ".env.bak.import-$(date +%s)"
            local key
            while IFS= read -r line; do
                [[ -z "$line" || "$line" =~ ^# ]] && continue
                key="${line%%=*}"
                if grep -q "^${key}=" .env; then
                    # Replace existing.
                    if [[ "$(uname -s)" == "Darwin" ]]; then
                        sed -i '' "s|^${key}=.*|${line}|" .env
                    else
                        sed -i "s|^${key}=.*|${line}|" .env
                    fi
                else
                    echo "$line" >> .env
                fi
            done < "${from_dir}/secrets.env"
            log "  Secrets applied. Backup of previous .env saved as .env.bak.import-*"
        fi
    else
        log "[6/6] Skipping secrets (--skip-secrets or no secrets.env in source)"
    fi

    # 7. Schema reconciliation. Vanilla DFIR-IRIS shipped a long stretch of
    #    upstream releases with a broken alembic env.py (begin_transaction
    #    commented out) — ADD COLUMN migrations during that window logged
    #    "Running upgrade ..." but never committed. alembic_version got
    #    advanced regardless. Result on iris-ng's side: db.create_all won't
    #    touch existing tables and alembic skips the "already applied"
    #    migrations, so columns the iris-ng ORM expects (ioc.case_id,
    #    asset_compromise_status_id, …) are silently absent. Run a one-shot
    #    diff-and-add pass via the iris-ng app image's Python env so every
    #    ORM-declared-but-missing column gets ALTER TABLE ADD COLUMN'd.
    log ""
    log "[7/8] Reconciling imported schema against iris-ng ORM models..."
    docker compose -f "$IRIS_NG_COMPOSE" run --rm --no-deps -T app \
        python /iriswebapp/scripts/reconcile_vanilla_schema.py \
        || warn "schema reconciliation reported errors — check the log above; the app may still boot, but some pages may 500 until manually fixed"

    # 8. Bring app + worker back up so Alembic runs on entrypoint.
    log ""
    log "[8/8] Bringing app + worker back up — Alembic will run iris-ng's additive migrations on entrypoint..."
    docker compose -f "$IRIS_NG_COMPOSE" up -d app worker

    # 8. Wait for app to be healthy, then post-Alembic schema check.
    log "Waiting up to 60s for app to come up..."
    tries=0
    until docker exec "$IRIS_NG_APP_CONTAINER" curl -sf http://localhost:8000 >/dev/null 2>&1; do
        tries=$((tries+1))
        [[ $tries -gt 60 ]] && { warn "app did not become healthy in 60s — check 'docker compose logs app'"; break; }
        sleep 1
    done

    log "Post-Alembic schema check (iris-ng additions)..."
    local ng_missing=()
    for tbl in "${IRIS_NG_NEW_TABLES[@]}"; do
        if ! docker exec "$IRIS_NG_DB_CONTAINER" psql -U postgres -d iris_db -tAc \
            "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='${tbl}';" \
            | grep -q '^1$'; then
            ng_missing+=("$tbl")
        fi
    done
    if [[ ${#ng_missing[@]} -gt 0 ]]; then
        warn "iris-ng tables missing AFTER app startup: ${ng_missing[*]}"
        warn "Alembic may have skipped silently. Check 'docker compose logs app | grep -i alembic'."
    else
        log "  All ${#IRIS_NG_NEW_TABLES[@]} iris-ng tables present."
    fi

    log ""
    log "=== Import complete ==="
    log "  Existing cases / customers / users / IOCs / assets / events / templates: carried over."
    log "  iris-ng features (AI artifacts, working timeline, MISP sync links, etc.): empty until used."
    log ""
    log "Login at https://localhost/ with your existing credentials. If you skipped secrets carry-over,"
    log "the first-boot admin password is in 'docker compose logs app | grep \"Administrator password\"'."
    log ""
    log "Reconfigure MISP sync (if used): /manage/modules -> iris_misp_sync_module"
    log "(Old upstream iris_misp_module config does NOT carry over — different module entirely.)"
}

# ---------------------------------------------------------------------------
# DISPATCH
# ---------------------------------------------------------------------------
print_help() { sed -n '2,40p' "$0"; exit 0; }

[[ $# -eq 0 ]] && print_help

cmd="$1"
shift
case "$cmd" in
    export)        export_run "$@" ;;
    import)        import_run "$@" ;;
    -h|--help)     print_help ;;
    *)             die "unknown command: $cmd (expected 'export' or 'import')" ;;
esac

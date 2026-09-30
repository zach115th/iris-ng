#!/usr/bin/env bash
# iris-ng: update a clone-based Docker Compose install in one go.
#
# Run from the clone directory on the Docker host:
#
#   scripts/update.sh                      # to the tip of origin/main
#   scripts/update.sh --ref IRIS-NG-v2.4.0 # to a release tag
#   scripts/update.sh --dry-run            # show the plan, change nothing
#
# What it does, in order, stopping at the first failure:
#   1. checks it runs inside the clone, that docker compose and .env exist,
#      and that the working tree carries no local edits the reset would lose;
#   2. fetches, resolves the target, and reports what the update brings:
#      commits, database migrations, changed images, the target version;
#   3. backs the database up with pg_dump into backups/ (a migration is
#      one-way: this file is the only road back) unless --skip-backup;
#   4. resets the checkout to the target;
#   5. rebuilds and recreates app, worker, ai_worker and nginx (the nginx
#      image is the one people forget), and db only when docker/db changed;
#   6. brings up the guest-portal tunnel agent when PORTAL_TUNNEL_AGENT_KEY
#      is set in .env (--enable-portal generates the key first);
#   7. waits for the app's "IRIS IS READY" line and prints the result.
#
# Environment (optional, for installs that run compose with extra files):
#   IRIS_COMPOSE_PROJECT   passed as `docker compose -p <name>`
#   IRIS_COMPOSE_EXTRA     extra compose arguments, e.g. "-f my.override.yml"
#
# First time, on a checkout that predates this script (it lives on main since
# IRIS-NG-v2.3.0 + 5): fetch just the file, then run it — it updates the rest.
#
#   git fetch origin && git show origin/main:scripts/update.sh > scripts/update.sh
#   bash scripts/update.sh
#
# This is a host-side wrapper around the documented manual commands. It never
# runs inside a container and never touches the database beyond pg_dump.

set -euo pipefail

REF="origin/main"
DRY_RUN=0
SKIP_BACKUP=0
ENABLE_PORTAL=0
ASSUME_YES=0
DISCARD_LOCAL=0
READY_TIMEOUT="${IRIS_READY_TIMEOUT:-600}"

usage() {
    sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
    cat <<'EOF'

Options:
  --ref <tag|branch|commit>  target (default: origin/main)
  --dry-run                  print the plan and exit
  --skip-backup              do not run pg_dump first (you have your own backup)
  --enable-portal            generate PORTAL_TUNNEL_AGENT_KEY in .env if missing
                             and start the guest-portal tunnel agent
  --discard-local            allow the reset to throw away local edits to
                             tracked files (untracked files are never touched)
  --yes                      do not ask for confirmation
  -h, --help                 this text
EOF
}

log()  { printf '\n==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --ref) [ $# -ge 2 ] || die "--ref needs a value"; REF="$2"; shift 2 ;;
        --ref=*) REF="${1#--ref=}"; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --skip-backup) SKIP_BACKUP=1; shift ;;
        --enable-portal) ENABLE_PORTAL=1; shift ;;
        --discard-local) DISCARD_LOCAL=1; shift ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
done

# ---------------------------------------------------------------- preflight
log "Preflight"
command -v git >/dev/null 2>&1 || die "git is not installed"
docker compose version >/dev/null 2>&1 || die "'docker compose' is not available (Compose v2 is required)"
TOP="$(git rev-parse --show-toplevel 2>/dev/null)" || die "not inside a git clone — run this from the iris-ng directory"
cd "$TOP"
[ -f docker-compose.dev.yml ] || die "docker-compose.dev.yml not found in $TOP — is this an iris-ng clone?"
[ -f .env ] || die ".env not found — copy .env.model to .env and set the passwords first"

COMPOSE=(docker compose)
[ -n "${IRIS_COMPOSE_PROJECT:-}" ] && COMPOSE+=(-p "$IRIS_COMPOSE_PROJECT")
COMPOSE+=(-f docker-compose.dev.yml)
# shellcheck disable=SC2206
EXTRA=(${IRIS_COMPOSE_EXTRA:-})
dc()  { "${COMPOSE[@]}" "${EXTRA[@]}" "$@"; }
dcp() { "${COMPOSE[@]}" -f docker-compose.portal.yml "${EXTRA[@]}" "$@"; }

env_value() {  # env_value KEY -> value from .env (last assignment wins; empty when absent)
    { grep -E "^${1}=" .env 2>/dev/null || true; } | tail -n 1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}
PG_USER="$(env_value POSTGRES_USER)"; PG_USER="${PG_USER:-postgres}"
PG_DB="$(env_value POSTGRES_DB)";     PG_DB="${PG_DB:-iris_db}"

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    if [ "$DISCARD_LOCAL" -eq 1 ]; then
        info "local edits to tracked files will be discarded (--discard-local)"
    else
        git status --short --untracked-files=no | sed 's/^/    /'
        die "the working tree has local edits to tracked files; the reset would destroy them. Commit or stash them, or pass --discard-local"
    fi
fi
info "clone: $TOP"
info "compose: ${COMPOSE[*]} ${EXTRA[*]:-}"

# ------------------------------------------------------------------ resolve
log "Fetching"
git fetch --all --tags --prune --quiet
CURRENT="$(git rev-parse HEAD)"
TARGET=""
for cand in "refs/tags/$REF" "refs/remotes/$REF" "refs/remotes/origin/$REF" "$REF"; do
    if TARGET="$(git rev-parse --verify --quiet "${cand}^{commit}")"; then break; fi
    TARGET=""
done
[ -n "$TARGET" ] || die "cannot resolve '$REF' as a tag, a remote branch or a commit"

cur_short="$(git rev-parse --short "$CURRENT")"
tgt_short="$(git rev-parse --short "$TARGET")"
version_at() { { git show "$1:source/app/configuration.py" 2>/dev/null || true; } | { grep -oE "IRIS_VERSION *= *['\"][^'\"]+" || true; } | sed -E "s/.*['\"]//" ; }
cur_version="$(version_at "$CURRENT")"; tgt_version="$(version_at "$TARGET")"

PORTAL_ONLY=0
if [ "$CURRENT" = "$TARGET" ]; then
    if [ "$ENABLE_PORTAL" -eq 1 ]; then
        # Nothing to update; --enable-portal alone still has work to do.
        PORTAL_ONLY=1
        info "already at $tgt_short (${tgt_version:-unknown version}); only the guest portal will be set up"
    else
        info "already at $tgt_short (${tgt_version:-unknown version}); nothing to do"
        exit 0
    fi
fi

log "Plan"
if git merge-base --is-ancestor "$CURRENT" "$TARGET"; then
    n_commits="$(git rev-list --count "$CURRENT..$TARGET")"
    info "from $cur_short (${cur_version:-?}) to $tgt_short (${tgt_version:-?}): $n_commits commit(s) ahead"
else
    info "from $cur_short (${cur_version:-?}) to $tgt_short (${tgt_version:-?}): histories diverge — this is a hard reset, not a fast-forward"
fi
n_migrations="$(git diff --name-only --diff-filter=A "$CURRENT" "$TARGET" -- source/app/alembic/versions | grep -c '\.py$' || true)"
db_changed=0;    git diff --quiet "$CURRENT" "$TARGET" -- docker/db    || db_changed=1
nginx_changed=0; git diff --quiet "$CURRENT" "$TARGET" -- docker/nginx || nginx_changed=1
info "database migrations: $n_migrations (one-way; the app applies them at boot)"
info "db image: $([ $db_changed -eq 1 ] && echo 'changed — will rebuild' || echo 'unchanged')"
info "nginx image: $([ $nginx_changed -eq 1 ] && echo 'changed' || echo 'unchanged') — rebuilt either way (cheap, and the one people forget)"
SERVICES=(app worker ai_worker nginx)
[ $db_changed -eq 1 ] && SERVICES=(db "${SERVICES[@]}")

portal_key="$(env_value PORTAL_TUNNEL_AGENT_KEY)"
portal=0
if [ "$ENABLE_PORTAL" -eq 1 ]; then
    portal=1
    if [ -n "$portal_key" ]; then
        info "guest portal: PORTAL_TUNNEL_AGENT_KEY already set — the tunnel agent will be (re)built"
    else
        info "guest portal: a PORTAL_TUNNEL_AGENT_KEY will be generated into .env and the tunnel agent started"
    fi
elif [ -n "$portal_key" ]; then
    portal=1
    info "guest portal: PORTAL_TUNNEL_AGENT_KEY is set — the tunnel agent will be (re)built"
else
    info "guest portal: off (no PORTAL_TUNNEL_AGENT_KEY in .env; --enable-portal turns it on)"
fi
if [ $portal -eq 1 ] && [ ! -f docker-compose.portal.yml ]; then
    info "note: docker-compose.portal.yml is not in the current checkout; it will be used only if the target carries it"
fi

if [ $PORTAL_ONLY -eq 1 ]; then
    info "steps: $([ -z "$portal_key" ] && echo 'write the key to .env ; recreate app ; ' || echo '')tunnel agent"
else
    info "steps: $([ $SKIP_BACKUP -eq 1 ] && echo 'NO backup (--skip-backup)' || echo "pg_dump -> backups/") ; git reset --hard $tgt_short ; rebuild + recreate ${SERVICES[*]}$([ $portal -eq 1 ] && echo ' ; tunnel agent')"
fi

if [ "$DRY_RUN" -eq 1 ]; then
    log "Dry run — nothing changed"
    exit 0
fi
if [ "$ASSUME_YES" -ne 1 ]; then
    [ -t 0 ] || die "not a terminal: pass --yes to proceed without confirmation"
    printf '\nProceed? [y/N] '
    read -r answer
    case "$answer" in y|Y|yes|YES) ;; *) echo "aborted"; exit 1 ;; esac
fi

# ------------------------------------------------------------------- backup
if [ $PORTAL_ONLY -eq 1 ]; then
    :
elif [ "$SKIP_BACKUP" -eq 1 ]; then
    log "Backup skipped (--skip-backup)"
else
    log "Backing the database up"
    dc ps --status running --services 2>/dev/null | grep -qx db || die "the db service is not running; start the stack first, or pass --skip-backup if you have a backup"
    mkdir -p backups
    dump="backups/iris-$(date +%Y%m%d-%H%M%S)-${cur_short}.dump"
    dc exec -T db pg_dump -U "$PG_USER" -Fc "$PG_DB" > "$dump"
    size="$(wc -c < "$dump" | tr -d ' ')"
    [ "$size" -gt 1024 ] || die "the dump is suspiciously small ($size bytes): $dump"
    info "wrote $dump ($size bytes) — restore with: docker compose exec -T db pg_restore -U $PG_USER -d $PG_DB --clean --if-exists < $dump"
fi

# ---------------------------------------------------------------- checkout
if [ $PORTAL_ONLY -ne 1 ]; then
    log "Updating the checkout to $tgt_short"
    git reset --hard --quiet "$TARGET"
    info "now at $(git rev-parse --short HEAD) $(git log -1 --format=%s | cut -c1-70)"
fi

# ------------------------------------------------------------- portal key
KEY_GENERATED=0
if [ $portal -eq 1 ] && [ -z "$portal_key" ]; then
    KEY_GENERATED=1
    log "Generating PORTAL_TUNNEL_AGENT_KEY"
    if command -v openssl >/dev/null 2>&1; then
        portal_key="$(openssl rand -hex 32)"
    else
        portal_key="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    fi
    if grep -qE '^PORTAL_TUNNEL_AGENT_KEY=' .env; then
        sed -i.bak -E "s|^PORTAL_TUNNEL_AGENT_KEY=.*|PORTAL_TUNNEL_AGENT_KEY=${portal_key}|" .env && rm -f .env.bak
    else
        printf '\n# Shared secret between the guest-portal tunnel agent and the app (scripts/update.sh --enable-portal)\nPORTAL_TUNNEL_AGENT_KEY=%s\n' "$portal_key" >> .env
    fi
    info "written to .env (the app reads it when recreated below)"
fi

# ----------------------------------------------------------------- rebuild
START_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RECREATED=0
if [ $PORTAL_ONLY -eq 1 ]; then
    if [ $KEY_GENERATED -eq 1 ]; then
        log "Recreating app so it reads the new key"
        dc up -d --force-recreate --no-deps app
        RECREATED=1
    fi
else
    log "Rebuilding and recreating: ${SERVICES[*]}"
    dc up -d --build --force-recreate "${SERVICES[@]}"
    RECREATED=1
fi

if [ $portal -eq 1 ]; then
    if [ -f docker-compose.portal.yml ]; then
        log "Guest-portal tunnel agent"
        dcp up -d --build tunnel
    else
        info "guest portal: docker-compose.portal.yml is not in this version; the tunnel agent was not started"
    fi
fi

# ------------------------------------------------------------------- ready
if [ $RECREATED -eq 1 ]; then
    log "Waiting for the app (up to ${READY_TIMEOUT}s)"
    deadline=$(( $(date +%s) + READY_TIMEOUT ))
    ready=0
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if dc logs --since "$START_TS" app 2>/dev/null | grep -q "IRIS IS READY"; then ready=1; break; fi
        sleep 5
    done
    if [ $ready -ne 1 ]; then
        dc ps
        dc logs --since "$START_TS" --tail 40 app || true
        die "the app did not report ready within ${READY_TIMEOUT}s — see the log above (a failed migration shows here; the backup is in backups/)"
    fi
fi

log "Done"
if [ $PORTAL_ONLY -eq 1 ]; then
    info "running $(git rev-parse --short HEAD) (${tgt_version:-unknown version}), unchanged"
else
    info "running $(git rev-parse --short HEAD) (${tgt_version:-unknown version}); $n_migrations migration(s) applied at boot"
fi
if [ $portal -eq 1 ] && [ -f docker-compose.portal.yml ]; then
    info "guest portal: the tunnel agent is up — Settings > Guest Portal shows its status within about fifteen seconds"
fi
if [ $n_migrations -gt 0 ] && [ "$SKIP_BACKUP" -ne 1 ]; then
    info "keep the backup until you have looked around; the old version cannot start on the migrated database"
fi
info "what changed: CHANGELOG.md, and the wiki"

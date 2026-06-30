# iris-ng

> A community fork of [DFIR-IRIS](https://github.com/dfir-iris/iris-web) v2.5.0-beta.1,
> with native MISP integration, MISP nomenclature alignment, and an in-tree AI assistant
> layer. See [`FORK.md`](./FORK.md) for attribution + the rationale.

[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)](./LICENSE.txt)

A collaborative incident-response platform. Forked from DFIR-IRIS because upstream paused
feature development in late 2024 and stranded `v2.5.0-beta.1` in beta.

## Compatibility goal

- **API-compatible with IRIS v2.5.0-beta.1** — existing n8n workflows and IRIS API
  clients continue to work unchanged.
- **Database is not backwards-compatible** — iris-ng adds new tables and columns that
  vanilla DFIR-IRIS does not have. A migration script is provided (see
  [Migrating from vanilla DFIR-IRIS](#migrating-from-vanilla-dfir-iris)).
- Upstream bugfixes can be cherry-picked into the `upstream-fixes` branch when they land.

## What's new vs upstream

### MISP integration

- Native MISP sync module (`source/iris_misp_sync_module/`) — case ↔ MISP event,
  IOC ↔ MISP attribute; the IOC's TLP drives distribution + attribute tags.
- MISP nomenclature alignment via `IocType.type_taxonomy` — every IOC type maps to a
  MISP attribute type, with an LLM fallback for the few that lack a direct match.
- Bundled MISP taxonomy + galaxy catalog (169 taxonomies, 122 galaxies, 66k machine-tag
  entries) powers tag autocomplete across every object in the UI.

### AI assistant layer (`source/app/iris_engine/ai/`)

- **Async AI request queue** — `POST` to any AI endpoint returns `202 + task_id`
  immediately; a dedicated `ai_worker` container runs jobs off an `ai_queue` so long
  LLM calls never block a web worker. Poll `GET /api/v2/ai/jobs/<id>` for status.
- **Executive case summary panel** — multi-pass map-reduce (4 domain specialists run in
  parallel, a synthesizer composes the output). Handles large cases without blowing past
  local-model context limits. Cached; re-runs only the affected specialist when a single
  object changes.
- **Case-scoped chat assistant** on six case-detail tabs (Notes / Timeline / Assets /
  IOC / Tasks / Evidence) with per-tab specialized prompts and full case context.
- **Per-event AI analysis right-drawer** — click any timeline card body for a 3-paragraph
  triage analysis; cached per event.
- **Running master-timeline AI analysis panel** — always-visible prose narrative (What
  the timeline tells us / What's still uncertain / Where to dig next). Flag-aware:
  reviewed events contribute with HIGH confidence, flagged events with MEDIUM.
- **MITRE ATT&CK + Unified Kill Chain v1.3 suggestions** on event create/edit — returns
  up to 4 validated ATT&CK technique IDs and a single UKC phase; a `Set Event Category`
  button auto-selects the matching dropdown option.
- **IOC extraction from note text** — type-validated against the live `IocType` table,
  per-type regex shape sanity, noise-flag affordance (CDN / public resolver / sinkhole),
  dedup against existing case IOCs. Available in both the modal and inline note editors.
- **IOC ↔ Note provenance back-link** — `+add` in the IOC extractor auto-creates a
  link; linked notes render as violet pill chips on the edit-IOC modal.
- **AI-suggested evidence type on upload** — auto-fires alongside the hash/size step;
  auto-applies to the type dropdown with a confidence chip. Analyst override clears it.
- **AI-suggested case template on alert escalation** — auto-fires when the Escalate
  modal opens; validated against the full live template catalog. 13/13 match in testing.
- **AI tag suggester** (MISP taxonomies + galaxies) — ✨ Suggest tags pill on IOC,
  asset, task, and event modals; output validated against the bundled 66k-entry catalog.
- **IOC cluster narrative** — AI-generated campaign brief per correlation cluster,
  server-cached in `case_ai_artifact`, rendered on the Correlation dashboard tab.
- **Two-slot AI backend** — primary + alternate backend configured in `/manage/settings`
  with a radio to switch active slot; per-feature backend overrides let individual AI
  surfaces route to a different slot.

### Dual timeline

- **Working timeline** — a right-side review panel on the master-timeline page for
  staging and reviewing forensic events before promoting them to the master timeline.
- **Hayabusa import** (`POST /api/v2/cases/<cid>/working-timeline/import/hayabusa`) —
  collapses sigma-rule fan-out on `(Timestamp, Computer, Channel, EventID, RecordID)`.
- **EZ Tools / KAPE import** (`…/import/eztools`) — auto-detects 11 sub-formats
  (EvtxECmd, MFT, Prefetch, AppCompat, Amcache, RecycleBin, JumpList, LNK) from column
  headers; stream-decoded, capped at 25k rows per import.
- **Master-timeline CSV → working timeline** — the existing "Upload CSV of events"
  picker now offers a Master / Working destination radio; routes to a new endpoint backed
  by `iris_master_csv_parser.py`.
- **Promote-time asset + IOC materialization** — promoting a working event auto-creates
  `CaseAssets` rows (hostname → Windows Computer/Server/DC heuristic; account →
  Windows Account AD/Local heuristic) and runs the AI IOC extractor (0.7 confidence
  threshold, noise-filtered).
- **Optional date-range filter on every import source** (From/To inclusive, server-side).
- **Per-event ✨ Explain pill** — LLM triage explanation, 3-state toggle (reveal / hide
  / re-render from memory without an API call), cached in `case_ai_artifact`.

### Case relationships

- **Asset ↔ Evidence linking** — select2 picker on the asset modal; inverse view as
  violet pill chips on the evidence modal with deep-link back to the asset.
- **IOC ↔ Note provenance** — M2M `ioc_note_link` table; back-links as violet chips
  on the edit-IOC modal; a backfill script handles pre-existing notes.
- **Jira-style task linking** — `blocks` / `is blocked by`, `depends_on` / `is depended
  on by`; advisory cycle-detection warning on the linking POST; dependency-tree view
  (indented hierarchy) on the Tasks tab with a toggle between flat and tree layouts.

### Dashboard

- **Metrics tab** — case throughput, MTTR, sector / incident-type / customer breakdowns,
  time-tracking summary, all filterable by date range.
- **Inventory tab** — barcode ↔ physical evidence drive management; lookup resolves a
  drive to its current case and evidence items; wipe-and-rotate lifecycle support.
- **Correlation tab** — IOC cross-case correlation engine:
  - Cluster cards (union-find by shared `(ioc_value, ioc_type_id)`) with decay score
    (exponential half-life per IOC type × tag-weight multipliers) and IOC confidence
    (log2 curve, ~40% at threshold, ~95% at 36 shared IOCs).
  - One-click `Apply campaign tag` (tags all cases + all shared IOCs in the cluster).
  - AI-generated cluster narrative cached per cluster.
  - D3 v7 force-directed graph — drag to pan, scroll to zoom (0.2×–4×); cluster filter
    redraws the graph to show only the selected cluster's nodes and edges.
  - Shared IOC click-through drawer (per-case enrichment, linked notes, IOC tags).
  - Per-IOC cross-case panel on the edit-IOC modal ("Check other cases").

### Operations + case management

- **Analyst time tracking** — clock icon in the case header; 15-minute increment
  enforced at the DB level; edit-locked on case close; opt-in "you haven't logged time"
  nudge; cross-case reporting (by customer / analyst / sector / incident type) + per-case
  breakdown on the case-edit modal; estimated case cost from per-analyst hourly rates.
- **Analyst skills + ad-hoc team building** — 34-skill / 8-category catalog seeded on
  boot; admin and self-service skill assignment; per-case team assembly with a greedy
  set-cover scorer (✨ Suggest); `/manage/teams` coverage + active-case assignment page.
- **Case export/import** — AES-256-GCM encrypted `.iris-case` format; PBKDF2-HMAC-SHA256
  key derivation (260k iterations); password in the request body (not the URL).
- **Master timeline events default to flagged** — new events arrive with a "needs review"
  flag; flag-aware timeline analysis uses `MEDIUM` confidence for flagged events.
- **Event history panel** — collapsible color-coded lifecycle log from
  `CasesEvent.modification_history` JSONB; accessible from the event modal's ⋮ dropdown.
- **Mandatory sector tag (soft-enforced)** — create-case modal requires a DHS CIIP /
  threatmatch sector selection; server-side warns (not rejects) if missing; customer
  record carries default sectors that new cases inherit.
- **Physical evidence custody fields** — `created_by` and `barcode` on every evidence
  record, with a barcode ↔ drive link maintained automatically. `physical_location` lives
  on the drive (`EvidenceDrive`), not the evidence row.

### Settings + admin

- **Tabbed `/manage/settings`** — General / Security / AI / Analyst / System; tab
  selection persisted in `localStorage`; single form, Save works from any tab.
- **Two-slot AI backend** — primary + alternate backends with a global active-slot radio
  and per-feature overrides (pin individual AI surfaces to a specific slot).
- **Unified Kill Chain v1.3 Event Categories** — 7 missing UKC phases added to the
  Event Category dropdown via `post_init` (Reconnaissance, Resource Development,
  Delivery, Social Engineering, Exploitation, Pivoting, Objectives).

## Migrating from vanilla DFIR-IRIS

iris-ng is purely additive over v2.5.0-beta.1 (new tables and columns only — no
renames, no removals), but vanilla DFIR-IRIS cannot connect to an iris-ng database
without the schema additions in place.

`scripts/import_vanilla_db.sh` handles the full migration: Postgres dump + restore,
named-volume copy (uploaded evidence, report templates), secret carry-over, and a
post-restore schema sanity check.

```bash
# On the OLD host (vanilla DFIR-IRIS)
bash scripts/import_vanilla_db.sh export --project iris-web --out ./iris-export

# Move iris-export/ to the new host, then:
bash scripts/import_vanilla_db.sh import --from ./iris-export
```

Supported source versions: v2.4.x and v2.5.0-beta.1. The script warns if it detects
a partially-committed upstream migration history (a known upstream bug — see the script
header for details).

If you are upgrading an existing iris-ng instance (not migrating from vanilla), use:

```bash
docker compose -f docker-compose.dev.yml up -d --build --force-recreate
```

The `--force-recreate` flag is required — a plain `--build` leaves the `worker` and
`ai_worker` containers on the old image, causing ORM/schema skew.

## Run it

```bash
# 1. Clone
git clone https://github.com/zach115th/iris-ng.git
cd iris-ng

# 2. Generate self-signed dev certs for nginx
bash scripts/generate_dev_certs.sh

# 3. Bootstrap .env (random secrets + first-boot admin password)
bash scripts/iris_helper.sh --init

# 4. Bring up the stack (dev compose)
docker compose -f docker-compose.dev.yml up -d --build
```

UI on `https://localhost` (HTTPS, port 443). The browser will warn about the self-signed
cert on first visit — accept the warning (`Advanced` → `Proceed`).

The first-boot admin username is `administrator`. Get the generated password from logs:

```bash
docker compose -f docker-compose.dev.yml logs app | grep "Administrator password"
```

Or seed it via `IRIS_ADM_PASSWORD` in `.env` before the first start.

### Optional features

- **MISP sync** — set `MISP_URL` and `MISP_API_KEY` in `.env`, then enable the
  `iris_misp_sync` module under `/manage/modules` after first boot.
- **AI assistant** — configure backend URL / API key / model under `/manage/settings`
  (defaults work with a local LM Studio at `http://<lm-studio-host>:1234/v1`). The
  free `openai/gpt-oss-20b` model is what the AI surfaces are tuned against. AI
  requests are queued through the `ai_worker` container — LLM calls never block a web
  worker. A second backend slot lets you route specific AI surfaces to a different model.

## Stack

Six containers: `app` (Flask + SocketIO), `db` (PostgreSQL), `rabbitmq`,
`worker` (Celery general worker), `ai_worker` (Celery AI worker — single-concurrency,
GPU-bound), `nginx`. See [`architecture.md`](./architecture.md) for the layered code
design (blueprints → business → datamgmt; cross-layer imports forbidden).

## Branches

- `main` — primary branch.
- `develop` — active work; feature commits land here before merging to `main`.
- `upstream-fixes` — created lazily if upstream ships a bugfix worth cherry-picking.

## Commit conventions

Inherited from upstream (`CODESTYLE.md`):

- `[ADD]` / `[FIX]` / `[IMP]` / `[DEL]` action prefix.
- With issue: `[#123][FIX] message`.
- Python: f-strings only, one import per line, function names include the module name
  (e.g. `iocs_create`).
- DB schema changes ship an Alembic migration. Define `CHECK` constraints on the ORM
  model's `__table_args__` (not just in the migration) — IRIS runs `db.create_all()`
  before alembic, so migration-only constraints are dropped.

## License

LGPL-3.0. See [`LICENSE.txt`](./LICENSE.txt). Modifications must remain LGPL.

## Acknowledgements

DFIR-IRIS by Airbus CyberSecurity (SAS) and the open-source community. Original repo at
<https://github.com/dfir-iris/iris-web>. Sponsored historically by Deutsche Telekom
Security GmbH.

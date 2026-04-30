# iris-ng

> A community fork of [DFIR-IRIS](https://github.com/dfir-iris/iris-web) v2.5.0-beta.1,
> with native MISP integration, MISP nomenclature alignment, and an in-tree AI assistant
> layer. See [`FORK.md`](./FORK.md) for attribution + the rationale.

[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)](./LICENSE.txt)

A collaborative incident-response platform. Forked from DFIR-IRIS because upstream paused
feature development in late 2024 and stranded `v2.5.0-beta.1` in beta.

## Compatibility goal

- **Drop-in compatible with IRIS v2.5.0-beta.1** (API + database) until forced to change.
- Existing n8n workflows and IRIS API clients should continue to work unchanged.
- Upstream bugfixes can be cherry-picked into the `upstream-fixes` branch when they land.

## What's new vs upstream

- Native MISP sync module (`source/iris_misp_sync_module/`) — case ↔ MISP event,
  IOC ↔ MISP attribute, with the IOC's TLP driving distribution + tags.
- MISP nomenclature alignment via `IocType.type_taxonomy` — IOC types map to MISP
  attribute types, with an AI fallback for the few that don't have a direct match.
- In-tree AI assistant layer (`source/app/iris_engine/ai/`):
  - Executive case summary panel (multi-pass map-reduce — handles big cases without
    blowing past local-model context windows).
  - Case-scoped chat assistant on six case-detail tabs (Notes / Timeline / Assets /
    IOC / Tasks / Evidence) with per-tab specialized prompts.
  - Per-event AI analysis right-drawer.
  - MITRE ATT&CK + Unified-Kill-Chain v1.3 phase suggestions on event create/edit.
  - IOC extraction from note text with type validation + noise-flag affordance.
  - AI-suggested evidence type on upload (auto-fires from filename + magic bytes).
  - AI-suggested case template on alert escalation.
- Asset ↔ Evidence linking + IOC ↔ Note provenance back-link (with violet inverse-view
  chips) — pairs the existing IOC ↔ Asset relationship.
- Jira-style task linking (`blocks` / `is blocked by`, `depends_on` / `is depended on by`)
  with advisory cycle-detection warnings.
- Admin-editable AI backend settings at `/manage/settings` — URL / API key / model /
  confidence threshold are configurable from the UI rather than env-only.

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
  free `openai/gpt-oss-20b` model is what the AI surfaces are tuned against.

## Stack

Five containers: `app` (Flask + SocketIO + Celery), `db` (PostgreSQL), `rabbitmq`,
`worker` (Celery worker), `nginx`. See [`architecture.md`](./architecture.md) for the
layered code design (blueprints → business → datamgmt; cross-layer imports forbidden).

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

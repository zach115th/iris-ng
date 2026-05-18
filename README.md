# iris-ng

> A community fork of [DFIR-IRIS](https://github.com/dfir-iris/iris-web) v2.5.0-beta.1,
> with native MISP integration, MISP nomenclature alignment, and an in-tree AI assistant
> layer. See [`FORK.md`](./FORK.md) for attribution + the rationale.

[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)](./LICENSE.txt)

A collaborative incident-response platform. Forked from DFIR-IRIS because upstream paused
feature development in late 2024 and stranded `v2.5.0-beta.1` in beta.

---

## What's new vs upstream

### Native MISP sync

Native MISP sync module (`source/iris_misp_sync_module/`) — case ↔ MISP event,
IOC ↔ MISP attribute, with the IOC's TLP driving distribution + tags.

MISP nomenclature alignment via `IocType.type_taxonomy` — IOC types map to MISP
attribute types, with an AI fallback for the few that don't have a direct match.
Each IOC carries a **MISP Report** tab showing its current sync state, and a
**Linked Notes** back-link recording where the IOC was sourced from.

![IOC editor showing ip-dst type, TLP amber, c2/network-traffic tags, and Linked Notes provenance back-link](docs/screenshots/ioc-linked-notes.png)

---

### AI assistant layer

In-tree AI assistant (`source/app/iris_engine/ai/`) across the full case lifecycle:

#### Executive case summary

Multi-pass map-reduce summary panel — handles large cases without blowing past
local-model context windows. Cached per content hash, stamped with model, prompt
version, and generation timestamp.

![Executive Case Summary panel showing an AI-generated TLP:AMBER incident summary with situation overview and current status](docs/screenshots/executive-summary.png)

#### Case-scoped chat on six tabs

Chat assistant scoped to the active case-detail tab (Notes / Timeline / Assets /
IOC / Tasks / Evidence) with per-tab specialized prompts. On the Notes tab the
assistant cross-references timeline, IOCs, and assets when needed.

![Notes tab showing the Notes Assistant panel with suggested prompts including Summarise all the notes and Are any notes contradicting the timeline](docs/screenshots/notes-assistant.png)

#### Timeline analysis

Full-width timeline analysis panel that summarises what the timeline tells us,
what remains uncertain, and where to dig next — generated across all visible events.

![Timeline tab showing the full-width TIMELINE ANALYSIS panel with What the Timeline Tells Us, What's Still Uncertain, and Where to Dig Next sections](docs/screenshots/timeline-analysis.png)

#### Per-event AI analysis

Right-drawer AI analysis on any timeline event: what the event implies, suggested
ATT&CK mappings with confidence ratings, and related events already in the case.

![Timeline with AI EVENT ANALYSIS drawer open for a Mimikatz detection, showing T1003.001 OS Credential Dumping suggestion and related events](docs/screenshots/event-analysis-drawer.png)

#### ATT&CK + Unified Kill Chain suggestions

MITRE ATT&CK and Unified Kill Chain v1.3 phase suggestions on event create/edit.
Events in the working timeline carry technique tags and per-event **Promote** /
**Reject** / **Explain** actions for inline triage.

![Working timeline view showing events tagged with ATT&CK technique IDs T1053.005 and S0111, with Promote, Reject, and Explain buttons per event](docs/screenshots/working-timeline-promote-reject.png)

The **Explain** button expands an inline AI panel describing what the detection
covers, what likely happened based on the log data, and a concrete triage hint.

![AI Explanation panel for a Possible LOLBIN event describing what was detected, what likely happened, and a triage hint about verifying the binary](docs/screenshots/ai-explanation-lolbin.png)

#### Other AI surfaces

- IOC extraction from note text with type validation + noise-flag affordance.
- AI-suggested evidence type on upload (auto-fires from filename + magic bytes).
- AI-suggested case template on alert escalation.

---

### Asset ↔ Evidence linking + IOC ↔ Note provenance

Asset-to-Evidence linking and IOC-to-Note provenance back-links — pairs the
existing IOC ↔ Asset relationship. All three relationship directions are navigable
from asset, evidence, and IOC records.

**Assets table** — compromise status, linked IOCs, and tags visible at a glance:

![Assets table showing WS-FIN-07 as a compromised Windows Computer with linked IOC secure-helpdesk-login.example.net and tags](docs/screenshots/assets-table.png)

**Asset editor** — linked IOC and linked evidence item both visible and navigable
from the same record:

![Asset editor for WS-FIN-07 showing Related IOC and Related Evidence fields linking to the phishing domain and disk image](docs/screenshots/asset-related-ioc-evidence.png)

**Evidence editor** — Linked Assets field records which asset the evidence
pertains to; hash, size, and type captured for chain-of-custody:

![Evidence editor for WS-FIN-07.E01 showing HDD image type, SHA1 hash, size, and Linked Assets back-link to WS-FIN-07](docs/screenshots/evidence-linked-assets.png)

---

### Jira-style task linking

`blocks` / `is blocked by`, `depends_on` / `is depended on by` — with advisory
cycle-detection warnings. Dependency status (Done / In progress / etc.) is visible
inline on the linked task chip.

![Task editor showing Linked Tasks section with BLOCKS, IS BLOCKED BY, DEPENDS ON, and IS DEPENDED ON BY fields](docs/screenshots/task-linking.png)

---

### Admin-editable AI backend settings

AI backend URL / API key / model / confidence threshold are configurable from the
UI at `/manage/settings` rather than env-only. No rebuild required to switch models
or point at a different endpoint.

---

## Run it

```bash
# 1. Clone
git clone https://github.com/zach115th/iris-ng.git
cd iris-ng

# 2. Generate self-signed dev certs for nginx
bash scripts/generate_dev_certs.sh

# 3. Bootstrap .env, build, and start the stack (one-shot)
bash scripts/iris_helper.sh --init
```

`--init` writes `.env` with fresh random secrets, builds the dev stack from
the in-tree Dockerfiles, and starts everything in daemon mode. If you'd rather
manage the stack yourself, skip `--init` and run
`docker compose -f docker-compose.dev.yml up -d --build` directly after
generating an `.env` from `.env.model`.

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

---

## Stack

Five containers: `app` (Flask + SocketIO + Celery), `db` (PostgreSQL), `rabbitmq`,
`worker` (Celery worker), `nginx`. See [`architecture.md`](./architecture.md) for the
layered code design (blueprints → business → datamgmt; cross-layer imports forbidden).

---

## Branches

- `main` — primary branch.
- `develop` — active work; feature commits land here before merging to `main`.
- `upstream-fixes` — created lazily if upstream ships a bugfix worth cherry-picking.

---

## Commit conventions

Inherited from upstream (`CODESTYLE.md`):

- `[ADD]` / `[FIX]` / `[IMP]` / `[DEL]` action prefix.
- With issue: `[#123][FIX] message`.
- Python: f-strings only, one import per line, function names include the module name
  (e.g. `iocs_create`).
- DB schema changes ship an Alembic migration. Define `CHECK` constraints on the ORM
  model's `__table_args__` (not just in the migration) — IRIS runs `db.create_all()`
  before alembic, so migration-only constraints are dropped.

---

## License

LGPL-3.0. See [`LICENSE.txt`](./LICENSE.txt). Modifications must remain LGPL.

## Acknowledgements

DFIR-IRIS by Airbus CyberSecurity (SAS) and the open-source community. Original repo at
<https://github.com/dfir-iris/iris-web>. Sponsored historically by Deutsche Telekom
Security GmbH.

# Changelog

All notable changes to `iris-next` (a fork of DFIR-IRIS) are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely, and
versions follow [SemVer 2.0](https://semver.org/) with `+iris-next.<build>` build
metadata appended to the upstream version we forked from.

Inherited upstream changelog (versions ≤ v2.5.0-beta.1) lives in upstream's release
notes: <https://github.com/dfir-iris/iris-web/releases>.

---

## [Unreleased]

Active work on `develop`.

---

## [v2.5.0-beta.1+iris-next.1] — 2026-06-28

All iris-next additions shipped on `develop` since the initial fork commit.

### Added — MISP integration

- **Native MISP sync module** (`source/iris_misp_sync_module/`) — bidirectional sync:
  case create/update → MISP event; IOC create/update → MISP attribute. IOC TLP drives
  distribution and attribute tags. Two new join tables (`misp_event_link`,
  `misp_attribute_link`) via Alembic `a1d9f5d4c2e8`.
- **`IocType.type_taxonomy`** — every IOC type maps to a MISP attribute type at startup
  from the bundled 193-type MISP catalog (`source/app/resources/misp.attribute_types.json`).
  Three IRIS-local types with no clean MISP match (`account`, `file-path`, `ip-any`) get
  an LLM fallback via `ai_type_resolver.py` (confidence ≥ 0.70).
- **MISP catalog enrichment of `/manage/tags/suggest`** — bundled taxonomy + galaxy
  catalog (169 taxonomies, 122 galaxies, 66k machine-tag entries) merges into the tag
  autocomplete endpoint so `tlp:*`, `dhs-ciip-sectors:*`, `misp-galaxy:threat-actor="…"`,
  etc. autocomplete before an analyst has applied them.
- **Celery fork-safety** — worker processes use `NullPool` (keyed on `"worker" in
  sys.argv`) so PostgreSQL connections are not inherited across `fork()`. Fixes
  `PGRES_TUPLES_OK` crashes under concurrent hook workloads.

### Added — AI assistant layer

- **Async AI request queue** (`source/app/iris_engine/ai/ai_jobs.py`, Alembic
  `a7c4e1f90d35`) — `POST` to any AI endpoint returns `202 + task_id`; dedicated
  `ai_worker` container (`ai_queue`, concurrency=1) runs jobs. Poll
  `GET /api/v2/ai/jobs/<id>`; `DELETE` cancels a queued job; `GET /api/v2/ai/jobs`
  lists (owner-scoped). Adding a new async surface = one entry in the `FEATURES` registry.
- **Executive case summary panel** — `POST /api/v2/cases/<id>/ai/summary`. Multi-pass
  map-reduce: 4 domain specialists (notes / timeline / iocs / assets) run in parallel, a
  synthesizer composes a 7-section executive output. Cached per specialist domain; re-runs
  only the affected specialist when a single object changes. Synthesizer routes to a
  smaller sibling model (`SYNTHESIZER_FAST_MODEL_MAP`) for Claude-family backends.
  Prompt lineage: `CaseSummarizationSystemPrompt-v4`.
- **Case-scoped chat assistant** — `POST /api/v2/cases/<id>/ai/ask`. Pill bar on six
  case-detail tabs (Notes / Timeline / Assets / IOC / Tasks / Evidence). Per-tab
  specialized system prompts; multi-turn, client owns history.
- **Per-event AI analysis drawer** — `POST /api/v2/cases/<id>/ai/timeline/events/<eid>/analysis`.
  Right slide-in on timeline card click; 3-paragraph triage; cached per event.
- **Running master-timeline AI analysis panel** — always-visible prose narrative on the
  timeline page. Flag-aware: reviewed events = HIGH confidence, flagged = MEDIUM.
  Auto-refreshes after any promote/add/edit/delete (1.5s debounce, cache-keyed).
  Prompt `TimelineNarrativeSystemPrompt-v4`.
- **MITRE ATT&CK + UKC suggestions** on event create/edit — returns up to 4 validated
  ATT&CK technique IDs + a single UKC phase; `Set Event Category` button auto-selects
  the matching dropdown option.
- **IOC extraction from note text** — type-validated, per-type regex shape sanity,
  noise-flag affordance (CDN / public resolver / sinkhole / parked), dedup against
  existing case IOCs. Available in modal and inline editors. `Accept all` is async-serialized.
- **AI-suggested evidence type on upload** — auto-fires alongside the hash/size step;
  auto-applies to the type dropdown with a confidence chip. Analyst override clears it.
- **AI-suggested case template on alert escalation** — auto-fires when the Escalate
  modal opens; validated against the full live template catalog. 13/13 match in testing.
- **AI tag suggester** (MISP taxonomies + galaxies) — `✨ Suggest tags` pill on IOC,
  asset, task, and event modals. Output validated against the bundled 66k-entry catalog.
- **AI cluster narrative** — per correlation cluster; cached in `case_ai_artifact`;
  confidence + decay pills; footer shows `prompt_id · model · cached · generated_at`.
- **Two-slot AI backend + per-feature overrides** (Alembic `e9d2c5a3f8b1`,
  `a3f7d2c19b4e`) — primary + alternate backend with a global active-slot radio and a
  per-feature override table. `build_default_client(feature=)` resolves feature override
  → global slot → app.config. No restart needed when admins switch slots.

### Added — Dual timeline

- **Working timeline** — right-side review panel for staging forensic events before
  promoting to the master timeline. `case_working_event` table (Alembic `b9e1f4a72c83`).
- **Hayabusa import** (`…/import/hayabusa`) — collapses sigma-rule fan-out on
  `(Timestamp, Computer, Channel, EventID, RecordID)`.
- **EZ Tools / KAPE import** (`…/import/eztools`) — auto-detects 11 sub-formats from
  column headers; stream-decoded, capped at 25k rows. Handles oversized CSV cells via
  `csv.field_size_limit(sys.maxsize)`.
- **Master-timeline CSV → working timeline** — destination radio in the "Upload CSV"
  picker; backed by `iris_master_csv_parser.py`.
- **Optional date-range filter** (From/To inclusive, server-side) on every import source.
- **Promote-time asset materialization** — auto-creates `CaseAssets` rows with
  hostname/account type heuristics.
- **Promote-time AI IOC extraction** — confidence ≥ 0.70, noise-filtered, cross-links
  assets ↔ IOCs via `IocAssetLink`.
- **Per-event ✨ Explain pill** — 3-state toggle (reveal / hide / re-render from memory);
  bulk-joined in list response to avoid N+1 GETs.

### Added — Case relationships

- **Asset ↔ Evidence linking** (Alembic `f6c83a91d201`) — select2 picker on the asset
  modal; inverse view as violet pill chips on the evidence modal.
- **IOC ↔ Note provenance** (Alembic `d4f12a87bc56`) — auto-created on `+add` in the
  IOC extractor; back-links render as violet pill chips on the edit-IOC modal.
- **Jira-style task linking** (Alembic `e5b239c0d128`) — `blocks` / `is blocked by`,
  `depends_on` / `is depended on by`; advisory cycle-detection warning on POST;
  dependency-tree view with flat/tree toggle on the Tasks tab.

### Added — Dashboard

- **Metrics tab** — `GET /api/v2/dashboard/metrics`. Sections: throughput / MTTR,
  Sectors, Case Tagging, Time Tracking. 3-state flip card per section (table → donut →
  multi-year grouped bar). Independent year selectors per section.
- **Inventory tab** — barcode ↔ physical evidence drive management (`EvidenceDrive`,
  Alembic `b4d7e2f93a18`). Lookup resolves barcode → drive → current case + evidence.
  Wipe-and-rotate lifecycle; barcode auto-link on blur; inline drive location editor.
- **Correlation tab** — IOC cross-case correlation (no new DB tables):
  - Union-find clustering on shared `(ioc_value, ioc_type_id)` pairs.
  - Cluster decay score (exponential half-life per IOC type × tag-weight multipliers)
    and IOC confidence (log2 curve, ~40% at threshold, ~95% at 36 shared IOCs).
  - `Apply campaign tag` — tags all cases + all shared IOCs in the cluster.
  - D3 v7 force-directed graph — pan, zoom, cluster filter with graph redraw.
  - Shared IOC click-through drawer — per-case enrichment, note references rendered as
    markdown HTML via `mistletoe`.
  - Per-IOC cross-case panel on the edit-IOC modal.
  - TLP filter — only TLP:GREEN and TLP:CLEAR IOCs participate (prevents cross-case
    information leakage on a shared dashboard).

### Added — Operations + case management

- **Analyst time tracking** (Alembic `b7e4a2d51c93`) — clock icon in the case header;
  15-minute increment enforced by `CHECK` on `__table_args__`; edit-locked on case close;
  opt-in nudge (off by default). Cross-case reporting + estimated case cost from per-analyst
  hourly rates.
- **Analyst skills + ad-hoc team building** (Alembic `e1b6c4d83a92`, `b1c3e7f94d20`) —
  34-skill / 8-category catalog; admin + self-service assignment; greedy set-cover scorer;
  `/manage/teams` coverage + active-case assignment page.
- **Case export/import** — AES-256-GCM encrypted `.iris-case` format; PBKDF2-HMAC-SHA256
  key derivation (260k iterations); password in the request body. Wrong password → HTTP 400.
- **Master timeline events default to flagged** — new events arrive as "needs review";
  unflagged once reviewed. Flag-aware timeline analysis applies appropriate confidence.
- **Event history panel** — collapsible lifecycle log from `CasesEvent.modification_history`
  JSONB; accessible from the event modal's ⋮ dropdown.
- **Mandatory sector tag (soft-enforced)** — create-case modal requires DHS CIIP /
  threatmatch sector selection; server-side warns (not rejects); customer record inherits
  defaults.
- **Physical evidence custody fields** — `created_by` and `barcode` on evidence records;
  `drive_id` links evidence to its physical drive (Alembic `a8e3f1c64b27`).

### Added — Settings + admin

- **Tabbed `/manage/settings`** — General / Security / AI / Analyst / System; tab
  persisted in `localStorage`; single Save form.
- **Unified Kill Chain v1.3 Event Categories** — 7 missing phases added via `post_init`
  (Reconnaissance, Resource Development, Delivery, Social Engineering, Exploitation,
  Pivoting, Objectives — 22 categories total).

### Fixed

- **Alembic migration-commit bug** — upstream `env.py` had `begin_transaction()` commented
  out; column-adds on existing tables silently dropped. Restored.
- **Custom-attribute tab id mismatch** — `modal_attributes_nav.html` `href` used an
  underscore-free id while `modal_attributes_tabs.html` used `id="<name>_{{idx}}"`.
  Bootstrap tab JS couldn't switch panes. Nav `href` now mirrors pane `id=` verbatim.
- **amsifySuggestags `data-val` escape bug** — chip widget interpolated raw tag values
  into `data-val="..."` without escaping `"`, silently truncating every MISP taxonomy
  tag in `<ns>:<pred>="<value>"` form on save. Added `irisAttrEscape()` helper.
- **MISP `GET /tags/search` colon-name bug** — endpoint silently returns `[]` for any
  tag name containing `:`. Switched to `POST /tags/index` with `searchall`. Fixed every
  IOC TLP tag being missing after sync.
- **`is_safe_url` open-redirect** — replaced `urljoin`+netloc comparison (bypassed by
  triple-slash and single-slash URLs) with an explicit allowlist (paths starting with
  `/`, no scheme, no netloc, no `//` prefix, backslash-normalised first).
- **DOCX report rejected by Word** — `{{ case.description|markdown }}` block output
  nested inside `<w:r><w:t>` produced invalid OOXML. Fixed at template level + added
  `docx_repair.py` lxml-flatten as defense-in-depth.
- **Asset tab blank on `analysis_status_id = NULL`** — working-timeline promote created
  `CaseAssets` rows without a default analysis status; frontend JS threw before the
  state-reset path. Fixed in the frontend null-guard, `create_asset()`, and
  `asset_resolver._ensure_asset()`.
- **Working-timeline `event_date` missing `Z` suffix** — bare `dt.isoformat()` on naive
  datetimes let browsers parse UTC events as local time. Added `_iso_utc()` helper.
- **CSP `worker-src blob:`** — ACE editor's syntax-checking web worker blocked by
  `script-src 'self'` fallback. Added `worker-src blob:` to both nginx conf files.
- **GitHub Actions workflow permissions** — added `permissions: contents: read` to
  `ci.yml` to prevent inheriting org-wide read-write defaults.
- **CSV round-trip `event_source` overwrite** — import endpoint was overwriting per-row
  `event_source` with the modal-supplied default. Default is now a fallback only.
- **CSV `event_assets` `"name (Type)"` format tolerance** — EZ Tools / Hayabusa write
  asset cells as `"<name> (<type>)"`; import endpoint now strips the suffix and retries
  `get_asset_by_name`.

---

## [v2.5.0-beta.1+iris-next.0] — 2026-04-28

Initial fork-identity commit. Establishes `iris-next` as a downstream fork of DFIR-IRIS
v2.5.0-beta.1 without changing runtime behaviour.

### Added
- `FORK.md` — attribution to upstream, forking point, rationale, LGPL-3.0 obligations.
- `.gitattributes` — line-ending normalisation (LF for text, CRLF for `*.bat`/`*.cmd`)
  and binary patterns for shipped wheels/images.
- `CHANGELOG.md` — this file.
- `.gitignore` exception `!.env.model` so the env template stays tracked despite the
  blanket `.env*` rule.

### Changed
- `README.md` rewritten to identify the fork, the drop-in-compatibility goal, the
  branching model (`main` / `develop` / `upstream-fixes`), and inherited upstream commit
  conventions (`[ADD]/[FIX]/[IMP]/[DEL]`).
- `docker-compose.yml` image namespaces switched from `ghcr.io/dfir-iris/iriswebapp_*`
  to `iris-next/*`. Default tag changed from the stale `v2.4.20` to `latest`.
- `.env.model` image-name defaults updated to match.
- `source/app/configuration.py:268` — `IRIS_VERSION` bumped to
  `v2.5.0-beta.1+iris-next.0` (SemVer build metadata).
- `.bumpversion.cfg` — version regex extended to parse the `+iris-next.<build>` suffix;
  `current_version` follows.

### Unchanged (explicitly)
- API routes (legacy `/case|/manage/*` and `/api/v2/*`) — drop-in compatible.
- Database schema and Alembic migrations.
- Runtime logic, modules, hooks, the worker, the frontend.

---

## [baseline-v2.5.0-beta.1] — 2025-02-27 (upstream)

Pristine import of DFIR-IRIS v2.5.0-beta.1 (upstream commit `a4bfeda`).
Tagged `baseline-v2.5.0-beta.1` on `main` as the reference point for upstream
cherry-picks.

[Unreleased]: https://github.com/dfir-iris/iris-web/compare/v2.5.0-beta.1...HEAD
[v2.5.0-beta.1+iris-next.0]: ./
[baseline-v2.5.0-beta.1]: https://github.com/dfir-iris/iris-web/releases/tag/v2.5.0-beta.1

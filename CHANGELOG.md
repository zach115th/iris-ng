# Changelog

All notable changes to `iris-next` (a fork of DFIR-IRIS) are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely, and
versions follow [SemVer 2.0](https://semver.org/) with `+iris-next.<build>` build
metadata appended to the upstream version we forked from.

Inherited upstream changelog (versions ≤ v2.5.0-beta.1) lives in upstream's release
notes: <https://github.com/dfir-iris/iris-web/releases>.

---

## [Unreleased]

Active work on `main`.

---

## [IRIS-NG-v1.0.2] — 2026-08-04

### Fixed

- **CSRF token was sent as a header on two `/api/v2/` POSTs, which the validator
  never reads.** `ac_api_requires` validates through `FlaskForm().validate()`, and
  Flask-WTF supplies `request.get_json()` as that form's data — so the token must be
  a field in the body. The case notification bell's acknowledge call failed with
  HTTP 400 on every click, leaving the unread badge permanently stuck; the
  master-timeline AI panel's generate and re-run failed the same way, less visibly,
  because the panel kept serving previously cached output over GET.

- **Cluster decay score could exceed its own range.** Tag weights multiplied the
  score through an unbounded product, so any fresh IOC carrying a single galaxy tag
  scored 1.40 and the UI rendered it as "140%" (fully stacked reached 464%). Tags now
  scale the type half-life instead, which confines the result to [0, 1] by
  construction and matches what the tags actually describe.

- **Decay aged indicators from the oldest case that contained them**, so a campaign
  scored staler the longer it persisted. Re-observation is evidence an indicator is
  still live; the anchor is now the most recent sighting.

- **Free-text tag keywords were matched as substrings**, so `rat` matched inside
  `misp-galaxy:sector="corporate"` and `apt` inside `adapter`. Matching is now on word
  boundaries.

### Changed

- **Cluster confidence is now weighted by rarity and credibility rather than being a
  function of shared-IOC count.** An indicator present in most cases contributes
  almost nothing, noise-flagged indicators contribute little, and sparsely connected
  clusters are discounted — single-linkage clustering means A–B plus B–C forms one
  cluster even when A and C share nothing. Confidence also no longer responds to the
  "Min shared IOCs" control, which is a view filter and should not move a measure of
  evidence. New fields on each cluster: `cohesion`, `min_edge_weight`,
  `distinctive_evidence`.

  Expect lower confidence figures than previous releases, and markedly lower ones on
  instances with few cases, where little is statistically distinctive.

- **TLP no longer affects decay weighting.** It expresses a sharing restriction, not
  fidelity or longevity, and correlation already excludes TLP:RED/AMBER indicators.

- Admiralty-scale reliability and credibility moved from decay weighting to confidence
  weighting: they describe whether an indicator is true, not how long it stays useful.

---

## [IRIS-NG-v1.0.1] — 2026-08-01

Chart-only release. The application code is identical to `IRIS-NG-v1.0.0`; the
version moves because the shipped artifact set does.

### Fixed

- **The Helm chart attached to `IRIS-NG-v1.0.0` deployed the wrong application
  version.** It was labelled `appVersion: IRIS-NG-v1.0.0` but pinned
  `v2.5.0-beta.1-iris-ng.7` for every image, so installing from the release asset
  gave you the previous release — without the Sponsor tab or IOC History — while
  claiming to be v1.0.0. The container images published under that tag were correct
  throughout; only the chart asset was wrong.

  The cause was an ordering trap rather than a slip: the images for a release do not
  exist until its tag has built, so hardcoded pins in `values.yaml` can only be
  corrected *after* tagging — which guarantees the chart packaged into every release
  pins the previous one.

### Changed

- **Chart image tags now default to the chart's `appVersion`** rather than being
  pinned in `values.yaml` (chart `0.4.0`). The packaged chart is therefore
  self-consistent with the release it ships with, by construction, and the ordering
  problem cannot recur. Pinning is still supported — set `irisapp.tag`,
  `irisworker.tag`, `irisaiworker.tag` or `postgres.tag` to override. `rabbitmq` is
  unaffected: it is an upstream image with its own version.

---

## [IRIS-NG-v1.0.0] — 2026-08-01

**Version scheme change.** Releases are now `IRIS-NG-v<major>.<minor>.<patch>`,
replacing `v2.5.0-beta.1+iris-ng.<build>`. Two things to be aware of: the new string
is not SemVer-parseable, and `1.0.0` sorts below every prior release. The upstream
API compatibility range this fork targets is unchanged and still reported on
**Settings → System** (Min/Max API supported).

> **Upgrading from a `v2.5.0-beta.1+iris-ng.N` release?** Nothing in the database or
> the API changed with the rename — it is a label change only. Follow the normal
> upgrade steps.

### Added

- **Sponsor tab** on Server Settings, listing the project's funding links. Read from
  the repository's `.github/FUNDING.yml` at runtime, parsing every platform key
  GitHub supports, so adding a funding platform later is a YAML edit with no code
  change. This is the only component in IRIS-NG that reaches the public internet on
  its own, and it is built to fail soft: loaded when the tab is first opened rather
  than on page load, 5-second timeout, cached for six hours, honours the proxies
  configured on the General tab, serves the last known values when GitHub is
  unreachable, and shows an empty panel rather than an error when there are none.
- **IOC History panel** on the IOC modal — a `History` item in the kebab menu and a
  clock icon beside the title, both shown only when history exists, opening a
  collapsible list of every recorded change with actor and timestamp. IOC create and
  update now write `modification_history`, which no previous release did; only IOCs
  touched from this release onward have entries, and nothing is backfilled.

### Fixed

- **Tag-driven workflows would have silently produced nothing under the new version
  scheme.** All four fired on `v*.*.*`, which `IRIS-NG-v1.0.0` does not match, so
  tagging would have built no images and created no release while every workflow
  reported success. They now accept both forms, keeping earlier `v*` releases
  re-dispatchable.
- **The publish sanitizer let real API keys through.** Its `Bearer` token floor was
  80 characters, set so a 64-character upstream demo key would fall through
  untouched, which also meant any genuine 40–79 character key in a published script
  passed straight through. The floor is now 40 and upstream boilerplate is protected
  by an explicit allowlist instead of a length coincidence. Separately, the
  leading-underscore "private" convention for `scripts/` only applied to `.py` files,
  so a fixture CSV published on every push while appearing excluded.
- **Chart publishing never worked.** `chart-releaser` detects changed charts by
  diffing against the previous commit, and this repository is republished as a fresh
  single-commit history, so it never found a changed chart and released nothing on
  every run since it was added. Chart packaging now happens in the release workflow
  and the packaged chart is attached to the release.
- **Helm chart brought forward to the current stack** (chart `0.3.0`): it defaults to
  the published images, deploys the `ai_worker` that AI summary and chat depend on,
  and requests a normal volume from the cluster default StorageClass instead of a
  node-local `hostPath` one that loses the database when a pod reschedules. The
  Postgres password environment variable was also misspelled in all three templates,
  masked by authentication being hardcoded to `trust`. Verified on a live single-node
  cluster.

### Changed

- Documentation no longer claims the stack "runs fully air-gapped once the images are
  pulled" — the Sponsor tab makes that untrue. The wiki names it as the single
  exception instead.

---

## [v2.5.0-beta.1+iris-ng.7] — 2026-08-01

First tagged release under the `+iris-ng.<build>` version scheme, and the first with
published container images. Builds `.5` and `.6` were version-string bumps that were
never tagged, so this entry covers everything since `+iris-next.4`.

### Added

- **Per-case notification bell** — a header bell showing what changed in the case
  currently in context, scoped strictly per case. Reads the existing `user_activity`
  audit log rather than a new notification store, so it works retroactively over
  history predating the feature. `case_notification_ack` (Alembic `f4a92c7e1b58`)
  holds a durable per-`(user, case)` read watermark that survives logout;
  acknowledging carries the newest timestamp actually shown, so activity arriving
  mid-read stays unread, and the watermark only moves forward. Own interactive edits
  are filtered out while `is_from_api` rows still notify. A never-acknowledged case
  falls back to a 14-day lookback rather than full history.
- **MISP cluster publishing (`IrisMISPCluster`)** — a *Push to MISP* button on each
  correlation cluster publishes it as one campaign event: narrative to an **Event
  Report**, linked notes to **analyst Notes** on the indicator they document,
  `ioc_description` to the attribute **comment**, IOC tags to attribute tags.
  **Entity names are redacted automatically** from all free text, with terms derived
  on every push from client records and case names; IOC values are never redacted.
  `misp_cluster_link` (Alembic `e7c1a94d2f38`) makes a repeat push return 409.
- **Analyst manual override of AI output** — the executive case summary and the AI
  cluster narrative can be corrected by hand. The original model output is always
  preserved, with *View AI original* and *Revert to AI*; regeneration returns HTTP
  409 (`reason: manual_edit_present`) unless explicitly discarded, so edits are never
  silently orphaned. Corrections flow into the STIX 2.1 export. Alembic
  `d3b8f5a1c674`.
- **Knowledge map layers on the case Graph tab** — note and evidence nodes plus
  direct `ioc_note_link` / `evidence_asset_link` / `ioc_asset_link` edges, with
  per-layer toggles. Upstream drew only assets and IOCs and connected them only when
  they shared a timeline event, so genuinely-linked objects appeared unconnected.
- **Master/working timeline deduplication** — on-demand exact and near-duplicate
  detection with a side-by-side merge editor.
- **Drive capacity planning and data retention policy** — rolling case-intake average
  drives a runway estimate and order recommendation; a retention threshold flags
  drives held past it. Alembic `c2e1f4d9b3a7`, `f2a8c6d1e4b9`.
- **Cloud and Kubernetes documentation** — a Helm chart ships in `deploy/kubernetes`,
  documented honestly as experimental: it predates the `ai_worker` split, ships
  placeholder values, and until this release had no published images to pull.

### Changed

- **Community Edition branding** — LGPL-3.0, no feature gates, no license key or
  activation, no telemetry, self-hosted. Corrected stale `develop` branch references
  across `README.md`, `CONTRIBUTING.md` and `FORK.md`; `develop` is retired with
  unrelated history and `main` is the active branch and PR target.
- Help menu links the iris-ng wiki instead of upstream `docs.dfir-iris.org`, and the
  Settings → System version links to the Releases page.
- Dashboard *Attributed open tasks* excludes tasks belonging to closed cases.
- Cluster narrative prompt v2 prohibits entity names in model output, making cached
  narratives safe to embed in STIX bundles shared with third parties.

### Fixed

- **Container image publishing was broken for every tagged release** — the three
  image workflows hardcoded `ghcr.io/dfir-iris/…`, the upstream org, so each run
  failed with `denied: permission_denied`. `GITHUB_TOKEN` can only write packages for
  its own owner; the namespace now follows the repository owner. This is why no
  images existed before this release.
- **Module configuration schemas were frozen at first registration** — adding a
  parameter to any module never reached an existing install, and an incomplete stored
  entry raised `KeyError` in `is_mod_configured()`, surfacing as a 500 on
  `/manage/modules/list` and an opaque DataTables Ajax error.
  `reconcile_module_configurations()` now runs every boot, adding declared-but-missing
  parameters and refreshing metadata while preserving admin-set values.
- **Reasoning models leaked their chain-of-thought into output** — `extract_content`
  now strips Gemma-4 channel markers and DeepSeek R1 / Qwen `<think>` blocks before
  returning to callers, so orchestrators need no per-feature handling.
- **IOC list N+1 query** — the IOC tab issued three queries per IOC; a single bulk
  aliased self-join replaces the loop (~2.6 s to ~30 ms on a 38-IOC case).
- **Evidence physical location rendered blank** — the list column now resolves from
  the linked drive rather than the deprecated per-row column.
- Settings save returned 400 when retention and capacity-planning fields were left
  blank; empty strings are now coerced to null before submit.
- Two STIX narrative lookup bugs (`art.content`, `order_by(generated_at)`) that made
  cluster exports silently skip AI enrichment.
- The *Generate report* button was dead after the Vite 8 migration — rolldown
  tree-shook handlers referenced only from inline `onclick` attributes.
- `sanitize_for_publish.py` wrote text files with platform line endings, shipping
  CRLF shell scripts that crash-looped the app and nginx containers on a fresh build.

### Security

- `setuptools >= 83` (MANIFEST.in sdist-exclusion advisory) with a build-time
  `pkg_resources` shim — `setuptools >= 81` removed `pkg_resources`, which
  `docxcompose` and `graphene-sqlalchemy` still import at module load. The shim
  rewrites both to `importlib` during the image build, changing no dependency
  versions.
- `brace-expansion` 1.1.16 (exponential-expansion DoS), `eslint` 9.39.5,
  `eslint-plugin-svelte` 3.22.0, `ajv` 6.15.0, transitive `postcss` 8.5.23.
- Replaced `showdown` with `marked` 18.0.5 (ReDoS with no upstream fix).
- CodeQL: open-redirect allowlist in `is_safe_url`, incomplete-sanitization fixes,
  explicit `permissions:` blocks on all workflows, and credential values removed from
  helper-script output.

### Known limitations

- The Helm chart in `deploy/kubernetes` is not deployable unmodified: it ships
  placeholder values, has no `ai_worker` deployment (AI summary and chat jobs would
  enqueue and never be consumed), and its `appVersion` still reads `2.4.5`.
- IOC updates do not write `modification_history`, so IOC edits cannot be surfaced
  the way timeline event history is.

---

## [v2.5.0-beta.1+iris-next.4] — 2026-07-04

### Fixed

- **`migrate_postgres_17.sh` restore: auto re-issue role passwords as scram-sha-256** —
  pg17 defaults to `scram-sha-256` auth for remote connections; a pg12 dump stores role
  passwords as MD5 hashes that are incompatible with scram-sha-256. The `restore` phase now
  reads `POSTGRES_USER/PASSWORD` and `POSTGRES_ADMIN_USER/PASSWORD` from `.env` and runs
  `ALTER USER ... PASSWORD '...'` for both the `postgres` and app (`raptor`) roles after the
  dump loads. Without this step the app container cannot connect to the database and the
  stack fails to start. Previously required a manual `ALTER USER` inside `docker exec psql`.

---

## [v2.5.0-beta.1+iris-next.3] — 2026-07-04

### Security

- **Replace showdown with marked@18.0.5** — Dependabot #99. showdown's link/anchor
  regex subparser has a catastrophic backtracking ReDoS with no upstream fix.
  `get_showdown_convert()` wraps `marked.parse()` with an identical `.makeHtml()` interface;
  all callers unchanged. img `on*` attribute sanitization and Bootstrap table
  post-processing inlined in the wrapper.

---

## [v2.5.0-beta.1+iris-next.2] — 2026-07-04

### Security

- **`vite-plugin-static-copy` 1.0.6→3.4.0** — dev-server path-traversal (Dependabot);
  3.3.0 is the minimum declaring Vite 8 peer support.
- **`picomatch` 2.3.1→2.3.2** — POSIX bracket-expression method injection via
  tailwindcss→chokidar→micromatch.
- **8 Python Dependabot patches** — urllib3, Flask, flask-cors, marshmallow, requests,
  Werkzeug, PyJWT, azure-identity.
- **Regex character-range corrected** — CodeQL `js/incomplete-sanitization`: overly-permissive
  range in `process_md_images_links_for_report`.

### Build

- **Vite 8 / rolldown 1.1.4 compatibility** — 36 import-free JS files moved from
  `ui/src/pages/` to `ui/public/` (rolldown silently drops globally-exported function
  declarations not called within their own module; verbatim copy in `public/` bypasses this).
  `popper.js` restored to `package.json` (vite-plugin-static-copy silently skips missing npm
  packages → Bootstrap tooltip 404 on every page). `jqvmap` removed (confirmed dead code
  since the fork).

### Fixed

- **N+1 IOC links query** — `case_list_ioc()` called `get_ioc_links(ioc_id)` in a
  per-IOC loop (3 DB round-trips × N). Replaced with a single SQLAlchemy aliased self-join
  (`get_ioc_links_bulk`). Measured ~25-38ms for 33-46 IOCs (was ~2.6s).
- **`User.user` field name in `enqueue_ai_job`** — `ai_jobs.py` read `u.user_login`
  (attribute does not exist on the `User` model); every AI summary + chat POST returned
  HTTP 500. Corrected to `u.user`.

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

[Unreleased]: https://github.com/zach115th/iris-ng/compare/v2.5.0-beta.1+iris-next.3...HEAD
[v2.5.0-beta.1+iris-next.3]: https://github.com/zach115th/iris-ng/releases/tag/v2.5.0-beta.1%2Biris-next.3
[v2.5.0-beta.1+iris-next.2]: https://github.com/zach115th/iris-ng/releases/tag/v2.5.0-beta.1%2Biris-next.2
[v2.5.0-beta.1+iris-next.1]: https://github.com/zach115th/iris-ng/releases/tag/v2.5.0-beta.1%2Biris-next.1
[v2.5.0-beta.1+iris-next.0]: https://github.com/zach115th/iris-ng/releases/tag/v2.5.0-beta.1%2Biris-next.0
[baseline-v2.5.0-beta.1]: https://github.com/dfir-iris/iris-web/releases/tag/v2.5.0-beta.1

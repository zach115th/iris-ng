# Changelog

All notable changes to `iris-next` (a fork of DFIR-IRIS) are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely, and
versions follow [SemVer 2.0](https://semver.org/) with `+iris-next.<build>` build
metadata appended to the upstream version we forked from.

Inherited upstream changelog (versions ≤ v2.5.0-beta.1) lives in upstream's release
notes: <https://github.com/dfir-iris/iris-web/releases>.

---

## [IRIS-NG-v2.0.0] — in development, not yet released

The v3-feature-integration program (this tree, branch `dev`): mail rules +
AI triage, alert clusters + clustering rules, investigation flows, the
customer-asset registry, notifications + home + following, war rooms +
AI SitReps, the correlation-workspace migration, and the v3 UI-parity
campaign. The full entry is written at the release pass; no image carries
this version yet.

---

## [IRIS-NG-v1.4.1] — 2026-08-25

Makes multi-factor authentication usable in practice: the enrolment control was
findable only by scrolling past the whole skills catalogue, it was labelled
*Reset* for people who had never enrolled, and the accounts that cannot use MFA
at all were still being offered it.

No schema migration. Confined to `source/app/`, so an upgrade needs a restart
rather than a rebuild.

### Added

- **The built-in administrator (user #1) and service accounts are exempt from
  MFA enforcement.** Service accounts were already exempt in behaviour rather
  than by policy — `_authenticate_password` refuses them before the password is
  even checked, so they never reach the MFA step and authenticate by API key,
  which has none. Naming them makes the interface honest about what was already
  true.

  The administrator exemption is a deliberate break-glass decision, and it is a
  security trade-off worth stating plainly: **whoever holds that password
  bypasses MFA entirely on the most privileged account in the system.** Give it
  a strong unique value, and consider keeping a second administrator account —
  which *is* subject to enforcement — for day-to-day work.

  The exemption is keyed to user #1 specifically, **not** to the
  `server_administrator` permission, so every administrator created later must
  enrol like anyone else.

  One helper, `is_mfa_exempt()`, is the only place the rule lives. Login
  enforcement, the profile page and the admin user modal all call it, so the
  greyed-out control and the actual behaviour cannot drift apart.
  `/auth/mfa-setup` refuses exempt accounts as well — otherwise one could enrol
  a secret that nothing ever checks, which looks like protection and is not.

### Fixed

- **The MFA and password controls were effectively hidden.** The self-service
  skills catalogue had been inserted between the account fields and the account
  action buttons, pushing *Change password* and the MFA control below roughly
  34 checkboxes and a screen out of view — they read as missing rather than as
  further down. The actions now sit with the account fields.

- **The enrolment button said "Reset MFA" to people who had never enrolled.**
  It now reads *Set up MFA* until enrolment is complete. The profile page shows
  a button rather than the QR code itself; the QR is on the page it links to.

- **Exempt accounts are shown a disabled control with the reason in its
  tooltip, rather than no control at all.** An absent control is ambiguous — it
  reads as broken. A disabled one is information.

---

## [IRIS-NG-v1.4.0] — 2026-08-25

Adds a lifecycle record to two more object types, fixes a field that had been
quietly discarding who created an IOC, and requires a reviewer before a case can
be closed. Carries everything staged under `IRIS-NG-v1.3.1`, which was never
tagged.

### Added

- **Asset history** ([#82](https://github.com/zach115th/iris-ng/issues/82)).
  Assets already carried a `modification_history` column and nothing had ever
  written to it, so the database could not tell you whether an asset had been
  edited. Creation, edits, comments, promotion from the working timeline and
  case import are now all recorded, and the asset modal gained the same
  collapsible **History** panel that timeline events and IOCs already had.

  The creation entry is written in the one function every creation path already
  funnels through, so it covers the single- and multi-asset modals, the API and
  alert escalation and merge alike.

  **Nothing is backfilled** — assets created before this show an empty panel,
  which is stated explicitly rather than left as a blank that could equally mean
  the panel is broken.

- **"Added by" on assets, IOCs and timeline events.** The creator is shown
  beneath the object's UUID, so the most common question about an object can be
  answered without opening its history. Hovering the name shows the login.

- **A reviewer is required before a case can be closed**
  ([#84](https://github.com/zach115th/iris-ng/issues/84)). Both routes that
  close a case are blocked — the *Close case* button and setting *State →
  Closed* then saving — because guarding only the button would have left the
  dropdown as a one-click bypass. Assigning a reviewer and closing in the same
  save works, and editing an already-closed case that has no reviewer is still
  allowed, so cases closed before this are not frozen.

  **Enforced in the interface only, deliberately.** `POST
  /manage/cases/close/<id>` and `PUT /api/v2/cases/<id>` with a Closed state
  still close a case with no reviewer, so existing automation keeps working.
  Treat the rule as a guard against analyst error rather than an invariant of
  the data: a case closed by a script or an n8n workflow may have no reviewer,
  so **do not read "closed" as "reviewed"**.

### Fixed

- **An IOC's creator was overwritten every time the IOC was edited.**
  `Ioc.user_id` was reassigned to whoever saved the IOC last, so on any IOC a
  second analyst had touched, the record of who added it was permanently gone.
  That contradicted the column's own use — the IOC list has always sorted it as
  *opened by*, and assets and timeline events both treat the equivalent column
  as the creator. Editing no longer touches it.

  **This is visible to API clients.** A client reading that field as *last
  modified by* will see it stop changing on edit; use the `created` and
  `ioc updated` entries in `modification_history` for that instead. Rows written
  before this release still hold whoever last edited them, so the value is not
  retroactively correct.

  Because the fix only helps going forward, the new *Added by* line does not
  read that column at all. It resolves an actual creation record — the `created`
  history entry, else the activity-log row written when the IOC was added, which
  is also the only creation *time* an IOC has, since `Ioc` has no date-added
  column. Where neither exists it reports **unknown** and names the last saver
  separately, rather than presenting them as the creator.

- **Editing a time-tracking entry created a duplicate instead of updating it**
  ([#41](https://github.com/zach115th/iris-ng/issues/41)) — first staged under
  the never-tagged `IRIS-NG-v1.3.1`; full detail below. **Duplicates already
  recorded are not corrected automatically.**

---

## [IRIS-NG-v1.3.1] — 2026-08-24 (never released)

> This version was staged on `main` but no tag, release or container images were ever
> produced for it, so nothing shipped under this number. The changes below are included
> in `IRIS-NG-v1.4.0`.

A single-defect patch release over `IRIS-NG-v1.3.0`.

### Fixed

- **Editing a time-tracking entry created a duplicate instead of updating it**
  ([#41](https://github.com/zach115th/iris-ng/issues/41)). Correcting the note on a
  logged entry left the original updated *and* added a second identical row, so the
  case total grew every time an entry was edited.

  The Log button carries the double duty of creating a new entry and saving an edited
  one, and the swap between the two was done with jQuery's `.off('click')`. The button
  also had an inline `onclick` in the template, and **jQuery cannot remove an inline
  handler** — it is a DOM attribute, not a jQuery binding. So *Save* fired both: the
  surviving inline handler POSTed a new entry while the rebound handler PUT the edit.

  The consequence went further than editing. Once the button had been swapped and
  reset — which also happens simply by closing the modal — it carried the inline
  handler *and* a bound one, both of which create. From that point every ordinary
  **Log** click added two entries until the page was reloaded.

  The inline handler is gone and the button is bound once in JavaScript. Both files
  carry a note explaining why that button must never regain an `onclick`.

  **No data is corrected automatically.** Duplicates already recorded remain, because
  a duplicate is indistinguishable from two genuine entries logged with the same
  duration, date and note. Review the Time tab on affected cases and delete the extra
  rows; the case total on the modal is the quickest way to spot one.

---

## [IRIS-NG-v1.3.0] — 2026-08-24

Introduces a per-event triage verdict on the master timeline, makes *Add to
summary* actually govern what the AI surfaces and the generated report take
into account, and carries everything staged under `IRIS-NG-v1.2.3`, which was
never tagged.

### Added

- **Event triage verdict** (Alembic `b8f4e2a71c93`). A single *Verdict*
  dropdown on the event modal replaces the *Add to summary* and *Display in
  graph* checkboxes and the seven-swatch colour picker: **To be determined**
  (default, purple), **True positive** (green), and **False positive** (red,
  excluded from both the AI surfaces and the case graph).

  The verdict needed its own column rather than being derived from the two
  flags, because *to be determined* and *true positive* carry the same boolean
  state and so are indistinguishable from them. `apply_verdict()` is the only
  place the verdict → (colour, summary, graph) mapping lives, and every write
  path goes through it.

  Existing events are migrated on first boot: an event with **both** flags off
  becomes a *false positive*, since that was the only way to express the same
  intent before; everything else, including rows predating the flags, becomes
  *to be determined*. Mixed states are normalised, which is a real change to
  stored data. `event_verdict` is optional for API clients — an absent or
  unrecognised value falls back to the default rather than failing the request,
  so workflows written before the field existed keep working.

  The timeline toolbar's *Toggle Summary*, *Toggle Graph* and colour swatches
  are now three verdict actions.

- **Who added an event, shown without opening the history panel.** The event
  modal carries an *Added by \<name\> on \<date\> UTC* line beneath the event
  UUID, and each timeline card shows the creator at the end of its footer row.
  This is the creator, not the last editor: the edit path never reassigns
  `user_id`/`event_added`, so it stays accurate however often an event is
  changed.

### Changed

- **"Add to summary" now decides what the AI and the report consider.** It was
  previously a marker that nothing acted on. It gates the executive case
  summary, the running timeline-analysis panel, the case chat, the surrounding
  context of the per-event analysis drawer, and the generated `.docx` report.

  Deliberately **not** gated: the per-event drawer's *target* event, since you
  opened the drawer on that card; and `/case/export` plus the encrypted
  `.iris-case` export, which must stay complete records.

  Made opt-out rather than opt-in. Promotion from the working timeline, CSV
  import and manual creation all previously stored the flag as false, so an
  opt-in reading would have silently emptied the analysis for any case built
  from a Hayabusa or KAPE import — and an empty payload reads as a quiet case
  rather than a missing one. All three now default it on.

  Both prompts receive a server-computed count of how many events were held
  back, and are explicit that a curated timeline must not be reported as an
  inactive one.

- **Dependency updates.** SQLAlchemy 2.0.51 → 2.0.52, azure-keyvault-secrets
  4.11.0 → 4.11.1, svelte 5.56.8 → 5.56.10, eslint-plugin-svelte 3.22.0 →
  3.23.0, globals 17.9.0 → 17.11.0, and `@types/node` 26.1.2 → 26.2.0.

### Fixed

- **The notification panel's header was invisible on the Timeline page**,
  taking the *Mark as read* button with it. The topbar is `position: fixed`
  with `z-index: 1001`, which makes it a stacking context — so every dropdown
  inside it paints at 1001 regardless of its own `z-index`. The Timeline
  page's filter bar carried `z-index: 1030` and therefore painted over the top
  of any open topbar dropdown. The bar only ever needed to clear the AI and
  working-timeline panels (910 and 920), so it now sits at 1000, below the
  topbar. Affected every topbar dropdown on that page, not only the bell.

- **A colour chosen for an event never appeared on its timeline card.** Two
  independent causes, so fixing either alone would not have shown anything.
  The renderer emitted the colour as a normal inline `style` attribute, while
  `dark-theme.css` sets the card border with `!important` — and importance
  is resolved before specificity, so the stylesheet won regardless of the
  inline declaration. The border was also drawn as `groove`, which renders as
  a darkened shade of the colour and is invisible against the card background.

- **Every task in the DIM Tasks list showed the red failure icon**, including
  tasks that had plainly succeeded. The list endpoint overwrote celery's own
  task status with `"success" if success else str(row.result)`, where `success`
  was hardcoded to `None` — so the truthy branch could never fire and each row
  rendered its raw result blob as its state. The frontend compares that against
  the literal string `'success'`, which it never equals. The list now uses
  celery's `status` column, and distinguishes pending or revoked tasks from
  failed ones instead of lumping them together.

  The icon reflects the **task**, not the module inside it: a task can complete
  while the module it ran reports a failure. Open the task to see that verdict —
  it is the modal's separate *Success* row.

  Corrects a claim made during the security review, which held that celery
  results are not pickles because `result_serializer` is `json`. That setting
  does not apply to the **database** result backend, which stores the column as
  a pickle. The `pickle.loads` call removed from this endpoint was therefore a
  live deserialisation sink rather than the inert one it was assessed as — the
  removal stands and matters more than recorded. It is not being reintroduced to
  read the module verdict; the modal already does that safely.

---

## [IRIS-NG-v1.2.3] — 2026-08-20 (never released)

> This version was staged on `main` but no tag, release or container images were ever
> produced for it, so nothing shipped under this number. The changes below are included
> in `IRIS-NG-v1.3.0`.

Four fixes that had accumulated on `main` since `IRIS-NG-v1.2.2`, two of
them reported from a production instance.

### Fixed

- **MISP sync failed on any IOC whose MISP attribute was already claimed**
  (Alembic `d1a7c93f5e64`). `misp_attribute_link` marked both
  `misp_attribute_id` and `misp_attribute_uuid` UNIQUE, which asserts that a
  MISP attribute belongs to exactly one IRIS IOC. MISP does not work that way:
  it deduplicates attributes within an event by (type, value, category), so it
  returns the *same* attribute for two IOCs sharing a value and type in one
  case, and for an IOC deleted and recreated in IRIS — that mints a new
  `ioc_id` **and** a new `ioc_uuid` while MISP still holds the original
  attribute. The insert then died on a `UniqueViolation`.

  `ioc_id` remains UNIQUE — one IRIS IOC still has at most one MISP attribute.
  Only the reverse direction is relaxed, so the table now models
  many-IOCs-to-one-attribute, which is what MISP expresses. Both columns keep a
  plain index.

  The attribute lookup also gained a second pass. It searched only for the
  provenance marker `dfir_ioc_uuid=<ioc_uuid>`, which a recreated IOC can never
  match; it now falls back to MISP's own identity (type + value within the
  event), so such an IOC takes the *update* path instead of trying to create a
  duplicate link.

- **One failing IOC took down the entire hook task.** The module caught sync
  errors and logged them but never rolled back, leaving the shared SQLAlchemy
  session in a failed-flush state. IRIS core commits that same session
  immediately after the hook returns, so it raised `PendingRollbackError` and
  the whole task was reported as failed — with a traceback naming
  `task_hook_wrapper` rather than the module, sending readers to the wrong
  place. Failures are now rolled back per item, so one unsyncable IOC no longer
  affects the others.

  This is a third distinct hook-failure shape, alongside the `NotImplementedError`
  of app/worker code skew and the `PGRES_TUPLES_OK` of celery fork-safety.

- **The case chat assistant could not see evidence.** The Evidence tab shipped
  with its own specialised prompt — telling the model to reason about hashes,
  asset linkage and collection gaps — over a payload that contained no evidence
  at all. Asked "which evidence records are missing a hash?", it correctly
  answered that it had no inventory to look at. Evidence was the only one of the
  six chat variants missing its data.

  `physical_location` is resolved from the linked drive rather than the column of
  the same name on the evidence row: that column is deprecated and is NULL for
  anything registered since the Inventory tab shipped, so reading it directly
  would report "no location" for evidence that plainly has one.

- **The correlation drawer showed nothing where linked notes go when an
  indicator had none.** No heading, no message — just a gap, which is
  indistinguishable from a broken lookup, and was reported as one. The section
  now always renders, with an explicit line when no note in that case references
  the indicator and none is linked as its source. That absence is a signal in
  its own right: an indicator nobody has written about is one nobody has
  explained.

  Note matching itself was working correctly, including defanged forms — a note
  containing `203.0.113[.]47` does match the indicator `203.0.113.47`.

### Added

- **Evidence preservation in the executive case summary.** A fifth domain
  specialist joins notes, timeline, IOCs and assets, and the briefing gains an
  **Evidence Preservation** section: how much was preserved, in what categories,
  and how defensible it is. This answers a leadership question — whether the
  organisation can stand behind its evidence for legal hold, insurance or a
  regulator — rather than an investigative one.

  Two constraints make it trustworthy. **The counts are computed server-side**
  and passed to the synthesizer directly, not relayed by a model; where the
  specialist's prose and those counts disagree, the counts win. And **no artifact
  is ever named** — filenames, hashes, barcodes and storage locations stay out of
  an executive briefing, so the specialist emits categories and counts instead of
  values the synthesizer would only have to strip.

  Evidence is deliberately excluded from the sparse-case test that decides
  whether a case is briefable at all: collecting artifacts is not the same as
  having analysed them.

  Synthesis prompt `CaseSummarizationSystemPrompt-v4` → `-v5`. Existing cached
  summaries invalidate on their own, since the input hash covers the prompt and
  the sub-summaries.

---

## [IRIS-NG-v1.2.2] — 2026-08-13

Carries everything staged under `IRIS-NG-v1.2.1`, which was never tagged — see
below.

### Changed

- **Dependency updates.** Applied from Dependabot rather than merged, since
  `main` is republished as a fresh snapshot and a merged pull request is
  discarded by the next publish.

  - `marked` 18.0.7 → 18.0.9, `vite` 8.2.0 → 8.2.1,
    `@sveltejs/vite-plugin-svelte` 7.2.0 → 7.3.0, plus a lockfile-only
    `postcss` 8.5.23 → 8.5.26.

    Only `marked` reaches the browser — it is copied verbatim into the bundle
    rather than compiled through it — so the usual "every built file is
    byte-identical" check cannot apply here. The control instead is that
    *exactly one* file differs, and it did: 688 built files, `marked.min.js`
    alone. Rendering is byte-identical across nine representative note bodies,
    including tables and defanged indicators.

  - `packaging` 26.2 → 26.3 and `alembic` 1.18.5 → 1.19.1. Alembic runs a
    migration upgrade on every container start, so this was verified by boot:
    the stored revision and the 96-table schema are unchanged.

  - `setuptools` floor `>=83.0.0` → `>=84.0.0`. Declarative only — the pin is
    an open floor, so 84.0.0 was already being installed.

- **Corrected a misleading comment** above the `pkg_resources` build-time patch:
  it disappeared in `setuptools>=81`, not `>=83`. As written it invited lowering
  the pin to 82, which would still land without `pkg_resources` and fail at app
  boot rather than at build time.

---

## [IRIS-NG-v1.2.1] — 2026-08-11

> Staged on `main` but never tagged, so no release or container images were
> produced under this number. Everything below ships in `IRIS-NG-v1.2.2`.

### Changed

- **Cross-case correlation now shows indicators at every TLP.** It previously
  restricted to TLP:GREEN and TLP:CLEAR. That was over-cautious in one direction
  and did nothing in the other.

  Over-cautious, because every correlation query is already scoped to the
  caller's granted cases (`_accessible_case_ids`) — an analyst was being denied a
  link between two cases they could both open anyway. And because the IOC modal
  defaults new indicators to **AMBER**, the default path produced indicators that
  silently never correlated. On the demo dataset shipped with the project, a
  SHA-256 shared between two cases was invisible for exactly this reason.

  What TLP actually governs is **redistribution**, so the restriction moved to
  the two paths where indicators leave the instance:

  - `GET /api/v2/correlation/clusters/<id>/stix`
  - `POST /api/v2/correlation/clusters/<id>/misp-push`

  Both now filter explicitly rather than inheriting the restriction from the
  query that feeds them, and both report what they held back — a partial export
  is no longer indistinguishable from a complete one. The MISP push returns
  `tlp_withheld_count`; the STIX download carries `X-IRIS-TLP-Withheld`, since a
  file response has no body to put a warning in.

  **The rule on both paths is most-restrictive-wins.** An indicator marked
  TLP:RED in any one of its cases is not published, even where another case
  labels the same value green — a value restricted in the case where it was
  discovered stays restricted, and a second analyst's label does not override
  that. An indicator with **no TLP set** is also not published: `ioc_tlp_id` has
  no column default, so any API client or n8n workflow that omits the field
  writes NULL, and an unlabelled indicator has not been cleared by anyone.

### Added

- **TLP badge on the Correlation tab.** New column in the Shared IOCs table and
  a badge on each per-case card in the click-through drawer. The table shows the
  most restrictive TLP across the indicator's appearances; the drawer shows each
  case's own, because the same indicator is routinely labelled differently in
  each. A padlock marks indicators that will not be included in an export or
  push, so the handling rule is visible where the analyst is acting rather than
  only on the IOC itself.

---

## [IRIS-NG-v1.2.0] — 2026-08-10

The first release to carry the security review. `IRIS-NG-v1.1.1` tagged a commit
that predates it, so no previously published image contains any of the fixes
below — upgrading is strongly recommended over rebuilding from an older tag.

### Security

- **First security review of the tree — all ten findings fixed.** Full write-up in
  `docs/23-security-review.md`. The two that mattered:

  - **Stored XSS in the correlation drawer.** Analyst note markdown was rendered
    into the DOM raw. `mistletoe` follows CommonMark, which passes HTML through
    verbatim, so note content became script. Rendering now goes through
    `app/iris_engine/safe_markdown.py`. `mistletoe` itself cannot be upgraded —
    the vendored `docx_generator 0.8.0` pins it at `==0.7.2` for the reporter.

  - **A publicly known default `IRIS_SECRET_KEY`.** Shipped in the sample config
    and therefore identical across every deployment that never changed it, which
    makes session cookies forgeable. A placeholder key is now replaced at boot by
    a generated one persisted in the new `runtime_secret` table (Alembic
    `c9f1e4b28a37`); an explicitly configured key always wins.

  Also fixed: `/context/set` was missing its authorization decorator, an
  unauthenticated 500 on `/auth/mfa-setup`, an unescaped login banner, PBKDF2
  iterations raised 260k → 600k with envelope versioning so existing hashes stay
  valid, two inert `pickle` sinks, default credentials in the EKS manifests, and
  upstream's hardcoded analytics origin replaced with an opt-in placeholder.

- **`Access-Control-Allow-Origin: *` with `Access-Control-Allow-Credentials: true`
  on every response.** Inherited from upstream. Browsers reject that pair, so it
  never granted credentialed cross-origin reads, but the wildcard alone let any
  site read unauthenticated responses and use a visiting analyst's browser to
  confirm an internal-only host was reachable. CORS is now opt-in via
  `IRIS_CORS_ALLOWED_ORIGINS` and off by default; when set, the matching origin is
  echoed verbatim rather than `*`. The websocket previously accepted any origin
  and is now same-origin unless the same allowlist says otherwise.

- **Security headers were absent from error responses.** nginx applies
  `add_header` only to 2xx/3xx unless marked `always`, and only HSTS was. Every
  error page — the Flask 404 in particular — therefore shipped with no CSP, no
  `X-Frame-Options` and no `nosniff`, leaving it frameable. All four security
  headers are now `always`.

- **The login form's CSRF token was never validated.** The guard read
  `not form.is_submitted() and not form.validate()`; on a POST `is_submitted()` is
  true, so the `and` short-circuited and `validate()` never ran. A POST carrying a
  valid token and one carrying none produced byte-identical responses. Now
  `not form.validate_on_submit()`. Also inherited from upstream. Impact was login
  CSRF — forcing a victim into an attacker's session — not authentication bypass,
  and `SameSite=Lax` on the session cookie already blunted it.

- **`npm audit` 2 high → 0.** `eslint` 9.39.5 → 10.8.1 with `@eslint/js` 10.0.1
  (version-locked, so neither moves alone), `globals` 15.9.0 → 17.9.0, plus a
  lockfile-only `nanoid` 3.3.18 (GHSA-2v37-7h3g-55p8) and the removal of
  `js-yaml` (GHSA-5p4m-2wfm-xmqj). All development tooling: 688/688 built files
  byte-identical, lint output unchanged line for line.

### Added

- **Bring your own TLS certificate** (#71). `CERT_DIR` in `.env` points at any host
  directory holding the certificate and key; the default stays the self-signed pair
  from `scripts/generate_dev_certs.sh`, so existing deployments are unaffected. No
  image rebuild is needed to switch.

  nginx now validates the certificate and key before starting and names both the
  resolved path and the variable that produced it. That covers the two failure modes
  that are otherwise near-undiagnosable: a Let's Encrypt `live/<domain>` mount whose
  symlinks dangle because `archive/` was left outside it, and a private key the
  container's `www-data` cannot read. See the wiki's TLS Certificates page.

---

## [IRIS-NG-v1.1.1] — 2026-08-05

### Security

- **Two high-severity advisories cleared in the UI dependency tree**, both
  transitive and both resolved by a lockfile update — `ui/package.json` is
  unchanged and the built bundle is byte-identical.

  - `brace-expansion` 1.1.16 → **1.1.18** — GHSA-mh99-v99m-4gvg (denial of
    service via unbounded expansion) and GHSA-rgw5-rvv9-x895, which bypasses the
    mitigation for the first. Reached through `eslint` → `minimatch`, so exposure
    was limited to development tooling. Previously recorded as requiring an
    `eslint` major upgrade; upstream has since backported the fix to the 1.x
    line, and `minimatch` accepts it without change.

  - `socket.io-parser` 4.2.6 → **4.2.7** — GHSA-2m8v-j782-fhvr (memory
    exhaustion). Not reachable in practice: this project's websocket server is
    Flask-SocketIO, and the Node `socket.io` package is present only as the
    source of the browser client file copied into static assets. That file ships
    prebuilt upstream, so it is unchanged by this update.

---

## [IRIS-NG-v1.1.0] — 2026-08-05

> Staged on `main` but never tagged, so no release or container images were
> produced under this number. Everything below ships in `IRIS-NG-v1.1.1`.

Dependency modernisation across Python, npm, Docker base images and GitHub
Actions, plus fixes to two version-comparison and diagnosability defects the
upgrades exposed.

### Fixed

- **The update check crashed on the current version scheme.** `updater.py` parsed
  `IRIS_VERSION` with `packaging.version.parse()`, and `IRIS-NG-v1.1.0` is not valid
  PEP 440. `packaging` 21.3 tolerated this by returning a `LegacyVersion`; version
  22.0 removed that class, so the comparison raises `InvalidVersion` instead. A new
  `parse_iris_version()` strips the product prefix before parsing, making the
  comparison genuine PEP 440 ordering rather than legacy string handling. It also
  now tolerates an empty or absent release name, which previously raised.

- **AI suggesters timed out against slower backends.** The per-feature timeouts were
  sized for a local model returning in seconds. A backend that shells out to a CLI
  takes an order of magnitude longer — a measured 28–34s against a 60s ceiling — so
  requests failed on latency alone. Raised to 180s for the tag, ATT&CK, evidence-type
  and case-template suggesters, and the IOC extractor. This is a ceiling rather than a
  wait, so fast backends are unaffected.

- **AI failures all reported the same unhelpful parse error.** Five orchestrators
  logged what the backend actually said and then discarded it, raising only the JSON
  decode exception. A model declining a request, an unrecognised model name and an
  empty response were indistinguishable in the interface — every one displayed
  `Expecting value: line 1 column 1`. The backend's message is now included in the
  error surfaced to the analyst.

- **The sidebar printed the product name twice.** `IRIS {{ iris_version }}` read
  correctly under the previous scheme but became `IRIS IRIS-NG-v1.0.3` once the name
  moved into the version string.

### Changed

- **Python dependencies** — 22 packages updated, including SQLAlchemy 2.0.51,
  alembic 1.18.5, celery 5.6.3, Flask-WTF 1.3.0, Werkzeug 3.1.8, graphene 3.4.3,
  psycopg2-binary 2.9.12 and requests 2.34.2. Also `cryptography>=50`,
  `qrcode[pil]==8.2`, `pyintelowl>=5.1.0` and `packaging==26.2`.

  `flask-marshmallow` is held at **1.4.0**: 1.5.0 requires `marshmallow>=4.0.0`,
  while this release pins marshmallow 3.26.2. Moving to marshmallow 4 is a schema-wide
  migration, not a dependency bump.

- **UI dependencies** — 11 packages including `ace-builds` 1.44.0 (six years and 137
  releases on from 1.4.9), Vite 8.2.0, Svelte 5.56.8, `socket.io` 4.8.3, `marked`
  18.0.7 and `sortablejs` 1.15.7.

- **Base images and CI** — nginx 1.31, `actions/checkout` v7, `actions/setup-node` v7,
  `softprops/action-gh-release` v3, and the devcontainer aligned to
  `python:3.12-trixie` to match the runtime it had drifted three minor versions behind.

- **End-to-end harness** — `wait-on` 9.1.0, `dotenv` 17.4.2, `@playwright/test` 1.62.1
  and `@types/node` 24.13.3 (matching the Node in use rather than the newest published).
  The `start` script waited on a port the application does not publish, with no
  timeout, so a failed startup hung indefinitely rather than reporting.

### Not taken

- **PostgreSQL 18** — a major Postgres version is a data migration, not a dependency
  bump: an 18 server will not start on a 17 data directory, so every existing
  installation would fail to come up. PostgreSQL 17 is supported until 2029.
- **jQuery 4** — removes APIs used in 86 places here, and Bootstrap 4 declares a peer
  range of `jquery 1.9.1 - 3`. Migrating requires moving to Bootstrap 5 first.
- **Node 25** — an odd-numbered release that never receives an LTS phase and reached
  end of life on 2026-06-01. Node 24 is supported until 2028.

---

## [IRIS-NG-v1.0.3] — 2026-08-04 (never released)

> This version was staged on `main` but no tag, release or container images were ever
> produced for it, so nothing shipped under this number. The changes below are included
> in `IRIS-NG-v1.1.0`.

### Fixed

- **A cluster's shared-IOC count contradicted the threshold that created it.** The
  count included only IOCs found *exclusively* within the cluster, so an indicator
  shared by two of its cases but also present elsewhere was discarded. At a threshold
  of 3, two cases linked *because they share three distinct IOCs* reported "1 shared
  IOC(s)". An IOC now counts for a cluster when at least two of that cluster's cases
  carry it, applied to both the displayed set and the scored set — their divergence is
  what produced the contradiction. Cluster confidence is corrected as a result, having
  been computed over the undercounted set.

### Changed

- **The Shared IOCs table now follows the clustering threshold**, listing the IOCs
  behind the surviving clusters rather than every IOC in two or more cases. It uses the
  same rule as the cluster cards, so the two cannot disagree. The "Shared IOCs" and
  "Correlated cases" summary cards count the same set, and an empty table now reports
  how many IOCs exist below the threshold instead of reading as "no data".

- **Labels state which surface the threshold governs.** "Min shared IOCs" counts
  distinct indicators a case *pair* must have in common; it is not a minimum number of
  cases an indicator must appear in. The control, the cluster panel and the IOC table
  now say so, since the distinction determines which IOCs appear.

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

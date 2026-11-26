# Changelog

All notable changes to `iris-next` (a fork of DFIR-IRIS) are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely, and
versions follow [SemVer 2.0](https://semver.org/) with `+iris-next.<build>` build
metadata appended to the upstream version we forked from.

Inherited upstream changelog (versions ≤ v2.5.0-beta.1) lives in upstream's release
notes: <https://github.com/dfir-iris/iris-web/releases>.

---

## [IRIS-NG-v2.24.1] — 2026-11-26

A code scanning fix in the tables' compatibility layer; no table looks or behaves differently. **No migration** -
the database head stays at `b3f7d1a9c5e2`. Only the app image changes (one browser script); the nginx and database
images, and the guest-portal tunnel agent, do not change.

### Security
- **The tables' column-width measure no longer looks like an HTML filter** (code scanning alert #56, "Incomplete
  multi-character sanitization"). `js/iris/datatables_compat.js` picks the longest cell of each column the way
  DataTables 1.10.16 did, by the length of its display text with tags removed, and built that text with a pattern
  that removes each `<...>` once - not enough to make HTML safe. The text was only measured: the cell that is sized
  is the one DataTables drew, and the text never reached the page, so nothing could be injected. The length is now
  counted directly, the same for every value, and the column widths do not change.

### Upgrading
- `scripts/update.sh --ref IRIS-NG-v2.24.1`, the 2.24.1 images, or chart 1.24.1. No migration. An install on 2.23.x
  or earlier also takes 2.24.0's changes (its entry below), the guest-portal tunnel agent's cloudflared 2026.11.2
  included.

---

## [IRIS-NG-v2.24.0] — 2026-11-26

Every table moves from DataTables 1.10.16 (2017) to DataTables 3.1.6, with its Buttons, Responsive, Select and RowGroup
extensions, and looks and behaves as it did; the Tasks page's status editor no longer needs the CellEdit plug-in. **No
migration.** The app image changes (the page layouts, the templates of the pages with tables, their scripts and
stylesheets); the guest-portal tunnel agent gets a newer cloudflared; the database and nginx images do not change.

### Changed
- **DataTables 1.10.16 → 3.1.6** with its Bootstrap 4 integration, **Buttons 1.6.1 → 4.1.4**, **Responsive 2.2.9 →
  4.1.1**, **Select 1.3.4 → 4.1.1** and **RowGroup 1.1.4 → 2.1.1**, installed from npm (they were copied in by hand). A
  compatibility layer, `js/iris/datatables_compat.js`, keeps every table as it was: the layout, the texts ("Show …
  entries", "Showing 1 to 10 of 57 entries", Previous / Next), the paging, the striped rows, the ordering (a header
  click toggles ascending and descending; DataTables 3 adds a third, unordered, step), the column widths, Responsive's
  details row, RowGroup's group rows, and the copy and CSV output (no footer row, no trailing line break, one header
  row where a table has a filter row). Select's, Responsive's and RowGroup's stylesheets of 1.10.16's time are served
  as `css/datatables_compat.select.css`, `.responsive.css` and `.rowgroup.css`; Buttons uses its Bootstrap 4
  stylesheet, as before.
- **CellEdit 1.0.19 → `js/iris/dt_cell_edit.js`** for the Tasks page's status column, the only place it was used: the
  same list with Confirm and Cancel, built without inline handlers, the statuses written as text.
- **The CSV exports of Activities, DIM Tasks and Search** put a `'` before a value that is not a number and starts with
  `=`, `+`, `-`, `@`, a tab or a carriage return, so a spreadsheet does not run it as a formula (Buttons 4's default).
  The case pages' exports set their own options and are unchanged.
- **Rows with equal values** keep the order they were loaded in when a table is sorted again; 1.10.16 kept the
  previous sort's order between them.
- On the Manage Cases page's legacy table (**Show legacy table**), when a narrow window hides a column, the other
  columns fill the table instead of leaving the hidden column's space empty.
- DataTables' own warning when a list cannot be loaded may read "Invalid JSON response" where it read "Ajax error".
- **cloudflared 2026.11.1 → 2026.11.2** in the guest-portal tunnel agent. cloudflared now reads the protocol version
  at the start of each QUIC tunnel stream in full: when a stream's first bytes arrived apart, the request or response
  it carried could fail to decode. A quick tunnel uses QUIC wherever UDP reaches Cloudflare's edge. cloudflared also
  updates its `golang.org/x/net` and `golang.org/x/crypto` libraries; the findings that update closes are in
  packages the cloudflared binary does not contain. The agent starts, and restarts cloudflared after a crash, as
  before.

### Fixed
- **The users list on the Access tab of a case's information dialog never sorted:** 1.10.16 put its sorting on the
  list's per-column filter row, whose inputs take the click. A click on a column header now sorts it.

### Removed
- No longer served (under `/static/assets/`): `js/plugin/datatables/datatables.min.js` (DataTables 1.10.16 and its
  Bootstrap 4 integration), `buttons.html5.min.js` and `buttons.colVis.min.js` (part of `dataTables.buttons.min.js`
  now), `dataTables.group.min.js` (RowGroup, now `dataTables.rowGroup.min.js`) and `dataTables.cellEdit.js`;
  `css/dataTables.buttons.min.css`, `css/dataTables.select.min.css`, `css/dataTables.responsive.css` and
  `css/dataTables.group.min.css`. `dataTables.buttons.min.js`, `dataTables.responsive.min.js` and
  `dataTables.select.min.js` keep their names; `dataTables.contextualActions.min.js` is unchanged.

### Compatibility
- A template or module of your own that loads one of the removed files gets a 404. Every page layout but the guest
  portal's loads `js/plugin/datatables/dataTables.min.js`, `dataTables.bootstrap4.min.js` and
  `js/iris/datatables_compat.js`; a page that uses an extension loads `dataTables.buttons.min.js` (copy, CSV and
  column visibility included), `dataTables.responsive.min.js`, `dataTables.select.min.js` or
  `dataTables.rowGroup.min.js`, with `css/buttons.bootstrap4.min.css` or the matching `css/datatables_compat.*.css`.
- A table of your own runs on DataTables 3: `.DataTable({...})` and `.dataTable()` work as before, with 1.10.16's
  defaults. The `error` event is now `dt-error` (`on('dt-error.dt', ...)`); for the rest, see DataTables' upgrade
  notes for 2.0 and 3.0. CellEdit's `MakeCellsEditable()` no longer exists.
- No API change.

### Upgrading
- `scripts/update.sh --ref IRIS-NG-v2.24.0`, the 2.24.0 images, or chart 1.24.0. No migration. Static files are
  served with `no-cache`, so a browser picks up the new scripts on its next page load.
- **With the guest portal enabled, `scripts/update.sh` rebuilds the tunnel agent** and so picks up cloudflared
  2026.11.2 (Settings → Guest Portal shows the version it reports). To rebuild the agent alone, from the clone:
  `docker compose -f docker-compose.dev.yml -f docker-compose.portal.yml build --pull tunnel`, then the same with
  `up -d tunnel`. A quick tunnel gets a new hostname whenever it restarts.

---

## [IRIS-NG-v2.23.0] — 2026-11-25

The Process button of the Add Evidence and Edit evidence dialogs hashes the selected file with spark-md5 instead of
CryptoJS, about 2.5 times faster, and fills in a hash only for the file it read: a large file's hash could be saved with
another file's name and size, and a file removed after it was selected was recorded as an empty file. **No
migration.** The app image changes (the Evidence page, its script, the help text); the database and nginx images and
the guest-portal tunnel agent do not.

### Changed
- **CryptoJS 3.1.2 → spark-md5 3.0.2** for the MD5 the Process button computes in the browser (the file is still not
  uploaded). The file is read in 4 MiB pieces; a 600 MiB file hashes in about 6.5 s instead of 16 s, a 4 GiB file in
  about 46 s instead of 110 s (measured in Chrome).
- The Process button's help text says what **Could not read the file** means.

### Fixed
- **A hash saved with another file's name and size.** The dialog took the name and size when the hash finished, from
  whichever file was selected then: selecting another file while a large one was hashing, with or without pressing
  Process again, filled in the first file's hash with the second file's name and size; pressing Process twice ran two
  hashes, the slower one winning; and a hash still running when the dialog was closed filled in the next dialog
  opened. A hash now fills in the hash, name and size of the file it read, and only while it is the latest one:
  pressing Process again, selecting another file or closing the dialog stops it, and it fills in nothing.
- **A file removed after it was selected was recorded as an empty file**, with size 0 and the empty file's MD5
  (`d41d8cd98f00b204e9800998ecf8427e`), and no error: the browser reports a vanished file as 0 bytes. A file removed
  or changed between selecting it and Process now shows **Could not read the file** on the button and fills in
  nothing; select it again. A changed file failed before too, but only in the browser console.
- An empty file's progress read "Processing NaN%".

### Removed
- `js/core/crypto.core.js` and `js/core/crypto.md5.js` (CryptoJS 3.1.2) are no longer served (under
  `/static/assets/`). The Evidence page loads `js/plugin/spark-md5/spark-md5.min.js` instead.

### Compatibility
- A template or module of your own that loads `crypto.core.js` or `crypto.md5.js` gets a 404, and `CryptoJS` is no
  longer defined on the Evidence page (since 2.20.0 it was defined there only). The page's `getMD5(blob[, progress])`
  works as before and resolves with the same lower-case hex.
- No API change; an evidence record's hash is the same MD5 as before.

### Upgrading
- `scripts/update.sh --ref IRIS-NG-v2.23.0`, the 2.23.0 images, or chart 1.23.0. No migration. Static files are
  served with `no-cache`, so a browser picks up the new script on its next page load.

---

## [IRIS-NG-v2.22.0] — 2026-11-25

Every confirmation, alert and "please wait" dialog moves from sweetalert 2.1.2 (unmaintained since 2018) to sweetalert2
11.26.26, and looks and behaves as it did; 22 confirmations now name their action on the button, and the "please wait"
dialogs and three notes prompts no longer close on a click outside. **No migration.** The app image changes (the five
page layouts, the dialog scripts and stylesheets); the database and nginx images and the guest-portal tunnel agent do
not.

### Changed
- **sweetalert 2.1.2 → sweetalert2 11.26.26** for every dialog on every page, the guest portal, the sign-in pages and
  the error pages included. A compatibility layer, `js/iris/swal_compat.js`, keeps `swal()` as it was: the same
  arguments and errors, the buttons in the same order, the same value from each button, from Escape, a click outside,
  the timer and `swal.close()`, the same focus. The dialogs keep their look and motion (`css/swal_compat.css`: the
  colours, sizes and spacing; the pop-in, the fades); titles, text and button labels are shown as text, as before. The
  icons are sweetalert2's.
- **Confirmations name their action:** the confirm button reads "Yes, delete it!", "Yes, delete them", "Yes, close
  it!", "Yes, remove it!", "Yes, remove them!" or "Go for it" where it read OK - on deleting a case object type
  (Case Objects), a user, a group, a customer, a report template, a case template, a datastore file or folder, selected
  timeline events or a case; on closing a case; on removing a module, a group member or case access; and on renewing an
  API key. These labels were in the calls all along; 2.1.2 ignored them. The destructive button stays red.
- **No longer closed by a click outside:** the "please wait" dialogs (alerts being updated or deleted, a datastore
  upload, custom attributes being updated, case templates being added or updated, access being updated) and the notes
  page's conflict, folder rename and folder delete prompts - the calls asked for this, and 2.1.2 ignored it. Escape
  closes what it closed before.

### Removed
- `js/plugin/sweetalert/sweetalert.min.js` is no longer served (under `/static/assets/`). The pages load
  `js/plugin/sweetalert2/sweetalert2.min.js`, `css/sweetalert2.min.css`, `js/iris/swal_compat.js` and
  `css/swal_compat.css` instead.

### Compatibility
- A template or module of your own that calls `swal()` keeps working (new code may call `Swal.fire()`); one that
  loads `js/plugin/sweetalert/sweetalert.min.js` itself gets a 404 (`swal` is already on the page). Its dialogs keep
  2.1.2's class names (`.swal-modal`, `.swal-title`, `.swal-text`, `.swal-footer`, `.swal-button`,
  `.swal-button--confirm` / `--cancel` / `--danger`, `.swal-content__input`), but not `.swal-overlay` (the backdrop is
  sweetalert2's `.swal2-container`) or 2.1.2's icon classes. A dialog shows at most three buttons (2.1.2 had no limit;
  the first and the last two show, with a console warning), and a call's `confirmButtonText`, `cancelButtonText` and
  `allowOutsideClick` now apply.
- No API change.

### Upgrading
- `scripts/update.sh --ref IRIS-NG-v2.22.0`, the 2.22.0 images, or chart 1.22.0. No migration. The app serves static
  files with `Cache-Control: no-cache`, so a browser picks up the new dialogs on its next page load.

---

## [IRIS-NG-v2.21.0] — 2026-11-25

The case graph, the alert graph and the visual timeline move from vis 4.21 (unmaintained, its npm package deprecated)
to vis-network 10.1.5 and vis-timeline 8.5.6, and look as they did; graph tooltips are plain text again, and the
Content-Security-Policy no longer allows `'unsafe-eval'`. **No migration.** The app image changes (three page
templates, three Python files, the two vis scripts, 10 static files fewer) and so does the nginx image (its policy);
the database image and the guest-portal tunnel agent do not.

### Changed
- **vis 4.21 → vis-network 10.1.5 + vis-timeline 8.5.6** on a case's Graph tab, an alert's Graph tab (its
  relationships) and the visual timeline (the case Timeline's **Visualize**, **Visualize by asset** and **Visualize by
  category**). The pages load the two libraries' standalone builds under the names they loaded before,
  `js/plugin/vis/vis-network.min.js` and `js/plugin/vis/vis.graph.js`; these builds carry their own styles, the alert
  graph's navigation-button images and, for the timeline, its own moment (2.30.1). Tooltips, labels, icons, colours,
  the timeline's items, groups, axis and time window are drawn as before; a graph's layout (where each node settles)
  can differ, as it is worked out by a newer version of the same physics.
- **Graph tooltips are plain text.** vis-network 10 shows a node's or a link's tooltip as text, where vis 4.21 read it
  as HTML, so the case graph and the alert graph now send each tooltip as the stored text, line breaks as `\n` - the
  form they had before IRIS-NG-v2.16.2, which escaped them for vis 4.21. A vulnerability node's tooltip lines are
  separated by `\n`. The visual timeline is unchanged: vis-timeline 8 still reads an item's text and tooltip and a
  group's label as HTML (after its own XSS filter), and IRIS still escapes them.
- **The alert graph's icon nodes** no longer set `icon.weight` (`"bold"`): vis 4.21 ignored it, vis-network 10 would
  draw the icons bold.
- **Content-Security-Policy:** `script-src` no longer allows `'unsafe-eval'`, so the browser refuses `eval` and
  `new Function` on every page. Nothing IRIS serves needs them: the only such call any page made was a fallback in
  vis 4.21, inside a `try`.

### Removed
- **Static paths no longer served** (under `/static/assets/`): `css/vis.min.css` and `css/vis.graph.css` (vis 4.21's
  stylesheets), the seven navigation images in `css/img/network/` (`upArrow.png`, `downArrow.png`, `leftArrow.png`,
  `rightArrow.png`, `plus.png`, `minus.png`, `zoomExtends.png`), and `js/core/moments.min.js` - the visual timeline
  was the last page that loaded it, for vis 4.21.
- The UI build drops the `vis` and `moment` packages and adds `vis-network` and `vis-timeline` (npm also records the
  peer packages they name - moment among them - none of which is served).

### Compatibility
- **API change:** in `GET /case/graph/getdata` and `GET /alerts/similarities/<alert_id>`, a node's or a link's
  `title` is the stored text with `\n` line breaks instead of escaped HTML with `<br>`, and an alert graph's icon
  object has no `weight`. The visual timeline's `GET /case/timeline/visualize/data/by-asset` and `/by-category` are
  unchanged.
- A template or module of your own that loads one of the paths above gets a 404, and `window.moment` is no longer
  defined on any page (on the visual timeline, vis-timeline's own is `vis.moment`). One that draws with `vis` gets the
  new libraries: vis-network shows a string tooltip as text (pass an element for markup) and honours `icon.weight`;
  vis-timeline uses its bundled moment rather than the page's. Code that calls `eval` or `new Function` is refused by
  the browser.
- The Kubernetes chart runs no nginx and sets no Content-Security-Policy, so the policy change does not reach it.

### Upgrading
- `scripts/update.sh --ref IRIS-NG-v2.21.0`, the 2.21.0 images, or chart 1.21.0. No migration. `update.sh` rebuilds
  the nginx image with the app; with the published images, a deployment that sets `NGINX_IMAGE_TAG` moves it to
  `IRIS-NG-v2.21.0` too. The app serves static files with `Cache-Control: no-cache`, so a browser picks up the changed
  pages on its next load.

---

## [IRIS-NG-v2.20.0] — 2026-11-24

Static files and script loads nothing used are gone - webfontloader and the vendored `flask_dropzone` module with them -
and the alert graph gets two fixes. **No migration.** The app image changes (page templates, `alerts.js`, the static
files it serves: 46 fewer, 4.45 MiB); the nginx and database images and the guest-portal tunnel agent do not.

### Removed
- **Script loads nothing called:** webfontloader and its `WebFont.load()` on every page (`fonts.css` is linked in each
  page's head, so this is one render-blocking script fewer; two of the font families it waited for were declared
  nowhere), TimelineJS3 on the case timeline, the bootstrap datepicker on the files page (and its stylesheet on the two
  timeline pages), SortableJS on the assets and notes pages, DataTables' print-button plugin (no table has a print
  button), the full vis bundle on Alerts and the case graph (the network build loaded after it was the one in use, and
  stays), and moment on the files page (it stays on the visual timeline, which uses it).
- **CryptoJS** now loads only on the files page, where evidence hashing uses it, instead of on every page.
- **Static paths no longer served** (under `/static/assets/`): `js/plugin/webfont/webfont.min.js`, `js/timeline.js`,
  `css/timeline.css` and `css/icons/tl-icons.*`, `js/core/bootstrap-datetimepicker.min.js`,
  `css/bootstrap-datetime.css`, `js/plugin/sortable/sortable.js`, `js/plugin/bootstrap-slider/bootstrap-slider.min.js`,
  `css/bootstrap-slider.min.css`, `js/plugin/vis/vis.min.js` (`vis-network.min.js` and `vis.graph.js` stay),
  `js/plugin/dropzone/dropzone.min.js` (`dropzone.js`, the same file, stays), `js/plugin/datatables/` -
  `buttons.print.min.js`, `dataTables.dateTime.min.js`, `dataTables.searchBuilder.js`,
  `dataTables.searchBuilder.bs4.js`, `pdfmake.min.js` and `pdfmake.vfs.fonts.min.js` - with
  `css/dataTables.searchBuilder.css`,
  `js/plugin/jquery.sparkline/jquery.sparkline.min.js`, `js/plugin/tagsinput/bootstrap-tagsinput.js` and
  `typeahead.bundle.js` (`suggesttag.js` stays) with `css/bootstrap-tagsinput.css`, `css/atlantis.min.css`
  (`atlantis.css`, the one the pages load, stays), `css/fa.css`, `css/latos.css`, `css/tags.css`,
  `css/bootstrap-select.css.map`, `fonts/flaticon/flaticon.css`, `flaticon.html` and `_flaticon.scss` (the Flaticon
  font stays), the Lato italic and Thin fonts (`fonts.css` uses Light, Regular, Bold and Black), `fonts/summernote/`,
  and `img/iris_logo-black.png`, `logo-alone-2.png`, `logo-alone-2-black.png`, `logo-alone-2-blue.png` and
  `logo-white-2.png`.
- **`flask_dropzone`**, a vendored module no page used (its loaders were never called, and its blueprint has no static
  folder to serve them from), with its two settings `DROPZONE_MAX_FILE_SIZE` and `DROPZONE_TIMEOUT`. The pipelines
  upload form keeps Dropzone itself (`dropzone.js`).
- The UI build drops the `bootstrap-slider`, `sortablejs` and `webfontloader` packages; no other package moves.

### Fixed
- **The alert graph's navigation buttons** (arrows, zoom, fit) show their icons: the seven images they use were never
  served, and each answered 404.
- **The alert graph's icons** (alerts, IOCs, cases) are drawn once their icon font has loaded. Before, the first icon
  was drawn while the font was still loading, and came out right only when the font file was already cached.

### Compatibility
- A template or module of your own that loads one of the paths above gets a 404, and `window.WebFont`, `window.TL`,
  `window.Sortable`, the bootstrap datepicker's `$.fn.datepicker` and DataTables' `print` button type are no longer
  defined; `CryptoJS` is defined on the files page only. The `wf-*` classes webfontloader set on `<html>` are
  gone.
- No route or reply changes.

### Upgrading
- `scripts/update.sh --ref IRIS-NG-v2.20.0`, the 2.20.0 images, or chart 1.20.0. No migration. The app serves static
  files with `Cache-Control: no-cache`, so a browser picks up the changed pages on its next load.

---

## [IRIS-NG-v2.19.0] — 2026-11-24

The charts move to Chart.js 4.6.2 (from 2.9.4, whose line has had no release since 2020) and look as they did. **No
migration.** The app image changes - four page templates, two chart scripts updated, one added and one removed; the
nginx and database images and the guest-portal tunnel agent do not.

### Changed
- **Chart.js 2.9.4 → 4.6.2** on Metrics, Inventory and the custom dashboards (their view and their editor). Chart.js 4
  changed most of its defaults, so a new script, `chart_defaults.js`, loaded right after `charts.js`, puts back what
  2.9.4 did by default: the axis layout (slanted labels included), the darker grid line at zero, numbers without a
  thousands separator in tooltips and axis labels, doughnut and pie tooltips without a title, a hover that highlights
  every bar or point at that position, and the legend box of a line drawn without fill in its line colour. Each chart
  was compared with 2.9.4 on the same data - what it draws, its legend, axes and plot area, and the tooltip a hover
  shows - and they match; bar borders and the edges of doughnut slices differ by up to one pixel (Chart.js 4 draws a
  bar's border inside the bar).
- The UI build gains one package, `@kurkle/color` (Chart.js 4's colour library; the pages load Chart.js's own bundle,
  which includes it), and loses Chart.js 2's `chartjs-color` packages.

### Removed
- `/static/assets/js/core/Chart.PieceLabel.min.js`, a Chart.js 2 plugin no chart used. Chart.js 4 has no
  `Chart.pluginService`, so it would fail as soon as it loaded.

### Compatibility
- `/static/assets/js/core/charts.js` keeps its name and is now Chart.js 4; it still sets `window.Chart`. A template or
  module of your own that draws with it needs Chart.js 4's options: `scales.x` / `scales.y` instead of `xAxes` /
  `yAxes`, `plugins.legend` and `plugins.tooltip` instead of `legend` and `tooltips`, `cutout` instead of
  `cutoutPercentage`, and `type: 'bar'` with `indexAxis: 'y'` instead of `horizontalBar` - Chart.js's 3.x and 4.x
  migration guides list the rest.
- No route or reply changes.

### Upgrading
- `scripts/update.sh --ref IRIS-NG-v2.19.0`, the 2.19.0 images, or chart 1.19.0. No migration. The app serves static
  files with `Cache-Control: no-cache`, so a browser loads the new chart scripts on its next page load.

---

## [IRIS-NG-v2.18.0] — 2026-11-24

The background task library moves to celery 5.7 (from 5.6). **No migration of IRIS's own**: celery adds two empty
columns to its own results table at the first start (see Upgrading). The app image changes; the nginx and database
images and the guest-portal tunnel agent do not.

### Security
- **Stored task results are never unpickled.** Until now every task result was stored as a pickle, and opening a
  task's details in DIM Tasks unpickled it in the web process; celery 5.7 still unpickles any stored result that looks
  like one. IRIS's result backend no longer does, so write access to the results database no longer leads to code
  running in the web process.

### Changed
- **celery 5.6.3 → 5.7.0.** Since 5.7 celery stores each task's result as JSON. Module hooks, import pipelines, AI
  jobs and the update check return an IRIS status that JSON could not encode - on celery 5.7 alone each of them would
  have been recorded as failed although it ran. IRIS now stores that status as JSON: its code, message and logs, and
  the data a module hands back only when it is plain JSON (modules return the records they were given, and nothing
  reads them back). DIM Tasks shows the module's verdict and logs as before.
- **Unpinned package in the released image:** babel 2.18.0 → 2.19.0, published hours before this release and resolved
  by its build (no requirement of IRIS names it; docxcompose, the `.docx` report library, requires it). docxcompose
  formats the date of a Word document-property field with it, which IRIS's reports never update; the bundled report
  templates render identically with either version.

### Compatibility
- **DIM Tasks, for tasks that ran before the update:** their stored result is a pickle IRIS no longer opens. The task
  list still shows their state; their details say the task ran before IRIS-NG-v2.18.0 instead of showing the module's
  verdict and logs. celery's clean-up removes results more than a day old every day at 04:00 UTC, so these are gone
  within two days.
- No route or reply changes.

### Upgrading
- `scripts/update.sh --ref IRIS-NG-v2.18.0`, the 2.18.0 images, or chart 1.18.0. Take a database dump first as usual
  (`scripts/update.sh` does).
- At its first start celery 5.7 adds the columns `children` and `stamps` to its table `celery_taskmeta` (database
  `iris_tasks`). As the app and both workers start together, a process may log `Failed to add missing column ...
  already exists` for a column another one added first; that is harmless and happens only at that first start.
- **Rolling back to 2.17.x** afterwards: the workers keep working and the DIM Tasks list still loads, but opening the
  details of a task that ran on 2.18.0 shows an error until the daily clean-up has removed those results.

---

## [IRIS-NG-v2.17.1] — 2026-11-24

A dependency release. **No migration.** The app image changes (SQLAlchemy, and of the built browser files the bundled
jQuery, the Markdown renderer and the sign-in page's script); the guest-portal tunnel agent gets a newer cloudflared;
the nginx and database images do not change.

### Fixed
- **A guest-portal quick tunnel could not connect where UDP to Cloudflare's edge is dropped** (cloudflared 2026.11.0 →
  2026.11.1 in the guest-portal tunnel agent). Since 2.16.0 the agent's cloudflared used QUIC only for a quick tunnel,
  so on such a network the portal stayed unreachable; it now falls back to HTTP/2 over TCP after about two and a half
  minutes. cloudflared also updates its OpenTelemetry library and reconnects when the account's region changes. The
  agent starts, and restarts cloudflared after a crash, as before.
- **Notes with a long run of `**` rendered slowly** (Markdown renderer marked 18.2.0 → 18.2.1). A run of emphasis
  delimiters was matched in quadratic time: 10 000 of them kept the browser busy for about 2 seconds; it now takes
  milliseconds.

### Changed
- **Markdown rendering** (marked 18.2.1) fixes fifteen parsing corner cases. Notes render as before except where a fix
  applies: trailing blank lines in a fenced code block are kept, backslashes in a code span inside link text are kept, a
  tab in a code block inside a quote is kept, and a link whose `<...>` destination holds an unescaped `<` or `>` is no
  longer a link (its text still goes through the HTML filter).
- **jQuery 3.7.1 → 3.8.0**, the copy every page loads: a selector with a long crafted identifier no longer takes
  excessive time to match, `.html()` runs a script that removes itself, `jQuery.cleanData` no longer skips elements,
  and `<col>` dimensions are read correctly. 3.8.0 deprecates `push`, `sort`, `splice` and `jQuery.expr[":"]`, which
  IRIS's own code does not use.
- **SQLAlchemy 2.1.8 → 2.1.9**: fixes for relationships to an aliased class over a correlated LATERAL subquery, for
  flushing mapped dataclasses with certain column defaults, and for SQL Server primary-key reflection. IRIS uses none of
  these, and its replies are unchanged.
- **Svelte 5.57.3 → 5.59.1** rebuilds the sign-in and demo pages' scripts (runtime fixes); sign-in works as before.

### Upgrading
- `scripts/update.sh --ref IRIS-NG-v2.17.1`, the 2.17.1 images, or chart 1.17.1; nothing else changes. **With the
  guest portal enabled, `scripts/update.sh` rebuilds the tunnel agent** and so picks up cloudflared 2026.11.1 (Settings →
  Guest Portal shows the version it reports). To rebuild the agent alone, from the clone: `docker compose -f
  docker-compose.dev.yml -f docker-compose.portal.yml build --pull tunnel`, then the same with `up -d tunnel`. A quick
  tunnel gets a new hostname whenever it restarts.

---

## [IRIS-NG-v2.17.0] — 2026-11-24

The schema layer moves to marshmallow 4 (marshmallow 3 is end of life), with flask-marshmallow 1.5 and
marshmallow-sqlalchemy 1.6. **No migration.** The app image changes; the nginx and database images and the
guest-portal tunnel agent do not.

### Changed
- **marshmallow 3.26.2 → 4.4.0, flask-marshmallow 1.4.0 → 1.5.0, marshmallow-sqlalchemy 1.5.0 → 1.6.0.** No other
  package moves. Replies and refusals are unchanged: a contract probe compared every IRIS schema (53) between the two -
  real records dumped, each field's output and parsing over inputs of its type, whole-request refusals - and the full
  test suite answered the same.
- **Kept as it was:** IRIS's schemas keep the placeholder database session they have always had. flask-marshmallow 1.5
  hands auto schemas the real session, and with it a create request naming an existing record's id would load that
  record and overwrite it; with the placeholder such a request still fails before any record is read. Boolean and
  date-time fields write their values as before (marshmallow 4 would pass a non-boolean value through a Boolean field
  and fail on a plain date in a date-time field).

### Compatibility
- **More date input is accepted.** marshmallow 4 reads dates with Python's own parser. A date-time field - an alert's
  times, an evidence's acquisition, start and end dates, a task's or a note's dates, among 33 - now takes a date alone
  (`2026-11-24`, read as midnight), a date and an hour (`2026-11-24T10`), the basic format (`20261124T100000`) and an
  ISO week date (`2026-W48-2`); a case's open and close dates take `20261124` and `2026-W48-2`. Each was refused before
  with "Not a valid datetime." / "Not a valid date.". Input accepted before is read as before, and a timeline event's
  date (`event_date`, `event_date_wtz`), which has a format of its own, is unchanged.
- No route or reply changes otherwise. Chart 1.17.0.

---

## [IRIS-NG-v2.16.10] — 2026-11-24

A security release: in war rooms, custom dashboards, asset flags and tutorials, a reply carries only what its caller
may see and a request changes only what its caller may change. **No migration.** The app image changes; the nginx and
database images and the guest-portal tunnel agent do not.

### Security
- **The war-room Scope's staging push told a responder whether a case they cannot open holds an IOC or asset.**
  `POST /api/v2/war-rooms/<id>/scope/staging/<sid>/push` removed the staged row, and answered `removed: true`, once
  every target case held the item, whether or not the caller could open those cases. Presence is now asked only of
  cases the caller can read: a row with a target they cannot read stays, for a member who can push it there.
- **Custom dashboards drew alerts for a user without the alerts-read permission.** A widget over the alerts source
  showed alert rows and counts in the viewer's customers to any user. It now shows *Needs the alerts-read
  permission.* (the other widgets still draw), and the editor no longer offers the alerts source to that user.
- **A guest's war-room Board showed each attached case's customer, owner and task counts**, which the guest view of
  the Cases tab never shows. A guest's case cards no longer carry them; the room's own tasks stay in the figures.
- **A deleted Stream message could still be read.** Deleting hides a message and keeps it for the record, but
  `GET /api/v2/war-rooms/<id>/messages` still returned it to every member and guest, a file that only deleted
  messages carried was still served, a deleted `/decision` message was still offered for the register and promoted,
  and the AI room summary and SitRep drafts still read it. None of them do now. An activity line quoting a deleted
  message (a pin) shows *Pinned a message* without the message's first words, and a search no longer matches it; the
  stored rows are left as they are.
- **Asset-flag in-use counts counted every case**, those the caller cannot open included. `GET
  /api/v2/manage/asset-flags?counts=true` gives them to administrators only, whose Settings page shows them.
- **The tutorial clean-up deleted a case for a user without the `standard_user` permission** the case delete routes
  require; it now requires it too.
- Each is in every release since its feature: the Scope, the Board, the Stream and asset flags since 2.10.0, custom
  dashboards since 2.11.0, tutorials since 2.13.0.

### Fixed
- An archived Stream topic refuses reactions and thread renames, as it refused new messages and edits; deleting a
  message there is still allowed.
- The Stream's *Show in activity* links (`#activity-...` in a message) are made from the message's text only: before,
  `#activity-...` inside a resource chip's text got a link built inside the chip's link.

### Hardening
- The links of the help tips, the tutorial runner's *Take me there* link and the asset-type icons of the Case Objects
  page accept a path only when the browser resolves it to this site: `/`, then a tab or a line break, then `/host`
  passed the old check and led to another site. Each value comes from IRIS-NG's own glossary or from what an
  administrator sets (a tutorial, an asset type's icon).

### Compatibility
- `GET /api/v2/war-rooms/<id>/messages` leaves out deleted messages.
- `GET /api/v2/war-rooms/<id>/files/<file_id>`: a file that only deleted messages carry answers `404`, and a message
  posted or edited with it answers `400` *An attachment is not a file of this room*. A file no message carries yet (an
  upload waiting to be sent) is unchanged.
- `GET /api/v2/war-rooms/<id>/decisions/chat-candidates` leaves out deleted messages; `POST
  /api/v2/war-rooms/<id>/decisions` naming a deleted one as `chat_message_id` answers `400`.
- `GET /api/v2/war-rooms/<id>/stream`: an activity line quoting a deleted message has *Pinned a message* or *Unpinned
  a message* as its `content`, and a search leaves it out.
- `POST /api/v2/war-rooms/<id>/messages/<message_id>/reactions` and `PUT
  /api/v2/war-rooms/<id>/messages/<message_id>/thread-title` in an archived topic answer `400` *Topic #... is archived -
  it is read-only*.
- `POST /api/v2/war-rooms/<id>/scope/staging/<sid>/push`: `removed` is `false`, and the row stays, while a target
  case is one the caller cannot read.
- `GET /api/v2/war-rooms/<id>/board` for a guest: each case card's `customer_name`, `owner_name`, `tasks_open` and
  `tasks_in_progress` are `null`.
- `GET /api/v2/manage/asset-flags?counts=true`: a non-administrator's rows carry no `in_use_count`.
- `GET /api/v2/custom-dashboards/<key>/data` and `POST /api/v2/custom-dashboards/preview`: for a user without
  alerts-read an alerts widget answers `ok: false` with the error *Needs the alerts-read permission.*; `GET
  /api/v2/custom-dashboards/schema` gains `unavailable_sources` (`["alerts"]` for that user, else `[]`).
- `POST /api/v2/tutorials/run/cleanup` refuses a case for a user without `standard_user` (*You cannot delete case
  #N.*).
- No other route or reply changes. Chart 1.16.10.

---

## [IRIS-NG-v2.16.9] — 2026-11-24

A security release: an alert request sets only the alert's own fields, in customers the caller can access, and the
alert list's custom conditions answer nothing about cases or users the caller cannot see. **No migration.** The app
image changes; the nginx and database images and the guest-portal tunnel agent do not.

### Security
- **A user with `alerts_write` could move an alert into a customer they cannot access.** `POST /alerts/update/<id>`
  and `POST /alerts/batch/update` checked the alert's current customer, then took `alert_customer_id` from the request.
  The customer must now exist and be one the caller can access.
- **An alert request could create customers, severities and alert statuses.** The alert routes load a request with
  every relationship of the alert, so a nested object in an update or in `POST /alerts/add` created its row: a
  `customer` object a new customer, with the alert placed in it (past the create's customer check), `severity` /
  `status` new entries in those lists, `iocs` / `assets` new IOCs and assets. These keys are now refused on create and
  update, and an update can no longer change the alert's id.
- **The alert list's custom conditions answered questions about cases and users the caller cannot see.** A condition
  on an alert's linked case (`cases.<column>`) told whether a case the caller cannot open matches - one guess per
  request - and a condition on the alert's owner reached any user column outside a short list, such as the hourly
  rate or the MFA counters. A case condition now matches only cases the caller can read, and an owner condition takes
  only the owner's id, login, name and email, which the alert shows; any other owner field is skipped, as the listed
  ones were.
- Smaller: the alert queue's detail lists and counts only the cluster members the caller can see - an alert moved to
  another customer stays in its cluster.
- The update and create routes and the custom conditions are inherited and present in every earlier IRIS-NG release;
  the user columns a condition reached grew with IRIS-NG (the MFA counters since 2.16.0). The alert queue's cluster
  summary is in every release since 2.11.0.

### Compatibility
- `POST /alerts/update/<id>` and `POST /alerts/batch/update`: an `alert_customer_id` naming a customer that does not
  exist answers `400` *Customer #N not found* (before: a database error, also `400`); one the caller cannot access
  answers `403`, as the alert's own customer always did. A body naming a related record - `customer`, `owner`,
  `severity`, `status`, `classification`, `resolution_status`, `iocs`, `assets`, `cases`, `comments` - answers `400`:
  send the `*_id` fields. An `alert_id` other than the URL's answers `400`, and a batch's `updates` take none.
- `POST /alerts/add` refuses the same related-record keys with `400`; IOCs and assets still come as `alert_iocs` /
  `alert_assets`.
- `custom_conditions` (`/alerts/filter`, `/api/v2/alerts`, the alert queue): a `cases.<column>` condition matches only
  cases the caller can read; an `owner.<column>` condition other than `id`, `user`, `name` or `email` is skipped.
- No other route or reply changes. Chart 1.16.9.

---

## [IRIS-NG-v2.16.8] — 2026-11-24

A security release: setting a task's status from Home needs full access to the task's case, custom attribute fields
drawn as HTML take no value from a request, and the last stored names and links of the 2026-10-23 review are shown as
text or kept on this site. **No migration.** The app image changes; the nginx and database images and the guest-portal
tunnel agent do not.

### Security
- **Any signed-in user could set the status of any case's task.** `POST /user/tasks/status/update` - the status menu
  of Home's task list - checked no case access. It now checks the case named in the request at full access, as the
  case page's own status route does.
- **Custom attribute fields of type `html` and `raw` took their value from requests.** An `html` field is drawn as
  HTML in every object's attribute tabs, and the IOC page's intel panel drew `raw` fields as HTML too; both are meant
  for module output. The API copied a request's value for them on create, and for a `raw` field on update, so once an
  administrator defined such a field, any user who could edit the object could store markup in it. A request's value
  for these fields is now ignored; modules keep writing them. The intel panel shows a `raw` value as text.
- **An asset's name could break out of the legacy assets table's alerts popover.** The name sat raw inside a
  single-quoted attribute of a focusable icon, so a quote in it ended the attribute and the rest of the name became
  attributes of the icon.
- **The Notes page's *Move item* dialog drew folder names as HTML.**
- Smaller: the alert cluster page puts its `?cid=` into links only as a number; Home's notification and following
  links are kept only when they are an http(s) address on this site; the access-control modals write case, group and
  access names into their scripts as JSON strings - a case name ending in a backslash broke the modal's script.
- The task status route, the attribute API, the assets popover, the *Move item* dialog and the access-control modals are
  inherited and present in every earlier IRIS-NG release; the IOC intel panel, the cluster page and Home's links in
  every 2.x release.

### Compatibility
- `POST /user/tasks/status/update` refuses a task in a case the caller cannot change with the same `400` as an
  unknown task; before, a user who could only read a case - or had no access to it - could set its tasks' status.
- A request's value for an `html` or `raw` custom attribute field is ignored on create and update; modules are not
  affected.
- No other route or reply changes. Chart 1.16.8.

---

## [IRIS-NG-v2.16.7] — 2026-11-24

The timeline highlights a case's IOCs in the text of each event, never inside its markup. **No migration.** The app
image changes; the nginx and database images and the guest-portal tunnel agent do not.

### Fixed
- **IOC highlighting wrote into links, images and entities.** The timeline highlighted IOCs by running a pattern per
  IOC over the rendered HTML of each event's title and content, so the highlight landed wherever the value appeared:
  inside a link's address or an image's alt text and title (the link or image broke, and the rest of its tag showed
  as text), inside an entity such as `&lt;`, and as an attribute's name - an IOC `href` took the address off every
  link on the timeline. It could not run script: what it inserted was fixed markup with the value sanitized and the
  description escaped, and the popovers show text. Highlighting now walks the rendered text and builds each highlight as an
  element; links, images and entities stay as written.
- **Matching.** The patterns' word boundaries matched anywhere, so `10.0.0.1` lit up inside `10.0.0.15` and
  `evil.com` inside `notevil.com`. A match is now a whole token - no letter, digit or underscore on either side - so
  `evil.com` still lights up in `sub.evil.com` and in `https://evil.com/x`. Matching ignores letter case (the text
  keeps the case it was written in), and IOCs longer than 64 characters - long URLs, every SHA-512 - are highlighted
  too. A value holding `&`, `<` or `>` is now highlighted where the text has it (it never was).
- Of two overlapping IOCs the longer is the highlight; before, the one the database returned first won.
- An IOC with no value no longer stops the timeline from drawing.

### Compatibility
- No route, reply or setting changes. Code and link text are highlighted as before; the compact view still highlights
  titles only.
- Chart 1.16.7.

---

## [IRIS-NG-v2.16.6] — 2026-11-23

A small change to the war room's guest invitation form. **No migration.** The app image changes; the nginx and
database images and the guest-portal tunnel agent do not.

### Changed
- The guest invitation form (a war room's Members > Add member > Guest) shows "Example Organisation" as the
  Organisation field's example text, in the style of the form's other examples ("Jane Doe", jane@example.org).

### Compatibility
- No route, reply or setting changes.
- Chart 1.16.6.

---

## [IRIS-NG-v2.16.5] — 2026-11-23

A security release: table cells show stored text as text, and a user can change only their own password through
`POST /user/update`. **No migration.** The app image changes; the nginx and database images and the guest-portal tunnel
agent do not.

### Security
- **A display name, an asset's fields and other stored text ran in tables.** The tables write a cell's value into the
  page as HTML unless the column escapes it, and several did not: on a customer's page the users list (display name,
  login), the assets list (name, description, type, IP) and the cases list (open date, state, the owner's display
  name); the case templates list (description, added by, created, updated); and the attributes list (description). A
  display name holding an `<img onerror=...>` ran for whoever opened that customer's users or cases list, and an
  asset's name or description - written by an analyst, an import or an alert - in its assets list. Each of these
  cells shows its value as text now.
- **Any user could change their own display name, login and email, and mark themselves a service account.**
  `POST /user/update` loaded every field of the user schema, although the profile page sends only a new password and
  shows the rest read-only. It now accepts only the password; an administrator changes the rest from Manage > Users.
  Marking oneself a service account did not bypass MFA: a service account cannot sign in with a password.
- Both are present in every earlier IRIS-NG release, 1.x included.

### Removed
- The modal note editor template (`modal_note_edit.html`), which no page has rendered since at least IRIS-NG-v1.2.2.

### Compatibility
- `POST /user/update` refuses a request naming any field other than `user_password` (and the `csrf_token` a browser
  sends) with `400` "Only your password can be changed here...". A client that changed its own name, login, email or
  service-account flag through it gets that error now; an administrator's `POST /manage/users/update/<id>` is
  unchanged. No other route or reply changes.
- Chart 1.16.5.

---

## [IRIS-NG-v2.16.4] — 2026-11-23

A security release: no stored or supplied value sits inside an inline click handler any more, and the alert owner list
shows each user's display name as text. With it, Markdown tables keep their column alignment wherever the case pages
draw Markdown. **No migration.** The app image changes; the nginx and database images and the guest-portal tunnel
agent do not.

### Security
- **A user's display name ran in the alert owner list.** Opening *Assign to...* on an alert, or the queue's batch
  *Assign...*, put every user's display name into the list as markup, and Chrome builds an element written inside a
  list option: a name holding an `<img onerror=...>` ran in the page of whoever opened the list. Any user can change
  their own display name from their profile. The names are text now.
- **A quote in an asset name ran when the asset editor was minimized.** The editor's Minimize button carried the
  asset name inside its inline click handler. The page escaped the quote, but the browser decodes it again before the
  handler runs, so a name such as `x'); ...; //` ran its code for whoever minimized that asset's editor. An asset name
  can also arrive from an alert, by mail or through the API.
- **The same pattern in four more places:** the DIM task feed and the DIM tasks page carried the task id, a module's
  manual-hook menu the hook and module names (and showed the hook name as markup), and the module page's parameter
  link the parameter name. Only Celery or a module's own code writes those values.
- Every such control now carries its value in a `data-` attribute that one shared listener reads, and the hook menu
  shows the name as text. All of these are present in every earlier IRIS-NG release, 1.x included.

### Changed
- Markdown tables keep their column alignment (`:--`, `:-:`, `--:` under the header row) wherever the case pages draw
  Markdown: the Notes page, the case summary, descriptions, comments, the IOC page's Notes tab and both timeline
  views. A cell's alignment can only be left, center or right. 2.16.3 had removed it from the IOC Notes tab and the
  timeline; the Notes page and the descriptions had never shown it.

### Compatibility
- No route or reply changes. The DIM task id is URL-encoded in `GET /dim/tasks/status/<task_id>` (a Celery task id
  is unchanged by it).
- Chart 1.16.4.

---

## [IRIS-NG-v2.16.3] — 2026-11-23

A security release: Markdown drawn in the browser is always filtered, so a note read on the IOC page's Notes tab and
a link in an event's content in the timeline's compact view can no longer run script. **No migration.** The app image
changes; the nginx and database images and the guest-portal tunnel agent do not.

### Security
- **A note read on the IOC page's Notes tab ran its markup.** The tab reads in place the notes an IOC is linked to,
  and drew the note's Markdown as HTML without filtering it, so markup in the note - an element that runs script as
  soon as it is shown, such as `<details open ontoggle=...>` or `<input autofocus onfocus=...>` - ran in the page of
  whoever opened the note there, with nothing else to click. A note is written by anyone with write access to the
  case, through the API or by a case import. Present since IRIS-NG-v2.0.0.
- **A Markdown link to a `javascript:` URL in an event's content could be clicked in the timeline's compact view.**
  The view filtered the event's Markdown before converting it, which removes raw markup but leaves a Markdown link's
  address as written; clicking the link ran the script. Present in every earlier IRIS-NG release, 1.x included.
- Both are closed in one place: the browser's shared Markdown converter now filters the HTML it returns with the
  list of elements and attributes the Notes page uses, so no page can show its output unfiltered. Pages that already
  filtered show the same as before, except for the table alignment below.

### Changed
- A Markdown link to a `javascript:` URL shows with an empty address on the IOC page's Notes tab and in the
  timeline's compact view, as it already did on the Notes page.
- Raw HTML in a note shows on the IOC page's Notes tab as it does on the Notes page: an element the list does not
  allow is shown as text.
- Tables in the timeline's expanded view no longer keep their columns' alignment (`:--`, `--:`): the Notes page's
  list allows no `align` attribute.

### Compatibility
- No route or reply changes. A script calling the page's `get_showdown_convert().makeHtml()` gets filtered HTML.
- Chart 1.16.3.

---

## [IRIS-NG-v2.16.2] — 2026-11-21

A security release: stored text in the alert Relationships graph, the case Graph tab and the visual timeline is shown
as text, and the Relationships graph shows only the cases the viewer can open. With it, the two helper scripts run
Compose from the clone root, which keeps a Windows build from being refused. **No migration.** The app image changes;
the nginx and database images and the guest-portal tunnel agent do not.

### Security
- **Stored text in the graphs and the visual timeline ran as HTML.** The library behind the alert Relationships
  graph, the case Graph tab and the visual timeline (by category and by asset) puts a node's or an edge's tooltip, a
  timeline item's text and tooltip, and a timeline group's name into the page as HTML. They were built from stored
  text as it was, so markup in an alert's or a case's description, an asset's or an IOC's description, an event's
  title or content, or an asset, note, evidence file or event category name ran in the page of whoever hovered it or
  opened the view - an alert's description can arrive by mail or through the API, an event's title through an
  import. That text is now escaped, its line breaks kept; node labels, which the graph draws on its canvas as text,
  are unchanged. A timeline item's colour is written into its style only when it is a hex colour.
- **The alert Relationships graph showed cases the viewer cannot open.** It drew every case of the alert's customer
  that shared an asset or an IOC with the alert, each with the case's description in its tooltip, whatever the
  viewer's access to that case. It now draws only the cases the viewer can open (read-only access is enough), by the
  same check as opening the case.
- Both are present in every earlier IRIS-NG release, 1.x included.

### Fixed
- **Pivot on an asset or an IOC in the alert Relationships graph** used the value up to its first `_` and put it into
  the alerts link unencoded, so `srv_db01` opened the alerts of `srv`, and a value holding `&`, `#` or `+` broke the
  link. It now takes the whole value and encodes it.
- **`scripts/iris_helper.sh` and the import of `scripts/import_vanilla_db.sh` run Compose from the clone root,**
  wherever they are started. On Windows a Compose build started from a folder whose drive letter is lower case
  (`c:\...`) is refused by Docker Buildx Bake ("additional privileges requested: pass --allow=fs.read=..."; seen with
  Docker Compose v5.6.1 and Buildx v0.38.1), and both scripts ran Compose from wherever they were started; the `cd`
  hands Compose the letter in upper case, and the scripts now also run from any other folder. A relative path given
  to `-e`, typed at the `.env` prompt or given to `--from` is read from the folder the script was started in; started
  from the clone root, the scripts pass Compose the same arguments as before. The export mode of
  `import_vanilla_db.sh` stays in the folder it is started in. `scripts/update.sh` already changed into the clone
  root, and Linux is not affected. The scripts are not part of the images: a clone gets them at this tag.

### Changed
- A graph or timeline tooltip whose text holds several lines (an asset's or an IOC's description, an event's
  content) shows them on several lines, and markup typed into a description is shown as typed.

### Compatibility
- `GET /alerts/similarities/<alert_id>` no longer lists the cases (nodes and their edges) the caller cannot open. Its
  `title` fields, those of `GET /case/graph/getdata` and the `title`, `content` and `group` fields of
  `GET /case/timeline/visualize/data/by-asset` and `/by-category` are escaped HTML with `<br>` for line breaks: a
  client reading them gets `&lt;`, `&amp;` and so on where it got the characters. A timeline item whose colour is not
  a hex colour comes without `style`. No other route or reply changes.
- Chart 1.16.2.

---

## [IRIS-NG-v2.16.1] — 2026-11-19

A security release: values written into page attributes are escaped, quotes included, and a case import keeps only
the event colours and time zones the event form accepts. With it, a fix for workers that stopped for good when they
started before the database. **No migration.** The app image changes; the nginx and database images and the
guest-portal tunnel agent do not.

### Security
- **Stored values could break out of the attribute they were written into.** Several pages put stored text into an
  HTML attribute through `sanitizeHTML` / `filterXSS`, which escapes neither quote, so a value holding one could close
  the attribute and add attributes of its own - an event handler included, which the content security policy lets
  run. Every such value now goes through one escaper (`iris_escape`, which escapes `& < > " '`):
  - the IOC table's link to another case sharing an IOC (that case's name and customer);
  - the timeline: the "Added by" tooltip (the creator's display name, which every user sets for themselves), an IOC's
    popover (its description), and a card's colour and local-time tooltip (both settable through a case import);
  - the avatar beside a comment and in a note's viewer list, whose tooltip carried the display name with no escaping
    at all.
- **Hardening of the same kind**, where only seeded or system values reach the attribute today: the task-status and
  TLP badge colours on the task, IOC and search pages, the module-task state tooltip, and the module-task feed, whose
  task name, user and date were written into the page without escaping. Twenty page helpers that escaped `& < >` but
  neither quote (the alert-cluster pages, Home, the Settings pages for attributes, case templates, clustering rules,
  customer assets, customers, investigation flows, mail rules, modules, objects, report templates and server settings,
  the condition builder, the flow checklist, the correlation workspace and its IOC cards, the metrics page and the
  notifications bell) now use the same escaper.
- **A case import wrote any event colour and time zone.** An imported `.iris-case` file's `color` and `tz` were stored
  as they came, so a crafted file could put any text into a timeline card's style attribute or the local-time tooltip.
  An import now keeps a colour of the timeline's palette or one of the verdict colours, and a time zone that parses the
  way the event form's does; anything else imports as no colour or `+00:00`, with a warning naming the event.
- All of these are present in every earlier IRIS-NG release, 1.x included.

### Fixed
- **A worker that started before the database stopped for good, and its container stayed Up.** At start each worker
  tried the database three times within the same second (the 0.5 s `DB_RETRY_DELAY` default was read as a whole
  number, 0) and exited; the start-up script ran each process in the background behind a `sleep` loop, so the
  container stayed Up and its restart policy never fired. After a host or Docker restart that started the workers
  first, nothing consumed the task queues - AI jobs, module hooks, MISP sync and the scheduled tasks - until someone
  restarted the workers by hand. Now the workers and the app wait for the database for at least a minute (30 tries,
  2 s apart; a connection that gets no answer gives up after 5 s; while the database container is stopped, each try
  also waits for its name not to resolve, about two minutes in all), and each process is its container's main
  process: one that exits stops the container, and Docker or Kubernetes start it again. The app's gunicorn runs the
  same way.
- The AI panel's "Queued — position #N" counted every job ever left queued, including ones whose queue message was
  lost (a worker down, a broker recreated with messages on it); it now counts the jobs ahead submitted in the last 24
  hours.
- Escalating or merging an alert whose title holds `<` or `>` filled the new case's title with `&lt;` / `&gt;`; the
  dialog now takes the title as it is. Assignee names in the task dialog and the timeline's asset popover show their
  values as stored instead of filtered.
- A note viewer whose name holds `<` or `>` was not removed from the note's viewer list on leaving: the list stored the
  filtered name and the leave message carries the real one.
- The message shown when a stored MFA secret can no longer be used names the real settings path (Settings → Access
  Control → Users → your account → Reset MFA); 2.16.0's named one that does not exist.

### Removed
- The search page's "Seen on MISP" marker beside comment results: it read fields a comment result never carries, so
  it was never shown.

### Compatibility
- A case file whose events carry a colour outside the timeline's palette and the verdict colours (which no IRIS export
  writes) imports those events without a colour, with a warning; one whose time zone does not parse imports them at
  `+00:00`. The import reply's `warnings` list names each such event. No route or API reply changes otherwise.
- `DB_RETRY_COUNT` / `DB_RETRY_DELAY` default to 30 / 2 (were 3 / 0.5, in effect 0 s); a fraction set by hand works
  (`DB_RETRY_DELAY=0.5` stopped the boot with a `ValueError` before). The chart still sets 5 / 5 for the app; its
  workers now use the defaults.
- A container whose process exits is started again by its restart policy instead of staying Up with nothing running,
  so `docker ps` (or the pod's restart count) shows it. A stop now reaches celery and gunicorn themselves, which shut
  down cleanly (celery's warm shutdown, gunicorn's graceful one) within the stop timeout; before, the shell in front
  of them ignored it and Docker killed everything once the timeout ran out (compose's default: 10 seconds).

### Upgrading
- **Docker Compose with `docker-compose.dev.yml` or `scripts/update.sh`:** `bash scripts/update.sh --ref
  IRIS-NG-v2.16.1`. From a release before 2.16.0 it also runs 2.16.0's migration `b3f7d1a9c5e2` (the script takes the
  database dump first); from a release before 2.14.0, take the new script first, as the 2.14.0 notes describe.
- **The image-based `docker-compose.yml`:** `git checkout IRIS-NG-v2.16.1 && docker compose pull && docker compose up
  -d`.
- **Kubernetes:** chart 1.16.1; `helm upgrade` needs nothing else.
- **AI jobs left at "Queued" by workers that were down:** once both workers consume again (`docker exec
  iriswebapp_rabbitmq rabbitmqctl list_queues name messages_ready consumers` shows a consumer on `celery` and
  `ai_queue`) and `ai_queue` holds no messages, a job still `queued` can never run; cancel such jobs with
  `docker exec iriswebapp_db psql -U postgres -d iris_db -c "update ai_job set state='cancelled', finished_at=now()
  where state='queued' and submitted_at < now() - interval '1 hour';"` (a cancelled job's message, if one turns up,
  is skipped).

---

## [IRIS-NG-v2.16.0] — 2026-11-19

A security release: multi-factor sign-in can no longer be bypassed or guessed at, the user routes stop returning MFA
secrets and password hashes, and a round of dependency updates. **One migration**, `b3f7d1a9c5e2`, adds three columns
to `user` at the first start - take a database dump first (`scripts/update.sh` does). The app image changes; the
guest-portal tunnel agent gets a newer cloudflared; the nginx and database images do not change.

### Security
- **A password alone could replace an account's authenticator.** The MFA setup page was reachable right after the
  password step, before the second factor was checked. It asked for the password again but not for the current second
  factor, so anyone with the password could enrol an authenticator of their own over the user's and finish signing in
  with it. An account whose MFA is set up now replaces its secret only from a session that is fully signed in (Profile
  → Reset MFA); a first setup is still offered right after the password, as before.
- **Second-factor codes could be guessed without limit, and reused.** Every code entered on the setup and verification
  pages now counts against the account: after 10 failures the second factor is locked for 15 minutes. A correct code
  clears the count, signing in again does not, and an administrator's Reset MFA clears the count and the lock. A code
  that has been accepted once - the setup code included - is refused afterwards.
- **The user routes returned MFA secrets, and accepted them.** The administrator's user list and user details, the
  API-key renewal, `/user/whoami` and the profile update all carried the account's TOTP secret (`mfa_secrets`) and
  `webauthn_credentials`; an administrator's user update could also write another user's MFA secret, and a profile
  update the caller's own, without the setup page's checks. Neither field is read or written through them any more.
- **The user routes returned the password hash.** The replies to an administrator's user update, deactivate and
  activate, and to a user's own profile update, carried the account's bcrypt hash as `user_password`. The field is now
  write-only: a password is still set through it, and the hash is never returned.
- All four are present in every earlier IRIS-NG release, 1.x included.
- **pypdf 7.0.1 → 7.1.1** fixes GHSA-5chg-c4f3-fw2p, GHSA-7f8r-xhw3-553h, GHSA-cqpq-3wwr-f5p2, GHSA-j9r2-rv26-5qv2 and
  GHSA-p3v2-r3fx-qpm6 (memory use, and an entry limit that was not applied, while reading crafted PDFs). Dependabot
  proposed 7.1.0, which still has all five. IRIS uses pypdf only to fill its own bundled FEMA ICS forms, so none of them
  was reachable; every form exports exactly as before.
- **cloudflared 2026.10.7 → 2026.11.0 in the guest-portal tunnel agent.** A request whose path carried `;` parameters
  could be matched to a tunnel rule other than the one Cloudflare Access protects. Only a named tunnel whose hostname
  enforces Access token validation in Zero Trust has such a rule; the quick tunnel's single rule behaves as before. It
  is built with Go 1.27.4 (security fixes to `net/http` among others), and 2026.10.2's distrust of the compromised
  eMudhra intermediates stays in. The agent starts, connects, serves the portal and restarts cloudflared after a crash
  as before.
- **The UI's lint tooling** (eslint 10.14.0 → 10.15.0) moves minimatch to 11.0.8 and brace-expansion to 5.0.13, which
  fix GHSA-cf2h-pxjq-68xw, GHSA-hqmv-qgp3-jx75, GHSA-c859-jr93-m5j4 and GHSA-6jwq-xf8q-xcwh. They run only when the UI
  is linted, on the repository's own patterns, and are in no image. The override that forced minimatch 11 since 2.9.4
  is removed: eslint now requires it itself.

### Changed
- **pyotp 2.10.0 → 2.12.1.** pyotp now refuses an MFA secret shorter than 112 bits, or one that is not valid Base32.
  IRIS has always generated 160-bit secrets; an account holding a shorter one can no longer pass the second factor, and
  its verification page now says that an administrator must reset its MFA (Settings → Access Control → Users → the user →
  Reset MFA) instead of reporting wrong codes. The user then sets up a new authenticator at the next sign-in.
- **email-validator 2.3.0 → 2.4.0** (the email check of the add-user, customer-contact and registration forms): an
  address whose domain mixes a right-to-left label with a label that starts with a digit (`user@1.xn--4dbc.com`) is now
  refused, as the IDNA rules require; every other address gets the same answer as before. Addresses already stored are
  not re-checked.
- **gunicorn 27.0.0 → 27.0.1**: a worker that is stopping keeps its kept-alive connections open for up to 2 seconds and
  answers a request that arrives on one with `Connection: close`, instead of dropping it.
- The MFA setup and verification pages show their messages (wrong code, lock, reset needed); before, no message
  reached the page.
- End-to-end harness: @playwright/test 1.65.1.

### Compatibility
- **API change:** the user routes (`/manage/users/...`, `/user/whoami`, `/user/update`) no longer return
  `mfa_secrets`, `webauthn_credentials` or `user_password`, nor the three new columns, and ignore the MFA fields when
  they are sent. A password is set through `user_password` as before; MFA is set up only through the setup page and
  cleared with Reset MFA.
- **MFA:** each code works once, so the verification right after a setup asks for the next code; a user who enters
  ten wrong codes waits 15 minutes or asks an administrator for Reset MFA; replacing an authenticator needs a signed-in
  session (Profile → Reset MFA). Accounts that do not sign in with MFA, and the exempt ones, are unaffected.

### Upgrading
- **Docker Compose with `docker-compose.dev.yml` or `scripts/update.sh`:** `bash scripts/update.sh --ref
  IRIS-NG-v2.16.0` - it takes the database dump before migration `b3f7d1a9c5e2` runs. From a release before 2.14.0,
  take the new script first, as the 2.14.0 notes describe. **With the guest portal enabled, `scripts/update.sh` rebuilds
  the tunnel agent** and so picks up cloudflared 2026.11.0; Settings → Guest Portal shows the version it reports. To
  rebuild the agent alone, from the clone: `docker compose -f docker-compose.dev.yml -f docker-compose.portal.yml build
  --pull tunnel`, then the same with `up -d tunnel`. A quick tunnel gets a new hostname whenever it restarts; a named
  tunnel keeps its own.
- **The image-based `docker-compose.yml`:** take a database dump, then `git checkout IRIS-NG-v2.16.0 && docker compose
  pull && docker compose up -d`.
- **Kubernetes:** chart 1.16.0; `helm upgrade` needs nothing else (the migration runs when the app starts).
- Migration `b3f7d1a9c5e2` chains from 2.13.0's `e4b9c2a7f5d1`; an install still on 2.12.x applies `e4b9c2a7f5d1` first,
  and one on 2.11.x 2.12.0's `b7e2c9f4a1d6` before that. A downgrade to an earlier release afterwards fails at boot
  (`Can't locate revision`) - restore the dump instead. An install on a release before 2.15.5 also takes 2.15.5's
  sign-in check before a request body is read and its 32 MB body limit, and one before 2.15.4 the earlier fixes listed
  in 2.15.5's notes.

## [IRIS-NG-v2.15.5] — 2026-11-19

A security fix release: a request is checked for sign-in before its body is read, request bodies have a size limit,
and a page opened with a case id shows that case only to a user who can open it. **No schema change** — the database
head stays at `e4b9c2a7f5d1`. Only the app image changes, in four source files (the version number is in one of
them); the nginx and database images, and the guest-portal tunnel agent, do not. The release build also resolved two
newer unpinned transitive packages: pydantic 2.14.3 → 2.14.4 and pydantic-core 2.50.4 → 2.50.5 (under `oic`'s
pydantic-settings, unchanged at 2.16.3); the released image imports them, boots, and passes the fix's checks.

### Security
- **A request that was not signed in could make the server read and parse its body.** The API routes checked the
  CSRF token before sign-in, and that check parses the body (a form or JSON) whenever a POST carries a session cookie
  of any value; the war-room routes did the same; and on most case routes the check that finds the case, which runs
  first, read a JSON body for its case id before anything looked at sign-in. A caller with no account and a made-up
  cookie could so make the server read and parse up to 100 MB per request (nginx's limit) - and bodies of any size on
  the template, case-file, datastore and working-timeline upload paths, where nginx sets no limit. All three now check
  sign-in first: a request that is not signed in gets `401 Authentication required` before its body is touched, and a
  war-room guest's CSRF token is checked once the guest is known.
- **The application set no limit on a request body.** A body larger than **32 MB** is now refused with a `413` whose
  message names the limit; `IRIS_MAX_REQUEST_MB` in `.env` changes it (nginx's own 100 MB limit still applies in front
  of it). The routes that take files or whole imports keep nginx's limits: templates, case files, asset-type icons,
  the datastore, war-room datastore and stream files, case and customer-asset imports, the working-timeline imports
  and the IOC, asset and timeline CSV imports.
- **A page opened with `?cid=<id>` showed that case's name and customer to any signed-in user.** Home and the other
  pages outside the case tabs made the case in their URL the session's current case without checking access to it:
  its name went into the page title and header, and its name and customer into the session cookie, which the browser
  can read. A user without access to the case now sees `Access denied to #<id>`, as on the case pages.
- The first and the last are present in every earlier IRIS-NG release, 1.x included; the war-room routes had the
  first since they were added.

### Compatibility
- A request that is not signed in gets `401` before anything else is checked. An anonymous POST carrying a session
  cookie used to get `400 Invalid CSRF token`, and an anonymous request to most legacy `/case/...` and `/datastore/...`
  routes `403 Permission denied`; both now get `401`. Signed-in requests and API keys are answered as before (a
  signed-in browser POST without its CSRF token still gets `400 Invalid CSRF token`).
- An API client sending more than 32 MB to an ordinary route - an alert with very large content, say - gets a `413`;
  raise `IRIS_MAX_REQUEST_MB` for it. The Helm chart does not set the variable, so the 32 MB default applies there.
- A user without access to a case who opens a page with that case's id sees `Access denied to #<id>` in the header
  instead of the case. Users with access, and an id that does not exist, are unchanged.

### Upgrading
- **Docker Compose with `docker-compose.dev.yml` or `scripts/update.sh`:** `bash scripts/update.sh --ref
  IRIS-NG-v2.15.5`. From a release before 2.14.0, take the new script first, as the 2.14.0 notes describe.
- **The image-based `docker-compose.yml`:** take a database dump, then `git checkout IRIS-NG-v2.15.5 && docker compose
  pull && docker compose up -d`.
- **Kubernetes:** chart 1.15.5; `helm upgrade` needs nothing else.
- No migration of its own; an install still on 2.12.x applies 2.13.0's `e4b9c2a7f5d1` at the first start, and one on
  2.11.x 2.12.0's `b7e2c9f4a1d6` before it, so take a database dump first (`scripts/update.sh` does). An install on a
  release before 2.15.4 also takes 2.15.4's link fixes, one before 2.15.3 2.15.3's cluster-narrative fix, one before
  2.15.2 2.15.2's case-route fix, and one before 2.15.1 the fix of case deletion, which deleted every IOC-asset link
  (see their notes).

## [IRIS-NG-v2.15.4] — 2026-11-16

A security fix release: links in the case pages' AI replies and in server-rendered Markdown keep their address only
when it is a safe one. **No schema change** — the database head stays at `e4b9c2a7f5d1`. Only the app image changes:
the fix's five files and the version number; the nginx and database images, and the guest-portal tunnel agent, do not.

### Security
- **A link in an AI reply could carry markup or run script.** The case pages' AI panels (the case summary panel, case
  chat and the timeline's per-event analysis) wrote a Markdown link's address into the link with only `&`, `<` and `>`
  escaped, and kept any scheme: a `"` in the address ended the attribute, so the rest of it became attributes of the
  link (an event handler such as `onmouseover` among them), and a `javascript:` or `data:` link was kept. The text
  is the model's reply, and the model reads the case's content (alerts and notes included), so text that reached a
  case could steer such a link into a reply. A link now keeps its address only for an `http` or `https` URL or a path
  on the same site (one leading `/`), escaped for the attribute; any other link shows as its text.
- **Server-rendered Markdown let a script link through when its scheme was spelled with HTML entities.** The renderer
  behind alert descriptions and notes in the Alerts queue, case descriptions, executive summaries and closing notes in
  the Overview queue and the case preview, war-room notes and the linked case notes a room shows, SitReps and their
  preview, decision rationales, Board notes, the room's operational summary, the note excerpts in the correlation
  workspace and the update banner's release notes refused only `javascript:`, `data:` and `vbscript:` links, judged on
  the text as typed - while the renderer decodes HTML entities when it writes the link. `&#106;avascript:` passed the
  check and reached the page as a working `javascript:` link, and a link with any other scheme (`file:` among them)
  was kept. The address is now decoded first, and only `http`, `https` and `mailto` links, or links with no scheme (a
  relative path, a query or a fragment), keep their link.
- Both are present in every IRIS-NG-v2 release and in 1.4.x.

### Compatibility
- In the AI panels, a link to anything other than an `http` / `https` URL or a same-site path - a `mailto:` address, a
  relative path without a leading `/`, a `//host` address - now shows as its text. A bare URL in an AI reply was never
  a link and is still not one.
- In server-rendered Markdown, a link with a scheme other than `http`, `https` or `mailto` (`ftp:`, `file:`, `tel:`,
  an application's own scheme) now shows as its text; links with no scheme are unchanged.

### Upgrading
- **Docker Compose with `docker-compose.dev.yml` or `scripts/update.sh`:** `bash scripts/update.sh --ref
  IRIS-NG-v2.15.4`. From a release before 2.14.0, take the new script first, as the 2.14.0 notes describe.
- **The image-based `docker-compose.yml`:** take a database dump, then `git checkout IRIS-NG-v2.15.4 && docker compose
  pull && docker compose up -d`.
- **Kubernetes:** chart 1.15.4; `helm upgrade` needs nothing else.
- No migration of its own; an install still on 2.12.x applies 2.13.0's `e4b9c2a7f5d1` at the first start, and one on
  2.11.x 2.12.0's `b7e2c9f4a1d6` before it, so take a database dump first (`scripts/update.sh` does). An install on a
  release before 2.15.3 also takes 2.15.3's cluster-narrative fix, one before 2.15.2 2.15.2's case-route fix, and one
  before 2.15.1 the fix of case deletion, which deleted every IOC-asset link (see their notes).

## [IRIS-NG-v2.15.3] — 2026-11-15

A security fix release: a cluster narrative in the correlation workspace is reachable only by a user who can open every
case of the cluster. **No schema change** — the database head stays at `e4b9c2a7f5d1`. Only the app image changes, in
one file; the nginx and database images, and the guest-portal tunnel agent, do not.

### Security
- **Any signed-in user could read, overwrite or revert the narrative of any correlation cluster.** `POST
  /api/v2/correlation/cluster-narrative` and `PUT` / `DELETE /api/v2/correlation/cluster-narrative/edit` took the
  cluster's id and case ids from the request body and checked neither, and a cluster id is derived from its case ids
  alone. A user with access to no case at all could read a cluster's stored narrative (the cached reply, the edit and
  revert replies, and the editor named by the manual-edit conflict), replace it with their own text or discard an
  analyst's correction - and the STIX export and the MISP push publish the newest narrative of a cluster. Every case a
  request lists must now be one the user can open (read-only access is enough, as for the correlation report itself),
  and the cluster id must be the one those exact cases give. Present in every earlier IRIS-NG release, 1.x included.

### Compatibility
- The correlation page's requests are answered as before. A request that lists a case the user cannot open, or a
  cluster id that does not match its case ids, gets a 404 with the message `Cluster not found among the cases you can
  access`, whether or not the cases or a narrative exist; a malformed body keeps its 400 reply.

### Upgrading
- **Docker Compose with `docker-compose.dev.yml` or `scripts/update.sh`:** `bash scripts/update.sh --ref
  IRIS-NG-v2.15.3`. From a release before 2.14.0, take the new script first, as the 2.14.0 notes describe.
- **The image-based `docker-compose.yml`:** take a database dump, then `git checkout IRIS-NG-v2.15.3 && docker compose
  pull && docker compose up -d`.
- **Kubernetes:** chart 1.15.3; `helm upgrade` needs nothing else.
- No migration of its own; an install still on 2.12.x applies 2.13.0's `e4b9c2a7f5d1` at the first start, and one on
  2.11.x 2.12.0's `b7e2c9f4a1d6` before it, so take a database dump first (`scripts/update.sh` does). An install on a
  release before 2.15.2 also takes 2.15.2's case-route fix, and one before 2.15.1 the fix of case deletion, which
  deleted every IOC-asset link (see their notes).

## [IRIS-NG-v2.15.2] — 2026-11-15

A security fix release: the case pages and the legacy case API no longer reach the IOCs, assets, tasks, evidence, notes
and timeline events of a case the user cannot open, and an update no longer moves an asset or a task into another case.
**No schema change** — the database head stays at `e4b9c2a7f5d1`. Only the app image changes; the nginx and database
images, and the guest-portal tunnel agent, do not.

### Security
- **A user with access to one case could reach the objects of other cases.** The legacy case routes check the user's
  access to the case named in `?cid=`, but then took the IOC, asset, task, evidence item, note or timeline event by its
  id alone. With their own case in `?cid=` and another case's object id in the path, a user could read another case's
  IOCs, assets and tasks (the view routes and dialogs) and the comments of all six kinds of object, comment on an IOC,
  asset or task, delete comments they had written on any of them, update an IOC, asset or task, change a task's status
  (`POST /case/tasks/status/update/<id>`) and delete a task (`POST /case/tasks/delete/<id>`). Each route now looks the
  object up in the `?cid=` case only, and another case's object answers as an unknown id does. The defect was inherited
  and is present in every earlier release.
- **An asset or task update could move it into another case.** `POST /case/assets/update/<id>`, `POST
  /case/tasks/update/<id>`, `PUT /api/v2/cases/<cid>/assets/<id>` and `PUT /api/v2/cases/<cid>/tasks/<id>` read
  `case_id` / `task_case_id` from the request body, so an update could move the asset or task into any case, one the
  user cannot open included. An update now keeps the object's own case, as an IOC update already did. Inherited, like
  the item above.
- **The GraphQL `iocUpdate` mutation** checked full access to the `?cid=` case only, then updated the IOC of any case.
  It now also requires full access to the IOC's own case, as `iocDelete` does.

### Compatibility
- A request that names an object of its own `?cid=` case is answered as before. One that names another case's object
  gets the reply an unknown id gets, and a `case_id` / `task_case_id` in an update's body is ignored. An API client that
  relied on either was reaching across cases.

### Upgrading
- **Docker Compose with `docker-compose.dev.yml` or `scripts/update.sh`:** `bash scripts/update.sh --ref
  IRIS-NG-v2.15.2`. From a release before 2.14.0, take the new script first, as the 2.14.0 notes describe.
- **The image-based `docker-compose.yml`:** take a database dump, then `git checkout IRIS-NG-v2.15.2 && docker compose
  pull && docker compose up -d`.
- **Kubernetes:** chart 1.15.2; `helm upgrade` needs nothing else.
- No migration of its own; an install still on 2.12.x applies 2.13.0's `e4b9c2a7f5d1` at the first start, and one on
  2.11.x 2.12.0's `b7e2c9f4a1d6` before it, so take a database dump first (`scripts/update.sh` does). An install on a
  release before 2.15.1 also takes 2.15.1's fix of case deletion, which deleted every IOC-asset link (see its notes).

## [IRIS-NG-v2.15.1] — 2026-11-14

A fix release: deleting a case no longer deletes the links between the IOCs and assets of every other case. **No schema
change** — the database head stays at `e4b9c2a7f5d1`. Only the app image changes, in one file; the nginx and database
images, and the guest-portal tunnel agent, do not.

### Fixed
- **Deleting a case deleted every IOC-asset link in the database.** When a case with at least one asset was deleted -
  from the web interface or through `DELETE /api/v2/cases/<id>` or the legacy `POST /manage/cases/delete/<id>` - the
  step meant to remove the links of that case's assets removed every link between an IOC and an asset, in every case:
  its filter compared each asset's id with itself, which is always true. The other cases kept their IOCs and assets,
  but each IOC lost its linked assets and each asset its linked IOCs. A deletion now removes only the links of the
  deleted case's own IOCs and assets, including their links to IOCs and assets of other cases. The defect was
  inherited and is present in every earlier release.

### Changed
- Dependabot no longer proposes Bootstrap 5 (Dependabot #189). Bootstrap 5 reads only `data-bs-*` attributes and needs
  Popper 2 and its own stylesheet, so the update would leave every dialog, toggle and dropdown without its behaviour
  while the build still passes; it moves with a migration of its own. 4.6.x updates still come through.

### Upgrading
- **Docker Compose with `docker-compose.dev.yml` or `scripts/update.sh`:** `bash scripts/update.sh --ref
  IRIS-NG-v2.15.1`. From a release before 2.14.0, take the new script first, as the 2.14.0 notes describe.
- **The image-based `docker-compose.yml`:** take a database dump, then `git checkout IRIS-NG-v2.15.1 && docker compose
  pull && docker compose up -d`.
- **Kubernetes:** chart 1.15.1; `helm upgrade` needs nothing else.
- **Links lost to an earlier case deletion are not restored by updating:** they were deleted from the database at the
  time. A database dump taken before that deletion still holds them (`scripts/update.sh` keeps its dumps in
  `backups/`).
- No migration of its own; an install still on 2.12.x applies 2.13.0's `e4b9c2a7f5d1` at the first start, and one on
  2.11.x 2.12.0's `b7e2c9f4a1d6` before it, so take a database dump first (`scripts/update.sh` does).

## [IRIS-NG-v2.15.0] — 2026-11-14

A dependency release: the database toolkit moves to the SQLAlchemy 2.1 series. Nothing changes for users or API
clients. **No schema change** — the database head stays at `e4b9c2a7f5d1`. Only the app image changes; the nginx and
database images, and the guest-portal tunnel agent, do not.

### Changed
- **SQLAlchemy 2.0.57 → 2.1.8**, the database toolkit under every page, API and background task. The parts of 2.1 that
  could affect IRIS were checked against its code: the database driver is named explicitly, so 2.1's new default
  PostgreSQL driver does not apply; and raw SQL now writes pending changes to the database first, which the places that
  take locks already allow for. A 1.4.1 database upgraded through every migration ends with the same schema and data as
  on SQLAlchemy 2.0, and the GraphQL API, the reports and every test suite answer as before. The pin takes the `asyncio`
  extra so that `greenlet`, which 2.1 no longer installs by default and the GraphQL layer needs, stays installed.
- Dependabot now proposes SQLAlchemy 2.1 updates; the hold on the 2.1 series is lifted.

### Upgrading
- **Docker Compose with `docker-compose.dev.yml` or `scripts/update.sh`:** `bash scripts/update.sh --ref
  IRIS-NG-v2.15.0`. From a release before 2.14.0, take the new script first, as the 2.14.0 notes describe.
- **The image-based `docker-compose.yml`:** take a database dump, then `git checkout IRIS-NG-v2.15.0 && docker compose
  pull && docker compose up -d`.
- **Kubernetes:** chart 1.15.0; `helm upgrade` needs nothing else.
- No migration of its own; an install still on 2.12.x applies 2.13.0's `e4b9c2a7f5d1` at the first start, and one on
  2.11.x 2.12.0's `b7e2c9f4a1d6` before it, so take a database dump first (`scripts/update.sh` does).

## [IRIS-NG-v2.14.2] — 2026-11-14

A fix release: AI jobs run on the AI worker only, and the image-based compose file runs one. **No schema change** —
the database head stays at `e4b9c2a7f5d1`. The app image changes only in its start script; the nginx and database
images, and the guest-portal tunnel agent, do not. The Helm chart changes the worker's queue setting.

### Fixed
- **AI jobs could run on the main background worker.** The main worker also took jobs from the AI queue, so about half
  of them - the executive case summary, case chat, SitRep and ICS drafts, the war-room summary, alert-cluster triage,
  the IOC deduplication pass and the task suggester - ran there instead of on the AI worker. A model call can take up
  to ten minutes, and there it held the worker slots that module hooks, imports, MISP sync and the mail poller need;
  AI jobs also did not run one at a time as the AI worker intends. The main worker now takes only the default queue.
  `IRIS_WORKER_QUEUES=celery,ai_queue` lets it take AI jobs as well, for an installation without an AI worker.
- **The image-based `docker-compose.yml` had no AI worker**, and its images defaulted to `iris-next/*:latest`, which
  names no published image. It now runs an `ai_worker` as `docker-compose.dev.yml` does, and each image defaults to
  this release on `ghcr.io/zach115th`, so the compose files and the images always match.

### Changed
- `.env.model` no longer sets the image names and tags (`NGINX_IMAGE_*`, `DB_IMAGE_*`, `APP_IMAGE_*`; they are
  commented examples), so a `.env` made from it follows the checkout instead of pinning images.
- Helm: with `irisaiworker.enabled: false` the main worker now takes the AI jobs too (the chart sets
  `IRIS_WORKER_QUEUES`); the values file's comment, which said they would never run, is corrected.

### Upgrading
- **Docker Compose with `docker-compose.dev.yml` or `scripts/update.sh`:** `bash scripts/update.sh --ref
  IRIS-NG-v2.14.2`. The AI worker was already running; only the main worker stops taking AI jobs. From a release before
  2.14.0, take the new script first, as the 2.14.0 notes describe.
- **The image-based `docker-compose.yml`:** remove the `NGINX_IMAGE_*`, `DB_IMAGE_*` and `APP_IMAGE_*` lines from your
  `.env` unless you mean to run other images - an old `.env` names `iris-next/*:latest`, and a tag pinned there stays
  behind when the checkout moves on - then `docker compose pull && docker compose up -d`.
- **A deployment of your own** that runs the worker without an AI worker: set `IRIS_WORKER_QUEUES=celery,ai_queue` on
  the worker, or AI jobs stay queued.
- **Kubernetes:** chart 1.14.2; `helm upgrade` needs nothing else.
- No migration of its own; an install still on 2.12.x applies 2.13.0's `e4b9c2a7f5d1` at the first start, and one on
  2.11.x 2.12.0's `b7e2c9f4a1d6` before it, so take a database dump first (`scripts/update.sh` does).

## [IRIS-NG-v2.14.1] — 2026-11-14

A maintenance release: the GraphQL endpoint and the report generator leave a pre-release and an old pin, the app server
moves to gunicorn 27, and the image build no longer patches installed packages. Nothing changes for API clients or in
the reports; gunicorn answers some malformed requests differently. **No schema change** —
the database head stays at `e4b9c2a7f5d1`. Only the app image changes; the nginx and database images, and the
guest-portal tunnel agent, do not.

### Changed
- **`/graphql` is served by IRIS's own view** instead of graphql-server 3.0.0b7, a pre-release. The final graphql-server
  3.0.0 rewrote that view and changed what clients see (an invalid query answered 200 instead of 400, request errors
  came back as plain text, and only JSON bodies were accepted), so IRIS now answers from a small view over graphql-core
  that keeps the existing behaviour: the same status codes and error bodies, the same accepted bodies (JSON,
  `application/graphql`, form posts), the query-string parameters and `?pretty`. Authentication and CSRF checks are
  unchanged. graphql-server is no longer installed.
- **graphene-sqlalchemy 3.0.0rc1 → 3.0.0rc2**, the newest release. rc2 would rename the input type of the `cases` date
  filter (`DefaultDateTimeScalarFilter`) and add comparison operators to it; IRIS keeps the existing type, so the GraphQL
  schema is unchanged.
- **docxcompose 1.1.2 → 2.2.0**, used when a report template embeds another document. The bundled report generator
  required exactly 1.1.2; that requirement is relaxed and 2.2.0 is installed, with Babel 2.18.0. Reports render the same:
  the bundled templates, a customised one and templates that embed documents with their own styles, numbering, tables,
  pictures and sections were compared part by part.
- **gunicorn 26.2.0 → 27.0.0** (Dependabot #188), the app server. It parses HTTP/1.1 more strictly, which changes two
  answers to malformed requests: a request line over 4094 bytes now answers `414 URI Too Long` instead of `400`, and a
  path with raw (not percent-encoded) non-ASCII bytes answers `400` instead of `404`. Browsers always percent-encode, and
  valid requests are answered as before. Where gunicorn receives requests without nginx in front (the Helm chart, behind
  an Ingress controller), it also refuses a `Transfer-Encoding` other than `chunked` with `400`, answers a request
  whose lines end in a bare LF at once instead of waiting for the timeout, and now answers a request sent on the same
  connection behind one whose body the application did not read.
- The image build no longer rewrites two installed packages: nothing in the image uses `pkg_resources` any more.
- The UI is built with vite 8.3.8 (Dependabot #187); the built files are identical.
- Dependabot proposes docxcompose updates again, and holds graphql-core below 3.3, which graphene 3.4.3 does not accept.

### Upgrading
- **Docker Compose:** `bash scripts/update.sh --ref IRIS-NG-v2.14.1`. From a release before 2.14.0, take the new script
  first (`git fetch origin && git show origin/main:scripts/update.sh > scripts/update.sh && bash scripts/update.sh --ref
  IRIS-NG-v2.14.1`) and update while the instance is idle: 2.14.0's move to RabbitMQ 4.4 replaces the broker.
- **Kubernetes:** chart 1.14.1 changes only the image version.
- No migration of its own; an install still on 2.12.x applies 2.13.0's `e4b9c2a7f5d1` at the first start, and one on
  2.11.x 2.12.0's `b7e2c9f4a1d6` before it, so take a database dump first (`scripts/update.sh` does).

## [IRIS-NG-v2.14.0] — 2026-11-13

A platform release: the message broker moves to RabbitMQ 4.4, the Kubernetes chart works with any Ingress controller,
and the update script protects queued work. **No schema change** — the database head stays at `e4b9c2a7f5d1`. The app
image changes (its Celery settings); the nginx and database images, and the guest-portal tunnel agent, do not.

### Changed
- **RabbitMQ 3.13 → 4.4** (`rabbitmq:4.4-management-alpine`, in the compose files and the Helm chart). RabbitMQ 3.13's
  community support ended in September 2024 and its image is no longer updated. RabbitMQ 4 refuses the kind of
  temporary queue each Celery worker declared for remote control and for events, so the app now declares them
  exclusive (`control_queue_exclusive`, `event_queue_exclusive` in its Celery settings). Without that the workers do not
  start on 4.4, and no module hook, import, AI job or mail poll would run.
- **`scripts/update.sh` protects queued tasks when the broker changes.** The broker keeps no data volume, so replacing
  it empties its queues, and until now an update that changed the broker's image replaced it straight away. The script
  now builds first, waits up to `IRIS_BROKER_DRAIN_TIMEOUT` seconds (default 120) for the task queues to empty, and
  says how many tasks would be lost if some remain: it asks, `--yes` continues, and answering no restores the checkout
  and stops before anything restarts. An update that changes neither the broker nor the database leaves both running,
  as before.
- **The Helm chart works with any Ingress controller** (ingress-nginx was retired in March 2026). The Ingress uses the
  path `/` (`pathType: Prefix`), sets no controller-specific annotations, and leaves `ingress.className` empty by
  default so the cluster's default IngressClass applies; `ingress.enabled: false` now removes it. The previous Ingress
  used an ingress-nginx regex path that other controllers read literally - on Traefik it served nothing. `Chart.yaml`
  declares Kubernetes 1.19 or later, and the chart's README is rewritten for Helm 4, maintained controllers and the
  settings that depend on the controller (upload size, long requests).
- CI: node24 versions of the artifact actions and ubuntu-24.04 runners; Dependabot also reads the compose files now.

### Fixed
- **`scripts/update.sh` could not take a newer copy of itself.** The documented first step (`git show
  origin/main:scripts/update.sh > scripts/update.sh`) leaves a change to a tracked file, which the script's own check
  refused - this never showed because the script had not changed until this release. It now ignores its own file, and
  it runs from a temporary copy so the checkout's reset cannot change the script while it runs.

### Upgrading
- **Docker Compose:** take the new script first, then update: `git fetch origin && git show
  origin/main:scripts/update.sh > scripts/update.sh && bash scripts/update.sh --ref IRIS-NG-v2.14.0`. The broker is
  replaced during this update, so background tasks still queued when it is (after up to two minutes of waiting) are
  lost: update while the instance is idle. The previous script replaces the broker too, without waiting.
- **This release's app image is required** by its compose files and chart: older images' workers cannot start on
  RabbitMQ 4.4. Do not pin an older `APP_IMAGE_TAG` or `irisapp.tag` with them. Going back to 2.13.3 also moves the
  broker back to 3.13 (its compose files name it).
- **Kubernetes:** set `ingress.className` to your controller's class, or leave it empty for the cluster's default, and
  put any controller-specific setting (the request-body limit, timeouts) in `ingress.annotations` - the chart no longer
  sets ingress-nginx's. `helm upgrade` replaces the broker pod; upgrade while no task is queued.
- No migration of its own; an install still on 2.12.x applies 2.13.0's `e4b9c2a7f5d1` at the first start, and one on
  2.11.x 2.12.0's `b7e2c9f4a1d6` before it, so take a database dump first (`scripts/update.sh` does).

## [IRIS-NG-v2.13.3] — 2026-11-13

A maintenance release: a login fix, and the removal of dependencies the application no longer uses or that no longer
worked. **No schema change** — the database head stays at `e4b9c2a7f5d1`. Only the app image changes; the nginx and
database images, and the guest-portal tunnel agent, do not change.

### Fixed
- **Passwords longer than 72 bytes could not be set, and a user with one could not log in** (since IRIS-NG-v2.0.0).
  The password-hashing library, bcrypt 5, refuses a password over 72 bytes where earlier versions used only its first
  72 bytes, and IRIS passed passwords to it unchanged. Creating or updating a user, or setting a war-room guest
  password, with a longer one failed with an error, and a user whose long password had been set earlier could no
  longer log in (the login page answered with a server error). IRIS now uses the first 72 bytes itself, which is what
  bcrypt always did before, so every stored password keeps working and nobody needs to reset one. A character outside
  plain ASCII takes more than one byte (an accented letter takes two).

### Removed
- **The EVTX import module** (`iris_evtx`, with the bundled `evtx2splunk`, its EVTX dump binaries and the Splunk HEC
  client). It could not run in any released image: a library it needs was never installed. Importing Hayabusa and
  EvtxECmd output into the working timeline is not affected.
- **The IntelOwl module** (`iris_intelowl_module`, with `pyintelowl` and the libraries only it used). See Upgrading.
- **What was left of installing an update from the web interface:** the update page, the "Update server" button and
  the code behind them. Nothing could reach them any more, and the restart step needed a component that is not
  installed. Updates go through `scripts/update.sh`; the update banner and the daily update check are unchanged.
- **Unused packages:** SQLAlchemy-ImageAttach, flask-cors, python-gnupg, Flask-Bcrypt and pyunpack, and the `7z`,
  `gpg` and `rsync` tools of the app image, which only the removed code used. pyunpack was called only by an unused
  helper; the bundled Seika module declared it without ever importing it, so its wheel now leaves that requirement
  out (nothing else in the wheel changes). With the two modules, 24 Python packages leave the image and two arrive
  (below), and 15.5 MB of binaries go.

### Changed
- **bcrypt** is now a direct requirement (5.0.0, the version already installed).
- **email-validator 2.3.0** (with dnspython 2.9.2) is installed: WTForms needs it to validate a form's e-mail field.
  The forms that declare one only draw the user and contact dialogs, whose data the API validates, so nothing failed
  in use.
- **Markdown rendering** (marked 18.1.3 → 18.2.0) follows the CommonMark / GFM rules in four more cases. A line that
  is not indented, after a code block or a heading inside a nested list item, now starts a paragraph after the list
  instead of joining the outer item - the one change an existing note can show. An image's alternative text keeps its
  line breaks; emphasis can open right after the other delimiter character (`*_text_`); and emphasis inside angle
  brackets that are not HTML is rendered (`<3 *note*>`).

### Upgrading
Update as usual (`scripts/update.sh --ref IRIS-NG-v2.13.3`, or the 2.13.3 images / chart 1.13.3). No migration of its
own; an install still on 2.12.x applies 2.13.0's `e4b9c2a7f5d1` at the first start, and one on 2.11.x 2.12.0's
`b7e2c9f4a1d6` before it, so take a database dump first (`scripts/update.sh` does).
- **If the IntelOwl module was enabled,** it is switched off at the first start (the log says so) and its
  configuration is kept; nothing in the image replaces it. A registered EVTX import module is switched off the same
  way; it never ran.
- **Going back to 2.13.2** is safe: every stored password works there too, except passwords over 72 bytes, which fail
  there as before.
- **The app image no longer contains `7z`, `gpg` or `rsync`.** This matters only if you ran them by hand inside the
  container.

## [IRIS-NG-v2.13.2] — 2026-11-12

A dependency release. **No schema change** — the database head stays at `e4b9c2a7f5d1`. Only the app image changes
(three Python packages, and of the built browser files only the Markdown renderer); the nginx and database images, and
the guest-portal tunnel agent, do not change.

### Security
- **pypdf 6.21.4 → 7.0.1** fixes GHSA-fhff-j4m8-439h, GHSA-rfv5-695j-j993, GHSA-59jv-x5x2-gg4c and GHSA-cmpx-464x-82c3
  (memory use while reading crafted PDFs) and GHSA-mwj3-fpmc-hjcv (low). IRIS uses pypdf only to fill its own bundled
  FEMA ICS forms, so none of these was reachable; the exported forms are unchanged.
- **The UI build tool Vite moves to 8.3.7** (GHSA-p4f5-76q4-ffq7, critical). Only a Vite development server exposed to
  the network was affected; IRIS images build the UI with `vite build` and never run a development server, so
  installations were not exposed. Running `npm run dev` in `ui/` was the only way to start one.

### Fixed
- **Notes with many unmatched `*`, `_` or `~` characters rendered slowly** (Markdown renderer marked 18.1.2 → 18.1.3).
  The unmatched markers were scanned quadratically: a note of a few thousand of them could keep the browser busy for
  several seconds while it rendered; it now takes milliseconds.

### Changed
- **Markdown rendering** (marked 18.1.3) follows the CommonMark / GFM rules more closely in a few corner cases: a
  `www.` link starts only at a word boundary (`xwww.example.org` is no longer a link), a setext heading underline or a
  task-list checkbox followed by a tab is recognised, an escaped `)` no longer closes a link, and a lazy line after a
  table in a quote or after an HTML block in a list item ends that block.
- **SQLAlchemy 2.0.55 → 2.0.57.** 2.0.56 fixes the parameters generated for an `IN` list taking the name of another
  parameter of the same query and silently replacing its value; no IRIS query is known to have been affected.
- **Flask-SocketIO 5.7.1 → 5.7.2** (only the routing of an event named `*` to a catch-all handler changes; IRIS has
  none).
- UI build tooling: Vite 8.3.7 (rolldown 1.2.19), eslint-plugin-svelte 3.24.1, postcss 8.5.32. End-to-end harness:
  dotenv 18.0.10, @playwright/test 1.65.0. The built UI files are byte-identical apart from the Markdown renderer.

### Removed
- **The unused Tailwind CSS / shadcn-svelte scaffolding in `ui/`** (Tailwind, autoprefixer, their configuration, an
  unused `App.svelte` and component folder). No shipped page used it: the built UI is byte-identical without it.
  Tailwind 4, which Dependabot proposed, would have stopped the UI from building.

### Held back
- **celery stays on 5.6.x.** celery 5.7 stores task results as JSON, and the module hooks, import pipelines and AI
  jobs return a status JSON cannot encode: DIM Tasks would show each of them as failed. Lifted once that status is
  JSON-safe.
- **pymisp stays on 2.5.x.** pymisp 3 needs python-dateutil 3, which graphene (behind `/graphql`) does not accept yet.

### Upgrading
Update as usual (`scripts/update.sh --ref IRIS-NG-v2.13.2`, or the 2.13.2 images / chart 1.13.2). No migration of its
own; an install still on 2.12.x applies 2.13.0's `e4b9c2a7f5d1` at the first start, and one on 2.11.x 2.12.0's
`b7e2c9f4a1d6` before it, so take a database dump first (`scripts/update.sh` does).

## [IRIS-NG-v2.13.1] — 2026-11-11

A security hardening fix for the tutorial panel. **No schema change** — the database head stays at `e4b9c2a7f5d1`.
Only the app image changes (one browser script); the nginx and database images, and the guest-portal tunnel agent,
do not change.

### Security
- **The tutorial panel no longer uses its saved progress as stored** (code scanning alerts #54 and #55,
  "Client-side cross-site scripting"). The panel keeps a copy of each completed step in the browser's session
  storage, so a step finished just before a page change is not lost, and a step can pick up a value from the page
  address; the copy's step number was written into the panel's markup (the "Title · 3/9" label and the progress
  bar). The step had to be a number, so nothing could be injected. The copy is now rebuilt before it is used: the
  step is read as a whole number, and each saved value must follow the rules of a captured value (text up to 200
  characters, or a number). The step counts are also escaped wherever the panel draws them.

### Fixed
- A saved step that was a number but not a whole one stopped the tutorial panel from drawing on the next page; it is
  ignored now, like a step of another tutorial.

### Upgrading
Update as usual (`scripts/update.sh --ref IRIS-NG-v2.13.1`, or the 2.13.1 images / chart 1.13.1). No migration of its
own; an install still on 2.12.x applies 2.13.0's `e4b9c2a7f5d1` at the first start, and one on 2.11.x 2.12.0's
`b7e2c9f4a1d6` before it, so take a database dump first (`scripts/update.sh` does).

## [IRIS-NG-v2.13.0] — 2026-11-11

Tutorials: step-by-step walkthroughs that run on the real pages, five built in and as many as your team writes.
**One schema migration** (`e4b9c2a7f5d1`), additive: two new tables — take a database dump before upgrading
(migrations are one-way; `scripts/update.sh` does the dump). Only the app image changes (application code, page
templates, scripts and styles; no requirement changes); the nginx and database images, and the guest-portal tunnel
agent, do not.

### Added
- **Tutorials**, under the user menu. A panel at the bottom right says what to do, outlines where on the page, offers
  **Fill** buttons for the values to type and a **Take me there** link to the right page, and moves on by itself once
  the step is done. The tutorial follows you from page to page; it can be minimized, or stopped and later picked up
  where it was with **Continue**. Completed tutorials stay marked, and **Start again** runs one from the beginning.
  Guests of the guest portal never see tutorials.
- **Five built-in tutorials**: *Run your first investigation* (a case, several IOCs at once, a raw log date on the
  timeline, a task for a colleague), *Triage alerts from the keyboard*, *Hand over: report and close a case*, *Track a
  vulnerability across a crisis* (the catalogue, a finding on an asset, a war room and its Scope), and *Write a
  tutorial for your team* (administrators). Those that create data use the IrisInitialClient test customer, and their
  last step offers to delete what they created: the case, the war room and, for an administrator, the catalogue
  entry - only what you created during that tutorial, and only with the right to delete it you already have.
- **Settings → Tutorials** (server administrators; no new permission). Edit a built-in tutorial: your version replaces
  it for everyone, unpublishing it hides it, and **Restore** brings back the version shipped with IRIS. Write your
  own: steps with what to do, what to outline, the values to fill in, and when the step is done (the learner clicks
  Next, something appears on the page, a page opens, or IRIS saves something - a value of its reply, such as the id of
  the case just opened, can be used by the later steps). **Who sees it**: everyone, or administrators only. **Try it**
  runs what the editor holds without counting as completed. **Export** and **Import** move a tutorial between IRIS-NG
  servers as a file (format `iris-ng-tutorial/1`; an import arrives as a draft).
- The controls the built-in tutorials point at carry a `data-tour` name a team's tutorials can use too: `case-new`,
  `case-form`, `case-create`, `case-quick-add`, `case-menu`, `case-state`, `case-report`, `case-edit`,
  `case-request-review`, the case tabs `case-tab-summary` … `case-tab-evidence`, `event-date-parse`.
- REST: `/api/v2/tutorials…` (the list, start, continue and the running tutorial's progress) and
  `/api/v2/manage/tutorials…` (server administrators: the tutorials, save, delete or restore, try, import, export).

### Fixed
- Alerts: switching to the Split view after an alert had been opened in the List view hid the queue, leaving only
  the alert; Split shows both again.

## [IRIS-NG-v2.12.1] — 2026-11-10

Vulnerability tags entered like every other tag field, and dashboards that leave out the test customer. **No schema
migration.** Only the app image changes (application code and one page script; no requirement changes); the nginx and
database images, and the guest-portal tunnel agent, do not.

### Changed
- **Vulnerability tags.** The Tags field of the vulnerability form is now the tag widget the other tag fields use:
  Enter adds a tag, typing suggests the tags already used on this server and those of the bundled MISP catalog, and a
  tag still being typed when the form is saved is kept. When a vulnerability is saved, its tags join the server's tag
  list, so they are suggested on every tag field. Through the API (`POST` / `PUT /api/v2/manage/vulnerabilities…`), a
  tag may now be up to 512 characters (it was 64) and a `|` belongs to the tag instead of separating two; commas and
  line breaks still separate tags, and at most 30 are kept.

### Fixed
- Dashboards - the built-in Statistics and every dashboard someone builds - counted the cases of IrisInitialClient,
  the bootstrap customer kept for testing, what those cases hold and its alerts, and offered it in the Customer filter
  and the editor's customer and case lists. They now leave it out entirely, as the Metrics page always has.

## [IRIS-NG-v2.12.0] — 2026-11-10

War-room categories, archive and datastore, a Vulnerabilities layer on the case graph, and three code-scanning
findings closed. **One schema migration** (`b7e2c9f4a1d6`), additive: three new tables and three new columns on
`war_room` — take a database dump before upgrading (migrations are one-way; `scripts/update.sh` does the dump). Only
the app image changes (application code, page templates and scripts; no requirement changes); the nginx and database
images, and the guest-portal tunnel agent, do not.

### Added
- **War-room categories.** One shared list in a sidebar of the War Rooms page: All, Uncategorised and each category
  with its count, the choice remembered per browser. Anyone adds or renames a category; deleting one is for its
  creator or a server administrator, and only takes its rooms out of it. A room's leads file it by dragging its card
  onto a category, through the card's Move menu, or when they create it.
- **Archiving a war room.** A lead (or a server administrator) archives a room from its card or its header. An
  archived room keeps its state and everything in it, and still works; it waits in the Archived section at the bottom
  of the War Rooms page, with a banner in the room, until it is restored. Archived is neither closed nor deleted.
- **A datastore for each war room**, opened from the room header: folders, and files with a description and tags.
  Observers browse and download; responders, leads and portal guests upload (100 MB a file, 20 at once, or drop files
  on the list), rename, replace and move; deleting is for whoever created the file or folder, or a lead, and deleting
  a folder moves what it held up one level. A closed room's datastore is read-only. Stream attachments lists the files
  posted in the Stream. Any file can be copied as a Markdown link, or copied into the datastore of a case attached to
  the room (folder "War rooms"; full access to that case is needed, and guests cannot).
- **A Vulnerabilities layer on the case graph.** Every catalogue entry with an open finding (under analysis, affected
  or mitigated) on a case asset is an ellipse coloured by its severity, linked to each asset it affects. An affected
  asset that is on no timeline event joins the map while the layer is on.
- REST: `/api/v2/war-rooms/categories`, `/api/v2/war-rooms/<id>/archive` (POST archives, DELETE restores),
  `/api/v2/war-rooms/<id>/category` and `/api/v2/war-rooms/<id>/datastore/…`.

### Changed
- A war room's `archived_at` now reports when it was archived; the time it was closed is `closed_at` (until now
  `archived_at` carried the close time). The room list also returns `archived`, `category_id` and `can_manage`, and
  takes `?archived=0` or `?archived=1`.

### Fixed
- `GET /api/v2/case-queue` answered 500 when `per_page` or `page` carried one of the control characters
  U+001C–U+001F around the number, and a dashboard's `f_<key>=` filter failed the same way; they now read the number.
  The same change closes code scanning alerts #51–#53 (number patterns that opened with `\s*`).

## [IRIS-NG-v2.11.0] — 2026-11-09

A new Alerts page, a case queue on Overview, dashboards you build yourself, and the old Dashboard page retired.
**Two schema migrations** (`b2d7f4a9c1e6` → `d4c8e1f7a3b9`), both additive: one index and one new table — take a
database dump before upgrading (migrations are one-way; `scripts/update.sh` does the dump). Only the app image
changes (application code, page templates, scripts and stylesheets; no requirement changes); the nginx and database
images, and the guest-portal tunnel agent, do not.

### Added
- **Alerts is now a triage queue.** Three views, remembered per browser: Split (the queue beside the selected alert),
  List (one line per alert) and Board (open alerts in columns, unassigned by severity or assigned by status; drag a
  card to change it, or Take it). The page opens on the open queue; quick tabs My queue, Unassigned, Escalated and
  All open carry their counts, and the address reproduces the view.
- **A search language for alerts**, read on the server: `field:value`, `*` and `?` wildcards, `>=` `<=` `>` `<` on
  severity and dates, ranges `[a TO b]`, `AND` / `OR` / `NOT` / `-` and brackets, or plain words over the title,
  description, source, source reference and tags. Conditions appear as chips, suggestions come from your own
  statuses, customers and users, and a mistake is reported at its position instead of returning an empty list.
- Alerts in a cluster collapse into one expandable row. The detail pane has Overview, Investigation, Assets, Cluster,
  IOCs, Raw event, Timeline, Notes, Comments and Graph tabs. Also: batch actions, keyboard triage (`j` `k` `e` `m` `x`
  `/` Enter Esc) and a New alert form for anything that did not come in through a feed.
- **Overview is now a case queue**, filtered, sorted and paged on the server: search, Show closed, four quick-filter
  chips, a filter builder with saved filters, a seven-step stage bar and an idle time per case, and a side panel with
  the stage track, the details, task counts and the executive summary. Cases with no owner now appear.
- **Dashboards you build yourself** (`/dashboards`). Sections of widgets over cases, alerts, IOCs, assets, tasks,
  timeline events, evidence, notes and time entries: counts, sums, averages, medians, percentages and lists, as
  numbers, donuts, pies, bars, lines and tables, with a filter bar and a date range. A shared dashboard is read-only
  to everyone but its owner and server administrators, and shows each viewer only what they can open. A built-in
  Statistics dashboard is included, and Metrics is unchanged.
- **Global tasks on Home**, beside My pending tasks: add, edit and delete, with a status menu on each row and finished
  tasks hidden until you show them. My pending tasks gets the same status menu.
- REST: `/api/v2/alert-queue` (read-only), `/api/v2/case-queue` and `/api/v2/custom-dashboards`.

### Changed
- The sidebar's Dashboard entry opens the new Dashboards page and keeps its icon.
- The logo and the site root now go to Home. Sign-in already did.

### Removed
- **The old Dashboard page.** Its address forwards to Home, so links and bookmarks keep working. What it showed is on
  Home (your cases, tasks and reviews), Overview (Import, New case) and Metrics (case counts, opened vs closed). The
  Global tasks table's Export and Copy buttons and its right-click module actions did not move with it.

### Fixed
- Global tasks could not be added or edited: their dialog had been left on the Inventory page since 2.0.0.
- Changing only a case's state wiped its reviewer and reset its review status (the state menu in the case header, and
  any API client sending just `state_id`).
- Saving a filter always failed with "user: Missing data".
- `GET /overview/filter` returned a 500 when a visible case had no open date.
- Cancelling a batch delete of alerts left a permanent "being deleted" overlay.
- Times in Home's Case activities were read as local time instead of UTC.

### Upgrading
Update as usual (`scripts/update.sh --ref IRIS-NG-v2.11.0`, or the 2.11.0 images / chart 1.11.0). Two migrations run
at the first start, ending at `d4c8e1f7a3b9`. No permission bit is added. Scripts that read the old page's HTML at
`/dashboard` now get a redirect to Home; the API routes it used are unchanged.

## [IRIS-NG-v2.10.1] — 2026-11-08

A security hardening fix for the war-room Stream. **No schema change** — the database head stays at
`f3b8d6a1c9e4`. Only the app image changes (one browser script); the nginx and database images, and
the guest-portal tunnel agent, do not change.

### Security
- **The Stream's attachment chips no longer reuse a value read from the page** (code scanning alert
  #50, "DOM text reinterpreted as HTML"). When a file was attached or removed, the composer it
  belonged to - named by the page's own `data-where` attribute - was written back into the chips'
  markup. The page only ever writes "main" or "thread" there, and any other value stopped the code
  before it drew anything, so nothing could be injected; the value is now re-derived, so only
  "thread" or "main" ever reaches the markup. An unexpected value attaches to, or removes from, the
  main composer instead of failing. Attachments look and behave as before.

### Upgrading
Update as usual (`scripts/update.sh --ref IRIS-NG-v2.10.1`, or the 2.10.1 images / chart 1.10.1). No
migration of its own; an install still on 2.9.x applies 2.10.0's five migrations at the first start
(ending at `f3b8d6a1c9e4`), and one on 2.8.x 2.9.0's `e7a3f9c2d6b1` before them, so take a database
dump first (`scripts/update.sh` does).

## [IRIS-NG-v2.10.0] — 2026-11-08

Vulnerability management, asset flags and war-room decisions, and war rooms rebuilt around a Board, a
three-column Stream and a Scope workspace. **Five schema migrations** (`58207f87c9e2` → `b6d1e4f8a2c7` →
`c5e9a2f7d4b8` → `e1d7b4a9c3f6` → `f3b8d6a1c9e4`), all additive: new tables, two new columns and a backfill of
each war room's activity history — take a database dump before upgrading (migrations are one-way;
`scripts/update.sh` does the dump). Only the app image changes (application code, page templates, scripts,
stylesheets, and one new Python requirement, `cvss==3.6`); the nginx and database images, and the guest-portal
tunnel agent, do not.

### Added
- **Intel → Vulnerabilities**, a vulnerability catalogue: public entries (CVE, GHSA, vendor advisories) and
  private ones numbered `IRIS-VULN-<year>-<NNNN>`, with CVSS 2.0 / 3.x / 4.0 vectors scored automatically (the
  severity follows the score unless set by hand), EPSS, CISA KEV, exploit maturity, patch availability, CWEs,
  affected products, references, aliases, TLP and tags. A CVE can be filled from cve.org and synced later (only
  the CVE id leaves the instance, through the configured proxy; Settings → System turns the lookups off).
  Administrators merge duplicates and delete entries.
- **Vulnerability findings** on case assets and on customer-registry assets: CISA VEX remediation status,
  exploitation status, due date, owner, detection, versions, verification, linked events and IOCs, a change
  history, and an optional approved war-room decision cited as the reason. On the case Assets page each asset has
  a Vulnerabilities tab and the list a shield coloured by its most severe open finding; the catalogue's Case
  filter lists one case's vulnerabilities across its assets. IOCs of type vulnerability link to their entry.
- **Asset flags**: status facts on case assets (isolated, credentials reset, restored…) from a list an
  administrator manages in Settings → Asset flags — each a status, a "done" or an exception, optionally requiring
  a written reason or an approved war-room decision. The Assets page shows them as chips, filters on them and
  keeps their history.
- **War-room Decisions**: a register numbered D-1, D-2… per room, with a rationale, an owner, a target date,
  optional approvers who vote, what it applies to (the room, cases, assets), and its trail; implemented, reopened
  and superseded states; status chips with counts; promotion of `/decision` chat messages; a new notification
  when a decision awaits your approval. A decision already taken can be recorded as approved.
- **War-room Board**, the tab a room opens on: a row of indicator tiles (compromised assets, open decisions,
  exceptions, open tasks, flags, open / exploited / overdue / KEV vulnerabilities), case cards, open decisions,
  open tasks, notes, and Needs attention — only what nobody has acted on yet. Every tile opens the matching tab,
  filtered. A lead lays the board out for everyone; anyone can customise their own view.
- **War-room Stream in three columns**: Conversation (topics, threads, decisions and pins, slash commands), the
  chat, and an Activity panel with lanes, filters, folded bursts and per-case / per-kind mutes, routed per person
  (Activity settings, saved to the profile). Messages can be edited, deleted and reacted to; replies live in
  threads that notify their followers (new notification event); topics can be archived; files and pictures can be
  attached (25 MB each); an emoji picker. Every change in a room — members, guests, teams, notes, tasks,
  timelines, SitReps, attached cases, tracked vulnerabilities — now writes an activity line with who made it, and
  existing rooms get their history back-filled.
- **War-room Scope**, a workspace over the attached cases you can open, in sub-tabs: **Assets** (type, IP,
  customer, compromise and analysis status, flags, IOCs, open findings, last update; grouped by case or
  vulnerability; a flag board where a card dropped on a flag sets it; select assets to set or remove flags, set a
  status, record a vulnerability or push them into other cases; copy a group as a table or CSV), **IOCs** (one row
  per indicator, one column per case, pushed into the cases missing it), **Customers** (the scope summed per
  customer), **Vulnerabilities** (moved here from its own room tab) and **Staging** (assets and IOCs kept in the
  room with the cases they are meant for, pushed later). **Add asset / Add IOC** create one object in several
  cases at once (or stage it), **Export** writes the IOCs as a blocklist, CSV or STIX 2.1, and **Attach from
  Assets Manager** puts customer-registry assets in the room's scope. A copy that would mix customers' data asks
  for confirmation first, naming the customers.

### Changed
- War rooms open on their Board; the tabs run Board, Stream, Scope, Decisions, Summary, Timelines, Tasks, Notes,
  SitReps, Cases, Members, Teams, Correlation. Notifications link to the tab they are about (`?pane=`); the old
  `?pane=vulnerabilities` opens the Scope's Vulnerabilities sub-tab.
- Every change made from a war room's Scope goes through the case's own paths (history, case activity, module
  hooks) and needs full access to that case; observers, guests and closed rooms change nothing, and guests never
  get the Scope or the vulnerability views.
- About 50 new help entries (470 in all).

### Upgrading
Update as usual (`scripts/update.sh --ref IRIS-NG-v2.10.0`, or the 2.10.0 images / chart 1.10.0). Five
migrations run at the first start, ending at `f3b8d6a1c9e4`; the activity back-fill reads each room's existing
rows once. No permission bit is added: the vulnerability catalogue is open to every user (merge and delete need
server administrator), and everything case-bound follows case access.

## [IRIS-NG-v2.9.4] — 2026-11-05

A maintenance release for the tools that build the browser bundle. **No schema change** — the
database head stays at `e7a3f9c2d6b1`. The app image is 2.9.3's apart from the version it reports:
the release build resolved the same Python packages, and the application code and the browser
bundle are identical. The nginx and database images and the guest-portal tunnel agent do not
change.

### Security
- **minimatch 10.2.6 → 11.0.4 in the build tools, pinned through `ui/package.json`'s `overrides`
  (Dependabot alert #174).** Closes GHSA-g3hv-75wg-m249: with `optimizationLevel` 2, a crafted
  glob pattern made minimatch generate an exponential number of pattern variants and then compare
  every pair. minimatch is used only by the linter (eslint), which never sets that option and only
  reads the repository's own patterns, and the image build does not run the linter; nothing of it
  ships in an image. The fix exists only in minimatch 11, which eslint does not declare yet, hence
  the override: eslint lints the same files with the same findings, and the browser bundle is
  byte-identical.

### Upgrading
Update as usual (`scripts/update.sh --ref IRIS-NG-v2.9.4`, or the 2.9.4 images / chart 1.9.4). No
migration runs; an install still on 2.8.x applies 2.9.0's single migration (`e7a3f9c2d6b1`) at the
first start, so take a database dump first (`scripts/update.sh` does). An install already on 2.9.3
gains nothing it would notice.

## [IRIS-NG-v2.9.3] — 2026-11-05

A maintenance release for the end-to-end test harness. **No schema change** — the database head
stays at `e7a3f9c2d6b1`. The app image is 2.9.2's apart from the version it reports: a fresh build
resolves the same Python packages, and the application code and the browser bundle are identical.
The nginx and database images and the guest-portal tunnel agent (cloudflared 2026.10.7) do not
change.

### Security
- **follow-redirects 1.16.1 → 1.16.2 in the end-to-end test harness (Dependabot #172).** Closes
  GHSA-mrwp-f3q8-3g9p: a `sensitiveHeaders` list created in another JavaScript realm (a `vm`
  context) was discarded, so the custom credential headers it named were kept on a redirect to
  another host. It reproduces on 1.16.1 and not on 1.16.2. The package belongs to the test
  harness's readiness poll only, which sets no such list (and axios, which the poll goes through,
  copies one into a new array anyway); nothing of it ships in an image.

### Upgrading
Update as usual (`scripts/update.sh --ref IRIS-NG-v2.9.3`, or the 2.9.3 images / chart 1.9.3). No
migration runs; an install still on 2.8.x applies 2.9.0's single migration (`e7a3f9c2d6b1`) at the
first start, so take a database dump first (`scripts/update.sh` does). An install already on 2.9.2
gains nothing but the new version number.

## [IRIS-NG-v2.9.2] — 2026-11-05

A dependency release. **No schema change** — the database head stays at `e7a3f9c2d6b1`. The app
image changes in Python packages only (the application code and the browser bundle are identical
to 2.9.1), and the guest-portal tunnel agent gets a newer cloudflared; the nginx and database
images do not change.

### Changed
- **pypdf 6.21.2 → 6.21.4 (Dependabot #167, also part of #170)**, which fills the bundled FEMA
  forms for the war-room ICS PDF export. Fixes seven denial-of-service advisories on crafted PDF
  files (GHSA-42gh-23hr-vphw, GHSA-4vqv-7265-gm2w, GHSA-62m5-6wh8-28x7, GHSA-x3rh-gjgm-fmqc,
  GHSA-5849-834g-hvw5, GHSA-cggf-277g-3q54, GHSA-mfr5-77xh-9j7h). None is reachable: IRIS-NG only
  opens its own bundled forms, and all seven export identically on both versions.
- **cloudflared 2026.10.4 → 2026.10.7 in the guest-portal tunnel agent (Dependabot #168).** Fixes
  a regression in the maximum number of concurrent HTTP/2 streams in the builds made with Go 1.27
  (a tunnel falls back to HTTP/2 where QUIC is blocked) and updates two of its own dependencies
  (go-chi 5.5.0, go-jose 4.1.6). The agent starts, connects, serves the portal and restarts
  cloudflared after a crash as before. It is still built with Go 1.27.3, so 2026.10.2's distrust
  of the compromised eMudhra intermediates stays in.
- **azure-keyvault-secrets 4.11.3 → 4.12.0, WTForms 3.3.1 → 3.3.2, Flask-SocketIO 5.7.0 → 5.7.1
  (Dependabot #170).** Azure Key Vault, used only when `AZURE_KEY_VAULT_NAME` is set: hardened
  handling of cached authentication challenges, a backslash in the vault URL's host is refused,
  and the default service API version is now 2026-04-01. WTForms: a numbering fix for nested
  `FieldList`s, which IRIS-NG's forms do not use; every form renders and validates identically.
  Flask-SocketIO now requires python-socketio 5.18 or newer (below).
- **Unpinned packages in the rebuilt image:** python-socketio 5.17.0 → 5.18.1, which refuses an
  event that arrives while a Socket.IO connect handler is still running instead of dispatching it
  (IRIS-NG has no connect handler that authenticates); kombu 5.6.2 → 5.7.0, which no longer
  installs `tzdata` (time zones still resolve, from the image's system database); amqp 5.4.2,
  billiard 4.3.2, Deprecated 3.0.1, pydantic 2.14.3, pydantic-core 2.50.4 and typing-inspection
  0.4.5. Checked on the rebuilt image: every module imports, app and both workers start cleanly,
  and GraphQL, a `.docx` report, case create and delete, the ICS PDF export and every test suite
  give the same results as before.
- Build-time only: eslint 10.13.0 → 10.14.0 and globals 17.13.0 → 17.14.0 (Dependabot #169); the
  built browser bundle is byte-identical.

### Upgrading
Update as usual (`scripts/update.sh --ref IRIS-NG-v2.9.2`, or the 2.9.2 images / chart 1.9.2). No
migration runs; an install still on 2.8.x applies 2.9.0's single migration (`e7a3f9c2d6b1`) at the
first start, so take a database dump first (`scripts/update.sh` does). **With the guest portal
enabled, `scripts/update.sh` rebuilds the tunnel agent** and so picks up cloudflared 2026.10.7;
Settings → Guest Portal shows the version it reports. To rebuild the agent alone, from the clone:
`docker compose -f docker-compose.dev.yml -f docker-compose.portal.yml build --pull tunnel`, then
the same with `up -d tunnel`. A quick tunnel gets a new hostname whenever it restarts; a named
tunnel keeps its own.

## [IRIS-NG-v2.9.1] — 2026-10-30

A security hardening fix for the help icons. **No schema change** — the database head stays at
`e7a3f9c2d6b1`. Only the app image changes (one application module and one script); the nginx and
database images, and the guest-portal tunnel agent, do not change.

### Security
- **A help tip's links are built only from the glossary itself** (code scanning alert #49, "DOM
  text reinterpreted as HTML"). The "All terms" link in a pinned tip was assembled from the
  icon's own page attribute. That attribute could only ever name an existing glossary term and
  sat after the `#` of the link, so it could not change where the link went, but the link now
  takes the term's key from the glossary data, URL-encoded, and a tip writes a link only for an
  `http(s)` address or a path on this server — anything else, such as a `javascript:` address,
  gives no link at all. Tips look and behave as before.

### Upgrading
Update as usual (`scripts/update.sh --ref IRIS-NG-v2.9.1`, or the 2.9.1 images / chart 1.9.1). No
migration runs; an install still on 2.8.x applies 2.9.0's single migration (`e7a3f9c2d6b1`) at the
first start, so take a database dump first (`scripts/update.sh` does).

## [IRIS-NG-v2.9.0] — 2026-10-30

Help icons across the interface, and four fixes. **One schema migration (`e7a3f9c2d6b1`)**, a
single nullable column on `user` — take a database dump before upgrading (migrations are one-way;
`scripts/update.sh` does the dump). Only the app image changes (application code, page templates,
scripts and stylesheets); the nginx and database images, and the guest-portal tunnel agent, do not.

### Added
- **(i) help icons.** Every page with a navigation bar, Manage included, carries an (i) beside the
  fields, columns, settings and sections that need explaining — about 420 definitions. Hover to
  read one; click it (or press Enter) to keep it open and use its links; Esc or a click elsewhere
  closes it. Where a field takes its value from a list (severity, case state, classification, IOC,
  asset and evidence type, task and alert status, resolution), the tip also shows what the chosen
  value means on this server: the descriptions administrators edit under Manage.
- **A Glossary page** (`/help/glossary`, in the user menu and behind "All terms" in every tip)
  lists every definition on one searchable page, with this server's values. "Learn more" in a tip
  opens the matching wiki section.
- **My settings → "Show help icons"** hides the icons for you; the Glossary stays.
- **War-room guests** see, on the guest portal, the definitions of what they can use in the room.

### Fixed
- **Selecting several alerts reassigned their owners.** Setting a status, closing with a note or
  assigning on several alerts at once made you the owner of every alert after the first unowned
  one — alerts someone else owned included — and "Assign to <someone>" gave the unowned alerts to
  you instead. Owned alerts now keep their owner, unowned ones become yours only when no owner is
  chosen, and Assign gives every selected alert to the person picked.
- **A timeline CSV moved events entered with an offset.** "Download as CSV" wrote each event's UTC
  time next to the offset it was typed in, and the import reads the time in that offset, so
  importing a downloaded file (into another case, say) moved those events by their offset: an
  event typed 00:02 at −07:00 came back at 14:02 UTC, and anyone reading the file got the wrong
  time too. The file now holds each time as it was entered, next to its offset, and both imports
  (master and working timeline) read it the same way. Files downloaded before this release still
  carry the old pairing.
- **"File is IOC" in the datastore never reached the case.** The file's SHA-256 was created as an
  IOC that belonged to no case (and only when the hash existed nowhere on the server), so it never
  appeared on the IOC tab. It is now added to the case's IOCs (type sha256, TLP:AMBER, tag
  `datastore`) unless the case already holds it.
- **Editing a seeded value's description duplicated it.** At start-up IRIS-NG re-creates missing
  seeded lookup values, and it compared the description as well as the name, so an evidence type,
  IOC type, case state or classification whose description an administrator had edited was added
  a second time at the next restart. Seeded values are now matched by name. Duplicates created
  before this release are left in place.
- **The HTTPS proxy setting was overwritten with the HTTP proxy** each time Settings was saved: the
  field showed the HTTP proxy's value.
- **Interface text that contradicted the software**: the IOC CSV format hint (tags come before
  TLP), the evidence form's note that the file never leaves the browser (the evidence-type
  suggestion sends its first 4 KB to the AI backend), the inventory wipe and overdue notes, the
  summary-verification note in Settings, and several war-room, mail-rule and timeline-filter
  descriptions.

### Changed
- The seeded severity, alert-status and task-status descriptions that only repeated the value's
  name (or were empty) now describe the value. A description an administrator has changed is kept.

### Upgrading
Update as usual (`scripts/update.sh --ref IRIS-NG-v2.9.0`, or the 2.9.0 images / chart 1.9.0). One
migration runs at the first start (`e7a3f9c2d6b1`, the nullable `user.has_help_tips` column); every
existing user sees the icons until they turn them off.

## [IRIS-NG-v2.8.10] — 2026-10-30

Page-load and accessibility fixes. **No schema change** — the database head stays at
`c4d9a2e7f1b3`. Only the app image changes (page templates, application code and one stylesheet);
the nginx and database images, and the guest-portal tunnel agent, do not change.

### Fixed
- **The case Summary page jumped while it loaded.** The Executive Case Summary panel first showed
  "No AI summary yet" and replaced it with the cached summary a moment later, which pushed the case
  summary card off the screen whenever the two cards sit one above the other. The page now arrives
  with the cached summary already drawn. "No AI summary yet" appears only when there is no summary;
  if the summary cannot be read, the panel says it is loading and fetches it as before. Generate,
  Refresh and the Review / Audit tabs are unchanged.
- **Every page moved down when a strip appeared.** The "a newer release is available" strip and the
  Settings → Banners announcements were added to the top of the page after it had been drawn,
  moving everything below them. They now arrive with the page. The release strip arrives this way
  while the server's last check is under six hours old; just after a restart, or once that answer
  is older, it is fetched as before.
- **Smaller movements while a page loads.** The page font is fetched before the first draw
  (headings changed width a moment later and could re-wrap the summary panel's header), the summary
  panel's Refresh icon keeps its size while the icon font loads, and the two summary cards hold
  their final widths from the start.
- **Screen-reader names and landmarks.** The icon-only buttons in the top bar and the quick
  sidebar's close link have names, the quick sidebar's tabs are announced as tabs, every page marks
  its main content area, and the minimized sidebar's links keep their names (their labels are now
  hidden from view instead of removed).

Measured with Chrome Lighthouse on a case page: layout shift 0.596 → 0.018, performance 75 → 99,
accessibility 66 → 89.

### Changed
- **Links inside written text are underlined** — case descriptions, notes, comments, task
  descriptions and the asset, IOC, event and evidence descriptions — so they no longer rely on
  colour alone. Other links (menus, buttons, the case and object lists) keep their look.

### Upgrading
Update as usual (`scripts/update.sh --ref IRIS-NG-v2.8.10`, or the 2.8.10 images / chart 1.8.10).
No migration runs.

## [IRIS-NG-v2.8.9] — 2026-10-29

Two interface fixes and three dependency updates. **No schema change** — the database head stays
at `c4d9a2e7f1b3`. Only the app image changes (page templates, one vendored browser library and
one Python package); the nginx and database images, and the guest-portal tunnel agent, do not
change.

### Fixed
- **Announcement banners were hidden under the top bar.** A banner set under Settings → Banners,
  and the "a newer release is available" strip, were drawn behind the fixed top bar (fully hidden
  on some screens, a sliver on others, nothing at all on Home) and left an empty band above the
  page. Both strips now sit directly under the top bar on every page, with the page starting right
  below them; the release strip stays above the announcements. Showing, dismissing or expanding a
  strip also moves the Timeline page's analysis and working-timeline panels with it straight away.
  The 403 page, which centres its content, shows no strip.
- **Add / Edit windows for Evidence, Assets, IOCs and Tasks closed on a click outside them (#156),**
  discarding whatever had been typed. They now stay open, as the Add Event window already did; Esc,
  the close button and Cancel still close them. Other windows keep closing on a click outside.

### Changed
- **marked 18.1.1 → 18.1.2 (Dependabot #160)**, the Markdown renderer behind notes and every other
  Markdown view. A parser fix release; three of its fixes change how some notes render:
  - a line starting with `#` and no space (such as a ticket number, `#4521`) written directly under
    a list item now stays part of that item instead of starting a new paragraph;
  - a tab after the `>` of a quote is kept as indentation;
  - an HTML block whose tag name is followed by a tab is recognised as HTML.

  Everything else in note-shaped Markdown (section tables, defanged IOC links, datastore images and
  file links, task lists, quotes, code) renders identically, and parsing is about 20% faster.
  autoprefixer 10.6.2 and svelte 5.57.3 rode along in the same update; neither changes any built
  file.
- **azure-identity 1.26.0 → 1.27.0 (Dependabot #161)**, used only when the configuration is read
  from Azure Key Vault. It adds an AKS identity-binding option and fixes three credential types
  IRIS-NG does not use; Key Vault configuration behaves identically.

### Upgrading
Update as usual (`scripts/update.sh --ref IRIS-NG-v2.8.9`, or the 2.8.9 images / chart 1.8.9).
No migration runs.

## [IRIS-NG-v2.8.8] — 2026-10-29

A dependency release. **No schema change** — the database head stays at `c4d9a2e7f1b3`. Only the
app image changes (one Python package and one vendored browser library); the application code is
identical to 2.8.7, and the nginx and database images, and the guest-portal tunnel agent, do not
change.

### Changed
- **xss 1.0.16 → 1.0.17 (Dependabot #158)**, the HTML filter behind note rendering and the
  escaping of alert, IOC and asset fields. It now falls back to its default handling when an
  option such as `escapeHtml` or `onTag` is null or not a function, treats a null allowlist as
  unset, and makes `filterXSSWithResult()` copy only the caller's own options. IRIS-NG calls the
  filter with no options or with an explicit allowlist, so its output is unchanged: the default
  filter and the note filter give identical results on 1.0.16 and 1.0.17 over note-shaped
  Markdown and hostile HTML, including with a polluted `Object.prototype`. The built
  `assets/js/plugin/xss/xss.js` is the only file of the browser bundle that changes.
- **WTForms 3.3.0 → 3.3.1 (Dependabot #159).** Keeps the form prefix when a `FieldList` renumbers
  its entries, and the `URL` validator no longer slows down exponentially on hostnames with long
  runs of dashes (a label with 36 dashes took over a second on 3.3.0). IRIS-NG's forms use
  neither, and every form renders and validates identically on both versions.

### Not taken
- **The devcontainer's Python 3.12 → 3.15 (Dependabot #157).** The devcontainer runs the same
  interpreter as the app image (`python:3.12-slim`), so it moves only together with it; Dependabot
  now leaves `devcontainers/python` minor and major versions alone.

### Upgrading
Update as usual (`scripts/update.sh --ref IRIS-NG-v2.8.8`, or the 2.8.8 images / chart 1.8.8).
No migration runs.

## [IRIS-NG-v2.8.7] — 2026-10-27

A bug-fix release for the MISP sync module. **No schema change** — the database head stays at
`c4d9a2e7f1b3`. Only the app image changes (the MISP sync module and
`scripts/misp_sync_repair.py`); the nginx and database images, and the guest-portal tunnel agent,
do not change.

### Fixed
- **MISP sync: IOCs whose value MISP's validation refuses never reached the case's event.** MISP
  checks each attribute's value against its type and rejects an attribute that does not fit, so
  these IOCs were never added and the MISP application log recorded a validation error for each.
  The module now sends them in a form MISP accepts:
  - a hostname without a domain part (a workstation name such as `DESKTOP-1A2B3C`; MISP's
    hostname type needs a dot and a top-level part of at least two characters) goes as type
    `other`, in the Network activity category where the MISP allows it, and still takes part in
    correlation;
  - a bare hash typed `filename|sha256` (or another `filename|<hash>` type) goes as the hash
    type;
  - a port written with its protocol (`tcp/8070`, `8070/udp`) goes as the number;
  - a line break inside a value becomes one space, and surrounding whitespace is trimmed.

  When the type changes, the attribute's comment records the IRIS type (`iris_type=hostname`), and
  when the value changes beyond whitespace it records the value as typed (`iris_value=tcp/8070`).
  An IOC whose value does not fit its type at all, such as a URL typed `ip-dst` or a bare filename
  typed `filename|sha256`, is still refused: change its type in IRIS and it syncs.

### Changed
- `scripts/misp_sync_repair.py` compares an attribute's value with its IOCs' values as the sync
  sends them, so an attribute holding `8070` for an IOC typed `tcp/8070` is not reported as
  damaged.

### Upgrading
Update, then run `scripts/misp_sync_repair.py` (the command is in the 2.8.6 notes below): the IOCs
MISP refused are listed as IOCs without an attribute, and `--apply --sync-missing` adds them.

Checked against a stand-in MISP that applies MISP 2.5.32's validation to these types: each shape
above is accepted and its comment carries the note, a hostname with a domain part and a complete
`filename|sha256` value go unchanged, a recreated port IOC finds the attribute holding the number,
and a URL typed `ip-dst` and a bare filename typed `filename|sha256` are still refused with nothing
added.

## [IRIS-NG-v2.8.6] — 2026-10-27

A bug-fix release for the MISP sync module. **No schema change** — the database head stays at
`c4d9a2e7f1b3`. Only the app image changes (the MISP sync module and one new script); the nginx
and database images, and the guest-portal tunnel agent, do not change.

### Fixed
- **MISP sync: each new IOC overwrote the case's first MISP attribute instead of adding its own
  (MISP 2.5.32 and earlier).** Before adding an attribute for an IOC it has not synced yet, the
  module looks in the case's MISP event for an attribute that already carries that IOC's marker
  (`dfir_ioc_uuid=…` in the comment). Up to MISP 2.5.32, MISP's attribute search does not support
  the full-text filter that lookup used and ignores it without an error, so the search returned
  every attribute of the event and the module took the first one as the IOC's own. Every IOC after
  the first was linked to that attribute and updated it in place: its value and comment were
  replaced and the IOC's tags were added to it, so a case's event ended up with a single attribute
  holding the latest IOC's value and every IOC's tags, while the module's task log reported
  success. On MISP 2.5.33 and later the filter is honoured, but it replaces the event filter and
  matches a whole field, so the lookup never found anything there: IOCs were added correctly, but
  an IOC whose link was lost could not be matched to its attribute again.
  The lookup now behaves the same on both: it checks every attribute MISP returns and reuses one
  only when it belongs to the case's event and carries the IOC's marker, or the IOC's type and
  value. Anything else gets a new attribute. Several IOCs with the same type and value still share
  one attribute, since MISP keeps one per event.

### Added
- **`scripts/misp_sync_repair.py`** finds what the bug left behind and repairs it. Run it in the
  app container (the container name of a Docker Compose install):
  ```
  docker exec -w /iriswebapp -e PYTHONPATH=/iriswebapp iriswebapp_app \
      python /iriswebapp/scripts/misp_sync_repair.py
  ```
  On its own it only reports: each MISP attribute linked to IOCs of different types or values, or
  holding a value none of its IOCs has, and each IOC with no MISP attribute; `--case <id>` limits
  it to one case. `--apply` soft-deletes each damaged attribute (MISP keeps it under the event's
  Deleted view) and syncs its IOCs again, so each gets its own attribute and tags;
  `--sync-missing` also syncs the IOCs that have none.

### Upgrading
If the MISP sync module runs against MISP 2.5.32 or earlier, turn off its "Trigger on IOC create"
and "Trigger on IOC update" settings (Manage → Modules) until you have updated, so no more
attributes are overwritten. Update, run the repair report, then run it again with `--apply` (and
`--sync-missing` if it lists IOCs without an attribute), and turn the two settings back on.

Checked against a stand-in MISP answering as 2.5.32 and as 2.5.33 and later: new IOCs each get
their own attribute and tags, an edit changes only its own attribute, a lost link is found again
by the marker, a recreated IOC reuses its predecessor's attribute, an attribute in another case's
event is never reused, and the repair script gives each damaged IOC its own attribute again while
leaving legitimately shared ones alone.

## [IRIS-NG-v2.8.5] — 2026-10-26

A security and dependency release. **No schema change** — the database head stays at
`c4d9a2e7f1b3`. The app image changes (Python packages and two vendored browser libraries), and
so does the guest-portal tunnel agent, which every install builds locally; the application code
is identical to 2.8.4, and the nginx and database images do not change.

### Security
- **Guest-portal tunnel agent: cloudflared pinned to 2026.10.4.** cloudflared before 2026.10.2
  trusts eight eMudhra (emSign) intermediate certificates whose private keys are weak, so anyone
  holding them can issue a certificate for any site (Cloudflare's notice of 2026-10-20; Go's
  `crypto/x509` now refuses chains through them, CVE-2026-111943). The agent was built from
  `cloudflare/cloudflared:latest`, and `docker compose up --build` (which `scripts/update.sh`
  runs) never re-downloads a `latest` image it already has, so every install kept the cloudflared
  it first built with; an agent first built in September runs 2026.9.x. The tag is now pinned and
  Dependabot tracks it. 2026.10.4 also restricts the debug endpoints on cloudflared's metrics
  server. **Updating to 2.8.5 with `scripts/update.sh` rebuilds the agent** when the guest portal
  is enabled; Settings → Guest Portal shows the version it reports. To rebuild the agent alone,
  from the clone: `docker compose -f docker-compose.dev.yml -f docker-compose.portal.yml build
  --pull tunnel`, then the same with `up -d tunnel`. A quick tunnel gets a new hostname whenever
  it restarts; a named tunnel keeps its own.
- **Tunnel agent base image Alpine 3.20 → 3.24 (Dependabot #150).** Alpine 3.20 has been end of
  life since 2026-04-01 and no longer receives fixes. Checked against Alpine's maintained security
  data, its package versions (curl, OpenSSL, jq, BusyBox, musl and others) matched about 130
  advisories; the 3.24 image matches none. The agent behaves exactly as before.
- **xss (js-xss) 1.0.15 → 1.0.16 (Dependabot #151)**, the HTML sanitiser every page loads. It now
  ignores inherited object properties when reading its options and allowlists: if another script
  on a page had polluted `Object.prototype`, 1.0.15 let a `<script>` tag through the filter that
  renders notes, and 1.0.16 escapes it. It also refuses non-HTTP(S) schemes in form `action` /
  `formaction` under a custom allowlist (IRIS-NG's allowlist has no form elements). Notes and other
  content render exactly as before.
- **certifi 2026.10.23** (picked up by the rebuild): removes two eMudhra roots (emSign Root CA -
  C1, emSign ECC Root CA - C3) from the certificate bundle IRIS-NG uses for outbound HTTPS (MISP,
  AI backends, the update check).
- **setuptools floor raised to 84.2.1 (Dependabot #154).** Rules out the releases with
  GHSA-xmj3-9gf7-h52w (Windows only; not reachable here). The image already installed 84.2.1.

### Changed
- WTForms 3.2.2 → 3.3.0 and alembic 1.20.0 → 1.20.1 (Dependabot #153). Every form renders and
  validates as before, including the CSRF check; the boot migration runs unchanged.
- ace-builds 1.45.2 (the notes editor; a soft-keyboard deletion fix), vite 8.3.5 with rolldown
  1.2.15 (the built bundles differ only in comments) and, in the end-to-end harness, dotenv 18.0.9
  (Dependabot #151).
- Dependabot now also watches the tunnel agent's Dockerfile, and holds three updates that cannot
  apply as proposed: Chart.js 3 and later (a rewrite — the dashboard, Inventory and Metrics charts
  need porting first; #152), marshmallow-sqlalchemy 1.6 and later (requires marshmallow 4; part
  of #153) and python-dateutil 3 (graphene, behind `/graphql`, requires an earlier version; #155).

Checked on the rebuilt images: the app image differs from 2.8.4 in exactly the packages above
(plus wcwidth, a command-line helper) and the two vendored libraries; no broken requirements;
every module imports; app and both workers start cleanly; GraphQL, a `.docx` report, case create
and delete, login and every test suite give the same results as before. The tunnel agent
connects, reports cloudflared 2026.10.4, serves the guest portal and restarts cloudflared when it
stops.

## [IRIS-NG-v2.8.4] — 2026-10-23

A security release for two Python packages in the app image. **No schema change** — the database
head stays at `c4d9a2e7f1b3`. Only the app image changes; the application code is identical to
2.8.3, and the nginx and database images do not change.

### Security
- **idna 3.3 → 3.20.** The image was held on idna 3.3 by the bundled `evtx2splunk` wheel (used by
  the EVTX import module), which pinned it exactly although it never uses idna itself. Because
  that pin sat inside the wheel rather than in `requirements.txt`, dependency scanners could not
  see it. idna 3.3 carries two denial-of-service advisories (GHSA-jjg7-2v4v-x38h /
  CVE-2024-3651 and GHSA-65pc-fj4g-8rjx / CVE-2026-45409): a crafted hostname makes
  `idna.encode()` take quadratic time. The `requests` library encodes non-ASCII hostnames with
  it, including the target of a redirect, so a server IRIS-NG contacts (MISP, an AI backend, a
  webhook target) could tie up a worker; a 16,000-character label took 17 seconds of CPU on
  3.3 and is rejected immediately on 3.20. The bundled wheel now leaves idna unpinned (that one
  line of its metadata changed, nothing else), and `requirements.txt` pins idna 3.20 directly
  so it is tracked from now on. Ordinary internationalised hostnames encode exactly as before.
- **pypdf 6.21.1 → 6.21.2.** Closes three further pypdf advisories (GHSA-gmh7-3g9r-mjh5,
  GHSA-jr96-gvgh-j3r4, GHSA-6c7f-9265-g8fw: long runtimes on malformed cross-reference data
  and repeated references to a missing object). Not reachable: the ICS form export, the only
  user of pypdf, opens only the bundled FEMA forms. The seven forms export identically.

Checked on the rebuilt image: it differs from 2.8.3 in exactly these packages and the bundled
wheel; no broken requirements; every module imports; app and both workers start cleanly; and
GraphQL, a `.docx` report, case create and delete, the ICS PDF export and every test suite give
the same results as before.

## [IRIS-NG-v2.8.3] — 2026-10-22

A dependency and security release. **No schema change** — the database head stays at
`c4d9a2e7f1b3`. Only the app image changes (Python packages and two vendored browser libraries);
the application code is identical to 2.8.2, and the nginx and database images do not change.

### Security
- **pypdf 6.20.0 → 6.21.1 (Dependabot #147; #149 proposed the same change).** Closes six pypdf
  advisories: unvalidated JPEG image data loading (GHSA-5hx5-vpf9-5wcv), long runtimes / large
  memory when retrieving form fields (GHSA-6vvc-x485-93v7), large memory when parsing arrays and
  dictionaries (GHSA-f54x-cmq8-qg57), large memory when parsing content streams
  (GHSA-cgf9-327m-v77c), and infinite loops when removing tree items (GHSA-9mx8-4j7g-633p) and in
  `PdfWriter.find_outline_item` (GHSA-qfv9-64jg-mh7p). None was reachable: pypdf is used only by
  the ICS form export, which parses the bundled, checksum-pinned FEMA forms and nothing a user
  uploads. The seven ICS forms export identically. Three further advisories fixed only in pypdf
  6.21.2 (published 2026-10-21; long runtimes on malformed cross-reference data) are not part of
  this release and are equally unreachable.
- **follow-redirects 1.16.0 → 1.16.1 in the end-to-end test harness (Dependabot #148).** Closes
  GHSA-q3jh-wrc6-jgq8 (credential headers passed in array form were kept on a redirect to another
  host) and GHSA-8r9p-f939-6h3c (`sensitiveHeaders` names containing `^` or `|` were never
  stripped). Both reproduce on 1.16.0 and not on 1.16.1. The package belongs to the test harness's
  readiness poll only, which sends no credentials; nothing of it ships in an image.

### Changed
- **SQLAlchemy 2.0.54 → 2.0.55 (Dependabot #147).** Fixes a regression since 2.0.36 where a bulk
  ORM `update()` refreshed an `onupdate` column on only one of the matched objects already loaded
  in the session. In IRIS-NG only the case template's `updated_at` has such a column, and no bulk
  update touches it.
- **Code editor and Markdown renderer (Dependabot #146).** ace-builds 1.44.0 → 1.45.0 (variable-
  width font support, faster search highlighting, three new Godot language modes; its changelog
  entry "V-001 security vulnerability" changes only ace's own build tooling, not the published
  editor). marked 18.1.0 → 18.1.1, which renders note bodies: CommonMark conformance fixes for
  blockquotes after headings, backslashes in code spans, character references, HTML blocks and
  tab-indented lists. Twenty note-shaped samples (indicator links, pasted images, datastore links,
  defanged URLs, tables, nested task lists) render identically, and the notes and alert-filter
  editors behave the same. Also eslint 10.13.0 (build-time only) and, in the test harness,
  @playwright/test 1.64.1 and dotenv 18.0.8.
- **Unpinned packages in the rebuilt image:** Pillow 12.3.0 → 13.0.0 (pulled in by the QR-code
  library for MFA setup; the MFA QR code is byte-identical), certifi, pycparser, pydantic-settings,
  setuptools 84.2.1, tzlocal and wcwidth. Checked on the rebuilt image: every module imports, app
  and both workers start cleanly, and GraphQL, a `.docx` report, case create and delete, the ICS
  PDF export and every test suite give the same results as before.

## [IRIS-NG-v2.8.2] — 2026-10-16

Faster working-timeline imports for large files. **No schema change** — the database head stays
at `c4d9a2e7f1b3`. The app image changes (Python and one template); the nginx and database
images do not.

### Changed
- **Large imports upload compressed.** The working-timeline import modal (Hayabusa and EZ Tools)
  gzips a file over 1 MB in the browser before sending it, and the server decompresses it as it
  parses. A 963 MB full-host Hayabusa run goes over the network as 24 MB; compressing it takes a
  few seconds in the browser. The server reads the whole upload before it starts parsing, so on a
  remote instance the upload was most of the wait. A `.csv.gz` you pick yourself is sent as is,
  and a browser without `CompressionStream` sends the raw file as before.
- **The modal says which phase it is in:** Compressing N MB (%), then Uploading N / M MB (%),
  then Parsing on the server… N s, instead of one "Uploading + parsing…" line for the whole
  import.
- **Hayabusa parsing is faster, with the same output.** Timestamps are read without `strptime`,
  and rows outside the date window or the selected levels are no longer cleaned up before being
  skipped. On the 963 MB file the parse drops from 24 s to 13.5 s on the development machine.
- **EZ Tools imports stream the upload** instead of reading it into memory first.

### Added
- **Time of day on the import window.** From and To each take an optional time (UTC) beside the
  date; To includes its whole minute. A day that holds more than the 25,000-event cap can be
  imported in several windows. API: `begin_time` / `end_time` (`HH:MM` or `HH:MM:SS`) on all
  three import endpoints; a time without its date is a 400; an ISO datetime sent in `begin_date`
  / `end_date` still reads as its date only.
- **gzip on the import API.** `POST …/working-timeline/import/{hayabusa,eztools,master-csv}`
  accept a gzip-compressed `file`, detected by its magic bytes rather than the file name or
  content type. A damaged or truncated gzip is a 400 that says so. The master-timeline CSV
  import, which holds the file in memory, refuses more than 512 MB once decompressed.
- **`truncated_at` in the Hayabusa import response:** when the cap stops an import, the newest
  imported event (UTC, `Z`-suffixed); `null` otherwise. The modal shows it ("reached 2026-10-14
  08:41:07 UTC") and stays open instead of closing after the import.

## [IRIS-NG-v2.8.1] — 2026-10-15

A dependency-only release. **No schema change** — the database head stays at `c4d9a2e7f1b3`.
The application code is identical to 2.8.0. The browser bundle differs in one vendored file,
`marked.min.js`; every bundle Vite builds is byte-for-byte the 2.8.0 output.

### Changed
- **Markdown renderer (Dependabot #144).** marked 18.0.14 → 18.1.0, the library vendored as
  `assets/js/plugin/marked/marked.min.js` that renders note bodies and other Markdown in the
  browser. 18.1.0 fixes cubic backtracking on unicode whitespace in a link destination: marked's
  own regression input (`[](` followed by non-breaking spaces) takes 2.3 s at 2 000 characters
  and 36 s at 5 000 on 18.0.14, under a millisecond on 18.1.0, so a crafted note could freeze the
  browser tab of anyone who opened it. It also stops treating a link destination with unbalanced
  parentheses as a link. Fifteen note-shaped samples (indicator mention links, sized pasted
  images, datastore file links, defanged URLs, tables, balanced parentheses) render identically;
  the only differences are the unbalanced-parenthesis cases. The same group moves vite 8.3.4,
  svelte 5.57.2, eslint-plugin-svelte 3.23.1 and the transitive nanoid 3.3.20 and postcss
  8.5.29 (build-time only, output unchanged), and in the end-to-end test harness
  @playwright/test 1.64.0, dotenv 18.0.7 and @types/node. The UI `npm audit` is unchanged (the
  six findings under Tailwind CSS 3).
- **Python dependencies (Dependabot #145).** SQLAlchemy-Utils 0.42.1 → 0.43.0 (IRIS uses only
  its database-creation helpers at boot, whose behaviour on SQLAlchemy 2.0 is unchanged; the
  release also adds SQLAlchemy 2.1 support, which this release does not adopt); Flask-SocketIO
  5.6.1 → 5.7.0 (two error-handling changes in the event dispatcher; the Socket.IO handshake and
  the `/alerts` namespace behave as before); pypdf 6.19.0 → 6.20.0 (per-stream work limits,
  BrotliDecode, robustness fixes; the seven ICS forms export byte-identically). The rebuilt image
  also resolves newer unpinned transitive packages: pycparser 3.11, pycryptodomex 3.24.1,
  pydantic 2.14.1, pydantic-core 2.50.1, pydantic-settings 2.16.0 and wrapt 2.5.1. Checked on the
  rebuilt image: every module imports, app and both workers start cleanly, and GraphQL, a
  `.docx` report, case create and delete, the ICS PDF export and every test suite give the same
  results as before.

## [IRIS-NG-v2.8.0] — 2026-10-09

The Executive Case Summary becomes a verified summary with review questions. **One schema
migration (`c4d9a2e7f1b3`)** — take a database dump before upgrading (migrations are one-way;
`scripts/update.sh` does the dump). Python and two templates; the browser bundle is unchanged.
A clone install needs a reset and an app + worker restart; the release images are rebuilt as
always.

### Added
- **Writer, checks, verifier.** The summary is no longer one prose pass. The five domain
  specialists cite the notes, events, indicators, assets and evidence items they draw on; a
  writer role turns them into sourced claims (section, text, confidence tier, cited objects)
  that the server renders into the familiar ten-section briefing, with every count, the assets
  table and the fixed lines computed server-side. Deterministic checks compare each claim with
  its cited sources: the objects exist in the case; numbers, dates, addresses, host names and
  accounts appear in them; task wording matches the task's status; evidence claims match the
  register; no "yesterday" or "in the past few hours". A verifier role judges every claim
  against only its cited sources and reads the whole briefing once for contradictions and the
  known failure patterns (a download described as a file, one address as one actor, a
  third-party figure stated as confirmed, an unsourced impact number, relative time, a status
  the claims do not support). When a high-severity flag remains, one automatic revise pass
  runs; never a second.
- **Review questions instead of a blank box.** Every flag becomes a question in the new
  Review tab of the summary panel, with concrete options proposed from the context (a
  rewritten sentence, a lower confidence tier, drop) plus "keep as written" and "other". Once
  every question is answered, **Apply answers** builds the next pass: the answers are applied
  exactly as chosen, the text is re-rendered and re-checked, a kept flag is not asked again,
  and anything new comes back as a question. Free-text "other" answers are the only ones that
  go back to the writer, and it may change only those claims. The Audit tab shows which
  backend (provider, label, model, prompt) produced each step, every pass, and the superseded
  questions. The status pill reads Draft while a question is open and Verified otherwise;
  `summary_status` and `summary_questions_open` travel with the case payload (module hooks,
  `/case/meta`) for report templates and webhooks.
- **Roles map to backends.** The writer uses the existing *Case Summary* override; the
  verifier and the question builder use the new *Case Summary verifier* override row, so a
  different backend can check the writer's work. Settings → AI also gains **Verify executive
  summaries** (on by default): off means the deterministic checks only, which still ask their
  questions.
- API: `GET /api/v2/cases/<id>/ai/summary` carries `summary_status`, `summary_questions_open`
  and a `verification` block; `GET …/summary/verification` (claims, questions with options,
  steps, passes); `POST …/summary/flags/<id>/answer`; `POST …/summary/apply-answers` (an
  async job, `?sync=true` inline). Indicator values, host names and accounts may now appear in
  the briefing when a cited source contains them; `unverified` and `third-party reported`
  claims carry an italic marker.

### Changed
- **Upgrade path.** Summaries generated before this release read as *Draft · not reviewed*
  and get questions on their next generation; the text itself is untouched. The specialist
  caches re-run once per case (the prompts changed), as do the case chat and task-suggester
  caches that share the case payload. A reasoning model on the writer role needs the
  12 000-token budget this release sets; the verifier and the question builder use 6 000.
  Answering a question no longer invalidates the summary cache (the activity-log timestamp
  left the cache key).

## [IRIS-NG-v2.7.0] — 2026-10-09

Any number of AI backends. **One schema migration (`b8e3f1a7c2d5`)** — take a database dump
before upgrading (migrations are one-way; `scripts/update.sh` does the dump). Python, one
template and one settings script; the browser bundle rebuilds for the settings script. A clone
install needs a reset and an app + worker restart; the release images are rebuilt as always.

### Added
- **As many AI backends as you want.** Settings → AI shows one card per backend and a
  **+ Add backend** button; each card saves and deletes on its own, and the "Use this backend"
  radio (saved with the tab) picks the active one. Backends live in a new `ai_backend` table
  (label, provider, URL, model, write-only API key, Bedrock catalog); labels are unique, the
  active backend cannot be deleted, a backend added while none is active becomes active, and
  deleting a backend that features were pinned to resets those pins to the active backend.
  "Load models" (Bedrock) works per card once the card is saved. The per-feature override
  table lists every backend by label.
- Admin routes `GET /manage/settings/ai/backends/list`, `POST …/add`, `POST …/update/<id>`,
  `POST …/delete/<id>` and `POST …/<id>/catalog` (the per-backend Bedrock listing). The
  settings form keeps only the pointers: `ai_backend_active_id` and `ai_feature_overrides`
  (values are now backend ids); an id that does not exist is a *Data error* naming the field.

### Changed
- **Upgrade path.** The migration imports the two existing slots once: every slot that had a
  URL or model becomes a backend (its label kept, a duplicate label suffixed), the active slot
  becomes the active backend and every per-feature pin is remapped, so nothing needs to be
  retyped. The old slot columns stay in the database but are no longer read, and the retired
  settings keys (`ai_backend_url`, `ai_backend_alt_*`, `ai_backend_active_slot`, the slot
  providers, labels and catalogs) are gone from the settings payload; a submission naming them
  is ignored. `POST /manage/settings/ai/bedrock/catalog` (added in 2.5.0) is replaced by the
  per-backend route. `AI_BACKEND_*` environment variables seed the first backend only while no
  backend exists.

## [IRIS-NG-v2.6.0] — 2026-10-09

OpenAI's own API as a first-class AI backend, and a chat-completions client that adapts its
request shape to whatever is on the other end. **No schema change** — the database head stays
at `a7c2d9e4f1b6`. Python and one template: a clone install needs a reset and an app + worker
restart; the release images are rebuilt as always.

### Added
- **"OpenAI (api.openai.com)" as a Provider choice on each AI slot** (Settings → AI). OpenAI's
  current models reject `max_tokens` ("Use `max_completion_tokens` instead") and its reasoning
  models reject any explicit temperature, so the executive case summary failed on every domain
  specialist against gpt-6.1-sol. The new provider sends `max_completion_tokens` from the
  first call. The existing entry keeps its stored value and is now labelled "OpenAI-compatible
  (LM Studio, OpenRouter, vLLM, Ollama)"; nothing changes for configured slots. Per-feature
  overrides keep picking a slot, so the provider follows the slot.
- **Self-healing request shape on both OpenAI-style providers.** A 400 that rejects
  `max_tokens` is resent once with `max_completion_tokens`; a 400 that rejects `temperature` is
  resent once without it. Each lesson is remembered per backend URL and model for the life of
  the worker process, so the next request for that backend sends the right shape first. A
  gateway that fronts OpenAI therefore works on the "OpenAI-compatible" setting too; choosing
  "OpenAI" only saves the first rejected call per worker. Only an explicit instruction naming
  `max_completion_tokens` is followed, only a 400 counts, and every other error is raised as
  before. Reasoning tokens count against `max_completion_tokens` exactly as they do on Bedrock,
  which the per-surface budgets and the compact retry already cover.

## [IRIS-NG-v2.5.4] — 2026-10-08

A dependency-only release. **No schema change** — the database head stays at `a7c2d9e4f1b6`.
The application code is identical to 2.5.3; the only change is a build-stage npm lockfile
entry, so the browser bundle is byte-for-byte the 2.5.3 bundle and the image-level delta is the
version string.

### Changed
- **Dependencies (Dependabot #142).** source-map-js 1.2.1 → 1.2.2 in the UI build closes
  **GHSA-68fv-2mgg-jv7q** (CVE-2026-93749, high): an indexed source map carrying an arbitrarily
  large per-section line offset made the library emit one separator per claimed line and block
  the event loop; 1.2.2 caps the offset at ten million (nested offsets summed), rejects
  non-integer offsets and builds line gaps as a single string. The package is a devDependency
  reached only through postcss (vite, tailwindcss, eslint-plugin-svelte) while the Docker node
  stage compiles the tree's own CSS, and the shipped images run no Node, so nothing in a running
  IRIS was reachable. Applied verbatim from the PR; baseline and candidate builds produce the
  same 716 dist files md5-for-md5, lint is identical, and the UI `npm audit` goes 9 → 8 (the
  remaining findings are the Tailwind 3 chain, pending that major upgrade). A behaviour probe on
  the library's own indexed fixture resolves the same positions on both versions while 1.2.2
  refuses the out-of-range and malformed offsets 1.2.1 accepted.
- **Dependencies (Dependabot alert #154, no PR).** postcss-selector-parser is pinned to 7.1.6
  through an npm `overrides` entry in the UI manifest, closing **GHSA-rj75-hqrm-r3gf**
  (CVE-2026-104844, medium): a flat selector such as `.a.a.a…` with many class or id indexes
  parsed in quadratic time, and the fix exists only on the 7.x line. The build held two copies,
  6.1.4 (what tailwindcss 3.4.x and postcss-nested declare — no 6.x release carries the fix) and
  7.1.4 (under svelte-eslint-parser); the override resolves both to 7.1.6. Tailwind only runs at
  build time over the tree's own CSS, and its stylesheet is not reached by any build entry, so
  nothing in a running IRIS was exposed. Validation: the 716 dist files are md5-identical with the
  override, compiling the Tailwind stylesheet directly with the forced parser produces a
  byte-identical result, and a timing probe shows 6.1.4 and 7.1.4 growing about fourfold per
  doubling of the index count while 7.1.6 grows linearly; the UI `npm audit` goes 8 → 6 (both
  moderate findings close; the remaining six are the `braces` chain under Tailwind 3).

## [IRIS-NG-v2.5.3] — 2026-10-08

The output-limit retry reaches every JSON-contract AI surface. **No schema change** — the
database head stays at `a7c2d9e4f1b6`. Python only: a clone install needs a reset and an app +
worker restart; the release images are rebuilt as always.

### Fixed
- **"AI backend did not return JSON" on IOC extraction from notes, the ATT&CK suggester, the
  evidence-type and case-template suggesters, the IOC deduplication pass and mail triage when
  the backend is a reasoning model.** 2.5.2 covered five surfaces; the IOC extractor failed the
  same way on the next click (its reply quoted the opening of the indicator list) at a
  1 500-token cap, and five more surfaces budgeted 600 to 3 000 tokens. All six now run the
  shared retry: a reply cut by the output limit before its JSON parses is retried once with a
  compact instruction, same budget; twice truncated names the limit, the retry and the
  per-feature Settings override. Budgets: IOC extractor and dedup pass 8 000, ATT&CK suggester
  and mail triage 6 000, evidence-type and case-template suggesters 4 000, with client timeouts
  moved to match. The executive case summary's specialists budget 6 000 and its synthesis 8 000
  (budget only). Nothing is cached on either failure.

### Changed
- **Dependencies (Dependabot #139, npm minor/patch group).** UI: marked 18.0.14 (six parser
  fixes in the vendored renderer — numeric character references in text are now decoded,
  `mailto:` autolinks keep the scheme in their text, tabs inside list items are preserved,
  reference-link labels tolerate surrounding spaces, indented setext headings and empty nested
  blockquotes), dropzone 6.3.5 (two upload fixes on paths the pipelines modal does not use;
  the modal's behavioural probe is 18/18 on both builds), socket.io 4.8.4 (server-side fixes;
  the vendored browser client is the rebuilt 4.8.4 file), vite 8.3.2, rolldown 1.2.12,
  @sveltejs/vite-plugin-svelte 7.3.1, eslint 10.12.0, globals 17.13.0. The bundled
  application JavaScript is byte-identical; only the three vendored files differ, each
  matching its npm tarball. e2e: wait-on 9.5.1, dotenv 18.0.5, @types/node 24.19.1, and
  **joi 18.2.9 closes GHSA-wr44-6hxh-3jwq** (CVE-2026-90771, moderate: prototype pollution
  through `__proto__` error codes in custom messages) — joi is a transitive of the e2e
  readiness poll and the e2e job is disabled, so it was unreachable in a running IRIS; the e2e
  `npm audit` goes 1 → 0, the UI audit stays at its pre-existing Tailwind 3 chain.
- **Dependencies (Dependabot #140, python minor/patch group).** PyJWT 2.15.1 (one change: a
  JWS segment carrying trailing Base64URL `=` padding, as AWS ALB issues, now decodes instead of
  raising `Invalid crypto padding`; non-alphabet junk is still rejected — probed per version;
  reached only by the OIDC `signature` mode), azure-identity 1.26.0 (Arc user-assigned managed
  identities, a cached-token fix for `AuthorizationCodeCredential`, `x-ms-client-request-id` on
  every request; msal floor 1.39.0 already met) and azure-keyvault-secrets 4.11.3 (authentication
  challenge cache verified before token use, backslashes in the authority rejected) — both
  reached only when `AZURE_KEY_VAULT_NAME` is set — and python-gnupg 0.5.7 (new helper
  functions; imported only by the retired updater module). Seven unpinned riders re-resolved
  at patch level (MarkupSafe 3.0.4, amqp 5.4.1, billiard 4.3.1, click-repl 0.4.1, pycryptodomex
  3.24.0, tzdata 2026.5, wcwidth 0.9.2). Validated by importing every top-level module of the
  built image before the recreate, then the scripted before/after stack snapshots. Dependabot
  #141 raises the `cryptography` floor to `>=50.0.2` (OpenSSL 4.0.3 wheels): the image already
  resolved 50.0.2 under the old floor, so the installed set is unchanged; 50.0.0's PKCS#7
  decryption-oracle fix (CVE-2026-69247) was already in place.

## [IRIS-NG-v2.5.2] — 2026-10-07

Every JSON-contract AI surface now survives a reasoning model on AWS Bedrock. **No schema
change** — the database head stays at `a7c2d9e4f1b6`. Python only: a clone install needs a
reset and an app + worker restart; the release images are rebuilt as always.

### Fixed
- **"AI backend returned no JSON object" on the war-room operational summary, the SitRep AI
  draft, the correlation cluster narrative, the alert-cluster triage and the ICS AI pass when the
  backend is a reasoning model.** 2.5.1 fixed the task suggester alone; the same cause — the
  model's thinking counts against the same output budget as its answer, so the JSON was cut
  mid-string at caps written for non-thinking models — sat in five more surfaces, three of them
  budgeting under 2 500 tokens (the cluster narrative 800). The output-limit retry is now one
  shared routine: a reply that `finish_reason=length` cuts before its JSON parses (empty or
  truncated) is retried once with a compact instruction on the user turn (answer first, fewer
  and shorter items), same budget; a `length` stop whose JSON still closes is an answer; non-JSON
  at a normal stop is still an immediate error. Budgets: operational summary and ICS pass 12 000,
  SitRep draft 8 000, alert-cluster triage 6 000, cluster narrative 4 000 (the model stops when
  the object closes, so a model that needs less is unaffected); client timeouts moved with
  them. A reply that truncates twice says so and points at the per-feature Settings override to
  a non-reasoning model. Nothing is cached on either failure.

## [IRIS-NG-v2.5.1] — 2026-10-07

One fix for the AI task suggester on reasoning models. **No schema change** — the database
head stays at `a7c2d9e4f1b6`. Python only: a clone install needs a reset and an app + worker
restart; the release images are rebuilt as always.

### Fixed
- **Task suggestions failed with "AI backend did not return JSON (the reply hit the output
  limit)" on a reasoning model.** The suggester capped replies at 6 000 tokens; a model that
  reasons before it writes (Kimi K3 on AWS Bedrock, for one) spent most of that thinking, and on
  a case with several tasks the JSON was cut mid-string. The budget is now 12 000 (the model
  stops when the object closes, so a model that needs less is unaffected), and a reply that the
  output limit cuts before its JSON closes is retried once with a compact instruction — answer
  first, at most 5 suggestions, descriptions at most 2 sentences — before it is reported. A
  reply that still truncates twice says so and points at the per-feature Settings override to a
  non-reasoning model. Nothing is cached on either failure.

## [IRIS-NG-v2.5.0] — 2026-10-07

A new AI backend provider and a war-room usability fix. **One schema change** — migration
`a7c2d9e4f1b6` adds four nullable columns to `server_settings` (the database head moves from
`f4b8d2e6a913`); take a `pg_dump` before updating a production install. The app image is
rebuilt (Settings template, war-room script); a clone install needs a reset, a rebuild and an
app + worker restart.

### Added
- **AWS Bedrock as an AI backend provider.** Each AI backend slot in Settings > AI now names its
  provider: *OpenAI-compatible* (the existing `/v1/chat/completions` client — LM Studio,
  OpenRouter, OpenAI) or *AWS Bedrock*, which talks to the Converse API with a Bedrock API key.
  For a Bedrock slot the URL field takes a region (`us-west-2`; a full endpoint URL still works
  for private endpoints) and the server builds the hosts; the Model field takes an inference
  profile ARN (pasted plain or URL-encoded, as the console copies it), a profile id or a model
  id. **Load models** lists the inference profiles the key can see (your named application
  profiles first, then the system-defined cross-region ones) and turns the Model field into a
  dropdown of friendly names; the chosen entry's ARN is what gets stored, and *Other* still takes
  a pasted value. The listing needs `bedrock:ListInferenceProfiles` on the key's IAM user — a
  console-generated long-term key does not have it, and the error says what to attach. Every
  AI surface runs unchanged: the adapter returns the same reply shape the other client does.
  Reasoning content from thinking models is dropped structurally; a stop caused by a guardrail
  or the provider's content filter is an error, never cached as an artifact; IRIS applies no
  Bedrock Guardrail of its own. A model that rejects the `temperature` field (Kimi K3 on
  Bedrock) is retried once without it and the rejection remembered for the rest of that job.
- **Right-click menus on the war-room Notes rail** (#137). Folders offer Add note / Rename /
  Delete; notes offer Open / Rename / Move to… / Copy link / Delete; the empty rail offers Add
  note / Add folder. Mutating items follow the same rule as the hover icons (responder or above,
  room not closed). *Copy link* yields the room URL with `?note=<id>`, which opens that note on
  the Notes tab. `/note <text>` in the stream now creates a note on the Notes tab (first line =
  title) instead of a stream message; `/pin` keeps the stream note. The command parser accepts
  multi-line arguments. `POST /war-rooms/<id>/notes/room` accepts an optional `content`.

### Changed
- **AI backend API keys are write-only.** The two stored keys are no longer returned by the
  settings API or prefilled into the Settings page; a *stored* badge shows one is set, and
  leaving the field blank on Save keeps the stored value (the same contract as the mail
  passwords). The settings payload gains `ai_backend_api_key_set` / `ai_backend_alt_api_key_set`
  booleans, `ai_backend_provider` / `ai_backend_alt_provider`, and the two read-only
  `*_model_catalog` lists.
- **Bedrock usage reporting** folds prompt tokens served from the prompt cache into
  `prompt_tokens` (Bedrock reports them separately) and details the cached share.

## [IRIS-NG-v2.4.6] — 2026-10-05

One fix for module hooks and webhook consumers. **No schema change** — the database head stays
at `f4b8d2e6a913`. Python only: a clone install needs a reset and an app restart; the release
images are rebuilt as always.

### Fixed
- **Changes to the Executive Case Summary now fire `on_postload_case_update`** (#138). The
  Summary tab's AI card is a stored artifact with its own save path, and nothing on that path
  reached the module layer — a webhook consumer (for example n8n syncing a case to Jira) saw
  an edited executive summary only when a later rename, close or reopen happened to fire the
  hook. The hook now fires after an analyst saves a correction, after a revert to the AI
  original, and after a generation completes with a new summary. It fires after the commit,
  only when the displayed text actually changed (saving identical text, or a generation served
  from cache, stays silent), and a failing module can never undo a saved summary or fail the
  AI job that produced it. The right-hand Case Summary card was covered by #128 in 2.4.1.
- **The case payload carries `executive_summary`.** Case details — what the webhooks module
  sends on every case hook, and `GET /case/meta` — gain an additive, read-only key with the
  executive summary as the card displays it (an analyst's correction over the model text,
  `null` when none was generated). A consumer reads the text from the hook body without a
  second call. Lists of cases fetch the summaries for the whole page in one statement.
- **Hooks fired from a background worker no longer fail silently.** The module dispatcher read
  the signed-in user's name unconditionally; inside a worker there is no signed-in user, so any
  hook fired from worker context (such as the AI worker finishing a summary) raised before it
  reached the module. Such tasks are now attributed to `system`.

## [IRIS-NG-v2.4.5] — 2026-10-02

Two dependency updates in the UI build toolchain, both closing published advisories.
**No schema change** — the database head stays at `f4b8d2e6a913`. **The shipped browser
bundle is byte-identical to 2.4.4**: neither package reaches the browser or the running
server, so this release exists to put the patched lockfile into a tagged image. Nothing to
do on an existing install beyond the normal update.

### Changed
- **brace-expansion 5.0.9 → 5.0.12** (Dependabot alert #152). Closes GHSA-q2hr-2g5m-vwhr
  (quadratic-time `{a},b}` rewrite, CVE-2026-102277) and the two sibling advisories on the
  same version (GHSA-qhr7-859c-m2p7, GHSA-6j4f-fj2g-mc7p — uncontrolled recursion).
  Reached only through `minimatch` under ESLint's config loader: a lint-time
  devDependency. A timing probe of the affected path grew ~3.8× per doubling of the input
  on 5.0.9 and under 2× on 5.0.12.
- **engine.io 6.6.9 → 6.6.11** (Dependabot #136, alert #149). Closes GHSA-2gc4-cqfq-p2gv /
  CVE-2026-102599: an Engine.IO server accepted a transport upgrade carrying a different
  protocol revision than the session had negotiated, and a crafted heartbeat on that
  transport could end the Node process. engine.io is the socket.io *server* half; IRIS
  only vendors the prebuilt browser client out of the socket.io tarball and never runs a
  Node socket server. Verified with a real server per version: 6.6.11 refuses the
  mismatched upgrade with 400 where 6.6.9 accepted it.

Both validated by rebuilding the UI from scratch in `node:24-alpine` with a strict
`npm ci`: 716 output files md5-identical to the previous build, ESLint output identical,
`npm audit` down from 8 high to 6 (the remaining six are the `braces` chain under
Tailwind CSS 3, which needs a major upgrade rather than a bump).

## [IRIS-NG-v2.4.4] — 2026-10-02

War-room timeline entries follow the case timeline's time rule. **One schema change**
(migration `f4b8d2e6a913`, a guarded nullable column) — back the database up before
upgrading, migrations are one-way. **An app image rebuild is required** (the war-room page
script is baked); the nginx and database images are unchanged.

### Added
- **Room timeline entries take a UTC offset and display in UTC.** The entry modal mirrors
  the case event modal: date, time and a `+HH:MM` offset (default `+00:00`). The server
  stores the instant in UTC and remembers the offset you entered; every entry on the room's
  Timelines tab — the room's own and the linked cases' — shows `HH:MM:SS UTC` under UTC day
  separators, with an info hint carrying the local time and offset it was entered in, and
  the editor reopens with exactly what you typed. Before this, the modal had no offset, the
  typed wall-clock was stored and declared UTC, and the card then shifted it to the browser's
  zone, so an entry typed at 14:59 showed as 07:59. The API accepts an aware value (`Z` or
  `+HH:MM`), a plain value plus `event_tz`, or a plain value alone (read as UTC, so existing
  clients are unchanged); changing only the offset of an entry keeps the typed wall-clock and
  moves the instant. Entries saved before this release keep their stored value as UTC.

## [IRIS-NG-v2.4.3] — 2026-10-02

One fix on the Customers page. **No schema change** — the database head stays at
`e3a7c5d9f261`. The fix is Python only: a clone install needs a reset and an app restart;
the release images are rebuilt as always.

### Fixed
- **Customers page: the Details pane showed Sectors "—" for every customer**, even when
  the edit modal showed one. The pane reads the customer's sectors from the per-customer
  detail endpoint (`GET /manage/customers/<id>`), whose column list never included them,
  while the list endpoint and the modal did. The detail payload now carries
  `customer_dhs_sectors` (null when the customer has none) — an additive key, so API clients
  are unaffected. Present since the two-pane Customers page shipped in `IRIS-NG-v2.0.0`.

## [IRIS-NG-v2.4.2] — 2026-10-01

One fix on the Assets page. **No schema change** — the database head stays at
`e3a7c5d9f261`. **An app image rebuild is required**: the fix is a baked page script,
so a clone install that only pulls the source keeps serving the old file until it rebuilds.

### Fixed
- **Assets page: *Save Changes* silently dropped a changed Compromise Status** on any asset
  that already had one. The save helper merged the edit form's values into the update and
  then wrote the asset's existing status back over them — a default meant for the IOC and
  evidence link paths, which send no status. The request succeeded, the list re-read from
  the server and the old value came back, while description, analysis status, IP, domain
  and tags saved normally. Present in every v2 release since `IRIS-NG-v2.0.0`. The existing
  status is now a default only; linking an IOC or evidence item still carries it unchanged.

## [IRIS-NG-v2.4.1] — 2026-10-01

A fix for case summaries that never reached webhooks, guests who can be mentioned, placed in
teams and assigned room tasks, and two security dependency updates. **One schema change**
(migration `e3a7c5d9f261`, guarded add-column / add-table) — back the database up before
upgrading, migrations are one-way. **An image rebuild is required** (Python dependencies and
page scripts moved); the nginx and database images are unchanged.

### Fixed
- **Editing a case Summary now fires `on_postload_case_update`** (#128). The summary route
  committed the new text and returned without calling the module layer, so a webhook — for
  example n8n syncing the case to Jira — only saw a summary change when a later rename, close
  or reopen happened to fire the hook. The hook now fires after the commit, like the
  case-edit, close and reopen paths, and only when the stored text actually changed: the
  Summary editor autosaves and an API client may write the same text back, and an unchanged
  summary has nothing to sync.

### Added
- **Guests can be @-mentioned, placed in teams and assigned room tasks.** Every war-room
  guest carries a per-room `@handle` (minted from the name, unique in the room, editable by a
  lead); the composer's palette offers guests beside members and teams; guests join @-mention
  teams; a room task can be assigned to a guest. Every reach to a guest is an email — a
  mention, a team mention, a task assignment, a leadership SitRep — since a guest has no
  in-app notification feed.

### Dependencies
- **Werkzeug 3.1.9** (security release: `safe_join` device-name guard, stricter Basic-auth
  parsing, the invalid `Range: bytes=-0` suffix rejected with 416, an over-long `int` URL
  value answers 404) and **PyJWT 2.15.0** (security release: a deeply nested token payload
  raises `DecodeError` instead of escaping as a `RecursionError` on the JWKS pre-verification
  path the `oidc_proxy` signature mode uses; OKP key consistency check).
- **axios 1.20.0** in the end-to-end test tooling (a transitive dependency of `wait-on`;
  closes twelve advisories, none reachable outside the test runner).
- **SQLAlchemy stays at 2.0.x.** SQLAlchemy 2.1 installs but the app cannot boot under it:
  SQLAlchemy-Utils has no release that imports against 2.1, and graphene-sqlalchemy's
  unconditional asyncio import needs the `greenlet` package 2.1 no longer installs by default.
  Dependabot now ignores `sqlalchemy >= 2.1.0` until a SQLAlchemy-Utils release supports it.

## [IRIS-NG-v2.4.0] — 2026-09-30

War rooms open to outside participants: guests who are not IRIS-NG users take part in one
room through a guest portal exposed by a Cloudflare tunnel; an ongoing, analyst-editable
operational summary on every room; a one-command update script for clone-based installs;
and a fix for the correlation STIX export. **Four schema changes** (migrations
`a8c3d5e7f912`, `b9d4e6f0a123`, `c1e5f7a2b348`, `d2f6a8c4e957`, all guarded add-table /
add-column) — back the database up before upgrading, migrations are one-way.
**A full image rebuild is required:** the nginx image gains the portal-only server block
and the app image carries new templates, page scripts and resources. The guest portal
stays off until `PORTAL_TUNNEL_AGENT_KEY` is set in `.env` and the tunnel overlay runs;
nothing else changes for an instance that does not use it.

### Added
- **Guests in war rooms, and a guest portal.** A room lead invites an outside participant
  — the affected organisation's incident lead, a partner agency's liaison — by name,
  organisation and email. The guest is never a user account: no login page, no
  permissions, no case access of their own, nothing outside the one room. The credential is
  email + password (a random 16-character one by default, or one the lead sets under the
  instance's password policy; ten failures lock the guest for fifteen minutes; lead-only
  reset); the invitation link opens the sign-in with the email pre-filled, and both are
  shown to the lead once and emailed when SMTP is configured. Expiry (14 days by default),
  extend, new link, revoke and remove; closing the room ends every guest's access. Inside
  the room a guest takes part at responder level on the room's own content — stream,
  polls, room tasks, room notes and folders, SitRep drafts and edits, room timelines and
  events, teams, ICS forms and their PDF export — and **sees every case attached to the
  room read-only** (its timeline events, tasks, note titles and content, activity):
  attaching a case to a room with guests is the sharing decision. Membership, room
  settings, publishing, correlation, exports and every AI feature stay with the analysts.
  Guest-authored content is attributed as "Name (Organisation)" with a `guest` badge.
- **Exposure through a Cloudflare tunnel, and nothing else.** nginx serves a second,
  portal-only server block on `PORTAL_PORT` (default 8081, Docker network only): the
  portal pages, the war-rooms API the portal uses and static assets; everything else,
  including `/login`, answers 404; sign-in and invitation paths are rate-limited; a user
  session or API key arriving through the portal is refused. A tunnel agent container
  (`docker-compose.portal.yml`, `docker/tunnel`) runs `cloudflared` against that port and
  follows **Settings → Guest Portal**: a quick tunnel (testing, no account) or a named
  tunnel from your own Cloudflare account with a write-only token, a public URL, and a live
  status card. Rooms carry a lead-editable slug, so a named tunnel serves
  `rooms.example.com/<slug>`; invitation links are built from the Settings URL, else the
  running tunnel's hostname, else the instance's own address.
- **Operational summary on the war room's Summary tab.** An ongoing AI summary of the
  room's cases at ICS/ESF operational level, in the fixed sections of an ICS 209, with the
  Emergency Support Functions derived on the server from the attached cases' sector tags
  (California's ESF list; ESF 18 Cybersecurity on every room). It refreshes on room events
  (attach, detach, status, SitRep publish, ICS note save) while nobody has edited it, is
  frozen once an analyst edits it, shows a *stale* badge when the room moved on, and can
  be reverted to the AI text. It never reads the SitReps and the SitRep drafter never reads
  it. The room's short export description stays a separate field.
- **`scripts/update.sh`: one-command update for clone-based installs.** Prints the plan
  (commits, migrations, changed images, versions), backs the database up with `pg_dump`
  into `backups/`, resets the checkout (`--ref` for a tag), rebuilds and recreates every
  changed image including nginx, starts the tunnel agent when the key is set
  (`--enable-portal` generates it), and waits for the app's ready line. On an older
  checkout: `git fetch origin && git show origin/main:scripts/update.sh > scripts/update.sh`.

### Fixed
- **Correlation STIX export failed with a 500** on any cluster holding a shared IOC whose
  TLP does not permit redistribution (the withheld-count branch referenced a name it never
  imported). Present since v2.0.0; the export now completes and reports the withheld count
  in `X-IRIS-TLP-Withheld` as documented.
- A guest calling the member-removal route crashed the request; a guest assigning a room
  task hit a comparison against a missing actor id.

## [IRIS-NG-v2.3.0] — 2026-09-27

Two additions to case notes: tags on notes, manual and AI-suggested, and IOC mentions that
become links to the IOC. **One schema change:** the `notes.note_tags` column (migration
`f1c4e7a92b38`, guarded add-column) — back the database up before upgrading, migrations are
one-way. **An image rebuild is required:** three page scripts changed and one is new. Also
in this release: the tag suggester's budget for reasoning models, which was silently empty
for every object type on such a backend.

### Added
- **IOC mentions in notes become links to the IOC**
  ([#130](https://github.com/zach115th/iris-ng/issues/130)). When an IOC extracted from a
  note is added to the case, every mention of it in the note text is rewritten as the
  "Copy MD link" shape with the value as the link text — a tag glyph followed by the value,
  pointing at that IOC on the IOC tab — and the note is saved. Extracted IOCs the case
  already holds get a **link** action instead of "in case" (Accept all links them too), and
  a **Link known IOCs** button beside Extract IOCs does the same for every IOC already on
  the case without calling the model. Defanged spellings in the note (`hxxp`, `[.]`, `(.)`,
  `[dot]`, `[at]`, `[:]`) are recognised and kept as the link text, so the note stays
  defanged; matching is case-insensitive and bounded, so a value inside a longer hostname or
  hash is not a mention; a mention already inside a link, a code span, a fenced block or an
  HTML tag is left alone; longer values win, so a URL links as the URL and the domain inside
  it is not linked again; running it twice changes nothing. Each linked IOC records the note
  as a source (provenance `note_link`, or `ai_extractor` when the link came with the add).
  On the IOC tab a `?shared=<id>` link now selects that indicator and opens its side panel,
  as a row click does, and the legacy edit modal no longer pops on top of it.

- **Tags on case notes, manual and AI-suggested** ([#129](https://github.com/zach115th/iris-ng/issues/129)).
  Every note now carries tags the same way IOCs, assets, tasks and timeline events do: a tag
  input under the note title with the usual autocomplete, saved with the note and on every
  add or remove; each note's tags show as chips in the directory tree, clicking a chip
  filters the tree to notes carrying it, and the notes search box matches tags as well as
  titles and content. The **Suggest tags** pill beside the input asks the AI tag suggester
  with the note's title, folder and text; besides the MISP taxonomy and galaxy catalog it
  may propose any tag already in use elsewhere in the case (its own notes, IOCs, assets,
  tasks, events and the case itself), so a case's labels stay consistent — an invented tag
  is still refused, and nothing is written until a chip is accepted. Tags travel with the
  note into the AI summary and chat payloads, the report (`note.note_tags`) and the case
  export/import. **One additive schema change:** `notes.note_tags` (migration
  `f1c4e7a92b38`). Also fixed on the way: the tag suggester's case-level suggestions never
  excluded the case's existing tags (it read an attribute that does not exist).

## [IRIS-NG-v2.2.1] — 2026-09-26

An AI task suggester on the Tasks page, follow-up question chips in every case chat,
SitRep drafts that describe only what changed, a leadership channel for published SitReps,
and two security dependency updates (moment, urllib3). **No schema change** — the database
head stays at `d6a2f8c47b19` from 2.2.0. **An image rebuild is required:** Python
dependencies moved and the task-suggester panel ships as a static asset in the app image.

### Added
- **AI task suggester.** A sparkle button on the Tasks toolbar opens a review panel of
  tasks the assistant proposes from the case material — existing tasks and their links,
  the notes, timeline, IOCs, assets and evidence, and the skill catalog. The AI only
  proposes: every card is editable, and a task exists only after Accept or Accept all.
  Each accepted task is created through the normal path (activity log, hooks, the
  task-assigned notification), tagged `ai-suggested`, with its dependencies recorded as
  task links. The model never sees an analyst's name: it tags the skills a task needs and
  the server picks the assignee among active users with full access to the case by skill
  overlap, then by fewest open tasks, at the moment the panel is read — so a cached run
  never carries a stale name; with no overlap the task goes to whoever accepts it.
  Duplicates of existing tasks, unknown skills and circular dependencies are dropped
  server-side; a reply that is not the contract (prose, a refusal, the wrong shape) is
  reported as an error and never stored, so it cannot read as "nothing to do". Suggestions
  that have since become tasks are withheld from cached reads, which also report whether
  the case changed since the run. `GET/POST /api/v2/cases/<id>/ai/task-suggestions` and
  `POST .../task-suggestions/accept`; read needs read access, generate and accept need
  full access; no new permission bit.
- **Follow-up question chips in case chat.** Every case-tab assistant (notes, timeline,
  IOC, assets, tasks, evidence and the default) now offers up to three follow-up questions
  under its newest answer, as the same pills as the starter suggestions; one click asks.
  Questions already asked in the conversation are never offered back.
- **Published SitReps reach leadership in full.** Publishing a SitRep now sends the
  members of the room's `@leadership` team (or, without one, the room leads) a new
  notification event, `sitrep_published_leadership`, carrying the full text, with an
  organisation default of in-app plus email; the rest of the room keeps the ordinary
  event with the short teaser. Nobody is told twice, the publisher is not told, and only
  the draft-to-published transition fires it. The notification catalog now lists 13
  events.

### Changed
- **SitRep drafts are deltas.** After a room's first published SitRep, the AI draft
  receives the previous report in full and is asked to write only what changed: no
  re-narration, decisions the material does not show as made carried forward as
  "(still open)", next steps shown as done dropped. The "Delta since SitRep … (vN,
  published …)" reference line is written by the server from the stored report, and the
  server counts draft lines that repeat the previous SitRep verbatim and shows the count
  in the editor's status line so the reviewer knows what to cut. Bullet sections a
  smaller model returns as JSON arrays are rendered one bullet per item instead of as a
  Python list.
- **Case chat answers are no longer cut off by reasoning models.** The chat budget rose
  from 2,000 to 6,000 tokens (a reasoning model spent almost all of 2,000 thinking and
  the visible answer stopped mid-sentence). A reply that still hits the limit is flagged:
  the bubble says so and offers a Continue chip.
- **War-room Notes and SitRep bodies fill the window.** The Notes view and editor and the
  SitRep editor, preview and read view now reach the bottom edge of the window and scroll
  inside, instead of a fixed 16-row box or a card that ended wherever the text did.

### Dependencies
- UI build: moment 2.31.0 — a security release (CVE-2026-17495: a crafted non-string
  value passed to `moment.locale()` could bypass the locale-name validation and load a
  file from an arbitrary path). That code path exists only in the Node build of moment;
  IRIS ships the browser bundle and none of its own code calls moment at all — the global
  is consumed by the vis timeline, the date-time picker and the DataTables date filters,
  whose parse/format calls were verified identical between 2.30.1 and 2.31.0. 2.31.0 also
  stops a prototype-property name such as `constructor` from being honoured as a format
  token and `locale("__proto__")` from blanking the global locale. dropzone 6.3.4 (the
  pipelines upload modal behaves identically — same options, queue, preview and multipart
  fields; the 6.3.2–6.3.4 fixes concern `destroy()` evicting the wrong instance, `cancelUpload`
  on parallel chunks, `emit` skipping a listener that removes itself, and the form
  `enctype` — none of which the modal exercises), autoprefixer 10.6.1, eslint 10.11.0,
  svelte 5.57.1 (with its compiler-side dependencies devalue 5.9.4 — closing an npm audit
  finding, GHSA-9rgm-9g3h-6x36, on a build-time package — esrap, acorn, acorn-typescript,
  sourcemap-codec, @types/node, undici-types; the compiled bundle is byte-identical);
  e2e: @types/node 24.13.6. The built static tree differs from the previous one in exactly
  the vendored moment and dropzone files.
- e2e: dotenv 18.0.1 (major: preloading, `.env.vault` support and the tips are removed and
  a CLI is added). The end-to-end tests only call `dotenv.parse()` on the stack's `.env`,
  which parses identically on 17.4.2 and 18.0.1 — same keys, same values, including quoted,
  `#`-bearing, `export`-prefixed and multi-line entries. The e2e job is disabled in CI, so
  nothing installable changes.
- Python: urllib3 2.8.0 — a security release closing three advisories against 2.7.0: the
  TLS settings meant for an HTTPS forwarding proxy could be ignored or replaced by the
  target server's (GHSA-8988-9cw3-xx77), the streaming reader buffered an unbounded
  chunk-size line from a malicious server (GHSA-vxq7-64xx-v4gw), and a chunked Deflate
  body with trailing bytes could loop forever (GHSA-gh4c-6fx4-qh6g). IRIS reaches urllib3
  through `requests` for the MISP modules, the AI backends, the update check and the
  sponsor tab; the first needs an HTTPS proxy configured in Server settings, the other two
  need a hostile server at one of those configured endpoints. Buffered and streamed
  responses (gzip and deflate, chunked) read back identically before and after. Also
  SQLAlchemy 2.0.54 (2.0.53 fixes for `aliased()` on an existing alias, chained
  `CTE.alias()`, a mapped-class memory leak, unclosed connections when a pool connect
  event raises, and the PostgreSQL schema-exclusion query treating `_` as a wildcard;
  2.0.54 is packaging only) — boot, migrations, the ORM read paths, a create-and-delete
  case round and the RETURNING-backed bulk update all behave identically; and pypdf 6.19.0
  (four more crafted-PDF resource-exhaustion advisories, unreachable because IRIS only
  opens its own bundled FEMA forms; all seven ICS exports read back field-for-field
  identical and slightly smaller).
- Python: pymisp 2.5.34.4 — one line in the optional `FileObject` helper (a new argument
  to the `pure-magic-rs` buffer scan) and raised floors on three optional extras; the API
  client module is byte-identical to 2.5.34.3 and the bundled MISP module only constructs
  the client and searches attributes. Core dependency floors unchanged.

## [IRIS-NG-v2.2.0] — 2026-09-18

The full ICS packet with official FEMA PDF export, IOC deduplication, @mention
completion on every comment box, default war-room teams, and pypdf. **One schema
change:** the `war_room_team_template` table (migration `d6a2f8c47b19`, guarded create —
back the database up before upgrading, migrations are one-way). **An image rebuild is
required:** pypdf is a new dependency and the mention palette ships as a static asset in
the built app image.

### Added
- **The full ICS packet for a cyber incident, exported as the official FEMA forms.** War
  rooms now seed seven Incident Command System forms on the first case attach instead of
  three — ICS 201 Incident Briefing, 202 Incident Objectives, 203 Organization Assignment
  List, and new **204 Assignment List**, **205A Communications List**, **209 Incident Status
  Summary** and **214 Activity Log** — the set an emergency-management reporting chain
  expects from an incident. The new forms are prefilled from what the room knows: 204
  from the responders (one resource per person, account e-mail as contact) and the open
  room and case tasks as work assignments; 205A as an alphabetized contact list of the
  members with their ICS position; 209 with the incident number, start date, a
  server-computed scope line (cases, assets, IOCs, evidence, timeline events), the case
  classifications as the incident definition, the customers as the affected area, and
  the team headcount; 214 with the members as resources and the room stream (messages,
  decisions, cases attached, members added, tasks, SitReps) as the activity log up to
  seed time. A room seeded before a form existed gets the missing ones on its next seed;
  existing notes are never touched. **Every ICS note now downloads as the filled official
  FEMA PDF** (a download button on the note; read access) — the bundled forms are FEMA's
  own fillable files, so the output is the real form, not a look-alike. The note's block
  numbers were aligned to FEMA's (the 201 gained "2. Incident Number" and its remaining
  blocks moved down by one) so each section maps onto the block with that number; notes
  seeded under the old numbering still export by their headings. The export fills what
  fits, prints no placeholder dashes, drops FEMA's instruction pages, leaves signatures
  for a pen, transliterates the few symbols the forms' font lacks, and tells you what it
  could not carry: rows that did not fit, AI-drafted fields nobody has reviewed yet, and
  any section you added that has no block on the form. Two ICS 209 blocks (38, 39) share
  a single field in FEMA's file and are carried in block 47 Remarks instead.
  `GET /api/v2/war-rooms/<id>/notes/room/<note_id>/ics-pdf` (`?format=json` for the field
  values and the report). New dependency: pypdf.
- **AI pass extended to the 204 and 209.** Work assignments and special instructions on
  the 204; incident definition, significant events, projected activity and threat
  summary per horizon, strategic objectives, critical resource needs, strategic
  discussion and planned actions on the 209 — same rules as before: only empty fields,
  every fill marked. The 205A contact list and the 214 activity log are records and are
  never drafted.
- **@mention autocomplete on every comment box (#120).** Typing `@` in a comment on an
  asset, IOC, evidence item, task, note, timeline event, alert or alert cluster now opens
  the same completion palette the war-room composer has: users who can see the object
  (case access for case objects, deny-all rows excluded), by login with the display name
  beside it; arrows to move, Tab or Enter to complete, Escape to dismiss, and while it is
  open Enter completes instead of posting. It works in the side-panel inputs and in the
  legacy comment modal's editor. Mentions resolve against the **login** (a typed display
  name notifies nobody), which is exactly the gap the palette closes. Rendered comments
  and war-room messages now highlight the mentions that resolved, so a plain `@name`
  visibly means nobody was notified.
- **Default war-room teams (#115).** Settings → War Room Teams lets administrators define
  the @-mention teams every room should start with — `@leadership`, `@dfir`, `@cti` — with
  a description, a colour, an order and an enabled switch. Every **new** war room (created
  or promoted from a correlation cluster) is seeded with one empty team per enabled
  template; the room's lead adds the people. Existing rooms are not changed, and a seeded
  team is an ordinary room team afterwards. New table `war_room_team_template` (migration
  `d6a2f8c47b19`).
- **IOC deduplication (#83).** *Find duplicates* in the IOC page's ⋮ menu scans the case:
  **exact** duplicates (same type and the same value after trimming, refanging `hxxp`,
  `[.]`, `[at]` and the like, and case-folding) are grouped with the first entry as the
  survivor and can be collapsed in one click; **near** candidates (a URL whose host is
  another indicator, `host:port` beside `host`, the same value under two types, close
  spellings within a type) are listed for review with Keep left / Merge / Keep right /
  Keep both; and **Run AI pass** asks the configured model to judge the whole list and
  appends its proposals with a confidence and a one-line reason, advisory only. A keep and
  a merge both carry the removed row's links — assets, timeline events, note provenance,
  alert association, comments, and the MISP attribute link when the survivor has none —
  onto the survivor, so nothing is orphaned; a merge also unions the tags and appends a
  differing description; the survivor's history records what was folded in. The same
  rule now holds at ingestion: a CSV import reports and skips a row the case already holds,
  and escalating an alert links the case's existing indicator instead of minting a second
  one. `POST /api/v2/cases/<id>/iocs/dedup/{scan,auto-exact,resolve,ai-scan}`.

### Changed
- **Mentions reach the mailbox by default.** The organisation default for the *You are
  mentioned* event is now in-app **and** email; an existing install gains it on its next
  boot unless an administrator has already saved the Notifications matrix (an explicit
  choice is never overwritten). Email still needs *Email notifications* enabled and SMTP
  configured on the Mail tab, and a personal override on the profile page still wins.

### Dependencies

- Python: pypdf 6.10.2 → 6.16.1. Twelve pypdf security advisories close along the
  way, all of the crafted-PDF denial-of-service class (unbounded loops or memory on
  malformed outlines, inline images, cross-reference tables, font tables and XForm
  objects). IRIS opens pypdf only on its own bundled FEMA forms, never on an uploaded
  file, so none of them was reachable here. What does change for the ICS export: the
  filled forms are smaller (the 214 by up to 14%) because appending pages no longer
  clones whole field hierarchies, and the em-dashes in the 202's attachment list no
  longer trigger the library's "characters not supported by font encoding" warning.
  Field values, page counts and every field read back were verified identical across
  all seven forms.

## [IRIS-NG-v2.1.1] — 2026-09-17

Incident Command System forms in war rooms, and a PyJWT security update. No
schema change: the database head is unchanged from v2.0.0 and no migration
runs on upgrade. An image rebuild is required — the dependency updates and
the ICS notes rail live in the built image.

### Added
- **ICS forms seeded into war rooms.** When the first case is attached to a room, three
  room notes are created in an "ICS" folder from bundled Incident Command System
  templates — ICS 201 Incident Briefing, ICS 202 Incident Objectives and ICS 203
  Organization Assignment List — prefilled with what the room already knows: incident
  name, date/time, the attached cases (customer, severity, state, opened, owner), the
  lead as Incident Commander, and the members with their room roles. One set per room;
  a later attach adds nothing and never edits a seeded note. A "Seed ICS forms" button
  on the Notes tab adds any form that is missing (deleted, or a room that predates this)
  and leaves existing ones alone. `GET/POST /api/v2/war-rooms/<id>/notes/ics[/seed]`.
- **AI pass over the ICS forms.** After the seed, a second pass proposes text for the
  fields still marked `—` from the attached cases' material (descriptions, cached
  executive summaries, tasks, recent activity): the ICS 201 situation summary, objectives,
  actions and resources; the ICS 202 objectives, command emphasis and site-safety answer;
  and ICS 203 positions, which may only name room members or case owners (the lead is
  already Incident Commander; one person, one position). It fills only empty fields, never
  rewrites anything the seed or an analyst wrote, and marks every fill — a header line on
  the note lists what the AI filled and each filled field carries an "AI draft" line to
  delete once reviewed. Runs automatically after the seed when an AI backend is
  configured and on demand from the Notes rail; a failed call changes nothing.
  `POST /api/v2/war-rooms/<id>/notes/ics/ai-draft` (202 + job id, `?sync=true` inline).

### Fixed
- **Hayabusa CSV import of a full-host run (#119).** A Hayabusa 4.x `dfir-timeline`
  export over a whole host is a multi-hundred-megabyte CSV, and the upload died at the
  reverse proxy's 100 MB body limit with a bare `413` before the app read a single row —
  which read like a format problem. The column layout is unchanged between 3.x and 4.x,
  and both parse identically. Fixed on three fronts: the working-timeline import routes
  now accept any body size with the same ten-minute timeouts as the other upload paths
  (nginx image rebuild required); the parser streams the upload instead of decoding it
  into one string, grouping fan-out rows as they arrive; and the import modal gained a
  **severity filter** — critical / high / medium / low / info checkboxes, info off by
  default because it is over 99% of a full-host run — applied per event (a card keeps
  every rule that fired on it and is dropped only when its highest level is unticked),
  together with the date window, ahead of a 25,000-event cap matching the EZ Tools
  import. The result message names what was skipped by level, by date, and whether the
  cap stopped the import. Also: the channel table now mirrors Hayabusa's own
  abbreviations (`RDS-LSM`, `BitsCli`, `MS-Win-…/Op` and kin) while still accepting the
  older spellings, so the Event Source of a promoted event reads as the Windows log name;
  and the modal names the 4.x command (`dfir-timeline -t csv`, `--utc`) beside the 3.x one.
  API: `POST …/working-timeline/import/hayabusa` accepts `levels` (comma-separated) and
  returns `skipped_by_level`, `truncated`, `cap`, `levels` and `rows_read`.

### Dependencies

- UI build: dropzone 6.3.1 (the pipelines upload modal behaves identically —
  same options, queue, preview and multipart fields), marked 18.0.13 (CommonMark
  conformance fixes: empty fenced code blocks, leading whitespace after a hard line
  break, a tab before a closing `#`, character references in autolink destinations,
  and email autolinks no longer truncate an address whose domain ends in `_` or `-`;
  the structured-note format renders unchanged), vite 8.3.0, autoprefixer 10.6.0,
  postcss 8.5.28; e2e: @types/node 24.13.4.
- Python: PyJWT 2.14.0 — a security release closing thirteen advisories against 2.13.0
  (HMAC-key validation against public-key material in every encoding, JWKS fetches no
  longer follow redirects, JWKS refreshes throttled on unknown key ids, malformed or
  deeply nested JWS/JWK input handled without aborting, compact-encoding rules enforced).
  IRIS reaches this code only in the `oidc_proxy` authentication mode with signature
  verification, where the incoming token is parsed before the user is authenticated;
  local, LDAP and OIDC sessions never touch it. Also alembic 1.20.0 (SQLAlchemy 2.0 now
  the minimum, which this tree already pins; its other changes concern batch mode and
  autogenerate, neither used at boot) and psycopg2-binary 2.9.13 (malformed bytea and
  int64-array input parsing, Python 3.15 wheels).
- Python: pymisp 2.5.34.3 — several feed-cache and server-sync client calls switched from
  GET to POST to match MISP; the bundled MISP module only searches attributes, so its
  behaviour is unchanged. Dependency floors identical to 2.5.34.2.

## [IRIS-NG-v2.1.0] — 2026-09-15

A release-availability banner, customer search on the drive inventory, two
access-control repairs that together retire the "give everyone case #1"
workaround, and the removal of light mode. No schema change: the database
head is unchanged from v2.0.0 and no migration runs on upgrade. An image
rebuild is required — the banner, the switcher fix and the theme removal
ship in baked static JS.

### Removed
- **Light mode (#92).** Dark is now the only theme. The IRIS Theme toggle is gone from the
  profile page, every layout loads the dark stylesheet unconditionally (including the
  access-denied and other centered pages, which previously rendered light for anonymous
  sessions), editors and graph labels no longer switch on the per-user flag, and the
  theme endpoint refuses `light`. Also removed on the way: a script tag for a
  `dark-mode.js` that never existed, and a stray debug print of the theme flag in the
  note editor modal.

### Fixed
- **New users landed on an access-denied page for a case they were never given.** The
  session's starting case was the lowest id in the database (usually #1), chosen with no
  access check, so anyone without that case hit the access-denied page on their first
  case-scoped click. The context is now seeded with the lowest case the user can actually
  access; a user with no case access lands on Home instead. This removes the need to grant
  everyone access to case #1.
- **Case switcher failed with a CSRF error on pages that render no form.** A user
  whose context was a case they cannot read (most often the default #1) landed on the
  access-denied page, where the case switcher — the only way out — returned "Invalid
  CSRF token". The switch modal now carries its own session token, so switching works
  on the access-denied page, `/manage/cases` and `/manage/metrics` as well as everywhere
  else. The CSRF guard and case-access check are unchanged (a bad token still 400s,
  switching into an inaccessible case still 404s).

### Added
- **Update banner (#111).** When a newer release exists on GitHub, a strip at the top of
  every page except Home says so (Home's strip stays reserved for admin announcements).
  Everyone sees the notice and can hide it for their browser until the next release;
  server administrators also get the release link and a "How to upgrade" panel with the
  clone-based commands and the release notes. The sidebar version line gains a small
  update icon. Backed by `GET /api/v2/updates/latest` (cached in-process for 6 hours,
  honours the configured proxies, never raises).
- **Settings → System → Updates:** "Check for new releases" toggle (on by default; turn
  it off for air-gapped deployments) and a "Check now" button.
- **Inventory search by customer (#106).** The scan bar's search mode also matches the
  case's customer name, over the same two relations as the case search (the drive's
  assigned case, and cases whose evidence is stored on the drive), so a customer search
  lists every drive holding anything of that customer. Matches, the result card, the
  drive-inventory cards and the drive detail now name the customer beside the case, and
  the drive list's own search box matches it too. Additive `case.client_name` /
  `case.client_id` on lookup matches and `client_name` on `GET /inventory/drives`.

### Changed
- `RELEASE_URL` now defaults to this project's releases feed; the inherited default
  compared the running version against another project's releases.

## [IRIS-NG-v2.0.2] — 2026-09-10

Three analyst-facing improvements, a repair to a modal that had never worked,
and a dependency refresh. No schema change: the database head is unchanged
from v2.0.0 and no migration runs on upgrade. An image rebuild is required —
the UI work ships in baked static JS and three Python packages moved.

### Added

- **Drive inventory searches by case, not just bar code.** The scan bar's
  lookup now also matches a case name, case number (`19` or `#19`) or SOC id,
  covering both the drive's assigned case and any case whose evidence items
  are stored on the drive. A term that is both a bar code and a case number
  returns both results, labelled apart, rather than one silently shadowing the
  other; a capped case list says so. The historical `barcode=` lookup is
  untouched for its existing consumers. (#97)
- **Collapsible days on both timelines.** Every date pill on the master
  timeline and the working panel toggles its day's events, with an explicit
  "N hidden" count, Collapse all / Expand all in the header menu, and the
  folded state remembered per case. A deep link into a folded day still opens
  it on first sight. (#105)
- **Shared IOCs on the correlation workspace are cards.** The `/correlation`
  Shared IOCs table became a two-pane master/detail view matching the rest of
  the platform, and the war-room Correlation tab renders the same cards from
  one shared renderer; the legacy table stays reachable behind a toggle.

### Fixed

- **The Processing pipelines modal's upload zone now loads.** The modal has
  always referenced `plugin/dropzone/dropzone.js` while the build only ever
  emitted `dropzone.min.js`, so its script tag returned 404 and the upload
  zone never initialised. The build now ships the file under both names.
- Timeline day folding survived three layout traps found after the first
  cut: a page-level `!important` rule that defeated the inline hide, a stale
  deep-link hash that pinned a day open, and a framework badge rule that
  pushed the folded pill to the right edge of the page.

### Dependencies

- UI build: dropzone 6.2.0 (major — its browser build moved, and the copy
  target moved with it), vite 8.2.2, eslint 10.10.0, globals 17.12.0,
  autoprefixer 10.5.5; e2e: @playwright/test 1.63.0, joi 18.2.8.
- Python: Flask-Caching 2.5.1, alembic 1.19.2, pymisp 2.5.34.2 (drops its
  `jsonschema` and `publicsuffixlist` dependencies; the bundled MISP module's
  call surface is unchanged).

## [IRIS-NG-v2.0.1] — 2026-09-04

A security-hardening release: the full triage of the CodeQL scan that ran against
the v2.0.0 promotion — thirteen alerts assessed, fixed and verified, none of them
exploitable as shipped but every flagged flow now closed by construction. No
schema change; the database head is unchanged from v2.0.0 and no migration runs
on upgrade. An image rebuild is required (several fixes are in baked static JS).

### Security

- **Rule condition regexes are gated against catastrophic backtracking.** The
  512-character pattern cap bounded size, not the engine: a short compilable
  pattern like `(a+)+b` could still stall the synchronous alert-ingest pipeline
  or the mail poller. A shared `is_safe_regex()` gate now rejects the classic
  ReDoS primitives (backreferences, lookarounds, and repeated groups whose body
  carries alternation or a quantifier) while passing every legitimate rule
  shape, enforced at save time (named validation errors for clustering rules,
  investigation flows and mail rules), at evaluation time (fail closed), and on
  the mail-rules dry-run endpoint, whose ad-hoc conditions previously skipped
  validation entirely.
- **The war-room Discovery panel builds its cluster cards as DOM, not an
  innerHTML template.** Values from the correlation report (shared-IOC counts,
  room ids, case ids in links) were interpolated with only partial escaping;
  the cards are now constructed with `createElement`/`textContent` and every id
  that lands in a link is validated.
- **The notification bell allowlists row URLs before navigating.** The stored
  notification URL rides a free-form column into `location.href`; only
  same-origin http(s) URLs are followed now, so a poisoned row can never become
  `javascript:` navigation.
- **Every id read from the DOM or a fetched payload is validated and re-derived
  before reaching a URL or HTML sink** across the war-room pages, alert
  clusters, the case shell header, the report-templates view, the customer-asset
  registry (list, sightings, filters and CSV export) and the case
  asset/IOC/evidence detail pages.

### Fixed

- The mail-rules dry-run endpoint now rejects an invalid or dangerous regex
  with a named error instead of silently reporting "no match" — a test that
  passes can no longer behave differently once the rule is saved.

## [IRIS-NG-v2.0.0] — 2026-09-04

The first release of the v2 line, and the largest since the fork. Six feature
areas land together — mail ingestion, alert clustering, investigation flows, a
customer-asset registry, notifications, and war rooms — alongside a redesigned
analyst UI across every case tab and the whole settings family, and a set of
long-standing inherited defects fixed along the way. This is the preview that
ran on the `dev` branch through September, now the mainline.

### Upgrading — read this before you pull

- **The migration is one-way.** 24 schema migrations apply on first boot (new
  Alembic head `f8b3c62d94a7`); once they have run, the database can no longer
  boot a 1.4.x image. Take a `pg_dump` first — it is the only road back. The
  jump from v1.4.1 was rehearsed against a copy of a production database:
  everything applies in one boot and every pre-existing row survives.
- **An image rebuild is mandatory** (`up -d --build --force-recreate`). Python
  and UI dependencies changed (gunicorn 26.2.0, Flask-Caching 2.5.0, marked
  18.0.11, eslint 10.9.1, svelte 5.57.0, cryptography ≥ 50.0.1) and the static
  assets baked into the image changed substantially.
- The API remains compatible with v2.5.0-beta.1 clients; every schema change is
  additive.

### Added

- **Mail rules with AI triage.** IMAP polling (standard library only, a fixed
  60-second self-gating tick), a regex/field rule engine that fails closed, a
  full ingest log, and advisory AI triage that refines severity and
  classification against the live catalogs. Mail passwords are write-only end
  to end — the API never returns them.
- **Alert clusters and clustering rules.** Rule-driven fingerprinting groups
  related alerts into clusters (one open cluster per fingerprint, enforced in
  the database), with an AI-drafted narrative, derived severity with an analyst
  override, and a full triage workspace: summary doc, member management,
  assets, IOCs, correlation graph, timeline and an activity feed. Escalation
  drives the existing case-creation and merge paths.
- **Investigation flows.** Condition-matched checklists attach to alerts and
  clusters at ingest; step states are analyst-owned, required steps are
  computed server-side, and flow edits merge by step so completed work
  survives a rename or reorder.
- **Customer-asset registry.** An org-wide, automatically-maintained registry
  of every asset seen per customer — synced from case work and alert ingest,
  never blocking either — with sightings, compromise curation that sync can
  never overwrite, CSV import, and per-asset detail live-derived from the
  newest case observation.
- **Notifications, home and following.** In-app + optional email notifications
  across a 12-event catalog with per-user and org-default channel matrices, a
  notification bell in both navs, @-mentions in every comment surface, follow
  buttons on cases and alerts, and a new `/home` landing page with your open
  work at a glance.
- **War rooms.** Cross-case coordination spaces: a chat stream with threads,
  topics, pins, polls, slash commands and @-mention autocomplete; a task board
  with subtasks; room-level timelines beside read-only case timelines; notes
  with folders; SitReps with revisions, publishing, exports and AI-drafted
  skeletons; attached-case peeks bounded by each viewer's case access; members
  and mention-teams. Room membership never grants case access, and outbound
  STIX/MISP publishing applies the same TLP gates as everywhere else.
- **The correlation workspace moved to `/correlation`** (sidebar: Intel), with
  the per-IOC context drawer shared into war rooms. The correlation engine and
  every `/api/v2/correlation/*` endpoint are unchanged.
- **A settings shell.** The Advanced submenu became a Manage IRIS rail;
  Modules, Custom Attributes, Case Templates, Report Templates, Case Objects
  and Customers were rebuilt as two-pane pages over their existing endpoints;
  a sector catalog now drives the sector pickers and metrics; and admins can
  post dismissible announcement banners.
- **A redesigned case UI.** An in-page case header on all eight tabs with
  interactive state/severity chips and quick actions; master/detail views on
  the Assets, IOCs, Tasks and Evidence tabs with inline editing, linked-object
  tabs, comments and CSV round-trips; four task views including a kanban
  board; cached AI profiles for assets and IOCs; and the datastore reshaped
  into a compact drawer. Every rebuild overlays the existing endpoints and
  modals — the legacy views stay reachable behind a toggle.
- **In-tree VirusTotal and MISP modules** (VirusTotal API v3; lean report
  defaults), so a fresh install carries working enrichment without hunting for
  module wheels.

### Fixed

All of these were present in released 1.4.x images; several are worth an
upgrade on their own:

- **A zero-access account could read the whole organisation's correlation data**
  — an empty case-access list was treated as "no restriction" on the
  correlation endpoints, and the same hole allowed tagging arbitrary cases.
  Empty now means nothing is visible.
- **A crafted `cid` URL parameter executed script** (DOM XSS) on two pages
  that interpolated it into markup unvalidated. It is now validated
  digits-only at the single place each page reads it.
- **No customer created through the UI was ever deletable** — creation granted
  the creator an access row, and deletion misread the resulting foreign-key
  violation as "customer is referenced". Access rows are now cleared in the
  same transaction; genuine references still block deletion.
- **Escalating alerts without a case template crashed**; escalating an
  untagged alert minted an empty tag row; and **a case escalated from an alert
  with imported IOCs could not be deleted** while the alert existed.
- **The Backup database button did nothing** — a form control's id shadowed
  the global function its inline handler named. Its error path was also broken
  since the original import.
- **Object-valued table columns (IOC Type/TLP/linked cases, asset analysis
  status) were unfilterable and unsortable.**
- **The timeline's analysis and working-timeline panels now reclaim the space
  the case banner frees as you scroll**, instead of floating at a fixed offset.
- Page loads got faster: HTTP/2 + gzip at nginx, a minimal ACE build, lazy
  html2canvas, and de-duplicated fetches on the case pages.

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

[IRIS-NG-v2.3.0]: https://github.com/zach115th/iris-ng/releases/tag/IRIS-NG-v2.3.0
[IRIS-NG-v2.2.1]: https://github.com/zach115th/iris-ng/releases/tag/IRIS-NG-v2.2.1
[IRIS-NG-v2.2.0]: https://github.com/zach115th/iris-ng/releases/tag/IRIS-NG-v2.2.0
[Unreleased]: https://github.com/zach115th/iris-ng/compare/v2.5.0-beta.1+iris-next.3...HEAD
[v2.5.0-beta.1+iris-next.3]: https://github.com/zach115th/iris-ng/releases/tag/v2.5.0-beta.1%2Biris-next.3
[v2.5.0-beta.1+iris-next.2]: https://github.com/zach115th/iris-ng/releases/tag/v2.5.0-beta.1%2Biris-next.2
[v2.5.0-beta.1+iris-next.1]: https://github.com/zach115th/iris-ng/releases/tag/v2.5.0-beta.1%2Biris-next.1
[v2.5.0-beta.1+iris-next.0]: https://github.com/zach115th/iris-ng/releases/tag/v2.5.0-beta.1%2Biris-next.0
[baseline-v2.5.0-beta.1]: https://github.com/dfir-iris/iris-web/releases/tag/v2.5.0-beta.1

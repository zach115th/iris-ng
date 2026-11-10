/* Vulnerability catalogue: shared widgets (iris-ng 2026-11-07).
 *
 * window.IrisVuln - import-free (ui/public: Vite never tree-shakes it), used by
 * the catalogue and detail pages (vulnerabilities.js), a case asset's
 * Vulnerabilities tab (Assets page and asset editor), Customer Assets and war
 * rooms. A case finding always names its asset - there is no case-wide finding.
 *
 *   IrisVuln.openVulnForm({vuln, onSaved})          new / edit catalogue entry (+ cve.org fill)
 *   IrisVuln.openMerge({vuln, onMerged})            merge into another entry (admins)
 *   IrisVuln.openFindingForm({...})                 record / edit a finding
 *   IrisVuln.mountFindings(el, {...})               findings table for a case, an asset or a registry entry
 *   IrisVuln.mountWarRoom(el, {roomId, canWrite})   tracked entries + the room's matrix
 *
 * Every value from the server goes through esc() before an .html() build;
 * ids through id() (digits only); links only for http(s) references. POST
 * bodies carry csrf_token (the v2 rule); PUT / PATCH / DELETE are exempt.
 */
(function () {
    'use strict';
    if (window.IrisVuln) { return; }
    var V = {};
    /* The (i) help icons (help_tips.js); a page without the help assets gets none. Calls stay
       literal - IrisHelp.icon('vuln.kind') - so scripts/_help_glossary_check.py sees every key. */
    var IrisHelp = window.IrisHelp || {icon: function () { return ''; }};
    var API = '/api/v2/manage/vulnerabilities';

    /* ------------------------------------------------------------ utils */
    V.esc = function (s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    };
    V.id = function (v) {
        var s = String(v == null ? '' : v);
        return /^\d+$/.test(s) ? String(parseInt(s, 10)) : null;
    };
    V.csrf = function () {
        var el = document.getElementById('csrf_token') || document.querySelector('input[name="csrf_token"]');
        return el ? el.value : '';
    };
    V.fetch = function (path, method, body) {
        var opts = {method: method || 'GET', headers: {'Content-Type': 'application/json'},
                    credentials: 'same-origin'};
        if (body !== undefined) {
            body = Object.assign({}, body);
            if ((method || 'GET') === 'POST') { body.csrf_token = V.csrf(); }
            opts.body = JSON.stringify(body);
        }
        return fetch(path, opts).then(function (r) {
            if (r.status === 204) { return {__status: 204}; }
            return r.json().then(function (j) {
                j = (j && typeof j === 'object' && !Array.isArray(j)) ? j : {value: j};
                j.__status = r.status;
                return j;
            }).catch(function () { return {__status: r.status}; });
        });
    };
    V.ok = function (j) { return j && j.__status >= 200 && j.__status < 300; };
    V.errText = function (j, fallback) {
        if (!j) { return fallback || 'The request failed.'; }
        if (j.message) { return j.message; }
        if (j.data && j.data.message) { return j.data.message; }
        if (j.__status === 403 || j.__status === 401) { return 'You are not allowed to do this.'; }
        if (j.__status === 404) { return 'Not found (or not visible to you).'; }
        return fallback || ('The request failed (HTTP ' + j.__status + ').');
    };
    V.fmtDate = function (iso) {
        if (!iso) { return '—'; }
        var m = /^(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}))?/.exec(String(iso));
        return m ? (m[1] + (m[2] ? ' ' + m[2] + ' UTC' : '')) : V.esc(iso);
    };
    V.pct = function (f) {
        if (f == null || f === '') { return '—'; }
        var p = Number(f) * 100;
        return (p < 1 ? p.toFixed(2) : p.toFixed(1)) + '%';
    };
    V.score = function (s) { return (s == null || s === '') ? '—' : Number(s).toFixed(1); };
    V.isCve = function (s) { return /^cve-\d{4}-\d{4,}$/i.test(String(s || '').trim()); };
    V.safeUrl = function (u) { return /^https?:\/\/[^\s"'<>]+$/i.test(String(u || '')) ? String(u) : null; };

    var vocabPromise = null;
    V.vocab = function () {
        if (!vocabPromise) {
            vocabPromise = V.fetch(API + '/vocab').then(function (j) {
                if (!V.ok(j)) { vocabPromise = null; throw new Error(V.errText(j, 'Could not load the vocabularies.')); }
                var m = function (list) { var o = {}; (list || []).forEach(function (x) { o[x.value] = x.label; }); return o; };
                j.L = {
                    kind: m(j.kinds), severity: m(j.severities), exploit: m(j.exploit_maturities),
                    patch: m(j.patch_availabilities), exploitation: m(j.exploitation_statuses),
                    vex: m(j.vex_justifications), remediation: {}, group: {}
                };
                (j.remediation_groups || []).forEach(function (g) {
                    g.statuses.forEach(function (s) { j.L.remediation[s.value] = s.label; j.L.group[s.value] = g.group; });
                });
                return j;
            });
        }
        return vocabPromise;
    };

    /* ------------------------------------------------------------ styles */
    V.css = function () {
        if (document.getElementById('iris-vu-css')) { return; }
        var st = document.createElement('style');
        st.id = 'iris-vu-css';
        st.textContent = [
            '.iris-vu-pill{display:inline-block;border-radius:10px;padding:1px 9px;font-size:.74rem;white-space:nowrap;line-height:1.5;}',
            '.iris-vu-mono{font-family:SFMono-Regular,Menlo,Consolas,monospace;}',
            '.iris-vu-sev-critical{background:rgba(245,54,92,.22);color:#ff8095;}',
            '.iris-vu-sev-high{background:rgba(251,99,64,.20);color:#ffa07f;}',
            '.iris-vu-sev-medium{background:rgba(244,196,48,.16);color:#f4c430;}',
            '.iris-vu-sev-low{background:rgba(54,162,235,.18);color:#7cc0f5;}',
            '.iris-vu-sev-none,.iris-vu-sev-unknown{background:rgba(255,255,255,.07);color:#9a9aa5;}',
            '.iris-vu-kev{background:#b91c1c;color:#fee2e2;font-weight:600;}',
            '.iris-vu-priv{border:1px solid rgba(255,255,255,.18);color:#9a9aa5;font-size:.66rem;padding:0 6px;}',
            '.iris-vu-kind{border:1px solid rgba(255,255,255,.18);color:#d6d6de;}',
            '.iris-vu-st-open{background:rgba(245,158,11,.18);color:#fbbf24;}',
            '.iris-vu-st-fixed{background:rgba(45,206,137,.16);color:#2dce89;}',
            '.iris-vu-st-dismissed{background:rgba(255,255,255,.08);color:#a8a8b3;}',
            '.iris-vu-ex-unknown{background:rgba(255,255,255,.07);color:#9a9aa5;}',
            '.iris-vu-ex-not-exploited{background:rgba(45,206,137,.16);color:#2dce89;}',
            '.iris-vu-ex-attempted{background:rgba(244,196,48,.16);color:#f4c430;}',
            '.iris-vu-ex-suspected{background:rgba(251,99,64,.20);color:#ffa07f;}',
            '.iris-vu-ex-exploited{background:rgba(245,54,92,.22);color:#ff8095;}',
            '.iris-vu-muted{color:#9a9aa5;}',
            '.iris-vu-small{font-size:.76rem;}',
            '.iris-vu-overdue{color:#ff8095;font-weight:600;}',
            '.iris-vu-table td,.iris-vu-table th{vertical-align:middle;padding:.45rem .6rem !important;font-size:.82rem;}',
            '.iris-vu-table th{color:#9a9aa5;font-weight:600;white-space:nowrap;}',
            '.iris-vu-table tr.iris-vu-row{cursor:pointer;}',
            '.iris-vu-table tr.iris-vu-row:hover td{background:rgba(255,255,255,.03);}',
            '.iris-vu-chip{display:inline-block;border-radius:8px;padding:2px 10px;margin:0 6px 6px 0;font-size:.76rem;' +
                'background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);}',
            '.iris-vu-chip b{font-weight:700;margin-right:4px;}',
            '.iris-vu-fieldset{border:1px solid rgba(255,255,255,.1);border-radius:6px;padding:10px 12px 4px;margin-bottom:12px;}',
            '.iris-vu-legend{font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;color:#9a9aa5;width:auto;padding:0 6px;margin:0;}',
            '.iris-vu-pick{max-height:210px;overflow-y:auto;border:1px solid rgba(255,255,255,.1);border-radius:6px;}',
            '.iris-vu-pick button{display:flex;width:100%;align-items:center;gap:8px;border:0;border-bottom:1px solid rgba(255,255,255,.06);' +
                'background:transparent;color:inherit;text-align:left;padding:6px 10px;font-size:.8rem;}',
            '.iris-vu-pick button:hover,.iris-vu-pick button:focus{background:rgba(255,255,255,.06);}',
            '.iris-vu-card{border:1px solid rgba(255,255,255,.12);border-radius:6px;padding:8px 10px;background:rgba(255,255,255,.03);}',
            '.iris-vu-err{color:#ff8095;font-size:.8rem;}',
            '.iris-vu-req{color:#ff8095;}',
            '.iris-vu-toolbar .btn.active{background:rgba(139,92,246,.25);color:#d4c4ff;border-color:rgba(139,92,246,.5);}',
            '.iris-vu-kv{display:flex;margin-bottom:5px;font-size:.82rem;}',
            '.iris-vu-kv .k{flex:0 0 38%;color:#9a9aa5;}',
            '.iris-vu-kv .v{flex:1 1 auto;min-width:0;overflow-wrap:anywhere;}',
            '.iris-vu-sec{font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:#9a9aa5;margin:14px 0 6px;}',
            '.iris-vu-desc{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.86rem;}',
            '.iris-vu-matrix td.iris-vu-cell{text-align:center;}'
        ].join('\n');
        document.head.appendChild(st);
    };

    /* ------------------------------------------------------------ badges */
    var SEV_LABEL = {critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low', none: 'None', unknown: 'Unknown'};
    V.sevBadge = function (sev, score) {
        var s = SEV_LABEL[sev] ? sev : 'unknown';
        var sc = (score == null || score === '') ? '' : ' <span class="iris-vu-mono" style="opacity:.85;">' + V.score(score) + '</span>';
        return '<span class="iris-vu-pill iris-vu-sev-' + s + '">' + SEV_LABEL[s] + sc + '</span>';
    };
    V.kevBadge = function (v) {
        if (!v || !v.kev) { return ''; }
        var t = 'Listed in CISA Known Exploited Vulnerabilities' + (v.kev_ransomware ? ' · known ransomware use' : '') +
            (v.kev_due_date ? ' · due ' + v.kev_due_date : '');
        return '<span class="iris-vu-pill iris-vu-kev" title="' + V.esc(t) + '">KEV' + (v.kev_ransomware ? ' · ransomware' : '') + '</span>';
    };
    V.privBadge = function (v) {
        return v && v.is_private ? '<span class="iris-vu-pill iris-vu-priv" title="Private entry: never leaves this instance">PRIVATE</span>' : '';
    };
    V.statusBadge = function (L, status) {
        var g = L.group[status] || 'open';
        return '<span class="iris-vu-pill iris-vu-st-' + g + '">' + V.esc(L.remediation[status] || status) + '</span>';
    };
    V.exploitBadge = function (L, status) {
        var s = L.exploitation[status] ? status : 'unknown';
        return '<span class="iris-vu-pill iris-vu-ex-' + s + '">' + V.esc(L.exploitation[s]) + '</span>';
    };
    /* the war-room decision a finding cites: its D-number, the title on hover */
    V.decisionChip = function (d) {
        if (!d || !d.ref) { return ''; }
        return ' <span class="iris-vu-pill" data-vu="decision" title="' + V.esc('Decision ' + d.ref + ': ' + (d.title || '')) + '">' + V.esc(d.ref) + '</span>';
    };
    V.vulnLink = function (v) {
        var id = V.id(v && v.vulnerability_id);
        var ident = '<span class="iris-vu-mono">' + V.esc(v && v.identifier) + '</span>';
        return id ? '<a href="/vulnerabilities/' + id + '">' + ident + '</a>' : ident;
    };

    /* ------------------------------------------------------------ modal shell */
    V.modal = function (opts) {
        V.css();
        var mid = 'iris-vu-modal-' + Math.random().toString(36).slice(2, 9);
        var html = '<div class="modal fade" id="' + mid + '" tabindex="-1" role="dialog" aria-labelledby="' + mid + '-t" aria-hidden="true">' +
            '<div class="modal-dialog ' + (opts.size || 'modal-lg') + '" role="document"><div class="modal-content">' +
            '<div class="modal-header"><div><h5 class="modal-title" id="' + mid + '-t">' + V.esc(opts.title) + '</h5>' +
            (opts.subtitle ? '<div class="iris-vu-muted iris-vu-small mt-1">' + opts.subtitle + '</div>' : '') + '</div>' +
            '<button type="button" class="close" data-dismiss="modal" aria-label="Close"><span aria-hidden="true">&times;</span></button></div>' +
            '<div class="modal-body" style="max-height:72vh;overflow-y:auto;"><div class="iris-vu-err mb-2" data-vu="err" role="alert"></div>' +
            (opts.body || '') + '</div>' +
            '<div class="modal-footer">' + (opts.footer || '') + '</div></div></div></div>';
        $('body').append(html);
        var $m = $('#' + mid);
        /* Stacked over another modal (the asset editor): above it, with its own backdrop,
           and the page stays scroll-locked for the modal underneath when this one closes. */
        $m.on('show.bs.modal', function () {
            var z = 1050 + 10 * $('.modal.show').not($m).length;
            $m.css('z-index', z);
            setTimeout(function () { $('.modal-backdrop').last().css('z-index', z - 1); }, 0);
        });
        $m.on('hidden.bs.modal', function () {
            $m.remove();
            if ($('.modal.show').length) { $('body').addClass('modal-open'); }
        });
        $m.modal({backdrop: 'static', show: true});
        return $m;
    };
    V.setErr = function ($m, msg) { $m.find('[data-vu="err"]').text(msg || ''); };

    /* ------------------------------------------------------------ vulnerability form */
    function opts(list, current, extra) {
        var h = extra || '';
        (list || []).forEach(function (o) {
            h += '<option value="' + V.esc(o.value) + '"' + (String(current) === String(o.value) ? ' selected' : '') + '>' + V.esc(o.label) + '</option>';
        });
        return h;
    }
    function productsText(list) {
        return (list || []).map(function (p) {
            return [p.vendor || '', p.product || '', p.versions || ''].filter(function (x, i) { return i < 2 || x; }).join(' | ')
                .replace(/^ \| /, '');
        }).join('\n');
    }
    function pctIn(f) { return (f == null || f === '') ? '' : String(Math.round(Number(f) * 100000) / 1000); }
    /* The Tags field is the product's own tag widget, as on every case object (amsifySuggestags through common.js's
       set_suggest_tags): Enter adds a chip, suggestions come from /manage/tags/suggest, and the hidden #vu-tags keeps
       the chips comma-joined. Without the widget (a page that lacks it) the plain input stays. */
    function tagWidget($m) {
        if (!$m.find('#vu-tags').length || typeof window.set_suggest_tags !== 'function' || !window.jQuery
            || !window.jQuery.fn || !window.jQuery.fn.amsifySuggestags) { return; }
        window.set_suggest_tags('vu-tags');
    }
    /* What the form saves: the chips plus a tag still being typed - a Save straight after typing must not drop it.
       The server splits, trims and de-duplicates. */
    function tagsValue($m) {
        var el = $m.find('#vu-tags')[0];
        if (!el) { return ''; }
        var area = el.nextElementSibling;
        var pending = (area && area.classList && area.classList.contains('amsify-suggestags-area'))
            ? area.querySelector('.amsify-suggestags-input') : null;
        return [el.value, pending ? pending.value : ''].filter(Boolean).join(',');
    }

    V.openVulnForm = function (o) {
        o = o || {};
        V.vocab().then(function (voc) {
            var v = o.vuln || null, edit = !!v;
            var lookup = null;   /* the cve.org prefill in use (create only) */
            var body =
                '<div class="form-row"><div class="form-group col-md-9 mb-2">' +
                '<label for="vu-ident">Identifier</label>' + IrisHelp.icon('vuln.identifier') +
                '<input type="text" class="form-control iris-vu-mono" id="vu-ident" autocomplete="off" placeholder="CVE-2024-3400"' +
                ' value="' + V.esc(v ? v.identifier : (o.identifier || '')) + '"' + (v && v.is_private ? ' disabled' : '') + '></div>' +
                '<div class="form-group col-md-3 mb-2 d-flex align-items-end">' +
                '<div class="form-check"><label class="form-check-label"><input class="form-check-input" type="checkbox" id="vu-private"' +
                (v && v.is_private ? ' checked' : '') + (edit ? ' disabled' : '') + '><span class="form-check-sign">Private entry</span></label>' + IrisHelp.icon('vuln.private') + '</div></div></div>' +
                '<div class="mb-2" data-vu="cve" style="display:none;"><button type="button" class="btn btn-sm btn-outline-primary" data-vu="fill">Fill from cve.org</button>' + IrisHelp.icon('vuln.cve_org') +
                ' <span class="iris-vu-small iris-vu-muted ml-2" data-vu="cvemsg"></span></div>' +
                '<div class="form-group mb-2"><label for="vu-title">Title</label>' +
                '<input type="text" class="form-control" id="vu-title" placeholder="Short description" value="' + V.esc(v ? v.title : '') + '"></div>' +
                '<div class="form-row">' +
                '<div class="form-group col-md-4 mb-2"><label for="vu-kind">Kind</label>' + IrisHelp.icon('vuln.kind') + '<select class="form-control" id="vu-kind">' +
                opts(voc.kinds, v ? v.kind : '', '<option value="">Automatic</option>') + '</select></div>' +
                '<div class="form-group col-md-4 mb-2"><label for="vu-em">Exploit maturity</label>' + IrisHelp.icon('vuln.exploit_maturity') + '<select class="form-control" id="vu-em">' +
                opts(voc.exploit_maturities, v ? v.exploit_maturity : 'unknown') + '</select></div>' +
                '<div class="form-group col-md-4 mb-2"><label for="vu-pa">Patch availability</label>' + IrisHelp.icon('vuln.patch') + '<select class="form-control" id="vu-pa">' +
                opts(voc.patch_availabilities, v ? v.patch_availability : 'unknown') + '</select></div></div>' +
                '<div class="form-group mb-3"><label for="vu-desc">Description</label><textarea class="form-control" id="vu-desc" rows="4">' +
                V.esc(v ? v.description : '') + '</textarea></div>' +
                '<fieldset class="iris-vu-fieldset"><legend class="iris-vu-legend">Scoring</legend>' +
                '<div class="form-group mb-2"><label for="vu-vector">CVSS vector</label>' + IrisHelp.icon('vuln.cvss') +
                '<input type="text" class="form-control iris-vu-mono" id="vu-vector" placeholder="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H" value="' +
                V.esc(v ? v.cvss_vector : '') + '"></div>' +
                '<div class="form-row">' +
                '<div class="form-group col-md-4 mb-2"><label for="vu-cver">CVSS version</label><select class="form-control" id="vu-cver">' +
                opts(voc.cvss_versions, v ? (v.cvss_version || '') : '', '<option value="">Not set</option>') + '</select></div>' +
                '<div class="form-group col-md-4 mb-2"><label for="vu-score">CVSS score</label>' +
                '<input type="text" inputmode="decimal" class="form-control" id="vu-score" placeholder="0.0 – 10.0" value="' +
                V.esc(v && v.cvss_score != null ? v.cvss_score : '') + '"></div>' +
                '<div class="form-group col-md-4 mb-2"><label for="vu-sev">Severity</label><select class="form-control" id="vu-sev">' +
                opts(voc.severities, v && !v.severity_auto ? v.severity : '', '<option value="">Automatic</option>') + '</select></div></div>' +
                '<div class="form-row">' +
                '<div class="form-group col-md-4 mb-2"><label for="vu-epss">EPSS (%)</label>' + IrisHelp.icon('vuln.epss') + '<input type="text" inputmode="decimal" class="form-control" id="vu-epss" placeholder="0 – 100" value="' +
                V.esc(pctIn(v && v.epss_score)) + '"></div>' +
                '<div class="form-group col-md-4 mb-2"><label for="vu-epssp">EPSS percentile (%)</label><input type="text" inputmode="decimal" class="form-control" id="vu-epssp" placeholder="0 – 100" value="' +
                V.esc(pctIn(v && v.epss_percentile)) + '"></div>' +
                '<div class="form-group col-md-4 mb-2"><label for="vu-epssd">EPSS date</label><input type="date" class="form-control" id="vu-epssd" value="' +
                V.esc(v && v.epss_date ? v.epss_date : '') + '"></div></div></fieldset>' +
                '<fieldset class="iris-vu-fieldset"><legend class="iris-vu-legend">CISA KEV</legend>' + IrisHelp.icon('vuln.kev') +
                '<div class="form-check mb-2"><label class="form-check-label"><input class="form-check-input" type="checkbox" id="vu-kev"' +
                (v && v.kev ? ' checked' : '') + '><span class="form-check-sign">Listed in the Known Exploited Vulnerabilities catalogue</span></label></div>' +
                '<div class="form-row" data-vu="kevrow">' +
                '<div class="form-group col-md-4 mb-2"><label for="vu-kevadd">Date added</label><input type="date" class="form-control" id="vu-kevadd" value="' +
                V.esc(v && v.kev_date_added ? v.kev_date_added : '') + '"></div>' +
                '<div class="form-group col-md-4 mb-2"><label for="vu-kevdue">Due date</label><input type="date" class="form-control" id="vu-kevdue" value="' +
                V.esc(v && v.kev_due_date ? v.kev_due_date : '') + '"></div>' +
                '<div class="form-group col-md-4 mb-2 d-flex align-items-end"><div class="form-check"><label class="form-check-label">' +
                '<input class="form-check-input" type="checkbox" id="vu-kevrw"' + (v && v.kev_ransomware ? ' checked' : '') +
                '><span class="form-check-sign">Known ransomware use</span></label></div></div></div></fieldset>' +
                '<div class="form-row">' +
                '<div class="form-group col-md-6 mb-2"><label for="vu-cwes">CWEs</label><input type="text" class="form-control" id="vu-cwes" placeholder="CWE-79, CWE-89" value="' +
                V.esc(v ? (v.cwes || []).join(', ') : '') + '"></div>' +
                '<div class="form-group col-md-6 mb-2"><label for="vu-aliases">Aliases</label>' + IrisHelp.icon('vuln.aliases') + '<input type="text" class="form-control iris-vu-mono" id="vu-aliases" placeholder="GHSA-xxxx-xxxx-xxxx, …" value="' +
                V.esc(v ? (v.aliases || []).join(', ') : '') + '"></div></div>' +
                '<div class="form-row">' +
                '<div class="form-group col-md-6 mb-2"><label for="vu-pub">Published</label><input type="date" class="form-control" id="vu-pub" value="' +
                V.esc(v && v.published_at ? v.published_at : '') + '"></div>' +
                '<div class="form-group col-md-6 mb-2"><label for="vu-mod">Modified</label><input type="date" class="form-control" id="vu-mod" value="' +
                V.esc(v && v.modified_at ? v.modified_at : '') + '"></div></div>' +
                '<div class="form-group mb-2"><label for="vu-products">Affected products</label>' + IrisHelp.icon('vuln.products') +
                '<textarea class="form-control iris-vu-mono" id="vu-products" rows="3" placeholder="One per line: vendor | product | versions&#10;Apache | httpd | 2.4.49 - 2.4.50">' +
                V.esc(v ? productsText(v.affected_products) : '') + '</textarea></div>' +
                '<div class="form-group mb-2"><label for="vu-refs">References</label>' +
                '<textarea class="form-control iris-vu-mono" id="vu-refs" rows="3" placeholder="One URL per line (http/https)">' +
                V.esc(v ? (v.reference_urls || []).join('\n') : '') + '</textarea></div>' +
                '<div class="form-group mb-1"><label for="vu-tags">Tags</label>' + IrisHelp.icon('common.tags') +
                '<input type="text" class="form-control" id="vu-tags" value="' + V.esc(v ? (v.tags || []).join(',') : '') + '"></div>';
            var $m = V.modal({
                title: edit ? 'Edit ' + v.identifier : 'New vulnerability',
                subtitle: 'A public entry is named by its CVE / GHSA / advisory identifier. A private entry gets an ' +
                    '<span class="iris-vu-mono">IRIS-VULN-YYYY-NNNN</span> identifier and never leaves this instance.',
                body: body,
                footer: '<button type="button" class="btn btn-outline-secondary" data-dismiss="modal">Cancel</button>' +
                    '<button type="button" class="btn btn-primary" data-vu="save">' + (edit ? 'Save changes' : 'Create vulnerability') + '</button>'
            });
            tagWidget($m);
            var origVector = v ? (v.cvss_vector || '') : '', origScore = v && v.cvss_score != null ? String(v.cvss_score) : '';
            function sync() {
                var priv = $m.find('#vu-private').is(':checked');
                if (!edit) {
                    $m.find('#vu-ident').prop('disabled', priv).attr('placeholder', priv ? 'Assigned on save (IRIS-VULN-YYYY-NNNN)' : 'CVE-2024-3400');
                }
                var hasVec = $.trim($m.find('#vu-vector').val()) !== '';
                $m.find('#vu-cver').prop('disabled', hasVec);
                $m.find('#vu-score').attr('placeholder', hasVec ? 'From the vector' : '0.0 – 10.0');
                $m.find('[data-vu="kevrow"]').toggle($m.find('#vu-kev').is(':checked'));
                var ident = $.trim($m.find('#vu-ident').val());
                var canLookup = !edit && !priv && voc.cve_lookup_enabled && V.isCve(ident);
                $m.find('[data-vu="cve"]').toggle(!!canLookup);
            }
            $m.on('input change', 'input,select,textarea', sync);
            sync();
            function fill(values) {
                var set = function (sel, val) { if (val != null && val !== '') { $m.find(sel).val(val); } };
                set('#vu-title', values.title);
                set('#vu-desc', values.description);
                if (values.cvss_vector) { $m.find('#vu-vector').val(values.cvss_vector); $m.find('#vu-score').val(''); }
                else { set('#vu-cver', values.cvss_version); set('#vu-score', values.cvss_score); }
                set('#vu-cwes', (values.cwes || []).join(', '));
                set('#vu-products', productsText(values.affected_products));
                set('#vu-refs', (values.reference_urls || []).join('\n'));
                set('#vu-pub', values.published_at);
                set('#vu-mod', values.modified_at);
                if (values.kev) { $m.find('#vu-kev').prop('checked', true); set('#vu-kevadd', values.kev_date_added); }
                set('#vu-em', values.exploit_maturity);
                if (!$.trim($m.find('#vu-kind').val())) { $m.find('#vu-kind').val('cve'); }
                sync();
            }
            $m.on('click', '[data-vu="fill"]', function () {
                var ident = $.trim($m.find('#vu-ident').val());
                var $msg = $m.find('[data-vu="cvemsg"]').text('Looking up ' + ident + ' …');
                V.fetch(API + '/cve-lookup?identifier=' + encodeURIComponent(ident)).then(function (j) {
                    if (!V.ok(j)) { $msg.text(V.errText(j, 'The cve.org lookup failed.')); return; }
                    if (j.existing_id) {
                        $msg.html('Already in the catalogue as <a href="/vulnerabilities/' + V.id(j.existing_id) + '">' +
                            V.esc(j.existing_identifier) + '</a>.');
                        return;
                    }
                    lookup = {identifier: ident.toUpperCase(), enrichment: j.enrichment};
                    fill(j.values || {});
                    $msg.text('Filled from cve.org' + (j.assigner ? ' (assigner ' + j.assigner + ')' : '') +
                        (j.state && j.state !== 'PUBLISHED' ? ' - record state ' + j.state : '') + '. Review before saving.');
                });
            });
            $m.on('click', '[data-vu="save"]', function () {
                var $b = $(this);
                var priv = $m.find('#vu-private').is(':checked');
                var pct = function (sel, label) {
                    var s = $.trim($m.find(sel).val());
                    if (s === '') { return null; }
                    var n = Number(s.replace(',', '.'));
                    if (isNaN(n) || n < 0 || n > 100) { throw new Error(label + ' must be between 0 and 100.'); }
                    return Math.round(n * 10000) / 1000000;
                };
                var p;
                try {
                    p = {
                        title: $.trim($m.find('#vu-title').val()),
                        kind: $m.find('#vu-kind').val() || null,
                        description: $m.find('#vu-desc').val(),
                        exploit_maturity: $m.find('#vu-em').val(),
                        patch_availability: $m.find('#vu-pa').val(),
                        severity: $m.find('#vu-sev').val() || null,
                        epss_score: pct('#vu-epss', 'EPSS'),
                        epss_percentile: pct('#vu-epssp', 'The EPSS percentile'),
                        epss_date: $m.find('#vu-epssd').val() || null,
                        kev: $m.find('#vu-kev').is(':checked'),
                        kev_date_added: $m.find('#vu-kevadd').val() || null,
                        kev_due_date: $m.find('#vu-kevdue').val() || null,
                        kev_ransomware: $m.find('#vu-kevrw').is(':checked'),
                        cwes: $m.find('#vu-cwes').val(),
                        aliases: $m.find('#vu-aliases').val(),
                        published_at: $m.find('#vu-pub').val() || null,
                        modified_at: $m.find('#vu-mod').val() || null,
                        affected_products: $m.find('#vu-products').val(),
                        reference_urls: $m.find('#vu-refs').val(),
                        tags: tagsValue($m)
                    };
                } catch (e) { V.setErr($m, e.message); return; }
                if (!p.title) { V.setErr($m, 'A title is required.'); return; }
                var vector = $.trim($m.find('#vu-vector').val());
                var score = $.trim($m.find('#vu-score').val());
                p.cvss_vector = vector || null;
                if (!vector) { p.cvss_version = $m.find('#vu-cver').val() || null; p.cvss_score = score === '' ? null : score; }
                else if (score !== '' && (!edit || vector === origVector || score !== origScore)) { p.cvss_score = score; }
                if (!edit) {
                    p.is_private = priv;
                    if (!priv) { p.identifier = $.trim($m.find('#vu-ident').val()); }
                    if (lookup && p.identifier && p.identifier.toUpperCase() === lookup.identifier) { p.enrichment = lookup.enrichment; }
                } else if (!v.is_private) {
                    p.identifier = $.trim($m.find('#vu-ident').val());
                }
                $b.prop('disabled', true);
                V.fetch(edit ? API + '/' + V.id(v.vulnerability_id) : API, edit ? 'PUT' : 'POST', p).then(function (j) {
                    $b.prop('disabled', false);
                    if (!V.ok(j)) {
                        var msg = V.errText(j);
                        if (j.data && j.data.existing_id) {
                            msg += ' ';
                        }
                        V.setErr($m, msg);
                        if (j.data && j.data.existing_id) {
                            $m.find('[data-vu="err"]').append(' <a href="/vulnerabilities/' + V.id(j.data.existing_id) + '">Open it</a>');
                        }
                        return;
                    }
                    $m.modal('hide');
                    if (o.onSaved) { o.onSaved(j); }
                });
            });
        }).catch(function (e) { window.alert(e.message); });
    };

    /* ------------------------------------------------------------ chooser (search + quick add) */
    V.chooser = function ($host, onChange) {
        $host.html('<div data-vu="chosen"></div><div data-vu="search">' +
            '<input type="text" class="form-control mb-1" data-vu="q" aria-label="Search the catalogue" placeholder="Search the catalogue by identifier or title, or type a new CVE / advisory id">' +
            '<div class="iris-vu-pick" data-vu="results"></div></div>');
        var state = {choice: null}, seq = 0, timer = null;
        function render() {
            var c = state.choice;
            $host.find('[data-vu="search"]').toggle(!c);
            if (!c) { $host.find('[data-vu="chosen"]').empty(); return; }
            var inner = c.type === 'existing'
                ? '<span class="iris-vu-mono font-weight-bold">' + V.esc(c.vulnerability.identifier) + '</span> ' +
                  V.sevBadge(c.vulnerability.severity, c.vulnerability.cvss_score) + ' ' + V.kevBadge(c.vulnerability) +
                  '<div class="iris-vu-small iris-vu-muted mt-1">' + V.esc(c.vulnerability.title) + '</div>'
                : '<span class="iris-vu-mono font-weight-bold">' + V.esc(c.identifier) + '</span> <span class="iris-vu-pill iris-vu-priv">New public entry</span>' +
                  '<input type="text" class="form-control form-control-sm mt-2" data-vu="qtitle" placeholder="Title (optional)" aria-label="Title of the new entry">';
            $host.find('[data-vu="chosen"]').html('<div class="iris-vu-card d-flex justify-content-between align-items-start">' +
                '<div style="min-width:0;">' + inner + '</div><button type="button" class="btn btn-sm btn-link" data-vu="change">Change</button></div>');
        }
        function search(q) {
            var my = ++seq;
            V.fetch(API + '?per_page=8&search=' + encodeURIComponent(q)).then(function (j) {
                if (my !== seq) { return; }
                var rows = V.ok(j) ? (j.data || []) : [];
                var up = q.trim().toUpperCase();
                var exact = rows.some(function (r) {
                    return r.identifier.toUpperCase() === up || (r.aliases || []).some(function (a) { return a.toUpperCase() === up; });
                });
                var h = '';
                if (up && !exact && !/\s/.test(up) && up.indexOf('IRIS-VULN-') !== 0) {
                    h += '<button type="button" data-vu="quick">+ Quick add <span class="iris-vu-mono font-weight-bold">' + V.esc(q.trim()) + '</span></button>';
                }
                rows.forEach(function (r, i) {
                    h += '<button type="button" data-vu="pick" data-i="' + i + '"><span class="iris-vu-mono font-weight-bold" style="flex-shrink:0;">' +
                        V.esc(r.identifier) + '</span><span class="iris-vu-muted" style="flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' +
                        V.esc(r.title) + '</span>' + V.sevBadge(r.severity, r.cvss_score) + V.kevBadge(r) + '</button>';
                });
                if (!h) { h = '<div class="iris-vu-small iris-vu-muted p-2">' + (V.ok(j) ? 'No match.' : V.esc(V.errText(j))) + '</div>'; }
                $host.find('[data-vu="results"]').html(h).data('rows', rows);
            });
        }
        $host.on('input', '[data-vu="q"]', function () {
            var q = $(this).val();
            clearTimeout(timer);
            timer = setTimeout(function () { search(q); }, q.trim() ? 250 : 0);
        });
        $host.on('click', '[data-vu="pick"]', function () {
            var rows = $host.find('[data-vu="results"]').data('rows') || [];
            state.choice = {type: 'existing', vulnerability: rows[Number($(this).attr('data-i'))]};
            render(); if (onChange) { onChange(state.choice); }
        });
        $host.on('click', '[data-vu="quick"]', function () {
            state.choice = {type: 'quick', identifier: $.trim($host.find('[data-vu="q"]').val()), title: ''};
            render(); if (onChange) { onChange(state.choice); }
        });
        $host.on('input', '[data-vu="qtitle"]', function () { if (state.choice) { state.choice.title = $(this).val(); } });
        $host.on('click', '[data-vu="change"]', function () {
            state.choice = null; render(); if (onChange) { onChange(null); }
            $host.find('[data-vu="q"]').trigger('focus');
        });
        search('');
        return {
            payload: function () {
                var c = state.choice;
                if (!c) { return null; }
                return c.type === 'existing' ? {vulnerability_id: c.vulnerability.vulnerability_id}
                    : {quick: {identifier: c.identifier, title: c.title || ''}};
            },
            set: function (vuln) { state.choice = {type: 'existing', vulnerability: vuln}; render(); }
        };
    };

    /* ------------------------------------------------------------ merge */
    V.openMerge = function (o) {
        var v = o.vuln;
        var $m = V.modal({
            title: 'Merge ' + v.identifier + ' into…', size: 'modal-dialog-centered',
            subtitle: 'Its findings move to the target entry, its identifier and aliases become aliases of the target, and it is deleted. This cannot be undone.',
            body: '<div class="mb-2 iris-vu-small iris-vu-muted">Merge into ' + IrisHelp.icon('vuln.merge') + '</div><div data-vu="chooser"></div>',
            footer: '<button type="button" class="btn btn-outline-secondary" data-dismiss="modal">Cancel</button>' +
                '<button type="button" class="btn btn-danger" data-vu="merge" disabled>Merge</button>'
        });
        var ch = V.chooser($m.find('[data-vu="chooser"]'), function (c) {
            var bad = !c || c.type !== 'existing' || c.vulnerability.vulnerability_id === v.vulnerability_id;
            $m.find('[data-vu="merge"]').prop('disabled', bad);
            V.setErr($m, c && c.type === 'quick' ? 'Pick an existing entry to merge into.' :
                (c && c.vulnerability && c.vulnerability.vulnerability_id === v.vulnerability_id ? 'Pick another entry.' : ''));
        });
        $m.on('click', '[data-vu="merge"]', function () {
            var p = ch.payload();
            if (!p || !p.vulnerability_id) { return; }
            $(this).prop('disabled', true);
            V.fetch(API + '/' + V.id(v.vulnerability_id) + '/merge', 'POST', {target_id: p.vulnerability_id}).then(function (j) {
                if (!V.ok(j)) { V.setErr($m, V.errText(j)); $m.find('[data-vu="merge"]').prop('disabled', false); return; }
                $m.modal('hide');
                if (o.onMerged) { o.onMerged(j); }
            });
        });
    };

    /* ------------------------------------------------------------ findings */
    function findingBase(o) {
        if (o.scope === 'registry') { return '/api/v2/customer-assets/' + V.id(o.registryAssetId) + '/vulnerabilities'; }
        return '/api/v2/cases/' + V.id(o.caseId) + '/vulnerabilities';
    }
    function dtLocal(iso) {
        var m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(String(iso || ''));
        return m ? m[1] + 'T' + m[2] : '';
    }
    function groupedStatusOptions(voc, current) {
        var h = '';
        (voc.remediation_groups || []).forEach(function (g) {
            h += '<optgroup label="' + V.esc(g.label) + '">' + opts(g.statuses, current) + '</optgroup>';
        });
        return h;
    }

    V.openFindingForm = function (o) {
        V.vocab().then(function (voc) {
            var f = o.finding || null, edit = !!f, L = voc.L;
            var usersUrl = o.scope === 'case' ? '/case/users/list?cid=' + V.id(o.caseId) : '/manage/users/restricted/list';
            var body =
                (edit ? '<div class="iris-vu-card mb-3"><span class="iris-vu-mono font-weight-bold">' + V.vulnLink(f.vulnerability) + '</span> ' +
                    V.sevBadge(f.vulnerability.severity, f.vulnerability.cvss_score) + ' ' + V.kevBadge(f.vulnerability) +
                    '<div class="iris-vu-small iris-vu-muted mt-1">' + V.esc(f.vulnerability.title) +
                    (f.asset_name ? ' · on <b>' + V.esc(f.asset_name) + '</b>' : '') + '</div></div>'
                    : '<div class="form-group mb-3"><label>Vulnerability</label>' + IrisHelp.icon('vuln.finding') + '<div data-vu="chooser"></div></div>') +
                (o.scope === 'case' && !edit && !o.assetId
                    ? '<div class="form-group mb-3"><label for="vf-asset">Asset <span class="iris-vu-req">*</span></label><select class="form-control" id="vf-asset">' +
                      '<option value="">Choose the case asset…</option></select></div>' : '') +
                '<div class="form-row">' +
                '<div class="form-group col-md-6 mb-2"><label for="vf-rem">Remediation status</label>' + IrisHelp.icon('vuln.remediation') + '<select class="form-control" id="vf-rem">' +
                groupedStatusOptions(voc, f ? f.remediation_status : 'under-analysis') + '</select></div>' +
                '<div class="form-group col-md-6 mb-2"><label for="vf-exp">Exploitation status</label>' + IrisHelp.icon('vuln.exploitation') + '<select class="form-control" id="vf-exp">' +
                opts(voc.exploitation_statuses, f ? f.exploitation_status : 'unknown') + '</select></div></div>' +
                '<div class="form-group mb-2" data-vu="just"><label for="vf-just">Justification (VEX) <span class="iris-vu-muted">— or give a reason below</span></label>' + IrisHelp.icon('vuln.vex') +
                '<select class="form-control" id="vf-just">' + opts(voc.vex_justifications, f ? f.not_affected_justification : '',
                    '<option value="">No justification</option>') + '</select></div>' +
                '<div class="form-group mb-2"><label for="vf-reason">Status reason <span class="iris-vu-req" data-vu="reasonreq">*</span></label>' +
                '<textarea class="form-control" id="vf-reason" rows="2">' + V.esc(f ? f.status_reason : '') + '</textarea></div>' +
                '<div class="form-row">' +
                '<div class="form-group col-md-4 mb-2" data-vu="exat"><label for="vf-exat">Exploited at (UTC)</label>' +
                '<input type="datetime-local" class="form-control" id="vf-exat" value="' + V.esc(dtLocal(f && f.exploited_at)) + '"></div>' +
                '<div class="form-group col-md-4 mb-2"><label for="vf-due">Due date</label>' + IrisHelp.icon('vuln.due') + '<input type="date" class="form-control" id="vf-due" value="' +
                V.esc(f && f.due_date ? f.due_date : '') + '"></div>' +
                '<div class="form-group col-md-4 mb-2"><label for="vf-det">Detected at (UTC)</label>' +
                '<input type="datetime-local" class="form-control" id="vf-det" value="' + V.esc(dtLocal(f && f.detected_at)) + '"></div></div>' +
                '<div class="form-row">' +
                '<div class="form-group col-md-6 mb-2"><label for="vf-src">Detection source</label><input type="text" class="form-control" id="vf-src" placeholder="Scanner, EDR, analyst…" value="' +
                V.esc(f ? f.detection_source : '') + '"></div>' +
                '<div class="form-group col-md-6 mb-2"><label for="vf-owner">Owner</label><select class="form-control" id="vf-owner"><option value="">No owner</option></select></div></div>' +
                '<div class="form-row">' +
                '<div class="form-group col-md-4 mb-2"><label for="vf-comp">Component</label><input type="text" class="form-control" id="vf-comp" placeholder="Affected package, service or product" value="' +
                V.esc(f ? f.component : '') + '"></div>' +
                '<div class="form-group col-md-4 mb-2"><label for="vf-inst">Installed version</label><input type="text" class="form-control" id="vf-inst" value="' +
                V.esc(f ? f.installed_version : '') + '"></div>' +
                '<div class="form-group col-md-4 mb-2"><label for="vf-fix">Fixed version</label><input type="text" class="form-control" id="vf-fix" value="' +
                V.esc(f ? f.fixed_version : '') + '"></div></div>' +
                '<div class="form-group mb-2" data-vu="verif"><label for="vf-verif">Verification method</label>' +
                '<textarea class="form-control" id="vf-verif" rows="2" placeholder="How the fix was confirmed (rescan, manual check…)">' +
                V.esc(f ? f.verification_method : '') + '</textarea></div>' +
                (o.scope === 'case'
                    ? '<div class="form-row"><div class="form-group col-md-6 mb-2"><label for="vf-events">Linked timeline events</label>' + IrisHelp.icon('vuln.links') +
                      '<select class="form-control" id="vf-events" multiple size="5"></select></div>' +
                      '<div class="form-group col-md-6 mb-2"><label for="vf-iocs">Linked IOCs</label>' +
                      '<select class="form-control" id="vf-iocs" multiple size="5"></select></div></div>' +
                      '<div class="form-group mb-2"><label for="vf-decision">War-room decision</label>' + IrisHelp.icon('vuln.decision') +
                      '<select class="form-control" id="vf-decision"><option value="">No decision</option></select>' +
                      '<div class="iris-vu-small iris-vu-muted mt-1" data-vu="dechint"></div></div>' : '') +
                '<div class="form-group mb-1"><label for="vf-notes">Notes</label><textarea class="form-control" id="vf-notes" rows="3">' +
                V.esc(f ? f.notes : '') + '</textarea></div>';
            var $m = V.modal({
                title: edit ? 'Edit finding' : 'Record a vulnerability',
                subtitle: o.scope === 'registry' ? 'On the registry entry <b>' + V.esc(o.registryAssetName || '') + '</b>.'
                    : (o.assetName ? 'On the case asset <b>' + V.esc(o.assetName) + '</b>.' : 'On one of this case\'s assets.'),
                body: body,
                footer: (edit && o.canDelete !== false ? '<button type="button" class="btn btn-outline-danger mr-auto" data-vu="del">Delete finding</button>' : '') +
                    '<button type="button" class="btn btn-outline-secondary" data-dismiss="modal">Cancel</button>' +
                    '<button type="button" class="btn btn-primary" data-vu="save">' + (edit ? 'Save' : 'Record finding') + '</button>'
            });
            var chooser = edit ? null : V.chooser($m.find('[data-vu="chooser"]'));
            if (o.preset && chooser) { chooser.set(o.preset); }
            function sync() {
                var rem = $m.find('#vf-rem').val(), ex = $m.find('#vf-exp').val();
                $m.find('[data-vu="just"]').toggle(rem === 'not-affected');
                $m.find('[data-vu="reasonreq"]').toggle((voc.reason_required || []).indexOf(rem) >= 0);
                $m.find('[data-vu="exat"]').toggle(ex === 'exploited');
                $m.find('[data-vu="verif"]').toggle(L.group[rem] === 'fixed');
            }
            $m.on('change', '#vf-rem,#vf-exp', sync);
            sync();
            /* the approved decisions a finding on the chosen asset may cite (the asset-flag rule); the one
               already cited stays offered. Until the list has loaded, a save leaves the decision as it is. */
            function loadDecisions() {
                var $d = $m.find('#vf-decision');
                if (!$d.length) { return; }
                var aid = (f && f.asset_id) || o.assetId || $m.find('#vf-asset').val();
                var keep = f && f.decision_id ? String(f.decision_id) : '';
                $d.data('loaded', false).find('option[value!=""]').remove();
                if (!aid) { $m.find('[data-vu="dechint"]').text('Choose the asset first.'); return; }
                V.fetch(findingBase(o) + '/decisions?asset_id=' + V.id(aid)).then(function (j) {
                    var rows = Array.isArray(j.value) ? j.value : null;
                    if (!V.ok(j) || !rows) { $m.find('[data-vu="dechint"]').text(V.errText(j)); return; }
                    rows.forEach(function (c) {
                        $d.append($('<option>').val(String(c.decision_id)).text(c.ref + ' ' + c.title + (c.room_name ? ' (' + c.room_name + ')' : '')));
                    });
                    if (keep && !$d.find('option[value="' + V.id(keep) + '"]').length) {
                        $d.append($('<option>').val(keep).text(f.decision ? f.decision.ref + ' ' + f.decision.title + ' (cited)' : '#' + keep));
                    }
                    $d.val(keep).data('loaded', true);
                    $m.find('[data-vu="dechint"]').text($d.find('option').length > 1 ? ''
                        : 'No approved decision of a war room this case is attached to (and you belong to) applies to this asset.');
                });
            }
            $m.on('change', '#vf-asset', loadDecisions);
            loadDecisions();
            V.fetch(usersUrl).then(function (j) {
                var users = (j && j.data) || [];
                var $s = $m.find('#vf-owner');
                users.forEach(function (u) {
                    if (u.user_active === false) { return; }
                    $s.append($('<option>').val(String(u.user_id)).text(u.user_name + ' (' + u.user_login + ')'));
                });
                if (f && f.owner_id && !$s.find('option[value="' + V.id(f.owner_id) + '"]').length) {
                    $s.append($('<option>').val(String(f.owner_id)).text(f.owner_name || ('#' + f.owner_id)));
                }
                if (f && f.owner_id) { $s.val(String(f.owner_id)); }
            });
            if (o.scope === 'case') {
                V.fetch(findingBase(o) + '/pickers').then(function (j) {
                    if (!V.ok(j)) { return; }
                    var $a = $m.find('#vf-asset');
                    (j.assets || []).forEach(function (a) {
                        $a.append($('<option>').val(String(a.asset_id)).text(a.asset_name + (a.asset_type ? ' (' + a.asset_type + ')' : '')));
                    });
                    var evSel = f ? (f.events || []).map(function (e) { return String(e.event_id); }) : [];
                    var iocSel = f ? (f.iocs || []).map(function (e) { return String(e.ioc_id); }) : [];
                    var $e = $m.find('#vf-events');
                    (j.events || []).forEach(function (e) {
                        $e.append($('<option>').val(String(e.event_id)).text((e.event_date ? e.event_date.slice(0, 16).replace('T', ' ') + ' · ' : '') + e.event_title)
                            .prop('selected', evSel.indexOf(String(e.event_id)) >= 0));
                    });
                    var $i = $m.find('#vf-iocs');
                    (j.iocs || []).forEach(function (i) {
                        $i.append($('<option>').val(String(i.ioc_id)).text(i.ioc_value + (i.ioc_type ? ' (' + i.ioc_type + ')' : ''))
                            .prop('selected', iocSel.indexOf(String(i.ioc_id)) >= 0));
                    });
                });
            }
            $m.on('click', '[data-vu="save"]', function () {
                var rem = $m.find('#vf-rem').val();
                var p = {
                    remediation_status: rem,
                    exploitation_status: $m.find('#vf-exp').val(),
                    not_affected_justification: rem === 'not-affected' ? ($m.find('#vf-just').val() || null) : null,
                    status_reason: $m.find('#vf-reason').val(),
                    exploited_at: $m.find('#vf-exat').val() || null,
                    due_date: $m.find('#vf-due').val() || null,
                    detected_at: $m.find('#vf-det').val() || (edit ? null : undefined),
                    detection_source: $m.find('#vf-src').val(),
                    owner_id: $m.find('#vf-owner').val() || null,
                    component: $m.find('#vf-comp').val(),
                    installed_version: $m.find('#vf-inst').val(),
                    fixed_version: $m.find('#vf-fix').val(),
                    verification_method: $m.find('#vf-verif').val(),
                    notes: $m.find('#vf-notes').val()
                };
                if (p.detected_at === undefined) { delete p.detected_at; }
                if ((voc.reason_required || []).indexOf(rem) >= 0 && !$.trim(p.status_reason)) {
                    V.setErr($m, (L.remediation[rem] || rem) + ' needs a reason.'); return;
                }
                if (o.scope === 'case') {
                    p.event_ids = ($m.find('#vf-events').val() || []).map(Number);
                    p.ioc_ids = ($m.find('#vf-iocs').val() || []).map(Number);
                    var $dec = $m.find('#vf-decision');
                    if ($dec.data('loaded')) { p.decision_id = $dec.val() ? Number($dec.val()) : null; }
                }
                var url = findingBase(o), method = 'POST';
                if (edit) { url += '/' + V.id(f.finding_id); method = 'PUT'; }
                else {
                    var c = chooser.payload();
                    if (!c) { V.setErr($m, 'Choose a vulnerability (or quick-add one by its identifier).'); return; }
                    Object.assign(p, c);
                    if (o.scope === 'case') {
                        var aid = o.assetId || $m.find('#vf-asset').val();
                        if (!aid) { V.setErr($m, 'Choose the case asset this vulnerability is on.'); return; }
                        p.asset_id = Number(aid);
                    }
                }
                var $b = $(this).prop('disabled', true);
                V.fetch(url, method, p).then(function (j) {
                    $b.prop('disabled', false);
                    if (!V.ok(j)) { V.setErr($m, V.errText(j)); return; }
                    $m.modal('hide');
                    if (o.onSaved) { o.onSaved(j); }
                });
            });
            $m.on('click', '[data-vu="del"]', function () {
                if (!window.confirm('Delete this finding? Its history goes with it.')) { return; }
                V.fetch(findingBase(o) + '/' + V.id(f.finding_id), 'DELETE').then(function (j) {
                    if (!V.ok(j)) { V.setErr($m, V.errText(j)); return; }
                    $m.modal('hide');
                    if (o.onSaved) { o.onSaved(null); }
                });
            });
        }).catch(function (e) { window.alert(e.message); });
    };

    V.openHistory = function (url, title) {
        V.vocab().then(function (voc) {
            var $m = V.modal({title: title || 'Finding history', size: 'modal-lg',
                body: '<div class="iris-vu-small iris-vu-muted mb-2">Every change, oldest last ' + IrisHelp.icon('vuln.history') + '</div><div data-vu="h">Loading…</div>',
                footer: '<button type="button" class="btn btn-outline-secondary" data-dismiss="modal">Close</button>'});
            V.fetch(url).then(function (j) {
                var rows = Array.isArray(j.value) ? j.value : null;
                if (!V.ok(j) || !rows) { $m.find('[data-vu="h"]').text(V.errText(j)); return; }
                if (!rows.length) { $m.find('[data-vu="h"]').text('No recorded change.'); return; }
                var lab = function (field, val) {
                    if (val == null || val === '') { return '<span class="iris-vu-muted">—</span>'; }
                    if (field === 'remediation_status') { return V.esc(voc.L.remediation[val] || val); }
                    if (field === 'exploitation_status') { return V.esc(voc.L.exploitation[val] || val); }
                    if (field === 'not_affected_justification') { return V.esc(voc.L.vex[val] || val); }
                    return V.esc(val);
                };
                var h = '<table class="table table-sm iris-vu-table"><thead><tr><th>When (UTC)</th><th>Who</th><th>Field</th><th>From</th><th>To</th></tr></thead><tbody>';
                rows.forEach(function (r) {
                    h += '<tr><td class="text-nowrap">' + V.fmtDate(r.changed_at) + '</td><td>' + V.esc(r.changed_by_name || '—') + '</td><td>' +
                        V.esc(String(r.field).replace(/_/g, ' ')) + '</td><td>' + lab(r.field, r.old_value) + '</td><td>' + lab(r.field, r.new_value) + '</td></tr>';
                });
                $m.find('[data-vu="h"]').html(h + '</tbody></table>');
            });
        });
    };

    /* mountFindings(el, {scope:'case'|'registry', caseId, assetId, assetName, registryAssetId,
                          registryAssetName, canWrite, showAsset, onChange}) -> {reload}
       onChange() runs after a finding is recorded, edited or deleted here (the Assets page
       refreshes its per-asset counts with it). */
    V.mountFindings = function (el, o) {
        V.css();
        var $el = $(el), filter = '', search = '';
        var base = findingBase(o);
        function changed() {
            load();
            if (o.onChange) { o.onChange(); }
        }
        $el.html('<div data-vu="sum" class="mb-2"></div>' +
            '<div class="d-flex flex-wrap align-items-center iris-vu-toolbar mb-2">' +
            '<div class="btn-group btn-group-sm mr-2 mb-1" role="group" aria-label="Status">' +
            ['', 'open', 'fixed', 'dismissed'].map(function (g) {
                return '<button type="button" class="btn btn-outline-secondary' + (g === '' ? ' active' : '') + '" data-vu-f="' + g + '">' +
                    (g ? g.charAt(0).toUpperCase() + g.slice(1) : 'All') + '</button>';
            }).join('') + '</div>' +
            '<input type="text" class="form-control form-control-sm mr-2 mb-1" style="max-width:240px;" data-vu="s" aria-label="Filter findings" placeholder="Filter…">' +
            (o.canWrite ? '<button type="button" class="btn btn-sm btn-primary ml-auto mb-1" data-vu="add">+ Record vulnerability</button>' : '') +
            '</div><div data-vu="list"><div class="iris-vu-muted iris-vu-small">Loading…</div></div>');
        function load() {
            V.vocab().then(function (voc) {
                var q = '?status=' + encodeURIComponent(filter) + '&search=' + encodeURIComponent(search) +
                    (o.scope === 'case' && o.assetId ? '&asset_id=' + V.id(o.assetId) : '');
                V.fetch(base + q).then(function (j) {
                    if (!V.ok(j) || !Array.isArray(j.findings)) {
                        $el.find('[data-vu="list"]').html('<div class="iris-vu-err">Could not load the findings: ' + V.esc(V.errText(j)) + '</div>');
                        return;
                    }
                    var s = j.summary || {};
                    var chip = function (n, label, cls) { return '<span class="iris-vu-chip"><b class="' + (cls || '') + '">' + Number(n || 0) + '</b>' + label + '</span>'; };
                    $el.find('[data-vu="sum"]').html(chip(s.open, 'open') + chip(s.fixed, 'fixed') + chip(s.dismissed, 'dismissed') +
                        chip(s.exploited_open, 'exploited & open', s.exploited_open ? 'iris-vu-overdue' : '') +
                        chip(s.overdue, 'overdue', s.overdue ? 'iris-vu-overdue' : '') + chip(s.kev_open, 'KEV open'));
                    var rows = j.findings;
                    if (!rows.length) {
                        $el.find('[data-vu="list"]').html('<div class="iris-vu-muted iris-vu-small py-2">' +
                            (filter || search ? 'No finding matches the filter.' :
                                (o.scope === 'registry' ? 'No vulnerability recorded on this registry entry.' :
                                    (o.assetId ? 'No vulnerability recorded on this asset.' : 'No vulnerability recorded in this case.'))) + '</div>');
                        return;
                    }
                    var showAsset = o.showAsset && !o.assetId;
                    var h = '<div class="table-responsive"><table class="table iris-vu-table mb-0"><thead><tr><th>Vulnerability</th><th>Severity</th>' +
                        (showAsset ? '<th>Asset</th>' : '') + '<th>Remediation</th><th>Exploitation</th><th>Due</th><th>Owner</th><th></th></tr></thead><tbody>';
                    rows.forEach(function (f, i) {
                        h += '<tr><td style="min-width:200px;">' + V.vulnLink(f.vulnerability) + ' ' + V.kevBadge(f.vulnerability) +
                            '<div class="iris-vu-small iris-vu-muted text-truncate" style="max-width:340px;">' + V.esc(f.vulnerability.title) + '</div></td>' +
                            '<td>' + V.sevBadge(f.vulnerability.severity, f.vulnerability.cvss_score) + '</td>' +
                            (showAsset ? '<td>' + (f.asset_name ? V.esc(f.asset_name) : '<span class="iris-vu-muted">—</span>') + '</td>' : '') +
                            '<td>' + V.statusBadge(voc.L, f.remediation_status) + V.decisionChip(f.decision) + '</td><td>' + V.exploitBadge(voc.L, f.exploitation_status) + '</td>' +
                            '<td class="text-nowrap' + (f.overdue ? ' iris-vu-overdue' : '') + '">' + (f.due_date ? V.esc(f.due_date) + (f.overdue ? ' · overdue' : '') : '<span class="iris-vu-muted">—</span>') + '</td>' +
                            '<td>' + (f.owner_name ? V.esc(f.owner_name) : '<span class="iris-vu-muted">—</span>') + '</td>' +
                            '<td class="text-right text-nowrap"><button type="button" class="btn btn-sm btn-link p-0 mr-2" data-vu="hist" data-i="' + i + '">History</button>' +
                            '<button type="button" class="btn btn-sm btn-link p-0" data-vu="edit" data-i="' + i + '">' + (o.canWrite ? 'Edit' : 'View') + '</button></td></tr>';
                    });
                    h += '</tbody></table></div>' + (j.truncated ? '<div class="iris-vu-small iris-vu-muted mt-1">Showing the newest 500 findings.</div>' : '');
                    $el.find('[data-vu="list"]').html(h).data('rows', rows);
                });
            }).catch(function (e) { $el.find('[data-vu="list"]').html('<div class="iris-vu-err">' + V.esc(e.message) + '</div>'); });
        }
        $el.on('click', '[data-vu-f]', function () {
            filter = $(this).attr('data-vu-f');
            $el.find('[data-vu-f]').removeClass('active');
            $(this).addClass('active');
            load();
        });
        var t = null;
        $el.on('input', '[data-vu="s"]', function () {
            var val = $(this).val();
            clearTimeout(t);
            t = setTimeout(function () { search = val; load(); }, 250);
        });
        $el.on('click', '[data-vu="add"]', function () {
            V.openFindingForm(Object.assign({}, o, {onSaved: changed}));
        });
        $el.on('click', '[data-vu="edit"]', function () {
            var f = ($el.find('[data-vu="list"]').data('rows') || [])[Number($(this).attr('data-i'))];
            if (!f) { return; }
            if (!o.canWrite) { window.location.href = '/vulnerabilities/' + V.id(f.vulnerability.vulnerability_id); return; }
            V.openFindingForm(Object.assign({}, o, {finding: f, onSaved: changed}));
        });
        $el.on('click', '[data-vu="hist"]', function () {
            var f = ($el.find('[data-vu="list"]').data('rows') || [])[Number($(this).attr('data-i'))];
            if (f) { V.openHistory(base + '/' + V.id(f.finding_id) + '/history', 'History · ' + f.vulnerability.identifier); }
        });
        load();
        return {reload: load};
    };

    /* ------------------------------------------------------------ war rooms */
    V.mountWarRoom = function (el, o) {
        V.css();
        var $el = $(el), base = '/api/v2/war-rooms/' + V.id(o.roomId);
        var mx = {case_id: '', tracked: false, search: ''};
        $el.html('<div class="d-flex align-items-center mb-2"><div class="iris-vu-sec m-0">Tracked in this room</div>' +
            (o.canWrite ? '<button type="button" class="btn btn-sm btn-primary ml-auto" data-vu="track">+ Track a vulnerability</button>' : '') +
            '</div><div data-vu="tracked" class="mb-4"><div class="iris-vu-muted iris-vu-small">Loading…</div></div>' +
            '<div class="iris-vu-sec">Across the room\'s cases</div>' +
            '<div class="d-flex flex-wrap align-items-center mb-2">' +
            '<select class="form-control form-control-sm mr-2 mb-1" style="max-width:240px;" data-vu="mcase" aria-label="Case"><option value="">All cases</option></select>' +
            '<input type="text" class="form-control form-control-sm mr-2 mb-1" style="max-width:220px;" data-vu="ms" aria-label="Filter" placeholder="Filter…">' +
            '<div class="form-check mb-1"><label class="form-check-label"><input class="form-check-input" type="checkbox" data-vu="mt">' +
            '<span class="form-check-sign">Tracked only</span></label></div></div>' +
            '<div data-vu="matrix"><div class="iris-vu-muted iris-vu-small">Loading…</div></div>' +
            '<div class="iris-vu-small iris-vu-muted mt-2">Counts come from the cases attached to this room that you can open.</div>');
        function loadTracked() {
            V.fetch(base + '/vulnerabilities').then(function (j) {
                var rows = Array.isArray(j.value) ? j.value : null;
                if (!V.ok(j) || !rows) { $el.find('[data-vu="tracked"]').html('<div class="iris-vu-err">' + V.esc(V.errText(j)) + '</div>'); return; }
                if (!rows.length) { $el.find('[data-vu="tracked"]').html('<div class="iris-vu-muted iris-vu-small">Nothing tracked yet.</div>'); return; }
                var h = '<div class="table-responsive"><table class="table iris-vu-table mb-0"><thead><tr><th>Vulnerability</th><th>Severity</th><th>Open</th><th>Exploited</th><th>Note</th><th></th></tr></thead><tbody>';
                rows.forEach(function (r, i) {
                    h += '<tr><td style="min-width:200px;">' + V.vulnLink(r.vulnerability) + ' ' + V.kevBadge(r.vulnerability) +
                        '<div class="iris-vu-small iris-vu-muted">' + V.esc(r.vulnerability.title) + '</div></td>' +
                        '<td>' + V.sevBadge(r.vulnerability.severity, r.vulnerability.cvss_score) + '</td>' +
                        '<td>' + Number(r.counts.open) + ' / ' + Number(r.counts.findings) + '</td><td>' + Number(r.counts.exploited) + '</td>' +
                        '<td style="min-width:200px;">' + (o.canWrite
                            ? '<textarea class="form-control form-control-sm" rows="1" data-vu="note" data-i="' + i + '" aria-label="Note">' + V.esc(r.note || '') + '</textarea>'
                            : V.esc(r.note || '—')) + '</td>' +
                        '<td class="text-right">' + (o.canWrite ? '<button type="button" class="btn btn-sm btn-link text-danger p-0" data-vu="untrack" data-i="' + i + '">Untrack</button>' : '') + '</td></tr>';
                });
                $el.find('[data-vu="tracked"]').html(h + '</tbody></table></div>').data('rows', rows);
            });
        }
        function loadMatrix() {
            var q = '?per_page=100&search=' + encodeURIComponent(mx.search) + (mx.case_id ? '&case_id=' + V.id(mx.case_id) : '') + (mx.tracked ? '&tracked=true' : '');
            V.fetch(base + '/scope/vulnerabilities' + q).then(function (j) {
                if (!V.ok(j) || !Array.isArray(j.rows)) { $el.find('[data-vu="matrix"]').html('<div class="iris-vu-err">' + V.esc(V.errText(j)) + '</div>'); return; }
                var $c = $el.find('[data-vu="mcase"]');
                if ($c.find('option').length === 1) {
                    (j.cases || []).forEach(function (c) { $c.append($('<option>').val(String(c.case_id)).text(c.case_name)); });
                }
                var cases = mx.case_id ? (j.cases || []).filter(function (c) { return String(c.case_id) === String(mx.case_id); }) : (j.cases || []);
                if (!j.rows.length) {
                    $el.find('[data-vu="matrix"]').html('<div class="iris-vu-muted iris-vu-small">' +
                        ((j.cases || []).length ? 'No vulnerability recorded in these cases.' : 'No case attached to this room that you can open.') + '</div>');
                    return;
                }
                var h = '<div class="table-responsive"><table class="table iris-vu-table iris-vu-matrix mb-0"><thead><tr><th>Vulnerability</th><th>Severity</th>';
                cases.forEach(function (c) {
                    h += '<th class="text-center"><a href="/vulnerabilities?case=' + V.id(c.case_id) + '" title="Every vulnerability in this case">' + V.esc(c.case_name) + '</a></th>';
                });
                h += '<th class="text-center">Total open</th></tr></thead><tbody>';
                j.rows.forEach(function (r) {
                    h += '<tr><td style="min-width:200px;">' + V.vulnLink(r.vulnerability) + ' ' + V.kevBadge(r.vulnerability) +
                        (r.tracked ? ' <span class="iris-vu-pill iris-vu-kind" title="Tracked in this room">tracked</span>' : '') +
                        '<div class="iris-vu-small iris-vu-muted">' + V.esc(r.vulnerability.title) + '</div></td><td>' +
                        V.sevBadge(r.vulnerability.severity, r.vulnerability.cvss_score) + '</td>';
                    cases.forEach(function (c) {
                        var k = r.per_case[String(c.case_id)];
                        h += '<td class="iris-vu-cell">' + (k ? '<span title="open / findings">' + Number(k.open) + ' / ' + Number(k.findings) + '</span>' +
                            (k.exploited ? ' <span class="iris-vu-pill iris-vu-ex-exploited" title="exploited">' + Number(k.exploited) + '</span>' : '')
                            : '<span class="iris-vu-muted">·</span>') + '</td>';
                    });
                    h += '<td class="iris-vu-cell font-weight-bold">' + Number(r.totals.open) + '</td></tr>';
                });
                $el.find('[data-vu="matrix"]').html(h + '</tbody></table></div>');
            });
        }
        $el.on('change', '[data-vu="mcase"]', function () { mx.case_id = $(this).val(); loadMatrix(); });
        $el.on('change', '[data-vu="mt"]', function () { mx.tracked = $(this).is(':checked'); loadMatrix(); });
        var t = null;
        $el.on('input', '[data-vu="ms"]', function () {
            var val = $(this).val(); clearTimeout(t); t = setTimeout(function () { mx.search = val; loadMatrix(); }, 250);
        });
        $el.on('change', '[data-vu="note"]', function () {
            var r = ($el.find('[data-vu="tracked"]').data('rows') || [])[Number($(this).attr('data-i'))];
            if (!r) { return; }
            V.fetch(base + '/vulnerabilities/' + V.id(r.vulnerability.vulnerability_id), 'PATCH', {note: $(this).val()}).then(function (j) {
                if (!V.ok(j)) { window.alert(V.errText(j)); }
            });
        });
        $el.on('click', '[data-vu="untrack"]', function () {
            var r = ($el.find('[data-vu="tracked"]').data('rows') || [])[Number($(this).attr('data-i'))];
            if (!r || !window.confirm('Stop tracking ' + r.vulnerability.identifier + ' in this room?')) { return; }
            V.fetch(base + '/vulnerabilities/' + V.id(r.vulnerability.vulnerability_id), 'DELETE').then(function (j) {
                if (!V.ok(j)) { window.alert(V.errText(j)); return; }
                loadTracked(); loadMatrix();
            });
        });
        $el.on('click', '[data-vu="track"]', function () {
            var $m = V.modal({title: 'Track a vulnerability in this room', body: '<div class="form-group"><label>Vulnerability</label><div data-vu="chooser"></div></div>' +
                    '<div class="form-group mb-0"><label for="vu-tnote">Note</label><textarea class="form-control" id="vu-tnote" rows="2"></textarea></div>',
                footer: '<button type="button" class="btn btn-outline-secondary" data-dismiss="modal">Cancel</button><button type="button" class="btn btn-primary" data-vu="ok">Track</button>'});
            var ch = V.chooser($m.find('[data-vu="chooser"]'));
            $m.on('click', '[data-vu="ok"]', function () {
                var p = ch.payload();
                if (!p) { V.setErr($m, 'Choose a vulnerability (or quick-add one by its identifier).'); return; }
                p.note = $m.find('#vu-tnote').val();
                V.fetch(base + '/vulnerabilities', 'POST', p).then(function (j) {
                    if (!V.ok(j)) { V.setErr($m, V.errText(j)); return; }
                    $m.modal('hide'); loadTracked(); loadMatrix();
                });
            });
        });
        loadTracked(); loadMatrix();
        return {reload: function () { loadTracked(); loadMatrix(); }};
    };

    window.IrisVuln = V;
})();

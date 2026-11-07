/* Intel -> Vulnerabilities: the catalogue list and an entry's detail page (iris-ng 2026-11-07).
 * Needs vuln_common.js (window.IrisVuln). The page tells which view it is with
 * <div id="iris-vu-page" data-view="list"> or data-view="detail" data-id="N">. */
(function () {
    'use strict';
    var V = window.IrisVuln;
    var API = '/api/v2/manage/vulnerabilities';
    var $page = $('#iris-vu-page');
    if (!$page.length || !V) { return; }
    V.css();

    /* ================================================================ list */
    function listView() {
        /* ?case=<id> (the Assets page and the war-room matrix link here) starts on that case */
        var caseParam = /[?&]case=(\d+)/.exec(window.location.search);
        var st = {page: 1, per_page: 25, order_by: '', sort_dir: '', search: '', severity: '', kind: '', vendor: '', product: '',
                  kev: '', private: '', affected: false, 'case': caseParam ? V.id(caseParam[1]) : ''};
        var voc = null, techs = [];
        var $tbl = $('#iris-vu-table'), $count = $('#iris-vu-count'), $pager = $('#iris-vu-pager');
        var $case = $('#iris-vu-f-case');

        /* The Case filter offers the cases the viewer can open that hold findings; a case named by
           the URL or by the list's answer joins the options when it has none. */
        function addCaseOption(id, label) {
            id = V.id(id);
            if (!id || $case.find('option').filter(function () { return this.value === id; }).length) { return; }
            $case.append($('<option>').val(id).text(label || ('Case #' + id)));
        }
        function loadCases() {
            V.fetch(API + '/cases').then(function (j) {
                var rows = Array.isArray(j.value) ? j.value : [];
                $case.find('option:not(:first)').remove();
                rows.forEach(function (c) {
                    addCaseOption(c.case_id, (c.case_name || ('Case #' + c.case_id)) + ' · ' + Number(c.open || 0) + ' open');
                });
                if (st['case']) { addCaseOption(st['case']); }
                $case.val(st['case'] || '');
            });
        }
        function syncCaseUrl() {
            /* absolute, from the page's own address: a relative URL would resolve against any <base href> */
            var url = window.location.href.split(/[?#]/)[0] + (st['case'] ? '?case=' + st['case'] : '');
            try { window.history.replaceState(null, '', url); } catch (e) { /* not essential */ }
        }
        $case.on('change', function () {
            st['case'] = V.id($(this).val()) || ''; st.page = 1; syncCaseUrl(); load();
        });

        function chips(name, $host) {
            $host.on('click', 'button', function () {
                st[name] = $(this).attr('data-v');
                $host.find('button').removeClass('active');
                $(this).addClass('active');
                st.page = 1; load();
            });
        }
        chips('kev', $('#iris-vu-f-kev'));
        chips('private', $('#iris-vu-f-private'));
        $('#iris-vu-f-affected').on('click', function () {
            st.affected = !st.affected; $(this).toggleClass('active', st.affected); st.page = 1; load();
        });
        $('#iris-vu-f-severity,#iris-vu-f-kind,#iris-vu-f-vendor,#iris-vu-f-product').on('change', function () {
            st[this.id.replace('iris-vu-f-', '')] = $(this).val(); st.page = 1; load();
        });
        $('#iris-vu-search-btn').on('click', function () { st.search = $('#iris-vu-search').val(); st.page = 1; load(); });
        $('#iris-vu-search').on('keydown', function (e) { if (e.key === 'Enter') { st.search = $(this).val(); st.page = 1; load(); } });
        $('#iris-vu-refresh').on('click', function () { loadTech(); loadCases(); load(); });
        $('#iris-vu-new').on('click', function () {
            V.openVulnForm({onSaved: function (v) { window.location.href = '/vulnerabilities/' + V.id(v.vulnerability_id); }});
        });
        $tbl.on('click', 'th[data-sort]', function () {
            var k = $(this).attr('data-sort');
            if (st.order_by === k) { st.sort_dir = st.sort_dir === 'asc' ? 'desc' : 'asc'; }
            else { st.order_by = k; st.sort_dir = (k === 'identifier' || k === 'title') ? 'asc' : 'desc'; }
            st.page = 1; load();
        });
        $tbl.on('keydown', 'th[data-sort]', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $(this).trigger('click'); } });
        $tbl.on('click', 'tr.iris-vu-row', function (e) {
            if ($(e.target).closest('a,button,.dropdown-menu').length) { return; }
            var id = V.id($(this).attr('data-id'));
            if (id) { window.location.href = '/vulnerabilities/' + id; }
        });
        $tbl.on('click', '[data-act]', function (e) {
            e.preventDefault();
            var rows = $tbl.data('rows') || [];
            var v = rows[Number($(this).attr('data-i'))];
            if (!v) { return; }
            var act = $(this).attr('data-act');
            if (act === 'edit') { V.openVulnForm({vuln: v, onSaved: load}); }
            else if (act === 'merge') { V.openMerge({vuln: v, onMerged: load}); }
            else if (act === 'delete') { del(v, load); }
        });
        $pager.on('click', '[data-page]', function (e) { e.preventDefault(); st.page = Number($(this).attr('data-page')); load(); });

        function loadTech() {
            V.fetch(API + '/technologies').then(function (j) {
                techs = Array.isArray(j.value) ? j.value : [];
                var vendors = {}, products = {};
                techs.forEach(function (t) { if (t.vendor) { vendors[t.vendor] = 1; } products[t.product] = 1; });
                var fill = function ($s, keys, cur) {
                    $s.find('option:not(:first)').remove();
                    Object.keys(keys).sort(function (a, b) { return a.toLowerCase() < b.toLowerCase() ? -1 : 1; }).forEach(function (k) {
                        $s.append($('<option>').val(k).text(k));
                    });
                    $s.val(cur || '');
                };
                fill($('#iris-vu-f-vendor'), vendors, st.vendor);
                fill($('#iris-vu-f-product'), products, st.product);
            });
        }
        function sortMark(k) {
            if (st.order_by !== k) { return ' <span class="iris-vu-muted" aria-hidden="true">↕</span>'; }
            return st.sort_dir === 'asc' ? ' <span aria-hidden="true">↑</span>' : ' <span aria-hidden="true">↓</span>';
        }
        function techCell(v) {
            var p = (v.affected_products || [])[0];
            if (!p) { return '<span class="iris-vu-muted">—</span>'; }
            return (p.vendor ? '<span class="iris-vu-muted">' + V.esc(p.vendor) + '</span> ' : '') + V.esc(p.product) +
                ((v.affected_products || []).length > 1 ? ' <span class="iris-vu-muted">+' + ((v.affected_products.length) - 1) + '</span>' : '');
        }
        function load() {
            var q = {page: st.page, per_page: st.per_page, search: st.search, severity: st.severity, kind: st.kind,
                     vendor: st.vendor, product: st.product, kev: st.kev, private: st.private};
            if (st.order_by) { q.order_by = st.order_by; q.sort_dir = st.sort_dir; }
            if (st.affected) { q.affected = 'true'; }
            if (st['case']) { q.case_id = st['case']; }
            var qs = Object.keys(q).filter(function (k) { return q[k] !== '' && q[k] != null; })
                .map(function (k) { return k + '=' + encodeURIComponent(q[k]); }).join('&');
            $tbl.find('tbody').html('<tr><td colspan="12" class="iris-vu-muted">Loading…</td></tr>');
            V.fetch(API + '?' + qs).then(function (j) {
                if (!V.ok(j) || !Array.isArray(j.data)) {
                    $tbl.find('tbody').html('<tr><td colspan="12" class="iris-vu-err">Could not load the catalogue: ' + V.esc(V.errText(j)) + '</td></tr>');
                    return;
                }
                var L = voc.L, rows = j.data;
                if (j['case'] && j['case'].case_id) { addCaseOption(j['case'].case_id, j['case'].case_name); $case.val(V.id(j['case'].case_id)); }
                var head = '<tr><th data-sort="identifier" tabindex="0" role="button">Identifier' + sortMark('identifier') + '</th>' +
                    '<th data-sort="title" tabindex="0" role="button">Title' + sortMark('title') + '</th><th>Technology</th><th>Kind</th>' +
                    '<th data-sort="severity" tabindex="0" role="button">Severity' + sortMark('severity') + '</th>' +
                    '<th data-sort="cvss_score" tabindex="0" role="button">CVSS' + sortMark('cvss_score') + '</th>' +
                    '<th data-sort="epss_score" tabindex="0" role="button">EPSS' + sortMark('epss_score') + '</th>' +
                    '<th>KEV</th><th>Exploit</th><th>Patch</th><th>Exposure</th><th><span class="sr-only">Actions</span></th></tr>';
                $tbl.find('thead').html(head);
                if (!rows.length) {
                    $tbl.find('tbody').html('<tr><td colspan="12" class="iris-vu-muted">' +
                        (j.total === 0 && !qs.match(/search=|severity=|kind=|vendor=|product=|kev=|private=|affected=|case_id=/)
                            ? 'The catalogue is empty. Use “New vulnerability” to add the first entry.'
                            : 'No entry matches these filters.') + '</td></tr>');
                } else {
                    var h = '';
                    rows.forEach(function (v, i) {
                        var c = v.counts || {}, cc = v.case_counts;
                        /* with the Case filter on, Exposure counts that case's findings */
                        var expo = cc
                            ? '<span class="iris-vu-small">' + Number(cc.open || 0) + ' open in this case</span>' +
                              '<div class="iris-vu-small iris-vu-muted">on ' + Number(cc.assets || 0) + ' asset(s) · ' + Number(cc.findings || 0) + ' finding(s)</div>'
                            : '<span class="iris-vu-small">' + Number(c.open || 0) + ' open</span>' +
                              '<div class="iris-vu-small iris-vu-muted">' + Number(c.cases || 0) + ' case(s) · ' + Number(c.registry_assets || 0) + ' registry</div>';
                        h += '<tr class="iris-vu-row" data-id="' + V.id(v.vulnerability_id) + '">' +
                            '<td class="text-nowrap">' + V.vulnLink(v) + ' ' + V.privBadge(v) + '</td>' +
                            '<td style="min-width:200px;">' + V.esc(v.title) + '</td><td>' + techCell(v) + '</td>' +
                            '<td>' + V.esc(L.kind[v.kind] || v.kind) + '</td>' +
                            '<td>' + V.sevBadge(v.severity) + '</td><td class="iris-vu-mono">' + V.score(v.cvss_score) + '</td>' +
                            '<td class="iris-vu-mono">' + V.pct(v.epss_score) + '</td><td>' + (V.kevBadge(v) || '<span class="iris-vu-muted">—</span>') + '</td>' +
                            '<td>' + V.esc(L.exploit[v.exploit_maturity] || v.exploit_maturity) + '</td>' +
                            '<td>' + V.esc(L.patch[v.patch_availability] || v.patch_availability) + '</td>' +
                            '<td class="text-nowrap">' + expo + '</td>' +
                            '<td class="text-right"><div class="dropdown"><button type="button" class="btn btn-sm btn-link" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" aria-label="Actions for ' +
                            V.esc(v.identifier) + '">⋯</button><div class="dropdown-menu dropdown-menu-right">' +
                            '<a class="dropdown-item" href="/vulnerabilities/' + V.id(v.vulnerability_id) + '">Open</a>' +
                            '<a class="dropdown-item" href="#" data-act="edit" data-i="' + i + '">Edit</a>' +
                            (voc.can_merge ? '<a class="dropdown-item" href="#" data-act="merge" data-i="' + i + '">Merge into…</a>' +
                                '<a class="dropdown-item text-danger" href="#" data-act="delete" data-i="' + i + '">Delete</a>' : '') +
                            '</div></div></td></tr>';
                    });
                    $tbl.find('tbody').html(h);
                }
                $tbl.data('rows', rows);
                var from = j.total ? (j.current_page - 1) * st.per_page + 1 : 0, to = Math.min(j.total, j.current_page * st.per_page);
                $count.text(from + '–' + to + ' of ' + j.total);
                var p = '';
                if (j.last_page > 1) {
                    p += '<li class="page-item' + (j.current_page <= 1 ? ' disabled' : '') + '"><a class="page-link" href="#" data-page="' + (j.current_page - 1) + '">‹</a></li>';
                    for (var n = Math.max(1, j.current_page - 3); n <= Math.min(j.last_page, j.current_page + 3); n++) {
                        p += '<li class="page-item' + (n === j.current_page ? ' active' : '') + '"><a class="page-link" href="#" data-page="' + n + '">' + n + '</a></li>';
                    }
                    p += '<li class="page-item' + (j.current_page >= j.last_page ? ' disabled' : '') + '"><a class="page-link" href="#" data-page="' + (j.current_page + 1) + '">›</a></li>';
                }
                $pager.html(p);
            });
        }
        V.vocab().then(function (v) {
            voc = v;
            var sev = $('#iris-vu-f-severity'), kind = $('#iris-vu-f-kind');
            (v.severities || []).forEach(function (s) { sev.append($('<option>').val(s.value).text(s.label)); });
            (v.kinds || []).forEach(function (s) { kind.append($('<option>').val(s.value).text(s.label)); });
            loadTech(); loadCases(); load();
        }).catch(function (e) { $tbl.find('tbody').html('<tr><td class="iris-vu-err">' + V.esc(e.message) + '</td></tr>'); });
    }

    function del(v, after) {
        var c = v.counts || {};
        var msg = 'Delete ' + v.identifier + '?' + (c.findings ? '\n\nIts ' + c.findings + ' finding(s) you can see (and any you cannot) are deleted with it. ' +
            'To keep them, merge it into another entry instead.' : '') + '\n\nThis cannot be undone.';
        if (!window.confirm(msg)) { return; }
        V.fetch(API + '/' + V.id(v.vulnerability_id), 'DELETE').then(function (j) {
            if (!V.ok(j)) { window.alert(V.errText(j)); return; }
            after();
        });
    }

    /* ================================================================ detail */
    function detailView(vid) {
        var voc = null, cur = null;
        var $body = $('#iris-vu-detail');
        function kv(k, v) { return '<div class="iris-vu-kv"><div class="k">' + V.esc(k) + '</div><div class="v">' + v + '</div></div>'; }
        function dash(x) { return (x == null || x === '' || (Array.isArray(x) && !x.length)) ? '<span class="iris-vu-muted">—</span>' : null; }
        function render(v) {
            cur = v;
            var L = voc.L, c = v.counts || {};
            var cve = (v.enrichment || {}).cve_org || null;
            $('#iris-vu-crumb').text(v.identifier);
            document.title = v.identifier + ' · Vulnerabilities';
            var canSync = !v.is_private && V.isCve(v.identifier) && voc.cve_lookup_enabled;
            $('#iris-vu-sync').toggle(!!canSync);
            $('#iris-vu-merge,#iris-vu-delete').toggle(!!voc.can_merge);
            var syncLine = cve && cve.synced_at
                ? 'Last synced from cve.org: ' + V.fmtDate(cve.synced_at) + (cve.date_updated ? ' · record updated ' + V.fmtDate(cve.date_updated).replace(/ \d\d:\d\d UTC$/, '') : '') +
                  (cve.assigner ? ' · assigner ' + V.esc(cve.assigner) : '') + (cve.state && cve.state !== 'PUBLISHED' ? ' · <b>record ' + V.esc(cve.state) + '</b>' : '')
                : (V.isCve(v.identifier) && !v.is_private ? 'Not synced from cve.org.' : '');
            var refs = (v.reference_urls || []).map(function (u) {
                var ok = V.safeUrl(u);
                return '<div class="iris-vu-small">' + (ok ? '<a href="' + V.esc(ok) + '" target="_blank" rel="noopener noreferrer">' + V.esc(u) + '</a>' : V.esc(u)) + '</div>';
            }).join('');
            var prods = (v.affected_products || []).length
                ? '<div class="table-responsive"><table class="table iris-vu-table mb-0"><thead><tr><th>Vendor</th><th>Product</th><th>Versions</th></tr></thead><tbody>' +
                  v.affected_products.map(function (p) {
                      return '<tr><td>' + (p.vendor ? V.esc(p.vendor) : '<span class="iris-vu-muted">—</span>') + '</td><td>' + V.esc(p.product) +
                          '</td><td class="iris-vu-mono iris-vu-small">' + (p.versions ? V.esc(p.versions) : '<span class="iris-vu-muted">—</span>') + '</td></tr>';
                  }).join('') + '</tbody></table></div>'
                : '<div class="iris-vu-muted iris-vu-small">None recorded.</div>';
            var h =
                '<div class="mb-2">' + V.sevBadge(v.severity, v.cvss_score) + ' ' + V.kevBadge(v) + ' <span class="iris-vu-pill iris-vu-kind">' +
                V.esc(L.kind[v.kind] || v.kind) + '</span> ' + V.privBadge(v) + '</div>' +
                '<h2 class="h4 mb-1" id="iris-vu-title">' + V.esc(v.title) + '</h2>' +
                '<div class="iris-vu-small iris-vu-muted mb-3">' + syncLine + '</div>' +
                '<div class="iris-vu-sec">Description</div><div class="card"><div class="card-body iris-vu-desc">' +
                (v.description ? V.esc(v.description) : '<span class="iris-vu-muted">No description.</span>') + '</div></div>' +
                '<div class="row"><div class="col-lg-6"><div class="iris-vu-sec">Scoring</div><div class="card"><div class="card-body">' +
                kv('CVSS', v.cvss_score != null ? V.score(v.cvss_score) + (v.cvss_version ? ' <span class="iris-vu-muted">(v' + V.esc(v.cvss_version) + ')</span>' : '') : dash(null)) +
                kv('Vector', v.cvss_vector ? '<span class="iris-vu-mono iris-vu-small">' + V.esc(v.cvss_vector) + '</span>' : dash(null)) +
                kv('Severity', V.esc(L.severity[v.severity] || v.severity) + (v.severity_auto ? ' <span class="iris-vu-muted">(from the score)</span>' : ' <span class="iris-vu-muted">(set by hand)</span>')) +
                kv('EPSS', v.epss_score != null ? V.pct(v.epss_score) + (v.epss_percentile != null ? ' <span class="iris-vu-muted">(percentile ' + V.pct(v.epss_percentile) + ')</span>' : '') : dash(null)) +
                kv('EPSS date', v.epss_date ? V.esc(v.epss_date) : dash(null)) +
                kv('Exploit maturity', V.esc(L.exploit[v.exploit_maturity] || v.exploit_maturity)) +
                kv('Patch', V.esc(L.patch[v.patch_availability] || v.patch_availability)) +
                kv('CISA KEV', v.kev ? 'Added ' + V.esc(v.kev_date_added || '—') + ' · due ' + V.esc(v.kev_due_date || '—') +
                    (v.kev_ransomware ? ' · known ransomware use' : '') : 'Not listed') +
                '</div></div></div><div class="col-lg-6"><div class="iris-vu-sec">Record</div><div class="card"><div class="card-body">' +
                kv('CWEs', dash(v.cwes) || (v.cwes || []).map(function (x) {
                    var m = /^CWE-(\d+)$/.exec(x);
                    return m ? '<a class="iris-vu-mono" href="https://cwe.mitre.org/data/definitions/' + m[1] + '.html" target="_blank" rel="noopener noreferrer">' + V.esc(x) + '</a>'
                        : '<span class="iris-vu-mono">' + V.esc(x) + '</span>';
                }).join(', ')) +
                kv('Aliases', dash(v.aliases) || (v.aliases || []).map(function (a) { return '<span class="iris-vu-mono">' + V.esc(a) + '</span>'; }).join(', ')) +
                kv('Tags', dash(v.tags) || (v.tags || []).map(V.esc).join(', ')) +
                kv('TLP', v.tlp_name ? V.esc(v.tlp_name) : dash(null)) +
                kv('Published', v.published_at ? V.esc(v.published_at) : dash(null)) +
                kv('Modified', v.modified_at ? V.esc(v.modified_at) : dash(null)) +
                kv('Origin', v.source === 'cve.org' ? 'Filled from cve.org' : 'Manual') +
                kv('Created', V.fmtDate(v.created_at) + (v.created_by_name ? ' by ' + V.esc(v.created_by_name) : '')) +
                kv('Updated', V.fmtDate(v.updated_at) + (v.updated_by_name ? ' by ' + V.esc(v.updated_by_name) : '')) +
                kv('UUID', '<span class="iris-vu-mono iris-vu-small">' + V.esc(v.vulnerability_uuid) + '</span>') +
                '</div></div></div></div>' +
                '<div class="iris-vu-sec">Affected products</div><div class="card"><div class="card-body p-2">' + prods + '</div></div>' +
                '<div class="iris-vu-sec">References</div><div class="card"><div class="card-body">' + (refs || '<span class="iris-vu-muted iris-vu-small">None recorded.</span>') + '</div></div>' +
                '<div class="iris-vu-sec">Exposure <span class="text-none" style="text-transform:none;letter-spacing:0;" id="iris-vu-exp-line">' +
                Number(c.cases || 0) + ' case(s) · ' + Number(c.findings || 0) + ' finding(s) · ' + Number(c.registry_assets || 0) + ' registry entr(ies) · ' +
                Number(c.open || 0) + ' open · ' + Number(c.exploited || 0) + ' exploited</span></div>' +
                '<div class="iris-vu-small iris-vu-muted mb-2">Only the cases you can open and the registry entries of your customers are counted.</div>' +
                '<div id="iris-vu-exposure"><div class="iris-vu-muted iris-vu-small">Loading…</div></div>';
            $body.html(h);
            loadExposure();
        }
        function loadExposure() {
            V.fetch(API + '/' + vid + '/exposure').then(function (j) {
                var $e = $('#iris-vu-exposure');
                if (!V.ok(j) || !Array.isArray(j.cases)) { $e.html('<div class="iris-vu-err">' + V.esc(V.errText(j)) + '</div>'); return; }
                var L = voc.L, h = '<div class="iris-vu-small font-weight-bold mb-1">Cases</div>';
                if (!j.cases.length) { h += '<div class="iris-vu-muted iris-vu-small mb-3">Not recorded in any case you can open.</div>'; }
                else {
                    h += '<div class="table-responsive mb-3"><table class="table iris-vu-table mb-0"><thead><tr><th>Case</th><th>Asset</th><th>Remediation</th><th>Exploitation</th><th>Due</th></tr></thead><tbody>';
                    j.cases.forEach(function (c) {
                        c.findings.forEach(function (f, i) {
                            /* the case opens the catalogue on that case; the asset opens its
                               Vulnerabilities tab on the case's Assets page */
                            var aid = V.id(f.asset_id), cid = V.id(c.case_id);
                            h += '<tr><td>' + (i === 0 ? '<a href="/vulnerabilities?case=' + cid + '" title="Every vulnerability in this case">' + V.esc(c.case_name) + '</a>' +
                                (c.client_name ? '<div class="iris-vu-small iris-vu-muted">' + V.esc(c.client_name) + '</div>' : '') : '') + '</td>' +
                                '<td>' + (aid && f.asset_name
                                    ? '<a href="/case/assets?cid=' + cid + '&asset=' + aid + '&tab=vulns">' + V.esc(f.asset_name) + '</a>'
                                    : '<span class="iris-vu-muted">—</span>') + '</td>' +
                                '<td>' + V.statusBadge(L, f.remediation_status) + '</td><td>' + V.exploitBadge(L, f.exploitation_status) + '</td>' +
                                '<td class="' + (f.overdue ? 'iris-vu-overdue' : '') + '">' + (f.due_date ? V.esc(f.due_date) : '<span class="iris-vu-muted">—</span>') + '</td></tr>';
                        });
                    });
                    h += '</tbody></table></div>';
                }
                h += '<div class="iris-vu-small font-weight-bold mb-1">Registry entries</div>';
                if (!j.registry.length) { h += '<div class="iris-vu-muted iris-vu-small mb-3">Not recorded on any registry entry you can see.</div>'; }
                else {
                    h += '<div class="table-responsive mb-3"><table class="table iris-vu-table mb-0"><thead><tr><th>Asset</th><th>Customer</th><th>Criticality</th><th>Remediation</th><th>Exploitation</th><th>Due</th></tr></thead><tbody>';
                    j.registry.forEach(function (r) {
                        h += '<tr><td><a href="/manage/customer-assets?asset=' + V.id(r.customer_asset_id) + '">' + V.esc(r.asset_name) + '</a></td><td>' +
                            V.esc(r.customer_name || '—') + '</td><td>' + V.esc(r.criticality ? r.criticality.charAt(0).toUpperCase() + r.criticality.slice(1) : 'Unknown') + '</td>' +
                            '<td>' + V.statusBadge(L, r.remediation_status) + '</td><td>' + V.exploitBadge(L, r.exploitation_status) + '</td>' +
                            '<td class="' + (r.overdue ? 'iris-vu-overdue' : '') + '">' + (r.due_date ? V.esc(r.due_date) : '<span class="iris-vu-muted">—</span>') + '</td></tr>';
                    });
                    h += '</tbody></table></div>';
                }
                h += '<div class="iris-vu-small font-weight-bold mb-1">Named as an IOC</div>';
                if (!j.ioc_mentions.length) { h += '<div class="iris-vu-muted iris-vu-small">No case you can open holds this identifier (or an alias) as a vulnerability IOC.</div>'; }
                else {
                    h += '<div class="iris-vu-small">' + j.ioc_mentions.map(function (m) {
                        return '<a href="/case/ioc?cid=' + V.id(m.case_id) + '&shared=' + V.id(m.ioc_id) + '">' + V.esc(m.case_name) + '</a> · <span class="iris-vu-mono">' + V.esc(m.ioc_value) + '</span>';
                    }).join('<br>') + '</div>';
                }
                $e.html(h);
            });
        }
        function load() {
            V.fetch(API + '/' + vid).then(function (j) {
                if (!V.ok(j) || !j.vulnerability_id) {
                    $body.html('<div class="iris-vu-err">' + (j.__status === 404 ? 'This entry does not exist (it may have been merged or deleted).' : V.esc(V.errText(j))) + '</div>');
                    $('#iris-vu-actions').hide();
                    return;
                }
                render(j);
            });
        }
        $('#iris-vu-refresh').on('click', load);
        $('#iris-vu-edit').on('click', function () { if (cur) { V.openVulnForm({vuln: cur, onSaved: render}); } });
        $('#iris-vu-merge').on('click', function () {
            if (cur) { V.openMerge({vuln: cur, onMerged: function (t) { window.location.href = '/vulnerabilities/' + V.id(t.vulnerability_id); }}); }
        });
        $('#iris-vu-delete').on('click', function () { if (cur) { del(cur, function () { window.location.href = '/vulnerabilities'; }); } });
        function sync(force) {
            var $msg = $('#iris-vu-sync-msg').removeClass('iris-vu-err').text('Syncing from cve.org…');
            V.fetch(API + '/' + vid + '/sync', 'POST', {force: !!force}).then(function (j) {
                if (!V.ok(j)) { $msg.addClass('iris-vu-err').text(V.errText(j, 'The sync failed.')); return; }
                render(j);
                var lab = function (a) { return a.map(function (x) { return x.replace(/_/g, ' '); }).join(', '); };
                var t = (j.updated_fields || []).length ? 'Updated: ' + lab(j.updated_fields) + '.' : 'Already up to date.';
                $msg.html(V.esc(t) + ((j.kept_fields || []).length
                    ? ' Kept local edits: ' + V.esc(lab(j.kept_fields)) + '. <a href="#" id="iris-vu-sync-force">Overwrite them with cve.org</a>' : ''));
            });
        }
        $('#iris-vu-sync').on('click', function () { sync(false); });
        $(document).on('click', '#iris-vu-sync-force', function (e) {
            e.preventDefault();
            if (window.confirm('Replace your local edits with the cve.org values?')) { sync(true); }
        });
        V.vocab().then(function (v) { voc = v; load(); }).catch(function (e) { $body.html('<div class="iris-vu-err">' + V.esc(e.message) + '</div>'); });
    }

    if ($page.attr('data-view') === 'detail') { detailView(V.id($page.attr('data-id'))); } else { listView(); }
})();

/* IrisCaseQueue - the Overview page's case queue (iris-ng, 2026-11-08).
 *
 * The server filters, sorts, pages and counts (GET /api/v2/case-queue); this script draws the answer, keeps the
 * query in the URL, and drives the side panel (GET /api/v2/case-queue/cases/<id>). The first frame comes from the
 * page itself (#cq-state, business/case_queue.page_state); null there means the read failed, and the script fetches
 * it instead. The stage track saves through PUT /api/v2/cases/<id> - the case header's state menu does the same,
 * with the same reviewer-before-close rule (#84, enforced in the UI only). Saved filters are the /filters routes,
 * filter_type "cases".
 *
 * Anything read back from the page (data-* attributes, an input's value) is re-derived before it reaches markup or a
 * URL: looked up in the vocabulary, or parsed as a number (code scanning #48 - #50).
 */
(function () {
    'use strict';

    var STORE = 'irisCaseQueue';
    var DENSITIES = ['comfortable', 'compact'];
    var SEV_SLUGS = ['critical', 'high', 'medium', 'low', 'informational', 'unspecified'];
    var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    var SVG = function (paths, cls) {
        return '<svg class="' + (cls || 'cq-i') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths + '</svg>';
    };
    /* Lucide icons (ISC). */
    var ICONS = {
        critical: '<path d="M12 16h.01"/><path d="M12 8v4"/><path d="M15.312 2a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 1-1.414-.586l-4.688-4.688A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688A2 2 0 0 1 8.688 2z"/>',
        high: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
        medium: '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
        low: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
        informational: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
        unspecified: '<circle cx="12" cy="12" r="10"/>',
        external: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
        folder: '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>',
        check: '<path d="M20 6 9 17l-5-5"/>',
        clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
        back: '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>'
    };

    var Q = {
        st: null, root: null, fb: null,
        q: '', closed: false, page: 1, per: 25, sort: 'age', dir: 'asc', tree: blank(), sf: null,
        density: 'comfortable', selected: null,
        result: null, kpis: null, error: null, loading: false,
        detail: null, detailErr: null, detailLoading: false, cache: {},
        saved: null, savedErr: null, seq: 0, dseq: 0, searchTimer: null
    };

    function blank() { return {logic: 'and', items: []}; }
    function $(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
            return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
        });
    }
    function num(v) {
        var s = String(v === null || v === undefined ? '' : v);
        return /^\d{1,12}$/.test(s) ? parseInt(s, 10) : null;
    }
    function pick(list, v, fallback) { var i = list.indexOf(v); return i === -1 ? fallback : list[i]; }
    function narrow() { return !!(window.matchMedia && window.matchMedia('(max-width: 1199px)').matches); }

    function prefs(update) {
        var cur = {};
        try { cur = JSON.parse(window.localStorage.getItem(STORE) || '{}') || {}; } catch (e) { cur = {}; }
        if (update) {
            Object.keys(update).forEach(function (k) { cur[k] = update[k]; });
            try { window.localStorage.setItem(STORE, JSON.stringify(cur)); } catch (e) { /* private window */ }
        }
        return cur;
    }

    function csrf() { var e = $('csrf_token'); return e ? e.value : ''; }
    function cid() { var m = /[?&]cid=(\d{1,12})(?:&|$)/.exec(window.location.search); return m ? m[1] : null; }

    function api(url, opts) {
        var o = {credentials: 'same-origin', headers: {'Accept': 'application/json'}};
        Object.keys(opts || {}).forEach(function (k) { o[k] = opts[k]; });
        if (o.json !== undefined) {
            o.headers['Content-Type'] = 'application/json';
            o.body = JSON.stringify(o.json);
            delete o.json;
        }
        return window.fetch(url, o).then(function (r) {
            return r.text().then(function (t) {
                var body = null;
                try { body = t ? JSON.parse(t) : null; } catch (e) { body = null; }
                return {ok: r.ok, status: r.status, body: body};
            });
        }, function () { return {ok: false, status: 0, body: null}; });
    }
    function legacyUrl(path) { var c = cid(); return path + (c ? (path.indexOf('?') === -1 ? '?' : '&') + 'cid=' + c : ''); }
    function message(r, fallback) {
        var b = r && r.body;
        return (b && typeof b.message === 'string' && b.message) ? b.message : fallback + (r && r.status ? ' (HTTP ' + r.status + ')' : '');
    }

    /* ------------------------------------------------------------ vocabulary helpers */

    function V() { return Q.st.vocab; }
    function sortKeys() { return Object.keys(V().sorts); }
    function kpiKeys() { return V().kpis.map(function (k) { return k.key; }); }
    function stages() { return V().stages; }
    function sevSlug(name) { return pick(SEV_SLUGS, String(name || '').toLowerCase(), 'unspecified'); }
    function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

    function fmtDay(iso) {
        var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
        if (!m) { return '—'; }
        return MONTHS[parseInt(m[2], 10) - 1] + ' ' + parseInt(m[3], 10) + ', ' + m[1];
    }
    function fmtStamp(iso) {
        var m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso || '');
        return m ? m[1] + ' ' + m[2] + ' UTC' : '';
    }
    function days(n) { return n === null || n === undefined ? '—' : (n === 0 ? 'today' : n + 'd'); }
    function initials(name) {
        var parts = String(name || '').trim().split(/[\s._-]+/).filter(Boolean);
        if (!parts.length) { return '??'; }
        if (parts.length === 1) { return parts[0].slice(0, 2).toUpperCase(); }
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }

    function sevPill(sev) {
        if (!sev) { return ''; }
        var slug = sevSlug(sev.name);
        return '<span class="cq-sev cq-sev--' + slug + '">' + SVG(ICONS[slug], 'cq-i cq-i--sev') + esc(sev.name) + '</span>';
    }
    function owner(o) {
        if (!o) { return '<span class="cq-avatar cq-avatar--none" aria-hidden="true">?</span><span class="cq-owner-none">Unassigned</span>'; }
        return '<span class="cq-avatar" aria-hidden="true">' + esc(initials(o.name)) + '</span><span class="cq-owner-name">' + esc(o.name) + '</span>';
    }
    function pipe(stage) {
        var html = '';
        for (var i = 0; i < stages().length; i++) {
            var cls = stage === null || stage === undefined ? '' : (i < stage ? ' cq-seg--done' : (i === stage ? ' cq-seg--now' : ''));
            html += '<span class="cq-seg' + cls + '"></span>';
        }
        return '<span class="cq-pipe" aria-hidden="true">' + html + '</span>';
    }

    /* ------------------------------------------------------------ URL + request */

    function listQuery() {
        var p = new URLSearchParams();
        if (Q.q) { p.set('q', Q.q); }
        if (Q.closed) { p.set('closed', '1'); }
        p.set('page', String(Q.page));
        p.set('per_page', String(Q.per));
        p.set('sort', Q.sort);
        p.set('dir', Q.dir);
        if (Q.tree.items.length) { p.set('filter', JSON.stringify(Q.tree)); }
        return p.toString();
    }

    function syncUrl() {
        var p = new URLSearchParams();
        var c = cid();
        if (c) { p.set('cid', c); }
        if (Q.q) { p.set('q', Q.q); }
        if (Q.closed) { p.set('closed', '1'); }
        if (Q.page > 1) { p.set('page', String(Q.page)); }
        if (Q.per !== V().default_page_size) { p.set('per_page', String(Q.per)); }
        var d = V().default_sort;
        if (Q.sort !== d.key || Q.dir !== d.dir) { p.set('sort', Q.sort); p.set('dir', Q.dir); }
        if (Q.sf) { p.set('sf', String(Q.sf)); }
        else if (Q.tree.items.length) { p.set('filter', JSON.stringify(Q.tree)); }
        if (Q.selected) { p.set('case', String(Q.selected)); }
        var qs = p.toString();
        /* Built from the page's own address: a relative URL resolves against <base href> (lesson 279). */
        try { window.history.replaceState(null, '', window.location.href.split(/[?#]/)[0] + (qs ? '?' + qs : '')); } catch (e) { /* file:// */ }
    }

    function load() {
        var seq = ++Q.seq;
        Q.loading = true;
        Q.cache = {};
        syncUrl();
        renderBusy();
        return api('/api/v2/case-queue?' + listQuery()).then(function (r) {
            if (seq !== Q.seq) { return; }   /* a newer request answers instead (lesson 293) */
            Q.loading = false;
            if (r.ok && r.body && Array.isArray(r.body.data)) {
                Q.error = null;
                Q.result = r.body;
                Q.kpis = r.body.kpis || Q.kpis;
                Q.page = r.body.page || Q.page;
            } else {
                Q.error = message(r, 'The queue could not be loaded');
                Q.result = null;
            }
            renderAll();
            autoSelect();
        });
    }

    function rows() { return (Q.result && Q.result.data) || []; }

    function autoSelect() {
        var list = rows();
        var onPage = list.some(function (c) { return c.case_id === Q.selected; });
        if (Q.selected && (onPage || Q.detail || Q.detailLoading)) {
            if (!Q.detail && !Q.detailLoading && !Q.detailErr) { select(Q.selected, false); }
            return;
        }
        if (list.length && !narrow()) { select(list[0].case_id, false); }
        else if (!list.length) { Q.selected = null; Q.detail = null; renderDetail(); syncUrl(); settle(); }
        else { settle(); }
    }

    function select(id, open) {
        id = num(id);
        if (id === null) { return; }
        Q.selected = id;
        syncUrl();
        markActive();
        if (open && narrow()) { Q.root.classList.add('cq--detail-open'); }
        if (Q.cache[id]) {
            Q.detail = Q.cache[id]; Q.detailErr = null; Q.detailLoading = false;
            renderDetail();
            settle();
            return;
        }
        var seq = ++Q.dseq;
        Q.detail = null; Q.detailErr = null; Q.detailLoading = true;
        renderDetail();
        api('/api/v2/case-queue/cases/' + id).then(function (r) {
            if (seq !== Q.dseq) { return; }
            Q.detailLoading = false;
            if (r.ok && r.body && r.body.case_id === id) {
                Q.cache[id] = r.body;
                Q.detail = r.body;
            } else {
                Q.detailErr = r.status === 404 ? 'This case does not exist or you cannot open it.' : message(r, 'The case could not be loaded');
            }
            renderDetail();
            settle();
        });
    }

    /* The probes wait on this: set only once the list AND the panel have answered. */
    function settle() {
        if (Q.loading || Q.detailLoading) { return; }
        Q.root.setAttribute('data-cq-settled', String(Q.seq) + '.' + String(Q.dseq));
    }

    /* ------------------------------------------------------------ rendering */

    function renderAll() {
        renderHead();
        renderKpis();
        renderTools();
        renderSortHead();
        renderList();
        renderFoot();
        renderDetail();
        settle();
    }

    function renderBusy() {
        var list = $('cq-list');
        if (list) { list.setAttribute('aria-busy', Q.loading ? 'true' : 'false'); }
        Q.root.classList.toggle('cq--loading', !!Q.loading);
        Q.root.removeAttribute('data-cq-settled');
    }

    function renderHead() {
        var sub = $('cq-sub');
        if (!sub) { return; }
        var open = Q.kpis ? Q.kpis.open : null;
        var label = (V().sorts[Q.sort] || {}).label || 'Age';
        sub.textContent = (open === null || open === undefined) ? '' :
            open + ' open investigation' + (open === 1 ? '' : 's') + ', sorted by ' + label.toLowerCase() + '.';
    }

    function activeKpi() {
        if (Q.q || Q.closed) { return null; }
        var trees = Q.st.kpi_trees || {};
        var hit = null;
        kpiKeys().forEach(function (k) { if (!hit && trees[k] && same(trees[k], Q.tree)) { hit = k; } });
        return hit;
    }

    function renderKpis() {
        var box = $('cq-kpis');
        if (!box) { return; }
        var on = activeKpi();
        box.innerHTML = V().kpis.map(function (k) {
            var val = Q.kpis ? Q.kpis[k.key] : null;
            if (val === null || val === undefined) {
                return k.key === 'critical' && Q.kpis ? '' :
                    '<span class="cq-kpi cq-kpi--' + esc(k.key) + '"><span class="cq-kpi-dot"></span><span class="cq-kpi-lbl">' + esc(k.label) + '</span><span class="cq-kpi-val">—</span></span>';
            }
            return '<button type="button" class="cq-kpi cq-kpi--' + esc(k.key) + (on === k.key ? ' cq-kpi--on' : '') +
                '" data-kpi="' + esc(k.key) + '" aria-pressed="' + (on === k.key ? 'true' : 'false') + '">' +
                '<span class="cq-kpi-dot"></span><span class="cq-kpi-lbl">' + esc(k.label) + '</span>' +
                '<span class="cq-kpi-val">' + esc(val) + '</span></button>';
        }).join('');
    }

    function renderTools() {
        var q = $('cq-q');
        if (q && q !== document.activeElement && q.value !== Q.q) { q.value = Q.q; }
        var closed = $('cq-closed');
        if (closed) { closed.checked = !!Q.closed; }
        var badge = $('cq-filter-count');
        var n = 0;
        (function count(g) { g.items.forEach(function (it) { if (it.items) { count(it); } else { n += 1; } }); })(Q.tree);
        if (badge) { badge.textContent = n ? String(n) : ''; badge.hidden = !n; }
        var fbtn = $('cq-filters-btn');
        if (fbtn) { fbtn.classList.toggle('cq-btn--on', n > 0 || isPanelOpen()); }
        var per = $('cq-per');
        if (per) { per.value = String(Q.per); }
        Array.prototype.forEach.call(document.querySelectorAll('#cq-density [data-density]'), function (b) {
            var on = b.getAttribute('data-density') === Q.density;
            b.classList.toggle('cq-density--on', on);
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        Q.root.classList.toggle('cq--compact', Q.density === 'compact');
        var sbtn = $('cq-saved-btn-lbl');
        if (sbtn) {
            var cur = Q.sf && Q.saved ? Q.saved.filter(function (f) { return f.filter_id === Q.sf; })[0] : null;
            sbtn.textContent = cur ? cur.filter_name : 'Saved filters';
        }
    }

    function renderSortHead() {
        Array.prototype.forEach.call(document.querySelectorAll('#cq-qhead [data-sort]'), function (b) {
            var key = b.getAttribute('data-sort');
            var on = key === Q.sort;
            b.classList.toggle('cq-sort--on', on);
            var arrow = b.querySelector('.cq-sort-arrow');
            if (arrow) { arrow.textContent = on ? (Q.dir === 'asc' ? '▲' : '▼') : ''; }
            var label = (V().sorts[key] || {}).label || key;
            b.setAttribute('aria-label', 'Sort by ' + label + (on ? (Q.dir === 'asc' ? ' (ascending)' : ' (descending)') : ''));
        });
    }

    function rowHtml(c) {
        var tags = c.tags || [];
        var max = V().tags_in_row;
        var tagHtml = tags.slice(0, max).map(function (t) { return '<span class="cq-tag" title="' + esc(t) + '">' + esc(t) + '</span>'; }).join('') +
            (tags.length > max ? '<span class="cq-tag cq-tag--more">+' + (tags.length - max) + '</span>' : '');
        var meta = [];
        if (c.soc_id) { meta.push('<span class="cq-soc">' + esc(c.soc_id) + '</span>'); }
        meta.push('<span class="cq-id">#' + esc(c.case_id) + '</span>');
        meta.push('<span class="cq-cust">' + esc(c.customer ? c.customer.name : '') + '</span>');
        var st = c.state;
        var hot = !c.closed && c.idle_days !== null && c.idle_days > V().stall_days;
        var idle = c.closed ? 'closed ' + fmtDay(c.close_date) : 'idle ' + days(c.idle_days);
        return '<div class="cq-row' + (c.case_id === Q.selected ? ' cq-row--active' : '') + (c.closed ? ' cq-row--closed' : '') + '" role="listitem">' +
            '<button type="button" class="cq-rowbtn" data-case="' + esc(c.case_id) + '" aria-pressed="' + (c.case_id === Q.selected ? 'true' : 'false') + '">' +
            '<span class="cq-c-case">' +
            '<span class="cq-line1">' + sevPill(c.severity) + '<span class="cq-title">' + esc(c.title || ('Case #' + c.case_id)) + '</span></span>' +
            '<span class="cq-line2">' + meta.join('<span class="cq-dot" aria-hidden="true">·</span>') + '</span>' +
            (tagHtml ? '<span class="cq-tags">' + tagHtml + '</span>' : '') +
            '</span>' +
            '<span class="cq-c-stage"><span class="cq-stage-name">' + esc(st ? st.name : '—') + '</span>' + pipe(st ? st.stage : null) + '</span>' +
            '<span class="cq-c-owner">' + owner(c.owner) + '</span>' +
            '<span class="cq-c-age"><span class="cq-age">' + esc(days(c.age_days)) + '</span>' +
            '<span class="cq-idle' + (hot ? ' cq-idle--hot' : '') + '"' + (c.last_activity ? ' title="Last activity ' + esc(fmtStamp(c.last_activity)) + '"' : '') + '>' + esc(idle) + '</span></span>' +
            '</button></div>';
    }

    function filtered() { return !!(Q.q || Q.tree.items.length); }

    function renderList() {
        var list = $('cq-list');
        if (!list) { return; }
        list.setAttribute('aria-busy', Q.loading ? 'true' : 'false');
        Q.root.classList.toggle('cq--loading', !!Q.loading);
        if (Q.error) {
            /* Always a way out: the bad filter may have come from the address, not from this page's state. */
            list.innerHTML = '<div class="cq-empty cq-empty--error" role="alert">' + esc(Q.error) +
                ' <button type="button" class="cq-link" data-cq-clear>Clear filters</button></div>';
            return;
        }
        if (!Q.result) {
            list.innerHTML = '<div class="cq-empty">Loading…</div>';
            return;
        }
        var data = rows();
        if (!data.length) {
            list.innerHTML = '<div class="cq-empty">No cases match this view.' +
                (filtered() ? ' <button type="button" class="cq-link" data-cq-clear>Clear filters</button>' : '') + '</div>';
            return;
        }
        list.innerHTML = data.map(rowHtml).join('');
    }

    function markActive() {
        Array.prototype.forEach.call(document.querySelectorAll('#cq-list .cq-rowbtn'), function (b) {
            var on = num(b.getAttribute('data-case')) === Q.selected;
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
            b.parentNode.classList.toggle('cq-row--active', on);
        });
    }

    function renderFoot() {
        var lbl = $('cq-pagelbl'), prev = $('cq-prev'), next = $('cq-next');
        var r = Q.result;
        if (!lbl) { return; }
        if (!r) { lbl.textContent = ''; if (prev) { prev.disabled = true; } if (next) { next.disabled = true; } return; }
        var from = r.total ? (r.page - 1) * r.per_page + 1 : 0;
        var to = Math.min(r.total, r.page * r.per_page);
        lbl.textContent = (r.total ? from + '–' + to + ' of ' + r.total : '0 of 0') + ' · page ' + r.page + '/' + r.last_page;
        if (prev) { prev.disabled = r.page <= 1; }
        if (next) { next.disabled = r.page >= r.last_page; }
    }

    function metaCell(label, value, extra) {
        return '<div class="cq-meta-cell' + (extra || '') + '"><dt class="cq-meta-lbl">' + esc(label) + '</dt><dd class="cq-meta-val">' + value + '</dd></div>';
    }

    function renderDetail() {
        var box = $('cq-detail');
        if (!box) { return; }
        var back = '<button type="button" class="cq-d-back" data-cq-back>' + SVG(ICONS.back) + 'Back to queue</button>';
        if (Q.detailLoading) { box.innerHTML = back + '<div class="cq-d-empty">Loading…</div>'; return; }
        if (Q.detailErr) { box.innerHTML = back + '<div class="cq-d-empty" role="alert">' + esc(Q.detailErr) + '</div>'; return; }
        var d = Q.detail;
        if (!d) { box.innerHTML = '<div class="cq-d-empty">Select a case to see its summary.</div>'; return; }
        var st = d.state;
        var cur = st ? st.stage : null;
        var stepHtml = stages().map(function (name, i) {
            var cls = cur === null || cur === undefined ? '' : (i < cur ? ' cq-step--done' : (i === cur ? ' cq-step--now' : ''));
            var label = name + (i === cur ? ' (current stage)' : (cur !== null && cur !== undefined && i < cur ? ' (completed)' : ''));
            var stateId = (Q.st.stage_states || {})[name];
            var canMove = d.can_edit && i !== cur && stateId !== undefined;
            return '<li class="cq-step' + cls + '"' + (i === cur ? ' aria-current="step"' : '') + '>' +
                '<button type="button" class="cq-step-btn" data-stage="' + i + '"' + (canMove ? '' : ' disabled') +
                ' title="' + esc(canMove ? 'Move the case to ' + name : (d.can_edit ? name : name + ' (read-only access)')) + '" aria-label="' + esc(label) + '">' +
                '<span class="cq-step-mark">' + (cls === ' cq-step--done' ? SVG(ICONS.check, 'cq-i cq-i--step') : '') + '</span>' +
                '<span class="cq-step-lbl">' + esc(name) + '</span></button></li>';
        }).join('');
        var stalled = d.stalled ? '<span class="cq-stalled">' + SVG(ICONS.clock) + 'Stalled ' + esc(d.idle_days) + 'd</span>' : '';
        var notOnTrack = st && (cur === null || cur === undefined) ? '<div class="cq-d-offtrack">Stage: ' + esc(st.name) + ' (not on the track)</div>' : '';
        var last = d.closed ? metaCell('Closed', esc(fmtDay(d.close_date))) :
            metaCell('Last activity', '<span class="' + (d.idle_days > V().stall_days ? 'cq-hot' : '') + '"' +
                (d.last_activity ? ' title="' + esc(fmtStamp(d.last_activity)) + '"' : '') + '>' +
                esc(d.idle_days === 0 ? 'today' : (d.idle_days === null ? '—' : d.idle_days + 'd ago')) + '</span>');
        var tags = (d.tags || []).map(function (t) { return '<span class="cq-tag">' + esc(t) + '</span>'; }).join('');
        var tasks = d.tasks || {open: 0, done: 0, total: 0};
        var meta = '<dl class="cq-meta">' +
            metaCell('Customer', esc(d.customer ? d.customer.name : '—')) +
            metaCell('Owner', '<span class="cq-owner">' + owner(d.owner) + '</span>') +
            metaCell('Opened', esc(fmtDay(d.open_date)) + ' <span class="cq-dim">· ' + esc(days(d.age_days)) + '</span>') +
            last +
            metaCell('Classification', esc(d.classification ? d.classification.name : '—')) +
            metaCell('Outcome', esc(d.outcome ? d.outcome.name : '—')) +
            metaCell('Reviewer', d.reviewer ? esc(d.reviewer.name) : '<span class="cq-dim">None assigned</span>') +
            metaCell('Review status', esc(d.review_status || '—')) +
            metaCell('Tasks', tasks.total ? esc(tasks.open) + ' open <span class="cq-dim">· ' + esc(tasks.done) + ' done of ' + esc(tasks.total) + '</span>' : '<span class="cq-dim">None</span>') +
            metaCell('Severity', d.severity ? sevPill(d.severity) : '<span class="cq-dim">—</span>') +
            metaCell('Tags', tags || '<span class="cq-dim">No tags</span>', ' cq-meta-cell--wide') +
            '</dl>';
        var summary = d.summary ?
            '<section class="cq-d-section"><h3 class="cq-d-section-title">' + (d.summary.kind === 'executive' ? 'Executive summary' : 'Description') + '</h3>' +
            '<div class="cq-md">' + d.summary.html + '</div></section>' :
            '<section class="cq-d-section"><h3 class="cq-d-section-title">Summary</h3><div class="cq-dim">No executive summary or description yet.</div></section>';
        var closing = d.closing_note_html ?
            '<section class="cq-d-section"><h3 class="cq-d-section-title">Closing note</h3><div class="cq-md">' + d.closing_note_html + '</div></section>' : '';
        var help = window.IrisHelp ? window.IrisHelp.icon('overview.stage_track', {cls: 'ml-1'}) : '';
        box.innerHTML = back +
            '<div class="cq-d-head">' +
            '<div class="cq-d-top">' + sevPill(d.severity) +
            (d.soc_id ? '<span class="cq-d-soc">' + esc(d.soc_id) + '</span><span class="cq-dot" aria-hidden="true">·</span>' : '') +
            '<span class="cq-d-id">#' + esc(d.case_id) + '</span><span class="cq-spacer"></span>' +
            '<span class="cq-d-state' + (d.closed ? ' cq-d-state--closed' : '') + '">' + SVG(ICONS.folder) + esc(d.closed ? 'Closed' : 'Open') + '</span></div>' +
            '<h2 class="cq-d-title">' + esc(d.title || ('Case #' + d.case_id)) + '</h2>' +
            '<div class="cq-d-actions"><a class="cq-btn cq-btn--primary" href="/case?cid=' + esc(d.case_id) + '">Open workspace' + SVG(ICONS.external) + '</a>' +
            '<a class="cq-btn" href="/case/notes?cid=' + esc(d.case_id) + '">Add note</a>' + stalled + '</div>' +
            '<div class="cq-steps-wrap"><div class="cq-steps-head">Stage' + help + '</div>' +
            '<ol class="cq-steps" aria-label="Investigation progress">' + stepHtml + '</ol>' + notOnTrack + '</div>' +
            '</div>' +
            '<div class="cq-d-body">' + meta + summary + closing + '</div>';
    }

    /* ------------------------------------------------------------ actions */

    function reset(to) {
        Q.page = 1;
        Q.sf = null;
        if (to && to.tree) { Q.tree = JSON.parse(JSON.stringify(to.tree)); }
    }

    function applyKpi(key) {
        key = pick(kpiKeys(), key, null);
        if (!key) { return; }
        var tree = (Q.st.kpi_trees || {})[key];
        if (!tree) { return; }
        reset({tree: tree});
        Q.q = '';
        Q.closed = false;
        if (Q.fb) { Q.fb.set(Q.tree); }
        load();
    }

    function isPanelOpen() { var p = $('cq-filter-panel'); return !!(p && !p.hidden); }
    function togglePanel(open) {
        var p = $('cq-filter-panel'), b = $('cq-filters-btn');
        if (!p) { return; }
        var show = open === undefined ? p.hidden : !!open;
        if (show) { Q.fb.set(Q.tree); }
        p.hidden = !show;
        if (b) { b.setAttribute('aria-expanded', show ? 'true' : 'false'); }
        renderTools();
    }

    function applyBuilder() {
        Q.tree = Q.fb.get();
        Q.sf = null;
        Q.page = 1;
        togglePanel(false);
        load();
    }

    /* The panel's Clear and the saved filters' "Clear filter": the filter only. The empty list's "Clear filters"
       (withSearch): the search too - together they are what can empty the list. */
    function clearFilters(withSearch) {
        reset({tree: blank()});
        if (withSearch) {
            Q.q = '';
            var box = $('cq-q');
            if (box) { box.value = ''; }
        }
        if (Q.fb) { Q.fb.clear(); }
        togglePanel(false);
        load();
    }

    function setSort(key) {
        key = pick(sortKeys(), key, null);
        if (!key) { return; }
        if (Q.sort === key) { Q.dir = Q.dir === 'asc' ? 'desc' : 'asc'; }
        else { Q.sort = key; Q.dir = V().sorts[key].first; }
        Q.page = 1;
        load();
    }

    /* ------------------------------------------------------------ dialogs */

    function dialog(html, wire) {
        var dlg = $('cq-dialog');
        dlg.innerHTML = html;
        wire(dlg);
        if (typeof dlg.showModal === 'function') { if (!dlg.open) { dlg.showModal(); } }
        else { dlg.setAttribute('open', ''); }
        var first = dlg.querySelector('[autofocus], textarea, input, button.cq-btn--primary');
        if (first) { first.focus(); }
    }
    function closeDialog() {
        var dlg = $('cq-dialog');
        if (dlg.open && typeof dlg.close === 'function') { dlg.close(); } else { dlg.removeAttribute('open'); }
    }

    function stageDialog(idx) {
        var d = Q.detail;
        idx = num(idx);
        if (!d || idx === null || idx >= stages().length || !d.can_edit) { return; }
        var name = stages()[idx];
        var stateId = (Q.st.stage_states || {})[name];
        if (stateId === undefined) { return; }
        var cur = d.state ? d.state.name : 'no stage';
        var closing = name === V().closed_stage;
        var head = '<h3 class="cq-dlg-title" id="cq-dialog-title">' + (closing ? 'Close case #' : 'Move case #') + esc(d.case_id) +
            (closing ? '?' : ' to ' + esc(name) + '?') + '</h3>';
        if (closing && !d.reviewer) {
            dialog(head + '<p class="cq-dlg-text" role="alert">A reviewer must be assigned before this case can be closed. ' +
                'Assign one in the case’s Edit Case Details, then close it here or there.</p>' +
                '<div class="cq-dlg-foot"><button type="button" class="cq-btn" data-dlg-cancel>Cancel</button>' +
                '<a class="cq-btn cq-btn--primary" href="/case?cid=' + esc(d.case_id) + '">Open the case</a></div>', function (dlg) {
                dlg.querySelector('[data-dlg-cancel]').addEventListener('click', closeDialog);
            });
            return;
        }
        var text = closing ? 'The case closes and its alerts are closed with it. Reviewer: ' + esc(d.reviewer.name) + '.' :
            (d.closed ? 'This reopens the case and moves it to ' + esc(name) + '.' :
                'The case moves from ' + esc(cur) + ' to ' + esc(name) + '.');
        var note = closing ? '<label class="cq-dlg-lbl" for="cq-dlg-note">Closing note</label>' +
            '<textarea id="cq-dlg-note" class="cq-dlg-input" rows="4" maxlength="20000"></textarea>' : '';
        dialog(head + '<p class="cq-dlg-text">' + text + '</p>' + note +
            '<div class="cq-dlg-err" role="alert" hidden></div>' +
            '<div class="cq-dlg-foot"><button type="button" class="cq-btn" data-dlg-cancel>Cancel</button>' +
            '<button type="button" class="cq-btn cq-btn--primary" data-dlg-ok>' + (closing ? 'Close case' : (d.closed ? 'Reopen and move' : 'Move')) + '</button></div>',
        function (dlg) {
            var ta = dlg.querySelector('#cq-dlg-note');
            if (ta) { ta.value = d.closing_note || ''; }
            dlg.querySelector('[data-dlg-cancel]').addEventListener('click', closeDialog);
            var ok = dlg.querySelector('[data-dlg-ok]');
            ok.addEventListener('click', function () {
                var body = {state_id: stateId};
                if (ta) { body.closing_note = ta.value; }
                ok.disabled = true;
                api('/api/v2/cases/' + d.case_id, {method: 'PUT', json: body}).then(function (r) {
                    if (!r.ok) {
                        ok.disabled = false;
                        var err = dlg.querySelector('.cq-dlg-err');
                        err.textContent = message(r, 'The stage could not be changed');
                        err.hidden = false;
                        return;
                    }
                    closeDialog();
                    /* The panel stays on the case just moved, even when the list no longer shows it. */
                    load();
                    select(d.case_id, false);
                });
            });
        });
    }

    function saveDialog() {
        var tree = Q.fb && isPanelOpen() ? Q.fb.get() : Q.tree;
        if (!tree.items.length && !Q.q && !Q.closed) { return; }
        dialog('<h3 class="cq-dlg-title" id="cq-dialog-title">Save filter</h3>' +
            '<label class="cq-dlg-lbl" for="cq-sf-name">Name</label>' +
            '<input id="cq-sf-name" class="cq-dlg-input" type="text" maxlength="120" placeholder="e.g. My open cases this month" autofocus>' +
            '<label class="cq-dlg-lbl" for="cq-sf-desc">Description (optional)</label>' +
            '<input id="cq-sf-desc" class="cq-dlg-input" type="text" maxlength="300" placeholder="What this filter is for">' +
            '<label class="cq-dlg-check"><input id="cq-sf-private" type="checkbox" checked> Private (only visible to you)</label>' +
            '<div class="cq-dlg-err" role="alert" hidden></div>' +
            '<div class="cq-dlg-foot"><button type="button" class="cq-btn" data-dlg-cancel>Cancel</button>' +
            '<button type="button" class="cq-btn cq-btn--primary" data-dlg-ok>Save</button></div>', function (dlg) {
            dlg.querySelector('[data-dlg-cancel]').addEventListener('click', closeDialog);
            var ok = dlg.querySelector('[data-dlg-ok]');
            ok.addEventListener('click', function () {
                var name = dlg.querySelector('#cq-sf-name').value.trim();
                var err = dlg.querySelector('.cq-dlg-err');
                if (!name) { err.textContent = 'Give the filter a name.'; err.hidden = false; return; }
                ok.disabled = true;
                api(legacyUrl('/filters/add'), {method: 'POST', json: {
                    filter_name: name.slice(0, 120),
                    filter_description: dlg.querySelector('#cq-sf-desc').value.trim().slice(0, 300),
                    filter_is_private: !!dlg.querySelector('#cq-sf-private').checked,
                    filter_type: V().saved_filter_type,
                    filter_data: {group: tree, showClosed: !!Q.closed, search: Q.q || ''},
                    csrf_token: csrf()
                }}).then(function (r) {
                    var saved = r.body && r.body.data;
                    if (!r.ok || !r.body || r.body.status !== 'success' || !saved || num(saved.filter_id) === null) {
                        ok.disabled = false;
                        err.textContent = message(r, 'The filter could not be saved');
                        err.hidden = false;
                        return;
                    }
                    closeDialog();
                    Q.tree = tree;
                    Q.sf = num(saved.filter_id);
                    Q.page = 1;
                    togglePanel(false);
                    loadSaved().then(load);
                });
            });
        });
    }

    /* ------------------------------------------------------------ saved filters */

    function loadSaved() {
        return api(legacyUrl('/filters/' + V().saved_filter_type + '/list')).then(function (r) {
            if (r.ok && r.body && Array.isArray(r.body.data)) {
                Q.saved = r.body.data.filter(function (f) { return f && num(f.filter_id) !== null; });
                Q.savedErr = null;
            } else {
                Q.saved = null;
                Q.savedErr = message(r, 'Saved filters could not be loaded');
            }
            renderTools();
            renderSavedMenu();
        });
    }

    function renderSavedMenu() {
        var menu = $('cq-saved-menu');
        if (!menu) { return; }
        var me = Q.st.me.id;
        var items;
        if (Q.savedErr) { items = '<div class="cq-menu-empty" role="alert">' + esc(Q.savedErr) + '</div>'; }
        else if (!Q.saved) { items = '<div class="cq-menu-empty">Loading…</div>'; }
        else if (!Q.saved.length) {
            items = '<div class="cq-menu-empty">No saved filters yet. Build a filter and hit <b>Save filter</b> to keep it.</div>';
        } else {
            items = Q.saved.map(function (f) {
                var id = num(f.filter_id);
                var mine = num(f.created_by) === me;
                return '<div class="cq-menu-row' + (id === Q.sf ? ' cq-menu-row--on' : '') + '">' +
                    '<button type="button" class="cq-menu-item" data-sf="' + id + '">' +
                    '<span class="cq-menu-name">' + esc(f.filter_name) + '</span>' +
                    '<span class="cq-menu-sub">' + (f.filter_is_private ? 'Private' : 'Public') +
                    (f.filter_description ? ' · ' + esc(f.filter_description) : '') + '</span></button>' +
                    (mine ? '<button type="button" class="cq-menu-del" data-sf-del="' + id + '" aria-label="Delete ' + esc(f.filter_name) + '" title="Delete">×</button>' : '') +
                    '</div>';
            }).join('');
        }
        menu.innerHTML = '<div class="cq-menu-head">Apply a preset</div>' + items +
            '<div class="cq-menu-sep"></div>' +
            '<button type="button" class="cq-menu-item cq-menu-action" data-sf-clear' + (Q.sf || Q.tree.items.length ? '' : ' disabled') + '>Clear filter</button>' +
            '<button type="button" class="cq-menu-item cq-menu-action" data-sf-save' +
            ((Q.tree.items.length || Q.q || Q.closed || (Q.fb && isPanelOpen() && Q.fb.complete())) ? '' : ' disabled title="Build a filter first"') + '>Save current filter</button>';
    }

    function toggleSavedMenu(open) {
        var menu = $('cq-saved-menu'), btn = $('cq-saved-btn');
        if (!menu) { return; }
        var show = open === undefined ? menu.hidden : !!open;
        if (show) { renderSavedMenu(); }
        menu.hidden = !show;
        if (btn) { btn.setAttribute('aria-expanded', show ? 'true' : 'false'); }
    }

    function applySaved(id) {
        id = num(id);
        var f = (Q.saved || []).filter(function (x) { return num(x.filter_id) === id; })[0];
        if (!f) { return; }
        var data = (f.filter_data && typeof f.filter_data === 'object') ? f.filter_data : {};
        Q.tree = (data.group && Array.isArray(data.group.items)) ? data.group : blank();
        Q.closed = !!data.showClosed;
        Q.q = typeof data.search === 'string' ? data.search.slice(0, V().limits.search) : '';
        Q.sf = id;
        Q.page = 1;
        if (Q.fb) { Q.fb.set(Q.tree); }
        toggleSavedMenu(false);
        load();
    }

    function deleteSaved(id) {
        id = num(id);
        var f = (Q.saved || []).filter(function (x) { return num(x.filter_id) === id; })[0];
        if (!f) { return; }
        toggleSavedMenu(false);
        dialog('<h3 class="cq-dlg-title" id="cq-dialog-title">Delete saved filter?</h3>' +
            '<p class="cq-dlg-text">“' + esc(f.filter_name) + '” will be deleted' + (f.filter_is_private ? '.' : ' for everyone.') + '</p>' +
            '<div class="cq-dlg-err" role="alert" hidden></div>' +
            '<div class="cq-dlg-foot"><button type="button" class="cq-btn" data-dlg-cancel>Cancel</button>' +
            '<button type="button" class="cq-btn cq-btn--danger" data-dlg-ok>Delete</button></div>', function (dlg) {
            dlg.querySelector('[data-dlg-cancel]').addEventListener('click', closeDialog);
            var ok = dlg.querySelector('[data-dlg-ok]');
            ok.addEventListener('click', function () {
                ok.disabled = true;
                api(legacyUrl('/filters/delete/' + id), {method: 'POST', json: {csrf_token: csrf()}}).then(function (r) {
                    if (!r.ok || !r.body || r.body.status !== 'success') {
                        ok.disabled = false;
                        var err = dlg.querySelector('.cq-dlg-err');
                        err.textContent = message(r, 'The filter could not be deleted');
                        err.hidden = false;
                        return;
                    }
                    closeDialog();
                    if (Q.sf === id) { Q.sf = null; syncUrl(); }
                    loadSaved();
                });
            });
        });
    }

    /* ------------------------------------------------------------ wiring */

    function wire() {
        var root = Q.root;
        root.addEventListener('click', function (e) {
            var t = e.target;
            var b;
            if ((b = t.closest('[data-kpi]'))) { applyKpi(b.getAttribute('data-kpi')); return; }
            if ((b = t.closest('#cq-list .cq-rowbtn'))) { select(b.getAttribute('data-case'), true); return; }
            if ((b = t.closest('[data-sort]'))) { setSort(b.getAttribute('data-sort')); return; }
            if ((b = t.closest('[data-cq-clear]'))) { clearFilters(true); return; }
            if ((b = t.closest('[data-cq-back]'))) { root.classList.remove('cq--detail-open'); return; }
            if ((b = t.closest('.cq-step-btn'))) { if (!b.disabled) { stageDialog(b.getAttribute('data-stage')); } return; }
            if ((b = t.closest('[data-density]'))) {
                Q.density = pick(DENSITIES, b.getAttribute('data-density'), 'comfortable');
                prefs({density: Q.density});
                renderTools();
                return;
            }
            if ((b = t.closest('[data-sf-del]'))) { e.stopPropagation(); deleteSaved(b.getAttribute('data-sf-del')); return; }
            if ((b = t.closest('[data-sf]'))) { applySaved(b.getAttribute('data-sf')); return; }
            if ((b = t.closest('[data-sf-clear]'))) { toggleSavedMenu(false); clearFilters(false); return; }
            if ((b = t.closest('[data-sf-save]'))) { toggleSavedMenu(false); saveDialog(); return; }
        });
        $('cq-list').addEventListener('keydown', function (e) {
            if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') { return; }
            var btns = Array.prototype.slice.call(document.querySelectorAll('#cq-list .cq-rowbtn'));
            var i = btns.indexOf(document.activeElement);
            if (i === -1) { return; }
            var j = e.key === 'ArrowDown' ? Math.min(btns.length - 1, i + 1) : Math.max(0, i - 1);
            e.preventDefault();
            btns[j].focus();
            select(btns[j].getAttribute('data-case'), false);
        });
        $('cq-q').addEventListener('input', function (e) {
            var v = String(e.target.value || '').slice(0, V().limits.search);
            if (Q.searchTimer) { window.clearTimeout(Q.searchTimer); }
            Q.searchTimer = window.setTimeout(function () {
                if (v.trim() === Q.q.trim()) { return; }
                Q.q = v.trim();
                Q.page = 1;
                Q.sf = null;
                load();
            }, 300);
        });
        $('cq-closed').addEventListener('change', function (e) { Q.closed = !!e.target.checked; Q.page = 1; Q.sf = null; load(); });
        $('cq-filters-btn').addEventListener('click', function () { togglePanel(); });
        $('cq-apply').addEventListener('click', applyBuilder);
        $('cq-clear').addEventListener('click', function () { clearFilters(false); });
        $('cq-save-filter').addEventListener('click', saveDialog);
        $('cq-saved-btn').addEventListener('click', function (e) { e.stopPropagation(); toggleSavedMenu(); });
        document.addEventListener('click', function (e) {
            var menu = $('cq-saved-menu');
            if (menu && !menu.hidden && !menu.contains(e.target) && !e.target.closest('#cq-saved-btn')) { toggleSavedMenu(false); }
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') { toggleSavedMenu(false); }
        });
        $('cq-per').addEventListener('change', function (e) {
            var n = pick(V().page_sizes, num(e.target.value), V().default_page_size);
            Q.per = n;
            prefs({per_page: n});
            Q.page = 1;
            load();
        });
        $('cq-prev').addEventListener('click', function () { if (Q.page > 1) { Q.page -= 1; load(); } });
        $('cq-next').addEventListener('click', function () {
            if (Q.result && Q.page < Q.result.last_page) { Q.page += 1; load(); }
        });
        var imp = $('cq-import');
        if (imp) { imp.addEventListener('click', function () { if (typeof window.open_import_case_modal === 'function') { window.open_import_case_modal(); } }); }
        var add = $('cq-new');
        if (add) { add.addEventListener('click', function () { if (typeof window.load_add_case === 'function') { window.load_add_case(); } }); }
        var dlg = $('cq-dialog');
        dlg.addEventListener('click', function (e) { if (e.target === dlg) { closeDialog(); } });
    }

    function init(st) {
        Q.st = st;
        var v = st.vocab;
        var pref = prefs();
        var q = st.query || {};
        Q.density = pick(DENSITIES, pref.density, 'comfortable');
        Q.q = typeof q.q === 'string' ? q.q : '';
        Q.closed = !!q.closed;
        Q.page = num(q.page) || 1;
        Q.per = pick(v.page_sizes, num(q.per_page), v.default_page_size);
        Q.sort = pick(Object.keys(v.sorts), q.sort, v.default_sort.key);
        Q.dir = pick(['asc', 'desc'], q.dir, v.default_sort.dir);
        Q.tree = (q.filter && Array.isArray(q.filter.items)) ? q.filter : blank();
        Q.sf = num(st.saved_filter_id);
        Q.result = st.result || null;
        Q.kpis = st.kpis || null;
        Q.error = st.error || null;
        var m = /[?&]case=(\d{1,12})(?:&|$)/.exec(window.location.search);
        Q.selected = m ? parseInt(m[1], 10) : null;
        if (st.detail && num(st.detail.case_id) !== null) {
            Q.cache[st.detail.case_id] = st.detail;
            if (Q.selected === null || Q.selected === st.detail.case_id) {
                Q.selected = st.detail.case_id;
                Q.detail = st.detail;
            }
        }
        Q.fb = window.IrisFilterBuilder.create($('cq-builder'), {
            fields: v.fields, operators: v.operators, noValueOps: v.no_value_ops, dayOps: v.day_ops,
            options: st.options, limits: v.limits, onEnter: applyBuilder
        });
        Q.fb.set(Q.tree);
        var per = $('cq-per');
        per.innerHTML = v.page_sizes.map(function (n) { return '<option value="' + n + '">' + n + ' / page</option>'; }).join('');
        wire();
        renderAll();
        var urlPer = /[?&]per_page=\d/.test(window.location.search);
        var wanted = pick(v.page_sizes, num(pref.per_page), null);
        if (!Q.error && (!Q.result || (!urlPer && wanted && wanted !== Q.per))) {
            if (!urlPer && wanted) { Q.per = wanted; }
            load();
        } else {
            syncUrl();
            autoSelect();
        }
        loadSaved();
    }

    function mount(root, state) {
        Q.root = root;
        if (state && state.vocab) { init(state); return; }
        /* The page could not embed its first frame: fetch it with the page's own query. */
        var list = $('cq-list');
        if (list) { list.innerHTML = '<div class="cq-empty">Loading…</div>'; }
        api('/api/v2/case-queue/state' + window.location.search).then(function (r) {
            if (r.ok && r.body && r.body.vocab) { init(r.body); return; }
            if (list) { list.innerHTML = '<div class="cq-empty cq-empty--error" role="alert">' + esc(message(r, 'The queue could not be loaded')) + '</div>'; }
        });
    }

    window.IrisCaseQueue = {mount: mount, _q: Q};
})();

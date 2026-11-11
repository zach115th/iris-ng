/* IrisAlertQueue - the Alerts page (iris-ng, 2026-11-09): the search bar, quick tabs, Split / List / Board views, grouped
 * clusters, selection and batch actions, keyboard triage, the Filter panel, saved filters, New alert.
 *
 *   IrisAlertQueue.mount(root, state)   state = GET /api/v2/alert-queue/state (null: fetched)
 *   reload() / alertChanged(id) / picked() / detailOf(id) / options() / newAlert()   what alerts.js calls back
 *
 * Needs IrisAlertQueryBar and IrisAlertDetail. The server filters, sorts, groups and pages; values read back from the page
 * (the filter fields, the page-size menu) are re-derived before they reach a URL.
 */
(function () {
    'use strict';

    var LAYOUT_KEY = 'irisAlertLayout';
    var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    var TAB_CLAUSES = ['is:open', 'owner:me', 'owner:none', 'status:escalated'];
    var Q = null;

    function el(tag, props, kids) {
        var n = document.createElement(tag);
        Object.keys(props || {}).forEach(function (k) {
            var v = props[k];
            if (v === null || v === undefined || v === false) { return; }
            if (k === 'text') { n.textContent = v; }
            else if (k === 'cls') { n.className = v; }
            else if (k === 'on') { Object.keys(v).forEach(function (ev) { n.addEventListener(ev, v[ev]); }); }
            else if (k === 'value') { n.value = v; }
            else { n.setAttribute(k, v === true ? '' : v); }
        });
        (kids || []).forEach(function (c) { if (c) { n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); } });
        return n;
    }

    function num(v) { var n = parseInt(v, 10); return isNaN(n) ? 0 : n; }
    function csrf() { var t = document.getElementById('csrf_token'); return t ? t.value : ''; }
    function byId(id) { return document.getElementById(id); }

    function cid() {
        var m = /[?&]cid=(\d{1,12})(?:&|$)/.exec(location.search);
        return m ? parseInt(m[1], 10) : null;
    }

    function api(method, url, body) {
        var opts = {method: method, credentials: 'same-origin', headers: {'Accept': 'application/json'}};
        if (body !== undefined) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(Object.assign({}, body, method === 'POST' ? {csrf_token: csrf()} : {}));
        }
        return fetch(url, opts).then(function (r) {
            return r.text().then(function (t) {
                var data = null;
                try { data = t ? JSON.parse(t) : null; } catch (e) { data = null; }
                return {ok: r.ok, status: r.status, data: data};
            });
        }, function () { return {ok: false, status: 0, data: null}; });
    }

    function layout() {
        try { return JSON.parse(window.localStorage.getItem(LAYOUT_KEY) || '{}') || {}; } catch (e) { return {}; }
    }

    function saveLayout(patch) {
        try { window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(Object.assign(layout(), patch))); } catch (e) { /* a convenience */ }
    }

    function stamp(iso) {
        var m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(String(iso || ''));
        return m ? m[1] + ' ' + m[2] + ' UTC' : '';
    }

    function short(iso) {
        var m = /^\d{4}-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(String(iso || ''));
        return m ? MONTHS[parseInt(m[1], 10) - 1] + ' ' + parseInt(m[2], 10) + ' ' + m[3] : '';
    }

    function age(iso) {
        var t = Date.parse(iso);
        if (isNaN(t)) { return '—'; }
        var mins = Math.max(0, Math.floor((Date.now() - t) / 60000));
        if (mins < 60) { return mins + 'm'; }
        if (mins < 1440) { return Math.floor(mins / 60) + 'h'; }
        return Math.floor(mins / 1440) + 'd';
    }

    function sevColor(name) { return window.IrisAlertDetail.sevColor(name); }

    function callGlobal(name) {
        var fn = window[name];
        if (typeof fn === 'function') { return fn.apply(null, [].slice.call(arguments, 1)); }
        return undefined;
    }

    // ------------------------------------------------------------------ requests and the address

    function pairs() {
        var out = [];
        var f = Q.params.filters || {};
        Object.keys(f).forEach(function (k) {
            var v = f[k];
            if (Q.vocab.filter_params.indexOf(k) === -1 || v === null || v === undefined || v === '') { return; }
            out.push([k, Array.isArray(v) ? v.join(',') : String(v)]);
        });
        return out;
    }

    function queryString(extra) {
        var p = new URLSearchParams();
        p.set('q', Q.params.q);
        pairs().forEach(function (kv) { p.set(kv[0], kv[1]); });
        p.set('order_by', Q.params.order_by);
        p.set('sort', Q.params.sort);
        p.set('page', String(Q.params.page));
        p.set('per_page', String(Q.params.per_page));
        p.set('board', Q.params.board);
        Object.keys(extra || {}).forEach(function (k) { p.set(k, extra[k]); });
        return p.toString();
    }

    function syncUrl() {
        var p = new URLSearchParams();
        var c = cid();
        if (c !== null) { p.set('cid', String(c)); }
        var defaultQ = pairs().length ? '' : Q.vocab.default_query;
        if (Q.params.q !== defaultQ) { p.set('q', Q.params.q); }
        pairs().forEach(function (kv) { p.set(kv[0], kv[1]); });
        var ds = Q.vocab.default_sort;
        if (Q.params.order_by !== ds.key) { p.set('order_by', Q.params.order_by); }
        if (Q.params.sort !== Q.vocab.sorts[Q.params.order_by].first) { p.set('sort', Q.params.sort); }
        if (Q.params.page > 1) { p.set('page', String(Q.params.page)); }
        if (Q.params.per_page !== Q.vocab.default_page_size) { p.set('per_page', String(Q.params.per_page)); }
        if (Q.view !== Q.vocab.default_view) { p.set('view', Q.view); }
        if (Q.view === 'board' && Q.params.board !== Q.vocab.default_board_group) { p.set('board', Q.params.board); }
        if (Q.selected) { p.set('alert', String(Q.selected)); }
        var s = p.toString();
        history.replaceState(null, '', location.href.split(/[?#]/)[0] + (s ? '?' + s : ''));
    }

    function errorOf(res, fallback) {
        var d = res && res.data;
        if (d && typeof d.message === 'string' && d.message) { return d.message; }
        return fallback;
    }

    function showError(text) {
        var box = byId('aq-error');
        box.textContent = text || '';
        box.hidden = !text;
    }

    function load() {
        Q.seq += 1;
        var mine = Q.seq;
        Q.root.removeAttribute('data-aq-settled');
        var url = (Q.view === 'board' ? '/api/v2/alert-queue/board?' : '/api/v2/alert-queue?') + queryString();
        return api('GET', url).then(function (res) {
            if (mine !== Q.seq) { return; }
            if (!res.ok || !res.data) {
                var qe = res.data && res.data.data && res.data.data.query_error;
                if (qe) {
                    Q.bar.setError(qe, Q.params.q);
                    showError('');
                } else {
                    showError(errorOf(res, 'The alerts could not be loaded.'));
                }
                if (Q.view === 'board') { Q.board = null; } else { Q.result = null; }
                drawHead();
                drawMain();
                Q.root.setAttribute('data-aq-settled', String(mine));
                return;
            }
            showError('');
            Q.tabCounts = res.data.tab_counts || Q.tabCounts;
            if (Q.view === 'board') { Q.board = res.data; } else { Q.result = res.data; }
            Q.params.page = res.data.page || Q.params.page;
            Q.bar.set(res.data.query);
            syncUrl();
            drawHead();
            drawMain();
            autoSelect();
            Q.root.setAttribute('data-aq-settled', String(mine));
        });
    }

    function search(text) {
        Q.params.q = String(text || '').trim();
        Q.params.page = 1;
        return load();
    }

    function reload() { Q.picked.clear(); Q.newCount = 0; drawNewBadge(); return load(); }

    function alertChanged(id) {
        var refreshDetail = id && Q.selected === num(id);
        return load().then(function () { if (refreshDetail) { loadDetail(Q.selected); } });
    }

    // ------------------------------------------------------------------ the frame

    function frame() {
        var root = Q.root;
        root.textContent = '';
        root.appendChild(el('div', {cls: 'aq-head'}, [
            el('h1', {cls: 'aq-title', id: 'aq-title'}),
            el('span', {id: 'aq-title-help'}),
            el('button', {type: 'button', cls: 'aq-btn', id: 'aq-filter-btn', 'aria-expanded': 'false', 'aria-controls': 'aq-filter-panel', on: {click: toggleFilters}},
               ['Filter', el('span', {cls: 'aq-badge', id: 'aq-filter-count', hidden: true})]),
            el('span', {cls: 'aq-spacer'}),
            Q.permissions.write ? el('button', {type: 'button', cls: 'aq-btn', id: 'aq-select', 'aria-pressed': 'false', on: {click: toggleSelect}}, ['Select']) : null,
            Q.permissions.write ? el('button', {type: 'button', cls: 'aq-btn aq-btn--primary', id: 'aq-new', on: {click: newAlertDialog}}, ['New alert']) : null,
            el('button', {type: 'button', cls: 'aq-btn', id: 'aq-refresh', on: {click: function () { reload(); }}},
               ['Refresh', el('span', {cls: 'aq-badge aq-badge--new', id: 'aq-new-badge', hidden: true})]),
            el('span', {cls: 'aq-views', role: 'group', 'aria-label': 'View'}, [
                viewBtn('list', 'List view'), viewBtn('split', 'Split triage'), viewBtn('board', 'Board view')])
        ]));
        var help = window.IrisHelp && window.IrisHelp.el ? window.IrisHelp.el('alert.alert', {cls: 'ml-2'}) : null;
        if (help) { byId('aq-title-help').appendChild(help); }
        var helpViews = window.IrisHelp && window.IrisHelp.el ? window.IrisHelp.el('alert.views', {cls: 'ml-1'}) : null;
        if (helpViews) { root.querySelector('.aq-head').appendChild(helpViews); }
        root.appendChild(el('div', {cls: 'aq-querywrap'}, [el('div', {id: 'aq-querybar', cls: 'aq-querybar'}),
                                                           window.IrisHelp && window.IrisHelp.el ? window.IrisHelp.el('alert.search', {cls: 'ml-1'}) : null]));
        root.appendChild(el('form', {id: 'aq-filter-panel', cls: 'aq-filter', hidden: true, on: {submit: function (e) { e.preventDefault(); applyFilters(); }}}));
        root.appendChild(el('div', {id: 'aq-error', cls: 'aq-alert', role: 'alert', hidden: true}));
        root.appendChild(el('div', {id: 'aq-body', cls: 'aq-body'}, [
            el('div', {id: 'aq-main', cls: 'aq-main'}),
            el('div', {id: 'aq-resize', cls: 'aq-resize', role: 'separator', 'aria-orientation': 'vertical', tabindex: '0',
                       'aria-label': 'Resize the alert queue: arrow keys to resize, Home to reset', title: 'Drag to resize, double-click to reset'}),
            el('div', {id: 'aq-detail', cls: 'aq-detail', tabindex: '-1'}, [el('p', {cls: 'aq-empty', text: 'Select an alert to triage it.'})])
        ]));
        root.appendChild(el('dialog', {id: 'aq-dialog', cls: 'aq-dialog', 'aria-labelledby': 'aq-dlg-title'}));
        Q.bar = window.IrisAlertQueryBar.create(byId('aq-querybar'), {
            fields: Q.vocab.query_fields, options: Q.options, isValues: Q.vocab.is_values, nullable: Q.vocab.nullable_choices,
            maxLength: Q.vocab.max_query, onSubmit: search
        });
        drawFilterPanel();
        wireResize();
    }

    function viewBtn(view, label) {
        return el('button', {type: 'button', cls: 'aq-view', 'data-view': view, 'aria-pressed': 'false', title: label, 'aria-label': label, on: {click: function () { setView(view); }}}, [VIEW_ICON[view]()]);
    }

    var VIEW_ICON = {
        list: function () { return icon([['line', {x1: '8', x2: '21', y1: '6', y2: '6'}], ['line', {x1: '8', x2: '21', y1: '12', y2: '12'}], ['line', {x1: '8', x2: '21', y1: '18', y2: '18'}], ['line', {x1: '3', x2: '3.01', y1: '6', y2: '6'}], ['line', {x1: '3', x2: '3.01', y1: '12', y2: '12'}], ['line', {x1: '3', x2: '3.01', y1: '18', y2: '18'}]]); },
        split: function () { return icon([['rect', {width: '18', height: '18', x: '3', y: '3', rx: '2'}], ['path', {d: 'M9 3v18'}]]); },
        board: function () { return icon([['rect', {width: '18', height: '18', x: '3', y: '3', rx: '2'}], ['path', {d: 'M8 7v7'}], ['path', {d: 'M12 7v4'}], ['path', {d: 'M16 7v9'}]]); }
    };

    function icon(parts) {
        var ns = 'http://www.w3.org/2000/svg';
        var s = document.createElementNS(ns, 'svg');
        s.setAttribute('viewBox', '0 0 24 24');
        s.setAttribute('fill', 'none');
        s.setAttribute('stroke', 'currentColor');
        s.setAttribute('stroke-width', '2');
        s.setAttribute('stroke-linecap', 'round');
        s.setAttribute('stroke-linejoin', 'round');
        s.setAttribute('aria-hidden', 'true');
        s.setAttribute('class', 'aq-i');
        parts.forEach(function (p) {
            var n = document.createElementNS(ns, p[0]);
            Object.keys(p[1]).forEach(function (k) { n.setAttribute(k, p[1][k]); });
            s.appendChild(n);
        });
        return s;
    }

    function setView(view) {
        if (view === Q.view || Q.vocab.views.indexOf(view) === -1) { return; }
        Q.view = Q.vocab.views[Q.vocab.views.indexOf(view)];
        saveLayout({view: Q.view});
        if (Q.view === 'board') { Q.selected = null; closeDetailPane(); }
        // iris-ng 2026-11-10: the List view's open detail hides the queue (aq--detail-open); Split always shows both, so
        // the flag must not follow it there - the queue vanished when an alert opened in List was then split.
        if (Q.view === 'split') { Q.detailOpen = false; }
        if ((Q.view === 'board' && !Q.board) || (Q.view !== 'board' && !Q.result)) { load(); return; }
        drawHead();
        drawMain();
        applyBodyClass();
        syncUrl();
        autoSelect();
    }

    function drawHead() {
        var total = Q.view === 'board' ? (Q.board ? Q.board.total : null) : (Q.result ? Q.result.total : null);
        byId('aq-title').textContent = total === null ? 'Alerts' : total.toLocaleString('en-US') + ' Alerts';
        Array.prototype.forEach.call(Q.root.querySelectorAll('.aq-view'), function (b) {
            var on = b.getAttribute('data-view') === Q.view;
            b.classList.toggle('aq-view--on', on);
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        var n = pairs().length;
        var badge = byId('aq-filter-count');
        badge.textContent = String(n);
        badge.hidden = !n;
        applyBodyClass();
    }

    function applyBodyClass() {
        var body = byId('aq-body');
        body.className = 'aq-body aq-body--' + Q.view + (Q.detailOpen ? ' aq--detail-open' : '');
        var w = layout().queue_width;
        if (w) { body.style.setProperty('--aq-queue-w', Math.max(320, Math.min(900, num(w))) + 'px'); }
    }

    function drawNewBadge() {
        var b = byId('aq-new-badge');
        b.textContent = Q.newCount > 99 ? '99+' : String(Q.newCount);
        b.hidden = !Q.newCount;
        byId('aq-refresh').title = Q.newCount ? 'New alerts available' : '';
    }

    function wireResize() {
        var r = byId('aq-resize');
        var body = byId('aq-body');
        var drag = null;
        function set(px) {
            var w = Math.max(320, Math.min(900, Math.round(px)));
            body.style.setProperty('--aq-queue-w', w + 'px');
            r.setAttribute('aria-valuenow', String(w));
            saveLayout({queue_width: w});
        }
        r.addEventListener('pointerdown', function (e) { drag = {x: e.clientX, w: byId('aq-main').getBoundingClientRect().width}; r.setPointerCapture(e.pointerId); });
        r.addEventListener('pointermove', function (e) { if (drag) { set(drag.w + e.clientX - drag.x); } });
        r.addEventListener('pointerup', function () { drag = null; });
        r.addEventListener('dblclick', function () { body.style.removeProperty('--aq-queue-w'); saveLayout({queue_width: null}); });
        r.addEventListener('keydown', function (e) {
            var cur = byId('aq-main').getBoundingClientRect().width;
            if (e.key === 'ArrowLeft') { e.preventDefault(); set(cur - 24); }
            if (e.key === 'ArrowRight') { e.preventDefault(); set(cur + 24); }
            if (e.key === 'Home') { e.preventDefault(); body.style.removeProperty('--aq-queue-w'); saveLayout({queue_width: null}); }
        });
    }

    // ------------------------------------------------------------------ the queue (Split and List)

    function drawMain() {
        var main = byId('aq-main');
        main.textContent = '';
        if (Q.view === 'board') { drawBoard(main); return; }
        drawQueue(main);
    }

    function activeTab() {
        var res = Q.result;
        if (!res || !res.query) { return null; }
        if (res.query.tab) { return res.query.tab; }
        return (res.query.clauses || []).some(function (c) { return c.text.toLowerCase() === 'is:open'; }) ? 'open' : null;
    }

    function setTab(tab) {
        var t = Q.vocab.tabs.filter(function (x) { return x.key === tab; })[0];
        if (!t) { return; }
        var rest = ((Q.result && Q.result.query && Q.result.query.clauses) || []).map(function (c) { return c.text; })
            .filter(function (c) { return TAB_CLAUSES.indexOf(c.toLowerCase()) === -1; });
        search([t.query].concat(rest).join(' '));
    }

    function drawQueue(main) {
        var tab = activeTab();
        main.appendChild(el('div', {cls: 'aq-qtabs', role: 'tablist', 'aria-label': 'Alert queue filter'}, Q.vocab.tabs.map(function (t) {
            var on = tab === t.key;
            var c = Q.tabCounts ? Q.tabCounts[t.key] : null;
            return el('button', {type: 'button', role: 'tab', cls: 'aq-qtab' + (on ? ' aq-qtab--on' : ''), 'data-tab': t.key, 'aria-selected': on ? 'true' : 'false',
                                 on: {click: function () { setTab(t.key); }}}, [t.label, c === null || c === undefined ? null : el('span', {cls: 'aq-qtab-count', text: c.toLocaleString('en-US')})]);
        })));
        if (Q.selectMode) { main.appendChild(selectionBar()); }
        var sortHead = el('div', {cls: 'aq-qhead', role: 'group', 'aria-label': 'Sort alerts'}, ['severity', 'title', 'customer_name', 'status', 'event_time'].map(function (k) {
            var on = Q.params.order_by === k;
            var dir = on ? (Q.params.sort === 'asc' ? 'ascending' : 'descending') : null;
            return el('button', {type: 'button', cls: 'aq-sort aq-sort--' + k + (on ? ' aq-sort--on' : ''), 'data-sort': k,
                                 'aria-label': 'Sort by ' + Q.vocab.sorts[k].label + (dir ? ' (' + dir + ')' : ''), on: {click: function () { setSort(k); }}},
                      [Q.vocab.sorts[k].label, on ? el('span', {cls: 'aq-sort-arrow', 'aria-hidden': 'true', text: Q.params.sort === 'asc' ? '▲' : '▼'}) : null]);
        }));
        sortHead.insertBefore(el('span', {cls: 'aq-qhead-label', text: 'Owner'}), sortHead.lastChild);
        main.appendChild(sortHead);
        var list = el('div', {cls: 'aq-list', id: 'aq-list', role: 'listbox', 'aria-label': 'Alerts'});
        var r = Q.result;
        if (!r) {
            list.appendChild(el('p', {cls: 'aq-empty', text: 'The alerts could not be shown.'}));
        } else if (!r.entries.length) {
            list.appendChild(el('p', {cls: 'aq-empty', id: 'aq-none', text: 'No alerts match the current filters.'}));
        } else {
            r.entries.forEach(function (e) { list.appendChild(e.kind === 'cluster' ? clusterEl(e) : rowEl(e.alert)); });
        }
        main.appendChild(list);
        main.appendChild(footer());
    }

    function setSort(k) {
        if (Q.params.order_by === k) { Q.params.sort = Q.params.sort === 'asc' ? 'desc' : 'asc'; }
        else { Q.params.order_by = k; Q.params.sort = Q.vocab.sorts[k].first; }
        Q.params.page = 1;
        load();
    }

    function footer() {
        var r = Q.result;
        var start = r && r.entries_total ? (r.page - 1) * r.per_page + 1 : 0;
        var end = r ? Math.min(r.page * r.per_page, r.entries_total) : 0;
        var per = el('select', {cls: 'aq-per', id: 'aq-per', 'aria-label': 'Rows per page', on: {change: function (e) {
            var n = parseInt(e.target.value, 10);
            if (Q.vocab.page_sizes.indexOf(n) === -1) { return; }
            Q.params.per_page = n;
            Q.params.page = 1;
            saveLayout({per_page: n});
            load();
        }}});
        Q.vocab.page_sizes.forEach(function (n) {
            var o = el('option', {value: String(n), text: String(n)});
            if (n === Q.params.per_page) { o.selected = true; }
            per.appendChild(o);
        });
        return el('div', {cls: 'aq-qfoot'}, [
            el('span', {cls: 'aq-hints'}, [el('kbd', {text: 'j / k'}), ' navigate ', el('kbd', {text: 'e'}), ' escalate ', el('kbd', {text: 'x'}), ' select ', el('kbd', {text: 'm'}), ' merge',
                                          window.IrisHelp && window.IrisHelp.el ? window.IrisHelp.el('alert.keyboard', {cls: 'ml-1'}) : null,
                                          window.IrisHelp && window.IrisHelp.el ? window.IrisHelp.el('alert.queue_clusters', {cls: 'ml-1'}) : null]),
            el('span', {cls: 'aq-spacer'}),
            per,
            el('button', {type: 'button', cls: 'aq-btn aq-btn--sm', id: 'aq-prev', text: 'Prev', disabled: !r || r.page <= 1, on: {click: function () { Q.params.page -= 1; load(); }}}),
            el('span', {cls: 'aq-range', id: 'aq-range', text: r ? start + '–' + end + ' of ' + r.entries_total.toLocaleString('en-US') : ''}),
            el('button', {type: 'button', cls: 'aq-btn aq-btn--sm', id: 'aq-next', text: 'Next', disabled: !r || r.page >= r.last_page, on: {click: function () { Q.params.page += 1; load(); }}})
        ]);
    }

    function rowEl(a, member) {
        var sev = (a.severity || {}).name || 'Unspecified';
        var id = num(a.alert_id);
        var row = el('div', {cls: 'aq-row' + (member ? ' aq-row--member' : '') + (Q.selected === id ? ' aq-row--on' : '') + (a.is_open ? '' : ' aq-row--done'),
                             role: 'option', tabindex: Q.selected === id ? '0' : '-1', 'aria-selected': Q.selected === id ? 'true' : 'false', 'data-alert': String(id),
                             on: {click: function () { select(id, {openPane: true}); }}});
        row.style.setProperty('--aq-sev', sevColor(sev));
        var chips = [];
        if (a.classification) { chips.push(el('span', {cls: 'aq-chip aq-chip--mono', text: a.classification.name})); }
        if (a.cluster && !member) { chips.push(el('span', {cls: 'aq-chip aq-chip--cluster', text: 'Cluster'})); }
        (a.tags || []).slice(0, 3).forEach(function (t) { chips.push(el('span', {cls: 'aq-chip', text: t})); });
        row.appendChild(el('span', {cls: 'aq-sevbar', 'aria-hidden': 'true'}));
        if (Q.selectMode) {
            var box = el('input', {type: 'checkbox', cls: 'aq-pick', 'aria-label': 'Select alert ' + a.title, on: {click: function (e) {
                e.stopPropagation();
                if (e.target.checked) { Q.picked.add(id); } else { Q.picked.delete(id); }
                drawSelectionCount();
            }}});
            box.checked = Q.picked.has(id);
            row.appendChild(box);
        }
        row.appendChild(el('div', {cls: 'aq-row-body'}, [
            el('div', {cls: 'aq-row-meta'}, [
                el('span', {cls: 'aq-row-sev', text: sev.toUpperCase()}),
                el('span', {cls: 'aq-row-customer', text: (a.customer || {}).name || ''}),
                el('span', {cls: 'aq-spacer'}),
                el('span', {cls: 'aq-row-time', title: stamp(a.event_time), text: short(a.event_time)})]),
            el('div', {cls: 'aq-row-title', text: a.title}),
            el('div', {cls: 'aq-row-foot'}, [
                el('span', {cls: 'aq-chips'}, chips),
                el('span', {cls: 'aq-spacer'}),
                el('span', {cls: 'aq-row-owner', title: 'Owner', text: a.owner ? a.owner.name : ''}),
                el('span', {cls: 'aq-row-status', text: (a.status || {}).name || ''})])
        ]));
        return row;
    }

    function isExpanded(e) {
        if (Q.expanded[e.key] !== undefined) { return Q.expanded[e.key]; }
        return Q.result.entries.length === 1;
    }

    function clusterEl(e) {
        var open = isExpanded(e);
        var cid_ = num(e.cluster.id);
        var box = el('div', {cls: 'aq-cluster' + (open ? ' aq-cluster--open' : ''), 'data-cluster': String(cid_)});
        box.appendChild(el('div', {cls: 'aq-cluster-head'}, [
            el('button', {type: 'button', cls: 'aq-cluster-toggle', 'aria-expanded': open ? 'true' : 'false',
                          'aria-label': (open ? 'Collapse' : 'Expand') + ' cluster ' + e.cluster.title,
                          on: {click: function () { Q.expanded[e.key] = !open; drawMain(); }}}, [el('span', {cls: 'aq-caret', 'aria-hidden': 'true', text: open ? '▾' : '▸'})]),
            el('span', {cls: 'aq-badge-cluster', text: 'CLUSTER'}),
            el('span', {cls: 'aq-cluster-title', title: e.cluster.title, text: e.cluster.title}),
            el('span', {cls: 'aq-cluster-count', text: e.count.toLocaleString('en-US') + ' alerts'}),
            el('a', {cls: 'aq-cluster-open', href: '/alert-clusters/' + cid_ + (cid() !== null ? '?cid=' + cid() : ''), text: 'Open ›'})]));
        if (open) {
            e.alerts.forEach(function (a) { box.appendChild(rowEl(a, true)); });
            if (e.more > 0) {
                box.appendChild(el('button', {type: 'button', cls: 'aq-cluster-more', text: 'Show ' + Math.min(e.more, 25) + ' more of ' + e.count.toLocaleString('en-US'),
                                              on: {click: function () { moreOf(e); }}}));
            }
        }
        return box;
    }

    function moreOf(e) {
        api('GET', '/api/v2/alert-queue/clusters/' + num(e.cluster.id) + '/alerts?' + queryString({offset: String(e.alerts.length)})).then(function (res) {
            if (!res.ok || !res.data) { showError(errorOf(res, 'More alerts could not be loaded.')); return; }
            e.alerts = e.alerts.concat(res.data.alerts || []);
            e.more = Math.max(0, res.data.total - e.alerts.length);
            drawMain();
        });
    }

    function visibleRows() { return Array.prototype.slice.call(Q.root.querySelectorAll('#aq-list .aq-row[data-alert]')); }

    function autoSelect() {
        if (Q.view !== 'split' || Q.selected) { return; }
        var first = visibleRows()[0];
        if (first) { select(num(first.getAttribute('data-alert')), {}); }
    }

    // ------------------------------------------------------------------ selection

    function toggleSelect() {
        Q.selectMode = !Q.selectMode;
        if (!Q.selectMode) { Q.picked.clear(); }
        var b = byId('aq-select');
        b.textContent = Q.selectMode ? 'Cancel' : 'Select';
        b.setAttribute('aria-pressed', Q.selectMode ? 'true' : 'false');
        drawMain();
    }

    function statusMenu() {
        var sel = el('select', {cls: 'aq-select', id: 'aq-batch-status', 'aria-label': 'Set status of the selected alerts', on: {change: function (e) {
            var names = Q.options.statuses.map(function (s) { return s.name; });
            var i = names.indexOf(e.target.value);
            e.target.value = '';
            if (i !== -1) { callGlobal('changeStatusBatchAlerts', names[i]); }
        }}}, [el('option', {value: '', text: 'Set status…'})]);
        Q.options.statuses.forEach(function (s) { sel.appendChild(el('option', {value: s.name, text: s.name})); });
        return sel;
    }

    function selectionBar() {
        return el('div', {cls: 'aq-selbar', id: 'aq-selbar'}, [
            el('span', {cls: 'aq-selcount', id: 'aq-selcount', 'aria-live': 'polite', text: Q.picked.size + ' selected'}),
            el('button', {type: 'button', cls: 'aq-btn aq-btn--sm', id: 'aq-select-all', text: 'Select page', on: {click: function () {
                visibleRows().forEach(function (r) { Q.picked.add(num(r.getAttribute('data-alert'))); });
                drawMain();
            }}}),
            el('button', {type: 'button', cls: 'aq-btn aq-btn--sm', id: 'aq-select-clear', text: 'Clear', on: {click: function () { Q.picked.clear(); drawMain(); }}}),
            el('span', {cls: 'aq-spacer'}),
            statusMenu(),
            el('button', {type: 'button', cls: 'aq-btn aq-btn--sm', id: 'aq-batch-me', text: 'Assign to me', on: {click: function () { callGlobal('updateBatchAlerts', {alert_owner_id: num(Q.me.id)}); }}}),
            el('button', {type: 'button', cls: 'aq-btn aq-btn--sm', id: 'aq-batch-assign', text: 'Assign…', on: {click: function () { callGlobal('changeBatchAlertOwner'); }}}),
            el('button', {type: 'button', cls: 'aq-btn aq-btn--sm', id: 'aq-batch-merge', text: 'Merge / escalate', on: {click: function () { callGlobal('mergeMultipleAlertsModal'); }}}),
            el('button', {type: 'button', cls: 'aq-btn aq-btn--sm', id: 'aq-batch-close', text: 'Close…', on: {click: function () { callGlobal('closeBatchAlerts'); }}}),
            Q.permissions.delete ? el('button', {type: 'button', cls: 'aq-btn aq-btn--sm aq-btn--danger', id: 'aq-batch-delete', text: 'Delete', on: {click: function () { callGlobal('deleteBatchAlerts'); }}}) : null
        ]);
    }

    function drawSelectionCount() {
        var c = byId('aq-selcount');
        if (c) { c.textContent = Q.picked.size + ' selected'; }
    }

    // ------------------------------------------------------------------ the detail pane

    function select(id, opts) {
        opts = opts || {};
        Q.selected = num(id);
        Array.prototype.forEach.call(Q.root.querySelectorAll('.aq-row[data-alert]'), function (r) {
            var on = num(r.getAttribute('data-alert')) === Q.selected;
            r.classList.toggle('aq-row--on', on);
            r.setAttribute('aria-selected', on ? 'true' : 'false');
            r.setAttribute('tabindex', on ? '0' : '-1');
        });
        if (Q.view !== 'split' && opts.openPane) { Q.detailOpen = true; applyBodyClass(); }
        syncUrl();
        return loadDetail(Q.selected);
    }

    function loadDetail(id) {
        Q.dseq += 1;
        var mine = Q.dseq;
        var pane = byId('aq-detail');
        pane.removeAttribute('data-ad-settled');
        return api('GET', '/api/v2/alert-queue/alerts/' + num(id)).then(function (res) {
            if (mine !== Q.dseq) { return; }
            if (!res.ok || !res.data) {
                Q.detail = null;
                pane.textContent = '';
                pane.appendChild(el('p', {cls: 'aq-empty', id: 'aq-detail-missing', text: res.status === 404 ? 'This alert does not exist, or you cannot see it.' : 'This alert could not be loaded.'}));
                pane.setAttribute('data-ad-settled', 'missing');
                return;
            }
            Q.detail = res.data;
            drawDetail();
        });
    }

    function drawDetail() {
        window.IrisAlertDetail.render(byId('aq-detail'), Q.detail, {
            options: Q.options, me: Q.me, permissions: Q.permissions, cid: cid(), tab: Q.tab, stamp: stamp, when: age,
            moduleOptions: Q.moduleOptions, moduleIoc: Q.moduleIoc,
            onTab: function (t) { Q.tab = t; },
            select: function (id) { select(id, {openPane: true}); },
            back: closeDetailPane
        });
    }

    function closeDetailPane() {
        Q.detailOpen = false;
        Q.selected = Q.view === 'split' ? Q.selected : null;
        applyBodyClass();
        syncUrl();
    }

    // ------------------------------------------------------------------ the board

    function drawBoard(main) {
        var b = Q.board;
        var groupSel = el('select', {cls: 'aq-select', id: 'aq-board-group', 'aria-label': 'Board layout', on: {change: function (e) {
            var keys = Q.vocab.board_groups.map(function (g) { return g.key; });
            var i = keys.indexOf(e.target.value);
            if (i === -1) { return; }
            Q.params.board = keys[i];
            saveLayout({board: keys[i]});
            load();
        }}});
        Q.vocab.board_groups.forEach(function (g) {
            var o = el('option', {value: g.key, text: g.label});
            if (g.key === Q.params.board) { o.selected = true; }
            groupSel.appendChild(o);
        });
        var desc = Q.vocab.board_groups.filter(function (g) { return g.key === Q.params.board; })[0];
        main.appendChild(el('div', {cls: 'aq-board-head'}, [groupSel, el('span', {cls: 'aq-dim', text: desc ? desc.description + '.' : ''}),
                                                            window.IrisHelp && window.IrisHelp.el ? window.IrisHelp.el('alert.views', {cls: 'ml-1'}) : null]));
        if (!b) { main.appendChild(el('p', {cls: 'aq-empty', text: 'The board could not be shown.'})); return; }
        var field = b.group === 'severity' ? 'alert_severity_id' : 'alert_status_id';
        var columns = b.columns || [];
        if (!columns.length) {
            main.appendChild(el('p', {cls: 'aq-empty', text: b.group === 'severity' ? 'No severities are configured, so there is nothing to lay the board out by.' : 'Every configured alert status is a terminal one, so the board has no column to show.'}));
            return;
        }
        main.appendChild(el('div', {cls: 'aq-board', id: 'aq-board'}, columns.map(function (c) {
            var col = el('section', {cls: 'aq-col', 'data-col': String(num(c.id)), 'aria-label': c.name}, [
                el('header', {cls: 'aq-col-head'}, [el('span', {cls: 'aq-col-name', text: c.name}), el('span', {cls: 'aq-col-count', text: c.total.toLocaleString('en-US')})])]);
            if (b.group === 'severity') { col.style.setProperty('--aq-sev', sevColor(c.name)); }
            var list = el('div', {cls: 'aq-col-list'}, c.alerts.map(function (a) { return cardEl(a, b, columns, c, field); }));
            if (!c.alerts.length) { list.appendChild(el('p', {cls: 'aq-col-empty', text: 'No alerts'})); }
            if (c.total > c.alerts.length) { list.appendChild(el('p', {cls: 'aq-col-more', text: 'Showing the newest ' + c.alerts.length + ' of ' + c.total.toLocaleString('en-US')})); }
            col.appendChild(list);
            if (Q.permissions.write) {
                col.addEventListener('dragover', function (e) { if (Q.drag) { e.preventDefault(); col.classList.add('aq-col--over'); } });
                col.addEventListener('dragleave', function () { col.classList.remove('aq-col--over'); });
                col.addEventListener('drop', function (e) {
                    e.preventDefault();
                    col.classList.remove('aq-col--over');
                    var d = Q.drag;
                    Q.drag = null;
                    if (d && d.col !== num(c.id)) { moveCard(d.id, field, num(c.id)); }
                });
            }
            return col;
        })));
        main.appendChild(el('p', {cls: 'aq-dim aq-board-note', text: 'Closed, merged and escalated alerts are never shown.' + (Q.permissions.write ? ' Drag a card to another column to change its ' + (b.group === 'severity' ? 'severity' : 'status') + ', or focus one and press Ctrl + ← →.' : '')}));
    }

    function moveCard(id, field, value) {
        var data = {};
        data[field] = value;
        // This board holds unowned alerts, and the update route claims one for whoever changes it unless told otherwise.
        if (field === 'alert_severity_id') { data.alert_owner_id = -1; }
        callGlobal('updateAlert', num(id), data, true);
    }

    function cardEl(a, b, columns, col, field) {
        var id = num(a.alert_id);
        var card = el('article', {cls: 'aq-card', tabindex: '0', 'data-alert': String(id), draggable: Q.permissions.write ? 'true' : null, 'aria-label': a.title,
                                  on: {click: function () { select(id, {openPane: true}); }}});
        card.style.setProperty('--aq-sev', sevColor((a.severity || {}).name));
        card.appendChild(el('div', {cls: 'aq-card-title', text: a.title}));
        card.appendChild(el('div', {cls: 'aq-row-meta'}, [el('span', {cls: 'aq-row-customer', text: (a.customer || {}).name || ''}), el('span', {cls: 'aq-spacer'}), el('span', {cls: 'aq-row-time', text: short(a.event_time)})]));
        var foot = el('div', {cls: 'aq-row-foot'}, [
            a.owner ? el('span', {cls: 'aq-row-owner', text: a.owner.name}) : null,
            el('span', {cls: 'aq-spacer'}),
            !a.owner && Q.permissions.write ? el('button', {type: 'button', cls: 'aq-btn aq-btn--sm aq-take', title: 'Assign this alert to me', text: 'Take', on: {click: function (e) {
                e.stopPropagation();
                callGlobal('updateAlert', id, {alert_owner_id: num(Q.me.id)}, true);
            }}}) : null]);
        card.appendChild(foot);
        card.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && e.target === card) { e.preventDefault(); select(id, {openPane: true}); }
        });
        if (Q.permissions.write) {
            card.addEventListener('dragstart', function (e) { Q.drag = {id: id, col: num(col.id)}; if (e.dataTransfer) { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(id)); } });
            card.addEventListener('dragend', function () { Q.drag = null; });
            card.addEventListener('keydown', function (e) {
                if (!(e.ctrlKey || e.metaKey) || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight')) { return; }
                e.preventDefault();
                var i = columns.indexOf(col) + (e.key === 'ArrowRight' ? 1 : -1);
                if (i >= 0 && i < columns.length) { moveCard(id, field, num(columns[i].id)); }
            });
        }
        return card;
    }

    // ------------------------------------------------------------------ the Filter panel + saved filters

    var FILTER_FORM = [
        ['alert_title', 'Title', 'text'], ['alert_description', 'Description', 'text'], ['alert_source', 'Source', 'text'], ['alert_tags', 'Tags', 'text'],
        ['alert_status_id', 'Status', 'statuses'], ['alert_severity_id', 'Severity', 'severities'], ['alert_classification_id', 'Classification', 'classifications'],
        ['alert_resolution_id', 'Resolution status', 'resolutions'], ['alert_customer_id', 'Customer', 'customers'], ['alert_owner_id', 'Owner', 'users'],
        ['source_start_date', 'Source start date', 'date'], ['source_end_date', 'Source end date', 'date'], ['creation_start_date', 'Creation start date', 'date'], ['creation_end_date', 'Creation end date', 'date'],
        ['alert_assets', 'Asset(s) name', 'text'], ['alert_iocs', 'IOC(s)', 'text'], ['alert_ids', 'Alert(s) ID', 'text'], ['source_reference', 'Source reference', 'text'],
        ['case_id', 'Case ID', 'number'], ['cluster_id', 'Alert cluster ID (-1 = none)', 'number']
    ];

    function toggleFilters() {
        var p = byId('aq-filter-panel');
        p.hidden = !p.hidden;
        byId('aq-filter-btn').setAttribute('aria-expanded', p.hidden ? 'false' : 'true');
        if (!p.hidden && !Q.savedLoaded) { loadSaved(); }
    }

    function filterHelp(name) {
        if (!window.IrisHelp || !window.IrisHelp.el) { return null; }
        if (name === 'alert_source') { return window.IrisHelp.el('alert.source', {cls: 'ml-1'}); }
        if (name === 'source_reference') { return window.IrisHelp.el('alert.source_reference', {cls: 'ml-1'}); }
        if (name === 'source_start_date') { return window.IrisHelp.el('alert.source_event_time', {cls: 'ml-1'}); }
        if (name === 'creation_start_date') { return window.IrisHelp.el('alert.creation_time', {cls: 'ml-1'}); }
        if (name === 'alert_owner_id') { return window.IrisHelp.el('alert.owner', {cls: 'ml-1'}); }
        if (name === 'case_id') { return window.IrisHelp.el('alert.linked_cases', {cls: 'ml-1'}); }
        return null;
    }

    function filterValue(name) {
        var v = (Q.params.filters || {})[name];
        return v === undefined || v === null ? '' : (Array.isArray(v) ? v.join(',') : String(v));
    }

    function drawFilterPanel() {
        var p = byId('aq-filter-panel');
        p.textContent = '';
        var grid = el('div', {cls: 'aq-filter-grid'});
        FILTER_FORM.forEach(function (f) {
            var id = 'aqf-' + f[0];
            var control;
            if (f[2] === 'text' || f[2] === 'date' || f[2] === 'number') {
                control = el('input', {type: f[2] === 'text' ? 'text' : f[2], id: id, name: f[0], cls: 'aq-input', value: filterValue(f[0])});
            } else {
                control = el('select', {id: id, name: f[0], cls: 'aq-input'}, [el('option', {value: '', text: 'Any'})]);
                if (f[0] === 'alert_owner_id') { control.appendChild(el('option', {value: '-1', text: 'Unassigned'})); }
                (Q.options[f[2]] || []).forEach(function (o) {
                    var opt = el('option', {value: String(o.id), text: o.name});
                    if (String(o.id) === filterValue(f[0])) { opt.selected = true; }
                    control.appendChild(opt);
                });
                if (f[0] === 'alert_owner_id' && filterValue(f[0]) === '-1') { control.value = '-1'; }
            }
            grid.appendChild(el('div', {cls: 'aq-field'}, [el('div', {cls: 'aq-label-row'}, [el('label', {cls: 'aq-label', 'for': id, text: f[1]}), filterHelp(f[0])]), control]));
        });
        var custom = el('textarea', {id: 'aqf-custom_conditions', name: 'custom_conditions', cls: 'aq-input aq-custom', rows: '4', spellcheck: 'false', 'aria-label': 'Custom conditions (JSON)'});
        custom.value = filterValue('custom_conditions');
        p.appendChild(el('div', {cls: 'aq-label-row aq-filter-title'}, [el('span', {cls: 'aq-label', text: 'Filter fields'}),
                                                                        window.IrisHelp && window.IrisHelp.el ? window.IrisHelp.el('alert.filters', {cls: 'ml-1'}) : null]));
        p.appendChild(grid);
        p.appendChild(el('div', {cls: 'aq-label-row aq-custom-help'}, [el('span', {cls: 'aq-label', text: 'Custom conditions (JSON)'}),
                                                                       window.IrisHelp && window.IrisHelp.el ? window.IrisHelp.el('alert.custom_conditions', {cls: 'ml-1'}) : null]));
        p.appendChild(el('details', {cls: 'aq-custom-wrap', open: filterValue('custom_conditions') ? true : null}, [
            el('summary', {text: 'Edit the conditions'}),
            custom,
            el('p', {cls: 'aq-dim', text: 'For fields the grid does not show. Example: [{"field": "severity.severity_name", "operator": "like", "value": "Critical"}]'})
        ]));
        p.appendChild(el('p', {cls: 'aq-dim', id: 'aq-also', text: 'The search bar applies as well: edit it there.'}));
        var saved = el('select', {id: 'aq-saved', cls: 'aq-input aq-input--saved', 'aria-label': 'Saved filters', on: {change: applySaved}}, [el('option', {value: '', text: 'Saved filters…'})]);
        p.appendChild(el('div', {cls: 'aq-filter-foot'}, [
            saved,
            window.IrisHelp && window.IrisHelp.el ? window.IrisHelp.el('alert.saved_filters', {cls: 'ml-1'}) : null,
            el('button', {type: 'button', cls: 'aq-btn aq-btn--sm', id: 'aq-saved-delete', text: 'Delete saved', disabled: true, on: {click: deleteSaved}}),
            el('span', {cls: 'aq-spacer'}),
            el('button', {type: 'button', cls: 'aq-btn aq-btn--sm', id: 'aq-filter-clear', text: 'Clear', on: {click: clearFilters}}),
            el('button', {type: 'button', cls: 'aq-btn aq-btn--sm', id: 'aq-filter-save', text: 'Save filter…', on: {click: saveDialog}}),
            el('button', {type: 'submit', cls: 'aq-btn aq-btn--sm aq-btn--primary', id: 'aq-filter-apply', text: 'Apply'})
        ]));
    }

    function readFilters() {
        var out = {};
        Array.prototype.forEach.call(byId('aq-filter-panel').querySelectorAll('[name]'), function (c) {
            var name = Q.vocab.filter_params[Q.vocab.filter_params.indexOf(c.name)];
            var v = String(c.value || '').trim();
            if (name && v) { out[name] = v; }
        });
        return out;
    }

    function applyFilters() {
        Q.params.filters = readFilters();
        Q.params.page = 1;
        return load();
    }

    function clearFilters() {
        Q.params.filters = {};
        drawFilterPanel();
        Q.savedLoaded = false;
        loadSaved();
        Q.params.page = 1;
        return load();
    }

    function loadSaved() {
        Q.savedLoaded = true;
        api('GET', '/filters/' + Q.vocab.saved_filter_type + '/list').then(function (res) {
            var sel = byId('aq-saved');
            if (!sel || !res.ok || !res.data) { return; }
            Q.saved = res.data.data || [];
            while (sel.options.length > 1) { sel.remove(1); }
            Q.saved.forEach(function (f) { sel.appendChild(el('option', {value: String(num(f.filter_id)), text: f.filter_name})); });
        });
    }

    function applySaved() {
        var id = num(byId('aq-saved').value);
        byId('aq-saved-delete').disabled = !id;
        if (!id) { return; }
        api('GET', '/filters/' + id).then(function (res) {
            var data = res.data && res.data.data && res.data.data.filter_data;
            if (!res.ok || !data) { showError(errorOf(res, 'The filter could not be read.')); return; }
            var filters = {};
            Object.keys(data).forEach(function (k) {
                if (Q.vocab.filter_params.indexOf(k) !== -1 && data[k] !== '' && data[k] !== null) { filters[k] = data[k]; }
            });
            Q.params.filters = filters;
            Q.params.q = typeof data.q === 'string' ? data.q : '';
            Q.params.page = 1;
            var keep = byId('aq-saved').value;
            drawFilterPanel();
            Q.savedLoaded = false;
            loadSaved();
            load().then(function () {
                var s = byId('aq-saved');
                if (s) { s.value = keep; byId('aq-saved-delete').disabled = !num(keep); }
            });
        });
    }

    function deleteSaved() {
        var id = num(byId('aq-saved').value);
        if (!id) { return; }
        api('POST', '/filters/delete/' + id, {}).then(function (res) {
            if (!res.ok) { showError(errorOf(res, 'The filter could not be deleted.')); return; }
            Q.savedLoaded = false;
            byId('aq-saved').value = '';
            byId('aq-saved-delete').disabled = true;
            loadSaved();
        });
    }

    function dialogShell(title, body, okText, onOk) {
        var dlg = byId('aq-dialog');
        dlg.textContent = '';
        var err = el('p', {cls: 'aq-alert aq-dlg-err', id: 'aq-dlg-err', role: 'alert', hidden: true});
        var ok = el('button', {type: 'button', cls: 'aq-btn aq-btn--primary', id: 'aq-dlg-ok', text: okText, on: {click: function () { onOk(err, ok); }}});
        dlg.appendChild(el('div', {cls: 'aq-dlg-head'}, [el('h2', {cls: 'aq-dlg-title', id: 'aq-dlg-title', text: title}),
            el('button', {type: 'button', cls: 'aq-icon', id: 'aq-dlg-x', 'aria-label': 'Close', text: '×', on: {click: function () { dlg.close(); }}})]));
        dlg.appendChild(body);
        dlg.appendChild(err);
        dlg.appendChild(el('div', {cls: 'aq-dlg-foot'}, [el('button', {type: 'button', cls: 'aq-btn', id: 'aq-dlg-cancel', text: 'Cancel', on: {click: function () { dlg.close(); }}}), ok]));
        if (typeof dlg.showModal === 'function') { dlg.showModal(); } else { dlg.setAttribute('open', ''); }
        return dlg;
    }

    function saveDialog() {
        var name = el('input', {type: 'text', id: 'aq-sf-name', cls: 'aq-input', maxlength: '100'});
        var desc = el('input', {type: 'text', id: 'aq-sf-desc', cls: 'aq-input', maxlength: '300'});
        var priv = el('input', {type: 'checkbox', id: 'aq-sf-private'});
        priv.checked = true;
        var body = el('div', {cls: 'aq-dlg-body'}, [
            el('label', {cls: 'aq-field', 'for': 'aq-sf-name'}, [el('span', {cls: 'aq-label', text: 'Filter name *'}), name]),
            el('label', {cls: 'aq-field', 'for': 'aq-sf-desc'}, [el('span', {cls: 'aq-label', text: 'Filter description'}), desc]),
            el('label', {cls: 'aq-check', 'for': 'aq-sf-private'}, [priv, ' Private filter'])]);
        var dlg = dialogShell('Save filter', body, 'Save', function (err, ok) {
            var filterName = name.value.trim();
            if (!filterName) { err.textContent = 'A filter needs a name.'; err.hidden = false; return; }
            var data = readFilters();
            if (Q.params.q) { data.q = Q.params.q; }
            ok.disabled = true;
            api('POST', '/filters/add', {filter_name: filterName, filter_description: desc.value.trim(), filter_data: data, filter_is_private: !!priv.checked,
                                         filter_type: Q.vocab.saved_filter_type}).then(function (res) {
                ok.disabled = false;
                if (!res.ok) { err.textContent = errorOf(res, 'The filter could not be saved.'); err.hidden = false; return; }
                dlg.close();
                Q.savedLoaded = false;
                loadSaved();
            });
        });
    }

    // ------------------------------------------------------------------ New alert

    function newAlertDialog() {
        var text = function (id, label, placeholder, required) {
            var input = el('input', {type: 'text', id: id, cls: 'aq-input', placeholder: placeholder || null});
            return {input: input, node: el('label', {cls: 'aq-field', 'for': id}, [el('span', {cls: 'aq-label', text: label + (required ? ' *' : '')}), input])};
        };
        var choose = function (id, label, source) {
            var sel = el('select', {id: id, cls: 'aq-input'}, [el('option', {value: '', text: label})]);
            (Q.options[source] || []).forEach(function (o) { sel.appendChild(el('option', {value: String(o.id), text: o.name})); });
            return {input: sel, node: el('label', {cls: 'aq-field', 'for': id}, [el('span', {cls: 'aq-label', text: label + ' *'}), sel])};
        };
        var title = text('aq-na-title', 'Title', 'What happened?', true);
        var desc = el('textarea', {id: 'aq-na-desc', cls: 'aq-input aq-textarea', rows: '4', placeholder: 'Who reported it, what they saw, anything already checked.'});
        var customer = choose('aq-na-customer', 'Customer', 'customers');
        var severity = choose('aq-na-severity', 'Severity', 'severities');
        var status = choose('aq-na-status', 'Status', 'statuses');
        var classification = choose('aq-na-classification', 'Classification', 'classifications');
        var source = text('aq-na-source', 'Source', 'e.g. SOC hotline');
        var when = el('input', {type: 'datetime-local', id: 'aq-na-time', cls: 'aq-input'});
        var ref = text('aq-na-ref', 'Source reference');
        var link = text('aq-na-link', 'Source link');
        var tags = text('aq-na-tags', 'Tags', 'Comma-separated');
        var note = el('textarea', {id: 'aq-na-note', cls: 'aq-input aq-textarea', rows: '2'});
        var body = el('div', {cls: 'aq-dlg-body aq-form'}, [
            el('p', {cls: 'aq-dim', text: 'Raise an alert by hand: a hotline call, an out-of-band report, anything that did not come in through a feed.'}),
            title.node,
            el('label', {cls: 'aq-field', 'for': 'aq-na-desc'}, [el('span', {cls: 'aq-label', text: 'Description'}), desc, el('span', {cls: 'aq-dim', text: 'Supports markdown.'})]),
            el('div', {cls: 'aq-row2'}, [customer.node, severity.node]), el('div', {cls: 'aq-row2'}, [status.node, classification.node]),
            el('div', {cls: 'aq-row2'}, [source.node, el('label', {cls: 'aq-field', 'for': 'aq-na-time'}, [el('span', {cls: 'aq-label', text: 'Event time'}), when,
                                                                                                         el('span', {cls: 'aq-dim', text: 'When it happened (UTC). Defaults to now if left empty.'})])]),
            el('div', {cls: 'aq-row2'}, [ref.node, link.node]),
            tags.node,
            el('label', {cls: 'aq-field', 'for': 'aq-na-note'}, [el('span', {cls: 'aq-label', text: 'Note'}), note])
        ]);
        var helpNew = window.IrisHelp && window.IrisHelp.el ? window.IrisHelp.el('alert.new_alert', {cls: 'ml-1'}) : null;
        if (helpNew) { body.firstChild.appendChild(helpNew); }
        var dlg = dialogShell('New alert', body, 'Create alert', function (err, ok) {
            var missing = [[title.input, 'a title'], [customer.input, 'a customer'], [severity.input, 'a severity'], [status.input, 'a status'], [classification.input, 'a classification']]
                .filter(function (p) { return !p[0].value.trim(); }).map(function (p) { return p[1]; });
            if (missing.length) { err.textContent = 'Give the alert ' + missing.join(', ') + '.'; err.hidden = false; return; }
            var payload = {alert_title: title.input.value.trim(), alert_description: desc.value.trim(), alert_customer_id: num(customer.input.value),
                           alert_severity_id: num(severity.input.value), alert_status_id: num(status.input.value), alert_classification_id: num(classification.input.value),
                           alert_source: source.input.value.trim(), alert_source_ref: ref.input.value.trim(), alert_source_link: link.input.value.trim(),
                           alert_tags: tags.input.value.trim(), alert_note: note.value.trim(), alert_context: {}, alert_source_content: {}};
            var m = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})/.exec(when.value || '');
            if (m) { payload.alert_source_event_time = m[1] + ':00'; }
            ok.disabled = true;
            api('POST', '/alerts/add', payload).then(function (res) {
                ok.disabled = false;
                if (!res.ok || !res.data || res.data.status === 'error') { err.textContent = errorOf(res, 'The alert could not be created.'); err.hidden = false; return; }
                dlg.close();
                var created = res.data.data && res.data.data.alert_id;
                reload().then(function () { if (created) { select(num(created), {openPane: true}); } });
            });
        });
        title.input.focus();
        return dlg;
    }

    // ------------------------------------------------------------------ keyboard

    function typing(t) { return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable); }

    function moved(step) {
        var rows = visibleRows();
        if (!rows.length) { return; }
        var i = rows.map(function (r) { return num(r.getAttribute('data-alert')); }).indexOf(Q.selected);
        var next = rows[Math.max(0, Math.min(rows.length - 1, i === -1 ? 0 : i + step))];
        select(num(next.getAttribute('data-alert')), {});
        if (next.scrollIntoView) { next.scrollIntoView({block: 'nearest'}); }
    }

    function onKey(e) {
        if (!Q || e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) { return; }
        if (document.querySelector('.modal.show') || document.querySelector('dialog[open]')) { return; }
        if (e.key === '/') { e.preventDefault(); Q.bar.focus(); return; }
        if (e.key === 'Escape' && Q.detailOpen) { e.preventDefault(); closeDetailPane(); return; }
        if (Q.view === 'board') { return; }
        var id = Q.selected;
        var onControl = e.target && e.target.closest && e.target.closest('button, a, summary');
        if (e.key === 'Enter' && id && !onControl && Q.view !== 'split') { e.preventDefault(); Q.detailOpen = true; applyBodyClass(); return; }
        if (e.key === 'j') { e.preventDefault(); moved(1); }
        else if (e.key === 'k') { e.preventDefault(); moved(-1); }
        else if (e.key === 'e' && id && Q.permissions.write) { e.preventDefault(); callGlobal('mergeAlertModal', id); }
        else if (e.key === 'm' && id && Q.permissions.write) { e.preventDefault(); callGlobal('mergeAlertModal', id, true); }
        else if (e.key === 'x' && id && Q.permissions.write) {
            e.preventDefault();
            if (!Q.selectMode) { toggleSelect(); }
            if (Q.picked.has(id)) { Q.picked.delete(id); } else { Q.picked.add(id); }
            drawMain();
        }
    }

    // ------------------------------------------------------------------ start

    function start(root, state) {
        var saved = layout();
        Q = {root: root, vocab: state.vocab, options: state.options, me: state.me, permissions: state.permissions, params: state.params,
             result: state.result, board: state.board, tabCounts: state.tab_counts, seq: 1, dseq: 0, picked: new Set(), selectMode: false, expanded: {},
             selected: null, detail: null, detailOpen: false, tab: 'overview', newCount: 0, moduleOptions: [], moduleIoc: [], saved: [], savedLoaded: false,
             view: state.view || (state.vocab.views.indexOf(saved.view) !== -1 ? saved.view : state.vocab.default_view)};
        var per = num(saved.per_page);
        var urlHasPer = /[?&]per_page=/.test(location.search);
        var perChanged = !urlHasPer && state.vocab.page_sizes.indexOf(per) !== -1 && per !== Q.params.per_page;
        if (perChanged) { Q.params.per_page = per; }
        if (state.vocab.board_groups.some(function (g) { return g.key === saved.board; }) && !/[?&]board=/.test(location.search)) { Q.params.board = saved.board; }
        frame();
        if (state.error) { showError(state.error); }
        if (state.query_error) { Q.bar.setError(state.query_error, Q.params.q); showError(''); }
        var needed = (Q.view === 'board' && !Q.board) || (Q.view !== 'board' && !Q.result) || perChanged;
        var hash = /^#alert=(\d{1,12})$/.exec(location.hash);
        if (hash) { Q.selected = num(hash[1]); }
        document.addEventListener('keydown', onKey);
        if (state.detail) {
            Q.selected = num(state.detail.alert_id);
            Q.detail = state.detail;
            Q.detailOpen = Q.view !== 'split';
            drawDetail();
        }
        if (needed && !state.query_error && !state.error) {
            load();
        } else {
            if (Q.result) { Q.bar.set(Q.result.query); } else if (Q.board) { Q.bar.set(Q.board.query); }
            drawHead();
            drawMain();
            autoSelect();
            Q.root.setAttribute('data-aq-settled', '1');
        }
        if (hash) { select(Q.selected, {openPane: true}); }
        window.addEventListener('load', function () {
            if (!Q.permissions.write || typeof window.fetchModulesOptionsAlert !== 'function') { return; }
            // Read when a menu opens or a panel draws: only a list already on screen needs drawing again.
            window.fetchModulesOptionsAlert().then(function (r) { Array.prototype.push.apply(Q.moduleOptions, (r && r.data) || []); });
            window.fetchModulesOptionsIoc().then(function (r) {
                Array.prototype.push.apply(Q.moduleIoc, (r && r.data) || []);
                if (Q.detail && Q.tab === 'iocs') { drawDetail(); }
            });
        });
    }

    function mount(root, state) {
        if (state) { start(root, state); return; }
        api('GET', '/api/v2/alert-queue/state' + location.search).then(function (res) {
            if (!res.ok || !res.data) {
                root.appendChild(el('div', {cls: 'aq-alert', role: 'alert', text: errorOf(res, 'The alerts could not be loaded.')}));
                return;
            }
            start(root, res.data);
        });
    }

    window.IrisAlertQueue = {
        mount: mount,
        reload: function () { return Q ? reload() : undefined; },
        alertChanged: function (id) { return Q ? alertChanged(id) : undefined; },
        picked: function () { return Q ? Array.from(Q.picked) : []; },
        detailOf: function (id) { return Q && Q.detail && num(Q.detail.alert_id) === num(id) ? Q.detail : null; },
        options: function () { return Q ? Q.options : {}; },
        newAlert: function () { if (Q) { Q.newCount += 1; drawNewBadge(); } }
    };
})();

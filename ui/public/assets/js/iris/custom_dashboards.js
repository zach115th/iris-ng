/* IrisDashboards - the custom dashboards' list and view pages (iris-ng, 2026-11-09).
 *
 *   IrisDashboards.mountList(root, state)   state = GET /api/v2/custom-dashboards (null: fetched)
 *   IrisDashboards.mountView(root, state)   state = {dashboard, schema, params, data, error, me} (null: fetched)
 *   IrisDashboards.drawSections(container, definition, opts) -> {widgetId: body}; fill(bodies, definition, data, opts)
 *   IrisDashboards.api(method, url, body)   -> Promise {ok, status, data}
 *
 * Needs IrisDashWidgets (dashboard_widgets.js). Every value from the server or the page is written with DOM calls;
 * values read back from inputs are re-derived (a number, a key of a closed set) before they reach a URL.
 */
(function () {
    'use strict';

    var UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

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

    function svg(paths, cls) {
        var ns = 'http://www.w3.org/2000/svg';
        var s = document.createElementNS(ns, 'svg');
        s.setAttribute('viewBox', '0 0 24 24');
        s.setAttribute('fill', 'none');
        s.setAttribute('stroke', 'currentColor');
        s.setAttribute('stroke-width', '2');
        s.setAttribute('stroke-linecap', 'round');
        s.setAttribute('stroke-linejoin', 'round');
        s.setAttribute('aria-hidden', 'true');
        s.setAttribute('class', cls || 'dash-i');
        paths.forEach(function (p) {
            var node = document.createElementNS(ns, p[0]);
            Object.keys(p[1]).forEach(function (k) { node.setAttribute(k, p[1][k]); });
            s.appendChild(node);
        });
        return s;
    }

    // Lucide icons (ISC).
    var ICONS = {
        layout: [['rect', {width: '7', height: '9', x: '3', y: '3', rx: '1'}], ['rect', {width: '7', height: '5', x: '14', y: '3', rx: '1'}],
                 ['rect', {width: '7', height: '9', x: '14', y: '12', rx: '1'}], ['rect', {width: '7', height: '5', x: '3', y: '16', rx: '1'}]],
        plus: [['path', {d: 'M5 12h14'}], ['path', {d: 'M12 5v14'}]],
        copy: [['rect', {width: '14', height: '14', x: '8', y: '8', rx: '2', ry: '2'}], ['path', {d: 'M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2'}]],
        code: [['polyline', {points: '16 18 22 12 16 6'}], ['polyline', {points: '8 6 2 12 8 18'}]],
        pen: [['path', {d: 'M12 20h9'}], ['path', {d: 'M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z'}]],
        back: [['path', {d: 'm12 19-7-7 7-7'}], ['path', {d: 'M19 12H5'}]],
        refresh: [['path', {d: 'M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8'}], ['path', {d: 'M21 3v5h-5'}],
                  ['path', {d: 'M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16'}], ['path', {d: 'M8 16H3v5'}]],
        lock: [['rect', {width: '18', height: '11', x: '3', y: '11', rx: '2', ry: '2'}], ['path', {d: 'M7 11V7a5 5 0 0 1 10 0v4'}]],
        sparkle: [['path', {d: 'M12 3v18'}], ['path', {d: 'm4.93 4.93 14.14 14.14'}], ['path', {d: 'M3 12h18'}], ['path', {d: 'm4.93 19.07 14.14-14.14'}]]
    };

    function icon(name, cls) { return svg(ICONS[name] || [], cls); }

    function csrf() {
        var t = document.getElementById('csrf_token');
        return t ? t.value : '';
    }

    function cidParam() {
        var m = /[?&]cid=(\d{1,12})(?:&|$)/.exec(location.search);
        return m ? 'cid=' + parseInt(m[1], 10) : '';
    }

    function pageUrl(path, extra) {
        var q = [cidParam(), extra || ''].filter(Boolean).join('&');
        return path + (q ? '?' + q : '');
    }

    function keyOf(value) {
        /* A dashboard key the server gave: a uuid, or a built-in key - rebuilt from the match. */
        var s = String(value || '');
        var m = UUID.exec(s);
        if (m) { return m[0]; }
        return s === 'statistics' ? 'statistics' : null;
    }

    function api(method, url, body) {
        var opts = {method: method, credentials: 'same-origin', headers: {'Accept': 'application/json'}};
        if (body !== undefined) {
            opts.headers['Content-Type'] = 'application/json';
            var b = Object.assign({}, body);
            if (method === 'POST') { b.csrf_token = csrf(); }
            opts.body = JSON.stringify(b);
        }
        return fetch(url, opts).then(function (r) {
            return r.text().then(function (t) {
                var data = null;
                try { data = t ? JSON.parse(t) : null; } catch (e) { data = null; }
                return {ok: r.ok, status: r.status, data: data};
            });
        }, function () { return {ok: false, status: 0, data: null}; });
    }

    function errorText(res, fallback) {
        var d = res && res.data;
        if (d && typeof d.message === 'string' && d.message) { return d.message; }
        if (res && res.status === 404) { return 'Not found (it may have been deleted, or it is not shared with you).'; }
        if (res && res.status === 403) { return 'You cannot do that here.'; }
        return fallback;
    }

    function stamp(iso) {
        /* A stored UTC timestamp as text, labelled UTC - never re-read through the browser's clock. */
        var m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(String(iso || ''));
        return m ? m[1] + ' ' + m[2] + ' UTC' : '';
    }

    function hue(key) {
        var h = 0, s = String(key || '');
        for (var i = 0; i < s.length; i++) { h = (h * 31 + s.charCodeAt(i)) % 360; }
        return h;
    }

    function toast(root, text, kind) {
        var box = root.querySelector('.dash-toast');
        if (!box) { return; }
        box.textContent = text;
        box.className = 'dash-toast dash-toast--' + (kind || 'ok');
        box.hidden = false;
        clearTimeout(box.__t);
        box.__t = setTimeout(function () { box.hidden = true; }, 4000);
    }

    // ------------------------------------------------------------------ the JSON dialog (list + view)

    function jsonDialog(root, dash, onClone) {
        var dlg = root.querySelector('dialog.dash-dialog--json');
        dlg.textContent = '';
        var text = JSON.stringify({name: dash.name, description: dash.description, is_shared: dash.is_shared,
                                   definition: dash.definition}, null, 2);
        var pre = el('pre', {cls: 'dash-json', tabindex: '0', text: text});
        var status = el('span', {cls: 'dash-dim', 'aria-live': 'polite'});
        dlg.appendChild(el('div', {cls: 'dash-dlg-head'}, [el('h2', {cls: 'dash-dlg-title', id: 'dash-dlg-title', text: dash.name + ' — JSON'})]));
        dlg.setAttribute('aria-labelledby', 'dash-dlg-title');
        dlg.appendChild(pre);
        var copyBtn = el('button', {type: 'button', cls: 'dash-btn', on: {click: function () {
            var done = function () { status.textContent = 'Copied to the clipboard.'; };
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(done, function () { status.textContent = 'Copy blocked: select the text by hand.'; });
            } else { status.textContent = 'Copy blocked: select the text by hand.'; }
        }}}, [icon('copy'), 'Copy']);
        var foot = el('div', {cls: 'dash-dlg-foot'}, [status, el('span', {cls: 'dash-spacer'}), copyBtn,
            onClone ? el('button', {type: 'button', cls: 'dash-btn', on: {click: function () { dlg.close(); onClone(); }}},
                         [icon('copy'), 'Clone as editable']) : null,
            el('button', {type: 'button', cls: 'dash-btn dash-btn--primary', on: {click: function () { dlg.close(); }}}, ['Close'])]);
        dlg.appendChild(foot);
        if (typeof dlg.showModal === 'function') { dlg.showModal(); } else { dlg.setAttribute('open', ''); }
    }

    function cloneAndEdit(root, key) {
        var k = keyOf(key);
        if (!k) { return; }
        api('POST', '/api/v2/custom-dashboards/' + k + '/clone', {}).then(function (res) {
            var nk = res.ok && res.data ? keyOf(res.data.key) : null;
            if (!nk) {
                toast(root, errorText(res, 'The dashboard could not be cloned.'), 'err');
                return;
            }
            location.href = pageUrl('/dashboards/' + nk + '/edit');
        });
    }

    function showJson(root, key) {
        var k = keyOf(key);
        if (!k) { return; }
        api('GET', '/api/v2/custom-dashboards/' + k).then(function (res) {
            if (!res.ok || !res.data) {
                toast(root, errorText(res, 'The dashboard could not be read.'), 'err');
                return;
            }
            jsonDialog(root, res.data, function () { cloneAndEdit(root, k); });
        });
    }

    // ------------------------------------------------------------------ the list page

    function tile(root, d) {
        var k = keyOf(d.key);
        var h = hue(d.key);
        var card = el('a', {cls: 'dash-tile', href: pageUrl('/dashboards/' + k), 'data-key': k});
        card.style.setProperty('--dash-hue', String(h));
        var first = (String(d.name || '?').trim().charAt(0) || '?').toUpperCase();
        var meta = [d.updated_at ? 'Updated ' + stamp(d.updated_at) : null,
                    d.widgets + (d.widgets === 1 ? ' widget' : ' widgets')].filter(Boolean).join(' · ');
        var badges = el('span', {cls: 'dash-badges'}, [
            d.is_shared ? el('span', {cls: 'dash-badge dash-badge--shared', text: 'Shared'}) : null,
            !d.mine && d.owner ? el('span', {cls: 'dash-badge', text: 'by ' + d.owner.name}) : null
        ]);
        card.appendChild(el('span', {cls: 'dash-tile-bar', 'aria-hidden': 'true'}));
        card.appendChild(el('span', {cls: 'dash-tile-row'}, [
            el('span', {cls: 'dash-avatar', 'aria-hidden': 'true', text: first}),
            el('span', {cls: 'dash-tile-text'}, [el('span', {cls: 'dash-tile-name', text: d.name}),
                                                 el('span', {cls: 'dash-tile-meta', text: meta}), badges])
        ]));
        return card;
    }

    function systemCard(root, d) {
        var k = keyOf(d.key);
        return el('div', {cls: 'dash-syscard', 'data-key': k}, [
            el('div', {cls: 'dash-tile-row'}, [
                el('span', {cls: 'dash-sysicon', 'aria-hidden': 'true'}, [icon('layout')]),
                el('div', {cls: 'dash-tile-text'}, [
                    el('div', {}, [el('a', {cls: 'dash-tile-name dash-syslink', href: pageUrl('/dashboards/' + k), text: d.name}),
                                   el('span', {cls: 'dash-badge'}, [icon('lock', 'dash-i dash-i--xs'), 'System'])]),
                    el('span', {cls: 'dash-tile-meta', text: d.description})])
            ]),
            el('div', {cls: 'dash-syscard-foot'}, [
                el('button', {type: 'button', cls: 'dash-btn dash-btn--sm', 'data-act': 'clone', on: {click: function () { cloneAndEdit(root, k); }}},
                   [icon('copy'), 'Clone']),
                el('button', {type: 'button', cls: 'dash-btn dash-btn--sm', 'data-act': 'json', on: {click: function () { showJson(root, k); }}},
                   [icon('code'), 'View JSON'])
            ])
        ]);
    }

    function drawList(root, state) {
        var sys = root.querySelector('#dash-system');
        var mine = root.querySelector('#dash-mine');
        sys.textContent = '';
        mine.textContent = '';
        (state.system || []).forEach(function (d) { sys.appendChild(systemCard(root, d)); });
        var list = state.dashboards || [];
        if (!list.length) {
            mine.appendChild(el('div', {cls: 'dash-empty'}, [
                el('span', {cls: 'dash-empty-icon', 'aria-hidden': 'true'}, [icon('layout')]),
                el('p', {cls: 'dash-empty-title', text: 'No dashboards yet'}),
                el('p', {cls: 'dash-dim', text: 'Create one from scratch, or clone the Statistics dashboard above to get started.'}),
                el('a', {cls: 'dash-btn dash-btn--primary', href: pageUrl('/dashboards/new')}, [icon('plus'), 'New dashboard'])
            ]));
        } else {
            list.forEach(function (d) { mine.appendChild(tile(root, d)); });
        }
        root.setAttribute('data-dash-settled', '1');
    }

    function mountList(root, state) {
        var newBtn = root.querySelector('#dash-new');
        if (newBtn) { newBtn.setAttribute('href', pageUrl('/dashboards/new')); }
        if (state) {
            drawList(root, state);
            return;
        }
        api('GET', '/api/v2/custom-dashboards').then(function (res) {
            if (!res.ok || !res.data) {
                root.querySelector('#dash-mine').appendChild(el('div', {cls: 'dash-alert', role: 'alert',
                    text: errorText(res, 'The dashboards could not be loaded.')}));
                root.setAttribute('data-dash-settled', '1');
                return;
            }
            drawList(root, res.data);
        });
    }

    // ------------------------------------------------------------------ sections + widgets (view and editor preview)

    function drawSections(container, definition, opts) {
        opts = opts || {};
        container.textContent = '';
        var bodies = {};
        var any = (definition.sections || []).some(function (s) { return (s.widgets || []).length > 0; });
        if (!any && opts.emptyText) {
            container.appendChild(el('div', {cls: 'dash-empty'}, [el('p', {cls: 'dash-empty-title', text: opts.emptyText})]));
            return bodies;
        }
        (definition.sections || []).forEach(function (s, si) {
            var grid = el('div', {cls: 'dash-grid'});
            (s.widgets || []).forEach(function (w) {
                var body = el('div', {cls: 'dash-w-body', 'data-dw-state': 'loading'}, [el('div', {cls: 'dw-msg dw-loading', text: 'Loading…'})]);
                var card = el('article', {cls: 'dash-w dash-w--' + (w.width in {full: 1, half: 1, third: 1, quarter: 1} ? w.width : 'half'),
                                          'data-wid': w.id, 'aria-label': w.name}, [
                    el('header', {cls: 'dash-w-head'}, [el('h3', {cls: 'dash-w-title', text: w.name})]),
                    body
                ]);
                if (w.chart === 'number') { card.classList.add('dash-w--kpi'); }
                bodies[w.id] = body;
                grid.appendChild(card);
            });
            var head = (s.title || s.description) ? el('header', {cls: 'dash-section-head'}, [
                s.title ? el('h2', {cls: 'dash-section-title', text: s.title}) : null,
                s.description ? el('p', {cls: 'dash-section-desc', text: s.description}) : null]) : null;
            container.appendChild(el('section', {cls: 'dash-section', 'data-sid': s.id, 'aria-label': s.title || ('Section ' + (si + 1))},
                                     [head, (s.widgets || []).length ? grid : el('p', {cls: 'dash-dim dash-section-empty', text: 'No widgets in this section.'})]));
        });
        return bodies;
    }

    function fill(bodies, definition, data, opts) {
        var results = (data && data.widgets) || {};
        (definition.sections || []).forEach(function (s) {
            (s.widgets || []).forEach(function (w) {
                if (bodies[w.id]) {
                    window.IrisDashWidgets.render(bodies[w.id], w, results[w.id] || {ok: false, error: 'No result.'}, opts);
                }
            });
        });
    }

    // ------------------------------------------------------------------ the view page

    function pad(n) { return (n < 10 ? '0' : '') + n; }

    function localInput(iso) {
        /* A UTC ISO stamp -> the datetime-local input's value (the inputs are in UTC, labelled so). */
        var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(String(iso || ''));
        return m ? m[1] + '-' + m[2] + '-' + m[3] + 'T' + m[4] + ':' + m[5] : '';
    }

    function readMoment(input) {
        /* An input's value re-derived: YYYY-MM-DDTHH:MM rebuilt from its numbers, else ''. */
        var m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(String(input.value || ''));
        if (!m) { return ''; }
        var y = parseInt(m[1], 10), mo = parseInt(m[2], 10), d = parseInt(m[3], 10);
        var h = m[4] ? parseInt(m[4], 10) : 0, mi = m[5] ? parseInt(m[5], 10) : 0;
        if (mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59) { return ''; }
        return y + '-' + pad(mo) + '-' + pad(d) + 'T' + pad(h) + ':' + pad(mi);
    }

    function mountView(root, state, key) {
        var V = {key: keyOf(key || (state && state.dashboard && state.dashboard.key)), seq: 0, dash: null, params: null,
                 bodies: {}, vocab: null, options: {}};
        if (!V.key) { return; }

        function barLabels() {
            var out = {};
            ((V.dash.definition || {}).filter_bar || []).forEach(function (e) { out[e.key] = e.label; });
            return out;
        }

        function queryString(p) {
            var parts = [];
            if (p.start || p.end) {
                if (p.start) { parts.push('start=' + encodeURIComponent(p.start)); }
                if (p.end) { parts.push('end=' + encodeURIComponent(p.end)); }
            } else if (p.range) {
                parts.push('range=' + encodeURIComponent(p.range));
            }
            Object.keys(p.bar || {}).forEach(function (k) { parts.push('f_' + k + '=' + encodeURIComponent(p.bar[k])); });
            return parts.join('&');
        }

        function syncUrl() {
            var q = [cidParam(), queryString(V.params)].filter(Boolean).join('&');
            history.replaceState(null, '', location.href.split(/[?#]/)[0] + (q ? '?' + q : ''));
        }

        function rangeKeys() { return (V.vocab.ranges || []).map(function (r) { return r.key; }); }

        function pickRange(k) {
            var keys = rangeKeys();
            var i = keys.indexOf(k);
            return i === -1 ? null : keys[i];
        }

        function drawHeader() {
            var d = V.dash;
            var head = root.querySelector('#dash-view-head');
            head.textContent = '';
            var badges = [d.system ? el('span', {cls: 'dash-badge'}, [icon('lock', 'dash-i dash-i--xs'), 'System']) : null,
                          d.is_shared && !d.system ? el('span', {cls: 'dash-badge dash-badge--shared', text: 'Shared'}) : null,
                          !d.system && !d.mine && d.owner ? el('span', {cls: 'dash-badge', text: 'by ' + d.owner.name}) : null];
            var actions = el('div', {cls: 'dash-actions'}, [
                el('button', {type: 'button', cls: 'dash-btn', id: 'dash-refresh', on: {click: function () { load(); }}}, [icon('refresh'), 'Refresh']),
                el('button', {type: 'button', cls: 'dash-btn', id: 'dash-json', on: {click: function () {
                    jsonDialog(root, V.dash, V.dash.can_edit ? null : function () { cloneAndEdit(root, V.key); });
                }}}, [icon('code'), 'View JSON']),
                el('button', {type: 'button', cls: 'dash-btn', id: 'dash-clone', on: {click: function () { cloneAndEdit(root, V.key); }}},
                   [icon('copy'), 'Clone']),
                d.can_edit ? el('a', {cls: 'dash-btn dash-btn--primary', id: 'dash-edit', href: pageUrl('/dashboards/' + V.key + '/edit')},
                                [icon('pen'), 'Edit']) : null
            ]);
            head.appendChild(el('div', {cls: 'dash-head'}, [
                el('div', {cls: 'dash-head-text'}, [
                    el('a', {cls: 'dash-back', href: pageUrl('/dashboards')}, [icon('back', 'dash-i dash-i--xs'), 'All dashboards']),
                    el('div', {cls: 'dash-title-row'}, [el('h1', {cls: 'dash-title', text: d.name})].concat(badges)),
                    d.description ? el('p', {cls: 'dash-desc', text: d.description}) : null
                ]),
                actions
            ]));
        }

        function drawFilters() {
            var box = root.querySelector('#dash-filters');
            box.textContent = '';
            var start = el('input', {type: 'datetime-local', id: 'dash-start', cls: 'dash-input', 'aria-describedby': 'dash-utc'});
            var end = el('input', {type: 'datetime-local', id: 'dash-end', cls: 'dash-input', 'aria-describedby': 'dash-utc'});
            var bar = el('div', {cls: 'dash-bar'});
            ((V.dash.definition || {}).filter_bar || []).forEach(function (e) {
                var meta = (V.vocab.filter_bar || []).filter(function (f) { return f.key === e.key; })[0];
                if (!meta) { return; }
                var sel = el('select', {cls: 'dash-input', id: 'dash-f-' + e.key, 'data-bar': e.key});
                sel.appendChild(el('option', {value: '', text: 'All'}));
                if (meta.options === 'users') { sel.appendChild(el('option', {value: V.vocab.me, text: 'Me (whoever views)'})); }
                ((V.options || {})[meta.options] || []).forEach(function (o) {
                    sel.appendChild(el('option', {value: String(o.id), text: o.name}));
                });
                bar.appendChild(el('label', {cls: 'dash-field', 'for': 'dash-f-' + e.key}, [el('span', {cls: 'dash-label', text: e.label}), sel]));
            });
            var chips = el('div', {cls: 'dash-chips', role: 'group', 'aria-label': 'Preset ranges'});
            (V.vocab.ranges || []).forEach(function (r) {
                chips.appendChild(el('button', {type: 'button', cls: 'dash-chip', 'data-range': r.key, 'aria-pressed': 'false',
                                                text: r.label, on: {click: function () {
                    var k = pickRange(r.key);
                    if (!k) { return; }
                    V.params = {range: k, start: '', end: '', bar: V.params.bar};
                    load();
                }}}));
            });
            box.appendChild(el('div', {cls: 'dash-filter-row'}, [
                el('label', {cls: 'dash-field', 'for': 'dash-start'}, [el('span', {cls: 'dash-label', text: 'Start'}), start]),
                el('label', {cls: 'dash-field', 'for': 'dash-end'}, [el('span', {cls: 'dash-label', text: 'End'}), end]),
                bar,
                el('div', {cls: 'dash-filter-btns'}, [
                    el('button', {type: 'button', cls: 'dash-btn dash-btn--primary', id: 'dash-apply', on: {click: apply}}, ['Apply']),
                    el('button', {type: 'button', cls: 'dash-btn', id: 'dash-reset', on: {click: reset}}, ['Reset'])])
            ]));
            box.appendChild(el('div', {cls: 'dash-kicker', text: 'Preset ranges'}));
            box.appendChild(chips);
            box.appendChild(el('p', {cls: 'dash-dim dash-note', id: 'dash-utc', 'aria-live': 'polite'}));
        }

        function syncFilters() {
            var p = V.params;
            var data = V.data;
            var start = root.querySelector('#dash-start'), end = root.querySelector('#dash-end');
            start.value = localInput(p.start || (data && data.range && data.range.start));
            end.value = localInput(p.end || (data && data.range && data.range.end));
            Array.prototype.forEach.call(root.querySelectorAll('.dash-chip'), function (c) {
                var on = !p.start && !p.end && c.getAttribute('data-range') === p.range;
                c.setAttribute('aria-pressed', on ? 'true' : 'false');
                c.classList.toggle('dash-chip--on', on);
            });
            Array.prototype.forEach.call(root.querySelectorAll('select[data-bar]'), function (s) {
                var v = (p.bar || {})[s.getAttribute('data-bar')];
                s.value = v === undefined || v === null ? '' : String(v);
            });
            var label = (V.vocab.ranges || []).filter(function (r) { return r.key === p.range; })[0];
            var note = root.querySelector('#dash-utc');
            var what = (p.start || p.end) ? 'Custom range' : (label ? label.label : 'Custom range');
            note.textContent = 'Times are UTC. Showing: ' + what + (V.loadedAt ? ' · updated ' + V.loadedAt : '') +
                '. Each figure counts only what you can open.';
        }

        function readBar() {
            var bar = {};
            Array.prototype.forEach.call(root.querySelectorAll('select[data-bar]'), function (s) {
                var key = s.getAttribute('data-bar');
                var known = ((V.dash.definition || {}).filter_bar || []).map(function (e) { return e.key; });
                var k = known[known.indexOf(key)];
                if (!k || s.value === '') { return; }
                if (s.value === V.vocab.me) { bar[k] = V.vocab.me; return; }
                var n = parseInt(s.value, 10);
                if (!isNaN(n)) { bar[k] = n; }
            });
            return bar;
        }

        function apply() {
            var s = readMoment(root.querySelector('#dash-start'));
            var e = readMoment(root.querySelector('#dash-end'));
            V.params = {range: (s || e) ? 'custom' : V.params.range, start: s, end: e, bar: readBar()};
            load();
        }

        function reset() {
            V.params = {range: (V.dash.definition || {}).default_range || V.vocab.default_range, start: '', end: '', bar: {}};
            load();
        }

        function draw(data) {
            V.data = data;
            var now = new Date();
            V.loadedAt = pad(now.getUTCHours()) + ':' + pad(now.getUTCMinutes()) + ':' + pad(now.getUTCSeconds()) + ' UTC';
            if (data && data.range && !V.params.start && !V.params.end && data.range.key && data.range.key !== 'custom') {
                V.params.range = data.range.key;
            }
            fill(V.bodies, V.dash.definition, data, {palette: V.vocab.palette, barLabels: barLabels()});
            syncFilters();
            root.setAttribute('data-dash-settled', String(V.seq));
        }

        function load() {
            V.seq += 1;
            var mine = V.seq;
            root.removeAttribute('data-dash-settled');
            var err = root.querySelector('#dash-error');
            err.hidden = true;
            Object.keys(V.bodies).forEach(function (id) { V.bodies[id].setAttribute('data-dw-state', 'loading'); });
            syncUrl();
            api('GET', '/api/v2/custom-dashboards/' + V.key + '/data?' + queryString(V.params)).then(function (res) {
                if (mine !== V.seq) { return; }
                if (!res.ok || !res.data) {
                    err.textContent = errorText(res, 'The dashboard could not be computed.');
                    err.hidden = false;
                    syncFilters();
                    root.setAttribute('data-dash-settled', String(mine));
                    return;
                }
                draw(res.data);
            });
        }

        function start(st) {
            V.dash = st.dashboard;
            V.vocab = st.schema.vocab;
            V.options = st.schema.options || {};
            var p = st.params || {};
            V.params = {range: p.start || p.end ? (p.range || 'custom') : (p.range || V.dash.definition.default_range),
                        start: p.range === 'custom' ? localInput(p.start) : '', end: p.range === 'custom' ? localInput(p.end) : '',
                        bar: p.bar || {}};
            drawHeader();
            drawFilters();
            V.bodies = drawSections(root.querySelector('#dash-sections'), V.dash.definition,
                                    {emptyText: V.dash.can_edit ? 'This dashboard has no widgets yet: Edit adds some.' : 'This dashboard has no widgets yet.'});
            if (st.error) {
                var err = root.querySelector('#dash-error');
                err.textContent = st.error;
                err.hidden = false;
            }
            if (st.data) {
                V.seq = 1;
                draw(st.data);
            } else {
                load();
            }
        }

        if (state) {
            start(state);
            return;
        }
        Promise.all([api('GET', '/api/v2/custom-dashboards/' + V.key),
                     api('GET', '/api/v2/custom-dashboards/schema')]).then(function (rs) {
            if (!rs[0].ok || !rs[1].ok) {
                var err = root.querySelector('#dash-error');
                err.textContent = errorText(rs[0].ok ? rs[1] : rs[0], 'The dashboard could not be loaded.');
                err.hidden = false;
                root.setAttribute('data-dash-settled', '0');
                return;
            }
            var params = {};
            location.search.replace(/^\?/, '').split('&').forEach(function (kv) {
                var i = kv.indexOf('=');
                if (i > 0) { params[decodeURIComponent(kv.slice(0, i))] = decodeURIComponent(kv.slice(i + 1)); }
            });
            var bar = {};
            Object.keys(params).forEach(function (k) {
                if (k.indexOf('f_') === 0) {
                    var n = parseInt(params[k], 10);
                    bar[k.slice(2)] = params[k] === rs[1].data.vocab.me ? rs[1].data.vocab.me : (isNaN(n) ? undefined : n);
                }
            });
            start({dashboard: rs[0].data, schema: rs[1].data, params: {range: params.range || null, bar: bar}, data: null});
        });
    }

    window.IrisDashboards = {mountList: mountList, mountView: mountView, drawSections: drawSections, fill: fill,
                             api: api, el: el, icon: icon, keyOf: keyOf, pageUrl: pageUrl, errorText: errorText,
                             stamp: stamp, jsonDialog: jsonDialog, toast: toast};
})();

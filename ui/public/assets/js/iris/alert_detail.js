/* IrisAlertDetail - the Alerts page's detail pane (iris-ng, 2026-11-09).
 *
 *   IrisAlertDetail.render(pane, alert, ctx)
 *     alert: GET /api/v2/alert-queue/alerts/<id>
 *     ctx:   {options, me, permissions, select(id), back(), tab, onTab(name), stamp(iso), when(iso)}
 *
 * Every action goes through the functions alerts.js keeps (updateAlert, mergeAlertModal, editAlert, ...), which call back
 * into the queue when they are done. Text is written with DOM calls; the description and the note are the server's
 * sanitised HTML (render_markdown_safe).
 */
(function () {
    'use strict';

    var SEV = {critical: '#f5365c', high: '#fb6340', medium: '#f6c344', low: '#48abf7', informational: '#a0a0b0', unspecified: '#7a7a86'};
    var HTTP = /^https?:\/\//i;

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

    function sevColor(name) { return SEV[String(name || '').toLowerCase()] || SEV.unspecified; }

    // Lucide icons (ISC).
    var ICONS = {
        pen: [['path', {d: 'M12 20h9'}], ['path', {d: 'M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z'}]],
        link: [['path', {d: 'M9 17H7A5 5 0 0 1 7 7h2'}], ['path', {d: 'M15 7h2a5 5 0 1 1 0 10h-2'}], ['line', {x1: '8', x2: '16', y1: '12', y2: '12'}]],
        more: [['circle', {cx: '12', cy: '12', r: '1'}], ['circle', {cx: '19', cy: '12', r: '1'}], ['circle', {cx: '5', cy: '12', r: '1'}]]
    };

    function svg(name) {
        var ns = 'http://www.w3.org/2000/svg';
        var s = document.createElementNS(ns, 'svg');
        s.setAttribute('viewBox', '0 0 24 24');
        s.setAttribute('fill', 'none');
        s.setAttribute('stroke', 'currentColor');
        s.setAttribute('stroke-width', '2');
        s.setAttribute('stroke-linecap', 'round');
        s.setAttribute('stroke-linejoin', 'round');
        s.setAttribute('aria-hidden', 'true');
        s.setAttribute('class', 'ad-i');
        ICONS[name].forEach(function (p) {
            var n = document.createElementNS(ns, p[0]);
            Object.keys(p[1]).forEach(function (k) { n.setAttribute(k, p[1][k]); });
            s.appendChild(n);
        });
        return s;
    }

    function num(v) { var n = parseInt(v, 10); return isNaN(n) ? 0 : n; }

    function menuButton(label, cls, items, id, aria) {
        /* A small dropdown of its own: click to open, click elsewhere or Escape to close. */
        var pop = el('div', {cls: 'ad-menu-pop', hidden: true});
        var btn = el('button', {type: 'button', cls: 'ad-btn ' + (cls || ''), id: id || null, 'aria-haspopup': 'true', 'aria-expanded': 'false', 'aria-label': aria || null}, [label]);
        var wrap = el('div', {cls: 'ad-menu'}, [btn, pop]);
        function close() { pop.hidden = true; btn.setAttribute('aria-expanded', 'false'); document.removeEventListener('click', outside, true); document.removeEventListener('keydown', esc, true); }
        function outside(e) { if (!wrap.contains(e.target)) { close(); } }
        function esc(e) { if (e.key === 'Escape') { e.stopPropagation(); close(); btn.focus(); } }
        function fill() {
            pop.textContent = '';
            (typeof items === 'function' ? items() : items).forEach(function (it) {
                if (!it) { return; }
                if (it.header) { pop.appendChild(el('p', {cls: 'ad-menu-head', text: it.header})); return; }
                pop.appendChild(el('button', {type: 'button', cls: 'ad-menu-item' + (it.danger ? ' ad-menu-item--danger' : ''), 'data-act': it.act || null, text: it.label,
                                              on: {click: function () { close(); it.run(); }}}));
            });
        }
        btn.addEventListener('click', function () {
            if (!pop.hidden) { close(); return; }
            fill();
            pop.hidden = false;
            btn.setAttribute('aria-expanded', 'true');
            document.addEventListener('click', outside, true);
            document.addEventListener('keydown', esc, true);
        });
        return wrap;
    }

    function section(title, body, help) { return el('section', {cls: 'ad-section'}, [el('h3', {cls: 'ad-section-title'}, [title, help || null]), body]); }

    function helpIf(node) { return node || null; }

    function empty(text) { return el('p', {cls: 'ad-empty', text: text}); }

    function typeName(v, key) { return v && typeof v === 'object' ? v[key] : (v || null); }

    function tagList(text) { return String(text || '').split(',').map(function (t) { return t.trim(); }).filter(Boolean); }

    function chipsOf(list, cls) {
        return list.length ? el('span', {cls: 'ad-tags'}, list.map(function (t) { return el('span', {cls: cls || 'ad-tag', text: t}); })) : null;
    }

    function plain(v) { return v !== null && typeof v === 'object' ? JSON.stringify(v) : String(v === null || v === undefined ? '' : v); }

    function showEnrichmentOf(data) {
        if (window.showEnrichment && window.jQuery) {
            window.showEnrichment(data);
            window.jQuery('#enrichmentModal').modal('show');
        }
    }

    function render(pane, alert, ctx) {
        var id = num(alert.alert_id);
        var perm = ctx.permissions || {};
        var tab = ctx.tab || 'overview';
        var flowCount = 0, flows = null;

        function act(fn) { return function () { var f = window[fn]; if (typeof f === 'function') { f.apply(null, [].slice.call(arguments)); } }; }
        var update = function (data) { if (typeof window.updateAlert === 'function') { window.updateAlert(id, data, true); } };

        function statusItems() {
            return (ctx.options.statuses || []).map(function (s) {
                return {label: s.name, act: 'status-' + num(s.id), run: function () { update({alert_status_id: num(s.id)}); }};
            });
        }

        function assignItems() {
            return [
                {label: 'Assign to me', act: 'assign-me', run: function () { update({alert_owner_id: num(ctx.me.id)}); }},
                {label: 'Assign to…', act: 'assign-other', run: function () { act('changeAlertOwner')(id); }},
                alert.owner ? {label: 'Unassign', act: 'unassign', run: function () { update({alert_owner_id: -1}); }} : null
            ];
        }

        function moreItems() {
            var out = [];
            if (perm.write) {
                out.push({label: 'Merge into a case…', act: 'merge', run: function () { act('mergeAlertModal')(id, true); }});
                out.push({label: 'Close…', act: 'close', run: function () { act('editAlert')(id, true); }});
            }
            out.push({label: 'Copy Markdown link', act: 'copy-md', run: function () { act('copyMDAlertLink')(id); }});
            (ctx.moduleOptions || []).forEach(function (o) {
                if (perm.write) {
                    out.push({label: 'Run: ' + o.manual_hook_ui_name, act: 'module', run: function () {
                        act('init_module_processing_alert')(id, o.hook_name, o.manual_hook_ui_name, o.module_name);
                    }});
                }
            });
            if (perm.delete) { out.push({label: 'Delete alert', act: 'delete', danger: true, run: function () { act('delete_alert')(id); }}); }
            return out;
        }

        var severity = (alert.severity || {}).severity_name || 'Unspecified';
        var ownerName = alert.owner ? (alert.owner.user_name || alert.owner.user_login) : null;

        var actions = el('div', {cls: 'ad-actions'}, [
            perm.write ? el('button', {type: 'button', cls: 'ad-btn ad-btn--primary', id: 'ad-escalate', text: 'Escalate to case', on: {click: function () { act('mergeAlertModal')(id); }}}) : null,
            perm.write ? menuButton((alert.status || {}).status_name || 'Status', 'ad-btn--status', statusItems, 'ad-status', 'Set the alert status') : null,
            perm.write ? menuButton('Assign', '', assignItems, 'ad-assign') : null,
            perm.write ? el('button', {type: 'button', cls: 'ad-btn ad-btn--icon', id: 'ad-edit', title: 'Edit alert', 'aria-label': 'Edit alert', on: {click: function () { act('editAlert')(id, false); }}}, [svg('pen')]) : null,
            el('button', {type: 'button', cls: 'ad-btn ad-btn--icon', id: 'ad-share', title: 'Copy a link to this alert', 'aria-label': 'Copy a link to this alert', on: {click: function () { act('copyAlertLink')(id); }}}, [svg('link')]),
            el('a', {href: '#', cls: 'iris-follow-star ad-star', 'data-object-type': 'alert', 'data-object-id': String(id), title: 'Follow', 'aria-label': 'Follow this alert', text: '☆'}),
            menuButton(svg('more'), 'ad-btn--icon', moreItems, 'ad-more', 'More actions')
        ]);

        var head = el('header', {cls: 'ad-head'}, [
            el('button', {type: 'button', cls: 'ad-back', id: 'ad-back', text: '‹ Back to queue', on: {click: function () { ctx.back(); }}}),
            el('div', {cls: 'ad-head-row'}, [
                el('span', {cls: 'ad-sev', style: null}, [severity]),
                el('span', {cls: 'ad-ref', text: '#A-' + id}),
                alert.customer ? el('span', {cls: 'ad-meta', text: alert.customer.customer_name}) : null,
                alert.alert_source ? el('span', {cls: 'ad-meta', text: alert.alert_source}) : null,
                el('span', {cls: 'ad-spacer'}), actions
            ]),
            el('h2', {cls: 'ad-title', id: 'ad-title', text: alert.alert_title}),
            el('div', {cls: 'ad-chips'}, [
                alert.cluster ? el('a', {cls: 'ad-chip-cluster', href: '/alert-clusters/' + num(alert.cluster.id) + (ctx.cid ? '?cid=' + ctx.cid : ''), title: 'Open the cluster'}, [
                    el('span', {cls: 'ad-badge', text: 'CLUSTER'}), alert.cluster.title + ' · ' + num(alert.cluster.count) + ' alerts']) : null,
                alert.classification ? el('span', {cls: 'ad-tag ad-tag--mono', text: alert.classification.name_expanded || alert.classification.name}) : null,
                chipsOf(alert.tags || []),
                (alert.cases || []).length ? el('span', {cls: 'ad-tags'}, alert.cases.map(function (c) {
                    var caseId = num(typeof c === 'object' ? c.case_id : c);
                    return el('span', {cls: 'ad-case'}, [
                        el('a', {href: '/case?cid=' + caseId, text: 'Case #' + caseId}),
                        perm.write ? el('button', {type: 'button', cls: 'ad-case-x', 'aria-label': 'Unlink from case #' + caseId, title: 'Unlink from this case', text: '×',
                                                   on: {click: function () { act('unlinkAlertFromCase')(id, caseId); }}}) : null]);
                })) : null
            ])
        ]);
        head.querySelector('.ad-sev').style.setProperty('--ad-sev', sevColor(severity));

        var TABS = [['overview', 'Overview'], ['flow', 'Investigation'], ['assets', 'Assets', (alert.assets || []).length],
                    ['cluster', 'Cluster', alert.cluster ? num(alert.cluster.count) : null], ['iocs', 'IOCs', (alert.iocs || []).length],
                    ['raw', 'Raw event'], ['timeline', 'Timeline'], ['notes', 'Notes'],
                    ['comments', 'Comments', (alert.comments || []).length], ['graph', 'Graph']];
        var tabsEl = el('div', {cls: 'ad-tabs', role: 'tablist', 'aria-label': 'Alert detail sections'});
        var panel = el('div', {cls: 'ad-panel', id: 'ad-panel', role: 'tabpanel', tabindex: '0'});

        function drawTabs() {
            tabsEl.textContent = '';
            TABS.forEach(function (t) {
                if (t[0] === 'flow' && !flowCount) { return; }
                tabsEl.appendChild(el('button', {type: 'button', role: 'tab', cls: 'ad-tab' + (tab === t[0] ? ' ad-tab--on' : ''), 'data-tab': t[0], id: 'ad-tab-' + t[0],
                                                 'aria-selected': tab === t[0] ? 'true' : 'false', 'aria-controls': 'ad-panel', tabindex: tab === t[0] ? '0' : '-1',
                                                 on: {click: function () { open(t[0]); }}}, [
                    t[1], t[2] !== undefined && t[2] !== null ? el('span', {cls: 'ad-tab-count', text: String(t[2])}) : null]));
            });
        }

        function open(name) {
            tab = name;
            if (ctx.onTab) { ctx.onTab(name); }
            drawTabs();
            drawPanel();
        }

        tabsEl.addEventListener('keydown', function (e) {
            if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') { return; }
            var names = Array.prototype.map.call(tabsEl.querySelectorAll('.ad-tab'), function (b) { return b.getAttribute('data-tab'); });
            var i = names.indexOf(tab);
            e.preventDefault();
            open(names[(i + (e.key === 'ArrowRight' ? 1 : names.length - 1)) % names.length]);
            var cur = tabsEl.querySelector('.ad-tab--on');
            if (cur) { cur.focus(); }
        });

        function overview() {
            var box = el('div', {});
            var any = false;
            if (alert.description_html) {
                any = true;
                var d = el('div', {cls: 'ad-prose', id: 'ad-description'});
                d.innerHTML = alert.description_html;
                box.appendChild(section('Description', d));
            }
            if (alert.alert_source_link) {
                any = true;
                box.appendChild(section('Source link', HTTP.test(alert.alert_source_link)
                    ? el('a', {href: alert.alert_source_link, target: '_blank', rel: 'noreferrer', cls: 'ad-link', text: alert.alert_source_link})
                    : el('span', {text: alert.alert_source_link})));
            }
            if (alert.alert_source_ref) {
                any = true;
                box.appendChild(section('Source reference', el('span', {cls: 'ad-mono', text: alert.alert_source_ref})));
            }
            var ctxObj = alert.alert_context;
            if (ctxObj && typeof ctxObj === 'object' && Object.keys(ctxObj).length) {
                any = true;
                box.appendChild(section('Context', el('div', {cls: 'ad-context'}, Object.keys(ctxObj).reduce(function (acc, k) {
                    acc.push(el('div', {cls: 'ad-context-key', text: k}), el('div', {cls: 'ad-context-val', text: plain(ctxObj[k])}));
                    return acc;
                }, [])), helpIf(window.IrisHelp && window.IrisHelp.el('alert.context', {cls: 'ml-1'}))));
            }
            if (!any) { box.appendChild(empty('No overview data for this alert.')); }
            return box;
        }

        function assets() {
            var list = alert.assets || [];
            if (!list.length) { return empty('No assets linked to this alert.'); }
            return el('div', {cls: 'ad-rows'}, list.map(function (a) {
                return el('div', {cls: 'ad-row'}, [
                    el('div', {cls: 'ad-row-main'}, [
                        el('span', {cls: 'ad-row-title', text: a.asset_name}),
                        el('span', {cls: 'ad-row-meta', text: [typeName(a.asset_type, 'asset_name'), a.asset_domain, a.asset_ip].filter(Boolean).join(' · ')}),
                        a.asset_description ? el('p', {cls: 'ad-row-desc', text: a.asset_description}) : null,
                        chipsOf(tagList(a.asset_tags))]),
                    a.asset_enrichment ? el('button', {type: 'button', cls: 'ad-btn ad-btn--sm', text: 'Enrichment', on: {click: function () { showEnrichmentOf(a.asset_enrichment); }}}) : null
                ]);
            }));
        }

        function iocs() {
            var list = alert.iocs || [];
            if (!list.length) { return empty('No observables extracted from this alert.'); }
            return el('div', {cls: 'ad-rows'}, list.map(function (i) {
                return el('div', {cls: 'ad-row'}, [
                    el('div', {cls: 'ad-row-main'}, [
                        el('span', {cls: 'ad-row-title ad-mono', text: i.ioc_value}),
                        el('span', {cls: 'ad-row-meta', text: [typeName(i.ioc_type, 'type_name'), typeName(i.ioc_tlp, 'tlp_name')].filter(Boolean).join(' · ')}),
                        i.ioc_description ? el('p', {cls: 'ad-row-desc', text: i.ioc_description}) : null,
                        chipsOf(tagList(i.ioc_tags))]),
                    i.ioc_enrichment ? el('button', {type: 'button', cls: 'ad-btn ad-btn--sm', text: 'Enrichment', on: {click: function () { showEnrichmentOf(i.ioc_enrichment); }}}) : null,
                    perm.write && (ctx.moduleIoc || []).length ? menuButton('Modules', 'ad-btn--sm', function () {
                        return ctx.moduleIoc.map(function (o) {
                            return {label: o.manual_hook_ui_name, run: function () {
                                if (typeof window.init_module_processing === 'function') {
                                    window.init_module_processing([num(i.ioc_id)], o.hook_name, o.manual_hook_ui_name, o.module_name, 'ioc');
                                }
                            }};
                        });
                    }) : null
                ]);
            }));
        }

        function cluster() {
            var c = alert.cluster;
            if (!c) { return empty('This alert is not part of a cluster.'); }
            var values = c.correlation_values && typeof c.correlation_values === 'object' ? Object.keys(c.correlation_values) : [];
            return el('div', {}, [
                section('Why this fired together', el('div', {}, [
                    el('p', {cls: 'ad-prose', text: c.rule ? 'Matched by the rule ' + c.rule + '.' : 'Grouped automatically.'}),
                    values.length ? el('div', {cls: 'ad-context'}, values.reduce(function (acc, k) {
                        acc.push(el('div', {cls: 'ad-context-key', text: k}), el('div', {cls: 'ad-context-val', text: plain(c.correlation_values[k])}));
                        return acc;
                    }, [])) : null])),
                section(num(c.count) > (c.members || []).length ? 'Newest ' + (c.members || []).length + ' of ' + num(c.count) + ' alerts' : 'Alerts',
                        el('div', {cls: 'ad-rows'}, (c.members || []).map(function (m) {
                    return el('button', {type: 'button', cls: 'ad-row ad-row--link', 'data-member': String(num(m.alert_id)), on: {click: function () { ctx.select(num(m.alert_id)); }}}, [
                        el('span', {cls: 'ad-row-main'}, [
                            el('span', {cls: 'ad-row-title', text: m.title}),
                            el('span', {cls: 'ad-row-meta', text: [(m.severity || {}).name, (m.status || {}).name, ctx.stamp(m.event_time)].filter(Boolean).join(' · ')})])]);
                })))
            ]);
        }

        function raw() {
            var data = alert.alert_source_content;
            if (data === null || data === undefined || (typeof data === 'object' && !Object.keys(data).length)) { return empty('No raw event payload was stored with this alert.'); }
            return section('Raw event', el('pre', {cls: 'ad-raw', tabindex: '0', text: typeof data === 'string' ? data : JSON.stringify(data, null, 2)}),
                           helpIf(window.IrisHelp && window.IrisHelp.el('alert.raw_alert', {cls: 'ml-1'})));
        }

        function timeline() {
            var list = alert.history || [];
            if (!list.length) { return empty('No recorded activity.'); }
            return el('ol', {cls: 'ad-timeline'}, list.map(function (h) {
                return el('li', {}, [el('span', {cls: 'ad-when', text: ctx.stamp(h.when)}), el('span', {cls: 'ad-who', text: h.user || 'IRIS'}), el('span', {text: h.action})]);
            }));
        }

        function notes() {
            if (!alert.note_html) { return empty('No notes on this alert yet.'); }
            var n = el('div', {cls: 'ad-prose', id: 'ad-note'});
            n.innerHTML = alert.note_html;
            return n;
        }

        function comments() {
            var box = el('div', {});
            var list = el('div', {cls: 'ad-rows', id: 'ad-comments'}, [empty('Loading comments…')]);
            box.appendChild(el('div', {cls: 'ad-bar'}, [el('button', {type: 'button', cls: 'ad-btn ad-btn--sm', id: 'ad-comment', text: 'Add or manage comments', on: {click: function () {
                if (typeof window.comment_element === 'function') { window.comment_element(id, 'alerts', true); }
            }}})]));
            box.appendChild(list);
            fetch('/alerts/' + id + '/comments/list' + (ctx.cid ? '?cid=' + ctx.cid : ''), {credentials: 'same-origin'})
                .then(function (r) { return r.json(); })
                .then(function (j) {
                    list.textContent = '';
                    var rows = (j && j.data) || [];
                    if (!rows.length) { list.appendChild(empty('No comments on this alert yet.')); return; }
                    rows.forEach(function (c) {
                        list.appendChild(el('div', {cls: 'ad-row ad-row--stack'}, [
                            el('span', {cls: 'ad-row-meta', text: [(c.user || {}).user_name || c.user_name, ctx.stamp(c.comment_date)].filter(Boolean).join(' · ')}),
                            el('span', {cls: 'ad-row-desc', text: c.comment_text})]));
                    });
                }).catch(function () { list.textContent = ''; list.appendChild(empty('The comments could not be loaded.')); });
            return box;
        }

        function flow() {
            var box = el('div', {cls: 'ad-flow', id: 'ad-flow'});
            if (window.IrisFlowChecklist && flows) { window.IrisFlowChecklist.render(box, flows); }
            return box;
        }

        function graph() {
            var pill = function (name, label, on) {
                var cb = el('input', {type: 'checkbox', name: name + '_' + id, cls: 'filter-graph-alert-checkbox', on: {change: function () { act('refreshAlertRelationships')(id); }}});
                cb.checked = on;
                return el('label', {cls: 'ad-pill'}, [cb, ' ' + label]);
            };
            var box = el('div', {cls: 'ad-graph'}, [
                el('p', {cls: 'ad-note'}, ['Relationships are worked out from the alert\'s IOCs and assets. They are an indication only.',
                                           helpIf(window.IrisHelp && window.IrisHelp.el('alert.relationships', {cls: 'ml-1'}))]),
                el('div', {cls: 'ad-bar'}, [pill('open_alerts', 'Show open alerts', true), pill('closed_alerts', 'Show closed alerts', false),
                                            pill('open_cases', 'Show open cases', false), pill('closed_cases', 'Show closed cases', false)]),
                el('div', {cls: 'ad-bar'}, [
                    el('label', {cls: 'ad-field'}, ['Nodes limit ', el('input', {type: 'number', id: 'nbResultsGraphFilter-' + id, value: '100', on: {change: function () { act('refreshAlertRelationships')(id); }}})]),
                    el('label', {cls: 'ad-field'}, ['Lookback (days) ', el('input', {type: 'number', id: 'daysBackGraphFilter-' + id, value: '180', on: {change: function () { act('refreshAlertRelationships')(id); }}})])]),
                el('div', {id: 'similarAlertsNotify-' + id, cls: 'ad-note'}),
                el('div', {id: 'similarAlerts-' + id, cls: 'similar-alert-graph ad-graph-canvas'})
            ]);
            setTimeout(function () { act('fetchSimilarAlerts')(id, true, true, false, false, false); }, 30);
            return box;
        }

        function drawPanel() {
            panel.textContent = '';
            panel.setAttribute('aria-labelledby', 'ad-tab-' + tab);
            var fn = {overview: overview, flow: flow, assets: assets, cluster: cluster, iocs: iocs, raw: raw, timeline: timeline, notes: notes, comments: comments, graph: graph}[tab] || overview;
            panel.appendChild(fn());
        }

        function rail() {
            var row = function (label, value, cls) { return el('div', {cls: 'ad-rail-row'}, [el('span', {cls: 'ad-rail-label', text: label}), el('span', {cls: 'ad-rail-val ' + (cls || ''), text: value})]); };
            var c = alert.cluster;
            var history = (alert.history || []).slice(0, 5);
            return el('aside', {cls: 'ad-rail'}, [
                el('div', {cls: 'ad-rail-block'}, [
                    el('h3', {cls: 'ad-section-title', text: 'Triage'}),
                    row('Status', (alert.status || {}).status_name || '—'),
                    row('Owner', ownerName || 'Unassigned'),
                    row('Severity', severity),
                    row('Age', ctx.when(alert.created)),
                    row('Resolution', (alert.resolution_status || {}).resolution_status_name || 'Unset')]),
                el('div', {cls: 'ad-rail-block'}, [
                    el('h3', {cls: 'ad-section-title', text: 'Seen before'}),
                    c ? el('p', {cls: 'ad-rail-text', text: 'Clustered with ' + (num(c.count) - 1) + ' other alert' + (num(c.count) === 2 ? '' : 's') + (c.rule ? ' by ' + c.rule : '') + '.'}) : el('p', {cls: 'ad-rail-text', text: 'Not part of a cluster.'}),
                    c ? el('button', {type: 'button', cls: 'ad-link-btn', id: 'ad-view-cluster', text: 'View cluster →', on: {click: function () { open('cluster'); }}}) : null,
                    el('button', {type: 'button', cls: 'ad-link-btn', id: 'ad-view-graph', text: 'View the graph →', on: {click: function () { open('graph'); }}})]),
                el('div', {cls: 'ad-rail-block'}, [
                    el('h3', {cls: 'ad-section-title', text: 'Activity'})].concat(history.length ? history.map(function (h) {
                        return el('div', {cls: 'ad-activity'}, [el('span', {text: h.action}), el('span', {cls: 'ad-when', text: ctx.stamp(h.when) + (h.user ? ' · ' + h.user : '')})]);
                    }) : [el('p', {cls: 'ad-rail-text', text: 'Nothing recorded yet.'})]))
            ]);
        }

        pane.textContent = '';
        pane.appendChild(head);
        pane.appendChild(tabsEl);
        pane.appendChild(el('div', {cls: 'ad-body'}, [el('div', {cls: 'ad-main'}, [panel]), rail()]));
        drawTabs();
        drawPanel();

        fetch('/api/v2/alerts/' + id + '/flows', {credentials: 'same-origin'}).then(function (r) { return r.status === 200 ? r.json() : []; }).then(function (atts) {
            if (atts && atts.length) {
                flows = atts;
                flowCount = atts.length;
                drawTabs();
                if (tab === 'flow') { drawPanel(); }
            } else if (tab === 'flow') {
                open('overview');
            }
        }).catch(function () { /* no checklist */ });

        var star = pane.querySelector('.iris-follow-star');
        if (star && window.irisFollowSetStar) {
            fetch('/api/v2/follow', {credentials: 'same-origin'}).then(function (r) { return r.ok ? r.json() : []; }).then(function (list) {
                var on = (list || []).some(function (f) { return f.object_type === 'alert' && num(f.object_id) === id; });
                window.irisFollowSetStar(star, on);
            }).catch(function () { /* the star stays hollow */ });
        }
        pane.setAttribute('data-ad-settled', String(id));
    }

    window.IrisAlertDetail = {render: render, sevColor: sevColor};
})();

/* iris-ng v2: Alert Cluster DETAIL page, v3 parity (2026-09-01).
 * Header (status / severity / owner), 7 tabs: Summary (autosave doc + the
 * iris-ng AI-triage panel + investigation flows), Alerts (member table with
 * remove), Assets, IOCs, Correlation (D3 force graph), Timeline, Activity
 * (analyst comments). "Escalate or merge…" drives the real batch machinery
 * via POST /api/v2/alert-clusters/<id>/escalate.
 *
 * Import-free (ui/public/ → verbatim copy). /api/v2 envelope: THE RESPONSE
 * IS THE DATA; legacy /manage/* endpoints wrap {status,data}. POST bodies
 * carry csrf_token (header is never read). Timestamps are STORED naive-UTC:
 * string-formatted, never new Date().
 *
 * Absent data vs absent knowledge: context/comments start as null ("have
 * not looked") with separate in-flight flags — [] is a claim of emptiness
 * and is only ever set by a completed fetch.
 */

var IRIS_ACD = {
    id: null,
    detail: null,
    context: null,          // null = not looked; {} shapes only after a 200
    contextFetching: false,
    contextFailed: false,
    comments: null,
    commentsFetching: false,
    commentsFailed: false,
    saveTimer: null,
    dirty: false,
    graph: null,            // {svg, zoom, sim, nodes}
    searchIdx: -1,
    severities: null,       // catalog rows; null = not loaded yet
    users: null
};

/* v3 status vocabulary. 'closed' = legacy/window-expiry; shown when current
 * but not offered as a pick. */
var IRIS_ACD_STATUSES = ['open', 'investigating', 'dismissed', 'escalated'];
var IRIS_ACD_STATUS_CLASS = {
    open: 'iris-ac-st-open',
    investigating: 'iris-ac-st-investigating',
    dismissed: 'iris-ac-st-dismissed',
    escalated: 'iris-ac-st-escalated',
    closed: 'iris-ac-st-closed'
};

/* Alias used by the AI-triage block, moved VERBATIM from the old list-page
 * panel (it addresses IRIS_AC._current / IRIS_AC._pollTimer). */
var IRIS_AC = { _current: null, _pollTimer: null };

function iris_ac_csrf() { return $('#csrf_token').val(); }

function iris_ac_esc(s) {
    return $('<div>').text(s == null ? '' : String(s)).html();
}

function iris_ac_fetch(path, method, body) {
    var opts = {
        method: method || 'GET',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin'
    };
    if (body !== undefined) {
        body = Object.assign({}, body, { csrf_token: iris_ac_csrf() });
        opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (r) {
        if (r.status === 204) { return { __status: 204 }; }
        return r.json().then(function (j) {
            j = (j && typeof j === 'object') ? j : { value: j };
            if (Array.isArray(j)) { return { __status: r.status, rows: j }; }
            j.__status = r.status;
            return j;
        }).catch(function () { return { __status: r.status }; });
    });
}

var IRIS_ACD_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function iris_ac_ts(iso) {
    if (!iso) { return ''; }
    var m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    if (!m) { return String(iso); }
    return IRIS_ACD_MONTHS[parseInt(m[2], 10) - 1] + ' ' + parseInt(m[3], 10)
        + ', ' + m[1] + ', ' + m[4] + ':' + m[5] + ' UTC';
}

function iris_acd_sev_class(name) {
    var n = (name || '').toLowerCase();
    if (n === 'critical') { return 'iris-ac-sev-critical'; }
    if (n === 'high') { return 'iris-ac-sev-high'; }
    if (n === 'medium') { return 'iris-ac-sev-medium'; }
    if (n === 'low') { return 'iris-ac-sev-low'; }
    return 'iris-ac-sev-none';
}

function iris_acd_sev_chip(name) {
    return '<span class="iris-ac-chip iris-ac-sev ' + iris_acd_sev_class(name)
        + '">' + iris_ac_esc(name || '—') + '</span>';
}

/* ------------------------------------------------------------- header */

function iris_acd_render_header() {
    var d = IRIS_ACD.detail;
    $('#iris-acd-title').text('#' + d.id + ' — ' + d.title);
    $('#iris-acd-meta').html(
        '<span>&#128337; Opened ' + iris_ac_esc(iris_ac_ts(d.created_at)) + '</span>'
        + '<span>&#127970; ' + iris_ac_esc(d.customer_name || d.customer_id) + '</span>'
        + '<span>&#128278; Rule: ' + iris_ac_esc(d.rule_name || '(rule deleted)') + '</span>');
    iris_acd_render_status_chip();
    iris_acd_render_severity_chip();
    iris_acd_render_owner_text();
    $('#iris-acd-count-alerts').text((d.alerts || []).length);

    if (d.escalated_case_id) {
        $('#iris-acd-escalate-btn')
            .removeClass('btn-primary').addClass('btn-outline-secondary')
            .html('Escalated to case #' + d.escalated_case_id + ' &nearr;');
    }
}

function iris_acd_cap(s) {
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function iris_acd_render_status_chip() {
    var st = IRIS_ACD.detail.status;
    $('#iris-acd-status-chip').html(
        '<span class="iris-ac-chip ' + (IRIS_ACD_STATUS_CLASS[st] || 'iris-ac-st-closed')
        + '">' + iris_ac_esc(iris_acd_cap(st)) + '</span>');
}

function iris_acd_render_severity_chip() {
    var d = IRIS_ACD.detail;
    $('#iris-acd-severity-chip').html(iris_acd_sev_chip(d.severity))
        .attr('title', d.severity_source === 'override'
            ? 'Pinned by an analyst — pick Derived to unpin'
            : 'Derived from member alerts; picking a value pins it');
}

function iris_acd_render_owner_text() {
    var d = IRIS_ACD.detail;
    var el = $('#iris-acd-owner-text');
    if (d.owner_name) {
        el.text(d.owner_name).addClass('assigned');
    } else {
        el.text('Unassigned').removeClass('assigned');
    }
}

/* Generic v3-style searchable dropdown. cfg: {options(): [{value,label,sub?,
 * checked?}], onPick(value)}. Options are re-read on every open so checks
 * always reflect the current detail. All text goes through textContent. */
function iris_acd_dd_setup(rootId, cfg) {
    var root = document.getElementById(rootId);
    var trigger = root.querySelector('.iris-acd-dd-trigger');
    var panel = root.querySelector('.iris-acd-dd-panel');
    var search = root.querySelector('.iris-acd-dd-search');
    var box = root.querySelector('.iris-acd-dd-opts');

    function render() {
        var q = (search.value || '').toLowerCase();
        box.innerHTML = '';
        cfg.options().forEach(function (o) {
            var hay = (o.label + ' ' + (o.sub || '')).toLowerCase();
            if (q && hay.indexOf(q) === -1) { return; }
            var row = document.createElement('div');
            row.className = 'iris-acd-dd-opt';
            var left = document.createElement('span');
            left.textContent = o.label;
            if (o.sub) {
                var sub = document.createElement('span');
                sub.className = 'iris-acd-dd-sub';
                sub.textContent = '(' + o.sub + ')';
                left.appendChild(sub);
            }
            row.appendChild(left);
            if (o.checked) {
                var ck = document.createElement('span');
                ck.className = 'iris-acd-dd-check';
                ck.textContent = '✓';
                row.appendChild(ck);
            }
            row.addEventListener('click', function () {
                root.classList.remove('open');
                cfg.onPick(o.value);
            });
            box.appendChild(row);
        });
    }

    trigger.addEventListener('click', function (ev) {
        ev.stopPropagation();
        var wasOpen = root.classList.contains('open');
        document.querySelectorAll('.iris-acd-dd.open').forEach(function (el) {
            el.classList.remove('open');
        });
        if (!wasOpen) {
            root.classList.add('open');
            search.value = '';
            render();
            search.focus();
        }
    });
    search.addEventListener('input', render);
    panel.addEventListener('click', function (ev) { ev.stopPropagation(); });
}

function iris_acd_load_catalogs() {
    fetch('/manage/severities/list', { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) { IRIS_ACD.severities = (j && j.data) || []; })
        .catch(function () { /* dropdown shows only Derived — degraded */ });
    fetch('/manage/users/restricted/list', { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) { IRIS_ACD.users = (j && j.data) || []; })
        .catch(function () { /* dropdown shows only Unassigned — degraded */ });
}

function iris_acd_put(fields, onDone) {
    iris_ac_fetch('/api/v2/alert-clusters/' + IRIS_ACD.id, 'PUT', fields)
        .then(function (j) {
            if (j.__status === 200) {
                // Refresh header facts from the authoritative row; the
                // detail's alerts list is not in a PUT response.
                Object.keys(j).forEach(function (k) {
                    if (k !== '__status') { IRIS_ACD.detail[k] = j[k]; }
                });
                if (onDone) { onDone(true); }
            } else if (onDone) { onDone(false, j); }
        });
}

/* ----------------------------------------------------- summary autosave */

function iris_acd_summary_render() {
    var s = IRIS_ACD.detail.summary;
    var view = $('#iris-acd-summary-view');
    if (s && s.trim()) {
        view.text(s).removeClass('iris-acd-empty');
    } else {
        view.text('Double-click to edit…').addClass('iris-acd-empty');
    }
}

function iris_acd_summary_set_state(txt, ok, sub) {
    $('#iris-acd-save-state').text(txt).toggleClass('iris-acd-saved-ok', !!ok);
    $('#iris-acd-save-sub').text(sub || '');
}

function iris_acd_summary_save(collapse) {
    var val = $('#iris-acd-summary-edit').val();
    iris_acd_summary_set_state('Saving…', false, '');
    iris_acd_put({ summary: val }, function (ok, j) {
        if (ok) {
            IRIS_ACD.dirty = false;
            iris_acd_summary_set_state('✓ All changes saved', true, 'Synced just now');
            if (collapse) {
                $('#iris-acd-summary-edit').hide();
                $('#iris-acd-summary-view').show();
                iris_acd_summary_render();
            }
        } else {
            // A refused save keeps the editor and its content — retryable.
            var msg = (j && (j.message || (j.data && j.data.message))) || 'save failed';
            iris_acd_summary_set_state('Not saved — ' + msg, false, '');
        }
    });
}

/* ------------------------------------------------------------- alerts */

function iris_acd_render_alerts() {
    var rows = (IRIS_ACD.detail.alerts || []).map(function (a) {
        var cid = (new URLSearchParams(window.location.search)).get('cid') || '1';
        var tags = String(a.tags || '').split(',').filter(Boolean).map(function (t) {
            return '<span class="iris-acd-tag">' + iris_ac_esc(t.trim()) + '</span>';
        }).join('');
        return '<tr>'
            + '<td><a class="iris-acd-rowtitle" href="/alerts?alert_ids=' + a.alert_id
                + '&cid=' + iris_ac_esc(cid) + '">#' + a.alert_id + ' — '
                + iris_ac_esc(a.title) + '</a>'
                + (tags ? '<div>' + tags + '</div>' : '') + '</td>'
            + '<td>' + iris_acd_sev_chip(a.severity) + '</td>'
            + '<td>' + iris_ac_esc(a.source || '') + '</td>'
            + '<td>' + iris_ac_esc(a.status || '') + '</td>'
            + '<td>' + iris_ac_esc(iris_ac_ts(a.source_event_time || a.creation_time)) + '</td>'
            + '<td><button type="button" class="btn btn-xs btn-outline-danger '
                + 'iris-acd-remove-alert" data-alert-id="' + a.alert_id + '" '
                + 'title="Remove from cluster">&#128465;</button></td>'
            + '</tr>';
    });
    $('#iris-acd-alerts-body').html(rows.join('')
        || '<tr><td colspan="6" class="text-muted">No member alerts.</td></tr>');
}

/* ----------------------------------------------- context (assets/IOCs) */

function iris_acd_load_context() {
    if (IRIS_ACD.contextFetching) { return; }
    IRIS_ACD.contextFetching = true;
    iris_ac_fetch('/api/v2/alert-clusters/' + IRIS_ACD.id + '/context')
        .then(function (j) {
            IRIS_ACD.contextFetching = false;
            if (j.__status !== 200) {
                IRIS_ACD.contextFailed = true;
                $('#iris-acd-assets-body, #iris-acd-iocs-body').html(
                    '<tr><td colspan="4" class="text-warning">Could not load.</td></tr>');
                return;
            }
            IRIS_ACD.context = { assets: j.assets || [], iocs: j.iocs || [],
                                 links: j.links || { assets: [], iocs: [] } };
            $('#iris-acd-count-assets').text(IRIS_ACD.context.assets.length);
            $('#iris-acd-count-iocs').text(IRIS_ACD.context.iocs.length);
            iris_acd_render_assets();
            iris_acd_render_iocs();
            iris_acd_render_timeline();
            if ($('#iris-acd-pane-correlation').hasClass('active')) {
                iris_acd_draw_graph();
            }
        });
}

function iris_acd_render_assets() {
    var rows = (IRIS_ACD.context.assets || []).map(function (a) {
        var ipdom = [a.ip, a.domain].filter(Boolean).join(' / ');
        return '<tr>'
            + '<td><span class="iris-acd-rowtitle">&#128421; ' + iris_ac_esc(a.name)
                + '</span><div class="iris-acd-sub">' + iris_ac_esc(a.name) + ' — '
                + iris_ac_esc(a.type || 'Unknown') + '</div></td>'
            + '<td>' + iris_ac_esc(a.type || '') + '</td>'
            + '<td class="iris-acd-mono">' + (ipdom ? iris_ac_esc(ipdom) : '—') + '</td>'
            + '<td>' + iris_ac_esc(a.compromise_status
                ? a.compromise_status.replace(/_/g, ' ') : '—') + '</td>'
            + '</tr>';
    });
    $('#iris-acd-assets-body').html(rows.join('')
        || '<tr><td colspan="4" class="text-muted">No assets on the member alerts.</td></tr>');
}

function iris_acd_render_iocs() {
    var rows = (IRIS_ACD.context.iocs || []).map(function (i) {
        var tags = String(i.tags || '').split(/[,|]/).filter(Boolean).map(function (t) {
            return '<span class="iris-acd-tag">' + iris_ac_esc(t.trim()) + '</span>';
        }).join('');
        return '<tr>'
            + '<td><span class="iris-acd-rowtitle iris-acd-mono">&#128373; '
                + iris_ac_esc(i.value) + '</span>'
                + (i.description ? '<div class="iris-acd-sub">'
                    + iris_ac_esc(i.description) + '</div>' : '') + '</td>'
            + '<td>' + iris_ac_esc(i.type || '') + '</td>'
            + '<td>' + (i.tlp ? iris_ac_esc(i.tlp) : '—') + '</td>'
            + '<td>' + (tags || '—') + '</td>'
            + '</tr>';
    });
    $('#iris-acd-iocs-body').html(rows.join('')
        || '<tr><td colspan="4" class="text-muted">No IOCs on the member alerts.</td></tr>');
}

/* ------------------------------------------------------------ timeline */

function iris_acd_render_timeline() {
    var items = (IRIS_ACD.detail.alerts || []).slice().sort(function (a, b) {
        var ta = a.source_event_time || a.creation_time || '';
        var tb = b.source_event_time || b.creation_time || '';
        return ta < tb ? -1 : (ta > tb ? 1 : a.alert_id - b.alert_id);
    }).map(function (a) {
        return '<div class="iris-acd-tl-item">'
            + '<div class="iris-acd-sub">' + iris_ac_esc(iris_ac_ts(
                a.source_event_time || a.creation_time))
            + '<span class="iris-acd-tl-chip">ALERT</span></div>'
            + '<div class="iris-acd-rowtitle">Alert #' + a.alert_id + ' — '
                + iris_ac_esc(a.title) + '</div>'
            + '<div class="iris-acd-sub">' + iris_ac_esc(a.severity || '')
                + ' · ' + iris_ac_esc(a.source || '') + '</div>'
            + '</div>';
    });
    $('#iris-acd-timeline-body').html(items.join('')
        || '<div class="text-muted">No member alerts.</div>');
}

/* ------------------------------------------------------ correlation graph */

function iris_acd_graph_data() {
    var d = IRIS_ACD.detail;
    var ctx = IRIS_ACD.context;
    var nodes = [], links = [], byId = {};
    (d.alerts || []).forEach(function (a) {
        var n = { id: 'a' + a.alert_id, kind: 'alert', label: a.title,
                  ref: a.alert_id };
        nodes.push(n); byId[n.id] = n;
    });
    (ctx.iocs || []).forEach(function (i) {
        var n = { id: 'i' + i.ioc_id, kind: 'ioc', label: i.value, ref: i.ioc_id };
        nodes.push(n); byId[n.id] = n;
    });
    (ctx.assets || []).forEach(function (s) {
        var n = { id: 's' + s.asset_id, kind: 'asset', label: s.name, ref: s.asset_id };
        nodes.push(n); byId[n.id] = n;
    });
    (ctx.links.iocs || []).forEach(function (p) {
        if (byId['a' + p[0]] && byId['i' + p[1]]) {
            links.push({ source: 'a' + p[0], target: 'i' + p[1], kind: 'ioc' });
        }
    });
    (ctx.links.assets || []).forEach(function (p) {
        if (byId['a' + p[0]] && byId['s' + p[1]]) {
            links.push({ source: 'a' + p[0], target: 's' + p[1], kind: 'asset' });
        }
    });
    return { nodes: nodes, links: links };
}

/* Pure panel-content builder (v3 node detail panel) — kept free of D3/DOM so
 * the vm harness can drive it. Neighbors come from the link pairs; the
 * description from whichever catalog owns the node. */
function iris_acd_node_panel_data(node, data, detail, ctx) {
    var kindLabel = { alert: 'Alert', ioc: 'IOC', asset: 'Asset' }[node.kind];
    var desc = null, alertId = null;
    if (node.kind === 'alert') {
        alertId = node.ref;
        var a = (detail.alerts || []).find(function (x) {
            return x.alert_id === node.ref;
        });
        if (a) {
            desc = a.title + (a.description ? '\n' + a.description : '');
        }
    } else if (node.kind === 'ioc') {
        var i = ((ctx && ctx.iocs) || []).find(function (x) {
            return x.ioc_id === node.ref;
        });
        if (i) {
            desc = i.value + (i.description ? '\n' + i.description : '')
                + (i.type ? '\nType: ' + i.type : '');
        }
    } else {
        var s = ((ctx && ctx.assets) || []).find(function (x) {
            return x.asset_id === node.ref;
        });
        if (s) {
            var bits = [s.name];
            if (s.type) { bits.push('Type: ' + s.type); }
            var ipdom = [s.ip, s.domain].filter(Boolean).join(' / ');
            if (ipdom) { bits.push(ipdom); }
            desc = bits.join('\n');
        }
    }
    var related = [];
    var seen = {};
    (data.links || []).forEach(function (l) {
        var sid = l.source.id || l.source;
        var tid = l.target.id || l.target;
        var other = null;
        if (sid === node.id) { other = tid; }
        else if (tid === node.id) { other = sid; }
        if (other && !seen[other]) {
            seen[other] = true;
            var n = (data.nodes || []).find(function (x) { return x.id === other; });
            if (n) { related.push({ id: n.id, label: n.label, kind: n.kind }); }
        }
    });
    return {
        kind: kindLabel,
        title: node.label,
        desc: desc,
        related: related,
        relatedLabel: node.kind === 'alert' ? 'Related indicators' : 'Related alerts',
        alertId: alertId
    };
}

var IRIS_ACD_GRAPH_COLORS = { alert: '#ff9e27', ioc: '#5e9bf2', asset: '#2dce89' };

/* Lucide bell (24x24 viewBox) for alert nodes — drawn inside the circle. */
var IRIS_ACD_BELL_PATHS = [
    'M10.268 21a2 2 0 0 0 3.464 0',
    'M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 '
        + '12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.737 '
        + '7.326'
];

function iris_acd_draw_graph() {
    if (!IRIS_ACD.context || typeof d3 === 'undefined') { return; }
    var wrap = document.getElementById('iris-acd-graph-area');
    var W = wrap.clientWidth || 800, H = wrap.clientHeight || 560;
    var data = iris_acd_graph_data();

    $('#iris-acd-graph-chip-alerts').text('Alerts '
        + data.nodes.filter(function (n) { return n.kind === 'alert'; }).length);
    $('#iris-acd-graph-chip-iocs').text('IOCs '
        + data.nodes.filter(function (n) { return n.kind === 'ioc'; }).length);
    $('#iris-acd-graph-chip-assets').text('Assets '
        + data.nodes.filter(function (n) { return n.kind === 'asset'; }).length);

    var svg = d3.select('#iris-acd-graph');
    svg.selectAll('*').remove();
    var root = svg.append('g').attr('class', 'iris-acd-graph-root');

    var zoom = d3.zoom().scaleExtent([0.2, 4]).on('zoom', function (ev) {
        root.attr('transform', ev.transform);
    });
    svg.call(zoom).on('dblclick.zoom', null);

    var sim = d3.forceSimulation(data.nodes)
        .force('link', d3.forceLink(data.links).id(function (n) { return n.id; })
            .distance(120))
        .force('charge', d3.forceManyBody().strength(-320))
        .force('center', d3.forceCenter(W / 2, H / 2))
        .force('collide', d3.forceCollide(40));

    // v3 edge styles: dashed to IOCs, solid to assets.
    var link = root.append('g').selectAll('line').data(data.links).join('line')
        .attr('stroke', function (l) {
            return l.kind === 'asset' ? 'rgba(94,155,242,0.55)'
                                      : 'rgba(255,255,255,0.25)';
        })
        .attr('stroke-width', function (l) { return l.kind === 'asset' ? 1.5 : 1; })
        .attr('stroke-dasharray', function (l) {
            return l.kind === 'asset' ? null : '4 4';
        });

    var node = root.append('g').selectAll('g').data(data.nodes).join('g')
        .style('cursor', 'pointer')
        .call(d3.drag()
            .on('start', function (ev, n) {
                if (!ev.active) { sim.alphaTarget(0.3).restart(); }
                n.fx = n.x; n.fy = n.y;
                ev.sourceEvent.stopPropagation();
            })
            .on('drag', function (ev, n) { n.fx = ev.x; n.fy = ev.y; })
            .on('end', function (ev, n) {
                if (!ev.active) { sim.alphaTarget(0); }
                n.fx = null; n.fy = null;
            }));

    node.append('circle')
        .attr('class', 'iris-acd-node-circle')
        .attr('r', function (n) { return n.kind === 'alert' ? 20 : 16; })
        .attr('fill', 'rgba(21,21,26,0.9)')
        .attr('stroke', function (n) { return IRIS_ACD_GRAPH_COLORS[n.kind]; })
        .attr('stroke-width', 2);

    // v3 node icons: bell for alerts, concentric target for IOCs, assets stay
    // a plain circle (matches the preview's nodes).
    node.each(function (n) {
        var g = d3.select(this);
        if (n.kind === 'alert') {
            var ig = g.append('g')
                .attr('transform', 'translate(-9,-9) scale(0.75)')
                .attr('fill', 'none')
                .attr('stroke', IRIS_ACD_GRAPH_COLORS.alert)
                .attr('stroke-width', 2)
                .attr('stroke-linecap', 'round')
                .attr('stroke-linejoin', 'round');
            IRIS_ACD_BELL_PATHS.forEach(function (d) {
                ig.append('path').attr('d', d);
            });
        } else if (n.kind === 'ioc') {
            g.append('circle').attr('r', 6.5).attr('fill', 'none')
                .attr('stroke', IRIS_ACD_GRAPH_COLORS.ioc).attr('stroke-width', 1.5);
            g.append('circle').attr('r', 2).attr('fill', IRIS_ACD_GRAPH_COLORS.ioc);
        }
    });

    node.append('text')
        .text(function (n) {
            return n.label.length > 34 ? n.label.slice(0, 33) + '…' : n.label;
        })
        .attr('text-anchor', 'middle')
        .attr('dy', function (n) { return (n.kind === 'alert' ? 20 : 16) + 14; })
        .attr('fill', '#c9c9d4')
        .style('font-size', '11px');

    node.on('click', function (ev, n) {
        ev.stopPropagation();
        iris_acd_select_node(n.id);
    });
    svg.on('click', function () { iris_acd_close_node_panel(); });

    sim.on('tick', function () {
        link.attr('x1', function (l) { return l.source.x; })
            .attr('y1', function (l) { return l.source.y; })
            .attr('x2', function (l) { return l.target.x; })
            .attr('y2', function (l) { return l.target.y; });
        node.attr('transform', function (n) {
            return 'translate(' + n.x + ',' + n.y + ')';
        });
    });

    IRIS_ACD.graph = { svg: svg, zoom: zoom, sim: sim, data: data, W: W, H: H };
}

/* --------------------------------------------- v3 node detail panel */

function iris_acd_highlight_node(nodeId) {
    var g = IRIS_ACD.graph;
    if (!g) { return; }
    g.svg.selectAll('.iris-acd-node-circle')
        .attr('stroke-width', function (m) { return m.id === nodeId ? 4 : 2; });
}

function iris_acd_select_node(nodeId) {
    var g = IRIS_ACD.graph;
    if (!g) { return; }
    var n = g.data.nodes.find(function (x) { return x.id === nodeId; });
    if (!n) { return; }
    iris_acd_highlight_node(nodeId);
    var pd = iris_acd_node_panel_data(n, g.data, IRIS_ACD.detail || {},
                                      IRIS_ACD.context || {});
    $('#iris-acd-np-kind').text(pd.kind);
    $('#iris-acd-np-title').text(pd.title).attr('title', pd.title);
    if (pd.desc) {
        $('#iris-acd-np-desc').text(pd.desc).show();
    } else {
        $('#iris-acd-np-desc').hide();
    }
    $('#iris-acd-np-related-label').text(pd.relatedLabel);
    $('#iris-acd-np-related-count').text(pd.related.length);
    var box = $('#iris-acd-np-related').empty();
    if (!pd.related.length) {
        box.append($('<div class="text-muted" style="font-size:0.8rem;"></div>')
            .text('Nothing linked to this node.'));
    }
    pd.related.forEach(function (r) {
        var row = $('<div class="iris-acd-np-row"></div>')
            .attr('data-node-id', r.id);
        row.append($('<span class="iris-acd-legend-dot" style="margin-left:0;"></span>')
            .css('background', IRIS_ACD_GRAPH_COLORS[r.kind] || '#9a9aa5'));
        row.append($('<span style="overflow:hidden;text-overflow:ellipsis;'
            + 'white-space:nowrap;"></span>').text(r.label).attr('title', r.label));
        box.append(row);
    });
    if (pd.alertId != null) {
        var cid = (new URLSearchParams(window.location.search)).get('cid') || '1';
        $('#iris-acd-np-open')
            .text('Open alert #' + pd.alertId + ' ↗')
            .attr('href', '/alerts?alert_ids=' + pd.alertId
                + '&cid=' + encodeURIComponent(cid));
        $('#iris-acd-np-foot').show();
    } else {
        $('#iris-acd-np-foot').hide();
    }
    document.getElementById('iris-acd-node-panel').classList.add('open');
}

function iris_acd_close_node_panel() {
    document.getElementById('iris-acd-node-panel').classList.remove('open');
    iris_acd_highlight_node(null);
}

function iris_acd_graph_search_cycle() {
    var g = IRIS_ACD.graph;
    if (!g) { return; }
    var q = ($('#iris-acd-graph-search').val() || '').toLowerCase().trim();
    if (!q) { return; }
    var hits = g.data.nodes.filter(function (n) {
        return n.label.toLowerCase().indexOf(q) !== -1;
    });
    if (!hits.length) { return; }
    IRIS_ACD.searchIdx = (IRIS_ACD.searchIdx + 1) % hits.length;
    var n = hits[IRIS_ACD.searchIdx];
    g.svg.transition().duration(400).call(
        g.zoom.transform,
        d3.zoomIdentity.translate(g.W / 2 - n.x * 1.4, g.H / 2 - n.y * 1.4).scale(1.4));
    g.svg.selectAll('circle').attr('stroke-width', function (m) {
        return m.id === n.id ? 4 : 2;
    });
}

/* ------------------------------------------------------------ comments */

function iris_acd_load_comments() {
    if (IRIS_ACD.commentsFetching) { return; }
    IRIS_ACD.commentsFetching = true;
    iris_ac_fetch('/api/v2/alert-clusters/' + IRIS_ACD.id + '/comments')
        .then(function (j) {
            IRIS_ACD.commentsFetching = false;
            if (j.__status !== 200) {
                IRIS_ACD.commentsFailed = true;
                $('#iris-acd-comments').html(
                    '<span class="text-warning">Could not load comments.</span>');
                return;
            }
            IRIS_ACD.comments = j.rows || [];
            iris_acd_render_comments();
        });
}

function iris_acd_render_comments() {
    if (IRIS_ACD.comments === null) { return; }  // have not looked yet
    if (!IRIS_ACD.comments.length) {
        $('#iris-acd-comments').html(
            '<span class="text-muted">No analyst comments yet.</span>');
        return;
    }
    var box = $('#iris-acd-comments').empty().removeClass('text-muted');
    IRIS_ACD.comments.forEach(function (cm) {
        var el = $('<div class="iris-acd-comment"></div>');
        el.append($('<div class="iris-acd-sub"></div>')
            .text((cm.user_name || 'unknown') + ' · ' + iris_ac_ts(cm.created_at)));
        el.append($('<div style="white-space:pre-wrap;"></div>').text(cm.content));
        box.append(el);
    });
}

/* --------------------------------------------------------------- flows */

function iris_acd_load_flows() {
    $('#iris-ac-flows').text('Loading…');
    iris_ac_fetch('/api/v2/alert-clusters/' + IRIS_ACD.id + '/flows')
        .then(function (fl) {
            if (fl.__status !== 200) {
                $('#iris-ac-flows').text('Failed to load flows.');
                return;
            }
            var atts = fl.rows || [];
            if (!atts.length) {
                $('#iris-ac-flows').text('No investigation flows attached.');
                return;
            }
            window.IrisFlowChecklist.render(
                document.getElementById('iris-ac-flows'), atts);
        });
}

/* ---------------------------------------------------- AI triage (moved) */
/* Moved verbatim from the pre-v3 list page; only the container changed. */

function iris_ac_triage_render(t) {
    $('#iris-ac-triage-status').text('');
    $('#iris-ac-triage-panel').show();
    $('#iris-ac-triage-editor').hide();
    $('#iris-ac-triage-name').text(t.suggested_name || '');
    var conf = t.confidence || 'low';
    $('#iris-ac-triage-conf')
        .attr('class', 'ml-2 iris-ac-conf-' + conf)
        .text(conf + ' confidence');
    $('#iris-ac-triage-narrative').text(t.narrative || '');
    $('#iris-ac-triage-edited-badge').toggle(!!t.is_edited);
    $('#iris-ac-triage-footer').text(
        (t.prompt_id || '') + ' · ' + (t.model || '')
        + (t.cached ? ' · cached' : '')
        + (t.generated_at ? ' · ' + iris_ac_ts(t.generated_at) : ''));
    $('#iris-ac-triage-generate').hide();
    $('#iris-ac-triage-rerun').show();
    $('#iris-ac-triage-edit-btn').show();
    $('#iris-ac-triage-revert').toggle(!!t.is_edited);
}

function iris_ac_triage_reset() {
    $('#iris-ac-triage-panel').hide();
    $('#iris-ac-triage-editor').hide();
    $('#iris-ac-triage-status').text('');
    $('#iris-ac-triage-generate').show();
    $('#iris-ac-triage-rerun').hide();
    $('#iris-ac-triage-edit-btn').hide();
    $('#iris-ac-triage-revert').hide();
    if (IRIS_AC._pollTimer) { clearTimeout(IRIS_AC._pollTimer); IRIS_AC._pollTimer = null; }
}

function iris_ac_triage_refresh() {
    iris_ac_triage_reset();
    if (!IRIS_AC._current) { return; }
    iris_ac_fetch('/api/v2/alert-clusters/' + IRIS_AC._current.id + '/triage')
        .then(function (j) {
            if (j.__status === 200) {
                iris_ac_triage_render(j);
            } else {
                $('#iris-ac-triage-status').text('Not generated yet.');
            }
        });
}

function iris_ac_triage_poll(taskId) {
    iris_ac_fetch('/api/v2/ai/jobs/' + taskId).then(function (j) {
        if (j.__status !== 200) {
            $('#iris-ac-triage-status').text('Poll failed (HTTP ' + j.__status + ').');
            return;
        }
        if (j.state === 'done') {
            if (j.result) { iris_ac_triage_render(j.result); }
            else { iris_ac_triage_refresh(); }
        } else if (j.state === 'error') {
            $('#iris-ac-triage-status').html('<span class="text-danger">'
                + iris_ac_esc(j.error || 'generation failed') + '</span>');
            $('#iris-ac-triage-generate').show();
        } else if (j.state === 'cancelled') {
            $('#iris-ac-triage-status').text('Cancelled.');
            $('#iris-ac-triage-generate').show();
        } else {
            $('#iris-ac-triage-status').text('Generating… (' + j.state
                + (j.queue_position ? (', queue position ' + j.queue_position) : '') + ')');
            IRIS_AC._pollTimer = setTimeout(function () { iris_ac_triage_poll(taskId); }, 2000);
        }
    });
}

function iris_ac_triage_generate(force, discardEdit) {
    if (!IRIS_AC._current) { return; }
    $('#iris-ac-triage-status').text('Queueing…');
    $('#iris-ac-triage-generate').hide();
    $('#iris-ac-triage-rerun').hide();
    iris_ac_fetch('/api/v2/alert-clusters/' + IRIS_AC._current.id + '/triage', 'POST',
        { force: !!force, discard_edit: !!discardEdit })
        .then(function (j) {
            if (j.__status === 202) {
                iris_ac_triage_poll(j.task_id);
            } else if (j.__status === 409) {
                if (confirm('A manual edit exists on this triage. Regenerating '
                            + 'discards it. Continue?')) {
                    iris_ac_triage_generate(force, true);
                } else {
                    iris_ac_triage_refresh();
                }
            } else {
                var msg = (j.data && j.data.message) || j.message || ('HTTP ' + j.__status);
                $('#iris-ac-triage-status').html('<span class="text-danger">'
                    + iris_ac_esc(msg) + '</span>');
                $('#iris-ac-triage-generate').show();
            }
        });
}

/* ------------------------------------------------------------ escalate */

function iris_acd_open_escalate() {
    var d = IRIS_ACD.detail;
    if (d.escalated_case_id) {
        var cid = (new URLSearchParams(window.location.search)).get('cid') || '1';
        window.location.href = '/case?cid=' + d.escalated_case_id;
        return;
    }
    $('#iris-acd-esc-title').val(d.title);
    $('#iris-acd-esc-error').hide();
    // Target-case options load on demand (merge only).
    var sel = document.getElementById('iris-acd-esc-case');
    if (!sel.options.length) {
        fetch('/manage/cases/list', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (j) {
                var rows = (j && j.data) || [];
                rows.forEach(function (c) {
                    if (c.case_close_date) { return; }  // open cases only
                    var o = document.createElement('option');
                    o.value = c.case_id;
                    o.textContent = '#' + c.case_id + ' — ' + c.case_name;
                    sel.appendChild(o);
                });
            })
            .catch(function () { /* merge select stays empty — new-case still works */ });
    }
    $('#iris-acd-escalate-modal').modal('show');
}

function iris_acd_submit_escalate() {
    var mode = $('input[name="iris-acd-esc-mode"]:checked').val();
    var body = {
        mode: mode,
        note: $('#iris-acd-esc-note').val() || null,
        import_as_event: $('#iris-acd-esc-event').is(':checked')
    };
    if (mode === 'new_case') {
        body.case_title = $('#iris-acd-esc-title').val();
    } else {
        body.target_case_id = parseInt($('#iris-acd-esc-case').val(), 10);
        if (!body.target_case_id) {
            $('#iris-acd-esc-error').text('Pick a target case.').show();
            return;
        }
    }
    $('#iris-acd-esc-submit').prop('disabled', true).text('Working…');
    iris_ac_fetch('/api/v2/alert-clusters/' + IRIS_ACD.id + '/escalate', 'POST', body)
        .then(function (j) {
            $('#iris-acd-esc-submit').prop('disabled', false).text('Escalate');
            if (j.__status === 200) {
                window.location.href = '/case?cid=' + j.case_id;
            } else {
                var msg = (j.data && j.data.message) || j.message || ('HTTP ' + j.__status);
                $('#iris-acd-esc-error').text(msg).show();
            }
        });
}

/* ----------------------------------------------------------------- load */

function iris_acd_load() {
    iris_ac_fetch('/api/v2/alert-clusters/' + IRIS_ACD.id).then(function (j) {
        if (j.__status !== 200) {
            $('#iris-acd-main').hide();
            $('#iris-acd-notfound').show();
            return;
        }
        IRIS_ACD.detail = j;
        IRIS_AC._current = j;   // the moved triage block reads this
        $('#iris-acd-notfound').hide();
        $('#iris-acd-main').show();
        iris_acd_render_header();
        iris_acd_summary_render();
        iris_acd_render_alerts();
        iris_acd_render_timeline();
        iris_acd_load_context();
        iris_acd_load_flows();
        iris_ac_triage_refresh();
        iris_acd_load_comments();
    });
}

/* --------------------------------------------------------------- wiring */

$(function () {
    IRIS_ACD.id = $('#iris-acd-cluster-id').val();
    iris_acd_load();

    // Tab switching; the graph draws on first entry (a hidden pane has
    // zero width — the D3-in-hidden-container trap).
    $('#iris-acd-tabs').on('click', '.iris-acd-tab', function () {
        $('.iris-acd-tab').removeClass('active');
        $(this).addClass('active');
        var pane = $(this).attr('data-pane');
        $('.iris-acd-pane').removeClass('active');
        $('#iris-acd-pane-' + pane).addClass('active');
        if (pane === 'correlation' && IRIS_ACD.context && !IRIS_ACD.graph) {
            iris_acd_draw_graph();
        }
    });

    /* Summary autosave. */
    $('#iris-acd-summary-view').on('dblclick', function () {
        $(this).hide();
        $('#iris-acd-summary-edit').val(IRIS_ACD.detail.summary || '').show().focus();
    });
    $('#iris-acd-summary-edit').on('input', function () {
        IRIS_ACD.dirty = true;
        iris_acd_summary_set_state('Unsaved changes…', false, '');
        clearTimeout(IRIS_ACD.saveTimer);
        IRIS_ACD.saveTimer = setTimeout(function () { iris_acd_summary_save(false); }, 1500);
    });
    $('#iris-acd-summary-edit').on('blur', function () {
        clearTimeout(IRIS_ACD.saveTimer);
        iris_acd_summary_save(true);
    });
    $('#iris-acd-summary-save').on('click', function () {
        if ($('#iris-acd-summary-edit').is(':visible')) {
            clearTimeout(IRIS_ACD.saveTimer);
            iris_acd_summary_save(true);
        }
    });
    $('#iris-acd-summary-refresh').on('click', function () {
        if (IRIS_ACD.dirty
            && !confirm('Discard unsaved summary changes and reload?')) { return; }
        IRIS_ACD.dirty = false;
        iris_acd_load();
    });

    /* Header controls: three v3-style searchable dropdowns. */
    iris_acd_load_catalogs();
    document.addEventListener('click', function () {
        document.querySelectorAll('.iris-acd-dd.open').forEach(function (el) {
            el.classList.remove('open');
        });
    });

    iris_acd_dd_setup('iris-acd-dd-status', {
        options: function () {
            var cur = IRIS_ACD.detail ? IRIS_ACD.detail.status : null;
            var vals = IRIS_ACD_STATUSES.slice();
            if (cur === 'closed') { vals.push('closed'); }  // legacy: shown, still current
            return vals.map(function (s) {
                return { value: s, label: iris_acd_cap(s), checked: s === cur };
            });
        },
        onPick: function (v) {
            if (!IRIS_ACD.detail || v === IRIS_ACD.detail.status) { return; }
            iris_acd_put({ status: v }, function (ok, j) {
                if (ok) { iris_acd_render_status_chip(); }
                else {
                    var msg = (j && ((j.data && j.data.message) || j.message))
                        || 'status change refused';
                    alert(msg);
                }
            });
        }
    });

    iris_acd_dd_setup('iris-acd-dd-severity', {
        options: function () {
            var d = IRIS_ACD.detail || {};
            var rows = [{ value: '', label: 'Derived (auto)',
                          checked: d.severity_override_id == null }];
            (IRIS_ACD.severities || []).forEach(function (s) {
                rows.push({ value: s.severity_id, label: s.severity_name,
                            checked: d.severity_override_id === s.severity_id });
            });
            return rows;
        },
        onPick: function (v) {
            iris_acd_put({ severity_override_id: v === '' ? null : parseInt(v, 10) },
                         function (ok) { if (ok) { iris_acd_render_severity_chip(); } });
        }
    });

    iris_acd_dd_setup('iris-acd-dd-owner', {
        options: function () {
            var d = IRIS_ACD.detail || {};
            var rows = [{ value: '', label: 'Unassigned',
                          checked: d.owner_id == null }];
            (IRIS_ACD.users || []).forEach(function (u) {
                rows.push({ value: u.user_id,
                            label: u.user_name || u.user_login,
                            sub: u.user_login,
                            checked: d.owner_id === u.user_id });
            });
            return rows;
        },
        onPick: function (v) {
            iris_acd_put({ owner_id: v === '' ? null : parseInt(v, 10) },
                         function (ok) { if (ok) { iris_acd_render_owner_text(); } });
        }
    });

    /* Alerts tab: remove member. */
    $(document).on('click', '.iris-acd-remove-alert', function () {
        var aid = $(this).attr('data-alert-id');
        if (!confirm('Remove alert #' + aid + ' from this cluster? The alert '
                     + 'itself is untouched.')) { return; }
        fetch('/api/v2/alert-clusters/' + IRIS_ACD.id + '/members/' + aid,
              { method: 'DELETE', credentials: 'same-origin' })
            .then(function (r) {
                if (r.status === 204 || r.ok) {
                    IRIS_ACD.context = null;
                    IRIS_ACD.graph = null;
                    iris_acd_load();
                }
            });
    });

    /* Correlation controls. */
    $('#iris-acd-graph-zoomin').on('click', function () {
        var g = IRIS_ACD.graph;
        if (g) { g.svg.transition().call(g.zoom.scaleBy, 1.3); }
    });
    $('#iris-acd-graph-zoomout').on('click', function () {
        var g = IRIS_ACD.graph;
        if (g) { g.svg.transition().call(g.zoom.scaleBy, 1 / 1.3); }
    });
    $('#iris-acd-graph-fit').on('click', function () {
        var g = IRIS_ACD.graph;
        if (g) { g.svg.transition().call(g.zoom.transform, d3.zoomIdentity); }
    });
    $('#iris-acd-graph-play').on('click', function () {
        var g = IRIS_ACD.graph;
        if (g) { g.sim.alpha(0.9).restart(); }
    });
    $('#iris-acd-graph-refresh').on('click', function () {
        iris_acd_close_node_panel();
        IRIS_ACD.graph = null;
        iris_acd_draw_graph();
    });
    $('#iris-acd-np-close').on('click', iris_acd_close_node_panel);
    $(document).on('click', '.iris-acd-np-row', function () {
        iris_acd_select_node($(this).attr('data-node-id'));
    });
    $('#iris-acd-graph-search').on('keydown', function (ev) {
        if (ev.key === 'Enter') { iris_acd_graph_search_cycle(); }
    });
    $('#iris-acd-graph-search').on('input', function () { IRIS_ACD.searchIdx = -1; });

    /* Activity. */
    $('#iris-acd-comment-post').on('click', function () {
        var content = ($('#iris-acd-comment-input').val() || '').trim();
        if (!content) { return; }
        iris_ac_fetch('/api/v2/alert-clusters/' + IRIS_ACD.id + '/comments', 'POST',
                      { content: content })
            .then(function (j) {
                if (j.__status === 201 || j.__status === 200) {
                    $('#iris-acd-comment-input').val('');
                    IRIS_ACD.comments = null;
                    iris_acd_load_comments();
                }
                // A refused post keeps the composer content for retry.
            });
    });

    /* Escalate or merge. */
    $('#iris-acd-escalate-btn').on('click', iris_acd_open_escalate);
    $('input[name="iris-acd-esc-mode"]').on('change', function () {
        var merge = $('#iris-acd-esc-mode-merge').is(':checked');
        $('#iris-acd-esc-case-group').toggle(merge);
        $('#iris-acd-esc-title-group').toggle(!merge);
        $('#iris-acd-esc-submit').text(merge ? 'Merge' : 'Escalate');
    });
    $('#iris-acd-esc-submit').on('click', iris_acd_submit_escalate);

    /* AI triage (moved bindings — ids unchanged). */
    $('#iris-ac-triage-generate').on('click', function () { iris_ac_triage_generate(false, false); });
    $('#iris-ac-triage-rerun').on('click', function () { iris_ac_triage_generate(true, false); });
    $('#iris-ac-triage-edit-btn').on('click', function () {
        $('#iris-ac-triage-edit-name').val($('#iris-ac-triage-name').text());
        $('#iris-ac-triage-edit-body').val($('#iris-ac-triage-narrative').text());
        $('#iris-ac-triage-panel').hide();
        $('#iris-ac-triage-editor').show();
    });
    $('#iris-ac-triage-cancel').on('click', function () {
        $('#iris-ac-triage-editor').hide();
        $('#iris-ac-triage-panel').show();
    });
    $('#iris-ac-triage-save').on('click', function () {
        if (!IRIS_AC._current) { return; }
        iris_ac_fetch('/api/v2/alert-clusters/' + IRIS_AC._current.id + '/triage', 'PUT', {
            suggested_name: $('#iris-ac-triage-edit-name').val(),
            narrative: $('#iris-ac-triage-edit-body').val()
        }).then(function (j) {
            if (j.__status === 200) {
                iris_ac_triage_render(j);
            } else {
                var msg = (j.data && j.data.message) || j.message || ('HTTP ' + j.__status);
                alert('Save failed: ' + msg);
            }
        });
    });
    $('#iris-ac-triage-revert').on('click', function () {
        if (!IRIS_AC._current) { return; }
        if (!confirm('Discard the manual edit and restore the AI output?')) { return; }
        iris_ac_fetch('/api/v2/alert-clusters/' + IRIS_AC._current.id + '/triage/revert',
            'POST', {})
            .then(function (j) {
                if (j.__status === 200) { iris_ac_triage_render(j); }
            });
    });
});

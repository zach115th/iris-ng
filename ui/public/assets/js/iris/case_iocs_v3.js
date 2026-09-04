/* v3-shaped IOC page: searchable master list + detail panel, rendered from
 * the SAME payload the legacy DataTable eats (GET /api/v2/cases/<cid>/iocs)
 * and driving the EXISTING modal functions (add_ioc / edit_ioc / delete_ioc).
 * The legacy toolbar + table stay in the DOM, hidden, so their machinery —
 * CSV import/export, module quick-actions, the update poller — keeps
 * working; "Show legacy table" in the ⋮ menu is the safety valve.
 *
 * NB the page calls the V2 endpoint, not /case/ioc/list. They are two
 * parallel implementations with different payloads; patch the one the page
 * actually fetches.
 */

var IRIS_CI = {rows: [], sel: null, q: '', tab: 'details',
               links: {}, comments: {}, profiles: {},
               editing: false, iocTypes: null, tlps: null, tagSugg: null,
               tl: null, tlFetching: false,
               assetCat: null, assetCatFetching: false,
               aMenu: false, aMenuQ: '', assetTypesCat: null,
               notes: {}, noteOpen: null,
               peeks: {}, caseOpen: null,
               modOpts: null, modMenu: false};

var IRIS_CI_TLP = {
    'red': ['rgba(242,89,97,0.15)', 'rgba(242,89,97,0.5)', '#F25961'],
    'amber': ['rgba(244,196,48,0.15)', 'rgba(244,196,48,0.5)', '#f4c430'],
    'amber strict': ['rgba(244,196,48,0.15)', 'rgba(244,196,48,0.5)', '#f4c430'],
    'green': ['rgba(45,206,137,0.15)', 'rgba(45,206,137,0.5)', '#2dce89'],
    'clear': ['rgba(255,255,255,0.08)', 'rgba(255,255,255,0.3)', '#c8c8d0'],
    'white': ['rgba(255,255,255,0.08)', 'rgba(255,255,255,0.3)', '#c8c8d0']
};

function iris_ci_esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return {'&': '&amp;', '<': '&lt;', '>': '&gt;',
                '"': '&quot;', "'": '&#39;'}[c];
    });
}

function iris_ci_cid() {
    /* The (\d+) capture is already digits-only; re-canonicalising through
       parseInt makes that provable to taint tracking, since this value is
       interpolated into html builds page-wide. */
    var m = window.location.search.match(/[?&]cid=(\d+)/);
    var n = m ? parseInt(m[1], 10) : 1;
    return (Number.isFinite(n) && n > 0) ? String(n) : '1';
}

function iris_ci_csrf() {
    var el = document.getElementById('csrf_token');
    return el ? el.value : '';
}

function iris_ci_type(row) {
    return (row.ioc_type && row.ioc_type.type_name) || row.ioc_type || '';
}

function iris_ci_tlp(row) {
    return (row.tlp && row.tlp.tlp_name) || row.tlp_name || '';
}

function iris_ci_tags(row) {
    return String(row.ioc_tags || '').split(/[,|]/)
        .map(function (t) { return t.trim(); })
        .filter(function (t) { return t; });
}

/* TLP name is validated against a known map — a server string is never
   interpolated into a style attribute. */
function iris_ci_tlp_badge(name) {
    var key = String(name || '').toLowerCase().trim();
    var c = IRIS_CI_TLP[key];
    if (!c) return '';
    return '<span style="background:' + c[0] + '; border:1px solid ' + c[1] +
        '; color:' + c[2] +
        '; border-radius:8px; padding:1px 8px; font-size:0.66rem; white-space:nowrap;">TLP:' +
        iris_ci_esc(key.charAt(0).toUpperCase() + key.slice(1)) + '</span>';
}

var IRIS_CI_LOAD_INFLIGHT = false;
var IRIS_CI_LOAD_QUEUED = false;

function iris_ci_load() {
    /* Coalesce bursts: the payload is the case's full IOC set — tens of MB
       on a VT-enriched case — and boot plus the legacy module's own
       get_case_ioc() can land here back to back. One fetch flies; a request
       made while it is in the air runs ONCE more on completion rather than
       being dropped (a save's reload may carry newer data than the
       in-flight response). */
    if (IRIS_CI_LOAD_INFLIGHT) { IRIS_CI_LOAD_QUEUED = true; return; }
    IRIS_CI_LOAD_INFLIGHT = true;
    var done = function () {
        IRIS_CI_LOAD_INFLIGHT = false;
        if (IRIS_CI_LOAD_QUEUED) { IRIS_CI_LOAD_QUEUED = false; iris_ci_load(); }
    };
    fetch('/api/v2/cases/' + iris_ci_cid() + '/iocs?per_page=1000',
          {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (d) {
            IRIS_CI.rows = (d && d.data) || [];
            iris_ci_render_list();
            iris_ci_render_detail();
            done();
        })
        .catch(function () { IRIS_CI.rows = []; iris_ci_render_list(); done(); });
    /* one bulk call for note + asset links rather than N per-IOC lookups */
    fetch('/api/v2/cases/' + iris_ci_cid() + '/iocs/links',
          {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (d) {
            IRIS_CI.links = d || {};
            iris_ci_render_list();
            iris_ci_render_detail();
        })
        .catch(function () { IRIS_CI.links = {}; });
}

function iris_ci_links_for(row) {
    return (row && IRIS_CI.links[String(row.ioc_id)])
        || {note_links: [], asset_links: [], misp: null};
}

/* ---- Timeline tab: master-timeline events referencing this indicator.
 * Same source as the timeline page itself (/case/timeline/advanced-filter,
 * NOT /events/list), and the same matching approach as the assets tab:
 * per-event iocs carry only a name, no id, so match on the value. */
function iris_ci_load_timeline(force) {
    /* `IRIS_CI.tl === null` means "not fetched yet", NOT "no events" — the
     * tab renders a different message for each, so the in-flight marker is
     * a separate flag rather than an early [] (an empty array would claim
     * the indicator appears nowhere before we had looked). */
    if (IRIS_CI.tlFetching) return;
    if (IRIS_CI.tl !== null && !force) return;
    IRIS_CI.tlFetching = true;
    fetch('/case/timeline/advanced-filter?cid=' + iris_ci_cid() + '&q=%7B%7D',
          {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (resp) {
            IRIS_CI.tlFetching = false;
            IRIS_CI.tl = ((resp && resp.data) || {}).tim || [];
            iris_ci_render_detail();
        })
        .catch(function () {
            IRIS_CI.tlFetching = false;
            IRIS_CI.tl = [];
            iris_ci_render_detail();
        });
}

function iris_ci_tl_for(r) {
    var v = String(r.ioc_value || '').toLowerCase();
    if (!v) return [];
    return (IRIS_CI.tl || []).filter(function (ev) {
        return (ev.iocs || []).some(function (i) {
            return String(i.name || '').toLowerCase() === v;
        });
    });
}

var IRIS_CI_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function iris_ci_tl_daylabel(dstr) {
    /* naive-UTC storage — label the STORED date, never re-zone it */
    var p = String(dstr || '').split('-');
    if (p.length < 3) return dstr || '';
    var label = IRIS_CI_MONTHS[parseInt(p[1], 10) - 1] + ' ' +
        parseInt(p[2], 10);
    var now = new Date();
    var today = now.getFullYear() + '-' +
        String(now.getMonth() + 1).padStart(2, '0') + '-' +
        String(now.getDate()).padStart(2, '0');
    return dstr === today ? 'Today &middot; ' + label
                          : label + ', ' + p[0];
}

/* Hover action icons — identical set and behaviour to the Assets tab:
 * flag toggles LIVE via the legacy GET /case/timeline/events/flag/<id>
 * (non-POST verbs are CSRF-exempt); edit / comment / open deep-link to
 * ?shared=<id> on the full timeline (the event modal machinery lives in
 * that bundle), branch links to the Graph. No dead buttons. */
function iris_ci_tl_actions_html(ev) {
    var shared = '/case/timeline?cid=' + iris_ci_cid() +
        '&shared=' + ev.event_id;
    var icon = function (paths) {
        return '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            paths + '</svg>';
    };
    var link = function (href, title, paths) {
        return '<a href="' + href + '" title="' + title +
            '" style="color:#9a9aa5; display:inline-flex; padding:2px;">' +
            icon(paths) + '</a>';
    };
    return '<span class="iris-ci-tlacts" style="margin-left:auto; display:inline-flex; align-items:center; gap:6px;">' +
        link(shared, 'Edit in timeline',
             '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>') +
        link('/case/graph?cid=' + iris_ci_cid(), 'View in graph',
             '<line x1="6" x2="6" y1="3" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>') +
        '<button type="button" class="iris-ci-tl-flag" data-event-id="' +
        ev.event_id + '" title="' +
        (ev.event_is_flagged ? 'Unflag event' : 'Flag event') +
        '" style="background:transparent; border:none; padding:2px; cursor:pointer; display:inline-flex; color:' +
        (ev.event_is_flagged ? '#f4c430' : '#9a9aa5') + ';">' +
        icon('<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" x2="4" y1="22" y2="15"/>') +
        '</button>' +
        link(shared, 'Comments (opens the event in the timeline)',
             '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>') +
        link(shared, 'Open in timeline',
             '<circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/>') +
        '</span>';
}

function iris_ci_tl_card_html(ev) {
    /* the colour lands in a style attribute — validate, never interpolate
     * free text (CSS injection surface) */
    var raw = ev.event_color || '';
    var color = /^#[0-9a-fA-F]{3,8}$/.test(raw) ? raw : '#8B5CF6';
    var chips = (ev.assets || []).map(function (a) {
        var label = String(a.name || '').replace(/ \([^)]*\)$/, '');
        return '<span style="border:1px solid rgba(244,196,48,0.4); color:#f4c430; border-radius:8px; padding:0 8px; font-size:0.68rem;">&#128737; ' +
            iris_ci_esc(label) + '</span>';
    }).concat((ev.iocs || []).map(function (i) {
        return '<span style="border:1px solid rgba(242,89,97,0.4); color:#F25961; border-radius:8px; padding:0 8px; font-size:0.68rem;">&#9678; ' +
            iris_ci_esc(i.name) + '</span>';
    })).join(' ');
    return '<div style="display:flex; gap:10px; margin:8px 0;">' +
        '<span style="width:9px; height:9px; border-radius:50%; background:' +
        color + '; flex-shrink:0; margin-top:14px;"></span>' +
        '<div class="iris-ci-tlcard" style="flex:1 1 auto; min-width:0; background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06); border-left:3px solid ' +
        color + '; border-radius:10px; padding:8px 12px;">' +
        '<div style="display:flex; align-items:center; gap:8px;">' +
        '<code style="color:#8fa3ef; font-size:0.72rem;">' +
        iris_ci_esc(String(ev.event_date || '').slice(11, 19)) + '</code>' +
        '<span style="border:1px solid rgba(143,163,239,0.4); color:#8fa3ef; border-radius:8px; padding:0 8px; font-size:0.66rem;">' +
        iris_ci_esc(ev.category_name || 'Unspecified') + '</span>' +
        '<span class="text-muted" style="font-size:0.68rem;">#' +
        ev.event_id + '</span>' +
        iris_ci_tl_actions_html(ev) + '</div>' +
        '<div style="color:#e8e8ee; font-size:0.84rem; font-weight:600; margin-top:2px;">' +
        iris_ci_esc(ev.event_title) + '</div>' +
        (ev.event_content
            ? '<div style="color:#9a9aa5; font-size:0.74rem;">' +
              iris_ci_esc(String(ev.event_content).slice(0, 180)) + '</div>'
            : '') +
        (chips ? '<div style="margin-top:5px; display:flex; gap:5px; flex-wrap:wrap;">' +
            chips + '</div>' : '') +
        '</div></div>';
}

/* Same shape as the Assets tab's Timeline (deliberately identical, down to
 * the header actions, the centred date pills and the card layout) — the
 * only differences are what the events are matched on and the empty-state
 * wording. */
function iris_ci_tl_tab_html(rows) {
    var tlUrl = '/case/timeline?cid=' + iris_ci_cid();
    var html =
        '<div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">' +
        '<span style="color:#e8e8ee; font-weight:600; font-size:0.9rem;">Timeline</span>' +
        '<span class="text-muted" style="font-size:0.74rem;">' +
        rows.length + ' event' + (rows.length === 1 ? '' : 's') +
        '</span>' +
        '<span style="margin-left:auto; display:inline-flex; align-items:center; gap:10px;">' +
        /* opens the timeline page's REAL add-event modal IN PLACE (shared
           event_modal.js + a local container), this indicator preselected
           — the preset id is validated server-side */
        '<a class="iris-cshell-btn" style="text-decoration:none;" href="#" ' +
        'onclick="add_event(null, {ioc: ' + IRIS_CI.sel +
        '}); return false;">+ Add event</a>' +
        '<a style="color:#8fa3ef; font-size:0.76rem; text-decoration:none;" href="' +
        tlUrl + '">Open full timeline &rarr;</a></span></div>';
    if (!rows.length) {
        /* "we have not looked yet" and "we looked and found none" are
         * different claims — say which one this is */
        return html +
            '<div class="text-muted" style="font-size:0.8rem; padding:6px 0;">' +
            (IRIS_CI.tl === null
                ? 'Loading timeline&hellip;'
                : 'No timeline events reference this indicator.') +
            '</div>';
    }
    var days = {};
    var order = [];
    rows.slice().sort(function (a, b) {
        return String(a.event_date).localeCompare(String(b.event_date));
    }).forEach(function (ev) {
        var d = String(ev.event_date || '').slice(0, 10);
        if (!days[d]) { days[d] = []; order.push(d); }
        days[d].push(ev);
    });
    order.forEach(function (d) {
        html +=
            '<div style="display:flex; align-items:center; gap:10px; margin:10px 0 2px;">' +
            '<span style="flex:1; border-top:1px solid rgba(255,255,255,0.07);"></span>' +
            '<span style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0 10px; color:#c8c8d0; font-size:0.7rem; white-space:nowrap;">' +
            iris_ci_tl_daylabel(d) + '</span>' +
            '<span style="flex:1; border-top:1px solid rgba(255,255,255,0.07);"></span></div>' +
            days[d].map(iris_ci_tl_card_html).join('');
    });
    return html;
}

/* ---- Assets tab: the linked asset rendered as the SAME card the Assets
 * page shows in its list, not just a name.
 *
 * The link rows from /iocs/links carry only (asset_id, asset_name) — enough
 * to name the asset, not to describe it. The detail is joined from the case
 * asset catalog, fetched ONCE from the endpoint the Assets page itself
 * calls (/case/assets/filter — NOT /case/assets/list, which is the parallel
 * implementation). One round trip, no N+1, no schema change, and the card
 * is built from the same fields by the same logic, so the two surfaces
 * cannot drift.
 *
 * Until that catalog is in hand the card renders its head alone: a name we
 * know is not evidence of details that do not exist. */
var IRIS_CI_COMP = {
    0: {label: 'To be determined', cls: 'iris-ci-comp-0', color: '#9a9aa5'},
    1: {label: 'Compromised', cls: 'iris-ci-comp-1', color: '#F25961'},
    2: {label: 'Not compromised', cls: 'iris-ci-comp-2', color: '#2dce89'},
    3: {label: 'Unknown', cls: 'iris-ci-comp-3', color: '#9a9aa5'}
};

function iris_ci_load_assets() {
    if (IRIS_CI.assetCatFetching) return;
    if (IRIS_CI.assetCat !== null) return;
    IRIS_CI.assetCatFetching = true;
    fetch('/case/assets/filter?cid=' + iris_ci_cid(),
          {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (resp) {
            IRIS_CI.assetCatFetching = false;
            IRIS_CI.assetCat = ((resp && resp.data) || {}).assets || [];
            iris_ci_render_detail();
        })
        .catch(function () {
            IRIS_CI.assetCatFetching = false;
            IRIS_CI.assetCat = [];
            iris_ci_render_detail();
        });
}

function iris_ci_asset_full(assetId) {
    return (IRIS_CI.assetCat || []).find(function (a) {
        return a.asset_id === assetId;
    }) || null;
}

function iris_ci_comp(row) {
    return IRIS_CI_COMP[row.asset_compromise_status_id] || IRIS_CI_COMP[3];
}

function iris_ci_asset_type_name(row) {
    return (row.asset_type && row.asset_type.asset_name)
        ? row.asset_type.asset_name : (row.asset_type || '');
}

function iris_ci_asset_tags(row) {
    return String(row.asset_tags || '').split(',')
        .map(function (t) { return t.trim(); })
        .filter(function (t) { return t; });
}

function iris_ci_rowicon(paths, color, title) {
    return '<span title="' + iris_ci_esc(title) +
        '" style="color:' + color + '; display:inline-flex;">' +
        '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        paths + '</svg></span>';
}

function iris_ci_analysis_color(name) {
    var n = String(name || '').toLowerCase();
    if (n.indexOf('done') !== -1 || n.indexOf('complete') !== -1) {
        return '#2dce89';
    }
    if (n.indexOf('start') !== -1 || n.indexOf('progress') !== -1) {
        return '#8fa3ef';
    }
    if (n.indexOf('pending') !== -1 || n.indexOf('to be') !== -1) {
        return '#f4c430';
    }
    if (n.indexOf('cancel') !== -1) return '#7a7a85';
    return '#55555e';   /* unspecified — dim */
}

/* Indicator cluster, identical to the Assets list: compromise chip (or a
 * state icon), analysis clock coloured by status NAME, and an explicit
 * has-IOCs / no-IOCs mark — absence rendered, not omitted. */
function iris_ci_row_icons_html(r) {
    var out = '';
    var comp = iris_ci_comp(r);
    var compId = (r.asset_compromise_status_id === null
        || r.asset_compromise_status_id === undefined)
        ? 0 : r.asset_compromise_status_id;
    if (compId === 1) {
        out += '<span class="iris-ci-comp-chip ' + comp.cls +
            '" style="border-color:' + comp.color + '55; color:' +
            comp.color + ';">' + comp.label + '</span>';
    } else if (compId === 2) {
        out += iris_ci_rowicon(
            '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
            '#2dce89', 'Not compromised');
    } else if (compId === 3) {
        out += iris_ci_rowicon(
            '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" x2="12.01" y1="17" y2="17"/>',
            '#9a9aa5', 'Compromise: unknown');
    } else {
        out += iris_ci_rowicon(
            '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
            '#f4c430', 'Compromise: to be determined');
    }
    var ana = (r.analysis_status && r.analysis_status.name)
        ? r.analysis_status.name : 'Unspecified';
    out += iris_ci_rowicon(
        '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
        iris_ci_analysis_color(ana), 'Analysis: ' + ana);
    var nIocs = Array.isArray(r.ioc_links) ? r.ioc_links.length : 0;
    if (nIocs) {
        out += '<span title="' + nIocs + ' linked IOC' +
            (nIocs === 1 ? '' : 's') +
            '" style="color:#e08fb9; display:inline-flex; align-items:center; gap:3px; font-size:0.72rem;">' +
            '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m8 2 1.88 1.88"/><path d="M14.12 3.88 16 2"/><path d="M9 7.13v-1a3.003 3.003 0 1 1 6 0v1"/><path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6"/><path d="M12 20v-9"/><path d="M6.53 9C4.6 8.8 3 7.1 3 5"/><path d="M6 13H2"/><path d="M3 21c0-2.1 1.7-3.9 3.8-4"/><path d="M20.97 5c0 2.1-1.6 3.8-3.5 4"/><path d="M22 13h-4"/><path d="M17.2 17c2.1.1 3.8 1.9 3.8 4"/></svg><b>' +
            nIocs + '</b></span>';
    } else {
        out += iris_ci_rowicon(
            '<path d="m2 2 20 20"/><path d="M5 5a1 1 0 0 0-1 1v7c0 5 3.5 7.5 7.66 8.95a1 1 0 0 0 .67.01c2.35-.82 4.48-1.97 5.9-3.71"/><path d="M9.309 3.652A12.252 12.252 0 0 0 11.24 2.28a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1v7a9.784 9.784 0 0 1-.08 1.264"/>',
            '#55555e', 'No IOCs linked');
    }
    return '<span style="display:inline-flex; align-items:center; gap:7px; flex-shrink:0; margin-left:8px;">' +
        out + '</span>';
}

/* The card body — the same name / meta / tags / icon layout the Assets
 * list row builds, from the same fields. */
function iris_ci_asset_inner_html(r) {
    var meta = ['<span>' + iris_ci_esc(iris_ci_asset_type_name(r)) +
        '</span>'];
    if (r.asset_ip) {
        meta.push('<code>' + iris_ci_esc(r.asset_ip) + '</code>');
    }
    if (r.asset_domain) {
        meta.push('<code>' + iris_ci_esc(r.asset_domain) + '</code>');
    }
    if (r.asset_description) {
        meta.push('<span>' + iris_ci_esc(
            String(r.asset_description).slice(0, 60)) + '</span>');
    }
    var tags = iris_ci_asset_tags(r).slice(0, 6).map(function (t) {
        return '<span class="iris-ci-atag">' + iris_ci_esc(t) + '</span>';
    }).join('');
    return '<div style="display:flex; align-items:flex-start;">' +
        '<div style="flex:1 1 auto; min-width:0;">' +
        '<div class="iris-ci-aname">' + iris_ci_esc(r.asset_name) + '</div>' +
        '<div class="iris-ci-ameta">' + meta.join(' &middot; ') + '</div>' +
        (tags ? '<div>' + tags + '</div>' : '') +
        '</div>' + iris_ci_row_icons_html(r) +
        '</div>';
}

function iris_ci_asset_card_html(link) {
    var full = iris_ci_asset_full(link.asset_id);
    var comp = full ? iris_ci_comp(full) : IRIS_CI_COMP[0];
    var inner;
    if (full) {
        inner = iris_ci_asset_inner_html(full);
    } else {
        /* catalog not in hand — name what we know, claim nothing else */
        inner = '<div class="iris-ci-aname">' +
            iris_ci_esc(link.asset_name) + '</div>' +
            '<div class="iris-ci-ameta"><span>' +
            (IRIS_CI.assetCat === null
                ? 'Loading asset details&hellip;'
                : 'Details unavailable — the asset is no longer in this case.') +
            '</span></div>';
    }
    return '<a class="iris-ci-acard" href="/case/assets?cid=' +
        iris_ci_cid() + '&shared=' + link.asset_id +
        '" title="Open this asset on the Assets tab" style="border-left-color:' +
        comp.color + ';">' + inner +
        '<button type="button" class="iris-ci-aunlink" data-asset-id="' +
        link.asset_id + '" title="Unlink from this indicator" ' +
        'style="position:absolute; top:6px; right:8px; background:transparent; border:none; color:#7a7a85; cursor:pointer; font-size:0.9rem;">&times;</button>' +
        '<span class="iris-ci-aid">#' + link.asset_id + '</span></a>';
}

/* ---- Link an asset FROM the IOC side — the mirror of the Assets tab's
 * "Link IOC" menu. The link is OWNED by the asset (ioc_asset_link is
 * written by the asset update's ioc_links set), so linking from here
 * saves the CHOSEN ASSET through the same curated full-payload
 * /case/assets/update/<id> the Assets page uses — history entry, module
 * hooks and registry sync all run, and the two directions cannot drift. */

function iris_ci_asset_ioc_ids(a) {
    return (Array.isArray(a.ioc_links) ? a.ioc_links : [])
        .map(function (i) { return i.ioc_id; });
}

function iris_ci_refresh_after_link() {
    /* the tab's rows ride the bulk /iocs/links payload and the cards join
       the asset catalog — refetch both */
    IRIS_CI.assetCat = null;
    IRIS_CI.assetCatFetching = false;
    IRIS_CI.aMenu = false;
    iris_ci_load();
    iris_ci_load_assets();
}

function iris_ci_save_asset_links(a, ids) {
    var payload = {
        asset_name: a.asset_name,
        asset_type_id: a.asset_type_id,
        analysis_status_id: a.analysis_status_id,
        asset_ip: a.asset_ip || '',
        asset_domain: a.asset_domain || '',
        asset_info: a.asset_info || '',
        asset_description: a.asset_description || '',
        asset_tags: a.asset_tags || '',
        ioc_links: ids,
        csrf_token: iris_ci_csrf()
    };
    if (a.asset_compromise_status_id !== null
            && a.asset_compromise_status_id !== undefined) {
        payload.asset_compromise_status_id = a.asset_compromise_status_id;
    }
    fetch('/case/assets/update/' + a.asset_id + '?cid=' + iris_ci_cid(), {
        method: 'POST',
        headers: {'Accept': 'application/json',
                  'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    }).then(function (resp) { return resp.json(); })
        .then(function (resp) {
            if (resp && resp.status === 'success') {
                iris_ci_refresh_after_link();
            } else {
                window.alert((resp && resp.message) || 'Update failed');
            }
        })
        .catch(function () { window.alert('Update failed'); });
}

function iris_ci_link_asset(r, assetId) {
    var a = iris_ci_asset_full(assetId);
    if (!a) return;
    iris_ci_save_asset_links(a,
        iris_ci_asset_ioc_ids(a).concat([r.ioc_id]));
}

function iris_ci_unlink_asset(r, assetId) {
    var a = iris_ci_asset_full(assetId);
    if (!a) {
        /* the catalog row is the curated payload — without it a save
           would write fields we never read */
        window.alert('Asset details are still loading — try again.');
        return;
    }
    iris_ci_save_asset_links(a, iris_ci_asset_ioc_ids(a)
        .filter(function (id) { return id !== r.ioc_id; }));
}

function iris_ci_fetch_asset_types() {
    if (IRIS_CI.assetTypesCat !== null) return;
    IRIS_CI.assetTypesCat = [];   /* fetch in flight */
    fetch('/manage/asset-type/list?cid=' + iris_ci_cid(),
          {headers: {'Accept': 'application/json'}})
        .then(function (resp) { return resp.json(); })
        .then(function (resp) {
            IRIS_CI.assetTypesCat = (resp && resp.data) || [];
            if (IRIS_CI.aMenu) iris_ci_render_detail();
        })
        .catch(function () { /* the select shows loading */ });
}

function iris_ci_alink_menuitems_html(r) {
    var q = IRIS_CI.aMenuQ.toLowerCase();
    if (IRIS_CI.assetCat === null) {
        return '<div class="text-muted" style="padding:4px 12px; font-size:0.76rem;">Loading assets&hellip;</div>';
    }
    var linked = {};
    iris_ci_links_for(r).asset_links.forEach(function (l) {
        linked[l.asset_id] = true; });
    var cands = (IRIS_CI.assetCat || []).filter(function (a) {
        if (linked[a.asset_id]) return false;
        var hay = (String(a.asset_name || '') + ' ' +
            iris_ci_asset_type_name(a)).toLowerCase();
        return !q || hay.indexOf(q) !== -1;
    });
    if (!cands.length) {
        return '<div class="text-muted" style="padding:4px 12px; font-size:0.76rem;">' +
            (q ? 'No match.' : 'Every case asset is already linked.') +
            '</div>';
    }
    return cands.map(function (a) {
        return '<a href="#" class="iris-ci-alinkitem" data-asset-id="' +
            a.asset_id +
            '" style="display:block; padding:4px 12px; color:#c8c8d0; font-size:0.78rem; text-decoration:none;">' +
            iris_ci_esc(a.asset_name) +
            ' <span class="text-muted" style="font-size:0.68rem;">' +
            iris_ci_esc(iris_ci_asset_type_name(a)) + '</span></a>';
    }).join('');
}

function iris_ci_alink_menu_html(r) {
    if (!IRIS_CI.aMenu) return '';
    iris_ci_fetch_asset_types();
    var typeOpts = (IRIS_CI.assetTypesCat || []).map(function (t) {
        return '<option value="' + t.asset_id + '">' +
            iris_ci_esc(t.asset_name) + '</option>';
    }).join('');
    return '<div id="iris-ci-amenu" class="iris-cshell-menu" style="display:block; left:auto; right:0; min-width:260px; max-height:340px; overflow-y:auto;">' +
        '<div style="padding:4px 12px;"><input type="text" class="form-control form-control-sm" id="iris-ci-amenuq" placeholder="Filter assets..." autocomplete="off" value="' +
        iris_ci_esc(IRIS_CI.aMenuQ) + '"></div>' +
        '<div id="iris-ci-amenuitems">' + iris_ci_alink_menuitems_html(r) +
        '</div>' +
        '<div class="iris-cshell-mh">New asset</div>' +
        '<div style="padding:2px 12px 8px; display:flex; flex-direction:column; gap:5px;">' +
        '<input type="text" class="form-control form-control-sm" id="iris-ci-anewname" placeholder="Asset name" autocomplete="off">' +
        '<select class="form-control form-control-sm" id="iris-ci-anewtype">' +
        (typeOpts || '<option value="">Loading types&hellip;</option>') +
        '</select>' +
        '<button type="button" class="btn btn-sm btn-primary" id="iris-ci-anewbtn">Add &amp; link</button>' +
        '</div></div>';
}

/* the create path honours ioc_links (business/assets.py sets them on
 * create — the add-asset modal's own Related IOCs picker rides it), so
 * new-asset-and-link is a single POST */
function iris_ci_new_asset_and_link(r) {
    var nm = document.getElementById('iris-ci-anewname');
    var ty = document.getElementById('iris-ci-anewtype');
    if (!nm || !nm.value.trim() || !ty || !ty.value) return;
    fetch('/case/assets/add?cid=' + iris_ci_cid(), {
        method: 'POST',
        headers: {'Accept': 'application/json',
                  'Content-Type': 'application/json'},
        body: JSON.stringify({
            asset_name: nm.value.trim(),
            asset_type_id: parseInt(ty.value, 10),
            ioc_links: [r.ioc_id],
            csrf_token: iris_ci_csrf()})
    }).then(function (resp) { return resp.json(); })
        .then(function (resp) {
            if (resp && resp.status === 'success') {
                iris_ci_refresh_after_link();
            } else {
                window.alert((resp && resp.message) || 'Asset add failed');
            }
        })
        .catch(function () { window.alert('Asset add failed'); });
}

/* ---- Notes tab: read the note HERE instead of being sent to the Notes
 * page. Only this surface changes — the note pills on the IOC list rows and
 * every other note link in the product still deep-link, which is what an
 * analyst wants when they intend to EDIT.
 *
 * Content is rendered by the product's own markdown renderer
 * (`get_showdown_convert()` from common.js, loaded page-wide by
 * default_ext.html), so a note reads here exactly as it does on the Notes
 * page — headings and tables included. That matters: the analyst's notes are
 * structured markdown with named section headings and tables, which a
 * hand-rolled mini renderer would flatten. */
function iris_ci_note_ts(s) {
    /* stored naive UTC — format the STORED string, never re-zone it */
    var t = String(s || '').replace('T', ' ');
    return t ? t.slice(0, 16) + ' UTC' : '';
}

function iris_ci_note_md(text) {
    var conv = (typeof window !== 'undefined' &&
                typeof window.get_showdown_convert === 'function')
        ? window.get_showdown_convert()
        : (typeof get_showdown_convert === 'function'
            ? get_showdown_convert() : null);
    if (conv && typeof conv.makeHtml === 'function') {
        try { return conv.makeHtml(String(text || '')); } catch (e) { /* fall through */ }
    }
    return iris_ci_md(text);   /* fallback: the small local renderer */
}

function iris_ci_load_note(noteId) {
    if (IRIS_CI.notes[noteId] !== undefined) return;
    IRIS_CI.notes[noteId] = null;         /* null = fetch in flight */
    fetch('/case/notes/' + noteId + '?cid=' + iris_ci_cid(),
          {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (resp) {
            IRIS_CI.notes[noteId] = (resp && resp.data) || false;
            iris_ci_render_detail();
        })
        .catch(function () {
            IRIS_CI.notes[noteId] = false;   /* false = looked, failed */
            iris_ci_render_detail();
        });
}

function iris_ci_note_row_html(n) {
    var open = IRIS_CI.noteOpen === n.note_id;
    var title = n.note_title || ('note #' + n.note_id);
    var head =
        '<div class="iris-ci-noterow" data-note-id="' + n.note_id + '">' +
        '<span class="iris-ci-notechev">' + (open ? '&#9662;' : '&#9656;') +
        '</span>' +
        '<span class="iris-ci-notetitle">' + iris_ci_esc(title) + '</span>' +
        '<a class="iris-ci-noteopen" href="/case/notes?cid=' + iris_ci_cid() +
        '&shared=' + n.note_id +
        '" title="Open this note in the Notes tab (to edit it)">&nearr;</a>' +
        '</div>';
    if (!open) return '<div class="iris-ci-notewrap">' + head + '</div>';

    var note = IRIS_CI.notes[n.note_id];
    var inner;
    if (note === undefined || note === null) {
        /* nothing has come back yet — say so rather than showing an empty
           note, which would read as "this note has no content" */
        inner = '<div class="text-muted" style="font-size:0.78rem;">Loading the note&hellip;</div>';
    } else if (note === false) {
        inner = '<div style="color:#F25961; font-size:0.78rem;">Could not load this note.</div>';
    } else {
        var meta = [];
        if (note.note_user) meta.push(iris_ci_esc(note.note_user));
        var when = iris_ci_note_ts(note.note_lastupdate
            || note.note_creationdate);
        if (when) meta.push(when);
        inner =
            (meta.length
                ? '<div class="text-muted" style="font-size:0.7rem; margin-bottom:6px;">' +
                  meta.join(' &middot; ') + '</div>'
                : '') +
            '<div class="iris-ci-noteview">' +
            iris_ci_note_md(note.note_content) + '</div>';
    }
    return '<div class="iris-ci-notewrap open">' + head +
        '<div class="iris-ci-notebody">' + inner + '</div></div>';
}

/* ---- Cases tab: where else this indicator appears.
 *
 * Rows carry the case's own detail (state, severity, customer, owner, when
 * it opened or closed) rather than a name alone, and clicking one opens the
 * SHARED case-peek modal - the same tiles + safe-rendered summary the
 * war-room Cases tab shows, from the same builder and the same markup
 * include. Row detail rides the bulk /iocs/links payload (one query for
 * every linked case); the peek is fetched per click.
 *
 * Cross-case ACL is resolved server-side: the link list only names cases
 * this viewer may see, and /peek re-checks read access on the target. */
var IRIS_CI_SEV = {
    'critical': '#F25961', 'high': '#f4a34a', 'medium': '#f4c430',
    'low': '#2dce89', 'informational': '#8fa3ef'
};

function iris_ci_sev_color(name) {
    return IRIS_CI_SEV[String(name || '').toLowerCase()] || '#9a9aa5';
}

/* The case name usually already begins with "#<id> - " (escalation names
 * them that way), so only prefix the id when it is not already there —
 * "#5 · #5 - ..." reads like a bug. */
function iris_ci_case_title(cs) {
    var name = String(cs.name || cs.case_name || '');
    var id = String(cs.case_id);
    return /^#\s*/.test(name) && name.replace(/^#\s*/, '').indexOf(id) === 0
        ? name : ('#' + id + ' \u00b7 ' + name);
}

function iris_ci_case_card_html(cs) {
    var open = String(IRIS_CI.caseOpen) === String(cs.case_id);
    var meta = [];
    if (cs.client_name) meta.push(iris_ci_esc(cs.client_name));
    if (cs.soc_id) meta.push('SOC ' + iris_ci_esc(cs.soc_id));
    if (cs.owner_name) meta.push(iris_ci_esc(cs.owner_name));
    if (cs.open_date) {
        meta.push('opened ' + iris_ci_esc(String(cs.open_date).slice(0, 10)));
    }
    var chips = '';
    if (cs.close_date) {
        chips += '<span class="iris-ci-ccl" style="border-color:#55555e; color:#9a9aa5;">Closed</span>';
    } else if (cs.state_name) {
        chips += '<span class="iris-ci-ccl" style="border-color:rgba(45,206,137,0.5); color:#2dce89;">' +
            iris_ci_esc(cs.state_name) + '</span>';
    }
    if (cs.severity_name) {
        var col = iris_ci_sev_color(cs.severity_name);
        chips += '<span class="iris-ci-ccl" style="border-color:' + col +
            '55; color:' + col + ';">' + iris_ci_esc(cs.severity_name) +
            '</span>';
    }
    var head = '<div class="iris-ci-crow" data-case-id="' + cs.case_id +
        '" title="' + (open ? 'Collapse' : 'Click to see this case') + '">' +
        '<div style="display:flex; align-items:flex-start; gap:8px;">' +
        '<div style="flex:1 1 auto; min-width:0;">' +
        '<div class="iris-ci-cname">' +
        '<span class="iris-ci-cchev">' + (open ? '&#9662;' : '&#9656;') +
        '</span> ' + iris_ci_esc(iris_ci_case_title(cs)) + '</div>' +
        (meta.length
            ? '<div class="iris-ci-cmeta">' + meta.join(' &middot; ') + '</div>'
            : '') +
        '</div>' +
        (chips ? '<span style="flex-shrink:0; display:inline-flex; gap:5px;">' +
            chips + '</span>' : '') +
        '</div></div>';
    if (!open) {
        return '<div class="iris-ci-ccard">' + head + '</div>';
    }
    return '<div class="iris-ci-ccard open">' + head +
        '<div class="iris-ci-cbody">' +
        iris_ci_case_detail_html(cs.case_id) + '</div></div>';
}

/* The case rendered IN the panel — same tiles and summary the war-room
 * popup shows, from the same /peek payload, just not behind a modal. */
function iris_ci_case_detail_html(caseId) {
    var p = IRIS_CI.peeks[caseId];
    if (p === undefined || p === null) {
        return '<div class="text-muted" style="font-size:0.78rem;">Loading the case&hellip;</div>';
    }
    if (p === false) {
        return '<div style="color:#F25961; font-size:0.78rem;">Could not load this case.</div>';
    }
    var tile = function (lbl, val) {
        return '<div class="iris-ci-pk-tile"><div class="iris-ci-pk-lbl">' +
            lbl + '</div><div class="iris-ci-pk-val">' +
            (val === null || val === undefined || val === ''
                ? '\u2014' : iris_ci_esc(String(val))) + '</div></div>';
    };
    var tags = (p.tags || []).filter(function (t) {
        return String(t || '').trim();
    });
    var html = '<div class="iris-ci-pk-grid">' +
        tile('State', p.close_date ? 'Closed' : (p.state_name || 'Open')) +
        tile('Severity', p.severity_name) +
        tile('Customer', p.client_name) +
        tile('Owner', p.owner_name) +
        tile('Opened', p.open_date) +
        tile('Closed', p.close_date || 'Still open') +
        tile('Reviewer', p.reviewer_name || 'Unassigned') +
        '<div class="iris-ci-pk-tile" style="grid-column: span 2;">' +
        '<div class="iris-ci-pk-lbl">Tags</div><div class="iris-ci-pk-val">' +
        (tags.length
            ? tags.map(function (t) {
                return '<span class="iris-ci-tag">' + iris_ci_esc(t) +
                    '</span>';
            }).join(' ')
            : '<span class="text-muted">none</span>') +
        '</div></div></div>';
    html += '<div class="text-muted mt-2" style="font-size:0.62rem; letter-spacing:0.08em;">SUMMARY</div>' +
        '<div class="iris-ci-noteview iris-ci-pk-summary">' +
        /* already sanitised server-side by render_markdown_safe */
        (p.description_html
            || '<span class="text-muted" style="font-size:0.8rem;">No description on this case.</span>') +
        '</div>';
    html += '<div style="margin-top:8px;"><a class="iris-cshell-btn" ' +
        'style="text-decoration:none;" href="/case?cid=' + p.case_id +
        '">Open case &rarr;</a></div>';
    return html;
}

/* Fetched on first expand and cached. undefined = never asked,
 * null = in flight, false = looked and failed — an empty panel would read
 * as "this case has nothing in it". */
function iris_ci_load_case_peek(caseId) {
    if (IRIS_CI.peeks[caseId] !== undefined) return;
    IRIS_CI.peeks[caseId] = null;
    fetch('/api/v2/cases/' + caseId + '/peek',
          {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
        .then(function (r) {
            if (!r.ok) throw new Error(r.status);
            return r.json();
        })
        .then(function (p) {
            IRIS_CI.peeks[caseId] = p;
            iris_ci_render_detail();
        })
        .catch(function () {
            IRIS_CI.peeks[caseId] = false;
            iris_ci_render_detail();
        });
}

/* ---- Intel tab: enrichment written by modules, plus a control to run
 * them on demand.
 *
 * Nothing is re-queried from VirusTotal or MISP here — modules own that.
 * VT writes a rendered report into the IOC's custom_attributes via
 * add_tab_attribute_field, and IrisMISPSync records what it published in
 * misp_attribute_link; this tab surfaces both. "Run enrichment" fires the
 * SAME on_manual_trigger_ioc path as the legacy table's quick-actions,
 * through common.js's init_module_processing — those actions were only
 * reachable from the legacy table before. */
function iris_ci_load_mod_options() {
    if (IRIS_CI.modOpts !== null) return;
    IRIS_CI.modOpts = [];
    fetch('/dim/hooks/options/ioc/list',
          {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (resp) {
            IRIS_CI.modOpts = (resp && resp.data) || [];
            iris_ci_render_detail();
        })
        .catch(function () { IRIS_CI.modOpts = []; });
}

function iris_ci_run_module(r, idx) {
    var o = (IRIS_CI.modOpts || [])[idx];
    if (!o || typeof window.init_module_processing !== 'function') return;
    IRIS_CI.modMenu = false;
    window.init_module_processing([r.ioc_id], o.hook_name,
                                  o.manual_hook_ui_name, o.module_name,
                                  'ioc');
    iris_ci_render_detail();
}

function iris_ci_intel_tab_html(r) {
    iris_ci_load_mod_options();
    var opts = IRIS_CI.modOpts || [];
    var menu = '';
    if (IRIS_CI.modMenu) {
        menu = '<div class="iris-cshell-menu" id="iris-ci-modmenu" style="display:block; left:auto; right:0; min-width:240px;">' +
            (opts.length
                ? opts.map(function (o, i) {
                    return '<a href="#" class="iris-ci-modrun" data-idx="' + i +
                        '">' + iris_ci_esc(o.manual_hook_ui_name ||
                                           o.module_name) + '</a>';
                }).join('')
                : '<div class="text-muted" style="font-size:0.72rem; padding:4px 12px;">No module exposes a manual action for indicators.</div>') +
            '</div>';
    }
    var out = '<div style="display:flex; align-items:center; gap:8px; margin-bottom:10px;">' +
        '<span style="color:#9a9aa5; font-size:0.74rem;">Enrichment recorded by modules</span>' +
        '<div class="iris-cshell-menuwrap" style="margin-left:auto;">' +
        '<button type="button" class="iris-cshell-btn" id="iris-ci-modbtn">Run enrichment &#9662;</button>' +
        menu + '</div></div>';

    /* --- module reports (custom_attributes tabs) --- */
    var attrs = r.custom_attributes || {};
    var tabs = Object.keys(attrs);
    if (tabs.length) {
        tabs.forEach(function (tab) {
            var fields = attrs[tab] || {};
            var inner = Object.keys(fields).map(function (fname) {
                var f = fields[fname] || {};
                var v = f.value;
                if (v === null || v === undefined || v === '') return '';
                /* Module-authored HTML is rendered as-is, exactly as the IOC
                   modal already does. Modules are admin-installed and run
                   server-side, so they are inside the trust boundary; analyst
                   and model text never reaches this path. */
                if (f.type === 'html' || f.type === 'raw') {
                    return '<div class="iris-ci-intel-html">' + v + '</div>';
                }
                return '<div style="font-size:0.76rem; color:#c8c8d0; margin-bottom:3px;">' +
                    '<span style="color:#7a7a85;">' + iris_ci_esc(fname) +
                    '</span> ' + iris_ci_esc(String(v)) + '</div>';
            }).join('');
            if (!inner) return;
            out += '<div class="iris-ci-intel-block">' +
                '<div class="iris-ci-intel-h">' + iris_ci_esc(tab) + '</div>' +
                inner + '</div>';
        });
    }

    /* --- MISP publication state --- */
    var misp = iris_ci_links_for(r).misp;
    out += '<div class="iris-ci-intel-block">' +
        '<div class="iris-ci-intel-h">MISP</div>' +
        (misp
            ? '<div style="font-size:0.76rem; color:#c8c8d0;">Published as attribute <code style="color:#8fa3ef;">' +
              iris_ci_esc(misp.attribute_id) + '</code>' +
              (misp.attribute_uuid ? ' <span class="text-muted" style="font-size:0.68rem;">' +
                  iris_ci_esc(misp.attribute_uuid) + '</span>' : '') +
              '<br>on event <code style="color:#8fa3ef;">' +
              iris_ci_esc(misp.event_id) + '</code>' +
              (misp.last_synced_at
                  ? ' <span class="text-muted" style="font-size:0.68rem;">last synced ' +
                    iris_ci_esc(String(misp.last_synced_at)
                        .replace('T', ' ').slice(0, 16)) + '</span>' : '') +
              '</div>'
            : '<div class="text-muted" style="font-size:0.76rem;">Not published to MISP.</div>') +
        '</div>';

    if (!tabs.length) {
        out += '<div class="text-muted" style="font-size:0.76rem; margin-top:10px;">' +
            'No module has written enrichment for this indicator yet. ' +
            'Run enrichment above, or configure a module under Manage &rsaquo; Modules.' +
            '</div>';
    }
    return out;
}

function iris_ci_load_comments(iocId) {
    fetch('/case/ioc/' + iocId + '/comments/list?cid=' + iris_ci_cid(),
          {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (resp) {
            IRIS_CI.comments[iocId] = (resp && resp.data) || [];
            iris_ci_render_detail();
        })
        .catch(function () {
            IRIS_CI.comments[iocId] = [];
            iris_ci_render_detail();
        });
}

function iris_ci_post_comment(iocId) {
    var input = document.getElementById('iris-ci-comment-input');
    if (!input || !input.value.trim()) return;
    var csrf = iris_ci_csrf();
    fetch('/case/ioc/' + iocId + '/comments/add?cid=' + iris_ci_cid(), {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
        body: JSON.stringify({comment_text: input.value.trim(),
                              csrf_token: csrf})
    }).then(function () {
        IRIS_CI.comments[iocId] = undefined;
        iris_ci_load_comments(iocId);
    });
}

function iris_ci_visible() {
    var q = IRIS_CI.q;
    if (!q) return IRIS_CI.rows;
    return IRIS_CI.rows.filter(function (r) {
        var l = iris_ci_links_for(r);
        var hay = [r.ioc_value, iris_ci_type(r), r.ioc_description,
                   r.ioc_tags, iris_ci_tlp(r),
                   (l.note_links || []).map(function (n) {
                       return n.note_title; }).join(' '),
                   (l.asset_links || []).map(function (a) {
                       return a.asset_name; }).join(' ')]
            .join(' ').toLowerCase();
        return hay.indexOf(q) !== -1;
    });
}

/* ---------------------------------------------------------------- CSV export

   The header and the field shapes below are the IMPORT contract, not a
   presentation choice: `case_upload_ioc` hardcodes
   'ioc_value,ioc_type,ioc_description,ioc_tags,ioc_tlp' and compares the first
   line against it, resolves ioc_type by NAME (lowercased) and ioc_tlp against
   the tlp table's own names, and reformats tags with .replace('|', ','), so
   tags travel PIPE-separated. Exporting anything else would produce a file the
   product's own importer cannot read.

   All five columns are emitted for every row even when empty. A short row is
   worse than it looks: the endpoint's missing-field check `continue`s the
   INNER loop over header names, so the row is not skipped and the next
   statement calls .replace() on None — a short row raises rather than being
   reported as a per-row error. (Pre-existing; not this change's to fix.)  */

const IRIS_CI_CSV_HEADER = 'ioc_value,ioc_type,ioc_description,ioc_tags,ioc_tlp';

/* Cell escaping lives in common.js (iris_csv_cell) so this export and the
   asset export cannot drift apart on quoting or newline handling. */
function iris_ci_csv_rows(rows) {
    var out = [IRIS_CI_CSV_HEADER];
    rows.forEach(function (r) {
        out.push([
            iris_csv_cell(r.ioc_value),
            iris_csv_cell(iris_ci_type(r)),
            iris_csv_cell(r.ioc_description),
            iris_csv_cell(iris_ci_tags(r).join('|')),
            iris_csv_cell(iris_ci_tlp(r))
        ].join(','));
    });
    return out.join('\n');
}

function iris_ci_export_csv() {
    var rows = iris_ci_visible();
    /* A header-only file would be indistinguishable from a broken export, so
       say which of the two happened rather than handing over an empty CSV. */
    if (!rows.length) {
        notify_error(IRIS_CI.q
            ? 'No indicators match the current search — nothing to export.'
            : 'This case has no indicators to export.');
        return;
    }
    var name = 'case-' + iris_ci_cid() + '-iocs'
        + (IRIS_CI.q ? '-filtered' : '') + '.csv';
    download_file(name, 'text/csv', iris_ci_csv_rows(rows));

    /* The filter is named in the FILENAME, not only in this notification — a
       partial export outlives the toast that described it. */
    var msg = rows.length + ' indicator' + (rows.length === 1 ? '' : 's')
        + ' exported' + (IRIS_CI.q ? ' (search filter applied)' : '') + '.';
    var flattened = rows.filter(function (r) {
        return /[\r\n]/.test(String(r.ioc_description || '')); }).length;
    if (flattened) {
        msg += ' ' + flattened + ' description'
            + (flattened === 1 ? '' : 's')
            + ' flattened to a single line for CSV.';
    }
    notify_success(msg);
}

function iris_ci_render_list() {
    var box = document.getElementById('iris-ci-list');
    if (!box) return;
    var rows = iris_ci_visible();
    var cnt = document.getElementById('iris-ci-count');
    if (cnt) cnt.textContent = '(' + rows.length + ')';
    if (!rows.length) {
        box.innerHTML = '<div class="text-muted" style="font-size:0.82rem; padding:14px 2px;">' +
            (IRIS_CI.q ? 'No indicators match the search.'
                       : 'No indicators recorded in this case.') + '</div>';
        return;
    }
    box.innerHTML = rows.map(function (r) {
        var l = iris_ci_links_for(r);
        var tags = iris_ci_tags(r);
        var chips = (l.note_links || []).slice(0, 2).map(function (n) {
            return '<span class="iris-ci-notepill" title="' +
                iris_ci_esc(n.note_title) + '">&#128221; ' +
                iris_ci_esc(String(n.note_title || 'note').slice(0, 20)) +
                '</span>';
        }).join('');
        return '<div class="iris-ci-row' +
            (IRIS_CI.sel === r.ioc_id ? ' active' : '') +
            '" data-ioc-id="' + r.ioc_id + '">' +
            '<div style="display:flex; align-items:flex-start; gap:8px;">' +
            '<div style="flex:1 1 auto; min-width:0;">' +
            '<div class="iris-ci-val">' + iris_ci_esc(r.ioc_value) + '</div>' +
            '<div class="iris-ci-meta">' +
            '<span>' + iris_ci_esc(iris_ci_type(r)) + '</span>' +
            (r.ioc_description
                ? '<span>&middot;</span><span>' +
                  iris_ci_esc(String(r.ioc_description).slice(0, 90)) +
                  '</span>' : '') +
            '</div>' +
            (tags.length || chips
                ? '<div style="margin-top:4px; display:flex; gap:4px; flex-wrap:wrap; align-items:center;">' +
                  tags.map(function (t) {
                      return '<span class="iris-ci-tag">' +
                          iris_ci_esc(t) + '</span>'; }).join('') +
                  chips + '</div>' : '') +
            '</div>' +
            '<div style="flex-shrink:0; display:flex; align-items:center; gap:6px;">' +
            ((r.link && r.link.length)
                ? '<span class="iris-ci-xcase" title="Also appears in ' +
                  r.link.length + ' other case' +
                  (r.link.length === 1 ? '' : 's') + '">&#128279; ' +
                  r.link.length + '</span>' : '') +
            iris_ci_tlp_badge(iris_ci_tlp(r)) +
            '</div></div></div>';
    }).join('');
}

function iris_ci_md(md) {
    /* render on the ESCAPED string — model output is never trusted HTML */
    var s = iris_ci_esc(String(md || '')).replace(/\r\n/g, '\n');
    s = s.replace(/`([^`\n]+)`/g,
        '<code style="background:rgba(255,255,255,0.06); padding:0 4px; border-radius:3px;">$1</code>');
    s = s.replace(/\*\*([^*\n]+)\*\*/g, '<b style="color:#e8e8ee;">$1</b>');
    return s.split(/\n{2,}/).map(function (p) {
        var lines = p.split('\n').filter(function (l) { return l.trim(); });
        if (!lines.length) return '';
        if (lines.every(function (l) { return /^\s*[-*]\s+/.test(l); })) {
            return '<ul style="margin:4px 0 8px 18px; padding:0;">' +
                lines.map(function (l) {
                    return '<li>' + l.replace(/^\s*[-*]\s+/, '') + '</li>';
                }).join('') + '</ul>';
        }
        return '<p style="margin:0 0 8px;">' + lines.join('<br>') + '</p>';
    }).join('');
}

function iris_ci_profile_fetch(r) {
    if (IRIS_CI.profiles[r.ioc_id]) return;
    IRIS_CI.profiles[r.ioc_id] = {state: 'loading'};
    fetch('/api/v2/cases/' + iris_ci_cid() + '/ai/iocs/' + r.ioc_id +
          '/profile', {credentials: 'same-origin',
                       headers: {'Accept': 'application/json'}})
        .then(function (resp) {
            if (resp.status === 404) return null;
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.json();
        })
        .then(function (art) {
            IRIS_CI.profiles[r.ioc_id] = art
                ? {state: 'ok', art: art, cached: true} : {state: 'none'};
            iris_ci_render_detail();
        })
        .catch(function () {
            IRIS_CI.profiles[r.ioc_id] = {state: 'none'};
            iris_ci_render_detail();
        });
}

function iris_ci_profile_gen(r, force) {
    var csrf = iris_ci_csrf();
    IRIS_CI.profiles[r.ioc_id] = {state: 'busy'};
    iris_ci_render_detail();
    fetch('/api/v2/cases/' + iris_ci_cid() + '/ai/iocs/' + r.ioc_id +
          '/profile' + (force ? '?force=true' : ''), {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
        body: JSON.stringify({csrf_token: csrf})
    }).then(function (resp) {
        return resp.json().then(function (j) {
            return {ok: resp.ok, status: resp.status, json: j}; });
    }).then(function (res) {
        if (!res.ok) {
            throw new Error((res.json && res.json.message)
                || ('HTTP ' + res.status));
        }
        IRIS_CI.profiles[r.ioc_id] = {state: 'ok', art: res.json,
                                      cached: false};
        iris_ci_render_detail();
    }).catch(function (e) {
        IRIS_CI.profiles[r.ioc_id] = {state: 'error',
                                      error: (e.message || String(e))};
        iris_ci_render_detail();
    });
}

function iris_ci_short_err(msg) {
    /* Upstream backends return whole JSON envelopes (rate-limit payloads run
       to several hundred characters). Show the readable head and keep the
       full text in the title, rather than filling the panel with noise. */
    var s = String(msg || '').replace(/\s+/g, ' ').trim();
    var m = s.match(/"message"\s*:\s*"([^"]{8,})"/);
    if (m) s = m[1];
    return s.length > 180 ? s.slice(0, 180) + '…' : s;
}

function iris_ci_profile_html(r) {
    var st = IRIS_CI.profiles[r.ioc_id];
    if (!st || st.state === 'loading') return '';
    if (st.state === 'busy') {
        return '<div class="iris-ci-prof"><div class="iris-ci-prof-h">&#x2728; Indicator profile</div>' +
            '<div class="text-muted" style="font-size:0.78rem;">Reading the indicator and everything linked to it&hellip;</div></div>';
    }
    if (st.state === 'none') {
        return '<div class="iris-ci-prof"><div class="iris-ci-prof-h">&#x2728; Indicator profile</div>' +
            '<div class="text-muted" style="font-size:0.78rem;">No profile yet. ' +
            '<a href="#" class="iris-ci-prof-gen" style="color:#a78bfa;">Generate one</a> ' +
            'from this indicator, the cases it appears in, and the notes, assets and events tied to it.</div></div>';
    }
    if (st.state === 'error') {
        return '<div class="iris-ci-prof"><div class="iris-ci-prof-h">&#x2728; Indicator profile</div>' +
            '<div style="font-size:0.78rem; color:#fca5a5;" title="' +
            iris_ci_esc(st.error) + '">Could not generate: ' +
            iris_ci_esc(iris_ci_short_err(st.error)) +
            '</div><div style="margin-top:6px;">' +
            '<a href="#" class="iris-ci-prof-gen" style="color:#a78bfa; font-size:0.74rem;">Try again</a></div></div>';
    }
    var a = st.art || {};
    var when = String(a.generated_at || '').replace('T', ' ').slice(0, 16);
    return '<div class="iris-ci-prof">' +
        '<div class="iris-ci-prof-h">&#x2728; Indicator profile</div>' +
        '<div class="iris-ci-prof-body">' +
        iris_ci_md(a.content || a.ai_content || '') + '</div>' +
        '<div class="iris-ci-prof-f">' +
        iris_ci_esc([a.model, a.prompt_id, when].filter(Boolean).join(' · ')) +
        (st.cached ? ' · cached' : '') +
        ' &middot; <a href="#" class="iris-ci-prof-rerun" style="color:#a78bfa;">Re-run</a></div></div>';
}

/* ---- Inline editing (v3): Edit IOC flips Details into a form and swaps
 * the header buttons for Cancel / Save Changes.
 *
 * Unlike the asset update path, iocs_update() loads with partial=True, so
 * only the edited fields are sent — custom attributes and everything else
 * are untouched by omission. The save goes through the SAME
 * PUT /api/v2/cases/<cid>/iocs/<id> the modal uses, so history, hooks and
 * validation all run. The modal stays reachable as "Full editor" for
 * custom attributes and the markdown preview.
 */
function iris_ci_fetch_edit_catalogs() {
    if (IRIS_CI.iocTypes === null) {
        IRIS_CI.iocTypes = [];
        fetch('/manage/ioc-types/list', {credentials: 'same-origin',
                                         headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.json(); })
            .then(function (d) {
                IRIS_CI.iocTypes = (d && d.data) || [];
                iris_ci_render_detail();
            }).catch(function () { IRIS_CI.iocTypes = []; });
    }
    if (IRIS_CI.tlps === null) {
        IRIS_CI.tlps = [];
        fetch('/manage/tlp/list', {credentials: 'same-origin',
                                   headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.json(); })
            .then(function (d) {
                IRIS_CI.tlps = (d && d.data) || [];
                iris_ci_render_detail();
            }).catch(function () { IRIS_CI.tlps = []; });
    }
}

function iris_ci_select_html(id, options, selected) {
    return '<select class="form-control form-control-sm" id="' + id + '">' +
        options.map(function (o) {
            return '<option value="' + o[0] + '"' +
                (String(o[0]) === String(selected) ? ' selected' : '') + '>' +
                iris_ci_esc(o[1]) + '</option>';
        }).join('') + '</select>';
}

function iris_ci_lbl(t) {
    return '<div style="color:#9a9aa5; font-size:0.66rem; letter-spacing:0.08em; text-transform:uppercase; margin-bottom:4px;">' +
        t + '</div>';
}

function iris_ci_edit_form_html(r) {
    var types = (IRIS_CI.iocTypes || []).map(function (t) {
        return [t.type_id, t.type_name]; });
    var tlps = (IRIS_CI.tlps || []).map(function (t) {
        return [t.tlp_id, t.tlp_name]; });
    var curType = (r.ioc_type && r.ioc_type.type_id) || r.ioc_type_id;
    var curTlp = (r.tlp && r.tlp.tlp_id) || r.ioc_tlp_id;
    return '<div style="display:grid; grid-template-columns:1fr 1fr; gap:10px 14px;">' +
        '<div>' + iris_ci_lbl('Type *') +
        iris_ci_select_html('iris-ci-f-type', types, curType) + '</div>' +
        '<div>' + iris_ci_lbl('TLP *') +
        iris_ci_select_html('iris-ci-f-tlp', tlps, curTlp) + '</div>' +
        '</div>' +
        '<div style="margin-top:10px;">' + iris_ci_lbl('IOC value *') +
        '<textarea class="form-control form-control-sm" id="iris-ci-f-value" rows="2">' +
        iris_ci_esc(r.ioc_value || '') + '</textarea></div>' +
        '<div style="margin-top:10px;">' + iris_ci_lbl('Description') +
        '<textarea class="form-control form-control-sm" id="iris-ci-f-desc" rows="4">' +
        iris_ci_esc(r.ioc_description || '') + '</textarea></div>' +
        '<div style="margin-top:10px;">' +
        iris_ci_lbl('Tags' + iris_ci_tagsugg_pill_html(r)) +
        '<input type="text" class="form-control form-control-sm" id="iris-ci-f-tags" value="' +
        iris_ci_esc(r.ioc_tags || '') + '" placeholder="Add a tag..." autocomplete="off">' +
        iris_ci_tagsugg_results_html(r) + '</div>' +
        '<div style="margin-top:10px;">' +
        '<a href="#" class="iris-ci-fulledit" style="color:#8fa3ef; font-size:0.74rem;">Full editor (custom attributes, markdown preview) &nearr;</a>' +
        '</div>';
}

function iris_ci_init_tag_widget() {
    var el = document.getElementById('iris-ci-f-tags');
    if (!el || el.getAttribute('data-iris-tagged') === '1') return;
    if (typeof window.set_suggest_tags !== 'function' || !window.jQuery
        || !window.jQuery.fn || !window.jQuery.fn.amsifySuggestags) return;
    el.setAttribute('data-iris-tagged', '1');
    window.set_suggest_tags('iris-ci-f-tags');
}

function iris_ci_read_tags() {
    var el = document.getElementById('iris-ci-f-tags');
    if (!el) return '';
    var parts = String(el.value || '').split(',');
    var area = el.nextElementSibling;
    var pending = area
        ? area.querySelector('.amsify-suggestags-input') : null;
    if (pending && pending.value) {
        parts = parts.concat(pending.value.split(','));
    }
    var seen = {};
    return parts.map(function (t) { return t.trim(); })
        .filter(function (t) {
            if (!t || seen[t]) return false;
            seen[t] = 1;
            return true;
        }).join(',');
}

function iris_ci_save_edit(r) {
    var val = function (id) {
        var el = document.getElementById(id);
        return el ? el.value : '';
    };
    var value = val('iris-ci-f-value').trim();
    if (!value) { window.alert('IOC value is required'); return; }
    var csrf = iris_ci_csrf();
    var body = {
        ioc_value: value,
        ioc_type_id: parseInt(val('iris-ci-f-type'), 10),
        ioc_tlp_id: parseInt(val('iris-ci-f-tlp'), 10),
        ioc_description: val('iris-ci-f-desc'),
        ioc_tags: iris_ci_read_tags(),
        csrf_token: csrf
    };
    fetch('/api/v2/cases/' + iris_ci_cid() + '/iocs/' + r.ioc_id, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
        body: JSON.stringify(body)
    }).then(function (resp) {
        return resp.json().then(function (j) {
            return {ok: resp.ok, json: j, status: resp.status}; });
    }).then(function (res) {
        if (!res.ok) {
            throw new Error((res.json && res.json.message)
                || ('HTTP ' + res.status));
        }
        IRIS_CI.editing = false;
        /* the edit may have changed what the profile was built from */
        delete IRIS_CI.profiles[r.ioc_id];
        iris_ci_load();
    }).catch(function (e) {
        /* deliberately no re-render: the analyst's typed values survive
           so they can correct and retry */
        window.alert('Could not save: ' + (e.message || e));
    });
}

/* ---- AI tag suggester (same shared endpoint the modals use) ---- */
function iris_ci_tagsugg_state(r) {
    var st = IRIS_CI.tagSugg;
    return (st && r && st.iocId === r.ioc_id) ? st : null;
}

function iris_ci_tagsugg_pill_html(r) {
    var st = iris_ci_tagsugg_state(r) || {};
    return ' <button type="button" id="iris-ci-tagsugg-pill" ' +
        'title="Ask the AI for MISP taxonomy + galaxy tags based on this indicator" ' +
        'style="background:rgba(139,92,246,0.18); border:1px solid rgba(139,92,246,0.45); color:#d4c4ff; font-size:10px; line-height:1; padding:2px 7px; border-radius:999px; cursor:pointer; text-transform:none; letter-spacing:0;"' +
        (st.busy ? ' disabled' : '') + '>&#x2728; Suggest tags</button>' +
        '<span id="iris-ci-tagsugg-status" style="font-size:10px; margin-left:6px; text-transform:none; letter-spacing:0; color:' +
        (st.statusColor || '#94a3b8') + ';">' +
        iris_ci_esc(st.status || '') + '</span>';
}

function iris_ci_tagsugg_results_html(r) {
    var st = iris_ci_tagsugg_state(r);
    if (!st || !st.items) return '';
    if (!st.items.length) {
        return '<div style="margin-top:6px; font-size:11px; color:#94a3b8;">No high-confidence suggestions.</div>';
    }
    var chips = st.items.map(function (s) {
        var c = (s.kind === 'galaxy')
            ? ['rgba(245,158,11,0.12)', 'rgba(245,158,11,0.35)', '#fbbf24']
            : ['rgba(139,92,246,0.12)', 'rgba(139,92,246,0.35)', '#d4c4ff'];
        var taken = st.accepted && st.accepted[s.tag];
        var conf = (typeof s.confidence === 'number')
            ? Math.round(s.confidence * 100) + '%' : '';
        return '<button type="button" class="iris-ci-tagsugg-chip" data-tag="' +
            iris_ci_esc(s.tag) + '" title="' +
            iris_ci_esc(s.reason || s.expanded || '') + '" style="background:' +
            c[0] + '; border:1px solid ' + c[1] + '; color:' + c[2] +
            '; font-size:11px; padding:3px 10px; border-radius:999px; cursor:pointer; display:inline-flex; align-items:center; gap:6px;' +
            (taken ? ' opacity:0.45; pointer-events:none;' : '') + '">' +
            (taken ? '&#10003;' : '+') +
            ' <code style="background:transparent; color:inherit; font-size:11px; padding:0;">' +
            iris_ci_esc(s.tag) + '</code><span style="font-size:9px; opacity:0.7;">' +
            iris_ci_esc(conf) + '</span></button>';
    }).join('');
    return '<div style="margin-top:8px; padding:8px 10px; background:#15151a; border:1px solid rgba(139,92,246,0.35); border-radius:8px;">' +
        '<div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center;">' +
        '<span style="font-size:11px; color:#94a3b8; margin-right:4px;">Suggested:</span>' +
        chips + '<button type="button" id="iris-ci-tagsugg-all" class="btn btn-sm btn-link" style="font-size:11px; padding:0 8px; color:#a78bfa;">+ add all</button>' +
        '</div></div>';
}

function iris_ci_tagsugg_add(tag) {
    var el = document.getElementById('iris-ci-f-tags');
    if (!el) return false;
    var area = el.nextElementSibling;
    var vis = area ? area.querySelector('.amsify-suggestags-input') : null;
    if (!vis || !window.jQuery) {
        var cur = String(el.value || '').split(',')
            .map(function (t) { return t.trim(); }).filter(Boolean);
        if (cur.indexOf(tag) === -1) cur.push(tag);
        el.value = cur.join(',');
        return true;
    }
    var $v = window.jQuery(vis);
    $v.val(tag).focus();
    $v.trigger(window.jQuery.Event('keyup',
        {keyCode: 13, which: 13, key: 'Enter'}));
    return true;
}

function iris_ci_tagsugg_run(r) {
    var csrf = iris_ci_csrf();
    IRIS_CI.tagSugg = {iocId: r.ioc_id, busy: true, items: null, accepted: {},
                       status: 'Asking the model...', statusColor: '#a78bfa'};
    iris_ci_render_detail();
    fetch('/api/v2/cases/' + iris_ci_cid() + '/ai/tag-suggestion', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
        body: JSON.stringify({object_type: 'ioc', object_id: r.ioc_id,
                              csrf_token: csrf})
    }).then(function (resp) {
        return resp.json().then(function (j) {
            return {ok: resp.ok, status: resp.status, json: j}; });
    }).then(function (res) {
        if (!res.ok) {
            throw new Error((res.json && res.json.message)
                || ('HTTP ' + res.status));
        }
        var d = res.json || {};
        var items = d.suggestions || [];
        IRIS_CI.tagSugg = {
            iocId: r.ioc_id, busy: false, items: items, accepted: {},
            status: items.length
                ? '(' + items.length + ' suggestion' +
                  (items.length === 1 ? '' : 's') + ')'
                : '(no suggestions above 0.5 confidence)',
            statusColor: '#94a3b8'};
        iris_ci_render_detail();
    }).catch(function (e) {
        IRIS_CI.tagSugg = {iocId: r.ioc_id, busy: false, items: null,
                           accepted: {},
                           status: 'Error: ' + (e.message || e),
                           statusColor: '#fca5a5'};
        iris_ci_render_detail();
    });
}

function iris_ci_clear_detail() {
    IRIS_CI.sel = null;
    var d = document.getElementById('iris-ci-detail');
    var p = document.getElementById('iris-ci-placeholder');
    if (d) d.style.display = 'none';
    if (p) p.style.display = '';
    iris_ci_render_list();
}

function iris_ci_render_detail() {
    var r = IRIS_CI.rows.find(function (x) {
        return x.ioc_id === IRIS_CI.sel; });
    if (!r) { iris_ci_clear_detail(); return; }
    var ph = document.getElementById('iris-ci-placeholder');
    if (ph) ph.style.display = 'none';
    var box = document.getElementById('iris-ci-detail');
    if (!box) return;
    box.style.display = '';

    var l = iris_ci_links_for(r);
    var notes = l.note_links || [];
    var assets = l.asset_links || [];
    /* enriched rows when the bulk links payload carries them; the IOC
       payload's own cross-case list is the fallback */
    var cases = (l.case_links && l.case_links.length)
        ? l.case_links : (r.link || []);
    var comments = IRIS_CI.comments[r.ioc_id];
    if (comments === undefined) {
        IRIS_CI.comments[r.ioc_id] = null;
        iris_ci_load_comments(r.ioc_id);
    }
    iris_ci_load_timeline();
    var tlRows = iris_ci_tl_for(r);
    var hist = r.modification_history || {};
    var histEntries = Object.keys(hist).map(function (k) {
        return {ts: parseFloat(k), e: hist[k]};
    }).sort(function (a, b) { return b.ts - a.ts; });

    var html =
        '<div style="display:flex; align-items:flex-start; gap:8px;">' +
        '<div style="flex:1 1 auto; min-width:0;">' +
        '<div style="color:#e8e8ee; font-weight:600; font-size:1.02rem; word-break:break-all;">' +
        iris_ci_esc(r.ioc_value) + '</div>' +
        '<div class="text-muted" style="font-size:0.74rem;">' +
        iris_ci_esc(iris_ci_type(r)) + ' &middot; #' + iris_ci_esc(r.ioc_id) + '</div>' +
        '</div>' +
        (IRIS_CI.editing
            ? '<button type="button" class="btn btn-sm btn-light iris-ci-edit-cancel">&times; Cancel</button>' +
              '<button type="button" class="btn btn-sm btn-primary iris-ci-edit-save">&#128190; Save Changes</button>'
            : /* Share + Markdown link — the legacy modal's ⋮ actions, kept
                 reachable on the v3 header (same functions, same deep link). */
              '<button type="button" class="iris-ci-linkbtn" title="Copy shareable link" onclick="copy_object_link(' + r.ioc_id + ');"><i class="fa fa-share"></i></button>' +
              '<button type="button" class="iris-ci-linkbtn" title="Copy Markdown link" onclick="copy_object_link_md(\'ioc\', ' + r.ioc_id + ');"><i class="fa-brands fa-markdown"></i></button>' +
              '<button type="button" class="iris-ci-prof-btn" title="AI profile of this indicator">&#x2728;</button>' +
              '<button type="button" class="btn btn-sm btn-light iris-ci-edit-btn">&#9998; Edit IOC</button>' +
              '<button type="button" class="btn btn-sm btn-danger iris-ci-del-btn">Delete</button>') +
        '</div>' +
        '<div class="iris-ci-dtabs">' +
        [['details', 'Details', null],
         ['timeline', 'Timeline', tlRows.length],
         ['intel', 'Intel', null],
         ['history', 'History', null],
         ['comments', 'Comments',
          Array.isArray(comments) ? comments.length : null],
         ['assets', 'Assets', assets.length],
         ['notes', 'Notes', notes.length],
         ['cases', 'Cases', cases.length]]
            .map(function (t) {
                return '<button type="button" class="iris-ci-dtab' +
                    (IRIS_CI.tab === t[0] ? ' active' : '') +
                    '" data-tab="' + t[0] + '">' + t[1] +
                    (t[2] === null ? ''
                        : ' <span class="text-muted">' + t[2] + '</span>') +
                    '</button>';
            }).join('') + '</div>';

    var body = '';
    if (IRIS_CI.tab === 'timeline') {
        body += iris_ci_tl_tab_html(tlRows);
    } else if (IRIS_CI.tab === 'intel') {
        body += iris_ci_intel_tab_html(r);
    } else if (IRIS_CI.tab === 'history') {
        body += histEntries.length
            ? histEntries.map(function (it) {
                var when = isNaN(it.ts) ? ''
                    : new Date(it.ts * 1000).toLocaleString();
                return '<div style="padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.05); font-size:0.78rem;">' +
                    '<span style="color:#9a9aa5;">' + iris_ci_esc(when) +
                    '</span> &middot; <span style="color:#c8c8d0;">' +
                    iris_ci_esc((it.e && it.e.action) || '') +
                    '</span> <span style="color:#7a7a85;">by ' +
                    iris_ci_esc((it.e && it.e.user) || '?') + '</span></div>';
            }).join('')
            : '<div class="text-muted" style="font-size:0.8rem;">No history recorded for this indicator.</div>';
    } else if (IRIS_CI.tab === 'comments') {
        if (!Array.isArray(comments)) {
            body += '<div class="text-muted" style="font-size:0.8rem;">Loading comments&hellip;</div>';
        } else {
            body += '<div class="iris-ci-clist">';
            body += comments.length
                ? comments.map(function (cm) {
                    var who = (cm.user && (cm.user.user_name ||
                        cm.user.user_login)) || '?';
                    var when = String(cm.comment_date || '')
                        .replace('T', ' ').slice(0, 16);
                    return '<div style="padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.05);">' +
                        '<div style="font-size:0.7rem; color:#9a9aa5;"><b style="color:#c8c8d0;">' +
                        iris_ci_esc(who) + '</b> &middot; ' +
                        iris_ci_esc(when) + '</div>' +
                        '<div style="font-size:0.8rem; color:#e8e8ee; white-space:pre-wrap;">' +
                        iris_ci_esc(cm.comment_text) + '</div></div>';
                }).join('')
                : '<div class="text-muted" style="font-size:0.8rem;">No comments yet.</div>';
            body += '</div>';
            body += '<div class="iris-ci-cfoot">' +
                '<input type="text" class="form-control form-control-sm" ' +
                'id="iris-ci-comment-input" placeholder="Add a comment..." autocomplete="off">' +
                '<button type="button" class="btn btn-sm btn-primary" ' +
                'onclick="iris_ci_post_comment(' + r.ioc_id +
                ');">Comment</button></div>';
        }
    } else if (IRIS_CI.tab === 'assets') {
        /* always — the Link-asset menu lists candidates even when nothing
           is linked yet */
        iris_ci_load_assets();
        body += '<div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">' +
            '<span style="color:#e8e8ee; font-weight:600; font-size:0.9rem;">Linked assets</span>' +
            '<span class="text-muted" style="font-size:0.74rem;">' +
            assets.length + '</span>' +
            '<span style="margin-left:auto; display:inline-flex; align-items:center; gap:10px;">' +
            '<div class="iris-cshell-menuwrap">' +
            '<button type="button" class="iris-cshell-btn" id="iris-ci-alinkbtn">&#128279; Link asset &#9662;</button>' +
            iris_ci_alink_menu_html(r) + '</div>' +
            '<a style="color:#8fa3ef; font-size:0.76rem; text-decoration:none;" href="/case/assets?cid=' +
            iris_ci_cid() + '">Open the Assets tab &rarr;</a></span></div>';
        body += assets.length
            ? assets.map(iris_ci_asset_card_html).join('')
            : '<div class="text-muted" style="font-size:0.8rem; padding:6px 0;">No assets linked to this indicator.</div>';
    } else if (IRIS_CI.tab === 'notes') {
        body += notes.length
            ? notes.map(iris_ci_note_row_html).join('')
            : '<div class="text-muted" style="font-size:0.8rem;">No notes cite this indicator.</div>';
    } else if (IRIS_CI.tab === 'cases') {
        body += '<div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">' +
            '<span style="color:#e8e8ee; font-weight:600; font-size:0.9rem;">Also seen in</span>' +
            '<span class="text-muted" style="font-size:0.74rem;">' +
            cases.length + ' case' + (cases.length === 1 ? '' : 's') +
            '</span></div>';
        body += cases.length
            ? cases.map(iris_ci_case_card_html).join('')
            : '<div class="text-muted" style="font-size:0.8rem; padding:6px 0;">This indicator does not appear in any other case.</div>';
    } else if (IRIS_CI.editing) {
        iris_ci_fetch_edit_catalogs();
        body += iris_ci_edit_form_html(r);
    } else {
        var tags = iris_ci_tags(r);
        body +=
            '<div style="display:flex; align-items:center; gap:14px; flex-wrap:wrap;">' +
            iris_ci_tlp_badge(iris_ci_tlp(r)) +
            '<span class="iris-ci-field"><span class="lbl">Type</span>' +
            iris_ci_esc(iris_ci_type(r)) + '</span>' +
            '</div>' +
            (tags.length
                ? '<div style="margin-top:8px; display:flex; gap:4px; flex-wrap:wrap; align-items:center;">' +
                  '<span class="lbl" style="color:#7a7a85; font-size:0.62rem; letter-spacing:0.08em; text-transform:uppercase; margin-right:4px;">Tags</span>' +
                  tags.map(function (t) {
                      return '<span class="iris-ci-tag">' + iris_ci_esc(t) +
                          '</span>'; }).join('') + '</div>' : '') +
            '<div class="iris-ci-valbox"><code>' +
            iris_ci_esc(r.ioc_value) + '</code></div>' +
            (r.ioc_description
                ? '<div class="iris-ci-desc">' +
                  iris_ci_esc(r.ioc_description) + '</div>'
                : '<div class="iris-ci-desc text-muted">(no description)</div>') +
            '<div class="iris-ci-foot">' +
            '<span>ID #' + iris_ci_esc(r.ioc_id) + '</span>' +
            (r.ioc_uuid ? '<span>UUID ' + iris_ci_esc(r.ioc_uuid) + '</span>'
                        : '') +
            '<span>Case #' + iris_ci_esc(r.case_id || iris_ci_cid()) +
            '</span></div>';
        iris_ci_profile_fetch(r);
        body += iris_ci_profile_html(r);
    }

    var cls = 'iris-ci-dbody' +
        (IRIS_CI.tab === 'comments' ? ' iris-ci-dbody-split' : '');
    box.innerHTML = html + '<div class="' + cls + '">' + body + '</div>';
    /* innerHTML replaced the node, so the tag widget re-attaches each time
       (the guard attribute lives on the element, so no double-wrap) */
    if (IRIS_CI.editing) iris_ci_init_tag_widget();
    iris_ci_fit_soon();
    if (IRIS_CI.tab === 'comments') {
        var cl = box.querySelector('.iris-ci-clist');
        if (cl) cl.scrollTop = cl.scrollHeight;
    }
}

/* The card is sticky, so its top only settles once pinned — measure both
   edges rather than deriving from a fixed offset. */
function iris_ci_fit_card() {
    var card = document.querySelector('.iris-ci-right');
    if (!card || !card.getBoundingClientRect) return;
    var top = card.getBoundingClientRect().top;
    var form = document.getElementById('iris-chat-form');
    var limit = (form && form.getBoundingClientRect)
        ? form.getBoundingClientRect().top
        : (window.innerHeight || 800) - 18;
    var h = Math.max(220, Math.round(limit - top - 14)) + 'px';
    /* write-only-on-change: an unchanged write still invalidates layout,
       forcing the next geometry read (ours or jQuery's) to reflow */
    if (card.style.height !== h) card.style.height = h;
}

var IRIS_CI_FIT_PENDING = false;

function iris_ci_fit_soon() {
    if (IRIS_CI_FIT_PENDING) return;
    IRIS_CI_FIT_PENDING = true;
    var run = function () {
        IRIS_CI_FIT_PENDING = false;
        iris_ci_fit_card();
    };
    if (window.requestAnimationFrame) window.requestAnimationFrame(run);
    else setTimeout(run, 16);
}

document.addEventListener('DOMContentLoaded', function () {
    if (!document.getElementById('iris-ci-list')) return;
    /* an event saved from the in-place add-event modal lands on the
       timeline this tab renders — refetch it */
    window.iris_event_saved = function () { iris_ci_load_timeline(true); };
    iris_ci_fit_card();
    window.addEventListener('scroll', iris_ci_fit_soon, {passive: true});
    window.addEventListener('resize', iris_ci_fit_soon);

    /* Modal saves call reload_iocs() -> get_case_ioc(); wrap it so the v3
       panes refresh too (the established monkey-patch idiom). The legacy
       module's own $(document).ready fires get_case_ioc() right after this
       handler (vanilla listeners registered earlier run first), so with the
       wrapper installed a direct iris_ci_load() here would fetch the same
       multi-MB payload a second time — load directly ONLY when the legacy
       module is absent. */
    if (typeof window.get_case_ioc === 'function') {
        var orig = window.get_case_ioc;
        window.get_case_ioc = function () {
            var out = orig.apply(this, arguments);
            iris_ci_load();
            return out;
        };
    } else {
        iris_ci_load();
    }

    var search = document.getElementById('iris-ci-search');
    if (search) {
        search.addEventListener('input', function (e) {
            IRIS_CI.q = e.target.value.trim().toLowerCase();
            iris_ci_render_list();
        });
    }

    document.getElementById('iris-ci-list')
        .addEventListener('click', function (e) {
            var row = e.target.closest('.iris-ci-row');
            if (!row) return;
            var id = parseInt(row.getAttribute('data-ioc-id'), 10);
            IRIS_CI.sel = (IRIS_CI.sel === id) ? null : id;
            IRIS_CI.tab = 'details';
            IRIS_CI.editing = false;   /* switching IOCs discards the form */
            IRIS_CI.tagSugg = null;
            IRIS_CI.noteOpen = null;   /* and closes any open note */
            IRIS_CI.caseOpen = null;
            iris_ci_render_list();
            iris_ci_render_detail();
        });

    /* the Link-asset menu filter re-renders only its own items fragment,
       so typing keeps focus (established idiom) */
    document.getElementById('iris-ci-detail')
        .addEventListener('input', function (e) {
            if (e.target.id !== 'iris-ci-amenuq') return;
            IRIS_CI.aMenuQ = e.target.value.trim();
            var sel = IRIS_CI.rows.find(function (x) {
                return x.ioc_id === IRIS_CI.sel; });
            var box = document.getElementById('iris-ci-amenuitems');
            if (box && sel) {
                box.innerHTML = iris_ci_alink_menuitems_html(sel);
            }
        });

    document.getElementById('iris-ci-detail')
        .addEventListener('click', function (e) {
            var sel = IRIS_CI.rows.find(function (x) {
                return x.ioc_id === IRIS_CI.sel; });
            if (!sel) return;
            /* asset link/unlink — before anything else, because the ×
               sits INSIDE the card anchor and must beat its navigation */
            var aun = e.target.closest('.iris-ci-aunlink');
            if (aun) {
                e.preventDefault();
                iris_ci_unlink_asset(sel,
                    parseInt(aun.getAttribute('data-asset-id'), 10));
                return;
            }
            if (e.target.closest('#iris-ci-alinkbtn')) {
                e.stopPropagation();
                IRIS_CI.aMenu = !IRIS_CI.aMenu;
                IRIS_CI.aMenuQ = '';
                iris_ci_render_detail();
                return;
            }
            var ali = e.target.closest('.iris-ci-alinkitem');
            if (ali) {
                e.preventDefault();
                iris_ci_link_asset(sel,
                    parseInt(ali.getAttribute('data-asset-id'), 10));
                return;
            }
            if (e.target.closest('#iris-ci-anewbtn')) {
                iris_ci_new_asset_and_link(sel);
                return;
            }
            if (e.target.closest('.iris-ci-prof-btn')
                    || e.target.closest('.iris-ci-prof-gen')) {
                e.preventDefault();
                IRIS_CI.tab = 'details';
                iris_ci_profile_gen(sel, false);
                return;
            }
            if (e.target.closest('.iris-ci-prof-rerun')) {
                e.preventDefault();
                iris_ci_profile_gen(sel, true);
                return;
            }
            if (e.target.closest('.iris-ci-edit-btn')) {
                IRIS_CI.editing = true;
                IRIS_CI.tab = 'details';
                iris_ci_fetch_edit_catalogs();
                iris_ci_render_detail();
                return;
            }
            if (e.target.closest('.iris-ci-edit-cancel')) {
                IRIS_CI.editing = false;
                IRIS_CI.tagSugg = null;
                iris_ci_render_detail();
                return;
            }
            if (e.target.closest('.iris-ci-edit-save')) {
                iris_ci_save_edit(sel);
                return;
            }
            /* the modal remains the full editor (custom attributes) */
            if (e.target.closest('.iris-ci-fulledit')) {
                e.preventDefault();
                if (typeof window.edit_ioc === 'function') {
                    window.edit_ioc(sel.ioc_id);
                }
                return;
            }
            if (e.target.closest('#iris-ci-modbtn')) {
                e.stopPropagation();
                IRIS_CI.modMenu = !IRIS_CI.modMenu;
                iris_ci_render_detail();
                return;
            }
            var crow = e.target.closest('.iris-ci-crow');
            if (crow) {
                /* the case opens IN the panel, not in a popup */
                var cid = crow.getAttribute('data-case-id');
                IRIS_CI.caseOpen =
                    (String(IRIS_CI.caseOpen) === String(cid)) ? null : cid;
                if (IRIS_CI.caseOpen !== null) iris_ci_load_case_peek(cid);
                iris_ci_render_detail();
                return;
            }
            var noterow = e.target.closest('.iris-ci-noterow');
            if (noterow && !e.target.closest('.iris-ci-noteopen')) {
                /* the row reads the note in place; the small arrow still
                   deep-links to the Notes page, which is where you go to
                   EDIT it — that link keeps its old behaviour */
                var nid = parseInt(noterow.getAttribute('data-note-id'), 10);
                IRIS_CI.noteOpen = (IRIS_CI.noteOpen === nid) ? null : nid;
                if (IRIS_CI.noteOpen !== null) iris_ci_load_note(nid);
                iris_ci_render_detail();
                return;
            }
            var tlflag = e.target.closest('.iris-ci-tl-flag');
            if (tlflag) {
                /* legacy GET toggle — non-POST verbs are CSRF-exempt */
                fetch('/case/timeline/events/flag/' +
                      tlflag.getAttribute('data-event-id') + '?cid=' +
                      iris_ci_cid(),
                      {credentials: 'same-origin',
                       headers: {'Accept': 'application/json'}})
                    .then(function (r2) { return r2.json(); })
                    .then(function (resp) {
                        if (resp && resp.status === 'success') {
                            iris_ci_load_timeline(true);
                        } else {
                            window.alert((resp && resp.message)
                                || 'Flag toggle failed');
                        }
                    })
                    .catch(function () {
                        window.alert('Flag toggle failed'); });
                return;
            }
            var runit = e.target.closest('.iris-ci-modrun');
            if (runit) {
                e.preventDefault();
                iris_ci_run_module(sel,
                    parseInt(runit.getAttribute('data-idx'), 10));
                return;
            }
            if (e.target.closest('#iris-ci-tagsugg-pill')) {
                iris_ci_tagsugg_run(sel);
                return;
            }
            var sugg = e.target.closest('.iris-ci-tagsugg-chip');
            if (sugg) {
                var stag = sugg.getAttribute('data-tag');
                if (stag && iris_ci_tagsugg_add(stag) && IRIS_CI.tagSugg) {
                    IRIS_CI.tagSugg.accepted[stag] = true;
                    iris_ci_render_detail();
                }
                return;
            }
            if (e.target.closest('#iris-ci-tagsugg-all') && IRIS_CI.tagSugg
                    && IRIS_CI.tagSugg.items) {
                IRIS_CI.tagSugg.items.forEach(function (s) {
                    if (!IRIS_CI.tagSugg.accepted[s.tag]
                            && iris_ci_tagsugg_add(s.tag)) {
                        IRIS_CI.tagSugg.accepted[s.tag] = true;
                    }
                });
                iris_ci_render_detail();
                return;
            }
            if (e.target.closest('.iris-ci-del-btn')) {
                if (typeof window.delete_ioc === 'function') {
                    window.delete_ioc(sel.ioc_id);
                }
                return;
            }
            var tab = e.target.closest('.iris-ci-dtab');
            if (tab) {
                IRIS_CI.tab = tab.getAttribute('data-tab');
                if (IRIS_CI.tab !== 'details') {
                    IRIS_CI.editing = false;   /* leaving Details discards it */
                    IRIS_CI.tagSugg = null;
                }
                iris_ci_render_detail();
            }
        });

    /* The section ⋮ (#iris-ci-more / #iris-ci-moremenu) moved into the shell
       header menu, which owns its own open/close — case_shell.js closes it on
       any item click, so these handlers no longer name a menu at all. The
       items kept their ids, so the bindings below are unchanged. */
    var exp = document.getElementById('iris-ci-export');
    if (exp) {
        exp.addEventListener('click', function (e) {
            e.preventDefault();
            iris_ci_export_csv();
        });
    }

    var legacy = document.getElementById('iris-ci-legacy-toggle');
    if (legacy) {
        legacy.addEventListener('click', function (e) {
            e.preventDefault();
            var w = document.getElementById('iris-ci-legacy');
            if (w) w.style.display = (w.style.display === 'none') ? '' : 'none';
            /* the legacy card is revealed by its own JS after the table
               loads; if that has not happened, show it so the safety valve
               is not an empty shell */
            var card = document.getElementById('card_main_load');
            if (card && w && w.style.display !== 'none') card.style.display = '';
        });
    }
});

Object.assign(window, {iris_ci_post_comment: iris_ci_post_comment});

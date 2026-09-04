/* v3 Evidence master/detail (case Evidence tab). Vanilla JS — renders
 * before jQuery. Data comes from the same /case/evidences/list payload the
 * legacy DataTable eats; Add/Edit/Delete go through the EXISTING modal
 * functions (add_modal_rfile / edit_rfiles / delete_rfile), so all evidence
 * machinery — hashing, drive linking, custom attributes, module quick
 * actions — is untouched. The legacy table stays in the DOM hidden as a
 * safety valve. */

var IRIS_CE = {rows: [], sel: null, q: '', tab: 'details',
               loaded: false, failed: false, comments: {},
               assetCatalog: null, assetCatalogLoaded: false,
               assetCatalogFailed: false,
               iocCat: null, iocCatFetching: false, iocCatFailed: false,
               drives: {},
               editing: false, evidenceTypes: null, drivesCat: null};

var IRIS_CE_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/* Size the detail card so its bottom edge stops just above the AI chat
 * bar. Same mechanism as the Assets tab: the card is position:sticky, so
 * its top is only `top:70px` once pinned — measure both edges, never
 * derive from a constant. The CSS calc remains as a no-JS fallback. */
function iris_ce_fit_card() {
    var card = document.querySelector('.iris-ce-right');
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

var IRIS_CE_FIT_PENDING = false;

function iris_ce_fit_soon() {
    if (IRIS_CE_FIT_PENDING) return;
    IRIS_CE_FIT_PENDING = true;
    var run = function () {
        IRIS_CE_FIT_PENDING = false;
        iris_ce_fit_card();
    };
    if (window.requestAnimationFrame) window.requestAnimationFrame(run);
    else setTimeout(run, 16);
}

function iris_ce_esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return {'&': '&amp;', '<': '&lt;', '>': '&gt;',
                '"': '&quot;', "'": '&#39;'}[c];
    });
}

function iris_ce_cid() {
    var m = window.location.search.match(/[?&]cid=(\d+)/);
    return m ? m[1] : '';
}

function iris_ce_csrf() {
    var el = document.getElementById('csrf_token');
    return el ? el.value : '';
}

function iris_ce_bytes(n) {
    n = parseInt(n, 10);
    if (isNaN(n) || n < 0) return null;
    var u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'], i = 0, v = n;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1; }
    return (i === 0 ? v : (v >= 10 ? v.toFixed(0) : v.toFixed(1))) +
        ' ' + u[i];
}

function iris_ce_hash_kind(h) {
    var L = String(h || '').length;
    return L === 32 ? 'MD5' : L === 40 ? 'SHA1'
         : L === 64 ? 'SHA256' : L === 128 ? 'SHA512' : 'hash';
}

function iris_ce_utc_label(iso, withTime) {
    /* Evidence timestamps are naive-UTC storage — label the STORED value,
       never re-zone it through new Date(). */
    var m = String(iso || '')
        .match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/);
    if (!m) return null;
    var s = IRIS_CE_MONTHS[parseInt(m[2], 10) - 1] + ' ' +
        parseInt(m[3], 10) + ', ' + m[1];
    if (withTime && m[4]) s += ' ' + m[4] + ':' + m[5] + ' UTC';
    return s;
}

function iris_ce_type_name(r) {
    return (r.type && r.type.name) ? r.type.name : 'Unspecified';
}

function iris_ce_sel_row() {
    return IRIS_CE.rows.find(function (x) { return x.id === IRIS_CE.sel; });
}

/* ---- data ---- */

function iris_ce_load() {
    fetch('/case/evidences/list?cid=' + iris_ce_cid(),
          {headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (resp) {
            IRIS_CE.rows = ((resp && resp.data) || {}).evidences || [];
            IRIS_CE.loaded = true;
            IRIS_CE.failed = false;
            /* the selection survives a refresh; a deleted item does not */
            if (IRIS_CE.sel !== null && !iris_ce_sel_row()) {
                IRIS_CE.sel = null;
            }
            /* a ?shared= deep link also selects the item in the panel
               (the legacy handler opens its modal on top, unchanged) */
            if (IRIS_CE.sel === null
                    && typeof getSharedLink === 'function') {
                var sid = parseInt(getSharedLink() || '', 10);
                if (!isNaN(sid) && IRIS_CE.rows.some(function (r2) {
                        return r2.id === sid; })) {
                    IRIS_CE.sel = sid;
                }
            }
            iris_ce_render_list();
            /* a background refresh must not rebuild an OPEN edit form —
               typing would be wiped mid-word */
            if (!IRIS_CE.editing) iris_ce_render_detail();
        })
        .catch(function () {
            IRIS_CE.loaded = true;
            IRIS_CE.failed = true;
            iris_ce_render_list();
        });
}

function iris_ce_load_comments(evId) {
    IRIS_CE.comments[evId] = null;   /* in flight — distinct from absent */
    fetch('/case/evidences/' + evId + '/comments/list?cid=' +
          iris_ce_cid(), {headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (resp) {
            IRIS_CE.comments[evId] = (resp && resp.data) || [];
            if (IRIS_CE.sel === evId && !IRIS_CE.editing) {
                iris_ce_render_detail();
            }
        })
        .catch(function () {
            /* failed is NOT the same claim as "no comments" */
            IRIS_CE.comments[evId] = 'failed';
            if (IRIS_CE.sel === evId && !IRIS_CE.editing) {
                iris_ce_render_detail();
            }
        });
}

function iris_ce_post_comment(evId) {
    var box = document.getElementById('iris-ce-comment-input');
    if (!box || !box.value.trim()) return;
    fetch('/case/evidences/' + evId + '/comments/add?cid=' + iris_ce_cid(), {
        method: 'POST',
        headers: {'Accept': 'application/json',
                  'Content-Type': 'application/json'},
        body: JSON.stringify({comment_text: box.value,
                              csrf_token: iris_ce_csrf()})
    }).then(function (r) { return r.json(); })
        .then(function (resp) {
            if (resp && resp.status === 'success') {
                iris_ce_load_comments(evId);
            } else {
                window.alert((resp && resp.message) || 'Comment failed');
            }
        })
        .catch(function () { window.alert('Comment failed'); });
}

/* The linked-asset chips need names; the link rows carry only ids. The
 * catalog comes from /case/assets/filter — the endpoint the Assets page
 * actually calls — fetched once, lazily, on the first detail that needs
 * it. null = have not looked. */
function iris_ce_fetch_asset_catalog() {
    if (IRIS_CE.assetCatalog !== null) return;
    IRIS_CE.assetCatalog = [];   /* fetch in flight */
    fetch('/case/assets/filter?cid=' + iris_ce_cid(),
          {headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (resp) {
            IRIS_CE.assetCatalog = ((resp && resp.data) || {}).assets || [];
            IRIS_CE.assetCatalogLoaded = true;
            if (!IRIS_CE.editing) iris_ce_render_detail();
        })
        .catch(function () {
            /* a failed lookup must NOT read as "asset no longer in this
               case" — keep failure distinct from an empty catalog */
            IRIS_CE.assetCatalogFailed = true;
            if (!IRIS_CE.editing) iris_ce_render_detail();
        });
}

/* ---- master list ---- */

function iris_ce_visible() {
    var q = IRIS_CE.q;
    return IRIS_CE.rows.filter(function (r) {
        if (!q) return true;
        return [r.filename, iris_ce_type_name(r), r.file_hash,
                r.file_description, r.barcode, r.created_by,
                r.physical_location]
            .some(function (v) {
                return String(v || '').toLowerCase().indexOf(q) >= 0;
            });
    });
}

function iris_ce_render_list() {
    var box = document.getElementById('iris-ce-list');
    var loading = document.getElementById('iris-ce-loading');
    var none = document.getElementById('iris-ce-none');
    var count = document.getElementById('iris-ce-count');
    if (!box) return;
    if (!IRIS_CE.loaded) return;
    loading.style.display = 'none';
    if (IRIS_CE.failed) {
        box.innerHTML = '';
        none.style.display = '';
        none.textContent = 'Could not load the evidence list.';
        return;
    }
    count.textContent = '(' + IRIS_CE.rows.length + ')';
    var rows = iris_ce_visible();
    /* the empty state names WHY it is empty */
    if (!rows.length) {
        box.innerHTML = '';
        none.style.display = '';
        none.textContent = IRIS_CE.rows.length
            ? 'No evidence matches "' + IRIS_CE.q + '".'
            : 'No evidence registered in this case yet — Add Evidence ' +
              'registers the first item.';
        return;
    }
    none.style.display = 'none';
    box.innerHTML = rows.map(function (r) {
        var size = iris_ce_bytes(r.file_size);
        var added = iris_ce_utc_label(r.date_added, true);
        return '<div class="iris-ce-row' +
            (r.id === IRIS_CE.sel ? ' active' : '') +
            '" data-ev-id="' + r.id + '">' +
            '<div style="display:flex; align-items:flex-start; gap:8px;">' +
            '<div style="flex:1 1 auto; min-width:0;">' +
            '<div class="iris-ce-name"><code>' + iris_ce_esc(r.filename) +
            '</code></div>' +
            '<div class="iris-ce-meta">' +
            (added ? '<span>' + iris_ce_esc(added) + '</span>' : '') +
            /* an unhashed item is a FINDING, rendered, not omitted — and
               here the row IS the catalog, so the claim is supported */
            (r.file_hash ? ''
                : '<span class="iris-ce-nohash">No hash recorded</span>') +
            '</div></div>' +
            '<div style="flex-shrink:0; text-align:right;">' +
            '<span class="iris-ce-chip">' +
            iris_ce_esc(iris_ce_type_name(r)) + '</span>' +
            (size ? '<div class="iris-ce-meta" style="justify-content:flex-end;">' +
                iris_ce_esc(size) + '</div>' : '') +
            '</div></div></div>';
    }).join('');
}

/* ---- detail panel ---- */

function iris_ce_field(lbl, val, mono) {
    return '<span class="iris-ce-field"><span class="lbl">' + lbl +
        '</span>' + (mono ? '<code>' + val + '</code>' : val) + '</span>';
}

function iris_ce_desc_html(r) {
    var d = r.file_description || '';
    if (!d.trim()) {
        return '<div class="iris-ce-desc text-muted"><i>No description ' +
            'provided</i></div>';
    }
    /* analyst content gets the PRODUCT's renderer — the same pair the
       modal's own preview uses (get_showdown_convert + do_md_filter_xss);
       plain escaped text is the fallback when it is not loaded yet */
    if (typeof get_showdown_convert === 'function'
            && typeof do_md_filter_xss === 'function') {
        var html = get_showdown_convert().makeHtml(do_md_filter_xss(d));
        return '<div class="iris-ce-desc iris-ce-md">' +
            do_md_filter_xss(html) + '</div>';
    }
    return '<div class="iris-ce-desc" style="white-space:pre-wrap;">' +
        iris_ce_esc(d) + '</div>';
}

/* The REAL asset ids ride the additive `asset_links` payload field — the
 * dumped `assets` field carries EvidenceAssetLink ROW ids, a different id
 * space entirely (link 36 pointed at asset 21; resolving it as an asset id
 * claimed "no longer in this case" about an asset sitting on the page). */
function iris_ce_asset_ids(r) {
    return Array.isArray(r.asset_links) ? r.asset_links : [];
}

/* ---- Assets tab: each linked asset rendered as the SAME card the IOC
 * page's Assets tab shows (ported from case_iocs_v3.js — name / meta /
 * tags / indicator cluster from the same fields), joined from the case
 * asset catalog. Evidence link rows carry only the asset id, so until the
 * catalog is in hand the card names the id and claims nothing else. */

var IRIS_CE_COMP = {
    0: {label: 'To be determined', color: '#9a9aa5'},
    1: {label: 'Compromised', color: '#F25961'},
    2: {label: 'Not compromised', color: '#2dce89'},
    3: {label: 'Unknown', color: '#9a9aa5'}
};

function iris_ce_asset_full(assetId) {
    return (IRIS_CE.assetCatalog || []).find(function (a) {
        return a.asset_id === assetId;
    }) || null;
}

function iris_ce_comp(row) {
    return IRIS_CE_COMP[row.asset_compromise_status_id] || IRIS_CE_COMP[3];
}

function iris_ce_asset_type_name(row) {
    return (row.asset_type && row.asset_type.asset_name)
        ? row.asset_type.asset_name : (row.asset_type || '');
}

function iris_ce_asset_tags(row) {
    return String(row.asset_tags || '').split(',')
        .map(function (t) { return t.trim(); })
        .filter(function (t) { return t; });
}

function iris_ce_rowicon(paths, color, title) {
    return '<span title="' + iris_ce_esc(title) +
        '" style="color:' + color + '; display:inline-flex;">' +
        '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        paths + '</svg></span>';
}

function iris_ce_analysis_color(name) {
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

/* Indicator cluster, identical to the Assets list row and the IOC page's
 * asset cards: compromise chip (or state icon), analysis clock coloured by
 * status NAME, explicit has-IOCs / no-IOCs mark — absence rendered. */
function iris_ce_row_icons_html(r) {
    var out = '';
    var comp = iris_ce_comp(r);
    var compId = (r.asset_compromise_status_id === null
        || r.asset_compromise_status_id === undefined)
        ? 0 : r.asset_compromise_status_id;
    if (compId === 1) {
        out += '<span class="iris-ce-comp-chip" style="border-color:' +
            comp.color + '55; color:' + comp.color + ';">' + comp.label +
            '</span>';
    } else if (compId === 2) {
        out += iris_ce_rowicon(
            '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
            '#2dce89', 'Not compromised');
    } else if (compId === 3) {
        out += iris_ce_rowicon(
            '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" x2="12.01" y1="17" y2="17"/>',
            '#9a9aa5', 'Compromise: unknown');
    } else {
        out += iris_ce_rowicon(
            '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
            '#f4c430', 'Compromise: to be determined');
    }
    var ana = (r.analysis_status && r.analysis_status.name)
        ? r.analysis_status.name : 'Unspecified';
    out += iris_ce_rowicon(
        '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
        iris_ce_analysis_color(ana), 'Analysis: ' + ana);
    var nIocs = Array.isArray(r.ioc_links) ? r.ioc_links.length : 0;
    if (nIocs) {
        out += '<span title="' + nIocs + ' linked IOC' +
            (nIocs === 1 ? '' : 's') +
            '" style="color:#e08fb9; display:inline-flex; align-items:center; gap:3px; font-size:0.72rem;">' +
            '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m8 2 1.88 1.88"/><path d="M14.12 3.88 16 2"/><path d="M9 7.13v-1a3.003 3.003 0 1 1 6 0v1"/><path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6"/><path d="M12 20v-9"/><path d="M6.53 9C4.6 8.8 3 7.1 3 5"/><path d="M6 13H2"/><path d="M3 21c0-2.1 1.7-3.9 3.8-4"/><path d="M20.97 5c0 2.1-1.6 3.8-3.5 4"/><path d="M22 13h-4"/><path d="M17.2 17c2.1.1 3.8 1.9 3.8 4"/></svg><b>' +
            nIocs + '</b></span>';
    } else {
        out += iris_ce_rowicon(
            '<path d="m2 2 20 20"/><path d="M5 5a1 1 0 0 0-1 1v7c0 5 3.5 7.5 7.66 8.95a1 1 0 0 0 .67.01c2.35-.82 4.48-1.97 5.9-3.71"/><path d="M9.309 3.652A12.252 12.252 0 0 0 11.24 2.28a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1v7a9.784 9.784 0 0 1-.08 1.264"/>',
            '#55555e', 'No IOCs linked');
    }
    return '<span style="display:inline-flex; align-items:center; gap:7px; flex-shrink:0; margin-left:8px;">' +
        out + '</span>';
}

function iris_ce_asset_inner_html(r) {
    var meta = ['<span>' + iris_ce_esc(iris_ce_asset_type_name(r)) +
        '</span>'];
    if (r.asset_ip) {
        meta.push('<code>' + iris_ce_esc(r.asset_ip) + '</code>');
    }
    if (r.asset_domain) {
        meta.push('<code>' + iris_ce_esc(r.asset_domain) + '</code>');
    }
    if (r.asset_description) {
        meta.push('<span>' + iris_ce_esc(
            String(r.asset_description).slice(0, 60)) + '</span>');
    }
    var tags = iris_ce_asset_tags(r).slice(0, 6).map(function (t) {
        return '<span class="iris-ce-atag">' + iris_ce_esc(t) + '</span>';
    }).join('');
    return '<div style="display:flex; align-items:flex-start;">' +
        '<div style="flex:1 1 auto; min-width:0;">' +
        '<div class="iris-ce-aname">' + iris_ce_esc(r.asset_name) + '</div>' +
        '<div class="iris-ce-ameta">' + meta.join(' &middot; ') + '</div>' +
        (tags ? '<div>' + tags + '</div>' : '') +
        '</div>' + iris_ce_row_icons_html(r) +
        '</div>';
}

function iris_ce_asset_card_html(assetId) {
    var full = iris_ce_asset_full(assetId);
    var comp = full ? iris_ce_comp(full) : IRIS_CE_COMP[0];
    var inner;
    if (full) {
        inner = iris_ce_asset_inner_html(full);
    } else {
        /* the link carries only an id — name what we know, claim nothing
           we have not read */
        inner = '<div class="iris-ce-aname">Asset #' + assetId + '</div>' +
            '<div class="iris-ce-ameta"><span>' +
            (IRIS_CE.assetCatalogFailed
                ? 'Could not load the asset details.'
                : (!IRIS_CE.assetCatalogLoaded
                    ? 'Loading asset details&hellip;'
                    : 'Details unavailable — the asset is no longer in this case.')) +
            '</span></div>';
    }
    return '<a class="iris-ce-acard" href="/case/assets?cid=' +
        iris_ce_cid() + '&shared=' + assetId +
        '" title="Open this asset on the Assets tab" style="border-left-color:' +
        comp.color + ';">' + inner +
        '<span class="iris-ce-aid">#' + assetId + '</span></a>';
}

function iris_ce_assets_tab_html(r) {
    var ids = iris_ce_asset_ids(r);
    if (!ids.length) {
        return '<div class="text-muted" style="font-size:0.8rem; padding:6px 0;">' +
            'No assets linked to this evidence. Evidence is linked from ' +
            'the asset side — open an asset\'s editor on the ' +
            '<a href="/case/assets?cid=' + iris_ce_cid() +
            '" style="color:#8fa3ef;">Assets tab</a>.</div>';
    }
    iris_ce_fetch_asset_catalog();
    return ids.map(iris_ce_asset_card_html).join('');
}

/* ---- IOCs tab: evidence has NO direct IOC links — these are DERIVED
 * through the linked assets (asset.ioc_links from the same catalog), and
 * the tab says so. Each row names which asset(s) carry it. */

var IRIS_CE_TLP = {
    'red':          '#F25961',
    'amber':        '#f4c430',
    'amber strict': '#f4c430',
    'green':        '#2dce89',
    'clear':        '#c8c8d0',
    'white':        '#c8c8d0'
};

function iris_ce_tlp_badge(name) {
    var key = String(name || '').toLowerCase();
    var color = IRIS_CE_TLP[key];
    if (!color) return '';
    var label = key.split(' ').map(function (w) {
        return w.charAt(0).toUpperCase() + w.slice(1); }).join(' ');
    return '<span style="border:1px solid ' + color + '55; color:' + color +
        '; border-radius:9px; padding:0 8px; font-size:0.68rem; white-space:nowrap;">TLP:' +
        label + '</span>';
}

function iris_ce_fetch_ioc_catalog() {
    if (IRIS_CE.iocCat !== null || IRIS_CE.iocCatFetching) return;
    IRIS_CE.iocCatFetching = true;
    fetch('/case/ioc/list?cid=' + iris_ce_cid(),
          {headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (resp) {
            IRIS_CE.iocCatFetching = false;
            /* legacy payload key is `ioc`, not `iocs` (documented trap) */
            IRIS_CE.iocCat = ((resp && resp.data) || {}).ioc || [];
            if (!IRIS_CE.editing) iris_ce_render_detail();
        })
        .catch(function () {
            IRIS_CE.iocCatFetching = false;
            IRIS_CE.iocCatFailed = true;
            if (!IRIS_CE.editing) iris_ce_render_detail();
        });
}

/* {state: 'loading'|'failed'|'ready', items: [{ioc_id, ioc_value, via}]}
 * — 'ready' is only claimed once the ASSET catalog is in hand, because an
 * empty union computed before looking is a claim about IOCs we never
 * derived. */
function iris_ce_derived_iocs(r) {
    var ids = iris_ce_asset_ids(r);
    if (!ids.length) return {state: 'ready', items: []};
    if (IRIS_CE.assetCatalogFailed) return {state: 'failed', items: []};
    if (!IRIS_CE.assetCatalogLoaded) return {state: 'loading', items: []};
    var byIoc = {};
    ids.forEach(function (aid) {
        var a = iris_ce_asset_full(aid);
        if (!a) return;
        (Array.isArray(a.ioc_links) ? a.ioc_links : []).forEach(
            function (l) {
                if (!byIoc[l.ioc_id]) {
                    byIoc[l.ioc_id] = {ioc_id: l.ioc_id,
                                       ioc_value: l.ioc_value, via: []};
                }
                byIoc[l.ioc_id].via.push(a.asset_name);
            });
    });
    return {state: 'ready', items: Object.keys(byIoc).map(function (k) {
        return byIoc[k]; })};
}

function iris_ce_iocs_tab_html(r) {
    var d = iris_ce_derived_iocs(r);
    var head = '<div class="text-muted" style="font-size:0.72rem; margin-bottom:6px;">' +
        'Derived via the linked assets — evidence carries no direct IOC ' +
        'links.</div>';
    if (d.state === 'loading') {
        return head + '<div class="text-muted" style="font-size:0.8rem;">Loading the linked assets&hellip;</div>';
    }
    if (d.state === 'failed') {
        return head + '<div style="font-size:0.8rem; color:#fca5a5;">Could not load the linked assets, so the IOCs could not be derived.</div>';
    }
    if (!iris_ce_asset_ids(r).length) {
        return head + '<div class="text-muted" style="font-size:0.8rem;">No assets are linked to this evidence, so there are no IOCs to derive.</div>';
    }
    if (!d.items.length) {
        return head + '<div class="text-muted" style="font-size:0.8rem;">The linked assets carry no IOCs.</div>';
    }
    iris_ce_fetch_ioc_catalog();
    var byId = {};
    (IRIS_CE.iocCat || []).forEach(function (i) { byId[i.ioc_id] = i; });
    /* grouped by type with count chips, like the Assets tab's IOC rows */
    var groups = {};
    d.items.forEach(function (i) {
        var full = byId[i.ioc_id];
        var t = (full && full.ioc_type) || '';
        (groups[t] = groups[t] || []).push(i);
    });
    return head + Object.keys(groups).sort().map(function (t) {
        var gh = t
            ? '<div style="display:flex; align-items:center; gap:6px; margin:8px 0 2px;">' +
              '<span style="color:#9a9aa5; font-size:0.74rem; font-weight:600;">' +
              iris_ce_esc(t) + '</span>' +
              '<span style="border:1px solid rgba(255,255,255,0.12); border-radius:8px; padding:0 7px; color:#9a9aa5; font-size:0.66rem;">' +
              groups[t].length + '</span></div>'
            : '';
        return gh + groups[t].map(function (i) {
            var full = byId[i.ioc_id];
            var via = i.via.slice(0, 3).map(function (nm) {
                return '<span class="iris-ce-viachip">' +
                    iris_ce_esc(nm) + '</span>';
            }).join('');
            if (i.via.length > 3) {
                via += '<span class="text-muted" style="font-size:0.66rem;">+' +
                    (i.via.length - 3) + '</span>';
            }
            return '<div style="display:flex; align-items:center; gap:8px; padding:5px 0 5px 4px; border-bottom:1px solid rgba(255,255,255,0.04);">' +
                '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#7a7a85" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/></svg>' +
                '<div style="min-width:0;">' +
                '<div style="color:#e8e8ee; font-size:0.8rem; font-weight:600; overflow:hidden; text-overflow:ellipsis;">' +
                '<a href="/case/ioc?cid=' + iris_ce_cid() + '&shared=' +
                i.ioc_id + '" style="color:inherit;">' +
                iris_ce_esc(i.ioc_value) + '</a></div>' +
                (full && full.ioc_type
                    ? '<div class="text-muted" style="font-size:0.68rem;">' +
                      iris_ce_esc(full.ioc_type) + '</div>' : '') +
                '</div>' +
                '<span style="margin-left:auto; display:inline-flex; align-items:center; gap:6px; flex-wrap:wrap;">' +
                via + (full ? iris_ce_tlp_badge(full.tlp_name) : '') +
                '</span></div>';
        }).join('');
    }).join('');
}

/* ---- Inventory tab: the physical drive this item sits on, from the v2
 * inventory lookup (payload-direct envelope — the response IS the drive).
 * The status is checked BEFORE any parse: a body-less 404 rejects .json()
 * and would make the status branches decorative (documented trap). */

var IRIS_CE_DRIVE_STATUS = {
    'available': '#f4c430',
    'in_use':    '#5e72e4',
    'wiped':     '#2dce89',
    'retired':   '#F25961'
};

function iris_ce_fetch_drive(barcode) {
    IRIS_CE.drives[barcode] = null;   /* in flight */
    fetch('/api/v2/dashboard/inventory/lookup?barcode=' +
          encodeURIComponent(barcode) + '&cid=' + iris_ce_cid(),
          {headers: {'Accept': 'application/json'}})
        .then(function (r) {
            if (r.status === 404) {
                IRIS_CE.drives[barcode] = 'notfound';
                if (!IRIS_CE.editing) iris_ce_render_detail();
                return null;
            }
            if (!r.ok) {
                IRIS_CE.drives[barcode] = 'failed';
                if (!IRIS_CE.editing) iris_ce_render_detail();
                return null;
            }
            return r.json().then(function (drive) {
                IRIS_CE.drives[barcode] = drive || 'failed';
                if (!IRIS_CE.editing) iris_ce_render_detail();
            });
        })
        .catch(function () {
            IRIS_CE.drives[barcode] = 'failed';
            if (!IRIS_CE.editing) iris_ce_render_detail();
        });
}

function iris_ce_inventory_tab_html(r) {
    if (!r.barcode) {
        return '<div class="text-muted" style="font-size:0.8rem; padding:6px 0;">' +
            (r.drive_id
                ? 'Linked to drive #' + r.drive_id + ' but no bar code is ' +
                  'recorded on this item — open Edit Evidence to set one.'
                : 'Not linked to an inventory drive. Set a bar code or ' +
                  'pick a drive in Edit Evidence.') + '</div>';
    }
    var d = IRIS_CE.drives[r.barcode];
    if (d === undefined) {
        iris_ce_fetch_drive(r.barcode);
        d = null;
    }
    if (d === null) {
        return '<div class="text-muted" style="font-size:0.8rem;">Looking up drive ' +
            iris_ce_esc(r.barcode) + '&hellip;</div>';
    }
    if (d === 'failed') {
        return '<div style="font-size:0.8rem; color:#fca5a5;">Could not look up the drive inventory.</div>';
    }
    if (d === 'notfound') {
        return '<div class="text-muted" style="font-size:0.8rem;">Bar code <code>' +
            iris_ce_esc(r.barcode) +
            '</code> matches no drive in the inventory.</div>';
    }
    var stColor = IRIS_CE_DRIVE_STATUS[String(d.status || '')
        .toLowerCase()] || '#9a9aa5';
    var html = '<div style="display:flex; align-items:center; gap:8px;">' +
        '<span style="color:#e8e8ee; font-weight:600; font-size:0.9rem;">' +
        iris_ce_esc(d.label || ('Drive #' + d.id)) + '</span>' +
        '<span class="iris-ce-chip" style="border-color:' + stColor +
        '55; color:' + stColor + ';">' +
        iris_ce_esc(String(d.status || 'unknown').replace('_', ' ')) +
        '</span></div>';
    var rows = [];
    if (d.barcode) rows.push(iris_ce_field('Bar code',
        iris_ce_esc(d.barcode), true));
    if (d.serial_number) rows.push(iris_ce_field('Serial',
        iris_ce_esc(d.serial_number), true));
    if (d.capacity) rows.push(iris_ce_field('Capacity',
        iris_ce_esc(d.capacity)));
    if (d.physical_location) rows.push(iris_ce_field('Location',
        iris_ce_esc(d.physical_location)));
    html += '<div style="margin-top:8px;">' + rows.join('') + '</div>';
    var rows2 = [];
    if (d.case && (d.case.case_name || d.case.case_id)) {
        rows2.push(iris_ce_field('Current case', iris_ce_esc(
            (d.case.case_name || ('#' + d.case.case_id)))));
    }
    if (d.created_by) rows2.push(iris_ce_field('Added by',
        iris_ce_esc(d.created_by)));
    var addedLbl = iris_ce_utc_label(d.date_added, true);
    if (addedLbl) rows2.push(iris_ce_field('Added', iris_ce_esc(addedLbl)));
    if (rows2.length) {
        html += '<div style="margin-top:8px;">' + rows2.join('') + '</div>';
    }
    if (d.notes) {
        html += '<div class="iris-ce-desc" style="white-space:pre-wrap;">' +
            iris_ce_esc(d.notes) + '</div>';
    }
    var others = (Array.isArray(d.evidences) ? d.evidences : [])
        .filter(function (e) { return e.id !== r.id; });
    html += '<div style="margin-top:12px;">' +
        '<span class="iris-ce-eyebrow">Also on this drive</span> ';
    if (!others.length) {
        html += '<span class="text-muted" style="font-size:0.76rem;">Nothing else — this is the only item.</span></div>';
    } else {
        html += '</div>' + others.map(function (e) {
            var same = String(e.case_id) === iris_ce_cid();
            return '<div style="display:flex; align-items:center; gap:8px; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.04); font-size:0.78rem;">' +
                (same
                    ? '<a href="#" class="iris-ce-drive-ev" data-ev-id="' +
                      e.id + '" style="color:#8fa3ef;"><code style="color:inherit; background:transparent;">' +
                      iris_ce_esc(e.filename) + '</code></a>'
                    : '<code style="color:#c8c8d0; background:transparent;">' +
                      iris_ce_esc(e.filename) + '</code>' +
                      '<span class="text-muted" style="font-size:0.68rem;">Case #' +
                      e.case_id + '</span>') +
                '<span class="text-muted" style="margin-left:auto; font-size:0.68rem;">' +
                iris_ce_esc(e.type_name || '') +
                (iris_ce_bytes(e.file_size)
                    ? ' &middot; ' + iris_ce_bytes(e.file_size) : '') +
                '</span></div>';
        }).join('');
    }
    return html;
}

function iris_ce_render_detail() {
    var box = document.getElementById('iris-ce-detail');
    var ph = document.getElementById('iris-ce-placeholder');
    if (!box) return;
    var r = iris_ce_sel_row();
    if (!r) {
        box.style.display = 'none';
        ph.style.display = '';
        return;
    }
    ph.style.display = 'none';
    box.style.display = '';

    var comments = IRIS_CE.comments[r.id];
    if (comments === undefined) iris_ce_load_comments(r.id);
    /* the Assets/IOCs tab counts need the catalog — kick the (guarded)
       fetch as soon as a detail with links renders */
    if (iris_ce_asset_ids(r).length) iris_ce_fetch_asset_catalog();

    var html =
        '<div style="display:flex; align-items:flex-start; gap:8px;">' +
        '<div style="flex:1 1 auto; min-width:0;">' +
        '<div style="color:#e8e8ee; font-weight:600; font-size:1.0rem; word-break:break-all;"><code>' +
        iris_ce_esc(r.filename) + '</code></div>' +
        '<div class="text-muted" style="font-size:0.74rem;">' +
        iris_ce_esc(iris_ce_type_name(r)) + ' &middot; #' + r.id + '</div>' +
        '</div>' +
        (IRIS_CE.editing
            ? '<button type="button" class="btn btn-sm btn-light iris-ce-edit-cancel">&times; Cancel</button>' +
              '<button type="button" class="btn btn-sm btn-primary iris-ce-edit-save">&#128190; Save Changes</button>'
            /* Share + Markdown link — the legacy modal's ⋮ actions, kept
               reachable on the v3 header (same functions, same deep
               link). */
            : '<button type="button" class="iris-ce-linkbtn" title="Copy shareable link" onclick="copy_object_link(' + r.id + ');"><i class="fa fa-share"></i></button>' +
              '<button type="button" class="iris-ce-linkbtn" title="Copy Markdown link" onclick="copy_object_link_md(\'evidence\', ' + r.id + ');"><i class="fa-brands fa-markdown"></i></button>' +
              '<button type="button" class="btn btn-sm btn-light iris-ce-edit-btn">&#9998; Edit Evidence</button>' +
              '<button type="button" class="btn btn-sm btn-danger" onclick="delete_rfile(' + r.id + ');">Delete</button>') +
        '</div>';

    var cCount = Array.isArray(comments) ? ' (' + comments.length + ')' : '';
    /* the IOC count is only claimed once the derivation actually ran */
    var dIocs = iris_ce_derived_iocs(r);
    var iCount = dIocs.state === 'ready' && iris_ce_asset_ids(r).length
        ? ' (' + dIocs.items.length + ')' : '';
    html += '<div class="iris-ce-dtabs">' +
        [['details', 'Details'],
         ['assets', 'Assets (' + iris_ce_asset_ids(r).length + ')'],
         ['iocs', 'IOCs' + iCount],
         ['inventory', 'Inventory'],
         ['comments', 'Comments' + cCount]]
            .map(function (t) {
                return '<button type="button" class="iris-ce-dtab' +
                    (IRIS_CE.tab === t[0] ? ' active' : '') +
                    '" data-tab="' + t[0] + '">' + t[1] + '</button>';
            }).join('') + '</div>';

    var body = '';
    if (IRIS_CE.editing && IRIS_CE.tab === 'details') {
        iris_ce_fetch_edit_catalogs();
        body += iris_ce_edit_form_html(r);
    } else if (IRIS_CE.tab === 'assets') {
        body += iris_ce_assets_tab_html(r);
    } else if (IRIS_CE.tab === 'iocs') {
        /* the derivation needs the asset catalog; the rows join the IOC
           catalog for type + TLP */
        if (iris_ce_asset_ids(r).length) iris_ce_fetch_asset_catalog();
        body += iris_ce_iocs_tab_html(r);
    } else if (IRIS_CE.tab === 'inventory') {
        body += iris_ce_inventory_tab_html(r);
    } else if (IRIS_CE.tab === 'comments') {
        if (comments === undefined || comments === null) {
            body += '<div class="text-muted" style="font-size:0.8rem;">Loading comments&hellip;</div>';
        } else if (comments === 'failed') {
            body += '<div style="font-size:0.8rem; color:#fca5a5;">Could not load the comments.</div>';
        } else {
            body += '<div class="iris-ce-clist">';
            body += comments.length
                ? comments.map(function (cm) {
                    var who = (cm.user && (cm.user.user_name ||
                        cm.user.user_login)) || '?';
                    var when = String(cm.comment_date || '')
                        .replace('T', ' ').slice(0, 16);
                    return '<div style="padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.05);">' +
                        '<div style="font-size:0.7rem; color:#9a9aa5;"><b style="color:#c8c8d0;">' +
                        iris_ce_esc(who) + '</b> &middot; ' +
                        iris_ce_esc(when) + '</div>' +
                        '<div style="font-size:0.8rem; color:#e8e8ee; white-space:pre-wrap;">' +
                        iris_ce_esc(cm.comment_text) + '</div></div>';
                }).join('')
                : '<div class="text-muted" style="font-size:0.8rem;">No comments yet.</div>';
            body += '</div>';
            body += '<div class="iris-ce-cfoot">' +
                '<input type="text" class="form-control form-control-sm" ' +
                'id="iris-ce-comment-input" placeholder="Add a comment..." ' +
                'autocomplete="off">' +
                '<button type="button" class="btn btn-sm btn-primary" ' +
                'onclick="iris_ce_post_comment(' + r.id +
                ');">Comment</button></div>';
        }
    } else {
        var size = iris_ce_bytes(r.file_size);
        var acq = iris_ce_utc_label(r.acquisition_date, true);
        body += '<div>' +
            iris_ce_field('Type', iris_ce_esc(iris_ce_type_name(r))) +
            (size ? iris_ce_field('Size',
                '<span title="' + iris_ce_esc(r.file_size) + ' bytes">' +
                iris_ce_esc(size) + '</span>') : '') +
            (acq ? iris_ce_field('Acquired', iris_ce_esc(acq)) : '') +
            '</div>';
        body += '<div style="margin-top:8px;">' +
            (r.file_hash
                ? iris_ce_field(iris_ce_hash_kind(r.file_hash),
                    iris_ce_esc(r.file_hash), true)
                /* the same figure the case-summary evidence specialist
                   counts — a finding, not a blank */
                : '<span class="iris-ce-nohash">No hash recorded</span>') +
            '</div>';
        var custody = [];
        if (r.created_by) {
            custody.push(iris_ce_field('Collected by',
                iris_ce_esc(r.created_by)));
        }
        if (r.barcode) {
            custody.push(iris_ce_field('Bar code',
                iris_ce_esc(r.barcode), true));
        }
        if (r.physical_location) {
            /* the drive's location — the route resolves it; the row's own
               column is deprecated */
            custody.push(iris_ce_field('Location',
                iris_ce_esc(r.physical_location)));
        }
        if (custody.length) {
            body += '<div style="margin-top:8px;">' + custody.join('') +
                '</div>';
        }
        var cs = iris_ce_utc_label(r.start_date, true);
        var ce = iris_ce_utc_label(r.end_date, true);
        if (cs || ce) {
            body += '<div style="margin-top:8px;">' +
                iris_ce_field('Coverage', iris_ce_esc(
                    (cs || '?') + ' → ' + (ce || '?'))) + '</div>';
        }
        body += iris_ce_desc_html(r);
        body += '<div class="iris-ce-foot">' +
            (iris_ce_utc_label(r.date_added, true)
                ? '<span>Added ' +
                  iris_ce_esc(iris_ce_utc_label(r.date_added, true)) +
                  '</span>' : '') +
            (r.user && r.user.user_name
                ? '<span>By ' + iris_ce_esc(r.user.user_name) + '</span>'
                : '') +
            '<span>ID #' + r.id + '</span>' +
            (r.file_uuid ? '<span>UUID <code style="color:#8fa3ef; background:transparent;">' +
                iris_ce_esc(r.file_uuid) + '</code></span>' : '') +
            '</div>';
    }

    var bodyCls = 'iris-ce-dbody' +
        (IRIS_CE.tab === 'comments' && Array.isArray(comments)
            ? ' iris-ce-dbody-split' : '');
    box.innerHTML = html + '<div class="' + bodyCls + '">' + body + '</div>';
    iris_ce_fit_soon();
    if (IRIS_CE.tab === 'comments') {
        var clist = box.querySelector('.iris-ce-clist');
        if (clist) clist.scrollTop = clist.scrollHeight;
    }
}

/* ---- Inline edit mode (v3): Edit Evidence flips the Details body into a
 * form; Cancel / Save Changes replace the header buttons. ⚠ Whether a
 * SUBSET payload is safe was settled BY EXPERIMENT: evidences/update loads
 * with instance= and NO partial=True — the shape that forced a curated
 * full payload on the ASSET path — but a probe (own row, own custom
 * attributes, own cleanup) proved description, hash, size, barcode,
 * created_by, dates AND custom_attributes all survive a
 * filename+type-only update. So the form posts only what it edits. The
 * modal stays reachable as "Full editor" for custom attributes, local
 * file hashing and the markdown preview. */

function iris_ce_fetch_edit_catalogs() {
    if (IRIS_CE.evidenceTypes === null) {
        IRIS_CE.evidenceTypes = [];   /* fetch in flight */
        fetch('/manage/evidence-types/list?cid=' + iris_ce_cid(),
              {headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.json(); })
            .then(function (resp) {
                IRIS_CE.evidenceTypes = (resp && resp.data) || [];
                if (IRIS_CE.editing) iris_ce_render_detail();
            })
            .catch(function () { /* select keeps the current value */ });
    }
    if (IRIS_CE.drivesCat === null) {
        IRIS_CE.drivesCat = [];
        fetch('/api/v2/dashboard/inventory/drives?cid=' + iris_ce_cid(),
              {headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.ok ? r.json() : []; })
            .then(function (resp) {
                /* v2 payload-direct: the response IS the list */
                IRIS_CE.drivesCat = Array.isArray(resp) ? resp : [];
                if (IRIS_CE.editing) iris_ce_render_detail();
            })
            .catch(function () { /* select keeps the current value */ });
    }
}

/* stored naive-UTC ISO -> the value a datetime-local input wants */
function iris_ce_dt_val(iso) {
    var m = String(iso || '')
        .match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/);
    return m ? m[1] + 'T' + m[2] : '';
}

function iris_ce_f_html(lbl, inner) {
    return '<div style="margin-top:10px;">' +
        '<div class="iris-ce-eyebrow" style="margin-bottom:3px;">' + lbl +
        '</div>' + inner + '</div>';
}

function iris_ce_edit_form_html(r) {
    var inp = function (id, val, ph) {
        return '<input type="text" class="form-control form-control-sm" id="' +
            id + '" value="' + iris_ce_esc(val == null ? '' : val) +
            '" placeholder="' + (ph || '') + '" autocomplete="off">';
    };
    var dt = function (id, val) {
        return '<input type="datetime-local" class="form-control form-control-sm" id="' +
            id + '" value="' + iris_ce_dt_val(val) + '">';
    };
    var typeOpts = (IRIS_CE.evidenceTypes || []).map(function (t) {
        return '<option value="' + t.id + '"' +
            (t.id === r.type_id ? ' selected' : '') + '>' +
            iris_ce_esc(t.name) + '</option>';
    }).join('');
    if (!typeOpts) {
        typeOpts = '<option value="' + (r.type_id || '') + '" selected>' +
            iris_ce_esc(iris_ce_type_name(r)) + ' (loading types…)</option>';
    }
    var driveOpts = '<option value=""' +
        (r.drive_id ? '' : ' selected') + '>&mdash; none &mdash;</option>' +
        (IRIS_CE.drivesCat || []).map(function (d) {
            return '<option value="' + d.id + '"' +
                (d.id === r.drive_id ? ' selected' : '') + '>' +
                iris_ce_esc((d.barcode || ('#' + d.id)) + ' — ' +
                    (d.label || '') +
                    (d.physical_location
                        ? ' (' + d.physical_location + ')' : '')) +
                '</option>';
        }).join('');
    if (r.drive_id && !(IRIS_CE.drivesCat || []).length) {
        driveOpts += '<option value="' + r.drive_id +
            '" selected>Drive #' + r.drive_id + ' (loading…)</option>';
    }
    return '<div id="iris-ce-edit-err" style="color:#fca5a5; font-size:0.76rem; display:none;"></div>' +
        iris_ce_f_html('Name *', inp('iris-ce-f-name', r.filename)) +
        '<div style="display:grid; grid-template-columns:1fr 1fr; gap:0 14px;">' +
        iris_ce_f_html('Type',
            '<select class="form-control form-control-sm" id="iris-ce-f-type">' +
            typeOpts + '</select>') +
        iris_ce_f_html('Size (bytes)', inp('iris-ce-f-size', r.file_size)) +
        '</div>' +
        iris_ce_f_html('Hash', inp('iris-ce-f-hash', r.file_hash)) +
        '<div style="display:grid; grid-template-columns:1fr 1fr; gap:0 14px;">' +
        iris_ce_f_html('Collected by',
            inp('iris-ce-f-collected', r.created_by)) +
        iris_ce_f_html('Bar code', inp('iris-ce-f-barcode', r.barcode)) +
        '</div>' +
        iris_ce_f_html('On physical drive',
            '<select class="form-control form-control-sm" id="iris-ce-f-drive">' +
            driveOpts + '</select>') +
        iris_ce_f_html('Acquisition date',
            dt('iris-ce-f-acquired', r.acquisition_date)) +
        '<div style="display:grid; grid-template-columns:1fr 1fr; gap:0 14px;">' +
        iris_ce_f_html('Coverage start', dt('iris-ce-f-start', r.start_date)) +
        iris_ce_f_html('Coverage end', dt('iris-ce-f-end', r.end_date)) +
        '</div>' +
        iris_ce_f_html('Description',
            '<textarea class="form-control form-control-sm" id="iris-ce-f-desc" rows="4">' +
            iris_ce_esc(r.file_description || '') + '</textarea>') +
        '<div style="margin-top:10px;">' +
        '<a href="#" class="iris-ce-fulledit" style="color:#8fa3ef; font-size:0.74rem;">Full editor (custom attributes, file hashing, markdown preview) &nearr;</a>' +
        '</div>';
}

function iris_ce_edit_err(msg) {
    var el = document.getElementById('iris-ce-edit-err');
    if (el) { el.textContent = msg; el.style.display = ''; }
}

function iris_ce_save_edit(r) {
    var val = function (id) {
        var el = document.getElementById(id);
        return el ? el.value : '';
    };
    var name = val('iris-ce-f-name').trim();
    if (!name) {
        /* refused client-side WITH a reason; the form stays as typed */
        iris_ce_edit_err('A name is required.');
        return;
    }
    var payload = {
        filename: name,
        type_id: parseInt(val('iris-ce-f-type'), 10) || r.type_id,
        file_hash: val('iris-ce-f-hash'),
        created_by: val('iris-ce-f-collected'),
        barcode: val('iris-ce-f-barcode'),
        file_description: val('iris-ce-f-desc'),
        csrf_token: iris_ce_csrf()
    };
    /* '' is rejected where the schema wants a number/date — send null
       (the modal's own drive_id coercion, applied to every such field) */
    var size = val('iris-ce-f-size').trim();
    payload.file_size = size === '' ? null : size;
    var drive = val('iris-ce-f-drive');
    payload.drive_id = drive === '' ? null : parseInt(drive, 10);
    ['acquisition_date', 'start_date', 'end_date'].forEach(function (k, i) {
        var v = val(['iris-ce-f-acquired', 'iris-ce-f-start',
                     'iris-ce-f-end'][i]);
        payload[k] = v === '' ? null : v;
    });
    fetch('/case/evidences/update/' + r.id + '?cid=' + iris_ce_cid(), {
        method: 'POST',
        headers: {'Accept': 'application/json',
                  'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    }).then(function (resp) { return resp.json(); })
        .then(function (resp) {
            if (resp && resp.status === 'success') {
                IRIS_CE.editing = false;
                /* refreshes the hidden legacy table AND the v3 panes */
                if (typeof window.get_case_rfiles === 'function') {
                    window.get_case_rfiles();
                } else { iris_ce_load(); }
            } else {
                /* a refused save does NOT re-render — the analyst's
                   values survive to correct and retry */
                iris_ce_edit_err((resp && resp.message) || 'Update failed');
            }
        })
        .catch(function () { iris_ce_edit_err('Update failed'); });
}

/* ---- wiring ---- */

document.addEventListener('DOMContentLoaded', function () {
    if (!document.getElementById('iris-ce-list')) return;
    iris_ce_fit_card();
    window.addEventListener('scroll', iris_ce_fit_soon, {passive: true});
    window.addEventListener('resize', iris_ce_fit_soon);

    /* Modal saves and deletes call get_case_rfiles(); wrap it so the v3
       panes refresh too (established monkey-patch idiom). The legacy
       $(document).ready fires get_case_rfiles() right after this handler,
       so with the wrapper installed a direct iris_ce_load() here would
       fetch the same payload a second time — load directly ONLY when the
       legacy module is absent. */
    if (typeof window.get_case_rfiles === 'function') {
        var orig = window.get_case_rfiles;
        window.get_case_rfiles = function () {
            orig();
            iris_ce_load();
        };
    } else {
        iris_ce_load();
    }

    var refresh = document.getElementById('iris-ce-refresh');
    if (refresh) {
        refresh.addEventListener('click', function () {
            /* an explicit refresh re-pulls the joined catalogs too */
            IRIS_CE.assetCatalog = null;
            IRIS_CE.assetCatalogLoaded = false;
            IRIS_CE.assetCatalogFailed = false;
            IRIS_CE.iocCat = null;
            IRIS_CE.iocCatFailed = false;
            IRIS_CE.drives = {};
            /* the wrapped loader refreshes the hidden legacy table AND
               the v3 panes */
            if (typeof window.get_case_rfiles === 'function') {
                window.get_case_rfiles();
            } else { iris_ce_load(); }
        });
    }

    var search = document.getElementById('iris-ce-search');
    if (search) {
        search.addEventListener('input', function () {
            IRIS_CE.q = this.value.trim().toLowerCase();
            iris_ce_render_list();
        });
    }

    document.getElementById('iris-ce-list')
        .addEventListener('click', function (e) {
            var row = e.target.closest('.iris-ce-row');
            if (!row) return;
            IRIS_CE.sel = parseInt(row.getAttribute('data-ev-id'), 10);
            IRIS_CE.tab = 'details';
            IRIS_CE.editing = false;   /* switching items discards a form */
            iris_ce_render_list();
            iris_ce_render_detail();
        });

    document.getElementById('iris-ce-detail')
        .addEventListener('click', function (e) {
            var sel = iris_ce_sel_row();
            var tab = e.target.closest('.iris-ce-dtab');
            if (tab) {
                /* leaving the form discards it (v3 Assets behaviour) */
                IRIS_CE.editing = false;
                IRIS_CE.tab = tab.getAttribute('data-tab');
                iris_ce_render_detail();
                return;
            }
            if (e.target.closest('.iris-ce-edit-btn') && sel) {
                IRIS_CE.editing = true;
                IRIS_CE.tab = 'details';
                iris_ce_render_detail();
                return;
            }
            if (e.target.closest('.iris-ce-edit-cancel')) {
                IRIS_CE.editing = false;
                iris_ce_render_detail();
                return;
            }
            if (e.target.closest('.iris-ce-edit-save') && sel) {
                iris_ce_save_edit(sel);
                return;
            }
            var full = e.target.closest('.iris-ce-fulledit');
            if (full && sel) {
                e.preventDefault();
                edit_rfiles(sel.id);
                return;
            }
            /* a same-case item on the drive selects in place */
            var dev = e.target.closest('.iris-ce-drive-ev');
            if (dev) {
                e.preventDefault();
                IRIS_CE.sel = parseInt(dev.getAttribute('data-ev-id'), 10);
                IRIS_CE.tab = 'details';
                iris_ce_render_list();
                iris_ce_render_detail();
            }
        });

    document.getElementById('iris-ce-detail')
        .addEventListener('keydown', function (e) {
            if (e.key === 'Enter'
                    && e.target.id === 'iris-ce-comment-input'
                    && IRIS_CE.sel !== null) {
                iris_ce_post_comment(IRIS_CE.sel);
            }
        });

    /* guarded — the Assets tab's unguarded copy of this binding once
       silently killed everything below it */
    var legacyToggle = document.getElementById('iris-ce-legacy-toggle');
    if (legacyToggle) {
        legacyToggle.addEventListener('click', function (e) {
            e.preventDefault();
            var legacy = document.getElementById('iris-ce-legacy');
            var toolbar = document.getElementById('iris-ce-legacy-toolbar');
            if (!legacy) return;
            var showing = legacy.style.display !== 'none';
            legacy.style.display = showing ? 'none' : '';
            if (toolbar) toolbar.style.display = showing ? 'none' : '';
            this.textContent = showing
                ? 'Show legacy table' : 'Hide legacy table';
        });
    }
});

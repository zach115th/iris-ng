/* v3 Assets master/detail (case Assets tab). Vanilla JS — renders before
 * jQuery. Data comes from the same /case/assets/filter payload the legacy
 * DataTable eats; Add/Edit/Delete go through the EXISTING modal functions
 * (add_assets / asset_details / delete_asset), so all asset machinery —
 * IOC links, evidence links, compromise status, comments, history — is
 * untouched. The legacy table stays in the DOM hidden as a safety valve. */

var IRIS_CA = {rows: [], sel: null, q: '', tab: 'details',
               tl: [], comments: {},
               caseIocs: null, iocTypes: null,
               iocMenu: false, iocq: '', iocMenuQ: '',
               caseEvidence: null,
               evMenu: false, evq: '', evMenuQ: '',
               editing: false, assetTypes: null, analysisStatuses: null,
               tagSugg: null, profiles: {}};

var IRIS_CA_COMP = {
    0: {label: 'To be determined', cls: 'iris-ca-comp-0', color: '#9a9aa5'},
    1: {label: 'Compromised', cls: 'iris-ca-comp-1', color: '#F25961'},
    2: {label: 'Not compromised', cls: 'iris-ca-comp-2', color: '#2dce89'},
    3: {label: 'Unknown', cls: 'iris-ca-comp-3', color: '#9a9aa5'}
};

/* Size the detail card so its bottom edge stops just above the AI chat
 * bar. This cannot be pure CSS: the card is position:sticky, so its top
 * is only `top:70px` once the page has scrolled far enough to pin it —
 * at rest it sits wherever the case header leaves it, and a height
 * derived from a fixed offset overshoots by exactly that difference.
 * Measure both edges instead. The CSS calc remains as a no-JS fallback. */
function iris_ca_fit_card() {
    var card = document.querySelector('.iris-ca-right');
    if (!card || !card.getBoundingClientRect) return;
    var top = card.getBoundingClientRect().top;
    /* The input row is the chat bar's persistent bottom element — the
       conversation panel opens ABOVE it, so this edge does not move. */
    var form = document.getElementById('iris-chat-form');
    var limit = (form && form.getBoundingClientRect)
        ? form.getBoundingClientRect().top
        : (window.innerHeight || 800) - 18;
    var h = Math.max(220, Math.round(limit - top - 14)) + 'px';
    /* write-only-on-change: an unchanged write still invalidates layout,
       forcing the next geometry read (ours or jQuery's) to reflow */
    if (card.style.height !== h) card.style.height = h;
}

var IRIS_CA_FIT_PENDING = false;

function iris_ca_fit_soon() {
    if (IRIS_CA_FIT_PENDING) return;
    IRIS_CA_FIT_PENDING = true;
    var run = function () {
        IRIS_CA_FIT_PENDING = false;
        iris_ca_fit_card();
    };
    if (window.requestAnimationFrame) window.requestAnimationFrame(run);
    else setTimeout(run, 16);
}

function iris_ca_esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return {'&': '&amp;', '<': '&lt;', '>': '&gt;',
                '"': '&quot;', "'": '&#39;'}[c];
    });
}

function iris_ca_cid() {
    var m = window.location.search.match(/[?&]cid=(\d+)/);
    return m ? m[1] : '1';
}

function iris_ca_comp(row) {
    var id = row.asset_compromise_status_id;
    return IRIS_CA_COMP[id] || IRIS_CA_COMP[3];
}

function iris_ca_type_name(row) {
    return (row.asset_type && row.asset_type.asset_name)
        ? row.asset_type.asset_name : (row.asset_type || '');
}

function iris_ca_tags(row) {
    return String(row.asset_tags || '').split(',')
        .map(function (t) { return t.trim(); })
        .filter(function (t) { return t; });
}

function iris_ca_load() {
    fetch('/case/assets/filter?cid=' + iris_ca_cid(),
          {headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (resp) {
            var data = (resp && resp.data) || {};
            IRIS_CA.rows = data.assets || [];
            document.getElementById('iris-ca-loading').style.display = 'none';
            iris_ca_render_list();
            /* Keep the selected asset fresh after an edit-modal save. */
            if (IRIS_CA.sel !== null) {
                var still = IRIS_CA.rows.some(function (r2) {
                    return r2.asset_id === IRIS_CA.sel; });
                if (still) iris_ca_render_detail();
                else iris_ca_clear_detail();
            }
        })
        .catch(function () {
            document.getElementById('iris-ca-loading').textContent =
                'Failed to load assets.';
        });
    iris_ca_load_timeline();
}

/* Timeline events for the detail Timeline tab — one fetch per page load
 * from the SAME endpoint that feeds the master timeline (advanced-filter,
 * NOT /events/list — project rule). Per-event assets carry no id, only
 * the "<name> (<Type>)" label the projection builds, so matching is by
 * that exact string. */
function iris_ca_load_timeline() {
    fetch('/case/timeline/advanced-filter?cid=' + iris_ca_cid() +
          '&q=%7B%7D', {headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (resp) {
            IRIS_CA.tl = ((resp && resp.data) || {}).tim || [];
            if (IRIS_CA.sel !== null) iris_ca_render_detail();
        })
        .catch(function () { /* tab shows an empty state */ });
}

function iris_ca_tl_for(r) {
    var label = (r.asset_name || '') + ' (' + iris_ca_type_name(r) + ')';
    return IRIS_CA.tl.filter(function (ev) {
        return (ev.assets || []).some(function (a) {
            return a && a.name === label;
        });
    });
}

function iris_ca_load_comments(assetId) {
    fetch('/case/assets/' + assetId + '/comments/list?cid=' +
          iris_ca_cid(), {headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (resp) {
            IRIS_CA.comments[assetId] = (resp && resp.data) || [];
            if (IRIS_CA.sel === assetId) iris_ca_render_detail();
        })
        .catch(function () { IRIS_CA.comments[assetId] = []; });
}

/* ---- IOCs tab: search / link / unlink / inline new IOC ----
 * Link + unlink round-trip through the REAL asset update endpoint
 * (/case/assets/update/<id>) with a curated full payload built from the
 * filter row — same machinery as the edit modal (history entry, module
 * hooks, registry sync), proven by probe before this was written. */

function iris_ca_csrf() {
    var el = document.getElementById('csrf_token');
    return el ? el.value : '';
}

function iris_ca_linked_ids(r) {
    return (Array.isArray(r.ioc_links) ? r.ioc_links : [])
        .map(function (i) { return i.ioc_id; });
}

/* One save path for both link kinds: the update endpoint only touches a
 * link set that is PRESENT in the payload (ioc_links via hasattr,
 * evidence_links via `in request_data`), so `extra` carries exactly the
 * set being changed and the other stays untouched. */
function iris_ca_save_asset_links(r, extra, done) {
    var payload = {
        asset_name: r.asset_name,
        asset_type_id: r.asset_type_id,
        analysis_status_id: r.analysis_status_id,
        asset_ip: r.asset_ip || '',
        asset_domain: r.asset_domain || '',
        asset_info: r.asset_info || '',
        asset_description: r.asset_description || '',
        asset_tags: r.asset_tags || '',
        csrf_token: iris_ca_csrf()
    };
    Object.keys(extra).forEach(function (k) { payload[k] = extra[k]; });
    if (r.asset_compromise_status_id !== null
            && r.asset_compromise_status_id !== undefined) {
        payload.asset_compromise_status_id = r.asset_compromise_status_id;
    }
    fetch('/case/assets/update/' + r.asset_id + '?cid=' + iris_ca_cid(), {
        method: 'POST',
        headers: {'Accept': 'application/json',
                  'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    }).then(function (resp) { return resp.json(); })
        .then(function (resp) {
            if (resp && resp.status === 'success') {
                if (done) done();
                /* wrapped: refreshes the hidden legacy table AND the v3
                   panes */
                if (typeof window.get_case_assets === 'function') {
                    window.get_case_assets();
                } else { iris_ca_load(); }
            } else {
                /* no re-render on failure — an edit form keeps its
                   values so the analyst can correct and retry */
                window.alert((resp && resp.message) || 'Update failed');
            }
        })
        .catch(function () { window.alert('Update failed'); });
}

function iris_ca_save_ioc_links(r, ids) {
    iris_ca_save_asset_links(r, {ioc_links: ids});
}

function iris_ca_save_evidence_links(r, ids) {
    iris_ca_save_asset_links(r, {evidence_links: ids});
}

function iris_ca_linked_ev_ids(r) {
    return (Array.isArray(r.evidence_links) ? r.evidence_links : [])
        .map(function (e) { return e.evidence_id; });
}

function iris_ca_fetch_evidence_catalog() {
    if (IRIS_CA.caseEvidence !== null) return;
    IRIS_CA.caseEvidence = [];   /* fetch in flight */
    fetch('/case/evidences/list?cid=' + iris_ca_cid(),
          {headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (resp) {
            IRIS_CA.caseEvidence =
                ((resp && resp.data) || {}).evidences || [];
            iris_ca_render_detail();
        })
        .catch(function () { IRIS_CA.caseEvidence = []; });
}

function iris_ca_bytes(n) {
    n = parseInt(n, 10);
    if (isNaN(n) || n < 0) return null;
    var u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'], i = 0, v = n;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1; }
    return (i === 0 ? v : (v >= 10 ? v.toFixed(0) : v.toFixed(1))) +
        ' ' + u[i];
}

function iris_ca_hash_kind(h) {
    var L = String(h || '').length;
    return L === 32 ? 'MD5' : L === 40 ? 'SHA1'
         : L === 64 ? 'SHA256' : L === 128 ? 'SHA512' : 'hash';
}

function iris_ca_utc_label(iso, withTime) {
    /* Evidence timestamps are naive-UTC storage — label the STORED value,
       never re-zone it through new Date(). */
    var m = String(iso || '')
        .match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/);
    if (!m) return null;
    var s = IRIS_CA_MONTHS[parseInt(m[2], 10) - 1] + ' ' +
        parseInt(m[3], 10) + ', ' + m[1];
    if (withTime && m[4]) s += ' ' + m[4] + ':' + m[5] + ' UTC';
    return s;
}

function iris_ca_ev_meta(id) {
    var cat = IRIS_CA.caseEvidence || [];
    for (var i = 0; i < cat.length; i += 1) {
        if (cat[i].id === id) return cat[i];
    }
    return null;   /* catalog not loaded yet, or item no longer visible */
}

function iris_ca_ev_rows_html(r) {
    var q = IRIS_CA.evq;
    var rows = (Array.isArray(r.evidence_links) ? r.evidence_links : [])
        .filter(function (e) {
            var m = iris_ca_ev_meta(e.evidence_id);
            var hay = (String(e.filename || '') + ' ' +
                (m ? String(m.file_description || '') + ' ' +
                     String((m.type || {}).name || '') + ' ' +
                     String(m.file_hash || '') : '')).toLowerCase();
            return !q || hay.indexOf(q) !== -1;
        });
    if (!rows.length) {
        return '<div class="text-muted" style="font-size:0.8rem; padding:6px 0;">' +
            (q ? 'No linked evidence matches the search.'
               : 'No evidence linked to this asset.') + '</div>';
    }
    return rows.map(function (e) {
        var m = iris_ca_ev_meta(e.evidence_id);
        var href = '/case/evidences?cid=' + iris_ca_cid() +
            '&shared=' + e.evidence_id;
        var head =
            '<div style="display:flex; align-items:center; gap:8px;">' +
            '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#7a7a85" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/><path d="M14 2v5h5"/></svg>' +
            '<a href="' + href + '" title="Open this evidence item" ' +
            'style="text-decoration:none; min-width:0;"><code style="color:#2dce89;">' +
            iris_ca_esc(e.filename) + '</code></a>' +
            (m && m.type && m.type.name
                ? '<span class="iris-ca-tag" style="margin-top:0;">' +
                  iris_ca_esc(m.type.name) + '</span>' : '') +
            '<button type="button" class="iris-ca-ev-unlink" data-evidence-id="' +
            e.evidence_id + '" title="Unlink from this asset" ' +
            'style="margin-left:auto; background:transparent; border:none; color:#7a7a85; cursor:pointer; font-size:0.9rem;">&times;</button>' +
            '</div>';
        /* Only claim things about the item once its catalog row is in hand —
           a missing catalog is not evidence of a missing hash. */
        if (!m) return '<div style="padding:5px 0 5px 4px; border-bottom:1px solid rgba(255,255,255,0.04);">' +
            head + '</div>';
        var bits = [];
        var size = iris_ca_bytes(m.file_size);
        if (size) bits.push('<span>' + size + '</span>');
        if (m.file_hash) {
            bits.push('<span title="' + iris_ca_esc(m.file_hash) + '">' +
                iris_ca_hash_kind(m.file_hash) + ' <code style="color:#8fa3ef;">' +
                iris_ca_esc(String(m.file_hash).slice(0, 10)) +
                '&hellip;</code></span>');
        } else {
            /* forensically load-bearing: an unhashed item is a finding,
               not a blank */
            bits.push('<span style="color:#f4c430;">&#9888; No hash recorded</span>');
        }
        if (m.physical_location) {
            bits.push('<span title="Physical location of the linked drive">&#128193; ' +
                iris_ca_esc(m.physical_location) +
                (m.barcode ? ' &middot; ' + iris_ca_esc(m.barcode) : '') +
                '</span>');
        }
        var added = iris_ca_utc_label(m.date_added, true);
        if (added) {
            bits.push('<span>Added ' + iris_ca_esc(added) +
                ((m.user && m.user.user_name)
                    ? ' by ' + iris_ca_esc(m.user.user_name) : '') +
                '</span>');
        }
        if (m.created_by) {
            bits.push('<span title="Chain of custody: who collected it">' +
                'Collected by ' + iris_ca_esc(m.created_by) + '</span>');
        }
        var acq = iris_ca_utc_label(m.acquisition_date, true);
        if (acq) bits.push('<span>Acquired ' + iris_ca_esc(acq) + '</span>');
        var s = iris_ca_utc_label(m.start_date, true),
            en = iris_ca_utc_label(m.end_date, true);
        if (s || en) {
            bits.push('<span title="Evidence coverage window">&#8986; ' +
                iris_ca_esc(s || '?') + ' &rarr; ' +
                iris_ca_esc(en || '?') + '</span>');
        }
        return '<div style="padding:5px 0 6px 4px; border-bottom:1px solid rgba(255,255,255,0.04);">' +
            head +
            (m.file_description
                ? '<div style="color:#c8c8d0; font-size:0.74rem; margin:2px 0 0 21px;">' +
                  iris_ca_esc(m.file_description) + '</div>' : '') +
            '<div style="display:flex; flex-wrap:wrap; gap:4px 12px; color:#9a9aa5; font-size:0.7rem; margin:3px 0 0 21px;">' +
            bits.join('') + '</div></div>';
    }).join('');
}

function iris_ca_ev_menuitems_html(r) {
    var linked = iris_ca_linked_ev_ids(r);
    var q = IRIS_CA.evMenuQ;
    var avail = (IRIS_CA.caseEvidence || []).filter(function (e) {
        return linked.indexOf(e.id) === -1 &&
            (!q || String(e.filename || '').toLowerCase()
                .indexOf(q) !== -1);
    });
    return avail.length
        ? avail.map(function (e) {
            var sub = [(e.type || {}).name, iris_ca_bytes(e.file_size)]
                .filter(Boolean).join(' · ');
            return '<a href="#" class="iris-ca-ev-linkitem" data-evidence-id="' +
                e.id + '" style="display:block; padding:4px 12px; color:#c8c8d0; font-size:0.78rem; text-decoration:none;"><code style="color:#2dce89;">' +
                iris_ca_esc(e.filename) + '</code>' +
                (sub ? '<div class="text-muted" style="font-size:0.66rem;">' +
                    iris_ca_esc(sub) + '</div>' : '') + '</a>';
        }).join('')
        : '<div class="text-muted" style="font-size:0.74rem; padding:4px 12px;">' +
          (q ? 'No match.'
             : 'Every evidence item is already linked.') + '</div>';
}

function iris_ca_ev_tab_html(r) {
    var menu = '';
    if (IRIS_CA.evMenu) {
        menu =
            '<div id="iris-ca-evmenu" class="iris-cshell-menu" style="display:block; left:auto; right:0; min-width:260px; max-height:320px; overflow-y:auto;">' +
            '<div style="padding:4px 12px;"><input type="text" class="form-control form-control-sm" id="iris-ca-ev-menuq" placeholder="Filter evidence..." autocomplete="off" value="' +
            iris_ca_esc(IRIS_CA.evMenuQ) + '"></div>' +
            '<div id="iris-ca-ev-menuitems">' +
            iris_ca_ev_menuitems_html(r) + '</div>' +
            /* registering evidence needs the upload modal — that lives on
               the Evidence tab, so link there rather than half-rebuild it */
            '<div class="iris-cshell-mh">New</div>' +
            '<a href="/case/evidences?cid=' + iris_ca_cid() +
            '" style="display:block; padding:4px 12px; color:#8fa3ef; font-size:0.76rem; text-decoration:none;">Register new evidence &nearr;</a>' +
            '</div>';
    }
    return '<div style="display:flex; gap:6px; align-items:center; margin-bottom:6px;">' +
        '<input type="text" class="form-control form-control-sm" id="iris-ca-ev-search" placeholder="Search evidence..." autocomplete="off" value="' +
        iris_ca_esc(IRIS_CA.evq) + '" style="flex:1 1 auto;">' +
        '<div class="iris-cshell-menuwrap">' +
        '<button type="button" class="iris-cshell-btn" id="iris-ca-ev-linkbtn">&#128279; Link evidence &#9662;</button>' +
        menu + '</div></div>' +
        '<div id="iris-ca-ev-rows">' + iris_ca_ev_rows_html(r) + '</div>';
}

/* ---- Inline edit mode (v3): Edit Asset flips the Details body into a
 * form; Cancel / Save Changes replace Edit/Delete in the header. Saves
 * ride the same curated update path as everything else. The full modal
 * stays reachable ("Full editor") for custom attributes + markdown
 * preview. */

function iris_ca_fetch_edit_catalogs() {
    if (IRIS_CA.assetTypes === null) {
        IRIS_CA.assetTypes = [];   /* fetch in flight */
        fetch('/manage/asset-type/list?cid=' + iris_ca_cid(),
              {headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.json(); })
            .then(function (resp) {
                IRIS_CA.assetTypes = (resp && resp.data) || [];
                if (IRIS_CA.editing) iris_ca_render_detail();
            })
            .catch(function () { IRIS_CA.assetTypes = []; });
    }
    if (IRIS_CA.analysisStatuses === null) {
        IRIS_CA.analysisStatuses = [];
        fetch('/manage/analysis-status/list?cid=' + iris_ca_cid(),
              {headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.json(); })
            .then(function (resp) {
                IRIS_CA.analysisStatuses = (resp && resp.data) || [];
                if (IRIS_CA.editing) iris_ca_render_detail();
            })
            .catch(function () { IRIS_CA.analysisStatuses = []; });
    }
}

function iris_ca_field_html(label, inner) {
    return '<div><div style="color:#9a9aa5; font-size:0.72rem; margin-bottom:3px;">' +
        label + '</div>' + inner + '</div>';
}

function iris_ca_select_html(id, options, selected) {
    return '<select class="form-control form-control-sm" id="' + id + '">' +
        options.map(function (o) {
            return '<option value="' + o[0] + '"' +
                (o[0] === selected ? ' selected' : '') + '>' +
                iris_ca_esc(o[1]) + '</option>';
        }).join('') + '</select>';
}

function iris_ca_edit_form_html(r) {
    var typeOpts = (IRIS_CA.assetTypes || []).map(function (t) {
        return [t.asset_id, t.asset_name]; });
    var anaOpts = (IRIS_CA.analysisStatuses || []).map(function (a) {
        return [a.id, a.name]; });
    var compOpts = Object.keys(IRIS_CA_COMP).map(function (k) {
        return [parseInt(k, 10), IRIS_CA_COMP[k].label]; });
    var compSel = (r.asset_compromise_status_id === null
        || r.asset_compromise_status_id === undefined)
        ? 0 : r.asset_compromise_status_id;
    var inp = function (id, value, ph) {
        return '<input type="text" class="form-control form-control-sm" id="' +
            id + '" value="' + iris_ca_esc(value || '') + '"' +
            (ph ? ' placeholder="' + ph + '"' : '') +
            ' autocomplete="off">';
    };
    return '<div style="display:grid; grid-template-columns:1fr 1fr; gap:10px 14px; margin-top:6px;">' +
        iris_ca_field_html('Asset Name',
            inp('iris-ca-f-name', r.asset_name)) +
        iris_ca_field_html('Asset Type',
            iris_ca_select_html('iris-ca-f-type', typeOpts,
                r.asset_type_id)) +
        iris_ca_field_html('Analysis Status',
            iris_ca_select_html('iris-ca-f-analysis', anaOpts,
                r.analysis_status_id)) +
        iris_ca_field_html('Compromise Status',
            iris_ca_select_html('iris-ca-f-comp', compOpts, compSel)) +
        '</div>' +
        '<div style="color:#9a9aa5; font-size:0.72rem; margin:10px 0 3px;">Description</div>' +
        '<textarea class="form-control form-control-sm" id="iris-ca-f-desc" rows="4">' +
        iris_ca_esc(r.asset_description || '') + '</textarea>' +
        '<div style="color:#e8e8ee; font-weight:600; font-size:0.82rem; margin:12px 0 6px;">Network Information</div>' +
        '<div style="display:grid; grid-template-columns:1fr 1fr; gap:10px 14px;">' +
        iris_ca_field_html('IP Address', inp('iris-ca-f-ip', r.asset_ip)) +
        iris_ca_field_html('Domain', inp('iris-ca-f-domain',
            r.asset_domain)) +
        '</div>' +
        '<div style="margin-top:10px;">' +
        iris_ca_field_html('Tags' + iris_ca_tagsugg_pill_html(r),
            inp('iris-ca-f-tags', r.asset_tags, 'Add a tag...')) +
        iris_ca_tagsugg_results_html(r) + '</div>' +
        '<div style="margin-top:10px;">' +
        '<a href="#" onclick="asset_details(' + r.asset_id +
        ');return false;" style="color:#8fa3ef; font-size:0.74rem;">Full editor (custom attributes, markdown preview) &nearr;</a>' +
        '</div>';
}

/* The Tags field uses the product's OWN tag widget (amsifySuggestags via
 * set_suggest_tags) rather than a plain text input, so it gets chips for
 * multiple tags and autocomplete against /manage/tags/suggest — which
 * includes the bundled MISP taxonomies and galaxies. The plugin keeps the
 * original input in sync (val = tagNames.join(',')), so the save path
 * reads it unchanged. Both the plugin and set_suggest_tags load page-wide
 * from the layout, but this degrades to the plain input if either is
 * absent rather than leaving a dead field. */
/* ---- AI asset profile.
 *
 * A short read of the asset built server-side from its own fields plus
 * everything linked to it (indicators, evidence, timeline events, analyst
 * comments). Cached as a case_ai_artifact keyed asset_profile:<id>, so a
 * second visit is free; the model is only asked when the underlying data
 * changed or the analyst clicks Re-run. Nothing is persisted when the call
 * fails — an error cached as content outlives its cause. */
function iris_ca_md(md) {
    /* Render markdown on the ESCAPED string: the only tags in the output
       are the ones this function introduces, so model output can never
       inject markup. */
    var s = iris_ca_esc(String(md || '')).replace(/\r\n/g, '\n');
    s = s.replace(/`([^`\n]+)`/g,
        '<code style="background:rgba(255,255,255,0.06); padding:0 4px; border-radius:3px;">$1</code>');
    s = s.replace(/\*\*([^*\n]+)\*\*/g, '<b style="color:#e8e8ee;">$1</b>');
    return s.split(/\n{2,}/).map(function (para) {
        var lines = para.split('\n').filter(function (l) {
            return l.trim(); });
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

function iris_ca_profile_state(r) {
    return (r && IRIS_CA.profiles[r.asset_id]) || null;
}

function iris_ca_profile_fetch(r) {
    /* Cached read only — never triggers a generation, so merely opening an
       asset costs nothing. */
    if (IRIS_CA.profiles[r.asset_id]) return;
    IRIS_CA.profiles[r.asset_id] = {state: 'loading'};
    fetch('/api/v2/cases/' + iris_ca_cid() + '/ai/assets/' +
          r.asset_id + '/profile', {credentials: 'same-origin',
                                    headers: {'Accept': 'application/json'}})
        .then(function (resp) {
            if (resp.status === 404) return null;
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.json();
        })
        .then(function (art) {
            IRIS_CA.profiles[r.asset_id] = art
                ? {state: 'ok', art: art, cached: true}
                : {state: 'none'};
            iris_ca_render_detail();
        })
        .catch(function () {
            /* a failed cache READ is not a failed generation — fall back to
               the invitation rather than showing an error */
            IRIS_CA.profiles[r.asset_id] = {state: 'none'};
            iris_ca_render_detail();
        });
}

function iris_ca_profile_gen(r, force) {
    var csrf = iris_ca_csrf();
    IRIS_CA.profiles[r.asset_id] = {state: 'busy'};
    iris_ca_render_detail();
    fetch('/api/v2/cases/' + iris_ca_cid() + '/ai/assets/' + r.asset_id +
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
        IRIS_CA.profiles[r.asset_id] = {state: 'ok', art: res.json,
                                        cached: false};
        iris_ca_render_detail();
    }).catch(function (e) {
        IRIS_CA.profiles[r.asset_id] = {state: 'error',
                                        error: (e.message || String(e))};
        iris_ca_render_detail();
    });
}

function iris_ca_short_err(msg) {
    /* Upstream backends return whole JSON envelopes (a rate-limit payload
       runs to several hundred characters). Show the readable head, keep the
       full text in the title. */
    var s = String(msg || '').replace(/\s+/g, ' ').trim();
    var m = s.match(/"message"\s*:\s*"([^"]{8,})"/);
    if (m) s = m[1];
    return s.length > 180 ? s.slice(0, 180) + '…' : s;
}

function iris_ca_profile_html(r) {
    var st = iris_ca_profile_state(r);
    if (!st || st.state === 'loading') return '';
    if (st.state === 'busy') {
        return '<div class="iris-ca-prof"><div class="iris-ca-prof-h">&#x2728; Asset profile</div>' +
            '<div class="text-muted" style="font-size:0.78rem;">Reading the asset and everything linked to it&hellip;</div></div>';
    }
    if (st.state === 'none') {
        return '<div class="iris-ca-prof"><div class="iris-ca-prof-h">&#x2728; Asset profile</div>' +
            '<div class="text-muted" style="font-size:0.78rem;">No profile yet. ' +
            '<a href="#" class="iris-ca-prof-gen" style="color:#a78bfa;">Generate one</a> ' +
            'from this asset\'s details, linked indicators, evidence, timeline events and comments.</div></div>';
    }
    if (st.state === 'error') {
        return '<div class="iris-ca-prof"><div class="iris-ca-prof-h">&#x2728; Asset profile</div>' +
            '<div style="font-size:0.78rem; color:#fca5a5;" title="' +
            iris_ca_esc(st.error) + '">Could not generate: ' +
            iris_ca_esc(iris_ca_short_err(st.error)) + '</div>' +
            '<div style="margin-top:6px;"><a href="#" class="iris-ca-prof-gen" style="color:#a78bfa; font-size:0.74rem;">Try again</a></div></div>';
    }
    var a = st.art || {};
    var when = String(a.generated_at || '').replace('T', ' ').slice(0, 16);
    return '<div class="iris-ca-prof">' +
        '<div class="iris-ca-prof-h">&#x2728; Asset profile</div>' +
        '<div class="iris-ca-prof-body">' +
        iris_ca_md(a.content || a.ai_content || '') + '</div>' +
        '<div class="iris-ca-prof-f">' +
        iris_ca_esc([a.model, a.prompt_id, when].filter(Boolean).join(' · ')) +
        (st.cached ? ' · cached' : '') +
        ' &middot; <a href="#" class="iris-ca-prof-rerun" style="color:#a78bfa;">Re-run</a></div>' +
        '</div>';
}

/* ---- AI tag suggester in the inline editor.
 *
 * Reuses the EXISTING surface: same POST /api/v2/cases/<cid>/ai/tag-suggestion
 * contract, same validated MISP taxonomy + galaxy output, same visual
 * treatment, and the same trick for adding a tag to an amsifySuggestags
 * input. Only the client wiring is re-expressed here — the shared Jinja
 * partial binds its handlers at page-parse time against fixed DOM ids, so
 * it cannot attach to a form this file renders after the fact, and its
 * object_id is frozen at include time while ours changes per selection.
 * Distinct `iris-ca-tagsugg-*` ids so the modal's copy can coexist.
 * Suggestions live in state, so a re-render does not lose them. */
function iris_ca_tagsugg_state(r) {
    /* Suggestions belong to ONE asset — never show another's against it. */
    var st = IRIS_CA.tagSugg;
    return (st && r && st.assetId === r.asset_id) ? st : null;
}

function iris_ca_tagsugg_pill_html(r) {
    var st = iris_ca_tagsugg_state(r) || {};
    return ' <button type="button" id="iris-ca-tagsugg-pill" ' +
        'title="Ask the AI for MISP taxonomy + galaxy tags based on this asset" ' +
        'style="background:rgba(139,92,246,0.18); border:1px solid rgba(139,92,246,0.45); color:#d4c4ff; font-size:11px; line-height:1; padding:3px 8px; border-radius:999px; cursor:pointer;"' +
        (st.busy ? ' disabled' : '') + '>&#x2728; Suggest tags</button>' +
        '<span id="iris-ca-tagsugg-status" style="font-size:11px; margin-left:8px; color:' +
        (st.statusColor || '#94a3b8') + ';">' +
        iris_ca_esc(st.status || '') + '</span>';
}

function iris_ca_tagsugg_results_html(r) {
    var st = iris_ca_tagsugg_state(r);
    if (!st || !st.items) return '';
    if (!st.items.length) {
        return '<div style="margin-top:8px; font-size:11px; color:#94a3b8;">No high-confidence suggestions.</div>';
    }
    var chips = st.items.map(function (s) {
        /* colour by KIND from a fixed map — never interpolate a server
           string into a style attribute */
        var c = (s.kind === 'galaxy')
            ? ['rgba(245,158,11,0.12)', 'rgba(245,158,11,0.35)', '#fbbf24']
            : ['rgba(139,92,246,0.12)', 'rgba(139,92,246,0.35)', '#d4c4ff'];
        var taken = st.accepted && st.accepted[s.tag];
        var conf = (typeof s.confidence === 'number')
            ? Math.round(s.confidence * 100) + '%' : '';
        return '<button type="button" class="iris-ca-tagsugg-chip" data-tag="' +
            iris_ca_esc(s.tag) + '" title="' +
            iris_ca_esc(s.reason || s.expanded || '') + '" ' +
            'style="background:' + c[0] + '; border:1px solid ' + c[1] +
            '; color:' + c[2] + '; font-size:11px; padding:3px 10px; border-radius:999px; cursor:pointer; display:inline-flex; align-items:center; gap:6px;' +
            (taken ? ' opacity:0.45; pointer-events:none;' : '') + '">' +
            (taken ? '&#10003;' : '+') +
            ' <code style="background:transparent; color:inherit; font-size:11px; padding:0;">' +
            iris_ca_esc(s.tag) + '</code><span style="font-size:9px; opacity:0.7;">' +
            iris_ca_esc(conf) + '</span></button>';
    }).join('');
    return '<div style="margin-top:8px; padding:8px 10px; background:#15151a; border:1px solid rgba(139,92,246,0.35); border-radius:8px;">' +
        '<div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center;">' +
        '<span style="font-size:11px; color:#94a3b8; margin-right:4px;">Suggested:</span>' +
        chips +
        '<button type="button" id="iris-ca-tagsugg-all" class="btn btn-sm btn-link" style="font-size:11px; padding:0 8px; color:#a78bfa;">+ add all</button>' +
        '</div></div>';
}

function iris_ca_tagsugg_add(tag) {
    /* amsifySuggestags exposes no addTag through jQuery, so drive its keyup
       handler on the visible input — the same approach the shared partial
       and the ATT&CK suggester use. Falls back to the raw input when the
       widget is not initialised. */
    var el = document.getElementById('iris-ca-f-tags');
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

function iris_ca_tagsugg_run(r) {
    var csrf = iris_ca_csrf();
    IRIS_CA.tagSugg = {assetId: r.asset_id, busy: true, items: null,
                       accepted: {}, status: 'Asking the model...',
                       statusColor: '#a78bfa'};
    iris_ca_render_detail();
    fetch('/api/v2/cases/' + iris_ca_cid() + '/ai/tag-suggestion', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
        body: JSON.stringify({object_type: 'asset',
                              object_id: r.asset_id, csrf_token: csrf})
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
        IRIS_CA.tagSugg = {
            assetId: r.asset_id, busy: false, items: items, accepted: {},
            status: items.length
                ? '(' + items.length + ' suggestion' +
                  (items.length === 1 ? '' : 's') +
                  (d.model ? ' · ' + d.model : '') + ')'
                : '(no suggestions above 0.5 confidence)',
            statusColor: '#94a3b8'};
        iris_ca_render_detail();
    }).catch(function (e) {
        /* surface the real reason — a silent no-op reads as a dead button,
           and "no AI backend configured" is the likeliest cause */
        IRIS_CA.tagSugg = {assetId: r.asset_id, busy: false, items: null,
                           accepted: {},
                           status: 'Error: ' + (e.message || e),
                           statusColor: '#fca5a5'};
        iris_ca_render_detail();
    });
}

function iris_ca_init_tag_widget() {
    var el = document.getElementById('iris-ca-f-tags');
    if (!el || el.getAttribute('data-iris-tagged') === '1') return;
    if (typeof window.set_suggest_tags !== 'function' || !window.jQuery
        || !window.jQuery.fn || !window.jQuery.fn.amsifySuggestags) return;
    el.setAttribute('data-iris-tagged', '1');
    window.set_suggest_tags('iris-ca-f-tags');
}

function iris_ca_read_tags() {
    var el = document.getElementById('iris-ca-f-tags');
    if (!el) return '';
    var parts = String(el.value || '').split(',');
    /* A tag typed but not yet committed with Enter/comma lives in the
       widget's own input, which the plugin inserts directly after ours.
       Clicking Save straight after typing must not silently drop it. */
    var area = el.nextElementSibling;
    var pending = area
        ? area.querySelector('.amsify-suggestags-input') : null;
    if (pending && pending.value) parts = parts.concat(pending.value.split(','));
    var seen = {};
    return parts.map(function (t) { return t.trim(); })
        .filter(function (t) {
            if (!t || seen[t]) return false;
            seen[t] = 1;
            return true;
        }).join(',');
}

function iris_ca_save_edit(r) {
    var val = function (id) {
        var el = document.getElementById(id);
        return el ? el.value : '';
    };
    var name = val('iris-ca-f-name').trim();
    if (!name) { window.alert('Asset name is required'); return; }
    var tags = iris_ca_read_tags();
    iris_ca_save_asset_links(r, {
        asset_name: name,
        asset_type_id: parseInt(val('iris-ca-f-type'), 10),
        analysis_status_id: parseInt(val('iris-ca-f-analysis'), 10),
        asset_compromise_status_id: parseInt(val('iris-ca-f-comp'), 10),
        asset_description: val('iris-ca-f-desc'),
        asset_ip: val('iris-ca-f-ip').trim(),
        asset_domain: val('iris-ca-f-domain').trim(),
        asset_tags: tags
    }, function () { IRIS_CA.editing = false; });
}

/* ---- Timeline tab (v3): header w/ Add event + Open full timeline,
 * date-separator pills, rail dots, cards with time / category chip / #id,
 * title, content, asset + IOC chips. Event CRUD machinery lives in the
 * timeline page bundle, so the actions navigate there (overlay rule). */

var IRIS_CA_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function iris_ca_tl_daylabel(dstr) {
    /* dstr = 'YYYY-MM-DD' (naive UTC storage — label the stored date,
       don't re-zone it) */
    var p = dstr.split('-');
    var label = IRIS_CA_MONTHS[parseInt(p[1], 10) - 1] + ' ' +
        parseInt(p[2], 10);
    var now = new Date();
    var today = now.getFullYear() + '-' +
        String(now.getMonth() + 1).padStart(2, '0') + '-' +
        String(now.getDate()).padStart(2, '0');
    return dstr === today ? 'Today &middot; ' + label
                          : label + ', ' + p[0];
}

/* Hover action icons (v3): flag toggles LIVE via the legacy GET
 * /case/timeline/events/flag/<id>; edit / comment / open deep-link to
 * the full timeline's ?shared=<id> (scroll + highlight — the event
 * modal machinery lives in that bundle), branch links to the Graph. */
function iris_ca_tl_actions_html(ev) {
    var shared = '/case/timeline?cid=' + iris_ca_cid() +
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
    return '<span class="iris-ca-tlacts" style="margin-left:auto; display:inline-flex; align-items:center; gap:6px;">' +
        link(shared, 'Edit in timeline',
             '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>') +
        link('/case/graph?cid=' + iris_ca_cid(), 'View in graph',
             '<line x1="6" x2="6" y1="3" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>') +
        '<button type="button" class="iris-ca-tl-flag" data-event-id="' +
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

function iris_ca_tl_card_html(ev) {
    /* the colour lands in a style attribute — validate, never interpolate
     * free text (CSS injection surface) */
    var raw = ev.event_color || '';
    var color = /^#[0-9a-fA-F]{3,8}$/.test(raw) ? raw : '#8B5CF6';
    var chips = (ev.assets || []).map(function (a) {
        var label = String(a.name || '').replace(/ \([^)]*\)$/, '');
        return '<span style="border:1px solid rgba(244,196,48,0.4); color:#f4c430; border-radius:8px; padding:0 8px; font-size:0.68rem;">&#128737; ' +
            iris_ca_esc(label) + '</span>';
    }).concat((ev.iocs || []).map(function (i) {
        return '<span style="border:1px solid rgba(242,89,97,0.4); color:#F25961; border-radius:8px; padding:0 8px; font-size:0.68rem;">&#9678; ' +
            iris_ca_esc(i.name) + '</span>';
    })).join(' ');
    return '<div style="display:flex; gap:10px; margin:8px 0;">' +
        '<span style="width:9px; height:9px; border-radius:50%; background:' +
        color + '; flex-shrink:0; margin-top:14px;"></span>' +
        '<div class="iris-ca-tlcard" style="flex:1 1 auto; min-width:0; background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06); border-left:3px solid ' +
        color + '; border-radius:10px; padding:8px 12px;">' +
        '<div style="display:flex; align-items:center; gap:8px;">' +
        '<code style="color:#8fa3ef; font-size:0.72rem;">' +
        iris_ca_esc(String(ev.event_date || '').slice(11, 19)) + '</code>' +
        '<span style="border:1px solid rgba(143,163,239,0.4); color:#8fa3ef; border-radius:8px; padding:0 8px; font-size:0.66rem;">' +
        iris_ca_esc(ev.category_name || 'Unspecified') + '</span>' +
        '<span class="text-muted" style="font-size:0.68rem;">#' +
        ev.event_id + '</span>' +
        iris_ca_tl_actions_html(ev) + '</div>' +
        '<div style="color:#e8e8ee; font-size:0.84rem; font-weight:600; margin-top:2px;">' +
        iris_ca_esc(ev.event_title) + '</div>' +
        (ev.event_content
            ? '<div style="color:#9a9aa5; font-size:0.74rem;">' +
              iris_ca_esc(String(ev.event_content).slice(0, 180)) + '</div>'
            : '') +
        (chips ? '<div style="margin-top:5px; display:flex; gap:5px; flex-wrap:wrap;">' +
            chips + '</div>' : '') +
        '</div></div>';
}

function iris_ca_tl_tab_html(tlRows) {
    var tlUrl = '/case/timeline?cid=' + iris_ca_cid();
    var html =
        '<div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">' +
        '<span style="color:#e8e8ee; font-weight:600; font-size:0.9rem;">Timeline</span>' +
        '<span class="text-muted" style="font-size:0.74rem;">' +
        tlRows.length + ' event' + (tlRows.length === 1 ? '' : 's') +
        '</span>' +
        '<span style="margin-left:auto; display:inline-flex; align-items:center; gap:10px;">' +
        /* opens the timeline page's REAL add-event modal IN PLACE (shared
           event_modal.js + a local container), this asset preselected —
           the preset id is validated server-side */
        '<a class="iris-cshell-btn" style="text-decoration:none;" href="#" ' +
        'onclick="add_event(null, {asset: ' + IRIS_CA.sel +
        '}); return false;">+ Add event</a>' +
        '<a style="color:#8fa3ef; font-size:0.76rem; text-decoration:none;" href="' +
        tlUrl + '">Open full timeline &rarr;</a></span></div>';
    if (!tlRows.length) {
        return html +
            '<div class="text-muted" style="font-size:0.8rem; padding:6px 0;">No timeline events reference this asset.</div>';
    }
    var days = {};
    var order = [];
    tlRows.slice().sort(function (a, b) {
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
            iris_ca_tl_daylabel(d) + '</span>' +
            '<span style="flex:1; border-top:1px solid rgba(255,255,255,0.07);"></span></div>' +
            days[d].map(iris_ca_tl_card_html).join('');
    });
    return html;
}

function iris_ca_fetch_ioc_catalogs() {
    if (IRIS_CA.caseIocs === null) {
        IRIS_CA.caseIocs = [];   /* fetch in flight */
        fetch('/case/ioc/list?cid=' + iris_ca_cid(),
              {headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.json(); })
            .then(function (resp) {
                IRIS_CA.caseIocs = ((resp && resp.data) || {}).ioc || [];
                iris_ca_render_detail();
            })
            .catch(function () { IRIS_CA.caseIocs = []; });
    }
    if (IRIS_CA.iocTypes === null) {
        IRIS_CA.iocTypes = [];
        fetch('/manage/ioc-types/list?cid=' + iris_ca_cid(),
              {headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.json(); })
            .then(function (resp) {
                IRIS_CA.iocTypes = (resp && resp.data) || [];
                iris_ca_render_detail();
            })
            .catch(function () { IRIS_CA.iocTypes = []; });
    }
}

/* TLP badge colours — known names only, no server string interpolated
 * into styles (same rule as iris_corr_tlp_badge). */
var IRIS_CA_TLP = {
    'red':          '#F25961',
    'amber':        '#f4c430',
    'amber strict': '#f4c430',
    'green':        '#2dce89',
    'clear':        '#c8c8d0',
    'white':        '#c8c8d0'
};

function iris_ca_tlp_badge(name) {
    var key = String(name || '').toLowerCase();
    var color = IRIS_CA_TLP[key];
    if (!color) return '';
    var label = key.split(' ').map(function (w) {
        return w.charAt(0).toUpperCase() + w.slice(1); }).join(' ');
    return '<span style="border:1px solid ' + color + '55; color:' + color +
        '; border-radius:9px; padding:0 8px; font-size:0.68rem; white-space:nowrap;">TLP:' +
        label + '</span>';
}

/* v3: linked IOCs grouped by type — "aba-rtn (1)" header, then rows of
 * value / type-subtitle / TLP badge / unlink. Type + TLP come from the
 * case IOC catalog joined by id (link rows carry only id + value); until
 * that fetch lands the rows render ungrouped and re-render on arrival. */
function iris_ca_ioc_rows_html(r) {
    var q = IRIS_CA.iocq;
    var byId = {};
    (IRIS_CA.caseIocs || []).forEach(function (i) {
        byId[i.ioc_id] = i; });
    var rows = (Array.isArray(r.ioc_links) ? r.ioc_links : [])
        .filter(function (i) {
            var full = byId[i.ioc_id];
            var hay = (String(i.ioc_value || '') + ' ' +
                (full ? String(full.ioc_type || '') : '') + ' ' +
                (full ? (full.note_links || []).map(function (n) {
                    return n.note_title; }).join(' ') : '')).toLowerCase();
            return !q || hay.indexOf(q) !== -1;
        });
    if (!rows.length) {
        return '<div class="text-muted" style="font-size:0.8rem; padding:6px 0;">' +
            (q ? 'No linked IOCs match the search.'
               : 'No IOCs linked to this asset.') + '</div>';
    }
    var groups = {};
    rows.forEach(function (i) {
        var full = byId[i.ioc_id];
        var t = (full && full.ioc_type) || '';
        (groups[t] = groups[t] || []).push(i);
    });
    return Object.keys(groups).sort().map(function (t) {
        var head = t
            ? '<div style="display:flex; align-items:center; gap:6px; margin:8px 0 2px;">' +
              '<span style="color:#9a9aa5; font-size:0.74rem; font-weight:600;">' +
              iris_ca_esc(t) + '</span>' +
              '<span style="border:1px solid rgba(255,255,255,0.12); border-radius:8px; padding:0 7px; color:#9a9aa5; font-size:0.66rem;">' +
              groups[t].length + '</span></div>'
            : '';
        return head + groups[t].map(function (i) {
            var full = byId[i.ioc_id];
            /* note-provenance pills (ioc_note_link) — the established
               inverse-view chip: violet, deep-links ?shared=<note_id> */
            var notes = (full && Array.isArray(full.note_links))
                ? full.note_links : [];
            var pills = notes.slice(0, 3).map(function (n) {
                return '<a class="iris-ca-notepill" href="/case/notes?cid=' +
                    iris_ca_cid() + '&shared=' + n.note_id + '" title="' +
                    iris_ca_esc(n.note_title) +
                    '" style="border:1px solid rgba(139,92,246,0.35); background:rgba(139,92,246,0.12); color:#d4c4ff; border-radius:8px; padding:0 8px; font-size:0.66rem; text-decoration:none; white-space:nowrap;">&#128221; ' +
                    iris_ca_esc(String(n.note_title || 'note')
                        .slice(0, 24)) +
                    (String(n.note_title || '').length > 24
                        ? '&hellip;' : '') + '</a>';
            }).join('');
            if (notes.length > 3) {
                pills += '<span class="text-muted" style="font-size:0.66rem;">+' +
                    (notes.length - 3) + '</span>';
            }
            return '<div style="display:flex; align-items:center; gap:8px; padding:5px 0 5px 4px; border-bottom:1px solid rgba(255,255,255,0.04);">' +
                '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#7a7a85" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/></svg>' +
                '<div style="min-width:0;">' +
                '<div style="color:#e8e8ee; font-size:0.8rem; font-weight:600; overflow:hidden; text-overflow:ellipsis;">' +
                iris_ca_esc(i.ioc_value) + '</div>' +
                (full && full.ioc_type
                    ? '<div class="text-muted" style="font-size:0.68rem;">' +
                      iris_ca_esc(full.ioc_type) + '</div>' : '') +
                '</div>' +
                (pills ? '<span style="display:inline-flex; align-items:center; gap:4px; flex-wrap:wrap; margin-left:4px;">' +
                    pills + '</span>' : '') +
                '<span style="margin-left:auto; display:inline-flex; align-items:center; gap:8px;">' +
                (full ? iris_ca_tlp_badge(full.tlp_name) : '') +
                '<button type="button" class="iris-ca-ioc-unlink" data-ioc-id="' +
                i.ioc_id + '" title="Unlink from this asset" ' +
                'style="background:transparent; border:none; color:#7a7a85; cursor:pointer; font-size:0.9rem;">&times;</button>' +
                '</span></div>';
        }).join('');
    }).join('');
}

function iris_ca_ioc_menuitems_html(r) {
    var linked = iris_ca_linked_ids(r);
    var q = IRIS_CA.iocMenuQ;
    var avail = (IRIS_CA.caseIocs || []).filter(function (i) {
        return linked.indexOf(i.ioc_id) === -1 &&
            (!q || String(i.ioc_value || '').toLowerCase()
                .indexOf(q) !== -1);
    });
    return avail.length
        ? avail.map(function (i) {
            return '<a href="#" class="iris-ca-ioc-linkitem" data-ioc-id="' +
                i.ioc_id + '" style="display:block; padding:4px 12px; color:#c8c8d0; font-size:0.78rem; text-decoration:none;"><code style="color:#e08fb9;">' +
                iris_ca_esc(i.ioc_value) + '</code> <span class="text-muted" style="font-size:0.68rem;">' +
                iris_ca_esc(i.ioc_type || '') + '</span></a>';
        }).join('')
        : '<div class="text-muted" style="font-size:0.74rem; padding:4px 12px;">' +
          (q ? 'No match.' : 'Every case IOC is already linked.') + '</div>';
}

function iris_ca_ioc_tab_html(r) {
    var menu = '';
    if (IRIS_CA.iocMenu) {
        var typeOpts = (IRIS_CA.iocTypes || []).map(function (t) {
            return '<option value="' + t.type_id + '">' +
                iris_ca_esc(t.type_name) + '</option>';
        }).join('');
        menu =
            '<div id="iris-ca-iocmenu" class="iris-cshell-menu" style="display:block; left:auto; right:0; min-width:260px; max-height:320px; overflow-y:auto;">' +
            '<div style="padding:4px 12px;"><input type="text" class="form-control form-control-sm" id="iris-ca-ioc-menuq" placeholder="Filter case IOCs..." autocomplete="off" value="' +
            iris_ca_esc(IRIS_CA.iocMenuQ) + '"></div>' +
            '<div id="iris-ca-ioc-menuitems">' +
            iris_ca_ioc_menuitems_html(r) + '</div>' +
            '<div class="iris-cshell-mh">New IOC</div>' +
            '<div style="padding:2px 12px 8px; display:flex; flex-direction:column; gap:5px;">' +
            '<input type="text" class="form-control form-control-sm" id="iris-ca-ioc-newval" placeholder="IOC value" autocomplete="off">' +
            '<select class="form-control form-control-sm" id="iris-ca-ioc-newtype">' +
            typeOpts + '</select>' +
            '<button type="button" class="btn btn-sm btn-primary" id="iris-ca-ioc-newbtn">Add &amp; link</button>' +
            '</div></div>';
    }
    return '<div style="display:flex; gap:6px; align-items:center; margin-bottom:6px;">' +
        '<input type="text" class="form-control form-control-sm" id="iris-ca-ioc-search" placeholder="Search IOCs..." autocomplete="off" value="' +
        iris_ca_esc(IRIS_CA.iocq) + '" style="flex:1 1 auto;">' +
        '<div class="iris-cshell-menuwrap">' +
        '<button type="button" class="iris-cshell-btn" id="iris-ca-ioc-linkbtn">&#128279; Link IOC &#9662;</button>' +
        menu + '</div></div>' +
        '<div id="iris-ca-ioc-rows">' + iris_ca_ioc_rows_html(r) + '</div>';
}

function iris_ca_new_ioc_and_link(r) {
    var val = document.getElementById('iris-ca-ioc-newval');
    var typ = document.getElementById('iris-ca-ioc-newtype');
    if (!val || !val.value.trim() || !typ || !typ.value) return;
    fetch('/case/ioc/add?cid=' + iris_ca_cid(), {
        method: 'POST',
        headers: {'Accept': 'application/json',
                  'Content-Type': 'application/json'},
        body: JSON.stringify({
            ioc_value: val.value.trim(),
            ioc_type_id: parseInt(typ.value, 10),
            /* the modal defaults TLP to amber; omitting writes NULL
               (documented trap) */
            ioc_tlp_id: 2,
            ioc_description: '', ioc_tags: '',
            csrf_token: iris_ca_csrf()})
    }).then(function (resp) { return resp.json(); })
        .then(function (resp) {
            if (resp && resp.status === 'success' && resp.data
                    && resp.data.ioc_id) {
                IRIS_CA.caseIocs = null;   /* refetch next open */
                IRIS_CA.iocMenu = false;
                iris_ca_save_ioc_links(r,
                    iris_ca_linked_ids(r).concat([resp.data.ioc_id]));
            } else {
                window.alert((resp && resp.message) || 'IOC add failed');
            }
        })
        .catch(function () { window.alert('IOC add failed'); });
}

function iris_ca_post_comment(assetId) {
    var box = document.getElementById('iris-ca-comment-input');
    if (!box || !box.value.trim()) return;
    var csrf = document.getElementById('csrf_token');
    fetch('/case/assets/' + assetId + '/comments/add?cid=' + iris_ca_cid(), {
        method: 'POST',
        headers: {'Accept': 'application/json',
                  'Content-Type': 'application/json'},
        body: JSON.stringify({comment_text: box.value,
                              csrf_token: csrf ? csrf.value : ''})
    }).then(function (r) { return r.json(); })
        .then(function (resp) {
            if (resp && resp.status === 'success') {
                delete IRIS_CA.comments[assetId];
                iris_ca_load_comments(assetId);
            } else {
                window.alert((resp && resp.message) || 'Comment failed');
            }
        })
        .catch(function () { window.alert('Comment failed'); });
}

function iris_ca_visible() {
    var q = IRIS_CA.q;
    return IRIS_CA.rows.filter(function (r) {
        if (!q) return true;
        var hay = ((r.asset_name || '') + ' ' + iris_ca_type_name(r) + ' ' +
            (r.asset_ip || '') + ' ' + (r.asset_domain || '') + ' ' +
            (r.asset_description || '') + ' ' + (r.asset_tags || ''))
            .toLowerCase();
        return hay.indexOf(q) !== -1;
    });
}

/* ---------------------------------------------------------------- CSV export

   The header and field shapes are the IMPORT contract, read out of
   case_assets_routes.py::case_upload_assets rather than chosen for display:
   that endpoint hardcodes the header line and compares the first line against
   it, resolves asset_type_name by NAME (lowercased) via get_asset_type_id,
   and reformats tags with .replace('|', ','), so tags travel PIPE-separated.
   Exporting anything else produces a file the product's own importer cannot
   read.

   Unlike the IOC importer, this one guards a short row properly (it sets
   missing_field and continues the OUTER loop), so a missing column is
   reported per row rather than raising. All six columns are emitted anyway —
   a row the importer rejects is no more useful than one that crashes it. */

const IRIS_CA_CSV_HEADER =
    'asset_name,asset_type_name,asset_description,asset_ip,asset_domain,asset_tags';

function iris_ca_csv_rows(rows) {
    var out = [IRIS_CA_CSV_HEADER];
    rows.forEach(function (r) {
        out.push([
            iris_csv_cell(r.asset_name),
            iris_csv_cell(iris_ca_type_name(r)),
            iris_csv_cell(r.asset_description),
            iris_csv_cell(r.asset_ip),
            iris_csv_cell(r.asset_domain),
            iris_csv_cell(iris_ca_tags(r).join('|'))
        ].join(','));
    });
    return out.join('\n');
}

function iris_ca_export_csv() {
    var rows = iris_ca_visible();
    /* A header-only file is indistinguishable from a failed export, so name
       which of the two happened instead of handing one over. */
    if (!rows.length) {
        notify_error(IRIS_CA.q
            ? 'No assets match the current search — nothing to export.'
            : 'This case has no assets to export.');
        return;
    }
    var name = 'case-' + iris_ca_cid() + '-assets'
        + (IRIS_CA.q ? '-filtered' : '') + '.csv';
    download_file(name, 'text/csv', iris_ca_csv_rows(rows));

    /* The filter is named in the FILENAME, not only in this notification — a
       partial export outlives the toast that described it. */
    var msg = rows.length + ' asset' + (rows.length === 1 ? '' : 's')
        + ' exported' + (IRIS_CA.q ? ' (search filter applied)' : '') + '.';
    var flattened = rows.filter(function (r) {
        return /[\r\n]/.test(String(r.asset_description || '')); }).length;
    if (flattened) {
        msg += ' ' + flattened + ' description'
            + (flattened === 1 ? '' : 's')
            + ' flattened to a single line for CSV.';
    }
    notify_success(msg);
}

/* v3 list-row indicator cluster: compromise (chip when compromised,
 * state icon otherwise), analysis-status clock coloured by name, and an
 * explicit has-IOCs / no-IOCs indicator. Tooltips carry the state names
 * — an icon without a title is a guessing game. */
function iris_ca_rowicon(paths, color, title) {
    return '<span title="' + iris_ca_esc(title) +
        '" style="color:' + color + '; display:inline-flex;">' +
        '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        paths + '</svg></span>';
}

function iris_ca_analysis_color(name) {
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

function iris_ca_row_icons_html(r) {
    var out = '';
    var comp = iris_ca_comp(r);
    var compId = (r.asset_compromise_status_id === null
        || r.asset_compromise_status_id === undefined)
        ? 0 : r.asset_compromise_status_id;
    if (compId === 1) {
        out += '<span class="iris-ca-comp-chip ' + comp.cls +
            '" style="border-color:' + comp.color + '55; color:' +
            comp.color + ';">' + comp.label + '</span>';
    } else if (compId === 2) {
        out += iris_ca_rowicon(
            '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
            '#2dce89', 'Not compromised');
    } else if (compId === 3) {
        out += iris_ca_rowicon(
            '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" x2="12.01" y1="17" y2="17"/>',
            '#9a9aa5', 'Compromise: unknown');
    } else {
        out += iris_ca_rowicon(
            '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
            '#f4c430', 'Compromise: to be determined');
    }
    var ana = (r.analysis_status && r.analysis_status.name)
        ? r.analysis_status.name : 'Unspecified';
    out += iris_ca_rowicon(
        '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
        iris_ca_analysis_color(ana), 'Analysis: ' + ana);
    var nIocs = Array.isArray(r.ioc_links) ? r.ioc_links.length : 0;
    if (nIocs) {
        out += '<span title="' + nIocs + ' linked IOC' +
            (nIocs === 1 ? '' : 's') +
            '" style="color:#e08fb9; display:inline-flex; align-items:center; gap:3px; font-size:0.72rem;">' +
            '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m8 2 1.88 1.88"/><path d="M14.12 3.88 16 2"/><path d="M9 7.13v-1a3.003 3.003 0 1 1 6 0v1"/><path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6"/><path d="M12 20v-9"/><path d="M6.53 9C4.6 8.8 3 7.1 3 5"/><path d="M6 13H2"/><path d="M3 21c0-2.1 1.7-3.9 3.8-4"/><path d="M20.97 5c0 2.1-1.6 3.8-3.5 4"/><path d="M22 13h-4"/><path d="M17.2 17c2.1.1 3.8 1.9 3.8 4"/></svg><b>' +
            nIocs + '</b></span>';
    } else {
        out += iris_ca_rowicon(
            '<path d="m2 2 20 20"/><path d="M5 5a1 1 0 0 0-1 1v7c0 5 3.5 7.5 7.66 8.95a1 1 0 0 0 .67.01c2.35-.82 4.48-1.97 5.9-3.71"/><path d="M9.309 3.652A12.252 12.252 0 0 0 11.24 2.28a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1v7a9.784 9.784 0 0 1-.08 1.264"/>',
            '#55555e', 'No IOCs linked');
    }
    return '<span style="display:inline-flex; align-items:center; gap:7px; flex-shrink:0; margin-left:8px;">' +
        out + '</span>';
}

function iris_ca_render_list() {
    var rows = iris_ca_visible();
    document.getElementById('iris-ca-count').textContent =
        IRIS_CA.rows.length ? '(' + IRIS_CA.rows.length + ')' : '';
    document.getElementById('iris-ca-none').style.display =
        IRIS_CA.rows.length ? 'none' : '';
    document.getElementById('iris-ca-list').innerHTML =
        rows.map(function (r) {
            var comp = iris_ca_comp(r);
            var meta = ['<span>' + iris_ca_esc(iris_ca_type_name(r)) +
                '</span>'];
            if (r.asset_ip) {
                meta.push('<code>' + iris_ca_esc(r.asset_ip) + '</code>');
            }
            if (r.asset_domain) {
                meta.push('<code>' + iris_ca_esc(r.asset_domain) +
                    '</code>');
            }
            if (r.asset_description) {
                meta.push('<span>' + iris_ca_esc(
                    String(r.asset_description).slice(0, 60)) + '</span>');
            }
            var tags = iris_ca_tags(r).slice(0, 6).map(function (t) {
                return '<span class="iris-ca-tag">' + iris_ca_esc(t) +
                    '</span>';
            }).join('');
            return '<div class="iris-ca-row' +
                (IRIS_CA.sel === r.asset_id ? ' active' : '') +
                '" data-asset-id="' + r.asset_id +
                '" style="border-left-color:' + comp.color + ';">' +
                '<div style="display:flex; align-items:flex-start;">' +
                '<div style="flex:1 1 auto; min-width:0;">' +
                '<div class="iris-ca-name">' + iris_ca_esc(r.asset_name) +
                '</div>' +
                '<div class="iris-ca-meta">' + meta.join(' &middot; ') +
                '</div>' + (tags ? '<div>' + tags + '</div>' : '') +
                '</div>' + iris_ca_row_icons_html(r) +
                '</div></div>';
        }).join('');
}

function iris_ca_clear_detail() {
    IRIS_CA.sel = null;
    document.getElementById('iris-ca-detail').style.display = 'none';
    document.getElementById('iris-ca-placeholder').style.display = '';
    iris_ca_render_list();
}

function iris_ca_render_detail() {
    var r = IRIS_CA.rows.find(function (x) {
        return x.asset_id === IRIS_CA.sel; });
    if (!r) { iris_ca_clear_detail(); return; }
    document.getElementById('iris-ca-placeholder').style.display = 'none';
    var box = document.getElementById('iris-ca-detail');
    box.style.display = '';
    var comp = iris_ca_comp(r);
    var iocs = Array.isArray(r.ioc_links) ? r.ioc_links : [];
    var evLinks = Array.isArray(r.evidence_links) ? r.evidence_links : [];
    var tlRows = iris_ca_tl_for(r);
    var comments = IRIS_CA.comments[r.asset_id];
    if (comments === undefined) {
        IRIS_CA.comments[r.asset_id] = null;   /* fetch in flight */
        iris_ca_load_comments(r.asset_id);
    }
    var analysis = (r.analysis_status && r.analysis_status.name)
        ? r.analysis_status.name : 'Unspecified';
    /* v3: the compromise chip sits in the detail HEADER next to the name. */
    var html =
        '<div style="display:flex; align-items:flex-start; gap:8px;">' +
        '<div style="flex:1 1 auto; min-width:0;">' +
        '<div style="color:#e8e8ee; font-weight:600; font-size:1.02rem;">' +
        iris_ca_esc(r.asset_name) +
        ' <span class="iris-ca-comp-chip ' + comp.cls +
        '" style="border-color:' + comp.color + '55; color:' + comp.color +
        '; vertical-align:2px; margin-left:6px;">' + comp.label +
        '</span></div>' +
        '<div class="text-muted" style="font-size:0.74rem;">' +
        iris_ca_esc(iris_ca_type_name(r)) + ' &middot; #' + r.asset_id +
        '</div></div>' +
        (IRIS_CA.editing
            ? '<button type="button" class="btn btn-sm btn-light iris-ca-edit-cancel">&times; Cancel</button>' +
              '<button type="button" class="btn btn-sm btn-primary iris-ca-edit-save">&#128190; Save Changes</button>'
            : /* Share + Markdown link — the legacy modal's ⋮ actions, kept
                 reachable on the v3 header (same functions, same deep link). */
              '<button type="button" class="iris-ca-linkbtn" title="Copy shareable link" onclick="copy_object_link(' + r.asset_id + ');"><i class="fa fa-share"></i></button>' +
              '<button type="button" class="iris-ca-linkbtn" title="Copy Markdown link" onclick="copy_object_link_md(\'asset\', ' + r.asset_id + ');"><i class="fa-brands fa-markdown"></i></button>' +
              '<button type="button" class="iris-ca-prof-btn" title="AI profile of this asset, from its details and everything linked to it">&#x2728;</button>' +
              '<button type="button" class="btn btn-sm btn-light iris-ca-edit-btn">&#9998; Edit Asset</button>' +
              '<button type="button" class="btn btn-sm btn-danger" ' +
              'onclick="delete_asset(' + r.asset_id + ');">Delete</button>') +
        '</div>' +
        '<div class="iris-ca-dtabs">' +
        [['details', 'Details', null],
         ['iocs', 'IOCs', iocs.length],
         ['timeline', 'Timeline', tlRows.length],
         ['history', 'History', null],
         ['comments', 'Comments',
          Array.isArray(comments) ? comments.length : null],
         ['evidence', 'Evidence', evLinks.length]]
            .map(function (t) {
                return '<button type="button" class="iris-ca-dtab' +
                    (IRIS_CA.tab === t[0] ? ' active' : '') +
                    '" data-tab="' + t[0] + '">' + t[1] +
                    (t[2] === null ? ''
                        : ' <span class="text-muted">' + t[2] + '</span>') +
                    '</button>';
            }).join('') +
        '</div>';
    /* Header + tab bar stay put; only the tab body scrolls, so switching
       tabs and reading a long history never loses the asset's identity. */
    var body = '';
    if (IRIS_CA.tab === 'iocs') {
        iris_ca_fetch_ioc_catalogs();
        body += iris_ca_ioc_tab_html(r);
    } else if (IRIS_CA.tab === 'evidence') {
        iris_ca_fetch_evidence_catalog();
        body += iris_ca_ev_tab_html(r);
    } else if (IRIS_CA.tab === 'timeline') {
        body += iris_ca_tl_tab_html(tlRows);
    } else if (IRIS_CA.tab === 'history') {
        var mh = r.modification_history || {};
        var entries = Object.keys(mh).map(function (k) {
            return {ts: parseFloat(k), e: mh[k]};
        }).sort(function (a, b) { return b.ts - a.ts; });
        body += entries.length
            ? entries.map(function (it) {
                var when = isNaN(it.ts) ? ''
                    : new Date(it.ts * 1000).toLocaleString();
                return '<div style="padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.05); font-size:0.78rem;">' +
                    '<span style="color:#9a9aa5;">' + iris_ca_esc(when) +
                    '</span> &middot; <span style="color:#c8c8d0;">' +
                    iris_ca_esc((it.e && it.e.action) || '') +
                    '</span> <span style="color:#7a7a85;">by ' +
                    iris_ca_esc((it.e && it.e.user) || '?') + '</span></div>';
            }).join('')
            : '<div class="text-muted" style="font-size:0.8rem;">No history recorded for this asset.</div>';
    } else if (IRIS_CA.tab === 'comments') {
        if (!Array.isArray(comments)) {
            body += '<div class="text-muted" style="font-size:0.8rem;">Loading comments&hellip;</div>';
        } else {
            /* The composer is pinned to the bottom of the card and only the
               list scrolls — otherwise it sits below every comment and the
               analyst has to scroll past the whole history to reach it. */
            body += '<div class="iris-ca-clist">';
            body += comments.length
                ? comments.map(function (cm) {
                    var who = (cm.user && (cm.user.user_name ||
                        cm.user.user_login)) || '?';
                    var when = String(cm.comment_date || '')
                        .replace('T', ' ').slice(0, 16);
                    return '<div style="padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.05);">' +
                        '<div style="font-size:0.7rem; color:#9a9aa5;"><b style="color:#c8c8d0;">' +
                        iris_ca_esc(who) + '</b> &middot; ' +
                        iris_ca_esc(when) + '</div>' +
                        '<div style="font-size:0.8rem; color:#e8e8ee; white-space:pre-wrap;">' +
                        iris_ca_esc(cm.comment_text) + '</div></div>';
                }).join('')
                : '<div class="text-muted" style="font-size:0.8rem;">No comments yet.</div>';
            body += '</div>';
            body +=
                '<div class="iris-ca-cfoot">' +
                '<input type="text" class="form-control form-control-sm" ' +
                'id="iris-ca-comment-input" placeholder="Add a comment..." ' +
                'autocomplete="off">' +
                '<button type="button" class="btn btn-sm btn-primary" ' +
                'onclick="iris_ca_post_comment(' + r.asset_id +
                ');">Comment</button></div>';
        }
    } else if (IRIS_CA.editing) {
        body += iris_ca_edit_form_html(r);
    } else {
        body +=
            '<div>' +
            '<span class="iris-ca-field"><span class="lbl">Type</span>' +
            iris_ca_esc(iris_ca_type_name(r)) + '</span>' +
            '<span class="iris-ca-field"><span class="lbl">Analysis</span>' +
            iris_ca_esc(analysis) + '</span>' +
            (r.asset_ip
                ? '<span class="iris-ca-field"><span class="lbl">IP</span><code>' +
                  iris_ca_esc(r.asset_ip) + '</code></span>' : '') +
            '</div>' +
            (r.asset_domain
                ? '<div style="margin-top:6px;"><span class="iris-ca-field"><span class="lbl">Domain</span><code>' +
                  iris_ca_esc(r.asset_domain) + '</code></span></div>' : '') +
            (iris_ca_tags(r).length
                ? '<div style="margin-top:6px;"><span class="lbl" style="color:#7a7a85; font-size:0.62rem; letter-spacing:0.08em; text-transform:uppercase; margin-right:5px;">Tags</span>' +
                  iris_ca_tags(r).map(function (t) {
                      return '<span class="iris-ca-tag">' + iris_ca_esc(t) +
                          '</span>';
                  }).join('') + '</div>' : '') +
            (r.asset_description
                ? '<div class="iris-ca-desc">' +
                  iris_ca_esc(r.asset_description) + '</div>'
                : '<div class="iris-ca-desc text-muted">(no description)</div>') +
            '<div class="iris-ca-foot">' +
            (r.date_added ? '<span>Added ' +
                new Date(r.date_added).toLocaleString() + '</span>' : '') +
            (r.date_update ? '<span>Updated ' +
                new Date(r.date_update).toLocaleString() + '</span>' : '') +
            '<span>ID #' + r.asset_id + '</span></div>';
        /* cached read only — opening an asset never spends a model call */
        iris_ca_profile_fetch(r);
        body += iris_ca_profile_html(r);
    }
    /* Comments splits the body: scrolling list + pinned composer, so the
       wrapper must not be the scroller itself. */
    var bodyCls = 'iris-ca-dbody' +
        (IRIS_CA.tab === 'comments' ? ' iris-ca-dbody-split' : '');
    box.innerHTML = html + '<div class="' + bodyCls + '">' + body + '</div>';
    iris_ca_fit_soon();
    if (IRIS_CA.tab === 'comments') {
        /* newest comment sits next to the composer, chat-style */
        var clist = box.querySelector('.iris-ca-clist');
        if (clist) clist.scrollTop = clist.scrollHeight;
    }
    /* innerHTML replaced the node, so the widget must be re-attached on
       every render that shows the edit form (the guard attribute lives on
       the element itself, so this cannot double-wrap). */
    if (IRIS_CA.editing) iris_ca_init_tag_widget();
}

document.addEventListener('DOMContentLoaded', function () {
    if (!document.getElementById('iris-ca-list')) return;
    /* an event saved from the in-place add-event modal lands on the
       timeline this tab renders — refetch it */
    window.iris_event_saved = function () { iris_ca_load_timeline(); };
    /* The card is sticky, so its top edge moves until it pins — refit on
       scroll and resize, not just once. */
    iris_ca_fit_card();
    window.addEventListener('scroll', iris_ca_fit_soon, {passive: true});
    window.addEventListener('resize', iris_ca_fit_soon);
    /* Modal saves call reload_assets() -> get_case_assets(); wrap it so
       the v3 panes refresh too (established monkey-patch idiom). The
       legacy $(document).ready fires get_case_assets() right after this
       handler, so with the wrapper installed a direct iris_ca_load() here
       would fetch the same payload a second time — load directly ONLY
       when the legacy module is absent. */
    if (typeof window.get_case_assets === 'function') {
        var orig = window.get_case_assets;
        window.get_case_assets = function () {
            orig();
            iris_ca_load();
        };
    } else {
        iris_ca_load();
    }
    document.getElementById('iris-ca-refresh')
        .addEventListener('click', iris_ca_load);
    document.getElementById('iris-ca-search')
        .addEventListener('input', function () {
            IRIS_CA.q = this.value.trim().toLowerCase();
            iris_ca_render_list();
        });
    document.getElementById('iris-ca-list')
        .addEventListener('click', function (e) {
            var row = e.target.closest('.iris-ca-row');
            if (!row) return;
            IRIS_CA.sel = parseInt(row.getAttribute('data-asset-id'), 10);
            IRIS_CA.tab = 'details';
            IRIS_CA.iocMenu = false;
            IRIS_CA.iocq = ''; IRIS_CA.iocMenuQ = '';
            IRIS_CA.evMenu = false;
            IRIS_CA.evq = ''; IRIS_CA.evMenuQ = '';
            IRIS_CA.editing = false;
            iris_ca_render_list();
            iris_ca_render_detail();
        });
    document.getElementById('iris-ca-detail')
        .addEventListener('click', function (e) {
            var sel = IRIS_CA.rows.find(function (x) {
                return x.asset_id === IRIS_CA.sel; });
            var linkbtn = e.target.closest('#iris-ca-ioc-linkbtn');
            if (linkbtn) {
                e.stopPropagation();
                IRIS_CA.iocMenu = !IRIS_CA.iocMenu;
                IRIS_CA.iocMenuQ = '';
                iris_ca_render_detail();
                return;
            }
            var item = e.target.closest('.iris-ca-ioc-linkitem');
            if (item && sel) {
                e.preventDefault();
                IRIS_CA.iocMenu = false;
                iris_ca_save_ioc_links(sel, iris_ca_linked_ids(sel)
                    .concat([parseInt(item.getAttribute('data-ioc-id'), 10)]));
                return;
            }
            var unlink = e.target.closest('.iris-ca-ioc-unlink');
            if (unlink && sel) {
                var rid = parseInt(unlink.getAttribute('data-ioc-id'), 10);
                iris_ca_save_ioc_links(sel, iris_ca_linked_ids(sel)
                    .filter(function (id) { return id !== rid; }));
                return;
            }
            if (e.target.closest('#iris-ca-ioc-newbtn') && sel) {
                iris_ca_new_ioc_and_link(sel);
                return;
            }
            if (sel && (e.target.closest('.iris-ca-prof-btn')
                    || e.target.closest('.iris-ca-prof-gen'))) {
                e.preventDefault();
                IRIS_CA.tab = 'details';
                IRIS_CA.editing = false;
                iris_ca_profile_gen(sel, false);
                return;
            }
            if (sel && e.target.closest('.iris-ca-prof-rerun')) {
                e.preventDefault();
                iris_ca_profile_gen(sel, true);
                return;
            }
            if (e.target.closest('#iris-ca-tagsugg-pill') && sel) {
                iris_ca_tagsugg_run(sel);
                return;
            }
            var sugg = e.target.closest('.iris-ca-tagsugg-chip');
            if (sugg) {
                var stag = sugg.getAttribute('data-tag');
                if (stag && iris_ca_tagsugg_add(stag) && IRIS_CA.tagSugg) {
                    IRIS_CA.tagSugg.accepted[stag] = true;
                    iris_ca_render_detail();
                }
                return;
            }
            if (e.target.closest('#iris-ca-tagsugg-all') && IRIS_CA.tagSugg
                    && IRIS_CA.tagSugg.items) {
                IRIS_CA.tagSugg.items.forEach(function (s) {
                    if (!IRIS_CA.tagSugg.accepted[s.tag]
                            && iris_ca_tagsugg_add(s.tag)) {
                        IRIS_CA.tagSugg.accepted[s.tag] = true;
                    }
                });
                iris_ca_render_detail();
                return;
            }
            if (e.target.closest('.iris-ca-edit-btn') && sel) {
                IRIS_CA.editing = true;
                IRIS_CA.tab = 'details';
                iris_ca_fetch_edit_catalogs();
                iris_ca_render_detail();
                return;
            }
            if (e.target.closest('.iris-ca-edit-cancel')) {
                IRIS_CA.editing = false;
                iris_ca_render_detail();
                return;
            }
            if (e.target.closest('.iris-ca-edit-save') && sel) {
                iris_ca_save_edit(sel);
                return;
            }
            var tlflag = e.target.closest('.iris-ca-tl-flag');
            if (tlflag) {
                /* legacy GET toggle — non-POST verbs are CSRF-exempt */
                fetch('/case/timeline/events/flag/' +
                      tlflag.getAttribute('data-event-id') + '?cid=' +
                      iris_ca_cid(),
                      {headers: {'Accept': 'application/json'}})
                    .then(function (r2) { return r2.json(); })
                    .then(function (resp) {
                        if (resp && resp.status === 'success') {
                            iris_ca_load_timeline();
                        } else {
                            window.alert((resp && resp.message)
                                || 'Flag toggle failed');
                        }
                    })
                    .catch(function () {
                        window.alert('Flag toggle failed'); });
                return;
            }
            var evbtn = e.target.closest('#iris-ca-ev-linkbtn');
            if (evbtn) {
                e.stopPropagation();
                IRIS_CA.evMenu = !IRIS_CA.evMenu;
                IRIS_CA.evMenuQ = '';
                iris_ca_render_detail();
                return;
            }
            var evitem = e.target.closest('.iris-ca-ev-linkitem');
            if (evitem && sel) {
                e.preventDefault();
                IRIS_CA.evMenu = false;
                iris_ca_save_evidence_links(sel, iris_ca_linked_ev_ids(sel)
                    .concat([parseInt(
                        evitem.getAttribute('data-evidence-id'), 10)]));
                return;
            }
            var evunlink = e.target.closest('.iris-ca-ev-unlink');
            if (evunlink && sel) {
                var evid = parseInt(
                    evunlink.getAttribute('data-evidence-id'), 10);
                iris_ca_save_evidence_links(sel, iris_ca_linked_ev_ids(sel)
                    .filter(function (id) { return id !== evid; }));
                return;
            }
            /* keep a link menu open while interacting inside it */
            if (e.target.closest('#iris-ca-iocmenu')
                    || e.target.closest('#iris-ca-evmenu')) {
                e.stopPropagation();
                return;
            }
            var tab = e.target.closest('.iris-ca-dtab[data-tab]');
            if (!tab) return;
            IRIS_CA.tab = tab.getAttribute('data-tab');
            IRIS_CA.iocMenu = false;
            IRIS_CA.evMenu = false;
            IRIS_CA.editing = false;   /* leaving Details discards the form */
            iris_ca_render_detail();
        });
    /* live filters — re-render only the affected fragment so the input
       keeps focus */
    document.getElementById('iris-ca-detail')
        .addEventListener('input', function (e) {
            var sel = IRIS_CA.rows.find(function (x) {
                return x.asset_id === IRIS_CA.sel; });
            if (!sel) return;
            if (e.target.id === 'iris-ca-ioc-search') {
                IRIS_CA.iocq = e.target.value.trim().toLowerCase();
                var wrap = document.getElementById('iris-ca-ioc-rows');
                if (wrap) wrap.innerHTML = iris_ca_ioc_rows_html(sel);
            } else if (e.target.id === 'iris-ca-ioc-menuq') {
                IRIS_CA.iocMenuQ = e.target.value.trim().toLowerCase();
                var items = document.getElementById('iris-ca-ioc-menuitems');
                if (items) items.innerHTML = iris_ca_ioc_menuitems_html(sel);
            } else if (e.target.id === 'iris-ca-ev-search') {
                IRIS_CA.evq = e.target.value.trim().toLowerCase();
                var evwrap = document.getElementById('iris-ca-ev-rows');
                if (evwrap) evwrap.innerHTML = iris_ca_ev_rows_html(sel);
            } else if (e.target.id === 'iris-ca-ev-menuq') {
                IRIS_CA.evMenuQ = e.target.value.trim().toLowerCase();
                var evitems =
                    document.getElementById('iris-ca-ev-menuitems');
                if (evitems) {
                    evitems.innerHTML = iris_ca_ev_menuitems_html(sel);
                }
            }
        });
    document.addEventListener('click', function (e) {
        if (IRIS_CA.iocMenu && !e.target.closest('#iris-ca-iocmenu')
                && !e.target.closest('#iris-ca-ioc-linkbtn')) {
            IRIS_CA.iocMenu = false;
            iris_ca_render_detail();
        }
        if (IRIS_CA.evMenu && !e.target.closest('#iris-ca-evmenu')
                && !e.target.closest('#iris-ca-ev-linkbtn')) {
            IRIS_CA.evMenu = false;
            iris_ca_render_detail();
        }
    });
    /* The section ⋮ (#iris-ca-more / #iris-ca-moremenu) moved into the shell
       header menu, which owns its own open/close. Its toggle wiring is gone
       rather than guarded: it addressed elements that no longer exist, and it
       was UNGUARDED — more.addEventListener on a null would have thrown here
       and silently killed every binding below it. */
    var exp = document.getElementById('iris-ca-export');
    if (exp) {
        exp.addEventListener('click', function (e) {
            e.preventDefault();
            iris_ca_export_csv();
        });
    }

    var legacyToggle = document.getElementById('iris-ca-legacy-toggle');
    if (legacyToggle) {
        legacyToggle.addEventListener('click', function (e) {
            e.preventDefault();
            var legacy = document.getElementById('iris-cassets-legacy');
            if (!legacy) return;
            var showing = legacy.style.display !== 'none';
            legacy.style.display = showing ? 'none' : '';
            this.textContent = showing
                ? 'Show legacy table' : 'Hide legacy table';
        });
    }
});

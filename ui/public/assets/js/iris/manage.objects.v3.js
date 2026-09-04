/* iris-ng: v3-parity Case Objects view (two-pane master/detail + tab bar).
 *
 * Overlay, not rebuild: renders from the SAME six list endpoints the legacy
 * DataTables call, and every action drives the EXISTING functions in
 * manage.objects.js (add_X / X_detail / delete_X). The legacy refresh_X_table
 * functions are wrapped so a save in the shared modal refreshes this view too
 * (the established monkey-patch idiom). Loaded AFTER manage.objects.js.
 *
 * Absent-data discipline: per-type rows start as null = "have not looked";
 * a fetch failure is recorded separately — an empty list is only claimed
 * after a successful fetch returned zero rows.
 */

var IRIS_CO = {
    type: 'asset',
    rows: {},        // type -> array (looked) | null/undefined (not looked)
    fetching: {},    // type -> bool, separate flag: [] is truthy-trap bait
    failed: {},      // type -> error string
    selected: {},    // type -> selected id
    search: ''
};

var IRIS_CO_TYPES = {
    asset: {
        label: 'Asset types', singular: 'asset type',
        url: '/manage/asset-type/list',
        id: 'asset_id', name: 'asset_name', desc: 'asset_description',
        add: 'add_asset_type', edit: 'assettype_detail', del: 'delete_asset_type',
        fields: function (r) {
            return [
                ['ID', '#' + r.asset_id], ['Name', r.asset_name],
                ['Description', r.asset_description],
                ['Icon (clean)', r.asset_icon_not_compromised, 'icon:' + (r.asset_icon_not_compromised_path || '')],
                ['Icon (compromised)', r.asset_icon_compromised, 'icon:' + (r.asset_icon_compromised_path || '')]
            ];
        }
    },
    ioc: {
        label: 'IOC types', singular: 'IOC type',
        url: '/manage/ioc-types/list',
        id: 'type_id', name: 'type_name', desc: 'type_description',
        add: 'add_ioc_type', edit: 'ioc_type_detail', del: 'delete_ioc_type',
        searchExtra: ['type_taxonomy'],
        fields: function (r) {
            return [
                ['ID', '#' + r.type_id], ['Name', r.type_name],
                ['Description', r.type_description],
                ['MISP taxonomy', r.type_taxonomy],
                ['Validation regex', r.type_validation_regex, 'code'],
                ['Validation hint', r.type_validation_expect]
            ];
        }
    },
    classification: {
        label: 'Case classifications', singular: 'classification',
        url: '/manage/case-classifications/list',
        id: 'id', name: 'name', desc: 'description',
        add: 'add_classification', edit: 'classification_detail', del: 'delete_case_classification',
        searchExtra: ['name_expanded'],
        fields: function (r) {
            return [
                ['ID', '#' + r.id], ['Name', r.name],
                ['Expanded name', r.name_expanded],
                ['Description', r.description],
                ['Created', r.creation_date]
            ];
        }
    },
    state: {
        label: 'Case states', singular: 'case state',
        url: '/manage/case-states/list',
        id: 'state_id', name: 'state_name', desc: 'state_description',
        add: 'add_state', edit: 'state_detail', del: 'delete_case_state',
        // Protected states are product machinery (Open, Closed...) — the
        // server refuses their deletion; do not offer the button.
        canDelete: function (r) { return !r.protected; },
        fields: function (r) {
            return [
                ['ID', '#' + r.state_id], ['Name', r.state_name],
                ['Description', r.state_description],
                ['Protected', r.protected
                    ? 'Yes — product state, cannot be deleted' : 'No']
            ];
        }
    },
    evidence: {
        label: 'Evidence types', singular: 'evidence type',
        url: '/manage/evidence-types/list',
        id: 'id', name: 'name', desc: 'description',
        add: 'add_evidence_type', edit: 'evidence_detail', del: 'delete_evidence_type',
        fields: function (r) {
            return [
                ['ID', '#' + r.id], ['Name', r.name],
                ['Description', r.description],
                ['Created', r.creation_date]
            ];
        }
    },
    sector: {
        label: 'Sectors', singular: 'sector',
        url: '/manage/sectors/list',
        id: 'id', name: 'name', desc: 'tag',
        add: 'add_sector', edit: 'sector_detail', del: 'delete_sector',
        searchExtra: ['slug'],
        fields: function (r) {
            return [
                ['ID', '#' + r.id], ['Name', r.name],
                ['Slug (stable key)', r.slug, 'code'],
                ['Machine tag', r.tag, 'code'],
                ['Enabled', r.enabled
                    ? 'Yes — offered in the sector pickers'
                    : 'No — hidden from pickers, still recognized in metrics']
            ];
        }
    }
};

function iris_co_esc(s) {
    return $('<div>').text(s === null || s === undefined ? '' : String(s)).html();
}

function iris_co_fetch(type, force) {
    if (IRIS_CO.fetching[type]) { return; }
    if (!force && Array.isArray(IRIS_CO.rows[type])) { iris_co_render(); return; }
    IRIS_CO.fetching[type] = true;
    delete IRIS_CO.failed[type];
    iris_co_render();
    get_request_api(IRIS_CO_TYPES[type].url)
    .done(function (data) {
        IRIS_CO.rows[type] = (data && data.data) ? data.data : [];
    })
    .fail(function (xhr) {
        IRIS_CO.failed[type] = 'HTTP ' + (xhr && xhr.status ? xhr.status : '?');
    })
    .always(function () {
        IRIS_CO.fetching[type] = false;
        iris_co_render();
    });
}

function iris_co_filtered(type) {
    var cfg = IRIS_CO_TYPES[type];
    var rows = IRIS_CO.rows[type] || [];
    var q = (IRIS_CO.search || '').toLowerCase();
    if (!q) { return rows; }
    return rows.filter(function (r) {
        var hay = [r[cfg.name], r[cfg.desc]].concat(
            (cfg.searchExtra || []).map(function (k) { return r[k]; }));
        return hay.some(function (v) {
            return v !== null && v !== undefined
                && String(v).toLowerCase().indexOf(q) !== -1;
        });
    });
}

function iris_co_render() {
    var type = IRIS_CO.type;
    var cfg = IRIS_CO_TYPES[type];

    $('.iris-co-tab').removeClass('active');
    $('.iris-co-tab[data-type="' + type + '"]').addClass('active');
    $('#iris-co-list-title').text(cfg.label);
    $('#iris-co-add').text('+ Add ' + cfg.singular);

    var $rows = $('#iris-co-rows');
    if (IRIS_CO.failed[type]) {
        $('#iris-co-count').text('');
        $rows.html('<div class="iris-co-empty">Could not load ' + iris_co_esc(cfg.label)
            + ' (' + iris_co_esc(IRIS_CO.failed[type]) + '). Refresh to retry.</div>');
        return;
    }
    if (!Array.isArray(IRIS_CO.rows[type])) {
        $('#iris-co-count').text('');
        $rows.html('<div class="iris-co-empty">Loading…</div>');
        return;
    }

    var all = IRIS_CO.rows[type];
    var shown = iris_co_filtered(type);
    $('#iris-co-count').text(shown.length + ' / ' + all.length);

    if (!all.length) {
        $rows.html('<div class="iris-co-empty">No ' + iris_co_esc(cfg.label.toLowerCase())
            + ' defined yet.</div>');
        iris_co_render_detail(null);
        return;
    }
    if (!shown.length) {
        $rows.html('<div class="iris-co-empty">No match for the current search.</div>');
        return;
    }

    var sel = IRIS_CO.selected[type];
    var html = shown.map(function (r) {
        var rid = r[cfg.id];
        return '<div class="iris-co-row' + (String(rid) === String(sel) ? ' selected' : '')
            + '" data-id="' + iris_co_esc(rid) + '">'
            + '<div class="iris-co-row-main">'
            + '<div class="iris-co-row-name">' + iris_co_esc(r[cfg.name]) + '</div>'
            + '<div class="iris-co-row-desc">' + iris_co_esc(r[cfg.desc]) + '</div>'
            + '</div><span class="iris-co-row-id">#' + iris_co_esc(rid) + '</span></div>';
    }).join('');
    $rows.html(html);

    var selRow = null;
    if (sel !== undefined) {
        selRow = all.find(function (r) { return String(r[cfg.id]) === String(sel); }) || null;
    }
    iris_co_render_detail(selRow);
}

function iris_co_render_detail(row) {
    var cfg = IRIS_CO_TYPES[IRIS_CO.type];
    var $d = $('#iris-co-detail');
    if (!row) {
        $d.html('<div class="iris-co-empty">Select an entry to see its details.</div>');
        return;
    }
    var rid = row[cfg.id];
    var canDelete = cfg.canDelete ? cfg.canDelete(row) : true;
    var html = '<div class="iris-co-d-head">'
        + '<span class="iris-co-d-eyebrow">Details</span>'
        + '<span class="iris-co-d-name">' + iris_co_esc(row[cfg.name]) + '</span>'
        + '<span class="iris-co-d-actions">'
        + '<button type="button" class="btn btn-sm btn-dark" id="iris-co-edit">Edit</button>'
        + (canDelete
            ? '<button type="button" class="btn btn-sm btn-outline-danger" id="iris-co-del">Delete</button>'
            : '')
        + '</span></div><div class="iris-co-fields">';
    cfg.fields(row).forEach(function (f) {
        var label = f[0], value = f[1], mode = f[2] || '';
        var rendered;
        if (value === null || value === undefined || value === '') {
            rendered = '<span class="text-muted">—</span>';
        } else if (mode === 'code') {
            rendered = '<code>' + iris_co_esc(value) + '</code>';
        } else if (mode.indexOf('icon:') === 0) {
            var path = mode.slice(5);
            // Icon paths come from the server catalog; render the image only
            // for a same-origin absolute path, else fall back to the name.
            rendered = (path && path.indexOf('/') === 0 && path.indexOf('//') !== 0)
                ? '<img src="' + iris_co_esc(path) + '" alt="">' + iris_co_esc(value)
                : iris_co_esc(value);
        } else {
            rendered = iris_co_esc(value);
        }
        html += '<div><div class="iris-co-f-label">' + iris_co_esc(label)
            + '</div><div class="iris-co-f-value">' + rendered + '</div></div>';
    });
    html += '</div>';
    $d.html(html);

    $('#iris-co-edit').on('click', function () { window[cfg.edit](rid); });
    $('#iris-co-del').on('click', function () { window[cfg.del](rid); });
}

function iris_co_set_tab(type) {
    if (!IRIS_CO_TYPES[type]) { type = 'asset'; }
    IRIS_CO.type = type;
    IRIS_CO.search = '';
    $('#iris-co-search').val('');
    try { localStorage.setItem('irisCaseObjectsTab', type); } catch (e) { /* private mode */ }
    iris_co_fetch(type, false);
}

$(function () {
    // A modal save calls the legacy refresh_X_table(); wrap each so this view
    // re-fetches too — one writer, two presentations.
    var refreshers = {
        asset: 'refresh_asset_table', ioc: 'refresh_ioc_table',
        classification: 'refresh_classification_table', state: 'refresh_state_table',
        evidence: 'refresh_evidence_table', sector: 'refresh_sector_table'
    };
    Object.keys(refreshers).forEach(function (type) {
        var fname = refreshers[type];
        var orig = window[fname];
        if (typeof orig !== 'function') { return; }
        window[fname] = function () {
            var out = orig.apply(this, arguments);
            iris_co_fetch(type, true);
            return out;
        };
    });

    $('#iris-co-tabs').on('click', '.iris-co-tab', function () {
        iris_co_set_tab($(this).data('type'));
    });
    $('#iris-co-rows').on('click', '.iris-co-row', function () {
        IRIS_CO.selected[IRIS_CO.type] = $(this).attr('data-id');
        iris_co_render();
    });
    $('#iris-co-search').on('input', function () {
        IRIS_CO.search = $(this).val();
        iris_co_render();
    });
    $('#iris-co-refresh').on('click', function () {
        iris_co_fetch(IRIS_CO.type, true);
    });
    $('#iris-co-add').on('click', function () {
        window[IRIS_CO_TYPES[IRIS_CO.type].add]();
    });

    var saved = null;
    try { saved = localStorage.getItem('irisCaseObjectsTab'); } catch (e) { /* private mode */ }
    iris_co_set_tab(saved || 'asset');
});

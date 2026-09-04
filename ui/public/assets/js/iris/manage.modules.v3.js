/* iris-ng: v3-parity Modules view (modules panel + registered-hooks panel).
 *
 * Overlay, not rebuild: renders from the SAME /manage/modules/list and
 * /manage/modules/hooks/list endpoints the legacy DataTables call; the
 * per-row actions drive the EXISTING functions in manage.modules.js
 * (module_detail / enable_module / disable_module / remove_module), and the
 * legacy refresh_modules / refresh_modules_hooks are wrapped so any save in
 * the module modal refreshes this view too. Loaded AFTER manage.modules.js.
 *
 * Absent-data discipline: rows start null ("have not looked"), a failed
 * fetch is recorded separately, and "none" is only claimed after a
 * successful empty fetch.
 */

var IRIS_MOD = {
    mods: null, modsFetching: false, modsFailed: null,
    hooks: null, hooksFetching: false, hooksFailed: null,
    hookSearch: ''
};

function iris_mod_esc(s) {
    return $('<div>').text(s === null || s === undefined ? '' : String(s)).html();
}

/* date_added is the STORED ISO string (naive UTC with microseconds) — label
 * a trimmed form of it, never re-zone through new Date(). */
function iris_mod_date(v) {
    var s = String(v || '');
    return s.replace('T', ' ').slice(0, 16);
}

function iris_mod_status(row) {
    if (!row.configured) {
        return '<span class="iris-mod-badge misconfigured" title="Missing mandatory configuration — open the module to complete it">Misconfigured</span>';
    }
    if (row.is_active) {
        return '<span class="iris-mod-badge active">Active</span>';
    }
    return '<span class="iris-mod-badge inactive">Inactive</span>';
}

function iris_mod_fetch(force) {
    if (!IRIS_MOD.modsFetching && (force || !Array.isArray(IRIS_MOD.mods))) {
        IRIS_MOD.modsFetching = true;
        IRIS_MOD.modsFailed = null;
        iris_mod_render();
        get_request_api('/manage/modules/list')
        .done(function (data) { IRIS_MOD.mods = (data && data.data) ? data.data : []; })
        .fail(function (xhr) { IRIS_MOD.modsFailed = 'HTTP ' + (xhr && xhr.status ? xhr.status : '?'); })
        .always(function () { IRIS_MOD.modsFetching = false; iris_mod_render(); });
    }
    if (!IRIS_MOD.hooksFetching && (force || !Array.isArray(IRIS_MOD.hooks))) {
        IRIS_MOD.hooksFetching = true;
        IRIS_MOD.hooksFailed = null;
        iris_hook_render();
        get_request_api('/manage/modules/hooks/list')
        .done(function (data) { IRIS_MOD.hooks = (data && data.data) ? data.data : []; })
        .fail(function (xhr) { IRIS_MOD.hooksFailed = 'HTTP ' + (xhr && xhr.status ? xhr.status : '?'); })
        .always(function () { IRIS_MOD.hooksFetching = false; iris_hook_render(); });
    }
}

function iris_mod_render() {
    var $l = $('#iris-mod-list');
    if (IRIS_MOD.modsFailed) {
        $('#iris-mod-count').text('');
        $l.html('<div class="iris-co-empty">Could not load modules ('
            + iris_mod_esc(IRIS_MOD.modsFailed) + '). Refresh to retry.</div>');
        return;
    }
    if (!Array.isArray(IRIS_MOD.mods)) {
        $('#iris-mod-count').text('');
        $l.html('<div class="iris-co-empty">Loading…</div>');
        return;
    }
    var mods = IRIS_MOD.mods;
    var active = mods.filter(function (m) { return m.is_active && m.configured; }).length;
    $('#iris-mod-count').text(active + ' / ' + mods.length + ' active');
    if (!mods.length) {
        $l.html('<div class="iris-co-empty">No modules installed.</div>');
        return;
    }
    var html = '<table class="iris-mod-table"><thead><tr>'
        + '<th>ID</th><th>Module</th><th>Pipeline</th><th>Version</th><th>Interface</th>'
        + '<th>Date added</th><th>Added by</th><th>Status</th><th></th></tr></thead><tbody>';
    mods.forEach(function (m) {
        html += '<tr>'
            + '<td class="iris-mod-id">' + iris_mod_esc(m.id) + '</td>'
            + '<td><span class="iris-mod-name" data-id="' + iris_mod_esc(m.id) + '">'
            + iris_mod_esc(m.module_human_name) + '</span></td>'
            + '<td>' + (m.has_pipeline ? 'Yes' : '<span class="text-muted">—</span>') + '</td>'
            + '<td>' + iris_mod_esc(m.module_version) + '</td>'
            + '<td>' + iris_mod_esc(m.interface_version) + '</td>'
            + '<td>' + iris_mod_esc(iris_mod_date(m.date_added)) + '</td>'
            + '<td>' + iris_mod_esc(m.name) + '</td>'
            + '<td>' + iris_mod_status(m) + '</td>'
            + '<td class="text-right"><span class="iris-mod-more" data-id="' + iris_mod_esc(m.id)
            + '" data-active="' + (m.is_active ? '1' : '0') + '">&#8943;</span></td>'
            + '</tr>';
    });
    html += '</tbody></table>';
    $l.html(html);
}

function iris_hook_filtered() {
    var rows = IRIS_MOD.hooks || [];
    var q = (IRIS_MOD.hookSearch || '').toLowerCase();
    if (!q) { return rows; }
    return rows.filter(function (h) {
        return [h.module_name, h.hook_name, h.hook_description].some(function (v) {
            return v !== null && v !== undefined
                && String(v).toLowerCase().indexOf(q) !== -1;
        });
    });
}

function iris_hook_render() {
    var $l = $('#iris-hook-list');
    if (IRIS_MOD.hooksFailed) {
        $('#iris-hook-count').text('');
        $l.html('<div class="iris-co-empty">Could not load hooks ('
            + iris_mod_esc(IRIS_MOD.hooksFailed) + '). Refresh to retry.</div>');
        return;
    }
    if (!Array.isArray(IRIS_MOD.hooks)) {
        $('#iris-hook-count').text('');
        $l.html('<div class="iris-co-empty">Loading…</div>');
        return;
    }
    var all = IRIS_MOD.hooks;
    var shown = iris_hook_filtered();
    $('#iris-hook-count').text(shown.length + ' / ' + all.length + ' bindings');
    if (!all.length) {
        $l.html('<div class="iris-co-empty">No hooks registered.</div>');
        return;
    }
    if (!shown.length) {
        $l.html('<div class="iris-co-empty">No match for the current search.</div>');
        return;
    }
    var html = '<table class="iris-mod-table"><thead><tr>'
        + '<th>ID</th><th>Registrant module</th><th>Hook</th><th>Description</th>'
        + '<th>Manual</th><th>Active</th></tr></thead><tbody>';
    shown.forEach(function (h) {
        html += '<tr>'
            + '<td class="iris-mod-id">' + iris_mod_esc(h.id) + '</td>'
            + '<td>' + iris_mod_esc(h.module_name) + '</td>'
            + '<td class="iris-mod-hookname">' + iris_mod_esc(h.hook_name) + '</td>'
            + '<td>' + iris_mod_esc(h.hook_description) + '</td>'
            + '<td>' + (h.is_manual_hook ? 'Yes' : 'No') + '</td>'
            + '<td>' + (h.is_active ? 'Yes' : 'No') + '</td>'
            + '</tr>';
    });
    html += '</tbody></table>';
    $l.html(html);
}

function iris_mod_close_menu() {
    $('.iris-mod-menu').remove();
}

$(function () {
    // Modal saves + enable/disable call the legacy refreshers; wrap both so
    // this view re-fetches too — one writer, two presentations.
    var origM = window.refresh_modules;
    if (typeof origM === 'function') {
        window.refresh_modules = function () {
            var out = origM.apply(this, arguments);
            iris_mod_fetch(true);
            return out;
        };
    }
    var origH = window.refresh_modules_hooks;
    if (typeof origH === 'function') {
        window.refresh_modules_hooks = function () {
            var out = origH.apply(this, arguments);
            iris_mod_fetch(true);
            return out;
        };
    }

    $('#iris-mod-list').on('click', '.iris-mod-name', function () {
        module_detail($(this).data('id'));
    });

    // Per-row ⋯ menu: open module / enable-or-disable / remove — every entry
    // drives an existing manage.modules.js function.
    $('#iris-mod-list').on('click', '.iris-mod-more', function (e) {
        e.stopPropagation();
        iris_mod_close_menu();
        var id = $(this).attr('data-id');
        var isActive = $(this).attr('data-active') === '1';
        var $m = $('<div class="iris-mod-menu">'
            + '<a href="#" data-act="open">Open module</a>'
            + (isActive
                ? '<a href="#" data-act="disable">Disable</a>'
                : '<a href="#" data-act="enable">Enable</a>')
            + '<a href="#" data-act="remove" class="danger">Remove…</a>'
            + '</div>');
        var off = $(this).offset();
        $m.css({ top: off.top + 22, left: Math.max(10, off.left - 140) });
        $('body').append($m);
        $m.on('click', 'a', function (ev) {
            ev.preventDefault();
            var act = $(this).attr('data-act');
            iris_mod_close_menu();
            if (act === 'open') { module_detail(id); }
            else if (act === 'enable') { enable_module(id); }
            else if (act === 'disable') { disable_module(id); }
            else if (act === 'remove') { remove_module(id); }
        });
    });
    $(document).on('click', iris_mod_close_menu);

    $('#iris-hook-search').on('input', function () {
        IRIS_MOD.hookSearch = $(this).val();
        iris_hook_render();
    });
    $('#iris-mod-refresh').on('click', function () { iris_mod_fetch(true); });

    iris_mod_fetch(false);
});

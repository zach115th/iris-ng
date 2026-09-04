/* iris-ng: v3-parity Report Templates view (template list + detail pane).
 *
 * Overlay, not rebuild: the list AND the detail pane render from the SAME
 * /manage/templates/list payload the legacy DataTable calls; + Add template
 * drives the EXISTING upload modal (add_report_template), Download the
 * existing /manage/templates/download/<id> route, Delete the existing
 * delete_report (swal dangerMode confirm). refresh_template_table is
 * wrapped so any legacy-path change refreshes this view too. Loaded AFTER
 * manage.templates.js.
 *
 * Report templates are immutable uploads — there is no edit surface, so the
 * detail pane is read-only metadata plus Download / Delete. In the legacy
 * table the name LINK deletes the template; here a row click only selects.
 */

var IRIS_RT = {
    rows: null, fetching: false, failed: null,
    selected: null, search: ''
};

function iris_rt_esc(s) {
    return $('<div>').text(s === null || s === undefined ? '' : String(s)).html();
}

/* date_created is the STORED value serialized by the server — label a
 * trimmed form of it, never re-zone through new Date(). */
function iris_rt_date(v) {
    return String(v || '').replace('T', ' ').slice(0, 16);
}

function iris_rt_fetch(force) {
    if (IRIS_RT.fetching) { return; }
    if (!force && Array.isArray(IRIS_RT.rows)) { return; }
    IRIS_RT.fetching = true;
    IRIS_RT.failed = null;
    iris_rt_render_rows();
    get_request_api('/manage/templates/list')
    .done(function (data) {
        IRIS_RT.rows = (data && data.data) ? data.data : [];
    })
    .fail(function (xhr) {
        IRIS_RT.failed = 'HTTP ' + (xhr && xhr.status ? xhr.status : '?');
    })
    .always(function () {
        IRIS_RT.fetching = false;
        // A refetch after a delete can drop the selected row — clear the
        // selection rather than keep showing a template that no longer exists.
        if (IRIS_RT.selected !== null && Array.isArray(IRIS_RT.rows)
                && !iris_rt_selected_row()) {
            IRIS_RT.selected = null;
        }
        iris_rt_render_rows();
        iris_rt_render_detail();
    });
}

function iris_rt_selected_row() {
    return (IRIS_RT.rows || []).find(function (r) {
        return String(r.id) === String(IRIS_RT.selected);
    }) || null;
}

function iris_rt_filtered() {
    var rows = IRIS_RT.rows || [];
    var q = (IRIS_RT.search || '').toLowerCase();
    if (!q) { return rows; }
    return rows.filter(function (r) {
        return [r.name, r.description].some(function (v) {
            return v !== null && v !== undefined
                && String(v).toLowerCase().indexOf(q) !== -1;
        });
    });
}

function iris_rt_render_rows() {
    var $l = $('#iris-rt-rows');
    if (IRIS_RT.failed) {
        $('#iris-rt-count').text('');
        $l.html('<div class="iris-co-empty">Could not load templates ('
            + iris_rt_esc(IRIS_RT.failed) + '). Refresh to retry.</div>');
        return;
    }
    if (!Array.isArray(IRIS_RT.rows)) {
        $('#iris-rt-count').text('');
        $l.html('<div class="iris-co-empty">Loading…</div>');
        return;
    }
    var all = IRIS_RT.rows;
    var shown = iris_rt_filtered();
    $('#iris-rt-count').text(shown.length + ' / ' + all.length);
    if (!all.length) {
        $l.html('<div class="iris-co-empty">No templates yet. Click + Add template to upload one.</div>');
        return;
    }
    if (!shown.length) {
        $l.html('<div class="iris-co-empty">No match for the current search.</div>');
        return;
    }
    var html = '';
    shown.forEach(function (r) {
        html += '<div class="iris-rt-row'
            + (String(r.id) === String(IRIS_RT.selected) ? ' active' : '')
            + '" data-id="' + iris_rt_esc(r.id) + '">'
            + '<div><div class="iris-rt-row-name">' + iris_rt_esc(r.name) + '</div>'
            + '<div class="iris-rt-row-sub">' + iris_rt_esc(r.type_name)
            + (r.description ? ' · ' + iris_rt_esc(r.description) : '') + '</div></div>'
            + '<span class="iris-rt-row-id">#' + iris_rt_esc(r.id) + '</span>'
            + '</div>';
    });
    $l.html(html);
}

function iris_rt_render_detail() {
    var $d = $('#iris-rt-detail');
    if (!Array.isArray(IRIS_RT.rows)) {
        $d.html('<div class="iris-co-empty">Loading…</div>');
        return;
    }
    var row = iris_rt_selected_row();
    if (!row) {
        $d.html('<div class="iris-co-empty">Select a template on the left, or click + Add template to upload one.</div>');
        return;
    }
    var $wrap = $('<div>');
    var $head = $('<div class="iris-rt-d-head">');
    $head.append($('<span class="iris-rt-d-title">').text(row.name));
    $head.append($('<span class="iris-rt-d-id">').text('#' + row.id));
    $head.append($('<span class="iris-rt-chip">').text(row.type_name || '?'));
    var $actions = $('<div class="iris-rt-d-actions">');
    $actions.append($('<button type="button" class="btn btn-sm btn-dark" id="iris-rt-download">').text('Download'));
    $actions.append($('<button type="button" class="btn btn-sm btn-outline-danger" id="iris-rt-delete">').text('Delete'));
    $head.append($actions);
    $wrap.append($head);
    if (row.description) {
        $wrap.append($('<div class="iris-rt-desc">').text(row.description));
    }
    var $meta = $('<dl class="iris-rt-meta">');
    [['Report type', row.type_name],
     ['Language', row.code],
     ['Naming format', row.naming_format],
     ['Created by', row.created_by],
     ['Date created', iris_rt_date(row.date_created) + (row.date_created ? ' UTC' : '')]
    ].forEach(function (kv) {
        $meta.append($('<dt>').text(kv[0]));
        $meta.append($('<dd>').text(kv[1] || '—'));
    });
    $wrap.append($meta);
    $d.empty().append($wrap);
}

$(function () {
    // Upload success and the legacy Refresh/Delete call the legacy
    // refresher; wrap it so the v3 view re-fetches too.
    var origR = window.refresh_template_table;
    if (typeof origR === 'function') {
        window.refresh_template_table = function () {
            var out = origR.apply(this, arguments);
            iris_rt_fetch(true);
            return out;
        };
    }

    $('#iris-rt-rows').on('click', '.iris-rt-row', function () {
        /* Template ids are digits only (server-assigned) — validate at the
           one read point; downstream the download URL and delete both
           interpolate this value, and their existing null guards handle a
           rejected read (broken markup selects nothing). */
        var id = $(this).attr('data-id') || '';
        IRIS_RT.selected = /^\d+$/.test(id) ? id : null;
        iris_rt_render_rows();
        iris_rt_render_detail();
    });
    $('#iris-rt-search').on('input', function () {
        IRIS_RT.search = $(this).val();
        iris_rt_render_rows();
    });
    $('#iris-rt-detail').on('click', '#iris-rt-download', function () {
        if (IRIS_RT.selected === null) { return; }
        window.location = '/manage/templates/download/' + IRIS_RT.selected + case_param();
    });
    $('#iris-rt-detail').on('click', '#iris-rt-delete', function () {
        if (IRIS_RT.selected === null) { return; }
        // Legacy delete: swal dangerMode confirm + POST + wrapped refresher.
        delete_report(IRIS_RT.selected);
    });
    $('#iris-rt-refresh').on('click', function () { iris_rt_fetch(true); });

    iris_rt_fetch(false);
});

/*
 * iris-next: per-case time-tracking widget (15-minute increments).
 *
 * Standalone static JS (served from /static/assets/js/iris/case.time.js via
 * Vite's publicDir copy). Loaded on every case page by footer_case.html.
 *
 * Talks to the v2 case-scoped endpoints:
 *   GET    /api/v2/cases/<cid>/time-entries
 *   POST   /api/v2/cases/<cid>/time-entries        {minutes, activity_date?, task_id?, note?}
 *   PUT    /api/v2/cases/<cid>/time-entries/<id>
 *   DELETE /api/v2/cases/<cid>/time-entries/<id>
 *
 * v2 endpoints return the payload DIRECTLY (no {status,data} wrapper) — read
 * the body as the data.
 */

var g_timelog_is_open = true;
var g_timelog_current_user_id = null;

function iris_fmt_minutes(mins) {
    mins = parseInt(mins, 10) || 0;
    var h = Math.floor(mins / 60);
    var m = mins % 60;
    return h + ':' + (m < 10 ? '0' + m : m);
}

/* v2 reads the body directly; tolerate a legacy {data:...} just in case. */
function iris_timelog_unwrap(resp) {
    if (resp && resp.entries !== undefined) return resp;
    if (resp && resp.data !== undefined) return resp.data;
    return resp || {};
}

function open_time_log_modal() {
    // Default the date input to today (local).
    var d = new Date();
    var iso = d.getFullYear() + '-' +
              ('0' + (d.getMonth() + 1)).slice(-2) + '-' +
              ('0' + d.getDate()).slice(-2);
    $('#iris-timelog-date').val(iso);
    $('#iris-timelog-minutes').val('30');
    $('#iris-timelog-custom-wrap').hide();
    $('#iris-timelog-custom').val('');
    $('#iris-timelog-note').val('');

    iris_timelog_load_tasks();
    iris_timelog_refresh();
    $('#iris-timelog-modal').modal('show');
}

/* Populate the optional task dropdown from the case's tasks. */
function iris_timelog_load_tasks() {
    get_request_api('/case/tasks/list')
    .done(function (data) {
        if (!data || data.status !== 'success') return;
        var $sel = $('#iris-timelog-task');
        $sel.find('option:not(:first)').remove();
        var tasks = (data.data && data.data.tasks) ? data.data.tasks : [];
        tasks.forEach(function (t) {
            $sel.append($('<option>').val(t.task_id).text('#' + t.task_id + ' ' + (t.task_title || '')));
        });
    });
}

function iris_timelog_refresh() {
    var cid = get_caseid();
    get_request_api('/api/v2/cases/' + cid + '/time-entries')
    .done(function (raw) {
        var data = iris_timelog_unwrap(raw);
        g_timelog_is_open = (data.is_open !== false);
        g_timelog_current_user_id = data.current_user_id;

        $('#iris-timelog-total').text('Total: ' + iris_fmt_minutes(data.total_minutes || 0));

        // Lock the form when the case is closed.
        $('#iris-timelog-closed-banner').toggle(!g_timelog_is_open);
        $('#iris-timelog-form input, #iris-timelog-form select, #iris-timelog-add')
            .prop('disabled', !g_timelog_is_open);

        var entries = data.entries || [];
        var $tb = $('#iris-timelog-tbody').empty();
        $('#iris-timelog-empty').toggle(entries.length === 0);

        entries.forEach(function (e) {
            var mine = (e.user_id != null && e.user_id === g_timelog_current_user_id);
            var $tr = $('<tr>').attr('data-entry_id', e.id);
            $tr.append($('<td>').text(e.activity_date || ''));
            $tr.append($('<td>').text(e.user_name || e.user_login || '—'));
            $tr.append($('<td>').text(e.task_id ? ('#' + e.task_id) : '—'));
            $tr.append($('<td>').text(iris_fmt_minutes(e.minutes)));
            $tr.append($('<td>').text(e.note || ''));

            var $actions = $('<td>').addClass('text-right');
            // Only show edit/delete for your own entries, and only while open.
            if (mine && g_timelog_is_open) {
                $('<a>').attr('href', '#').addClass('text-muted mr-2').attr('title', 'Edit')
                    .html('<i class="fa-solid fa-pen"></i>')
                    .on('click', function (ev) { ev.preventDefault(); iris_timelog_edit(e); })
                    .appendTo($actions);
                $('<a>').attr('href', '#').addClass('text-danger').attr('title', 'Delete')
                    .html('<i class="fa-solid fa-trash"></i>')
                    .on('click', function (ev) { ev.preventDefault(); iris_timelog_delete(e.id); })
                    .appendTo($actions);
            }
            $tr.append($actions);
            $tb.append($tr);
        });
    });
}

/* Resolve the chosen minutes (preset or custom). Returns null if invalid. */
function iris_timelog_chosen_minutes() {
    var v = $('#iris-timelog-minutes').val();
    var mins;
    if (v === 'custom') {
        mins = parseInt($('#iris-timelog-custom').val(), 10);
    } else {
        mins = parseInt(v, 10);
    }
    if (!mins || mins <= 0 || mins % 15 !== 0) {
        notify_error('Duration must be a positive multiple of 15 minutes.');
        return null;
    }
    return mins;
}

function iris_timelog_submit() {
    if (!g_timelog_is_open) { return; }
    var mins = iris_timelog_chosen_minutes();
    if (mins === null) { return; }

    var cid = get_caseid();
    var task_id = $('#iris-timelog-task').val();
    var body = {
        minutes: mins,
        activity_date: $('#iris-timelog-date').val() || null,
        task_id: task_id ? parseInt(task_id, 10) : null,
        note: $('#iris-timelog-note').val() || null,
        csrf_token: $('#csrf_token').val()
    };

    post_request_api('/api/v2/cases/' + cid + '/time-entries', JSON.stringify(body), true)
    .done(function () {
        $('#iris-timelog-note').val('');
        notify_success('Time logged');
        iris_timelog_refresh();
    });
}

/* Inline-edit: prefill the form from an entry, swap the Log button to Save. */
function iris_timelog_edit(entry) {
    var presets = ['15', '30', '45', '60', '90', '120', '240', '480'];
    if (presets.indexOf(String(entry.minutes)) !== -1) {
        $('#iris-timelog-minutes').val(String(entry.minutes));
        $('#iris-timelog-custom-wrap').hide();
    } else {
        $('#iris-timelog-minutes').val('custom');
        $('#iris-timelog-custom-wrap').show();
        $('#iris-timelog-custom').val(entry.minutes);
    }
    $('#iris-timelog-date').val(entry.activity_date || '');
    $('#iris-timelog-task').val(entry.task_id ? String(entry.task_id) : '');
    $('#iris-timelog-note').val(entry.note || '');

    var $btn = $('#iris-timelog-add');
    $btn.html('<i class="fa-solid fa-check mr-1"></i>Save')
        .off('click').on('click', function (e) {
            e.preventDefault();
            iris_timelog_save_edit(entry.id);
            return false;
        });
}

function iris_timelog_reset_add_button() {
    $('#iris-timelog-add').html('<i class="fa-solid fa-plus mr-1"></i>Log')
        .off('click').on('click', function (e) {
            e.preventDefault();
            iris_timelog_submit();
            return false;
        });
}

function iris_timelog_save_edit(entry_id) {
    var mins = iris_timelog_chosen_minutes();
    if (mins === null) { return; }
    var cid = get_caseid();
    var task_id = $('#iris-timelog-task').val();
    var body = {
        minutes: mins,
        activity_date: $('#iris-timelog-date').val() || null,
        task_id: task_id ? parseInt(task_id, 10) : null,
        note: $('#iris-timelog-note').val() || null,
        csrf_token: $('#csrf_token').val()
    };
    put_request_api('/api/v2/cases/' + cid + '/time-entries/' + entry_id, JSON.stringify(body))
    .done(function () {
        notify_success('Time entry updated');
        $('#iris-timelog-note').val('');
        iris_timelog_reset_add_button();
        iris_timelog_refresh();
    });
}

function iris_timelog_delete(entry_id) {
    var cid = get_caseid();
    var body = JSON.stringify({ csrf_token: $('#csrf_token').val() });
    delete_request_api('/api/v2/cases/' + cid + '/time-entries/' + entry_id, body)
    .done(function () {
        notify_success('Time entry deleted');
        iris_timelog_refresh();
    });
}

/* Opt-in nudge: "you logged 0 time on cases you touched". Off by default —
 * the endpoint returns enabled:false unless an admin turned it on. Shown once
 * per page load as a dismissible toast; suppressed for the rest of the browser
 * session after the analyst dismisses it. */
function iris_timelog_check_nudge() {
    if (sessionStorage.getItem('iris_timelog_nudge_dismissed') === '1') { return; }
    get_request_api('/api/v2/cases/time-nudge')
    .done(function (raw) {
        var data = (raw && raw.enabled !== undefined) ? raw : ((raw && raw.data) || {});
        if (!data.enabled || !data.cases || !data.cases.length) { return; }
        var n = data.cases.length;
        var msg = 'You have ' + n + ' case' + (n === 1 ? '' : 's') +
                  ' with no time logged. Use the clock icon in the case header to log time.';
        if (typeof notify_warning === 'function') {
            notify_warning(msg);
        } else if (typeof notify_success === 'function') {
            notify_success(msg);
        }
        sessionStorage.setItem('iris_timelog_nudge_dismissed', '1');
    });
}

/* Toggle the custom-minutes input and reset to add-mode on duration change. */
$(document).ready(function () {
    /* Bind the default "Log" handler once. The button deliberately carries NO inline
       onclick: it swaps between Log (POST) and Save (PUT) via .off('click')/.on('click'),
       and jQuery cannot remove an inline onclick, so one would survive the swap and fire
       alongside the rebound handler — creating a duplicate entry on every edit (#41). */
    iris_timelog_reset_add_button();

    $('#iris-timelog-minutes').on('change', function () {
        $('#iris-timelog-custom-wrap').toggle($(this).val() === 'custom');
    });
    // Leaving the modal cancels any in-progress edit.
    $('#iris-timelog-modal').on('hidden.bs.modal', function () {
        iris_timelog_reset_add_button();
    });
    // Fire the opt-in nudge once on case-page load.
    if (typeof get_caseid === 'function') {
        try { iris_timelog_check_nudge(); } catch (e) { /* non-fatal */ }
    }
});

/* Home page (iris-ng v2, Phase 5). Import-free (ui/public - rolldown rule).
 * v2 endpoints return the payload directly; the LEGACY endpoints
 * (/alerts/filter, /activities/list) wrap it in {status, data} - read
 * accordingly (project rule).
 * CaseDetailsSchema is a bare auto-schema over Cases: the fields are the
 * MODEL columns (name, open_date, close_date), NOT case_name. */

var IRIS_HOME_G = {statuses: [], tasks: [], showFinished: false};
var IRIS_HOME_FINISHED = ['Done', 'Canceled'];

function iris_home_esc(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
}

function iris_home_rel(iso) {
    if (!iso) { return ''; }
    var then = new Date(iso).getTime();
    if (isNaN(then)) { return ''; }
    var secs = Math.floor((Date.now() - then) / 1000);
    if (secs < 60) { return 'just now'; }
    if (secs < 3600) { return Math.floor(secs / 60) + 'm ago'; }
    if (secs < 86400) { return Math.floor(secs / 3600) + 'h ago'; }
    if (secs < 2592000) { return Math.floor(secs / 86400) + 'd ago'; }
    return new Date(iso).toISOString().slice(0, 10);
}

/* The legacy lists send naive UTC ("2026-11-09T21:50:25.216032"); read without a zone it would be local time. */
function iris_home_utc(s) {
    var text = String(s || '');
    return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(text) && !/(Z|[+-]\d{2}:?\d{2})$/.test(text) ? text + 'Z' : s;
}

function iris_home_get(url) {
    return fetch(url, { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); });
}

function iris_home_fill(id, rows, emptyText) {
    var el = document.getElementById(id);
    if (!el) { return; }
    el.innerHTML = rows.length ? rows.join('')
        : '<div class="iris-home-empty">' + emptyText + '</div>';
}

function iris_home_set(id, text) {
    var el = document.getElementById(id);
    if (el) { el.textContent = text; }
}

function iris_home_sev(name) {
    if (!name) { return ''; }
    return '<span class="iris-home-sev iris-home-sev-' + iris_home_esc(String(name).toLowerCase())
        + '">' + iris_home_esc(name) + '</span>';
}

function iris_home_attr(s) {
    return iris_home_esc(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function iris_home_num(v) {
    var n = parseInt(v, 10);
    return isNaN(n) ? 0 : n;
}

/* A status menu for a task row; null until the statuses have loaded. attrs are built from numbers only. */
function iris_home_status_select(attrs, current, label) {
    if (!IRIS_HOME_G.statuses.length) { return null; }
    return '<select class="iris-home-status" ' + attrs + ' aria-label="' + iris_home_attr(label) + '">'
        + IRIS_HOME_G.statuses.map(function (s) {
            var id = iris_home_num(s.id);
            return '<option value="' + id + '"' + (id === iris_home_num(current) ? ' selected' : '') + '>' + iris_home_esc(s.status_name) + '</option>';
        }).join('')
        + '</select>';
}

function iris_home_greeting() {
    var h = new Date().getHours();
    var g = h < 5 ? 'Good night' : h < 12 ? 'Good morning'
        : h < 18 ? 'Good afternoon' : 'Good evening';
    iris_home_set('iris-home-greeting', g);
}

function iris_home_cases() {
    iris_home_get('/api/v2/dashboard/cases/list').then(function (list) {
        var open = Array.isArray(list) ? list : [];
        iris_home_set('iris-home-t-cases', String(open.length));
        iris_home_set('iris-home-c-cases', open.length ? String(open.length) : '');
        var rows = open.slice(0, 8).map(function (c) {
            var sev = c.severity && c.severity.severity_name;
            return '<div class="iris-home-item">'
                + '<span><span class="cid">#' + c.case_id + '</span>'
                + '<a href="/case?cid=' + c.case_id + '">'
                + iris_home_esc(String(c.name || '').replace(/^#\d+ - /, '')) + '</a></span>'
                + '<span>' + iris_home_sev(sev)
                + ' <span class="meta">' + iris_home_esc((c.client && c.client.customer_name) || '')
                + ' &middot; ' + iris_home_rel(c.open_date) + '</span></span>'
                + '</div>';
        });
        iris_home_fill('iris-home-cases', rows, 'No open cases assigned to you.');
    }).catch(function () { iris_home_fill('iris-home-cases', [], 'Failed to load.'); });
    // Closed (30d): same endpoint with closed cases included.
    iris_home_get('/api/v2/dashboard/cases/list?show_closed=true').then(function (list) {
        var cutoff = Date.now() - 30 * 86400 * 1000;
        var n = (Array.isArray(list) ? list : []).filter(function (c) {
            if (!c.close_date) { return false; }
            var t = new Date(c.close_date).getTime();
            return !isNaN(t) && t >= cutoff;
        }).length;
        iris_home_set('iris-home-t-closed', String(n));
    }).catch(function () {});
}

function iris_home_alerts() {
    /* LEGACY endpoint + envelope. Owner-scoped server-side; "open" =
       everything whose status is not Closed, filtered client-side (status
       ids vary per deployment - never hardcode). */
    iris_home_get('/alerts/filter?alert_owner_id=' + IRIS_HOME_UID + '&per_page=50')
        .then(function (resp) {
            var d = resp && resp.data ? resp.data : resp;
            var list = (d && (d.alerts || d.data)) || [];
            var open = list.filter(function (a) {
                var st = a.status && a.status.status_name;
                return st !== 'Closed' && st !== 'Merged' && st !== 'Escalated';
            });
            iris_home_set('iris-home-t-alerts', String(open.length));
            iris_home_set('iris-home-c-alerts', open.length ? String(open.length) : '');
            var rows = open.slice(0, 8).map(function (a) {
                var sev = a.severity && a.severity.severity_name;
                return '<div class="iris-home-item">'
                    + '<span><span class="cid">#' + a.alert_id + '</span>'
                    + '<a href="/alerts?alert_ids=' + a.alert_id + '">'
                    + iris_home_esc(a.alert_title) + '</a></span>'
                    + iris_home_sev(sev)
                    + '</div>';
            });
            iris_home_fill('iris-home-alerts', rows, 'No alerts. Nice and quiet.');
        })
        .catch(function () {
            iris_home_set('iris-home-t-alerts', '0');
            iris_home_fill('iris-home-alerts', [], 'No alerts. Nice and quiet.');
        });
}

function iris_home_tasks() {
    /* v3 row shape: bold title, "#id - Case name" subtitle, status pill +
       relative time on the right. The endpoint serializes the Row directly
       (task_case / case_id / status_name / task_last_update). */
    iris_home_get('/api/v2/dashboard/tasks/list').then(function (list) {
        var tasks = Array.isArray(list) ? list : [];
        iris_home_set('iris-home-t-tasks', String(tasks.length));
        iris_home_set('iris-home-c-tasks', tasks.length ? String(tasks.length) : '');
        var rows = tasks.slice(0, 8).map(function (t) {
            var caseName = String(t.task_case || '').replace(/^#\d+ - /, '');
            return '<div class="iris-home-item">'
                + '<span><a href="/case/tasks?cid=' + t.case_id + '" style="font-weight:600;">'
                + iris_home_esc(t.task_title) + '</a>'
                + '<div class="iris-home-sub">#' + t.case_id + ' &middot; '
                + iris_home_esc(caseName) + '</div></span>'
                + '<span class="iris-home-right">'
                + (iris_home_status_select('data-task="' + iris_home_num(t.task_id) + '" data-case="' + iris_home_num(t.case_id) + '"', t.task_status_id, 'Status of ' + t.task_title)
                   || '<span class="iris-home-pill-outline">' + iris_home_esc(t.status_name || '') + '</span>')
                + ' <span class="meta">' + iris_home_rel(t.task_last_update) + '</span></span>'
                + '</div>';
        });
        iris_home_fill('iris-home-tasks', rows, "No pending tasks. You're all caught up.");
    }).catch(function () { iris_home_fill('iris-home-tasks', [], 'Failed to load.'); });
}

function iris_home_reviews() {
    iris_home_get('/api/v2/dashboard/reviews/list').then(function (list) {
        var rows = (Array.isArray(list) ? list : []).slice(0, 6).map(function (c) {
            return '<div class="iris-home-item">'
                + '<a href="/case?cid=' + c.case_id + '">' + iris_home_esc(c.case_name || c.name) + '</a>'
                + '<span class="meta">' + iris_home_esc((c.review_status && c.review_status.status_name) || '') + '</span>'
                + '</div>';
        });
        iris_home_fill('iris-home-reviews', rows, 'No cases awaiting your review.');
    }).catch(function () { iris_home_fill('iris-home-reviews', [], 'Failed to load.'); });
}

function iris_home_notifs() {
    iris_home_get('/api/v2/notifications?per_page=6').then(function (j) {
        var rows = (j.notifications || []).map(function (n) {
            return '<div class="iris-home-item' + (n.is_read ? '" style="opacity:.55;' : '') + '">'
                + '<a href="' + iris_home_esc(n.url || '#') + '">' + iris_home_esc(n.title) + '</a>'
                + '<span class="meta">' + iris_home_rel(n.created_at) + '</span>'
                + '</div>';
        });
        iris_home_fill('iris-home-notifs', rows, 'Nothing addressed to you.');
    }).catch(function () { iris_home_fill('iris-home-notifs', [], 'Failed to load.'); });
}

function iris_home_feed() {
    /* v3's Following card lists the followed OBJECTS (name + chip), not an
       activity feed. The latest activity line per followed case is layered
       on from /follow/feed afterwards, so a followed-but-quiet object still
       shows up ("no activity" and "not followed" are different states -
       project rule). */
    iris_home_get('/api/v2/follow').then(function (list) {
        var items = Array.isArray(list) ? list : [];
        iris_home_set('iris-home-c-follow', items.length ? String(items.length) : '');
        var rows = items.slice(0, 10).map(function (f) {
            return '<div class="iris-home-item">'
                + '<span><span class="iris-home-chip">' + iris_home_esc(f.object_type) + '</span> '
                + '<a href="' + iris_home_esc(f.url || '#') + '">'
                + iris_home_esc(String(f.object_name || ('#' + f.object_id)).replace(/^#\d+ - /, '')) + '</a>'
                + '<div class="text-muted iris-home-fw-act" data-key="'
                + iris_home_esc(f.object_type + ':' + f.object_id)
                + '" style="font-size:0.76rem;"></div></span>'
                + '<span class="meta">followed ' + iris_home_rel(f.created_at) + '</span>'
                + '</div>';
        });
        iris_home_fill('iris-home-feed', rows,
            'Nothing followed yet. Use the Follow button on a case or the star on an alert.');
        if (!items.length) { return; }
        // Layer the newest activity line under each followed object.
        iris_home_get('/api/v2/follow/feed').then(function (j) {
            var seen = {};
            (j.items || []).forEach(function (i) {
                var key = i.object_type + ':' + i.object_id;
                if (seen[key]) { return; }
                seen[key] = true;
                var el = document.querySelector('.iris-home-fw-act[data-key="'
                    + (window.CSS && CSS.escape ? CSS.escape(key) : key) + '"]');
                if (el) {
                    el.textContent = (i.text || '') + ' · ' + iris_home_rel(i.at);
                }
            });
        }).catch(function () {});
    }).catch(function () { iris_home_fill('iris-home-feed', [], 'Failed to load.'); });
}

function iris_home_activities() {
    /* LEGACY endpoint + envelope: rows {case_name, user_name, activity_date,
       activity_desc}. Viewer-relevant slice of what the Activities page shows. */
    iris_home_get('/activities/list').then(function (resp) {
        var list = (resp && resp.data) || [];
        var rows = list.slice(0, 10).map(function (a) {
            return '<div class="iris-home-item">'
                + '<span>' + iris_home_esc(a.activity_desc)
                + '<div class="text-muted" style="font-size:0.74rem;">'
                + iris_home_esc(a.case_name || '') + (a.user_name ? ' &middot; ' + iris_home_esc(a.user_name) : '')
                + '</div></span>'
                + '<span class="meta">' + iris_home_rel(iris_home_utc(a.activity_date)) + '</span>'
                + '</div>';
        });
        iris_home_fill('iris-home-activities', rows, 'No recent activity.');
    }).catch(function () { iris_home_fill('iris-home-activities', [], 'Failed to load.'); });
}

/* ---- Global tasks: team work that belongs to no case. */

function iris_home_gtask(id) {
    return IRIS_HOME_G.tasks.filter(function (t) { return iris_home_num(t.task_id) === id; })[0];
}

function iris_home_gtask_row(t) {
    var id = iris_home_num(t.task_id);
    var title = String(t.task_title || '').trim() || '#' + id;
    var tags = String(t.task_tags || '').split(',').map(function (x) { return x.trim(); }).filter(Boolean).slice(0, 3);
    return '<div class="iris-home-item" data-gtask-row="' + id + '">'
        + '<span class="iris-home-grow"><button type="button" class="iris-home-titlebtn" data-gtask-edit="' + id + '" title="Edit this task">' + iris_home_esc(title) + '</button>'
        + '<div class="iris-home-sub">' + iris_home_esc(t.user_name || '')
        + tags.map(function (x) { return ' <span class="iris-home-chip">' + iris_home_esc(x) + '</span>'; }).join('')
        + '</div></span>'
        + '<span class="iris-home-right">'
        + (iris_home_status_select('data-gtask="' + id + '"', t.task_status_id, 'Status of ' + title)
           || '<span class="iris-home-pill-outline">' + iris_home_esc(t.status_name || '') + '</span>')
        + ' <span class="meta">' + iris_home_rel(iris_home_utc(t.task_last_update)) + '</span></span>'
        + '</div>';
}

function iris_home_draw_gtasks() {
    var finishedOf = function (t) { return IRIS_HOME_FINISHED.indexOf(t.status_name) !== -1; };
    var recent = function (a, b) { return String(b.task_last_update || '').localeCompare(String(a.task_last_update || '')); };
    var open = IRIS_HOME_G.tasks.filter(function (t) { return !finishedOf(t); }).sort(recent);
    var finished = IRIS_HOME_G.tasks.filter(finishedOf).sort(recent);
    var shown = IRIS_HOME_G.showFinished ? open.concat(finished) : open;
    iris_home_fill('iris-home-gtasks', shown.map(iris_home_gtask_row), finished.length ? 'No open global tasks.' : 'No global tasks yet. Add one for team work not tied to a case.');
    iris_home_set('iris-home-c-gtasks', open.length ? String(open.length) : '');
    var toggle = document.getElementById('iris-home-gtask-finished');
    toggle.hidden = !finished.length;
    toggle.textContent = (IRIS_HOME_G.showFinished ? 'Hide finished (' : 'Show finished (') + finished.length + ')';
    toggle.setAttribute('aria-pressed', IRIS_HOME_G.showFinished ? 'true' : 'false');
}

/* Also the source of the task statuses the two status menus offer. */
function iris_home_gtasks() {
    return iris_home_get('/global/tasks/list').then(function (resp) {
        var d = (resp && resp.data) || {};
        IRIS_HOME_G.statuses = d.tasks_status || [];
        IRIS_HOME_G.tasks = d.tasks || [];
        iris_home_draw_gtasks();
    }).catch(function () { iris_home_fill('iris-home-gtasks', [], 'Failed to load.'); });
}

function iris_home_gtask_saved(data) {
    if (notify_auto_api(data)) {
        iris_home_gtasks();
        $('#modal_add_gtask').modal('hide');
    }
}

function iris_home_gtask_form() {
    var data = $('#form_new_gtask').serializeObject();
    data.task_tags = $('#task_tags').val();
    data.task_assignee_id = $('#task_assignee_id').val();
    data.task_status_id = $('#task_status_id').val();
    data.csrf_token = $('#csrf_token').val();
    return JSON.stringify(data);
}

function add_gtask() {
    var url = '/global/tasks/add/modal' + case_param();
    $('#modal_add_gtask_content').load(url, function (response, status, xhr) {
        if (status !== 'success') {
            ajax_notify_error(xhr, url);
            return false;
        }
        $('#submit_new_gtask').on('click', function () {
            post_request_api('/global/tasks/add', iris_home_gtask_form(), true).done(iris_home_gtask_saved);
            return false;
        });
        $('#modal_add_gtask').modal({show: true});
    });
}

function edit_gtask(id) {
    var url = '/global/tasks/update/' + iris_home_num(id) + '/modal' + case_param();
    $('#modal_add_gtask_content').load(url, function (response, status, xhr) {
        if (status !== 'success') {
            ajax_notify_error(xhr, url);
            return false;
        }
        $('#modal_add_gtask').modal({show: true});
    });
}

/* The two below are called from the dialog's own buttons. */
function update_gtask(id) {
    post_request_api('/global/tasks/update/' + iris_home_num(id), iris_home_gtask_form(), true).done(iris_home_gtask_saved);
}

function delete_gtask(id) {
    do_deletion_prompt('You are about to delete this global task.').then(function (doDelete) {
        if (doDelete) {
            post_request_api('/global/tasks/delete/' + iris_home_num(id)).done(iris_home_gtask_saved);
        }
    });
}

function iris_home_wire_tasks() {
    $('#iris-home-gtask-add').on('click', function () { add_gtask(); });
    $('#iris-home-gtask-finished').on('click', function () {
        IRIS_HOME_G.showFinished = !IRIS_HOME_G.showFinished;
        iris_home_draw_gtasks();
    });
    $('#iris-home-gtasks').on('click', 'button[data-gtask-edit]', function () { edit_gtask(this.getAttribute('data-gtask-edit')); });
    $('#iris-home-gtasks').on('change', 'select[data-gtask]', function () {
        var id = iris_home_num(this.getAttribute('data-gtask'));
        var t = iris_home_gtask(id);
        if (!t) { return; }
        var body = {task_title: t.task_title, task_assignee_id: t.task_assignee_id, task_status_id: iris_home_num(this.value), csrf_token: $('#csrf_token').val()};
        post_request_api('/global/tasks/update/' + id, JSON.stringify(body), true)
            .done(function (data) { notify_auto_api(data); iris_home_gtasks(); })
            .fail(function () { iris_home_gtasks(); });
    });
    /* The address carries the task's own case, not the one the page happens to be on. */
    $('#iris-home-tasks').on('change', 'select[data-task]', function () {
        var caseId = iris_home_num(this.getAttribute('data-case'));
        var body = {task_id: iris_home_num(this.getAttribute('data-task')), case_id: caseId, task_status_id: iris_home_num(this.value), csrf_token: $('#csrf_token').val()};
        post_request_api('/user/tasks/status/update', JSON.stringify(body), true, undefined, caseId)
            .done(function (data) { notify_auto_api(data); iris_home_tasks(); })
            .fail(function () { iris_home_tasks(); });
    });
}

$(function () {
    iris_home_greeting();
    iris_home_wire_tasks();
    iris_home_cases();
    iris_home_alerts();
    iris_home_gtasks().then(iris_home_tasks);
    iris_home_reviews();
    iris_home_notifs();
    iris_home_feed();
    iris_home_activities();
});

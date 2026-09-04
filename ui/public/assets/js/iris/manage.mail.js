/* iris-ng v2 (Phase 1): Mail settings tab — rules CRUD, condition editor,
 * dry-run test, Poll Now, connection tests, ingest activity log.
 *
 * Import-free on purpose (lives in ui/public/ → copied verbatim, no rolldown
 * pass). Talks to /api/v2/mail* which uses the v2 envelope: THE RESPONSE IS
 * THE DATA — no {status,data} wrapper. Browser POSTs carry csrf_token in the
 * BODY (project rule; the X-CSRFToken header is never read).
 */

var IRIS_MAIL = {
    _rules: []
};

function iris_mail_csrf() {
    return $('#csrf_token').val();
}

function iris_mail_esc(s) {
    return $('<div>').text(s == null ? '' : String(s)).html();
}

function iris_mail_fetch(path, method, body) {
    var opts = {
        method: method || 'GET',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin'
    };
    if (body !== undefined) {
        body = Object.assign({}, body, { csrf_token: iris_mail_csrf() });
        opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (r) {
        if (r.status === 204) { return { __status: 204 }; }
        return r.json().then(function (j) { j = j || {}; j.__status = r.status; return j; });
    });
}

/* ------------------------------------------------------------ rules table */

function iris_mail_rules_load() {
    // The rules table lives on /manage/mail-rules since the v3 Settings
    // split; this file also loads on /manage/settings (Test buttons),
    // where the tab-shown handler would otherwise fetch for nothing.
    if (!document.getElementById('iris-mail-rules-body')) { return; }
    iris_mail_fetch('/api/v2/mail-rules').then(function (rules) {
        if (rules.__status !== 200) {
            $('#iris-mail-rules-body').html('<tr><td colspan="8" class="text-danger">Failed to load rules (HTTP ' + rules.__status + ')</td></tr>');
            return;
        }
        delete rules.__status;
        var list = Array.isArray(rules) ? rules : [];
        IRIS_MAIL._rules = list;
        if (!list.length) {
            $('#iris-mail-rules-body').html('<tr><td colspan="8" class="text-muted">No rules configured. Nothing is ingested until a rule (or a fallback rule) exists.</td></tr>');
            return;
        }
        var custNames = {};
        $('#mr-customer option').each(function () { custNames[$(this).val()] = $(this).text(); });
        var rows = list.map(function (r) {
            var conds = (r.conditions || []).map(function (c) {
                return iris_mail_esc(c.field) + ' ~ /' + iris_mail_esc(c.regex) + '/';
            }).join('<br>') || '<span class="text-muted">(matches everything)</span>';
            return '<tr>' +
                '<td>' + iris_mail_esc(r.priority) + '</td>' +
                '<td>' + iris_mail_esc(r.name) + '</td>' +
                '<td>' + iris_mail_esc(r.action) + '</td>' +
                '<td>' + iris_mail_esc(custNames[String(r.customer_id)] || r.customer_id) + '</td>' +
                '<td style="font-family:monospace; font-size:0.8rem;">' + conds + '</td>' +
                '<td>' + (r.enabled ? 'yes' : '<span class="text-muted">no</span>') + '</td>' +
                '<td>' + (r.is_fallback ? 'yes' : '') + '</td>' +
                '<td class="text-right">' +
                '<button type="button" class="btn btn-xs btn-outline-secondary iris-mail-rule-edit" data-rule-id="' + r.id + '">Edit</button> ' +
                '<button type="button" class="btn btn-xs btn-outline-danger iris-mail-rule-del" data-rule-id="' + r.id + '">Delete</button>' +
                '</td></tr>';
        });
        $('#iris-mail-rules-body').html(rows.join(''));
    });
}

/* ------------------------------------------------------------ rule editor */

function iris_mail_cond_add(field, regex) {
    var row = $('<div class="row mb-1 iris-mail-cond-row">' +
        '<div class="col-md-3"><select class="form-control form-control-sm mr-cond-field">' +
        '<option value="subject">subject</option><option value="from">from</option>' +
        '<option value="to">to</option><option value="body">body</option></select></div>' +
        '<div class="col-md-7"><input type="text" class="form-control form-control-sm mr-cond-regex" placeholder="regex (case-insensitive search)"></div>' +
        '<div class="col-md-2"><button type="button" class="btn btn-xs btn-outline-danger mr-cond-del">remove</button></div>' +
        '</div>');
    if (field) { row.find('.mr-cond-field').val(field); }
    if (regex) { row.find('.mr-cond-regex').val(regex); }
    $('#mr-conditions').append(row);
}

function iris_mail_conditions_read() {
    var conds = [];
    $('#mr-conditions .iris-mail-cond-row').each(function () {
        var regex = $(this).find('.mr-cond-regex').val();
        if (regex && regex.trim()) {
            conds.push({ field: $(this).find('.mr-cond-field').val(), regex: regex });
        }
    });
    return conds;
}

function iris_mail_rule_new() {
    $('#iris-mail-rule-editor-title').text('New rule');
    $('#mr-edit-id').val('');
    $('#mr-name').val('');
    $('#mr-priority').val('100');
    $('#mr-action').val('create_alert');
    $('#mr-enabled').prop('checked', true);
    $('#mr-fallback').prop('checked', false);
    $('#mr-severity').val('');
    $('#mr-classification').val('');
    $('#mr-title-template').val('');
    $('#mr-source').val('Mail');
    $('#mr-conditions').empty();
    $('#mr-test-result').text('');
    $('#mr-save-result').text('');
    $('#iris-mail-rule-editor').show();
}

function iris_mail_rule_edit(ruleId) {
    var r = IRIS_MAIL._rules.find(function (x) { return String(x.id) === String(ruleId); });
    if (!r) { return; }
    iris_mail_rule_new();
    $('#iris-mail-rule-editor-title').text('Edit rule: ' + r.name);
    $('#mr-edit-id').val(r.id);
    $('#mr-name').val(r.name);
    $('#mr-priority').val(r.priority);
    $('#mr-action').val(r.action);
    $('#mr-enabled').prop('checked', !!r.enabled);
    $('#mr-fallback').prop('checked', !!r.is_fallback);
    $('#mr-customer').val(String(r.customer_id));
    $('#mr-severity').val(r.severity_id == null ? '' : String(r.severity_id));
    $('#mr-classification').val(r.classification_id == null ? '' : String(r.classification_id));
    $('#mr-title-template').val(r.title_template || '');
    $('#mr-source').val(r.alert_source || 'Mail');
    (r.conditions || []).forEach(function (c) { iris_mail_cond_add(c.field, c.regex); });
}

function iris_mail_rule_cancel() {
    $('#iris-mail-rule-editor').hide();
}

function iris_mail_rule_save() {
    var body = {
        name: $('#mr-name').val(),
        priority: parseInt($('#mr-priority').val(), 10) || 100,
        action: $('#mr-action').val(),
        enabled: $('#mr-enabled').is(':checked'),
        is_fallback: $('#mr-fallback').is(':checked'),
        customer_id: parseInt($('#mr-customer').val(), 10),
        severity_id: $('#mr-severity').val() ? parseInt($('#mr-severity').val(), 10) : null,
        classification_id: $('#mr-classification').val() ? parseInt($('#mr-classification').val(), 10) : null,
        title_template: $('#mr-title-template').val() || null,
        alert_source: $('#mr-source').val() || 'Mail',
        conditions: iris_mail_conditions_read()
    };
    var editId = $('#mr-edit-id').val();
    var req = editId
        ? iris_mail_fetch('/api/v2/mail-rules/' + editId, 'PUT', body)
        : iris_mail_fetch('/api/v2/mail-rules', 'POST', body);
    req.then(function (j) {
        if (j.__status === 200 || j.__status === 201) {
            $('#mr-save-result').html('<span class="text-success">saved</span>');
            $('#iris-mail-rule-editor').hide();
            iris_mail_rules_load();
        } else {
            $('#mr-save-result').html('<span class="text-danger">' + iris_mail_esc(JSON.stringify(j.data || j.message || j)) + '</span>');
        }
    });
}

function iris_mail_rule_test() {
    var sample = { subject: $('#mr-test-sample').val() || '' };
    iris_mail_fetch('/api/v2/mail-rules/test', 'POST',
        { conditions: iris_mail_conditions_read(), sample: sample })
        .then(function (j) {
            if (j.__status !== 200) {
                $('#mr-test-result').html('<span class="text-danger">error</span>');
            } else if (j.matches) {
                $('#mr-test-result').html('<span class="text-success">MATCH</span>');
            } else {
                $('#mr-test-result').html('<span class="text-warning">no match</span>');
            }
        });
}

/* ---------------------------------------------------- poll & connection */

function iris_mail_poll_now() {
    $('#iris-mail-imap-test-result').text('polling…');
    iris_mail_fetch('/api/v2/mail/poll', 'POST', {}).then(function (j) {
        if (j.__status === 200) {
            $('#iris-mail-imap-test-result').html('<span class="text-success">poll queued (task ' + iris_mail_esc(j.task_id) + ') — refresh the activity log below in a moment</span>');
            setTimeout(iris_mail_log_load, 5000);
        } else {
            $('#iris-mail-imap-test-result').html('<span class="text-danger">failed (HTTP ' + j.__status + ')</span>');
        }
    });
}

function iris_mail_test_connection(target) {
    var slot = target === 'imap' ? '#iris-mail-imap-test-result' : '#iris-mail-smtp-test-result';
    $(slot).text('testing…');
    iris_mail_fetch('/api/v2/mail/test-connection', 'POST', { target: target }).then(function (j) {
        if (j.__status !== 200) {
            $(slot).html('<span class="text-danger">request failed (HTTP ' + j.__status + ')</span>');
        } else if (j.ok) {
            $(slot).html('<span class="text-success">' + iris_mail_esc(j.detail) + '</span>');
        } else {
            $(slot).html('<span class="text-danger">' + iris_mail_esc(j.detail) + '</span>');
        }
    });
}

/* ------------------------------------------------------------- ingest log */

function iris_mail_log_load() {
    if (!document.getElementById('iris-mail-log-body')) { return; }
    iris_mail_fetch('/api/v2/mail/ingest-log?per_page=25').then(function (j) {
        if (j.__status !== 200) { return; }
        var rows = (j.rows || []).map(function (r) {
            var alert = r.alert_id
                ? '<a href="/alerts?cid=1#alert=' + r.alert_id + '">#' + r.alert_id + '</a>'
                : '';
            return '<tr>' +
                '<td>' + iris_mail_esc((r.processed_at || '').replace('T', ' ').slice(0, 19)) + '</td>' +
                '<td>' + iris_mail_esc(r.from_addr) + '</td>' +
                '<td>' + iris_mail_esc(r.subject) + '</td>' +
                '<td>' + iris_mail_esc(r.outcome) + '</td>' +
                '<td>' + iris_mail_esc(r.rule_name || '') + '</td>' +
                '<td>' + alert + '</td>' +
                '<td class="text-danger" style="font-size:0.8rem;">' + iris_mail_esc(r.error || '') + '</td>' +
                '</tr>';
        });
        $('#iris-mail-log-body').html(rows.length ? rows.join('')
            : '<tr><td colspan="7" class="text-muted">No messages ingested yet.</td></tr>');
    });
}

/* --------------------------------------------------------------- wiring */

$(function () {
    // Delegated handlers: rows re-render on every load, and inline onclick
    // with embedded ids is against project rules (data-* + delegation).
    $(document).on('click', '.iris-mail-rule-edit', function () {
        iris_mail_rule_edit($(this).attr('data-rule-id'));
    });
    $(document).on('click', '.iris-mail-rule-del', function () {
        var id = $(this).attr('data-rule-id');
        if (!confirm('Delete this mail rule? The ingest log keeps its rows.')) { return; }
        fetch('/api/v2/mail-rules/' + id, { method: 'DELETE', credentials: 'same-origin' })
            .then(function () { iris_mail_rules_load(); });
    });
    $(document).on('click', '.mr-cond-del', function () {
        $(this).closest('.iris-mail-cond-row').remove();
    });
    // Lazy-load table data when the tab is first shown.
    $('#tab-mail-tab').on('shown.bs.tab', function () {
        iris_mail_rules_load();
        iris_mail_log_load();
    });
});

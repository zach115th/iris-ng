/* iris-ng v2 (Phase 3): Flows settings tab — flow CRUD with a steps editor,
 * condition builder reuse, dry-run test, deploy-to-existing.
 *
 * Steps editor rows carry a hidden step id: the PUT endpoint merges by id
 * so analyst progress on kept steps survives edits (removing a row removes
 * that step's recorded progress everywhere — the tab says so).
 *
 * Import-free (ui/public/). v2 envelope; csrf in the body; delegated
 * data-* handlers.
 */

var IRIS_FLW = {
    _flows: []
};

function iris_flw_csrf() {
    return $('#csrf_token').val();
}

function iris_flw_esc(s) {
    return $('<div>').text(s == null ? '' : String(s)).html();
}

function iris_flw_fetch(path, method, body) {
    var opts = {
        method: method || 'GET',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin'
    };
    if (body !== undefined) {
        body = Object.assign({}, body, { csrf_token: iris_flw_csrf() });
        opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (r) {
        if (r.status === 204) { return { __status: 204 }; }
        return r.json().then(function (j) {
            j = (j && typeof j === 'object') ? j : { value: j };
            j.__status = r.status;
            return j;
        }).catch(function () { return { __status: r.status }; });
    });
}

/* ------------------------------------------------------------ flows table */

function iris_flw_load() {
    iris_flw_fetch('/api/v2/investigation-flows').then(function (flows) {
        if (flows.__status !== 200) {
            $('#iris-flw-body').html('<tr><td colspan="7" class="text-danger">Failed '
                + 'to load flows (HTTP ' + flows.__status + ')</td></tr>');
            return;
        }
        delete flows.__status;
        var list = Array.isArray(flows) ? flows : [];
        IRIS_FLW._flows = list;
        if (!list.length) {
            $('#iris-flw-body').html('<tr><td colspan="7" class="text-muted">No flows. '
                + 'Checklists attach to alerts/clusters once a flow exists.</td></tr>');
            return;
        }
        var rows = list.map(function (f) {
            var conds = (!f.match_conditions || !Object.keys(f.match_conditions).length)
                ? '<span class="text-muted">(matches everything)</span>'
                : iris_flw_esc(JSON.stringify(f.match_conditions).slice(0, 60) + '…');
            return '<tr>'
                + '<td>' + iris_flw_esc(f.priority) + '</td>'
                + '<td>' + iris_flw_esc(f.name) + '</td>'
                + '<td>' + iris_flw_esc(f.target) + '</td>'
                + '<td>' + (f.steps || []).length + '</td>'
                + '<td style="font-family: monospace; font-size: 0.78rem;">' + conds + '</td>'
                + '<td>' + (f.enabled ? 'yes' : '<span class="text-muted">no</span>') + '</td>'
                + '<td class="text-right">'
                + '<button type="button" class="btn btn-xs btn-outline-secondary '
                + 'iris-flw-edit" data-flow-id="' + f.id + '">Edit</button> '
                + '<button type="button" class="btn btn-xs btn-outline-danger '
                + 'iris-flw-del" data-flow-id="' + f.id + '">Delete</button>'
                + '</td></tr>';
        });
        $('#iris-flw-body').html(rows.join(''));
    });
}

/* ------------------------------------------------------------ steps editor */

function iris_flw_step_add(step) {
    step = step || {};
    var row = $('<div class="row mb-1 iris-flw-step-row">'
        + '<input type="hidden" class="fw-step-id">'
        + '<div class="col-md-4"><input type="text" class="form-control '
        + 'form-control-sm fw-step-title" placeholder="step title"></div>'
        + '<div class="col-md-4"><input type="text" class="form-control '
        + 'form-control-sm fw-step-desc" placeholder="description (optional)"></div>'
        + '<div class="col-md-2 pt-1"><label style="font-size: 0.8rem;">'
        + '<input type="checkbox" class="fw-step-req"> required</label></div>'
        + '<div class="col-md-2">'
        + '<button type="button" class="btn btn-xs btn-outline-secondary fw-step-up" title="move up">&#8593;</button> '
        + '<button type="button" class="btn btn-xs btn-outline-secondary fw-step-down" title="move down">&#8595;</button> '
        + '<button type="button" class="btn btn-xs btn-outline-danger fw-step-del">&#10005;</button>'
        + '</div></div>');
    if (step.id) { row.find('.fw-step-id').val(step.id); }
    if (step.title) { row.find('.fw-step-title').val(step.title); }
    if (step.description) { row.find('.fw-step-desc').val(step.description); }
    row.find('.fw-step-req').prop('checked', !!step.is_required);
    $('#fw-steps').append(row);
}

function iris_flw_steps_read() {
    var steps = [];
    $('#fw-steps .iris-flw-step-row').each(function () {
        var title = $(this).find('.fw-step-title').val().trim();
        if (!title) { return; }
        var idVal = $(this).find('.fw-step-id').val();
        steps.push({
            id: idVal ? parseInt(idVal, 10) : null,
            title: title,
            description: $(this).find('.fw-step-desc').val() || null,
            is_required: $(this).find('.fw-step-req').is(':checked')
        });
    });
    return steps;
}

/* ------------------------------------------------------------ flow editor */

function iris_flw_new() {
    $('#iris-flw-editor-title').text('New flow');
    $('#fw-edit-id').val('');
    $('#fw-name').val('');
    $('#fw-description').val('');
    $('#fw-priority').val('100');
    $('#fw-target').val('alert');
    $('#fw-enabled').prop('checked', true);
    $('#fw-steps').empty();
    iris_flw_step_add();
    $('#fw-test-result').text('');
    $('#fw-save-result').text('');
    window.IrisConditionBuilder.mount('#fw-conditions', {});
    $('#iris-flw-editor').show();
}

function iris_flw_edit(flowId) {
    var f = IRIS_FLW._flows.find(function (x) { return String(x.id) === String(flowId); });
    if (!f) { return; }
    iris_flw_new();
    $('#iris-flw-editor-title').text('Edit flow: ' + f.name);
    $('#fw-edit-id').val(f.id);
    $('#fw-name').val(f.name);
    $('#fw-description').val(f.description || '');
    $('#fw-priority').val(f.priority);
    $('#fw-target').val(f.target);
    $('#fw-enabled').prop('checked', !!f.enabled);
    $('#fw-steps').empty();
    (f.steps || []).forEach(function (s) { iris_flw_step_add(s); });
    if (!(f.steps || []).length) { iris_flw_step_add(); }
    window.IrisConditionBuilder.mount('#fw-conditions', f.match_conditions || {});
}

function iris_flw_cancel() {
    $('#iris-flw-editor').hide();
}

function iris_flw_save() {
    var cond = window.IrisConditionBuilder.read('#fw-conditions');
    if (cond.error) {
        $('#fw-save-result').html('<span class="text-danger">'
            + iris_flw_esc(cond.error) + '</span>');
        return;
    }
    var body = {
        name: $('#fw-name').val(),
        description: $('#fw-description').val() || null,
        priority: parseInt($('#fw-priority').val(), 10) || 100,
        target: $('#fw-target').val(),
        enabled: $('#fw-enabled').is(':checked'),
        match_conditions: cond.tree,
        steps: iris_flw_steps_read()
    };
    var editId = $('#fw-edit-id').val();
    var req = editId
        ? iris_flw_fetch('/api/v2/investigation-flows/' + editId, 'PUT', body)
        : iris_flw_fetch('/api/v2/investigation-flows', 'POST', body);
    req.then(function (j) {
        if (j.__status === 200 || j.__status === 201) {
            $('#fw-save-result').html('<span class="text-success">saved</span>');
            $('#iris-flw-editor').hide();
            iris_flw_load();
        } else {
            $('#fw-save-result').html('<span class="text-danger">'
                + iris_flw_esc(JSON.stringify(j.data || j.message || j)) + '</span>');
        }
    });
}

function iris_flw_test() {
    var cond = window.IrisConditionBuilder.read('#fw-conditions');
    if (cond.error) {
        $('#fw-test-result').html('<span class="text-danger">'
            + iris_flw_esc(cond.error) + '</span>');
        return;
    }
    iris_flw_fetch('/api/v2/investigation-flows/test', 'POST', {
        conditions: cond.tree,
        last_n: parseInt($('#fw-test-lastn').val(), 10) || 20
    }).then(function (j) {
        if (j.__status !== 200) {
            $('#fw-test-result').html('<span class="text-danger">'
                + iris_flw_esc(JSON.stringify(j.data || j.message
                    || ('HTTP ' + j.__status))) + '</span>');
            return;
        }
        $('#fw-test-result').html('<span class="'
            + (j.matched ? 'text-success' : 'text-warning') + '">'
            + j.matched + ' / ' + j.evaluated + ' matched</span>');
    });
}

function iris_flw_deploy() {
    if (!confirm('Deploy: attach matching flows to every existing alert and '
                 + 'cluster? Already-attached anchors are skipped.')) { return; }
    iris_flw_fetch('/api/v2/investigation-flows/deploy', 'POST', {})
        .then(function (j) {
            if (j.__status === 202) {
                alert('Deploy queued (task ' + j.task_id + ').');
            } else {
                alert('Deploy failed (HTTP ' + j.__status + ')');
            }
        });
}

/* --------------------------------------------------------------- wiring */

$(function () {
    $(document).on('click', '.iris-flw-edit', function () {
        iris_flw_edit($(this).attr('data-flow-id'));
    });
    $(document).on('click', '.iris-flw-del', function () {
        var id = $(this).attr('data-flow-id');
        if (!confirm('Delete this flow? Its checklists (and their progress) are '
                     + 'removed from every alert and cluster.')) { return; }
        fetch('/api/v2/investigation-flows/' + id,
              { method: 'DELETE', credentials: 'same-origin' })
            .then(function () { iris_flw_load(); });
    });
    $(document).on('click', '.fw-step-del', function () {
        $(this).closest('.iris-flw-step-row').remove();
    });
    $(document).on('click', '.fw-step-up', function () {
        var row = $(this).closest('.iris-flw-step-row');
        row.prev('.iris-flw-step-row').before(row);
    });
    $(document).on('click', '.fw-step-down', function () {
        var row = $(this).closest('.iris-flw-step-row');
        row.next('.iris-flw-step-row').after(row);
    });
    $('#tab-flows-tab').on('shown.bs.tab', function () {
        iris_flw_load();
    });
});

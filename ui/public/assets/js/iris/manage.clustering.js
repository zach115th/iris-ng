/* iris-ng v2 (Phase 2): Clustering settings tab — rules CRUD, condition
 * builder (window.IrisConditionBuilder), dry-run test, per-rule backfill.
 *
 * Import-free (ui/public/). v2 envelope: THE RESPONSE IS THE DATA. POSTs
 * carry csrf_token in the BODY. Row actions are delegated with data-*
 * attributes, read via .attr() (never .data() — it int-coerces).
 */

var IRIS_CLU = {
    _rules: []
};

function iris_clu_csrf() {
    return $('#csrf_token').val();
}

function iris_clu_esc(s) {
    return $('<div>').text(s == null ? '' : String(s)).html();
}

function iris_clu_fetch(path, method, body) {
    var opts = {
        method: method || 'GET',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin'
    };
    if (body !== undefined) {
        body = Object.assign({}, body, { csrf_token: iris_clu_csrf() });
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

function iris_clu_cond_summary(tree) {
    if (!tree || !Object.keys(tree).length) {
        return '<span class="text-muted">(matches everything)</span>';
    }
    if (tree.field) {
        return iris_clu_esc(tree.field + ' ' + tree.operator + ' '
            + JSON.stringify(tree.value));
    }
    var comb = tree.and ? 'and' : (tree.or ? 'or' : (tree.not ? 'not' : '?'));
    var n = Array.isArray(tree[comb]) ? tree[comb].length : 1;
    return iris_clu_esc(comb.toUpperCase() + ' (' + n + ' condition'
        + (n === 1 ? '' : 's') + ')');
}

/* ------------------------------------------------------------ rules table */

function iris_clu_rules_load() {
    iris_clu_fetch('/api/v2/alert-clustering-rules').then(function (rules) {
        if (rules.__status !== 200) {
            $('#iris-clu-rules-body').html('<tr><td colspan="7" class="text-danger">'
                + 'Failed to load rules (HTTP ' + rules.__status + ')</td></tr>');
            return;
        }
        delete rules.__status;
        var list = Array.isArray(rules) ? rules : [];
        IRIS_CLU._rules = list;
        if (!list.length) {
            $('#iris-clu-rules-body').html('<tr><td colspan="7" class="text-muted">'
                + 'No clustering rules. Alerts are not grouped until one exists.</td></tr>');
            return;
        }
        var rows = list.map(function (r) {
            return '<tr>'
                + '<td>' + iris_clu_esc(r.priority) + '</td>'
                + '<td>' + iris_clu_esc(r.name) + '</td>'
                + '<td style="font-family: monospace; font-size: 0.8rem;">'
                + iris_clu_cond_summary(r.match_conditions) + '</td>'
                + '<td style="font-family: monospace; font-size: 0.8rem;">'
                + iris_clu_esc((r.correlation_keys || []).join(', ')) + '</td>'
                + '<td>' + iris_clu_esc(r.window_minutes) + '</td>'
                + '<td>' + (r.enabled ? 'yes' : '<span class="text-muted">no</span>') + '</td>'
                + '<td class="text-right">'
                + '<button type="button" class="btn btn-xs btn-outline-secondary '
                + 'iris-clu-rule-edit" data-rule-id="' + r.id + '">Edit</button> '
                + '<button type="button" class="btn btn-xs btn-outline-secondary '
                + 'iris-clu-rule-backfill" data-rule-id="' + r.id + '">Backfill</button> '
                + '<button type="button" class="btn btn-xs btn-outline-danger '
                + 'iris-clu-rule-del" data-rule-id="' + r.id + '">Delete</button>'
                + '</td></tr>';
        });
        $('#iris-clu-rules-body').html(rows.join(''));
    });
}

/* ------------------------------------------------------------ rule editor */

function iris_clu_rule_new() {
    $('#iris-clu-rule-editor-title').text('New rule');
    $('#cr-edit-id').val('');
    $('#cr-name').val('');
    $('#cr-priority').val('100');
    $('#cr-window').val('1440');
    $('#cr-enabled').prop('checked', true);
    $('#cr-keys').val('');
    $('#cr-title-template').val('');
    $('#cr-test-result').text('');
    $('#cr-test-detail').empty();
    $('#cr-save-result').text('');
    window.IrisConditionBuilder.mount('#cr-conditions', {});
    $('#iris-clu-rule-editor').show();
}

function iris_clu_rule_edit(ruleId) {
    var r = IRIS_CLU._rules.find(function (x) { return String(x.id) === String(ruleId); });
    if (!r) { return; }
    iris_clu_rule_new();
    $('#iris-clu-rule-editor-title').text('Edit rule: ' + r.name);
    $('#cr-edit-id').val(r.id);
    $('#cr-name').val(r.name);
    $('#cr-priority').val(r.priority);
    $('#cr-window').val(r.window_minutes);
    $('#cr-enabled').prop('checked', !!r.enabled);
    $('#cr-keys').val((r.correlation_keys || []).join(', '));
    $('#cr-title-template').val(r.title_template || '');
    window.IrisConditionBuilder.mount('#cr-conditions', r.match_conditions || {});
}

function iris_clu_rule_cancel() {
    $('#iris-clu-rule-editor').hide();
}

function iris_clu_read_keys() {
    return $('#cr-keys').val().split(',')
        .map(function (s) { return s.trim(); })
        .filter(function (s) { return s.length; });
}

function iris_clu_rule_save() {
    var cond = window.IrisConditionBuilder.read('#cr-conditions');
    if (cond.error) {
        $('#cr-save-result').html('<span class="text-danger">'
            + iris_clu_esc(cond.error) + '</span>');
        return;
    }
    var body = {
        name: $('#cr-name').val(),
        priority: parseInt($('#cr-priority').val(), 10) || 100,
        window_minutes: parseInt($('#cr-window').val(), 10) || 1440,
        enabled: $('#cr-enabled').is(':checked'),
        correlation_keys: iris_clu_read_keys(),
        title_template: $('#cr-title-template').val() || null,
        match_conditions: cond.tree
    };
    var editId = $('#cr-edit-id').val();
    var req = editId
        ? iris_clu_fetch('/api/v2/alert-clustering-rules/' + editId, 'PUT', body)
        : iris_clu_fetch('/api/v2/alert-clustering-rules', 'POST', body);
    req.then(function (j) {
        if (j.__status === 200 || j.__status === 201) {
            $('#cr-save-result').html('<span class="text-success">saved</span>');
            $('#iris-clu-rule-editor').hide();
            iris_clu_rules_load();
        } else {
            $('#cr-save-result').html('<span class="text-danger">'
                + iris_clu_esc(JSON.stringify(j.data || j.message || j)) + '</span>');
        }
    });
}

function iris_clu_rule_test() {
    var cond = window.IrisConditionBuilder.read('#cr-conditions');
    if (cond.error) {
        $('#cr-test-result').html('<span class="text-danger">'
            + iris_clu_esc(cond.error) + '</span>');
        return;
    }
    var lastN = parseInt($('#cr-test-lastn').val(), 10) || 20;
    iris_clu_fetch('/api/v2/alert-clustering-rules/test', 'POST', {
        conditions: cond.tree,
        correlation_keys: iris_clu_read_keys(),
        last_n: lastN
    }).then(function (j) {
        if (j.__status !== 200) {
            $('#cr-test-result').html('<span class="text-danger">'
                + iris_clu_esc(JSON.stringify(j.data || j.message || ('HTTP ' + j.__status)))
                + '</span>');
            return;
        }
        $('#cr-test-result').html('<span class="'
            + (j.matched ? 'text-success' : 'text-warning') + '">'
            + j.matched + ' / ' + j.evaluated + ' matched</span>');
        var rows = (j.results || []).filter(function (r) { return r.matches; })
            .slice(0, 10).map(function (r) {
                var vals = r.correlation_values
                    ? ' <span class="text-muted">' + iris_clu_esc(
                        JSON.stringify(r.correlation_values)) + '</span>'
                    : '';
                return '<div>#' + iris_clu_esc(r.alert_id) + ' '
                    + iris_clu_esc(r.title) + vals + '</div>';
            });
        $('#cr-test-detail').html(rows.join(''));
    });
}

/* --------------------------------------------------------------- wiring */

$(function () {
    $(document).on('click', '.iris-clu-rule-edit', function () {
        iris_clu_rule_edit($(this).attr('data-rule-id'));
    });
    $(document).on('click', '.iris-clu-rule-del', function () {
        var id = $(this).attr('data-rule-id');
        if (!confirm('Delete this clustering rule? Existing clusters survive '
                     + '(their rule reference is cleared).')) { return; }
        fetch('/api/v2/alert-clustering-rules/' + id,
              { method: 'DELETE', credentials: 'same-origin' })
            .then(function () { iris_clu_rules_load(); });
    });
    $(document).on('click', '.iris-clu-rule-backfill', function () {
        var id = $(this).attr('data-rule-id');
        if (!confirm('Backfill: run clustering over every alert not yet in a '
                     + 'cluster (oldest first)?')) { return; }
        var btn = $(this);
        btn.prop('disabled', true).text('Queued…');
        iris_clu_fetch('/api/v2/alert-clustering-rules/' + id + '/backfill', 'POST', {})
            .then(function (j) {
                btn.prop('disabled', false).text('Backfill');
                if (j.__status === 202) {
                    alert('Backfill queued (task ' + j.task_id + '). Results appear '
                          + 'on the Alert Clusters page as it runs.');
                } else {
                    alert('Backfill failed (HTTP ' + j.__status + ')');
                }
            });
    });
    // Lazy-load when the tab is first shown.
    $('#tab-clustering-tab').on('shown.bs.tab', function () {
        iris_clu_rules_load();
    });
});

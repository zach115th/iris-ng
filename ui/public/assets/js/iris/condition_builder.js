/* iris-ng v2 (Phase 2): shared condition-tree builder — window.IrisConditionBuilder.
 *
 * Edits the JSON condition grammar evaluated by business/condition_eval.py:
 *   leaf  {field, operator, value}
 *   group {"and"|"or": [...]} | {"not": node}
 *
 * Two modes:
 *   - SIMPLE: one top-level AND/OR group of leaf rows (covers the common
 *     case). Field is a datalist (known alert_view fields + free-text dotted
 *     paths like alert_context.hostname).
 *   - ADVANCED: raw JSON textarea for arbitrary nesting (not-groups, nested
 *     and/or). The builder opens here automatically when the initial tree
 *     is deeper than simple mode can represent.
 *
 * Reused by the Clustering settings tab (Phase 2) and Investigation Flows
 * (Phase 3). Import-free (ui/public/, no rolldown pass); exposed on window
 * because callers live in separate script files.
 */

(function () {
    'use strict';

    var FIELDS = [
        'alert_title', 'alert_description', 'alert_source', 'alert_source_ref',
        'severity', 'status', 'classification', 'customer',
        'tags', 'asset_names', 'ioc_values',
        'alert_context.', 'alert_source_content.'
    ];
    var OPS = ['eq', 'not', 'in', 'not_in', 'like', 'regex', 'exists'];

    function esc(s) {
        return $('<div>').text(s == null ? '' : String(s)).html();
    }

    /* Is this tree representable in simple mode?
       null/{} yes; {and|or: [leaf, leaf...]} yes; a single leaf yes. */
    function isSimple(tree) {
        if (tree == null || (typeof tree === 'object' && !Object.keys(tree).length)) {
            return true;
        }
        if (typeof tree !== 'object') { return false; }
        if (tree.field && tree.operator) { return true; }
        var comb = tree.and ? 'and' : (tree.or ? 'or' : null);
        if (!comb || !Array.isArray(tree[comb])) { return false; }
        return tree[comb].every(function (n) {
            return n && typeof n === 'object' && n.field && n.operator;
        });
    }

    function leafRow(leaf) {
        leaf = leaf || {};
        var listId = 'icb-fields-datalist';
        var row = $(
            '<div class="row mb-1 icb-leaf-row">'
            + '<div class="col-md-4"><input type="text" list="' + listId + '" '
            + 'class="form-control form-control-sm icb-field" '
            + 'placeholder="field (e.g. alert_context.hostname)"></div>'
            + '<div class="col-md-2"><select class="form-control form-control-sm icb-op">'
            + OPS.map(function (o) { return '<option>' + o + '</option>'; }).join('')
            + '</select></div>'
            + '<div class="col-md-4"><input type="text" '
            + 'class="form-control form-control-sm icb-value" '
            + 'placeholder="value (comma-separate for in/not_in)"></div>'
            + '<div class="col-md-2"><button type="button" '
            + 'class="btn btn-xs btn-outline-danger icb-leaf-del">remove</button></div>'
            + '</div>');
        if (leaf.field) { row.find('.icb-field').val(leaf.field); }
        if (leaf.operator) { row.find('.icb-op').val(leaf.operator); }
        if (leaf.value !== undefined && leaf.value !== null) {
            row.find('.icb-value').val(Array.isArray(leaf.value)
                ? leaf.value.join(', ') : String(leaf.value));
        }
        return row;
    }

    function mount(sel, tree) {
        var $c = $(sel);
        $c.empty().addClass('icb-container');

        if (!document.getElementById('icb-fields-datalist')) {
            $('body').append('<datalist id="icb-fields-datalist">'
                + FIELDS.map(function (f) { return '<option value="' + esc(f) + '">'; }).join('')
                + '</datalist>');
        }

        var simple = isSimple(tree);
        $c.append(
            '<div class="d-flex justify-content-between align-items-center mb-1">'
            + '<div class="icb-simple-head">Match <select class="form-control '
            + 'form-control-sm d-inline-block icb-comb" style="width: 80px;">'
            + '<option value="and">ALL</option><option value="or">ANY</option>'
            + '</select> of:</div>'
            + '<button type="button" class="btn btn-xs btn-outline-secondary icb-mode-toggle">'
            + (simple ? 'Advanced (JSON)' : 'Simple') + '</button></div>'
            + '<div class="icb-simple"><div class="icb-leaves"></div>'
            + '<button type="button" class="btn btn-xs btn-outline-secondary icb-leaf-add">'
            + '+ condition</button>'
            + '<div class="text-muted mt-1" style="font-size: 0.75rem;">'
            + 'No conditions = matches every alert.</div></div>'
            + '<div class="icb-advanced" style="display: none;">'
            + '<textarea class="form-control form-control-sm icb-json" rows="6" '
            + 'style="font-family: monospace;"></textarea>'
            + '<div class="text-muted mt-1" style="font-size: 0.75rem;">'
            + 'Leaves {"field","operator","value"}; groups {"and":[...]}, '
            + '{"or":[...]}, {"not":...}. Empty {} matches everything.</div></div>');

        if (simple) {
            var comb = (tree && tree.or) ? 'or' : 'and';
            $c.find('.icb-comb').val(comb);
            var leaves = [];
            if (tree && tree.field) { leaves = [tree]; }
            else if (tree && (tree.and || tree.or)) { leaves = tree[comb] || []; }
            leaves.forEach(function (l) { $c.find('.icb-leaves').append(leafRow(l)); });
        } else {
            $c.find('.icb-simple').hide();
            $c.find('.icb-simple-head').hide();
            $c.find('.icb-advanced').show();
            $c.find('.icb-json').val(JSON.stringify(tree, null, 2));
        }
    }

    function read(sel) {
        var $c = $(sel);
        if ($c.find('.icb-advanced').is(':visible')) {
            var raw = $c.find('.icb-json').val().trim();
            if (!raw) { return { tree: {} }; }
            try {
                return { tree: JSON.parse(raw) };
            } catch (e) {
                return { error: 'Conditions JSON does not parse: ' + e.message };
            }
        }
        var leaves = [];
        $c.find('.icb-leaf-row').each(function () {
            var field = $(this).find('.icb-field').val().trim();
            var op = $(this).find('.icb-op').val();
            var valRaw = $(this).find('.icb-value').val();
            if (!field) { return; }
            var leaf = { field: field, operator: op };
            if (op === 'exists') {
                var v = valRaw.trim().toLowerCase();
                leaf.value = !(v === 'false' || v === 'no' || v === '0');
            } else if (op === 'in' || op === 'not_in') {
                leaf.value = valRaw.split(',').map(function (s) { return s.trim(); })
                    .filter(function (s) { return s.length; });
            } else {
                leaf.value = valRaw;
            }
            leaves.push(leaf);
        });
        if (!leaves.length) { return { tree: {} }; }
        if (leaves.length === 1) { return { tree: leaves[0] }; }
        var comb = $c.find('.icb-comb').val() === 'or' ? 'or' : 'and';
        var tree = {};
        tree[comb] = leaves;
        return { tree: tree };
    }

    /* Delegated wiring — one binding covers every mounted builder. */
    $(document).on('click', '.icb-leaf-add', function () {
        $(this).closest('.icb-container').find('.icb-leaves').append(leafRow());
    });
    $(document).on('click', '.icb-leaf-del', function () {
        $(this).closest('.icb-leaf-row').remove();
    });
    $(document).on('click', '.icb-mode-toggle', function () {
        var $c = $(this).closest('.icb-container');
        var advVisible = $c.find('.icb-advanced').is(':visible');
        if (advVisible) {
            // JSON -> simple only when representable; else refuse quietly.
            var res = read($c);
            if (res.error || !isSimple(res.tree)) {
                alert(res.error || 'This tree uses nesting simple mode cannot '
                    + 'show — keep editing as JSON.');
                return;
            }
            mount($c, res.tree);
        } else {
            var r = read($c);
            mount($c, r.tree || {});
            $c.find('.icb-mode-toggle').text('Simple');
            $c.find('.icb-simple, .icb-simple-head').hide();
            $c.find('.icb-advanced').show();
            $c.find('.icb-json').val(JSON.stringify(r.tree || {}, null, 2));
        }
    });

    window.IrisConditionBuilder = { mount: mount, read: read, isSimple: isSimple };
})();

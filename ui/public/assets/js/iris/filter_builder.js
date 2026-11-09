/* IrisFilterBuilder - a nested AND / OR condition builder (iris-ng, 2026-11-08; first used by the case queue).
 *
 *   var fb = IrisFilterBuilder.create(container, {
 *       fields: [{key, label, type: text|number|choice|date|tags, options: <source key>, ops: [...]}],
 *       operators: {op: label}, noValueOps: [...], dayOps: [...],
 *       options: {<source key>: [{id, name}]}, limits: {depth, conditions, value, days},
 *       tokens: ['@me'],                // optional: non-numeric values a choice field may hold
 *       onChange: function () {}
 *   });
 *   fb.set(tree); fb.get();            // get() = the COMPLETE conditions only, values re-derived (numbers parsed)
 *   fb.count(); fb.complete(); fb.clear();
 *
 * A tree is {logic: 'and' | 'or', items: [{field, op, value} | <tree>]}. Everything is built with DOM calls -
 * labels and values never pass through HTML parsing (a filter can come from the URL).
 */
(function () {
    'use strict';

    function el(tag, props, kids) {
        var n = document.createElement(tag);
        Object.keys(props || {}).forEach(function (k) {
            var v = props[k];
            if (v === null || v === undefined || v === false) { return; }
            if (k === 'text') { n.textContent = v; }
            else if (k === 'cls') { n.className = v; }
            else if (k === 'on') { Object.keys(v).forEach(function (ev) { n.addEventListener(ev, v[ev]); }); }
            else if (k === 'value') { n.value = v; }
            else { n.setAttribute(k, v === true ? '' : v); }
        });
        (kids || []).forEach(function (c) { if (c) { n.appendChild(c); } });
        return n;
    }

    function create(root, cfg) {
        var fields = cfg.fields || [];
        var byKey = {};
        fields.forEach(function (f) { byKey[f.key] = f; });
        var limits = cfg.limits || {depth: 3, conditions: 40, value: 200, days: 36500};
        var noValue = cfg.noValueOps || ['empty', 'not_empty'];
        var dayOps = cfg.dayOps || ['older_than', 'within'];
        var tokens = cfg.tokens || [];
        var tree = blank();

        function blank() { return {logic: 'and', items: []}; }
        function changed() { if (cfg.onChange) { cfg.onChange(); } }

        function needsValue(op) { return noValue.indexOf(op) === -1; }

        function kind(f, op) {
            if (!needsValue(op)) { return 'none'; }
            if (dayOps.indexOf(op) !== -1) { return 'days'; }
            return f.type;
        }

        function cleanValue(f, op, v) {
            /* The value as the server wants it - re-derived, never the raw text handed on. */
            var k = kind(f, op);
            if (k === 'none') { return null; }
            if (k === 'days' || k === 'number' || k === 'choice') {
                var s = String(v === null || v === undefined ? '' : v).trim();
                if (k === 'choice' && tokens.indexOf(s) !== -1) { return tokens[tokens.indexOf(s)]; }
                if (!/^\d{1,12}$/.test(s)) { return undefined; }
                var n = parseInt(s, 10);
                if (k === 'days' && n > limits.days) { return undefined; }
                return n;
            }
            if (k === 'date') {
                var d = String(v || '').trim();
                return /^\d{4}-\d{2}-\d{2}$/.test(d) ? d.slice(0, 10) : undefined;
            }
            var t = String(v === null || v === undefined ? '' : v).trim();
            return t ? t.slice(0, limits.value) : undefined;
        }

        function leafCount(g) {
            return g.items.reduce(function (n, it) { return n + (it.items ? leafCount(it) : 1); }, 0);
        }

        function prune(g) {
            var out = {logic: g.logic === 'or' ? 'or' : 'and', items: []};
            g.items.forEach(function (it) {
                if (it.items) {
                    var sub = prune(it);
                    if (sub.items.length) { out.items.push(sub); }
                    return;
                }
                var f = byKey[it.field];
                if (!f || f.ops.indexOf(it.op) === -1) { return; }
                var v = cleanValue(f, it.op, it.value);
                if (v === undefined) { return; }
                out.items.push({field: f.key, op: it.op, value: v});
            });
            return out;
        }

        function adopt(g, depth) {
            /* A tree from outside (URL, saved filter, the server's echo) -> the builder's model; unknown fields and
               operators are dropped, values become editable text. */
            var out = {logic: g && g.logic === 'or' ? 'or' : 'and', items: []};
            ((g && Array.isArray(g.items)) ? g.items : []).forEach(function (it) {
                if (!it || typeof it !== 'object') { return; }
                if (Array.isArray(it.items)) {
                    if (depth + 1 < limits.depth) { out.items.push(adopt(it, depth + 1)); }
                    return;
                }
                var f = byKey[it.field];
                if (!f || f.ops.indexOf(it.op) === -1) { return; }
                var v = it.value === null || it.value === undefined ? '' : String(it.value);
                out.items.push({field: f.key, op: it.op, value: v});
            });
            return out;
        }

        function valueWidget(item, f) {
            var k = kind(f, item.op);
            var label = f.label + ' value';
            var onInput = function (e) { item.value = e.target.value; changed(); };
            if (k === 'none') {
                return el('input', {type: 'text', cls: 'fb-value', disabled: true, placeholder: 'No value required',
                                    'aria-label': label});
            }
            if (k === 'choice') {
                var sel = el('select', {cls: 'fb-value', 'aria-label': label, on: {change: onInput}},
                             [el('option', {value: '', text: 'Pick a value'})]);
                ((cfg.options || {})[f.options] || []).forEach(function (o) {
                    var opt = el('option', {value: String(o.id), text: o.name + (o.active === false ? ' (inactive)' : '')});
                    if (String(o.id) === String(item.value)) { opt.selected = true; }
                    sel.appendChild(opt);
                });
                return sel;
            }
            if (k === 'date') {
                return el('input', {type: 'date', cls: 'fb-value', value: item.value || '', 'aria-label': label,
                                    on: {input: onInput, change: onInput}});
            }
            if (k === 'days' || k === 'number') {
                return el('input', {type: 'number', min: k === 'days' ? '0' : '1', max: k === 'days' ? String(limits.days) : null,
                                    step: '1', cls: 'fb-value', value: item.value || '', 'aria-label': label,
                                    placeholder: k === 'days' ? 'days' : 'Value', on: {input: onInput}});
            }
            return el('input', {type: 'text', cls: 'fb-value', value: item.value || '', maxlength: String(limits.value),
                                placeholder: 'Value', 'aria-label': label,
                                on: {input: onInput, keydown: function (e) {
                                    if (e.key === 'Enter' && cfg.onEnter) { e.preventDefault(); cfg.onEnter(); }
                                }}});
        }

        function leafRow(item, group) {
            var f = byKey[item.field] || fields[0];
            var fieldSel = el('select', {cls: 'fb-field', 'aria-label': 'Field', on: {change: function (e) {
                var nf = byKey[e.target.value];
                if (!nf) { return; }
                item.field = nf.key; item.op = nf.ops[0]; item.value = '';
                render(); changed();
            }}});
            fields.forEach(function (x) {
                var o = el('option', {value: x.key, text: x.label});
                if (x.key === f.key) { o.selected = true; }
                fieldSel.appendChild(o);
            });
            var opSel = el('select', {cls: 'fb-op', 'aria-label': 'Operator', on: {change: function (e) {
                var before = kind(f, item.op);
                if (f.ops.indexOf(e.target.value) === -1) { return; }
                item.op = e.target.value;
                if (kind(f, item.op) !== before) { item.value = ''; }
                render(); changed();
            }}});
            f.ops.forEach(function (op) {
                var o = el('option', {value: op, text: (cfg.operators || {})[op] || op});
                if (op === item.op) { o.selected = true; }
                opSel.appendChild(o);
            });
            var rm = el('button', {type: 'button', cls: 'fb-icon fb-remove', 'aria-label': 'Remove condition',
                                   title: 'Remove condition', text: '×', on: {click: function () {
                group.items.splice(group.items.indexOf(item), 1);
                render(); changed();
            }}});
            return el('div', {cls: 'fb-leaf'}, [fieldSel, opSel, valueWidget(item, f), rm]);
        }

        function groupBox(g, depth, parent) {
            var full = leafCount(tree) >= limits.conditions;
            var logicBtn = function (logic, text) {
                return el('button', {type: 'button', cls: 'fb-logic' + (g.logic === logic ? ' fb-logic--on' : ''),
                                     'aria-pressed': g.logic === logic ? 'true' : 'false', text: text,
                                     on: {click: function () { if (g.logic !== logic) { g.logic = logic; render(); changed(); } }}});
            };
            var n = g.items.length;
            var head = el('div', {cls: 'fb-head'}, [
                el('span', {cls: 'fb-match', text: depth === 0 ? 'Match' : 'Sub-group'}),
                el('span', {cls: 'fb-logicset', role: 'group', 'aria-label': 'Match all or any'},
                   [logicBtn('and', 'All (AND)'), logicBtn('or', 'Any (OR)')]),
                el('span', {cls: 'fb-count', text: n + (n === 1 ? ' item' : ' items')}),
                parent ? el('button', {type: 'button', cls: 'fb-icon fb-remove-group', 'aria-label': 'Remove sub-group',
                                       title: 'Remove sub-group', text: '×', on: {click: function () {
                    parent.items.splice(parent.items.indexOf(g), 1);
                    render(); changed();
                }}}) : null
            ]);
            var list = el('div', {cls: 'fb-items'});
            g.items.forEach(function (it) {
                list.appendChild(it.items ? groupBox(it, depth + 1, g) : leafRow(it, g));
            });
            var foot = el('div', {cls: 'fb-foot'}, [
                el('button', {type: 'button', cls: 'fb-add', disabled: full, text: '+ Add condition',
                              on: {click: function () {
                    var f0 = fields[0];
                    g.items.push({field: f0.key, op: f0.ops[0], value: ''});
                    render(); changed();
                    var rows = root.querySelectorAll('.fb-leaf .fb-value');
                    if (rows.length) { var last = rows[rows.length - 1]; if (!last.disabled) { last.focus(); } }
                }}}),
                depth + 1 < limits.depth ? el('button', {type: 'button', cls: 'fb-add fb-add-group', disabled: full,
                                                         title: 'Wrap upcoming conditions in their own AND/OR group',
                                                         text: 'Add sub-group', on: {click: function () {
                    var f0 = fields[0];
                    g.items.push({logic: 'and', items: [{field: f0.key, op: f0.ops[0], value: ''}]});
                    render(); changed();
                }}}) : null
            ]);
            return el('div', {cls: 'fb-group fb-depth-' + Math.min(depth, 2)}, [head, list, foot]);
        }

        function render() {
            root.textContent = '';
            root.appendChild(groupBox(tree, 0, null));
        }

        render();
        return {
            set: function (t) { tree = adopt(t || blank(), 0); render(); },
            get: function () { return prune(tree); },
            count: function () { return leafCount(tree); },
            complete: function () { return leafCount(prune(tree)); },
            clear: function () { tree = blank(); render(); }
        };
    }

    window.IrisFilterBuilder = {create: create};
})();

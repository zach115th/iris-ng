/* IrisDashEditor - the custom dashboards' editor (iris-ng, 2026-11-09).
 *
 *   IrisDashEditor.mount(root, state, key)   state = {dashboard, schema: {vocab, options, me}, presets} (null: fetched);
 *                                            key = the dashboard's key, or null for a new one
 *
 * Visual mode edits the dashboard (name, description, sharing, default range, filter bar, sections, widgets) and
 * JSON mode the same object as text. The server validates everything (POST /validate, /preview, the save) and the
 * editor adopts its normalised copy; nothing here decides what is valid. Needs IrisDashboards, IrisDashWidgets and
 * IrisFilterBuilder.
 */
(function () {
    'use strict';

    var D = window.IrisDashboards;
    var el = D.el, icon = D.icon, api = D.api;

    function copy(o) { return JSON.parse(JSON.stringify(o)); }
    function rid(prefix) { return prefix + Math.random().toString(36).slice(2, 12); }
    function pad(n) { return (n < 10 ? '0' : '') + n; }

    function mount(root, state, key) {
        var E = {key: D.keyOf(key), vocab: null, options: {}, presets: [], model: null, dirty: false, mode: 'visual',
                 pseq: 0, ptimer: null, vtimer: null, ace: null, drag: null, previewOpen: true, saving: false};

        // -------------------------------------------------------------- vocabulary helpers

        function src(k) { return (E.vocab.sources || []).filter(function (s) { return s.key === k; })[0]; }
        function fld(s, k) { return ((src(s) || {}).fields || []).filter(function (f) { return f.key === k; })[0]; }
        function label(list, k) {
            var hit = (list || []).filter(function (x) { return x.key === k; })[0];
            return hit ? hit.label : k;
        }
        function optionsWithMe() {
            var out = {};
            Object.keys(E.options).forEach(function (k) { out[k] = E.options[k]; });
            out.users = [{id: E.vocab.me, name: 'Me (whoever views the dashboard)'}].concat(E.options.users || []);
            return out;
        }
        function builderFields(s) {
            return (src(s).fields || []).map(function (f) {
                return {key: f.key, label: f.label, type: f.type, options: f.options, ops: f.ops};
            });
        }

        function markDirty() {
            E.dirty = true;
            var st = root.querySelector('#de-state');
            if (st) { st.textContent = 'Unsaved changes'; }
            schedulePreview();
        }

        function toast(text, kind) { D.toast(root, text, kind); }

        // -------------------------------------------------------------- the page frame

        function frame() {
            root.textContent = '';
            var isNew = !E.key;
            var back = el('a', {cls: 'dash-back', id: 'de-back', href: D.pageUrl(isNew ? '/dashboards' : '/dashboards/' + E.key)},
                          [icon('back', 'dash-i dash-i--xs'), isNew ? 'All dashboards' : 'Back to dashboard']);
            var modes = el('div', {cls: 'de-modes', role: 'group', 'aria-label': 'Editor mode'}, [
                el('button', {type: 'button', cls: 'de-mode', 'data-mode': 'visual', 'aria-pressed': 'true', text: 'Visual',
                              on: {click: function () { setMode('visual'); }}}),
                el('button', {type: 'button', cls: 'de-mode', 'data-mode': 'json', 'aria-pressed': 'false', text: 'JSON',
                              on: {click: function () { setMode('json'); }}})
            ]);
            root.appendChild(el('div', {cls: 'dash-head'}, [
                el('div', {cls: 'dash-head-text'}, [back,
                    el('h1', {cls: 'dash-title', id: 'de-title', text: isNew ? 'New dashboard' : 'Edit dashboard'}),
                    el('p', {cls: 'dash-dim', id: 'de-state', 'aria-live': 'polite', text: isNew ? 'Not saved yet' : ''})]),
                el('div', {cls: 'dash-actions'}, [modes,
                    el('button', {type: 'button', cls: 'dash-btn', id: 'de-preview-btn', on: {click: function () {
                        E.previewOpen = true;
                        drawPreviewFrame();
                        renderPreview();
                        var p = root.querySelector('#de-preview');
                        if (p && p.scrollIntoView) { p.scrollIntoView({block: 'start'}); }
                    }}}, ['Preview']),
                    el('button', {type: 'button', cls: 'dash-btn dash-btn--primary', id: 'de-save', on: {click: save}},
                       ['Save'])])
            ]));
            root.appendChild(el('div', {cls: 'dash-alert', id: 'de-issues', role: 'alert', hidden: true}));
            root.appendChild(el('div', {id: 'de-visual'}));
            root.appendChild(el('div', {id: 'de-json', hidden: true}));
            root.appendChild(el('section', {cls: 'dash-card de-preview', id: 'de-preview', 'aria-label': 'Live preview'}));
            root.appendChild(el('dialog', {cls: 'dash-dialog de-dialog', id: 'de-widget-dialog', 'aria-labelledby': 'de-wd-title'}));
            root.appendChild(el('dialog', {cls: 'dash-dialog de-dialog', id: 'de-preset-dialog', 'aria-labelledby': 'de-pd-title'}));
            root.appendChild(el('dialog', {cls: 'dash-dialog', id: 'de-confirm', 'aria-labelledby': 'de-cf-title'}));
            root.appendChild(el('dialog', {cls: 'dash-dialog dash-dialog--json'}));
            root.appendChild(el('div', {cls: 'dash-toast', role: 'status', hidden: true}));
            drawVisual();
            drawPreviewFrame();
        }

        // -------------------------------------------------------------- the dashboard card + sections

        function drawVisual() {
            var box = root.querySelector('#de-visual');
            box.textContent = '';
            box.appendChild(metaCard());
            var secs = el('div', {id: 'de-sections'});
            box.appendChild(secs);
            drawSectionsEditor();
            box.appendChild(el('button', {type: 'button', cls: 'de-add-section', id: 'de-add-section', on: {click: function () {
                var defn = E.model.definition;
                if (defn.sections.length >= E.vocab.limits.sections) { toast('A dashboard holds at most ' + E.vocab.limits.sections + ' sections.', 'err'); return; }
                defn.sections.push({id: rid('s'), title: 'New section', description: '', widgets: []});
                drawSectionsEditor();
                markDirty();
            }}}, [icon('plus'), 'Add section']));
        }

        function metaCard() {
            var m = E.model;
            var name = el('input', {type: 'text', id: 'de-name', cls: 'dash-input', maxlength: String(E.vocab.limits.name),
                                    value: m.name, on: {input: function (e) { m.name = e.target.value; markDirty(); }}});
            var desc = el('input', {type: 'text', id: 'de-desc', cls: 'dash-input', maxlength: String(E.vocab.limits.description),
                                    value: m.description || '', on: {input: function (e) { m.description = e.target.value; markDirty(); }}});
            var shared = el('input', {type: 'checkbox', id: 'de-shared', on: {change: function (e) { m.is_shared = !!e.target.checked; markDirty(); }}});
            shared.checked = !!m.is_shared;
            var range = el('select', {id: 'de-range', cls: 'dash-input', on: {change: function (e) {
                var keys = E.vocab.ranges.map(function (r) { return r.key; });
                var i = keys.indexOf(e.target.value);
                if (i !== -1) { m.definition.default_range = keys[i]; markDirty(); }
            }}});
            E.vocab.ranges.forEach(function (r) {
                var o = el('option', {value: r.key, text: r.label});
                if (r.key === m.definition.default_range) { o.selected = true; }
                range.appendChild(o);
            });
            var bar = el('div', {cls: 'de-bar', id: 'de-bar'});
            drawBar(bar);
            return el('section', {cls: 'dash-card de-meta', 'aria-labelledby': 'de-meta-title'}, [
                el('h2', {cls: 'de-card-title', id: 'de-meta-title', text: 'Dashboard'}),
                el('p', {cls: 'dash-dim', text: 'Name, description, sharing, the range it opens with and the filter bar.'}),
                el('div', {cls: 'de-meta-grid'}, [
                    el('label', {cls: 'dash-field', 'for': 'de-name'}, [el('span', {cls: 'dash-label', text: 'Name'}), name]),
                    el('label', {cls: 'dash-field', 'for': 'de-desc'}, [el('span', {cls: 'dash-label', text: 'Description'}), desc]),
                    el('label', {cls: 'dash-field', 'for': 'de-range'}, [el('span', {cls: 'dash-label', text: 'Opens on'}), range])
                ]),
                el('div', {cls: 'de-check-row'}, [el('label', {cls: 'de-check', 'for': 'de-shared'}, [shared, ' Share with other users']),
                                                  (window.IrisHelp ? window.IrisHelp.el('custom_dashboards.sharing', {cls: 'ml-1'}) : null)]),
                bar,
                E.key ? el('div', {cls: 'de-meta-foot'}, [el('button', {type: 'button', cls: 'dash-btn dash-btn--danger-ghost', id: 'de-delete',
                                                                        on: {click: confirmDelete}}, ['Delete dashboard'])]) : null
            ]);
        }

        function drawBar(box) {
            box.textContent = '';
            var defn = E.model.definition;
            var used = defn.filter_bar.map(function (e) { return e.key; });
            var free = E.vocab.filter_bar.filter(function (f) { return used.indexOf(f.key) === -1; });
            var add = el('select', {cls: 'dash-input dash-input--sm', id: 'de-bar-add', 'aria-label': 'Filter to add'});
            free.forEach(function (f) { add.appendChild(el('option', {value: f.key, text: f.label})); });
            var addBtn = el('button', {type: 'button', cls: 'dash-btn dash-btn--sm', id: 'de-bar-add-btn',
                                       disabled: !free.length || defn.filter_bar.length >= E.vocab.limits.filter_bar,
                                       on: {click: function () {
                var keys = free.map(function (f) { return f.key; });
                var i = keys.indexOf(add.value);
                if (i === -1) { return; }
                defn.filter_bar.push({key: keys[i], label: free[i].label});
                drawBar(box);
                markDirty();
            }}}, [icon('plus'), 'Add filter']);
            box.appendChild(el('div', {cls: 'de-bar-head'}, [el('span', {cls: 'dash-label', text: 'Filter bar'}),
                                                             (window.IrisHelp ? window.IrisHelp.el('custom_dashboards.filter_bar', {cls: 'ml-1'}) : null),
                                                             el('span', {cls: 'dash-spacer'}), free.length ? add : null, addBtn]));
            if (!defn.filter_bar.length) {
                box.appendChild(el('p', {cls: 'dash-dim', text: 'No filter-bar entries: the dashboard offers its date range only.'}));
            }
            defn.filter_bar.forEach(function (e, i) {
                var meta = E.vocab.filter_bar.filter(function (f) { return f.key === e.key; })[0] || {sources: []};
                var lab = el('input', {type: 'text', cls: 'dash-input dash-input--sm', maxlength: '60', value: e.label,
                                       'aria-label': 'Label of the ' + e.key + ' filter',
                                       on: {input: function (ev) { e.label = ev.target.value; markDirty(); }}});
                box.appendChild(el('div', {cls: 'de-bar-row', 'data-bar': e.key}, [
                    el('span', {cls: 'de-chip', text: label(E.vocab.filter_bar, e.key)}), lab,
                    el('span', {cls: 'dash-dim', text: 'applies to ' + meta.sources.map(function (s) { return label(E.vocab.sources, s); }).join(', ')}),
                    el('span', {cls: 'dash-spacer'}),
                    el('button', {type: 'button', cls: 'de-icon', 'aria-label': 'Remove the ' + e.key + ' filter', text: '×',
                                  on: {click: function () { defn.filter_bar.splice(i, 1); drawBar(box); markDirty(); }}})
                ]));
            });
        }

        function widgetChips(w) {
            var s = src(w.source) || {label: w.source};
            var m = label(E.vocab.measures, w.measure.type);
            if (w.measure.field) { m += ' of ' + ((fld(w.source, w.measure.field) || {}).label || w.measure.field); }
            var chips = [label(E.vocab.charts, w.chart), s.label + ' · ' + m];
            if (w.group_by) { chips.push('by ' + ((fld(w.source, w.group_by) || {}).label || w.group_by)); }
            if (w.split_by) { chips.push('split by ' + ((fld(w.source, w.split_by) || {}).label || w.split_by)); }
            if ((w.filter || {}).items && w.filter.items.length) { chips.push('filtered'); }
            if (w.range === 'all') { chips.push('all time'); }
            return el('div', {cls: 'de-chips'}, chips.map(function (c) { return el('span', {cls: 'de-chip', text: c}); }));
        }

        function moveWidget(fs, fw, ts, tw) {
            var secs = E.model.definition.sections;
            var w = secs[fs].widgets.splice(fw, 1)[0];
            if (fs === ts && tw > fw) { tw -= 1; }
            secs[ts].widgets.splice(Math.max(0, Math.min(tw, secs[ts].widgets.length)), 0, w);
            drawSectionsEditor();
            markDirty();
        }

        function totalWidgets() {
            return E.model.definition.sections.reduce(function (n, s) { return n + s.widgets.length; }, 0);
        }

        function widgetCard(si, wi, w) {
            var name = w.name;
            var width = el('select', {cls: 'dash-input dash-input--xs de-w-width', 'aria-label': 'Width of ' + name,
                                      on: {change: function (e) {
                var keys = E.vocab.widths.map(function (x) { return x.key; });
                var i = keys.indexOf(e.target.value);
                if (i !== -1) { w.width = keys[i]; drawSectionsEditor(); markDirty(); }
            }}});
            E.vocab.widths.forEach(function (x) {
                var o = el('option', {value: x.key, text: x.key});
                if (x.key === w.width) { o.selected = true; }
                width.appendChild(o);
            });
            var btn = function (cls, aria, content, fn) {
                return el('button', {type: 'button', cls: 'de-icon ' + cls, 'aria-label': aria, title: aria, on: {click: fn}},
                          typeof content === 'string' ? [content] : [content]);
            };
            var card = el('div', {cls: 'de-w dash-w--' + w.width, draggable: 'true', 'data-si': String(si), 'data-wi': String(wi),
                                  'data-wid': w.id}, [
                el('div', {cls: 'de-w-head'}, [
                    el('span', {cls: 'de-grip', 'aria-hidden': 'true', title: 'Drag to reorder', text: '⠇'}),
                    el('span', {cls: 'de-w-name', title: name, text: name})]),
                el('div', {cls: 'de-w-tools'}, [
                    width,
                    btn('de-w-edit', 'Edit widget ' + name, icon('pen', 'dash-i dash-i--xs'), function () { openWidget(si, wi); }),
                    btn('de-w-dup', 'Duplicate widget ' + name, icon('copy', 'dash-i dash-i--xs'), function () {
                        if (totalWidgets() >= E.vocab.limits.widgets) { toast('A dashboard holds at most ' + E.vocab.limits.widgets + ' widgets.', 'err'); return; }
                        var c = copy(w);
                        c.id = rid('w');
                        c.name = (w.name + ' (copy)').slice(0, E.vocab.limits.widget_name);
                        E.model.definition.sections[si].widgets.splice(wi + 1, 0, c);
                        drawSectionsEditor();
                        markDirty();
                    }),
                    btn('de-w-left', 'Move ' + name + ' earlier', '‹', function () {
                        if (wi > 0) { moveWidget(si, wi, si, wi - 1); }
                        else if (si > 0) { moveWidget(si, wi, si - 1, E.model.definition.sections[si - 1].widgets.length); }
                    }),
                    btn('de-w-right', 'Move ' + name + ' later', '›', function () {
                        var secs = E.model.definition.sections;
                        if (wi < secs[si].widgets.length - 1) { moveWidget(si, wi, si, wi + 2); }
                        else if (si < secs.length - 1) { moveWidget(si, wi, si + 1, 0); }
                    }),
                    btn('de-w-remove', 'Remove widget ' + name, '×', function () {
                        E.model.definition.sections[si].widgets.splice(wi, 1);
                        drawSectionsEditor();
                        markDirty();
                    })
                ]),
                widgetChips(w)
            ]);
            card.addEventListener('dragstart', function (e) {
                E.drag = {si: si, wi: wi};
                card.classList.add('de-w--dragging');
                if (e.dataTransfer) { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', si + ':' + wi); }
            });
            card.addEventListener('dragend', function () { E.drag = null; card.classList.remove('de-w--dragging'); clearDrop(); });
            card.addEventListener('dragover', function (e) {
                if (!E.drag) { return; }
                e.preventDefault();
                e.stopPropagation();
                var r = card.getBoundingClientRect();
                var after = (e.clientX - r.left) > r.width / 2;
                clearDrop();
                card.classList.add(after ? 'de-drop-after' : 'de-drop-before');
            });
            card.addEventListener('drop', function (e) {
                if (!E.drag) { return; }
                e.preventDefault();
                e.stopPropagation();
                var r = card.getBoundingClientRect();
                var after = (e.clientX - r.left) > r.width / 2;
                var from = E.drag;
                E.drag = null;
                clearDrop();
                moveWidget(from.si, from.wi, si, wi + (after ? 1 : 0));
            });
            return card;
        }

        function clearDrop() {
            Array.prototype.forEach.call(root.querySelectorAll('.de-drop-before, .de-drop-after, .de-grid--over'), function (n) {
                n.classList.remove('de-drop-before', 'de-drop-after', 'de-grid--over');
            });
        }

        function drawSectionsEditor() {
            var box = root.querySelector('#de-sections');
            if (!box) { return; }
            box.textContent = '';
            var secs = E.model.definition.sections;
            secs.forEach(function (s, si) {
                var grid = el('div', {cls: 'de-grid', 'data-si': String(si)});
                s.widgets.forEach(function (w, wi) { grid.appendChild(widgetCard(si, wi, w)); });
                if (!s.widgets.length) {
                    grid.appendChild(el('div', {cls: 'de-drop-zone', text: 'Drop a widget here, or add one.'}));
                }
                grid.addEventListener('dragover', function (e) {
                    if (!E.drag) { return; }
                    e.preventDefault();
                    clearDrop();
                    grid.classList.add('de-grid--over');
                });
                grid.addEventListener('drop', function (e) {
                    if (!E.drag) { return; }
                    e.preventDefault();
                    var from = E.drag;
                    E.drag = null;
                    clearDrop();
                    moveWidget(from.si, from.wi, si, secs[si].widgets.length);
                });
                var title = el('input', {type: 'text', cls: 'dash-input de-sec-title', maxlength: String(E.vocab.limits.section_title),
                                         value: s.title, 'aria-label': 'Title of section ' + (si + 1), placeholder: 'Section title',
                                         on: {input: function (e) { s.title = e.target.value; markDirty(); }}});
                var desc = el('input', {type: 'text', cls: 'dash-input dash-input--sm de-sec-desc', maxlength: String(E.vocab.limits.description),
                                        value: s.description || '', 'aria-label': 'Description of section ' + (si + 1),
                                        placeholder: 'Description (optional)',
                                        on: {input: function (e) { s.description = e.target.value; markDirty(); }}});
                var tools = el('div', {cls: 'de-sec-tools'}, [
                    el('button', {type: 'button', cls: 'dash-btn dash-btn--sm de-add-widget', on: {click: function () { openWidget(si, null); }}},
                       [icon('plus'), 'Widget']),
                    el('button', {type: 'button', cls: 'dash-btn dash-btn--sm de-add-preset', on: {click: function () { openPresets(si); }}},
                       [icon('sparkle'), 'Preset']),
                    el('button', {type: 'button', cls: 'de-icon', 'aria-label': 'Move section ' + (si + 1) + ' up', text: '↑',
                                  disabled: si === 0, on: {click: function () {
                        secs.splice(si - 1, 0, secs.splice(si, 1)[0]); drawSectionsEditor(); markDirty();
                    }}}),
                    el('button', {type: 'button', cls: 'de-icon', 'aria-label': 'Move section ' + (si + 1) + ' down', text: '↓',
                                  disabled: si === secs.length - 1, on: {click: function () {
                        secs.splice(si + 1, 0, secs.splice(si, 1)[0]); drawSectionsEditor(); markDirty();
                    }}}),
                    el('button', {type: 'button', cls: 'de-icon de-sec-remove', 'aria-label': 'Remove section ' + (si + 1), text: '×',
                                  on: {click: function () {
                        var go = function () { secs.splice(si, 1); drawSectionsEditor(); markDirty(); };
                        if (s.widgets.length) {
                            confirmBox('Remove this section?', 'Its ' + s.widgets.length + ' widget' + (s.widgets.length === 1 ? '' : 's') +
                                       ' go with it (until you save, Back discards the change).', 'Remove section', go);
                        } else { go(); }
                    }}})
                ]);
                box.appendChild(el('section', {cls: 'dash-card de-section', 'data-sid': s.id, 'aria-label': 'Section ' + (si + 1)}, [
                    el('div', {cls: 'de-sec-head'}, [el('div', {cls: 'de-sec-text'}, [title, desc]), tools]),
                    grid
                ]));
            });
            if (!secs.length) {
                box.appendChild(el('p', {cls: 'dash-dim', text: 'No sections yet: Add section starts one.'}));
            }
        }

        // -------------------------------------------------------------- the widget dialog

        function defaultWidget() {
            return {id: rid('w'), name: 'New widget', source: 'alerts', measure: {type: 'count', field: null, filter: null},
                    group_by: null, bucket: null, split_by: null, filter: {logic: 'and', items: []}, range: 'dashboard',
                    chart: 'number', width: 'quarter', order: null, limit: null, columns: null, sort: null, options: {}};
        }

        function firstOf(list) { return list.length ? list[0] : null; }

        function normaliseLocal(W) {
            /* Keep the working copy coherent while it is edited; the server has the last word on save. */
            var s = src(W.source);
            var fields = s.fields;
            var keys = fields.map(function (f) { return f.key; });
            var mt = W.measure.type;
            if (E.vocab.number_measures.indexOf(mt) !== -1) {
                var nums = fields.filter(function (f) { return f.kind === 'number'; }).map(function (f) { return f.key; });
                if (nums.indexOf(W.measure.field) === -1) { W.measure.field = firstOf(nums); }
            } else if (mt === 'distinct') {
                var ds = fields.filter(function (f) { return ['choice', 'text', 'bool'].indexOf(f.kind) !== -1; }).map(function (f) { return f.key; });
                if (ds.indexOf(W.measure.field) === -1) { W.measure.field = firstOf(ds); }
            } else {
                W.measure.field = null;
            }
            if (mt !== 'share') { W.measure.filter = null; }
            else if (!W.measure.filter) { W.measure.filter = {logic: 'and', items: []}; }
            if (mt === 'rows') {
                W.chart = 'table';
                W.group_by = W.split_by = W.bucket = null;
                W.columns = (W.columns || []).filter(function (c) { return keys.indexOf(c) !== -1; });
                if (W.columns.indexOf(s.title_field) === -1) { W.columns.unshift(s.title_field); }
                if (!W.sort || keys.indexOf(W.sort.field) === -1) { W.sort = {field: s.date_field, dir: 'desc'}; }
                if (!W.limit || W.limit > E.vocab.limits.rows) { W.limit = 10; }
            } else {
                W.columns = null;
                W.sort = null;
                if (W.chart === 'number') { W.group_by = W.split_by = W.bucket = null; }
            }
            if (W.group_by && (!fld(W.source, W.group_by) || !fld(W.source, W.group_by).group)) { W.group_by = null; }
            var g = W.group_by ? fld(W.source, W.group_by) : null;
            W.bucket = g && g.kind === 'date' ? (W.bucket || 'auto') : null;
            if (W.split_by) {
                var sp = fld(W.source, W.split_by);
                if (!sp || !sp.group || sp.kind === 'date' || W.split_by === W.group_by ||
                        E.vocab.split_charts.indexOf(W.chart) === -1 || !W.group_by) { W.split_by = null; }
            }
            if (W.group_by && !W.bucket && mt !== 'rows') {
                W.order = W.order || 'value_desc';
                W.limit = W.limit && W.limit <= E.vocab.limits.groups ? W.limit : E.vocab.limits.default_groups;
            } else if (mt !== 'rows') {
                W.order = null;
                W.limit = null;
            }
            W.options = W.options || {};
            if (!(g && (g.kind === 'tags' || g.kind === 'csv'))) { delete W.options.match; delete W.options.exclude; }
            W.filter = W.filter || {logic: 'and', items: []};
            return W;
        }

        function selectOf(id, items, current, onChange, aria) {
            var s = el('select', {id: id, cls: 'dash-input', 'aria-label': aria || null, on: {change: function (e) {
                var keys = items.map(function (x) { return x.key; });
                var i = keys.indexOf(e.target.value);
                onChange(i === -1 ? null : keys[i]);
            }}});
            items.forEach(function (x) {
                var o = el('option', {value: x.key === null ? '' : x.key, text: x.label});
                if (x.key === current || (x.key === null && (current === null || current === undefined))) { o.selected = true; }
                s.appendChild(o);
            });
            return s;
        }

        function field(labelText, control, id, extra) {
            return el('div', {cls: 'dash-field'}, [el('div', {cls: 'de-label-row'}, [el('label', {cls: 'dash-label', 'for': id, text: labelText}),
                                                                                    extra || null]), control]);
        }

        function openWidget(si, wi) {
            var editing = wi !== null && wi !== undefined;
            if (!editing && totalWidgets() >= E.vocab.limits.widgets) {
                toast('A dashboard holds at most ' + E.vocab.limits.widgets + ' widgets.', 'err');
                return;
            }
            var W = normaliseLocal(editing ? copy(E.model.definition.sections[si].widgets[wi]) : defaultWidget());
            var dlg = root.querySelector('#de-widget-dialog');
            var tab = 'data';
            var fb = null, sfb = null;

            function grab() {
                if (fb) { W.filter = fb.get(); }
                if (sfb) { W.measure.filter = sfb.get(); }
            }

            function redraw() {
                grab();
                normaliseLocal(W);
                draw();
            }

            function tabButton(k, text) {
                return el('button', {type: 'button', role: 'tab', id: 'de-tab-' + k, cls: 'de-tab' + (tab === k ? ' de-tab--on' : ''),
                                     'aria-selected': tab === k ? 'true' : 'false', 'aria-controls': 'de-tabpanel',
                                     tabindex: tab === k ? '0' : '-1', text: text,
                                     on: {click: function () { grab(); tab = k; draw(); }}});
            }

            function dataTab() {
                var s = src(W.source);
                var mt = W.measure.type;
                var out = el('div', {cls: 'de-form'});
                out.appendChild(field('Source', selectOf('dw-source', E.vocab.sources.map(function (x) { return {key: x.key, label: x.label}; }),
                    W.source, function (v) {
                        if (!v || v === W.source) { return; }
                        W.source = v;
                        W.filter = {logic: 'and', items: []};
                        W.measure.filter = W.measure.type === 'share' ? {logic: 'and', items: []} : null;
                        W.group_by = W.split_by = null;
                        W.columns = [];
                        W.sort = null;
                        fb = sfb = null;
                        normaliseLocal(W);
                        draw();
                    }), 'dw-source', (window.IrisHelp ? window.IrisHelp.el('custom_dashboards.source', {cls: 'ml-1'}) : null)));
                out.appendChild(field('Measure', selectOf('dw-measure', E.vocab.measures, mt, function (v) {
                    if (!v) { return; }
                    if (W.measure.type === 'rows' && v !== 'rows') { W.chart = 'number'; }
                    W.measure.type = v;
                    redraw();
                }), 'dw-measure', (window.IrisHelp ? window.IrisHelp.el('custom_dashboards.measure', {cls: 'ml-1'}) : null)));
                if (E.vocab.number_measures.indexOf(mt) !== -1 || mt === 'distinct') {
                    var choices = s.fields.filter(function (f) {
                        return mt === 'distinct' ? ['choice', 'text', 'bool'].indexOf(f.kind) !== -1 : f.kind === 'number';
                    }).map(function (f) { return {key: f.key, label: f.label}; });
                    out.appendChild(field('Of the field', choices.length ? selectOf('dw-mfield', choices, W.measure.field, function (v) { W.measure.field = v; })
                                                                         : el('p', {cls: 'dash-dim', id: 'dw-mfield', text: s.label + ' have no number field.'}), 'dw-mfield'));
                }
                if (mt === 'share') {
                    var sbox = el('div', {cls: 'de-fb', id: 'dw-share'});
                    out.appendChild(el('div', {cls: 'dash-field'}, [el('span', {cls: 'dash-label', text: 'Counts as matching'}),
                        el('p', {cls: 'dash-dim', text: 'The figure is the share (%) of the widget\'s rows that match this filter.'}), sbox]));
                    sfb = window.IrisFilterBuilder.create(sbox, builderCfg());
                    sfb.set(W.measure.filter);
                }
                if (mt === 'rows') {
                    var cols = el('div', {cls: 'de-cols', role: 'group', 'aria-label': 'Columns'});
                    s.fields.forEach(function (f) {
                        var cb = el('input', {type: 'checkbox', id: 'dw-col-' + f.key, 'data-col': f.key,
                                              disabled: f.key === s.title_field, on: {change: function (e) {
                            var cur = W.columns || [];
                            if (e.target.checked) {
                                if (cur.length >= E.vocab.limits.columns) { e.target.checked = false; toast('A table shows at most ' + E.vocab.limits.columns + ' columns.', 'err'); return; }
                                if (cur.indexOf(f.key) === -1) { cur.push(f.key); }
                            } else {
                                W.columns = cur.filter(function (c) { return c !== f.key; });
                                return;
                            }
                            W.columns = cur;
                        }}});
                        cb.checked = (W.columns || []).indexOf(f.key) !== -1;
                        cols.appendChild(el('label', {cls: 'de-check', 'for': 'dw-col-' + f.key}, [cb, ' ' + f.label]));
                    });
                    out.appendChild(el('div', {cls: 'dash-field'}, [el('span', {cls: 'dash-label', text: 'Columns'}), cols]));
                    var sortable = s.fields.filter(function (f) { return !f.many; }).map(function (f) { return {key: f.key, label: f.label}; });
                    out.appendChild(el('div', {cls: 'de-row3'}, [
                        field('Sort by', selectOf('dw-sort', sortable, W.sort.field, function (v) { if (v) { W.sort.field = v; } }), 'dw-sort'),
                        field('Direction', selectOf('dw-dir', [{key: 'desc', label: 'Descending'}, {key: 'asc', label: 'Ascending'}],
                                                    W.sort.dir, function (v) { if (v) { W.sort.dir = v; } }), 'dw-dir'),
                        field('Rows', el('input', {type: 'number', id: 'dw-rows', cls: 'dash-input', min: '1', max: String(E.vocab.limits.rows),
                                                   value: String(W.limit), on: {input: function (e) {
                            var n = parseInt(e.target.value, 10);
                            if (!isNaN(n)) { W.limit = n; }
                        }}}), 'dw-rows')
                    ]));
                } else if (W.chart !== 'number') {
                    var groupable = s.fields.filter(function (f) { return f.group; }).map(function (f) { return {key: f.key, label: f.label}; });
                    out.appendChild(field('Group by', selectOf('dw-group', [{key: null, label: '(choose a field)'}].concat(groupable), W.group_by,
                                                               function (v) { W.group_by = v; redraw(); }), 'dw-group',
                                          (window.IrisHelp ? window.IrisHelp.el('custom_dashboards.group_by', {cls: 'ml-1'}) : null)));
                    var g = W.group_by ? fld(W.source, W.group_by) : null;
                    if (g && g.kind === 'date') {
                        out.appendChild(field('Time bucket', selectOf('dw-bucket', E.vocab.time_buckets.map(function (b) {
                            return {key: b, label: b === 'auto' ? 'Automatic (by the range)' : b};
                        }), W.bucket, function (v) { if (v) { W.bucket = v; } }), 'dw-bucket'));
                    }
                    if (W.group_by && E.vocab.split_charts.indexOf(W.chart) !== -1) {
                        var splits = s.fields.filter(function (f) { return f.group && f.kind !== 'date' && f.key !== W.group_by; })
                            .map(function (f) { return {key: f.key, label: f.label}; });
                        out.appendChild(field('Split into series by', selectOf('dw-split', [{key: null, label: '(no split)'}].concat(splits),
                                                                              W.split_by, function (v) { W.split_by = v; }), 'dw-split'));
                    }
                }
                var df = fld(W.source, s.date_field);
                out.appendChild(field('Range', selectOf('dw-range', [
                    {key: 'dashboard', label: 'The dashboard\'s range (' + (df ? df.label : s.date_field) + ')'},
                    {key: 'all', label: 'All time (ignores the range)'}], W.range, function (v) { if (v) { W.range = v; } }), 'dw-range'));
                return out;
            }

            function builderCfg() {
                return {fields: builderFields(W.source), operators: E.vocab.operators, noValueOps: E.vocab.no_value_ops,
                        dayOps: E.vocab.day_ops, options: optionsWithMe(), tokens: [E.vocab.me],
                        limits: {depth: E.vocab.limits.depth, conditions: E.vocab.limits.conditions,
                                 value: E.vocab.limits.value, days: E.vocab.limits.days}};
            }

            function filtersTab() {
                var box = el('div', {cls: 'de-fb', id: 'dw-filter'});
                fb = window.IrisFilterBuilder.create(box, builderCfg());
                fb.set(W.filter);
                return el('div', {cls: 'de-form'}, [
                    el('p', {cls: 'dash-dim', text: 'Only rows matching these conditions count. The dashboard\'s filter bar and range apply as well.'}),
                    box]);
            }

            function swatches(id, current, onPick, allowNone) {
                var box = el('div', {cls: 'de-swatches', role: 'radiogroup', id: id, 'aria-label': 'Colour'});
                var items = (allowNone ? [null] : []).concat(E.vocab.palette);
                items.forEach(function (c) {
                    var on = c === (current || null);
                    var b = el('button', {type: 'button', role: 'radio', 'aria-checked': on ? 'true' : 'false',
                                          cls: 'de-swatch' + (c ? '' : ' de-swatch--auto') + (on ? ' de-swatch--on' : ''),
                                          'aria-label': c ? 'Colour ' + c : 'Automatic colour', title: c || 'Automatic',
                                          on: {click: function () { onPick(c); }}});
                    if (c) { b.style.setProperty('background', E.vocab.palette[E.vocab.palette.indexOf(c)]); }
                    else { b.textContent = 'A'; }
                    box.appendChild(b);
                });
                return box;
            }

            function vizTab() {
                var out = el('div', {cls: 'de-form'});
                out.appendChild(field('Width', selectOf('dw-width', E.vocab.widths.map(function (x) { return {key: x.key, label: x.key}; }),
                                                        W.width, function (v) { if (v) { W.width = v; } }), 'dw-width'));
                out.appendChild(el('div', {cls: 'dash-field'}, [el('span', {cls: 'dash-label', text: 'Colour'}),
                    swatches('dw-color', W.options.color, function (c) {
                        if (c) { W.options.color = c; } else { delete W.options.color; }
                        draw();
                    }, true)]));
                var g = W.group_by ? fld(W.source, W.group_by) : null;
                if (g && !W.bucket && W.measure.type !== 'rows') {
                    var other = el('input', {type: 'checkbox', id: 'dw-other', on: {change: function (e) { W.options.other = !!e.target.checked; }}});
                    other.checked = W.options.other !== false;
                    var none = el('input', {type: 'checkbox', id: 'dw-hidenone', on: {change: function (e) {
                        if (e.target.checked) { W.options.hide_none = true; } else { delete W.options.hide_none; }
                    }}});
                    none.checked = !!W.options.hide_none;
                    out.appendChild(el('div', {cls: 'de-row3'}, [
                        field('Show at most', el('input', {type: 'number', id: 'dw-limit', cls: 'dash-input', min: '1', max: String(E.vocab.limits.groups),
                                                           value: String(W.limit), on: {input: function (e) {
                            var n = parseInt(e.target.value, 10);
                            if (!isNaN(n)) { W.limit = n; }
                        }}}), 'dw-limit'),
                        field('Order', selectOf('dw-order', [{key: 'value_desc', label: 'Largest first'}, {key: 'value_asc', label: 'Smallest first'},
                                                            {key: 'label_asc', label: 'A to Z'}, {key: 'label_desc', label: 'Z to A'}],
                                                W.order, function (v) { if (v) { W.order = v; } }), 'dw-order')
                    ]));
                    out.appendChild(el('div', {cls: 'de-check-row'}, [el('label', {cls: 'de-check', 'for': 'dw-other'}, [other, ' Sum the rest as "Other"']),
                                                                      el('label', {cls: 'de-check', 'for': 'dw-hidenone'}, [none, ' Leave out "(none)"'])]));
                }
                if (g && (g.kind === 'tags' || g.kind === 'csv')) {
                    out.appendChild(el('div', {cls: 'de-row3'}, [
                        field('Only tags containing', el('input', {type: 'text', id: 'dw-match', cls: 'dash-input', maxlength: String(E.vocab.limits.match_text),
                                                                   value: W.options.match || '', placeholder: 'e.g. sectors',
                                                                   on: {input: function (e) { if (e.target.value.trim()) { W.options.match = e.target.value; } else { delete W.options.match; } }}}), 'dw-match'),
                        field('Leave out tags containing', el('input', {type: 'text', id: 'dw-exclude', cls: 'dash-input', maxlength: String(E.vocab.limits.match_text),
                                                                        value: W.options.exclude || '', placeholder: 'e.g. tlp:',
                                                                        on: {input: function (e) { if (e.target.value.trim()) { W.options.exclude = e.target.value; } else { delete W.options.exclude; } }}}), 'dw-exclude')
                    ]));
                }
                if (W.chart === 'number') {
                    var list = el('div', {cls: 'de-thresholds', id: 'dw-thresholds'});
                    var ts = W.options.thresholds || [];
                    if (!ts.length) {
                        list.appendChild(el('p', {cls: 'dash-dim', text: 'No thresholds: the figure takes the widget\'s colour. A rule such as "≥ 100 → red" highlights an outlier.'}));
                    }
                    ts.forEach(function (t, i) {
                        list.appendChild(el('div', {cls: 'de-threshold'}, [
                            selectOf('dw-t-op-' + i, [{key: 'gte', label: '≥ at least'}, {key: 'lte', label: '≤ at most'}], t.op,
                                     function (v) { if (v) { t.op = v; } }, 'Threshold ' + (i + 1) + ' comparison'),
                            el('input', {type: 'number', cls: 'dash-input', step: 'any', value: String(t.value), 'aria-label': 'Threshold ' + (i + 1) + ' value',
                                         on: {input: function (e) { var n = parseFloat(e.target.value); if (!isNaN(n)) { t.value = n; } }}}),
                            swatches('dw-t-c-' + i, t.color, function (c) { t.color = c; draw(); }, false),
                            el('button', {type: 'button', cls: 'de-icon', 'aria-label': 'Remove threshold ' + (i + 1), text: '×',
                                          on: {click: function () { ts.splice(i, 1); draw(); }}})
                        ]));
                    });
                    out.appendChild(el('div', {cls: 'dash-field'}, [
                        el('div', {cls: 'de-bar-head'}, [el('span', {cls: 'dash-label', text: 'Thresholds'}), (window.IrisHelp ? window.IrisHelp.el('custom_dashboards.thresholds', {cls: 'ml-1'}) : null),
                            el('span', {cls: 'dash-spacer'}),
                            el('button', {type: 'button', cls: 'dash-btn dash-btn--sm', id: 'dw-t-add', disabled: ts.length >= E.vocab.limits.thresholds,
                                          on: {click: function () {
                                W.options.thresholds = ts;
                                ts.push({op: 'gte', value: 100, color: E.vocab.palette[3]});
                                draw();
                            }}}, [icon('plus'), 'Threshold'])]),
                        list]));
                }
                return out;
            }

            function advancedTab() {
                var ta = el('textarea', {id: 'dw-json', cls: 'dash-input de-json-ta', spellcheck: 'false', 'aria-label': 'The widget as JSON'});
                ta.value = JSON.stringify(W, null, 2);
                return el('div', {cls: 'de-form'}, [
                    el('p', {cls: 'dash-dim', text: 'The widget as JSON. Apply replaces the form with it, once the server has checked it.'}),
                    ta,
                    el('div', {}, [el('button', {type: 'button', cls: 'dash-btn dash-btn--sm', id: 'dw-json-apply', on: {click: function () {
                        var parsed;
                        try { parsed = JSON.parse(ta.value); } catch (e) { showErr(['Invalid JSON: ' + e.message]); return; }
                        checkWidget(parsed).then(function (clean) {
                            if (clean) { W = normaliseLocal(clean); fb = sfb = null; tab = 'data'; draw(); }
                        });
                    }}}, ['Apply JSON'])])
                ]);
            }

            function showErr(list) {
                var box = dlg.querySelector('.de-dlg-err');
                box.textContent = '';
                if (!list || !list.length) { box.hidden = true; return; }
                box.appendChild(el('ul', {}, list.map(function (t) {
                    return el('li', {text: String(t).replace(/^sections\[0\]\.widgets\[0\]: /, '')});
                })));
                box.hidden = false;
            }

            function checkWidget(w) {
                showErr(null);
                return api('POST', '/api/v2/custom-dashboards/validate', {
                    name: 'check', definition: {sections: [{id: 'check', title: '', widgets: [w]}]}
                }).then(function (res) {
                    if (!res.ok || !res.data) { showErr([D.errorText(res, 'The widget could not be checked.')]); return null; }
                    if (!res.data.valid) { showErr(res.data.issues); return null; }
                    var secs = res.data.dashboard.definition.sections;
                    return secs[0].widgets[0];
                });
            }

            function draw() {
                dlg.textContent = '';
                var chartSel = selectOf('dw-chart', W.measure.type === 'rows' ? [{key: 'table', label: 'Table'}] : E.vocab.charts,
                                        W.chart, function (v) {
                    if (!v) { return; }
                    W.chart = v;
                    if (v !== 'number' && W.measure.type !== 'rows' && !W.group_by) {
                        var s = src(W.source);
                        var df = fld(W.source, s.date_field);
                        W.group_by = v === 'line' && df ? s.date_field : (firstOf(s.fields.filter(function (f) { return f.group && f.kind === 'choice'; })) || {}).key || null;
                    }
                    redraw();
                });
                var name = el('input', {type: 'text', id: 'dw-name', cls: 'dash-input', maxlength: String(E.vocab.limits.widget_name),
                                        value: W.name, on: {input: function (e) { W.name = e.target.value; }}});
                var panel = el('div', {cls: 'de-tabpanel', id: 'de-tabpanel', role: 'tabpanel', 'aria-labelledby': 'de-tab-' + tab});
                fb = sfb = null;
                panel.appendChild(tab === 'data' ? dataTab() : tab === 'filters' ? filtersTab() : tab === 'viz' ? vizTab() : advancedTab());
                dlg.appendChild(el('div', {cls: 'de-dlg-head'}, [el('h2', {cls: 'dash-dlg-title', id: 'de-wd-title',
                                                                          text: editing ? 'Edit widget' : 'Add a widget'})]));
                dlg.appendChild(el('div', {cls: 'de-row2'}, [field('Name', name, 'dw-name'), field('Chart', chartSel, 'dw-chart')]));
                var tabs = el('div', {cls: 'de-tabs', role: 'tablist', 'aria-label': 'Widget settings'}, [
                    tabButton('data', 'Data'), tabButton('filters', 'Filters' + (W.filter.items.length ? ' (' + W.filter.items.length + ')' : '')),
                    tabButton('viz', 'Visualization'), tabButton('advanced', 'Advanced')]);
                tabs.addEventListener('keydown', function (e) {
                    var order = ['data', 'filters', 'viz', 'advanced'];
                    var i = order.indexOf(tab);
                    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                        e.preventDefault();
                        grab();
                        tab = order[(i + (e.key === 'ArrowRight' ? 1 : order.length - 1)) % order.length];
                        draw();
                        var t = dlg.querySelector('#de-tab-' + tab);
                        if (t) { t.focus(); }
                    }
                });
                dlg.appendChild(tabs);
                dlg.appendChild(panel);
                dlg.appendChild(el('div', {cls: 'de-dlg-err dash-alert', role: 'alert', hidden: true}));
                dlg.appendChild(el('div', {cls: 'dash-dlg-foot'}, [el('span', {cls: 'dash-spacer'}),
                    el('button', {type: 'button', cls: 'dash-btn', id: 'dw-cancel', on: {click: function () { dlg.close(); }}}, ['Cancel']),
                    el('button', {type: 'button', cls: 'dash-btn dash-btn--primary', id: 'dw-save', on: {click: function () {
                        grab();
                        checkWidget(W).then(function (clean) {
                            if (!clean) { return; }
                            var secs = E.model.definition.sections;
                            if (editing) { secs[si].widgets[wi] = clean; } else { secs[si].widgets.push(clean); }
                            dlg.close();
                            drawSectionsEditor();
                            markDirty();
                        });
                    }}}, [editing ? 'Save widget' : 'Add widget'])]));
            }

            draw();
            if (typeof dlg.showModal === 'function') { dlg.showModal(); } else { dlg.setAttribute('open', ''); }
            var first = dlg.querySelector('#dw-name');
            if (first) { first.focus(); }
        }

        // -------------------------------------------------------------- presets

        function openPresets(si) {
            var dlg = root.querySelector('#de-preset-dialog');
            dlg.textContent = '';
            var grid = el('div', {cls: 'de-presets'});
            if (!E.presets.length) { grid.appendChild(el('p', {cls: 'dash-dim', text: 'No presets available.'})); }
            E.presets.forEach(function (p) {
                var w = p.widget;
                grid.appendChild(el('button', {type: 'button', cls: 'de-preset', 'data-preset': p.key, on: {click: function () {
                    if (totalWidgets() >= E.vocab.limits.widgets) { toast('A dashboard holds at most ' + E.vocab.limits.widgets + ' widgets.', 'err'); return; }
                    var c = copy(w);
                    c.id = rid('w');
                    E.model.definition.sections[si].widgets.push(c);
                    dlg.close();
                    drawSectionsEditor();
                    markDirty();
                }}}, [el('span', {cls: 'de-preset-name', text: p.name}),
                      p.description ? el('span', {cls: 'dash-dim de-preset-desc', text: p.description}) : null,
                      widgetChips(w)]));
            });
            dlg.appendChild(el('div', {cls: 'de-dlg-head'}, [el('h2', {cls: 'dash-dlg-title', id: 'de-pd-title', text: 'Insert from a preset'})]));
            dlg.appendChild(el('p', {cls: 'dash-dim', text: 'Ready-made widgets. Picking one adds a copy to the section; edit it afterwards like any other.'}));
            dlg.appendChild(grid);
            dlg.appendChild(el('div', {cls: 'dash-dlg-foot'}, [el('span', {cls: 'dash-spacer'}),
                el('button', {type: 'button', cls: 'dash-btn', on: {click: function () { dlg.close(); }}}, ['Close'])]));
            if (typeof dlg.showModal === 'function') { dlg.showModal(); } else { dlg.setAttribute('open', ''); }
        }

        // -------------------------------------------------------------- confirm, delete

        function confirmBox(title, text, okText, onOk) {
            var dlg = root.querySelector('#de-confirm');
            dlg.textContent = '';
            dlg.appendChild(el('h2', {cls: 'dash-dlg-title', id: 'de-cf-title', text: title}));
            dlg.appendChild(el('p', {cls: 'dash-dim', text: text}));
            dlg.appendChild(el('div', {cls: 'dash-dlg-foot'}, [el('span', {cls: 'dash-spacer'}),
                el('button', {type: 'button', cls: 'dash-btn', id: 'de-cf-cancel', on: {click: function () { dlg.close(); }}}, ['Cancel']),
                el('button', {type: 'button', cls: 'dash-btn dash-btn--danger', id: 'de-cf-ok', on: {click: function () { dlg.close(); onOk(); }}}, [okText])]));
            if (typeof dlg.showModal === 'function') { dlg.showModal(); } else { dlg.setAttribute('open', ''); }
            var cancel = dlg.querySelector('#de-cf-cancel');
            if (cancel) { cancel.focus(); }
        }

        function confirmDelete() {
            confirmBox('Delete this dashboard?', 'It is gone for everyone it is shared with. This cannot be undone.', 'Delete', function () {
                api('DELETE', '/api/v2/custom-dashboards/' + E.key).then(function (res) {
                    if (!res.ok) { toast(D.errorText(res, 'The dashboard could not be deleted.'), 'err'); return; }
                    E.dirty = false;
                    location.href = D.pageUrl('/dashboards');
                });
            });
        }

        // -------------------------------------------------------------- the live preview

        function drawPreviewFrame() {
            var box = root.querySelector('#de-preview');
            box.textContent = '';
            var toggle = el('button', {type: 'button', cls: 'de-icon', id: 'de-preview-toggle', 'aria-expanded': E.previewOpen ? 'true' : 'false',
                                       'aria-controls': 'de-preview-body', 'aria-label': E.previewOpen ? 'Collapse the preview' : 'Expand the preview',
                                       text: E.previewOpen ? '⌃' : '⌄', on: {click: function () {
                E.previewOpen = !E.previewOpen;
                drawPreviewFrame();
                if (E.previewOpen) { renderPreview(); }
            }}});
            box.appendChild(el('div', {cls: 'de-preview-head'}, [
                el('h2', {cls: 'de-card-title', text: 'Live preview'}), (window.IrisHelp ? window.IrisHelp.el('custom_dashboards.scope', {cls: 'ml-1'}) : null),
                el('span', {cls: 'dash-spacer'}),
                el('span', {cls: 'dash-dim', id: 'de-preview-status', 'aria-live': 'polite'}),
                el('button', {type: 'button', cls: 'de-icon', id: 'de-preview-now', 'aria-label': 'Render the preview now',
                              title: 'Render now', on: {click: renderPreview}}, [icon('refresh', 'dash-i dash-i--xs')]),
                toggle]));
            var body = el('div', {id: 'de-preview-body', hidden: !E.previewOpen});
            box.appendChild(body);
        }

        function schedulePreview() {
            clearTimeout(E.ptimer);
            if (!E.previewOpen || E.mode !== 'visual') { return; }
            E.ptimer = setTimeout(renderPreview, 800);
        }

        function renderPreview() {
            if (!E.previewOpen) { return; }
            E.pseq += 1;
            var mine = E.pseq;
            var status = root.querySelector('#de-preview-status');
            var body = root.querySelector('#de-preview-body');
            if (!body) { return; }
            root.removeAttribute('data-de-preview');
            status.textContent = 'rendering…';
            var defn = copy(E.model.definition);
            api('POST', '/api/v2/custom-dashboards/preview', {definition: defn, range: defn.default_range}).then(function (res) {
                if (mine !== E.pseq) { return; }
                body.textContent = '';
                if (!res.ok || !res.data) {
                    var issues = res.data && res.data.data && res.data.data.issues;
                    body.appendChild(el('div', {cls: 'dash-alert', role: 'alert'}, [
                        el('p', {text: D.errorText(res, 'The preview could not be rendered.')}),
                        issues && issues.length ? el('ul', {}, issues.map(function (t) { return el('li', {text: t}); })) : null]));
                    status.textContent = 'not rendered';
                    root.setAttribute('data-de-preview', 'error-' + mine);
                    return;
                }
                var bodies = D.drawSections(body, defn, {emptyText: 'Add a widget to see it here.'});
                var labels = {};
                defn.filter_bar.forEach(function (e) { labels[e.key] = e.label; });
                D.fill(bodies, defn, res.data, {palette: E.vocab.palette, barLabels: labels});
                var now = new Date();
                status.textContent = 'last rendered ' + pad(now.getUTCHours()) + ':' + pad(now.getUTCMinutes()) + ':' + pad(now.getUTCSeconds()) + ' UTC';
                root.setAttribute('data-de-preview', 'ok-' + mine);
            });
        }

        // -------------------------------------------------------------- JSON mode

        function payload() {
            return {name: E.model.name, description: E.model.description || '', is_shared: !!E.model.is_shared,
                    definition: E.model.definition};
        }

        function jsonText() {
            if (E.ace) { return E.ace.getValue(); }
            var ta = root.querySelector('#de-json-ta');
            return ta ? ta.value : '';
        }

        function setJsonText(t) {
            if (E.ace) { E.ace.setValue(t, -1); return; }
            var ta = root.querySelector('#de-json-ta');
            if (ta) { ta.value = t; }
        }

        function jsonStatus(kind, text, issues) {
            var pill = root.querySelector('#de-json-pill');
            var list = root.querySelector('#de-json-issues');
            if (!pill) { return; }
            pill.className = 'de-pill de-pill--' + kind;
            pill.textContent = text;
            list.textContent = '';
            list.hidden = !(issues && issues.length);
            (issues || []).forEach(function (t) { list.appendChild(el('li', {text: t})); });
        }

        function checkJson() {
            var parsed;
            try { parsed = JSON.parse(jsonText()); } catch (e) {
                jsonStatus('bad', 'JSON syntax error', ['Invalid JSON: ' + e.message]);
                return Promise.resolve(null);
            }
            return api('POST', '/api/v2/custom-dashboards/validate', parsed).then(function (res) {
                if (!res.ok || !res.data) { jsonStatus('warn', 'Not checked', [D.errorText(res, 'The server did not answer.')]); return null; }
                if (!res.data.valid) {
                    var n = res.data.issues.length;
                    jsonStatus('warn', n + ' schema issue' + (n === 1 ? '' : 's'), res.data.issues);
                    return null;
                }
                jsonStatus('ok', 'Valid', []);
                return res.data.dashboard;
            });
        }

        function drawJson() {
            var box = root.querySelector('#de-json');
            box.textContent = '';
            var holder = el('div', {id: 'de-ace', cls: 'de-ace'});
            box.appendChild(el('section', {cls: 'dash-card'}, [
                el('div', {cls: 'de-bar-head'}, [el('h2', {cls: 'de-card-title', text: 'Definition (JSON)'}), (window.IrisHelp ? window.IrisHelp.el('custom_dashboards.json', {cls: 'ml-1'}) : null),
                    el('span', {cls: 'dash-spacer'}),
                    el('span', {cls: 'de-pill', id: 'de-json-pill', 'aria-live': 'polite'}),
                    el('button', {type: 'button', cls: 'dash-btn dash-btn--sm', id: 'de-json-format', on: {click: function () {
                        try { setJsonText(JSON.stringify(JSON.parse(jsonText()), null, 2)); } catch (e) { jsonStatus('bad', 'JSON syntax error', ['Invalid JSON: ' + e.message]); }
                    }}}, ['Reformat']),
                    el('button', {type: 'button', cls: 'dash-btn dash-btn--sm', id: 'de-json-reset', on: {click: function () {
                        setJsonText(JSON.stringify(payload(), null, 2));
                        checkJson();
                    }}}, ['Reset to current'])]),
                el('p', {cls: 'dash-dim', text: 'The whole dashboard as JSON: the server checks sources, fields, operators, charts and limits as you type. Visual applies it.'}),
                holder,
                el('ul', {cls: 'de-json-issues', id: 'de-json-issues', hidden: true})
            ]));
            var text = JSON.stringify(payload(), null, 2);
            E.ace = null;
            if (window.ace && typeof window.ace.edit === 'function') {
                try {
                    E.ace = window.ace.edit(holder);
                    E.ace.session.setMode('ace/mode/json');
                    E.ace.setTheme('ace/theme/tomorrow_night');
                    E.ace.session.setTabSize(2);
                    E.ace.setOption('showPrintMargin', false);
                    E.ace.setValue(text, -1);
                    E.ace.session.on('change', function () { clearTimeout(E.vtimer); E.vtimer = setTimeout(checkJson, 500); });
                } catch (e) { E.ace = null; }
            }
            if (!E.ace) {
                holder.className = 'de-ace de-ace--plain';
                var ta = el('textarea', {id: 'de-json-ta', cls: 'dash-input de-json-ta', spellcheck: 'false', 'aria-label': 'The dashboard as JSON',
                                         on: {input: function () { clearTimeout(E.vtimer); E.vtimer = setTimeout(checkJson, 500); }}});
                ta.value = text;
                holder.appendChild(ta);
            }
            checkJson();
        }

        function adopt(clean) {
            E.model = {name: clean.name, description: clean.description || '', is_shared: !!clean.is_shared,
                       definition: clean.definition};
        }

        function setMode(mode) {
            if (mode === E.mode) { return; }
            if (mode === 'json') {
                E.mode = 'json';
                root.querySelector('#de-visual').hidden = true;
                root.querySelector('#de-json').hidden = false;
                drawJson();
                syncModeButtons();
                return;
            }
            checkJson().then(function (clean) {
                if (!clean) { toast('Fix the JSON first: Visual applies it once it is valid.', 'err'); return; }
                var changed = JSON.stringify(clean) !== JSON.stringify(payload());
                adopt(clean);
                E.mode = 'visual';
                if (E.ace) { try { E.ace.destroy(); } catch (e) { /* gone */ } E.ace = null; }
                root.querySelector('#de-json').hidden = true;
                root.querySelector('#de-visual').hidden = false;
                drawVisual();
                syncModeButtons();
                if (changed) { markDirty(); } else { schedulePreview(); }
            });
        }

        function syncModeButtons() {
            Array.prototype.forEach.call(root.querySelectorAll('.de-mode'), function (b) {
                var on = b.getAttribute('data-mode') === E.mode;
                b.setAttribute('aria-pressed', on ? 'true' : 'false');
                b.classList.toggle('de-mode--on', on);
            });
        }

        // -------------------------------------------------------------- saving

        function showIssues(list, message) {
            var box = root.querySelector('#de-issues');
            box.textContent = '';
            if (!message && (!list || !list.length)) { box.hidden = true; return; }
            box.appendChild(el('p', {text: message || 'The dashboard was not saved.'}));
            if (list && list.length) { box.appendChild(el('ul', {}, list.map(function (t) { return el('li', {text: t}); }))); }
            box.hidden = false;
        }

        function save() {
            if (E.saving) { return; }
            var go = function () {
                E.saving = true;
                var btn = root.querySelector('#de-save');
                btn.disabled = true;
                btn.textContent = 'Saving…';
                var req = E.key ? api('PUT', '/api/v2/custom-dashboards/' + E.key, payload())
                                : api('POST', '/api/v2/custom-dashboards', payload());
                req.then(function (res) {
                    E.saving = false;
                    btn.disabled = false;
                    btn.textContent = 'Save';
                    if (!res.ok || !res.data) {
                        var issues = res.data && res.data.data && res.data.data.issues;
                        showIssues(issues || [], D.errorText(res, 'The dashboard was not saved.'));
                        return;
                    }
                    showIssues(null);
                    var wasNew = !E.key;
                    var nk = D.keyOf(res.data.key);
                    adopt(res.data);
                    E.key = nk;
                    E.dirty = false;
                    if (wasNew && nk) {
                        history.replaceState(null, '', D.pageUrl('/dashboards/' + nk + '/edit'));
                        if (E.ace) { try { E.ace.destroy(); } catch (e) { /* gone */ } E.ace = null; }
                        E.mode = 'visual';
                        frame();
                        syncModeButtons();
                    } else if (E.mode === 'visual') {
                        drawVisual();
                    } else {
                        setJsonText(JSON.stringify(payload(), null, 2));
                    }
                    var st = root.querySelector('#de-state');
                    st.textContent = '';
                    st.appendChild(document.createTextNode('Saved. '));
                    st.appendChild(el('a', {href: D.pageUrl('/dashboards/' + nk), id: 'de-open', text: 'Open the dashboard'}));
                    toast('Saved.', 'ok');
                    root.setAttribute('data-de-saved', nk);
                    renderPreview();
                });
            };
            if (E.mode === 'json') {
                checkJson().then(function (clean) {
                    if (!clean) { showIssues(null, 'Fix the JSON first: it is not valid yet.'); return; }
                    adopt(clean);
                    go();
                });
            } else {
                go();
            }
        }

        // -------------------------------------------------------------- start

        function start(st) {
            E.vocab = st.schema.vocab;
            E.options = st.schema.options || {};
            E.presets = st.presets || [];
            var d = st.dashboard;
            E.key = D.keyOf(d.key) || null;
            adopt(d);
            frame();
            syncModeButtons();
            renderPreview();
            root.setAttribute('data-de-ready', '1');
        }

        window.addEventListener('beforeunload', function (e) {
            if (E.dirty) { e.preventDefault(); e.returnValue = ''; }
        });

        if (state) {
            start(state);
            return;
        }
        var reqs = [api('GET', '/api/v2/custom-dashboards/schema'), api('GET', '/api/v2/custom-dashboards/presets')];
        if (E.key) { reqs.push(api('GET', '/api/v2/custom-dashboards/' + E.key)); }
        Promise.all(reqs).then(function (rs) {
            var bad = rs.filter(function (r) { return !r.ok; })[0];
            if (bad) {
                root.appendChild(el('div', {cls: 'dash-alert', role: 'alert', text: D.errorText(bad, 'The editor could not be loaded.')}));
                return;
            }
            var dash = E.key ? rs[2].data : {key: null, name: 'Untitled dashboard', description: '', is_shared: false,
                                             definition: {sections: [{id: 's1', title: 'Overview', description: '', widgets: []}],
                                                          filter_bar: [], default_range: rs[0].data.vocab.default_range}};
            start({dashboard: dash, schema: rs[0].data, presets: rs[1].data});
        });
    }

    window.IrisDashEditor = {mount: mount};
})();

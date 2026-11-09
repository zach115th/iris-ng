/* IrisAlertQueryBar - the Alerts page's search bar (iris-ng, 2026-11-09).
 *
 *   var bar = IrisAlertQueryBar.create(root, {fields: vocab.query_fields, options, isValues, nullable, onSubmit: fn(text)});
 *   bar.set({text, clauses: [{text}]});   // the search as the server parsed it: one chip per condition
 *   bar.setError({message}, text);        // a refused search stays in the box, with the server's message
 *   bar.focus(); bar.text();
 *
 * The server is the only parser: this file splits nothing but the word under the caret, to suggest field names and
 * values. Built with DOM calls only; recent searches live in localStorage (they are a convenience).
 */
(function () {
    'use strict';

    var RECENT_KEY = 'irisAlertRecentSearches';
    var RECENT_MAX = 8;
    var MAX_SUGGESTIONS = 10;
    var KEYWORDS = [{label: 'OR', detail: 'match either side'},
                    {label: 'AND', detail: 'match both (what a space already means)'},
                    {label: 'NOT', detail: 'exclude what follows'}];

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

    function readRecent() {
        try {
            var v = JSON.parse(window.localStorage.getItem(RECENT_KEY) || '[]');
            return Array.isArray(v) ? v.filter(function (x) { return typeof x === 'string' && x; }) : [];
        } catch (e) { return []; }
    }

    function remember(text) {
        if (!text) { return; }
        var list = [text].concat(readRecent().filter(function (x) { return x !== text; })).slice(0, RECENT_MAX);
        try { window.localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch (e) { /* a convenience */ }
    }

    function quoted(value) {
        return /[\s"()[\]{}]/.test(value) ? '"' + value.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"' : value;
    }

    function create(root, cfg) {
        var clauses = [];
        var items = [];
        var active = -1;
        var blurTimer = null;

        var chips = el('span', {cls: 'aq-q-chips'});
        var input = el('input', {type: 'text', id: 'aq-q', cls: 'aq-q-input', autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false',
                                 maxlength: String(cfg.maxLength || 2000), role: 'combobox', 'aria-autocomplete': 'list', 'aria-expanded': 'false',
                                 'aria-controls': 'aq-q-list', 'aria-label': 'Search alerts',
                                 placeholder: 'Search alerts: try  is:open owner:me severity:>=High'});
        var clear = el('button', {type: 'button', cls: 'aq-q-clear', id: 'aq-q-clear', 'aria-label': 'Clear the search', title: 'Clear the search', text: '×', hidden: true});
        var list = el('div', {id: 'aq-q-list', cls: 'aq-q-list', role: 'listbox', hidden: true});
        var err = el('p', {cls: 'aq-q-error', id: 'aq-q-error', role: 'alert', hidden: true});
        root.textContent = '';
        root.appendChild(el('div', {cls: 'aq-q-box'}, [
            el('span', {cls: 'aq-q-icon', 'aria-hidden': 'true', text: '⌕'}), chips, input, clear]));
        root.appendChild(list);
        root.appendChild(err);

        function fields() { return cfg.fields || []; }

        function fieldOf(name) {
            var low = name.toLowerCase();
            return fields().filter(function (f) { return f.key === low || f.synonyms.indexOf(low) !== -1; })[0];
        }

        function committed() { return clauses.map(function (c) { return c.text; }).join(' '); }

        function joined(extra) { return (committed() + ' ' + (extra || '')).trim(); }

        function drawChips() {
            chips.textContent = '';
            clauses.forEach(function (c, i) {
                chips.appendChild(el('span', {cls: 'aq-chip'}, [
                    el('button', {type: 'button', cls: 'aq-chip-text', title: 'Edit this condition', text: c.text, on: {click: function () {
                        var taken = clauses.splice(i, 1)[0];
                        input.value = (taken.text + ' ' + input.value).trim();
                        drawChips();
                        input.focus();
                    }}}),
                    el('button', {type: 'button', cls: 'aq-chip-x', 'aria-label': 'Remove filter ' + c.text, title: 'Remove', text: '×', on: {click: function () {
                        clauses.splice(i, 1);
                        drawChips();
                        submit(joined(input.value));
                    }}})
                ]));
            });
            clear.hidden = !clauses.length && !input.value;
            input.setAttribute('placeholder', clauses.length ? '' : 'Search alerts: try  is:open owner:me severity:>=High');
        }

        function close() {
            items = [];
            active = -1;
            list.hidden = true;
            list.textContent = '';
            input.setAttribute('aria-expanded', 'false');
            input.removeAttribute('aria-activedescendant');
        }

        function drawList(title) {
            list.textContent = '';
            if (!items.length) { close(); return; }
            if (title) { list.appendChild(el('p', {cls: 'aq-q-listhead', text: title})); }
            items.forEach(function (it, i) {
                list.appendChild(el('button', {type: 'button', role: 'option', id: 'aq-q-opt' + i, cls: 'aq-q-opt' + (i === active ? ' aq-q-opt--on' : ''),
                                               'aria-selected': i === active ? 'true' : 'false', tabindex: '-1',
                                               on: {mousedown: function (e) { e.preventDefault(); pick(it); }}}, [
                    el('span', {cls: 'aq-q-opt-label', text: it.label}),
                    it.detail ? el('span', {cls: 'aq-q-opt-detail', text: it.detail}) : null]));
            });
            list.hidden = false;
            input.setAttribute('aria-expanded', 'true');
            if (active >= 0) { input.setAttribute('aria-activedescendant', 'aq-q-opt' + active); } else { input.removeAttribute('aria-activedescendant'); }
        }

        function valuesFor(f) {
            var out = [];
            if (f.key === 'is') { return (cfg.isValues || []).slice(); }
            if (f.key === 'owner') { out.push('me'); }
            if ((cfg.nullable || []).indexOf(f.key) !== -1) { out.push('none'); }
            ((cfg.options || {})[f.options] || []).forEach(function (o) { out.push(o.name); });
            return out;
        }

        function suggest() {
            var text = input.value;
            var pos = input.selectionStart === null ? text.length : input.selectionStart;
            var before = text.slice(0, pos);
            if (!text.trim() && !clauses.length) {
                items = readRecent().map(function (r) { return {label: r, recent: true}; });
                active = -1;
                drawList('Recent searches');
                return;
            }
            var word = /(^|[\s(])(-?)([^\s()"]*)$/.exec(before);
            if (!word) { close(); return; }
            var body = word[3];
            var colon = body.indexOf(':');
            var from = before.length - body.length;
            var found = [];
            if (colon > 0) {
                var f = fieldOf(body.slice(0, colon));
                if (!f) { close(); return; }
                var typed = body.slice(colon + 1);
                var op = (/^(>=|<=|>|<)/.exec(typed) || [''])[0];
                var q = typed.slice(op.length).replace(/^"/, '').toLowerCase();
                valuesFor(f).forEach(function (v) {
                    if (found.length < MAX_SUGGESTIONS && v.toLowerCase().indexOf(q) === 0) {
                        found.push({label: v, detail: f.key, insert: body.slice(0, colon + 1) + op + quoted(v) + ' ', from: from});
                    }
                });
            } else {
                var low = body.toLowerCase();
                if (low || before.trim()) {
                    fields().forEach(function (fd) {
                        [fd.key].concat(fd.synonyms).forEach(function (name) {
                            if (found.length < MAX_SUGGESTIONS && name.indexOf(low) === 0) {
                                found.push({label: name + ':', detail: fd.label, insert: name + ':', from: from, keepOpen: true});
                            }
                        });
                    });
                    if (body && (committed() || before.slice(0, from).trim())) {
                        KEYWORDS.forEach(function (k) {
                            if (k.label.toLowerCase().indexOf(low) === 0) { found.push({label: k.label, detail: k.detail, insert: k.label + ' ', from: from}); }
                        });
                    }
                }
            }
            items = found;
            active = -1;
            drawList(null);
        }

        function pick(it) {
            if (it.recent) {
                input.value = it.label;
                close();
                submit(joined(it.label));
                return;
            }
            var text = input.value;
            var pos = input.selectionStart === null ? text.length : input.selectionStart;
            input.value = text.slice(0, it.from) + it.insert + text.slice(pos);
            var caret = it.from + it.insert.length;
            input.setSelectionRange(caret, caret);
            input.focus();
            if (it.keepOpen) { suggest(); } else { close(); }
        }

        function submit(text) {
            close();
            remember(text);
            err.hidden = true;
            input.value = '';
            cfg.onSubmit(text);
        }

        input.addEventListener('input', function () { clear.hidden = !clauses.length && !input.value; suggest(); });
        input.addEventListener('focus', function () { if (blurTimer) { clearTimeout(blurTimer); } suggest(); });
        input.addEventListener('blur', function () { blurTimer = setTimeout(close, 120); });
        input.addEventListener('keydown', function (e) {
            if (e.key === 'ArrowDown' && items.length) { e.preventDefault(); active = (active + 1) % items.length; drawList(items[0] && items[0].recent ? 'Recent searches' : null); return; }
            if (e.key === 'ArrowUp' && items.length) { e.preventDefault(); active = (active + items.length - 1) % items.length; drawList(items[0] && items[0].recent ? 'Recent searches' : null); return; }
            if (e.key === 'Tab' && active >= 0) { e.preventDefault(); pick(items[active]); return; }
            if (e.key === 'Enter') {
                e.preventDefault();
                if (active >= 0) { pick(items[active]); return; }
                submit(joined(input.value));
                return;
            }
            if (e.key === 'Escape' && !list.hidden) { e.stopPropagation(); close(); return; }
            if (e.key === 'Backspace' && !input.value && clauses.length) {
                e.preventDefault();
                var last = clauses.pop();
                input.value = last.text;
                drawChips();
                input.setSelectionRange(input.value.length, input.value.length);
            }
        });
        clear.addEventListener('click', function () {
            clauses = [];
            input.value = '';
            drawChips();
            submit('');
            input.focus();
        });

        return {
            set: function (described) {
                clauses = ((described && described.clauses) || []).map(function (c) { return {text: c.text}; });
                err.hidden = true;
                err.textContent = '';
                drawChips();
            },
            setError: function (queryError, text) {
                clauses = [];
                input.value = text || '';
                drawChips();
                err.textContent = (queryError && queryError.message) || 'The search could not be read.';
                err.hidden = false;
            },
            focus: function () { input.focus(); },
            text: function () { return joined(input.value); }
        };
    }

    window.IrisAlertQueryBar = {create: create};
})();

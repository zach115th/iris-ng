/*  iris-ng tutorials (2026-11-10): the Tutorials list (/tutorials), Settings -> Tutorials (/manage/tutorials) and
    its editor (/manage/tutorials/<ref>). Import-free; every page draws its first frame from the state embedded in it
    (null = the read failed: fetch it). Values reach the DOM through textContent / .value or esc(); the runner itself
    is tutorial_runner.js (window.IrisTutorial). */
(function () {
    'use strict';

    var API = '/api/v2';

    function esc(s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function csrf(root) {
        var el = root.querySelector('input[name="csrf_token"]') || document.querySelector('input[name="csrf_token"]');
        if (el && el.value) { return el.value; }
        return window.IrisTutorial && window.IrisTutorial.csrf ? window.IrisTutorial.csrf() : '';
    }

    function getJson(url) {
        return fetch(url, {credentials: 'same-origin'}).then(function (r) {
            return r.json().catch(function () { return null; }).then(function (j) { return {status: r.status, data: j}; });
        });
    }

    function postJson(root, url, body) {
        body = body || {};
        body.csrf_token = csrf(root);
        return fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
                           body: JSON.stringify(body)}).then(function (r) {
            return r.json().catch(function () { return null; }).then(function (j) { return {status: r.status, data: j}; });
        }, function () { return {status: 0, data: null}; });
    }

    function message(res) {
        var d = res && res.data;
        return (d && d.message) || (res && res.status ? 'The server answered ' + res.status : 'The server could not be reached.');
    }

    function issuesOf(res) {
        var d = res && res.data;
        return (d && d.data && Array.isArray(d.data.issues)) ? d.data.issues : [];
    }

    function toast(root, text) {
        var t = root.querySelector('.iris-tut-toast');
        if (!t) { return; }
        t.textContent = text;
        t.hidden = false;
        window.clearTimeout(t.__timer);
        t.__timer = window.setTimeout(function () { t.hidden = true; }, 3500);
    }

    function showIssues(root, title, issues) {
        var box = root.querySelector('#iris-tut-issues');
        if (!box) { return; }
        if (!title) { box.hidden = true; box.innerHTML = ''; return; }
        box.innerHTML = '<strong>' + esc(title) + '</strong>' +
            (issues && issues.length ? '<ul>' + issues.map(function (i) { return '<li>' + esc(i) + '</li>'; }).join('') + '</ul>' : '');
        box.hidden = false;
        box.scrollIntoView({block: 'nearest'});
    }

    function when(iso) {
        if (!iso) { return ''; }
        // Stored UTC; shown as the UTC digits it carries.
        return String(iso).replace('T', ' ').replace(/\.\d+/, '').replace('Z', ' UTC');
    }

    var SVG = {
        play: '<path d="M6 3l14 9-14 9V3z"/>',
        pencil: '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
        download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
        restore: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
        trash: '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
        up: '<path d="m18 15-6-6-6 6"/>',
        down: '<path d="m6 9 6 6 6-6"/>',
        x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
        check: '<path d="M20 6 9 17l-5-5"/>'
    };
    function svg(name, size) {
        size = size || 15;
        return '<svg xmlns="http://www.w3.org/2000/svg" width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + SVG[name] + '</svg>';
    }

    // Literal keys, so scripts/_help_glossary_check.py sees each icon.
    function helpIcons() {
        var IrisHelp = window.IrisHelp;
        if (!IrisHelp || !IrisHelp.icon) { return {}; }
        return {highlight: IrisHelp.icon('tutorials.highlight'), goto: IrisHelp.icon('tutorials.goto'),
                done: IrisHelp.icon('tutorials.done_when'), fills: IrisHelp.icon('tutorials.fills'),
                cleanup: IrisHelp.icon('tutorials.cleanup')};
    }

    function startPreview(root, content) {
        return postJson(root, API + '/manage/tutorials/try', {content: content}).then(function (res) {
            if (res.status === 200 && res.data && window.IrisTutorial) {
                window.IrisTutorial.use(res.data);
                showIssues(root, null);
                toast(root, 'Preview started: the panel is at the bottom right.');
                return true;
            }
            showIssues(root, message(res), issuesOf(res));
            return false;
        });
    }

    // ------------------------------------------------------------------ the Tutorials list

    function mountList(root, state) {
        var box = root.querySelector('#iris-tut-cards');
        var data = state;

        function actionsHtml(t, runningRef) {
            var s = t.status || {};
            if (runningRef === t.ref || s.running) {
                return '<button type="button" class="btn btn-sm btn-outline-secondary" disabled>In progress</button>';
            }
            if (s.paused_step) {
                return '<button type="button" class="btn btn-sm btn-primary" data-tut-go="resume" data-ref="' + esc(t.ref) + '">Continue</button>' +
                    '<button type="button" class="btn btn-sm btn-outline-secondary" data-tut-go="start" data-ref="' + esc(t.ref) + '">Start again</button>';
            }
            if (s.completed) {
                return '<button type="button" class="btn btn-sm btn-outline-secondary" data-tut-go="start" data-ref="' + esc(t.ref) + '">Start again</button>';
            }
            return '<button type="button" class="btn btn-sm btn-primary" data-tut-go="start" data-ref="' + esc(t.ref) + '">Start</button>';
        }

        function draw() {
            if (!data) { box.innerHTML = '<p class="iris-tut-empty">The tutorials could not be loaded. Reload the page to try again.</p>'; return; }
            var run = window.IrisTutorial && window.IrisTutorial.current();
            var runningRef = run ? run.ref : null;
            if (!data.tutorials.length) {
                box.innerHTML = '<p class="iris-tut-empty">No tutorial is published for you yet.</p>';
                return;
            }
            box.innerHTML = data.tutorials.map(function (t) {
                var s = t.status || {};
                var chips = '';
                if (s.completed) { chips += '<span class="iris-tut-chip iris-tut-chip--done">' + svg('check', 12) + 'Completed</span>'; }
                if (s.paused_step && !(runningRef === t.ref || s.running)) {
                    chips += '<span class="iris-tut-chip iris-tut-chip--run">Stopped at step ' + esc(s.paused_step + 1) + '</span>';
                }
                if (t.audience === 'admins') { chips += '<span class="iris-tut-chip iris-tut-chip--admin">Administrators</span>'; }
                var meta = esc(t.steps) + ' step' + (t.steps === 1 ? '' : 's') + (t.duration ? ' · ' + esc(t.duration) : '');
                return '<article class="iris-tut-card" data-ref="' + esc(t.ref) + '">' +
                    '<h2 class="iris-tut-card-title">' + esc(t.title) + chips + '</h2>' +
                    '<div class="iris-tut-card-act">' + actionsHtml(t, runningRef) + '</div>' +
                    (t.summary ? '<p class="iris-tut-card-sum">' + esc(t.summary) + '</p>' : '') +
                    '<p class="iris-tut-card-meta">' + meta + '</p></article>';
            }).join('');
        }

        function reload() {
            getJson(API + '/tutorials').then(function (res) {
                if (res.status === 200 && res.data) { data = res.data; }
                draw();
            }, function () { draw(); });
        }

        box.addEventListener('click', function (e) {
            var b = e.target.closest('[data-tut-go]');
            if (!b || !window.IrisTutorial) { return; }
            // The ref comes from the list the page holds, never from the attribute (page text).
            var item = (data && data.tutorials || []).filter(function (t) { return t.ref === b.getAttribute('data-ref'); })[0];
            if (!item) { return; }
            var ref = item.ref;
            var go = b.getAttribute('data-tut-go') === 'resume' ? window.IrisTutorial.resume : window.IrisTutorial.start;
            b.disabled = true;
            go(ref).then(function (r) {
                if (!r.ok) { b.disabled = false; toast(root, r.message); }
            });
        });
        document.addEventListener('iris-tutorial-changed', reload);

        if (data) { draw(); } else { reload(); }
    }

    // ------------------------------------------------------------------ Settings -> Tutorials

    var STATUS_LABEL = {shipped: 'As shipped', edited: 'Edited', hidden: 'Hidden', published: 'Published', draft: 'Draft'};

    function mountManage(root, state) {
        var data = state;
        var fileInput = root.querySelector('#iris-tut-import-file');

        function rowHtml(t, builtin) {
            var acts = '<button type="button" class="iris-tut-icon" data-tut-row="try" data-ref="' + esc(t.ref) + '" title="Try it" aria-label="Try ' + esc(t.title) + '">' + svg('play') + '</button>' +
                '<a class="iris-tut-icon" href="/manage/tutorials/' + encodeURIComponent(t.ref) + '" title="Edit" aria-label="Edit ' + esc(t.title) + '">' + svg('pencil') + '</a>' +
                '<a class="iris-tut-icon" href="' + API + '/manage/tutorials/' + encodeURIComponent(t.ref) + '/export" title="Export" aria-label="Export ' + esc(t.title) + '">' + svg('download') + '</a>';
            if (builtin && t.status !== 'shipped') {
                acts += '<button type="button" class="iris-tut-icon" data-tut-row="restore" data-ref="' + esc(t.ref) + '" title="Restore the shipped version" aria-label="Restore ' + esc(t.title) + '">' + svg('restore') + '</button>';
            }
            if (!builtin) {
                acts += '<button type="button" class="iris-tut-icon iris-tut-icon--danger" data-tut-row="delete" data-ref="' + esc(t.ref) + '" title="Delete" aria-label="Delete ' + esc(t.title) + '">' + svg('trash') + '</button>';
            }
            var chip = t.audience === 'admins' ? ' <span class="iris-tut-chip iris-tut-chip--admin">Administrators</span>' : '';
            return '<tr><td><div class="iris-tut-row-title">' + esc(t.title) + chip + '</div>' +
                (t.summary ? '<div class="iris-tut-row-sum">' + esc(t.summary) + '</div>' : '') + '</td>' +
                '<td class="iris-tut-num">' + esc(t.steps) + '</td>' +
                '<td class="iris-tut-num iris-tut-status--' + esc(t.status) + '">' + esc(STATUS_LABEL[t.status] || t.status) + '</td>' +
                '<td class="iris-tut-num">' + (t.updated_at ? esc(when(t.updated_at)) + (t.updated_by ? '<br><small class="text-muted">' + esc(t.updated_by) + '</small>' : '') : '<span class="text-muted">—</span>') + '</td>' +
                '<td><div class="iris-tut-row-acts">' + acts + '</div></td></tr>';
        }

        function table(rows, builtin, empty) {
            if (!rows.length) { return '<p class="text-muted">' + esc(empty) + '</p>'; }
            return '<table class="iris-tut-table"><thead><tr><th>Title</th><th>Steps</th><th>Status</th><th>Updated</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody>' +
                rows.map(function (t) { return rowHtml(t, builtin); }).join('') + '</tbody></table>';
        }

        function draw() {
            if (!data) {
                root.querySelector('#iris-tut-builtin').innerHTML = '<p class="text-muted">The tutorials could not be loaded. Refresh to try again.</p>';
                root.querySelector('#iris-tut-team').innerHTML = '';
                return;
            }
            root.querySelector('#iris-tut-builtin').innerHTML = table(data.builtin, true, 'No built-in tutorial could be loaded.');
            root.querySelector('#iris-tut-team').innerHTML = table(data.team, false, 'None yet: New tutorial writes one, Import loads a tutorial file.');
        }

        function reload() {
            getJson(API + '/manage/tutorials').then(function (res) {
                if (res.status === 200 && res.data) { data = res.data; }
                draw();
            });
        }

        root.addEventListener('click', function (e) {
            var a = e.target.closest('[data-tut-act]');
            if (a) {
                var act = a.getAttribute('data-tut-act');
                if (act === 'refresh') { reload(); }
                if (act === 'import') { fileInput.value = ''; fileInput.click(); }
                return;
            }
            var b = e.target.closest('[data-tut-row]');
            if (!b) { return; }
            // The ref comes from the lists the page holds, never from the attribute (page text).
            var item = (data ? data.builtin.concat(data.team) : []).filter(function (t) { return t.ref === b.getAttribute('data-ref'); })[0];
            if (!item) { return; }
            var ref = item.ref;
            var what = b.getAttribute('data-tut-row');
            if (what === 'try') {
                getJson(API + '/manage/tutorials/' + encodeURIComponent(ref)).then(function (res) {
                    if (res.status === 200 && res.data) { startPreview(root, res.data.content); }
                    else { toast(root, message(res)); }
                });
            } else if (what === 'restore') {
                if (!window.confirm('Drop your version and bring back the tutorial shipped with IRIS?')) { return; }
                postJson(root, API + '/manage/tutorials/' + encodeURIComponent(ref) + '/delete').then(function (res) {
                    if (res.status === 200) { toast(root, 'Restored.'); reload(); } else { toast(root, message(res)); }
                });
            } else if (what === 'delete') {
                if (!window.confirm('Delete this tutorial for everyone? This cannot be undone.')) { return; }
                postJson(root, API + '/manage/tutorials/' + encodeURIComponent(ref) + '/delete').then(function (res) {
                    if (res.status === 200) { toast(root, 'Deleted.'); reload(); } else { toast(root, message(res)); }
                });
            }
        });

        fileInput.addEventListener('change', function () {
            var f = fileInput.files && fileInput.files[0];
            if (!f) { return; }
            var reader = new FileReader();
            reader.onload = function () {
                postJson(root, API + '/manage/tutorials/import', {file: String(reader.result || '')}).then(function (res) {
                    if (res.status === 201 && res.data) {
                        showIssues(root, null);
                        toast(root, 'Imported as a draft: "' + res.data.content.title + '".');
                        reload();
                    } else {
                        showIssues(root, message(res), issuesOf(res));
                    }
                });
            };
            reader.onerror = function () { showIssues(root, 'The file could not be read.', []); };
            reader.readAsText(f);
        });

        if (data) { draw(); } else { reload(); }
    }

    // ------------------------------------------------------------------ the editor

    function mountEditor(root, state, vocab) {
        var S = state || {ref: null, kind: 'team', content: {title: '', summary: '', duration: '', audience: 'everyone', steps: []}, published: false};
        var list = root.querySelector('#iris-tut-steps');
        var dirty = false;
        var HELP = helpIcons();
        var $ = function (sel) { return root.querySelector(sel); };

        function doneOptions() {
            return vocab.done_when.map(function (d) { return '<option value="' + esc(d.value) + '">' + esc(d.label) + '</option>'; }).join('');
        }
        function methodOptions() {
            return vocab.methods.map(function (m) { return '<option value="' + esc(m) + '">' + esc(m) + '</option>'; }).join('');
        }
        function cleanupOptions() {
            return vocab.cleanup.map(function (c) { return '<option value="' + esc(c.value) + '">' + esc(c.label) + '</option>'; }).join('');
        }

        function captureRow(name, source, page) {
            var row = document.createElement('div');
            row.className = 'iris-tut-sub-row';
            row.setAttribute('data-capture', '');
            row.innerHTML = '<input type="text" class="form-control form-control-sm" data-f="cap-name" placeholder="Name, e.g. caseId" aria-label="Captured value name">' +
                '<input type="text" class="form-control form-control-sm" data-f="cap-src" placeholder="' + (page ? 'Query parameter, e.g. cid' : 'Reply field, e.g. case_id or data.ioc_id') + '" aria-label="Where to read it">' +
                '<button type="button" class="iris-tut-icon iris-tut-icon--danger" data-ed="rm-row" title="Remove" aria-label="Remove this value">' + svg('x', 13) + '</button>';
            row.querySelector('[data-f="cap-name"]').value = name || '';
            row.querySelector('[data-f="cap-src"]').value = source || '';
            return row;
        }

        function fillRow(f) {
            var row = document.createElement('div');
            row.className = 'iris-tut-sub-row';
            row.setAttribute('data-fill', '');
            row.innerHTML = '<input type="text" class="form-control form-control-sm" data-f="fill-label" placeholder="Label" aria-label="Fill button label" maxlength="' + vocab.limits.fill_label + '">' +
                '<input type="text" class="form-control form-control-sm" data-f="fill-anchor" placeholder="Field: data-tour name or CSS selector" aria-label="Field to fill">' +
                '<textarea class="form-control form-control-sm" rows="1" data-f="fill-value" placeholder="Value" aria-label="Value to fill in"></textarea>' +
                '<button type="button" class="iris-tut-icon iris-tut-icon--danger" data-ed="rm-row" title="Remove" aria-label="Remove this Fill button">' + svg('x', 13) + '</button>';
            row.querySelector('[data-f="fill-label"]').value = (f && f.label) || '';
            row.querySelector('[data-f="fill-anchor"]').value = (f && f.anchor) || '';
            row.querySelector('[data-f="fill-value"]').value = (f && f.value) || '';
            return row;
        }

        function cleanupRow(c) {
            var row = document.createElement('div');
            row.className = 'iris-tut-sub-row';
            row.setAttribute('data-cleanup', '');
            row.innerHTML = '<select class="form-control form-control-sm" data-f="cl-kind" aria-label="What to offer to delete">' + cleanupOptions() + '</select>' +
                '<input type="text" class="form-control form-control-sm" data-f="cl-var" placeholder="Captured value holding its id, e.g. caseId" aria-label="Captured value holding its id">' +
                '<button type="button" class="iris-tut-icon iris-tut-icon--danger" data-ed="rm-row" title="Remove" aria-label="Remove this clean-up">' + svg('x', 13) + '</button>';
            row.querySelector('[data-f="cl-kind"]').value = (c && c.kind) || vocab.cleanup[0].value;
            row.querySelector('[data-f="cl-var"]').value = (c && c.var) || '';
            return row;
        }

        function stepCard(st) {
            var card = document.createElement('section');
            card.className = 'iris-tut-step';
            card.innerHTML =
                '<div class="iris-tut-step-head"><span class="iris-tut-step-n"></span>' +
                '<input type="text" class="form-control form-control-sm" data-f="title" placeholder="Step title" aria-label="Step title" maxlength="' + vocab.limits.step_title + '" data-tour="tut-step-title">' +
                '<button type="button" class="iris-tut-icon" data-ed="up" title="Move up" aria-label="Move this step up">' + svg('up') + '</button>' +
                '<button type="button" class="iris-tut-icon" data-ed="down" title="Move down" aria-label="Move this step down">' + svg('down') + '</button>' +
                '<button type="button" class="iris-tut-icon iris-tut-icon--danger" data-ed="rm-step" title="Delete this step" aria-label="Delete this step">' + svg('trash') + '</button></div>' +
                '<div class="iris-tut-step-body">' +
                '<div class="form-group"><label>What to do</label>' +
                '<textarea class="form-control" rows="3" data-f="body" maxlength="' + vocab.limits.body + '" aria-label="What to do" data-tour="tut-step-body"></textarea>' +
                '<p class="iris-tut-hint">**bold**, `code`, and values captured earlier as {name}.</p></div>' +
                '<div class="form-row"><div class="form-group col-md-6"><label>Highlight</label>' + (HELP.highlight || '') +
                '<textarea class="form-control form-control-sm" rows="2" data-f="anchor" aria-label="Highlight" data-tour="tut-step-anchor"></textarea>' +
                '<p class="iris-tut-hint">A data-tour name or a CSS selector per line; the first one on screen is highlighted.</p></div>' +
                '<div class="form-group col-md-6"><label>"Take me there" link</label>' + (HELP.goto || '') +
                '<input type="text" class="form-control form-control-sm" data-f="goto" placeholder="/case/ioc?cid={caseId}" aria-label="Take me there link">' +
                '<p class="iris-tut-hint">Offered when the learner is on another page.</p></div></div>' +
                '<div class="form-group"><label>Done when</label>' + (HELP.done || '') +
                '<select class="form-control form-control-sm" data-f="kind" aria-label="Done when" data-tour="tut-step-done">' + doneOptions() + '</select>' +
                '<div class="iris-tut-sub" data-sub="element" hidden><input type="text" class="form-control form-control-sm" data-f="w-anchor" placeholder="The element that appears: data-tour name or CSS selector" aria-label="Element to wait for"></div>' +
                '<div class="iris-tut-sub" data-sub="page" hidden><input type="text" class="form-control form-control-sm" data-f="w-page" placeholder="/case/ioc?cid={caseId} - * matches any segment or value" aria-label="Page to wait for">' +
                '<div class="mt-2" data-caps></div><button type="button" class="iris-tut-linkbtn" data-ed="add-cap">+ Capture a query parameter</button></div>' +
                '<div class="iris-tut-sub" data-sub="request" hidden><div class="iris-tut-sub-row"><select class="form-control form-control-sm" data-f="w-method" aria-label="Request method" style="flex:0 0 100px">' + methodOptions() + '</select>' +
                '<input type="text" class="form-control form-control-sm" data-f="w-path" placeholder="/api/v2/cases - the path without its query; * matches a segment" aria-label="Request path"></div>' +
                '<div data-caps></div><button type="button" class="iris-tut-linkbtn" data-ed="add-cap">+ Capture a value from the reply</button></div></div>' +
                '<div class="form-group"><label>Fill buttons</label>' + (HELP.fills || '') + '<div data-fills></div>' +
                '<button type="button" class="iris-tut-linkbtn" data-ed="add-fill">+ Add a value the learner can fill in with one click</button></div>' +
                '<div class="form-group mb-0"><label>Clean-up</label>' + (HELP.cleanup || '') + '<div data-cleanups></div>' +
                '<button type="button" class="iris-tut-linkbtn" data-ed="add-cleanup">+ Offer to delete what this tutorial created</button></div>' +
                '</div>';
            card.querySelector('[data-f="title"]').value = st.title || '';
            card.querySelector('[data-f="body"]').value = st.body || '';
            card.querySelector('[data-f="anchor"]').value = (st.anchor ? (Array.isArray(st.anchor) ? st.anchor : [st.anchor]) : []).join('\n');
            card.querySelector('[data-f="goto"]').value = st.goTo || '';
            var w = st.waitFor || null;
            var kind = w ? w.kind : 'next';
            card.querySelector('[data-f="kind"]').value = kind;
            if (w && w.kind === 'element') { card.querySelector('[data-f="w-anchor"]').value = (Array.isArray(w.anchor) ? w.anchor : [w.anchor]).join('\n'); }
            if (w && w.kind === 'page') { card.querySelector('[data-f="w-page"]').value = w.path || ''; }
            if (w && w.kind === 'request') {
                card.querySelector('[data-f="w-method"]').value = w.method || 'POST';
                card.querySelector('[data-f="w-path"]').value = w.path || '';
            }
            if (w && w.capture) {
                var caps = card.querySelector('[data-sub="' + w.kind + '"] [data-caps]');
                Object.keys(w.capture).forEach(function (n) { caps.appendChild(captureRow(n, w.capture[n], w.kind === 'page')); });
            }
            (st.fills || []).forEach(function (f) { card.querySelector('[data-fills]').appendChild(fillRow(f)); });
            (st.cleanup || []).forEach(function (c) { card.querySelector('[data-cleanups]').appendChild(cleanupRow(c)); });
            showSub(card);
            return card;
        }

        function showSub(card) {
            var kind = card.querySelector('[data-f="kind"]').value;
            card.querySelectorAll('[data-sub]').forEach(function (s) { s.hidden = s.getAttribute('data-sub') !== kind; });
        }

        function renumber() {
            list.querySelectorAll('.iris-tut-step').forEach(function (c, i) { c.querySelector('.iris-tut-step-n').textContent = String(i + 1); });
        }

        function lines(text) {
            return String(text || '').split('\n').map(function (l) { return l.trim(); }).filter(Boolean);
        }

        function collect() {
            var steps = [];
            list.querySelectorAll('.iris-tut-step').forEach(function (card) {
                var v = function (f) { var el = card.querySelector('[data-f="' + f + '"]'); return el ? el.value : ''; };
                var st = {title: v('title').trim(), body: v('body')};
                var anchors = lines(v('anchor'));
                if (anchors.length) { st.anchor = anchors; }
                if (v('goto').trim()) { st.goTo = v('goto').trim(); }
                var kind = v('kind');
                if (kind === 'element') { st.waitFor = {kind: 'element', anchor: lines(v('w-anchor'))}; }
                else if (kind === 'page') { st.waitFor = {kind: 'page', path: v('w-page').trim()}; }
                else if (kind === 'request') { st.waitFor = {kind: 'request', method: v('w-method'), path: v('w-path').trim()}; }
                if (st.waitFor && kind !== 'element') {
                    var cap = {};
                    card.querySelectorAll('[data-sub="' + kind + '"] [data-capture]').forEach(function (row) {
                        var n = row.querySelector('[data-f="cap-name"]').value.trim();
                        var s = row.querySelector('[data-f="cap-src"]').value.trim();
                        if (n || s) { cap[n] = s; }
                    });
                    if (Object.keys(cap).length) { st.waitFor.capture = cap; }
                }
                var fills = [];
                card.querySelectorAll('[data-fill]').forEach(function (row) {
                    var f = {label: row.querySelector('[data-f="fill-label"]').value, anchor: row.querySelector('[data-f="fill-anchor"]').value,
                             value: row.querySelector('[data-f="fill-value"]').value};
                    if (f.label || f.anchor || f.value) { fills.push(f); }
                });
                if (fills.length) { st.fills = fills; }
                var cl = [];
                card.querySelectorAll('[data-cleanup]').forEach(function (row) {
                    cl.push({kind: row.querySelector('[data-f="cl-kind"]').value, var: row.querySelector('[data-f="cl-var"]').value.trim()});
                });
                if (cl.length) { st.cleanup = cl; }
                steps.push(st);
            });
            return {format: vocab.format, title: $('#iris-tut-f-title').value, summary: $('#iris-tut-f-summary').value,
                    duration: $('#iris-tut-f-duration').value, audience: $('#iris-tut-f-audience').value, steps: steps};
        }

        function drawHeader() {
            var c = S.content;
            $('#iris-tut-ed-name').textContent = S.ref ? (c.title || 'Tutorial') : 'New tutorial';
            $('#iris-tut-published').checked = !!S.published;
            var note = $('#iris-tut-ed-note');
            if (S.kind === 'builtin') {
                note.hidden = false;
                note.textContent = S.edited
                    ? 'Your version of a built-in tutorial: it replaces the shipped one for everyone while published, and hides the tutorial while not. Restore brings the shipped version back.'
                    : 'The version shipped with IRIS. Saving creates your version, which replaces it for everyone.';
            } else {
                note.hidden = true;
            }
            root.querySelector('[data-tut-act="restore"]').hidden = !(S.kind === 'builtin' && S.edited);
            root.querySelector('[data-tut-act="delete"]').hidden = !(S.kind === 'team' && S.ref);
        }

        function draw() {
            var c = S.content;
            $('#iris-tut-f-title').value = c.title || '';
            $('#iris-tut-f-summary').value = c.summary || '';
            $('#iris-tut-f-duration').value = c.duration || '';
            $('#iris-tut-f-audience').value = c.audience || 'everyone';
            list.innerHTML = '';
            (c.steps || []).forEach(function (st) { list.appendChild(stepCard(st)); });
            renumber();
            drawHeader();
        }

        function save() {
            var content = collect();
            var published = $('#iris-tut-published').checked;
            var url = S.ref ? API + '/manage/tutorials/' + encodeURIComponent(S.ref) + '/save' : API + '/manage/tutorials';
            return postJson(root, url, {content: content, published: published}).then(function (res) {
                if ((res.status === 200 || res.status === 201) && res.data) {
                    showIssues(root, null);
                    dirty = false;
                    var created = !S.ref;
                    S = res.data;
                    if (created) { window.location.replace('/manage/tutorials/' + encodeURIComponent(S.ref)); return; }
                    drawHeader();
                    toast(root, 'Saved.');
                } else {
                    showIssues(root, message(res), issuesOf(res));
                }
            });
        }

        function exportFile() {
            postJson(root, API + '/manage/tutorials/validate', {content: collect()}).then(function (res) {
                var d = res.data;
                if (res.status !== 200 || !d) { showIssues(root, message(res), []); return; }
                if (!d.valid) { showIssues(root, 'Fix these first:', d.issues); return; }
                showIssues(root, null);
                var blob = new Blob([JSON.stringify(d.content, null, 2) + '\n'], {type: 'application/json'});
                var a = document.createElement('a');
                var slug = (d.content.title || 'tutorial').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'tutorial';
                a.href = URL.createObjectURL(blob);
                a.download = slug + '.tutorial.json';
                document.body.appendChild(a);
                a.click();
                window.setTimeout(function () { URL.revokeObjectURL(a.href); a.parentNode.removeChild(a); }, 0);
            });
        }

        root.addEventListener('click', function (e) {
            var a = e.target.closest('[data-tut-act]');
            if (a) {
                var act = a.getAttribute('data-tut-act');
                if (act === 'save') { save(); }
                else if (act === 'try') { startPreview(root, collect()); }
                else if (act === 'export') { exportFile(); }
                else if (act === 'add-step') {
                    if (list.children.length >= vocab.limits.steps) { toast(root, 'At most ' + vocab.limits.steps + ' steps.'); return; }
                    var card = stepCard({title: '', body: ''});
                    list.appendChild(card);
                    renumber();
                    dirty = true;
                    card.querySelector('[data-f="title"]').focus();
                } else if (act === 'restore') {
                    if (!window.confirm('Drop your version and bring back the tutorial shipped with IRIS?')) { return; }
                    postJson(root, API + '/manage/tutorials/' + encodeURIComponent(S.ref) + '/delete').then(function (res) {
                        if (res.status === 200) { dirty = false; window.location.reload(); } else { toast(root, message(res)); }
                    });
                } else if (act === 'delete') {
                    if (!window.confirm('Delete this tutorial for everyone? This cannot be undone.')) { return; }
                    postJson(root, API + '/manage/tutorials/' + encodeURIComponent(S.ref) + '/delete').then(function (res) {
                        if (res.status === 200) { dirty = false; window.location.href = '/manage/tutorials'; } else { toast(root, message(res)); }
                    });
                }
                return;
            }
            var b = e.target.closest('[data-ed]');
            if (!b) { return; }
            var card2 = b.closest('.iris-tut-step');
            var ed = b.getAttribute('data-ed');
            dirty = true;
            if (ed === 'rm-step') {
                if (!window.confirm('Delete this step?')) { return; }
                card2.parentNode.removeChild(card2); renumber();
            } else if (ed === 'up' && card2.previousElementSibling) {
                list.insertBefore(card2, card2.previousElementSibling); renumber();
            } else if (ed === 'down' && card2.nextElementSibling) {
                list.insertBefore(card2.nextElementSibling, card2); renumber();
            } else if (ed === 'rm-row') {
                var row = b.closest('.iris-tut-sub-row');
                row.parentNode.removeChild(row);
            } else if (ed === 'add-cap') {
                var sub = b.closest('[data-sub]');
                sub.querySelector('[data-caps]').appendChild(captureRow('', '', sub.getAttribute('data-sub') === 'page'));
            } else if (ed === 'add-fill') {
                card2.querySelector('[data-fills]').appendChild(fillRow(null));
            } else if (ed === 'add-cleanup') {
                card2.querySelector('[data-cleanups]').appendChild(cleanupRow(null));
            }
        });
        root.addEventListener('change', function (e) {
            dirty = true;
            if (e.target.matches('[data-f="kind"]')) { showSub(e.target.closest('.iris-tut-step')); }
        });
        root.addEventListener('input', function () { dirty = true; });
        window.addEventListener('beforeunload', function (e) {
            if (dirty) { e.preventDefault(); e.returnValue = ''; }
        });

        draw();
    }

    window.IrisTutorialPages = {mountList: mountList, mountManage: mountManage, mountEditor: mountEditor};
})();

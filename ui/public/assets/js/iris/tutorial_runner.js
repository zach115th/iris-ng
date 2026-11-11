/*  iris-ng tutorials (2026-11-10): the runner, on every page with a nav (includes/tutorial_assets.html, in <head>).

    The running tutorial is embedded in the page (window.IrisTutorialState = {looked, run, csrf}; run null = none
    running, looked false = the read failed and the runner fetches it). The pages are full page loads, so the run
    lives on the server and every completed step is reported (POST /api/v2/tutorials/run/step, `keepalive` so a
    navigation right after a save does not cancel it, plus a sessionStorage copy replayed on the next page).

    A step is done when (waitFor): the learner clicks Next (none) | an element is visible (element) | the page is
    open (page) | the page's own request succeeded (request: XMLHttpRequest and fetch are observed here; the reply's
    fields named in `capture` become {values} for the later steps). Anchors are data-tour names or CSS selectors;
    the first visible one is highlighted. Everything shown is escaped: a body knows **bold**, `code` and {values}.

    window.IrisTutorial = {start(ref), resume(ref), use(run), stop(), current()}; the pages listen for the
    'iris-tutorial-changed' event on document. */
(function () {
    'use strict';
    if (window.IrisTutorial) { return; }

    var NAME_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;
    var VAR_REF = /\{([A-Za-z][A-Za-z0-9_]{0,31})\}/g;
    var PENDING = 'irisTutPending';
    var WHAT = {'case': 'case', 'war_room': 'war room', 'vulnerability': 'catalogue vulnerability'};
    var CLEANUP_KIND = {'case': 'case', 'war_room': 'war_room', 'vulnerability': 'vulnerability'};
    var API = '/api/v2/tutorials';

    var boot = window.IrisTutorialState || {looked: false, run: null, csrf: ''};
    var csrf = boot.csrf || '';
    var nativeFetch = typeof window.fetch === 'function' ? window.fetch.bind(window) : null;

    var R = null;           // the run (business.tutorials.run_payload) + local fields: armed
    var ui = null;          // {root, panel, pill, ring}
    var target = null;      // the highlighted element
    var scrolledFor = -1;   // the step whose highlight was scrolled into view
    var ticker = null;
    var sendSeq = 0;

    // ------------------------------------------------------------------ helpers

    function esc(s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function cur() { return R && R.steps ? R.steps[R.step] || null : null; }

    function subst(text, enc) {
        return String(text == null ? '' : text).replace(VAR_REF, function (whole, name) {
            if (!R || !R.vars || !Object.prototype.hasOwnProperty.call(R.vars, name)) { return whole; }
            return enc(String(R.vars[name]));
        });
    }

    function plain(v) { return v; }
    function selectorSafe(v) { return v.replace(/[^A-Za-z0-9_\-.:]/g, ''); }

    function inline(s) {
        var parts = s.split('`');
        if (parts.length % 2 === 0) { parts = [s]; }
        return parts.map(function (p, i) {
            if (i % 2) { return '<code>' + esc(p) + '</code>'; }
            return esc(p).replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>');
        }).join('');
    }

    function md(text) {
        var t = subst(text, plain).trim();
        if (!t) { return ''; }
        return t.split(/\n{2,}/).map(function (p) { return '<p>' + inline(p).replace(/\n/g, '<br>') + '</p>'; }).join('');
    }

    function visible(el) {
        if (!el || !el.getClientRects || !el.getClientRects().length) { return false; }
        var r = el.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) { return false; }
        var cs = window.getComputedStyle(el);
        return cs.visibility !== 'hidden' && cs.display !== 'none';
    }

    function asList(a) { return a == null ? [] : (Array.isArray(a) ? a : [a]); }

    function resolve(anchors) {
        var list = asList(anchors);
        for (var i = 0; i < list.length; i++) {
            var a = subst(list[i], selectorSafe).trim();
            if (!a) { continue; }
            var sel = NAME_RE.test(a) ? '[data-tour="' + a + '"]' : a;
            var found;
            try { found = document.querySelectorAll(sel); } catch (e) { continue; }
            for (var j = 0; j < found.length; j++) {
                if (ui && ui.root.contains(found[j])) { continue; }
                if (visible(found[j])) { return found[j]; }
            }
        }
        return null;
    }

    function splitPath(p) {
        var q = p.indexOf('?');
        return {path: q === -1 ? p : p.slice(0, q), query: q === -1 ? '' : p.slice(q + 1)};
    }

    function segmentsMatch(pattern, actual) {
        var a = pattern.replace(/\/+$/, '').split('/');
        var b = actual.replace(/\/+$/, '').split('/');
        if (a.length !== b.length) { return false; }
        for (var i = 0; i < a.length; i++) {
            if (a[i] !== '*' && a[i] !== b[i]) { return false; }
        }
        return true;
    }

    function pageMatches(pattern) {
        var p = splitPath(subst(pattern, encodeURIComponent));
        if (!segmentsMatch(p.path, window.location.pathname)) { return false; }
        if (!p.query) { return true; }
        var have = new URLSearchParams(window.location.search);
        var want = new URLSearchParams(p.query);
        var ok = true;
        want.forEach(function (value, key) {
            var actual = have.get(key);
            if (actual === null || (value !== '*' && actual !== value)) { ok = false; }
        });
        return ok;
    }

    function dig(data, path) {
        var parts = String(path).split('.');
        for (var i = 0; i < parts.length; i++) {
            if (data == null || typeof data !== 'object') { return undefined; }
            data = Array.isArray(data) ? data[parseInt(parts[i], 10)] : data[parts[i]];
        }
        return data;
    }

    function capturedValue(v) {
        if (typeof v === 'number' && isFinite(v)) { return v; }
        if (typeof v === 'string' && v.trim() && v.length <= 200) { return v.trim(); }
        return undefined;
    }

    // ------------------------------------------------------------------ the page's own requests

    function observed(method, url, status, body) {
        var st = cur();
        var w = st && st.waitFor;
        if (!w || w.kind !== 'request' || !R || R.busy) { return; }
        if (!(status >= 200 && status < 300) || !requestMatches(w, method, url)) { return; }
        var vars = {};
        var names = Object.keys(w.capture || {});
        if (names.length) {
            var data = body;
            if (typeof data === 'string') { try { data = JSON.parse(data); } catch (e) { data = null; } }
            for (var i = 0; i < names.length; i++) {
                var v = capturedValue(dig(data, w.capture[names[i]]));
                if (v === undefined) {
                    if (window.console) { console.warn('Tutorial: the reply has no ' + w.capture[names[i]]); }
                    return;
                }
                vars[names[i]] = v;
            }
        }
        complete(vars);
    }

    function requestMatches(w, method, url) {
        if (String(method || 'GET').toUpperCase() !== (w.method || 'POST')) { return false; }
        var u;
        try { u = new URL(url, document.baseURI); } catch (e) { return false; }
        if (u.origin !== window.location.origin) { return false; }
        return segmentsMatch(splitPath(subst(w.path, encodeURIComponent)).path, u.pathname);
    }

    function wantsRequest(method, url) {
        var st = cur();
        return !!(st && st.waitFor && st.waitFor.kind === 'request' && requestMatches(st.waitFor, method, url));
    }

    (function hookXhr() {
        var X = window.XMLHttpRequest;
        if (!X || !X.prototype) { return; }
        var open = X.prototype.open;
        var send = X.prototype.send;
        X.prototype.open = function (method, url) {
            try { this.__irisTut = {method: String(method || 'GET').toUpperCase(), url: String(url)}; } catch (e) { /* ignore */ }
            return open.apply(this, arguments);
        };
        X.prototype.send = function () {
            var xhr = this;
            if (xhr.__irisTut && !xhr.__irisTutHooked) {
                xhr.__irisTutHooked = true;
                xhr.addEventListener('loadend', function () {
                    var info = xhr.__irisTut;
                    if (!R || !wantsRequest(info.method, info.url)) { return; }
                    var text = null;
                    try {
                        if (xhr.responseType === '' || xhr.responseType === 'text') { text = xhr.responseText; }
                        else if (xhr.responseType === 'json') { text = xhr.response; }
                    } catch (e) { text = null; }
                    observed(info.method, info.url, xhr.status, text);
                });
            }
            return send.apply(this, arguments);
        };
    })();

    if (nativeFetch) {
        window.fetch = function (input, init) {
            var p = nativeFetch.apply(window, arguments);
            try {
                var method = (init && init.method) || (input && typeof input === 'object' && input.method) || 'GET';
                var url = typeof input === 'string' ? input : (input && input.url) || String(input);
                if (R && wantsRequest(method, url)) {
                    p.then(function (resp) {
                        resp.clone().text().then(function (t) { observed(method, url, resp.status, t); }, function () {});
                    }, function () {});
                }
            } catch (e) { /* never break the page's request */ }
            return p;
        };
    }

    // ------------------------------------------------------------------ the server

    function post(path, body) {
        body = body || {};
        body.csrf_token = csrf;
        var send = nativeFetch || window.fetch;
        return send(API + path, {method: 'POST', credentials: 'same-origin', keepalive: true,
                                 headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})
            .then(function (r) {
                return r.json().catch(function () { return null; }).then(function (j) { return {status: r.status, data: j}; });
            });
    }

    function errorText(res) {
        var d = res && res.data;
        return (d && d.message) || ('The server answered ' + (res ? res.status : 'nothing'));
    }

    function readPending() {
        try { return JSON.parse(window.sessionStorage.getItem(PENDING) || 'null'); } catch (e) { return null; }
    }
    function writePending(v) {
        try {
            if (v) { window.sessionStorage.setItem(PENDING, JSON.stringify(v)); }
            else { window.sessionStorage.removeItem(PENDING); }
        } catch (e) { /* storage refused: the server copy is the only one */ }
    }

    function changed() {
        try { document.dispatchEvent(new CustomEvent('iris-tutorial-changed', {detail: {run: R}})); } catch (e) { /* old browser */ }
    }

    function adopt(run, keepLocal) {
        if (!run) { R = null; teardown(); changed(); return; }
        var armed = keepLocal && R && R.run === run.run && R.step === run.step ? R.armed : true;
        if (!keepLocal) { scrolledFor = -1; }
        R = run;
        R.armed = armed;
        render();
        changed();
    }

    function report(step, vars) {
        var seq = ++sendSeq;
        var runId = R.run;
        writePending({run: runId, step: step, vars: vars});
        post('/run/step', {run: runId, step: step, vars: vars}).then(function (res) {
            if (seq !== sendSeq) { return; }  // a newer report is on its way
            if (res.status === 200 && res.data) {
                writePending(null);
                if (R && R.run === res.data.run && R.step === res.data.step) {
                    R.cleanup = res.data.cleanup;
                    R.vars = res.data.vars;
                    renderCleanup();
                }
            } else if (res.status === 409) {
                writePending(null);
                refetch();
            } else {
                message(errorText(res));
            }
        }, function () { message('Your progress could not be saved; it will be retried on the next page.'); });
    }

    function refetch() {
        var get = nativeFetch || window.fetch;
        get(API + '/run', {credentials: 'same-origin'}).then(function (r) { return r.json(); })
            .then(function (j) { adopt(j && j.run ? j.run : null, false); }, function () { /* keep what we have */ });
    }

    // ------------------------------------------------------------------ moving through the steps

    function complete(vars) {
        if (!R || R.busy) { return; }
        var merged = {};
        Object.keys(R.vars || {}).forEach(function (k) { merged[k] = R.vars[k]; });
        Object.keys(vars || {}).forEach(function (k) { merged[k] = vars[k]; });
        R.vars = merged;
        if (R.step + 1 >= R.total) {
            report(R.step, vars || {});
            finish();
            return;
        }
        R.step += 1;
        R.armed = true;
        R.cleanup = null;
        // Report before drawing: drawing evaluates the new step, which may complete at once and report the next one;
        // reported after, this step's captured values went out under the later step's number.
        report(R.step, vars || {});
        render();
    }

    function back() {
        if (!R || R.step === 0) { return; }
        R.step -= 1;
        // A page or element step that is already satisfied must not complete again at once: it waits until its
        // condition has been false (the learner left the page, closed the form) - otherwise Back could never stop.
        var w = (cur() || {}).waitFor;
        R.armed = !(w && (w.kind === 'page' || w.kind === 'element'));
        R.cleanup = null;
        report(R.step, {});
        render();
    }

    function finish() {
        if (!R) { return; }
        R.busy = true;
        var runId = R.run;
        post('/run/finish', {run: runId}).then(function (res) {
            if (res.status === 200) {
                var preview = R && R.preview;
                writePending(null);
                R = null;
                teardown();
                toast(preview ? 'Preview finished.' : 'Tutorial complete. Well done!');
                changed();
            } else if (res.status === 409) {
                refetch();
            } else {
                if (R) { R.busy = false; }
                message(errorText(res));
            }
        }, function () { if (R) { R.busy = false; } message('The server could not be reached.'); });
    }

    function stop() {
        if (!R) { return; }
        var runId = R.run;
        post('/run/stop', {run: runId}).then(function () { writePending(null); R = null; teardown(); changed(); },
            function () { message('The server could not be reached.'); });
    }

    function setMinimized(flag) {
        if (!R) { return; }
        R.minimized = flag;
        render();
        post('/run/minimize', {run: R.run, minimized: flag});
    }

    function begin(path) {
        return post(path, {}).then(function (res) {
            if (res.status === 200 && res.data) {
                writePending(null);
                adopt(res.data, false);
                return {ok: true, run: res.data};
            }
            return {ok: false, message: errorText(res)};
        }, function () { return {ok: false, message: 'The server could not be reached.'}; });
    }

    function cleanup(kind) {
        if (!R) { return; }
        var entry = (R.cleanup || []).filter(function (c) { return c.kind === kind; })[0];
        if (!entry || !entry.available) { return; }
        var what = WHAT[kind] + ' #' + entry.id;
        if (!window.confirm('Delete ' + what + ' and everything in it? This cannot be undone.')) { return; }
        post('/run/cleanup', {run: R.run, kind: kind}).then(function (res) {
            if (res.status === 200 && res.data) { adopt(res.data, true); toast(what.charAt(0).toUpperCase() + what.slice(1) + ' deleted.'); }
            else if (res.status === 409) { refetch(); }
            else { message(errorText(res)); }
        }, function () { message('The server could not be reached.'); });
    }

    // ------------------------------------------------------------------ fill buttons

    function setValue(el, value) {
        var aceEl = el.classList && el.classList.contains('ace_editor') ? el : (el.querySelector ? el.querySelector('.ace_editor') : null);
        if (aceEl && window.ace) {
            try { window.ace.edit(aceEl).setValue(value, 1); return true; } catch (e) { /* not an editor after all */ }
        }
        var t = el;
        if (!/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) {
            t = el.querySelector('input:not([type="hidden"]), textarea, select') || el;
        }
        if (t.tagName === 'SELECT') {
            var want = String(value).trim().toLowerCase();
            var opt = null;
            for (var i = 0; i < t.options.length; i++) {
                if (t.options[i].value === value) { opt = t.options[i]; break; }
            }
            if (!opt) {
                for (var k = 0; k < t.options.length; k++) {
                    if (t.options[k].text.trim().toLowerCase() === want) { opt = t.options[k]; break; }
                }
            }
            if (!opt) { return false; }
            t.value = opt.value;
            opt.selected = true;
            // bootstrap-select redraws its button on this change event (no 'refresh' call needed: the probe shows it).
            t.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
        }
        if (t.tagName === 'INPUT' && (t.type === 'checkbox' || t.type === 'radio')) {
            t.checked = /^(1|true|yes|on)$/i.test(String(value).trim());
            t.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
        }
        if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA') {
            var proto = t.tagName === 'INPUT' ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype;
            var desc = Object.getOwnPropertyDescriptor(proto, 'value');
            if (desc && desc.set) { desc.set.call(t, value); } else { t.value = value; }
            t.dispatchEvent(new Event('input', {bubbles: true}));
            t.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
        }
        if (t.isContentEditable) {
            t.textContent = value;
            t.dispatchEvent(new Event('input', {bubbles: true}));
            return true;
        }
        return false;
    }

    function fill(index) {
        var st = cur();
        var f = st && st.fills && st.fills[index];
        if (!f) { return; }
        var el = resolve([f.anchor]);
        if (!el) { message('That field is not on the page yet: open the form first.'); return; }
        if (!setValue(el, subst(f.value, plain))) { message('That value could not be filled in; type it instead.'); return; }
        message('');
    }

    // ------------------------------------------------------------------ drawing

    var ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z"/><path d="M22 10v6"/><path d="M6 12.5V16a6 3 0 0 0 12 0v-3.5"/></svg>';
    var WAND = '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m21.64 3.64-1.28-1.28a1.21 1.21 0 0 0-1.72 0L2.36 18.64a1.21 1.21 0 0 0 0 1.72l1.28 1.28a1.2 1.2 0 0 0 1.72 0L21.64 5.36a1.2 1.2 0 0 0 0-1.72"/><path d="m14 7 3 3"/><path d="M5 6v4"/><path d="M19 14v4"/><path d="M10 2v2"/><path d="M7 8H3"/><path d="M21 16h-4"/><path d="M11 3H9"/></svg>';

    function ensureUi() {
        if (ui) { return ui; }
        var root = document.createElement('div');
        root.className = 'iris-tut-runner';
        root.id = 'iris-tut-runner';
        root.innerHTML = '<div class="iris-tut-ring" aria-hidden="true"></div>' +
            '<section class="iris-tut-panel" role="dialog" aria-label="Tutorial" hidden></section>' +
            '<button type="button" class="iris-tut-pill" hidden></button>';
        document.body.appendChild(root);
        ui = {root: root, ring: root.querySelector('.iris-tut-ring'), panel: root.querySelector('.iris-tut-panel'),
              pill: root.querySelector('.iris-tut-pill')};
        // Keep the focus where it is: a Bootstrap modal takes it back from anything outside it, and a Fill button
        // must not blur the field it fills.
        root.addEventListener('mousedown', function (e) {
            if (e.target.closest('button')) { e.preventDefault(); }
        });
        root.addEventListener('click', onClick);
        window.addEventListener('scroll', place, true);
        window.addEventListener('resize', place);
        return ui;
    }

    function teardown() {
        if (ticker) { window.clearInterval(ticker); ticker = null; }
        target = null;
        if (ui) {
            window.removeEventListener('scroll', place, true);
            window.removeEventListener('resize', place);
            ui.root.parentNode && ui.root.parentNode.removeChild(ui.root);
            ui = null;
        }
    }

    function onClick(e) {
        var b = e.target.closest('[data-tut]');
        if (!b || !R) { return; }
        var act = b.getAttribute('data-tut');
        if (act === 'next') { e.preventDefault(); complete({}); }
        else if (act === 'skip') { e.preventDefault(); complete({}); }
        else if (act === 'back') { e.preventDefault(); back(); }
        else if (act === 'finish') { e.preventDefault(); finish(); }
        else if (act === 'close') { e.preventDefault(); stop(); }
        else if (act === 'min') { e.preventDefault(); setMinimized(true); }
        else if (act === 'max') { e.preventDefault(); setMinimized(false); }
        else if (act === 'fill') { e.preventDefault(); fill(parseInt(b.getAttribute('data-i'), 10)); }
        else if (act === 'cleanup') {
            e.preventDefault();
            // Re-derived from a constant table: the attribute is page text.
            var kind = CLEANUP_KIND[b.getAttribute('data-kind')];
            if (kind) { cleanup(kind); }
        }
    }

    function render() {
        if (!R || !R.steps || !R.total) { teardown(); return; }
        ensureUi();
        var st = cur();
        var label = esc(R.title) + ' · ' + (R.step + 1) + '/' + R.total;
        if (R.minimized) {
            ui.panel.hidden = true;
            ui.pill.hidden = false;
            ui.pill.setAttribute('data-tut', 'max');
            ui.pill.innerHTML = ICON + '<span>' + label + '</span>';
            ui.pill.title = 'Show the tutorial';
        } else {
            ui.pill.hidden = true;
            ui.panel.hidden = false;
            ui.panel.innerHTML = panelHtml(st, label);
            renderCleanup();
        }
        tick();
        if (!ticker) { ticker = window.setInterval(tick, 150); }
    }

    function panelHtml(st, label) {
        var w = st.waitFor;
        var last = R.step === R.total - 1;
        var pct = Math.round(((R.step + 1) / R.total) * 100);
        var h = '<header class="iris-tut-p-head">' + ICON +
            '<span class="iris-tut-p-name">' + label + (R.preview ? ' <em>(preview)</em>' : '') + '</span>' +
            '<button type="button" class="iris-tut-icon" data-tut="min" title="Minimize" aria-label="Minimize the tutorial">' +
            '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m14 10 7-7"/><path d="M20 10h-6V4"/><path d="m3 21 7-7"/><path d="M4 14h6v6"/></svg></button>' +
            '<button type="button" class="iris-tut-icon" data-tut="close" title="Stop the tutorial" aria-label="Stop the tutorial">' +
            '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg></button>' +
            '</header>' +
            '<div class="iris-tut-p-bar" role="progressbar" aria-valuemin="1" aria-valuemax="' + R.total + '" aria-valuenow="' + (R.step + 1) + '"><span style="width:' + pct + '%"></span></div>' +
            '<div class="iris-tut-p-main" aria-live="polite">' +
            '<h3 class="iris-tut-p-title">' + esc(subst(st.title, plain)) + '</h3>' +
            '<div class="iris-tut-p-body">' + md(st.body) + '</div>';
        (st.fills || []).forEach(function (f, i) {
            h += '<div class="iris-tut-fill"><div class="iris-tut-fill-text"><span class="iris-tut-fill-label">' + esc(f.label) +
                '</span><code class="iris-tut-fill-value" title="' + esc(subst(f.value, plain)) + '">' + esc(subst(f.value, plain)) + '</code></div>' +
                '<button type="button" class="iris-tut-btn iris-tut-btn--ghost" data-tut="fill" data-i="' + i + '">' + WAND + ' Fill</button></div>';
        });
        h += '<div class="iris-tut-cleanup"></div><div class="iris-tut-msg" role="alert" hidden></div></div>';
        h += '<footer class="iris-tut-p-foot">';
        var go = goToHref(st);
        if (go && !pageMatches(st.goTo)) { h += '<a class="iris-tut-goto" href="' + esc(go) + '">Take me there</a>'; }
        h += '<span class="iris-tut-spacer"></span>';
        if (w) {
            h += '<span class="iris-tut-wait"><span class="iris-tut-dot" aria-hidden="true"></span>Waiting for you…</span>';
            if (!w.capture) { h += '<button type="button" class="iris-tut-link" data-tut="skip" title="Mark this step done">Skip</button>'; }
        }
        if (R.step > 0) { h += '<button type="button" class="iris-tut-btn iris-tut-btn--ghost" data-tut="back">Back</button>'; }
        if (!w) {
            h += last ? '<button type="button" class="iris-tut-btn" data-tut="finish">Finish</button>'
                      : '<button type="button" class="iris-tut-btn" data-tut="next">Next</button>';
        }
        h += '</footer>';
        return h;
    }

    function goToHref(st) {
        if (!st || !st.goTo) { return null; }
        var href = subst(st.goTo, encodeURIComponent);
        if (!/^\/(?![\/\\])/.test(href) || /\{[A-Za-z]/.test(href)) { return null; }
        return href;
    }

    function renderCleanup() {
        if (!ui || !R || R.minimized) { return; }
        var box = ui.panel.querySelector('.iris-tut-cleanup');
        if (!box) { return; }
        var st = cur();
        if (!st || !st.cleanup || !st.cleanup.length) { box.innerHTML = ''; return; }
        if (!R.cleanup) { box.innerHTML = '<p class="iris-tut-muted">Checking what can be deleted…</p>'; return; }
        box.innerHTML = R.cleanup.map(function (c) {
            var what = WHAT[c.kind] || 'item';
            if (c.available) {
                return '<button type="button" class="iris-tut-btn iris-tut-btn--danger" data-tut="cleanup" data-kind="' + esc(c.kind) + '">Delete ' + what + ' #' + esc(c.id) + '</button>';
            }
            return '<p class="iris-tut-muted">' + esc(c.reason || '') + '</p>';
        }).join('');
    }

    function message(text) {
        if (!ui) { return; }
        var m = ui.panel.querySelector('.iris-tut-msg');
        if (!m) { return; }
        m.textContent = text || '';
        m.hidden = !text;
    }

    function toast(text) {
        var t = document.createElement('div');
        t.className = 'iris-tut-toast-float';
        t.setAttribute('role', 'status');
        t.textContent = text;
        document.body.appendChild(t);
        window.setTimeout(function () { t.parentNode && t.parentNode.removeChild(t); }, 3500);
    }

    // What the learner sees for an element: a bootstrap-select picker hides its <select> behind its own button.
    function shown(el) {
        var p = el && el.tagName === 'SELECT' ? el.parentElement : null;
        return p && p.classList && p.classList.contains('bootstrap-select') ? p : el;
    }

    // The open modal <dialog>, if any: showModal() makes everything outside it inert and draws it in the top layer,
    // so the panel has to live inside it while it is open.
    function host() {
        var ds = document.querySelectorAll('dialog[open]');
        for (var i = ds.length - 1; i >= 0; i--) {
            var modal = true;
            try { modal = ds[i].matches(':modal'); } catch (e) { modal = true; }
            if (modal) { return ds[i]; }
        }
        return document.body;
    }

    // The panel sits bottom right, above dialogs - where a dialog's main button often is. When the highlighted
    // element is under the panel's corner, the panel moves to the bottom left (unless that corner covers it too).
    function dodge(r) {
        var box = R && R.minimized ? ui.pill : ui.panel;
        var w = box.offsetWidth || 384;
        var h = box.offsetHeight || 200;
        var vw = window.innerWidth;
        var vh = window.innerHeight;
        var m = 16 + 8;
        var hitsRight = r.right > vw - m - w && r.bottom > vh - m - h;
        var hitsLeft = r.left < m + w && r.bottom > vh - m - h;
        ui.root.classList.toggle('iris-tut-runner--left', hitsRight && !hitsLeft);
    }

    function place() {
        if (!ui) { return; }
        if (!target || !document.contains(target) || !visible(target) || R && R.minimized) {
            ui.ring.style.display = 'none';
            // Nothing to keep clear: back to the usual corner (the page's own toasts appear bottom left).
            ui.root.classList.remove('iris-tut-runner--left');
            return;
        }
        var r = shown(target).getBoundingClientRect();
        dodge(r);
        var s = ui.ring.style;
        s.display = 'block';
        s.top = (r.top - 4) + 'px';
        s.left = (r.left - 4) + 'px';
        s.width = (r.width + 8) + 'px';
        s.height = (r.height + 8) + 'px';
    }

    function tick() {
        if (!R || !ui) { return; }
        var st = cur();
        if (!st) { return; }
        var h = host();
        if (ui.root.parentNode !== h) { h.appendChild(ui.root); }
        target = st.anchor ? resolve(st.anchor) : null;
        if (target && scrolledFor !== R.step && !R.minimized) {
            scrolledFor = R.step;
            try { target.scrollIntoView({block: 'nearest', inline: 'nearest'}); } catch (e) { /* old browser */ }
        }
        place();
        var w = st.waitFor;
        if (!w || R.busy || w.kind === 'request') { return; }
        var met = false;
        var vars = {};
        if (w.kind === 'element') {
            met = !!resolve(w.anchor);
        } else if (w.kind === 'page') {
            met = pageMatches(w.path);
            if (met && w.capture) {
                var q = new URLSearchParams(window.location.search);
                Object.keys(w.capture).forEach(function (name) {
                    var v = capturedValue(q.get(w.capture[name]));
                    if (v === undefined) { met = false; } else { vars[name] = /^[0-9]{1,12}$/.test(v) ? parseInt(v, 10) : v; }
                });
            }
        }
        if (!met) { R.armed = true; return; }
        if (R.armed) { complete(vars); }
    }

    // ------------------------------------------------------------------ start

    function init(run) {
        if (!run) { return; }
        var pending = readPending();
        if (pending && pending.run === run.run && typeof pending.step === 'number' && pending.step > run.step &&
            pending.step < run.total) {
            run.step = pending.step;
            run.vars = run.vars || {};
            Object.keys(pending.vars || {}).forEach(function (k) { run.vars[k] = pending.vars[k]; });
            run.cleanup = null;
            R = run;
            R.armed = true;
            report(pending.step, pending.vars || {});
        } else {
            writePending(null);
            R = run;
            R.armed = true;
        }
        render();
    }

    function onReady(fn) {
        if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', fn); } else { fn(); }
    }

    onReady(function () {
        if (boot.looked) { init(boot.run); }
        else { refetch(); }
    });

    window.IrisTutorial = {
        start: function (ref) { return begin('/' + encodeURIComponent(ref) + '/start'); },
        resume: function (ref) { return begin('/' + encodeURIComponent(ref) + '/resume'); },
        use: function (run) { writePending(null); adopt(run, false); },
        stop: stop,
        current: function () { return R; },
        csrf: function () { return csrf; }
    };
})();

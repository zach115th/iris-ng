/* @-mention palette + mention highlighting for every comment surface (#120).
 *
 * The war-room composer had an @-palette (members + teams); the comment boxes
 * on the case pages, the alerts page and the alert-cluster page had none, so a
 * mention had to be typed as the exact LOGIN by hand — and the server resolves
 * mentions against User.user (the login), never the display name, so a typed
 * display name silently notified nobody. This module generalises the war-room
 * algorithm (same token detector: walk back to the last WHITESPACE, not the
 * last '@', because logins can be email-shaped) over three host kinds:
 *
 *   <input> / <textarea>  — any element carrying data-iris-mention="case|users"
 *                           is attached lazily on its first focus (the v3 side
 *                           panels re-create their input on every render);
 *   ACE editor            — attachAce(editor, opts) for the legacy comment modal.
 *
 * Candidates:
 *   "case"  -> GET /case/users/list?cid=   (active users with case access,
 *              deny_all rows dropped — the exact set notify_mentions allows);
 *   "users" -> GET /manage/users/restricted/list (alerts / clusters: the
 *              server applies the client-access filter itself).
 *
 * highlightHtml(html, logins) wraps @login tokens that RESOLVE to a known
 * login in <span class="iris-mention">, walking text nodes only (never inside
 * <a>, <code>, <pre>) and trimming trailing .-_@ the way scan_mentions does.
 * Unresolved tokens stay plain — a plain "@name" in a rendered comment means
 * exactly what it means server-side: nobody was notified.
 *
 * import-free by design (ui/public/ — no bundler pass, no tree-shaking). */

(function () {
    'use strict';

    var TOKEN_RE = /(^|[^A-Za-z0-9._@-])@([A-Za-z0-9][A-Za-z0-9._@-]{0,127})/g;
    var SKIP_TAGS = {A: 1, CODE: 1, PRE: 1, SCRIPT: 1, STYLE: 1, TEXTAREA: 1};

    var sources = {};          /* key -> {items: [], logins: Set, loaded, promise} */
    var active = null;         /* the one open palette state */
    var pop = null;

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function cidFromUrl() {
        try {
            return new URLSearchParams(window.location.search).get('cid');
        } catch (e) { return null; }
    }

    function ensureStyle() {
        if (document.getElementById('iris-mention-style')) return;
        var st = document.createElement('style');
        st.id = 'iris-mention-style';
        st.textContent =
            '.iris-mention-pop{position:fixed;z-index:2100;display:none;' +
            'border:1px solid rgba(139,92,246,0.35);border-radius:8px;' +
            'background:#1a1a22;padding:6px 10px;max-height:220px;' +
            'overflow-y:auto;font-size:0.78rem;color:#e8e8ee;' +
            'box-shadow:0 8px 24px rgba(0,0,0,0.45);}' +
            '.iris-mention-pop .iris-mention-opt{padding:2px 4px;cursor:pointer;' +
            'border-radius:4px;white-space:nowrap;overflow:hidden;' +
            'text-overflow:ellipsis;}' +
            '.iris-mention-pop .iris-mention-opt:hover{background:rgba(139,92,246,0.12);}' +
            '.iris-mention-pop .iris-mention-opt.active{background:rgba(139,92,246,0.22);}' +
            '.iris-mention-pop code{color:#c4b5fd;background:transparent;padding:0;}' +
            '.iris-mention{color:#c4b5fd;background:rgba(139,92,246,0.14);' +
            'border-radius:4px;padding:0 3px;font-weight:600;}';
        document.head.appendChild(st);
    }

    function ensurePop() {
        if (pop) return pop;
        ensureStyle();
        pop = document.createElement('div');
        pop.id = 'iris-mention-pop';
        pop.className = 'iris-mention-pop';
        pop.addEventListener('mousedown', function (e) {
            /* keep the host focused — blur would close the palette before
               the click lands */
            e.preventDefault();
        });
        pop.addEventListener('click', function (e) {
            var opt = e.target.closest('.iris-mention-opt');
            if (!opt || !active) return;
            complete(active, parseInt(opt.getAttribute('data-i'), 10));
        });
        document.body.appendChild(pop);
        window.addEventListener('scroll', function () { close(); }, true);
        window.addEventListener('resize', function () { close(); });
        return pop;
    }

    /* ---- candidate sources ---------------------------------------------- */

    function sourceKey(kind, cid) {
        return kind === 'case' ? 'case:' + (cid || cidFromUrl() || '') : 'users';
    }

    function fetchJson(url) {
        return fetch(url, {credentials: 'same-origin',
                           headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.ok ? r.json() : null; })
            .catch(function () { return null; });
    }

    function load(kind, cid) {
        var key = sourceKey(kind, cid);
        var src = sources[key];
        if (src) return src.promise;
        src = sources[key] = {items: [], logins: new Set(), loaded: false};
        var url;
        if (kind === 'case') {
            var c = cid || cidFromUrl();
            if (!c) {
                src.loaded = true;
                src.promise = Promise.resolve(src.items);
                return src.promise;
            }
            url = '/case/users/list?cid=' + encodeURIComponent(c);
        } else {
            url = '/manage/users/restricted/list' +
                (cidFromUrl() ? '?cid=' + encodeURIComponent(cidFromUrl()) : '');
        }
        src.promise = fetchJson(url).then(function (j) {
            var rows = (j && j.data) || [];
            rows.forEach(function (u) {
                if (!u || !u.user_login || u.user_active === false) return;
                /* deny_all = 0x1: an effective-access row that DENIES the
                   case — the server drops these, so must the palette */
                if (kind === 'case' && (u.user_access_level & 1)) return;
                src.items.push({login: u.user_login, label: u.user_name || '',
                                kind: 'user'});
                src.logins.add(String(u.user_login).toLowerCase());
            });
            src.loaded = true;
            try {
                document.dispatchEvent(new CustomEvent('iris-mentions-loaded',
                    {detail: {source: key}}));
            } catch (e) { /* old engines */ }
            return src.items;
        });
        return src.promise;
    }

    function candidatesOf(state) {
        if (typeof state.candidates === 'function') return state.candidates() || [];
        if (Array.isArray(state.candidates)) return state.candidates;
        var src = sources[sourceKey(state.kind, state.cid)];
        if (!src) { load(state.kind, state.cid); return []; }
        return src.items;
    }

    function knownLogins(extra) {
        var out = new Set();
        Object.keys(sources).forEach(function (k) {
            sources[k].logins.forEach(function (l) { out.add(l); });
        });
        (extra || []).forEach(function (l) {
            if (l) out.add(String(l).toLowerCase());
        });
        return out;
    }

    /* ---- token detection (shared with the war room's rules) ------------- */

    function ctxOf(before) {
        var ws = Math.max(before.lastIndexOf(' '), before.lastIndexOf('\n'),
                          before.lastIndexOf('\t'));
        var token = before.slice(ws + 1);
        if (token.charAt(0) !== '@') return null;
        return {at: ws + 1, frag: token.slice(1)};
    }

    function rank(items, q) {
        var hits = items.filter(function (it) {
            return it.login.toLowerCase().indexOf(q) !== -1
                || (it.label || '').toLowerCase().indexOf(q) !== -1;
        });
        hits.sort(function (a, b) {
            var ap = a.login.toLowerCase().indexOf(q) === 0 ? 0 : 1;
            var bp = b.login.toLowerCase().indexOf(q) === 0 ? 0 : 1;
            return (ap - bp) || a.login.localeCompare(b.login);
        });
        return hits.slice(0, 8);
    }

    /* ---- palette state machine ----------------------------------------- */

    function render() {
        var p = ensurePop();
        if (!active || !active.open || !active.items.length) {
            if (active) active.open = false;
            p.style.display = 'none';
            if (active && active.onClose) active.onClose();
            return;
        }
        p.innerHTML = active.items.map(function (it, i) {
            return '<div class="iris-mention-opt' + (i === active.idx ? ' active' : '')
                + '" data-i="' + i + '"><code>@' + esc(it.login) + '</code> '
                + '<span class="text-muted">' + esc(it.label || '')
                + (it.kind === 'team' ? ' &middot; team' : '') + '</span></div>';
        }).join('');
        var r = active.rect();
        p.style.left = Math.max(4, r.left) + 'px';
        p.style.width = Math.max(180, Math.min(r.width, window.innerWidth - 8)) + 'px';
        p.style.bottom = Math.max(4, window.innerHeight - r.top + 4) + 'px';
        p.style.top = '';
        p.style.display = '';
        if (active.onOpen) active.onOpen();
    }

    function update(state) {
        var ctx = state.ctx();
        if (!ctx) {
            if (active === state) { state.open = false; render(); }
            return;
        }
        var q = ctx.frag.toLowerCase();
        state.items = rank(candidatesOf(state), q);
        state.idx = 0;
        state.start = ctx.at;
        state.open = state.items.length > 0;
        if (active && active !== state && active.open) {
            active.open = false; render();
        }
        active = state;
        render();
    }

    function complete(state, i) {
        var it = state.items[i === undefined ? state.idx : i];
        if (!it) return;
        state.insert(it.login);
        state.open = false;
        render();
    }

    function close() {
        if (active && active.open) { active.open = false; render(); }
    }

    /* Returns true when the key was consumed by an OPEN palette. */
    function handleKey(state, key) {
        if (!state.open || active !== state) return false;
        if (key === 'Tab' || key === 'Enter') { complete(state); return true; }
        if (key === 'ArrowDown') {
            state.idx = (state.idx + 1) % state.items.length; render(); return true;
        }
        if (key === 'ArrowUp') {
            state.idx = (state.idx + state.items.length - 1) % state.items.length;
            render(); return true;
        }
        if (key === 'Escape') { state.open = false; render(); return true; }
        return false;
    }

    /* ---- host adapters -------------------------------------------------- */

    function attach(el, opts) {
        if (!el || el.__irisMention) return el && el.__irisMention;
        opts = opts || {};
        var state = {
            el: el,
            kind: opts.kind || el.getAttribute('data-iris-mention') || 'case',
            cid: opts.cid || el.getAttribute('data-iris-mention-cid') || null,
            candidates: opts.candidates || null,
            open: false, items: [], idx: 0, start: -1,
            ctx: function () {
                var pos = el.selectionStart;
                if (pos === null || pos === undefined) pos = el.value.length;
                return ctxOf(el.value.slice(0, pos));
            },
            insert: function (login) {
                var v = el.value;
                var pos = el.selectionStart;
                if (pos === null || pos === undefined) pos = v.length;
                el.value = v.slice(0, state.start) + '@' + login + ' ' + v.slice(pos);
                var np = state.start + login.length + 2;
                try { el.setSelectionRange(np, np); } catch (e) { /* type=email etc. */ }
                el.focus();
                try { el.dispatchEvent(new Event('input', {bubbles: true})); } catch (e) {}
            },
            rect: function () { return el.getBoundingClientRect(); }
        };
        el.__irisMention = state;
        load(state.kind, state.cid);
        /* capture phase + stopImmediatePropagation: the page's own Enter →
           post handler (a bubbling listener on an ancestor, or a later one
           on the element) must not fire while the palette owns the key */
        el.addEventListener('keydown', function (e) {
            if (handleKey(state, e.key)) {
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
            }
        }, true);
        el.addEventListener('input', function () {
            /* a completion dispatches a synthetic input — with the palette
               already closed, update() sees no token and stays closed */
            update(state);
        });
        el.addEventListener('click', function () { update(state); });
        el.addEventListener('keyup', function (e) {
            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight'
                    || e.key === 'Home' || e.key === 'End') update(state);
        });
        el.addEventListener('blur', function () {
            setTimeout(function () {
                if (active === state) { state.open = false; render(); }
            }, 200);
        });
        return state;
    }

    function attachAce(editor, opts) {
        if (!editor || editor.__irisMention) return editor && editor.__irisMention;
        opts = opts || {};
        var Range;
        try { Range = ace.require('ace/range').Range; } catch (e) { Range = null; }
        var HashHandler;
        try { HashHandler = ace.require('ace/keyboard/hash_handler').HashHandler; }
        catch (e) { HashHandler = null; }
        var state = {
            el: editor.container,
            kind: opts.kind || 'case',
            cid: opts.cid || null,
            candidates: opts.candidates || null,
            open: false, items: [], idx: 0, start: -1, row: 0,
            ctx: function () {
                var pos = editor.getCursorPosition();
                var line = editor.session.getLine(pos.row);
                var c = ctxOf(line.slice(0, pos.column));
                if (c) state.row = pos.row;
                return c;
            },
            insert: function (login) {
                var pos = editor.getCursorPosition();
                if (Range) {
                    editor.session.replace(
                        new Range(state.row, state.start, pos.row, pos.column),
                        '@' + login + ' ');
                } else {
                    editor.insert('@' + login + ' ');
                }
                editor.focus();
            },
            rect: function () { return editor.container.getBoundingClientRect(); }
        };
        editor.__irisMention = state;
        load(state.kind, state.cid);

        var handler = null;
        if (HashHandler) {
            handler = new HashHandler();
            var bind = function (key) {
                /* a false return tells ACE the key was NOT consumed, so the
                   default binding (newline, indent, cursor move) still runs */
                return function () { return handleKey(state, key) ? undefined : false; };
            };
            handler.bindKeys({
                'Tab': bind('Tab'), 'Return': bind('Enter'),
                'Down': bind('ArrowDown'), 'Up': bind('ArrowUp'),
                'Esc': bind('Escape')
            });
            var pushed = false;
            state.onOpen = function () {
                if (!pushed) { editor.keyBinding.addKeyboardHandler(handler); pushed = true; }
            };
            state.onClose = function () {
                if (pushed) { editor.keyBinding.removeKeyboardHandler(handler); pushed = false; }
            };
        }
        /* ACE fires `change` BEFORE it moves the cursor after an insert, so
           the token detector must run on the cursor move as well — that is
           the event that lands the caret after the '@' token. */
        editor.on('change', function () { update(state); });
        editor.selection.on('changeCursor', function () { update(state); });
        editor.on('blur', function () {
            setTimeout(function () {
                if (active === state) { state.open = false; render(); }
            }, 200);
        });
        return state;
    }

    /* ---- highlighting --------------------------------------------------- */

    function resolveToken(tok, logins) {
        var t = tok;
        while (t) {
            if (logins.has(t.toLowerCase())) return t;
            if ('.-_@'.indexOf(t.charAt(t.length - 1)) !== -1) t = t.slice(0, -1);
            else break;
        }
        return null;
    }

    function highlightHtml(html, logins) {
        var known = knownLogins(logins);
        if (!html || !known.size || html.indexOf('@') === -1) return html;
        var tpl = document.createElement('template');
        tpl.innerHTML = html;
        var walker = document.createTreeWalker(tpl.content, NodeFilter.SHOW_TEXT);
        var nodes = [];
        var n;
        while ((n = walker.nextNode())) {
            var p = n.parentNode, skip = false;
            while (p && p !== tpl.content) {
                if (SKIP_TAGS[p.nodeName]) { skip = true; break; }
                p = p.parentNode;
            }
            if (!skip && n.nodeValue.indexOf('@') !== -1) nodes.push(n);
        }
        nodes.forEach(function (node) {
            var text = node.nodeValue;
            var frag = document.createDocumentFragment();
            var last = 0, m, touched = false;
            TOKEN_RE.lastIndex = 0;
            while ((m = TOKEN_RE.exec(text))) {
                var hit = resolveToken(m[2], known);
                if (!hit) continue;
                var start = m.index + m[1].length;
                frag.appendChild(document.createTextNode(text.slice(last, start)));
                var span = document.createElement('span');
                span.className = 'iris-mention';
                span.textContent = '@' + hit;
                frag.appendChild(span);
                last = start + 1 + hit.length;
                /* re-scan from just after the resolved part: "@bob." keeps
                   its dot as plain text */
                TOKEN_RE.lastIndex = last;
                touched = true;
            }
            if (!touched) return;
            frag.appendChild(document.createTextNode(text.slice(last)));
            node.parentNode.replaceChild(frag, node);
        });
        return tpl.innerHTML;
    }

    /* ---- wiring --------------------------------------------------------- */

    document.addEventListener('focusin', function (e) {
        var el = e.target;
        if (!el || !el.getAttribute) return;
        var kind = el.getAttribute('data-iris-mention');
        if (!kind || el.__irisMention) return;
        if (el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA') return;
        attach(el, {kind: kind});
    });

    document.addEventListener('DOMContentLoaded', function () {
        ensureStyle();
        /* preload so the first rendered comment can already highlight */
        var path = window.location.pathname || '';
        if (path.indexOf('/case/') === 0 && cidFromUrl()) load('case');
        else if (path.indexOf('/alerts') === 0
                 || path.indexOf('/alert-clusters') === 0) load('users');
    });

    window.IrisMentionPalette = {
        attach: attach,
        attachAce: attachAce,
        load: load,
        close: close,
        highlightHtml: highlightHtml,
        knownLogins: knownLogins,
        /* exposed for the headless probe */
        _ctxOf: ctxOf,
        _rank: rank,
        _resolveToken: resolveToken,
        _sources: sources
    };
})();

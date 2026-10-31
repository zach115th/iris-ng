/* iris-ng (i) help icons (2026-10-30). Import-free; loaded in <head> by
 * templates/includes/help_assets.html on every layout with a nav and on the
 * guest portal.
 *
 * An icon is <button class="iris-help" data-iris-help="<key>">, drawn by the
 * Jinja global help_tip() (business/help_glossary.py::icon_markup) or by
 * IrisHelp.icon() below - the two emit the same markup. The definitions come
 * from window.IrisHelpGlossary (/help/glossary.js, content-hashed), the viewer
 * from window.IrisHelpConfig; with either missing (icons turned off in
 * Profile, nobody signed in) IrisHelp.icon() returns '' and nothing listens.
 *
 * Hovering an icon previews its definition; a click, tap, Enter or Space pins
 * it open; Esc, the close button or a click elsewhere closes it. A term with
 * "values" shows the description this server stores for the value chosen in
 * the field the icon names (data-iris-help-for), from /api/v2/help/values/.
 * Listeners sit on window in the CAPTURE phase, so a click or key on an icon
 * inside a sortable table header, a collapse toggle or a draggable modal
 * header never reaches those handlers, and Esc closes the tip before a modal.
 */
(function () {
    'use strict';
    if (window.IrisHelp) { return; }

    var OPEN_DELAY = 150;
    var CLOSE_DELAY = 220;
    var LIST_VALUES_UP_TO = 12;

    var pop = null;          // the one popover element
    var cur = null;          // {btn, key, pinned}
    var openTimer = 0;
    var closeTimer = 0;
    var renderToken = 0;     // drops a values reply that arrives after a close
    var valuesCache = {};
    var watched = null;      // {el, fn}: the field a "values" tip follows
    var restoringFocus = false;  // our own focus() back onto an icon is not a keyboard visit
    var gone = null;         // MutationObserver: an open tip closes when its icon leaves the page

    function config() { return window.IrisHelpConfig || null; }
    function data() { return window.IrisHelpGlossary || null; }
    function enabled() {
        var c = config(), d = data();
        return !!(c && d && d.terms);
    }
    function term(key) {
        var d = data();
        if (!d || !d.terms || !Object.prototype.hasOwnProperty.call(d.terms, key)) { return null; }
        return d.terms[key];
    }

    // markupsafe.escape()'s entities, so both renderers emit identical markup.
    function esc(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&#34;').replace(/'/g, '&#39;');
    }

    function icon(key, opts) {
        var t = enabled() ? term(key) : null;
        if (!t) { return ''; }
        var target = (opts && opts.target) ? ' data-iris-help-for="' + esc(opts.target) + '"' : '';
        var classes = 'iris-help' + ((opts && opts.cls) ? ' ' + esc(opts.cls) : '');
        return '<button type="button" class="' + classes + '" data-iris-help="' + esc(key) + '"' + target +
            ' aria-label="About ' + esc(t.title) + '" aria-haspopup="dialog" aria-expanded="false"></button>';
    }

    function el(key, opts) {
        var html = icon(key, opts);
        if (!html) { return null; }
        var tpl = document.createElement('template');
        tpl.innerHTML = html;
        return tpl.content.firstChild;
    }

    function mk(tag, cls, text) {
        var n = document.createElement(tag);
        if (cls) { n.className = cls; }
        if (text !== undefined && text !== null) { n.textContent = text; }
        return n;
    }

    function link(href, text, external) {
        var a = mk('a', 'iris-help-pop-link', text);
        a.href = href;
        if (external) {
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            a.setAttribute('aria-label', text + ' (opens the wiki in a new tab)');
        }
        return a;
    }

    function iconFrom(t) {
        return (t && t.closest) ? t.closest('button.iris-help[data-iris-help]') : null;
    }
    function inPop(t) { return !!(pop && t && t.nodeType === 1 && pop.contains(t)); }

    function ensurePop() {
        if (pop) { return pop; }
        pop = mk('div', 'iris-help-pop');
        pop.id = 'iris-help-pop';
        pop.setAttribute('role', 'dialog');
        pop.setAttribute('aria-labelledby', 'iris-help-pop-title');
        pop.tabIndex = -1;
        pop.hidden = true;
        return pop;
    }

    // ---- values ---------------------------------------------------------

    function fetchValues(source) {
        var c = config();
        if (!c || !c.values_url) { return Promise.reject(new Error('no values for this viewer')); }
        if (!valuesCache[source]) {
            valuesCache[source] = fetch(c.values_url + encodeURIComponent(source),
                {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
                .then(function (r) {
                    if (!r.ok) { throw new Error('HTTP ' + r.status); }
                    return r.json();
                })
                .then(function (d) {
                    if (!d || !Array.isArray(d.values)) { throw new Error('not a values reply'); }
                    return d.values;
                })
                .catch(function (e) { delete valuesCache[source]; throw e; });
        }
        return valuesCache[source];
    }

    function targetOf(btn) {
        var sel = btn.getAttribute('data-iris-help-for');
        if (!sel) { return null; }
        try { return document.querySelector(sel); } catch (e) { return null; }
    }

    function selectedRow(btn, rows) {
        var field = targetOf(btn);
        if (!field) { return null; }
        var value, text;
        if (field.tagName === 'SELECT') {
            if (field.selectedIndex < 0) { return null; }
            var opt = field.options[field.selectedIndex];
            value = opt.value;
            text = opt.text;
        } else if ('value' in field && field.tagName !== 'BUTTON') {
            value = field.value;
            text = field.value;
        } else {
            value = text = field.textContent;
        }
        value = String(value === undefined || value === null ? '' : value).trim();
        text = String(text || '').trim();
        if (!value && !text) { return null; }
        var i;
        for (i = 0; i < rows.length; i++) { if (String(rows[i].id) === value) { return rows[i]; } }
        for (i = 0; i < rows.length; i++) {
            if (rows[i].name === text || rows[i].label === text || rows[i].name === value) { return rows[i]; }
        }
        return null;
    }

    function meaning(row) {
        var d = (row.description || '').trim();
        // An earlier seed stored the name itself as the description.
        return (d && d.toLowerCase() !== String(row.name).toLowerCase()) ? d : '';
    }

    function drawValues(box, btn, rows) {
        box.textContent = '';
        var picked = selectedRow(btn, rows);
        if (picked) {
            var p = mk('p', 'iris-help-pop-selected');
            p.appendChild(mk('strong', null, 'Selected: ' + picked.label));
            var m = meaning(picked);
            p.appendChild(document.createTextNode(m ? ' — ' + m : ' — no description on this server.'));
            box.appendChild(p);
        }
        if (rows.length && rows.length <= LIST_VALUES_UP_TO) {
            box.appendChild(mk('div', 'iris-help-pop-vhead', 'On this server'));
            var dl = mk('dl', 'iris-help-pop-items');
            rows.forEach(function (row) {
                var dt = mk('dt', null, row.label);
                var dd = mk('dd', null, meaning(row) || '—');
                if (picked && row.id === picked.id) { dt.className = dd.className = 'is-selected'; }
                dl.appendChild(dt);
                dl.appendChild(dd);
            });
            box.appendChild(dl);
        } else if (rows.length) {
            var c = config();
            box.appendChild(mk('p', 'iris-help-pop-vnote', rows.length + ' values on this server' +
                (picked ? '' : '; choose one to see what it means') +
                ((c && c.glossary_url) ? '. All terms lists every one.' : '.')));
        }
    }

    function fillValues(box, btn, source) {
        var token = renderToken;
        box.appendChild(mk('p', 'iris-help-pop-vnote', 'Loading this server’s values…'));
        fetchValues(source).then(function (rows) {
            if (token !== renderToken || !box.isConnected) { return; }
            drawValues(box, btn, rows);
            place();
        }, function () {
            if (token !== renderToken || !box.isConnected) { return; }
            box.textContent = '';
            box.appendChild(mk('p', 'iris-help-pop-vnote', 'Could not load this server’s values.'));
            place();
        });
    }

    function watchTarget(btn, t) {
        unwatchTarget();
        if (!t.values) { return; }
        var field = targetOf(btn);
        if (!field) { return; }
        var fn = function () {
            if (!cur || cur.btn !== btn || !pop) { return; }
            var box = pop.querySelector('.iris-help-pop-values');
            if (!box) { return; }
            fetchValues(t.values).then(function (rows) {
                if (cur && cur.btn === btn && box.isConnected) { drawValues(box, btn, rows); place(); }
            }, function () { /* the open tip already says so */ });
        };
        field.addEventListener('change', fn);
        watched = {el: field, fn: fn};
    }

    function unwatchTarget() {
        if (watched) { watched.el.removeEventListener('change', watched.fn); }
        watched = null;
    }

    // ---- the popover ----------------------------------------------------

    function render(btn, key, t, pinned) {
        var p = ensurePop();
        renderToken += 1;
        p.textContent = '';
        p.setAttribute('data-pinned', pinned ? 'true' : 'false');
        p.setAttribute('data-iris-help-key', key);

        var head = mk('div', 'iris-help-pop-head');
        var title = mk('div', 'iris-help-pop-title', t.title);
        title.id = 'iris-help-pop-title';
        head.appendChild(title);
        if (pinned) {
            var x = mk('button', 'iris-help-pop-close', '×');
            x.type = 'button';
            x.setAttribute('aria-label', 'Close');
            head.appendChild(x);
        }
        p.appendChild(head);

        var body = mk('div', 'iris-help-pop-body');
        String(t.text).split(/\n[ \t]*\n/).forEach(function (para) {
            if (para.trim()) { body.appendChild(mk('p', null, para.trim())); }
        });
        if (t.items && t.items.length) {
            var dl = mk('dl', 'iris-help-pop-items');
            t.items.forEach(function (item) {
                dl.appendChild(mk('dt', null, item[0]));
                dl.appendChild(mk('dd', null, item[1]));
            });
            body.appendChild(dl);
        }
        if (t.values) {
            var box = mk('div', 'iris-help-pop-values');
            body.appendChild(box);
            fillValues(box, btn, t.values);
        }
        p.appendChild(body);

        var d = data(), c = config();
        var links = [];
        if (t.wiki && d && d.wiki_base) { links.push(link(d.wiki_base + t.wiki, 'Learn more', true)); }
        if (c && c.glossary_url) { links.push(link(c.glossary_url + '#term-' + key, 'All terms', false)); }
        if (links.length) {
            var foot = mk('div', 'iris-help-pop-foot');
            links.forEach(function (a) { foot.appendChild(a); });
            p.appendChild(foot);
        }
    }

    function place() {
        if (!cur || !pop || pop.hidden) { return; }
        var btn = cur.btn;
        if (!btn.isConnected) { close(false); return; }
        var r = btn.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) { close(false); return; }
        var de = document.documentElement;
        var vw = de.clientWidth, vh = de.clientHeight, m = 8, gap = 6;
        pop.style.maxWidth = Math.min(360, vw - 2 * m) + 'px';
        pop.style.left = '0px';
        pop.style.top = '0px';
        var w = pop.offsetWidth, h = pop.offsetHeight;
        var below = vh - r.bottom - gap - m, above = r.top - gap - m;
        var top = r.bottom + gap;
        var side = 'below';
        if (h > below && above > below) {
            top = Math.max(m, r.top - gap - h);
            side = 'above';
        }
        var left = Math.min(Math.max(m, r.left + r.width / 2 - 18), Math.max(m, vw - w - m));
        pop.style.left = Math.round(left) + 'px';
        pop.style.top = Math.round(top) + 'px';
        pop.setAttribute('data-side', side);
    }

    function clearTimers() {
        clearTimeout(openTimer);
        clearTimeout(closeTimer);
        openTimer = closeTimer = 0;
    }

    function open(btn, pinned) {
        var key = btn.getAttribute('data-iris-help');
        var t = enabled() ? term(key) : null;
        if (!t) { return; }
        clearTimers();
        if (cur && cur.btn !== btn) { close(false); }
        var p = ensurePop();
        var host = btn.closest('.modal') || document.body;
        if (p.parentNode !== host) { host.appendChild(p); }
        render(btn, key, t, pinned);
        p.hidden = false;
        cur = {btn: btn, key: key, pinned: pinned};
        btn.setAttribute('aria-expanded', 'true');
        btn.setAttribute('aria-controls', 'iris-help-pop');
        if (pinned) { btn.removeAttribute('aria-describedby'); }
        else { btn.setAttribute('aria-describedby', 'iris-help-pop'); }
        watchTarget(btn, t);
        watchIcon();
        place();
    }

    function watchIcon() {
        if (!window.MutationObserver) { return; }
        if (!gone) {
            gone = new MutationObserver(function () {
                if (cur && (!cur.btn.isConnected || cur.btn.getClientRects().length === 0)) { close(false); }
            });
        }
        gone.disconnect();
        // Removed by a re-render, or hidden (a dropdown or a tab closing around it).
        gone.observe(document.body, {childList: true, subtree: true, attributes: true,
                                     attributeFilter: ['class', 'style', 'hidden']});
    }

    function close(restoreFocus) {
        clearTimers();
        if (!cur) { return; }
        var btn = cur.btn;
        cur = null;
        renderToken += 1;
        unwatchTarget();
        if (gone) { gone.disconnect(); }
        if (pop) {
            pop.hidden = true;
            pop.textContent = '';
            pop.removeAttribute('data-iris-help-key');
        }
        btn.setAttribute('aria-expanded', 'false');
        btn.removeAttribute('aria-describedby');
        btn.removeAttribute('aria-controls');
        if (restoreFocus && btn.isConnected) {
            restoringFocus = true;
            try { btn.focus(); } finally { restoringFocus = false; }
        }
    }

    function scheduleClose() {
        clearTimeout(closeTimer);
        closeTimer = setTimeout(function () {
            if (cur && !cur.pinned) { close(false); }
        }, CLOSE_DELAY);
    }

    // ---- listeners (capture phase, on window) ---------------------------

    window.addEventListener('pointerover', function (e) {
        if (e.pointerType === 'touch') { return; }
        var btn = iconFrom(e.target);
        if (btn) {
            clearTimeout(closeTimer);
            if (!enabled() || (cur && (cur.btn === btn || cur.pinned))) { return; }
            clearTimeout(openTimer);
            openTimer = setTimeout(function () { open(btn, false); }, OPEN_DELAY);
            return;
        }
        if (inPop(e.target)) { clearTimeout(closeTimer); }
    }, true);

    window.addEventListener('pointerout', function (e) {
        if (e.pointerType === 'touch') { return; }
        var btn = iconFrom(e.target);
        var from = btn || (inPop(e.target) ? pop : null);
        if (!from) { return; }
        var to = e.relatedTarget;
        if (to && to.nodeType === 1 && (from.contains(to) || inPop(to) || (cur && cur.btn.contains(to)))) { return; }
        if (btn) { clearTimeout(openTimer); }
        if (cur && !cur.pinned) { scheduleClose(); }
    }, true);

    window.addEventListener('click', function (e) {
        var btn = iconFrom(e.target);
        if (btn) {
            e.preventDefault();
            e.stopPropagation();
            if (!enabled()) { return; }
            var keyboard = e.detail === 0;
            if (cur && cur.btn === btn && cur.pinned) { close(keyboard); return; }
            open(btn, true);
            if (keyboard && pop) {
                var x = pop.querySelector('.iris-help-pop-close');
                if (x) { x.focus(); }
            }
            return;
        }
        if (inPop(e.target)) {
            // A click inside the tip is not a click on the page under it: a
            // Bootstrap dropdown holding the icon must not read it as "clicked
            // outside" and close. Links still open (no preventDefault).
            e.stopPropagation();
            if (e.target.closest('.iris-help-pop-close')) {
                e.preventDefault();
                close(true);
            }
            return;
        }
        if (cur && cur.pinned) { close(false); }
    }, true);

    function isActivationKey(e) { return e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar'; }

    window.addEventListener('keydown', function (e) {
        if (iconFrom(e.target) && isActivationKey(e)) {
            // The button's own click follows; a sortable header or a collapse
            // toggle around it must not also act on the key.
            e.stopPropagation();
            return;
        }
        if ((e.key === 'Escape' || e.key === 'Esc') && cur) {
            var active = document.activeElement;
            var refocus = active === cur.btn || inPop(active);
            e.preventDefault();
            e.stopPropagation();
            close(refocus);
        }
    }, true);

    ['keyup', 'keypress'].forEach(function (type) {
        window.addEventListener(type, function (e) {
            if (iconFrom(e.target) && isActivationKey(e)) { e.stopPropagation(); }
        }, true);
    });

    window.addEventListener('focusin', function (e) {
        var btn = iconFrom(e.target);
        if (!btn || restoringFocus || (cur && cur.pinned)) { return; }
        var keyboard = true;
        try { keyboard = btn.matches(':focus-visible'); } catch (x) { keyboard = true; }
        if (keyboard && !(cur && cur.btn === btn)) {
            clearTimeout(openTimer);
            open(btn, false);
        }
    }, true);

    window.addEventListener('focusout', function (e) {
        if (!cur || cur.pinned) { return; }
        var btn = iconFrom(e.target);
        if (btn && btn === cur.btn && !inPop(e.relatedTarget)) { scheduleClose(); }
    }, true);

    var raf = 0;
    function schedulePlace() {
        if (cur && !cur.btn.isConnected) { close(false); return; }
        if (!cur || raf) { return; }
        raf = window.requestAnimationFrame(function () { raf = 0; place(); });
    }
    window.addEventListener('scroll', schedulePlace, {capture: true, passive: true});
    window.addEventListener('resize', schedulePlace);

    window.IrisHelp = {
        icon: icon,
        el: el,
        term: term,
        enabled: enabled,
        open: function (btn) { if (btn) { open(btn, true); } },
        close: function () { close(false); },
        state: function () { return cur ? {key: cur.key, pinned: cur.pinned} : null; }
    };
}());

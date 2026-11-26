/*
 * swal() with sweetalert 2.1.2's API, drawn by sweetalert2 (iris-ng, backlog #44 slice 3.3).
 *
 * Every layout loads plugin/sweetalert2/sweetalert2.min.js and then this file. sweetalert2's build defines its
 * own `swal` (its class); this file replaces it with a function that takes 2.1.2's arguments and resolves with
 * 2.1.2's values, so IRIS's calls - and a custom template or module calling swal() - keep working unchanged.
 * New code may call Swal.fire() directly.
 *
 * What 2.1.2 did, and this file does:
 *   - arguments: swal(text) / swal(title, text) / swal(title, text, icon) / swal(..., {options}) / swal({options});
 *     an argument of the wrong kind throws, as 2.1.2's did (an undefined text included);
 *   - buttons: `button` (one confirm), `buttons` (true / false / [cancel, confirm] / {key: true | text | {text,
 *     value, visible, className, closeModal}}), shown in the order given; the promise resolves with the clicked
 *     button's value (confirm true, cancel null, another key its name unless it says otherwise); Escape, a click
 *     outside, the timer and swal.close() resolve with the cancel key's value, shown or not;
 *   - content 'input': the confirm resolves with the typed text ('' when nothing was typed), Enter confirms;
 *   - dangerMode: the confirm button red, focus on the first button (else on the last);
 *   - a dialog opened over another leaves the first one's promise unsettled (sweetalert2 would settle it as
 *     dismissed, and a caller's cancel branch would run).
 * Text stays text: 2.1.2 wrote the title, the text and every button label as text, while sweetalert2 writes
 * `title` and button labels as HTML - the title goes in as `titleText`, the text as `text`, labels escaped.
 *
 * Honoured where 2.1.2 ignored them (maintainer, 2026-11-25): confirmButtonText / cancelButtonText (the label of
 * a confirm / cancel the call did not label itself) and allowOutsideClick. Ignored, as before: the button colours
 * (dangerMode decides), allowEnterKey and every other sweetalert2 option. More than three buttons: sweetalert2
 * has three places, so the first and the last two show (a console warning says so); no IRIS call has more than two.
 */
(function () {
    'use strict';
    var S2 = window.Sweetalert2;
    if (!S2 || typeof S2.fire !== 'function') { return; }

    var ICONS = ['warning', 'error', 'success', 'info'];
    var assign = Object.assign;

    function esc(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    // 2.1.2's own tests: a plain object has Object's prototype (or none), and an error is thrown as a string
    function isPlain(o) {
        if (Object.prototype.toString.call(o) !== '[object Object]') { return false; }
        var p = Object.getPrototypeOf(o);
        return p === null || p === Object.prototype;
    }
    function fail(m) { throw 'SweetAlert: ' + m.replace(/ +(?= )/g, '').trim(); }   // eslint-disable-line no-throw-literal
    function ordinal(n) {
        var s = ['th', 'st', 'nd', 'rd'], v = n % 100;
        return n + (s[(v - 20) % 10] || s[v] || s[0]);
    }

    // ------------------------------------------------------------------ 2.1.2's options, as 2.1.2 read them
    var BUTTON = {visible: true, text: null, value: null, className: '', closeModal: true};
    var CANCEL = assign({}, BUTTON, {visible: false, text: 'Cancel', value: null});
    var CONFIRM = assign({}, BUTTON, {text: 'OK', value: true});

    function defaultsFor(key) {
        if (key === 'confirm') { return CONFIRM; }
        if (key === 'cancel') { return CANCEL; }
        return assign({}, BUTTON, {text: key.charAt(0).toUpperCase() + key.slice(1), value: key});
    }
    function buttonOpt(key, v) {
        var d = defaultsFor(key);
        if (v === true) { return assign({}, d, {visible: true}); }
        if (typeof v === 'string') { return assign({}, d, {visible: true, text: v}); }
        if (isPlain(v)) { return assign({visible: true}, d, v); }
        return assign({}, d, {visible: false});
    }
    function fromArray(a) {
        if (a.length === 1) { return {cancel: assign({}, CANCEL)}; }
        if (a.length === 2) { return {cancel: buttonOpt('cancel', a[0]), confirm: buttonOpt('confirm', a[1])}; }
        return fail("Invalid number of 'buttons' in array (" + a.length + ").\n      If you want more than 2 buttons, you need to use an object!");
    }
    function buttonList(b) {
        if (typeof b === 'string') { return {cancel: CANCEL, confirm: buttonOpt('confirm', b)}; }
        if (Array.isArray(b)) { return fromArray(b); }
        if (isPlain(b)) {
            var out = {};
            Object.keys(b).forEach(function (k) { out[k] = buttonOpt(k, b[k]); });
            if (!out.cancel) { out.cancel = CANCEL; }
            return out;
        }
        if (b === true) { return fromArray([true, true]); }
        if (b === false) { return fromArray([false, false]); }
        return {cancel: CANCEL, confirm: CONFIRM};
    }
    function readArgs(args) {
        var o = {};
        args.forEach(function (a, i) {
            var next = args[i + 1];
            if (typeof a === 'string') {
                if (i === 0) { assign(o, {text: a}); return; }
                if (i === 1) { assign(o, {text: a, title: args[0]}); return; }
                if (i === 2) {
                    if (!(isPlain(next) || next === undefined)) { fail('Expected ' + ordinal(i + 2) + " argument ('" + next + "') to be a plain object"); }
                    assign(o, {icon: a}); return;
                }
            } else if (a instanceof Element && i === 0) {
                if (!(isPlain(next) || next === undefined)) { fail('Expected ' + ordinal(i + 2) + " argument ('" + next + "') to be a plain object"); }
                assign(o, {content: a}); return;
            } else if (isPlain(a)) {
                if (next !== undefined) { fail('Unexpected ' + ordinal(i + 2) + ' argument (' + next + ')'); }
                assign(o, a); return;
            }
            fail(ordinal(i + 1) + " argument ('" + a + "') is invalid");
        });
        if (o.button !== undefined && o.buttons !== undefined) { fail("Cannot set both 'button' and 'buttons' options!"); }
        o.buttons = buttonList(o.button !== undefined ? {confirm: o.button} : o.buttons);
        delete o.button;
        return assign({title: null, text: null, icon: null, content: null, className: null,
                       closeOnClickOutside: true, closeOnEsc: true, dangerMode: false, timer: null}, o);
    }
    function classesOf(c) {
        return (Array.isArray(c) ? c : String(c || '').split(' ')).filter(function (x) { return x.length > 0; });
    }

    // ------------------------------------------------------------------ the dialog

    var current = null;   // the newest dialog: {actions, closed, closeKey, settle}

    function swal() {
        var o = readArgs(Array.prototype.slice.call(arguments));
        var list = o.buttons;
        var rec = {actions: {}, closed: false, closeKey: undefined};
        Object.keys(list).forEach(function (k) { rec.actions[k] = {value: list[k].value, closeModal: list[k].closeModal !== false}; });
        // a label the call did not give itself, from sweetalert2's own option (maintainer, 2026-11-25)
        if (list.confirm && list.confirm.text === CONFIRM.text && typeof o.confirmButtonText === 'string') {
            list.confirm = assign({}, list.confirm, {text: o.confirmButtonText});
        }
        if (list.cancel && list.cancel.text === CANCEL.text && typeof o.cancelButtonText === 'string') {
            list.cancel = assign({}, list.cancel, {text: o.cancelButtonText});
        }
        var shown = Object.keys(list).filter(function (k) { return list[k].visible; });
        if (shown.length > 3) {
            if (window.console) { console.warn('swal(): sweetalert2 shows at most three buttons; showing ' + [shown[0]].concat(shown.slice(-2)).join(', ')); }
            shown = [shown[0]].concat(shown.slice(-2));
        }
        // sweetalert2's places, left to right with reverseButtons: cancel, deny, confirm
        var slot = {};
        if (shown.length === 1) { slot.confirm = shown[0]; }
        if (shown.length === 2) { slot.cancel = shown[0]; slot.confirm = shown[1]; }
        if (shown.length === 3) { slot.cancel = shown[0]; slot.deny = shown[1]; slot.confirm = shown[2]; }
        var cls = function (k) {
            return ['swal-button', 'swal-button--' + k].concat(k === 'confirm' && o.dangerMode ? ['swal-button--danger'] : [],
                                                               classesOf(list[k].className)).join(' ');
        };
        var label = function (k) { return list[k].text === null || list[k].text === undefined ? '' : esc(list[k].text); };

        var icon, image;
        if (o.icon) {
            if (ICONS.indexOf(o.icon) >= 0) { icon = o.icon; } else { image = String(o.icon); }
        }
        var input = null, html;
        var c = o.content;
        if (c === 'input' || (isPlain(c) && c.element === 'input')) {
            input = isPlain(c) ? (c.attributes || {}) : {};
        } else if (c instanceof Element) {
            html = document.createElement('div');
            if (o.text) { html.appendChild(document.createElement('div')).textContent = String(o.text); }
            html.appendChild(c);
        }

        var promise = new Promise(function (resolve) {
            var settled = false;
            rec.settle = function (v) { if (!settled) { settled = true; resolve(v); } };
        });
        var value = function (k) { return k && rec.actions[k] ? rec.actions[k].value : null; };
        var params = {
            titleText: o.title ? String(o.title) : '',
            text: html ? undefined : (o.text ? String(o.text) : ''),
            html: html,
            icon: icon,
            imageUrl: image,
            input: input ? (input.type || 'text') : undefined,
            inputPlaceholder: input && input.placeholder ? String(input.placeholder) : undefined,
            inputValue: input && input.value !== undefined ? String(input.value) : undefined,
            showConfirmButton: !!slot.confirm,
            showDenyButton: !!slot.deny,
            showCancelButton: !!slot.cancel,
            confirmButtonText: slot.confirm ? label(slot.confirm) : undefined,
            denyButtonText: slot.deny ? label(slot.deny) : undefined,
            cancelButtonText: slot.cancel ? label(slot.cancel) : undefined,
            reverseButtons: true,
            buttonsStyling: false,
            focusConfirm: false,
            focusCancel: false,
            focusDeny: false,
            allowOutsideClick: typeof o.allowOutsideClick === 'boolean' ? o.allowOutsideClick : o.closeOnClickOutside !== false,
            allowEscapeKey: o.closeOnEsc !== false,
            timer: o.timer || undefined,
            heightAuto: false,
            // 2.1.2 left focus where it was on close; returning it would move focus inside a Bootstrap modal
            returnFocus: false,
            customClass: {
                container: 'iris-swal',
                popup: ['swal-modal'].concat(classesOf(o.className)).join(' '),
                title: 'swal-title',
                htmlContainer: 'swal-text',
                actions: 'swal-footer',
                confirmButton: slot.confirm ? cls(slot.confirm) : '',
                denyButton: slot.deny ? cls(slot.deny) : '',
                cancelButton: slot.cancel ? cls(slot.cancel) : '',
                input: 'swal-content__input',
            },
            // the title and the text written as 2.1.2 wrote them: the title by textContent (a line break in it
            // collapses to a space; sweetalert2's titleText goes through innerText, which would break the line),
            // the text as one text node per line with a <br> between
            didRender: function (popup) {
                // what the dialog shows, for swal_compat.css: 2.1.2 spaced its parts with :first-child /
                // :last-child, which sweetalert2's popup (it keeps hidden parts in place) never matches
                popup.classList.toggle('iris-swal--icon', !!(icon || image));
                popup.classList.toggle('iris-swal--title', !!o.title);
                popup.classList.toggle('iris-swal--text', !!(o.text || html));
                popup.classList.toggle('iris-swal--buttons', shown.length > 0);
                popup.classList.toggle('iris-swal--input', !!input);
                var t = popup.querySelector('.swal2-title');
                if (t && o.title) { t.textContent = String(o.title); }
                var h = popup.querySelector('.swal2-html-container');
                if (h && !html && o.text) {
                    h.textContent = '';
                    String(o.text).split('\n').forEach(function (line, i, all) {
                        h.appendChild(document.createTextNode(line));
                        if (i < all.length - 1) { h.appendChild(document.createElement('br')); }
                    });
                }
            },
            didOpen: function (popup) {
                // in document order, as 2.1.2 found them (reverseButtons puts sweetalert2's in the order shown; a
                // long label can wrap the row, so the left edge is no guide)
                var buttons = Array.prototype.slice.call(popup.querySelectorAll('.swal2-actions button'))
                    .filter(function (b) { return b.offsetParent !== null; });
                // 2.1.2's focus: the first button in danger mode, else the last; an input takes it after
                var target = o.dangerMode ? buttons[0] : buttons[buttons.length - 1];
                if (target) { target.focus(); }
                // Escape outside the popup: 2.1.2 listened on the document (keyup), sweetalert2 only on its popup.
                // Over a Bootstrap 4 modal, whose focus trap pulls focus back into the modal, 2.1.2 still closed on
                // Escape (and the modal with it); this keeps that.
                var onKeyup = function (e) {
                    if (e.key !== 'Escape' || o.closeOnEsc === false || rec.done || current !== rec) { return; }
                    if (popup.contains(e.target)) { return; }   // sweetalert2 took it on keydown
                    rec.closed = true;
                    rec.closeKey = 'cancel';
                    S2.close();
                };
                document.addEventListener('keyup', onKeyup);
                rec.cleanup = function () { document.removeEventListener('keyup', onKeyup); };
                var field = popup.querySelector('.swal2-input');
                if (input && field) {
                    if (rec.actions.confirm) { rec.actions.confirm.value = ''; } else { rec.actions.confirm = {value: '', closeModal: true}; }
                    field.addEventListener('input', function () { rec.actions.confirm.value = field.value; });
                    field.focus();
                }
                // a button whose closeModal is false resolves and stays open, loading
                ['confirm', 'deny', 'cancel'].forEach(function (s) {
                    var k = slot[s];
                    if (!k || rec.actions[k].closeModal) { return; }
                    var b = popup.querySelector('.swal2-' + s);
                    if (b) {
                        b.addEventListener('click', function (e) {
                            e.stopImmediatePropagation();
                            rec.settle(value(k));
                            S2.showLoading(b);
                        }, true);
                    }
                });
            },
        };
        current = rec;
        S2.fire(params).then(function (r) {
            rec.done = true;
            if (rec.cleanup) { rec.cleanup(); }
            if (rec.closed) { rec.settle(value(rec.closeKey || 'cancel')); return; }
            if (r.isConfirmed) { rec.settle(input && slot.confirm === 'confirm' ? rec.actions.confirm.value : value(slot.confirm)); return; }
            if (r.isDenied) { rec.settle(value(slot.deny)); return; }
            if (r.dismiss === S2.DismissReason.cancel) { rec.settle(value(slot.cancel)); return; }
            if (r.dismiss) { rec.settle(value('cancel')); return; }
            // dismissed for no reason: a newer dialog replaced this one, and 2.1.2 never settled it
        });
        return promise;
    }

    swal.close = function (key) {
        if (current) { current.closed = true; current.closeKey = key; }
        S2.close();
    };
    swal.getState = function () {
        var a = {};
        if (current) { Object.keys(current.actions).forEach(function (k) { a[k] = assign({}, current.actions[k]); }); }
        return {isOpen: S2.isVisible(), actions: a};
    };
    swal.setActionValue = function (v) {
        if (!current) { return; }
        var set = function (k, x) { current.actions[k] = assign(current.actions[k] || {closeModal: true}, {value: x}); };
        if (typeof v === 'string') { set('confirm', v); return; }
        Object.keys(v || {}).forEach(function (k) { set(k, v[k]); });
    };
    swal.stopLoading = function () { S2.hideLoading(); };

    window.swal = swal;
    window.sweetAlert = swal;
})();

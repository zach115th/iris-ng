/* War-room Scope as a workspace (iris-ng 2026-11-08).
 *
 * window.IrisRoomScope - import-free (ui/public). Every asset of the attached cases the viewer can open:
 *   a table (type, IP, customer, compromise, analysis, flags, IOCs, open findings, updated) grouped by case, by
 *   vulnerability or not at all, or a flag board (one column per flag; drag a card onto a flag to set it);
 *   select assets to set / remove flags, set the compromise or analysis status, or push (copy) them to other
 *   attached cases; copy a group as a table (clipboard or CSV).
 * war_room_board.js keeps IrisRoomBoard.mountScope / setScopeFilter (the Board's tiles and ?pane=scope addresses)
 * and hands them here. The server decides every change per asset (full access to its case) and answers one result
 * per asset, so a selection spanning cases can partly succeed; this page reports what happened.
 *
 * Server values go through esc() before an innerHTML build, ids through id(). POST bodies carry csrf_token.
 */
(function () {
    'use strict';
    if (window.IrisRoomScope) { return; }
    var R = {};
    var $ = window.jQuery;
    var IrisHelp = window.IrisHelp || {icon: function () { return ''; }};
    var S = {el: null, ctx: null, filter: {}, group: 'case', view: 'table', data: null, seq: 0, done: 0, sel: {}, note: null,
             err: null, decisions: null};
    var KEYS = ['q', 'case_id', 'customer_id', 'compromised', 'flag', 'kind', 'vulnerable', 'vuln', 'sort', 'dir', 'page'];
    var COMPROMISE = {compromised: ['Compromised', 'iris-sc-red'], not_compromised: ['Not compromised', 'iris-sc-green'],
                      unknown: ['Unknown', ''], to_be_determined: ['To be determined', '']};
    var COLS = [['asset', 'Asset'], ['case', 'Case'], ['type', 'Type'], ['ip', 'IP'], ['domain', 'Domain'],
                ['customer', 'Customer'], ['compromise', 'Compromise'], ['analysis', 'Analysis'], ['flags', 'Flags'],
                ['iocs', 'IOCs'], ['vulns', 'Open findings'], ['updated', 'Updated']];
    var P = {
        push: '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/>',
        copy: '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
        table: '<path d="M12 3v18"/><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/>',
        board: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/><path d="M15 3v18"/>',
        search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
        flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" x2="4" y1="22" y2="15"/>',
        x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
        chevron: '<path d="m6 9 6 6 6-6"/>'
    };
    function ic(name, size) {
        return '<svg xmlns="http://www.w3.org/2000/svg" width="' + (size || 14) + '" height="' + (size || 14) + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;flex-shrink:0;">' + P[name] + '</svg>';
    }
    function esc(s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function id(v) { var n = parseInt(v, 10); return isNaN(n) ? 0 : n; }
    function csrf() { var e = document.getElementById('csrf_token'); return e ? e.value : ''; }
    function base() { return '/api/v2/war-rooms/' + id(S.ctx.roomId) + '/scope'; }
    function api(method, path, body) {
        var opts = {method: method, headers: {'Accept': 'application/json'}};
        if (body) {
            body.csrf_token = csrf();
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        return fetch(path, opts).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (j) { return {ok: r.ok, status: r.status, j: j}; });
        });
    }
    /* case names come back as "#<id> - <name>": add the id only when the name lacks it */
    function caseLabel(cid, name) {
        var n = String(name || '');
        return /^#\d+\b/.test(n) ? n : '#' + id(cid) + (n ? ' ' + n : '');
    }
    /* asked live: the room can be closed (or the viewer's role change) while the tab is open */
    function canChange() {
        var open = typeof window.iris_wroom_active === 'function' ? window.iris_wroom_active() : S.ctx.active;
        return !S.ctx.guest && !!open && !!(window.iris_wroom_can && window.iris_wroom_can('responder'));
    }
    function stamp(iso) {
        if (!iso) { return ''; }
        var d = new Date(iso);
        return isNaN(d) ? '' : d.toLocaleDateString() + ', ' + d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    }

    /* ------------------------------------------------------------------------ CSS */
    function css() {
        if (window.IrisFlags && window.IrisFlags.css) { window.IrisFlags.css(); }
        if (document.getElementById('iris-sc-css')) { return; }
        var st = document.createElement('style');
        st.id = 'iris-sc-css';
        st.textContent = [
            '.iris-sc-head{display:flex;align-items:flex-start;gap:12px;margin-bottom:10px;}',
            '.iris-sc-head h5{margin:0;font-weight:600;color:#e8e8ee;}',
            '.iris-sc-sub{color:#7a7a85;font-size:.78rem;}',
            '.iris-sc-views{margin-left:auto;display:inline-flex;border:1px solid rgba(255,255,255,.12);border-radius:8px;overflow:hidden;}',
            '.iris-sc-views button{background:none;border:0;color:#9a9aa5;padding:5px 9px;cursor:pointer;}',
            '.iris-sc-views button[aria-pressed="true"]{background:rgba(94,114,228,.22);color:#e8e8ee;}',
            '.iris-sc-bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;padding:10px;border:1px solid rgba(255,255,255,.07);border-radius:10px;background:rgba(255,255,255,.015);margin-bottom:10px;font-size:.75rem;color:#9a9aa5;}',
            '.iris-sc-bar label{margin:0;display:inline-flex;align-items:center;gap:6px;font-weight:normal;font-size:.75rem!important;color:#9a9aa5!important;white-space:nowrap;}',
            '.iris-sc-bar input::placeholder{color:#62626d;}',
            '.iris-sc-bar select,.iris-sc-bar input[type=text]{height:30px!important;font-size:.76rem;background:rgba(255,255,255,.02)!important;border:1px solid rgba(255,255,255,.12)!important;border-radius:7px!important;color:#d8d8e0!important;padding:0 8px!important;}',
            '.iris-sc-bar select option{background:#1d1d24;color:#d8d8e0;}',
            '.iris-sc-search{position:relative;flex:1 1 240px;min-width:200px;}',
            '.iris-sc-bar .iris-sc-search input[type=text]{width:100%;padding-left:28px!important;}',
            '.iris-sc-search svg{position:absolute;left:9px;top:8px;color:#7a7a85;z-index:2;pointer-events:none;}',
            '.iris-sc-sel{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:7px 10px;border:1px solid rgba(94,114,228,.45);border-radius:10px;background:rgba(94,114,228,.08);margin-bottom:10px;font-size:.78rem;color:#c8c8d0;}',
            '.iris-sc-sel .btn{font-size:.74rem;padding:3px 10px;}',
            '.iris-sc-dd{position:relative;display:inline-block;}',
            '.iris-sc-menu{position:absolute;top:110%;left:0;z-index:30;background:#1d1d24;border:1px solid rgba(255,255,255,.12);border-radius:8px;padding:4px;min-width:200px;box-shadow:0 8px 24px rgba(0,0,0,.45);}',
            '.iris-sc-menu button{display:block;width:100%;text-align:left;background:none;border:0;color:#c8c8d0;padding:5px 9px;border-radius:5px;font-size:.78rem;cursor:pointer;}',
            '.iris-sc-menu button:hover{background:rgba(255,255,255,.07);}',
            '.iris-sc-menu label{display:flex;gap:6px;align-items:center;padding:3px 8px;margin:0;font-size:.76rem;color:#c8c8d0;font-weight:normal;}',
            '.iris-sc-note{margin-bottom:10px;padding:7px 10px;border-radius:8px;font-size:.78rem;background:rgba(45,206,137,.08);border:1px solid rgba(45,206,137,.35);color:#bfeedd;}',
            '.iris-sc-note.iris-sc-warn{background:rgba(244,196,48,.08);border-color:rgba(244,196,48,.4);color:#f3e3a8;}',
            '.iris-sc-note ul{margin:4px 0 0 18px;padding:0;}',
            '.iris-sc-wrap{border:1px solid rgba(255,255,255,.07);border-radius:10px;overflow:auto;max-height:70vh;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,.16) transparent;}',
            '.iris-sc-table{width:100%;font-size:.8rem;border-collapse:collapse;}',
            '.iris-sc-table th{position:sticky;top:0;z-index:2;background:#17171d;color:#7a7a85;font-weight:600;font-size:.72rem;text-align:left;padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.08);white-space:nowrap;}',
            '.iris-sc-table td{padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.05);color:#c8c8d0;vertical-align:middle;}',
            '.iris-sc-table tr[data-asset]:hover td{background:rgba(255,255,255,.02);}',
            '.iris-sc-table tr.iris-sc-on td{background:rgba(94,114,228,.07);}',
            '.iris-sc-grp td{background:rgba(255,255,255,.03);font-size:.76rem;color:#9a9aa5;padding:6px 10px;}',
            '.iris-sc-grp b{color:#e8e8ee;}',
            '.iris-sc-grp .iris-sc-copy{float:right;background:none;border:0;color:#9a9aa5;font-size:.72rem;cursor:pointer;}',
            '.iris-sc-grp .iris-sc-copy:hover{color:#e8e8ee;}',
            '.iris-sc-name{color:#e8e8ee;font-weight:600;}',
            '.iris-sc-pill{display:inline-block;padding:0 8px;border-radius:9px;font-size:.7rem;border:1px solid rgba(255,255,255,.14);white-space:nowrap;}',
            '.iris-sc-red{border-color:rgba(242,89,97,.55);color:#ff9aa5;background:rgba(242,89,97,.08);}',
            '.iris-sc-green{border-color:rgba(45,206,137,.5);color:#7fe0b3;background:rgba(45,206,137,.07);}',
            '.iris-sc-flags{cursor:pointer;display:inline-flex;flex-wrap:wrap;gap:3px;min-height:20px;align-items:center;}',
            '.iris-sc-flags:hover .iris-sc-noflag{color:#c8c8d0;}',
            '.iris-sc-noflag{font-size:.72rem;color:#6a6a75;border:1px dashed rgba(255,255,255,.15);border-radius:8px;padding:0 7px;}',
            '.iris-sc-table .iris-sc-num{text-align:center;font-variant-numeric:tabular-nums;}',
            '.iris-sc-exploited{color:#ff9aa5;font-weight:600;}',
            '.iris-sc-act{background:none;border:0;color:#9a9aa5;padding:2px 4px;border-radius:5px;cursor:pointer;}',
            '.iris-sc-act:hover{color:#e8e8ee;background:rgba(255,255,255,.06);}',
            '.iris-sc-foot{display:flex;align-items:center;gap:10px;margin-top:8px;font-size:.76rem;color:#7a7a85;}',
            '.iris-sc-empty{padding:28px;text-align:center;color:#7a7a85;}',
            '.iris-sc-board{display:flex;gap:10px;overflow-x:auto;padding-bottom:6px;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,.16) transparent;}',
            '.iris-sc-col{flex:0 0 230px;border:1px solid rgba(255,255,255,.07);border-radius:10px;background:rgba(255,255,255,.015);display:flex;flex-direction:column;max-height:65vh;}',
            '.iris-sc-col.iris-sc-over{border-color:rgba(94,114,228,.8);background:rgba(94,114,228,.08);}',
            '.iris-sc-colh{padding:8px 10px;font-size:.76rem;font-weight:600;color:#e8e8ee;display:flex;align-items:center;gap:6px;border-bottom:1px solid rgba(255,255,255,.06);}',
            '.iris-sc-colh span.iris-sc-count{margin-left:auto;color:#7a7a85;font-weight:normal;}',
            '.iris-sc-cards{padding:6px;overflow-y:auto;display:flex;flex-direction:column;gap:6px;min-height:60px;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,.16) transparent;}',
            '.iris-sc-card{border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:6px 8px;background:#1b1b22;font-size:.76rem;color:#c8c8d0;}',
            '.iris-sc-card[draggable="true"]{cursor:grab;}',
            '.iris-sc-card b{color:#e8e8ee;}',
            '.iris-sc-dlg .modal-body{font-size:.82rem;}',
            '.iris-sc-dlg .iris-sc-list{max-height:240px;overflow-y:auto;border:1px solid rgba(255,255,255,.08);border-radius:8px;padding:4px 8px;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,.16) transparent;}',
            '.iris-sc-dlg .iris-sc-list label{display:flex;align-items:center;gap:8px;margin:4px 0;font-weight:normal;color:#c8c8d0;}',
            '.iris-sc-dlg .iris-sc-hint{color:#7a7a85;font-size:.74rem;}',
            '.iris-sc-dlg textarea.form-control,.iris-sc-dlg select.form-control{background:rgba(255,255,255,.03)!important;border:1px solid rgba(255,255,255,.12)!important;color:#d8d8e0!important;}',
            '.iris-sc-dlg select.form-control option{background:#1d1d24;color:#d8d8e0;}'
        ].join('\n');
        document.head.appendChild(st);
    }

    /* ---------------------------------------------------------------------- filters */
    function clean(f) {
        var out = {};
        KEYS.forEach(function (k) {
            var v = f && f[k] != null ? String(f[k]) : '';
            if (v && v.length <= 200) { out[k] = v; }
        });
        return out;
    }
    function query() {
        var parts = [];
        KEYS.forEach(function (k) { if (S.filter[k]) { parts.push(k + '=' + encodeURIComponent(S.filter[k])); } });
        return parts.length ? '?' + parts.join('&') : '';
    }
    function setF(k, v) {
        if (v) { S.filter[k] = String(v); } else { delete S.filter[k]; }
        if (k !== 'page') { delete S.filter.page; }
    }

    /* -------------------------------------------------------------------- loading */
    function load() {
        var seq = ++S.seq;
        S.err = null;
        return api('GET', base() + '/assets' + query()).then(function (res) {
            if (seq !== S.seq) { return; }
            if (!res.ok) { S.err = (res.j && res.j.message) || 'Could not load the scope assets'; S.data = null; } else { S.data = res.j; }
            var keep = {};
            (S.data ? S.data.assets : []).forEach(function (a) { if (S.sel[a.asset_id]) { keep[a.asset_id] = true; } });
            S.sel = keep;
            draw();
            S.done = seq;   /* the newest request's reply is drawn (a probe waits on this, never on a timer) */
        });
    }

    /* ------------------------------------------------------------------------ drawing */
    function opt(v, label, cur) {
        return '<option value="' + esc(v) + '"' + (String(cur || '') === String(v) ? ' selected' : '') + '>' + esc(label) + '</option>';
    }
    function shell() {
        var d = S.data || {}, f = S.filter;
        var cases = d.cases || [], custs = d.customers || [], flags = d.flags || [];
        var sub = S.data ? 'Every asset of the ' + d.case_count + ' attached case' + (d.case_count === 1 ? '' : 's') + ' you can open' +
            (d.cases_restricted ? ', and ' + d.cases_restricted + ' more case' + (d.cases_restricted === 1 ? '' : 's') + ' you cannot open' : '') +
            '. Select assets to set flags or a status in bulk, or push them to other cases.' : 'Loading…';
        var flagVal = f.flag || (f.kind ? 'kind:' + f.kind : '');
        return '<div class="iris-sc-head"><div><h5>Scope ' + IrisHelp.icon('room.scope') + '</h5><div class="iris-sc-sub" data-sc="sub">' +
            esc(sub) + '</div></div><div class="iris-sc-views" role="group" aria-label="View">' +
            '<button type="button" data-sc="view" data-v="table" aria-pressed="' + (S.view === 'table') + '" title="Table view" aria-label="Table view">' + ic('table') + '</button>' +
            '<button type="button" data-sc="view" data-v="board" aria-pressed="' + (S.view === 'board') + '" title="Flag board - drag a card onto a flag to set it" aria-label="Flag board view">' + ic('board') + '</button></div></div>' +
            '<div class="iris-sc-bar" role="search">' +
            '<span class="iris-sc-search">' + ic('search') + '<input type="text" class="form-control" data-sc="q" placeholder="Filter by name, IP, domain, tags…" aria-label="Filter the assets" value="' + esc(f.q || '') + '"></span>' +
            '<label>Case <select class="form-control" data-sc="case_id" aria-label="Filter by case">' + opt('', 'All cases', f.case_id) +
            cases.map(function (c) { return opt(c.case_id, caseLabel(c.case_id, c.case_name), f.case_id); }).join('') + '</select></label>' +
            '<label>Customer <select class="form-control" data-sc="customer_id" aria-label="Filter by customer">' + opt('', 'All customers', f.customer_id) +
            custs.map(function (c) { return opt(c.customer_id, c.name || ('#' + c.customer_id), f.customer_id); }).join('') + '</select></label>' +
            '<label>Flag <select class="form-control" data-sc="flag" aria-label="Filter by flag">' + opt('', 'All flags', flagVal) + opt('none', 'No flag', flagVal) +
            opt('kind:done', 'Any "done" flag', flagVal) + opt('kind:exception', 'Any exception flag', flagVal) +
            flags.map(function (x) { return opt(x.flag_id, x.name + ' (' + x.assets + ')', flagVal); }).join('') + '</select></label>' +
            '<label><input type="checkbox" data-sc="compromised"' + (f.compromised ? ' checked' : '') + '> Compromised only</label>' +
            '<label>Vulnerable <select class="form-control" data-sc="vulnerable" aria-label="Filter by findings">' + opt('', 'All', f.vulnerable) +
            opt('open', 'Open finding', f.vulnerable) + opt('exploited', 'Exploited', f.vulnerable) + opt('kev', 'CISA KEV', f.vulnerable) +
            opt('overdue', 'Overdue', f.vulnerable) + opt('none', 'None', f.vulnerable) + '</select></label>' +
            '<label>Vuln ID <input type="text" class="form-control" data-sc="vuln" list="iris-sc-idents" placeholder="Any identifier" aria-label="Filter by vulnerability identifier" value="' + esc(f.vuln || '') + '" style="width:140px;"></label>' +
            '<datalist id="iris-sc-idents">' + (d.identifiers || []).map(function (x) { return '<option value="' + esc(x) + '">'; }).join('') + '</datalist>' +
            '<label>Sort <select class="form-control" data-sc="sort" aria-label="Sort">' + opt('', 'Case', f.sort) + opt('name', 'Name', f.sort) +
            opt('findings', 'Most findings', f.sort) + opt('compromise', 'Compromised first', f.sort) + opt('updated', 'Recently updated', f.sort) + '</select></label>' +
            '<label>Group by <select class="form-control" data-sc="group" aria-label="Group by">' + opt('case', 'Case', S.group) +
            opt('vulnerability', 'Vulnerability', S.group) + opt('none', 'None', S.group) + '</select></label>' +
            (Object.keys(f).length ? '<a href="#" data-sc="clear">Clear filters</a>' : '') + '</div>' +
            '<div data-sc="selbar"></div><div data-sc="note"></div><div data-sc="body"></div><div data-sc="foot"></div>';
    }
    function draw() {
        if (!S.el) { return; }
        var act = document.activeElement && S.el.contains(document.activeElement) ? document.activeElement : null;
        var typing = act && act.getAttribute('data-sc') === 'q' ? {v: act.value, a: act.selectionStart, b: act.selectionEnd} : null;
        S.el.innerHTML = shell();
        drawSel();
        drawNote();
        drawBody();
        if (typing) {
            var q = S.el.querySelector('[data-sc="q"]');
            q.value = typing.v;
            q.focus();
            q.setSelectionRange(typing.a, typing.b);
        }
    }
    function rows() { return S.data ? S.data.assets : []; }
    function selected() { return rows().filter(function (a) { return S.sel[a.asset_id]; }); }
    function drawSel() {
        var host = S.el.querySelector('[data-sc="selbar"]');
        var sel = selected();
        if (!sel.length || !canChange()) { host.innerHTML = ''; return; }
        host.innerHTML = '<div class="iris-sc-sel" role="toolbar" aria-label="Change the selected assets"><b>' + sel.length + '</b> selected' +
            '<button type="button" class="btn btn-xs btn-dark" data-sc="set-flags">' + ic('flag', 12) + ' Set flags</button>' +
            '<button type="button" class="btn btn-xs btn-dark" data-sc="remove-flags">Remove flags</button>' +
            '<span class="iris-sc-dd"><button type="button" class="btn btn-xs btn-dark" data-sc="menu" data-m="compromise" aria-haspopup="true" title="Set the compromise status of the selected assets">Compromise ' + ic('chevron', 11) + '</button></span>' +
            '<span class="iris-sc-dd"><button type="button" class="btn btn-xs btn-dark" data-sc="menu" data-m="analysis" aria-haspopup="true" title="Set the analysis status of the selected assets">Analysis ' + ic('chevron', 11) + '</button></span>' +
            '<button type="button" class="btn btn-xs btn-dark" data-sc="push-sel">' + ic('push', 12) + ' Push to cases</button>' +
            '<a href="#" data-sc="clear-sel" style="margin-left:auto;">Clear selection</a></div>';
    }
    function drawNote() {
        var host = S.el.querySelector('[data-sc="note"]');
        var n = S.note;
        if (!n) { host.innerHTML = ''; return; }
        host.innerHTML = '<div class="iris-sc-note' + (n.warn ? ' iris-sc-warn' : '') + '" role="status">' + esc(n.text) +
            (n.items && n.items.length ? '<ul>' + n.items.slice(0, 8).map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') +
             (n.items.length > 8 ? '<li>… and ' + (n.items.length - 8) + ' more</li>' : '') + '</ul>' : '') + '</div>';
    }
    function groupsOf(list) {
        var out = [], by = {};
        if (S.group === 'none') { return [{key: 'all', title: 'All assets', rows: list}]; }
        if (S.group === 'vulnerability') {
            list.forEach(function (a) {
                (a.vulns.length ? a.vulns : ['']).forEach(function (v) {
                    if (!by[v]) { by[v] = {key: 'v:' + v, title: v || 'No vulnerability finding', rows: []}; out.push(by[v]); }
                    by[v].rows.push(a);
                });
            });
            out.sort(function (x, y) { return (x.title === 'No vulnerability finding') - (y.title === 'No vulnerability finding') || (x.title < y.title ? -1 : 1); });
            return out;
        }
        list.forEach(function (a) {
            if (!by[a.case_id]) { by[a.case_id] = {key: 'c:' + a.case_id, caseId: a.case_id, title: caseLabel(a.case_id, a.case_name), customer: a.customer_name, rows: []}; out.push(by[a.case_id]); }
            by[a.case_id].rows.push(a);
        });
        return out;
    }
    function compPill(c) {
        var p = COMPROMISE[c] || ['—', ''];
        return '<span class="iris-sc-pill ' + p[1] + '">' + esc(p[0]) + '</span>';
    }
    function flagChips(a) {
        var F = window.IrisFlags;
        return '<span class="iris-sc-flags" data-sc="flags" data-asset="' + id(a.asset_id) + '" role="button" tabindex="0" title="' +
            esc(a.asset_name + ' in case #' + a.case_id + (a.can_write && canChange() ? ', change flags' : '')) + '">' +
            (a.flags.length ? a.flags.map(function (x) { return F ? F.chip(x) : esc(x.name); }).join('') : '<span class="iris-sc-noflag">No flag</span>') + '</span>';
    }
    function rowHtml(a) {
        var v = a.findings || {};
        var guest = S.ctx.guest;
        return '<tr data-asset="' + id(a.asset_id) + '"' + (S.sel[a.asset_id] ? ' class="iris-sc-on"' : '') + '>' +
            '<td>' + (canChange() ? '<input type="checkbox" data-sc="pick" data-asset="' + id(a.asset_id) + '"' + (S.sel[a.asset_id] ? ' checked' : '') +
                ' aria-label="Select ' + esc(a.asset_name) + '">' : '') + '</td>' +
            '<td>' + (guest ? '<span class="iris-sc-name">' + esc(a.asset_name) + '</span>' : '<a class="iris-sc-name" href="' + esc(a.href) + '">' + esc(a.asset_name) + '</a>') +
            ((S.group !== 'case' || a.asset_domain) ? '<div class="iris-sc-sub">' + esc([S.group !== 'case' ? caseLabel(a.case_id, a.case_name) : '', a.asset_domain || '']
                .filter(Boolean).join(' \u00b7 ')) + '</div>' : '') + '</td>' +
            '<td>' + esc(a.asset_type || '') + '</td><td>' + esc(a.asset_ip || '—') + '</td><td>' + esc(a.customer_name || '') + '</td>' +
            '<td>' + compPill(a.compromise) + '</td><td>' + esc(a.analysis || '') + '</td><td>' + flagChips(a) + '</td>' +
            '<td class="iris-sc-num">' + (a.ioc_count || '') + '</td>' +
            '<td class="iris-sc-num">' + (v.open ? '<a href="' + esc(a.vulns_href) + '"' + (v.exploited_open ? ' class="iris-sc-exploited" title="' + v.exploited_open + ' exploited"' : '') + '>' + v.open + '</a>' : '') + '</td>' +
            '<td style="white-space:nowrap;">' + esc(stamp(a.updated_at)) + '</td>' +
            '<td>' + (canChange() ? '<button type="button" class="iris-sc-act" data-sc="push-one" data-asset="' + id(a.asset_id) + '" title="Push ' + esc(a.asset_name) + ' to other cases" aria-label="Push ' + esc(a.asset_name) + ' to other cases">' + ic('push') + '</button>' : '') + '</td></tr>';
    }
    function groupHead(g, i) {
        var done = g.rows.filter(function (a) { return a.flags.some(function (x) { return x.kind === 'done'; }); }).length;
        return '<tr class="iris-sc-grp"><td colspan="12"><b>' + esc(g.title) + '</b>' + (g.customer ? ' · ' + esc(g.customer) : '') +
            ' · ' + g.rows.length + ' asset' + (g.rows.length === 1 ? '' : 's') + ' · ' + done + ' done' +
            '<button type="button" class="iris-sc-copy" data-sc="copy" data-g="' + i + '" title="Copy the assets of this group as a table, picking the columns" aria-label="Copy the assets - ' + esc(g.title) + '">' + ic('copy', 12) + ' Copy…</button></td></tr>';
    }
    function drawBody() {
        var host = S.el.querySelector('[data-sc="body"]'), foot = S.el.querySelector('[data-sc="foot"]');
        if (S.err) { host.innerHTML = '<div class="iris-sc-empty" data-sc="empty" role="alert">' + esc(S.err) + '</div>'; foot.innerHTML = ''; return; }
        if (!S.data) { host.innerHTML = '<div class="iris-sc-empty">Loading…</div>'; foot.innerHTML = ''; return; }
        var d = S.data, list = rows();
        if (!d.case_count) {
            host.innerHTML = '<div class="iris-sc-empty" data-sc="empty">No case attached to this war room that you can open.</div>';
            foot.innerHTML = '';
            return;
        }
        if (!d.total) {
            host.innerHTML = '<div class="iris-sc-empty" data-sc="empty">' + (d.summary && d.summary.assets ? 'No asset matches.' : 'The attached cases you can open have no asset yet.') + '</div>';
            foot.innerHTML = '';
            return;
        }
        S.groups = groupsOf(list);
        if (S.view === 'board') { host.innerHTML = boardHtml(list); } else {
            var all = canChange() && list.length && list.every(function (a) { return S.sel[a.asset_id]; });
            host.innerHTML = '<div class="iris-sc-wrap"><table class="iris-sc-table" data-sc="table"><thead><tr>' +
                '<th>' + (canChange() ? '<input type="checkbox" data-sc="pick-all"' + (all ? ' checked' : '') + ' aria-label="Select all visible assets" title="Select all visible assets">' : '') + '</th>' +
                '<th>Asset</th><th>Type</th><th>IP</th><th>Customer</th><th>Compromise</th><th title="Investigation progress (case analysis status)">Analysis</th>' +
                '<th title="Status flags (isolated, patched…)">Flags ' + IrisHelp.icon('flags.asset') + '</th><th class="iris-sc-num">IOCs</th>' +
                '<th class="iris-sc-num" title="Open vulnerability findings">Vulns</th><th>Updated</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody>' +
                S.groups.map(function (g, i) { return groupHead(g, i) + g.rows.map(rowHtml).join(''); }).join('') + '</tbody></table></div>';
        }
        var page = Number(d.page) || 1, per = Number(d.per_page) || 100;
        var from = (page - 1) * per + 1, to = Math.min(d.total, page * per);
        foot.innerHTML = '<div class="iris-sc-foot" data-sc="range">' + from + '–' + to + ' of ' + d.total + ' asset' + (d.total === 1 ? '' : 's') +
            (d.total > per ? ' <button type="button" class="btn btn-xs btn-dark" data-sc="prev"' + (page <= 1 ? ' disabled' : '') + '>Previous</button>' +
             '<button type="button" class="btn btn-xs btn-dark" data-sc="next"' + (to >= d.total ? ' disabled' : '') + '>Next</button>' : '') + '</div>';
    }
    function boardHtml(list) {
        var flags = S.data.flags || [];
        var cols = [{flag_id: 0, name: 'No flag', color: 'slate', icon: 'flag'}].concat(flags);
        var drag = canChange();
        return '<div class="iris-sc-board" data-sc="board">' + cols.map(function (f) {
            var cards = list.filter(function (a) { return f.flag_id ? a.flags.some(function (x) { return x.flag_id === f.flag_id; }) : !a.flags.length; });
            var F = window.IrisFlags;
            return '<div class="iris-sc-col" data-sc="col" data-flag="' + id(f.flag_id) + '"><div class="iris-sc-colh">' +
                (f.flag_id && F ? '<span style="color:' + F.color(f.color) + ';">' + F.icon(f.icon, 13) + '</span>' : '') + esc(f.name) +
                '<span class="iris-sc-count">' + cards.length + '</span></div><div class="iris-sc-cards">' + cards.map(function (a) {
                    return '<div class="iris-sc-card" data-sc="card" data-asset="' + id(a.asset_id) + '"' + (drag && a.can_write ? ' draggable="true"' : '') +
                        ' title="' + esc(a.asset_name + ' in case #' + a.case_id) + '"><b>' + esc(a.asset_name) + '</b><div class="iris-sc-sub">#' + id(a.case_id) +
                        ' · ' + esc(a.asset_type || '') + '</div><div style="margin-top:3px;">' + compPill(a.compromise) + '</div></div>';
                }).join('') + '</div></div>';
        }).join('') + '</div>';
    }

    /* -------------------------------------------------------------------- dialogs */
    function dialog(title, bodyHtml, okLabel, onOk) {
        var old = document.getElementById('iris-sc-dlg');
        if (old) {   /* never two: the old one goes with its backdrop */
            $(old).off('hidden.bs.modal');
            old.remove();
            $('.modal-backdrop').remove();
            document.body.classList.remove('modal-open');
        }
        var m = document.createElement('div');
        m.className = 'modal fade iris-sc-dlg';
        m.id = 'iris-sc-dlg';
        m.tabIndex = -1;
        m.setAttribute('role', 'dialog');
        m.setAttribute('aria-labelledby', 'iris-sc-dlg-title');
        m.innerHTML = '<div class="modal-dialog" role="document" style="max-width:560px;"><div class="modal-content">' +
            '<div class="modal-header" style="border-bottom:0;padding-bottom:0;"><h5 class="modal-title" id="iris-sc-dlg-title">' + esc(title) + '</h5>' +
            '<button type="button" class="close" data-dismiss="modal" aria-label="Close"><span>&times;</span></button></div>' +
            '<div class="modal-body">' + bodyHtml + '<div class="iris-fl-err" data-sc="dlg-err" role="alert" style="display:none;color:#ff8095;margin-top:8px;"></div></div>' +
            '<div class="modal-footer" style="border-top:0;"><button type="button" class="btn btn-outline-dark" data-dismiss="modal">Cancel</button>' +
            '<button type="button" class="btn btn-primary" data-sc="dlg-ok">' + esc(okLabel) + '</button></div></div></div>';
        document.body.appendChild(m);
        /* onOk answers a problem to show (nothing sent), or the request it sent: OK stays disabled until it settles */
        var ok = m.querySelector('[data-sc="dlg-ok"]');
        ok.addEventListener('click', function () {
            var err = m.querySelector('[data-sc="dlg-err"]');
            var r = onOk(m);
            if (typeof r === 'string') { err.textContent = r; err.style.display = ''; return; }
            if (r && typeof r.then === 'function') {
                ok.disabled = true;
                r.then(function () { ok.disabled = false; }, function () { ok.disabled = false; });
            }
        });
        m.__shown = false;
        $(m).one('shown.bs.modal', function () { m.__shown = true; });
        $(m).on('hidden.bs.modal', function () { m.remove(); });
        $(m).modal('show');
        return m;
    }
    /* Bootstrap 4 ignores a hide until the dialog has finished opening - the "show" class comes before that
       (lessons 285, 290): a quick answer closes it once it is shown */
    function closeDlg(m) {
        var $m = $(m);
        if (m.__shown) { $m.modal('hide'); } else { $m.one('shown.bs.modal', function () { $m.modal('hide'); }); }
    }
    function loadDecisions() {
        if (S.decisions) { return Promise.resolve(S.decisions); }
        return api('GET', '/api/v2/war-rooms/' + id(S.ctx.roomId) + '/decisions?status=approved').then(function (res) {
            S.decisions = res.ok ? (res.j.decisions || []) : [];
            return S.decisions;
        });
    }
    function flagsDialog(mode, assets, preset) {
        var flags = (S.data && S.data.flags) || [];
        if (!flags.length) { note('No asset flag is configured. An administrator can add them in Settings → Asset flags.', true); return; }
        loadDecisions().then(function (decisions) {
            var who = assets.length === 1 ? assets[0].asset_name : assets.length + ' assets';
            var body = '<div class="iris-sc-hint mb-2">' + (mode === 'set' ? 'Pick the flags to set on ' : 'Pick the flags to remove from ') + esc(who) + '.</div>' +
                '<div class="iris-sc-list" data-sc="flag-list">' + flags.map(function (f) {
                    return '<label><input type="checkbox" value="' + id(f.flag_id) + '"' + (preset === f.flag_id ? ' checked' : '') + '> ' +
                        (window.IrisFlags ? window.IrisFlags.chip(f) : esc(f.name)) +
                        (f.requires_reason ? ' <span class="iris-sc-hint">needs a reason</span>' : '') +
                        (f.requires_decision && mode === 'set' ? ' <span class="iris-sc-hint">needs a decision</span>' : '') + '</label>';
                }).join('') + '</div>' +
                '<label for="iris-sc-reason" class="mt-2 iris-sc-hint">Reason <span data-sc="reason-req"></span></label>' +
                '<textarea id="iris-sc-reason" class="form-control form-control-sm" rows="2" data-sc="reason"></textarea>' +
                (mode === 'set' ? '<div data-sc="decision-row" style="display:none;"><label for="iris-sc-decision" class="mt-2 iris-sc-hint">Decision (a picked flag requires a decision from the register)</label>' +
                    '<select id="iris-sc-decision" class="form-control form-control-sm" data-sc="decision"><option value="">Pick an approved decision</option>' +
                    decisions.map(function (dd) { return '<option value="' + id(dd.decision_id || dd.id) + '">' + esc((dd.ref || '') + ' ' + (dd.title || '')) + '</option>'; }).join('') +
                    '</select>' + (decisions.length ? '' : '<div class="iris-sc-hint mt-1">The room has no approved decision yet.</div>') + '</div>' : '');
            var m = dialog(mode === 'set' ? 'Set flags on ' + who : 'Remove flags from ' + who, body, mode === 'set' ? 'Set flags' : 'Remove flags', function (mm) {
                var picked = Array.prototype.map.call(mm.querySelectorAll('[data-sc="flag-list"] input:checked'), function (x) { return id(x.value); });
                if (!picked.length) { return 'Pick at least one flag.'; }
                var reason = mm.querySelector('[data-sc="reason"]').value.trim();
                var pf = flags.filter(function (f) { return picked.indexOf(f.flag_id) !== -1; });
                if (pf.some(function (f) { return f.requires_reason; }) && !reason) { return 'A picked flag requires a reason.'; }
                var dec = mode === 'set' ? id((mm.querySelector('[data-sc="decision"]') || {}).value) : 0;
                if (mode === 'set' && pf.some(function (f) { return f.requires_decision; }) && !dec) { return 'A picked flag requires a decision from the register.'; }
                var body2 = {asset_ids: assets.map(function (a) { return a.asset_id; }), flag_ids: picked, action: mode === 'set' ? 'set' : 'remove'};
                if (reason) { body2.reason = reason; }
                if (dec) { body2.decision_id = dec; }
                return api('POST', base() + '/assets/flags', body2).then(function (res) {
                    if (!res.ok) { var e = mm.querySelector('[data-sc="dlg-err"]'); e.textContent = (res.j && res.j.message) || 'The server refused the change.'; e.style.display = ''; return; }
                    closeDlg(mm);
                    report(res.j, mode === 'set' ? 'Flags set' : 'Flags removed');
                    load();
                });
            });
            function sync() {
                var picked = Array.prototype.map.call(m.querySelectorAll('[data-sc="flag-list"] input:checked'), function (x) { return id(x.value); });
                var pf = flags.filter(function (f) { return picked.indexOf(f.flag_id) !== -1; });
                m.querySelector('[data-sc="reason-req"]').textContent = pf.some(function (f) { return f.requires_reason; }) ? '(required)' : '(optional)';
                var dr = m.querySelector('[data-sc="decision-row"]');
                if (dr) { dr.style.display = pf.some(function (f) { return f.requires_decision; }) ? '' : 'none'; }
            }
            m.addEventListener('change', sync);
            sync();
        });
    }
    function pushDialog(assets) {
        var own = {};
        assets.forEach(function (a) { own[a.case_id] = true; });
        var targets = (S.data.cases || []).filter(function (c) { return c.can_write && !(assets.length === 1 && own[c.case_id]); });
        var who = assets.length === 1 ? assets[0].asset_name : assets.length + ' assets';
        if (!targets.length) { note('No other attached case you can change.', true); return; }
        var body = '<div class="iris-sc-hint mb-2">Copies name, type, description, IP, domain, tags, compromise and analysis status. The flags are not copied. ' +
            'A case that already holds the asset is skipped.</div><div class="iris-sc-list" data-sc="case-list">' + targets.map(function (c) {
                return '<label><input type="checkbox" value="' + id(c.case_id) + '"> ' + esc(caseLabel(c.case_id, c.case_name)) +
                    (c.customer_name ? ' <span class="iris-sc-hint">' + esc(c.customer_name) + '</span>' : '') + '</label>';
            }).join('') + '</div>';
        dialog(assets.length === 1 ? 'Push ' + who + ' to other cases' : 'Push ' + who + ' to cases', body, 'Push', function (mm) {
            var cases = Array.prototype.map.call(mm.querySelectorAll('[data-sc="case-list"] input:checked'), function (x) { return id(x.value); });
            if (!cases.length) { return 'Pick at least one case.'; }
            return api('POST', base() + '/assets/push', {asset_ids: assets.map(function (a) { return a.asset_id; }), case_ids: cases}).then(function (res) {
                if (!res.ok) { var e = mm.querySelector('[data-sc="dlg-err"]'); e.textContent = (res.j && res.j.message) || 'The server refused the push.'; e.style.display = ''; return; }
                closeDlg(mm);
                report(res.j, 'Pushed');
                load();
            });
        });
    }
    function assetFlagsDialog(a) {
        var m = dialog('Flags of ' + a.asset_name, '<div class="iris-sc-hint mb-2">' + esc(a.asset_name + ' in case #' + a.case_id) + '</div><div data-sc="flag-host"></div>', 'Done', function (mm) { closeDlg(mm); });
        var asset = {asset_id: a.asset_id, asset_name: a.asset_name, flags: a.flags.slice()};
        function render() {
            if (!window.IrisFlags) { return; }
            window.IrisFlags.renderAssetFlags(m.querySelector('[data-sc="flag-host"]'), {
                caseId: a.case_id, asset: asset, canWrite: !!(a.can_write && canChange()),
                onChange: function (flags) { asset.flags = flags; render(); load(); }
            });
        }
        render();
    }
    function note(text, warn, items) { S.note = {text: text, warn: !!warn, items: items || []}; if (S.el) { drawNote(); } }
    function report(res, verb) {
        var c = res.counts || {}, refused = (res.results || []).filter(function (r) { return r.status === 'refused'; });
        var parts = [];
        Object.keys(c).forEach(function (k) {
            var label = {set: 'set', updated: 'updated', unchanged: 'unchanged', cleared: 'removed', not_set: 'not set (nothing to remove)',
                         changed: 'changed', created: 'created', exists: 'already there', refused: 'refused'}[k] || k;
            parts.push(c[k] + ' ' + label);
        });
        note(verb + ': ' + parts.join(' · '), !!refused.length, refused.map(function (r) {
            return (r.asset_name || ('asset #' + r.asset_id)) + (r.target_case_id ? ' → case #' + r.target_case_id : '') + ': ' + (r.error || 'refused');
        }));
    }
    function statusMenu(btn, kind) {
        closeMenus();
        var items = kind === 'compromise' ? (S.data.compromise_statuses || []).map(function (s) { return [s.key, s.label]; })
            : (S.data.analysis_statuses || []).map(function (s) { return [String(s.id), s.name]; });
        var mnu = document.createElement('div');
        mnu.className = 'iris-sc-menu';
        mnu.setAttribute('role', 'menu');
        mnu.innerHTML = items.map(function (it) { return '<button type="button" role="menuitem" data-v="' + esc(it[0]) + '">' + esc(it[1]) + '</button>'; }).join('');
        btn.parentNode.appendChild(mnu);
        mnu.addEventListener('click', function (e) {
            var b = e.target.closest('[data-v]');
            if (!b) { return; }
            closeMenus();
            var body = {asset_ids: selected().map(function (a) { return a.asset_id; })};
            if (kind === 'compromise') { body.compromise = b.getAttribute('data-v'); } else { body.analysis_status_id = id(b.getAttribute('data-v')); }
            api('POST', base() + '/assets/status', body).then(function (res) {
                if (!res.ok) { note((res.j && res.j.message) || 'Could not change the status', true); return; }
                report(res.j, kind === 'compromise' ? 'Compromise status' : 'Analysis status');
                load();
            });
        });
    }
    function copyMenu(btn, g) {
        closeMenus();
        var mnu = document.createElement('div');
        mnu.className = 'iris-sc-menu';
        mnu.style.left = 'auto';
        mnu.style.right = '0';
        mnu.innerHTML = '<div class="iris-sc-hint" style="padding:3px 8px;">Columns</div>' + COLS.map(function (c) {
            return '<label><input type="checkbox" value="' + c[0] + '"' + (c[0] === 'domain' ? '' : ' checked') + '> ' + esc(c[1]) + '</label>';
        }).join('') + '<button type="button" data-v="copy">' + ic('copy', 12) + ' Copy as a table</button><button type="button" data-v="csv">Download CSV</button>';
        btn.parentNode.style.position = 'relative';
        btn.parentNode.appendChild(mnu);
        mnu.addEventListener('click', function (e) {
            var b = e.target.closest('[data-v]');
            if (!b) { return; }
            var cols = Array.prototype.map.call(mnu.querySelectorAll('input:checked'), function (x) { return x.value; });
            var table = [cols.map(function (k) { return COLS.filter(function (c) { return c[0] === k; })[0][1]; })].concat(g.rows.map(function (a) { return cols.map(function (k) { return cell(a, k); }); }));
            closeMenus();
            if (b.getAttribute('data-v') === 'csv') {
                var csv = table.map(function (r) { return r.map(function (v) { return /[",\n;]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }).join(','); }).join('\n');
                var a = document.createElement('a');
                a.href = URL.createObjectURL(new Blob([csv], {type: 'text/csv'}));
                a.download = 'scope-' + g.key.replace(/[^a-z0-9-]+/gi, '-') + '.csv';
                document.body.appendChild(a);
                a.click();
                a.remove();
                return;
            }
            var tsv = table.map(function (r) { return r.map(function (v) { return String(v).replace(/[\t\n]+/g, ' '); }).join('\t'); }).join('\n');
            copyText(tsv).then(function () { note('Copied ' + g.rows.length + ' asset' + (g.rows.length === 1 ? '' : 's') + ' (' + cols.length + ' columns) - paste it into a sheet or a note.'); },
                function () { note('Could not copy: the browser refused access to the clipboard.', true); });
        });
    }
    function cell(a, k) {
        switch (k) {
        case 'asset': return a.asset_name || '';
        case 'case': return caseLabel(a.case_id, a.case_name);
        case 'type': return a.asset_type || '';
        case 'ip': return a.asset_ip || '';
        case 'domain': return a.asset_domain || '';
        case 'customer': return a.customer_name || '';
        case 'compromise': return (COMPROMISE[a.compromise] || [''])[0];
        case 'analysis': return a.analysis || '';
        case 'flags': return a.flags.map(function (x) { return x.name; }).join(', ');
        case 'iocs': return String(a.ioc_count || 0);
        case 'vulns': return String((a.findings || {}).open || 0);
        case 'updated': return a.updated_at || '';
        default: return '';
        }
    }
    function copyText(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) { return navigator.clipboard.writeText(text); }
        return new Promise(function (ok, no) {
            var t = document.createElement('textarea');
            t.value = text;
            document.body.appendChild(t);
            t.select();
            var done = false;
            try { done = document.execCommand('copy'); } catch (e) { done = false; }
            t.remove();
            if (done) { ok(); } else { no(new Error('copy')); }
        });
    }
    /* the selection bar, every row's box and highlight, and the select-all box, without redrawing the table */
    function syncPicks() {
        drawSel();
        if (!S.el) { return; }
        S.el.querySelectorAll('[data-sc="pick"]').forEach(function (b) {
            var on = !!S.sel[id(b.getAttribute('data-asset'))];
            b.checked = on;
            var tr = b.closest('tr');
            if (tr) { tr.classList.toggle('iris-sc-on', on); }
        });
        var all = S.el.querySelector('[data-sc="pick-all"]');
        if (all) { all.checked = rows().length > 0 && rows().every(function (a) { return S.sel[a.asset_id]; }); }
    }
    function closeMenus() { if (S.el) { S.el.querySelectorAll('.iris-sc-menu').forEach(function (m) { m.remove(); }); } }
    function rowById(aid) { return rows().filter(function (a) { return a.asset_id === id(aid); })[0]; }

    /* ---------------------------------------------------------------------- wiring */
    var timer = null;
    function wire() {
        var el = S.el;
        el.addEventListener('input', function (e) {
            var k = e.target.getAttribute('data-sc');
            if (k === 'q') {
                clearTimeout(timer);
                var v = e.target.value.trim();
                timer = setTimeout(function () { setF('q', v); load(); }, 300);
            }
        });
        el.addEventListener('change', function (e) {
            var t = e.target, k = t.getAttribute('data-sc');
            if (k === 'case_id' || k === 'customer_id' || k === 'vulnerable') { setF(k, t.value); load(); return; }
            if (k === 'sort') { setF('sort', t.value); setF('dir', /^(findings|compromise|updated)$/.test(t.value) ? 'desc' : ''); load(); return; }
            if (k === 'flag') {
                delete S.filter.kind;
                if (/^kind:/.test(t.value)) { setF('flag', ''); setF('kind', t.value.slice(5)); } else { setF('flag', t.value); }
                load();
                return;
            }
            if (k === 'compromised') { setF('compromised', t.checked ? '1' : ''); load(); return; }
            if (k === 'vuln') { setF('vuln', t.value.trim()); load(); return; }
            if (k === 'group') { S.group = t.value; drawBody(); return; }
            if (k === 'pick') {
                var aid = id(t.getAttribute('data-asset'));
                if (t.checked) { S.sel[aid] = true; } else { delete S.sel[aid]; }
                syncPicks();
                return;
            }
            if (k === 'pick-all') { rows().forEach(function (a) { if (t.checked) { S.sel[a.asset_id] = true; } else { delete S.sel[a.asset_id]; } }); syncPicks(); }
        });
        el.addEventListener('keydown', function (e) {
            if (e.target.getAttribute('data-sc') === 'vuln' && e.key === 'Enter') { e.preventDefault(); setF('vuln', e.target.value.trim()); load(); }
            if (e.target.getAttribute('data-sc') === 'flags' && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); e.target.click(); }
        });
        el.addEventListener('click', function (e) {
            var b = e.target.closest('[data-sc]');
            if (!b) { if (!e.target.closest('.iris-sc-menu')) { closeMenus(); } return; }
            var k = b.getAttribute('data-sc');
            if (k === 'view') { S.view = b.getAttribute('data-v'); el.querySelectorAll('[data-sc="view"]').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); }); drawBody(); return; }
            if (k === 'clear') { e.preventDefault(); S.filter = {}; load(); return; }
            if (k === 'clear-sel') { e.preventDefault(); S.sel = {}; syncPicks(); return; }
            if (k === 'set-flags' || k === 'remove-flags') { flagsDialog(k === 'set-flags' ? 'set' : 'remove', selected()); return; }
            if (k === 'push-sel') { pushDialog(selected()); return; }
            if (k === 'push-one') { pushDialog([rowById(b.getAttribute('data-asset'))]); return; }
            if (k === 'menu') { if (b.parentNode.querySelector('.iris-sc-menu')) { closeMenus(); } else { statusMenu(b, b.getAttribute('data-m')); } return; }
            if (k === 'copy') { if (b.parentNode.querySelector('.iris-sc-menu')) { closeMenus(); } else { copyMenu(b, S.groups[id(b.getAttribute('data-g'))]); } return; }
            if (k === 'flags') { var a = rowById(b.getAttribute('data-asset')); if (a) { assetFlagsDialog(a); } return; }
            if (k === 'prev' || k === 'next') { setF('page', String(Math.max(1, (S.data.page || 1) + (k === 'next' ? 1 : -1)))); load(); return; }
        });
        /* the flag board: drag a card onto a flag to set it */
        el.addEventListener('dragstart', function (e) {
            var c = e.target.closest && e.target.closest('[data-sc="card"]');
            if (!c) { return; }
            e.dataTransfer.setData('text/plain', c.getAttribute('data-asset'));
            e.dataTransfer.effectAllowed = 'move';
            S.dragging = id(c.getAttribute('data-asset'));
        });
        el.addEventListener('dragover', function (e) {
            var col = e.target.closest && e.target.closest('[data-sc="col"]');
            if (!col || !S.dragging || !id(col.getAttribute('data-flag'))) { return; }
            e.preventDefault();
            el.querySelectorAll('.iris-sc-over').forEach(function (x) { if (x !== col) { x.classList.remove('iris-sc-over'); } });
            col.classList.add('iris-sc-over');
        });
        el.addEventListener('dragleave', function (e) {
            var col = e.target.closest && e.target.closest('[data-sc="col"]');
            if (col && !col.contains(e.relatedTarget)) { col.classList.remove('iris-sc-over'); }
        });
        el.addEventListener('drop', function (e) {
            var col = e.target.closest && e.target.closest('[data-sc="col"]');
            el.querySelectorAll('.iris-sc-over').forEach(function (x) { x.classList.remove('iris-sc-over'); });
            if (!col || !S.dragging) { return; }
            e.preventDefault();
            var fid = id(col.getAttribute('data-flag')), a = rowById(S.dragging);
            S.dragging = null;
            if (!fid || !a || a.flags.some(function (x) { return x.flag_id === fid; })) { return; }
            var f = (S.data.flags || []).filter(function (x) { return x.flag_id === fid; })[0];
            if (f && (f.requires_reason || f.requires_decision)) { flagsDialog('set', [a], fid); return; }
            api('POST', base() + '/assets/flags', {asset_ids: [a.asset_id], flag_ids: [fid], action: 'set'}).then(function (res) {
                if (!res.ok) { note((res.j && res.j.message) || 'Could not set the flag', true); return; }
                report(res.j, (f ? f.name : 'Flag') + ' on ' + a.asset_name);
                load();
            });
        });
        el.addEventListener('dragend', function () { S.dragging = null; });
    }

    /* ---------------------------------------------------------------------- public */
    R.mount = function (el, ctx) {
        css();
        var fresh = S.el !== el;
        S.el = el;
        S.ctx = ctx;
        if (fresh) { wire(); }
        draw();
        return load();
    };
    R.setFilter = function (f) {
        S.filter = clean(f);
        S.sel = {};
        S.note = null;
        if (S.el) { draw(); load(); }
    };
    R.reload = function () { return S.el ? load() : Promise.resolve(); };
    R._state = S;
    window.IrisRoomScope = R;
}());

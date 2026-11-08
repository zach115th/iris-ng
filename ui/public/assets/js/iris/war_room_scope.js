/* War-room Scope as a workspace (iris-ng 2026-11-08).
 *
 * window.IrisRoomScope - import-free (ui/public). Sub-tabs over the attached cases the viewer can open:
 *   Assets - a table (type, IP, customer, compromise, analysis, flags, IOCs, open findings, updated) grouped by
 *     case, by vulnerability or not at all, or a flag board (drag a card onto a flag to set it); select assets to
 *     set / remove flags, set the compromise or analysis status, record a vulnerability, or push (copy) them to
 *     other attached cases; copy a group as a table (clipboard or CSV); below, the assets attached from the
 *     Assets Manager (customer registry): link to a case, push into cases, detach.
 *   IOCs - one row per indicator, one column per case (present, or a push into it); select and push.
 *   Customers - the scope summed per customer. Vulnerabilities - the room's tracked entries and findings
 *     (vuln_common.js, IrisVuln.mountWarRoom). Staging - assets / IOCs waiting with the cases they are meant for.
 *   Header: Add asset / Add IOC (into several cases at once, or "Stage for later"), Export (blocklist txt / CSV /
 *     STIX), Attach from Assets Manager.
 * A copy across customers comes back 409 (data.code = cross_customer, the customers named): the dialog shows the
 * warning and resends with confirm_cross_customer once the user says so.
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
    var S = {el: null, ctx: null, tab: 'assets', filter: {}, group: 'case', view: 'table', data: null, seq: 0, done: 0, sel: {},
             note: null, err: null, decisions: null, counts: null, reg: null, tabs: {}, vocab: null, vulnEl: null};
    /* the sub-tabs: [key, label, icon] */
    var TABS = [['assets', 'Assets', 'server'], ['iocs', 'IOCs', 'bug'], ['customers', 'Customers', 'building'],
                ['vulnerabilities', 'Vulnerabilities', 'shield'], ['staging', 'Staging', 'inbox']];
    var TLP_CLASS = {red: 'iris-sc-red', amber: 'iris-sc-amber', 'amber+strict': 'iris-sc-amber', green: 'iris-sc-green', clear: ''};
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
        chevron: '<path d="m6 9 6 6 6-6"/>',
        server: '<rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/>',
        bug: '<path d="m8 2 1.88 1.88"/><path d="M14.12 3.88 16 2"/><path d="M9 7.13v-1a3.003 3.003 0 1 1 6 0v1"/><path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6"/><path d="M12 20v-9"/><path d="M6.53 9C4.6 8.8 3 7.1 3 5"/><path d="M6 13H2"/><path d="M3 21c0-2.1 1.7-3.9 3.8-4"/><path d="M20.97 5c0 2.1-1.6 3.8-3.5 4"/><path d="M22 13h-4"/><path d="M17.2 17c2.1.1 3.8 1.9 3.8 4"/>',
        building: '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/>',
        shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
        inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
        download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
        clip: '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
        plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
        check: '<path d="M20 6 9 17l-5-5"/>',
        pencil: '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
        trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
        unlink: '<path d="m18.84 12.25 1.72-1.71h-.02a5.004 5.004 0 0 0-.12-7.07 5.006 5.006 0 0 0-6.95 0l-1.72 1.71"/><path d="m5.17 11.75-1.71 1.71a5.004 5.004 0 0 0 .12 7.07 5.006 5.006 0 0 0 6.95 0l1.71-1.71"/><line x1="8" x2="8" y1="2" y2="5"/><line x1="2" x2="5" y1="8" y2="8"/><line x1="16" x2="16" y1="19" y2="22"/><line x1="19" x2="22" y1="16" y2="16"/>',
        alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>'
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
            '.iris-sc-dlg select.form-control option{background:#1d1d24;color:#d8d8e0;}',
            '.iris-sc-dlg input.form-control{background:rgba(255,255,255,.03)!important;border:1px solid rgba(255,255,255,.12)!important;color:#d8d8e0!important;}',
            '.iris-sc-dlg .iris-sc-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px 12px;}',
            '.iris-sc-dlg .iris-sc-fl{display:block;margin:0 0 2px;font-size:.72rem!important;color:#9a9aa5!important;font-weight:normal;}',
            '.iris-sc-dlg input::placeholder,.iris-sc-dlg textarea::placeholder{color:#5a5a65;}',
            '.iris-sc-hint{color:#7a7a85;font-size:.74rem;font-weight:normal;}',
            '.iris-sc-menu .iris-sc-hint{font-size:.72rem;line-height:1.4;}',
            '.iris-sc-acts{margin-left:auto;display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end;align-items:center;}',
            '.iris-sc-acts .btn{font-size:.76rem;padding:4px 10px;display:inline-flex;align-items:center;gap:5px;}',
            '.iris-sc-tabs{display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap;}',
            '.iris-sc-tabs .iris-sc-views{margin-left:0;}',
            '.iris-sc-tablist{display:inline-flex;flex-wrap:wrap;gap:2px;border:1px solid rgba(255,255,255,.1);border-radius:9px;padding:2px;}',
            '.iris-sc-tablist button{background:none;border:0;color:#9a9aa5;padding:5px 10px;border-radius:7px;font-size:.78rem;display:inline-flex;align-items:center;gap:5px;cursor:pointer;}',
            '.iris-sc-tablist button.active{background:rgba(255,255,255,.07);color:#e8e8ee;font-weight:600;}',
            '.iris-sc-tcount{font-size:.66rem;color:#7a7a85;background:rgba(255,255,255,.06);border-radius:8px;padding:0 6px;min-width:18px;text-align:center;font-weight:normal;}',
            '.iris-sc-sec{display:flex;align-items:center;gap:6px;margin:18px 0 6px;font-size:.78rem;font-weight:600;color:#c8c8d0;}',
            '.iris-sc-amber{border-color:rgba(244,196,48,.5);color:#f3d77e;background:rgba(244,196,48,.07);}',
            '.iris-sc-ok{color:#7fe0b3;}',
            '.iris-sc-cell{background:none;border:1px dashed rgba(255,255,255,.18);color:#9a9aa5;border-radius:6px;width:22px;height:22px;line-height:18px;padding:0;cursor:pointer;}',
            '.iris-sc-cell:hover{color:#e8e8ee;border-color:rgba(94,114,228,.7);}',
            '.iris-sc-dot{color:#4e4e58;}',
            '.iris-sc-staged{border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:10px 12px;margin-bottom:8px;background:rgba(255,255,255,.015);display:flex;gap:12px;align-items:flex-start;font-size:.8rem;color:#c8c8d0;}',
            '.iris-sc-chip{display:inline-flex;align-items:center;gap:3px;border:1px solid rgba(255,255,255,.14);border-radius:8px;padding:0 7px;font-size:.7rem;color:#9a9aa5;margin:3px 4px 0 0;}',
            '.iris-sc-chip.iris-sc-has{border-color:rgba(45,206,137,.5);color:#7fe0b3;}',
            '.iris-sc-cross{display:flex;gap:8px;align-items:flex-start;padding:8px 10px;border:1px solid rgba(244,196,48,.45);border-radius:8px;background:rgba(244,196,48,.08);color:#f3e3a8;}',
            '.iris-sc-menu-r{left:auto!important;right:0;min-width:270px;}',
            '.iris-sc-pick{max-height:280px;overflow-y:auto;border:1px solid rgba(255,255,255,.08);border-radius:8px;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,.16) transparent;}',
            '.iris-sc-pick label{display:flex;align-items:center;gap:8px;margin:0;padding:6px 8px;border-bottom:1px solid rgba(255,255,255,.04);font-weight:normal;color:#c8c8d0;}',
            '.iris-sc-sel-sm{height:28px!important;font-size:.74rem;background:rgba(255,255,255,.02)!important;border:1px solid rgba(255,255,255,.12)!important;color:#d8d8e0!important;max-width:230px;padding:0 6px!important;}'
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
        var ch = canChange();
        var head = '<div class="iris-sc-head"><div><h5>Scope ' + IrisHelp.icon('room.scope') + '</h5><div class="iris-sc-sub" data-sc="sub">' +
            esc(sub) + '</div></div><div class="iris-sc-acts">' +
            (ch ? '<button type="button" class="btn btn-dark" data-sc="add-asset">' + ic('server', 13) + ' Add asset</button>' +
                  '<button type="button" class="btn btn-primary" data-sc="add-ioc">' + ic('plus', 13) + ' Add IOC</button>' : '') +
            '<span class="iris-sc-dd"><button type="button" class="btn btn-dark" data-sc="export" aria-haspopup="true" title="Export the IOCs of the attached cases you can open">' +
            ic('download', 13) + ' Export</button></span>' +
            (ch ? '<button type="button" class="btn btn-dark" data-sc="attach" title="Put assets of the Assets Manager in scope, with or without a case">' +
                  ic('clip', 13) + ' Attach from Assets Manager</button>' : '') + '</div></div>';
        var cnt = S.counts || {};
        var tabs = '<div class="iris-sc-tabs"><div class="iris-sc-tablist" role="tablist" aria-label="Scope">' + TABS.map(function (t) {
            var on = S.tab === t[0];
            return '<button type="button" role="tab" data-sc="tab" data-t="' + t[0] + '" aria-selected="' + on + '"' + (on ? ' class="active"' : '') + '>' +
                ic(t[2], 13) + ' ' + t[1] + ' <span class="iris-sc-tcount" data-sc-count="' + t[0] + '">' + (cnt[t[0]] != null ? Number(cnt[t[0]]) : '') + '</span></button>';
        }).join('') + '</div>' + (S.tab === 'assets' ? '<div class="iris-sc-views" role="group" aria-label="View">' +
            '<button type="button" data-sc="view" data-v="table" aria-pressed="' + (S.view === 'table') + '" title="Table view" aria-label="Table view">' + ic('table') + '</button>' +
            '<button type="button" data-sc="view" data-v="board" aria-pressed="' + (S.view === 'board') + '" title="Flag board - drag a card onto a flag to set it" aria-label="Flag board view">' + ic('board') + '</button></div>' : '') + '</div>';
        if (S.tab !== 'assets') {
            return head + tabs + '<div data-sc="note"></div><div data-sc="tabbody"></div>';
        }
        return head + tabs +
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
            '<div data-sc="selbar"></div><div data-sc="note"></div><div data-sc="body"></div><div data-sc="foot"></div><div data-sc="registry"></div>';
    }
    function draw() {
        if (!S.el) { return; }
        var act = document.activeElement && S.el.contains(document.activeElement) ? document.activeElement : null;
        var key = act ? act.getAttribute('data-sc') : null;
        var typing = key === 'q' || key === 'iq' ? {k: key, v: act.value, a: act.selectionStart, b: act.selectionEnd} : null;
        S.el.innerHTML = shell();
        drawNote();
        if (S.tab === 'assets') {
            drawSel();
            drawBody();
            drawRegistry();
        } else {
            drawTab();
        }
        var q = typing ? S.el.querySelector('[data-sc="' + typing.k + '"]') : null;
        if (q) {
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
            '<button type="button" class="btn btn-xs btn-dark" data-sc="rec-vuln" title="Record one vulnerability on the selected assets">' + ic('shield', 12) + ' Record vulnerability</button>' +
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
        function run(confirmed) {
            var err = m.querySelector('[data-sc="dlg-err"]');
            var r = onOk(m, confirmed);
            if (typeof r === 'string') { err.textContent = r; err.style.display = ''; return; }
            if (r && typeof r.then === 'function') {
                ok.disabled = true;
                r.then(function () { ok.disabled = false; }, function () { ok.disabled = false; });
            }
        }
        ok.addEventListener('click', function () { run(false); });
        /* the cross-customer warning's button resends the same request, confirmed */
        m.addEventListener('click', function (e) { if (e.target.closest('[data-sc="dlg-confirm"]')) { run(true); } });
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
    /* a 409 cross_customer answer: the warning (the customers named) with a button that resends, confirmed */
    function crossBlock(mm, res) {
        var d = res && res.j && res.j.data;
        if (!res || res.status !== 409 || !d || d.code !== 'cross_customer') { return false; }
        var e = mm.querySelector('[data-sc="dlg-err"]');
        e.innerHTML = '<div class="iris-sc-cross" data-sc="cross" role="alert">' + ic('alert', 15) + '<div>This spans ' + (d.customers || []).length +
            ' customers (' + esc((d.customers || []).join(', ')) + '). Make sure the data may be shared between them before going on.' +
            '<div class="mt-2"><button type="button" class="btn btn-sm btn-warning" data-sc="dlg-confirm">Share across customers</button></div></div></div>';
        e.style.display = '';
        return true;
    }
    function dlgError(mm, res, fallback) {
        var e = mm.querySelector('[data-sc="dlg-err"]');
        e.textContent = (res && res.j && res.j.message) || fallback;
        e.style.display = '';
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
    /* pick target cases, then send: o = {title, hint, cases, checked, okLabel, send(caseIds, confirmed) -> request,
       done(res), fail}. A cross-customer answer shows its warning in the dialog; its button resends, confirmed. */
    function casesDialog(o) {
        var body = '<div class="iris-sc-hint mb-2">' + esc(o.hint) + '</div><div class="iris-sc-list" data-sc="case-list">' + o.cases.map(function (c) {
            return '<label><input type="checkbox" value="' + id(c.case_id) + '"' + ((o.checked || []).indexOf(c.case_id) !== -1 ? ' checked' : '') + '> ' +
                esc(caseLabel(c.case_id, c.case_name)) + (c.customer_name ? ' <span class="iris-sc-hint">' + esc(c.customer_name) + '</span>' : '') + '</label>';
        }).join('') + '</div>';
        return dialog(o.title, body, o.okLabel || 'Push', function (mm, confirmed) {
            var cases = checkedIds(mm, 'case-list');
            if (!cases.length) { return 'Pick at least one case.'; }
            return o.send(cases, confirmed).then(function (res) {
                if (crossBlock(mm, res)) { return; }
                if (!res.ok) { dlgError(mm, res, o.fail || 'The server refused the push.'); return; }
                closeDlg(mm);
                o.done(res);
            });
        });
    }
    function checkedIds(mm, list) {
        return Array.prototype.map.call(mm.querySelectorAll('[data-sc="' + list + '"] input:checked'), function (x) { return id(x.value); });
    }
    function withConfirm(body, confirmed) {
        if (confirmed) { body.confirm_cross_customer = true; }
        return body;
    }
    function writableCases() { return ((S.data && S.data.cases) || []).filter(function (c) { return c.can_write; }); }
    function pushDialog(assets) {
        var own = {};
        assets.forEach(function (a) { own[a.case_id] = true; });
        var targets = writableCases().filter(function (c) { return !(assets.length === 1 && own[c.case_id]); });
        var who = assets.length === 1 ? assets[0].asset_name : assets.length + ' assets';
        if (!targets.length) { note('No other attached case you can change.', true); return; }
        casesDialog({title: assets.length === 1 ? 'Push ' + who + ' to other cases' : 'Push ' + who + ' to cases', cases: targets,
            hint: 'Copies name, type, description, IP, domain, tags, compromise and analysis status. The flags are not copied. A case that already holds the asset is skipped.',
            send: function (cases, confirmed) {
                return api('POST', base() + '/assets/push', withConfirm({asset_ids: assets.map(function (a) { return a.asset_id; }), case_ids: cases}, confirmed));
            },
            done: function (res) { report(res.j, 'Pushed'); load(); }});
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
                         changed: 'changed', created: 'created', exists: 'already there', refused: 'refused', attached: 'attached'}[k] || k;
            parts.push(c[k] + ' ' + label);
        });
        note(verb + ': ' + parts.join(' · '), !!refused.length, refused.map(function (r) {
            var who = r.asset_name || r.ioc_value || (r.asset_id ? 'asset #' + r.asset_id : (r.ioc_id ? 'IOC #' + r.ioc_id
                : (r.customer_asset_id ? 'registry asset #' + r.customer_asset_id : '')));
            var where = r.target_case_id ? ' → case #' + r.target_case_id : (!who && r.case_id ? 'case #' + r.case_id : '');
            return who + where + ': ' + (r.error || 'refused');
        }));
        loadCounts();
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

    /* ------------------------------------------------------- counts, the Assets Manager rows, the other sub-tabs */
    function T(name) { return S.tabs[name] || (S.tabs[name] = {filter: {}, data: null, sel: {}, seq: 0, done: 0, err: null}); }
    function loadCounts() {
        if (!S.el) { return Promise.resolve(); }
        return api('GET', base() + '/counts').then(function (res) {
            if (!res.ok || !S.el) { return; }
            S.counts = res.j;
            S.el.querySelectorAll('[data-sc-count]').forEach(function (e) {
                var v = S.counts[e.getAttribute('data-sc-count')];
                e.textContent = v != null ? Number(v) : '';
            });
        });
    }
    function vocab() {
        if (!S.vocab) {
            S.vocab = api('GET', base() + '/vocab').then(function (res) {
                if (!res.ok) { S.vocab = null; throw new Error((res.j && res.j.message) || 'Could not load the lists.'); }
                S.vocabData = res.j;
                return res.j;
            });
        }
        return S.vocab;
    }
    function loadTab(name) {
        if (name === 'iocs') { return loadIocs(); }
        if (name === 'customers') { return loadCustomers(); }
        if (name === 'staging') {
            vocab().then(function () { if (S.tab === 'staging') { drawTab(); } }, function () {});
            return loadStaging();
        }
        return Promise.resolve();
    }
    function showTab(name) {
        if (!TABS.some(function (t) { return t[0] === name; })) { name = 'assets'; }
        S.tab = name;
        closeMenus();
        draw();
        return loadTab(name);
    }
    function drawTab() {
        var host = S.el ? S.el.querySelector('[data-sc="tabbody"]') : null;
        if (!host) { return; }
        if (S.tab === 'iocs') { host.innerHTML = iocsHtml(); return; }
        if (S.tab === 'customers') { host.innerHTML = customersHtml(); return; }
        if (S.tab === 'staging') { host.innerHTML = stagingHtml(); return; }
        if (S.tab === 'vulnerabilities') {
            host.innerHTML = '<div class="iris-sc-sub mb-2">Vulnerabilities this room follows, and those recorded in its cases. ' +
                IrisHelp.icon('vuln.war_room') + '</div>';
            if (!S.vulnEl) {   /* mounted once and moved back in on every draw: it keeps its state */
                S.vulnEl = document.createElement('div');
                S.vulnEl.setAttribute('data-sc', 'vulns');
                if (window.IrisVuln) { window.IrisVuln.mountWarRoom(S.vulnEl, {roomId: S.ctx.roomId, canWrite: canChange()}); }
                else { S.vulnEl.innerHTML = '<div class="iris-sc-empty">The vulnerability catalogue could not be loaded on this page.</div>'; }
            }
            host.appendChild(S.vulnEl);
        }
    }

    /* ---- the Assets Manager attachments (below the Assets table) */
    function loadRegistry() {
        if (!S.el) { return Promise.resolve(); }
        var t = T('registry'), seq = ++t.seq;
        return api('GET', base() + '/registry-assets').then(function (res) {
            if (seq !== t.seq) { return; }
            S.reg = res.ok ? res.j : null;
            if (S.tab === 'assets') { drawRegistry(); }
            t.done = seq;
        });
    }
    function regById(lid) { return ((S.reg && S.reg.assets) || []).filter(function (a) { return a.id === id(lid); })[0]; }
    function drawRegistry() {
        var host = S.el ? S.el.querySelector('[data-sc="registry"]') : null;
        if (!host) { return; }
        var r = S.reg;
        if (!r || (!r.assets.length && !r.hidden)) { host.innerHTML = ''; return; }
        var ch = canChange(), cases = (S.data && S.data.cases) || [];
        host.innerHTML = '<div class="iris-sc-sec">' + ic('clip', 13) + ' Attached from the Assets Manager <span class="iris-sc-tcount">' + r.assets.length +
            '</span>' + IrisHelp.icon('room.scope_registry') + '</div>' + (r.assets.length ? '<div class="iris-sc-wrap"><table class="iris-sc-table" data-sc="reg-table"><thead><tr>' +
            '<th>Asset</th><th>Type</th><th>Customer</th><th>Criticality</th><th>Compromise</th><th>Case</th><th class="iris-sc-num" title="Open findings on the registry entry">Vulns</th>' +
            '<th>Added</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody>' + r.assets.map(function (a) {
                var cur = a.case ? a.case.case_id : '';
                var caseCell = ch ? '<select class="form-control iris-sc-sel-sm" data-sc="reg-case" data-reg="' + id(a.id) + '" aria-label="Case of ' + esc(a.asset_name) + '">' +
                    opt('', 'No case', cur) + cases.map(function (c) { return opt(c.case_id, caseLabel(c.case_id, c.case_name), cur); }).join('') +
                    (a.case && !a.case.visible ? opt(a.case.case_id, '#' + id(a.case.case_id), cur) : '') + '</select>'
                    : (a.case ? esc(a.case.case_name ? caseLabel(a.case.case_id, a.case.case_name) : '#' + id(a.case.case_id)) : '—');
                return '<tr data-reg="' + id(a.id) + '"><td><a class="iris-sc-name" href="' + esc(a.href) + '">' + esc(a.asset_name) + '</a>' +
                    (a.note ? '<div class="iris-sc-sub">' + esc(a.note) + '</div>' : '') + '</td><td>' + esc(a.asset_type || '') + '</td><td>' + esc(a.customer_name || '') +
                    '</td><td>' + esc(a.criticality || '—') + '</td><td>' + compPill(a.compromise) + '</td><td>' + caseCell + '</td><td class="iris-sc-num">' + (a.open_findings || '') +
                    '</td><td style="white-space:nowrap;">' + esc(stamp(a.added_at)) + (a.added_by ? '<div class="iris-sc-sub">' + esc(a.added_by) + '</div>' : '') + '</td>' +
                    '<td style="white-space:nowrap;">' + (ch ? '<button type="button" class="iris-sc-act" data-sc="reg-push" data-reg="' + id(a.id) + '" title="Push ' + esc(a.asset_name) +
                    ' into cases" aria-label="Push ' + esc(a.asset_name) + ' into cases">' + ic('push') + '</button><button type="button" class="iris-sc-act" data-sc="reg-detach" data-reg="' + id(a.id) +
                    '" title="Detach from the scope (kept in the Assets Manager)" aria-label="Detach ' + esc(a.asset_name) + '">' + ic('unlink') + '</button>' : '') + '</td></tr>';
            }).join('') + '</tbody></table></div>' : '') +
            (r.hidden ? '<div class="iris-sc-sub mt-1" data-sc="reg-hidden">' + Number(r.hidden) + ' more attached for customers you cannot access.</div>' : '');
    }
    function regPushDialog(a) {
        var targets = writableCases();
        if (!targets.length) { note('No attached case you can change.', true); return; }
        casesDialog({title: 'Push ' + a.asset_name + ' into cases', cases: targets, checked: a.case && a.case.case_id ? [a.case.case_id] : [],
            hint: 'Creates it as a case asset: name, type, compromise status, and the IP, domain, tags and description of its latest sighting. A case that already holds it is skipped.',
            send: function (cases, confirmed) { return api('POST', base() + '/registry-assets/' + id(a.id) + '/push', withConfirm({case_ids: cases}, confirmed)); },
            done: function (res) { report(res.j, 'Pushed ' + a.asset_name); load(); }});
    }
    function attachDialog() {
        var have = {};
        ((S.reg && S.reg.assets) || []).forEach(function (a) { have[a.customer_asset_id] = true; });
        var custs = (S.data && S.data.customers) || [], cases = (S.data && S.data.cases) || [];
        var body = '<div class="iris-sc-hint mb-2">Put assets of the Assets Manager in scope, with or without a case. They stay in the registry; a push copies one into a case. ' +
            IrisHelp.icon('room.scope_registry') + '</div><div class="d-flex" style="gap:8px;">' +
            '<input type="text" class="form-control form-control-sm" data-sc="reg-q" placeholder="Search the Assets Manager…" aria-label="Search the Assets Manager">' +
            '<select class="form-control form-control-sm" data-sc="reg-cust" aria-label="Customer" style="max-width:200px;">' + opt('', 'All customers', '') +
            custs.map(function (c) { return opt(c.customer_id, c.name || ('#' + c.customer_id), ''); }).join('') + '</select></div>' +
            '<div class="iris-sc-pick mt-2" data-sc="reg-results"><div class="iris-sc-hint p-2">Loading…</div></div>' +
            '<label class="iris-sc-fl mt-2" for="iris-sc-reg-link">Case (optional)</label><select id="iris-sc-reg-link" class="form-control form-control-sm" data-sc="reg-link">' +
            opt('', 'No case', '') + cases.map(function (c) { return opt(c.case_id, caseLabel(c.case_id, c.case_name), ''); }).join('') + '</select>';
        var seq = 0, timer = null;
        var m = dialog('Attach assets from the Assets Manager', body, 'Attach', function (mm) {
            var picked = checkedIds(mm, 'reg-results');
            if (!picked.length) { return 'Pick at least one asset.'; }
            var cid = id(mm.querySelector('[data-sc="reg-link"]').value), b = {customer_asset_ids: picked};
            if (cid) { b.case_id = cid; }
            return api('POST', base() + '/registry-assets', b).then(function (res) {
                if (!res.ok) { dlgError(mm, res, 'Could not attach the assets.'); return; }
                closeDlg(mm);
                report(res.j, 'Attached from the Assets Manager');
                loadRegistry();
            });
        });
        function search() {
            var my = ++seq, q = m.querySelector('[data-sc="reg-q"]').value.trim(), c = m.querySelector('[data-sc="reg-cust"]').value;
            api('GET', '/api/v2/customer-assets?per_page=50' + (q ? '&q=' + encodeURIComponent(q) : '') + (c ? '&customer_id=' + id(c) : '')).then(function (res) {
                if (my !== seq) { return; }
                var host = m.querySelector('[data-sc="reg-results"]'), rows = res.ok ? res.j.assets : null;
                if (!Array.isArray(rows)) {
                    host.innerHTML = '<div class="iris-sc-hint p-2" role="alert">' + esc((res.j && res.j.message) || 'Could not search the Assets Manager.') + '</div>';
                    return;
                }
                host.innerHTML = rows.length ? rows.map(function (a) {
                    var on = have[a.id];
                    return '<label><input type="checkbox" value="' + id(a.id) + '"' + (on ? ' disabled' : '') + '> <b class="iris-sc-name">' + esc(a.asset_name) + '</b> <span class="iris-sc-hint">' +
                        esc([a.asset_type, a.customer_name, a.criticality].filter(Boolean).join(' · ')) + '</span>' + (on ? ' <span class="iris-sc-hint">already attached</span>' : '') + '</label>';
                }).join('') : '<div class="iris-sc-hint p-2">No asset matches.</div>';
            });
        }
        m.addEventListener('input', function (e) {
            if (e.target.getAttribute('data-sc') === 'reg-q') { clearTimeout(timer); timer = setTimeout(search, 250); }
        });
        m.addEventListener('change', function (e) { if (e.target.getAttribute('data-sc') === 'reg-cust') { search(); } });
        search();
    }

    /* ---- IOCs: one row per indicator, one column per case */
    function loadIocs() {
        var t = T('iocs'), seq = ++t.seq, f = t.filter, parts = [];
        ['q', 'case_id', 'page'].forEach(function (k) { if (f[k]) { parts.push(k + '=' + encodeURIComponent(f[k])); } });
        return api('GET', base() + '/iocs' + (parts.length ? '?' + parts.join('&') : '')).then(function (res) {
            if (seq !== t.seq) { return; }
            t.err = res.ok ? null : ((res.j && res.j.message) || 'Could not load the IOCs');
            t.data = res.ok ? res.j : null;
            var keep = {};
            (t.data ? t.data.iocs : []).forEach(function (r) { if (t.sel[r.key]) { keep[r.key] = true; } });
            t.sel = keep;
            if (S.tab === 'iocs') { drawTab(); }
            t.done = seq;
        });
    }
    function iocRow(key) { var d = T('iocs').data; return d ? d.iocs.filter(function (r) { return r.key === key; })[0] : null; }
    function firstIoc(r) { var k = Object.keys(r.cases || {}); return k.length ? id(r.cases[k[0]]) : 0; }
    function tlpPill(t) {
        var n = t && t.name ? t.name : 'unset';
        return n === 'unset' ? '<span class="iris-sc-pill" title="No TLP set">No TLP</span>'
            : '<span class="iris-sc-pill ' + (TLP_CLASS[n] || '') + '">TLP:' + esc(String(n).toUpperCase()) + '</span>';
    }
    function iselHtml() {
        var t = T('iocs'), d = t.data, sel = d ? d.iocs.filter(function (r) { return t.sel[r.key]; }) : [];
        if (!sel.length || !canChange()) { return ''; }
        return '<div class="iris-sc-sel" role="toolbar" aria-label="Change the selected IOCs"><b>' + sel.length + '</b> selected' +
            '<button type="button" class="btn btn-xs btn-dark" data-sc="ipush-sel">' + ic('push', 12) + ' Push to cases</button>' +
            '<a href="#" data-sc="iclear-sel" style="margin-left:auto;">Clear selection</a></div>';
    }
    function iocsHtml() {
        var t = T('iocs'), d = t.data, f = t.filter, ch = canChange();
        var cases = d ? d.cases : ((S.data && S.data.cases) || []);
        var h = '<div class="iris-sc-bar" role="search"><span class="iris-sc-search">' + ic('search') +
            '<input type="text" class="form-control" data-sc="iq" placeholder="Filter by value, type, tags…" aria-label="Filter the IOCs" value="' + esc(f.q || '') + '"></span>' +
            '<label>Case <select class="form-control" data-sc="icase" aria-label="The IOCs of a case">' + opt('', 'All cases', f.case_id) +
            cases.map(function (c) { return opt(c.case_id, caseLabel(c.case_id, c.case_name), f.case_id); }).join('') + '</select></label>' +
            '<span class="iris-sc-sub">One row per indicator; a dashed cell is a case missing it. ' + IrisHelp.icon('room.scope_iocs') + '</span></div>' +
            '<div data-sc="iselwrap">' + iselHtml() + '</div>';
        if (t.err) { return h + '<div class="iris-sc-empty" data-sc="iempty" role="alert">' + esc(t.err) + '</div>'; }
        if (!d) { return h + '<div class="iris-sc-empty">Loading…</div>'; }
        if (!d.case_count) { return h + '<div class="iris-sc-empty" data-sc="iempty">No case attached to this war room that you can open.</div>'; }
        if (!d.total) {
            return h + '<div class="iris-sc-empty" data-sc="iempty">' + (f.q || f.case_id ? 'No IOC matches.' : 'The attached cases you can open have no IOC yet.') + '</div>';
        }
        var all = ch && d.iocs.length && d.iocs.every(function (r) { return t.sel[r.key]; });
        h += '<div class="iris-sc-wrap"><table class="iris-sc-table" data-sc="itable"><thead><tr><th>' +
            (ch ? '<input type="checkbox" data-sc="ipick-all"' + (all ? ' checked' : '') + ' aria-label="Select all visible IOCs" title="Select all visible IOCs">' : '') + '</th>' +
            '<th>Value</th><th>Type</th><th>TLP</th><th>Customers</th>' + d.cases.map(function (c) {
                return '<th class="iris-sc-num" title="' + esc(caseLabel(c.case_id, c.case_name)) + '">#' + id(c.case_id) + '</th>';
            }).join('') + '<th><span class="sr-only">Actions</span></th></tr></thead><tbody>' + d.iocs.map(function (r) {
                var miss = d.cases.filter(function (c) { return !r.cases[String(c.case_id)] && c.can_write; });
                return '<tr data-ioc="' + esc(r.key) + '"' + (t.sel[r.key] ? ' class="iris-sc-on"' : '') + '><td>' +
                    (ch ? '<input type="checkbox" data-sc="ipick" data-key="' + esc(r.key) + '"' + (t.sel[r.key] ? ' checked' : '') + ' aria-label="Select ' + esc(r.ioc_value) + '">' : '') + '</td>' +
                    '<td class="iris-sc-name" style="word-break:break-all;">' + esc(r.ioc_value) + (r.ioc_tags ? '<div class="iris-sc-sub">' + esc(r.ioc_tags) + '</div>' : '') + '</td>' +
                    '<td>' + esc(r.ioc_type || '') + '</td><td>' + tlpPill(r.tlp) + '</td><td>' + esc((r.customers || []).join(', ')) + '</td>' +
                    d.cases.map(function (c) {
                        if (r.cases[String(c.case_id)]) {
                            return '<td class="iris-sc-num"><span class="iris-sc-ok" data-sc="ihas" title="Present in case #' + id(c.case_id) + '">' + ic('check', 14) + '</span></td>';
                        }
                        return '<td class="iris-sc-num">' + (ch && c.can_write ? '<button type="button" class="iris-sc-cell" data-sc="ipush-cell" data-key="' + esc(r.key) + '" data-case="' + id(c.case_id) +
                            '" title="Push ' + esc(r.ioc_value) + ' to case #' + id(c.case_id) + '" aria-label="Push ' + esc(r.ioc_value) + ' to case #' + id(c.case_id) + '">+</button>'
                            : '<span class="iris-sc-dot" title="Not in case #' + id(c.case_id) + '">·</span>') + '</td>';
                    }).join('') +
                    '<td style="white-space:nowrap;">' + (ch && miss.length ? '<button type="button" class="iris-sc-act" data-sc="ipush-row" data-key="' + esc(r.key) +
                    '" title="Push ' + esc(r.ioc_value) + ' to the ' + miss.length + ' case' + (miss.length === 1 ? '' : 's') + ' missing it">' + ic('push') +
                    ' <span class="iris-sc-sub">' + miss.length + '</span></button>' : '') + '</td></tr>';
            }).join('') + '</tbody></table></div>';
        var page = Number(d.page) || 1, per = Number(d.per_page) || 100, from = (page - 1) * per + 1, to = Math.min(d.total, page * per);
        return h + '<div class="iris-sc-foot" data-sc="irange">' + from + '–' + to + ' of ' + d.total + ' IOC' + (d.total === 1 ? '' : 's') +
            (d.total > per ? ' <button type="button" class="btn btn-xs btn-dark" data-sc="iprev"' + (page <= 1 ? ' disabled' : '') + '>Previous</button>' +
             '<button type="button" class="btn btn-xs btn-dark" data-sc="inext"' + (to >= d.total ? ' disabled' : '') + '>Next</button>' : '') + '</div>';
    }
    function syncIocPicks() {
        var t = T('iocs');
        S.el.querySelectorAll('[data-sc="ipick"]').forEach(function (b) {
            var on = !!t.sel[b.getAttribute('data-key')];
            b.checked = on;
            var tr = b.closest('tr');
            if (tr) { tr.classList.toggle('iris-sc-on', on); }
        });
        var w = S.el.querySelector('[data-sc="iselwrap"]');
        if (w) { w.innerHTML = iselHtml(); }
        var all = S.el.querySelector('[data-sc="ipick-all"]'), d = t.data;
        if (all && d) { all.checked = d.iocs.length > 0 && d.iocs.every(function (r) { return t.sel[r.key]; }); }
    }
    function iocPushDialog(rows, preset) {
        var d = T('iocs').data;
        var targets = (d ? d.cases : []).filter(function (c) { return c.can_write && !(rows.length === 1 && rows[0].cases[String(c.case_id)]); });
        var who = rows.length === 1 ? rows[0].ioc_value : rows.length + ' IOCs';
        if (!targets.length) { note('No attached case you can change is missing it.', true); return; }
        casesDialog({title: 'Push ' + who + ' to cases', cases: targets,
            checked: preset || (rows.length === 1 ? targets.map(function (c) { return c.case_id; }) : []),
            hint: 'Copies value, type, TLP, description and tags. A case that already holds it is skipped.',
            send: function (cases, confirmed) { return api('POST', base() + '/iocs/push', withConfirm({ioc_ids: rows.map(firstIoc), case_ids: cases}, confirmed)); },
            done: function (res) { report(res.j, 'Pushed'); loadIocs(); }});
    }

    /* ---- Customers */
    function loadCustomers() {
        var t = T('customers'), seq = ++t.seq;
        return api('GET', base() + '/customers').then(function (res) {
            if (seq !== t.seq) { return; }
            t.err = res.ok ? null : ((res.j && res.j.message) || 'Could not load the customers');
            t.data = res.ok ? res.j : null;
            if (S.tab === 'customers') { drawTab(); }
            t.done = seq;
        });
    }
    function customersHtml() {
        var t = T('customers'), d = t.data;
        var h = '<div class="iris-sc-sub mb-2">The scope summed per customer of the attached cases you can open. ' + IrisHelp.icon('room.scope_customers') + '</div>';
        if (t.err) { return h + '<div class="iris-sc-empty" data-sc="cempty" role="alert">' + esc(t.err) + '</div>'; }
        if (!d) { return h + '<div class="iris-sc-empty">Loading…</div>'; }
        if (!d.customers.length) { return h + '<div class="iris-sc-empty" data-sc="cempty">No case attached to this war room that you can open.</div>'; }
        return h + '<div class="iris-sc-wrap"><table class="iris-sc-table" data-sc="ctable"><thead><tr><th>Customer</th><th>Cases</th><th class="iris-sc-num">Assets</th>' +
            '<th class="iris-sc-num">Compromised</th><th class="iris-sc-num" title="Assets carrying a flag of kind done">Done</th>' +
            '<th class="iris-sc-num" title="Distinct IOCs per case, summed">IOCs</th><th class="iris-sc-num">Open vulns</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody>' +
            d.customers.map(function (c) {
                return '<tr data-cust="' + id(c.customer_id) + '"><td class="iris-sc-name">' + esc(c.name || ('Customer #' + id(c.customer_id))) + '</td><td>' +
                    c.cases.map(function (k) { return '<a href="/case?cid=' + id(k.case_id) + '" title="' + esc(caseLabel(k.case_id, k.case_name)) + '">#' + id(k.case_id) + '</a>'; }).join(' ') +
                    '</td><td class="iris-sc-num">' + Number(c.assets) + '</td><td class="iris-sc-num' + (c.compromised ? ' iris-sc-exploited' : '') + '">' + Number(c.compromised) +
                    '</td><td class="iris-sc-num">' + Number(c.done) + '</td><td class="iris-sc-num">' + Number(c.iocs) + '</td><td class="iris-sc-num"' +
                    (c.vuln_exploited_open ? ' title="' + Number(c.vuln_exploited_open) + ' exploited and open"' : '') + '>' + Number(c.vuln_open) + '</td>' +
                    '<td><button type="button" class="iris-sc-act" data-sc="cust-assets" data-cust="' + id(c.customer_id) + '" title="Show the assets of this customer" aria-label="Show the assets of ' +
                    esc(c.name || 'this customer') + '">' + ic('server') + '</button></td></tr>';
            }).join('') + '</tbody></table></div>';
    }

    /* ---- Staging */
    function loadStaging() {
        var t = T('staging'), seq = ++t.seq;
        return api('GET', base() + '/staging').then(function (res) {
            if (seq !== t.seq) { return; }
            t.err = res.ok ? null : ((res.j && res.j.message) || 'Could not load the staging inbox');
            t.data = res.ok ? res.j : null;
            if (S.tab === 'staging') { drawTab(); }
            t.done = seq;
        });
    }
    function typeName(list, tid) { var x = (list || []).filter(function (t) { return t.id === tid; })[0]; return x ? x.name : ''; }
    function tlpName(tid) {
        var x = S.vocabData ? (S.vocabData.tlps || []).filter(function (t) { return t.id === tid; })[0] : null;
        return x ? 'TLP:' + String(x.name).toUpperCase() : '';
    }
    function stagedById(sid) { var d = T('staging').data; return d ? d.staged.filter(function (x) { return x.id === id(sid); })[0] : null; }
    function stagingHtml() {
        var t = T('staging'), d = t.data, ch = canChange(), v = S.vocabData;
        var h = '<div class="iris-sc-sub mb-2">Assets and IOCs typed into the room, waiting with the cases they are meant for. A push creates them there; the row goes once every case holds it. ' +
            IrisHelp.icon('room.scope_staging') + '</div>';
        if (t.err) { return h + '<div class="iris-sc-empty" data-sc="sempty" role="alert">' + esc(t.err) + '</div>'; }
        if (!d) { return h + '<div class="iris-sc-empty">Loading…</div>'; }
        if (!d.staged.length) {
            return h + '<div class="iris-sc-empty" data-sc="sempty">Staging is empty. "Stage for later" in Add asset or Add IOC keeps one here until it is pushed.</div>';
        }
        return h + d.staged.map(function (x) {
            var p = x.payload || {}, isAsset = x.kind === 'asset';
            var tname = isAsset ? typeName(v && v.asset_types, p.asset_type_id) : typeName(v && v.ioc_types, p.ioc_type_id);
            return '<div class="iris-sc-staged" data-staged="' + id(x.id) + '"><span class="iris-sc-pill">' + (isAsset ? 'Asset' : 'IOC') + '</span><div style="flex:1 1 auto;min-width:0;">' +
                '<b class="iris-sc-name" style="word-break:break-all;">' + esc(x.label || '') + '</b> <span class="iris-sc-sub">' + esc(tname) + (isAsset ? '' : ' · ' + esc(tlpName(p.ioc_tlp_id))) + '</span>' +
                '<div>' + (x.targets.length ? x.targets.map(function (c) {
                    var name = c.case_name ? caseLabel(c.case_id, c.case_name) : '#' + id(c.case_id);
                    return '<span class="iris-sc-chip' + (c.present ? ' iris-sc-has' : '') + '" data-sc="st-target" data-case="' + id(c.case_id) + '" title="' +
                        esc((c.present ? 'Present in ' : (c.visible ? 'Missing from ' : 'A case you cannot open: ')) + name) + '">' + (c.present ? ic('check', 11) + ' ' : '') + '#' + id(c.case_id) + '</span>';
                }).join('') : '<span class="iris-sc-sub">No target case yet</span>') + '</div>' + (x.note ? '<div class="iris-sc-sub mt-1">' + esc(x.note) + '</div>' : '') +
                '<div class="iris-sc-sub mt-1">' + esc((x.created_by || '') + (x.created_at ? ', ' + stamp(x.created_at) : '')) + (x.updated_at ? ' · edited ' + esc(stamp(x.updated_at)) : '') + '</div></div>' +
                (ch ? '<div style="white-space:nowrap;"><button type="button" class="btn btn-xs btn-primary" data-sc="st-push" data-staged="' + id(x.id) + '">' + ic('push', 12) + ' Push</button> ' +
                    '<button type="button" class="iris-sc-act" data-sc="st-edit" data-staged="' + id(x.id) + '" title="Edit" aria-label="Edit ' + esc(x.label || '') + '">' + ic('pencil') + '</button>' +
                    '<button type="button" class="iris-sc-act" data-sc="st-del" data-staged="' + id(x.id) + '" title="Discard" aria-label="Discard ' + esc(x.label || '') + '">' + ic('trash') + '</button></div>' : '') + '</div>';
        }).join('');
    }
    function stagedPushDialog(x) {
        vocab().then(function (v) {
            var targets = v.cases.filter(function (c) { return c.can_write; });
            if (!targets.length) { note('No attached case you can change.', true); return; }
            casesDialog({title: 'Push ' + (x.label || 'the staged object') + ' to cases', cases: targets,
                checked: x.targets.filter(function (c) { return !c.present; }).map(function (c) { return c.case_id; }),
                hint: 'Create it in the selected cases. The staged row is removed once every target holds it.', fail: 'Could not push the staged object.',
                send: function (cases, confirmed) { return api('POST', base() + '/staging/' + id(x.id) + '/push', withConfirm({case_ids: cases}, confirmed)); },
                done: function (res) {
                    report(res.j, 'Pushed ' + (x.label || ''));
                    if (res.j.removed && S.note) { S.note.text += ' · removed from staging'; drawNote(); }
                    loadStaging();
                    load();
                    if (T('iocs').data) { loadIocs(); }
                }});
        }, function (e) { note(e.message, true); });
    }
    function discardStaged(x) {
        if (!window.confirm('Discard "' + (x.label || '') + '" from the staging inbox? It was never pushed to a case.')) { return; }
        api('DELETE', base() + '/staging/' + id(x.id)).then(function (res) {
            if (!res.ok) { note((res.j && res.j.message) || 'Could not discard the staged object.', true); return; }
            note('Staged object discarded.');
            loadStaging();
            loadCounts();
        });
    }

    /* ---- Add asset / Add IOC (several cases at once, or "Stage for later"), and editing a staged one */
    function objectDialog(kind, staged) {
        vocab().then(function (v) {
            var p = staged ? (staged.payload || {}) : {}, isAsset = kind === 'asset', edit = !!staged;
            function sel(name, list, cur, label, extra) {
                return '<div><label class="iris-sc-fl" for="iris-sc-f-' + name + '">' + label + '</label><select id="iris-sc-f-' + name + '" class="form-control form-control-sm" data-sc="f-' + name + '">' +
                    (extra || '') + list.map(function (x) { return opt(x.id, x.name, cur); }).join('') + '</select></div>';
            }
            function inp(name, label, cur, ph) {
                return '<div><label class="iris-sc-fl" for="iris-sc-f-' + name + '">' + label + '</label><input type="text" id="iris-sc-f-' + name + '" class="form-control form-control-sm" data-sc="f-' + name +
                    '" value="' + esc(cur == null ? '' : cur) + '"' + (ph ? ' placeholder="' + esc(ph) + '"' : '') + '></div>';
            }
            var unspecified = ((v.analysis_statuses || []).filter(function (a) { return /^unspecified$/i.test(a.name || ''); })[0] || {}).id;
            var amber = ((v.tlps || []).filter(function (t) { return /^amber$/i.test(t.name || ''); })[0] || {}).id;
            var desc = isAsset ? 'asset_description' : 'ioc_description';
            var fields = (isAsset
                ? '<div class="iris-sc-grid">' + inp('asset_name', 'Name', p.asset_name, 'WS-FIN-07') + sel('asset_type_id', v.asset_types, p.asset_type_id, 'Type', '<option value="">Pick a type</option>') +
                  inp('asset_ip', 'IP', p.asset_ip) + inp('asset_domain', 'Domain', p.asset_domain) +
                  sel('asset_compromise_status_id', v.compromise_statuses.map(function (c) { return {id: c.id, name: c.label}; }), p.asset_compromise_status_id != null ? p.asset_compromise_status_id : 0, 'Compromise') +
                  sel('analysis_status_id', v.analysis_statuses, p.analysis_status_id || unspecified, 'Analysis') + '</div>' + inp('asset_tags', 'Tags (comma-separated)', p.asset_tags)
                : '<div class="iris-sc-grid">' + inp('ioc_value', 'Value', p.ioc_value, 'evil.example') + sel('ioc_type_id', v.ioc_types, p.ioc_type_id, 'Type', '<option value="">Pick a type</option>') +
                  sel('ioc_tlp_id', v.tlps.map(function (t) { return {id: t.id, name: 'TLP:' + String(t.name).toUpperCase()}; }), p.ioc_tlp_id || amber, 'TLP') +
                  inp('ioc_tags', 'Tags (comma-separated)', p.ioc_tags) + '</div>') +
                '<label class="iris-sc-fl mt-2" for="iris-sc-f-' + desc + '">Description</label><textarea id="iris-sc-f-' + desc + '" class="form-control form-control-sm" rows="2" data-sc="f-' + desc + '">' +
                esc(p[desc] || '') + '</textarea>';
            var mine = v.cases.filter(function (c) { return c.can_write; });
            var checked = edit ? (staged.targets || []).map(function (c) { return c.case_id; }) : (mine.length === 1 ? [mine[0].case_id] : []);
            var targets = '<div class="iris-sc-fl mt-2">' + (edit ? 'Proposed for' : 'Cases') + '</div><div class="iris-sc-list" data-sc="case-list">' + (v.cases.length ? v.cases.map(function (c) {
                return '<label><input type="checkbox" value="' + id(c.case_id) + '"' + (checked.indexOf(c.case_id) !== -1 ? ' checked' : '') + (c.can_write || edit ? '' : ' data-ro="1"') + '> ' +
                    esc(caseLabel(c.case_id, c.case_name)) + (c.customer_name ? ' <span class="iris-sc-hint">' + esc(c.customer_name) + '</span>' : '') +
                    (c.can_write ? '' : ' <span class="iris-sc-hint">read-only for you</span>') + '</label>';
            }).join('') : '<div class="iris-sc-hint">No attached case you can open.</div>') + '</div>' +
                (edit ? '' : '<div class="iris-sc-hint mt-1">Created in every selected case. Cases that already hold it are skipped.</div>');
            var flagsHtml = isAsset && !edit && (v.flags || []).length ? '<div data-sc="flags-block"><div class="iris-sc-fl mt-2">Initial flags (optional) ' + IrisHelp.icon('flags.asset') +
                '</div><div class="iris-sc-list" data-sc="flag-list">' + v.flags.map(function (f) {
                    return '<label><input type="checkbox" value="' + id(f.flag_id) + '"> ' + (window.IrisFlags ? window.IrisFlags.chip(f) : esc(f.name)) +
                        (f.requires_reason ? ' <span class="iris-sc-hint">needs a reason</span>' : '') + (f.requires_decision ? ' <span class="iris-sc-hint">needs a decision</span>' : '') + '</label>';
                }).join('') + '</div><div data-sc="flag-extra" style="display:none;"><label class="iris-sc-fl mt-2" for="iris-sc-f-reason">Flag reason <span data-sc="reason-req"></span></label>' +
                '<textarea id="iris-sc-f-reason" class="form-control form-control-sm" rows="2" data-sc="reason"></textarea><div data-sc="decision-row" style="display:none;">' +
                '<label class="iris-sc-fl mt-2" for="iris-sc-f-decision">Decision</label><select id="iris-sc-f-decision" class="form-control form-control-sm" data-sc="decision">' +
                '<option value="">Pick an approved decision</option></select></div></div></div>' : '';
            var stage = edit ? '' : '<label class="mt-3 d-flex align-items-center" style="gap:6px;font-weight:normal;"><input type="checkbox" data-sc="stage"> Stage for later</label>' +
                '<div class="iris-sc-hint">Keep it in the war-room staging inbox and push it later (at most ' + Number(v.limits.staged_targets) + ' target cases).</div>';
            var noteF = '<div data-sc="note-row"' + (edit ? '' : ' style="display:none;"') + '><label class="iris-sc-fl mt-2" for="iris-sc-f-note">Note</label>' +
                '<textarea id="iris-sc-f-note" class="form-control form-control-sm" rows="2" data-sc="f-note">' + esc(edit ? (staged.note || '') : '') + '</textarea></div>';
            var title = edit ? 'Edit staged ' + (isAsset ? 'asset' : 'IOC') : (isAsset ? 'Add asset' : 'Add IOC');
            var keys = isAsset ? ['asset_name', 'asset_type_id', 'asset_ip', 'asset_domain', 'asset_compromise_status_id', 'analysis_status_id', 'asset_tags', 'asset_description']
                : ['ioc_value', 'ioc_type_id', 'ioc_tlp_id', 'ioc_tags', 'ioc_description'];
            var m = dialog(title, fields + targets + flagsHtml + stage + noteF, edit ? 'Save' : 'Add', function (mm, confirmed) {
                var payload = {};
                keys.forEach(function (k) {
                    var e = mm.querySelector('[data-sc="f-' + k + '"]'), val = e ? e.value.trim() : '';
                    payload[k] = /_id$/.test(k) ? (val === '' ? null : id(val)) : (val || null);
                });
                if (isAsset && !payload.asset_name) { return 'Name the asset.'; }
                if (isAsset && !payload.asset_type_id) { return 'Pick an asset type.'; }
                if (!isAsset && !payload.ioc_value) { return 'Give the IOC value.'; }
                if (!isAsset && !payload.ioc_type_id) { return 'Pick an IOC type.'; }
                var cases = checkedIds(mm, 'case-list');
                var stageIt = !!(mm.querySelector('[data-sc="stage"]') || {}).checked;
                var noteV = ((mm.querySelector('[data-sc="f-note"]') || {}).value || '').trim();
                if (edit) {
                    return api('PATCH', base() + '/staging/' + id(staged.id), {payload: payload, target_case_ids: cases, note: noteV}).then(function (res) {
                        if (!res.ok) { dlgError(mm, res, 'Could not save the staged object.'); return; }
                        closeDlg(mm);
                        note('Staged ' + (isAsset ? 'asset' : 'IOC') + ' saved.');
                        loadStaging();
                    });
                }
                if (stageIt) {
                    if (cases.length > v.limits.staged_targets) { return 'A staged object proposes at most ' + v.limits.staged_targets + ' target cases.'; }
                    return api('POST', base() + '/staging', {kind: kind, payload: payload, target_case_ids: cases, note: noteV}).then(function (res) {
                        if (!res.ok) { dlgError(mm, res, 'Could not stage the object.'); return; }
                        closeDlg(mm);
                        note('Added to staging: ' + (payload.asset_name || payload.ioc_value) + '.');
                        if (T('staging').data) { loadStaging(); }
                        loadCounts();
                    });
                }
                if (!cases.length) { return 'Pick at least one case (or stage it for later).'; }
                var body = withConfirm(isAsset ? {asset: payload, case_ids: cases} : {ioc: payload, case_ids: cases}, confirmed);
                if (isAsset) {
                    var fl = checkedIds(mm, 'flag-list');
                    if (fl.length) {
                        var pf = (v.flags || []).filter(function (f) { return fl.indexOf(f.flag_id) !== -1; });
                        var reason = ((mm.querySelector('[data-sc="reason"]') || {}).value || '').trim();
                        var dec = id((mm.querySelector('[data-sc="decision"]') || {}).value);
                        if (pf.some(function (f) { return f.requires_reason; }) && !reason) { return 'A picked flag requires a reason.'; }
                        if (pf.some(function (f) { return f.requires_decision; }) && !dec) { return 'A picked flag requires a decision from the register.'; }
                        body.flag_ids = fl;
                        if (reason) { body.reason = reason; }
                        if (dec) { body.decision_id = dec; }
                    }
                }
                return api('POST', base() + (isAsset ? '/assets' : '/iocs'), body).then(function (res) {
                    if (crossBlock(mm, res)) { return; }
                    if (!res.ok) { dlgError(mm, res, isAsset ? 'Could not add the asset.' : 'Could not add the IOC.'); return; }
                    closeDlg(mm);
                    report(res.j, (isAsset ? 'Asset ' : 'IOC ') + (payload.asset_name || payload.ioc_value));
                    load();
                    if (T('iocs').data) { loadIocs(); }
                });
            });
            var decFilled = false;
            function sync() {
                var stageIt = !!(m.querySelector('[data-sc="stage"]') || {}).checked;
                m.querySelectorAll('[data-ro]').forEach(function (x) { x.disabled = !stageIt; if (!stageIt) { x.checked = false; } });
                var nr = m.querySelector('[data-sc="note-row"]');
                if (nr && !edit) { nr.style.display = stageIt ? '' : 'none'; }
                var fb = m.querySelector('[data-sc="flags-block"]');
                if (fb) {
                    fb.style.display = stageIt ? 'none' : '';
                    var picked = checkedIds(m, 'flag-list'), pf = (v.flags || []).filter(function (f) { return picked.indexOf(f.flag_id) !== -1; });
                    var needDec = pf.some(function (f) { return f.requires_decision; });
                    m.querySelector('[data-sc="flag-extra"]').style.display = picked.length ? '' : 'none';
                    m.querySelector('[data-sc="reason-req"]').textContent = pf.some(function (f) { return f.requires_reason; }) ? '(required)' : '(optional)';
                    m.querySelector('[data-sc="decision-row"]').style.display = needDec ? '' : 'none';
                    if (needDec && !decFilled) {
                        decFilled = true;
                        loadDecisions().then(function (ds) {
                            m.querySelector('[data-sc="decision"]').innerHTML = '<option value="">Pick an approved decision</option>' + ds.map(function (dd) {
                                return '<option value="' + id(dd.decision_id || dd.id) + '">' + esc((dd.ref || '') + ' ' + (dd.title || '')) + '</option>';
                            }).join('');
                        });
                    }
                }
                var n = checkedIds(m, 'case-list').length;
                if (!edit) { m.querySelector('[data-sc="dlg-ok"]').textContent = stageIt ? 'Stage' : 'Add to ' + n + ' case' + (n === 1 ? '' : 's'); }
            }
            m.addEventListener('change', sync);
            sync();
        }, function (e) { note(e.message, true); });
    }

    /* ---- Record vulnerability (on the selected assets), with the catalogue's own chooser */
    function vulnDialog(assets) {
        if (!window.IrisVuln) { note('The vulnerability catalogue could not be loaded on this page.', true); return; }
        window.IrisVuln.vocab().then(function (voc) {
            var who = assets.length === 1 ? assets[0].asset_name : assets.length + ' assets';
            var groups = (voc.remediation_groups || []).map(function (g) {
                return '<optgroup label="' + esc(g.label) + '">' + (g.statuses || []).map(function (st) { return opt(st.value, st.label, 'affected'); }).join('') + '</optgroup>';
            }).join('');
            var body = '<div class="iris-sc-hint mb-2">Record one vulnerability on ' + esc(who) + '. An asset that already carries it is skipped.</div>' +
                '<div data-sc="vchooser"></div><label class="iris-sc-fl mt-2" for="iris-sc-vstatus">Status</label>' +
                '<select id="iris-sc-vstatus" class="form-control form-control-sm" data-sc="vstatus">' + groups + '</select>';
            var ch = null;
            var m = dialog('Record a vulnerability on ' + who, body, 'Record', function (mm) {
                var pick = ch ? ch.payload() : null;
                if (!pick) { return 'Choose a vulnerability (or quick-add one by its identifier).'; }
                var b = {asset_ids: assets.map(function (a) { return a.asset_id; }), remediation_status: mm.querySelector('[data-sc="vstatus"]').value};
                Object.keys(pick).forEach(function (k) { b[k] = pick[k]; });
                return api('POST', base() + '/assets/vulnerability', b).then(function (res) {
                    if (!res.ok) { dlgError(mm, res, 'Could not record the vulnerability.'); return; }
                    closeDlg(mm);
                    report(res.j, 'Recorded ' + ((res.j.vulnerability || {}).identifier || 'the vulnerability'));
                    load();
                });
            });
            ch = window.IrisVuln.chooser($(m.querySelector('[data-sc="vchooser"]')), function () {});
        }, function (e) { note(e.message, true); });
    }

    /* ---- Export (the IOCs of the attached cases the viewer can open) */
    function exportMenu(btn) {
        closeMenus();
        var mnu = document.createElement('div');
        mnu.className = 'iris-sc-menu iris-sc-menu-r';
        mnu.setAttribute('role', 'menu');
        mnu.innerHTML = '<div class="iris-sc-hint" style="padding:4px 8px 6px;">Every IOC you can see in the attached cases, deduplicated. ' + IrisHelp.icon('room.scope_export') + '</div>' +
            '<button type="button" role="menuitem" data-x="txt">Blocklist (.txt)</button><button type="button" role="menuitem" data-x="csv">CSV</button>' +
            '<button type="button" role="menuitem" data-x="stix">STIX 2.1 <span class="iris-sc-hint">TLP:GREEN / CLEAR only</span></button>' +
            '<label><input type="checkbox" data-sc="export-red"> Include TLP:RED <span class="iris-sc-hint">(txt, CSV)</span></label>';
        btn.parentNode.appendChild(mnu);
        mnu.addEventListener('click', function (e) {
            var b = e.target.closest('[data-x]');
            if (!b) { return; }
            var red = !!mnu.querySelector('[data-sc="export-red"]').checked;
            closeMenus();
            exportIocs(b.getAttribute('data-x'), red);
        });
    }
    function exportIocs(fmt, red) {
        var url = base() + '/iocs/export?format=' + encodeURIComponent(fmt) + (red ? '&include_red=1' : '');
        return fetch(url, {headers: {'Accept': '*/*'}}).then(function (r) {
            if (!r.ok) {
                return r.json().catch(function () { return {}; }).then(function (j) { note((j && j.message) || 'Export failed.', true); });
            }
            var name = (/filename="?([^";]+)"?/i.exec(r.headers.get('Content-Disposition') || '') || [])[1] || ('scope-iocs.' + (fmt === 'stix' ? 'json' : fmt));
            var held = id(r.headers.get('X-IRIS-TLP-Withheld'));
            return r.blob().then(function (blob) {
                var a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = name;
                document.body.appendChild(a);
                a.click();
                a.remove();
                note('Exported ' + name + (held ? ': ' + held + ' IOC' + (held === 1 ? '' : 's') + ' left out by their TLP.' : '.'), !!held);
            });
        }, function () { note('Export failed: the server did not answer.', true); });
    }

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
            if (k === 'iq') {
                clearTimeout(timer);
                var iv = e.target.value.trim();
                timer = setTimeout(function () {
                    var f = T('iocs').filter;
                    if (iv) { f.q = iv; } else { delete f.q; }
                    delete f.page;
                    loadIocs();
                }, 300);
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
            if (k === 'icase') {
                var f = T('iocs').filter;
                if (t.value) { f.case_id = t.value; } else { delete f.case_id; }
                delete f.page;
                loadIocs();
                return;
            }
            if (k === 'ipick' || k === 'ipick-all') {
                var ti = T('iocs');
                if (k === 'ipick') {
                    if (t.checked) { ti.sel[t.getAttribute('data-key')] = true; } else { delete ti.sel[t.getAttribute('data-key')]; }
                } else if (ti.data) {
                    ti.data.iocs.forEach(function (r) { if (t.checked) { ti.sel[r.key] = true; } else { delete ti.sel[r.key]; } });
                }
                syncIocPicks();
                return;
            }
            if (k === 'reg-case') {
                var lid = id(t.getAttribute('data-reg')), cid = id(t.value);
                api('PATCH', base() + '/registry-assets/' + lid, {case_id: cid || null}).then(function (res) {
                    if (!res.ok) { note((res.j && res.j.message) || 'Could not change the case.', true); loadRegistry(); return; }
                    note(cid ? 'Linked to case #' + cid + '.' : 'No case linked any more.');
                    loadRegistry();
                });
            }
        });
        el.addEventListener('keydown', function (e) {
            if (e.target.getAttribute('data-sc') === 'vuln' && e.key === 'Enter') { e.preventDefault(); setF('vuln', e.target.value.trim()); load(); }
            if (e.target.getAttribute('data-sc') === 'flags' && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); e.target.click(); }
        });
        el.addEventListener('click', function (e) {
            var b = e.target.closest('[data-sc]');
            if (!b) { if (!e.target.closest('.iris-sc-menu')) { closeMenus(); } return; }
            var k = b.getAttribute('data-sc');
            if (k === 'tab') { showTab(b.getAttribute('data-t')); return; }
            if (k === 'add-asset' || k === 'add-ioc') { objectDialog(k === 'add-asset' ? 'asset' : 'ioc'); return; }
            if (k === 'export') { if (b.parentNode.querySelector('.iris-sc-menu')) { closeMenus(); } else { exportMenu(b); } return; }
            if (k === 'attach') { attachDialog(); return; }
            if (k === 'rec-vuln') { vulnDialog(selected()); return; }
            if (k === 'reg-push') { var ra = regById(b.getAttribute('data-reg')); if (ra) { regPushDialog(ra); } return; }
            if (k === 'reg-detach') {
                var rd = regById(b.getAttribute('data-reg'));
                if (rd && window.confirm('Detach ' + rd.asset_name + ' from the scope? It stays in the Assets Manager.')) {
                    api('DELETE', base() + '/registry-assets/' + id(rd.id)).then(function (res) {
                        if (!res.ok) { note((res.j && res.j.message) || 'Could not detach it.', true); return; }
                        note('Detached ' + rd.asset_name + ' (kept in the Assets Manager).');
                        loadRegistry();
                        loadCounts();
                    });
                }
                return;
            }
            if (k === 'ipush-sel') { var ti = T('iocs'); if (ti.data) { iocPushDialog(ti.data.iocs.filter(function (r) { return ti.sel[r.key]; })); } return; }
            if (k === 'iclear-sel') { e.preventDefault(); T('iocs').sel = {}; syncIocPicks(); return; }
            if (k === 'ipush-row' || k === 'ipush-cell') {
                var ir = iocRow(b.getAttribute('data-key'));
                if (ir) { iocPushDialog([ir], k === 'ipush-cell' ? [id(b.getAttribute('data-case'))] : null); }
                return;
            }
            if (k === 'iprev' || k === 'inext') {
                var tf = T('iocs');
                tf.filter.page = String(Math.max(1, ((tf.data && tf.data.page) || 1) + (k === 'inext' ? 1 : -1)));
                loadIocs();
                return;
            }
            if (k === 'cust-assets') {
                S.filter = {customer_id: String(id(b.getAttribute('data-cust')))};
                S.sel = {};
                S.tab = 'assets';
                draw();
                load();
                return;
            }
            if (k === 'st-push' || k === 'st-edit' || k === 'st-del') {
                var sx = stagedById(b.getAttribute('data-staged'));
                if (!sx) { return; }
                if (k === 'st-push') { stagedPushDialog(sx); } else if (k === 'st-edit') { objectDialog(sx.kind, sx); } else { discardStaged(sx); }
                return;
            }
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
        loadCounts();
        loadRegistry();
        loadTab(S.tab);
        return load();
    };
    /* the Board's tiles and ?pane=scope addresses: the Assets filters, and ?tab=<sub-tab> (a filter means Assets) */
    R.setFilter = function (f) {
        var tab = f && f.tab;
        S.filter = clean(f);
        S.sel = {};
        S.note = null;
        S.tab = TABS.some(function (t) { return t[0] === tab; }) ? tab : 'assets';
        if (S.el) { draw(); load(); loadTab(S.tab); }
    };
    R.showTab = function (name) { return S.el ? showTab(name) : Promise.resolve(); };
    R.reload = function () { return S.el ? load() : Promise.resolve(); };
    R._state = S;
    window.IrisRoomScope = R;
}());

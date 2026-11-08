/* War-room Board and Decisions tabs (iris-ng 2026-11-07).
 *
 * window.IrisRoomBoard - import-free (ui/public). war_room.js mounts both on first open:
 *   IrisRoomBoard.mountDecisions(el, ctx)   the decision register (D-n), propose / vote / implement / supersede
 *   IrisRoomBoard.mountBoard(el, ctx)       the room's Board of widgets; leads set the layout, anyone hides /
 *                                           reorders widgets for themselves (kept in this browser)
 *   IrisRoomBoard.openDecision(id)          select a decision (Board links, ?pane=decisions&d=<id>)
 * ctx: {roomId, guest, active (room not closed), openPane(name)}.
 *
 * Server values go through esc() before an innerHTML build, ids through id();
 * rationale_html and note HTML come from the server's sanitising Markdown
 * renderer. Stored times are UTC and shown as UTC strings. POST bodies carry
 * csrf_token; PATCH / PUT / DELETE are exempt (the v2 rule).
 */
(function () {
    'use strict';
    if (window.IrisRoomBoard) { return; }
    var B = {};
    var IrisHelp = window.IrisHelp || {icon: function () { return ''; }};
    var $ = window.jQuery;
    var ctx = null;
    var STATUS = {proposed: 'Pending', approved: 'Approved', rejected: 'Rejected', superseded: 'Superseded'};
    /* the register's status chips: [filter value, label, key in the list reply's counts] */
    var CHIPS = [['', 'All', 'all'], ['open', 'Open', 'open'], ['proposed', 'Pending', 'proposed'],
                 ['approved', 'Approved', 'approved'], ['rejected', 'Rejected', 'rejected'],
                 ['superseded', 'Superseded', 'superseded'], ['overdue', 'Overdue', 'overdue'],
                 ['implemented', 'Implemented', 'implemented']];
    var GAVEL = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m14.5 12.5-8 8a2.119 2.119 0 1 1-3-3l8-8"/><path d="m16 16 6-6"/><path d="m8 8 6-6"/><path d="m9 7 8 8"/><path d="m21 11-8-8"/></svg>';
    var STATUS_CLS = {proposed: '#8fa3ef', approved: '#2dce89', rejected: '#ff8095', superseded: '#9a9aa5'};
    var VERDICT = {pending: 'pending', approved: 'approved', rejected: 'rejected'};

    function esc(s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function id(v) {
        var s = String(v == null ? '' : v);
        return /^\d+$/.test(s) ? String(parseInt(s, 10)) : null;
    }
    function csrf() {
        var el = document.getElementById('csrf_token') || document.querySelector('input[name="csrf_token"]');
        return el ? el.value : '';
    }
    function api(path, method, body) {
        var opts = {method: method || 'GET', credentials: 'same-origin', headers: {'Accept': 'application/json'}};
        if (body !== undefined) {
            body = Object.assign({}, body);
            if (opts.method === 'POST') { body.csrf_token = csrf(); }
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        return fetch('/api/v2/war-rooms/' + id(ctx.roomId) + path, opts).then(function (r) {
            if (r.status === 204) { return {ok: true, status: 204, j: {}}; }
            return r.json().then(function (j) { return {ok: r.ok, status: r.status, j: j}; },
                function () { return {ok: r.ok, status: r.status, j: {}}; });
        });
    }
    function errText(res) {
        return (res && res.j && (res.j.message || (res.j.data && res.j.data.message))) || 'The request failed (HTTP ' + (res ? res.status : '?') + ').';
    }
    function utc(iso) {
        return iso ? String(iso).replace('T', ' ').replace(/(:\d\d)(\.\d+)?Z?$/, '$1').slice(0, 16) + ' UTC' : '';
    }
    function span(ms) {
        var m = Math.abs(ms) / 60000;
        if (m < 60) { return Math.max(1, Math.round(m)) + ' min'; }
        if (m < 1440) { return Math.round(m / 60) + ' h'; }
        return Math.round(m / 1440) + ' d';
    }
    function due(d) {
        if (!d.target_at) { return '<span class="iris-rb-muted">No target</span>'; }
        var t = Date.parse(d.target_at), now = Date.now();
        var rel = d.is_open ? (t >= now ? 'in ' + span(t - now) : 'overdue by ' + span(t - now)) : '';
        return '<span class="' + (d.is_overdue ? 'iris-rb-over' : '') + '" title="' + esc(utc(d.target_at)) + '">' +
            esc(utc(d.target_at)) + (rel ? ' &middot; ' + esc(rel) : '') + '</span>';
    }
    function statusBadge(s, implemented) {
        return '<span class="iris-rb-status" style="color:' + (STATUS_CLS[s] || '#9a9aa5') + ';border-color:' + (STATUS_CLS[s] || '#9a9aa5') + '66;">' +
            esc(STATUS[s] || s) + '</span>' + (implemented ? ' <span class="iris-rb-status" style="color:#2dce89;border-color:#2dce8966;">Implemented</span>' : '');
    }
    function css() {
        if (document.getElementById('iris-rb-css')) { return; }
        var st = document.createElement('style');
        st.id = 'iris-rb-css';
        st.textContent = [
            '.iris-rb-muted{color:#9a9aa5;font-size:.78rem;}',
            '.iris-rb-over{color:#ff8095;}',
            '.iris-rb-status{display:inline-block;border:1px solid;border-radius:5px;font-size:.68rem;padding:0 6px;line-height:1.6;}',
            '.iris-rb-split{display:flex;gap:14px;align-items:flex-start;}',
            '.iris-rb-left{flex:0 0 42%;min-width:0;}',
            '.iris-rb-right{flex:1 1 auto;min-width:0;}',
            '.iris-rb-list{list-style:none;margin:0;padding:0;border:1px solid rgba(255,255,255,.07);border-radius:8px;max-height:620px;overflow:auto;}',
            '.iris-rb-li{padding:8px 11px;border-bottom:1px solid rgba(255,255,255,.05);cursor:pointer;}',
            '.iris-rb-li:hover{background:rgba(255,255,255,.03);}',
            '.iris-rb-li.active{background:rgba(139,92,246,.12);box-shadow:inset 3px 0 0 #8B5CF6;}',
            '.iris-rb-ref{font-family:monospace;font-weight:700;color:#a78bfa;margin-right:6px;}',
            '.iris-rb-card{border:1px solid rgba(255,255,255,.07);border-radius:8px;padding:12px 14px;background:#15151a;}',
            '.iris-rb-sec{color:#7a7a85;font-size:.62rem;letter-spacing:.08em;text-transform:uppercase;margin:12px 0 4px;}',
            '.iris-rb-chip{display:inline-block;border:1px solid rgba(255,255,255,.15);border-radius:6px;padding:0 6px;font-size:.74rem;margin:0 4px 4px 0;}',
            '.iris-rb-trail{list-style:none;padding:0;margin:0;font-size:.76rem;}',
            '.iris-rb-trail li{padding:3px 0;border-bottom:1px solid rgba(255,255,255,.04);}',
            '.iris-rb-linkbtn{background:none;border:0;padding:0;color:#a78bfa;cursor:pointer;text-align:left;}',
            '.iris-rb-linkbtn:hover{text-decoration:underline;}',
            '.iris-rb-note{font-size:.84rem;}',
            '.iris-rb-min0{min-width:0;}',
            '.iris-rb-head{display:flex;flex-wrap:wrap;align-items:flex-start;gap:10px;margin-bottom:12px;}',
            '.iris-rb-h1{font-size:1.05rem;font-weight:600;margin:0;color:#e8e8ee;}',
            '.iris-rb-head-btns{margin-left:auto;display:flex;flex-wrap:wrap;gap:6px;}',
            '.iris-rb-btn{display:inline-flex;align-items:center;gap:6px;}',
            '.iris-rb-tz{display:grid;gap:12px;grid-template-columns:repeat(6,minmax(0,1fr));margin-bottom:14px;}',
            '.iris-rb-kpi{display:block;border:1px solid rgba(255,255,255,.08);border-radius:12px;background:#15151a;padding:13px 15px;min-width:0;color:#c8c8d0;text-decoration:none;transition:border-color .15s;}',
            'a.iris-rb-kpi:hover,a.iris-rb-kpi:focus-visible{border-color:rgba(139,92,246,.55);color:#c8c8d0;text-decoration:none;}',
            '.iris-rb-kpi-wide{grid-column:span 2;}',
            '.iris-rb-kpi-danger{border-color:rgba(239,68,68,.5);background:rgba(239,68,68,.1);}',
            '.iris-rb-kpi-top{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:.78rem;color:#9a9aa5;font-weight:500;}',
            '.iris-rb-kpi-label{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
            '.iris-rb-kpi-ic{flex:0 0 auto;color:#7a7a85;}',
            '.iris-rb-kpi-n{font-size:1.55rem;font-weight:600;color:#e8e8ee;margin-top:4px;font-variant-numeric:tabular-nums;line-height:1.2;}',
            '.iris-rb-kpi-sub{display:flex;align-items:center;gap:4px;font-size:.7rem;color:#9a9aa5;margin-top:2px;}',
            '.iris-rb-kpi-sub span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
            '.iris-rb-kpi-go{opacity:0;transition:opacity .15s;flex:0 0 auto;}',
            'a.iris-rb-kpi:hover .iris-rb-kpi-go,a.iris-rb-kpi:focus-visible .iris-rb-kpi-go{opacity:1;}',
            '.iris-rb-kpi-pct{display:flex;align-items:baseline;gap:6px;}',
            '.iris-rb-t-red{color:#f87171 !important;}',
            '.iris-rb-t-amber{color:#fbbf24 !important;}',
            '.iris-rb-t-blue{color:#7dd3fc !important;}',
            '.iris-rb-bar{display:flex;height:8px;border-radius:999px;background:rgba(255,255,255,.08);overflow:hidden;margin:8px 0 6px;}',
            '.iris-rb-bar i{display:block;height:100%;background:#10b981;}',
            '.iris-rb-bar-thin{height:6px;}',
            '.iris-rb-legend{list-style:none;padding:0;margin:6px 0 0;display:flex;flex-wrap:wrap;gap:4px 12px;font-size:.7rem;color:#9a9aa5;}',
            '.iris-rb-legend a,.iris-rb-legend span{color:inherit;display:inline-flex;align-items:center;gap:4px;}',
            '.iris-rb-legend a:hover{color:#e8e8ee;text-decoration:underline;}',
            '.iris-rb-legend b{color:#e8e8ee;font-weight:600;}',
            '.iris-rb-dot{display:inline-block;width:8px;height:8px;border-radius:50%;flex:0 0 auto;}',
            '.iris-rb-plink{display:inline-flex;align-items:center;gap:3px;font-size:.74rem;color:#60a5fa;}',
            '.iris-rb-plink:hover{color:#93c5fd;}',
            '.iris-rb-ml{margin-left:auto;}',
            '.iris-rb-cols{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:14px;align-items:start;}',
            '.iris-rb-cols-one{grid-template-columns:minmax(0,1fr);}',
            '.iris-rb-col{display:flex;flex-direction:column;gap:14px;min-width:0;}',
            '.iris-rb-w{border:1px solid rgba(255,255,255,.08);border-radius:12px;background:#15151a;min-width:0;overflow:hidden;}',
            '.iris-rb-ph{display:flex;align-items:center;gap:8px;padding:11px 15px;border-bottom:1px solid rgba(255,255,255,.06);}',
            '.iris-rb-ph h3{font-size:.88rem;font-weight:600;margin:0;color:#e8e8ee;}',
            '.iris-rb-ph-ic{color:#9a9aa5;flex:0 0 auto;}',
            '.iris-rb-count{display:inline-block;min-width:20px;text-align:center;border-radius:999px;font-size:.66rem;font-weight:600;padding:1px 6px;background:rgba(255,255,255,.08);color:#c8c8d0;}',
            '.iris-rb-c-red{background:rgba(239,68,68,.18);color:#fca5a5;}',
            '.iris-rb-c-amber{background:rgba(245,158,11,.18);color:#fcd34d;}',
            '.iris-rb-c-blue{background:rgba(59,130,246,.18);color:#93c5fd;}',
            '.iris-rb-pb{padding:10px 15px;}',
            '.iris-rb-pf{padding:7px 15px;border-top:1px solid rgba(255,255,255,.06);font-size:.68rem;color:#7a7a85;}',
            '.iris-rb-empty-line{text-align:center;color:#9a9aa5;font-size:.8rem;margin:14px 0;}',
            '.iris-rb-rows{list-style:none;padding:0;margin:0;max-height:24rem;overflow-y:auto;}',
            '.iris-rb-rows > li{border-bottom:1px solid rgba(255,255,255,.05);}',
            '.iris-rb-rows > li:last-child{border-bottom:0;}',
            '.iris-rb-row{display:flex;align-items:center;gap:8px;padding:7px 2px;color:#e8e8ee;font-size:.8rem;}',
            'a.iris-rb-row:hover{color:#e8e8ee;text-decoration:none;background:rgba(255,255,255,.03);}',
            '.iris-rb-grow{flex:1 1 auto;}',
            '.iris-rb-meta{display:block;font-size:.7rem;color:#9a9aa5;}',
            '.iris-rb-when{display:inline-flex;align-items:center;gap:3px;}',
            '.iris-rb-att-i{display:flex;align-items:flex-start;gap:8px;padding:8px 2px;font-size:.8rem;color:#e8e8ee;}',
            '.iris-rb-att-ic{color:#9a9aa5;flex:0 0 auto;margin-top:2px;}',
            '.iris-rb-sev{width:8px;height:8px;border-radius:50%;margin-top:6px;flex:0 0 auto;background:#94a3b8;}',
            '.iris-rb-sev-high{background:#ef4444;}',
            '.iris-rb-sev-medium{background:#f59e0b;}',
            '.iris-rb-act{flex:0 0 auto;font-size:.7rem;padding:1px 8px;}',
            '.iris-rb-pill{display:inline-block;border:1px solid rgba(255,255,255,.15);border-radius:6px;font-size:.66rem;font-weight:500;padding:1px 6px;white-space:nowrap;color:#c8c8d0;}',
            '.iris-rb-pill-open{border-color:rgba(16,185,129,.4);background:rgba(16,185,129,.1);color:#6ee7b7;}',
            '.iris-rb-pill-closed{background:rgba(255,255,255,.05);color:#9a9aa5;}',
            '.iris-rb-pill-red{border-color:rgba(239,68,68,.45);background:rgba(239,68,68,.1);color:#fca5a5;}',
            '.iris-rb-pill-in_progress{border-color:rgba(14,165,233,.45);background:rgba(14,165,233,.1);color:#7dd3fc;}',
            '.iris-rb-pill-on_hold,.iris-rb-pill-blocked{border-color:rgba(245,158,11,.45);background:rgba(245,158,11,.1);color:#fcd34d;}',
            '.iris-rb-st-in_progress{background:#0ea5e9;}',
            '.iris-rb-st-todo{background:#94a3b8;}',
            '.iris-rb-st-on_hold,.iris-rb-st-blocked{background:#f59e0b;}',
            '.iris-rb-more{display:block;text-align:center;font-size:.74rem;padding:6px 0 0;}',
            '.iris-rb-cases{display:grid;gap:8px;grid-template-columns:minmax(0,1fr);}',
            '.iris-rb-cases-wide{grid-template-columns:repeat(auto-fill,minmax(260px,1fr));}',
            '.iris-rb-case{border:1px solid rgba(255,255,255,.08);border-radius:10px;background:#1a1a20;padding:10px 12px;min-width:0;}',
            '.iris-rb-case-locked{display:flex;align-items:center;gap:8px;border-style:dashed;background:rgba(255,255,255,.02);color:#9a9aa5;font-size:.8rem;}',
            '.iris-rb-case-h{display:flex;gap:8px;align-items:flex-start;}',
            '.iris-rb-case-t{font-weight:600;font-size:.84rem;color:#e8e8ee;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
            'a.iris-rb-case-t:hover{color:#c4b5fd;}',
            '.iris-rb-case-n{display:flex;justify-content:space-between;font-size:.7rem;color:#9a9aa5;}',
            '.iris-rb-case-i{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:.7rem;color:#9a9aa5;margin-top:6px;}',
            '.iris-rb-case-i a,.iris-rb-case-i span{display:inline-flex;align-items:center;gap:3px;}',
            '.iris-rb-case-i a{color:#9a9aa5;}',
            '.iris-rb-case-i a:hover{color:#e8e8ee;}',
            '.iris-rb-meta svg{vertical-align:-2px;margin-right:2px;}',
            '.iris-rb-mono{font-family:monospace;font-size:.76rem;color:#9a9aa5;}',
            '.iris-rb-ed{border:1px solid rgba(139,92,246,.45);border-radius:12px;background:#15151a;margin-bottom:14px;}',
            '.iris-rb-ed-h{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid rgba(255,255,255,.06);}',
            '.iris-rb-ed-z{display:grid;gap:12px;padding:12px 14px;grid-template-columns:minmax(0,2fr) minmax(0,1fr);}',
            '.iris-rb-zone-tile{grid-column:1 / -1;}',
            '.iris-rb-cust-z{grid-template-columns:repeat(3,minmax(0,1fr));}',
            '.iris-rb-cust-z .iris-rb-zone-tile{grid-column:auto;}',
            '.iris-rb-zone{border:1px solid transparent;border-radius:10px;padding:6px;min-width:0;}',
            '.iris-rb-zone.iris-rb-dropzone{border-color:rgba(139,92,246,.6);border-style:dashed;background:rgba(139,92,246,.05);}',
            '.iris-rb-zone-h{font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;color:#9a9aa5;margin-bottom:6px;}',
            '.iris-rb-zone-h .iris-rb-meta{display:inline;text-transform:none;letter-spacing:0;}',
            '.iris-rb-zone-rows{display:flex;flex-direction:column;gap:6px;}',
            '.iris-rb-zone-tile .iris-rb-zone-rows{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));}',
            '.iris-rb-cust-z .iris-rb-zone-tile .iris-rb-zone-rows{display:flex;}',
            '.iris-rb-zone-empty{border:1px dashed rgba(255,255,255,.12);border-radius:8px;padding:10px;text-align:center;font-size:.7rem;color:#7a7a85;}',
            '.iris-rb-ed-row{display:flex;align-items:center;gap:6px;border:1px solid rgba(255,255,255,.08);border-radius:8px;background:#1a1a20;padding:6px 8px;min-width:0;}',
            '.iris-rb-ed-row[draggable="true"]{cursor:grab;}',
            '.iris-rb-ed-row.iris-rb-dragging{opacity:.5;}',
            '.iris-rb-ed-row.iris-rb-off{opacity:.55;}',
            '.iris-rb-ed-t{font-size:.78rem;font-weight:500;color:#e8e8ee;}',
            '.iris-rb-grip{color:#7a7a85;flex:0 0 auto;}',
            '.iris-rb-ibtn{background:none;border:0;border-radius:6px;padding:3px;color:#9a9aa5;line-height:0;cursor:pointer;}',
            '.iris-rb-ibtn:hover:not([disabled]){background:rgba(255,255,255,.08);color:#e8e8ee;}',
            '.iris-rb-ibtn[disabled]{opacity:.3;cursor:default;}',
            '.iris-rb-add{display:flex;align-items:center;justify-content:center;gap:4px;width:100%;margin-top:6px;border:1px dashed rgba(255,255,255,.18);border-radius:8px;background:none;color:#9a9aa5;font-size:.72rem;padding:6px;cursor:pointer;}',
            '.iris-rb-add:hover:not([disabled]){border-color:rgba(139,92,246,.6);color:#e8e8ee;background:rgba(139,92,246,.06);}',
            '.iris-rb-stable td,.iris-rb-stable th{vertical-align:top;font-size:.8rem;}',
            '.iris-rb-stable th{color:#9a9aa5;font-weight:500;font-size:.72rem;}',
            '@media (max-width: 1399px){.iris-rb-tz{grid-template-columns:repeat(4,minmax(0,1fr));}}',
            '@media (max-width: 575px){.iris-rb-tz{grid-template-columns:minmax(0,1fr);}.iris-rb-kpi-wide{grid-column:auto;}}',
            '.iris-rb-fchips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;}',
            '.iris-rb-fchip{background:none;border:1px solid rgba(255,255,255,.14);border-radius:999px;color:#c8c8d0;font-size:.74rem;padding:1px 10px;cursor:pointer;}',
            '.iris-rb-fchip.active{border-color:#4a8cff;background:rgba(74,140,255,.15);color:#9ec2ff;}',
            '.iris-rb-fchip b{font-weight:600;margin-left:3px;}',
            '.iris-rb-pick{background:none;border:1px solid rgba(255,255,255,.15);border-radius:6px;color:#c8c8d0;font-size:.76rem;padding:1px 8px;margin:0 4px 4px 0;cursor:pointer;}',
            '.iris-rb-pick.on{border-color:#4a8cff;background:rgba(74,140,255,.15);color:#e8e8ee;}',
            '.iris-rb-empty{text-align:center;padding:48px 16px;}',
            '.iris-rb-empty-ic{display:inline-flex;width:40px;height:40px;border-radius:50%;align-items:center;justify-content:center;background:rgba(139,92,246,.15);color:#a78bfa;margin-bottom:10px;}',
            '.iris-rb-empty-ic svg{width:20px;height:20px;}',
            '@media (max-width: 991px){.iris-rb-split{display:block;}.iris-rb-left{margin-bottom:12px;}.iris-rb-cols,.iris-rb-ed-z,.iris-rb-cust-z{grid-template-columns:minmax(0,1fr);}.iris-rb-tz{grid-template-columns:repeat(2,minmax(0,1fr));}}'
        ].join('\n');
        document.head.appendChild(st);
    }
    function modal(o) {
        var $m = $('<div class="modal fade" tabindex="-1" role="dialog" aria-modal="true"><div class="modal-dialog ' + (o.size || 'modal-lg') +
            '" role="document"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title">' + o.title + '</h5>' +
            (o.subtitle ? '<div class="iris-rb-muted">' + o.subtitle + '</div>' : '') +
            '</div><button type="button" class="close" data-dismiss="modal" aria-label="Close"><span aria-hidden="true">&times;</span></button></div>' +
            '<div class="modal-body">' + o.body + '<div class="text-danger small mt-2" data-rb="err" role="alert"></div></div>' +
            '<div class="modal-footer">' + o.footer + '</div></div></div></div>');
        $('body').append($m);
        $m.on('hidden.bs.modal', function () { $m.remove(); });
        $m.modal({backdrop: 'static'});
        return $m;
    }

    /* ================================================================ Decisions */
    var D = {el: null, list: [], sel: null, canPropose: false, members: null, cases: null, filter: {status: '', q: '', case_id: ''}};

    B.mountDecisions = function (el, c) {
        css();
        ctx = c;
        D.el = el;
        el.innerHTML =
            '<div class="d-flex flex-wrap align-items-center mb-2" style="gap:6px;">' +
            '<h2 class="h6 mb-0 mr-1">Decisions</h2>' + IrisHelp.icon('room.decisions') +
            '<span class="iris-rb-muted" data-rb="total"></span>' +
            '<span class="ml-auto"></span>' +
            '<button type="button" class="btn btn-sm btn-outline-secondary" data-rb="fromchat" style="display:none;">From chat</button>' +
            '<button type="button" class="btn btn-sm btn-primary" data-rb="propose" style="display:none;">+ Propose</button></div>' +
            '<div class="iris-rb-fchips" role="group" aria-label="Filter by status">' + CHIPS.map(function (c) {
                return '<button type="button" class="iris-rb-fchip' + (c[0] ? '' : ' active') + '" data-rb="chip" data-v="' + c[0] +
                    '" aria-pressed="' + (c[0] ? 'false' : 'true') + '">' + c[1] + ' <b data-rb-count="' + c[2] + '">&ndash;</b></button>';
            }).join('') + '</div>' +
            '<div class="d-flex flex-wrap align-items-center mb-2" style="gap:6px;">' +
            '<label class="sr-only" for="iris-rb-dcase">Case</label><select id="iris-rb-dcase" class="form-control form-control-sm" style="max-width:190px;"><option value="">All cases</option></select>' +
            '<label class="sr-only" for="iris-rb-dq">Search decisions</label><input type="text" id="iris-rb-dq" class="form-control form-control-sm" style="max-width:220px;" placeholder="Search D-n, title, owner…"></div>' +
            '<div class="iris-rb-split"><div class="iris-rb-left"><ul class="iris-rb-list" data-rb="list" aria-label="Decision register"><li class="p-3 iris-rb-muted">Loading…</li></ul></div>' +
            '<div class="iris-rb-right" data-rb="detail"></div></div>';
        setChips();
        var $el = $(el);
        $el.on('click', '[data-rb="chip"]', function () {
            D.filter.status = $(this).attr('data-v') || '';
            setChips();
            loadList();
        });
        $el.on('change', '#iris-rb-dcase', function () { D.filter.case_id = id($(this).val()) || ''; loadList(); });
        var t = null;
        $el.on('input', '#iris-rb-dq', function () {
            var v = $(this).val();
            clearTimeout(t);
            t = setTimeout(function () { D.filter.q = v; loadList(); }, 250);
        });
        $el.on('click', '.iris-rb-li', function () { selectDecision(Number($(this).attr('data-id'))); });
        $el.on('keydown', '.iris-rb-li', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $(this).trigger('click'); } });
        $el.on('click', '[data-rb="propose"]', function () { openForm({}); });
        $el.on('click', '[data-rb="fromchat"]', fromChat);
        $el.on('click', '[data-rb="act"]', function () { act($(this).attr('data-act')); });
        $el.on('click', '[data-rb="goto"]', function () { selectDecision(Number($(this).attr('data-id'))); });
        loadCases().then(function () { loadList(); });
    };

    function loadCases() {
        if (D.cases !== null) { return Promise.resolve(D.cases); }
        return api('/cases').then(function (res) {
            D.cases = res.ok ? (Array.isArray(res.j) ? res.j : (res.j.cases || [])) : [];
            var $s = $(D.el).find('#iris-rb-dcase');
            D.cases.forEach(function (c) {
                $s.append($('<option>').val(String(c.case_id)).text(c.case_name || c.name || ('Case #' + c.case_id)));
            });
            return D.cases;
        });
    }
    function setChips() {
        $(D.el).find('[data-rb="chip"]').each(function () {
            var on = ($(this).attr('data-v') || '') === (D.filter.status || '');
            $(this).toggleClass('active', on).attr('aria-pressed', on ? 'true' : 'false');
        });
    }
    function emptyHtml() {
        return '<div class="iris-rb-empty" data-rb="empty"><div class="iris-rb-empty-ic">' + GAVEL + '</div>' +
            '<div class="h6 mb-1">No decisions yet</div>' +
            '<div class="iris-rb-muted mb-3">Record the calls the room makes: isolate a site, reset credentials, accept a risk. ' +
            'Each one gets a D-number, an owner, a target date and time, and optional approvers who vote on it.</div>' +
            (D.canPropose ? '<button type="button" class="btn btn-sm btn-primary mr-1" data-rb="propose">+ Propose a decision</button>' +
                '<button type="button" class="btn btn-sm btn-outline-secondary" data-rb="fromchat">Promote from chat</button>' : '') + '</div>';
    }
    function loadMembers() {
        if (D.members !== null) { return Promise.resolve(D.members); }
        return api('/members').then(function (res) {
            var rows = res.ok ? (Array.isArray(res.j) ? res.j : (res.j.members || [])) : [];
            D.members = rows.filter(function (m) { return m.user_id && !m.is_guest; });
            return D.members;
        });
    }
    function loadList(selectId) {
        var q = [];
        Object.keys(D.filter).forEach(function (k) { if (D.filter[k]) { q.push(k + '=' + encodeURIComponent(D.filter[k])); } });
        return api('/decisions' + (q.length ? '?' + q.join('&') : '')).then(function (res) {
            var $l = $(D.el).find('[data-rb="list"]');
            if (!res.ok || !Array.isArray(res.j.decisions)) { $l.html('<li class="p-3 text-danger">' + esc(errText(res)) + '</li>'); return; }
            D.list = res.j.decisions;
            D.canPropose = !!res.j.can_propose && !ctx.guest;
            $(D.el).find('[data-rb="propose"],[data-rb="fromchat"]').toggle(D.canPropose);
            var counts = res.j.counts || {};
            $(D.el).find('[data-rb-count]').each(function () {
                var k = $(this).attr('data-rb-count');
                $(this).text(counts[k] == null ? '\u2013' : String(Number(counts[k]) || 0));
            });
            $(D.el).find('[data-rb="total"]').text(counts.all == null ? '' : Number(counts.all) + ' decision' + (Number(counts.all) === 1 ? '' : 's'));
            var filtered = !!(D.filter.status || D.filter.q || D.filter.case_id);
            if (!D.list.length) {
                $l.html('<li class="p-3 iris-rb-muted">' + (filtered ? 'No decisions match the current filters.' : 'No decisions yet.') + '</li>');
            } else {
                $l.html(D.list.map(function (d) {
                    var votes = d.approvers.length ? ' &middot; ' + d.approvers.filter(function (a) { return a.verdict === 'approved'; }).length + '/' + d.approvers.length + ' approved' : '';
                    return '<li class="iris-rb-li' + (d.decision_id === D.sel ? ' active' : '') + '" data-id="' + id(d.decision_id) + '" tabindex="0" role="button">' +
                        '<div><span class="iris-rb-ref">' + esc(d.ref) + '</span>' + esc(d.title) + '</div>' +
                        '<div class="iris-rb-muted mt-1">' + statusBadge(d.status, !!d.implemented_at) + ' ' + due(d) +
                        (d.owner_name ? ' &middot; ' + esc(d.owner_name) : '') + votes +
                        (d.can.vote && d.my_verdict === 'pending' ? ' &middot; <b style="color:#f4c430;">awaits your vote</b>' : '') + '</div></li>';
                }).join(''));
            }
            var want = selectId || D.sel || (D.list[0] && D.list[0].decision_id);
            if (want) { selectDecision(want); }
            else { $(D.el).find('[data-rb="detail"]').html(filtered ? '<div class="iris-rb-muted p-3">No decision matches the current filters.</div>' : emptyHtml()); }
        });
    }
    B.openDecision = function (did) {
        if (!D.el) { return; }   /* war_room.js mounts the pane before it opens a decision */
        D.filter = {status: '', q: '', case_id: ''};
        $(D.el).find('#iris-rb-dcase').val('');
        setChips();
        $(D.el).find('#iris-rb-dq').val('');
        loadList(Number(did));
    };
    function selectDecision(did) {
        D.sel = did;
        $(D.el).find('.iris-rb-li').removeClass('active').filter('[data-id="' + id(did) + '"]').addClass('active');
        api('/decisions/' + id(did)).then(function (res) {
            var $d = $(D.el).find('[data-rb="detail"]');
            if (!res.ok) { $d.html('<div class="text-danger p-3">' + esc(errText(res)) + '</div>'); return; }
            D.cur = res.j;
            $d.html(detailHtml(res.j));
        });
    }
    function scopeHtml(d) {
        if (d.whole_room) { return '<span class="iris-rb-chip">Whole war room</span>'; }
        return d.cases.map(function (c) {
            return '<span class="iris-rb-chip">' + (c.restricted ? '<i>Restricted case</i>' : 'Case: ' + esc(c.case_name)) + '</span>';
        }).join('') + d.assets.map(function (a) {
            return '<span class="iris-rb-chip">' + (a.restricted ? '<i>Restricted asset</i>' : 'Asset: ' +
                (ctx.guest ? esc(a.asset_name) : '<a href="/case/assets?cid=' + id(a.case_id) + '&asset=' + id(a.asset_id) + '&tab=details">' + esc(a.asset_name) + '</a>')) + '</span>';
        }).join('');
    }
    function detailHtml(d) {
        var c = d.can || {};
        var btn = function (a, label, cls) { return '<button type="button" class="btn btn-sm ' + (cls || 'btn-outline-secondary') + '" data-rb="act" data-act="' + a + '">' + label + '</button>'; };
        var actions = (c.vote ? btn('approve', 'Approve', 'btn-success') + btn('reject', 'Reject', 'btn-outline-danger') : '') +
            (c.set_status ? btn('set-approved', 'Mark approved', 'btn-success') + btn('set-rejected', 'Mark rejected', 'btn-outline-danger') : '') +
            (c.implement ? (d.implemented_at ? btn('reopen', 'Reopen') : btn('implemented', 'Mark implemented', 'btn-primary')) : '') +
            (c.edit ? btn('edit', 'Edit') : '') + (c.supersede ? btn('supersede', 'Supersede with a new decision…') : '') +
            (c['delete'] ? btn('delete', 'Delete', 'btn-outline-danger') : '');
        return '<div class="iris-rb-card">' +
            '<div class="d-flex align-items-start" style="gap:8px;"><div style="flex:1 1 auto;min-width:0;"><div class="h6 mb-1"><span class="iris-rb-ref">' + esc(d.ref) + '</span>' + esc(d.title) + '</div>' +
            '<div>' + statusBadge(d.status, !!d.implemented_at) + '</div></div></div>' +
            (actions ? '<div class="d-flex flex-wrap mt-2" style="gap:6px;">' + actions + '</div>' : '') +
            '<div class="iris-rb-sec">Owner</div><div>' + (d.owner_name ? esc(d.owner_name) : '<span class="iris-rb-muted">Unassigned</span>') + '</div>' +
            '<div class="iris-rb-sec">Target ' + IrisHelp.icon('decision.target') + '</div><div>' + due(d) + '</div>' +
            '<div class="iris-rb-sec">Applies to ' + IrisHelp.icon('decision.applies_to') + '</div><div>' + scopeHtml(d) + '</div>' +
            '<div class="iris-rb-sec">Approvers ' + IrisHelp.icon('decision.approvers') + '</div>' +
            (d.approvers.length ? '<ul class="iris-rb-trail">' + d.approvers.map(function (a) {
                return '<li>' + esc(a.name || ('#' + a.user_id)) + ' &middot; <span style="color:' + (a.verdict === 'approved' ? '#2dce89' : a.verdict === 'rejected' ? '#ff8095' : '#9a9aa5') + ';">' +
                    esc(VERDICT[a.verdict] || a.verdict) + '</span>' + (a.voted_at ? ' <span class="iris-rb-muted">' + esc(utc(a.voted_at)) + '</span>' : '') + '</li>';
            }).join('') + '</ul>' : '<div class="iris-rb-muted">No approver required: a lead or the owner decides.</div>') +
            '<div class="iris-rb-sec">Implementation ' + IrisHelp.icon('decision.implementation') + '</div><div>' +
            (d.implemented_at ? 'Implemented ' + esc(utc(d.implemented_at)) + (d.implemented_by_name ? ' by ' + esc(d.implemented_by_name) : '')
                : '<span class="iris-rb-muted">Not implemented</span>') + '</div>' +
            (d.supersedes ? '<div class="iris-rb-sec">Supersedes</div><div><button type="button" class="iris-rb-linkbtn" data-rb="goto" data-id="' + id(d.supersedes.decision_id) + '">' +
                esc(d.supersedes.ref) + ' ' + esc(d.supersedes.title) + '</button></div>' : '') +
            (d.superseded_by && d.superseded_by.length ? '<div class="iris-rb-sec">Superseded by</div><div>' + d.superseded_by.map(function (x) {
                return '<button type="button" class="iris-rb-linkbtn mr-2" data-rb="goto" data-id="' + id(x.decision_id) + '">' + esc(x.ref) + '</button>' + statusBadge(x.status);
            }).join(' ') + '</div>' : '') +
            (d.cited_by_flags || d.cited_by_findings ? '<div class="iris-rb-sec">Cited by</div><div>' + [
                d.cited_by_flags ? Number(d.cited_by_flags) + ' asset flag' + (Number(d.cited_by_flags) === 1 ? '' : 's') : '',
                d.cited_by_findings ? Number(d.cited_by_findings) + ' vulnerability finding' + (Number(d.cited_by_findings) === 1 ? '' : 's') : ''
            ].filter(Boolean).join(' &middot; ') + '</div>' : '') +
            '<div class="iris-rb-sec">Rationale</div><div class="iris-rb-note">' + (d.rationale_html || '<span class="iris-rb-muted">No rationale.</span>') + '</div>' +
            '<div class="iris-rb-sec">Trail</div><ul class="iris-rb-trail">' + (d.trail || []).map(function (t) {
                return '<li><span class="iris-rb-muted">' + esc(utc(t.at)) + '</span> &middot; ' + esc(t.action.replace(/_/g, ' ')) +
                    (t.detail ? ' (' + esc(t.detail) + ')' : '') + (t.user_name ? ' &middot; ' + esc(t.user_name) : '') + '</li>';
            }).join('') + '</ul></div>';
    }
    function act(a) {
        var d = D.cur;
        if (!d) { return; }
        var base = '/decisions/' + id(d.decision_id);
        var call = null;
        if (a === 'approve' || a === 'reject') { call = api(base + '/vote', 'POST', {verdict: a === 'approve' ? 'approved' : 'rejected'}); }
        else if (a === 'set-approved' || a === 'set-rejected') { call = api(base, 'PATCH', {status: a === 'set-approved' ? 'approved' : 'rejected'}); }
        else if (a === 'implemented') { call = api(base + '/implemented', 'POST', {}); }
        else if (a === 'reopen') { call = api(base + '/reopen', 'POST', {}); }
        else if (a === 'edit') { openForm({decision: d}); return; }
        else if (a === 'supersede') { openForm({supersedes: d}); return; }
        else if (a === 'delete') {
            if (!window.confirm('Delete ' + d.ref + ' "' + d.title + '"? Its trail goes with it.')) { return; }
            call = api(base, 'DELETE');
        }
        if (!call) { return; }
        call.then(function (res) {
            if (!res.ok) { window.alert(errText(res)); return; }
            if (a === 'delete') { D.sel = null; }
            loadList(a === 'delete' ? null : d.decision_id);
        });
    }
    function fromChat() {
        api('/decisions/chat-candidates').then(function (res) {
            var rows = res.ok && Array.isArray(res.j) ? res.j : [];
            var $m = modal({title: 'Promote a chat decision', subtitle: 'Decisions posted in the stream with /decision that are not in the register yet.',
                body: rows.length ? '<ul class="iris-rb-trail">' + rows.map(function (m, i) {
                    return '<li class="d-flex align-items-start" style="gap:8px;"><div style="flex:1 1 auto;">' + esc(m.content) +
                        '<div class="iris-rb-muted">' + esc(m.author) + ' &middot; ' + esc(utc(m.created_at)) + '</div></div>' +
                        '<button type="button" class="btn btn-sm btn-outline-primary" data-i="' + i + '">Register</button></li>';
                }).join('') + '</ul>' : '<div class="iris-rb-muted">' + (res.ok ? 'No unregistered decision in the stream.' : esc(errText(res))) + '</div>',
                footer: '<button type="button" class="btn btn-outline-secondary" data-dismiss="modal">Close</button>', size: ''});
            $m.on('click', '[data-i]', function () {
                var m = rows[Number($(this).attr('data-i'))];
                $m.modal('hide');
                openForm({chat: m});
            });
        });
    }
    function openForm(o) {
        Promise.all([loadMembers(), loadCases()]).then(function () {
            var d = o.decision || null, edit = !!d, proposed = !d || d.status === 'proposed';
            var cur = {assets: d ? d.assets.filter(function (a) { return !a.restricted; }).map(function (a) { return {asset_id: a.asset_id, asset_name: a.asset_name}; }) : []};
            var target = d && d.target_at ? String(d.target_at).replace(/Z$/, '').slice(0, 16) : '';
            var approverIds = d ? d.approvers.map(function (a) { return a.user_id; }) : [];
            var caseIds = d ? d.case_ids : [];
            /* the cases it applies to that this viewer can read (a restricted one cannot be chosen again) */
            cur.cases = caseIds.filter(function (x) {
                return D.cases.some(function (c2) { return c2.case_id === x && c2.accessible !== false; });
            });
            var title = o.chat ? o.chat.content.split('\n')[0].slice(0, 256) : (o.supersedes ? '' : (d ? d.title : ''));
            var body =
                (o.supersedes ? '<div class="iris-rb-muted mb-2">Supersedes <b>' + esc(o.supersedes.ref) + '</b> ' + esc(o.supersedes.title) +
                    ' once this one is approved.</div>' : '') +
                (o.chat ? '<div class="iris-rb-muted mb-2">From the /decision message of ' + esc(o.chat.author) + '.</div>' : '') +
                '<div class="form-group"><label for="rb-title">Decision <span class="text-danger">*</span></label>' +
                '<input type="text" class="form-control" id="rb-title" maxlength="256" value="' + esc(title) + '" placeholder="e.g. Keep the Lyon site offline overnight"></div>' +
                '<div class="form-group"><label for="rb-rationale">Rationale <span class="iris-rb-muted">(Markdown)</span></label>' +
                '<textarea class="form-control" id="rb-rationale" rows="4">' + esc(d ? (d.rationale || '') : (o.chat ? o.chat.content : '')) + '</textarea></div>' +
                '<div class="form-row"><div class="form-group col-md-6"><label for="rb-target">Target date &amp; time (UTC)</label>' + IrisHelp.icon('decision.target') +
                '<input type="datetime-local" class="form-control" id="rb-target" value="' + esc(target) + '"></div>' +
                (edit ? '' : '<div class="form-group col-md-6"><label for="rb-status">Status</label>' + IrisHelp.icon('decision.status') +
                    '<select class="form-control" id="rb-status"><option value="proposed" selected>Pending</option><option value="approved">Approved</option></select>' +
                    '<div class="iris-rb-muted mt-1" data-rb="status-hint"></div></div>') + '</div>' +
                '<div class="form-group"><label for="rb-owner">Owner</label><select class="form-control" id="rb-owner">' +
                D.members.map(function (m) {
                    var sel = d ? m.user_id === d.owner_id : false;
                    return '<option value="' + id(m.user_id) + '"' + (sel ? ' selected' : '') + '>' + esc(m.user_name || m.name || ('#' + m.user_id)) + '</option>';
                }).join('') + '</select></div>' +
                '<fieldset class="form-group"' + (proposed ? '' : ' disabled') + '><legend class="col-form-label pt-0" style="font-size:.88rem;">Approvers ' + IrisHelp.icon('decision.approvers') +
                (proposed ? '' : ' <span class="iris-rb-muted">(fixed once decided)</span>') + '</legend>' +
                (D.members.map(function (m) {
                    return '<div class="custom-control custom-checkbox custom-control-inline"><input type="checkbox" class="custom-control-input" id="rb-ap-' + id(m.user_id) + '" value="' + id(m.user_id) + '"' +
                        (approverIds.indexOf(m.user_id) >= 0 ? ' checked' : '') + ' data-rb="approver"><label class="custom-control-label" for="rb-ap-' + id(m.user_id) + '">' +
                        esc(m.user_name || m.name || ('#' + m.user_id)) + '</label></div>';
                }).join('') || '<div class="iris-rb-muted">No war-room members.</div>') + '</fieldset>' +
                '<fieldset class="form-group"' + (proposed ? '' : ' disabled') + '><legend class="col-form-label pt-0" style="font-size:.88rem;">Applies to ' + IrisHelp.icon('decision.applies_to') +
                ' <span class="iris-rb-muted">(nothing chosen: the whole war room)</span></legend>' +
                '<div class="iris-rb-muted mb-1">Cases</div><div data-rb="cases">' +
                (D.cases.filter(function (c2) { return c2.accessible !== false; }).map(function (c2) {
                    var on = cur.cases.indexOf(c2.case_id) >= 0;
                    return '<button type="button" class="iris-rb-pick' + (on ? ' on' : '') + '" data-rb="case" data-id="' + id(c2.case_id) + '" aria-pressed="' + (on ? 'true' : 'false') + '">' +
                        esc(c2.case_name || c2.name || ('Case #' + c2.case_id)) + '</button>';
                }).join('') || '<span class="iris-rb-muted">No case attached to this war room.</span>') + '</div>' +
                '<div class="iris-rb-muted mt-2 mb-1">Assets</div>' +
                '<label class="sr-only" for="rb-asset-q">Search assets</label><input type="text" class="form-control form-control-sm" id="rb-asset-q" placeholder="Search assets of attached cases…">' +
                '<div data-rb="asset-results" class="mt-1"></div><div data-rb="assets" class="mt-1"></div></fieldset>';
            var $m = modal({title: edit ? 'Edit ' + esc(d.ref) : (o.supersedes ? 'Supersede ' + esc(o.supersedes.ref) : o.chat ? 'Register a /decision message' : 'Propose a decision'),
                subtitle: edit ? 'Changes are recorded on the decision and visible to the whole war room.'
                    : 'Gets the next D-number and appears on the Board until it is decided and implemented.',
                body: body, footer: '<button type="button" class="btn btn-outline-secondary" data-dismiss="modal">Cancel</button>' +
                    '<button type="button" class="btn btn-primary" data-rb="save">' + (edit ? 'Save' : 'Propose') + '</button>'});
            function drawAssets() {
                $m.find('[data-rb="assets"]').html(cur.assets.length ? cur.assets.map(function (a, i) {
                    return '<span class="iris-rb-chip">' + esc(a.asset_name) + ' <button type="button" class="iris-rb-linkbtn" data-rb="unasset" data-i="' + i + '" aria-label="Remove ' + esc(a.asset_name) + '">&times;</button></span>';
                }).join('') : '');
            }
            drawAssets();
            $m.on('click', '[data-rb="case"]', function () {
                var cid = Number($(this).attr('data-id')), i = cur.cases.indexOf(cid);
                if (i >= 0) { cur.cases.splice(i, 1); } else { cur.cases.push(cid); }
                $(this).toggleClass('on', i < 0).attr('aria-pressed', i < 0 ? 'true' : 'false');
            });
            /* with approvers their votes decide: Approved is offered only without one */
            function syncStatus() {
                var $s = $m.find('#rb-status');
                if (!$s.length) { return; }
                var voters = $m.find('[data-rb="approver"]:checked').length > 0;
                if (voters) { $s.val('proposed'); }
                $s.prop('disabled', voters);
                $m.find('[data-rb="status-hint"]').text(voters ? 'With approvers, their votes decide.' : '');
            }
            $m.on('change', '[data-rb="approver"]', syncStatus);
            syncStatus();
            var st = null;
            $m.on('input', '#rb-asset-q', function () {
                var v = $(this).val();
                clearTimeout(st);
                st = setTimeout(function () {
                    api('/decisions/assets?q=' + encodeURIComponent(v)).then(function (res) {
                        var rows = res.ok && Array.isArray(res.j) ? res.j : [];
                        $m.find('[data-rb="asset-results"]').data('rows', rows).html(rows.length ? rows.map(function (a, i) {
                            return '<button type="button" class="btn btn-sm btn-outline-secondary mr-1 mb-1" data-rb="addasset" data-i="' + i + '">' + esc(a.asset_name) +
                                ' <span class="iris-rb-muted">(' + esc(a.case_name || '') + ')</span></button>';
                        }).join('') : '<span class="iris-rb-muted">' + (res.ok ? 'No asset found.' : esc(errText(res))) + '</span>');
                    });
                }, 250);
            });
            $m.on('click', '[data-rb="addasset"]', function () {
                var a = ($m.find('[data-rb="asset-results"]').data('rows') || [])[Number($(this).attr('data-i'))];
                if (a && !cur.assets.some(function (x) { return x.asset_id === a.asset_id; })) { cur.assets.push(a); drawAssets(); }
            });
            $m.on('click', '[data-rb="unasset"]', function () { cur.assets.splice(Number($(this).attr('data-i')), 1); drawAssets(); });
            $m.on('click', '[data-rb="save"]', function () {
                var p = {title: $.trim($m.find('#rb-title').val()), rationale: $m.find('#rb-rationale').val(),
                         target_at: $m.find('#rb-target').val() || null};
                var owner = Number($m.find('#rb-owner').val()) || null;
                if (!edit || owner !== d.owner_id) { p.owner_id = owner; }
                if (!p.title) { $m.find('[data-rb="err"]').text('A title is required'); return; }
                if (proposed) {
                    p.approver_ids = $m.find('[data-rb="approver"]:checked').map(function () { return Number(this.value); }).get();
                    p.case_ids = cur.cases.slice();
                    p.asset_ids = cur.assets.map(function (a) { return a.asset_id; });
                }
                if (!edit) { p.status = $m.find('#rb-status').val() === 'approved' && !p.approver_ids.length ? 'approved' : 'proposed'; }
                if (o.supersedes) { p.supersedes_id = o.supersedes.decision_id; }
                if (o.chat) { p.chat_message_id = o.chat.message_id; }
                var $b = $(this).prop('disabled', true);
                (edit ? api('/decisions/' + id(d.decision_id), 'PATCH', p) : api('/decisions', 'POST', p)).then(function (res) {
                    $b.prop('disabled', false);
                    if (!res.ok) { $m.find('[data-rb="err"]').text(errText(res)); return; }
                    $m.modal('hide');
                    loadList(res.j.decision_id);
                });
            });
            if (!d) {
                /* a new decision's owner defaults to the proposer (the server fills an empty owner_id) */
                $m.find('#rb-owner').prepend('<option value="" selected>Me (the proposer)</option>');
            } else if (d.owner_id && !D.members.some(function (m) { return m.user_id === d.owner_id; })) {
                /* an owner who left the room stays the owner until someone picks another */
                $m.find('#rb-owner').prepend($('<option selected>').val(String(d.owner_id)).text((d.owner_name || '#' + d.owner_id) + ' (not in the room)'));
            }
        });
    }

    /* ================================================================ Board */
    /* Lucide icons (ISC), the ones the Board, the Scope tab and their editors draw */
    var IC = {
        'unplug': '<path d="m19 5 3-3"/><path d="m2 22 3-3"/><path d="M6.3 20.3a2.4 2.4 0 0 0 3.4 0L12 18l-6-6-2.3 2.3a2.4 2.4 0 0 0 0 3.4Z"/><path d="M7.5 13.5 10 11"/><path d="M10.5 16.5 13 14"/><path d="m12 6 6 6 2.3-2.3a2.4 2.4 0 0 0 0-3.4l-2.6-2.6a2.4 2.4 0 0 0-3.4 0Z"/>',
        'gavel': '<path d="m14.5 12.5-8 8a2.119 2.119 0 1 1-3-3l8-8"/><path d="m16 16 6-6"/><path d="m8 8 6-6"/><path d="m9 7 8 8"/><path d="m21 11-8-8"/>',
        'shield-off': '<path d="m2 2 20 20"/><path d="M5 5a1 1 0 0 0-1 1v7c0 5 3.5 7.5 7.67 8.94a1 1 0 0 0 .67.01c2.35-.82 4.48-1.97 5.9-3.71"/><path d="M9.309 3.652A12.252 12.252 0 0 0 11.24 2.28a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1v7a9.784 9.784 0 0 1-.08 1.264"/>',
        'list-checks': '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8"/><path d="M13 12h8"/><path d="M13 18h8"/>',
        'shield-x': '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m14.5 9.5-5 5"/><path d="m9.5 9.5 5 5"/>',
        'flame': '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
        'calendar-clock': '<path d="M21 7.5V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h3.5"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h5"/><path d="M17.5 17.5 16 16.3V14"/><circle cx="16" cy="16" r="6"/>',
        'badge-alert': '<path d="M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
        'server': '<rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/>',
        'timer': '<line x1="10" x2="14" y1="2" y2="2"/><line x1="12" x2="15" y1="14" y2="11"/><circle cx="12" cy="14" r="8"/>',
        'circle-alert': '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
        'siren': '<path d="M7 18v-6a5 5 0 1 1 10 0v6"/><path d="M5 21a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-1a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2z"/><path d="M21 12h1"/><path d="M18.5 4.5 18 5"/><path d="M2 12h1"/><path d="M12 2v1"/><path d="m4.929 4.929.707.707"/><path d="M12 12v6"/>',
        'layout-dashboard': '<rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>',
        'lock': '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
        'building-2': '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/>',
        'user-round': '<circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/>',
        'activity': '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
        'arrow-right': '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
        'plus': '<path d="M5 12h14"/><path d="M12 5v14"/>',
        'grip-vertical': '<circle cx="9" cy="12" r="1"/><circle cx="9" cy="5" r="1"/><circle cx="9" cy="19" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="15" cy="5" r="1"/><circle cx="15" cy="19" r="1"/>',
        'settings-2': '<path d="M20 7h-9"/><path d="M14 17H5"/><circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/>',
        'arrow-left': '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
        'arrow-up': '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
        'arrow-down': '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
        'boxes': '<path d="M2.97 12.92A2 2 0 0 0 2 14.63v3.24a2 2 0 0 0 .97 1.71l3 1.8a2 2 0 0 0 2.06 0L12 19v-5.5l-5-3-4.03 2.42Z"/><path d="m7 16.5-4.74-2.85"/><path d="m7 16.5 5-3"/><path d="M7 16.5v5.17"/><path d="M12 13.5V19l3.97 2.38a2 2 0 0 0 2.06 0l3-1.8a2 2 0 0 0 .97-1.71v-3.24a2 2 0 0 0-.97-1.71L17 10.5l-5 3Z"/><path d="m17 16.5-5-3"/><path d="m17 16.5 4.74-2.85"/><path d="M17 16.5v5.17"/><path d="M7.97 4.42A2 2 0 0 0 7 6.13v4.37l5 3 5-3V6.13a2 2 0 0 0-.97-1.71l-3-1.8a2 2 0 0 0-2.06 0l-3 1.8Z"/><path d="M12 8 7.26 5.15"/><path d="m12 8 4.74-2.85"/><path d="M12 13.5V8"/>',
        'pencil': '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
        'sliders-horizontal': '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>',
        'refresh-cw': '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
        'x': '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
        'chevron-left': '<path d="m15 18-6-6 6-6"/>',
        'chevron-right': '<path d="m9 18 6-6-6-6"/>'
    };
    function ic(name, cls, size) {
        return '<svg xmlns="http://www.w3.org/2000/svg" width="' + (size || 16) + '" height="' + (size || 16) + '" viewBox="0 0 24 24" fill="none" ' +
            'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"' +
            (cls ? ' class="' + cls + '"' : '') + '>' + (IC[name] || IC['circle-alert']) + '</svg>';
    }
    var W = {el: null, data: null, editing: null, dirty: false, customizing: null, err: '', timer: null, at: 0, drag: null};
    var REFRESH_MS = 60000;
    var ZONES = [['tile', 'Indicators', 'Figures in a row of tiles'], ['main', 'Main column', 'Wide panels'], ['side', 'Side column', 'Narrow panels']];
    var ATT_ICON = {compromised_unflagged: 'unplug', exception_without_decision: 'shield-off', decision_overdue: 'timer',
                    decision_due_soon: 'timer', decision_pending_vote: 'gavel', vulnerability_exploited_open: 'flame',
                    vulnerability_overdue: 'calendar-clock'};
    var TASK_STATUS = {todo: 'To do', in_progress: 'In progress', on_hold: 'On hold', blocked: 'Blocked'};

    function types() { return (W.data && W.data.widget_types) || []; }
    function typeInfo(t) { return types().filter(function (x) { return x.type === t; })[0] || null; }
    function zoneOf(w) { var t = typeInfo(w.type); return t ? t.zone : 'panel'; }
    /* the editor's zone of a widget: tile, main or side */
    function slotOf(w) { return zoneOf(w) === 'tile' ? 'tile' : (w.column === 'side' ? 'side' : 'main'); }
    function labelOf(w) { var t = typeInfo(w.type); return t ? t.label : w.type; }
    function plural(n, one, many) { return Number(n) + ' ' + (Number(n) === 1 ? one : (many || one + 's')); }
    /* "#5 - Name" -> "Name": the card prints the id itself */
    function caseTitle(c) {
        var n = String(c.case_name || ''), m = n.match(/^#(\d+)\s*-\s*/);
        return m && Number(m[1]) === Number(c.case_id) ? n.slice(m[0].length) : n;
    }
    /* the clock part of a UTC ISO string, from the string (never a Date): "18:37:05 UTC" */
    function clock(iso) { var m = String(iso || '').match(/T(\d\d:\d\d:\d\d)/); return m ? m[1] + ' UTC' : ''; }
    function stamp(iso) { var m = String(iso || '').match(/^(\d{4}-\d\d-\d\d)T(\d\d:\d\d:\d\d)/); return m ? m[1] + ' ' + m[2] + ' UTC' : ''; }

    /* an in-room address (?pane=...): the anchor opens the tab in place, or a new tab on a modified click */
    function roomHref(params) {
        var q = [], cid = new URLSearchParams(window.location.search).get('cid');
        if (cid && /^\d+$/.test(cid)) { q.push('cid=' + cid); }
        Object.keys(params).forEach(function (k) { q.push(encodeURIComponent(k) + '=' + encodeURIComponent(params[k])); });
        return window.location.pathname + '?' + q.join('&');
    }
    function go(pane, params) {
        return 'href="' + esc(roomHref(Object.assign({pane: pane}, params || {}))) + '" data-wb-go="' + esc(pane) + '"';
    }
    /* the Scope tab exists for members, never for guests */
    function scopeGo(params) { return W.data && W.data.scope ? go('scope', params) : ''; }

    var LS = function () { return 'war_room_board_layout_' + id(ctx.roomId); };
    function personal() {
        try { var v = JSON.parse(window.localStorage.getItem(LS()) || 'null'); return v && typeof v === 'object' && !Array.isArray(v) ? v : null; } catch (e) { return null; }
    }
    function savePersonal(v) {
        try { if (v) { window.localStorage.setItem(LS(), JSON.stringify(v)); } else { window.localStorage.removeItem(LS()); } } catch (e) { /* per-browser convenience only */ }
    }
    /* the room's widgets in the viewer's own order and columns, minus the ones they hid (with keepHidden: all of them) */
    function arranged(widgets, mine, keepHidden) {
        var list = widgets.map(function (w) { return Object.assign({}, w); });
        if (!mine) { return list; }
        var order = Array.isArray(mine.order) ? mine.order : [], hidden = Array.isArray(mine.hidden) ? mine.hidden : [];
        var cols = mine.columns && typeof mine.columns === 'object' ? mine.columns : {};
        var byId = {};
        list.forEach(function (w) { byId[w.id] = w; });
        var out = [];
        order.forEach(function (i) { if (byId[i] && out.indexOf(byId[i]) < 0) { out.push(byId[i]); } });
        list.forEach(function (w, n) {
            if (out.indexOf(w) >= 0) { return; }
            var at = 0;
            for (var k = n - 1; k >= 0; k--) { var p = out.indexOf(list[k]); if (p >= 0) { at = p + 1; break; } }
            out.splice(at, 0, w);
        });
        out.forEach(function (w) {
            if (zoneOf(w) === 'panel' && (cols[w.id] === 'main' || cols[w.id] === 'side')) { w.column = cols[w.id]; }
        });
        return keepHidden ? out : out.filter(function (w) { return hidden.indexOf(w.id) < 0; });
    }

    B.mountBoard = function (el, c) {
        css();
        ctx = c;
        W.el = el;
        var $el = $(el);
        $el.on('click', '[data-wb]', function (e) {
            /* the "Add" menu items are <a href="#">: never follow them */
            e.preventDefault();
            boardAction($(this).attr('data-wb'), $(this));
        });
        $el.on('click', 'a[data-wb-go]', function (e) {
            if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) { return; }   /* a new tab follows the address */
            e.preventDefault();
            var u = new URL(this.getAttribute('href'), window.location.href), q = {};
            u.searchParams.forEach(function (v, k) { if (k !== 'pane' && k !== 'cid') { q[k] = v; } });
            var pane = u.searchParams.get('pane');
            ctx.openPane(pane, {decisionId: /^\d+$/.test(q.d || '') ? Number(q.d) : null, status: q.status || null,
                                scope: pane === 'scope' ? q : null});
        });
        $el.on('change', '[data-wb-show]', function () {
            var C = W.customizing, wid = $(this).attr('data-wb-show'), k = C.hidden.indexOf(wid);
            if (this.checked && k >= 0) { C.hidden.splice(k, 1); }
            if (!this.checked && k < 0) { C.hidden.push(wid); }
            drawBoard();
        });
        $el.on('dragstart', '[data-wb-row]', function (e) {
            W.drag = $(this).attr('data-wb-row');
            var dt = e.originalEvent && e.originalEvent.dataTransfer;
            if (dt) { try { dt.setData('text/plain', W.drag); dt.effectAllowed = 'move'; } catch (x) { /* some browsers refuse */ } }
            $(this).addClass('iris-rb-dragging');
        });
        $el.on('dragend', '[data-wb-row]', function () { W.drag = null; $(W.el).find('.iris-rb-dragging, .iris-rb-dropzone').removeClass('iris-rb-dragging iris-rb-dropzone'); });
        $el.on('dragover', '[data-wb-zone]', function (e) {
            var w = dragged();
            if (!w || !fits(w, $(this).attr('data-wb-zone'))) { return; }
            e.preventDefault();
            $(this).addClass('iris-rb-dropzone');
        });
        $el.on('dragleave', '[data-wb-zone]', function () { $(this).removeClass('iris-rb-dropzone'); });
        $el.on('drop', '[data-wb-zone]', function (e) {
            var w = dragged(), zone = $(this).attr('data-wb-zone');
            if (!w || !fits(w, zone)) { return; }
            e.preventDefault();
            var target = $(e.target).closest('[data-wb-row]').attr('data-wb-row') || null;
            moveTo(w, zone, target === w.id ? null : target);
            W.drag = null;
            drawBoard();
        });
        if (!W.timer) {
            W.timer = window.setInterval(B.tick, REFRESH_MS);
        }
        loadBoard();
    };
    /* the minute refresh: only while the Board shows, the page is visible and nobody edits */
    B.tick = function () {
        if (!W.el || W.editing || W.customizing || document.hidden || !W.el.offsetParent || $('.modal.show').length) { return false; }
        loadBoard();
        return true;
    };
    /* war_room.js: the Board tab was shown again - refresh a board older than a minute */
    B.boardShown = function () {
        if (W.el && W.data && Date.now() - W.at >= REFRESH_MS) { B.tick(); }
    };
    function loadBoard() {
        return api('/board').then(function (res) {
            if (!res.ok) {
                if (!W.data) { $(W.el).html('<div class="text-danger p-3" role="alert">The board could not be loaded: ' + esc(errText(res)) + '</div>'); }
                else { W.err = 'The board could not be refreshed: ' + errText(res); drawBoard(); }
                return;
            }
            W.data = res.j;
            W.at = Date.now();
            if (!W.editing && !W.customizing) { W.err = ''; }
            drawBoard();
        });
    }
    function btn(a, icon, label, cls, extra) {
        return '<button type="button" class="btn btn-sm ' + (cls || 'btn-outline-secondary') + ' iris-rb-btn" data-wb="' + a + '"' + (extra || '') + '>' +
            ic(icon, '', 14) + '<span>' + label + '</span></button>';
    }
    function drawBoard() {
        var b = W.data, d = b.data, editing = W.editing, cust = W.customizing;
        var list = editing ? editing : (cust ? cust.all.filter(function (w) { return cust.hidden.indexOf(w.id) < 0; }) : arranged(b.widgets, personal()));
        var sub = plural(d.cases_total, 'case') + (d.cases_total !== d.case_count ? ' (' + Number(d.case_count) + ' visible to you)' : '') +
            ' &middot; updated ' + esc(clock(b.generated_at)) + ' &middot; refreshes every minute';
        var head = '<div class="iris-rb-head"><div class="iris-rb-min0"><div class="d-flex align-items-center" style="gap:6px;"><h2 class="iris-rb-h1">Board</h2>' +
            IrisHelp.icon('room.board') + '</div><div class="iris-rb-muted" data-wb-sub>' + sub + '</div></div><div class="iris-rb-head-btns">';
        if (!editing && !cust) {
            head += (b.can_edit ? btn('edit', 'pencil', 'Edit board', '', ' title="Set the widgets of this war room\'s board, for everyone"') : '') +
                btn('customize', 'sliders-horizontal', 'Customize', '', ' title="Hide, reorder or move widgets, only for you"') +
                btn('refresh', 'refresh-cw', 'Refresh');
        }
        head += '</div></div>' + (W.err ? '<div class="text-danger small mb-2" role="alert">' + esc(W.err) + '</div>' : '');
        var panel = editing ? editorHtml() : (cust ? customizeHtml() : '');
        var tiles = '', cols = {main: '', side: ''};
        list.forEach(function (w) {
            if (zoneOf(w) === 'tile') { tiles += tileHtml(w); } else { cols[w.column === 'side' ? 'side' : 'main'] += panelHtml(w); }
        });
        var body = (tiles ? '<div class="iris-rb-tz" data-wb-tiles>' + tiles + '</div>' : '') +
            '<div class="iris-rb-cols' + (!cols.main || !cols.side ? ' iris-rb-cols-one' : '') + '">' +
            (cols.main ? '<div class="iris-rb-col" data-col="main">' + cols.main + '</div>' : '') +
            (cols.side ? '<div class="iris-rb-col" data-col="side">' + cols.side + '</div>' : '') + '</div>' +
            (!list.length ? '<div class="iris-rb-muted p-3">Nothing on this board.</div>' : '');
        $(W.el).html(head + panel + body);
    }

    /* ---------------------------------------------------------------- tiles */
    function kpi(w, o) {
        var label = w.title || o.label;
        var inner = '<div class="iris-rb-kpi-top"><span class="iris-rb-kpi-label" title="' + esc(label) + '">' + esc(label) + '</span>' + ic(o.icon, 'iris-rb-kpi-ic') + '</div>' +
            '<div class="iris-rb-kpi-n' + (o.tone ? ' iris-rb-t-' + o.tone : '') + '">' + esc(o.value) + '</div>' +
            '<div class="iris-rb-kpi-sub"><span title="' + esc(o.sub) + '">' + esc(o.sub) + '</span>' + (o.go ? ic('arrow-right', 'iris-rb-kpi-go', 12) : '') + '</div>';
        var cls = 'iris-rb-kpi' + (o.danger ? ' iris-rb-kpi-danger' : '');
        var attrs = ' data-widget="' + esc(w.id) + '" data-type="' + esc(w.type) + '" aria-label="' + esc(label + ': ' + o.value + '. ' + o.sub + (o.go ? '. Open' : '')) + '"';
        return o.go ? '<a class="' + cls + '" ' + o.go + attrs + '>' + inner + '</a>' : '<div class="' + cls + '" role="group"' + attrs + '>' + inner + '</div>';
    }
    function segments(byFlag, none, total) {
        var out = [];
        (byFlag || []).forEach(function (f) {
            if (f.assets > 0) { out.push({key: String(f.flag_id), label: f.name, color: f.color, count: f.assets}); }
        });
        if (none > 0) { out.push({key: 'none', label: 'No flag', color: null, count: none}); }
        out.forEach(function (s) { s.pct = total > 0 ? Math.min(100, 100 * s.count / total) : 0; });
        return out;
    }
    function dot(s, size) {
        var c = s.color && window.IrisFlags ? window.IrisFlags.color(s.color) : 'rgba(154,154,165,.45)';
        return '<span class="iris-rb-dot" style="background:' + c + ';' + (size ? 'width:' + size + 'px;height:' + size + 'px;' : '') + '" aria-hidden="true"></span>';
    }
    function legend(segs, links) {
        if (!segs.length) { return ''; }
        return '<ul class="iris-rb-legend" data-wb-legend>' + segs.map(function (s) {
            var g = links ? scopeGo({flag: s.key}) : '';
            var inner = dot(s) + '<span>' + esc(s.label) + '</span> <b>' + Number(s.count) + '</b>';
            var tip = ' title="' + esc(s.label + ': ' + s.count + ' (' + Math.round(s.pct) + '% of the assets)') + '"';
            return '<li>' + (g ? '<a ' + g + tip + '>' + inner + '</a>' : '<span' + tip + '>' + inner + '</span>') + '</li>';
        }).join('') + '</ul>';
    }
    function bar(done, total, thin) {
        var pct = total > 0 ? Math.round(100 * done / total) : 0;
        return '<div class="iris-rb-bar' + (thin ? ' iris-rb-bar-thin' : '') + '" role="img" aria-label="' + (total > 0 ? Number(done) + ' of ' + Number(total) + ' assets done' : 'No assets') +
            '"><i style="width:' + pct + '%;"></i></div>';
    }
    function tileHtml(w) {
        var d = W.data.data, k = d.kpis, v = d.vulnerabilities;
        switch (w.type) {
        case 'kpi_compromised':
            return kpi(w, {label: 'Compromised', value: k.compromised, icon: 'unplug', tone: k.compromised > 0 ? 'red' : '',
                           sub: plural(k.unflagged, 'asset') + ' without a flag', go: scopeGo({compromised: 1})});
        case 'kpi_decisions':
            return kpi(w, {label: 'Open decisions', value: k.decisions_open, icon: 'gavel',
                           tone: k.decisions_overdue > 0 ? 'red' : (k.decisions_open > 0 ? 'amber' : ''),
                           sub: (k.decisions_overdue > 0 ? Number(k.decisions_overdue) + ' overdue \u00b7 ' : '') + Number(k.decisions_due_24h) + ' due in 24 h',
                           go: go('decisions', {status: 'open'})});
        case 'kpi_exceptions':
            return kpi(w, {label: 'Exceptions', value: k.exceptions, icon: 'shield-off', tone: k.exceptions > 0 ? 'amber' : '',
                           sub: k.exceptions > 0 ? 'Assets with an exception flag' : 'None', go: scopeGo({kind: 'exception'})});
        case 'kpi_tasks':
            return kpi(w, {label: 'Open tasks', value: k.tasks_open, icon: 'list-checks', tone: k.tasks_overdue > 0 ? 'amber' : '',
                           sub: Number(k.tasks_in_progress) + ' in progress' + (k.tasks_overdue > 0 ? ' \u00b7 ' + Number(k.tasks_overdue) + ' overdue' : ''),
                           go: go('tasks')});
        case 'flags':
            var f = d.flags, pct = f.assets > 0 ? Math.round(100 * f.done / f.assets) : 0, sg = scopeGo({});
            return '<div class="iris-rb-kpi iris-rb-kpi-wide" role="group" data-widget="' + esc(w.id) + '" data-type="flags" aria-label="' + esc((w.title || 'Flags') + ': ' + pct + '% done') + '">' +
                '<div class="iris-rb-kpi-top"><span class="iris-rb-kpi-label">' + esc(w.title || 'Flags') + ' &middot; ' + plural(f.assets, 'asset') + '</span>' +
                (sg ? '<a class="iris-rb-plink" ' + sg + '>Scope ' + ic('arrow-right', '', 12) + '</a>' : '') + '</div>' +
                '<div class="iris-rb-kpi-pct"><span class="iris-rb-kpi-n">' + pct + '%</span> <span class="iris-rb-muted">done</span></div>' +
                bar(f.done, f.assets) + legend(segments(f.by_flag, f.none, f.assets), true) + '</div>';
        case 'vuln_open':
            return kpi(w, {label: 'Open vulnerabilities', value: v.open, icon: 'shield-x', tone: v.open > 0 ? 'amber' : '',
                           sub: 'Open findings on case assets', go: scopeGo({vulnerable: 'open'})});
        case 'vuln_exploited':
            return kpi(w, {label: 'Exploited & open', value: v.exploited_open, icon: 'flame', tone: v.exploited_open > 0 ? 'red' : '',
                           danger: v.exploited_open > 0, go: scopeGo({vulnerable: 'exploited'}),
                           sub: v.exploited_open > 0 ? 'Exploited and not fixed yet' : 'No exploited finding left open'});
        case 'vuln_overdue':
            return kpi(w, {label: 'Overdue', value: v.overdue, icon: 'calendar-clock', tone: v.overdue > 0 ? 'amber' : '',
                           sub: 'Open findings past their due date', go: scopeGo({vulnerable: 'overdue'})});
        case 'vuln_kev':
            return kpi(w, {label: 'KEV open', value: v.kev_open, icon: 'badge-alert', tone: v.kev_open > 0 ? 'red' : '',
                           sub: 'Open findings listed in CISA KEV', go: scopeGo({vulnerable: 'kev'})});
        case 'vuln_assets':
            return kpi(w, {label: 'Vulnerable assets', value: v.vulnerable_assets, icon: 'server', tone: '',
                           sub: 'Assets with an open finding', go: scopeGo({vulnerable: 'open'})});
        }
        return '';
    }

    /* ---------------------------------------------------------------- panels */
    function panelHtml(w) {
        var d = W.data.data, o = w.options || {}, p = {icon: 'circle-alert', title: labelOf(w), count: null, tone: '', link: '', body: '', foot: ''};
        if (w.type === 'cases') {
            var main = w.column !== 'side';
            p.icon = 'layout-dashboard';
            p.title = 'Cases';
            p.count = d.cases.length;
            p.link = d.cases.some(function (c) { return c.accessible; }) ? '<span class="iris-rb-muted iris-rb-ml">Assets by flag</span>' : '';
            p.body = d.cases.length ? '<div class="iris-rb-cases' + (main ? ' iris-rb-cases-wide' : '') + '">' + d.cases.map(caseCard).join('') + '</div>'
                : '<p class="iris-rb-empty-line">No case attached to this war room yet.</p>';
        } else if (w.type === 'decisions') {
            p.icon = 'gavel';
            p.title = 'Open decisions';
            p.count = d.decisions.length;
            p.tone = d.decisions.length ? 'amber' : '';
            p.link = '<a class="iris-rb-plink iris-rb-ml" ' + go('decisions', {status: 'open'}) + '>All decisions ' + ic('arrow-right', '', 12) + '</a>';
            p.body = d.decisions.length ? '<ul class="iris-rb-rows">' + d.decisions.map(function (x) {
                var when = x.target_at ? '<span class="iris-rb-when' + (x.is_overdue ? ' iris-rb-t-red' : (x.due_soon ? ' iris-rb-t-amber' : '')) + '" title="' + esc(utc(x.target_at)) + '">' +
                    ic('timer', '', 12) + esc(utc(x.target_at)) + '</span>' : '<span class="iris-rb-muted">No target date</span>';
                return '<li><a class="iris-rb-row" ' + go('decisions', {d: x.decision_id}) + '><span class="iris-rb-min0 iris-rb-grow"><span class="d-block text-truncate">' +
                    '<span class="iris-rb-ref">' + esc(x.ref) + '</span>' + esc(x.title) + '</span><span class="iris-rb-meta">' + when +
                    (x.status === 'proposed' && x.pending_approvers > 0 ? ' &middot; ' + plural(x.pending_approvers, 'vote') + ' pending' : '') +
                    (x.awaiting_me ? ' &middot; <b class="iris-rb-t-amber">awaits your vote</b>' : '') + '</span></span>' + statusBadge(x.status) + '</a></li>';
            }).join('') + '</ul>' : '<p class="iris-rb-empty-line">No open decision.</p>';
        } else if (w.type === 'attention') {
            var att = d.attention, high = att.some(function (a) { return a.severity === 'high'; });
            p.icon = 'siren';
            p.title = 'Needs attention';
            p.count = d.attention_total;
            p.tone = d.attention_total ? (high ? 'red' : 'amber') : '';
            p.body = att.length ? '<ul class="iris-rb-rows">' + att.map(function (a) {
                var act = '';
                if (a.link && a.link.href) {
                    act = '<a class="btn btn-xs btn-outline-secondary iris-rb-act" href="' + esc(a.link.href) + '">' + esc(a.action || 'Open') + '</a>';
                } else if (a.link && a.link.pane) {
                    act = '<a class="btn btn-xs btn-outline-secondary iris-rb-act" ' + go(a.link.pane, a.link.decision_id ? {d: a.link.decision_id} : {}) + '>' + esc(a.action || 'Open') + '</a>';
                }
                return '<li class="iris-rb-att-i" data-type="' + esc(a.type) + '"><span class="iris-rb-sev iris-rb-sev-' + esc(a.severity) + '" role="img" aria-label="' + esc(a.severity) + ' priority"></span>' +
                    '<span class="iris-rb-min0 iris-rb-grow"><span class="d-flex align-items-start" style="gap:6px;">' + ic(ATT_ICON[a.type] || 'circle-alert', 'iris-rb-att-ic', 14) +
                    '<span>' + esc(a.label) + '</span></span>' + (a.case_id != null ? '<span class="iris-rb-meta">Case #' + Number(a.case_id) + '</span>' : '') + '</span>' + act + '</li>';
            }).join('') + '</ul>' : '<p class="iris-rb-empty-line">Nothing needs attention.</p>';
            p.foot = 'Computed ' + esc(stamp(W.data.generated_at)) + (d.attention_total > att.length ? ' &middot; ' + Number(d.attention_total - att.length) + ' more not shown' : '');
        } else if (w.type === 'tasks') {
            var teams = o.team_ids || [];
            var rows = d.tasks.filter(function (t) {
                if (o.in_progress_only && t.status !== 'in_progress') { return false; }
                return !teams.length || t.team_ids.some(function (x) { return teams.indexOf(x) >= 0; });
            });
            var shown = rows.slice(0, 8);
            p.icon = 'activity';
            p.title = o.in_progress_only ? 'Actions in progress' : 'Open tasks';
            p.count = rows.length;
            p.tone = rows.length ? 'blue' : '';
            p.link = '<a class="iris-rb-plink iris-rb-ml" ' + go('tasks') + '>All tasks ' + ic('arrow-right', '', 12) + '</a>';
            p.body = rows.length ? '<ul class="iris-rb-rows">' + shown.map(function (t) {
                return '<li><a class="iris-rb-row" ' + go('tasks') + '><span class="iris-rb-dot iris-rb-st-' + esc(t.status) + '" aria-hidden="true"></span><span class="iris-rb-min0 iris-rb-grow">' +
                    '<span class="d-block text-truncate">' + esc(t.title) + '</span><span class="iris-rb-meta">' + (t.assignee ? esc(t.assignee) : 'Unassigned') +
                    (t.due_date ? ' &middot; <span class="' + (t.overdue ? 'iris-rb-t-red' : '') + '">due ' + esc(utc(t.due_date)) + '</span>' : '') + '</span></span>' +
                    '<span class="iris-rb-pill iris-rb-pill-' + esc(t.status) + '">' + esc(TASK_STATUS[t.status] || t.status.replace(/_/g, ' ')) + '</span></a></li>';
            }).join('') + '</ul>' + (rows.length > shown.length ? '<a class="iris-rb-more" ' + go('tasks') + '>' + Number(rows.length - shown.length) + ' more</a>' : '')
                : '<p class="iris-rb-empty-line">' + (o.in_progress_only ? 'No task in progress.' : 'No open task.') + '</p>';
        } else if (w.type === 'note') {
            var html = (W.data.notes || {})[w.id];
            p.icon = 'pencil';
            p.title = 'Note';
            p.body = html ? '<div class="iris-rb-note">' + html + '</div>' : '<p class="iris-rb-empty-line">Empty note.</p>';
        }
        var title = w.title || p.title;
        return '<section class="iris-rb-w" aria-label="' + esc(title) + '" data-widget="' + esc(w.id) + '" data-type="' + esc(w.type) + '">' +
            '<div class="iris-rb-ph">' + ic(p.icon, 'iris-rb-ph-ic') + '<h3>' + esc(title) + '</h3>' +
            (p.count != null ? '<span class="iris-rb-count' + (p.tone ? ' iris-rb-c-' + p.tone : '') + '">' + Number(p.count) + '</span>' : '') + p.link + '</div>' +
            '<div class="iris-rb-pb">' + p.body + '</div>' + (p.foot ? '<div class="iris-rb-pf">' + p.foot + '</div>' : '') + '</section>';
    }
    function caseCard(c) {
        if (!c.accessible) {
            return '<article class="iris-rb-case iris-rb-case-locked" data-case="' + Number(c.case_id) + '">' + ic('lock', '', 14) +
                '<span class="iris-rb-mono">#' + Number(c.case_id) + '</span><span class="text-truncate">' + esc(caseTitle(c)) + '</span>' +
                '<span class="iris-rb-muted iris-rb-ml">Restricted &mdash; you don\'t have access</span></article>';
        }
        var segs = segments((W.data.data.flags.by_flag || []).map(function (f) {
            return {flag_id: f.flag_id, name: f.name, color: f.color, assets: (c.by_flag || {})[String(f.flag_id)] || 0};
        }), (c.by_flag || {}).none || 0, c.assets_total);
        var title = '<span class="iris-rb-mono">#' + Number(c.case_id) + '</span> ' + esc(caseTitle(c));
        var meta = [c.customer_name ? ic('building-2', '', 12) + esc(c.customer_name) : '', c.owner_name ? ic('user-round', '', 12) + esc(c.owner_name) : '']
            .filter(Boolean).join(' &middot; ');
        return '<article class="iris-rb-case" data-case="' + Number(c.case_id) + '"><div class="iris-rb-case-h"><div class="iris-rb-min0 iris-rb-grow">' +
            (c.href ? '<a class="iris-rb-case-t" href="' + esc(c.href) + '">' + title + '</a>' : '<span class="iris-rb-case-t">' + title + '</span>') +
            (meta ? '<div class="iris-rb-meta">' + meta + '</div>' : '') + '</div><div class="text-right">' +
            (c.state_name ? '<span class="iris-rb-pill ' + (c.closed || /^closed$/i.test(c.state_name) ? 'iris-rb-pill-closed' : 'iris-rb-pill-open') + '">' + esc(c.state_name) + '</span>' : '') +
            (c.severity_name ? '<div class="iris-rb-meta">' + esc(c.severity_name) + '</div>' : '') + '</div></div>' +
            bar(c.done, c.assets_total, true) +
            '<div class="iris-rb-case-n"><span>' + Number(c.done) + '/' + Number(c.assets_total) + ' done</span><span class="' + (c.assets_compromised ? 'iris-rb-t-red' : '') + '">' +
            Number(c.assets_compromised) + ' compromised</span></div>' +
            '<div class="iris-rb-case-i">' +
            (c.assets_href ? '<a href="' + esc(c.assets_href) + '" title="Assets">' + ic('server', '', 12) + Number(c.assets_total) + '</a>' : '<span title="Assets">' + ic('server', '', 12) + Number(c.assets_total) + '</span>') +
            '<span title="Open case tasks">' + ic('list-checks', '', 12) + Number(c.tasks_open) + ' open</span>' +
            (c.tasks_in_progress > 0 ? '<span class="iris-rb-t-blue" title="Tasks in progress">' + ic('activity', '', 12) + Number(c.tasks_in_progress) + ' in progress</span>' : '') +
            (c.exceptions > 0 ? '<span class="iris-rb-t-amber" title="Assets with an exception flag">' + ic('shield-off', '', 12) + Number(c.exceptions) + '</span>' : '') +
            (c.vulnerabilities_open > 0 ? '<span class="' + (c.vulnerabilities_exploited_open ? 'iris-rb-t-red' : '') + '" title="Open findings' +
                (c.vulnerabilities_exploited_open ? ', ' + Number(c.vulnerabilities_exploited_open) + ' exploited' : '') + '">' + ic('shield-x', '', 12) + Number(c.vulnerabilities_open) + '</span>' : '') +
            '</div>' + legend(segs, false) + '</article>';
    }

    /* ---------------------------------------------------------------- Edit board (a lead, for everyone) */
    function zoneWidgets(list, slot) { return list.filter(function (w) { return slotOf(w) === slot; }); }
    function fits(w, slot) { return slot === 'tile' ? zoneOf(w) === 'tile' : zoneOf(w) === 'panel'; }
    function dragged() {
        var list = W.editing || (W.customizing && W.customizing.all);
        return list && W.drag ? list.filter(function (w) { return w.id === W.drag; })[0] || null : null;
    }
    /* move a widget into a zone, before `beforeId` (or at the end of the zone) */
    function moveTo(w, slot, beforeId) {
        var L = W.editing || W.customizing.all;
        L.splice(L.indexOf(w), 1);
        if (slot !== 'tile') {
            w.column = slot;
            if (W.customizing) { W.customizing.columns[w.id] = slot; }
        }
        var at = -1;
        if (beforeId) { L.forEach(function (x, i) { if (x.id === beforeId) { at = i; } }); }
        if (at < 0) {
            L.forEach(function (x, i) { if (slotOf(x) === slot) { at = i + 1; } });
            if (at < 0) { at = L.length; }
        }
        L.splice(at, 0, w);
        if (W.editing) { W.dirty = true; }
    }
    /* swap a widget with its neighbour in the same zone */
    function step(L, w, dir) {
        var same = zoneWidgets(L, slotOf(w)), k = same.indexOf(w), other = same[k + dir];
        if (!other) { return; }
        var a = L.indexOf(w), b = L.indexOf(other);
        L[a] = other;
        L[b] = w;
    }
    function rowHtml(w, slot, n, k, mode) {
        var t = typeInfo(w.type), name = w.title || labelOf(w), horiz = slot === 'tile';
        var b = function (a, icon, label, dis) {
            return '<button type="button" class="iris-rb-ibtn" data-wb="' + a + '" data-id="' + esc(w.id) + '" aria-label="' + esc(label) + '" title="' + esc(label) + '"' + (dis ? ' disabled' : '') + '>' + ic(icon, '', 14) + '</button>';
        };
        var other = slot === 'main' ? 'side' : 'main';
        if (mode === 'cust') {
            var shown = W.customizing.hidden.indexOf(w.id) < 0;
            return '<div class="iris-rb-ed-row' + (shown ? '' : ' iris-rb-off') + '" data-wb-row="' + esc(w.id) + '">' +
                '<input type="checkbox" id="board-customize-' + esc(w.id) + '" data-wb-show="' + esc(w.id) + '"' + (shown ? ' checked' : '') + ' aria-label="Show ' + esc(name) + '">' +
                '<label class="iris-rb-min0 iris-rb-grow mb-0" for="board-customize-' + esc(w.id) + '"><span class="d-block text-truncate iris-rb-ed-t">' + esc(name) + '</span>' +
                '<span class="d-block text-truncate iris-rb-meta">' + esc(t ? t.description : '') + '</span></label>' +
                (slot !== 'tile' ? b('mine-col', slot === 'main' ? 'arrow-right' : 'arrow-left', 'Move ' + name + ' to the ' + other + ' column') : '') +
                b('mine-up', horiz ? 'arrow-left' : 'arrow-up', 'Move ' + name + (horiz ? ' left' : ' up'), k === 0) +
                b('mine-down', horiz ? 'arrow-right' : 'arrow-down', 'Move ' + name + (horiz ? ' right' : ' down'), k === n - 1) + '</div>';
        }
        return '<div class="iris-rb-ed-row" draggable="true" data-wb-row="' + esc(w.id) + '">' + ic('grip-vertical', 'iris-rb-grip', 14) +
            '<span class="iris-rb-min0 iris-rb-grow"><span class="d-block text-truncate iris-rb-ed-t">' + esc(name) +
            (w.title ? ' <span class="iris-rb-meta">(' + esc(labelOf(w)) + ')</span>' : '') + '</span>' +
            '<span class="d-block text-truncate iris-rb-meta">' + esc(t ? t.description : '') + '</span></span>' +
            b('setup', 'settings-2', 'Set up ' + name) +
            (slot !== 'tile' ? b('col', slot === 'main' ? 'arrow-right' : 'arrow-left', 'Move ' + name + ' to the ' + other + ' column') : '') +
            b('up', horiz ? 'arrow-left' : 'arrow-up', 'Move ' + name + (horiz ? ' left' : ' up'), k === 0) +
            b('down', horiz ? 'arrow-right' : 'arrow-down', 'Move ' + name + (horiz ? ' right' : ' down'), k === n - 1) +
            b('remove', 'x', 'Remove ' + name) + '</div>';
    }
    function zoneHtml(L, z, mode) {
        var rows = zoneWidgets(L, z[0]), full = W.editing && W.editing.length >= 40;
        var add = '';
        if (mode === 'edit') {
            var offer = types().filter(function (t) { return z[0] === 'tile' ? t.zone === 'tile' : t.zone === 'panel'; });
            add = '<div class="dropdown"><button type="button" class="iris-rb-add" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false"' +
                (full ? ' disabled title="At most 40 widgets"' : '') + '>' + ic('plus', '', 14) + ' Add ' + (z[0] === 'tile' ? 'an indicator' : 'a widget') + '</button>' +
                '<div class="dropdown-menu">' + offer.map(function (t) {
                    return '<a href="#" class="dropdown-item" data-wb="add" data-type="' + esc(t.type) + '" data-zone="' + z[0] + '"><b>' + esc(t.label) + '</b><div class="iris-rb-meta">' + esc(t.description) + '</div></a>';
                }).join('') + '</div></div>';
        }
        return '<section class="iris-rb-zone iris-rb-zone-' + z[0] + '" aria-label="' + esc(z[1]) + '" data-wb-zone="' + z[0] + '"><div class="iris-rb-zone-h"><b>' + esc(z[1]) +
            '</b> <span class="iris-rb-meta">' + esc(z[2]) + '</span></div><div class="iris-rb-zone-rows">' +
            (rows.length ? rows.map(function (w, k) { return rowHtml(w, z[0], rows.length, k, mode); }).join('') : '<div class="iris-rb-zone-empty">Empty</div>') +
            '</div>' + add + '</section>';
    }
    function editorHtml() {
        return '<div class="iris-rb-ed" role="region" aria-label="Edit the board"><div class="iris-rb-ed-h"><b>Edit the board</b>' +
            '<span class="iris-rb-muted">' + (W.data.is_default ? 'This war room shows the default board.' : 'Set by a lead.') + ' Your changes apply to everyone in this war room.</span>' +
            '<span class="iris-rb-ml"></span>' + (W.dirty ? '<span class="iris-rb-t-amber" data-wb-dirty>&middot; unsaved changes</span>' : '') +
            '<button type="button" class="btn btn-sm btn-outline-danger" data-wb="reset">Reset to the default board</button>' +
            '<button type="button" class="btn btn-sm btn-outline-secondary" data-wb="cancel">Cancel</button>' +
            '<button type="button" class="btn btn-sm btn-primary" data-wb="save">Save</button></div>' +
            '<div class="iris-rb-ed-z">' + ZONES.map(function (z) { return zoneHtml(W.editing, z, 'edit'); }).join('') + '</div>' +
            '<div class="iris-rb-meta px-3 pb-2">Drag a widget to move it, or use its arrows. The board below previews your changes.</div></div>';
    }
    function customizeHtml() {
        return '<div class="iris-rb-ed iris-rb-cust" role="region" aria-label="Customize the board"><div class="iris-rb-ed-h"><b>Customize the board</b>' +
            '<span class="iris-rb-muted">Only for you, in this war room. The widgets are the room\'s.</span><span class="iris-rb-ml"></span>' +
            '<button type="button" class="btn btn-sm btn-outline-secondary" data-wb="mine-reset">Back to the room\'s layout</button>' +
            '<button type="button" class="btn btn-sm btn-primary" data-wb="mine-done">Done</button></div>' +
            '<div class="iris-rb-ed-z iris-rb-cust-z">' + ZONES.map(function (z) { return zoneHtml(W.customizing.all, z, 'cust'); }).join('') + '</div></div>';
    }
    function newId(type) {
        var base = type.replace(/_/g, '-'), n = 1;
        while (W.editing.some(function (w) { return w.id === base + '-' + n; })) { n++; }
        return base + '-' + n;
    }
    function setup(w) {
        var t = typeInfo(w.type), o = w.options || {}, teams = W.data.data.teams || [], panelZone = zoneOf(w) === 'panel';
        var body = '<div class="form-group"><label for="wb-title">Title <span class="iris-rb-muted">(optional)</span></label>' +
            '<input type="text" class="form-control form-control-sm" id="wb-title" maxlength="80" placeholder="' + esc(t ? t.label : '') + '" value="' + esc(w.title || '') + '"></div>' +
            (panelZone ? '<fieldset class="form-group"><legend class="iris-rb-sec mt-0">Column</legend>' +
                '<label class="mr-3"><input type="radio" name="wb-col" value="main"' + (w.column !== 'side' ? ' checked' : '') + '> Main <span class="iris-rb-muted">wide</span></label>' +
                '<label><input type="radio" name="wb-col" value="side"' + (w.column === 'side' ? ' checked' : '') + '> Side <span class="iris-rb-muted">narrow</span></label></fieldset>' : '') +
            (w.type === 'tasks' ? '<div class="form-group"><label class="mb-0"><input type="checkbox" id="wb-inprog"' + (o.in_progress_only ? ' checked' : '') + '> In progress only</label>' +
                '<div class="iris-rb-muted">Leave out the open tasks not started yet.</div></div>' +
                '<div class="form-group"><div class="iris-rb-sec mt-0">Teams</div>' + (teams.length ? '<div>' + teams.map(function (tm) {
                    var on = (o.team_ids || []).indexOf(tm.id) >= 0;
                    return '<button type="button" class="iris-rb-pick' + (on ? ' on' : '') + '" data-wb-team="' + id(tm.id) + '" aria-pressed="' + (on ? 'true' : 'false') + '">@' + esc(tm.name) + '</button>';
                }).join('') + '</div><div class="iris-rb-muted">The tasks of these teams &mdash; every task when none is picked.</div>' : '<div class="iris-rb-muted">The war room has no team.</div>') + '</div>' : '') +
            (w.type === 'note' ? '<div class="form-group"><label for="wb-note">Text (Markdown)</label><textarea class="form-control form-control-sm" id="wb-note" rows="8" maxlength="10000">' + esc(o.text || '') + '</textarea></div>' : '');
        var $m = modal({title: 'Set up ' + esc(w.title || labelOf(w)), subtitle: esc(t ? t.description : ''), size: '', body: body,
                        footer: '<button type="button" class="btn btn-outline-secondary" data-dismiss="modal">Cancel</button><button type="button" class="btn btn-primary" data-wb-apply>Apply</button>'});
        /* Bootstrap 4 ignores a hide while the dialog is still opening (lesson 285): a quick Apply waits for it */
        var shown = false;
        $m.one('shown.bs.modal', function () { shown = true; });
        var close = function () {
            if (shown) { $m.modal('hide'); } else { $m.one('shown.bs.modal', function () { $m.modal('hide'); }); }
        };
        $m.on('click', '[data-wb-team]', function () {
            var on = !$(this).hasClass('on');
            $(this).toggleClass('on', on).attr('aria-pressed', on ? 'true' : 'false');
        });
        $m.on('click', '[data-wb-apply]', function () {
            w.title = $.trim($m.find('#wb-title').val()) || null;
            if (panelZone) { w.column = $m.find('input[name="wb-col"]:checked').val() === 'side' ? 'side' : 'main'; }
            w.options = w.options || {};
            if (w.type === 'tasks') {
                w.options.in_progress_only = $m.find('#wb-inprog').is(':checked');
                w.options.team_ids = $m.find('[data-wb-team].on').map(function () { return Number($(this).attr('data-wb-team')); }).get();
            }
            if (w.type === 'note') { w.options.text = $m.find('#wb-note').val(); }
            W.dirty = true;
            close();
            drawBoard();
        });
        return $m;
    }
    B._setup = setup;
    function find(L, wid) { return L.filter(function (w) { return w.id === wid; })[0] || null; }
    function boardAction(a, $t) {
        var wid = $t.attr('data-id');
        if (a === 'refresh') { W.err = ''; loadBoard(); return; }
        if (a === 'edit') {
            W.editing = JSON.parse(JSON.stringify(W.data.widgets));
            W.editing.forEach(function (w) { w.options = w.options || {}; });
            W.dirty = false;
            W.err = '';
            drawBoard();
            return;
        }
        if (W.editing) {
            var L = W.editing, w = wid ? find(L, wid) : null;
            if (a === 'cancel') {
                if (W.dirty && !window.confirm('Drop your changes to the board?')) { return; }
                W.editing = null;
                W.dirty = false;
                W.err = '';
                drawBoard();
                return;
            }
            if (a === 'setup' && w) { setup(w); return; }
            if (a === 'up' && w) { step(L, w, -1); }
            if (a === 'down' && w) { step(L, w, 1); }
            if (a === 'col' && w) { moveTo(w, slotOf(w) === 'main' ? 'side' : 'main', null); }
            if (a === 'remove' && w) { L.splice(L.indexOf(w), 1); }
            if (a === 'add') {
                if (L.length >= 40) { return; }
                var type = $t.attr('data-type'), zone = $t.attr('data-zone'), t = typeInfo(type);
                if (!t) { return; }
                var nw = {id: newId(type), type: type, column: t.zone === 'panel' ? (zone === 'side' || zone === 'main' ? zone : t.column) : null, title: null, options: {}};
                L.push(nw);
                moveTo(nw, slotOf(nw), null);
            }
            if (['up', 'down', 'col', 'remove', 'add'].indexOf(a) >= 0) {
                W.dirty = true;
                drawBoard();
                return;
            }
            if (a === 'save' || a === 'reset') {
                if (a === 'reset' && !window.confirm('Replace this room\'s widgets with the default board, for everyone?')) { return; }
                api('/board/widgets', 'PUT', {widgets: a === 'reset' ? null : W.editing}).then(function (res) {
                    if (!res.ok) { W.err = 'Could not save the board: ' + errText(res); drawBoard(); return; }
                    W.editing = null;
                    W.dirty = false;
                    W.err = '';
                    W.data = res.j;
                    W.at = Date.now();
                    drawBoard();
                });
                return;
            }
        }
        if (a === 'customize') {
            var mine = personal() || {};
            W.customizing = {all: arranged(W.data.widgets, {order: mine.order || [], hidden: [], columns: mine.columns || {}}, true),
                             hidden: Array.isArray(mine.hidden) ? mine.hidden.slice() : [],
                             columns: mine.columns && typeof mine.columns === 'object' ? Object.assign({}, mine.columns) : {}};
            drawBoard();
            return;
        }
        if (W.customizing && a.indexOf('mine-') === 0) {
            var C = W.customizing, cw = wid ? find(C.all, wid) : null;
            if (a === 'mine-up' && cw) { step(C.all, cw, -1); }
            if (a === 'mine-down' && cw) { step(C.all, cw, 1); }
            if (a === 'mine-col' && cw) { moveTo(cw, slotOf(cw) === 'main' ? 'side' : 'main', null); }
            if (a === 'mine-reset') { savePersonal(null); W.customizing = null; drawBoard(); return; }
            if (a === 'mine-done') {
                var room = {};
                W.data.widgets.forEach(function (x) { room[x.id] = x.column; });
                var cols = {};
                C.all.forEach(function (x) { if (zoneOf(x) === 'panel' && x.column !== room[x.id]) { cols[x.id] = x.column; } });
                savePersonal({order: C.all.map(function (x) { return x.id; }), hidden: C.hidden.slice(), columns: cols});
                W.customizing = null;
                drawBoard();
                return;
            }
            drawBoard();
        }
    }

    /* ================================================================ Scope */
    var S = {el: null, filter: {}, data: null, seq: 0};
    var SCOPE_KEYS = ['q', 'case_id', 'compromised', 'flag', 'kind', 'vulnerable', 'sort', 'dir', 'page'];
    /* quick filters: [label, the filters they set, the summary figure they show] */
    var QUICK = [['All', {}, 'assets'], ['Compromised', {compromised: '1'}, 'compromised'], ['Without a flag', {flag: 'none'}, 'no_flag'],
                 ['Done', {kind: 'done'}, 'done'], ['Exceptions', {kind: 'exception'}, 'exceptions'], ['Vulnerable', {vulnerable: 'open'}, 'vulnerable'],
                 ['Exploited', {vulnerable: 'exploited'}, 'exploited'], ['KEV', {vulnerable: 'kev'}, 'kev'], ['Overdue findings', {vulnerable: 'overdue'}, 'overdue']];
    var QUICK_KEYS = ['compromised', 'flag', 'kind', 'vulnerable'];
    var COMPROMISE = {compromised: ['Compromised', 'iris-rb-pill-red'], not_compromised: ['Not compromised', 'iris-rb-pill-open'],
                      unknown: ['Unknown', ''], to_be_determined: ['To be determined', '']};
    function cleanScope(f) {
        var out = {};
        SCOPE_KEYS.forEach(function (k) {
            var v = f && f[k] != null ? String(f[k]) : '';
            if (v && v.length <= 200) { out[k] = v; }
        });
        return out;
    }
    /* war_room.js: a Board tile or a ?pane=scope address sets the filters before the tab shows */
    B.setScopeFilter = function (f) {
        S.filter = cleanScope(f);
        if (S.el) { drawScopeShell(); loadScope(); }
    };
    B.filterDecisions = function (status) {
        D.filter = {status: /^[a-z]+$/.test(status || '') ? status : '', q: '', case_id: ''};
        if (D.el) {
            $(D.el).find('#iris-rb-dcase').val('');
            $(D.el).find('#iris-rb-dq').val('');
            setChips();
            loadList();
        }
    };
    B.mountScope = function (el, c) {
        css();
        ctx = c;
        S.el = el;
        var $el = $(el);
        $el.on('click', '[data-sc="quick"]', function () {
            var q = QUICK[Number($(this).attr('data-i'))][1];
            QUICK_KEYS.forEach(function (k) { delete S.filter[k]; });
            Object.keys(q).forEach(function (k) { S.filter[k] = q[k]; });
            delete S.filter.page;
            drawScopeShell();
            loadScope();
        });
        $el.on('change', '[data-sc="field"]', function () {
            var k = $(this).attr('data-k'), v = $(this).val();
            if (v) { S.filter[k] = v; } else { delete S.filter[k]; }
            if (k === 'sort') { S.filter.dir = v === 'findings' || v === 'compromise' ? 'desc' : 'asc'; }
            delete S.filter.page;
            loadScope();
        });
        var t = null;
        $el.on('input', '#iris-sc-q', function () {
            var v = $.trim($(this).val());
            clearTimeout(t);
            t = setTimeout(function () { if (v) { S.filter.q = v; } else { delete S.filter.q; } delete S.filter.page; loadScope(); }, 250);
        });
        $el.on('click', '[data-sc="page"]', function () {
            S.filter.page = String(Math.max(1, Number(S.filter.page || 1) + Number($(this).attr('data-d'))));
            loadScope();
        });
        $el.on('click', '[data-sc="clear"]', function () { S.filter = {}; drawScopeShell(); loadScope(); });
        drawScopeShell();
        loadScope();
    };
    function quickActive(i) {
        var q = QUICK[i][1];
        return QUICK_KEYS.every(function (k) { return (S.filter[k] || '') === (q[k] || ''); });
    }
    function drawScopeShell() {
        var f = S.filter;
        S.el.innerHTML = '<div class="iris-rb-head"><div class="iris-rb-min0"><div class="d-flex align-items-center" style="gap:6px;"><h2 class="iris-rb-h1">Scope</h2>' +
            IrisHelp.icon('room.scope') + '</div><div class="iris-rb-muted" data-sc="sub">&nbsp;</div></div></div>' +
            '<div class="iris-rb-fchips" role="group" aria-label="Quick filters">' + QUICK.map(function (q, i) {
                var on = quickActive(i);
                return '<button type="button" class="iris-rb-fchip' + (on ? ' active' : '') + '" data-sc="quick" data-i="' + i + '" aria-pressed="' + (on ? 'true' : 'false') + '">' +
                    esc(q[0]) + ' <b data-sc-count="' + q[2] + '">&ndash;</b></button>';
            }).join('') + '</div>' +
            '<div class="d-flex flex-wrap align-items-center mb-2" style="gap:6px;">' +
            '<label class="sr-only" for="iris-sc-q">Search assets</label><input type="search" id="iris-sc-q" class="form-control form-control-sm" style="max-width:230px;" placeholder="Search name, IP, domain, type…" value="' + esc(f.q || '') + '">' +
            '<label class="sr-only" for="iris-sc-case">Case</label><select id="iris-sc-case" class="form-control form-control-sm" style="max-width:220px;" data-sc="field" data-k="case_id"><option value="">All cases</option></select>' +
            '<label class="sr-only" for="iris-sc-flag">Flag</label><select id="iris-sc-flag" class="form-control form-control-sm" style="max-width:190px;" data-sc="field" data-k="flag"><option value="">Any flag</option><option value="none">No flag</option></select>' +
            '<label class="sr-only" for="iris-sc-sort">Sort</label><select id="iris-sc-sort" class="form-control form-control-sm" style="max-width:190px;" data-sc="field" data-k="sort">' +
            '<option value="case">Sort: case</option><option value="name">Sort: name</option><option value="compromise">Sort: compromised first</option><option value="findings">Sort: most findings</option></select>' +
            '<button type="button" class="btn btn-sm btn-link" data-sc="clear">Clear filters</button></div>' +
            '<div data-sc="err" class="text-danger small mb-2" role="alert"></div>' +
            '<div class="table-responsive"><table class="table table-sm iris-rb-stable"><caption class="sr-only">Assets in scope</caption><thead><tr>' +
            '<th scope="col">Asset</th><th scope="col">Case</th><th scope="col">Compromise</th><th scope="col">Flags</th><th scope="col" class="text-right">Open findings</th>' +
            '</tr></thead><tbody data-sc="rows"><tr><td colspan="5" class="iris-rb-muted">Loading&hellip;</td></tr></tbody></table></div>' +
            '<div class="d-flex align-items-center" style="gap:8px;" data-sc="pager"></div>';
        $(S.el).find('#iris-sc-sort').val(f.sort || 'case');
    }
    function loadScope() {
        var f = S.filter, q = [], seq = ++S.seq;
        SCOPE_KEYS.forEach(function (k) { if (f[k]) { q.push(k + '=' + encodeURIComponent(f[k])); } });
        $(S.el).find('[data-sc="quick"]').each(function () {
            var on = quickActive(Number($(this).attr('data-i')));
            $(this).toggleClass('active', on).attr('aria-pressed', on ? 'true' : 'false');
        });
        return api('/scope/assets' + (q.length ? '?' + q.join('&') : '')).then(function (res) {
            if (seq !== S.seq) { return; }   /* a newer request is on its way */
            var $el = $(S.el);
            if (!res.ok) {
                $el.find('[data-sc="err"]').text('The scope could not be loaded: ' + errText(res));
                $el.find('[data-sc="rows"]').html('<tr><td colspan="5" class="iris-rb-muted">&mdash;</td></tr>');
                return;
            }
            $el.find('[data-sc="err"]').text('');
            S.data = res.j;
            drawScope();
        });
    }
    function drawScope() {
        var j = S.data, $el = $(S.el), f = S.filter;
        $el.find('[data-sc="sub"]').html('Every asset of the ' + plural(j.case_count, 'attached case') + ' you can open' +
            (j.cases_restricted ? ' &middot; ' + plural(j.cases_restricted, 'more case') + ' you cannot open' : '') + '.');
        Object.keys(j.summary || {}).forEach(function (k) { $el.find('[data-sc-count="' + k + '"]').text(Number(j.summary[k])); });
        var $c = $el.find('#iris-sc-case');
        if ($c.children().length === 1) {
            (j.cases || []).forEach(function (c) { $c.append($('<option>').val(String(c.case_id)).text(c.case_name || ('Case #' + c.case_id))); });
        }
        $c.val(f.case_id || '');
        var $f = $el.find('#iris-sc-flag');
        if ($f.children().length === 2) {
            (j.flags || []).forEach(function (x) { $f.append($('<option>').val(String(x.flag_id)).text(x.name + ' (' + Number(x.assets) + ')')); });
        }
        $f.val(f.flag || '');
        var rows = j.assets || [];
        $el.find('[data-sc="rows"]').html(rows.length ? rows.map(scopeRow).join('') :
            '<tr><td colspan="5" class="iris-rb-muted" data-sc="empty">' + (j.case_count === 0 ? 'No case attached to this war room that you can open.' :
                (j.summary.assets === 0 ? 'The attached cases you can open have no asset yet.' : 'No asset matches these filters.')) + '</td></tr>');
        var page = Number(j.page) || 1, per = Number(j.per_page) || 100, from = j.total ? (page - 1) * per + 1 : 0, to = Math.min(j.total, page * per);
        $el.find('[data-sc="pager"]').html('<span class="iris-rb-muted" data-sc="range">' + from + '&ndash;' + to + ' of ' + plural(j.total, 'asset') + '</span>' +
            (j.total > per ? '<button type="button" class="iris-rb-ibtn" data-sc="page" data-d="-1" aria-label="Previous page"' + (page <= 1 ? ' disabled' : '') + '>' + ic('chevron-left', '', 14) + '</button>' +
                '<button type="button" class="iris-rb-ibtn" data-sc="page" data-d="1" aria-label="Next page"' + (to >= j.total ? ' disabled' : '') + '>' + ic('chevron-right', '', 14) + '</button>' : ''));
    }
    function scopeRow(r) {
        var comp = COMPROMISE[r.compromise] || ['Not set', ''];
        var v = r.findings || {}, where = [r.asset_type, r.asset_ip, r.asset_domain].filter(Boolean).join(' \u00b7 ');
        var fl = (r.flags || []).length ? r.flags.map(function (x) { return window.IrisFlags ? window.IrisFlags.chip(x) : esc(x.name); }).join(' ') : '<span class="iris-rb-muted">No flag</span>';
        var fnd = v.open ? '<a href="' + esc(r.vulns_href) + '">' + Number(v.open) + ' open</a>' +
            (v.exploited_open ? ' &middot; <span class="iris-rb-t-red">' + Number(v.exploited_open) + ' exploited</span>' : '') +
            (v.kev_open ? ' &middot; <span class="iris-rb-t-red">' + Number(v.kev_open) + ' KEV</span>' : '') +
            (v.overdue ? ' &middot; <span class="iris-rb-t-amber">' + Number(v.overdue) + ' overdue</span>' : '') : '<span class="iris-rb-muted">&mdash;</span>';
        return '<tr data-asset="' + Number(r.asset_id) + '"><td><a href="' + esc(r.href) + '">' + esc(r.asset_name || 'Unnamed asset') + '</a>' +
            (where ? '<div class="iris-rb-meta">' + esc(where) + '</div>' : '') + '</td>' +
            '<td><a href="/case?cid=' + Number(r.case_id) + '" class="iris-rb-mono">#' + Number(r.case_id) + '</a> <span class="iris-rb-meta">' + esc(caseTitle(r)) + '</span></td>' +
            '<td><span class="iris-rb-pill ' + comp[1] + '">' + esc(comp[0]) + '</span></td><td>' + fl + '</td><td class="text-right">' + fnd + '</td></tr>';
    }

    window.IrisRoomBoard = B;
})();

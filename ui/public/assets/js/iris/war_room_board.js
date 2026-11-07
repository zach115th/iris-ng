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
            '.iris-rb-cols{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:14px;align-items:start;}',
            '.iris-rb-col{display:flex;flex-direction:column;gap:14px;min-width:0;}',
            '.iris-rb-w{border:1px solid rgba(255,255,255,.07);border-radius:8px;background:#15151a;padding:12px 14px;min-width:0;}',
            '.iris-rb-w h3{font-size:.86rem;font-weight:600;margin:0 0 8px;color:#e8e8ee;display:flex;align-items:center;gap:6px;}',
            '.iris-rb-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;}',
            '.iris-rb-tile{border:1px solid rgba(255,255,255,.07);border-radius:8px;padding:8px 10px;}',
            '.iris-rb-tile b{display:block;font-size:1.3rem;color:#e8e8ee;}',
            '.iris-rb-tile span{font-size:.72rem;color:#9a9aa5;}',
            '.iris-rb-bar{height:7px;border-radius:4px;background:rgba(255,255,255,.08);overflow:hidden;margin:4px 0 8px;}',
            '.iris-rb-bar i{display:block;height:100%;background:#2dce89;}',
            '.iris-rb-att{list-style:none;padding:0;margin:0;}',
            '.iris-rb-att li{display:flex;gap:8px;align-items:flex-start;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:.8rem;}',
            '.iris-rb-sev{width:8px;height:8px;border-radius:50%;margin-top:6px;flex:0 0 auto;}',
            '.iris-rb-linkbtn{background:none;border:0;padding:0;color:#a78bfa;cursor:pointer;text-align:left;}',
            '.iris-rb-linkbtn:hover{text-decoration:underline;}',
            '.iris-rb-cases{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px;}',
            '.iris-rb-edit{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:8px;padding:6px 8px;border:1px dashed rgba(139,92,246,.45);border-radius:6px;}',
            '.iris-rb-note{font-size:.84rem;}',
            '.iris-rb-fchips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;}',
            '.iris-rb-fchip{background:none;border:1px solid rgba(255,255,255,.14);border-radius:999px;color:#c8c8d0;font-size:.74rem;padding:1px 10px;cursor:pointer;}',
            '.iris-rb-fchip.active{border-color:#4a8cff;background:rgba(74,140,255,.15);color:#9ec2ff;}',
            '.iris-rb-fchip b{font-weight:600;margin-left:3px;}',
            '.iris-rb-pick{background:none;border:1px solid rgba(255,255,255,.15);border-radius:6px;color:#c8c8d0;font-size:.76rem;padding:1px 8px;margin:0 4px 4px 0;cursor:pointer;}',
            '.iris-rb-pick.on{border-color:#4a8cff;background:rgba(74,140,255,.15);color:#e8e8ee;}',
            '.iris-rb-empty{text-align:center;padding:48px 16px;}',
            '.iris-rb-empty-ic{display:inline-flex;width:40px;height:40px;border-radius:50%;align-items:center;justify-content:center;background:rgba(139,92,246,.15);color:#a78bfa;margin-bottom:10px;}',
            '.iris-rb-empty-ic svg{width:20px;height:20px;}',
            '@media (max-width: 991px){.iris-rb-split{display:block;}.iris-rb-left{margin-bottom:12px;}.iris-rb-cols{grid-template-columns:minmax(0,1fr);}}'
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
    var W = {el: null, data: null, editing: null, customizing: null};
    var LS = function () { return 'war_room_board_layout_' + id(ctx.roomId); };
    function personal() {
        try { var v = JSON.parse(window.localStorage.getItem(LS()) || 'null'); return v && typeof v === 'object' ? v : null; } catch (e) { return null; }
    }
    function savePersonal(v) {
        try { if (v) { window.localStorage.setItem(LS(), JSON.stringify(v)); } else { window.localStorage.removeItem(LS()); } } catch (e) { /* per-browser convenience only */ }
    }
    /* the room's widgets in the viewer's own order, minus the ones they hid */
    function arranged(widgets, mine) {
        if (!mine) { return widgets.slice(); }
        var order = Array.isArray(mine.order) ? mine.order : [], hidden = Array.isArray(mine.hidden) ? mine.hidden : [];
        var byId = {};
        widgets.forEach(function (w) { byId[w.id] = w; });
        var out = order.filter(function (i) { return byId[i]; }).map(function (i) { return byId[i]; });
        widgets.forEach(function (w, n) {
            if (out.indexOf(w) >= 0) { return; }
            var at = 0;
            for (var k = n - 1; k >= 0; k--) { var p = out.indexOf(widgets[k]); if (p >= 0) { at = p + 1; break; } }
            out.splice(at, 0, w);
        });
        return out.filter(function (w) { return hidden.indexOf(w.id) < 0; });
    }

    B.mountBoard = function (el, c) {
        css();
        ctx = c;
        W.el = el;
        var $el = $(el);
        $el.on('click', '[data-wb]', function (e) {
            /* the "Add widget" items are <a href="#">: never follow them */
            e.preventDefault();
            var a = $(this).attr('data-wb');
            if (a === 'pane') { ctx.openPane($(this).attr('data-pane'), {decisionId: Number($(this).attr('data-id')) || null}); return; }
            boardAction(a, $(this));
        });
        loadBoard();
    };
    function loadBoard() {
        return api('/board').then(function (res) {
            if (!res.ok) { $(W.el).html('<div class="text-danger p-3">The board could not be loaded: ' + esc(errText(res)) + '</div>'); return; }
            W.data = res.j;
            drawBoard();
        });
    }
    function widgetTitle(w) {
        var t = (W.data.widget_types || []).filter(function (x) { return x.type === w.type; })[0];
        return w.title || (t ? t.label : w.type);
    }
    function drawBoard() {
        var b = W.data, editing = W.editing, cust = W.customizing;
        var list = editing ? editing : (cust ? cust.all : arranged(b.widgets, personal()));
        var head = '<div class="d-flex flex-wrap align-items-center mb-2" style="gap:6px;"><h2 class="h6 mb-0 mr-1">Board</h2>' + IrisHelp.icon('room.board') +
            '<span class="iris-rb-muted">' + (b.is_default ? 'The default board.' : 'The room\'s board, set by a lead.') + ' Figures over the ' + Number(b.data.case_count) +
            ' attached case' + (b.data.case_count === 1 ? '' : 's') + ' you can open.</span><span class="ml-auto"></span>';
        if (editing) {
            head += '<div class="dropdown"><button type="button" class="btn btn-sm btn-outline-secondary dropdown-toggle" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">Add widget</button><div class="dropdown-menu dropdown-menu-right">' +
                (b.widget_types || []).map(function (t) {
                    return '<a href="#" class="dropdown-item" data-wb="add" data-type="' + esc(t.type) + '"><b>' + esc(t.label) + '</b><div class="iris-rb-muted">' + esc(t.description) + '</div></a>';
                }).join('') + '</div></div>' +
                '<button type="button" class="btn btn-sm btn-outline-danger" data-wb="reset">Reset to the default board</button>' +
                '<button type="button" class="btn btn-sm btn-outline-secondary" data-wb="cancel">Cancel</button><button type="button" class="btn btn-sm btn-primary" data-wb="save">Save the board</button>';
        } else if (cust) {
            head += '<span class="iris-rb-muted">Only for you, in this war room.</span><button type="button" class="btn btn-sm btn-outline-secondary" data-wb="mine-reset">Back to the room\'s layout</button>' +
                '<button type="button" class="btn btn-sm btn-primary" data-wb="mine-done">Done</button>';
        } else {
            head += '<button type="button" class="btn btn-sm btn-outline-secondary" data-wb="refresh">Refresh</button>' +
                '<button type="button" class="btn btn-sm btn-outline-secondary" data-wb="customize" title="Hide or reorder widgets, only for you">Customize</button>' +
                (b.can_edit ? '<button type="button" class="btn btn-sm btn-outline-primary" data-wb="edit" title="Set the widgets of this war room\'s board, for everyone">Edit board</button>' : '');
        }
        head += '</div>' + (W.err ? '<div class="text-danger small mb-2" role="alert">' + esc(W.err) + '</div>' : '');
        var cols = {main: '', side: ''};
        list.forEach(function (w, i) {
            var col = w.column === 'side' ? 'side' : 'main';
            cols[col] += '<section class="iris-rb-w" aria-label="' + esc(widgetTitle(w)) + '" data-widget="' + esc(w.id) + '">' +
                (editing ? editControls(w, i, list.length) : '') + (cust ? custControls(w, i, list.length, cust) : '') +
                '<h3>' + esc(widgetTitle(w)) + '</h3>' + widgetBody(w) + '</section>';
        });
        $(W.el).html(head + '<div class="iris-rb-cols"><div class="iris-rb-col">' + (cols.main || '<div class="iris-rb-muted">Nothing here.</div>') +
            '</div><div class="iris-rb-col">' + (cols.side || '') + '</div></div>');
    }
    function editControls(w, i, n) {
        var o = w.options || {};
        var teams = (W.data.data.teams || []);
        return '<div class="iris-rb-edit">' +
            '<button type="button" class="btn btn-sm btn-outline-secondary" data-wb="up" data-i="' + i + '"' + (i === 0 ? ' disabled' : '') + ' aria-label="Move up">&uarr;</button>' +
            '<button type="button" class="btn btn-sm btn-outline-secondary" data-wb="down" data-i="' + i + '"' + (i === n - 1 ? ' disabled' : '') + ' aria-label="Move down">&darr;</button>' +
            '<button type="button" class="btn btn-sm btn-outline-secondary" data-wb="col" data-i="' + i + '">' + (w.column === 'side' ? 'To the main column' : 'To the side column') + '</button>' +
            '<label class="sr-only" for="wb-title-' + i + '">Title</label><input type="text" class="form-control form-control-sm" style="max-width:180px;" id="wb-title-' + i + '" data-wb-title="' + i + '" maxlength="80" placeholder="Title" value="' + esc(w.title || '') + '">' +
            (w.type === 'flags' ? '<label class="mb-0 iris-rb-muted"><input type="checkbox" data-wb-opt="of_total" data-i="' + i + '"' + (o.of_total ? ' checked' : '') + '> show 10/20</label>' : '') +
            (w.type === 'tasks' ? '<label class="mb-0 iris-rb-muted"><input type="checkbox" data-wb-opt="in_progress_only" data-i="' + i + '"' + (o.in_progress_only ? ' checked' : '') + '> in progress only</label>' +
                teams.map(function (t) {
                    return '<label class="mb-0 iris-rb-muted"><input type="checkbox" data-wb-team="' + id(t.id) + '" data-i="' + i + '"' + ((o.team_ids || []).indexOf(t.id) >= 0 ? ' checked' : '') + '> @' + esc(t.name) + '</label>';
                }).join('') : '') +
            '<button type="button" class="btn btn-sm btn-outline-danger ml-auto" data-wb="remove" data-i="' + i + '" aria-label="Remove this widget">&times;</button>' +
            (w.type === 'note' ? '<label class="sr-only" for="wb-note-' + i + '">Note (Markdown)</label><textarea class="form-control form-control-sm mt-1" id="wb-note-' + i + '" data-wb-note="' + i + '" rows="5" maxlength="10000" placeholder="A Markdown note for everyone">' + esc(o.text || '') + '</textarea>' : '') +
            '</div>';
    }
    function custControls(w, i, n, cust) {
        var hidden = cust.hidden.indexOf(w.id) >= 0;
        return '<div class="iris-rb-edit"><button type="button" class="btn btn-sm btn-outline-secondary" data-wb="mine-up" data-i="' + i + '"' + (i === 0 ? ' disabled' : '') + ' aria-label="Move up">&uarr;</button>' +
            '<button type="button" class="btn btn-sm btn-outline-secondary" data-wb="mine-down" data-i="' + i + '"' + (i === n - 1 ? ' disabled' : '') + ' aria-label="Move down">&darr;</button>' +
            '<button type="button" class="btn btn-sm ' + (hidden ? 'btn-outline-primary' : 'btn-outline-secondary') + '" data-wb="mine-hide" data-i="' + i + '">' + (hidden ? 'Show' : 'Hide') + '</button>' +
            (hidden ? '<span class="iris-rb-muted">hidden for you</span>' : '') + '</div>';
    }
    function tile(n, label, cls) { return '<div class="iris-rb-tile"><b class="' + (cls || '') + '">' + Number(n || 0) + '</b><span>' + label + '</span></div>'; }
    function paneLink(text, pane, did) {
        return '<button type="button" class="iris-rb-linkbtn" data-wb="pane" data-pane="' + esc(pane) + '"' + (did ? ' data-id="' + id(did) + '"' : '') + '>' + text + '</button>';
    }
    function widgetBody(w) {
        var d = W.data.data, o = w.options || {};
        if (w.type === 'indicators') {
            var i = d.indicators;
            return '<div class="iris-rb-tiles">' + tile(i.open_decisions, 'open decisions') + tile(i.overdue_decisions, 'overdue decisions', i.overdue_decisions ? 'iris-rb-over' : '') +
                tile(i.open_tasks, 'open tasks (' + Number(i.tasks_in_progress) + ' in progress)') + tile(i.assets_done, 'of ' + Number(i.assets) + ' assets done') +
                tile(i.exceptions, 'exceptions') + tile(i.compromised, 'compromised, not done', i.compromised ? 'iris-rb-over' : '') +
                tile(i.vulnerabilities_open, 'open vulnerabilities (' + Number(i.vulnerabilities_exploited_open) + ' exploited)') + '</div>';
        }
        if (w.type === 'attention') {
            if (!d.attention.length) { return '<div class="iris-rb-muted">Nothing needs attention.</div>'; }
            var colour = {danger: '#ff8095', warning: '#f4c430', info: '#8fa3ef'};
            return '<ul class="iris-rb-att">' + d.attention.map(function (a) {
                var text = esc(a.text) + (a.case_name ? ' <span class="iris-rb-muted">(' + esc(a.case_name) + ')</span>' : '');
                var body = a.link && a.link.href ? '<a href="' + esc(a.link.href) + '">' + text + '</a>'
                    : (a.link && a.link.pane ? paneLink(text, a.link.pane, a.link.decision_id) : text);
                return '<li><span class="iris-rb-sev" style="background:' + (colour[a.severity] || '#9a9aa5') + ';" aria-hidden="true"></span><span>' + body + '</span></li>';
            }).join('') + '</ul>';
        }
        if (w.type === 'flags') {
            var f = d.flags, pct = f.total ? Math.round(100 * f.done / f.total) : 0;
            return '<div class="iris-rb-muted">Done ' + IrisHelp.icon('flags.kind') + ' ' + (o.of_total ? Number(f.done) + '/' + Number(f.total) : Number(f.done)) + ' assets (' + pct + '%)</div>' +
                '<div class="iris-rb-bar" role="img" aria-label="' + pct + '% of the assets done"><i style="width:' + pct + '%;"></i></div>' +
                '<div class="iris-rb-tiles mb-2">' + tile(f.exceptions, 'with an exception flag') + tile(f.no_flag, 'without a flag') + tile(f.compromised, 'compromised, not done', f.compromised ? 'iris-rb-over' : '') + '</div>' +
                (f.by_flag.length ? '<div>' + f.by_flag.map(function (x) {
                    return (window.IrisFlags ? window.IrisFlags.chip(x) : esc(x.name)) + ' <span class="iris-rb-muted mr-2">' + Number(x.assets) + '</span>';
                }).join('') + '</div>' : '<div class="iris-rb-muted">No asset flag is configured (Settings &rarr; Asset flags).</div>');
        }
        if (w.type === 'cases') {
            if (!d.cases.length) { return '<div class="iris-rb-muted">No case attached to this war room yet' + (d.case_count === 0 ? ', or none you can open' : '') + '.</div>'; }
            return '<div class="iris-rb-cases">' + d.cases.map(function (c) {
                var pc = c.assets ? Math.round(100 * c.done / c.assets) : 0;
                return '<div class="iris-rb-tile"><div style="font-weight:600;">' + (c.href ? '<a href="' + esc(c.href) + '">' + esc(c.case_name) + '</a>' : esc(c.case_name)) + '</div>' +
                    '<div class="iris-rb-muted">' + esc(c.state_name || '') + '</div><div class="iris-rb-bar"><i style="width:' + pc + '%;"></i></div>' +
                    '<div class="iris-rb-muted">' + Number(c.done) + '/' + Number(c.assets) + ' assets done &middot; ' + Number(c.exceptions) + ' exceptions' +
                    (c.compromised ? ' &middot; <span class="iris-rb-over">' + Number(c.compromised) + ' compromised</span>' : '') +
                    ' &middot; ' + Number(c.vulnerabilities_open) + ' open vulnerabilities' + (c.vulnerabilities_exploited_open ? ' (' + Number(c.vulnerabilities_exploited_open) + ' exploited)' : '') + '</div></div>';
            }).join('') + '</div>';
        }
        if (w.type === 'decisions') {
            if (!d.decisions.length) { return '<div class="iris-rb-muted">No open decision.</div>'; }
            return '<ul class="iris-rb-att">' + d.decisions.map(function (x) {
                return '<li><span>' + paneLink('<span class="iris-rb-ref">' + esc(x.ref) + '</span>' + esc(x.title), 'decisions', x.decision_id) +
                    '<div class="iris-rb-muted">' + statusBadge(x.status) + ' ' + due({target_at: x.target_at, is_open: true, is_overdue: x.is_overdue}) +
                    (x.awaiting_me ? ' &middot; <b style="color:#f4c430;">awaits your vote</b>' : '') + '</div></span></li>';
            }).join('') + '</ul>';
        }
        if (w.type === 'tasks') {
            var teams = o.team_ids || [];
            var rows = d.tasks.filter(function (t) {
                if (o.in_progress_only && t.status !== 'in_progress') { return false; }
                return !teams.length || t.team_ids.some(function (x) { return teams.indexOf(x) >= 0; });
            });
            if (!rows.length) { return '<div class="iris-rb-muted">Nothing here.</div>'; }
            return '<ul class="iris-rb-att">' + rows.map(function (t) {
                return '<li><span>' + paneLink(esc(t.title), 'tasks') + '<div class="iris-rb-muted">' + esc(t.status.replace(/_/g, ' ')) +
                    (t.assignee ? ' &middot; ' + esc(t.assignee) : '') + (t.due_date ? ' &middot; <span class="' + (t.overdue ? 'iris-rb-over' : '') + '">due ' + esc(utc(t.due_date)) + '</span>' : '') + '</div></span></li>';
            }).join('') + '</ul>';
        }
        if (w.type === 'vulnerabilities') {
            var v = d.vulnerabilities;
            return '<div class="iris-rb-tiles">' + tile(v.open, 'open') + tile(v.exploited_open, 'exploited & open', v.exploited_open ? 'iris-rb-over' : '') +
                tile(v.overdue, 'overdue', v.overdue ? 'iris-rb-over' : '') + tile(v.kev_open, 'KEV open') + tile(v.vulnerable_assets, 'vulnerable assets') + '</div>';
        }
        if (w.type === 'note') {
            var html = (W.data.notes || {})[w.id];
            return html ? '<div class="iris-rb-note">' + html + '</div>' : '<div class="iris-rb-muted">Empty note.</div>';
        }
        return '';
    }
    function readEdits() {
        var $el = $(W.el);
        W.editing.forEach(function (w, i) {
            var t = $el.find('[data-wb-title="' + i + '"]');
            if (t.length) { w.title = $.trim(t.val()) || null; }
            var n = $el.find('[data-wb-note="' + i + '"]');
            if (n.length) { w.options.text = n.val(); }
            $el.find('[data-wb-opt][data-i="' + i + '"]').each(function () { w.options[$(this).attr('data-wb-opt')] = this.checked; });
            if (w.type === 'tasks') {
                w.options.team_ids = $el.find('[data-wb-team][data-i="' + i + '"]:checked').map(function () { return Number($(this).attr('data-wb-team')); }).get();
            }
        });
    }
    function boardAction(a, $t) {
        var i = Number($t.attr('data-i'));
        W.err = '';
        if (a === 'refresh') { loadBoard(); return; }
        if (a === 'edit') { W.editing = JSON.parse(JSON.stringify(W.data.widgets)); W.editing.forEach(function (w) { w.options = w.options || {}; }); drawBoard(); return; }
        if (a === 'cancel') { W.editing = null; drawBoard(); return; }
        if (W.editing && ['up', 'down', 'col', 'remove', 'add'].indexOf(a) >= 0) {
            readEdits();
            var L = W.editing;
            if (a === 'up' && i > 0) { L.splice(i - 1, 0, L.splice(i, 1)[0]); }
            if (a === 'down' && i < L.length - 1) { L.splice(i + 1, 0, L.splice(i, 1)[0]); }
            if (a === 'col') { L[i].column = L[i].column === 'side' ? 'main' : 'side'; }
            if (a === 'remove') { L.splice(i, 1); }
            if (a === 'add') {
                var type = $t.attr('data-type'), t = (W.data.widget_types || []).filter(function (x) { return x.type === type; })[0];
                var n = 1;
                while (L.some(function (w) { return w.id === type + '-' + n; })) { n++; }
                L.push({id: type + '-' + n, type: type, column: t ? t.column : 'main', title: null, options: {}});
            }
            drawBoard();
            return;
        }
        if (a === 'save' || a === 'reset') {
            if (a === 'save') { readEdits(); }
            if (a === 'reset' && !window.confirm('Restore the default board for everyone in this war room?')) { return; }
            api('/board/widgets', 'PUT', {widgets: a === 'reset' ? null : W.editing}).then(function (res) {
                if (!res.ok) { W.err = errText(res); drawBoard(); return; }
                W.editing = null;
                W.data = res.j;
                drawBoard();
            });
            return;
        }
        if (a === 'customize') {
            var mine = personal() || {};
            var all = arranged(W.data.widgets, {order: mine.order || [], hidden: []});
            W.customizing = {all: all, hidden: Array.isArray(mine.hidden) ? mine.hidden.slice() : []};
            drawBoard();
            return;
        }
        if (W.customizing && a.indexOf('mine-') === 0) {
            var C = W.customizing;
            if (a === 'mine-up' && i > 0) { C.all.splice(i - 1, 0, C.all.splice(i, 1)[0]); }
            if (a === 'mine-down' && i < C.all.length - 1) { C.all.splice(i + 1, 0, C.all.splice(i, 1)[0]); }
            if (a === 'mine-hide') {
                var wid = C.all[i].id, k = C.hidden.indexOf(wid);
                if (k >= 0) { C.hidden.splice(k, 1); } else { C.hidden.push(wid); }
            }
            if (a === 'mine-reset') { savePersonal(null); W.customizing = null; drawBoard(); return; }
            if (a === 'mine-done') {
                savePersonal({order: C.all.map(function (w) { return w.id; }), hidden: C.hidden});
                W.customizing = null;
                drawBoard();
                return;
            }
            drawBoard();
        }
    }

    window.IrisRoomBoard = B;
})();

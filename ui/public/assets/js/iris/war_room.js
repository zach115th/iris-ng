/* War Room detail page (iris-ng v2, Phase 6; v3-shaped).
 * Import-free by rule (ui/public is copied verbatim). REST + short polling
 * by DESIGN: the upstream socket handler package is dead code (no
 * client->server events are registered in this tree).
 * Topics/threads/decisions/slash-commands render as inert placeholders
 * (maintainer decision) — the machinery is deferred. */

var IRIS_WROOM = {
    /* cid is a case id — digits only, else fall back to '1' (it is
       interpolated into request URLs; see war_rooms.js for the sink
       this guards against). */
    _cid: (function () {
        var v = new URLSearchParams(window.location.search).get('cid');
        return /^\d+$/.test(v || '') ? v : '1';
    })(),
    _rid: null,
    _room: null,
    _pollTimer: null,
    _sitrep: null,
    _corr: null,
    _stream: [],
    _topics: ['main'],
    _users: [],
    /* v3 stream lanes (matching the preview): message / task_event /
     * sitrep / notes_pins / system / case_link. Case activity is filtered
     * via the per-case sub-lanes instead of a top lane. */
    _lanes: {message: true, task_event: true, sitrep: true,
             notes_pins: true, system: true, case_link: true},
    _topicSel: null,       /* null = all topics; otherwise a Set of names */
    _threadSel: null,      /* null = all threads; otherwise a Set of root ids */
    _caseLanes: {},        /* case_id -> {sublane: bool}; absent = all on */
    _caseOpen: {},         /* case_id -> sub-lane list expanded */
    _chatQ: '',
    /* Composer target: topic mode or reply/thread mode. */
    _target: {mode: 'topic', topic: 'main', parentId: null, label: null},
    _loadedTabs: {}
};

var IRIS_WROOM_LANES = [
    ['message', 'Messages'],
    ['task_event', 'Tasks'],
    ['sitrep', 'SitReps'],
    ['notes_pins', 'Notes / Pins'],
    ['system', 'System'],
    ['case_link', 'Case attached / detached']
];

var IRIS_WROOM_SUBLANES = [
    ['notes', 'Notes'], ['iocs', 'IOCs'], ['assets', 'Assets'],
    ['evidence', 'Evidence'], ['tasks', 'Tasks'],
    ['timeline', 'Timeline events'], ['lifecycle', 'Case lifecycle'],
    ['other', 'Other']
];

/* Case-activity rows are text-only (the Phase 5 bell trade-off), so the
 * per-case sub-lanes classify by keyword — heuristic by design. */
function iris_wroom_classify(desc) {
    var d = (desc || '').toLowerCase();
    if (d.indexOf('ioc') !== -1) return 'iocs';
    if (d.indexOf('task') !== -1) return 'tasks';
    if (d.indexOf('asset') !== -1) return 'assets';
    if (d.indexOf('evidence') !== -1 || d.indexOf('file') !== -1
        || d.indexOf('datastore') !== -1) return 'evidence';
    if (d.indexOf('event') !== -1 || d.indexOf('timeline') !== -1)
        return 'timeline';
    if (d.indexOf('note') !== -1) return 'notes';
    if (d.indexOf('review') !== -1 || d.indexOf('clos') !== -1
        || d.indexOf('open') !== -1 || d.indexOf('state') !== -1
        || d.indexOf('status') !== -1 || d.indexOf('summary') !== -1)
        return 'lifecycle';
    return 'other';
}

var IRIS_WROOM_COMMANDS = [
    ['/note <text>', 'Create a war-room note'],
    ['/pin <text>', 'Post a pinned note (hover a message to pin it)'],
    ['/decision <text>', 'Log a command decision'],
    ['/attach <case_id>', 'Attach a case'],
    ['/detach <case_id>', 'Detach a case'],
    ['/task [@user] <title>', 'Create a room task'],
    ['/assign @user <title>', 'Create + assign a room task'],
    ['/sitrep <title>', 'Start a SitRep draft'],
    ['/summary', 'AI-draft a SitRep from the room snapshot'],
    ['/state <open|active|standby|closed>', 'Flip war-room state (lead)'],
    ['/priority <low|medium|high|critical>', 'Set room severity (lead)'],
    ['/thread <title>', 'Open a named thread'],
    ['/topic <name>', 'Create + switch to a topic']
];

function iris_wroom_esc(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function iris_wroom_csrf() {
    var el = document.getElementById('csrf_token');
    return el ? el.value : '';
}

function iris_wroom_rel(iso) {
    if (!iso) return '';
    var s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    return Math.floor(s / 86400) + 'd ago';
}

function iris_wroom_api(method, path, body) {
    var opts = {method: method, headers: {'Accept': 'application/json'}};
    if (body) {
        body.csrf_token = iris_wroom_csrf();
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }
    return fetch('/api/v2/war-rooms/' + IRIS_WROOM._rid + path, opts)
        .then(function (r) {
            return r.json().then(function (j) { return {ok: r.ok, status: r.status, j: j}; });
        });
}

function iris_wroom_can(minRole) {
    var rank = {observer: 1, responder: 2, lead: 3};
    var role = IRIS_WROOM._room ? IRIS_WROOM._room.my_role : null;
    if (!role) return false;
    return rank[role] >= rank[minRole];
}

function iris_wroom_active() {
    /* v3 four-state model: only 'closed' is read-only. */
    return IRIS_WROOM._room && IRIS_WROOM._room.status !== 'closed';
}

/* ------------------------------------------------------------------ header */

var IRIS_WROOM_AVACOLORS = ['#8B5CF6', '#5e72e4', '#2dce89', '#f4c430',
                            '#F25961', '#11cdef', '#fb6340', '#a78bfa'];

function iris_wroom_avatar(name) {
    var n = name || '?';
    var parts = n.trim().split(/\s+/);
    var initials = (parts[0][0] || '?') + (parts[1] ? parts[1][0] : '');
    var h = 0;
    for (var i = 0; i < n.length; i++) h = (h * 31 + n.charCodeAt(i)) >>> 0;
    var color = IRIS_WROOM_AVACOLORS[h % IRIS_WROOM_AVACOLORS.length];
    return '<span class="iris-wr-avatar" style="background:' + color +
        '44; border: 1px solid ' + color + '88;">' +
        iris_wroom_esc(initials.toUpperCase()) + '</span>';
}

function iris_wroom_render_header() {
    var r = IRIS_WROOM._room;
    document.getElementById('iris-wr-name').textContent = r.name;
    document.title = 'WR#' + r.id + ' - ' + r.name;

    var created = r.created_at ? new Date(r.created_at) : null;
    var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug',
                  'Sep', 'Oct', 'Nov', 'Dec'];
    var leadCount = (r.members || []).filter(function (m) {
        return m.role === 'lead'; }).length;
    var crown = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11.562 3.266a.5.5 0 0 1 .876 0L15.39 8.87a1 1 0 0 0 1.516.294L21.183 5.5a.5.5 0 0 1 .798.519l-2.834 10.246a1 1 0 0 1-.956.735H5.81a1 1 0 0 1-.957-.735L2.02 6.02a.5.5 0 0 1 .798-.52l4.276 3.664a1 1 0 0 0 1.516-.294z"/><path d="M5 21h14"/></svg>';
    document.getElementById('iris-wr-meta').innerHTML =
        (created ? 'Created ' + months[created.getMonth()] + ' ' +
            created.getDate() + ', ' + created.getFullYear() + ' · ' : '') +
        crown + ' ' + leadCount + ' lead' + (leadCount === 1 ? '' : 's') +
        ' · ' + r.member_count + ' member' +
        (r.member_count === 1 ? '' : 's') +
        ' · ' + r.case_count + ' case' + (r.case_count === 1 ? '' : 's') +
        (r.description ? ' &nbsp; ' + iris_wroom_esc(r.description) : '');

    var radio = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9"/><path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5"/><circle cx="12" cy="12" r="2"/><path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5"/><path d="M19.1 4.9C23 8.8 23 15.1 19.1 19"/></svg>';
    document.getElementById('iris-wr-status').innerHTML =
        '<span class="iris-wr-chip-lg iris-wr-chip-status-' + r.status + '">' +
        radio + ' ' + r.status + '</span>';

    var alertIco = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>';
    document.getElementById('iris-wr-severity').innerHTML = r.severity
        ? '<span class="iris-wr-chip-lg iris-wr-chip-sev-' + r.severity + '">' +
          alertIco + ' ' + r.severity + '</span>'
        : '';

    document.getElementById('iris-wr-myrole').innerHTML = r.my_role
        ? '<span class="iris-wr-role' + (r.my_role === 'lead'
            ? ' iris-wr-role-lead' : '') + '">' + iris_wroom_esc(r.my_role) +
          '</span>' : '';

    var sv = document.getElementById('iris-wr-summary-view');
    if (r.summary) {
        sv.textContent = r.summary;
        sv.classList.remove('text-muted');
    } else {
        sv.textContent = 'No summary yet.';
        sv.classList.add('text-muted');
    }

    var lead = iris_wroom_can('lead');
    document.getElementById('iris-wr-edit-btn').style.display =
        (lead && iris_wroom_active()) ? '' : 'none';
    /* Delete is gated on lead ALONE — unlike Edit it stays available on a
       CLOSED room, since an accidentally created room may already be closed
       (the closed guard protects room content, not the room row). */
    document.getElementById('iris-wr-delete-btn').style.display =
        lead ? '' : 'none';
    var sel = document.getElementById('iris-wr-status-select');
    sel.style.display = lead ? '' : 'none';
    sel.value = r.status;
    document.getElementById('iris-wr-composer').style.display =
        (iris_wroom_can('responder') && iris_wroom_active()) ? '' : 'none';
    document.getElementById('iris-wr-sitrep-new').style.display =
        (iris_wroom_can('responder') && iris_wroom_active()) ? '' : 'none';
    document.getElementById('iris-wr-sitrep-ai').style.display =
        (iris_wroom_can('responder') && iris_wroom_active()) ? '' : 'none';
    /* The Cases tab's + Attach button and the Members tab's + Add member
       button are gated in their own render functions. */
}

function iris_wroom_render_members() {
    var members = IRIS_WROOM._room.members || [];
    document.getElementById('iris-wr-member-count').textContent =
        '(' + members.length + ')';
    var lead = iris_wroom_can('lead') && iris_wroom_active();
    document.getElementById('iris-wr-member-addbtn').style.display =
        lead ? '' : 'none';
    var crown = '<span class="iris-wr-mb-crown" title="Room lead">' +
        '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11.562 3.266a.5.5 0 0 1 .876 0L15.39 8.87a1 1 0 0 0 1.516.294L21.183 5.5a.5.5 0 0 1 .798.519l-2.834 10.246a1 1 0 0 1-.956.735H5.81a1 1 0 0 1-.957-.735L2.02 6.02a.5.5 0 0 1 .798-.519l4.276 3.664a1 1 0 0 0 1.516-.294z"/><path d="M5 21h14"/></svg></span>';
    var trashIco = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></svg>';
    document.getElementById('iris-wr-mb-list').innerHTML =
        members.map(function (m) {
            /* Trash: leads manage everyone; anyone can leave (self-leave —
               last-lead protection is server-side either way). */
            var removable = lead || m.user_id === IRIS_WROOM._myUserId;
            return '<div class="iris-wr-mb-row">' +
                (m.role === 'lead' ? crown : '') +
                '<span class="iris-wr-mb-name">' +
                iris_wroom_esc(m.user_name) + '</span>' +
                (m.user_login
                    ? '<span class="iris-wr-mb-login">@' +
                      iris_wroom_esc(m.user_login) + '</span>' : '') +
                '<span class="iris-wr-mb-chip' +
                (m.role === 'lead' ? ' lead' : '') + '">' +
                iris_wroom_esc(m.role) + '</span>' +
                (removable
                    ? '<a href="#" class="iris-wr-member-remove iris-wr-nt-toolbtn" ' +
                      'data-user-id="' + m.user_id + '" title="' +
                      (m.user_id === IRIS_WROOM._myUserId && !lead
                          ? 'Leave room' : 'Remove member') +
                      '" style="color:#a04a52; margin-left:0;">' + trashIco +
                      '</a>'
                    : '') + '</div>';
        }).join('');
}

/* ------------------------------------------------------------------ teams */

var IRIS_WROOM_TM = {teams: [], hidden: {}, addFor: null};

function iris_wroom_load_teams() {
    iris_wroom_api('GET', '/teams').then(function (res) {
        if (!res.ok) return;
        IRIS_WROOM_TM.teams = res.j.teams || [];
        iris_wroom_tm_render();
    });
}

function iris_wroom_tm_render() {
    var s = IRIS_WROOM_TM;
    var canEdit = iris_wroom_can('responder') && iris_wroom_active();
    document.getElementById('iris-wr-team-newbtn').style.display =
        canEdit ? '' : 'none';
    document.getElementById('iris-wr-team-count').textContent =
        s.teams.length ? '(' + s.teams.length + ')' : '';
    document.getElementById('iris-wr-tm-empty').style.display =
        s.teams.length ? 'none' : '';
    var trash13 = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></svg>';
    var trash11 = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>';
    document.getElementById('iris-wr-tm-list').innerHTML =
        s.teams.map(function (t) {
            var hidden = s.hidden[t.id];
            var chips = '';
            if (!hidden) {
                chips = t.members.map(function (m) {
                    return '<span class="iris-wr-tm-chip">' +
                        iris_wroom_esc(m.user_name) +
                        (canEdit
                            ? '<a href="#" class="iris-wr-tm-rmmember" ' +
                              'data-team-id="' + t.id + '" data-user-id="' +
                              m.user_id + '" title="Remove from team">' +
                              trash11 + '</a>'
                            : '') + '</span>';
                }).join('');
                if (s.addFor === t.id) {
                    var inTeam = {};
                    t.members.forEach(function (m) {
                        inTeam[m.user_id] = true; });
                    var opts = ((IRIS_WROOM._room
                        && IRIS_WROOM._room.members) || [])
                        .filter(function (m) { return !inTeam[m.user_id]; })
                        .map(function (m) {
                            return '<option value="' + m.user_id + '">' +
                                iris_wroom_esc(m.user_name) + '</option>';
                        }).join('');
                    chips += '<span class="iris-wr-tm-chip" style="padding:1px 6px;">' +
                        '<select class="iris-wr-tm-addsel" data-team-id="' +
                        t.id + '" style="background:transparent; border:0; ' +
                        'color:#c8c8d0; font-size:0.74rem; outline:none;">' +
                        '<option value="">Add member&hellip;</option>' + opts +
                        '</select></span>';
                }
            }
            return '<div class="iris-wr-tm-row" data-team-id="' + t.id + '">' +
                '<div class="iris-wr-tm-head">' +
                '<span class="iris-wr-tm-dot" style="background:' +
                iris_wroom_tl_color(t.color) + ';"></span>' +
                '<span class="iris-wr-tm-name">@' + iris_wroom_esc(t.name) +
                '</span>' +
                '<span class="iris-wr-tm-sub">' + t.members.length +
                ' member' + (t.members.length === 1 ? '' : 's') + '</span>' +
                '<span class="ml-auto" style="display:inline-flex; gap:14px; align-items:center;">' +
                '<a href="#" class="iris-wr-tm-act iris-wr-tm-hide" ' +
                'data-team-id="' + t.id + '">' + (hidden ? 'Show' : 'Hide') +
                '</a>' +
                (canEdit
                    ? '<a href="#" class="iris-wr-tm-act iris-wr-tm-add" ' +
                      'data-team-id="' + t.id + '">+ Add</a>' +
                      '<a href="#" class="iris-wr-tm-act iris-wr-tm-del" ' +
                      'data-team-id="' + t.id + '" title="Delete team" ' +
                      'style="color:#a04a52;">' + trash13 + '</a>'
                    : '') +
                '</span></div>' +
                (t.description
                    ? '<div class="iris-wr-tm-desc">' +
                      iris_wroom_esc(t.description) + '</div>'
                    : '') +
                '<div>' + chips + '</div></div>';
        }).join('');
}

var IRIS_WROOM_CS = {q: '', state: '', tasks: '', noteEdit: null};

function iris_wroom_cs_visible() {
    var cases = (IRIS_WROOM._room && IRIS_WROOM._room.cases) || [];
    var f = IRIS_WROOM_CS;
    return cases.filter(function (c) {
        if (f.state === 'open' && c.closed) return false;
        if (f.state === 'closed' && !c.closed) return false;
        if (f.tasks === 'open' && !(c.tasks_open > 0)) return false;
        if (f.tasks === 'none' && (!c.accessible || c.tasks_open > 0))
            return false;
        if (f.q) {
            var hay = ('#' + c.case_id + ' ' + (c.case_name || '') + ' ' +
                (c.client_name || '') + ' ' + (c.owner_name || '') + ' ' +
                (c.note || '')).toLowerCase();
            if (hay.indexOf(f.q) === -1) return false;
        }
        return true;
    });
}

function iris_wroom_render_cases() {
    var cases = (IRIS_WROOM._room && IRIS_WROOM._room.cases) || [];
    document.getElementById('iris-wr-case-count').textContent =
        '(' + cases.length + ')';
    var responder = iris_wroom_can('responder') && iris_wroom_active();
    document.getElementById('iris-wr-case-attachbtn').style.display =
        responder ? '' : 'none';
    var visible = iris_wroom_cs_visible();
    document.getElementById('iris-wr-cs-counter').textContent =
        visible.length + '/' + cases.length;
    document.getElementById('iris-wr-cs-empty').style.display =
        cases.length ? 'none' : '';
    var extIco = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>';
    var trashIco = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></svg>';
    var pencilIco = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/></svg>';
    document.getElementById('iris-wr-cs-list').innerHTML =
        visible.map(function (c) {
            var meta = [];
            if (c.client_name) meta.push(iris_wroom_esc(c.client_name));
            if (c.owner_name) meta.push(iris_wroom_esc(c.owner_name));
            if (c.open_date) {
                meta.push('Opened ' + iris_wroom_esc(c.open_date));
            }
            if (c.accessible && c.tasks_total !== undefined) {
                meta.push(c.tasks_open + '/' + c.tasks_total + ' open');
            }
            var noteLine;
            if (IRIS_WROOM_CS.noteEdit === c.case_id) {
                noteLine = '<div class="iris-wr-cs-note iris-wr-nt-inline" ' +
                    'style="display:flex; gap:6px; max-width:420px;">' +
                    '<input type="text" maxlength="500" value="' +
                    iris_wroom_esc(c.note || '') +
                    '" placeholder="Attachment note" data-case-id="' +
                    c.case_id + '"></div>';
            } else {
                noteLine = '<div class="iris-wr-cs-note">' +
                    (c.note ? 'Note: ' + iris_wroom_esc(c.note) : '') +
                    (responder
                        ? ' <a href="#" class="iris-wr-cs-noteedit" ' +
                          'data-case-id="' + c.case_id + '" title="' +
                          (c.note ? 'Edit note' : 'Add note') +
                          '" style="color:#7a7a85;">' + pencilIco +
                          (c.note ? '' : ' add note') + '</a>'
                        : '') + '</div>';
            }
            var stateChip = c.accessible
                ? '<span class="iris-wr-cs-state' + (c.closed ? ' closed' : '')
                  + '">' + iris_wroom_esc(c.closed ? 'Closed'
                      : (c.state_name || 'Open')) + '</span>'
                : ' <span class="text-muted" title="You do not have access to this case">&#128274;</span>';
            return '<div class="iris-wr-cs-row" data-case-id="' + c.case_id +
                '" data-accessible="' + (c.accessible ? '1' : '0') + '">' +
                '<div style="flex:1 1 auto; min-width:0;">' +
                '<div><span class="iris-wr-cs-name">#' + c.case_id + ' - ' +
                iris_wroom_esc(c.case_name || '') + '</span>' + stateChip +
                '</div>' +
                '<div class="iris-wr-cs-meta">' + meta.join(' · ') + '</div>' +
                noteLine + '</div>' +
                '<span class="iris-wr-cs-acts">' +
                (c.accessible
                    ? '<a href="/case?cid=' + c.case_id +
                      '" class="iris-wr-nt-toolbtn" title="Open case" ' +
                      'style="margin-left:0;">' + extIco + '</a>'
                    : '') +
                (responder
                    ? '<a href="#" class="iris-wr-cs-detach iris-wr-nt-toolbtn" ' +
                      'data-case-id="' + c.case_id + '" title="Detach case" ' +
                      'style="margin-left:0; color:#a04a52;">' + trashIco +
                      '</a>'
                    : '') + '</span></div>';
        }).join('');
    var inline = document.querySelector('#iris-wr-cs-list .iris-wr-nt-inline input');
    if (inline) { inline.focus(); inline.select(); }

    /* Left-rail case rows render in iris_wroom_render_rail(). */
    iris_wroom_render_rail();
}

function iris_wroom_cs_peek(caseId) {
    iris_wroom_api('GET', '/cases/' + caseId + '/peek').then(function (res) {
        if (!res.ok) return;
        var p = res.j;
        document.getElementById('iris-wr-pk-eyebrow').textContent =
            'CASE #' + p.case_id + (p.soc_id ? ' · SOC ' + p.soc_id : '');
        document.getElementById('iris-wr-pk-title').textContent =
            '#' + p.case_id + ' - ' + (p.name || '');
        var setv = function (id, val) {
            document.getElementById(id).textContent = val || '—';
        };
        setv('iris-wr-pk-state', p.close_date ? 'Closed'
            : (p.state_name || 'Open'));
        setv('iris-wr-pk-sev', p.severity_name);
        setv('iris-wr-pk-cust', p.client_name);
        setv('iris-wr-pk-owner', p.owner_name);
        setv('iris-wr-pk-opened', p.open_date);
        setv('iris-wr-pk-closed', p.close_date || 'Still open');
        setv('iris-wr-pk-reviewer', p.reviewer_name || 'Unassigned');
        document.getElementById('iris-wr-pk-tags').innerHTML =
            (p.tags && p.tags.length)
                ? p.tags.map(function (t) {
                    return '<span class="iris-wr-tl-chip iris-wr-tl-chip-tag">' +
                        iris_wroom_esc(t) + '</span>';
                }).join(' ')
                : '<span class="text-muted">none</span>';
        document.getElementById('iris-wr-pk-summary').innerHTML =
            p.description_html
            || '<div class="iris-wr-nt-hintline">No description on this case.</div>';
        document.getElementById('iris-wr-pk-open')
            .setAttribute('href', '/case?cid=' + p.case_id);
        $('#iris-wr-cspeek-modal').modal('show');
    });
}

function iris_wroom_load_room() {
    return iris_wroom_api('GET', '').then(function (res) {
        if (!res.ok) {
            document.getElementById('iris-wr-name').textContent =
                'Room not found — or you are not a member.';
            return null;
        }
        IRIS_WROOM._room = res.j;
        IRIS_WROOM._myUserId = res.j.viewer_id;
        iris_wroom_render_header();
        iris_wroom_render_members();
        iris_wroom_render_cases();
        return res.j;
    });
}

/* ------------------------------------------------------------------ chat */

function iris_wroom_lane_of(i) {
    if (i.kind === 'message') {
        if (i.msg_kind === 'note' || i.msg_kind === 'decision' || i.pinned)
            return 'notes_pins';
        return 'message';
    }
    if (i.kind === 'poll') return 'message';   /* polls ride the Messages lane */
    return i.kind;   /* task_event / sitrep / system / case_link / case_activity */
}

/* #resource tokens: #[type:case_id:object_id|title] inserted by the picker,
 * rendered as linked chips. Runs on the ESCAPED text, so title content is
 * already safe. */
var IRIS_WROOM_RES_URLS = {
    event: '/case?cid=', ioc: '/case/ioc?cid=',
    asset: '/case/assets?cid=', task: '/case/tasks?cid='
};

function iris_wroom_render_body(content) {
    var esc = iris_wroom_esc(content);
    return esc.replace(
        /#\[(event|ioc|asset|task):(\d+):(\d+)\|([^\]]{1,120})\]/g,
        function (_, type, cid, oid, title) {
            return '<a class="iris-wr-res-chip" href="' +
                IRIS_WROOM_RES_URLS[type] + cid + '" title="' + type +
                ' in case #' + cid + '">' + title + '</a>';
        });
}

function iris_wroom_visible_stream() {
    return IRIS_WROOM._stream.filter(function (i) {
        if (i.kind === 'case_activity') {
            /* Filtered via the per-case sub-lanes, not a top lane. */
            var lanes = IRIS_WROOM._caseLanes[i.case_id];
            if (lanes && lanes.__all === false) return false;
            if (lanes && lanes[iris_wroom_classify(i.content)] === false)
                return false;
        } else if (i.kind === 'case_link' && i.case_id) {
            var cl = IRIS_WROOM._caseLanes[i.case_id];
            if (cl && cl.__all === false) return false;
            if (!IRIS_WROOM._lanes.case_link) return false;
        } else if (!IRIS_WROOM._lanes[iris_wroom_lane_of(i)]) {
            return false;
        }
        if (i.kind === 'message') {
            if (IRIS_WROOM._topicSel !== null
                    && !IRIS_WROOM._topicSel.has(i.topic || 'main'))
                return false;
            if (IRIS_WROOM._threadSel !== null) {
                var root = i.parent_id || (i.thread_title ? i.id : null);
                if (root !== null && !IRIS_WROOM._threadSel.has(root))
                    return false;
            }
        }
        if (IRIS_WROOM._chatQ) {
            var hay = ((i.content || '') + ' ' + (i.user_name || '') + ' '
                + (i.thread_title || '')).toLowerCase();
            if (hay.indexOf(IRIS_WROOM._chatQ) === -1) return false;
        }
        return true;
    });
}

/* ------------------------------------------------------------- left rail */

function iris_wroom_render_rail() {
    var msgs = IRIS_WROOM._stream.filter(function (i) {
        return i.kind === 'message';
    });

    /* Topics */
    var tbox = document.getElementById('iris-wr-rail-topics');
    tbox.innerHTML = '';
    IRIS_WROOM._topics.forEach(function (t) {
        var checked = IRIS_WROOM._topicSel === null
            || IRIS_WROOM._topicSel.has(t);
        var row = document.createElement('div');
        row.className = 'iris-wr-railrow';
        row.innerHTML = '<span class="iris-wr-railtxt"># ' +
            iris_wroom_esc(t === 'main' ? 'Main' : t) + '</span>' +
            '<input type="checkbox" class="iris-wr-railtopic" data-topic="' +
            iris_wroom_esc(t) + '"' + (checked ? ' checked' : '') + '>';
        tbox.appendChild(row);
    });

    /* Threads: roots = named threads or messages with replies. */
    var rootIds = {};
    msgs.forEach(function (m) {
        if (m.thread_title) rootIds[m.id] = m.thread_title;
        if (m.parent_id) {
            if (!rootIds[m.parent_id])
                rootIds[m.parent_id] = m.parent_snippet || ('#' + m.parent_id);
        }
    });
    var roots = Object.keys(rootIds);
    document.getElementById('iris-wr-thread-count').textContent = roots.length;
    document.getElementById('iris-wr-thread-hint').style.display =
        roots.length ? 'none' : '';
    var thbox = document.getElementById('iris-wr-rail-threads');
    thbox.innerHTML = '';
    roots.forEach(function (rid) {
        var checked = IRIS_WROOM._threadSel === null
            || IRIS_WROOM._threadSel.has(parseInt(rid, 10));
        var row = document.createElement('div');
        row.className = 'iris-wr-railrow';
        row.innerHTML = '<span class="iris-wr-railtxt" title="' +
            iris_wroom_esc(rootIds[rid]) + '">&#128172; ' +
            iris_wroom_esc(String(rootIds[rid]).slice(0, 26)) + '</span>' +
            '<input type="checkbox" class="iris-wr-railthread" ' +
            'data-root-id="' + rid + '"' + (checked ? ' checked' : '') + '>';
        thbox.appendChild(row);
    });

    /* Decisions & pins counter */
    var dp = msgs.filter(function (m) {
        return m.msg_kind === 'decision' || m.pinned;
    }).length;
    document.getElementById('iris-wr-dp-count').textContent = dp;

    /* Stream lanes */
    var lbox = document.getElementById('iris-wr-rail-lanes');
    lbox.innerHTML = '';
    IRIS_WROOM_LANES.forEach(function (lane) {
        var row = document.createElement('div');
        row.className = 'iris-wr-railrow';
        row.innerHTML = '<span class="iris-wr-railtxt">' + lane[1] + '</span>' +
            '<input type="checkbox" class="iris-wr-lane" data-kind="' +
            lane[0] + '"' + (IRIS_WROOM._lanes[lane[0]] ? ' checked' : '') + '>';
        lbox.appendChild(row);
    });

    /* Per-case sub-lanes */
    var cases = (IRIS_WROOM._room && IRIS_WROOM._room.cases) || [];
    document.getElementById('iris-wr-rail-case-count').textContent =
        cases.length;
    var cbox = document.getElementById('iris-wr-rail-cases');
    cbox.innerHTML = '';
    cases.forEach(function (c) {
        var lanes = IRIS_WROOM._caseLanes[c.case_id] || {};
        var open = !!IRIS_WROOM._caseOpen[c.case_id];
        var row = document.createElement('div');
        row.innerHTML =
            '<div class="iris-wr-railrow">' +
            '<span class="iris-wr-chev iris-wr-case-chev" data-case-id="' +
            c.case_id + '">' + (open ? '&#9662;' : '&#9656;') + '</span>' +
            '<span class="iris-wr-railtxt" title="' +
            iris_wroom_esc(c.case_name) + '">#' + c.case_id + ' - ' +
            iris_wroom_esc(c.case_name) + '</span>' +
            '<input type="checkbox" class="iris-wr-railcase" data-case-id="' +
            c.case_id + '"' + (lanes.__all === false ? '' : ' checked') + '>' +
            '</div>' +
            '<div class="iris-wr-sublanes' + (open ? ' open' : '') +
            '" data-case-id="' + c.case_id + '">' +
            IRIS_WROOM_SUBLANES.map(function (sl) {
                return '<div class="iris-wr-railrow">' +
                    '<span class="iris-wr-railtxt">' + sl[1] + '</span>' +
                    '<input type="checkbox" class="iris-wr-railsub" ' +
                    'data-case-id="' + c.case_id + '" data-sublane="' + sl[0] +
                    '"' + (lanes[sl[0]] === false ? '' : ' checked') + '></div>';
            }).join('') + '</div>';
        cbox.appendChild(row);
    });

    /* Slash-command catalog */
    var cmd = document.getElementById('iris-wr-cmdlist');
    if (!cmd.childElementCount) {
        cmd.innerHTML = IRIS_WROOM_COMMANDS.map(function (c) {
            return '<div><code>' + iris_wroom_esc(c[0]) + '</code>' +
                '<div class="iris-wr-cmddesc">' + iris_wroom_esc(c[1]) +
                '</div></div>';
        }).join('');
    }
}

function iris_wroom_render_chat() {
    var box = document.getElementById('iris-wr-chat');
    var stick = (box.scrollHeight - box.scrollTop - box.clientHeight) < 80
        || box.childElementCount === 0;
    /* v3 chat is chronological: oldest at top, composer at the bottom. */
    var items = iris_wroom_visible_stream().slice().reverse();
    document.getElementById('iris-wr-stream-empty').style.display =
        items.length ? 'none' : '';
    box.innerHTML = '';
    var lastDate = '';
    items.forEach(function (i) {
        var d = i.created_at ? new Date(i.created_at) : null;
        var dateKey = d ? ((d.getMonth() + 1) + '/' + d.getDate() + '/' +
            d.getFullYear()) : '';
        if (dateKey && dateKey !== lastDate) {
            lastDate = dateKey;
            var sep = document.createElement('div');
            sep.className = 'iris-wr-datesep';
            sep.innerHTML = '<span>' + dateKey + '</span>';
            box.appendChild(sep);
        }
        var mnames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug',
                      'Sep', 'Oct', 'Nov', 'Dec'];
        var time = d ? (mnames[d.getMonth()] + ' ' + d.getDate() + ', ' +
            d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'}))
            : '';
        var div = document.createElement('div');
        if (i.kind === 'message') {
            div.className = 'iris-wr-msgrow';
            if (i.msg_kind === 'decision') div.className += ' iris-wr-kind-decision';
            if (i.msg_kind === 'note') div.className += ' iris-wr-kind-note';
            if (i.parent_id) div.className += ' iris-wr-reply';
            var head = '<strong>' + iris_wroom_esc(i.user_name) + '</strong>' +
                '<span class="iris-wr-msg-time">' + time + '</span>' +
                (i.pinned ? ' <span title="Pinned">&#128204;</span>' : '') +
                (i.msg_kind === 'decision'
                    ? ' <span class="iris-wr-thread-badge">decision</span>' : '') +
                (i.msg_kind === 'note'
                    ? ' <span class="iris-wr-thread-badge">note</span>' : '') +
                (i.thread_title
                    ? ' <span class="iris-wr-thread-badge"># ' +
                      iris_wroom_esc(i.thread_title) + '</span>' : '') +
                (i.topic && i.topic !== 'main'
                    ? ' <span class="iris-wr-thread-badge">#' +
                      iris_wroom_esc(i.topic) + '</span>' : '');
            var replyRef = i.parent_id
                ? '<div class="iris-wr-reply-ref">&#8618; replying to ' +
                  iris_wroom_esc(i.parent_snippet || 'a message') + '</div>'
                : '';
            var actions = (iris_wroom_can('responder') && iris_wroom_active())
                ? '<div class="iris-wr-msg-actions">' +
                  '<a href="#" class="iris-wr-act-reply" data-msg-id="' + i.id +
                  '" data-snippet="' + iris_wroom_esc(
                      (i.thread_title || i.content || '').slice(0, 40)) +
                  '">Reply</a>' +
                  '<a href="#" class="iris-wr-act-pin" data-msg-id="' + i.id +
                  '" data-pinned="' + (i.pinned ? '1' : '0') + '">' +
                  (i.pinned ? 'Unpin' : 'Pin') + '</a></div>'
                : '';
            div.innerHTML = iris_wroom_avatar(i.user_name) +
                '<div style="min-width:0; flex:1 1 auto;">' + replyRef +
                '<div class="iris-wr-msg-head">' + head + '</div>' +
                '<div class="iris-wr-msg-body">' +
                iris_wroom_render_body(i.content) +
                '</div></div>' + actions;
        } else if (i.kind === 'poll' && i.poll) {
            div.innerHTML = iris_wroom_render_poll(i.poll, time);
        } else {
            div.className = 'iris-wr-sysrow';
            var icon = {system: '&#9881;', sitrep: '&#128196;',
                        task_event: '&#9989;', case_link: '&#128279;',
                        case_activity: '&#9679;'}[i.kind] || '&#9881;';
            div.innerHTML = icon + ' ' + iris_wroom_esc(i.content) +
                (i.case_id ? '<span class="iris-wr-case-chip">' +
                    '<a href="/case?cid=' + i.case_id + '">Case #' +
                    i.case_id + '</a></span>' : '') +
                '<span class="iris-wr-msg-time"' +
                (i.case_id ? '' : ' style="margin-left:auto;"') + '>' +
                time + '</span>';
        }
        box.appendChild(div);
    });
    if (stick) box.scrollTop = box.scrollHeight;
    iris_wroom_render_rail();
}

function iris_wroom_load_stream() {
    iris_wroom_api('GET', '/stream?limit=200').then(function (res) {
        if (!res.ok) return;
        IRIS_WROOM._stream = res.j.stream || [];
        IRIS_WROOM._topics = res.j.topics || ['main'];
        iris_wroom_render_chat();
    });
}

/* ------------------------------------------------------------------ polls */

function iris_wroom_render_poll(p, time) {
    var total = Math.max.apply(null, [1].concat(p.options.map(function (o) {
        return o.count; })));
    var canVote = !p.closed && IRIS_WROOM._room && IRIS_WROOM._room.my_role;
    var opts = p.options.map(function (o) {
        var pct = p.total_voters
            ? Math.round(100 * o.count / Math.max(1, p.total_voters)) : 0;
        var voters = (!p.anonymous && o.voters.length)
            ? '<div class="iris-wr-poll-voters">' +
              iris_wroom_esc(o.voters.join(', ')) + '</div>' : '';
        return '<div><div class="iris-wr-poll-opt' +
            (o.voted ? ' voted' : '') + (p.closed ? ' closed' : '') +
            '" data-poll-id="' + p.id + '" data-option-id="' + o.id + '">' +
            '<div class="iris-wr-poll-bar" style="width:' +
            Math.round(100 * o.count / total) + '%;"></div>' +
            '<span>' + (o.voted ? '&#9745;' : '&#9744;') + '</span>' +
            '<span style="flex:1 1 auto; min-width:0;">' +
            iris_wroom_esc(o.text) + '</span>' +
            '<span>' + o.count + (p.total_voters
                ? ' · ' + pct + '%' : '') + '</span>' +
            '</div>' + voters + '</div>';
    }).join('');
    var closeLink = (!p.closed
        && (iris_wroom_can('lead') || p.created_by === IRIS_WROOM._myUserId))
        ? ' · <a href="#" class="iris-wr-poll-close" data-poll-id="' + p.id +
          '">Close poll</a>' : '';
    return '<div class="iris-wr-pollcard">' +
        '<div class="iris-wr-poll-q">&#128202; ' + iris_wroom_esc(p.question) +
        (p.closed ? ' <span class="iris-wr-thread-badge">closed</span>' : '') +
        (p.multiple ? ' <span class="iris-wr-poll-voters">(multiple choice)</span>' : '') +
        '</div>' + opts +
        '<div class="iris-wr-poll-meta">' +
        iris_wroom_esc(p.created_by_name || '') + ' · ' + time + ' · ' +
        p.total_voters + ' voter' + (p.total_voters === 1 ? '' : 's') +
        (p.anonymous ? ' · anonymous' : '') +
        (p.closes_at && !p.closed
            ? ' · closes ' + iris_wroom_rel(p.closes_at).replace(' ago', '')
            : '') +
        closeLink + '</div></div>';
}

function iris_wroom_poll_modal_reset() {
    document.getElementById('iris-wr-poll-question').value = '';
    document.getElementById('iris-wr-poll-multiple').checked = false;
    document.getElementById('iris-wr-poll-anon').checked = false;
    document.getElementById('iris-wr-poll-autoclose').checked = false;
    document.getElementById('iris-wr-poll-closes').style.display = 'none';
    document.getElementById('iris-wr-poll-closes').value = '';
    document.getElementById('iris-wr-poll-error').style.display = 'none';
    var box = document.getElementById('iris-wr-poll-options');
    box.innerHTML = '';
    iris_wroom_poll_add_option();
    iris_wroom_poll_add_option();
}

function iris_wroom_poll_add_option() {
    var box = document.getElementById('iris-wr-poll-options');
    if (box.childElementCount >= 20) return;
    var n = box.childElementCount + 1;
    var row = document.createElement('div');
    row.className = 'd-flex align-items-center mb-1 iris-wr-poll-optrow';
    row.innerHTML =
        '<input type="text" class="form-control form-control-sm iris-wr-poll-optinput" ' +
        'placeholder="Option ' + n + '" maxlength="200">' +
        '<a href="#" class="iris-wr-poll-optdel ml-2 text-muted">&times;</a>';
    box.appendChild(row);
    document.getElementById('iris-wr-poll-optcount').textContent =
        box.childElementCount;
}

/* ---------------------------------------------------------- resource pick */

var IRIS_WROOM_RES = {tab: 'event', caseId: null, q: '', cache: {}};

function iris_wroom_res_render(items) {
    var pop = document.getElementById('iris-wr-resource-pop');
    var list = pop.querySelector('.iris-wr-res-list');
    var q = IRIS_WROOM_RES.q;
    var shown = items.filter(function (it) {
        return !q || it.title.toLowerCase().indexOf(q) !== -1;
    }).slice(0, 100);
    list.innerHTML = shown.length ? '' :
        '<div class="text-muted" style="font-size:0.78rem;">Nothing found.</div>';
    shown.forEach(function (it) {
        var div = document.createElement('div');
        div.className = 'iris-wr-res-item';
        div.setAttribute('data-token', '#[' + IRIS_WROOM_RES.tab + ':' +
            IRIS_WROOM_RES.caseId + ':' + it.id + '|' +
            it.title.replace(/[\[\]|]/g, ' ').slice(0, 80) + ']');
        div.innerHTML = '<div>' + iris_wroom_esc(it.title) + '</div>' +
            (it.sub ? '<div class="iris-wr-res-sub">' +
             iris_wroom_esc(it.sub) + '</div>' : '');
        list.appendChild(div);
    });
}

function iris_wroom_res_load() {
    var tab = IRIS_WROOM_RES.tab;
    var cid = IRIS_WROOM_RES.caseId;
    if (!cid) { iris_wroom_res_render([]); return; }
    var key = tab + ':' + cid;
    if (IRIS_WROOM_RES.cache[key]) {
        iris_wroom_res_render(IRIS_WROOM_RES.cache[key]);
        return;
    }
    var done = function (items) {
        IRIS_WROOM_RES.cache[key] = items;
        iris_wroom_res_render(items);
    };
    if (tab === 'event') {
        iris_wroom_api('GET', '/timeline?limit=500').then(function (res) {
            done((res.ok ? res.j.events : []).filter(function (e) {
                return e.case_id === cid;
            }).map(function (e) {
                return {id: e.event_id, title: e.event_title || '(untitled)',
                        sub: (e.event_date || '').replace('T', ' ')};
            }));
        });
    } else if (tab === 'task') {
        iris_wroom_api('GET', '/tasks?limit=500').then(function (res) {
            done((res.ok ? res.j.tasks : []).filter(function (t) {
                return t.case_id === cid;
            }).map(function (t) {
                return {id: t.task_id, title: t.task_title || '(untitled)',
                        sub: t.status_name || ''};
            }));
        });
    } else if (tab === 'ioc') {
        /* Legacy endpoint — {status,data} envelope, data.ioc list. */
        fetch('/case/ioc/list?cid=' + cid,
              {headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.ok ? r.json() : {data: {}}; })
            .then(function (resp) {
                var rows = (resp.data && resp.data.ioc) || [];
                done(rows.map(function (io) {
                    return {id: io.ioc_id, title: io.ioc_value || '',
                            sub: (io.ioc_type ? (io.ioc_type.type_name
                                  || io.ioc_type) : '')};
                }));
            });
    } else if (tab === 'asset') {
        fetch('/case/assets/list?cid=' + cid,
              {headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.ok ? r.json() : {data: {}}; })
            .then(function (resp) {
                var rows = (resp.data && resp.data.assets) || [];
                done(rows.map(function (a) {
                    return {id: a.asset_id, title: a.asset_name || '',
                            sub: (a.asset_type ? (a.asset_type.asset_name
                                  || a.asset_type) : '')};
                }));
            });
    }
}

function iris_wroom_res_open() {
    var pop = document.getElementById('iris-wr-resource-pop');
    var cases = ((IRIS_WROOM._room && IRIS_WROOM._room.cases) || [])
        .filter(function (c) { return c.accessible; });
    pop.innerHTML =
        '<div class="iris-wr-res-tabs">' +
        [['event', 'Events'], ['ioc', 'IOCs'], ['asset', 'Assets'],
         ['task', 'Tasks']].map(function (t) {
            return '<button type="button" class="iris-wr-res-tab' +
                (IRIS_WROOM_RES.tab === t[0] ? ' active' : '') +
                '" data-tab="' + t[0] + '">' + t[1] + '</button>';
        }).join('') + '</div>' +
        '<div style="font-size:0.68rem; letter-spacing:0.06em; text-transform:uppercase; color:#7a7a85;">Case</div>' +
        '<select class="form-control form-control-sm iris-wr-res-case mb-1">' +
        (cases.length ? cases.map(function (c) {
            return '<option value="' + c.case_id + '">#' + c.case_id +
                ' — ' + iris_wroom_esc(c.case_name) + '</option>';
        }).join('') : '<option value="">No accessible cases attached</option>') +
        '</select>' +
        '<input type="text" class="form-control form-control-sm iris-wr-res-search" placeholder="Search...">' +
        '<div class="iris-wr-res-list"></div>';
    IRIS_WROOM_RES.caseId = cases.length ? cases[0].case_id : null;
    IRIS_WROOM_RES.q = '';
    pop.style.display = 'block';
    iris_wroom_res_load();
}

/* ------------------------------------------------- composer + commands */

function iris_wroom_cmd_status(txt) {
    document.getElementById('iris-wr-cmd-status').textContent = txt || '';
}

function iris_wroom_set_target(target) {
    IRIS_WROOM._target = target;
    var chip = document.getElementById('iris-wr-post-target');
    var clear = document.getElementById('iris-wr-target-clear');
    if (target.mode === 'topic') {
        chip.textContent = '# ' + (target.topic === 'main'
            ? 'Main' : target.topic);
        clear.style.display = target.topic === 'main' ? 'none' : '';
    } else {
        chip.textContent = '↪ ' + (target.label || 'thread');
        clear.style.display = '';
    }
}

function iris_wroom_post(fields, keepTarget) {
    return iris_wroom_api('POST', '/messages', fields).then(function (res) {
        if (res.ok) {
            document.getElementById('iris-wr-msg-input').value = '';
            /* A one-off reply resets to # Main; a named-thread target
             * (persistent) keeps receiving messages until cleared. */
            if (!keepTarget && IRIS_WROOM._target.mode === 'reply'
                    && !IRIS_WROOM._target.persistent) {
                iris_wroom_set_target({mode: 'topic', topic: 'main'});
            }
            iris_wroom_load_stream();
        } else {
            iris_wroom_cmd_status(res.j.message || 'Failed');
        }
        return res;
    });
}

function iris_wroom_resolve_user(login) {
    var l = (login || '').replace(/^@/, '').toLowerCase();
    var u = IRIS_WROOM._users.find(function (x) {
        return (x.user_login || '').toLowerCase() === l
            || (x.user_name || '').toLowerCase() === l;
    });
    return u ? u.user_id : null;
}

/* ---- @-mention autocomplete -------------------------------------------
 * Candidates are ROOM MEMBERS (by login — logins can be full email
 * addresses) plus the room's @-mention TEAMS (by slug), which is exactly
 * the set the mention machinery notifies. The token detector walks back to
 * the last whitespace, NOT the last '@' — an email-shaped login contains
 * its own '@' and must not break the palette mid-completion. */

var IRIS_WROOM_MENTION = {open: false, items: [], idx: 0, start: -1};

function iris_wroom_mention_candidates() {
    var out = [];
    (((IRIS_WROOM._room || {}).members) || []).forEach(function (m) {
        if (m.user_login) {
            out.push({login: m.user_login, label: m.user_name || '',
                      kind: 'member'});
        }
    });
    ((IRIS_WROOM_TM || {}).teams || []).forEach(function (t) {
        out.push({login: t.name,
                  label: (t.members || []).length + ' member'
                      + ((t.members || []).length === 1 ? '' : 's'),
                  kind: 'team'});
    });
    return out;
}

function iris_wroom_mention_ctx() {
    var input = document.getElementById('iris-wr-msg-input');
    var pos = input.selectionStart;
    var before = input.value.slice(0, pos);
    var ws = Math.max(before.lastIndexOf(' '), before.lastIndexOf('\n'),
                      before.lastIndexOf('\t'));
    var token = before.slice(ws + 1);
    if (token.charAt(0) !== '@') { return null; }
    return {at: ws + 1, frag: token.slice(1), pos: pos};
}

function iris_wroom_mention_render() {
    var pop = document.getElementById('iris-wr-mention-pop');
    var s = IRIS_WROOM_MENTION;
    if (!s.open || !s.items.length) {
        s.open = false;
        pop.style.display = 'none';
        return;
    }
    pop.innerHTML = s.items.map(function (it, i) {
        return '<div class="iris-wr-cmd-opt' + (i === s.idx ? ' active' : '')
            + '" data-i="' + i + '"><code>@' + iris_wroom_esc(it.login)
            + '</code> <span class="text-muted">' + iris_wroom_esc(it.label)
            + (it.kind === 'team' ? ' · team' : '') + '</span></div>';
    }).join('');
    pop.style.display = '';
}

function iris_wroom_mention_update() {
    var s = IRIS_WROOM_MENTION;
    var ctx = iris_wroom_mention_ctx();
    if (!ctx) {
        s.open = false;
        iris_wroom_mention_render();
        return;
    }
    var q = ctx.frag.toLowerCase();
    var items = iris_wroom_mention_candidates().filter(function (it) {
        return it.login.toLowerCase().indexOf(q) !== -1
            || it.label.toLowerCase().indexOf(q) !== -1;
    });
    items.sort(function (a, b) {
        var ap = a.login.toLowerCase().indexOf(q) === 0 ? 0 : 1;
        var bp = b.login.toLowerCase().indexOf(q) === 0 ? 0 : 1;
        return (ap - bp) || a.login.localeCompare(b.login);
    });
    s.items = items.slice(0, 8);
    s.idx = 0;
    s.start = ctx.at;
    s.open = s.items.length > 0;
    iris_wroom_mention_render();
}

function iris_wroom_mention_complete(i) {
    var s = IRIS_WROOM_MENTION;
    var it = s.items[i === undefined ? s.idx : i];
    if (!it) { return; }
    var input = document.getElementById('iris-wr-msg-input');
    var v = input.value;
    input.value = v.slice(0, s.start) + '@' + it.login + ' '
        + v.slice(input.selectionStart);
    var np = s.start + it.login.length + 2;
    input.setSelectionRange(np, np);
    s.open = false;
    iris_wroom_mention_render();
    input.focus();
}

function iris_wroom_run_command(line) {
    var m = line.match(/^\/(\S+)\s*(.*)$/);
    var cmd = m[1].toLowerCase();
    var arg = (m[2] || '').trim();
    var t = IRIS_WROOM._target;
    var base = t.mode === 'topic' ? {topic: t.topic} : {parent_id: t.parentId};

    function need(what) { iris_wroom_cmd_status('Usage: ' + what); }

    switch (cmd) {
    case 'note':
        if (!arg) return need('/note <text>');
        return iris_wroom_post(Object.assign({content: arg, kind: 'note'}, base), true);
    case 'pin':
        if (!arg) return need('/pin <text> (or hover a message to pin it)');
        return iris_wroom_post(Object.assign(
            {content: arg, kind: 'note', pinned: true}, base), true);
    case 'decision':
        if (!arg) return need('/decision <text>');
        return iris_wroom_post(Object.assign(
            {content: arg, kind: 'decision'}, base), true);
    case 'attach': {
        var cid = parseInt(arg.replace('#', ''), 10);
        if (!cid) return need('/attach <case_id>');
        return iris_wroom_api('POST', '/cases', {case_id: cid})
            .then(function (res) {
                iris_wroom_cmd_status(res.ok ? 'Case #' + cid + ' attached'
                    : (res.j.message || 'Attach failed'));
                if (res.ok) {
                    document.getElementById('iris-wr-msg-input').value = '';
                    iris_wroom_load_room().then(iris_wroom_load_stream);
                }
            });
    }
    case 'detach': {
        var did = parseInt(arg.replace('#', ''), 10);
        if (!did) return need('/detach <case_id>');
        return iris_wroom_api('DELETE', '/cases/' + did).then(function (res) {
            iris_wroom_cmd_status(res.ok ? 'Case #' + did + ' detached'
                : (res.j.message || 'Detach failed'));
            if (res.ok) {
                document.getElementById('iris-wr-msg-input').value = '';
                iris_wroom_load_room().then(iris_wroom_load_stream);
            }
        });
    }
    case 'task':
    case 'assign': {
        var am = arg.match(/^@(\S+)\s+(.+)$/);
        var assignee = null, title = arg;
        if (am) {
            assignee = iris_wroom_resolve_user(am[1]);
            if (assignee === null) {
                return iris_wroom_cmd_status('Unknown user @' + am[1]);
            }
            title = am[2];
        } else if (cmd === 'assign') {
            return need('/assign @user <title>');
        }
        if (!title) return need('/task [@user] <title>');
        return iris_wroom_api('POST', '/room-tasks',
                              {title: title, assignee_id: assignee})
            .then(function (res) {
                iris_wroom_cmd_status(res.ok ? 'Room task created'
                    : (res.j.message || 'Task failed'));
                if (res.ok) {
                    document.getElementById('iris-wr-msg-input').value = '';
                    iris_wroom_load_room_tasks();
                    iris_wroom_load_stream();
                }
            });
    }
    case 'sitrep':
        if (!arg) return need('/sitrep <title>');
        return iris_wroom_api('POST', '/sitreps', {title: arg})
            .then(function (res) {
                if (res.ok) {
                    document.getElementById('iris-wr-msg-input').value = '';
                    iris_wroom_load_sitreps();
                    iris_wroom_show_pane('sitreps');
                    iris_wroom_open_sitrep(res.j.id);
                } else {
                    iris_wroom_cmd_status(res.j.message || 'SitRep failed');
                }
            });
    case 'summary':
        document.getElementById('iris-wr-msg-input').value = '';
        iris_wroom_show_pane('sitreps');
        document.getElementById('iris-wr-sitrep-ai').click();
        return;
    case 'state':
        if (['open', 'active', 'standby', 'closed'].indexOf(arg) === -1)
            return need('/state <open|active|standby|closed>');
        return iris_wroom_api('POST', '/status', {status: arg})
            .then(function (res) {
                iris_wroom_cmd_status(res.ok ? 'State: ' + arg
                    : (res.j.message || 'State change failed (lead only)'));
                if (res.ok) {
                    document.getElementById('iris-wr-msg-input').value = '';
                    iris_wroom_load_room();
                }
            });
    case 'priority':
        if (['low', 'medium', 'high', 'critical'].indexOf(arg) === -1)
            return need('/priority <low|medium|high|critical>');
        return iris_wroom_api('PUT', '', {severity: arg}).then(function (res) {
            iris_wroom_cmd_status(res.ok ? 'Severity: ' + arg
                : (res.j.message || 'Severity failed (lead only)'));
            if (res.ok) {
                document.getElementById('iris-wr-msg-input').value = '';
                iris_wroom_load_room();
            }
        });
    case 'thread':
        if (!arg) return need('/thread <title>');
        return iris_wroom_post({content: arg, thread_title: arg}, true)
            .then(function (res) {
                if (res.ok) {
                    iris_wroom_set_target({mode: 'reply', parentId: res.j.id,
                                           label: arg, persistent: true});
                    iris_wroom_cmd_status('Thread "' + arg + '" opened');
                }
            });
    case 'topic': {
        if (!arg) return need('/topic <name>');
        var name = arg.replace(/^#/, '').slice(0, 64);
        iris_wroom_set_target({mode: 'topic', topic: name});
        document.getElementById('iris-wr-msg-input').value = '';
        iris_wroom_cmd_status('Posting to # ' + name +
            ' — the topic appears once you send a message');
        return;
    }
    default:
        iris_wroom_cmd_status('Unknown command /' + cmd +
            ' — see Slash commands in the rail');
    }
}

function iris_wroom_send() {
    var input = document.getElementById('iris-wr-msg-input');
    var content = input.value.trim();
    if (!content) return;
    iris_wroom_cmd_status('');
    document.getElementById('iris-wr-cmd-pop').style.display = 'none';
    if (content.charAt(0) === '/') {
        iris_wroom_run_command(content);
        return;
    }
    var t = IRIS_WROOM._target;
    var fields = t.mode === 'topic'
        ? {content: content, topic: t.topic}
        : {content: content, parent_id: t.parentId};
    iris_wroom_post(fields, t.mode === 'reply' && t.persistent);
}

/* -------------------------------------------------------------- room tasks */

var IRIS_WROOM_RT = {
    tasks: [], q: '', fStatus: '', fAssignee: '', view: 'list',
    editing: null, parentFor: null
};

var IRIS_WROOM_RT_STATUS = {
    no_status: 'No status', todo: 'To do', in_progress: 'In progress',
    on_hold: 'On hold', done: 'Done', cancelled: 'Cancelled'
};

/* Board column dot colours (v3 palette). */
var IRIS_WROOM_RT_DOT = {
    no_status: '#7a7a85', todo: '#F25961', in_progress: '#f4c430',
    on_hold: '#9aa0b5', done: '#2dce89', cancelled: '#7a7a85'
};

function iris_wroom_rt_open_count() {
    return IRIS_WROOM_RT.tasks.filter(function (t) {
        return t.status !== 'done' && t.status !== 'cancelled';
    }).length;
}

function iris_wroom_load_room_tasks() {
    iris_wroom_api('GET', '/room-tasks').then(function (res) {
        if (!res.ok) return;
        IRIS_WROOM_RT.tasks = res.j.tasks || [];
        iris_wroom_rt_render();
    });
}

function iris_wroom_rt_visible() {
    var s = IRIS_WROOM_RT;
    return s.tasks.filter(function (t) {
        if (s.fStatus && t.status !== s.fStatus) return false;
        if (s.fAssignee && String(t.assignee_id || '') !== s.fAssignee)
            return false;
        if (s.q) {
            var hay = ((t.title || '') + ' ' + (t.description || '') + ' ' +
                (t.tags || '')).toLowerCase();
            if (hay.indexOf(s.q) === -1) return false;
        }
        return true;
    });
}

function iris_wroom_rt_row(t, isSub, canEdit) {
    var doneish = t.status === 'done' || t.status === 'cancelled';
    var due = '';
    if (t.due_date) {
        var d = new Date(t.due_date);
        var overdue = !doneish && d.getTime() < Date.now();
        due = '<span class="iris-wr-rt-due' + (overdue ? ' overdue' : '') +
            '">due ' + (d.getMonth() + 1) + '/' + d.getDate() + '</span>';
    }
    var tags = '';
    (t.tags || '').split(',').forEach(function (tg) {
        tg = tg.trim();
        if (tg) {
            tags += '<span class="iris-wr-tl-chip iris-wr-tl-chip-tag">#' +
                iris_wroom_esc(tg) + '</span>';
        }
    });
    var actions = canEdit
        ? '<div class="iris-wr-rt-actions">' +
          (!isSub ? '<a href="#" class="iris-wr-rt-addsub" data-task-id="' +
           t.id + '">+ Sub</a>' : '') +
          '<a href="#" class="iris-wr-rt-del" data-task-id="' + t.id +
          '">Delete</a></div>'
        : '';
    return '<div class="iris-wr-rt-row' + (isSub ? ' iris-wr-rt-sub' : '') +
        (doneish ? ' done-task' : '') + '" data-task-id="' + t.id + '">' +
        '<input type="checkbox" class="iris-wr-rt-toggle" data-task-id="' +
        t.id + '"' + (t.status === 'done' ? ' checked' : '') +
        (canEdit ? '' : ' disabled') + '>' +
        '<span class="iris-wr-rt-pill iris-wr-rt-pill-' + t.status + '">' +
        IRIS_WROOM_RT_STATUS[t.status] + '</span>' +
        '<span class="iris-wr-rt-title" style="flex:1 1 auto; min-width:0;">' +
        iris_wroom_esc(t.title) + ' ' + tags + '</span>' + due +
        (t.assignee_name
            ? '<span title="' + iris_wroom_esc(t.assignee_name) + '">' +
              iris_wroom_avatar(t.assignee_name) + '</span>'
            : '<span class="text-muted" style="font-size:0.7rem;">unassigned</span>') +
        actions + '</div>';
}

function iris_wroom_rt_render() {
    var s = IRIS_WROOM_RT;
    var canEdit = iris_wroom_can('responder') && iris_wroom_active();
    document.getElementById('iris-wr-rtask-new').style.display =
        canEdit ? '' : 'none';
    var open = iris_wroom_rt_open_count();
    document.getElementById('iris-wr-rtask-count').textContent =
        open ? '(' + open + ')' : '';

    var visible = iris_wroom_rt_visible();
    document.getElementById('iris-wr-rt-counter').textContent =
        'Showing ' + visible.length + ' of ' + s.tasks.length + ' tasks';

    var listBox = document.getElementById('iris-wr-rtask-list');
    var boardBox = document.getElementById('iris-wr-rtask-board');
    listBox.style.display = s.view === 'list' ? '' : 'none';
    boardBox.style.display = s.view === 'board' ? '' : 'none';

    if (s.view === 'board') {
        var cols = ['no_status', 'todo', 'in_progress', 'on_hold',
                    'done', 'cancelled'];
        var cardHtml = function (t) {
            var meta = '';
            if (t.due_date) {
                var d = new Date(t.due_date);
                var overdue = t.status !== 'done' && t.status !== 'cancelled'
                    && d.getTime() < Date.now();
                meta += '<span class="iris-wr-rt-due' +
                    (overdue ? ' overdue' : '') + '">due ' +
                    (d.getMonth() + 1) + '/' + d.getDate() + '</span>';
            }
            return '<div class="iris-wr-rt-card"' +
                (canEdit ? ' draggable="true"' : '') +
                ' data-task-id="' + t.id + '">' +
                iris_wroom_esc(t.title) +
                ((meta || t.assignee_name)
                    ? '<div class="mt-1 d-flex" style="align-items:center; gap:6px;">' +
                      meta +
                      (t.assignee_name
                          ? '<span class="ml-auto" title="' +
                            iris_wroom_esc(t.assignee_name) + '">' +
                            iris_wroom_avatar(t.assignee_name) + '</span>'
                          : '') + '</div>'
                    : '') + '</div>';
        };
        boardBox.innerHTML = '<div class="iris-wr-rt-board">' +
            cols.map(function (st) {
                var items = visible.filter(function (t) {
                    return t.status === st;
                });
                return '<div class="iris-wr-rt-col" data-status="' + st +
                    '"' + (canEdit ? ' data-droppable="1"' : '') + '>' +
                    '<div class="iris-wr-rt-colhead">' +
                    '<span class="iris-wr-rt-coldot" style="background:' +
                    IRIS_WROOM_RT_DOT[st] + ';"></span>' +
                    IRIS_WROOM_RT_STATUS[st] +
                    '<span class="iris-wr-rt-colcount">' + items.length +
                    '</span></div>' +
                    (items.length
                        ? items.map(cardHtml).join('')
                        : '<div class="iris-wr-rt-colempty">No tasks</div>') +
                    '</div>';
            }).join('') + '</div>' +
            '<div class="iris-wr-rt-boardhint">' + visible.length + ' task' +
            (visible.length === 1 ? '' : 's') + ', subtasks included' +
            (canEdit
                ? ' · Drag a card to another column to change its status.'
                : '') + '</div>';
        return;
    }

    /* List view: OPEN / DONE sections; subtasks under their parent. */
    var byParent = {};
    visible.forEach(function (t) {
        if (t.parent_task_id) {
            (byParent[t.parent_task_id] =
                byParent[t.parent_task_id] || []).push(t);
        }
    });
    var visIds = {};
    visible.forEach(function (t) { visIds[t.id] = true; });
    function renderGroup(pred, label) {
        var tops = visible.filter(function (t) {
            /* A subtask whose parent is visible renders under it. */
            if (t.parent_task_id && visIds[t.parent_task_id]) return false;
            return pred(t);
        });
        var html = '<div class="iris-wr-rt-section">' + label + ' (' +
            tops.length + ')</div>';
        if (!tops.length) {
            html += '<div class="text-muted" style="font-size:0.8rem;">No ' +
                label.toLowerCase() + ' tasks.</div>';
        }
        tops.forEach(function (t) {
            html += iris_wroom_rt_row(t, false, canEdit);
            (byParent[t.id] || []).forEach(function (sub) {
                html += iris_wroom_rt_row(sub, true, canEdit);
            });
        });
        return html;
    }
    listBox.innerHTML =
        renderGroup(function (t) {
            return t.status !== 'done' && t.status !== 'cancelled';
        }, 'Open') +
        renderGroup(function (t) {
            return t.status === 'done' || t.status === 'cancelled';
        }, 'Done');
}

function iris_wroom_rt_open_modal(editing, parentFor) {
    IRIS_WROOM_RT.editing = editing || null;
    IRIS_WROOM_RT.parentFor = parentFor || null;
    var hint = document.getElementById('iris-wr-rtask-parenthint');
    hint.style.display = 'none';
    document.getElementById('iris-wr-rtask-f-error').style.display = 'none';
    document.getElementById('iris-wr-rtask-f-delete').style.display =
        editing ? '' : 'none';
    document.getElementById('iris-wr-rtask-f-save').textContent =
        editing ? 'Save' : 'Create';
    document.getElementById('iris-wr-rtask-modal-title').textContent =
        editing ? 'Edit task' : (parentFor ? 'New subtask' : 'New task');
    if (parentFor) {
        var parent = IRIS_WROOM_RT.tasks.find(function (t) {
            return t.id === parentFor; });
        if (parent) {
            hint.textContent = 'Subtask of: ' + parent.title;
            hint.style.display = '';
        }
    }
    var t = editing ? IRIS_WROOM_RT.tasks.find(function (x) {
        return x.id === editing; }) : null;
    document.getElementById('iris-wr-rtask-f-title').value = t ? t.title : '';
    document.getElementById('iris-wr-rtask-f-desc').value =
        t ? (t.description || '') : '';
    document.getElementById('iris-wr-rtask-f-status').value =
        t ? t.status : 'no_status';
    document.getElementById('iris-wr-rtask-f-due').value =
        (t && t.due_date) ? t.due_date.slice(0, 10) : '';
    document.getElementById('iris-wr-rtask-f-assignee').value =
        (t && t.assignee_id) ? String(t.assignee_id) : '';
    document.getElementById('iris-wr-rtask-f-tags').value =
        t ? (t.tags || '') : '';
    $('#iris-wr-rtask-modal').modal('show');
}

/* ------------------------------------------------ read-only tab loaders */

/* ------------------------------------------------ Timelines tab (v3) */

var IRIS_WROOM_TL = {
    data: {timelines: [], events: [], visible_cases: 0},
    roomSel: {},   /* timeline_id -> false when toggled off */
    caseSel: {},   /* case_id -> false when toggled off */
    q: '', cat: '', from: '', to: '', view: 'list',
    editing: null  /* {timeline_id, event_id} when editing a room event */
};

function iris_wroom_tl_color(c) {
    return (c && /^#[0-9a-fA-F]{3,8}$/.test(c)) ? c : '#5e72e4';
}

/* v3-shaped timeline modal (name + colour swatch). Create mode when
   editingTl is null (afterCreate runs with the created row); edit mode
   prefills and PUTs. */
function iris_wroom_tl_open_modal(afterCreate, editingTl) {
    IRIS_WROOM_TL._afterCreate = afterCreate || null;
    IRIS_WROOM_TL._editingTl = editingTl || null;
    document.getElementById('iris-wr-tl-modal-title').textContent =
        editingTl ? 'Edit timeline' : 'New timeline';
    document.getElementById('iris-wr-tl-f-create').textContent =
        editingTl ? 'Save' : 'Create';
    document.getElementById('iris-wr-tl-f-name').value =
        editingTl ? editingTl.name : '';
    document.getElementById('iris-wr-tl-f-color').value =
        iris_wroom_tl_color(editingTl && editingTl.color);
    $('#iris-wr-tl-modal').modal('show');
    setTimeout(function () {
        document.getElementById('iris-wr-tl-f-name').focus();
    }, 300);
}

function iris_wroom_tl_colorof(tid) {
    var tl = (IRIS_WROOM_TL.data.timelines || []).find(function (t) {
        return t.id === parseInt(tid, 10);
    });
    return iris_wroom_tl_color(tl && tl.color);
}

function iris_wroom_load_timelines() {
    iris_wroom_api('GET', '/timeline?limit=500').then(function (res) {
        if (!res.ok) return;
        IRIS_WROOM_TL.data = res.j;
        iris_wroom_tl_render_rail();
        iris_wroom_tl_render();
    });
}

function iris_wroom_tl_render_rail() {
    var d = IRIS_WROOM_TL.data;
    var canEdit = iris_wroom_can('responder') && iris_wroom_active();
    var box = document.getElementById('iris-wr-tl-roomlist');
    document.getElementById('iris-wr-tl-roomempty').style.display =
        d.timelines.length ? 'none' : '';
    box.innerHTML = '';
    var svgPlus = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>';
    var svgPencil = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/></svg>';
    var svgTrash = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></svg>';
    d.timelines.forEach(function (tl) {
        var on = IRIS_WROOM_TL.roomSel[tl.id] !== false;
        var acts = '';
        if (canEdit) {
            acts += '<a href="#" class="iris-wr-tl-act iris-wr-tl-addev" ' +
                'data-timeline-id="' + tl.id + '" title="Add event">' +
                svgPlus + '</a>' +
                '<a href="#" class="iris-wr-tl-act iris-wr-tl-edit" ' +
                'data-timeline-id="' + tl.id + '" title="Edit timeline">' +
                svgPencil + '</a>';
        }
        if (iris_wroom_can('lead') && iris_wroom_active()) {
            acts += '<a href="#" class="iris-wr-tl-act iris-wr-tl-del" ' +
                'data-timeline-id="' + tl.id + '" title="Delete timeline">' +
                svgTrash + '</a>';
        }
        var row = document.createElement('div');
        row.className = 'iris-wr-railrow';
        row.innerHTML =
            '<input type="checkbox" class="iris-wr-tl-roomtoggle mr-1" ' +
            'style="margin-left:0;" data-timeline-id="' + tl.id + '"' +
            (on ? ' checked' : '') + '>' +
            '<span class="iris-wr-tldotname" style="background:' +
            iris_wroom_tl_color(tl.color) + ';"></span>' +
            '<span class="iris-wr-railtxt">' + iris_wroom_esc(tl.name) +
            ' <span class="text-muted">(' + tl.event_count + ')</span></span>' +
            (acts ? '<span class="iris-wr-tl-acts">' + acts + '</span>' : '');
        box.appendChild(row);
    });
    document.getElementById('iris-wr-tl-addevent').style.display =
        canEdit ? '' : 'none';

    var cbox = document.getElementById('iris-wr-tl-caselist');
    cbox.innerHTML = '';
    var cases = ((IRIS_WROOM._room && IRIS_WROOM._room.cases) || [])
        .filter(function (c) { return c.accessible; });
    if (!cases.length) {
        cbox.innerHTML = '<div class="iris-wr-rail-hint">No accessible linked cases.</div>';
    }
    cases.forEach(function (c) {
        var on = IRIS_WROOM_TL.caseSel[c.case_id] !== false;
        var row = document.createElement('div');
        row.innerHTML =
            '<div class="iris-wr-railrow"><span class="iris-wr-railtxt" ' +
            'title="' + iris_wroom_esc(c.case_name) + '">#' + c.case_id +
            ' - ' + iris_wroom_esc(c.case_name) + '</span>' +
            (on ? '<span class="iris-wr-tl-on">ON</span>' : '') + '</div>' +
            '<div class="iris-wr-railrow" style="margin-left:14px;">' +
            '<input type="checkbox" class="iris-wr-tl-casetoggle mr-1" ' +
            'style="margin-left:0;" data-case-id="' + c.case_id + '"' +
            (on ? ' checked' : '') + '>' +
            '<span class="iris-wr-railtxt">Main</span>' +
            '<span class="iris-wr-tl-on" style="margin-left:auto;">DEFAULT</span></div>';
        cbox.appendChild(row);
    });
}

function iris_wroom_tl_visible() {
    var t = IRIS_WROOM_TL;
    return (t.data.events || []).filter(function (e) {
        if (e.source === 'room'
                && t.roomSel[e.timeline_id] === false) return false;
        if (e.source === 'case'
                && t.caseSel[e.case_id] === false) return false;
        if (t.cat && (e.category || '') !== t.cat) return false;
        if (t.q) {
            var hay = ((e.event_title || '') + ' ' + (e.event_content || '')
                + ' ' + (e.category || '')).toLowerCase();
            if (hay.indexOf(t.q) === -1) return false;
        }
        var dt = e.event_date || '';
        if (t.from && dt && dt < t.from) return false;
        if (t.to && dt && dt > t.to) return false;
        return true;
    });
}

function iris_wroom_tl_card(e, isChild) {
    var color = iris_wroom_tl_color(e.color);
    var d = e.event_date ? new Date(e.event_date) : null;
    var time = d ? d.toLocaleTimeString([], {hour12: false}) : '';
    var srcChip = e.source === 'case'
        ? '<span class="iris-wr-tl-srcchip">Case</span>' +
          '<span class="iris-wr-tl-ref"><a href="/case?cid=' + e.case_id +
          '" class="text-muted">#case:' + e.case_id + ':' + e.event_id +
          '</a></span>'
        : '<span class="iris-wr-tl-srcchip room">Room</span>' +
          '<span class="iris-wr-tl-ref">' +
          iris_wroom_esc(e.timeline_name || '') + '</span>';
    var chips = '';
    if (e.asset_count) {
        chips += '<span class="iris-wr-tl-chip iris-wr-tl-chip-assets">' +
            e.asset_count + ' asset' + (e.asset_count === 1 ? '' : 's') +
            '</span>';
    }
    if (e.ioc_count) {
        chips += '<span class="iris-wr-tl-chip iris-wr-tl-chip-iocs">' +
            e.ioc_count + ' IOC' + (e.ioc_count === 1 ? '' : 's') + '</span>';
    }
    (e.tags || '').split(',').forEach(function (tg) {
        tg = tg.trim();
        if (tg) {
            chips += '<span class="iris-wr-tl-chip iris-wr-tl-chip-tag">#' +
                iris_wroom_esc(tg) + '</span>';
        }
    });
    var actions = (e.source === 'room' && iris_wroom_can('responder')
                   && iris_wroom_active())
        ? '<div class="iris-wr-tl-actions">' +
          '<a href="#" class="iris-wr-tlev-edit" data-timeline-id="' +
          e.timeline_id + '" data-event-id="' + e.event_id + '">Edit</a>' +
          '<a href="#" class="iris-wr-tlev-del" data-timeline-id="' +
          e.timeline_id + '" data-event-id="' + e.event_id + '">Delete</a>' +
          '</div>' : '';
    return '<div class="iris-wr-tlrow' +
        (isChild ? ' iris-wr-tree-child' : '') + '">' +
        '<span class="iris-wr-tldot" style="background:' + color + ';"></span>' +
        '<div class="iris-wr-tlcard" style="border-left-color:' + color + ';">' +
        actions +
        '<div class="iris-wr-tl-head">' +
        '<span class="iris-wr-tl-time">' + time + '</span>' +
        (e.category ? '<span>&middot;</span><span class="iris-wr-tl-catname">' +
            iris_wroom_esc(e.category) + '</span>' : '') +
        srcChip + '</div>' +
        '<div class="iris-wr-tl-title">' + iris_wroom_esc(e.event_title) +
        '</div>' +
        (e.event_content ? '<div class="iris-wr-tl-body">' +
            iris_wroom_esc(e.event_content) + '</div>' : '') +
        (chips ? '<div class="iris-wr-tl-chips">' + chips + '</div>' : '') +
        '</div></div>';
}

function iris_wroom_tl_render() {
    var t = IRIS_WROOM_TL;
    var visible = iris_wroom_tl_visible();
    var all = t.data.events || [];
    document.getElementById('iris-wr-tl-counter').textContent =
        visible.length + ' / ' + all.length + ' events';

    /* Category select options (kept in sync with the loaded data). */
    var catSel = document.getElementById('iris-wr-tl-cat');
    var cats = {};
    all.forEach(function (e) { if (e.category) cats[e.category] = true; });
    var current = catSel.value;
    catSel.innerHTML = '<option value="">Category</option>' +
        Object.keys(cats).sort().map(function (c) {
            return '<option value="' + iris_wroom_esc(c) + '">' +
                iris_wroom_esc(c) + '</option>';
        }).join('');
    catSel.value = current;

    var box = document.getElementById('iris-wr-tl-list');
    var empty = document.getElementById('iris-wr-tl-empty');
    box.innerHTML = '';
    if (!visible.length) {
        /* Say WHY it is empty (none-vs-broken rule). */
        empty.textContent = !all.length
            ? (t.data.visible_cases
                ? 'No timeline events yet — case timelines are empty and no room timeline has events.'
                : 'No room timeline events, and no linked cases you can access.')
            : 'No events match the current filters.';
        empty.style.display = '';
        return;
    }
    empty.style.display = 'none';

    /* Chronological, v3-style. */
    var items = visible.slice().sort(function (a, b) {
        return (a.event_date || '') < (b.event_date || '') ? -1 : 1;
    });

    if (t.view === 'tree') {
        /* Case events with a visible parent nest under it; everything else
         * stays flat. Cycles cannot occur in one pass (children render
         * after their parent only when the parent is visible). */
        var byId = {};
        items.forEach(function (e) {
            if (e.source === 'case') byId['c' + e.event_id] = e;
        });
        var rendered = {};
        var html = '';
        var lastDate = '';
        items.forEach(function (e) {
            if (e.source === 'case' && e.parent_event_id
                    && byId['c' + e.parent_event_id]) return; /* child */
            lastDate = iris_wroom_tl_sep(e, lastDate, function (h) {
                html += h; });
            html += iris_wroom_tl_card(e, false);
            rendered['c' + e.event_id] = true;
            if (e.source === 'case') {
                items.forEach(function (ch) {
                    if (ch.source === 'case'
                            && ch.parent_event_id === e.event_id) {
                        html += iris_wroom_tl_card(ch, true);
                    }
                });
            }
        });
        box.innerHTML = html;
    } else {
        var html2 = '';
        var last2 = '';
        items.forEach(function (e) {
            last2 = iris_wroom_tl_sep(e, last2, function (h) { html2 += h; });
            html2 += iris_wroom_tl_card(e, false);
        });
        box.innerHTML = html2;
    }
}

function iris_wroom_tl_sep(e, lastDate, emit) {
    var d = e.event_date ? new Date(e.event_date) : null;
    if (!d) return lastDate;
    var key = d.toLocaleDateString([], {weekday: 'short', month: 'short',
                                        day: 'numeric'});
    if (key !== lastDate) {
        emit('<div class="iris-wr-datesep"><span>' + iris_wroom_esc(key) +
             '</span></div>');
        return key;
    }
    return lastDate;
}

function iris_wroom_tlev_open(editing, preselectTl) {
    var t = IRIS_WROOM_TL;
    IRIS_WROOM_TL.editing = editing || null;
    var sel = document.getElementById('iris-wr-tlev-timeline');
    sel.innerHTML = t.data.timelines.map(function (tl) {
        return '<option value="' + tl.id + '">' + iris_wroom_esc(tl.name) +
            '</option>';
    }).join('');
    document.getElementById('iris-wr-tlev-error').style.display = 'none';
    document.getElementById('iris-wr-tlev-delete').style.display =
        editing ? '' : 'none';
    document.getElementById('iris-wr-tlev-title-h').textContent =
        editing ? 'Edit timeline entry' : 'New timeline entry';
    var colorEl = document.getElementById('iris-wr-tlev-color');
    // Untouched swatch = inherit the timeline's colour (the input can never
    // be empty, so "no explicit colour" is tracked as a touched flag).
    IRIS_WROOM_TL._tlevColorTouched = false;
    if (editing) {
        var ev = (t.data.events || []).find(function (e) {
            return e.source === 'room' && e.event_id === editing.event_id;
        });
        if (!ev) return;
        sel.value = ev.timeline_id;
        sel.disabled = true;
        document.getElementById('iris-wr-tlev-timeline-grp').style.display =
            'none';
        document.getElementById('iris-wr-tlev-title').value = ev.event_title;
        document.getElementById('iris-wr-tlev-date').value =
            (ev.event_date || '').replace('Z', '').slice(0, 19);
        document.getElementById('iris-wr-tlev-cat').value = ev.category || '';
        colorEl.value = ev.color ? iris_wroom_tl_color(ev.color)
            : iris_wroom_tl_colorof(ev.timeline_id);
        IRIS_WROOM_TL._tlevColorTouched = !!ev.color;
        document.getElementById('iris-wr-tlev-tags').value = ev.tags || '';
        document.getElementById('iris-wr-tlev-content').value =
            ev.event_content || '';
    } else {
        sel.disabled = false;
        if (preselectTl) sel.value = preselectTl;
        // The timeline chooser only appears when there is a real choice.
        document.getElementById('iris-wr-tlev-timeline-grp').style.display =
            (preselectTl || t.data.timelines.length < 2) ? 'none' : '';
        document.getElementById('iris-wr-tlev-title').value = '';
        document.getElementById('iris-wr-tlev-date').value = '';
        document.getElementById('iris-wr-tlev-cat').value = '';
        colorEl.value = iris_wroom_tl_colorof(sel.value);
        document.getElementById('iris-wr-tlev-tags').value = '';
        document.getElementById('iris-wr-tlev-content').value = '';
    }
    $('#iris-wr-tlev-modal').modal('show');
    setTimeout(function () {
        document.getElementById('iris-wr-tlev-title').focus();
    }, 300);
}

function iris_wroom_load_tasks() {
    iris_wroom_api('GET', '/tasks?limit=200').then(function (res) {
        if (!res.ok) return;
        var rows = res.j.tasks || [];
        var tb = document.getElementById('iris-wr-tk-tbody');
        var empty = document.getElementById('iris-wr-tk-empty');
        tb.innerHTML = '';
        if (!rows.length) {
            empty.textContent = 'No tasks in the linked cases you can access.';
            empty.style.display = '';
            return;
        }
        empty.style.display = 'none';
        rows.forEach(function (t) {
            var tr = document.createElement('tr');
            tr.innerHTML =
                '<td><a href="/case/tasks?cid=' + t.case_id + '">' +
                iris_wroom_esc(t.task_title) + '</a></td>' +
                '<td>' + iris_wroom_esc(t.status_name || '') + '</td>' +
                '<td><a href="/case?cid=' + t.case_id + '">#' + t.case_id +
                '</a></td>' +
                '<td class="text-muted" style="font-size:0.78rem;">' +
                iris_wroom_rel(t.task_last_update) + '</td>';
            tb.appendChild(tr);
        });
    });
}

/* ------------------------------------------------------- notes (two-pane) */

var IRIS_WROOM_NT = {
    data: {folders: [], room_notes: [], case_notes: []},
    q: '', sel: null, doc: null, dirty: false, saveTimer: null,
    folderEdit: null
};

var IRIS_WROOM_NT_ICO = {
    folder: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>',
    file: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/></svg>',
    plus: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>',
    pencil: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/></svg>',
    trash: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></svg>'
};

function iris_wroom_load_notes() {
    iris_wroom_api('GET', '/notes?limit=200').then(function (res) {
        if (!res.ok) return;
        IRIS_WROOM_NT.data = res.j;
        iris_wroom_nt_render_rail();
    });
}

function iris_wroom_nt_can_edit() {
    return iris_wroom_can('responder') && iris_wroom_active();
}

function iris_wroom_nt_noterow(n, isSub) {
    var active = IRIS_WROOM_NT.sel && IRIS_WROOM_NT.sel.type === 'room'
        && IRIS_WROOM_NT.sel.id === n.id;
    return '<div class="iris-wr-nt-row' + (isSub ? ' iris-wr-nt-sub' : '') +
        (active ? ' active' : '') + '" data-note-id="' + n.id + '">' +
        IRIS_WROOM_NT_ICO.file +
        '<span class="iris-wr-nt-name">' +
        iris_wroom_esc(n.title || '(untitled)') + '</span></div>';
}

function iris_wroom_nt_inline_row(value, dataAttrs) {
    return '<div class="iris-wr-nt-row iris-wr-nt-inline"' + dataAttrs + '>' +
        IRIS_WROOM_NT_ICO.folder +
        '<input type="text" maxlength="120" value="' +
        iris_wroom_esc(value || '') + '" placeholder="Folder name">' +
        '</div>';
}

function iris_wroom_nt_render_rail() {
    var s = IRIS_WROOM_NT;
    var canEdit = iris_wroom_nt_can_edit();
    document.getElementById('iris-wr-nt-newfolder').style.display =
        canEdit ? '' : 'none';
    document.getElementById('iris-wr-nt-newnote').style.display =
        canEdit ? '' : 'none';

    var match = function (title) {
        return !s.q || (title || '').toLowerCase().indexOf(s.q) !== -1;
    };
    var box = document.getElementById('iris-wr-nt-roomlist');
    var html = '';
    if (s.folderEdit && s.folderEdit.mode === 'new') {
        html += iris_wroom_nt_inline_row('', ' data-inline="new"');
    }
    (s.data.folders || []).forEach(function (f) {
        var notes = (s.data.room_notes || []).filter(function (n) {
            return n.folder_id === f.id && match(n.title);
        });
        if (s.q && !notes.length && !match(f.name)) return;
        if (s.folderEdit && s.folderEdit.mode === 'rename'
                && s.folderEdit.id === f.id) {
            html += iris_wroom_nt_inline_row(f.name,
                ' data-inline="rename" data-folder-id="' + f.id + '"');
        } else {
            html += '<div class="iris-wr-nt-row iris-wr-nt-folderhead" ' +
                'data-folder-id="' + f.id + '">' + IRIS_WROOM_NT_ICO.folder +
                '<span class="iris-wr-nt-name">' + iris_wroom_esc(f.name) +
                '</span>' +
                (canEdit
                    ? '<span class="iris-wr-tl-acts">' +
                      '<a href="#" class="iris-wr-tl-act iris-wr-nt-addin" data-folder-id="' + f.id + '" title="New note here">' + IRIS_WROOM_NT_ICO.plus + '</a>' +
                      '<a href="#" class="iris-wr-tl-act iris-wr-nt-ren" data-folder-id="' + f.id + '" title="Rename folder">' + IRIS_WROOM_NT_ICO.pencil + '</a>' +
                      '<a href="#" class="iris-wr-tl-act iris-wr-tl-del iris-wr-nt-delfolder" data-folder-id="' + f.id + '" title="Delete folder (notes move to root)">' + IRIS_WROOM_NT_ICO.trash + '</a>' +
                      '</span>'
                    : '') + '</div>';
        }
        notes.forEach(function (n) { html += iris_wroom_nt_noterow(n, true); });
    });
    (s.data.room_notes || []).filter(function (n) {
        return !n.folder_id && match(n.title);
    }).forEach(function (n) { html += iris_wroom_nt_noterow(n, false); });
    box.innerHTML = html;
    document.getElementById('iris-wr-nt-roomempty').style.display =
        (s.data.room_notes || []).length || s.folderEdit ? 'none' : '';
    var inline = box.querySelector('.iris-wr-nt-inline input');
    if (inline) { inline.focus(); inline.select(); }

    /* Linked case notes, grouped per accessible case. */
    var cbox = document.getElementById('iris-wr-nt-caselist');
    var chtml = '';
    var byCase = {};
    (s.data.case_notes || []).forEach(function (n) {
        if (!match(n.note_title)) return;
        (byCase[n.case_id] = byCase[n.case_id] || []).push(n);
    });
    ((IRIS_WROOM._room && IRIS_WROOM._room.cases) || [])
        .filter(function (c) { return c.accessible && byCase[c.case_id]; })
        .forEach(function (c) {
            chtml += '<div class="iris-wr-nt-row iris-wr-nt-folderhead" ' +
                'title="' + iris_wroom_esc(c.case_name) + '">' +
                '<span class="iris-wr-nt-name">#' + c.case_id + ' - ' +
                iris_wroom_esc(c.case_name) + '</span></div>';
            byCase[c.case_id].forEach(function (n) {
                var active = s.sel && s.sel.type === 'case'
                    && s.sel.note_id === n.note_id;
                chtml += '<div class="iris-wr-nt-row iris-wr-nt-sub' +
                    (active ? ' active' : '') + '" data-case-id="' +
                    n.case_id + '" data-case-note-id="' + n.note_id + '">' +
                    IRIS_WROOM_NT_ICO.file +
                    '<span class="iris-wr-nt-name">' +
                    iris_wroom_esc(n.note_title || '(untitled)') +
                    '</span></div>';
            });
        });
    cbox.innerHTML = chtml;
    document.getElementById('iris-wr-nt-caseempty').style.display =
        chtml ? 'none' : '';
}

function iris_wroom_nt_status(text) {
    document.getElementById('iris-wr-nt-status').textContent = text || '';
}

function iris_wroom_nt_show_doc(doc, readOnly) {
    IRIS_WROOM_NT.doc = doc;
    document.getElementById('iris-wr-nt-placeholder').style.display = 'none';
    document.getElementById('iris-wr-nt-doc').style.display = '';
    var title = document.getElementById('iris-wr-nt-title');
    title.value = doc.title || '';
    title.readOnly = readOnly;
    document.getElementById('iris-wr-nt-ro').style.display =
        readOnly ? '' : 'none';
    document.getElementById('iris-wr-nt-del').style.display =
        (!readOnly && iris_wroom_nt_can_edit()) ? '' : 'none';
    document.getElementById('iris-wr-nt-meta').textContent = doc.meta || '';
    var view = document.getElementById('iris-wr-nt-view');
    view.innerHTML = doc.content_html
        || '<div class="iris-wr-nt-hintline">' +
           (readOnly ? '(empty note)' : 'Double-click to edit...') + '</div>';
    view.style.display = '';
    document.getElementById('iris-wr-nt-edit').style.display = 'none';
    iris_wroom_nt_status('');
}

function iris_wroom_nt_open_room(id) {
    iris_wroom_nt_flush_save();
    iris_wroom_api('GET', '/notes/room/' + id).then(function (res) {
        if (!res.ok) return;
        IRIS_WROOM_NT.sel = {type: 'room', id: id};
        res.j.meta = 'Room note · updated ' + iris_wroom_rel(res.j.updated_at)
            + (res.j.updated_by_name ? ' by ' + res.j.updated_by_name : '');
        iris_wroom_nt_show_doc(res.j, !iris_wroom_nt_can_edit());
        iris_wroom_nt_render_rail();
    });
}

function iris_wroom_nt_open_case(caseId, noteId) {
    iris_wroom_nt_flush_save();
    iris_wroom_api('GET', '/notes/case/' + caseId + '/' + noteId)
        .then(function (res) {
            if (!res.ok) return;
            IRIS_WROOM_NT.sel = {type: 'case', case_id: caseId,
                                 note_id: noteId};
            res.j.meta = 'Case note from #' + caseId + ' · updated ' +
                iris_wroom_rel(res.j.updated_at);
            iris_wroom_nt_show_doc(res.j, true);
            iris_wroom_nt_render_rail();
        });
}

/* Debounced autosave for the markdown editor. flush() saves immediately —
   called before switching notes or leaving edit mode. */
function iris_wroom_nt_queue_save() {
    var s = IRIS_WROOM_NT;
    s.dirty = true;
    iris_wroom_nt_status('Saving...');
    if (s.saveTimer) clearTimeout(s.saveTimer);
    s.saveTimer = setTimeout(iris_wroom_nt_flush_save, 800);
}

function iris_wroom_nt_flush_save() {
    var s = IRIS_WROOM_NT;
    if (s.saveTimer) { clearTimeout(s.saveTimer); s.saveTimer = null; }
    if (!s.dirty || !s.sel || s.sel.type !== 'room') return;
    s.dirty = false;
    var body = {content: document.getElementById('iris-wr-nt-edit').value};
    var savedId = s.sel.id;
    iris_wroom_api('PUT', '/notes/room/' + savedId, body)
        .then(function (res) {
            if (!res.ok) { iris_wroom_nt_status('Save failed'); return; }
            if (s.doc) s.doc.content_html = res.j.content_html;
            iris_wroom_nt_status('Changes saved');
            /* If the editor is closed and this note is still open, repaint
               the rendered view with the fresh server-side markdown. */
            var ed = document.getElementById('iris-wr-nt-edit');
            if (ed.style.display === 'none' && s.sel
                    && s.sel.type === 'room' && s.sel.id === savedId) {
                document.getElementById('iris-wr-nt-view').innerHTML =
                    res.j.content_html
                    || '<div class="iris-wr-nt-hintline">Double-click to edit...</div>';
            }
        });
}

/* --------------------------------------------------------------- sitreps */

/* v3 two-pane SitReps: rail + inline editor (markdown toolbar + preview),
   title-only draft modal, publish confirm, MD/HTML/print-PDF exports. */

var IRIS_WROOM_SR = {list: [], cur: null, mode: 'read', previewOn: false};

var IRIS_WROOM_SR_SKELETON =
    '## Situation\n\n## Actions taken\n\n## Next steps\n';

function iris_wroom_load_sitreps() {
    iris_wroom_api('GET', '/sitreps').then(function (res) {
        if (!res.ok) return;
        IRIS_WROOM_SR.list = res.j.sitreps || [];
        iris_wroom_sr_render_rail();
    });
}

function iris_wroom_sr_render_rail() {
    var rows = IRIS_WROOM_SR.list;
    document.getElementById('iris-wr-sitrep-count').textContent =
        rows.length ? '(' + rows.length + ')' : '';
    var box = document.getElementById('iris-wr-sitrep-list');
    document.getElementById('iris-wr-sitrep-empty').style.display =
        rows.length ? 'none' : '';
    box.innerHTML = rows.map(function (s) {
        var active = IRIS_WROOM_SR.cur && IRIS_WROOM_SR.cur.id === s.id;
        return '<div class="iris-wr-sitrep-item' + (active ? ' active' : '') +
            (s.status === 'published' ? ' published' : '') +
            '" data-sitrep-id="' + s.id + '">' +
            '<div>' + iris_wroom_esc(s.title) + '</div>' +
            '<div class="iris-wr-sitrep-sub">v' + (s.version || 1) + ' · ' +
            (s.status === 'published' ? 'Published' : 'Draft') + ' · ' +
            iris_wroom_rel(s.updated_at || s.created_at) + '</div></div>';
    }).join('');
}

function iris_wroom_sr_meta(s) {
    var d = s.status === 'published'
        ? s.published_at : (s.updated_at || s.created_at);
    return 'v' + (s.version || 1) + ' · ' +
        (s.status === 'published' ? 'Published' : 'Draft') +
        (d ? ' · ' + new Date(d).toLocaleString() : '');
}

function iris_wroom_sr_show(s, mode) {
    IRIS_WROOM_SR.cur = s;
    IRIS_WROOM_SR.mode = mode;
    IRIS_WROOM_SR.previewOn = false;
    document.getElementById('iris-wr-sr-placeholder').style.display = 'none';
    document.getElementById('iris-wr-sr-doc').style.display = '';
    var canEdit = iris_wroom_can('responder') && iris_wroom_active();
    var lead = iris_wroom_can('lead') && iris_wroom_active();
    var edit = mode === 'edit' && canEdit;
    var title = document.getElementById('iris-wr-sr-title');
    title.value = s.title || '';
    title.readOnly = !edit;
    document.getElementById('iris-wr-sr-meta').textContent =
        iris_wroom_sr_meta(s);
    document.getElementById('iris-wr-sr-status').textContent = '';
    document.getElementById('iris-wr-sr-editbox').style.display =
        edit ? '' : 'none';
    var view = document.getElementById('iris-wr-sr-view');
    view.style.display = edit ? 'none' : '';
    if (edit) {
        document.getElementById('iris-wr-sr-content').value = s.content || '';
        document.getElementById('iris-wr-sr-content').style.display = '';
        document.getElementById('iris-wr-sr-preview').style.display = 'none';
        document.getElementById('iris-wr-sr-preview-toggle').innerHTML =
            '&#128065; Preview';
    } else {
        view.innerHTML = s.content_html
            || '<div class="iris-wr-nt-hintline">(empty)</div>';
    }
    document.getElementById('iris-wr-sr-cancel').style.display =
        edit ? '' : 'none';
    document.getElementById('iris-wr-sr-save').style.display =
        edit ? '' : 'none';
    document.getElementById('iris-wr-sr-publishbtn').style.display =
        (edit && lead && s.status === 'draft') ? '' : 'none';
    document.getElementById('iris-wr-sr-editbtn').style.display =
        (!edit && canEdit) ? '' : 'none';
    /* v3 parity (maintainer decision): published SitReps ARE deletable —
       lead only, same as drafts. */
    document.getElementById('iris-wr-sr-del').style.display =
        lead ? '' : 'none';
    iris_wroom_sr_render_rail();
}

function iris_wroom_open_sitrep(id, forceMode) {
    iris_wroom_api('GET', '/sitreps/' + id).then(function (res) {
        if (!res.ok) return;
        var canEdit = iris_wroom_can('responder') && iris_wroom_active();
        var mode = forceMode
            || (res.j.status === 'draft' && canEdit ? 'edit' : 'read');
        iris_wroom_sr_show(res.j, mode);
    });
}

function iris_wroom_sr_save(cb) {
    var s = IRIS_WROOM_SR.cur;
    if (!s) return;
    iris_wroom_api('PUT', '/sitreps/' + s.id, {
        title: document.getElementById('iris-wr-sr-title').value,
        content: document.getElementById('iris-wr-sr-content').value
    }).then(function (res) {
        if (!res.ok) {
            document.getElementById('iris-wr-sr-status').textContent =
                res.j.message || 'Save failed';
            return;
        }
        IRIS_WROOM_SR.cur = res.j;
        document.getElementById('iris-wr-sr-meta').textContent =
            iris_wroom_sr_meta(res.j);
        document.getElementById('iris-wr-sr-status').textContent = 'Saved';
        iris_wroom_load_sitreps();
        if (cb) cb(res.j);
    });
}

/* Markdown toolbar: wrap the selection or prefix the line. */
function iris_wroom_sr_md(action) {
    var ta = document.getElementById('iris-wr-sr-content');
    var start = ta.selectionStart, end = ta.selectionEnd;
    var sel = ta.value.slice(start, end);
    var before = ta.value.slice(0, start), after = ta.value.slice(end);
    var ins = null, cursor;
    function wrap(mark, ph) {
        var body = sel || ph;
        ins = mark + body + mark;
        cursor = start + ins.length;
    }
    function linePrefix(p, ph) {
        var body = sel || ph;
        ins = (before && before.slice(-1) !== '\n' ? '\n' : '') + p + body;
        cursor = start + ins.length;
    }
    switch (action) {
    case 'bold': wrap('**', 'bold'); break;
    case 'italic': wrap('*', 'italic'); break;
    case 'strike': wrap('~~', 'strikethrough'); break;
    case 'h1': linePrefix('# ', 'Heading'); break;
    case 'h2': linePrefix('## ', 'Heading'); break;
    case 'h3': linePrefix('### ', 'Heading'); break;
    case 'ul': linePrefix('- ', 'item'); break;
    case 'ol': linePrefix('1. ', 'item'); break;
    case 'quote': linePrefix('> ', 'quote'); break;
    case 'code': wrap('`', 'code'); break;
    case 'link':
        ins = '[' + (sel || 'text') + '](https://)';
        cursor = start + ins.length - 1;
        break;
    case 'table':
        ins = '\n| Col A | Col B |\n| --- | --- |\n|  |  |\n';
        cursor = start + ins.length;
        break;
    default: return;
    }
    ta.value = before + ins + after;
    ta.focus();
    ta.setSelectionRange(cursor, cursor);
}

function iris_wroom_sr_toggle_preview() {
    var s = IRIS_WROOM_SR;
    var ta = document.getElementById('iris-wr-sr-content');
    var pv = document.getElementById('iris-wr-sr-preview');
    var btn = document.getElementById('iris-wr-sr-preview-toggle');
    if (s.previewOn) {
        s.previewOn = false;
        pv.style.display = 'none';
        ta.style.display = '';
        btn.innerHTML = '&#128065; Preview';
        return;
    }
    iris_wroom_api('POST', '/sitreps/preview', {content: ta.value})
        .then(function (res) {
            if (!res.ok) return;
            s.previewOn = true;
            pv.innerHTML = res.j.content_html
                || '<div class="iris-wr-nt-hintline">(empty)</div>';
            pv.style.display = '';
            ta.style.display = 'none';
            btn.innerHTML = '&#10003; Done';
        });
}

function iris_wroom_sr_download(name, mime, text) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], {type: mime}));
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}

function iris_wroom_sr_export(fmt) {
    var s = IRIS_WROOM_SR.cur;
    if (!s) return;
    var fname = (s.title || 'sitrep').replace(/[^\w\- ]+/g, '').trim()
        .replace(/\s+/g, '-') || 'sitrep';
    if (fmt === 'md') {
        iris_wroom_sr_download(fname + '.md', 'text/markdown',
            '# ' + (s.title || '') + '\n\n' + (s.content || ''));
        return;
    }
    /* HTML + PDF export the last SAVED content (content_html is
       server-rendered safe markdown). */
    var doc = '<!doctype html><html><head><meta charset="utf-8"><title>' +
        iris_wroom_esc(s.title || 'SitRep') + '</title>' +
        '<style>body{font-family:system-ui,sans-serif;max-width:800px;' +
        'margin:40px auto;color:#111;line-height:1.5;}' +
        'table{border-collapse:collapse}td,th{border:1px solid #999;' +
        'padding:4px 8px}</style></head><body><h1>' +
        iris_wroom_esc(s.title || '') + '</h1>' + (s.content_html || '') +
        '</body></html>';
    if (fmt === 'html') {
        iris_wroom_sr_download(fname + '.html', 'text/html', doc);
        return;
    }
    var w = window.open('', '_blank');
    if (!w) return;
    w.document.write(doc);
    w.document.close();
    w.focus();
    setTimeout(function () { w.print(); }, 250);
}

/* ---------------------------------------------------------- correlation */

var IRIS_WROOM_TLP = {
    red: '#F25961', amber: '#f4c430', 'amber+strict': '#f4c430',
    green: '#2dce89', clear: '#c8c8d0'
};

function iris_wroom_tlp_badge(name, shareable) {
    /* Validate against a known map rather than escaping — no server string
     * is interpolated into markup (dashboard rule). */
    var key = (name || '').toLowerCase();
    if (!IRIS_WROOM_TLP[key]) {
        return '<span class="text-muted" title="No TLP set on at least one appearance">unset</span>';
    }
    var lock = shareable ? '' :
        ' <span title="TLP does not permit redistribution">&#128274;</span>';
    return '<span style="color:' + IRIS_WROOM_TLP[key] + '; font-size:0.75rem;">' +
        key.toUpperCase() + '</span>' + lock;
}

function iris_wroom_corr_status(txt) {
    document.getElementById('iris-wr-corr-status').textContent = txt || '';
}

function iris_wroom_load_correlation() {
    iris_wroom_api('GET', '/correlation').then(function (res) {
        if (!res.ok) return;
        IRIS_WROOM._corr = res.j;
        var pairs = res.j.pairs || [];
        var stats = res.j.stats || {};
        var tb = document.getElementById('iris-wr-corr-tbody');
        var empty = document.getElementById('iris-wr-corr-empty');
        var note = document.getElementById('iris-wr-corr-note');
        note.textContent = stats.inaccessible_cases
            ? (stats.inaccessible_cases + ' linked case(s) are outside your ' +
               'access — indicators from them are not shown.')
            : '';
        tb.innerHTML = '';
        if (!pairs.length) {
            /* An empty table must say WHY (none-vs-broken rule). */
            empty.textContent = stats.linked_cases < 2
                ? 'Correlation needs at least two attached cases.'
                : 'No IOC is shared by two or more of the attached cases' +
                  (stats.inaccessible_cases ? ' that you can access.' : '.');
            empty.style.display = '';
        } else {
            empty.style.display = 'none';
        }
        pairs.forEach(function (p) {
            var tr = document.createElement('tr');
            /* Opt the row into the shared cross-case drawer (the include on
             * this page carries a delegated document-level listener on
             * .iris-corr-ioc-row). setAttribute, never string-concat: an IOC
             * value can contain quotes, and setAttribute is attribute-safe
             * by construction. Clicks on the case anchors still navigate —
             * the drawer's listener ignores clicks inside <a>. */
            tr.className = 'iris-corr-ioc-row';
            tr.style.cursor = 'pointer';
            tr.setAttribute('data-ioc-value', p.ioc_value);
            tr.setAttribute('data-ioc-type-id', p.ioc_type_id);
            tr.setAttribute('data-ioc-type-name', p.ioc_type_name || '');
            tr.innerHTML =
                '<td style="font-family:monospace; font-size:0.8rem; word-break:break-all;">' +
                iris_wroom_esc(p.ioc_value) + '</td>' +
                '<td>' + iris_wroom_esc(p.ioc_type_name) + '</td>' +
                '<td>' + iris_wroom_tlp_badge(p.tlp_name, p.tlp_shareable) + '</td>' +
                '<td>' + p.case_ids.map(function (cid) {
                    return '<a href="/case?cid=' + cid + '">#' + cid + '</a>';
                }).join(' ') + '</td>';
            tb.appendChild(tr);
        });
        document.getElementById('iris-wr-corr-tag').style.display =
            (pairs.length && iris_wroom_can('responder') && iris_wroom_active())
                ? '' : 'none';
        document.getElementById('iris-wr-corr-stix').href =
            '/api/v2/war-rooms/' + IRIS_WROOM._rid + '/stix';
        document.getElementById('iris-wr-corr-misp').style.display =
            (pairs.length && iris_wroom_can('lead') && iris_wroom_active())
                ? '' : 'none';
    });
}

function iris_wroom_apply_campaign_tag() {
    var corr = IRIS_WROOM._corr || {};
    var pairs = corr.pairs || [];
    var tag = corr.campaign_tag || ('campaign:war-room-' + IRIS_WROOM._rid);
    var caseIds = {};
    pairs.forEach(function (p) {
        p.case_ids.forEach(function (cid) { caseIds[cid] = true; });
    });
    iris_wroom_corr_status('Applying tag…');
    /* Reuse of the EXISTING correlation endpoint — the engine and its API
     * stay verbatim; the room just feeds it room-scoped data. */
    fetch('/api/v2/correlation/apply-campaign-tag', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            case_ids: Object.keys(caseIds).map(Number),
            tag: tag,
            shared_ioc_pairs: pairs.map(function (p) {
                return {ioc_value: p.ioc_value, ioc_type_id: p.ioc_type_id};
            }),
            csrf_token: iris_wroom_csrf()
        })
    }).then(function (r) {
        return r.json().then(function (j) { return {ok: r.ok, j: j}; });
    }).then(function (res) {
        iris_wroom_corr_status(res.ok
            ? ('Tagged ' + (res.j.applied || []).length + ' case(s), ' +
               (res.j.iocs_tagged || 0) + ' IOC row(s) with ' + tag)
            : ('Tagging failed: ' + (res.j.message || '')));
    });
}

function iris_wroom_misp_push(force) {
    iris_wroom_corr_status('Publishing to MISP…');
    iris_wroom_api('POST', '/misp-push', force ? {force: true} : {})
        .then(function (res) {
            if (res.ok) {
                var note = res.j.tlp_withheld_note
                    ? ' (' + res.j.tlp_withheld_count + ' withheld on TLP)'
                    : '';
                iris_wroom_corr_status('Published as MISP event #' +
                    res.j.misp_event_id + note);
            } else if (res.status === 409) {
                var d = res.j.data || {};
                if (window.confirm((res.j.message ||
                        'Already published.') + '\n\nPublish again?')) {
                    iris_wroom_misp_push(true);
                } else {
                    iris_wroom_corr_status('Already published as MISP event #' +
                        d.misp_event_id);
                }
            } else {
                iris_wroom_corr_status('MISP push failed: ' +
                    (res.j.message || res.status));
            }
        });
}

/* --------------------------------------------------------- AI SitRep draft */

function iris_wroom_ai_status(txt) {
    document.getElementById('iris-wr-sitrep-ai-status').textContent = txt || '';
}

function iris_wroom_open_draft(draft) {
    /* AI output becomes a real DRAFT row the analyst reviews, edits, and
     * (as lead) publishes — AI never publishes. */
    iris_wroom_api('POST', '/sitreps', {
        title: draft.title || 'AI draft',
        content: draft.content || ''
    }).then(function (res) {
        if (!res.ok) {
            iris_wroom_ai_status(res.j.message || 'Draft save failed');
            return;
        }
        iris_wroom_show_pane('sitreps');
        iris_wroom_load_sitreps();
        iris_wroom_sr_show(res.j, 'edit');
        iris_wroom_ai_status('AI draft · ' + (draft.model || '') +
            (draft.cached ? ' · cached' : ''));
    });
}

function iris_wroom_poll_draft(taskId, tries) {
    if (tries > 240) { iris_wroom_ai_status('AI draft timed out.'); return; }
    fetch('/api/v2/ai/jobs/' + taskId, {headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (job) {
            if (job.state === 'done' && job.result) {
                iris_wroom_ai_status('');
                iris_wroom_open_draft(job.result);
            } else if (job.state === 'error' || job.state === 'cancelled') {
                iris_wroom_ai_status('AI draft failed: ' +
                    (job.error || job.state));
            } else {
                iris_wroom_ai_status('AI drafting… (' + job.state + ')');
                setTimeout(function () {
                    iris_wroom_poll_draft(taskId, tries + 1);
                }, 2500);
            }
        });
}

/* ------------------------------------------------------------------ boot */

function iris_wroom_show_pane(name) {
    document.querySelectorAll('.iris-wr-pane').forEach(function (p) {
        p.classList.remove('active');
    });
    document.querySelectorAll('.iris-wr-tab').forEach(function (t) {
        t.classList.toggle('active', t.getAttribute('data-pane') === name);
    });
    var pane = document.getElementById('iris-wr-pane-' + name);
    if (pane) pane.classList.add('active');
    /* Lazy-load the read-only aggregation tabs on first open. */
    if (!IRIS_WROOM._loadedTabs[name]) {
        IRIS_WROOM._loadedTabs[name] = true;
        if (name === 'timelines') iris_wroom_load_timelines();
        if (name === 'tasks') iris_wroom_load_tasks();
        if (name === 'notes') iris_wroom_load_notes();
        if (name === 'teams') iris_wroom_load_teams();
    }
}

document.addEventListener('DOMContentLoaded', function () {
    /* rid is a room id — digits only, like _cid above (it is interpolated
       into request URLs and the STIX href). The input is server-rendered
       from an <int:> route so a mismatch means the page is already broken;
       fall back to '0', a room that cannot exist, so every API call 404s
       and the loader bails instead of silently showing another room. */
    var ridRaw = document.getElementById('iris-wr-room-id').value;
    /* String(parseInt(...)) DERIVES a fresh value — a bare test-ternary
       keeps the tainted string and taint tracking does not credit it. */
    IRIS_WROOM._rid = /^\d+$/.test(ridRaw || '')
        ? String(parseInt(ridRaw, 10)) : '0';

    iris_wroom_load_room().then(function (room) {
        if (!room) return;
        iris_wroom_load_stream();
        iris_wroom_load_sitreps();
        iris_wroom_load_correlation();
        iris_wroom_load_room_tasks();
        /* Teams used to load lazily on the Teams tab; the @-mention palette
         * needs the slugs at composer time, so load them at boot too. */
        iris_wroom_load_teams();
        IRIS_WROOM._pollTimer = setInterval(iris_wroom_load_stream, 5000);
    });

    document.getElementById('iris-wr-tabbar')
        .addEventListener('click', function (e) {
            var tab = e.target.closest('.iris-wr-tab');
            if (tab) iris_wroom_show_pane(tab.getAttribute('data-pane'));
        });

    /* Stream filters — delegated on the rail (it re-renders per refresh). */
    document.querySelector('.iris-wr-rail')
        .addEventListener('change', function (e) {
            var cb = e.target;
            if (cb.classList.contains('iris-wr-lane')) {
                IRIS_WROOM._lanes[cb.getAttribute('data-kind')] = cb.checked;
            } else if (cb.classList.contains('iris-wr-railtopic')) {
                var sel = new Set();
                document.querySelectorAll('.iris-wr-railtopic')
                    .forEach(function (c) {
                        if (c.checked) sel.add(c.getAttribute('data-topic'));
                    });
                IRIS_WROOM._topicSel =
                    (sel.size === IRIS_WROOM._topics.length) ? null : sel;
            } else if (cb.classList.contains('iris-wr-railthread')) {
                var all = document.querySelectorAll('.iris-wr-railthread');
                var tsel = new Set();
                all.forEach(function (c) {
                    if (c.checked)
                        tsel.add(parseInt(c.getAttribute('data-root-id'), 10));
                });
                IRIS_WROOM._threadSel = (tsel.size === all.length) ? null : tsel;
            } else if (cb.classList.contains('iris-wr-railcase')) {
                var cid = parseInt(cb.getAttribute('data-case-id'), 10);
                var lanes = IRIS_WROOM._caseLanes[cid] || {};
                lanes.__all = cb.checked;
                IRIS_WROOM._caseLanes[cid] = lanes;
            } else if (cb.classList.contains('iris-wr-railsub')) {
                var scid = parseInt(cb.getAttribute('data-case-id'), 10);
                var slanes = IRIS_WROOM._caseLanes[scid] || {};
                slanes[cb.getAttribute('data-sublane')] = cb.checked;
                IRIS_WROOM._caseLanes[scid] = slanes;
            } else {
                return;
            }
            iris_wroom_render_chat();
        });
    document.querySelector('.iris-wr-rail')
        .addEventListener('click', function (e) {
            var chev = e.target.closest('.iris-wr-case-chev');
            if (chev) {
                var cid = parseInt(chev.getAttribute('data-case-id'), 10);
                IRIS_WROOM._caseOpen[cid] = !IRIS_WROOM._caseOpen[cid];
                iris_wroom_render_rail();
            }
        });
    document.getElementById('iris-wr-cmd-toggle')
        .addEventListener('click', function () {
            document.getElementById('iris-wr-cmdlist')
                .classList.toggle('open');
        });
    document.getElementById('iris-wr-topic-add')
        .addEventListener('click', function (e) {
            e.preventDefault();
            var name = window.prompt('New topic name:');
            if (name && name.trim()) {
                iris_wroom_set_target({mode: 'topic',
                    topic: name.trim().replace(/^#/, '').slice(0, 64)});
                iris_wroom_cmd_status('Posting to # ' + IRIS_WROOM._target.topic +
                    ' — the topic appears once you send a message');
                document.getElementById('iris-wr-msg-input').focus();
            }
        });
    document.getElementById('iris-wr-chat-filter')
        .addEventListener('input', function () {
            IRIS_WROOM._chatQ = this.value.trim().toLowerCase();
            iris_wroom_render_chat();
        });
    document.getElementById('iris-wr-clear-filters')
        .addEventListener('click', function (e) {
            e.preventDefault();
            IRIS_WROOM._chatQ = '';
            document.getElementById('iris-wr-chat-filter').value = '';
            IRIS_WROOM._topicSel = null;
            IRIS_WROOM._threadSel = null;
            IRIS_WROOM._caseLanes = {};
            IRIS_WROOM._lanes = {message: true, task_event: true, sitrep: true,
                                 notes_pins: true, system: true,
                                 case_link: true};
            iris_wroom_render_chat();
        });

    /* Composer: Enter sends, Shift+Enter newline; '/' opens the palette. */
    document.getElementById('iris-wr-msg-send')
        .addEventListener('click', iris_wroom_send);
    document.getElementById('iris-wr-msg-input')
        .addEventListener('keydown', function (e) {
            /* An open @-palette owns Tab/Enter/arrows/Escape — Enter
             * completes the mention instead of sending. */
            var ms = IRIS_WROOM_MENTION;
            if (ms.open) {
                if (e.key === 'Tab' || e.key === 'Enter') {
                    e.preventDefault();
                    iris_wroom_mention_complete();
                    return;
                }
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    ms.idx = (ms.idx + 1) % ms.items.length;
                    iris_wroom_mention_render();
                    return;
                }
                if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    ms.idx = (ms.idx + ms.items.length - 1) % ms.items.length;
                    iris_wroom_mention_render();
                    return;
                }
                if (e.key === 'Escape') {
                    ms.open = false;
                    iris_wroom_mention_render();
                    return;
                }
            }
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                iris_wroom_send();
            }
        });
    document.getElementById('iris-wr-msg-input')
        .addEventListener('input', iris_wroom_mention_update);
    document.getElementById('iris-wr-msg-input')
        .addEventListener('click', iris_wroom_mention_update);
    document.getElementById('iris-wr-msg-input')
        .addEventListener('blur', function () {
            /* Delayed so a click on the palette can land first. */
            setTimeout(function () {
                IRIS_WROOM_MENTION.open = false;
                iris_wroom_mention_render();
            }, 200);
        });
    document.getElementById('iris-wr-mention-pop')
        .addEventListener('click', function (e) {
            var opt = e.target.closest('.iris-wr-cmd-opt');
            if (!opt) { return; }
            iris_wroom_mention_complete(parseInt(opt.getAttribute('data-i'), 10));
        });
    document.getElementById('iris-wr-msg-input')
        .addEventListener('input', function () {
            var pop = document.getElementById('iris-wr-cmd-pop');
            var v = this.value;
            if (v.charAt(0) === '/' && v.indexOf(' ') === -1 && v.length > 0) {
                var q = v.toLowerCase();
                var hits = IRIS_WROOM_COMMANDS.filter(function (c) {
                    return c[0].indexOf(q) === 0;
                });
                if (hits.length) {
                    pop.innerHTML = hits.map(function (c) {
                        return '<div class="iris-wr-cmd-opt" data-cmd="' +
                            iris_wroom_esc(c[0].split(' ')[0]) + '"><code>' +
                            iris_wroom_esc(c[0]) + '</code> <span class="text-muted">' +
                            iris_wroom_esc(c[1]) + '</span></div>';
                    }).join('');
                    pop.style.display = '';
                    return;
                }
            }
            pop.style.display = 'none';
        });
    document.getElementById('iris-wr-cmd-pop')
        .addEventListener('click', function (e) {
            var opt = e.target.closest('.iris-wr-cmd-opt');
            if (!opt) return;
            var input = document.getElementById('iris-wr-msg-input');
            input.value = opt.getAttribute('data-cmd') + ' ';
            this.style.display = 'none';
            input.focus();
        });
    document.getElementById('iris-wr-target-clear')
        .addEventListener('click', function (e) {
            e.preventDefault();
            iris_wroom_set_target({mode: 'topic', topic: 'main'});
        });

    /* Polls */
    document.getElementById('iris-wr-poll-btn')
        .addEventListener('click', function (e) {
            e.preventDefault();
            iris_wroom_poll_modal_reset();
            $('#iris-wr-poll-modal').modal('show');
        });
    document.getElementById('iris-wr-poll-addopt')
        .addEventListener('click', function (e) {
            e.preventDefault();
            iris_wroom_poll_add_option();
        });
    document.getElementById('iris-wr-poll-options')
        .addEventListener('click', function (e) {
            var del = e.target.closest('.iris-wr-poll-optdel');
            if (!del) return;
            e.preventDefault();
            var box = document.getElementById('iris-wr-poll-options');
            if (box.childElementCount > 2) {
                del.closest('.iris-wr-poll-optrow').remove();
                document.getElementById('iris-wr-poll-optcount').textContent =
                    box.childElementCount;
            }
        });
    document.getElementById('iris-wr-poll-autoclose')
        .addEventListener('change', function () {
            document.getElementById('iris-wr-poll-closes').style.display =
                this.checked ? '' : 'none';
        });
    document.getElementById('iris-wr-poll-create')
        .addEventListener('click', function () {
            var options = [];
            document.querySelectorAll('.iris-wr-poll-optinput')
                .forEach(function (inp) {
                    if (inp.value.trim()) options.push(inp.value.trim());
                });
            var closes = document.getElementById('iris-wr-poll-autoclose').checked
                ? document.getElementById('iris-wr-poll-closes').value : null;
            iris_wroom_api('POST', '/polls', {
                question: document.getElementById('iris-wr-poll-question').value,
                options: options,
                multiple: document.getElementById('iris-wr-poll-multiple').checked,
                anonymous: document.getElementById('iris-wr-poll-anon').checked,
                closes_at: closes || null
            }).then(function (res) {
                if (!res.ok) {
                    var err = document.getElementById('iris-wr-poll-error');
                    err.textContent = res.j.message || 'Poll failed';
                    err.style.display = '';
                    return;
                }
                $('#iris-wr-poll-modal').modal('hide');
                iris_wroom_load_stream();
            });
        });

    /* Resource picker */
    document.getElementById('iris-wr-resource-btn')
        .addEventListener('click', function (e) {
            e.preventDefault();
            var pop = document.getElementById('iris-wr-resource-pop');
            if (pop.style.display === 'block') {
                pop.style.display = 'none';
            } else {
                iris_wroom_res_open();
            }
        });
    document.getElementById('iris-wr-resource-pop')
        .addEventListener('click', function (e) {
            var tab = e.target.closest('.iris-wr-res-tab');
            if (tab) {
                IRIS_WROOM_RES.tab = tab.getAttribute('data-tab');
                this.querySelectorAll('.iris-wr-res-tab')
                    .forEach(function (t) { t.classList.remove('active'); });
                tab.classList.add('active');
                iris_wroom_res_load();
                return;
            }
            var item = e.target.closest('.iris-wr-res-item');
            if (item) {
                var input = document.getElementById('iris-wr-msg-input');
                var token = item.getAttribute('data-token');
                input.value = input.value +
                    (input.value && !/\s$/.test(input.value) ? ' ' : '') +
                    token + ' ';
                this.style.display = 'none';
                input.focus();
            }
        });
    document.getElementById('iris-wr-resource-pop')
        .addEventListener('change', function (e) {
            var sel = e.target.closest('.iris-wr-res-case');
            if (sel) {
                IRIS_WROOM_RES.caseId = parseInt(sel.value, 10) || null;
                iris_wroom_res_load();
            }
        });
    document.getElementById('iris-wr-resource-pop')
        .addEventListener('input', function (e) {
            var s = e.target.closest('.iris-wr-res-search');
            if (s) {
                IRIS_WROOM_RES.q = s.value.trim().toLowerCase();
                iris_wroom_res_load();
            }
        });
    document.addEventListener('click', function (e) {
        var pop = document.getElementById('iris-wr-resource-pop');
        if (pop.style.display === 'block'
                && !e.target.closest('#iris-wr-resource-pop')
                && !e.target.closest('#iris-wr-resource-btn')) {
            pop.style.display = 'none';
        }
    });

    /* Message hover actions: Reply + Pin (delegated on the chat box). */
    document.getElementById('iris-wr-chat')
        .addEventListener('click', function (e) {
            var vote = e.target.closest('.iris-wr-poll-opt');
            if (vote && !vote.classList.contains('closed')) {
                iris_wroom_api('POST',
                    '/polls/' + vote.getAttribute('data-poll-id') + '/vote',
                    {option_id: parseInt(
                        vote.getAttribute('data-option-id'), 10)})
                    .then(iris_wroom_load_stream);
                return;
            }
            var pclose = e.target.closest('.iris-wr-poll-close');
            if (pclose) {
                e.preventDefault();
                iris_wroom_api('POST',
                    '/polls/' + pclose.getAttribute('data-poll-id') + '/close', {})
                    .then(iris_wroom_load_stream);
                return;
            }
            var reply = e.target.closest('.iris-wr-act-reply');
            if (reply) {
                e.preventDefault();
                iris_wroom_set_target({
                    mode: 'reply',
                    parentId: parseInt(reply.getAttribute('data-msg-id'), 10),
                    label: reply.getAttribute('data-snippet')
                });
                document.getElementById('iris-wr-msg-input').focus();
                return;
            }
            var pin = e.target.closest('.iris-wr-act-pin');
            if (pin) {
                e.preventDefault();
                iris_wroom_api('POST',
                    '/messages/' + pin.getAttribute('data-msg-id') + '/pin',
                    {pinned: pin.getAttribute('data-pinned') !== '1'})
                    .then(iris_wroom_load_stream);
            }
        });

    /* Room tasks (v3 tab) */
    document.getElementById('iris-wr-rtask-new')
        .addEventListener('click', function () {
            iris_wroom_rt_open_modal(null, null);
        });
    document.getElementById('iris-wr-rt-viewlist')
        .addEventListener('click', function () {
            IRIS_WROOM_RT.view = 'list';
            this.className = 'btn btn-dark';
            document.getElementById('iris-wr-rt-viewboard').className =
                'btn btn-outline-dark';
            iris_wroom_rt_render();
        });
    document.getElementById('iris-wr-rt-viewboard')
        .addEventListener('click', function () {
            IRIS_WROOM_RT.view = 'board';
            this.className = 'btn btn-dark';
            document.getElementById('iris-wr-rt-viewlist').className =
                'btn btn-outline-dark';
            iris_wroom_rt_render();
        });
    document.getElementById('iris-wr-rt-search')
        .addEventListener('input', function () {
            IRIS_WROOM_RT.q = this.value.trim().toLowerCase();
            iris_wroom_rt_render();
        });
    document.getElementById('iris-wr-rt-filters-btn')
        .addEventListener('click', function () {
            var f = document.getElementById('iris-wr-rt-filters');
            f.style.display = f.style.display === 'none' ? 'flex' : 'none';
        });
    document.getElementById('iris-wr-rt-fstatus')
        .addEventListener('change', function () {
            IRIS_WROOM_RT.fStatus = this.value;
            iris_wroom_rt_render();
        });
    document.getElementById('iris-wr-rt-fassignee')
        .addEventListener('change', function () {
            IRIS_WROOM_RT.fAssignee = this.value;
            iris_wroom_rt_render();
        });
    function rtClick(e) {
        var toggle = e.target.closest('.iris-wr-rt-toggle');
        if (toggle) {
            iris_wroom_api('PUT',
                '/room-tasks/' + toggle.getAttribute('data-task-id'),
                {status: toggle.checked ? 'done' : 'todo'})
                .then(iris_wroom_load_room_tasks);
            return;
        }
        var addsub = e.target.closest('.iris-wr-rt-addsub');
        if (addsub) {
            e.preventDefault();
            e.stopPropagation();
            iris_wroom_rt_open_modal(null,
                parseInt(addsub.getAttribute('data-task-id'), 10));
            return;
        }
        var del = e.target.closest('.iris-wr-rt-del');
        if (del) {
            e.preventDefault();
            e.stopPropagation();
            iris_wroom_api('DELETE',
                '/room-tasks/' + del.getAttribute('data-task-id'))
                .then(iris_wroom_load_room_tasks);
            return;
        }
        var row = e.target.closest('.iris-wr-rt-row, .iris-wr-rt-card');
        if (row) {
            iris_wroom_rt_open_modal(
                parseInt(row.getAttribute('data-task-id'), 10), null);
        }
    }
    document.getElementById('iris-wr-rtask-list')
        .addEventListener('click', rtClick);
    document.getElementById('iris-wr-rtask-board')
        .addEventListener('click', rtClick);
    /* Board drag-and-drop: drop a card on a column to change its status. */
    var rtBoard = document.getElementById('iris-wr-rtask-board');
    rtBoard.addEventListener('dragstart', function (e) {
        var card = e.target.closest('.iris-wr-rt-card');
        if (!card) return;
        e.dataTransfer.setData('text/plain',
            card.getAttribute('data-task-id'));
        e.dataTransfer.effectAllowed = 'move';
    });
    rtBoard.addEventListener('dragover', function (e) {
        var col = e.target.closest('.iris-wr-rt-col[data-droppable]');
        if (!col) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        col.classList.add('dragover');
    });
    rtBoard.addEventListener('dragleave', function (e) {
        var col = e.target.closest('.iris-wr-rt-col');
        if (col && !col.contains(e.relatedTarget)) {
            col.classList.remove('dragover');
        }
    });
    rtBoard.addEventListener('drop', function (e) {
        var col = e.target.closest('.iris-wr-rt-col[data-droppable]');
        if (!col) return;
        e.preventDefault();
        col.classList.remove('dragover');
        var id = parseInt(e.dataTransfer.getData('text/plain'), 10);
        var st = col.getAttribute('data-status');
        var t = IRIS_WROOM_RT.tasks.find(function (x) { return x.id === id; });
        if (!id || !st || !t || t.status === st) return;
        iris_wroom_api('PUT', '/room-tasks/' + id, {status: st})
            .then(iris_wroom_load_room_tasks);
    });
    document.getElementById('iris-wr-rtask-f-save')
        .addEventListener('click', function () {
            var body = {
                title: document.getElementById('iris-wr-rtask-f-title').value,
                description: document.getElementById('iris-wr-rtask-f-desc').value,
                status: document.getElementById('iris-wr-rtask-f-status').value,
                due_date: document.getElementById('iris-wr-rtask-f-due').value || null,
                assignee_id: (function () {
                    var v = document.getElementById('iris-wr-rtask-f-assignee').value;
                    return v ? parseInt(v, 10) : null;
                })(),
                tags: document.getElementById('iris-wr-rtask-f-tags').value
            };
            var p;
            if (IRIS_WROOM_RT.editing) {
                p = iris_wroom_api('PUT',
                    '/room-tasks/' + IRIS_WROOM_RT.editing, body);
            } else {
                if (IRIS_WROOM_RT.parentFor) {
                    body.parent_task_id = IRIS_WROOM_RT.parentFor;
                }
                p = iris_wroom_api('POST', '/room-tasks', body);
            }
            p.then(function (res) {
                if (!res.ok) {
                    var err = document.getElementById('iris-wr-rtask-f-error');
                    err.textContent = res.j.message || 'Save failed';
                    err.style.display = '';
                    return;
                }
                $('#iris-wr-rtask-modal').modal('hide');
                iris_wroom_load_room_tasks();
            });
        });
    document.getElementById('iris-wr-rtask-f-delete')
        .addEventListener('click', function () {
            if (!IRIS_WROOM_RT.editing) return;
            iris_wroom_api('DELETE', '/room-tasks/' + IRIS_WROOM_RT.editing)
                .then(function (res) {
                    if (res.ok) {
                        $('#iris-wr-rtask-modal').modal('hide');
                        iris_wroom_load_room_tasks();
                    }
                });
        });

    /* Timelines tab */
    document.getElementById('iris-wr-tl-add')
        .addEventListener('click', function (e) {
            e.preventDefault();
            iris_wroom_tl_open_modal(null);
        });
    document.getElementById('iris-wr-tl-f-name')
        .addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                document.getElementById('iris-wr-tl-f-create').click();
            }
        });
    document.getElementById('iris-wr-tl-f-create')
        .addEventListener('click', function () {
            var name = document.getElementById('iris-wr-tl-f-name')
                .value.trim();
            if (!name) {
                document.getElementById('iris-wr-tl-f-name').focus();
                return;
            }
            var color = document.getElementById('iris-wr-tl-f-color').value;
            var editing = IRIS_WROOM_TL._editingTl;
            var p = editing
                ? iris_wroom_api('PUT', '/timelines/' + editing.id,
                                 {name: name, color: color})
                : iris_wroom_api('POST', '/timelines',
                                 {name: name, color: color});
            p.then(function (res) {
                if (!res.ok) return;
                $('#iris-wr-tl-modal').modal('hide');
                var after = IRIS_WROOM_TL._afterCreate;
                IRIS_WROOM_TL._afterCreate = null;
                IRIS_WROOM_TL._editingTl = null;
                if (after) after(res.j);
                iris_wroom_load_timelines();
            });
        });
    document.getElementById('iris-wr-tl-showall')
        .addEventListener('click', function (e) {
            e.preventDefault();
            IRIS_WROOM_TL.roomSel = {};
            IRIS_WROOM_TL.caseSel = {};
            IRIS_WROOM_TL.q = '';
            IRIS_WROOM_TL.cat = '';
            IRIS_WROOM_TL.from = '';
            IRIS_WROOM_TL.to = '';
            document.getElementById('iris-wr-tl-search').value = '';
            document.getElementById('iris-wr-tl-cat').value = '';
            document.getElementById('iris-wr-tl-from').value = '';
            document.getElementById('iris-wr-tl-to').value = '';
            iris_wroom_tl_render_rail();
            iris_wroom_tl_render();
        });
    document.getElementById('iris-wr-tl-roomlist')
        .addEventListener('change', function (e) {
            var cb = e.target.closest('.iris-wr-tl-roomtoggle');
            if (!cb) return;
            IRIS_WROOM_TL.roomSel[
                parseInt(cb.getAttribute('data-timeline-id'), 10)] = cb.checked;
            iris_wroom_tl_render();
        });
    document.getElementById('iris-wr-tl-roomlist')
        .addEventListener('click', function (e) {
            var add = e.target.closest('.iris-wr-tl-addev');
            if (add) {
                e.preventDefault();
                iris_wroom_tlev_open(null,
                    parseInt(add.getAttribute('data-timeline-id'), 10));
                return;
            }
            var ed = e.target.closest('.iris-wr-tl-edit');
            if (ed) {
                e.preventDefault();
                var tid = parseInt(ed.getAttribute('data-timeline-id'), 10);
                var tl = (IRIS_WROOM_TL.data.timelines || []).find(
                    function (t) { return t.id === tid; });
                if (tl) iris_wroom_tl_open_modal(null, tl);
                return;
            }
            var del = e.target.closest('.iris-wr-tl-del');
            if (!del) return;
            e.preventDefault();
            if (!window.confirm('Delete this room timeline and its events?'))
                return;
            iris_wroom_api('DELETE',
                '/timelines/' + del.getAttribute('data-timeline-id'))
                .then(iris_wroom_load_timelines);
        });
    document.getElementById('iris-wr-tl-caselist')
        .addEventListener('change', function (e) {
            var cb = e.target.closest('.iris-wr-tl-casetoggle');
            if (!cb) return;
            IRIS_WROOM_TL.caseSel[
                parseInt(cb.getAttribute('data-case-id'), 10)] = cb.checked;
            iris_wroom_tl_render_rail();
            iris_wroom_tl_render();
        });
    document.getElementById('iris-wr-tl-search')
        .addEventListener('input', function () {
            IRIS_WROOM_TL.q = this.value.trim().toLowerCase();
            iris_wroom_tl_render();
        });
    document.getElementById('iris-wr-tl-cat')
        .addEventListener('change', function () {
            IRIS_WROOM_TL.cat = this.value;
            iris_wroom_tl_render();
        });
    document.getElementById('iris-wr-tl-from')
        .addEventListener('change', function () {
            IRIS_WROOM_TL.from = this.value;
            iris_wroom_tl_render();
        });
    document.getElementById('iris-wr-tl-to')
        .addEventListener('change', function () {
            IRIS_WROOM_TL.to = this.value;
            iris_wroom_tl_render();
        });
    document.getElementById('iris-wr-tl-viewlist')
        .addEventListener('click', function () {
            IRIS_WROOM_TL.view = 'list';
            this.className = 'btn btn-dark';
            document.getElementById('iris-wr-tl-viewtree').className =
                'btn btn-outline-dark';
            iris_wroom_tl_render();
        });
    document.getElementById('iris-wr-tl-viewtree')
        .addEventListener('click', function () {
            IRIS_WROOM_TL.view = 'tree';
            this.className = 'btn btn-dark';
            document.getElementById('iris-wr-tl-viewlist').className =
                'btn btn-outline-dark';
            iris_wroom_tl_render();
        });
    document.getElementById('iris-wr-tl-addevent')
        .addEventListener('click', function () {
            if (!IRIS_WROOM_TL.data.timelines.length) {
                // No room timeline yet: create one first (v3 modal), then
                // continue straight into the add-event modal.
                iris_wroom_tl_open_modal(function (tl) {
                    IRIS_WROOM_TL.data.timelines.push(tl);
                    iris_wroom_tlev_open(null);
                });
                return;
            }
            iris_wroom_tlev_open(null);
        });
    document.getElementById('iris-wr-tl-list')
        .addEventListener('click', function (e) {
            var ed = e.target.closest('.iris-wr-tlev-edit');
            if (ed) {
                e.preventDefault();
                iris_wroom_tlev_open({
                    timeline_id: parseInt(
                        ed.getAttribute('data-timeline-id'), 10),
                    event_id: parseInt(ed.getAttribute('data-event-id'), 10)
                });
                return;
            }
            var del = e.target.closest('.iris-wr-tlev-del');
            if (del) {
                e.preventDefault();
                iris_wroom_api('DELETE',
                    '/timelines/' + del.getAttribute('data-timeline-id') +
                    '/events/' + del.getAttribute('data-event-id'))
                    .then(iris_wroom_load_timelines);
            }
        });
    document.getElementById('iris-wr-tlev-color')
        .addEventListener('input', function () {
            IRIS_WROOM_TL._tlevColorTouched = true;
        });
    document.getElementById('iris-wr-tlev-timeline')
        .addEventListener('change', function () {
            if (!IRIS_WROOM_TL._tlevColorTouched) {
                document.getElementById('iris-wr-tlev-color').value =
                    iris_wroom_tl_colorof(this.value);
            }
        });
    document.getElementById('iris-wr-tlev-save')
        .addEventListener('click', function () {
            var editing = IRIS_WROOM_TL.editing;
            var body = {
                title: document.getElementById('iris-wr-tlev-title').value,
                event_date: document.getElementById('iris-wr-tlev-date').value,
                category: document.getElementById('iris-wr-tlev-cat').value,
                tags: document.getElementById('iris-wr-tlev-tags').value,
                content: document.getElementById('iris-wr-tlev-content').value
            };
            // Only an explicitly-picked colour is stored; otherwise the
            // event keeps inheriting its timeline's colour.
            if (IRIS_WROOM_TL._tlevColorTouched) {
                body.color =
                    document.getElementById('iris-wr-tlev-color').value;
            }
            var tid = document.getElementById('iris-wr-tlev-timeline').value;
            var p = editing
                ? iris_wroom_api('PUT', '/timelines/' + editing.timeline_id +
                                 '/events/' + editing.event_id, body)
                : iris_wroom_api('POST', '/timelines/' + tid + '/events', body);
            p.then(function (res) {
                if (!res.ok) {
                    var err = document.getElementById('iris-wr-tlev-error');
                    err.textContent = res.j.message || 'Save failed';
                    err.style.display = '';
                    return;
                }
                $('#iris-wr-tlev-modal').modal('hide');
                iris_wroom_load_timelines();
            });
        });
    document.getElementById('iris-wr-tlev-delete')
        .addEventListener('click', function () {
            var editing = IRIS_WROOM_TL.editing;
            if (!editing) return;
            iris_wroom_api('DELETE', '/timelines/' + editing.timeline_id +
                           '/events/' + editing.event_id)
                .then(function (res) {
                    if (res.ok) {
                        $('#iris-wr-tlev-modal').modal('hide');
                        iris_wroom_load_timelines();
                    }
                });
        });

    /* Notes tab */
    document.getElementById('iris-wr-nt-search')
        .addEventListener('input', function () {
            IRIS_WROOM_NT.q = this.value.trim().toLowerCase();
            iris_wroom_nt_render_rail();
        });
    document.getElementById('iris-wr-nt-newfolder')
        .addEventListener('click', function (e) {
            e.preventDefault();
            IRIS_WROOM_NT.folderEdit = {mode: 'new'};
            iris_wroom_nt_render_rail();
        });
    document.getElementById('iris-wr-nt-newnote')
        .addEventListener('click', function (e) {
            e.preventDefault();
            iris_wroom_api('POST', '/notes/room', {}).then(function (res) {
                if (!res.ok) return;
                iris_wroom_load_notes();
                iris_wroom_nt_open_room(res.j.id);
            });
        });
    document.getElementById('iris-wr-nt-roomlist')
        .addEventListener('click', function (e) {
            if (e.target.closest('.iris-wr-nt-inline')) return;
            var a = e.target.closest('.iris-wr-nt-addin');
            if (a) {
                e.preventDefault();
                iris_wroom_api('POST', '/notes/room',
                    {folder_id: parseInt(
                        a.getAttribute('data-folder-id'), 10)})
                    .then(function (res) {
                        if (!res.ok) return;
                        iris_wroom_load_notes();
                        iris_wroom_nt_open_room(res.j.id);
                    });
                return;
            }
            var rn = e.target.closest('.iris-wr-nt-ren');
            if (rn) {
                e.preventDefault();
                IRIS_WROOM_NT.folderEdit = {mode: 'rename',
                    id: parseInt(rn.getAttribute('data-folder-id'), 10)};
                iris_wroom_nt_render_rail();
                return;
            }
            var df = e.target.closest('.iris-wr-nt-delfolder');
            if (df) {
                e.preventDefault();
                if (!window.confirm(
                        'Delete this folder? Its notes move to the root.'))
                    return;
                iris_wroom_api('DELETE', '/notes/folders/' +
                    df.getAttribute('data-folder-id'))
                    .then(iris_wroom_load_notes);
                return;
            }
            var row = e.target.closest('.iris-wr-nt-row[data-note-id]');
            if (row) {
                iris_wroom_nt_open_room(
                    parseInt(row.getAttribute('data-note-id'), 10));
            }
        });
    document.getElementById('iris-wr-nt-roomlist')
        .addEventListener('keydown', function (e) {
            var inline = e.target.closest('.iris-wr-nt-inline');
            if (!inline || e.target.tagName !== 'INPUT') return;
            if (e.key === 'Escape') {
                IRIS_WROOM_NT.folderEdit = null;
                iris_wroom_nt_render_rail();
                return;
            }
            if (e.key !== 'Enter') return;
            e.preventDefault();
            var name = e.target.value.trim();
            if (!name) return;
            var fid = inline.getAttribute('data-folder-id');
            var p = fid
                ? iris_wroom_api('PUT', '/notes/folders/' + fid, {name: name})
                : iris_wroom_api('POST', '/notes/folders', {name: name});
            p.then(function (res) {
                if (!res.ok) return;
                IRIS_WROOM_NT.folderEdit = null;
                iris_wroom_load_notes();
            });
        });
    document.getElementById('iris-wr-nt-roomlist')
        .addEventListener('focusout', function (e) {
            /* Clicking away cancels an inline folder editor. */
            if (e.target.tagName === 'INPUT'
                    && e.target.closest('.iris-wr-nt-inline')) {
                setTimeout(function () {
                    if (IRIS_WROOM_NT.folderEdit) {
                        IRIS_WROOM_NT.folderEdit = null;
                        iris_wroom_nt_render_rail();
                    }
                }, 150);
            }
        });
    document.getElementById('iris-wr-nt-caselist')
        .addEventListener('click', function (e) {
            var row = e.target.closest('.iris-wr-nt-row[data-case-note-id]');
            if (!row) return;
            iris_wroom_nt_open_case(
                parseInt(row.getAttribute('data-case-id'), 10),
                parseInt(row.getAttribute('data-case-note-id'), 10));
        });
    document.getElementById('iris-wr-nt-view')
        .addEventListener('dblclick', function () {
            var s = IRIS_WROOM_NT;
            if (!s.sel || s.sel.type !== 'room'
                    || !iris_wroom_nt_can_edit()) return;
            this.style.display = 'none';
            var ed = document.getElementById('iris-wr-nt-edit');
            ed.value = (s.doc && s.doc.content) || '';
            ed.style.display = '';
            ed.focus();
        });
    document.getElementById('iris-wr-nt-edit')
        .addEventListener('input', function () {
            if (IRIS_WROOM_NT.doc) {
                IRIS_WROOM_NT.doc.content = this.value;
            }
            iris_wroom_nt_queue_save();
        });
    document.getElementById('iris-wr-nt-edit')
        .addEventListener('keydown', function (e) {
            if (e.key === 'Escape') this.blur();
        });
    document.getElementById('iris-wr-nt-edit')
        .addEventListener('blur', function () {
            this.style.display = 'none';
            var view = document.getElementById('iris-wr-nt-view');
            view.style.display = '';
            iris_wroom_nt_flush_save();
            var doc = IRIS_WROOM_NT.doc;
            /* flush_save refreshes content_html async; show what we have and
               let its callback repaint when the render lands. */
            setTimeout(function () {
                if (doc && doc === IRIS_WROOM_NT.doc) {
                    view.innerHTML = doc.content_html
                        || '<div class="iris-wr-nt-hintline">Double-click to edit...</div>';
                }
            }, 400);
        });
    var ntTitleTimer = null;
    document.getElementById('iris-wr-nt-title')
        .addEventListener('input', function () {
            var s = IRIS_WROOM_NT;
            if (!s.sel || s.sel.type !== 'room' || this.readOnly) return;
            var val = this.value;
            var id = s.sel.id;
            iris_wroom_nt_status('Saving...');
            if (ntTitleTimer) clearTimeout(ntTitleTimer);
            ntTitleTimer = setTimeout(function () {
                if (!val.trim()) return;
                iris_wroom_api('PUT', '/notes/room/' + id, {title: val})
                    .then(function (res) {
                        if (!res.ok) {
                            iris_wroom_nt_status('Save failed');
                            return;
                        }
                        iris_wroom_nt_status('Changes saved');
                        var row = (IRIS_WROOM_NT.data.room_notes || [])
                            .find(function (n) { return n.id === id; });
                        if (row) row.title = res.j.title;
                        iris_wroom_nt_render_rail();
                    });
            }, 800);
        });
    document.getElementById('iris-wr-nt-del')
        .addEventListener('click', function (e) {
            e.preventDefault();
            var s = IRIS_WROOM_NT;
            if (!s.sel || s.sel.type !== 'room') return;
            if (!window.confirm('Delete this room note?')) return;
            iris_wroom_api('DELETE', '/notes/room/' + s.sel.id)
                .then(function (res) {
                    if (!res.ok) return;
                    s.sel = null; s.doc = null; s.dirty = false;
                    document.getElementById('iris-wr-nt-doc')
                        .style.display = 'none';
                    document.getElementById('iris-wr-nt-placeholder')
                        .style.display = '';
                    iris_wroom_load_notes();
                });
        });

    document.getElementById('iris-wr-edit-btn')
        .addEventListener('click', function () {
            var r = IRIS_WROOM._room;
            document.getElementById('iris-wr-edit-name').value = r.name;
            document.getElementById('iris-wr-edit-desc').value = r.description || '';
            document.getElementById('iris-wr-edit-severity').value = r.severity || '';
            document.getElementById('iris-wr-edit-summary').value = r.summary || '';
            document.getElementById('iris-wr-edit-error').style.display = 'none';
            $('#iris-wr-edit-modal').modal('show');
        });

    document.getElementById('iris-wr-edit-save')
        .addEventListener('click', function () {
            iris_wroom_api('PUT', '', {
                name: document.getElementById('iris-wr-edit-name').value,
                description: document.getElementById('iris-wr-edit-desc').value,
                severity: document.getElementById('iris-wr-edit-severity').value,
                summary: document.getElementById('iris-wr-edit-summary').value
            }).then(function (res) {
                if (!res.ok) {
                    var err = document.getElementById('iris-wr-edit-error');
                    err.textContent = res.j.message || 'Save failed';
                    err.style.display = '';
                    return;
                }
                $('#iris-wr-edit-modal').modal('hide');
                iris_wroom_load_room();
            });
        });

    document.getElementById('iris-wr-status-select')
        .addEventListener('change', function () {
            iris_wroom_api('POST', '/status', {status: this.value})
                .then(function () { iris_wroom_load_room(); });
        });

    document.getElementById('iris-wr-delete-btn')
        .addEventListener('click', function () {
            var r = IRIS_WROOM._room || {};
            swal({
                title: 'Delete this war room?',
                text: 'This permanently deletes "' + (r.name || 'this room')
                    + '" with its stream, SitReps, tasks, notes, polls and '
                    + 'room timelines. Linked cases are NOT touched, and a '
                    + 'promoted cluster becomes promotable again.',
                icon: 'warning',
                buttons: true,
                dangerMode: true
            }).then(function (confirmed) {
                if (!confirmed) { return; }
                // Empty body on purpose: iris_wroom_api only attaches the
                // csrf_token when a body object is present.
                iris_wroom_api('POST', '/delete', {}).then(function (res) {
                    if (!res.ok) {
                        notify_error((res.j && res.j.message)
                            ? res.j.message : 'Could not delete the room');
                        return;
                    }
                    window.location.href = '/war-rooms' + case_param();
                });
            });
        });

    /* SitReps */
    document.getElementById('iris-wr-sitrep-new')
        .addEventListener('click', function (e) {
            e.preventDefault();
            document.getElementById('iris-wr-srnew-title').value = '';
            $('#iris-wr-srnew-modal').modal('show');
            setTimeout(function () {
                document.getElementById('iris-wr-srnew-title').focus();
            }, 300);
        });
    function srnewCreate() {
        var title = document.getElementById('iris-wr-srnew-title')
            .value.trim();
        if (!title) {
            document.getElementById('iris-wr-srnew-title').focus();
            return;
        }
        iris_wroom_api('POST', '/sitreps',
            {title: title, content: IRIS_WROOM_SR_SKELETON})
            .then(function (res) {
                if (!res.ok) return;
                $('#iris-wr-srnew-modal').modal('hide');
                iris_wroom_load_sitreps();
                iris_wroom_sr_show(res.j, 'edit');
            });
    }
    document.getElementById('iris-wr-srnew-create')
        .addEventListener('click', srnewCreate);
    document.getElementById('iris-wr-srnew-title')
        .addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); srnewCreate(); }
        });
    document.getElementById('iris-wr-sitrep-ai')
        .addEventListener('click', function () {
            iris_wroom_ai_status('AI drafting…');
            iris_wroom_api('POST', '/sitreps/ai-draft', {force: true})
                .then(function (res) {
                    if (res.status === 202 && res.j.task_id) {
                        iris_wroom_poll_draft(res.j.task_id, 0);
                    } else if (res.ok) {
                        iris_wroom_ai_status('');
                        iris_wroom_open_draft(res.j);
                    } else {
                        iris_wroom_ai_status('AI draft failed: ' +
                            (res.j.message || res.status));
                    }
                });
        });
    document.getElementById('iris-wr-sitrep-list')
        .addEventListener('click', function (e) {
            var row = e.target.closest('.iris-wr-sitrep-item');
            if (row) {
                iris_wroom_open_sitrep(
                    parseInt(row.getAttribute('data-sitrep-id'), 10));
            }
        });
    document.getElementById('iris-wr-sr-editbtn')
        .addEventListener('click', function () {
            if (IRIS_WROOM_SR.cur) {
                iris_wroom_sr_show(IRIS_WROOM_SR.cur, 'edit');
            }
        });
    document.getElementById('iris-wr-sr-cancel')
        .addEventListener('click', function () {
            if (IRIS_WROOM_SR.cur) {
                /* Discard unsaved changes: reload from the server (drafts
                   reopen in edit, published in read). */
                iris_wroom_open_sitrep(IRIS_WROOM_SR.cur.id,
                    IRIS_WROOM_SR.cur.status === 'published' ? 'read' : null);
            }
        });
    document.getElementById('iris-wr-sr-save')
        .addEventListener('click', function () { iris_wroom_sr_save(); });
    document.getElementById('iris-wr-sr-publishbtn')
        .addEventListener('click', function () {
            /* Save the current text first, then confirm the publish. */
            iris_wroom_sr_save(function (s) {
                document.getElementById('iris-wr-srpub-title').textContent =
                    'Publish "' + s.title + '"?';
                $('#iris-wr-srpub-modal').modal('show');
            });
        });
    document.getElementById('iris-wr-srpub-confirm')
        .addEventListener('click', function () {
            var s = IRIS_WROOM_SR.cur;
            if (!s) return;
            iris_wroom_api('POST', '/sitreps/' + s.id + '/publish', {})
                .then(function (res) {
                    $('#iris-wr-srpub-modal').modal('hide');
                    if (!res.ok) {
                        document.getElementById('iris-wr-sr-status')
                            .textContent = res.j.message || 'Publish failed';
                        return;
                    }
                    iris_wroom_load_sitreps();
                    iris_wroom_sr_show(res.j, 'read');
                    document.getElementById('iris-wr-sr-status').textContent =
                        'SitRep v' + (res.j.version || 1) + ' published';
                });
        });
    document.getElementById('iris-wr-sr-del')
        .addEventListener('click', function (e) {
            e.preventDefault();
            var s = IRIS_WROOM_SR.cur;
            if (!s) return;
            if (!window.confirm('Delete SitRep "' + s.title + '"?')) return;
            iris_wroom_api('DELETE', '/sitreps/' + s.id)
                .then(function (res) {
                    if (!res.ok) return;
                    IRIS_WROOM_SR.cur = null;
                    document.getElementById('iris-wr-sr-doc')
                        .style.display = 'none';
                    document.getElementById('iris-wr-sr-placeholder')
                        .style.display = '';
                    iris_wroom_load_sitreps();
                });
        });
    document.querySelector('.iris-wr-sr-toolbar')
        .addEventListener('click', function (e) {
            var b = e.target.closest('.iris-wr-sr-md');
            if (b) {
                e.preventDefault();
                iris_wroom_sr_md(b.getAttribute('data-md'));
                return;
            }
            if (e.target.closest('#iris-wr-sr-preview-toggle')) {
                e.preventDefault();
                iris_wroom_sr_toggle_preview();
            }
        });
    document.querySelectorAll('.iris-wr-sr-export').forEach(function (a) {
        a.addEventListener('click', function (e) {
            e.preventDefault();
            iris_wroom_sr_export(this.getAttribute('data-fmt'));
        });
    });

    /* Members (v3 tab) */
    var mbaddSel = null;
    function mbaddRender() {
        var memberIds = {};
        ((IRIS_WROOM._room && IRIS_WROOM._room.members) || [])
            .forEach(function (m) { memberIds[m.user_id] = true; });
        var q = document.getElementById('iris-wr-mbadd-search')
            .value.trim().toLowerCase();
        var rows = (IRIS_WROOM._users || []).filter(function (u) {
            if (memberIds[u.user_id]) return false;
            var hay = ((u.user_name || '') + ' ' +
                (u.user_login || '')).toLowerCase();
            return !q || hay.indexOf(q) !== -1;
        });
        document.getElementById('iris-wr-mbadd-list').innerHTML =
            rows.length ? rows.map(function (u) {
                return '<div class="iris-wr-mbadd-row' +
                    (mbaddSel === u.user_id ? ' selected' : '') +
                    '" data-user-id="' + u.user_id + '">' +
                    '<span>' + iris_wroom_esc(u.user_name || '') + '</span>' +
                    '<span class="iris-wr-mb-login">@' +
                    iris_wroom_esc(u.user_login || '') + '</span></div>';
            }).join('')
            : '<div class="iris-wr-rail-hint">No matching users.</div>';
    }
    document.getElementById('iris-wr-member-addbtn')
        .addEventListener('click', function () {
            mbaddSel = null;
            document.getElementById('iris-wr-mbadd-search').value = '';
            document.getElementById('iris-wr-mbadd-role').value = 'responder';
            mbaddRender();
            $('#iris-wr-mbadd-modal').modal('show');
            setTimeout(function () {
                document.getElementById('iris-wr-mbadd-search').focus();
            }, 300);
        });
    document.getElementById('iris-wr-mbadd-search')
        .addEventListener('input', mbaddRender);
    document.getElementById('iris-wr-mbadd-list')
        .addEventListener('click', function (e) {
            var row = e.target.closest('.iris-wr-mbadd-row');
            if (!row) return;
            mbaddSel = parseInt(row.getAttribute('data-user-id'), 10);
            mbaddRender();
        });
    document.getElementById('iris-wr-mbadd-go')
        .addEventListener('click', function () {
            if (!mbaddSel) return;
            iris_wroom_api('POST', '/members', {
                user_id: mbaddSel,
                role: document.getElementById('iris-wr-mbadd-role').value
            }).then(function (res) {
                if (!res.ok) return;
                $('#iris-wr-mbadd-modal').modal('hide');
                iris_wroom_load_room();
            });
        });
    document.getElementById('iris-wr-mb-list')
        .addEventListener('click', function (e) {
            var a = e.target.closest('.iris-wr-member-remove');
            if (!a) return;
            e.preventDefault();
            if (!window.confirm('Remove this member from the room?')) return;
            iris_wroom_api('DELETE', '/members/' + a.getAttribute('data-user-id'))
                .then(function () { iris_wroom_load_room(); });
        });

    /* Teams (v3 tab) */
    document.getElementById('iris-wr-team-newbtn')
        .addEventListener('click', function () {
            document.getElementById('iris-wr-tm-f-name').value = '';
            document.getElementById('iris-wr-tm-f-desc').value = '';
            document.getElementById('iris-wr-tm-f-color').value = '#5e72e4';
            document.getElementById('iris-wr-tm-f-error').style.display =
                'none';
            $('#iris-wr-tmnew-modal').modal('show');
            setTimeout(function () {
                document.getElementById('iris-wr-tm-f-name').focus();
            }, 300);
        });
    document.getElementById('iris-wr-tm-f-create')
        .addEventListener('click', function () {
            iris_wroom_api('POST', '/teams', {
                name: document.getElementById('iris-wr-tm-f-name').value,
                description:
                    document.getElementById('iris-wr-tm-f-desc').value,
                color: document.getElementById('iris-wr-tm-f-color').value
            }).then(function (res) {
                if (!res.ok) {
                    var err = document.getElementById('iris-wr-tm-f-error');
                    err.textContent = res.j.message || 'Create failed';
                    err.style.display = '';
                    return;
                }
                $('#iris-wr-tmnew-modal').modal('hide');
                IRIS_WROOM_TM.teams = res.j.teams || [];
                iris_wroom_tm_render();
            });
        });
    document.getElementById('iris-wr-tm-f-name')
        .addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                document.getElementById('iris-wr-tm-f-create').click();
            }
        });
    document.getElementById('iris-wr-tm-list')
        .addEventListener('click', function (e) {
            var h = e.target.closest('.iris-wr-tm-hide');
            if (h) {
                e.preventDefault();
                var tid = parseInt(h.getAttribute('data-team-id'), 10);
                IRIS_WROOM_TM.hidden[tid] = !IRIS_WROOM_TM.hidden[tid];
                iris_wroom_tm_render();
                return;
            }
            var a = e.target.closest('.iris-wr-tm-add');
            if (a) {
                e.preventDefault();
                var atid = parseInt(a.getAttribute('data-team-id'), 10);
                IRIS_WROOM_TM.addFor =
                    IRIS_WROOM_TM.addFor === atid ? null : atid;
                IRIS_WROOM_TM.hidden[atid] = false;
                iris_wroom_tm_render();
                return;
            }
            var d = e.target.closest('.iris-wr-tm-del');
            if (d) {
                e.preventDefault();
                if (!window.confirm('Delete this team? (Members are only ' +
                        'ungrouped — nothing else changes.)')) return;
                iris_wroom_api('DELETE',
                    '/teams/' + d.getAttribute('data-team-id'))
                    .then(iris_wroom_load_teams);
                return;
            }
            var rm = e.target.closest('.iris-wr-tm-rmmember');
            if (rm) {
                e.preventDefault();
                iris_wroom_api('DELETE',
                    '/teams/' + rm.getAttribute('data-team-id') +
                    '/members/' + rm.getAttribute('data-user-id'))
                    .then(function (res) {
                        if (!res.ok) return;
                        IRIS_WROOM_TM.teams = res.j.teams || [];
                        iris_wroom_tm_render();
                    });
            }
        });
    document.getElementById('iris-wr-tm-list')
        .addEventListener('change', function (e) {
            var sel = e.target.closest('.iris-wr-tm-addsel');
            if (!sel || !sel.value) return;
            iris_wroom_api('POST',
                '/teams/' + sel.getAttribute('data-team-id') + '/members',
                {user_id: parseInt(sel.value, 10)})
                .then(function (res) {
                    if (!res.ok) return;
                    IRIS_WROOM_TM.teams = res.j.teams || [];
                    iris_wroom_tm_render();
                });
        });

    /* Cases (v3 tab) */
    document.getElementById('iris-wr-cs-filter')
        .addEventListener('input', function () {
            IRIS_WROOM_CS.q = this.value.trim().toLowerCase();
            iris_wroom_render_cases();
        });
    document.getElementById('iris-wr-pane-cases')
        .addEventListener('click', function (e) {
            var chip = e.target.closest('.iris-wr-cs-chip');
            if (!chip) return;
            var group = chip.getAttribute('data-group');
            IRIS_WROOM_CS[group] = chip.getAttribute('data-val');
            document.querySelectorAll(
                '.iris-wr-cs-chip[data-group="' + group + '"]')
                .forEach(function (c) { c.classList.remove('active'); });
            chip.classList.add('active');
            iris_wroom_render_cases();
        });
    function csattRender() {
        var attached = {};
        ((IRIS_WROOM._room && IRIS_WROOM._room.cases) || [])
            .forEach(function (c) { attached[c.case_id] = true; });
        var q = document.getElementById('iris-wr-csatt-search')
            .value.trim().toLowerCase();
        var rows = (IRIS_WROOM._allCases || []).filter(function (c) {
            var id = c.case_id !== undefined ? c.case_id : c.id;
            if (attached[id]) return false;
            var label = '#' + id + ' ' + (c.case_name || c.name || '');
            return !q || label.toLowerCase().indexOf(q) !== -1;
        });
        document.getElementById('iris-wr-csatt-list').innerHTML =
            rows.length ? rows.map(function (c) {
                var id = c.case_id !== undefined ? c.case_id : c.id;
                return '<label class="iris-wr-csatt-row">' +
                    '<input type="checkbox" class="iris-wr-csatt-cb" ' +
                    'value="' + id + '" style="accent-color:#5e72e4;">' +
                    '<span>#' + id + ' - ' +
                    iris_wroom_esc(c.case_name || c.name || '') +
                    '</span></label>';
            }).join('')
            : '<div class="iris-wr-rail-hint">No unattached cases match.</div>';
    }
    document.getElementById('iris-wr-case-attachbtn')
        .addEventListener('click', function () {
            document.getElementById('iris-wr-csatt-search').value = '';
            csattRender();
            $('#iris-wr-csatt-modal').modal('show');
        });
    document.getElementById('iris-wr-csatt-search')
        .addEventListener('input', csattRender);
    document.getElementById('iris-wr-csatt-go')
        .addEventListener('click', function () {
            var ids = Array.prototype.slice.call(
                document.querySelectorAll('.iris-wr-csatt-cb:checked'))
                .map(function (cb) { return parseInt(cb.value, 10); });
            if (!ids.length) return;
            /* Sequential attach — each POST re-validates existence + the
               actor's own case ACL server-side. */
            var next = function () {
                if (!ids.length) {
                    $('#iris-wr-csatt-modal').modal('hide');
                    iris_wroom_load_room();
                    return;
                }
                iris_wroom_api('POST', '/cases', {case_id: ids.shift()})
                    .then(next);
            };
            next();
        });
    document.getElementById('iris-wr-cs-list')
        .addEventListener('click', function (e) {
            if (e.target.closest('.iris-wr-nt-inline')
                    || e.target.closest('a[href^="/case"]')) return;
            var ne = e.target.closest('.iris-wr-cs-noteedit');
            if (ne) {
                e.preventDefault();
                IRIS_WROOM_CS.noteEdit =
                    parseInt(ne.getAttribute('data-case-id'), 10);
                iris_wroom_render_cases();
                return;
            }
            var del = e.target.closest('.iris-wr-cs-detach');
            if (del) {
                e.preventDefault();
                if (!window.confirm('Detach this case from the room?')) return;
                iris_wroom_api('DELETE',
                    '/cases/' + del.getAttribute('data-case-id'))
                    .then(function () { iris_wroom_load_room(); });
                return;
            }
            var row = e.target.closest('.iris-wr-cs-row');
            if (row && row.getAttribute('data-accessible') === '1') {
                iris_wroom_cs_peek(
                    parseInt(row.getAttribute('data-case-id'), 10));
            }
        });
    document.getElementById('iris-wr-cs-list')
        .addEventListener('keydown', function (e) {
            var input = e.target.closest('.iris-wr-nt-inline input');
            if (!input) return;
            if (e.key === 'Escape') {
                IRIS_WROOM_CS.noteEdit = null;
                iris_wroom_render_cases();
                return;
            }
            if (e.key !== 'Enter') return;
            e.preventDefault();
            var cid = parseInt(input.getAttribute('data-case-id'), 10);
            iris_wroom_api('PUT', '/cases/' + cid + '/note',
                {note: input.value}).then(function (res) {
                    if (!res.ok) return;
                    IRIS_WROOM_CS.noteEdit = null;
                    var c = (IRIS_WROOM._room.cases || []).find(function (x) {
                        return x.case_id === cid; });
                    if (c) c.note = res.j.note;
                    iris_wroom_render_cases();
                });
        });
    document.getElementById('iris-wr-cs-list')
        .addEventListener('focusout', function (e) {
            if (e.target.closest('.iris-wr-nt-inline')) {
                setTimeout(function () {
                    if (IRIS_WROOM_CS.noteEdit !== null) {
                        IRIS_WROOM_CS.noteEdit = null;
                        iris_wroom_render_cases();
                    }
                }, 150);
            }
        });

    /* Correlation */
    document.getElementById('iris-wr-corr-tag')
        .addEventListener('click', iris_wroom_apply_campaign_tag);
    document.getElementById('iris-wr-corr-misp')
        .addEventListener('click', function () { iris_wroom_misp_push(false); });

    /* Pickers: users (any authenticated user may call analyst-skills) and
     * cases (legacy endpoint — {status,data} envelope, unlike v2). */
    fetch('/api/v2/teams/analyst-skills', {headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (data) {
            var users = (Array.isArray(data) ? data : [])
                .filter(function (u) { return !u.is_service_account; });
            IRIS_WROOM._users = users;   /* @login resolution, add-member
                                            modal, task assignee pickers */
            var asel = document.getElementById('iris-wr-rtask-f-assignee');
            var fsel = document.getElementById('iris-wr-rt-fassignee');
            users.forEach(function (u) {
                var opt = document.createElement('option');
                opt.value = u.user_id;
                opt.textContent = u.user_name + ' (' + u.user_login + ')';
                asel.appendChild(opt);
                fsel.appendChild(opt.cloneNode(true));
            });
        });
    fetch('/manage/cases/list?cid=' + IRIS_WROOM._cid,
          {headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (resp) {
            /* Feeds the v3 Attach-cases modal; the list is already scoped
               to cases the actor can see (legacy endpoint enforces ACL). */
            IRIS_WROOM._allCases = (resp && resp.data) || [];
        });
});

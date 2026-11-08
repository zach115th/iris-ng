/* War-room Stream (iris-ng 2026-11-08).
 *
 * window.IrisRoomStream - import-free (ui/public). The Stream tab in three columns:
 *   Conversation  topics (show / hide / only one / archive / restore), threads, Decisions & Pins, slash commands
 *   the chat      messages (grouped by author), polls, and every lane a person routes to the chat; reactions,
 *                 edit / delete, pins, threads, attachments, emoji, paging back in time
 *   Activity      the lanes routed to the panel (case activity, war-room activity, tasks, system by default):
 *                 filter, lane chips with counts, hour headers, folded bursts, pause, "Discuss in chat", mutes
 * plus the Activity settings (where each lane goes, fold bursts, quiet mode, per-case and per-type mutes; saved
 * to the user's profile, in this browser for a guest) and the thread panel (replies, rename, follow).
 *
 * war_room.js owns the room (IRIS_WROOM), its helpers (iris_wroom_api, iris_wroom_esc, iris_wroom_avatar,
 * iris_wroom_render_body, iris_wroom_render_poll, iris_wroom_can, iris_wroom_active), the slash commands and
 * the @-mention palette; it calls IrisRoomStream.mount() once the room is loaded, poll() every 5 s and shown()
 * when the tab opens. Server text goes through esc() before any innerHTML build; ids through parseInt.
 * Times are the browser's local time (the API sends UTC with a Z). POST bodies carry csrf_token (the v2 rule).
 */
(function () {
    'use strict';
    if (window.IrisRoomStream) { return; }
    var R = {};
    var $ = window.jQuery;

    /* ------------------------------------------------------------------ icons (Lucide, ISC) */
    var P = {
        x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
        pencil: '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
        trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
        pin: '<path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>',
        thread: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
        react: '<path d="M22 11v1a10 10 0 1 1-9-10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" x2="9.01" y1="9" y2="9"/><line x1="15" x2="15.01" y1="9" y2="9"/><path d="M16 5h6"/><path d="M19 2v6"/>',
        smile: '<circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" x2="9.01" y1="9" y2="9"/><line x1="15" x2="15.01" y1="9" y2="9"/>',
        clip: '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
        sliders: '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>',
        pause: '<rect x="14" y="4" width="4" height="16" rx="1"/><rect x="6" y="4" width="4" height="16" rx="1"/>',
        play: '<polygon points="6 3 20 12 6 21 6 3"/>',
        panel: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M15 3v18"/>',
        archive: '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
        restore: '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h2"/><path d="M20 8v11a2 2 0 0 1-2 2h-2"/><path d="m9 15 3-3 3 3"/><path d="M12 12v9"/>',
        eye: '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
        eyeoff: '<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49"/><path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/><path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143"/><path d="m2 2 20 20"/>',
        briefcase: '<path d="M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/><rect width="20" height="14" x="2" y="6" rx="2"/>',
        users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
        note: '<path d="M16 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V8Z"/><path d="M15 3v4a2 2 0 0 0 2 2h4"/>',
        folder: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
        task: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="m9 12 2 2 4-4"/>',
        clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
        sitrep: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
        shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
        gavel: '<path d="m14.5 12.5-8 8a2.119 2.119 0 1 1-3-3l8-8"/><path d="m16 16 6-6"/><path d="m8 8 6-6"/><path d="m9 7 8 8"/><path d="m21 11-8-8"/>',
        info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
        bell: '<path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"/>',
        belloff: '<path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M17 17H4a1 1 0 0 1-.74-1.673C4.59 13.956 6 12.499 6 8a6 6 0 0 1 .258-1.742"/><path d="m2 2 20 20"/><path d="M8.668 3.01A6 6 0 0 1 18 8c0 2.687.77 4.653 1.707 6.05"/>',
        flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" x2="4" y1="22" y2="15"/>',
        link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
        unlink: '<path d="m18.84 12.25 1.72-1.71h-.02a5.004 5.004 0 0 0-.12-7.07 5.006 5.006 0 0 0-6.95 0l-1.72 1.71"/><path d="m5.17 11.75-1.71 1.71a5.004 5.004 0 0 0 .12 7.07 5.006 5.006 0 0 0 6.95 0l1.71-1.71"/><line x1="8" x2="8" y1="2" y2="5"/><line x1="2" x2="5" y1="8" y2="8"/><line x1="16" x2="16" y1="19" y2="22"/><line x1="19" x2="22" y1="16" y2="16"/>',
        quote: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 12a2 2 0 0 0 2-2V8H8"/><path d="M14 12a2 2 0 0 0 2-2V8h-2"/>',
        dots: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
        activity: '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
        download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
        file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>',
        chevron: '<path d="m6 9 6 6 6-6"/>',
        plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
        search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
        hash: '<line x1="4" x2="20" y1="9" y2="9"/><line x1="4" x2="20" y1="15" y2="15"/><line x1="10" x2="8" y1="3" y2="21"/><line x1="16" x2="14" y1="3" y2="21"/>',
        conv: '<path d="M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z"/><path d="M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1"/>',
        check: '<path d="M20 6 9 17l-5-5"/>'
    };
    function ic(name, cls) {
        return '<svg class="iris-st-ic' + (cls ? ' ' + cls : '') + '" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (P[name] || P.info) + '</svg>';
    }

    /* ---------------------------------------------------------------------------- state */
    var S = {
        rid: null, guest: false, vocab: null, prefs: null, mounted: false,
        chat: {map: {}, cursor: null, done: false, loading: false, q: '', seq: 0},
        rail: {map: {}, cursor: null, done: false, loading: false, filter: '', chip: 'all', paused: false,
               pending: {}, seq: 0},
        expanded: {},            /* burst id -> true */
        topics: [], hidden: {}, only: null, target: 'main', showArchived: false,
        threads: [], index: [], indexQ: '',
        thread: null,            /* {rootId, data} */
        editing: null,           /* message id whose inline editor is open */
        pending: {main: [], thread: []},
        lastMeta: 0
    };
    var SRC = {message: 1, poll: 2, activity: 3, case_activity: 4, decision: 5};
    var LS_PREFS = 'irisRoomStreamPrefs', LS_RECENT = 'irisEmojiRecent';

    function esc(s) { return window.iris_wroom_esc(s); }
    function api(m, p, b) { return window.iris_wroom_api(m, p, b); }
    function room() { return (window.IRIS_WROOM || {})._room || {}; }
    function canPost() { return window.iris_wroom_can('responder') && window.iris_wroom_active(); }
    function canRead() { return window.iris_wroom_active(); }
    function isLead() { return room().my_role === 'lead'; }
    function myGuestId() { return room().viewer_guest ? room().viewer_guest.id : null; }
    function myUserId() { return S.guest ? null : room().viewer_id; }
    function mine(i) {
        if (S.guest) { return !!i.guest_id && i.guest_id === myGuestId(); }
        return !i.guest_id && !!i.user_id && i.user_id === myUserId();
    }
    function $id(x) { return document.getElementById(x); }
    function ls(key, value) {
        try {
            if (value === undefined) { return JSON.parse(window.localStorage.getItem(key) || 'null'); }
            window.localStorage.setItem(key, JSON.stringify(value));
        } catch (e) { /* private window or blocked storage: the page works without it */ }
        return null;
    }
    function status(txt) { var el = $id('iris-wr-cmd-status'); if (el) { el.textContent = txt || ''; } }

    /* ------------------------------------------------------------------------ CSS */
    function css() {
        if ($id('iris-st-css')) { return; }
        var st = document.createElement('style');
        st.id = 'iris-st-css';
        st.textContent = [
            '#iris-st{display:grid;grid-template-columns:300px minmax(0,1fr) var(--iris-st-rail,340px);gap:12px;height:var(--iris-st-h,620px);min-height:480px;}',
            '#iris-st.iris-st-norail{grid-template-columns:300px minmax(0,1fr);}',
            '#iris-st,#iris-st *,.iris-st-emoji *,#iris-st-settings-body{scrollbar-width:thin;scrollbar-color:rgba(255,255,255,.16) transparent;}',
            '#iris-st *:hover{scrollbar-color:rgba(255,255,255,.28) transparent;}',
            '.iris-st-col{border:1px solid rgba(255,255,255,.07);border-radius:10px;background:rgba(255,255,255,.015);display:flex;flex-direction:column;min-height:0;min-width:0;position:relative;}',
            '.iris-st-ic{width:14px;height:14px;flex-shrink:0;vertical-align:-2px;}',
            '.iris-st-h{color:#7a7a85;font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;display:flex;align-items:center;gap:6px;margin:12px 0 6px;}',
            '.iris-st-h svg,.iris-st-convhead svg{width:12px;height:12px;flex-shrink:0;}',
            '.iris-st-conv .iris-st-h{border-top:1px solid rgba(255,255,255,.06);margin:12px -12px 6px;padding:12px 12px 0;}',
            '.iris-st-h > a{margin-left:auto;}',
            '.iris-st-conv{padding:10px 12px;overflow-y:auto;font-size:.8rem;}',
            '.iris-st-convhead{display:flex;align-items:center;gap:6px;color:#7a7a85;font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;padding-bottom:8px;border-bottom:1px solid rgba(255,255,255,.06);}',
            '.iris-st-convhead a{margin-left:auto;text-transform:none;letter-spacing:0;font-size:.72rem;color:#9a9aa5;white-space:nowrap;display:inline-flex;align-items:center;gap:4px;}',
            '.iris-st-convhead a:hover{color:#e8e8ee;text-decoration:none;}',
            '.iris-st-row{display:flex;align-items:center;gap:6px;padding:3px 4px;border-radius:6px;color:#c8c8d0;cursor:pointer;min-width:0;}',
            '.iris-st-row:hover{background:rgba(255,255,255,.04);}',
            '.iris-st-row .iris-st-txt{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;flex:1 1 auto;}',
            '.iris-st-row .iris-st-sub{color:#7a7a85;font-size:.7rem;}',
            '.iris-st-row.iris-st-dim .iris-st-txt{color:#6a6a75;}',
            '.iris-st-row.iris-st-on{background:rgba(139,92,246,.12);}',
            '.iris-st-dot{width:16px;height:16px;border-radius:50%;border:1.5px solid #5a5a66;flex-shrink:0;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;}',
            '.iris-st-dot.iris-st-on{background:#5e72e4;border-color:#5e72e4;}',
            '.iris-st-dot .iris-st-ic{width:11px;height:11px;color:#fff;stroke-width:3;}',
            '.iris-st-badge{font-size:.62rem;padding:0 6px;border-radius:8px;background:rgba(94,114,228,.18);color:#a9b6f5;white-space:nowrap;}',
            '.iris-st-rowact{visibility:hidden;color:#7a7a85;background:none;border:0;padding:0 2px;cursor:pointer;}',
            '.iris-st-row:hover .iris-st-rowact{visibility:visible;}',
            '.iris-st-hint{color:#6a6a75;font-size:.72rem;}',
            '.iris-st-idx{padding:4px;border-radius:6px;cursor:pointer;}',
            '.iris-st-idx:hover{background:rgba(255,255,255,.04);}',
            '.iris-st-idx .iris-st-idxt{color:#c8c8d0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
            '.iris-st-idx .iris-st-idxt{display:flex;align-items:center;gap:6px;}',
            '.iris-st-idx .iris-st-idxt .iris-st-ic{color:#f3d77e;}',
            '.iris-st-idx .iris-st-idxm{color:#7a7a85;font-size:.68rem;margin-left:20px;}',
            '.iris-st-idx .iris-st-idxm b{font-weight:600;text-transform:uppercase;letter-spacing:.04em;font-size:.62rem;}',
            '.iris-st-search{position:relative;margin:6px 0;}',
            '#iris-st .iris-st-search input.form-control{padding:0 10px 0 30px!important;font-size:.78rem;height:32px!important;background:rgba(255,255,255,.02)!important;border:1px solid rgba(255,255,255,.1)!important;border-radius:8px!important;color:#d8d8e0!important;box-shadow:none!important;}',
            '#iris-st .iris-st-search input.form-control:focus{border-color:rgba(94,114,228,.6)!important;}',
            '#iris-st .iris-st-search input.form-control::placeholder{color:#6a6a75;}',
            '.iris-st-search .iris-st-ic{position:absolute;left:10px;top:9px;color:#7a7a85;z-index:3;pointer-events:none;}',
            '.iris-st-main{padding:10px 12px 8px;}',
            '.iris-st-mainhead{display:flex;align-items:center;gap:8px;}',
            '.iris-st-mainhead .iris-st-search{flex:1 1 auto;margin:0;}',
            '.iris-st-matches{color:#7a7a85;font-size:.72rem;white-space:nowrap;}',
            '#iris-wr-chat{flex:1 1 auto;overflow-y:auto;padding:4px 6px;min-height:0;}',
            '.iris-st-start{color:#6a6a75;font-size:.7rem;text-align:center;margin:6px 0 10px;}',
            '.iris-st-loadmore{color:#7a7a85;font-size:.72rem;text-align:center;padding:6px;}',
            '.iris-wr-datesep{text-align:center;color:#7a7a85;font-size:.72rem;margin:12px 0 8px;position:relative;}',
            '.iris-wr-datesep span{background:#15151a;padding:0 10px;position:relative;z-index:1;}',
            '.iris-wr-datesep:before{content:"";position:absolute;left:0;right:0;top:50%;border-top:1px solid rgba(255,255,255,.06);}',
            '.iris-st-msg{display:flex;gap:10px;padding:4px 4px;border-radius:8px;position:relative;}',
            '.iris-st-msg:hover{background:rgba(255,255,255,.025);}',
            '.iris-st-msg.iris-st-compact{padding-top:0;}',
            '.iris-st-msg.iris-st-compact .iris-st-gutter{visibility:hidden;height:0;}',
            '.iris-st-msg.iris-st-flash{box-shadow:0 0 0 2px rgba(139,92,246,.6);}',
            '.iris-st-gutter{width:30px;flex-shrink:0;}',
            '.iris-st-msgmain{min-width:0;flex:1 1 auto;}',
            '.iris-st-msghead{font-size:.8rem;display:flex;align-items:baseline;gap:6px;flex-wrap:wrap;}',
            '.iris-st-msghead strong{color:#e8e8ee;}',
            '.iris-st-time{color:#7a7a85;font-size:.7rem;}',
            '.iris-st-edited{color:#7a7a85;font-size:.68rem;}',
            '.iris-st-kind{font-size:.62rem;padding:0 6px;border-radius:8px;border:1px solid rgba(255,255,255,.12);color:#c8c8d0;}',
            '.iris-st-kind.iris-st-k-decision{border-color:rgba(45,206,137,.5);color:#7fe0b3;}',
            '.iris-st-kind.iris-st-k-note{border-color:rgba(244,196,48,.5);color:#f3d77e;}',
            '.iris-st-body{color:#d8d8e0;font-size:.85rem;white-space:pre-wrap;word-break:break-word;}',
            '.iris-st-quote{display:block;border-left:3px solid rgba(139,92,246,.6);padding:2px 8px;margin:2px 0;color:#b8b8c4;background:rgba(139,92,246,.06);border-radius:0 6px 6px 0;}',
            '.iris-st-files{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px;}',
            '.iris-st-img{display:block;max-width:280px;max-height:200px;border-radius:6px;border:1px solid rgba(255,255,255,.1);}',
            '.iris-st-file{display:inline-flex;align-items:center;gap:6px;border:1px solid rgba(255,255,255,.12);border-radius:6px;padding:3px 8px;font-size:.75rem;color:#c8c8d0;background:rgba(255,255,255,.03);}',
            '.iris-st-file small{color:#7a7a85;}',
            '.iris-st-reacts{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;}',
            '.iris-st-react{border:1px solid rgba(255,255,255,.12);border-radius:10px;background:rgba(255,255,255,.03);padding:0 7px;font-size:.78rem;color:#c8c8d0;cursor:pointer;line-height:1.6;}',
            '.iris-st-react.iris-st-mine{border-color:rgba(94,114,228,.7);background:rgba(94,114,228,.18);}',
            '.iris-st-react[disabled]{cursor:default;}',
            '.iris-st-threadchip{display:inline-flex;align-items:center;gap:5px;margin-top:4px;font-size:.72rem;color:#a9b6f5;border:1px solid rgba(94,114,228,.35);border-radius:10px;padding:0 8px;background:rgba(94,114,228,.08);cursor:pointer;}',
            '.iris-st-actions{position:absolute;right:6px;top:-10px;display:none;gap:2px;background:#1d1d24;border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:2px;z-index:5;}',
            '.iris-st-msg:hover .iris-st-actions,.iris-st-ev:hover .iris-st-actions{display:flex;}',
            '.iris-st-actions button{background:none;border:0;color:#9a9aa5;padding:3px 5px;border-radius:5px;cursor:pointer;}',
            '.iris-st-actions button:hover{background:rgba(255,255,255,.07);color:#e8e8ee;}',
            '.iris-st-ev{display:flex;align-items:flex-start;gap:8px;padding:5px 6px;border-radius:8px;position:relative;font-size:.8rem;color:#c8c8d0;}',
            '.iris-st-ev:hover{background:rgba(255,255,255,.025);}',
            '.iris-st-chat .iris-st-ev{border:1px solid rgba(255,255,255,.06);margin:4px 0;}',
            '.iris-st-ev .iris-st-evic{color:#8fa3ef;margin-top:2px;}',
            '.iris-st-ev .iris-st-evmain{min-width:0;flex:1 1 auto;}',
            '.iris-st-ev strong{color:#e8e8ee;font-weight:600;}',
            '.iris-st-ev.iris-st-priority{border-color:rgba(242,89,97,.45)!important;background:rgba(242,89,97,.07);}',
            '.iris-st-chip{display:inline-flex;align-items:center;gap:4px;font-size:.68rem;padding:0 7px;border-radius:9px;border:1px solid rgba(242,89,97,.4);color:#ff9aa5;background:rgba(242,89,97,.08);margin-left:4px;white-space:nowrap;}',
            '.iris-st-chip.iris-st-c-note{border-color:rgba(56,189,248,.4);color:#7dd3fc;background:rgba(56,189,248,.08);}',
            '.iris-st-chip.iris-st-c-sitrep{border-color:rgba(244,196,48,.4);color:#f3d77e;background:rgba(244,196,48,.08);}',
            '.iris-st-chip.iris-st-c-dec{border-color:rgba(45,206,137,.4);color:#7fe0b3;background:rgba(45,206,137,.08);}',
            '.iris-st-burst{font-size:.72rem;color:#8fa3ef;cursor:pointer;margin-left:6px;}',
            '.iris-st-children{margin-left:22px;border-left:1px dashed rgba(255,255,255,.1);padding-left:6px;}',
            '.iris-st-hour{color:#7a7a85;font-size:.66rem;letter-spacing:.06em;text-transform:uppercase;margin:10px 4px 4px;}',
            '.iris-st-act{font-size:.8rem;}',
            '.iris-st-acthead{display:flex;align-items:center;gap:6px;padding:10px 12px 6px;}',
            '.iris-st-acthead p{margin:0;font-weight:600;color:#e8e8ee;}',
            '.iris-st-acthead .iris-st-count{color:#7a7a85;font-size:.72rem;}',
            '.iris-st-acthead button{background:none;border:0;color:#9a9aa5;padding:3px;border-radius:5px;cursor:pointer;}',
            '.iris-st-acthead button:hover{background:rgba(255,255,255,.07);color:#e8e8ee;}',
            '.iris-st-acthead .iris-st-tools{margin-left:auto;display:flex;gap:2px;}',
            '.iris-st-live{width:8px;height:8px;border-radius:50%;background:#2dce89;flex-shrink:0;}',
            '.iris-st-live.iris-st-paused{background:#f4c430;}',
            '.iris-st-chips{display:flex;flex-wrap:wrap;gap:4px;padding:0 12px 6px;}',
            '.iris-st-lanechip{border:1px solid rgba(255,255,255,.12);border-radius:10px;background:none;color:#9a9aa5;font-size:.68rem;padding:1px 8px;cursor:pointer;display:inline-flex;align-items:center;gap:4px;}',
            '.iris-st-lanechip.iris-st-on{border-color:rgba(94,114,228,.7);color:#e8e8ee;background:rgba(94,114,228,.15);}',
            '.iris-st-actlist{flex:1 1 auto;overflow-y:auto;padding:0 8px 6px;min-height:0;}',
            '.iris-st-actfoot{border-top:1px solid rgba(255,255,255,.06);padding:5px 12px;color:#7a7a85;font-size:.7rem;}',
            '.iris-st-banner{margin:4px 8px;padding:4px 8px;border-radius:6px;background:rgba(244,196,48,.12);color:#f3d77e;font-size:.72rem;cursor:pointer;text-align:center;}',
            '.iris-st-resize{position:absolute;left:-7px;top:0;bottom:0;width:6px;cursor:col-resize;}',
            '.iris-st-menu{position:fixed;z-index:1050;background:#1d1d24;border:1px solid rgba(255,255,255,.12);border-radius:8px;padding:4px;min-width:220px;box-shadow:0 8px 24px rgba(0,0,0,.4);font-size:.78rem;}',
            '.iris-st-menu button{display:flex;width:100%;gap:6px;align-items:center;background:none;border:0;color:#c8c8d0;text-align:left;padding:5px 8px;border-radius:5px;cursor:pointer;}',
            '.iris-st-menu button:hover{background:rgba(255,255,255,.07);}',
            '.iris-st-thread{padding:0;}',
            '.iris-st-threadhead{display:flex;align-items:center;gap:6px;padding:10px 12px;border-bottom:1px solid rgba(255,255,255,.06);}',
            '.iris-st-threadhead .iris-st-ttl{font-weight:600;color:#e8e8ee;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
            '.iris-st-threadhead .iris-st-ttl.iris-st-editable{cursor:text;}',
            '.iris-st-threadhead .iris-st-tools{margin-left:auto;display:flex;gap:4px;align-items:center;flex-shrink:0;}',
            '.iris-st-threadbody{flex:1 1 auto;overflow-y:auto;padding:8px 10px;min-height:0;}',
            '.iris-st-threadsep{display:flex;align-items:center;gap:8px;color:#7a7a85;font-size:.7rem;margin:8px 0;}',
            '.iris-st-threadsep:before,.iris-st-threadsep:after{content:"";flex:1;border-top:1px solid rgba(255,255,255,.08);}',
            '.iris-st-compose{border-top:1px solid rgba(255,255,255,.06);padding:8px 10px;position:relative;}',
            '.iris-st-compose textarea{resize:none;overflow-y:auto;max-height:140px;font-size:.85rem;}',
            '#iris-wr-composer > .d-flex{border:1px solid rgba(255,255,255,.1);border-radius:10px;background:rgba(255,255,255,.02);padding:6px 6px 6px 10px;align-items:center!important;}',
            '#iris-wr-composer > .d-flex:focus-within{border-color:rgba(94,114,228,.55);}',
            '#iris-wr-composer #iris-wr-msg-input{background:transparent!important;border:0!important;box-shadow:none!important;padding:6px 4px!important;color:#e8e8ee!important;}',
            '#iris-wr-composer #iris-wr-msg-input::placeholder{color:#6a6a75;}',
            '#iris-wr-composer #iris-wr-msg-send{border-radius:8px;}',
            '#iris-wr-composer .iris-st-ctools{gap:10px;}',
            '#iris-st-thread-input{background:rgba(255,255,255,.02)!important;border:1px solid rgba(255,255,255,.1)!important;border-radius:8px!important;color:#e8e8ee!important;}',
            '.iris-st-ctools{display:flex;align-items:center;gap:8px;color:#9a9aa5;}',
            '.iris-st-ctools a,.iris-st-ctools button{color:inherit;background:none;border:0;padding:2px;cursor:pointer;}',
            '.iris-st-ctools a:hover,.iris-st-ctools button:hover{color:#e8e8ee;}',
            '.iris-st-attach{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 6px;}',
            '.iris-st-attach .iris-st-file button{background:none;border:0;color:#9a9aa5;padding:0 0 0 4px;cursor:pointer;}',
            '.iris-st-target{position:relative;display:inline-block;}',
            '.iris-st-target .iris-wr-topic-chip{cursor:pointer;}',
            '.iris-st-dropdown{position:absolute;bottom:120%;left:0;z-index:20;background:#1d1d24;border:1px solid rgba(255,255,255,.12);border-radius:8px;padding:4px;min-width:200px;max-height:260px;overflow-y:auto;box-shadow:0 8px 24px rgba(0,0,0,.4);}',
            '.iris-st-dropdown button{display:block;width:100%;text-align:left;background:none;border:0;color:#c8c8d0;padding:4px 8px;border-radius:5px;font-size:.78rem;cursor:pointer;}',
            '.iris-st-dropdown button:hover,.iris-st-dropdown button.iris-st-on{background:rgba(255,255,255,.07);}',
            '.iris-st-drop{position:absolute;inset:0;z-index:30;display:none;align-items:center;justify-content:center;border:2px dashed rgba(139,92,246,.7);border-radius:10px;background:rgba(21,21,26,.85);color:#d4c4ff;font-size:.9rem;}',
            '.iris-st-drop.iris-st-on{display:flex;}',
            '.iris-st-edit textarea{font-size:.85rem;margin-top:2px;}',
            '.iris-st-edit .iris-st-hint kbd{font-size:.62rem;}',
            '.iris-st-emoji{position:fixed;z-index:1060;width:330px;background:#1d1d24;border:1px solid rgba(255,255,255,.12);border-radius:10px;box-shadow:0 10px 30px rgba(0,0,0,.5);display:flex;flex-direction:column;max-height:360px;}',
            '.iris-st-emoji input{margin:8px;width:calc(100% - 16px);font-size:.8rem;height:30px;}',
            '.iris-st-emotabs{display:flex;gap:2px;padding:0 8px 4px;border-bottom:1px solid rgba(255,255,255,.06);}',
            '.iris-st-emotabs button{background:none;border:0;font-size:1rem;padding:2px 4px;border-radius:5px;cursor:pointer;opacity:.6;}',
            '.iris-st-emotabs button.iris-st-on{opacity:1;background:rgba(255,255,255,.08);}',
            '.iris-st-emogrid{overflow-y:auto;padding:6px 8px;display:grid;grid-template-columns:repeat(8,1fr);gap:2px;}',
            '.iris-st-emogrid button{background:none;border:0;font-size:1.25rem;line-height:1.6;border-radius:6px;cursor:pointer;padding:0;}',
            '.iris-st-emogrid button:hover{background:rgba(255,255,255,.08);}',
            '.iris-st-emolabel{grid-column:1/-1;color:#7a7a85;font-size:.66rem;text-transform:uppercase;letter-spacing:.06em;margin-top:4px;}',
            '.iris-st-ac{position:absolute;bottom:100%;left:10px;z-index:25;background:#1d1d24;border:1px solid rgba(255,255,255,.12);border-radius:8px;padding:4px;min-width:240px;box-shadow:0 8px 24px rgba(0,0,0,.4);}',
            '.iris-st-ac div{padding:3px 8px;border-radius:5px;cursor:pointer;font-size:.8rem;color:#c8c8d0;}',
            '.iris-st-ac div.iris-st-on,.iris-st-ac div:hover{background:rgba(94,114,228,.2);}',
            '.iris-st-set .iris-st-lane{display:flex;align-items:center;gap:8px;padding:4px 0;}',
            '.iris-st-set .iris-st-lane span{flex:1 1 auto;}',
            '.iris-st-seg{display:inline-flex;border:1px solid rgba(255,255,255,.12);border-radius:8px;overflow:hidden;}',
            '.iris-st-seg button{background:none;border:0;color:#9a9aa5;font-size:.72rem;padding:2px 10px;cursor:pointer;}',
            '.iris-st-seg button.iris-st-on{background:rgba(94,114,228,.25);color:#e8e8ee;}',
            '.iris-st-set h6{color:#7a7a85;font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;margin:14px 0 6px;}',
            '.iris-st-set label{font-weight:normal;color:#c8c8d0;margin:0;}',
            '.iris-st-set .iris-st-fams{display:flex;flex-wrap:wrap;gap:4px 14px;margin:4px 0 0 4px;}',
            '.iris-st-set .iris-st-case{border:1px solid rgba(255,255,255,.07);border-radius:8px;padding:6px 8px;margin-bottom:6px;}',
            '.iris-st-set .iris-st-casetypes{margin:6px 0 0 18px;display:none;}',
            '.iris-st-set .iris-st-casetypes.iris-st-on{display:block;}',
            '.iris-st-set .iris-st-typegrp{margin-bottom:4px;}',
            '.iris-st-set .iris-st-typegrp b{color:#9a9aa5;font-weight:600;font-size:.7rem;}',
            '@media (max-width:1199px){#iris-st,#iris-st.iris-st-norail{grid-template-columns:minmax(0,1fr);height:auto;}.iris-st-conv{max-height:260px;}#iris-wr-chat{height:520px;flex:none;}.iris-st-actlist,.iris-st-threadbody{max-height:420px;}.iris-st-resize{display:none;}}'
        ].join('\n');
        document.head.appendChild(st);
    }

    /* -------------------------------------------------------------------- time helpers */
    var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    var DAY = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
    function dt(iso) { return iso ? new Date(iso) : null; }
    function two(n) { return (n < 10 ? '0' : '') + n; }
    function hm(d) { return d ? two(d.getHours()) + ':' + two(d.getMinutes()) : ''; }
    function stamp(d) { return d ? MON[d.getMonth()] + ' ' + d.getDate() + ', ' + hm(d) : ''; }
    function dayKey(d) { return d ? (d.getMonth() + 1) + '/' + d.getDate() + '/' + d.getFullYear() : ''; }
    function hourLabel(d) {
        return DAY[d.getDay()] + ', ' + MON[d.getMonth()].toUpperCase() + ' ' + d.getDate() + ' · ' + two(d.getHours()) + ':00';
    }
    function srcOf(key) { return SRC[key.split(':')[0]] || 9; }
    function idOf(key) { return parseInt(key.split(':')[1], 10) || 0; }
    /* the server's order: time, source, id - newest first */
    function cmpDesc(a, b) {
        if (a.created_at !== b.created_at) { return a.created_at < b.created_at ? 1 : -1; }
        var sa = srcOf(a.key), sb = srcOf(b.key);
        if (sa !== sb) { return sb - sa; }
        return idOf(b.key) - idOf(a.key);
    }

    /* ------------------------------------------------------------------- settings */
    function lane(key) { return (S.vocab.lanes || []).filter(function (l) { return l.key === key; })[0]; }
    function laneOfKind(kind) {
        var l = (S.vocab.lanes || []).filter(function (x) { return x.kinds.indexOf(kind) !== -1; })[0];
        return l ? l.key : null;
    }
    function routeOf(kind) {
        if (S.vocab.always_chat.indexOf(kind) !== -1) { return 'chat'; }
        var l = laneOfKind(kind);
        return l ? (S.prefs.routes[l] || 'off') : 'off';
    }
    function kindsFor(where) {
        return S.vocab.kinds.filter(function (k) { return routeOf(k) === where; });
    }
    function normalisePrefs(raw) {
        /* the client mirror of war_room_stream_vocab.normalise_prefs, for a guest's local copy */
        var d = JSON.parse(JSON.stringify(S.vocab.defaults));
        if (!raw || typeof raw !== 'object') { return d; }
        if (raw.routes && typeof raw.routes === 'object') {
            Object.keys(d.routes).forEach(function (k) {
                if (S.vocab.routes.indexOf(raw.routes[k]) !== -1) { d.routes[k] = raw.routes[k]; }
            });
        }
        ['foldBursts', 'quietMode', 'railOpen'].forEach(function (k) { if (typeof raw[k] === 'boolean') { d[k] = raw[k]; } });
        if (typeof raw.railWidth === 'number') {
            d.railWidth = Math.max(S.vocab.limits.rail_width[0], Math.min(S.vocab.limits.rail_width[1], Math.round(raw.railWidth)));
        }
        if (Array.isArray(raw.excludedCases)) {
            d.excludedCases = raw.excludedCases.filter(function (x) { return typeof x === 'number' && x > 0; });
        }
        var slugs = [];
        S.vocab.case_activity.forEach(function (g) { g.slugs.forEach(function (s) { slugs.push(s.slug); }); });
        if (raw.excludedCaseActivities && typeof raw.excludedCaseActivities === 'object') {
            Object.keys(raw.excludedCaseActivities).forEach(function (cid) {
                var v = raw.excludedCaseActivities[cid];
                if (/^\d+$/.test(cid) && Array.isArray(v)) {
                    v = v.filter(function (s) { return slugs.indexOf(s) !== -1; });
                    if (v.length) { d.excludedCaseActivities[cid] = v; }
                }
            });
        }
        var fams = S.vocab.families.map(function (f) { return f.key; });
        if (Array.isArray(raw.excludedRoomActivities)) {
            d.excludedRoomActivities = raw.excludedRoomActivities.filter(function (f) { return fams.indexOf(f) !== -1; });
        }
        return d;
    }
    var saveTimer = null;
    function savePrefs() {
        if (S.guest) { ls(LS_PREFS, S.prefs); return; }
        clearTimeout(saveTimer);
        saveTimer = setTimeout(function () {
            fetch('/api/v2/war-rooms/stream-preferences', {
                method: 'PUT', headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
                body: JSON.stringify({prefs: S.prefs})
            }).then(function (r) {
                if (!r.ok) { status('Your Activity settings could not be saved'); }
            }).catch(function () { status('Your Activity settings could not be saved'); });
        }, 500);
    }
    function loadPrefs() {
        if (S.guest) { S.prefs = normalisePrefs(ls(LS_PREFS)); return Promise.resolve(); }
        return fetch('/api/v2/war-rooms/stream-preferences', {headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (j) { S.prefs = (j && j.prefs) ? j.prefs : normalisePrefs(null); })
            .catch(function () { S.prefs = normalisePrefs(null); });
    }
    function isMuted(i) {
        var p = S.prefs;
        if (i.kind === 'case_activity') {
            if (p.excludedCases.indexOf(i.case_id) !== -1) { return true; }
            var per = p.excludedCaseActivities[String(i.case_id)];
            if (per && per.indexOf(i.activity_type) !== -1) { return true; }
            return !!(p.quietMode && /\.updated$/.test(i.activity_type || ''));
        }
        if (i.kind === 'war_room_activity') { return p.excludedRoomActivities.indexOf(i.family) !== -1; }
        if (i.kind === 'case_attached' || i.kind === 'case_detached') {
            return p.excludedCases.indexOf(i.case_id) !== -1;
        }
        return false;
    }

    /* ------------------------------------------------------------------------- feeds */
    function feedUrl(where, before) {
        var kinds = kindsFor(where);
        var q = '?limit=50&kinds=' + encodeURIComponent(kinds.join(','));
        if (before) { q += '&before=' + encodeURIComponent(before); }
        if (where === 'chat' && S.chat.q) { q += '&q=' + encodeURIComponent(S.chat.q); }
        return '/stream' + q;
    }
    function feedOf(where) { return where === 'chat' ? S.chat : S.rail; }
    function load(where, older) {
        var f = feedOf(where);
        if (!kindsFor(where).length) { f.map = {}; f.done = true; render(where); return Promise.resolve(); }
        if (older && (f.done || f.loading || !f.cursor)) { return Promise.resolve(); }
        f.loading = true;
        var seq = ++f.seq;
        return api('GET', feedUrl(where, older ? f.cursor : null)).then(function (res) {
            f.loading = false;
            if (seq !== f.seq || !res.ok) { return; }
            var items = res.j.stream || [];
            if (!older) {
                f.map = {};
                f.pending = {};
            }
            items.forEach(function (i) { f.map[i.key] = i; });
            f.cursor = res.j.next_cursor || null;
            f.done = !res.j.next_cursor;
            render(where, older);
        }, function () { f.loading = false; });
    }
    /* newest page again: add what is new, refresh what changed, drop what the page no longer has
       (a deleted message) inside the window the page covers */
    function refresh(where) {
        var f = feedOf(where);
        if (!kindsFor(where).length || f.loading) { return Promise.resolve(); }
        var seq = f.seq;
        return api('GET', feedUrl(where, null)).then(function (res) {
            if (seq !== f.seq || !res.ok) { return; }
            var items = res.j.stream || [];
            var fresh = {};
            items.forEach(function (i) { fresh[i.key] = i; });
            var oldest = items.length ? items[items.length - 1] : null;
            var changed = false;
            if (where === 'rail' && S.rail.paused) {
                items.forEach(function (i) { if (!f.map[i.key]) { f.pending[i.key] = i; } });
                renderRailHead();
                return;
            }
            Object.keys(f.map).forEach(function (k) {
                var cur = f.map[k];
                if (fresh[k]) { return; }
                var inWindow = !res.j.next_cursor || (oldest && cmpDesc(cur, oldest) <= 0);
                if (inWindow && cur.kind === 'message') { delete f.map[k]; changed = true; }
            });
            items.forEach(function (i) {
                var cur = f.map[i.key];
                if (!cur || JSON.stringify(cur) !== JSON.stringify(i)) { f.map[i.key] = i; changed = true; }
            });
            if (changed) { render(where); }
        });
    }
    function sorted(where) {
        var f = feedOf(where);
        return Object.keys(f.map).map(function (k) { return f.map[k]; }).sort(cmpDesc).reverse();
    }

    /* ------------------------------------------------------------------------ topics */
    function topicRow(name) { return S.topics.filter(function (t) { return t.name === name; })[0]; }
    function topicArchived(name) { var t = topicRow(name); return !!(t && t.archived); }
    function loadTopics() {
        return api('GET', '/topics').then(function (res) {
            if (!res.ok) { return; }
            S.topics = res.j.topics || [];
            renderConv();
            renderTarget();
            render('chat');
        });
    }
    function topicVisible(name) {
        if (S.only !== null) { return name === S.only; }
        if (topicArchived(name)) { return false; }
        return !S.hidden[name];
    }
    function setTarget(name) {
        S.target = name || 'main';
        if (window.IRIS_WROOM) { window.IRIS_WROOM._target = {mode: 'topic', topic: S.target}; }
        renderTarget();
    }
    function renderTarget() {
        var chip = $id('iris-wr-post-target');
        if (!chip) { return; }
        chip.innerHTML = '# ' + esc(S.target === 'main' ? 'Main' : S.target) + ' ' + ic('chevron');
        var arch = topicArchived(S.target);
        var note = $id('iris-st-target-note');
        if (note) {
            note.textContent = arch ? 'The selected topic is archived — pick a live one.' : '';
            note.style.display = arch ? '' : 'none';
        }
        var send = $id('iris-wr-msg-send');
        if (send) { send.disabled = arch; }
    }

    /* ---------------------------------------------------------------- body rendering */
    var FILE_RE = /#\[file:(\d{1,18})\|([^\]\n]{1,200})\]/g;
    function fmtSize(n) {
        if (n < 1024) { return n + ' B'; }
        if (n < 1024 * 1024) { return (n / 1024).toFixed(1) + ' KB'; }
        return (n / (1024 * 1024)).toFixed(1) + ' MB';
    }
    function fileUrl(id, download) {
        return '/api/v2/war-rooms/' + S.rid + '/files/' + parseInt(id, 10) + (download ? '?download=1' : '');
    }
    function filesHtml(files) {
        if (!files || !files.length) { return ''; }
        return '<div class="iris-st-files">' + files.map(function (f) {
            if (f.is_image) {
                return '<a href="' + fileUrl(f.id) + '" target="_blank" rel="noopener" title="' + esc(f.filename) +
                    ' — open in a new tab"><img class="iris-st-img" loading="lazy" alt="' + esc(f.filename) +
                    '" src="' + fileUrl(f.id) + '"></a>';
            }
            return '<a class="iris-st-file" href="' + fileUrl(f.id, true) + '" title="Download ' + esc(f.filename) + '">' +
                ic('file') + '<span>' + esc(f.filename) + '</span><small>' + fmtSize(f.size) + '</small>' + ic('download') + '</a>';
        }).join('') + '</div>';
    }
    function bodyHtml(i) {
        var text = String(i.content || '').replace(FILE_RE, '').replace(/[ \t]+$/gm, '').replace(/\n{3,}/g, '\n\n').trim();
        var html = text ? window.iris_wroom_render_body(text) : '';
        /* "> ..." lines (Discuss in chat) are quotes; #activity-<a|c|d><id> links back to the Activity line */
        html = html.split('\n').map(function (line) {
            return /^&gt; /.test(line) ? '<span class="iris-st-quote">' + line.slice(5) + '</span>' : line;
        }).join('\n');
        html = html.replace(/#activity-([acd])(\d{1,18})/g, function (_, s, n) {
            return '<a href="#" class="iris-st-actlink" data-act="' + s + n + '">Show in activity</a>';
        });
        return html;
    }

    /* --------------------------------------------------------------- message markup */
    function reactsHtml(i) {
        if (!i.reactions || !i.reactions.length) { return ''; }
        var can = canRead();
        return '<div class="iris-st-reacts">' + i.reactions.map(function (r) {
            return '<button type="button" class="iris-st-react' + (r.mine ? ' iris-st-mine' : '') + '" data-react="' +
                esc(r.emoji) + '" data-msg-id="' + i.id + '"' + (can ? '' : ' disabled') + ' title="' +
                esc((r.names || []).join(', ')) + '">' + esc(r.emoji) + ' ' + r.count + '</button>';
        }).join('') + '</div>';
    }
    function actionsHtml(i, inThread) {
        var b = [];
        var post = canPost();
        if (canRead()) { b.push('<button type="button" data-act="react" title="Add reaction" aria-label="Add reaction">' + ic('react') + '</button>'); }
        if (post && !inThread && !i.parent_id) { b.push('<button type="button" data-act="thread" title="Reply in thread" aria-label="Reply in thread">' + ic('thread') + '</button>'); }
        if (post && mine(i)) { b.push('<button type="button" data-act="edit" title="Edit message" aria-label="Edit message">' + ic('pencil') + '</button>'); }
        if (post && (mine(i) || isLead())) { b.push('<button type="button" data-act="delete" title="Delete message" aria-label="Delete message">' + ic('trash') + '</button>'); }
        if (post) {
            b.push('<button type="button" data-act="pin" data-pinned="' + (i.pinned ? '1' : '0') + '" title="' +
                (i.pinned ? 'Unpin message' : 'Pin message') + '" aria-label="' + (i.pinned ? 'Unpin message' : 'Pin message') + '">' + ic('pin') + '</button>');
        }
        return b.length ? '<div class="iris-st-actions">' + b.join('') + '</div>' : '';
    }
    function msgHtml(i, compact, inThread) {
        var d = dt(i.created_at);
        var head = '<div class="iris-st-msghead"><strong>' + esc(i.user_name) + '</strong>' +
            (i.is_guest ? '<span class="iris-st-badge" title="Guest participant (portal)">guest</span>' : '') +
            '<span class="iris-st-time" title="' + esc(d ? d.toString() : '') + '">' + stamp(d) + '</span>' +
            (i.pinned ? '<span title="Pinned">' + ic('pin') + '</span>' : '') +
            (i.msg_kind === 'decision' ? '<span class="iris-st-kind iris-st-k-decision">decision</span>' : '') +
            (i.msg_kind === 'note' ? '<span class="iris-st-kind iris-st-k-note">note</span>' : '') +
            (i.thread_title ? '<span class="iris-st-kind"># ' + esc(i.thread_title) + '</span>' : '') +
            (i.topic && i.topic !== 'main' && S.only === null && !inThread ? '<span class="iris-st-kind">#' + esc(i.topic) + '</span>' : '') +
            (i.edited_at ? '<span class="iris-st-edited" title="Edited ' + esc(stamp(dt(i.edited_at))) + '">(edited)</span>' : '') +
            '</div>';
        var body = S.editing === i.id ? editHtml(i)
            : '<div class="iris-st-body">' + bodyHtml(i) + (compact && i.edited_at ? ' <span class="iris-st-edited" title="Edited ' +
              esc(stamp(dt(i.edited_at))) + '">(edited)</span>' : '') + '</div>' + filesHtml(i.files);
        var chip = (!inThread && (i.reply_count || i.thread_title))
            ? '<div><span class="iris-st-threadchip" data-thread="' + i.id + '">' + ic('thread') + ' ' +
              (i.reply_count ? i.reply_count + (i.reply_count === 1 ? ' reply' : ' replies') +
               (i.last_reply_at ? ' · last ' + esc(stamp(dt(i.last_reply_at))) : '') : 'Open thread') + '</span></div>'
            : '';
        return '<div class="iris-st-msg' + (compact ? ' iris-st-compact' : '') + '" data-msg-id="' + i.id + '" data-key="' +
            esc(i.key) + '"><div class="iris-st-gutter">' + (compact ? '' : window.iris_wroom_avatar(i.user_name)) + '</div>' +
            '<div class="iris-st-msgmain">' + (compact ? '' : head) + body + reactsHtml(i) + chip + '</div>' +
            actionsHtml(i, inThread) + '</div>';
    }
    function editHtml(i) {
        return '<div class="iris-st-edit"><textarea class="form-control" rows="2" id="iris-st-edit-input" aria-label="Edit message">' +
            esc(i.content) + '</textarea><div class="iris-st-hint"><button type="button" class="btn btn-xs btn-primary mt-1" data-act="save-edit">Save</button> ' +
            '<button type="button" class="btn btn-xs btn-dark mt-1" data-act="cancel-edit">Cancel</button> ' +
            '<kbd>Enter</kbd> to save · <kbd>Esc</kbd> to cancel</div></div>';
    }

    /* -------------------------------------------------------------- event markup */
    var FAMILY_ICON = {room: 'info', member: 'users', team: 'users', topic: 'hash', note: 'note', folder: 'folder',
                       task: 'task', timeline: 'clock', event: 'clock', sitrep: 'sitrep', vulnerability: 'shield',
                       system: 'info'};
    function evIcon(i) {
        switch (i.kind) {
        case 'war_room_activity': return FAMILY_ICON[i.family] || 'info';
        case 'task_assigned': case 'task_completed': return 'task';
        case 'case_attached': return 'link';
        case 'case_detached': return 'unlink';
        case 'case_activity': return 'briefcase';
        case 'sitrep_published': return 'sitrep';
        case 'note': return 'note';
        case 'pin': return 'pin';
        case 'decision': return 'gavel';
        case 'priority': return 'flag';
        case 'system': return 'info';
        default: return 'activity';
        }
    }
    function caseChip(cid) {
        cid = parseInt(cid, 10);
        if (!cid) { return ''; }
        return S.guest ? '<span class="iris-st-chip">Case #' + cid + '</span>'
            : '<a class="iris-st-chip" href="/case?cid=' + cid + '" title="Open case #' + cid + '">' + ic('briefcase') + 'Case #' + cid + '</a>';
    }
    function refChips(i) {
        var out = '';
        if (i.case_id) { out += caseChip(i.case_id); }
        if (i.kind === 'note' && i.ref_id) {
            out += '<a href="#" class="iris-st-chip iris-st-c-note" data-note="' + parseInt(i.ref_id, 10) + '">' + ic('note') + 'Note #' + parseInt(i.ref_id, 10) + '</a>';
        }
        if (i.kind === 'sitrep_published') {
            out += '<a href="#" class="iris-st-chip iris-st-c-sitrep" data-pane="sitreps">' + ic('sitrep') + 'SitRep</a>';
        }
        if (i.kind === 'decision' && /^\d+$/.test(String(i.decision_id))) {
            out += '<a href="#" class="iris-st-chip iris-st-c-dec iris-wr-open-decision" data-decision-id="' + parseInt(i.decision_id, 10) + '">' + ic('gavel') + 'Open</a>';
        }
        if (i.kind === 'pin' && i.ref_id) {
            out += '<a href="#" class="iris-st-chip iris-st-c-note" data-jump="' + parseInt(i.ref_id, 10) + '">Jump</a>';
        }
        return out;
    }
    function actCode(i) { return ({activity: 'a', case_activity: 'c', decision: 'd'})[i.key.split(':')[0]] || ''; }
    function evHtml(i, where, child) {
        var d = dt(i.created_at);
        var who = i.actor_name ? '<strong>' + esc(i.actor_name) + '</strong> ' : '';
        var acts = '';
        if (where === 'rail' && !child) {
            acts = '<div class="iris-st-actions">' +
                (canPost() && actCode(i) ? '<button type="button" data-act="discuss" title="Discuss in chat" aria-label="Discuss in chat">' + ic('quote') + '</button>' : '') +
                '<button type="button" data-act="mute" title="Mute…" aria-label="Mute">' + ic('belloff') + '</button></div>';
        }
        return '<div class="iris-st-ev' + (i.kind === 'priority' ? ' iris-st-priority' : '') + '" data-key="' + esc(i.key) + '">' +
            '<span class="iris-st-evic">' + ic(evIcon(i)) + '</span><div class="iris-st-evmain">' + who +
            esc(i.content) + refChips(i) + ' <span class="iris-st-time" title="' + esc(d ? d.toString() : '') + '">' +
            (where === 'rail' ? hm(d) : stamp(d)) + '</span></div>' + acts + '</div>';
    }

    /* -------------------------------------------------------------------- bursts */
    var NOUN = {note: 'notes', directory: 'note folders', ioc: 'IOCs', asset: 'assets', evidence: 'evidence files',
                task: 'tasks', event: 'timeline events', 'case': 'case changes', alert: 'alert links', datastore: 'datastore files'};
    function burstKey(i) {
        return [i.actor_name || '', i.kind, i.case_id || '', i.activity_type || ''].join('|');
    }
    function burstLabel(items) {
        var first = items[0], n = items.length;
        var same = items.every(function (x) { return x.content === first.content; });
        if (same) { return null; }
        var parts = (first.activity_type || '').split('.');
        var verb = parts[1] === 'created' ? 'added' : (parts[1] || '').replace(/_/g, ' ');
        if (first.kind === 'case_activity' && NOUN[parts[0]]) { return verb + ' ' + n + ' ' + NOUN[parts[0]]; }
        if (first.family && parts[1]) {
            var fam = (S.vocab.families.filter(function (f) { return f.key === first.family; })[0] || {}).label;
            if (fam) { return verb + ' ' + n + ' ' + fam.toLowerCase(); }
        }
        var l = lane(laneOfKind(first.kind));
        return n + ' ' + (l ? l.label.toLowerCase() : 'similar') + ' events';
    }
    /* [{type:'one', item} | {type:'burst', items}] - three or more similar events in a row fold */
    function fold(list) {
        if (!S.prefs.foldBursts) { return list.map(function (i) { return {type: 'one', item: i}; }); }
        var out = [];
        for (var a = 0; a < list.length;) {
            var i = list[a];
            if (i.kind === 'message' || i.kind === 'poll') { out.push({type: 'one', item: i}); a++; continue; }
            var k = burstKey(i), b = a + 1;
            while (b < list.length && list[b].kind !== 'message' && list[b].kind !== 'poll' && burstKey(list[b]) === k) { b++; }
            if (b - a >= 3) { out.push({type: 'burst', items: list.slice(a, b)}); } else {
                list.slice(a, b).forEach(function (x) { out.push({type: 'one', item: x}); });
            }
            a = b;
        }
        return out;
    }
    function burstHtml(g, where) {
        var first = g.items[0], last = g.items[g.items.length - 1];
        var id = first.key, open = !!S.expanded[id];
        var label = burstLabel(g.items);
        var d = dt(last.created_at);
        var head = '<div class="iris-st-ev" data-burst="' + esc(id) + '"><span class="iris-st-evic">' + ic(evIcon(first)) + '</span>' +
            '<div class="iris-st-evmain">' + (first.actor_name ? '<strong>' + esc(first.actor_name) + '</strong> ' : '') +
            (label ? esc(label) : esc(first.content) + ' <b>' + g.items.length + '×</b>') + refChips(first) +
            ' <span class="iris-st-time">' + (where === 'rail' ? hm(d) : stamp(d)) + '</span>' +
            '<a href="#" class="iris-st-burst" data-burst="' + esc(id) + '" aria-expanded="' + (open ? 'true' : 'false') + '">' +
            (open ? 'Hide' : 'Show all') + '</a></div></div>';
        if (!open) { return head; }
        return head + '<div class="iris-st-children">' + g.items.map(function (x) { return evHtml(x, where, true); }).join('') + '</div>';
    }

    /* ---------------------------------------------------------------------- chat */
    function chatVisible(i) {
        if (isMuted(i)) { return false; }
        if (i.kind === 'message') { return topicVisible(i.topic || 'main'); }
        return S.only === null;
    }
    function render(where, keepTop) {
        if (where === 'chat') { renderChat(keepTop); } else { renderRail(keepTop); }
    }
    function renderChat(keepTop) {
        var box = $id('iris-wr-chat');
        if (!box || !S.prefs) { return; }
        var stick = (box.scrollHeight - box.scrollTop - box.clientHeight) < 80 || !box.childElementCount;
        var prevH = box.scrollHeight, prevTop = box.scrollTop;
        var list = sorted('chat').filter(chatVisible);
        var groups = fold(list);
        var html = [];
        if (S.chat.done) { html.push('<div class="iris-st-start">Start of the conversation</div>'); } else {
            html.push('<div class="iris-st-loadmore" id="iris-st-chat-more">' + (S.chat.loading ? 'Loading older messages…' : 'Scroll up for older messages') + '</div>');
        }
        var lastDay = '', prev = null;
        groups.forEach(function (g) {
            var i = g.type === 'one' ? g.item : g.items[0];
            var d = dt(i.created_at), day = dayKey(d);
            if (day && day !== lastDay) {
                lastDay = day;
                html.push('<div class="iris-wr-datesep"><span>' + day + '</span></div>');
                prev = null;
            }
            if (g.type === 'burst') { html.push(burstHtml(g, 'chat')); prev = null; return; }
            if (i.kind === 'message') {
                var compact = !!(prev && prev.kind === 'message' && prev.user_name === i.user_name &&
                    prev.guest_id === i.guest_id && (dt(i.created_at) - dt(prev.created_at)) < 5 * 60000 &&
                    !i.thread_title && !prev.thread_title && i.topic === prev.topic);
                html.push(msgHtml(i, compact, false));
                prev = i;
                return;
            }
            prev = null;
            if (i.kind === 'poll' && i.poll) {
                html.push('<div class="iris-st-poll" data-key="' + esc(i.key) + '">' + window.iris_wroom_render_poll(i.poll, stamp(d)) + '</div>');
                return;
            }
            html.push(evHtml(i, 'chat'));
        });
        var empty = $id('iris-wr-stream-empty');
        if (empty) {
            var anyMsg = Object.keys(S.chat.map).some(function (k) { return S.chat.map[k].kind === 'message'; });
            empty.style.display = list.length ? 'none' : '';
            empty.textContent = S.chat.q ? 'No messages match “' + S.chat.q + '”.'
                : (Object.keys(S.chat.map).length && !list.length) ? 'Nothing to show with your Activity settings.'
                : (!anyMsg && kindsFor('rail').length) ? 'Nobody has said anything yet. Automatic activity is in the Activity rail.'
                : 'No activity yet. Drop the first message or attach a case.';
        }
        box.innerHTML = html.join('');
        var m = $id('iris-st-matches');
        if (m) {
            var n = list.filter(function (x) { return x.kind === 'message' || x.kind === 'poll' || x.content; }).length;
            m.textContent = S.chat.q ? n + ' match' + (n === 1 ? '' : 'es') : '';
        }
        if (keepTop) { box.scrollTop = prevTop + (box.scrollHeight - prevH); } else if (stick) { box.scrollTop = box.scrollHeight; }
        if (S.editing) {
            var ed = $id('iris-st-edit-input');
            if (ed && document.activeElement !== ed) { ed.focus(); ed.setSelectionRange(ed.value.length, ed.value.length); }
        }
    }

    /* ---------------------------------------------------------------------- rail */
    function railItems() {
        var all = sorted('rail');
        var muted = 0, q = S.rail.filter.toLowerCase();
        var vis = all.filter(function (i) {
            if (isMuted(i)) { muted++; return false; }
            if (q && ((i.actor_name || '') + ' ' + (i.content || '')).toLowerCase().indexOf(q) === -1) { return false; }
            return true;
        });
        return {all: all, vis: vis, muted: muted};
    }
    function renderRailHead() {
        var r = railItems();
        var cnt = $id('iris-st-act-count');
        if (cnt) { cnt.textContent = r.vis.length; }
        var dot = $id('iris-st-live');
        if (dot) { dot.className = 'iris-st-live' + (S.rail.paused ? ' iris-st-paused' : ''); }
        var pb = $id('iris-st-pause');
        if (pb) {
            pb.innerHTML = ic(S.rail.paused ? 'play' : 'pause');
            pb.title = S.rail.paused ? 'Resume activity' : 'Pause activity';
            pb.setAttribute('aria-label', pb.title);
            pb.setAttribute('aria-pressed', S.rail.paused ? 'true' : 'false');
        }
        var ban = $id('iris-st-act-banner');
        if (ban) {
            var n = Object.keys(S.rail.pending).length;
            ban.style.display = (S.rail.paused && n) ? '' : 'none';
            ban.textContent = n + ' new event' + (n === 1 ? '' : 's') + ' · resume';
        }
    }
    function renderRail(keepTop) {
        var box = $id('iris-st-actlist');
        if (!box || !S.prefs) { return; }
        var r = railItems();
        var lanes = (S.vocab.lanes || []).filter(function (l) { return S.prefs.routes[l.key] === 'rail'; });
        var counts = {};
        r.vis.forEach(function (i) { var l = laneOfKind(i.kind); counts[l] = (counts[l] || 0) + 1; });
        if (S.rail.chip !== 'all' && !lanes.some(function (l) { return l.key === S.rail.chip; })) { S.rail.chip = 'all'; }
        $id('iris-st-chips').innerHTML = [{key: 'all', label: 'All'}].concat(lanes).map(function (l) {
            var n = l.key === 'all' ? r.vis.length : (counts[l.key] || 0);
            return '<button type="button" class="iris-st-lanechip' + (S.rail.chip === l.key ? ' iris-st-on' : '') + '" data-chip="' +
                l.key + '" aria-pressed="' + (S.rail.chip === l.key ? 'true' : 'false') + '">' + esc(l.label) + ' <span>' + n + '</span></button>';
        }).join('');
        var list = r.vis.filter(function (i) { return S.rail.chip === 'all' || laneOfKind(i.kind) === S.rail.chip; });
        var stick = (box.scrollHeight - box.scrollTop - box.clientHeight) < 60 || !box.childElementCount;
        var prevH = box.scrollHeight, prevTop = box.scrollTop;
        var html = [];
        if (!lanes.length) {
            html.push('<div class="iris-st-hint p-2">Every lane goes to the chat or is off — change it in the Activity settings.</div>');
        } else {
            html.push(S.rail.done ? '<div class="iris-st-start">Start of the activity</div>'
                : '<div class="iris-st-loadmore">' + (S.rail.loading ? 'Loading older activity…' : 'Scroll up for older activity') + '</div>');
            if (!list.length) {
                html.push('<div class="iris-st-hint p-2">' + (r.all.length ? 'Nothing here with the current filters.' : 'No activity yet.') + '</div>');
            }
            var lastHour = '';
            fold(list).forEach(function (g) {
                var i = g.type === 'one' ? g.item : g.items[0];
                var d = dt(i.created_at);
                var h = d ? hourLabel(d) : '';
                if (h !== lastHour) { lastHour = h; html.push('<div class="iris-st-hour">' + esc(h) + '</div>'); }
                html.push(g.type === 'burst' ? burstHtml(g, 'rail') : evHtml(i, 'rail'));
            });
        }
        box.innerHTML = html.join('');
        if (keepTop) { box.scrollTop = prevTop + (box.scrollHeight - prevH); } else if (stick) { box.scrollTop = box.scrollHeight; }
        var foot = $id('iris-st-actfoot');
        var off = (S.vocab.lanes || []).filter(function (l) { return S.prefs.routes[l.key] === 'off'; }).length;
        foot.style.display = (r.muted || off) ? '' : 'none';
        foot.innerHTML = (r.muted ? r.muted + ' event' + (r.muted === 1 ? '' : 's') + ' muted · ' : '') +
            (off ? off + ' lane' + (off === 1 ? '' : 's') + ' off · ' : '') + '<a href="#" data-act="settings">Activity settings</a>';
        renderRailHead();
    }
    function layout() {
        var st = $id('iris-st');
        if (!st || !S.prefs) { return; }
        var showRail = S.prefs.railOpen || !!S.thread;
        st.classList.toggle('iris-st-norail', !showRail);
        $id('iris-st-act').style.display = (S.prefs.railOpen && !S.thread) ? '' : 'none';
        $id('iris-st-thread').style.display = S.thread ? '' : 'none';
        $id('iris-st-showrail').style.display = (S.prefs.railOpen || S.thread) ? 'none' : '';
        st.style.setProperty('--iris-st-rail', S.prefs.railWidth + 'px');
        fit();
    }
    /* the three columns fill the window below them; measured when shown (a hidden box has no position) */
    function fit() {
        var st = $id('iris-st');
        if (!st || !st.offsetParent) { return; }
        var top = st.getBoundingClientRect().top;
        var h = Math.max(480, Math.round(window.innerHeight - top - 24));
        st.style.setProperty('--iris-st-h', h + 'px');
    }

    /* ---------------------------------------------------------------- Conversation */
    function renderConv() {
        var box = $id('iris-st-topics');
        if (!box) { return; }
        var live = S.topics.filter(function (t) { return !t.archived; });
        var arch = S.topics.filter(function (t) { return t.archived; });
        var lead = isLead();
        box.innerHTML = live.map(function (t) {
            var shown = topicVisible(t.name);
            var own = t.created_by && t.created_by === myUserId() || (S.guest && t.created_by_guest_id && t.created_by_guest_id === myGuestId());
            return '<div class="iris-st-row' + (S.only === t.name ? ' iris-st-on' : '') + (shown ? '' : ' iris-st-dim') + '" data-topic="' + esc(t.name) + '">' +
                '<span class="iris-st-dot' + (shown ? ' iris-st-on' : '') + '" role="checkbox" aria-checked="' + (shown ? 'true' : 'false') +
                '" tabindex="0" data-act="toggle-topic" title="Toggle ' + esc(t.name) + '" aria-label="Toggle ' + esc(t.name) + '">' +
                (shown ? ic('check') : '') + '</span>' +
                '<span class="iris-st-txt" data-act="only-topic" title="Show only this topic"># ' + esc(t.is_main ? 'Main' : t.name) + '</span>' +
                (S.target === t.name ? '<span class="iris-st-badge" title="Composer target">post</span>' : '') +
                (!t.is_main && canPost() && (lead || own) ? '<button type="button" class="iris-st-rowact" data-act="archive-topic" data-topic-id="' +
                    parseInt(t.id, 10) + '" title="Archive ' + esc(t.name) + '" aria-label="Archive ' + esc(t.name) + '">' + ic('archive') + '</button>' : '') +
                (t.is_main ? '<span class="sr-only">Main topic (cannot be archived)</span>' : '') + '</div>';
        }).join('') + (arch.length ? '<div class="iris-st-row" data-act="toggle-archived"><span class="iris-st-txt iris-st-sub">' +
            ic(S.showArchived ? 'chevron' : 'archive') + ' Archived (' + arch.length + ')</span></div>' : '') +
            (S.showArchived ? arch.map(function (t) {
                var own = t.created_by && t.created_by === myUserId() || (S.guest && t.created_by_guest_id && t.created_by_guest_id === myGuestId());
                return '<div class="iris-st-row iris-st-dim' + (S.only === t.name ? ' iris-st-on' : '') + '" data-topic="' + esc(t.name) + '">' +
                    '<span class="iris-st-txt" data-act="only-topic" title="Show only this archived topic (read-only)">' + ic('archive') + ' ' + esc(t.name) + '</span>' +
                    (canPost() && (lead || own) ? '<button type="button" class="iris-st-rowact" data-act="restore-topic" data-topic-id="' +
                        parseInt(t.id, 10) + '" title="Unarchive ' + esc(t.name) + '" aria-label="Unarchive ' + esc(t.name) + '">' + ic('restore') + '</button>' : '') + '</div>';
            }).join('') : '');
        var only = $id('iris-st-only');
        if (only) {
            only.style.display = S.only !== null ? '' : 'none';
            only.innerHTML = S.only !== null ? 'Showing only #' + esc(S.only === 'main' ? 'Main' : S.only) +
                (topicArchived(S.only) ? ' (archived, read-only)' : '') + ' · <a href="#" data-act="all-topics">show all</a>' : '';
        }
        var add = $id('iris-wr-topic-add');
        if (add) { add.style.display = canPost() ? '' : 'none'; }
        renderThreads();
        renderIndex();
    }
    function renderThreads() {
        var box = $id('iris-st-threads');
        if (!box) { return; }
        $id('iris-st-thread-count').textContent = S.threads.length;
        $id('iris-wr-thread-hint').style.display = S.threads.length ? 'none' : '';
        box.innerHTML = S.threads.slice(0, 50).map(function (t) {
            return '<div class="iris-st-row' + (S.thread && S.thread.rootId === t.root_id ? ' iris-st-on' : '') + '" data-thread="' + parseInt(t.root_id, 10) + '">' +
                '<span class="iris-st-txt">' + esc(t.title) + '<br><span class="iris-st-sub">' + (t.reply_count || 0) + ' ' +
                (t.reply_count === 1 ? 'reply' : 'replies') + ' · ' + esc(t.author_name) + '</span></span>' +
                (t.following ? '<span title="You follow this thread">' + ic('bell') + '</span>' : '') + '</div>';
        }).join('');
    }
    function renderIndex() {
        var box = $id('iris-st-index');
        if (!box) { return; }
        var q = S.indexQ.toLowerCase();
        var items = S.index.filter(function (i) {
            return !q || ((i.title || '') + ' ' + (i.author_name || '') + ' ' + i.type).toLowerCase().indexOf(q) !== -1;
        });
        $id('iris-st-index-count').textContent = S.index.length;
        var LABEL = {decision: 'Decision', pin: 'Pin', note: 'Note'};
        box.innerHTML = items.length ? items.slice(0, 80).map(function (i) {
            var d = dt(i.created_at);
            return '<div class="iris-st-idx" role="button" tabindex="0" data-idx-type="' + esc(i.type) + '" data-idx-id="' + parseInt(i.id, 10) + '"' +
                (i.parent_id ? ' data-idx-parent="' + parseInt(i.parent_id, 10) + '"' : '') + ' title="Jump to this entry">' +
                '<div class="iris-st-idxt">' + ic(i.type === 'decision' ? 'gavel' : (i.type === 'pin' ? 'pin' : 'note')) + ' ' + esc(i.title) + '</div>' +
                '<div class="iris-st-idxm"><b>' + LABEL[i.type] + '</b>' + (i.author_name ? ' · ' + esc(i.author_name) : '') + (d ? ' · ' + esc(stamp(d)) : '') + '</div></div>';
        }).join('') : (S.indexQ ? '<div class="iris-st-hint">No matches for “' + esc(S.indexQ) + '”.</div>'
            : '<div class="iris-st-hint">Use <code>/decision</code> or <code>/pin</code> to record something the room should remember.</div>');
    }
    function loadMeta() {
        S.lastMeta = Date.now();
        return Promise.all([
            api('GET', '/threads').then(function (r) { if (r.ok) { S.threads = r.j.threads || []; } }),
            api('GET', '/stream/index').then(function (r) { if (r.ok) { S.index = r.j.items || []; } }),
            loadTopics()
        ]).then(renderConv);
    }

    /* ------------------------------------------------------------------ threads */
    function openThread(rootId) {
        rootId = parseInt(rootId, 10);
        if (!rootId) { return; }
        S.thread = {rootId: rootId, data: null};
        layout();
        renderThread();
        loadThread();
        renderThreads();
    }
    function closeThread() {
        S.thread = null;
        S.pending.thread = [];
        layout();
        renderThreads();
    }
    function loadThread() {
        if (!S.thread) { return Promise.resolve(); }
        var rid = S.thread.rootId;
        return api('GET', '/messages/' + rid + '/thread').then(function (res) {
            if (!S.thread || S.thread.rootId !== rid) { return; }
            if (!res.ok) {
                S.thread.data = {error: res.status === 404 ? 'This thread is gone (its first message was deleted).' : (res.j.message || 'Could not load the thread')};
            } else { S.thread.data = res.j; }
            renderThread();
        });
    }
    function renderThread() {
        var host = $id('iris-st-thread');
        if (!host || !S.thread) { return; }
        var d = S.thread.data;
        var root = d && d.root;
        var canRename = root && canPost() && (mine(root) || isLead());
        var title = root ? (root.thread_title || String(root.content || '').slice(0, 60)) : 'Thread';
        var n = d && d.replies ? d.replies.length : 0;
        var head = '<div class="iris-st-threadhead">' + ic('thread') +
            '<span class="iris-st-ttl' + (canRename ? ' iris-st-editable' : '') + '" id="iris-st-thread-title"' +
            (canRename ? ' title="Click to rename" data-act="rename-thread"' : '') + '>' + esc(title) + '</span>' +
            '<div class="iris-st-tools"><span class="iris-st-time">' + n + ' ' + (n === 1 ? 'reply' : 'replies') + '</span>' +
            (root && canRead() ? '<button type="button" class="btn btn-xs btn-dark" data-act="follow" aria-pressed="' + (d.following ? 'true' : 'false') + '">' +
                ic(d.following ? 'belloff' : 'bell') + ' ' + (d.following ? 'Unfollow' : 'Follow') + '</button>' : '') +
            '<button type="button" class="btn btn-xs btn-dark" data-act="close-thread" aria-label="Close thread">' + ic('x') + '</button></div></div>';
        var body;
        if (!d) { body = '<div class="iris-st-hint p-2">Loading replies…</div>'; } else if (d.error) {
            body = '<div class="iris-st-hint p-2">' + esc(d.error) + '</div>';
        } else {
            body = msgHtml(root, false, true) + '<div class="iris-st-threadsep">' + n + ' ' + (n === 1 ? 'reply' : 'replies') + '</div>' +
                (n ? d.replies.map(function (x, k) {
                    var prev = d.replies[k - 1];
                    var compact = !!(prev && prev.user_name === x.user_name && prev.guest_id === x.guest_id &&
                        (dt(x.created_at) - dt(prev.created_at)) < 5 * 60000);
                    return msgHtml(x, compact, true);
                }).join('') : '<div class="iris-st-hint">No replies yet — be the first.</div>');
        }
        var closedTopic = root && topicArchived(root.topic);
        var compose = (root && canPost() && !closedTopic)
            ? '<div class="iris-st-compose" id="iris-st-thread-compose"><div class="iris-st-ac" id="iris-st-thread-ac" style="display:none;"></div>' +
              '<div class="iris-wr-cmd-pop" id="iris-st-thread-mention-pop" style="display:none;"></div>' +
              '<div class="iris-st-attach" id="iris-st-thread-attach"></div>' +
              '<textarea class="form-control" id="iris-st-thread-input" rows="2" maxlength="20000" placeholder="Reply in thread… @mentions, attachments" aria-label="Reply in thread"></textarea>' +
              '<div class="iris-st-ctools mt-1"><button type="button" data-act="attach" data-where="thread" title="Attach files" aria-label="Attach files">' + ic('clip') + '</button>' +
              '<button type="button" data-act="emoji" data-where="thread" title="Insert emoji" aria-label="Insert emoji">' + ic('smile') + '</button>' +
              '<span class="iris-st-hint ml-1"><kbd>Enter</kbd> to send · <kbd>Shift+Enter</kbd> for newline</span>' +
              '<button type="button" class="btn btn-xs btn-primary ml-auto" data-act="send-thread">Reply</button></div></div>'
            : (closedTopic ? '<div class="iris-st-compose iris-st-hint">This thread’s topic is archived — it is read-only.</div>' : '');
        var keep = $id('iris-st-thread-input');
        var draft = keep ? keep.value : '';
        host.innerHTML = head + '<div class="iris-st-threadbody" id="iris-st-threadbody">' + body + '</div>' + compose;
        var inp = $id('iris-st-thread-input');
        if (inp && draft) { inp.value = draft; }
        renderAttach('thread');
        var tb = $id('iris-st-threadbody');
        if (tb) { tb.scrollTop = tb.scrollHeight; }
    }
    function sendThread() {
        var inp = $id('iris-st-thread-input');
        if (!inp || !S.thread) { return; }
        var text = withTokens(inp.value.trim(), 'thread');
        if (!text) { return; }
        if (S.pending.thread.some(function (p) { return p.uploading; })) { status('Wait for the upload to finish'); return; }
        api('POST', '/messages', {content: text, parent_id: S.thread.rootId}).then(function (res) {
            if (!res.ok) { status(res.j.message || 'Could not send the reply'); return; }
            inp.value = '';
            S.pending.thread = [];
            loadThread();
            refresh('chat');
            loadMeta();
        });
    }

    /* ----------------------------------------------------------------- attachments */
    /* The two attachment slots. A slot read back from the page (data-where) is re-derived here, never reused:
       anything but 'thread' is the main composer. */
    function attachSlot(v) { return v === 'thread' ? 'thread' : 'main'; }
    function withTokens(text, where) {
        var toks = S.pending[where].filter(function (p) { return p.token; }).map(function (p) { return p.token; });
        return [text].concat(toks).filter(Boolean).join(text && toks.length ? '\n' : ' ').trim();
    }
    function renderAttach(where) {
        where = attachSlot(where);
        var box = $id(where === 'main' ? 'iris-st-attach' : 'iris-st-thread-attach');
        if (!box) { return; }
        box.innerHTML = S.pending[where].map(function (p, k) {
            return '<span class="iris-st-file">' + ic(p.is_image ? 'smile' : 'file') + '<span>' + esc(p.filename) + '</span><small>' +
                (p.uploading ? 'uploading…' : (p.error ? esc(p.error) : fmtSize(p.size))) + '</small>' +
                '<button type="button" data-act="unattach" data-where="' + where + '" data-k="' + k + '" title="Remove attachment" aria-label="Remove attachment">' + ic('x') + '</button></span>';
        }).join('');
    }
    function uploadFiles(files, where) {
        where = attachSlot(where);
        Array.prototype.slice.call(files || []).forEach(function (file) {
            var max = S.vocab.limits.file_max_bytes;
            var slot = {filename: file.name || 'file', size: file.size, uploading: true};
            if (file.size > max) {
                slot.uploading = false;
                slot.error = 'over ' + Math.round(max / 1048576) + ' MB';
                S.pending[where].push(slot);
                renderAttach(where);
                return;
            }
            S.pending[where].push(slot);
            renderAttach(where);
            var fd = new FormData();
            fd.append('file', file, file.name || 'file');
            fd.append('csrf_token', window.iris_wroom_csrf());
            fetch('/api/v2/war-rooms/' + S.rid + '/files', {method: 'POST', body: fd, headers: {'Accept': 'application/json'}})
                .then(function (r) { return r.json().then(function (j) { return {ok: r.ok, j: j}; }); })
                .then(function (res) {
                    slot.uploading = false;
                    if (!res.ok) { slot.error = (res.j && res.j.message) || 'upload failed'; } else {
                        slot.id = res.j.id; slot.token = res.j.token; slot.is_image = res.j.is_image; slot.filename = res.j.filename;
                    }
                    renderAttach(where);
                }, function () { slot.uploading = false; slot.error = 'upload failed'; renderAttach(where); });
        });
    }
    function pastedName(file) {
        var d = new Date();
        var ext = ((file.type || '').split('/')[1] || 'png').replace(/[^a-z0-9]/gi, '');
        return 'pasted-image-' + d.getFullYear() + two(d.getMonth() + 1) + two(d.getDate()) + '-' + two(d.getHours()) + two(d.getMinutes()) + two(d.getSeconds()) + '.' + ext;
    }

    /* ------------------------------------------------------------------------ emoji */
    var emojiLoad = null;
    function emojiData() {
        if (window.IrisEmojiData) { return Promise.resolve(window.IrisEmojiData); }
        if (!emojiLoad) {
            emojiLoad = new Promise(function (ok, no) {
                var s = document.createElement('script');
                s.src = '/static/assets/js/iris/emoji_data.js';
                s.charset = 'utf-8';
                s.onload = function () { ok(window.IrisEmojiData); };
                s.onerror = function () { emojiLoad = null; no(new Error('emoji data')); };
                document.head.appendChild(s);
            });
        }
        return emojiLoad;
    }
    function emojiSearch(data, q, n) {
        q = q.toLowerCase();
        var out = [], seen = {};
        Object.keys(data.aliases).forEach(function (a) {
            if (a.indexOf(q) === 0 && !seen[data.aliases[a]]) { seen[data.aliases[a]] = 1; out.push([data.aliases[a], a]); }
        });
        data.groups.forEach(function (g) {
            g.emoji.forEach(function (e) {
                if (out.length >= n * 4 || seen[e[0]]) { return; }
                if (e[2].indexOf(q) === 0 || (q.length > 1 && e[1].toLowerCase().indexOf(q) !== -1)) { seen[e[0]] = 1; out.push([e[0], e[2]]); }
            });
        });
        out.sort(function (a, b) { return (a[1].indexOf(q) === 0 ? 0 : 1) - (b[1].indexOf(q) === 0 ? 0 : 1); });
        return out.slice(0, n);
    }
    function remember(e) {
        var r = (ls(LS_RECENT) || []).filter(function (x) { return x !== e; });
        r.unshift(e);
        ls(LS_RECENT, r.slice(0, 24));
    }
    var picker = null;
    function closePicker() { if (picker) { picker.el.remove(); picker = null; } }
    function openPicker(anchor, onPick) {
        closePicker();
        var el = document.createElement('div');
        el.className = 'iris-st-emoji';
        el.setAttribute('role', 'dialog');
        el.setAttribute('aria-label', 'Insert emoji');
        el.innerHTML = '<div class="iris-st-hint p-2">Loading…</div>';
        document.body.appendChild(el);
        var rect = anchor.getBoundingClientRect();
        el.style.left = Math.max(8, Math.min(window.innerWidth - 340, rect.left - 150)) + 'px';
        el.style.top = Math.max(8, rect.top - 370) + 'px';
        if (rect.top < 380) { el.style.top = (rect.bottom + 6) + 'px'; }
        picker = {el: el, onPick: onPick, group: null};
        emojiData().then(function (data) {
            if (!picker || picker.el !== el) { return; }
            var recent = ls(LS_RECENT) || [];
            picker.group = recent.length ? 'recent' : data.groups[0].key;
            el.innerHTML = '<input type="text" class="form-control" placeholder="Search emoji" aria-label="Search emoji">' +
                '<div class="iris-st-emotabs">' + (recent.length ? '<button type="button" data-g="recent" title="Recent">' + esc(recent[0]) + '</button>' : '') +
                data.groups.map(function (g) { return '<button type="button" data-g="' + esc(g.key) + '" title="' + esc(g.label) + '">' + esc(g.emoji[0][0]) + '</button>'; }).join('') +
                '</div><div class="iris-st-emogrid" id="iris-st-emogrid"></div>';
            var grid = el.querySelector('.iris-st-emogrid');
            var input = el.querySelector('input');
            function draw() {
                var q = input.value.trim();
                var list;
                if (q) { list = [{label: 'Results', emoji: emojiSearch(data, q, 64).map(function (x) { return [x[0], x[1], x[1]]; })}]; } else if (picker.group === 'recent') {
                    list = [{label: 'Recent', emoji: recent.map(function (e) { return [e, '', '']; })}];
                } else {
                    list = data.groups.filter(function (g) { return g.key === picker.group; });
                }
                el.querySelectorAll('.iris-st-emotabs button').forEach(function (b) { b.classList.toggle('iris-st-on', !q && b.getAttribute('data-g') === picker.group); });
                grid.innerHTML = list.map(function (g) {
                    return '<div class="iris-st-emolabel">' + esc(g.label) + '</div>' + g.emoji.map(function (e) {
                        return '<button type="button" data-e="' + esc(e[0]) + '" title="' + esc(e[1] ? ':' + e[2] + ':' : '') + '">' + esc(e[0]) + '</button>';
                    }).join('');
                }).join('') || '<div class="iris-st-emolabel">No match</div>';
            }
            el.addEventListener('click', function (ev) {
                var t = ev.target.closest('[data-g]');
                if (t) { picker.group = t.getAttribute('data-g'); input.value = ''; draw(); return; }
                var b = ev.target.closest('[data-e]');
                if (b) { var e = b.getAttribute('data-e'); remember(e); var cb = picker.onPick; closePicker(); cb(e); }
            });
            input.addEventListener('input', draw);
            input.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') { closePicker(); } });
            draw();
            input.focus();
        }, function () { el.innerHTML = '<div class="iris-st-hint p-2">The emoji list could not be loaded.</div>'; });
    }
    function insertAt(input, text) {
        var a = input.selectionStart, b = input.selectionEnd;
        if (typeof a !== 'number') { a = b = input.value.length; }
        input.value = input.value.slice(0, a) + text + input.value.slice(b);
        input.setSelectionRange(a + text.length, a + text.length);
        input.focus();
        input.dispatchEvent(new Event('input', {bubbles: true}));
    }
    /* :shortcode completion in a composer */
    var ac = {open: false, items: [], idx: 0, input: null, box: null, start: 0};
    function acClose() { ac.open = false; if (ac.box) { ac.box.style.display = 'none'; } }
    function acUpdate(input, box) {
        var pos = input.selectionStart;
        var m = input.value.slice(0, pos).match(/(^|\s):([a-z0-9_+\-]{2,30})$/i);
        if (!m) { acClose(); return; }
        ac.input = input; ac.box = box; ac.start = pos - m[2].length - 1;
        emojiData().then(function (data) {
            var full = m[2].toLowerCase();
            ac.items = emojiSearch(data, full, 8);
            ac.idx = 0;
            ac.open = ac.items.length > 0;
            if (!ac.open) { acClose(); return; }
            box.innerHTML = ac.items.map(function (x, k) {
                return '<div class="' + (k === ac.idx ? 'iris-st-on' : '') + '" data-k="' + k + '">' + esc(x[0]) + ' <code>:' + esc(x[1]) + ':</code></div>';
            }).join('');
            box.style.display = '';
        }, acClose);
    }
    function acPick(k) {
        var it = ac.items[k === undefined ? ac.idx : k];
        if (!it || !ac.input) { return; }
        var inp = ac.input;
        var end = inp.selectionStart;
        inp.value = inp.value.slice(0, ac.start) + it[0] + ' ' + inp.value.slice(end);
        var p = ac.start + it[0].length + 1;
        inp.setSelectionRange(p, p);
        remember(it[0]);
        acClose();
        inp.focus();
    }
    function acKey(e) {
        if (!ac.open || e.target !== ac.input) { return; }
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault(); e.stopPropagation();
            ac.idx = (ac.idx + (e.key === 'ArrowDown' ? 1 : ac.items.length - 1)) % ac.items.length;
            ac.box.querySelectorAll('[data-k]').forEach(function (d, k) { d.className = k === ac.idx ? 'iris-st-on' : ''; });
        } else if (e.key === 'Enter' || e.key === 'Tab') {
            e.preventDefault(); e.stopPropagation(); acPick();
        } else if (e.key === 'Escape') { e.stopPropagation(); acClose(); }
    }

    /* --------------------------------------------------------------- the actions */
    function itemByKey(key) { return S.chat.map[key] || S.rail.map[key] || null; }
    function msgById(id) {
        id = parseInt(id, 10);
        var hit = null;
        Object.keys(S.chat.map).forEach(function (k) { if (S.chat.map[k].kind === 'message' && S.chat.map[k].id === id) { hit = S.chat.map[k]; } });
        if (!hit && S.thread && S.thread.data && S.thread.data.root) {
            [S.thread.data.root].concat(S.thread.data.replies || []).forEach(function (x) { if (x.id === id) { hit = x; } });
        }
        return hit;
    }
    function afterChange() { refresh('chat'); if (S.thread) { loadThread(); } loadMeta(); }
    function react(id, emoji) {
        api('POST', '/messages/' + parseInt(id, 10) + '/reactions', {emoji: emoji}).then(function (res) {
            if (!res.ok) { status(res.j.message || 'Could not save the reaction'); return; }
            var m = msgById(id);
            if (m) { m.reactions = res.j.reactions; }
            renderChat(); if (S.thread) { renderThread(); }
        });
    }
    function startEdit(id) { S.editing = parseInt(id, 10); renderChat(); if (S.thread) { renderThread(); } }
    function saveEdit() {
        var inp = $id('iris-st-edit-input');
        var id = S.editing;
        if (!inp || !id) { return; }
        var m = msgById(id);
        var text = inp.value.trim();
        if (!text || (m && text === m.content)) { S.editing = null; renderChat(); if (S.thread) { renderThread(); } return; }
        fetch('/api/v2/war-rooms/' + S.rid + '/messages/' + id, {
            method: 'PUT', headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
            body: JSON.stringify({content: text})
        }).then(function (r) { return r.json().then(function (j) { return {ok: r.ok, j: j}; }); }).then(function (res) {
            if (!res.ok) { status(res.j.message || 'Could not edit the message'); return; }
            S.editing = null;
            if (m) { Object.keys(res.j).forEach(function (k) { m[k] = res.j[k]; }); }
            renderChat(); if (S.thread) { renderThread(); }
        });
    }
    function del(id) {
        if (!window.confirm('Delete this message?\n\nIt will be hidden from the stream. This can\'t be undone.')) { return; }
        fetch('/api/v2/war-rooms/' + S.rid + '/messages/' + parseInt(id, 10), {method: 'DELETE', headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.json().then(function (j) { return {ok: r.ok, j: j}; }); }).then(function (res) {
                if (!res.ok) { status(res.j.message || 'Could not delete the message'); return; }
                delete S.chat.map['message:' + parseInt(id, 10)];
                if (S.thread && S.thread.rootId === parseInt(id, 10)) { closeThread(); }
                renderChat();
                afterChange();
            });
    }
    function pin(id, pinned) {
        api('POST', '/messages/' + parseInt(id, 10) + '/pin', {pinned: !pinned}).then(function (res) {
            if (!res.ok) { status(res.j.message || 'Could not pin the message'); return; }
            afterChange();
        });
    }
    function discuss(key) {
        var i = itemByKey(key);
        var input = $id('iris-wr-msg-input');
        if (!i || !input) { return; }
        var who = i.actor_name ? i.actor_name + ' ' : '';
        var line = '> ' + who + String(i.content || '').replace(/\s+/g, ' ').trim() + ' · #activity-' + actCode(i) + i.id;
        input.value = line + '\n' + input.value;
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
        input.dispatchEvent(new Event('input', {bubbles: true}));
    }
    function showInActivity(code) {
        var map = {a: 'activity', c: 'case_activity', d: 'decision'};
        var key = map[code.charAt(0)] + ':' + parseInt(code.slice(1), 10);
        var i = S.rail.map[key] || S.chat.map[key];
        if (i && isMuted(i)) { status('Hidden by your settings — that activity is muted in the Activity settings.'); return; }
        if (!S.prefs.railOpen) { S.prefs.railOpen = true; savePrefs(); layout(); }
        if (S.thread) { closeThread(); }
        S.rail.chip = 'all'; S.rail.filter = '';
        var f = $id('iris-st-actfilter'); if (f) { f.value = ''; }
        renderRail();
        var el = document.querySelector('#iris-st-actlist [data-key="' + key + '"], #iris-wr-chat [data-key="' + key + '"]');
        if (!el) { status('Not found — that activity is far back in the stream, or its lane is off in the Activity settings.'); return; }
        el.scrollIntoView({block: 'center'});
        el.classList.add('iris-st-flash');
        setTimeout(function () { el.classList.remove('iris-st-flash'); }, 1600);
    }
    function jumpTo(msgId, parentId, tries) {
        if (parentId) { openThread(parentId); return; }
        var el = document.querySelector('#iris-wr-chat [data-msg-id="' + parseInt(msgId, 10) + '"]');
        if (el) {
            el.scrollIntoView({block: 'center'});
            el.classList.add('iris-st-flash');
            setTimeout(function () { el.classList.remove('iris-st-flash'); }, 1600);
            return;
        }
        if (!S.chat.done && (tries || 0) < 10) {
            load('chat', true).then(function () { jumpTo(msgId, null, (tries || 0) + 1); });
            return;
        }
        status('Message not loaded — scroll up in the chat to load older messages and find it.');
    }
    function openIndex(el) {
        var t = el.getAttribute('data-idx-type'), id = parseInt(el.getAttribute('data-idx-id'), 10);
        if (t === 'decision') { window.iris_wroom_open_pane('decisions', {decisionId: id}); return; }
        if (t === 'note') { window.iris_wroom_show_pane('notes'); window.iris_wroom_nt_open_room(id); return; }
        var parent = parseInt(el.getAttribute('data-idx-parent') || '0', 10) || null;
        if (S.only !== null && !parent) { S.only = null; renderConv(); renderChat(); }
        jumpTo(id, parent);
    }
    var menu = null;
    function closeMenu() { if (menu) { menu.remove(); menu = null; } }
    function muteMenu(btn, key) {
        closeMenu();
        var i = itemByKey(key);
        if (!i) { return; }
        var opts = [];
        if (i.kind === 'case_activity' && i.case_id) {
            var lbl = slugLabel(i.activity_type);
            opts.push(['type', 'Mute “' + lbl + '” on case #' + i.case_id]);
            opts.push(['case', 'Mute everything from case #' + i.case_id]);
        }
        if (i.kind === 'war_room_activity') {
            var fam = (S.vocab.families.filter(function (f) { return f.key === i.family; })[0] || {}).label || i.family;
            opts.push(['family', 'Mute war-room activity: ' + fam]);
        }
        var l = laneOfKind(i.kind);
        if (l) { opts.push(['lane', 'Turn off “' + lane(l).label + '”']); }
        menu = document.createElement('div');
        menu.className = 'iris-st-menu';
        menu.setAttribute('role', 'menu');
        menu.innerHTML = opts.map(function (o) { return '<button type="button" role="menuitem" data-mute="' + o[0] + '">' + ic('belloff') + esc(o[1]) + '</button>'; }).join('');
        document.body.appendChild(menu);
        var r = btn.getBoundingClientRect();
        menu.style.left = Math.max(8, Math.min(window.innerWidth - 240, r.right - 230)) + 'px';
        menu.style.top = (r.bottom + 4) + 'px';
        menu.addEventListener('click', function (e) {
            var b = e.target.closest('[data-mute]');
            if (!b) { return; }
            var what = b.getAttribute('data-mute'), p = S.prefs;
            if (what === 'type') {
                var per = p.excludedCaseActivities[String(i.case_id)] || [];
                if (per.indexOf(i.activity_type) === -1) { per.push(i.activity_type); }
                p.excludedCaseActivities[String(i.case_id)] = per;
            } else if (what === 'case') {
                if (p.excludedCases.indexOf(i.case_id) === -1) { p.excludedCases.push(i.case_id); }
            } else if (what === 'family') {
                if (p.excludedRoomActivities.indexOf(i.family) === -1) { p.excludedRoomActivities.push(i.family); }
            } else if (what === 'lane') {
                p.routes[l] = 'off';
            }
            status(b.textContent.replace(/^Mute |^Turn off /, '') + ' — undo it in the Activity settings.');
            closeMenu();
            savePrefs();
            if (what === 'lane') { reloadFeeds(); } else { renderChat(); renderRail(); }
        });
    }
    function slugLabel(slug) {
        var out = slug;
        S.vocab.case_activity.forEach(function (g) {
            g.slugs.forEach(function (s) { if (s.slug === slug) { out = g.key === 'other' ? s.label : g.label + ' ' + s.label.toLowerCase(); } });
        });
        return out;
    }

    /* ----------------------------------------------------------- Activity settings */
    function settingsHtml() {
        var p = S.prefs;
        var cases = (room().cases || []);
        var h = '<div class="iris-st-set"><h6>Where events go</h6>' +
            '<div class="iris-st-hint mb-1"><b>Rail</b> this panel · <b>Chat</b> inline in the conversation · <b>Off</b> hidden everywhere</div>' +
            S.vocab.lanes.map(function (l) {
                return '<div class="iris-st-lane"><span>' + esc(l.label) + '</span><div class="iris-st-seg" role="radiogroup" aria-label="Where ' + esc(l.label) + ' goes">' +
                    S.vocab.routes.map(function (r) {
                        return '<button type="button" role="radio" aria-checked="' + (p.routes[l.key] === r ? 'true' : 'false') + '" class="' +
                            (p.routes[l.key] === r ? 'iris-st-on' : '') + '" data-route="' + r + '" data-lane="' + l.key + '">' + r.charAt(0).toUpperCase() + r.slice(1) + '</button>';
                    }).join('') + '</div></div>' + (l.key === 'room_activity' && p.routes.room_activity !== 'off'
                    ? '<div class="iris-st-fams">' + S.vocab.families.map(function (f) {
                        var on = p.excludedRoomActivities.indexOf(f.key) === -1;
                        return '<label><input type="checkbox" data-family="' + f.key + '"' + (on ? ' checked' : '') + '> ' + esc(f.label) + '</label>';
                    }).join('') + '</div>' : '');
            }).join('') +
            '<div class="iris-st-hint mt-1">Messages and polls always stay in the chat.</div>' +
            '<h6>Noise</h6>' +
            '<div><label><input type="checkbox" data-pref="foldBursts"' + (p.foldBursts ? ' checked' : '') + '> Fold bursts</label>' +
            '<div class="iris-st-hint ml-3">3+ similar events in a row become one expandable row.</div></div>' +
            '<div class="mt-1"><label><input type="checkbox" data-pref="quietMode"' + (p.quietMode ? ' checked' : '') + '> Quiet mode</label>' +
            '<div class="iris-st-hint ml-3">Hide case “updated” events, keep creations, deletions and state changes.</div></div>' +
            '<h6>Cases (' + cases.length + ') ' + (window.IrisHelp ? window.IrisHelp.icon('room.case_activity') : '') + '</h6>' +
            (cases.length ? cases.map(function (c) {
                var cid = parseInt(c.case_id, 10);
                var muted = p.excludedCases.indexOf(cid) !== -1;
                var per = p.excludedCaseActivities[String(cid)] || [];
                var total = 0;
                S.vocab.case_activity.forEach(function (g) { total += g.slugs.length; });
                return '<div class="iris-st-case"><div class="d-flex align-items-center" style="gap:6px;">' +
                    '<label class="mb-0"><input type="checkbox" data-case="' + cid + '"' + (muted ? '' : ' checked') + ' aria-label="Show activity of case #' + cid + '"> #' + cid +
                    ' ' + esc(c.case_name || '') + '</label><a href="#" class="ml-auto iris-st-hint" data-case-types="' + cid + '" aria-label="Activity types of case #' + cid + '">' +
                    (total - per.length) + '/' + total + ' ' + ic('chevron') + '</a></div>' +
                    '<div class="iris-st-casetypes" id="iris-st-ct-' + cid + '">' + S.vocab.case_activity.map(function (g) {
                        return '<div class="iris-st-typegrp"><b>' + esc(g.label) + '</b> ' + g.slugs.map(function (s) {
                            return '<label class="mr-2"><input type="checkbox" data-case-slug="' + cid + '" data-slug="' + s.slug + '"' +
                                (per.indexOf(s.slug) === -1 ? ' checked' : '') + (muted ? ' disabled' : '') + '> ' + esc(s.label) + '</label>';
                        }).join('') + '</div>';
                    }).join('') + '</div></div>';
            }).join('') : '<div class="iris-st-hint">No cases attached. Anything attached later will appear here automatically.</div>') +
            '<div class="iris-st-hint mt-2">A case attached later starts streaming automatically.</div>' +
            '<div class="iris-st-hint mt-2">' + (S.guest ? 'Saved in this browser.' : 'Saved to your profile, applies to every war room you open.') + '</div></div>';
        return h;
    }
    function openSettings() {
        $id('iris-st-settings-body').innerHTML = settingsHtml();
        if ($) { $('#iris-st-settings-modal').modal('show'); }
    }
    function settingsChanged(routes) {
        savePrefs();
        $id('iris-st-settings-body').innerHTML = settingsHtml();
        layout();
        if (routes) { reloadFeeds(); } else { renderChat(); renderRail(); }
    }
    function closeSettings() {
        var m = $ && $('#iris-st-settings-modal');
        if (!m) { return; }
        /* Bootstrap 4 ignores a hide while the dialog is still opening (lessons 285, 290) */
        if (m.hasClass('show')) { m.modal('hide'); } else { m.one('shown.bs.modal', function () { m.modal('hide'); }); }
    }
    function reloadFeeds() {
        S.chat.map = {}; S.rail.map = {}; S.chat.done = S.rail.done = false;
        S.chat.cursor = S.rail.cursor = null;
        S.rail.pending = {};
        return Promise.all([load('chat'), load('rail')]);
    }

    /* --------------------------------------------------------------- composer send */
    function send() {
        var input = $id('iris-wr-msg-input');
        var text = input.value.trim();
        if (text.charAt(0) === '/') { window.iris_wroom_run_command(text); return; }
        if (S.pending.main.some(function (p) { return p.uploading; })) { status('Wait for the upload to finish'); return; }
        var content = withTokens(text, 'main');
        if (!content) { return; }
        if (topicArchived(S.target)) { status('The selected topic is archived — pick a live one.'); return; }
        window.iris_wroom_post({content: content, topic: S.target}, true).then(function (res) {
            if (res && res.ok) {
                S.pending.main = [];
                renderAttach('main');
                if (!topicRow(S.target)) { loadTopics(); }
            }
        });
    }

    /* ------------------------------------------------------------------- wiring */
    function wire() {
        var st = $id('iris-st');
        /* chat + thread: messages, reactions, threads, polls, chips */
        st.addEventListener('click', function (e) {
            var t = e.target;
            var a = t.closest('[data-act]');
            var msg = t.closest('[data-msg-id]');
            var act = a ? a.getAttribute('data-act') : null;
            if (t.closest('.iris-st-react') && !t.closest('.iris-st-react').disabled) {
                var rb = t.closest('.iris-st-react');
                react(rb.getAttribute('data-msg-id'), rb.getAttribute('data-react'));
                return;
            }
            if (act === 'react' && msg) { openPicker(a, function (em) { react(msg.getAttribute('data-msg-id'), em); }); return; }
            if (act === 'thread' && msg) { openThread(msg.getAttribute('data-msg-id')); return; }
            if (act === 'edit' && msg) { startEdit(msg.getAttribute('data-msg-id')); return; }
            if (act === 'delete' && msg) { del(msg.getAttribute('data-msg-id')); return; }
            if (act === 'pin' && msg) { pin(msg.getAttribute('data-msg-id'), a.getAttribute('data-pinned') === '1'); return; }
            if (act === 'save-edit') { saveEdit(); return; }
            if (act === 'cancel-edit') { S.editing = null; renderChat(); if (S.thread) { renderThread(); } return; }
            var chip = t.closest('.iris-st-threadchip');
            if (chip) { openThread(chip.getAttribute('data-thread')); return; }
            var burst = t.closest('a.iris-st-burst');
            if (burst) {
                e.preventDefault();
                var id = burst.getAttribute('data-burst');
                S.expanded[id] = !S.expanded[id];
                if (t.closest('#iris-st-actlist')) { renderRail(true); } else { renderChat(true); }
                return;
            }
            var note = t.closest('[data-note]');
            if (note) { e.preventDefault(); window.iris_wroom_show_pane('notes'); window.iris_wroom_nt_open_room(parseInt(note.getAttribute('data-note'), 10)); return; }
            var pane = t.closest('a[data-pane]');
            if (pane) { e.preventDefault(); window.iris_wroom_show_pane(pane.getAttribute('data-pane')); return; }
            var jump = t.closest('[data-jump]');
            if (jump) { e.preventDefault(); jumpTo(jump.getAttribute('data-jump')); return; }
            var al = t.closest('.iris-st-actlink');
            if (al) { e.preventDefault(); showInActivity(al.getAttribute('data-act')); return; }
            var vote = t.closest('.iris-wr-poll-opt');
            if (vote && !vote.classList.contains('closed')) {
                api('POST', '/polls/' + vote.getAttribute('data-poll-id') + '/vote',
                    {option_id: parseInt(vote.getAttribute('data-option-id'), 10)}).then(function () { refresh('chat'); });
                return;
            }
            var pclose = t.closest('.iris-wr-poll-close');
            if (pclose) {
                e.preventDefault();
                api('POST', '/polls/' + pclose.getAttribute('data-poll-id') + '/close', {}).then(function () { refresh('chat'); });
                return;
            }
            /* Activity rail */
            if (act === 'discuss') { discuss(t.closest('[data-key]').getAttribute('data-key')); return; }
            if (act === 'mute') { muteMenu(a, t.closest('[data-key]').getAttribute('data-key')); return; }
            if (act === 'settings') { e.preventDefault(); openSettings(); return; }
            var lc = t.closest('.iris-st-lanechip');
            if (lc) { S.rail.chip = lc.getAttribute('data-chip'); renderRail(); return; }
            /* thread panel */
            if (act === 'close-thread') { closeThread(); return; }
            if (act === 'follow' && S.thread && S.thread.data) {
                api('POST', '/messages/' + S.thread.rootId + '/follow', {following: !S.thread.data.following}).then(function (res) {
                    if (!res.ok) { status(res.j.message || 'Could not update follow state'); return; }
                    S.thread.data.following = res.j.following;
                    renderThread(); loadMeta();
                });
                return;
            }
            if (act === 'rename-thread' && S.thread) {
                var cur = (S.thread.data.root.thread_title || '');
                var nt = window.prompt('Thread title (empty = none):', cur);
                if (nt === null) { return; }
                fetch('/api/v2/war-rooms/' + S.rid + '/messages/' + S.thread.rootId + '/thread-title', {
                    method: 'PUT', headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
                    body: JSON.stringify({title: nt})
                }).then(function (r) { return r.json().then(function (j) { return {ok: r.ok, j: j}; }); }).then(function (res) {
                    if (!res.ok) { status(res.j.message || 'Could not rename thread'); return; }
                    loadThread(); refresh('chat'); loadMeta();
                });
                return;
            }
            if (act === 'send-thread') { sendThread(); return; }
            if (act === 'attach') { var fi = $id('iris-st-file-input'); fi.setAttribute('data-where', attachSlot(a.getAttribute('data-where'))); fi.click(); return; }
            if (act === 'unattach') { var uw = attachSlot(a.getAttribute('data-where')); S.pending[uw].splice(parseInt(a.getAttribute('data-k'), 10), 1); renderAttach(uw); return; }
            if (act === 'emoji') {
                var where = attachSlot(a.getAttribute('data-where'));
                openPicker(a, function (em) { insertAt($id(where === 'main' ? 'iris-wr-msg-input' : 'iris-st-thread-input'), em); });
                return;
            }
            if (act === 'showrail') { S.prefs.railOpen = true; savePrefs(); layout(); renderRail(); return; }
            if (act === 'closerail') { S.prefs.railOpen = false; savePrefs(); layout(); return; }
            if (act === 'pause') {
                S.rail.paused = !S.rail.paused;
                if (!S.rail.paused) { Object.keys(S.rail.pending).forEach(function (k) { S.rail.map[k] = S.rail.pending[k]; }); S.rail.pending = {}; renderRail(); } else { renderRailHead(); }
                return;
            }
            /* Conversation rail */
            var row = t.closest('[data-topic]');
            if (act === 'toggle-topic' && row) { var nm = row.getAttribute('data-topic'); S.hidden[nm] = !S.hidden[nm]; S.only = null; saveTopicView(); renderConv(); renderChat(); return; }
            if (act === 'only-topic' && row) {
                var on = row.getAttribute('data-topic');
                S.only = S.only === on ? null : on;
                if (S.only !== null && !topicArchived(S.only)) { setTarget(S.only); }
                renderConv(); renderChat();
                return;
            }
            if (act === 'all-topics') { e.preventDefault(); S.only = null; renderConv(); renderChat(); return; }
            if (act === 'toggle-archived') { S.showArchived = !S.showArchived; renderConv(); return; }
            if ((act === 'archive-topic' || act === 'restore-topic') && a) {
                api('POST', '/topics/' + parseInt(a.getAttribute('data-topic-id'), 10) + (act === 'archive-topic' ? '/archive' : '/restore'), {})
                    .then(function (res) {
                        if (!res.ok) { status(res.j.message || 'Could not change the topic'); return; }
                        S.topics = res.j.topics || S.topics;
                        if (act === 'archive-topic' && S.target === res.j.name) { setTarget('main'); }
                        renderConv(); renderTarget(); renderChat();
                    });
                return;
            }
            var th = t.closest('#iris-st-threads [data-thread]');
            if (th) { openThread(th.getAttribute('data-thread')); return; }
            var ix = t.closest('.iris-st-idx');
            if (ix) { openIndex(ix); return; }
        });
        st.addEventListener('keydown', function (e) {
            if ((e.key === 'Enter' || e.key === ' ') && e.target.classList && (e.target.classList.contains('iris-st-idx') || e.target.getAttribute('data-act') === 'toggle-topic')) {
                e.preventDefault(); e.target.click();
            }
            if (e.target.id === 'iris-st-edit-input') {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEdit(); }
                if (e.key === 'Escape') { S.editing = null; renderChat(); if (S.thread) { renderThread(); } }
            }
            if (e.target.id === 'iris-st-thread-input') {
                /* the @-palette of the thread composer owns Tab / Enter / arrows / Escape while open */
                if (window.iris_wroom_mention_key(e)) { return; }
                if (e.key === 'Enter' && !e.shiftKey && !ac.open) { e.preventDefault(); sendThread(); }
            }
        });
        /* :shortcode completion runs before the composers' own keys (capture) */
        st.addEventListener('keydown', acKey, true);
        st.addEventListener('input', function (e) {
            if (e.target.id === 'iris-wr-msg-input') { acUpdate(e.target, $id('iris-st-ac')); }
            if (e.target.id === 'iris-st-thread-input') {
                acUpdate(e.target, $id('iris-st-thread-ac'));
                window.iris_wroom_mention_bind(e.target, $id('iris-st-thread-mention-pop'));
                window.iris_wroom_mention_update();
            }
            if (e.target.id === 'iris-st-actfilter') { S.rail.filter = e.target.value.trim(); renderRail(); }
            if (e.target.id === 'iris-st-indexq') { S.indexQ = e.target.value.trim(); renderIndex(); }
        });
        st.addEventListener('focusin', function (e) {
            if (e.target.id === 'iris-wr-msg-input') { window.iris_wroom_mention_bind(null, null); }
        });
        st.addEventListener('mousedown', function (e) {
            var k = e.target.closest('.iris-st-ac [data-k]');
            if (k) { e.preventDefault(); acPick(parseInt(k.getAttribute('data-k'), 10)); }
        });
        /* chat search (server side) */
        var tmr = null;
        $id('iris-wr-chat-filter').addEventListener('input', function () {
            var v = this.value.trim();
            clearTimeout(tmr);
            tmr = setTimeout(function () { S.chat.q = v; S.chat.map = {}; S.chat.done = false; S.chat.cursor = null; load('chat'); }, 300);
        });
        $id('iris-wr-chat-filter').addEventListener('keydown', function (e) {
            if (e.key === 'Escape') { this.value = ''; S.chat.q = ''; load('chat'); }
        });
        /* older pages on scroll */
        $id('iris-wr-chat').addEventListener('scroll', function () { if (this.scrollTop < 40) { load('chat', true); } });
        $id('iris-st-actlist').addEventListener('scroll', function () { if (this.scrollTop < 40) { load('rail', true); } });
        /* attachments: picker, drop, paste */
        $id('iris-st-file-input').addEventListener('change', function () {
            uploadFiles(this.files, attachSlot(this.getAttribute('data-where')));
            this.value = '';
        });
        var main = $id('iris-st-main'), drop = $id('iris-st-drop'), depth = 0;
        main.addEventListener('dragenter', function (e) {
            if (!canPost() || !e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') === -1) { return; }
            depth++; drop.classList.add('iris-st-on'); e.preventDefault();
        });
        main.addEventListener('dragover', function (e) { if (drop.classList.contains('iris-st-on')) { e.preventDefault(); } });
        main.addEventListener('dragleave', function () { depth = Math.max(0, depth - 1); if (!depth) { drop.classList.remove('iris-st-on'); } });
        main.addEventListener('drop', function (e) {
            if (!drop.classList.contains('iris-st-on')) { return; }
            e.preventDefault(); depth = 0; drop.classList.remove('iris-st-on');
            uploadFiles(e.dataTransfer.files, 'main');
        });
        st.addEventListener('paste', function (e) {
            var inp = e.target;
            if (!inp || (inp.id !== 'iris-wr-msg-input' && inp.id !== 'iris-st-thread-input') || !e.clipboardData) { return; }
            var files = Array.prototype.slice.call(e.clipboardData.files || []).filter(function (f) { return /^image\//.test(f.type); });
            if (!files.length) { return; }
            e.preventDefault();
            uploadFiles(files.map(function (f) { return new File([f], pastedName(f), {type: f.type}); }), inp.id === 'iris-wr-msg-input' ? 'main' : 'thread');
        });
        /* composer target */
        $id('iris-wr-post-target').addEventListener('click', function (e) {
            e.stopPropagation();
            var dd = $id('iris-st-target-dd');
            if (dd.style.display !== 'none') { dd.style.display = 'none'; return; }
            var live = S.topics.filter(function (x) { return !x.archived; });
            dd.innerHTML = live.map(function (x) {
                return '<button type="button" data-target="' + esc(x.name) + '" class="' + (x.name === S.target ? 'iris-st-on' : '') + '"># ' + esc(x.is_main ? 'Main' : x.name) + '</button>';
            }).join('') + (canPost() ? '<button type="button" data-act="new-topic">' + ic('plus') + ' New topic…</button>' : '');
            dd.style.display = '';
        });
        $id('iris-st-target-dd').addEventListener('click', function (e) {
            var b = e.target.closest('[data-target]');
            if (b) { setTarget(b.getAttribute('data-target')); this.style.display = 'none'; renderConv(); return; }
            if (e.target.closest('[data-act="new-topic"]')) { this.style.display = 'none'; newTopic(); }
        });
        document.addEventListener('click', function (e) {
            var dd = $id('iris-st-target-dd');
            if (dd && dd.style.display !== 'none' && !e.target.closest('#iris-st-target-dd')) { dd.style.display = 'none'; }
            if (picker && !e.target.closest('.iris-st-emoji') && !e.target.closest('[data-act="emoji"],[data-act="react"]')) { closePicker(); }
            if (menu && !e.target.closest('.iris-st-menu') && !e.target.closest('[data-act="mute"]')) { closeMenu(); }
        });
        document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { closePicker(); closeMenu(); } });
        $id('iris-wr-topic-add').addEventListener('click', function (e) { e.preventDefault(); newTopic(); });
        /* settings dialog */
        var body = $id('iris-st-settings-body');
        body.addEventListener('click', function (e) {
            var rb = e.target.closest('[data-route]');
            if (rb) { S.prefs.routes[rb.getAttribute('data-lane')] = rb.getAttribute('data-route'); settingsChanged(true); return; }
            var ct = e.target.closest('[data-case-types]');
            if (ct) { e.preventDefault(); $id('iris-st-ct-' + ct.getAttribute('data-case-types')).classList.toggle('iris-st-on'); }
        });
        body.addEventListener('change', function (e) {
            var t = e.target, p = S.prefs;
            if (t.hasAttribute('data-pref')) { p[t.getAttribute('data-pref')] = t.checked; settingsChanged(false); return; }
            if (t.hasAttribute('data-family')) {
                var f = t.getAttribute('data-family');
                p.excludedRoomActivities = p.excludedRoomActivities.filter(function (x) { return x !== f; });
                if (!t.checked) { p.excludedRoomActivities.push(f); }
                settingsChanged(false);
                return;
            }
            if (t.hasAttribute('data-case')) {
                var cid = parseInt(t.getAttribute('data-case'), 10);
                p.excludedCases = p.excludedCases.filter(function (x) { return x !== cid; });
                if (!t.checked) { p.excludedCases.push(cid); }
                settingsChanged(false);
                return;
            }
            if (t.hasAttribute('data-case-slug')) {
                var c2 = t.getAttribute('data-case-slug'), slug = t.getAttribute('data-slug');
                var per = (p.excludedCaseActivities[c2] || []).filter(function (x) { return x !== slug; });
                if (!t.checked) { per.push(slug); }
                if (per.length) { p.excludedCaseActivities[c2] = per; } else { delete p.excludedCaseActivities[c2]; }
                var open = $id('iris-st-ct-' + c2) && $id('iris-st-ct-' + c2).classList.contains('iris-st-on');
                settingsChanged(false);
                if (open) { $id('iris-st-ct-' + c2).classList.add('iris-st-on'); }
            }
        });
        $id('iris-st-settings-reset').addEventListener('click', function () { S.prefs = normalisePrefs(null); settingsChanged(true); });
        $id('iris-st-settings-done').addEventListener('click', closeSettings);
        /* the Activity panel's width */
        var grip = $id('iris-st-resize');
        grip.addEventListener('pointerdown', function (e) {
            e.preventDefault();
            var startX = e.clientX, startW = S.prefs.railWidth, lim = S.vocab.limits.rail_width;
            function mv(ev) {
                S.prefs.railWidth = Math.max(lim[0], Math.min(lim[1], startW + (startX - ev.clientX)));
                $id('iris-st').style.setProperty('--iris-st-rail', S.prefs.railWidth + 'px');
            }
            function up() { document.removeEventListener('pointermove', mv); document.removeEventListener('pointerup', up); savePrefs(); }
            document.addEventListener('pointermove', mv);
            document.addEventListener('pointerup', up);
        });
        grip.addEventListener('keydown', function (e) {
            if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') { return; }
            var lim = S.vocab.limits.rail_width;
            S.prefs.railWidth = Math.max(lim[0], Math.min(lim[1], S.prefs.railWidth + (e.key === 'ArrowLeft' ? 20 : -20)));
            layout(); savePrefs();
        });
        window.addEventListener('resize', fit);
    }
    function newTopic() {
        if (!canPost()) { return; }
        var name = window.prompt('New topic name:');
        if (!name || !name.trim()) { return; }
        api('POST', '/topics', {name: name}).then(function (res) {
            if (!res.ok) { status(res.j.message || 'Could not create topic'); return; }
            S.topics = res.j.topics || S.topics;
            setTarget(res.j.name);
            renderConv();
            $id('iris-wr-msg-input').focus();
        });
    }
    function saveTopicView() { ls('irisStreamTopics:' + S.rid, {hidden: S.hidden}); }

    /* ------------------------------------------------------------------- public */
    R.mount = function (ctx) {
        if (S.mounted) { return Promise.resolve(); }
        S.mounted = true;
        S.rid = ctx.roomId;
        S.guest = !!ctx.guest;
        css();
        var saved = ls('irisStreamTopics:' + S.rid);
        if (saved && saved.hidden) { S.hidden = saved.hidden; }
        wire();
        return api('GET', '/stream/vocab').then(function (res) {
            S.vocab = res.ok ? res.j : null;
            if (!S.vocab) { status('The stream could not be loaded'); return; }
            return loadPrefs();
        }).then(function () {
            if (!S.vocab) { return; }
            layout();
            setTarget('main');
            return Promise.all([reloadFeeds(), loadMeta()]).then(function () {
                if (R._pendingThread) { openThread(R._pendingThread); R._pendingThread = null; }
            });
        });
    };
    /* every 5 s (war_room.js): the newest page of both feeds, the open thread; topics, threads and the index
       every 15 s */
    R.poll = function () {
        if (!S.vocab || !S.prefs) { return; }
        refresh('chat');
        refresh('rail');
        if (S.thread && !S.editing) { loadThread(); }
        if (Date.now() - S.lastMeta > 15000) { loadMeta(); }
    };
    R.refresh = function () { if (S.vocab && S.prefs) { refresh('chat'); refresh('rail'); loadMeta(); } };
    R.shown = function () {
        layout();
        var box = $id('iris-wr-chat');
        if (box) { box.scrollTop = box.scrollHeight; }
        var rail = $id('iris-st-actlist');
        if (rail) { rail.scrollTop = rail.scrollHeight; }
    };
    R.casesChanged = function () { if (S.vocab && S.prefs) { reloadFeeds(); } };
    R.openThread = function (id) { if (S.vocab) { openThread(id); } else { R._pendingThread = id; } };
    R.setTarget = function (name) { setTarget(name); renderConv(); };
    R.target = function () { return S.target; };
    R.afterPost = function () { if (S.vocab && S.prefs) { refresh('chat'); loadMeta(); } };
    R.openSettings = function () { openSettings(); };
    R.send = function () { send(); };
    R._state = S;
    window.IrisRoomStream = R;
}());

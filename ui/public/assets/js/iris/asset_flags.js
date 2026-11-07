/* Asset flags: shared widgets (iris-ng 2026-11-07).
 *
 * window.IrisFlags - import-free (ui/public: Vite never tree-shakes it). Used by
 * Settings -> Asset flags (the catalogue), the case Assets page (row chips, the
 * Flag filter, the Flags row of the selected asset) and the war-room Board.
 *
 *   IrisFlags.chip(flag, {remove})        a flag chip (icon + name, its colour)
 *   IrisFlags.icon(name, size)            one of the 19 Lucide icons (ISC)
 *   IrisFlags.catalogue(force)            GET /api/v2/manage/asset-flags (cached)
 *   IrisFlags.mountSettings(el)           the Settings page
 *   IrisFlags.renderAssetFlags(host, o)   the Flags row of a case asset (re-callable after every render)
 *   IrisFlags.history(caseId, assetId, assetName)   the asset's flag history in a modal
 *
 * Every server value goes through esc() before an innerHTML build; ids
 * through id(); colours and icons through the allowlists below. POST bodies
 * carry csrf_token (the v2 rule); PUT / DELETE are exempt.
 */
(function () {
    'use strict';
    if (window.IrisFlags) { return; }
    var F = {};
    /* (i) help icons (help_tips.js); calls stay literal - IrisHelp.icon('flags.kind') - for the glossary checker. */
    var IrisHelp = window.IrisHelp || {icon: function () { return ''; }};
    var API = '/api/v2/manage/asset-flags';

    F.COLORS = {
        slate: '#64748b', gray: '#6b7280', red: '#ef4444', orange: '#f97316', amber: '#f59e0b',
        yellow: '#eab308', lime: '#84cc16', green: '#22c55e', emerald: '#10b981', teal: '#14b8a6',
        cyan: '#06b6d4', sky: '#0ea5e9', blue: '#3b82f6', indigo: '#6366f1', violet: '#8b5cf6',
        purple: '#a855f7', fuchsia: '#d946ef', pink: '#ec4899', rose: '#f43f5e'
    };
    /* Lucide (ISC) path data */
    var SHIELD = '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>';
    F.ICONS = {
        'unplug': '<path d="m19 5 3-3"/><path d="m2 22 3-3"/><path d="M6.3 20.3a2.4 2.4 0 0 0 3.4 0L12 18l-6-6-2.3 2.3a2.4 2.4 0 0 0 0 3.4Z"/><path d="M7.5 13.5 10 11"/><path d="M10.5 16.5 13 14"/><path d="m12 6 6 6 2.3-2.3a2.4 2.4 0 0 0 0-3.4l-2.6-2.6a2.4 2.4 0 0 0-3.4 0Z"/>',
        'key-round': '<path d="M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z"/><circle cx="16.5" cy="7.5" r=".5" fill="currentColor"/>',
        'wrench': '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
        'hard-drive': '<line x1="22" x2="2" y1="12" y2="12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/><line x1="6" x2="6.01" y1="16" y2="16"/><line x1="10" x2="10.01" y1="16" y2="16"/>',
        'eye': '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
        'circle-check': '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
        'shield-off': '<path d="m2 2 20 20"/><path d="M5 5a1 1 0 0 0-1 1v7c0 5 3.5 7.5 7.67 8.94a1 1 0 0 0 .67.01c2.35-.82 4.48-1.97 5.9-3.71"/><path d="M9.309 3.652A12.252 12.252 0 0 0 11.24 2.28a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1v7a9.784 9.784 0 0 1-.08 1.264"/>',
        'octagon-x': '<path d="m15 9-6 6"/><path d="M2.586 16.726A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688A2 2 0 0 1 8.688 2h6.624a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 1-1.414-.586z"/><path d="m9 9 6 6"/>',
        'shield': SHIELD,
        'shield-check': SHIELD + '<path d="m9 12 2 2 4-4"/>',
        'triangle-alert': '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
        'scan-search': '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><circle cx="12" cy="12" r="3"/><path d="m16 16-1.9-1.9"/>',
        'microscope': '<path d="M6 18h8"/><path d="M3 22h18"/><path d="M14 22a7 7 0 1 0 0-14h-1"/><path d="M9 14h2"/><path d="M9 12a2 2 0 0 1-2-2V6h6v4a2 2 0 0 1-2 2Z"/><path d="M12 6V3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3"/>',
        'rotate-ccw': '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
        'circle-dot': '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="1"/>',
        'bug': '<path d="m8 2 1.88 1.88"/><path d="M14.12 3.88 16 2"/><path d="M9 7.13v-1a3.003 3.003 0 1 1 6 0v1"/><path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6"/><path d="M12 20v-9"/><path d="M6.53 9C4.6 8.8 3 7.1 3 5"/><path d="M6 13H2"/><path d="M3 21c0-2.1 1.7-3.9 3.8-4"/><path d="M20.97 5c0 2.1-1.6 3.8-3.5 4"/><path d="M22 13h-4"/><path d="M17.2 17c2.1.1 3.8 1.9 3.8 4"/>',
        'ban': '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
        'flag': '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" x2="4" y1="22" y2="15"/>',
        'hourglass': '<path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22"/><path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"/>'
    };
    var KIND_LABEL = {status: 'Status', done: 'Done', exception: 'Exception'};
    var MSG_ICON = '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>';
    var GAVEL = '<path d="m14.5 12.5-8 8a2.119 2.119 0 1 1-3-3l8-8"/><path d="m16 16 6-6"/><path d="m8 8 6-6"/><path d="m9 7 8 8"/><path d="m21 11-8-8"/>';

    /* ------------------------------------------------------------ utils */
    F.esc = function (s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    };
    F.id = function (v) {
        var s = String(v == null ? '' : v);
        return /^\d+$/.test(s) ? String(parseInt(s, 10)) : null;
    };
    F.color = function (name) { return Object.prototype.hasOwnProperty.call(F.COLORS, name) ? F.COLORS[name] : F.COLORS.slate; };
    F.svg = function (paths, size, extra) {
        return '<svg xmlns="http://www.w3.org/2000/svg" width="' + (size || 13) + '" height="' + (size || 13) +
            '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
            'stroke-linejoin="round" aria-hidden="true"' + (extra || '') + '>' + paths + '</svg>';
    };
    F.icon = function (name, size) {
        return F.svg(Object.prototype.hasOwnProperty.call(F.ICONS, name) ? F.ICONS[name] : F.ICONS['circle-dot'], size);
    };
    function rgba(hex, a) {
        var n = parseInt(hex.slice(1), 16);
        return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
    }
    F.chip = function (f, o) {
        o = o || {};
        var c = F.color(f.color);
        var tip = [f.description || '', f.reason ? 'Reason: ' + f.reason : '', f.decision_ref ? 'Decision ' + f.decision_ref : '']
            .filter(Boolean).join(' - ');
        return '<span class="iris-fl-chip' + (o.cls ? ' ' + o.cls : '') + '" data-flag-id="' + F.id(f.flag_id || f.id) +
            '" style="color:' + c + ';border-color:' + rgba(c, 0.45) + ';background:' + rgba(c, 0.12) + ';"' +
            (tip ? ' title="' + F.esc(tip) + '"' : '') + '>' + F.icon(f.icon, o.size || 12) +
            '<span class="iris-fl-chip-name">' + F.esc(f.name) + '</span>' +
            (f.decision_ref ? '<span class="iris-fl-chip-ref">' + F.esc(f.decision_ref) + '</span>' : '') +
            (o.remove ? '<button type="button" class="iris-fl-x" data-flag-id="' + F.id(f.flag_id || f.id) +
                '" aria-label="Remove ' + F.esc(f.name) + '">&times;</button>' : '') + '</span>';
    };
    F.csrf = function () {
        var el = document.getElementById('csrf_token') || document.querySelector('input[name="csrf_token"]');
        return el ? el.value : '';
    };
    F.api = function (path, method, body) {
        var opts = {method: method || 'GET', credentials: 'same-origin', headers: {'Accept': 'application/json'}};
        if (body !== undefined) {
            body = Object.assign({}, body);
            if (opts.method === 'POST') { body.csrf_token = F.csrf(); }
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        return fetch(path, opts).then(function (r) {
            if (r.status === 204) { return {ok: true, status: 204, j: {}}; }
            return r.json().then(function (j) { return {ok: r.ok, status: r.status, j: j}; },
                function () { return {ok: r.ok, status: r.status, j: {}}; });
        });
    };
    F.errText = function (res) {
        return (res && res.j && (res.j.message || (res.j.data && res.j.data.message))) || 'The request failed (HTTP ' + (res ? res.status : '?') + ').';
    };
    var cat = null;
    F.catalogue = function (force) {
        if (cat && !force) { return cat; }
        cat = F.api(API).then(function (res) {
            if (!res.ok || !Array.isArray(res.j)) { cat = null; throw new Error(F.errText(res)); }
            return res.j;
        });
        return cat;
    };
    F.css = function () {
        if (document.getElementById('iris-fl-css')) { return; }
        var st = document.createElement('style');
        st.id = 'iris-fl-css';
        st.textContent = [
            '.iris-fl-chip{display:inline-flex;align-items:center;gap:4px;border:1px solid;border-radius:6px;padding:0 6px;font-size:.72rem;line-height:1.6;white-space:nowrap;max-width:220px;}',
            '.iris-fl-chip-name{overflow:hidden;text-overflow:ellipsis;}',
            '.iris-fl-chip-ref{font-family:monospace;font-size:.66rem;opacity:.85;}',
            '.iris-fl-x{background:none;border:0;color:inherit;padding:0 0 0 2px;line-height:1;cursor:pointer;font-size:.9rem;opacity:.8;}',
            '.iris-fl-x:hover{opacity:1;}',
            '.iris-fl-row{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin-top:10px;}',
            '.iris-fl-lbl{color:#7a7a85;font-size:.62rem;letter-spacing:.08em;text-transform:uppercase;margin-right:2px;}',
            '.iris-fl-add{background:transparent;border:1px dashed rgba(255,255,255,.25);color:#b8b8c4;border-radius:6px;font-size:.72rem;padding:0 7px;line-height:1.6;cursor:pointer;}',
            '.iris-fl-add:hover{border-color:#8B5CF6;color:#e8e8ee;}',
            '.iris-fl-changes{margin-left:auto;font-size:.7rem;color:#9a9aa5;cursor:pointer;background:none;border:0;padding:0;}',
            '.iris-fl-changes:hover{color:#e8e8ee;text-decoration:underline;}',
            '.iris-fl-menu{margin-top:6px;border:1px solid rgba(255,255,255,.1);border-radius:8px;background:#1a1a20;max-height:260px;overflow:auto;}',
            '.iris-fl-opt{display:flex;align-items:flex-start;gap:8px;width:100%;text-align:left;background:none;border:0;border-bottom:1px solid rgba(255,255,255,.05);padding:6px 10px;color:#e8e8ee;cursor:pointer;}',
            '.iris-fl-opt:hover,.iris-fl-opt:focus{background:rgba(139,92,246,.12);outline:none;}',
            '.iris-fl-opt small{display:block;color:#9a9aa5;font-size:.7rem;}',
            '.iris-fl-kind{font-size:.62rem;border-radius:4px;padding:0 5px;margin-left:4px;border:1px solid rgba(255,255,255,.18);color:#c8c8d0;}',
            '.iris-fl-kind-done{color:#2dce89;border-color:rgba(45,206,137,.45);}',
            '.iris-fl-kind-exception{color:#f4c430;border-color:rgba(244,196,48,.45);}',
            '.iris-fl-kind-status{color:#8fa3ef;border-color:rgba(143,163,239,.45);}',
            '.iris-fl-form{margin-top:6px;border:1px solid rgba(139,92,246,.35);border-radius:8px;padding:8px 10px;}',
            '.iris-fl-form textarea{width:100%;min-height:54px;}',
            '.iris-fl-err{color:#ff8095;font-size:.75rem;margin-top:4px;}',
            '.iris-fl-muted{color:#9a9aa5;font-size:.75rem;}',
            '.iris-fl-set-wrap{display:flex;gap:16px;align-items:flex-start;}',
            '.iris-fl-panel{background:#15151a;border:1px solid rgba(255,255,255,.06);border-radius:8px;}',
            '.iris-fl-panel-head{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-bottom:1px solid rgba(255,255,255,.06);font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:#9a9aa5;}',
            '.iris-fl-list{list-style:none;margin:0;padding:0;}',
            '.iris-fl-li{display:flex;align-items:center;gap:10px;padding:9px 12px;border-bottom:1px solid rgba(255,255,255,.05);cursor:pointer;}',
            '.iris-fl-li:hover{background:rgba(255,255,255,.03);}',
            '.iris-fl-li.active{background:rgba(139,92,246,.12);box-shadow:inset 3px 0 0 #8B5CF6;}',
            '.iris-fl-li.dragging{opacity:.4;}',
            '.iris-fl-li.drop-before{box-shadow:inset 0 2px 0 #8B5CF6;}',
            '.iris-fl-handle{color:#55555e;cursor:grab;font-size:.9rem;user-select:none;}',
            '.iris-fl-dot{width:26px;height:26px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;}',
            '.iris-fl-li-main{flex:1 1 auto;min-width:0;}',
            '.iris-fl-li-main b{font-size:.84rem;font-weight:600;color:#e8e8ee;}',
            '.iris-fl-li-main div{color:#9a9aa5;font-size:.72rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
            '.iris-fl-use{color:#9a9aa5;font-size:.72rem;white-space:nowrap;min-width:64px;text-align:right;}',
            '.iris-fl-kv{display:grid;grid-template-columns:1fr 1fr;gap:14px 24px;padding:14px;}',
            '.iris-fl-kv .k{color:#7a7a85;font-size:.62rem;letter-spacing:.08em;text-transform:uppercase;margin-bottom:3px;}',
            '.iris-fl-kv .v{color:#e8e8ee;font-size:.84rem;}',
            '.iris-fl-preview{display:flex;flex-wrap:wrap;gap:6px;padding:12px 14px;border:1px solid rgba(255,255,255,.06);border-radius:8px;margin:0 14px 14px;}',
            '.iris-fl-swatches,.iris-fl-icons{display:flex;flex-wrap:wrap;gap:6px;}',
            '.iris-fl-swatch{width:24px;height:24px;border-radius:50%;border:2px solid transparent;cursor:pointer;padding:0;}',
            '.iris-fl-swatch[aria-checked="true"]{border-color:#fff;box-shadow:0 0 0 2px rgba(139,92,246,.7);}',
            '.iris-fl-iconbtn{width:32px;height:32px;border-radius:6px;border:1px solid rgba(255,255,255,.12);background:transparent;color:#c8c8d0;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;}',
            '.iris-fl-iconbtn[aria-checked="true"]{border-color:#8B5CF6;background:rgba(139,92,246,.18);color:#fff;}',
            '.iris-fl-kinds{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;}',
            '.iris-fl-kindcard{text-align:left;border:1px solid rgba(255,255,255,.12);border-radius:8px;background:transparent;color:#e8e8ee;padding:8px 10px;cursor:pointer;}',
            '.iris-fl-kindcard small{display:block;color:#9a9aa5;font-size:.7rem;}',
            '.iris-fl-kindcard[aria-checked="true"]{border-color:#8B5CF6;background:rgba(139,92,246,.14);}',
            '@media (max-width: 991px){.iris-fl-set-wrap{display:block;}.iris-fl-set-wrap>div{margin-bottom:14px;}}'
        ].join('\n');
        document.head.appendChild(st);
    };
    F.kindBadge = function (kind) {
        var k = Object.prototype.hasOwnProperty.call(KIND_LABEL, kind) ? kind : 'status';
        return '<span class="iris-fl-kind iris-fl-kind-' + k + '">' + KIND_LABEL[k] + '</span>';
    };

    /* A Bootstrap modal appended to <body> (jQuery is loaded by the time anyone opens one). */
    F.modal = function (o) {
        var $ = window.jQuery;
        var $m = $('<div class="modal fade" tabindex="-1" role="dialog" aria-modal="true"><div class="modal-dialog ' +
            (o.size || '') + '" role="document"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title">' +
            o.title + '</h5>' + (o.subtitle ? '<div class="iris-fl-muted">' + o.subtitle + '</div>' : '') +
            '</div><button type="button" class="close" data-dismiss="modal" aria-label="Close"><span aria-hidden="true">&times;</span></button></div>' +
            '<div class="modal-body">' + o.body + '<div class="iris-fl-err" data-fl="err" role="alert"></div></div>' +
            (o.footer ? '<div class="modal-footer">' + o.footer + '</div>' : '') + '</div></div></div>');
        $('body').append($m);
        $m.on('hidden.bs.modal', function () { $m.remove(); });
        $m.modal({backdrop: 'static'});
        return $m;
    };

    /* ------------------------------------------------------------ the asset's history */
    F.history = function (caseId, assetId, assetName) {
        F.css();
        var $m = F.modal({title: 'Flag history', subtitle: 'Asset ' + F.esc(assetName || ''), size: 'modal-lg',
            body: '<div class="iris-fl-muted mb-2">Every flag set, updated or removed, newest first (UTC) ' +
                IrisHelp.icon('flags.history') + '</div><div data-fl="h">Loading…</div>',
            footer: '<button type="button" class="btn btn-outline-secondary" data-dismiss="modal">Close</button>'});
        F.api('/api/v2/cases/' + F.id(caseId) + '/assets/' + F.id(assetId) + '/flag-history').then(function (res) {
            var $h = $m.find('[data-fl="h"]');
            if (!res.ok || !Array.isArray(res.j)) { $h.text(F.errText(res)); return; }
            if (!res.j.length) { $h.text('No flag change recorded.'); return; }
            var verb = {set: 'Set', updated: 'Updated', cleared: 'Removed'};
            $h.html('<table class="table table-sm"><thead><tr><th>When (UTC)</th><th>Who</th><th>Flag</th><th>Change</th><th>Reason / decision</th></tr></thead><tbody>' +
                res.j.map(function (c) {
                    return '<tr><td class="text-nowrap">' + F.esc(String(c.changed_at || '').replace('T', ' ').slice(0, 16)) + '</td><td>' +
                        F.esc(c.changed_by_name || '—') + '</td><td>' + F.esc(c.flag_name) + '</td><td>' + (verb[c.action] || F.esc(c.action)) +
                        '</td><td>' + F.esc(c.reason || '') + (c.decision_ref ? ' <span class="iris-fl-chip-ref">' + F.esc(c.decision_ref) + '</span>' : '') +
                        '</td></tr>';
                }).join('') + '</tbody></table>');
        });
    };

    /* ------------------------------------------------------------ the Flags row of a case asset
       renderAssetFlags(host, {caseId, asset: {asset_id, asset_name, flags, flag_changes}, canWrite, onChange(flags, changed)})
       The host is rebuilt with the asset pane, so the row's own state (menu open, a flag waiting for its
       reason / decision) lives here per asset and survives the re-render. */
    var ui = {};
    F.renderAssetFlags = function (host, o) {
        if (!host) { return; }
        F.css();
        var a = o.asset, aid = F.id(a.asset_id);
        var st = ui[aid] || (ui[aid] = {open: false, pending: null, err: '', decisions: null});
        var set = Array.isArray(a.flags) ? a.flags : [];
        F.catalogue().then(function (flags) {
            draw(host, o, st, set, flags);
        }).catch(function (e) {
            host.innerHTML = '<div class="iris-fl-row"><span class="iris-fl-lbl">Flags</span>' +
                set.map(function (f) { return F.chip(f); }).join('') +
                '<span class="iris-fl-err">' + F.esc(e.message) + '</span></div>';
        });
    };

    function draw(host, o, st, set, flags) {
        /* what the delegated remove handler (document level) needs, kept on the host itself */
        host.setAttribute('data-iris-flags-host', '1');
        host.__irisFlags = {o: o, st: st, set: set, flags: flags};
        var a = o.asset, setIds = set.map(function (f) { return f.flag_id; });
        var free = flags.filter(function (f) { return setIds.indexOf(f.id) < 0; });
        var h = '<div class="iris-fl-row"><span class="iris-fl-lbl">Flags</span>' + IrisHelp.icon('flags.asset') +
            (set.length ? set.map(function (f) { return F.chip(f, {remove: o.canWrite}); }).join('')
                : '<span class="iris-fl-muted">None</span>') +
            (o.canWrite && free.length ? '<button type="button" class="iris-fl-add" data-fl="add" aria-expanded="' + (st.open ? 'true' : 'false') +
                '">+ Flag</button>' : '') +
            (o.canWrite && !flags.length ? '<span class="iris-fl-muted">No asset flag is configured. An administrator adds them in Settings &rarr; Asset flags.</span>' : '') +
            (a.flag_changes ? '<button type="button" class="iris-fl-changes" data-fl="hist">' + Number(a.flag_changes) +
                ' change' + (Number(a.flag_changes) === 1 ? '' : 's') + ' &rsaquo;</button>' : '') + '</div>';
        if (st.open && !st.pending) {
            h += '<div class="iris-fl-menu" role="menu" aria-label="Set a flag">' + free.map(function (f) {
                return '<button type="button" class="iris-fl-opt" role="menuitem" data-fl="pick" data-flag-id="' + F.id(f.id) + '">' +
                    '<span style="color:' + F.color(f.color) + ';margin-top:2px;">' + F.icon(f.icon, 14) + '</span><span><b>' + F.esc(f.name) +
                    '</b>' + F.kindBadge(f.kind) +
                    (f.requires_reason ? ' <span title="Requires a reason" style="color:#f4c430;">' + F.svg(MSG_ICON, 11) + '</span>' : '') +
                    (f.requires_decision ? ' <span title="Requires a decision" style="color:#f4c430;">' + F.svg(GAVEL, 11) + '</span>' : '') +
                    (f.description ? '<small>' + F.esc(f.description) + '</small>' : '') + '</span></button>';
            }).join('') + '</div>';
        }
        if (st.pending) {
            var f = flags.filter(function (x) { return x.id === st.pending.flagId; })[0];
            if (f) {
                var clearing = st.pending.mode === 'clear';
                h += '<div class="iris-fl-form" data-fl="form">' +
                    '<div class="mb-1">' + F.chip(f) + ' <span class="iris-fl-muted">' +
                    (clearing ? 'Why is the flag removed?' : (f.kind === 'exception' ? 'Why is this asset an exception?' : 'Why is the flag set?')) +
                    '</span></div>' +
                    (f.requires_reason || clearing ? '<label class="sr-only" for="iris-fl-reason">Reason</label><textarea id="iris-fl-reason" class="form-control form-control-sm" data-fl="reason" placeholder="Reason' +
                        (f.requires_reason ? ' (required)' : ' (optional)') + '">' + F.esc(st.pending.reason || '') + '</textarea>' : '') +
                    (f.requires_decision && !clearing ? '<div class="mt-2"><label for="iris-fl-decision" class="iris-fl-muted mb-1">Decision</label>' + IrisHelp.icon('flags.requires_decision') +
                        '<select id="iris-fl-decision" class="form-control form-control-sm" data-fl="decision">' + decisionOptions(st) + '</select>' +
                        (st.decisions && !st.decisions.length ? '<div class="iris-fl-muted mt-1">No approved decision of a war room this case is attached to (and you belong to) applies to this asset. Record one on the room\'s Decisions tab.</div>' : '') +
                        '</div>' : '') +
                    (st.err ? '<div class="iris-fl-err" role="alert">' + F.esc(st.err) + '</div>' : '') +
                    '<div class="mt-2 d-flex" style="gap:6px;"><button type="button" class="btn btn-sm btn-primary" data-fl="confirm">' +
                    (clearing ? 'Remove flag' : 'Set flag') + '</button><button type="button" class="btn btn-sm btn-outline-secondary" data-fl="cancel">Cancel</button></div></div>';
            }
        } else if (st.err) {
            h += '<div class="iris-fl-err" role="alert">' + F.esc(st.err) + '</div>';
        }
        host.innerHTML = h;
        host.onclick = function (e) { click(e, host, o, st, set, flags); };
        host.oninput = function (e) {
            if (e.target.getAttribute('data-fl') === 'reason' && st.pending) { st.pending.reason = e.target.value; }
        };
        host.onchange = function (e) {
            if (e.target.getAttribute('data-fl') === 'decision' && st.pending) { st.pending.decisionId = e.target.value; }
        };
        if (st.pending && st.pending.mode === 'set') {
            var fp = flags.filter(function (x) { return x.id === st.pending.flagId; })[0];
            if (fp && fp.requires_decision && st.decisions === null && !st.loadingDecisions) {
                loadDecisions(host, o, st, set, flags);
            }
        }
    }

    function decisionOptions(st) {
        if (st.decisions === null) { return '<option value="">Loading…</option>'; }
        return '<option value="">Choose an approved decision…</option>' + st.decisions.map(function (d) {
            return '<option value="' + F.id(d.decision_id) + '"' + (String(st.pending && st.pending.decisionId) === String(d.decision_id) ? ' selected' : '') +
                '>' + F.esc(d.ref + ' - ' + d.title + ' (' + (d.room_name || 'war room') + ', ' +
                    (d.applies === 'room' ? 'whole room' : d.applies === 'case' ? 'this case' : 'this asset') + ')') + '</option>';
        }).join('');
    }

    /* st.decisions: null = not looked yet (the select says Loading), [] = looked, none applies */
    function loadDecisions(host, o, st, set, flags) {
        st.loadingDecisions = true;
        F.api('/api/v2/cases/' + F.id(o.caseId) + '/assets/' + F.id(o.asset.asset_id) + '/flag-decisions').then(function (res) {
            st.loadingDecisions = false;
            st.decisions = res.ok && Array.isArray(res.j) ? res.j : [];
            if (!res.ok) { st.err = F.errText(res); }
            draw(host, o, st, set, flags);
        });
    }

    function click(e, host, o, st, set, flags) {
        var t = e.target.closest('[data-fl]');
        if (!t) { return; }
        var act = t.getAttribute('data-fl'), aid = F.id(o.asset.asset_id), cid = F.id(o.caseId);
        if (act === 'hist') { F.history(cid, aid, o.asset.asset_name); return; }
        if (act === 'add') { st.open = !st.open; st.err = ''; draw(host, o, st, set, flags); return; }
        if (act === 'cancel') { st.pending = null; st.err = ''; draw(host, o, st, set, flags); return; }
        var flag;
        if (act === 'pick') {
            flag = flags.filter(function (f) { return String(f.id) === String(t.getAttribute('data-flag-id')); })[0];
            if (!flag) { return; }
            st.open = false;
            st.err = '';
            if (flag.requires_reason || flag.requires_decision) {
                st.pending = {mode: 'set', flagId: flag.id, reason: '', decisionId: ''};
                st.decisions = null;
                draw(host, o, st, set, flags);
                return;
            }
            send(host, o, st, set, flags, 'PUT', flag, {});
            return;
        }
        if (act === 'confirm' && st.pending) {
            flag = flags.filter(function (f) { return f.id === st.pending.flagId; })[0];
            var body = {reason: st.pending.reason || ''};
            if (st.pending.mode === 'set' && flag.requires_decision) { body.decision_id = st.pending.decisionId || null; }
            if (flag.requires_reason && !$trim(body.reason)) { st.err = '"' + flag.name + '" needs a reason.'; draw(host, o, st, set, flags); return; }
            if (st.pending.mode === 'set' && flag.requires_decision && !body.decision_id) {
                st.err = '"' + flag.name + '" requires an approved war-room decision.'; draw(host, o, st, set, flags); return;
            }
            send(host, o, st, set, flags, st.pending.mode === 'clear' ? 'DELETE' : 'PUT', flag, body);
        }
    }

    /* the remove buttons carry no data-fl: delegate them here */
    document.addEventListener('click', function (e) {
        var x = e.target.closest('.iris-fl-x');
        if (!x) { return; }
        var host = x.closest('[data-iris-flags-host]');
        if (!host || !host.__irisFlags) { return; }
        var c = host.__irisFlags;
        var flag = c.flags.filter(function (f) { return String(f.id) === String(x.getAttribute('data-flag-id')); })[0];
        if (!flag) { return; }
        c.st.open = false;
        c.st.err = '';
        if (flag.requires_reason) {
            c.st.pending = {mode: 'clear', flagId: flag.id, reason: ''};
            draw(host, c.o, c.st, c.set, c.flags);
            return;
        }
        send(host, c.o, c.st, c.set, c.flags, 'DELETE', flag, {});
    });

    function $trim(s) { return String(s == null ? '' : s).replace(/^\s+|\s+$/g, ''); }

    function send(host, o, st, set, flags, method, flag, body) {
        var url = '/api/v2/cases/' + F.id(o.caseId) + '/assets/' + F.id(o.asset.asset_id) + '/flags/' + F.id(flag.id);
        F.api(url, method, body).then(function (res) {
            if (!res.ok) { st.err = F.errText(res); draw(host, o, st, set, flags); return; }
            st.pending = null;
            st.err = '';
            var changed = method === 'DELETE' || (res.j && res.j.action);
            if (o.onChange) { o.onChange(res.j.flags || [], changed ? 1 : 0); }
        });
    }

    /* ------------------------------------------------------------ Settings -> Asset flags */
    F.mountSettings = function (el) {
        F.css();
        var state = {flags: [], sel: null, vocab: null};
        var $ = window.jQuery;
        el.innerHTML =
            '<div class="card mb-3"><div class="card-body d-flex align-items-start justify-content-between flex-wrap" style="gap:10px;">' +
            '<div><h1 class="card-title mb-0" style="font-size:1.15rem;">' + F.svg(F.ICONS.flag, 16) + ' Asset flags ' + IrisHelp.icon('flags.catalogue') + '</h1>' +
            '<div class="iris-fl-muted">Status facts set on case assets. Each change is recorded in the asset\'s history and the case log.</div></div>' +
            '<div class="d-flex flex-wrap" style="gap:6px;">' +
            '<button type="button" class="btn btn-sm btn-outline-secondary" data-fs="refresh">Refresh</button>' +
            '<div class="dropdown"><button type="button" class="btn btn-sm btn-outline-secondary dropdown-toggle" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" data-fs="presetbtn">Load preset</button>' +
            '<div class="dropdown-menu dropdown-menu-right" data-fs="presets" style="min-width:320px;"></div></div>' + IrisHelp.icon('flags.preset') +
            '<button type="button" class="btn btn-sm btn-primary" data-fs="new">+ Add flag</button></div></div>' +
            '<div class="px-3 pb-2 iris-fl-muted" data-fs="msg" role="status"></div></div>' +
            '<div class="iris-fl-set-wrap"><div class="iris-fl-panel" style="flex:1 1 55%;min-width:0;">' +
            '<div class="iris-fl-panel-head"><span>Flags <span data-fs="count"></span></span><span>Drag to reorder</span></div>' +
            '<ul class="iris-fl-list" data-fs="list" aria-label="Asset flags"><li class="p-3 iris-fl-muted">Loading…</li></ul></div>' +
            '<div class="iris-fl-panel" style="flex:1 1 45%;min-width:0;" data-fs="detail"></div></div>';
        var $el = $(el);
        function msg(t) { $el.find('[data-fs="msg"]').text(t || ''); }
        function load(keepSel) {
            return F.api(API + '?counts=true').then(function (res) {
                if (!res.ok || !Array.isArray(res.j)) { $el.find('[data-fs="list"]').html('<li class="p-3 iris-fl-err">' + F.esc(F.errText(res)) + '</li>'); return; }
                state.flags = res.j;
                cat = Promise.resolve(res.j.map(function (f) { return f; }));
                if (!keepSel || !state.flags.some(function (f) { return f.id === state.sel; })) {
                    state.sel = state.flags.length ? state.flags[0].id : null;
                }
                drawList();
                drawDetail();
            });
        }
        function drawList() {
            $el.find('[data-fs="count"]').text(state.flags.length);
            var $l = $el.find('[data-fs="list"]');
            if (!state.flags.length) {
                $l.html('<li class="p-3 iris-fl-muted">No flag yet. Add one, or load a preset.</li>');
                return;
            }
            $l.html(state.flags.map(function (f) {
                var c = F.color(f.color);
                return '<li class="iris-fl-li' + (f.id === state.sel ? ' active' : '') + '" draggable="true" data-id="' + F.id(f.id) + '" tabindex="0" role="button" aria-pressed="' + (f.id === state.sel) + '">' +
                    '<span class="iris-fl-handle" aria-hidden="true">&#10303;</span>' +
                    '<span class="iris-fl-dot" style="color:' + c + ';background:' + rgba(c, 0.14) + ';">' + F.icon(f.icon, 14) + '</span>' +
                    '<span class="iris-fl-li-main"><b>' + F.esc(f.name) + '</b><div>' + F.esc(f.description || '') + '</div></span>' +
                    F.kindBadge(f.kind) +
                    (f.requires_reason ? '<span title="Requires a reason" style="color:#f4c430;">' + F.svg(MSG_ICON, 12) + '<span class="sr-only">Requires a reason</span></span>' : '') +
                    (f.requires_decision ? '<span title="Requires a decision" style="color:#f4c430;">' + F.svg(GAVEL, 12) + '<span class="sr-only">Requires a decision</span></span>' : '') +
                    '<span class="iris-fl-use">' + Number(f.in_use_count || 0) + ' asset' + (Number(f.in_use_count) === 1 ? '' : 's') + '</span></li>';
            }).join(''));
        }
        function drawDetail() {
            var $d = $el.find('[data-fs="detail"]');
            var f = state.flags.filter(function (x) { return x.id === state.sel; })[0];
            if (!f) { $d.html('<div class="iris-fl-panel-head"><span>Details</span></div><div class="p-3 iris-fl-muted">Select a flag.</div>'); return; }
            var idx = state.flags.indexOf(f);
            $d.html('<div class="iris-fl-panel-head"><span>Details <span style="text-transform:none;letter-spacing:0;">' + F.esc(f.name) + '</span></span>' +
                '<span class="d-flex" style="gap:6px;">' +
                '<button type="button" class="btn btn-sm btn-outline-secondary" data-fs="up"' + (idx === 0 ? ' disabled' : '') + ' aria-label="Move up">&uarr;</button>' +
                '<button type="button" class="btn btn-sm btn-outline-secondary" data-fs="down"' + (idx === state.flags.length - 1 ? ' disabled' : '') + ' aria-label="Move down">&darr;</button>' +
                '<button type="button" class="btn btn-sm btn-outline-secondary" data-fs="edit">Edit</button>' +
                '<button type="button" class="btn btn-sm btn-outline-danger" data-fs="del">Delete</button></span></div>' +
                '<div class="iris-fl-kv">' +
                '<div><div class="k">Flag</div><div class="v">' + F.chip(f) + '</div></div>' +
                '<div><div class="k">Kind ' + IrisHelp.icon('flags.kind') + '</div><div class="v">' + F.esc(KIND_LABEL[f.kind] || f.kind) + '</div></div>' +
                '<div style="grid-column:1 / -1;"><div class="k">Description</div><div class="v">' + (f.description ? F.esc(f.description) : '<span class="iris-fl-muted">—</span>') + '</div></div>' +
                '<div><div class="k">Colour</div><div class="v"><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:' + F.color(f.color) + ';"></span> ' + F.esc(f.color) + '</div></div>' +
                '<div><div class="k">Icon</div><div class="v"><code>' + F.esc(f.icon) + '</code></div></div>' +
                '<div><div class="k">Requires a reason ' + IrisHelp.icon('flags.requires_reason') + '</div><div class="v">' + (f.requires_reason ? 'Yes' : 'No') + '</div></div>' +
                '<div><div class="k">Requires a decision ' + IrisHelp.icon('flags.requires_decision') + '</div><div class="v">' + (f.requires_decision ? 'Yes' : 'No') + '</div></div>' +
                '<div><div class="k">In use</div><div class="v">' + Number(f.in_use_count || 0) + ' asset' + (Number(f.in_use_count) === 1 ? '' : 's') + '</div></div>' +
                '<div><div class="k">Flag ID</div><div class="v">' + F.id(f.id) + '</div></div></div>' +
                '<div class="iris-fl-preview" aria-label="Preview of every flag"><div class="iris-fl-lbl" style="width:100%;">Preview</div>' +
                state.flags.map(function (x) { return F.chip(x); }).join('') + '</div>');
        }
        function reorder(ids) {
            F.api(API + '/reorder', 'POST', {ids: ids}).then(function (res) {
                if (!res.ok) { msg(F.errText(res)); }
                load(true);
            });
        }
        $el.on('click', '.iris-fl-li', function () { state.sel = Number($(this).attr('data-id')); drawList(); drawDetail(); });
        $el.on('keydown', '.iris-fl-li', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $(this).trigger('click'); } });
        var dragId = null;
        $el.on('dragstart', '.iris-fl-li', function (e) { dragId = Number($(this).attr('data-id')); $(this).addClass('dragging'); e.originalEvent.dataTransfer.effectAllowed = 'move'; });
        $el.on('dragend', '.iris-fl-li', function () { $(this).removeClass('dragging'); $el.find('.drop-before').removeClass('drop-before'); });
        $el.on('dragover', '.iris-fl-li', function (e) { e.preventDefault(); $el.find('.drop-before').removeClass('drop-before'); $(this).addClass('drop-before'); });
        $el.on('drop', '.iris-fl-li', function (e) {
            e.preventDefault();
            var target = Number($(this).attr('data-id'));
            if (dragId === null || dragId === target) { return; }
            var ids = state.flags.map(function (f) { return f.id; }).filter(function (i) { return i !== dragId; });
            ids.splice(ids.indexOf(target), 0, dragId);
            dragId = null;
            reorder(ids);
        });
        $el.on('click', '[data-fs="up"],[data-fs="down"]', function () {
            var ids = state.flags.map(function (f) { return f.id; });
            var i = ids.indexOf(state.sel), j2 = $(this).attr('data-fs') === 'up' ? i - 1 : i + 1;
            if (i < 0 || j2 < 0 || j2 >= ids.length) { return; }
            ids[i] = ids[j2];
            ids[j2] = state.sel;
            reorder(ids);
        });
        $el.on('click', '[data-fs="refresh"]', function () { msg(''); load(true); });
        $el.on('click', '[data-fs="new"]', function () { openForm(null); });
        $el.on('click', '[data-fs="edit"]', function () { openForm(state.flags.filter(function (x) { return x.id === state.sel; })[0]); });
        $el.on('click', '[data-fs="del"]', function () {
            var f = state.flags.filter(function (x) { return x.id === state.sel; })[0];
            if (!f) { return; }
            var n = Number(f.in_use_count || 0);
            if (!window.confirm('Delete the flag "' + f.name + '"?' + (n ? '\n\nIt is removed from ' + n + ' asset' + (n === 1 ? '' : 's') +
                    '; their history keeps it.' : '') + '\n\nThis cannot be undone.')) { return; }
            F.api(API + '/' + F.id(f.id), 'DELETE').then(function (res) {
                if (!res.ok) { msg(F.errText(res)); return; }
                msg('Flag "' + f.name + '" deleted.');
                load(false);
            });
        });
        $el.on('click', '[data-fs="preset"]', function (e) {
            e.preventDefault();
            var pid = $(this).attr('data-preset'), label = $(this).attr('data-label');
            F.api(API + '/presets/' + encodeURIComponent(pid), 'POST', {}).then(function (res) {
                if (!res.ok) { msg(F.errText(res)); return; }
                var added = res.j.added || [];
                msg(added.length ? 'Preset "' + label + '" loaded: added ' + added.join(', ') + '.'
                    : 'Preset "' + label + '": every flag it holds already exists - nothing added.');
                load(true);
            });
        });
        function openForm(f) {
            var v = state.vocab;
            var cur = {name: f ? f.name : '', description: f ? (f.description || '') : '', color: f ? f.color : 'slate',
                       icon: f ? f.icon : 'flag', kind: f ? f.kind : 'status', requires_reason: f ? f.requires_reason : false,
                       requires_decision: f ? f.requires_decision : false};
            var body =
                '<div class="form-group"><label for="fl-name">Name <span style="color:#ff8095;">*</span></label>' +
                '<input type="text" class="form-control" id="fl-name" maxlength="' + Number(v.name_max || 64) + '" value="' + F.esc(cur.name) + '" placeholder="Isolated"></div>' +
                '<div class="form-group"><label for="fl-desc">Description</label><textarea class="form-control" id="fl-desc" rows="2" maxlength="1000" placeholder="Shown in the flag menus">' + F.esc(cur.description) + '</textarea></div>' +
                '<div class="form-group"><div class="mb-1" id="fl-colour-l">Colour</div><div class="iris-fl-swatches" role="radiogroup" aria-labelledby="fl-colour-l">' +
                v.colors.map(function (c) {
                    return '<button type="button" class="iris-fl-swatch" role="radio" aria-checked="' + (c === cur.color) + '" aria-label="' + F.esc(c) + '" data-color="' + F.esc(c) + '" style="background:' + F.color(c) + ';"></button>';
                }).join('') + '</div></div>' +
                '<div class="form-group"><div class="mb-1" id="fl-icon-l">Icon</div><div class="iris-fl-icons" role="radiogroup" aria-labelledby="fl-icon-l">' +
                v.icons.map(function (i) {
                    return '<button type="button" class="iris-fl-iconbtn" role="radio" aria-checked="' + (i === cur.icon) + '" aria-label="' + F.esc(i) + '" data-icon="' + F.esc(i) + '">' + F.icon(i, 15) + '</button>';
                }).join('') + '</div></div>' +
                '<div class="form-group"><div class="mb-1" id="fl-kind-l">Kind ' + IrisHelp.icon('flags.kind') + '</div><div class="iris-fl-kinds" role="radiogroup" aria-labelledby="fl-kind-l">' +
                v.kinds.map(function (k) {
                    return '<button type="button" class="iris-fl-kindcard" role="radio" aria-checked="' + (k.value === cur.kind) + '" data-kind="' + F.esc(k.value) + '"><b>' + F.esc(k.label) + '</b><small>' + F.esc(k.description) + '</small></button>';
                }).join('') + '</div></div>' +
                '<div class="custom-control custom-switch mb-2"><input type="checkbox" class="custom-control-input" id="fl-reason"' + (cur.requires_reason ? ' checked' : '') + '>' +
                '<label class="custom-control-label" for="fl-reason"><b>Requires a reason</b> <span class="iris-fl-muted">- setting or removing this flag asks for a written reason.</span></label>' + IrisHelp.icon('flags.requires_reason') + '</div>' +
                '<div class="custom-control custom-switch mb-2"><input type="checkbox" class="custom-control-input" id="fl-decision"' + (cur.requires_decision ? ' checked' : '') + '>' +
                '<label class="custom-control-label" for="fl-decision"><b>Requires a decision</b> <span class="iris-fl-muted">- setting this flag must cite an approved war-room decision (e.g. risk acceptance).</span></label>' + IrisHelp.icon('flags.requires_decision') + '</div>' +
                '<div class="mt-2 iris-fl-muted">Preview <span data-fl-preview></span></div>';
            var $m = F.modal({title: f ? 'Edit flag' : 'Add flag', subtitle: f ? '' : 'Create a new asset flag. It is appended to the end of the list.',
                body: body, footer: '<button type="button" class="btn btn-outline-secondary" data-dismiss="modal">Cancel</button>' +
                    '<button type="button" class="btn btn-primary" data-fs="save">' + (f ? 'Save' : 'Create') + '</button>'});
            function preview() {
                $m.find('[data-fl-preview]').html(F.chip({name: $.trim($m.find('#fl-name').val()) || 'Flag', color: cur.color, icon: cur.icon}));
            }
            preview();
            $m.on('input', '#fl-name', preview);
            $m.on('click', '.iris-fl-swatch', function () { cur.color = $(this).attr('data-color'); $m.find('.iris-fl-swatch').attr('aria-checked', 'false'); $(this).attr('aria-checked', 'true'); preview(); });
            $m.on('click', '.iris-fl-iconbtn', function () { cur.icon = $(this).attr('data-icon'); $m.find('.iris-fl-iconbtn').attr('aria-checked', 'false'); $(this).attr('aria-checked', 'true'); preview(); });
            $m.on('click', '.iris-fl-kindcard', function () { cur.kind = $(this).attr('data-kind'); $m.find('.iris-fl-kindcard').attr('aria-checked', 'false'); $(this).attr('aria-checked', 'true'); });
            $m.on('click', '[data-fs="save"]', function () {
                var payload = {name: $.trim($m.find('#fl-name').val()), description: $m.find('#fl-desc').val(), color: cur.color, icon: cur.icon,
                               kind: cur.kind, requires_reason: $m.find('#fl-reason').is(':checked'), requires_decision: $m.find('#fl-decision').is(':checked')};
                if (!payload.name) { $m.find('[data-fl="err"]').text('Name is required'); return; }
                var $b = $(this).prop('disabled', true);
                F.api(f ? API + '/' + F.id(f.id) : API, f ? 'PUT' : 'POST', payload).then(function (res) {
                    $b.prop('disabled', false);
                    if (!res.ok) { $m.find('[data-fl="err"]').text(F.errText(res)); return; }
                    $m.modal('hide');
                    state.sel = res.j.id;
                    msg((f ? 'Saved' : 'Created') + ' "' + res.j.name + '".');
                    load(true);
                });
            });
        }
        F.api(API + '/vocab').then(function (res) {
            if (!res.ok) { msg(F.errText(res)); return; }
            state.vocab = res.j;
            $el.find('[data-fs="presets"]').html((res.j.presets || []).map(function (p) {
                return '<a href="#" class="dropdown-item" data-fs="preset" data-preset="' + F.esc(p.id) + '" data-label="' + F.esc(p.label) +
                    '" style="white-space:normal;"><b>' + F.esc(p.label) + '</b><div class="iris-fl-muted">' + F.esc(p.summary) + '</div></a>';
            }).join(''));
            load(false);
        });
    };

    window.IrisFlags = F;
})();

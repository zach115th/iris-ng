/* War Rooms list page (iris-ng v2, Phase 6; v3-shaped card grid).
 * Import-free by rule (Vite copies ui/public verbatim; rolldown drops
 * inline-handler-only functions from ui/src). All data from /api/v2.
 * The API returns EVERY status and archived rooms too; the chips, the
 * category sidebar and the search filter client-side.
 *
 * iris-ng 2026-11-10: categories (one shared list; a room's leads file it
 * by dragging its card onto a category or through its Move menu) and the
 * archive (a flag beside the state: an archived room keeps its state and
 * waits in the Archived section until a lead restores it). */

var IRIS_WR = {
    /* cid reaches innerHTML (discovery "Open room" link) and navigation
       URLs — it must be a case id, so anything non-numeric falls back
       to '1' instead of reaching a sink. */
    _cid: (function () {
        var v = new URLSearchParams(window.location.search).get('cid');
        return /^\d+$/.test(v || '') ? v : '1';
    })(),
    _rooms: [],
    _chip: '',
    _q: '',
    _cats: [],
    _catFilter: 'all',
    _viewer: null,
    _isAdmin: false,
    _archOpen: false,
    _drag: null,
    _seq: 0
};

var IRIS_WR_STORE_CAT = 'irisWarRoomCategory';
var IRIS_WR_STORE_ARCH = 'irisWarRoomArchivedOpen';

var IRIS_WR_ICONS = {
    all: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/></svg>',
    none: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>',
    folder: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>',
    move: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 9V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H20a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-1"/><path d="M2 13h10"/><path d="m9 16 3-3-3-3"/></svg>',
    archive: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/></svg>',
    restore: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h2"/><path d="M20 8v11a2 2 0 0 1-2 2h-2"/><path d="m9 15 3-3 3 3"/><path d="M12 12v9"/></svg>',
    pencil: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/></svg>',
    trash: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></svg>'
};

function iris_wr_esc(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function iris_wr_csrf() {
    var el = document.getElementById('csrf_token');
    return el ? el.value : '';
}

/* A number the server assigned, re-derived (never the text read back). */
function iris_wr_int(v) {
    var n = parseInt(v, 10);
    return isFinite(n) && n > 0 ? n : null;
}

function iris_wr_store_get(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
}

function iris_wr_store_set(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* private window: per page only */ }
}

function iris_wr_toast(ok, msg) {
    if (ok && typeof notify_success === 'function') { notify_success(msg); return; }
    if (!ok && typeof notify_error === 'function') { notify_error(msg); return; }
    if (!ok) { window.alert(msg); }
}

function iris_wr_api(method, url, body) {
    var opts = {method: method, headers: {'Accept': 'application/json'}};
    if (body) {
        body.csrf_token = iris_wr_csrf();
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
            return {ok: r.ok, status: r.status, j: j || {}};
        });
    });
}

function iris_wr_date(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    return (d.getMonth() + 1) + '/' + d.getDate() + '/' + d.getFullYear();
}

function iris_wr_created(iso) {
    return iso ? 'Created ' + iris_wr_date(iso) : '';
}

/* ------------------------------------------------------------- categories */

function iris_wr_cat_by_id(id) {
    for (var i = 0; i < IRIS_WR._cats.length; i++) {
        if (IRIS_WR._cats[i].id === id) return IRIS_WR._cats[i];
    }
    return null;
}

/* The room's category, or null when it has none or names one that is gone. */
function iris_wr_room_cat(r) {
    return r.category_id != null && iris_wr_cat_by_id(r.category_id) ? r.category_id : null;
}

function iris_wr_in_cat(r) {
    var f = IRIS_WR._catFilter;
    if (f === 'all') return true;
    if (f === 'none') return iris_wr_room_cat(r) === null;
    return iris_wr_room_cat(r) === f;
}

function iris_wr_set_filter(value) {
    var v = value;
    if (v !== 'all' && v !== 'none') {
        v = iris_wr_int(v);
        if (v === null || !iris_wr_cat_by_id(v)) v = 'all';
    }
    IRIS_WR._catFilter = v;
    iris_wr_store_set(IRIS_WR_STORE_CAT, String(v));
}

function iris_wr_can_delete_cat(c) {
    return IRIS_WR._isAdmin || (IRIS_WR._viewer !== null && c.created_by === IRIS_WR._viewer);
}

function iris_wr_render_cats(live) {
    var counts = {all: live.length, none: 0}, byId = {};
    live.forEach(function (r) {
        var c = iris_wr_room_cat(r);
        if (c === null) counts.none += 1; else byId[c] = (byId[c] || 0) + 1;
    });
    var f = IRIS_WR._catFilter;
    function item(key, icon, name, count, tools) {
        return '<div class="iris-wr-cat' + (String(f) === String(key) ? ' active' : '') + '" role="listitem" ' +
            'data-cat="' + iris_wr_esc(key) + '">' +
            '<button type="button" class="iris-wr-cat-pick" aria-pressed="' + (String(f) === String(key)) + '">' +
            icon + '<span class="iris-wr-cat-name">' + iris_wr_esc(name) + '</span>' +
            '<span class="iris-wr-cat-count">' + count + '</span></button>' + (tools || '') + '</div>';
    }
    var html = item('all', IRIS_WR_ICONS.all, 'All', counts.all) +
        item('none', IRIS_WR_ICONS.none, 'Uncategorised', counts.none);
    IRIS_WR._cats.forEach(function (c) {
        var id = iris_wr_int(c.id);
        if (id === null) return;
        var tools = '<span class="iris-wr-cat-tools">' +
            '<button type="button" class="iris-wr-iconbtn iris-wr-cat-rename" title="Rename" aria-label="Rename ' +
            iris_wr_esc(c.name) + '">' + IRIS_WR_ICONS.pencil + '</button>' +
            (iris_wr_can_delete_cat(c)
                ? '<button type="button" class="iris-wr-iconbtn iris-wr-cat-delete" title="Delete" aria-label="Delete ' +
                  iris_wr_esc(c.name) + '">' + IRIS_WR_ICONS.trash + '</button>' : '') +
            '</span>';
        html += item(id, IRIS_WR_ICONS.folder, c.name, byId[id] || 0, tools);
    });
    document.getElementById('iris-wr-cat-list').innerHTML = html;
}

function iris_wr_load_cats() {
    return iris_wr_api('GET', '/api/v2/war-rooms/categories').then(function (res) {
        if (!res.ok) return;
        IRIS_WR._cats = (res.j.categories || []).filter(function (c) { return iris_wr_int(c.id) !== null; });
        IRIS_WR._viewer = iris_wr_int(res.j.viewer_id);
        IRIS_WR._isAdmin = res.j.is_admin === true;
    });
}

function iris_wr_new_cat_show(on) {
    var row = document.getElementById('iris-wr-cat-newrow');
    var input = document.getElementById('iris-wr-cat-newname');
    row.style.display = on ? '' : 'none';
    input.value = '';
    if (on) input.focus();
}

function iris_wr_new_cat_save() {
    var input = document.getElementById('iris-wr-cat-newname');
    var name = input.value.trim();
    if (!name) { iris_wr_new_cat_show(false); return; }
    input.disabled = true;
    iris_wr_api('POST', '/api/v2/war-rooms/categories', {name: name}).then(function (res) {
        input.disabled = false;
        if (!res.ok) { iris_wr_toast(false, res.j.message || 'Could not create the category'); input.focus(); return; }
        iris_wr_new_cat_show(false);
        iris_wr_toast(true, 'Category "' + res.j.name + '" created');
        iris_wr_load_cats().then(iris_wr_render);
    });
}

function iris_wr_rename_cat_start(catEl) {
    var id = iris_wr_int(catEl.getAttribute('data-cat'));
    var c = id !== null ? iris_wr_cat_by_id(id) : null;
    if (!c) return;
    catEl.innerHTML = '<label class="sr-only" for="iris-wr-cat-rename-input">Category name</label>' +
        '<input type="text" class="form-control" id="iris-wr-cat-rename-input" maxlength="64">';
    var input = catEl.querySelector('input');
    input.value = c.name;
    input.setAttribute('data-cat-id', String(id));
    input.focus();
    input.select();
}

function iris_wr_rename_cat_save(input) {
    var id = iris_wr_int(input.getAttribute('data-cat-id'));
    var c = id !== null ? iris_wr_cat_by_id(id) : null;
    var name = input.value.trim();
    if (!c || !name || name === c.name) { iris_wr_render(); return; }
    input.disabled = true;
    iris_wr_api('PUT', '/api/v2/war-rooms/categories/' + id, {name: name}).then(function (res) {
        if (!res.ok) { iris_wr_toast(false, res.j.message || 'Could not rename the category'); iris_wr_render(); return; }
        c.name = res.j.name;
        IRIS_WR._rooms.forEach(function (r) { if (r.category_id === id) r.category_name = res.j.name; });
        iris_wr_render();
    });
}

function iris_wr_delete_cat(id) {
    var c = iris_wr_cat_by_id(id);
    if (!c) return;
    var mine = IRIS_WR._rooms.filter(function (r) { return r.category_id === id; }).length;
    var go = function () {
        iris_wr_api('DELETE', '/api/v2/war-rooms/categories/' + id).then(function (res) {
            if (!res.ok) { iris_wr_toast(false, res.j.message || 'Could not delete the category'); return; }
            iris_wr_toast(true, 'Category "' + c.name + '" deleted');
            iris_wr_reload();      /* it re-validates the filter: a deleted category falls back to All */
        });
    };
    var text = 'The rooms filed under it (' + mine + ' that you can see) become uncategorised. No room is deleted.';
    if (typeof swal === 'function') {
        swal({title: 'Delete category "' + c.name + '"?', text: text, icon: 'warning', buttons: true, dangerMode: true})
            .then(function (yes) { if (yes) go(); });
    } else if (window.confirm('Delete category "' + c.name + '"? ' + text)) {
        go();
    }
}

/* ---------------------------------------------------------------- rooms */

function iris_wr_room(id) {
    for (var i = 0; i < IRIS_WR._rooms.length; i++) {
        if (IRIS_WR._rooms[i].id === id) return IRIS_WR._rooms[i];
    }
    return null;
}

function iris_wr_replace_room(row) {
    for (var i = 0; i < IRIS_WR._rooms.length; i++) {
        if (IRIS_WR._rooms[i].id === row.id) {
            row.can_manage = IRIS_WR._rooms[i].can_manage;
            IRIS_WR._rooms[i] = row;
            return;
        }
    }
}

function iris_wr_match(r) {
    if (!IRIS_WR._q) return true;
    var hay = ((r.name || '') + ' ' + (r.description || '')).toLowerCase();
    return hay.indexOf(IRIS_WR._q) !== -1;
}

function iris_wr_card(r) {
    var id = iris_wr_int(r.id);
    if (id === null) return '';
    var archived = r.archived === true;
    var meta = r.member_count + ' member' + (r.member_count === 1 ? '' : 's')
        + ' · ' + r.case_count + ' case' + (r.case_count === 1 ? '' : 's')
        + (r.my_role ? ' · ' + r.my_role : '');
    var actions = '';
    if (r.can_manage) {
        actions = archived
            ? '<button type="button" class="iris-wr-iconbtn iris-wr-restore" title="Restore this room to the list" ' +
              'aria-label="Restore ' + iris_wr_esc(r.name) + '">' + IRIS_WR_ICONS.restore + ' Restore</button>'
            : '<button type="button" class="iris-wr-iconbtn iris-wr-move" title="Move to category" aria-haspopup="true" ' +
              'aria-label="Move ' + iris_wr_esc(r.name) + ' to a category">' + IRIS_WR_ICONS.move + '</button>' +
              '<button type="button" class="iris-wr-iconbtn iris-wr-archive" title="File this room away — its state is kept" ' +
              'aria-label="Archive ' + iris_wr_esc(r.name) + '">' + IRIS_WR_ICONS.archive + ' Archive</button>';
    }
    var cat = iris_wr_room_cat(r);
    var catLabel = (IRIS_WR._catFilter === 'all' && cat !== null)
        ? '<div class="iris-wr-card-cat" title="Category">' + IRIS_WR_ICONS.folder +
          iris_wr_esc(iris_wr_cat_by_id(cat).name) + '</div>' : '';
    var status = ['open', 'active', 'standby', 'closed'].indexOf(r.status) !== -1 ? r.status : 'open';
    return '<div class="col-md-4 mb-3"><div class="iris-wr-card' + (archived ? ' iris-wr-archived' : '') + '" ' +
        'data-room-id="' + id + '"' + (r.can_manage && !archived ? ' draggable="true"' : '') + '>' +
        '<div style="display:flex; align-items:flex-start;">' +
        '<div class="iris-wr-card-title">' +
        (status === 'open' ? '<span class="iris-wr-open-dot"></span>' : '') +
        iris_wr_esc(r.name) + '</div>' +
        '<span class="iris-wr-badge iris-wr-badge-' + status + '" style="margin-left:auto;">' + status + '</span></div>' +
        '<div class="iris-wr-card-desc">' + iris_wr_esc(r.description || '') + '</div>' + catLabel +
        '<div class="iris-wr-card-foot"><span>' +
        (archived ? 'Archived ' + iris_wr_esc(iris_wr_date(r.archived_at)) : iris_wr_created(r.created_at)) +
        '</span><span style="margin-left:12px;">' + iris_wr_esc(meta) + '</span>' +
        '<span class="iris-wr-card-actions">' + actions + '</span></div></div></div>';
}

function iris_wr_chip_counts(rooms) {
    var counts = {'': rooms.length, open: 0, active: 0, standby: 0, closed: 0};
    rooms.forEach(function (r) { if (counts[r.status] !== undefined) counts[r.status] += 1; });
    document.querySelectorAll('#iris-wr-chips .iris-wr-chip').forEach(function (chip) {
        var key = chip.getAttribute('data-status') || '';
        var span = chip.querySelector('.iris-wr-chip-count');
        if (!span) {
            span = document.createElement('span');
            span.className = 'iris-wr-chip-count';
            chip.appendChild(span);
        }
        span.textContent = String(counts[key] || 0);
    });
}

function iris_wr_render() {
    var base = IRIS_WR._rooms.filter(iris_wr_match);
    var live = base.filter(function (r) { return r.archived !== true; });
    var arch = base.filter(function (r) { return r.archived === true; });
    iris_wr_render_cats(live);
    var inCat = live.filter(iris_wr_in_cat);
    iris_wr_chip_counts(inCat);
    var shown = inCat.filter(function (r) { return !IRIS_WR._chip || r.status === IRIS_WR._chip; });
    var grid = document.getElementById('iris-wr-cards');
    var empty = document.getElementById('iris-wr-empty');
    grid.innerHTML = shown.map(iris_wr_card).join('');
    if (!shown.length) {
        /* Say WHY it is empty (none-vs-broken rule). */
        empty.textContent = IRIS_WR._rooms.length
            ? (live.length ? 'No rooms match the current filter.' : 'Every room is archived.')
            : 'No war rooms yet. Create one, or ask a lead to add you.';
        empty.style.display = '';
    } else {
        empty.style.display = 'none';
    }
    var archShown = arch.filter(iris_wr_in_cat).filter(function (r) {
        return !IRIS_WR._chip || r.status === IRIS_WR._chip;
    });
    var section = document.getElementById('iris-wr-archived');
    section.style.display = archShown.length ? '' : 'none';
    document.getElementById('iris-wr-arch-count').textContent = '(' + archShown.length + ')';
    var toggle = document.getElementById('iris-wr-arch-toggle');
    toggle.setAttribute('aria-expanded', IRIS_WR._archOpen ? 'true' : 'false');
    var archGrid = document.getElementById('iris-wr-arch-cards');
    archGrid.style.display = IRIS_WR._archOpen ? '' : 'none';
    archGrid.innerHTML = IRIS_WR._archOpen ? archShown.map(iris_wr_card).join('') : '';
    IRIS_WR._seq += 1;
    grid.setAttribute('data-wr-settled', String(IRIS_WR._seq));
}

function iris_wr_load() {
    return fetch('/api/v2/war-rooms', {headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (data) {
            IRIS_WR._rooms = (data.rooms || []).filter(function (r) { return iris_wr_int(r.id) !== null; });
        });
}

function iris_wr_reload() {
    return Promise.all([iris_wr_load(), iris_wr_load_cats()]).then(function () {
        iris_wr_set_filter(IRIS_WR._catFilter);
        iris_wr_render();
    });
}

function iris_wr_set_category(roomId, catId) {
    var r = iris_wr_room(roomId);
    if (!r || (iris_wr_room_cat(r) === catId)) return;
    iris_wr_api('PUT', '/api/v2/war-rooms/' + roomId + '/category', {category_id: catId}).then(function (res) {
        if (!res.ok) { iris_wr_toast(false, res.j.message || 'Could not move the room'); return; }
        iris_wr_replace_room(res.j);
        var c = catId !== null ? iris_wr_cat_by_id(catId) : null;
        iris_wr_toast(true, c ? 'Moved "' + r.name + '" to ' + c.name : '"' + r.name + '" is uncategorised');
        iris_wr_render();
    });
}

function iris_wr_archive(roomId, restore) {
    var r = iris_wr_room(roomId);
    if (!r) return;
    iris_wr_api(restore ? 'DELETE' : 'POST', '/api/v2/war-rooms/' + roomId + '/archive', restore ? null : {})
        .then(function (res) {
            if (!res.ok) {
                iris_wr_toast(false, res.j.message || (restore ? 'Could not restore the room' : 'Could not archive the room'));
                return;
            }
            iris_wr_replace_room(res.j);
            if (!restore) { IRIS_WR._archOpen = true; iris_wr_store_set(IRIS_WR_STORE_ARCH, '1'); }
            iris_wr_toast(true, (restore ? 'Restored "' : 'Archived "') + r.name + '"');
            iris_wr_render();
        });
}

/* The Move menu: one shared element, opened under the card's button. */
function iris_wr_close_move() {
    var m = document.getElementById('iris-wr-movemenu');
    if (m) m.parentNode.removeChild(m);
}

function iris_wr_open_move(roomId, btn) {
    iris_wr_close_move();
    var r = iris_wr_room(roomId);
    if (!r) return;
    var cur = iris_wr_room_cat(r);
    var menu = document.createElement('div');
    menu.id = 'iris-wr-movemenu';
    menu.className = 'iris-wr-movemenu';
    menu.setAttribute('role', 'menu');
    var html = '<div class="iris-wr-movemenu-title">Move to category</div>' +
        '<button type="button" role="menuitem" data-move-cat="none"><span class="iris-wr-check">' +
        (cur === null ? '&#10003;' : '') + '</span>No category</button>';
    IRIS_WR._cats.forEach(function (c) {
        var id = iris_wr_int(c.id);
        if (id === null) return;
        html += '<button type="button" role="menuitem" data-move-cat="' + id + '"><span class="iris-wr-check">' +
            (cur === id ? '&#10003;' : '') + '</span>' + iris_wr_esc(c.name) + '</button>';
    });
    if (!IRIS_WR._cats.length) {
        html += '<div class="iris-wr-movemenu-title">No category yet: add one with + in the sidebar.</div>';
    }
    menu.innerHTML = html;
    menu.setAttribute('data-room-id', String(roomId));
    document.body.appendChild(menu);
    var rect = btn.getBoundingClientRect();
    var top = rect.bottom + 4, left = Math.max(8, rect.right - menu.offsetWidth);
    if (top + menu.offsetHeight > window.innerHeight - 8) top = Math.max(8, rect.top - menu.offsetHeight - 4);
    menu.style.top = top + 'px';
    menu.style.left = left + 'px';
    var first = menu.querySelector('button');
    if (first) first.focus();
}

/* ------------------------------------------------- discovery panel */

function iris_wr_load_discovery() {
    var minShared = parseInt(
        document.getElementById('iris-wr-disc-minshared').value, 10) || 2;
    Promise.all([
        fetch('/api/v2/correlation/report?min_shared=' + minShared,
              {headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.json(); }),
        fetch('/api/v2/war-rooms/promoted-clusters',
              {headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.json(); })
    ]).then(function (results) {
        var report = results[0] || {};
        var promoted = (results[1] && results[1].promoted) || {};
        var clusters = report.clusters || [];
        var meta = report.case_meta || {};
        var box = document.getElementById('iris-wr-disc-list');
        document.getElementById('iris-wr-disc-empty').style.display =
            clusters.length ? 'none' : '';
        box.innerHTML = '';
        clusters.forEach(function (cl) {
            /* Built as DOM, not an HTML string: every value here arrives in
             * the fetched JSON, and textContent/setAttribute are safe by
             * construction where an innerHTML template needs per-value
             * escaping to be. Ids that land in hrefs are digits-validated. */
            var mutedEl = document.createElement('div');
            mutedEl.className = 'text-muted';
            mutedEl.style.fontSize = '0.8rem';
            cl.case_ids.forEach(function (cid, idx) {
                var m = meta[cid] || meta[String(cid)] || {};
                if (idx) { mutedEl.appendChild(document.createTextNode(' · ')); }
                var cidStr = String(cid);
                if (/^\d+$/.test(cidStr)) {
                    var caseA = document.createElement('a');
                    caseA.href = '/case?cid=' + cidStr;
                    caseA.textContent = '#' + cidStr;
                    mutedEl.appendChild(caseA);
                } else {
                    mutedEl.appendChild(document.createTextNode('#' + cidStr));
                }
                mutedEl.appendChild(document.createTextNode(' ' + (m.name || '')));
            });
            var roomId = String(promoted[cl.cluster_id] || '');
            var actionEl;
            if (/^\d+$/.test(roomId)) {
                actionEl = document.createElement('a');
                actionEl.className = 'btn btn-sm btn-secondary';
                actionEl.href = '/war-rooms/' + roomId + '?cid=' + IRIS_WR._cid;
                actionEl.textContent = 'Open room #' + roomId;
            } else {
                actionEl = document.createElement('button');
                actionEl.className = 'btn btn-sm btn-primary iris-wr-promote';
                actionEl.setAttribute('data-cluster-id', String(cl.cluster_id));
                actionEl.textContent = 'Promote to war room';
            }
            var div = document.createElement('div');
            div.className = 'mb-3 p-2';
            div.style.cssText = 'border: 1px solid rgba(139,92,246,0.25);' +
                'border-radius: 8px; background: rgba(139,92,246,0.05);';
            var rowEl = document.createElement('div');
            rowEl.style.cssText = 'display:flex; align-items:center;';
            var leftEl = document.createElement('div');
            leftEl.style.cssText = 'flex:1 1 auto; min-width:0;';
            var chip = document.createElement('span');
            chip.className = 'iris-wr-campaign-chip';
            chip.textContent = String(cl.cluster_id);
            leftEl.appendChild(chip);
            leftEl.appendChild(document.createTextNode(' '));
            var strongEl = document.createElement('strong');
            strongEl.textContent = cl.case_ids.length + ' cases';
            leftEl.appendChild(strongEl);
            leftEl.appendChild(document.createTextNode(
                ' · ' + cl.shared_ioc_count + ' shared IOC(s)'));
            leftEl.appendChild(mutedEl);
            var rightEl = document.createElement('div');
            rightEl.style.flexShrink = '0';
            rightEl.appendChild(actionEl);
            rowEl.appendChild(leftEl);
            rowEl.appendChild(rightEl);
            div.appendChild(rowEl);
            box.appendChild(div);
        });
    });
}

document.addEventListener('DOMContentLoaded', function () {
    IRIS_WR._catFilter = iris_wr_store_get(IRIS_WR_STORE_CAT) || 'all';
    IRIS_WR._archOpen = iris_wr_store_get(IRIS_WR_STORE_ARCH) === '1';
    iris_wr_reload().then(function () {
        document.getElementById('iris-wr-cats').setAttribute('data-wr-ready', '1');
    });
    iris_wr_load_discovery();

    document.getElementById('iris-wr-chips')
        .addEventListener('click', function (e) {
            var chip = e.target.closest('.iris-wr-chip');
            if (!chip) return;
            IRIS_WR._chip = chip.getAttribute('data-status') || '';
            document.querySelectorAll('#iris-wr-chips .iris-wr-chip')
                .forEach(function (c) { c.classList.remove('active'); });
            chip.classList.add('active');
            iris_wr_render();
        });

    document.getElementById('iris-wr-search')
        .addEventListener('input', function () {
            IRIS_WR._q = this.value.trim().toLowerCase();
            iris_wr_render();
        });

    /* Categories sidebar: pick, rename, delete, new; and the drop target of a dragged card. */
    var catList = document.getElementById('iris-wr-cat-list');
    catList.addEventListener('click', function (e) {
        var catEl = e.target.closest('.iris-wr-cat');
        if (!catEl) return;
        var key = catEl.getAttribute('data-cat');
        if (e.target.closest('.iris-wr-cat-rename')) { iris_wr_rename_cat_start(catEl); return; }
        if (e.target.closest('.iris-wr-cat-delete')) {
            var del = iris_wr_int(key);
            if (del !== null) iris_wr_delete_cat(del);
            return;
        }
        if (e.target.closest('.iris-wr-cat-pick')) {
            iris_wr_set_filter(key);
            iris_wr_render();
        }
    });
    catList.addEventListener('keydown', function (e) {
        var input = e.target.closest('#iris-wr-cat-rename-input');
        if (!input) return;
        if (e.key === 'Enter') { e.preventDefault(); iris_wr_rename_cat_save(input); }
        if (e.key === 'Escape') { e.preventDefault(); iris_wr_render(); }
    });
    catList.addEventListener('focusout', function (e) {
        if (e.target && e.target.id === 'iris-wr-cat-rename-input' && !e.target.disabled) {
            iris_wr_rename_cat_save(e.target);
        }
    });
    catList.addEventListener('dragover', function (e) {
        var catEl = e.target.closest('.iris-wr-cat');
        if (!catEl || IRIS_WR._drag === null || catEl.getAttribute('data-cat') === 'all') return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        catEl.classList.add('iris-wr-drop');
    });
    catList.addEventListener('dragleave', function (e) {
        var catEl = e.target.closest('.iris-wr-cat');
        if (catEl && !catEl.contains(e.relatedTarget)) catEl.classList.remove('iris-wr-drop');
    });
    catList.addEventListener('drop', function (e) {
        var catEl = e.target.closest('.iris-wr-cat');
        if (!catEl || IRIS_WR._drag === null) return;
        e.preventDefault();
        catEl.classList.remove('iris-wr-drop');
        var key = catEl.getAttribute('data-cat');
        var roomId = IRIS_WR._drag;
        IRIS_WR._drag = null;
        if (key === 'all') return;
        iris_wr_set_category(roomId, key === 'none' ? null : iris_wr_int(key));
    });

    document.getElementById('iris-wr-cat-new').addEventListener('click', function () {
        var row = document.getElementById('iris-wr-cat-newrow');
        iris_wr_new_cat_show(row.style.display === 'none');
    });
    var newName = document.getElementById('iris-wr-cat-newname');
    newName.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); iris_wr_new_cat_save(); }
        if (e.key === 'Escape') { e.preventDefault(); iris_wr_new_cat_show(false); }
    });

    /* Cards (live and archived): navigate, or the Move / Archive / Restore buttons. */
    function onCardClick(e) {
        var card = e.target.closest('.iris-wr-card');
        if (!card) return;
        /* Room ids are digits only (server-assigned) — re-derived before
           they reach a URL; a non-numeric value means broken markup. */
        var roomId = iris_wr_int(card.getAttribute('data-room-id'));
        if (roomId === null) return;
        if (e.target.closest('.iris-wr-move')) {
            e.preventDefault(); e.stopPropagation();
            iris_wr_open_move(roomId, e.target.closest('.iris-wr-move'));
            return;
        }
        if (e.target.closest('.iris-wr-archive')) { e.preventDefault(); iris_wr_archive(roomId, false); return; }
        if (e.target.closest('.iris-wr-restore')) { e.preventDefault(); iris_wr_archive(roomId, true); return; }
        if (e.target.closest('button')) return;
        window.location.href = '/war-rooms/' + roomId + '?cid=' + IRIS_WR._cid;
    }
    document.getElementById('iris-wr-cards').addEventListener('click', onCardClick);
    document.getElementById('iris-wr-arch-cards').addEventListener('click', onCardClick);
    document.getElementById('iris-wr-cards').addEventListener('dragstart', function (e) {
        var card = e.target.closest && e.target.closest('.iris-wr-card[draggable="true"]');
        if (!card) return;
        IRIS_WR._drag = iris_wr_int(card.getAttribute('data-room-id'));
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', 'war room');
    });
    document.getElementById('iris-wr-cards').addEventListener('dragend', function () {
        IRIS_WR._drag = null;
        document.querySelectorAll('.iris-wr-cat.iris-wr-drop').forEach(function (el) {
            el.classList.remove('iris-wr-drop');
        });
    });

    document.addEventListener('click', function (e) {
        var menu = document.getElementById('iris-wr-movemenu');
        if (!menu) return;
        var item = e.target.closest('#iris-wr-movemenu [data-move-cat]');
        if (item) {
            var roomId = iris_wr_int(menu.getAttribute('data-room-id'));
            var key = item.getAttribute('data-move-cat');
            iris_wr_close_move();
            if (roomId !== null) iris_wr_set_category(roomId, key === 'none' ? null : iris_wr_int(key));
            return;
        }
        if (!e.target.closest('#iris-wr-movemenu')) iris_wr_close_move();
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') iris_wr_close_move();
    });
    window.addEventListener('scroll', function (e) {
        var menu = document.getElementById('iris-wr-movemenu');
        if (menu && e.target && e.target.nodeType === 1 && menu.contains(e.target)) return;
        iris_wr_close_move();
    }, true);

    document.getElementById('iris-wr-arch-toggle').addEventListener('click', function () {
        IRIS_WR._archOpen = !IRIS_WR._archOpen;
        iris_wr_store_set(IRIS_WR_STORE_ARCH, IRIS_WR._archOpen ? '1' : '0');
        iris_wr_render();
    });

    document.getElementById('iris-wr-new-btn')
        .addEventListener('click', function () {
            document.getElementById('iris-wr-new-name').value = '';
            document.getElementById('iris-wr-new-desc').value = '';
            document.getElementById('iris-wr-new-error').style.display = 'none';
            var sel = document.getElementById('iris-wr-new-cat');
            sel.innerHTML = '<option value="">No category</option>' + IRIS_WR._cats.map(function (c) {
                var id = iris_wr_int(c.id);
                return id === null ? '' : '<option value="' + id + '">' + iris_wr_esc(c.name) + '</option>';
            }).join('');
            sel.value = typeof IRIS_WR._catFilter === 'number' ? String(IRIS_WR._catFilter) : '';
            document.getElementById('iris-wr-new-cat-row').style.display = IRIS_WR._cats.length ? '' : 'none';
            $('#iris-wr-new-modal').modal('show');
        });

    document.getElementById('iris-wr-new-save')
        .addEventListener('click', function () {
            var body = {
                name: document.getElementById('iris-wr-new-name').value,
                description: document.getElementById('iris-wr-new-desc').value,
                category_id: iris_wr_int(document.getElementById('iris-wr-new-cat').value),
                csrf_token: iris_wr_csrf()
            };
            fetch('/api/v2/war-rooms', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)
            }).then(function (r) {
                return r.json().then(function (j) { return {ok: r.ok, j: j}; });
            }).then(function (res) {
                if (!res.ok) {
                    var err = document.getElementById('iris-wr-new-error');
                    err.textContent = res.j.message || 'Failed to create room';
                    err.style.display = '';
                    return;
                }
                var id = iris_wr_int(res.j.id);
                if (id !== null) window.location.href = '/war-rooms/' + id + '?cid=' + IRIS_WR._cid;
            });
        });

    document.getElementById('iris-wr-disc-refresh')
        .addEventListener('click', iris_wr_load_discovery);
    document.getElementById('iris-wr-disc-list')
        .addEventListener('click', function (e) {
            var btn = e.target.closest('.iris-wr-promote');
            if (!btn) return;
            btn.disabled = true;
            var minShared = parseInt(
                document.getElementById('iris-wr-disc-minshared').value, 10) || 2;
            fetch('/api/v2/war-rooms/promote-cluster', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    cluster_id: btn.getAttribute('data-cluster-id'),
                    min_shared: minShared,
                    csrf_token: iris_wr_csrf()
                })
            }).then(function (r) {
                return r.json().then(function (j) {
                    return {ok: r.ok, status: r.status, j: j};
                });
            }).then(function (res) {
                if (res.ok) {
                    window.location.href = '/war-rooms/' + res.j.id +
                        '?cid=' + IRIS_WR._cid;
                } else if (res.status === 409 && res.j.room_id) {
                    window.location.href = '/war-rooms/' + res.j.room_id +
                        '?cid=' + IRIS_WR._cid;
                } else {
                    btn.disabled = false;
                    alert(res.j.message || 'Promote failed');
                }
            });
        });
});

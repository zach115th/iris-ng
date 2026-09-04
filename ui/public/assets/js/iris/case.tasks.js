var current_users_list = [];
var g_task_id = null;
var g_task_desc_editor = null;

/* iris-next: three views over the same task list - 'table' | 'board' | 'tree' */
var g_task_view = 'table';        // which view is currently shown
var g_task_links = [];            // [{from_task_id, to_task_id, link_type}]
/* Separate from the array above: an empty [] is what "this case has no links"
 * looks like AND what "we have not asked yet" looks like, and the card view
 * must not claim a task has no dependencies before it has looked. */
var g_task_links_loaded = false;
var g_task_links_failed = false;
/* And a third: neither of the two above is set while the request is in the
 * air, so without this every re-render fires another identical fetch. */
var g_task_links_inflight = false;
var g_tasks_by_id = {};           // task_id -> task row (from tasks_list)
var g_tree_collapsed = {};        // "<graph>:<task_id>" -> true when collapsed
var g_task_status_catalog = [];   // live TaskStatus catalog, from /case/tasks/list

const IRIS_TASK_VIEW_KEY = 'irisTaskView';
const IRIS_TASK_VIEWS = ['table', 'cards', 'board', 'tree'];

/* v3 card view state: which task is open, which detail tab, cached comments. */
const IRIS_TK = {sel: null, tab: 'details', comments: {}, loading: {},
                 search: '', editing: false};

/* Bootstrap contextual name -> the dot colour used on a board column header.
 * Validated against this map rather than interpolated: status_bscolor is
 * catalog text and it lands in a style attribute here. Unknown -> neutral. */
const IRIS_TASK_DOT = {
    danger: '#F25961', warning: '#f4c430', success: '#2dce89',
    primary: '#5e72e4', info: '#48b0f7', secondary: '#9a9aa5',
    muted: '#9aa0b5', light: '#c8c8d0', dark: '#7a7a85'
};

/* Show exactly one view. Called on every load so a refresh cannot leave two
 * cards visible (hide_loader() force-shows the table card). */
function apply_task_view() {
    $('#card_main_load').toggle(g_task_view === 'table');
    $('#iris-task-cards-view').toggle(g_task_view === 'cards');
    $('#iris-task-board-card').toggle(g_task_view === 'board');
    $('#iris-task-tree-card').toggle(g_task_view === 'tree');

    $('.iris-task-view-btn').each(function () {
        const on = $(this).attr('data-view') === g_task_view;
        $(this).toggleClass('btn-primary', on).toggleClass('btn-dark', !on);
    });

    if (g_task_view === 'cards') {
        render_task_cards();
    } else if (g_task_view === 'board') {
        render_task_board();
    } else if (g_task_view === 'tree') {
        // Always re-pull links so the tree reflects current state.
        fetch_task_links_then_render();
    }
}

function set_task_view(view) {
    if (IRIS_TASK_VIEWS.indexOf(view) === -1) { return; }
    g_task_view = view;
    try { localStorage.setItem(IRIS_TASK_VIEW_KEY, view); } catch (e) { /* private mode */ }
    apply_task_view();
}

/* Back-compat: the page used to carry a single table<->tree toggle button. */
function toggle_task_view() {
    set_task_view(g_task_view === 'tree' ? 'table' : 'tree');
}

/*
 * Render the kanban board: one column per entry in the LIVE task-status
 * catalog, ordered by id (which is the seed order To do / In progress /
 * On hold / Done / Canceled). Deriving the columns rather than hardcoding
 * them means a deployment that has added a status gets a column for it,
 * and a task whose status is not in the catalog still shows up - in an
 * explicit "Unknown status" column rather than vanishing.
 *
 * Built as DOM, not an HTML string: task titles, assignee names and tags are
 * analyst text, and .text() cannot be escaped wrongly.
 */
function render_task_board() {
    if (g_task_view !== 'board') { return; }

    const $board = $('<div>').addClass('iris-tb-board');
    const rows = (typeof tasks_list !== 'undefined' && tasks_list) ? tasks_list : [];

    const cols = g_task_status_catalog.slice().sort(function (a, b) { return a.id - b.id; });
    const known = {};
    cols.forEach(function (s) { known[s.id] = true; });

    // Anything whose status is missing from the catalog gets its own column,
    // so the board's task count always matches the case's task count.
    const orphans = rows.filter(function (t) { return !known[t.task_status_id]; });
    const columns = cols.map(function (s) {
        return {id: s.id, name: s.status_name, color: IRIS_TASK_DOT[s.status_bscolor] || '#9a9aa5',
                items: rows.filter(function (t) { return t.task_status_id === s.id; })};
    });
    if (orphans.length) {
        columns.push({id: null, name: 'Unknown status', color: '#9a9aa5', items: orphans});
    }

    columns.forEach(function (col) {
        const $col = $('<div>').addClass('iris-tb-col').attr('data-status_id', col.id === null ? '' : col.id);
        if (col.id !== null) { $col.attr('data-droppable', '1'); }

        const $head = $('<div>').addClass('iris-tb-colhead');
        $head.append($('<span>').addClass('iris-tb-coldot').css('background', col.color));
        $head.append($('<span>').text(col.name));
        $head.append($('<span>').addClass('iris-tb-colcount').text(col.items.length));
        $col.append($head);

        // Cards live in their own scroll container so the column header stays
        // put and a long column scrolls instead of stretching the page.
        const $body = $('<div>').addClass('iris-tb-colbody');
        if (col.items.length === 0) {
            $body.append($('<div>').addClass('iris-tb-colempty').text('No tasks'));
        } else {
            col.items.forEach(function (t) { $body.append(build_task_card(t, col.id !== null)); });
        }
        $col.append($body);
        $board.append($col);
    });

    $('#iris-task-board').empty().append($board);
    iris_task_board_sync_height();

    // The board is not filtered by the table's search box - that box lives in
    // the table view and is not visible here - so say what is being shown.
    const total = rows.length;
    $('#iris-task-board-hint').text(
        'Showing all ' + total + ' task' + (total === 1 ? '' : 's') + ' in this case.' +
        ' Drag a card to another column to change its status.');
}

/* Task timestamps are naive-UTC storage. Label the STORED value; never put it
 * through new Date(), which re-zones it to the browser and shifts the time by
 * the analyst's offset. Same idiom as the v3 asset/IOC surfaces. */
const IRIS_TASK_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function iris_task_utc_label(iso, withTime) {
    const m = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/);
    if (!m) { return null; }
    let s = IRIS_TASK_MONTHS[parseInt(m[2], 10) - 1] + ' ' +
        parseInt(m[3], 10) + ', ' + m[1];
    if (withTime && m[4]) { s += ' ' + m[4] + ':' + m[5] + ' UTC'; }
    return s;
}

/* A one-line plain-text preview of a markdown description. Deliberately NOT
 * rendered: on a card the point is to recognise the task at a glance, and
 * headings, tables and code fences do not survive three clamped lines. The
 * markers are stripped so the preview reads as prose rather than syntax. */
function iris_task_desc_preview(md, limit) {
    if (!md) { return ''; }
    let s = String(md)
        .replace(/```[\s\S]*?```/g, ' ')      // fenced code blocks
        .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ') // images
        .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1') // links -> their text
        .replace(/^\s{0,3}#{1,6}\s+/gm, '')   // headings
        .replace(/^\s{0,3}>\s?/gm, '')        // block quotes
        .replace(/^\s*[-*+]\s+/gm, '')        // bullets
        .replace(/\|/g, ' ')                  // table pipes
        .replace(/[*_`~]/g, '')               // emphasis / code marks
        .replace(/\s+/g, ' ')
        .trim();
    const cap = limit || 160;
    if (s.length > cap) { s = s.slice(0, cap - 1).trimEnd() + '…'; }
    return s;
}

/* One board card: title, #id, a description preview, assignees, tags (capped)
 * and when it was opened. */
function build_task_card(task, draggable) {
    const $card = $('<div>').addClass('iris-tb-card').attr('data-task_id', task.task_id);
    if (draggable) { $card.attr('draggable', 'true'); }

    const title = task.task_title && !isWhiteSpace(task.task_title)
        ? task.task_title : '(untitled)';
    $card.append($('<span>').addClass('iris-tb-card-title').text(title).attr('title', title));
    $card.append($('<span>').addClass('iris-tb-card-id').text('#' + task.task_id));

    // A task with no description renders no preview: an absent line says
    // nothing, whereas a "No description" line on every card would be noise.
    const desc = iris_task_desc_preview(task.task_description);
    if (desc) {
        $card.append($('<div>').addClass('iris-tb-card-desc').text(desc).attr('title', desc));
    }

    const $meta = $('<div>').addClass('iris-tb-card-meta');
    const assignees = task.task_assignees || [];
    if (assignees.length) {
        assignees.forEach(function (a) {
            $meta.append($('<span>').addClass('iris-tb-chip').text(a.name));
        });
    } else {
        // The flat table says "Unassigned" explicitly; an unowned task is a
        // finding, so the card says it too rather than showing nothing.
        $meta.append($('<span>').addClass('iris-tb-chip iris-tb-chip-none').text('Unassigned'));
    }

    if (task.task_tags) {
        const tags = task.task_tags.split(',').filter(function (x) { return x.trim() !== ''; });
        tags.slice(0, 3).forEach(function (tg) {
            $meta.append($('<span>').addClass('iris-tb-chip iris-tb-chip-tag').text(tg.trim()));
        });
        if (tags.length > 3) {
            $meta.append($('<span>').addClass('iris-tb-chip iris-tb-chip-tag')
                .text('+' + (tags.length - 3)));
        }
    }
    $card.append($meta);

    const opened = iris_task_utc_label(task.task_open_date, true);
    if (opened) {
        $card.append($('<div>').addClass('iris-tb-card-date').text('Opened ' + opened));
    }
    return $card;
}

/*
 * Fit the board to the space actually available.
 *
 * The board's top edge moves - the case header is compact on working tabs and
 * taller on Summary, it hydrates after first paint and wraps on narrow
 * viewports, and a sticky toolbar sits above - and the AI chat bar is fixed to
 * the bottom and changes height when it is expanded. So the floor and the top
 * are both MEASURED rather than derived from constants; the CSS fallback is
 * only for first paint and no-JS.
 */
/* Breathing space kept between the bottom of the board card and the AI chat
 * bar. The bar is a fixed overlay and must never be crowded by page content. */
const IRIS_TASK_BOARD_GAP = 24;

function iris_task_board_sync_height() {
    const board = document.getElementById('iris-task-board');
    if (!board || board.offsetParent === null) { return; }

    const brect = board.getBoundingClientRect();

    // The chat bar is fixed at the bottom of the viewport; its top edge is the
    // floor. A zero-height rect means "not rendered", not "at the top".
    let floor = window.innerHeight;
    const chat = document.getElementById('iris-chat');
    if (chat) {
        const cr = chat.getBoundingClientRect();
        if (cr.height > 0 && cr.top > 0) { floor = Math.min(floor, cr.top); }
    }

    // Everything between the board's bottom edge and the card's outer bottom -
    // the hint line, the card body's padding, the card's margin - is MEASURED
    // as one overhang rather than guessed at. It does not change when the
    // columns grow, so this cannot oscillate. Subtracting a constant here is
    // what put the card flush against the chat bar the first time.
    const card = document.getElementById('iris-task-board-card');
    let overhang = 0;
    if (card) {
        const crect = card.getBoundingClientRect();
        if (crect.height > 0) { overhang = Math.max(0, crect.bottom - brect.bottom); }
    }

    const h = Math.max(320, Math.round(floor - brect.top - overhang - IRIS_TASK_BOARD_GAP));
    // write-only-on-change: an unchanged write still invalidates layout,
    // and this runs from a ResizeObserver — reading the inline style back
    // is cheap (no layout), rewriting it is not.
    const hpx = h + 'px';
    const root = document.documentElement;
    if (root.style.getPropertyValue('--iris-tb-h') !== hpx) {
        root.style.setProperty('--iris-tb-h', hpx);
    }
}
window.irisTaskBoardSyncHeight = iris_task_board_sync_height;

/* Move a card to another column = the same status write the table's inline
 * cell editor performs, so both views change a status the same way. */
function board_set_task_status(task_id, status_id) {
    const task = (typeof tasks_list !== 'undefined' && tasks_list || []).find(
        function (t) { return t.task_id === task_id; });
    if (!task || task.task_status_id === status_id) { return; }

    post_request_api(`/case/tasks/status/update/${task_id}`, JSON.stringify({
        task_status_id: status_id,
        csrf_token: $('#csrf_token').val()
    }))
    // Re-draw from the server either way: notify_auto_api() reports a refusal
    // (no write access, unknown status), and the board must never keep showing
    // a move that did not happen.
    .done(function (data) { notify_auto_api(data); get_tasks(); })
    .fail(function () { get_tasks(); });
}

/* =====================================================================
 * v3 card view: a master list on the left, a display/edit panel on the
 * right. Nothing here re-implements task editing - Edit Task opens the
 * existing modal, Delete calls the existing delete_task(), and comments
 * ride the endpoints the comments modal already uses.
 * ===================================================================== */

function iris_tk_cid() {
    const m = window.location.search.match(/[?&]cid=(\d+)/);
    return m ? m[1] : '';
}

function iris_tk_status_of(task) {
    for (let i = 0; i < g_task_status_catalog.length; i += 1) {
        if (g_task_status_catalog[i].id === task.task_status_id) {
            return g_task_status_catalog[i];
        }
    }
    return null;
}

function iris_tk_by_id(id) {
    const rows = (typeof tasks_list !== 'undefined' && tasks_list) ? tasks_list : [];
    for (let i = 0; i < rows.length; i += 1) {
        if (rows[i].task_id === id) { return rows[i]; }
    }
    return null;
}

/* Left-hand list. Search matches title, description and tags - the fields an
 * analyst would look for a task by. */
function render_task_cards() {
    if (g_task_view !== 'cards') { return; }

    const rows = (typeof tasks_list !== 'undefined' && tasks_list) ? tasks_list : [];
    const q = (IRIS_TK.search || '').trim().toLowerCase();
    const shown = !q ? rows : rows.filter(function (t) {
        return [t.task_title, t.task_description, t.task_tags]
            .some(function (f) { return String(f || '').toLowerCase().indexOf(q) !== -1; });
    });

    const $list = $('#iris-tk-list').empty();
    shown.forEach(function (t) { $list.append(iris_tk_row(t)); });

    // Distinguish "this case has no tasks" from "your search matched none":
    // an empty list with no explanation is a claim the page cannot support.
    const $none = $('#iris-tk-none');
    if (shown.length === 0) {
        $none.text(rows.length === 0
            ? 'No tasks in this case yet — use Add task to create the first one.'
            : 'No task matches "' + q + '" — ' + rows.length + ' in this case.').show();
    } else {
        $none.hide();
    }

    // A selection that is no longer in the list (deleted, or filtered out)
    // must not leave a stale panel open.
    if (IRIS_TK.sel !== null && !shown.some(function (t) { return t.task_id === IRIS_TK.sel; })) {
        if (!iris_tk_by_id(IRIS_TK.sel)) { IRIS_TK.sel = null; }
    }
    // The Linked tasks block needs the case's link graph. Fetch it once and
    // re-render; the dependency tree shares the same state.
    if (!g_task_links_loaded && !g_task_links_failed) {
        fetch_task_links(function () {
            if (g_task_view === 'cards') { iris_tk_render_detail(); }
        });
    }

    // Re-rendering the list must not rebuild an open edit form - typing in
    // the search box would otherwise wipe the analyst's changes. Selection
    // and tab changes clear the flag first, so they still redraw.
    if (!IRIS_TK.editing) { iris_tk_render_detail(); }
    iris_tk_fit_card();
}

function iris_tk_row(task) {
    const st = iris_tk_status_of(task);
    const colour = st ? (IRIS_TASK_DOT[st.status_bscolor] || '#9a9aa5') : '#9a9aa5';

    const $row = $('<div>').addClass('iris-tk-row').attr('data-task_id', task.task_id)
        .css('border-left-color', colour);
    if (IRIS_TK.sel === task.task_id) { $row.addClass('selected'); }

    const $main = $('<div>').addClass('iris-tk-row-main');
    const title = task.task_title && !isWhiteSpace(task.task_title)
        ? task.task_title : '(untitled)';
    $main.append($('<span>').addClass('iris-tk-row-title').text(title).attr('title', title));

    const $sub = $('<div>').addClass('iris-tk-row-sub');
    if (st) {
        $sub.append($('<span>').addClass('iris-tk-chip iris-tk-chip-status').text(st.status_name));
    }
    const assignees = task.task_assignees || [];
    if (assignees.length) {
        assignees.forEach(function (a) {
            $sub.append($('<span>').addClass('iris-tk-chip').text(a.name));
        });
    } else {
        $sub.append($('<span>').addClass('iris-tk-chip iris-tk-chip-none').text('Unassigned'));
    }
    const opened = iris_task_utc_label(task.task_open_date, false);
    if (opened) { $sub.append($('<span>').text(opened)); }
    $main.append($sub);

    $row.append($main);
    $row.append($('<span>').addClass('iris-tk-row-id').css({color: '#9b87d6', fontSize: '0.7rem'})
        .text('#' + task.task_id));
    return $row;
}

/* Right-hand display/edit panel. */
function iris_tk_render_detail() {
    const $ph = $('#iris-tk-placeholder');
    const $det = $('#iris-tk-detail').empty();
    const task = IRIS_TK.sel === null ? null : iris_tk_by_id(IRIS_TK.sel);

    if (!task) {
        $det.hide();
        $ph.show();
        return;
    }
    $ph.hide();
    $det.show();

    const title = task.task_title && !isWhiteSpace(task.task_title)
        ? task.task_title : '(untitled)';

    const $head = $('<div>').addClass('iris-tk-dhead');
    const $hmain = $('<div>').addClass('iris-tk-dhead-main');
    $hmain.append($('<span>').addClass('iris-tk-dtitle').text(title).attr('title', title));
    $hmain.append($('<div>').addClass('iris-tk-dsub').text('Task · #' + task.task_id));
    $head.append($hmain);

    const $acts = $('<div>').addClass('iris-tk-dacts');
    if (IRIS_TK.editing) {
        // v3 swaps the header actions while editing rather than opening a modal.
        $acts.append($('<button>').attr('type', 'button')
            .addClass('btn btn-sm btn-secondary')
            .html('<i class="fa-solid fa-xmark mr-1"></i>Cancel')
            .on('click', function () {
                IRIS_TK.editing = false;
                iris_tk_render_detail();
            }));
        $acts.append($('<button>').attr('type', 'button')
            .addClass('btn btn-sm btn-primary').attr('id', 'iris-tk-f-save')
            .html('<i class="fa-solid fa-floppy-disk mr-1"></i>Save Changes')
            .on('click', function () { iris_tk_save_edit(task); }));
    } else {
        // Share + Markdown link — the legacy modal's ⋮ actions, kept
        // reachable on the v3 header (same functions, same deep link).
        $acts.append($('<button>').attr('type', 'button')
            .attr('title', 'Copy shareable link')
            .addClass('iris-tk-linkbtn')
            .html('<i class="fa fa-share"></i>')
            .on('click', function () { copy_object_link(task.task_id); }));
        $acts.append($('<button>').attr('type', 'button')
            .attr('title', 'Copy Markdown link')
            .addClass('iris-tk-linkbtn')
            .html('<i class="fa-brands fa-markdown"></i>')
            .on('click', function () {
                copy_object_link_md('task', task.task_id);
            }));
        // Both buttons drive the machinery this page already has.
        $acts.append($('<button>').attr('type', 'button')
            .addClass('btn btn-sm btn-primary')
            .html('<i class="fa-solid fa-pen-to-square mr-1"></i>Edit Task')
            .on('click', function () {
                IRIS_TK.editing = true;
                IRIS_TK.tab = 'details';
                iris_tk_render_detail();
            }));
        $acts.append($('<button>').attr('type', 'button')
            .addClass('btn btn-sm btn-outline-danger')
            .html('<i class="fa-solid fa-trash mr-1"></i>Delete')
            .on('click', function () { delete_task(task.task_id); }));
    }
    $head.append($acts);
    $det.append($head);

    const comments = IRIS_TK.comments[task.task_id];
    const $tabs = $('<div>').addClass('iris-tk-tabs');
    [['details', 'Details'],
     ['comments', 'Comments' + (comments ? ' (' + comments.length + ')' : '')]
    ].forEach(function (t) {
        const $b = $('<button>').attr('type', 'button').addClass('iris-tk-tab').text(t[1]);
        if (IRIS_TK.tab === t[0]) { $b.addClass('active'); }
        $b.on('click', function () {
            // Leaving Details discards an edit in progress, the same way the
            // v3 Assets panel behaves.
            IRIS_TK.editing = false;
            IRIS_TK.tab = t[0];
            iris_tk_render_detail();
            if (t[0] === 'comments') { iris_tk_load_comments(task.task_id); }
        });
        $tabs.append($b);
    });
    $det.append($tabs);

    if (IRIS_TK.tab === 'comments') {
        $det.append(iris_tk_comments_body(task));
        iris_tk_load_comments(task.task_id);
    } else if (IRIS_TK.editing) {
        $det.append(iris_tk_edit_body(task));
        iris_tk_init_tag_widget();
    } else {
        $det.append(iris_tk_details_body(task));
    }
    iris_tk_fit_card();
}

/* ---------------------------------------------------------------------
 * Inline editing, v3-style: the Details pane becomes the form, with Cancel
 * and Save Changes in the header. No modal.
 *
 * Verified by experiment before writing this: /case/tasks/update/<id> leaves
 * fields absent from the payload alone - description, tags, custom attributes
 * and the open date all survived a title+status+assignees update - so the
 * form sends only what it edits. task_assignees_id is the exception:
 * tasks_update() rejects a payload without it.
 * ------------------------------------------------------------------ */
function iris_tk_field(label, $control) {
    return $('<div>').addClass('iris-tk-fld')
        .append($('<label>').addClass('iris-tk-meta-k').text(label))
        .append($control);
}

function iris_tk_edit_body(task) {
    const $body = $('<div>').addClass('iris-tk-dbody');

    $body.append(iris_tk_field('Title *',
        $('<input>').attr({type: 'text', id: 'iris-tk-f-title', autocomplete: 'off'})
            .addClass('form-control form-control-sm')
            .val(task.task_title || '')));

    const $row = $('<div>').addClass('iris-tk-frow');
    const $status = $('<select>').attr('id', 'iris-tk-f-status')
        .addClass('form-control form-control-sm');
    g_task_status_catalog.slice().sort(function (a, b) { return a.id - b.id; })
        .forEach(function (s) {
            const $o = $('<option>').attr('value', s.id).text(s.status_name);
            if (s.id === task.task_status_id) { $o.attr('selected', 'selected'); }
            $status.append($o);
        });
    $row.append(iris_tk_field('Status *', $status));

    const $assignees = $('<select>').attr({id: 'iris-tk-f-assignees', multiple: 'multiple',
                                           size: 4})
        .addClass('form-control form-control-sm');
    const current = (task.task_assignees || []).map(function (a) { return a.id; });
    if (!current_users_list || current_users_list.length === 0) {
        // Not fetched yet: say so rather than rendering an empty picker that
        // looks like "this case has no analysts".
        $assignees.append($('<option>').attr('disabled', 'disabled').text('Loading users…'));
        refresh_users(function () {
            if (IRIS_TK.editing) { iris_tk_render_detail(); }
        });
    } else {
        current_users_list.forEach(function (u) {
            // Same filter the task modal applies.
            if (u.user_access_level !== 4) { return; }
            const $o = $('<option>').attr('value', u.user_id)
                .text(u.user_login + ' (' + u.user_name + ')');
            if (current.indexOf(u.user_id) !== -1) { $o.attr('selected', 'selected'); }
            $assignees.append($o);
        });
    }
    $row.append(iris_tk_field('Assignees', $assignees));
    $body.append($row);

    $body.append($('<div>').addClass('iris-tk-section')
        .append($('<i>').addClass('fa-solid fa-file-lines'))
        .append($('<span>').text('Description')));
    $body.append($('<textarea>').attr({id: 'iris-tk-f-desc', rows: 8})
        .addClass('form-control form-control-sm')
        .val(task.task_description || ''));

    $body.append(iris_tk_field('Tags',
        $('<input>').attr({type: 'text', id: 'iris-tk-f-tags',
                           placeholder: 'Add tags...', autocomplete: 'off'})
            .addClass('form-control form-control-sm')
            .val(task.task_tags || '')));

    // Everything the inline form deliberately does not carry - custom
    // attributes, the markdown preview, managing task links - is one click
    // away rather than half-rebuilt here.
    $body.append($('<div>').addClass('iris-tk-fulllink')
        .append($('<a>').attr('href', 'javascript:void(0);').attr('id', 'iris-tk-f-full')
            .text('Full editor ↗')
            .on('click', function () { edit_task(task.task_id); })));
    return $body;
}

/* The Tags field uses the product's OWN widget (amsifySuggestags via
 * set_suggest_tags) so it gets chips and autocomplete over the bundled MISP
 * catalogs. It syncs the original input, so the save path reads it unchanged.
 * Re-attached per render behind a per-element guard. */
function iris_tk_init_tag_widget() {
    const el = document.getElementById('iris-tk-f-tags');
    if (!el || el.getAttribute('data-iris-tagged') === '1') { return; }
    if (typeof window.set_suggest_tags !== 'function' || !window.jQuery
        || !window.jQuery.fn || !window.jQuery.fn.amsifySuggestags) { return; }
    el.setAttribute('data-iris-tagged', '1');
    window.set_suggest_tags('iris-tk-f-tags');
}

function iris_tk_read_tags() {
    const el = document.getElementById('iris-tk-f-tags');
    if (!el) { return ''; }
    let parts = String(el.value || '').split(',');
    /* A tag typed but not yet committed with Enter/comma lives in the widget's
       own input, which the plugin inserts directly after ours. Clicking Save
       straight after typing must not silently drop it. */
    const area = el.nextElementSibling;
    const pending = area ? area.querySelector('.amsify-suggestags-input') : null;
    if (pending && pending.value) { parts = parts.concat(pending.value.split(',')); }
    const seen = {};
    return parts.map(function (t) { return t.trim(); })
        .filter(function (t) {
            if (!t || seen[t]) { return false; }
            seen[t] = 1;
            return true;
        }).join(',');
}

function iris_tk_save_edit(task) {
    const title = ($('#iris-tk-f-title').val() || '').trim();
    if (!title) {
        notify_error('A task title is required.');
        return;
    }
    const assignees = ($('#iris-tk-f-assignees').val() || []).map(function (v) {
        return parseInt(v, 10);
    }).filter(function (v) { return !isNaN(v); });

    $('#iris-tk-f-save').attr('disabled', 'disabled');
    post_request_api(`/case/tasks/update/${task.task_id}`, JSON.stringify({
        task_title: title,
        task_status_id: parseInt($('#iris-tk-f-status').val(), 10),
        task_assignees_id: assignees,
        task_description: $('#iris-tk-f-desc').val() || '',
        task_tags: iris_tk_read_tags(),
        csrf_token: $('#csrf_token').val()
    }))
    .done(function (data) {
        if (notify_auto_api(data)) {
            IRIS_TK.editing = false;
            get_tasks();
        }
        // A refused save leaves the form exactly as it is: the analyst's
        // typing survives to be corrected and retried.
    })
    .always(function () { $('#iris-tk-f-save').removeAttr('disabled'); });
}

function iris_tk_meta(label, $value) {
    return $('<div>')
        .append($('<span>').addClass('iris-tk-meta-k').text(label))
        .append($value);
}

function iris_tk_details_body(task) {
    const $body = $('<div>').addClass('iris-tk-dbody');

    const st = iris_tk_status_of(task);
    const $meta = $('<div>').addClass('iris-tk-meta');
    $meta.append(iris_tk_meta('Status', $('<span>').addClass('iris-tk-chip iris-tk-chip-status')
        .text(st ? st.status_name : 'Unknown')));

    const $as = $('<span>');
    const assignees = task.task_assignees || [];
    if (assignees.length) {
        assignees.forEach(function (a) {
            $as.append($('<span>').addClass('iris-tk-chip mr-1').text(a.name));
        });
    } else {
        $as.append($('<span>').addClass('iris-tk-chip iris-tk-chip-none').text('Unassigned'));
    }
    $meta.append(iris_tk_meta('Assignees', $as));

    const opened = iris_task_utc_label(task.task_open_date, true);
    $meta.append(iris_tk_meta('Opened', $('<span>').css({color: '#c8c8d0', fontSize: '0.78rem'})
        .text(opened || 'not recorded')));

    if (task.task_tags) {
        const $tags = $('<span>');
        task.task_tags.split(',').forEach(function (tg) {
            if (tg.trim()) {
                $tags.append($('<span>').addClass('iris-tk-chip iris-tk-chip-tag mr-1').text(tg.trim()));
            }
        });
        $meta.append(iris_tk_meta('Tags', $tags));
    }
    $body.append($meta);

    // The description is analyst markdown - render it with the PRODUCT'S
    // renderer, the same one the task modal's preview uses, so headings and
    // tables come out as they do everywhere else.
    const $desc = $('<div>').addClass('iris-tk-desc');
    if (task.task_description && !isWhiteSpace(task.task_description)) {
        const converter = get_showdown_convert();
        $desc.html(do_md_filter_xss(converter.makeHtml(do_md_filter_xss(task.task_description))));
    } else {
        $desc.append($('<i>').css('color', '#7a7a85').text('No description recorded.'));
    }
    $body.append($desc);

    $body.append(iris_tk_links_block(task));

    const $foot = $('<div>').addClass('iris-tk-foot');
    $foot.append($('<span>').text('ID #' + task.task_id));
    if (task.task_uuid) { $foot.append($('<span>').text('UUID ' + task.task_uuid)); }
    const cid = iris_tk_cid();
    if (cid) { $foot.append($('<span>').text('Case #' + cid)); }
    $body.append($foot);
    return $body;
}

/* The four views of this task's Jira-style relationships. Links are stored
 * once in the canonical forward direction; the inverse views are computed
 * here, the same way the edit modal computes them. */
const IRIS_TK_LINK_VIEWS = [
    {key: 'blocks', label: 'Blocks', type: 'blocks', side: 'from'},
    {key: 'is_blocked_by', label: 'Is blocked by', type: 'blocks', side: 'to'},
    {key: 'depends_on', label: 'Depends on', type: 'depends_on', side: 'from'},
    {key: 'is_depended_on_by', label: 'Is depended on by', type: 'depends_on', side: 'to'}
];

function iris_tk_links_for(taskId) {
    const out = {};
    IRIS_TK_LINK_VIEWS.forEach(function (v) {
        out[v.key] = g_task_links.filter(function (l) {
            return l.link_type === v.type &&
                (v.side === 'from' ? l.from_task_id === taskId : l.to_task_id === taskId);
        }).map(function (l) {
            return v.side === 'from' ? l.to_task_id : l.from_task_id;
        });
    });
    return out;
}

function iris_tk_links_block(task) {
    const $wrap = $('<div>').addClass('iris-tk-links');
    $wrap.append($('<span>').addClass('iris-tk-meta-k').text('Linked tasks'));

    // Three distinct states. Saying "no linked tasks" before the lookup has
    // run would be a claim about this task's dependencies that we cannot
    // support - and dependencies are exactly the thing an analyst acts on.
    if (g_task_links_failed) {
        $wrap.append($('<i>').css('color', '#F25961')
            .text('Could not load linked tasks.'));
        return $wrap;
    }
    if (!g_task_links_loaded) {
        $wrap.append($('<i>').css('color', '#7a7a85').text('Loading linked tasks…'));
        return $wrap;
    }

    const buckets = iris_tk_links_for(task.task_id);
    const any = IRIS_TK_LINK_VIEWS.some(function (v) { return buckets[v.key].length > 0; });
    if (!any) {
        $wrap.append($('<i>').css('color', '#7a7a85').text('No linked tasks.'));
        return $wrap;
    }

    IRIS_TK_LINK_VIEWS.forEach(function (v) {
        const ids = buckets[v.key];
        if (!ids.length) { return; }   // an absent bucket reads as "none of these"
        const $row = $('<div>').addClass('iris-tk-linkrow');
        $row.append($('<span>').addClass('iris-tk-linklabel').text(v.label));
        const $vals = $('<span>');
        ids.forEach(function (id) {
            const t = iris_tk_by_id(id);
            const $a = $('<a>').attr('href', 'javascript:void(0);')
                .addClass('iris-tk-linkitem').attr('data-task_id', id);
            if (t) {
                const title = t.task_title && !isWhiteSpace(t.task_title)
                    ? t.task_title : '(untitled)';
                $a.text('#' + id + ' ' + title).attr('title', title);
            } else {
                // Linked to something not in the current list - say which,
                // rather than rendering a bare id that looks like a glitch.
                $a.text('#' + id + ' (not in this list)');
            }
            $vals.append($a);
        });
        $row.append($vals);
        $wrap.append($row);
    });
    return $wrap;
}

function iris_tk_comments_body(task) {
    const $body = $('<div>').addClass('iris-tk-dbody iris-tk-dbody-split');
    const $list = $('<div>').addClass('iris-tk-clist').attr('id', 'iris-tk-clist');

    const comments = IRIS_TK.comments[task.task_id];
    if (comments === undefined) {
        // Not looked yet - say so. An empty pane would read as "no comments",
        // which is a different claim.
        $list.append($('<div>').css('color', '#7a7a85').text('Loading comments…'));
    } else if (comments === null) {
        $list.append($('<div>').css('color', '#F25961').text('Could not load comments.'));
    } else if (comments.length === 0) {
        $list.append($('<i>').css('color', '#7a7a85').text('No comments on this task yet.'));
    } else {
        comments.forEach(function (c) {
            const $c = $('<div>').addClass('iris-tk-comment');
            $c.append($('<div>').addClass('iris-tk-comment-meta')
                .text((c.user && c.user.user_name ? c.user.user_name : 'unknown') +
                      ' · ' + (iris_task_utc_label(c.comment_date, true) || '')));
            $c.append($('<div>').text(c.comment_text || ''));
            $list.append($c);
        });
    }
    $body.append($list);

    const $form = $('<div>').css({marginTop: '10px', flexShrink: 0});
    const $input = $('<textarea>').attr({id: 'iris-tk-comment-input', rows: 2,
                                         placeholder: 'Write a comment…'})
        .addClass('form-control form-control-sm');
    $form.append($input);
    $form.append($('<button>').attr('type', 'button')
        .addClass('btn btn-sm btn-primary mt-2')
        .text('Comment')
        .on('click', function () { iris_tk_post_comment(task.task_id); }));
    $body.append($form);
    return $body;
}

function iris_tk_load_comments(taskId) {
    // In-flight is tracked separately: assigning `undefined` to the cache is
    // indistinguishable from "absent", so it cannot act as a marker and every
    // re-render would fire another request.
    if (IRIS_TK.comments[taskId] !== undefined || IRIS_TK.loading[taskId]) { return; }
    IRIS_TK.loading[taskId] = true;
    get_request_api(`/case/tasks/${taskId}/comments/list`)
    .always(function () { delete IRIS_TK.loading[taskId]; })
    .done(function (data) {
        IRIS_TK.comments[taskId] = (data && data.data) ? data.data : [];
        if (IRIS_TK.sel === taskId && IRIS_TK.tab === 'comments') { iris_tk_render_detail(); }
    })
    .fail(function () {
        // null = looked and failed, which is not the same as [] = none.
        IRIS_TK.comments[taskId] = null;
        if (IRIS_TK.sel === taskId && IRIS_TK.tab === 'comments') { iris_tk_render_detail(); }
    });
}

function iris_tk_post_comment(taskId) {
    const $box = $('#iris-tk-comment-input');
    const text = ($box.val() || '').trim();
    if (!text) { return; }
    post_request_api(`/case/tasks/${taskId}/comments/add`, JSON.stringify({
        comment_text: text,
        csrf_token: $('#csrf_token').val()
    }))
    .done(function (data) {
        if (notify_auto_api(data)) {
            delete IRIS_TK.comments[taskId];
            iris_tk_load_comments(taskId);
        }
    });
}

/*
 * Fit the detail card to the space available.
 *
 * The card is `position: sticky`, so it only sits at its `top:` once PINNED -
 * at rest it starts wherever the page has scrolled to, and a fixed-offset
 * calc overshoots by exactly that difference. So measure. The floor is the
 * chat bar's INPUT ROW, not the bar itself: the conversation panel opens
 * upward above that row, and following it would relayout the whole card every
 * time the analyst opens the assistant.
 */
function iris_tk_fit_card() {
    const card = document.querySelector('.iris-tk-right');
    if (!card || card.offsetParent === null) { return; }
    const top = card.getBoundingClientRect().top;
    const form = document.getElementById('iris-chat-form');
    let limit;
    if (form && form.getBoundingClientRect().height > 0) {
        limit = form.getBoundingClientRect().top;
    } else {
        limit = (window.innerHeight || 800) - 18;
    }
    const h = Math.max(220, Math.round(limit - top - IRIS_TASK_BOARD_GAP)) + 'px';
    // write-only-on-change: an unchanged write still invalidates layout,
    // forcing the next geometry read (ours or jQuery's) to reflow
    if (card.style.height !== h) { card.style.height = h; }
}
window.irisTaskCardsFit = iris_tk_fit_card;

/* Pull every link in the case in one round-trip, then (re)draw the tree. */
function fetch_task_links_then_render() {
    fetch_task_links(render_task_tree);
}

/* One round-trip for every link in the case, shared by the dependency tree and
 * the card view's Linked tasks block so the two cannot disagree. */
function fetch_task_links(after) {
    if (g_task_links_inflight) { return; }
    g_task_links_inflight = true;
    let cid = get_caseid();
    get_request_api(`/api/v2/cases/${cid}/tasks/links`)
    .always(() => { g_task_links_inflight = false; })
    .done((data) => {
        // v2 endpoint returns the payload directly (no {status,data} wrapper).
        let payload = (data && data.links !== undefined) ? data : (data && data.data ? data.data : data);
        g_task_links = (payload && payload.links) ? payload.links : [];
        g_task_links_loaded = true;
        g_task_links_failed = false;
        if (after) { after(); }
    })
    .fail(() => {
        // Failed is not the same as none: the panel says so rather than
        // reporting a task as having no dependencies.
        g_task_links_failed = true;
        g_task_links_loaded = false;
        if (after) { after(); }
    });
}

/* Build a status badge identical to the flat table's. */
function tree_status_badge(task) {
    if (!task || task.status_name === undefined) { return ''; }
    return '<span class="badge badge-' + sanitizeHTML(task.status_bscolor || 'secondary') +
           '">' + sanitizeHTML(task.status_name) + '</span>';
}

/*
 * Render both dependency graphs (blocks / depends_on) as indented trees.
 *
 * Roots = tasks that are a parent in at least one edge but never a child
 * of the same link_type (so the top of each chain). A task with no links
 * of a given type does not appear in that graph. Multiple-parent edges
 * (a DAG, not a strict tree) are rendered under every parent; a cycle is
 * broken by not re-descending into a node already on the current path,
 * with the repeat marked "(cycle)".
 */
function render_task_tree() {
    if (g_task_view !== 'tree') { return; }

    // Index the current task rows (tasks_list is populated by get_tasks()).
    g_tasks_by_id = {};
    if (typeof tasks_list !== 'undefined' && tasks_list) {
        tasks_list.forEach(function (t) { g_tasks_by_id[t.task_id] = t; });
    }

    ['blocks', 'depends_on'].forEach(function (lt) {
        const edges = g_task_links.filter(function (l) { return l.link_type === lt; });
        const $container = (lt === 'blocks') ? $('#iris-task-tree-blocks') : $('#iris-task-tree-depends');
        $container.empty();

        if (edges.length === 0) {
            $container.append('<div class="iris-tree-empty">No ' +
                (lt === 'blocks' ? 'blocking' : 'dependency') + ' relationships in this case.</div>');
            return;
        }

        // Adjacency: parent -> [children]; track which ids are ever a child.
        const children = {};
        const isChild = {};
        edges.forEach(function (e) {
            (children[e.from_task_id] = children[e.from_task_id] || []).push(e.to_task_id);
            isChild[e.to_task_id] = true;
        });

        // Roots: any node that is a parent but never a child of this type.
        const rootSet = {};
        Object.keys(children).forEach(function (pid) {
            if (!isChild[pid]) { rootSet[pid] = true; }
        });
        // Pure cycle with no acyclic root: fall back to every parent node.
        let roots = Object.keys(rootSet).map(Number);
        if (roots.length === 0) {
            roots = Object.keys(children).map(Number);
        }
        roots.sort(function (a, b) { return a - b; });

        roots.forEach(function (rootId) {
            $container.append(build_tree_node(lt, rootId, children, []));
        });
    });
}

/* Recursively build one node (+ its children) as DOM. `path` carries the
 * ancestor chain for cycle detection. */
function build_tree_node(graph, taskId, children, path) {
    const task = g_tasks_by_id[taskId];
    const onPath = path.indexOf(taskId) !== -1;
    const kids = (children[taskId] || []).slice().sort(function (a, b) { return a - b; });
    const hasKids = kids.length > 0 && !onPath;

    const $node = $('<div>').addClass('iris-tree-node');

    const $row = $('<div>').addClass('iris-tree-row').attr('data-task_id', taskId);
    if (onPath) { $row.addClass('iris-tree-cycle'); }

    const collapseKey = graph + ':' + taskId;
    const collapsed = !!g_tree_collapsed[collapseKey];

    const $toggle = $('<span>').addClass('iris-tree-toggle');
    if (hasKids) {
        $toggle.html(collapsed ? '<i class="fa-solid fa-caret-right"></i>'
                               : '<i class="fa-solid fa-caret-down"></i>');
        $toggle.on('click', function (ev) {
            ev.stopPropagation();
            g_tree_collapsed[collapseKey] = !g_tree_collapsed[collapseKey];
            render_task_tree();
        });
    } else {
        $toggle.addClass('iris-tree-leaf');
    }
    $row.append($toggle);

    $row.append($('<span>').addClass('iris-tree-id').text('#' + taskId));

    const title = task ? (task.task_title || '(untitled)') : ('(task ' + taskId + ' not in list)');
    const $title = $('<span>').addClass('iris-tree-title')
        .text(title + (onPath ? '  ↻ (cycle)' : ''))
        .attr('title', title);
    $row.append($title);

    if (task) {
        $row.append($('<span>').addClass('iris-tree-status').html(tree_status_badge(task)));
    }

    // Clicking a row (not the toggle) opens the task editor.
    $row.on('click', function () { edit_task(taskId); });
    $node.append($row);

    if (hasKids) {
        const $children = $('<div>').addClass('iris-tree-children');
        if (collapsed) { $children.addClass('iris-collapsed'); }
        const nextPath = path.concat([taskId]);
        kids.forEach(function (cid) {
            $children.append(build_tree_node(graph, cid, children, nextPath));
        });
        $node.append($children);
    }

    return $node;
}

function edit_in_task_desc() {
    if($('#container_task_desc_content').is(':visible')) {
        $('#container_task_description').show(100);
        $('#container_task_desc_content').hide(100);
        $('#task_edition_btn').hide(100);
        $('#task_preview_button').hide(100);
    } else {
        $('#task_preview_button').show(100);
        $('#task_edition_btn').show(100);
        $('#container_task_desc_content').show(100);
        $('#container_task_description').hide(100);
    }
}


/* Fetch a modal that allows to add an event */
function add_task() {
    url = 'tasks/add/modal' + case_param();
    $('#modal_add_task_content').load(url, function (response, status, xhr) {
        hide_minimized_modal_box();
        if (status !== "success") {
             ajax_notify_error(xhr, url);
             return false;
        }
        
        g_task_desc_editor = get_new_ace_editor('task_description', 'task_desc_content', 'target_task_desc',
                            function() {
                                $('#last_saved').addClass('btn-danger').removeClass('btn-success');
                                $('#last_saved > i').attr('class', "fa-solid fa-file-circle-exclamation");
                            }, null);
        g_task_desc_editor.setOption("minLines", "10");
        edit_in_task_desc();

        headers = get_editor_headers('g_task_desc_editor', null, 'task_edition_btn');
        $('#task_edition_btn').append(headers);

        $('#submit_new_task').on("click", function () {

            clear_api_error();
            if(!$('form#form_new_task').valid()) {
                return false;
            }

            var data_sent = $('#form_new_task').serializeObject();
            data_sent['task_tags'] = $('#task_tags').val();
            data_sent['task_assignees_id'] = $('#task_assignees_id').val();
            data_sent['task_status_id'] = $('#task_status_id').val();
            data_sent['task_description'] = g_task_desc_editor.getValue();
            ret = get_custom_attributes_fields();
            has_error = ret[0].length > 0;
            attributes = ret[1];

            if (has_error){return false;}

            data_sent['custom_attributes'] = attributes;
            case_id =  get_caseid()
            post_request_api(`/api/v2/cases/${case_id}/tasks`, JSON.stringify(data_sent), true)
            .done((data, textStatus) => {
                if(textStatus === 'success') {
                    get_tasks();
                    $('#modal_add_task').modal('hide');
                }
            });

            return false;
        })
        $('#modal_add_task').modal({ show: true });
        $('#task_title').focus();

    });

}

function save_task() {
    $('#submit_new_task').click();
}

function update_task(task_id) {
    update_task_ext(task_id, true);
}

function update_task_ext(task_id, do_close) {

    clear_api_error();
    if(!$('form#form_new_task').valid()) {
        return false;
    }

    if (task_id === undefined || task_id === null) {
        task_id = g_task_id;
    }

    var data_sent = $('#form_new_task').serializeObject();
    data_sent['task_tags'] = $('#task_tags').val();

    data_sent['task_assignees_id'] = $('#task_assignees_id').val();
    data_sent['task_status_id'] = $('#task_status_id').val();
    ret = get_custom_attributes_fields();
    has_error = ret[0].length > 0;
    attributes = ret[1];

    if (has_error){return false;}

    data_sent['custom_attributes'] = attributes;
    data_sent['task_description'] = g_task_desc_editor.getValue();

    $('#update_task_btn').text('Updating..');

    post_request_api(`/case/tasks/update/${task_id}`, JSON.stringify(data_sent), true)
    .done((data) => {
        if(notify_auto_api(data)) {
            get_tasks();
            $('#submit_new_task').text("Saved").addClass('btn-outline-success').removeClass('btn-outline-danger').removeClass('btn-outline-warning');
            $('#last_saved').removeClass('btn-danger').addClass('btn-success');
            $('#last_saved > i').attr('class', "fa-solid fa-file-circle-check");

            if (do_close !== undefined && do_close === true) {
                $('#modal_add_task').modal('hide');
            }
        }
    })
    .always(() => {
        $('#update_task_btn').text('Update');
    });
}

/* Delete an event from the timeline thank to its id */ 
function delete_task(id) {
    do_deletion_prompt("You are about to delete task #" + id)
    .then((doDelete) => {
        if (doDelete) {
            let cid = get_caseid();
            delete_request_api(`/api/v2/cases/${cid}/tasks/${id}`)
            .done((data, textStatus) => {
                 if (textStatus === 'nocontent') {
                    get_tasks();
                    $('#modal_add_task').modal('hide');
                    notify_success('Task deleted');
                } else {
                     notify_error('Error deleting task')
                 }
            });
        }
    });
}

/* Edit and event from the timeline thanks to its ID */
function edit_task(id) {
  url = `/case/tasks/${id}/modal${case_param()}`;
  $('#modal_add_task_content').load(url, function (response, status, xhr) {
        hide_minimized_modal_box();
        if (status !== "success") {
             ajax_notify_error(xhr, url);
             return false;
        }

        g_task_id = id;

        g_task_desc_editor = get_new_ace_editor('task_description', 'task_desc_content', 'target_task_desc',
                            function() {
                                $('#last_saved').addClass('btn-danger').removeClass('btn-success');
                                $('#last_saved > i').attr('class', "fa-solid fa-file-circle-exclamation");
                            }, null);

        g_task_desc_editor.setOption("minLines", "6");
        preview_task_description(true);

        headers = get_editor_headers('g_task_desc_editor', null, 'task_edition_btn');
        $('#task_edition_btn').append(headers);

        load_menu_mod_options_modal(id, 'task', $("#task_modal_quick_actions"));
        $('#modal_add_task').modal({show:true});
        edit_in_task_desc();
  });
}

function preview_task_description(no_btn_update) {
    if(!$('#container_task_description').is(':visible')) {
        task_desc = g_task_desc_editor.getValue();
        converter = get_showdown_convert();
        html = converter.makeHtml(do_md_filter_xss(task_desc));
        task_desc_html = do_md_filter_xss(html);
        $('#target_task_desc').html(task_desc_html);
        $('#container_task_description').show();
        if (!no_btn_update) {
            $('#task_preview_button').html('<i class="fa-solid fa-eye-slash"></i>');
        }
        $('#container_task_desc_content').hide();
    }
    else {
        $('#container_task_description').hide();
         if (!no_btn_update) {
            $('#task_preview_button').html('<i class="fa-solid fa-eye"></i>');
        }

        $('#task_preview_button').html('<i class="fa-solid fa-eye"></i>');
        $('#container_task_desc_content').show();
    }
}

/* Fetch and draw the tasks */
function get_tasks() {
    $('#tasks_list').empty();
    show_loader();
    // A refresh follows an edit as often as not, and links may have changed
    // in the modal - drop the cached graph so the next render re-pulls it.
    g_task_links_loaded = false;
    g_task_links_failed = false;

    get_request_api('/case/tasks/list')
    .done((data) => {
        if (data.status == 'success') {
                Table.MakeCellsEditable("destroy");
                tasks_list = data.data.tasks;

                options_l = data.data.tasks_status;
                // iris-next: the board builds its columns from this catalog.
                g_task_status_catalog = options_l || [];
                options = [];
                for (index in options_l) {
                    option = options_l[index];
                    options.push({ "value": option.id, "display": option.status_name })
                }
                Table.clear();
                Table.rows.add(tasks_list);
                Table.MakeCellsEditable({
                    "onUpdate": callBackEditTaskStatus,
                    "inputCss": 'form-control col-12',
                    "columns": [2],
                    "allowNulls": {
                      "columns": [2],
                      "errorClass": 'error'
                    },
                    "confirmationButton": {
                      "confirmCss": 'my-confirm-class',
                      "cancelCss": 'my-cancel-class'
                    },
                    "inputTypes": [
                      {
                        "column": 2,
                        "type": "list",
                        "options": options
                      }
                    ]
                  });

                Table.columns.adjust().draw();
                load_menu_mod_options('task', Table, delete_task);
                //$('[data-toggle="popover"]').popover();
                Table.responsive.recalc();

                $(document)
                    .off('click', '.task_details_link')
                    .on('click', '.task_details_link', function(event) {
                    event.preventDefault();
                    let task_id = $(this).data('task_id');
                    edit_task(task_id);
                });

                set_last_state(data.data.state);
                hide_loader();

                // iris-next: re-assert the active view with the freshly-loaded
                // rows. hide_loader() force-shows #card_main_load, so without
                // this a refresh drops the analyst back onto the table.
                apply_task_view();
            }

    });
}

function refresh_users(on_finish, cur_assignees_id_list) {

    get_request_api('/case/users/list')
    .done((data) => {
        if (api_request_failed(data)) {
            return;
        }

        current_users_list = data.data;
        if (on_finish !== undefined) {
            on_finish(current_users_list, cur_assignees_id_list);
        }
    });

}

function do_list_users(list_users, cur_assignees_id_list) {

    $('#task_assignees_id').selectpicker({
        liveSearch: true,
        title: "Select assignee(s)"
    });

    for (let user in list_users) {
        if (list_users[user].user_access_level === 4) {
            $('#task_assignees_id').append(new Option(`${filterXSS(list_users[user].user_login)} (${filterXSS(list_users[user].user_name)})`,
                list_users[user].user_id));
        }
    }

    if (cur_assignees_id_list !== undefined) {
        $('#task_assignees_id').selectpicker('val', cur_assignees_id_list);
    }

    $('#task_assignees_id').selectpicker('refresh');
}

function callBackEditTaskStatus(updatedCell, updatedRow, oldValue) {
  data_send = updatedRow.data();
  data_send['csrf_token'] = $('#csrf_token').val();
  tid = data_send['task_id'];

  post_request_api(`/case/tasks/status/update/${tid}`, JSON.stringify(data_send))
  .done(function (data){
    if(notify_auto_api(data)) {
         get_tasks();
    }
  });
}

/* iris-next: called by the shell header menu's "Export to CSV" item — it
 * triggers the hidden DataTables csvHtml5 button, so the export is the same
 * one the old toolbar strip produced (works from any of the four views; the
 * DataTable holds the data whether or not the flat table is displayed). */
function iris_tasks_export_csv() {
    $('#tasks_table').DataTable().button('.buttons-csv').trigger();
}

/* Page is ready, fetch the assets of the case */
$(document).ready(function(){

    /* add filtering fields for each table of the page (must be done before datatable initialization) */
    $.each($.find("table"), function(index, element){
        addFilterFields($(element).attr("id"));
    });

    Table = $("#tasks_table").DataTable({
        dom: '<"container-fluid"<"row"<"col"l><"col"f>>>rt<"container-fluid"<"row"<"col"i><"col"p>>>',
        aaData: [],
        fixedHeader: true,
        aoColumns: [
          {
            "data": "task_title",
            "render": function (data, type, row, meta) {
              if (type === 'display' && data != null) {

                let datak = '';
                let anchor = $('<a>')
                    .attr('href', 'javascript:void(0);')
                    .attr('data-task_id', row['task_id'])
                    .attr('title', `Task ID #${row['task_id']} - ${data}`)
                    .addClass('task_details_link')

                if (isWhiteSpace(data)) {
                    datak = '#' + row['task_id'];
                    anchor.text(datak);
                } else {
                    datak= ellipsis_field(data, 64);
                    anchor.html(datak);
                }

                return anchor.prop('outerHTML');
              }
              return data;
            }
          },
          { "data": "task_description",
           "render": function (data, type, row, meta) {
              if (type === 'display') {
                  return ret_obj_dt_description(data);
              }
              return data;
            }
          },
          {
            "data": "task_status_id",
            "render": function(data, type, row) {
               if (type === 'display') {
                  data = sanitizeHTML(data);
                  data = '<span class="badge ml-2 badge-'+ row['status_bscolor'] +'">' + row['status_name'] + '</span>';
               }
               else if (type === 'filter' || type === 'sort'){
                  data = row['status_name']
               } else if (type === 'export') {
                   data = row['status_name']
                }
              return data;
            }
          },
          {
            "data": "task_assignees",
            "render": function (data, type, row, meta) {
                if (data != null) {
                    names = "";

                    if (data.length > 0) {
                        lst = [];
                        data.forEach(function (item, index) { lst.push(item['name']); });
                        if (type === 'display') {
                            names = list_to_badges(lst, 'primary', 10, 'users');
                        }
                        else {
                            lst.forEach(function (item, index) {
                                names += `${sanitizeHTML(item)}`;
                            });
                        }
                    }
                    else {
                        if (type === 'display') {
                            names = '<span class="badge badge-light ml-2">' + "Unassigned" + '</span>';
                        }
                        else {
                            names = "Unassigned";
                        }
                    }

                    return names;

                }
                return data;

            }
          },
          {
            "data": "task_open_date",
            "render": function (data, type, row, meta) {
                if (type === 'display' && data != null) {
                    /* task_open_date is naive-UTC storage with no offset, and
                     * formatTime() runs it through new Date(), which reads it
                     * as browser-local and shifts it by the analyst's offset.
                     * Label the stored value instead - and the board shows the
                     * same field, so both views must agree. Sort and export
                     * paths below still get the raw ISO. */
                    return iris_task_utc_label(data, true) || data;
                }
                return data;
            }
          },
          { "data": "task_tags",
            "render": function (data, type, row, meta) {
              if (type === 'display' && data != null) {
                  let datas = "";
                  let de = data.split(',');
                  for (let tag in de) {
                    datas += get_tag_from_data(de[tag], 'badge badge-light ml-2');
                }
                return datas;
              }
              return data;
            }
          }
        ],
        rowCallback: function (nRow, data) {
            nRow = '<span class="badge ml-2 badge-'+ sanitizeHTML(data['status_bscolor']) +'">' + sanitizeHTML(data['status_name']) + '</span>';
        },
        filter: true,
        info: true,
        ordering: true,
        processing: true,
        retrieve: true,
        pageLength: 50,
        order: [[ 2, "asc" ]],
        buttons: [
        ],
        responsive: {
            details: {
                display: $.fn.dataTable.Responsive.display.childRow,
                renderer: $.fn.dataTable.Responsive.renderer.tableAll()
            }
        },
        orderCellsTop: true,
        initComplete: function () {
            tableFiltering(this.api(), 'tasks_table');
        },
        select: true
    });
    $("#tasks_table").css("font-size", 12);

    Table.on( 'responsive-resize', function ( e, datatable, columns ) {
            hide_table_search_input( columns );
    });

    /* iris-next: the visible button strip is retired — the CSV export moved
     * into the case shell's header menu (Export to CSV), which triggers this
     * hidden DataTables button so the export machinery is unchanged. The
     * copy + colvis buttons were removed outright. */
    var buttons = new $.fn.dataTable.Buttons(Table, {
         buttons: [
            { "extend": 'csvHtml5', "text":'<i class="fas fa-cloud-download-alt"></i>',"className": 'btn btn-link text-white'
            , "titleAttr": 'Download as CSV', "exportOptions": { "columns": ':visible', 'orthogonal':  'export' } }
        ]
    }).container().appendTo($('#tables_button'));

    /* iris-next: restore the analyst's last view before the first draw, so a
     * board user is not bounced back to the table on every page load. */
    try {
        const saved = localStorage.getItem(IRIS_TASK_VIEW_KEY);
        if (saved && IRIS_TASK_VIEWS.indexOf(saved) !== -1) { g_task_view = saved; }
    } catch (e) { /* private mode: fall back to the table */ }

    /* Keep the board fitted to the space available. The chat bar changes
     * height when expanded and the case header hydrates after first paint, so
     * watch both rather than measuring once. */
    let boardFitPending = false;
    const scheduleBoardFit = function () {
        if (boardFitPending) { return; }
        boardFitPending = true;
        window.requestAnimationFrame(function () {
            boardFitPending = false;
            iris_task_board_sync_height();
        });
    };
    const scheduleFits = function () {
        scheduleBoardFit();
        iris_tk_fit_card();
    };
    window.addEventListener('resize', scheduleFits);
    window.addEventListener('scroll', scheduleFits, {passive: true});
    if (window.ResizeObserver) {
        const ro = new window.ResizeObserver(scheduleFits);
        ['iris-chat', 'iris-chat-form', 'iris-cshell', 'iris-task-board-hint']
            .forEach(function (id) {
                const el = document.getElementById(id);
                if (el) { ro.observe(el); }
            });
    }

    /* Card view: pick a task to open it in the display/edit panel. */
    $(document).on('click', '#iris-tk-list .iris-tk-row', function () {
        IRIS_TK.sel = parseInt($(this).attr('data-task_id'), 10);
        IRIS_TK.tab = 'details';
        IRIS_TK.editing = false;   // switching task discards an edit
        render_task_cards();
    });
    /* A linked task opens in the same panel - no dead links, no navigation. */
    $(document).on('click', '#iris-tk-detail .iris-tk-linkitem', function () {
        const id = parseInt($(this).attr('data-task_id'), 10);
        if (!iris_tk_by_id(id)) { return; }   // not in this list - nothing to open
        IRIS_TK.sel = id;
        IRIS_TK.tab = 'details';
        IRIS_TK.editing = false;
        render_task_cards();
    });
    $(document).on('input', '#iris-tk-search', function () {
        IRIS_TK.search = $(this).val() || '';
        render_task_cards();
    });

    /* Board: click a card to open the task editor. */
    $(document).on('click', '#iris-task-board .iris-tb-card', function () {
        edit_task(parseInt($(this).attr('data-task_id'), 10));
    });

    /* Board drag-and-drop. The drop target is the column, so dropping on a
     * card inside it works too (closest() walks up). */
    $(document).on('dragstart', '#iris-task-board .iris-tb-card[draggable]', function (e) {
        const dt = e.originalEvent.dataTransfer;
        dt.setData('text/plain', $(this).attr('data-task_id'));
        dt.effectAllowed = 'move';
        $(this).addClass('iris-tb-dragging');
    });
    $(document).on('dragend', '#iris-task-board .iris-tb-card', function () {
        $(this).removeClass('iris-tb-dragging');
        $('#iris-task-board .iris-tb-col').removeClass('dragover');
    });
    $(document).on('dragover', '#iris-task-board .iris-tb-col[data-droppable]', function (e) {
        e.preventDefault();
        e.originalEvent.dataTransfer.dropEffect = 'move';
        $(this).addClass('dragover');
    });
    $(document).on('dragleave', '#iris-task-board .iris-tb-col', function (e) {
        // Only clear when the pointer really left the column, not when it
        // crossed onto a card inside it.
        if (!this.contains(e.originalEvent.relatedTarget)) {
            $(this).removeClass('dragover');
        }
    });
    $(document).on('drop', '#iris-task-board .iris-tb-col[data-droppable]', function (e) {
        e.preventDefault();
        $(this).removeClass('dragover');
        const task_id = parseInt(e.originalEvent.dataTransfer.getData('text/plain'), 10);
        const status_id = parseInt($(this).attr('data-status_id'), 10);
        if (!task_id || !status_id) { return; }
        board_set_task_status(task_id, status_id);
    });

    get_tasks();

    setInterval(function() { check_update('/case/tasks/state'); }, 3000);

    shared_id = getSharedLink();
    if (shared_id) {
        edit_task(shared_id);
    }
});

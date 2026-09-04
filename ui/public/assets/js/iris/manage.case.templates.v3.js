/* iris-ng: v3-parity Case Templates view (template list + Form / Raw JSON /
 * Schema editor).
 *
 * Overlay, not rebuild: the list renders from the SAME
 * /manage/case-templates/list the legacy DataTable calls, the editor loads
 * from the additive GET /manage/case-templates/<id> (same builder as the
 * legacy modal), and Save / Add / Delete / Import drive the SAME endpoints
 * and payload keys as manage.case.templates.js (delete reuses its
 * delete_case_template, Import its fire_upload_case_template). Loaded AFTER
 * manage.case.templates.js.
 *
 * The Form tab and the Raw JSON tab edit ONE model object; leaving the Raw
 * tab (or saving from it) parses the editor back into the model, and invalid
 * JSON refuses the switch rather than silently dropping edits.
 */

var IRIS_CT = {
    rows: null, fetching: false, failed: null,
    selected: null, model: null, snapshot: '',
    raw: null, activeTab: 'form',
    search: '', classifications: null
};

function iris_ct_esc(s) {
    return $('<div>').text(s === null || s === undefined ? '' : String(s)).html();
}

function iris_ct_normalize(d) {
    d = (d && typeof d === 'object' && !Array.isArray(d)) ? d : {};
    var m = {
        name: String(d.name || ''),
        display_name: String(d.display_name || ''),
        description: String(d.description || ''),
        author: String(d.author || ''),
        title_prefix: String(d.title_prefix || ''),
        summary: String(d.summary || ''),
        tags: Array.isArray(d.tags) ? d.tags.map(String) : [],
        classification: String(d.classification || ''),
        tasks: [],
        note_directories: []
    };
    (Array.isArray(d.tasks) ? d.tasks : []).forEach(function (t) {
        t = (t && typeof t === 'object') ? t : {};
        m.tasks.push({
            title: String(t.title || ''),
            description: String(t.description || ''),
            tags: Array.isArray(t.tags) ? t.tags.map(String) : []
        });
    });
    (Array.isArray(d.note_directories) ? d.note_directories : []).forEach(function (nd) {
        nd = (nd && typeof nd === 'object') ? nd : {};
        var out = { title: String(nd.title || ''), notes: [] };
        (Array.isArray(nd.notes) ? nd.notes : []).forEach(function (n) {
            n = (n && typeof n === 'object') ? n : {};
            out.notes.push({ title: String(n.title || ''), content: String(n.content || '') });
        });
        m.note_directories.push(out);
    });
    return m;
}

function iris_ct_fetch(force) {
    if (IRIS_CT.fetching) { return; }
    if (!force && Array.isArray(IRIS_CT.rows)) { return; }
    IRIS_CT.fetching = true;
    IRIS_CT.failed = null;
    iris_ct_render_rows();
    get_request_api('/manage/case-templates/list')
    .done(function (data) {
        IRIS_CT.rows = (data && data.data) ? data.data : [];
    })
    .fail(function (xhr) {
        IRIS_CT.failed = 'HTTP ' + (xhr && xhr.status ? xhr.status : '?');
    })
    .always(function () {
        IRIS_CT.fetching = false;
        iris_ct_render_rows();
        if (Array.isArray(IRIS_CT.rows) && IRIS_CT.rows.length
                && IRIS_CT.selected === null) {
            iris_ct_select(IRIS_CT.rows[0].id);
        }
    });
}

function iris_ct_filtered() {
    var rows = IRIS_CT.rows || [];
    var q = (IRIS_CT.search || '').toLowerCase();
    if (!q) { return rows; }
    return rows.filter(function (r) {
        return [r.name, r.display_name, r.description, r.author].some(function (v) {
            return v !== null && v !== undefined
                && String(v).toLowerCase().indexOf(q) !== -1;
        });
    });
}

function iris_ct_render_rows() {
    var $l = $('#iris-ct-rows');
    if (IRIS_CT.failed) {
        $('#iris-ct-count').text('');
        $l.html('<div class="iris-co-empty">Could not load templates ('
            + iris_ct_esc(IRIS_CT.failed) + '). Refresh to retry.</div>');
        return;
    }
    if (!Array.isArray(IRIS_CT.rows)) {
        $('#iris-ct-count').text('');
        $l.html('<div class="iris-co-empty">Loading…</div>');
        return;
    }
    var all = IRIS_CT.rows;
    var shown = iris_ct_filtered();
    $('#iris-ct-count').text(shown.length + ' / ' + all.length);
    if (!all.length) {
        $l.html('<div class="iris-co-empty">No templates yet — click + Add template to create one.</div>');
        return;
    }
    if (!shown.length) {
        $l.html('<div class="iris-co-empty">No match for the current search.</div>');
        return;
    }
    var html = '';
    shown.forEach(function (r) {
        html += '<div class="iris-ct-row'
            + (String(r.id) === String(IRIS_CT.selected) ? ' active' : '')
            + '" data-id="' + iris_ct_esc(r.id) + '">'
            + '<div><div class="iris-ct-row-name">'
            + iris_ct_esc(r.display_name || r.name) + '</div>'
            + (r.description
                ? '<div class="iris-ct-row-sub">' + iris_ct_esc(r.description) + '</div>' : '')
            + '</div>'
            + '<span class="iris-ct-row-id">#' + iris_ct_esc(r.id) + '</span>'
            + '</div>';
    });
    $l.html(html);
}

/* ---- one-model serialization ------------------------------------------- */

function iris_ct_serialized() {
    if (IRIS_CT.activeTab === 'raw' && IRIS_CT.raw) {
        try {
            return JSON.stringify(iris_ct_normalize(JSON.parse(IRIS_CT.raw.getSession().getValue())));
        } catch (e) {
            return '<invalid json>';
        }
    }
    return JSON.stringify(IRIS_CT.model);
}

function iris_ct_dirty() {
    return IRIS_CT.model !== null && iris_ct_serialized() !== IRIS_CT.snapshot;
}

/* Pull the Raw JSON editor back into the model. Returns false (and reports)
 * when the JSON does not parse — the caller must abort what it was doing. */
function iris_ct_sync_from_raw() {
    if (IRIS_CT.activeTab !== 'raw' || !IRIS_CT.raw) { return true; }
    try {
        IRIS_CT.model = iris_ct_normalize(JSON.parse(IRIS_CT.raw.getSession().getValue()));
        return true;
    } catch (e) {
        notify_error('Invalid JSON — fix the Raw JSON tab first.');
        return false;
    }
}

/* ---- selection --------------------------------------------------------- */

function iris_ct_select(tid) {
    if (String(tid) === String(IRIS_CT.selected)) { return; }
    if (iris_ct_dirty() && !confirm('Discard unsaved template changes?')) { return; }
    IRIS_CT.selected = tid;
    iris_ct_render_rows();
    get_request_api('/manage/case-templates/' + tid)
    .done(function (data) {
        if (String(IRIS_CT.selected) !== String(tid)) { return; }
        var d = (data && data.data) ? data.data : {};
        IRIS_CT.model = iris_ct_normalize(d);
        IRIS_CT.snapshot = JSON.stringify(IRIS_CT.model);
        $('#iris-ct-editor-empty').hide();
        $('#iris-ct-editor-wrap').show();
        $('#iris-ct-sel-label').text((IRIS_CT.model.display_name || IRIS_CT.model.name)
            + ' · #' + tid);
        $('#iris-ct-errors').hide();
        iris_ct_render_form();
        if (IRIS_CT.activeTab === 'raw') {
            IRIS_CT.raw.getSession().setValue(JSON.stringify(IRIS_CT.model, null, 4));
            iris_ct_render_valid();
        }
    })
    .fail(function (xhr) {
        $('#iris-ct-editor-empty').show().text('Could not load template #' + tid
            + ' (HTTP ' + (xhr && xhr.status ? xhr.status : '?') + ').');
        $('#iris-ct-editor-wrap').hide();
    });
}

/* ---- form rendering ----------------------------------------------------- */

function iris_ct_render_form() {
    var m = IRIS_CT.model;
    $('#iris-ct-f-name').val(m.name);
    $('#iris-ct-f-display').val(m.display_name);
    $('#iris-ct-f-description').val(m.description);
    $('#iris-ct-f-author').val(m.author);
    $('#iris-ct-f-prefix').val(m.title_prefix);
    $('#iris-ct-f-summary').val(m.summary);
    $('#iris-ct-f-classification').val(m.classification);
    $('#iris-ct-f-tag-input').val('');
    iris_ct_render_tags();
    iris_ct_render_notedirs();
    iris_ct_render_tasks();
}

function iris_ct_render_tags() {
    var $c = $('#iris-ct-tags-chips').empty();
    IRIS_CT.model.tags.forEach(function (t, i) {
        $c.append($('<span class="iris-ct-chip">').text(t)
            .append($('<span data-i="' + i + '">').text(' ×')));
    });
}

function iris_ct_render_notedirs() {
    var dirs = IRIS_CT.model.note_directories;
    $('#iris-ct-notedirs-count').text(dirs.length);
    var $c = $('#iris-ct-notedirs').empty();
    if (!dirs.length) {
        $c.append($('<div class="iris-co-empty">').text('Nothing yet — click Add to insert one.'));
        return;
    }
    dirs.forEach(function (nd, di) {
        var $item = $('<div class="iris-ct-item">');
        var $head = $('<div class="iris-ct-item-head">');
        $head.append($('<input type="text" class="form-control form-control-sm iris-ct-nd-title" placeholder="Directory title *">')
            .attr('data-di', di).val(nd.title));
        $head.append($('<button type="button" class="btn btn-sm btn-dark iris-ct-note-add">').attr('data-di', di).text('+ Add note'));
        $head.append($('<span class="iris-ct-x iris-ct-nd-x" title="Remove directory">').attr('data-di', di).text('×'));
        $item.append($head);
        nd.notes.forEach(function (n, ni) {
            var $note = $('<div class="iris-ct-note">');
            var $nh = $('<div class="iris-ct-item-head">');
            $nh.append($('<input type="text" class="form-control form-control-sm iris-ct-n-title" placeholder="Note title *">')
                .attr({'data-di': di, 'data-ni': ni}).val(n.title));
            $nh.append($('<span class="iris-ct-x iris-ct-n-x" title="Remove note">').attr({'data-di': di, 'data-ni': ni}).text('×'));
            $note.append($nh);
            $note.append($('<textarea class="form-control form-control-sm mt-1 iris-ct-n-content" rows="2" placeholder="Note content (markdown)">')
                .attr({'data-di': di, 'data-ni': ni}).val(n.content));
            $item.append($note);
        });
        $c.append($item);
    });
}

function iris_ct_render_tasks() {
    var tasks = IRIS_CT.model.tasks;
    $('#iris-ct-tasks-count').text(tasks.length);
    var $c = $('#iris-ct-tasks').empty();
    if (!tasks.length) {
        $c.append($('<div class="iris-co-empty">').text('Nothing yet — click Add to insert one.'));
        return;
    }
    tasks.forEach(function (t, ti) {
        var $item = $('<div class="iris-ct-item">');
        var $head = $('<div class="iris-ct-item-head">');
        $head.append($('<input type="text" class="form-control form-control-sm iris-ct-t-title" placeholder="Task title *">')
            .attr('data-ti', ti).val(t.title));
        $head.append($('<span class="iris-ct-x iris-ct-t-x" title="Remove task">').attr('data-ti', ti).text('×'));
        $item.append($head);
        $item.append($('<input type="text" class="form-control form-control-sm mt-1 iris-ct-t-desc" placeholder="Description">')
            .attr('data-ti', ti).val(t.description));
        $item.append($('<input type="text" class="form-control form-control-sm mt-1 iris-ct-t-tags" placeholder="Tags, comma-separated">')
            .attr('data-ti', ti).val(t.tags.join(', ')));
        $c.append($item);
    });
}

/* ---- raw JSON tab ------------------------------------------------------- */

function iris_ct_init_raw() {
    if (IRIS_CT.raw) { return; }
    var editor = ace.edit('iris-ct-raw-editor', {
        autoScrollEditorIntoView: true,
        minLines: 18
    });
    editor.setTheme('ace/theme/tomorrow');
    editor.session.setMode('ace/mode/json');
    editor.renderer.setShowGutter(true);
    editor.setOption('showLineNumbers', true);
    editor.setOption('showPrintMargin', false);
    editor.setOption('displayIndentGuides', true);
    editor.setOption('maxLines', 40);
    editor.session.setUseWrapMode(true);
    editor.setOption('indentedSoftWrap', true);
    editor.renderer.setScrollMargin(8, 5);
    editor.setOptions({
        enableBasicAutocompletion: [{
            getCompletions: (editor, session, pos, prefix, callback) => {
                callback(null, [
                    {value: 'name', score: 1, meta: 'name of the template'},
                    {value: 'display_name', score: 1, meta: 'display name of the template'},
                    {value: 'description', score: 1, meta: 'description of the template'},
                    {value: 'author', score: 1, meta: 'author of the template'},
                    {value: 'title_prefix', score: 1, meta: 'prefix of instantiated cases'},
                    {value: 'summary', score: 1, meta: 'summary of the case'},
                    {value: 'tags', score: 1, meta: 'tags of the case or the tasks'},
                    {value: 'tasks', score: 1, meta: 'tasks of the case'},
                    {value: 'classification', score: 1, meta: 'name of a case classification'},
                    {value: 'note_directories', score: 1, meta: 'note directories of the case'},
                    {value: 'notes', score: 1, meta: 'notes of a note directory'},
                    {value: 'title', score: 1, meta: 'title of the task, note directory or note'},
                    {value: 'content', score: 1, meta: 'content of the note'}
                ]);
            }
        }],
        enableLiveAutocompletion: true,
        enableSnippets: true
    });
    editor.getSession().on('change', iris_ct_render_valid);
    IRIS_CT.raw = editor;
}

function iris_ct_render_valid() {
    var $v = $('#iris-ct-valid');
    if (!IRIS_CT.raw) { $v.text('').removeClass('ok bad'); return; }
    try {
        JSON.parse(IRIS_CT.raw.getSession().getValue());
        $v.text('✓ Valid JSON').removeClass('bad').addClass('ok');
    } catch (e) {
        $v.text('✗ Invalid JSON').removeClass('ok').addClass('bad');
    }
}

function iris_ct_switch_tab(tab) {
    if (tab === IRIS_CT.activeTab) { return; }
    // Leaving the raw tab folds the editor back into the model; invalid JSON
    // refuses the switch instead of silently dropping the edits.
    if (!iris_ct_sync_from_raw()) { return; }
    if (IRIS_CT.activeTab === 'raw') { iris_ct_render_form(); }
    IRIS_CT.activeTab = tab;
    $('.iris-ct-tab').removeClass('active');
    $('.iris-ct-tab[data-tab="' + tab + '"]').addClass('active');
    $('#iris-ct-pane-form').toggle(tab === 'form');
    $('#iris-ct-pane-raw').toggle(tab === 'raw');
    $('#iris-ct-pane-schema').toggle(tab === 'schema');
    if (tab === 'raw') {
        iris_ct_init_raw();
        IRIS_CT.raw.getSession().setValue(JSON.stringify(IRIS_CT.model, null, 4));
        iris_ct_render_valid();
    }
}

/* ---- actions: same endpoints + payload keys as the legacy module -------- */

function iris_ct_save() {
    if (IRIS_CT.selected === null || !IRIS_CT.model) { return; }
    if (!iris_ct_sync_from_raw()) { return; }
    var data_sent = Object();
    data_sent['case_template_json'] = JSON.stringify(IRIS_CT.model);
    data_sent['csrf_token'] = $('#csrf_token').val();

    $('#iris-ct-errors').hide();
    $('#iris-ct-errors-msg').empty();
    $('#iris-ct-errors-list').empty();

    post_request_api('/manage/case-templates/update/' + IRIS_CT.selected,
                     JSON.stringify(data_sent), false, function () {
        window.swal({
            title: 'Updating...',
            text: 'Please wait',
            icon: '/static/assets/img/loader.gif',
            button: false,
            allowOutsideClick: false
        });
    })
    .done(function (data) {
        if (api_request_failed(data)) { return; }
        notify_auto_api(data);
        IRIS_CT.snapshot = JSON.stringify(IRIS_CT.model);
        $('#iris-ct-sel-label').text((IRIS_CT.model.display_name || IRIS_CT.model.name)
            + ' · #' + IRIS_CT.selected);
        iris_ct_fetch(true);
    })
    .fail(function (error) {
        var data = (error && error.responseJSON) ? error.responseJSON : {};
        $('#iris-ct-errors-msg').text(data.message || 'Update failed');
        if (data.data) {
            $('#iris-ct-errors-list').append($('<li>').text(String(data.data)));
        }
        $('#iris-ct-errors').show();
    })
    .always(function () {
        window.swal.close();
    });
}

function iris_ct_add() {
    if (iris_ct_dirty() && !confirm('Discard unsaved template changes?')) { return; }
    var stub = iris_ct_normalize({ name: 'new-template', display_name: 'New template' });
    var data_sent = Object();
    data_sent['case_template_json'] = JSON.stringify(stub);
    data_sent['csrf_token'] = $('#csrf_token').val();
    post_request_api('/manage/case-templates/add', JSON.stringify(data_sent))
    .done(function (data) {
        if (api_request_failed(data)) { return; }
        notify_auto_api(data);
        var created = (data && data.data) ? data.data : {};
        IRIS_CT.selected = null;
        IRIS_CT.model = null;
        IRIS_CT.snapshot = '';
        iris_ct_fetch(true);
        if (created.id) { iris_ct_select(created.id); }
    });
}

function iris_ct_export() {
    if (!IRIS_CT.model) { return; }
    var text = (IRIS_CT.activeTab === 'raw' && IRIS_CT.raw)
        ? IRIS_CT.raw.getSession().getValue()
        : JSON.stringify(IRIS_CT.model, null, 4);
    var filename = 'case_template_' + (IRIS_CT.model.name || 'template') + '.json';
    download_file(filename, 'text/json', text);
}

$(function () {
    // Upload success and the legacy Refresh call the legacy refresher; wrap
    // it so the v3 list re-fetches too — one writer, two presentations.
    var origR = window.refresh_case_template_table;
    if (typeof origR === 'function') {
        window.refresh_case_template_table = function () {
            var out = origR.apply(this, arguments);
            iris_ct_fetch(true);
            return out;
        };
    }

    $('#iris-ct-rows').on('click', '.iris-ct-row', function () {
        iris_ct_select($(this).attr('data-id'));
    });
    $('#iris-ct-search').on('input', function () {
        IRIS_CT.search = $(this).val();
        iris_ct_render_rows();
    });
    $('.iris-ct-tab').on('click', function () {
        iris_ct_switch_tab($(this).attr('data-tab'));
    });

    // Static form fields write straight into the model.
    $('#iris-ct-f-name').on('input', function () { IRIS_CT.model.name = $(this).val(); });
    $('#iris-ct-f-display').on('input', function () { IRIS_CT.model.display_name = $(this).val(); });
    $('#iris-ct-f-description').on('input', function () { IRIS_CT.model.description = $(this).val(); });
    $('#iris-ct-f-author').on('input', function () { IRIS_CT.model.author = $(this).val(); });
    $('#iris-ct-f-prefix').on('input', function () { IRIS_CT.model.title_prefix = $(this).val(); });
    $('#iris-ct-f-summary').on('input', function () { IRIS_CT.model.summary = $(this).val(); });
    $('#iris-ct-f-classification').on('input', function () { IRIS_CT.model.classification = $(this).val(); });

    // Tags: Enter adds a chip, × removes.
    $('#iris-ct-f-tag-input').on('keydown', function (e) {
        if (e.key !== 'Enter') { return; }
        e.preventDefault();
        var v = $(this).val().trim();
        if (v && IRIS_CT.model.tags.indexOf(v) === -1) {
            IRIS_CT.model.tags.push(v);
            iris_ct_render_tags();
        }
        $(this).val('');
    });
    $('#iris-ct-tags-chips').on('click', '.iris-ct-chip span', function () {
        IRIS_CT.model.tags.splice(Number($(this).attr('data-i')), 1);
        iris_ct_render_tags();
    });

    // Note directories: text edits update in place, structure edits re-render.
    $('#iris-ct-notedir-add').on('click', function () {
        IRIS_CT.model.note_directories.push({ title: '', notes: [] });
        iris_ct_render_notedirs();
    });
    $('#iris-ct-notedirs')
        .on('input', '.iris-ct-nd-title', function () {
            IRIS_CT.model.note_directories[Number($(this).attr('data-di'))].title = $(this).val();
        })
        .on('click', '.iris-ct-nd-x', function () {
            IRIS_CT.model.note_directories.splice(Number($(this).attr('data-di')), 1);
            iris_ct_render_notedirs();
        })
        .on('click', '.iris-ct-note-add', function () {
            IRIS_CT.model.note_directories[Number($(this).attr('data-di'))].notes
                .push({ title: '', content: '' });
            iris_ct_render_notedirs();
        })
        .on('input', '.iris-ct-n-title', function () {
            IRIS_CT.model.note_directories[Number($(this).attr('data-di'))]
                .notes[Number($(this).attr('data-ni'))].title = $(this).val();
        })
        .on('input', '.iris-ct-n-content', function () {
            IRIS_CT.model.note_directories[Number($(this).attr('data-di'))]
                .notes[Number($(this).attr('data-ni'))].content = $(this).val();
        })
        .on('click', '.iris-ct-n-x', function () {
            IRIS_CT.model.note_directories[Number($(this).attr('data-di'))]
                .notes.splice(Number($(this).attr('data-ni')), 1);
            iris_ct_render_notedirs();
        });

    // Tasks.
    $('#iris-ct-task-add').on('click', function () {
        IRIS_CT.model.tasks.push({ title: '', description: '', tags: [] });
        iris_ct_render_tasks();
    });
    $('#iris-ct-tasks')
        .on('input', '.iris-ct-t-title', function () {
            IRIS_CT.model.tasks[Number($(this).attr('data-ti'))].title = $(this).val();
        })
        .on('input', '.iris-ct-t-desc', function () {
            IRIS_CT.model.tasks[Number($(this).attr('data-ti'))].description = $(this).val();
        })
        .on('input', '.iris-ct-t-tags', function () {
            IRIS_CT.model.tasks[Number($(this).attr('data-ti'))].tags =
                $(this).val().split(',').map(function (t) { return t.trim(); })
                    .filter(function (t) { return t.length > 0; });
        })
        .on('click', '.iris-ct-t-x', function () {
            IRIS_CT.model.tasks.splice(Number($(this).attr('data-ti')), 1);
            iris_ct_render_tasks();
        });

    $('#iris-ct-save').on('click', iris_ct_save);
    $('#iris-ct-add').on('click', iris_ct_add);
    $('#iris-ct-export').on('click', iris_ct_export);
    $('#iris-ct-delete').on('click', function () {
        if (IRIS_CT.selected === null) { return; }
        // The legacy delete: swal confirm + POST + full page reload on success.
        delete_case_template(IRIS_CT.selected);
    });
    $('#iris-ct-refresh').on('click', function () {
        if (iris_ct_dirty() && !confirm('Discard unsaved template changes?')) { return; }
        iris_ct_fetch(true);
    });

    // Classification datalist from the live catalog — fail-soft, the input
    // stays free text either way.
    get_request_api('/manage/case-classifications/list')
    .done(function (data) {
        var rows = (data && data.data) ? data.data : [];
        var $d = $('#iris-ct-classifications').empty();
        rows.forEach(function (r) {
            $d.append($('<option>').attr('value', r.name));
        });
        IRIS_CT.classifications = rows;
    });

    iris_ct_fetch(false);
});

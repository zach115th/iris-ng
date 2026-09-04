/* iris-ng: v3-parity Custom Attributes view (object-type list + schema editor
 * + inline analyst preview).
 *
 * Overlay, not rebuild: everything renders from the SAME
 * /manage/attributes/list payload the legacy DataTable calls (it already
 * carries attribute_content + attribute_for), saves post to the SAME
 * /manage/attributes/update/<id> endpoint with the SAME payload keys as
 * manage.attributes.js::update_attribute, and the preview injects the
 * EXISTING /manage/attributes/preview render inline. Loaded AFTER
 * manage.attributes.js.
 *
 * Absent-data discipline: rows start null ("have not looked"), a failed
 * fetch is recorded separately, and the preview pane distinguishes
 * "nothing selected" / "invalid JSON" / "schema has no tabs" / rendered.
 */

var IRIS_ATTR = {
    rows: null, fetching: false, failed: null,
    selected: null, editor: null,
    loaded: '',
    previewSeq: 0, previewTimer: null
};

/* attribute_for slugs -> the friendly kind subtitle v3 shows. Unknown slugs
 * fall back to the raw value rather than being hidden. */
var IRIS_ATTR_KINDS = {
    'asset': 'Asset', 'case': 'Case', 'client': 'Customer',
    'event': 'Timeline event', 'evidence': 'Evidence',
    'ioc': 'Indicator of Compromise', 'note': 'Note', 'task': 'Task'
};

function iris_attr_esc(s) {
    return $('<div>').text(s === null || s === undefined ? '' : String(s)).html();
}

function iris_attr_fetch(force) {
    if (IRIS_ATTR.fetching) { return; }
    if (!force && Array.isArray(IRIS_ATTR.rows)) { return; }
    IRIS_ATTR.fetching = true;
    IRIS_ATTR.failed = null;
    iris_attr_render_rows();
    get_request_api('/manage/attributes/list')
    .done(function (data) {
        IRIS_ATTR.rows = (data && data.data) ? data.data : [];
    })
    .fail(function (xhr) {
        IRIS_ATTR.failed = 'HTTP ' + (xhr && xhr.status ? xhr.status : '?');
    })
    .always(function () {
        IRIS_ATTR.fetching = false;
        iris_attr_render_rows();
        if (Array.isArray(IRIS_ATTR.rows) && IRIS_ATTR.rows.length
                && IRIS_ATTR.selected === null) {
            iris_attr_select(iris_attr_sorted()[0].attribute_id);
        }
    });
}

function iris_attr_sorted() {
    return (IRIS_ATTR.rows || []).slice().sort(function (a, b) {
        return String(a.attribute_display_name).localeCompare(String(b.attribute_display_name));
    });
}

function iris_attr_render_rows() {
    var $l = $('#iris-attr-rows');
    if (IRIS_ATTR.failed) {
        $('#iris-attr-count').text('');
        $l.html('<div class="iris-co-empty">Could not load attributes ('
            + iris_attr_esc(IRIS_ATTR.failed) + '). Refresh to retry.</div>');
        return;
    }
    if (!Array.isArray(IRIS_ATTR.rows)) {
        $('#iris-attr-count').text('');
        $l.html('<div class="iris-co-empty">Loading…</div>');
        return;
    }
    var rows = iris_attr_sorted();
    $('#iris-attr-count').text(rows.length);
    if (!rows.length) {
        $l.html('<div class="iris-co-empty">No object types registered.</div>');
        return;
    }
    var html = '';
    rows.forEach(function (r) {
        var kind = IRIS_ATTR_KINDS[r.attribute_for] || r.attribute_for;
        html += '<div class="iris-attr-row'
            + (String(r.attribute_id) === String(IRIS_ATTR.selected) ? ' active' : '')
            + '" data-id="' + iris_attr_esc(r.attribute_id) + '">'
            + '<div><div class="iris-attr-row-name">' + iris_attr_esc(r.attribute_display_name) + '</div>'
            + '<div class="iris-attr-row-sub">' + iris_attr_esc(kind) + '</div></div>'
            + '<span class="iris-attr-row-id">#' + iris_attr_esc(r.attribute_id) + '</span>'
            + '</div>';
    });
    $l.html(html);
}

function iris_attr_current_row() {
    if (IRIS_ATTR.selected === null || !Array.isArray(IRIS_ATTR.rows)) { return null; }
    return IRIS_ATTR.rows.find(function (r) {
        return String(r.attribute_id) === String(IRIS_ATTR.selected);
    }) || null;
}

function iris_attr_editor_value() {
    return IRIS_ATTR.editor ? IRIS_ATTR.editor.getSession().getValue() : '';
}

function iris_attr_dirty() {
    return IRIS_ATTR.editor !== null && iris_attr_editor_value() !== IRIS_ATTR.loaded;
}

function iris_attr_init_editor() {
    if (IRIS_ATTR.editor) { return; }
    var editor = ace.edit('iris-attr-editor', {
        autoScrollEditorIntoView: true,
        minLines: 14
    });
    editor.setTheme('ace/theme/tomorrow');
    editor.session.setMode('ace/mode/json');
    editor.renderer.setShowGutter(true);
    editor.setOption('showLineNumbers', true);
    editor.setOption('showPrintMargin', false);
    editor.setOption('displayIndentGuides', true);
    editor.setOption('maxLines', 34);
    editor.session.setUseWrapMode(true);
    editor.setOption('indentedSoftWrap', true);
    editor.renderer.setScrollMargin(8, 5);
    // Same completion vocabulary as the legacy modal editor — the suite
    // asserts the two lists stay identical.
    editor.setOptions({
        enableBasicAutocompletion: [{
            getCompletions: (editor, session, pos, prefix, callback) => {
                callback(null, [
                    {value: 'mandatory', score: 1, meta: 'mandatory tag'},
                    {value: 'type', score: 1, meta: 'type tag'},
                    {value: 'input_string', score: 1, meta: 'An input string field type'},
                    {value: 'input_checkbox', score: 1, meta: 'An input checkbox field type'},
                    {value: 'input_textfield', score: 1, meta: 'An input textfield field type'},
                    {value: 'input_date', score: 1, meta: 'An input date field type'},
                    {value: 'input_datetime', score: 1, meta: 'An input datetime field type'},
                    {value: 'input_select', score: 1, meta: 'An input select field type'},
                    {value: 'raw', score: 1, meta: 'A raw field type'},
                    {value: 'html', score: 1, meta: 'An html field type'},
                    {value: 'value', score: 1, meta: 'default value'}
                ]);
            }
        }],
        enableLiveAutocompletion: true,
        enableSnippets: true
    });
    editor.getSession().on('change', function () {
        iris_attr_render_valid();
        clearTimeout(IRIS_ATTR.previewTimer);
        IRIS_ATTR.previewTimer = setTimeout(iris_attr_preview_run, 900);
    });
    IRIS_ATTR.editor = editor;
}

function iris_attr_select(attr_id) {
    if (String(attr_id) === String(IRIS_ATTR.selected)) { return; }
    if (iris_attr_dirty()
            && !confirm('Discard unsaved schema changes?')) { return; }
    IRIS_ATTR.selected = attr_id;
    var row = iris_attr_current_row();
    if (!row) { return; }
    iris_attr_render_rows();
    $('#iris-attr-editor-empty').hide();
    $('#iris-attr-editor-wrap').show();
    $('#iris-attr-sel-label').text(row.attribute_display_name + ' · ' + row.attribute_for);
    $('#iris-attr-name').val(row.attribute_display_name);
    $('#iris-attr-desc').val(row.attribute_description);
    iris_attr_init_editor();
    IRIS_ATTR.editor.getSession().setValue(JSON.stringify(row.attribute_content || {}, null, 4));
    IRIS_ATTR.loaded = iris_attr_editor_value();
    $('#iris-attr-errors').hide();
    iris_attr_render_valid();
    clearTimeout(IRIS_ATTR.previewTimer);
    iris_attr_preview_run();
}

function iris_attr_parse() {
    try {
        return { ok: true, parsed: JSON.parse(iris_attr_editor_value()) };
    } catch (e) {
        return { ok: false, error: String(e && e.message ? e.message : e) };
    }
}

function iris_attr_render_valid() {
    var $v = $('#iris-attr-valid');
    if (!IRIS_ATTR.editor) { $v.text('').removeClass('ok bad'); return; }
    var r = iris_attr_parse();
    if (r.ok) {
        $v.text('✓ Valid schema').removeClass('bad').addClass('ok');
    } else {
        $v.text('✗ Invalid JSON').removeClass('ok').addClass('bad');
    }
}

function iris_attr_preview_run() {
    var $p = $('#iris-attr-preview');
    if (IRIS_ATTR.selected === null || !IRIS_ATTR.editor) {
        $p.html('<div class="iris-co-empty">Select an object type to see the analyst preview.</div>');
        return;
    }
    var r = iris_attr_parse();
    if (!r.ok) {
        $p.html('<div class="iris-co-empty">Fix the JSON to see the preview.</div>');
        return;
    }
    if (!r.parsed || typeof r.parsed !== 'object' || !Object.keys(r.parsed).length) {
        $p.html('<div class="iris-co-empty">This schema has no tabs yet. Add one in the JSON editor to see the preview.</div>');
        return;
    }
    var seq = ++IRIS_ATTR.previewSeq;
    $.ajax({
        url: '/manage/attributes/preview',
        type: 'POST',
        data: JSON.stringify({
            attribute_content: iris_attr_editor_value(),
            csrf_token: $('#csrf_token').val()
        }),
        contentType: 'application/json;charset=UTF-8'
    })
    .done(function (html) {
        if (seq !== IRIS_ATTR.previewSeq) { return; }
        $p.html(html);
    })
    .fail(function () {
        if (seq !== IRIS_ATTR.previewSeq) { return; }
        $p.html('<div class="iris-co-empty">Preview failed — the server rejected the schema.</div>');
    });
}

/* Same endpoint + payload keys as manage.attributes.js::update_attribute —
 * the suite asserts the two key sets stay identical. */
function iris_attr_save(partial, complete) {
    var row = iris_attr_current_row();
    if (!row) { return; }
    var data_sent = Object();
    data_sent['attribute_content'] = iris_attr_editor_value();
    data_sent['csrf_token'] = $('#csrf_token').val();
    data_sent['partial_overwrite'] = partial;
    data_sent['complete_overwrite'] = complete;

    $('#iris-attr-errors').hide();
    $('#iris-attr-errors-msg').empty();
    $('#iris-attr-errors-list').empty();

    post_request_api('/manage/attributes/update/' + IRIS_ATTR.selected,
                     JSON.stringify(data_sent), false, function () {
        window.swal({
            title: 'Updating and migrating...',
            text: 'Please wait',
            icon: '/static/assets/img/loader.gif',
            button: false,
            allowOutsideClick: false
        });
    })
    .done(function (data) {
        if (api_request_failed(data)) { return; }
        notify_auto_api(data);
        IRIS_ATTR.loaded = iris_attr_editor_value();
        iris_attr_fetch(true);
    })
    .fail(function (error) {
        var data = error.responseJSON || {};
        $('#iris-attr-errors-msg').text(data.message || 'Update failed');
        if (data.data && data.data.length > 0) {
            for (var i in data.data) {
                $('#iris-attr-errors-list').append(
                    $('<li>').text(String(data.data[i])));
            }
        }
        $('#iris-attr-errors').show();
    })
    .always(function () {
        window.swal.close();
    });
}

function iris_attr_confirm_overwrite(kindLabel, text, cb) {
    swal({
        title: kindLabel + '?',
        text: text,
        icon: 'warning',
        buttons: true,
        dangerMode: true
    })
    .then(function (confirmed) {
        if (confirmed) { cb(); }
    });
}

$(function () {
    // The legacy Refresh reloads the hidden DataTable; wrap it so the v3
    // view re-fetches too — one writer, two presentations.
    var origR = window.refresh_attribute_table;
    if (typeof origR === 'function') {
        window.refresh_attribute_table = function () {
            var out = origR.apply(this, arguments);
            iris_attr_fetch(true);
            return out;
        };
    }

    $('#iris-attr-rows').on('click', '.iris-attr-row', function () {
        iris_attr_select($(this).attr('data-id'));
    });

    $('#iris-attr-save').on('click', function () { iris_attr_save(false, false); });
    $('#iris-attr-partial').on('click', function () {
        var row = iris_attr_current_row();
        if (!row) { return; }
        iris_attr_confirm_overwrite('Partial overwrite',
            'Resets the attribute values of matching tabs on every '
            + row.attribute_display_name
            + ' object, then applies this schema. Associated values are lost. '
            + 'Module-pushed attributes are kept.',
            function () { iris_attr_save(true, false); });
    });
    $('#iris-attr-complete').on('click', function () {
        var row = iris_attr_current_row();
        if (!row) { return; }
        iris_attr_confirm_overwrite('Complete overwrite',
            'Resets ALL custom attributes on every ' + row.attribute_display_name
            + ' object, INCLUDING module-pushed ones, then applies this schema. '
            + 'All associated values are lost.',
            function () { iris_attr_save(false, true); });
    });

    $('#iris-attr-refresh').on('click', function () {
        if (iris_attr_dirty()
                && !confirm('Discard unsaved schema changes?')) { return; }
        iris_attr_fetch(true);
    });

    iris_attr_fetch(false);
});

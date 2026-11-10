/* War-room datastore (iris-ng 2026-11-10). Import-free (ui/public is copied verbatim).
 *
 * The room's own folders and files, plus the files posted in the Stream as a read-only folder. Opened by the
 * header's Datastore button (window.IrisRoomDs.open()). The server decides what the viewer may do (`can` on
 * GET .../datastore, `can_delete` per file and folder); this page only hides what it would refuse.
 * Forms open inside the dialog, never as a second modal. Settled markers for probes: the dialog's
 * data-ds-tree (tree drawn) and data-ds-settled (file list drawn, a counter).
 */
(function () {
    'use strict';

    var S = {
        rid: null, tree: null, folder: 'root', q: '', files: [], byId: {}, seq: 0, want: 0,
        canWrite: false, lead: false, copyToCase: false, closed: false, limits: {}, qTimer: null
    };

    var ICO = {
        folder: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>',
        root: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/></svg>',
        stream: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
        download: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>',
        link: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
        edit: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/></svg>',
        move: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 9V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H20a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-1"/><path d="M2 13h10"/><path d="m9 16 3-3-3-3"/></svg>',
        tocase: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="14" x="2" y="7" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>',
        trash: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></svg>'
    };

    function el(id) { return document.getElementById(id); }

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    /* A server-assigned id, re-derived (never the text read back from the page). */
    function int(v) {
        var n = parseInt(v, 10);
        return isFinite(n) && n > 0 ? n : null;
    }

    function csrf() {
        var t = el('csrf_token');
        return t ? t.value : '';
    }

    function toast(ok, msg) {
        if (ok && typeof notify_success === 'function') { notify_success(msg); return; }
        if (!ok && typeof notify_error === 'function') { notify_error(msg); return; }
        if (!ok) { window.alert(msg); }
    }

    function base() { return '/api/v2/war-rooms/' + S.rid + '/datastore'; }

    function api(method, path, body) {
        var opts = {method: method, headers: {'Accept': 'application/json'}};
        if (body) {
            body.csrf_token = csrf();
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        return fetch(base() + path, opts).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (j) {
                return {ok: r.ok, status: r.status, j: j || {}};
            });
        });
    }

    function postForm(path, fd) {
        fd.append('csrf_token', csrf());
        return fetch(base() + path, {method: 'POST', headers: {'Accept': 'application/json'}, body: fd})
            .then(function (r) {
                return r.json().catch(function () { return {}; }).then(function (j) {
                    return {ok: r.ok, status: r.status, j: j || {}};
                });
            });
    }

    function size(n) {
        n = Number(n) || 0;
        if (n < 1024) return n + ' B';
        if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
        if (n < 1024 * 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + ' MB';
        return (n / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
    }

    /* Stored naive UTC, labelled as such (never re-read through a Date in the viewer's zone). */
    function when(iso) {
        var m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(String(iso || ''));
        return m ? m[1] + ' ' + m[2] + ' UTC' : '';
    }

    function contentUrl(id) { return '/api/v2/war-rooms/' + S.rid + '/datastore/files/' + id + '/content'; }
    function streamUrl(id) { return '/api/v2/war-rooms/' + S.rid + '/files/' + id + '?download=1'; }
    function mdLink(name, url) { return '[' + String(name).replace(/[[\]]/g, '') + '](' + url + ')'; }

    function status(msg) { el('iris-wr-ds-status').textContent = msg || ''; }

    /* ------------------------------------------------------------------- the tree */

    function folders() { return (S.tree && S.tree.folders) || []; }

    function folderById(id) {
        var list = folders();
        for (var i = 0; i < list.length; i++) { if (list[i].id === id) return list[i]; }
        return null;
    }

    function childrenOf(parentId) {
        return folders().filter(function (f) { return (f.parent_id || null) === parentId; });
    }

    function descendants(id) {
        var out = {}, stack = [id];
        while (stack.length) {
            var cur = stack.pop();
            childrenOf(cur).forEach(function (f) { if (!out[f.id]) { out[f.id] = true; stack.push(f.id); } });
        }
        return out;
    }

    function pathOf(id) {
        var names = [], cur = folderById(id), guard = 0;
        while (cur && guard < 20) { names.unshift(cur.name); cur = cur.parent_id ? folderById(cur.parent_id) : null; guard++; }
        return names;
    }

    function node(key, icon, name, count, depth, tools) {
        var active = String(S.folder) === String(key) && !S.q;
        return '<div class="iris-wr-ds-node' + (active ? ' active' : '') + '" data-ds-folder="' + esc(key) + '" ' +
            'style="padding-left:' + (6 + depth * 14) + 'px;">' +
            '<button type="button" class="iris-wr-ds-ibtn iris-wr-ds-pick" style="display:flex; align-items:center; gap:6px; flex:1 1 auto; min-width:0; padding:0; color:inherit;" aria-pressed="' + active + '">' +
            icon + '<span class="iris-wr-ds-node-name">' + esc(name) + '</span>' +
            '<span class="iris-wr-ds-node-count">' + (count || 0) + '</span></button>' + (tools || '') + '</div>';
    }

    function renderTree() {
        var html = node('root', ICO.root, 'Room files', S.tree ? S.tree.root_count : 0, 0);
        function walk(parentId, depth) {
            childrenOf(parentId).forEach(function (f) {
                var id = int(f.id);
                if (id === null) return;
                var tools = '';
                if (S.canWrite) {
                    tools = '<span class="iris-wr-ds-node-tools">' +
                        '<button type="button" class="iris-wr-ds-ibtn iris-wr-ds-frename" title="Rename" aria-label="Rename folder ' + esc(f.name) + '">' + ICO.edit + '</button>' +
                        '<button type="button" class="iris-wr-ds-ibtn iris-wr-ds-fmove" title="Move" aria-label="Move folder ' + esc(f.name) + '">' + ICO.move + '</button>' +
                        (f.can_delete ? '<button type="button" class="iris-wr-ds-ibtn iris-wr-ds-fdelete" title="Delete" aria-label="Delete folder ' + esc(f.name) + '">' + ICO.trash + '</button>' : '') +
                        '</span>';
                }
                html += node(id, ICO.folder, f.name, f.file_count, depth, tools);
                walk(id, depth + 1);
            });
        }
        walk(null, 1);
        html += '<div class="iris-wr-ds-sep"></div>' +
            node('stream', ICO.stream, 'Stream attachments', S.tree ? S.tree.stream_count : 0, 0);
        el('iris-wr-ds-tree').innerHTML = html;
        el('iris-wr-ds-modal').setAttribute('data-ds-tree', String(Date.now()));
    }

    function loadTree() {
        return api('GET', '').then(function (res) {
            if (!res.ok) { status(res.j.message || 'Could not read the datastore'); return; }
            S.tree = res.j;
            S.canWrite = !!(res.j.can && res.j.can.write);
            S.lead = !!(res.j.can && res.j.can.lead);
            S.copyToCase = !!(res.j.can && res.j.can.copy_to_case);
            S.closed = res.j.closed === true;
            S.limits = res.j.limits || {};
            if (typeof S.folder === 'number' && !folderById(S.folder)) S.folder = 'root';
            renderTree();
        });
    }

    /* ------------------------------------------------------------------ the files */

    function crumb() {
        if (S.q) return 'Search: "' + S.q + '"';
        if (S.folder === 'stream') return 'Stream attachments (read-only)';
        if (S.folder === 'root') return 'Room files';
        return 'Room files / ' + pathOf(S.folder).join(' / ');
    }

    function actionsFor(r, stream) {
        var id = int(r.id);
        var out = '<a class="iris-wr-ds-ibtn" title="Download" aria-label="Download ' + esc(r.filename) + '" href="' +
            (stream ? streamUrl(id) : contentUrl(id)) + '">' + ICO.download + '</a>' +
            '<button type="button" class="iris-wr-ds-ibtn iris-wr-ds-link" title="Copy as Markdown link" aria-label="Copy a Markdown link to ' + esc(r.filename) + '">' + ICO.link + '</button>';
        if (!stream && S.canWrite) {
            out += '<button type="button" class="iris-wr-ds-ibtn iris-wr-ds-edit" title="Edit" aria-label="Edit ' + esc(r.filename) + '">' + ICO.edit + '</button>' +
                '<button type="button" class="iris-wr-ds-ibtn iris-wr-ds-move" title="Move" aria-label="Move ' + esc(r.filename) + '">' + ICO.move + '</button>';
        }
        if (S.copyToCase) {
            out += '<button type="button" class="iris-wr-ds-ibtn iris-wr-ds-tocase" title="Copy to a case" aria-label="Copy ' + esc(r.filename) + ' to a case">' + ICO.tocase + '</button>';
        }
        if (!stream && r.can_delete) {
            out += '<button type="button" class="iris-wr-ds-ibtn iris-wr-ds-delete" title="Delete" aria-label="Delete ' + esc(r.filename) + '" style="color:#c46a72;">' + ICO.trash + '</button>';
        }
        return out;
    }

    function renderFiles() {
        var stream = S.folder === 'stream' && !S.q;
        el('iris-wr-ds-crumb').textContent = crumb();
        el('iris-wr-ds-upload').style.display = (S.canWrite && !stream) ? '' : 'none';
        el('iris-wr-ds-newfolder').style.display = (S.canWrite && !stream && !S.q) ? '' : 'none';
        var list = el('iris-wr-ds-list');
        if (!S.files.length) {
            var msg;
            if (S.q) msg = 'No file matches "' + S.q + '".';
            else if (stream) msg = 'No file has been posted in the Stream yet.';
            else if (S.canWrite) msg = 'No file here yet. Upload one, or drop files here.';
            else msg = S.closed ? 'No file here. The room is closed: its datastore is read-only.' : 'No file here yet.';
            list.innerHTML = '<div class="iris-wr-ds-empty">' + esc(msg) + '</div>';
        } else {
            list.innerHTML = '<table class="iris-wr-ds-table"><thead><tr><th>Name</th>' + (S.q ? '<th>Folder</th>' : '') +
                '<th>Size</th><th>Added</th><th class="iris-wr-ds-actions"><span class="sr-only">Actions</span></th></tr></thead><tbody>' +
                S.files.map(function (r) {
                    var id = int(r.id);
                    if (id === null) return '';
                    var tags = String(r.tags || '').split(',').filter(Boolean).map(function (t) {
                        return '<span class="iris-wr-ds-tag">' + esc(t) + '</span>';
                    }).join('');
                    var folderName = S.q ? (r.folder_id ? pathOf(r.folder_id).join(' / ') : 'Room files') : null;
                    return '<tr data-ds-file="' + id + '" data-ds-kind="' + (stream ? 'stream' : 'datastore') + '">' +
                        '<td><div class="iris-wr-ds-fname">' + esc(r.filename) + '</div>' +
                        (r.description ? '<div class="iris-wr-ds-sub">' + esc(r.description) + '</div>' : '') +
                        (tags ? '<div>' + tags + '</div>' : '') + '</td>' +
                        (S.q ? '<td class="iris-wr-ds-sub">' + esc(folderName) + '</td>' : '') +
                        '<td style="white-space:nowrap;">' + esc(size(r.size)) + '</td>' +
                        '<td><div style="white-space:nowrap;">' + esc(when(r.created_at)) + '</div>' +
                        (r.uploaded_by_name ? '<div class="iris-wr-ds-sub">' + esc(r.uploaded_by_name) + '</div>' : '') + '</td>' +
                        '<td class="iris-wr-ds-actions">' + actionsFor(r, stream) + '</td></tr>';
                }).join('') + '</tbody></table>';
        }
        S.seq += 1;
        el('iris-wr-ds-modal').setAttribute('data-ds-settled', String(S.seq));
    }

    function loadFiles() {
        var ticket = ++S.want;
        var path = '/files?folder=' + encodeURIComponent(String(S.folder)) + (S.q ? '&q=' + encodeURIComponent(S.q) : '');
        return api('GET', path).then(function (res) {
            if (ticket !== S.want) return;          /* an older answer than the view it would draw */
            if (!res.ok) {
                S.files = [];
                status(res.j.message || 'Could not list the files');
            } else {
                S.files = res.j.files || [];
            }
            S.byId = {};
            S.files.forEach(function (r) { var id = int(r.id); if (id !== null) S.byId[id] = r; });
            renderFiles();
        });
    }

    function refresh() { return loadTree().then(loadFiles); }

    /* ---------------------------------------------------------------------- forms */

    function hideForm() { el('iris-wr-ds-form-slot').innerHTML = ''; }

    function showForm(title, body, submitLabel, onSubmit) {
        el('iris-wr-ds-form-slot').innerHTML = '<form class="iris-wr-ds-form" id="iris-wr-ds-form" novalidate>' +
            '<div style="font-weight:600; margin-bottom:8px;">' + esc(title) + '</div>' + body +
            '<div class="text-danger mt-1" id="iris-wr-ds-form-err" style="display:none;"></div>' +
            '<div class="mt-2 d-flex" style="gap:6px;"><button type="submit" class="btn btn-sm btn-primary">' + esc(submitLabel) +
            '</button><button type="button" class="btn btn-sm btn-outline-secondary" id="iris-wr-ds-form-cancel">Cancel</button></div></form>';
        var form = el('iris-wr-ds-form');
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            var btn = form.querySelector('button[type="submit"]');
            btn.disabled = true;
            Promise.resolve(onSubmit(form)).then(function (err) {
                btn.disabled = false;
                if (err) {
                    var box = el('iris-wr-ds-form-err');
                    box.textContent = err;
                    box.style.display = '';
                    return;
                }
                hideForm();
            });
        });
        el('iris-wr-ds-form-cancel').addEventListener('click', hideForm);
        var first = form.querySelector('input, select, textarea');
        if (first) first.focus();
    }

    function folderOptions(selected, excluded) {
        var opts = '<option value="root"' + (selected === null ? ' selected' : '') + '>Room files (top level)</option>';
        function walk(parentId, depth) {
            childrenOf(parentId).forEach(function (f) {
                var id = int(f.id);
                if (id === null || (excluded && excluded[id])) return;
                opts += '<option value="' + id + '"' + (selected === id ? ' selected' : '') + '>' +
                    new Array(depth + 1).join('   ') + esc(f.name) + '</option>';
                walk(id, depth + 1);
            });
        }
        walk(null, 1);
        return opts;
    }

    function newFolder() {
        var parent = typeof S.folder === 'number' ? S.folder : null;
        showForm('New folder' + (parent ? ' in ' + pathOf(parent).join(' / ') : ''),
            '<label for="iris-wr-ds-fname">Name</label><input type="text" class="form-control" id="iris-wr-ds-fname" maxlength="' +
            (S.limits.folder_name_max || 120) + '">', 'Create', function () {
                return api('POST', '/folders', {name: el('iris-wr-ds-fname').value, parent_id: parent}).then(function (res) {
                    if (!res.ok) return res.j.message || 'Could not create the folder';
                    toast(true, 'Folder "' + res.j.name + '" created');
                    refresh();
                    return null;
                });
            });
    }

    function renameFolder(id) {
        var f = folderById(id);
        if (!f) return;
        showForm('Rename folder', '<label for="iris-wr-ds-fname">Name</label><input type="text" class="form-control" id="iris-wr-ds-fname" maxlength="' +
            (S.limits.folder_name_max || 120) + '">', 'Rename', function () {
                return api('PUT', '/folders/' + id, {name: el('iris-wr-ds-fname').value}).then(function (res) {
                    if (!res.ok) return res.j.message || 'Could not rename the folder';
                    refresh();
                    return null;
                });
            });
        el('iris-wr-ds-fname').value = f.name;
    }

    function moveFolder(id) {
        var f = folderById(id);
        if (!f) return;
        var excluded = descendants(id);
        excluded[id] = true;
        showForm('Move folder "' + f.name + '"', '<label for="iris-wr-ds-fparent">Into</label><select class="form-control" id="iris-wr-ds-fparent">' +
            folderOptions(f.parent_id || null, excluded) + '</select>', 'Move', function () {
                var v = el('iris-wr-ds-fparent').value;
                return api('POST', '/folders/' + id + '/move', {parent_id: v === 'root' ? null : int(v)}).then(function (res) {
                    if (!res.ok) return res.j.message || 'Could not move the folder';
                    refresh();
                    return null;
                });
            });
    }

    function confirmThen(title, text, go) {
        if (typeof swal === 'function') {
            swal({title: title, text: text, icon: 'warning', buttons: true, dangerMode: true}).then(function (yes) { if (yes) go(); });
        } else if (window.confirm(title + ' ' + text)) {
            go();
        }
    }

    function deleteFolder(id) {
        var f = folderById(id);
        if (!f) return;
        confirmThen('Delete folder "' + f.name + '"?', 'What it holds moves up one level. No file is deleted.', function () {
            api('DELETE', '/folders/' + id).then(function (res) {
                if (!res.ok) { toast(false, res.j.message || 'Could not delete the folder'); return; }
                toast(true, 'Folder deleted; ' + res.j.moved_files + ' file(s) and ' + res.j.moved_folders + ' folder(s) moved up');
                if (S.folder === id) S.folder = f.parent_id ? int(f.parent_id) : 'root';
                refresh();
            });
        });
    }

    function editFile(id) {
        var r = S.byId[id];
        if (!r) return;
        showForm('Edit file',
            '<label for="iris-wr-ds-ename">Name</label><input type="text" class="form-control" id="iris-wr-ds-ename" maxlength="200">' +
            '<label for="iris-wr-ds-edesc" class="mt-2">Description</label><textarea class="form-control" id="iris-wr-ds-edesc" rows="2" maxlength="' +
            (S.limits.description_max || 2000) + '"></textarea>' +
            '<label for="iris-wr-ds-etags" class="mt-2">Tags (comma-separated)</label><input type="text" class="form-control" id="iris-wr-ds-etags" maxlength="' +
            (S.limits.tags_max || 500) + '">' +
            '<label for="iris-wr-ds-erep" class="mt-2">Replace the contents (optional)</label><input type="file" class="form-control-file" id="iris-wr-ds-erep">',
            'Save', function () {
                return api('PUT', '/files/' + id, {
                    filename: el('iris-wr-ds-ename').value,
                    description: el('iris-wr-ds-edesc').value,
                    tags: el('iris-wr-ds-etags').value
                }).then(function (res) {
                    if (!res.ok) return res.j.message || 'Could not save the file';
                    var rep = el('iris-wr-ds-erep').files;
                    if (!rep || !rep.length) { loadFiles(); return null; }
                    if (S.limits.file_max_bytes && rep[0].size > S.limits.file_max_bytes) {
                        return rep[0].name + ' is larger than ' + size(S.limits.file_max_bytes);
                    }
                    var fd = new FormData();
                    fd.append('file', rep[0], rep[0].name);
                    return postForm('/files/' + id + '/replace', fd).then(function (res2) {
                        if (!res2.ok) return res2.j.message || 'Could not replace the contents';
                        toast(true, 'Contents replaced');
                        refresh();
                        return null;
                    });
                });
            });
        el('iris-wr-ds-ename').value = r.filename || '';
        el('iris-wr-ds-edesc').value = r.description || '';
        el('iris-wr-ds-etags').value = r.tags || '';
        el('iris-wr-ds-ename').focus();
    }

    function moveFile(id) {
        var r = S.byId[id];
        if (!r) return;
        showForm('Move "' + r.filename + '"', '<label for="iris-wr-ds-mfolder">Into</label><select class="form-control" id="iris-wr-ds-mfolder">' +
            folderOptions(r.folder_id ? int(r.folder_id) : null, null) + '</select>', 'Move', function () {
                var v = el('iris-wr-ds-mfolder').value;
                return api('POST', '/files/' + id + '/move', {folder_id: v === 'root' ? null : int(v)}).then(function (res) {
                    if (!res.ok) return res.j.message || 'Could not move the file';
                    refresh();
                    return null;
                });
            });
    }

    function deleteFile(id) {
        var r = S.byId[id];
        if (!r) return;
        confirmThen('Delete "' + r.filename + '"?', 'It is removed from the room\'s datastore for everyone.', function () {
            api('DELETE', '/files/' + id).then(function (res) {
                if (!res.ok) { toast(false, res.j.message || 'Could not delete the file'); return; }
                toast(true, 'File deleted');
                refresh();
            });
        });
    }

    function attachedCases() {
        var room = window.IRIS_WROOM && window.IRIS_WROOM._room;
        return ((room && room.cases) || []).filter(function (c) { return c.accessible && int(c.case_id) !== null; });
    }

    function copyToCase(kind, id) {
        var r = S.byId[id];
        if (!r) return;
        var cases = attachedCases();
        if (!cases.length) {
            showForm('Copy "' + r.filename + '" to a case', '<div>No attached case you can open. Attach one on the Cases tab first.</div>',
                'Close', function () { return null; });
            return;
        }
        showForm('Copy "' + r.filename + '" to a case',
            '<label for="iris-wr-ds-case">Case (attached to this room)</label><select class="form-control" id="iris-wr-ds-case">' +
            cases.map(function (c) {
                var cid = int(c.case_id);
                var name = String(c.case_name || '');
                return '<option value="' + cid + '">' + esc(/^#\d+ /.test(name) ? name : '#' + cid + ' ' + name) + '</option>';
            }).join('') + '</select><div class="iris-wr-ds-sub mt-1">It lands in the case datastore\'s "War rooms" folder; the room keeps its copy. You need full access to the case.</div>',
            'Copy', function () {
                var cid = int(el('iris-wr-ds-case').value);
                var path = (kind === 'stream' ? '/stream/' : '/files/') + id + '/copy-to-case';
                return api('POST', path, {case_id: cid}).then(function (res) {
                    if (!res.ok) return res.j.message || 'Could not copy the file';
                    toast(true, 'Copied to case #' + int(res.j.case_id) + ' (datastore folder "' + (res.j.folder || 'War rooms') + '")');
                    return null;
                });
            });
    }

    function copyLink(kind, id) {
        var r = S.byId[id];
        if (!r) return;
        var md = mdLink(r.filename, kind === 'stream' ? streamUrl(id) : contentUrl(id));
        var fallback = function () {
            showForm('Markdown link', '<label for="iris-wr-ds-md">Copy this link</label><input type="text" class="form-control" id="iris-wr-ds-md" readonly>',
                'Done', function () { return null; });
            el('iris-wr-ds-md').value = md;
            el('iris-wr-ds-md').select();
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(md).then(function () { toast(true, 'Markdown link copied'); }, fallback);
        } else {
            fallback();
        }
    }

    /* --------------------------------------------------------------------- upload */

    function uploadFiles(list) {
        var files = Array.prototype.slice.call(list || []);
        if (!files.length || !S.canWrite) return;
        var max = S.limits.upload_files_max || 20, cap = S.limits.file_max_bytes || 0;
        if (files.length > max) { toast(false, 'Upload ' + max + ' files at most at once'); return; }
        var big = files.filter(function (f) { return cap && f.size > cap; });
        if (big.length) {
            toast(false, big.map(function (f) { return f.name; }).join(', ') + ': larger than ' + size(cap));
            return;
        }
        var fd = new FormData();
        files.forEach(function (f) { fd.append('file', f, f.name); });
        fd.append('folder_id', typeof S.folder === 'number' && !S.q ? String(S.folder) : 'root');
        status('Uploading ' + files.length + ' file(s)...');
        postForm('/files', fd).then(function (res) {
            if (!res.ok) { status(''); toast(false, res.j.message || 'Upload failed'); return; }
            var saved = (res.j.files || []).length, errors = res.j.errors || [];
            status('Uploaded ' + saved + ' file(s)' + (errors.length ? '; ' + errors.length + ' refused: ' +
                errors.map(function (e) { return e.filename + ' (' + e.message + ')'; }).join(', ') : ''));
            refresh();
        });
    }

    /* ----------------------------------------------------------------- the dialog */

    function open() {
        var rid = int((el('iris-wr-room-id') || {}).value);
        if (rid === null) return;
        S.rid = rid;
        S.folder = 'root';
        S.q = '';
        el('iris-wr-ds-q').value = '';
        hideForm();
        status('');
        $('#iris-wr-ds-modal').modal('show');
        refresh();
    }

    function wire() {
        var modal = el('iris-wr-ds-modal');
        if (!modal || modal.getAttribute('data-ds-wired')) return;
        modal.setAttribute('data-ds-wired', '1');
        el('iris-wr-ds-tree').addEventListener('click', function (e) {
            var nodeEl = e.target.closest('.iris-wr-ds-node');
            if (!nodeEl) return;
            var key = nodeEl.getAttribute('data-ds-folder');
            var id = int(key);
            if (e.target.closest('.iris-wr-ds-frename')) { if (id) renameFolder(id); return; }
            if (e.target.closest('.iris-wr-ds-fmove')) { if (id) moveFolder(id); return; }
            if (e.target.closest('.iris-wr-ds-fdelete')) { if (id) deleteFolder(id); return; }
            S.folder = key === 'stream' ? 'stream' : (id !== null ? id : 'root');
            S.q = '';
            el('iris-wr-ds-q').value = '';
            hideForm();
            renderTree();
            loadFiles();
        });
        el('iris-wr-ds-list').addEventListener('click', function (e) {
            var row = e.target.closest('tr[data-ds-file]');
            if (!row) return;
            var id = int(row.getAttribute('data-ds-file'));
            var kind = row.getAttribute('data-ds-kind') === 'stream' ? 'stream' : 'datastore';
            if (id === null) return;
            if (e.target.closest('.iris-wr-ds-link')) copyLink(kind, id);
            else if (e.target.closest('.iris-wr-ds-edit')) editFile(id);
            else if (e.target.closest('.iris-wr-ds-move')) moveFile(id);
            else if (e.target.closest('.iris-wr-ds-tocase')) copyToCase(kind, id);
            else if (e.target.closest('.iris-wr-ds-delete')) deleteFile(id);
        });
        el('iris-wr-ds-newfolder').addEventListener('click', newFolder);
        el('iris-wr-ds-upload').addEventListener('click', function () { el('iris-wr-ds-file').click(); });
        el('iris-wr-ds-file').addEventListener('change', function () {
            uploadFiles(this.files);
            this.value = '';
        });
        el('iris-wr-ds-q').addEventListener('input', function () {
            var v = this.value.trim();
            clearTimeout(S.qTimer);
            S.qTimer = setTimeout(function () {
                S.q = v;
                renderTree();
                loadFiles();
            }, 250);
        });
        var list = el('iris-wr-ds-list');
        list.addEventListener('dragover', function (e) {
            if (!S.canWrite || S.folder === 'stream' || !e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') === -1) return;
            e.preventDefault();
            list.classList.add('iris-wr-ds-dragover');
        });
        list.addEventListener('dragleave', function (e) {
            if (!list.contains(e.relatedTarget)) list.classList.remove('iris-wr-ds-dragover');
        });
        list.addEventListener('drop', function (e) {
            list.classList.remove('iris-wr-ds-dragover');
            if (!S.canWrite || S.folder === 'stream' || !e.dataTransfer || !e.dataTransfer.files.length) return;
            e.preventDefault();
            uploadFiles(e.dataTransfer.files);
        });
    }

    document.addEventListener('DOMContentLoaded', wire);
    window.IrisRoomDs = {open: open, refresh: refresh};
})();

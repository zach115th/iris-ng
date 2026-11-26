/*
 * DataTables 3 drawn and behaving as DataTables 1.10.16 did (backlog #44 slice 3.5).
 *
 * Loaded right after plugin/datatables/dataTables.min.js and dataTables.bootstrap4.min.js in each layout, before any
 * extension or page script. DataTables 3 still attaches to the jQuery the layouts load first ($.fn.dataTable,
 * $.fn.DataTable, events through jQuery), so the pages keep their code; what changed since 1.10.16 is put back here:
 *
 * - class names: each generated element keeps DataTables 3's class (Select and Buttons look for `dt-container`,
 *   RowGroup for `dt-scroll-body`) and gets 1.10.16's beside it - the theme (atlantis.css carries 1.10.16's
 *   Bootstrap 4 stylesheet), the dark theme and IRIS's own rules are written against dataTables_wrapper /
 *   _length / _filter / _info / _paginate; the header cells get only 1.10.16's sorting / sorting_asc / ...
 * - the layout: 1.10.16's Bootstrap 4 `dom` (the length and search row, the table, the info and paging row);
 * - the texts: "Show _MENU_ entries", "Showing _START_ to _END_ of _TOTAL_ entries", Previous / Next...; page
 *   numbers unformatted ("1000", not "1,000") and the ellipsis disabled, as 1.10.16's paging wrote them;
 * - ordering: a header click toggles ascending / descending (3 adds a third, unordered, step); equal values keep
 *   their loaded order when descending too (orderDescReverse off); a column holding a non-ASCII character orders
 *   as 1.10.16 ordered every string (3's "-utf8" types compare with localeCompare and ignore spaces and
 *   punctuation); paging is simple_numbers; every row is drawn when the data is added (deferRender off);
 * - the rows: 1.10.16 gave each drawn row `odd` / `even`, which the dark theme's selected-row colours use;
 * - the search box inside its label;
 * - column widths: 1.10.16's own measure (header cells, or a copy holding each column's longest value) on the
 *   header cells, at the moments 1.10.16 measured - not 3's (always a copy, into a colgroup, on every container
 *   resize, and again whenever Responsive 4 hides a column);
 * - Responsive's tableAll() renderer lists every column, each title followed by a colon (Responsive 4's lists
 *   only the hidden ones);
 * - RowGroup's group row is a td again (RowGroup 2 writes a th);
 * - Buttons: no drop-down arrow on collection buttons (colvis); a copy / CSV with no footer row, no trailing line
 *   break and one header row (Buttons 4 writes the header again as a footer, ends with a line break and writes
 *   every header row - the per-column filter row became a row of empty cells).
 *
 * A table that sets one of these options itself keeps its own value. Some of these reach DataTables 3's and its
 * extensions' internals (the settings object, Responsive's _resize): a version bump is checked with
 * scripts/_datatables_probe.js (private) against the version before.
 */
(function () {
    'use strict';
    var DT = window.DataTable;
    if (!DT || !DT.util || !DT.ext) { return; }
    var deep = DT.util.object.assignDeep;

    deep(DT.ext.classes, {
        container: 'dt-container dataTables_wrapper container-fluid dt-bootstrap4',
        empty: {row: 'dt-empty dataTables_empty'},
        info: {container: 'dt-info dataTables_info'},
        length: {container: 'dt-length dataTables_length', select: 'form-control form-control-sm'},
        order: {
            canAsc: 'sorting', canDesc: 'sorting', isAsc: 'sorting_asc', isDesc: 'sorting_desc',
            none: 'sorting_disabled', position: 'sorting_'
        },
        processing: {container: 'dt-processing dataTables_processing card'},
        scrolling: {
            body: 'dt-scroll-body dataTables_scrollBody', container: 'dt-scroll dataTables_scroll',
            footer: {self: 'dt-scroll-foot dataTables_scrollFoot', inner: 'dt-scroll-footInner dataTables_scrollFootInner'},
            header: {self: 'dt-scroll-head dataTables_scrollHead', inner: 'dt-scroll-headInner dataTables_scrollHeadInner'}
        },
        search: {container: 'dt-search dataTables_filter', input: 'form-control form-control-sm'},
        paging: {container: 'dt-paging dataTables_paginate paging_simple_numbers'}
    });

    deep(DT.defaults, {
        dom: "<'row'<'col-sm-12 col-md-6'l><'col-sm-12 col-md-6'f>>" +
             "<'row'<'col-sm-12'tr>>" +
             "<'row'<'col-sm-12 col-md-5'i><'col-sm-12 col-md-7'p>>",
        pagingType: 'simple_numbers',
        deferRender: false,
        orderDescReverse: false,
        language: {
            emptyTable: 'No data available in table',
            info: 'Showing _START_ to _END_ of _TOTAL_ entries',
            infoEmpty: 'Showing 0 to 0 of 0 entries',
            infoFiltered: '(filtered from _MAX_ total entries)',
            lengthMenu: 'Show _MENU_ entries',
            loadingRecords: 'Loading...',
            processing: 'Processing...',
            search: 'Search:',
            zeroRecords: 'No matching records found',
            paginate: {first: 'First', last: 'Last', next: 'Next', previous: 'Previous'}
        }
    });
    DT.defaults.column.orderSequence = ['asc', 'desc'];

    // one object each: DataTables names the detection object it is given (a property that cannot be redefined)
    var never = function () { return {allOf: function () { return false; }, oneOf: function () { return false; }}; };
    DT.type('string-utf8', 'detect', never());
    DT.type('html-utf8', 'detect', never());

    var button = DT.ext.renderer.pagingButton.bootstrap;
    if (button) {
        DT.ext.renderer.pagingButton.bootstrap = function (settings, buttonType, content, active, disabled) {
            if (typeof buttonType === 'number') { content = String(buttonType + 1); }
            if (buttonType === 'ellipsis') { disabled = true; }
            return button.call(this, settings, buttonType, content, active, disabled);
        };
    }

    jQuery(document).on('draw.dt', function (e, settings) {
        if (e.namespace !== 'dt') { return; }
        var api = new DT.Api(settings);
        var rows = api.rows({page: 'current'}).nodes().toArray();
        if (!rows.length) {
            var body = api.table().body();
            rows = body ? Array.prototype.slice.call(body.rows, 0, 1) : [];
        }
        for (var i = 0; i < rows.length; i++) {
            rows[i].classList.remove('odd', 'even');
            rows[i].classList.add(i % 2 ? 'even' : 'odd');
        }
    });

    // 1.10.16's column widths (its _fnCalculateColumnWidths) in place of DataTables 3's, for a table with autoWidth
    // on. 1.10.16's first measure (before the first draw) read each header cell as the browser laid it out, when the
    // header had one row, no column was given a width and nothing scrolled; every later measure (and the first,
    // otherwise) laid out a hidden copy of the table holding each column's longest value. It wrote the widths on the
    // header cells (the bottom row's, or the top's with orderCellsTop) and the table's width, and measured again on
    // columns.adjust(), a visibility change, the end of initialisation for an Ajax or `data` table, and a window
    // resize when the table had a width attribute. DataTables 3 always sizes from a copy of its own making, into a
    // colgroup, and on every resize of the container.
    var $ = window.jQuery;
    var px = function (v) { return typeof v === 'number' ? (v < 0 ? '0px' : v + 'px') : (/\d$/.test(v) ? v + 'px' : v); };
    function headerCells(settings, thead) {
        var rows = thead.rows;
        var top = settings.init && (settings.init.orderCellsTop || settings.init.bSortCellsTop);
        var row = top ? rows[0] : rows[rows.length - 1];
        return row ? Array.prototype.slice.call(row.cells) : [];
    }
    // How long a cell's display text is, counted as 1.10.16 counted it (_fnGetMaxLenString): without anything from a
    // `<` to the next `>` on the same line, each `&nbsp;` then one character. Only the count is used, to pick the
    // longest cell; the cell measured is the node DataTables drew, so this text never reaches the page.
    function isLineEnd(c) { return c === '\n' || c === '\r' || c === '\u2028' || c === '\u2029'; }
    function displayLength(s) {
        var kept = [], i = 0, n = s.length;
        while (i < n) {
            if (s.charAt(i) === '<') {
                var j = i + 1;
                while (j < n && s.charAt(j) !== '>' && !isLineEnd(s.charAt(j))) { j++; }
                if (j < n && s.charAt(j) === '>') { i = j + 1; continue; }
            }
            kept.push(s.charAt(i));
            i++;
        }
        var text = kept.join('');
        return text.length - 5 * (text.split('&nbsp;').length - 1);
    }
    function longestCell(api, col) {
        var best = -1, at = null;
        api.rows({order: 'index'}).indexes().each(function (r) {
            var len = displayLength(String(api.cell(r, col).render('display')));
            if (len > best) { best = len; at = r; }
        });
        return at === null ? null : api.cell(at, col).node();
    }
    function widths110(settings) {
        var api = new DT.Api(settings);
        var table = api.table().node(), thead = api.table().header(), tfoot = api.table().footer();
        var cols = settings.columns;
        var vis = [];
        api.columns().visible().toArray().forEach(function (v, i) { if (v) { vis.push(i); } });
        var scroll = settings.scroll || {};
        var g = table.getAttribute('width');
        if (table.style.width && table.style.width.indexOf('%') !== -1) { g = table.style.width; }
        var user = vis.some(function (i) { return cols[i].widthOrig; });
        var w = {};
        if (!settings._irisMeasured && !user && !scroll.x && !scroll.y &&
                cols.length === vis.length && cols.length === thead.querySelectorAll('th').length) {
            var all = thead.querySelectorAll('th');
            vis.forEach(function (c, a) { w[c] = px($(all[a]).width()); });
        } else {
            var copy = $(table).clone().css('visibility', 'hidden').removeAttr('id');
            copy.find('tbody tr').remove();
            var row = $('<tr/>').appendTo(copy.find('tbody'));
            copy.find('thead, tfoot').remove();
            copy.append($(thead).clone());
            if (tfoot) { copy.append($(tfoot).clone()); }
            copy.find('tfoot th, tfoot td').css('width', '');
            var cells = headerCells(settings, copy.find('thead')[0]);
            vis.forEach(function (c, a) {
                if (cells[a]) { cells[a].style.width = cols[c].widthOrig ? px(cols[c].widthOrig) : ''; }
            });
            if (api.rows().count()) {
                vis.forEach(function (c) {
                    var n = longestCell(api, c);
                    row.append(n ? $(n).clone(false) : $('<td/>'));
                });
            }
            $('[name]', copy).removeAttr('name');
            var holder = $('<div/>').append(copy).appendTo(table.parentNode);
            if (g) { copy.width(g); }
            var total = 0;
            vis.forEach(function (c, a) {
                var m = $(cells[a]);
                var pad = m.outerWidth() - m.width();
                var bw = Math.ceil(cells[a].getBoundingClientRect().width);
                total += bw;
                w[c] = px(bw - pad);
            });
            table.style.width = px(total);
            holder.remove();
        }
        if (g) { table.style.width = px(g); }
        settings._irisMeasured = true;
        var real = headerCells(settings, thead);
        vis.forEach(function (c, a) { if (real[a]) { real[a].style.width = w[c]; } });
        if ((g || scroll.x) && !settings._irisResize) {
            settings._irisResize = true;
            $(window).on('resize.DT-iris-' + settings.tableId, DT.util.throttle(function () {
                if (!settings.destroying && document.body.contains(table)) { new DT.Api(settings).columns.adjust(); }
            }));
        }
    }
    function onSizing(e, settings) {
        if (e.namespace !== 'dt' || !settings || !settings._irisWidths || settings._irisInResponsive) { return; }
        // the sizing at the end of initialisation: 1.10.16 measured there only for an Ajax or `data` table
        if (settings.initDone && !settings._irisInitDone) {
            var init = settings.init || {};
            if (!settings.json && !init.data && !init.aaData) { return; }
        }
        widths110(settings);
    }
    // the search box inside its label, as 1.10.16 wrote it (<label>Search:<input></label>): 3 writes the input after
    // the label, which lets the two wrap apart
    $(document).on('preInit.dt', function (e, settings) {
        if (e.namespace !== 'dt') { return; }
        var wrap = settings.tableWrapper;
        var box = wrap && wrap.querySelector('div.dataTables_filter');
        if (!box) { return; }
        var label = box.querySelector('label'), input = box.querySelector('input');
        if (label && input && input.parentNode === box) { label.appendChild(input); }
    });
    $(document).on('preInit.dt', function (e, settings) {
        if (e.namespace !== 'dt' || !settings.features.autoWidth) { return; }
        settings.features.autoWidth = false;
        settings._irisWidths = true;
        widths110(settings);
        // column-sizing does not bubble in DataTables 3 (every 1.10.16 event did): listen on the table itself
        $(settings.table).on('column-sizing.dt', onSizing);
    });
    $(document).on('init.dt', function (e, settings) {
        if (e.namespace === 'dt') { settings._irisInitDone = true; }
    });

    // Responsive 2.2.9's tableAll(): every column, `title:` then the value, in a full-width table
    function tableAll(options) {
        options = Object.assign({tableClass: ''}, options);
        return function (api, rowIdx, columns) {
            var table = document.createElement('table');
            table.className = options.tableClass + ' dtr-details';
            table.setAttribute('width', '100%');
            columns.forEach(function (col) {
                var tr = document.createElement('tr');
                if (col.className) { tr.className = col.className; }
                tr.setAttribute('data-dt-row', col.rowIndex);
                tr.setAttribute('data-dt-column', col.columnIndex);
                var title = document.createElement('td');
                title.innerHTML = col.title + ':';
                var data = document.createElement('td');
                data.innerHTML = col.data;
                tr.appendChild(title);
                tr.appendChild(document.createTextNode(' '));
                tr.appendChild(data);
                table.appendChild(tr);
            });
            return table;
        };
    }

    // the extensions load after this file, page by page: patch each when it attaches itself to DataTables (it
    // registers its renderers and button types before that assignment)
    function whenAttached(name, patch) {
        if (DT[name]) { patch(DT[name]); return; }
        var held;
        Object.defineProperty(DT, name, {
            configurable: true, enumerable: true,
            get: function () { return held; },
            set: function (v) { held = v; patch(v); }
        });
    }
    whenAttached('Responsive', function (R) {
        if (R && R.renderer) { R.renderer.tableAll = tableAll; }
        // Responsive 4 calls columns.adjust() itself after it hides or shows columns (2.2.9 did not), so the widths
        // would be measured again with the hidden columns gone: the sizing it causes is not one 1.10.16 measured
        var resize = R && R.prototype && R.prototype._resize;
        if (resize) {
            R.prototype._resize = function () {
                var s = this.s && this.s.dt ? this.s.dt.settings()[0] : null;
                if (s) { s._irisInResponsive = (s._irisInResponsive || 0) + 1; }
                try { return resize.apply(this, arguments); } finally { if (s) { s._irisInResponsive--; } }
            };
        }
    });
    // RowGroup 1.1.4's group row: <tr><td colspan="N">name</td></tr> (RowGroup 2 writes a th, which the 1.1.4-era
    // stylesheet and the dark theme do not style); the name is written as text, as RowGroup 2 escapes it
    whenAttached('RowGroup', function (RG) {
        if (!RG || !RG.defaults) { return; }
        RG.defaults.startRender = function (rows, group) {
            var tr = document.createElement('tr');
            var td = document.createElement('td');
            td.colSpan = this._colspan();
            td.textContent = group === null || group === undefined ? '' : String(group);
            tr.appendChild(td);
            return tr;
        };
    });
    whenAttached('Buttons', function () {
        var b = DT.ext.buttons;
        if (!b) { return; }
        if (b.collection) { b.collection.dropIcon = false; }
        // Buttons 1.6.1 exported no footer; Buttons 4 repeats the header row at the end of a copy / CSV
        ['copyHtml5', 'csvHtml5', 'excelHtml5', 'pdfHtml5', 'print'].forEach(function (k) {
            if (b[k] && typeof b[k] === 'object') { b[k].footer = false; }
        });
        // ... and ends every copy / CSV with a line break 1.6.1 did not write
        ['copyHtml5', 'csvHtml5'].forEach(function (k) {
            if (b[k] && !b[k].customize) {
                b[k].customize = function (out) { return typeof out === 'string' ? out.replace(/(\r\n|\n)$/, '') : out; };
            }
        });
        // ... and writes every header row (the per-column filter row became a row of empty cells); 1.6.1 wrote one,
        // each column's own header cell - the top row's with orderCellsTop, the bottom row's otherwise. A page's own
        // exportOptions replace the type's (Buttons merges them shallowly), so the action supplies it each time.
        ['copyHtml5', 'csvHtml5'].forEach(function (k) {
            var action = b[k] && b[k].action;
            if (!action) { return; }
            b[k].action = function (e, dt, button, config, cb) {
                var own = config.exportOptions && config.exportOptions.customizeData;
                var top = !!(dt.settings()[0].init && dt.settings()[0].init.orderCellsTop);
                config.exportOptions = Object.assign({}, config.exportOptions, {
                    customizeData: function (data) {
                        var rows = data.headerStructure;
                        if (rows && rows.length > 1) { data.headerStructure = [rows[top ? 0 : rows.length - 1]]; }
                        if (own) { own(data); }
                    }
                });
                return action.call(this, e, dt, button, config, cb);
            };
        });
    });
})();

/*
 * A DataTables cell edited through a select, with Confirm / Cancel (backlog #44 slice 3.5).
 *
 * Replaces the CellEdit 1.0.19 plug-in for the one place IRIS used it, the Tasks table's status column, with the
 * same behaviour and markup, built through the DOM: no inline handlers (CellEdit wrote onclick / onchange attributes
 * and the options' text as HTML).
 *
 *   IrisCellEdit.attach(table, {columns: [2], options: [{value, display}], inputCss, confirmCss, cancelCss,
 *                               allowNull, errorClass, onUpdate: function (cell, row, oldValue) {...}});
 *   IrisCellEdit.detach(table);
 *
 * A click on a cell of one of `columns` replaces its content with the select (the cell's value selected), a
 * no-break space, "Confirm" and "Cancel". Confirm writes the selected value into the cell, calls onUpdate(cell,
 * row, oldValue) and redraws the page the table is on; an empty value is refused (errorClass on the select) unless
 * allowNull. Cancel restores the cell and redraws the table. Changing the select alone does nothing.
 */
(function () {
    'use strict';
    var NS = 'click.irisCellEdit';

    function link(text, cls, handler) {
        var a = document.createElement('a');
        a.href = '#';
        a.className = cls || '';
        a.textContent = text;
        a.addEventListener('click', function (e) {
            e.preventDefault();
            handler(a);
        });
        return a;
    }

    function attach(table, opts) {
        detach(table);
        jQuery(table.table().body()).on(NS, 'td', function () {
            var cell = table.cell(this);
            var idx = cell.index();
            if (!idx || (opts.columns && opts.columns.indexOf(idx.column) < 0)) { return; }
            var node = cell.node();
            if (node.querySelector('input, select, textarea')) { return; }
            var oldValue = cell.data();
            if (oldValue === undefined || oldValue === null) { oldValue = ''; }

            var select = document.createElement('select');
            select.className = opts.inputCss || '';
            (opts.options || []).forEach(function (o) {
                var opt = new Option(o.display, o.value);
                // loose, as CellEdit compared: a numeric cell value matches its option's string value
                opt.selected = oldValue == o.value;
                select.appendChild(opt);
            });

            var confirm = link('Confirm', opts.confirmCss, function () {
                var row = table.row(node.parentNode);
                var newValue = select.value;
                if (!newValue && !opts.allowNull) {
                    select.classList.add(opts.errorClass || 'error');
                } else {
                    var before = cell.data();
                    cell.data(newValue);
                    if (opts.onUpdate) { opts.onUpdate(cell, row, before); }
                }
                table.page(table.page.info().page).draw(false);
            });
            var cancel = link('Cancel', opts.cancelCss, function () {
                cell.data(cell.data());
                table.draw();
            });

            node.textContent = '';
            node.appendChild(select);
            node.appendChild(document.createTextNode('\u00a0'));
            node.appendChild(confirm);
            node.appendChild(document.createTextNode(' '));
            node.appendChild(cancel);
        });
    }

    function detach(table) {
        jQuery(table.table().body()).off(NS);
    }

    window.IrisCellEdit = {attach: attach, detach: detach};
})();

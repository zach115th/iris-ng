/* IrisDashWidgets - draws one custom-dashboard widget from the server's result (iris-ng, 2026-11-09).
 *
 *   IrisDashWidgets.render(body, widget, result, {palette, barLabels})   number / donut / pie / bar / hbar / line /
 *                                                                          table (groups or rows)
 *   IrisDashWidgets.format(value, unit)                                    a figure as text (counts, %, durations, bytes)
 *   IrisDashWidgets.destroy(body)
 *
 * Built with DOM calls only: labels and cells never pass through HTML parsing. Colours come from the widget's
 * validated options and are re-checked here (#rrggbb) before they reach a style. Charts are Chart.js 2.
 */
(function () {
    'use strict';

    var DEFAULT_PALETTE = ['#5464d8', '#2bb0a0', '#f6c344', '#f5365c', '#8b5cf6', '#48abf7', '#fb6340', '#31ce36',
                           '#e83e8c', '#a0a0b0'];
    var HEX = /^#[0-9a-fA-F]{6}$/;
    var charts = typeof WeakMap === 'function' ? new WeakMap() : null;

    function el(tag, props, kids) {
        var n = document.createElement(tag);
        Object.keys(props || {}).forEach(function (k) {
            var v = props[k];
            if (v === null || v === undefined || v === false) { return; }
            if (k === 'text') { n.textContent = v; }
            else if (k === 'cls') { n.className = v; }
            else { n.setAttribute(k, v === true ? '' : v); }
        });
        (kids || []).forEach(function (c) { if (c) { n.appendChild(c); } });
        return n;
    }

    function color(c, fallback) {
        return (typeof c === 'string' && HEX.test(c)) ? c.toLowerCase() : fallback;
    }

    function alpha(hex, a) {
        var h = color(hex, '#5464d8');
        var r = parseInt(h.slice(1, 3), 16), g = parseInt(h.slice(3, 5), 16), b = parseInt(h.slice(5, 7), 16);
        return 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
    }

    function group3(n) {
        var s = String(Math.round(Math.abs(n)));
        return (n < 0 ? '-' : '') + s.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    }

    function duration(minutes) {
        var neg = minutes < 0;
        var m = Math.abs(minutes);
        var out;
        if (m < 1) { out = Math.round(m * 60) + 's'; }
        else if (m < 60) { out = Math.floor(m) + 'm' + (m % 1 >= 1 / 60 ? ' ' + Math.round((m % 1) * 60) + 's' : ''); }
        else if (m < 1440) { out = Math.floor(m / 60) + 'h' + (Math.round(m % 60) ? ' ' + Math.round(m % 60) + 'm' : ''); }
        else { out = Math.floor(m / 1440) + 'd' + (Math.round((m % 1440) / 60) ? ' ' + Math.round((m % 1440) / 60) + 'h' : ''); }
        return (neg ? '-' : '') + out;
    }

    function format(value, unit) {
        if (value === null || value === undefined || value === '' || isNaN(Number(value))) { return '—'; }
        var v = Number(value);
        if (unit === 'percent') { return (Math.round(v * 10) / 10).toFixed(1) + '%'; }
        if (unit === 'minutes') { return duration(v); }
        if (unit === 'days') { return duration(v * 1440); }
        if (unit === 'bytes') {
            var units = ['B', 'KB', 'MB', 'GB', 'TB'], i = 0;
            while (Math.abs(v) >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
            return (i ? (Math.round(v * 10) / 10) : Math.round(v)) + ' ' + units[i];
        }
        if (v % 1 !== 0) { return (Math.round(v * 100) / 100).toLocaleString('en-US'); }
        return group3(v);
    }

    function destroy(body) {
        var c = charts ? charts.get(body) : body.__irisChart;
        if (c) {
            try { c.destroy(); } catch (e) { /* already gone */ }
        }
        if (charts) { charts.delete(body); } else { body.__irisChart = null; }
        body.textContent = '';
    }

    function message(body, text, cls) {
        body.appendChild(el('div', {cls: 'dw-msg' + (cls ? ' ' + cls : ''), text: text}));
    }

    function threshold(widget, value) {
        var list = ((widget.options || {}).thresholds) || [];
        for (var i = 0; i < list.length; i++) {
            var t = list[i];
            var limit = Number(t.value);
            if (value === null || value === undefined || isNaN(limit)) { continue; }
            if ((t.op === 'gte' && value >= limit) || (t.op === 'lte' && value <= limit)) {
                return color(t.color, null);
            }
        }
        return null;
    }

    function drawNumber(body, widget, result) {
        var fig = el('div', {cls: 'dw-number', text: format(result.value, result.unit)});
        var c = threshold(widget, result.value === null ? null : Number(result.value))
            || color((widget.options || {}).color, null);
        if (c) { fig.style.setProperty('color', c); }
        body.appendChild(fig);
    }

    function isEmpty(result) {
        if (!result.labels || !result.labels.length) { return true; }
        return !(result.series || []).some(function (s) {
            return (s.values || []).some(function (v) { return v !== null && v !== undefined && Number(v) !== 0; });
        });
    }

    function summary(widget, result) {
        var s = (result.series || [])[0] || {values: []};
        var parts = (result.labels || []).slice(0, 12).map(function (l, i) {
            return l + ' ' + format(s.values[i], result.unit);
        });
        return (widget.name || 'Chart') + ': ' + parts.join(', ') + ((result.labels || []).length > 12 ? ', …' : '');
    }

    function chartHeight(widget, result) {
        if (widget.chart === 'hbar') {
            return Math.min(620, Math.max(170, 26 * (result.labels || []).length * Math.max(1, (result.series || []).length > 1 ? 1.3 : 1) + 50));
        }
        return 260;
    }

    function drawChart(body, widget, result, opts) {
        if (typeof window.Chart !== 'function') {
            message(body, 'Charts are unavailable on this page.');
            return;
        }
        var palette = (opts.palette || DEFAULT_PALETTE).map(function (c, i) { return color(c, DEFAULT_PALETTE[i % 10]); });
        var unit = result.unit;
        var wrap = el('div', {cls: 'dw-canvas'});
        wrap.style.setProperty('height', chartHeight(widget, result) + 'px');
        var canvas = el('canvas', {role: 'img', 'aria-label': summary(widget, result)});
        wrap.appendChild(canvas);
        body.appendChild(wrap);
        var own = color((widget.options || {}).color, null);
        var series = result.series || [];
        var split = series.length > 1;
        var round = widget.chart === 'donut' || widget.chart === 'pie';
        var stack = split && (unit === 'count' || unit === 'minutes' || unit === 'days' || unit === 'bytes')
            && widget.chart !== 'line';
        var datasets = series.map(function (s, i) {
            var base = split ? palette[i % palette.length] : (own || palette[0]);
            var ds = {label: s.label, data: (s.values || []).map(function (v) { return v === null ? null : Number(v); })};
            if (round) {
                ds.backgroundColor = ds.data.map(function (_v, j) { return palette[j % palette.length]; });
                ds.borderColor = '#1a1a22';
                ds.borderWidth = 2;
            } else if (widget.chart === 'line') {
                ds.borderColor = base;
                ds.backgroundColor = alpha(base, split ? 0.0 : 0.15);
                ds.fill = !split;
                ds.lineTension = 0.25;
                ds.pointRadius = ds.data.length > 60 ? 0 : 2;
                ds.borderWidth = 2;
                ds.spanGaps = true;
            } else {
                ds.backgroundColor = alpha(base, 0.85);
                ds.borderColor = base;
                ds.borderWidth = 1;
                ds.maxBarThickness = 38;
            }
            return ds;
        });
        var fontColor = '#c4c4cf';
        var grid = {color: 'rgba(255,255,255,0.07)', zeroLineColor: 'rgba(255,255,255,0.18)'};
        var tickFmt = function (v) { return format(v, unit); };
        var valueAxis = {stacked: stack, ticks: {beginAtZero: true, fontColor: fontColor, callback: tickFmt, maxTicksLimit: 7},
                         gridLines: grid};
        if (unit === 'count') { valueAxis.ticks.precision = 0; }
        var labelAxis = {stacked: stack, ticks: {fontColor: fontColor, autoSkip: true, maxRotation: 45, minRotation: 0,
                                                 callback: function (l) { l = String(l); return l.length > 28 ? l.slice(0, 27) + '…' : l; }},
                         gridLines: {display: false}};
        var type = {donut: 'doughnut', pie: 'pie', bar: 'bar', hbar: 'horizontalBar', line: 'line'}[widget.chart];
        var options = {
            responsive: true,
            maintainAspectRatio: false,
            animation: {duration: 250},
            legend: {display: round || split, position: round ? 'right' : 'bottom',
                     labels: {fontColor: fontColor, boxWidth: 12, padding: 10}},
            tooltips: {callbacks: {label: function (item, data) {
                var ds = data.datasets[item.datasetIndex];
                var v = ds.data[item.index];
                var name = round ? data.labels[item.index] : (split ? ds.label : (data.labels[item.index]));
                return ' ' + name + ': ' + format(v, unit);
            }}}
        };
        if (round) {
            if (widget.chart === 'donut') { options.cutoutPercentage = 62; }
        } else if (widget.chart === 'hbar') {
            options.scales = {xAxes: [valueAxis], yAxes: [labelAxis]};
        } else {
            options.scales = {xAxes: [labelAxis], yAxes: [valueAxis]};
        }
        var chart = new window.Chart(canvas.getContext('2d'), {type: type, data: {labels: result.labels, datasets: datasets},
                                                               options: options});
        if (charts) { charts.set(body, chart); } else { body.__irisChart = chart; }
    }

    function drawGroupTable(body, widget, result) {
        var series = result.series || [];
        var head = el('tr', {}, [el('th', {scope: 'col', text: result.time ? 'Period' : 'Group'})]
            .concat(series.map(function (s) { return el('th', {scope: 'col', cls: 'dw-num', text: s.label}); })));
        var rows = (result.labels || []).map(function (label, i) {
            return el('tr', {}, [el('td', {text: label})].concat(series.map(function (s) {
                return el('td', {cls: 'dw-num', text: format(s.values[i], result.unit)});
            })));
        });
        body.appendChild(el('div', {cls: 'dw-table-wrap'}, [el('table', {cls: 'dw-table'},
            [el('thead', {}, [head]), el('tbody', {}, rows)])]));
    }

    // A row link is one of the app's own pages, rebuilt from its parts: never the server's string as it came.
    var LINK_PAGES = {'/case': 'cid', '/case/ioc': 'cid', '/case/assets': 'cid', '/case/tasks': 'cid',
                      '/case/timeline': 'cid', '/case/evidences': 'cid', '/case/notes': 'cid', '/alerts': 'alert_ids'};

    function safeLink(link) {
        var m = /^(\/[a-z\/]+)\?(cid|alert_ids)=(\d{1,12})$/.exec(String(link || ''));
        if (!m) { return null; }
        var page = Object.prototype.hasOwnProperty.call(LINK_PAGES, m[1]) ? m[1] : null;
        if (!page || LINK_PAGES[page] !== m[2]) { return null; }
        return page + '?' + LINK_PAGES[page] + '=' + parseInt(m[3], 10);
    }

    function cellNode(value, kind) {
        if (value === null || value === undefined || (Array.isArray(value) && !value.length)) {
            return el('span', {cls: 'dw-dim', text: '—'});
        }
        if (Array.isArray(value)) {
            var box = el('span', {cls: 'dw-tags'});
            value.slice(0, 6).forEach(function (t) { box.appendChild(el('span', {cls: 'dw-tag', text: String(t)})); });
            if (value.length > 6) { box.appendChild(el('span', {cls: 'dw-dim', text: '+' + (value.length - 6)})); }
            return box;
        }
        if (kind === 'number') { return document.createTextNode(format(value, 'count')); }
        return document.createTextNode(String(value));
    }

    function drawRows(body, widget, result) {
        var cols = result.columns || [];
        if (!(result.rows || []).length) {
            message(body, 'Nothing to list in this range.');
            return;
        }
        var head = el('tr', {}, cols.map(function (c) {
            return el('th', {scope: 'col', cls: c.kind === 'number' ? 'dw-num' : null, text: c.label});
        }));
        var rows = result.rows.map(function (r) {
            var href = safeLink(r.link);
            return el('tr', {}, (r.cells || []).map(function (v, i) {
                var td = el('td', {cls: (cols[i] || {}).kind === 'number' ? 'dw-num' : null});
                var node = cellNode(v, (cols[i] || {}).kind);
                if (i === 0 && href) {
                    td.appendChild(el('a', {href: href, cls: 'dw-link'}, [node]));
                } else {
                    td.appendChild(node);
                }
                return td;
            }));
        });
        body.appendChild(el('div', {cls: 'dw-table-wrap'}, [el('table', {cls: 'dw-table'},
            [el('thead', {}, [head]), el('tbody', {}, rows)])]));
        if (result.total > result.rows.length) {
            body.appendChild(el('div', {cls: 'dw-foot', text: 'Showing ' + result.rows.length + ' of ' + group3(result.total)}));
        }
    }

    function render(body, widget, result, opts) {
        opts = opts || {};
        destroy(body);
        body.removeAttribute('data-dw-state');
        if (!result) {
            message(body, 'Loading…', 'dw-loading');
            body.setAttribute('data-dw-state', 'loading');
            return;
        }
        if (!result.ok) {
            message(body, result.error || 'This widget could not be computed.', 'dw-error');
            body.setAttribute('data-dw-state', 'error');
            return;
        }
        if (result.kind === 'number') {
            drawNumber(body, widget, result);
        } else if (result.kind === 'rows') {
            drawRows(body, widget, result);
        } else if (isEmpty(result)) {
            message(body, 'No data in this range.');
        } else if (widget.chart === 'table') {
            drawGroupTable(body, widget, result);
        } else {
            drawChart(body, widget, result, opts);
        }
        var notes = [];
        if (result.other) { notes.push('"Other" sums the remaining groups.'); }
        if (result.series_truncated) { notes.push('Only the largest series are shown.'); }
        var ignored = (result.ignored_filters || []).map(function (k) { return (opts.barLabels || {})[k] || k; });
        if (ignored.length) { notes.push('Not filtered by ' + ignored.join(', ') + ' (this source has no such field).'); }
        if (notes.length) { body.appendChild(el('div', {cls: 'dw-foot', text: notes.join(' ')})); }
        body.setAttribute('data-dw-state', 'drawn');
    }

    window.IrisDashWidgets = {render: render, format: format, destroy: destroy, safeLink: safeLink};
})();

/* IrisChartDefaults - Chart.js 4 set up to draw what Chart.js 2.9.4 drew (iris-ng, 2026-11-25).
 *
 * Loaded right after /static/assets/js/core/charts.js on every page that draws a chart: Metrics, Inventory and the
 * custom dashboards' view and editor. Each setting below is a Chart.js 2.9.4 default that 4.x changed or dropped;
 * a chart's own options still win over all of it.
 *
 *   IrisChartDefaults.grid(color[, zeroColor])   a scriptable grid colour that strokes the line at 0 in zeroColor
 *                                                 (2.x's zeroLineColor, by default rgba(0,0,0,0.25))
 *
 * What a chart still sets itself: an axis whose grid has another colour sets `border.color` to it (2.x drew the axis
 * line in the grid colour), and an axis whose grid is hidden sets `border.display: false` (2.x hid the axis line
 * with the grid).
 */
(function () {
    'use strict';

    var C = window.Chart;
    if (typeof C !== 'function' || !C.defaults || !C.defaults.plugins || !C.overrides) { return; }   // not Chart.js 4
    var d = C.defaults;
    var ZERO_LINE = 'rgba(0,0,0,0.25)';

    function grid(color, zeroColor) {
        var zero = zeroColor || ZERO_LINE;
        return function (ctx) { return ctx.tick && ctx.tick.value === 0 ? zero : color; };
    }

    // Axes. 2.x laid an axis out as a 10 px tick mark, its labels with no padding and 0.4 of a label's line height
    // to spare; a horizontal axis also kept 3 px from the canvas edges, and the grid line at 0 had its own colour.
    // Rotated labels it measured over every tick, before any was skipped, each as its height less half a line.
    d.scale.ticks.padding = 0;
    d.scale.grid.tickLength = 10;
    d.scale.grid.color = grid('rgba(0,0,0,0.1)');
    // 2.x sized rotated labels from every tick, before any was skipped: keep them while they are all there.
    d.scale.afterCalculateLabelRotation = function (scale) {
        scale.$irisLabels = scale.ticks.map(function (t) { return t.label; });
        scale.$irisValues = scale.ticks.map(function (t) { return t.value; });
    };
    d.scale.afterFit = function (scale) {
        if (!scale.options.display || !scale.options.ticks.display) { return; }
        var font = C.helpers.toFont(scale.options.ticks.font);
        var lineSpace = font.lineHeight * 0.4;
        if (!scale.isHorizontal()) {
            scale.width += lineSpace;
            return;
        }
        if (!scale.labelRotation || !scale.$irisLabels || !scale.$irisLabels.length) {
            if (!scale.labelRotation) { scale.height += lineSpace; }
            scale.paddingLeft += 3;
            scale.paddingRight += 3;
            return;
        }
        // Rotated: 2.9.4's fit() - each label's height less half a line, and its own end paddings.
        var rad = scale.labelRotation * Math.PI / 180, cos = Math.cos(rad), sin = Math.sin(rad);
        var ctx = scale.ctx, lh = font.lineHeight, off = lh / 2, ws = [], hs = [];
        ctx.save();
        ctx.font = font.string;
        scale.$irisLabels.forEach(function (label) {
            var lines = Array.isArray(label) ? label : [label], w = 0, h = 0;
            lines.forEach(function (l) {
                if (l !== null && l !== undefined && !Array.isArray(l)) { w = Math.max(w, ctx.measureText(String(l)).width); h += lh; }
            });
            ws.push(w);
            hs.push(h);
        });
        ctx.restore();
        var n = ws.length;
        var widest = Math.max.apply(null, ws), highest = Math.max.apply(null, hs);
        var tl = scale.options.grid.drawTicks ? scale.options.grid.tickLength : 0;
        scale.height = Math.min(scale.maxHeight, tl + sin * widest + cos * (highest - off));
        var bottom = scale.options.position === 'bottom';
        var pl = bottom ? cos * ws[0] + sin * off : sin * (hs[0] - off);
        var pr = bottom ? sin * (hs[n - 1] - off) : cos * ws[n - 1] + sin * off;
        // offsets of the first / last label from the ends of the axis's own pixel range (2.x: left / right)
        var oL = scale.getPixelForValue(scale.$irisValues[0]) - scale.getPixelForDecimal(0);
        var oR = scale.getPixelForDecimal(1) - scale.getPixelForValue(scale.$irisValues[n - 1]);
        scale.paddingLeft = Math.max((pl - oL) * scale.width / (scale.width - oL), 0) + 3;
        scale.paddingRight = Math.max((pr - oR) * scale.width / (scale.width - oR), 0) + 3;
    };

    // Linear axis labels as 2.x wrote them: as many decimals as the step between ticks needs and no thousands
    // separator (4.x formats them for the locale: 1250 becomes "1,250"). 2.9.4's formatter, ported.
    d.scales.linear.ticks.callback = function (value, index, ticks) {
        var vals = ticks.map(function (t) { return t.value; });
        var delta = vals.length > 3 ? vals[2] - vals[1] : vals[1] - vals[0];
        if (Math.abs(delta) > 1 && value !== Math.floor(value)) { delta = value - Math.floor(value); }
        if (value === 0) { return '0'; }
        var logDelta = Math.log10(Math.abs(delta));
        var maxTick = Math.max(Math.abs(vals[0]), Math.abs(vals[vals.length - 1]));
        if (maxTick < 1e-4) {
            return value.toExponential(Math.max(Math.min(Math.floor(Math.log10(Math.abs(value))) - Math.floor(logDelta), 20), 0));
        }
        return value.toFixed(Math.max(Math.min(-1 * Math.floor(logDelta), 20), 0));
    };

    // Hover. 2.x's bar and line charts highlighted every element at the index under the pointer.
    C.overrides.bar.hover = {mode: 'index', intersect: true};
    C.overrides.line.hover = {mode: 'index', intersect: true};

    // Tooltips write the raw value (4.x formats it for the locale: 1234 becomes "1,234"); a doughnut's or pie's has
    // no title and reads "label: value".
    d.plugins.tooltip.callbacks.label = function (item) {
        var label = item.dataset.label || '';
        return (label ? label + ': ' : '') + item.raw;
    };
    ['doughnut', 'pie'].forEach(function (type) {
        var o = C.overrides[type];
        o.plugins = o.plugins || {};
        o.plugins.tooltip = {callbacks: {
            title: function () { return ''; },
            label: function (item) { return item.label + ': ' + item.raw; }
        }};
    });

    // Legend. 2.x gave the box of a dataset drawn without a fill its line colour (4.x keeps its fill colour, which
    // for such a line is usually transparent).
    var generate = d.plugins.legend.labels.generateLabels;
    d.plugins.legend.labels.generateLabels = function (chart) {
        var items = generate.call(this, chart);
        items.forEach(function (item) {
            var ds = chart.data.datasets[item.datasetIndex];
            if (ds && (ds.fill === false || ds.fill === null)) { item.fillStyle = item.strokeStyle; }
        });
        return items;
    };

    window.IrisChartDefaults = {grid: grid};
})();

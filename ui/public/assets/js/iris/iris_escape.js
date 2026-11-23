/* iris-ng: the one HTML escaper (backlog #25 F1 + F2, 2026-11-19).
 *
 * Use it for any plain value written into markup - an attribute value as much as element text. It escapes the five
 * characters that can end a value or start markup (& < > " '); null and undefined give ''. It is not a sanitizer:
 * Markdown and other HTML meant to render goes through do_md_filter_xss / filterXSS instead, and a value going into a
 * URL attribute still needs its scheme checked.
 *
 * filterXSS (sanitizeHTML) escapes neither quote, so `title="' + sanitizeHTML(x) + '"` let a stored value close the
 * attribute and add its own. The page helpers built on .text(s).html() / textContent -> innerHTML left both quotes too.
 *
 * Loaded synchronously in <head> by every layout with a nav and by the guest portal's (common.js loads at the end of the
 * body and not at all in the portal), so inline scripts and the page helpers that call it can run at any point.
 */
var IRIS_ESCAPE_MAP = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'};

function iris_escape(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
        return IRIS_ESCAPE_MAP[c];
    });
}

/* A DataTables column render with the shape of $.fn.dataTable.render.text(): the cell shows its value as text.
   DataTables writes a cell's data with innerHTML unless a render escapes it, and 1.10.16's render.text() leaves '&'
   alone (a stored "&amp;" showed as "&"), so this one escapes all five through iris_escape. Sorting and search
   keep the raw value. Use it as `"render": iris_dt_text()` (backlog #25 F6, 2026-11-23). */
function iris_dt_text() {
    return {display: function (data) { return iris_escape(data); }};
}

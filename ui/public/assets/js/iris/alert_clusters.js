/* iris-ng v2: Alert Clusters LIST page, v3 parity (2026-09-01).
 * Filter bar (status / severity / customer / title search / per-page),
 * v3 table (#id — title, severity + status chips, alerts count, customer,
 * owner, source rule, opened). Row click navigates to the detail page
 * /alert-clusters/<id> (v3 URL scheme); everything that used to be the
 * inline detail panel lives there now (alert_cluster_detail.js).
 *
 * Import-free on purpose (ui/public/ → copied verbatim, no rolldown pass).
 * /api/v2 envelope: THE RESPONSE IS THE DATA. Legacy /manage/* endpoints
 * wrap {status,data}. Timestamps are STORED naive-UTC: format the string,
 * never new Date() (re-zoning trap).
 */

var IRIS_AC = {
    _clusters: [],
    _page: 1,
    _total: 0,
    _debounce: null
};

function iris_ac_csrf() {
    return $('#csrf_token').val();
}

function iris_ac_esc(s) {
    return $('<div>').text(s == null ? '' : String(s)).html();
}

function iris_ac_fetch(path, method, body) {
    var opts = {
        method: method || 'GET',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin'
    };
    if (body !== undefined) {
        body = Object.assign({}, body, { csrf_token: iris_ac_csrf() });
        opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (r) {
        if (r.status === 204) { return { __status: 204 }; }
        return r.json().then(function (j) {
            j = (j && typeof j === 'object') ? j : { value: j };
            j.__status = r.status;
            return j;
        }).catch(function () { return { __status: r.status }; });
    });
}

var IRIS_AC_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/* Format the STORED naive-UTC ISO string into "Sep 1, 2026, 14:45 UTC" —
 * string surgery only; new Date() would re-zone it to the browser. */
function iris_ac_ts(iso) {
    if (!iso) { return ''; }
    var m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    if (!m) { return String(iso); }
    return IRIS_AC_MONTHS[parseInt(m[2], 10) - 1] + ' ' + parseInt(m[3], 10)
        + ', ' + m[1] + ', ' + m[4] + ':' + m[5] + ' UTC';
}

function iris_ac_sev_chip(name) {
    var n = (name || '').toLowerCase();
    var cls = 'iris-ac-sev-none';
    if (n === 'critical') { cls = 'iris-ac-sev-critical'; }
    else if (n === 'high') { cls = 'iris-ac-sev-high'; }
    else if (n === 'medium') { cls = 'iris-ac-sev-medium'; }
    else if (n === 'low') { cls = 'iris-ac-sev-low'; }
    return '<span class="iris-ac-chip iris-ac-sev ' + cls + '">'
        + iris_ac_esc(name || '—') + '</span>';
}

var IRIS_AC_STATUS_CLASS = {
    open: 'iris-ac-st-open',
    investigating: 'iris-ac-st-investigating',
    dismissed: 'iris-ac-st-dismissed',
    escalated: 'iris-ac-st-escalated',
    closed: 'iris-ac-st-closed'
};

function iris_ac_status_chip(status) {
    var cls = IRIS_AC_STATUS_CLASS[status] || 'iris-ac-st-closed';
    var label = status ? status.charAt(0).toUpperCase() + status.slice(1) : '—';
    return '<span class="iris-ac-chip ' + cls + '">' + iris_ac_esc(label) + '</span>';
}

/* ------------------------------------------------------- filter catalogs */

function iris_ac_load_severities() {
    // Lookup ids/names vary per deployment — resolve at runtime (fork rule).
    fetch('/manage/severities/list', { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
            var rows = (j && j.data) || [];
            var sel = document.getElementById('iris-ac-severity-filter');
            rows.forEach(function (s) {
                var o = document.createElement('option');
                o.value = s.severity_name;
                o.textContent = s.severity_name;
                sel.appendChild(o);
            });
        })
        .catch(function () { /* filter stays "Any severity" — degraded, not broken */ });
}

function iris_ac_load_customers() {
    fetch('/manage/customers/list', { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
            var rows = (j && j.data) || [];
            var sel = document.getElementById('iris-ac-customer-filter');
            rows.forEach(function (c) {
                var o = document.createElement('option');
                o.value = c.customer_id;
                o.textContent = c.customer_name;
                sel.appendChild(o);
            });
        })
        .catch(function () { /* non-admins may be refused — degraded, not broken */ });
}

/* ---------------------------------------------------------------- list */

function iris_ac_load() {
    var params = new URLSearchParams();
    var status = $('#iris-ac-status-filter').val();
    var sev = $('#iris-ac-severity-filter').val();
    var cust = $('#iris-ac-customer-filter').val();
    var q = ($('#iris-ac-search').val() || '').trim();
    if (status) { params.set('status', status); }
    if (sev) { params.set('severity', sev); }
    if (cust) { params.set('customer_id', cust); }
    if (q) { params.set('q', q); }
    params.set('page', IRIS_AC._page);
    params.set('per_page', $('#iris-ac-perpage').val());

    iris_ac_fetch('/api/v2/alert-clusters?' + params.toString()).then(function (j) {
        if (j.__status !== 200) {
            $('#iris-ac-body').html('<tr><td colspan="8" class="text-danger">Failed to load (HTTP '
                + j.__status + ')</td></tr>');
            return;
        }
        IRIS_AC._clusters = j.clusters || [];
        IRIS_AC._total = j.total || 0;

        $('#iris-ac-headline').text(
            IRIS_AC._total + ' total — ' + (j.awaiting_triage || 0) + ' awaiting triage');

        if (!IRIS_AC._clusters.length) {
            $('#iris-ac-body').html('<tr><td colspan="8" class="text-muted">No clusters'
                + (q || status || sev || cust ? ' match the current filters.'
                   : '. Alerts stack here when a clustering rule matches them '
                     + '(Settings &rarr; Clustering Rules).') + '</td></tr>');
            $('#iris-ac-pager').hide();
            return;
        }

        var rows = IRIS_AC._clusters.map(function (c) {
            var owner = c.owner_name
                ? iris_ac_esc(c.owner_name)
                : '<span class="iris-ac-owner-unassigned">Unassigned</span>';
            return '<tr class="iris-ac-row" data-cluster-id="' + c.id + '">'
                + '<td><span class="iris-ac-title">#' + c.id + ' — '
                    + iris_ac_esc(c.title) + '</span></td>'
                + '<td>' + iris_ac_sev_chip(c.severity) + '</td>'
                + '<td>' + iris_ac_status_chip(c.status) + '</td>'
                + '<td class="text-right"><strong>' + iris_ac_esc(c.alert_count)
                    + '</strong></td>'
                + '<td>' + iris_ac_esc(c.customer_name || c.customer_id) + '</td>'
                + '<td>' + owner + '</td>'
                + '<td>' + iris_ac_esc(c.rule_name || '(rule deleted)') + '</td>'
                + '<td>' + iris_ac_esc(iris_ac_ts(c.created_at)) + '</td></tr>';
        });
        $('#iris-ac-body').html(rows.join(''));

        var per = parseInt($('#iris-ac-perpage').val(), 10);
        if (IRIS_AC._total > per) {
            var pages = Math.ceil(IRIS_AC._total / per);
            $('#iris-ac-pager-label').text('Page ' + IRIS_AC._page + ' of ' + pages);
            $('#iris-ac-prev').prop('disabled', IRIS_AC._page <= 1);
            $('#iris-ac-next').prop('disabled', IRIS_AC._page >= pages);
            $('#iris-ac-pager').css('display', 'flex');
        } else {
            $('#iris-ac-pager').hide();
        }
    });
}

function iris_ac_reload_first_page() {
    IRIS_AC._page = 1;
    iris_ac_load();
}

/* --------------------------------------------------------------- wiring */

$(function () {
    iris_ac_load_severities();
    iris_ac_load_customers();
    iris_ac_load();

    $('#iris-ac-refresh').on('click', iris_ac_load);
    $('#iris-ac-status-filter, #iris-ac-severity-filter, #iris-ac-customer-filter, '
        + '#iris-ac-perpage').on('change', iris_ac_reload_first_page);
    $('#iris-ac-search').on('input', function () {
        clearTimeout(IRIS_AC._debounce);
        IRIS_AC._debounce = setTimeout(iris_ac_reload_first_page, 300);
    });
    $('#iris-ac-prev').on('click', function () {
        if (IRIS_AC._page > 1) { IRIS_AC._page -= 1; iris_ac_load(); }
    });
    $('#iris-ac-next').on('click', function () {
        IRIS_AC._page += 1; iris_ac_load();
    });

    $(document).on('click', '.iris-ac-row', function () {
        var cid = (new URLSearchParams(window.location.search)).get('cid') || '1';
        window.location.href = '/alert-clusters/' + $(this).attr('data-cluster-id')
            + '?cid=' + encodeURIComponent(cid);
    });
});

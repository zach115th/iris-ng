/* iris-ng v2 (Phase 4): Customer Assets registry page — filtered list with
 * live sightings, curation editor, change log, CSV export/import, scan.
 *
 * Import-free (ui/public/). v2 envelope: THE RESPONSE IS THE DATA. POSTs
 * carry csrf_token in the body; the CSV import carries it as a FORM field
 * (multipart CSRF project rule). Delegated data-* handlers via .attr().
 */

var IRIS_CA = {
    _assets: [],
    _current: null
};

function iris_ca_csrf() {
    return $('#csrf_token').val();
}

function iris_ca_esc(s) {
    return $('<div>').text(s == null ? '' : String(s)).html();
}

/* Server ids are digits only — returns the id as a string, or null for
   anything else, so a corrupted value renders as text instead of becoming
   part of a link inside an .html() build. Covers BOTH positions an id is
   used in (href and visible "#N" text), which per-href URL-encoding
   would not. */
function iris_ca_id(v) {
    var s = String(v == null ? '' : v);
    return /^\d+$/.test(s) ? s : null;
}

function iris_ca_fetch(path, method, body) {
    var opts = {
        method: method || 'GET',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin'
    };
    if (body !== undefined) {
        body = Object.assign({}, body, { csrf_token: iris_ca_csrf() });
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

function iris_ca_ts(iso) {
    if (!iso) { return ''; }
    return String(iso).replace('T', ' ').slice(0, 16);
}

function iris_ca_filter_qs() {
    var parts = [];
    /* Every dynamic value is encoded — the selects and chips carry
       server/markup-controlled values today, but this QS feeds a
       window.location sink and encoding at the one builder covers
       every consumer (also keeps the QS well-formed regardless). */
    if ($('#iris-ca-f-customer').val()) { parts.push('customer_id=' + encodeURIComponent($('#iris-ca-f-customer').val())); }
    if ($('#iris-ca-f-type').val()) { parts.push('type_id=' + encodeURIComponent($('#iris-ca-f-type').val())); }
    if ($('#iris-ca-f-crit').val()) { parts.push('criticality=' + encodeURIComponent($('#iris-ca-f-crit').val())); }
    /* Tri-state chip groups carry their value in data-val ('' = Any).
       Read with .attr() per project rule — never .data(). */
    var comp = $('#iris-ca-f-comp').attr('data-val');
    if (comp) { parts.push('compromised=' + encodeURIComponent(comp)); }
    var seen = $('#iris-ca-f-seen').attr('data-val');
    if (seen) { parts.push('seen=' + encodeURIComponent(seen)); }
    if ($('#iris-ca-f-env').val().trim()) {
        parts.push('environment=' + encodeURIComponent($('#iris-ca-f-env').val().trim()));
    }
    if ($('#iris-ca-f-owner').val().trim()) {
        parts.push('owner=' + encodeURIComponent($('#iris-ca-f-owner').val().trim()));
    }
    if ($('#iris-ca-f-q').val().trim()) {
        parts.push('q=' + encodeURIComponent($('#iris-ca-f-q').val().trim()));
    }
    return parts.length ? ('?' + parts.join('&')) : '';
}

/* ------------------------------------------------------------------ list */

function iris_ca_load() {
    iris_ca_fetch('/api/v2/customer-assets' + iris_ca_filter_qs()).then(function (j) {
        if (j.__status !== 200) {
            $('#iris-ca-body').html('<tr><td colspan="10" class="text-danger">Failed '
                + 'to load (HTTP ' + j.__status + ')</td></tr>');
            return;
        }
        IRIS_CA._assets = j.assets || [];
        if (!IRIS_CA._assets.length) {
            $('#iris-ca-body').html('<tr><td colspan="10" class="text-muted">No '
                + 'registry entries. Use <b>Scan cases</b> to build the registry '
                + 'from existing case and alert assets.</td></tr>');
            $('#iris-ca-pager').text('');
            return;
        }
        var rows = IRIS_CA._assets.map(function (a) {
            var crit = a.criticality
                ? '<span class="iris-ca-crit iris-ca-crit-' + iris_ca_esc(a.criticality)
                  + '">' + iris_ca_esc(a.criticality) + '</span>'
                : '';
            var comp = a.compromise_status === 1
                ? '<span class="iris-ca-comp">compromised</span>'
                : iris_ca_esc(a.compromise_status_name || '');
            return '<tr class="iris-ca-row" data-asset-id="' + (iris_ca_id(a.id) || '') + '">'
                + '<td>' + iris_ca_esc(a.asset_name) + '</td>'
                + '<td>' + iris_ca_esc(a.asset_type || '') + '</td>'
                + '<td>' + iris_ca_esc(a.customer_name || '') + '</td>'
                + '<td>' + crit + '</td>'
                + '<td>' + iris_ca_esc(a.environment || '') + '</td>'
                + '<td>' + iris_ca_esc(a.owner || '') + '</td>'
                + '<td>' + comp + '</td>'
                + '<td class="text-right">' + (a.sightings ? a.sightings.cases : 0) + '</td>'
                + '<td class="text-right">' + (a.sightings ? a.sightings.alerts : 0) + '</td>'
                + '<td>' + iris_ca_esc(iris_ca_ts(a.last_seen)) + '</td></tr>';
        });
        $('#iris-ca-body').html(rows.join(''));
        $('#iris-ca-pager').text(j.total + ' asset(s)'
            + (j.total > j.per_page ? ' — showing first ' + j.per_page : ''));
    });
}

/* ---------------------------------------------------------------- detail */

function iris_ca_kv(key, valueHtml) {
    return '<div class="iris-ca-kv"><span class="k">' + key + '</span><span class="v">'
        + (valueHtml || '<span class="text-muted">&mdash;</span>') + '</span></div>';
}

function iris_ca_comp_badge(a) {
    if (a.compromise_status === 1) {
        var since = a.compromise_since
            ? (' <span class="text-muted" style="font-size:0.72rem;">since '
               + iris_ca_esc(iris_ca_ts(a.compromise_since)) + '</span>') : '';
        return '<span class="iris-ca-badge-bad">Compromised</span>' + since;
    }
    if (a.compromise_status === 2) {
        return '<span class="iris-ca-badge-ok">Not compromised</span>';
    }
    return '<span class="iris-ca-badge-mut">'
        + iris_ca_esc(a.compromise_status_name || 'unknown') + '</span>';
}

function iris_ca_render_summary(a) {
    var obs = a.latest_observation || {};
    var crit = a.criticality
        ? '<span class="iris-ca-crit iris-ca-crit-' + iris_ca_esc(a.criticality) + '">'
          + iris_ca_esc(a.criticality) + '</span>'
        : '<span class="iris-ca-badge-mut">unknown</span>';
    var tags = (obs.tags || '').split(/[,|]/).filter(function (t) { return t.trim(); })
        .map(function (t) { return '<span class="iris-ca-tagchip">' + iris_ca_esc(t.trim()) + '</span>'; })
        .join('');
    var html = '<div style="font-size:1.05rem; font-weight:600;">' + iris_ca_esc(a.asset_name) + '</div>'
        + '<div class="text-muted mb-3" style="font-size:0.78rem;">'
        + iris_ca_esc(a.customer_name || '') + ' &middot; ' + iris_ca_esc(a.asset_type || '') + '</div>'
        + iris_ca_kv('Criticality', crit)
        + iris_ca_kv('Environment', a.environment ? iris_ca_esc(a.environment) : null)
        + iris_ca_kv('Owner', a.owner ? iris_ca_esc(a.owner) : null)
        + iris_ca_kv('IP', obs.ip ? iris_ca_esc(obs.ip) : null)
        + iris_ca_kv('Domain', obs.domain ? iris_ca_esc(obs.domain) : null)
        + iris_ca_kv('Tags', tags || null);
    if (a.notes) {
        html += iris_ca_kv('Notes', iris_ca_esc(a.notes));
    }
    $('#iris-ca-summary').html(html);
}

function iris_ca_open(assetId) {
    iris_ca_fetch('/api/v2/customer-assets/' + assetId).then(function (a) {
        if (a.__status !== 200) { return; }
        IRIS_CA._current = a;
        $('#iris-ca-detail-title').text(a.asset_name + ' — '
            + (a.asset_type || '') + ' @ ' + (a.customer_name || ''));
        $('#iris-ca-e-crit').val(a.criticality || '');
        $('#iris-ca-e-env').val(a.environment || '');
        $('#iris-ca-e-owner').val(a.owner || '');
        $('#iris-ca-e-comp').val(a.compromise_status == null ? '' : String(a.compromise_status));
        $('#iris-ca-e-notes').val(a.notes || '');
        $('#iris-ca-e-result').text('');
        $('#iris-ca-editor').hide();
        iris_ca_render_summary(a);

        var s = a.sightings || { cases: 0, alerts: 0 };
        $('#iris-ca-activity').html(
            iris_ca_kv('Cases', String(s.cases))
            + iris_ca_kv('Alerts', String(s.alerts))
            + iris_ca_kv('Timeline events', String(a.timeline_events || 0))
            + iris_ca_kv('First seen', iris_ca_esc(iris_ca_ts(a.first_seen)))
            + iris_ca_kv('Last seen', iris_ca_esc(iris_ca_ts(a.last_seen)))
            + iris_ca_kv('Compromise', iris_ca_comp_badge(a)));
        $('#iris-ca-record').html(
            iris_ca_kv('Origin', a.origin === 'manual'
                ? 'Manual' + (a.created_by ? ' <span class="text-muted">('
                  + iris_ca_esc(a.created_by) + ')</span>' : '')
                : 'Observed <span class="text-muted">(sync)</span>')
            + iris_ca_kv('Registry id', '<span style="font-size:0.75rem;">'
                + (iris_ca_id(a.id) || '') + '</span>'));
        $('#iris-ca-sight-count').text('(' + (s.cases + s.alerts) + ')');
        $('#iris-ca-tl-count').text('(' + (a.timeline_events || 0) + ')');
        // Fresh asset: back to Overview, invalidate the lazy Timeline tab.
        IRIS_CA._tlLoadedFor = null;
        $('#iris-ca-dtabs a[href="#iris-ca-tab-overview"]').tab('show');

        var det = a.sighting_details || { cases: [], alerts: [], cases_hidden_by_acl: 0 };
        // cid is interpolated into innerHTML below (alert links) —
        // digits only, else fall back to '1'.
        var cidm = window.location.search.match(/[?&]cid=(\d+)/);
        // The (\d+) capture is already digits-only, but taint tracking does
        // not credit a match group — route it through the id validator.
        var cid = iris_ca_id(cidm && cidm[1]) || '1';
        var html = '<div class="mb-1"><b>Cases</b></div>';
        html += (det.cases || []).map(function (c) {
            // Case names already carry the "#N - " prefix — do not prepend it again.
            var caseId = iris_ca_id(c.case_id);
            return '<div>' + (caseId
                    ? '<a href="/case?cid=' + caseId + '">' + iris_ca_esc(c.name) + '</a>'
                    : iris_ca_esc(c.name))
                + (c.closed ? ' <span class="text-muted">(closed)</span>' : '')
                + '</div>';
        }).join('') || '<div class="text-muted">none</div>';
        if (det.cases_hidden_by_acl > 0) {
            html += '<div class="text-muted">(' + det.cases_hidden_by_acl
                + ' case(s) hidden — no access)</div>';
        }
        html += '<div class="mt-2 mb-1"><b>Alerts</b></div>';
        html += (det.alerts || []).slice(0, 20).map(function (al) {
            var alertId = iris_ca_id(al.alert_id);
            return '<div>' + (alertId
                    ? '<a href="/alerts?alert_ids=' + alertId + '&cid=' + cid
                      + '">#' + alertId + '</a>'
                    : '#' + iris_ca_esc(al.alert_id))
                + ' ' + iris_ca_esc(al.title) + '</div>';
        }).join('') || '<div class="text-muted">none</div>';
        $('#iris-ca-sightings').html(html);

        iris_ca_fetch('/api/v2/customer-assets/' + assetId + '/changes').then(function (ch) {
            if (ch.__status !== 200) { return; }
            delete ch.__status;
            var list = Array.isArray(ch) ? ch : [];
            $('#iris-ca-changes').html(list.map(function (c) {
                return '<div>' + iris_ca_esc(iris_ca_ts(c.changed_at)) + ' · '
                    + iris_ca_esc(c.changed_by) + ': <b>' + iris_ca_esc(c.field)
                    + '</b> ' + iris_ca_esc(c.old_value == null ? '(unset)' : c.old_value)
                    + ' &rarr; ' + iris_ca_esc(c.new_value == null ? '(unset)' : c.new_value)
                    + '</div>';
            }).join('') || '<div class="text-muted">No changes recorded.</div>');
        });

        $('#iris-ca-detail').show();
        document.getElementById('iris-ca-detail').scrollIntoView({ behavior: 'smooth' });
    });
}

/* --------------------------------------------------------------- wiring */

$(function () {
    iris_ca_load();

    $('#iris-ca-refresh').on('click', iris_ca_load);
    $('#iris-ca-f-q, #iris-ca-f-env, #iris-ca-f-owner').on('keydown', function (e) {
        if (e.key === 'Enter') { iris_ca_load(); }
    });
    $('#iris-ca-f-customer, #iris-ca-f-type, #iris-ca-f-crit')
        .on('change', iris_ca_load);
    $('.iris-ca-chips').on('click', 'button', function () {
        var $g = $(this).closest('.iris-ca-chips');
        $g.find('button').removeClass('active');
        $(this).addClass('active');
        $g.attr('data-val', $(this).attr('data-val'));
        iris_ca_load();
    });

    $(document).on('click', '.iris-ca-row', function () {
        iris_ca_open($(this).attr('data-asset-id'));
    });
    $('#iris-ca-edit-toggle').on('click', function () {
        $('#iris-ca-editor').toggle();
    });
    // Timeline tab is lazy: linked master-timeline events load on first
    // open per asset (the count in the tab label comes with the detail).
    $('#iris-ca-dtabs a[href="#iris-ca-tab-timeline"]').on('shown.bs.tab', function () {
        if (!IRIS_CA._current) { return; }
        var id = IRIS_CA._current.id;
        if (IRIS_CA._tlLoadedFor === id) { return; }
        IRIS_CA._tlLoadedFor = id;
        iris_ca_fetch('/api/v2/customer-assets/' + id + '/timeline').then(function (tl) {
            if (tl.__status !== 200) { return; }
            delete tl.__status;
            var list = Array.isArray(tl) ? tl : [];
            $('#iris-ca-timeline').html(list.map(function (e) {
                return '<div class="iris-ca-kv"><span class="k" style="flex-basis: 150px;">'
                    + iris_ca_esc(iris_ca_ts(e.event_date)) + '</span><span class="v">'
                    + iris_ca_esc(e.title)
                    + ' <a href="/case/timeline?cid=' + e.case_id + '" class="text-muted"'
                    + ' style="font-size:0.72rem;">' + iris_ca_esc(e.case_name) + '</a>'
                    + '</span></div>';
            }).join('') || '<div class="text-muted">No linked timeline events'
                + ' in cases you can access.</div>');
        });
    });
    $('#iris-ca-detail-close').on('click', function () {
        $('#iris-ca-detail').hide();
        IRIS_CA._current = null;
    });

    $('#iris-ca-e-save').on('click', function () {
        if (!IRIS_CA._current) { return; }
        var body = {
            criticality: $('#iris-ca-e-crit').val() || null,
            environment: $('#iris-ca-e-env').val(),
            owner: $('#iris-ca-e-owner').val(),
            notes: $('#iris-ca-e-notes').val(),
            compromise_status: $('#iris-ca-e-comp').val() === ''
                ? null : parseInt($('#iris-ca-e-comp').val(), 10)
        };
        iris_ca_fetch('/api/v2/customer-assets/' + IRIS_CA._current.id, 'PUT', body)
            .then(function (j) {
                if (j.__status === 200) {
                    $('#iris-ca-e-result').html('<span class="text-success">saved</span>');
                    iris_ca_load();
                    iris_ca_open(IRIS_CA._current.id);
                } else {
                    $('#iris-ca-e-result').html('<span class="text-danger">'
                        + iris_ca_esc(j.message || ('HTTP ' + j.__status)) + '</span>');
                }
            });
    });

    $('#iris-ca-export').on('click', function (e) {
        e.preventDefault();
        window.location = '/api/v2/customer-assets/export' + iris_ca_filter_qs();
    });

    $('#iris-ca-import-btn').on('click', function () {
        $('#iris-ca-import-file').trigger('click');
    });
    $('#iris-ca-import-file').on('change', function () {
        var file = this.files[0];
        if (!file) { return; }
        var fd = new FormData();
        fd.append('file', file);
        fd.append('csrf_token', iris_ca_csrf());   // multipart: token as form field
        $('#iris-ca-action-result').text('importing…');
        fetch('/api/v2/customer-assets/import',
              { method: 'POST', body: fd, credentials: 'same-origin' })
            .then(function (r) { return r.json().then(function (j) { j.__status = r.status; return j; }); })
            .then(function (j) {
                if (j.__status === 200) {
                    var msg = j.imported + ' imported';
                    if ((j.errors || []).length) {
                        msg += ', ' + j.errors.length + ' error(s)';
                        alert('Import errors:\n' + j.errors.join('\n'));
                    }
                    $('#iris-ca-action-result').html('<span class="text-success">'
                        + iris_ca_esc(msg) + '</span>');
                    iris_ca_load();
                } else {
                    $('#iris-ca-action-result').html('<span class="text-danger">import '
                        + 'failed (HTTP ' + j.__status + ')</span>');
                }
                $('#iris-ca-import-file').val('');
            });
    });

    $('#iris-ca-scan').on('click', function () {
        if (!confirm('Scan every case and alert asset into the registry? '
                     + 'Existing entries and curation are preserved.')) { return; }
        iris_ca_fetch('/api/v2/customer-assets/scan', 'POST', {}).then(function (j) {
            if (j.__status === 202) {
                $('#iris-ca-action-result').html('<span class="text-success">scan '
                    + 'queued — refresh in a moment</span>');
                setTimeout(iris_ca_load, 4000);
            } else if (j.__status === 403) {
                $('#iris-ca-action-result').html('<span class="text-danger">scan '
                    + 'requires administrator</span>');
            } else {
                $('#iris-ca-action-result').html('<span class="text-danger">scan '
                    + 'failed (HTTP ' + j.__status + ')</span>');
            }
        });
    });
});

/* iris-ng: v3-parity Customers view (master/detail + contacts).
 *
 * Overlay, not rebuild: list from /manage/customers/list, detail + contacts
 * from /manage/customers/<id> (the endpoint that already dumps contacts),
 * Add/Edit through the EXISTING customer modal (add_customer /
 * customer_detail in manage.customers.js — refresh_customer_table is wrapped
 * so modal saves refresh this view), Delete through the existing
 * delete_customer, and contacts through the EXISTING contact modal routes
 * (mirroring view.customers.js, but refreshing the pane instead of
 * window.location.reload — that page reloads because it IS the customer).
 *
 * Absent-data discipline: list null = "have not looked"; the detail pane and
 * the contacts section each track fetching/failed separately, so "no
 * contacts" is only ever claimed after a successful fetch said so.
 */

var IRIS_CUST = {
    rows: null,          // null = not looked; [] = looked, none
    fetching: false,
    failed: null,
    search: '',
    selected: null,      // customer_id
    detail: null,        // full payload of the selected customer (has contacts)
    detailFetching: false,
    detailFailed: null
};

function iris_cust_esc(s) {
    return $('<div>').text(s === null || s === undefined ? '' : String(s)).html();
}

function iris_cust_fetch(force) {
    if (IRIS_CUST.fetching) { return; }
    if (!force && Array.isArray(IRIS_CUST.rows)) { iris_cust_render(); return; }
    IRIS_CUST.fetching = true;
    IRIS_CUST.failed = null;
    iris_cust_render();
    get_request_api('/manage/customers/list')
    .done(function (data) {
        IRIS_CUST.rows = (data && data.data) ? data.data : [];
    })
    .fail(function (xhr) {
        IRIS_CUST.failed = 'HTTP ' + (xhr && xhr.status ? xhr.status : '?');
    })
    .always(function () {
        IRIS_CUST.fetching = false;
        iris_cust_render();
    });
}

function iris_cust_select(cid) {
    IRIS_CUST.selected = cid;
    IRIS_CUST.detail = null;
    IRIS_CUST.detailFailed = null;
    iris_cust_render();
    iris_cust_fetch_detail(cid);
}

function iris_cust_fetch_detail(cid) {
    if (IRIS_CUST.detailFetching) { return; }
    IRIS_CUST.detailFetching = true;
    get_request_api('/manage/customers/' + cid)
    .done(function (data) {
        if (String(IRIS_CUST.selected) === String(cid)) {
            IRIS_CUST.detail = (data && data.data) ? data.data : null;
        }
    })
    .fail(function (xhr) {
        if (String(IRIS_CUST.selected) === String(cid)) {
            IRIS_CUST.detailFailed = 'HTTP ' + (xhr && xhr.status ? xhr.status : '?');
        }
    })
    .always(function () {
        IRIS_CUST.detailFetching = false;
        iris_cust_render_detail();
    });
}

function iris_cust_filtered() {
    var rows = IRIS_CUST.rows || [];
    var q = (IRIS_CUST.search || '').toLowerCase();
    if (!q) { return rows; }
    return rows.filter(function (r) {
        return [r.customer_name, r.customer_description].some(function (v) {
            return v !== null && v !== undefined
                && String(v).toLowerCase().indexOf(q) !== -1;
        });
    });
}

function iris_cust_render() {
    var $rows = $('#iris-cust-rows');
    if (IRIS_CUST.failed) {
        $('#iris-cust-count').text('');
        $rows.html('<div class="iris-co-empty">Could not load customers ('
            + iris_cust_esc(IRIS_CUST.failed) + '). Refresh to retry.</div>');
        return;
    }
    if (!Array.isArray(IRIS_CUST.rows)) {
        $('#iris-cust-count').text('');
        $rows.html('<div class="iris-co-empty">Loading…</div>');
        return;
    }
    var all = IRIS_CUST.rows;
    var shown = iris_cust_filtered();
    $('#iris-cust-count').text(shown.length + ' / ' + all.length);
    if (!all.length) {
        $rows.html('<div class="iris-co-empty">No customers yet.</div>');
        iris_cust_render_detail();
        return;
    }
    if (!shown.length) {
        $rows.html('<div class="iris-co-empty">No match for the current search.</div>');
        return;
    }
    var sel = IRIS_CUST.selected;
    $rows.html(shown.map(function (r) {
        return '<div class="iris-co-row' + (String(r.customer_id) === String(sel) ? ' selected' : '')
            + '" data-id="' + iris_cust_esc(r.customer_id) + '">'
            + '<div class="iris-co-row-main">'
            + '<div class="iris-co-row-name">' + iris_cust_esc(r.customer_name) + '</div>'
            + '<div class="iris-co-row-desc">' + iris_cust_esc(r.customer_description) + '</div>'
            + '</div><span class="iris-co-row-id">#' + iris_cust_esc(r.customer_id) + '</span></div>';
    }).join(''));
    iris_cust_render_detail();
}

function iris_cust_render_detail() {
    var $d = $('#iris-cust-detail');
    var cid = IRIS_CUST.selected;
    if (cid === null || cid === undefined) {
        $d.html('<div class="iris-co-empty">Select a customer to see its details.</div>');
        return;
    }
    if (IRIS_CUST.detailFailed) {
        $d.html('<div class="iris-co-empty">Could not load this customer ('
            + iris_cust_esc(IRIS_CUST.detailFailed) + ').</div>');
        return;
    }
    var det = IRIS_CUST.detail;
    if (!det) {
        $d.html('<div class="iris-co-empty">Loading…</div>');
        return;
    }

    var html = '<div class="iris-co-d-head">'
        + '<span class="iris-co-d-eyebrow">Details</span>'
        + '<span class="iris-co-d-name">' + iris_cust_esc(det.customer_name) + '</span>'
        + '<span class="iris-co-d-actions">'
        + '<a class="btn btn-sm btn-dark" href="/manage/customers/' + iris_cust_esc(det.customer_id)
        + '/view' + case_param() + '" title="Cases, assets and stats for this customer">Open full view</a>'
        + '<button type="button" class="btn btn-sm btn-dark" id="iris-cust-edit">Edit</button>'
        + '<button type="button" class="btn btn-sm btn-outline-danger" id="iris-cust-del">Delete</button>'
        + '</span></div>';

    var sectors = (det.customer_dhs_sectors || '')
        .split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    var fields = [
        ['Name', det.customer_name],
        ['Customer ID', '#' + det.customer_id],
        ['Description', det.customer_description],
        ['SLA', det.customer_sla],
        ['Sectors', sectors.length ? sectors.join(', ') : null]
    ];
    html += '<div class="iris-co-fields">';
    fields.forEach(function (f) {
        var v = (f[1] === null || f[1] === undefined || f[1] === '')
            ? '<span class="text-muted">—</span>' : iris_cust_esc(f[1]);
        html += '<div><div class="iris-co-f-label">' + iris_cust_esc(f[0])
            + '</div><div class="iris-co-f-value">' + v + '</div></div>';
    });
    html += '</div>';

    // contacts — this payload came from a successful /manage/customers/<id>
    // fetch, so an empty list here really is "no contacts".
    var contacts = det.contacts || [];
    html += '<div class="iris-cust-contacts"><div class="iris-cust-contacts-head">'
        + '<span class="iris-co-d-eyebrow">Contacts</span>'
        + '<span class="iris-co-row-id">' + contacts.length + '</span>'
        + '<span class="iris-co-d-actions">'
        + '<button type="button" class="btn btn-sm btn-primary" id="iris-cust-add-contact">+ Add contact</button>'
        + '</span></div>';
    if (!contacts.length) {
        html += '<div class="iris-co-empty">No contacts. Add one to get started.</div>';
    } else {
        html += contacts.map(function (ct) {
            var meta = [ct.contact_role, ct.contact_email, ct.contact_work_phone,
                        ct.contact_mobile_phone].filter(Boolean).join(' · ');
            return '<div class="iris-cust-contact" data-contact-id="' + iris_cust_esc(ct.id) + '" '
                + 'title="Click to edit">'
                + '<div class="iris-co-row-main">'
                + '<div class="iris-cust-contact-name">' + iris_cust_esc(ct.contact_name) + '</div>'
                + '<div class="iris-cust-contact-meta">' + iris_cust_esc(meta) + '</div>'
                + (ct.contact_note
                    ? '<div class="iris-cust-contact-meta">' + iris_cust_esc(ct.contact_note) + '</div>' : '')
                + '</div></div>';
        }).join('');
    }
    html += '</div>';
    $d.html(html);

    $('#iris-cust-edit').on('click', function () { customer_detail(cid); });
    $('#iris-cust-del').on('click', function () { delete_customer(cid); });
    $('#iris-cust-add-contact').on('click', function () { iris_cust_add_contact(cid); });
    $d.find('.iris-cust-contact').on('click', function () {
        iris_cust_edit_contact($(this).attr('data-contact-id'), cid);
    });
}

/* Contact modals — the EXISTING routes + templates the customer view page
 * uses; only the after-save action differs (refresh the pane, the view page
 * reloads itself because it IS the customer). */
function iris_cust_add_contact(customer_id) {
    var url = '/manage/customers/' + customer_id + '/contacts/add/modal' + case_param();
    $('#modal_add_contact_content').load(url, function (response, status, xhr) {
        if (status !== "success") {
            ajax_notify_error(xhr, url);
            return false;
        }
        $('#form_new_contact').on("submit", preventFormDefaultBehaviourOnSubmit);
        $('#submit_new_contact').on("click", function () {
            var form = $('#form_new_contact').serializeObject();
            post_request_api('/manage/customers/' + customer_id + '/contacts/add',
                             JSON.stringify(form), true)
            .done(function (data) {
                if (notify_auto_api(data)) {
                    $('#modal_add_contact').modal('hide');
                    iris_cust_fetch_detail(customer_id);
                }
            });
            return false;
        });
    });
    $('#modal_add_contact').modal({ show: true });
}

function iris_cust_edit_contact(contact_id, customer_id) {
    var url = '/manage/customers/' + customer_id + '/contacts/' + contact_id + '/modal' + case_param();
    $('#modal_add_contact_content').load(url, function (response, status, xhr) {
        if (status !== "success") {
            ajax_notify_error(xhr, url);
            return false;
        }
        $('#form_new_contact').on("submit", preventFormDefaultBehaviourOnSubmit);
        $('#submit_new_contact').on("click", function () {
            var form = $('#form_new_contact').serializeObject();
            post_request_api('/manage/customers/' + customer_id + '/contacts/' + contact_id + '/update',
                             JSON.stringify(form), true)
            .done(function (data) {
                if (notify_auto_api(data)) {
                    $('#modal_add_contact').modal('hide');
                    iris_cust_fetch_detail(customer_id);
                }
            });
            return false;
        });
        $('#submit_delete_contact').on("click", function () {
            post_request_api('/manage/customers/' + customer_id + '/contacts/' + contact_id + '/delete')
            .done(function (data) {
                if (notify_auto_api(data)) {
                    $('#modal_add_contact').modal('hide');
                    iris_cust_fetch_detail(customer_id);
                }
            });
            return false;
        });
    });
    $('#modal_add_contact').modal({ show: true });
}

$(function () {
    // Modal saves call refresh_customer_table(); wrap it so this view
    // re-fetches too (and the detail, in case the selected customer changed).
    var orig = window.refresh_customer_table;
    if (typeof orig === 'function') {
        window.refresh_customer_table = function () {
            var out = orig.apply(this, arguments);
            iris_cust_fetch(true);
            if (IRIS_CUST.selected !== null && IRIS_CUST.selected !== undefined) {
                iris_cust_fetch_detail(IRIS_CUST.selected);
            }
            return out;
        };
    }

    $('#iris-cust-rows').on('click', '.iris-co-row', function () {
        iris_cust_select($(this).attr('data-id'));
    });
    $('#iris-cust-search').on('input', function () {
        IRIS_CUST.search = $(this).val();
        iris_cust_render();
    });
    $('#iris-cust-refresh').on('click', function () {
        iris_cust_fetch(true);
        if (IRIS_CUST.selected !== null && IRIS_CUST.selected !== undefined) {
            iris_cust_fetch_detail(IRIS_CUST.selected);
        }
    });

    iris_cust_fetch(false);
});

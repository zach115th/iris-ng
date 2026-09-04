function update_settings() {
    var data_sent = $('form#form_srv_settings').serializeObject();
    data_sent['prevent_post_mod_repush'] = $('#prevent_post_mod_repush').is(":checked");
    data_sent['prevent_post_objects_repush'] = $('#prevent_post_objects_repush').is(":checked");
    data_sent['password_policy_upper_case'] = $('#password_policy_upper_case').is(":checked");
    data_sent['password_policy_lower_case'] = $('#password_policy_lower_case').is(":checked");
    data_sent['password_policy_digit'] = $('#password_policy_digit').is(":checked");
    data_sent['enforce_mfa'] = $('#enforce_mfa').is(":checked");
    // iris-ng v2: Mail tab checkboxes (serializeObject drops unchecked boxes)
    data_sent['mail_ingest_enabled'] = $('#mail_ingest_enabled').is(":checked");
    data_sent['mail_imap_ssl'] = $('#mail_imap_ssl').is(":checked");
    data_sent['mail_ai_triage_enabled'] = $('#mail_ai_triage_enabled').is(":checked");
    data_sent['email_notifications_enabled'] = $('#email_notifications_enabled').is(":checked");
    data_sent['password_policy_min_length'] = $('#password_policy_min_length').val().toString();

    // Collect per-feature backend overrides into a single dict.
    // Empty string = "Default (global)" → store as null (omit from dict so
    // the backend treats it as "follow the global radio").
    var featureOverrides = {};
    $('.iris-feat-override').each(function () {
        var key = $(this).data('feat');
        var val = $(this).val();
        featureOverrides[key] = val ? val : null;
    });
    data_sent['ai_feature_overrides'] = featureOverrides;

    // iris-ng v2 Phase 5: org-wide notification defaults matrix.
    var notifDefaults = {};
    $('.iris-nd-toggle').each(function () {
        var ev = $(this).attr('data-event');
        var ch = $(this).attr('data-channel');
        if (!notifDefaults[ev]) { notifDefaults[ev] = {}; }
        notifDefaults[ev][ch] = $(this).is(':checked');
    });
    if (Object.keys(notifDefaults).length) {
        data_sent['notification_defaults'] = notifDefaults;
    }

    // Marshmallow Integer(allow_none=True) rejects empty strings — convert to null.
    ['retention_months', 'capacity_planning_window_months', 'capacity_planning_target_months',
     'mail_imap_port', 'mail_smtp_port', 'mail_poll_interval_minutes'].forEach(function(k) {
        if (data_sent[k] === '') { data_sent[k] = null; }
    });

    post_request_api('/manage/settings/update', JSON.stringify(data_sent), true)
    .done((data) => {
        notify_auto_api(data);
    });
}


function init_db_backup() {

    get_request_api('/manage/server/backups/make-db')
    .done((data) => {
            msg = ""
            for (idx in data.data) {
                msg += data.data[idx] + '\n';
            }
            swal("Done",
             msg,
            {
                icon: "success"
            });
    })
    .fail((error) => {
        // Upstream read `data.data` (the .done parameter) off an
        // uninitialized `msg` here, so every backup FAILURE threw a
        // ReferenceError instead of showing the error dialog.
        msg = "";
        var rows = (error.responseJSON && error.responseJSON.data)
            ? error.responseJSON.data
            : [error.statusText || 'Backup request failed'];
        for (idx in rows) {
            msg += rows[idx] + '\n';
        }

        swal("Error",
         msg,
        {
            icon: "error"
        });
    });
}
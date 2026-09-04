/* Add-event modal loader — EXTRACTED from case.timeline.js so the Assets
 * and IOC pages can open the REAL modal in place instead of navigating to
 * the timeline page. The timeline page loads this file before
 * case.timeline.js (which no longer defines these), so the timeline keeps
 * the exact code it always had.
 *
 * Page contract: a #modal_add_event / #modal_add_event_content container
 * in the DOM, plus the shared helpers every case page already loads
 * (case_param, ACE, select2, selectpicker, custom attributes). Two
 * timeline-only touches are guarded by typeof: current_timeline (the
 * parent-event list — empty elsewhere) and apply_filtering (the page
 * refresh). Other pages refresh via an optional window.iris_event_saved
 * hook instead. */

var g_event_desc_editor = null;

function edit_in_event_desc() {
    if($('#container_event_desc_content').is(':visible')) {
        $('#container_event_description').show(100);
        $('#container_event_desc_content').hide(100);
        $('#event_edition_btn').hide(100);
        $('#event_preview_button').hide(100);
    } else {
        $('#event_preview_button').show(100);
        $('#event_edition_btn').show(100);
        $('#container_event_desc_content').show(100);
        $('#container_event_description').hide(100);
    }
}

/* Fetch a modal that allows to add an event.
 * preset ({asset: id} or {ioc: id}) rides from the Assets/IOC pages'
 * Timeline tabs — the SERVER validates the id against the case before
 * preselecting it in the picker. */
function add_event(parent_event_id = null, preset = null) {
    url = 'timeline/events/add/modal' + case_param();
    if (preset && preset.asset) {
        url += '&preset_asset=' + encodeURIComponent(preset.asset);
    }
    if (preset && preset.ioc) {
        url += '&preset_ioc=' + encodeURIComponent(preset.ioc);
    }
    $('#modal_add_event_content').load(url, function (response, status, xhr) {
        hide_minimized_modal_box();
        if (status !== "success") {
             ajax_notify_error(xhr, url);
             return false;
        }

        g_event_desc_editor = get_new_ace_editor('event_description', 'event_desc_content', 'target_event_desc',
                            function() {
                                $('#last_saved').addClass('btn-danger').removeClass('btn-success');
                                $('#last_saved > i').attr('class', "fa-solid fa-file-circle-exclamation");
                            }, null);

        g_event_desc_editor.setOption("minLines", "10");
        let headers = get_editor_headers('g_event_desc_editor', null, 'event_edition_btn');
        $('#event_edition_btn').append(headers);
        edit_in_event_desc();

        let parent_selector = $('#parent_event_id');

        // Add empty option
        let option = $('<option>');
        option.attr('value', '');
        option.text('No parent event');
        parent_selector.append(option);

        // Add all events to the parent selector. current_timeline is the
        // timeline page's own global — undeclared on the Assets/IOC pages,
        // so a bare reference would throw, not just iterate nothing.
        let tl_events = (typeof current_timeline !== 'undefined'
            && current_timeline) ? current_timeline : [];
        for (let idx in tl_events) {
            let event = tl_events[idx];
            let option = $('<option>');
            option.attr('value', event.event_id);
            option.text(`${event.event_title}`);
            parent_selector.append(option);
        }

        parent_selector.selectpicker({
            liveSearch: true,
            size: 10,
            width: '100%',
            title: 'Select a parent event',
            style: 'btn-light',
            noneSelectedText: 'No event selected',
        });

        if (parent_event_id != null) {
            parent_selector.selectpicker('val', parent_event_id);
            parent_selector.selectpicker("refresh");
        }

        $('#submit_new_event').on("click", function () {
            clear_api_error();
            var data_sent = $('#form_new_event').serializeObject();
            data_sent['event_date'] = `${$('#event_date').val()}T${$('#event_time').val()}`;
            // event_verdict comes through serializeObject() from the <select>;
            // the server derives event_in_summary / event_in_graph / event_color
            // from it. Do NOT read the old checkboxes here -- they no longer
            // exist, and .is(':checked') on a missing element returns false.
            data_sent['event_sync_iocs_assets'] = $('#event_sync_iocs_assets').is(':checked');
            data_sent['event_tags'] = $('#event_tags').val();
            data_sent['event_assets'] = $('#event_assets').val();
            data_sent['event_iocs'] = $('#event_iocs').val();
            data_sent['event_tz'] = $('#event_tz').val();
            data_sent['event_content'] = g_event_desc_editor.getValue();
            data_sent['parent_event_id'] = $('#parent_event_id').val() || null;

            ret = get_custom_attributes_fields();
            has_error = ret[0].length > 0;
            attributes = ret[1];

            if (has_error){return false;}

            data_sent['custom_attributes'] = attributes;

            post_request_api('/case/timeline/events/add', JSON.stringify(data_sent), true)
            .done((data) => {
                if(notify_auto_api(data)) {
                    window.location.hash = data.data.event_id;
                    /* timeline page refresh; other pages hook instead */
                    if (typeof apply_filtering === 'function') {
                        apply_filtering();
                    }
                    if (typeof window.iris_event_saved === 'function') {
                        window.iris_event_saved(data.data);
                    }
                    $('#modal_add_event').modal('hide');
                }
            });

            return false;
        })

        $('#modal_add_event').modal({ show: true });
        $('#event_title').focus();

    });
}


function objectToQueryString(obj) {
  return Object.keys(obj)
    .filter(key => obj[key] !== undefined && obj[key] !== null && obj[key] !== '')
    .map(key => encodeURIComponent(key) + '=' + encodeURIComponent(obj[key]))
    .join('&');
}

async function fetchAlert(alertId) {
    const response = get_raw_request_api(`/alerts/${alertId}?cid=${get_caseid()}`);
    return await response;
}

async function fetchMultipleAlerts(alertIds) {
    const response = get_raw_request_api(`/alerts/filter?cid=${get_caseid()}&alert_ids=${alertIds.join(',')}`);
    return await response;
}


let alertStatusList = {};
let alertResolutionList = {};

function getAlertStatusList() {
    get_request_api('/manage/alert-status/list')
        .then((data) => {
            if (api_request_failed(data)) {
                return;
            }
            alertStatusList = data.data;
        });
}

function getAlertResolutionList() {
    get_request_api('/manage/alert-resolutions/list')
        .then((data) => {
            if (api_request_failed(data)) {
                return;
            }
            alertResolutionList = data.data;
        });
}

function getAlertStatusId(statusName) {
    const status = alertStatusList.find((status) => status.status_name === statusName);
    return status ? status.status_id : undefined;
}

function getAlertResolutionId(resolutionName) {
    if (alertResolutionList.length === undefined) {
        getAlertResolutionList();
    }
    const resolution = alertResolutionList.find((resolution) => resolution.resolution_status_name.toLowerCase().replaceAll(' ', '_') === resolutionName);
    return resolution ? resolution.resolution_status_id : undefined;
}

function appendLabels(list, items, itemType) {
    items.forEach((item) => {
        const label = $('<label></label>').addClass('d-block');
        const input = $('<input>').attr({
            type: 'checkbox',
            name: itemType,
            value: filterXSS(item[itemType + '_name'] || item[itemType + '_value']),
            id: item[itemType + '_uuid'],
            checked: true,
        });
        label.append(input);
        label.append(`${filterXSS(item[itemType + '_name'] || item[itemType + '_value'])}`);
        list.append(label);
    });
}

function toggleSelectDeselect(toggleButton, listSelector) {
    let allChecked = true;
    $(listSelector).each(function () {
        if (!$(this).prop("checked")) {
            allChecked = false;
        }
        $(this).prop("checked", !$(this).prop("checked"));
    });

    if (allChecked) {
        toggleButton.text("Select All");
    } else {
        toggleButton.text("Deselect All");
    }
}

function unlinkAlertFromCase(alert_id, case_id) {

    do_deletion_prompt(`Unlink alert #${alert_id} from the case #${case_id}?`, true)
        .then( () => {
            unlinkAlertFromCaseRequest(alert_id, case_id)
                .then((data) => {
                    notify_auto_api(data);
                    if (data.status !== 'success') {
                        return;
                    }
                    refreshAlert(alert_id);
                });
    });

}

async function unlinkAlertFromCaseRequest(alert_id, case_id) {
    return await post_request_api(`/alerts/unmerge/${alert_id}`, JSON.stringify({
        target_case_id: case_id,
        csrf_token: $('#csrf_token').val()
    }));
}

function mergeMultipleAlertsModal() {
    const selectedAlerts = getBatchAlerts();
    const escalateButton = $("#escalateOrMergeButton");
    if (selectedAlerts.length === 0) {
        notify_error('Please select at least one alert to perform this action on.');
        return;
    }
    fetchMultipleAlerts(selectedAlerts)
        .then((alertDataReq) => {
            if (api_request_failed(alertDataReq)) {
                return;
            }
            const ioCsList = $("#ioCsList");
                const assetsList = $("#assetsList");

                // Configure the modal for both escalation and merging
                $('#escalateModalLabel').text('Merge multiple alerts in a new case');
                $('#escalateModalExplanation').text('These alerts will be merged into a new case. Set the case title and select the IOCs and Assets to escalate into the case.');
                $('#modalAlertTitleContainer').hide();

                $('#modalEscalateCaseTitle').val(`[ALERT] Escalation of ${selectedAlerts.length} alerts`);
                $('#modalEscalateCaseTitleContainer').show();

                escalateButton.attr("data-merge", false);
                $('#mergeAlertCaseSelectSection').hide();

                const case_tags = $('#case_tags');

                case_tags.val('')
                case_tags.amsifySuggestags({
                    printValues: false,
                    suggestions: []
                });

                // Load case options for merging
                var options = {
                    ajax: {
                        url: '/context/search-cases' + case_param(),
                        type: 'GET',
                        dataType: 'json'
                    },
                    minLength: 0,
                    clearOnEmpty: false,
                    emptyRequest: true,
                    locale: {
                        emptyTitle: 'Select and Begin Typing',
                        statusInitialized: '',
                    },
                    preprocessData: function (data) {
                        return context_data_parser(data);
                    },
                    preserveSelected: false
                };
                get_request_api('/context/search-cases')
                    .done((data) => {
                        if (api_request_failed(data)) {
                            return;
                        }
                        mergeAlertCasesSelectOption(data);
                        $('#mergeAlertCaseSelect').ajaxSelectPicker(options);

                        get_request_api('/manage/case-templates/list')
                        .done((dataTemplate) => {
                            if (api_request_failed(dataTemplate)) {
                                return;
                            }
                            dataTemplate = dataTemplate.data;
                            const templateSelect = $('#mergeAlertCaseTemplateSelect');
                            templateSelect.html('');
                            templateSelect.append('<option value="">Select a template</option>');
                            for (let i = 0; i < dataTemplate.length; i++) {
                                templateSelect.append(`<option value="${dataTemplate[i].id}">${filterXSS(dataTemplate[i].display_name)}</option>`);
                            }
                            templateSelect.selectpicker('refresh');

                            // Clear the lists
                            ioCsList.html("");
                            assetsList.html("");

                            let alertsData = alertDataReq.data;

                            for (let i = 0; i < alertsData.length; i++) {
                                let alertData = alertsData[i];
                                if (alertData.iocs.length !== 0) {
                                    appendLabels(ioCsList, alertData.iocs, 'ioc');
                                }
                                if (alertData.assets.length !== 0) {
                                    appendLabels(assetsList, alertData.assets, 'asset');
                                }
                            }

                            escalateButton.attr("data-merge", false);
                            escalateButton.attr("data-multi-merge", true);
                            $("#escalateOrMergeButton").attr('onclick',
                                `mergeAlertClicked("${selectedAlerts.join(',')}");`);

                            $('#escalateModal').modal('show');

                            $("input[type='radio'][name='mergeOption']:checked").trigger("change");

                            $("input[type='radio'][name='mergeOption']").off('change').on("change", function () {
                                if ($(this).val() === "existing_case") {
                                    $('#escalateModalLabel').text(`Merge ${selectedAlerts.length} alerts in an existing case`);
                                    $('#escalateModalExplanation').text('These alerts will be merged into the selected case. Select the IOCs and Assets to merge into the case.');
                                    $('#mergeAlertCaseSelectSection').show();
                                    $('#mergeAlertCaseTemplateSection').hide();
                                    $('#modalEscalateCaseTitleContainer').hide();
                                    $('#mergeAlertCaseSelect').selectpicker('refresh');
                                    $('#mergeAlertCaseSelect').selectpicker('val', get_caseid());
                                    escalateButton.data("merge", true);
                                } else {
                                    console.log('change')
                                    $('#escalateModalLabel').text(`Merge ${selectedAlerts.length} alerts in new case`);
                                    $('#escalateModalExplanation').text('This alert will be merged into a new case. Set the case title and select the IOCs and Assets to merge into the case.');
                                    $('#mergeAlertCaseSelectSection').hide();
                                    $('#mergeAlertCaseTemplateSection').show();
                                    $('#modalEscalateCaseTitleContainer').show();
                                    escalateButton.data("merge", false);
                                }
                            });
                        });
                    });
        });


}

function showEscalationModal() {
    $("#escalateModal").modal("show");
}

function mergeAlertModal(alert_id, existing_case = false) {

    const escalateButton = $("#escalateOrMergeButton");
    escalateButton.attr("data-alert-id", alert_id);

    let alertDataReq = null;
    const ioCsList = $("#ioCsList");
    const assetsList = $("#assetsList");

    fetchAlert(alert_id)
        .then((data) => {
            if (data.status !== 'success') {
                notify_api_request_error(data);
            }
            alertDataReq = data;
            let alert_title = filterXSS(alertDataReq.data.alert_title);

            $("#modalAlertTitle").val(alert_title);

            // Configure the modal for both escalation and merging
            $('#escalateModalLabel').html(`Merge alert #${alert_id} in a new case`);
            $('#escalateModalLabel')[0].offsetHeight;

            $('#escalateModalExplanation').text('This alert will be escalated into a new case. Set a title and select the IOCs and Assets to escalate into the case.');

            $('#modalEscalateCaseTitle').val(`[ALERT] ${alert_title}`);
            $('#modalEscalateCaseTitleContainer').show();

            escalateButton.attr("data-merge", false);
            $('#mergeAlertCaseSelectSection').hide();

            const case_tags = $('#case_tags');

            case_tags.val(alertDataReq.data.alert_tags)
            case_tags.amsifySuggestags({
                printValues: false,
                suggestions: []
            });

            // Load case options for merging
            var options = {
                ajax: {
                    url: '/context/search-cases' + case_param(),
                    type: 'GET',
                    dataType: 'json'
                },
                minLength: 0,
                clearOnEmpty: false,
                emptyRequest: true,
                locale: {
                    emptyTitle: 'Select and Begin Typing',
                    statusInitialized: '',
                },
                preprocessData: function (data) {
                    return context_data_parser(data, false);
                },
                preserveSelected: false
            };

            get_request_api('/context/search-cases')
            .done((data) => {
                if (api_request_failed(data)) {
                    return;
                }
                mergeAlertCasesSelectOption(data);
                $('#mergeAlertCaseSelect').ajaxSelectPicker(options);

                get_request_api('/manage/case-templates/list')
                .done((data) => {
                    if (api_request_failed(data)) {
                        return;
                    }
                    data = data.data;
                    const templateSelect = $('#mergeAlertCaseTemplateSelect');
                    templateSelect.html('');
                    templateSelect.append('<option value="">Select a template</option>');
                    for (let i = 0; i < data.length; i++) {
                        templateSelect.append(`<option value="${data[i].id}">${filterXSS(data[i].display_name)}</option>`);
                    }
                    templateSelect.selectpicker('refresh');

                    // Clear the lists
                    ioCsList.html("");
                    assetsList.html("");

                    if (api_request_failed(alertDataReq)) {
                        return;
                    }

                    let alertData = alertDataReq.data;

                    if (alertData.iocs.length !== 0) {
                        appendLabels(ioCsList, alertData.iocs, 'ioc');
                        $("#toggle-iocs").off("click").on("click", function () {
                            toggleSelectDeselect($(this), "#ioCsList input[type='checkbox']");
                        });
                        $("#ioc-container").show();
                    } else {
                        $("#ioc-container").show();
                    }

                    if (alertData.assets.length !== 0) {
                        appendLabels(assetsList, alertData.assets, 'asset');
                        $("#toggle-assets").off("click").on("click", function () {
                            toggleSelectDeselect($(this), "#assetsList input[type='checkbox']");
                        });
                        $("#asset-container").show();
                    } else {
                        $("#asset-container").hide();
                    }


                    $("input[type='radio'][name='mergeOption']:checked").trigger("change");

                    $("input[type='radio'][name='mergeOption']").off("change").on("change", function () {
                        if ($(this).val() === "existing_case") {
                            $('#escalateModalLabel').text(`Merge alert #${alert_id} in existing case`);
                            $('#escalateModalExplanation').text('This alert will be merged into the selected case. Select the IOCs and Assets to merge into the case.');
                            $('#mergeAlertCaseSelectSection').show();
                            $('#mergeAlertCaseTemplateSection').hide();
                            $('#modalEscalateCaseTitleContainer').hide();
                            $('#mergeAlertCaseSelect').selectpicker('refresh');
                            $('#mergeAlertCaseSelect').selectpicker('val', get_caseid());
                            escalateButton.data("merge", true);
                        } else {
                            $('#escalateModalLabel').text(`Merge alert #${alert_id} in new case`);
                            $('#escalateModalExplanation').text('This alert will be merged into a new case. Set the case title and select the IOCs and Assets to merge into the case.');
                            $('#mergeAlertCaseSelectSection').hide();
                            $('#mergeAlertCaseTemplateSection').show();
                            $('#modalEscalateCaseTitleContainer').show();
                            escalateButton.data("merge", false);
                        }
                    });

                    $("#escalateOrMergeButton").attr('onclick',
                        `mergeAlertClicked(${alert_id});`);

                    $("#escalateModal").modal("show");
                    if (existing_case) {
                        $("input[type='radio'][name='mergeOption'][value='existing_case']").prop('checked', true).trigger('change');
                    }
                });
            });


        });

}




function mergeAlertCasesSelectOption(data) {
    if (api_request_failed(data)) {
        return;
    }
    $('#mergeAlertCaseSelect').empty();

    $('#mergeAlertCaseSelect').append('<optgroup label="Open" id="switchMergeAlertCasesOpen"></optgroup>');
    $('#mergeAlertCaseSelect').append('<optgroup label="Closed" id="switchMergeAlertCasesClose"></optgroup>');
    let ocs = data.data;
    let ret_data = [];
    for (index in ocs) {
        let case_name = sanitizeHTML(ocs[index].name);
        let cs_name = sanitizeHTML(ocs[index].customer_name);
        ret_data.push({
                    'value': ocs[index].case_id,
                    'text': `${case_name} (${cs_name}) ${ocs[index].access}`
                });
        if (ocs[index].close_date != null) {
            $('#switchMergeAlertCasesClose').append(`<option value="${ocs[index].case_id}">${case_name} (${cs_name}) ${ocs[index].access}</option>`);
        } else {
            $('#switchMergeAlertCasesOpen').append(`<option value="${ocs[index].case_id}">${case_name} (${cs_name}) ${ocs[index].access}</option>`)
        }
    }

    return ret_data;
}

function fetchSmartRelations(alert_id) {
    $(`input[name="open_alerts_${alert_id}"]`).prop('checked', true);
    $(`input[name="closed_alerts_${alert_id}"]`).prop('checked', true);
    $(`input[name="open_cases_${alert_id}"]`).prop('checked', true);
    $(`input[name="closed_cases_${alert_id}"]`).prop('checked', true);

    fetchSimilarAlerts(alert_id, false, true, true,
        true, true);
}

function buildAlertLink(alert_id){
    const current_path = location.protocol + '//' + location.host
    return current_path + '/alerts' + case_param() + '&alert_ids=' + alert_id;
}

function copyAlertLink(alert_id) {
    const link = buildAlertLink(alert_id);
    navigator.clipboard.writeText(link).then(function() {
        notify_success('Link copied');
    }, function(err) {
        notify_error('Can\'t copy link. I printed it in console.');
        console.error('Shared link', err);
    });
}

function copyMDAlertLink(alert_id){
    const link = `[<i class="fa-solid fa-bell"></i> #${alert_id}](${buildAlertLink(alert_id)})`;
    navigator.clipboard.writeText(link).then(function() {
        notify_success('MD link copied');
    }, function(err) {
        notify_error('Can\'t copy link. I printed it in console.');
        console.error('Shared link', err);
    });
}

function getAlertOffset(element) {
  const rect = element.getBoundingClientRect();
  return {
    left: rect.left,
    top: rect.top + window.scrollY,
  };
}

function createNetwork(alert_id, relatedAlerts, nb_nodes, containerId, containerConfigureId) {
  const { nodes, edges } = relatedAlerts;

  if (nodes.length === 0 || nodes.length === undefined) {
      $(`#similarAlertsNotify-${alert_id}`).text(`No relationships found for this alert`);
     return;
  }

  const data = {
    nodes: new vis.DataSet(nodes),
    edges: new vis.DataSet(edges),
  };

const options = {
    edges: {
        smooth: {
            enabled: true,
            type: 'continuous',
            roundness: 0.5
        }
    },
    layout: {
        randomSeed: 2,
        improvedLayout: true
    },
    interaction: {
        hideEdgesOnDrag: false,
        tooltipDelay: 100,
        zoomView: false,
        navigationButtons: true,
        keyboard: {
            enabled: true,
            bindToWindow: true
        }
    },
    height: (window.innerHeight - 400) + "px",
    clickToUse: true,
    physics: {
        forceAtlas2Based: {
            gravitationalConstant: -167,
            centralGravity: 0.02,
            springLength: 0,
            springConstant: 0.01,
            damping: 0.1
        },
        minVelocity: 0.41,
        solver: "forceAtlas2Based",
        timestep: 0.45
    }
};

const container = document.getElementById(containerId);
const network = new vis.Network(container, data, options);


    // Create a MutationObserver to listen for DOM changes in the container
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === 'childList') {
          network.redraw(); // Force a redraw when the DOM is updated
          break;
        }
      }
    });

    // Start observing the container for DOM changes
    observer.observe(container, {
      childList: true,
      subtree: true,
    });

    network.on("stabilizationIterationsDone", function () {
        network.setOptions( { physics: false } );
    });

    let selectedNodeId = null;
    let node_type = null;
    let node_id = null;


    network.on('oncontext', (event) => {
      event.event.preventDefault();

      const nodeId = network.getNodeAt(event.pointer.DOM);

      if (nodeId) {

          selectedNodeId = nodeId;
          node_type = selectedNodeId.split('_')[0];
          node_id = selectedNodeId.split('_')[1];

          if (node_type === 'alert' || node_type === 'case' || node_type === 'asset' || node_type === 'ioc') {
              // Get the offset of the container element.
              const containerOffset = getAlertOffset(container);

              const x = event.pointer.DOM.x + 110;
              const y = containerOffset.top + event.pointer.DOM.y;

              const contextMenu = $('#context-menu-relationships');
              contextMenu.css({
                  position: 'absolute',
                  left: `${x}px`,
                  top: `${y}px`
              })

              $('#view-alert').data('node-id', node_id);
              $('#view-alert').data('node-type', node_type);
              if (node_type === 'alert' || node_type === 'case') {
                  $('#view-alert-text').text(`View ${node_type} #${node_id}`);
              } else {
                    $('#view-alert-text').text(`Pivot on ${node_type} ${node_id}`);
              }
              contextMenu.show();
          }
      }
    });

    document.addEventListener('click', () => {
      const contextMenu = $('#context-menu-relationships');
      contextMenu.hide();
    });

      if (nodes.length >= nb_nodes) {
            $(`#similarAlertsNotify-${alert_id}`).text(`Relationships node exceeded the nodes limit. Expect truncated results.`)
      } else {
            $(`#similarAlertsNotify-${alert_id}`).text(``);
      }

}

function viewAlertGraph() {
    const node_id = $("#view-alert").data('node-id');
    const node_type = $("#view-alert").data('node-type');

    if (node_type === 'alert') {
        window.open(`/alerts?alert_ids=${node_id}&cid=${get_caseid()}`);
    } else if (node_type === 'case') {
        window.open(`/case?cid=${node_id}`);
    } else if (node_type === 'asset') {
        window.open(`/alerts?alert_assets=${node_id}&cid=${get_caseid()}`);
    } else if (node_type === 'ioc') {
        window.open(`/alerts?alert_iocs=${node_id}&cid=${get_caseid()}`);
    }
}


function fetchSimilarAlerts(alert_id,
  refresh = false,
  fetch_open_alerts = true,
  fetch_closed_alerts = false,
  fetch_open_cases = false,
  fetch_closed_cases = false
    ) {
      const similarAlertsElement = $(`#similarAlerts-${alert_id}`);
      if (!similarAlertsElement.html() || refresh) {
        // Build the query string with the new parameters
        const nb_nodes = $(`#nbResultsGraphFilter-${alert_id}`).val();
        const queryString = new URLSearchParams({
          'open-alerts': fetch_open_alerts,
          'closed-alerts': fetch_closed_alerts,
          'open-cases': fetch_open_cases,
          'closed-cases': fetch_closed_cases,
          'days-back': $(`#daysBackGraphFilter-${alert_id}`).val(),
          'number-of-nodes': nb_nodes
        }).toString();

        $(`#similarAlertsNotify-${alert_id}`).text('Fetching relationships...');
        get_raw_request_api(`/alerts/similarities/${alert_id}?${queryString}&cid=${get_caseid()}`)
          .done((data) => {
            createNetwork(alert_id, data.data, nb_nodes, `similarAlerts-${alert_id}`, `graphConfigure-${alert_id}`);
          });
      }
}



function escalateOrMergeAlert(alert_id, merge = false, batch = false) {

    const selectedIOCs = $('#ioCsList input[type="checkbox"]:checked').map((_, checkbox) => {
        return $(checkbox).attr('id');
    }).get();

    const selectedAssets = $('#assetsList input[type="checkbox"]:checked').map((_, checkbox) => {
        return $(checkbox).attr('id');
    }).get();

    const note = $('#note').val();
    const importAsEvent = $('#importAsEvent').is(':checked');

    let case_template_id = null;

    if (!merge) {
        case_template_id = $('#mergeAlertCaseTemplateSelect').val();
    }

    const requestBody = {
        iocs_import_list: selectedIOCs,
        assets_import_list: selectedAssets,
        note: note,
        import_as_event: importAsEvent,
        case_tags: $('#case_tags').val(),
        case_template_id: case_template_id,
        csrf_token: $("#csrf_token").val()
    };

    let url =  batch ? `/alerts/batch/`: `/alerts/`;

    if (merge) {
        requestBody.target_case_id = $('#mergeAlertCaseSelect').val();
        url += batch ? 'merge' : `merge/${alert_id}`;
    } else {
        requestBody.case_title = $('#modalEscalateCaseTitle').val();
        url += batch ? 'escalate' : `escalate/${alert_id}`;
    }

    if (batch) {
        requestBody.alert_ids = alert_id;
    }

    post_request_api(url, JSON.stringify(requestBody))
        .then((data) => {
            if (data.status == 'success') {
                $("#escalateModal").modal("hide");
                notify_auto_api(data);
                if (batch) {
                    refreshAlerts();
                } else {
                    refreshAlert(alert_id);
                }
            } else {
                notify_auto_api(data);
            }
        });
}










function init_module_processing_alert(alert_id, hook_name, hook_ui_name, module_name, data_type) {
    let data = Object();
    data['hook_name'] = hook_name;
    data['module_name'] = module_name;
    data['hook_ui_name'] = hook_ui_name;
    data['csrf_token'] = $('#csrf_token').val();
    data['type'] = 'alert';
    data['targets'] = [alert_id];

    post_request_api('/dim/hooks/call', JSON.stringify(data), true)
    .done(function (data){
        notify_auto_api(data)
    });
}




async function fetchModulesOptionsAlert() {
    const response = get_request_api('/dim/hooks/options/alert/list');

    return await response;
}

async function fetchModulesOptionsIoc() {
    const response = get_request_api('/dim/hooks/options/ioc/list');

    return await response;
}

async function fetchModulesOptionsAsset() {
    const response = get_request_api('/dim/hooks/options/asset/list');

    return await response;
}













function showEnrichment(enrichment) {
    const ace = get_new_ace_editor('enrichmentData', null,
        null, null, null, true, false);
    ace.session.setMode("ace/mode/json");
    ace.setValue(JSON.stringify(enrichment, null, 4), -1);
}

function delete_alert(alert_id) {
    do_deletion_prompt(`Are you sure you want to delete alert #${alert_id}?`, true)
        .then((doDelete) => {
            if (doDelete) {
                post_request_api(`/alerts/delete/${alert_id}`)
                    .then((data) => {
                        if (notify_auto_api(data)) {
                            refreshAlerts();
                        }
                    });
            }
        });
}



function closeBatchAlerts() {
    const alertTag = $('#editAlertTags');
    const confirmAlertEdition = $('#confirmAlertEdition');
    $('#editAlertNote').val('');
    alertTag.val('');

    confirmAlertEdition.text('Close alerts');
    $('.alert-edition-part').hide();
    $('#closeAlertModalLabel').text(`Close multiple alerts`);

    $('#editAlertModal').modal('show');

    confirmAlertEdition.off('click').on('click', function () {
        let alert_note = $('#editAlertNote').val();
        let alert_tags = alertTag.val();

        let data = {
          alert_note: alert_note,
          alert_tags: alert_tags,
          alert_resolution_status_id: getAlertResolutionId($("input[type='radio'][name='resolutionStatus']:checked").val()),
        };

        if (close) {
            data['alert_status_id'] = getAlertStatusId('Closed');
        }

        updateBatchAlerts(data)
            .then(() => {
                $('#editAlertModal').modal('hide');
            });
    });

}




function mergeAlertClicked(alertId) {

  const merge = $("#escalateOrMergeButton").data("merge");
  const multiMerge = $("#escalateOrMergeButton").data("multi-merge");

  escalateOrMergeAlert(alertId, merge, multiMerge);

}

function changeStatusAlert(alert_id, status_name) {
    let status_id = getAlertStatusId(status_name);

    let data = {
        'alert_status_id': status_id
    }
    updateAlert(alert_id, data, true);
}

async function changeAlertOwner(alertId) {
  // Fetch the user list from the endpoint
  const usersReq = await get_request_api('/manage/users/restricted/list');

  if (api_request_failed(usersReq)) {
    return;
  };

  users = usersReq.data;

  // Populate the select element with the fetched user list
  const userSelect = $('#changeOwnerAlertSelect');
  userSelect.empty();
  users.forEach((user) => {
    userSelect.append(`<option value="${user.user_id}">${user.user_name}</option>`);
  });

  $('#alertIDAssignModal').text(alertId);

  // Show the modal
  $('#changeAlertOwnerModal').modal('show');

  // Set up the form submission
  document.getElementById('assign-owner-button').onclick = async () => {
      // Get the selected user ID
      const newOwnerId = userSelect.val();

      // Send a POST request to the update endpoint
      updateAlert(alertId, {alert_owner_id: newOwnerId}, true)
      .then(() => {
            // Close the modal
            $('#changeAlertOwnerModal').modal('hide');
      });
  };
}


async function changeBatchAlertOwner(alertId) {

    const selectedAlerts = getBatchAlerts();
    if (selectedAlerts.length === 0) {
        notify_error('Please select at least one alert to perform this action on.');
        return;
    }

      // Fetch the user list from the endpoint
      const usersReq = await get_request_api('/manage/users/restricted/list');

      if (api_request_failed(usersReq)) {
        return;
      };

      users = usersReq.data;

      // Populate the select element with the fetched user list
      const userSelect = $('#changeOwnerAlertSelect');
      userSelect.empty();
      users.forEach((user) => {
        userSelect.append(`<option value="${user.user_id}">${user.user_name}</option>`);
      });

      $('#alertIDAssignModal').text(alertId);

      // Show the modal
      $('#changeAlertOwnerModal').modal('show');

      // Set up the form submission
      document.getElementById('assign-owner-button').onclick = async () => {
          // Get the selected user ID
          const newOwnerId = userSelect.val();

          // Send a POST request to the update endpoint
          updateBatchAlerts({alert_owner_id: newOwnerId})
          .then(() => {
                // Close the modal
                $('#changeAlertOwnerModal').modal('hide');
          });
      };
}









function changeStatusBatchAlerts(status_name) {
    const data = {
        'alert_status_id': getAlertStatusId(status_name)
    }

    updateBatchAlerts(data);
}

async function updateBatchAlerts(data_content= {}) {
    const selectedAlerts = getBatchAlerts();
    if (selectedAlerts.length === 0) {
        notify_error('Please select at least one alert to perform this action on.');
        return;
    }

    const data = {
        'alert_ids': selectedAlerts,
        'csrf_token': $('#csrf_token').val(),
        'updates': data_content
    };

       window.swal({
          title: "Alerts are being updated, please wait",
          text: "This window will close automatically when it's done",
          icon: "/static/assets/img/loader.gif",
          button: false,
          allowOutsideClick: false
        });

    return post_request_api('/alerts/batch/update', JSON.stringify(data)).then(function (data) {
        if (notify_auto_api(data)) {
            refreshAlerts();
        }
    }).always(() => {
        window.swal.close();
    });

}


async function deleteBatchAlerts(data_content= {}) {
    const selectedAlerts = getBatchAlerts();
    if (selectedAlerts.length === 0) {
        notify_error('Please select at least one alert to perform this action on.');
        return;
    }

    do_deletion_prompt(`You are about to delete ${selectedAlerts.length} alerts`, true)
    .then((doDelete) => {
       if (!doDelete) {
           return;
       }
       window.swal({
              title: "Alerts are being deleted, please wait",
              text: "This window will close automatically when it's done",
              icon: "/static/assets/img/loader.gif",
              button: false,
              allowOutsideClick: false
        });
        if (doDelete) {
            const data = {
                'alert_ids': selectedAlerts,
                'csrf_token': $('#csrf_token').val()
            }

            return post_request_api('/alerts/batch/delete', JSON.stringify(data)).then(
                (data) => {
                    if (notify_auto_api(data)) {
                        refreshAlerts();
                    }
                }).always(() => {
                window.swal.close();
            });
        }
    });
}



function refreshAlertRelationships(alertId) {
    // Get the checked status of each checkbox
    let fetch_open_alerts = $(`input[name="open_alerts_${alertId}"]`).prop('checked');
    let fetch_closed_alerts = $(`input[name="closed_alerts_${alertId}"]`).prop('checked');
    let fetch_open_cases = $(`input[name="open_cases_${alertId}"]`).prop('checked');
    let fetch_closed_cases = $(`input[name="closed_cases_${alertId}"]`).prop('checked');

    fetchSimilarAlerts(alertId, true, fetch_open_alerts, fetch_closed_alerts,
        fetch_open_cases, fetch_closed_cases);
}


/* iris-ng 2026-11-09: this file is the Alerts page's actions (the escalate / merge dialog, batch changes, the relations graph);
 * the queue itself is alert_queue.js, which these call back into. */
function refreshAlert(alertId) {
    return window.IrisAlertQueue ? window.IrisAlertQueue.alertChanged(alertId) : Promise.resolve();
}

function refreshAlerts() {
    return window.IrisAlertQueue ? window.IrisAlertQueue.reload() : Promise.resolve();
}

function getBatchAlerts() {
    return window.IrisAlertQueue ? window.IrisAlertQueue.picked() : [];
}

async function updateAlert(alert_id, data = {}, do_refresh = false) {
  data['csrf_token'] = $('#csrf_token').val();
  return post_request_api('/alerts/update/' + alert_id, JSON.stringify(data)).then(function (data) {
    if (notify_auto_api(data) && do_refresh) {
      return refreshAlert(alert_id);
    }
  });
}

function fillAlertSelect(selector, rows, value) {
    const select = $(selector);
    select.empty();
    rows.forEach((row) => select.append($('<option>').val(row.id).text(row.name)));
    select.val(value);
}

function editAlert(alert_id, close=false) {
    const alert = window.IrisAlertQueue ? window.IrisAlertQueue.detailOf(alert_id) : null;
    if (!alert) {
        return;
    }
    const options = window.IrisAlertQueue.options();
    const alertTag = $('#editAlertTags');
    const confirmAlertEdition = $('#confirmAlertEdition');

    alertTag.val(alert.alert_tags || '');
    set_suggest_tags(`editAlertTags`);
    $('#editAlertNote').val(alert.alert_note || '');

    const resolutionName = (alert.resolution_status || {}).resolution_status_name;
    const resolutionValue = resolutionName ? resolutionName.toLowerCase().replace(/ /g, '_') : 'unknown';
    $(`input[type='radio'][name='resolutionStatus']`).prop('checked', false)
        .filter(function () { return this.value === resolutionValue; }).prop('checked', true);

    if (close) {
        confirmAlertEdition.text('Close alert');
        $('.alert-edition-part').hide();
        $('#closeAlertModalLabel').text(`Close alert #${alert_id}`);
    } else {
        $('.alert-edition-part').show();
        $('#closeAlertModalLabel').text(`Edit alert #${alert_id}`);
        confirmAlertEdition.text('Save');
    }

    fillAlertSelect('#editAlertClassification', options.classifications || [], alert.alert_classification_id);
    fillAlertSelect('#editAlertSeverity', options.severities || [], alert.alert_severity_id);

    $('#editAlertModal').modal('show');

    confirmAlertEdition.off('click').on('click', function () {
        let data = {
          alert_note: $('#editAlertNote').val(),
          alert_tags: alertTag.val(),
          alert_resolution_status_id: getAlertResolutionId($("input[type='radio'][name='resolutionStatus']:checked").val()),
          alert_severity_id: $('#editAlertSeverity').val(),
        };

        let alert_classification_id = $('#editAlertClassification').val();
        if (alert_classification_id)
            data['alert_classification_id'] = alert_classification_id;

        if (close) {
            data['alert_status_id'] = getAlertStatusId('Closed');
        }

        updateAlert(alert_id, data, true)
            .then(() => {
                $('#editAlertModal').modal('hide');
            });
    });
}

$(document).ready(function () {
    getAlertStatusList();
    getAlertResolutionList();

    if (typeof io === 'undefined') {
        return;
    }
    const socket = io.connect('/alerts');
    socket.on('new_alert', function () {
        if (window.IrisAlertQueue) {
            window.IrisAlertQueue.newAlert();
        }
    });
});

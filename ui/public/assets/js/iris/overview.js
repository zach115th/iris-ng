$.each($.find("table"), function(index, element){
    addFilterFields($(element).attr("id"));
});

/* v3-parity pill renderer. The class comes from a slug of the NAME
 * (lowercase, non-alnum -> dash); names with no matching CSS class simply
 * inherit the base pill look, and the label itself is text-escaped. */
function iris_ov_pill(label, name, kind) {
    let slug = String(name == null ? '' : name).toLowerCase().replace(/[^a-z0-9]+/g, '-');
    let span = $('<span>').addClass('iris-ov-pill')
        .addClass('iris-ov-' + kind + '-' + slug)
        .text(label == null ? '' : String(label));
    return span.prop('outerHTML');
}

let OverviewTable = $("#overview_table").DataTable({
    dom: '<"container-fluid"<"row"<"col"l><"col"f>>>rt<"container-fluid"<"row"<"col"i><"col"p>>>',
    aaData: [],
    columns: [ // https://datatables.net/reference/option/columns
        // ---- hidden, searchable data columns -------------------------------
        {
          visible: false,
          searchable: true,
          "data": "status_name",
            "render": function (data, type, row, meta) {
                return data;
            }
        },
        {
          visible: false,
          searchable: true,
          "data": "case_id",
            "render": function (data, type, row, meta) {
                return data;
          }
        },
        {
          visible: false,
          searchable: true,
          "data": "classification",
            "render": function (data, type, row, meta) {
                if (data != null && (type === 'filter' || type === 'sort' || type === 'display' || type === 'search')) {
                    return data.name;
                }
                return data;
            }
        },
        {
          visible: false,
          searchable: true,
          "data": "case_open_since_days",
            "render": function (data, type, row, meta) {
                return parseInt(data);
            }
        },
        {
          visible: false,
          searchable: true,
          "data": "tasks_status",
            "render": function (data, type, row, meta) {
                if (data != null) {
                    return data.closed_tasks + '/' + (data.closed_tasks + data.open_tasks) + ' tasks done';
                }
                return data;
            }
        },
        // ---- visible columns, v3 order: Title | SOC ID | Opened | Closed |
        //      Customer | State | Severity | Owner | Tags --------------------
      {
        visible: true,
        searchable: true,
        type: 'integer',
        "data": "name",
        "render": function (data, type, row, meta) {
            if (type === 'display' || type === 'filter') {
                if (isWhiteSpace(data)) {
                    data = '#' + row['case_id'];
                }
            } else if (type === 'sort') {
                return parseInt(row['case_id']);
            }

            if (type === 'display') {
                let div_anchor = $('<div>');
                let a_anchor = $('<a>');
                a_anchor.attr('href', `/case?cid=${row['case_id']}`);
                a_anchor.attr('target', '_blank');
                a_anchor.attr('rel', 'noopener');
                a_anchor.html("<i class='fa-solid fa-arrow-up-right-from-square ml-1 mr-2 text-muted'></i>");

                let span_anchor = $('<span>');
                span_anchor.attr('data-index', meta.row);
                span_anchor.addClass('btn-quick-view');
                span_anchor.addClass('text-link');
                span_anchor.addClass('mr-2');
                span_anchor.attr('title', 'Quick view');
                span_anchor.attr('style', 'cursor: pointer;');
                span_anchor.text(data);
                div_anchor.append(a_anchor);
                div_anchor.append(span_anchor);

                // v3-style subtitle: #id - SOC reference
                let sub = $('<div>').addClass('iris-ov-sub');
                let subtext = '#' + row['case_id'];
                if (row['soc_id'] != null && String(row['soc_id']).trim() !== '') {
                    subtext += ' \u00b7 SOC ' + row['soc_id'];
                }
                sub.text(subtext);
                div_anchor.append(sub);

                return div_anchor.prop('outerHTML');
            }

            return data;
        }
      },
      {
        "data": "soc_id",
        "render": function (data, type, row, meta) {
            if (type === 'display') {
                if (data == null || String(data).trim() === '') { return '-'; }
                return sanitizeHTML(data);
            }
            return data == null ? '' : data;
        }
      },
      {
        "data": "open_date",
        "render": function (data, type, row, meta) {
            if (type === 'display' && data != null) {
              data = formatTime(data, { day: 'numeric', month: 'short', year: 'numeric' });
            }
            return data;
          }
      },
      {
        "data": "close_date",
        "render": function (data, type, row, meta) {
            if (type === 'display') {
                if (data == null || String(data).trim() === '') { return '\u2014'; }
                return formatTime(data, { day: 'numeric', month: 'short', year: 'numeric' });
            }
            return data == null ? '' : data;
          }
      },
      {
        "data": "client",
        "render": function (data, type, row, meta) {
          if (type === 'display') {
            let div_anchor = $('<div>');
            let a_anchor = $('<a>');
            a_anchor.attr('href', `/manage/customers/${data.customer_id}/view`);
            a_anchor.attr('target', '_blank');
            a_anchor.attr('rel', 'noopener');
            a_anchor.html("<i class='fa-solid fa-arrow-up-right-from-square ml-1 mr-2 text-muted'></i>");

            let span_anchor = $('<span>');
            span_anchor.text(data.customer_name);
            div_anchor.append(a_anchor);
            div_anchor.append(span_anchor);

            return div_anchor.prop('outerHTML');

          } else if (type === 'sort' || type === 'filter') {
            data = sanitizeHTML(data.customer_name);
          }
          return data;
        }
      },
      {
        "data": "state",
        "render": function (data, type, row, meta) {
            if (type === 'display' && data != null) {
                let review_status = row['review_status'] ? row['review_status'].status_name : 'Not reviewed';
                let label = data.state_name;
                if (data.state_name === 'Closed' && review_status !== 'Not reviewed') {
                    label = `Closed - ${review_status}`;
                }
                return iris_ov_pill(label, data.state_name, 'st');
            } else if (data != null && (type === 'sort' || type === 'filter')) {
                let datar = sanitizeHTML(data.state_name);
                let review_status = row['review_status'] ? row['review_status'].status_name : 'Not reviewed';
                datar = `${datar} ${review_status === "Not reviewed"? '' : ' - ' + review_status}`;
                return datar;
            } else {
                return data;
            }
        }
      },
      {
        "data": "severity",
        "render": function (data, type, row, meta) {
            if (type === 'display') {
                if (data == null) { return '\u2014'; }
                return iris_ov_pill(data.severity_name, data.severity_name, 'sev');
            }
            if (data != null && (type === 'filter' || type === 'sort' || type === 'search')) {
                return data.severity_name;
            }
            return data;
        }
      },
      {
        "data": "owner",
        "render": function (data, type, row, meta) {
            let sdata;
            if (type === 'display' && data != null) {
                sdata = sanitizeHTML(data.user_name);
                let div_anchor = $('<div>');
                div_anchor.addClass('row');
                div_anchor.append(get_avatar_initials(sdata, false, null, true));
                div_anchor.append($('<span/>').addClass('ml-1').text(sdata));
                return div_anchor.html();
            }
            if ((type === 'filter' || type === 'sort') && data !== null) {
                return sanitizeHTML(data.user_name);
            }
          return data;
        }
      },
     {
        "data": "tags",
        "render": function (data, type, row, meta) {
            if (type === 'display' && data != null) {
                let output = '';
                for (let index in data) {
                    output += get_tag_from_data(data[index].tag_title, 'badge badge-pill badge-light');
                }
                return output;
            } else if (type === 'sort' || type === 'filter') {
                let output = [];
                for (let index in data) {
                    let tag = data[index].tag_title;
                    output.push(tag);
                }
                return output;
            }
            return data;
        }

     }
    ],
    filter: true,
    info: true,
    ordering: true,
    processing: true,
    retrieve: true,
    lengthChange: true,
    pageLength: 25,
    searchBuilder: {
    },
    language: {
      searchBuilder: {
        add: "Add filter",
        title: {
            _: 'Filters (%d)',
            0: '',
        }
      }
    },
    order: [[ 7, "asc" ]],  // Opened, ascending - the v3 default
    buttons: [
        { "extend": 'csvHtml5', "text":'Export',"className": 'btn btn-primary btn-border btn-round btn-sm float-left mr-4 mt-2' },
        { "extend": 'copyHtml5', "text":'Copy',"className": 'btn btn-primary btn-border btn-round btn-sm float-left mr-4 mt-2' },
    ],
    responsive: {
        details: {
            display: $.fn.dataTable.Responsive.display.childRow,
            renderer: $.fn.dataTable.Responsive.renderer.tableAll()
        }
    },
    select: true,
    orderCellsTop: true,
    initComplete: function () {
            tableFiltering(this.api(), 'overview_table');
    },
    drawCallback: function () {
            $('.btn-quick-view').off('click').on('click', function() {
                    show_case_view($(this).data('index'));
                });
        }
    });

OverviewTable.searchBuilder.container().appendTo($('#table_buttons'));

function get_cases_overview(silent, show_full=false) {
    show_loader();
    show_full = show_full || $('#overviewLoadClosedCase').prop('checked');

     $('#overviewTableTitle').text(show_full ? 'All Cases' : 'Open Cases');

    let show_closed = '';
    if (show_full) {
        show_closed = '&show_closed=true'
    }
    get_raw_request_api(`/overview/filter?cid=${get_caseid()}${show_closed}`)
    .done((data) => {
        if (api_request_failed(data)) {
            return;
        }
        if (!silent) {
            notify_api_request_success(data)
        }
        OverviewTable.clear();
        OverviewTable.rows.add(data.data);
        OverviewTable.columns.adjust().draw();
        $(".truncate").on("click", function() {
            var index = $(this).index() + 1;
            $('table tr td:nth-child(' + index  + ')').toggleClass("truncate");
        });

        hide_loader();
    });
}

function show_case_view(row_index) {
    let case_data = OverviewTable.row(row_index).data();
    $('#caseViewModal').find('.modal-title').text(case_data.name);
    $('#caseViewModal').find('.modal-subtitle').text(case_data.case_uuid);

    let body = $('#caseViewModal').find('.modal-body .container');
    body.empty();

    // Owner Card
    let owner_card = $('<div/>').addClass('card mb-3');
    let owner_body = $('<div/>').addClass('card-body');
    owner_body.append($('<h2/>').addClass('card-title mb-2').text('Metadata'));

    let owner_row = $('<div/>').addClass('row');
    let owner_col1 = $('<div/>').addClass('col-md-6');
    let owner_col2 = $('<div/>').addClass('col-md-6');
    let timeSinceLastUpdateStr = '';
    let modifications = case_data.modification_history;
    if (modifications != null) {
        let timestamps = Object.keys(modifications).map(parseFloat);
        let lastUpdatedTimestamp = Math.max(...timestamps);

        let currentTime = Date.now() / 1000; // convert to seconds
        let timeSinceLastUpdate = currentTime - lastUpdatedTimestamp;
        let timeSinceLastUpdateInSeconds = currentTime - lastUpdatedTimestamp;

        let timeSinceLastUpdateInMinutes = timeSinceLastUpdate / 60;
        let timeSinceLastUpdateInHours = timeSinceLastUpdateInMinutes / 60;
        let timeSinceLastUpdateInDays = timeSinceLastUpdateInHours / 24;


        if (timeSinceLastUpdateInSeconds < 60) {
            timeSinceLastUpdateStr = `${Math.round(timeSinceLastUpdateInSeconds)} second(s) ago`;
        } else if (timeSinceLastUpdateInMinutes < 60) {
            timeSinceLastUpdateStr = `${Math.round(timeSinceLastUpdateInMinutes)} minute(s) ago`;
        } else if (timeSinceLastUpdateInHours < 24) {
            timeSinceLastUpdateStr = `${Math.round(timeSinceLastUpdateInHours)} hour(s) ago`;
        } else {
            timeSinceLastUpdateStr = `${Math.round(timeSinceLastUpdateInDays)} day(s) ago`;
        }
    } else {
        timeSinceLastUpdateStr = 'Never';
    }

    let tagsStr = '';
    for (let index in case_data.tags) {
        let tag = sanitizeHTML(case_data.tags[index].tag_title);
        tagsStr += `<span class="badge badge-pill badge-light">${tag}</span> `;
    }

    let owner_dl1 = $('<dl class="row"/>');
    owner_dl1.append($('<dt class="col-sm-3"/>').text('Owner:'));
    owner_dl1.append($('<dd class="col-sm-8"/>').text(case_data.owner.user_name));
    owner_dl1.append($('<dt class="col-sm-3"/>').text('Opening User:'));
    owner_dl1.append($('<dd class="col-sm-8"/>').text(case_data.user.user_name));
    owner_dl1.append($('<dt class="col-sm-3"/>').text('Open Date:'));
    owner_dl1.append($('<dd class="col-sm-8"/>').text(case_data.open_date));

    if (case_data.close_date != null) {
        owner_dl1.append($('<dt class="col-sm-3"/>').text('Close Date:'));
        owner_dl1.append($('<dd class="col-sm-8"/>').text(case_data.close_date))
    }
    owner_dl1.append($('<dt class="col-sm-3"/>').text('Tags:'));
    owner_dl1.append($('<dd class="col-sm-8"/>').html(tagsStr !== ''? tagsStr : 'No tags'));
    owner_dl1.append($('<dt class="col-sm-3"/>').text('State:'));
    owner_dl1.append($('<dd class="col-sm-8"/>').text(case_data.state ? case_data.state.state_description: 'None'));
    owner_dl1.append($('<dt class="col-sm-3"/>').text('Last update:'));
    owner_dl1.append($('<dd class="col-sm-8"/>').text(timeSinceLastUpdateStr));
    owner_dl1.append($('<dt class="col-sm-3"/>').text('Severity:'));
    owner_dl1.append($('<dd class="col-sm-8"/>').text(case_data.severity ? case_data.severity.severity_name: "Unspecified"));
    owner_dl1.append($('<dt class="col-sm-3"/>').text('Outcome:'));
    let statusName = case_data.status_name.replace(/_/g, ' ');
    statusName = statusName.replace(/\b\w/g, function(l){ return l.toUpperCase() });
    owner_dl1.append($('<dd class="col-sm-8"/>').text(statusName));

    owner_col1.append(owner_dl1);



    let owner_dl2 = $('<dl class="row"/>');
    owner_dl2.append($('<dt class="col-sm-3"/>').text('Customer Name:'));
    owner_dl2.append($('<dd class="col-sm-8"/>').text(case_data.client.customer_name));

    owner_dl2.append($('<dt class="col-sm-3"/>').text('Classification:'));
    owner_dl2.append($('<dd class="col-sm-8"/>').text(case_data.classification ? case_data.classification.name_expanded: 'None'));
    owner_dl2.append($('<dt class="col-sm-3"/>').text('SOC ID:'));
    owner_dl2.append($('<dd class="col-sm-8"/>').text(case_data.soc_id !== '' ? case_data.soc_id : 'None'));
    owner_dl2.append($('<dt class="col-sm-3"/>').text('Related alerts:'));
    owner_dl2.append($('<dd class="col-sm-8"/>').html(`<a target="_blank" rel="noopener" href='/alerts?case_id=${case_data.case_id}'>${case_data.alerts.length} related alert(s) <i class="fa-solid fa-up-right-from-square ml-2"></i></a>`));
    owner_dl2.append($('<dt class="col-sm-3"/>').text('Tasks:'));
    if (case_data.tasks_status != null) {
        owner_dl2.append($('<dd class="col-sm-8"/>').html(`<a target="_blank" rel="noopener" href='/case/tasks?cid=${case_data.case_id}'>${case_data.tasks_status.closed_tasks}/${case_data.tasks_status.open_tasks + case_data.tasks_status.closed_tasks} task(s) <i class="fa-solid fa-up-right-from-square ml-2"></i></a>`));
    } else {
        owner_dl2.append($('<dd class="col-sm-8"/>').text('No tasks'));
    }
    owner_dl2.append($('<dt class="col-sm-3"/>').text('Review:'));
    if (case_data.review_status != null) {
        owner_dl2.append($('<dd class="col-sm-8"/>').text(case_data.review_status.status_name));
    } else {
        owner_dl2.append($('<dd class="col-sm-8"/>').text('No review'));
    }
    owner_dl2.append($('<dt class="col-sm-3"/>').text('Reviewer:'));
    if (case_data.reviewer != null) {
         owner_dl2.append($('<dd class="col-sm-8"/>').text(case_data.reviewer.user_name));
    } else {
        owner_dl2.append($('<dd class="col-sm-8"/>').text('No reviewer'));
    }
    owner_col2.append(owner_dl2);

    owner_row.append(owner_col1);
    owner_row.append(owner_col2);
    owner_body.append(owner_row);
    owner_body.append(`<a type="button" class="btn btn-sm btn-dark float-right" target="_blank" rel="noopener" href='/case?cid=${case_data.case_id}'><i class="fa-solid fa-up-right-from-square mr-2"></i> View case</a>`);

    owner_card.append(owner_body);
    body.append(owner_card);

    // Description Card
    let desc_card = $('<div/>').addClass('card mb-3');
    let desc_body = $('<div/>').addClass('card-body');
    desc_body.append($('<h2/>').addClass('card-title mb-3').text('Summary'));
    let converter = get_showdown_convert();
    let html = converter.makeHtml(case_data.description);
    desc_body.append($('<div/>').addClass('card-text').html(html));

    desc_card.append(desc_body);
    body.append(desc_card);


    $('#caseViewModal').modal('show');
}

$(document).ready(function() {
    show_loader();
    get_cases_overview(true);


    $('#overviewLoadClosedCase').change(function() {
        get_cases_overview(true, this.checked);
    });

});
$('#search_value').keypress(function(event){
    var keycode = (event.keyCode ? event.keyCode : event.which);
    if(keycode == '13'){
        jQuery(this).blur();
        jQuery('#submit_search').focus().click();
        event.stopPropagation();
        return false;
    }
});


function buildCaseAnchor(data, row) {
    let a = $('<a>');
    a.attr('href', 'case?cid=' + row['case_id']);
    a.attr('target', '_blank');
    a.text(data || '');
    return a[0].outerHTML;
}


Table_1 = $("#file_search_table_1").DataTable({
    dom: 'Bfrtip',
    aaData: [],
    aoColumns: [
      { "data": "ioc_name",
       "render": function (data, type, row, meta) {
            if (type === 'display') {
                let span_anchor = $('<span>');
                span_anchor.text(data);
                return span_anchor.html();
            }
            return data;
          }
       },
      { "data": "ioc_description",
        "render": function (data, type, row, meta) {
            if (type === 'display') {
                return ret_obj_dt_description(data);
            }
            return data;
          }
      },
      { "data": "type_name",
        "render": function (data, type, row, meta) {
            if (type === 'display') { data = sanitizeHTML(data);}
            return data;
          }},
      { "data": "case_name",
         "render": function (data, type, row, meta) {
            if (type === 'display') {
                return buildCaseAnchor(data, row);
            }
            return data;
          }},
      { "data": "customer_name",
         "render": function (data, type, row, meta) {
            if (type === 'display') { data = sanitizeHTML(data);}
            return data;
          } },
      { "data": "tlp_name",
        "render": function(data, type, row, meta) {
            if (type === 'display') {
                data = sanitizeHTML(data);
                data = '<span class="badge badge-'+ row['tlp_bscolor'] +' ml-2">tlp:' + data + '</span>';
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
    buttons: [
    { "extend": 'csvHtml5', "text":'Export',"className": 'btn btn-primary btn-border btn-round btn-sm float-left mr-4 mt-2' },
    { "extend": 'copyHtml5', "text":'Copy',"className": 'btn btn-primary btn-border btn-round btn-sm float-left mr-4 mt-2' },
    ]
});
$("#file_search_table_1").css("font-size", 12);

Table_comments = $("#comments_search_table").DataTable({
    dom: 'Bfrtip',
    aaData: [],
    aoColumns: [
      { "data": "comment_id",
       "render": function (data, type, row, meta) {
            if (type === 'display') {
                data = sanitizeHTML(data);
                if (row['ioc_misp'] != null) {
                    jse = JSON.parse(row['ioc_misp']);
                    data += `<i class="fas fa-exclamation-triangle ml-2 text-warning" style="cursor: pointer;" data-html="true"
                       data-toggle="popover" data-trigger="hover" title="Seen on MISP" data-content="Has been seen on  <a href='` + row['misp_link'] + `/events/view/` + jse.misp_id +`'>this event</a><br/><br/><b>Description: </b>`+ jse.misp_desc +`"></i>`;
                }
            }
            return data;
          }
       },
      { "data": "comment_text",
        "render": function (data, type, row, meta) {
            if (type === 'display') {
               return ret_obj_dt_description(data);
            }
            return data;
          }
      },
      { "data": "case_name",
         "render": function (data, type, row, meta) {
            return buildCaseAnchor(data, row);
          }},
      { "data": "customer_name",
         "render": function (data, type, row, meta) {
            if (type === 'display') { data = sanitizeHTML(data);}
            return data;
          }
      }
    ],
    filter: true,
    info: true,
    ordering: true,
    processing: true,
    retrieve: true,
    buttons: [
    { "extend": 'csvHtml5', "text":'Export',"className": 'btn btn-primary btn-border btn-round btn-sm float-left mr-4 mt-2' },
    { "extend": 'copyHtml5', "text":'Copy',"className": 'btn btn-primary btn-border btn-round btn-sm float-left mr-4 mt-2' },
    ]
});
$("#comments_search_table").css("font-size", 12);


const stdButtons = [
    { "extend": 'csvHtml5', "text":'Export',"className": 'btn btn-primary btn-border btn-round btn-sm float-left mr-4 mt-2' },
    { "extend": 'copyHtml5', "text":'Copy',"className": 'btn btn-primary btn-border btn-round btn-sm float-left mr-4 mt-2' },
];

function safeDisplay(data) {
    if (data === null || data === undefined) return '';
    return sanitizeHTML(String(data));
}


Table_assets = $("#assets_search_table").DataTable({
    dom: 'Bfrtip',
    aaData: [],
    aoColumns: [
      { "data": "asset_name",
        "render": function (data, type, row) {
            if (type === 'display') {
                let a = $('<a>');
                a.attr('href', 'case/assets?cid=' + row['case_id'] + '&shared=' + row['asset_id']);
                a.attr('target', '_blank');
                a.text(data || '');
                return a[0].outerHTML;
            }
            return data;
        }
      },
      { "data": "asset_description",
        "render": function (data, type) {
            if (type === 'display') return ret_obj_dt_description(data);
            return data;
        }
      },
      { "data": "asset_type",
        "render": function (data, type) {
            if (type === 'display') return safeDisplay(data);
            return data;
        }
      },
      { "data": "asset_ip",
        "render": function (data, type) {
            if (type === 'display') return safeDisplay(data);
            return data;
        }
      },
      { "data": "asset_domain",
        "render": function (data, type) {
            if (type === 'display') return safeDisplay(data);
            return data;
        }
      },
      { "data": "case_name",
        "render": function (data, type, row) {
            if (type === 'display') return buildCaseAnchor(data, row);
            return data;
        }
      },
      { "data": "customer_name",
        "render": function (data, type) {
            if (type === 'display') return safeDisplay(data);
            return data;
        }
      }
    ],
    filter: true, info: true, ordering: true, processing: true, retrieve: true,
    buttons: stdButtons
});
$("#assets_search_table").css("font-size", 12);


Table_tasks = $("#tasks_search_table").DataTable({
    dom: 'Bfrtip',
    aaData: [],
    aoColumns: [
      { "data": "task_title",
        "render": function (data, type, row) {
            if (type === 'display') {
                let a = $('<a>');
                a.attr('href', 'case/tasks?cid=' + row['case_id'] + '&shared=' + row['task_id']);
                a.attr('target', '_blank');
                a.text(data || '');
                return a[0].outerHTML;
            }
            return data;
        }
      },
      { "data": "task_description",
        "render": function (data, type) {
            if (type === 'display') return ret_obj_dt_description(data);
            return data;
        }
      },
      { "data": "status_name",
        "render": function (data, type, row) {
            if (type === 'display') {
                let color = row['status_bscolor'] || 'secondary';
                return '<span class="badge badge-' + color + '">' + safeDisplay(data) + '</span>';
            }
            return data;
        }
      },
      { "data": "case_name",
        "render": function (data, type, row) {
            if (type === 'display') return buildCaseAnchor(data, row);
            return data;
        }
      },
      { "data": "customer_name",
        "render": function (data, type) {
            if (type === 'display') return safeDisplay(data);
            return data;
        }
      }
    ],
    filter: true, info: true, ordering: true, processing: true, retrieve: true,
    buttons: stdButtons
});
$("#tasks_search_table").css("font-size", 12);


Table_evidence = $("#evidence_search_table").DataTable({
    dom: 'Bfrtip',
    aaData: [],
    aoColumns: [
      { "data": "filename",
        "render": function (data, type, row) {
            if (type === 'display') {
                let a = $('<a>');
                a.attr('href', 'case/evidences?cid=' + row['case_id'] + '&shared=' + row['evidence_id']);
                a.attr('target', '_blank');
                a.text(data || '');
                return a[0].outerHTML;
            }
            return data;
        }
      },
      { "data": "file_description",
        "render": function (data, type) {
            if (type === 'display') return ret_obj_dt_description(data);
            return data;
        }
      },
      { "data": "type_name",
        "render": function (data, type) {
            if (type === 'display') return safeDisplay(data);
            return data;
        }
      },
      { "data": "file_hash",
        "render": function (data, type) {
            if (type === 'display') return safeDisplay(data);
            return data;
        }
      },
      { "data": "case_name",
        "render": function (data, type, row) {
            if (type === 'display') return buildCaseAnchor(data, row);
            return data;
        }
      },
      { "data": "customer_name",
        "render": function (data, type) {
            if (type === 'display') return safeDisplay(data);
            return data;
        }
      }
    ],
    filter: true, info: true, ordering: true, processing: true, retrieve: true,
    buttons: stdButtons
});
$("#evidence_search_table").css("font-size", 12);


Table_events = $("#events_search_table").DataTable({
    dom: 'Bfrtip',
    aaData: [],
    aoColumns: [
      { "data": "event_title",
        "render": function (data, type, row) {
            if (type === 'display') {
                let a = $('<a>');
                a.attr('href', 'case/timeline?cid=' + row['case_id'] + '&shared=' + row['event_id']);
                a.attr('target', '_blank');
                a.text(data || '');
                return a[0].outerHTML;
            }
            return data;
        }
      },
      { "data": "event_content",
        "render": function (data, type) {
            if (type === 'display') return ret_obj_dt_description(data);
            return data;
        }
      },
      { "data": "event_source",
        "render": function (data, type) {
            if (type === 'display') return safeDisplay(data);
            return data;
        }
      },
      { "data": "event_date",
        "render": function (data, type) {
            if (type === 'display') return safeDisplay(data);
            return data;
        }
      },
      { "data": "case_name",
        "render": function (data, type, row) {
            if (type === 'display') return buildCaseAnchor(data, row);
            return data;
        }
      },
      { "data": "customer_name",
        "render": function (data, type) {
            if (type === 'display') return safeDisplay(data);
            return data;
        }
      }
    ],
    filter: true, info: true, ordering: true, processing: true, retrieve: true,
    buttons: stdButtons
});
$("#events_search_table").css("font-size", 12);


Table_cases = $("#cases_search_table").DataTable({
    dom: 'Bfrtip',
    aaData: [],
    aoColumns: [
      { "data": "case_name",
        "render": function (data, type, row) {
            if (type === 'display') return buildCaseAnchor(data, row);
            return data;
        }
      },
      { "data": "case_description",
        "render": function (data, type) {
            if (type === 'display') return ret_obj_dt_description(data);
            return data;
        }
      },
      { "data": "soc_id",
        "render": function (data, type) {
            if (type === 'display') return safeDisplay(data);
            return data;
        }
      },
      { "data": "open_date",
        "render": function (data, type) {
            if (type === 'display') return safeDisplay(data);
            return data;
        }
      },
      { "data": "close_date",
        "render": function (data, type) {
            if (type === 'display') return safeDisplay(data);
            return data;
        }
      },
      { "data": "customer_name",
        "render": function (data, type) {
            if (type === 'display') return safeDisplay(data);
            return data;
        }
      }
    ],
    filter: true, info: true, ordering: true, processing: true, retrieve: true,
    buttons: stdButtons
});
$("#cases_search_table").css("font-size", 12);


$('#submit_search').click(function () {
    search();
});


function search() {
    var data_sent = $('form#form_search').serializeObject();
    data_sent['csrf_token'] = $('#csrf_token').val();
    post_request_api('/search', JSON.stringify(data_sent), true, function (data) {
            $('#submit_search').text("Searching...");
    })
    .done((data) => {
        if (api_request_failed(data)) {
            return;
        }

        $('#notes_msearch_list').empty();
        Table_1.clear();
        Table_comments.clear();
        Table_assets.clear();
        Table_tasks.clear();
        Table_evidence.clear();
        Table_events.clear();
        Table_cases.clear();
        $('#search_table_wrapper_1').hide();
        $('#search_table_wrapper_2').hide();
        $('#search_table_wrapper_3').hide();
        $('#search_table_wrapper_assets').hide();
        $('#search_table_wrapper_tasks').hide();
        $('#search_table_wrapper_evidence').hide();
        $('#search_table_wrapper_events').hide();
        $('#search_table_wrapper_cases').hide();
        val = $("input[type='radio']:checked").val();
        if (val == "ioc") {
            Table_1.rows.add(data.data);
            Table_1.columns.adjust().draw();
            $('#search_table_wrapper_1').show();

            $('#search_table_wrapper_1').on('click', function(e){
                if($('.popover').length>1)
                    $('.popover').popover('hide');
                    $(e.target).popover('toggle');
            });
        } else if (val == "notes") {
            for (e in data.data) {
                let li_anchor = $('<i>');
                li_anchor.addClass('list-group-item');
                let span_anchor = $('<span>');
                span_anchor.addClass('name');
                span_anchor.attr('style', 'cursor:pointer');
                span_anchor.attr('title', 'Click to open note');
                span_anchor.attr('onclick', 'note_in_details(' + data.data[e]['note_id'] + ', ' + data.data[e]['case_id'] + ');');
                span_anchor.text(data.data[e]['note_title'] + ' - ' + data.data[e]['case_name'] + ' - ' + data.data[e]['client_name']);
                li_anchor.append(span_anchor);
                $('#notes_msearch_list').append(li_anchor);

            }
            $('#search_table_wrapper_2').show();
        } else if (val == "comments") {
            Table_comments.rows.add(data.data);
            Table_comments.columns.adjust().draw();
            $('#search_table_wrapper_3').show();

            $('#search_table_wrapper_3').on('click', function(e){
                if($('.popover').length>1)
                    $('.popover').popover('hide');
                    $(e.target).popover('toggle');
            });
        } else if (val == "assets") {
            Table_assets.rows.add(data.data);
            Table_assets.columns.adjust().draw();
            $('#search_table_wrapper_assets').show();
        } else if (val == "tasks") {
            Table_tasks.rows.add(data.data);
            Table_tasks.columns.adjust().draw();
            $('#search_table_wrapper_tasks').show();
        } else if (val == "evidence") {
            Table_evidence.rows.add(data.data);
            Table_evidence.columns.adjust().draw();
            $('#search_table_wrapper_evidence').show();
        } else if (val == "events") {
            Table_events.rows.add(data.data);
            Table_events.columns.adjust().draw();
            $('#search_table_wrapper_events').show();
        } else if (val == "cases") {
            Table_cases.rows.add(data.data);
            Table_cases.columns.adjust().draw();
            $('#search_table_wrapper_cases').show();
        }
    })
    .always(() => {
        $('#submit_search').text("Search");
    });
}

function note_in_details(note_id, case_id) {
    window.open("/case/notes?cid=" + case_id + "&shared=" + note_id);

}

$(document).ready(function(){
    $('#search_value').focus();
});

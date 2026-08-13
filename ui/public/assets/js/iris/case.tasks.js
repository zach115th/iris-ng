var current_users_list = [];
var g_task_id = null;
var g_task_desc_editor = null;

/* iris-next: indented dependency-tree view state */
var g_task_tree_active = false;   // is the tree view currently shown?
var g_task_links = [];            // [{from_task_id, to_task_id, link_type}]
var g_tasks_by_id = {};           // task_id -> task row (from tasks_list)
var g_tree_collapsed = {};        // "<graph>:<task_id>" -> true when collapsed

/* Flip between the flat DataTable and the indented dependency tree. */
function toggle_task_view() {
    g_task_tree_active = !g_task_tree_active;
    const $label = $('#iris-task-view-toggle-label');
    if (g_task_tree_active) {
        $('#card_main_load').hide();
        $('#iris-task-tree-card').show();
        $label.text('Table view');
        $('#iris-task-view-toggle').removeClass('btn-dark').addClass('btn-primary');
        // Always re-pull links on activation so the tree reflects current state.
        fetch_task_links_then_render();
    } else {
        $('#iris-task-tree-card').hide();
        $('#card_main_load').show();
        $label.text('Tree view');
        $('#iris-task-view-toggle').removeClass('btn-primary').addClass('btn-dark');
    }
}

/* Pull every link in the case in one round-trip, then (re)draw the tree. */
function fetch_task_links_then_render() {
    let cid = get_caseid();
    get_request_api(`/api/v2/cases/${cid}/tasks/links`)
    .done((data) => {
        // v2 endpoint returns the payload directly (no {status,data} wrapper).
        let payload = (data && data.links !== undefined) ? data : (data && data.data ? data.data : data);
        g_task_links = (payload && payload.links) ? payload.links : [];
        render_task_tree();
    });
}

/* Build a status badge identical to the flat table's. */
function tree_status_badge(task) {
    if (!task || task.status_name === undefined) { return ''; }
    return '<span class="badge badge-' + sanitizeHTML(task.status_bscolor || 'secondary') +
           '">' + sanitizeHTML(task.status_name) + '</span>';
}

/*
 * Render both dependency graphs (blocks / depends_on) as indented trees.
 *
 * Roots = tasks that are a parent in at least one edge but never a child
 * of the same link_type (so the top of each chain). A task with no links
 * of a given type does not appear in that graph. Multiple-parent edges
 * (a DAG, not a strict tree) are rendered under every parent; a cycle is
 * broken by not re-descending into a node already on the current path,
 * with the repeat marked "(cycle)".
 */
function render_task_tree() {
    if (!g_task_tree_active) { return; }

    // Index the current task rows (tasks_list is populated by get_tasks()).
    g_tasks_by_id = {};
    if (typeof tasks_list !== 'undefined' && tasks_list) {
        tasks_list.forEach(function (t) { g_tasks_by_id[t.task_id] = t; });
    }

    ['blocks', 'depends_on'].forEach(function (lt) {
        const edges = g_task_links.filter(function (l) { return l.link_type === lt; });
        const $container = (lt === 'blocks') ? $('#iris-task-tree-blocks') : $('#iris-task-tree-depends');
        $container.empty();

        if (edges.length === 0) {
            $container.append('<div class="iris-tree-empty">No ' +
                (lt === 'blocks' ? 'blocking' : 'dependency') + ' relationships in this case.</div>');
            return;
        }

        // Adjacency: parent -> [children]; track which ids are ever a child.
        const children = {};
        const isChild = {};
        edges.forEach(function (e) {
            (children[e.from_task_id] = children[e.from_task_id] || []).push(e.to_task_id);
            isChild[e.to_task_id] = true;
        });

        // Roots: any node that is a parent but never a child of this type.
        const rootSet = {};
        Object.keys(children).forEach(function (pid) {
            if (!isChild[pid]) { rootSet[pid] = true; }
        });
        // Pure cycle with no acyclic root: fall back to every parent node.
        let roots = Object.keys(rootSet).map(Number);
        if (roots.length === 0) {
            roots = Object.keys(children).map(Number);
        }
        roots.sort(function (a, b) { return a - b; });

        roots.forEach(function (rootId) {
            $container.append(build_tree_node(lt, rootId, children, []));
        });
    });
}

/* Recursively build one node (+ its children) as DOM. `path` carries the
 * ancestor chain for cycle detection. */
function build_tree_node(graph, taskId, children, path) {
    const task = g_tasks_by_id[taskId];
    const onPath = path.indexOf(taskId) !== -1;
    const kids = (children[taskId] || []).slice().sort(function (a, b) { return a - b; });
    const hasKids = kids.length > 0 && !onPath;

    const $node = $('<div>').addClass('iris-tree-node');

    const $row = $('<div>').addClass('iris-tree-row').attr('data-task_id', taskId);
    if (onPath) { $row.addClass('iris-tree-cycle'); }

    const collapseKey = graph + ':' + taskId;
    const collapsed = !!g_tree_collapsed[collapseKey];

    const $toggle = $('<span>').addClass('iris-tree-toggle');
    if (hasKids) {
        $toggle.html(collapsed ? '<i class="fa-solid fa-caret-right"></i>'
                               : '<i class="fa-solid fa-caret-down"></i>');
        $toggle.on('click', function (ev) {
            ev.stopPropagation();
            g_tree_collapsed[collapseKey] = !g_tree_collapsed[collapseKey];
            render_task_tree();
        });
    } else {
        $toggle.addClass('iris-tree-leaf');
    }
    $row.append($toggle);

    $row.append($('<span>').addClass('iris-tree-id').text('#' + taskId));

    const title = task ? (task.task_title || '(untitled)') : ('(task ' + taskId + ' not in list)');
    const $title = $('<span>').addClass('iris-tree-title')
        .text(title + (onPath ? '  ↻ (cycle)' : ''))
        .attr('title', title);
    $row.append($title);

    if (task) {
        $row.append($('<span>').addClass('iris-tree-status').html(tree_status_badge(task)));
    }

    // Clicking a row (not the toggle) opens the task editor.
    $row.on('click', function () { edit_task(taskId); });
    $node.append($row);

    if (hasKids) {
        const $children = $('<div>').addClass('iris-tree-children');
        if (collapsed) { $children.addClass('iris-collapsed'); }
        const nextPath = path.concat([taskId]);
        kids.forEach(function (cid) {
            $children.append(build_tree_node(graph, cid, children, nextPath));
        });
        $node.append($children);
    }

    return $node;
}

function edit_in_task_desc() {
    if($('#container_task_desc_content').is(':visible')) {
        $('#container_task_description').show(100);
        $('#container_task_desc_content').hide(100);
        $('#task_edition_btn').hide(100);
        $('#task_preview_button').hide(100);
    } else {
        $('#task_preview_button').show(100);
        $('#task_edition_btn').show(100);
        $('#container_task_desc_content').show(100);
        $('#container_task_description').hide(100);
    }
}


/* Fetch a modal that allows to add an event */
function add_task() {
    url = 'tasks/add/modal' + case_param();
    $('#modal_add_task_content').load(url, function (response, status, xhr) {
        hide_minimized_modal_box();
        if (status !== "success") {
             ajax_notify_error(xhr, url);
             return false;
        }
        
        g_task_desc_editor = get_new_ace_editor('task_description', 'task_desc_content', 'target_task_desc',
                            function() {
                                $('#last_saved').addClass('btn-danger').removeClass('btn-success');
                                $('#last_saved > i').attr('class', "fa-solid fa-file-circle-exclamation");
                            }, null);
        g_task_desc_editor.setOption("minLines", "10");
        edit_in_task_desc();

        headers = get_editor_headers('g_task_desc_editor', null, 'task_edition_btn');
        $('#task_edition_btn').append(headers);

        $('#submit_new_task').on("click", function () {

            clear_api_error();
            if(!$('form#form_new_task').valid()) {
                return false;
            }

            var data_sent = $('#form_new_task').serializeObject();
            data_sent['task_tags'] = $('#task_tags').val();
            data_sent['task_assignees_id'] = $('#task_assignees_id').val();
            data_sent['task_status_id'] = $('#task_status_id').val();
            data_sent['task_description'] = g_task_desc_editor.getValue();
            ret = get_custom_attributes_fields();
            has_error = ret[0].length > 0;
            attributes = ret[1];

            if (has_error){return false;}

            data_sent['custom_attributes'] = attributes;
            case_id =  get_caseid()
            post_request_api(`/api/v2/cases/${case_id}/tasks`, JSON.stringify(data_sent), true)
            .done((data, textStatus) => {
                if(textStatus === 'success') {
                    get_tasks();
                    $('#modal_add_task').modal('hide');
                }
            });

            return false;
        })
        $('#modal_add_task').modal({ show: true });
        $('#task_title').focus();

    });

}

function save_task() {
    $('#submit_new_task').click();
}

function update_task(task_id) {
    update_task_ext(task_id, true);
}

function update_task_ext(task_id, do_close) {

    clear_api_error();
    if(!$('form#form_new_task').valid()) {
        return false;
    }

    if (task_id === undefined || task_id === null) {
        task_id = g_task_id;
    }

    var data_sent = $('#form_new_task').serializeObject();
    data_sent['task_tags'] = $('#task_tags').val();

    data_sent['task_assignees_id'] = $('#task_assignees_id').val();
    data_sent['task_status_id'] = $('#task_status_id').val();
    ret = get_custom_attributes_fields();
    has_error = ret[0].length > 0;
    attributes = ret[1];

    if (has_error){return false;}

    data_sent['custom_attributes'] = attributes;
    data_sent['task_description'] = g_task_desc_editor.getValue();

    $('#update_task_btn').text('Updating..');

    post_request_api(`/case/tasks/update/${task_id}`, JSON.stringify(data_sent), true)
    .done((data) => {
        if(notify_auto_api(data)) {
            get_tasks();
            $('#submit_new_task').text("Saved").addClass('btn-outline-success').removeClass('btn-outline-danger').removeClass('btn-outline-warning');
            $('#last_saved').removeClass('btn-danger').addClass('btn-success');
            $('#last_saved > i').attr('class', "fa-solid fa-file-circle-check");

            if (do_close !== undefined && do_close === true) {
                $('#modal_add_task').modal('hide');
            }
        }
    })
    .always(() => {
        $('#update_task_btn').text('Update');
    });
}

/* Delete an event from the timeline thank to its id */ 
function delete_task(id) {
    do_deletion_prompt("You are about to delete task #" + id)
    .then((doDelete) => {
        if (doDelete) {
            let cid = get_caseid();
            delete_request_api(`/api/v2/cases/${cid}/tasks/${id}`)
            .done((data, textStatus) => {
                 if (textStatus === 'nocontent') {
                    get_tasks();
                    $('#modal_add_task').modal('hide');
                    notify_success('Task deleted');
                } else {
                     notify_error('Error deleting task')
                 }
            });
        }
    });
}

/* Edit and event from the timeline thanks to its ID */
function edit_task(id) {
  url = `/case/tasks/${id}/modal${case_param()}`;
  $('#modal_add_task_content').load(url, function (response, status, xhr) {
        hide_minimized_modal_box();
        if (status !== "success") {
             ajax_notify_error(xhr, url);
             return false;
        }

        g_task_id = id;

        g_task_desc_editor = get_new_ace_editor('task_description', 'task_desc_content', 'target_task_desc',
                            function() {
                                $('#last_saved').addClass('btn-danger').removeClass('btn-success');
                                $('#last_saved > i').attr('class', "fa-solid fa-file-circle-exclamation");
                            }, null);

        g_task_desc_editor.setOption("minLines", "6");
        preview_task_description(true);

        headers = get_editor_headers('g_task_desc_editor', null, 'task_edition_btn');
        $('#task_edition_btn').append(headers);

        load_menu_mod_options_modal(id, 'task', $("#task_modal_quick_actions"));
        $('#modal_add_task').modal({show:true});
        edit_in_task_desc();
  });
}

function preview_task_description(no_btn_update) {
    if(!$('#container_task_description').is(':visible')) {
        task_desc = g_task_desc_editor.getValue();
        converter = get_showdown_convert();
        html = converter.makeHtml(do_md_filter_xss(task_desc));
        task_desc_html = do_md_filter_xss(html);
        $('#target_task_desc').html(task_desc_html);
        $('#container_task_description').show();
        if (!no_btn_update) {
            $('#task_preview_button').html('<i class="fa-solid fa-eye-slash"></i>');
        }
        $('#container_task_desc_content').hide();
    }
    else {
        $('#container_task_description').hide();
         if (!no_btn_update) {
            $('#task_preview_button').html('<i class="fa-solid fa-eye"></i>');
        }

        $('#task_preview_button').html('<i class="fa-solid fa-eye"></i>');
        $('#container_task_desc_content').show();
    }
}

/* Fetch and draw the tasks */
function get_tasks() {
    $('#tasks_list').empty();
    show_loader();

    get_request_api('/case/tasks/list')
    .done((data) => {
        if (data.status == 'success') {
                Table.MakeCellsEditable("destroy");
                tasks_list = data.data.tasks;

                options_l = data.data.tasks_status;
                options = [];
                for (index in options_l) {
                    option = options_l[index];
                    options.push({ "value": option.id, "display": option.status_name })
                }
                Table.clear();
                Table.rows.add(tasks_list);
                Table.MakeCellsEditable({
                    "onUpdate": callBackEditTaskStatus,
                    "inputCss": 'form-control col-12',
                    "columns": [2],
                    "allowNulls": {
                      "columns": [2],
                      "errorClass": 'error'
                    },
                    "confirmationButton": {
                      "confirmCss": 'my-confirm-class',
                      "cancelCss": 'my-cancel-class'
                    },
                    "inputTypes": [
                      {
                        "column": 2,
                        "type": "list",
                        "options": options
                      }
                    ]
                  });

                Table.columns.adjust().draw();
                load_menu_mod_options('task', Table, delete_task);
                //$('[data-toggle="popover"]').popover();
                Table.responsive.recalc();

                $(document)
                    .off('click', '.task_details_link')
                    .on('click', '.task_details_link', function(event) {
                    event.preventDefault();
                    let task_id = $(this).data('task_id');
                    edit_task(task_id);
                });

                set_last_state(data.data.state);
                hide_loader();

                // iris-next: keep the dependency-tree view in sync with the
                // freshly-loaded task rows (titles / statuses may have changed).
                // hide_loader() force-shows #card_main_load, so when the tree
                // is the active view re-hide the flat table and keep the tree up.
                if (g_task_tree_active) {
                    $('#card_main_load').hide();
                    $('#iris-task-tree-card').show();
                    fetch_task_links_then_render();
                }
            }

    });
}

function refresh_users(on_finish, cur_assignees_id_list) {

    get_request_api('/case/users/list')
    .done((data) => {
        if (api_request_failed(data)) {
            return;
        }

        current_users_list = data.data;
        if (on_finish !== undefined) {
            on_finish(current_users_list, cur_assignees_id_list);
        }
    });

}

function do_list_users(list_users, cur_assignees_id_list) {

    $('#task_assignees_id').selectpicker({
        liveSearch: true,
        title: "Select assignee(s)"
    });

    for (let user in list_users) {
        if (list_users[user].user_access_level === 4) {
            $('#task_assignees_id').append(new Option(`${filterXSS(list_users[user].user_login)} (${filterXSS(list_users[user].user_name)})`,
                list_users[user].user_id));
        }
    }

    if (cur_assignees_id_list !== undefined) {
        $('#task_assignees_id').selectpicker('val', cur_assignees_id_list);
    }

    $('#task_assignees_id').selectpicker('refresh');
}

function callBackEditTaskStatus(updatedCell, updatedRow, oldValue) {
  data_send = updatedRow.data();
  data_send['csrf_token'] = $('#csrf_token').val();
  tid = data_send['task_id'];

  post_request_api(`/case/tasks/status/update/${tid}`, JSON.stringify(data_send))
  .done(function (data){
    if(notify_auto_api(data)) {
         get_tasks();
    }
  });
}

/* Page is ready, fetch the assets of the case */
$(document).ready(function(){

    /* add filtering fields for each table of the page (must be done before datatable initialization) */
    $.each($.find("table"), function(index, element){
        addFilterFields($(element).attr("id"));
    });

    Table = $("#tasks_table").DataTable({
        dom: '<"container-fluid"<"row"<"col"l><"col"f>>>rt<"container-fluid"<"row"<"col"i><"col"p>>>',
        aaData: [],
        fixedHeader: true,
        aoColumns: [
          {
            "data": "task_title",
            "render": function (data, type, row, meta) {
              if (type === 'display' && data != null) {

                let datak = '';
                let anchor = $('<a>')
                    .attr('href', 'javascript:void(0);')
                    .attr('data-task_id', row['task_id'])
                    .attr('title', `Task ID #${row['task_id']} - ${data}`)
                    .addClass('task_details_link')

                if (isWhiteSpace(data)) {
                    datak = '#' + row['task_id'];
                    anchor.text(datak);
                } else {
                    datak= ellipsis_field(data, 64);
                    anchor.html(datak);
                }

                return anchor.prop('outerHTML');
              }
              return data;
            }
          },
          { "data": "task_description",
           "render": function (data, type, row, meta) {
              if (type === 'display') {
                  return ret_obj_dt_description(data);
              }
              return data;
            }
          },
          {
            "data": "task_status_id",
            "render": function(data, type, row) {
               if (type === 'display') {
                  data = sanitizeHTML(data);
                  data = '<span class="badge ml-2 badge-'+ row['status_bscolor'] +'">' + row['status_name'] + '</span>';
               }
               else if (type === 'filter' || type === 'sort'){
                  data = row['status_name']
               } else if (type === 'export') {
                   data = row['status_name']
                }
              return data;
            }
          },
          {
            "data": "task_assignees",
            "render": function (data, type, row, meta) {
                if (data != null) {
                    names = "";

                    if (data.length > 0) {
                        lst = [];
                        data.forEach(function (item, index) { lst.push(item['name']); });
                        if (type === 'display') {
                            names = list_to_badges(lst, 'primary', 10, 'users');
                        }
                        else {
                            lst.forEach(function (item, index) {
                                names += `${sanitizeHTML(item)}`;
                            });
                        }
                    }
                    else {
                        if (type === 'display') {
                            names = '<span class="badge badge-light ml-2">' + "Unassigned" + '</span>';
                        }
                        else {
                            names = "Unassigned";
                        }
                    }

                    return names;

                }
                return data;

            }
          },
          {
            "data": "task_open_date",
            "render": function (data, type, row, meta) {
                if (type === 'display' && data != null) {
                    return formatTime(data);
                }
                return data;
            }
          },
          { "data": "task_tags",
            "render": function (data, type, row, meta) {
              if (type === 'display' && data != null) {
                  let datas = "";
                  let de = data.split(',');
                  for (let tag in de) {
                    datas += get_tag_from_data(de[tag], 'badge badge-light ml-2');
                }
                return datas;
              }
              return data;
            }
          }
        ],
        rowCallback: function (nRow, data) {
            nRow = '<span class="badge ml-2 badge-'+ sanitizeHTML(data['status_bscolor']) +'">' + sanitizeHTML(data['status_name']) + '</span>';
        },
        filter: true,
        info: true,
        ordering: true,
        processing: true,
        retrieve: true,
        pageLength: 50,
        order: [[ 2, "asc" ]],
        buttons: [
        ],
        responsive: {
            details: {
                display: $.fn.dataTable.Responsive.display.childRow,
                renderer: $.fn.dataTable.Responsive.renderer.tableAll()
            }
        },
        orderCellsTop: true,
        initComplete: function () {
            tableFiltering(this.api(), 'tasks_table');
        },
        select: true
    });
    $("#tasks_table").css("font-size", 12);

    Table.on( 'responsive-resize', function ( e, datatable, columns ) {
            hide_table_search_input( columns );
    });

    var buttons = new $.fn.dataTable.Buttons(Table, {
         buttons: [
            { "extend": 'csvHtml5', "text":'<i class="fas fa-cloud-download-alt"></i>',"className": 'btn btn-link text-white'
            , "titleAttr": 'Download as CSV', "exportOptions": { "columns": ':visible', 'orthogonal':  'export' } } ,
            { "extend": 'copyHtml5', "text":'<i class="fas fa-copy"></i>',"className": 'btn btn-link text-white'
            , "titleAttr": 'Copy', "exportOptions": { "columns": ':visible', 'orthogonal':  'export' } },
            { "extend": 'colvis', "text":'<i class="fas fa-eye-slash"></i>',"className": 'btn btn-link text-white'
            , "titleAttr": 'Toggle columns' }
        ]
    }).container().appendTo($('#tables_button'));

    get_tasks();

    setInterval(function() { check_update('/case/tasks/state'); }, 3000);

    shared_id = getSharedLink();
    if (shared_id) {
        edit_task(shared_id);
    }
});

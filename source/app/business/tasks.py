#  IRIS Source Code
#  Copyright (C) 2024 - DFIR-IRIS
#  contact@dfir-iris.org
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3 of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

from datetime import datetime

from flask_sqlalchemy.pagination import Pagination
from flask_login import current_user

from app import db
from app.datamgmt.case.case_tasks_db import delete_task
from app.datamgmt.case.case_tasks_db import add_task
from app.datamgmt.case.case_tasks_db import update_task_assignees
from app.datamgmt.case.case_tasks_db import get_task
from app.datamgmt.case.case_tasks_db import get_filtered_tasks
from app.datamgmt.states import update_tasks_state
from app.iris_engine.module_handler.module_handler import call_modules_hook
from app.iris_engine.utils.tracker import track_activity
from app.models.models import CaseTasks
from app.models.pagination_parameters import PaginationParameters
from app.schema.marshables import CaseTaskSchema
from app.business.errors import BusinessProcessingError
from app.business.errors import ObjectNotFoundError
from marshmallow.exceptions import ValidationError


def _load(request_data, **kwargs):
    try:
        add_task_schema = CaseTaskSchema()
        return add_task_schema.load(request_data, **kwargs)
    except ValidationError as e:
        raise BusinessProcessingError('Data error', e.messages)


def tasks_delete(task: CaseTasks):
    call_modules_hook('on_preload_task_delete', data=task.id)

    delete_task(task.id)
    update_tasks_state(caseid=task.task_case_id)
    call_modules_hook('on_postload_task_delete', data=task.id, caseid=task.task_case_id)
    track_activity(f'deleted task "{task.task_title}"')


def tasks_create(case_identifier: int, request_json: dict) -> (str, CaseTasks):

    request_data = call_modules_hook('on_preload_task_create', data=request_json, caseid=case_identifier)

    if 'task_assignee_id' in request_data or 'task_assignees_id' not in request_data:
        raise BusinessProcessingError('task_assignee_id is not valid anymore since v1.5.0')

    task_assignee_list = request_data['task_assignees_id']
    del request_data['task_assignees_id']
    task = _load(request_data)

    ctask = add_task(task=task,
                     assignee_id_list=task_assignee_list,
                     user_id=current_user.id,
                     caseid=case_identifier
                     )

    ctask = call_modules_hook('on_postload_task_create', data=ctask, caseid=case_identifier)

    if ctask:
        track_activity(f'added task "{ctask.task_title}"', caseid=case_identifier)
        # Phase 5: notify the assignees. Post-commit, fail-soft by contract.
        from app.business.notifications import notify
        from app.models.models import TaskAssignee
        assignee_ids = [r.user_id for r in TaskAssignee.query.with_entities(
            TaskAssignee.user_id).filter(TaskAssignee.task_id == ctask.id).all()]
        # keep_actor (maintainer decision, 2026-09-02): assigning a task to
        # yourself is an explicit assignment worth a record — same rationale
        # as self-selected reviewers and self-@mentions. Without it the event
        # is permanently silent on a single-operator instance, which was
        # reported as a bug in exactly those words.
        notify('task_assigned', assignee_ids,
               f'Task "{ctask.task_title}" assigned to you (case #{case_identifier})',
               object_type='task', object_id=ctask.id, case_id=case_identifier,
               url=f'/case/tasks?cid={case_identifier}',
               actor_id=current_user.id, keep_actor=True)
        return f'Task "{ctask.task_title}" added', ctask
    raise BusinessProcessingError("Unable to create task for internal reasons")


def tasks_get(identifier) -> CaseTasks:
    task = get_task(identifier)
    if not task:
        raise ObjectNotFoundError()
    return task


def tasks_filter(case_identifier, pagination_parameters: PaginationParameters) -> Pagination:
    return get_filtered_tasks(case_identifier, pagination_parameters)


def tasks_update(task: CaseTasks, request_json):
    case_identifier = task.task_case_id
    request_data = call_modules_hook('on_preload_task_update', data=request_json, caseid=case_identifier)

    if 'task_assignee_id' in request_data or 'task_assignees_id' not in request_data:
        raise BusinessProcessingError('task_assignee_id is not valid anymore since v1.5.0')

    task_assignee_list = request_data['task_assignees_id']
    del request_data['task_assignees_id']

    request_data['id'] = task.id
    task = _load(request_data, instance=task)

    task.task_userid_update = current_user.id
    task.task_last_update = datetime.utcnow()

    # Phase 5: capture prior assignees so only the NEWLY added get notified.
    from app.models.models import TaskAssignee
    prior_assignees = {r.user_id for r in TaskAssignee.query.with_entities(
        TaskAssignee.user_id).filter(TaskAssignee.task_id == task.id).all()}

    update_task_assignees(task.id, task_assignee_list, case_identifier)

    update_tasks_state(caseid=case_identifier)

    db.session.commit()

    # Phase 5: post-commit, fail-soft by contract (notify never raises).
    from app.business.notifications import notify
    current_assignees = {r.user_id for r in TaskAssignee.query.with_entities(
        TaskAssignee.user_id).filter(TaskAssignee.task_id == task.id).all()}
    # keep_actor: see tasks_create — self-assignment notifies by decision.
    notify('task_assigned', list(current_assignees - prior_assignees),
           f'Task "{task.task_title}" assigned to you (case #{case_identifier})',
           object_type='task', object_id=task.id, case_id=case_identifier,
           url=f'/case/tasks?cid={case_identifier}',
           actor_id=current_user.id, keep_actor=True)

    task = call_modules_hook('on_postload_task_update', data=task, caseid=case_identifier)

    if not task:
        raise BusinessProcessingError('Unable to update task for internal reasons')

    track_activity(f'updated task "{task.task_title}" (status {task.status.status_name})', caseid=case_identifier)
    return task

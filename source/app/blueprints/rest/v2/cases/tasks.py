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

from flask import Blueprint
from flask import request

from flask_login import current_user

from app import db
from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_deleted
from app.blueprints.rest.endpoints import response_api_success
from app.blueprints.rest.endpoints import response_api_paginated
from app.blueprints.rest.endpoints import response_api_created
from app.blueprints.rest.parsing import parse_pagination_parameters
from app.blueprints.access_controls import ac_api_return_access_denied
from app.blueprints.access_controls import ac_api_requires
from app.schema.marshables import CaseTaskSchema
from app.business.errors import BusinessProcessingError
from app.business.errors import ObjectNotFoundError
from app.business.tasks import tasks_create
from app.business.tasks import tasks_get
from app.business.tasks import tasks_update
from app.business.tasks import tasks_delete
from app.business.tasks import tasks_filter
from app.models.authorization import CaseAccessLevel
from app.models.models import CaseTaskLink
from app.models.models import CaseTasks
from app.models.models import TaskStatus
from app.iris_engine.access_control.utils import ac_fast_check_current_user_has_case_access


# iris-next: supported task-link types. Two in v1 — `blocks` and
# `depends_on` — each rendered with its inverse name in the UI. Adding a
# third type (e.g. `relates_to`, `duplicates`) is a one-line change here
# plus the matching CHECK constraint update.
TASK_LINK_TYPES = {'blocks', 'depends_on'}
TASK_LINK_INVERSE_LABEL = {
    'blocks': 'is blocked by',
    'depends_on': 'is depended on by',
}
TASK_LINK_FORWARD_LABEL = {
    'blocks': 'blocks',
    'depends_on': 'depends on',
}


def _would_close_cycle(case_id: int, from_task_id: int, to_task_id: int, link_type: str) -> bool:
    """Advisory cycle check — would adding `from -> to` of `link_type` close
    a cycle in the existing graph for the same link_type?

    Walks forward edges starting at `to_task_id`; if `from_task_id` is
    reachable, the proposed edge would close a cycle. Per-link-type:
    `A blocks B` + `B depends_on A` is NOT a cycle (different graphs).

    Bounded by the number of existing links per case, which is small in
    practice. We keep this in pure-python rather than recursive SQL
    because Postgres CTE machinery is overkill at this scale and the
    pure-python path is portable to any future SQLite dev mode.

    The check is advisory only — the caller still creates the link.
    """
    visited: set[int] = set()
    stack = [to_task_id]
    while stack:
        cur = stack.pop()
        if cur == from_task_id:
            return True
        if cur in visited:
            continue
        visited.add(cur)
        rows = CaseTaskLink.query.with_entities(CaseTaskLink.to_task_id).filter(
            CaseTaskLink.case_id == case_id,
            CaseTaskLink.link_type == link_type,
            CaseTaskLink.from_task_id == cur,
        ).all()
        for (next_id,) in rows:
            if next_id not in visited:
                stack.append(next_id)
    return False

case_tasks_blueprint = Blueprint('case_tasks',
                                 __name__,
                                 url_prefix='/<int:case_identifier>/tasks')


@case_tasks_blueprint.post('')
@ac_api_requires()
def add_case_task(case_identifier):
    """
    Add a task to a case.

    Args:
        case_identifier (int): The Case ID for this task
    """
    if not ac_fast_check_current_user_has_case_access(case_identifier, [CaseAccessLevel.full_access]):
        return ac_api_return_access_denied(caseid=case_identifier)

    task_schema = CaseTaskSchema()
    try:
        _, case = tasks_create(case_identifier, request.get_json())
        return response_api_created(task_schema.dump(case))
    except BusinessProcessingError as e:
        return response_api_error(e.get_message())


@case_tasks_blueprint.get('')
@ac_api_requires()
def case_get_tasks(case_identifier):

    if not ac_fast_check_current_user_has_case_access(case_identifier, [CaseAccessLevel.read_only, CaseAccessLevel.full_access]):
        return ac_api_return_access_denied(caseid=case_identifier)

    pagination_parameters = parse_pagination_parameters(request)

    tasks = tasks_filter(case_identifier, pagination_parameters)

    task_schema = CaseTaskSchema()
    return response_api_paginated(task_schema, tasks)


@case_tasks_blueprint.get('/<int:identifier>')
@ac_api_requires()
def get_case_task(case_identifier, identifier):
    """
    Handles getting a task from a case.

    Args:
        case_identifier (int): The case ID
        identifier (int): The task ID
    """

    try:
        task = tasks_get(identifier)

        if task.task_case_id != case_identifier:
            raise ObjectNotFoundError()

        if not ac_fast_check_current_user_has_case_access(task.task_case_id, [CaseAccessLevel.read_only, CaseAccessLevel.full_access]):
            return ac_api_return_access_denied(caseid=task.task_case_id)

        task_schema = CaseTaskSchema()
        return response_api_success(task_schema.dump(task))
    except ObjectNotFoundError:
        return response_api_not_found()


@case_tasks_blueprint.put('/<int:identifier>')
@ac_api_requires()
def update_case_task(case_identifier, identifier):
    try:
        task = tasks_get(identifier)

        if task.task_case_id != case_identifier:
            raise ObjectNotFoundError()

        if not ac_fast_check_current_user_has_case_access(task.task_case_id, [CaseAccessLevel.read_only, CaseAccessLevel.full_access]):
            return ac_api_return_access_denied(caseid=task.task_case_id)

        task = tasks_update(task, request.get_json())

        task_schema = CaseTaskSchema()
        return response_api_success(task_schema.dump(task))
    except ObjectNotFoundError:
        return response_api_not_found()
    except BusinessProcessingError as e:
        return response_api_error(e.get_message())


# ---- iris-next: task-link relationships -----------------------------------
# Jira-style directed task relationships within a case.
# v1 link types: `blocks` and `depends_on`. Stored in canonical forward
# direction; inverse views computed at read time.

def _serialize_task_brief(t: CaseTasks):
    status_name = None
    if t.task_status_id is not None:
        st = TaskStatus.query.filter(TaskStatus.id == t.task_status_id).first()
        if st is not None:
            status_name = st.status_name
    return {
        'task_id': t.id,
        'task_uuid': str(t.task_uuid) if t.task_uuid else None,
        'task_title': t.task_title,
        'task_status_id': t.task_status_id,
        'task_status_name': status_name,
    }


@case_tasks_blueprint.get('/<int:identifier>/links')
@ac_api_requires()
def list_case_task_links(case_identifier, identifier):
    """Return forward + inverse links for a task, grouped by link_type.

    Response shape:
        {
          "blocks":          [task_brief, ...],   # tasks this task blocks
          "is_blocked_by":   [task_brief, ...],   # tasks blocking this task
          "depends_on":      [task_brief, ...],
          "is_depended_on_by": [task_brief, ...]
        }
    """
    try:
        task = tasks_get(identifier)
    except ObjectNotFoundError:
        return response_api_not_found()
    if task.task_case_id != case_identifier:
        return response_api_not_found()
    if not ac_fast_check_current_user_has_case_access(
        task.task_case_id, [CaseAccessLevel.read_only, CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=task.task_case_id)

    forward_rows = (
        CaseTaskLink.query.filter(CaseTaskLink.from_task_id == identifier).all()
    )
    inverse_rows = (
        CaseTaskLink.query.filter(CaseTaskLink.to_task_id == identifier).all()
    )

    def _resolve(link, side: str):
        target_id = link.to_task_id if side == 'forward' else link.from_task_id
        target = CaseTasks.query.filter(CaseTasks.id == target_id).first()
        if target is None:
            return None
        brief = _serialize_task_brief(target)
        brief['link_id'] = link.id
        brief['link_type'] = link.link_type
        return brief

    out = {
        'blocks': [],
        'is_blocked_by': [],
        'depends_on': [],
        'is_depended_on_by': [],
    }
    for r in forward_rows:
        item = _resolve(r, 'forward')
        if item is None:
            continue
        out[r.link_type].append(item)
    for r in inverse_rows:
        item = _resolve(r, 'inverse')
        if item is None:
            continue
        bucket = 'is_blocked_by' if r.link_type == 'blocks' else 'is_depended_on_by'
        out[bucket].append(item)
    return response_api_success(out)


@case_tasks_blueprint.post('/<int:identifier>/links')
@ac_api_requires()
def add_case_task_link(case_identifier, identifier):
    """Create a new task-link row.

    Body:
      - target_task_id: int  (required, must belong to the same case)
      - link_type:      str  (required, one of `blocks` / `depends_on`)
      - direction:      str  (optional, 'forward' (default) | 'inverse')
                              'forward'  → identifier <link_type> target
                              'inverse'  → target <link_type> identifier
                              The inverse helper is a UX nicety: the analyst
                              doesn't have to mentally swap when they want to
                              record "this task is blocked by #N" vs
                              "this task blocks #N".
    """
    try:
        task = tasks_get(identifier)
    except ObjectNotFoundError:
        return response_api_not_found()
    if task.task_case_id != case_identifier:
        return response_api_not_found()
    if not ac_fast_check_current_user_has_case_access(
        task.task_case_id, [CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=task.task_case_id)

    body = request.get_json(silent=True) or {}
    target_id = body.get('target_task_id')
    link_type = body.get('link_type')
    direction = body.get('direction') or 'forward'

    if not isinstance(target_id, int):
        return response_api_error("'target_task_id' (int) is required")
    if link_type not in TASK_LINK_TYPES:
        return response_api_error(f"'link_type' must be one of {sorted(TASK_LINK_TYPES)}")
    if direction not in ('forward', 'inverse'):
        return response_api_error("'direction' must be 'forward' or 'inverse'")
    if target_id == identifier:
        return response_api_error("Cannot link a task to itself")

    target = CaseTasks.query.filter(CaseTasks.id == target_id).first()
    if target is None or target.task_case_id != case_identifier:
        return response_api_error("Target task not found in this case")

    # Direction-aware: forward = identifier -> target; inverse = target -> identifier.
    if direction == 'forward':
        from_id, to_id = identifier, target_id
    else:
        from_id, to_id = target_id, identifier

    existing = CaseTaskLink.query.filter(
        CaseTaskLink.from_task_id == from_id,
        CaseTaskLink.to_task_id == to_id,
        CaseTaskLink.link_type == link_type,
    ).first()
    if existing is not None:
        return response_api_success({
            'id': existing.id,
            'from_task_id': existing.from_task_id,
            'to_task_id': existing.to_task_id,
            'link_type': existing.link_type,
            'duplicate': True,
        })

    # Advisory cycle check before insert. Doesn't block the link — the
    # analyst may legitimately want to flag a circular dependency to make
    # it visible to reviewers. The warning is just surfaced in the response
    # so the UI can show an inline hint.
    cycle = _would_close_cycle(case_identifier, from_id, to_id, link_type)

    link = CaseTaskLink(
        from_task_id=from_id,
        to_task_id=to_id,
        link_type=link_type,
        case_id=case_identifier,
        created_by=current_user.id if current_user and current_user.is_authenticated else None,
    )
    db.session.add(link)
    db.session.commit()
    payload = {
        'id': link.id,
        'from_task_id': link.from_task_id,
        'to_task_id': link.to_task_id,
        'link_type': link.link_type,
        'duplicate': False,
    }
    if cycle:
        payload['warning'] = (
            f"This link closes a cycle in the '{link_type}' graph "
            f"(task #{to_id} already reaches task #{from_id} through other links)."
        )
    return response_api_created(payload)


@case_tasks_blueprint.delete('/<int:identifier>/links/<int:link_id>')
@ac_api_requires()
def delete_case_task_link(case_identifier, identifier, link_id):
    """Remove a task-link row. Either endpoint of the link (the from_task or
    the to_task) is allowed to delete it, as long as the user has full
    access to the case. The `identifier` path component must match one
    side of the link to prevent cross-task delete confusion.
    """
    try:
        task = tasks_get(identifier)
    except ObjectNotFoundError:
        return response_api_not_found()
    if task.task_case_id != case_identifier:
        return response_api_not_found()
    if not ac_fast_check_current_user_has_case_access(
        task.task_case_id, [CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=task.task_case_id)

    link = CaseTaskLink.query.filter(CaseTaskLink.id == link_id).first()
    if link is None or link.case_id != case_identifier:
        return response_api_not_found()
    if link.from_task_id != identifier and link.to_task_id != identifier:
        return response_api_not_found()

    db.session.delete(link)
    db.session.commit()
    return response_api_deleted()


@case_tasks_blueprint.delete('/<int:identifier>')
@ac_api_requires()
def delete_case_task(case_identifier, identifier):
    """
    Handle deleting a task from a case

    Args:
        case_identifier (int): The case ID
        identifier (int): The task ID    
    """

    try:
        task = tasks_get(identifier)

        if task.task_case_id != case_identifier:
            raise ObjectNotFoundError()

        if not ac_fast_check_current_user_has_case_access(task.task_case_id, [CaseAccessLevel.full_access]):
            return ac_api_return_access_denied(caseid=identifier)

        tasks_delete(task)
        return response_api_deleted()
    except ObjectNotFoundError:
        return response_api_not_found()
    except BusinessProcessingError as e:
        return response_api_error(e.get_message())


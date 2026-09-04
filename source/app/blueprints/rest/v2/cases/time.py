#  IRIS Source Code
#  iris-next
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

"""iris-next: case-scoped analyst time-tracking endpoints.

Mounted under /api/v2/cases/<case_identifier>/time-entries.

A time entry stores only (case, analyst, minutes, date, optional note/task).
Sector + incident-type breakdowns are derived at report time on the
dashboard Metrics tab (see app.business.dashboard_metrics).
"""
from flask import Blueprint
from flask import request

from flask_login import current_user

from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_deleted
from app.blueprints.rest.endpoints import response_api_success
from app.blueprints.rest.endpoints import response_api_created
from app.blueprints.access_controls import ac_api_return_access_denied
from app.blueprints.access_controls import ac_api_requires
from app.business.errors import BusinessProcessingError
from app.business.errors import ObjectNotFoundError
from app.business.case_time import time_entry_create
from app.business.case_time import time_entry_update
from app.business.case_time import time_entry_delete
from app.datamgmt.case.case_time_db import list_case_time_entries
from app.datamgmt.case.case_time_db import case_total_minutes
from app.datamgmt.case.case_time_db import case_is_open
from app.datamgmt.case.case_time_db import get_time_entry
from app.datamgmt.case.case_time_db import serialize_time_entry
from app.models.authorization import CaseAccessLevel
from app.iris_engine.access_control.utils import ac_fast_check_current_user_has_case_access


case_time_blueprint = Blueprint('case_time',
                                __name__,
                                url_prefix='/<int:case_identifier>/time-entries')


@case_time_blueprint.get('')
@ac_api_requires()
def list_time_entries(case_identifier):
    """All time entries for a case + the case total, plus an `is_open` flag the
    UI uses to enable/disable the edit affordances."""
    if not ac_fast_check_current_user_has_case_access(
        case_identifier, [CaseAccessLevel.read_only, CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=case_identifier)

    exists, is_open = case_is_open(case_identifier)
    if not exists:
        return response_api_not_found()

    return response_api_success({
        'entries': list_case_time_entries(case_identifier),
        'total_minutes': case_total_minutes(case_identifier),
        'is_open': is_open,
        'current_user_id': current_user.id,
    })


@case_time_blueprint.post('')
@ac_api_requires()
def create_time_entry_endpoint(case_identifier):
    """Log time. Requires full case access (you must be a contributor)."""
    if not ac_fast_check_current_user_has_case_access(case_identifier, [CaseAccessLevel.full_access]):
        return ac_api_return_access_denied(caseid=case_identifier)

    body = request.get_json(silent=True) or {}
    try:
        entry = time_entry_create(case_identifier, current_user.id, body)
        return response_api_created(serialize_time_entry(entry))
    except ObjectNotFoundError:
        return response_api_not_found()
    except BusinessProcessingError as e:
        return response_api_error(e.get_message())


@case_time_blueprint.put('/<int:entry_id>')
@ac_api_requires()
def update_time_entry_endpoint(case_identifier, entry_id):
    if not ac_fast_check_current_user_has_case_access(case_identifier, [CaseAccessLevel.full_access]):
        return ac_api_return_access_denied(caseid=case_identifier)

    body = request.get_json(silent=True) or {}
    try:
        entry = time_entry_update(case_identifier, entry_id, current_user.id, body)
        return response_api_success(serialize_time_entry(entry))
    except ObjectNotFoundError:
        return response_api_not_found()
    except BusinessProcessingError as e:
        return response_api_error(e.get_message())


@case_time_blueprint.delete('/<int:entry_id>')
@ac_api_requires()
def delete_time_entry_endpoint(case_identifier, entry_id):
    if not ac_fast_check_current_user_has_case_access(case_identifier, [CaseAccessLevel.full_access]):
        return ac_api_return_access_denied(caseid=case_identifier)

    try:
        time_entry_delete(case_identifier, entry_id, current_user.id)
        return response_api_deleted()
    except ObjectNotFoundError:
        return response_api_not_found()
    except BusinessProcessingError as e:
        return response_api_error(e.get_message())

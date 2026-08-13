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

"""iris-next: case-scoped notification endpoints backing the header bell.

Mounted under /api/v2/cases/<case_identifier>/notifications.

    GET  ''       full unread list + counts for the current analyst
    GET  '/count' badge number only (polled)
    POST '/ack'   move the read watermark forward

Every route is scoped to the case in the URL and to current_user - there is no
way to read another analyst's watermark or another case's activity through it.
"""
from flask import Blueprint
from flask import request

from flask_login import current_user

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.access_controls import ac_api_return_access_denied
from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_success
from app.business.case_notifications import case_notifications_acknowledge
from app.business.case_notifications import case_notifications_count
from app.business.case_notifications import case_notifications_list
from app.business.errors import BusinessProcessingError
from app.iris_engine.access_control.utils import ac_fast_check_current_user_has_case_access
from app.models.authorization import CaseAccessLevel


case_notifications_blueprint = Blueprint(
    'case_notifications',
    __name__,
    url_prefix='/<int:case_identifier>/notifications'
)

_READ_LEVELS = [CaseAccessLevel.read_only, CaseAccessLevel.full_access]


@case_notifications_blueprint.get('')
@ac_api_requires()
def get_notifications(case_identifier):
    if not ac_fast_check_current_user_has_case_access(case_identifier, _READ_LEVELS):
        return ac_api_return_access_denied(caseid=case_identifier)

    return response_api_success(
        case_notifications_list(current_user.id, case_identifier)
    )


@case_notifications_blueprint.get('/count')
@ac_api_requires()
def get_notifications_count(case_identifier):
    if not ac_fast_check_current_user_has_case_access(case_identifier, _READ_LEVELS):
        return ac_api_return_access_denied(caseid=case_identifier)

    return response_api_success({
        'unread': case_notifications_count(current_user.id, case_identifier)
    })


@case_notifications_blueprint.post('/ack')
@ac_api_requires()
def acknowledge_notifications(case_identifier):
    """Acknowledge up to the `up_to` the client was shown.

    Read access is enough to acknowledge: the watermark is the analyst's own
    per-case reading state, not case data.
    """
    if not ac_fast_check_current_user_has_case_access(case_identifier, _READ_LEVELS):
        return ac_api_return_access_denied(caseid=case_identifier)

    body = request.get_json(silent=True) or {}

    try:
        result = case_notifications_acknowledge(
            current_user.id, case_identifier, body.get('up_to')
        )
    except BusinessProcessingError as exc:
        return response_api_error(str(exc))

    return response_api_success(result)

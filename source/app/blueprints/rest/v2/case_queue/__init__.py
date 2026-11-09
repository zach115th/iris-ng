#  IRIS Source Code
#  Copyright (C) 2026 - iris-ng
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

"""REST - the case queue behind the Overview page (iris-ng 2026-11-08).

  /api/v2/case-queue                  GET  one page of the cases the caller can open:
                                           ?q= &closed=1 &page= &per_page= &sort=case|stage|owner|age|idle &dir=asc|desc
                                           &filter=<JSON tree, models.case_queue_vocab> -> {total, page, per_page,
                                           last_page, sort, dir, data, kpis}; a bad filter is a 400 with its message
  /api/v2/case-queue/state            GET  the page's first frame (what /overview embeds), for a page that could
                                           not embed it; same query as the page
  /api/v2/case-queue/cases/<cid>      GET  the side panel for one case (404 when it does not exist or the caller
                                           cannot open it - one answer for both)

Saved filters are the existing /filters routes with filter_type "cases"; the stage track saves through
PUT /api/v2/cases/<cid>. No new permission: a case is listed when the caller has any access to it but deny_all.
"""

from flask import Blueprint
from flask import request
from flask_login import current_user

from app import db
from app.blueprints.access_controls import ac_api_requires
from app.blueprints.responses import response_error
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
from app.business import case_queue as cq
from app.iris_engine.access_control.utils import ac_fast_check_current_user_has_case_access
from app.models.authorization import CaseAccessLevel
from app.models.cases import Cases

case_queue_blueprint = Blueprint('rest_v2_case_queue', __name__)


@case_queue_blueprint.route('/case-queue', methods=['GET'])
@ac_api_requires()
def get_case_queue():
    try:
        params = cq.parse_args(request.args)
    except cq.QueueError as exc:
        return response_error(exc.message, data=exc.data, status=exc.status)
    data = cq.queue_page(current_user.id, params)
    data['kpis'] = cq.kpis(current_user.id)
    return response_api_success(data)


@case_queue_blueprint.route('/case-queue/state', methods=['GET'])
@ac_api_requires()
def get_case_queue_state():
    return response_api_success(cq.page_state(current_user, request.args))


@case_queue_blueprint.route('/case-queue/cases/<int:case_id>', methods=['GET'])
@ac_api_requires()
def get_case_queue_case(case_id):
    if db.session.get(Cases, case_id) is None:
        return response_api_not_found()
    if not ac_fast_check_current_user_has_case_access(case_id, [CaseAccessLevel.read_only,
                                                                CaseAccessLevel.full_access]):
        return response_api_not_found()
    can_edit = ac_fast_check_current_user_has_case_access(case_id, [CaseAccessLevel.full_access])
    return response_api_success(cq.case_detail(case_id, can_edit))

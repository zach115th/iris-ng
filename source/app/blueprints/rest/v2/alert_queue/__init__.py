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

"""REST - the alert queue behind the Alerts page (iris-ng 2026-11-09). Read-only: changes go through /alerts/*.

  /api/v2/alert-queue                       GET ?q=<search> &order_by= &sort= &page= &per_page= &group=0 and the Filter
                                                panel's fields (the /alerts/filter names) -> {total, entries_total, page,
                                                per_page, last_page, entries: [{kind: alert | cluster, ...}], query,
                                                tab_counts}; a bad search is a 400 with its position in data.query_error
  /api/v2/alert-queue/state                 GET the page's first frame, for a page that could not embed it
  /api/v2/alert-queue/board                 GET the same search + &board=severity|status -> {group, columns, total}
  /api/v2/alert-queue/clusters/<id>/alerts  GET the same search + &offset= &limit= -> more of one cluster's matches
  /api/v2/alert-queue/alerts/<id>           GET the detail pane (404 when it does not exist or the caller cannot see it)

Every route needs alerts_read and sees only the alerts of the caller's customers (every alert for a server
administrator): the same rule as /alerts/filter, whose filter these routes share.
"""

from flask import Blueprint
from flask import request
from flask_login import current_user

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.responses import response_error
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
from app.business import alert_queue as aq
from app.models.authorization import Permissions

alert_queue_blueprint = Blueprint('rest_v2_alert_queue', __name__)


def _error(exc):
    return response_error(exc.message, data={'query_error': exc.query_error} if exc.query_error else None, status=exc.status)


@alert_queue_blueprint.route('/alert-queue', methods=['GET'])
@ac_api_requires(Permissions.alerts_read)
def get_alert_queue():
    try:
        params = aq.parse_args(request.args)
        data = aq.queue_page(current_user, params)
    except aq.QueueError as exc:
        return _error(exc)
    data['tab_counts'] = aq.tab_counts(current_user)
    return response_api_success(data)


@alert_queue_blueprint.route('/alert-queue/state', methods=['GET'])
@ac_api_requires(Permissions.alerts_read)
def get_alert_queue_state():
    return response_api_success(aq.page_state(current_user, request.args))


@alert_queue_blueprint.route('/alert-queue/board', methods=['GET'])
@ac_api_requires(Permissions.alerts_read)
def get_alert_queue_board():
    try:
        params = aq.parse_args(request.args)
        data = aq.board(current_user, params)
    except aq.QueueError as exc:
        return _error(exc)
    data['tab_counts'] = aq.tab_counts(current_user)
    return response_api_success(data)


@alert_queue_blueprint.route('/alert-queue/clusters/<int:cluster_id>/alerts', methods=['GET'])
@ac_api_requires(Permissions.alerts_read)
def get_alert_queue_cluster(cluster_id):
    try:
        params = aq.parse_args(request.args)
        offset = request.args.get('offset', 0, type=int)
        limit = request.args.get('limit', None, type=int)
        return response_api_success(aq.cluster_alerts(current_user, cluster_id, params, offset=offset, limit=limit))
    except aq.QueueError as exc:
        return _error(exc)


@alert_queue_blueprint.route('/alert-queue/alerts/<int:alert_id>', methods=['GET'])
@ac_api_requires(Permissions.alerts_read)
def get_alert_queue_detail(alert_id):
    data = aq.detail(current_user, alert_id)
    if data is None:
        return response_api_not_found()
    return response_api_success(data)

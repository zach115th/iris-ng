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

"""REST - custom dashboards (iris-ng 2026-11-09). Every route is open to any signed-in user; no new permission.

  /api/v2/custom-dashboards                    GET  {system: [...], dashboards: [...]} - the built-in ones, the
                                                    caller's own and every shared one
                                               POST {name, description, is_shared, definition} -> 201 the dashboard
  /api/v2/custom-dashboards/schema             GET  the field catalogue + the option lists (customers and cases:
                                                    only those the caller may see)
  /api/v2/custom-dashboards/presets            GET  widget templates
  /api/v2/custom-dashboards/validate           POST a dashboard -> {valid, issues, dashboard (normalised)}
  /api/v2/custom-dashboards/preview            POST {definition, range | start, end, f_<key>} -> an unsaved
                                                    definition's figures; 400 + issues when it is faulty
  /api/v2/custom-dashboards/<key>              GET / PUT (partial) / DELETE; <key> = a dashboard uuid or a
                                                    built-in key ("statistics": read-only). PUT and DELETE: the
                                                    owner or a server administrator (403); missing and hidden: 404
  /api/v2/custom-dashboards/<key>/clone        POST a private copy owned by the caller -> 201
  /api/v2/custom-dashboards/<key>/data         GET  ?range=<key> | ?start=&end= (UTC) &f_<filter bar key>=<id|@me>
                                                    -> {range, widgets: {id: result}}, figures for the CALLER

Figures only ever cover what the caller may open (business.custom_dashboards).
"""

from flask import Blueprint
from flask import request
from flask_login import current_user

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.responses import response_error
from app.blueprints.rest.endpoints import response_api_created
from app.blueprints.rest.endpoints import response_api_deleted
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
from app.business import custom_dashboards as cd

custom_dashboards_blueprint = Blueprint('rest_v2_custom_dashboards', __name__)


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    data = dict(data)
    data.pop('csrf_token', None)
    return data


def _error(exc):
    if exc.status == 404:
        return response_api_not_found()
    return response_error(exc.message, data={'issues': exc.issues} if exc.issues else None, status=exc.status)


@custom_dashboards_blueprint.route('/custom-dashboards', methods=['GET'])
@ac_api_requires()
def list_custom_dashboards():
    return response_api_success(cd.list_dashboards(current_user))


@custom_dashboards_blueprint.route('/custom-dashboards', methods=['POST'])
@ac_api_requires()
def create_custom_dashboard():
    try:
        return response_api_created(cd.create(current_user, _body()))
    except cd.DashboardError as exc:
        return _error(exc)


@custom_dashboards_blueprint.route('/custom-dashboards/schema', methods=['GET'])
@ac_api_requires()
def get_custom_dashboard_schema():
    return response_api_success(cd.schema(current_user))


@custom_dashboards_blueprint.route('/custom-dashboards/presets', methods=['GET'])
@ac_api_requires()
def get_custom_dashboard_presets():
    return response_api_success(cd.presets())


@custom_dashboards_blueprint.route('/custom-dashboards/validate', methods=['POST'])
@ac_api_requires()
def validate_custom_dashboard():
    try:
        clean = cd.validate_payload(_body())
    except cd.DashboardError as exc:
        return response_api_success({'valid': False, 'message': exc.message, 'issues': exc.issues or [exc.message],
                                     'dashboard': None})
    return response_api_success({'valid': True, 'message': '', 'issues': [], 'dashboard': clean})


@custom_dashboards_blueprint.route('/custom-dashboards/preview', methods=['POST'])
@ac_api_requires()
def preview_custom_dashboard():
    body = _body()
    definition, issues = cd.validate_definition(body.get('definition'))
    if issues:
        return response_error('The definition has %d problem%s.' % (len(issues), '' if len(issues) == 1 else 's'),
                              data={'issues': issues}, status=400)
    args = {k: v for k, v in body.items() if k in ('range', 'start', 'end') or k.startswith('f_')}
    try:
        params = cd.parse_render_args(args, definition)
    except cd.DashboardError as exc:
        return _error(exc)
    return response_api_success(cd.render(current_user, definition, params))


@custom_dashboards_blueprint.route('/custom-dashboards/<key>', methods=['GET'])
@ac_api_requires()
def get_custom_dashboard(key):
    dash = cd.get_dashboard(current_user, key)
    if dash is None:
        return response_api_not_found()
    return response_api_success(dash)


@custom_dashboards_blueprint.route('/custom-dashboards/<key>', methods=['PUT'])
@ac_api_requires()
def update_custom_dashboard(key):
    try:
        return response_api_success(cd.update(current_user, key, _body()))
    except cd.DashboardError as exc:
        return _error(exc)


@custom_dashboards_blueprint.route('/custom-dashboards/<key>', methods=['DELETE'])
@ac_api_requires()
def delete_custom_dashboard(key):
    try:
        cd.delete(current_user, key)
    except cd.DashboardError as exc:
        return _error(exc)
    return response_api_deleted()


@custom_dashboards_blueprint.route('/custom-dashboards/<key>/clone', methods=['POST'])
@ac_api_requires()
def clone_custom_dashboard(key):
    try:
        return response_api_created(cd.clone(current_user, key))
    except cd.DashboardError as exc:
        return _error(exc)


@custom_dashboards_blueprint.route('/custom-dashboards/<key>/data', methods=['GET'])
@ac_api_requires()
def get_custom_dashboard_data(key):
    dash = cd.get_dashboard(current_user, key)
    if dash is None:
        return response_api_not_found()
    try:
        params = cd.parse_render_args(request.args, dash['definition'])
    except cd.DashboardError as exc:
        return _error(exc)
    return response_api_success(cd.render(current_user, dash['definition'], params))

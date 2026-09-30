#!/usr/bin/env python3
#
#  IRIS Source Code
#  Copyright (C) 2026 - IRIS-NG contributors
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

"""Guest-portal tunnel API (iris-ng).

Agent side (shared key, no session, no CSRF — the agent is not a browser):
  GET  /api/v2/portal/tunnel/config    mode, public URL, port; the token only
                                       in named mode
  POST /api/v2/portal/tunnel/status    heartbeat: mode, connected, hostname,
                                       version, error

Admin side (session, server_administrator):
  GET  /api/v2/portal/tunnel           settings (token never returned) + status
  POST /api/v2/portal/tunnel           save mode / public URL / token
"""

from flask import Blueprint
from flask import request

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
from app.blueprints.responses import response_error
from app.business.errors import BusinessProcessingError
from app.business.war_room_guests import agent_key_configured
from app.business.war_room_guests import agent_key_ok
from app.business.war_room_guests import store_tunnel_status
from app.business.war_room_guests import tunnel_config_for_agent
from app.business.war_room_guests import tunnel_settings
from app.business.war_room_guests import tunnel_status
from app.business.war_room_guests import update_tunnel_settings
from app.iris_engine.access_control.utils import ac_current_user_has_permission
from app.models.authorization import Permissions

portal_rest_blueprint = Blueprint('portal_rest', __name__, url_prefix='/api/v2/portal')

AGENT_HEADER = 'X-IRIS-Portal-Agent-Key'


def _agent_gate():
    """404 when no key is configured (the feature is off), 401 on a bad key."""
    if not agent_key_configured():
        return response_api_not_found()
    if not agent_key_ok(request.headers.get(AGENT_HEADER)):
        return response_error('Invalid agent key', status=401)
    return None


@portal_rest_blueprint.route('/tunnel/config', methods=['GET'])
def agent_tunnel_config():
    err = _agent_gate()
    if err:
        return err
    return response_api_success(tunnel_config_for_agent())


@portal_rest_blueprint.route('/tunnel/status', methods=['POST'])
def agent_tunnel_status():
    err = _agent_gate()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        return response_api_success(store_tunnel_status(data))
    except BusinessProcessingError as e:
        return response_api_error(str(e))


@portal_rest_blueprint.route('/tunnel', methods=['GET'])
@ac_api_requires()
def admin_tunnel_get():
    if not ac_current_user_has_permission(Permissions.server_administrator):
        return response_error('Permission denied', status=403)
    return response_api_success({'settings': tunnel_settings(), 'status': tunnel_status()})


@portal_rest_blueprint.route('/tunnel', methods=['POST'])
@ac_api_requires()
def admin_tunnel_save():
    if not ac_current_user_has_permission(Permissions.server_administrator):
        return response_error('Permission denied', status=403)
    data = request.get_json(silent=True) or {}
    try:
        settings = update_tunnel_settings(mode=data.get('mode'),
                                          public_url=data.get('public_url'),
                                          token=data.get('token'))
    except BusinessProcessingError as e:
        return response_api_error(str(e))
    return response_api_success({'settings': settings, 'status': tunnel_status()})

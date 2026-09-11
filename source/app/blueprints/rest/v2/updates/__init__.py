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

"""iris-ng: newer-release check for the update banner (issue #111).

Open to any authenticated user — everyone sees the banner — because the
payload is derived entirely from a public GitHub release object plus the
running version string, which the sidebar already shows to everyone.
`viewer_can_act` tells the client whether to render the upgrade affordances
(server administrators only); it is a UI hint, not an access control, since
nothing in the payload is privileged.
"""
from flask import Blueprint
from flask import request
from flask import session

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.rest.endpoints import response_api_success
from app.blueprints.rest.parsing import parse_boolean
from app.iris_engine.update_check import get_update_state
from app.models.authorization import Permissions


updates_blueprint = Blueprint('updates', __name__, url_prefix='/updates')


def _viewer_is_server_admin() -> bool:
    perms = session.get('permissions') or 0
    return bool(perms & Permissions.server_administrator.value)


@updates_blueprint.get('/latest')
@ac_api_requires()
def get_latest_release():
    """Latest-release state, cached in-process.

    `?refresh=true` bypasses the cache — honoured for server administrators
    only, so a non-admin session cannot drive repeated outbound requests
    against GitHub's rate limit. Always 200: failure is reported in the
    body's `error` field.
    """
    is_admin = _viewer_is_server_admin()
    refresh = parse_boolean(request.args.get('refresh', 'false')) and is_admin
    state = get_update_state(force=refresh)
    state['viewer_can_act'] = is_admin
    return response_api_success(state)

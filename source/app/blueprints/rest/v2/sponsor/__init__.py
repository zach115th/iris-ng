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

"""iris-next: sponsor links read from the project's GitHub FUNDING.yml.

Open to any authenticated user rather than admins only, because the Help menu
surfaces this alongside the settings tab. It exposes no instance data — the
response is derived entirely from a public file.
"""
from flask import Blueprint
from flask import request

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.rest.endpoints import response_api_success
from app.blueprints.rest.parsing import parse_boolean
from app.iris_engine.sponsor import get_sponsor_links


sponsor_blueprint = Blueprint('sponsor', __name__, url_prefix='/sponsor')


@sponsor_blueprint.get('')
@ac_api_requires()
def get_sponsor():
    """Sponsor links, cached in-process. `?refresh=true` bypasses the cache.

    Always 200: get_sponsor_links() reports failure in the body's `error` field
    rather than raising, so a client can render a message without treating an
    unreachable GitHub as a broken endpoint.
    """
    refresh = parse_boolean(request.args.get('refresh', 'false'))
    return response_api_success(get_sponsor_links(force=refresh))

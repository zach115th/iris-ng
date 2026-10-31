"""iris-ng: the lookup values behind the (i) help icons (2026-10-30).

GET /api/v2/help/values/<source> -> {"source", "values": [{id, name, label,
description}]}, the rows of one lookup table (severities, alert statuses,
case states, classifications, IOC / asset / evidence types, task statuses) as
this server stores them. Any signed-in user: the same names and descriptions
already fill the pickers on every page that uses them.
"""
from flask import Blueprint

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
from app.business.help_glossary import value_rows

help_blueprint = Blueprint('help_rest', __name__, url_prefix='/help')


@help_blueprint.route('/values/<string:source>', methods=['GET'])
@ac_api_requires()
def help_values(source):
    rows = value_rows(source)
    if rows is None:
        return response_api_not_found()
    return response_api_success({'source': source, 'values': rows})

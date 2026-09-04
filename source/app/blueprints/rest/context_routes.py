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
from flask import redirect
from flask import request
from flask_login import current_user

from app import app
from app import cache
from app import db
from app.datamgmt.context.context_db import ctx_search_user_cases
from app.models.authorization import Permissions
from app.models.cases import Cases
from app.models.models import Client
from app.blueprints.access_controls import ac_api_requires, not_authenticated_redirection_url
from app.blueprints.responses import response_error
from app.blueprints.responses import response_success
from app.iris_engine.access_control.utils import ac_get_fast_user_cases_access

context_rest_blueprint = Blueprint('context_rest', __name__)


@context_rest_blueprint.route('/context/search-cases', methods=['GET'])
@ac_api_requires()
def cases_context_search():
    search = request.args.get('q')

    # Get all investigations not closed
    datao = ctx_search_user_cases(search, current_user.id, max_results=100)

    return response_success(data=datao)


@context_rest_blueprint.route('/context/set', methods=['POST'])
@ac_api_requires()
def set_ctx():
    """
    Set the context elements of a user i.e the current case
    :return: Page
    """
    # The client sends a jQuery-serialised object, but be tolerant of a JSON
    # body so the endpoint behaves the same for API callers.
    payload = request.form if request.form else (request.get_json(silent=True) or {})

    try:
        ctx = int(payload.get('ctx'))
    except (TypeError, ValueError):
        return response_error('Invalid case identifier')

    # Previously any authenticated user could point their context at any case id
    # -- there was no access check and _update_user_case_ctx() only verified the
    # case EXISTS, so an inaccessible case was accepted and its name shown in the
    # header. Restrict to cases the user actually has access to.
    if ctx not in ac_get_fast_user_cases_access(current_user.id):
        return response_error('Case not found', status=404)

    case = Cases.query.filter(Cases.case_id == ctx).first()
    if not case:
        return response_error('Case not found', status=404)

    # Derive the display name from the case rather than trusting the posted
    # value, which was previously stored verbatim.
    current_user.ctx_case = case.case_id
    current_user.ctx_human_case = case.name

    db.session.commit()

    _update_user_case_ctx()

    return response_success(msg="Saved")


# TODO should move this method somewhere else, it is not a REST route
@app.context_processor
def iris_version():
    return dict(iris_version=app.config.get('IRIS_VERSION'),
                organisation_name=app.config.get('ORGANISATION_NAME'),
                std_permissions=Permissions,
                demo_domain=app.config.get('DEMO_DOMAIN', None),
                # Analytics is opt-in and independent of demo mode. The layouts
                # render the tag only when analytics_script_url is non-empty.
                analytics_script_url=app.config.get('ANALYTICS_SCRIPT_URL', ''),
                analytics_site_id=app.config.get('ANALYTICS_SITE_ID', ''))


# TODO should move this method somewhere else, it is not a REST route
@app.context_processor
@cache.cached(timeout=3600, key_prefix='iris_has_updates')
def has_updates():

    return dict(has_updates=False)


def _update_user_case_ctx():
    """
    Retrieve a list of cases for the case selector
    :return:
    """
    # Get all investigations not closed
    res = Cases.query.with_entities(
        Cases.name,
        Client.name,
        Cases.case_id,
        Cases.close_date) \
        .join(Cases.client) \
        .order_by(Cases.open_date) \
        .all()

    data = [row for row in res]

    if current_user and current_user.ctx_case:
        # If the current user have a current case,
        # Look for it in the fresh list. If not
        # exists then remove from the user context
        is_found = False
        for row in data:
            if row[2] == current_user.ctx_case:
                is_found = True
                break

        if not is_found:
            # The case does not exist,
            # Removes it from the context
            current_user.ctx_case = None
            current_user.ctx_human_case = "Not set"
            db.session.commit()

    app.jinja_env.globals.update({
        'cases_context_selector': data
    })

    return data

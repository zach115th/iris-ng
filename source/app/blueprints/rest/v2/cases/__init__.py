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

import json

from flask import Blueprint
from flask import Response as FlaskResponse
from flask import request
from flask_login import current_user
from werkzeug import Response

from app.blueprints.rest.parsing import parse_comma_separated_identifiers
from app.blueprints.rest.parsing import parse_boolean
from app.blueprints.rest.endpoints import response_api_success
from app.blueprints.rest.endpoints import response_api_deleted
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_created
from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_paginated
from app.blueprints.rest.parsing import parse_pagination_parameters
from app.blueprints.rest.v2.cases.ai import case_ai_blueprint
from app.blueprints.rest.v2.cases.assets import case_assets_blueprint
from app.blueprints.rest.v2.cases.iocs import case_iocs_blueprint
from app.blueprints.rest.v2.cases.tasks import case_tasks_blueprint
from app.blueprints.rest.v2.cases.time import case_time_blueprint
from app.blueprints.rest.v2.cases.team import case_team_blueprint
from app.blueprints.rest.v2.cases.dedup import case_dedup_blueprint
from app.blueprints.rest.v2.cases.working_timeline import case_working_timeline_blueprint
from app.business.cases import cases_create
from app.business.cases import cases_delete
from app.business.cases_portability import export_case_for_portability
from app.business.cases_portability import import_case_from_portability_dict
from app.iris_engine.case_crypto import decrypt_case_export
from app.iris_engine.case_crypto import encrypt_case_export
from app.iris_engine.case_crypto import is_encrypted_case_file
from app.datamgmt.case.case_db import get_case
from app.business.cases import cases_update
from app.business.errors import BusinessProcessingError
from app.datamgmt.manage.manage_cases_db import get_filtered_cases
from app.schema.marshables import CaseSchemaForAPIV2
from app.blueprints.access_controls import ac_api_requires
from app.iris_engine.access_control.utils import ac_fast_check_current_user_has_case_access
from app.blueprints.access_controls import ac_api_return_access_denied
from app.models.authorization import Permissions
from app.models.authorization import CaseAccessLevel


# Create blueprint & import child blueprints
cases_blueprint = Blueprint('cases',
                            __name__,
                            url_prefix='/cases')
cases_blueprint.register_blueprint(case_ai_blueprint)
cases_blueprint.register_blueprint(case_assets_blueprint)
cases_blueprint.register_blueprint(case_iocs_blueprint)
cases_blueprint.register_blueprint(case_tasks_blueprint)
cases_blueprint.register_blueprint(case_time_blueprint)
cases_blueprint.register_blueprint(case_team_blueprint)
cases_blueprint.register_blueprint(case_working_timeline_blueprint)
cases_blueprint.register_blueprint(case_dedup_blueprint)


# iris-next: time-tracking nudge — OPT-IN (server setting, off by default).
@cases_blueprint.get('/time-nudge')
@ac_api_requires()
def time_tracking_nudge():
    """Cases the current user touched recently but logged no time on. Returns
    an empty list (enabled=False) unless an admin enabled the nudge."""
    from app.models.models import ServerSettings
    from app.datamgmt.case.case_time_db import cases_touched_without_time

    settings = ServerSettings.query.first()
    enabled = bool(settings and getattr(settings, 'time_tracking_nudge_enabled', False))
    if not enabled:
        return response_api_success({'enabled': False, 'cases': []})

    return response_api_success({
        'enabled': True,
        'cases': cases_touched_without_time(current_user.id, days=7),
    })


# Routes
@cases_blueprint.post('')
@ac_api_requires(Permissions.standard_user)
def create_case():
    """
    Handles creating a new case.
    """

    try:
        case = cases_create(request.get_json())
        return response_api_created(CaseSchemaForAPIV2().dump(case))
    except BusinessProcessingError as e:
        return response_api_error(e.get_message(), e.get_data())


@cases_blueprint.get('')
@ac_api_requires()
def get_cases() -> Response:
    """
    Handles getting cases, with optional filtering & pagination
    """

    pagination_parameters = parse_pagination_parameters(request)

    case_ids_str = request.args.get('case_ids', None, type=parse_comma_separated_identifiers)

    case_customer_id = request.args.get('case_customer_id', None, type=str)
    case_name = request.args.get('case_name', None, type=str)
    case_description = request.args.get('case_description', None, type=str)
    case_classification_id = request.args.get(
        'case_classification_id', None, type=int)
    case_owner_id = request.args.get('case_owner_id', None, type=int)
    case_opening_user_id = request.args.get(
        'case_opening_user_id', None, type=int)
    case_severity_id = request.args.get('case_severity_id', None, type=int)
    case_state_id = request.args.get('case_state_id', None, type=int)
    case_soc_id = request.args.get('case_soc_id', None, type=str)
    start_open_date = request.args.get('start_open_date', None, type=str)
    end_open_date = request.args.get('end_open_date', None, type=str)
    is_open = request.args.get('is_open', None, type=parse_boolean)

    filtered_cases = get_filtered_cases(
        current_user.id,
        pagination_parameters,
        case_ids=case_ids_str,
        case_customer_id=case_customer_id,
        case_name=case_name,
        case_description=case_description,
        case_classification_id=case_classification_id,
        case_owner_id=case_owner_id,
        case_opening_user_id=case_opening_user_id,
        case_severity_id=case_severity_id,
        case_state_id=case_state_id,
        case_soc_id=case_soc_id,
        start_open_date=start_open_date,
        end_open_date=end_open_date,
        search_value='',
        is_open=is_open
    )
    if filtered_cases is None:
        return response_api_error('Filtering error')

    case_schema = CaseSchemaForAPIV2()
    return response_api_paginated(case_schema, filtered_cases)


@cases_blueprint.get('/<int:identifier>')
@ac_api_requires()
def case_routes_get(identifier):
    """
    Get a case by its ID
    """

    case = get_case(identifier)
    if not case:
        return response_api_not_found()
    if not ac_fast_check_current_user_has_case_access(identifier, [CaseAccessLevel.read_only, CaseAccessLevel.full_access]):
        return ac_api_return_access_denied(caseid=identifier)
    return response_api_success(CaseSchemaForAPIV2().dump(case))


@cases_blueprint.put('/<int:identifier>')
@ac_api_requires(Permissions.standard_user)
def rest_v2_cases_update(identifier):
    if not ac_fast_check_current_user_has_case_access(identifier, [CaseAccessLevel.full_access]):
        return ac_api_return_access_denied(caseid=identifier)

    try:
        case, _ = cases_update(identifier, request.get_json())
        return response_api_success(CaseSchemaForAPIV2().dump(case))
    except BusinessProcessingError as e:
        return response_api_error(e.get_message(), e.get_data())


@cases_blueprint.delete('/<int:identifier>')
@ac_api_requires(Permissions.standard_user)
def case_routes_delete(identifier):
    """
    Delete a case by ID
    """

    if not ac_fast_check_current_user_has_case_access(identifier, [CaseAccessLevel.full_access]):
        return ac_api_return_access_denied(caseid=identifier)

    try:
        cases_delete(identifier)
        return response_api_deleted()
    except BusinessProcessingError as e:
        return response_api_error(e.get_message(), e.get_data())


# iris-next: portable case export/import (round-trip JSON, AES-256-GCM encrypted).
@cases_blueprint.post('/<int:identifier>/export')
@ac_api_requires()
def case_export_portable(identifier):
    """Encrypt and download the case as a .iris-case file.

    Expects a JSON body: {"password": "<analyst-chosen password>"}.
    The exported file is AES-256-GCM encrypted; the password is required to
    import it. Skips evidence binaries, working-timeline rows, comments, AI
    cache, and modification history. The receiving side resolves lookup IDs
    by name."""

    if not ac_fast_check_current_user_has_case_access(identifier,
                                                     [CaseAccessLevel.read_only,
                                                      CaseAccessLevel.full_access]):
        return ac_api_return_access_denied(caseid=identifier)

    body_json = request.get_json(silent=True) or {}
    password = (body_json.get('password') or '').strip()
    if not password:
        return response_api_error('A password is required to encrypt the export')

    try:
        payload = export_case_for_portability(identifier)
    except BusinessProcessingError as e:
        return response_api_error(e.get_message(), e.get_data())

    encrypted = encrypt_case_export(payload, password)
    filename = f'iris-case-{identifier}-export.iris-case'
    return FlaskResponse(
        encrypted,
        mimetype='application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@cases_blueprint.post('/import')
@ac_api_requires(Permissions.standard_user)
def case_import_portable():
    """Create a brand-new case from a previously-exported .iris-case file.

    Accepts multipart/form-data with:
      - file    — the .iris-case encrypted file (required)
      - password — the export password (required for encrypted files)

    Returns the new case id, name, per-object insert counts, and any warnings
    accumulated during name-based lookup resolution (e.g. unknown IOC types)."""

    if 'file' not in request.files:
        return response_api_error('No file provided — send file=<iris-case> as multipart form data')

    file_storage = request.files['file']
    raw = file_storage.read()

    if is_encrypted_case_file(raw):
        password = (request.form.get('password') or '').strip()
        if not password:
            return response_api_error('This file is encrypted — provide the export password')
        try:
            payload = decrypt_case_export(raw, password)
        except ValueError as e:
            return response_api_error(str(e))
    else:
        # Plaintext JSON fallback (legacy unencrypted exports).
        try:
            text = raw.decode('utf-8-sig', errors='replace')
            payload = json.loads(text)
        except (ValueError, UnicodeDecodeError) as e:
            return response_api_error(f'Invalid file: {e}')
        # Catch the edge case where is_encrypted_case_file missed the envelope
        # (e.g. a file exported with a prior build) but the JSON parses as an
        # encryption envelope rather than a case payload.
        if isinstance(payload, dict) and payload.get('enc') == 'aes256gcm':
            password = (request.form.get('password') or '').strip()
            if not password:
                return response_api_error('This file is encrypted — provide the export password')
            try:
                payload = decrypt_case_export(raw, password)
            except ValueError as e:
                return response_api_error(str(e))

    try:
        result = import_case_from_portability_dict(payload)
    except BusinessProcessingError as e:
        return response_api_error(e.get_message(), e.get_data())

    return response_api_created(result)

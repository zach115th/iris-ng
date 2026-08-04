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

import logging as log
from flask import Blueprint
from flask import request

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.rest.endpoints import response_api_created
from app.blueprints.rest.endpoints import response_api_deleted
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_success
from app.blueprints.rest.endpoints import response_api_paginated
from app.blueprints.rest.parsing import parse_pagination_parameters
from app.business.errors import BusinessProcessingError
from app.business.errors import ObjectNotFoundError
from app.business.iocs import iocs_create
from app.business.iocs import iocs_get
from app.business.iocs import iocs_delete
from app.business.iocs import iocs_update
from app.datamgmt.case.case_iocs_db import get_filtered_iocs
from app.iris_engine.access_control.utils import ac_fast_check_current_user_has_case_access
from app.models.authorization import CaseAccessLevel
from app.models.models import IocNoteLink
from app.models.models import Notes
from app import db
from app.schema.marshables import IocSchemaForAPIV2
from app.blueprints.access_controls import ac_api_return_access_denied

case_iocs_blueprint = Blueprint('case_ioc_rest_v2',
                                __name__,
                                url_prefix='/<int:case_identifier>/iocs')


@case_iocs_blueprint.get('')
@ac_api_requires()
def get_case_iocs(case_identifier):

    if not ac_fast_check_current_user_has_case_access(case_identifier, [CaseAccessLevel.read_only, CaseAccessLevel.full_access]):
        return ac_api_return_access_denied(caseid=case_identifier)

    pagination_parameters = parse_pagination_parameters(request)

    ioc_type_id = request.args.get('ioc_type_id', None, type=int)
    ioc_type = request.args.get('ioc_type', None, type=str)
    ioc_tlp_id = request.args.get('ioc_tlp_id', None, type=int)
    ioc_value = request.args.get('ioc_value', None, type=str)
    ioc_description = request.args.get('ioc_description', None, type=str)
    ioc_tags = request.args.get('ioc_tags', None, type=str)

    filtered_iocs = get_filtered_iocs(
        pagination_parameters,
        caseid=case_identifier,
        ioc_type_id=ioc_type_id,
        ioc_type=ioc_type,
        ioc_tlp_id=ioc_tlp_id,
        ioc_value=ioc_value,
        ioc_description=ioc_description,
        ioc_tags=ioc_tags
    )

    if filtered_iocs is None:
        return response_api_error('Filtering error')

    iocs_schema = IocSchemaForAPIV2()
    return response_api_paginated(iocs_schema, filtered_iocs)


@case_iocs_blueprint.post('')
@ac_api_requires()
def add_ioc_to_case(case_identifier):

    if not ac_fast_check_current_user_has_case_access(case_identifier, [CaseAccessLevel.full_access]):
        return ac_api_return_access_denied(caseid=case_identifier)

    ioc_schema = IocSchemaForAPIV2()

    try:
        ioc, _ = iocs_create(request.get_json(), case_identifier)
        return response_api_created(ioc_schema.dump(ioc))
    except BusinessProcessingError as e:
        log.error(e)
        return response_api_error(e.get_message())


@case_iocs_blueprint.delete('/<int:identifier>')
@ac_api_requires()
def delete_case_ioc(case_identifier, identifier):

    try:
        ioc = iocs_get(identifier)
        if not ac_fast_check_current_user_has_case_access(ioc.case_id, [CaseAccessLevel.full_access]):
            return ac_api_return_access_denied(caseid=ioc.case_id)
        if ioc.case_id != case_identifier:
            raise ObjectNotFoundError()

        iocs_delete(ioc)
        return response_api_deleted()

    except ObjectNotFoundError:
        return response_api_not_found()
    except BusinessProcessingError as e:
        return response_api_error(e.get_message())


@case_iocs_blueprint.get('/<int:identifier>')
@ac_api_requires()
def get_case_ioc(case_identifier, identifier):

    ioc_schema = IocSchemaForAPIV2()
    try:
        ioc = iocs_get(identifier)
        if not ac_fast_check_current_user_has_case_access(ioc.case_id, [CaseAccessLevel.read_only, CaseAccessLevel.full_access]):
            return ac_api_return_access_denied(caseid=ioc.case_id)
        if ioc.case_id != case_identifier:
            raise ObjectNotFoundError()

        return response_api_success(ioc_schema.dump(ioc))
    except ObjectNotFoundError:
        return response_api_not_found()


@case_iocs_blueprint.put('/<int:identifier>')
@ac_api_requires()
def update_ioc(case_identifier, identifier):

    ioc_schema = IocSchemaForAPIV2()
    try:
        ioc = iocs_get(identifier)
        if not ac_fast_check_current_user_has_case_access(ioc.case_id,
                                                          [CaseAccessLevel.full_access]):
            return ac_api_return_access_denied(caseid=ioc.case_id)

        ioc, _ = iocs_update(ioc, request.get_json())
        return response_api_success(ioc_schema.dump(ioc))

    except ObjectNotFoundError:
        return response_api_not_found()

    except BusinessProcessingError as e:
        return response_api_error(e.get_message(), data=e.get_data())


# ---- iris-next: source-note provenance link --------------------------------
# These endpoints record where an IOC originated (currently only the AI IOC
# extractor populates them on `+ add`), so the IOC modal can show analysts
# "this came from note X" without forcing the analyst to remember.

def _serialize_link_note(row):
    return {
        'note_id': row.note_id,
        'note_uuid': str(row.note_uuid) if row.note_uuid else None,
        'note_title': row.note_title,
    }


@case_iocs_blueprint.get('/<int:identifier>/source-notes')
@ac_api_requires()
def list_ioc_source_notes(case_identifier, identifier):
    """Return the notes recorded as source for a given IOC."""
    try:
        ioc = iocs_get(identifier)
    except ObjectNotFoundError:
        return response_api_not_found()
    if ioc.case_id != case_identifier:
        return response_api_not_found()
    if not ac_fast_check_current_user_has_case_access(
        ioc.case_id, [CaseAccessLevel.read_only, CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=ioc.case_id)

    rows = (
        db.session.query(Notes.note_id, Notes.note_uuid, Notes.note_title, IocNoteLink.source, IocNoteLink.created_at)
        .join(IocNoteLink, IocNoteLink.note_id == Notes.note_id)
        .filter(IocNoteLink.ioc_id == identifier)
        .order_by(IocNoteLink.created_at.asc())
        .all()
    )
    return response_api_success([
        {
            'note_id': r.note_id,
            'note_uuid': str(r.note_uuid) if r.note_uuid else None,
            'note_title': r.note_title,
            'source': r.source,
            'created_at': r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ])


@case_iocs_blueprint.post('/<int:identifier>/source-notes')
@ac_api_requires()
def add_ioc_source_note(case_identifier, identifier):
    """Record that an IOC was sourced from a note. Idempotent — a duplicate
    (ioc_id, note_id) pair is silently treated as success.

    Body (JSON):
      - note_id: int  (required, must belong to the same case as the IOC)
      - source:  str  (optional, defaults to 'ai_extractor'; max 32 chars)
    """
    try:
        ioc = iocs_get(identifier)
    except ObjectNotFoundError:
        return response_api_not_found()
    if ioc.case_id != case_identifier:
        return response_api_not_found()
    if not ac_fast_check_current_user_has_case_access(
        ioc.case_id, [CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=ioc.case_id)

    body = request.get_json(silent=True) or {}
    note_id = body.get('note_id')
    if not isinstance(note_id, int):
        return response_api_error("'note_id' (int) is required")
    note = Notes.query.filter(Notes.note_id == note_id).first()
    if note is None or note.note_case_id != case_identifier:
        return response_api_error("Note not found in this case")

    source = body.get('source')
    if not isinstance(source, str) or not source.strip():
        source = 'ai_extractor'
    source = source.strip()[:32]

    existing = IocNoteLink.query.filter(
        IocNoteLink.ioc_id == identifier,
        IocNoteLink.note_id == note_id,
    ).first()
    if existing is not None:
        return response_api_success({
            'id': existing.id,
            'ioc_id': existing.ioc_id,
            'note_id': existing.note_id,
            'note_title': note.note_title,
            'source': existing.source,
            'created_at': existing.created_at.isoformat() if existing.created_at else None,
            'duplicate': True,
        })

    link = IocNoteLink(
        ioc_id=identifier,
        note_id=note_id,
        case_id=case_identifier,
        source=source,
    )
    db.session.add(link)
    db.session.commit()
    return response_api_created({
        'id': link.id,
        'ioc_id': link.ioc_id,
        'note_id': link.note_id,
        'note_title': note.note_title,
        'source': link.source,
        'created_at': link.created_at.isoformat() if link.created_at else None,
        'duplicate': False,
    })

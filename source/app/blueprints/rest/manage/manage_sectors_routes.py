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

"""iris-ng: CRUD for the sector catalog (Case Objects > Sectors).

Mirrors the case-classification routes: list open to any authenticated
user (the pickers need it), writes server_administrator. Deleting a
sector whose machine-tag namespace is not covered by the legacy
recognition constants removes historical metrics recognition for that
namespace — the modal says so; disable is the safe retirement.
"""
import marshmallow

from flask import Blueprint
from flask import Response
from flask import request

from app import db
from app.datamgmt.manage.manage_sectors_db import get_sector_by_id
from app.datamgmt.manage.manage_sectors_db import get_sectors_list
from app.iris_engine.utils.tracker import track_activity
from app.models.authorization import Permissions
from app.schema.marshables import SectorCatalogSchema
from app.blueprints.access_controls import ac_api_requires
from app.blueprints.responses import response_error
from app.blueprints.responses import response_success

manage_sectors_rest_blueprint = Blueprint('manage_sectors_rest', __name__)


@manage_sectors_rest_blueprint.route('/manage/sectors/list', methods=['GET'])
@ac_api_requires()
def list_sectors() -> Response:
    return response_success("", data=get_sectors_list())


@manage_sectors_rest_blueprint.route('/manage/sectors/<int:sector_id>', methods=['GET'])
@ac_api_requires()
def get_sector(sector_id: int) -> Response:
    row = get_sector_by_id(sector_id)
    if not row:
        return response_error(f"Invalid sector ID {sector_id}")
    return response_success("", data=SectorCatalogSchema().dump(row))


@manage_sectors_rest_blueprint.route('/manage/sectors/add', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def add_sector() -> Response:
    if not request.is_json:
        return response_error("Invalid request")

    schema = SectorCatalogSchema()
    try:
        row = schema.load(request.get_json())
        db.session.add(row)
        db.session.commit()
    except marshmallow.exceptions.ValidationError as e:
        return response_error(msg="Data error", data=e.messages)

    track_activity(f'added sector "{row.slug}"')
    return response_success("Sector added", schema.dump(row))


@manage_sectors_rest_blueprint.route('/manage/sectors/update/<int:sector_id>', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def update_sector(sector_id: int) -> Response:
    if not request.is_json:
        return response_error("Invalid request")

    row = get_sector_by_id(sector_id)
    if not row:
        return response_error(f"Invalid sector ID {sector_id}")

    schema = SectorCatalogSchema()
    try:
        row = schema.load(request.get_json(), instance=row)
        db.session.commit()
    except marshmallow.exceptions.ValidationError as e:
        return response_error(msg="Data error", data=e.messages)

    track_activity(f'updated sector "{row.slug}"')
    return response_success("Sector updated", schema.dump(row))


@manage_sectors_rest_blueprint.route('/manage/sectors/delete/<int:sector_id>', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def delete_sector(sector_id: int) -> Response:
    row = get_sector_by_id(sector_id)
    if not row:
        return response_error(f"Invalid sector ID {sector_id}")

    slug = row.slug
    db.session.delete(row)
    db.session.commit()
    track_activity(f'deleted sector "{slug}"')
    return response_success("Sector deleted")

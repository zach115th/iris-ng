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

"""iris-ng: modal routes for the sector catalog (Case Objects > Sectors)."""
from typing import Union

from flask import Blueprint
from flask import Response
from flask import redirect
from flask import render_template
from flask import url_for

from app.datamgmt.manage.manage_sectors_db import get_sector_by_id
from app.forms import SectorForm
from app.models.authorization import Permissions
from app.blueprints.access_controls import ac_requires
from app.blueprints.responses import response_error

manage_sectors_blueprint = Blueprint('manage_sectors', __name__,
                                     template_folder='templates')


@manage_sectors_blueprint.route('/manage/sectors/update/<int:sector_id>/modal', methods=['GET'])
@ac_requires(Permissions.server_administrator, no_cid_required=True)
def update_sector_modal(sector_id: int, caseid: int, url_redir: bool) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for('manage_sectors.update_sector_modal',
                                sector_id=sector_id, caseid=caseid))

    row = get_sector_by_id(sector_id)
    if not row:
        return response_error(f"Invalid sector ID {sector_id}")

    form = SectorForm()
    form.slug.render_kw = {'value': row.slug}
    form.name.render_kw = {'value': row.name}
    form.tag.render_kw = {'value': row.tag}

    return render_template("modal_sector.html", form=form, sector=row)


@manage_sectors_blueprint.route('/manage/sectors/add/modal', methods=['GET'])
@ac_requires(Permissions.server_administrator, no_cid_required=True)
def add_sector_modal(caseid: int, url_redir: bool) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for('manage_sectors.add_sector_modal', caseid=caseid))

    return render_template("modal_sector.html", form=SectorForm(), sector=None)

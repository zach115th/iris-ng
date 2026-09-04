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

"""Metrics + Inventory pages (sidebar section: Manage). Both views moved
here VERBATIM from the dashboard's tabs of the same names; all data comes
from the unchanged /api/v2/dashboard/* endpoints. Open to any
authenticated user, exactly as the dashboard tabs were (the inventory is
an evidence-locker workflow by design)."""

from typing import Union

from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import url_for
from flask_wtf import FlaskForm
from werkzeug import Response

from app.blueprints.access_controls import ac_requires

manage_metrics_inventory_blueprint = Blueprint(
    'manage_metrics_inventory',
    __name__,
    template_folder='templates'
)


@manage_metrics_inventory_blueprint.route('/manage/metrics', methods=['GET'])
@ac_requires(no_cid_required=True)
def manage_metrics_view_route(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for(
            'manage_metrics_inventory.manage_metrics_view_route', cid=caseid))

    form = FlaskForm()
    return render_template('manage_metrics.html', caseid=caseid, form=form)


@manage_metrics_inventory_blueprint.route('/manage/inventory',
                                          methods=['GET'])
@ac_requires(no_cid_required=True)
def manage_inventory_view_route(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for(
            'manage_metrics_inventory.manage_inventory_view_route',
            cid=caseid))

    form = FlaskForm()
    return render_template('manage_inventory.html', caseid=caseid, form=form)

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

"""Customer Assets registry page (iris-ng v2, Phase 4). Server-rendered
shell (customer + type selects come from live tables); data via
/api/v2/customer-assets* (manage.customer_assets.js)."""

from typing import Union

from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import url_for
from flask_wtf import FlaskForm
from werkzeug import Response

from app.blueprints.access_controls import ac_requires
from app.models.models import AssetsType
from app.models.models import Client

customer_assets_page_blueprint = Blueprint(
    'customer_assets',
    __name__,
    template_folder='templates'
)


@customer_assets_page_blueprint.route('/manage/customer-assets', methods=['GET'])
@ac_requires(no_cid_required=True)
def customer_assets_view_route(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for('customer_assets.customer_assets_view_route', cid=caseid))

    form = FlaskForm()
    customers = Client.query.order_by(Client.name.asc()).all()
    asset_types = AssetsType.query.order_by(AssetsType.asset_name.asc()).all()
    return render_template('customer_assets.html', caseid=caseid, form=form,
                           customers=customers, asset_types=asset_types)

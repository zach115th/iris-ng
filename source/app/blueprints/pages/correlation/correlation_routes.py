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

"""Cross-case correlation page (sidebar section: Intel). The workspace
moved here VERBATIM from the dashboard's Correlation tab; all data comes
from the unchanged /api/v2/correlation/* endpoints, which scope every
read to the viewer's case ACL. Open to any authenticated user, exactly
as the dashboard tab was."""

from typing import Union

from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import url_for
from flask_wtf import FlaskForm
from werkzeug import Response

from app.blueprints.access_controls import ac_requires

correlation_page_blueprint = Blueprint(
    'correlation_page',
    __name__,
    template_folder='templates'
)


@correlation_page_blueprint.route('/correlation', methods=['GET'])
@ac_requires(no_cid_required=True)
def correlation_view_route(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for('correlation_page.correlation_view_route',
                                cid=caseid))

    form = FlaskForm()
    return render_template('correlation.html', caseid=caseid, form=form)

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

"""Intel -> Vulnerabilities pages (iris-ng 2026-11-07): the catalogue and an
entry's detail page. Open to any signed-in user, like Correlation; the data
comes from /api/v2/manage/vulnerabilities, which scopes every count to the
viewer's cases and customers."""

from typing import Union

from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import url_for
from flask_wtf import FlaskForm
from werkzeug import Response

from app.blueprints.access_controls import ac_requires

vulnerabilities_page_blueprint = Blueprint(
    'vulnerabilities_page',
    __name__,
    template_folder='templates'
)


@vulnerabilities_page_blueprint.route('/vulnerabilities', methods=['GET'])
@ac_requires(no_cid_required=True)
def vulnerabilities_view(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for('vulnerabilities_page.vulnerabilities_view', cid=caseid))
    return render_template('vulnerabilities.html', form=FlaskForm())


@vulnerabilities_page_blueprint.route('/vulnerabilities/<int:vid>', methods=['GET'])
@ac_requires(no_cid_required=True)
def vulnerability_view(vid, caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for('vulnerabilities_page.vulnerability_view', vid=vid, cid=caseid))
    return render_template('vulnerability.html', vulnerability_id=vid, form=FlaskForm())

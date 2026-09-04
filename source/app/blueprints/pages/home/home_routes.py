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

"""Home page (iris-ng v2, Phase 5). The default post-login landing:
my cases / my tasks / my reviews / following feed / latest notifications.
Server-rendered shell; all data comes from the self-scoped v2 endpoints
(home.js). The /dashboard page is untouched."""

from typing import Union

from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import url_for
from flask_wtf import FlaskForm
from werkzeug import Response

from app.blueprints.access_controls import ac_requires

home_blueprint = Blueprint(
    'home',
    __name__,
    template_folder='templates'
)


@home_blueprint.route('/home', methods=['GET'])
@ac_requires(no_cid_required=True)
def home(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for('home.home', cid=caseid))

    form = FlaskForm()
    return render_template('home.html', caseid=caseid, form=form)

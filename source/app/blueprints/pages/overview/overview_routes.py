#  IRIS Source Code
#  DFIR-IRIS Team
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
from flask import render_template
from flask import request
from flask import url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from werkzeug.utils import redirect

from app import app
from app import db
from app.blueprints.access_controls import ac_requires
from app.business import case_queue

overview_blueprint = Blueprint(
    'overview',
    __name__,
    template_folder='templates'
)


@overview_blueprint.route('/overview', methods=['GET'])
@ac_requires()
def get_overview(caseid, url_redir):
    """
    The case queue: the cases the user can open, filtered, sorted and paged on the server
    """
    if url_redir:
        return redirect(url_for('index.index', cid=caseid, redirect=True))

    form = FlaskForm()

    # iris-ng 2026-11-08: the case queue. Its first page, figures and vocabulary are drawn in the first frame; None
    # (the read failed) makes the page fetch them instead.
    try:
        queue_state = case_queue.page_state(current_user, request.args)
    except Exception as exc:
        db.session.rollback()
        app.logger.warning('Case queue not embedded (%s); the page will fetch it', exc)
        queue_state = None

    return render_template('overview.html', caseid=caseid, form=form, queue_state=queue_state)

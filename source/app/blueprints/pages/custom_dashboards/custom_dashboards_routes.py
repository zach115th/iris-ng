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

"""Custom dashboards' pages (iris-ng 2026-11-09): the list, a dashboard, and its editor. Open to any signed-in
user; each page draws its first frame from state embedded in it (None = the read failed, the page fetches)."""

from typing import Union

from flask import abort
from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from werkzeug import Response

from app import app
from app import db
from app.blueprints.access_controls import ac_requires
from app.business import custom_dashboards as cd

custom_dashboards_page_blueprint = Blueprint(
    'custom_dashboards_page',
    __name__,
    template_folder='templates'
)


def _redirect_with_cid(endpoint, caseid, **kw):
    args = {k: v for k, v in request.args.items() if k != 'cid'}
    args.update(kw)
    return redirect(url_for(endpoint, cid=caseid, **args))


def _embed(build, what):
    try:
        return build()
    except Exception as exc:  # noqa: BLE001 - the page then fetches what it could not embed
        db.session.rollback()
        app.logger.warning('Dashboards: %s not embedded (%s); the page will fetch it', what, exc)
        return None


@custom_dashboards_page_blueprint.route('/dashboards', methods=['GET'])
@ac_requires(no_cid_required=True)
def dashboards_list(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return _redirect_with_cid('custom_dashboards_page.dashboards_list', caseid)
    state = _embed(lambda: cd.list_state(current_user), 'the list')
    return render_template('dashboards_list.html', form=FlaskForm(), state=state)


@custom_dashboards_page_blueprint.route('/dashboards/new', methods=['GET'])
@ac_requires(no_cid_required=True)
def dashboard_new(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return _redirect_with_cid('custom_dashboards_page.dashboard_new', caseid)
    state = _embed(lambda: cd.edit_state(current_user, None), 'the editor')
    return render_template('dashboard_edit.html', form=FlaskForm(), state=state, dash_key=None)


@custom_dashboards_page_blueprint.route('/dashboards/<key>', methods=['GET'])
@ac_requires(no_cid_required=True)
def dashboard_view(key, caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return _redirect_with_cid('custom_dashboards_page.dashboard_view', caseid, key=key)
    if cd.get_dashboard(current_user, key) is None:
        abort(404)
    state = _embed(lambda: cd.view_state(current_user, key, request.args), 'the dashboard')
    return render_template('dashboard_view.html', form=FlaskForm(), state=state, dash_key=key)


@custom_dashboards_page_blueprint.route('/dashboards/<key>/edit', methods=['GET'])
@ac_requires(no_cid_required=True)
def dashboard_edit(key, caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return _redirect_with_cid('custom_dashboards_page.dashboard_edit', caseid, key=key)
    dash = cd.get_dashboard(current_user, key)
    if dash is None:
        abort(404)
    if not dash['can_edit']:
        return redirect(url_for('custom_dashboards_page.dashboard_view', key=key, cid=caseid))
    state = _embed(lambda: cd.edit_state(current_user, key), 'the editor')
    return render_template('dashboard_edit.html', form=FlaskForm(), state=state, dash_key=key)

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

"""Tutorials' pages (iris-ng 2026-11-10): the list every signed-in user sees (/tutorials) and, for server
administrators, Settings -> Tutorials (/manage/tutorials) with its editor. Each page draws its first frame from state
embedded in it (None = the read failed: the page fetches it)."""

from typing import Union

from flask import abort
from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for
from flask_wtf import FlaskForm
from werkzeug import Response

from app import app
from app import db
from app.blueprints.access_controls import ac_requires
from app.blueprints.rest.v2.tutorials import viewer
from app.blueprints.rest.v2.tutorials import vocab
from app.business import tutorials as tb
from app.models.authorization import Permissions

tutorials_page_blueprint = Blueprint('tutorials_page', __name__, template_folder='templates')


def _redirect_with_cid(endpoint, caseid, **kw):
    args = {k: v for k, v in request.args.items() if k != 'cid'}
    args.update(kw)
    return redirect(url_for(endpoint, cid=caseid, **args))


def _embed(build, what):
    try:
        return build()
    except tb.TutorialError:
        raise
    except Exception as exc:  # noqa: BLE001 - the page then fetches what it could not embed
        db.session.rollback()
        app.logger.warning('Tutorials: %s not embedded (%s); the page will fetch it', what, exc)
        return None


@tutorials_page_blueprint.route('/tutorials', methods=['GET'])
@ac_requires(no_cid_required=True)
def tutorials_list(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return _redirect_with_cid('tutorials_page.tutorials_list', caseid)
    state = _embed(lambda: tb.list_for_user(viewer()), 'the list')
    return render_template('tutorials.html', form=FlaskForm(), state=state)


@tutorials_page_blueprint.route('/manage/tutorials', methods=['GET'])
@ac_requires(Permissions.server_administrator, no_cid_required=True)
def manage_tutorials(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return _redirect_with_cid('tutorials_page.manage_tutorials', caseid)
    state = _embed(tb.admin_list, 'the list')
    return render_template('manage_tutorials.html', form=FlaskForm(), state=state)


@tutorials_page_blueprint.route('/manage/tutorials/new', methods=['GET'])
@ac_requires(Permissions.server_administrator, no_cid_required=True)
def manage_tutorial_new(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return _redirect_with_cid('tutorials_page.manage_tutorial_new', caseid)
    state = {'ref': None, 'kind': 'team', 'published': False, 'status': 'draft', 'edited': False,
             'content': {'title': '', 'summary': '', 'duration': '', 'audience': 'everyone', 'steps': []}}
    return render_template('manage_tutorial_edit.html', form=FlaskForm(), state=state, vocab=vocab())


@tutorials_page_blueprint.route('/manage/tutorials/<ref>', methods=['GET'])
@ac_requires(Permissions.server_administrator, no_cid_required=True)
def manage_tutorial_edit(ref, caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return _redirect_with_cid('tutorials_page.manage_tutorial_edit', caseid, ref=ref)
    try:
        state = _embed(lambda: tb.admin_get(ref), 'the tutorial')
    except tb.TutorialError:
        abort(404)
    return render_template('manage_tutorial_edit.html', form=FlaskForm(), state=state, vocab=vocab(), ref=ref)

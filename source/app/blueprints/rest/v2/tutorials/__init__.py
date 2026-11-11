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

"""REST - tutorials (iris-ng 2026-11-10). No new permission: any signed-in user runs the published tutorials meant
for them; server administrators edit them. Every change is a POST (CSRF token in the body).

  /api/v2/tutorials                          GET  {tutorials: [...], admin} - each with the caller's status
  /api/v2/tutorials/<ref>/start              POST -> the run (a fresh start; any other running tutorial stops)
  /api/v2/tutorials/<ref>/resume             POST -> the run, where it was stopped
  /api/v2/tutorials/run                      GET  the caller's running tutorial, or null
  /api/v2/tutorials/run/step                 POST {run, step, vars} -> the run
  /api/v2/tutorials/run/minimize             POST {run, minimized} -> the run
  /api/v2/tutorials/run/stop                 POST {run}
  /api/v2/tutorials/run/finish               POST {run} (on the last step)
  /api/v2/tutorials/run/cleanup              POST {run, kind} -> the run; deletes the case / war room this run
                                                  captured, only one the caller created after the run started
  /api/v2/manage/tutorials                   GET  {builtin: [...], team: [...]}; POST {content, published} -> 201
  /api/v2/manage/tutorials/vocab             GET  the vocabulary and limits (models.tutorial_vocab)
  /api/v2/manage/tutorials/validate          POST {content} -> {valid, issues, content}
  /api/v2/manage/tutorials/try               POST {content} -> the caller's preview run (never completed)
  /api/v2/manage/tutorials/import            POST {file: "<the JSON text>"} -> 201, a draft team tutorial
  /api/v2/manage/tutorials/<ref>             GET
  /api/v2/manage/tutorials/<ref>/save        POST {content, published} (a built-in: this server's version)
  /api/v2/manage/tutorials/<ref>/delete      POST (a built-in: back to the shipped version)
  /api/v2/manage/tutorials/<ref>/export      GET  the tutorial file

<ref> = builtin-<key> | team-<id>. A run report naming an older run (another tab, a restart) gets 409."""

import json

from flask import Blueprint
from flask import Response
from flask import request
from flask import session
from flask_login import current_user

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.responses import response_error
from app.blueprints.rest.endpoints import response_api_created
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
from app.business import tutorials as tb
from app.iris_engine.access_control.utils import ac_flag_match_mask
from app.models import tutorial_vocab as V
from app.models.authorization import Permissions

tutorials_blueprint = Blueprint('rest_v2_tutorials', __name__)


def viewer():
    perms = session.get('permissions') or 0
    return tb.Viewer(user_id=current_user.id,
                     admin=ac_flag_match_mask(perms, Permissions.server_administrator.value))


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    data = dict(data)
    data.pop('csrf_token', None)
    return data


def _error(exc):
    if exc.status == 404:
        return response_api_not_found()
    return response_error(exc.message, data={'issues': exc.issues} if exc.issues else None, status=exc.status)


def _run(fn, *args):
    try:
        return response_api_success(fn(*args))
    except tb.TutorialError as exc:
        return _error(exc)


@tutorials_blueprint.route('/tutorials', methods=['GET'])
@ac_api_requires()
def list_tutorials():
    return response_api_success(tb.list_for_user(viewer()))


@tutorials_blueprint.route('/tutorials/<ref>/start', methods=['POST'])
@ac_api_requires()
def start_tutorial(ref):
    return _run(tb.start, viewer(), ref)


@tutorials_blueprint.route('/tutorials/<ref>/resume', methods=['POST'])
@ac_api_requires()
def resume_tutorial(ref):
    return _run(tb.resume, viewer(), ref)


@tutorials_blueprint.route('/tutorials/run', methods=['GET'])
@ac_api_requires()
def get_run():
    return response_api_success({'run': tb.run_state(viewer())})


@tutorials_blueprint.route('/tutorials/run/step', methods=['POST'])
@ac_api_requires()
def run_step():
    return _run(tb.set_step, viewer(), _body())


@tutorials_blueprint.route('/tutorials/run/minimize', methods=['POST'])
@ac_api_requires()
def run_minimize():
    return _run(tb.set_minimized, viewer(), _body())


@tutorials_blueprint.route('/tutorials/run/stop', methods=['POST'])
@ac_api_requires()
def run_stop():
    return _run(tb.stop, viewer(), _body())


@tutorials_blueprint.route('/tutorials/run/finish', methods=['POST'])
@ac_api_requires()
def run_finish():
    return _run(tb.finish, viewer(), _body())


@tutorials_blueprint.route('/tutorials/run/cleanup', methods=['POST'])
@ac_api_requires()
def run_cleanup():
    return _run(tb.cleanup, viewer(), _body())


# ------------------------------------------------------------------ administration

@tutorials_blueprint.route('/manage/tutorials', methods=['GET'])
@ac_api_requires(Permissions.server_administrator)
def manage_list():
    return response_api_success(tb.admin_list())


@tutorials_blueprint.route('/manage/tutorials', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def manage_create():
    try:
        return response_api_created(tb.create(viewer(), _body()))
    except tb.TutorialError as exc:
        return _error(exc)


@tutorials_blueprint.route('/manage/tutorials/vocab', methods=['GET'])
@ac_api_requires(Permissions.server_administrator)
def manage_vocab():
    return response_api_success(vocab())


def vocab():
    return {'format': V.FORMAT, 'audiences': [{'value': a, 'label': V.AUDIENCE_LABELS[a]} for a in V.AUDIENCES],
            'done_when': [{'value': k, 'label': V.DONE_WHEN_LABELS[k]} for k in V.DONE_WHEN],
            'methods': list(V.METHODS),
            'cleanup': [{'value': k, 'label': V.CLEANUP_LABELS[k]} for k in V.CLEANUP_KINDS],
            'limits': dict(V.LIMITS), 'anchor_name_re': V.ANCHOR_NAME_RE, 'var_re': V.VAR_RE}


@tutorials_blueprint.route('/manage/tutorials/validate', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def manage_validate():
    clean, issues = tb.validate_content(_body().get('content'))
    return response_api_success({'valid': not issues, 'issues': issues, 'content': clean})


@tutorials_blueprint.route('/manage/tutorials/try', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def manage_try():
    return _run(tb.preview, viewer(), _body().get('content'))


@tutorials_blueprint.route('/manage/tutorials/import', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def manage_import():
    raw = _body().get('file')
    if not isinstance(raw, (str, dict)):
        return response_error('Choose a tutorial file to import')
    try:
        return response_api_created(tb.import_file(viewer(), raw))
    except tb.TutorialError as exc:
        return _error(exc)


@tutorials_blueprint.route('/manage/tutorials/<ref>', methods=['GET'])
@ac_api_requires(Permissions.server_administrator)
def manage_get(ref):
    return _run(tb.admin_get, ref)


@tutorials_blueprint.route('/manage/tutorials/<ref>/save', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def manage_save(ref):
    return _run(tb.save, viewer(), ref, _body())


@tutorials_blueprint.route('/manage/tutorials/<ref>/delete', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def manage_delete(ref):
    return _run(tb.delete, ref)


@tutorials_blueprint.route('/manage/tutorials/<ref>/export', methods=['GET'])
@ac_api_requires(Permissions.server_administrator)
def manage_export(ref):
    try:
        content, filename = tb.export(ref)
    except tb.TutorialError as exc:
        return _error(exc)
    return Response(json.dumps(content, indent=2, ensure_ascii=False) + '\n', mimetype='application/json',
                    headers={'Content-Disposition': 'attachment; filename="%s"' % filename,
                             'X-Content-Type-Options': 'nosniff'})

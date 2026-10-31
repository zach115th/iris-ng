"""iris-ng: the (i) help icons' glossary (2026-10-30).

  GET /help/glossary      every term on one searchable page, with this
                          server's lookup values (signed-in users)
  GET /help/glossary.js   the glossary as a script for the icons; the URL
                          carries the content hash, so a matching ?v= is
                          cached for good and a new release fetches anew
The portal serves guests their subset at /portal/help/glossary.js
(blueprints/pages/portal/portal_routes.py); the values behind a "values" term
come from GET /api/v2/help/values/<source>.
"""
from typing import Union

from flask import Blueprint
from flask import Response
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.access_controls import ac_requires
from app.business.help_glossary import WIKI_BASE
from app.business.help_glossary import client_script
from app.business.help_glossary import glossary_page_groups
from app.business.help_glossary import value_rows

help_blueprint = Blueprint('help', __name__, template_folder='templates')

# Values long enough to fold behind a <details> on the glossary page.
FOLD_VALUES_OVER = 12


def glossary_script_response(viewer):
    script = client_script(viewer)
    resp = Response(script['js'], mimetype='application/javascript')
    if request.args.get('v') == script['hash']:
        resp.headers['Cache-Control'] = 'private, max-age=31536000, immutable'
    else:
        resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    return resp


@help_blueprint.route('/help/glossary', methods=['GET'])
@ac_requires(no_cid_required=True)
def help_glossary_page(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for('help.help_glossary_page', cid=caseid))
    groups = glossary_page_groups()
    values = {}
    for group in groups:
        for t in group['terms']:
            if t['values'] and t['values'] not in values:
                values[t['values']] = value_rows(t['values']) or []
    return render_template('help_glossary.html', groups=groups, values=values, wiki_base=WIKI_BASE,
                           fold_over=FOLD_VALUES_OVER, caseid=caseid)


@help_blueprint.route('/help/glossary.js', methods=['GET'])
@ac_api_requires()
def help_glossary_script():
    return glossary_script_response('user')

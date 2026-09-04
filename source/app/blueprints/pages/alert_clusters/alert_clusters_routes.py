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

"""Alert Clusters page (iris-ng v2, Phase 2). Server-rendered shell; all
data comes from /api/v2/alert-clusters* (alert_clusters.js)."""

from typing import Union

from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import url_for
from flask_wtf import FlaskForm
from werkzeug import Response

from app.blueprints.access_controls import ac_requires
from app.models.authorization import Permissions

alert_clusters_page_blueprint = Blueprint(
    'alert_clusters',
    __name__,
    template_folder='templates'
)


@alert_clusters_page_blueprint.route('/alert-clusters', methods=['GET'])
@ac_requires(Permissions.alerts_read, no_cid_required=True)
def alert_clusters_view_route(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for('alert_clusters.alert_clusters_view_route', cid=caseid))

    form = FlaskForm()
    return render_template('alert_clusters.html', caseid=caseid, form=form)


@alert_clusters_page_blueprint.route('/alert-clusters/<int:cluster_id>', methods=['GET'])
@ac_requires(Permissions.alerts_read, no_cid_required=True)
def alert_cluster_detail_route(cluster_id, caseid, url_redir) -> Union[str, Response]:
    """v3-parity detail page (own URL, like v3's /alert-clusters/<id>). The
    shell is server-rendered; data + tenant checks live in the v2 API, which
    404s ids the viewer must not see — the page then shows its own not-found
    state rather than leaking anything here."""
    if url_redir:
        return redirect(url_for('alert_clusters.alert_cluster_detail_route',
                                cluster_id=cluster_id, cid=caseid))

    form = FlaskForm()
    return render_template('alert_cluster_detail.html', caseid=caseid,
                           cluster_id=cluster_id, form=form)

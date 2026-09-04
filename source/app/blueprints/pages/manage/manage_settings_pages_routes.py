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

"""v3-style Settings pages (2026-08-31): four panes extracted VERBATIM out
of /manage/settings' tab bar into standalone pages under the shared
MANAGE IRIS rail — Notifications (org defaults matrix), Mail rules
(rules + ingest log; the IMAP/SMTP mailbox CONFIG stays on Server
settings, exactly the split v3 makes), Clustering Rules and
Investigation flows — plus the new Banners management page. All
server_administrator, like the tabs they came from."""

from typing import Union

from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import url_for
from flask_wtf import FlaskForm
from werkzeug import Response

from app.blueprints.access_controls import ac_requires
from app.models.authorization import Permissions
from app.models.alerts import Severity
from app.models.models import CaseClassification
from app.models.models import Client

manage_settings_pages_blueprint = Blueprint(
    'manage_settings_pages',
    __name__,
    template_folder='templates'
)


@manage_settings_pages_blueprint.route('/manage/notifications', methods=['GET'])
@ac_requires(Permissions.server_administrator, no_cid_required=True)
def manage_notifications_view_route(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for('manage_settings_pages.manage_notifications_view_route', cid=caseid))

    from app.datamgmt.manage.manage_srv_settings_db import get_srv_settings
    from app.business.notifications import org_defaults_matrix
    server_settings = get_srv_settings()
    return render_template('manage_notifications.html', form=FlaskForm(),
                           settings=server_settings,
                           notification_events=org_defaults_matrix(server_settings))


@manage_settings_pages_blueprint.route('/manage/mail-rules', methods=['GET'])
@ac_requires(Permissions.server_administrator, no_cid_required=True)
def manage_mail_rules_view_route(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for('manage_settings_pages.manage_mail_rules_view_route', cid=caseid))

    # Catalogs for the rule editor selects — lookup ids vary per deployment,
    # always server-render from the live tables (moved here with the editor).
    mail_customers = Client.query.order_by(Client.name.asc()).all()
    mail_severities = Severity.query.order_by(Severity.severity_id.asc()).all()
    mail_classifications = CaseClassification.query.order_by(CaseClassification.name.asc()).all()
    return render_template('manage_mail_rules.html', form=FlaskForm(),
                           mail_customers=mail_customers,
                           mail_severities=mail_severities,
                           mail_classifications=mail_classifications)


@manage_settings_pages_blueprint.route('/manage/clustering-rules', methods=['GET'])
@ac_requires(Permissions.server_administrator, no_cid_required=True)
def manage_clustering_rules_view_route(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for('manage_settings_pages.manage_clustering_rules_view_route', cid=caseid))

    return render_template('manage_clustering_rules.html', form=FlaskForm())


@manage_settings_pages_blueprint.route('/manage/investigation-flows', methods=['GET'])
@ac_requires(Permissions.server_administrator, no_cid_required=True)
def manage_investigation_flows_view_route(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for('manage_settings_pages.manage_investigation_flows_view_route', cid=caseid))

    return render_template('manage_investigation_flows.html', form=FlaskForm())


@manage_settings_pages_blueprint.route('/manage/banners', methods=['GET'])
@ac_requires(Permissions.server_administrator, no_cid_required=True)
def manage_banners_view_route(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for('manage_settings_pages.manage_banners_view_route', cid=caseid))

    return render_template('manage_banners.html', form=FlaskForm())

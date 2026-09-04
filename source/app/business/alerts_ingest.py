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

"""Shared alert-ingest business layer.

Extracted verbatim from ``alerts_add_route`` (blueprints/rest/alerts_routes.py) so
that every way an alert can enter IRIS goes through ONE function:

  - ``POST /alerts/add``           (the API route -- a thin wrapper around this)
  - the mail-rule ingest poller    (iris_engine/mail/, no request context)

and so the post-create pipeline (alert clustering, investigation-flow attachment)
has a single, fail-soft place to hook. The route's request/response behaviour is
preserved exactly: this function raises, the route converts to the same
``response_error`` payloads it always produced.

Behavioural contract (verified byte-for-byte against the pre-extraction route by
a canned-alert probe -- good path, schema-error path, unknown-client path, plus
side effects: history entry, similarity-cache rows, ioc/asset attachment):

  - schema/DB errors propagate to the caller unchanged;
  - the client-access failure raises ``BusinessProcessingError`` with the exact
    legacy message string;
  - commit happens BEFORE the history entry and similarity cache, matching the
    original ordering.
"""

import json
from datetime import datetime

from flask_login import current_user

import app
from app import db
from app.business.errors import BusinessProcessingError
from app.models.authorization import User
from app.datamgmt.alerts.alerts_db import cache_similar_alert
from app.datamgmt.manage.manage_access_control_db import user_has_client_access
from app.iris_engine.module_handler.module_handler import call_modules_hook
from app.iris_engine.utils.tracker import track_activity
from app.models.alerts import Alert
from app.schema.marshables import AlertSchema
from app.schema.marshables import CaseAssetsSchema
from app.schema.marshables import IocSchema
from app.util import add_obj_history_entry

CLIENT_ACCESS_MESSAGE = 'User not entitled to create alerts for the client'


def create_alert_from_payload(data: dict, *, user_id: int,
                              enforce_client_access: bool = True) -> Alert:
    """Create one alert from an /alerts/add-shaped payload.

    ``user_id`` is the acting user: ``current_user.id`` on the API route, the
    system actor for non-interactive ingest (mail poller). With
    ``enforce_client_access=False`` the per-client entitlement check is skipped
    -- ONLY for system ingest paths that resolve the customer themselves.

    Raises marshmallow/DB errors unchanged; raises BusinessProcessingError with
    the legacy message when the user lacks client access.
    """
    alert_schema = AlertSchema()
    ioc_schema = IocSchema()
    asset_schema = CaseAssetsSchema()

    iocs_list = data.pop('alert_iocs', [])
    assets_list = data.pop('alert_assets', [])

    iocs = ioc_schema.load(iocs_list, many=True, partial=True)
    assets = asset_schema.load(assets_list, many=True, partial=True)

    # Deserialize the JSON data into an Alert object
    new_alert = alert_schema.load(data)

    # Verify the user is entitled to create an alert for the client
    if enforce_client_access and not user_has_client_access(user_id, new_alert.alert_customer_id):
        raise BusinessProcessingError(CLIENT_ACCESS_MESSAGE)

    new_alert.alert_creation_time = datetime.utcnow()

    new_alert.iocs = iocs
    new_alert.assets = assets

    # Add the new alert to the session and commit it
    db.session.add(new_alert)
    db.session.commit()

    # Add history entry. On the API route current_user carries the actor and
    # behaviour is byte-identical to the pre-extraction code; in a worker
    # context (mail poller) current_user resolves to None, so the acting user
    # row is passed explicitly.
    actor = None
    if getattr(current_user, 'id', None) is None:
        actor = db.session.get(User, user_id)
    add_obj_history_entry(new_alert, 'Alert created', user=actor)

    # Cache the alert for similarities check
    cache_similar_alert(new_alert.alert_customer_id, assets=assets_list,
                        iocs=iocs_list, alert_id=new_alert.alert_id,
                        creation_date=new_alert.alert_source_event_time)

    new_alert = call_modules_hook('on_postload_alert_create', data=new_alert)

    track_activity(f"created alert #{new_alert.alert_id} - {new_alert.alert_title}", ctx_less=True)

    # Emit a socket io event
    app.socket_io.emit('new_alert', json.dumps({
        'alert_id': new_alert.alert_id
    }), namespace='/alerts')

    _run_post_create_pipeline(new_alert)

    return new_alert


def _run_post_create_pipeline(alert: Alert) -> None:
    """Extension point for ingest-time enrichment. Each stage MUST be fail-soft:
    a defect in clustering or flow attachment must never fail alert ingest
    (this path serves n8n bulk ingest). Every failure path rolls the session
    back — a poisoned session reaching a later commit is the
    PendingRollbackError shape (fork rule).

    Stages:
      - Phase 2: alert clustering  (business/alert_clustering.py::evaluate_alert)
      - Phase 3: investigation-flow attachment
        (business/investigation_flows.py::evaluate_attachment)
    """
    cluster = None
    try:
        # Import here, not at module top: the ingest hot path must load even
        # if a pipeline stage's module is broken.
        from app.business.alert_clustering import evaluate_alert
        cluster = evaluate_alert(alert)
    except Exception:
        db.session.rollback()
        app.app.logger.exception(
            f'alert post-create pipeline: clustering failed for alert '
            f'#{alert.alert_id} — ingest unaffected')

    try:
        from app.business.investigation_flows import evaluate_attachment
        evaluate_attachment(
            alert, cluster=cluster,
            cluster_created=bool(getattr(cluster, 'freshly_created', False)))
    except Exception:
        db.session.rollback()
        app.app.logger.exception(
            f'alert post-create pipeline: flow attachment failed for alert '
            f'#{alert.alert_id} — ingest unaffected')

    # Phase 4: org-wide asset registry — alert assets carry no case, so the
    # customer comes from the alert. sync_alert_assets is internally
    # fail-soft AND runs on its own engine connection, but the belt stays.
    try:
        from app.datamgmt.manage.customer_assets_db import sync_alert_assets
        sync_alert_assets(alert)
    except Exception:
        db.session.rollback()
        app.app.logger.exception(
            f'alert post-create pipeline: customer-asset sync failed for alert '
            f'#{alert.alert_id} — ingest unaffected')

    return None

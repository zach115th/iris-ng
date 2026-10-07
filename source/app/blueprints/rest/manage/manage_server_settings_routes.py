#  IRIS Source Code
#  Copyright (C) 2024 - DFIR-IRIS
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

import marshmallow
from flask import Blueprint
from flask import request

from app import app
from app import celery
from app import db
from app.datamgmt.manage.manage_srv_settings_db import get_srv_settings
from app.iris_engine.backup.backup import backup_iris_db
from app.iris_engine.updater.updater import remove_periodic_update_checks
from app.iris_engine.updater.updater import setup_periodic_update_checks
from app.iris_engine.utils.tracker import track_activity
from app.models.authorization import Permissions
from app.schema.marshables import ServerSettingsSchema
from app.blueprints.access_controls import ac_api_requires
from app.blueprints.responses import response_error
from app.blueprints.responses import response_success
from dictdiffer import diff

manage_server_settings_rest_blueprint = Blueprint('manage_server_settings_rest', __name__)


@manage_server_settings_rest_blueprint.route('/manage/server/backups/make-db', methods=['GET'])
@ac_api_requires(Permissions.server_administrator)
def manage_make_db_backup():

    has_error, logs = backup_iris_db()
    if has_error:
        rep = response_error('Backup failed', data=logs)

    else:
        rep = response_success('Backup done', data=logs)

    return rep


@manage_server_settings_rest_blueprint.route('/manage/settings/update', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def manage_update_settings():
    if not request.is_json:
        return response_error('Invalid request')

    srv_settings_schema = ServerSettingsSchema()
    server_settings = get_srv_settings()
    original_update_check = server_settings.enable_updates_check

    try:

        original_settings = srv_settings_schema.dump(server_settings)
        new_settings = request.get_json()

        # iris-ng v2: the mail passwords are write-only — the settings GET never
        # returns them, so the UI submits blank (or the mask) to mean "keep the
        # stored value". Drop those keys so the load leaves the column untouched.
        # A non-empty submission replaces the secret; consequently a stored
        # password cannot be cleared to empty, only overwritten — to stop using
        # the mailbox, disable mail ingest instead. (The activity-log diff below
        # records only 'change' rows against the dump, which never contains
        # these keys, so a submitted secret cannot reach the log either.)
        # The two AI backend API keys joined the write-only set on 2026-10-07.
        for secret_key in ('mail_imap_password', 'mail_smtp_password',
                           'ai_backend_api_key', 'ai_backend_alt_api_key'):
            if new_settings.get(secret_key) in (None, '', '********'):
                new_settings.pop(secret_key, None)

        differences = list(diff(original_settings, new_settings))
        changes = [{difference[1]: difference[2]} for difference in differences if difference[0] == 'change']

        srv_settings_sc = srv_settings_schema.load(new_settings, instance=server_settings)
        db.session.commit()

        if original_update_check != srv_settings_sc.enable_updates_check:
            if srv_settings_sc.enable_updates_check:
                setup_periodic_update_checks(celery)
            else:
                remove_periodic_update_checks()
        if srv_settings_sc:
            track_activity(f"Server settings updated: {changes}")
            app.config['SERVER_SETTINGS'] = srv_settings_schema.dump(server_settings)
            return response_success("Server settings updated", app.config['SERVER_SETTINGS'])

    except marshmallow.exceptions.ValidationError as e:
        return response_error(msg="Data error", data=e.messages)


_BEDROCK_SLOTS = {
    'primary': ('ai_backend_url', 'ai_backend_api_key', 'ai_backend_model_catalog'),
    'alt': ('ai_backend_alt_url', 'ai_backend_alt_api_key', 'ai_backend_alt_model_catalog'),
}


@manage_server_settings_rest_blueprint.route('/manage/settings/ai/bedrock/catalog', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def manage_ai_bedrock_catalog():
    """List the Bedrock inference profiles a slot's key can see and cache them on the slot.

    Body: {slot: 'primary'|'alt', region: <region or endpoint URL>, api_key?: <key>}.
    The key typed in the (unsaved) form wins when non-empty, else the slot's
    stored key -- resolved here so the browser never receives a stored key.
    The listing is persisted into the slot's *_model_catalog column so the
    Settings page renders the Model dropdown offline; the reply carries the
    catalog and never the key. Bedrock errors (403 on a bad key, DNS on a
    bad region) come back as 400 with Bedrock's message.
    """
    from app.iris_engine.ai.bedrock_client import list_inference_profiles
    from app.iris_engine.ai.openai_client import AIClientError

    if not request.is_json:
        return response_error('Invalid request')
    body = request.get_json() or {}
    slot = (body.get('slot') or 'primary').strip().lower()
    if slot not in _BEDROCK_SLOTS:
        return response_error('Unknown backend slot', data={'slot': [slot]})
    url_attr, key_attr, catalog_attr = _BEDROCK_SLOTS[slot]

    settings = get_srv_settings()
    region = (body.get('region') or '').strip() or (getattr(settings, url_attr, None) or '').strip()
    if not region:
        return response_error('Enter the Bedrock region first', data={'region': ['empty']})
    api_key = (body.get('api_key') or '').strip() or (getattr(settings, key_attr, None) or '').strip()
    if not api_key:
        return response_error('Enter the Bedrock API key first (none stored for this slot)',
                              data={'api_key': ['empty']})

    try:
        catalog = list_inference_profiles(region, api_key)
    except AIClientError as e:
        msg = str(e)
        if 'ListInferenceProfiles' in msg and 'not authorized' in msg:
            # A console-generated long-term key's IAM user has inference rights but
            # not the control-plane listing. Say what to attach instead of relaying
            # only the IAM sentence; pasting the ARN under "Other" works meanwhile.
            return response_error(
                "Bedrock listing failed: this API key's IAM user lacks bedrock:ListInferenceProfiles. "
                "Attach a policy allowing bedrock:ListInferenceProfiles and bedrock:GetInferenceProfile "
                "on resource * (Bedrock console > API keys > Long-term > Manage in IAM Console), or pick "
                "'Other' and paste the inference profile ARN. AWS said: " + msg)
        return response_error(f'Bedrock listing failed: {msg}')

    setattr(settings, catalog_attr, catalog)
    db.session.commit()
    app.config['SERVER_SETTINGS'] = ServerSettingsSchema().dump(settings)
    track_activity(f"Bedrock inference-profile catalog refreshed for the {slot} AI backend slot "
                   f"({len(catalog)} entries)")
    return response_success('Catalog refreshed', data={
        'slot': slot,
        'count': len(catalog),
        'application': sum(1 for c in catalog if c.get('type') == 'APPLICATION'),
        'catalog': catalog,
    })

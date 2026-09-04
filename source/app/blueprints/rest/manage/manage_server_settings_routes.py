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
        for secret_key in ('mail_imap_password', 'mail_smtp_password'):
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

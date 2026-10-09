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
        # (The AI backend keys live on the ai_backend rows since 2026-10-09 and
        # go through /manage/settings/ai/backends/*, never this form.)
        for secret_key in ('mail_imap_password', 'mail_smtp_password'):
            if new_settings.get(secret_key) in (None, '', '********'):
                new_settings.pop(secret_key, None)

        # iris-ng 2026-10-09: the AI pointers name ai_backend rows. An id that
        # does not exist is a Data error (naming the field / feature), so a
        # stale page cannot silently point the stack at nothing; '' and None
        # mean "no backend" / "follow the global one".
        problems = _check_backend_pointers(new_settings)
        if problems:
            return response_error(msg="Data error", data=problems)

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


# ---------------------------------------------------------------------------
# AI backends (iris-ng, 2026-10-09): any number of `ai_backend` rows, each
# saved / deleted on its own through the routes below (legacy envelope,
# session or API key, CSRF in the body like every /manage POST). The settings
# form keeps only the pointers (ai_backend_active_id, ai_feature_overrides).
# ---------------------------------------------------------------------------

_KEEP_KEY = (None, '', '********')


def _coerce_backend_id(value):
    """(ok, id_or_None). ok is False for a value that is neither empty nor an
    integer-looking id."""
    if value is None or value == '':
        return True, None
    if isinstance(value, bool):
        return False, None
    try:
        return True, int(str(value).strip())
    except (TypeError, ValueError):
        return False, None


def _check_backend_pointers(new_settings: dict) -> dict:
    """Validate ai_backend_active_id and every ai_feature_overrides value against
    the ai_backend table; normalise them to ints / None in place. Returns the
    marshmallow-shaped problems dict ({} when clean)."""
    from app.datamgmt.manage.manage_ai_backends_db import get_ai_backend

    problems: dict = {}
    if 'ai_backend_active_id' in new_settings:
        ok, bid = _coerce_backend_id(new_settings.get('ai_backend_active_id'))
        if not ok or (bid is not None and get_ai_backend(bid) is None):
            problems['ai_backend_active_id'] = [f'unknown backend {new_settings.get("ai_backend_active_id")!r}']
        else:
            new_settings['ai_backend_active_id'] = bid
    overrides = new_settings.get('ai_feature_overrides')
    if isinstance(overrides, dict):
        cleaned = {}
        for feature, value in overrides.items():
            ok, bid = _coerce_backend_id(value)
            if not ok or (bid is not None and get_ai_backend(bid) is None):
                problems.setdefault('ai_feature_overrides', []).append(f'{feature}: unknown backend {value!r}')
                continue
            cleaned[feature] = bid
        if 'ai_feature_overrides' not in problems:
            new_settings['ai_feature_overrides'] = cleaned
    return problems


def _backend_payload(backend, active_id) -> dict:
    from app.schema.marshables import AiBackendSchema
    data = AiBackendSchema().dump(backend)
    data['is_active'] = (active_id is not None and backend.id == active_id)
    return data


def _refresh_settings_cache():
    app.config['SERVER_SETTINGS'] = ServerSettingsSchema().dump(get_srv_settings())


@manage_server_settings_rest_blueprint.route('/manage/settings/ai/backends/list', methods=['GET'])
@ac_api_requires(Permissions.server_administrator)
def manage_ai_backends_list():
    """Every configured backend (never a key) + the active id."""
    from app.datamgmt.manage.manage_ai_backends_db import list_ai_backends
    settings = get_srv_settings()
    active_id = settings.ai_backend_active_id if settings else None
    return response_success('', data={
        'active_id': active_id,
        'backends': [_backend_payload(b, active_id) for b in list_ai_backends()],
    })


@manage_server_settings_rest_blueprint.route('/manage/settings/ai/backends/add', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def manage_ai_backends_add():
    """Create a backend. Body: {label, provider?, url?, model?, api_key?}. The
    label must be unique (case-insensitive). The FIRST backend of an install
    becomes the active one so a single configured backend works without a
    trip to the radio."""
    from app.datamgmt.manage.manage_ai_backends_db import find_ai_backend_by_label
    from app.datamgmt.manage.manage_ai_backends_db import next_ai_backend_position
    from app.models.models import AiBackend
    from app.schema.marshables import AiBackendSchema

    if not request.is_json:
        return response_error('Invalid request')
    try:
        data = AiBackendSchema().load(request.get_json() or {})
    except marshmallow.exceptions.ValidationError as e:
        return response_error(msg="Data error", data=e.messages)
    label = data['label'].strip()
    clash = find_ai_backend_by_label(label)
    if clash is not None:
        return response_error(msg="Data error", data={'label': [f'already used by backend #{clash.id} ({clash.label})']})

    backend = AiBackend(
        label=label,
        provider=(data.get('provider') or 'openai').strip().lower(),
        url=(data.get('url') or '').strip() or None,
        model=(data.get('model') or '').strip() or None,
        api_key=(data.get('api_key') or '').strip() or None,
        position=next_ai_backend_position(),
    )
    db.session.add(backend)
    settings = get_srv_settings()
    db.session.flush()
    became_active = False
    if settings is not None and settings.ai_backend_active_id is None:
        settings.ai_backend_active_id = backend.id
        became_active = True
    db.session.commit()
    _refresh_settings_cache()
    track_activity(f"AI backend #{backend.id} '{backend.label}' added (provider {backend.provider}"
                   f"{', now active' if became_active else ''})")
    return response_success('Backend added', data=_backend_payload(backend, settings.ai_backend_active_id if settings else None))


@manage_server_settings_rest_blueprint.route('/manage/settings/ai/backends/update/<int:backend_id>', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def manage_ai_backends_update(backend_id):
    """Update a backend. Any subset of {label, provider, url, model, api_key};
    an api_key submitted empty or as the mask keeps the stored key (write-only
    contract, like the mail passwords)."""
    from app.datamgmt.manage.manage_ai_backends_db import find_ai_backend_by_label
    from app.datamgmt.manage.manage_ai_backends_db import get_ai_backend
    from app.schema.marshables import AiBackendSchema
    from sqlalchemy import func as sa_func

    if not request.is_json:
        return response_error('Invalid request')
    backend = get_ai_backend(backend_id)
    if backend is None:
        return response_error('Unknown backend', data={'id': [backend_id]})
    body = dict(request.get_json() or {})
    if body.get('api_key') in _KEEP_KEY:
        body.pop('api_key', None)
    try:
        data = AiBackendSchema(partial=True).load(body)
    except marshmallow.exceptions.ValidationError as e:
        return response_error(msg="Data error", data=e.messages)

    changes = []
    if 'label' in data:
        label = data['label'].strip()
        clash = find_ai_backend_by_label(label, exclude_id=backend.id)
        if clash is not None:
            return response_error(msg="Data error", data={'label': [f'already used by backend #{clash.id} ({clash.label})']})
        if label != backend.label:
            changes.append('label')
            backend.label = label
    if 'provider' in data:
        provider = (data.get('provider') or 'openai').strip().lower()
        if provider != backend.provider:
            changes.append('provider')
            backend.provider = provider
    for field in ('url', 'model'):
        if field in data:
            value = (data.get(field) or '').strip() or None
            if value != getattr(backend, field):
                changes.append(field)
                setattr(backend, field, value)
    if 'api_key' in data:
        backend.api_key = (data.get('api_key') or '').strip() or None
        changes.append('api_key')
    if changes:
        backend.updated_at = sa_func.now()
        db.session.commit()
        _refresh_settings_cache()
        track_activity(f"AI backend #{backend.id} '{backend.label}' updated: {', '.join(changes)}")
    settings = get_srv_settings()
    return response_success('Backend updated' if changes else 'No change',
                            data=_backend_payload(backend, settings.ai_backend_active_id if settings else None))


@manage_server_settings_rest_blueprint.route('/manage/settings/ai/backends/delete/<int:backend_id>', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def manage_ai_backends_delete(backend_id):
    """Delete a backend. The ACTIVE backend is refused (switch first); features
    pinned to the deleted backend fall back to the global one (their override
    resets to null) and are named in the reply. Deleting down to zero is
    allowed -- every AI surface then reports "not configured"."""
    from app.datamgmt.manage.manage_ai_backends_db import clear_feature_overrides_for
    from app.datamgmt.manage.manage_ai_backends_db import get_ai_backend

    backend = get_ai_backend(backend_id)
    if backend is None:
        return response_error('Unknown backend', data={'id': [backend_id]})
    settings = get_srv_settings()
    if settings is not None and settings.ai_backend_active_id == backend.id:
        return response_error('This backend is the active one: pick another backend as active and save, then delete it',
                              data={'id': ['active']})
    cleared = clear_feature_overrides_for(settings, backend.id) if settings is not None else []
    label = backend.label
    db.session.delete(backend)
    db.session.commit()
    _refresh_settings_cache()
    track_activity(f"AI backend #{backend_id} '{label}' deleted"
                   f"{' (overrides cleared: ' + ', '.join(cleared) + ')' if cleared else ''}")
    return response_success('Backend deleted', data={'deleted': backend_id, 'overrides_cleared': cleared})


@manage_server_settings_rest_blueprint.route('/manage/settings/ai/backends/<int:backend_id>/catalog', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def manage_ai_backend_catalog(backend_id):
    """List the Bedrock inference profiles a backend's key can see and cache
    them on the row.

    Body: {region?: <region or endpoint URL>, api_key?: <key>}. A value typed
    in the (unsaved) card wins when non-empty, else the row's stored value --
    resolved here so the browser never receives a stored key. The listing is
    persisted into the row's model_catalog so the Settings page renders the
    Model dropdown offline; the reply carries the catalog and never the key.
    Bedrock errors (403 on a bad key, DNS on a bad region) come back as 400
    with Bedrock's message.
    """
    from app.datamgmt.manage.manage_ai_backends_db import get_ai_backend
    from app.iris_engine.ai.bedrock_client import list_inference_profiles
    from app.iris_engine.ai.openai_client import AIClientError

    if not request.is_json:
        return response_error('Invalid request')
    backend = get_ai_backend(backend_id)
    if backend is None:
        return response_error('Unknown backend', data={'id': [backend_id]})
    body = request.get_json() or {}
    region = (body.get('region') or '').strip() or (backend.url or '').strip()
    if not region:
        return response_error('Enter the Bedrock region first', data={'region': ['empty']})
    api_key = (body.get('api_key') or '').strip() or (backend.api_key or '').strip()
    if not api_key:
        return response_error('Enter the Bedrock API key first (none stored for this backend)',
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

    backend.model_catalog = catalog
    db.session.commit()
    track_activity(f"Bedrock inference-profile catalog refreshed for AI backend #{backend.id} '{backend.label}' "
                   f"({len(catalog)} entries)")
    return response_success('Catalog refreshed', data={
        'id': backend.id,
        'count': len(catalog),
        'application': sum(1 for c in catalog if c.get('type') == 'APPLICATION'),
        'catalog': catalog,
    })

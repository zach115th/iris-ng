#  IRIS Source Code
#  Copyright (C) 2021 - Airbus CyberSecurity (SAS)
#  ir@cyberactionlab.net
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

"""How celery task results are stored: the JSON form of IIStatus, and a result backend that never unpickles.

Since celery 5.7 the database result backend encodes a task's result with ``result_serializer`` (``json`` here)
instead of pickling it. Module hooks, import pipelines, AI jobs and the update check return an ``IIStatus`` from the
module interface, which JSON cannot encode by itself: without the type registered below each of those tasks would be
stored FAILURE (``EncodeError``) although it ran, and the DIM Tasks modal would lose the module's verdict and logs.

``make_celery()`` (``app.iris_engine.tasker.celery``) registers the type where the web process and both workers build
their celery app, so every process encodes and decodes a status the same way. An ``IIStatus`` keeps its code,
message and logs; its ``data`` is kept only when it is plain JSON (module hooks hand back the ORM objects they were
given, and nothing reads ``data`` from a stored result).

celery 5.7 still unpickles a stored result that starts with the pickle marker (the rows written before it), in
whatever process reads it - the web process, when the DIM Tasks modal opens one. ``IrisDatabaseBackend`` never
unpickles: such a row reads as ``StoredResultNotRead``. celery's daily clean-up removes results older than
``result_expires`` (a day), so the rows from before the update are gone a day later.
"""
import json
import logging

from celery.backends.database import DatabaseBackend
from iris_interface.IrisInterfaceStatus import IIStatus
from kombu.utils.encoding import ensure_bytes
from kombu.utils.json import register_type

log = logging.getLogger(__name__)

IISTATUS_JSON_MARKER = 'iris_iistatus'
PICKLE_MARKER = b'\x80'


def _json_native(value) -> bool:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False
    return True


def encode_iistatus(status: IIStatus) -> dict:
    logs = status.logs if isinstance(status.logs, (list, tuple)) else [status.logs]
    return {
        'code': status.code if isinstance(status.code, int) else 0xFFFF,
        'message': status.message if isinstance(status.message, str) else str(status.message),
        # A log entry that is not a string (merge_status() appends whole lists) is kept as the text the DIM Tasks
        # modal printed for it before.
        'logs': [entry if isinstance(entry, str) else str(entry) for entry in logs],
        'data': status.data if _json_native(status.data) else None,
    }


def decode_iistatus(value) -> IIStatus:
    if not isinstance(value, dict):
        return IIStatus(message='Unreadable task status')
    return IIStatus(code=value.get('code'), message=value.get('message'), data=value.get('data'),
                    logs=value.get('logs'))


def register_iistatus_json():
    register_type(IIStatus, IISTATUS_JSON_MARKER, encode_iistatus, decode_iistatus)


class StoredResultNotRead:
    """A stored task result IRIS does not open: a pickle (written before celery 5.7) or bytes it cannot decode."""

    def __repr__(self):
        return 'StoredResultNotRead()'


class IrisDatabaseBackend(DatabaseBackend):
    """celery's database result backend, without its fallback to unpickling a stored result."""

    def _decode_stored_result(self, payload):
        if payload is None:
            return None
        payload = ensure_bytes(payload)
        if payload[:1] == PICKLE_MARKER:
            return StoredResultNotRead()
        try:
            return self.decode(payload)
        except Exception:
            log.warning('A stored task result could not be decoded', exc_info=True)
            return StoredResultNotRead()

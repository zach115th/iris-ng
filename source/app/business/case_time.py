#  IRIS Source Code
#  iris-next
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

"""Business rules for analyst time tracking.

Policy enforced here (not in the datamgmt or DB layer):
  - minutes must be a positive multiple of 15.
  - an entry can be created/edited/deleted only while the case is OPEN
    (cases.close_date IS NULL). Closing locks; reopening unlocks.
  - an analyst may only edit/delete their OWN entries (unless they have
    full case access acting as a manager — the blueprint decides which
    access level to require; the business layer enforces ownership for the
    self-service path).
"""
from datetime import date
from datetime import datetime

from app.business.errors import BusinessProcessingError
from app.business.errors import ObjectNotFoundError
from app.datamgmt.case.case_time_db import case_is_open
from app.datamgmt.case.case_time_db import create_time_entry
from app.datamgmt.case.case_time_db import delete_time_entry
from app.datamgmt.case.case_time_db import get_time_entry
from app.datamgmt.case.case_time_db import task_belongs_to_case
from app.datamgmt.case.case_time_db import update_time_entry


def _validate_minutes(minutes):
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        raise BusinessProcessingError("'minutes' must be an integer")
    if minutes <= 0:
        raise BusinessProcessingError("'minutes' must be greater than zero")
    if minutes % 15 != 0:
        raise BusinessProcessingError("'minutes' must be a multiple of 15")
    return minutes


def _parse_activity_date(value):
    """Accept 'YYYY-MM-DD' (or None -> today). Stored as a plain Date."""
    if value is None or value == '':
        return date.today()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except ValueError:
        raise BusinessProcessingError("'activity_date' must be YYYY-MM-DD")


def _require_open_case(case_id):
    exists, is_open = case_is_open(case_id)
    if not exists:
        raise ObjectNotFoundError('Case not found')
    if not is_open:
        raise BusinessProcessingError(
            'Time entries are locked because this case is closed. '
            'Reopen the case to edit time.'
        )


def time_entry_create(case_id, user_id, body):
    _require_open_case(case_id)
    minutes = _validate_minutes(body.get('minutes'))
    activity_date = _parse_activity_date(body.get('activity_date'))
    task_id = body.get('task_id')
    if task_id in ('', 0):
        task_id = None
    if task_id is not None and not task_belongs_to_case(task_id, case_id):
        raise BusinessProcessingError('task_id does not belong to this case')
    note = (body.get('note') or '').strip() or None
    return create_time_entry(case_id, user_id, minutes, activity_date, task_id=task_id, note=note)


def _get_owned_entry(case_id, entry_id, acting_user_id, allow_any_owner=False):
    entry = get_time_entry(entry_id)
    if entry is None or entry.case_id != case_id:
        raise ObjectNotFoundError('Time entry not found')
    if not allow_any_owner and entry.user_id is not None and entry.user_id != acting_user_id:
        raise BusinessProcessingError('You can only edit your own time entries')
    return entry


def time_entry_update(case_id, entry_id, acting_user_id, body, allow_any_owner=False):
    _require_open_case(case_id)
    entry = _get_owned_entry(case_id, entry_id, acting_user_id, allow_any_owner)

    minutes = None
    if 'minutes' in body and body.get('minutes') is not None:
        minutes = _validate_minutes(body.get('minutes'))

    activity_date = None
    if 'activity_date' in body and body.get('activity_date') not in (None, ''):
        activity_date = _parse_activity_date(body.get('activity_date'))

    task_id = ...
    if 'task_id' in body:
        task_id = body.get('task_id')
        if task_id in ('', 0):
            task_id = None
        if task_id is not None and not task_belongs_to_case(task_id, case_id):
            raise BusinessProcessingError('task_id does not belong to this case')

    note = ...
    if 'note' in body:
        note = (body.get('note') or '').strip() or None

    return update_time_entry(entry, minutes=minutes, activity_date=activity_date,
                             task_id=task_id, note=note)


def time_entry_delete(case_id, entry_id, acting_user_id, allow_any_owner=False):
    _require_open_case(case_id)
    entry = _get_owned_entry(case_id, entry_id, acting_user_id, allow_any_owner)
    delete_time_entry(entry)

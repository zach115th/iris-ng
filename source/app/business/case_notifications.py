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

"""iris-next: business layer for the per-case notification bell."""
from datetime import datetime
from datetime import timezone

from app.business.errors import BusinessProcessingError
from app.datamgmt.case.case_notifications_db import ACTIVITY_CATEGORIES
from app.datamgmt.case.case_notifications_db import list_activity
from app.datamgmt.case.case_notifications_db import acknowledge
from app.datamgmt.case.case_notifications_db import count_unread
from app.datamgmt.case.case_notifications_db import list_unread


def _parse_client_timestamp(value):
    """Parse the `latest_at` the client echoes back into naive UTC.

    UserActivity.activity_date is stored naive-UTC, so a tz-aware value has to
    be normalised to UTC and stripped before it can be compared against it -
    mixing the two raises TypeError at comparison time.
    """
    if value in (None, ''):
        return None

    if not isinstance(value, str):
        raise BusinessProcessingError('up_to must be an ISO-8601 timestamp string')

    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise BusinessProcessingError(f'Invalid timestamp: {value}')

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def case_notifications_list(user_id, case_id):
    """Unread activity for one case, scoped to one analyst."""
    return list_unread(user_id, case_id)


def case_notifications_count(user_id, case_id):
    """Just the badge number - cheap enough to poll."""
    return count_unread(user_id, case_id)


def case_notifications_acknowledge(user_id, case_id, up_to=None):
    """Mark this case's updates as read up to the point the analyst was shown."""
    watermark = acknowledge(user_id, case_id, _parse_client_timestamp(up_to))
    return {
        'acknowledged_at': watermark.isoformat() + 'Z' if watermark else None,
        'unread': count_unread(user_id, case_id),
    }


def case_activity_log(case_id, category=None, limit=None):
    """Recent case activity for the live log, optionally scoped to a view.

    Unlike the notification feed this ignores the read watermark and keeps
    the reader's own actions - it is a log of what happened in the case, not
    a list of things addressed to one analyst.
    """
    if category is not None and category not in ACTIVITY_CATEGORIES:
        raise BusinessProcessingError(f'Unknown activity category: {category}')
    kwargs = {'category': category}
    if limit is not None:
        kwargs['limit'] = limit
    return list_activity(case_id, **kwargs)

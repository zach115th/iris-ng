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

"""iris-next: data layer for the per-case notification bell.

Reads the existing UserActivity audit log rather than introducing a parallel
notification store - every mutation already writes a row there via
iris_engine.utils.tracker.track_activity, so there is nothing extra to emit and
the feed works retroactively over history that predates this feature.

The only new state is CaseNotificationAck: one read watermark per (user, case).
"""
from datetime import datetime
from datetime import timedelta

from sqlalchemy import and_
from sqlalchemy import func
from sqlalchemy import not_
from sqlalchemy import or_

from app import db
from app.models.models import CaseNotificationAck
from app.models.models import UserActivity
from app.models.authorization import User

# How far back to look for a case the analyst has never acknowledged. Without a
# bound, first sight of a long-running case dumps its entire history into the
# panel; with one, the bell opens on recent context. Only applies until the
# first acknowledgement - after that the watermark governs.
DEFAULT_LOOKBACK_DAYS = 14

# Maximum rows returned in one panel load. The unread *count* is not capped by
# this - it is computed separately, so the badge stays truthful.
MAX_ROWS = 50

# Description prefix -> kind, used purely for the row icon/colour in the panel.
# Matched case-insensitively against the start of activity_desc, longest first.
_KIND_PREFIXES = (
    ('added ioc', 'ioc'),
    ('updated ioc', 'ioc'),
    ('deleted ioc', 'ioc'),
    ('added asset', 'asset'),
    ('updated asset', 'asset'),
    ('deleted asset', 'asset'),
    ('added event', 'timeline'),
    ('updated event', 'timeline'),
    ('deleted event', 'timeline'),
    ('created note', 'note'),
    ('updated note', 'note'),
    ('deleted note', 'note'),
    ('added directory', 'note'),
    ('added task', 'task'),
    ('updated task', 'task'),
    ('deleted task', 'task'),
    ('added evidence', 'evidence'),
    ('updated evidence', 'evidence'),
    ('deleted evidence', 'evidence'),
    ('new case', 'case'),
    ('case', 'case'),
)


def _classify(description):
    """Best-effort row kind from the activity description, for the icon only.

    Deliberately conservative: anything unrecognised falls back to 'activity'
    rather than guessing, since a wrong icon is worse than a neutral one.
    """
    if not description:
        return 'activity'
    lowered = description.strip().lower()
    for prefix, kind in _KIND_PREFIXES:
        if lowered.startswith(prefix):
            return kind
    return 'activity'


def get_ack_watermark(user_id, case_id):
    """The analyst's last acknowledged timestamp for this case, or None."""
    row = CaseNotificationAck.query.filter(
        CaseNotificationAck.user_id == user_id,
        CaseNotificationAck.case_id == case_id
    ).first()
    return row.last_ack_at if row else None


def _unread_filter(user_id, case_id, since):
    """Shared WHERE clause for the unread set of one case.

    Actor rule: the analyst's own *interactive* actions are excluded - being
    notified of your own edit is noise. Rows carrying is_from_api stay in even
    under the analyst's own account, because those come from n8n, API clients
    and module hooks rather than from the person reading the panel.
    """
    conditions = [
        UserActivity.case_id == case_id,
        UserActivity.display_in_ui == True,  # noqa: E712 - SQLAlchemy needs ==
        not_(
            and_(
                UserActivity.user_id == user_id,
                or_(UserActivity.is_from_api == False,  # noqa: E712
                    UserActivity.is_from_api.is_(None))
            )
        ),
    ]
    if since is not None:
        conditions.append(UserActivity.activity_date > since)
    return conditions


def count_unread(user_id, case_id, since=None, _resolved=False):
    """Number of unread activities for (user, case). Drives the badge."""
    if not _resolved:
        since = _resolve_since(user_id, case_id)
    return db.session.query(func.count(UserActivity.id)).filter(
        *_unread_filter(user_id, case_id, since)
    ).scalar() or 0


def _resolve_since(user_id, case_id):
    """Watermark if the case was ever acknowledged, else the lookback floor."""
    watermark = get_ack_watermark(user_id, case_id)
    if watermark is not None:
        return watermark
    return datetime.utcnow() - timedelta(days=DEFAULT_LOOKBACK_DAYS)


def list_unread(user_id, case_id, limit=MAX_ROWS):
    """Unread activities for one case, newest first, plus counts and watermark.

    Returns a dict shaped for the REST layer:
        total          - full unread count (not capped by `limit`)
        items          - up to `limit` rows, newest first
        truncated      - True when total > len(items)
        latest_at      - ISO timestamp of the newest row returned, or None.
                         The client echoes this back on acknowledge so anything
                         arriving mid-read is not silently swallowed.
        acknowledged_at- current watermark, or None if never acknowledged
        window_days    - lookback applied when there is no watermark
    """
    watermark = get_ack_watermark(user_id, case_id)
    since = watermark if watermark is not None else (
        datetime.utcnow() - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    )

    conditions = _unread_filter(user_id, case_id, since)

    total = db.session.query(func.count(UserActivity.id)).filter(*conditions).scalar() or 0

    rows = db.session.query(
        UserActivity.id,
        UserActivity.activity_date,
        UserActivity.activity_desc,
        UserActivity.is_from_api,
        UserActivity.user_input,
        User.name,
        User.user
    ).outerjoin(
        User, User.id == UserActivity.user_id
    ).filter(*conditions).order_by(
        UserActivity.activity_date.desc()
    ).limit(limit).all()

    items = []
    for row in rows:
        items.append({
            'id': row.id,
            # Naive UTC in the column; append Z so the browser does not read it
            # as local time (same convention as the working-timeline serializer).
            'at': row.activity_date.isoformat() + 'Z' if row.activity_date else None,
            'text': row.activity_desc,
            'kind': _classify(row.activity_desc),
            'by': row.name or row.user or 'system',
            'from_api': bool(row.is_from_api),
            'is_note': bool(row.user_input),
        })

    return {
        'total': total,
        'items': items,
        'truncated': total > len(items),
        'latest_at': items[0]['at'] if items else None,
        'acknowledged_at': watermark.isoformat() + 'Z' if watermark else None,
        'window_days': None if watermark else DEFAULT_LOOKBACK_DAYS,
    }


def acknowledge(user_id, case_id, up_to=None):
    """Move the read watermark for (user, case) forward.

    `up_to` should be the `latest_at` the client was actually shown. Anything
    that lands after that stays unread instead of being swallowed by the ack -
    which is why the watermark is not simply utcnow().

    The watermark only ever moves forward, so a stale or replayed ack cannot
    re-hide activity the analyst has not seen.
    """
    if up_to is None:
        newest = db.session.query(func.max(UserActivity.activity_date)).filter(
            *_unread_filter(user_id, case_id, None)
        ).scalar()
        up_to = newest or datetime.utcnow()

    row = CaseNotificationAck.query.filter(
        CaseNotificationAck.user_id == user_id,
        CaseNotificationAck.case_id == case_id
    ).first()

    if row is None:
        row = CaseNotificationAck(user_id=user_id, case_id=case_id, last_ack_at=up_to)
        db.session.add(row)
    elif up_to > row.last_ack_at:
        row.last_ack_at = up_to

    db.session.commit()
    return row.last_ack_at

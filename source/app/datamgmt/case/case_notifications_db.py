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
import re
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

# ---------------------------------------------------------------------------
# Activity classification.
#
# UserActivity rows are TEXT ONLY - no object type or id column - so the only
# signal available is the description `track_activity()` wrote. That was fine
# while the classification only picked a row icon: an unrecognised row got a
# neutral icon and nothing was lost.
#
# It is now also the FILTER behind the per-view live case log, which raises
# the stakes: a row we fail to classify would silently vanish from every
# scoped view, and the view would then claim "no timeline activity" when the
# truth is "we could not tell". So the rules below are derived from the
# actual track_activity() call sites, `classify_activity` returns None (not a
# guess) when it cannot attribute a row, and the reader counts those rows and
# reports them rather than dropping them quietly.
#
# Matching happens AFTER the quoted portions are blanked, because analyst-
# supplied names are interpolated into these strings: a note titled
# "event log" must not be classified as timeline activity.
# ---------------------------------------------------------------------------
_QUOTED_RE = re.compile(r'"[^"]*"|\'[^\']*\'')

# Ordered: the first category whose pattern matches wins. Order only matters
# for descriptions mentioning two object words after the names are blanked,
# e.g. "comment {id} on ioc {id} deleted".
_CATEGORY_RULES = (
    ('datastore', re.compile(r'\b(?:datastore|added to ds|deleted from ds)\b')),
    ('timeline', re.compile(r'\b(?:event|events|timeline)\b')),
    ('ioc', re.compile(r'\b(?:ioc|iocs)\b')),
    ('asset', re.compile(r'\b(?:asset|assets)\b')),
    ('note', re.compile(r'\b(?:note|notes|directory|directories)\b')),
    ('task', re.compile(r'\b(?:task|tasks)\b')),
    ('evidence', re.compile(r'\b(?:evidence|evidences)\b')),
    ('case', re.compile(r'\b(?:case|cases|alert|alerts)\b')),
)

#: Categories a caller may scope the live log to.
ACTIVITY_CATEGORIES = tuple(name for name, _ in _CATEGORY_RULES)

#: Rows we could not attribute to any view.
UNATTRIBUTED = 'activity'

#: Upper bound on rows examined for one scoped read. Classification is text
#: matching and cannot run in SQL, so the window is scanned in Python; the
#: reader reports when it hits this so the UI never implies completeness it
#: does not have.
SCAN_CAP = 500


def classify_activity(description):
    """Category for one activity description, or None when unattributable.

    Returning None rather than a fallback is deliberate: the caller needs to
    tell "belongs to another view" from "could not be placed", and only the
    first of those is safe to hide.
    """
    if not description:
        return None
    lowered = _QUOTED_RE.sub('""', description).lower()
    for category, pattern in _CATEGORY_RULES:
        if pattern.search(lowered):
            return category
    return None


def _classify(description):
    """Row kind for the panel icon. Unattributable rows get a neutral kind."""
    return classify_activity(description) or UNATTRIBUTED


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


def _activity_filter(case_id, since):
    """Rows for the live case log.

    Deliberately WIDER than `_unread_filter`: this is a log, not a
    notification feed, so it keeps the reader's own actions and ignores the
    read watermark. `display_in_ui` is still honoured - some call sites
    (datastore downloads) opt out of being surfaced at all.
    """
    conditions = [
        UserActivity.case_id == case_id,
        UserActivity.display_in_ui == True,  # noqa: E712 - SQLAlchemy needs ==
    ]
    if since is not None:
        conditions.append(UserActivity.activity_date > since)
    return conditions


def list_activity(case_id, category=None, limit=MAX_ROWS,
                  window_days=DEFAULT_LOOKBACK_DAYS):
    """Recent case activity, optionally scoped to one view's category.

    Returns:
        items         - up to `limit` rows, newest first
        category      - the requested category, or None for everything
        shown         - len(items)
        matched       - rows in the window matching the category
        unattributed  - rows in the window no rule could place. Surfaced, not
                        dropped: an empty scoped view must be able to say
                        whether it means "nothing happened here" or "some
                        entries could not be attributed".
        scanned       - rows examined
        scan_capped   - True when `scanned` hit SCAN_CAP, so `matched` and
                        `unattributed` are lower bounds rather than totals
        window_days   - lookback applied
    """
    since = datetime.utcnow() - timedelta(days=window_days) if window_days else None
    conditions = _activity_filter(case_id, since)

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
    ).limit(SCAN_CAP).all()

    items = []
    matched = 0
    unattributed = 0
    for row in rows:
        kind = classify_activity(row.activity_desc)
        if kind is None:
            unattributed += 1
        if category is not None and kind != category:
            continue
        matched += 1
        if len(items) >= limit:
            continue
        items.append({
            'id': row.id,
            # Naive UTC in the column; append Z so the browser does not read
            # it as local time (same convention as everywhere else here).
            'at': row.activity_date.isoformat() + 'Z' if row.activity_date else None,
            'text': row.activity_desc,
            'kind': kind or UNATTRIBUTED,
            'by': row.name or row.user or 'system',
            'from_api': bool(row.is_from_api),
            'is_note': bool(row.user_input),
        })

    return {
        'items': items,
        'category': category,
        'shown': len(items),
        'matched': matched,
        'unattributed': unattributed,
        'scanned': len(rows),
        'scan_capped': len(rows) >= SCAN_CAP,
        'window_days': window_days,
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

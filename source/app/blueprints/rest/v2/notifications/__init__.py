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

"""Notifications + preferences + following REST surface (iris-ng v2, Phase 5).

Everything here is strictly SELF-scoped: a user reads, acks and configures
their own notifications and follows — there is no cross-user surface, so no
permission bit beyond an authenticated session (project rule: no new bits).
Follow targets are validated against the viewer's OWN access (case ACL /
client access) so following cannot be used to probe object existence.
"""

from datetime import datetime

from flask import Blueprint
from flask import request
from flask_login import current_user

from app import db
from app.blueprints.access_controls import ac_api_requires
from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
# Top-level import keeps task_send_notification_email registered on the
# celery workers (blueprints are imported at worker boot; function-local
# imports in routes are not — the Phase 4 scan lesson).
from app.business.notifications import EVENT_CATALOG
from app.business.notifications import _code_default
from app.business.notifications import task_send_notification_email  # noqa: F401
from app.datamgmt.manage.manage_access_control_db import user_has_client_access
from app.iris_engine.access_control.utils import ac_get_fast_user_cases_access
from app.models.alerts import Alert
from app.models.cases import Cases
from app.models.models import Notification
from app.models.models import ServerSettings
from app.models.models import UserActivity
from app.models.models import UserFollow
from app.models.models import UserNotificationPreference

notifications_blueprint = Blueprint('rest_v2_notifications', __name__)


def _iso(dt):
    if dt is None:
        return None
    return dt.isoformat() + ('Z' if dt.tzinfo is None else '')


def _notif_row(n: Notification) -> dict:
    return {
        'id': n.id, 'event_type': n.event_type, 'title': n.title,
        'body': n.body, 'object_type': n.object_type, 'object_id': n.object_id,
        'case_id': n.case_id, 'url': n.url, 'is_read': n.is_read,
        'created_at': _iso(n.created_at),
    }


# ------------------------------------------------------------- notifications

@notifications_blueprint.route('/notifications', methods=['GET'])
@ac_api_requires()
def list_notifications():
    q = Notification.query.filter(Notification.user_id == current_user.id)
    if request.args.get('unread') == 'true':
        q = q.filter(Notification.is_read.is_(False))
    total = q.count()
    page = max(int(request.args.get('page', 1) or 1), 1)
    per_page = min(int(request.args.get('per_page', 25) or 25), 100)
    rows = (q.order_by(Notification.created_at.desc())
            .offset((page - 1) * per_page).limit(per_page).all())
    unread = Notification.query.filter(
        Notification.user_id == current_user.id,
        Notification.is_read.is_(False)).count()
    return response_api_success({
        'total': total, 'unread': unread, 'page': page, 'per_page': per_page,
        'notifications': [_notif_row(n) for n in rows],
    })


@notifications_blueprint.route('/notifications/count', methods=['GET'])
@ac_api_requires()
def notifications_count():
    unread = Notification.query.filter(
        Notification.user_id == current_user.id,
        Notification.is_read.is_(False)).count()
    return response_api_success({'unread': unread})


@notifications_blueprint.route('/notifications/<int:notif_id>/read', methods=['POST'])
@ac_api_requires()
def mark_notification_read(notif_id):
    n = db.session.get(Notification, notif_id)
    # Cross-user reads 404 (existence is data), same as every v2 surface.
    if n is None or n.user_id != current_user.id:
        return response_api_not_found()
    n.is_read = True
    db.session.commit()
    return response_api_success(_notif_row(n))


@notifications_blueprint.route('/notifications/read-all', methods=['POST'])
@ac_api_requires()
def mark_all_notifications_read():
    updated = Notification.query.filter(
        Notification.user_id == current_user.id,
        Notification.is_read.is_(False)).update({'is_read': True})
    db.session.commit()
    return response_api_success({'marked_read': updated})


# --------------------------------------------------------------- preferences

@notifications_blueprint.route('/user/notification-preferences', methods=['GET'])
@ac_api_requires()
def get_notification_preferences():
    settings = ServerSettings.query.first()
    org = (settings.notification_defaults or {}) if settings else {}
    own = {p.event_type: p for p in UserNotificationPreference.query.filter(
        UserNotificationPreference.user_id == current_user.id).all()}
    events = []
    for ev, label in EVENT_CATALOG.items():
        org_ev = org.get(ev) or {}
        row = own.get(ev)
        code_default = _code_default(ev)
        events.append({
            'event_type': ev, 'label': label,
            'org_in_app': bool(org_ev.get('in_app', code_default['in_app'])),
            'org_email': bool(org_ev.get('email', code_default['email'])),
            # None = inherit the org default.
            'in_app': row.in_app if row else None,
            'email': row.email if row else None,
        })
    return response_api_success({
        'events': events,
        'email_channel_enabled': bool(
            settings and settings.email_notifications_enabled),
    })


@notifications_blueprint.route('/user/notification-preferences', methods=['PUT'])
@ac_api_requires()
def put_notification_preferences():
    data = request.get_json(silent=True) or {}
    prefs = data.get('preferences')
    if not isinstance(prefs, list):
        return response_api_error('preferences must be a list')
    for p in prefs:
        ev = (p or {}).get('event_type')
        if ev not in EVENT_CATALOG:
            return response_api_error(f'unknown event_type: {ev}')
    for p in prefs:
        ev = p['event_type']
        in_app = p.get('in_app')
        email = p.get('email')
        if in_app is not None and not isinstance(in_app, bool):
            return response_api_error(f'{ev}: in_app must be boolean or null')
        if email is not None and not isinstance(email, bool):
            return response_api_error(f'{ev}: email must be boolean or null')
        row = UserNotificationPreference.query.filter_by(
            user_id=current_user.id, event_type=ev).first()
        if in_app is None and email is None:
            # Full inherit — drop the override row entirely.
            if row is not None:
                db.session.delete(row)
            continue
        if row is None:
            row = UserNotificationPreference(user_id=current_user.id,
                                             event_type=ev)
            db.session.add(row)
        row.in_app = in_app
        row.email = email
    db.session.commit()
    return get_notification_preferences()


# ------------------------------------------------------------------- follow

def _viewer_can_see(object_type, object_id):
    """Validated against the VIEWER's own access. Returns (ok, case_or_alert)."""
    if object_type == 'case':
        case = db.session.get(Cases, object_id)
        if case is None:
            return False, None
        from app.models.authorization import Permissions
        from app.iris_engine.access_control.utils import ac_current_user_has_permission
        if ac_current_user_has_permission(Permissions.server_administrator):
            return True, case
        return object_id in (ac_get_fast_user_cases_access(current_user.id) or []), case
    if object_type == 'alert':
        alert = db.session.get(Alert, object_id)
        if alert is None:
            return False, None
        return user_has_client_access(current_user.id, alert.alert_customer_id), alert
    return False, None


@notifications_blueprint.route('/follow', methods=['GET'])
@ac_api_requires()
def list_follows():
    """Own follows, enriched with the object's display name + link so the
    home Following card can list them (v3 lists the followed OBJECTS, not
    an activity feed). Objects that were deleted or that the viewer can no
    longer see are skipped — a follow does not outlive a revoked grant."""
    rows = UserFollow.query.filter(
        UserFollow.user_id == current_user.id).order_by(
        UserFollow.created_at.desc()).all()
    out = []
    for r in rows:
        ok, obj = _viewer_can_see(r.object_type, r.object_id)
        if not ok:
            continue
        if r.object_type == 'case':
            name, url = obj.name, f'/case?cid={r.object_id}'
        else:
            name, url = obj.alert_title, f'/alerts?alert_ids={r.object_id}'
        out.append({
            'object_type': r.object_type, 'object_id': r.object_id,
            'object_name': name, 'url': url,
            'created_at': _iso(r.created_at),
        })
    return response_api_success(out)


@notifications_blueprint.route('/follow', methods=['POST'])
@ac_api_requires()
def add_follow():
    data = request.get_json(silent=True) or {}
    object_type = data.get('object_type')
    object_id = data.get('object_id')
    if object_type not in ('case', 'alert') or not isinstance(object_id, int):
        return response_api_error('object_type must be case|alert, object_id an integer')
    ok, _obj = _viewer_can_see(object_type, object_id)
    if not ok:
        return response_api_not_found()
    existing = UserFollow.query.filter_by(
        user_id=current_user.id, object_type=object_type,
        object_id=object_id).first()
    if existing is None:
        db.session.add(UserFollow(user_id=current_user.id,
                                  object_type=object_type,
                                  object_id=object_id))
        db.session.commit()
    return response_api_success({'following': True,
                                 'object_type': object_type,
                                 'object_id': object_id})


@notifications_blueprint.route('/follow', methods=['DELETE'])
@ac_api_requires()
def remove_follow():
    object_type = request.args.get('object_type')
    object_id = request.args.get('object_id', type=int)
    deleted = UserFollow.query.filter_by(
        user_id=current_user.id, object_type=object_type,
        object_id=object_id).delete()
    db.session.commit()
    return response_api_success({'following': False, 'removed': deleted})


@notifications_blueprint.route('/follow/count', methods=['GET'])
@ac_api_requires()
def follow_count():
    """Follower count + own state for one object (the case-header Follow
    button). Same visibility rule as following itself: an object the viewer
    cannot see 404s rather than leaking a count."""
    object_type = request.args.get('object_type')
    object_id = request.args.get('object_id', type=int)
    if object_type not in ('case', 'alert') or object_id is None:
        return response_api_error('object_type must be case|alert, object_id an integer')
    ok, _obj = _viewer_can_see(object_type, object_id)
    if not ok:
        return response_api_not_found()
    count = UserFollow.query.filter_by(object_type=object_type,
                                       object_id=object_id).count()
    following = UserFollow.query.filter_by(
        user_id=current_user.id, object_type=object_type,
        object_id=object_id).first() is not None
    return response_api_success({'count': count, 'following': following})


@notifications_blueprint.route('/follow/feed', methods=['GET'])
@ac_api_requires()
def follow_feed():
    """Merged activity on followed objects, newest first, capped at 50.

    Case side reads user_activity (re-filtered to the viewer's CURRENT case
    access — a follow does not outlive a revoked grant); alert side flattens
    each alert's modification_history dict (epoch-keyed {user, action}).
    """
    follows = UserFollow.query.filter(
        UserFollow.user_id == current_user.id).all()
    case_ids = [f.object_id for f in follows if f.object_type == 'case']
    alert_ids = [f.object_id for f in follows if f.object_type == 'alert']

    items = []

    if case_ids:
        from app.models.authorization import Permissions
        from app.iris_engine.access_control.utils import ac_current_user_has_permission
        if not ac_current_user_has_permission(Permissions.server_administrator):
            accessible = set(ac_get_fast_user_cases_access(current_user.id) or [])
            case_ids = [c for c in case_ids if c in accessible]
        if case_ids:
            names = {c.case_id: c.name for c in Cases.query.filter(
                Cases.case_id.in_(case_ids)).all()}
            rows = (UserActivity.query.filter(
                UserActivity.case_id.in_(case_ids),
                UserActivity.display_in_ui.is_(True))
                .order_by(UserActivity.activity_date.desc()).limit(50).all())
            for r in rows:
                items.append({
                    'object_type': 'case', 'object_id': r.case_id,
                    'object_name': names.get(r.case_id),
                    'text': r.activity_desc,
                    'actor': r.user.name if r.user else None,
                    'at': _iso(r.activity_date),
                    'url': f'/case?cid={r.case_id}',
                })

    for aid in alert_ids[:50]:
        alert = db.session.get(Alert, aid)
        if alert is None:
            continue  # deleted objects are skipped at read time (model rule)
        if not user_has_client_access(current_user.id, alert.alert_customer_id):
            continue
        hist = alert.modification_history or {}
        for key, entry in list(hist.items())[-20:]:
            try:
                at = datetime.utcfromtimestamp(float(key))
            except (TypeError, ValueError):
                continue
            items.append({
                'object_type': 'alert', 'object_id': aid,
                'object_name': alert.alert_title,
                'text': (entry or {}).get('action'),
                'actor': (entry or {}).get('user'),
                'at': _iso(at),
                'url': f'/alerts?alert_ids={aid}',
            })

    items.sort(key=lambda i: i['at'] or '', reverse=True)
    return response_api_success({'items': items[:50]})

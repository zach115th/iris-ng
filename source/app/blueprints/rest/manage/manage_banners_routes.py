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

"""Announcement banners (iris-ng v2, Settings > Banners, v3 parity).

Management CRUD is server_administrator; the /active feed is open to any
authenticated user — it is the display source for the top-of-app strip
rendered by includes/announcement_banners.html in BOTH navs, and exposes
nothing but what the admin chose to announce to everyone."""

from flask import Blueprint
from flask import request
from flask_login import current_user

from app import db
from app.iris_engine.utils.tracker import track_activity
from app.models.authorization import Permissions
from app.models.models import AnnouncementBanner
from app.blueprints.access_controls import ac_api_requires
from app.blueprints.responses import response_error
from app.blueprints.responses import response_success

manage_banners_rest_blueprint = Blueprint('manage_banners_rest', __name__)

_VALID_LEVELS = ('info', 'warning', 'danger')


def _dump(b):
    return {
        'id': b.id,
        'message': b.message,
        'level': b.level,
        'is_active': bool(b.is_active),
        'created_at': b.created_at.isoformat() + 'Z' if b.created_at else None,
        'created_by': b.created_by,
    }


@manage_banners_rest_blueprint.route('/manage/banners/active', methods=['GET'])
@ac_api_requires()
def banners_active():
    rows = AnnouncementBanner.query.filter(
        AnnouncementBanner.is_active.is_(True)
    ).order_by(AnnouncementBanner.created_at.asc()).all()
    return response_success('', data=[_dump(b) for b in rows])


@manage_banners_rest_blueprint.route('/manage/banners/list', methods=['GET'])
@ac_api_requires(Permissions.server_administrator)
def banners_list():
    rows = AnnouncementBanner.query.order_by(AnnouncementBanner.created_at.desc()).all()
    return response_success('', data=[_dump(b) for b in rows])


def _read_banner_payload(existing=None):
    """Validate the add/update body. Returns (message, level, is_active) or
    raises ValueError with a client-safe reason. Level is validated against
    the fixed vocabulary — it selects a CSS class client-side and must never
    be free text."""
    payload = request.get_json(silent=True) or {}
    message = payload.get('message', existing.message if existing else None)
    level = payload.get('level', existing.level if existing else 'info')
    is_active = payload.get('is_active', existing.is_active if existing else True)
    if not isinstance(message, str) or not message.strip():
        raise ValueError('Banner message is required')
    if level not in _VALID_LEVELS:
        raise ValueError(f'Invalid level — one of {", ".join(_VALID_LEVELS)}')
    return message.strip(), level, bool(is_active)


@manage_banners_rest_blueprint.route('/manage/banners/add', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def banners_add():
    try:
        message, level, is_active = _read_banner_payload()
    except ValueError as e:
        return response_error(str(e))

    banner = AnnouncementBanner(message=message, level=level, is_active=is_active,
                                created_by=current_user.id)
    db.session.add(banner)
    db.session.commit()
    track_activity(f'Announcement banner #{banner.id} created', ctx_less=True)
    return response_success('Banner created', data=_dump(banner))


@manage_banners_rest_blueprint.route('/manage/banners/update/<int:banner_id>', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def banners_update(banner_id):
    banner = db.session.get(AnnouncementBanner, banner_id)
    if banner is None:
        return response_error('Banner not found')
    try:
        banner.message, banner.level, banner.is_active = _read_banner_payload(existing=banner)
    except ValueError as e:
        return response_error(str(e))
    db.session.commit()
    track_activity(f'Announcement banner #{banner.id} updated', ctx_less=True)
    return response_success('Banner updated', data=_dump(banner))


@manage_banners_rest_blueprint.route('/manage/banners/delete/<int:banner_id>', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def banners_delete(banner_id):
    banner = db.session.get(AnnouncementBanner, banner_id)
    if banner is None:
        return response_error('Banner not found')
    db.session.delete(banner)
    db.session.commit()
    track_activity(f'Announcement banner #{banner_id} deleted', ctx_less=True)
    return response_success('Banner deleted')

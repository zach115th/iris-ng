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

"""War-room categories (iris-ng, 2026-11-10; maintainer: one shared list, anyone adds; a room's leads file it).

Any signed-in user lists, creates and renames categories. Deleting one is for its creator or a server
administrator, and only un-files its rooms (the FK sets NULL): no room is touched. Guests never reach these
(the REST layer uses the non-room decorator). Filing a room is set_room_category, checked as lead at the REST layer.
"""

import unicodedata

from sqlalchemy import func

from app import db
from app.business.errors import BusinessProcessingError
from app.models import war_room_datastore_vocab as dv
from app.models.models import WarRoomCategory


class CategoryError(BusinessProcessingError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def clean_name(raw):
    """A category name: trimmed, inner whitespace collapsed, no control characters, 1-64 characters."""
    if not isinstance(raw, str):
        raise CategoryError('A category needs a name')
    name = ' '.join(''.join(ch for ch in raw if not unicodedata.category(ch).startswith('C')).split())
    if not name:
        raise CategoryError('A category needs a name')
    if len(name) > dv.CATEGORY_NAME_MAX:
        raise CategoryError('A category name can be %d characters at most' % dv.CATEGORY_NAME_MAX)
    return name


def row(category):
    return {'id': category.id, 'name': category.name, 'created_by': category.created_by,
            'created_by_name': category.creator.name if category.creator else None}


def list_categories():
    return WarRoomCategory.query.order_by(func.lower(WarRoomCategory.name), WarRoomCategory.id).all()


def get_category(category_id):
    if isinstance(category_id, bool):
        raise CategoryError('Category not found', status=404)
    try:
        cid = int(category_id)
    except (TypeError, ValueError):
        raise CategoryError('Category not found', status=404)
    category = db.session.get(WarRoomCategory, cid)
    if category is None:
        raise CategoryError('Category not found', status=404)
    return category


def _clash(name, exclude_id=None):
    q = WarRoomCategory.query.filter(func.lower(WarRoomCategory.name) == name.lower())
    if exclude_id is not None:
        q = q.filter(WarRoomCategory.id != exclude_id)
    return q.first() is not None


def create_category(raw_name, user_id):
    name = clean_name(raw_name)
    if WarRoomCategory.query.count() >= dv.CATEGORIES_MAX:
        raise CategoryError('There can be %d categories at most' % dv.CATEGORIES_MAX)
    if _clash(name):
        raise CategoryError('A category named "%s" already exists' % name, status=409)
    category = WarRoomCategory(name=name, created_by=user_id)
    db.session.add(category)
    db.session.commit()
    return category


def rename_category(category_id, raw_name):
    category = get_category(category_id)
    name = clean_name(raw_name)
    if _clash(name, exclude_id=category.id):
        raise CategoryError('A category named "%s" already exists' % name, status=409)
    category.name = name
    db.session.commit()
    return category


def delete_category(category_id, user_id, is_admin):
    """Its creator or a server administrator; the rooms filed under it become uncategorised (ON DELETE SET NULL,
    done here through the ORM so the room activity log records each room)."""
    category = get_category(category_id)
    if not is_admin and category.created_by != user_id:
        raise CategoryError('Only the person who created this category, or an administrator, can delete it',
                            status=403)
    from app.models.models import WarRoom
    for room in WarRoom.query.filter(WarRoom.category_id == category.id).all():
        room.category_id = None
    db.session.flush()
    db.session.delete(category)
    db.session.commit()


def set_room_category(room, category_id):
    """File the room under a category, or un-file it (None)."""
    if category_id is None or category_id == '':
        room.category_id = None
    else:
        room.category_id = get_category(category_id).id
    db.session.commit()
    return room

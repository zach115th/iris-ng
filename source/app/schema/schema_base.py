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

"""What every IRIS schema shares, kept as it behaved under marshmallow 3 and flask-marshmallow 1.4.

iris-ng (marshmallow 4, flask-marshmallow 1.5, marshmallow-sqlalchemy 1.6):

- ``IrisAutoSchema`` keeps flask-marshmallow's placeholder session. Up to flask-marshmallow 1.4.0, ``init_app`` handed
  the database session to the wrong options class, so every auto schema kept ``DummySession``; 1.5.0 fixed that. With
  the real session, a ``load_instance`` schema given a body that names an existing row's primary key loads THAT row:
  a create carrying ``ioc_id`` would overwrite an IOC of another case. With the placeholder such a load fails before
  any row is read, as it always has. Code that updates a row passes it as ``instance=``.
- ``IrisBoolean`` dumps like marshmallow 3: every value becomes true or false. marshmallow 4 passes a non-boolean
  value through, so an attribute holding 1 would answer 1.
- ``IrisDateTime`` dumps a ``date`` as its ISO date, like marshmallow 3. marshmallow 4 formats with
  ``datetime.isoformat``, which raises TypeError on a date.

Every field marshmallow-sqlalchemy generates for a bool or a datetime column takes these classes through
``TYPE_MAPPING``; a field declared by hand names them.
"""

import datetime

from flask_marshmallow.sqla import DummySession
from flask_marshmallow.sqla import SQLAlchemyAutoSchemaOpts
from marshmallow import fields

from app import ma


def _isoformat(value):
    """marshmallow 3's ``utils.isoformat``: the value's own ``isoformat()``, so a date gives YYYY-MM-DD."""
    return value.isoformat()


class IrisBoolean(fields.Boolean):
    """A Boolean field that dumps any value as true or false (marshmallow 3's serialization)."""

    def _serialize(self, value, attr, obj, **kwargs):
        if value is None:
            return None
        try:
            if value in self.truthy:
                return True
            if value in self.falsy:
                return False
        except TypeError:
            pass
        return bool(value)


class IrisDateTime(fields.DateTime):
    """A DateTime field whose ISO output is the value's own ``isoformat()`` (marshmallow 3's serialization)."""

    SERIALIZATION_FUNCS = {**fields.DateTime.SERIALIZATION_FUNCS, 'iso': _isoformat, 'iso8601': _isoformat}


class IrisAutoSchemaOpts(SQLAlchemyAutoSchemaOpts):
    """flask-marshmallow's auto-schema options with the placeholder session it gave IRIS up to 1.4.0."""

    session = DummySession()


class IrisAutoSchema(ma.SQLAlchemyAutoSchema):
    """The base of every IRIS auto schema: the placeholder session and the marshmallow 3 dump of bools and datetimes."""

    OPTIONS_CLASS = IrisAutoSchemaOpts
    TYPE_MAPPING = {**ma.SQLAlchemyAutoSchema.TYPE_MAPPING, bool: IrisBoolean, datetime.datetime: IrisDateTime}

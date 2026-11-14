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
"""Keeps the /graphql schema the same across graphene-sqlalchemy releases.

graphene-sqlalchemy 3.0.0rc2 registers its own ``DateTimeFilter`` (eq, in,
nEq, notIn plus gt, gte, lt, lte) for every DateTime column. rc1 had none and
built ``DefaultDateTimeScalarFilter`` (eq, in, nEq, notIn) the first time a
DateTime column needed one - the type the ``filter`` argument of ``cases`` and
``iocs`` has always named. IRIS registers that type again, built the way rc1
built it, so introspection and any client query naming it do not change.

``register_scalar_filters()`` must run before an ``SQLAlchemyObjectType`` is
defined: the object types look their column filters up when they are built.
"""

import graphene
from graphene_sqlalchemy.filters import FieldFilter
from graphene_sqlalchemy.registry import get_global_registry

DefaultDateTimeScalarFilter = FieldFilter.create_type(
    'DefaultDateTimeScalarFilter', graphene_type=graphene.DateTime
)


def register_scalar_filters():
    get_global_registry().register_filter_for_scalar_type(graphene.DateTime, DefaultDateTimeScalarFilter)

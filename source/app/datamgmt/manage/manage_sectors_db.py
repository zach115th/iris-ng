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

"""iris-ng: data helpers for the admin-editable sector catalog.

The catalog is the single source for the sector pickers
(modal_add_case / modal_add_customer), the soft-enforcement check in
business/cases.py and the metrics recognition in
business/dashboard_metrics.py. Recognition helpers read ALL rows
(enabled or not) so disabling a sector never orphans historical tags;
the pickers read enabled rows only.
"""
from typing import List

from app.models.models import SectorCatalog


def get_sectors_list() -> List[dict]:
    """Every sector row, picker order (name), as plain dicts."""
    rows = SectorCatalog.query.order_by(SectorCatalog.name).all()
    return [{
        'id': r.id, 'slug': r.slug, 'name': r.name, 'tag': r.tag,
        'enabled': bool(r.enabled),
    } for r in rows]


def get_enabled_sectors() -> List[SectorCatalog]:
    """Rows the pickers render, display order."""
    return SectorCatalog.query.filter(
        SectorCatalog.enabled.is_(True)
    ).order_by(SectorCatalog.name).all()


def get_sector_by_id(sector_id: int) -> SectorCatalog:
    return SectorCatalog.query.get(sector_id)


def get_sector_by_slug(slug: str) -> SectorCatalog:
    return SectorCatalog.query.filter(SectorCatalog.slug == slug).first()


def get_sector_tag_prefixes() -> tuple:
    """Recognition prefixes derived from ALL catalog rows: everything up to
    and including the '=' of each row's machine-tag. Callers union this with
    their legacy constants so recognition survives an empty catalog."""
    out = set()
    for (tag,) in SectorCatalog.query.with_entities(SectorCatalog.tag).all():
        head, sep, _ = (tag or '').partition('=')
        if sep:
            out.add(head + '=')
    return tuple(sorted(out))


def get_sector_tag_by_slug(slug: str) -> str:
    row = get_sector_by_slug(slug)
    return row.tag if row else None

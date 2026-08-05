#
#  IRIS Source Code
#

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app import app
from app import db
from app.models.models import IocType


RESOURCE_PATH = Path(__file__).parent / "resources" / "misp.attribute_types.json"


def load_misp_attribute_type_catalog() -> dict[str, Any]:
    with open(RESOURCE_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def get_known_misp_attribute_types() -> set[str]:
    catalog = load_misp_attribute_type_catalog()
    return set(catalog.get("types", []))


def get_local_ioc_type_overrides() -> dict[str, str | None]:
    catalog = load_misp_attribute_type_catalog()
    return dict(catalog.get("local_type_overrides", {}))


def resolve_ioc_type_taxonomy(
    type_name: str | None,
    type_taxonomy: str | None,
    *,
    known_misp_types: set[str] | None = None,
    local_overrides: dict[str, str | None] | None = None
) -> str | None:
    if type_taxonomy and type_taxonomy.strip():
        return type_taxonomy.strip()

    if not type_name:
        return None

    normalized_type_name = type_name.strip()
    if not normalized_type_name:
        return None

    if local_overrides is None:
        local_overrides = get_local_ioc_type_overrides()
    if normalized_type_name in local_overrides:
        return local_overrides[normalized_type_name]

    if known_misp_types is None:
        known_misp_types = get_known_misp_attribute_types()
    if normalized_type_name in known_misp_types:
        return normalized_type_name

    return None


def backfill_ioc_type_taxonomy(*, overwrite: bool = False) -> dict[str, Any]:
    known_misp_types = get_known_misp_attribute_types()
    local_overrides = get_local_ioc_type_overrides()

    updated: list[dict[str, str]] = []
    unresolved: list[str] = []
    unchanged = 0

    ioc_types = IocType.query.order_by(IocType.type_name.asc()).all()
    for ioc_type in ioc_types:
        current_taxonomy = (ioc_type.type_taxonomy or "").strip()
        if current_taxonomy and not overwrite:
            unchanged += 1
            continue

        resolved_taxonomy = resolve_ioc_type_taxonomy(
            ioc_type.type_name,
            None if overwrite else current_taxonomy,
            known_misp_types=known_misp_types,
            local_overrides=local_overrides
        )

        if resolved_taxonomy is None:
            unresolved.append(ioc_type.type_name)
            if overwrite and ioc_type.type_taxonomy is not None:
                ioc_type.type_taxonomy = None
            continue

        if current_taxonomy == resolved_taxonomy:
            unchanged += 1
            continue

        ioc_type.type_taxonomy = resolved_taxonomy
        updated.append({
            "type_name": ioc_type.type_name,
            "type_taxonomy": resolved_taxonomy
        })

    if updated or (overwrite and unresolved):
        db.session.commit()

    summary = {
        "catalog_type_count": len(known_misp_types),
        "ioc_type_count": len(ioc_types),
        "updated_count": len(updated),
        "unchanged_count": unchanged,
        "unresolved_count": len(unresolved),
        "unresolved_types": unresolved
    }

    app.logger.info(
        "IOC type taxonomy backfill completed: "
        f"{summary['updated_count']} updated, "
        f"{summary['unchanged_count']} unchanged, "
        f"{summary['unresolved_count']} unresolved"
    )
    if unresolved:
        app.logger.warning(
            "IOC types without a direct MISP attribute-type mapping: "
            + ", ".join(unresolved)
        )

    return summary

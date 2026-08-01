"""Promote-time asset materialization for working-timeline events.

Called from the working-timeline `promote` endpoint — NEVER at import
time. The user's design intent is explicit: tool-ingested events stay
inert until an analyst signs off, at which point we promote them to a
real `cases_event` AND lazily create any assets they reference (host +
users) that don't exist yet in the case.

Today this only handles Hayabusa-shaped subject info from
`event_raw['subjects']`. Future ingest sources (KAPE / EZTools /
Cybertriage) populate the same `subjects` shape and reuse this resolver
unchanged.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func

from app import db
from app.datamgmt.case.case_assets_db import get_asset_by_name
from app.datamgmt.case.case_assets_db import get_unspecified_analysis_status_id
from app.models.cases import CaseWorkingEvent
from app.models.models import AssetsType
from app.models.models import CaseAssets
from app.models.models import CompromiseStatus

# Default asset types — names match seeded rows in the assets_type table.
ASSET_TYPE_HOST_DEFAULT = 'Windows - Computer'
ASSET_TYPE_USER_LOCAL = 'Windows Account - Local'
ASSET_TYPE_USER_AD = 'Windows Account - AD'
ASSET_TYPE_USER_GENERIC = 'Account'


def _get_asset_type_id(asset_type_name: str) -> int | None:
    """Case-insensitive lookup against assets_type."""
    row = (
        AssetsType.query
        .with_entities(AssetsType.asset_id)
        .filter(func.lower(AssetsType.asset_name) == asset_type_name.lower())
        .first()
    )
    return row.asset_id if row else None


def _pick_host_asset_type(host: str) -> str:
    """Heuristic from hostname patterns. Pure-substring matches kept
    intentionally broad — analyst can edit the type after promote.

    Patterns shipped today (from the user's lab CSV vocabulary):
      - 'dc' or 'domain-controller' → Windows - DC
      - leading 'srv' / 'fs' / 'sql' / 'exchange' / 'iis' → Windows - Server
      - everything else → Windows - Computer (workstation default)"""
    name = (host or '').lower()
    short = name.split('.')[0]
    if 'dc' in short or 'domain-controller' in name:
        return 'Windows - DC'
    if any(short.startswith(p) for p in ('srv', 'fs', 'sql', 'exchange', 'iis', 'web')):
        return 'Windows - Server'
    return ASSET_TYPE_HOST_DEFAULT


def _ensure_asset(
    *,
    case_id: int,
    asset_name: str,
    asset_type_name: str,
    description: str,
    user_id: int,
    domain: str | None = None,
) -> tuple[CaseAssets, bool]:
    """Find-or-create a CaseAsset by name within the case.

    Returns ``(asset, created)`` so callers can report which assets
    were freshly minted vs. already in the case. We do NOT update an
    existing row's type/description — the analyst owns that field
    after first import."""
    existing = get_asset_by_name(asset_name, case_id)
    if existing is not None:
        return existing, False

    type_id = _get_asset_type_id(asset_type_name)
    if type_id is None:
        # Fall back to the generic 'Account' type if a Windows-specific
        # variant isn't in the catalog. As a last resort, asset_id=1
        # (Account) which is seeded on every fresh install.
        type_id = _get_asset_type_id(ASSET_TYPE_USER_GENERIC) or 1

    # Default compromise status = to_be_determined (0x0): "not yet triaged".
    # Procedurally distinct from unknown (0x3) which means "analyst tried,
    # couldn't decide". Don't auto-flag as compromised — analyst judgement.
    asset = CaseAssets()
    asset.asset_name = asset_name
    asset.asset_type_id = type_id
    asset.case_id = case_id
    asset.user_id = user_id
    asset.asset_description = description
    asset.asset_domain = domain or ''
    asset.asset_compromise_status_id = CompromiseStatus.to_be_determined.value
    asset.analysis_status_id = get_unspecified_analysis_status_id()
    asset.date_added = datetime.utcnow()
    asset.date_update = datetime.utcnow()
    db.session.add(asset)
    db.session.flush()  # populate asset_id for the FK link below
    return asset, True


def _split_fqdn_domain(host: str) -> str | None:
    """Extract the domain suffix from a fully-qualified hostname.

    `WIN10-client01.offsec.lan` → `offsec.lan`. Bare hostnames return None.
    Only triggers when the name has at least two dot-separated parts AND
    the first part isn't an IP-like number (avoid mangling '10.0.0.1').
    """
    if not host or '.' not in host:
        return None
    parts = host.strip().split('.')
    if len(parts) < 2:
        return None
    first = parts[0]
    if first.isdigit():
        return None  # IPv4 first octet — not an FQDN
    return '.'.join(parts[1:])


def ensure_assets_for_working_event(
    working: CaseWorkingEvent,
    *,
    user_id: int,
) -> dict[str, Any]:
    """Materialize assets implied by a working event's `event_raw.subjects`.

    Behavior per the user's design rule (2026-05-05):
      * Only called from the promote endpoint — NEVER at import time.
      * Idempotent: re-calling on an already-promoted event returns the
        same asset ids without duplicates.
      * Host always materializes when present.
      * Subject user materializes when present (DOMAIN+name combined
        into a single asset name like ``OFFSEC\\admmig`` so AD vs Local
        accounts don't collide).
      * Target user materializes when present and ≠ subject user.

    Returns:
        ``{
            'asset_ids':  [int, …],   # all assets that should be linked
            'created':    [{'id', 'name', 'type'}, …],  # newly minted only
            'reused':     [{'id', 'name', 'type'}, …],  # already in the case
        }``
    The caller wires `asset_ids` into the cases_event ↔ assets join
    table via ``update_event_assets``.
    """
    raw = working.event_raw or {}
    subjects: dict[str, Any] = raw.get('subjects') or {}

    asset_ids: list[int] = []
    created: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []

    seen_names: set[str] = set()

    def _materialize(name: str, type_name: str, desc: str, domain: str | None = None) -> None:
        if not name or name in seen_names:
            return
        seen_names.add(name)
        asset, was_created = _ensure_asset(
            case_id=working.case_id,
            asset_name=name,
            asset_type_name=type_name,
            description=desc,
            user_id=user_id,
            domain=domain,
        )
        asset_ids.append(asset.asset_id)
        info = {
            'id': asset.asset_id,
            'name': asset.asset_name,
            'type': type_name,
        }
        (created if was_created else reused).append(info)

    # 1) Host
    host = subjects.get('host') or working.event_source_host
    if host:
        host_type = _pick_host_asset_type(host)
        _materialize(
            host,
            host_type,
            f'Auto-created from {working.source} working event ({working.external_id or working.id})',
            domain=_split_fqdn_domain(host),
        )

    # 2) Subject user — combine DOMAIN+user so AD principals don't
    #    collide with same-named local accounts.
    su = subjects.get('subject_user')
    sd = subjects.get('subject_domain')
    if su:
        full = f'{sd}\\{su}' if sd else su
        utype = ASSET_TYPE_USER_AD if sd else ASSET_TYPE_USER_LOCAL
        _materialize(
            full,
            utype,
            f'Auto-created from {working.source} working event ({working.external_id or working.id})',
        )

    # 3) Target user (lateral movement signal — only when distinct).
    tu = subjects.get('target_user')
    td = subjects.get('target_domain')
    if tu:
        target_full = f'{td}\\{tu}' if td else tu
        if target_full != (f'{sd}\\{su}' if (sd and su) else su):
            ttype = ASSET_TYPE_USER_AD if td else ASSET_TYPE_USER_LOCAL
            _materialize(
                target_full,
                ttype,
                f'Target principal from {working.source} working event ({working.external_id or working.id})',
            )

    return {
        'asset_ids': asset_ids,
        'created': created,
        'reused': reused,
    }

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

"""Customer-asset registry business layer (iris-ng v2, Phase 4).

Curation edits + the scan celery task. The sync/sightings/scan PRIMITIVES
live in datamgmt/manage/customer_assets_db.py — datamgmt code (the
create_asset funnel, the escalation/merge loops) calls them, and datamgmt
must never import business (three-layer rule)."""

import logging
from datetime import datetime

from app import app as flask_app
from app import celery
from app import db
from app.datamgmt.manage.customer_assets_db import CRITICALITY_VALUES
from app.datamgmt.manage.customer_assets_db import scan_registry
from app.datamgmt.manage.customer_assets_db import sightings_counts  # noqa: F401 (re-export)
from app.datamgmt.manage.customer_assets_db import sighting_details  # noqa: F401 (re-export)
from app.models.models import CompromiseStatus
from app.models.models import CustomerAsset
from app.models.models import CustomerAssetChange

log = logging.getLogger(__name__)


def update_curation(asset: CustomerAsset, data: dict, user_id: int):
    """Apply analyst edits to curated fields, writing one change row per
    actual change. Raises ValueError on bad values (endpoint maps to 400).
    Uses the ORM session (interactive path — commit is the caller's)."""
    changes = []

    def _stage(field, new_value):
        old_value = getattr(asset, field)
        if old_value == new_value:
            return
        setattr(asset, field, new_value)
        changes.append(CustomerAssetChange(
            customer_asset_id=asset.id, field=field,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None,
            changed_by=user_id))

    if 'criticality' in data:
        v = data['criticality'] or None
        if v is not None and v not in CRITICALITY_VALUES:
            raise ValueError(f'criticality must be one of {", ".join(CRITICALITY_VALUES)}')
        _stage('criticality', v)
    if 'environment' in data:
        _stage('environment', (data['environment'] or '').strip() or None)
    if 'owner' in data:
        _stage('owner', (data['owner'] or '').strip() or None)
    if 'notes' in data:
        _stage('notes', (data['notes'] or '').strip() or None)
    if 'compromise_status' in data:
        v = data['compromise_status']
        if v is not None and not CompromiseStatus.has_value(v):
            raise ValueError('compromise_status must be 0-3 or null')
        _stage('compromise_status', v)
        if v == CompromiseStatus.compromised.value and asset.compromise_since is None:
            asset.compromise_since = datetime.utcnow()
        if v in (None, CompromiseStatus.not_compromised.value):
            asset.compromise_since = None

    db.session.add_all(changes)
    return changes


@celery.task(bind=True)
def task_scan_registry(self):
    """Celery entry point for POST /scan (default queue)."""
    with flask_app.app_context():
        try:
            summary = scan_registry()
            log.info('customer-asset scan: %s', summary)
            return summary
        except Exception as e:
            log.exception('customer-asset scan failed')
            return {'error': str(e)[:500]}

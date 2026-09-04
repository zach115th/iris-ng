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

"""Customer-asset registry REST surface (iris-ng v2, Phase 4).

ACL model (per plan — the evidence-inventory open-to-all precedent was
REJECTED, registry rows are case-derived data): read + curate carry no
specific permission bit but are scoped by user_has_client_access — a
server_administrator session sees every customer, everyone else exactly
their UserClient rows, and an empty list means NOTHING. Delete, scan and
CSV import are server_administrator. Cross-tenant reads 404 (existence is
data).

CSV import is multipart with csrf_token as a FORM FIELD (multipart CSRF
project rule). Customer and asset type resolve by NAME at import time
(lookup ids vary per deployment — fork rule); per-row errors are reported,
good rows still land.
"""

import csv
import io
from datetime import datetime

from flask import Blueprint
from flask import Response
from flask import request
from flask_login import current_user
from sqlalchemy import or_
from sqlalchemy import text as sa_text

from app import db
from app.blueprints.access_controls import ac_api_requires
from app.blueprints.rest.endpoints import response
from app.blueprints.rest.endpoints import response_api_deleted
from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
from app.business.customer_assets import task_scan_registry
from app.business.customer_assets import update_curation
from app.datamgmt.manage.customer_assets_db import latest_observation
from app.datamgmt.manage.customer_assets_db import sighting_details
from app.datamgmt.manage.customer_assets_db import sightings_counts
from app.datamgmt.manage.customer_assets_db import sync_asset
from app.datamgmt.manage.customer_assets_db import timeline_event_count
from app.datamgmt.manage.customer_assets_db import timeline_events_for
from app.datamgmt.manage.manage_access_control_db import get_user_clients_id
from app.datamgmt.manage.manage_access_control_db import user_has_client_access
from app.iris_engine.access_control.utils import ac_current_user_has_permission
from app.iris_engine.utils.tracker import track_activity
from app.models.models import AssetsType
from app.models.models import Client
from app.models.models import CompromiseStatus
from app.models.models import CustomerAsset
from app.models.models import CustomerAssetChange
from app.models.authorization import Permissions

customer_assets_blueprint = Blueprint('customer_assets_rest_v2', __name__)

_CSV_COLUMNS = ['customer', 'asset_name', 'asset_type', 'criticality',
                'environment', 'owner', 'compromise_status', 'notes',
                'first_seen', 'last_seen']


def _iso(dt):
    if dt is None:
        return None
    return dt.isoformat() + ('Z' if dt.tzinfo is None else '')


def _compromise_name(value):
    if value is None:
        return None
    try:
        return CompromiseStatus(value).name
    except ValueError:
        return str(value)


def _row(asset: CustomerAsset, counts: dict = None) -> dict:
    d = {
        'id': asset.id,
        'customer_id': asset.customer_id,
        'customer_name': asset.customer.name if asset.customer else None,
        'asset_name': asset.asset_name,
        'asset_type_id': asset.asset_type_id,
        'asset_type': asset.asset_type.asset_name if asset.asset_type else None,
        'criticality': asset.criticality,
        'environment': asset.environment,
        'owner': asset.owner,
        'compromise_status': asset.compromise_status,
        'compromise_status_name': _compromise_name(asset.compromise_status),
        'compromise_since': _iso(asset.compromise_since),
        'notes': asset.notes,
        'first_seen': _iso(asset.first_seen),
        'last_seen': _iso(asset.last_seen),
        'created_by': asset.creator.name if asset.creator else None,
    }
    if counts is not None:
        d['sightings'] = counts.get(asset.id, {'cases': 0, 'alerts': 0})
    return d


def _scoped_query():
    """Registry query scoped exactly like user_has_client_access: admin
    sees all; others their UserClient rows; empty means NOTHING."""
    if ac_current_user_has_permission(Permissions.server_administrator):
        return CustomerAsset.query
    client_ids = get_user_clients_id(current_user.id)
    if not client_ids:
        return None
    return CustomerAsset.query.filter(CustomerAsset.customer_id.in_(client_ids))


def _get_checked(asset_id):
    asset = db.session.get(CustomerAsset, asset_id)
    if asset is None:
        return None, response_api_not_found()
    if not user_has_client_access(current_user.id, asset.customer_id):
        return None, response_api_not_found()
    return asset, None


# "Seen" = the registry row has at least one live sighting. Reuses the exact
# join predicates of sightings_counts (name_norm + type + customer); alert
# sightings route through case_assets rows too (alert assets are case_assets
# with a NULL case_id, linked via alert_assets_association), so the case-side
# EXISTS alone would miss alert-only assets — both are needed.
_SEEN_PREDICATE = (
    "(EXISTS (SELECT 1 FROM case_assets ca JOIN cases cs"
    " ON cs.case_id = ca.case_id AND cs.client_id = customer_asset.customer_id"
    " WHERE lower(trim(ca.asset_name)) = customer_asset.asset_name_norm"
    " AND ca.asset_type_id = customer_asset.asset_type_id)"
    " OR EXISTS (SELECT 1 FROM case_assets ca"
    " JOIN alert_assets_association aaa ON aaa.asset_id = ca.asset_id"
    " JOIN alerts a ON a.alert_id = aaa.alert_id"
    " AND a.alert_customer_id = customer_asset.customer_id"
    " WHERE lower(trim(ca.asset_name)) = customer_asset.asset_name_norm"
    " AND ca.asset_type_id = customer_asset.asset_type_id))"
)


def _apply_filters(query):
    if request.args.get('customer_id'):
        query = query.filter(CustomerAsset.customer_id == int(request.args['customer_id']))
    if request.args.get('type_id'):
        query = query.filter(CustomerAsset.asset_type_id == int(request.args['type_id']))
    if request.args.get('criticality'):
        query = query.filter(CustomerAsset.criticality == request.args['criticality'])
    compromised = request.args.get('compromised')
    if compromised == 'true':
        query = query.filter(
            CustomerAsset.compromise_status == CompromiseStatus.compromised.value)
    elif compromised == 'false':
        # NULL counts as not-compromised here (IS DISTINCT FROM, not !=).
        query = query.filter(CustomerAsset.compromise_status.is_distinct_from(
            CompromiseStatus.compromised.value))
    if request.args.get('environment'):
        query = query.filter(CustomerAsset.environment.ilike(
            f"%{request.args['environment'].strip()}%"))
    if request.args.get('owner'):
        query = query.filter(CustomerAsset.owner.ilike(
            f"%{request.args['owner'].strip()}%"))
    seen = request.args.get('seen')
    if seen == 'yes':
        query = query.filter(sa_text(_SEEN_PREDICATE))
    elif seen == 'no':
        query = query.filter(sa_text(f"NOT {_SEEN_PREDICATE}"))
    if request.args.get('q'):
        q = request.args['q'].strip()
        query = query.filter(or_(
            CustomerAsset.asset_name_norm.like(f"%{q.lower()}%"),
            CustomerAsset.owner.ilike(f"%{q}%"),
            CustomerAsset.notes.ilike(f"%{q}%"),
        ))
    return query


@customer_assets_blueprint.route('/customer-assets', methods=['GET'])
@ac_api_requires()
def list_customer_assets():
    query = _scoped_query()
    if query is None:
        return response_api_success({'total': 0, 'assets': []})
    query = _apply_filters(query)

    total = query.count()
    page = max(int(request.args.get('page', 1) or 1), 1)
    per_page = min(int(request.args.get('per_page', 50) or 50), 200)
    rows = (query.order_by(CustomerAsset.last_seen.desc())
            .offset((page - 1) * per_page).limit(per_page).all())
    counts = sightings_counts([r.id for r in rows])
    return response_api_success({
        'total': total, 'page': page, 'per_page': per_page,
        'assets': [_row(r, counts) for r in rows],
    })


@customer_assets_blueprint.route('/customer-assets/<int:asset_id>', methods=['GET'])
@ac_api_requires()
def get_customer_asset(asset_id):
    asset, err = _get_checked(asset_id)
    if err is not None:
        return err
    d = _row(asset, sightings_counts([asset.id]))
    d['sighting_details'] = sighting_details(asset, current_user.id)
    # v3-parity detail enrichment, all live-derived (never stored):
    d['latest_observation'] = latest_observation(asset)
    d['timeline_events'] = timeline_event_count(asset)
    # Origin: a NULL created_by means the row came from sync/scan.
    d['origin'] = 'manual' if asset.created_by else 'observed'
    return response_api_success(d)


@customer_assets_blueprint.route('/customer-assets/<int:asset_id>/timeline', methods=['GET'])
@ac_api_requires()
def get_customer_asset_timeline(asset_id):
    asset, err = _get_checked(asset_id)
    if err is not None:
        return err
    return response_api_success(timeline_events_for(asset, current_user.id))


@customer_assets_blueprint.route('/customer-assets/<int:asset_id>', methods=['PUT'])
@ac_api_requires()
def update_customer_asset(asset_id):
    asset, err = _get_checked(asset_id)
    if err is not None:
        return err
    try:
        update_curation(asset, request.get_json() or {}, current_user.id)
    except ValueError as e:
        db.session.rollback()
        return response_api_error(str(e))
    db.session.commit()
    track_activity(f"updated customer asset '{asset.asset_name}'", ctx_less=True)
    return response_api_success(_row(asset, sightings_counts([asset.id])))


@customer_assets_blueprint.route('/customer-assets/<int:asset_id>/changes', methods=['GET'])
@ac_api_requires()
def get_customer_asset_changes(asset_id):
    asset, err = _get_checked(asset_id)
    if err is not None:
        return err
    rows = (CustomerAssetChange.query
            .filter(CustomerAssetChange.customer_asset_id == asset.id)
            .order_by(CustomerAssetChange.changed_at.desc())
            .limit(200).all())
    return response_api_success([{
        'field': r.field, 'old_value': r.old_value, 'new_value': r.new_value,
        'changed_by': r.changed_by_user.name if r.changed_by_user else 'system',
        'changed_at': _iso(r.changed_at),
    } for r in rows])


@customer_assets_blueprint.route('/customer-assets/<int:asset_id>/sightings', methods=['GET'])
@ac_api_requires()
def get_customer_asset_sightings(asset_id):
    asset, err = _get_checked(asset_id)
    if err is not None:
        return err
    return response_api_success(sighting_details(asset, current_user.id))


@customer_assets_blueprint.route('/customer-assets/<int:asset_id>', methods=['DELETE'])
@ac_api_requires(Permissions.server_administrator)
def delete_customer_asset(asset_id):
    asset = db.session.get(CustomerAsset, asset_id)
    if asset is None:
        return response_api_not_found()
    name = asset.asset_name
    db.session.delete(asset)   # change rows CASCADE
    db.session.commit()
    track_activity(f"deleted customer asset '{name}'", ctx_less=True)
    return response_api_deleted()


@customer_assets_blueprint.route('/customer-assets/scan', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def scan_customer_assets():
    task = task_scan_registry.delay()
    track_activity('started customer-asset registry scan', ctx_less=True)
    return response(202, data={'task_id': task.id, 'state': 'queued'})


# ------------------------------------------------------------------ CSV

@customer_assets_blueprint.route('/customer-assets/export', methods=['GET'])
@ac_api_requires()
def export_customer_assets():
    query = _scoped_query()
    if query is None:
        rows = []
    else:
        rows = _apply_filters(query).order_by(
            CustomerAsset.customer_id.asc(),
            CustomerAsset.asset_name_norm.asc()).all()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(_CSV_COLUMNS)
    for r in rows:
        writer.writerow([
            r.customer.name if r.customer else '',
            r.asset_name,
            r.asset_type.asset_name if r.asset_type else '',
            r.criticality or '',
            r.environment or '',
            r.owner or '',
            _compromise_name(r.compromise_status) or '',
            r.notes or '',
            _iso(r.first_seen) or '',
            _iso(r.last_seen) or '',
        ])
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition':
                             'attachment; filename=customer-assets.csv'})


@customer_assets_blueprint.route('/customer-assets/import', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def import_customer_assets():
    """Multipart CSV. Creates/touches the registry row via sync_asset and
    applies the curation columns. Per-row error report; good rows land."""
    file = request.files.get('file')
    if file is None:
        return response_api_error('No file provided (multipart field: file)')
    try:
        text = file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        return response_api_error('File is not UTF-8 text')

    reader = csv.DictReader(io.StringIO(text))
    customers = {c.name.strip().lower(): c.client_id for c in Client.query.all()}
    types = {t.asset_name.strip().lower(): t.asset_id for t in AssetsType.query.all()}
    status_by_name = {s.name: s.value for s in CompromiseStatus}

    imported = 0
    errors = []
    for i, row in enumerate(reader, start=2):   # 1 is the header line
        cust_name = (row.get('customer') or '').strip()
        name = (row.get('asset_name') or '').strip()
        type_name = (row.get('asset_type') or '').strip()
        cust_id = customers.get(cust_name.lower())
        type_id = types.get(type_name.lower())
        if not name:
            errors.append(f'line {i}: asset_name is required')
            continue
        if cust_id is None:
            errors.append(f'line {i}: unknown customer {cust_name!r}')
            continue
        if type_id is None:
            errors.append(f'line {i}: unknown asset type {type_name!r}')
            continue

        sync_asset(cust_id, name, type_id)
        asset = (CustomerAsset.query
                 .filter_by(customer_id=cust_id,
                            asset_name_norm=name.strip().lower(),
                            asset_type_id=type_id).first())
        if asset is None:
            errors.append(f'line {i}: row did not land (sync failure — see logs)')
            continue
        if asset.created_by is None:
            asset.created_by = current_user.id

        curation = {}
        if (row.get('criticality') or '').strip():
            curation['criticality'] = row['criticality'].strip().lower()
        for field in ('environment', 'owner', 'notes'):
            if (row.get(field) or '').strip():
                curation[field] = row[field].strip()
        comp = (row.get('compromise_status') or '').strip()
        if comp:
            if comp not in status_by_name:
                errors.append(f'line {i}: unknown compromise_status {comp!r} '
                              f'(valid: {", ".join(status_by_name)})')
                db.session.rollback()
                continue
            curation['compromise_status'] = status_by_name[comp]
        try:
            update_curation(asset, curation, current_user.id)
            db.session.commit()
            imported += 1
        except ValueError as e:
            db.session.rollback()
            errors.append(f'line {i}: {e}')

    track_activity(f'imported {imported} customer assets from CSV', ctx_less=True)
    return response_api_success({'imported': imported, 'errors': errors})

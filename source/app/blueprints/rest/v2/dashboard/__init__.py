#  IRIS Source Code
#  Copyright (C) 2024 - DFIR-IRIS
#  contact@dfir-iris.org
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

from flask import Blueprint, request

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.rest.endpoints import response_api_success
from app.blueprints.rest.endpoints import response_api_error
from app.business.dashboard_metrics import get_dashboard_metrics, get_bar_data
from app.datamgmt.dashboard.dashboard_db import list_user_cases, list_user_tasks, list_user_reviews
from app.datamgmt.dashboard.inventory_db import compute_capacity_planning
from app.datamgmt.dashboard.inventory_db import create_drive
from app.datamgmt.dashboard.inventory_db import delete_drive
from app.datamgmt.dashboard.inventory_db import get_drive
from app.datamgmt.dashboard.inventory_db import get_drive_by_barcode
from app.datamgmt.dashboard.inventory_db import list_drives
from app.datamgmt.dashboard.inventory_db import lookup_drive_payload
from app.datamgmt.dashboard.inventory_db import update_drive
from app.datamgmt.dashboard.inventory_db import wipe_drive
from app.schema.marshables import CaseDetailsSchema, CaseSchema

from flask_login import current_user

dashboard_blueprint = Blueprint('dashboard',
                                __name__,
                                url_prefix='/dashboard')


# TODO this endpoint does not adhere to the conventions (verb in URL).
#      Prefer to use GET /api/v2/cases. Check it is possible. If not, evolve /api/v2/cases
# iris-ng v2 Phase 5: re-enabled — the /home page reads it.
@dashboard_blueprint.route('/cases/list', methods=['GET'])
@ac_api_requires()
def list_own_cases():
    cases = list_user_cases(
        request.args.get('show_closed', 'false', type=str).lower() == 'true'
    )

    return response_api_success(data=CaseDetailsSchema(many=True).dump(cases))


# TODO this endpoint does not adhere to the conventions (verb in URL).
#      We should rather have /api/v2/tasks?
# iris-ng v2 Phase 5: re-enabled — the /home page reads it.
@dashboard_blueprint.route('/tasks/list', methods=['GET'])
@ac_api_requires()
def list_own_tasks():
    # list_user_tasks() returns a with_entities Row set (task_id, task_title,
    # task_case, case_id, status_name, status_bscolor, task_last_update...).
    # Dumping that through the ORM CaseTaskSchema silently DROPS every field
    # whose name is a Row label rather than a model column (case_id, the case
    # name, the status) — serialize the rows directly instead.
    out = []
    for row in list_user_tasks():
        d = row._asdict()
        if d.get('task_last_update') is not None:
            # naive UTC storage — explicit Z (project serialization rule)
            d['task_last_update'] = d['task_last_update'].isoformat() + 'Z'
        out.append(d)
    return response_api_success(data=out)


# TODO this endpoint does not adhere to the conventions (verb in URL).
#      We should rather have /api/v2/reviews?
# iris-ng v2 Phase 5: re-enabled — the /home page reads it.
@dashboard_blueprint.route('/reviews/list', methods=['GET'])
@ac_api_requires()
def list_own_reviews():
    reviews = list_user_reviews()
    return response_api_success(
        data=CaseSchema(
            many=True,
            only=["case_id", "case_name",
                  "review_status.status_name", "status_id"]
        ).dump(reviews))


# iris-next: aggregated metrics dashboard. Returns KPI strip + four sections
# (analyst self, SOC manager, admin/system health, investigation quality)
# computed on the fly from existing tables. Date range via query params:
#   ?start=<iso>&end=<iso>   (defaults to last 30 days)
@dashboard_blueprint.get('/metrics')
@ac_api_requires()
def get_metrics():
    start = request.args.get('start', None, type=str)
    end = request.args.get('end', None, type=str)
    ci_year = request.args.get('ci_year', None, type=int)
    tag_year = request.args.get('tag_year', None, type=int)
    try:
        data = get_dashboard_metrics(start, end, ci_year=ci_year, tag_year=tag_year)
    except Exception as exc:
        return response_api_error(f'Failed to compute metrics: {exc}')
    return response_api_success(data=data)


# iris-next: multi-year grouped bar data for Case Tagging and Sectors cards.
# ?section=tagging|ci  &years=2024,2025,2026
@dashboard_blueprint.get('/metrics/bar-data')
@ac_api_requires()
def get_metrics_bar_data():
    section = request.args.get('section', 'tagging', type=str)
    years_raw = request.args.get('years', '', type=str)
    years = []
    for part in years_raw.split(','):
        part = part.strip()
        if part.isdigit():
            years.append(int(part))
    if not years:
        import datetime as _dt
        years = [_dt.datetime.utcnow().year]
    try:
        data = get_bar_data(section, years)
    except Exception as exc:
        return response_api_error(f'Failed to compute bar data: {exc}')
    return response_api_success(data=data)


# iris-next: physical evidence-drive inventory (Inventory tab).
# A barcode identifies a physical drive; the lookup resolves it to the drive's
# location, current case, and the evidence items on it. Open to any logged-in
# user (evidence-locker workflow) — not per-case gated.

@dashboard_blueprint.get('/inventory/capacity')
@ac_api_requires()
def inventory_capacity():
    """Rolling-average intake rate vs effective 30-day drive supply.

    Returns a capacity planning dict — effective supply, runway in months,
    and an order recommendation with quantity when runway < the configured
    target. Open to any logged-in user (same scope as the inventory tab).
    """
    try:
        data = compute_capacity_planning()
    except Exception as exc:
        return response_api_error(f'Failed to compute capacity planning: {exc}')
    return response_api_success(data=data)


@dashboard_blueprint.get('/inventory/lookup')
@ac_api_requires()
def inventory_lookup():
    barcode = request.args.get('barcode', None, type=str)
    if not barcode or not barcode.strip():
        return response_api_error('A barcode is required')
    drive = get_drive_by_barcode(barcode)
    if drive is None:
        return response_api_error(f'No drive found for barcode "{barcode.strip()}"')
    return response_api_success(data=lookup_drive_payload(drive))


@dashboard_blueprint.get('/inventory/drives')
@ac_api_requires()
def inventory_list():
    return response_api_success(data=list_drives())


@dashboard_blueprint.post('/inventory/drives')
@ac_api_requires()
def inventory_create():
    body = request.get_json(silent=True) or {}
    barcode = (body.get('barcode') or '').strip()
    if not barcode:
        return response_api_error('A barcode is required')
    if get_drive_by_barcode(barcode) is not None:
        return response_api_error(f'A drive with barcode "{barcode}" already exists')
    created_by = body.get('created_by') or (current_user.name if current_user and current_user.is_authenticated else None)
    try:
        drive = create_drive(
            barcode=barcode,
            label=body.get('label'),
            serial_number=body.get('serial_number'),
            physical_location=body.get('physical_location'),
            status=body.get('status'),
            capacity=body.get('capacity'),
            notes=body.get('notes'),
            created_by=created_by,
            case_id=body.get('case_id'),
        )
    except Exception as exc:
        return response_api_error(f'Failed to register drive: {exc}')
    return response_api_success(data=lookup_drive_payload(drive))


@dashboard_blueprint.put('/inventory/drives/<int:drive_id>')
@ac_api_requires()
def inventory_update(drive_id):
    drive = get_drive(drive_id)
    if drive is None:
        return response_api_error('Drive not found')
    body = request.get_json(silent=True) or {}
    new_bc = (body.get('barcode') or '').strip()
    if new_bc and new_bc != drive.barcode:
        clash = get_drive_by_barcode(new_bc)
        if clash is not None and clash.id != drive.id:
            return response_api_error(f'A drive with barcode "{new_bc}" already exists')
    try:
        update_drive(
            drive,
            barcode=body.get('barcode'),
            label=body.get('label'),
            serial_number=body.get('serial_number'),
            physical_location=body.get('physical_location'),
            status=body.get('status'),
            capacity=body.get('capacity'),
            notes=body.get('notes'),
            case_id=body.get('case_id'),
        )
    except Exception as exc:
        return response_api_error(f'Failed to update drive: {exc}')
    return response_api_success(data=lookup_drive_payload(drive))


@dashboard_blueprint.post('/inventory/drives/<int:drive_id>/wipe')
@ac_api_requires()
def inventory_wipe(drive_id):
    drive = get_drive(drive_id)
    if drive is None:
        return response_api_error('Drive not found')
    try:
        wipe_drive(drive)
    except Exception as exc:
        return response_api_error(f'Failed to wipe drive: {exc}')
    return response_api_success(data=lookup_drive_payload(drive))


@dashboard_blueprint.delete('/inventory/drives/<int:drive_id>')
@ac_api_requires()
def inventory_delete(drive_id):
    drive = get_drive(drive_id)
    if drive is None:
        return response_api_error('Drive not found')
    try:
        delete_drive(drive)
    except Exception as exc:
        return response_api_error(f'Failed to delete drive: {exc}')
    return response_api_success(data={'deleted': drive_id})

#  IRIS-NG Source Code
#  contact@dfir-iris.org
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3 of the License, or (at your option) any later version.
"""Data access for the physical evidence-drive inventory (Inventory tab).

A drive is the barcoded physical item; CaseReceivedFile rows are the logical
evidence items on it. These helpers stay in the datamgmt layer per the
three-layer rule — blueprints call them, they never import from blueprints.
"""
import math
from datetime import datetime, timedelta

from app import db
from app.models.models import CaseReceivedFile
from app.models.models import EvidenceDrive
from app.models.models import EvidenceTypes
from app.models.models import ServerSettings
from app.models.cases import Cases


VALID_STATUSES = ('available', 'in_use', 'wiped', 'retired')


def list_drives():
    """All drives, newest first, with current-case name and overdue flag resolved."""
    settings = ServerSettings.query.first()
    retention_months = settings.retention_months if settings else None

    rows = db.session.query(
            EvidenceDrive,
            Cases.name.label('case_name'),
            Cases.close_date.label('case_close_date'),
        ) \
        .outerjoin(Cases, EvidenceDrive.case_id == Cases.case_id) \
        .order_by(EvidenceDrive.date_added.desc()) \
        .all()
    out = []
    for drive, case_name, case_close_date in rows:
        d = _serialize_drive(drive)
        d['case_name'] = case_name
        d['overdue'] = _is_overdue(drive, retention_months, case_close_date)
        out.append(d)
    return out


def _is_overdue(drive, retention_months, case_close_date=None):
    """True when an in-use drive's case closed longer ago than the retention period.

    The clock starts at case closure, not at drive assignment — a drive linked
    to a still-open case is never considered overdue regardless of how long it
    has been checked out.
    """
    if retention_months is None or drive.status != 'in_use' or case_close_date is None:
        return False
    # close_date may be a date or datetime depending on the ORM column type.
    if isinstance(case_close_date, datetime):
        close_dt = case_close_date
    else:
        close_dt = datetime(case_close_date.year, case_close_date.month, case_close_date.day)
    return (datetime.utcnow() - close_dt).days > retention_months * 30


def get_drive_by_barcode(barcode):
    """Resolve a scanned/keyed barcode to a drive (exact, then case-insensitive)."""
    if not barcode:
        return None
    bc = barcode.strip()
    drive = EvidenceDrive.query.filter(EvidenceDrive.barcode == bc).first()
    if drive is None:
        drive = EvidenceDrive.query.filter(db.func.lower(EvidenceDrive.barcode) == bc.lower()).first()
    return drive


def get_drive(drive_id):
    return EvidenceDrive.query.filter(EvidenceDrive.id == drive_id).first()


def lookup_drive_payload(drive):
    """Full lookup result for a drive: drive + location + case + evidence items."""
    if drive is None:
        return None
    payload = _serialize_drive(drive)

    case = Cases.query.filter(Cases.case_id == drive.case_id).first() if drive.case_id else None
    payload['case'] = {
        'case_id': case.case_id,
        'case_name': case.name,
    } if case else None

    items = db.session.query(CaseReceivedFile, EvidenceTypes.name.label('type_name')) \
        .outerjoin(EvidenceTypes, CaseReceivedFile.type_id == EvidenceTypes.id) \
        .filter(CaseReceivedFile.drive_id == drive.id) \
        .order_by(CaseReceivedFile.date_added.desc()) \
        .all()
    payload['evidences'] = [{
        'id': it.id,
        'filename': it.filename,
        'type_name': type_name,
        'file_hash': it.file_hash,
        'file_size': it.file_size,
        'case_id': it.case_id,
    } for it, type_name in items]

    return payload


def create_drive(barcode, label=None, serial_number=None, physical_location=None, status=None,
                  capacity=None, notes=None, created_by=None, case_id=None):
    # Maintainer vocabulary (2026-08-28): 'wiped' = in rotation, 'available'
    # = retention over / awaiting wipe. A fresh drive is in rotation.
    status = status if status in VALID_STATUSES else ('in_use' if case_id else 'wiped')
    drive = EvidenceDrive(
        barcode=barcode.strip(),
        label=label,
        serial_number=serial_number,
        physical_location=physical_location,
        status=status,
        capacity=capacity,
        notes=notes,
        created_by=created_by,
        case_id=case_id,
        date_added=datetime.utcnow(),
        date_assigned=datetime.utcnow() if case_id else None,
    )
    db.session.add(drive)
    db.session.commit()
    return drive


def update_drive(drive, **fields):
    """Patch mutable fields. Assigning a case flips status→in_use + stamps
    date_assigned (unless an explicit status is given)."""
    prev_case = drive.case_id
    for key in ('barcode', 'label', 'serial_number', 'physical_location', 'capacity', 'notes',
                'created_by', 'case_id', 'status'):
        if key in fields and fields[key] is not None:
            value = fields[key].strip() if key == 'barcode' else fields[key]
            setattr(drive, key, value)

    if 'case_id' in fields and fields['case_id'] and fields['case_id'] != prev_case:
        drive.date_assigned = datetime.utcnow()
        if 'status' not in fields:
            drive.status = 'in_use'

    if drive.status not in VALID_STATUSES:
        drive.status = 'wiped'

    db.session.commit()
    return drive


def wipe_drive(drive):
    """Lifecycle: wipe & return to rotation. Keeps the evidence rows (case
    history must survive) but unlinks them from the drive and clears the
    drive's case. Maintainer vocabulary (2026-08-28): a wiped drive is
    'wiped' — that IS the in-rotation state; 'available' means retention
    over and awaiting wipe."""
    db.session.query(CaseReceivedFile) \
        .filter(CaseReceivedFile.drive_id == drive.id) \
        .update({CaseReceivedFile.drive_id: None}, synchronize_session=False)
    drive.case_id = None
    drive.status = 'wiped'
    drive.date_wiped = datetime.utcnow()
    drive.date_assigned = None
    db.session.commit()
    return drive


def delete_drive(drive):
    # drive_id FK is ondelete=SET NULL, so evidence rows survive with drive_id=NULL.
    db.session.delete(drive)
    db.session.commit()


def compute_capacity_planning():
    """Rolling-average case intake rate vs effective 30-day drive supply.

    Effective supply = available drives + wipe-eligible drives (in_use drives
    whose case closed within 30 days of the configured retention threshold, or
    already past it). Without a retention policy wipe_eligible is 0 — there is
    no automatic return-to-rotation signal.

    Returns a dict consumed by GET /api/v2/dashboard/inventory/capacity.
    """
    settings = ServerSettings.query.first()
    window_months = (settings.capacity_planning_window_months if settings else None) or 3
    target_months = (settings.capacity_planning_target_months if settings else None) or 2
    retention_months = settings.retention_months if settings else None

    now = datetime.utcnow()
    window_start = (now - timedelta(days=window_months * 30)).date()

    # Cases.open_date is a Date column.
    case_count = Cases.query.filter(Cases.open_date >= window_start).count()
    avg_cases_per_month = case_count / window_months

    # Maintainer vocabulary (2026-08-28): 'wiped' = IN ROTATION (usable
    # supply); 'available' = retention over, awaiting wipe (one wipe away
    # from rotation). Both count toward effective supply, reported apart.
    in_rotation_count = EvidenceDrive.query.filter(EvidenceDrive.status == 'wiped').count()
    awaiting_wipe_count = EvidenceDrive.query.filter(EvidenceDrive.status == 'available').count()

    # Wipe-eligible: in_use drives past or within 30 days of the retention
    # threshold — the drives that will free up in the next ~30 days.
    if retention_months is not None:
        # Drives whose case closed >= (threshold - 30) days ago.
        threshold_cutoff = (now - timedelta(days=max(0, retention_months * 30 - 30))).date()
        wipe_eligible_count = (
            db.session.query(EvidenceDrive)
            .join(Cases, EvidenceDrive.case_id == Cases.case_id)
            .filter(EvidenceDrive.status == 'in_use')
            .filter(Cases.close_date.isnot(None))
            .filter(Cases.close_date <= threshold_cutoff)
            .count()
        )
    else:
        wipe_eligible_count = 0

    effective_supply = in_rotation_count + awaiting_wipe_count + wipe_eligible_count
    insufficient_data = avg_cases_per_month <= 0

    if insufficient_data:
        runway_months = None
        order_recommended = False
        order_quantity = 0
    else:
        runway_months = round(effective_supply / avg_cases_per_month, 1)
        order_recommended = runway_months < target_months
        order_quantity = (
            max(0, math.ceil(target_months * avg_cases_per_month) - effective_supply)
            if order_recommended else 0
        )

    return {
        'insufficient_data': insufficient_data,
        'window_months': window_months,
        'target_runway_months': target_months,
        'avg_cases_per_month': round(avg_cases_per_month, 2),
        'in_rotation_count': in_rotation_count,
        'awaiting_wipe_count': awaiting_wipe_count,
        # kept for API compatibility: the count of status='available' drives
        'available_count': awaiting_wipe_count,
        'wipe_eligible_count': wipe_eligible_count,
        'effective_supply': effective_supply,
        'runway_months': runway_months,
        'order_recommended': order_recommended,
        'order_quantity': order_quantity,
    }


def _serialize_drive(drive):
    return {
        'id': drive.id,
        'drive_uuid': str(drive.drive_uuid) if drive.drive_uuid else None,
        'barcode': drive.barcode,
        'label': drive.label,
        'serial_number': drive.serial_number,
        'physical_location': drive.physical_location,
        'status': drive.status,
        'capacity': drive.capacity,
        'notes': drive.notes,
        'created_by': drive.created_by,
        'case_id': drive.case_id,
        'date_added': drive.date_added.isoformat() + 'Z' if drive.date_added else None,
        'date_assigned': drive.date_assigned.isoformat() + 'Z' if drive.date_assigned else None,
        'date_wiped': drive.date_wiped.isoformat() + 'Z' if drive.date_wiped else None,
    }

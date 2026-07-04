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
from datetime import datetime

from app import db
from app.models.models import CaseReceivedFile
from app.models.models import EvidenceDrive
from app.models.models import EvidenceTypes
from app.models.cases import Cases


VALID_STATUSES = ('available', 'in_use', 'wiped', 'retired')


def list_drives():
    """All drives, newest first, with current-case name resolved."""
    rows = db.session.query(EvidenceDrive, Cases.name.label('case_name')) \
        .outerjoin(Cases, EvidenceDrive.case_id == Cases.case_id) \
        .order_by(EvidenceDrive.date_added.desc()) \
        .all()
    out = []
    for drive, case_name in rows:
        d = _serialize_drive(drive)
        d['case_name'] = case_name
        out.append(d)
    return out


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
    status = status if status in VALID_STATUSES else ('in_use' if case_id else 'available')
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
        drive.status = 'available'

    db.session.commit()
    return drive


def wipe_drive(drive):
    """Lifecycle: wipe & return to rotation. Keeps the evidence rows (case
    history must survive) but unlinks them from the drive and clears the
    drive's case + sets it available."""
    db.session.query(CaseReceivedFile) \
        .filter(CaseReceivedFile.drive_id == drive.id) \
        .update({CaseReceivedFile.drive_id: None}, synchronize_session=False)
    drive.case_id = None
    drive.status = 'available'
    drive.date_wiped = datetime.utcnow()
    drive.date_assigned = None
    db.session.commit()
    return drive


def delete_drive(drive):
    # drive_id FK is ondelete=SET NULL, so evidence rows survive with drive_id=NULL.
    db.session.delete(drive)
    db.session.commit()


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

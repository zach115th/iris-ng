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

import datetime
import marshmallow.exceptions
from flask_login import current_user
from sqlalchemy import and_
from sqlalchemy import desc

from app import db
from app.datamgmt.manage.manage_attribute_db import get_default_custom_attributes
from app.datamgmt.states import update_evidences_state
from app.models.models import CaseReceivedFile
from app.models.models import Comments
from app.models.models import EvidenceAssetLink
from app.models.models import EvidenceDrive
from app.models.models import EvidencesComments
from app.models.authorization import User


def _reconcile_evidence_drive(evidence):
    """iris-next: keep the evidence custody `barcode` field and the Inventory
    `drive_id` link consistent so a barcode the analyst typed doesn't silently
    fail to associate with the matching drive.

    - drive_id set, barcode empty  -> backfill barcode from the drive.
    - drive_id unset, barcode given -> auto-link to a drive with that barcode.
    An explicitly chosen drive_id always wins; we never override it.

    Whatever resolved, the drive's own case/status follow via
    _sync_drive_assignment — linking evidence is what puts a drive in use.
    """
    drive_id = getattr(evidence, 'drive_id', None)
    barcode = (getattr(evidence, 'barcode', None) or '').strip()
    drive = None

    if drive_id:
        drive = EvidenceDrive.query.filter(EvidenceDrive.id == drive_id).first()
        if drive and not barcode:
            evidence.barcode = drive.barcode
        elif (drive and barcode
                and barcode.lower() != (drive.barcode or '').lower()):
            # The typed barcode names a DIFFERENT drive than the stored
            # link — on an update the ORM instance keeps its old drive_id,
            # so without this the fresh scan silently disagrees with the
            # link (and the one-case rule below never sees the new drive).
            # A barcode matching a real drive wins; free text that matches
            # nothing leaves the chosen link alone.
            other = EvidenceDrive.query.filter(
                EvidenceDrive.barcode == barcode).first()
            if other is None:
                other = EvidenceDrive.query.filter(
                    db.func.lower(EvidenceDrive.barcode) == barcode.lower()
                ).first()
            if other is not None:
                drive = other
                evidence.drive_id = other.id
    elif barcode:
        drive = EvidenceDrive.query.filter(EvidenceDrive.barcode == barcode).first()
        if drive is None:
            drive = EvidenceDrive.query.filter(
                db.func.lower(EvidenceDrive.barcode) == barcode.lower()).first()
        if drive is not None:
            evidence.drive_id = drive.id

    _sync_drive_assignment(evidence, drive)


def _sync_drive_assignment(evidence, drive):
    """iris-next (maintainer rules, 2026-08-28): a drive holds evidence from
    ONE case only, and the status vocabulary is: 'wiped' = back in rotation,
    'available' = retention over, AWAITING wipe (still holds old data),
    'in_use' = assigned, 'retired' = out of service.

    - Cross-case link is REFUSED — a mis-scanned barcode must not silently
      re-home a drive; reassignment is an explicit act (edit or wipe).
    - Linking to an unassigned 'available' drive is REFUSED — new case data
      never lands on a drive that has not been wiped.
    - Linking claims an unassigned drive for the evidence's case and flips
      'wiped' -> 'in_use' (+ date_assigned). 'retired' is never resurrected.

    Raises marshmallow ValidationError so the evidence routes' existing
    handler turns it into a 400 the analyst can read; both save paths raise
    BEFORE commit, so nothing half-applies.
    """
    if drive is None or not getattr(evidence, 'case_id', None):
        return

    if drive.case_id:
        if drive.case_id != evidence.case_id:
            raise marshmallow.exceptions.ValidationError(
                f"Drive '{drive.barcode}' is assigned to case "
                f"#{drive.case_id} — a drive holds evidence from one case "
                "only. Wipe the drive to return it to rotation, or pick "
                "another drive.")
        return

    if drive.status == 'available':
        raise marshmallow.exceptions.ValidationError(
            f"Drive '{drive.barcode}' is awaiting wipe (status: available) — "
            "wipe it before assigning new evidence.")

    drive.case_id = evidence.case_id
    drive.date_assigned = datetime.datetime.utcnow()
    if drive.status == 'wiped':
        drive.status = 'in_use'


def get_rfiles(caseid):
    crf = CaseReceivedFile.query.filter(
        CaseReceivedFile.case_id == caseid
    ).order_by(
        desc(CaseReceivedFile.date_added)
    ).all()

    return crf


def get_evidence_asset_ids_bulk(evidence_ids):
    """{evidence_id: [asset_id, ...]} for a set of evidence items, in one
    query. The auto-schema's dumped `assets` field carries EvidenceAssetLink
    ROW ids, not asset ids — code that resolves assets from it looks up the
    wrong id space, so surfaces join through this instead."""
    if not evidence_ids:
        return {}
    rows = EvidenceAssetLink.query.with_entities(
        EvidenceAssetLink.evidence_id,
        EvidenceAssetLink.asset_id
    ).filter(
        EvidenceAssetLink.evidence_id.in_(evidence_ids)
    ).all()
    out = {}
    for evidence_id, asset_id in rows:
        out.setdefault(evidence_id, []).append(asset_id)
    return out


def add_rfile(evidence, caseid, user_id):

    evidence.date_added = datetime.datetime.now()
    evidence.case_id = caseid
    evidence.user_id = user_id

    evidence.custom_attributes = get_default_custom_attributes('evidence')

    _reconcile_evidence_drive(evidence)

    db.session.add(evidence)

    update_evidences_state(caseid=caseid, userid=user_id)

    db.session.commit()

    return evidence


def get_rfile(rfile_id, caseid):
    return CaseReceivedFile.query.filter(
        CaseReceivedFile.id == rfile_id,
        CaseReceivedFile.case_id == caseid
    ).first()


def update_rfile(evidence, user_id, caseid):

    evidence.user_id = user_id

    _reconcile_evidence_drive(evidence)

    update_evidences_state(caseid=caseid, userid=user_id)
    db.session.commit()
    return evidence


def delete_rfile(rfile_id, caseid):
    with db.session.begin_nested():
        com_ids = EvidencesComments.query.with_entities(
            EvidencesComments.comment_id
        ).filter(
            EvidencesComments.comment_evidence_id == rfile_id
        ).all()

        com_ids = [c.comment_id for c in com_ids]
        EvidencesComments.query.filter(EvidencesComments.comment_id.in_(com_ids)).delete()

        Comments.query.filter(Comments.comment_id.in_(com_ids)).delete()

        CaseReceivedFile.query.filter(and_(
            CaseReceivedFile.id == rfile_id,
            CaseReceivedFile.case_id == caseid,
        )).delete()

        update_evidences_state(caseid=caseid)

        db.session.commit()


def get_case_evidence_comments(evidence_id):
    return Comments.query.filter(
        EvidencesComments.comment_evidence_id == evidence_id
    ).join(
        EvidencesComments,
        Comments.comment_id == EvidencesComments.comment_id
    ).order_by(
        Comments.comment_date.asc()
    ).all()


def add_comment_to_evidence(evidence_id, comment_id):
    ec = EvidencesComments()
    ec.comment_evidence_id = evidence_id
    ec.comment_id = comment_id

    db.session.add(ec)
    db.session.commit()


def get_case_evidence_comments_count(evidences_list):
    return EvidencesComments.query.filter(
        EvidencesComments.comment_evidence_id.in_(evidences_list)
    ).with_entities(
        EvidencesComments.comment_evidence_id,
        EvidencesComments.comment_id
    ).group_by(
        EvidencesComments.comment_evidence_id,
        EvidencesComments.comment_id
    ).all()


def get_case_evidence_comment(evidence_id, comment_id):
    return EvidencesComments.query.filter(
        EvidencesComments.comment_evidence_id == evidence_id,
        EvidencesComments.comment_id == comment_id
    ).with_entities(
        Comments.comment_id,
        Comments.comment_text,
        Comments.comment_date,
        Comments.comment_update_date,
        Comments.comment_uuid,
        User.name,
        User.user
    ).join(
        EvidencesComments.comment
    ).join(
        Comments.user
    ).first()


def delete_evidence_comment(evidence_id, comment_id):
    comment = Comments.query.filter(
        Comments.comment_id == comment_id,
        Comments.comment_user_id == current_user.id
    ).first()
    if not comment:
        return False, "You are not allowed to delete this comment"

    EvidencesComments.query.filter(
        EvidencesComments.comment_evidence_id == evidence_id,
        EvidencesComments.comment_id == comment_id
    ).delete()

    db.session.delete(comment)
    db.session.commit()

    return True, "Comment deleted"

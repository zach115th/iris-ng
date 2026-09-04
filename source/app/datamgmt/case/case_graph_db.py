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

"""Queries backing the case knowledge-map overlay on the Graph tab.

The stock graph derives every edge from timeline-event co-occurrence: two
objects are connected only if they appear on the same event. These helpers
supply the *direct* object-to-object relationships instead -- the M2M link
tables -- so the Graph tab can overlay note and evidence provenance and show
links that no timeline event happens to cover.

Each helper returns plain tuples/dicts (not ORM objects) so the caller can
serialise them without worrying about detached instances.
"""

from app.models.models import CaseAssets
from app.models.models import CaseReceivedFile
from app.models.models import EvidenceAssetLink
from app.models.models import Ioc
from app.models.models import IocAssetLink
from app.models.models import IocNoteLink
from app.models.models import Notes
from app import db


def get_case_note_ioc_links(caseid):
    """Note <-> IOC provenance links for a case.

    Returns rows of (note_id, note_title, ioc_id, ioc_value).
    Scoped through Ioc.case_id rather than IocNoteLink.case_id so the result
    is correct even for link rows written before case_id was populated.
    """
    return db.session.query(
        Notes.note_id,
        Notes.note_title,
        Ioc.ioc_id,
        Ioc.ioc_value,
    ).select_from(IocNoteLink).join(
        Notes, Notes.note_id == IocNoteLink.note_id
    ).join(
        Ioc, Ioc.ioc_id == IocNoteLink.ioc_id
    ).filter(
        Ioc.case_id == caseid
    ).all()


def get_case_evidence_asset_links(caseid):
    """Evidence <-> Asset links for a case.

    Returns rows of (evidence_id, filename, asset_id, asset_name).
    """
    return db.session.query(
        CaseReceivedFile.id,
        CaseReceivedFile.filename,
        CaseAssets.asset_id,
        CaseAssets.asset_name,
    ).select_from(EvidenceAssetLink).join(
        CaseReceivedFile, CaseReceivedFile.id == EvidenceAssetLink.evidence_id
    ).join(
        CaseAssets, CaseAssets.asset_id == EvidenceAssetLink.asset_id
    ).filter(
        CaseReceivedFile.case_id == caseid
    ).all()


def get_case_ioc_asset_links(caseid):
    """IOC <-> Asset links for a case.

    Returns rows of (ioc_id, ioc_value, asset_id, asset_name). These are the
    direct links created by "push IOCs to assets" and by working-timeline
    promotion -- distinct from event co-occurrence.
    """
    return db.session.query(
        Ioc.ioc_id,
        Ioc.ioc_value,
        CaseAssets.asset_id,
        CaseAssets.asset_name,
    ).select_from(IocAssetLink).join(
        Ioc, Ioc.ioc_id == IocAssetLink.ioc_id
    ).join(
        CaseAssets, CaseAssets.asset_id == IocAssetLink.asset_id
    ).filter(
        CaseAssets.case_id == caseid
    ).all()

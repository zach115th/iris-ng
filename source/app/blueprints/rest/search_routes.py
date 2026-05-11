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

from flask import Blueprint
from flask import request
from sqlalchemy import and_
from sqlalchemy import or_

from app.iris_engine.utils.tracker import track_activity
from app.models.models import AssetsType
from app.models.models import CaseAssets
from app.models.models import CaseReceivedFile
from app.models.models import CaseTasks
from app.models.models import Comments
from app.models.models import EvidenceTypes
from app.models.models import Ioc
from app.models.models import IocType
from app.models.models import Notes
from app.models.models import TaskStatus
from app.models.models import Tlp
from app.models.cases import Cases
from app.models.cases import CasesEvent
from app.models.models import Client
from app.models.authorization import Permissions
from app.blueprints.access_controls import ac_api_requires
from app.blueprints.responses import response_success

search_rest_blueprint = Blueprint('search_rest', __name__)


@search_rest_blueprint.route('/search', methods=['POST'])
@ac_api_requires(Permissions.search_across_cases)
def search_file_post():

    jsdata = request.get_json()
    search_value = jsdata.get('search_value')
    search_type = jsdata.get('search_type')
    files = []
    search_condition = and_()

    track_activity("started a global search for {} on {}".format(search_value, search_type))

    if search_type == "ioc":
        res = Ioc.query.with_entities(
                            Ioc.ioc_value.label('ioc_name'),
                            Ioc.ioc_description.label('ioc_description'),
                            Ioc.ioc_misp,
                            IocType.type_name,
                            Tlp.tlp_name,
                            Tlp.tlp_bscolor,
                            Cases.name.label('case_name'),
                            Cases.case_id,
                            Client.name.label('customer_name')
                    ).filter(
                        and_(
                            Ioc.ioc_value.like(search_value),
                            Ioc.case_id == Cases.case_id,
                            Client.client_id == Cases.client_id,
                            Ioc.ioc_tlp_id == Tlp.tlp_id,
                            search_condition
                        )
                    ).join(Ioc.ioc_type).all()

        files = [row._asdict() for row in res]

    if search_type == "notes":

        ns = []
        if search_value:
            search_value = "%{}%".format(search_value)
            ns = Notes.query.filter(
                Notes.note_content.like(search_value),
                Cases.client_id == Client.client_id,
                search_condition
            ).with_entities(
                Notes.note_id,
                Notes.note_title,
                Cases.name.label('case_name'),
                Client.name.label('client_name'),
                Cases.case_id
            ).join(
                Notes.case
            ).order_by(
                Client.name
            ).all()

            ns = [row._asdict() for row in ns]

        files = ns

    if search_type == "comments":
        search_value = "%{}%".format(search_value)
        comments = Comments.query.filter(
            Comments.comment_text.like(search_value),
            Cases.client_id == Client.client_id,
            search_condition
        ).with_entities(
            Comments.comment_id,
            Comments.comment_text,
            Cases.name.label('case_name'),
            Client.name.label('customer_name'),
            Cases.case_id
        ).join(
            Comments.case
        ).join(
            Cases.client
        ).order_by(
            Client.name
        ).all()

        files = [row._asdict() for row in comments]

    if search_type == "assets":
        if search_value:
            like_value = "%{}%".format(search_value)
            res = CaseAssets.query.with_entities(
                CaseAssets.asset_id,
                CaseAssets.asset_name,
                CaseAssets.asset_description,
                CaseAssets.asset_ip,
                CaseAssets.asset_domain,
                AssetsType.asset_name.label('asset_type'),
                Cases.name.label('case_name'),
                Cases.case_id,
                Client.name.label('customer_name')
            ).filter(
                and_(
                    or_(
                        CaseAssets.asset_name.ilike(like_value),
                        CaseAssets.asset_description.ilike(like_value),
                        CaseAssets.asset_ip.ilike(like_value),
                        CaseAssets.asset_domain.ilike(like_value),
                    ),
                    CaseAssets.case_id == Cases.case_id,
                    Client.client_id == Cases.client_id,
                    search_condition
                )
            ).join(
                CaseAssets.asset_type
            ).order_by(
                Client.name
            ).all()
            files = [row._asdict() for row in res]

    if search_type == "tasks":
        if search_value:
            like_value = "%{}%".format(search_value)
            res = CaseTasks.query.with_entities(
                CaseTasks.id.label('task_id'),
                CaseTasks.task_title,
                CaseTasks.task_description,
                TaskStatus.status_name.label('status_name'),
                TaskStatus.status_bscolor.label('status_bscolor'),
                Cases.name.label('case_name'),
                Cases.case_id,
                Client.name.label('customer_name')
            ).filter(
                and_(
                    or_(
                        CaseTasks.task_title.ilike(like_value),
                        CaseTasks.task_description.ilike(like_value),
                    ),
                    CaseTasks.task_case_id == Cases.case_id,
                    Client.client_id == Cases.client_id,
                    search_condition
                )
            ).outerjoin(
                TaskStatus, TaskStatus.id == CaseTasks.task_status_id
            ).order_by(
                Client.name
            ).all()
            files = [row._asdict() for row in res]

    if search_type == "evidence":
        if search_value:
            like_value = "%{}%".format(search_value)
            res = CaseReceivedFile.query.with_entities(
                CaseReceivedFile.id.label('evidence_id'),
                CaseReceivedFile.filename,
                CaseReceivedFile.file_description,
                CaseReceivedFile.file_hash,
                EvidenceTypes.name.label('type_name'),
                Cases.name.label('case_name'),
                Cases.case_id,
                Client.name.label('customer_name')
            ).filter(
                and_(
                    or_(
                        CaseReceivedFile.filename.ilike(like_value),
                        CaseReceivedFile.file_description.ilike(like_value),
                        CaseReceivedFile.file_hash.ilike(like_value),
                    ),
                    CaseReceivedFile.case_id == Cases.case_id,
                    Client.client_id == Cases.client_id,
                    search_condition
                )
            ).outerjoin(
                EvidenceTypes, EvidenceTypes.id == CaseReceivedFile.type_id
            ).order_by(
                Client.name
            ).all()
            files = [row._asdict() for row in res]

    if search_type == "events":
        if search_value:
            like_value = "%{}%".format(search_value)
            res = CasesEvent.query.with_entities(
                CasesEvent.event_id,
                CasesEvent.event_title,
                CasesEvent.event_content,
                CasesEvent.event_date,
                CasesEvent.event_source,
                Cases.name.label('case_name'),
                Cases.case_id,
                Client.name.label('customer_name')
            ).filter(
                and_(
                    or_(
                        CasesEvent.event_title.ilike(like_value),
                        CasesEvent.event_content.ilike(like_value),
                        CasesEvent.event_source.ilike(like_value),
                    ),
                    CasesEvent.case_id == Cases.case_id,
                    Client.client_id == Cases.client_id,
                    search_condition
                )
            ).order_by(
                Client.name
            ).all()
            files = [row._asdict() for row in res]

    if search_type == "cases":
        if search_value:
            like_value = "%{}%".format(search_value)
            res = Cases.query.with_entities(
                Cases.case_id,
                Cases.name.label('case_name'),
                Cases.description.label('case_description'),
                Cases.soc_id,
                Cases.open_date,
                Cases.close_date,
                Client.name.label('customer_name')
            ).filter(
                and_(
                    or_(
                        Cases.name.ilike(like_value),
                        Cases.description.ilike(like_value),
                        Cases.soc_id.ilike(like_value),
                        Cases.closing_note.ilike(like_value),
                    ),
                    Client.client_id == Cases.client_id,
                    search_condition
                )
            ).order_by(
                Client.name
            ).all()
            files = [row._asdict() for row in res]

    return response_success("Results fetched", files)

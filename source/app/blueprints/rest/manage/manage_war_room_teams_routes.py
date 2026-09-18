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

"""War-room team templates (iris-ng v2, Settings > War Room Teams, #115).

Org-wide default @-mention teams seeded, EMPTY, into every new war room.
Management is server_administrator only; the room side needs nothing from
here (seeding happens inside business.war_rooms room creation)."""

from flask import Blueprint
from flask import request
from flask_login import current_user

from app.business.errors import BusinessProcessingError
from app.business.war_rooms import create_team_template
from app.business.war_rooms import delete_team_template
from app.business.war_rooms import list_team_templates
from app.business.war_rooms import reorder_team_templates
from app.business.war_rooms import team_template_row
from app.business.war_rooms import update_team_template
from app.iris_engine.utils.tracker import track_activity
from app.models.authorization import Permissions
from app.blueprints.access_controls import ac_api_requires
from app.blueprints.responses import response_error
from app.blueprints.responses import response_success

manage_war_room_teams_rest_blueprint = Blueprint('manage_war_room_teams_rest', __name__)


@manage_war_room_teams_rest_blueprint.route('/manage/war-room-teams/list', methods=['GET'])
@ac_api_requires(Permissions.server_administrator)
def war_room_teams_list():
    return response_success('', data=[team_template_row(t) for t in list_team_templates()])


@manage_war_room_teams_rest_blueprint.route('/manage/war-room-teams/add', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def war_room_teams_add():
    payload = request.get_json(silent=True) or {}
    try:
        t = create_team_template(payload.get('name'), current_user.id,
                                 description=payload.get('description'),
                                 color=payload.get('color'),
                                 is_active=payload.get('is_active', True))
    except BusinessProcessingError as e:
        return response_error(str(e))
    track_activity(f'War-room team template @{t.name} created', ctx_less=True)
    return response_success('Team template created', data=team_template_row(t))


@manage_war_room_teams_rest_blueprint.route('/manage/war-room-teams/update/<int:template_id>',
                                            methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def war_room_teams_update(template_id):
    payload = request.get_json(silent=True) or {}
    fields = {k: payload[k] for k in ('name', 'description', 'color', 'is_active')
              if k in payload}
    try:
        t = update_team_template(template_id, **fields)
    except BusinessProcessingError as e:
        return response_error(str(e))
    track_activity(f'War-room team template @{t.name} updated', ctx_less=True)
    return response_success('Team template updated', data=team_template_row(t))


@manage_war_room_teams_rest_blueprint.route('/manage/war-room-teams/delete/<int:template_id>',
                                            methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def war_room_teams_delete(template_id):
    try:
        delete_team_template(template_id)
    except BusinessProcessingError as e:
        return response_error(str(e))
    track_activity(f'War-room team template #{template_id} deleted', ctx_less=True)
    return response_success('Team template deleted')


@manage_war_room_teams_rest_blueprint.route('/manage/war-room-teams/reorder', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def war_room_teams_reorder():
    payload = request.get_json(silent=True) or {}
    try:
        reorder_team_templates(payload.get('ids'))
    except BusinessProcessingError as e:
        return response_error(str(e))
    return response_success('Order saved',
                            data=[team_template_row(t) for t in list_team_templates()])

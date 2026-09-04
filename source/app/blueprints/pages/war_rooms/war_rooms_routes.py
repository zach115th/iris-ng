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

"""War Rooms pages (iris-ng v2, Phase 6). Server-rendered shells; all data
comes from /api/v2/war-rooms* (war_rooms.js / war_room.js). Membership is
enforced by the API — a non-member's detail page renders the shell and the
API's 404 shows as 'not found or not a member'."""

from typing import Union

from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import url_for
from flask_wtf import FlaskForm
from werkzeug import Response

from app.blueprints.access_controls import ac_requires

war_rooms_page_blueprint = Blueprint(
    'war_rooms',
    __name__,
    template_folder='templates'
)


@war_rooms_page_blueprint.route('/war-rooms', methods=['GET'])
@ac_requires(no_cid_required=True)
def war_rooms_list_route(caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for('war_rooms.war_rooms_list_route', cid=caseid))

    form = FlaskForm()
    return render_template('war_rooms.html', caseid=caseid, form=form)


@war_rooms_page_blueprint.route('/war-rooms/<int:room_id>', methods=['GET'])
@ac_requires(no_cid_required=True)
def war_room_detail_route(room_id, caseid, url_redir) -> Union[str, Response]:
    if url_redir:
        return redirect(url_for('war_rooms.war_room_detail_route',
                                room_id=room_id, cid=caseid))

    form = FlaskForm()
    return render_template('war_room.html', caseid=caseid, form=form,
                           room_id=room_id)

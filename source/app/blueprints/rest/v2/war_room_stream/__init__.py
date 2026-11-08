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

"""War-room Stream REST (iris-ng 2026-11-08).

  /api/v2/war-rooms/<rid>/stream                          GET ?kinds=&before=&limit=&topics=&q= (members + guests)
  /api/v2/war-rooms/<rid>/stream/vocab                    GET: lanes, kinds, families, case activity types
  /api/v2/war-rooms/<rid>/stream/index                    GET: Decisions & Pins (decisions, pins, notes)
  /api/v2/war-rooms/stream-preferences                    GET / PUT {prefs} (users; guests keep theirs locally)
  /api/v2/war-rooms/<rid>/topics                          GET / POST {name} (responder)
  /api/v2/war-rooms/<rid>/topics/<tid>/archive|restore    POST (a lead or the topic's creator)
  /api/v2/war-rooms/<rid>/messages/<mid>                  PUT {content} (author) / DELETE (author or lead)
  /api/v2/war-rooms/<rid>/messages/<mid>/reactions        POST {emoji}: toggles the caller's reaction
  /api/v2/war-rooms/<rid>/messages/<mid>/thread           GET: the thread (root + replies)
  /api/v2/war-rooms/<rid>/messages/<mid>/thread-title     PUT {title} (author or lead)
  /api/v2/war-rooms/<rid>/messages/<mid>/follow           POST {following}
  /api/v2/war-rooms/<rid>/threads                         GET
  /api/v2/war-rooms/<rid>/files                           POST multipart `file` (responder): 25 MB at most
  /api/v2/war-rooms/<rid>/files/<fid>                     GET (members + guests): raster images inline,
                                                          everything else as a download (?download=1 forces it)

Room access is the war rooms' own (_resolve: non-members 404). Guests take part like responders (post,
edit and delete their own messages, react, follow, attach files); the attached cases' activity they see
is every attached case's (maintainer decision 2026-09-30). A closed room is read-only.
"""
from datetime import datetime

from flask import Blueprint
from flask import request
from flask import send_file

from app.blueprints.access_controls import ac_room_api_requires
from app.blueprints.responses import response_error
from app.blueprints.rest.endpoints import response_api_success
from app.business import war_room_stream as ws
from app.business.errors import BusinessProcessingError
from app.business.war_room_stream import StreamError
from app.models import war_room_stream_vocab as sv

war_room_stream_blueprint = Blueprint('war_room_stream_rest_v2', __name__)


def _ctx():
    from app.blueprints.rest.v2.war_rooms import _gid
    from app.blueprints.rest.v2.war_rooms import _uid
    return _uid(), _gid()


def _resolve(room_id, min_role):
    from app.blueprints.rest.v2.war_rooms import _resolve as resolve
    return resolve(room_id, min_role, guests=True)


def _out(value):
    """Datetimes become ISO UTC strings, recursively."""
    if isinstance(value, datetime):
        return value.isoformat() + ('Z' if value.tzinfo is None else '')
    if isinstance(value, dict):
        return {k: _out(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_out(v) for v in value]
    return value


def _err(e):
    status = getattr(e, 'status', 400)
    return response_error(e.get_message() if hasattr(e, 'get_message') else str(e), status=status)


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


# ------------------------------------------------------------------------------ the feed

@war_room_stream_blueprint.route('/war-rooms/<int:room_id>/stream', methods=['GET'])
@ac_room_api_requires()
def get_room_stream(room_id):
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    uid, gid = _ctx()
    topics = [t for t in (request.args.get('topics') or '').split(',') if t.strip()] or None
    try:
        page = ws.stream_page(room, uid, viewer_guest_id=gid, kinds=request.args.get('kinds'),
                              before=request.args.get('before'), limit=request.args.get('limit'),
                              topics=topics, q=request.args.get('q'))
    except StreamError as e:
        return _err(e)
    return response_api_success(_out({'stream': page['items'], 'next_cursor': page['next_cursor'],
                                      'topics': [t['name'] for t in ws.topic_rows(room)]}))


@war_room_stream_blueprint.route('/war-rooms/<int:room_id>/stream/vocab', methods=['GET'])
@ac_room_api_requires()
def get_room_stream_vocab(room_id):
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    return response_api_success(sv.as_dict())


@war_room_stream_blueprint.route('/war-rooms/<int:room_id>/stream/index', methods=['GET'])
@ac_room_api_requires()
def get_room_stream_index(room_id):
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    return response_api_success(_out({'items': ws.room_index(room)}))


@war_room_stream_blueprint.route('/war-rooms/stream-preferences', methods=['GET', 'PUT'])
@ac_room_api_requires()
def room_stream_preferences():
    uid, gid = _ctx()
    if gid or not uid:
        return response_error('Guests keep their Activity settings in the browser', status=403)
    if request.method == 'GET':
        return response_api_success({'prefs': ws.get_prefs(uid)})
    try:
        prefs = ws.save_prefs(uid, _body().get('prefs'))
    except StreamError as e:
        return _err(e)
    return response_api_success({'prefs': prefs})


# --------------------------------------------------------------------------------- topics

@war_room_stream_blueprint.route('/war-rooms/<int:room_id>/topics', methods=['GET'])
@ac_room_api_requires()
def get_room_topics(room_id):
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    return response_api_success(_out({'topics': ws.topic_rows(room)}))


@war_room_stream_blueprint.route('/war-rooms/<int:room_id>/topics', methods=['POST'])
@ac_room_api_requires()
def create_room_topic(room_id):
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    uid, gid = _ctx()
    try:
        row = ws.create_topic(room, _body().get('name'), user_id=uid, guest_id=gid)
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success(_out({'id': row.id, 'name': row.name, 'topics': ws.topic_rows(room)}))


def _archive(room_id, topic_id, archived):
    room, role, err = _resolve(room_id, 'responder')
    if err:
        return err
    uid, gid = _ctx()
    try:
        row = ws.set_topic_archived(room, topic_id, archived, user_id=uid, guest_id=gid, is_lead=role == 'lead')
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success(_out({'id': row.id, 'name': row.name, 'archived': row.archived_at is not None,
                                      'topics': ws.topic_rows(room)}))


@war_room_stream_blueprint.route('/war-rooms/<int:room_id>/topics/<int:topic_id>/archive', methods=['POST'])
@ac_room_api_requires()
def archive_room_topic(room_id, topic_id):
    return _archive(room_id, topic_id, True)


@war_room_stream_blueprint.route('/war-rooms/<int:room_id>/topics/<int:topic_id>/restore', methods=['POST'])
@ac_room_api_requires()
def restore_room_topic(room_id, topic_id):
    return _archive(room_id, topic_id, False)


# ------------------------------------------------------------------------------- messages

def _message_out(room, msg):
    uid, gid = _ctx()
    return _out(ws.message_items(room, [msg], uid, gid)[0])


@war_room_stream_blueprint.route('/war-rooms/<int:room_id>/messages/<int:message_id>', methods=['PUT'])
@ac_room_api_requires()
def edit_room_message(room_id, message_id):
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    uid, gid = _ctx()
    try:
        msg = ws.edit_message(room, message_id, _body().get('content'), user_id=uid, guest_id=gid)
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success(_message_out(room, msg))


@war_room_stream_blueprint.route('/war-rooms/<int:room_id>/messages/<int:message_id>', methods=['DELETE'])
@ac_room_api_requires()
def delete_room_message(room_id, message_id):
    room, role, err = _resolve(room_id, 'responder')
    if err:
        return err
    uid, gid = _ctx()
    try:
        ws.delete_message(room, message_id, user_id=uid, guest_id=gid, is_lead=role == 'lead')
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success({'deleted': message_id})


@war_room_stream_blueprint.route('/war-rooms/<int:room_id>/messages/<int:message_id>/reactions', methods=['POST'])
@ac_room_api_requires()
def react_room_message(room_id, message_id):
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    uid, gid = _ctx()
    try:
        reactions = ws.toggle_reaction(room, message_id, _body().get('emoji'), user_id=uid, guest_id=gid)
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success({'message_id': message_id, 'reactions': reactions})


# -------------------------------------------------------------------------------- threads

@war_room_stream_blueprint.route('/war-rooms/<int:room_id>/threads', methods=['GET'])
@ac_room_api_requires()
def get_room_threads(room_id):
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    uid, gid = _ctx()
    return response_api_success(_out({'threads': ws.list_threads(room, uid, gid)}))


@war_room_stream_blueprint.route('/war-rooms/<int:room_id>/messages/<int:message_id>/thread', methods=['GET'])
@ac_room_api_requires()
def get_room_thread(room_id, message_id):
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    uid, gid = _ctx()
    try:
        return response_api_success(_out(ws.thread(room, message_id, uid, gid)))
    except BusinessProcessingError as e:
        return _err(e)


@war_room_stream_blueprint.route('/war-rooms/<int:room_id>/messages/<int:message_id>/thread-title',
                                 methods=['PUT'])
@ac_room_api_requires()
def set_room_thread_title(room_id, message_id):
    room, role, err = _resolve(room_id, 'responder')
    if err:
        return err
    uid, gid = _ctx()
    try:
        root = ws.set_thread_title(room, message_id, _body().get('title'), user_id=uid, guest_id=gid,
                                   is_lead=role == 'lead')
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success({'root_id': root.id, 'thread_title': root.thread_title})


@war_room_stream_blueprint.route('/war-rooms/<int:room_id>/messages/<int:message_id>/follow', methods=['POST'])
@ac_room_api_requires()
def follow_room_thread(room_id, message_id):
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    uid, gid = _ctx()
    try:
        following = ws.set_follow(room, message_id, bool(_body().get('following', True)), user_id=uid,
                                  guest_id=gid)
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success({'root_id': message_id, 'following': following})


# ---------------------------------------------------------------------------------- files

@war_room_stream_blueprint.route('/war-rooms/<int:room_id>/files', methods=['POST'])
@ac_room_api_requires()
def upload_room_file(room_id):
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    uid, gid = _ctx()
    try:
        row = ws.save_upload(room, request.files.get('file'), user_id=uid, guest_id=gid)
    except BusinessProcessingError as e:
        return _err(e)
    out = _out(ws.file_row(row))
    out['token'] = '#[file:%d|%s]' % (row.id, row.filename)
    return response_api_success(out)


@war_room_stream_blueprint.route('/war-rooms/<int:room_id>/files/<int:file_id>', methods=['GET'])
@ac_room_api_requires()
def get_room_file(room_id, file_id):
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    try:
        f = ws.get_file(room, file_id)
    except BusinessProcessingError as e:
        return _err(e)
    inline = f.mime_type.startswith('image/') and request.args.get('download') != '1'
    resp = send_file(ws.file_path(f), mimetype=f.mime_type if inline else 'application/octet-stream',
                     as_attachment=not inline, download_name=f.filename, max_age=0, conditional=True)
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Content-Security-Policy'] = "default-src 'none'; sandbox"
    resp.headers['Cache-Control'] = 'private, no-store'
    return resp

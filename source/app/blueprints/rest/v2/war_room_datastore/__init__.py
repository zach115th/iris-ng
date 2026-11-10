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

"""War-room datastore REST (iris-ng 2026-11-10).

  /api/v2/war-rooms/<rid>/datastore                                 GET: folders, counts, what the viewer may do
  /api/v2/war-rooms/<rid>/datastore/files                           GET ?folder=<id|root|stream>&q= / POST multipart
                                                                    `file` (one or more), folder_id, description, tags
  /api/v2/war-rooms/<rid>/datastore/files/<fid>                     GET / PUT {filename, description, tags} / DELETE
  /api/v2/war-rooms/<rid>/datastore/files/<fid>/content             GET: a download (?inline=1 shows a raster image)
  /api/v2/war-rooms/<rid>/datastore/files/<fid>/replace             POST multipart `file`: new contents
  /api/v2/war-rooms/<rid>/datastore/files/<fid>/move                POST {folder_id} (null or 'root' = top level)
  /api/v2/war-rooms/<rid>/datastore/files/<fid>/copy-to-case        POST {case_id}
  /api/v2/war-rooms/<rid>/datastore/stream/<fid>/copy-to-case       POST {case_id}: a Stream attachment
  /api/v2/war-rooms/<rid>/datastore/folders                         POST {name, parent_id}
  /api/v2/war-rooms/<rid>/datastore/folders/<id>                    PUT {name} / DELETE (contents move up)
  /api/v2/war-rooms/<rid>/datastore/folders/<id>/move               POST {parent_id}

Room access is the war rooms' own (_resolve: non-members 404). Maintainer's rules: observers browse and download;
responders, leads and portal guests upload, edit and move; deleting is for whoever created the file or folder, or a
lead; a closed room's datastore is read-only. Copying to a case is for users with full access to that case, never
a guest. A Stream attachment downloads through the Stream's own route.
"""
from datetime import datetime

from flask import Blueprint
from flask import request
from flask import send_file
from flask_login import current_user

from app.blueprints.access_controls import ac_room_api_requires
from app.blueprints.responses import response_error
from app.blueprints.rest.endpoints import response_api_success
from app.business import war_room_datastore as wd
from app.business.errors import BusinessProcessingError
from app.models import war_room_datastore_vocab as dv

war_room_datastore_blueprint = Blueprint('war_room_datastore_rest_v2', __name__)


def _ctx():
    from app.blueprints.rest.v2.war_rooms import _gid
    from app.blueprints.rest.v2.war_rooms import _uid
    return _uid(), _gid()


def _resolve(room_id, min_role, guests=True):
    from app.blueprints.rest.v2.war_rooms import _resolve as resolve
    return resolve(room_id, min_role, guests=guests)


def _out(value):
    if isinstance(value, datetime):
        return value.isoformat() + ('Z' if value.tzinfo is None else '')
    if isinstance(value, dict):
        return {k: _out(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_out(v) for v in value]
    return value


def _err(e):
    return response_error(e.get_message() if hasattr(e, 'get_message') else str(e), status=getattr(e, 'status', 400))


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _rows(room, role, files):
    uid, gid = _ctx()
    lead = role == 'lead'
    writable = room.status != 'closed'
    rows = wd.file_rows(files)
    by_id = {f.id: f for f in files}
    for r in rows:
        r['can_delete'] = writable and wd.can_delete_file(by_id[r['id']], uid, gid, lead)
    return rows


# --------------------------------------------------------------------------------------- the store

@war_room_datastore_blueprint.route('/war-rooms/<int:room_id>/datastore', methods=['GET'])
@ac_room_api_requires()
def get_room_datastore(room_id):
    room, role, err = _resolve(room_id, 'observer')
    if err:
        return err
    uid, gid = _ctx()
    out = wd.tree(room)
    lead = role == 'lead'
    writable = room.status != 'closed'
    for f in out['folders']:
        f['can_delete'] = writable and (lead or (gid is not None and f['created_by_guest_id'] == gid)
                                        or (gid is None and uid is not None and f['created_by'] == uid))
    out['can'] = {
        'write': writable and role in ('responder', 'lead'),
        'lead': lead,
        'copy_to_case': gid is None and role in ('responder', 'lead'),
    }
    out['closed'] = not writable
    out['limits'] = {'file_max_bytes': dv.DS_FILE_MAX_BYTES, 'upload_files_max': dv.DS_UPLOAD_FILES_MAX,
                     'folder_name_max': dv.DS_FOLDER_NAME_MAX, 'description_max': dv.DS_DESCRIPTION_MAX,
                     'tags_max': dv.DS_TAGS_MAX, 'depth_max': dv.DS_DEPTH_MAX}
    return response_api_success(_out(out))


@war_room_datastore_blueprint.route('/war-rooms/<int:room_id>/datastore/files', methods=['GET'])
@ac_room_api_requires()
def list_room_datastore_files(room_id):
    room, role, err = _resolve(room_id, 'observer')
    if err:
        return err
    folder = request.args.get('folder', dv.ROOT)
    try:
        if folder == dv.STREAM:
            return response_api_success(_out({'folder': dv.STREAM, 'files': wd.stream_rows(wd.stream_files(room))}))
        files = wd.list_files(room, folder, request.args.get('q'))
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success(_out({'folder': folder, 'q': request.args.get('q') or '',
                                      'files': _rows(room, role, files)}))


@war_room_datastore_blueprint.route('/war-rooms/<int:room_id>/datastore/files', methods=['POST'])
@ac_room_api_requires()
def upload_room_datastore_files(room_id):
    room, role, err = _resolve(room_id, 'responder')
    if err:
        return err
    uploads = request.files.getlist('file')
    if not uploads:
        return response_error('No file')
    if len(uploads) > dv.DS_UPLOAD_FILES_MAX:
        return response_error('Upload %d files at most at once' % dv.DS_UPLOAD_FILES_MAX)
    uid, gid = _ctx()
    saved, errors, first = [], [], None
    for upload in uploads:
        try:
            saved.append(wd.upload(room, upload, request.form.get('folder_id'), request.form.get('description'),
                                   request.form.get('tags'), user_id=uid, guest_id=gid))
        except BusinessProcessingError as e:
            first = first or e
            errors.append({'filename': upload.filename, 'message': str(e)})
    if not saved:
        return _err(first)
    return response_api_success(_out({'files': _rows(room, role, saved), 'errors': errors}))


@war_room_datastore_blueprint.route('/war-rooms/<int:room_id>/datastore/files/<int:file_id>', methods=['GET'])
@ac_room_api_requires()
def get_room_datastore_file(room_id, file_id):
    room, role, err = _resolve(room_id, 'observer')
    if err:
        return err
    try:
        f = wd.get_file(room, file_id)
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success(_out(_rows(room, role, [f])[0]))


@war_room_datastore_blueprint.route('/war-rooms/<int:room_id>/datastore/files/<int:file_id>', methods=['PUT'])
@ac_room_api_requires()
def update_room_datastore_file(room_id, file_id):
    room, role, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = _body()
    fields = {k: data[k] for k in ('filename', 'description', 'tags') if k in data}
    uid, gid = _ctx()
    try:
        f = wd.update_file(room, file_id, user_id=uid, guest_id=gid, **fields)
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success(_out(_rows(room, role, [f])[0]))


@war_room_datastore_blueprint.route('/war-rooms/<int:room_id>/datastore/files/<int:file_id>', methods=['DELETE'])
@ac_room_api_requires()
def delete_room_datastore_file(room_id, file_id):
    room, role, err = _resolve(room_id, 'responder')
    if err:
        return err
    uid, gid = _ctx()
    try:
        wd.delete_file(room, file_id, user_id=uid, guest_id=gid, is_lead=role == 'lead')
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success({'deleted': file_id})


@war_room_datastore_blueprint.route('/war-rooms/<int:room_id>/datastore/files/<int:file_id>/content',
                                    methods=['GET'])
@ac_room_api_requires()
def get_room_datastore_content(room_id, file_id):
    room, _, err = _resolve(room_id, 'observer')
    if err:
        return err
    try:
        f = wd.get_file(room, file_id)
        path = wd.stored_path(f)
    except BusinessProcessingError as e:
        return _err(e)
    inline = f.mime_type.startswith('image/') and request.args.get('inline') == '1'
    resp = send_file(path, mimetype=f.mime_type if inline else 'application/octet-stream', as_attachment=not inline,
                     download_name=f.filename, max_age=0, conditional=True)
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Content-Security-Policy'] = "default-src 'none'; sandbox"
    resp.headers['Cache-Control'] = 'private, no-store'
    return resp


@war_room_datastore_blueprint.route('/war-rooms/<int:room_id>/datastore/files/<int:file_id>/replace',
                                    methods=['POST'])
@ac_room_api_requires()
def replace_room_datastore_file(room_id, file_id):
    room, role, err = _resolve(room_id, 'responder')
    if err:
        return err
    uid, gid = _ctx()
    try:
        f = wd.replace_file(room, file_id, request.files.get('file'), user_id=uid, guest_id=gid)
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success(_out(_rows(room, role, [f])[0]))


@war_room_datastore_blueprint.route('/war-rooms/<int:room_id>/datastore/files/<int:file_id>/move',
                                    methods=['POST'])
@ac_room_api_requires()
def move_room_datastore_file(room_id, file_id):
    room, role, err = _resolve(room_id, 'responder')
    if err:
        return err
    uid, gid = _ctx()
    try:
        f = wd.move_file(room, file_id, _body().get('folder_id'), user_id=uid, guest_id=gid)
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success(_out(_rows(room, role, [f])[0]))


def _copy(room_id, source, file_id):
    room, _, err = _resolve(room_id, 'responder', guests=False)
    if err:
        return err
    try:
        dsf = wd.copy_to_case(room, source, file_id, _body().get('case_id'), current_user)
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success({'case_id': dsf.file_case_id, 'file_id': dsf.file_id,
                                 'filename': dsf.file_original_name, 'folder': dv.CASE_FOLDER_NAME})


@war_room_datastore_blueprint.route('/war-rooms/<int:room_id>/datastore/files/<int:file_id>/copy-to-case',
                                    methods=['POST'])
@ac_room_api_requires()
def copy_room_datastore_file_to_case(room_id, file_id):
    return _copy(room_id, 'datastore', file_id)


@war_room_datastore_blueprint.route('/war-rooms/<int:room_id>/datastore/stream/<int:file_id>/copy-to-case',
                                    methods=['POST'])
@ac_room_api_requires()
def copy_room_stream_file_to_case(room_id, file_id):
    return _copy(room_id, 'stream', file_id)


# ------------------------------------------------------------------------------------------ folders

@war_room_datastore_blueprint.route('/war-rooms/<int:room_id>/datastore/folders', methods=['POST'])
@ac_room_api_requires()
def create_room_datastore_folder(room_id):
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    data = _body()
    uid, gid = _ctx()
    try:
        folder = wd.create_folder(room, data.get('name'), data.get('parent_id'), user_id=uid, guest_id=gid)
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success({'id': folder.id, 'name': folder.name, 'parent_id': folder.parent_id})


@war_room_datastore_blueprint.route('/war-rooms/<int:room_id>/datastore/folders/<int:folder_id>',
                                    methods=['PUT'])
@ac_room_api_requires()
def rename_room_datastore_folder(room_id, folder_id):
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    try:
        folder = wd.rename_folder(room, folder_id, _body().get('name'))
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success({'id': folder.id, 'name': folder.name, 'parent_id': folder.parent_id})


@war_room_datastore_blueprint.route('/war-rooms/<int:room_id>/datastore/folders/<int:folder_id>/move',
                                    methods=['POST'])
@ac_room_api_requires()
def move_room_datastore_folder(room_id, folder_id):
    room, _, err = _resolve(room_id, 'responder')
    if err:
        return err
    try:
        folder = wd.move_folder(room, folder_id, _body().get('parent_id'))
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success({'id': folder.id, 'name': folder.name, 'parent_id': folder.parent_id})


@war_room_datastore_blueprint.route('/war-rooms/<int:room_id>/datastore/folders/<int:folder_id>',
                                    methods=['DELETE'])
@ac_room_api_requires()
def delete_room_datastore_folder(room_id, folder_id):
    room, role, err = _resolve(room_id, 'responder')
    if err:
        return err
    uid, gid = _ctx()
    try:
        moved_folders, moved_files = wd.delete_folder(room, folder_id, user_id=uid, guest_id=gid,
                                                      is_lead=role == 'lead')
    except BusinessProcessingError as e:
        return _err(e)
    return response_api_success({'deleted': folder_id, 'moved_folders': moved_folders, 'moved_files': moved_files})

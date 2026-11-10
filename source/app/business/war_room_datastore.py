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

"""A war room's datastore (iris-ng, 2026-11-10): its own folders and files, plus the Stream's attachments as a
read-only folder.

Maintainer's rules: by role, guests like responders. Observers browse and download; responders, leads and portal
guests upload, edit (name, description, tags, contents) and move; deleting a file or folder is for whoever created it
or a lead; a closed room's datastore is read-only. Copying a file to an attached case needs full access to that case
(never a guest). The REST layer resolves the role; this module enforces what depends on the row.

Deleting a folder moves what it holds up one level (the room-notes rule): nothing is deleted with a folder.
Files live under DATASTORE_PATH/war-rooms/room-<id>/datastore/, which a room's deletion removes with the rest of the
room's files.
"""

import hashlib
import os
import shutil
import unicodedata
import uuid
from datetime import datetime

from sqlalchemy import desc
from sqlalchemy import func
from sqlalchemy import or_

import app
from app import db
from app.business.errors import BusinessProcessingError
from app.models import war_room_datastore_vocab as dv
from app.models import war_room_stream_vocab as sv
from app.models.models import WarRoomDsFile
from app.models.models import WarRoomDsFolder
from app.models.models import WarRoomFile
from app.models.models import WarRoomMessage

_MISSING = object()


class DatastoreError(BusinessProcessingError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.utcnow()


def _writable(room):
    if room.status == 'closed':
        raise DatastoreError('The room is closed: its datastore is read-only')


def _id(value, what):
    if isinstance(value, bool):
        raise DatastoreError('%s not found' % what, status=404)
    try:
        return int(value)
    except (TypeError, ValueError):
        raise DatastoreError('%s not found' % what, status=404)


# ------------------------------------------------------------------------------------------ storage

def files_dir(room_id):
    from app.business.war_room_stream import room_files_dir
    return room_files_dir(room_id) / 'datastore'


def file_path(f):
    return files_dir(f.room_id) / ('wrd-%s' % f.file_uuid)


def _store(room, upload):
    """Write one werkzeug FileStorage under the room's datastore folder: (uuid, name, mime, size, sha256)."""
    if upload is None or not getattr(upload, 'filename', None):
        raise DatastoreError('No file')
    from app.business.war_room_stream import clean_filename
    name = clean_filename(upload.filename)
    folder = files_dir(room.id)
    folder.mkdir(parents=True, exist_ok=True)
    fid = uuid.uuid4()
    tmp = folder / ('.upload-%s' % fid)
    digest, size, head = hashlib.sha256(), 0, b''
    try:
        with open(tmp, 'wb') as out:
            while True:
                chunk = upload.stream.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > dv.DS_FILE_MAX_BYTES:
                    raise DatastoreError('A file can be %d MB at most' % (dv.DS_FILE_MAX_BYTES // (1024 * 1024)),
                                         status=413)
                if len(head) < 16:
                    head += chunk[:16 - len(head)]
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise DatastoreError('The file is empty')
        os.replace(tmp, folder / ('wrd-%s' % fid))
    finally:
        if tmp.exists():
            tmp.unlink()
    return fid, name, sv.image_type(head) or 'application/octet-stream', size, digest.hexdigest()


def _unlink(path):
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        app.app.logger.exception('war-room datastore file %s not removed', path)


# ------------------------------------------------------------------------------------------- text

def _clean_text(raw, limit, label):
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise DatastoreError('%s must be text' % label)
    text_ = raw.strip()
    if len(text_) > limit:
        raise DatastoreError('%s can be %d characters at most' % (label, limit))
    return text_ or None


def clean_tags(raw):
    """Comma-separated tags: trimmed, blanks and repeats dropped (ignoring case), at most DS_TAGS_MAX characters."""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        raw = ','.join(str(t) for t in raw)
    if not isinstance(raw, str):
        raise DatastoreError('Tags must be text')
    seen, out = set(), []
    for tag in raw.split(','):
        tag = ' '.join(tag.split())
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    joined = ','.join(out)
    if len(joined) > dv.DS_TAGS_MAX:
        raise DatastoreError('Tags can be %d characters at most' % dv.DS_TAGS_MAX)
    return joined or None


def clean_folder_name(raw):
    if not isinstance(raw, str):
        raise DatastoreError('A folder needs a name')
    name = ''.join(ch for ch in raw if not unicodedata.category(ch).startswith('C')).strip()
    if not name:
        raise DatastoreError('A folder needs a name')
    if len(name) > dv.DS_FOLDER_NAME_MAX:
        raise DatastoreError('A folder name can be %d characters at most' % dv.DS_FOLDER_NAME_MAX)
    return name


def clean_file_name(raw):
    if not isinstance(raw, str) or not raw.strip():
        raise DatastoreError('A file needs a name')
    from app.business.war_room_stream import clean_filename
    return clean_filename(raw)


# ----------------------------------------------------------------------------------------- folders

def _folders(room):
    return {f.id: f for f in WarRoomDsFolder.query.filter_by(room_id=room.id).all()}


def get_folder(room, folder_id):
    """None for the room's top level ('root', '' or None); else the room's folder, or a 404."""
    if folder_id is None or folder_id == '' or folder_id == dv.ROOT:
        return None
    folder = db.session.get(WarRoomDsFolder, _id(folder_id, 'Folder'))
    if folder is None or folder.room_id != room.id:
        raise DatastoreError('Folder not found', status=404)
    return folder


def _depth(folder_id, folders):
    """1 for a top-level folder; 0 for the top level itself."""
    depth, cur, seen = 0, folder_id, set()
    while cur is not None and cur in folders and cur not in seen:
        seen.add(cur)
        depth += 1
        cur = folders[cur].parent_id
    return depth


def _height(folder_id, folders, _guard=0):
    """Levels of folders from this one down (1 = it has no subfolder)."""
    if _guard > dv.DS_DEPTH_MAX + 2:
        return 1
    kids = [f.id for f in folders.values() if f.parent_id == folder_id]
    return 1 + max((_height(k, folders, _guard + 1) for k in kids), default=0)


def _sibling_names(folders, parent_id, exclude_id=None):
    return {f.name.lower() for f in folders.values() if f.parent_id == parent_id and f.id != exclude_id}


def _unique_name(name, taken):
    if name.lower() not in taken:
        return name
    n = 2
    while ('%s (%d)' % (name, n)).lower() in taken:
        n += 1
    return '%s (%d)' % (name, n)


def create_folder(room, raw_name, parent_id=None, user_id=None, guest_id=None):
    _writable(room)
    name = clean_folder_name(raw_name)
    parent = get_folder(room, parent_id)
    folders = _folders(room)
    if len(folders) >= dv.DS_FOLDERS_MAX:
        raise DatastoreError('A room can hold %d folders at most' % dv.DS_FOLDERS_MAX)
    pid = parent.id if parent is not None else None
    if _depth(pid, folders) + 1 > dv.DS_DEPTH_MAX:
        raise DatastoreError('Folders can be nested %d deep at most' % dv.DS_DEPTH_MAX)
    if name.lower() in _sibling_names(folders, pid):
        raise DatastoreError('A folder named "%s" already exists here' % name, status=409)
    folder = WarRoomDsFolder(room_id=room.id, parent_id=pid, name=name, created_by=user_id,
                             created_by_guest_id=guest_id)
    db.session.add(folder)
    db.session.commit()
    return folder


def rename_folder(room, folder_id, raw_name):
    _writable(room)
    folder = get_folder(room, folder_id)
    if folder is None:
        raise DatastoreError('The top level cannot be renamed')
    name = clean_folder_name(raw_name)
    if name.lower() in _sibling_names(_folders(room), folder.parent_id, exclude_id=folder.id):
        raise DatastoreError('A folder named "%s" already exists here' % name, status=409)
    folder.name = name
    db.session.commit()
    return folder


def move_folder(room, folder_id, parent_id):
    _writable(room)
    folder = get_folder(room, folder_id)
    if folder is None:
        raise DatastoreError('The top level cannot be moved')
    parent = get_folder(room, parent_id)
    folders = _folders(room)
    pid = parent.id if parent is not None else None
    cur, seen = pid, set()
    while cur is not None and cur in folders and cur not in seen:
        if cur == folder.id:
            raise DatastoreError('A folder cannot go inside itself')
        seen.add(cur)
        cur = folders[cur].parent_id
    if _depth(pid, folders) + _height(folder.id, folders) > dv.DS_DEPTH_MAX:
        raise DatastoreError('Folders can be nested %d deep at most' % dv.DS_DEPTH_MAX)
    if folder.name.lower() in _sibling_names(folders, pid, exclude_id=folder.id):
        raise DatastoreError('A folder named "%s" already exists there' % folder.name, status=409)
    folder.parent_id = pid
    db.session.commit()
    return folder


def can_delete_folder(folder, user_id=None, guest_id=None, is_lead=False):
    if is_lead:
        return True
    if guest_id is not None:
        return folder.created_by_guest_id == guest_id
    return user_id is not None and folder.created_by == user_id


def delete_folder(room, folder_id, user_id=None, guest_id=None, is_lead=False):
    """Its creator or a lead. What it holds moves up one level (a subfolder whose name is taken there gets a
    numbered name); returns (folders moved, files moved)."""
    _writable(room)
    folder = get_folder(room, folder_id)
    if folder is None:
        raise DatastoreError('The top level cannot be deleted')
    if not can_delete_folder(folder, user_id, guest_id, is_lead):
        raise DatastoreError('Only the person who created this folder, or a lead, can delete it', status=403)
    folders = _folders(room)
    parent_id = folder.parent_id
    taken = _sibling_names(folders, parent_id, exclude_id=folder.id)
    kids = sorted((f for f in folders.values() if f.parent_id == folder.id), key=lambda f: f.id)
    files = WarRoomDsFile.query.filter_by(room_id=room.id, folder_id=folder.id).all()
    from app.business.war_room_activity import quiet
    with quiet(db.session):     # one activity line for the deletion, not one per item moved up
        for kid in kids:
            kid.name = _unique_name(kid.name, taken)
            taken.add(kid.name.lower())
            kid.parent_id = parent_id
        for f in files:
            f.folder_id = parent_id
        db.session.flush()
    db.session.delete(folder)
    db.session.commit()
    return len(kids), len(files)


def tree(room):
    """Every folder with its file count, the top level's count and the Stream attachments' count."""
    folders = sorted(_folders(room).values(), key=lambda f: (f.name.lower(), f.id))
    counts = dict(db.session.query(WarRoomDsFile.folder_id, func.count())
                  .filter(WarRoomDsFile.room_id == room.id).group_by(WarRoomDsFile.folder_id).all())
    return {
        'folders': [{'id': f.id, 'name': f.name, 'parent_id': f.parent_id, 'file_count': counts.get(f.id, 0),
                     'created_by': f.created_by, 'created_by_guest_id': f.created_by_guest_id}
                    for f in folders],
        'root_count': counts.get(None, 0),
        'stream_count': len(stream_files(room)),
    }


# ------------------------------------------------------------------------------------------- files

def get_file(room, file_id):
    f = db.session.get(WarRoomDsFile, _id(file_id, 'File'))
    if f is None or f.room_id != room.id:
        raise DatastoreError('File not found', status=404)
    return f


def stored_path(f):
    path = file_path(f)
    if not path.is_file():
        raise DatastoreError('File not found', status=404)
    return path


def upload(room, upload_, folder_id=None, description=None, tags=None, user_id=None, guest_id=None):
    _writable(room)
    folder = get_folder(room, folder_id)
    description = _clean_text(description, dv.DS_DESCRIPTION_MAX, 'The description')
    tags = clean_tags(tags)
    fid, name, mime, size, sha = _store(room, upload_)
    row = WarRoomDsFile(room_id=room.id, folder_id=folder.id if folder is not None else None, file_uuid=fid,
                        filename=name, mime_type=mime, size=size, sha256=sha, description=description, tags=tags,
                        uploaded_by=user_id, uploaded_by_guest_id=guest_id)
    db.session.add(row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        _unlink(files_dir(room.id) / ('wrd-%s' % fid))
        raise
    return row


def update_file(room, file_id, filename=_MISSING, description=_MISSING, tags=_MISSING, user_id=None, guest_id=None):
    """Name, description and tags; any responder (the maintainer's 'edit and move')."""
    _writable(room)
    f = get_file(room, file_id)
    if filename is not _MISSING:
        f.filename = clean_file_name(filename)
    if description is not _MISSING:
        f.description = _clean_text(description, dv.DS_DESCRIPTION_MAX, 'The description')
    if tags is not _MISSING:
        f.tags = clean_tags(tags)
    f.updated_at, f.updated_by, f.updated_by_guest_id = _now(), user_id, guest_id
    db.session.commit()
    return f


def replace_file(room, file_id, upload_, user_id=None, guest_id=None):
    """New contents under the same entry (its name follows the new file); the old bytes go once the row moved."""
    _writable(room)
    f = get_file(room, file_id)
    old = file_path(f)
    fid, name, mime, size, sha = _store(room, upload_)
    f.file_uuid, f.filename, f.mime_type, f.size, f.sha256 = fid, name, mime, size, sha
    f.updated_at, f.updated_by, f.updated_by_guest_id = _now(), user_id, guest_id
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        _unlink(files_dir(room.id) / ('wrd-%s' % fid))
        raise
    _unlink(old)
    return f


def move_file(room, file_id, folder_id, user_id=None, guest_id=None):
    _writable(room)
    f = get_file(room, file_id)
    folder = get_folder(room, folder_id)
    f.folder_id = folder.id if folder is not None else None
    f.updated_at, f.updated_by, f.updated_by_guest_id = _now(), user_id, guest_id
    db.session.commit()
    return f


def can_delete_file(f, user_id=None, guest_id=None, is_lead=False):
    if is_lead:
        return True
    if guest_id is not None:
        return f.uploaded_by_guest_id == guest_id
    return user_id is not None and f.uploaded_by == user_id


def delete_file(room, file_id, user_id=None, guest_id=None, is_lead=False):
    _writable(room)
    f = get_file(room, file_id)
    if not can_delete_file(f, user_id, guest_id, is_lead):
        raise DatastoreError('Only the person who uploaded this file, or a lead, can delete it', status=403)
    path = file_path(f)
    db.session.delete(f)
    db.session.commit()
    _unlink(path)


def _like(text_):
    return '%' + text_.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def list_files(room, folder_id=None, q=None):
    """The files of one folder (or the top level), or with `q` every file whose name, description or tags match."""
    query = WarRoomDsFile.query.filter(WarRoomDsFile.room_id == room.id)
    q = (q or '').strip()
    if q:
        pattern = _like(q[:200])
        query = query.filter(or_(WarRoomDsFile.filename.ilike(pattern, escape='\\'),
                                 WarRoomDsFile.description.ilike(pattern, escape='\\'),
                                 WarRoomDsFile.tags.ilike(pattern, escape='\\')))
    else:
        folder = get_folder(room, folder_id)
        if folder is not None:
            query = query.filter(WarRoomDsFile.folder_id == folder.id)
        else:
            query = query.filter(WarRoomDsFile.folder_id.is_(None))
    return query.order_by(func.lower(WarRoomDsFile.filename), WarRoomDsFile.id).limit(dv.DS_FILES_PAGE_MAX).all()


def _names(user_ids, guest_ids):
    from app.models.authorization import User
    from app.models.models import WarRoomGuest
    users = {u.id: u.name for u in User.query.filter(User.id.in_({i for i in user_ids if i}))} if any(user_ids) else {}
    guests = {g.id: g.label for g in WarRoomGuest.query.filter(WarRoomGuest.id.in_({i for i in guest_ids if i}))} \
        if any(guest_ids) else {}
    return users, guests


def file_rows(files):
    users, guests = _names([f.uploaded_by for f in files] + [f.updated_by for f in files],
                           [f.uploaded_by_guest_id for f in files] + [f.updated_by_guest_id for f in files])

    def who(uid, gid):
        if gid:
            return guests.get(gid) or 'former guest'
        if uid:
            return users.get(uid) or 'deleted user'
        return None

    return [{'id': f.id, 'folder_id': f.folder_id, 'filename': f.filename, 'mime_type': f.mime_type,
             'size': f.size, 'sha256': f.sha256, 'description': f.description, 'tags': f.tags,
             'uploaded_by': f.uploaded_by, 'uploaded_by_guest_id': f.uploaded_by_guest_id,
             'uploaded_by_name': who(f.uploaded_by, f.uploaded_by_guest_id),
             'created_at': f.created_at, 'updated_at': f.updated_at,
             'updated_by_name': who(f.updated_by, f.updated_by_guest_id) if f.updated_at else None}
            for f in files]


# ------------------------------------------------------------------------------- Stream attachments

def stream_attachment_ids(room):
    """Ids of the files a live (not deleted) message of the room carries as #[file:<id>|name] tokens."""
    ids = set()
    rows = (db.session.query(WarRoomMessage.content)
            .filter(WarRoomMessage.room_id == room.id, WarRoomMessage.deleted_at.is_(None),
                    WarRoomMessage.content.like('%#[file:%')).all())
    for (content,) in rows:
        for m in sv.FILE_TOKEN_RE.finditer(content or ''):
            ids.add(int(m.group(1)))
    return ids


def stream_files(room):
    ids = stream_attachment_ids(room)
    if not ids:
        return []
    return (WarRoomFile.query.filter(WarRoomFile.room_id == room.id, WarRoomFile.id.in_(ids))
            .order_by(desc(WarRoomFile.id)).all())


def get_stream_file(room, file_id):
    fid = _id(file_id, 'File')
    if fid not in stream_attachment_ids(room):
        raise DatastoreError('File not found', status=404)
    f = db.session.get(WarRoomFile, fid)
    if f is None or f.room_id != room.id:
        raise DatastoreError('File not found', status=404)
    return f


def stream_rows(files):
    users, guests = _names([f.uploaded_by for f in files], [f.uploaded_by_guest_id for f in files])
    return [{'id': f.id, 'filename': f.filename, 'mime_type': f.mime_type, 'size': f.size, 'sha256': f.sha256,
             'uploaded_by_name': (guests.get(f.uploaded_by_guest_id) or 'former guest') if f.uploaded_by_guest_id
             else (users.get(f.uploaded_by) or ('deleted user' if f.uploaded_by else None)),
             'created_at': f.created_at}
            for f in files]


# ------------------------------------------------------------------------------------ copy to a case

def _case_folder(case_id):
    """The case datastore's 'War rooms' folder under its root, made on first use."""
    from app.datamgmt.datastore.datastore_db import datastore_get_root
    from app.models.models import DataStorePath
    root = datastore_get_root(case_id)
    folder = DataStorePath.query.filter(DataStorePath.path_case_id == case_id,
                                        DataStorePath.path_parent_id == root.path_id,
                                        DataStorePath.path_name == dv.CASE_FOLDER_NAME).first()
    if folder is None:
        folder = DataStorePath(path_case_id=case_id, path_parent_id=root.path_id, path_name=dv.CASE_FOLDER_NAME,
                               path_is_root=False)
        db.session.add(folder)
        db.session.flush()
    return folder


def copy_to_case(room, source, file_id, case_id, user):
    """Copy a datastore file or a Stream attachment into an attached case's datastore (folder 'War rooms'); the
    room keeps its copy. The actor needs FULL access to the case."""
    from app.datamgmt.datastore.datastore_db import datastore_get_standard_path
    from app.iris_engine.access_control.utils import ac_fast_check_user_has_case_access
    from app.iris_engine.utils.tracker import track_activity
    from app.models.authorization import CaseAccessLevel
    from app.models.models import DataStoreFile
    from app.models.models import WarRoomCaseLink
    from app.util import add_obj_history_entry
    if source not in dv.COPY_SOURCES:
        raise DatastoreError('Unknown source')
    if source == 'datastore':
        f = get_file(room, file_id)
        path, description, tags = stored_path(f), f.description, f.tags
    else:
        f = get_stream_file(room, file_id)
        from app.business.war_room_stream import file_path as stream_path
        path, description, tags = stream_path(f), None, None
        if not path.is_file():
            raise DatastoreError('File not found', status=404)
    cid = _id(case_id, 'Case')
    if WarRoomCaseLink.query.filter_by(room_id=room.id, case_id=cid).first() is None:
        raise DatastoreError('Case #%d is not attached to this room' % cid)
    if not ac_fast_check_user_has_case_access(user.id, cid, [CaseAccessLevel.full_access]):
        raise DatastoreError('You need full access to case #%d to add files to it' % cid, status=403)
    note = 'Copied from war room WR#%d (%s)' % (room.id, room.name)
    dsf = DataStoreFile(file_original_name=f.filename, file_local_name='tmp_xc',
                        file_description=(note + (': ' + description if description else ''))[:4000],
                        file_tags=tags or '', file_password='', file_is_ioc=False, file_is_evidence=False,
                        file_case_id=cid, file_date_added=datetime.now(), added_by_user_id=user.id,
                        file_parent_id=_case_folder(cid).path_id, file_sha256=f.sha256, file_size=f.size)
    add_obj_history_entry(dsf, 'created', user=user)
    db.session.add(dsf)
    db.session.commit()
    target = datastore_get_standard_path(dsf, cid)
    try:
        shutil.copyfile(path, target)
    except OSError:
        db.session.delete(dsf)
        db.session.commit()
        raise DatastoreError('The file could not be copied', status=500)
    dsf.file_local_name = target.as_posix()
    db.session.commit()
    track_activity('File "%s" copied from war room WR#%d to the datastore' % (f.filename, room.id), caseid=cid)
    return dsf

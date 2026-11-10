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

"""War-room categories, archive and datastore: the one vocabulary (iris-ng, 2026-11-10). Import-free.

Categories: one shared list, a room is filed under at most one. Archive: a flag beside the state (a room keeps its
state, open or closed, while archived). Datastore: the room's own folders and files; the Stream's attachments show
in it as a read-only folder.
"""

CATEGORY_NAME_MAX = 64
CATEGORIES_MAX = 200

DS_FILE_MAX_BYTES = 100 * 1024 * 1024       # nginx's client_max_body_size for every server, the portal's included
DS_FILE_NAME_MAX = 200
DS_FOLDER_NAME_MAX = 120
DS_FOLDERS_MAX = 500                         # per room
DS_DEPTH_MAX = 8                             # folders inside folders
DS_DESCRIPTION_MAX = 2000
DS_TAGS_MAX = 500
DS_FILES_PAGE_MAX = 500
DS_UPLOAD_FILES_MAX = 20                     # files in one upload request

# The folder selectors of the file list: a folder id, the room's top level, or the Stream's attachments.
ROOT = 'root'
STREAM = 'stream'

# Where a copy lands in a case's datastore (a folder under the case's root, created on first use).
CASE_FOLDER_NAME = 'War rooms'

# The two sources a file can be copied to a case from.
COPY_SOURCES = ('datastore', 'stream')

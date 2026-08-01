#  IRIS Source Code
#  Copyright (C) 2021 - Airbus CyberSecurity (SAS)
#  contact@dfir-iris.org
#  Created by Lukas Zurschmiede @LukyLuke
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
import logging
import os
import shutil
import uuid
import re

from pathlib import Path
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docxtpl import DocxTemplate

from docx_generator.globals.picture_globals import PictureGlobals

from app.datamgmt.datastore.datastore_db import datastore_get_local_file_path


def _patch_picture_globals_alignment():
    """Monkeypatch docx_generator's PictureGlobals.__init__ for python-docx >= 1.x.

    docx_generator (Airbus, last released 2021) builds its alignment table with::

        for member in WD_PARAGRAPH_ALIGNMENT.__members__:
            self._available_alignment_values.append(member.name)

    On python-docx >= 1.x, ``EnumMeta.__members__`` is a ``mappingproxy`` whose
    iteration yields the member *names as plain strings*, so ``member.name`` raises
    ``AttributeError: 'str' object has no attribute 'name'`` and every report
    generation 500s. docx_generator instantiates ``PictureGlobals`` directly during
    rendering (``globals/globals.py``), so subclassing ImageHandler alone is not
    enough — we patch the base class once, at import time, idempotently.
    """
    if getattr(PictureGlobals, '_iris_alignment_patched', False):
        return

    _original_init = PictureGlobals.__init__

    def _patched_init(self, template, base_path):
        self._template = template
        self._base_path = base_path
        self._output_path = os.path.join(base_path, 'tmp', 'images')
        # list(mappingproxy) yields the member names as strings on every
        # python-docx version — exactly the list the original loop intended.
        self._available_alignment_values = list(WD_PARAGRAPH_ALIGNMENT.__members__)
        self._logger = logging.getLogger('docx_generator.globals.picture_globals')

    PictureGlobals.__init__ = _patched_init
    PictureGlobals._iris_alignment_patched = True


_patch_picture_globals_alignment()


class ImageHandler(PictureGlobals):
    def __init__(self, template: DocxTemplate, base_path: str):
        # NOTE: We intentionally do NOT call PictureGlobals.__init__ here.
        # docx_generator (last released 2021) builds its alignment table with
        #   for member in WD_PARAGRAPH_ALIGNMENT.__members__:
        #       self._available_alignment_values.append(member.name)
        # On python-docx >= 1.x, EnumMeta.__members__ is a mappingproxy whose
        # iteration yields the member *names* as plain strings, so member.name
        # raises "AttributeError: 'str' object has no attribute 'name'" and any
        # report generation 500s. We replicate the parent's setup here with a
        # version-agnostic alignment loop. Keep the rest of the assignments in
        # sync with PictureGlobals.__init__ on dependency upgrades.
        self._template = template
        self._base_path = base_path
        self._output_path = os.path.join(base_path, 'tmp', 'images')

        self._available_alignment_values = list(WD_PARAGRAPH_ALIGNMENT.__members__)

        self._logger = logging.getLogger(__name__)

    def _process_remote(self, image_path: str) -> str:
        """
        Checks if the given Link is a datastore-link and if so, save the image locally for further processing.
        :
        A Datastore Links looks like this: https://localhost:4433/datastore/file/view/2?cid=1
        """
        res = re.search(r'datastore\/file\/view\/(\d+)\?cid=(\d+)', image_path)
        if not res:
            return super()._process_remote(image_path)

        if image_path[:4] == 'http' and len(res.groups()) == 2:
            file_id = res.groups(0)[0]
            case_id = res.groups(0)[1]
            has_error, dsf = datastore_get_local_file_path(file_id, case_id)

            if has_error:
                raise RenderingError(self._logger, f'File-ID {file_id} does not exist in Case {case_id}')
            if not Path(dsf.file_local_name).is_file():
                raise RenderingError(self._logger, f'File {dsf.file_local_name} does not exists on the server. Update or delete virtual entry')

            file_ext = os.path.splitext(dsf.file_original_name)[1]
            file_name = os.path.join(self._output_path, str(uuid.uuid4())) + file_ext
            return_value = shutil.copy(dsf.file_local_name, file_name)
            return return_value
        return super()._process_remote(image_path)

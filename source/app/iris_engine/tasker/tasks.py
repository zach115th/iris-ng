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

# IMPORTS ------------------------------------------------
import os
import urllib.parse
from celery.signals import task_prerun
from celery.signals import worker_process_init
from flask_login import current_user

from app import app
from app import db
from app.datamgmt.case.case_db import get_case
from app.iris_engine.module_handler.module_handler import pipeline_dispatcher
from app.iris_engine.utils.common import build_upload_path
from app.iris_engine.utils.tracker import track_activity
from iris_interface import IrisInterfaceStatus as IStatus
from iris_interface.IrisModuleInterface import IrisPipelineTypes

app.config['timezone'] = 'Europe/Paris'


# CONTENT ------------------------------------------------
@worker_process_init.connect
def on_worker_process_init(*args, **kwargs):
    # Fork-safety, the PRIMARY fix — fires ONCE in each prefork child right
    # after fork(), before any task runs.
    #
    # Celery's default prefork pool fork()s N worker children that all inherit
    # the SAME live psycopg2 connection fd from the parent. Postgres connections
    # are NOT fork-safe, and worse, sibling children sharing one inherited fd
    # corrupt each other's protocol state when they run concurrently — so a
    # commit in core task_hook_wrapper (module_handler.py:465) crashes with
    # `(psycopg2.DatabaseError) error with status PGRES_TUPLES_OK and no message
    # from the libpq`. This manifested as one hook task succeeding and a sibling
    # task on the SAME hook failing, ~40ms apart, because they landed in two
    # children racing on the inherited connection.
    #
    # Disposing the engine pool here, once per child at fork time, guarantees
    # each child lazily opens its OWN connections and never touches the parent's
    # inherited fd. This is the documented SQLAlchemy + os.fork() fix:
    # https://docs.sqlalchemy.org/en/20/core/pooling.html#using-connection-pools-with-multiprocessing-or-os-fork
    # `worker_process_init` (per-child, post-fork) is the correct hook for this;
    # the per-task `task_prerun` below alone could not fix the sibling-race
    # because the fd was already shared by the time the first task started.
    try:
        db.session.remove()
    except Exception:
        pass
    db.engine.dispose()


@task_prerun.connect
def on_task_init(*args, **kwargs):
    # Defense-in-depth on top of on_worker_process_init above: drop the scoped
    # session + recycle the pool before each task too. `engine.dispose()` alone
    # recycles the POOL but a scoped session that already checked out a
    # connection keeps that fd, so remove the session first, then dispose.
    try:
        db.session.remove()
    except Exception:
        pass
    db.engine.dispose()


def task_case_update(module, pipeline, pipeline_args, caseid):
    """
    Update the current case of the current user with fresh data.
    The files should have already been uploaded.
    :return: Tuple (success, errors)
    """
    errors = []
    case = get_case(caseid=caseid)

    if case:
        # We have a case so we can update the current case

        # Build the upload path where the files should be
        fpath = build_upload_path(case_customer=case.client.name,
                                  case_name=urllib.parse.unquote(case.name),
                                  module=module)

        # Check the path is valid and exists
        if fpath:
            if os.path.isdir(fpath):
                # Build task args
                task_args = {
                    "pipeline_args": pipeline_args,
                    "db_name": '',
                    "user": current_user.name,
                    "user_id": current_user.id,
                    "case_name": case.name,
                    "case_id": case.case_id,
                    "path": fpath,
                    "is_update": True
                }

                track_activity("started a new analysis import with pipeline {}".format(pipeline))

                pipeline_dispatcher.delay(module_name=module,
                                          hook_name=IrisPipelineTypes.pipeline_type_update,
                                          pipeline_type=IrisPipelineTypes.pipeline_type_update,
                                          pipeline_data=task_args,
                                          init_user=current_user.name,
                                          caseid=caseid)

                return IStatus.I2Success('Pipeline task queued')

            return IStatus.I2FileNotFound("Built path was not found ")

        return IStatus.I2UnexpectedResult("Unable to build path")

    else:
        # The user do not have any context so we cannot update
        # Return an error
        errors.append('Current user does not have a valid case in context')
        return IStatus.I2UnexpectedResult("Invalid context")


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

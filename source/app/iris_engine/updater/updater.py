#  IRIS Core Code
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

# What is left of the in-app updater: the release check and the daily task that
# records its answer. Installing an update from the UI (download, signature
# check, file copy and restart) was retired; updates go through the host-side
# scripts/update.sh.

import re
import requests
from celery.schedules import crontab
from packaging import version

from app import app
from app import cache
from app import celery
from app import db
from app.datamgmt.manage.manage_srv_settings_db import get_server_settings_as_dict
from app.models.models import ServerSettings
from iris_interface import IrisInterfaceStatus as IStatus

log = app.logger

# iris-ng version strings look like "IRIS-NG-v1.0.3", which is NOT valid PEP 440 -
# the leading product name has no equivalent in the spec. packaging 21.3 tolerated
# it by returning a LegacyVersion, but packaging 22.0 REMOVED LegacyVersion and
# parse() now raises InvalidVersion instead. Strip the prefix so packaging sees a
# real version and the comparison is genuine PEP 440 ordering rather than legacy
# string handling. GitHub release names carry the same prefix, so both sides of
# every comparison need it.
_IRIS_VERSION_PREFIX_RE = re.compile(r'^IRIS-NG-v', re.IGNORECASE)


def parse_iris_version(raw):
    """Parse an iris-ng version string, tolerating the IRIS-NG-v prefix."""
    return version.parse(_IRIS_VERSION_PREFIX_RE.sub('', (raw or '0').strip()))


def get_external_url(url):
    server_settings = get_server_settings_as_dict()
    proxies = server_settings.get('proxies')
    try:
        request = requests.get(url, proxies=proxies)
    except Exception as e:
        app.logger.error(e)
        return None

    return request


def get_latest_release():

    try:
        releases = get_external_url(app.config.get('RELEASE_URL'))
    except Exception as e:
        app.logger.error(e)
        return True, {'message': f"Unexpected error. {str(e)}"}

    if not releases:
        return True, {'message': "Unexpected error"}

    if releases.status_code == 200:
        releases_j = releases.json()

        return False, releases_j[0]

    if releases.status_code == 403:
        return True, releases.json()

    return True, {'msg': "Unexpected error"}


def is_updates_available():
    has_error, release = get_latest_release()

    current_version = app.config.get('IRIS_VERSION')

    if has_error:
        return False, release.get('message'), None

    release_version = release.get('name')

    cache.delete('iris_has_updates')

    srv_settings = ServerSettings.query.first()
    if not srv_settings:
        raise Exception('Unable to fetch server settings. Please reach out for help')

    if parse_iris_version(current_version) < parse_iris_version(release_version):
        srv_settings.has_updates_available = True
        db.session.commit()
        return True, f'# New version {release_version} available\n\n{release.get("body")}', release

    else:
        srv_settings.has_updates_available = False
        db.session.commit()
        return False, f'**Current server is up-to-date with {release_version}**', None


@celery.on_after_finalize.connect
def setup_periodic_update_checks(self, **kwargs):
    self.add_periodic_task(
        crontab(hour=0, minute=0),
        task_check_available_updates.s(),
        name='iris_auto_check_updates'
    )


def remove_periodic_update_checks():
    if 'iris_auto_check_updates' in celery.conf['beat_schedule']:
        del celery.conf['beat_schedule']['iris_auto_check_updates']


@celery.task
def task_check_available_updates():
    log.info('Cron - Checking if updates are available')
    has_updates, _, _ = is_updates_available()
    srv_settings = ServerSettings.query.first()
    if not srv_settings:
        return IStatus.I2Error('Unable to fetch server settings. Please reach out for help')

    srv_settings.has_updates_available = has_updates
    db.session.commit()

    if srv_settings.has_updates_available:
        log.info('Updates are available for this server')

    return IStatus.I2Success(f'Successfully checked updates. Available : {srv_settings.has_updates_available}')

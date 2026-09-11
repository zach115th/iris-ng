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

"""iris-ng: "a newer release is available" check (issue #111).

Reads the project's GitHub *latest release* at runtime and compares its tag
against the running IRIS_VERSION. Consumers:

* GET /api/v2/updates/latest  - the banner strip on every page (all users)
* the sidebar version line     - the small warning icon next to the version
* Settings > System            - the "Check now" button

Design, mirroring iris_engine/sponsor.py (the first component that reached
the public internet on its own — this is the second):

* Never raises. Every failure degrades to "no update known" with an `error`
  field, so a proxied or air-gapped deployment renders nothing rather than a
  broken page. `enable_updates_check` on server_settings turns the outbound
  call off entirely (NULL — the pre-existing rows — means ON).
* Cached in-process for CACHE_TTL, per gunicorn worker, so a page fleet of
  analysts costs at most one request per worker per TTL against GitHub's
  60/hour unauthenticated ceiling. `force=True` bypasses the cache and is
  reserved for administrators at the endpoint.
* The comparison is real PEP 440 ordering via the updater's
  parse_iris_version (which strips the `IRIS-NG-v` prefix). A tag that does
  not parse is NEVER reported as an update — "newer" is a claim, not a guess.
* Release notes are rendered server-side through render_markdown_safe and
  capped, so the banner injects nothing GitHub could have carried raw.
* `releases/latest` excludes drafts and prereleases by GitHub's own contract.
"""
from datetime import datetime
from datetime import timedelta
import logging
import re
from urllib.parse import quote

import requests

from app import app

log = logging.getLogger(__name__)

# Derived from the (config.ini / env) RELEASE_URL the upstream updater already
# reads, so one key points both the legacy check and this one at the same
# repository. RELEASE_URL is the /releases LIST endpoint; /latest hangs off it.
REPO_RELEASES_FALLBACK = 'https://api.github.com/repos/zach115th/iris-ng/releases'
RELEASE_PAGE_FALLBACK = 'https://github.com/zach115th/iris-ng/releases/tag/{tag}'

# Kept short: the endpoint is called by the banner script on every page load
# that misses the cache, and a slow GitHub must never hold a worker for long.
REQUEST_TIMEOUT = 5
CACHE_TTL = timedelta(hours=6)
# Release bodies are short on this project (a heading + links + image tags),
# but cap the rendered notes so a long-winded release cannot turn the strip
# into a wall.
NOTES_MAX_CHARS = 2500

_TAG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+-]{0,99}$')

_cache = {'at': None, 'value': None}


def _latest_url() -> str:
    base = (app.config.get('RELEASE_URL') or REPO_RELEASES_FALLBACK).rstrip('/')
    return base + '/latest'


def _proxies() -> dict:
    """Honour the proxies configured on the Server Settings General tab."""
    try:
        from app.datamgmt.manage.manage_srv_settings_db import get_srv_settings
        settings = get_srv_settings()
        proxies = {}
        if settings and settings.http_proxy:
            proxies['http'] = settings.http_proxy
        if settings and settings.https_proxy:
            proxies['https'] = settings.https_proxy
        return proxies
    except Exception:
        return {}


def is_check_enabled() -> bool:
    """The admin toggle. NULL (rows predating the toggle's UI) means enabled."""
    try:
        from app.datamgmt.manage.manage_srv_settings_db import get_srv_settings
        settings = get_srv_settings()
    except Exception:
        return True
    if settings is None:
        return True
    return settings.enable_updates_check is not False


def is_newer(candidate: str, current: str) -> bool:
    """True only when BOTH parse and candidate > current. Unparseable = False."""
    # Lazy: the updater module pulls gnupg/celery/socket_io at import time and
    # this module is imported by a context processor early in app wiring.
    from app.iris_engine.updater.updater import parse_iris_version
    try:
        return parse_iris_version(candidate) > parse_iris_version(current)
    except Exception:
        return False


def _release_page_url(tag: str, html_url) -> str:
    """The release page. GitHub's html_url is used only when it is GitHub's."""
    if isinstance(html_url, str) and html_url.startswith('https://github.com/'):
        return html_url
    return RELEASE_PAGE_FALLBACK.format(tag=quote(tag, safe=''))


def parse_release(payload: dict) -> dict:
    """Reduce a GitHub release object to what the UI needs. Raises on junk."""
    if not isinstance(payload, dict):
        raise ValueError('release payload is not an object')
    tag = str(payload.get('tag_name') or '').strip()
    if not _TAG_RE.match(tag):
        raise ValueError('release has no usable tag_name')

    from app.iris_engine.safe_markdown import render_markdown_safe
    body = payload.get('body') or ''
    if not isinstance(body, str):
        body = ''
    truncated = len(body) > NOTES_MAX_CHARS
    if truncated:
        body = body[:NOTES_MAX_CHARS].rsplit('\n', 1)[0]

    return {
        'tag': tag,
        'name': str(payload.get('name') or tag),
        'url': _release_page_url(tag, payload.get('html_url')),
        'published_at': payload.get('published_at') if isinstance(payload.get('published_at'), str) else None,
        'notes_html': render_markdown_safe(body),
        'notes_truncated': truncated,
    }


def _base(enabled: bool) -> dict:
    return {
        'enabled': enabled,
        'current_version': app.config.get('IRIS_VERSION'),
        'update_available': False,
        'latest': None,
        'error': None,
        'fetched_at': None,
        'source_url': _latest_url(),
        'cached': False,
        'stale': False,
    }


def get_update_state(force: bool = False) -> dict:
    """Latest-release state for the UI. Never raises.

    Returns {'enabled', 'current_version', 'update_available', 'latest',
             'error', 'fetched_at', 'source_url', 'cached', 'stale'}.
    `latest` is None until a fetch has succeeded on this worker.
    """
    enabled = is_check_enabled()
    if not enabled:
        # No outbound call, and no stale value served either: the admin said
        # "do not phone home", so a previously cached answer must not leak
        # through as if the check were still running.
        return _base(False)

    now = datetime.utcnow()
    if not force and _cache['at'] and (now - _cache['at']) < CACHE_TTL and _cache['value']:
        return {**_cache['value'], 'cached': True}

    result = _base(True)
    try:
        response = requests.get(
            _latest_url(),
            timeout=REQUEST_TIMEOUT,
            proxies=_proxies(),
            headers={
                'Accept': 'application/vnd.github+json',
                'User-Agent': f'iris-ng/{app.config.get("IRIS_VERSION")}',
            },
        )
        response.raise_for_status()
        latest = parse_release(response.json())
    except Exception as exc:
        # Deliberately soft: a nice-to-have banner must not be able to break a
        # page or leak a stack trace into it.
        log.warning('Could not check for a newer iris-ng release: %s', exc)
        result['error'] = 'Could not reach GitHub to check for a newer release.'
        if _cache['value'] and _cache['value'].get('latest'):
            # Serve the last good answer rather than nothing.
            return {**_cache['value'], 'error': result['error'], 'cached': True, 'stale': True}
        return result

    result['latest'] = latest
    result['update_available'] = is_newer(latest['tag'], result['current_version'])
    result['fetched_at'] = now.isoformat() + 'Z'

    _cache['at'] = now
    _cache['value'] = result
    return result


def peek_update_state() -> dict:
    """What THIS worker already knows, with NO outbound call.

    For synchronous render paths (the sidebar's context processor): a page
    must never wait on the public internet. Until the banner script has made
    the first request on this worker, this reports no update — which is the
    honest answer, not a claim that there is none.
    """
    if not _cache['value']:
        return {'update_available': False, 'latest': None}
    if not is_check_enabled():
        return {'update_available': False, 'latest': None}
    value = _cache['value']
    return {'update_available': bool(value.get('update_available')), 'latest': value.get('latest')}


def reset_cache() -> None:
    """Test hook + used when the admin flips the toggle."""
    _cache['at'] = None
    _cache['value'] = None

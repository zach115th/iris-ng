#  IRIS Source Code
#  iris-next
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

"""iris-next: sponsor links, read from the project's GitHub FUNDING.yml.

GitHub's FUNDING.yml is the single source of truth, fetched at runtime so
editing it upstream updates every instance without a rebuild.

Two consequences of that choice, both handled here rather than at the call site:

* This is the only feature in iris-ng that reaches the public internet on its
  own. Everything degrades to "no links" when it cannot - the caller gets a
  result object, never an exception - so an air-gapped or proxied deployment
  sees an empty panel rather than a broken settings page.
* The response is cached in-process for CACHE_TTL so revisiting the page does
  not re-hit GitHub. The cache is per gunicorn worker, which is fine: the worst
  case is one request per worker per TTL.

The file is deliberately parsed by hand instead of with PyYAML. FUNDING.yml is
a flat `key: value` document with an optional inline list, PyYAML is not
installed in the app image, and adding a dependency (plus an image rebuild) for
one flat file is disproportionate.
"""
from datetime import datetime
from datetime import timedelta
import logging
import re

import requests

log = logging.getLogger(__name__)

FUNDING_URL = 'https://raw.githubusercontent.com/zach115th/iris-ng/main/.github/FUNDING.yml'

# Kept short: this runs while an admin is looking at a settings tab.
REQUEST_TIMEOUT = 5
CACHE_TTL = timedelta(hours=6)

# platform key -> (display name, URL template). Mirrors the platforms GitHub
# itself supports in FUNDING.yml, so adding one later is a YAML edit only.
PLATFORMS = {
    'github':            ('GitHub Sponsors',   'https://github.com/sponsors/{}'),
    'patreon':           ('Patreon',           'https://patreon.com/{}'),
    'open_collective':   ('Open Collective',   'https://opencollective.com/{}'),
    'ko_fi':             ('Ko-fi',             'https://ko-fi.com/{}'),
    'tidelift':          ('Tidelift',          'https://tidelift.com/funding/github/{}'),
    'community_bridge':  ('Community Bridge',  'https://funding.communitybridge.org/projects/{}'),
    'liberapay':         ('Liberapay',         'https://liberapay.com/{}'),
    'issuehunt':         ('IssueHunt',         'https://issuehunt.io/r/{}'),
    'lfx_crowdfunding':  ('LFX Crowdfunding',  'https://crowdfunding.lfx.linuxfoundation.org/projects/{}'),
    'polar':             ('Polar',             'https://polar.sh/{}'),
    'buy_me_a_coffee':   ('Buy Me a Coffee',   'https://buymeacoffee.com/{}'),
    'thanks_dev':        ('thanks.dev',        'https://thanks.dev/u/gh/{}'),
    # `custom` holds whole URLs rather than a username, so it has no template.
    'custom':            ('Website',           None),
}

_cache = {'at': None, 'value': None}


def _strip_comment(value: str) -> str:
    """Drop a trailing ` # comment`.

    Only splits on a hash that follows whitespace, so a '#' inside a value (a
    URL fragment, say) survives.
    """
    return re.split(r'\s+#', value, maxsplit=1)[0].strip()


def _parse_scalar_or_list(value: str):
    """Return [] , [scalar] or the inline list. FUNDING.yml allows both."""
    value = _strip_comment(value)
    if not value:
        return []
    if value.startswith('[') and value.endswith(']'):
        inner = value[1:-1]
        return [v.strip().strip('\'"') for v in inner.split(',') if v.strip().strip('\'"')]
    return [value.strip('\'"')]


def parse_funding(text: str) -> dict:
    """Parse a FUNDING.yml body into {platform_key: [value, ...]}.

    Ignores comments, blank lines and keys with no value — GitHub's template
    ships every supported platform commented out with a placeholder, so most
    lines in a real file are empty keys.
    """
    result = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or ':' not in line:
            continue
        key, _, value = line.partition(':')
        key = key.strip()
        if key not in PLATFORMS:
            continue
        values = _parse_scalar_or_list(value)
        if values:
            result[key] = values
    return result


def _build_links(parsed: dict) -> list:
    links = []
    for key, values in parsed.items():
        label, template = PLATFORMS.get(key, (key, None))
        for value in values:
            if template is None:
                # `custom` entries are already URLs.
                url = value if value.startswith(('http://', 'https://')) else f'https://{value}'
                display = re.sub(r'^https?://', '', url).rstrip('/')
            else:
                url = template.format(value)
                display = value
            links.append({'platform': key, 'label': label, 'url': url, 'display': display})
    return links


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


def get_sponsor_links(force: bool = False) -> dict:
    """Sponsor links for the UI. Never raises.

    Returns {'links': [...], 'error': str|None, 'fetched_at': iso|None,
             'source_url': str, 'cached': bool}
    """
    now = datetime.utcnow()
    if not force and _cache['at'] and (now - _cache['at']) < CACHE_TTL and _cache['value']:
        return {**_cache['value'], 'cached': True}

    result = {
        'links': [],
        'error': None,
        'fetched_at': None,
        'source_url': FUNDING_URL,
    }

    try:
        response = requests.get(FUNDING_URL, timeout=REQUEST_TIMEOUT, proxies=_proxies())
        response.raise_for_status()
        result['links'] = _build_links(parse_funding(response.text))
        result['fetched_at'] = now.isoformat() + 'Z'
    except Exception as exc:
        # Deliberately soft: this is a nice-to-have panel, and it must not be
        # able to break a settings page or leak a stack trace into the UI.
        log.warning('Could not fetch sponsor information: %s', exc)
        result['error'] = 'Could not reach GitHub to load sponsor information.'
        if _cache['value'] and _cache['value'].get('links'):
            # Serve the last good answer rather than nothing.
            stale = {**_cache['value'], 'error': result['error'], 'cached': True, 'stale': True}
            return stale
        return {**result, 'cached': False}

    _cache['at'] = now
    _cache['value'] = result
    return {**result, 'cached': False}

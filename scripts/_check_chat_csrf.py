"""Debug helper: simulate the browser-side CSRF flow against the AI chat
endpoint to isolate where the 400 is coming from.

Logs in with admin creds (read from `IRIS_ADM_USERNAME` / `IRIS_ADM_PASSWORD`
in the project .env), opens the case timeline page, extracts the rendered
csrf_token, and POSTs to /api/v2/cases/<cid>/ai/ask the same way our chat
bar does. Prints the response so we can see whether the token is being
rejected or never reaches the validator.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib3

import requests


def main() -> int:
    urllib3.disable_warnings()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import iris_misp_sync_dev as h  # type: ignore
    h.load_env_file(h.ENV_FILE)

    base = 'https://localhost'
    user = os.environ.get('IRIS_ADM_USERNAME', 'administrator')
    pw = os.environ.get('IRIS_ADM_PASSWORD', '')
    if not pw:
        print('Set IRIS_ADM_PASSWORD in .env (or env) before running.')
        return 1

    s = requests.Session()
    s.verify = False

    r = s.get(f'{base}/login', timeout=15)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    login_csrf = m.group(1) if m else None
    print(f'login csrf: {(login_csrf or "")[:40]}...')

    r = s.post(
        f'{base}/login',
        data={'username': user, 'password': pw, 'csrf_token': login_csrf},
        allow_redirects=False,
        timeout=15
    )
    print(f'login: {r.status_code} -> {r.headers.get("Location")}')

    r = s.get(f'{base}/case/timeline?cid=3', allow_redirects=False, timeout=15)
    print(f'timeline page: {r.status_code}, html len: {len(r.text)}')
    if r.status_code != 200:
        print(f'  unexpected, body head: {r.text[:300]}')
        return 1

    inputs = re.findall(r'<input[^>]*id="csrf_token"[^>]*>', r.text)
    print(f'csrf_token inputs on page: {len(inputs)}')
    for inp in inputs[:5]:
        print(f'  {inp[:200]}')

    m = re.search(r'id="csrf_token"[^>]*value="([^"]+)"', r.text)
    page_csrf = m.group(1) if m else None
    print(f'page csrf: {(page_csrf or "")[:40]}...')

    r = s.post(
        f'{base}/api/v2/cases/3/ai/ask',
        headers={'Content-Type': 'application/json', 'X-CSRFToken': page_csrf or ''},
        data=json.dumps({'question': 'test', 'history': []}),
        allow_redirects=False,
        timeout=120
    )
    print(f'ai/ask: {r.status_code}')
    print(f'  body (first 400): {r.text[:400]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

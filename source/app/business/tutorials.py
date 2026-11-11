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

"""Tutorials (iris-ng 2026-11-10): step-by-step walkthroughs that run on the real pages.

What a tutorial is: models.tutorial_vocab. The built-in ones are files (resources/tutorials/<key>.json); a server's
own version of one, and every team tutorial, is a `tutorial` row. Server administrators edit them; every signed-in
user runs the published ones meant for them (audience 'admins' = server administrators). No new permission.

A run lives on the server (`tutorial_progress`): the pages are full page loads, so each page embeds the running step
(includes/tutorial_assets.html) and the runner (tutorial_runner.js) reports each step it completes. A run keeps a
snapshot of the tutorial taken at its start. Its `run_seq` changes on every start / resume, so a report from a tab
of an older run is refused (409) instead of moving the current one.

Clean-up (`cleanup()`): a step may offer to delete the case or war room the run captured, and only one this user
created after the run started, with the same rights as the normal delete (full case access; room lead)."""

import json
import os
import re
from collections import namedtuple
from datetime import datetime
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from app import app
from app import db
from app.models import tutorial_vocab as V
from app.models.models import Tutorial
from app.models.models import TutorialProgress

Viewer = namedtuple('Viewer', 'user_id admin')

_RES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'resources', 'tutorials')

_ANCHOR_NAME = re.compile(V.ANCHOR_NAME_RE)
_VAR = re.compile(V.VAR_RE)
_CAPTURE = re.compile(V.CAPTURE_PATH_RE)
_PATH = re.compile(V.PATH_RE)
_VAR_REF = re.compile(V.VAR_REF_RE)
_REF = re.compile(V.REF_RE)
_PARAM = re.compile(r'^[A-Za-z0-9_\-]{1,40}$')
_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
# A clean-up may name a case or room created up to this long before the run started (clock and commit skew).
_CLEANUP_SLACK = timedelta(minutes=1)
_CLEANED = '_cleaned'


class TutorialError(Exception):
    def __init__(self, message, status=400, issues=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.issues = issues or []


# ------------------------------------------------------------------ validation

def _text(value, limit, what, issues, required=False, multiline=False):
    if value is None:
        value = ''
    if not isinstance(value, str):
        issues.append('%s: text expected' % what)
        return ''
    value = value.replace('\r\n', '\n').replace('\r', '\n').strip()
    if _CONTROL.search(value):
        issues.append('%s: control characters are not allowed' % what)
    if not multiline and '\n' in value:
        issues.append('%s: one line only' % what)
    if required and not value:
        issues.append('%s is required' % what)
    if len(value) > limit:
        issues.append('%s: at most %d characters' % (what, limit))
    return value


def _refs(text):
    return set(_VAR_REF.findall(text or ''))


def _check_refs(text, known, what, issues):
    for name in sorted(_refs(text) - known):
        issues.append('%s uses {%s}, which no earlier step captures' % (what, name))


def _anchors(value, what, issues, known, required=False):
    if value is None or value == '' or value == []:
        if required:
            issues.append('%s is required' % what)
        return []
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        if not isinstance(item, str):
            issues.append('%s: text expected' % what)
            continue
        item = item.strip()
        if not item:
            continue
        if '\n' in item or _CONTROL.search(item):
            issues.append('%s: one selector per entry' % what)
            continue
        if len(item) > V.LIMITS['anchor']:
            issues.append('%s: at most %d characters per entry' % (what, V.LIMITS['anchor']))
            continue
        _check_refs(item, known, what, issues)
        if item not in out:
            out.append(item)
    if len(out) > V.LIMITS['anchors']:
        issues.append('%s: at most %d entries' % (what, V.LIMITS['anchors']))
    if required and not out:
        issues.append('%s is required' % what)
    return out[:V.LIMITS['anchors']]


def _path(value, what, issues, known, wildcard, query):
    value = _text(value, V.LIMITS['path'], what, issues, required=True)
    if not value:
        return ''
    if not _PATH.match(value):
        issues.append('%s: a path on this server, starting with one "/"' % what)
        return value
    if not wildcard and '*' in value:
        issues.append('%s: "*" is not allowed here' % what)
    if not query and '?' in value:
        issues.append('%s: the request path is compared without its query; leave "?..." out' % what)
    _check_refs(value, known, what, issues)
    return value


def _captures(value, what, issues, page):
    if value in (None, {}, ''):
        return {}
    if not isinstance(value, dict):
        issues.append('%s: a map of name to %s expected' % (what, 'query parameter' if page else 'reply field'))
        return {}
    out = {}
    for name, source in value.items():
        if not isinstance(name, str) or not _VAR.match(name):
            issues.append('%s: "%s" is not a valid name (a letter, then letters, digits or _)' % (what, name))
            continue
        if not isinstance(source, str) or not (_PARAM if page else _CAPTURE).match(source.strip()):
            issues.append('%s: where to read {%s} is not valid' % (what, name))
            continue
        out[name] = source.strip()
    if len(out) > V.LIMITS['captures']:
        issues.append('%s: at most %d values' % (what, V.LIMITS['captures']))
    return out


def _wait_for(value, where, issues, known):
    if value in (None, '', {}):
        return None
    if not isinstance(value, dict):
        issues.append('%s: Done when is not valid' % where)
        return None
    kind = value.get('kind')
    if kind in (None, '', 'next'):
        return None
    if kind not in V.DONE_WHEN:
        issues.append('%s: Done when "%s" is not one of %s' % (where, kind, ', '.join(V.DONE_WHEN)))
        return None
    if kind == 'element':
        return {'kind': 'element',
                'anchor': _anchors(value.get('anchor'), where + ': Done when (element)', issues, known, True)}
    if kind == 'page':
        out = {'kind': 'page', 'path': _path(value.get('path'), where + ': Done when (page)', issues, known,
                                             wildcard=True, query=True)}
        capture = _captures(value.get('capture'), where + ': Capture', issues, page=True)
        if capture:
            out['capture'] = capture
        return out
    method = (value.get('method') or 'POST')
    method = method.upper() if isinstance(method, str) else method
    if method not in V.METHODS:
        issues.append('%s: Done when (request): method one of %s' % (where, ', '.join(V.METHODS)))
        method = 'POST'
    out = {'kind': 'request', 'method': method,
           'path': _path(value.get('path'), where + ': Done when (request)', issues, known, wildcard=True,
                         query=False)}
    capture = _captures(value.get('capture'), where + ': Capture', issues, page=False)
    if capture:
        out['capture'] = capture
    return out


def _fills(value, where, issues, known):
    if value in (None, '', []):
        return []
    if not isinstance(value, list):
        issues.append('%s: Fill buttons: a list expected' % where)
        return []
    out = []
    for n, item in enumerate(value, 1):
        what = '%s: Fill button %d' % (where, n)
        if not isinstance(item, dict):
            issues.append('%s is not valid' % what)
            continue
        label = _text(item.get('label'), V.LIMITS['fill_label'], what + ': label', issues, required=True)
        anchor = _anchors(item.get('anchor'), what + ': field', issues, known, required=True)
        val = item.get('value')
        val = _text(val if isinstance(val, str) else ('' if val is None else str(val)), V.LIMITS['fill_value'],
                    what + ': value', issues, required=True, multiline=True)
        _check_refs(val, known, what + ': value', issues)
        if len(anchor) > 1:
            issues.append('%s: one field per Fill button' % what)
        out.append({'label': label, 'anchor': anchor[0] if anchor else '', 'value': val})
    if len(out) > V.LIMITS['fills']:
        issues.append('%s: at most %d Fill buttons' % (where, V.LIMITS['fills']))
    return out


def _cleanup(value, where, issues, known):
    if value in (None, '', []):
        return []
    if not isinstance(value, list):
        issues.append('%s: Clean-up: a list expected' % where)
        return []
    out = []
    for item in value:
        if not isinstance(item, dict) or item.get('kind') not in V.CLEANUP_KINDS:
            issues.append('%s: Clean-up: kind one of %s' % (where, ', '.join(V.CLEANUP_KINDS)))
            continue
        var = item.get('var')
        if not isinstance(var, str) or not _VAR.match(var):
            issues.append('%s: Clean-up: the captured value to delete is not valid' % where)
            continue
        if var not in known:
            issues.append('%s: Clean-up uses {%s}, which no earlier step captures' % (where, var))
        if any(o['kind'] == item['kind'] for o in out):
            issues.append('%s: Clean-up: one %s per step' % (where, item['kind']))
            continue
        out.append({'kind': item['kind'], 'var': var})
    if len(out) > V.LIMITS['cleanup']:
        issues.append('%s: Clean-up: at most %d entries' % (where, V.LIMITS['cleanup']))
    return out


def validate_content(raw, require_format=False):
    """(clean content, issues). `clean` always has every key; the issues name the field ("Step 3: Highlight ...")."""
    issues = []
    if not isinstance(raw, dict):
        return None, ['A tutorial is a JSON object']
    fmt = raw.get('format')
    if require_format or fmt not in (None, ''):
        if fmt != V.FORMAT:
            issues.append('Not an IRIS-NG tutorial file: the format must be "%s"' % V.FORMAT)
            return None, issues
    clean = {
        'format': V.FORMAT,
        'title': _text(raw.get('title'), V.LIMITS['title'], 'Title', issues, required=True),
        'summary': _text(raw.get('summary'), V.LIMITS['summary'], 'Summary', issues, multiline=True),
        'duration': _text(raw.get('duration'), V.LIMITS['duration'], 'Duration', issues),
        'audience': raw.get('audience') or 'everyone',
        'steps': [],
    }
    if clean['audience'] not in V.AUDIENCES:
        issues.append('Audience: one of %s' % ', '.join(V.AUDIENCES))
        clean['audience'] = 'everyone'
    steps = raw.get('steps')
    if steps is None:
        steps = []
    if not isinstance(steps, list):
        issues.append('Steps: a list expected')
        steps = []
    if len(steps) > V.LIMITS['steps']:
        issues.append('At most %d steps' % V.LIMITS['steps'])
        steps = steps[:V.LIMITS['steps']]
    known = set()
    for n, step in enumerate(steps, 1):
        where = 'Step %d' % n
        if not isinstance(step, dict):
            issues.append('%s is not valid' % where)
            continue
        out = {'title': _text(step.get('title'), V.LIMITS['step_title'], where + ': title', issues, required=True),
               'body': _text(step.get('body'), V.LIMITS['body'], where + ': What to do', issues, multiline=True)}
        anchor = _anchors(step.get('anchor'), where + ': Highlight', issues, known)
        if anchor:
            out['anchor'] = anchor
        if step.get('goTo') not in (None, ''):
            out['goTo'] = _path(step.get('goTo'), where + ': "Take me there" link', issues, known,
                                wildcard=False, query=True)
        fills = _fills(step.get('fills'), where, issues, known)
        if fills:
            out['fills'] = fills
        wait = _wait_for(step.get('waitFor'), where, issues, known)
        if wait:
            out['waitFor'] = wait
        cleanup = _cleanup(step.get('cleanup'), where, issues, known)
        if cleanup:
            out['cleanup'] = cleanup
        clean['steps'].append(out)
        if wait and wait.get('capture'):
            known.update(wait['capture'].keys())
    return clean, issues


def captured_names(steps):
    names = set()
    for step in steps or []:
        names.update(((step.get('waitFor') or {}).get('capture') or {}).keys())
    return names


# ------------------------------------------------------------------ built-ins

_BUILTINS = None


def builtins():
    """{key: clean content} for the built-in files that load and validate, in V.BUILTIN_KEYS order. A broken file
    is logged and left out (the suite fails on it)."""
    global _BUILTINS
    if _BUILTINS is None:
        out = {}
        for key in V.BUILTIN_KEYS:
            path = os.path.join(_RES_DIR, key + '.json')
            try:
                with open(path, encoding='utf-8') as fh:
                    raw = json.load(fh)
            except Exception as exc:  # noqa: BLE001
                app.logger.error('Built-in tutorial %s not loaded: %s', key, exc)
                continue
            clean, issues = validate_content(raw, require_format=True)
            if issues:
                app.logger.error('Built-in tutorial %s not loaded: %s', key, '; '.join(issues))
                continue
            out[key] = clean
        _BUILTINS = out
    return _BUILTINS


def builtin_issues():
    """For the suite: {key: [issues]} over every built-in file, loaded or not."""
    result = {}
    for key in V.BUILTIN_KEYS:
        path = os.path.join(_RES_DIR, key + '.json')
        try:
            with open(path, encoding='utf-8') as fh:
                raw = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            result[key] = ['unreadable: %s' % exc]
            continue
        result[key] = validate_content(raw, require_format=True)[1]
    return result


# ------------------------------------------------------------------ catalogue

def _row_content(row):
    return {'format': V.FORMAT, 'title': row.title, 'summary': row.summary or '', 'duration': row.duration or '',
            'audience': row.audience, 'steps': row.steps or []}


def parse_ref(ref):
    if not isinstance(ref, str) or not _REF.match(ref):
        raise TutorialError('Tutorial not found', status=404)
    kind, _, ident = ref.partition('-')
    if kind == 'builtin':
        if ident not in builtins():
            raise TutorialError('Tutorial not found', status=404)
        return 'builtin', ident
    return 'team', int(ident)


def _entries(for_admin):
    """[(ref, kind, content, row | None, published)] - every tutorial in list order. A server's version of a built-in
    replaces it; an unpublished one hides it unless `for_admin`."""
    overrides = {t.builtin_key: t for t in Tutorial.query.filter(Tutorial.builtin_key.isnot(None)).all()}
    out = []
    for key, content in builtins().items():
        row = overrides.get(key)
        if row is not None and not row.published and not for_admin:
            continue
        out.append(('builtin-' + key, 'builtin', _row_content(row) if row is not None else content, row,
                    True if row is None else bool(row.published)))
    team = Tutorial.query.filter(Tutorial.builtin_key.is_(None)).order_by(Tutorial.id).all()
    for row in team:
        if not row.published and not for_admin:
            continue
        out.append(('team-%d' % row.id, 'team', _row_content(row), row, bool(row.published)))
    return out


def _visible(content, viewer):
    return content.get('audience') != 'admins' or viewer.admin


def _progress_map(user_id):
    return {p.tutorial_ref: p for p in TutorialProgress.query.filter(TutorialProgress.user_id == user_id).all()}


def _iso(value):
    return value.isoformat() + 'Z' if value else None


def _status(progress):
    if progress is None:
        return {'completed': False, 'completed_at': None, 'running': False, 'paused_step': None}
    paused = None
    if not progress.running and progress.snapshot and progress.step > 0:
        paused = progress.step
    return {'completed': progress.completed_at is not None, 'completed_at': _iso(progress.completed_at),
            'running': bool(progress.running), 'paused_step': paused}


def list_for_user(viewer):
    progress = _progress_map(viewer.user_id)
    out = []
    for ref, kind, content, _row, _published in _entries(for_admin=False):
        if not _visible(content, viewer) or not content['steps']:
            continue
        out.append({'ref': ref, 'kind': kind, 'title': content['title'], 'summary': content['summary'],
                    'duration': content['duration'], 'audience': content['audience'],
                    'steps': len(content['steps']), 'status': _status(progress.get(ref))})
    return {'tutorials': out, 'admin': bool(viewer.admin)}


def _user_name(user):
    return (user.name or user.user) if user is not None else None


def admin_list():
    builtin, team = [], []
    for ref, kind, content, row, published in _entries(for_admin=True):
        item = {'ref': ref, 'title': content['title'], 'summary': content['summary'], 'audience': content['audience'],
                'steps': len(content['steps']), 'published': published,
                'updated_at': _iso(row.updated_at) if row is not None else None,
                'updated_by': _user_name(row.updater) if row is not None else None}
        if kind == 'builtin':
            item['status'] = 'shipped' if row is None else ('edited' if published else 'hidden')
            builtin.append(item)
        else:
            item['status'] = 'published' if published else 'draft'
            team.append(item)
    return {'builtin': builtin, 'team': team}


def admin_get(ref):
    kind, ident = parse_ref(ref)
    if kind == 'builtin':
        row = Tutorial.query.filter(Tutorial.builtin_key == ident).first()
        content = _row_content(row) if row is not None else builtins()[ident]
        return {'ref': ref, 'kind': kind, 'content': content,
                'published': True if row is None else bool(row.published),
                'status': 'shipped' if row is None else ('edited' if row.published else 'hidden'),
                'edited': row is not None}
    row = Tutorial.query.filter(Tutorial.id == ident, Tutorial.builtin_key.is_(None)).first()
    if row is None:
        raise TutorialError('Tutorial not found', status=404)
    return {'ref': ref, 'kind': kind, 'content': _row_content(row), 'published': bool(row.published),
            'status': 'published' if row.published else 'draft', 'edited': True}


def _checked(content, published):
    clean, issues = validate_content(content)
    if clean is not None and published and not clean['steps']:
        issues.append('A published tutorial needs at least one step')
    if issues:
        raise TutorialError('The tutorial has %d problem%s.' % (len(issues), '' if len(issues) == 1 else 's'),
                            issues=issues)
    return clean


def _apply(row, clean, published, user_id):
    row.title = clean['title']
    row.summary = clean['summary'] or None
    row.duration = clean['duration'] or None
    row.audience = clean['audience']
    row.steps = clean['steps']
    row.published = bool(published)
    row.updated_by = user_id
    row.updated_at = datetime.utcnow()


def _published_flag(body):
    value = body.get('published', False)
    if not isinstance(value, bool):
        raise TutorialError('Published: true or false')
    return value


def create(viewer, body):
    published = _published_flag(body)
    clean = _checked(body.get('content'), published)
    if Tutorial.query.filter(Tutorial.builtin_key.is_(None)).count() >= V.LIMITS['team_tutorials']:
        raise TutorialError('At most %d team tutorials' % V.LIMITS['team_tutorials'])
    row = Tutorial(created_by=viewer.user_id)
    _apply(row, clean, published, viewer.user_id)
    db.session.add(row)
    db.session.commit()
    return admin_get('team-%d' % row.id)


def save(viewer, ref, body):
    kind, ident = parse_ref(ref)
    published = _published_flag(body)
    clean = _checked(body.get('content'), published)
    if kind == 'builtin':
        row = Tutorial.query.filter(Tutorial.builtin_key == ident).first()
        if row is None:
            row = Tutorial(builtin_key=ident, created_by=viewer.user_id)
            db.session.add(row)
    else:
        row = Tutorial.query.filter(Tutorial.id == ident, Tutorial.builtin_key.is_(None)).first()
        if row is None:
            raise TutorialError('Tutorial not found', status=404)
    _apply(row, clean, published, viewer.user_id)
    try:
        db.session.commit()
    except IntegrityError:
        # Two administrators saving their first version of the same built-in at once.
        db.session.rollback()
        raise TutorialError('Someone saved this tutorial at the same time; reload it', status=409)
    return admin_get(ref)


def delete(ref):
    """A team tutorial: gone, with every record of it except the runs in progress (they hold their snapshot).
    A built-in: this server's version is dropped, so the built-in comes back."""
    kind, ident = parse_ref(ref)
    if kind == 'builtin':
        row = Tutorial.query.filter(Tutorial.builtin_key == ident).first()
        if row is None:
            raise TutorialError('This built-in tutorial has not been edited', status=400)
        db.session.delete(row)
        db.session.commit()
        return {'restored': ref}
    row = Tutorial.query.filter(Tutorial.id == ident, Tutorial.builtin_key.is_(None)).first()
    if row is None:
        raise TutorialError('Tutorial not found', status=404)
    TutorialProgress.query.filter(TutorialProgress.tutorial_ref == ref,
                                  TutorialProgress.running.is_(False)).delete(synchronize_session=False)
    db.session.delete(row)
    db.session.commit()
    return {'deleted': ref}


def export(ref):
    data = admin_get(ref)
    content = dict(data['content'])
    content['format'] = V.FORMAT
    slug = re.sub(r'[^a-z0-9]+', '-', content['title'].lower()).strip('-')[:60] or 'tutorial'
    return content, '%s.tutorial.json' % slug


def import_file(viewer, raw):
    """A tutorial file (text or the parsed object) -> a new team tutorial, as a draft."""
    if isinstance(raw, (bytes, str)):
        if len(raw) > V.LIMITS['file_bytes']:
            raise TutorialError('The file is larger than %d KB' % (V.LIMITS['file_bytes'] // 1024))
        try:
            raw = json.loads(raw)
        except ValueError:
            raise TutorialError('The file is not JSON')
    clean, issues = validate_content(raw, require_format=True)
    if issues:
        raise TutorialError('The file has %d problem%s.' % (len(issues), '' if len(issues) == 1 else 's'),
                            issues=issues)
    return create(viewer, {'content': clean, 'published': False})


# ------------------------------------------------------------------ runs

def _content_for_run(viewer, ref):
    kind, ident = parse_ref(ref)
    for entry_ref, _kind, content, _row, _published in _entries(for_admin=False):
        if entry_ref == ref:
            if not _visible(content, viewer):
                break
            return content
    raise TutorialError('Tutorial not found', status=404)


def _running(user_id):
    return TutorialProgress.query.filter(TutorialProgress.user_id == user_id,
                                         TutorialProgress.running.is_(True)).first()


def _next_seq(user_id):
    """A run id unique among the user's runs of every tutorial: a report naming another tutorial's run must never
    move this one (ids counted per tutorial collided: run 1 of A was accepted as run 1 of B)."""
    from sqlalchemy import func
    top = db.session.query(func.max(TutorialProgress.run_seq)).filter(TutorialProgress.user_id == user_id).scalar()
    return (top or 0) + 1


def _begin(viewer, ref, content):
    if not content['steps']:
        raise TutorialError('This tutorial has no steps yet')
    now = datetime.utcnow()
    TutorialProgress.query.filter(TutorialProgress.user_id == viewer.user_id,
                                  TutorialProgress.running.is_(True)).update({'running': False},
                                                                             synchronize_session=False)
    row = TutorialProgress.query.filter(TutorialProgress.user_id == viewer.user_id,
                                        TutorialProgress.tutorial_ref == ref).first()
    if row is None:
        row = TutorialProgress(user_id=viewer.user_id, tutorial_ref=ref, run_seq=0, vars={})
        db.session.add(row)
    row.running = True
    row.minimized = False
    row.run_seq = _next_seq(viewer.user_id)
    row.step = 0
    row.vars = {}
    row.snapshot = {'ref': ref, 'title': content['title'], 'audience': content['audience'],
                    'steps': content['steps']}
    row.started_at = now
    row.updated_at = now
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise TutorialError('Another tutorial started at the same moment; try again', status=409)
    return run_payload(row, viewer.admin)


def start(viewer, ref):
    return _begin(viewer, ref, _content_for_run(viewer, ref))


def preview(viewer, content):
    """The editor's Try it: the posted (maybe unsaved) tutorial runs as this user's preview, never completed."""
    clean = _checked(content, published=True)
    return _begin(viewer, V.PREVIEW_REF, clean)


def resume(viewer, ref):
    if ref != V.PREVIEW_REF:
        parse_ref(ref)
    row = TutorialProgress.query.filter(TutorialProgress.user_id == viewer.user_id,
                                        TutorialProgress.tutorial_ref == ref).first()
    if row is None or not row.snapshot:
        raise TutorialError('There is nothing to continue; start the tutorial instead', status=400)
    if row.running:
        return run_payload(row, viewer.admin)
    TutorialProgress.query.filter(TutorialProgress.user_id == viewer.user_id,
                                  TutorialProgress.running.is_(True)).update({'running': False},
                                                                             synchronize_session=False)
    row.running = True
    row.minimized = False
    row.run_seq = _next_seq(viewer.user_id)
    row.updated_at = datetime.utcnow()
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise TutorialError('Another tutorial started at the same moment; try again', status=409)
    return run_payload(row, viewer.admin)


def _cleanup_state(row, admin):
    steps = (row.snapshot or {}).get('steps') or []
    if not (0 <= row.step < len(steps)):
        return []
    out = []
    cleaned = (row.vars or {}).get(_CLEANED) or {}
    for entry in steps[row.step].get('cleanup') or []:
        ident = _int((row.vars or {}).get(entry['var']))
        state = {'kind': entry['kind'], 'var': entry['var'], 'id': ident, 'done': cleaned.get(entry['kind']) == ident
                 and ident is not None}
        if state['done']:
            state['available'], state['reason'] = False, 'Deleted.'
        else:
            state['available'], state['reason'] = _cleanup_allowed(row, entry['kind'], ident, admin)
        out.append(state)
    return out


def run_payload(row, admin=False):
    snap = row.snapshot or {}
    steps = snap.get('steps') or []
    return {'run': row.run_seq, 'ref': row.tutorial_ref, 'preview': row.tutorial_ref == V.PREVIEW_REF,
            'title': snap.get('title') or '', 'steps': steps, 'total': len(steps),
            'step': row.step, 'vars': {k: v for k, v in (row.vars or {}).items() if k != _CLEANED},
            'minimized': bool(row.minimized), 'cleanup': _cleanup_state(row, admin)}


def run_state(viewer):
    row = _running(viewer.user_id)
    return run_payload(row, viewer.admin) if row is not None else None


def _current(viewer, run_seq):
    row = _running(viewer.user_id)
    if row is None:
        raise TutorialError('No tutorial is running', status=409)
    if not isinstance(run_seq, int) or isinstance(run_seq, bool) or run_seq != row.run_seq:
        raise TutorialError('This tutorial was restarted elsewhere', status=409)
    return row


def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,12}', value.strip()):
        return int(value.strip())
    return None


def _clean_vars(row, incoming):
    if incoming in (None, {}):
        return dict(row.vars or {})
    if not isinstance(incoming, dict):
        raise TutorialError('Values: a map expected')
    allowed = captured_names((row.snapshot or {}).get('steps'))
    merged = dict(row.vars or {})
    for name, value in incoming.items():
        if not isinstance(name, str) or not _VAR.match(name) or name not in allowed:
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            continue
        if isinstance(value, str):
            value = value.strip()[:V.LIMITS['var_value']]
        merged[name] = value
    if len([k for k in merged if k != _CLEANED]) > V.LIMITS['run_vars']:
        raise TutorialError('Too many captured values')
    return merged


def set_step(viewer, body):
    row = _current(viewer, body.get('run'))
    total = len((row.snapshot or {}).get('steps') or [])
    step = body.get('step')
    if not isinstance(step, int) or isinstance(step, bool) or not (0 <= step < total):
        raise TutorialError('Step out of range')
    row.vars = _clean_vars(row, body.get('vars'))
    row.step = step
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return run_payload(row, viewer.admin)


def set_minimized(viewer, body):
    row = _current(viewer, body.get('run'))
    value = body.get('minimized')
    if not isinstance(value, bool):
        raise TutorialError('Minimized: true or false')
    row.minimized = value
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return run_payload(row, viewer.admin)


def stop(viewer, body):
    row = _current(viewer, body.get('run'))
    row.running = False
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return {'stopped': row.tutorial_ref}


def finish(viewer, body):
    row = _current(viewer, body.get('run'))
    total = len((row.snapshot or {}).get('steps') or [])
    if row.step != total - 1:
        raise TutorialError('Finish is the last step')
    now = datetime.utcnow()
    row.running = False
    if row.tutorial_ref != V.PREVIEW_REF:
        row.completed_at = now
    row.snapshot = None
    row.step = 0
    row.vars = {}
    row.updated_at = now
    db.session.commit()
    return {'finished': row.tutorial_ref, 'completed': row.tutorial_ref != V.PREVIEW_REF}


# ------------------------------------------------------------------ clean-up

def _cleanup_allowed(row, kind, ident, admin):
    """(allowed, reason) for deleting what the run captured: the object must exist, be this user's, created after
    the run started, and the user must hold the normal right to delete it (a case: full access; a war room: lead;
    a catalogue vulnerability: server administrator)."""
    if ident is None:
        return False, 'Nothing was captured to delete.'
    since = (row.started_at or datetime.utcnow()) - _CLEANUP_SLACK
    if kind == 'vulnerability':
        from app.models.models import Vulnerability
        v = Vulnerability.query.filter(Vulnerability.vulnerability_id == ident).first()
        if v is None:
            return False, 'The catalogue entry no longer exists.'
        if v.created_by_id != row.user_id or v.created_at is None or v.created_at < since:
            return False, '%s was not recorded by you during this tutorial.' % v.identifier
        if not admin:
            return False, 'Only an administrator can delete %s from the catalogue.' % v.identifier
        return True, None
    if kind == 'case':
        from app.iris_engine.access_control.utils import ac_fast_check_user_has_case_access
        from app.models.authorization import CaseAccessLevel
        from app.models.cases import Cases
        case = Cases.query.filter(Cases.case_id == ident).first()
        if case is None:
            return False, 'Case #%d no longer exists.' % ident
        if ident == 1:
            return False, 'Case #1 cannot be deleted.'
        if case.user_id != row.user_id or case.initial_date is None or case.initial_date < since:
            return False, 'Case #%d was not opened by you during this tutorial.' % ident
        if not ac_fast_check_user_has_case_access(row.user_id, ident, [CaseAccessLevel.full_access]):
            return False, 'You cannot delete case #%d.' % ident
        return True, None
    from app.models.models import WarRoom
    from app.models.models import WarRoomMember
    room = WarRoom.query.filter(WarRoom.id == ident).first()
    if room is None:
        return False, 'War room #%d no longer exists.' % ident
    if room.created_by != row.user_id or room.created_at is None or room.created_at < since:
        return False, 'War room #%d was not opened by you during this tutorial.' % ident
    lead = WarRoomMember.query.filter(WarRoomMember.room_id == ident, WarRoomMember.user_id == row.user_id,
                                      WarRoomMember.role == 'lead').first()
    if lead is None:
        return False, 'Only a lead of war room #%d can delete it.' % ident
    return True, None


def cleanup(viewer, body):
    row = _current(viewer, body.get('run'))
    kind = body.get('kind')
    steps = (row.snapshot or {}).get('steps') or []
    entry = None
    if 0 <= row.step < len(steps):
        entry = next((e for e in steps[row.step].get('cleanup') or [] if e['kind'] == kind), None)
    if entry is None:
        raise TutorialError('This step offers no such clean-up')
    ident = _int((row.vars or {}).get(entry['var']))
    allowed, reason = _cleanup_allowed(row, kind, ident, viewer.admin)
    if not allowed:
        raise TutorialError(reason, status=403)
    from app.iris_engine.utils.tracker import track_activity
    if kind == 'case':
        from app.business.cases import cases_delete
        from app.business.errors import BusinessProcessingError
        try:
            cases_delete(ident)
        except BusinessProcessingError as exc:
            raise TutorialError(exc.get_message())
    elif kind == 'vulnerability':
        from app.business.vulnerabilities import delete_vulnerability
        from app.models.models import Vulnerability
        v = Vulnerability.query.filter(Vulnerability.vulnerability_id == ident).first()
        label = v.identifier
        delete_vulnerability(v)
        db.session.commit()
        track_activity("deleted vulnerability '%s' (tutorial clean-up)" % label, ctx_less=True)
    else:
        from app.business.war_rooms import delete_room
        from app.models.models import WarRoom
        room = WarRoom.query.filter(WarRoom.id == ident).first()
        name = room.name
        delete_room(room)
        track_activity("war room '%s' (#%d) deleted (tutorial clean-up)" % (name, ident), ctx_less=True)
    row = _running(viewer.user_id)
    cleaned = dict((row.vars or {}).get(_CLEANED) or {})
    cleaned[kind] = ident
    merged = dict(row.vars or {})
    merged[_CLEANED] = cleaned
    row.vars = merged
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return run_payload(row, viewer.admin)

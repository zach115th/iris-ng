"""The glossary behind the (i) help icons (iris-ng, 2026-10-30).

The text lives in resources/help_glossary/*.json, one file per group:

    {"group": "IOCs", "order": 40, "terms": {"ioc.tlp": {...}, ...}}

A term has a `title` and a `text` (plain text; a blank line starts a new
paragraph), and optionally:
  items     [{"name", "text"}] - the meaning of each value of a field whose
            values are fixed in the code (verdicts, roles, TLP levels)
  values    a lookup table whose stored descriptions explain the chosen value
            (datamgmt.manage.help_values_db.VALUE_TABLES)
  wiki      "Page" or "Page#anchor" on the project wiki ("Learn more")
  guest     true = also shown to war-room guests on the portal
  aka       other words the glossary page search should match
  page_only true = listed on the glossary page, no icon anywhere

Templates place an icon with {{ help_tip('ioc.tlp') }} (a Jinja global, see
blueprints/rest/context_routes.py) and JS renderers with IrisHelp.icon('ioc.tlp')
(ui/public/assets/js/iris/help_tips.js); both emit the same markup. A term
that fails validation is left out (logged once) - scripts/_test_help_tips.py
fails on any problem.
"""
import hashlib
import json
import logging
import re
import threading
from pathlib import Path

from markupsafe import Markup
from markupsafe import escape

from app.datamgmt.manage.help_values_db import VALUE_TABLES
from app.datamgmt.manage.help_values_db import lookup_values

log = logging.getLogger(__name__)

GLOSSARY_DIR = Path(__file__).resolve().parent.parent / 'resources' / 'help_glossary'
WIKI_BASE = 'https://github.com/zach115th/iris-ng/wiki/'
GLOSSARY_PAGE = '/help/glossary'

KEY_RE = re.compile(r'^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$')
WIKI_RE = re.compile(r'^[A-Za-z0-9-]+(#[a-z0-9-]+)?$')
PARAGRAPH_RE = re.compile(r'\n[ \t]*\n')
TERM_FIELDS = {'title', 'text', 'items', 'values', 'wiki', 'guest', 'aka', 'page_only'}
MAX_TITLE = 80
MAX_TEXT = 700
MAX_ITEMS = 24
MAX_ITEM_NAME = 80
MAX_ITEM_TEXT = 320

VIEWERS = ('user', 'guest')

_lock = threading.Lock()
_state = {'loaded': None}


def _problem(problems, where, message):
    problems.append('%s: %s' % (where, message))


def _clean_term(key, raw, where, problems):
    """The validated term, or None (with the reasons in `problems`)."""
    if not isinstance(raw, dict):
        _problem(problems, where, 'not an object')
        return None
    bad = len(problems)
    unknown = sorted(set(raw) - TERM_FIELDS)
    if unknown:
        _problem(problems, where, 'unknown field(s) %s' % ', '.join(unknown))
    title = raw.get('title')
    if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE:
        _problem(problems, where, 'title must be 1-%d characters' % MAX_TITLE)
    text = raw.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        _problem(problems, where, 'text must be 1-%d characters (has %s)'
                 % (MAX_TEXT, len(text) if isinstance(text, str) else type(text).__name__))
    items = raw.get('items', [])
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        _problem(problems, where, 'items must be a list of at most %d' % MAX_ITEMS)
        items = []
    clean_items = []
    for i, item in enumerate(items):
        if (not isinstance(item, dict) or set(item) != {'name', 'text'}
                or not isinstance(item['name'], str) or not item['name'].strip()
                or not isinstance(item['text'], str) or not item['text'].strip()
                or len(item['name']) > MAX_ITEM_NAME or len(item['text']) > MAX_ITEM_TEXT):
            _problem(problems, where, 'items[%d] must be {"name" <= %d, "text" <= %d}'
                     % (i, MAX_ITEM_NAME, MAX_ITEM_TEXT))
            continue
        clean_items.append({'name': item['name'].strip(), 'text': item['text'].strip()})
    values = raw.get('values')
    if values is not None and values not in VALUE_TABLES:
        _problem(problems, where, 'values %r is not one of %s' % (values, ', '.join(sorted(VALUE_TABLES))))
    wiki = raw.get('wiki')
    if wiki is not None and (not isinstance(wiki, str) or not WIKI_RE.match(wiki)):
        _problem(problems, where, 'wiki must look like "Page" or "Page#anchor"')
    for flag in ('guest', 'page_only'):
        if flag in raw and not isinstance(raw[flag], bool):
            _problem(problems, where, '%s must be true or false' % flag)
    aka = raw.get('aka', [])
    if not isinstance(aka, list) or not all(isinstance(a, str) and a.strip() for a in aka):
        _problem(problems, where, 'aka must be a list of words')
        aka = []
    if len(problems) > bad:
        return None
    return {
        'key': key,
        'title': title.strip(),
        'text': text.strip(),
        'paragraphs': [para.strip() for para in PARAGRAPH_RE.split(text) if para.strip()],
        'items': clean_items,
        'values': values,
        'wiki': wiki,
        'guest': bool(raw.get('guest', False)),
        'aka': [a.strip() for a in aka],
        'page_only': bool(raw.get('page_only', False)),
    }


def _load(directory=GLOSSARY_DIR):
    problems = []
    terms = {}
    groups = []
    files = sorted(Path(directory).glob('*.json')) if Path(directory).is_dir() else []
    if not files:
        _problem(problems, str(directory), 'no glossary files')
    for path in files:
        where = path.name
        try:
            with open(path, encoding='utf-8') as fh:
                doc = json.load(fh)
        except Exception as exc:
            _problem(problems, where, 'unreadable (%s)' % exc)
            continue
        if not isinstance(doc, dict) or set(doc) != {'group', 'order', 'terms'}:
            _problem(problems, where, 'must be {"group", "order", "terms"}')
            continue
        if not isinstance(doc['group'], str) or not doc['group'].strip() or not isinstance(doc['order'], int) \
                or not isinstance(doc['terms'], dict):
            _problem(problems, where, 'group must be a name, order a number, terms an object')
            continue
        keys = []
        for key, raw in doc['terms'].items():
            here = '%s %s' % (where, key)
            if not KEY_RE.match(key):
                _problem(problems, here, 'key must look like "area.term" (lowercase, dots)')
                continue
            if key in terms:
                _problem(problems, here, 'defined twice (also in another file)')
                continue
            term = _clean_term(key, raw, here, problems)
            if term is None:
                continue
            term['group'] = doc['group'].strip()
            terms[key] = term
            keys.append(key)
        groups.append({'name': doc['group'].strip(), 'order': doc['order'], 'file': path.name, 'keys': keys})
    groups.sort(key=lambda g: (g['order'], g['name']))
    for p in problems:
        log.warning('Help glossary: %s', p)
    loaded = {'terms': terms, 'groups': groups, 'problems': problems}
    loaded['scripts'] = {viewer: _client_script(loaded, viewer) for viewer in VIEWERS}
    return loaded


def glossary():
    """The loaded glossary (read once per process; reload_glossary() re-reads)."""
    loaded = _state['loaded']
    if loaded is None:
        with _lock:
            if _state['loaded'] is None:
                _state['loaded'] = _load()
            loaded = _state['loaded']
    return loaded


def reload_glossary(directory=GLOSSARY_DIR):
    with _lock:
        _state['loaded'] = _load(directory)
    return _state['loaded']


def glossary_problems():
    return list(glossary()['problems'])


def term(key):
    return glossary()['terms'].get(key)


def visible_to(t, viewer):
    """Whether a term's icon / entry is shown to this viewer ('user' or 'guest')."""
    if t is None or viewer not in VIEWERS:
        return False
    return viewer == 'user' or t['guest']


def wiki_url(ref):
    return (WIKI_BASE + ref) if ref else None


def glossary_anchor(key):
    return 'term-' + key


def icon_markup(key, viewer, target=None, cls=None):
    """The (i) button for `key`, or '' when this viewer is not shown it.
    `target`: a CSS selector of the field whose chosen value a "values" term
    describes; `cls`: extra classes (a spacing class moved off the label). The
    markup must stay identical to IrisHelp.icon() in help_tips.js. The button
    holds no text (help_tips.css draws the "i" with ::before), so a table
    header's export, a column toggle or any code reading a label's text never
    picks up an "i"."""
    t = term(key)
    if t is None:
        if viewer in VIEWERS:
            log.warning('Help glossary: no term %r (icon left out)', key)
        return Markup('')
    if t['page_only'] or not visible_to(t, viewer):
        return Markup('')
    target_attr = ' data-iris-help-for="%s"' % escape(target) if target else ''
    classes = 'iris-help' + (' ' + str(escape(cls)) if cls else '')
    return Markup('<button type="button" class="%s" data-iris-help="%s"%s aria-label="About %s"'
                  ' aria-haspopup="dialog" aria-expanded="false"></button>'
                  % (classes, escape(key), target_attr, escape(t['title'])))


def _client_terms(loaded, viewer):
    out = {}
    for key, t in loaded['terms'].items():
        if t['page_only'] or not visible_to(t, viewer):
            continue
        # `key` lets the client build the glossary link from this data rather
        # than from the icon's data-iris-help attribute (code scanning #49).
        entry = {'key': key, 'title': t['title'], 'text': t['text']}
        if t['items']:
            entry['items'] = [[i['name'], i['text']] for i in t['items']]
        if t['values'] and viewer == 'user':
            entry['values'] = t['values']
        if t['wiki']:
            entry['wiki'] = t['wiki']
        out[key] = entry
    return out


def _client_script(loaded, viewer):
    payload = {'wiki_base': WIKI_BASE, 'terms': _client_terms(loaded, viewer)}
    body = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(body.encode('ascii')).hexdigest()[:16]
    payload_js = body.replace('</', '<\\/')
    return {'hash': digest, 'js': 'window.IrisHelpGlossary=%s;\n' % payload_js}


def client_script(viewer):
    """{'hash', 'js'} - the glossary as a cacheable script for this viewer."""
    return glossary()['scripts'][viewer]


def value_rows(source):
    return lookup_values(source)


def glossary_page_groups():
    """Groups with their terms in order, for the glossary page (users only)."""
    loaded = glossary()
    out = []
    for g in loaded['groups']:
        terms = [loaded['terms'][k] for k in g['keys']]
        terms.sort(key=lambda t: t['title'].lower())
        if terms:
            out.append({'name': g['name'], 'terms': terms})
    return out

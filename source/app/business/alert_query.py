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

"""The Alerts page's search language (iris-ng, 2026-11-09): text -> tree -> SQL clause (models.alert_queue_vocab).

  parse(text)            the tree, or None for an empty search; QueryError(message, start, end) on a fault
  clauses(text, node)    the top-level conditions, as the search bar's chips [{text, start, end}]
  tab_of(node)           which quick tab the search stands for, or None
  compile_query(node, lookups)   the SQL clause, every value bound

The browser never parses: it sends the text and draws what comes back. A value names a lookup row by name, so a typo
is an error with its position rather than an empty list.
"""

import re
from datetime import date
from datetime import datetime
from datetime import timedelta

from sqlalchemy import and_
from sqlalchemy import func
from sqlalchemy import literal
from sqlalchemy import not_
from sqlalchemy import or_
from sqlalchemy import select

from app.models import alert_queue_vocab as av
from app.models.alerts import Alert
from app.models.alerts import AlertCaseAssociation
from app.models.alerts import AlertClusterMember
from app.models.models import CaseAssets
from app.models.models import Ioc

_FIELD = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*:')
_KEYWORDS = {'AND': 'and', 'OR': 'or', 'NOT': 'not', 'TO': 'to'}
_DELIMS = {'(': 'lparen', ')': 'rparen', '[': 'lbracket', ']': 'rbracket', '{': 'lbrace', '}': 'rbrace'}
_COMPARE = ('>=', '<=', '>', '<')


class QueryError(Exception):
    def __init__(self, message, start=0, end=0):
        super().__init__(message)
        self.message = message
        self.start = start
        self.end = end

    def as_dict(self):
        return {'message': self.message, 'start': self.start, 'end': self.end}


class _Token:
    __slots__ = ('kind', 'text', 'start', 'end')

    def __init__(self, kind, text, start, end):
        self.kind, self.text, self.start, self.end = kind, text, start, end


def _tokens(text):
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c in _DELIMS:
            out.append(_Token(_DELIMS[c], c, i, i + 1))
            i += 1
            continue
        if c == '"':
            j, value = i + 1, []
            while j < n and text[j] != '"':
                if text[j] == '\\' and j + 1 < n:
                    j += 1
                value.append(text[j])
                j += 1
            if j >= n:
                raise QueryError('Unterminated quoted phrase', i, n)
            out.append(_Token('phrase', ''.join(value), i, j + 1))
            i = j + 1
            continue
        j = i
        while j < n and not text[j].isspace() and text[j] not in _DELIMS and text[j] != '"':
            j += 1
        run = text[i:j]
        if run in _KEYWORDS:
            out.append(_Token(_KEYWORDS[run], run, i, j))
        elif run.startswith('-') and len(run) > 1:
            out.append(_Token('not', '-', i, i + 1))
            i += 1
            continue
        else:
            m = _FIELD.match(run)
            after = run[m.end():] if m else ''
            is_field = m and not after.startswith('//') and not after.startswith(':')
            # a field name directly before a quote, a bracket or nothing is still a field
            if is_field:
                name_end = i + m.end()
                out.append(_Token('field', run[:m.end() - 1], i, name_end))
                if after:
                    out.append(_Token('term', after, name_end, j))
            else:
                out.append(_Token('term', run, i, j))
        i = j
    return out


class _Parser:
    def __init__(self, text):
        self.text = text
        self.toks = _tokens(text)
        self.i = 0
        self.count = 0

    def cur(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def kind(self):
        t = self.cur()
        return t.kind if t else 'eof'

    def next(self):
        t = self.cur()
        self.i += 1
        return t

    def fail(self, message, tok=None):
        if tok is None:
            tok = self.cur()
        if tok is None:
            n = len(self.text)
            raise QueryError(message, n, n)
        raise QueryError(message, tok.start, tok.end)

    def counted(self, node):
        self.count += 1
        if self.count > av.MAX_TERMS:
            raise QueryError('A search holds at most %d terms.' % av.MAX_TERMS, node['start'], node['end'])
        return node

    def parse(self):
        node = self.or_expr(0)
        if self.cur() is not None:
            self.fail("Unexpected '%s'" % self.cur().text)
        return node

    def or_expr(self, depth):
        items = [self.and_expr(depth)]
        while self.kind() == 'or':
            op = self.next()
            if self.kind() in ('eof', 'rparen'):
                self.fail('OR needs something after it', op)
            items.append(self.and_expr(depth))
        if len(items) == 1:
            return items[0]
        return {'type': 'or', 'items': items, 'start': items[0]['start'], 'end': items[-1]['end']}

    def and_expr(self, depth):
        items = [self.not_expr(depth)]
        while True:
            k = self.kind()
            if k == 'and':
                op = self.next()
                if self.kind() in ('eof', 'rparen'):
                    self.fail('AND needs something after it', op)
                items.append(self.not_expr(depth))
            elif k in ('term', 'phrase', 'field', 'not', 'lparen'):
                items.append(self.not_expr(depth))
            else:
                break
        if len(items) == 1:
            return items[0]
        return {'type': 'and', 'items': items, 'start': items[0]['start'], 'end': items[-1]['end']}

    def not_expr(self, depth):
        if self.kind() == 'not':
            op = self.next()
            if depth + 1 > av.MAX_DEPTH:
                self.fail('A search nests at most %d levels deep.' % av.MAX_DEPTH, op)
            if self.kind() in ('eof', 'rparen'):
                self.fail('NOT needs something after it', op)
            child = self.not_expr(depth + 1)
            return {'type': 'not', 'item': child, 'start': op.start, 'end': child['end']}
        return self.primary(depth)

    def primary(self, depth):
        t = self.cur()
        if t is None:
            self.fail('The search ends unexpectedly')
        if t.kind == 'lparen':
            if depth + 1 > av.MAX_DEPTH:
                self.fail('A search nests at most %d levels deep.' % av.MAX_DEPTH, t)
            self.next()
            if self.kind() == 'rparen':
                self.fail('Empty parentheses', t)
            node = self.or_expr(depth + 1)
            close = self.cur()
            if close is None or close.kind != 'rparen':
                self.fail('Unbalanced parenthesis', t)
            self.next()
            return dict(node, start=t.start, end=close.end, grouped=True)
        if t.kind == 'field':
            self.next()
            value = self.value(t)
            return self.counted({'type': 'clause', 'field': t.text, 'value': value, 'start': t.start, 'end': value['end'],
                                 'name_end': t.end})
        if t.kind in ('term', 'phrase'):
            self.next()
            return self.counted({'type': 'bare', 'text': t.text, 'quoted': t.kind == 'phrase', 'start': t.start, 'end': t.end})
        self.fail("Unexpected '%s'" % t.text, t)

    def value(self, field_tok):
        t = self.cur()
        if t is None or t.kind not in ('term', 'phrase', 'lbracket', 'lbrace'):
            self.fail("'%s:' needs a value after it" % field_tok.text, field_tok)
        if t.kind in ('lbracket', 'lbrace'):
            return self.range(t)
        self.next()
        if t.kind == 'phrase':
            return {'type': 'term', 'text': t.text, 'quoted': True, 'start': t.start, 'end': t.end}
        for op in _COMPARE:
            if t.text.startswith(op):
                rest = t.text[len(op):]
                if not rest:
                    follow = self.cur()
                    if follow is None or follow.kind not in ('term', 'phrase'):
                        self.fail("'%s' needs a value after it" % op, t)
                    self.next()
                    rest, end = follow.text, follow.end
                else:
                    end = t.end
                return {'type': 'compare', 'op': op, 'text': rest, 'start': t.start, 'end': end}
        return {'type': 'term', 'text': t.text, 'quoted': False, 'start': t.start, 'end': t.end}

    def range(self, opener):
        self.next()
        lower = self.bound(opener)
        if self.kind() != 'to':
            self.fail("A range needs a 'TO' between its bounds", opener)
        self.next()
        upper = self.bound(opener)
        close = self.cur()
        if close is None or close.kind not in ('rbracket', 'rbrace'):
            self.fail('Unterminated range', opener)
        self.next()
        if lower is None and upper is None:
            raise QueryError('A range needs at least one bound', opener.start, close.end)
        return {'type': 'range', 'lower': lower, 'upper': upper, 'include_lower': opener.kind == 'lbracket',
                'include_upper': close.kind == 'rbracket', 'start': opener.start, 'end': close.end}

    def bound(self, opener):
        t = self.cur()
        if t is None or t.kind not in ('term', 'phrase'):
            self.fail('Range bound is missing', opener)
        self.next()
        return None if t.kind == 'term' and t.text == '*' else t.text


def parse(text):
    """The search as a tree, or None when it is empty."""
    text = text or ''
    if len(text) > av.MAX_QUERY:
        raise QueryError('A search is at most %d characters.' % av.MAX_QUERY, av.MAX_QUERY, len(text))
    if not text.strip():
        return None
    return _Parser(text).parse()


def _top(node):
    return node['items'] if node and node['type'] == 'and' and not node.get('grouped') else ([node] if node else [])


def clauses(text, node):
    """The top-level conditions as chips: what a space separates. OR makes everything around it one condition."""
    return [{'text': text[n['start']:n['end']], 'start': n['start'], 'end': n['end']} for n in _top(node)]


def _plain_value(node):
    if node.get('type') != 'clause' or node['value']['type'] != 'term':
        return None, None
    return av.canonical_field(node['field']), node['value']['text'].lower()


def tab_of(node):
    """mine / unassigned / escalated when the search's top level holds that tab's clause, else None."""
    found = {_plain_value(n) for n in _top(node)}
    if ('status', av.ESCALATED_STATUS.lower()) in found:
        return 'escalated'
    if ('owner', av.ME) in found:
        return 'mine'
    if ('owner', av.NONE) in found:
        return 'unassigned'
    return None


# ------------------------------------------------------------------ compile

def _like(text):
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _has_wildcard(value):
    return not value['quoted'] and ('*' in value['text'] or '?' in value['text'])


def _pattern(value):
    """Contains; an unquoted * or ? makes it a whole-value wildcard."""
    if _has_wildcard(value):
        return _like(value['text']).replace('*', '%').replace('?', '_')
    return '%' + _like(value['text']) + '%'


def _ilike(column, value):
    return func.coalesce(column, '').ilike(_pattern(value), escape='\\')


def _tag_norm():
    return literal(',') + func.regexp_replace(func.lower(func.btrim(func.coalesce(Alert.alert_tags, ''))),
                                              r'\s*,\s*', ',', 'g') + literal(',')


def _tag_clause(value):
    text = value['text'].strip().lower()
    if _has_wildcard(value):
        # a wildcard stays inside one tag: LIKE's % would run across the commas
        pattern = ',' + ''.join('[^,]*' if ch == '*' else '[^,]' if ch == '?' else re.escape(ch) for ch in text) + ','
        return _tag_norm().op('~')(pattern)
    return _tag_norm().like('%,' + _like(text) + ',%', escape='\\')


TEXT_COLUMNS = {
    'title': Alert.alert_title,
    'description': Alert.alert_description,
    'source': Alert.alert_source,
    'ref': Alert.alert_source_ref,
    'note': Alert.alert_note,
}
CHOICE_COLUMNS = {
    'status': Alert.alert_status_id,
    'severity': Alert.alert_severity_id,
    'classification': Alert.alert_classification_id,
    'resolution': Alert.alert_resolution_status_id,
    'customer': Alert.alert_customer_id,
    'owner': Alert.alert_owner_id,
}
DATE_COLUMNS = {'event_time': Alert.alert_source_event_time, 'created': Alert.alert_creation_time}


def _only_term(node, what):
    if node['value']['type'] != 'term':
        raise QueryError('%s takes a single value.' % what, node['value']['start'], node['value']['end'])
    return node['value']


def _whole_number(node, what):
    value = _only_term(node, what)
    if not re.fullmatch(r'\d{1,18}', value['text']):
        raise QueryError('%s takes a number.' % what, value['start'], value['end'])
    return int(value['text'])


def _moment(text, start, end):
    """-> (the moment, whether it was a whole day)."""
    text = text.strip()
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
            return datetime.combine(date.fromisoformat(text), datetime.min.time()), True
        return datetime.fromisoformat(text.replace('Z', '')).replace(tzinfo=None), False
    except ValueError:
        raise QueryError('A date is YYYY-MM-DD or YYYY-MM-DDTHH:MM (UTC).', start, end)


def _date_clause(node):
    column = DATE_COLUMNS[av.canonical_field(node['field'])]
    value = node['value']
    start, end = value['start'], value['end']
    if value['type'] == 'term':
        moment, whole_day = _moment(value['text'], start, end)
        if whole_day:
            return and_(column >= moment, column < moment + timedelta(days=1))
        return column == moment
    if value['type'] == 'compare':
        moment, whole_day = _moment(value['text'], start, end)
        next_day = moment + timedelta(days=1)
        return {'>=': column >= moment, '<': column < moment,
                '>': column >= next_day if whole_day else column > moment,
                '<=': column < next_day if whole_day else column <= moment}[value['op']]
    parts = []
    if value['lower'] is not None:
        moment, whole_day = _moment(value['lower'], start, end)
        if value['include_lower']:
            parts.append(column >= moment)
        else:
            parts.append(column >= moment + timedelta(days=1) if whole_day else column > moment)
    if value['upper'] is not None:
        moment, whole_day = _moment(value['upper'], start, end)
        if value['include_upper']:
            parts.append(column < moment + timedelta(days=1) if whole_day else column <= moment)
        else:
            parts.append(column < moment)
    return and_(*parts)


def _choice_clause(field, node, lookups):
    column = CHOICE_COLUMNS[field]
    value = node['value']
    label = av.QUERY_FIELDS[field][3].split(' (')[0].split(':')[0]
    if value['type'] == 'range':
        raise QueryError('%s takes a single value.' % label, value['start'], value['end'])
    if value['type'] == 'compare':
        if field != 'severity':
            raise QueryError('Only severity and dates can be compared.', value['start'], value['end'])
        rank = lookups.severity_rank(value['text'])
        if rank is None:
            raise QueryError('No severity named "%s".' % value['text'], value['start'], value['end'])
        ids = lookups.severities_where(value['op'], rank)
        return column.in_(ids) if ids else literal(False)
    text = value['text'].strip()
    low = text.lower()
    if field in av.NULLABLE_CHOICES and low == av.NONE and not value['quoted']:
        return column.is_(None)
    if field == 'owner' and low == av.ME and not value['quoted']:
        return column == lookups.user_id
    ids = lookups.ids_for(field, low)
    if not ids:
        raise QueryError('No %s named "%s".' % (label.lower(), text), value['start'], value['end'])
    return column.in_(ids)


def _clause(node, lookups):
    field = av.canonical_field(node['field'])
    if field is None:
        raise QueryError('Unknown field "%s".' % node['field'], node['start'], node['name_end'])
    kind = av.QUERY_FIELDS[field][0]
    if kind == 'date':
        return _date_clause(node)
    if kind == 'choice':
        return _choice_clause(field, node, lookups)
    if kind == 'id':
        return Alert.alert_id == _whole_number(node, 'id:')
    if kind == 'case':
        return Alert.alert_id.in_(_case_alerts(_whole_number(node, 'case:')))
    if kind == 'cluster':
        value = _only_term(node, 'cluster:')
        if value['text'].lower() == av.NONE and not value['quoted']:
            return not_(_in_cluster())
        return Alert.alert_id.in_(_cluster_alerts(_whole_number(node, 'cluster:')))
    if kind == 'is':
        value = _only_term(node, 'is:')
        low = value['text'].lower()
        if low not in av.IS_VALUES:
            raise QueryError('is: takes %s.' % ' or '.join(av.IS_VALUES), value['start'], value['end'])
        finished = lookups.finished_ids
        if low == 'open':
            return Alert.alert_status_id.notin_(finished) if finished else literal(True)
        return Alert.alert_status_id.in_(finished) if finished else literal(False)
    value = node['value']
    if value['type'] != 'term':
        raise QueryError('%s takes text.' % av.QUERY_FIELDS[field][3], value['start'], value['end'])
    if len(value['text']) > av.MAX_VALUE_LEN:
        raise QueryError('A value is at most %d characters.' % av.MAX_VALUE_LEN, value['start'], value['end'])
    if kind == 'tag':
        return _tag_clause(value)
    if kind == 'asset':
        return Alert.assets.any(CaseAssets.asset_name.ilike(_pattern(value), escape='\\'))
    if kind == 'ioc':
        return Alert.iocs.any(Ioc.ioc_value.ilike(_pattern(value), escape='\\'))
    return _ilike(TEXT_COLUMNS[field], value)


def _case_alerts(case_id):
    return select(AlertCaseAssociation.alert_id).where(AlertCaseAssociation.case_id == case_id)


def _cluster_alerts(cluster_id):
    return select(AlertClusterMember.alert_id).where(AlertClusterMember.cluster_id == cluster_id)


def _in_cluster():
    return select(AlertClusterMember.alert_id).where(AlertClusterMember.alert_id == Alert.alert_id).exists()


def _bare(node):
    if len(node['text']) > av.MAX_VALUE_LEN:
        raise QueryError('A value is at most %d characters.' % av.MAX_VALUE_LEN, node['start'], node['end'])
    # a bare word is always "contains"; a wildcard inside it still works, unanchored
    if not node['quoted'] and ('*' in node['text'] or '?' in node['text']):
        pattern = '%' + _like(node['text']).replace('*', '%').replace('?', '_') + '%'
    else:
        pattern = '%' + _like(node['text']) + '%'
    return or_(*[func.coalesce(c, '').ilike(pattern, escape='\\')
                 for c in (Alert.alert_title, Alert.alert_description, Alert.alert_source, Alert.alert_source_ref,
                           Alert.alert_tags)])


def compile_query(node, lookups):
    """The SQL clause of a parsed search (None for an empty one). NOT treats "no value" as "does not match"."""
    if node is None:
        return None
    t = node['type']
    if t == 'and':
        return and_(*[compile_query(n, lookups) for n in node['items']])
    if t == 'or':
        return or_(*[compile_query(n, lookups) for n in node['items']])
    if t == 'not':
        return not_(func.coalesce(compile_query(node['item'], lookups), False))
    if t == 'bare':
        return _bare(node)
    return _clause(node, lookups)

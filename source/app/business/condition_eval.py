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

"""Condition-tree evaluation over an alert view (iris-ng v2, Phase 2).

Shared grammar for Alert Clustering rules (Phase 2) and Investigation Flow
attachment (Phase 3). Conditions are evaluated in PYTHON, not SQL, on
purpose: ``alerts.alert_context`` is a plain ``json`` column (no JSONB
operators), and the rule set is small admin-authored config while the alert
volume is what scales — one dict walk per alert beats a query per rule.

Grammar (JSON):

  leaf   := {"field": "<dotted path>", "operator": "<op>", "value": <any>}
  group  := {"and": [node, ...]} | {"or": [node, ...]} | {"not": node}
  tree   := leaf | group | {} | null          ({} / null match everything)

Operators: eq, not, in, not_in, like (SQL % wildcards), regex, exists.
String comparisons are case-insensitive (rule authors think in display
values). When the resolved field is a LIST (asset_names, ioc_values, tags),
a leaf matches if ANY element satisfies it — except ``exists``, which tests
the list itself.

Fail-closed everywhere: unknown operator, missing field (except exists),
uncompilable regex, or a malformed node all evaluate to False and are logged
once — a broken rule must silently not-match, never break ingest. Strings
are truncated to 4 KB before regex/like matching (admin-supplied, but
bounded anyway — same rule as mail conditions).

``build_alert_view(alert)`` flattens an Alert ORM object into the dict the
grammar addresses:

  scalar columns        alert_title, alert_description, alert_source,
                        alert_source_ref, alert_source_link, alert_note,
                        alert_severity_id, alert_status_id,
                        alert_customer_id, alert_classification_id
  resolved names        severity, status, classification, customer
  lists                 tags[], asset_names[], ioc_values[]
  dotted JSON           alert_context.*, alert_source_content.*

``resolve_path`` also serves correlation-key resolution in
business/alert_clustering.py — unresolved keys return the _MISSING sentinel
there, mapped to '' for fingerprint stability.
"""

import logging
import re

log = logging.getLogger(__name__)

_MAX_MATCH_LEN = 4096

# Cap on the PATTERN, not just the subject: rule regexes are admin-authored,
# but they arrive through ordinary request paths (rule CRUD and the /test
# endpoints), and _MAX_MATCH_LEN bounds only the text being searched — a
# catastrophic-backtracking pattern is expensive at any subject length.
# Public: the mail-rule evaluator and schema validator enforce the same cap.
MAX_PATTERN_LEN = 512

# Sentinel distinguishing "path not present" from a stored None/null.
MISSING = object()

_VALID_OPS = ('eq', 'not', 'in', 'not_in', 'like', 'regex', 'exists')

# {m} / {m,} / {m,n} — group 2 is the comma, group 3 the (possibly empty)
# upper bound; {m,} (comma present, empty upper) is an UNBOUNDED repeat.
_BRACE_QUANT = re.compile(r'\{(\d+)(?:(,)(\d*))?\}')


def is_safe_regex(pattern: str) -> bool:
    """Conservative ReDoS gate over an admin-authored pattern (public: the
    mail-rule evaluator and schema validator share it, like MAX_PATTERN_LEN).

    Rejects the classic catastrophic-backtracking primitives — a REPEATED
    group (+, * or {…}) whose body carries alternation or an unbounded
    quantifier ((a+)+, (.*)*, (a|a)+, (a|ab)*c, (a+){3}) — plus
    backreferences and lookarounds, which the grammar's and/or/not
    composition already expresses. Everything observed in real rule sets
    passes: literal alternation (phish|trojan), optional atoms (e-?mail),
    unquantified groups (mfa (fatigue|bombing)), character classes, and
    bounded repeats incl. on groups ((\\.\\d{1,3}){3}).

    Deliberately incomplete — full ReDoS detection is undecidable in
    practice. The residual (e.g. nested BOUNDED repeats with huge bounds)
    requires a privileged author deliberately attacking their own instance,
    and MAX_PATTERN_LEN bounds the pattern while _MAX_MATCH_LEN bounds the
    subject. Fail closed on anything this scanner cannot place.
    """
    # One frame per open group: [contains_alternation, contains_unbounded].
    root = [False, False]
    stack = [root]
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == '\\':
            nxt = pattern[i + 1] if i + 1 < n else ''
            if nxt.isdigit() and nxt != '0':
                return False                      # numeric backreference
            i += 2
            continue
        if c == '[':
            # Character-class contents are literal — skip to the closing ].
            i += 1
            while i < n and pattern[i] != ']':
                i += 2 if pattern[i] == '\\' else 1
            i += 1
            continue
        if c == '(':
            head = pattern[i + 1:i + 4]
            if head.startswith('?=') or head.startswith('?!') \
                    or head == '?<=' or head == '?<!':
                return False                      # lookaround
            if head == '?P=':
                return False                      # named backreference
            stack.append([False, False])
            # Consume the '?' of extension groups ((?:, (?P<, (?i, (?>) so
            # it is not misread as a quantifier inside the new frame.
            i += 2 if pattern[i + 1:i + 2] == '?' else 1
            continue
        if c == ')':
            # Unbalanced ')' compiles to re.error downstream — treat inertly.
            frame = stack.pop() if len(stack) > 1 else [False, False]
            q = pattern[i + 1] if i + 1 < n else ''
            repeated = q in ('+', '*')   # NOT `q in '+*'` — '' is in every str
            if q == '{':
                m = _BRACE_QUANT.match(pattern, i + 1)
                repeated = m is not None
            if repeated and (frame[0] or frame[1]):
                return False    # repeated group with '|' or unbounded body
            # The group's body is still text inside the PARENT's body —
            # propagate so ((a|b)c)+ is judged at the outer group too.
            stack[-1][0] = stack[-1][0] or frame[0]
            stack[-1][1] = stack[-1][1] or frame[1]
            i += 1
            continue
        if c == '|':
            stack[-1][0] = True
            i += 1
            continue
        if c in '+*?':
            # '?' counts too: an empty-matchable repeated body ((a?)+ and
            # the classic (a?){k}) backtracks combinatorially.
            stack[-1][1] = True
            i += 1
            continue
        if c == '{':
            m = _BRACE_QUANT.match(pattern, i)
            if m:
                if m.group(2) is not None and m.group(3) == '':
                    stack[-1][1] = True           # {m,} is unbounded
                i = m.end()
                continue
            i += 1                                # literal brace
            continue
        i += 1
    return True


class _LazyView(dict):
    """Dict whose expensive keys materialize on first access. The resolved-
    name fields (severity, status, classification, customer) and the
    asset/ioc lists each cost a lazy-load SELECT on a freshly-ingested
    alert; on the ingest hot path most rules never touch them, and paying
    4-6 SELECTs per alert for unused fields is what pushed the Phase 2
    latency benchmark past its acceptance bar. resolve_path() only uses
    ``in`` and ``[]``, both overridden here.
    """

    def __init__(self, base: dict, lazy: dict):
        super().__init__(base)
        self._lazy = lazy

    def __contains__(self, key):
        return super().__contains__(key) or key in self._lazy

    def __getitem__(self, key):
        if not super().__contains__(key) and key in self._lazy:
            self[key] = self._lazy.pop(key)()
        return super().__getitem__(key)


def build_alert_view(alert) -> dict:
    """Flatten an Alert ORM object into the flat + dotted dict the condition
    grammar and the correlation keys address. Scalar columns are eager
    (already loaded); relationship-backed fields are LAZY — each costs a
    SELECT and is only paid when a rule actually references it.
    """
    base = {
        'alert_title': alert.alert_title,
        'alert_description': alert.alert_description,
        'alert_source': alert.alert_source,
        'alert_source_ref': alert.alert_source_ref,
        'alert_source_link': alert.alert_source_link,
        'alert_note': alert.alert_note,
        'alert_severity_id': alert.alert_severity_id,
        'alert_status_id': alert.alert_status_id,
        'alert_customer_id': alert.alert_customer_id,
        'alert_classification_id': alert.alert_classification_id,
        'tags': [t.strip() for t in (alert.alert_tags or '').split(',') if t.strip()],
        'alert_context': alert.alert_context if isinstance(alert.alert_context, dict) else {},
        'alert_source_content': (alert.alert_source_content
                                 if isinstance(alert.alert_source_content, dict) else {}),
    }
    # Friendly names so rules can say severity eq "High" instead of
    # hardcoding per-deployment lookup ids (fork rule: ids vary).
    lazy = {
        'severity': lambda: alert.severity.severity_name if alert.severity else None,
        'status': lambda: alert.status.status_name if alert.status else None,
        'classification': lambda: (alert.classification.name
                                   if alert.classification else None),
        'customer': lambda: alert.customer.name if alert.customer else None,
        'asset_names': lambda: [a.asset_name for a in (alert.assets or []) if a.asset_name],
        'ioc_values': lambda: [i.ioc_value for i in (alert.iocs or []) if i.ioc_value],
    }
    return _LazyView(base, lazy)


def resolve_path(view: dict, path: str):
    """Resolve a dotted path against the view. Returns MISSING when any
    segment is absent or a non-dict is dotted into.
    """
    if not path or not isinstance(path, str):
        return MISSING
    node = view
    for segment in path.split('.'):
        if not isinstance(node, dict) or segment not in node:
            return MISSING
        node = node[segment]
    return node


def _norm(value):
    """Case-fold strings for comparison; pass everything else through."""
    if isinstance(value, str):
        return value[:_MAX_MATCH_LEN].lower()
    return value


def _leaf_matches_scalar(op: str, actual, expected) -> bool:
    if op == 'eq':
        return _norm(actual) == _norm(expected)
    if op == 'not':
        return _norm(actual) != _norm(expected)
    if op == 'in':
        if not isinstance(expected, list):
            return False
        return _norm(actual) in [_norm(v) for v in expected]
    if op == 'not_in':
        if not isinstance(expected, list):
            return False
        return _norm(actual) not in [_norm(v) for v in expected]
    if op == 'like':
        if not isinstance(actual, str) or not isinstance(expected, str):
            return False
        # SQL LIKE: % = any run, _ = any single char; everything else literal.
        pattern = re.escape(expected).replace('%', '.*').replace('_', '.')
        try:
            return re.fullmatch(pattern, actual[:_MAX_MATCH_LEN],
                                re.IGNORECASE | re.DOTALL) is not None
        except re.error:
            return False
    if op == 'regex':
        if not isinstance(actual, str) or not isinstance(expected, str):
            return False
        if len(expected) > MAX_PATTERN_LEN:
            log.warning("condition_eval: regex longer than %d chars — leaf fails closed",
                        MAX_PATTERN_LEN)
            return False
        if not is_safe_regex(expected):
            log.warning("condition_eval: regex %r rejected by the ReDoS gate — "
                        "leaf fails closed", expected)
            return False
        try:
            return re.search(expected, actual[:_MAX_MATCH_LEN],
                             re.IGNORECASE) is not None
        except re.error:
            log.warning("condition_eval: uncompilable regex %r — leaf fails closed", expected)
            return False
    return False


def _eval_leaf(leaf: dict, view: dict) -> bool:
    op = leaf.get('operator')
    field = leaf.get('field')
    expected = leaf.get('value')

    if op not in _VALID_OPS or not field:
        log.warning("condition_eval: malformed leaf %r — fails closed", leaf)
        return False

    actual = resolve_path(view, field)

    if op == 'exists':
        present = actual is not MISSING and actual is not None
        # value defaults to True; {"operator": "exists", "value": false}
        # asserts absence.
        want = True if expected is None else bool(expected)
        return present is want

    if actual is MISSING or actual is None:
        # A missing field satisfies only negative operators — "field is not X"
        # is true of an alert that has no such field at all.
        return op in ('not', 'not_in')

    if isinstance(actual, list):
        return any(_leaf_matches_scalar(op, item, expected) for item in actual)
    return _leaf_matches_scalar(op, actual, expected)


def evaluate_tree(tree, view: dict) -> bool:
    """Evaluate a condition tree against a view. Empty/None tree matches
    everything (a rule with no conditions is a catch-all, like the mail
    fallback rule). Malformed nodes fail closed.
    """
    if tree is None:
        return True
    if not isinstance(tree, dict):
        log.warning("condition_eval: non-dict node %r — fails closed", type(tree).__name__)
        return False
    if not tree:
        return True

    if 'and' in tree:
        children = tree['and']
        if not isinstance(children, list):
            return False
        return all(evaluate_tree(c, view) for c in children)
    if 'or' in tree:
        children = tree['or']
        if not isinstance(children, list):
            return False
        # Empty or-list matches nothing (vacuous any()) — deliberate.
        return any(evaluate_tree(c, view) for c in children)
    if 'not' in tree:
        return not evaluate_tree(tree['not'], view)

    return _eval_leaf(tree, view)


def validate_tree(tree, _depth: int = 0):
    """Save-time validation for admin input: returns a list of problem
    strings (empty = valid). Mirrors evaluate_tree's structure so anything
    that validates clean cannot fail-closed at ingest for structural reasons.
    """
    problems = []
    if tree is None or tree == {}:
        return problems
    if _depth > 16:
        return ['condition tree deeper than 16 levels']
    if not isinstance(tree, dict):
        return [f'node must be an object, got {type(tree).__name__}']

    group_keys = [k for k in ('and', 'or', 'not') if k in tree]
    if len(group_keys) > 1:
        return [f'node mixes group keys {group_keys}']

    if group_keys:
        key = group_keys[0]
        if key == 'not':
            problems += validate_tree(tree['not'], _depth + 1)
        else:
            children = tree[key]
            if not isinstance(children, list):
                return [f'"{key}" must hold a list']
            for child in children:
                problems += validate_tree(child, _depth + 1)
        return problems

    op = tree.get('operator')
    if op not in _VALID_OPS:
        problems.append(f'unknown operator {op!r} (valid: {", ".join(_VALID_OPS)})')
    if not tree.get('field') or not isinstance(tree.get('field'), str):
        problems.append('leaf is missing a "field" string')
    if op in ('in', 'not_in') and not isinstance(tree.get('value'), list):
        problems.append(f'operator {op!r} needs a list value')
    if op == 'regex':
        pattern = tree.get('value')
        if not isinstance(pattern, str):
            problems.append('regex operator needs a string value')
        elif len(pattern) > MAX_PATTERN_LEN:
            problems.append(f'regex is longer than {MAX_PATTERN_LEN} characters')
        else:
            try:
                re.compile(pattern)
            except re.error as e:
                problems.append(f'regex does not compile: {e}')
            else:
                if not is_safe_regex(pattern):
                    problems.append(
                        'regex uses constructs prone to catastrophic '
                        'backtracking (a backreference, lookaround, or a '
                        'repeated group containing "|", "+", "*", "?" or an '
                        'open-ended repeat)')
    return problems

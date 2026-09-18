"""IOC value normalisation — the "100 % match" key for deduplication (#83).

Pure module (no Flask / ORM imports) so datamgmt, business and the AI layer
can all share ONE definition of "the same indicator": trim, Unicode NFKC,
refang the common defanging conventions, collapse whitespace, case-fold.

Refanging covers what analysts paste from reports and feeds:
  hxxp:// hxxps:// fxp://          -> http:// https:// ftp://
  [.] (.) {.} [dot] (dot) " dot "   -> .
  [at] (at) [@]                     -> @
  [:] [://]                         -> : ://
  \\.                                -> .   (regex-escaped dots)

Case-folding is deliberate (maintainer decision, 2026-09-18): hashes,
domains, e-mails and URLs are case-insensitive in practice, and two rows that
differ only by case are one indicator.
"""
from __future__ import annotations

import re
import unicodedata

_SCHEME_RE = re.compile(r'^(hxxps?|fxp)(://)', re.IGNORECASE)
_DOT_TOKENS = ('[.]', '(.)', '{.}', '[dot]', '(dot)', '{dot}', ' dot ')
_AT_TOKENS = ('[at]', '(at)', '{at}', '[@]', '(@)')
_COLON_TOKENS = (('[://]', '://'), ('[:]', ':'))


def _refang_scheme(m: re.Match) -> str:
    scheme = m.group(1).lower()
    scheme = {'hxxp': 'http', 'hxxps': 'https', 'fxp': 'ftp'}[scheme]
    return scheme + m.group(2)


def refang(value: str) -> str:
    """Undo defanging without touching case or surrounding whitespace."""
    s = str(value or '')
    s = _SCHEME_RE.sub(_refang_scheme, s)
    low = s.lower()
    for tok in _DOT_TOKENS:
        if tok in low:
            s = re.sub(re.escape(tok), '.', s, flags=re.IGNORECASE)
            low = s.lower()
    for tok in _AT_TOKENS:
        if tok in low:
            s = re.sub(re.escape(tok), '@', s, flags=re.IGNORECASE)
            low = s.lower()
    for tok, rep in _COLON_TOKENS:
        s = s.replace(tok, rep)
    s = s.replace('\\.', '.')
    return s


def normalise_ioc_value(value) -> str:
    """The dedup key for one IOC value (pair it with the type id)."""
    s = unicodedata.normalize('NFKC', str(value or '')).strip()
    s = refang(s)
    s = ' '.join(s.split())
    return s.lower()

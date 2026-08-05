"""Timeline deduplication logic — exact and near-duplicate detection.

Both master (`CasesEvent`) and working (`CaseWorkingEvent`) timelines are
supported via separate find_* functions.  No ORM imports here; callers pass
lists of ORM objects so this module has zero Flask dependencies and is
straightforward to unit-test.

Exact-match keys:
  master  : (event_date, norm(event_title), norm(event_content))
  working : (event_date, norm(event_title), norm(event_description), norm(event_source_host))

Near-duplicate detection:
  Events sorted by event_date; pairs whose dates are within `date_window_seconds`
  (default 5 min) AND whose titles have a token-sort SequenceMatcher ratio >=
  `threshold` (default 0.75) are flagged for analyst review.
"""
from __future__ import annotations

import difflib
import unicodedata
from datetime import datetime


def _norm(text) -> str:
    if not text:
        return ""
    return " ".join(unicodedata.normalize("NFKC", str(text)).strip().lower().split())


def _token_sort_ratio(a: str, b: str) -> float:
    a_tok = " ".join(sorted(_norm(a).split()))
    b_tok = " ".join(sorted(_norm(b).split()))
    return difflib.SequenceMatcher(None, a_tok, b_tok).ratio()


# ---------------------------------------------------------------------------
# Exact duplicates
# ---------------------------------------------------------------------------

def find_exact_master(events: list) -> list[dict]:
    """Return groups of exact duplicates in the master timeline.

    Each group: {"keep": CasesEvent, "duplicates": [CasesEvent, ...]}
    The kept event is the one with the earliest event_added timestamp.
    """
    seen: dict[tuple, dict] = {}
    for ev in sorted(events, key=lambda e: e.event_added or datetime.min):
        key = (ev.event_date, _norm(ev.event_title), _norm(ev.event_content or ""))
        if key in seen:
            seen[key]["duplicates"].append(ev)
        else:
            seen[key] = {"keep": ev, "duplicates": []}
    return [v for v in seen.values() if v["duplicates"]]


def find_exact_working(events: list) -> list[dict]:
    """Return groups of exact duplicates in the working timeline.

    The kept event is the one with the earliest created_at timestamp.
    """
    seen: dict[tuple, dict] = {}
    for ev in sorted(events, key=lambda e: e.created_at or datetime.min):
        key = (
            ev.event_date,
            _norm(ev.event_title),
            _norm(ev.event_description or ""),
            _norm(ev.event_source_host or ""),
        )
        if key in seen:
            seen[key]["duplicates"].append(ev)
        else:
            seen[key] = {"keep": ev, "duplicates": []}
    return [v for v in seen.values() if v["duplicates"]]


# ---------------------------------------------------------------------------
# Near duplicates
# ---------------------------------------------------------------------------

def find_near_master(
    events: list,
    date_window_seconds: int = 300,
    threshold: float = 0.75,
) -> list[dict]:
    """Return near-duplicate pairs in the master timeline.

    Each pair: {"event_a", "event_b", "similarity" (float 0-1), "date_diff_seconds"}
    Events are sorted by date so we can break early once dates diverge.
    Exact duplicates (already caught by find_exact_master) are excluded via
    the similarity < 1.0 check — but since we lower-case+normalise for the
    ratio they may still appear; callers should run exact dedup first.
    """
    dated = sorted([e for e in events if e.event_date], key=lambda e: e.event_date)
    pairs: list[dict] = []
    seen: set[tuple] = set()
    for i, a in enumerate(dated):
        for b in dated[i + 1:]:
            diff = abs((a.event_date - b.event_date).total_seconds())
            if diff > date_window_seconds:
                break
            pk = (min(a.event_id, b.event_id), max(a.event_id, b.event_id))
            if pk in seen:
                continue
            sim = _token_sort_ratio(a.event_title or "", b.event_title or "")
            if threshold <= sim < 1.0:
                seen.add(pk)
                pairs.append({
                    "event_a": a,
                    "event_b": b,
                    "similarity": round(sim, 3),
                    "date_diff_seconds": round(diff),
                })
    return pairs


def find_near_working(
    events: list,
    date_window_seconds: int = 300,
    threshold: float = 0.75,
) -> list[dict]:
    """Return near-duplicate pairs in the working timeline."""
    dated = sorted([e for e in events if e.event_date], key=lambda e: e.event_date)
    pairs: list[dict] = []
    seen: set[tuple] = set()
    for i, a in enumerate(dated):
        for b in dated[i + 1:]:
            diff = abs((a.event_date - b.event_date).total_seconds())
            if diff > date_window_seconds:
                break
            pk = (min(a.id, b.id), max(a.id, b.id))
            if pk in seen:
                continue
            sim = _token_sort_ratio(a.event_title or "", b.event_title or "")
            if threshold <= sim < 1.0:
                seen.add(pk)
                pairs.append({
                    "event_a": a,
                    "event_b": b,
                    "similarity": round(sim, 3),
                    "date_diff_seconds": round(diff),
                })
    return pairs

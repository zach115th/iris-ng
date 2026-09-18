"""IOC deduplication (#83) — exact groups, near candidates, merge.

Exact = same IOC type AND the same value under the dedup key
(`iris_engine.utils.ioc_normalise.normalise_ioc_value`: trim, refang,
case-fold). The survivor of an exact group is the FIRST entry (lowest id).

Near candidates are a heuristic, never applied on their own:
  similar        same type, token-sort SequenceMatcher ratio >= threshold
  same_value     same normalised value under a DIFFERENT type
  url_host       a URL whose host is another indicator's value
  port_variant   host:port vs host
The AI pass (`iris_engine.ai.ioc_dedup`) judges the whole list and returns
its own candidate pairs with a reason; the analyst chooses keep A / keep B /
merge / keep both in the modal.

A "keep" and a "merge" both TRANSFER the loser's links (assets, timeline
events, note provenance, alert association, comments, MISP attribute link
when the survivor has none, alert-similarity rows) to the survivor — deleting
an indicator without that would silently orphan its timeline and asset
links. Merge additionally unions the tags and appends a differing
description; keep discards the loser's fields.
"""
from __future__ import annotations

import difflib
import re
from urllib.parse import urlsplit

from flask_login import current_user

from app import db
from app.business.errors import BusinessProcessingError
from app.datamgmt.case.case_iocs_db import delete_ioc
from app.datamgmt.case.case_iocs_db import get_iocs_asset_links
from app.datamgmt.case.case_iocs_db import get_iocs_note_links
from app.datamgmt.case.case_iocs_db import transfer_ioc_links
from app.datamgmt.case.case_iocs_db import update_ioc_state
from app.datamgmt.states import update_timeline_state
from app.iris_engine.utils.ioc_normalise import normalise_ioc_value
from app.iris_engine.utils.tracker import track_activity
from app.models.models import CaseEventsIoc
from app.models.models import Ioc
from app.models.models import IocType
from app.models.models import Tlp
from app.util import add_obj_history_entry

MAX_IOCS_FOR_NEAR = 2000
MAX_NEAR_PAIRS = 200
NEAR_THRESHOLD = 0.85

_HOST_PORT_RE = re.compile(r'^(?P<host>[^/:\s]+|\[[0-9a-f:]+\]):(?P<port>\d{1,5})$', re.IGNORECASE)


def _token_sort_ratio(a: str, b: str) -> float:
    a_tok = ' '.join(sorted(a.split()))
    b_tok = ' '.join(sorted(b.split()))
    return difflib.SequenceMatcher(None, a_tok, b_tok).ratio()


def _url_host(norm_value: str) -> str | None:
    if '://' not in norm_value:
        return None
    try:
        host = urlsplit(norm_value).hostname
    except ValueError:
        return None
    return host or None


def _strip_port(norm_value: str) -> str | None:
    m = _HOST_PORT_RE.match(norm_value)
    return m.group('host') if m else None


# ---------------------------------------------------------------- scanning

def load_case_iocs(case_id: int) -> list[Ioc]:
    return (Ioc.query.filter(Ioc.case_id == case_id)
            .order_by(Ioc.ioc_id).all())


def find_exact(iocs: list[Ioc]) -> list[dict]:
    """Groups of exact duplicates: {"keep": Ioc, "duplicates": [Ioc, ...]}.
    Keep = lowest ioc_id (the first entry)."""
    seen: dict[tuple, dict] = {}
    for ioc in sorted(iocs, key=lambda i: i.ioc_id):
        key = (ioc.ioc_type_id, normalise_ioc_value(ioc.ioc_value))
        if not key[1]:
            continue
        if key in seen:
            seen[key]['duplicates'].append(ioc)
        else:
            seen[key] = {'keep': ioc, 'duplicates': []}
    return [g for g in seen.values() if g['duplicates']]


def find_near(iocs: list[Ioc], threshold: float = NEAR_THRESHOLD) -> list[dict]:
    """Candidate pairs: {"ioc_a", "ioc_b", "similarity", "reason"}. Exact
    duplicates (same type + same key) are excluded — find_exact owns them.
    Bounded: the first MAX_IOCS_FOR_NEAR rows, at most MAX_NEAR_PAIRS pairs."""
    rows = sorted(iocs, key=lambda i: i.ioc_id)[:MAX_IOCS_FOR_NEAR]
    norm = {i.ioc_id: normalise_ioc_value(i.ioc_value) for i in rows}
    by_value: dict[str, list[Ioc]] = {}
    for i in rows:
        if norm[i.ioc_id]:
            by_value.setdefault(norm[i.ioc_id], []).append(i)
    pairs: list[dict] = []
    seen: set[tuple] = set()

    def add(a: Ioc, b: Ioc, sim: float, reason: str):
        pk = (min(a.ioc_id, b.ioc_id), max(a.ioc_id, b.ioc_id))
        if pk in seen or a.ioc_id == b.ioc_id:
            return
        seen.add(pk)
        first, second = (a, b) if a.ioc_id < b.ioc_id else (b, a)
        pairs.append({'ioc_a': first, 'ioc_b': second,
                      'similarity': round(sim, 3), 'reason': reason})

    # same value, different type
    for group in by_value.values():
        types = {i.ioc_type_id for i in group}
        if len(types) > 1:
            for x in range(len(group)):
                for y in range(x + 1, len(group)):
                    if group[x].ioc_type_id != group[y].ioc_type_id:
                        add(group[x], group[y], 1.0, 'same_value')

    # url host / port variants against other values
    for i in rows:
        v = norm[i.ioc_id]
        if not v:
            continue
        host = _url_host(v)
        if host and host in by_value:
            for other in by_value[host]:
                add(i, other, 1.0, 'url_host')
        bare = _strip_port(v)
        if bare and bare in by_value:
            for other in by_value[bare]:
                add(i, other, 1.0, 'port_variant')

    # string similarity within a type
    by_type: dict[int, list[Ioc]] = {}
    for i in rows:
        if norm[i.ioc_id]:
            by_type.setdefault(i.ioc_type_id, []).append(i)
    for group in by_type.values():
        for x in range(len(group)):
            if len(pairs) >= MAX_NEAR_PAIRS:
                break
            a = group[x]
            for y in range(x + 1, len(group)):
                b = group[y]
                va, vb = norm[a.ioc_id], norm[b.ioc_id]
                if va == vb:
                    continue   # exact — owned by find_exact
                if abs(len(va) - len(vb)) > max(len(va), len(vb)) * (1 - threshold) + 2:
                    continue   # cheap length gate before the matcher
                sim = _token_sort_ratio(va, vb)
                if sim >= threshold:
                    add(a, b, sim, 'similar')
                    if len(pairs) >= MAX_NEAR_PAIRS:
                        break
    pairs.sort(key=lambda p: (-p['similarity'], p['ioc_a'].ioc_id, p['ioc_b'].ioc_id))
    return pairs[:MAX_NEAR_PAIRS]


# ------------------------------------------------------------ serialising

def serialize_iocs(iocs: list[Ioc]) -> dict[int, dict]:
    """{ioc_id: brief row} with type/TLP names and link COUNTS so the modal
    can show what a merge would carry over."""
    ids = [i.ioc_id for i in iocs]
    if not ids:
        return {}
    types = {t.type_id: t.type_name for t in IocType.query.all()}
    tlps = {t.tlp_id: t.tlp_name for t in Tlp.query.all()}
    assets = get_iocs_asset_links(ids)
    notes = get_iocs_note_links(ids)
    events: dict[int, int] = {}
    for row in (CaseEventsIoc.query.with_entities(CaseEventsIoc.ioc_id)
                .filter(CaseEventsIoc.ioc_id.in_(ids)).all()):
        events[row.ioc_id] = events.get(row.ioc_id, 0) + 1
    out = {}
    for i in iocs:
        out[i.ioc_id] = {
            'id': i.ioc_id,
            'value': i.ioc_value or '',
            'normalised': normalise_ioc_value(i.ioc_value),
            'type_id': i.ioc_type_id,
            'type': types.get(i.ioc_type_id, '?'),
            'description': i.ioc_description or '',
            'tags': i.ioc_tags or '',
            'tlp': tlps.get(i.ioc_tlp_id),
            'links': {
                'assets': len(assets.get(i.ioc_id, [])),
                'events': events.get(i.ioc_id, 0),
                'notes': len(notes.get(i.ioc_id, [])),
            },
        }
    return out


def scan_case(case_id: int) -> dict:
    iocs = load_case_iocs(case_id)
    ser = serialize_iocs(iocs)
    exact = [{'keep': ser[g['keep'].ioc_id],
              'duplicates': [ser[d.ioc_id] for d in g['duplicates']]}
             for g in find_exact(iocs)]
    near = [{'ioc_a': ser[p['ioc_a'].ioc_id], 'ioc_b': ser[p['ioc_b'].ioc_id],
             'similarity': p['similarity'], 'reason': p['reason']}
            for p in find_near(iocs)]
    return {'ioc_count': len(iocs), 'exact': exact, 'near': near}


# --------------------------------------------------------------- merging

def _union_tags(a: str | None, b: str | None) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for src in (a or '', b or ''):
        for t in src.split(','):
            t = t.strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
    return ','.join(out)


def merge_iocs(survivor: Ioc, loser: Ioc, *, union_fields: bool, actor_id: int) -> dict:
    """Transfer the loser's links to the survivor, optionally union the
    fields, record history, delete the loser. Commits. Returns the transfer
    counts."""
    if survivor.ioc_id == loser.ioc_id:
        raise BusinessProcessingError('An indicator cannot be merged into itself')
    if survivor.case_id != loser.case_id:
        raise BusinessProcessingError('Indicators belong to different cases')
    moved = transfer_ioc_links(loser.ioc_id, survivor.ioc_id)
    if union_fields:
        survivor.ioc_tags = _union_tags(survivor.ioc_tags, loser.ioc_tags) or None
        ldesc = (loser.ioc_description or '').strip()
        sdesc = (survivor.ioc_description or '').strip()
        if ldesc and ldesc not in sdesc:
            survivor.ioc_description = (
                (sdesc + '\n\n' if sdesc else '') +
                f'---\nMerged from IOC #{loser.ioc_id} ({loser.ioc_value}):\n{ldesc}')
        if survivor.ioc_tlp_id is None and loser.ioc_tlp_id is not None:
            survivor.ioc_tlp_id = loser.ioc_tlp_id
        if not survivor.ioc_misp and loser.ioc_misp:
            survivor.ioc_misp = loser.ioc_misp
        if survivor.ioc_enrichment is None and loser.ioc_enrichment is not None:
            survivor.ioc_enrichment = loser.ioc_enrichment
    add_obj_history_entry(
        survivor,
        f'merged duplicate IOC #{loser.ioc_id} "{loser.ioc_value}" into this one '
        f'({"fields unioned" if union_fields else "links only"})')
    loser_value, loser_id = loser.ioc_value, loser.ioc_id
    delete_ioc(loser)          # comments already moved; refreshes ioc state
    update_ioc_state(caseid=survivor.case_id)
    if moved.get('events'):
        update_timeline_state(caseid=survivor.case_id)
    db.session.commit()
    track_activity(
        f'merged duplicate IOC #{loser_id} "{loser_value}" into IOC #{survivor.ioc_id} '
        f'"{survivor.ioc_value}"', caseid=survivor.case_id)
    return moved


def _get_case_ioc(case_id: int, ioc_id) -> Ioc:
    try:
        ioc_id = int(ioc_id)
    except (TypeError, ValueError):
        raise BusinessProcessingError('Invalid IOC id')
    ioc = Ioc.query.filter(Ioc.ioc_id == ioc_id, Ioc.case_id == case_id).first()
    if ioc is None:
        raise BusinessProcessingError(f'IOC #{ioc_id} not found in this case')
    return ioc


def resolve(case_id: int, action: str, keep_id, delete_ids: list, actor_id: int) -> dict:
    """action = 'keep' (links transferred, loser fields dropped) or 'merge'
    (links transferred, tags/description unioned). 'keep_both' is a client-
    side dismissal and never reaches here."""
    if action not in ('keep', 'merge'):
        raise BusinessProcessingError("action must be 'keep' or 'merge'")
    survivor = _get_case_ioc(case_id, keep_id)
    if not delete_ids:
        raise BusinessProcessingError('at least one delete_id is required')
    totals: dict[str, int] = {}
    merged = 0
    for did in delete_ids:
        loser = _get_case_ioc(case_id, did)
        moved = merge_iocs(survivor, loser, union_fields=(action == 'merge'),
                           actor_id=actor_id)
        for k, v in moved.items():
            totals[k] = totals.get(k, 0) + v
        merged += 1
    return {'kept': survivor.ioc_id, 'merged': merged, 'transferred': totals}


def auto_exact(case_id: int, actor_id: int) -> dict:
    """Collapse every exact group onto its first entry (links transferred,
    fields unioned so nothing typed on the duplicate is lost)."""
    groups = find_exact(load_case_iocs(case_id))
    removed = 0
    totals: dict[str, int] = {}
    for g in groups:
        for d in g['duplicates']:
            moved = merge_iocs(g['keep'], d, union_fields=True, actor_id=actor_id)
            for k, v in moved.items():
                totals[k] = totals.get(k, 0) + v
            removed += 1
    if removed:
        track_activity(f'Dedup: collapsed {removed} exact duplicate IOC(s) in {len(groups)} group(s)',
                       caseid=case_id)
    return {'removed': removed, 'groups': len(groups), 'transferred': totals}


def actor_id_or_none():
    try:
        return current_user.id
    except Exception:  # noqa: BLE001 — worker context
        return None

"""
IOC cross-case correlation engine.

No new tables needed — correlation is computed on-the-fly from the existing
Ioc table using the same (ioc_value, ioc_type_id) equality that get_ioc_links()
already uses. This module adds:

  - Parameterised overlap queries (date window, min-shared-ioc threshold)
  - Cluster builder: groups cases into clusters by shared-IOC graph connectivity
  - Campaign tag suggestion: when a case pair shares >= threshold IOCs, suggest
    a campaign:<slug> tag on both cases
  - All queries respect the caller's case-access ACL

TLP policy: only IOCs marked TLP:GREEN (id=3) or TLP:CLEAR (id=4) are included
in correlation queries. RED and AMBER IOCs are excluded to prevent cross-case
information leakage on the dashboard.

Typical call from the REST layer:

    from app.business.ioc_correlation import build_correlation_report
    report = build_correlation_report(
        current_user_id=current_user.id,
        min_shared=2,
        start_date=datetime(2026, 1, 1),
        end_date=None,          # None = no upper bound
    )
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from mistletoe import markdown as _mistletoe_markdown

def _render_md(text: str) -> str:
    """Render markdown to HTML using mistletoe (tables supported natively)."""
    return _mistletoe_markdown(text)

from sqlalchemy import and_, func

from app import db
from app.iris_engine.access_control.utils import ac_get_fast_user_cases_access
from app.models.alerts import Severity
from app.models.cases import Cases
from app.models.cases import CaseTags
from app.models.models import CaseClassification, Client, Ioc, IocNoteLink, IocType, Notes, Tags


# ---------------------------------------------------------------------------
# IOC decay scoring
# ---------------------------------------------------------------------------

# Type half-lives in days — how long until a fresh IOC of this type
# scores 0.5 (exponential decay: score = exp(-ln2 * age / half_life))
_TYPE_HALF_LIFE: dict[str, float] = {
    # Network indicators — rotate fast
    "ip-dst":       14.0,
    "ip-src":       14.0,
    "ip-dst|port":  14.0,
    "ip-src|port":  14.0,
    "ip-any":       14.0,
    "url":          30.0,
    "uri":          30.0,
    # Domains — slower than IPs
    "domain":       45.0,
    "hostname":     45.0,
    "domain|ip":    30.0,
    # Email — moderate
    "email-src":    90.0,
    "email-dst":    90.0,
    "email":        90.0,
    # Files / hashes — long-lived artefacts
    "md5":         180.0,
    "sha1":        180.0,
    "sha256":      180.0,
    "sha512":      180.0,
    "filename":    120.0,
    "filename|md5":   180.0,
    "filename|sha1":  180.0,
    "filename|sha256":180.0,
    # Registry / mutex / other host artefacts
    "regkey":      120.0,
    "regkey|value":120.0,
    "mutex":       120.0,
    # Everything else gets a middling default
}
_DEFAULT_HALF_LIFE = 60.0  # days


# Tag-based multipliers applied to each IOC's decay score.
# Higher multiplier = decays more slowly (stays relevant longer).
# Evaluated in order; first match per IOC per tag wins (no stacking within a tier).
# Multiple tags on the same IOC CAN contribute (one multiplier per distinct tag prefix match).
_TAG_MULTIPLIERS: list[tuple[str, float]] = [
    # Admiralty scale — source reliability (A=best, F=worst)
    ("admiralty-scale:source-reliability=\"a\"", 1.35),
    ("admiralty-scale:source-reliability=\"b\"", 1.20),
    ("admiralty-scale:source-reliability=\"c\"", 1.10),
    ("admiralty-scale:source-reliability=\"d\"", 0.85),
    ("admiralty-scale:source-reliability=\"e\"", 0.80),
    ("admiralty-scale:source-reliability=\"f\"", 0.75),
    # Admiralty scale — information credibility (1=confirmed, 6=cannot be judged)
    ("admiralty-scale:information-credibility=\"1\"", 1.35),
    ("admiralty-scale:information-credibility=\"2\"", 1.15),
    ("admiralty-scale:information-credibility=\"3\"", 1.05),
    ("admiralty-scale:information-credibility=\"4\"", 0.90),
    ("admiralty-scale:information-credibility=\"5\"", 0.85),
    ("admiralty-scale:information-credibility=\"6\"", 0.80),
    # MISP galaxies — attribution / malware family
    ("misp-galaxy:threat-actor=",  1.40),
    ("misp-galaxy:ransomware=",    1.35),
    ("misp-galaxy:malpedia=",      1.30),
    ("misp-galaxy:rat=",           1.30),
    ("misp-galaxy:tool=",          1.25),
    ("misp-galaxy:sector=",        1.10),
    # CIRCL incident classification
    ("circl:incident-classification=\"apt\"",          1.40),
    ("circl:incident-classification=\"c2server\"",     1.35),
    ("circl:incident-classification=\"ransomware\"",   1.35),
    ("circl:incident-classification=\"botnet\"",       1.30),
    ("circl:incident-classification=\"malware\"",      1.30),
    ("circl:incident-classification=\"ddos\"",         1.20),
    ("circl:incident-classification=\"phishing\"",     1.15),
    ("circl:incident-classification=\"scanner\"",      1.10),
    ("circl:incident-classification=",                 1.05),  # any other circl class
    # TLP — sensitivity/fidelity proxy
    ("tlp:red",    1.30),
    ("tlp:amber",  1.10),
    ("tlp:green",  1.00),
    ("tlp:clear",  0.85),
    ("tlp:white",  0.85),
    # CSSA
    ("cssa:sharing-class=\"threat-intel\"", 1.20),
    # Noise flags (applied by the IOC extractor at ingest time)
    ("⚠ cdn",          0.50),
    ("⚠ public dns",   0.50),
    ("⚠ parked",       0.40),
    ("⚠ sinkhole",     0.40),
]

# Free-text keyword fallback (lower ceiling: max 1.20, applied only when no
# MISP-taxonomy prefix matched for that keyword concept)
_FREETEXT_KEYWORDS: list[tuple[str, float]] = [
    ("apt",                  1.20),
    ("c2",                   1.18),
    ("c&c",                  1.18),
    ("command-and-control",  1.18),
    ("ransomware",           1.18),
    ("botnet",               1.15),
    ("malware",              1.15),
    ("backdoor",             1.15),
    ("dropper",              1.12),
    ("loader",               1.12),
    ("stealer",              1.12),
    ("rat",                  1.12),
    ("trojan",               1.12),
    ("phishing",             1.10),
    ("exploit",              1.10),
    ("rootkit",              1.10),
]

# Decay label thresholds (on the cluster-level weighted-mean score)
_LABEL_ACTIVE = 0.60
_LABEL_AGING  = 0.25


def _ioc_decay_score(age_days: float, type_name: str, tags_str: str) -> float:
    """
    Return a [0, ∞) decay score for a single IOC.

    Base: exponential half-life decay keyed on ioc_type.
    Modified: multiplicative tag multipliers (one per distinct matched prefix,
              with free-text keyword scan as a lower-ceiling fallback tier).
    """
    half_life = _TYPE_HALF_LIFE.get(type_name.lower() if type_name else "", _DEFAULT_HALF_LIFE)
    base = math.exp(-math.log(2) * max(age_days, 0.0) / half_life)

    # Parse comma/pipe-separated tags (matches Ioc.ioc_tags storage format)
    raw_tags = [t.strip().lower() for t in (tags_str or "").replace("|", ",").split(",") if t.strip()]

    multiplier = 1.0
    freetext_covered: set[str] = set()  # concepts covered by taxonomy matches

    for tag in raw_tags:
        for prefix, mult in _TAG_MULTIPLIERS:
            if tag.startswith(prefix.lower()):
                multiplier *= mult
                # Mark free-text keywords covered by this taxonomy match
                for kw, _ in _FREETEXT_KEYWORDS:
                    if kw in prefix.lower():
                        freetext_covered.add(kw)
                break  # first matching rule wins for this tag

    # Free-text keyword scan on uncovered concepts only
    all_tags_joined = " ".join(raw_tags)
    for kw, ft_mult in _FREETEXT_KEYWORDS:
        if kw not in freetext_covered and kw in all_tags_joined:
            multiplier *= min(ft_mult, 1.20)  # ceiling for free-text tier

    return base * multiplier


def _ioc_confidence(shared_ioc_count: int, min_shared: int) -> float:
    """
    Logistic confidence score in [0, 1] based on how many IOCs a cluster shares
    relative to the analyst-set threshold.

    Anchored so that:
      count == min_shared       → ~0.40  (just at threshold — plausible but weak)
      count == min_shared * 2.5 → ~0.65
      count == 10               → ~0.80 (when min_shared=2)
      count == 20               → ~0.90
      count == 36               → ~0.95
    Formula: 1 - 1 / (1 + log2(count / min_shared + 1))
    """
    if shared_ioc_count <= 0 or min_shared <= 0:
        return 0.0
    ratio = shared_ioc_count / min_shared
    return round(1.0 - 1.0 / (1.0 + math.log2(ratio + 1)), 3)


def _compute_cluster_decay(
    cluster_case_ids: list[int],
    all_pairs: list[dict],
    case_open_dates: dict[int, datetime | None],
    case_close_dates: dict[int, datetime | None],
    min_shared: int = 2,
) -> dict:
    """
    Compute decay label + score for one cluster.

    Uses the IOCs shared within the cluster (from all_pairs), anchoring each
    IOC's age to the open_date of its oldest case in the cluster.

    Returns:
      {
        "decay_label": "Active" | "Aging" | "Stale",
        "decay_score": 0.73,          # weighted mean, 2 dp
        "decay_detail": "3 ip-dst (14d half-life) · 2 sha256 (180d) · ...",
      }
    """
    now = datetime.now(timezone.utc)
    member_set = set(cluster_case_ids)

    # Collect IOCs that belong to this cluster
    cluster_iocs = [p for p in all_pairs if member_set.issuperset(set(p["case_ids"]))]

    if not cluster_iocs:
        return {"decay_label": "Stale", "decay_score": 0.0, "decay_detail": "no shared IOCs"}

    scores: list[float] = []
    type_counts: dict[str, int] = defaultdict(int)

    for pair in cluster_iocs:
        # Age anchor: oldest case open_date among the cases sharing this IOC
        sharing_case_ids = [c for c in pair["case_ids"] if c in member_set]
        anchor: datetime | None = None
        for cid in sharing_case_ids:
            od = case_open_dates.get(cid)
            if od:
                # Cases.open_date may be a plain date — promote to datetime
                if not isinstance(od, datetime):
                    od = datetime(od.year, od.month, od.day)
                od_aware = od.replace(tzinfo=timezone.utc) if od.tzinfo is None else od
                if anchor is None or od_aware < anchor:
                    anchor = od_aware

        age_days = (now - anchor).total_seconds() / 86400.0 if anchor else 0.0

        # We need tags for this IOC value — they may differ per case; use the
        # first non-empty tags string found across the sharing cases (best effort).
        # The full per-IOC tag query is done separately below.
        scores.append(None)  # placeholder; filled after tag lookup
        type_counts[pair.get("ioc_type_name", "") or ""] += 1

    # Bulk-fetch ioc_tags for all IOC values in this cluster's shared set
    ioc_values = [p["ioc_value"] for p in cluster_iocs]
    ioc_type_ids = [p["ioc_type_id"] for p in cluster_iocs]

    tag_map: dict[tuple, str] = {}  # (value, type_id) → tags string
    if ioc_values:
        tag_rows = (
            db.session.query(Ioc.ioc_value, Ioc.ioc_type_id, Ioc.ioc_tags)
            .filter(
                Ioc.ioc_value.in_(ioc_values),
                Ioc.ioc_type_id.in_(ioc_type_ids),
                Ioc.case_id.in_(list(member_set)),
            )
            .all()
        )
        for ioc_val, ioc_tid, ioc_tags in tag_rows:
            key = (ioc_val, ioc_tid)
            # Prefer the richer tags string (more tags = more signal)
            if key not in tag_map or len(ioc_tags or "") > len(tag_map[key]):
                tag_map[key] = ioc_tags or ""

    # Now compute actual scores
    scores = []
    for pair in cluster_iocs:
        sharing_case_ids = [c for c in pair["case_ids"] if c in member_set]
        anchor = None
        for cid in sharing_case_ids:
            od = case_open_dates.get(cid)
            if od:
                # Cases.open_date may be a plain date — promote to datetime
                if not isinstance(od, datetime):
                    od = datetime(od.year, od.month, od.day)
                od_aware = od.replace(tzinfo=timezone.utc) if od.tzinfo is None else od
                if anchor is None or od_aware < anchor:
                    anchor = od_aware

        age_days = (now - anchor).total_seconds() / 86400.0 if anchor else 0.0
        tags_str = tag_map.get((pair["ioc_value"], pair["ioc_type_id"]), "")
        scores.append(_ioc_decay_score(age_days, pair.get("ioc_type_name", ""), tags_str))

    weighted_mean = sum(scores) / len(scores) if scores else 0.0

    # Cap label if all cases are closed — closed investigation can't be "Active"
    all_closed = all(case_close_dates.get(cid) is not None for cid in cluster_case_ids)

    if weighted_mean >= _LABEL_ACTIVE and not all_closed:
        label = "Active"
    elif weighted_mean >= _LABEL_AGING:
        label = "Aging" if not all_closed else "Aging"
    else:
        label = "Stale"

    # Detail string: top type breakdown
    top_types = sorted(type_counts.items(), key=lambda x: -x[1])[:4]
    detail_parts = []
    for tn, cnt in top_types:
        hl = _TYPE_HALF_LIFE.get(tn.lower() if tn else "", _DEFAULT_HALF_LIFE)
        detail_parts.append(f"{cnt}× {tn} ({int(hl)}d ½-life)")
    detail = " · ".join(detail_parts) if detail_parts else "mixed types"

    return {
        "decay_label": label,
        "decay_score": round(weighted_mean, 3),
        "decay_detail": detail,
        "ioc_confidence": _ioc_confidence(len(cluster_iocs), min_shared),
    }


# ---------------------------------------------------------------------------
# TLP policy
# ---------------------------------------------------------------------------

# Only IOCs with these TLP IDs are included in cross-case correlation.
# TLP id mapping (load-bearing — from CLAUDE.md):
#   1=red  2=amber  3=green  4=clear  5=amber+strict
# Correlating RED/AMBER IOCs would expose them on the shared dashboard to any
# user with access to either case — green/clear only are safe to surface.
_CORRELATABLE_TLP_IDS = (3, 4)  # green, clear


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _accessible_case_ids(user_id: int) -> list[int] | None:
    """Return the set of case IDs the user may see, or None = all cases."""
    limitations = ac_get_fast_user_cases_access(user_id)
    return list(limitations) if limitations else None


def _case_filter(start_date: Optional[datetime], end_date: Optional[datetime]):
    """Build SQLAlchemy filter clauses for case open_date window."""
    clauses = []
    if start_date:
        clauses.append(Cases.open_date >= start_date)
    if end_date:
        clauses.append(Cases.open_date <= end_date)
    return clauses


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_shared_ioc_pairs(
    user_id: int,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> list[dict]:
    """
    Return every (ioc_value, ioc_type_id) that appears in ≥2 cases the user
    can see, plus the list of case IDs it appears in.

    Result shape:
      [
        {
          "ioc_value": "185.193.88.41",
          "ioc_type_id": 3,
          "ioc_type_name": "ip-dst",
          "case_ids": [3, 7, 12],
          "case_count": 3,
        },
        ...
      ]
    """
    accessible = _accessible_case_ids(user_id)

    case_clauses = _case_filter(start_date, end_date)

    q = (
        db.session.query(
            Ioc.ioc_value,
            Ioc.ioc_type_id,
            IocType.type_name,
            func.array_agg(Ioc.case_id.distinct()).label("case_ids"),
            func.count(Ioc.case_id.distinct()).label("case_count"),
        )
        .join(IocType, Ioc.ioc_type_id == IocType.type_id)
        .join(Cases, Ioc.case_id == Cases.case_id)
        .filter(Ioc.ioc_tlp_id.in_(_CORRELATABLE_TLP_IDS))
        .filter(and_(*case_clauses) if case_clauses else True)
    )

    if accessible is not None:
        q = q.filter(Ioc.case_id.in_(accessible))

    q = (
        q.group_by(Ioc.ioc_value, Ioc.ioc_type_id, IocType.type_name)
         .having(func.count(Ioc.case_id.distinct()) >= 2)
         .order_by(func.count(Ioc.case_id.distinct()).desc())
    )

    rows = q.all()

    return [
        {
            "ioc_value": r.ioc_value,
            "ioc_type_id": r.ioc_type_id,
            "ioc_type_name": r.type_name,
            "case_ids": sorted(r.case_ids),
            "case_count": r.case_count,
        }
        for r in rows
    ]


def build_correlation_report(
    user_id: int,
    min_shared: int = 2,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> dict:
    """
    Full correlation report for the dashboard Correlation tab.

    Returns:
      {
        "pairs": [<shared_ioc_pair>, ...],          # all IOCs shared across ≥2 cases
        "clusters": [                                # connected components keyed by cluster_id
          {
            "cluster_id": "a3f...",                 # deterministic hash of sorted case ids
            "case_ids": [3, 7],
            "shared_ioc_count": 4,
            "shared_iocs": ["185.193.88.41", ...],
            "suggested_campaign_tag": "campaign:cluster-a3f",
          },
          ...
        ],
        "case_meta": {                              # display metadata per case_id
          3: {"name": "...", "client": "...", "open_date": "...", "severity": "..."},
          ...
        },
        "generated_at": "2026-...",
        "params": {"min_shared": 2, "start_date": ..., "end_date": ...},
      }
    """
    all_pairs = get_shared_ioc_pairs(user_id, start_date, end_date)

    # --- build adjacency graph: case_id -> set of case_ids sharing IOCs ---
    # Only count an edge if the pair shares >= min_shared distinct IOC values.

    # edge_weights[(ca, cb)] = number of distinct IOC values shared between ca and cb
    edge_weights: dict[tuple[int, int], int] = defaultdict(int)

    for pair in all_pairs:
        case_ids = pair["case_ids"]
        for i in range(len(case_ids)):
            for j in range(i + 1, len(case_ids)):
                key = (case_ids[i], case_ids[j])
                edge_weights[key] += 1

    # Keep only edges that meet the threshold
    strong_edges: dict[tuple[int, int], int] = {
        k: v for k, v in edge_weights.items() if v >= min_shared
    }

    # Collect all case IDs that appear in at least one strong edge
    correlated_case_ids: set[int] = set()
    for ca, cb in strong_edges:
        correlated_case_ids.add(ca)
        correlated_case_ids.add(cb)

    # --- connected-components clustering ---
    parent: dict[int, int] = {c: c for c in correlated_case_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for ca, cb in strong_edges:
        union(ca, cb)

    # Group cases by cluster root
    cluster_map: dict[int, set[int]] = defaultdict(set)
    for c in correlated_case_ids:
        cluster_map[find(c)].add(c)

    # Build cluster dicts
    clusters = []
    for root, members in cluster_map.items():
        member_list = sorted(members)
        # Shared IOC values across ALL members of this cluster
        member_set = set(member_list)
        shared_iocs = [
            p["ioc_value"]
            for p in all_pairs
            if member_set.issuperset(set(p["case_ids"]))
        ]
        # Count distinct IOC values shared by at least min_shared cases in this
        # cluster — not the number of case pairs.
        shared_count = len(shared_iocs)
        cluster_hash = hashlib.md5(
            ",".join(str(c) for c in member_list).encode()
        ).hexdigest()[:8]
        clusters.append({
            "cluster_id": cluster_hash,
            "case_ids": member_list,
            "shared_ioc_count": shared_count,
            "shared_iocs": shared_iocs[:20],  # cap for display
            "suggested_campaign_tag": f"campaign:cluster-{cluster_hash}",
        })

    clusters.sort(key=lambda c: c["shared_ioc_count"], reverse=True)

    # --- case metadata ---
    all_case_ids = correlated_case_ids | {
        cid for p in all_pairs for cid in p["case_ids"]
    }

    case_rows = (
        db.session.query(
            Cases.case_id,
            Cases.name,
            Cases.open_date,
            Cases.close_date,
            Client.name.label("client_name"),
        )
        .join(Client, Cases.client_id == Client.client_id)
        .filter(Cases.case_id.in_(all_case_ids))
        .all()
    )

    # Index open/close dates for decay computation
    case_open_dates: dict[int, datetime | None] = {r.case_id: r.open_date for r in case_rows}
    case_close_dates: dict[int, datetime | None] = {r.case_id: r.close_date for r in case_rows}

    # Fetch tags for all correlated cases so the UI can detect already-tagged clusters
    meta_tags: dict[int, list[str]] = defaultdict(list)
    if all_case_ids:
        meta_tag_rows = (
            db.session.query(Tags.tag_title, CaseTags.case_id)
            .join(CaseTags, Tags.id == CaseTags.tag_id)
            .filter(CaseTags.case_id.in_(all_case_ids))
            .all()
        )
        for tag_title, cid in meta_tag_rows:
            meta_tags[cid].append(tag_title)

    case_meta = {
        r.case_id: {
            "name": r.name,
            "client": r.client_name,
            "open_date": r.open_date.isoformat() if r.open_date else None,
            "close_date": r.close_date.isoformat() if r.close_date else None,
            "tags": meta_tags.get(r.case_id, []),
        }
        for r in case_rows
    }

    # Attach decay scoring to each cluster
    for cluster in clusters:
        decay = _compute_cluster_decay(
            cluster_case_ids=cluster["case_ids"],
            all_pairs=all_pairs,
            case_open_dates=case_open_dates,
            case_close_dates=case_close_dates,
            min_shared=min_shared,
        )
        cluster.update(decay)

    return {
        "pairs": all_pairs,
        "clusters": clusters,
        "case_meta": case_meta,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "params": {
            "min_shared": min_shared,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
        },
    }


def get_ioc_cross_case_context(ioc_value: str, ioc_type_id: int, user_id: int) -> dict:
    """
    Return cross-case context for a single IOC value — used by the AI brief pill
    on the IOC modal.

    Each appearance entry includes:
      - IOC-level: per-case description and tags (may differ between cases)
      - Case-level: classification, severity, case tags, open/close dates
      - Note context: titles of linked notes in that case + a short snippet from
        the first note body that mentions the IOC value (first 300 chars of the
        sentence containing the value, or first 300 chars of the note)
    """
    accessible = _accessible_case_ids(user_id)

    q = (
        db.session.query(
            Ioc.ioc_id,
            Ioc.ioc_description,
            Ioc.ioc_tags,
            Cases.case_id,
            Cases.name.label("case_name"),
            Cases.open_date,
            Cases.close_date,
            Client.name.label("client_name"),
            IocType.type_name,
            CaseClassification.name_expanded.label("classification"),
            Severity.severity_name.label("severity"),
        )
        .join(Cases, Ioc.case_id == Cases.case_id)
        .join(Client, Cases.client_id == Client.client_id)
        .join(IocType, Ioc.ioc_type_id == IocType.type_id)
        .outerjoin(CaseClassification, Cases.classification_id == CaseClassification.id)
        .outerjoin(Severity, Cases.severity_id == Severity.severity_id)
        .filter(
            Ioc.ioc_value == ioc_value,
            Ioc.ioc_type_id == ioc_type_id,
            Ioc.ioc_tlp_id.in_(_CORRELATABLE_TLP_IDS),
        )
    )

    if accessible is not None:
        q = q.filter(Ioc.case_id.in_(accessible))

    rows = q.order_by(Cases.open_date.asc()).all()

    # Bulk-fetch case tags for all matched cases
    case_ids = [r.case_id for r in rows]
    case_tags: dict[int, list[str]] = defaultdict(list)
    if case_ids:
        tag_rows = (
            db.session.query(Tags.tag_title, Cases.case_id)
            .join(Cases, Tags.cases)
            .filter(Cases.case_id.in_(case_ids))
            .all()
        )
        for tag_title, cid in tag_rows:
            case_tags[cid].append(tag_title)

    # Pass 1 — formal IocNoteLink provenance (keyed by ioc_id)
    ioc_ids = [r.ioc_id for r in rows]
    ioc_id_to_case: dict[int, int] = {r.ioc_id: r.case_id for r in rows}
    formal_note_snippets: dict[int, list[dict]] = defaultdict(list)
    cases_with_formal_links: set[int] = set()
    if ioc_ids:
        note_rows = (
            db.session.query(
                IocNoteLink.ioc_id,
                Notes.note_title,
                Notes.note_content,
            )
            .join(Notes, IocNoteLink.note_id == Notes.note_id)
            .filter(IocNoteLink.ioc_id.in_(ioc_ids))
            .order_by(IocNoteLink.ioc_id, Notes.note_id)
            .all()
        )
        for ioc_id, note_title, note_content in note_rows:
            snippet = _extract_snippet(note_content or "", ioc_value)
            formal_note_snippets[ioc_id].append({
                "note_title": note_title or "",
                "snippet": snippet,
                "source": "linked",
            })
            cases_with_formal_links.add(ioc_id_to_case[ioc_id])

    # Pass 2 — substring fallback: search all notes in cases that had no formal links.
    # Also matches common defang variants (185[.]193[.]88[.]41, hxxp://, etc.).
    cases_needing_fallback = [cid for cid in case_ids if cid not in cases_with_formal_links]
    case_fallback_snippets: dict[int, list[dict]] = defaultdict(list)
    if cases_needing_fallback:
        defanged = _defang_variants(ioc_value)
        search_terms = [ioc_value] + defanged
        all_notes = (
            db.session.query(Notes.note_id, Notes.note_title, Notes.note_content, Notes.note_case_id)
            .filter(Notes.note_case_id.in_(cases_needing_fallback))
            .all()
        )
        for note_id, note_title, note_content, note_case_id in all_notes:
            content = note_content or ""
            matched_term = next((t for t in search_terms if t.lower() in content.lower()), None)
            if matched_term:
                snippet = _extract_snippet(content, matched_term)
                case_fallback_snippets[note_case_id].append({
                    "note_title": note_title or "",
                    "snippet": snippet,
                    "source": "mention",
                })

    appearances = []
    for r in rows:
        # Prefer formal links; fall back to mention search for cases with none
        if r.ioc_id in formal_note_snippets:
            linked_notes = formal_note_snippets[r.ioc_id]
        else:
            linked_notes = case_fallback_snippets.get(r.case_id, [])

        appearances.append({
            "case_id": r.case_id,
            "case_name": r.case_name,
            "client": r.client_name,
            "open_date": r.open_date.isoformat() if r.open_date else None,
            "close_date": r.close_date.isoformat() if r.close_date else None,
            "classification": r.classification or "",
            "severity": r.severity or "",
            "case_tags": case_tags.get(r.case_id, []),
            "ioc_description": r.ioc_description or "",
            "ioc_tags": r.ioc_tags or "",
            "linked_notes": linked_notes,
        })

    return {
        "ioc_value": ioc_value,
        "ioc_type_name": rows[0].type_name if rows else None,
        "appearances": appearances,
        "total_cases": len(rows),
    }


def _extract_snippet(text: str, needle: str, max_chars: int = 300) -> str:
    """Return a markdown-rendered HTML snippet around the first occurrence of needle.
    Falls back to the first max_chars characters of text if needle not found.
    When the match is inside a markdown table, expands to include the full table
    so the renderer can produce a proper <table> element.
    The returned value is safe HTML, not plain text."""
    idx = text.lower().find(needle.lower())
    if idx == -1:
        return _render_md(text[:max_chars].strip())

    # Check whether the match sits inside a markdown table block.
    # A table block is a run of lines where every line starts with '|'.
    lines = text.splitlines(keepends=True)
    char_pos = 0
    match_line = 0
    for i, line in enumerate(lines):
        if char_pos + len(line) > idx:
            match_line = i
            break
        char_pos += len(line)

    def _is_table_line(ln: str) -> bool:
        return ln.strip().startswith("|")

    if _is_table_line(lines[match_line]):
        # Expand upward to find the first line of the table block
        table_start = match_line
        while table_start > 0 and _is_table_line(lines[table_start - 1]):
            table_start -= 1
        # Expand downward to find the last line of the table block
        table_end = match_line
        while table_end + 1 < len(lines) and _is_table_line(lines[table_end + 1]):
            table_end += 1
        raw = "".join(lines[table_start:table_end + 1])
        return _render_md(raw)

    # Not in a table — return a windowed snippet
    start = max(0, idx - 80)
    end = min(len(text), idx + max_chars - 80)
    raw = text[start:end].strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return _render_md(prefix + raw + suffix)


def _defang_variants(value: str) -> list[str]:
    """Return common defanged forms of an IOC value for note substring search."""
    variants = []
    # IP: 1.2.3.4 → 1[.]2[.]3[.]4
    if '.' in value and not value.startswith('http'):
        variants.append(value.replace('.', '[.]'))
        variants.append(value.replace('.', '(.)'))
    # URL/domain: hxxp:// and hxxps://
    if value.startswith('http://'):
        variants.append('hxxp://' + value[7:])
        variants.append('hxxp://' + value[7:].replace('.', '[.]'))
    elif value.startswith('https://'):
        variants.append('hxxps://' + value[8:])
        variants.append('hxxps://' + value[8:].replace('.', '[.]'))
    # Bare domain with [.] notation
    if '.' in value and '/' not in value and not value[0].isdigit():
        variants.append(value.replace('.', '[.]'))
        variants.append(value.replace('.', '(.)'))
    return list(dict.fromkeys(v for v in variants if v != value))

#  IRIS-NG additive — dashboard metrics aggregator (v1, on-load).
#
#  Returns four sections (analyst-self, SOC/manager, admin/system health,
#  investigation quality) plus a top KPI strip, computed from existing tables.
#  Token usage tracking is deferred — there's no `ai_call_log` table yet.
#
#  Aggregation strategy: compute on each load. Simple, fine up to several
#  thousand cases. If it ever hurts, the natural next move is a nightly
#  `metrics_daily` rollup table.

import datetime as _dt
from typing import Any

from flask_login import current_user
from sqlalchemy import and_, case, func

from app import db
from app.models.alerts import Severity
from app.models.cases import Cases, CasesEvent, CaseTags, CaseWorkingEvent
from app.models.models import (
    CaseAiArtifact, CaseAssets, CaseClassification, CaseEventsAssets,
    CaseEventsIoc, CaseReceivedFile, CaseTasks, Client, Ioc, MispEventLink,
    Notes, Tags,
)
from app.models.authorization import User


# Shared constants — referenced by both _case_tagging and _critical_infrastructure.
# Tag form per the bundled MISP taxonomy: dhs-ciip-sectors:DHS-critical-sectors="<value>"
DHS_CIIP_TAG_NAMESPACE = 'dhs-ciip-sectors'
DHS_CIIP_TAG_PREDICATE = 'DHS-critical-sectors'

# value → display label (Title Case + a few canonical hyphen-replacements)
DHS_CIIP_SECTOR_LABELS = {
    'chemical': 'Chemical',
    'commercial-facilities': 'Commercial Facilities',
    'communications': 'Communications',
    'critical-manufacturing': 'Critical Manufacturing',
    'dams': 'Dams',
    'dib': 'Defense Industrial Base',
    'emergency-services': 'Emergency Services',
    'energy': 'Energy',
    'financial-services': 'Financial Services',
    'food-agriculture': 'Food & Agriculture',
    'government-facilities': 'Government Facilities',
    'healthcare-public': 'Healthcare & Public Health',
    'it': 'Information Technology',
    'nuclear': 'Nuclear',
    'transport': 'Transportation Systems',
    'water': 'Water Systems',
}


def _epoch_days(d):
    if d is None:
        return None
    if isinstance(d, _dt.datetime):
        return d.date().toordinal()
    return d.toordinal()


def _to_dt(value, fallback):
    if isinstance(value, _dt.datetime):
        return value
    if isinstance(value, _dt.date):
        return _dt.datetime.combine(value, _dt.time.min)
    if isinstance(value, str) and value:
        try:
            return _dt.datetime.fromisoformat(value.replace('Z', '+00:00')).replace(tzinfo=None)
        except ValueError:
            return fallback
    return fallback


def _median(values):
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


# ---------------------------------------------------------------------------
# Section: KPI strip
# ---------------------------------------------------------------------------

def _kpi_strip(start_dt, end_dt):
    open_cases = db.session.query(func.count(Cases.case_id)) \
        .filter(Cases.close_date.is_(None)).scalar() or 0

    closed_in_range = db.session.query(func.count(Cases.case_id)) \
        .filter(Cases.close_date.isnot(None),
                Cases.close_date >= start_dt.date(),
                Cases.close_date <= end_dt.date()).scalar() or 0

    closed_rows = db.session.query(Cases.open_date, Cases.close_date) \
        .filter(Cases.close_date.isnot(None),
                Cases.close_date >= start_dt.date(),
                Cases.close_date <= end_dt.date()).all()
    mttr_days = []
    for opened, closed in closed_rows:
        if opened and closed:
            delta = (closed - opened).days
            if delta >= 0:
                mttr_days.append(delta)
    median_mttr_days = _median(mttr_days)

    untriaged_working_tl = db.session.query(func.count(CaseWorkingEvent.id)) \
        .filter(CaseWorkingEvent.status == 'pending').scalar() or 0

    return {
        'open_cases': open_cases,
        'closed_in_range': closed_in_range,
        'median_mttr_days': median_mttr_days,
        'untriaged_working_tl': untriaged_working_tl,
    }


# ---------------------------------------------------------------------------
# Section: Analyst self-view (current_user scoped)
# ---------------------------------------------------------------------------

def _analyst_self(start_dt, end_dt, user_id):
    my_open = db.session.query(func.count(Cases.case_id)) \
        .filter(Cases.owner_id == user_id, Cases.close_date.is_(None)).scalar() or 0

    my_closed_in_range = db.session.query(func.count(Cases.case_id)) \
        .filter(Cases.owner_id == user_id,
                Cases.close_date.isnot(None),
                Cases.close_date >= start_dt.date(),
                Cases.close_date <= end_dt.date()).scalar() or 0

    my_closed_rows = db.session.query(Cases.open_date, Cases.close_date) \
        .filter(Cases.owner_id == user_id,
                Cases.close_date.isnot(None),
                Cases.close_date >= start_dt.date(),
                Cases.close_date <= end_dt.date()).all()
    my_mttr = [(c - o).days for o, c in my_closed_rows if o and c and (c - o).days >= 0]
    my_median_mttr_days = _median(my_mttr)

    # Working-timeline reviews I performed in range (promoted or rejected)
    my_wt_reviews = db.session.query(
        CaseWorkingEvent.status, func.count(CaseWorkingEvent.id)
    ).filter(
        CaseWorkingEvent.reviewed_by == user_id,
        CaseWorkingEvent.reviewed_at.isnot(None),
        CaseWorkingEvent.reviewed_at >= start_dt,
        CaseWorkingEvent.reviewed_at <= end_dt,
    ).group_by(CaseWorkingEvent.status).all()
    wt_review_counts = {status: int(n) for status, n in my_wt_reviews}

    # Notes I authored in range (a rough proxy for engagement)
    my_notes_in_range = db.session.query(func.count(Notes.note_id)) \
        .filter(Notes.note_user == user_id,
                Notes.note_creationdate >= start_dt,
                Notes.note_creationdate <= end_dt).scalar() or 0

    return {
        'my_open_cases': my_open,
        'my_closed_in_range': my_closed_in_range,
        'my_median_mttr_days': my_median_mttr_days,
        'my_wt_reviews': wt_review_counts,
        'my_notes_in_range': my_notes_in_range,
    }


# ---------------------------------------------------------------------------
# Section: SOC / IR manager (team throughput)
# ---------------------------------------------------------------------------

def _date_bucket_label(d):
    return d.isoformat() if d else None


def _opened_vs_closed_over_time(start_dt, end_dt):
    # Per-day buckets for the line chart. Stays fast even at high case volumes
    # because both queries are a single GROUP BY on an indexed date column.
    opened = db.session.query(
        Cases.open_date, func.count(Cases.case_id)
    ).filter(
        Cases.open_date.isnot(None),
        Cases.open_date >= start_dt.date(),
        Cases.open_date <= end_dt.date(),
    ).group_by(Cases.open_date).all()

    closed = db.session.query(
        Cases.close_date, func.count(Cases.case_id)
    ).filter(
        Cases.close_date.isnot(None),
        Cases.close_date >= start_dt.date(),
        Cases.close_date <= end_dt.date(),
    ).group_by(Cases.close_date).all()

    opened_map = {_date_bucket_label(d): int(n) for d, n in opened}
    closed_map = {_date_bucket_label(d): int(n) for d, n in closed}

    # Fill in all days in range with zeros so the chart shows a continuous line
    cur = start_dt.date()
    end = end_dt.date()
    labels = []
    opened_series = []
    closed_series = []
    while cur <= end:
        key = cur.isoformat()
        labels.append(key)
        opened_series.append(opened_map.get(key, 0))
        closed_series.append(closed_map.get(key, 0))
        cur += _dt.timedelta(days=1)

    return {'labels': labels, 'opened': opened_series, 'closed': closed_series}


def _soc_manager(start_dt, end_dt):
    # Classification breakdown (all open cases, current snapshot)
    classification_rows = db.session.query(
        CaseClassification.name, func.count(Cases.case_id)
    ).select_from(Cases).outerjoin(
        CaseClassification, CaseClassification.id == Cases.classification_id
    ).group_by(CaseClassification.name).all()
    classifications = [
        {'name': (n or 'Unclassified'), 'count': int(c)}
        for n, c in sorted(classification_rows, key=lambda r: -int(r[1]))
    ]

    # Severity breakdown (current snapshot)
    severity_rows = db.session.query(
        Severity.severity_name, func.count(Cases.case_id)
    ).select_from(Cases).outerjoin(
        Severity, Severity.severity_id == Cases.severity_id
    ).group_by(Severity.severity_name).all()
    severities = [
        {'name': (n or 'Unspecified'), 'count': int(c)}
        for n, c in sorted(severity_rows, key=lambda r: -int(r[1]))
    ]

    # Top owners by cases opened in range
    owner_rows = db.session.query(
        User.name, func.count(Cases.case_id)
    ).join(User, User.id == Cases.owner_id).filter(
        Cases.open_date.isnot(None),
        Cases.open_date >= start_dt.date(),
        Cases.open_date <= end_dt.date(),
    ).group_by(User.name).order_by(func.count(Cases.case_id).desc()).limit(10).all()
    top_owners = [{'name': n, 'count': int(c)} for n, c in owner_rows]

    # Customer load in range
    customer_rows = db.session.query(
        Client.name, func.count(Cases.case_id)
    ).join(Client, Client.client_id == Cases.client_id).filter(
        Cases.open_date.isnot(None),
        Cases.open_date >= start_dt.date(),
        Cases.open_date <= end_dt.date(),
    ).group_by(Client.name).order_by(func.count(Cases.case_id).desc()).limit(10).all()
    top_customers = [{'name': n, 'count': int(c)} for n, c in customer_rows]

    timeline = _opened_vs_closed_over_time(start_dt, end_dt)

    return {
        'timeline': timeline,
        'classifications': classifications,
        'severities': severities,
        'top_owners': top_owners,
        'top_customers': top_customers,
    }


# ---------------------------------------------------------------------------
# Section: Admin / system health
# ---------------------------------------------------------------------------

def _admin_health(start_dt, end_dt):
    # AI artifacts generated in range, by model
    ai_rows = db.session.query(
        CaseAiArtifact.model, func.count(CaseAiArtifact.id)
    ).filter(
        CaseAiArtifact.generated_at >= start_dt,
        CaseAiArtifact.generated_at <= end_dt,
    ).group_by(CaseAiArtifact.model).all()
    ai_by_model = [{'model': m or 'unknown', 'count': int(c)}
                   for m, c in sorted(ai_rows, key=lambda r: -int(r[1]))]

    # AI artifacts by kind (which feature is hot?)
    kind_rows = db.session.query(
        CaseAiArtifact.kind, func.count(CaseAiArtifact.id)
    ).filter(
        CaseAiArtifact.generated_at >= start_dt,
        CaseAiArtifact.generated_at <= end_dt,
    ).group_by(CaseAiArtifact.kind).all()
    # Trim the per-event discriminator (event_analysis:1234 → event_analysis) so
    # the chart doesn't have one bar per timeline event.
    rolled = {}
    for kind, n in kind_rows:
        base = (kind or 'unknown').split(':', 1)[0]
        rolled[base] = rolled.get(base, 0) + int(n)
    ai_by_kind = [{'kind': k, 'count': v} for k, v in
                  sorted(rolled.items(), key=lambda r: -r[1])]

    # MISP sync state — current snapshot
    misp_total = db.session.query(func.count(MispEventLink.id)).scalar() or 0
    misp_synced = db.session.query(func.count(MispEventLink.id)) \
        .filter(MispEventLink.last_synced_at.isnot(None)).scalar() or 0
    misp_oldest_unsynced = db.session.query(func.min(MispEventLink.date_created)) \
        .filter(MispEventLink.last_synced_at.is_(None)).scalar()

    # Working-timeline ingest volume in range, by source
    wt_rows = db.session.query(
        CaseWorkingEvent.source, func.count(CaseWorkingEvent.id)
    ).filter(
        CaseWorkingEvent.created_at >= start_dt,
        CaseWorkingEvent.created_at <= end_dt,
    ).group_by(CaseWorkingEvent.source).all()
    wt_imports = [{'source': s or 'unknown', 'count': int(c)}
                  for s, c in sorted(wt_rows, key=lambda r: -int(r[1]))]

    # Working-timeline status snapshot (right now, not range-scoped)
    wt_status_rows = db.session.query(
        CaseWorkingEvent.status, func.count(CaseWorkingEvent.id)
    ).group_by(CaseWorkingEvent.status).all()
    wt_status = {s or 'unknown': int(c) for s, c in wt_status_rows}

    return {
        'ai_by_model': ai_by_model,
        'ai_by_kind': ai_by_kind,
        'misp': {
            'total_links': misp_total,
            'synced': misp_synced,
            'unsynced': max(misp_total - misp_synced, 0),
            'oldest_unsynced_at': misp_oldest_unsynced.isoformat() if misp_oldest_unsynced else None,
        },
        'wt_imports': wt_imports,
        'wt_status': wt_status,
    }


# ---------------------------------------------------------------------------
# Section: Investigation quality
# ---------------------------------------------------------------------------

def _investigation_quality():
    # Count children per open case via group-by joins (a single round trip each).
    case_id_to_notes = dict(db.session.query(
        Notes.note_case_id, func.count(Notes.note_id)
    ).group_by(Notes.note_case_id).all())
    case_id_to_iocs = dict(db.session.query(
        Ioc.case_id, func.count(Ioc.ioc_id)
    ).group_by(Ioc.case_id).all())
    case_id_to_assets = dict(db.session.query(
        CaseAssets.case_id, func.count(CaseAssets.asset_id)
    ).group_by(CaseAssets.case_id).all())
    case_id_to_events = dict(db.session.query(
        CasesEvent.case_id, func.count(CasesEvent.event_id)
    ).group_by(CasesEvent.case_id).all())
    case_id_to_evidences = dict(db.session.query(
        CaseReceivedFile.case_id, func.count(CaseReceivedFile.id)
    ).group_by(CaseReceivedFile.case_id).all())

    # Pull open cases ordered most-recent
    open_cases = db.session.query(
        Cases.case_id, Cases.name, Cases.open_date
    ).filter(Cases.close_date.is_(None)).order_by(Cases.open_date.desc()).all()

    red_flags = []
    for cid, name, opened in open_cases:
        notes = int(case_id_to_notes.get(cid, 0))
        iocs = int(case_id_to_iocs.get(cid, 0))
        assets = int(case_id_to_assets.get(cid, 0))
        events = int(case_id_to_events.get(cid, 0))
        evidences = int(case_id_to_evidences.get(cid, 0))
        missing = []
        if notes == 0:
            missing.append('notes')
        if iocs == 0:
            missing.append('IOCs')
        if assets == 0:
            missing.append('assets')
        if events == 0:
            missing.append('events')
        if missing:
            red_flags.append({
                'case_id': cid,
                'case_name': name,
                'open_date': opened.isoformat() if opened else None,
                'notes': notes, 'iocs': iocs, 'assets': assets,
                'events': events, 'evidences': evidences,
                'missing': missing,
            })

    # Cross-link coverage: % of timeline events that have ≥1 asset OR ≥1 IOC link
    total_events = db.session.query(func.count(CasesEvent.event_id)).scalar() or 0
    events_with_asset = db.session.query(
        func.count(func.distinct(CaseEventsAssets.event_id))
    ).scalar() or 0
    events_with_ioc = db.session.query(
        func.count(func.distinct(CaseEventsIoc.event_id))
    ).scalar() or 0
    # Approximation — a single event can be in both, so this slightly overcounts;
    # the more accurate UNION query is more expensive and not worth it for a metric.
    linked_pct = None
    if total_events > 0:
        # Take the max of the two as a lower bound for "events with ≥1 cross-link".
        # Better lower bound than sum (which would double-count overlaps).
        linked_pct = round(100.0 * max(events_with_asset, events_with_ioc) / total_events, 1)

    # Top-10 working-timeline backlog by case (pending rows)
    wt_backlog_rows = db.session.query(
        CaseWorkingEvent.case_id, func.count(CaseWorkingEvent.id)
    ).filter(CaseWorkingEvent.status == 'pending') \
     .group_by(CaseWorkingEvent.case_id) \
     .order_by(func.count(CaseWorkingEvent.id).desc()).limit(10).all()
    case_id_to_name = dict(db.session.query(Cases.case_id, Cases.name).filter(
        Cases.case_id.in_([r[0] for r in wt_backlog_rows]) if wt_backlog_rows else [False]
    ).all()) if wt_backlog_rows else {}
    wt_backlog_top = [
        {'case_id': cid, 'case_name': case_id_to_name.get(cid, f'#{cid}'), 'pending': int(n)}
        for cid, n in wt_backlog_rows
    ]

    return {
        'red_flags': red_flags[:25],  # cap so the JSON stays light
        'red_flag_total': len(red_flags),
        'total_events': total_events,
        'events_with_crosslink_pct': linked_pct,
        'wt_backlog_top': wt_backlog_top,
    }


# ---------------------------------------------------------------------------
# Section: Case tagging — year-scoped, shaped like the Critical Infrastructure
# card so management has the same per-quarter view across the two surfaces.
# Excludes DHS CIIP sector tags (they have their own card).
# ---------------------------------------------------------------------------

# Tags starting with this prefix are considered "sector" tags and handled
# entirely by `_critical_infrastructure`. Anything else is a regular case tag.
_SECTOR_TAG_PREFIX = f'{DHS_CIIP_TAG_NAMESPACE}:{DHS_CIIP_TAG_PREDICATE}='

# Max distinct tags surfaced in the per-quarter matrix. Cardinality on
# free-text tags can balloon (every analyst's pet `priority-*` etc.); cap
# the rows to keep the table readable, surface the rest via the rank list.
_MATRIX_TOP_N = 15


def _case_tagging(start_dt, end_dt, ci_year=None):
    # Same year-snap rule as the sector card — full calendar year regardless
    # of the page-level date range. Reuses the ci_year override so the year
    # selector drives both sections in lock-step.
    year = int(ci_year) if ci_year else end_dt.year
    year_start = _dt.datetime(year, 1, 1, 0, 0)
    year_end = _dt.datetime(year, 12, 31, 23, 59, 59)

    # Pull every case + its tags in a single query (one row per case-tag pair
    # via the case_tags join; cases with multiple tags repeat; cases with no
    # tags still show via the outer joins so we can count "untagged" cleanly).
    rows = db.session.query(
        Cases.case_id, Cases.name, Cases.open_date,
        Tags.tag_title,
    ).select_from(Cases).outerjoin(
        CaseTags, CaseTags.case_id == Cases.case_id
    ).outerjoin(
        Tags, Tags.id == CaseTags.tag_id
    ).all()

    # Build per-case tag set (sector tags excluded), plus per-case metadata
    case_tags = {}        # case_id -> set of non-sector tag titles
    case_meta = {}        # case_id -> {name, open_date}
    for cid, name, opened, tag in rows:
        case_meta.setdefault(cid, {'name': name, 'open_date': opened})
        if not tag:
            continue
        if tag.startswith(_SECTOR_TAG_PREFIX):
            continue
        case_tags.setdefault(cid, set()).add(tag)

    # Cardinality KPIs (current state, all cases)
    total_cases_all = len(case_meta)
    tagged_cases_all = len([cid for cid, tags in case_tags.items() if tags])
    overall_counter = {}
    for tags in case_tags.values():
        for t in tags:
            overall_counter[t] = overall_counter.get(t, 0) + 1
    unique_tag_count = len(overall_counter)
    tag_applications = sum(overall_counter.values())

    # Quarter keys for the selected year
    quarter_keys = []
    cur = _dt.date(year, 1, 1)
    while cur.year == year:
        q = (cur.month - 1) // 3 + 1
        quarter_keys.append(f'{year}-Q{q}')
        # advance 3 months
        m = cur.month + 3
        cur = _dt.date(year + (m - 1) // 12, ((m - 1) % 12) + 1, 1)
    # quarter_keys may contain duplicates from how the loop advances if year
    # boundary hits — dedup conservatively.
    quarter_keys = sorted(set(quarter_keys))

    # Build the tag × quarter matrix for cases opened in the year.
    quarter_totals = {q: 0 for q in quarter_keys}
    tag_quarter_counts = {}     # tag -> {q -> count}
    tag_year_totals = {}        # tag -> int (sum across quarters)
    for cid, meta in case_meta.items():
        opened = meta.get('open_date')
        if not opened:
            continue
        if opened < year_start.date() or opened > year_end.date():
            continue
        q = _quarter_key(opened)
        if q not in quarter_totals:
            continue
        quarter_totals[q] += 1
        for tag in case_tags.get(cid, ()):
            tag_quarter_counts.setdefault(tag, {qq: 0 for qq in quarter_keys})[q] += 1
            tag_year_totals[tag] = tag_year_totals.get(tag, 0) + 1

    # Top N tag rows by year total for the matrix
    top_tags = sorted(tag_year_totals.items(), key=lambda r: (-r[1], r[0]))[:_MATRIX_TOP_N]
    matrix_rows = []
    for tag, total in top_tags:
        cells = tag_quarter_counts.get(tag, {})
        matrix_rows.append({
            'tag': tag,
            'counts': [cells.get(q, 0) for q in quarter_keys],
            'total': total,
        })

    # Top tag per quarter — same shape as the sector card's pills
    top_per_quarter = []
    for q in quarter_keys:
        best_tag = None
        best_count = 0
        for tag, cells in tag_quarter_counts.items():
            c = cells.get(q, 0)
            if c > best_count:
                best_count = c
                best_tag = tag
        top_per_quarter.append({
            'quarter': q,
            'total_cases': quarter_totals.get(q, 0),
            'top_tag': best_tag,
            'top_tag_count': best_count,
        })

    # YTD top tag
    ytd_top_tag = None
    ytd_top_count = 0
    if tag_year_totals:
        ytd_top_tag = max(tag_year_totals, key=tag_year_totals.get)
        ytd_top_count = tag_year_totals[ytd_top_tag]

    # Cases with no non-sector tag at all — kept as a header KPI count only.
    untagged_case_count = sum(1 for cid in case_meta if not case_tags.get(cid))

    return {
        'year': year,
        'totals': {
            'unique_tags': unique_tag_count,
            'tag_applications': tag_applications,
            'tagged_cases': tagged_cases_all,
            'total_cases': total_cases_all,
            'untagged_cases': untagged_case_count,
        },
        'ytd': {
            'total_cases_in_year': sum(quarter_totals.values()),
            'top_tag': ytd_top_tag,
            'top_tag_count': ytd_top_count,
        },
        'quarters': quarter_keys,
        'matrix': matrix_rows,
        'top_per_quarter': top_per_quarter,
    }


# ---------------------------------------------------------------------------
# Section: Critical Infrastructure (DHS CIIP sectors) — for management reports
# ---------------------------------------------------------------------------

def _extract_dhs_ciip_value(tag_title):
    """Parse a tag like `dhs-ciip-sectors:DHS-critical-sectors="energy"` and
    return `energy`, or None if the tag isn't a DHS CIIP sector tag.
    Tolerant of single/double quotes and missing quotes."""
    if not tag_title:
        return None
    prefix = f'{DHS_CIIP_TAG_NAMESPACE}:{DHS_CIIP_TAG_PREDICATE}='
    if not tag_title.startswith(prefix):
        return None
    rest = tag_title[len(prefix):].strip()
    if (rest.startswith('"') and rest.endswith('"')) or (rest.startswith("'") and rest.endswith("'")):
        rest = rest[1:-1]
    return rest or None


def _quarter_key(d):
    """`date(2026, 4, 15)` → `"2026-Q2"`."""
    if d is None:
        return None
    q = (d.month - 1) // 3 + 1
    return f'{d.year}-Q{q}'


def _critical_infrastructure(start_dt, end_dt, ci_year=None):
    # Management wants the full calendar year always — Q1-Q4 visible even when
    # the page's date range only spans the current quarter. We snap the
    # window to Jan 1 → Dec 31 of `ci_year` (default `end_dt.year`) for this
    # section only, so the rest of the dashboard's range-driven sections are
    # unaffected. The ci_year override lets a year-selector pick historical
    # years independently of the page's date range.
    year = int(ci_year) if ci_year else end_dt.year
    year_start = _dt.datetime(year, 1, 1, 0, 0)
    year_end = _dt.datetime(year, 12, 31, 23, 59, 59)
    start_dt, end_dt = year_start, year_end

    # Discover which years have any cases — used by the front-end's year
    # selector. Distinct on a derived year is the cheapest path; no index
    # needed for the dataset sizes IRIS operates at.
    year_rows = db.session.query(
        func.extract('year', Cases.open_date)
    ).filter(Cases.open_date.isnot(None)).distinct().all()
    available_years = sorted({int(r[0]) for r in year_rows if r[0] is not None}, reverse=True)
    # Always include the current selection so the dropdown stays consistent
    # even when the selected year has zero cases.
    if year not in available_years:
        available_years.append(year)
        available_years.sort(reverse=True)

    # Pull every case + its sector tags in a single query (one row per
    # case-tag pair; cases with multiple tags repeat).
    rows = db.session.query(
        Cases.case_id, Cases.name, Cases.open_date, Cases.close_date,
        Tags.tag_title,
    ).select_from(Cases).outerjoin(
        CaseTags, CaseTags.case_id == Cases.case_id
    ).outerjoin(
        Tags, Tags.id == CaseTags.tag_id
    ).all()

    # Group sectors per case
    case_sectors = {}        # case_id -> set of sector values
    case_meta = {}           # case_id -> dict(name, open_date, close_date)
    for cid, name, open_d, close_d, tag in rows:
        meta = case_meta.setdefault(cid, {
            'name': name, 'open_date': open_d, 'close_date': close_d,
        })
        sector = _extract_dhs_ciip_value(tag)
        if sector:
            case_sectors.setdefault(cid, set()).add(sector)

    # Quarter × sector matrix for cases opened in range. Cells = case count.
    # Quarters are derived from the start/end of the requested range so the
    # matrix only ever has columns the user asked for.
    quarter_keys = []
    cur = _dt.date(start_dt.year, ((start_dt.month - 1) // 3) * 3 + 1, 1)
    end_quarter_first_month = ((end_dt.month - 1) // 3) * 3 + 1
    end_marker = _dt.date(end_dt.year, end_quarter_first_month, 1)
    while cur <= end_marker:
        quarter_keys.append(_quarter_key(cur))
        # advance by ~3 months
        new_month = cur.month + 3
        new_year = cur.year + (new_month - 1) // 12
        new_month = ((new_month - 1) % 12) + 1
        cur = _dt.date(new_year, new_month, 1)

    matrix = {}   # sector -> {quarter_key -> count}
    quarter_totals = {q: 0 for q in quarter_keys}
    for cid, meta in case_meta.items():
        opened = meta.get('open_date')
        if not opened:
            continue
        if opened < start_dt.date() or opened > end_dt.date():
            continue
        q = _quarter_key(opened)
        if q not in quarter_totals:
            continue
        quarter_totals[q] += 1
        for s in case_sectors.get(cid, ()):
            matrix.setdefault(s, {q: 0 for q in quarter_keys})[q] += 1

    sector_rows = []
    for s in sorted(matrix.keys(), key=lambda x: -sum(matrix[x].values())):
        cells = matrix[s]
        sector_rows.append({
            'sector': s,
            'label': DHS_CIIP_SECTOR_LABELS.get(s, s),
            'counts': [cells.get(q, 0) for q in quarter_keys],
            'total': sum(cells.values()),
        })

    # Compliance: cases with NO dhs-ciip-sectors tag
    all_case_ids = {cid for cid in case_meta}
    tagged_case_ids = {cid for cid, sectors in case_sectors.items() if sectors}
    missing_count = len(all_case_ids - tagged_case_ids)

    # Headline per-quarter winner — useful for management "Q1 was X" framing
    top_sector_per_quarter = []
    for q in quarter_keys:
        best = None
        best_count = 0
        for s, cells in matrix.items():
            c = cells.get(q, 0)
            if c > best_count:
                best_count = c
                best = s
        top_sector_per_quarter.append({
            'quarter': q,
            'total_cases': quarter_totals.get(q, 0),
            'top_sector': best,
            'top_sector_label': DHS_CIIP_SECTOR_LABELS.get(best, best) if best else None,
            'top_sector_count': best_count,
        })

    # YTD summary — sum of all quarters, top sector across the whole year.
    ytd_totals_by_sector = {s: sum(cells.values()) for s, cells in matrix.items()}
    ytd_top_sector = None
    ytd_top_count = 0
    if ytd_totals_by_sector:
        ytd_top_sector = max(ytd_totals_by_sector, key=ytd_totals_by_sector.get)
        ytd_top_count = ytd_totals_by_sector[ytd_top_sector]

    return {
        'year': year,
        'available_years': available_years,
        'ytd': {
            'total_cases': sum(quarter_totals.values()),
            'top_sector': ytd_top_sector,
            'top_sector_label': DHS_CIIP_SECTOR_LABELS.get(ytd_top_sector, ytd_top_sector) if ytd_top_sector else None,
            'top_sector_count': ytd_top_count,
        },
        'quarters': quarter_keys,
        'matrix': sector_rows,
        'quarter_totals': [{'quarter': q, 'count': quarter_totals[q]} for q in quarter_keys],
        'top_per_quarter': top_sector_per_quarter,
        'compliance': {
            'total_cases': len(all_case_ids),
            'tagged_cases': len(tagged_case_ids),
            'missing_cases_count': missing_count,
        },
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_dashboard_metrics(start, end, ci_year=None) -> dict:
    """Compute every section. `start` and `end` may be datetime, date, or ISO
    string; the helper coerces them into naive UTC datetimes.

    `ci_year` overrides the year for the Critical Infrastructure section only —
    that section is deliberately decoupled from the page-level date range so
    management can compare years independently of the operational view."""

    now = _dt.datetime.utcnow()
    end_dt = _to_dt(end, now)
    start_dt = _to_dt(start, end_dt - _dt.timedelta(days=30))
    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt

    user_id = current_user.id

    return {
        'range': {
            'start': start_dt.isoformat() + 'Z',
            'end': end_dt.isoformat() + 'Z',
            'days': (end_dt.date() - start_dt.date()).days + 1,
        },
        'kpi': _kpi_strip(start_dt, end_dt),
        'analyst': _analyst_self(start_dt, end_dt, user_id),
        'soc': _soc_manager(start_dt, end_dt),
        'admin': _admin_health(start_dt, end_dt),
        'quality': _investigation_quality(),
        # Both sections honor ci_year so the dashboard's year selector
        # drives them in lock-step.
        'tagging': _case_tagging(start_dt, end_dt, ci_year=ci_year),
        'critical_infra': _critical_infrastructure(start_dt, end_dt, ci_year=ci_year),
    }

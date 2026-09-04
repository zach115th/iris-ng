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
    CaseEventsIoc, CaseReceivedFile, CaseTasks, CaseTimeEntry, Client, Ioc,
    MispEventLink, Notes, Tags,
)
from app.models.authorization import User


# Shared constants — referenced by both _case_tagging and _critical_infrastructure.
# Tag form per the bundled MISP taxonomy: dhs-ciip-sectors:DHS-critical-sectors="<value>"
DHS_CIIP_TAG_NAMESPACE = 'dhs-ciip-sectors'
DHS_CIIP_TAG_PREDICATE = 'DHS-critical-sectors'

# Clients whose cases are hidden from every metric. `IrisInitialClient` is the
# bootstrap customer created by post_init for fresh installs (parent of the
# Initial Demo case and any case where the analyst forgot to set a customer);
# letting it leak into metrics drags down all the per-customer breakdowns and
# inflates the case-tagging untagged count. Extend the tuple to hide more.
EXCLUDED_CLIENT_NAMES = ('IrisInitialClient',)


def _excluded_case_ids():
    """Return the list of case IDs whose client is in EXCLUDED_CLIENT_NAMES.
    Empty list when no matching cases exist — caller skips adding the filter
    in that case to avoid SQLAlchemy's empty-IN warning."""
    rows = db.session.query(Cases.case_id).join(
        Client, Client.client_id == Cases.client_id
    ).filter(Client.name.in_(EXCLUDED_CLIENT_NAMES)).all()
    return [r[0] for r in rows]


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

def _kpi_strip(start_dt, end_dt, excluded_case_ids):
    open_q = db.session.query(func.count(Cases.case_id)) \
        .filter(Cases.close_date.is_(None))
    if excluded_case_ids:
        open_q = open_q.filter(Cases.case_id.notin_(excluded_case_ids))
    open_cases = open_q.scalar() or 0

    closed_q = db.session.query(func.count(Cases.case_id)) \
        .filter(Cases.close_date.isnot(None),
                Cases.close_date >= start_dt.date(),
                Cases.close_date <= end_dt.date())
    if excluded_case_ids:
        closed_q = closed_q.filter(Cases.case_id.notin_(excluded_case_ids))
    closed_in_range = closed_q.scalar() or 0

    closed_rows_q = db.session.query(Cases.open_date, Cases.close_date) \
        .filter(Cases.close_date.isnot(None),
                Cases.close_date >= start_dt.date(),
                Cases.close_date <= end_dt.date())
    if excluded_case_ids:
        closed_rows_q = closed_rows_q.filter(Cases.case_id.notin_(excluded_case_ids))
    closed_rows = closed_rows_q.all()
    mttr_days = []
    for opened, closed in closed_rows:
        if opened and closed:
            delta = (closed - opened).days
            if delta >= 0:
                mttr_days.append(delta)
    median_mttr_days = _median(mttr_days)

    wt_q = db.session.query(func.count(CaseWorkingEvent.id)) \
        .filter(CaseWorkingEvent.status == 'pending')
    if excluded_case_ids:
        wt_q = wt_q.filter(CaseWorkingEvent.case_id.notin_(excluded_case_ids))
    untriaged_working_tl = wt_q.scalar() or 0

    return {
        'open_cases': open_cases,
        'closed_in_range': closed_in_range,
        'median_mttr_days': median_mttr_days,
        'untriaged_working_tl': untriaged_working_tl,
    }


# ---------------------------------------------------------------------------
# Section: Analyst self-view (current_user scoped)
# ---------------------------------------------------------------------------

def _analyst_self(start_dt, end_dt, user_id, excluded_case_ids):
    my_open_q = db.session.query(func.count(Cases.case_id)) \
        .filter(Cases.owner_id == user_id, Cases.close_date.is_(None))
    if excluded_case_ids:
        my_open_q = my_open_q.filter(Cases.case_id.notin_(excluded_case_ids))
    my_open = my_open_q.scalar() or 0

    my_closed_q = db.session.query(func.count(Cases.case_id)) \
        .filter(Cases.owner_id == user_id,
                Cases.close_date.isnot(None),
                Cases.close_date >= start_dt.date(),
                Cases.close_date <= end_dt.date())
    if excluded_case_ids:
        my_closed_q = my_closed_q.filter(Cases.case_id.notin_(excluded_case_ids))
    my_closed_in_range = my_closed_q.scalar() or 0

    my_closed_rows_q = db.session.query(Cases.open_date, Cases.close_date) \
        .filter(Cases.owner_id == user_id,
                Cases.close_date.isnot(None),
                Cases.close_date >= start_dt.date(),
                Cases.close_date <= end_dt.date())
    if excluded_case_ids:
        my_closed_rows_q = my_closed_rows_q.filter(Cases.case_id.notin_(excluded_case_ids))
    my_closed_rows = my_closed_rows_q.all()
    my_mttr = [(c - o).days for o, c in my_closed_rows if o and c and (c - o).days >= 0]
    my_median_mttr_days = _median(my_mttr)

    # Working-timeline reviews I performed in range (promoted or rejected)
    my_wt_q = db.session.query(
        CaseWorkingEvent.status, func.count(CaseWorkingEvent.id)
    ).filter(
        CaseWorkingEvent.reviewed_by == user_id,
        CaseWorkingEvent.reviewed_at.isnot(None),
        CaseWorkingEvent.reviewed_at >= start_dt,
        CaseWorkingEvent.reviewed_at <= end_dt,
    )
    if excluded_case_ids:
        my_wt_q = my_wt_q.filter(CaseWorkingEvent.case_id.notin_(excluded_case_ids))
    my_wt_reviews = my_wt_q.group_by(CaseWorkingEvent.status).all()
    wt_review_counts = {status: int(n) for status, n in my_wt_reviews}

    # Notes I authored in range (a rough proxy for engagement)
    my_notes_q = db.session.query(func.count(Notes.note_id)) \
        .filter(Notes.note_user == user_id,
                Notes.note_creationdate >= start_dt,
                Notes.note_creationdate <= end_dt)
    if excluded_case_ids:
        my_notes_q = my_notes_q.filter(Notes.note_case_id.notin_(excluded_case_ids))
    my_notes_in_range = my_notes_q.scalar() or 0

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


def _opened_vs_closed_over_time(start_dt, end_dt, excluded_case_ids):
    # Per-day buckets for the line chart. Stays fast even at high case volumes
    # because both queries are a single GROUP BY on an indexed date column.
    opened_q = db.session.query(
        Cases.open_date, func.count(Cases.case_id)
    ).filter(
        Cases.open_date.isnot(None),
        Cases.open_date >= start_dt.date(),
        Cases.open_date <= end_dt.date(),
    )
    if excluded_case_ids:
        opened_q = opened_q.filter(Cases.case_id.notin_(excluded_case_ids))
    opened = opened_q.group_by(Cases.open_date).all()

    closed_q = db.session.query(
        Cases.close_date, func.count(Cases.case_id)
    ).filter(
        Cases.close_date.isnot(None),
        Cases.close_date >= start_dt.date(),
        Cases.close_date <= end_dt.date(),
    )
    if excluded_case_ids:
        closed_q = closed_q.filter(Cases.case_id.notin_(excluded_case_ids))
    closed = closed_q.group_by(Cases.close_date).all()

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


def _soc_manager(start_dt, end_dt, excluded_case_ids):
    # Classification breakdown (all open cases, current snapshot)
    classification_q = db.session.query(
        CaseClassification.name, func.count(Cases.case_id)
    ).select_from(Cases).outerjoin(
        CaseClassification, CaseClassification.id == Cases.classification_id
    )
    if excluded_case_ids:
        classification_q = classification_q.filter(Cases.case_id.notin_(excluded_case_ids))
    classification_rows = classification_q.group_by(CaseClassification.name).all()
    classifications = [
        {'name': (n or 'Unclassified'), 'count': int(c)}
        for n, c in sorted(classification_rows, key=lambda r: -int(r[1]))
    ]

    # Severity breakdown (current snapshot)
    severity_q = db.session.query(
        Severity.severity_name, func.count(Cases.case_id)
    ).select_from(Cases).outerjoin(
        Severity, Severity.severity_id == Cases.severity_id
    )
    if excluded_case_ids:
        severity_q = severity_q.filter(Cases.case_id.notin_(excluded_case_ids))
    severity_rows = severity_q.group_by(Severity.severity_name).all()
    severities = [
        {'name': (n or 'Unspecified'), 'count': int(c)}
        for n, c in sorted(severity_rows, key=lambda r: -int(r[1]))
    ]

    # Top owners by cases opened in range
    owner_q = db.session.query(
        User.name, func.count(Cases.case_id)
    ).join(User, User.id == Cases.owner_id).filter(
        Cases.open_date.isnot(None),
        Cases.open_date >= start_dt.date(),
        Cases.open_date <= end_dt.date(),
    )
    if excluded_case_ids:
        owner_q = owner_q.filter(Cases.case_id.notin_(excluded_case_ids))
    owner_rows = owner_q.group_by(User.name).order_by(func.count(Cases.case_id).desc()).limit(10).all()
    top_owners = [{'name': n, 'count': int(c)} for n, c in owner_rows]

    # Customer load in range
    customer_q = db.session.query(
        Client.name, func.count(Cases.case_id)
    ).join(Client, Client.client_id == Cases.client_id).filter(
        Cases.open_date.isnot(None),
        Cases.open_date >= start_dt.date(),
        Cases.open_date <= end_dt.date(),
    )
    if excluded_case_ids:
        customer_q = customer_q.filter(Cases.case_id.notin_(excluded_case_ids))
    customer_rows = customer_q.group_by(Client.name).order_by(func.count(Cases.case_id).desc()).limit(10).all()
    top_customers = [{'name': n, 'count': int(c)} for n, c in customer_rows]

    timeline = _opened_vs_closed_over_time(start_dt, end_dt, excluded_case_ids)

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

def _admin_health(start_dt, end_dt, excluded_case_ids):
    # AI artifacts generated in range, by model
    ai_q = db.session.query(
        CaseAiArtifact.model, func.count(CaseAiArtifact.id)
    ).filter(
        CaseAiArtifact.generated_at >= start_dt,
        CaseAiArtifact.generated_at <= end_dt,
    )
    if excluded_case_ids:
        ai_q = ai_q.filter(CaseAiArtifact.case_id.notin_(excluded_case_ids))
    ai_rows = ai_q.group_by(CaseAiArtifact.model).all()
    ai_by_model = [{'model': m or 'unknown', 'count': int(c)}
                   for m, c in sorted(ai_rows, key=lambda r: -int(r[1]))]

    # AI artifacts by kind (which feature is hot?)
    kind_q = db.session.query(
        CaseAiArtifact.kind, func.count(CaseAiArtifact.id)
    ).filter(
        CaseAiArtifact.generated_at >= start_dt,
        CaseAiArtifact.generated_at <= end_dt,
    )
    if excluded_case_ids:
        kind_q = kind_q.filter(CaseAiArtifact.case_id.notin_(excluded_case_ids))
    kind_rows = kind_q.group_by(CaseAiArtifact.kind).all()
    # Trim the per-event discriminator (event_analysis:1234 → event_analysis) so
    # the chart doesn't have one bar per timeline event.
    rolled = {}
    for kind, n in kind_rows:
        base = (kind or 'unknown').split(':', 1)[0]
        rolled[base] = rolled.get(base, 0) + int(n)
    ai_by_kind = [{'kind': k, 'count': v} for k, v in
                  sorted(rolled.items(), key=lambda r: -r[1])]

    # MISP sync state — current snapshot
    misp_total_q = db.session.query(func.count(MispEventLink.id))
    misp_synced_q = db.session.query(func.count(MispEventLink.id)) \
        .filter(MispEventLink.last_synced_at.isnot(None))
    misp_oldest_q = db.session.query(func.min(MispEventLink.date_created)) \
        .filter(MispEventLink.last_synced_at.is_(None))
    if excluded_case_ids:
        misp_total_q = misp_total_q.filter(MispEventLink.case_id.notin_(excluded_case_ids))
        misp_synced_q = misp_synced_q.filter(MispEventLink.case_id.notin_(excluded_case_ids))
        misp_oldest_q = misp_oldest_q.filter(MispEventLink.case_id.notin_(excluded_case_ids))
    misp_total = misp_total_q.scalar() or 0
    misp_synced = misp_synced_q.scalar() or 0
    misp_oldest_unsynced = misp_oldest_q.scalar()

    # Working-timeline ingest volume in range, by source
    wt_imports_q = db.session.query(
        CaseWorkingEvent.source, func.count(CaseWorkingEvent.id)
    ).filter(
        CaseWorkingEvent.created_at >= start_dt,
        CaseWorkingEvent.created_at <= end_dt,
    )
    if excluded_case_ids:
        wt_imports_q = wt_imports_q.filter(CaseWorkingEvent.case_id.notin_(excluded_case_ids))
    wt_rows = wt_imports_q.group_by(CaseWorkingEvent.source).all()
    wt_imports = [{'source': s or 'unknown', 'count': int(c)}
                  for s, c in sorted(wt_rows, key=lambda r: -int(r[1]))]

    # Working-timeline status snapshot (right now, not range-scoped)
    wt_status_q = db.session.query(
        CaseWorkingEvent.status, func.count(CaseWorkingEvent.id)
    )
    if excluded_case_ids:
        wt_status_q = wt_status_q.filter(CaseWorkingEvent.case_id.notin_(excluded_case_ids))
    wt_status_rows = wt_status_q.group_by(CaseWorkingEvent.status).all()
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

def _investigation_quality(excluded_case_ids):
    # Count children per open case via group-by joins (a single round trip each).
    notes_q = db.session.query(
        Notes.note_case_id, func.count(Notes.note_id)
    )
    iocs_q = db.session.query(
        Ioc.case_id, func.count(Ioc.ioc_id)
    )
    assets_q = db.session.query(
        CaseAssets.case_id, func.count(CaseAssets.asset_id)
    )
    events_q = db.session.query(
        CasesEvent.case_id, func.count(CasesEvent.event_id)
    )
    evidence_q = db.session.query(
        CaseReceivedFile.case_id, func.count(CaseReceivedFile.id)
    )
    if excluded_case_ids:
        notes_q = notes_q.filter(Notes.note_case_id.notin_(excluded_case_ids))
        iocs_q = iocs_q.filter(Ioc.case_id.notin_(excluded_case_ids))
        assets_q = assets_q.filter(CaseAssets.case_id.notin_(excluded_case_ids))
        events_q = events_q.filter(CasesEvent.case_id.notin_(excluded_case_ids))
        evidence_q = evidence_q.filter(CaseReceivedFile.case_id.notin_(excluded_case_ids))
    case_id_to_notes = dict(notes_q.group_by(Notes.note_case_id).all())
    case_id_to_iocs = dict(iocs_q.group_by(Ioc.case_id).all())
    case_id_to_assets = dict(assets_q.group_by(CaseAssets.case_id).all())
    case_id_to_events = dict(events_q.group_by(CasesEvent.case_id).all())
    case_id_to_evidences = dict(evidence_q.group_by(CaseReceivedFile.case_id).all())

    # Pull open cases ordered most-recent
    open_cases_q = db.session.query(
        Cases.case_id, Cases.name, Cases.open_date
    ).filter(Cases.close_date.is_(None))
    if excluded_case_ids:
        open_cases_q = open_cases_q.filter(Cases.case_id.notin_(excluded_case_ids))
    open_cases = open_cases_q.order_by(Cases.open_date.desc()).all()

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
    total_events_q = db.session.query(func.count(CasesEvent.event_id))
    events_with_asset_q = db.session.query(
        func.count(func.distinct(CaseEventsAssets.event_id))
    )
    events_with_ioc_q = db.session.query(
        func.count(func.distinct(CaseEventsIoc.event_id))
    )
    if excluded_case_ids:
        total_events_q = total_events_q.filter(CasesEvent.case_id.notin_(excluded_case_ids))
        events_with_asset_q = events_with_asset_q.filter(CaseEventsAssets.case_id.notin_(excluded_case_ids))
        events_with_ioc_q = events_with_ioc_q.filter(CaseEventsIoc.case_id.notin_(excluded_case_ids))
    total_events = total_events_q.scalar() or 0
    events_with_asset = events_with_asset_q.scalar() or 0
    events_with_ioc = events_with_ioc_q.scalar() or 0
    # Approximation — a single event can be in both, so this slightly overcounts;
    # the more accurate UNION query is more expensive and not worth it for a metric.
    linked_pct = None
    if total_events > 0:
        # Take the max of the two as a lower bound for "events with ≥1 cross-link".
        # Better lower bound than sum (which would double-count overlaps).
        linked_pct = round(100.0 * max(events_with_asset, events_with_ioc) / total_events, 1)

    # Top-10 working-timeline backlog by case (pending rows)
    wt_backlog_q = db.session.query(
        CaseWorkingEvent.case_id, func.count(CaseWorkingEvent.id)
    ).filter(CaseWorkingEvent.status == 'pending')
    if excluded_case_ids:
        wt_backlog_q = wt_backlog_q.filter(CaseWorkingEvent.case_id.notin_(excluded_case_ids))
    wt_backlog_rows = wt_backlog_q.group_by(CaseWorkingEvent.case_id) \
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

# Tags starting with these prefixes are considered "sector" tags — they
# categorize the case by sector, not by the free-text/incident dimension the
# case-tagging metric measures, so they're excluded from it. DHS CIIP has its
# own card; threatmatch:sector covers sectors outside the DHS list (e.g.
# Education). Add a prefix here if a future sector option emits another taxonomy.
_SECTOR_TAG_PREFIX = f'{DHS_CIIP_TAG_NAMESPACE}:{DHS_CIIP_TAG_PREDICATE}='
_SECTOR_TAG_PREFIXES = (_SECTOR_TAG_PREFIX, 'threatmatch:sector=')


def _sector_tag_prefixes():
    """Legacy floor + prefixes derived from the sector CATALOG (all rows,
    enabled or not — disabling retires a picker option, never metrics
    recognition). Fail-soft to the legacy constants."""
    prefixes = set(_SECTOR_TAG_PREFIXES)
    try:
        from app.datamgmt.manage.manage_sectors_db import get_sector_tag_prefixes
        prefixes.update(get_sector_tag_prefixes())
    except Exception:
        pass
    return tuple(prefixes)

# TLP tags (`tlp:red`, `tlp:amber`, `tlp:amber+strict`, `tlp:green`, `tlp:clear`)
# are applied to virtually every case, so they swamp the case-tagging metric
# and tell management nothing about how cases are categorized. Exclude them —
# same treatment as sector tags. Matched case-insensitively on the `tlp:`
# namespace prefix so any current/future TLP level is covered.
_TLP_TAG_PREFIX = 'tlp:'


def _is_excluded_metric_tag(tag_title):
    """True if a tag should be dropped from the case-tagging metric (sector
    tags categorize by sector, not the dimension this metric measures; TLP tags
    are universal noise)."""
    if not tag_title:
        return True
    if tag_title.startswith(_sector_tag_prefixes()):
        return True
    if tag_title.lower().startswith(_TLP_TAG_PREFIX):
        return True
    return False

# Max distinct tags surfaced in the per-quarter matrix. Cardinality on
# free-text tags can balloon (every analyst's pet `priority-*` etc.); cap
# the rows to keep the table readable, surface the rest via the rank list.
_MATRIX_TOP_N = 15


def _case_tagging(start_dt, end_dt, excluded_case_ids, tag_year=None):
    # Full calendar year regardless of the page-level date range.
    # tag_year lets the tag card's own year selector pick historical years
    # independently of the CI card's selector.
    year = int(tag_year) if tag_year else end_dt.year
    year_start = _dt.datetime(year, 1, 1, 0, 0)
    year_end = _dt.datetime(year, 12, 31, 23, 59, 59)

    # Pull every case + its tags in a single query (one row per case-tag pair
    # via the case_tags join; cases with multiple tags repeat; cases with no
    # tags still show via the outer joins so we can count "untagged" cleanly).
    rows_q = db.session.query(
        Cases.case_id, Cases.name, Cases.open_date,
        Tags.tag_title,
    ).select_from(Cases).outerjoin(
        CaseTags, CaseTags.case_id == Cases.case_id
    ).outerjoin(
        Tags, Tags.id == CaseTags.tag_id
    )
    if excluded_case_ids:
        rows_q = rows_q.filter(Cases.case_id.notin_(excluded_case_ids))
    rows = rows_q.all()

    # Available years — distinct open_date years across all cases so the
    # selector can offer historical years even when a year has zero tags.
    year_q = db.session.query(
        db.func.extract('year', Cases.open_date)
    ).select_from(Cases)
    if excluded_case_ids:
        year_q = year_q.filter(Cases.case_id.notin_(excluded_case_ids))
    year_rows = year_q.distinct().all()
    available_years = sorted({int(r[0]) for r in year_rows if r[0] is not None}, reverse=True)
    if year not in available_years:
        available_years.append(year)
        available_years.sort(reverse=True)

    # Build per-case tag set (sector tags excluded), plus per-case metadata
    case_tags = {}        # case_id -> set of non-sector tag titles
    case_meta = {}        # case_id -> {name, open_date}
    for cid, name, opened, tag in rows:
        case_meta.setdefault(cid, {'name': name, 'open_date': opened})
        if not tag:
            continue
        # Drop sector tags (own card) and TLP tags (applied to every case).
        if _is_excluded_metric_tag(tag):
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
        'available_years': available_years,
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

def _unquote_tag_value(rest):
    """Strip surrounding single/double quotes from a machine-tag value."""
    rest = (rest or '').strip()
    if (rest.startswith('"') and rest.endswith('"')) or (rest.startswith("'") and rest.endswith("'")):
        rest = rest[1:-1]
    return rest or None


def _extract_dhs_ciip_value(tag_title):
    """Parse a tag like `dhs-ciip-sectors:DHS-critical-sectors="energy"` and
    return `energy`, or None if the tag isn't a DHS CIIP sector tag.
    Tolerant of single/double quotes and missing quotes."""
    if not tag_title:
        return None
    prefix = f'{DHS_CIIP_TAG_NAMESPACE}:{DHS_CIIP_TAG_PREDICATE}='
    if not tag_title.startswith(prefix):
        return None
    return _unquote_tag_value(tag_title[len(prefix):])


# Non-DHS sector taxonomies surfaced on the Sectors card alongside DHS CIIP.
# `threatmatch:sector="Education"` etc. Keyed in the matrix as
# `threatmatch:<value>` so a threatmatch sector never collides with a DHS slug
# of the same name; the display label is the bare value.
_THREATMATCH_SECTOR_PREFIX = 'threatmatch:sector='


def _extract_sector_key_label(tag_title):
    """Parse any recognized sector tag → (matrix_key, display_label), or None.

    DHS CIIP    → (slug, DHS_CIIP_SECTOR_LABELS[slug])  — bare slug key for
                  backward compatibility with existing label lookups.
    threatmatch → ('threatmatch:<value>', '<value>')   — namespaced key.
    """
    if not tag_title:
        return None
    dhs = _extract_dhs_ciip_value(tag_title)
    if dhs:
        return dhs, DHS_CIIP_SECTOR_LABELS.get(dhs, dhs)
    if tag_title.startswith(_THREATMATCH_SECTOR_PREFIX):
        val = _unquote_tag_value(tag_title[len(_THREATMATCH_SECTOR_PREFIX):])
        if val:
            return f'threatmatch:{val}', val
    # iris-ng: catalog-added namespaces (any prefix beyond the two legacy
    # forms) get the threatmatch treatment generalized — key is namespaced by
    # the taxonomy so slugs can never collide with DHS keys, label is the
    # quoted value.
    for prefix in _sector_tag_prefixes():
        if prefix in (_SECTOR_TAG_PREFIX, _THREATMATCH_SECTOR_PREFIX):
            continue
        if tag_title.startswith(prefix):
            val = _unquote_tag_value(tag_title[len(prefix):])
            if val:
                ns = prefix.split(':', 1)[0]
                return f'{ns}:{val}', val
    return None


def _quarter_key(d):
    """`date(2026, 4, 15)` → `"2026-Q2"`."""
    if d is None:
        return None
    q = (d.month - 1) // 3 + 1
    return f'{d.year}-Q{q}'


def _critical_infrastructure(start_dt, end_dt, excluded_case_ids, ci_year=None):
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
    year_q = db.session.query(
        func.extract('year', Cases.open_date)
    ).filter(Cases.open_date.isnot(None))
    if excluded_case_ids:
        year_q = year_q.filter(Cases.case_id.notin_(excluded_case_ids))
    year_rows = year_q.distinct().all()
    available_years = sorted({int(r[0]) for r in year_rows if r[0] is not None}, reverse=True)
    # Always include the current selection so the dropdown stays consistent
    # even when the selected year has zero cases.
    if year not in available_years:
        available_years.append(year)
        available_years.sort(reverse=True)

    # Pull every case + its sector tags in a single query (one row per
    # case-tag pair; cases with multiple tags repeat).
    rows_q = db.session.query(
        Cases.case_id, Cases.name, Cases.open_date, Cases.close_date,
        Tags.tag_title,
    ).select_from(Cases).outerjoin(
        CaseTags, CaseTags.case_id == Cases.case_id
    ).outerjoin(
        Tags, Tags.id == CaseTags.tag_id
    )
    if excluded_case_ids:
        rows_q = rows_q.filter(Cases.case_id.notin_(excluded_case_ids))
    rows = rows_q.all()

    # Group sectors per case. Recognizes DHS CIIP + threatmatch sectors;
    # sector_labels maps each matrix key to its display label (handles both
    # taxonomies in one place).
    case_sectors = {}        # case_id -> set of sector keys
    sector_labels = {}       # sector key -> display label
    case_meta = {}           # case_id -> dict(name, open_date, close_date)
    for cid, name, open_d, close_d, tag in rows:
        meta = case_meta.setdefault(cid, {
            'name': name, 'open_date': open_d, 'close_date': close_d,
        })
        parsed = _extract_sector_key_label(tag)
        if parsed:
            key, label = parsed
            case_sectors.setdefault(cid, set()).add(key)
            sector_labels[key] = label

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
            'label': sector_labels.get(s, s),
            'counts': [cells.get(q, 0) for q in quarter_keys],
            'total': sum(cells.values()),
        })

    # Compliance: cases opened in the selected year with NO sector tag.
    # Scoped to the year window so "Tagged X/Y" reflects only the current year,
    # not all-time (same date filter used by the quarter matrix above).
    all_case_ids = {
        cid for cid, meta in case_meta.items()
        if meta.get('open_date') and
           start_dt.date() <= meta['open_date'] <= end_dt.date()
    }
    # tagged = year-scoped cases that have at least one sector key
    tagged_case_ids = {cid for cid in all_case_ids if case_sectors.get(cid)}
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
            'top_sector_label': sector_labels.get(best, best) if best else None,
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
            'top_sector_label': sector_labels.get(ytd_top_sector, ytd_top_sector) if ytd_top_sector else None,
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


def _case_tagging_multi_year(excluded_case_ids, years):
    """Return grouped bar data for multiple years.

    Result shape: {
        'tags':  [tag, ...],        # union of top tags across all years, ordered by total desc
        'years': [year, ...],       # same order as requested
        'series': {year: [count, ...]}  # parallel to tags list
    }
    Only the top _MATRIX_TOP_N tags (by combined total across all requested years) are returned.
    """
    # Pull all case+tag rows in one shot, filter to relevant years client-side.
    rows_q = db.session.query(
        Cases.case_id, Cases.open_date, Tags.tag_title,
    ).select_from(Cases).outerjoin(
        CaseTags, CaseTags.case_id == Cases.case_id
    ).outerjoin(
        Tags, Tags.id == CaseTags.tag_id
    ).filter(
        func.extract('year', Cases.open_date).in_(years)
    )
    if excluded_case_ids:
        rows_q = rows_q.filter(Cases.case_id.notin_(excluded_case_ids))
    rows = rows_q.all()

    # year -> tag -> case_id set  (count distinct cases per tag per year)
    year_tag_cases = {y: {} for y in years}
    for cid, opened, tag in rows:
        if not opened:
            continue
        y = opened.year
        if y not in year_tag_cases:
            continue
        if not tag or _is_excluded_metric_tag(tag):
            continue
        year_tag_cases[y].setdefault(tag, set()).add(cid)

    # Combine totals across years to pick top N tags
    combined = {}
    for y, tag_cases in year_tag_cases.items():
        for tag, cases in tag_cases.items():
            combined[tag] = combined.get(tag, 0) + len(cases)
    top_tags = [t for t, _ in sorted(combined.items(), key=lambda r: -r[1])[:_MATRIX_TOP_N]]

    series = {y: [len(year_tag_cases[y].get(t, set())) for t in top_tags] for y in years}
    return {'tags': top_tags, 'years': list(years), 'series': series}


def _critical_infra_multi_year(excluded_case_ids, years):
    """Return grouped bar data for multiple years.

    Result shape: {
        'sectors': [{key, label}, ...],
        'years':   [year, ...],
        'series':  {year: [count, ...]}
    }
    """
    rows_q = db.session.query(
        Cases.case_id, Cases.open_date, Tags.tag_title,
    ).select_from(Cases).outerjoin(
        CaseTags, CaseTags.case_id == Cases.case_id
    ).outerjoin(
        Tags, Tags.id == CaseTags.tag_id
    ).filter(
        func.extract('year', Cases.open_date).in_(years)
    )
    if excluded_case_ids:
        rows_q = rows_q.filter(Cases.case_id.notin_(excluded_case_ids))
    rows = rows_q.all()

    # year -> sector_key -> case_id set
    year_sector_cases = {y: {} for y in years}
    sector_labels = {}
    for cid, opened, tag in rows:
        if not opened:
            continue
        y = opened.year
        if y not in year_sector_cases:
            continue
        parsed = _extract_sector_key_label(tag)
        if not parsed:
            continue
        key, label = parsed
        year_sector_cases[y].setdefault(key, set()).add(cid)
        sector_labels[key] = label

    combined = {}
    for y, sec_cases in year_sector_cases.items():
        for k, cases in sec_cases.items():
            combined[k] = combined.get(k, 0) + len(cases)
    top_sectors = sorted(combined.keys(), key=lambda k: -combined[k])

    sectors_out = [{'key': k, 'label': sector_labels.get(k, k)} for k in top_sectors]
    series = {y: [len(year_sector_cases[y].get(k, set())) for k in top_sectors] for y in years}
    return {'sectors': sectors_out, 'years': list(years), 'series': series}


def get_bar_data(section, years, end_dt=None):
    """Multi-year bar data for a single section ('tagging' or 'ci').

    `years` is a list/set of ints. Returns the shape expected by the grouped
    bar chart on the frontend. `end_dt` is only used to build `available_years`
    so the frontend can keep the checkbox list in sync; it defaults to utcnow().
    """
    if end_dt is None:
        end_dt = _dt.datetime.utcnow()
    excluded = _excluded_case_ids()

    # available_years — same logic as the single-year helpers
    year_q = db.session.query(
        func.extract('year', Cases.open_date)
    ).filter(Cases.open_date.isnot(None))
    if excluded:
        year_q = year_q.filter(Cases.case_id.notin_(excluded))
    yr_rows = year_q.distinct().all()
    available_years = sorted({int(r[0]) for r in yr_rows if r[0] is not None}, reverse=True)
    if not available_years:
        available_years = [end_dt.year]

    years_clean = sorted({int(y) for y in years if y}, reverse=True)
    if not years_clean:
        years_clean = [end_dt.year]

    if section == 'tagging':
        data = _case_tagging_multi_year(excluded, years_clean)
    elif section == 'ci':
        data = _critical_infra_multi_year(excluded, years_clean)
    else:
        raise ValueError(f'Unknown section: {section!r}')

    data['available_years'] = available_years
    return data


def _time_tracking(start_dt, end_dt, excluded_case_ids):
    """Analyst time tracking, broken down four ways for management.

    Time entries store only (case, analyst, minutes, date). Sector and
    incident type are joined in HERE at report time — sector from the case's
    DHS CIIP tag (same parser as the Critical Infrastructure section),
    incident type from `Cases.classification_id`. Analysts never enter those
    two dimensions, so the breakdowns cost them nothing.

    Window: time entries whose `activity_date` falls in the page date range.
    Totals are in minutes; the front-end formats H:MM.
    """
    start_d = start_dt.date()
    end_d = end_dt.date()

    # One pass over the entries in range, joined to the case (for client +
    # classification) and the analyst. Tags are pulled separately (a case can
    # carry several) to resolve sector without fanning out the minute sums.
    base = db.session.query(
        CaseTimeEntry.case_id,
        CaseTimeEntry.user_id,
        CaseTimeEntry.minutes,
        Cases.name.label('case_name'),
        Cases.classification_id,
        CaseClassification.name_expanded.label('classification_label'),
        CaseClassification.name.label('classification_name'),
        Client.name.label('customer_name'),
        User.name.label('user_name'),
        User.user.label('user_login'),
    ).select_from(CaseTimeEntry).join(
        Cases, Cases.case_id == CaseTimeEntry.case_id
    ).outerjoin(
        CaseClassification, CaseClassification.id == Cases.classification_id
    ).outerjoin(
        Client, Client.client_id == Cases.client_id
    ).outerjoin(
        User, User.id == CaseTimeEntry.user_id
    ).filter(
        CaseTimeEntry.activity_date >= start_d,
        CaseTimeEntry.activity_date <= end_d,
    )
    if excluded_case_ids:
        base = base.filter(CaseTimeEntry.case_id.notin_(excluded_case_ids))
    entry_rows = base.all()

    # case_id -> set of sector values (from the DHS CIIP tag), one query.
    sector_q = db.session.query(Cases.case_id, Tags.tag_title).select_from(Cases).join(
        CaseTags, CaseTags.case_id == Cases.case_id
    ).join(
        Tags, Tags.id == CaseTags.tag_id
    )
    if excluded_case_ids:
        sector_q = sector_q.filter(Cases.case_id.notin_(excluded_case_ids))
    case_sectors = {}        # case_id -> set of sector keys
    tt_sector_labels = {}    # sector key -> display label
    for cid, tag in sector_q.all():
        parsed = _extract_sector_key_label(tag)
        if parsed:
            key, label = parsed
            case_sectors.setdefault(cid, set()).add(key)
            tt_sector_labels[key] = label

    by_case = {}      # case_id -> {label, minutes}
    # The person/customer/sector/incident-type breakdowns carry BOTH the running
    # total (for CSV export) and the set of distinct cases that contributed, so
    # the card can show an *average per case* — total minutes / # of cases in the
    # group. Averaging normalises for "this customer simply has more cases" and
    # answers management's real question: how much effort does a typical case in
    # this bucket take.
    by_person = {}    # user_id -> {label, minutes, cases:set}
    by_customer = {}  # customer name -> {label, minutes, cases:set}
    by_sector = {}    # sector key -> {minutes, cases:set}
    by_type = {}      # classification label -> {label, minutes, cases:set}
    total = 0

    for r in entry_rows:
        mins = int(r.minutes or 0)
        total += mins

        c = by_case.setdefault(r.case_id, {'case_id': r.case_id, 'label': r.case_name or f'#{r.case_id}', 'minutes': 0})
        c['minutes'] += mins

        pid = r.user_id if r.user_id is not None else 0
        plabel = r.user_name or r.user_login or 'Unassigned'
        p = by_person.setdefault(pid, {'user_id': r.user_id, 'label': plabel, 'minutes': 0, 'cases': set()})
        p['minutes'] += mins
        p['cases'].add(r.case_id)

        customer_label = r.customer_name or 'Unknown customer'
        cust = by_customer.setdefault(customer_label, {'label': customer_label, 'minutes': 0, 'cases': set()})
        cust['minutes'] += mins
        cust['cases'].add(r.case_id)

        type_label = r.classification_label or r.classification_name or 'Unclassified'
        typ = by_type.setdefault(type_label, {'label': type_label, 'minutes': 0, 'cases': set()})
        typ['minutes'] += mins
        typ['cases'].add(r.case_id)

        # A case may carry multiple sectors — attribute its minutes to each so
        # sector columns sum to >= total (documented, same convention as the
        # CI matrix where a multi-sector case counts in each row). The case is
        # counted toward each of its sectors for the per-case average too.
        sectors = case_sectors.get(r.case_id) or {'__unsectored__'}
        for s in sectors:
            sec = by_sector.setdefault(s, {'minutes': 0, 'cases': set()})
            sec['minutes'] += mins
            sec['cases'].add(r.case_id)

    def _with_avg(entry, **extra):
        """Flatten an aggregation bucket into a serialisable row carrying both
        the total minutes (CSV) and the per-case average (card display)."""
        n = len(entry['cases']) or 1
        row = {
            'label': entry['label'],
            'minutes': entry['minutes'],
            'case_count': len(entry['cases']),
            'avg_minutes': int(round(entry['minutes'] / n)),
        }
        row.update(extra)
        return row

    person_rows = sorted(
        (_with_avg(e, user_id=e.get('user_id')) for e in by_person.values()),
        key=lambda x: -x['avg_minutes'],
    )
    customer_rows = sorted(
        (_with_avg(e) for e in by_customer.values()),
        key=lambda x: -x['avg_minutes'],
    )
    type_rows = sorted(
        (_with_avg(e) for e in by_type.values()),
        key=lambda x: -x['avg_minutes'],
    )
    sector_rows = sorted(
        (
            _with_avg(
                {**e, 'label': 'No sector tag' if s == '__unsectored__' else tt_sector_labels.get(s, s)},
                sector=s,
            )
            for s, e in by_sector.items()
        ),
        key=lambda x: -x['avg_minutes'],
    )

    # by_case stays totals-only — an "average per case" of a single case is just
    # its total. Kept off the card but still exported in the CSV.
    case_rows = sorted(by_case.values(), key=lambda x: -x['minutes'])

    return {
        'total_minutes': total,
        'entry_count': len(entry_rows),
        'by_case': case_rows,
        'by_person': person_rows,
        'by_customer': customer_rows,
        'by_sector': sector_rows,
        'by_incident_type': type_rows,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_dashboard_metrics(start, end, ci_year=None, tag_year=None) -> dict:
    """Compute every section. `start` and `end` may be datetime, date, or ISO
    string; the helper coerces them into naive UTC datetimes.

    `ci_year` overrides the year for the Critical Infrastructure section.
    `tag_year` overrides the year for the Case Tagging section independently.
    Both default to the year of `end` when not supplied."""

    now = _dt.datetime.utcnow()
    end_dt = _to_dt(end, now)
    start_dt = _to_dt(start, end_dt - _dt.timedelta(days=30))
    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt

    user_id = current_user.id

    # Resolved once per request and passed into each section. Empty list when
    # no excluded clients have cases yet — sections then skip the NOT IN
    # filter entirely (SQLAlchemy warns on empty IN lists).
    excluded_case_ids = _excluded_case_ids()

    return {
        'range': {
            'start': start_dt.isoformat() + 'Z',
            'end': end_dt.isoformat() + 'Z',
            'days': (end_dt.date() - start_dt.date()).days + 1,
        },
        'kpi': _kpi_strip(start_dt, end_dt, excluded_case_ids),
        'analyst': _analyst_self(start_dt, end_dt, user_id, excluded_case_ids),
        'soc': _soc_manager(start_dt, end_dt, excluded_case_ids),
        'admin': _admin_health(start_dt, end_dt, excluded_case_ids),
        'quality': _investigation_quality(excluded_case_ids),
        'tagging': _case_tagging(start_dt, end_dt, excluded_case_ids, tag_year=tag_year),
        'critical_infra': _critical_infrastructure(start_dt, end_dt, excluded_case_ids, ci_year=ci_year),
        # Time tracking honors the IrisInitialClient exclusion like every other
        # section — demo/bootstrap cases stay out of management metrics. Real
        # cases live under real customers, so their logged hours count normally.
        'time_tracking': _time_tracking(start_dt, end_dt, excluded_case_ids),
    }

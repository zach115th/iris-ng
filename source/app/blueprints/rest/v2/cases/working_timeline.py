"""Dual-timeline REST endpoints — tool-ingested events pending review.

Surface area:
    POST   /api/v2/cases/<cid>/working-timeline/import/hayabusa   (multipart)
    GET    /api/v2/cases/<cid>/working-timeline/events?status=&source=&limit=
    POST   /api/v2/cases/<cid>/working-timeline/events/<id>/promote
    POST   /api/v2/cases/<cid>/working-timeline/events/<id>/reject
    POST   /api/v2/cases/<cid>/working-timeline/events/<id>/reset
    DELETE /api/v2/cases/<cid>/working-timeline/events/<id>
    DELETE /api/v2/cases/<cid>/working-timeline/imports/<batch_id>

Architecture: docs/19-ux-ai-design.md §5b.1.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from flask import Blueprint
from flask import request
from flask_login import current_user

from app import db
from app.blueprints.access_controls import ac_api_requires
from app.blueprints.access_controls import ac_api_return_access_denied
from app.blueprints.rest.endpoints import response_api_created
from app.blueprints.rest.endpoints import response_api_deleted
from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
from app.datamgmt.case.case_events_db import get_default_category
from app.datamgmt.case.case_events_db import save_event_category
from app.datamgmt.case.case_events_db import update_event_assets
from app.datamgmt.case.case_events_db import update_event_iocs
from app.datamgmt.states import update_assets_state
from app.datamgmt.states import update_ioc_state
from app.datamgmt.states import update_timeline_state
from app.iris_engine.access_control.utils import ac_fast_check_current_user_has_case_access
from app.iris_engine.ai.working_event_explainer import WORKING_EXPLAIN_KIND_PREFIX
from app.iris_engine.ai.working_event_explainer import WorkingEventExplainerError
from app.iris_engine.ai.working_event_explainer import explain_working_event
from app.iris_engine.ai.working_event_explainer import get_cached as get_cached_explanation
from app.iris_engine.utils.tracker import track_activity
from app.iris_engine.working_timeline.asset_resolver import ensure_assets_for_working_event
from app.iris_engine.working_timeline.ioc_resolver import ensure_iocs_for_working_event
from app.iris_engine.working_timeline.eztools_parser import EztoolsParseError
from app.iris_engine.working_timeline.eztools_parser import parse_eztools_csv
from app.iris_engine.working_timeline.hayabusa_parser import HayabusaParseError
from app.iris_engine.working_timeline.hayabusa_parser import parse_hayabusa_csv
from app.models.authorization import CaseAccessLevel
from app.models.cases import CaseWorkingEvent
from app.models.cases import CasesEvent
from app.models.models import CaseAiArtifact

case_working_timeline_blueprint = Blueprint(
    'case_working_timeline_rest_v2',
    __name__,
    url_prefix='/<int:case_identifier>/working-timeline'
)


def _iso_utc(dt) -> str | None:
    """Serialize a stored datetime as an explicit UTC ISO string.

    Working-timeline ingest sources (Hayabusa with --UTC, EZ Tools / KAPE
    output run in UTC mode) all store event_date as a *naive* datetime that
    represents UTC wall-clock. Without an explicit `Z` suffix the browser's
    `new Date(iso)` parses the value as the browser's local timezone, which
    then displays an offset value (e.g. a 15:28 UTC event renders as 22:28Z
    for a PDT analyst). Appending `Z` makes the conversion correct.
    """
    if dt is None:
        return None
    # If a future ingest source stores TZ-aware values, normalise to UTC.
    if dt.tzinfo is not None:
        from datetime import timezone as _tz
        return dt.astimezone(_tz.utc).isoformat().replace('+00:00', 'Z')
    return dt.isoformat() + 'Z'


def _serialize(ev: CaseWorkingEvent) -> dict:
    return {
        'id': ev.id,
        'case_id': ev.case_id,
        'source': ev.source,
        'event_date': _iso_utc(ev.event_date),
        'event_title': ev.event_title,
        'event_description': ev.event_description,
        'event_source_host': ev.event_source_host,
        'severity': ev.severity,
        'event_tags': ev.event_tags,
        'mitre_techniques': ev.mitre_techniques,
        'external_id': ev.external_id,
        'import_batch_id': str(ev.import_batch_id) if ev.import_batch_id else None,
        'status': ev.status,
        'promoted_event_id': ev.promoted_event_id,
        'created_at': _iso_utc(ev.created_at),
        'reviewed_at': _iso_utc(ev.reviewed_at),
    }


def _require_full_access(case_identifier):
    if not ac_fast_check_current_user_has_case_access(
        case_identifier, [CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=case_identifier)
    return None


def _require_read_access(case_identifier):
    if not ac_fast_check_current_user_has_case_access(
        case_identifier, [CaseAccessLevel.read_only, CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=case_identifier)
    return None


# --- IMPORT --------------------------------------------------------------

@case_working_timeline_blueprint.post('/import/hayabusa')
@ac_api_requires()
def import_hayabusa(case_identifier):
    """Upload a Hayabusa CSV and stage it as pending working events.

    Accepts either ``multipart/form-data`` with a ``file`` field, or a
    JSON body with a ``csv`` string field (handy for scripted imports).
    """
    denied = _require_full_access(case_identifier)
    if denied is not None:
        return denied

    csv_bytes: bytes | str | None = None
    if 'file' in request.files:
        csv_bytes = request.files['file'].read()
    else:
        body = request.get_json(silent=True) or {}
        if 'csv' in body:
            csv_bytes = body['csv']

    if not csv_bytes:
        return response_api_error('No CSV provided. POST a "file" multipart field or JSON {"csv": "..."}.')

    try:
        batch_id, parsed = parse_hayabusa_csv(csv_bytes, case_identifier)
    except HayabusaParseError as exc:
        return response_api_error(str(exc))

    inserted = 0
    for row in parsed:
        ev = CaseWorkingEvent(
            case_id=row['case_id'],
            source=row['source'],
            event_date=row['event_date'],
            event_title=row['event_title'],
            event_description=row['event_description'],
            event_source_host=row['event_source_host'],
            severity=row['severity'],
            event_tags=row['event_tags'],
            mitre_techniques=row['mitre_techniques'],
            external_id=row['external_id'],
            event_raw=row['event_raw'],
            import_batch_id=row['import_batch_id'],
            status='pending',
            created_by=current_user.id,
        )
        db.session.add(ev)
        inserted += 1
    db.session.commit()

    track_activity(
        f'imported {inserted} Hayabusa event(s) into the working timeline (batch {batch_id})',
        caseid=case_identifier,
    )

    return response_api_created({
        'import_batch_id': str(batch_id),
        'imported': inserted,
        'source': 'hayabusa',
    })


@case_working_timeline_blueprint.post('/import/eztools')
@ac_api_requires()
def import_eztools(case_identifier):
    """Upload an Eric Zimmerman tools CSV and stage it as pending working events.

    Accepts ``multipart/form-data`` with a ``file`` field, or a JSON body
    with a ``csv`` string field. Auto-detects which EZ Tools sub-format
    the CSV is (EvtxECmd / MFTECmd $J / PECmd / Amcache / AppCompatCache /
    RBCmd / LECmd / JLECmd) by inspecting the header columns.
    """
    denied = _require_full_access(case_identifier)
    if denied is not None:
        return denied

    csv_bytes: bytes | str | None = None
    if 'file' in request.files:
        csv_bytes = request.files['file'].read()
    else:
        body = request.get_json(silent=True) or {}
        if 'csv' in body:
            csv_bytes = body['csv']

    if not csv_bytes:
        return response_api_error('No CSV provided. POST a "file" multipart field or JSON {"csv": "..."}.')

    try:
        batch_id, kind, parsed = parse_eztools_csv(csv_bytes, case_identifier)
    except EztoolsParseError as exc:
        return response_api_error(str(exc))

    inserted = 0
    for row in parsed:
        ev = CaseWorkingEvent(
            case_id=row['case_id'],
            source=row['source'],
            event_date=row['event_date'],
            event_title=row['event_title'],
            event_description=row['event_description'],
            event_source_host=row['event_source_host'],
            severity=row['severity'],
            event_tags=row['event_tags'],
            mitre_techniques=row['mitre_techniques'],
            external_id=row['external_id'],
            event_raw=row['event_raw'],
            import_batch_id=row['import_batch_id'],
            status='pending',
            created_by=current_user.id,
        )
        db.session.add(ev)
        inserted += 1
    db.session.commit()

    track_activity(
        f'imported {inserted} EZ Tools ({kind}) event(s) into the working timeline '
        f'(batch {batch_id})',
        caseid=case_identifier,
    )

    return response_api_created({
        'import_batch_id': str(batch_id),
        'imported': inserted,
        'source': 'eztools',
        'kind': kind,
    })


# --- LIST ----------------------------------------------------------------

@case_working_timeline_blueprint.get('/events')
@ac_api_requires()
def list_working_events(case_identifier):
    """List working events for the case.

    Query params:
        status   one of pending / true_positive / false_positive (default: pending)
                 use 'all' to skip the filter
        source   filter by source (hayabusa, …); omit for all
        limit    max rows (default 500)
    """
    denied = _require_read_access(case_identifier)
    if denied is not None:
        return denied

    status = request.args.get('status', 'pending')
    source = request.args.get('source')
    try:
        limit = min(int(request.args.get('limit', 500)), 5000)
    except (TypeError, ValueError):
        limit = 500

    q = CaseWorkingEvent.query.filter(CaseWorkingEvent.case_id == case_identifier)
    if status and status != 'all':
        q = q.filter(CaseWorkingEvent.status == status)
    if source:
        q = q.filter(CaseWorkingEvent.source == source)
    q = q.order_by(CaseWorkingEvent.event_date.asc()).limit(limit)
    rows = q.all()

    # Lightweight summary counts so the UI can show "23 pending · 4 promoted · 2 rejected"
    # without a second round trip.
    counts_q = (
        db.session.query(CaseWorkingEvent.status, db.func.count(CaseWorkingEvent.id))
        .filter(CaseWorkingEvent.case_id == case_identifier)
        .group_by(CaseWorkingEvent.status)
        .all()
    )
    counts = {row[0]: row[1] for row in counts_q}

    # Bulk-load any cached AI explanations for the listed events so the UI
    # can re-render them after a refresh without N+1 follow-up GETs. The
    # kind discriminator embeds the working event id, so we filter on the
    # set of expected kinds rather than parsing in Python.
    explanations_by_id: dict[int, dict] = {}
    if rows:
        kind_to_wid = {f"{WORKING_EXPLAIN_KIND_PREFIX}{r.id}": r.id for r in rows}
        cached = (
            CaseAiArtifact.query
            .filter(
                CaseAiArtifact.case_id == case_identifier,
                CaseAiArtifact.kind.in_(list(kind_to_wid.keys())),
            )
            .order_by(CaseAiArtifact.generated_at.desc())
            .all()
        )
        for art in cached:
            wid = kind_to_wid.get(art.kind)
            if wid is None or wid in explanations_by_id:
                continue  # only newest per event (results are date-desc)
            explanations_by_id[wid] = {
                'id': art.id,
                'model': art.model,
                'content': art.content,
                'generated_at': art.generated_at.isoformat() if art.generated_at else None,
            }

    serialized = []
    for r in rows:
        d = _serialize(r)
        if r.id in explanations_by_id:
            d['explanation'] = explanations_by_id[r.id]
        serialized.append(d)

    return response_api_success({
        'events': serialized,
        'counts': {
            'pending': counts.get('pending', 0),
            'true_positive': counts.get('true_positive', 0),
            'false_positive': counts.get('false_positive', 0),
        },
    })


# --- PROMOTE / REJECT / RESET --------------------------------------------

def _get_or_404(working_id: int, case_identifier: int) -> CaseWorkingEvent | None:
    return CaseWorkingEvent.query.filter(
        CaseWorkingEvent.id == working_id,
        CaseWorkingEvent.case_id == case_identifier,
    ).first()


def _get_or_404_locked(working_id: int, case_identifier: int) -> CaseWorkingEvent | None:
    # SELECT ... FOR UPDATE — blocks concurrent transactions trying to mutate
    # the same working event. Without this, rapid double-clicks on Promote race
    # past the idempotency check and create duplicate cases_events rows.
    return CaseWorkingEvent.query.filter(
        CaseWorkingEvent.id == working_id,
        CaseWorkingEvent.case_id == case_identifier,
    ).with_for_update().first()


@case_working_timeline_blueprint.post('/events/<int:working_id>/promote')
@ac_api_requires()
def promote_working_event(case_identifier, working_id):
    """Spawn a real cases_events row from this working event.

    Side-effects:
      * Creates a CasesEvent with the same date/title/description/host/tags.
      * Categorises with the default ("Unspecified") category.
      * Marks working event status=true_positive + back-references the new event_id.
      * Bumps the timeline state so the existing /case/timeline page refreshes.
    """
    denied = _require_full_access(case_identifier)
    if denied is not None:
        return denied

    # Row-locked fetch so a rapid double-click can't race past the idempotency
    # check below and create duplicate cases_events rows. The lock releases on
    # commit/rollback at the end of this request.
    working = _get_or_404_locked(working_id, case_identifier)
    if working is None:
        return response_api_not_found()
    if working.status == 'true_positive':
        # Idempotent. Note: we also short-circuit when promoted_event_id is
        # NULL (legacy rows from before the back-ref was wired) — re-promoting
        # would silently create a duplicate cases_events row, which is exactly
        # the bug we're guarding against. Analyst can hit Reset first if they
        # actually want to re-promote.
        return response_api_success({
            'working': _serialize(working),
            'promoted_event_id': working.promoted_event_id,
            'note': 'already promoted',
        })

    # Pull the parser-built Event Source string (e.g. "Windows Security 4698")
    # from event_raw. Falls back to the source name if the parser didn't
    # populate it (older rows, future ingest sources without that field).
    raw = working.event_raw or {}
    event_source = raw.get('windows_event_source') or working.source

    promoted = CasesEvent()
    promoted.case_id = case_identifier
    promoted.event_title = working.event_title
    promoted.event_content = working.event_description or ''
    promoted.event_source = event_source
    promoted.event_date = working.event_date
    promoted.event_date_wtz = working.event_date
    promoted.event_tz = '+00:00'
    promoted.event_added = datetime.utcnow()
    promoted.event_in_graph = True
    promoted.event_in_summary = False
    promoted.user_id = current_user.id
    promoted.event_tags = working.event_tags
    promoted.event_color = ''
    promoted.event_is_flagged = False
    db.session.add(promoted)
    db.session.flush()  # need event_id for category + back-ref + asset links

    default_cat = get_default_category()
    if default_cat:
        save_event_category(promoted.event_id, default_cat.id)

    # Materialize + link assets implied by the working event's subjects
    # (host + users from event_raw). Per user's design rule: this only
    # happens at promote time, never at import.
    asset_report = ensure_assets_for_working_event(working, user_id=current_user.id)

    # Same idea for IOCs — run the AI extractor against the event's text
    # and find-or-create / link any high-confidence indicators. Failures
    # here are reported but don't block the promote.
    ioc_report = ensure_iocs_for_working_event(working, user_id=current_user.id)

    if asset_report['asset_ids']:
        # update_event_assets owns case_events_assets. With
        # sync_iocs_assets=True it ALSO creates IocAssetLink rows for
        # each (asset, ioc) pair tied to this event — same effect as
        # the analyst ticking "Push IOCs to assets" on the event modal.
        # We pass the AI-extracted IOC ids so every linked asset gets
        # cross-referenced to every linked IOC for this event.
        update_event_assets(
            event_id=promoted.event_id,
            caseid=case_identifier,
            assets_list=asset_report['asset_ids'],
            iocs_list=ioc_report['ioc_ids'],
            sync_iocs_assets=True,
        )
    if ioc_report['ioc_ids']:
        # Separate helper for the case_events_ioc join (event ↔ IOC).
        update_event_iocs(
            event_id=promoted.event_id,
            caseid=case_identifier,
            iocs_list=ioc_report['ioc_ids'],
        )

    working.status = 'true_positive'
    working.promoted_event_id = promoted.event_id
    working.reviewed_at = datetime.utcnow()
    working.reviewed_by = current_user.id

    db.session.commit()
    update_timeline_state(caseid=case_identifier)
    if asset_report['created']:
        update_assets_state(caseid=case_identifier, userid=current_user.id)
    if ioc_report['created']:
        update_ioc_state(caseid=case_identifier, userid=current_user.id)

    created_asset_names = ', '.join(a['name'] for a in asset_report['created']) or 'none'
    created_ioc_values = ', '.join(i['value'] for i in ioc_report['created']) or 'none'
    track_activity(
        f'promoted working event #{working_id} ({working.source}) → cases_event '
        f'#{promoted.event_id}; created {len(asset_report["created"])} new asset(s) '
        f'[{created_asset_names}], reused {len(asset_report["reused"])}; '
        f'created {len(ioc_report["created"])} new IOC(s) [{created_ioc_values}], '
        f'reused {len(ioc_report["reused"])}, skipped {len(ioc_report["skipped"])}',
        caseid=case_identifier,
    )

    return response_api_success({
        'working': _serialize(working),
        'promoted_event_id': promoted.event_id,
        'event_source': event_source,
        'assets': asset_report,
        'iocs': ioc_report,
    })


@case_working_timeline_blueprint.post('/events/<int:working_id>/reject')
@ac_api_requires()
def reject_working_event(case_identifier, working_id):
    """Mark this working event as a false positive (analyst-reviewed)."""
    denied = _require_full_access(case_identifier)
    if denied is not None:
        return denied

    working = _get_or_404(working_id, case_identifier)
    if working is None:
        return response_api_not_found()

    working.status = 'false_positive'
    working.reviewed_at = datetime.utcnow()
    working.reviewed_by = current_user.id
    db.session.commit()

    track_activity(
        f'rejected working event #{working_id} ({working.source}) as false positive',
        caseid=case_identifier,
    )

    return response_api_success(_serialize(working))


@case_working_timeline_blueprint.post('/events/<int:working_id>/reset')
@ac_api_requires()
def reset_working_event(case_identifier, working_id):
    """Undo a promote/reject — return the event to pending.

    For promote, we also drop the promoted_event_id pointer (we do NOT
    delete the underlying cases_events row — analyst may have edited it).
    """
    denied = _require_full_access(case_identifier)
    if denied is not None:
        return denied

    working = _get_or_404(working_id, case_identifier)
    if working is None:
        return response_api_not_found()

    working.status = 'pending'
    working.promoted_event_id = None
    working.reviewed_at = None
    working.reviewed_by = None
    db.session.commit()

    return response_api_success(_serialize(working))


@case_working_timeline_blueprint.delete('/events/<int:working_id>')
@ac_api_requires()
def delete_working_event(case_identifier, working_id):
    """Hard delete (use sparingly — prefer reject so the audit trail stays).

    Does NOT touch any cases_events row spawned via promote.
    """
    denied = _require_full_access(case_identifier)
    if denied is not None:
        return denied

    working = _get_or_404(working_id, case_identifier)
    if working is None:
        return response_api_not_found()

    db.session.delete(working)
    db.session.commit()

    track_activity(
        f'deleted working event #{working_id} ({working.source})',
        caseid=case_identifier,
    )

    return response_api_deleted()


# --- AI EXPLAIN -----------------------------------------------------------

def _serialize_explanation(art) -> dict:
    if art is None:
        return None
    return {
        'id': art.id,
        'kind': art.kind,
        'prompt_id': art.prompt_id,
        'model': art.model,
        'content': art.content,
        'generated_at': art.generated_at.isoformat() if art.generated_at else None,
    }


@case_working_timeline_blueprint.get('/events/<int:working_id>/explain')
@ac_api_requires()
def get_working_event_explanation(case_identifier, working_id):
    """Return the latest cached explanation for this working event, or 404."""
    denied = _require_read_access(case_identifier)
    if denied is not None:
        return denied

    working = _get_or_404(working_id, case_identifier)
    if working is None:
        return response_api_not_found()

    art = get_cached_explanation(case_identifier, working_id)
    if art is None:
        return response_api_not_found()
    return response_api_success(_serialize_explanation(art))


@case_working_timeline_blueprint.post('/events/<int:working_id>/explain')
@ac_api_requires()
def post_working_event_explanation(case_identifier, working_id):
    """Generate (or return cached) AI explanation for a working event.

    Query params:
      - force=true   bypass the cache and re-run the model
    """
    denied = _require_full_access(case_identifier)
    if denied is not None:
        return denied

    working = _get_or_404(working_id, case_identifier)
    if working is None:
        return response_api_not_found()

    force = request.args.get('force', '').lower() in ('1', 'true', 'yes')

    try:
        art = explain_working_event(case_identifier, working_id, force=force)
    except WorkingEventExplainerError as exc:
        return response_api_error(str(exc))

    return response_api_success(_serialize_explanation(art))


@case_working_timeline_blueprint.delete('/imports/<batch_id>')
@ac_api_requires()
def delete_import_batch(case_identifier, batch_id):
    """Drop a whole import in one shot (for "I uploaded the wrong CSV" recovery).

    Only deletes pending rows by default — if any have been promoted or
    rejected (i.e. analyst-reviewed), they're left alone. Pass
    ``?force=true`` to delete reviewed rows too (does NOT delete the
    spawned cases_events rows).
    """
    denied = _require_full_access(case_identifier)
    if denied is not None:
        return denied

    try:
        batch_uuid = uuid.UUID(batch_id)
    except (ValueError, AttributeError):
        return response_api_error('Invalid batch id')

    force = request.args.get('force', '').lower() in ('1', 'true', 'yes')

    q = CaseWorkingEvent.query.filter(
        CaseWorkingEvent.case_id == case_identifier,
        CaseWorkingEvent.import_batch_id == batch_uuid,
    )
    if not force:
        q = q.filter(CaseWorkingEvent.status == 'pending')

    deleted = q.delete(synchronize_session=False)
    db.session.commit()

    track_activity(
        f'deleted {deleted} working events from batch {batch_id} (force={force})',
        caseid=case_identifier,
    )

    return response_api_success({'deleted': deleted, 'batch_id': batch_id})

"""Timeline deduplication REST endpoints.

Surface area:
    POST /api/v2/cases/<cid>/timeline/dedup/scan
        body: {"scope": "master"|"working"}
        Scan for exact and near-duplicate events; returns results without
        making any changes.

    POST /api/v2/cases/<cid>/timeline/dedup/auto-exact
        body: {"scope": "master"|"working"}
        Automatically delete all exact duplicates, keeping the earliest
        event_added / created_at entry in each group.

    POST /api/v2/cases/<cid>/timeline/dedup/resolve
        body: {"scope", "action": "keep"|"merge", "keep_id", "delete_ids": [...],
               "merged": {"event_title", "event_content"|"event_description"}}
        Resolve a single near-duplicate pair.  "keep" deletes the unwanted
        event(s); "merge" updates the kept event with analyst-edited content
        then deletes the other(s).
"""
from __future__ import annotations

from flask import Blueprint
from flask import request

from app import db
from app.blueprints.access_controls import ac_api_requires
from app.blueprints.access_controls import ac_api_return_access_denied
from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_success
from app.business.timeline_dedup import find_exact_master
from app.business.timeline_dedup import find_exact_working
from app.business.timeline_dedup import find_near_master
from app.business.timeline_dedup import find_near_working
from app.iris_engine.access_control.utils import ac_fast_check_current_user_has_case_access
from app.iris_engine.utils.tracker import track_activity
from app.models.authorization import CaseAccessLevel
from app.models.cases import CaseWorkingEvent
from app.models.cases import CasesEvent
from app.models.models import CaseEventsAssets
from app.models.models import CaseEventsIoc
from app.models.models import CaseEventCategory
from app.models.models import EventComments

case_dedup_blueprint = Blueprint("case_dedup", __name__)

_WRITE_LEVELS = [CaseAccessLevel.full_access]
_READ_LEVELS = [CaseAccessLevel.full_access, CaseAccessLevel.read_only]


def _delete_master_event(ev: CasesEvent) -> None:
    """Delete a master-timeline event and all dependent join-table rows.

    case_events_assets, case_events_ioc, case_events_category, and Comments
    all have FK references to cases_events.event_id without ON DELETE CASCADE,
    so they must be cleaned up manually before the event row can be deleted.
    """
    eid = ev.event_id
    CaseEventsAssets.query.filter_by(event_id=eid).delete()
    CaseEventsIoc.query.filter_by(event_id=eid).delete()
    CaseEventCategory.query.filter_by(event_id=eid).delete()
    EventComments.query.filter_by(comment_event_id=eid).delete()
    db.session.delete(ev)


def _check_access(case_id: int, levels: list):
    if not ac_fast_check_current_user_has_case_access(case_id, levels):
        return ac_api_return_access_denied(f"Case #{case_id}")
    return None


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _ser_master(ev) -> dict:
    return {
        "id": ev.event_id,
        "title": ev.event_title or "",
        "content": ev.event_content or "",
        "date": (ev.event_date.isoformat() + "Z") if ev.event_date else None,
        "added": (ev.event_added.isoformat() + "Z") if ev.event_added else None,
        "source": ev.event_source or "",
        "tags": ev.event_tags or "",
        "is_flagged": bool(ev.event_is_flagged),
    }


def _ser_working(ev) -> dict:
    return {
        "id": ev.id,
        "title": ev.event_title or "",
        "description": ev.event_description or "",
        "date": (ev.event_date.isoformat() + "Z") if ev.event_date else None,
        "created_at": (ev.created_at.isoformat() + "Z") if ev.created_at else None,
        "source": ev.source or "",
        "source_host": ev.event_source_host or "",
        "tags": ev.event_tags or "",
        "status": ev.status or "pending",
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@case_dedup_blueprint.route("/<int:case_id>/timeline/dedup/scan", methods=["POST"])
@ac_api_requires()
def dedup_scan(case_id: int):
    denied = _check_access(case_id, _READ_LEVELS)
    if denied:
        return denied

    scope = (request.json or {}).get("scope", "master")
    if scope not in ("master", "working"):
        return response_api_error("scope must be 'master' or 'working'")

    if scope == "master":
        events = CasesEvent.query.filter_by(case_id=case_id).all()
        exact_groups = find_exact_master(events)
        near_pairs = find_near_master(events)
        exact_out = [
            {
                "keep": _ser_master(g["keep"]),
                "duplicates": [_ser_master(d) for d in g["duplicates"]],
            }
            for g in exact_groups
        ]
        near_out = [
            {
                "event_a": _ser_master(p["event_a"]),
                "event_b": _ser_master(p["event_b"]),
                "similarity": p["similarity"],
                "date_diff_seconds": p["date_diff_seconds"],
            }
            for p in near_pairs
        ]
    else:
        events = CaseWorkingEvent.query.filter_by(case_id=case_id).all()
        exact_groups = find_exact_working(events)
        near_pairs = find_near_working(events)
        exact_out = [
            {
                "keep": _ser_working(g["keep"]),
                "duplicates": [_ser_working(d) for d in g["duplicates"]],
            }
            for g in exact_groups
        ]
        near_out = [
            {
                "event_a": _ser_working(p["event_a"]),
                "event_b": _ser_working(p["event_b"]),
                "similarity": p["similarity"],
                "date_diff_seconds": p["date_diff_seconds"],
            }
            for p in near_pairs
        ]

    return response_api_success({
        "scope": scope,
        "exact": exact_out,
        "near": near_out,
    })


@case_dedup_blueprint.route("/<int:case_id>/timeline/dedup/auto-exact", methods=["POST"])
@ac_api_requires()
def dedup_auto_exact(case_id: int):
    denied = _check_access(case_id, _WRITE_LEVELS)
    if denied:
        return denied

    scope = (request.json or {}).get("scope", "master")
    if scope not in ("master", "working"):
        return response_api_error("scope must be 'master' or 'working'")

    if scope == "master":
        events = CasesEvent.query.filter_by(case_id=case_id).all()
        groups = find_exact_master(events)
        removed = 0
        for g in groups:
            for d in g["duplicates"]:
                _delete_master_event(d)
                removed += 1
    else:
        events = CaseWorkingEvent.query.filter_by(case_id=case_id).all()
        groups = find_exact_working(events)
        removed = 0
        for g in groups:
            for d in g["duplicates"]:
                db.session.delete(d)
                removed += 1

    db.session.commit()
    track_activity(
        f"Dedup: auto-removed {removed} exact duplicate(s) from {scope} timeline",
        caseid=case_id,
    )
    return response_api_success({"removed": removed, "groups": len(groups)})


@case_dedup_blueprint.route("/<int:case_id>/timeline/dedup/resolve", methods=["POST"])
@ac_api_requires()
def dedup_resolve(case_id: int):
    denied = _check_access(case_id, _WRITE_LEVELS)
    if denied:
        return denied

    body = request.json or {}
    scope = body.get("scope", "master")
    action = body.get("action")
    keep_id = body.get("keep_id")
    # Accept delete_ids list or single delete_id for convenience
    delete_ids = body.get("delete_ids") or (
        [body["delete_id"]] if body.get("delete_id") else []
    )
    merged = body.get("merged") or {}

    if scope not in ("master", "working"):
        return response_api_error("scope must be 'master' or 'working'")
    if action not in ("keep", "merge"):
        return response_api_error("action must be 'keep' or 'merge'")
    if not keep_id or not delete_ids:
        return response_api_error("keep_id and at least one delete_id are required")

    if scope == "master":
        keep_ev = CasesEvent.query.filter_by(event_id=keep_id, case_id=case_id).first()
        if not keep_ev:
            return response_api_error("keep event not found in this case")
        if action == "merge" and merged:
            if "event_title" in merged:
                keep_ev.event_title = merged["event_title"]
            if "event_content" in merged:
                keep_ev.event_content = merged["event_content"]
        deleted = 0
        for did in delete_ids:
            ev = CasesEvent.query.filter_by(event_id=did, case_id=case_id).first()
            if ev:
                _delete_master_event(ev)
                deleted += 1
    else:
        keep_ev = CaseWorkingEvent.query.filter_by(id=keep_id, case_id=case_id).first()
        if not keep_ev:
            return response_api_error("keep event not found in this case")
        if action == "merge" and merged:
            if "event_title" in merged:
                keep_ev.event_title = merged["event_title"]
            if "event_description" in merged:
                keep_ev.event_description = merged["event_description"]
        deleted = 0
        for did in delete_ids:
            ev = CaseWorkingEvent.query.filter_by(id=did, case_id=case_id).first()
            if ev:
                db.session.delete(ev)
                deleted += 1

    db.session.commit()
    track_activity(
        f"Dedup: resolved {deleted} duplicate(s) on {scope} timeline (action={action})",
        caseid=case_id,
    )
    return response_api_success({"removed": deleted, "action": action})

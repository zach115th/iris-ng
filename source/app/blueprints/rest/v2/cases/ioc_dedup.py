"""IOC deduplication REST endpoints (#83).

Surface area (all under /api/v2/cases/<cid>/iocs/dedup):
    POST /scan
        Exact groups (same type + normalised value; keep = first entry) and
        heuristic near candidates. Read-only.
    POST /auto-exact
        Collapse every exact group onto its first entry: links transferred,
        tags/description unioned, duplicates deleted.
    POST /resolve   body: {"action": "keep"|"merge", "keep_id", "delete_ids": [...]}
        Resolve one candidate pair (or more). Both actions transfer the
        loser's links to the survivor; "merge" also unions the fields.
        "keep both" is a client-side dismissal — no endpoint.
    POST /ai-scan   (?sync=true runs inline for scripts)
        Enqueue the AI pass on the async queue; 202 + task_id, poll
        GET /api/v2/ai/jobs/<task_id>; `result.pairs` lists the proposals.
"""
from __future__ import annotations

from flask import Blueprint
from flask import request
from flask_login import current_user

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.access_controls import ac_api_return_access_denied
from app.blueprints.rest.endpoints import response
from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_success
from app.business.errors import BusinessProcessingError
from app.business.ioc_dedup import auto_exact
from app.business.ioc_dedup import resolve
from app.business.ioc_dedup import scan_case
from app.iris_engine.access_control.utils import ac_fast_check_current_user_has_case_access
from app.models.authorization import CaseAccessLevel

case_ioc_dedup_blueprint = Blueprint("case_ioc_dedup", __name__)

_WRITE_LEVELS = [CaseAccessLevel.full_access]
_READ_LEVELS = [CaseAccessLevel.full_access, CaseAccessLevel.read_only]


def _check_access(case_id: int, levels: list):
    if not ac_fast_check_current_user_has_case_access(case_id, levels):
        return ac_api_return_access_denied(f"Case #{case_id}")
    return None


@case_ioc_dedup_blueprint.route("/<int:case_id>/iocs/dedup/scan", methods=["POST"])
@ac_api_requires()
def ioc_dedup_scan(case_id: int):
    denied = _check_access(case_id, _READ_LEVELS)
    if denied:
        return denied
    return response_api_success(scan_case(case_id))


@case_ioc_dedup_blueprint.route("/<int:case_id>/iocs/dedup/auto-exact", methods=["POST"])
@ac_api_requires()
def ioc_dedup_auto_exact(case_id: int):
    denied = _check_access(case_id, _WRITE_LEVELS)
    if denied:
        return denied
    try:
        return response_api_success(auto_exact(case_id, current_user.id))
    except BusinessProcessingError as e:
        return response_api_error(str(e))


@case_ioc_dedup_blueprint.route("/<int:case_id>/iocs/dedup/resolve", methods=["POST"])
@ac_api_requires()
def ioc_dedup_resolve(case_id: int):
    denied = _check_access(case_id, _WRITE_LEVELS)
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    delete_ids = body.get("delete_ids") or ([body["delete_id"]] if body.get("delete_id") else [])
    try:
        return response_api_success(resolve(case_id, body.get("action"), body.get("keep_id"),
                                            delete_ids, current_user.id))
    except BusinessProcessingError as e:
        return response_api_error(str(e))


@case_ioc_dedup_blueprint.route("/<int:case_id>/iocs/dedup/ai-scan", methods=["POST"])
@ac_api_requires()
def ioc_dedup_ai_scan(case_id: int):
    denied = _check_access(case_id, _READ_LEVELS)
    if denied:
        return denied
    if request.args.get("sync", "").lower() == "true":
        from app.iris_engine.ai.ioc_dedup import IocDedupError
        from app.iris_engine.ai.ioc_dedup import suggest_ioc_duplicates
        try:
            return response_api_success(suggest_ioc_duplicates(case_id))
        except IocDedupError as e:
            return response_api_error(str(e))
    from app.iris_engine.ai.ai_jobs import enqueue_ai_job
    job = enqueue_ai_job(feature='ioc_dedup', case_id=case_id, user_id=current_user.id,
                         params={})
    return response(202, data={'task_id': job.task_id, 'state': 'queued'})

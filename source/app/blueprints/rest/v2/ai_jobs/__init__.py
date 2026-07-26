#  IRIS Source Code
#
#  Async AI request queue — job-status REST (docs/19 §5b.3).
#
#  These endpoints are NOT case-scoped (a task_id is globally unique), so they
#  live under /api/v2/ai/jobs rather than under the case AI blueprint. The
#  submit side (POST that returns 202) stays on the per-feature endpoints
#  (e.g. /api/v2/cases/<id>/ai/summary) — see cases/ai.py — which call
#  enqueue_ai_job() and hand back the task_id resolved here.

from flask import Blueprint

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
from app.blueprints.responses import response
from app import db
from app.models.models import AiJob

from flask_login import current_user

ai_jobs_blueprint = Blueprint('ai_jobs_rest_v2', __name__, url_prefix='/ai/jobs')


def _serialize_job(job: AiJob) -> dict:
    import json
    result = None
    if job.result_json:
        try:
            result = json.loads(job.result_json)
        except (TypeError, ValueError):
            result = None
    return {
        'task_id': job.task_id,
        'case_id': job.case_id,
        'feature': job.feature,
        'state': job.state,
        'priority': job.priority,
        'submitted_at': job.submitted_at.isoformat() if job.submitted_at else None,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'finished_at': job.finished_at.isoformat() if job.finished_at else None,
        'artifact_id': job.artifact_id,
        'result': result,             # populated for dict features (chat)
        'error': job.error_message,
        'queue_position': _queue_position(job),
    }


def _queue_position(job: AiJob) -> int | None:
    """Best-effort: how many queued jobs sit ahead of this one (higher
    priority first, then older). Only meaningful while state == 'queued'.
    Not authoritative — celery is the real scheduler — but good enough for a
    "you're #N in line" affordance."""
    if job.state != 'queued':
        return None
    ahead = AiJob.query.filter(
        AiJob.state == 'queued',
        AiJob.id != job.id,
    ).filter(
        (AiJob.priority < job.priority) |
        ((AiJob.priority == job.priority) & (AiJob.id < job.id))
    ).count()
    return ahead + 1


def _owned_or_404(task_id: str) -> AiJob | None:
    job = AiJob.query.filter(AiJob.task_id == task_id).first()
    if job is None:
        return None
    # A user can only see their own jobs (the design's audit-trail intent).
    if job.user_id != current_user.id:
        return None
    return job


@ai_jobs_blueprint.get('/<string:task_id>')
@ac_api_requires()
def get_ai_job(task_id):
    """Poll one job. Client polls every 1-2s while queued/running."""
    job = _owned_or_404(task_id)
    if job is None:
        return response_api_not_found()
    return response_api_success(_serialize_job(job))


@ai_jobs_blueprint.delete('/<string:task_id>')
@ac_api_requires()
def cancel_ai_job(task_id):
    """Cancel a job. Effective only while queued — once running, the model
    call is in flight and we let it finish (marking 'cancelled' would orphan
    the result). The worker re-checks state at pickup, so a queued job flagged
    here is skipped if celery hands it over after the flag lands."""
    job = _owned_or_404(task_id)
    if job is None:
        return response_api_not_found()
    if job.state not in ('queued',):
        return response_api_error(f"Cannot cancel a job in state '{job.state}'")
    job.state = 'cancelled'
    db.session.commit()
    # Best-effort revoke in celery too (no-op if already delivered).
    try:
        from app import celery
        celery.control.revoke(task_id)
    except Exception:
        pass
    return response_api_success(_serialize_job(job))


@ai_jobs_blueprint.get('')
@ac_api_requires()
def list_ai_jobs():
    """List the caller's jobs, optionally filtered. Surfaces queue depth for
    the admin queue view + lets a panel recover an in-flight job on reload.

    Query params: case_id, state, limit (default 50, max 200)."""
    from flask import request
    q = AiJob.query.filter(AiJob.user_id == current_user.id)
    case_id = request.args.get('case_id', type=int)
    if case_id is not None:
        q = q.filter(AiJob.case_id == case_id)
    state = request.args.get('state', type=str)
    if state:
        q = q.filter(AiJob.state == state)
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
    except (TypeError, ValueError):
        limit = 50
    jobs = q.order_by(AiJob.id.desc()).limit(limit).all()
    return response_api_success({'jobs': [_serialize_job(j) for j in jobs]})

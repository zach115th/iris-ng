#  IRIS Source Code
#
#  Async AI request queue — dispatcher + helpers (docs/19 §5b.3).
#
#  The synchronous AI endpoints block a gunicorn worker for the full model
#  latency (120-180s on gpt-oss-20b for a large case). This module backs the
#  async pattern instead:
#
#    1. The REST POST calls enqueue_ai_job(...) — creates an AiJob row in
#       state='queued' and dispatches run_ai_job.apply_async() onto the
#       dedicated `ai_queue` (priority per feature). Returns the AiJob.
#    2. The iris-ai-worker container (celery, --concurrency=1, ai_queue only)
#       runs run_ai_job: flip to 'running', call the feature's orchestrator,
#       persist the result (artifact_id for artifact features, result_json for
#       dict features), flip to 'done' / 'error'.
#    3. The client polls GET /api/v2/ai/jobs/<task_id> until state is terminal.
#
#  Adding a feature = one FEATURES entry: the orchestrator callable, how to
#  pull the result out of it, and a default priority. No dispatcher edits.

from __future__ import annotations

import json
from typing import Any
from typing import Callable

from iris_interface.IrisInterfaceStatus import IIStatus

from app import app
from app import celery
from app import db
from app.models.models import AiJob
from app.models.models import CaseAiArtifact


# --- feature registry -------------------------------------------------------
#
# Each feature: how to run it, how to turn its return value into a stored
# result, and a default celery priority (1=high … 9=low). `runner` receives
# (case_id, params_dict) and returns whatever the orchestrator returns.
# `kind` is 'artifact' (return value is a CaseAiArtifact → store artifact_id)
# or 'dict' (return value is JSON-serializable → store result_json).


def _run_case_summary(case_id: int, params: dict[str, Any]):
    from app.iris_engine.ai.case_summary import generate_case_summary
    return generate_case_summary(case_id, force=bool(params.get('force', False)))


def _run_case_chat(case_id: int, params: dict[str, Any]):
    from app.iris_engine.ai.case_chat import ask_case
    return ask_case(
        case_id,
        params.get('question') or '',
        history=params.get('history') or [],
        variant=params.get('variant') if isinstance(params.get('variant'), str) else None,
    )


# Error classes are imported lazily inside run_ai_job so this module stays
# import-cheap and never fails to load if one orchestrator has a heavy import.
FEATURES: dict[str, dict[str, Any]] = {
    'case_summary': {'runner': _run_case_summary, 'kind': 'artifact', 'priority': 6},
    'chat':         {'runner': _run_case_chat,    'kind': 'dict',     'priority': 3},
}


class AiJobError(Exception):
    """Raised on enqueue-time validation problems (unknown feature, etc.)."""


def enqueue_ai_job(*, feature: str, case_id: int | None, user_id: int,
                   params: dict[str, Any] | None = None) -> AiJob:
    """Create an AiJob row + dispatch the celery task. Returns the AiJob.

    The celery task_id is generated up front so the row carries it before the
    task runs — the client can poll immediately after the 202.
    """
    cfg = FEATURES.get(feature)
    if cfg is None:
        raise AiJobError(f"Unknown AI feature '{feature}'")

    params = params or {}
    priority = int(cfg['priority'])

    # Generate the celery id ourselves so the row + task agree without a race.
    import uuid
    task_id = str(uuid.uuid4())

    job = AiJob(
        task_id=task_id,
        case_id=case_id,
        user_id=user_id,
        feature=feature,
        params=json.dumps(params, default=str),
        priority=priority,
        state='queued',
    )
    db.session.add(job)
    db.session.commit()

    # Resolve display metadata for the IRIS Modules Tasks page.
    # The page reads task kwargs to populate User / Case / Processing module columns.
    from app.models.authorization import User
    u = db.session.get(User, user_id)
    task_kwargs = {
        'init_user': u.user if u else f'user#{user_id}',
        'module_name': 'AI',
        'hook_name': feature,
    }
    if case_id is not None:
        task_kwargs['caseid'] = case_id

    # Dispatch onto ai_queue. Lower number = higher priority (celery/RabbitMQ).
    run_ai_job.apply_async(args=[job.id], task_id=task_id, priority=priority,
                           kwargs=task_kwargs)
    return job


def _terminal(job: AiJob, state: str, *, artifact_id: int | None = None,
              result: Any = None, error: str | None = None) -> None:
    from sqlalchemy.sql import func
    job.state = state
    job.finished_at = func.now()
    if artifact_id is not None:
        job.artifact_id = artifact_id
    if result is not None:
        job.result_json = json.dumps(result, default=str)
    if error is not None:
        job.error_message = error[:4000]
    db.session.commit()


@celery.task(bind=True)
def run_ai_job(self, job_id: int, **kwargs):
    """Worker entry point — runs one AI job to completion.

    Runs inside the celery ContextTask app context (see make_celery), so
    db.session + the orchestrators' app/db usage work. Concurrency is bounded
    to 1 by the iris-ai-worker (--concurrency=1) so only one model call is in
    flight at a time regardless of queue depth.

    Extra kwargs (init_user, caseid, module_name, hook_name) are passed by
    enqueue_ai_job so the IRIS Modules Tasks page shows the correct user, case,
    and feature name instead of the "Shadow Iris / Task did not returned a valid
    IIStatus object" fallback.
    """
    from sqlalchemy.sql import func

    job = db.session.get(AiJob, job_id)
    if job is None:
        return IIStatus(0xFF01, f'AiJob #{job_id} not found')

    # A DELETE may have cancelled the job between enqueue and pickup.
    if job.state == 'cancelled':
        app.logger.info(f"AiJob #{job_id} ({job.feature}) was cancelled before start — skipping")
        return IIStatus(0x0001, f'AiJob #{job_id} cancelled before pickup')

    cfg = FEATURES.get(job.feature)
    if cfg is None:
        _terminal(job, 'error', error=f"Unknown AI feature '{job.feature}'")
        return IIStatus(0xFF01, f"Unknown AI feature '{job.feature}'")

    job.state = 'running'
    job.started_at = func.now()
    db.session.commit()

    try:
        params = json.loads(job.params) if job.params else {}
    except (TypeError, ValueError):
        params = {}

    try:
        result = cfg['runner'](job.case_id, params)
    except Exception as exc:  # orchestrators raise their own *Error types
        app.logger.exception(f"AiJob #{job_id} ({job.feature}) failed")
        _terminal(job, 'error', error=str(exc))
        return IIStatus(0xFF01, f'AiJob #{job_id} ({job.feature}) failed',
                        logs=[str(exc)[:400]])

    if cfg['kind'] == 'artifact':
        art_id = result.id if isinstance(result, CaseAiArtifact) else None
        _terminal(job, 'done', artifact_id=art_id)
    else:
        _terminal(job, 'done', result=result)

    return IIStatus(0x0001, f'AiJob #{job_id} ({job.feature}) completed',
                    logs=[f'Feature: {job.feature}', f'Case ID: {job.case_id}'])

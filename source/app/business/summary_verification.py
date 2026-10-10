#  IRIS Source Code
#
#  Business layer of the verified executive summary (iris-ng, 2026-10-09):
#  the derived summary status, the analyst's answers to the review questions
#  and the state of the answers pass. The pipeline itself lives in
#  iris_engine/ai/case_summary.py; the routes in rest/v2/cases/ai.py.
#
#  summary_status is DERIVED, never stored:
#    no run                      -> draft   (every legacy summary)
#    an unanswered question      -> draft
#    otherwise                   -> verified
#  Every flag of a pass is a question whatever its severity. Nothing gates
#  the investigation report (decision 2026-10-09): the status is information
#  for the API, the case payload and the panel.

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func

from app import app
from app import db
from app.iris_engine.ai.summary_questions import KEEP_OPTION
from app.iris_engine.ai.summary_questions import OTHER_OPTION
from app.iris_engine.ai.summary_questions import resolve_answer
from app.models.cases import CasesEvent
from app.models.models import CaseAiArtifact
from app.models.models import CaseAssets
from app.models.models import CaseReceivedFile
from app.models.models import CaseSummaryFlag
from app.models.models import CaseSummaryRun
from app.models.models import CaseSummaryStep
from app.models.models import CaseTasks
from app.models.models import Ioc
from app.models.models import Notes

STATUS_DRAFT = "draft"
STATUS_VERIFIED = "verified"

# ref type -> (page, model, pk column, label column)
_REF_PAGES = {
    "note": ("notes", Notes, "note_id", "note_title"),
    "event": ("timeline", CasesEvent, "event_id", "event_title"),
    "task": ("tasks", CaseTasks, "id", "task_title"),
    "asset": ("assets", CaseAssets, "asset_id", "asset_name"),
    "ioc": ("ioc", Ioc, "ioc_id", "ioc_value"),
    "evidence": ("evidences", CaseReceivedFile, "id", "filename"),
}


class SummaryVerificationError(Exception):
    """A refused operation: `status` is the HTTP code, `reason` a stable
    machine-readable token, `data` extra fields for the body."""

    def __init__(self, message: str, *, reason: str, status: int = 409, data: dict | None = None):
        super().__init__(message)
        self.reason = reason
        self.status = status
        self.data = data or {}


# ----- lookups ----------------------------------------------------------------


def latest_summary_artifact(case_id: int) -> CaseAiArtifact | None:
    return (CaseAiArtifact.query
            .filter(CaseAiArtifact.case_id == case_id, CaseAiArtifact.kind == 'case_summary')
            .order_by(CaseAiArtifact.generated_at.desc(), CaseAiArtifact.id.desc())
            .first())


def run_for_artifact(artifact: CaseAiArtifact | None) -> CaseSummaryRun | None:
    if artifact is None:
        return None
    return CaseSummaryRun.query.filter(CaseSummaryRun.artifact_id == artifact.id).first()


def latest_run(case_id: int) -> tuple[CaseAiArtifact | None, CaseSummaryRun | None]:
    artifact = latest_summary_artifact(case_id)
    return artifact, run_for_artifact(artifact)


def open_questions(run: CaseSummaryRun | None) -> list[CaseSummaryFlag]:
    if run is None:
        return []
    return (CaseSummaryFlag.query
            .filter(CaseSummaryFlag.run_id == run.id, CaseSummaryFlag.status == 'open')
            .order_by(CaseSummaryFlag.id.asc())
            .all())


def derive_status(run: CaseSummaryRun | None, open_count: int) -> str:
    if run is None or open_count > 0:
        return STATUS_DRAFT
    return STATUS_VERIFIED


def summary_state(case_id: int) -> dict[str, Any]:
    artifact, run = latest_run(case_id)
    opens = open_questions(run)
    return {
        "summary_status": derive_status(run, len(opens)),
        "questions_open": len(opens),
        "artifact": artifact,
        "run": run,
    }


def newest_summary_artifacts(case_ids) -> dict[int, CaseAiArtifact]:
    """{case_id: newest `case_summary` artifact} in ONE DISTINCT ON statement
    (analyst edit or not - the caller reads display_content). Shared by the
    executive_summary prefetch and the summary-state prefetch of
    CaseDetailsSchema so a dump touches case_ai_artifact exactly once."""
    ids = sorted({i for i in case_ids if i is not None})
    if not ids:
        return {}
    arts = (CaseAiArtifact.query
            .filter(CaseAiArtifact.case_id.in_(ids), CaseAiArtifact.kind == 'case_summary')
            .order_by(CaseAiArtifact.case_id, CaseAiArtifact.generated_at.desc(), CaseAiArtifact.id.desc())
            .distinct(CaseAiArtifact.case_id)
            .all())
    return {a.case_id: a for a in arts}


def summary_states_for(case_ids) -> dict[int, dict[str, Any]]:
    """{case_id: {summary_status, summary_questions_open}} for a batch: the
    newest summary artifact per case (one statement), their runs (one), and
    one grouped count of open questions."""
    ids = sorted({i for i in case_ids if i is not None})
    return summary_states_for_artifacts(newest_summary_artifacts(ids), ids)


def summary_states_for_artifacts(arts: dict[int, CaseAiArtifact], case_ids) -> dict[int, dict[str, Any]]:
    """The run + flag half of summary_states_for, over artifacts already
    fetched. Every id in `case_ids` is in the result (draft / 0 by default)."""
    ids = sorted({i for i in case_ids if i is not None})
    out = {i: {"summary_status": STATUS_DRAFT, "summary_questions_open": 0} for i in ids}
    art_case = {a.id: cid for cid, a in arts.items()}
    if not art_case:
        return out
    runs = CaseSummaryRun.query.filter(CaseSummaryRun.artifact_id.in_(list(art_case))).all()
    run_case = {r.id: art_case[r.artifact_id] for r in runs}
    counts: dict[int, int] = {}
    if run_case:
        rows = (db.session.query(CaseSummaryFlag.run_id, func.count(CaseSummaryFlag.id))
                .filter(CaseSummaryFlag.run_id.in_(list(run_case)), CaseSummaryFlag.status == 'open')
                .group_by(CaseSummaryFlag.run_id)
                .all())
        counts = {rid: int(n) for rid, n in rows}
    for r in runs:
        n = counts.get(r.id, 0)
        out[run_case[r.id]] = {"summary_status": derive_status(r, n), "summary_questions_open": n}
    return out


# ----- serialisation ------------------------------------------------------------


def deep_link(case_id: int, ref_type: str, ref_id: int) -> str | None:
    page = _REF_PAGES.get(ref_type)
    if page is None:
        return None
    return f"/case/{page[0]}?cid={case_id}&shared={ref_id}"


def object_label(case_id: int, ref_type: str, ref_id: int) -> str | None:
    page = _REF_PAGES.get(ref_type)
    if page is None:
        return None
    _, model, pk, label_col = page
    case_col = 'note_case_id' if model is Notes else ('task_case_id' if model is CaseTasks else 'case_id')
    row = model.query.filter(getattr(model, pk) == ref_id, getattr(model, case_col) == case_id).first()
    if row is None:
        return None
    return getattr(row, label_col, None)


def resolve_refs(case_id: int, refs) -> list[dict[str, Any]]:
    out = []
    for r in refs or []:
        if not isinstance(r, dict):
            continue
        t, i = r.get("type"), r.get("id")
        if t not in _REF_PAGES or not isinstance(i, int):
            continue
        out.append({"type": t, "id": i, "label": object_label(case_id, t, i), "url": deep_link(case_id, t, i)})
    return out


def _loads(text: str | None, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def flag_options(flag: CaseSummaryFlag) -> list[dict[str, Any]]:
    """The options a flag offers: the stored list, or the two fixed ones for
    a flag whose question was never built (a legacy run, a crashed builder)."""
    opts = _loads(flag.options_json, None)
    if isinstance(opts, list) and opts:
        return opts
    return [dict(KEEP_OPTION), dict(OTHER_OPTION)]


def serialize_flag(flag: CaseSummaryFlag, case_id: int, *, resolve: bool = True) -> dict[str, Any]:
    refs = _loads(flag.source_refs_json, [])
    return {
        "id": flag.id,
        "run_id": flag.run_id,
        "claim_id": flag.claim_id,
        "code": flag.code,
        "severity": flag.severity,
        "source": flag.source,
        "message": flag.message,
        "detail": _loads(flag.detail_json, None),
        "source_refs": resolve_refs(case_id, refs) if resolve else refs,
        "question": flag.question or flag.message,
        "options": flag_options(flag),
        "status": flag.status,
        "answer": _loads(flag.answer_json, None),
        "answered_by": flag.answered_by.name if flag.answered_by else None,
        "answered_at": flag.answered_at.isoformat() if flag.answered_at else None,
        "created_at": flag.created_at.isoformat() if flag.created_at else None,
    }


def serialize_step(step: CaseSummaryStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "step": step.step,
        "provider": step.provider,
        "backend_id": step.backend_id,
        "backend_label": step.backend_label,
        "model": step.model,
        "prompt_id": step.prompt_id,
        "artifact_id": step.artifact_id,
        "cached": bool(step.cached),
        "outcome": step.outcome,
        "error": step.error,
        "usage": _loads(step.usage_json, None),
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "finished_at": step.finished_at.isoformat() if step.finished_at else None,
    }


def serialize_run(run: CaseSummaryRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "artifact_id": run.artifact_id,
        "pass_no": run.pass_no,
        "pass_kind": run.pass_kind,
        "parent_run_id": run.parent_run_id,
        "input_hash": run.input_hash,
        "pipeline_version": run.pipeline_version,
        "verifier_status": run.verifier_status,
        "writer_meta": _loads(run.writer_meta_json, None),
        "answers": _loads(run.answers_json, None),
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def verification_summary(run: CaseSummaryRun | None) -> dict[str, Any] | None:
    """The compact block GET /summary carries beside the text."""
    if run is None:
        return None
    return {
        "run_id": run.id,
        "pass_no": run.pass_no,
        "pass_kind": run.pass_kind,
        "verifier_status": run.verifier_status,
        "previous_run_id": run.parent_run_id,
    }


def apply_state(run: CaseSummaryRun | None) -> dict[str, Any]:
    """Can the answers pass run now, and if not, why."""
    if run is None:
        return {"can_apply": False, "reason": "no verified summary"}
    flags = list(run.flags)
    if not flags:
        return {"can_apply": False, "reason": "no review questions on this pass"}
    opens = [f for f in flags if f.status == "open"]
    if opens:
        return {"can_apply": False, "reason": f"{len(opens)} question(s) still unanswered"}
    actions = [(_loads(f.answer_json, {}) or {}).get("action") for f in flags]
    if all(a == "keep" for a in actions):
        return {"can_apply": False, "reason": "every answer keeps the summary as written"}
    return {"can_apply": True, "reason": None}


def _pass_chain(run: CaseSummaryRun, limit: int = 12) -> list[dict[str, Any]]:
    """This pass and its ancestors, newest first: id, pass number and kind,
    verifier status, question counts, created_at."""
    out = []
    cur = run
    while cur is not None and len(out) < limit:
        flags = list(cur.flags)
        out.append({
            "id": cur.id, "pass_no": cur.pass_no, "pass_kind": cur.pass_kind, "verifier_status": cur.verifier_status,
            "artifact_id": cur.artifact_id, "questions": len(flags),
            "answered": sum(1 for f in flags if f.status == "answered"),
            "high": sum(1 for f in flags if f.severity == "high"),
            "created_at": cur.created_at.isoformat() if cur.created_at else None,
        })
        cur = db.session.get(CaseSummaryRun, cur.parent_run_id) if cur.parent_run_id else None
    return out


def verification_payload(case_id: int) -> dict[str, Any]:
    """GET /summary/verification: null lists = no run (legacy summary or none),
    [] = a run that has none."""
    state = summary_state(case_id)
    artifact, run = state["artifact"], state["run"]
    base = {
        "summary_status": state["summary_status"],
        "questions_open": state["questions_open"],
        "artifact_id": artifact.id if artifact else None,
        "legacy": artifact is not None and run is None,
        "apply": apply_state(run),
    }
    if run is None:
        return {**base, "run": None, "claims": None, "flags": None, "steps": None, "previous_pass": None, "passes": None}
    previous = None
    if run.parent_run_id:
        parent = db.session.get(CaseSummaryRun, run.parent_run_id)
        if parent is not None:
            previous = {
                "run": serialize_run(parent),
                "flags": [serialize_flag(f, case_id) for f in parent.flags],
                "steps": [serialize_step(s) for s in parent.steps],
                "claims": _loads(parent.claims_json, []),
            }
    return {
        **base,
        "run": serialize_run(run),
        "claims": _loads(run.claims_json, []),
        "flags": [serialize_flag(f, case_id) for f in run.flags],
        "steps": [serialize_step(s) for s in run.steps],
        "previous_pass": previous,
        "passes": _pass_chain(run),
    }


# ----- analyst actions ---------------------------------------------------------


def answer_flag(case_id: int, flag_id: int, option_id: str | None, text: str | None, user_id: int) -> CaseSummaryFlag:
    """Record the analyst's answer to one review question. 404 for a flag of
    another case, 409 when it is already answered, 400 for an unknown option
    or an "Other" without text."""
    flag = (CaseSummaryFlag.query
            .join(CaseSummaryRun, CaseSummaryRun.id == CaseSummaryFlag.run_id)
            .filter(CaseSummaryFlag.id == flag_id, CaseSummaryRun.case_id == case_id)
            .first())
    if flag is None:
        raise SummaryVerificationError("Question not found for this case", reason="flag_not_found", status=404)
    if flag.status != "open":
        raise SummaryVerificationError("This question is already answered", reason="flag_not_open", status=409,
                                       data={"status": flag.status})
    try:
        answer = resolve_answer(flag_options(flag), str(option_id or "").strip(), text, flag.claim_id)
    except ValueError as exc:
        raise SummaryVerificationError(str(exc), reason="bad_answer", status=400) from exc
    flag.status = "answered"
    flag.answer_json = json.dumps(answer, ensure_ascii=False)
    flag.answered_by_id = user_id
    flag.answered_at = datetime.utcnow()
    db.session.commit()
    app.logger.info(f"Case #{case_id}: review question {flag.id} ({flag.code}) answered '{answer['action']}' by user {user_id}")
    return flag


__all__ = ["STATUS_DRAFT", "STATUS_VERIFIED", "SummaryVerificationError", "latest_summary_artifact",
           "run_for_artifact", "latest_run", "open_questions", "derive_status", "summary_state",
           "newest_summary_artifacts", "summary_states_for", "summary_states_for_artifacts", "deep_link",
           "object_label", "resolve_refs", "flag_options", "serialize_flag", "serialize_step", "serialize_run",
           "verification_summary", "apply_state", "verification_payload", "answer_flag"]

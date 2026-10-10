#  IRIS Source Code
#
#  Executive case summary -- the verified pipeline (iris-ng, 2026-10-09).
#
#  Stage 1 (per-domain specialists, unchanged in shape): five bounded LLM
#  calls compress the bulky free-form domains (notes, timeline, IOCs, assets,
#  evidence) into structured JSON sub-summaries that CITE the objects they
#  draw on (`[note:12,15]`, `event_id`, `asset_id`, `evidence_ids`). Each is
#  persisted in case_ai_artifact as `case_summary:<domain>` and cached on a
#  stable hash of its own payload + prompt + model. An emitted id the
#  specialist was not given fails that domain; nothing non-contract is
#  persisted.
#
#  Stage 2 (writer): one LLM call turns the structured metadata + raw tasks +
#  the five sub-summaries into a list of sourced CLAIMS -- id, section,
#  text, tier, source_refs, event_time -- not prose. The server renders the
#  claims into the ten-section leadership markdown (summary_render.py); the
#  text, counts, tables and fixed lines are the server's.
#
#  Stage 3 (checks, code only): every ref exists in this case; numbers,
#  dates, hosts, accounts and addresses in a claim appear in its cited
#  sources; task words match task records; evidence claims match the
#  register (summary_checks.py).
#
#  Stage 4 (verifier, a second LLM role): per-claim verdicts against ONLY the
#  cited sources + one whole-document pass for contradictions and known
#  failure patterns (summary_verifier.py). The verifier never edits.
#
#  Flags carry a severity. When a HIGH flag exists after pass 1 (other than
#  the pipeline's own "verifier unavailable / failed"), ONE automatic revise
#  pass sends the writer its claims + the flags and runs stages 2-4 again.
#  Never a third automatic pass. Every pass is persisted in ONE transaction:
#  the artifact (the markdown every consumer reads), the run (claims, checks,
#  verdicts), the steps (provider, backend id + label, model, prompt id,
#  timestamps per step) and the flags.
#
#  Stage 5 (review questions): every flag of the final pass becomes a
#  question with concrete options (summary_questions.py: one batched call on
#  the verifier role proposes rewrites / tier changes / drops; the server adds
#  "keep as written" and "other"). The analyst answers them in the Review
#  tab; `apply_answers_pass()` then applies the answers IN CODE, re-renders,
#  reruns the deterministic checks (a flag the analyst kept is not asked
#  again) and calls the writer only for free-text answers. Each answers pass
#  is started by hand, so there is never an automatic loop. A summary reads
#  `draft` while a question is unanswered and `verified` otherwise
#  (business/summary_verification.py); nothing gates the report.
#
#  Roles: the writer and the specialists use the `case_summary` feature
#  override, the verifier `case_summary_verifier` (Settings -> AI).
#
#  Why multi-pass: local models (LM Studio gpt-oss-20b at 32K context)
#  can blow past the context budget on real cases -- 30 notes x 4 KB +
#  75 timeline events x 1.5 KB easily exceed the window. The map-reduce
#  pattern gives each domain its own focused window.

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func

from app import app
from app import db
from app.iris_engine.ai import summary_questions
from app.iris_engine.ai import summary_verifier
from app.iris_engine.ai.json_reply import JsonReply
from app.iris_engine.ai.json_reply import ask_json
from app.iris_engine.ai.json_reply import truncation_hint
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client
from app.iris_engine.ai.summary_checks import CHECKS_VERSION
from app.iris_engine.ai.summary_checks import REF_TYPES
from app.iris_engine.ai.summary_checks import SECTIONS
from app.iris_engine.ai.summary_checks import TASK_STATUS_MAP
from app.iris_engine.ai.summary_checks import TIERS
from app.iris_engine.ai.summary_checks import Flag
from app.iris_engine.ai.summary_checks import make_flag
from app.iris_engine.ai.summary_checks import normalise
from app.iris_engine.ai.summary_checks import run_checks
from app.iris_engine.ai.summary_checks import specialist_ids
from app.iris_engine.ai.summary_render import is_sparse
from app.iris_engine.ai.summary_render import render_claims_markdown
from app.iris_engine.ai.summary_render import render_sparse
from app.iris_engine.ai.summary_verifier import parse_json_object
from app.iris_engine.ai.summary_verifier import step_record
from app.iris_engine.module_handler.module_handler import call_modules_hook
from app.models.cases import Cases
from app.models.cases import CasesEvent
from app.models.models import CaseAiArtifact
from app.models.models import CaseAssets
from app.models.models import CaseReceivedFile
from app.models.models import CaseSummaryFlag
from app.models.models import CaseSummaryRun
from app.models.models import CaseSummaryStep
from app.models.models import CaseTasks
from app.models.models import CompromiseStatus
from app.models.models import Ioc
from app.models.models import Notes
from app.models.models import TaskAssignee
from app.models.models import UserActivity


CASE_SUMMARY_KIND = "case_summary"
CASE_SUMMARY_PROMPT_ID = "CaseSummaryWriter-v1"   # the artifact's prompt_id = the writer prompt
PIPELINE_VERSION = "verified-1"                   # folded into the writer hash
WRITER_MAX_TOKENS = 12000    # ~30 claims = 3-4 k output; a reasoning model thinks first
SPECIALIST_MAX_TOKENS = 6000
MAX_CLAIMS = 60
MAX_CLAIM_CHARS = 1000
OVERDUE_DAYS = 14

WRITER_COMPACT_SUFFIX = (
    "\n\nYour previous reply was cut off by the output limit before the JSON closed. "
    "Answer NOW with the JSON object only: at most two claims per section, each one short "
    "sentence with its source_refs. No reasoning before the answer."
)
SPECIALIST_COMPACT_SUFFIX = (
    "\n\nYour previous reply was cut off by the output limit before the JSON closed. "
    "Answer NOW with the JSON object only; keep every text field to one short sentence and "
    "keep the citations. No reasoning before the answer."
)


# Writer model routing. The writer call is the dominant latency in the
# pipeline. This map picks a faster sibling within the same backend family;
# LM Studio and any other backend whose model id is not a known Claude
# variant fall through to None -- the writer uses the configured model
# unchanged. Add entries when new fast/slow pairings are worth optimizing.
SYNTHESIZER_FAST_MODEL_MAP: dict[str, str] = {
    "claude-opus-4-7":  "claude-haiku-4-5",
    "claude-sonnet-4-6": "claude-haiku-4-5",
}


def _pick_synthesizer_model(configured_model: str) -> str:
    """Return the model to use for the writer call (the configured model
    unchanged when no fast sibling is mapped)."""
    return SYNTHESIZER_FAST_MODEL_MAP.get(configured_model, configured_model)


PROMPTS_DIR = Path(__file__).parent.parent.parent / "resources" / "ai_prompts"

# Per-domain specialist config: prompt filename, artifact kind, prompt id,
# the ref type the specialist may cite, and whether the writer consumes the
# whole JSON (structured) or just its `summary` bullets.
DOMAIN_CONFIG: dict[str, dict[str, Any]] = {
    "notes":    {"prompt_file": "case_summary_notes.md",    "kind": "case_summary:notes",    "prompt_id": "CaseSummaryNotes-v2",    "structured": False, "ref_type": "note",     "id_key": "note_id"},
    "timeline": {"prompt_file": "case_summary_timeline.md", "kind": "case_summary:timeline", "prompt_id": "CaseSummaryTimeline-v3", "structured": True,  "ref_type": "event",    "id_key": "event_id"},
    "iocs":     {"prompt_file": "case_summary_iocs.md",     "kind": "case_summary:iocs",     "prompt_id": "CaseSummaryIocs-v2",     "structured": False, "ref_type": "ioc",      "id_key": "ioc_id"},
    "assets":   {"prompt_file": "case_summary_assets.md",   "kind": "case_summary:assets",   "prompt_id": "CaseSummaryAssets-v2",   "structured": True,  "ref_type": "asset",    "id_key": "asset_id"},
    "evidence": {"prompt_file": "case_summary_evidence.md", "kind": "case_summary:evidence", "prompt_id": "CaseSummaryEvidence-v2", "structured": True,  "ref_type": "evidence", "id_key": "evidence_id"},
}
_DOMAIN_LIST_KEY = {"notes": "notes", "timeline": "timeline", "iocs": "iocs", "assets": "assets", "evidence": "evidence"}
_ASSET_STATUS_VALUES = ("Confirmed compromised", "Suspected compromised", "Under investigation")
_TLP_RANK = {"red": 4, "amber+strict": 3, "amber": 2, "green": 1, "clear": 0, "white": 0}
_TLP_RE = re.compile(r"tlp:\s*(red|amber\+strict|amber|green|clear|white)\b", re.IGNORECASE)
_EVENT_TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})")


class CaseSummaryError(Exception):
    """Raised when summary generation can't proceed."""


def _load_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8")


def load_system_prompt() -> str:
    """The writer prompt -- kept exported for back-compat with anything that
    imported the synthesizer prompt loader from the v1 module."""
    return _load_prompt("case_summary_writer.md")


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[:limit] + " […]"


def _fmt_event_time(dt: datetime | None) -> str | None:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else None


def task_status_class(name: str | None) -> str | None:
    return TASK_STATUS_MAP.get((name or "").strip().lower())


def _tasks_with_assignees(task_ids: list[int]) -> set[int]:
    if not task_ids:
        return set()
    rows = (db.session.query(TaskAssignee.task_id)
            .filter(TaskAssignee.task_id.in_(task_ids))
            .distinct()
            .all())
    return {r[0] for r in rows}


# ----- Domain payloads ------------------------------------------------------
#
# Each builder returns a JSON-serializable dict + a "is_empty" flag. The
# orchestrator skips the specialist call entirely when the domain is empty.
# Every object carries its id so the specialists can cite it and the writer
# can reference it; the deterministic checks resolve those ids against the
# case record.


def _build_notes_payload(case_id: int) -> tuple[dict[str, Any], bool]:
    rows = Notes.query.filter(Notes.note_case_id == case_id).order_by(Notes.note_id.asc()).limit(50).all()
    notes = [
        {
            "note_id": n.note_id,
            "title": n.note_title,
            # iris-ng #129: the analyst's labels travel with the note; [] = none set
            "tags": [t.strip() for t in (n.note_tags or "").split(",") if t.strip()],
            "content": _truncate(n.note_content, 6000),
        }
        for n in rows
    ]
    return {"notes": notes}, len(notes) == 0


def _build_timeline_payload(case_id: int) -> tuple[dict[str, Any], bool]:
    # The "Add to summary" checkbox decides what reaches this specialist.
    # `isnot(False)` rather than `== True` on purpose: the column is nullable
    # and older events predate the flag, so NULL has to mean included --
    # `!= False` would drop them, since in SQL NULL != False is NULL.
    rows = (
        CasesEvent.query
        .filter(CasesEvent.case_id == case_id)
        .filter(CasesEvent.event_in_summary.isnot(False))
        .order_by(CasesEvent.event_date.asc(), CasesEvent.event_id.asc())
        .limit(150)
        .all()
    )
    # Count what the analyst excluded so the writer can tell a curated
    # timeline from a genuinely quiet case.
    excluded = (
        CasesEvent.query
        .filter(CasesEvent.case_id == case_id)
        .filter(CasesEvent.event_in_summary.is_(False))
        .count()
    )
    timeline = [
        {
            "event_id": e.event_id,
            "date": e.event_date.isoformat() if e.event_date else None,
            # Pre-formatted so the specialist copies it and the checks compare
            # the same digits (naive UTC, minute precision).
            "event_time": _fmt_event_time(e.event_date),
            "title": e.event_title,
            "tags": e.event_tags or None,
            "content": _truncate(e.event_content, 1500),
            "source": _truncate(e.event_source, 200),
            "is_flagged": bool(e.event_is_flagged),
        }
        for e in rows
    ]
    return {"timeline": timeline, "events_excluded_by_analyst": excluded}, len(timeline) == 0


def _build_iocs_payload(case_id: int) -> tuple[dict[str, Any], bool]:
    rows = Ioc.query.filter(Ioc.case_id == case_id).order_by(Ioc.ioc_id.asc()).all()
    iocs = [
        {
            "ioc_id": i.ioc_id,
            "value": i.ioc_value,
            "type": getattr(i.ioc_type, "type_name", None) if getattr(i, "ioc_type", None) else None,
            "tlp": getattr(i.tlp, "tlp_name", None) if getattr(i, "tlp", None) else None,
            "description": _truncate(i.ioc_description, 500),
            "tags": i.ioc_tags or None,
        }
        for i in rows
    ]
    return {"iocs": iocs}, len(iocs) == 0


def _compromise_name(status_id) -> str | None:
    try:
        return CompromiseStatus(status_id).name if status_id is not None else None
    except ValueError:
        return None


def _build_assets_payload(case_id: int) -> tuple[dict[str, Any], bool]:
    rows = CaseAssets.query.filter(CaseAssets.case_id == case_id).order_by(CaseAssets.asset_id.asc()).all()
    assets = [
        {
            "asset_id": a.asset_id,
            "name": a.asset_name,
            "type": getattr(a.asset_type, "asset_name", None) if getattr(a, "asset_type", None) else None,
            "ip": a.asset_ip or None,
            "domain": a.asset_domain or None,
            "compromise_status_id": a.asset_compromise_status_id,
            "compromise_status": _compromise_name(a.asset_compromise_status_id),
            "description": _truncate(a.asset_description, 1000),
            "tags": a.asset_tags or None,
        }
        for a in rows
    ]
    return {"assets": assets}, len(assets) == 0


def _build_tasks_payload(case_id: int) -> list[dict[str, Any]]:
    rows = CaseTasks.query.filter(CaseTasks.task_case_id == case_id).order_by(CaseTasks.id.asc()).all()
    assigned = _tasks_with_assignees([t.id for t in rows])
    out = []
    for t in rows:
        name = getattr(t.status, "status_name", None) if getattr(t, "status", None) else None
        out.append({
            "task_id": t.id,
            "title": t.task_title,
            "status_id": t.task_status_id,
            "status": name,
            # open | blocked | closed, from TASK_STATUS_MAP; an unmapped status
            # reads as open here and raises a low flag in the checks.
            "status_class": task_status_class(name) or "open",
            "has_assignee": t.id in assigned,
            "description": _truncate(t.task_description, 800),
            "open_date": t.task_open_date.isoformat() if t.task_open_date else None,
            "close_date": t.task_close_date.isoformat() if t.task_close_date else None,
        })
    return out


def _build_evidence_payload(case_id: int) -> tuple[dict[str, Any], bool]:
    """Evidence register for the case (the Evidence tab).

    `physical_location` is resolved from the linked drive, not from the
    column of the same name on this row: that column is deprecated and is
    NULL for anything registered after the Inventory tab shipped. The row's
    own value is kept as a fallback for legacy rows with no drive.
    """
    rows = (
        CaseReceivedFile.query
        .filter(CaseReceivedFile.case_id == case_id)
        .order_by(CaseReceivedFile.date_added.asc(), CaseReceivedFile.id.asc())
        .limit(200)
        .all()
    )
    evidence = []
    for e in rows:
        drive = getattr(e, "drive", None)
        evidence.append({
            "evidence_id": e.id,
            "filename": e.filename,
            "type": getattr(e.type, "name", None) if getattr(e, "type", None) else None,
            # Key names match the DB columns because case_chat_evidence.md
            # names them literally. Explicit null rather than omission: a key
            # that is simply absent reads as "unknown" instead of "not recorded".
            "file_hash": e.file_hash or None,
            "file_size": e.file_size,
            "description": _truncate(e.file_description, 800),
            "date_added": e.date_added.isoformat() if e.date_added else None,
            "acquisition_date": e.acquisition_date.isoformat() if e.acquisition_date else None,
            "coverage_start": e.start_date.isoformat() if e.start_date else None,
            "coverage_end": e.end_date.isoformat() if e.end_date else None,
            "created_by": e.created_by or None,
            "barcode": e.barcode or None,
            "physical_location": (
                (drive.physical_location if drive else None) or e.physical_location or None
            ),
            "drive_label": (drive.label or drive.barcode) if drive else None,
            "linked_assets": [
                link.asset.asset_name
                for link in (getattr(e, "assets", None) or [])
                if getattr(link, "asset", None) is not None
            ] or None,
        })

    # Counted here, not by the model: "3 of 11 items are unhashed" is exactly
    # the kind of figure that ends up in a briefing read by legal.
    integrity = {
        "items_total": len(evidence),
        "items_with_hash": sum(1 for e in evidence if e["file_hash"]),
        "items_missing_hash": sum(1 for e in evidence if not e["file_hash"]),
        "items_without_asset_link": sum(1 for e in evidence if not e["linked_assets"]),
        "items_without_coverage_window": sum(
            1 for e in evidence if not (e["coverage_start"] or e["coverage_end"])
        ),
    }
    return {"evidence": evidence, "integrity": integrity}, len(evidence) == 0


def _build_activity_payload(case_id: int) -> dict[str, Any]:
    """Cross-object recency signal for the "no activity in N hours" line.

    A case can be actively worked via IOCs, assets, notes, tasks, or evidence
    without a new *timeline* event. This computes, per object type, the most
    recent "touch" timestamp from that type's best column, plus an overall
    last-activity time and the hours since (server-side). Timeline activity
    uses `event_added` (when the event was logged) NOT `event_date` (the
    historical time the event describes). The `UserActivity` audit log is
    folded in as a backstop. Returns naive-UTC ISO strings + hours.
    """
    now = datetime.utcnow()
    per_type: dict[str, datetime | None] = {}

    per_type["assets"] = db.session.query(
        func.max(func.coalesce(CaseAssets.date_update, CaseAssets.date_added))
    ).filter(CaseAssets.case_id == case_id).scalar()

    per_type["notes"] = db.session.query(
        func.max(func.coalesce(Notes.note_lastupdate, Notes.note_creationdate))
    ).filter(Notes.note_case_id == case_id).scalar()

    per_type["tasks"] = db.session.query(
        func.max(func.coalesce(CaseTasks.task_last_update, CaseTasks.task_open_date))
    ).filter(CaseTasks.task_case_id == case_id).scalar()

    per_type["timeline"] = db.session.query(
        func.max(func.coalesce(CasesEvent.event_added, CasesEvent.event_date))
    ).filter(CasesEvent.case_id == case_id).scalar()

    per_type["evidence"] = db.session.query(
        func.max(CaseReceivedFile.date_added)
    ).filter(CaseReceivedFile.case_id == case_id).scalar()

    last_audit = db.session.query(
        func.max(UserActivity.activity_date)
    ).filter(UserActivity.case_id == case_id).scalar()
    per_type["audit_log"] = last_audit

    candidates = [v for v in per_type.values() if v is not None]
    last_activity = max(candidates) if candidates else None

    def _fmt(dt: datetime | None) -> str | None:
        return dt.isoformat() + "Z" if dt is not None else None

    def _hours(dt: datetime | None) -> float | None:
        if dt is None:
            return None
        return round((now - dt).total_seconds() / 3600.0, 1)

    return {
        "now_utc": now.isoformat() + "Z",
        "last_activity_at": _fmt(last_activity),
        "hours_since_last_activity": _hours(last_activity),
        "per_type_last_activity": {
            k: {"at": _fmt(v), "hours_ago": _hours(v)}
            for k, v in per_type.items()
        },
    }


# ----- The case record (for the deterministic checks and the verifier) ------


def _text(*parts) -> str:
    return " ".join(str(p) for p in parts if p not in (None, ""))


def _dates(*values) -> set:
    return {v.date() if isinstance(v, datetime) else v for v in values if v is not None}


def build_case_record(case_id: int) -> dict[str, Any]:
    """Every object of the case with its FULL text, keyed by id per ref type.
    `search` is the normalised text the checks match tokens against, `text`
    the original the verifier reads, `label` the title for deep links, plus
    the structured fields the task / evidence rules compare. Only this case's
    rows are loaded, so "belongs to this case" is "id in the record".
    `allowed_numbers` are the server counts a claim may quote unsourced."""
    record: dict[str, Any] = {"case_id": case_id, "notes": {}, "events": {}, "tasks": {}, "assets": {},
                              "iocs": {}, "evidence": {}, "allowed_numbers": {"*": set(), "evidence": set()}}

    for n in Notes.query.filter(Notes.note_case_id == case_id).all():
        text = _text(n.note_title, n.note_content, n.note_tags)
        record["notes"][n.note_id] = {
            "id": n.note_id, "label": n.note_title, "text": text, "search": normalise(text),
            "dates": _dates(n.note_creationdate, n.note_lastupdate), "numbers": {n.note_id},
        }

    for e in CasesEvent.query.filter(CasesEvent.case_id == case_id).all():
        when = _fmt_event_time(e.event_date)
        text = _text(e.event_title, e.event_content, e.event_raw, e.event_source, e.event_tags, when)
        record["events"][e.event_id] = {
            "id": e.event_id, "label": e.event_title, "event_time": when, "text": text,
            "search": normalise(text), "dates": _dates(e.event_date), "numbers": {e.event_id},
        }

    tasks = CaseTasks.query.filter(CaseTasks.task_case_id == case_id).all()
    assigned = _tasks_with_assignees([t.id for t in tasks])
    class_counts: dict[str, int] = {"open": 0, "blocked": 0, "closed": 0}
    for t in tasks:
        name = getattr(t.status, "status_name", None) if getattr(t, "status", None) else None
        cls = task_status_class(name)
        class_counts[cls or "open"] += 1
        # The verifier reads `text`: say in words what the structured fields
        # hold, or it judges "unassigned" / "confirmed compromised" / "unhashed"
        # unsupported (the live run of 2026-10-09 lost a revise pass to that).
        text = _text(t.task_title, t.task_description, f"status: {name}" if name else None, t.task_tags,
                     "has an assignee" if t.id in assigned else "no assignee")
        record["tasks"][t.id] = {
            "id": t.id, "label": t.task_title, "status_name": name, "status_class": cls,
            "has_assignee": t.id in assigned, "text": text, "search": normalise(text),
            "dates": _dates(t.task_open_date, t.task_close_date), "numbers": {t.id},
        }

    for a in CaseAssets.query.filter(CaseAssets.case_id == case_id).all():
        atype = getattr(a.asset_type, "asset_name", None) if getattr(a, "asset_type", None) else None
        compromise = _compromise_name(a.asset_compromise_status_id)
        text = _text(a.asset_name, atype, a.asset_ip, a.asset_domain, a.asset_description, a.asset_tags,
                     f"compromise status: {(compromise or 'to_be_determined').replace('_', ' ')}")
        record["assets"][a.asset_id] = {
            "id": a.asset_id, "label": a.asset_name, "name": a.asset_name, "ip": a.asset_ip or None,
            "domain": a.asset_domain or None, "compromise_status": compromise,
            "text": text, "search": normalise(text), "dates": _dates(a.date_added, a.date_update),
            "numbers": {a.asset_id},
        }

    for i in Ioc.query.filter(Ioc.case_id == case_id).all():
        itype = getattr(i.ioc_type, "type_name", None) if getattr(i, "ioc_type", None) else None
        text = _text(i.ioc_value, itype, i.ioc_description, i.ioc_tags)
        record["iocs"][i.ioc_id] = {
            "id": i.ioc_id, "label": i.ioc_value, "value": i.ioc_value, "type": itype,
            "text": text, "search": normalise(text), "dates": set(), "numbers": {i.ioc_id},
        }

    for ev in CaseReceivedFile.query.filter(CaseReceivedFile.case_id == case_id).all():
        etype = getattr(ev.type, "name", None) if getattr(ev, "type", None) else None
        text = _text(ev.filename, etype, ev.file_description,
                     f"hash: {ev.file_hash}" if ev.file_hash else "no hash recorded",
                     ev.barcode, f"custodian: {ev.created_by}" if ev.created_by else None,
                     f"size: {ev.file_size} bytes" if ev.file_size else None,
                     f"added: {ev.date_added.date().isoformat()}" if ev.date_added else None,
                     f"acquired: {ev.acquisition_date.date().isoformat()}" if ev.acquisition_date else None)
        record["evidence"][ev.id] = {
            "id": ev.id, "label": ev.filename, "filename": ev.filename, "file_hash": ev.file_hash or None,
            "file_size": ev.file_size, "created_by": ev.created_by or None, "text": text,
            "search": normalise(text),
            "dates": _dates(ev.date_added, ev.acquisition_date, ev.start_date, ev.end_date),
            "numbers": {ev.id} | ({ev.file_size} if ev.file_size else set()),
        }

    counts = {
        "notes": len(record["notes"]), "events": len(record["events"]), "tasks": len(record["tasks"]),
        "assets": len(record["assets"]), "iocs": len(record["iocs"]), "evidence": len(record["evidence"]),
    }
    allowed = {str(v) for v in counts.values()} | {str(v) for v in class_counts.values()} | {str(case_id)}
    record["allowed_numbers"]["*"] = allowed
    record["counts"] = counts
    record["task_class_counts"] = class_counts
    return record


def _set_evidence_allowed(record: dict[str, Any], integrity: dict[str, Any]) -> None:
    record["allowed_numbers"]["evidence"] = {str(v) for v in (integrity or {}).values()}


# ----- Hashing + caching ----------------------------------------------------


def _hashable_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy of the writer payload with wall-clock-derived activity fields
    removed, so the cache key is stable across calls when nothing actually
    changed. Keeps the absolute `at` timestamps (which only move on real
    activity) and drops `now_utc` + every `hours_*` delta (recomputed each run).
    """
    p = dict(payload)
    activity = p.get("activity")
    if isinstance(activity, dict):
        # The audit-log timestamp (and the overall last_activity_at it feeds)
        # moves on ANY tracked action - answering a review question, a comment
        # - none of which changes the summary's inputs; every real object
        # change reaches the hash through the payload content and the per-type
        # `at` values. Keeping it made a plain Generate re-run the writer right
        # after an answers pass (2026-10-09).
        a = {k: v for k, v in activity.items()
             if k not in ("now_utc", "hours_since_last_activity", "last_activity_at")}
        per_type = a.get("per_type_last_activity")
        if isinstance(per_type, dict):
            a["per_type_last_activity"] = {
                k: ({"at": v.get("at")} if isinstance(v, dict) else v)
                for k, v in per_type.items() if k != "audit_log"
            }
        p["activity"] = a
    return p


def _hash_inputs(*parts: Any) -> str:
    """Stable hash of arbitrary inputs (each gets JSON-serialized first)."""
    h = hashlib.md5()
    for p in parts:
        if isinstance(p, str):
            h.update(p.encode("utf-8"))
        else:
            h.update(json.dumps(p, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _find_artifact(case_id: int, kind: str, input_hash: str) -> CaseAiArtifact | None:
    return (
        CaseAiArtifact.query
        .filter(
            CaseAiArtifact.case_id == case_id,
            CaseAiArtifact.kind == kind,
            CaseAiArtifact.input_hash == input_hash
        )
        .order_by(CaseAiArtifact.generated_at.desc(), CaseAiArtifact.id.desc())
        .first()
    )


def get_cached_summary(case_id: int) -> CaseAiArtifact | None:
    """Latest stored final summary for the case, regardless of input hash.
    The id tie-break matters now: a revise pass lands within the same second
    as pass 1 and must win."""
    return (
        CaseAiArtifact.query
        .filter(
            CaseAiArtifact.case_id == case_id,
            CaseAiArtifact.kind == CASE_SUMMARY_KIND
        )
        .order_by(CaseAiArtifact.generated_at.desc(), CaseAiArtifact.id.desc())
        .first()
    )


def find_cache_hit(case_id: int, input_hash: str) -> CaseAiArtifact | None:
    """Backward-compat alias for the v1 cache lookup."""
    return _find_artifact(case_id, CASE_SUMMARY_KIND, input_hash)


# ----- Analyst manual override ---------------------------------------------


def case_last_activity_at(case_id: int) -> datetime | None:
    """Most recent 'touch' across every case object type, as naive UTC."""
    activity = _build_activity_payload(case_id)
    raw = activity.get("last_activity_at")
    if not raw:
        return None
    return datetime.fromisoformat(raw.rstrip("Z"))


def summary_edit_is_stale(artifact: CaseAiArtifact) -> bool:
    """True when case data was touched after the manual edit was saved."""
    if not artifact.is_edited or artifact.edited_at is None:
        return False
    last = case_last_activity_at(artifact.case_id)
    return last is not None and last > artifact.edited_at


def _notify_case_update(case_id: int, what: str) -> None:
    """Fire ``on_postload_case_update`` for the case (iris-ng #138), AFTER the
    commit and fail-soft; only when the displayed text actually changed."""
    case = Cases.query.filter(Cases.case_id == case_id).first()
    if case is None:
        return
    try:
        call_modules_hook('on_postload_case_update', data=case, caseid=case_id)
    except Exception:
        app.logger.exception(
            f"Case #{case_id}: on_postload_case_update after executive summary {what} failed"
        )


def save_summary_edit(case_id: int, content: str, user_id: int) -> CaseAiArtifact:
    """Store an analyst correction on the case's latest summary artifact.
    The original model output stays in `content` so the edit is reversible."""
    artifact = get_cached_summary(case_id)
    if artifact is None:
        raise CaseSummaryError(
            f"Case #{case_id} has no generated summary to edit — generate one first"
        )

    text = (content or "").strip()
    if not text:
        raise CaseSummaryError("Edited summary cannot be empty")

    previous_display = artifact.display_content
    artifact.edited_content = text
    artifact.edited_by_id = user_id
    artifact.edited_at = datetime.utcnow()
    db.session.commit()

    app.logger.info(
        f"Case #{case_id}: summary manually edited by user {user_id} "
        f"(artifact_id={artifact.id}, len={len(text)} chars)"
    )
    if text != previous_display:
        _notify_case_update(case_id, 'edit')
    return artifact


def revert_summary_edit(case_id: int) -> CaseAiArtifact:
    """Drop the analyst override, restoring the original model output."""
    artifact = get_cached_summary(case_id)
    if artifact is None:
        raise CaseSummaryError(f"Case #{case_id} has no summary")

    if not artifact.is_edited:
        return artifact

    previous_display = artifact.display_content
    artifact.edited_content = None
    artifact.edited_by_id = None
    artifact.edited_at = None
    db.session.commit()

    app.logger.info(
        f"Case #{case_id}: summary edit reverted to AI original "
        f"(artifact_id={artifact.id})"
    )
    if artifact.display_content != previous_display:
        _notify_case_update(case_id, 'revert')
    return artifact


# ----- Per-domain specialist call ------------------------------------------


def _validate_specialist(domain: str, parsed: Any, payload: dict[str, Any]) -> None:
    """The contract shape and: every id the specialist names is one it was
    given. Raises CaseSummaryError -- the domain then counts as failed and
    nothing is persisted (a refusal, prose or an invented id never becomes a
    cached specialist row)."""
    cfg = DOMAIN_CONFIG[domain]
    if not isinstance(parsed, dict) or not isinstance(parsed.get("summary"), str):
        raise CaseSummaryError(f"Domain '{domain}' specialist reply is not the contract (no summary)")
    if domain == "timeline":
        events = parsed.get("key_events")
        if not isinstance(events, list) or any(
                not isinstance(e, dict) or not isinstance(e.get("event_id"), int) or isinstance(e.get("event_id"), bool)
                or not isinstance(e.get("date"), str) or not isinstance(e.get("description"), str) for e in events):
            raise CaseSummaryError("Domain 'timeline' specialist reply is not the contract (key_events)")
    elif domain == "assets":
        rows = parsed.get("asset_status")
        if not isinstance(rows, list) or any(
                not isinstance(r, dict) or not isinstance(r.get("asset_id"), int) or isinstance(r.get("asset_id"), bool)
                or r.get("status") not in _ASSET_STATUS_VALUES for r in rows):
            raise CaseSummaryError("Domain 'assets' specialist reply is not the contract (asset_status)")
    elif domain == "evidence":
        if not isinstance(parsed.get("coverage"), list) or not isinstance(parsed.get("integrity_notes"), list):
            raise CaseSummaryError("Domain 'evidence' specialist reply is not the contract (coverage)")
    known = {row[cfg["id_key"]] for row in payload.get(_DOMAIN_LIST_KEY[domain], [])}
    for ref_type, ids in specialist_ids(parsed).items():
        if not ids:
            continue
        if ref_type != cfg["ref_type"]:
            raise CaseSummaryError(
                f"Domain '{domain}' specialist cited {ref_type} ids it was not given: {sorted(ids)[:5]}")
        unknown = ids - known
        if unknown:
            raise CaseSummaryError(
                f"Domain '{domain}' specialist cited unknown {ref_type} id(s): {sorted(unknown)[:5]}")


def _call_domain_specialist(
    *, case_id: int, domain: str, payload: dict[str, Any], force: bool
) -> tuple[CaseAiArtifact | None, dict[str, Any]]:
    """Run one specialist or return its cached row, plus the audit step.
    Model trouble (transport, contract, invented ids) returns (None, failed
    step) so the writer can proceed without that domain; only a missing
    backend raises."""
    cfg = DOMAIN_CONFIG[domain]
    system_prompt = _load_prompt(cfg["prompt_file"])
    started = datetime.utcnow()
    step_name = f"specialist:{domain}"

    client = build_default_client(timeout=600.0, default_max_tokens=SPECIALIST_MAX_TOKENS, feature='case_summary')
    if client is None:
        raise CaseSummaryError(
            "AI backend is not configured (set AI_BACKEND_URL and AI_BACKEND_MODEL)"
        )

    input_hash = _hash_inputs(client.model, system_prompt, payload)

    if not force:
        cached = _find_artifact(case_id, cfg["kind"], input_hash)
        if cached is not None:
            app.logger.info(
                f"Case #{case_id}: domain '{domain}' cache hit (artifact_id={cached.id})"
            )
            # The stored row knows its model and prompt, not the backend row
            # that produced it: provider / backend stay None on a cache hit.
            return cached, step_record(step_name, None, cached.prompt_id, started, artifact_id=cached.id,
                                       cached=True, model=cached.model)

    user_prompt = (
        f"Summarize the {domain} for this case using the data below.\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
    )

    app.logger.info(
        f"Case #{case_id}: domain '{domain}' specialist call "
        f"(model={client.model}, prompt={cfg['prompt_id']})"
    )

    try:
        reply = ask_json(
            client,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=SPECIALIST_MAX_TOKENS,
            compact_suffix=SPECIALIST_COMPACT_SUFFIX,
            parse=parse_json_object,
            log=app.logger,
            label=f"case #{case_id} {domain} specialist",
        )
    except AIClientError as exc:
        err = f"Domain '{domain}' specialist call failed: {exc}"
        return None, step_record(step_name, client, cfg["prompt_id"], started, outcome="failed", error=err)

    if reply.parsed is None:
        err = (f"Domain '{domain}' specialist did not return JSON"
               + truncation_hint("Case Summary", reply)
               + f" (finish_reason={reply.finish})")
        return None, step_record(step_name, client, cfg["prompt_id"], started, outcome="failed", error=err,
                                 usage=reply.response.get("usage"))
    try:
        _validate_specialist(domain, reply.parsed, payload)
    except CaseSummaryError as exc:
        return None, step_record(step_name, client, cfg["prompt_id"], started, outcome="failed", error=str(exc),
                                 usage=reply.response.get("usage"))

    content = json.dumps(reply.parsed, ensure_ascii=False)
    artifact = CaseAiArtifact(
        case_id=case_id,
        kind=cfg["kind"],
        prompt_id=cfg["prompt_id"],
        model=client.model,
        input_hash=input_hash,
        content=content,
        confidence=None
    )
    db.session.add(artifact)
    db.session.commit()

    app.logger.info(
        f"Case #{case_id}: domain '{domain}' specialist persisted "
        f"(artifact_id={artifact.id}, len={len(content)} chars)"
    )
    return artifact, step_record(step_name, client, cfg["prompt_id"], started, artifact_id=artifact.id,
                                 usage=reply.response.get("usage"))


def _parse_specialist_content(domain: str, artifact: CaseAiArtifact | None) -> Any:
    """Convert a stored specialist artifact into the value the writer expects:
    the whole JSON for structured domains (timeline, assets, evidence), the
    `summary` bullets for the others. A legacy Markdown row passes through as
    text. Empty/missing returns None."""
    if artifact is None:
        return None
    cfg = DOMAIN_CONFIG[domain]
    raw = (artifact.content or "").strip()
    if not raw:
        return None
    try:
        parsed = parse_json_object(raw)
    except (ValueError, TypeError):
        app.logger.warning(
            f"Case '{domain}' specialist row is not JSON (artifact_id={artifact.id}); passing raw text"
        )
        return raw
    if not cfg["structured"]:
        return parsed.get("summary") if isinstance(parsed.get("summary"), str) else raw
    return parsed


# ----- Public API: backward-compatible payload -----------------------------


def build_case_payload(case: Cases) -> dict[str, Any]:
    """The single-pass payload case_chat.py and the task suggester build
    their context off. Objects carry their ids since the verified pipeline."""
    case_id = case.case_id
    notes_p, _ = _build_notes_payload(case_id)
    timeline_p, _ = _build_timeline_payload(case_id)
    iocs_p, _ = _build_iocs_payload(case_id)
    assets_p, _ = _build_assets_payload(case_id)
    tasks = _build_tasks_payload(case_id)
    evidence_p, _ = _build_evidence_payload(case_id)
    return {
        "case": {
            "id": case.case_id,
            "name": case.name,
            "soc_id": case.soc_id,
            "open_date": case.open_date.isoformat() if case.open_date else None,
            "description": _truncate(case.description, 2000),
        },
        "counts": {
            "assets": len(assets_p["assets"]),
            "iocs": len(iocs_p["iocs"]),
            "timeline_events": len(timeline_p["timeline"]),
            "timeline_events_excluded_by_analyst": timeline_p["events_excluded_by_analyst"],
            "tasks": len(tasks),
            "notes": len(notes_p["notes"]),
            "evidence": len(evidence_p["evidence"]),
        },
        "assets": assets_p["assets"],
        "iocs": iocs_p["iocs"],
        "timeline": timeline_p["timeline"],
        "tasks": tasks,
        "notes": notes_p["notes"],
        "evidence": evidence_p["evidence"],
    }


def compute_input_hash(payload: dict[str, Any], system_prompt: str, model: str) -> str:
    """Backward-compat hasher matching the v1 signature."""
    return _hash_inputs(model, system_prompt, payload)


# ----- Writer ---------------------------------------------------------------


def classification_for(case: Cases, iocs: list[dict[str, Any]]) -> str:
    """TLP label: a RED indicator makes the whole summary RED; otherwise a
    case tag or a `tlp:` token in the description, else the highest IOC TLP,
    else AMBER. Server-derived so no model decides the classification."""
    ioc_best = None
    for i in iocs or []:
        name = (i.get("tlp") or "").strip().lower()
        if name in _TLP_RANK and (ioc_best is None or _TLP_RANK[name] > _TLP_RANK[ioc_best]):
            ioc_best = name
    if ioc_best == "red":
        return "TLP:RED"
    case_level = None
    for t in (getattr(case, "tags", None) or []):
        m = _TLP_RE.match((getattr(t, "tag_title", "") or "").strip())
        if m:
            name = m.group(1).lower()
            if case_level is None or _TLP_RANK[name] > _TLP_RANK[case_level]:
                case_level = name
    if case_level is None:
        m = _TLP_RE.search(case.description or "")
        if m:
            case_level = m.group(1).lower()
    label = case_level or ioc_best or "amber"
    return "TLP:" + label.upper()


def _object_index(notes_p, timeline_p, iocs_p, assets_p, tasks, evidence_p) -> dict[str, list[dict[str, Any]]]:
    return {
        "notes": [{"id": n["note_id"], "title": n["title"]} for n in notes_p["notes"]],
        "events": [{"id": e["event_id"], "date": e["event_time"], "title": e["title"]} for e in timeline_p["timeline"]],
        "tasks": [{"id": t["task_id"], "title": t["title"], "status": t["status"]} for t in tasks],
        "assets": [{"id": a["asset_id"], "name": a["name"]} for a in assets_p["assets"]],
        "iocs": [{"id": i["ioc_id"], "type": i["type"], "value": i["value"]} for i in iocs_p["iocs"]],
        "evidence": [{"id": e["evidence_id"], "filename": e["filename"]} for e in evidence_p["evidence"]],
    }


def _coerce_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def validate_claims(parsed: Any, *, is_closed: bool) -> tuple[list[dict[str, Any]], str, list[Flag]]:
    """The writer's reply -> (claims, status, low flags). Contract failures
    (not an object, no claims list, zero claims, more than MAX_CLAIMS) raise
    CaseSummaryError and nothing is persisted. Per-item problems are
    coerced and reported as LOW flags; a ref to an object that does not
    exist is KEPT so the checks flag it HIGH and the revise pass can fix it.
    Ids are renumbered c1..cN."""
    if not isinstance(parsed, dict):
        raise CaseSummaryError("Writer reply is not a JSON object")
    raw_claims = parsed.get("claims")
    if not isinstance(raw_claims, list):
        raise CaseSummaryError("Writer reply carries no claims list")
    if len(raw_claims) == 0:
        raise CaseSummaryError("Writer returned zero claims for a case with enough data to brief on")
    if len(raw_claims) > MAX_CLAIMS:
        raise CaseSummaryError(f"Writer returned {len(raw_claims)} claims; the limit is {MAX_CLAIMS}")

    flags: list[Flag] = []
    status = str(parsed.get("status") or "").strip().lower()
    if status not in ("critical", "high", "medium", "low"):
        flags.append(make_flag("STATUS_MISSING", None,
                               f"The writer gave no valid status ({parsed.get('status')!r}); rendered as medium",
                               detail={"status": parsed.get("status")}))
        status = "medium"

    claims: list[dict[str, Any]] = []
    for pos, raw in enumerate(raw_claims, start=1):
        given_id = raw.get("id") if isinstance(raw, dict) else None
        label = f"claim {given_id or pos}"
        if not isinstance(raw, dict):
            flags.append(make_flag("CLAIM_DROPPED", None, f"{label} is not an object", detail={"raw": str(raw)[:200]}))
            continue
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            flags.append(make_flag("CLAIM_DROPPED", None, f"{label} has no text", detail={"id": given_id}))
            continue
        text = " ".join(text.split())
        if len(text) > MAX_CLAIM_CHARS:
            text = text[:MAX_CLAIM_CHARS] + " […]"
        section = str(raw.get("section") or "").strip().lower()
        if section not in SECTIONS:
            flags.append(make_flag("CLAIM_DROPPED", None, f"{label} names an unknown section {raw.get('section')!r}",
                                   detail={"id": given_id, "section": raw.get("section"), "text": text}))
            continue
        if section == "lessons" and not is_closed:
            flags.append(make_flag("CLAIM_DROPPED", None, f"{label} is a lessons-learned claim on an open case",
                                   detail={"id": given_id, "text": text}))
            continue
        tier = str(raw.get("tier") or "").strip().lower()
        new_id = f"c{len(claims) + 1}"
        if tier not in TIERS:
            flags.append(make_flag("TIER_COERCED", new_id,
                                   f"Tier {raw.get('tier')!r} is not one of {', '.join(TIERS)}; read as unverified",
                                   detail={"tier": raw.get("tier")}))
            tier = "unverified"
        refs: list[dict[str, Any]] = []
        raw_refs = raw.get("source_refs")
        if raw_refs is None:
            raw_refs = []
        if not isinstance(raw_refs, list):
            flags.append(make_flag("REF_DROPPED", new_id, "source_refs is not a list; read as none",
                                   detail={"source_refs": str(raw_refs)[:200]}))
            raw_refs = []
        seen = set()
        for r in raw_refs:
            rt = str(r.get("type") or "").strip().lower() if isinstance(r, dict) else None
            rid = _coerce_int(r.get("id")) if isinstance(r, dict) else None
            if rt not in REF_TYPES or rid is None:
                flags.append(make_flag("REF_DROPPED", new_id, f"A source ref is malformed: {str(r)[:120]}",
                                       detail={"ref": str(r)[:200]}))
                continue
            if (rt, rid) in seen:
                continue
            seen.add((rt, rid))
            refs.append({"type": rt, "id": rid})
        claim = {"id": new_id, "section": section, "text": text, "tier": tier, "source_refs": refs}
        if section == "timeline":
            et = raw.get("event_time")
            et = str(et).strip() if et is not None else ""
            m = _EVENT_TIME_RE.match(et)
            claim["event_time"] = f"{m.group(1)} {m.group(2)}" if m else et
        claims.append(claim)
    if not claims:
        raise CaseSummaryError("Writer returned no usable claim")
    return claims, status, flags


def _writer_messages(payload: dict[str, Any], *, previous_claims=None, flags=None) -> list[dict[str, str]]:
    system_prompt = _load_prompt("case_summary_writer.md")
    if previous_claims is None:
        user = (
            "Write the sourced claims for this case's executive briefing from the inputs below.\n\n"
            f"```json\n{json.dumps(payload, indent=2, default=str, ensure_ascii=False)}\n```"
        )
    else:
        body = {
            "inputs": payload,
            "previous_claims": previous_claims,
            "flags": [{"claim_id": f.get("claim_id"), "code": f.get("code"), "severity": f.get("severity"),
                       "message": f.get("message")} for f in (flags or [])],
        }
        user = (
            "REVISION MODE. Your previous claims and the flags raised against them follow the inputs. "
            "Return the complete corrected claim list: fix or drop every flagged claim, lower overstated "
            "tiers, cite only ids from object_index, add no new facts.\n\n"
            f"```json\n{json.dumps(body, indent=2, default=str, ensure_ascii=False)}\n```"
        )
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user}]


def _call_writer(client, writer_model: str, payload: dict[str, Any], *, case_id: int, pass_no: int,
                 previous_claims=None, flags=None) -> tuple[dict[str, Any], JsonReply, datetime]:
    started = datetime.utcnow()
    app.logger.info(
        f"Case #{case_id}: writer pass {pass_no} (model={writer_model}, prompt={CASE_SUMMARY_PROMPT_ID}"
        f"{f', configured={client.model}' if writer_model != client.model else ''})"
    )
    try:
        reply = ask_json(
            client,
            _writer_messages(payload, previous_claims=previous_claims, flags=flags),
            max_tokens=WRITER_MAX_TOKENS,
            compact_suffix=WRITER_COMPACT_SUFFIX,
            parse=parse_json_object,
            log=app.logger,
            label=f"case #{case_id} summary writer pass {pass_no}",
            model=writer_model,
        )
    except AIClientError as exc:
        raise CaseSummaryError(f"Writer call failed: {exc}") from exc
    if reply.parsed is None:
        raise CaseSummaryError(
            "Writer did not return the claims contract" + truncation_hint("Case Summary writer", reply)
            + f" (finish_reason={reply.finish})")
    return reply.parsed, reply, started


# ----- Rendering meta, flags, persistence ----------------------------------


def _render_meta(*, status: str, counts: dict[str, Any], activity: dict[str, Any], tasks: list[dict[str, Any]],
                 assets: list[dict[str, Any]], integrity: dict[str, Any], now: datetime) -> dict[str, Any]:
    unassigned = [t["title"] or f"task #{t['task_id']}" for t in tasks
                  if t["status_class"] != "closed" and not t["has_assignee"]]
    overdue = []
    for t in tasks:
        if t["status_class"] == "closed" or not t.get("open_date"):
            continue
        try:
            opened = datetime.fromisoformat(t["open_date"])
        except ValueError:
            continue
        if now - opened > timedelta(days=OVERDUE_DAYS):
            overdue.append(t["title"] or f"task #{t['task_id']}")
    rows = []
    for a in assets:
        cs = a.get("compromise_status")
        label = ("Confirmed compromised" if cs == "compromised"
                 else "Not compromised" if cs == "not_compromised" else "Under investigation")
        rows.append({"asset_id": a["asset_id"], "name": a["name"], "type": a["type"], "status": label})
    return {
        "status": status,
        "counts": counts,
        "activity": activity,
        "task_flags": {"unassigned": unassigned, "overdue": overdue, "overdue_days": OVERDUE_DAYS},
        "assets": rows,
        "evidence_integrity": integrity,
    }


def _dedupe_flags(flags: list[Flag]) -> list[Flag]:
    """One flag per (claim_id, code); the first wins, and the callers order
    them validation -> checks -> verifier so the deterministic result wins."""
    seen = set()
    out: list[Flag] = []
    for f in flags:
        key = (f.claim_id, f.code)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def _needs_revise(flags: list[Flag]) -> bool:
    """Any HIGH flag the writer can act on. The pipeline's own flags (verifier
    unavailable / failed) are not the writer's to fix."""
    return any(f.severity == "high" and f.source != "pipeline" for f in flags)


def _persist_pass(*, case_id: int, markdown: str, input_hash: str, writer_model: str, claims: list[dict[str, Any]],
                  meta: dict[str, Any], checks_flags: list[Flag], verifier_status: str, verifier_raw: dict,
                  flags: list[Flag], steps: list[dict[str, Any]], pass_no: int, pass_kind: str,
                  parent_run_id: int | None, answers: dict[str, Any] | None = None) -> tuple[CaseAiArtifact, CaseSummaryRun]:
    """ONE transaction for the artifact, the run, its steps and its flags: a
    crashed worker leaves nothing half-written."""
    artifact = CaseAiArtifact(
        case_id=case_id,
        kind=CASE_SUMMARY_KIND,
        prompt_id=CASE_SUMMARY_PROMPT_ID,
        model=writer_model,
        input_hash=input_hash,
        content=markdown,
        confidence=None
    )
    db.session.add(artifact)
    db.session.flush()
    run = CaseSummaryRun(
        case_id=case_id,
        artifact_id=artifact.id,
        pass_no=pass_no,
        pass_kind=pass_kind,
        parent_run_id=parent_run_id,
        input_hash=input_hash,
        pipeline_version=PIPELINE_VERSION,
        claims_json=json.dumps(claims, ensure_ascii=False),
        writer_meta_json=json.dumps(meta, default=str, ensure_ascii=False),
        checks_json=json.dumps({"version": CHECKS_VERSION, "flags": [f.to_dict() for f in checks_flags]},
                               default=str, ensure_ascii=False),
        verifier_status=verifier_status,
        verifier_json=json.dumps(verifier_raw, default=str, ensure_ascii=False),
        answers_json=json.dumps(answers, default=str, ensure_ascii=False) if answers is not None else None,
    )
    db.session.add(run)
    db.session.flush()
    for s in steps:
        db.session.add(CaseSummaryStep(run_id=run.id, **s))
    for f in flags:
        db.session.add(CaseSummaryFlag(
            run_id=run.id, claim_id=f.claim_id, code=f.code, severity=f.severity, source=f.source,
            message=f.message, detail_json=json.dumps(f.detail, default=str) if f.detail is not None else None,
            source_refs_json=json.dumps(f.source_refs, default=str)))
    db.session.commit()
    return artifact, run


def _run_pass(*, case_id: int, case: Cases, client, writer_model: str, payload: dict[str, Any], record: dict[str, Any],
              input_hash: str, counts: dict[str, Any], tasks: list[dict[str, Any]], assets: list[dict[str, Any]],
              integrity: dict[str, Any], specialist_steps: list[dict[str, Any]], pass_no: int,
              prior: tuple[CaseSummaryRun, list[dict[str, Any]], list[Flag]] | None = None
              ) -> tuple[CaseAiArtifact, CaseSummaryRun, list[dict[str, Any]], list[Flag]]:
    """Writer -> validate -> render -> checks -> verifier -> one commit."""
    is_closed = bool(case.close_date)
    previous_claims = prior[1] if prior else None
    prior_flags = [f.to_dict() for f in prior[2] if f.severity in ("high", "medium")] if prior else None
    parsed, reply, writer_started = _call_writer(client, writer_model, payload, case_id=case_id, pass_no=pass_no,
                                                 previous_claims=previous_claims, flags=prior_flags)
    claims, status, low_flags = validate_claims(parsed, is_closed=is_closed)
    writer_step = step_record("writer", client, CASE_SUMMARY_PROMPT_ID, writer_started, model=writer_model,
                              usage=reply.response.get("usage"))

    now = datetime.utcnow()
    meta = _render_meta(status=status, counts=counts, activity=payload["activity"], tasks=tasks, assets=assets,
                        integrity=integrity, now=now)
    markdown = render_claims_markdown(
        {"name": case.name, "classification": payload["classification"], "generated_on": now.strftime("%Y-%m-%d"),
         "is_closed": is_closed},
        claims, meta)

    checks_started = datetime.utcnow()
    checks_flags = run_checks(claims, record)
    checks_step = step_record("checks", None, CHECKS_VERSION, checks_started)

    verifier_result = summary_verifier.verify_summary(claims, record, status=status, is_closed=is_closed,
                                                      label=f"case #{case_id} pass {pass_no}")

    flags = _dedupe_flags(low_flags + checks_flags + verifier_result.flags)
    steps = list(specialist_steps) + [writer_step, checks_step] + verifier_result.steps
    meta_stored = {**meta, "claims_count": len(claims), "pass_no": pass_no, "retried": reply.retried,
                   "finish_reason": reply.finish}
    artifact, run = _persist_pass(
        case_id=case_id, markdown=markdown, input_hash=input_hash, writer_model=writer_model, claims=claims,
        meta=meta_stored, checks_flags=checks_flags, verifier_status=verifier_result.status,
        verifier_raw=verifier_result.raw, flags=flags, steps=steps, pass_no=pass_no,
        pass_kind="revise" if prior else "draft", parent_run_id=prior[0].id if prior else None)
    app.logger.info(
        f"Case #{case_id}: summary pass {pass_no} persisted (artifact_id={artifact.id}, run_id={run.id}, "
        f"claims={len(claims)}, flags={len(flags)} "
        f"[high={sum(1 for f in flags if f.severity == 'high')}], verifier={verifier_result.status}, "
        f"usage={reply.response.get('usage')})"
    )
    return artifact, run, claims, flags


def _persist_sparse(*, case_id: int, markdown: str, input_hash: str, writer_model: str,
                    counts: dict[str, Any]) -> CaseAiArtifact:
    started = datetime.utcnow()
    steps = [step_record(name, None, pid, started, outcome="skipped", error="sparse case")
             for name, pid in (("writer", CASE_SUMMARY_PROMPT_ID), ("checks", CHECKS_VERSION),
                               ("verifier:claims", summary_verifier.VERIFIER_CLAIMS_PROMPT_ID),
                               ("verifier:document", summary_verifier.VERIFIER_DOCUMENT_PROMPT_ID))]
    artifact, _ = _persist_pass(
        case_id=case_id, markdown=markdown, input_hash=input_hash, writer_model=writer_model, claims=[],
        meta={"sparse": True, "counts": counts}, checks_flags=[], verifier_status="skipped", verifier_raw={},
        flags=[], steps=steps, pass_no=1, pass_kind="draft", parent_run_id=None)
    return artifact


# ----- Review questions + the answers pass ----------------------------------


def _latest_run(case_id: int) -> tuple[CaseAiArtifact | None, CaseSummaryRun | None]:
    artifact = get_cached_summary(case_id)
    if artifact is None:
        return None, None
    return artifact, CaseSummaryRun.query.filter(CaseSummaryRun.artifact_id == artifact.id).first()


def _attach_questions(run_id: int, claims: list[dict[str, Any]], record: dict[str, Any], *, label: str) -> None:
    """Ask the review question for every open flag of a run that has none yet
    (one batched call on the verifier role, fallback options without it) and
    store question + options on the flag rows plus a 'questions' step. Runs
    AFTER the pass is committed: the pass stands whatever happens here."""
    run = db.session.get(CaseSummaryRun, run_id)
    if run is None:
        return
    flags = [f for f in run.flags if f.status == "open" and f.question is None]
    if not flags:
        return
    flag_dicts = [{"id": f.id, "code": f.code, "severity": f.severity, "message": f.message, "claim_id": f.claim_id,
                   "detail": json.loads(f.detail_json) if f.detail_json else None} for f in flags]
    result = summary_questions.build_questions(flag_dicts, claims, record, label=label)
    for f in flags:
        q = result.questions.get(f.id)
        if q is None:
            continue
        f.question = q["question"]
        f.options_json = json.dumps(q["options"], ensure_ascii=False)
    for s in result.steps:
        db.session.add(CaseSummaryStep(run_id=run.id, **s))
    db.session.commit()
    app.logger.info(f"{label}: {len(flags)} review question(s) attached to run {run.id} ({result.status})")


ANSWERS_COMPACT_SUFFIX = (
    "\n\nYour previous reply was cut off by the output limit before the JSON closed. "
    "Answer NOW with the JSON object only: just the instructed claims, one short sentence each."
)


def _call_writer_answers(client, writer_model: str, *, case_id: int, claims: list[dict[str, Any]],
                         instructions: list[dict[str, Any]], object_index: dict[str, Any]) -> tuple[dict, JsonReply, datetime]:
    started = datetime.utcnow()
    body = {
        "claims": claims,
        "instructions": [{"claim_id": i.get("claim_id"), "instruction": i.get("text"), "flag_message": i.get("flag_message")}
                         for i in instructions],
        "object_index": object_index,
    }
    user = ("ANSWERS MODE. The analyst answered the review questions; apply the free-text instructions below to the "
            "named claims only and return just those claims.\n\n"
            f"```json\n{json.dumps(body, indent=2, default=str, ensure_ascii=False)}\n```")
    app.logger.info(f"Case #{case_id}: writer answers pass ({len(instructions)} instruction(s), model={writer_model})")
    try:
        reply = ask_json(client, [{"role": "system", "content": _load_prompt("case_summary_writer.md")},
                                  {"role": "user", "content": user}],
                         max_tokens=WRITER_MAX_TOKENS, compact_suffix=ANSWERS_COMPACT_SUFFIX, parse=parse_json_object,
                         log=app.logger, label=f"case #{case_id} summary writer answers", model=writer_model)
    except AIClientError as exc:
        raise CaseSummaryError(f"Writer call failed: {exc}") from exc
    if reply.parsed is None or not isinstance(reply.parsed.get("claims"), list):
        raise CaseSummaryError("Writer did not return the answers contract" + truncation_hint("Case Summary writer", reply)
                               + f" (finish_reason={reply.finish})")
    return reply.parsed, reply, started


def _merge_answer_claims(claims: list[dict[str, Any]], parsed: dict[str, Any], instructions: list[dict[str, Any]],
                         *, is_closed: bool) -> tuple[list[dict[str, Any]], list[Flag], list[str]]:
    """Fold the writer's answers-mode reply into the claim list: only the
    instructed ids may change; a returned claim is validated like any other
    (its id restored afterwards); `drop: true` removes it; an instructed claim
    the writer did not return stays as it was (logged)."""
    allowed = {i.get("claim_id") for i in instructions if i.get("claim_id")}
    by_id = {c["id"]: c for c in claims}
    order = [c["id"] for c in claims]
    low_flags: list[Flag] = []
    notes: list[str] = []
    seen: set[str] = set()
    for raw in parsed.get("claims") or []:
        if not isinstance(raw, dict):
            continue
        cid = str(raw.get("id") or "").strip()
        if cid not in allowed or cid not in by_id:
            notes.append(f"writer returned {cid or '?'}, not an instructed claim; ignored")
            continue
        seen.add(cid)
        if raw.get("drop") is True:
            by_id.pop(cid)
            order.remove(cid)
            notes.append(f"{cid} dropped by the writer on the analyst's instruction")
            continue
        try:
            validated, _, flags = validate_claims({"status": "medium", "claims": [raw]}, is_closed=is_closed)
        except CaseSummaryError as exc:
            notes.append(f"{cid}: the writer's version was not usable ({exc}); kept as it was")
            continue
        new = validated[0]
        new["id"] = cid
        by_id[cid] = new
        for f in flags:
            f.claim_id = cid
        low_flags.extend(f for f in flags if f.code != "STATUS_MISSING")
    for cid in allowed - seen:
        notes.append(f"{cid}: the writer returned no version; kept as it was")
    return [by_id[i] for i in order if i in by_id], low_flags, notes


def apply_answers_pass(case_id: int, *, user_id: int | None = None) -> CaseAiArtifact:
    """The answers pass: every question of the newest run answered -> apply
    the structured answers in code, call the writer for the free-text ones,
    re-render, rerun the deterministic checks (a flag the analyst kept is
    not asked again), persist a new run (`pass_kind` answers, parent = the
    run that asked) and attach the questions for whatever is new. Refuses
    while a question is unanswered or when every answer keeps the text."""
    case = Cases.query.filter(Cases.case_id == case_id).first()
    if case is None:
        raise CaseSummaryError(f"Case #{case_id} not found")
    artifact, run = _latest_run(case_id)
    if run is None:
        raise CaseSummaryError("This summary has no review questions to apply (regenerate it first)")
    open_flags = [f for f in run.flags if f.status == "open"]
    if open_flags:
        raise CaseSummaryError(f"{len(open_flags)} review question(s) are still unanswered")
    answered = [f for f in run.flags if f.status == "answered"]
    if not answered:
        raise CaseSummaryError("This summary has no answered questions to apply")
    claims = json.loads(run.claims_json or "[]")
    flag_dicts = [{"id": f.id, "code": f.code, "claim_id": f.claim_id, "message": f.message,
                   "answer": json.loads(f.answer_json) if f.answer_json else {}} for f in answered]
    applied = summary_questions.apply_answers(claims, flag_dicts)
    if not applied["instructions"] and all(ch.get("action") == "keep" or ch.get("skipped") for ch in applied["changes"]):
        raise CaseSummaryError("Every answer keeps the summary as written; there is nothing to apply")

    started = datetime.utcnow()
    is_closed = bool(case.close_date)
    notes_payload, _ = _build_notes_payload(case_id)
    timeline_payload, _ = _build_timeline_payload(case_id)
    iocs_payload, _ = _build_iocs_payload(case_id)
    assets_payload, _ = _build_assets_payload(case_id)
    evidence_payload, _ = _build_evidence_payload(case_id)
    tasks = _build_tasks_payload(case_id)
    counts = {"assets": len(assets_payload["assets"]), "iocs": len(iocs_payload["iocs"]),
              "timeline_events": len(timeline_payload["timeline"]), "tasks": len(tasks),
              "notes": len(notes_payload["notes"]), "evidence": len(evidence_payload["evidence"])}
    record = build_case_record(case_id)
    _set_evidence_allowed(record, evidence_payload["integrity"])

    new_claims = applied["claims"]
    steps: list[dict[str, Any]] = []
    writer_model = run.artifact.model if run.artifact else None
    merge_notes: list[str] = []
    low_flags: list[Flag] = []
    if applied["instructions"]:
        client = build_default_client(timeout=600.0, default_max_tokens=WRITER_MAX_TOKENS, feature='case_summary')
        if client is None:
            raise CaseSummaryError("AI backend is not configured (set AI_BACKEND_URL and AI_BACKEND_MODEL)")
        writer_model = _pick_synthesizer_model(client.model)
        parsed, reply, t0 = _call_writer_answers(
            client, writer_model, case_id=case_id, claims=new_claims, instructions=applied["instructions"],
            object_index=_object_index(notes_payload, timeline_payload, iocs_payload, assets_payload, tasks, evidence_payload))
        new_claims, low_flags, merge_notes = _merge_answer_claims(new_claims, parsed, applied["instructions"], is_closed=is_closed)
        steps.append(step_record("writer", client, CASE_SUMMARY_PROMPT_ID, t0, model=writer_model,
                                 usage=reply.response.get("usage")))
    steps.insert(0, step_record("apply", None, PIPELINE_VERSION, started))

    prev_meta = json.loads(run.writer_meta_json or "{}")
    status = str(prev_meta.get("status") or "medium")
    now = datetime.utcnow()
    meta = _render_meta(status=status, counts=counts, activity=_build_activity_payload(case_id), tasks=tasks,
                        assets=assets_payload["assets"], integrity=evidence_payload["integrity"], now=now)
    markdown = render_claims_markdown(
        {"name": case.name, "classification": classification_for(case, iocs_payload["iocs"]),
         "generated_on": now.strftime("%Y-%m-%d"), "is_closed": is_closed},
        new_claims, meta)

    checks_started = datetime.utcnow()
    checks_flags = [f for f in run_checks(new_claims, record) if (f.claim_id, f.code) not in applied["confirmed"]]
    steps.append(step_record("checks", None, CHECKS_VERSION, checks_started))
    flags = _dedupe_flags(low_flags + checks_flags)
    answers_log = {"changes": applied["changes"], "instructions": applied["instructions"], "dropped": applied["dropped"],
                   "writer_notes": merge_notes, "confirmed": sorted([list(x) for x in applied["confirmed"]]),
                   "applied_by": user_id}
    meta_stored = {**meta, "claims_count": len(new_claims), "pass_no": run.pass_no + 1, "answers_pass": True}
    artifact2, run2 = _persist_pass(
        case_id=case_id, markdown=markdown, input_hash=run.input_hash, writer_model=writer_model or "", claims=new_claims,
        meta=meta_stored, checks_flags=checks_flags, verifier_status="carried",
        verifier_raw={"carried_from_run": run.id}, flags=flags, steps=steps, pass_no=run.pass_no + 1,
        pass_kind="answers", parent_run_id=run.id, answers=answers_log)
    app.logger.info(
        f"Case #{case_id}: answers pass persisted (artifact_id={artifact2.id}, run_id={run2.id}, "
        f"claims={len(new_claims)}, new flags={len(flags)}, instructions={len(applied['instructions'])})")
    _attach_questions(run2.id, new_claims, record, label=f"case #{case_id} answers pass")
    _notify_case_update(case_id, 'generation')
    return artifact2


# ----- Orchestrator ---------------------------------------------------------


def generate_case_summary(case_id: int, *, force: bool = False) -> CaseAiArtifact:
    """Specialists -> writer -> checks -> verifier (-> one revise pass).

    Returns the final-stage artifact (kind=case_summary) of the newest pass.
    `force=True` invalidates every stage (specialists + writer); `False`
    serves the stored pass wherever the input hash matches, without
    re-verifying.
    """
    case = Cases.query.filter(Cases.case_id == case_id).first()
    if case is None:
        raise CaseSummaryError(f"Case #{case_id} not found")

    client = build_default_client(timeout=600.0, default_max_tokens=WRITER_MAX_TOKENS, feature='case_summary')
    if client is None:
        raise CaseSummaryError(
            "AI backend is not configured (set AI_BACKEND_URL and AI_BACKEND_MODEL)"
        )
    writer_model = _pick_synthesizer_model(client.model)
    writer_prompt = _load_prompt("case_summary_writer.md")

    # Build the 5 domain payloads once. Each is hashed independently so the
    # specialist cache hits when only one domain changed.
    notes_payload, notes_empty = _build_notes_payload(case_id)
    timeline_payload, timeline_empty = _build_timeline_payload(case_id)
    iocs_payload, iocs_empty = _build_iocs_payload(case_id)
    assets_payload, assets_empty = _build_assets_payload(case_id)
    evidence_payload, evidence_empty = _build_evidence_payload(case_id)
    tasks = _build_tasks_payload(case_id)

    counts = {
        "assets": len(assets_payload["assets"]),
        "iocs": len(iocs_payload["iocs"]),
        "timeline_events": len(timeline_payload["timeline"]),
        "tasks": len(tasks),
        "notes": len(notes_payload["notes"]),
        # Deliberately NOT part of the sparse-case test -- a pile of evidence
        # with no notes, timeline or IOCs is still too early to brief on.
        "evidence": len(evidence_payload["evidence"]),
    }

    app.logger.info(
        f"Case #{case_id}: starting verified summary "
        f"(model={client.model}, counts={counts}, force={force})"
    )

    # The sparse decision is the server's (it used to be the synthesizer's):
    # no specialist, writer or verifier call for a case too thin to brief on.
    if is_sparse(counts):
        markdown = render_sparse(counts)
        sparse_hash = _hash_inputs(PIPELINE_VERSION, "sparse", counts)
        if not force:
            cached = _find_artifact(case_id, CASE_SUMMARY_KIND, sparse_hash)
            if cached is not None:
                return cached
        artifact = _persist_sparse(case_id=case_id, markdown=markdown, input_hash=sparse_hash,
                                   writer_model=writer_model, counts=counts)
        _notify_case_update(case_id, 'generation')
        return artifact

    # Stage 1: domain specialists, in a small thread pool so cache hits
    # finish instantly and cache-miss waits overlap.
    domain_inputs = [
        ("notes",    notes_payload,    notes_empty),
        ("timeline", timeline_payload, timeline_empty),
        ("iocs",     iocs_payload,     iocs_empty),
        ("assets",   assets_payload,   assets_empty),
        ("evidence", evidence_payload, evidence_empty),
    ]
    artifacts: dict[str, CaseAiArtifact | None] = {}
    failures: dict[str, str] = {}
    specialist_steps: list[dict[str, Any]] = []

    def _runner(args):
        # Pool workers run in fresh threads with no Flask app context bound,
        # so push one explicitly. Return primitives (the artifact id, the step
        # dict), never ORM objects -- the worker's session ends with the
        # context.
        domain, payload, empty = args
        if empty:
            return domain, None, None, None
        with app.app_context():
            try:
                art, step = _call_domain_specialist(case_id=case_id, domain=domain, payload=payload, force=force)
                return domain, (art.id if art else None), step.get("error"), step
            except CaseSummaryError as exc:
                return domain, None, str(exc), None

    with ThreadPoolExecutor(max_workers=len(domain_inputs)) as pool:
        for domain, art_id, err, step in pool.map(_runner, domain_inputs):
            artifacts[domain] = db.session.get(CaseAiArtifact, art_id) if art_id is not None else None
            if err:
                failures[domain] = err
            if step is not None:
                specialist_steps.append(step)

    if failures:
        # Don't abort -- the writer can still produce a useful summary when
        # most domains succeeded. Abort only if every domain that had data
        # failed.
        app.logger.warning(
            f"Case #{case_id}: {len(failures)} domain specialist(s) failed: "
            + "; ".join(f"{k}: {v}" for k, v in failures.items())
        )
        attempted = sum(1 for _, _, empty in domain_inputs if not empty)
        if len(failures) == attempted:
            raise CaseSummaryError(
                "All domain specialists failed: "
                + "; ".join(f"{k}: {v}" for k, v in failures.items())
            )

    record = build_case_record(case_id)
    _set_evidence_allowed(record, evidence_payload["integrity"])

    payload = {
        "case": {
            "id": case.case_id,
            "name": case.name,
            "soc_id": case.soc_id,
            "open_date": case.open_date.isoformat() if case.open_date else None,
            "description": _truncate(case.description, 2000),
            "is_closed": bool(case.close_date),
        },
        "counts": counts,
        "activity": _build_activity_payload(case_id),
        "tasks": tasks,
        "notes_summary":    _parse_specialist_content("notes",    artifacts.get("notes")),
        "timeline_summary": _parse_specialist_content("timeline", artifacts.get("timeline")),
        "iocs_summary":     _parse_specialist_content("iocs",     artifacts.get("iocs")),
        "assets_summary":   _parse_specialist_content("assets",   artifacts.get("assets")),
        "evidence_summary": _parse_specialist_content("evidence", artifacts.get("evidence")),
        "evidence_integrity": evidence_payload["integrity"],
        "classification": classification_for(case, iocs_payload["iocs"]),
        "object_index": _object_index(notes_payload, timeline_payload, iocs_payload, assets_payload, tasks,
                                      evidence_payload),
    }

    # Cache key: the pipeline version, the writer model + prompt and the
    # payload without its wall-clock fields. Both passes share it; the
    # newest artifact with this hash is the pass to serve.
    input_hash = _hash_inputs(PIPELINE_VERSION, writer_model, writer_prompt, _hashable_payload(payload))

    if not force:
        cached = _find_artifact(case_id, CASE_SUMMARY_KIND, input_hash)
        if cached is not None:
            app.logger.info(
                f"Case #{case_id}: summary cache hit "
                f"(artifact_id={cached.id}, generated_at={cached.generated_at.isoformat()})"
            )
            return cached

    common = dict(case_id=case_id, case=case, client=client, writer_model=writer_model, payload=payload,
                  record=record, input_hash=input_hash, counts=counts, tasks=tasks,
                  assets=assets_payload["assets"], integrity=evidence_payload["integrity"],
                  specialist_steps=specialist_steps)
    artifact, run, claims, flags = _run_pass(pass_no=1, **common)

    if _needs_revise(flags):
        high = sum(1 for f in flags if f.severity == "high" and f.source != "pipeline")
        app.logger.info(f"Case #{case_id}: {high} high flag(s) after pass 1 -- running the revise pass")
        try:
            artifact, run, claims, flags = _run_pass(pass_no=2, prior=(run, claims, flags), **common)
        except CaseSummaryError as exc:
            # Pass 1 stands, with a medium flag + a failed writer step on it.
            db.session.rollback()
            app.logger.warning(f"Case #{case_id}: revise pass failed, keeping pass 1: {exc}")
            db.session.add(CaseSummaryStep(run_id=run.id, **step_record(
                "writer", client, CASE_SUMMARY_PROMPT_ID, datetime.utcnow(), outcome="failed", error=str(exc),
                model=writer_model)))
            f = make_flag("REVISE_FAILED", None,
                          f"The automatic revise pass did not complete; this is pass 1 as written: {exc}",
                          source="pipeline")
            db.session.add(CaseSummaryFlag(run_id=run.id, claim_id=None, code=f.code, severity=f.severity,
                                           source=f.source, message=f.message, detail_json=None,
                                           source_refs_json="[]"))
            db.session.commit()

    # Stage 5: every flag of the pass that stands becomes a review question.
    _attach_questions(run.id, claims, record, label=f"case #{case_id}")

    # A NEW final artifact changes what the card shows; a cache hit above
    # returned early and changed nothing, so it does not fire.
    _notify_case_update(case_id, 'generation')
    return artifact


__all__ = ["CASE_SUMMARY_KIND", "CASE_SUMMARY_PROMPT_ID", "PIPELINE_VERSION", "WRITER_MAX_TOKENS",
           "SPECIALIST_MAX_TOKENS", "MAX_CLAIMS", "OVERDUE_DAYS", "SYNTHESIZER_FAST_MODEL_MAP", "DOMAIN_CONFIG",
           "CaseSummaryError", "load_system_prompt", "build_case_payload", "build_case_record",
           "classification_for", "validate_claims", "generate_case_summary", "apply_answers_pass",
           "get_cached_summary", "find_cache_hit", "compute_input_hash", "save_summary_edit", "revert_summary_edit",
           "summary_edit_is_stale", "case_last_activity_at", "task_status_class"]

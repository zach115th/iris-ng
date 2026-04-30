#  IRIS Source Code
#
#  Tier-1 case summary generator — multi-pass map-reduce.
#
#  Stage 1 (per-domain specialists): four bounded LLM calls compress the
#  bulky free-form domains (notes, timeline, IOCs, assets) into compact
#  Markdown / structured-JSON sub-summaries. Each sub-summary is persisted
#  in case_ai_artifact with a `case_summary:<domain>` kind and is cached
#  on a stable hash of its own payload + prompt + model — so re-running
#  the summary after adding one IOC only re-runs the IOC specialist.
#
#  Stage 2 (synthesizer): one LLM call takes the structured case
#  metadata + raw tasks + the four sub-summaries and produces the
#  user-visible 7-section executive briefing. Cached as `case_summary`
#  with an input_hash covering all the sub-summary contents — so
#  the briefing re-runs only when at least one sub-summary changes.
#
#  Why multi-pass: local models (LM Studio gpt-oss-20b at 32K context)
#  can blow past the context budget on real cases — 30 notes × 4 KB +
#  75 timeline events × 1.5 KB easily exceed the window. The map-reduce
#  pattern fixes that by giving each domain its own focused window and
#  emitting compressed text into the synthesis stage.
#
#  Distinct from the multi-section incident-report generator (pinned in
#  n8n, see docs/19-ux-ai-design.md §5a.1) — that one emits a customer-
#  facing report with N domain specialists per section. This one is the
#  glanceable executive summary that updates with case state.

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app import app
from app import db
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client
from app.models.cases import Cases
from app.models.cases import CasesEvent
from app.models.models import CaseAiArtifact
from app.models.models import CaseAssets
from app.models.models import CaseTasks
from app.models.models import Ioc
from app.models.models import Notes


CASE_SUMMARY_KIND = "case_summary"
CASE_SUMMARY_PROMPT_ID = "CaseSummarizationSystemPrompt-v2"  # v2: multi-pass

PROMPTS_DIR = Path(__file__).parent.parent.parent / "resources" / "ai_prompts"

# Per-domain specialist config. Each entry: prompt filename, artifact kind
# discriminator, prompt-id (for the artifact metadata), and whether the
# specialist emits structured JSON the synthesizer needs to consume by
# field (vs a Markdown bullet list the synthesizer interpolates as text).
DOMAIN_CONFIG: dict[str, dict[str, Any]] = {
    "notes":    {"prompt_file": "case_summary_notes.md",    "kind": "case_summary:notes",    "prompt_id": "CaseSummaryNotes-v1",    "structured": False},
    "timeline": {"prompt_file": "case_summary_timeline.md", "kind": "case_summary:timeline", "prompt_id": "CaseSummaryTimeline-v1", "structured": True},
    "iocs":     {"prompt_file": "case_summary_iocs.md",     "kind": "case_summary:iocs",     "prompt_id": "CaseSummaryIocs-v1",     "structured": False},
    "assets":   {"prompt_file": "case_summary_assets.md",   "kind": "case_summary:assets",   "prompt_id": "CaseSummaryAssets-v1",   "structured": True},
}


class CaseSummaryError(Exception):
    """Raised when summary generation can't proceed."""


def _load_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8")


def load_system_prompt() -> str:
    """Synthesizer prompt — kept exported for back-compat with anything
    that imported it from the v1 module."""
    return _load_prompt("case_summary.md")


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[:limit] + " […]"


# ----- Domain payloads ------------------------------------------------------
#
# Each builder returns a JSON-serializable dict + a "is_empty" flag. The
# orchestrator skips the specialist call entirely when the domain is empty
# — saves 5–15 s of LM Studio time per skipped domain on sparse cases.


def _build_notes_payload(case_id: int) -> tuple[dict[str, Any], bool]:
    rows = Notes.query.filter(Notes.note_case_id == case_id).limit(50).all()
    notes = [
        {
            "title": n.note_title,
            "content": _truncate(n.note_content, 6000),
        }
        for n in rows
    ]
    return {"notes": notes}, len(notes) == 0


def _build_timeline_payload(case_id: int) -> tuple[dict[str, Any], bool]:
    rows = (
        CasesEvent.query
        .filter(CasesEvent.case_id == case_id)
        .order_by(CasesEvent.event_date.asc())
        .limit(150)
        .all()
    )
    timeline = [
        {
            "date": e.event_date.isoformat() if e.event_date else None,
            "title": e.event_title,
            "tags": e.event_tags or None,
            "content": _truncate(e.event_content, 1500),
            "source": _truncate(e.event_source, 200),
            "is_flagged": bool(e.event_is_flagged),
        }
        for e in rows
    ]
    return {"timeline": timeline}, len(timeline) == 0


def _build_iocs_payload(case_id: int) -> tuple[dict[str, Any], bool]:
    rows = Ioc.query.filter(Ioc.case_id == case_id).all()
    iocs = [
        {
            "value": i.ioc_value,
            "type": getattr(i.ioc_type, "type_name", None) if getattr(i, "ioc_type", None) else None,
            "tlp": getattr(i.tlp, "tlp_name", None) if getattr(i, "tlp", None) else None,
            "description": _truncate(i.ioc_description, 500),
            "tags": i.ioc_tags or None,
        }
        for i in rows
    ]
    return {"iocs": iocs}, len(iocs) == 0


def _build_assets_payload(case_id: int) -> tuple[dict[str, Any], bool]:
    rows = CaseAssets.query.filter(CaseAssets.case_id == case_id).all()
    assets = [
        {
            "name": a.asset_name,
            "type": getattr(a.asset_type, "asset_name", None) if getattr(a, "asset_type", None) else None,
            "ip": a.asset_ip or None,
            "domain": a.asset_domain or None,
            "compromise_status_id": a.asset_compromise_status_id,
            "description": _truncate(a.asset_description, 1000),
            "tags": a.asset_tags or None,
        }
        for a in rows
    ]
    return {"assets": assets}, len(assets) == 0


def _build_tasks_payload(case_id: int) -> list[dict[str, Any]]:
    rows = CaseTasks.query.filter(CaseTasks.task_case_id == case_id).all()
    return [
        {
            "title": t.task_title,
            "status_id": t.task_status_id,
            "description": _truncate(t.task_description, 800),
            "open_date": t.task_open_date.isoformat() if t.task_open_date else None,
            "close_date": t.task_close_date.isoformat() if t.task_close_date else None,
        }
        for t in rows
    ]


# ----- Hashing + caching ----------------------------------------------------


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
        .order_by(CaseAiArtifact.generated_at.desc())
        .first()
    )


def get_cached_summary(case_id: int) -> CaseAiArtifact | None:
    """Latest stored final summary for the case, regardless of input hash."""
    return (
        CaseAiArtifact.query
        .filter(
            CaseAiArtifact.case_id == case_id,
            CaseAiArtifact.kind == CASE_SUMMARY_KIND
        )
        .order_by(CaseAiArtifact.generated_at.desc())
        .first()
    )


def find_cache_hit(case_id: int, input_hash: str) -> CaseAiArtifact | None:
    """Backward-compat alias for the v1 cache lookup."""
    return _find_artifact(case_id, CASE_SUMMARY_KIND, input_hash)


# ----- Per-domain specialist call ------------------------------------------


def _call_domain_specialist(
    *, case_id: int, domain: str, payload: dict[str, Any], force: bool
) -> CaseAiArtifact | None:
    """Run one specialist or return its cached row.

    Returns None if the domain is empty (caller should pass `null` to the
    synthesizer in that case). Raises CaseSummaryError on real failures so
    the caller can decide whether to abort or proceed without that domain.
    """
    cfg = DOMAIN_CONFIG[domain]
    system_prompt = _load_prompt(cfg["prompt_file"])

    client = build_default_client(timeout=120.0, default_max_tokens=2000)
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
            return cached

    user_prompt = (
        f"Summarize the {domain} for this case using the data below.\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
    )

    app.logger.info(
        f"Case #{case_id}: domain '{domain}' specialist call "
        f"(model={client.model}, prompt={cfg['prompt_id']})"
    )

    try:
        response = client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])
    except AIClientError as exc:
        raise CaseSummaryError(
            f"Domain '{domain}' specialist call failed: {exc}"
        ) from exc

    content = client.extract_content(response).strip()
    if not content:
        raise CaseSummaryError(
            f"Domain '{domain}' specialist returned an empty response "
            f"(finish_reason={response.get('choices', [{}])[0].get('finish_reason')})"
        )

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
    return artifact


def _parse_specialist_content(domain: str, artifact: CaseAiArtifact | None) -> Any:
    """Convert a stored specialist artifact into the value the synthesizer
    expects in its input payload.

    Structured specialists (timeline, assets) emit JSON — parse it. Text
    specialists (notes, iocs) emit Markdown bullets — pass through as a
    string. Empty/missing returns None.
    """
    if artifact is None:
        return None
    cfg = DOMAIN_CONFIG[domain]
    raw = (artifact.content or "").strip()
    if not raw:
        return None
    if not cfg["structured"]:
        return raw  # Markdown bullets — synthesizer interpolates as text
    # Structured — strip optional fences and parse.
    if raw.startswith("```"):
        first_nl = raw.find("\n")
        if first_nl != -1:
            raw = raw[first_nl + 1:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        app.logger.warning(
            f"Case '{domain}' specialist returned non-JSON content "
            f"(artifact_id={artifact.id}); falling back to raw text"
        )
        return raw


# ----- Public API: backward-compatible single entry point ------------------


def build_case_payload(case: Cases) -> dict[str, Any]:
    """Build the legacy single-pass payload — kept for callers that still
    want the raw view (e.g. case_chat.py builds its context off this).

    Note: the multi-pass orchestrator does NOT use this; it calls the
    domain-specific builders directly so it can hash + cache each domain
    on its own input.
    """
    case_id = case.case_id
    notes_p, _ = _build_notes_payload(case_id)
    timeline_p, _ = _build_timeline_payload(case_id)
    iocs_p, _ = _build_iocs_payload(case_id)
    assets_p, _ = _build_assets_payload(case_id)
    tasks = _build_tasks_payload(case_id)
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
            "tasks": len(tasks),
            "notes": len(notes_p["notes"]),
        },
        "assets": assets_p["assets"],
        "iocs": iocs_p["iocs"],
        "timeline": timeline_p["timeline"],
        "tasks": tasks,
        "notes": notes_p["notes"],
    }


def compute_input_hash(payload: dict[str, Any], system_prompt: str, model: str) -> str:
    """Backward-compat hasher matching the v1 signature."""
    return _hash_inputs(model, system_prompt, payload)


def generate_case_summary(case_id: int, *, force: bool = False) -> CaseAiArtifact:
    """Map-reduce summary: 4 domain specialists then 1 synthesizer.

    Returns the final-stage artifact (kind=case_summary). Sub-summaries are
    persisted alongside as kind=case_summary:<domain> rows but are not
    returned — callers that want them can query case_ai_artifact directly.

    `force=True` invalidates every stage (specialists + synthesis); `False`
    serves cached rows wherever the input hash matches.
    """
    case = Cases.query.filter(Cases.case_id == case_id).first()
    if case is None:
        raise CaseSummaryError(f"Case #{case_id} not found")

    client = build_default_client(timeout=180.0, default_max_tokens=4000)
    if client is None:
        raise CaseSummaryError(
            "AI backend is not configured (set AI_BACKEND_URL and AI_BACKEND_MODEL)"
        )

    # Build the 4 domain payloads once. Each is hashed independently so the
    # specialist cache hits when only one domain changed.
    notes_payload, notes_empty = _build_notes_payload(case_id)
    timeline_payload, timeline_empty = _build_timeline_payload(case_id)
    iocs_payload, iocs_empty = _build_iocs_payload(case_id)
    assets_payload, assets_empty = _build_assets_payload(case_id)
    tasks = _build_tasks_payload(case_id)

    counts = {
        "assets": len(assets_payload["assets"]),
        "iocs": len(iocs_payload["iocs"]),
        "timeline_events": len(timeline_payload["timeline"]),
        "tasks": len(tasks),
        "notes": len(notes_payload["notes"]),
    }

    app.logger.info(
        f"Case #{case_id}: starting multi-pass summary "
        f"(model={client.model}, counts={counts}, force={force})"
    )

    # Stage 1: domain specialists. Run in a small thread pool so cache hits
    # finish instantly and any cache-miss waits overlap with each other —
    # if LM Studio is single-stream the requests just queue, but threading
    # at least frees the synthesizer to start as soon as all four return.
    domain_inputs = [
        ("notes",    notes_payload,    notes_empty),
        ("timeline", timeline_payload, timeline_empty),
        ("iocs",     iocs_payload,     iocs_empty),
        ("assets",   assets_payload,   assets_empty),
    ]
    artifacts: dict[str, CaseAiArtifact | None] = {}
    failures: dict[str, str] = {}

    def _runner(args):
        # Pool workers run in fresh threads with no Flask app context bound,
        # so push one explicitly — the specialist needs db.session (scoped
        # to the app context) and app.logger. Return the artifact's id (not
        # the ORM object) — the worker's session ends when the context
        # exits, so the calling thread re-fetches by id into its own session.
        domain, payload, empty = args
        if empty:
            return domain, None, None
        with app.app_context():
            try:
                art = _call_domain_specialist(case_id=case_id, domain=domain, payload=payload, force=force)
                return domain, (art.id if art else None), None
            except CaseSummaryError as exc:
                return domain, None, str(exc)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for domain, art_id, err in pool.map(_runner, domain_inputs):
            if art_id is not None:
                artifacts[domain] = db.session.get(CaseAiArtifact, art_id)
            else:
                artifacts[domain] = None
            if err:
                failures[domain] = err

    if failures:
        # Don't abort — the synthesizer can still produce a useful summary
        # if 3 of 4 domains succeeded. Only abort if everything blew up.
        app.logger.warning(
            f"Case #{case_id}: {len(failures)} domain specialist(s) failed: "
            + "; ".join(f"{k}: {v}" for k, v in failures.items())
        )
        if len(failures) == sum(1 for _, _, e in [(d, p, e) for (d, p, e) in domain_inputs if not e]):
            raise CaseSummaryError(
                "All domain specialists failed: "
                + "; ".join(f"{k}: {v}" for k, v in failures.items())
            )

    # Stage 2: synthesis. Build the input from the structured case fields +
    # raw tasks + the four sub-summary contents. Hash covers everything that
    # could change the synthesis output, so adding/removing a sub-summary
    # invalidates the cache.
    notes_summary    = _parse_specialist_content("notes",    artifacts.get("notes"))
    timeline_summary = _parse_specialist_content("timeline", artifacts.get("timeline"))
    iocs_summary     = _parse_specialist_content("iocs",     artifacts.get("iocs"))
    assets_summary   = _parse_specialist_content("assets",   artifacts.get("assets"))

    synthesis_payload = {
        "case": {
            "id": case.case_id,
            "name": case.name,
            "soc_id": case.soc_id,
            "open_date": case.open_date.isoformat() if case.open_date else None,
            "description": _truncate(case.description, 2000),
        },
        "counts": counts,
        "tasks": tasks,
        "notes_summary": notes_summary,
        "timeline_summary": timeline_summary,
        "iocs_summary": iocs_summary,
        "assets_summary": assets_summary,
    }

    synthesis_prompt = _load_prompt("case_summary.md")
    synthesis_hash = _hash_inputs(client.model, synthesis_prompt, synthesis_payload)

    if not force:
        cached = _find_artifact(case_id, CASE_SUMMARY_KIND, synthesis_hash)
        if cached is not None:
            app.logger.info(
                f"Case #{case_id}: synthesis cache hit "
                f"(artifact_id={cached.id}, generated_at={cached.generated_at.isoformat()})"
            )
            return cached

    user_prompt = (
        "Generate the executive case summary using the synthesized inputs below.\n\n"
        f"```json\n{json.dumps(synthesis_payload, indent=2, default=str)}\n```"
    )

    app.logger.info(
        f"Case #{case_id}: running synthesis stage "
        f"(model={client.model}, prompt={CASE_SUMMARY_PROMPT_ID})"
    )

    try:
        response = client.chat([
            {"role": "system", "content": synthesis_prompt},
            {"role": "user", "content": user_prompt}
        ])
    except AIClientError as exc:
        raise CaseSummaryError(f"Synthesis call failed: {exc}") from exc

    content = client.extract_content(response).strip()
    if not content:
        raise CaseSummaryError(
            f"Synthesis returned an empty response (finish_reason={response.get('choices', [{}])[0].get('finish_reason')})"
        )

    artifact = CaseAiArtifact(
        case_id=case_id,
        kind=CASE_SUMMARY_KIND,
        prompt_id=CASE_SUMMARY_PROMPT_ID,
        model=client.model,
        input_hash=synthesis_hash,
        content=content,
        confidence=None
    )
    db.session.add(artifact)
    db.session.commit()

    app.logger.info(
        f"Case #{case_id}: synthesis persisted "
        f"(artifact_id={artifact.id}, len={len(content)} chars, "
        f"usage={response.get('usage')})"
    )

    return artifact

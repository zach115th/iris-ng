#  IRIS Source Code
#
#  AI task suggester. Reads one case and proposes the NEXT tasks the team
#  should open. ADVISORY ONLY: the result is listed in the Tasks page's
#  suggestion panel; a task exists only once an analyst accepts it
#  (business/task_suggestions.py::accept_suggestions).
#
#  Split of responsibilities (the model is authoritative for nothing but the
#  suggestions themselves):
#    model   - title / description / rationale / priority, the SKILLS a task
#              needs (slugs from the catalog), and what it depends on.
#    server  - which suggestions survive (duplicates of existing tasks, unknown
#              skills, dangling or looping dependencies are dropped), and WHO is
#              proposed for each task: the model never sees an analyst. The
#              assignee is ranked here from skill overlap among users who can
#              actually work the case, at READ time, so a cached run never
#              carries a stale name.
#
#  Cached in case_ai_artifact (kind 'task_suggestions') keyed on
#  (model, prompt, payload). The payload holds no wall-clock value. A reply
#  that is not the expected JSON is an ERROR and is never persisted - a
#  refusal or an auth error must not become an empty "nothing to do" list.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app import app
from app import db
from app.iris_engine.ai.case_summary import _hash_inputs
from app.iris_engine.ai.case_summary import build_case_payload
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import build_default_client
from app.models.cases import Cases
from app.models.models import CaseAiArtifact

TASK_SUGGESTER_PROMPT_ID = "TaskSuggesterSystemPrompt-v1"
TASK_SUGGESTIONS_KIND = "task_suggestions"
PROMPT_PATH = Path(__file__).parent.parent.parent / "resources" / "ai_prompts" / "task_suggester.md"

MAX_SUGGESTIONS = 8
MAX_TOKENS = 6000            # reasoning models think before they answer (see case_chat)
MAX_TITLE = 160
MAX_DESCRIPTION = 2000
MAX_RATIONALE = 400
MAX_SKILLS = 3
MAX_DEPENDS = 5
PRIORITIES = ("high", "medium", "low")
CLOSED_STATUS_NAMES = ("done", "canceled", "cancelled", "closed")

_TASK_REF_RE = re.compile(r"^T(\d+)$")
_SUGG_REF_RE = re.compile(r"^S(\d+)$")


class TaskSuggesterError(Exception):
    """Raised when the suggester cannot produce a usable result."""


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _extract_json_block(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9]*\n?", "", stripped)
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


def normalise_title(title: Any) -> str:
    """Comparison key for "is this the same task": case, punctuation and
    spacing do not make a different task."""
    if not isinstance(title, str):
        return ""
    return " ".join(re.sub(r"[^\w\s]", " ", title.casefold()).split())


# --- payload -----------------------------------------------------------------

def existing_tasks(case_id: int) -> list[dict[str, Any]]:
    from app.models.models import CaseTasks
    from app.models.models import TaskAssignee
    from app.models.models import TaskStatus

    status_names = {s.id: (s.status_name or "") for s in TaskStatus.query.all()}
    rows = (CaseTasks.query.filter(CaseTasks.task_case_id == case_id)
            .order_by(CaseTasks.id.asc()).all())
    assigned = {r.task_id for r in TaskAssignee.query.with_entities(TaskAssignee.task_id)
                .filter(TaskAssignee.task_id.in_([t.id for t in rows] or [0])).all()}
    out = []
    for t in rows:
        status = status_names.get(t.task_status_id, "")
        desc = (t.task_description or "").strip()
        out.append({
            "id": int(t.id),
            "title": t.task_title,
            "status": status or None,
            "is_closed": status.strip().casefold() in CLOSED_STATUS_NAMES,
            "description": desc[:800] or None,
            "open_date": t.task_open_date.isoformat() if t.task_open_date else None,
            "close_date": t.task_close_date.isoformat() if t.task_close_date else None,
            "has_assignee": int(t.id) in assigned,
        })
    return out


def existing_task_links(case_id: int) -> list[dict[str, Any]]:
    from app.models.models import CaseTaskLink
    rows = (CaseTaskLink.query.filter(CaseTaskLink.case_id == case_id)
            .order_by(CaseTaskLink.id.asc()).all())
    return [{"from_task_id": int(r.from_task_id), "to_task_id": int(r.to_task_id),
             "link_type": r.link_type} for r in rows]


def skill_catalog() -> list[dict[str, str]]:
    from app.models.authorization import Skill
    rows = Skill.query.filter(Skill.is_active.isnot(False)).order_by(Skill.skill_slug.asc()).all()
    return [{"slug": s.skill_slug, "name": s.skill_name} for s in rows]


def build_payload(case: Cases) -> dict[str, Any]:
    """Everything the model sees. No analyst, no wall-clock value."""
    payload = build_case_payload(case)
    payload.pop("tasks", None)   # replaced by the id-bearing view below
    payload["existing_tasks"] = existing_tasks(case.case_id)
    payload["existing_task_links"] = existing_task_links(case.case_id)
    payload["skill_catalog"] = skill_catalog()
    return payload


# --- validation ---------------------------------------------------------------

def _clean_text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:limit] if text else None


def _breaks_loop(ref: str, dep: str, deps_by_ref: dict[str, list[str]]) -> bool:
    """Would `ref depends on dep` close a loop among the suggestions kept so far?"""
    stack, seen = [dep], set()
    while stack:
        cur = stack.pop()
        if cur == ref:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(d for d in deps_by_ref.get(cur, []) if _SUGG_REF_RE.match(d))
    return False


def validate_suggestions(parsed: Any, tasks: list[dict[str, Any]],
                         skill_slugs: set[str]) -> list[dict[str, Any]]:
    """Coerce the model's answer into suggestions that are safe to show.

    Raises TaskSuggesterError when the answer is not the contract at all (no
    `suggestions` list) - that is a failed call, not "nothing to suggest".
    """
    if not isinstance(parsed, dict) or not isinstance(parsed.get("suggestions"), list):
        raise TaskSuggesterError("AI backend returned JSON without a 'suggestions' list")

    taken = {normalise_title(t.get("title")) for t in tasks}
    taken.discard("")
    task_ids = {int(t["id"]) for t in tasks}

    kept: list[dict[str, Any]] = []
    ref_map: dict[str, str] = {}          # model ref -> server ref
    for item in parsed["suggestions"]:
        if len(kept) >= MAX_SUGGESTIONS:
            break
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"), MAX_TITLE)
        if title is None or len(title) < 2:
            continue
        key = normalise_title(title)
        if not key or key in taken:
            continue                       # already a task, or already suggested
        taken.add(key)

        priority = item.get("priority")
        priority = priority.strip().lower() if isinstance(priority, str) else ""
        raw_skills = item.get("skills") if isinstance(item.get("skills"), list) else []
        skills: list[str] = []
        for s in raw_skills:
            if isinstance(s, str) and s.strip() in skill_slugs and s.strip() not in skills:
                skills.append(s.strip())

        ref = f"S{len(kept) + 1}"
        model_ref = item.get("ref")
        if isinstance(model_ref, str) and model_ref.strip() and model_ref.strip() not in ref_map:
            ref_map[model_ref.strip()] = ref
        kept.append({
            "ref": ref,
            "title": title,
            "description": _clean_text(item.get("description"), MAX_DESCRIPTION),
            "rationale": _clean_text(item.get("rationale"), MAX_RATIONALE),
            "priority": priority if priority in PRIORITIES else "medium",
            "skills": skills[:MAX_SKILLS],
            "_raw_depends": item.get("depends_on") if isinstance(item.get("depends_on"), list) else [],
        })

    deps_by_ref: dict[str, list[str]] = {}
    for sugg in kept:
        deps: list[str] = []
        for dep in sugg.pop("_raw_depends"):
            if not isinstance(dep, str) or len(deps) >= MAX_DEPENDS:
                continue
            dep = dep.strip()
            m = _TASK_REF_RE.match(dep)
            if m:
                if int(m.group(1)) in task_ids and dep not in deps:
                    deps.append(dep)
                continue
            target = ref_map.get(dep)
            if target is None or target == sugg["ref"] or target in deps:
                continue
            if _breaks_loop(sugg["ref"], target, deps_by_ref):
                continue
            deps.append(target)
        sugg["depends_on"] = deps
        deps_by_ref[sugg["ref"]] = deps
    return kept


# --- assignee ranking (server-side; the model never sees a person) -----------

def assignable_users(case_id: int) -> list[dict[str, Any]]:
    """Active, human users with FULL access to the case, with their skill
    slugs and how many open tasks they already hold on it."""
    from app.models.authorization import CaseAccessLevel
    from app.models.authorization import Skill
    from app.models.authorization import User
    from app.models.authorization import UserCaseEffectiveAccess
    from app.models.authorization import UserSkill
    from app.models.models import TaskAssignee

    rows = (UserCaseEffectiveAccess.query
            .with_entities(User.id, User.name, User.user, UserCaseEffectiveAccess.access_level)
            .join(User, User.id == UserCaseEffectiveAccess.user_id)
            .filter(UserCaseEffectiveAccess.case_id == case_id,
                    User.active.is_(True),
                    User.is_service_account.isnot(True))
            .all())
    full, deny = CaseAccessLevel.full_access.value, CaseAccessLevel.deny_all.value
    users = {int(r.id): {"user_id": int(r.id), "user_name": r.name, "user_login": r.user}
             for r in rows
             if r.access_level is not None and (int(r.access_level) & full) and not (int(r.access_level) & deny)}
    if not users:
        return []

    skills: dict[int, list[str]] = {uid: [] for uid in users}
    for uid, slug in (UserSkill.query.with_entities(UserSkill.user_id, Skill.skill_slug)
                      .join(Skill, Skill.id == UserSkill.skill_id)
                      .filter(UserSkill.user_id.in_(list(users)), Skill.is_active.isnot(False)).all()):
        skills[int(uid)].append(slug)

    open_ids = [t["id"] for t in existing_tasks(case_id) if not t["is_closed"]]
    load: dict[int, int] = {uid: 0 for uid in users}
    if open_ids:
        for (uid,) in (TaskAssignee.query.with_entities(TaskAssignee.user_id)
                       .filter(TaskAssignee.task_id.in_(open_ids)).all()):
            if int(uid) in load:
                load[int(uid)] += 1

    out = []
    for uid, u in users.items():
        out.append({**u, "skills": sorted(skills[uid]), "open_tasks": load[uid]})
    out.sort(key=lambda u: (u["user_name"] or "").casefold())
    return out


def rank_assignee(skills: list[str], users: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Best skill match; ties go to whoever holds fewer open tasks on the case,
    then the lower user id (stable). No overlap = no proposal (None): the
    panel falls back to the analyst who is accepting."""
    wanted = set(skills or [])
    best = None
    for u in users:
        matched = sorted(wanted & set(u.get("skills") or []))
        if not matched:
            continue
        rank = (-len(matched), int(u.get("open_tasks") or 0), int(u["user_id"]))
        if best is None or rank < best[0]:
            best = (rank, u, matched)
    if best is None:
        return None
    _, u, matched = best
    return {"user_id": u["user_id"], "user_name": u["user_name"], "matched_skills": matched}


# --- cache --------------------------------------------------------------------

def _latest_artifact(case_id: int) -> CaseAiArtifact | None:
    return (CaseAiArtifact.query
            .filter(CaseAiArtifact.case_id == case_id,
                    CaseAiArtifact.kind == TASK_SUGGESTIONS_KIND)
            .order_by(CaseAiArtifact.generated_at.desc(), CaseAiArtifact.id.desc())
            .first())


def _current_hash(case: Cases) -> tuple[str | None, str | None]:
    """(input_hash, model) for the case as it is NOW; (None, None) when no AI
    backend is configured - staleness is then unknown, not false."""
    client = build_default_client(timeout=600.0, default_max_tokens=MAX_TOKENS, feature='task_suggester')
    if client is None:
        return None, None
    return _hash_inputs(client.model, load_system_prompt(), build_payload(case)), client.model


def compose_result(case_id: int, artifact: CaseAiArtifact, *, cached: bool,
                   stale: bool | None) -> dict[str, Any]:
    """Stored suggestions + everything computed live: suggestions that have
    since become tasks are withheld, dependencies on tasks that no longer
    exist are dropped, assignees are ranked against today's access + skills."""
    try:
        stored = json.loads(artifact.content or "{}").get("suggestions") or []
    except (TypeError, ValueError):
        stored = []
    tasks = existing_tasks(case_id)
    taken = {normalise_title(t["title"]) for t in tasks}
    task_titles = {f"T{t['id']}": t["title"] for t in tasks}
    users = assignable_users(case_id)

    live = [s for s in stored if normalise_title(s.get("title")) not in taken]
    live_refs = {s["ref"] for s in live}
    out = []
    for s in live:
        deps = []
        for dep in s.get("depends_on") or []:
            if dep in task_titles:
                deps.append({"ref": dep, "kind": "task", "task_id": int(dep[1:]), "title": task_titles[dep]})
            elif dep in live_refs:
                deps.append({"ref": dep, "kind": "suggestion",
                             "title": next(x["title"] for x in live if x["ref"] == dep)})
        out.append({**s, "depends_on": deps, "assignee": rank_assignee(s.get("skills") or [], users)})

    return {
        "case_id": case_id,
        "suggestions": out,
        "withheld_now_tasks": len(stored) - len(live),
        "assignable_users": [{"user_id": u["user_id"], "user_name": u["user_name"],
                              "skills": u["skills"], "open_tasks": u["open_tasks"]} for u in users],
        "artifact_id": artifact.id,
        "model": artifact.model,
        "prompt_id": artifact.prompt_id,
        "generated_at": artifact.generated_at.isoformat() if artifact.generated_at else None,
        "cached": cached,
        "stale": stale,
    }


def get_cached_suggestions(case_id: int) -> dict[str, Any] | None:
    """Newest stored run for the case, or None when the suggester never ran."""
    case = Cases.query.filter(Cases.case_id == case_id).first()
    artifact = _latest_artifact(case_id) if case is not None else None
    if artifact is None:
        return None
    current, _ = _current_hash(case)
    stale = None if current is None else (current != artifact.input_hash)
    return compose_result(case_id, artifact, cached=True, stale=stale)


# --- generation ----------------------------------------------------------------

def suggest_tasks(case_id: int, *, force: bool = False) -> dict[str, Any]:
    case = Cases.query.filter(Cases.case_id == case_id).first()
    if case is None:
        raise TaskSuggesterError(f"Case #{case_id} not found")

    client = build_default_client(timeout=600.0, default_max_tokens=MAX_TOKENS, feature='task_suggester')
    if client is None:
        raise TaskSuggesterError(
            "AI backend is not configured (set AI_BACKEND_URL and AI_BACKEND_MODEL "
            "or configure it in Server Settings)")

    system_prompt = load_system_prompt()
    payload = build_payload(case)
    input_hash = _hash_inputs(client.model, system_prompt, payload)

    if not force:
        hit = (CaseAiArtifact.query
               .filter(CaseAiArtifact.case_id == case_id,
                       CaseAiArtifact.kind == TASK_SUGGESTIONS_KIND,
                       CaseAiArtifact.input_hash == input_hash)
               .order_by(CaseAiArtifact.generated_at.desc()).first())
        if hit is not None:
            app.logger.info(f"TaskSuggester: case #{case_id} cache hit (artifact_id={hit.id})")
            return compose_result(case_id, hit, cached=True, stale=False)

    user_prompt = (
        "Propose the next tasks for this case. Return only the JSON object described "
        "in your instructions.\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, default=str)}\n```"
    )
    app.logger.info(f"TaskSuggester: case #{case_id} requesting suggestions (model={client.model}, "
                    f"existing_tasks={len(payload['existing_tasks'])})")
    try:
        response = client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], max_tokens=MAX_TOKENS)
    except AIClientError as exc:
        raise TaskSuggesterError(f"AI backend call failed: {exc}") from exc

    finish = response.get('choices', [{}])[0].get('finish_reason')
    raw = client.extract_content(response).strip()
    if not raw:
        raise TaskSuggesterError(f"AI backend returned an empty response (finish_reason={finish})")
    try:
        parsed = json.loads(_extract_json_block(raw))
    except json.JSONDecodeError as exc:
        detail = ' '.join(raw.split())[:200]
        hint = " (the reply hit the output limit)" if finish == "length" else ""
        raise TaskSuggesterError(f"AI backend did not return JSON{hint}. Backend said: {detail}") from exc

    suggestions = validate_suggestions(parsed, payload["existing_tasks"],
                                       {s["slug"] for s in payload["skill_catalog"]})

    artifact = CaseAiArtifact(
        case_id=case_id,
        kind=TASK_SUGGESTIONS_KIND,
        prompt_id=TASK_SUGGESTER_PROMPT_ID,
        model=client.model,
        input_hash=input_hash,
        content=json.dumps({"suggestions": suggestions}, ensure_ascii=False),
        confidence=None
    )
    db.session.add(artifact)
    db.session.commit()
    app.logger.info(f"TaskSuggester: case #{case_id} persisted {len(suggestions)} suggestion(s) "
                    f"(artifact_id={artifact.id})")
    return compose_result(case_id, artifact, cached=False, stale=False)

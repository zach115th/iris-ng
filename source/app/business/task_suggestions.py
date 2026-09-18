#  IRIS Source Code
#
#  Accepting AI task suggestions (iris_engine/ai/task_suggester.py). This is
#  the ONLY place a suggestion becomes a task, and it only runs on an
#  analyst's click. Each task is created through business.tasks.tasks_create
#  - the same funnel as the Add task modal - so module hooks, the activity
#  log and the task_assigned notification behave exactly as for a hand-made
#  task. Accepted tasks carry the `ai-suggested` tag as provenance.
#
#  What the client sends is treated as untrusted input, not as "what the
#  model said": the analyst may have edited the text, the assignee must be
#  someone who can work the case, a dependency must point at a task of THIS
#  case or at another item of the same batch.

from __future__ import annotations

import re
from typing import Any

from flask_login import current_user

from app import db
from app.business.errors import BusinessProcessingError
from app.business.tasks import tasks_create
from app.iris_engine.ai.task_suggester import MAX_DEPENDS
from app.iris_engine.ai.task_suggester import MAX_DESCRIPTION
from app.iris_engine.ai.task_suggester import MAX_SUGGESTIONS
from app.iris_engine.ai.task_suggester import MAX_TITLE
from app.iris_engine.ai.task_suggester import assignable_users
from app.iris_engine.ai.task_suggester import normalise_title
from app.models.models import CaseTaskLink
from app.models.models import CaseTasks
from app.models.models import TaskStatus

AI_SUGGESTED_TAG = "ai-suggested"
DEPENDS_ON = "depends_on"

_TASK_REF_RE = re.compile(r"^T(\d+)$")
_SUGG_REF_RE = re.compile(r"^S\d+$")


def _todo_status_id() -> int:
    """Lookup ids vary per deployment: resolve 'To do' by name, else the first status."""
    rows = TaskStatus.query.order_by(TaskStatus.id.asc()).all()
    if not rows:
        raise BusinessProcessingError("No task status is defined")
    for s in rows:
        if (s.status_name or "").strip().casefold() in ("to do", "todo"):
            return int(s.id)
    return int(rows[0].id)


def accept_suggestions(case_id: int, items: Any) -> dict[str, Any]:
    """Create tasks (+ depends_on links) from accepted suggestions.

    items: [{ref, title, description, assignee_id | None, depends_on: [ref, ...]}]
    Returns {'created': [{ref, task_id, title, assignee_id}], 'failed': [{ref, error}],
             'links_created': n, 'links_dropped': [{ref, depends_on, reason}]}.
    One bad item never blocks the others.
    """
    if not isinstance(items, list) or not items:
        raise BusinessProcessingError("'tasks' must be a non-empty list")
    if len(items) > MAX_SUGGESTIONS:
        raise BusinessProcessingError(f"At most {MAX_SUGGESTIONS} tasks can be accepted at once")

    status_id = _todo_status_id()
    allowed_assignees = {u["user_id"] for u in assignable_users(case_id)}
    case_task_ids = {int(r.id) for r in CaseTasks.query.with_entities(CaseTasks.id)
                     .filter(CaseTasks.task_case_id == case_id).all()}
    taken = {normalise_title(r.task_title) for r in CaseTasks.query.with_entities(CaseTasks.task_title)
             .filter(CaseTasks.task_case_id == case_id).all()}

    created: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    wanted_links: list[tuple[str, int, list[Any]]] = []
    ref_to_task: dict[str, int] = {}

    for pos, item in enumerate(items):
        ref = item.get("ref") if isinstance(item, dict) else None
        ref = ref.strip() if isinstance(ref, str) and _SUGG_REF_RE.match(ref.strip()) else f"#{pos + 1}"
        if not isinstance(item, dict):
            failed.append({"ref": ref, "error": "not an object"})
            continue
        title = item.get("title").strip()[:MAX_TITLE] if isinstance(item.get("title"), str) else ""
        if len(title) < 2:
            failed.append({"ref": ref, "error": "title is required (2 characters or more)"})
            continue
        key = normalise_title(title)
        if key in taken:
            failed.append({"ref": ref, "error": "a task with this title already exists on the case"})
            continue
        description = item.get("description")
        description = description.strip()[:MAX_DESCRIPTION] if isinstance(description, str) else ""

        assignee_id = item.get("assignee_id")
        if assignee_id is not None:
            if not isinstance(assignee_id, int) or isinstance(assignee_id, bool) \
                    or assignee_id not in allowed_assignees:
                failed.append({"ref": ref, "error": "assignee cannot work this case"})
                continue

        try:
            _, task = tasks_create(case_id, {
                "task_title": title,
                "task_description": description,
                "task_status_id": status_id,
                "task_tags": AI_SUGGESTED_TAG,
                "task_assignees_id": [assignee_id] if assignee_id is not None else [],
            })
        except BusinessProcessingError as exc:
            db.session.rollback()
            failed.append({"ref": ref, "error": exc.get_message()})
            continue

        taken.add(key)
        case_task_ids.add(int(task.id))
        ref_to_task[ref] = int(task.id)
        created.append({"ref": ref, "task_id": int(task.id), "title": task.task_title,
                        "assignee_id": assignee_id})
        deps = item.get("depends_on") if isinstance(item.get("depends_on"), list) else []
        wanted_links.append((ref, int(task.id), deps[:MAX_DEPENDS]))

    links_created = 0
    links_dropped: list[dict[str, Any]] = []
    for ref, task_id, deps in wanted_links:
        seen: set[int] = set()
        for dep in deps:
            dep = dep.strip() if isinstance(dep, str) else ""
            m = _TASK_REF_RE.match(dep)
            if m:
                target = int(m.group(1))
                if target not in case_task_ids:
                    links_dropped.append({"ref": ref, "depends_on": dep, "reason": "not a task of this case"})
                    continue
            elif dep in ref_to_task:
                target = ref_to_task[dep]
            else:
                links_dropped.append({"ref": ref, "depends_on": dep or None,
                                      "reason": "that suggestion was not accepted"})
                continue
            if target == task_id or target in seen:
                continue
            seen.add(target)
            db.session.add(CaseTaskLink(
                from_task_id=task_id, to_task_id=target, link_type=DEPENDS_ON, case_id=case_id,
                created_by=current_user.id if current_user and current_user.is_authenticated else None))
            links_created += 1
    if links_created:
        db.session.commit()

    return {"created": created, "failed": failed,
            "links_created": links_created, "links_dropped": links_dropped}

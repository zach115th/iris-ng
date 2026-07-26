#  IRIS Source Code
#  iris-next
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3 of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.

"""Data-management layer for analyst time tracking (case_time_entry).

Pure DB operations. The open/closed edit-lock and ownership policy live in
the business layer (app.business.case_time) — this module just reads/writes.
"""
from datetime import datetime
from datetime import timedelta

from sqlalchemy import desc

from app import db
from app.models.models import CaseTimeEntry
from app.models.models import CaseTasks
from app.models.models import TaskAssignee
from app.models.cases import Cases
from app.models.authorization import User


def get_time_entry(entry_id: int) -> CaseTimeEntry:
    return CaseTimeEntry.query.filter(CaseTimeEntry.id == entry_id).first()


def serialize_time_entry(entry: CaseTimeEntry) -> dict:
    """Shape returned to clients. Includes the analyst display name so the
    per-case list can render without a second lookup."""
    user_name = None
    user_login = None
    if entry.user_id is not None:
        u = User.query.with_entities(User.name, User.user).filter(User.id == entry.user_id).first()
        if u is not None:
            user_name = u.name
            user_login = u.user
    return {
        'id': entry.id,
        'case_id': entry.case_id,
        'user_id': entry.user_id,
        'user_name': user_name,
        'user_login': user_login,
        'task_id': entry.task_id,
        'minutes': entry.minutes,
        'activity_date': entry.activity_date.isoformat() if entry.activity_date else None,
        'note': entry.note,
        'created_at': entry.created_at.isoformat() if entry.created_at else None,
        'updated_at': entry.updated_at.isoformat() if entry.updated_at else None,
    }


def list_case_time_entries(case_id: int):
    """All time entries for a case, newest activity first."""
    entries = (
        CaseTimeEntry.query
        .filter(CaseTimeEntry.case_id == case_id)
        .order_by(desc(CaseTimeEntry.activity_date), desc(CaseTimeEntry.id))
        .all()
    )
    return [serialize_time_entry(e) for e in entries]


def case_total_minutes(case_id: int) -> int:
    total = (
        db.session.query(db.func.coalesce(db.func.sum(CaseTimeEntry.minutes), 0))
        .filter(CaseTimeEntry.case_id == case_id)
        .scalar()
    )
    return int(total or 0)


def fmt_minutes(mins) -> str:
    """`75` -> `'1:15'`. Shared by the template's Time tab."""
    mins = int(mins or 0)
    return f'{mins // 60}:{mins % 60:02d}'


def case_time_summary(case_id: int) -> dict:
    """Total + per-user + per-task breakdown for ONE case. Drives the case-info
    modal's Time tab. Server-rendered (the modal reloads fresh each open, so a
    live endpoint isn't needed here)."""
    total = case_total_minutes(case_id)

    # By user. Pull each analyst's hourly_rate so we can estimate per-user and
    # total case cost = sum(minutes/60 * rate). A user with no rate set
    # (hourly_rate IS NULL) contributes 0 to the cost but is flagged via
    # `unpriced` so the total isn't silently understated.
    user_rows = (
        db.session.query(
            CaseTimeEntry.user_id,
            User.name.label('user_name'),
            User.user.label('user_login'),
            User.hourly_rate.label('hourly_rate'),
            db.func.sum(CaseTimeEntry.minutes).label('minutes'),
        )
        .outerjoin(User, User.id == CaseTimeEntry.user_id)
        .filter(CaseTimeEntry.case_id == case_id)
        .group_by(CaseTimeEntry.user_id, User.name, User.user, User.hourly_rate)
        .order_by(db.func.sum(CaseTimeEntry.minutes).desc())
        .all()
    )
    by_user = []
    total_cost = 0.0
    any_unpriced = False
    for r in user_rows:
        mins = int(r.minutes or 0)
        rate = float(r.hourly_rate) if r.hourly_rate is not None else None
        unpriced = rate is None
        cost = 0.0 if unpriced else round((mins / 60.0) * rate, 2)
        if unpriced and mins > 0:
            any_unpriced = True
        total_cost += cost
        by_user.append({
            'label': r.user_name or r.user_login or 'Unassigned',
            'minutes': mins,
            'fmt': fmt_minutes(mins),
            'hourly_rate': rate,
            'unpriced': unpriced,
            'cost': round(cost, 2),
        })
    total_cost = round(total_cost, 2)

    # By task (NULL task_id -> case-level work)
    task_rows = (
        db.session.query(
            CaseTimeEntry.task_id,
            CaseTasks.task_title,
            db.func.sum(CaseTimeEntry.minutes).label('minutes'),
        )
        .outerjoin(CaseTasks, CaseTasks.id == CaseTimeEntry.task_id)
        .filter(CaseTimeEntry.case_id == case_id)
        .group_by(CaseTimeEntry.task_id, CaseTasks.task_title)
        .order_by(db.func.sum(CaseTimeEntry.minutes).desc())
        .all()
    )
    by_task = [
        {
            'task_id': r.task_id,
            'label': (f'#{r.task_id} {r.task_title}' if r.task_id else 'Case-level (no task)'),
            'minutes': int(r.minutes or 0),
            'fmt': fmt_minutes(r.minutes),
        }
        for r in task_rows
    ]

    return {
        'total_minutes': total,
        'total_fmt': fmt_minutes(total),
        'by_user': by_user,
        'by_task': by_task,
        # iris-ng: estimated case cost from logged time × per-analyst rate.
        'total_cost': total_cost,
        'total_cost_fmt': f'{total_cost:,.2f}',
        'has_unpriced_time': any_unpriced,
    }


def create_time_entry(case_id: int, user_id, minutes: int, activity_date,
                      task_id=None, note=None) -> CaseTimeEntry:
    entry = CaseTimeEntry(
        case_id=case_id,
        user_id=user_id,
        task_id=task_id,
        minutes=minutes,
        activity_date=activity_date,
        note=note,
    )
    db.session.add(entry)
    db.session.commit()
    return entry


def update_time_entry(entry: CaseTimeEntry, minutes=None, activity_date=None,
                      task_id=..., note=...) -> CaseTimeEntry:
    if minutes is not None:
        entry.minutes = minutes
    if activity_date is not None:
        entry.activity_date = activity_date
    if task_id is not ...:
        entry.task_id = task_id
    if note is not ...:
        entry.note = note
    entry.updated_at = datetime.utcnow()
    db.session.commit()
    return entry


def delete_time_entry(entry: CaseTimeEntry) -> None:
    db.session.delete(entry)
    db.session.commit()


def task_belongs_to_case(task_id: int, case_id: int) -> bool:
    if task_id is None:
        return True
    t = CaseTasks.query.with_entities(CaseTasks.task_case_id).filter(CaseTasks.id == task_id).first()
    return t is not None and t.task_case_id == case_id


def case_is_open(case_id: int):
    """Returns (exists: bool, is_open: bool). A case is OPEN iff close_date is
    NULL — the same canonical test the rest of the codebase uses. Reopening a
    case nulls close_date, so entries unlock automatically."""
    c = Cases.query.with_entities(Cases.close_date).filter(Cases.case_id == case_id).first()
    if c is None:
        return False, False
    return True, c.close_date is None


def cases_touched_without_time(user_id: int, days: int = 7):
    """Open cases the user is involved in (owns, opened, or is assigned a task
    on) that were active in the last `days` days but have NO time entry from
    this user yet. Drives the opt-in "you haven't logged time" nudge.

    Kept deliberately cheap — a handful of small queries, run only when the
    admin has enabled the nudge."""
    since = datetime.utcnow() - timedelta(days=days)

    # Cases the user owns/opened, still open, recently active.
    owned = (
        db.session.query(Cases.case_id, Cases.name)
        .filter(
            Cases.close_date.is_(None),
            ((Cases.owner_id == user_id) | (Cases.user_id == user_id)),
            ((Cases.initial_date >= since) | (Cases.open_date >= since.date())),
        )
        .all()
    )

    # Cases where the user is assigned an open task.
    assigned = (
        db.session.query(Cases.case_id, Cases.name)
        .select_from(TaskAssignee)
        .join(CaseTasks, CaseTasks.id == TaskAssignee.task_id)
        .join(Cases, Cases.case_id == CaseTasks.task_case_id)
        .filter(TaskAssignee.user_id == user_id, Cases.close_date.is_(None))
        .distinct()
        .all()
    )

    candidates = {cid: name for cid, name in owned}
    for cid, name in assigned:
        candidates.setdefault(cid, name)
    if not candidates:
        return []

    # Drop any case where this user has already logged time.
    logged_rows = (
        db.session.query(CaseTimeEntry.case_id)
        .filter(
            CaseTimeEntry.user_id == user_id,
            CaseTimeEntry.case_id.in_(list(candidates.keys())),
        )
        .distinct()
        .all()
    )
    logged = {r[0] for r in logged_rows}

    return [
        {'case_id': cid, 'case_name': name}
        for cid, name in candidates.items()
        if cid not in logged
    ]

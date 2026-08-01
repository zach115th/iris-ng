#  iris-next: per-case analyst team endpoints.
#
#  Routes (all under /api/v2/cases/<cid>/):
#    GET  /team               — current analyst assignments + required skills
#    PUT  /team               — replace analyst team + required skills
#    GET  /team/suggest       — skill-coverage-scored analyst suggestions
#    GET  /team/skills        — required skills for this case
#    PUT  /team/skills        — replace required skills for this case

from flask import Blueprint
from flask import request

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.access_controls import ac_api_return_access_denied
from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_success
from app.datamgmt.case.case_db import get_case
from app.datamgmt.case.case_team_db import (
    derive_required_skills_for_case,
    get_case_analysts,
    get_case_required_skill_ids,
    set_case_analysts,
    set_case_required_skills,
    suggest_analysts_for_case,
)
from app.datamgmt.manage.manage_users_db import get_skills_catalog
from app.iris_engine.access_control.utils import ac_fast_check_current_user_has_case_access
from app.models.authorization import CaseAccessLevel

case_team_blueprint = Blueprint('case_team', __name__)


def _check_access(case_id, levels=None):
    if levels is None:
        levels = [CaseAccessLevel.read_only, CaseAccessLevel.full_access]
    if not get_case(case_id):
        return response_api_error('Case not found'), 404
    if not ac_fast_check_current_user_has_case_access(case_id, levels):
        return ac_api_return_access_denied(caseid=case_id), 403
    return None


# ---------------------------------------------------------------------------
# Team assignment endpoints
# ---------------------------------------------------------------------------

@case_team_blueprint.get('/<int:case_id>/team')
@ac_api_requires()
def get_case_team(case_id):
    """Return current analyst team + required skills for this case."""
    err = _check_access(case_id)
    if err:
        return err

    analysts = get_case_analysts(case_id)
    required_skill_ids = get_case_required_skill_ids(case_id)
    catalog = get_skills_catalog()
    skill_map = {s['skill_id']: s for s in catalog}

    return response_api_success({
        'analysts': analysts,
        'required_skill_ids': required_skill_ids,
        'required_skills': [skill_map[sid] for sid in required_skill_ids if sid in skill_map],
    })


@case_team_blueprint.put('/<int:case_id>/team')
@ac_api_requires()
def put_case_team(case_id):
    """Replace analyst team and required skills atomically.

    Body: {
      "analysts": [{"user_id": int, "role": "lead"|"analyst"}, ...],
      "required_skill_ids": [int, ...]
    }
    """
    err = _check_access(case_id, [CaseAccessLevel.full_access])
    if err:
        return err

    body = request.get_json(silent=True) or {}
    analysts = body.get('analysts', [])
    required_skill_ids = body.get('required_skill_ids', [])

    saved_analysts = set_case_analysts(case_id, analysts)
    saved_skills = set_case_required_skills(case_id, required_skill_ids)
    catalog = get_skills_catalog()
    skill_map = {s['skill_id']: s for s in catalog}

    return response_api_success({
        'analysts': saved_analysts,
        'required_skill_ids': saved_skills,
        'required_skills': [skill_map[sid] for sid in saved_skills if sid in skill_map],
    })


# ---------------------------------------------------------------------------
# Skill suggestion endpoint
# ---------------------------------------------------------------------------

@case_team_blueprint.get('/<int:case_id>/team/suggest')
@ac_api_requires()
def suggest_case_team(case_id):
    """Return skill-coverage-scored analyst suggestions for this case.

    Query params:
      max (int, default 5) — max number of suggestions to return
    """
    err = _check_access(case_id)
    if err:
        return err

    max_size = min(int(request.args.get('max', 5)), 20)
    suggestions = suggest_analysts_for_case(case_id, max_team_size=max_size)
    required_ids = get_case_required_skill_ids(case_id)
    catalog = get_skills_catalog()
    skill_map = {s['skill_id']: s for s in catalog}

    return response_api_success({
        'suggestions': suggestions,
        'required_skill_ids': required_ids,
        'required_skills': [skill_map[sid] for sid in required_ids if sid in skill_map],
        'skill_catalog': catalog,
    })


# ---------------------------------------------------------------------------
# Required skills sub-resource
# ---------------------------------------------------------------------------

@case_team_blueprint.get('/<int:case_id>/team/skills')
@ac_api_requires()
def get_case_team_skills(case_id):
    err = _check_access(case_id)
    if err:
        return err

    skill_ids = get_case_required_skill_ids(case_id)
    catalog = get_skills_catalog()
    skill_map = {s['skill_id']: s for s in catalog}

    return response_api_success({
        'required_skill_ids': skill_ids,
        'required_skills': [skill_map[sid] for sid in skill_ids if sid in skill_map],
        'skill_catalog': catalog,
    })


@case_team_blueprint.get('/<int:case_id>/team/skills/derive')
@ac_api_requires()
def derive_case_team_skills(case_id):
    """Derive required skills from the case classification + tags (rule-based, no LLM).

    Always re-derives on every call (the caller decides whether to persist).
    Also persists the result into case_required_skill if the case has none yet.
    """
    err = _check_access(case_id)
    if err:
        return err

    derived_ids = derive_required_skills_for_case(case_id)

    # Auto-persist if case currently has no required skills set
    existing = get_case_required_skill_ids(case_id)
    if not existing and derived_ids:
        set_case_required_skills(case_id, derived_ids)

    catalog = get_skills_catalog()
    skill_map = {s['skill_id']: s for s in catalog}

    return response_api_success({
        'derived_skill_ids': derived_ids,
        'derived_skills': [skill_map[sid] for sid in derived_ids if sid in skill_map],
        'was_empty': not bool(existing),
    })


@case_team_blueprint.put('/<int:case_id>/team/skills')
@ac_api_requires()
def put_case_team_skills(case_id):
    """Replace the case's required-skill set.  Body: {"skill_ids": [int, ...]}"""
    err = _check_access(case_id, [CaseAccessLevel.full_access])
    if err:
        return err

    body = request.get_json(silent=True) or {}
    saved = set_case_required_skills(case_id, body.get('skill_ids', []))
    catalog = get_skills_catalog()
    skill_map = {s['skill_id']: s for s in catalog}

    return response_api_success({
        'required_skill_ids': saved,
        'required_skills': [skill_map[sid] for sid in saved if sid in skill_map],
    })

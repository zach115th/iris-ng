#  iris-next: /api/v2/teams/* — team-management API endpoints.
#
#  GET /api/v2/teams/analyst-skills — all active analysts with their skill IDs
#    (used by the /manage/teams coverage table; requires only logged-in user)

from flask import Blueprint

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.rest.endpoints import response_api_success
from app.datamgmt.manage.manage_users_db import get_user_skill_ids
from app.models.authorization import User

teams_blueprint = Blueprint('teams', __name__, url_prefix='/teams')


@teams_blueprint.get('/analyst-skills')
@ac_api_requires()
def get_analyst_skills():
    """All active users with their enabled skill IDs.

    Used by the /manage/teams skill-coverage table. No admin perm required —
    analysts need to view coverage across the team."""
    users = User.query.filter(User.active == True).order_by(User.name).all()
    result = []
    for u in users:
        skill_ids = sorted(get_user_skill_ids(u.id))
        result.append({
            'user_id': u.id,
            'user_name': u.name,
            'user_login': u.user,
            'user_email': u.email,
            'is_service_account': u.is_service_account,
            'skill_ids': skill_ids,
        })
    return response_api_success(result)

#  iris-next: /manage/teams — skill-coverage overview and per-case team assignments.
#  Accessible to all authenticated users (analysts need to view team coverage).

from flask import Blueprint
from flask import render_template
from flask_wtf import FlaskForm

from app.blueprints.access_controls import ac_requires
from app.datamgmt.manage.manage_users_db import get_skills_catalog

manage_teams_blueprint = Blueprint(
    'manage_teams',
    __name__,
    template_folder='templates'
)


@manage_teams_blueprint.route('/manage/teams', methods=['GET'])
@ac_requires()
def manage_teams_index(caseid, url_redir):
    from flask import redirect, url_for
    if url_redir:
        return redirect(url_for('manage_teams.manage_teams_index', cid=caseid))

    form = FlaskForm()
    skill_catalog = get_skills_catalog()

    return render_template(
        'manage_teams.html',
        form=form,
        skill_catalog=skill_catalog,
        caseid=caseid,
    )

from flask import Blueprint

from app.blueprints.rest.v2.auth import auth_blueprint
from app.blueprints.rest.v2.tasks import tasks_blueprint
from app.blueprints.rest.v2.iocs import iocs_blueprint
from app.blueprints.rest.v2.assets import assets_blueprint
from app.blueprints.rest.v2.alerts import alerts_blueprint
from app.blueprints.rest.v2.dashboard import dashboard_blueprint
from app.blueprints.rest.v2.cases import cases_blueprint
from app.blueprints.rest.v2.misp_tags import misp_tags_blueprint
from app.blueprints.rest.v2.ai_jobs import ai_jobs_blueprint
from app.blueprints.rest.v2.teams import teams_blueprint
from app.blueprints.rest.v2.correlation import correlation_blueprint
from app.blueprints.rest.v2.mail import mail_blueprint
from app.blueprints.rest.v2.alert_clusters import alert_clusters_blueprint
from app.blueprints.rest.v2.flows import flows_blueprint
from app.blueprints.rest.v2.customer_assets import customer_assets_blueprint
from app.blueprints.rest.v2.notifications import notifications_blueprint
from app.blueprints.rest.v2.war_rooms import war_rooms_blueprint
from app.blueprints.rest.v2.sponsor import sponsor_blueprint


# Create root /api/v2 blueprint
rest_v2_blueprint = Blueprint("rest_v2", __name__, url_prefix="/api/v2")


# Register child blueprints
rest_v2_blueprint.register_blueprint(cases_blueprint)
rest_v2_blueprint.register_blueprint(auth_blueprint)
rest_v2_blueprint.register_blueprint(tasks_blueprint)
rest_v2_blueprint.register_blueprint(iocs_blueprint)
rest_v2_blueprint.register_blueprint(assets_blueprint)
rest_v2_blueprint.register_blueprint(alerts_blueprint)
rest_v2_blueprint.register_blueprint(dashboard_blueprint)
rest_v2_blueprint.register_blueprint(misp_tags_blueprint)
rest_v2_blueprint.register_blueprint(sponsor_blueprint)
rest_v2_blueprint.register_blueprint(ai_jobs_blueprint)
rest_v2_blueprint.register_blueprint(teams_blueprint)
rest_v2_blueprint.register_blueprint(correlation_blueprint)
rest_v2_blueprint.register_blueprint(mail_blueprint)
rest_v2_blueprint.register_blueprint(alert_clusters_blueprint)
rest_v2_blueprint.register_blueprint(flows_blueprint)
rest_v2_blueprint.register_blueprint(customer_assets_blueprint)
rest_v2_blueprint.register_blueprint(notifications_blueprint)
rest_v2_blueprint.register_blueprint(war_rooms_blueprint)

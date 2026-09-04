#  IRIS Source Code
#  Copyright (C) 2026 - iris-ng
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
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

"""Mail ingest REST surface (iris-ng v2, Phase 1). All endpoints are
server_administrator-gated: rules decide which CUSTOMER ingested mail lands
under, which makes them tenant-boundary configuration, and the connection
tests exercise stored credentials.

Importing this module is also what wires app.iris_engine.mail.mail_poller
into the celery task registry for BOTH the web and worker processes (the
worker imports the app package, which imports the blueprints)."""

import marshmallow
from flask import Blueprint
from flask import request
from flask_login import current_user

from app import db
from app.blueprints.access_controls import ac_api_requires
from app.blueprints.rest.endpoints import response_api_created
from app.blueprints.rest.endpoints import response_api_deleted
from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
from app.business.mail_rules import evaluate_conditions
from app.iris_engine.mail import mail_poller  # noqa: F401  (task registration)
from app.iris_engine.mail.mail_client import test_connection as imap_test_connection
from app.iris_engine.mail.mail_sender import test_connection as smtp_test_connection
from app.iris_engine.utils.tracker import track_activity
from app.models.alerts import MailIngestLog
from app.models.alerts import MailRule
from app.models.authorization import Permissions
from app.models.models import ServerSettings
from app.schema.marshables import _validate_mail_rule_conditions
from app.schema.marshables import MailIngestLogSchema
from app.schema.marshables import MailRuleSchema

mail_blueprint = Blueprint('mail_rest_v2', __name__)


# ---------------------------------------------------------------- mail rules

@mail_blueprint.route('/mail-rules', methods=['GET'])
@ac_api_requires(Permissions.server_administrator)
def list_mail_rules():
    rules = MailRule.query.order_by(MailRule.priority.asc(), MailRule.id.asc()).all()
    return response_api_success(MailRuleSchema(many=True).dump(rules))


@mail_blueprint.route('/mail-rules', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def create_mail_rule():
    try:
        rule = MailRuleSchema().load(request.get_json())
    except marshmallow.exceptions.ValidationError as e:
        return response_api_error('Data error', data=e.messages)
    rule.created_by = current_user.id
    db.session.add(rule)
    db.session.commit()
    track_activity(f"created mail rule '{rule.name}'", ctx_less=True)
    return response_api_created(MailRuleSchema().dump(rule))


@mail_blueprint.route('/mail-rules/<int:rule_id>', methods=['GET'])
@ac_api_requires(Permissions.server_administrator)
def get_mail_rule(rule_id):
    rule = db.session.get(MailRule, rule_id)
    if rule is None:
        return response_api_not_found()
    return response_api_success(MailRuleSchema().dump(rule))


@mail_blueprint.route('/mail-rules/<int:rule_id>', methods=['PUT'])
@ac_api_requires(Permissions.server_administrator)
def update_mail_rule(rule_id):
    rule = db.session.get(MailRule, rule_id)
    if rule is None:
        return response_api_not_found()
    try:
        rule = MailRuleSchema().load(request.get_json(), instance=rule, partial=True)
    except marshmallow.exceptions.ValidationError as e:
        return response_api_error('Data error', data=e.messages)
    db.session.commit()
    track_activity(f"updated mail rule '{rule.name}'", ctx_less=True)
    return response_api_success(MailRuleSchema().dump(rule))


@mail_blueprint.route('/mail-rules/<int:rule_id>', methods=['DELETE'])
@ac_api_requires(Permissions.server_administrator)
def delete_mail_rule(rule_id):
    rule = db.session.get(MailRule, rule_id)
    if rule is None:
        return response_api_not_found()
    name = rule.name
    # mail_ingest_log.rule_id is ondelete=SET NULL — the audit trail survives.
    db.session.delete(rule)
    db.session.commit()
    track_activity(f"deleted mail rule '{name}'", ctx_less=True)
    return response_api_deleted()


@mail_blueprint.route('/mail-rules/reorder', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def reorder_mail_rules():
    """Body: {"order": [rule_id, ...]} — priorities reassigned 10, 20, 30…
    in the given sequence. Ids not listed keep their current priority."""
    body = request.get_json() or {}
    order = body.get('order')
    if not isinstance(order, list) or not all(isinstance(i, int) for i in order):
        return response_api_error('order must be a list of rule ids')
    rules = {r.id: r for r in MailRule.query.filter(MailRule.id.in_(order)).all()}
    missing = [i for i in order if i not in rules]
    if missing:
        return response_api_error(f'unknown rule id(s): {missing}')
    for pos, rule_id in enumerate(order):
        rules[rule_id].priority = (pos + 1) * 10
    db.session.commit()
    track_activity('reordered mail rules', ctx_less=True)
    return response_api_success(MailRuleSchema(many=True).dump(
        MailRule.query.order_by(MailRule.priority.asc(), MailRule.id.asc()).all()))


@mail_blueprint.route('/mail-rules/test', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def test_mail_rule():
    """Dry-run rule conditions against a pasted sample message — the SAME
    evaluator the poller uses, so a green test means a real match.

    Body: {"conditions": [...]} or {"rule_id": N}, plus
          {"sample": {"subject": ..., "from": ..., "to": ..., "body": ...}}."""
    body = request.get_json() or {}
    sample = body.get('sample') or {}
    if 'rule_id' in body:
        rule = db.session.get(MailRule, body['rule_id'])
        if rule is None:
            return response_api_not_found()
        conditions = rule.conditions
    else:
        conditions = body.get('conditions')
        if conditions is None:
            return response_api_error('provide conditions or rule_id')
        # Ad-hoc conditions get the SAME validation a save gets (field
        # names, pattern cap, compilability, the ReDoS gate) — a rejected
        # regex is a named 400 here, not a silent no-match, and a test
        # that passes cannot behave differently once saved. NOT re.escape:
        # escaping would make the dry-run match literally while the saved
        # rule matches as a regex.
        try:
            _validate_mail_rule_conditions(conditions)
        except marshmallow.ValidationError as e:
            return response_api_error(str(e.messages))
    parsed = {k: str(sample.get(k) or '') for k in ('subject', 'from', 'to', 'body')}
    return response_api_success({'matches': evaluate_conditions(conditions, parsed)})


# ------------------------------------------------------------ poll & testing

@mail_blueprint.route('/mail/poll', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def poll_now():
    """Poll Now — enqueues one forced poll cycle (skips the interval gate;
    the advisory lock still guarantees a single concurrent poll)."""
    task = mail_poller.task_poll_mailbox.delay(force=True)
    track_activity('mail poll requested', ctx_less=True)
    return response_api_success({'task_id': task.id})


@mail_blueprint.route('/mail/test-connection', methods=['POST'])
@ac_api_requires(Permissions.server_administrator)
def mail_test_connection():
    """Handshake check against the STORED settings (the UI cannot know the
    write-only passwords). Body: {"target": "imap"|"smtp"}."""
    target = (request.get_json() or {}).get('target')
    settings = db.session.query(ServerSettings).first()
    if settings is None:
        return response_api_error('server settings not initialised')
    if target == 'imap':
        if not settings.mail_imap_host:
            return response_api_success({'ok': False, 'detail': 'IMAP host is not configured'})
        result = imap_test_connection(
            settings.mail_imap_host, settings.mail_imap_port,
            settings.mail_imap_username, settings.mail_imap_password,
            use_ssl=bool(settings.mail_imap_ssl),
            folder=settings.mail_imap_folder or 'INBOX')
    elif target == 'smtp':
        result = smtp_test_connection(settings)
    else:
        return response_api_error("target must be 'imap' or 'smtp'")
    return response_api_success(result)


@mail_blueprint.route('/mail/ingest-log', methods=['GET'])
@ac_api_requires(Permissions.server_administrator)
def ingest_log():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 25, type=int), 100)
    q = (MailIngestLog.query.order_by(MailIngestLog.processed_at.desc())
         .paginate(page=page, per_page=per_page, error_out=False))
    return response_api_success({
        'total': q.total,
        'page': q.page,
        'per_page': per_page,
        'rows': MailIngestLogSchema(many=True).dump(q.items),
    })

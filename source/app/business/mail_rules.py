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

"""Mail-rule evaluation + alert-payload building (iris-ng v2, Phase 1).

Kept in the business layer because TWO callers need identical semantics: the
IMAP poller (iris_engine/mail/mail_poller.py) and the rules /test endpoint
(dry-run). A parsed message is a plain dict with keys 'subject', 'from',
'to', 'body' (+ 'message_id', 'received_at', 'imap_uid', 'folder' for
payload building) so both callers can construct one without touching IMAP.
"""

import re

from app import db
from app.business.condition_eval import MAX_PATTERN_LEN
from app.business.condition_eval import is_safe_regex
from app.models.alerts import MailRule
from app.models.alerts import AlertStatus
from app.models.alerts import Severity

# Regex inputs are truncated before matching. Rules are admin-supplied, but a
# catastrophic-backtracking pattern against an unbounded body would stall the
# poller; 4 KB is plenty for matching intent.
_MATCH_TRUNCATE = 4096

_CONDITION_FIELDS = ('subject', 'from', 'to', 'body')


def evaluate_conditions(conditions: list, parsed: dict) -> bool:
    """AND every {field, regex} leaf against the parsed message. An empty (or
    null) condition list matches everything — meaningful only on a fallback
    rule, but harmless elsewhere. An invalid regex or unknown field fails the
    condition (and therefore the rule) rather than raising: one bad rule must
    not take down evaluation of the mailbox."""
    for cond in (conditions or []):
        field = cond.get('field')
        pattern = cond.get('regex') or ''
        if field not in _CONDITION_FIELDS:
            return False
        if len(pattern) > MAX_PATTERN_LEN:
            return False
        if not is_safe_regex(pattern):
            return False
        value = (parsed.get(field) or '')[:_MATCH_TRUNCATE]
        try:
            if not re.search(pattern, value, re.IGNORECASE):
                return False
        except re.error:
            return False
    return True


def find_matching_rule(parsed: dict, rules=None):
    """First enabled match wins, ascending priority; fallback rules are
    evaluated after ALL non-fallback rules regardless of their priority value,
    so a fallback can never shadow an ordinary rule. Returns None when nothing
    matches (outcome 'no_match')."""
    if rules is None:
        rules = (MailRule.query.filter(MailRule.enabled == True)  # noqa: E712
                 .order_by(MailRule.priority.asc(), MailRule.id.asc()).all())
    ordinary = [r for r in rules if not r.is_fallback]
    fallback = [r for r in rules if r.is_fallback]
    for rule in ordinary + fallback:
        if evaluate_conditions(rule.conditions, parsed):
            return rule
    return None


_TEMPLATE_TOKEN = re.compile(r'\{(subject|from|to)\}')


def render_title(template, parsed: dict) -> str:
    """Safe substitution of {subject} / {from} / {to} only — never str.format
    on admin/user input. Falls back to '[Mail] <subject>'."""
    if template:
        title = _TEMPLATE_TOKEN.sub(
            lambda m: (parsed.get(m.group(1)) or '')[:512], template).strip()
        if title:
            return title[:1024]
    return ('[Mail] ' + (parsed.get('subject') or '(no subject)'))[:1024]


def _lowest_severity_id() -> int:
    """The v3-style fallback is "lowest severity". Lookup ids vary per
    deployment, so resolve by name at runtime; 'Informational' is the seeded
    floor, min(id) the last resort."""
    row = Severity.query.filter(Severity.severity_name == 'Informational').first()
    if row:
        return row.severity_id
    return db.session.query(db.func.min(Severity.severity_id)).scalar()


def _new_alert_status_id() -> int:
    row = AlertStatus.query.filter(AlertStatus.status_name == 'New').first()
    if row:
        return row.status_id
    return db.session.query(db.func.min(AlertStatus.status_id)).scalar()


def build_alert_payload(rule: MailRule, parsed: dict, triage: dict = None) -> dict:
    """Build an /alerts/add-shaped payload from a matched rule + parsed email.
    Rule defaults are the floor; a successful AI triage may refine severity /
    classification and contribute extracted IOCs — it can never remove the
    rule's values, only override severity/classification or add IOCs."""
    triage = triage or {}

    severity_id = triage.get('severity_id') or rule.severity_id or _lowest_severity_id()
    classification_id = triage.get('classification_id') or rule.classification_id

    description = (parsed.get('body') or '')[:8192]
    summary = triage.get('summary')
    if summary:
        description = f"{summary}\n\n---\n\n{description}"

    payload = {
        'alert_title': render_title(rule.title_template, parsed),
        'alert_description': description,
        'alert_source': rule.alert_source or 'Mail',
        'alert_source_ref': parsed.get('message_id') or parsed.get('imap_uid') or '',
        'alert_severity_id': severity_id,
        'alert_status_id': _new_alert_status_id(),
        'alert_customer_id': rule.customer_id,
        'alert_context': {
            'mail_from': parsed.get('from'),
            'mail_to': parsed.get('to'),
            'mail_subject': parsed.get('subject'),
            'mail_message_id': parsed.get('message_id'),
            'mail_folder': parsed.get('folder'),
            'mail_rule': rule.name,
        },
        'alert_source_content': {
            'headers': {
                'from': parsed.get('from'),
                'to': parsed.get('to'),
                'subject': parsed.get('subject'),
                'message_id': parsed.get('message_id'),
                'date': parsed.get('received_at'),
            },
            'body_excerpt': (parsed.get('body') or '')[:4096],
        },
        'alert_tags': 'mail-ingest',
        'alert_iocs': triage.get('iocs') or [],
        'alert_assets': [],
    }
    if classification_id:
        payload['alert_classification_id'] = classification_id
    if parsed.get('received_at'):
        payload['alert_source_event_time'] = parsed['received_at']
    return payload

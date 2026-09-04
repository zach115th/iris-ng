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

"""Addressed-to-me notifications (iris-ng v2, Phase 5).

notify() is the single emission funnel. Two load-bearing properties, both
inherited from the Phase 4 sync engine and for the same reasons:

- **It writes on its OWN engine-level connection** (db.engine.begin()), never
  through the caller's session. Emission points sit inside hot-path routes
  (comments, task updates, case updates, alert escalation); a notification
  write must never commit a caller's half-done transaction and a caller
  rollback must not lose an already-decided notification.
- **It never raises.** A notification is strictly derived convenience data;
  the underlying write (the comment, the assignment) must survive any
  notify() failure. Every emission point gets a regression test asserting
  exactly that.

Channel resolution: per-user override row -> org default
(server_settings.notification_defaults JSONB) -> code default (in-app on,
email off). Email sends are enqueued to celery AFTER the insert transaction
commits and are additionally gated inside the task on
email_notifications_enabled + SMTP configuration, so flipping the master
switch off silences the channel with no queue drain needed.
"""

import re

from sqlalchemy import text as sa_text

import app
from app import celery
from app import db
from app.models.models import ServerSettings

log = app.app.logger

# v1 event catalog — aligned with the v3 preview's per-user Notifications
# matrix (docs/25 §Phase 5 design reference). war_room_message is emitted
# from Phase 6; custom_module_notification is a stub for the module API.
EVENT_CATALOG = {
    'mention': 'You are mentioned',
    'task_assigned': 'Task assigned to you',
    'case_updated_own': 'Case you own is updated',
    'case_assigned': 'Case assigned to you',
    'alert_assigned': 'Alert assigned to you',
    'alert_escalated': 'Alert escalated',
    # v3 parity (2026-09-01): alert-cluster ownership is a first-class
    # assignment (OWNER on the cluster header/list).
    'cluster_assigned': 'Alert cluster assigned to you',
    # iris-ng extension (not in v3's matrix): the reviewer-before-close flow
    # makes review selection a first-class assignment.
    'case_review_requested': 'You are asked to review a case',
    'war_room_added': 'Added to a war room',
    'war_room_message': 'War-room message',
    'sitrep_published': 'SitRep published',
    'custom_module_notification': 'Custom module notification',
}

_CODE_DEFAULT = {'in_app': True, 'email': False}

# Per-event code defaults override the global one. war_room_message is
# QUIET by default: it fires on EVERY chat message in a room the user is a
# member of, so default-on would flood the bell — members opt in via their
# matrix (or the org default) when they want message pings.
_EVENT_CODE_DEFAULTS = {
    'war_room_message': {'in_app': False, 'email': False},
}


def _code_default(event_type):
    return _EVENT_CODE_DEFAULTS.get(event_type, _CODE_DEFAULT)

# @login tokens. Logins may carry dots/dashes/underscores/@ (service accounts
# use email-like logins); match lazily and resolve against the user table so
# "@bob." at the end of a sentence still finds login "bob".
_MENTION_RE = re.compile(r'@([A-Za-z0-9][A-Za-z0-9._@-]{0,127})')


def resolve_channels(user_ids, event_type, conn=None):
    """{user_id: {'in_app': bool, 'email': bool}} for ACTIVE users only.

    Reads on the given connection (or a throwaway one) — never the ORM
    session, so it is safe mid-transaction anywhere.
    """
    if not user_ids:
        return {}

    def _read(c):
        active = {r[0] for r in c.execute(sa_text(
            'SELECT id FROM "user" WHERE id = ANY(:ids) AND active = true'),
            {'ids': list(user_ids)}).all()}
        org_row = c.execute(sa_text(
            'SELECT notification_defaults FROM server_settings LIMIT 1')).first()
        org = (org_row[0] or {}) if org_row else {}
        org_ev = org.get(event_type) or {}
        code_default = _code_default(event_type)
        base = {
            'in_app': bool(org_ev.get('in_app', code_default['in_app'])),
            'email': bool(org_ev.get('email', code_default['email'])),
        }
        out = {uid: dict(base) for uid in active}
        rows = c.execute(sa_text(
            'SELECT user_id, in_app, email FROM user_notification_preference '
            'WHERE user_id = ANY(:ids) AND event_type = :ev'),
            {'ids': list(active) or [0], 'ev': event_type}).all()
        for uid, in_app, email in rows:
            # NULL channel = inherit the org default.
            if in_app is not None:
                out[uid]['in_app'] = bool(in_app)
            if email is not None:
                out[uid]['email'] = bool(email)
        return out

    if conn is not None:
        return _read(conn)
    with db.engine.connect() as c:
        return _read(c)


def notify(event_type, user_ids, title, body=None, object_type=None,
           object_id=None, case_id=None, url=None, actor_id=None,
           keep_actor=False):
    """Emit one notification to each recipient. NEVER raises; returns the
    number of in-app rows written (0 on failure or empty recipient set).

    Recipients equal to actor_id are dropped — nobody needs a notification
    about their own action — UNLESS keep_actor is set. Three callers pass it
    (maintainer decisions): review selection ("you are the reviewer now" is
    a standing assignment worth a record even when self-assigned),
    notify_mentions (an @mention is an explicit address, deliberate even
    when it names yourself), and task assignment (2026-09-02 — assigning a
    task to yourself is an explicit assignment; the silent version was
    reported as a bug). On a single-operator instance the dedupe would
    otherwise make these events permanently silent.
    """
    try:
        recipients = {int(u) for u in (user_ids or []) if u is not None}
        if not keep_actor:
            recipients.discard(actor_id)
        if not recipients:
            return 0
        if event_type not in EVENT_CATALOG:
            log.warning('notify: unknown event type %s — dropped', event_type)
            return 0

        email_uids = []
        written = 0
        with db.engine.begin() as conn:
            channels = resolve_channels(recipients, event_type, conn=conn)
            rows = []
            for uid, ch in channels.items():
                if ch['in_app']:
                    rows.append({
                        'uid': uid, 'ev': event_type, 'title': title,
                        'body': body, 'ot': object_type, 'oid': object_id,
                        'cid': case_id, 'url': url,
                    })
                if ch['email']:
                    email_uids.append(uid)
            if rows:
                conn.execute(sa_text(
                    'INSERT INTO notification '
                    ' (user_id, event_type, title, body, object_type,'
                    '  object_id, case_id, url) '
                    'VALUES (:uid, :ev, :title, :body, :ot, :oid, :cid, :url)'),
                    rows)
                written = len(rows)

        # Enqueue AFTER the insert transaction is committed.
        for uid in email_uids:
            try:
                task_send_notification_email.delay(uid, title, body or '', url)
            except Exception:
                log.exception('notify: email enqueue failed for user %s', uid)
        return written
    except Exception:
        log.exception('notify: emission failed for event %s', event_type)
        return 0


def scan_mentions(text):
    """Resolve @login tokens in text to user ids. Longest-candidate-first per
    token: '@bob.smith,' tries 'bob.smith,' then 'bob.smith' then 'bob.smith'
    minus further trailing punctuation, so sentence punctuation never breaks a
    match. Case-insensitive against User.user (the LOGIN field — project
    rule: there is no user_login attribute)."""
    if not text:
        return []
    candidates = set()
    for tok in _MENTION_RE.findall(text):
        t = tok
        while t:
            candidates.add(t.lower())
            if t[-1] in '.-_@':
                t = t[:-1]
            else:
                break
    if not candidates:
        return []
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(sa_text(
                'SELECT id FROM "user" WHERE lower("user") = ANY(:logins) '
                'AND active = true'), {'logins': list(candidates)}).all()
        return [r[0] for r in rows]
    except Exception:
        log.exception('scan_mentions failed')
        return []


def case_access_user_ids(case_id):
    """User ids allowed to see the case — the ACL boundary for case-object
    mentions. Business layer wrapping the datamgmt helper (routes call this,
    never datamgmt directly).

    deny_all rows are FILTERED: get_users_list_restricted_from_case returns
    every effective-access row including explicit denials, and a denied user
    must not learn about case activity through a mention."""
    try:
        from app.datamgmt.manage.manage_users_db import get_users_list_restricted_from_case
        from app.models.authorization import CaseAccessLevel
        return [u.get('user_id') for u in get_users_list_restricted_from_case(case_id)
                if u.get('user_access_level') != CaseAccessLevel.deny_all.value]
    except Exception:
        log.exception('case_access_user_ids failed for case %s', case_id)
        return []


def client_access_filter(user_ids, client_id):
    """Subset of user_ids with access to the client — the ACL boundary for
    alert mentions. Per-user check is fine: mention lists are tiny.

    Deliberately NOT user_has_client_access: that helper short-circuits True
    when the SESSION user is a server_administrator (the known asymmetry) —
    here the question is about the TARGET user, so an admin commenting
    would otherwise grant every mentioned login access. Check the target's
    own UserClient rows / admin permission instead."""
    try:
        from app.iris_engine.access_control.utils import ac_get_effective_permissions_of_user
        from app.models.authorization import Permissions
        from app.models.authorization import User
        from app.models.authorization import UserClient
        out = []
        for uid in user_ids:
            if UserClient.query.filter_by(user_id=uid, client_id=client_id).first():
                out.append(uid)
                continue
            target = db.session.get(User, uid)
            if target is not None and (
                    ac_get_effective_permissions_of_user(target)
                    & Permissions.server_administrator.value):
                out.append(uid)
        return out
    except Exception:
        log.exception('client_access_filter failed for client %s', client_id)
        return []


def notify_mentions(text, title, *, body=None, object_type=None,
                    object_id=None, case_id=None, url=None, actor_id=None,
                    allowed_user_ids=None):
    """scan + notify in one fail-soft call for the comment endpoints.
    allowed_user_ids (when given) restricts recipients to users who can see
    the object — mentions must not leak activity across ACL boundaries.

    keep_actor: an @mention is an EXPLICIT address — typing your own login
    is deliberate, not incidental self-activity — so a self-mention notifies
    (same single-operator rationale as case_review_requested)."""
    try:
        mentioned = scan_mentions(text)
        if allowed_user_ids is not None:
            allowed = {int(u) for u in allowed_user_ids}
            mentioned = [u for u in mentioned if u in allowed]
        return notify('mention', mentioned, title, body=body,
                      object_type=object_type, object_id=object_id,
                      case_id=case_id, url=url, actor_id=actor_id,
                      keep_actor=True)
    except Exception:
        log.exception('notify_mentions failed')
        return 0


@celery.task(bind=True)
def task_send_notification_email(self, user_id, subject, body, url=None):
    """Send one notification email. Gated HERE on the master switch + SMTP
    config so a queued send after the admin turns the channel off is a no-op.
    Failures are logged, never retried — a notification email is best-effort."""
    with app.app.app_context():
        try:
            settings = ServerSettings.query.first()
            if not settings or not settings.email_notifications_enabled:
                return 'email channel disabled'
            if not settings.mail_smtp_host:
                return 'smtp not configured'
            row = db.session.execute(sa_text(
                'SELECT email FROM "user" WHERE id = :uid AND active = true'),
                {'uid': user_id}).first()
            if not row or not row[0]:
                return 'no recipient email'
            text_body = body or subject
            if url:
                text_body = f'{text_body}\n\n{url}'
            from app.iris_engine.mail.mail_sender import send_email
            send_email(settings, row[0], f'[IRIS-NG] {subject}', text_body)
            return f'sent to user {user_id}'
        except Exception as exc:
            log.exception('notification email to user %s failed', user_id)
            return f'failed: {exc}'


def org_defaults_matrix(server_settings):
    """Resolved org-default channel matrix for the admin UI — one row per
    catalog event with the effective in_app/email booleans (stored JSONB
    override -> code default). Single source for every page that renders the
    defaults table (the Settings page used to compute this inline; the
    standalone /manage/notifications page must not drift from it)."""
    nd = server_settings.notification_defaults or {}
    return [{
        'event_type': ev, 'label': label,
        'in_app': bool((nd.get(ev) or {}).get('in_app', _code_default(ev)['in_app'])),
        'email': bool((nd.get(ev) or {}).get('email', _code_default(ev)['email'])),
    } for ev, label in EVENT_CATALOG.items()]

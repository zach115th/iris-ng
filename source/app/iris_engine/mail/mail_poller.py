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

"""The mail-rule ingest poller (iris-ng v2, Phase 1).

Scheduling design — deliberately NOT the updater's mutate-the-beat-schedule
pattern: beat fires task_poll_mailbox_tick at a FIXED 60s cadence, and the task
itself decides whether to do anything (ingest enabled? interval elapsed?).
Settings changes therefore take effect within one tick with no restart and no
cross-process beat mutation (the updater's runtime add/remove only mutates the
process that runs it, which is not the beat process when toggled from the web
container). The mail_poll_interval_minutes setting is a best-effort minimum
between polls; its floor is the 60s tick.

Concurrency: a Postgres advisory lock (held on ONE dedicated connection —
advisory locks are per-connection and the workers use NullPool, so the lock
must not be taken through the ORM session) guarantees a single poll runs at a
time across all workers. Poll Now enqueues the same task with force=True.

Per-message contract: every processed message gets a MailIngestLog row
whatever the outcome; errors are recorded, never raised past the message loop;
messages are marked \\Seen after handling (success OR logged error) so a
poison message cannot loop forever. Runs on the default 'celery' queue —
light, timeout-bounded I/O; a dedicated queue is the escape hatch if IMAP
latency ever contends with module hooks.
"""

import time
from datetime import datetime

from app import app
from app import celery
from app import db
from app.iris_engine.mail.mail_client import MailClient
from app.models.alerts import MailIngestLog
from app.models.models import ServerSettings

# Arbitrary constant; pg advisory lock namespace for "mail poll running".
_POLL_LOCK_ID = 871_231_001

# Best-effort interval gate (module-global; per worker process). Worst case a
# poll runs early after a worker restart — harmless: UNSEEN + dedup make polls
# idempotent.
_last_poll_ts = 0.0

log = app.logger


def _acquire_poll_lock(conn) -> bool:
    return conn.exec_driver_sql(
        'SELECT pg_try_advisory_lock(%s)' % _POLL_LOCK_ID).scalar()


def _release_poll_lock(conn) -> None:
    try:
        conn.exec_driver_sql('SELECT pg_advisory_unlock(%s)' % _POLL_LOCK_ID)
    except Exception:
        pass


def _already_ingested(parsed: dict) -> bool:
    if parsed.get('message_id'):
        if MailIngestLog.query.filter(
                MailIngestLog.message_id == parsed['message_id']).first():
            return True
        return False
    # No Message-ID: fall back to (imap_uid, folder).
    return MailIngestLog.query.filter(
        MailIngestLog.imap_uid == parsed.get('imap_uid'),
        MailIngestLog.folder == parsed.get('folder')).first() is not None


def _log_row(parsed: dict, outcome: str, rule=None, alert=None,
             error: str = None, ai_triage: dict = None) -> None:
    """Write one audit row. On the duplicate-Message-ID race (two polls,
    UNIQUE violation) downgrade to a rollback — the message was handled."""
    try:
        row = MailIngestLog(
            message_id=parsed.get('message_id'),
            imap_uid=parsed.get('imap_uid'),
            folder=parsed.get('folder'),
            from_addr=parsed.get('from'),
            subject=parsed.get('subject'),
            received_at=(datetime.fromisoformat(parsed['received_at'])
                         if parsed.get('received_at') else None),
            rule_id=rule.id if rule is not None else None,
            outcome=outcome,
            alert_id=alert.alert_id if alert is not None else None,
            error=(error or None),
            ai_triage=ai_triage,
        )
        db.session.add(row)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        log.warning(f'mail ingest: could not write log row for '
                    f'{parsed.get("message_id") or parsed.get("imap_uid")}: {e}')


def _maybe_triage(settings: ServerSettings, parsed: dict):
    """Optional AI triage. Returns (enrichment_for_payload, audit_for_log).
    Fail-soft: any error yields (None, {'error': ...}) and ingest proceeds
    with the rule defaults. Never blocks alert creation."""
    if not settings.mail_ai_triage_enabled:
        return None, None
    try:
        from app.iris_engine.ai.mail_triage import triage_email
        result = triage_email(subject=parsed.get('subject') or '',
                              body=parsed.get('body') or '',
                              from_addr=parsed.get('from') or '')
        return result, result
    except Exception as e:
        log.warning(f'mail ingest: AI triage failed, using rule defaults: {e}')
        return None, {'error': str(e)[:500]}


def _process_message(mc: MailClient, uid: str, settings: ServerSettings) -> None:
    """Handle one message end to end. Never raises."""
    from app.business.alerts_ingest import create_alert_from_payload
    from app.business.mail_rules import build_alert_payload
    from app.business.mail_rules import find_matching_rule

    parsed = None
    try:
        parsed = mc.fetch(uid)

        if _already_ingested(parsed):
            _log_row(parsed, 'duplicate')
            mc.mark_seen(uid)
            return

        rule = find_matching_rule(parsed)
        if rule is None:
            _log_row(parsed, 'no_match')
            mc.mark_seen(uid)
            return

        if rule.action == 'ignore':
            _log_row(parsed, 'ignored', rule=rule)
            mc.mark_seen(uid)
            return

        enrichment, triage_audit = _maybe_triage(settings, parsed)
        payload = build_alert_payload(rule, parsed, triage=enrichment)

        # System ingest: user #1 acts; the rule's customer_id IS the
        # entitlement decision, made by the administrator who saved the rule.
        alert = create_alert_from_payload(payload, user_id=1,
                                          enforce_client_access=False)

        _log_row(parsed, 'alert_created', rule=rule, alert=alert,
                 ai_triage=triage_audit)
        mc.mark_seen(uid)

    except Exception as e:
        db.session.rollback()
        log.exception(f'mail ingest: message uid {uid} failed')
        if parsed is not None:
            _log_row(parsed, 'error', error=str(e)[:2000])
            # Mark seen so a poison message cannot loop the poller forever —
            # the log row is the record of what happened.
            try:
                mc.mark_seen(uid)
            except Exception:
                pass


def poll_mailbox(force: bool = False) -> str:
    """One poll cycle. Returns a short human summary (task result)."""
    global _last_poll_ts

    settings = db.session.query(ServerSettings).first()
    if settings is None or not settings.mail_ingest_enabled:
        return 'mail ingest disabled'
    if not settings.mail_imap_host or not settings.mail_imap_username:
        return 'mail ingest enabled but IMAP is not configured'
    if not force and settings.mail_poll_interval_minutes is None:
        return 'polling disabled (no interval set); use Poll Now'

    if not force:
        interval_s = max(60, int(settings.mail_poll_interval_minutes) * 60)
        if time.monotonic() - _last_poll_ts < interval_s:
            return 'interval not elapsed'

    lock_conn = db.engine.connect()
    try:
        if not _acquire_poll_lock(lock_conn):
            return 'another poll is running'

        _last_poll_ts = time.monotonic()
        handled = 0
        with MailClient(settings.mail_imap_host, settings.mail_imap_port,
                        settings.mail_imap_username, settings.mail_imap_password,
                        use_ssl=bool(settings.mail_imap_ssl),
                        folder=settings.mail_imap_folder or 'INBOX') as mc:
            uids = mc.unseen_uids(limit=50)
            for uid in uids:
                _process_message(mc, uid, settings)
                handled += 1
        return f'polled {settings.mail_imap_folder or "INBOX"}: {handled} message(s) handled'
    finally:
        _release_poll_lock(lock_conn)
        lock_conn.close()


@celery.task(bind=True)
def task_poll_mailbox(self, force: bool = False):
    """Celery entry point (beat tick + Poll Now)."""
    with app.app_context():
        try:
            summary = poll_mailbox(force=force)
            log.info(f'mail poll: {summary}')
            return summary
        except Exception as e:
            db.session.rollback()
            log.exception('mail poll cycle failed')
            return f'mail poll failed: {str(e)[:500]}'


@celery.on_after_finalize.connect
def setup_mail_poll_tick(sender, **kwargs):
    """Fixed 60s tick; the task itself gates on settings. Registered
    unconditionally so no runtime beat mutation is ever needed."""
    sender.add_periodic_task(60.0, task_poll_mailbox.s(),
                             name='iris_mail_poll_tick')

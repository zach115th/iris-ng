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

"""Stdlib SMTP sender. Consumed by the Phase 5 notification email channel and
by the settings tab's connection test. Reads config from the ServerSettings
ORM row (the dumped settings dict deliberately excludes the password)."""

import smtplib
import ssl
from email.message import EmailMessage

from app.models.models import ServerSettings

_SOCKET_TIMEOUT = 30


def _smtp_connection(settings: ServerSettings):
    host = settings.mail_smtp_host
    security = settings.mail_smtp_security or 'tls'
    port = int(settings.mail_smtp_port or (465 if security == 'tls' else 587))

    if security == 'tls':
        conn = smtplib.SMTP_SSL(host, port, timeout=_SOCKET_TIMEOUT,
                                context=ssl.create_default_context())
    else:
        conn = smtplib.SMTP(host, port, timeout=_SOCKET_TIMEOUT)
        if security == 'starttls':
            conn.starttls(context=ssl.create_default_context())
    if settings.mail_smtp_username:
        conn.login(settings.mail_smtp_username, settings.mail_smtp_password or '')
    return conn


def send_email(settings: ServerSettings, to: str, subject: str,
               text_body: str, html_body: str = None) -> None:
    """Send one email. Raises on failure — callers (the Phase 5 notification
    celery task) decide their own retry/log policy; nothing in the ingest path
    ever calls this."""
    if not settings.mail_smtp_host:
        raise RuntimeError('SMTP is not configured (mail_smtp_host is empty)')

    msg = EmailMessage()
    msg['From'] = settings.mail_smtp_from_addr or settings.mail_smtp_username or 'iris-ng@localhost'
    msg['To'] = to
    msg['Subject'] = subject
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype='html')

    with _smtp_connection(settings) as conn:
        conn.send_message(msg)


def test_connection(settings: ServerSettings) -> dict:
    """Handshake + auth check (no mail sent). Never raises."""
    try:
        if not settings.mail_smtp_host:
            return {'ok': False, 'detail': 'SMTP host is not configured'}
        with _smtp_connection(settings) as conn:
            conn.noop()
        return {'ok': True, 'detail': 'connected and authenticated'}
    except Exception as e:
        return {'ok': False, 'detail': str(e)[:500]}

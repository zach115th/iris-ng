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

"""Stdlib IMAP client for the mail-rule poller. Fetches UNSEEN messages with
BODY.PEEK (fetching must not mark anything seen — only successful handling
does), parses them into plain dicts, and marks them seen explicitly."""

import email
import email.policy
import imaplib
import re
import socket
from datetime import timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

# One slow mailbox must not stall a poll forever.
_SOCKET_TIMEOUT = 30

# Caps applied at parse time. Headers are small; bodies can be arbitrarily
# large — 64 KB is more than any matching/triage use needs.
_HEADER_CAP = 1024
_BODY_CAP = 65536


class _HtmlToText(HTMLParser):
    """Minimal HTML→text for messages with no text/plain part."""

    _SKIP = {'script', 'style', 'head'}

    def __init__(self):
        super().__init__()
        self._chunks = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in ('br', 'p', 'div', 'tr', 'li'):
            self._chunks.append('\n')

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self._chunks.append(data)

    def text(self):
        return re.sub(r'\n{3,}', '\n\n', ''.join(self._chunks)).strip()


def _html_to_text(html: str) -> str:
    parser = _HtmlToText()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # A malformed document still yields whatever was parsed so far.
        pass
    return parser.text()


def _extract_body(msg) -> str:
    """Prefer text/plain; fall back to text/html stripped to text."""
    plain, html = None, None
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            ctype = part.get_content_type()
            try:
                content = part.get_content()
            except Exception:
                continue
            if not isinstance(content, str):
                continue
            if ctype == 'text/plain' and plain is None:
                plain = content
            elif ctype == 'text/html' and html is None:
                html = content
    else:
        try:
            content = msg.get_content()
            if isinstance(content, str):
                if msg.get_content_type() == 'text/html':
                    html = content
                else:
                    plain = content
        except Exception:
            pass
    if plain is not None:
        return plain[:_BODY_CAP]
    if html is not None:
        return _html_to_text(html)[:_BODY_CAP]
    return ''


def parse_message(raw: bytes, imap_uid: str, folder: str) -> dict:
    """Parse a raw RFC822 message into the plain dict the rule engine and the
    alert-payload builder consume."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)

    received_at = None
    try:
        date_hdr = msg.get('Date')
        if date_hdr:
            dt = parsedate_to_datetime(date_hdr)
            if dt is not None:
                # Store naive UTC, matching the project convention.
                if dt.tzinfo is not None:
                    dt = dt.astimezone(tz=timezone.utc).replace(tzinfo=None)
                received_at = dt.isoformat()
    except Exception:
        received_at = None

    return {
        'imap_uid': imap_uid,
        'folder': folder,
        'message_id': (msg.get('Message-ID') or '').strip()[:_HEADER_CAP] or None,
        'from': str(msg.get('From') or '')[:_HEADER_CAP],
        'to': str(msg.get('To') or '')[:_HEADER_CAP],
        'subject': str(msg.get('Subject') or '')[:_HEADER_CAP],
        'received_at': received_at,
        'body': _extract_body(msg),
    }


class MailClient:
    """Thin context-managed wrapper around imaplib for one poll cycle."""

    def __init__(self, host, port, username, password, use_ssl=True, folder='INBOX'):
        self._host = host
        self._port = int(port or (993 if use_ssl else 143))
        self._username = username
        self._password = password
        self._use_ssl = use_ssl
        self.folder = folder or 'INBOX'
        self._conn = None

    def __enter__(self):
        socket.setdefaulttimeout(_SOCKET_TIMEOUT)
        cls = imaplib.IMAP4_SSL if self._use_ssl else imaplib.IMAP4
        self._conn = cls(self._host, self._port)
        self._conn.login(self._username, self._password)
        typ, _ = self._conn.select(self.folder)
        if typ != 'OK':
            raise RuntimeError(f"cannot select folder {self.folder!r}")
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn.logout()
        except Exception:
            pass
        return False

    def unseen_uids(self, limit=50) -> list:
        """UIDs of unseen messages, oldest first, capped per poll cycle so a
        mailbox backlog is drained across cycles rather than in one giant one."""
        typ, data = self._conn.uid('SEARCH', None, 'UNSEEN')
        if typ != 'OK':
            raise RuntimeError('UNSEEN search failed')
        uids = (data[0] or b'').split()
        return [u.decode() for u in uids[:limit]]

    def fetch(self, uid: str) -> dict:
        """Fetch one message WITHOUT setting \\Seen (BODY.PEEK)."""
        typ, data = self._conn.uid('FETCH', uid, '(BODY.PEEK[])')
        if typ != 'OK' or not data or data[0] is None:
            raise RuntimeError(f'fetch of uid {uid} failed')
        raw = data[0][1]
        return parse_message(raw, imap_uid=uid, folder=self.folder)

    def mark_seen(self, uid: str) -> None:
        self._conn.uid('STORE', uid, '+FLAGS', '(\\Seen)')


def test_connection(host, port, username, password, use_ssl=True, folder='INBOX') -> dict:
    """Handshake check for the settings tab. Never raises."""
    try:
        with MailClient(host, port, username, password, use_ssl=use_ssl, folder=folder) as mc:
            uids = mc.unseen_uids(limit=1)
        return {'ok': True, 'detail': f'connected; folder {folder!r} selectable; '
                                      f'{"unseen mail present" if uids else "no unseen mail"}'}
    except Exception as e:
        return {'ok': False, 'detail': str(e)[:500]}

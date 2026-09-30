#!/usr/bin/env python3
#
#  IRIS Source Code
#  Copyright (C) 2026 - IRIS-NG contributors
#  contact@dfir-iris.org
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

"""War-room guests (iris-ng, maintainer decisions 2026-09-30).

A guest is an out-of-band participant — the affected entity's contact, a
partner agency — invited into ONE war room. Guests are never `user` rows:
they cannot log in at /login, hold no permissions, have no case access and
cannot reach any route outside the room. They enter through the guest
portal (`/portal/join/<secret>`), which turns a valid invitation into a
portal session bound to (guest_id, room_id); the room API then treats the
guest as a `responder`-level participant on the routes explicitly opened
to guests (see `ac_room_api_requires` / `_resolve(guests=True)`), and denies
everything else by default.

Invitations: a random secret (shown ONCE — only its sha256 is stored),
emailed through the existing SMTP path when it is configured and always
handed back to the lead for copy/paste. Lifetime: `expires_at` (default 14
days, extendable), `revoked_at`, and the room's `closed` status; any of the
three ends access on the next request. "New link" rotates the secret (the
old one dies) — there is no way to re-display a secret.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import string
import time
from datetime import datetime
from datetime import timedelta

import app
from app import bc
from app import celery
from app import db
from app.business.errors import BusinessProcessingError
from app.models.models import ServerSettings
from app.models.models import WarRoom
from app.models.models import WarRoomGuest

log = app.app.logger

DEFAULT_TTL_DAYS = 14
MAX_TTL_DAYS = 90
GUEST_ROLE = 'responder'
_SECRET_BYTES = 32


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode('utf-8')).hexdigest()


def _norm_email(email: str) -> str:
    e = (email or '').strip().lower()
    if not e or '@' not in e or ' ' in e or len(e) > 254:
        raise BusinessProcessingError('A valid email address is required')
    return e


def _ttl_days(days) -> int:
    try:
        d = int(days) if days not in (None, '') else DEFAULT_TTL_DAYS
    except (TypeError, ValueError):
        raise BusinessProcessingError('Invalid number of days')
    if d < 1 or d > MAX_TTL_DAYS:
        raise BusinessProcessingError(f'Days must be between 1 and {MAX_TTL_DAYS}')
    return d


def guest_status(g: WarRoomGuest, room: WarRoom | None = None) -> str:
    """active | expired | revoked | closed (room) — computed, never stored."""
    room = room or db.session.get(WarRoom, g.room_id)
    if g.revoked_at is not None:
        return 'revoked'
    if room is not None and room.status == 'closed':
        return 'closed'
    if g.expires_at is not None and g.expires_at <= datetime.utcnow():
        return 'expired'
    return 'active'


def guest_is_active(g: WarRoomGuest | None, room: WarRoom | None = None) -> bool:
    return g is not None and guest_status(g, room) == 'active'


def list_guests(room: WarRoom) -> list[WarRoomGuest]:
    return (WarRoomGuest.query.filter_by(room_id=room.id)
            .order_by(WarRoomGuest.id.asc()).all())


def get_guest(room: WarRoom, guest_id) -> WarRoomGuest:
    g = db.session.get(WarRoomGuest, int(guest_id))
    if g is None or g.room_id != room.id:
        raise BusinessProcessingError('Invalid guest')
    return g


def guest_from_secret(secret: str) -> WarRoomGuest | None:
    if not secret or len(secret) > 128:
        return None
    return WarRoomGuest.query.filter_by(token_hash=_hash(secret)).first()


# ------------------------------------------------------------------- handles
#
# The @-mention handle (maintainer decision 2026-09-30): minted from the display
# name ("Zach C" -> zach-c, a clash gets -2, -3, ...), unique per room, editable
# by a lead. Same charset as user logins and team names so the palette, the
# highlighter and the mention scanners share one token shape.

HANDLE_RE = re.compile(r'^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$')


def slugify_handle(name: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', (name or '').lower()).strip('-')
    s = re.sub(r'-{2,}', '-', s)[:60].strip('-')
    return s or 'guest'


def assign_handle(g: WarRoomGuest, wanted: str | None = None) -> str:
    """Give the guest a unique handle in its room (session only — the caller
    commits). `wanted` must already be a valid handle; None derives one."""
    base = wanted or slugify_handle(g.display_name)
    candidate = base
    n = 2
    while True:
        clash = (WarRoomGuest.query.filter(WarRoomGuest.room_id == g.room_id,
                                           WarRoomGuest.handle == candidate,
                                           WarRoomGuest.id != (g.id or -1)).first())
        if clash is None:
            g.handle = candidate
            return candidate
        if wanted:
            raise BusinessProcessingError('That handle is already used in this room')
        candidate = f'{base[:58]}-{n}'
        n += 1


def guest_handle(g: WarRoomGuest) -> str:
    """The handle, minted on first read for guests that predate the column."""
    if not g.handle:
        assign_handle(g)
        db.session.commit()
    return g.handle


def set_guest_handle(room: WarRoom, guest_id, handle: str | None) -> WarRoomGuest:
    """Lead edit. Blank derives it again from the display name."""
    g = get_guest(room, guest_id)
    h = (handle or '').strip().lower().lstrip('@')
    if h and not HANDLE_RE.match(h):
        raise BusinessProcessingError(
            'Handle: letters, digits, dots, hyphens and underscores; no spaces (e.g. jane-doe)')
    assign_handle(g, h or None)
    db.session.commit()
    return g


def active_guests_by_handle(room: WarRoom) -> dict:
    """{handle: guest} for the room's ACTIVE guests — what a mention may reach."""
    out = {}
    for g in list_guests(room):
        if guest_is_active(g, room):
            out[guest_handle(g)] = g
    return out


def create_guest(room: WarRoom, actor_id: int, email: str, display_name: str,
                 organisation: str | None = None, days=None,
                 password: str | None = None) -> tuple[WarRoomGuest, str, str]:
    """Create the guest and return (row, SECRET, PASSWORD). Neither is stored
    in clear; both are shown to the lead once and emailed to the guest."""
    if room.status == 'closed':
        raise BusinessProcessingError('Room is closed')
    email = _norm_email(email)
    name = (display_name or '').strip()
    if not name:
        raise BusinessProcessingError('A display name is required')
    if WarRoomGuest.query.filter_by(room_id=room.id, email=email).first():
        raise BusinessProcessingError('This email is already invited to this room')
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    g = WarRoomGuest(room_id=room.id, email=email, display_name=name[:120],
                     organisation=((organisation or '').strip() or None),
                     token_hash=_hash(secret), invited_by=actor_id,
                     expires_at=datetime.utcnow() + timedelta(days=_ttl_days(days)))
    db.session.add(g)
    db.session.flush()
    assign_handle(g)
    plain = set_guest_password(g, password)
    db.session.commit()
    return g, secret, plain


# ------------------------------------------------------------------ passwords
#
# Email + password are the guest's credential (maintainer decision, 2026-09-30):
# the invitation link only pre-fills the sign-in and pins the room. Generated
# passwords are 16 letters/digits; a lead-set password must satisfy the
# instance's own password policy (Server settings). Hashing = the users' bcrypt.

PASSWORD_ALPHABET = string.ascii_letters + string.digits
GENERATED_PASSWORD_LENGTH = 16
LOCKOUT_ATTEMPTS = 10
LOCKOUT_MINUTES = 15


def generate_password() -> str:
    return ''.join(secrets.choice(PASSWORD_ALPHABET) for _ in range(GENERATED_PASSWORD_LENGTH))


def password_policy_errors(pw: str, s: ServerSettings | None = None) -> list[str]:
    """The instance policy (Server settings → Security), applied to a
    lead-set guest password. Empty list = acceptable."""
    s = s or ServerSettings.query.first()
    errs = []
    try:
        min_len = int(getattr(s, 'password_policy_min_length', None) or 0) if s else 0
    except (TypeError, ValueError):
        min_len = 0
    min_len = max(min_len, 8)
    if len(pw) < min_len:
        errs.append(f'at least {min_len} characters')
    if s and s.password_policy_upper_case and not re.search(r'[A-Z]', pw):
        errs.append('an upper-case letter')
    if s and s.password_policy_lower_case and not re.search(r'[a-z]', pw):
        errs.append('a lower-case letter')
    if s and s.password_policy_digit and not re.search(r'[0-9]', pw):
        errs.append('a digit')
    specials = (getattr(s, 'password_policy_special_chars', None) or '') if s else ''
    if specials and not any(c in specials for c in pw):
        errs.append(f'one of {specials}')
    return errs


def set_guest_password(g: WarRoomGuest, plain: str | None = None) -> str:
    """Store a new password (generated when `plain` is empty) and clear the
    lockout. Session-only: the caller commits. Returns the clear text ONCE."""
    plain = (plain or '').strip()
    if plain:
        errs = password_policy_errors(plain)
        if errs:
            raise BusinessProcessingError('Password policy: needs ' + ', '.join(errs))
    else:
        plain = generate_password()
    g.password_hash = bc.generate_password_hash(plain.encode('utf-8')).decode('utf-8')
    g.password_set_at = datetime.utcnow()
    g.failed_logins = 0
    g.locked_until = None
    return plain


def reset_guest_password(room: WarRoom, guest_id, plain: str | None = None) -> tuple[WarRoomGuest, str]:
    g = get_guest(room, guest_id)
    if room.status == 'closed':
        raise BusinessProcessingError('Room is closed')
    new = set_guest_password(g, plain)
    db.session.commit()
    return g, new


def check_guest_password(g: WarRoomGuest, plain: str) -> tuple[bool, str, int]:
    """(ok, reason, minutes_left). reason: ok | bad | locked | none. A
    failure counts against the lockout; success clears it. Commits."""
    now = datetime.utcnow()
    if g.locked_until and g.locked_until > now:
        return False, 'locked', max(1, int((g.locked_until - now).total_seconds() // 60) + 1)
    if not g.password_hash or not plain:
        return False, 'none', 0
    ok = False
    try:
        ok = bool(bc.check_password_hash(g.password_hash, (plain or '').encode('utf-8')))
    except ValueError:
        ok = False
    if ok:
        g.failed_logins = 0
        g.locked_until = None
        db.session.commit()
        return True, 'ok', 0
    g.failed_logins = int(g.failed_logins or 0) + 1
    if g.failed_logins >= LOCKOUT_ATTEMPTS:
        g.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
        g.failed_logins = 0
        db.session.commit()
        return False, 'locked', LOCKOUT_MINUTES
    db.session.commit()
    return False, 'bad', 0


def guest_for_login(*, secret: str | None = None, slug: str | None = None,
                    email: str | None = None) -> WarRoomGuest | None:
    """Resolve the guest a sign-in refers to: by invitation secret (the
    email must match it) or by room slug + email. None means 'no such
    guest' — the caller answers the same way as for a bad password."""
    e = (email or '').strip().lower()
    if not e:
        return None
    if secret:
        g = guest_from_secret(secret)
        return g if (g is not None and g.email == e) else None
    if slug:
        from app.business.war_rooms import get_room_by_slug
        room = get_room_by_slug((slug or '').lower())
        if room is None:
            return None
        return WarRoomGuest.query.filter_by(room_id=room.id, email=e).first()
    return None


def rotate_secret(room: WarRoom, guest_id) -> tuple[WarRoomGuest, str]:
    """New link: a fresh secret, the old one dies. Un-revokes and, when the
    guest had expired, restarts the default lifetime — a lead who asks for
    a new link wants the guest back in."""
    g = get_guest(room, guest_id)
    if room.status == 'closed':
        raise BusinessProcessingError('Room is closed')
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    g.token_hash = _hash(secret)
    g.revoked_at = None
    if g.expires_at is None or g.expires_at <= datetime.utcnow():
        g.expires_at = datetime.utcnow() + timedelta(days=DEFAULT_TTL_DAYS)
    db.session.commit()
    return g, secret


def revoke_guest(room: WarRoom, guest_id) -> WarRoomGuest:
    g = get_guest(room, guest_id)
    if g.revoked_at is None:
        g.revoked_at = datetime.utcnow()
        db.session.commit()
    return g


def extend_guest(room: WarRoom, guest_id, days=None) -> WarRoomGuest:
    g = get_guest(room, guest_id)
    if room.status == 'closed':
        raise BusinessProcessingError('Room is closed')
    base = max(g.expires_at or datetime.utcnow(), datetime.utcnow())
    g.expires_at = base + timedelta(days=_ttl_days(days))
    db.session.commit()
    return g


def delete_guest(room: WarRoom, guest_id) -> None:
    g = get_guest(room, guest_id)
    db.session.delete(g)
    db.session.commit()


def touch_seen(g: WarRoomGuest) -> None:
    """Called on portal entry; `first_seen_at` is what the stream's System
    lane derives "joined" from. Fail-soft: a bookkeeping write never blocks
    the request."""
    try:
        now = datetime.utcnow()
        if g.first_seen_at is None:
            g.first_seen_at = now
        g.last_seen_at = now
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        log.exception('guest touch_seen failed (guest=%s)', g.id)


# ---------------------------------------------------------------- invitation

def portal_base_url(request_url_root: str | None = None) -> str:
    """The base URL guests use: Settings → portal_public_url (the tunnel
    hostname) when set, else the origin the BROWSER used (nginx forwards it
    as X-Forwarded-Host; the request's own url_root is the proxied app socket,
    `app:8000`, which no guest can reach)."""
    return portal_base(request_url_root)[0]


def portal_base(request_url_root: str | None = None) -> tuple[str, str]:
    """(base_url, source) with source in settings | tunnel | browser."""
    s = ServerSettings.query.first()
    base = (getattr(s, 'portal_public_url', None) or '').strip() if s else ''
    if base:
        return base.rstrip('/'), 'settings'
    reported = agent_reported_url(s)
    if reported:
        return reported.rstrip('/'), 'tunnel'
    tunnel = quick_tunnel_url()
    if tunnel:
        return tunnel.rstrip('/'), 'tunnel'
    return _browser_origin(request_url_root).rstrip('/'), 'browser'


# ------------------------------------------------------ portal tunnel agent
#
# The tunnel runs in its own container (docker/tunnel): cloudflared plus a
# loop that asks IRIS which mode to run and reports back. Auth is a shared
# key from .env (PORTAL_TUNNEL_AGENT_KEY) compared in constant time; without
# the key the agent endpoints do not exist (404).

TUNNEL_MODES = ('quick', 'named')
AGENT_KEY_ENV = 'PORTAL_TUNNEL_AGENT_KEY'
AGENT_FRESH_SECONDS = 120


def agent_key_configured() -> bool:
    return bool((os.environ.get(AGENT_KEY_ENV) or '').strip())


def agent_key_ok(presented: str | None) -> bool:
    import hmac
    key = (os.environ.get(AGENT_KEY_ENV) or '').strip()
    if not key or not presented:
        return False
    return hmac.compare_digest(key, presented.strip())


def tunnel_settings(s: ServerSettings | None = None) -> dict:
    s = s or ServerSettings.query.first()
    mode = (getattr(s, 'portal_tunnel_mode', None) or 'quick') if s else 'quick'
    return {
        'mode': mode if mode in TUNNEL_MODES else 'quick',
        'public_url': ((getattr(s, 'portal_public_url', None) or '').strip() if s else ''),
        'token_set': bool(s and (getattr(s, 'portal_tunnel_token', None) or '').strip()),
        'agent_key_configured': agent_key_configured(),
    }


def update_tunnel_settings(mode=None, public_url=None, token=None) -> dict:
    """Admin save. `token` is write-only: None / '' / the mask keep the stored
    value; a value replaces it; the literal 'clear' empties it."""
    s = ServerSettings.query.first()
    if s is None:
        raise BusinessProcessingError('Server settings row is missing')
    if mode is not None:
        if mode not in TUNNEL_MODES:
            raise BusinessProcessingError('Tunnel mode must be quick or named')
        s.portal_tunnel_mode = mode
    if public_url is not None:
        u = (public_url or '').strip().rstrip('/')
        if u and not re.match(r'^https?://[a-z0-9.-]+(:\d+)?$', u, flags=re.I):
            raise BusinessProcessingError('Public URL must look like https://rooms.example.com')
        s.portal_public_url = u or None
    if token is not None and token not in ('', '********'):
        s.portal_tunnel_token = None if token == 'clear' else token.strip()
    if (s.portal_tunnel_mode == 'named' and not (s.portal_tunnel_token or '').strip()):
        raise BusinessProcessingError('Named mode needs the tunnel token from Zero Trust')
    db.session.commit()
    return tunnel_settings(s)


def tunnel_config_for_agent() -> dict:
    """What the agent needs to run; the token travels ONLY here."""
    s = ServerSettings.query.first()
    cfg = tunnel_settings(s)
    out = {'mode': cfg['mode'], 'public_url': cfg['public_url'],
           'portal_port': int(os.environ.get('PORTAL_PORT') or 8081)}
    if cfg['mode'] == 'named':
        out['token'] = (getattr(s, 'portal_tunnel_token', None) or '').strip() if s else ''
    return out


def store_tunnel_status(payload: dict) -> dict:
    """The agent's heartbeat. Only known keys are kept, and only as scalars."""
    s = ServerSettings.query.first()
    if s is None:
        raise BusinessProcessingError('Server settings row is missing')
    keep = {}
    for k in ('mode', 'connected', 'hostname', 'version', 'error', 'agent'):
        v = payload.get(k)
        if isinstance(v, (str, bool, int)) or v is None:
            keep[k] = (v[:500] if isinstance(v, str) else v)
    keep['reported_at'] = datetime.utcnow().isoformat()
    s.portal_tunnel_status = keep
    db.session.commit()
    return keep


def tunnel_status(s: ServerSettings | None = None) -> dict:
    """Status for the settings page: the agent's last report plus freshness."""
    s = s or ServerSettings.query.first()
    st = dict((getattr(s, 'portal_tunnel_status', None) or {}) if s else {})
    fresh = False
    if st.get('reported_at'):
        try:
            fresh = (datetime.utcnow() - datetime.fromisoformat(st['reported_at'])).total_seconds() < AGENT_FRESH_SECONDS
        except ValueError:
            fresh = False
    st['agent_seen'] = fresh
    return st


def agent_reported_url(s: ServerSettings | None = None) -> str:
    """Hostname the agent last reported while connected and fresh; the quick
    tunnel's random name in quick mode."""
    st = tunnel_status(s)
    host = (st.get('hostname') or '').strip().lower()
    if st.get('agent_seen') and st.get('connected') and host and re.fullmatch(r'[a-z0-9.-]+', host):
        return f'https://{host}'
    return ''


def portal_base_is_configured() -> bool:
    return portal_base()[1] != 'browser'


# Quick-tunnel discovery: cloudflared's metrics endpoint answers /quicktunnel
# with {"hostname": "<random>.trycloudflare.com"}. Reached on the docker
# network only; a 60 s cache keeps the invite modal snappy and a dead
# endpoint costs one short timeout per minute.
QUICK_TUNNEL_METRICS_URL = os.environ.get('IRIS_PORTAL_TUNNEL_METRICS_URL',
                                          'http://cloudflared:2000/quicktunnel')
_tunnel_cache = {'at': 0.0, 'url': ''}
_TUNNEL_CACHE_SECONDS = 60


def quick_tunnel_url() -> str:
    now = time.monotonic()
    if now - _tunnel_cache['at'] < _TUNNEL_CACHE_SECONDS:
        return _tunnel_cache['url']
    url = ''
    try:
        import json as _json
        import urllib.request
        with urllib.request.urlopen(QUICK_TUNNEL_METRICS_URL, timeout=1.5) as resp:
            host = (_json.loads(resp.read().decode('utf-8') or '{}') or {}).get('hostname') or ''
        host = host.strip().lower()
        if host and re.fullmatch(r'[a-z0-9.-]+', host):
            url = f'https://{host}'
    except Exception:  # noqa: BLE001 — no tunnel is the normal case
        url = ''
    _tunnel_cache.update(at=now, url=url)
    return url


def _browser_origin(request_url_root: str | None) -> str:
    try:
        from flask import request
        host = (request.headers.get('X-Forwarded-Host') or '').split(',')[0].strip()
        if host:
            proto = (request.headers.get('X-Forwarded-Proto') or 'https').split(',')[0].strip()
            return f'{proto}://{host}'
    except RuntimeError:
        pass
    return (request_url_root or '').strip()


def invite_url(secret: str, request_url_root: str | None = None) -> str:
    return f'{portal_base_url(request_url_root)}/portal/join/{secret}'


def serialize_guest(g: WarRoomGuest, room: WarRoom | None = None, *, manage: bool = False) -> dict:
    out = {
        'id': g.id,
        'display_name': g.display_name,
        'organisation': g.organisation,
        'label': g.label,
        'handle': guest_handle(g),
        'status': guest_status(g, room),
        'expires_at': g.expires_at.isoformat() if g.expires_at else None,
        'first_seen_at': g.first_seen_at.isoformat() if g.first_seen_at else None,
        'last_seen_at': g.last_seen_at.isoformat() if g.last_seen_at else None,
        'password_set': bool(g.password_hash),
        'locked': bool(g.locked_until and g.locked_until > datetime.utcnow()),
    }
    if manage:
        out.update({
            'email': g.email,
            'invited_by_name': g.inviter.name if g.inviter else None,
            'created_at': g.created_at.isoformat() if g.created_at else None,
            'revoked_at': g.revoked_at.isoformat() if g.revoked_at else None,
            'invite_sent_at': g.invite_sent_at.isoformat() if g.invite_sent_at else None,
        })
    return out


def smtp_configured() -> bool:
    s = ServerSettings.query.first()
    return bool(s and s.mail_smtp_host)


def queue_invite_email(g: WarRoomGuest, room: WarRoom, url: str, inviter_name: str,
                       password: str | None = None, room_url: str | None = None,
                       kind: str = 'invite') -> bool:
    """Enqueue the invitation (or password-reset) email. Returns False (and
    sends nothing) when SMTP is not configured — the lead then relays the
    link and password by hand. The password rides in the task args only."""
    if not smtp_configured():
        return False
    try:
        task_send_guest_invite.delay(g.id, url, room.name, inviter_name,
                                     password=password, room_url=room_url, kind=kind)
        g.invite_sent_at = datetime.utcnow()
        db.session.commit()
        return True
    except Exception:  # noqa: BLE001 — a broker hiccup must not lose the link
        db.session.rollback()
        log.exception('guest invite enqueue failed (guest=%s)', g.id)
        return False


def room_portal_address(room: WarRoom) -> str:
    """The room's portal address for an email body, from the configured base
    when there is one (Settings, a connected agent, discovery); '' otherwise —
    business code may run without a request, so the browser origin is never
    used here."""
    from app.business.war_rooms import room_slug
    try:
        base, source = portal_base(None)
    except Exception:  # noqa: BLE001
        return ''
    if not base or source == 'browser':
        return ''
    return f'{base}/portal/r/{room_slug(room)}'


def queue_guest_email(g: WarRoomGuest, subject: str, body: str) -> bool:
    """Enqueue a plain notification email to one guest (mention, team mention,
    task assignment, leadership SitRep). Best-effort; False when SMTP is not
    configured or the broker refuses. Never raises."""
    if not smtp_configured():
        return False
    try:
        task_send_guest_email.delay(g.id, subject, body)
        return True
    except Exception:  # noqa: BLE001
        log.exception('guest email enqueue failed (guest=%s)', g.id)
        return False


@celery.task(bind=True)
def task_send_guest_email(self, guest_id, subject, body):
    with app.app.app_context():
        try:
            settings = ServerSettings.query.first()
            if not settings or not settings.mail_smtp_host:
                return 'smtp not configured'
            g = db.session.get(WarRoomGuest, int(guest_id))
            if g is None:
                return 'guest gone'
            from app.iris_engine.mail.mail_sender import send_email
            send_email(settings, g.email, subject, body)
            return f'sent to guest {guest_id}'
        except Exception:  # noqa: BLE001
            log.exception('guest email failed (guest=%s)', guest_id)
            return 'failed'


@celery.task(bind=True)
def task_send_guest_invite(self, guest_id, url, room_name, inviter_name,
                           password=None, room_url=None, kind='invite'):
    """Send one guest invitation or password reset. Best-effort: failures
    are logged, never retried (the lead always has the link and password)."""
    with app.app.app_context():
        try:
            settings = ServerSettings.query.first()
            if not settings or not settings.mail_smtp_host:
                return 'smtp not configured'
            g = db.session.get(WarRoomGuest, int(guest_id))
            if g is None:
                return 'guest gone'
            expires = g.expires_at.strftime('%Y-%m-%d %H:%M UTC') if g.expires_at else 'the room closes'
            from app.iris_engine.mail.mail_sender import send_email
            if kind == 'reset':
                body = (
                    f'Your password for the incident coordination room "{room_name}" was reset '
                    f'by {inviter_name}.\n\n'
                    f'Room address: {room_url or url}\n'
                    f'Sign in with this email address and the new password:\n{password}\n\n'
                    f'Your access is valid until {expires}.\n'
                )
                send_email(settings, g.email, f'[IRIS-NG] New password for "{room_name}"', body)
                return f'reset sent to guest {guest_id}'
            body = (
                f'{inviter_name} invited you to the incident coordination room '
                f'"{room_name}" as a guest.\n\n'
                f'Room address: {room_url or url}\n'
                f'Sign in with this email address ({g.email}) and this password:\n{password}\n\n'
                f'This personal link opens the sign-in with your email filled in — do not '
                f'forward it:\n{url}\n\n'
                f'Your access is valid until {expires}. Nothing outside this room is '
                f'visible to you.\n'
            )
            send_email(settings, g.email, f'[IRIS-NG] Invitation to "{room_name}"', body)
            return f'sent to guest {guest_id}'
        except Exception as exc:  # noqa: BLE001
            log.exception('guest invitation email failed (guest=%s)', guest_id)
            return f'failed: {exc}'

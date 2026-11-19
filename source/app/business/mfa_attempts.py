#  IRIS Source Code
#
#  iris-ng (2026-11-15): the attempt limit and replay guard of the second-factor steps.
#
#  Every code submitted on the MFA verify page, and every code + password submitted on the MFA
#  setup page, is one attempt against the ACCOUNT - a new sign-in does not reset the count. After
#  MFA_MAX_FAILURES failed attempts the second-factor steps are locked for MFA_LOCK_MINUTES; a
#  correct code clears the count, and an administrator's Reset MFA clears the count and the lock.
#  An attempt is reserved with an atomic UPDATE before the code is checked, so parallel requests
#  cannot evaluate more than MFA_MAX_FAILURES codes per lock window.
#
#  A code is accepted once: the TOTP time-step of the last accepted code is stored per account,
#  and a code of that step or an older one is refused (also atomic, so two requests carrying the
#  same code cannot both succeed).
#
#  Times are naive UTC, as everywhere in the schema.

from __future__ import annotations

import binascii
from datetime import datetime, timedelta, timezone

import pyotp
from sqlalchemy import or_, select, update

from app import db
from app.models.authorization import User

MFA_MAX_FAILURES = 10
MFA_LOCK_MINUTES = 15


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _minutes_left(until: datetime | None, now: datetime) -> int:
    if until is None or until <= now:
        return 0
    return max(1, int((until - now).total_seconds() // 60) + 1)


def secret_usable(secret: str | None) -> bool:
    """Can a code ever be checked against this stored secret?

    pyotp (2.12+) refuses a secret that is not Base32 or decodes to fewer than 112 bits. IRIS has
    always generated 160-bit secrets, but an account holding a shorter or damaged one can never
    pass the second factor: its MFA has to be reset by an administrator (Reset MFA), and the
    verification page says so instead of counting wrong codes.
    """
    if not secret:
        return False
    try:
        pyotp.TOTP(secret).byte_secret()
    except (binascii.Error, ValueError, TypeError):
        return False
    return True


def code_step(secret: str | None, token) -> int | None:
    """The TOTP time-step `token` is valid for under `secret` right now, else None.

    Only the current step counts (pyotp's default window). A malformed secret - the setup page
    takes it back from the form - is a wrong code, never an exception.
    """
    token = str(token or '').strip()
    if not secret or not token:
        return None
    now = datetime.now(timezone.utc)
    try:
        totp = pyotp.TOTP(secret)
        step = totp.timecode(now)
        expected = totp.generate_otp(step)
    except (binascii.Error, ValueError, TypeError):
        return None
    return step if pyotp.utils.strings_equal(token, expected) else None


def begin_attempt(user_id: int) -> int:
    """Reserve one second-factor attempt for the account. Commits.

    Returns 0 when the attempt may be checked, else the minutes the lock has left. The attempt
    that would exceed MFA_MAX_FAILURES sets the lock instead of being checked.
    """
    now = _utcnow()
    count = db.session.execute(
        update(User)
        .where(User.id == user_id, or_(User.mfa_locked_until.is_(None), User.mfa_locked_until <= now))
        .values(mfa_failed_attempts=User.mfa_failed_attempts + 1)
        .returning(User.mfa_failed_attempts)
    ).scalar()
    if count is None:
        until = db.session.execute(select(User.mfa_locked_until).where(User.id == user_id)).scalar()
        db.session.commit()
        return _minutes_left(until, now) or MFA_LOCK_MINUTES
    if count > MFA_MAX_FAILURES:
        _lock(user_id, now)
        db.session.commit()
        return MFA_LOCK_MINUTES
    db.session.commit()
    return 0


def attempt_failed(user_id: int) -> int:
    """Record that the reserved attempt failed. Commits. Returns the lock's minutes when this
    failure reached MFA_MAX_FAILURES (the lock starts now), else 0."""
    now = _utcnow()
    locked = db.session.execute(
        update(User)
        .where(User.id == user_id, User.mfa_failed_attempts >= MFA_MAX_FAILURES)
        .values(mfa_locked_until=now + timedelta(minutes=MFA_LOCK_MINUTES), mfa_failed_attempts=0)
        .returning(User.id)
    ).scalar()
    db.session.commit()
    return MFA_LOCK_MINUTES if locked is not None else 0


def accept_code(user_id: int, step: int) -> bool:
    """Accept a correct code of time-step `step`: clears the count and the lock and remembers the
    step. False - nothing changed - when that step or a later one was already accepted (a replayed
    code). Commits."""
    done = db.session.execute(
        update(User)
        .where(User.id == user_id, or_(User.mfa_last_timestep.is_(None), User.mfa_last_timestep < step))
        .values(mfa_failed_attempts=0, mfa_locked_until=None, mfa_last_timestep=step)
        .returning(User.id)
    ).scalar()
    db.session.commit()
    return done is not None


def clear_attempts(user: User) -> None:
    """Forget the count, the lock and the last step (an administrator's Reset MFA, a new secret).
    Session-only: the caller commits."""
    user.mfa_failed_attempts = 0
    user.mfa_locked_until = None
    user.mfa_last_timestep = None


def _lock(user_id: int, now: datetime) -> None:
    db.session.execute(
        update(User)
        .where(User.id == user_id)
        .values(mfa_locked_until=now + timedelta(minutes=MFA_LOCK_MINUTES), mfa_failed_attempts=0)
    )

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
"""Password hashing with bcrypt (replaces Flask-Bcrypt).

bcrypt only ever uses the first 72 bytes of a password. Up to bcrypt 4.x the
library dropped the rest silently; bcrypt 5.0 raises ``ValueError`` instead,
which made setting a longer password - and logging in with one whose hash was
made before - fail with an error. This keeps the old behaviour exactly: the
password is cut to its first 72 bytes before hashing and before checking, so
every hash made by bcrypt 4.x still verifies and a long password works again.

Drop-in for the two methods IRIS calls on ``app.bc`` (same names, arguments
and return values as Flask-Bcrypt 1.0.1; ``BCRYPT_LOG_ROUNDS`` and
``BCRYPT_HASH_PREFIX`` are still read from the app config, defaults 12 / 2b).
Imports nothing from ``app`` - ``app/__init__.py`` builds it.
"""

import hmac

import bcrypt

# bcrypt's own limit; everything past it never took part in a hash.
BCRYPT_MAX_PASSWORD_BYTES = 72


def _to_bytes(value):
    if isinstance(value, str):
        return value.encode('utf-8')
    return value


def _fit(password):
    return password[:BCRYPT_MAX_PASSWORD_BYTES]


class PasswordHasher:
    """bcrypt hashing / checking for user and guest passwords."""

    def __init__(self, app=None):
        self._log_rounds = 12
        self._prefix = '2b'
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        self._log_rounds = app.config.get('BCRYPT_LOG_ROUNDS', 12)
        self._prefix = app.config.get('BCRYPT_HASH_PREFIX', '2b')

    def generate_password_hash(self, password, rounds=None, prefix=None):
        """Return the bcrypt hash (bytes) of ``password`` (str or bytes)."""
        if not password:
            raise ValueError('Password must be non-empty.')
        rounds = self._log_rounds if rounds is None else rounds
        prefix = _to_bytes(self._prefix if prefix is None else prefix)
        salt = bcrypt.gensalt(rounds=rounds, prefix=prefix)
        return bcrypt.hashpw(_fit(_to_bytes(password)), salt)

    def check_password_hash(self, pw_hash, password):
        """True when ``password`` matches ``pw_hash``; compared in constant time."""
        pw_hash = _to_bytes(pw_hash)
        password = _fit(_to_bytes(password))
        return hmac.compare_digest(bcrypt.hashpw(password, pw_hash), pw_hash)

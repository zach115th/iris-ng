"""First-boot generation of server secrets that must not ship as public defaults.

`.env.model`, the Helm `values.yaml` and the EKS manifests all shipped a working
`IRIS_SECRET_KEY` of `AVerySuperSecretKey-SoNotThisOne`. SECRET_KEY signs the
Flask session cookie, and the repository is public -- so an install that never
edited that file could have a session forged for any user, administrator
included, with no password and no MFA. Nothing in the application detected it.

Rather than refusing to boot (which would break every existing deployment on
upgrade), a placeholder is replaced with a generated value that is persisted in
the database, so every process and replica agrees on it.

Consequence worth knowing: on the first boot after this lands, an install that
was running the placeholder gets a new key, which invalidates existing session
cookies once. Users log in again. That is the intended outcome -- those sessions
were signed with a public key.

An explicitly configured key always wins; this never overrides an operator.
"""

import secrets

from sqlalchemy.exc import IntegrityError

from app.models.models import RuntimeSecret

# Values shipped in the repo, plus the "you forgot to edit this" sentinel used
# by .env.model. Anything matching is treated as unset.
_PLACEHOLDERS = {
    'AVerySuperSecretKey-SoNotThisOne',
    'ARandomSalt-NotThisOneEither',
    '__MUST_BE_CHANGED__',
    'ChangeMe',
    '',
}

_SECRET_KEY_NAME = 'iris_secret_key'
_PASSWORD_SALT_NAME = 'iris_security_password_salt'


def _is_placeholder(value) -> bool:
    return value is None or str(value).strip() in _PLACEHOLDERS


def _get_or_create(db, name: str) -> str:
    """Return the stored secret, generating and persisting one if absent.

    Race-safe by construction: `name` is UNIQUE, so when replicas start together
    exactly one INSERT succeeds and the others fall into the IntegrityError path
    and adopt the winner's value. Generating per process would mean a session
    signed by one replica is rejected by the next.
    """
    existing = RuntimeSecret.query.filter(RuntimeSecret.name == name).first()
    if existing and existing.value:
        return existing.value

    candidate = secrets.token_urlsafe(48)
    try:
        db.session.add(RuntimeSecret(name=name, value=candidate))
        db.session.commit()
        return candidate
    except IntegrityError:
        # Another process inserted first -- take theirs, never overwrite.
        db.session.rollback()
        winner = RuntimeSecret.query.filter(RuntimeSecret.name == name).first()
        if winner and winner.value:
            return winner.value
        raise


def resolve_server_secrets(app, db, log=None) -> None:
    """Replace placeholder secrets with generated, persisted ones.

    Called from run_post_init(), which is after db.create_all() and the alembic
    upgrade, so `runtime_secret` is guaranteed to exist, and before the app
    serves its first request, so no cookie is ever signed with a placeholder.
    """
    # Workers do not load SECRET_KEY at all (see configuration.py), so there is
    # nothing to resolve for them.
    if 'SECRET_KEY' not in app.config:
        return

    if _is_placeholder(app.config.get('SECRET_KEY')):
        app.config['SECRET_KEY'] = _get_or_create(db, _SECRET_KEY_NAME)
        if log:
            log.warning(
                'IRIS_SECRET_KEY was the shipped placeholder. A unique key has '
                'been generated and stored; existing sessions are invalidated '
                'once. Set IRIS_SECRET_KEY explicitly to manage it yourself.'
            )

    # SECURITY_PASSWORD_SALT is loaded by configuration.py but is not currently
    # read anywhere -- password hashing uses bcrypt, which generates its own
    # per-password salt. Rotating it is therefore harmless today, and giving it
    # a per-install value means it is not a public constant if something starts
    # using it later. It does NOT affect existing passwords.
    if _is_placeholder(app.config.get('SECURITY_PASSWORD_SALT')):
        app.config['SECURITY_PASSWORD_SALT'] = _get_or_create(db, _PASSWORD_SALT_NAME)

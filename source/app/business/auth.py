from urllib.parse import urlparse

from flask import session, redirect, url_for, request
from flask_login import login_user

from app import bc, app, db
from app.datamgmt.manage.manage_srv_settings_db import get_server_settings_as_dict
from app.datamgmt.manage.manage_users_db import get_active_user_by_login
from app.iris_engine.access_control.ldap_handler import ldap_authenticate
from app.iris_engine.access_control.utils import ac_get_effective_permissions_of_user
from app.iris_engine.utils.tracker import track_activity
from app.models.cases import Cases
from app.schema.marshables import UserSchema

log = app.logger

def _retrieve_user_by_username(username:str):
    """
    Retrieve the user object by username.

    :param username: Username
    :return: User object if found, None
    """
    user = get_active_user_by_login(username)
    if not user:
        track_activity(f'someone tried to log in with user \'{username}\', which does not exist',
                       ctx_less=True, display_in_ui=False)
    return user

def validate_ldap_login(username: str, password:str, local_fallback: bool = True):
    """
    Validate the user login using LDAP authentication.

    :param username: Username
    :param password: Password
    :param local_fallback: If True, will fallback to local authentication if LDAP fails.
    :return: User object if successful, None otherwise
    """
    try:
        if ldap_authenticate(username, password) is False:
            if local_fallback is True:
                track_activity(f'wrong login password for user \'{username}\' using LDAP auth - falling back to local based on settings',
                               ctx_less=True, display_in_ui=False)
                return validate_local_login(username, password)
            track_activity(f'wrong login password for user \'{username}\' using LDAP auth', ctx_less=True, display_in_ui=False)
            return None

        user = _retrieve_user_by_username(username)
        if not user:
            return None

        return UserSchema(exclude=['user_password', 'mfa_secrets', 'webauthn_credentials']).dump(user)
    except Exception as e:
        log.error(e.__str__())
        return None


def validate_local_login(username: str, password: str):
    """
    Validate the user login using local authentication.

    :param username: Username
    :param password: Password

    :return: User object if successful, None otherwise
    """
    user = _retrieve_user_by_username(username)
    if not user:
        return None

    if bc.check_password_hash(user.password, password):
        wrap_login_user(user)
        return UserSchema(exclude=['user_password', 'mfa_secrets', 'webauthn_credentials']).dump(user)

    track_activity(f'wrong login password for user \'{username}\' using local auth', ctx_less=True, display_in_ui=False)
    return None


def is_safe_url(target):
    """
    Check whether the target URL is safe for redirection.
    Only allows in-application absolute paths (starts with /, no scheme, no host).
    Backslashes are normalised first because browsers treat them as forward slashes.
    """
    if not target:
        return False
    target = target.replace('\\', '')
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or target.startswith('//'):
        return False
    return target.startswith('/')

def _filter_next_url(next_url, context_case):
    """
    Ensures that the URL to which the user is redirected is safe. If the provided URL is not safe or is missing,
    a default URL (typically the index page) is returned.
    """
    # iris-ng v2 Phase 5: the default post-login landing is /home. UI redirect
    # only - /dashboard and the open-redirect guard are untouched, and an
    # explicit safe ?next= still wins.
    if not next_url:
        return url_for('home.home', cid=context_case)
    if is_safe_url(next_url):
        return next_url
    return url_for('home.home', cid=context_case)


# iris-ng: the built-in administrator created by post_init is always the first row
# in the user table, so it is the account an operator can still reach when MFA
# enrolment has gone wrong for everyone else.
BUILTIN_ADMIN_USER_ID = 1


def is_mfa_exempt(user_id, is_service_account=False):
    """Whether MFA enforcement does not apply to this account.

    This is the ONLY place the exemption rule lives -- login enforcement, the
    profile page and the admin user modal all call it, so the greyed-out control
    and the actual behaviour cannot drift apart.

    Two exempt cases:

    - Service accounts. Already exempt in practice rather than by policy:
      `_authenticate_password` refuses them before the password is even checked,
      so they never reach `wrap_login_user`. They authenticate by API key, which
      has no MFA step. Naming them here keeps the UI honest.

    - The built-in administrator (user #1), by explicit maintainer decision -- a
      permanent break-glass account that is never prompted for a second factor.
      SECURITY TRADE-OFF: whoever holds that password bypasses MFA entirely on
      the most privileged account in the system. Every other administrator you
      create later IS subject to enforcement; the exemption is deliberately keyed
      to the single bootstrap account, not to the server_administrator permission.
    """
    if is_service_account:
        return True

    return user_id == BUILTIN_ADMIN_USER_ID


def wrap_login_user(user, is_oidc=False):

    session['username'] = user.user

    if 'SERVER_SETTINGS' not in app.config:
        app.config['SERVER_SETTINGS'] = get_server_settings_as_dict()

    if app.config['SERVER_SETTINGS']['enforce_mfa'] is True and is_oidc is False \
            and not is_mfa_exempt(user.id, user.is_service_account):
        if "mfa_verified" not in session or session["mfa_verified"] is False:
            return redirect(url_for('mfa_verify'))

    login_user(user)

    caseid = user.ctx_case
    session['permissions'] = ac_get_effective_permissions_of_user(user)

    if caseid is None:
        case = Cases.query.order_by(Cases.case_id).first()
        user.ctx_case = case.case_id
        user.ctx_human_case = case.name
        db.session.commit()

    session['current_case'] = {
        'case_name': user.ctx_human_case,
        'case_info': "",
        'case_id': user.ctx_case
    }

    track_activity(f'user \'{user.user}\' successfully logged-in', ctx_less=True, display_in_ui=False)

    next_url = _filter_next_url(request.args.get('next'), user.ctx_case)

    return redirect(next_url)
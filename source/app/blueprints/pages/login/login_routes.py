#  IRIS Source Code
#  Copyright (C) 2021 - Airbus CyberSecurity (SAS)
#  ir@cyberactionlab.net
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

import base64
import io
import pyotp
import qrcode
import secrets
from authlib.integrations.base_client.errors import MismatchingStateError
from flask import Blueprint, flash
from flask import redirect
from flask import render_template
from flask import request
from flask import session
from flask import url_for
from flask_login import current_user

from app import app
from app import bc
from app import db
from app import oidc_client
from app.blueprints.access_controls import is_authentication_oidc, is_authentication_ldap
from app.blueprints.responses import response_error
from app.business.auth import validate_ldap_login, _retrieve_user_by_username, wrap_login_user, is_mfa_exempt
from app.business.mfa_attempts import accept_code, attempt_failed, begin_attempt, clear_attempts, code_step, \
    secret_usable
from app.datamgmt.manage.manage_users_db import create_user
from app.datamgmt.manage.manage_users_db import get_user
from app.forms import LoginForm, MFASetupForm
from app.iris_engine.access_control.oidc_handler import ID_TOKEN_LEEWAY_S
from app.iris_engine.access_control.oidc_handler import ID_TOKEN_SESSION_KEY
from app.iris_engine.access_control.oidc_handler import OidcProviderUnavailable
from app.iris_engine.access_control.oidc_handler import oidc_id_token_checks
from app.iris_engine.access_control.oidc_handler import oidc_metadata
from app.iris_engine.utils.tracker import track_activity

login_blueprint = Blueprint(
    'login',
    __name__,
    template_folder='templates'
)

log = app.logger


# filter User out of database through username



def _render_template_login(form, msg):
    organisation_name = app.config.get('ORGANISATION_NAME')
    login_banner = app.config.get('LOGIN_BANNER_TEXT')
    ptfm_contact = app.config.get('LOGIN_PTFM_CONTACT')
    auth_type = app.config.get('AUTHENTICATION_TYPE')

    return render_template('login.html', form=form, msg=msg, organisation_name=organisation_name,
                           login_banner=login_banner, ptfm_contact=ptfm_contact, auth_type=auth_type)


def _validate_local_login(username, password):
    user = _retrieve_user_by_username(username)
    if not user:
        return None

    if bc.check_password_hash(user.password, password):
        return user

    track_activity(f'wrong login password for user \'{username}\' using local auth', ctx_less=True, display_in_ui=False)
    return None


def _authenticate_ldap(form, username, password, local_fallback=True):
    try:
        user = validate_ldap_login(username, password, local_fallback)
        if user is None:
            return _render_template_login(form, 'Wrong credentials. Please try again.')

        return wrap_login_user(user)

    except Exception as e:
        log.error(e.__str__())
        return _render_template_login(form, 'LDAP authentication unavailable. Check server logs')


def _authenticate_password(form, username, password):
    user = _retrieve_user_by_username(username)
    if not user or user.is_service_account:
        return _render_template_login(form, 'Wrong credentials. Please try again.')

    if bc.check_password_hash(user.password, password):
        return wrap_login_user(user)

    track_activity(f'wrong login password for user \'{username}\' using local auth', ctx_less=True,
                   display_in_ui=False)
    return _render_template_login(form, 'Wrong credentials. Please try again.')


# Authenticate user
if app.config.get("AUTHENTICATION_TYPE") in ["local", "ldap", "oidc"]:
    @login_blueprint.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('index.index'))

        if is_authentication_oidc() and app.config.get('AUTHENTICATION_LOCAL_FALLBACK') is False:
            return redirect(url_for('login.oidc_login'))

        form = LoginForm(request.form)

        # check if both http method is POST and form is valid on submit
        #
        # This was `not form.is_submitted() and not form.validate()`, which is the
        # inverse of what the comment describes: on a POST is_submitted() is True,
        # so the `and` short-circuits and validate() is NEVER called. That left the
        # login form's CSRF token decorative -- a POST with a valid token and one
        # with no token at all produced byte-identical responses.
        if not form.validate_on_submit():
            # Reached on a GET (render the form) and on a POST whose validation
            # failed -- in practice a stale or missing CSRF token, e.g. a tab left
            # open past the session.
            return _render_template_login(form, None)

        # assign form data to variables
        username = request.form.get('username', '', type=str)
        password = request.form.get('password', '', type=str)

        if is_authentication_ldap() is True:
            return _authenticate_ldap(form, username, password, app.config.get('AUTHENTICATION_LOCAL_FALLBACK'))

        return _authenticate_password(form, username, password)

def _oidc_refused(reason, message='Sign-in with the identity provider failed.'):
    # a refused OIDC sign-in goes back to the sign-in page with a message (the reason is logged, never shown)
    log.warning(f'OIDC sign-in refused: {reason}')
    track_activity(f'OIDC sign-in refused: {reason}', ctx_less=True, display_in_ui=False)
    flash(message, 'danger')
    return redirect(url_for('login.login'))


if is_authentication_oidc():
    @login_blueprint.route('/oidc-login')
    def oidc_login():
        if current_user.is_authenticated:
            return redirect(url_for('index.index'))

        # the provider's discovery document is required, read again at every sign-in until it answers
        try:
            oidc_metadata(oidc_client, app)
        except OidcProviderUnavailable as exc:
            return _oidc_refused(str(exc), 'The identity provider is not available. Try again later.')

        # Authlib keeps state, nonce and the PKCE verifier in the session
        return oidc_client.authorize_redirect(url_for('login.oidc_authorise', _external=True))

if is_authentication_oidc():

    @login_blueprint.route('/oidc-authorize')
    def oidc_authorise():
        error = request.args.get('error')
        if error:
            return _oidc_refused(f"the provider answered '{error[:64]}'", 'The identity provider did not sign you in.')

        try:
            metadata = oidc_metadata(oidc_client, app)
            # the code exchange; the ID token's signature, issuer, audience, expiry and nonce are checked
            token = oidc_client.authorize_access_token(claims_options=oidc_id_token_checks(metadata, app),
                                                       leeway=ID_TOKEN_LEEWAY_S)
        except MismatchingStateError:
            return _oidc_refused('the authorization state is not this session\'s (a replayed or a stale sign-in)')
        except OidcProviderUnavailable as exc:
            return _oidc_refused(str(exc), 'The identity provider is not available. Try again later.')
        except Exception as exc:
            return _oidc_refused(f'{type(exc).__name__}: {str(exc)[:160]}')

        claims = token.get('userinfo')
        if not claims:
            return _oidc_refused('the reply carries no checked ID token')

        # not all providers set email by default, use preferred_username where it's missing
        # Use the mapping from the configuration or default to email or preferred_username if not set
        email_field = app.config.get("OIDC_MAPPING_EMAIL")
        username_field = app.config.get("OIDC_MAPPING_USERNAME")

        user_login = claims.get(username_field) or claims.get(email_field)
        user_name = claims.get(email_field) or claims.get(username_field)
        if not user_login:
            return _oidc_refused(f'the ID token has neither the {username_field!r} nor the {email_field!r} claim')

        user = get_user(user_login, 'user')

        if not user:
            log.warning(f'OIDC user {user_login} not found in database')
            if app.config.get('AUTHENTICATION_CREATE_USER_IF_NOT_EXIST') is False:
                log.warning('Authentication is set to not create user if not exists')
                track_activity(
                    f'OIDC user {user_login} not found in database',
                    ctx_less=True,
                    display_in_ui=False,
                )
                return response_error('User not found in IRIS', 404)

            log.info(f'Creating OIDC user {user_login} in database')
            track_activity(
                f'Creating OIDC user {user_login} in database',
                ctx_less=True,
                display_in_ui=False,
            )

            # a random password nobody knows: the account signs in through the provider
            password = secrets.token_urlsafe(32)

            user = create_user(
                        user_name=user_name,
                        user_login=user_login,
                        user_email=claims.get(email_field) or user_login,
                        user_password=bc.generate_password_hash(password.encode('utf8')).decode('utf8'),
                        user_active=True,
                        user_is_service_account=False
                )

        if user and not user.active:
            return response_error("User not active in IRIS", 403)

        response = wrap_login_user(user, is_oidc=True)
        # kept for the provider's end-session request at logout (id_token_hint)
        session[ID_TOKEN_SESSION_KEY] = token.get('id_token')
        return response


@app.route('/auth/mfa-setup', methods=['GET', 'POST'])
def mfa_setup():
    # session['username'] is only set by wrap_login_user() after the password
    # has been verified. Without this guard an unauthenticated request raises
    # KeyError and returns a 500 with a stack trace. Mirrors mfa_verify below.
    if 'username' not in session:
        return redirect(url_for('login.login'))

    user = _retrieve_user_by_username(username=session['username'])
    if not user:
        session.pop('username', None)
        return redirect(url_for('login.login'))

    # iris-ng: an exempt account is never prompted for a second factor, so letting it
    # enrol would store a secret nothing ever checks -- a confusing half-state that
    # looks like protection and is not. The UI greys the control out; this closes the
    # direct-navigation path so the two cannot disagree.
    if is_mfa_exempt(user.id, user.is_service_account):
        flash('This account is exempt from multi-factor authentication.', 'warning')
        return redirect(url_for('profile.user_settings', cid=user.ctx_case))

    # iris-ng: an account that has MFA set up replaces its secret only from a session that is
    # fully signed in. The password step puts the login in the session before the second factor is
    # checked, and this page checks the password again but not the current second factor - so a
    # password alone could enrol a new authenticator over the user's own and finish the sign-in
    # with it. A first setup (no complete secret yet) stays open from the password step.
    enrolled = bool(user.mfa_secrets) and bool(user.mfa_setup_complete)
    signed_in = current_user.is_authenticated and current_user.id == user.id
    if enrolled and not signed_in:
        track_activity(f'MFA setup refused for user {user.user}: MFA is set up and the second factor is not '
                       f'verified', ctx_less=True, display_in_ui=False)
        return redirect(url_for('mfa_verify'))

    form = MFASetupForm()

    if form.submit() and form.validate():
        locked = begin_attempt(user.id)
        if locked:
            track_activity(f'MFA setup refused for user {user.user}: too many failed attempts', ctx_less=True,
                           display_in_ui=False)
            flash(_locked_message(locked), 'danger')
        else:
            token = form.token.data
            mfa_secret = form.mfa_secret.data
            user_password = form.user_password.data
            step = code_step(mfa_secret, token)

            if step is not None:
                has_valid_password = False
                if is_authentication_ldap() is True:
                    if validate_ldap_login(user.user, user_password,
                                           local_fallback=app.config.get('AUTHENTICATION_LOCAL_FALLBACK')):
                        has_valid_password = True

                elif bc.check_password_hash(user.password, user_password):
                    has_valid_password = True

                if not has_valid_password:
                    track_activity(f'Failed MFA setup for user {user.user}. Invalid password.', ctx_less=True, display_in_ui=False)
                    minutes = attempt_failed(user.id)
                    flash(_locked_message(minutes) if minutes else 'Invalid password. Please try again.', 'danger')
                    return render_template('mfa_setup.html', form=form)

                user.mfa_secrets = mfa_secret
                user.mfa_setup_complete = True
                clear_attempts(user)
                # The setup code counts as used: the verification that follows needs the next one.
                user.mfa_last_timestep = step
                db.session.commit()
                session["mfa_verified"] = False
                track_activity(f'MFA setup successful for user {user.user}', ctx_less=True, display_in_ui=False)
                return wrap_login_user(user)
            else:
                track_activity(f'Failed MFA setup for user {user.user}. Invalid token.', ctx_less=True, display_in_ui=False)
                minutes = attempt_failed(user.id)
                flash(_locked_message(minutes) if minutes else 'Invalid token or password. Please try again.', 'danger')

    temp_otp_secret = pyotp.random_base32()
    otp_uri = pyotp.TOTP(temp_otp_secret).provisioning_uri(name=user.email, issuer_name="IRIS")
    form.mfa_secret.data = temp_otp_secret
    img = qrcode.make(otp_uri)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    img_str = base64.b64encode(buf.getvalue()).decode()

    return render_template('mfa_setup.html', form=form, img_data=img_str, otp_setup_key=temp_otp_secret)


@app.route('/auth/mfa-verify', methods=['GET', 'POST'])
def mfa_verify():
    if 'username' not in session:

        return redirect(url_for('login.login'))

    user = _retrieve_user_by_username(username=session['username'])
    if not user:
        session.pop('username', None)
        return redirect(url_for('login.login'))

    # Redirect user to MFA setup if MFA is not fully set up
    if not user.mfa_secrets or not user.mfa_setup_complete:
        track_activity(f'MFA setup required for user {user.user}', ctx_less=True, display_in_ui=False)
        return redirect(url_for('mfa_setup'))

    form = MFASetupForm()
    form.user_password.data = 'not required for verification'

    # iris-ng: a stored secret no code can match (shorter than 112 bits, or damaged) is not a wrong
    # code: say that an administrator must reset the account's MFA, and count no attempt.
    if not secret_usable(user.mfa_secrets):
        track_activity(f'MFA verification impossible for user {user.user}: the stored MFA secret is not accepted, '
                       f'an administrator must reset MFA', ctx_less=True, display_in_ui=False)
        flash('Your MFA setup can no longer be used. Ask an administrator to reset your MFA '
              '(Settings → Access Control → Users → your account → Reset MFA), then sign in again to set it up.',
              'danger')
        return render_template('mfa_verify.html', form=form)

    if form.submit() and form.validate():
        token = form.token.data
        if not token:
            flash('Token is required.', 'danger')
            return render_template('mfa_verify.html', form=form)

        # iris-ng: every code is an attempt against the account (business/mfa_attempts.py), and a
        # code is accepted once.
        locked = begin_attempt(user.id)
        if locked:
            track_activity(f'MFA verification refused for user {user.user}: too many failed attempts', ctx_less=True,
                           display_in_ui=False)
            flash(_locked_message(locked), 'danger')
            return render_template('mfa_verify.html', form=form)

        step = code_step(user.mfa_secrets, token)
        if step is not None and accept_code(user.id, step):
            session.pop('username', None)
            session['mfa_verified'] = True
            track_activity(f'MFA verification successful for user {user.user}', ctx_less=True, display_in_ui=False)
            return wrap_login_user(user)

        minutes = attempt_failed(user.id)
        reason = 'Token already used' if step is not None else 'Invalid token'
        track_activity(f'Failed MFA verification for user {user.user}. {reason}.', ctx_less=True, display_in_ui=False)
        flash(_locked_message(minutes) if minutes else 'Invalid or already used token. Please try again.', 'danger')

    return render_template('mfa_verify.html', form=form)


def _locked_message(minutes):
    return f'Too many failed attempts. Try again in {minutes} minute{"" if minutes == 1 else "s"}.'

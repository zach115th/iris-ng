#  IRIS Source Code
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

# OpenID Connect sign-in through Authlib's Flask client (iris-ng, since IRIS-NG-v2.27.0; oic before it).
#
# The provider's discovery document (OIDC_ISSUER_URL + /.well-known/openid-configuration) is required: it is read at
# the first sign-in and again at every sign-in until it answers, and nobody signs in while it cannot be read - an ID
# token is never checked against no key. Its `issuer` must be OIDC_ISSUER_URL. The ID token's signature (against the
# provider's JWKS), issuer, audience, expiry and nonce are checked by Authlib - the issuer and the audience named by
# IRIS (oidc_id_token_checks: Authlib's default checks the audience only through `azp`); the authorization request
# carries PKCE (S256); state, nonce and the PKCE verifier live in the session, and so does the ID token, for the
# provider's end-session request at logout (`id_token_hint`), so no state is kept in the process.
from urllib.parse import urlencode

from authlib.integrations.flask_client import OAuth
from flask import session

ID_TOKEN_SESSION_KEY = 'oidc_id_token'
# the clock skew allowed on the ID token's exp / iat (Authlib's default, named so it is one place)
ID_TOKEN_LEEWAY_S = 120
# no longer read since IRIS-NG-v2.27.0: they described a provider without discovery, whose ID tokens had no key to be
# checked against
UNUSED_FALLBACK_KEYS = ('OIDC_AUTH_ENDPOINT', 'OIDC_TOKEN_ENDPOINT')
# With IRIS_AUTHENTICATION_LOCAL_FALLBACK off, /login sends the browser straight to the provider. After a refused
# sign-in or a local logout it shows the sign-in page once instead (since IRIS-NG-v2.27.1): a refusal redirected to
# /login, which redirected to the provider again, in a loop; a logout landed on /login and signed straight back in
# through a provider that still had a session. The marker lives in the session and is taken by the next /login.
SHOW_SIGN_IN_ONCE_KEY = 'oidc_show_sign_in'


class OidcProviderUnavailable(Exception):
    """The provider's discovery document cannot be read, or names another issuer: nobody signs in until it can."""


def get_oidc_client(app):
    """Register the provider with Authlib; nothing is fetched until the first sign-in."""
    issuer = (app.config.get("OIDC_ISSUER_URL") or "").rstrip('/')
    unused = [k for k in UNUSED_FALLBACK_KEYS if app.config.get(k)]
    if unused:
        app.logger.warning(f"OIDC: {', '.join(unused)} are no longer used - the provider's discovery document "
                           f"({issuer}/.well-known/openid-configuration) is required")
    oauth = OAuth(app)
    # registered as `iris_oidc`: Authlib also reads `<NAME>_*` keys from app.config, and IRIS's own OIDC_* settings
    # must not be picked up that way
    return oauth.register(
        name='iris_oidc',
        client_id=app.config.get("OIDC_CLIENT_ID"),
        client_secret=app.config.get("OIDC_CLIENT_SECRET"),
        server_metadata_url=f"{issuer}/.well-known/openid-configuration",
        client_kwargs={'scope': app.config.get("OIDC_SCOPES"), 'code_challenge_method': 'S256'},
    )


def oidc_metadata(client, app):
    """The provider's discovery document; raises OidcProviderUnavailable when it cannot be read (it is fetched again
    at the next call) or when its issuer is not OIDC_ISSUER_URL."""
    try:
        metadata = client.load_server_metadata()
    except Exception as exc:
        raise OidcProviderUnavailable(f"discovery failed: {type(exc).__name__}") from exc
    expected = (app.config.get("OIDC_ISSUER_URL") or "").rstrip('/')
    if (metadata.get('issuer') or '').rstrip('/') != expected:
        client.server_metadata.clear()
        raise OidcProviderUnavailable(f"discovery names the issuer {metadata.get('issuer')!r}, not {expected!r}")
    return metadata


def oidc_id_token_checks(metadata, app):
    """The claims the ID token must carry, passed to Authlib explicitly. By default Authlib 1.9 names only the issuer:
    the audience is then checked through `azp` alone, and a token issued to another client whose `azp` names ours is
    accepted. OpenID Connect requires `aud` to contain our client id."""
    return {
        "iss": {"essential": True, "values": [metadata['issuer']]},
        "aud": {"essential": True, "values": [app.config.get("OIDC_CLIENT_ID")]},
    }


def show_sign_in_once():
    """Have the next /login show the sign-in page instead of sending the browser to the provider."""
    session[SHOW_SIGN_IN_ONCE_KEY] = True


def take_show_sign_in_once():
    """Whether the sign-in page is to be shown this once; the marker is removed."""
    return bool(session.pop(SHOW_SIGN_IN_ONCE_KEY, False))


def oidc_logout_url(client, app):
    """The provider's end-session URL for this session (its ID token as `id_token_hint`), or None when there is no
    end-session endpoint (discovery, else OIDC_END_SESSION_ENDPOINT) or no ID token in the session (a password
    sign-in, or a session from before IRIS-NG-v2.27.0)."""
    id_token = session.get(ID_TOKEN_SESSION_KEY)
    if not id_token:
        return None
    try:
        endpoint = oidc_metadata(client, app).get('end_session_endpoint')
    except OidcProviderUnavailable:
        endpoint = None
    endpoint = endpoint or app.config.get("OIDC_END_SESSION_ENDPOINT")
    if not endpoint:
        return None
    return endpoint + ('&' if '?' in endpoint else '?') + urlencode({'id_token_hint': id_token})

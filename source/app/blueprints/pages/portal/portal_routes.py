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

"""Guest portal pages (iris-ng war-room guests).

  GET /portal/join/<secret>   turn a valid invitation into a portal session
                              (logs out any user session first) and land on
                              the room; an invalid / expired / revoked link
                              renders a plain explanation, never a redirect
                              to /login.
  GET /portal/rooms/<id>      the war-room page itself, rendered with the
                              minimal portal layout for the session's guest
                              (the room API decides what the guest may do).
  GET /portal/leave           end the portal session.

The pages never touch flask-login: a guest is a portal session, not a user.
"""

from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import request
from flask import session
from flask_login import current_user
from flask_login import logout_user
from flask_wtf import FlaskForm

from app.blueprints.access_controls import GUEST_SESSION_KEY
from app.blueprints.access_controls import load_session_guest
from app.business.war_room_guests import check_guest_password
from app.business.war_room_guests import guest_for_login
from app.business.war_room_guests import guest_from_secret
from app.business.war_room_guests import guest_is_active
from app.business.war_room_guests import guest_status
from app.business.war_room_guests import touch_seen
from app.business.war_rooms import get_room_by_slug
from app.business.war_rooms import room_slug
from app.models.models import WarRoom

portal_page_blueprint = Blueprint('portal', __name__, template_folder='templates')

_REASONS = {
    'invalid': 'This invitation link is not valid. Ask the room lead for a new one.',
    'expired': 'This invitation has expired. Ask the room lead to extend it or send a new link.',
    'revoked': 'This invitation was revoked by the room lead.',
    'closed': 'This war room has been closed; guest access ended with it.',
}


def _invalid(reason: str, status: int = 403):
    return render_template('portal_invalid.html',
                           message=_REASONS.get(reason, _REASONS['invalid'])), status


def _login_form(*, email=None, secret=None, slug=None, error=None, status=200):
    return render_template('portal_login.html', form=FlaskForm(), email=email,
                           secret=secret, slug=slug, error=error), status


def _start_session(g, room):
    # A guest session replaces whatever was there: a user session must never
    # coexist with a guest one in the same cookie.
    if getattr(current_user, 'is_authenticated', False):
        logout_user()
    session.clear()
    session[GUEST_SESSION_KEY] = {'guest_id': g.id, 'room_id': g.room_id}
    session.permanent = False
    touch_seen(g)
    slug = room_slug(room)
    return redirect(f'/portal/r/{slug}' if slug else f'/portal/rooms/{g.room_id}')


@portal_page_blueprint.route('/portal/join/<secret>', methods=['GET'])
def portal_join(secret):
    """The invitation link: pins the room and pre-fills the email on the
    sign-in form. It never admits by itself — the password does."""
    g = guest_from_secret(secret)
    if g is None:
        return _invalid('invalid', 404)
    room = WarRoom.query.get(g.room_id)
    st = guest_status(g, room)
    if room is None or st != 'active':
        return _invalid(st, 410 if st in ('expired', 'revoked', 'closed') else 404)
    existing = load_session_guest(g.room_id)
    if existing is not None and existing.id == g.id:
        return _start_session(g, room)
    return _login_form(email=g.email, secret=secret)


@portal_page_blueprint.route('/portal/login', methods=['POST'])
def portal_login():
    """Email + password (+ the invitation secret or the room slug). Every
    failure answers the same generic message; lockout is per guest."""
    form = FlaskForm()
    if not form.validate():
        return _login_form(error='The form expired. Please try again.', status=400)
    email = (request.form.get('email') or '').strip()
    password = request.form.get('password') or ''
    secret = (request.form.get('secret') or '').strip() or None
    slug = (request.form.get('slug') or '').strip().lower() or None
    generic = 'Sign-in failed. Check the email address and password, or ask the room lead for a reset.'
    g = guest_for_login(secret=secret, slug=slug, email=email)
    if g is None:
        return _login_form(email=email, secret=secret, slug=slug, error=generic, status=401)
    room = WarRoom.query.get(g.room_id)
    st = guest_status(g, room)
    if room is None or st != 'active':
        return _invalid(st, 410 if st in ('expired', 'revoked', 'closed') else 404)
    ok, reason, minutes = check_guest_password(g, password)
    if not ok:
        if reason == 'locked':
            msg = f'Too many failed attempts. Try again in {minutes} minute(s).'
        else:
            msg = generic
        return _login_form(email=email, secret=secret, slug=slug, error=msg, status=401)
    return _start_session(g, room)


@portal_page_blueprint.route('/portal/rooms/<int:room_id>', methods=['GET'])
def portal_room(room_id):
    g = load_session_guest(room_id)
    if g is None:
        room = WarRoom.query.get(room_id)
        if room is None:
            return _invalid('invalid', 404)
        return _login_form(slug=room_slug(room), status=401)
    room = WarRoom.query.get(room_id)
    if room is None or not guest_is_active(g, room):
        return _invalid(guest_status(g, room) if room else 'invalid', 410)
    touch_seen(g)
    form = FlaskForm()
    return render_template('war_room.html', caseid=None, form=form, room_id=room_id,
                           layout='layouts/portal.html', guest_mode=True,
                           guest=g, room=room)


@portal_page_blueprint.route('/portal/r/<slug>', methods=['GET'])
def portal_room_by_slug(slug):
    """rooms.example.com/<slug> (the portal nginx block rewrites the bare
    path to this route). The session decides: a guest bound to another
    room, or nobody, gets the invitation page — never a room listing."""
    room = get_room_by_slug((slug or '').lower())
    if room is None:
        return _invalid('invalid', 404)
    if load_session_guest(room.id) is None:
        return _login_form(slug=room.slug, status=401)
    return portal_room(room.id)


@portal_page_blueprint.route('/portal/leave', methods=['GET'])
def portal_leave():
    session.pop(GUEST_SESSION_KEY, None)
    return render_template(
        'portal_invalid.html',
        message='You have left the room. Use your invitation link to come back.'), 200


@portal_page_blueprint.route('/portal', methods=['GET'])
@portal_page_blueprint.route('/portal/', methods=['GET'])
def portal_index():
    data = session.get(GUEST_SESSION_KEY) or {}
    if data.get('room_id'):
        return redirect(f"/portal/rooms/{int(data['room_id'])}")
    return _invalid('invalid', 404)

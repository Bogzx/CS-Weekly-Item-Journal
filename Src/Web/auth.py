"""Sessions, CSRF tokens, the login throttle and safe redirects."""

import hmac
import ipaddress
import logging
import os
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlparse

from flask import current_app, flash, redirect, request, session, url_for
from flask.sessions import SecureCookieSessionInterface
from markupsafe import Markup

logger = logging.getLogger(__name__)

# How long a "remember me" session lasts. Sessions without "remember me" get
# UNREMEMBERED_SESSION_LIFETIME instead (see login() in app.py).
REMEMBERED_SESSION_LIFETIME = timedelta(days=int(os.environ.get('SESSION_LIFETIME_DAYS', '120')))
UNREMEMBERED_SESSION_LIFETIME = timedelta(hours=1)


class RememberMeSessionInterface(SecureCookieSessionInterface):
    """Give each session its own cookie lifetime.

    Flask reads PERMANENT_SESSION_LIFETIME from app.config when it serializes
    the cookie, which makes the lifetime process-global. Overriding
    get_expiration_time lets an individual session opt into the short lifetime
    without mutating shared state.
    """

    def get_expiration_time(self, app, session):
        if not session.permanent:
            return None
        lifetime = (REMEMBERED_SESSION_LIFETIME if session.get('remember')
                    else UNREMEMBERED_SESSION_LIFETIME)
        return datetime.now(timezone.utc) + lifetime


def enforce_session_expiry():
    """Drop sessions past their absolute expiry (a before_request hook).

    get_expiration_time above sets the cookie's browser-side expiry. This is
    the server-side half: a client that ignores the cookie expiry (or replays a
    stored cookie) still gets logged out.
    """
    expires_at = session.get('expires_at')
    if expires_at is not None and datetime.now(timezone.utc).timestamp() > expires_at:
        session.clear()


# --- CSRF protection -------------------------------------------------------
#
# Every POST must carry the per-session token that templates embed with
# {{ csrf_field() }}. SameSite=Lax cookies already stop most cross-site form
# posts in current browsers, but not from a sibling subdomain or an old
# browser, and every state-changing route here (add/remove/clear journal,
# upload, login) is a plain form POST. A small token check needs no extra
# dependency; Flask-WTF's CSRFProtect is the drop-in alternative.
CSRF_SESSION_KEY = '_csrf_token'
CSRF_FIELD = 'csrf_token'


def get_csrf_token():
    """This session's CSRF token, created on first use."""
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def csrf_field():
    """Hidden form input carrying the CSRF token (for templates)."""
    return Markup(f'<input type="hidden" name="{CSRF_FIELD}" value="{get_csrf_token()}">')


def csrf_protect():
    """Reject a POST without this session's token (a before_request hook)."""
    if request.method != 'POST' or not current_app.config.get('CSRF_ENABLED', True):
        return None
    expected = session.get(CSRF_SESSION_KEY)
    sent = request.form.get(CSRF_FIELD) or request.headers.get('X-CSRF-Token')
    # compare_digest raises TypeError on non-ASCII str, which turned a forged
    # token such as 'é' into a 500; compare bytes instead.
    if not expected or not sent or not hmac.compare_digest(str(sent).encode(), str(expected).encode()):
        logger.warning("Rejected POST %s: missing or invalid CSRF token", request.path)
        return ('The form was missing its security token or it has expired. '
                'Go back, reload the page and try again.', 400,
                {'Content-Type': 'text/plain; charset=utf-8'})
    return None


class LoginThrottle:
    """Count failed logins per client and refuse further attempts for a while.

    In-memory and per-process: enough to stop an online password guesser
    against a single `python app.py` instance, and it needs no extra service.
    Failures older than `window` seconds are forgotten. Behind a reverse proxy
    every client shares the proxy's address, so run the app directly or set
    TRUSTED_PROXIES first.

    An attempt is counted *before* the password is checked (begin_attempt),
    so parallel requests cannot all slip in under the limit while the slow
    password hash runs. A successful login then clears only that username's
    failures: clearing the whole client let anyone with an account of their
    own guess max_failures - 1 passwords, log in as themselves, and repeat.
    """

    def __init__(self, max_failures, window, clock=time.monotonic):
        self.max_failures = max_failures
        self.window = window
        self.clock = clock
        self._failures = {}  # key -> deque of (timestamp, username)
        self._lock = threading.Lock()

    def _recent(self, key, now):
        failures = self._failures.get(key)
        if failures is None:
            return None
        while failures and failures[0][0] <= now - self.window:
            failures.popleft()
        if not failures:
            del self._failures[key]
            return None
        return failures

    def _retry_after(self, key, now):
        failures = self._recent(key, now)
        if failures is None or len(failures) < self.max_failures:
            return 0
        return max(1, int(failures[-self.max_failures][0] + self.window - now + 0.999))

    def retry_after(self, key):
        """Seconds until `key` may try again, or 0 if it is not locked out."""
        if self.max_failures <= 0:
            return 0
        with self._lock:
            return self._retry_after(key, self.clock())

    def _append(self, key, now, username):
        failures = self._recent(key, now)
        if failures is None:
            failures = self._failures[key] = deque()
        failures.append((now, username))
        # Only the newest max_failures entries matter.
        while len(failures) > max(self.max_failures, 1):
            failures.popleft()

    def begin_attempt(self, key, username=None):
        """Count an attempt as failed unless succeeded() is called for it.

        Returns 0 if the attempt may go ahead, or the seconds to wait if the
        client is locked out (then nothing is recorded). The check and the
        count happen under one lock.
        """
        if self.max_failures <= 0:
            return 0
        with self._lock:
            now = self.clock()
            wait = self._retry_after(key, now)
            if not wait:
                self._append(key, now, username)
            return wait

    def succeeded(self, key, username=None):
        """Forget `key`'s failures for `username`, and only for it."""
        with self._lock:
            failures = self._failures.get(key)
            if failures is None:
                return
            kept = deque(f for f in failures if f[1] != username)
            if kept:
                self._failures[key] = kept
            else:
                del self._failures[key]

    def record_failure(self, key, username=None):
        with self._lock:
            self._append(key, self.clock(), username)

    def reset(self, key=None):
        with self._lock:
            if key is None:
                self._failures.clear()
            else:
                self._failures.pop(key, None)


def throttle_key(address):
    """The login-throttle key for a client address.

    An IPv6 client usually controls a whole /64, so one bucket per /64:
    otherwise every guess could come from a fresh address.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address or 'unknown'
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f'{ip}/64', strict=False))
    return str(ip)


def login_required(f):
    """Decorator to require login for certain routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def is_safe_redirect(target):
    """True if `target` is a path on this site.

    Checking startswith('/') alone let '//evil.example' and '/\\evil.example'
    through; browsers treat both as a different host.
    """
    if not target or not target.startswith('/') or target.startswith(('//', '/\\')):
        return False
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc

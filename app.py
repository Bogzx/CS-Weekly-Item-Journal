"""The Flask app: configuration, wiring and routes.

The logic lives in Src/Web/ (see its __init__.py for the map). This module
reads the configuration, builds the app, and keeps the request handlers.
"""

import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash

from Src.ImageDetector.item_matcher import ItemMatcher
from Src.ImageDetector.modified_detect_text import DetectionError, WeeklyDropProcessor
from Src.Web import history as history_lib
from Src.Web import matching, prices, valuation
from Src.Web.auth import (  # noqa: F401  (CSRF_FIELD, CSRF_SESSION_KEY: tests and tools post forms)
    CSRF_FIELD, CSRF_SESSION_KEY, REMEMBERED_SESSION_LIFETIME, UNREMEMBERED_SESSION_LIFETIME,
    LoginThrottle, RememberMeSessionInterface, csrf_field, csrf_protect, enforce_session_expiry,
    get_csrf_token, is_safe_redirect, login_required, throttle_key,
)
from Src.Web.db import (
    close_db, get_current_user, get_db, get_journal_price_rows, get_journal_total,
    get_user_journal, initialize_database,
)
from Src.Web.history import (
    CS2_RESET_HOUR_UTC, build_history_chart, resolve_week_boundary, summarize_history,
)
from Src.Web.prices import DEFAULT_PRICE_UPDATE_CONFIG  # noqa: F401  (tests, docs)
from Src.Web.settings import env_bool, repo_path, resolve_secret_key
from Src.Web.uploads import (
    cleanup_uploads as _cleanup_uploads, decode_pasted_image, save_pasted_image, save_uploaded_image,
)
from Src.Web.valuation import RECOMMENDED_PICKS, VALUATION_RULES, resolve_valuation_rule

# Load variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = resolve_secret_key(os.environ.get('SECRET_KEY'))

# Behind a reverse proxy every request arrives from the proxy's address, so
# the login throttle would lock out everyone at once (or no one). Set
# TRUSTED_PROXIES to the number of proxies in front of the app to take the
# client address, scheme and host from their X-Forwarded-* headers. It stays
# 0 by default: trusting those headers without a proxy lets any client spoof
# its address and dodge the throttle.
_raw_wsgi_app = app.wsgi_app


def trust_proxies(count):
    """Honour X-Forwarded-For/-Proto/-Host from `count` proxies (0 = none)."""
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = (ProxyFix(_raw_wsgi_app, x_for=count, x_proto=count, x_host=count)
                    if count > 0 else _raw_wsgi_app)


trust_proxies(int(os.environ.get('TRUSTED_PROXIES', '0')))

app.config['UPLOAD_FOLDER'] = repo_path(os.environ.get('UPLOAD_FOLDER', 'uploads'))
# A 4K PNG screenshot is ~10 MB, and a pasted one arrives as base64 text in a
# form field (+33%). This was 256 MB, which let any logged-in user make the
# server buffer and decode a quarter-gigabyte request per upload.
MAX_UPLOAD_MB = int(os.environ.get('MAX_UPLOAD_MB', '20'))
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024
# Werkzeug's per-field in-memory limit (default 500 KB) must fit a pasted
# screenshot, so it follows the request limit.
app.config['MAX_FORM_MEMORY_SIZE'] = app.config['MAX_CONTENT_LENGTH']
app.config['DATABASE'] = repo_path(os.environ.get('DATABASE_PATH', 'csgo_items.db'))
app.config['MODEL_PATH'] = repo_path(os.environ.get('MODEL_PATH', os.path.join('Models', 'BOX_TRAINED.pt')))
app.config['SESSION_TYPE'] = 'filesystem'
app.config['VALUATION_RULE'] = resolve_valuation_rule(os.environ.get('VALUATION_RULE'))
app.config['WEEK_BOUNDARY'] = resolve_week_boundary(os.environ.get('WEEK_BOUNDARY'))
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = REMEMBERED_SESSION_LIFETIME
# Only send the session cookie over HTTPS. This MUST be false when serving
# plain HTTP -- with it hard-coded to True, login silently failed on any LAN
# or non-TLS host because the browser refused to store the cookie.
app.config['SESSION_COOKIE_SECURE'] = env_bool('SESSION_COOKIE_SECURE', False)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config.setdefault('CSRF_ENABLED', env_bool('CSRF_ENABLED', True))

app.session_interface = RememberMeSessionInterface()
app.before_request(enforce_session_expiry)
app.before_request(csrf_protect)
app.teardown_appcontext(close_db)
app.jinja_env.globals.update(csrf_token=get_csrf_token, csrf_field=csrf_field)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
initialize_database(app.config['DATABASE'])

login_throttle = LoginThrottle(
    max_failures=int(os.environ.get('LOGIN_MAX_ATTEMPTS', '5')),
    window=int(os.environ.get('LOGIN_LOCKOUT_MINUTES', '15')) * 60,
)

# The weekly drop processor is built lazily, on the first upload.
#
# It used to be constructed here at import time, which meant loading the YOLO
# weights and pulling down EasyOCR's models before Flask could even start. Any
# failure in that path -- most notably the `AttributeError: Can't get attribute
# 'C3k2'` raised by ultralytics < 8.3.94 when unpickling these YOLO11 weights --
# was an unrecoverable crash at startup with no route ever registered.
#
# Deferring it means the web app boots, the login and journal pages work, and a
# model problem surfaces as an error on the page that actually needed the model.
# It also keeps the test suite and `flask routes` from paying a model load.
_processor = None

# Initialize the item matcher (cheap: it only stores a path until first query)
matcher = ItemMatcher(app.config['DATABASE'])


def get_processor():
    """Return the shared WeeklyDropProcessor, constructing it on first use."""
    global _processor
    if _processor is None:
        logger.info("Loading detection model from %s", app.config['MODEL_PATH'])
        _processor = WeeklyDropProcessor(app.config['MODEL_PATH'])
    return _processor


def process_image(image_path):
    """The four OCR texts of a screenshot.

    Raises DetectionError when there is no drop panel and ValueError when the
    file cannot be read; upload_file() turns those into messages for the user.
    """
    return get_processor().process_image(image_path, save_crops=False)


def match_items_in_database(item_names):
    """Candidate items for each OCR text (see Src/Web/matching.py)."""
    return matching.match_items_in_database(item_names, matcher)


def annotate_recommendation(item_results, rule=None, picks=RECOMMENDED_PICKS):
    """Value each slot and flag the two to claim (see Src/Web/valuation.py)."""
    return valuation.annotate_recommendation(item_results, rule or app.config['VALUATION_RULE'], picks)


def bucket_by_week(rows, boundary=None):
    """Weekly buckets under the configured WEEK_BOUNDARY (see Src/Web/history.py)."""
    return history_lib.bucket_by_week(rows, boundary or app.config['WEEK_BOUNDARY'])


def get_journal_history(user_id):
    """A user's journal as weekly drop history, oldest week first."""
    return bucket_by_week(get_journal_price_rows(user_id))


def cleanup_uploads():
    _cleanup_uploads(app.config['UPLOAD_FOLDER'])


def update_prices_job():
    """One price crawl against the app's database (scheduled daily)."""
    prices.update_prices_job(app.config['DATABASE'])


# Routes
@app.route('/')
def index():
    """Main page with upload form."""
    # Get current user if logged in
    user = get_current_user()
    journal = []
    total_value = 0
    
    if user:
        # Get user's journal from database
        journal = get_user_journal(user['id'])
        total_value = get_journal_total(journal)
    
    return render_template(
        'index.html', 
        user=user,
        journal=journal, 
        total_value=total_value
    )

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration page."""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        
        # Validate form data
        error = None
        if not username:
            error = 'Username is required.'
        elif not email:
            error = 'Email is required.'
        elif not password:
            error = 'Password is required.'
        elif password != confirm:
            error = 'Passwords do not match.'
            
        if error is None:
            # Check if username or email already exists
            conn = get_db()
            existing_user = conn.execute(
                'SELECT id FROM users WHERE username = ? OR email = ?',
                (username, email)
            ).fetchone()
            
            if existing_user:
                error = 'Username or email is already taken.'
            else:
                # Hash password and create user
                password_hash = generate_password_hash(password)
                try:
                    conn.execute(
                        'INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
                        (username, email, password_hash)
                    )
                    conn.commit()
                    flash('Registration successful! You can now log in.', 'success')
                    return redirect(url_for('login'))
                except sqlite3.IntegrityError:
                    # Someone registered the same name between the check and
                    # the insert.
                    conn.rollback()
                    error = 'Username or email is already taken.'
                except sqlite3.Error:
                    conn.rollback()
                    logger.exception("Could not create user %r", username)
                    error = 'Could not create the account. Please try again.'

        
        if error:
            flash(error, 'error')
    
    return render_template('register.html')

def locked_out(wait):
    """The login page with a 429 for a client the throttle has locked out."""
    minutes = (wait + 59) // 60
    flash(f'Too many failed login attempts. Try again in {minutes} minute'
          f'{"s" if minutes != 1 else ""}.', 'error')
    return render_template('login.html'), 429


@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login page."""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = 'remember' in request.form
        
        client_key = throttle_key(request.remote_addr)
        wait = login_throttle.retry_after(client_key)
        if wait:
            return locked_out(wait)

        error = None
        if not username:
            error = 'Username is required.'
        elif not password:
            error = 'Password is required.'
            
        if error is None:
            # Counted before the (slow) password check; see LoginThrottle.
            wait = login_throttle.begin_attempt(client_key, username)
            if wait:
                return locked_out(wait)
            conn = get_db()
            user = conn.execute(
                'SELECT id, username, password_hash FROM users WHERE username = ?',
                (username,)
            ).fetchone()
            
            # One message for both cases so the form cannot be used to find
            # out which usernames are registered.
            if user is None or not check_password_hash(user['password_hash'], password):
                error = 'Invalid username or password.'
            else:
                # Login successful
                login_throttle.succeeded(client_key, username)
                session.clear()
                session['user_id'] = user['id']
                
                # Set the session lifetime according to "remember me".
                #
                # This was previously a no-op: the 1-hour lifetime was written
                # to app.config and then immediately overwritten with 120 days
                # BEFORE Flask serialized the cookie at the end of the request,
                # so every session got 120 days regardless. Worse, mutating
                # app.config is process-global -- one user's login changed the
                # lifetime for every concurrent request.
                #
                # Flask reads PERMANENT_SESSION_LIFETIME when it serializes the
                # cookie, so the value has to still be correct at that point.
                # We set it per-session instead of globally.
                session.permanent = True
                session['remember'] = bool(remember)
                lifetime = REMEMBERED_SESSION_LIFETIME if remember else UNREMEMBERED_SESSION_LIFETIME
                session['expires_at'] = (datetime.now(timezone.utc) + lifetime).timestamp()

                logger.info("User %s logged in (remember me: %s)", username, remember)
                
                # Redirect to next page if specified, otherwise to index
                next_page = request.args.get('next')
                if is_safe_redirect(next_page):
                    return redirect(next_page)
                return redirect(url_for('index'))
        
        if error:
            flash(error, 'error')
    
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout():
    """Log out the current user.

    POST with the CSRF token only. As a GET link, any page could log a user
    out with an <img src=".../logout">.
    """
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile():
    """User profile page."""
    user = get_current_user()
    journal = get_user_journal(user['id'])
    
    # Process dates for display
    for item in journal:
        if 'created_at' in item:
            item['created_at_display'] = str(item['created_at'])
    
    total_value = get_journal_total(journal)
    
    return render_template(
        'profile.html',
        user=user,
        journal=journal,
        total_value=total_value
    )

@app.route('/history')
@login_required
def history():
    """Drop history and expected value over time."""
    user = get_current_user()
    buckets = get_journal_history(user['id'])

    return render_template(
        'history.html',
        user=user,
        history=list(reversed(buckets)),  # table reads newest-first
        summary=summarize_history(buckets),
        chart=build_history_chart(buckets),
        week_note=(f"Weeks start at the CS2 weekly reset, Wednesday {CS2_RESET_HOUR_UTC:02d}:00 UTC."
                   if app.config['WEEK_BOUNDARY'] == 'cs2' else "ISO weeks, starting Monday 00:00 UTC.")
    )


def upload_error_page(user, message, status=400):
    """Render a rejected or failed upload as the results page.

    These used to be bare JSON bodies, which a browser submitting the upload
    form showed as raw text.
    """
    journal = get_user_journal(user['id']) if user else []
    return render_template(
        'results.html',
        error=message,
        screenshot_id='',
        item_results=[],
        user=user,
        journal=journal,
        total_value=get_journal_total(journal)
    ), status


# Shown for anything unexpected. The details go to the log, not the page:
# exception text can name files, paths and library internals.
UNEXPECTED_UPLOAD_ERROR = ('Something went wrong while processing the screenshot. '
                           'The error has been logged; please try again.')


@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    """Handle file upload or pasted image.

    Outcomes: 200 with the results; 400 for something that is not a readable
    screenshot; 422 when the weekly-drop panel is not in it (the message says
    so); 500 with a generic message for anything else, logged in full.
    Oversized requests never get here: Flask enforces MAX_CONTENT_LENGTH while
    parsing the form and the 413 handler takes over.
    """
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    try:
        cleanup_uploads()

        # A unique name for this upload; nothing from the request is used.
        screenshot_id = str(uuid.uuid4())
        path_stem = os.path.join(app.config['UPLOAD_FOLDER'], screenshot_id)

        if 'file' in request.files and request.files['file'].filename:
            try:
                filepath = save_uploaded_image(request.files['file'].read(), path_stem)
            except ValueError as upload_error:
                logger.info("Rejected uploaded file: %s", upload_error)
                return upload_error_page(user, f'That file is not a screenshot we can read: {upload_error}.')
        elif 'image_data' in request.form and request.form['image_data']:
            try:
                extension, binary_data = decode_pasted_image(request.form['image_data'])
            except ValueError as paste_error:
                logger.info("Rejected pasted image: %s", paste_error)
                return upload_error_page(user, f'Error processing pasted image: {paste_error}.')

            # The extension comes from PASTED_IMAGE_EXTENSIONS, never from the
            # request, so the path cannot escape UPLOAD_FOLDER.
            filepath = f"{path_stem}.{extension}"
            save_pasted_image(binary_data, filepath)
        else:
            return upload_error_page(user, 'No file or pasted image was received.')

        # The screenshot is not needed afterwards (nothing displays it), so it
        # is deleted right away rather than lingering until cleanup_uploads().
        try:
            item_names = process_image(filepath)
        except DetectionError as e:
            logger.info("No drop panel in upload %s: %s", screenshot_id, e)
            return upload_error_page(user, str(e), status=422)
        except ValueError as e:
            logger.info("Unreadable upload %s: %s", screenshot_id, e)
            return upload_error_page(user, 'That file is not a screenshot we can read.')
        finally:
            try:
                os.remove(filepath)
            except OSError:
                pass
        logger.info("Detected %d items in upload %s", len(item_names), screenshot_id)

        matched_items = match_items_in_database(item_names)

        # Value each drop and pick the two worth claiming. This mutates
        # matched_items in place, tagging the winning slots and matches.
        recommendations = annotate_recommendation(matched_items)

        journal = get_user_journal(user['id'])
        return render_template(
            'results.html',
            screenshot_id=screenshot_id,
            item_results=matched_items,
            recommendations=recommendations,
            valuation_rule=app.config['VALUATION_RULE'],
            valuation_label=VALUATION_RULES[app.config['VALUATION_RULE']],
            user=user,
            journal=journal,
            total_value=get_journal_total(journal)
        )
    except Exception:
        logger.exception("Error processing upload")
        return upload_error_page(user, UNEXPECTED_UPLOAD_ERROR, status=500)


@app.route('/add_to_journal', methods=['POST'])
@login_required
def add_to_journal():
    """Add selected items to the user's journal."""
    # Get the current user
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))
    
    # Get the item IDs - this can be a single ID or multiple IDs (up to 2)
    item_ids = request.form.getlist('item_id')
    screenshot_id = request.form.get('screenshot_id', str(uuid.uuid4()))
    
    if not item_ids:
        return redirect(url_for('index'))
    
    # Limit to adding at most 2 items at a time
    item_ids = item_ids[:2]
    
    conn = get_db()
    try:
        
        for item_id in item_ids:
            cur = conn.execute(
                "SELECT id, name, collection, price, price_type, item_type FROM items WHERE id = ?",
                (item_id,)
            )
            item = cur.fetchone()
            
            if item:
                item_dict = item  # get_db() returns rows as dicts

                # Insert into user_journals table
                conn.execute(
                    """
                    INSERT INTO user_journals (
                        user_id, item_id, item_name, item_collection, 
                        item_price, item_price_type, item_type, screenshot_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user['id'],
                        item_dict.get('id'),
                        item_dict.get('name', 'Unknown Item'),
                        item_dict.get('collection', ''),
                        item_dict.get('price'),
                        item_dict.get('price_type', 'unknown'),
                        item_dict.get('item_type', ''),
                        screenshot_id
                    )
                )
        
        conn.commit()
        flash('Items added to your journal successfully!', 'success')
        
    except sqlite3.Error:
        logger.exception("Could not add items %s to the journal of user %s", item_ids, user['id'])
        conn.rollback()
        flash('Could not add the items to your journal. Please try again.', 'error')
    
    return redirect(url_for('index'))

@app.route('/remove_from_journal', methods=['POST'])
@login_required
def remove_from_journal():
    """Remove an item from the journal."""
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))
    
    journal_id = request.form.get('journal_id')
    
    if not journal_id:
        return redirect(url_for('index'))
    
    conn = get_db()
    try:
        
        # Verify the journal item belongs to this user
        journal_item = conn.execute(
            "SELECT id FROM user_journals WHERE id = ? AND user_id = ?",
            (journal_id, user['id'])
        ).fetchone()
        
        if journal_item:
            conn.execute(
                "DELETE FROM user_journals WHERE id = ?",
                (journal_id,)
            )
            conn.commit()
            flash('Item removed from your journal.', 'success')
        else:
            flash('Journal item not found or not authorized.', 'error')
        
    except sqlite3.Error:
        logger.exception("Could not remove journal entry %s of user %s", journal_id, user['id'])
        conn.rollback()
        flash('Could not remove the item. Please try again.', 'error')
    
    return redirect(url_for('index'))

@app.route('/clear_journal', methods=['POST'])
@login_required
def clear_journal():
    """Clear all items from the user's journal."""
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))
    
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM user_journals WHERE user_id = ?",
            (user['id'],)
        )
        conn.commit()
        flash('Your journal has been cleared.', 'success')
    except sqlite3.Error:
        logger.exception("Could not clear the journal of user %s", user['id'])
        conn.rollback()
        flash('Could not clear your journal. Please try again.', 'error')
    
    return redirect(url_for('index'))

# Custom error handlers
@app.errorhandler(RequestEntityTooLarge)
def handle_request_entity_too_large(error):
    """Handle 413 Request Entity Too Large error."""
    logger.info("Rejected an upload over %d MB", MAX_UPLOAD_MB)
    flash(f'The image you uploaded is too large (limit {MAX_UPLOAD_MB} MB). '
          f'Please reduce its size or upload a different image.', 'error')
    return redirect(url_for('index'))

@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle 413 Request Entity Too Large error (HTTP version)."""
    logger.info("Rejected an upload over %d MB", MAX_UPLOAD_MB)
    flash(f'The image you uploaded is too large (limit {MAX_UPLOAD_MB} MB). '
          f'Please reduce its size or upload a different image.', 'error')
    return redirect(url_for('index'))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    # Initialize the scheduler for daily price updates
    prices.init_scheduler(app.config['DATABASE'])

    # debug=True was hard-coded. Werkzeug's debugger exposes an interactive
    # Python console on any unhandled exception, so shipping it on by default
    # is remote code execution the moment the app is reachable off localhost.
    # It is now opt-in via FLASK_DEBUG.
    debug_mode = env_bool('FLASK_DEBUG', False)
    host = os.environ.get('FLASK_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_PORT', '5000'))

    app.run(host=host, port=port, debug=debug_mode, use_reloader=False)

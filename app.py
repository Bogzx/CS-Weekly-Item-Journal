import os
import uuid
import time
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, g
from flask.sessions import SecureCookieSessionInterface
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.formparser import RequestEntityTooLarge
from Src.ImageDetector.modified_detect_text import WeeklyDropProcessor
from Src.ImageDetector.item_matcher import ItemMatcher

from dotenv import load_dotenv

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import json
import subprocess
import sys
import logging
from urllib.parse import urlparse

# Load variables from .env file
load_dotenv()

# Absolute path to the repository root, so that subprocesses and file lookups
# do not depend on the process working directory.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _env_bool(name, default):
    """Read a boolean from the environment, accepting 1/true/yes/on."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


# Written to price_update_config.json on first run if it is missing. An empty
# 'collections' list means "every collection".
DEFAULT_PRICE_UPDATE_CONFIG = {
    "collections": [],
    "max_items": 5000,
    "batch_size": 100,
}


# The placeholder shipped in .env.EXAMPLE. Anyone who copies that file without
# editing it would otherwise sign sessions with a key published on GitHub,
# which lets a visitor forge a cookie for any user_id.
PLACEHOLDER_SECRET_PREFIX = 'CHANGE_ME'


def resolve_secret_key(raw):
    """Return a usable session signing key.

    Falls back to a random per-process key (sessions end on restart) when the
    configured one is missing or is still the .env.EXAMPLE placeholder.
    """
    if not raw or raw.startswith(PLACEHOLDER_SECRET_PREFIX):
        logging.getLogger(__name__).warning(
            "SECRET_KEY is unset or still the .env.EXAMPLE placeholder; using a "
            "random key. Logins will not survive a restart. See README 'Configure'."
        )
        return os.urandom(24)
    return raw


app = Flask(__name__)
app.secret_key = resolve_secret_key(os.environ.get('SECRET_KEY'))

# How long a "remember me" session lasts. Sessions without "remember me" get
# REMEMBER_ME_OFF_LIFETIME instead (see login()).
REMEMBERED_SESSION_LIFETIME = timedelta(days=int(os.environ.get('SESSION_LIFETIME_DAYS', '120')))
UNREMEMBERED_SESSION_LIFETIME = timedelta(hours=1)

# Configure the session to use cookies
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 256 * 1024 * 1024  # 256MB max upload (increased from 128MB)
app.config['MAX_CONTENT_PATH'] = 16 * 1024 * 1024  # 16MB max for form fields
app.config['DATABASE'] = os.environ.get('DATABASE_PATH', 'csgo_items.db')
app.config['MODEL_PATH'] = os.environ.get('MODEL_PATH', os.path.join('Models', 'BOX_TRAINED.pt'))
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = REMEMBERED_SESSION_LIFETIME
# Only send the session cookie over HTTPS. This MUST be false when serving
# plain HTTP -- with it hard-coded to True, login silently failed on any LAN
# or non-TLS host because the browser refused to store the cookie.
app.config['SESSION_COOKIE_SECURE'] = _env_bool('SESSION_COOKIE_SECURE', False)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


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


app.session_interface = RememberMeSessionInterface()


@app.before_request
def enforce_session_expiry():
    """Drop sessions past their absolute expiry.

    get_expiration_time above sets the cookie's browser-side expiry. This is
    the server-side half: a client that ignores the cookie expiry (or replays a
    stored cookie) still gets logged out.
    """
    expires_at = session.get('expires_at')
    if expires_at is not None and datetime.now(timezone.utc).timestamp() > expires_at:
        session.clear()

# Increase request size limits for Werkzeug
app.config['MAX_FORM_MEMORY_SIZE'] = 64 * 1024 * 1024  # 64MB for form data

# Ensure the upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

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
        app.logger.info("Loading detection model from %s", app.config['MODEL_PATH'])
        _processor = WeeklyDropProcessor(app.config['MODEL_PATH'])
    return _processor

# Database functions
def get_db():
    """Get a connection to the SQLite database."""
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        # Set row_factory to return dictionaries instead of Row objects
        g.db.row_factory = lambda cursor, row: {
            column[0]: row[idx] for idx, column in enumerate(cursor.description)
        }
    return g.db

@app.teardown_appcontext
def close_db(error):
    """Close database connection at the end of request."""
    if 'db' in g:
        g.db.close()

def initialize_database():
    """Check if the database has all required tables and columns."""
    conn = sqlite3.connect(app.config['DATABASE'])
    cursor = conn.cursor()
    
    # Check and add price_type column if needed
    try:
        cursor.execute("ALTER TABLE items ADD COLUMN price_type TEXT")
        print("Added price_type column to items table")
    except sqlite3.OperationalError:
        # Column already exists, which is fine
        pass
    
    # Create users table if it doesn't exist
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Create user_journals table if it doesn't exist
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_journals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL,
        item_name TEXT NOT NULL,
        item_collection TEXT,
        item_price REAL,
        item_price_type TEXT,
        item_type TEXT,
        screenshot_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
    )
    ''')
    
    # Add indexes for better performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_journals_user_id ON user_journals (user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_journals_item_id ON user_journals (item_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_journals_screenshot_id ON user_journals (screenshot_id)")
    
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

# Initialize the database
initialize_database()

# Authentication functions
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


def get_current_user():
    """Get current user from session."""
    if 'user_id' in session:
        conn = get_db()
        user = conn.execute(
            "SELECT id, username, email FROM users WHERE id = ?", 
            (session['user_id'],)
        ).fetchone()
        return user
    return None

def get_user_journal(user_id):
    """Get a user's journal items from the database."""
    conn = get_db()
    journal_items = conn.execute(
        "SELECT * FROM user_journals WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    return journal_items

def get_journal_total(journal_items):
    """Calculate total value of items in a journal."""
    return sum(float(item.get('item_price', 0) or 0) for item in journal_items)


def get_journal_history(user_id):
    """Aggregate a user's journal into a per-week drop history.

    CS2 grants one care package per week, so the natural unit for "how am I
    doing over time" is the ISO-ish week the item was journalled in. Returns
    buckets oldest-first, each carrying the number of items kept, their total
    value, the mean value per item that week (the realised expected value of a
    drop) and the running cumulative total.
    """
    conn = get_db()
    rows = conn.execute(
        """
        SELECT
            strftime('%Y-W%W', created_at) AS week,
            MIN(date(created_at))          AS week_start,
            COUNT(*)                       AS item_count,
            COALESCE(SUM(item_price), 0)   AS total_value,
            AVG(item_price)                AS avg_value
        FROM user_journals
        WHERE user_id = ?
        GROUP BY week
        ORDER BY week ASC
        """,
        (user_id,)
    ).fetchall()

    history = []
    running_total = 0.0
    for row in rows:
        total = float(row.get('total_value') or 0)
        running_total += total
        history.append({
            'week': row.get('week'),
            'week_start': row.get('week_start'),
            'item_count': int(row.get('item_count') or 0),
            # AVG() skips NULLs, so this is the mean over *priced* items only,
            # which is what you want for an EV figure.
            'avg_value': float(row.get('avg_value') or 0),
            'total_value': total,
            'cumulative_value': running_total,
        })
    return history


def summarize_history(history):
    """Headline numbers for the history page."""
    if not history:
        return {
            'weeks_tracked': 0,
            'total_items': 0,
            'total_value': 0.0,
            'avg_per_item': 0.0,
            'avg_per_week': 0.0,
            'best_week': None,
        }

    total_items = sum(bucket['item_count'] for bucket in history)
    total_value = history[-1]['cumulative_value']

    return {
        'weeks_tracked': len(history),
        'total_items': total_items,
        'total_value': total_value,
        'avg_per_item': (total_value / total_items) if total_items else 0.0,
        'avg_per_week': total_value / len(history),
        'best_week': max(history, key=lambda bucket: bucket['total_value']),
    }


def build_history_chart(history, width=760, height=260, pad=44):
    """Pre-compute SVG geometry for the history chart.

    The app ships no charting library and the templates load nothing from a
    CDN, so the coordinates are worked out here and the template simply emits
    them. Bars are the per-week value; the line is the cumulative total.
    """
    if not history:
        return None

    inner_w = width - pad * 2
    inner_h = height - pad * 2
    baseline = pad + inner_h
    count = len(history)

    # `or 1.0` keeps an all-zero journal (every item unpriced) from dividing
    # by zero and instead draws a flat line along the baseline.
    max_cumulative = max(b['cumulative_value'] for b in history) or 1.0
    max_weekly = max(b['total_value'] for b in history) or 1.0

    step = inner_w / (count - 1) if count > 1 else 0
    bar_width = max(6.0, min(44.0, (inner_w / count) * 0.55))

    points = []
    bars = []
    for index, bucket in enumerate(history):
        x = pad + (step * index if count > 1 else inner_w / 2)
        y = baseline - (bucket['cumulative_value'] / max_cumulative) * inner_h
        points.append((round(x, 2), round(y, 2)))

        bar_height = (bucket['total_value'] / max_weekly) * inner_h
        bars.append({
            'x': round(x - bar_width / 2, 2),
            'y': round(baseline - bar_height, 2),
            'width': round(bar_width, 2),
            'height': round(bar_height, 2),
            'label': bucket['week'],
            'value': bucket['total_value'],
        })

    return {
        'width': width,
        'height': height,
        'pad': pad,
        'baseline': baseline,
        'max_cumulative': max_cumulative,
        'max_weekly': max_weekly,
        'polyline': ' '.join(f'{x},{y}' for x, y in points),
        'points': [{'x': x, 'y': y} for x, y in points],
        'bars': bars,
    }

def cleanup_uploads():
    """Remove old uploads to prevent disk filling up."""
    # In a production app, you might want a more sophisticated cleanup strategy
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        try:
            if os.path.isfile(file_path) and os.path.getmtime(file_path) < time.time() - 3600:
                os.unlink(file_path)
        except Exception as e:
            print(f"Error cleaning up file {file_path}: {e}")

def process_image(image_path):
    """Process an image using the WeeklyDropProcessor.

    Errors deliberately propagate. This used to swallow every exception and
    return [], so a failed model load, an unreadable upload or a screenshot
    with no drop panel all surfaced to the user as the same bare "No items
    were detected in the image" with the real cause visible only in the server
    log. upload_file() renders the exception into the results page instead.
    """
    return get_processor().process_image(image_path, save_crops=False)

# MIME subtype of a pasted data: URL -> file extension we save it under.
PASTED_IMAGE_EXTENSIONS = {
    'png': 'png',
    'jpeg': 'jpg',
    'jpg': 'jpg',
    'webp': 'webp',
    'bmp': 'bmp',
    'gif': 'gif',
}


def decode_pasted_image(image_data):
    """Split a pasted image into (extension, bytes).

    Accepts a `data:image/<type>;base64,...` URL or bare base64 (assumed PNG).
    The subtype used to be copied straight from the request into the saved
    file name, so a crafted header such as `data:image/..\\..\\app.py;base64,`
    chose the path and extension of the written file on Windows, and bytes PIL
    could not parse were then written there verbatim. Now the type must be a
    known image format and the payload must actually decode as an image.

    Raises ValueError for anything else.
    """
    import base64
    import binascii
    from io import BytesIO
    from PIL import Image, UnidentifiedImageError

    if not image_data:
        raise ValueError('no image data received')

    extension = 'png'
    if image_data.startswith('data:'):
        header, sep, image_data = image_data.partition(',')
        match = re.fullmatch(r'data:image/([a-z0-9.+-]+)(;base64)?', header.strip().lower())
        if not sep or not match or not match.group(2):
            raise ValueError('expected a base64 data:image URL')
        subtype = match.group(1)
        if subtype not in PASTED_IMAGE_EXTENSIONS:
            raise ValueError(f'unsupported image type {subtype!r}')
        extension = PASTED_IMAGE_EXTENSIONS[subtype]

    try:
        binary_data = base64.b64decode(image_data, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError('image data is not valid base64')

    try:
        with Image.open(BytesIO(binary_data)) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise ValueError(f'not a readable image ({e.__class__.__name__})')

    return extension, binary_data


def save_pasted_image(binary_data, filepath, max_dimension=2048):
    """Write a decoded pasted image, downscaling very large ones."""
    from io import BytesIO
    from PIL import Image

    img = Image.open(BytesIO(binary_data))
    if img.width > max_dimension or img.height > max_dimension:
        # Preserve aspect ratio; thumbnail() never upscales.
        img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
        print(f"Resized image to {img.width}x{img.height}")
    if filepath.endswith('.jpg') and img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    img.save(filepath, optimize=True, quality=85)


def clean_item_name(name):
    """Clean up the detected item name for better database matching."""
    # Remove OCR artifacts, normalize spacing, etc.
    cleaned = re.sub(r'\s+', ' ', name).strip()
    # Remove common OCR errors or prefixes like "Item X:" if they exist
    cleaned = re.sub(r'^Item \d+:\s*', '', cleaned)
    # Remove [OCR failed] or [Detection failed] markers
    cleaned = re.sub(r'\[.*?\]', '', cleaned).strip()
    return cleaned

def ensure_dict(obj):
    """Ensure an object is converted to a dictionary."""
    if obj is None:
        return {}
    
    if isinstance(obj, dict):
        return obj
    
    # Handle sqlite3.Row objects
    if hasattr(obj, 'keys') and callable(obj.keys):
        try:
            return dict(obj)
        except:
            pass
    
    # Handle objects with __dict__ attribute
    if hasattr(obj, '__dict__'):
        return obj.__dict__
    
    # Handle objects with __slots__
    if hasattr(obj, '__slots__'):
        return {slot: getattr(obj, slot, None) for slot in obj.__slots__}
    
    # If it's an iterable but not a string
    if hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
        try:
            return {i: v for i, v in enumerate(obj)}
        except:
            pass
    
    # If all else fails, just wrap it in a dictionary
    return {'value': obj}

def match_items_in_database(item_names):
    """Match detected item names to the database using the ItemMatcher."""
    results = []
    
    for i, name in enumerate(item_names):
        cleaned_name = clean_item_name(name)
        if not cleaned_name:
            results.append({
                'original': name,
                'cleaned': cleaned_name,
                'status': 'empty',
                'matches': []
            })
            continue
        
        # Use the ItemMatcher to match the item with confidence
        match_result = matcher.match_with_confidence(cleaned_name, threshold=0.4)
        
        if match_result['status'] == 'matched':
            # Convert the matches to the expected format
            match_list = []
            
            # First get the best match
            best_match = ensure_dict(match_result['best_match'])
            best_match_entry = {
                'id': best_match.get('id'),
                'name': best_match.get('name', 'Unknown Item'),
                'collection': best_match.get('collection', ''),
                'price': best_match.get('price'),
                'price_type': best_match.get('price_type', 'unknown'),
                'item_type': best_match.get('item_type', ''),
                'score': match_result['score'],
                'confidence': match_result['confidence']
            }
            
            # First item (index 0) should only show case type items
            if i == 0:
                # Filter to only include case type items
                case_matches = []
                
                # Add the best match if it's a case
                if best_match.get('item_type') == 'case':
                    case_matches.append(best_match_entry)
                
                # Look for case items in other matches, but avoid duplicates
                seen_ids = {best_match.get('id')} if best_match.get('id') else set()
                
                for match_data in match_result['matches']:
                    match_item = ensure_dict(match_data.get('item', {}))
                    item_id = match_item.get('id')
                    
                    # Skip if we've already added this item or if it's not a case
                    if item_id in seen_ids or match_item.get('item_type') != 'case':
                        continue
                        
                    seen_ids.add(item_id)
                    score = match_data.get('score', 0)
                    
                    # Determine confidence level based on score
                    confidence = 'low'
                    if score > 0.85:
                        confidence = 'high'
                    elif score > 0.65:
                        confidence = 'medium'
                    
                    case_matches.append({
                        'id': item_id,
                        'name': match_item.get('name', 'Unknown Item'),
                        'collection': match_item.get('collection', ''),
                        'price': match_item.get('price'),
                        'price_type': match_item.get('price_type', 'unknown'),
                        'item_type': match_item.get('item_type', ''),
                        'score': score,
                        'confidence': confidence
                    })
                
                # Use case matches instead of all matches
                match_list = case_matches
            
            # For graffiti items, only show the best match
            elif best_match.get('item_type') == 'graffiti':
                match_list = [best_match_entry]
            
            # For all other items, process normally
            else:
                # Add the best match
                match_list.append(best_match_entry)
                
                # Add other matches if available
                for match_data in match_result['matches'][1:]:  # Skip the first one as it's already added
                    match_item = ensure_dict(match_data.get('item', {}))
                    score = match_data.get('score', 0)
                    
                    # Determine confidence level based on score
                    confidence = 'low'
                    if score > 0.85:
                        confidence = 'high'
                    elif score > 0.65:
                        confidence = 'medium'
                    
                    match_list.append({
                        'id': match_item.get('id'),
                        'name': match_item.get('name', 'Unknown Item'),
                        'collection': match_item.get('collection', ''),
                        'price': match_item.get('price'),
                        'price_type': match_item.get('price_type', 'unknown'),
                        'item_type': match_item.get('item_type', ''),
                        'score': score,
                        'confidence': confidence
                    })
                
                # Add wear variations if they're not already in the matches
                for variation in match_result['all_wear_variations']:
                    variation = ensure_dict(variation)
                    # Check if this variation is already in the match list
                    if not any(match['id'] == variation.get('id') for match in match_list):
                        match_list.append({
                            'id': variation.get('id'),
                            'name': variation.get('name', 'Unknown Item'),
                            'collection': variation.get('collection', ''),
                            'price': variation.get('price'),
                            'price_type': variation.get('price_type', 'unknown'),
                            'item_type': variation.get('item_type', ''),
                            'score': 0.0,  # No direct match score
                            'confidence': 'variation'  # Mark as a variation
                        })
            
            results.append({
                'original': name,
                'cleaned': cleaned_name,
                'status': 'found',
                'matches': match_list
            })
        else:
            # No matches found
            results.append({
                'original': name,
                'cleaned': cleaned_name,
                'status': 'not_found',
                'matches': []
            })
    
    return results


def _as_price(value):
    """Coerce a stored price into a float, tolerating None and junk strings.

    Prices arrive from SQLite and from the Steam scrapers, so a column can hold
    a REAL, a string like "1.23", or NULL for an item that has never been
    priced. Anything that is not a usable non-negative number becomes None so
    that it is simply excluded from the comparison rather than crashing it.
    """
    if value is None:
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price < 0:
        return None
    return price


def annotate_recommendation(item_results):
    """Tag the highest-value drop so the UI can recommend it.

    README.md:5 and :12 advertise that the app "automatically recommends the
    highest-value item", and the usage steps at README.md:126 tell the user the
    recommendation will be highlighted -- but no code ever implemented it. The
    results page was a flat checkbox list ordered by OCR match score
    (item_matcher.py:327 sorts on 'score'), which has nothing to do with price.

    For each of the four detected slots we pick the priciest candidate match,
    then mark the single most valuable slot overall. Both the slot and the
    winning match get flagged so the template can highlight the exact checkbox
    rather than just the box it lives in.

    Returns the recommended slot dict, or None when nothing anywhere has a
    known price (an unpriced database is the common first-run state).
    """
    best_slot = None

    for result in item_results:
        best_match = None

        for match in result.get('matches') or []:
            price = _as_price(match.get('price'))
            # Keep the parsed value so the template can format it without
            # re-parsing, and so unpriced rows stay visually distinct.
            match['price_value'] = price
            if price is None:
                continue
            if best_match is None or price > best_match['price_value']:
                best_match = match

        result['best_match'] = best_match
        result['best_price'] = best_match['price_value'] if best_match else None

        if best_match is not None and (
            best_slot is None or best_match['price_value'] > best_slot['best_price']
        ):
            best_slot = result

    if best_slot is not None:
        best_slot['recommended'] = True
        best_slot['best_match']['recommended'] = True

    return best_slot


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
                except Exception as e:
                    conn.rollback()
                    error = f"Error creating user: {str(e)}"
        
        if error:
            flash(error, 'error')
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login page."""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = 'remember' in request.form
        
        error = None
        if not username:
            error = 'Username is required.'
        elif not password:
            error = 'Password is required.'
            
        if error is None:
            conn = get_db()
            user = conn.execute(
                'SELECT id, username, password_hash FROM users WHERE username = ?',
                (username,)
            ).fetchone()
            
            if user is None:
                error = 'Invalid username.'
            elif not check_password_hash(user['password_hash'], password):
                error = 'Invalid password.'
            else:
                # Login successful
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

                # Log the login
                print(f"User {username} logged in with 'remember me' set to {remember}")
                
                # Redirect to next page if specified, otherwise to index
                next_page = request.args.get('next')
                if is_safe_redirect(next_page):
                    return redirect(next_page)
                return redirect(url_for('index'))
        
        if error:
            flash(error, 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Log out the current user."""
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
        chart=build_history_chart(buckets)
    )


@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    """Handle file upload or pasted image."""
    try:
        # Handle RequestEntityTooLarge exception
        # This will catch the 413 error before it becomes an HTTP response
        if request.content_length and request.content_length > app.config['MAX_CONTENT_LENGTH']:
            raise RequestEntityTooLarge("The uploaded file is too large. Maximum size is 256MB.")
            
        # Check if cleanup is needed
        cleanup_uploads()
        
        # Get current user
        user = get_current_user()
        if not user:
            return redirect(url_for('login'))
        
        # Generate a unique screenshot ID for this upload
        screenshot_id = str(uuid.uuid4())
        
        # Debug information
        print(f"Form data keys: {list(request.form.keys())}")
        print(f"Files: {list(request.files.keys())}")
        
        # Handle file upload
        if 'file' in request.files and request.files['file'].filename:
            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400
                
            # Generate a unique filename
            filename = secure_filename(f"{screenshot_id}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            print(f"Saved uploaded file to {filepath}")
        
        # Handle pasted image
        elif 'image_data' in request.form and request.form['image_data']:
            try:
                extension, binary_data = decode_pasted_image(request.form['image_data'])
            except ValueError as paste_error:
                print(f"Rejected pasted image: {paste_error}")
                return jsonify({'error': f'Error processing pasted image: {paste_error}'}), 400

            # The extension comes from PASTED_IMAGE_EXTENSIONS, never from the
            # request, so the path cannot escape UPLOAD_FOLDER.
            filename = f"{screenshot_id}.{extension}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            save_pasted_image(binary_data, filepath)
            print(f"Saved pasted image to {filepath}")
        else:
            print("Neither file nor image data found in the request")
            return jsonify({'error': 'No file or image data provided'}), 400
        
        # Process the image
        item_names = process_image(filepath)
        print(f"Detected {len(item_names)} items in the image")
        
        # Match items to database
        try:
            matched_items = match_items_in_database(item_names)
        except Exception as e:
            print(f"Error matching items: {e}")
            return render_template(
                'results.html', 
                error=f"Error processing items: {e}",
                screenshot_id=screenshot_id,
                item_results=[],
                user=user,
                journal=get_user_journal(user['id']),
                total_value=get_journal_total(get_user_journal(user['id']))
            )
        
        # Work out which of the four drops is worth the most. This mutates
        # matched_items in place, tagging the winning slot and match.
        recommendation = annotate_recommendation(matched_items)

        # Return the results
        return render_template(
            'results.html',
            screenshot_id=screenshot_id,
            item_results=matched_items,
            recommendation=recommendation,
            user=user,
            journal=get_user_journal(user['id']),
            total_value=get_journal_total(get_user_journal(user['id']))
        )
        
    except Exception as e:
        print(f"Error processing upload: {e}")
        import traceback
        traceback.print_exc()
        
        user = get_current_user()
        journal = get_user_journal(user['id']) if user else []
        error_msg = str(e)
        return render_template(
            'results.html', 
            error=f"Error processing the image: {error_msg}",
            screenshot_id="",
            item_results=[],
            user=user,
            journal=journal,
            total_value=get_journal_total(journal)
        )

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
    
    try:
        conn = get_db()
        
        for item_id in item_ids:
            cur = conn.execute(
                "SELECT id, name, collection, price, price_type, item_type FROM items WHERE id = ?",
                (item_id,)
            )
            item = cur.fetchone()
            
            if item:
                # Ensure item is a dictionary
                item_dict = ensure_dict(item)
                
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
        
    except Exception as e:
        print(f"Error adding items to journal: {e}")
        conn.rollback()
        flash(f"Error adding items to journal: {str(e)}", 'error')
    
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
    
    try:
        conn = get_db()
        
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
        
    except Exception as e:
        print(f"Error removing item from journal: {e}")
        conn.rollback()
        flash(f"Error removing item: {str(e)}", 'error')
    
    return redirect(url_for('index'))

@app.route('/clear_journal', methods=['POST'])
@login_required
def clear_journal():
    """Clear all items from the user's journal."""
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))
    
    try:
        conn = get_db()
        conn.execute(
            "DELETE FROM user_journals WHERE user_id = ?",
            (user['id'],)
        )
        conn.commit()
        flash('Your journal has been cleared.', 'success')
    except Exception as e:
        print(f"Error clearing journal: {e}")
        conn.rollback()
        flash(f"Error clearing journal: {str(e)}", 'error')
    
    return redirect(url_for('index'))

# Custom error handlers
@app.errorhandler(RequestEntityTooLarge)
def handle_request_entity_too_large(error):
    """Handle 413 Request Entity Too Large error."""
    print(f"413 Error: {error}")
    flash('The image you uploaded is too large. Please reduce its size or upload a different image.', 'error')
    return redirect(url_for('index'))

@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle 413 Request Entity Too Large error (HTTP version)."""
    print(f"HTTP 413 Error: {error}")
    flash('The image you uploaded is too large. Please reduce its size or upload a different image.', 'error')
    return redirect(url_for('index'))


def update_prices_job():
    """
    Job that runs daily to update prices for specific collections/items.
    Runs in a separate process to avoid database locking issues.
    """
    app.logger.info("Running scheduled price update job")
    
    try:
        # Path to the configuration file, resolved against the repo root so the
        # job does not depend on the process working directory.
        config_path = os.environ.get(
            'PRICE_UPDATE_CONFIG', os.path.join(BASE_DIR, 'price_update_config.json')
        )

        # Write a working default rather than giving up. .gitignore used to
        # ignore all *.json, so this file could never be committed and the job
        # bailed out here on every install -- the advertised "real-time price
        # tracking" never ran for anyone.
        if not os.path.exists(config_path):
            app.logger.warning(
                f"Price update configuration not found at {config_path}; writing defaults."
            )
            try:
                with open(config_path, 'w') as f:
                    json.dump(DEFAULT_PRICE_UPDATE_CONFIG, f, indent=2)
            except OSError as e:
                app.logger.error(f"Could not write default price config: {e}")
                return

        # Read configuration
        with open(config_path, 'r') as f:
            config = json.load(f)

        collections = config.get('collections', [])
        max_items = config.get('max_items', 100)
        batch_size = config.get('batch_size', 100)

        app.logger.info(f"Updating prices for collections: {collections}, max items: {max_items}")

        # Run the bulk scraper as a separate process to avoid database locking.
        #
        # This used to invoke 'src/DB/update_price.py'. Two bugs in one line:
        #   1. The directory is 'Src/DB', capital S. Windows' case-insensitive
        #      filesystem hid it; on Linux and macOS the subprocess just failed,
        #      so the advertised daily price update silently never ran.
        #   2. update_price.py sleeps 15 s before EVERY single item request
        #      (Src/DB/update_price.py:26). Against a 20k+ row database that is
        #      over three days of continuous scraping for one refresh.
        #      bulk_scraper.py fetches 100 items per request instead.
        #
        # Paths are now built from this file's own location so the job works
        # regardless of the process working directory.
        db_path = os.path.abspath(app.config['DATABASE'])
        scraper_path = os.path.join(BASE_DIR, 'Src', 'DB', 'bulk_scraper.py')

        if not os.path.exists(scraper_path):
            app.logger.error(f"Bulk scraper not found at {scraper_path}")
            return

        # Build command for subprocess
        cmd = [
            sys.executable,  # Python executable
            scraper_path,
            '--db', db_path
        ]

        # Add collections if specified
        if collections:
            cmd.append('--collections')
            cmd.extend(collections)

        # Add max items if specified
        if max_items:
            cmd.append('--max')
            cmd.append(str(max_items))

        # Number of items to pull per Steam request
        if batch_size:
            cmd.append('--batch-size')
            cmd.append(str(batch_size))

        app.logger.info(f"Executing command: {' '.join(cmd)}")
        
        # Execute the command in a separate process
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=BASE_DIR)
        
        if result.returncode == 0:
            app.logger.info(f"Price update completed: {result.stdout}")
        else:
            # The scraper reports progress on stdout; keep its tail so the log
            # shows where an interrupted crawl stopped, not just stderr.
            app.logger.error(
                f"Price update failed (exit {result.returncode}): {result.stderr}\n"
                f"{result.stdout[-2000:]}"
            )
        
        
    except Exception as e:
        app.logger.error(f"Error running price update job: {e}")
        import traceback
        app.logger.error(traceback.format_exc())

# At the module level (outside any function)
scheduler = None

def init_scheduler():
    """Initialize and start the scheduler for periodic tasks."""
    global scheduler
    
    # If scheduler is already running, shut it down first
    if scheduler is not None and scheduler.running:
        app.logger.info("Shutting down existing scheduler...")
        scheduler.shutdown(wait=False)
    
    scheduler = BackgroundScheduler()
    
    # Schedule the regular job
    scheduler.add_job(
        update_prices_job,
        trigger=CronTrigger(hour=0, minute=0, timezone='UTC'),
        id='price_update_job',
        name='Daily price update',
        replace_existing=True
    )
    from datetime import datetime
    from apscheduler.triggers.date import DateTrigger
    
    '''scheduler.add_job(
        update_prices_job,
        trigger=DateTrigger(run_date=datetime.now()),
        id='price_update_test_job',
        name='Immediate test update'
    )'''
    
    # Start the scheduler
    scheduler.start()
    app.logger.info("Scheduler started, price updates will run daily at 00:00 UTC")
    
    # Register shutdown function 
    import atexit
    atexit.register(shutdown_scheduler)
    
def shutdown_scheduler():
    """Safely shut down the scheduler."""
    global scheduler
    if scheduler is not None and scheduler.running:
        app.logger.info("Shutting down scheduler...")
        try:
            scheduler.shutdown(wait=False)
            app.logger.info("Scheduler successfully shut down")
        except Exception as e:
            app.logger.error(f"Error shutting down scheduler: {e}")

if __name__ == '__main__':
    # Initialize the scheduler for daily price updates
    init_scheduler()

    # debug=True was hard-coded. Werkzeug's debugger exposes an interactive
    # Python console on any unhandled exception, so shipping it on by default
    # is remote code execution the moment the app is reachable off localhost.
    # It is now opt-in via FLASK_DEBUG.
    debug_mode = _env_bool('FLASK_DEBUG', False)
    host = os.environ.get('FLASK_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_PORT', '5000'))

    app.run(host=host, port=port, debug=debug_mode, use_reloader=False)
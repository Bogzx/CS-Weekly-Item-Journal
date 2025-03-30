import os
import uuid
import time
import re
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, g
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

# Load variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

# Configure the session to use cookies
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 256 * 1024 * 1024  # 256MB max upload (increased from 128MB)
app.config['MAX_CONTENT_PATH'] = 16 * 1024 * 1024  # 16MB max for form fields
app.config['DATABASE'] = 'csgo_items.db'
app.config['MODEL_PATH'] = os.path.join('Models', 'BOX_TRAINED.pt')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=120)  # Set default to 30 days
app.config['SESSION_COOKIE_SECURE'] = True  # Set to False if not using HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Increase request size limits for Werkzeug
app.config['MAX_FORM_MEMORY_SIZE'] = 64 * 1024 * 1024  # 64MB for form data

# Ensure the upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize the weekly drop processor
processor = WeeklyDropProcessor(app.config['MODEL_PATH'])

# Initialize the item matcher
matcher = ItemMatcher(app.config['DATABASE'])

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
    """Process an image using the WeeklyDropProcessor."""
    try:
        # Process the image and get the detected text for each item
        item_names = processor.process_image(image_path, save_crops=False)
        return item_names
    except Exception as e:
        print(f"Error processing image: {e}")
        return []

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
                
                # Set session to permanent if remember me is checked
                if remember:
                    # This makes the session permanent with the lifetime configured in app.config
                    session.permanent = True
                else:
                    # For non-remembered sessions, set a shorter lifetime (e.g., 1 hour)
                    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
                    session.permanent = True
                    # Reset back to the default for other users
                    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=120)
                
                # Log the login
                print(f"User {username} logged in with 'remember me' set to {remember}")
                
                # Redirect to next page if specified, otherwise to index
                next_page = request.args.get('next')
                if next_page and next_page.startswith('/'):  # Ensure it's a relative URL
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
                import base64
                from io import BytesIO
                from PIL import Image
                
                image_data = request.form['image_data']
                print(f"Received image data of length: {len(image_data)}")
                
                if not image_data:
                    return jsonify({'error': 'No image data received'}), 400
                    
                # Strip the Data URL header if it exists
                if 'data:image' in image_data:
                    # Get the image format from the header
                    image_format = image_data.split(';')[0].split('/')[1]
                    image_data = image_data.split(',')[1]
                else:
                    image_format = 'png'  # Default format
                
                # Generate a unique filename for the pasted image
                filename = f"{screenshot_id}.{image_format}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                
                # First try to decode and optimize the image before saving
                try:
                    # Decode base64 to binary data
                    binary_data = base64.b64decode(image_data)
                    
                    # Open image with PIL
                    img = Image.open(BytesIO(binary_data))
                    
                    # Resize if the image is very large
                    max_dimension = 2048  # Set a reasonable max dimension
                    if img.width > max_dimension or img.height > max_dimension:
                        # Calculate new dimensions while preserving aspect ratio
                        if img.width > img.height:
                            new_width = max_dimension
                            new_height = int(img.height * (max_dimension / img.width))
                        else:
                            new_height = max_dimension
                            new_width = int(img.width * (max_dimension / img.height))
                            
                        img = img.resize((new_width, new_height), Image.LANCZOS)
                        print(f"Resized image to {new_width}x{new_height}")
                    
                    # Save the optimized image
                    img.save(filepath, optimize=True, quality=85)
                    print(f"Saved optimized pasted image to {filepath}")
                    
                except Exception as img_error:
                    print(f"Error optimizing image: {img_error}, falling back to direct save")
                    # Fall back to direct save if optimization fails
                    with open(filepath, 'wb') as f:
                        f.write(binary_data)
                    print(f"Saved pasted image to {filepath}")
            
            except Exception as paste_error:
                print(f"Error processing pasted image: {paste_error}")
                return jsonify({'error': f'Error processing pasted image: {str(paste_error)}'}), 400
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
        
        # Return the results
        return render_template(
            'results.html', 
            screenshot_id=screenshot_id,
            item_results=matched_items,
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
        # Path to the configuration file
        config_path = os.environ.get('PRICE_UPDATE_CONFIG', 'price_update_config.json')
        
        if not os.path.exists(config_path):
            app.logger.warning(f"Price update configuration file not found: {config_path}")
            return
            
        # Read configuration
        with open(config_path, 'r') as f:
            config = json.load(f)
            
        collections = config.get('collections', [])
        max_items = config.get('max_items', 100)
        retry_on_rate_limit = config.get('retry_on_rate_limit', True)
        all_cases_graffiti = config.get('all_cases_graffiti', False)
        
        app.logger.info(f"Updating prices for collections: {collections}, max items: {max_items}")
        
        # Run update_price.py as a separate process to avoid database locking
        db_path = app.config['DATABASE']
        
        # Build command for subprocess
        cmd = [
            sys.executable,  # Python executable
            'src/DB/update_price.py',
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
            
        # Add no-retry flag if retry is disabled
        if not retry_on_rate_limit:
            cmd.append('--no-retry')
            
        # Add cases and graffiti flag if specified
        if all_cases_graffiti:
            cmd.append('--all-cases-graffiti')
        
        app.logger.info(f"Executing command: {' '.join(cmd)}")
        
        # Execute the command in a separate process
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            app.logger.info(f"Price update completed: {result.stdout}")
        else:
            app.logger.error(f"Price update failed: {result.stderr}")
        
        
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
    app.run(debug=True,use_reloader=False)
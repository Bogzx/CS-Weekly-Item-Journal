import os
import uuid
import time
import re
import sqlite3
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.utils import secure_filename
from Src.ImageDetector.modified_detect_text import WeeklyDropProcessor
from Src.ImageDetector.item_matcher import ItemMatcher

app = Flask(__name__)
app.secret_key = os.urandom(24)  # For session management
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload
app.config['DATABASE'] = 'csgo_items.db'
app.config['MODEL_PATH'] = os.path.join('Models', 'BOX_TRAINED.pt')

# Ensure the upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize the weekly drop processor
processor = WeeklyDropProcessor(app.config['MODEL_PATH'])

# Initialize the item matcher
matcher = ItemMatcher(app.config['DATABASE'])

# Check if price_type column exists in the database and add it if needed
def initialize_database():
    """Check if the database has all required columns and add them if needed."""
    conn = sqlite3.connect(app.config['DATABASE'])
    cursor = conn.cursor()
    try:
        # Try to add price_type column if it doesn't exist
        cursor.execute("ALTER TABLE items ADD COLUMN price_type TEXT")
        print("Added price_type column to items table")
    except sqlite3.OperationalError:
        # Column already exists, which is fine
        pass
    conn.commit()
    conn.close()

# Initialize the database
initialize_database()

def get_db_connection():
    """Get a connection to the SQLite database."""
    conn = sqlite3.connect(app.config['DATABASE'])
    # Set row_factory to return dictionaries instead of Row objects
    conn.row_factory = lambda cursor, row: {
        column[0]: row[idx] for idx, column in enumerate(cursor.description)
    }
    return conn

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

@app.route('/')
def index():
    """Main page with upload form."""
    # Initialize the journal in session if it doesn't exist
    if 'journal' not in session:
        session['journal'] = []
    
    # Calculate total value of items in journal
    total_value = sum(float(item.get('price', 0) or 0) for item in session['journal'])
    
    return render_template('index.html', journal=session['journal'], total_value=total_value)

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload or pasted image."""
    try:
        # Check if cleanup is needed
        cleanup_uploads()
        
        # Generate a unique screenshot ID for this upload
        screenshot_id = str(uuid.uuid4())
        
        # Handle file upload
        if 'file' in request.files:
            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400
                
            # Generate a unique filename
            filename = secure_filename(f"{screenshot_id}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
        
        # Handle pasted image
        elif 'image_data' in request.form:
            import base64
            image_data = request.form['image_data']
            if not image_data:
                return jsonify({'error': 'No image data received'}), 400
                
            # Strip the Data URL header if it exists
            if 'data:image' in image_data:
                image_data = image_data.split(',')[1]
                
            # Generate a unique filename for the pasted image
            filename = f"{screenshot_id}.png"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Save the image data
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(image_data))
        else:
            return jsonify({'error': 'No file or image data provided'}), 400
        
        # Process the image
        item_names = process_image(filepath)
        
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
                journal=session.get('journal', []),
                total_value=sum(float(item.get('price', 0) or 0) for item in session.get('journal', []))
            )
        
        # Return the results
        return render_template(
            'results.html', 
            screenshot_id=screenshot_id,
            item_results=matched_items,
            journal=session.get('journal', []),
            total_value=sum(float(item.get('price', 0) or 0) for item in session.get('journal', []))
        )
        
    except Exception as e:
        print(f"Error processing upload: {e}")
        error_msg = str(e)
        return render_template(
            'results.html', 
            error=f"Error processing the image: {error_msg}",
            item_results=[],
            journal=session.get('journal', []),
            total_value=sum(float(item.get('price', 0) or 0) for item in session.get('journal', []))
        )

@app.route('/add_to_journal', methods=['POST'])
def add_to_journal():
    """Add selected items to the user's journal."""
    # Get the item IDs - this can be a single ID or multiple IDs (up to 2)
    item_ids = request.form.getlist('item_id')
    if not item_ids:
        return redirect(url_for('index'))
    
    # Limit to adding at most 2 items at a time
    item_ids = item_ids[:2]
    
    try:
        conn = get_db_connection()
        journal = session.get('journal', [])
        
        for item_id in item_ids:
            cur = conn.execute(
                "SELECT id, name, collection, price, price_type, item_type FROM items WHERE id = ?",
                (item_id,)
            )
            item = cur.fetchone()
            
            if item:
                # Ensure item is a dictionary
                item_dict = ensure_dict(item)
                
                # Create a journal item with safe access
                journal_item = {
                    'id': item_dict.get('id'),
                    'name': item_dict.get('name', 'Unknown Item'),
                    'collection': item_dict.get('collection', ''),
                    'price': item_dict.get('price'),
                    'price_type': item_dict.get('price_type', 'unknown'),
                    'item_type': item_dict.get('item_type', ''),
                    'timestamp': time.time(),
                    'screenshot_id': request.form.get('screenshot_id', str(uuid.uuid4()))  # Track which screenshot this came from
                }
                
                # Add to journal in session
                journal.append(journal_item)
        
        conn.close()
        session['journal'] = journal
        
    except Exception as e:
        print(f"Error adding items to journal: {e}")
    
    return redirect(url_for('index'))

@app.route('/remove_from_journal', methods=['POST'])
def remove_from_journal():
    """Remove an item from the journal."""
    item_id = request.form.get('item_id')
    timestamp = request.form.get('timestamp')
    
    if not item_id or not timestamp:
        return redirect(url_for('index'))
    
    journal = session.get('journal', [])
    journal = [item for item in journal if not (str(item.get('id')) == item_id and str(item.get('timestamp')) == timestamp)]
    session['journal'] = journal
    
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
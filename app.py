import os
import uuid
import time
import re
import sqlite3
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.utils import secure_filename
from Src.ImageDetector.modified_detect_text import WeeklyDropProcessor

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

def get_db_connection():
    """Get a connection to the SQLite database."""
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
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

def match_items_in_database(item_names):
    """Match detected item names to the database."""
    results = []
    conn = get_db_connection()
    
    for name in item_names:
        cleaned_name = clean_item_name(name)
        if not cleaned_name:
            results.append({
                'original': name,
                'cleaned': cleaned_name,
                'status': 'empty',
                'matches': []
            })
            continue
            
        # Try exact match first
        cur = conn.execute(
            "SELECT id, name, collection, price, price_type, item_type FROM items WHERE name = ?",
            (cleaned_name,)
        )
        matches = cur.fetchall()
        
        # If no exact match, try partial match using LIKE
        if not matches:
            search_term = f"%{cleaned_name}%"
            cur = conn.execute(
                "SELECT id, name, collection, price, price_type, item_type FROM items WHERE name LIKE ?",
                (search_term,)
            )
            matches = cur.fetchall()
        
        # Convert matches to dictionaries for easier handling in templates
        match_list = []
        for match in matches:
            match_list.append({
                'id': match['id'],
                'name': match['name'],
                'collection': match['collection'],
                'price': match['price'],
                'price_type': match['price_type'],
                'item_type': match['item_type']
            })
        
        results.append({
            'original': name,
            'cleaned': cleaned_name,
            'status': 'found' if match_list else 'not_found',
            'matches': match_list
        })
    
    conn.close()
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
        
        # Handle file upload
        if 'file' in request.files:
            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400
                
            # Generate a unique filename
            filename = secure_filename(f"{uuid.uuid4()}_{file.filename}")
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
            filename = f"{uuid.uuid4()}.png"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Save the image data
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(image_data))
        else:
            return jsonify({'error': 'No file or image data provided'}), 400
        
        # Process the image
        item_names = process_image(filepath)
        
        # Match items to database
        matched_items = match_items_in_database(item_names)
        
        # Return the results
        return render_template(
            'results.html', 
            item_results=matched_items,
            journal=session.get('journal', []),
            total_value=sum(float(item.get('price', 0) or 0) for item in session.get('journal', []))
        )
        
    except Exception as e:
        print(f"Error processing upload: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/add_to_journal', methods=['POST'])
def add_to_journal():
    """Add a selected item to the user's journal."""
    item_id = request.form.get('item_id')
    if not item_id:
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cur = conn.execute(
        "SELECT id, name, collection, price, price_type, item_type FROM items WHERE id = ?",
        (item_id,)
    )
    item = cur.fetchone()
    conn.close()
    
    if not item:
        return redirect(url_for('index'))
    
    # Create a journal item
    journal_item = {
        'id': item['id'],
        'name': item['name'],
        'collection': item['collection'],
        'price': item['price'],
        'price_type': item['price_type'],
        'item_type': item['item_type'],
        'timestamp': time.time()
    }
    
    # Add to journal in session
    journal = session.get('journal', [])
    journal.append(journal_item)
    session['journal'] = journal
    
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
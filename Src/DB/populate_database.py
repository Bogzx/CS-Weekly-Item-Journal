import sqlite3
import csv
import argparse
import os
import urllib.parse
from datetime import datetime

def read_csv_file(file_path):
    """
    Read a CSV file and return the data as a list of dictionaries
    
    Parameters:
    - file_path (str): Path to the CSV file
    
    Returns:
    - list: List of dictionaries containing the CSV data
    """
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} not found")
        return []
    
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        print(f"CSV headers for {file_path}: {reader.fieldnames}")
        for row in reader:
            data.append(row)
    return data

def populate_collections(conn, collections):
    """
    Add collections to the collections table
    
    Parameters:
    - conn: SQLite connection
    - collections (list): List of collection names
    """
    cursor = conn.cursor()
    for collection in collections:
        cursor.execute("INSERT OR IGNORE INTO collections (name) VALUES (?)", (collection,))
    conn.commit()

def generate_quality_url(base_url, quality):
    """
    Generate a Steam Market API URL for a specific quality of an item
    
    Parameters:
    - base_url (str): Base Steam Market API URL
    - quality (str): Wear quality to add (e.g., "Factory New")
    
    Returns:
    - str: Properly formatted URL for the specified quality
    """
    # If the URL contains market_hash_name parameter, we need to modify it
    if 'market_hash_name=' in base_url:
        # Split the URL at the market_hash_name parameter
        parts = base_url.split('market_hash_name=')
        prefix = parts[0]
        suffix = parts[1]
        
        # If there are more parameters after market_hash_name
        if '&' in suffix:
            hash_name = suffix.split('&')[0]
            extra_params = '&' + '&'.join(suffix.split('&')[1:])
        else:
            hash_name = suffix
            extra_params = ''
        
        # Decode the URL-encoded hash_name
        decoded_hash_name = urllib.parse.unquote(hash_name)
        
        # Remove any existing quality information
        base_name = decoded_hash_name
        for q in ["Factory New", "Minimal Wear", "Field-Tested", "Well-Worn", "Battle-Scarred"]:
            if f" ({q})" in decoded_hash_name:
                base_name = decoded_hash_name.replace(f" ({q})", "")
                break
        
        # Create new hash_name with the desired quality
        new_hash_name = f"{base_name} ({quality})"
        
        # URL encode the new hash_name
        encoded_new_hash_name = urllib.parse.quote(new_hash_name)
        
        # Reconstruct the URL
        new_url = f"{prefix}market_hash_name={encoded_new_hash_name}{extra_params}"
        
        return new_url
    
    # If the URL doesn't have market_hash_name, return it unchanged
    return base_url

def populate_skins(conn, skins_data, target_collections=None):
    """
    Add skin items to the database with all wear qualities
    
    Parameters:
    - conn: SQLite connection
    - skins_data (list): List of dictionaries containing skin data
    - target_collections (list): Optional list of collections to filter by
    
    Returns:
    - int: Number of items added
    """
    cursor = conn.cursor()
    counter = 0
    
    # Define all wear qualities
    wear_qualities = [
        "Factory New",
        "Minimal Wear", 
        "Field-Tested", 
        "Well-Worn",
        "Battle-Scarred"
    ]
    
    for skin in skins_data:
        collection = skin.get('Collection', '')
        
        # Skip if not in target collections (if specified)
        if target_collections and collection not in target_collections:
            continue
            
        weapon = skin.get('Weapon', '')
        skin_name = skin.get('Skin', '')
        original_quality = skin.get('Quality', '')
        
        # Original API URL (likely for Factory New condition)
        original_url = skin.get('Steam Market API URL', '')
        
        # Create entries for each wear quality
        for wear_quality in wear_qualities:
            # For skins, combine weapon and skin name for the full item name with wear quality
            item_name = f"{weapon} | {skin_name} ({wear_quality})" if skin_name else f"{weapon} ({wear_quality})"
            
            # Generate URL for this quality
            url = generate_quality_url(original_url, wear_quality)
            
            try:
                cursor.execute('''
                INSERT OR IGNORE INTO items (name, collection, market_api_url, item_type, last_updated)
                VALUES (?, ?, ?, ?, ?)
                ''', (item_name, collection, url, 'skin', datetime.now()))
                
                if cursor.rowcount > 0:
                    counter += 1
                    if counter % 100 == 0:  # Log progress every 100 items
                        print(f"Added {counter} skin variants so far...")
            except sqlite3.Error as e:
                print(f"Error inserting {item_name}: {e}")
    
    conn.commit()
    return counter

def populate_cases(conn, cases_data, target_collections=None):
    """
    Add case items to the database
    
    Parameters:
    - conn: SQLite connection
    - cases_data (list): List of dictionaries containing case data
    - target_collections (list): Optional list of collections to filter by
    
    Returns:
    - int: Number of items added
    """
    cursor = conn.cursor()
    counter = 0
    
    # Debug: Print a sample case data to see column names
    if cases_data:
        print("Sample case data keys:", list(cases_data[0].keys()))
    
    for case in cases_data:
        # Try different possible column names for the case name
        case_name = None
        for key in ['Case', 'Case Steam', 'Name']:
            if key in case:
                case_name = case[key]
                break
        
        if not case_name:
            print(f"Warning: Could not find case name in row: {case}")
            continue
        
        # Skip if not in target collections (if specified)
        if target_collections and case_name not in target_collections:
            continue
        
        # Try different possible column names for the URL
        url = None
        for key in ['Steam Market API URL', 'Market API URL', 'URL', 'SteamMarketURL']:
            if key in case:
                url = case[key]
                break
        
        if not url:
            print(f"Warning: Could not find URL for case {case_name}")
            continue
            
        try:
            cursor.execute('''
            INSERT OR IGNORE INTO items (name, collection, market_api_url, item_type, last_updated)
            VALUES (?, ?, ?, ?, ?)
            ''', (case_name, case_name, url, 'case', datetime.now()))
            
            if cursor.rowcount > 0:
                counter += 1
                print(f"Added case: {case_name}")
        except sqlite3.Error as e:
            print(f"Error inserting {case_name}: {e}")
    
    conn.commit()
    return counter

def populate_graffiti(conn, graffiti_data, target_collections=None):
    """
    Add graffiti items to the database
    
    Parameters:
    - conn: SQLite connection
    - graffiti_data (list): List of dictionaries containing graffiti data
    - target_collections (list): Optional list of collections to filter by
    
    Returns:
    - int: Number of items added
    """
    cursor = conn.cursor()
    counter = 0
    
    # Debug: Print a sample graffiti data to see column names
    if graffiti_data:
        print("Sample graffiti data keys:", list(graffiti_data[0].keys()))
    
    for graffiti in graffiti_data:
        # Get collection and name information
        collection = graffiti.get('Collection', '')
        
        # Use FullName as primary name if available, otherwise use Name
        graffiti_name = graffiti.get('FullName', graffiti.get('Name', ''))
        
        if not graffiti_name:
            print(f"Warning: Could not find graffiti name in row: {graffiti}")
            continue
        
        # Skip if not in target collections (if specified)
        if target_collections and collection not in target_collections:
            continue
        
        # Try different possible column names for the URL
        url = None
        for key in ['SteamMarketURL', 'Steam Market API URL', 'Market API URL', 'URL']:
            if key in graffiti:
                url = graffiti[key]
                break
        
        if not url:
            print(f"Warning: Could not find URL for graffiti {graffiti_name}")
            continue
            
        try:
            cursor.execute('''
            INSERT OR IGNORE INTO items (name, collection, market_api_url, item_type, last_updated)
            VALUES (?, ?, ?, ?, ?)
            ''', (graffiti_name, collection, url, 'graffiti', datetime.now()))
            
            if cursor.rowcount > 0:
                counter += 1
                if counter % 20 == 0:  # Log progress every 20 items
                    print(f"Added {counter} graffiti so far...")
        except sqlite3.Error as e:
            print(f"Error inserting {graffiti_name}: {e}")
    
    conn.commit()
    return counter

def main():
    parser = argparse.ArgumentParser(description='Populate CS:GO items database with specific collections')
    parser.add_argument('--db', type=str, default='csgo_items.db', help='Path to SQLite database')
    parser.add_argument('--skins', type=str, default='cs_skins.csv', help='Path to skins CSV file')
    parser.add_argument('--cases', type=str, default='cs_cases.csv', help='Path to cases CSV file')
    parser.add_argument('--graffiti', type=str, default='cs_graffiti.csv', help='Path to graffiti CSV file')
    parser.add_argument('--collections', type=str, nargs='+', 
                        help='List of collections to include (if not specified, all will be included)')
    parser.add_argument('--list-collections', action='store_true', help='List all available collections and exit')
    parser.add_argument('--cases-only', action='store_true', help='Import only cases, not skins or graffiti')
    parser.add_argument('--skins-only', action='store_true', help='Import only skins, not cases or graffiti')
    parser.add_argument('--graffiti-only', action='store_true', help='Import only graffiti, not cases or skins')
    parser.add_argument('--debug', action='store_true', help='Print debug information')
    parser.add_argument('--no-quality-variants', action='store_true', 
                        help='Do not create multiple quality variants for each skin')
    
    args = parser.parse_args()
    
    # Check if database exists, if not, suggest creating it
    if not os.path.exists(args.db):
        print(f"Database {args.db} not found. Please run create_database.py first.")
        return
    
    # Connect to database
    conn = sqlite3.connect(args.db)
    
    # Determine what to import based on flags
    import_skins = not (args.cases_only or args.graffiti_only)
    import_cases = not (args.skins_only or args.graffiti_only)
    import_graffiti = not (args.cases_only or args.skins_only)
    
    # Load data from CSV files
    skins_data = [] if not import_skins else read_csv_file(args.skins)
    cases_data = [] if not import_cases else read_csv_file(args.cases)
    graffiti_data = [] if not import_graffiti else read_csv_file(args.graffiti)
    
    if args.debug:
        if cases_data:
            print(f"Loaded {len(cases_data)} cases from {args.cases}")
            if cases_data:
                print("First case data:", cases_data[0])
        if skins_data:
            print(f"Loaded {len(skins_data)} skins from {args.skins}")
        if graffiti_data:
            print(f"Loaded {len(graffiti_data)} graffiti from {args.graffiti}")
    
    if not skins_data and not cases_data and not graffiti_data:
        print("No data loaded. Please check CSV file paths.")
        conn.close()
        return
    
    # Get all available collections for skins
    all_skin_collections = set(skin.get('Collection', '') for skin in skins_data if skin.get('Collection'))
    
    # Get all available case names - try different possible column names
    all_case_names = set()
    for case in cases_data:
        for key in ['Case', 'Case Steam', 'Name']:
            if key in case and case[key]:
                all_case_names.add(case[key])
                break
    
    # Get all available graffiti collections
    all_graffiti_collections = set(graffiti.get('Collection', '') for graffiti in graffiti_data if graffiti.get('Collection'))
    
    # Combine all available collections
    all_collections = all_skin_collections.union(all_case_names).union(all_graffiti_collections)
    
    # If --list-collections flag is present, show collections and exit
    if args.list_collections:
        print("Available collections:")
        for collection in sorted(all_collections):
            print(f"- {collection}")
        conn.close()
        return
    
    # Determine target collections
    target_collections = None
    if args.collections:
        target_collections = args.collections
        # Validate input collections
        invalid_collections = set(target_collections) - all_collections
        if invalid_collections:
            print(f"Warning: The following collections are not found in the data: {', '.join(invalid_collections)}")
        
        # Filter to only valid collections
        target_collections = list(set(target_collections) & all_collections)
        if not target_collections:
            print("No valid collections specified. No data will be added.")
            conn.close()
            return
            
        print(f"Importing items from collections: {', '.join(target_collections)}")
    else:
        print("No collections specified. Importing all items.")
    
    # Add collections to database
    collections_to_add = target_collections if target_collections else all_collections
    populate_collections(conn, collections_to_add)
    
    # Add items to database
    skins_added = 0
    cases_added = 0
    graffiti_added = 0
    
    if import_skins:
        print("Adding skins to database...")
        if args.no_quality_variants:
            # Use original function (not shown here - would need to be defined)
            # skins_added = original_populate_skins(conn, skins_data, target_collections)
            print("Note: --no-quality-variants flag is set, but the original function is not available.")
            print("Falling back to quality variant generation.")
            skins_added = populate_skins(conn, skins_data, target_collections)
        else:
            print("Creating multiple quality variants for each skin...")
            skins_added = populate_skins(conn, skins_data, target_collections)
    
    if import_cases:
        print("Adding cases to database...")
        cases_added = populate_cases(conn, cases_data, target_collections)
    
    if import_graffiti:
        print("Adding graffiti to database...")
        graffiti_added = populate_graffiti(conn, graffiti_data, target_collections)
    
    # Show a message about the multiplier effect and summary
    if skins_added > 0 and not args.no_quality_variants:
        print(f"Added {skins_added} skin variants (representing approximately {skins_added // 5} unique skins in 5 qualities each)")
    else:
        print(f"Added {skins_added} skins")
    
    print(f"Added {cases_added} cases")
    print(f"Added {graffiti_added} graffiti")
    print(f"Database populated: Added a total of {skins_added + cases_added + graffiti_added} items")
    
    # Close connection
    conn.close()

if __name__ == "__main__":
    main()
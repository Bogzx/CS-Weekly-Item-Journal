import sqlite3
import os

def create_csgo_database(db_path="csgo_items.db"):
    """
    Create a new SQLite database for CS:GO items if it doesn't exist.
    
    Parameters:
    - db_path (str): Path to the SQLite database file
    
    Returns:
    - bool: True if database was created, False if it already existed
    """
    # If the database file exists already, delete it to ensure a clean start
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
            print(f"Removed existing database: {db_path}")
        except Exception as e:
            print(f"Warning: Could not remove existing database: {e}")
    
    # Connect to database (creates it if it doesn't exist)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Set pragmas for better performance and compatibility
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA journal_mode = WAL")
    
    # Create items table
    cursor.execute('''
    CREATE TABLE items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        collection TEXT,
        market_api_url TEXT NOT NULL,
        price REAL,
        last_updated TIMESTAMP,
        item_type TEXT,
        UNIQUE(name, collection)
    )
    ''')
    
    # Create collections table for easier filtering
    cursor.execute('''
    CREATE TABLE collections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    ''')
    
    # Create a simple test table to verify it's working
    cursor.execute('''
    CREATE TABLE test_table (
        id INTEGER PRIMARY KEY,
        value TEXT
    )
    ''')
    
    # Add a test record
    cursor.execute("INSERT INTO test_table (value) VALUES ('test')")
    
    # Commit changes and close connection
    conn.commit()
    conn.close()
    
    print(f"Created new database at {db_path}")
    return True

if __name__ == "__main__":
    create_csgo_database()
    print("Database setup complete. Use populate_database.py to add items.")


'''
# Documentation for create_database.py

## Overview
This script creates a new SQLite database for storing CS:GO items including skins and cases. 
It sets up the necessary tables and initializes the database with appropriate settings for 
optimal performance.

## Tables Created
1. items - Stores information about CS:GO items (skins and cases)
   - id: Unique identifier
   - name: Item name
   - collection: Collection the item belongs to
   - market_api_url: Steam Market API URL for price information
   - price: Current price (may be NULL)
   - last_updated: Timestamp of last price update
   - item_type: Type of item ('skin' or 'case')

2. collections - Stores collection names for easier filtering
   - id: Unique identifier
   - name: Collection name

3. test_table - A simple test table to verify the database is working
   - id: Unique identifier
   - value: Test value

## Usage
Run this script without any arguments to create a new database:
```
python create_database.py
```

This will create a new database file named 'csgo_items.db' in the current directory.
If a database with this name already exists, it will be deleted and recreated.

## Functions
- create_csgo_database(db_path): Creates a new SQLite database at the specified path
  - Parameters:
    - db_path (str): Path to the SQLite database file (default: 'csgo_items.db')
  - Returns:
    - bool: True if database was created successfully

## Notes
- The script uses WAL (Write-Ahead Logging) mode for better performance
- Foreign key constraints are enabled
- The script deletes any existing database with the same name to ensure a clean start
- After creating the database, use populate_database.py to add items
'''
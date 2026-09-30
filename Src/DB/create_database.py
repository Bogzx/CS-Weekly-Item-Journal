import argparse
import os
import sqlite3
import sys

# Tables this script owns. app.py keeps `users` and `user_journals` in the same
# file, so a rebuild must only ever touch these.
ITEM_TABLES = ("items", "collections", "test_table")


def has_item_table(db_path):
    """True if the database at db_path already has an `items` table."""
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='items'"
        ).fetchone() is not None
    finally:
        conn.close()


def create_csgo_database(db_path="csgo_items.db", force=False):
    """
    Create the item tables in a SQLite database.
    
    Parameters:
    - db_path (str): Path to the SQLite database file
    - force (bool): Rebuild the item tables if the database already exists
    
    Returns:
    - bool: True if the tables were created, False if the database already
      had item tables and force was not given
    """
    # This used to os.remove() any existing file. app.py stores user accounts
    # and journals in the same database, so re-running the first setup step
    # silently deleted every user and their whole drop history.
    if os.path.exists(db_path) and not force and has_item_table(db_path):
        print(f"{db_path} already exists. Re-run with --force to rebuild the item "
              f"tables; user accounts and journals are kept.")
        return False
    # A database without an item table is one app.py created on its first
    # start (users and journals only). Adding the item tables to it loses
    # nothing, so that needs no --force.
    
    # Connect to database (creates it if it doesn't exist)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Set pragmas for better performance and compatibility
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA journal_mode = WAL")
    
    for table in ITEM_TABLES:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
    
    # Create items table
    cursor.execute('''
    CREATE TABLE items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        collection TEXT,
        market_api_url TEXT NOT NULL,
        price REAL,
        price_type TEXT,
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
    
    print(f"Created item tables in {db_path}")
    return True

def main(argv=None):
    parser = argparse.ArgumentParser(description='Create the CS2 item database schema')
    parser.add_argument('--db', type=str, default='csgo_items.db', help='Path to SQLite database')
    parser.add_argument('--force', action='store_true',
                        help='Rebuild the item tables of an existing database (keeps users and journals)')
    args = parser.parse_args(argv)
    
    if not create_csgo_database(args.db, force=args.force):
        return 1
    print("Database setup complete. Use populate_database.py to add items.")
    return 0

if __name__ == "__main__":
    sys.exit(main())


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
If a database with this name already exists the script refuses to touch it; pass
--force to drop and recreate the item tables (users and journals are kept).

## Functions
- create_csgo_database(db_path): Creates a new SQLite database at the specified path
  - Parameters:
    - db_path (str): Path to the SQLite database file (default: 'csgo_items.db')
  - Returns:
    - bool: True if database was created successfully

## Notes
- The script uses WAL (Write-Ahead Logging) mode for better performance
- Foreign key constraints are enabled
- An existing database is left alone unless --force is given, and even then only
  the item tables are rebuilt
- After creating the database, use populate_database.py to add items
'''
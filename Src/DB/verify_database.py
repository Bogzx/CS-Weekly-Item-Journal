import sqlite3
import os

def verify_database(db_path="csgo_items.db"):
    """
    Verify the database structure and report its contents.
    """
    if not os.path.exists(db_path):
        print(f"Error: Database file {db_path} does not exist")
        return False
    
    print(f"Database file found: {db_path}")
    print(f"File size: {os.path.getsize(db_path)} bytes")
    
    try:
        # Connect to the database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get list of tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        print("\nTables in database:")
        for table in tables:
            table_name = table[0]
            print(f"- {table_name}")
            
            # Get table schema
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            print(f"  Columns:")
            for column in columns:
                print(f"  - {column[1]} ({column[2]})")
            
            # Get row count
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            row_count = cursor.fetchone()[0]
            print(f"  Row count: {row_count}")
            
            # Show sample data (up to 5 rows)
            if row_count > 0:
                cursor.execute(f"SELECT * FROM {table_name} LIMIT 5")
                rows = cursor.fetchall()
                print(f"  Sample data:")
                for row in rows:
                    print(f"  - {row}")
            
            print()
        
        # Close connection
        conn.close()
        print("Database verification completed successfully!")
        return True
        
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        return False

if __name__ == "__main__":
    verify_database()



'''
# Documentation for verify_database.py

## Overview
This utility script verifies and examines the structure and contents of the CS:GO items database.
It provides a comprehensive report of all tables, their schemas, row counts, and sample data,
which is useful for debugging or validating the database.

## Usage
Run the script without any arguments to verify the default database:
```
python verify_database.py
```

To verify a different database file:
```
python verify_database.py --db path/to/database.db
```

## Output
The script outputs:
1. Database file information (path and size)
2. List of all tables in the database
3. For each table:
   - Column names and types
   - Row count
   - Sample data (up to 5 rows)
4. Success or error message

## Functions
- verify_database(db_path): Verifies and reports on database content
  - Parameters:
    - db_path (str): Path to the SQLite database file (default: 'csgo_items.db')
  - Returns:
    - bool: True if verification completed successfully, False otherwise

## Use Cases
- Verify that a database was created and populated correctly
- Debug issues with database structure or content
- Check the format of data in the database
- Confirm that prices have been updated
- Examine the database structure before making changes

## Notes
- This script is read-only and does not modify the database
- It's useful for troubleshooting issues with the other scripts
- The script will display detailed error messages if it encounters problems
- It provides a quick way to preview data without needing a SQLite browser
'''
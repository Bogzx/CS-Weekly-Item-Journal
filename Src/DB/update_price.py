import sqlite3
import requests
import json
import time
import argparse
import os
import random
from datetime import datetime

def fetch_price(market_url, max_retries=3):
    """
    Fetch the current price of an item from the Steam market API
    
    Parameters:
    - market_url (str): Steam market API URL for the item
    - max_retries (int): Maximum number of retry attempts on rate limit
    
    Returns:
    - tuple: (float, str) - Price of the item and price type ('lowest' or 'median'), or (None, None) if not available
    """
    retries = 0
    
    while retries <= max_retries:
        try:
            # Add a small delay to avoid rate limiting
            time.sleep(15)
            
            # Send request to Steam API
            response = requests.get(market_url)
            
            # Check if we're being rate limited (HTTP 429 or specific Steam error)
            if response.status_code == 429 or (response.status_code == 200 and "Retry Later" in response.text):
                retries += 1
                if retries <= max_retries:
                    wait_time = 30  # Wait 30 seconds on rate limit
                    print(f"Rate limited by Steam API. Waiting {wait_time} seconds before retry {retries}/{max_retries}...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"Maximum retries reached for {market_url}")
                    return None, None
            
            if response.status_code == 200:
                data = response.json()
                
                # Check if success
                if data.get('success'):
                    # Try to get lowest_price first
                    if 'lowest_price' in data:
                        price_str = data['lowest_price']
                        price = float(price_str.replace('$', '').replace(',', ''))
                        return price, 'lowest'
                    # If lowest_price is not available, try median_price
                    elif 'median_price' in data:
                        price_str = data['median_price']
                        price = float(price_str.replace('$', '').replace(',', ''))
                        return price, 'median'
            
            print(f"Failed to get price from {market_url}: {response.status_code} - {response.text}")
            return None, None
            
        except Exception as e:
            print(f"Error fetching price: {e}")
            retries += 1
            if retries <= max_retries and "Timeout" in str(e):
                wait_time = 30
                print(f"Request timed out. Waiting {wait_time} seconds before retry {retries}/{max_retries}...")
                time.sleep(wait_time)
                continue
            return None, None
    
    return None, None

# Function to retry database operations with exponential backoff
def execute_with_retry(conn, sql, params=(), max_retries=5, initial_delay=0.1):
    """Execute a SQL statement with retry logic for handling database locks."""
    cursor = conn.cursor()
    retries = 0
    delay = initial_delay
    
    while True:
        try:
            cursor.execute(sql, params)
            return cursor
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and retries < max_retries:
                retries += 1
                # Add some randomness to avoid thundering herd problem
                jitter = random.uniform(0.1, 0.3)
                wait_time = delay + jitter
                print(f"Database is locked. Retry {retries}/{max_retries} after {wait_time:.2f}s")
                time.sleep(wait_time)
                # Exponential backoff
                delay *= 2
            else:
                raise

def update_prices(db_path, collection_filter=None, max_items=None, retry_on_rate_limit=True, include_cases_graffiti=False):
    """
    Update prices for items in the database
    
    Parameters:
    - db_path (str): Path to SQLite database
    - collection_filter (list): Optional list of collections to filter by
    - max_items (int): Maximum number of items to update prices for
    - retry_on_rate_limit (bool): Whether to retry requests when rate limited
    - include_cases_graffiti (bool): If True, also update all cases and graffiti regardless of collection filter
    
    Returns:
    - int: Number of prices updated
    """
    # Set a longer timeout for the SQLite connection
    conn = sqlite3.connect(db_path, timeout=60.0)  # 60 second timeout
    
    # Enable immediate transactions to reduce lock time
    conn.isolation_level = 'IMMEDIATE'
    
    # Add price_type column if it doesn't exist
    try:
        execute_with_retry(conn, "ALTER TABLE items ADD COLUMN price_type TEXT")
        print("Added price_type column to items table")
    except sqlite3.OperationalError:
        # Column already exists
        pass
    
    cursor = conn.cursor()
    
    # Handle the case where we want to include all cases and graffiti
    if include_cases_graffiti:
        print("Special case: Including all cases and graffiti items regardless of collection filter")
        
        # First, build a query to get all items in specified collections (if any)
        collection_query = ""
        collection_params = []
        
        if collection_filter:
            placeholders = ','.join(['?'] * len(collection_filter))
            collection_query = f"collection IN ({placeholders})"
            collection_params.extend(collection_filter)
        
        # Now, build the query to get all items in collections OR cases/graffiti
        query = "SELECT id, name, market_api_url FROM items WHERE market_api_url IS NOT NULL AND ("
        params = []
        
        # Add collection filter if present
        if collection_query:
            query += collection_query
            params.extend(collection_params)
            query += " OR "
        
        # Add case and graffiti filter
        query += "item_type IN ('case', 'graffiti'))"
        
        # Add limit if specified
        if max_items:
            query += " LIMIT ?"
            params.append(max_items)
    else:
        # Regular case - only filter by collections
        query = "SELECT id, name, market_api_url FROM items WHERE market_api_url IS NOT NULL"
        params = []
        
        if collection_filter:
            placeholders = ','.join(['?'] * len(collection_filter))
            query += f" AND collection IN ({placeholders})"
            params.extend(collection_filter)
        
        if max_items:
            query += " LIMIT ?"
            params.append(max_items)
    
    # Fetch items to update using retry logic
    cursor = execute_with_retry(conn, query, params)
    items = cursor.fetchall()
    
    if not items:
        print("No items found to update.")
        conn.close()
        return 0
    
    print(f"Updating prices for {len(items)} items...")
    counter = 0
    lowest_count = 0
    median_count = 0
    failed_count = 0
    rate_limited_count = 0
    
    # Process items in smaller batches to reduce lock time
    batch_size = 10  # Update 10 items at a time
    for i in range(0, len(items), batch_size):
        batch_items = items[i:i+batch_size]
        
        for item_id, name, url in batch_items:
            max_retries = 3 if retry_on_rate_limit else 0
            price, price_type = fetch_price(url, max_retries)
            
            if price is not None:
                try:
                    # Use retry logic for database updates
                    execute_with_retry(
                        conn,
                        "UPDATE items SET price = ?, price_type = ?, last_updated = ? WHERE id = ?",
                        (price, price_type, datetime.now(), item_id)
                    )
                    # Commit after each update to release locks faster
                    conn.commit()
                    
                    print(f"Updated {name}: ${price:.2f} ({price_type} price)")
                    counter += 1
                    
                    if price_type == 'lowest':
                        lowest_count += 1
                    elif price_type == 'median':
                        median_count += 1
                except Exception as e:
                    print(f"Error updating {name}: {e}")
                    failed_count += 1
            else:
                failed_count += 1
                # Check if this was a rate limit issue
                if retry_on_rate_limit and max_retries > 0:
                    rate_limited_count += 1
    
    # Close connection
    conn.close()
    
    print(f"\nSummary:")
    print(f"- Total items updated: {counter}")
    print(f"- Items with lowest price: {lowest_count}")
    print(f"- Items with median price: {median_count}")
    print(f"- Failed updates: {failed_count}")
    if retry_on_rate_limit and rate_limited_count > 0:
        print(f"- Items that experienced rate limiting: {rate_limited_count}")
    
    return counter

def main():
    parser = argparse.ArgumentParser(description='Update CS:GO item prices in the database')
    parser.add_argument('--db', type=str, default='csgo_items.db', help='Path to SQLite database')
    parser.add_argument('--collections', type=str, nargs='+', help='List of collections to update')
    parser.add_argument('--max', type=int, help='Maximum number of items to update')
    parser.add_argument('--no-retry', action='store_true', help='Disable retry on rate limiting')
    parser.add_argument('--all-cases-graffiti', action='store_true', 
                       help='Update all cases and graffiti regardless of collection filter')
    
    args = parser.parse_args()
    
    # Check if database exists
    if not os.path.exists(args.db):
        print(f"Database {args.db} not found. Please run create_database.py first.")
        return
    
    # Update prices
    updated = update_prices(
        args.db, 
        args.collections, 
        args.max, 
        not args.no_retry,
        args.all_cases_graffiti
    )
    
    print(f"Price update complete. Updated {updated} items.")

if __name__ == "__main__":
    main()
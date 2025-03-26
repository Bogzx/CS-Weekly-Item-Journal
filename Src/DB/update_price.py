import sqlite3
import requests
import json
import time
import argparse
import os
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
            time.sleep(5)
            
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

def update_prices(db_path, collection_filter=None, max_items=None, retry_on_rate_limit=True):
    """
    Update prices for items in the database
    
    Parameters:
    - db_path (str): Path to SQLite database
    - collection_filter (list): Optional list of collections to filter by
    - max_items (int): Maximum number of items to update prices for
    - retry_on_rate_limit (bool): Whether to retry requests when rate limited
    
    Returns:
    - int: Number of prices updated
    """
    # Connect to database
    conn = sqlite3.connect(db_path)
    
    # Add price_type column if it doesn't exist
    try:
        conn.execute("ALTER TABLE items ADD COLUMN price_type TEXT")
        print("Added price_type column to items table")
    except sqlite3.OperationalError:
        # Column already exists
        pass
    
    cursor = conn.cursor()
    
    # Build the query
    query = "SELECT id, name, market_api_url FROM items WHERE market_api_url IS NOT NULL"
    params = []
    
    if collection_filter:
        placeholders = ','.join(['?'] * len(collection_filter))
        query += f" AND collection IN ({placeholders})"
        params.extend(collection_filter)
    
    if max_items:
        query += " LIMIT ?"
        params.append(max_items)
    
    # Fetch items to update
    cursor.execute(query, params)
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
    
    for item_id, name, url in items:
        max_retries = 3 if retry_on_rate_limit else 0
        price, price_type = fetch_price(url, max_retries)
        
        if price is not None:
            cursor.execute(
                "UPDATE items SET price = ?, price_type = ?, last_updated = ? WHERE id = ?",
                (price, price_type, datetime.now(), item_id)
            )
            print(f"Updated {name}: ${price:.2f} ({price_type} price)")
            counter += 1
            
            if price_type == 'lowest':
                lowest_count += 1
            elif price_type == 'median':
                median_count += 1
        else:
            failed_count += 1
            # Check if this was a rate limit issue
            if retry_on_rate_limit and max_retries > 0:
                rate_limited_count += 1
    
    # Commit changes and close connection
    conn.commit()
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
    
    args = parser.parse_args()
    
    # Check if database exists
    if not os.path.exists(args.db):
        print(f"Database {args.db} not found. Please run create_database.py first.")
        return
    
    # Update prices
    updated = update_prices(args.db, args.collections, args.max, not args.no_retry)
    
    print(f"Price update complete. Updated {updated} items.")

if __name__ == "__main__":
    main()

'''
# Documentation for update_price.py

## Overview
This script updates the prices of CS:GO items in the database by fetching current
price information from the Steam Market API. It handles rate limiting and can 
work with different price types (lowest and median).

## Usage Examples
1. Update prices for all items with automatic retries:
   ```
   python update_price.py
   ```

2. Update prices without retry on rate limiting:
   ```
   python update_price.py --no-retry
   ```

3. Update prices for specific collections:
   ```
   python update_price.py --collections "Clutch Case" "Chroma Case"
   ```

4. Limit the number of items to update (useful for testing):
   ```
   python update_price.py --max 10
   ```

5. Combine options:
   ```
   python update_price.py --collections "Clutch Case" --max 5 --no-retry
   ```

## Command-line Arguments
- --db: Path to SQLite database (default: csgo_items.db)
- --collections: List of collections to update (space-separated)
- --max: Maximum number of items to update
- --no-retry: Disable retry on rate limiting

## Functions
- fetch_price(market_url, max_retries): Fetches current price from Steam Market API
  - Returns a tuple with price and price type ('lowest' or 'median')
  - Handles rate limiting with automatic retries
  - Waits 30 seconds between retries

- update_prices(db_path, collection_filter, max_items, retry_on_rate_limit): 
  Updates prices in the database
  - Adds price_type column if needed
  - Provides detailed summary of updates

## Notes
- The script adds a 5-second delay between API requests to avoid rate limiting
- If rate limited, it waits 30 seconds before retrying (up to 3 retries)
- It tries to get the 'lowest_price' first, then falls back to 'median_price'
- The price_type column tracks which type of price was stored
- Prices are stored in USD without the '$' symbol
- The script stores the timestamp of each price update
- Steam API has rate limits, so updating many items may take time
'''
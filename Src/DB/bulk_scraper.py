import sqlite3
import requests
import json
import time
import argparse
import os
import urllib.parse
from datetime import datetime

def build_steam_market_url(start=0, count=100, filters=None, query=None, sort_column='price', sort_dir='asc'):
    """
    Build a Steam Market URL with specified filters for CS2 items
    
    Parameters:
    - start (int): Starting index for pagination
    - count (int): Number of items to retrieve
    - filters (dict): Dictionary of category filters
    - query (str): Search query term
    - sort_column (str): Column to sort by (price, name, quantity)
    - sort_dir (str): Sort direction (asc, desc)
    
    Returns:
    - str: Formatted URL
    """
    # Base URL parameters
    params = {
        'appid': 730,  # CS2/CS:GO app ID
        'norender': 1,
        'start': start,
        'count': count,
        'sort_column': sort_column,
        'sort_dir': sort_dir
    }
    
    # Add search query if provided
    if query:
        params['q'] = query
    
    # Add category filters if provided
    if filters and isinstance(filters, dict):
        for category, values in filters.items():
            if isinstance(values, list):
                for value in values:
                    # Each filter is added as a separate parameter with empty value
                    params[f'{category}[]'] = value
            else:
                params[f'{category}[]'] = values
    
    # Build URL with parameters
    base_url = "https://steamcommunity.com/market/search/render/"
    query_string = urllib.parse.urlencode(params, doseq=True)
    
    return f"{base_url}?{query_string}"

def fetch_prices_in_bulk(start=0, count=100, filters=None, query=None, retries=3):
    """
    Fetch multiple item prices at once from Steam Market
    
    Parameters:
    - start (int): Starting index for pagination
    - count (int): Number of items to retrieve
    - filters (dict): Dictionary of category filters
    - query (str): Search query term
    - retries (int): Number of retry attempts
    
    Returns:
    - dict: Dictionary of item market_hash_name to price data
    """
    url = build_steam_market_url(start, count, filters, query)
    
    for attempt in range(retries):
        try:
            print(f"Fetching items {start} to {start+count-1}...")
            response = requests.get(url)
            
            if response.status_code == 429:
                wait_time = 60  # Wait longer for bulk requests
                print(f"Rate limited by Steam API. Waiting {wait_time} seconds before retry {attempt+1}/{retries}...")
                time.sleep(wait_time)
                continue
                
            if response.status_code == 200:
                data = response.json()
                
                if not data.get('success'):
                    print(f"Steam API returned unsuccessful response: {data}")
                    return {}
                
                # Create a dictionary mapping market_hash_name to price data
                price_data = {}
                for item in data.get('results', []):
                    hash_name = item.get('hash_name')
                    sell_price = item.get('sell_price')
                    
                    if hash_name and sell_price:
                        # Convert price from cents to dollars/euros
                        actual_price = sell_price / 100.0
                        price_data[hash_name] = {
                            'price': actual_price,
                            'price_type': 'lowest',  # This is the lowest listing price
                            'listings': item.get('sell_listings', 0)
                        }
                
                return price_data
            
            print(f"Failed to get prices: {response.status_code} - {response.text}")
            return {}
            
        except Exception as e:
            print(f"Error fetching prices: {e}")
            if attempt < retries - 1:
                time.sleep(30)  # Wait before retry
    
    return {}

def get_total_item_count(filters=None, query=None):
    """
    Get the total number of CS2 items on the market matching the filters
    
    Parameters:
    - filters (dict): Dictionary of category filters
    - query (str): Search query term
    
    Returns:
    - int: Total number of items, or a default value if request fails
    """
    url = build_steam_market_url(0, 1, filters, query)
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            return data.get('total_count', 10000)
    except Exception as e:
        print(f"Error getting total item count: {e}")
    
    return 10000  # Default fallback value

def fetch_all_prices(max_items=None, batch_size=100, filters=None, query=None):
    """
    Fetch prices for all available CS2 items in batches
    
    Parameters:
    - max_items (int): Maximum number of items to fetch (None for all)
    - batch_size (int): Number of items to fetch per request
    - filters (dict): Dictionary of category filters
    - query (str): Search query term
    
    Returns:
    - dict: Dictionary of market_hash_name to price data
    """
    total_items = get_total_item_count(filters, query)
    print(f"Total market items found: {total_items}")
    
    if max_items is not None:
        total_items = min(total_items, max_items)
        print(f"Limited to {total_items} items")
    
    all_price_data = {}
    
    for start in range(0, total_items, batch_size):
        # Adjust the final batch size if needed
        current_batch_size = min(batch_size, total_items - start)
        
        batch_data = fetch_prices_in_bulk(start, current_batch_size, filters, query)
        all_price_data.update(batch_data)
        
        print(f"Fetched {len(batch_data)} items. Total collected: {len(all_price_data)}")
        
        # Sleep between batches to avoid rate limiting
        if start + batch_size < total_items:
            time.sleep(10)  # 10 second delay between batches
    
    return all_price_data

def update_database_prices(db_path, price_data, collection_filter=None):
    """
    Update prices in the database from the fetched price data
    
    Parameters:
    - db_path (str): Path to SQLite database
    - price_data (dict): Dictionary of market_hash_name to price data
    - collection_filter (list): Optional list of collections to filter by
    
    Returns:
    - int: Number of items updated
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
    
    # Get all items from database
    query = "SELECT id, name, collection FROM items"
    params = []
    
    if collection_filter:
        placeholders = ','.join(['?'] * len(collection_filter))
        query += f" WHERE collection IN ({placeholders})"
        params.extend(collection_filter)
    
    cursor.execute(query, params)
    db_items = cursor.fetchall()
    
    counter = 0
    for item_id, item_name, collection in db_items:
        # If the item name is in our price data
        if item_name in price_data:
            data = price_data[item_name]
            price = data['price']
            price_type = data['price_type']
            
            try:
                cursor.execute(
                    "UPDATE items SET price = ?, price_type = ?, last_updated = ? WHERE id = ?",
                    (price, price_type, datetime.now(), item_id)
                )
                counter += 1
                if counter % 100 == 0:
                    print(f"Updated {counter} items...")
            except sqlite3.Error as e:
                print(f"Error updating {item_name}: {e}")
    
    # Commit changes and close connection
    conn.commit()
    conn.close()
    
    return counter

def get_available_categories():
    """
    Return a dictionary of available CS2 category filters
    """
    categories = {
        # Item type categories
        "category_730_Type": [
            "tag_CSGO_Type_Pistol",
            "tag_CSGO_Type_SMG",
            "tag_CSGO_Type_Rifle",
            "tag_CSGO_Type_SniperRifle",
            "tag_CSGO_Type_Shotgun",
            "tag_CSGO_Type_Machinegun",
            "tag_CSGO_Type_Knife",
            "tag_Type_Hands",
            "tag_CSGO_Type_Container",
            "tag_CSGO_Tool_Sticker",
            "tag_CSGO_Tool_Patch",
            "tag_CSGO_Tool_Name_Tag",
            "tag_CSGO_Tool_Key"
        ],
        
        # Quality categories
        "category_730_Quality": [
            "tag_normal",
            "tag_strange",  # StatTrak™
            "tag_tournament",  # Souvenir
            "tag_unusual",  # ★ (Knife/Glove)
            "tag_unusual_strange"  # ★ StatTrak™
        ],
        
        # Popular weapon categories
        "category_730_Weapon": [
            "tag_weapon_ak47",
            "tag_weapon_awp",
            "tag_weapon_m4a1",
            "tag_weapon_m4a1_silencer",
            "tag_weapon_knife",
            "tag_weapon_glock",
            "tag_weapon_usp_silencer",
            "tag_weapon_deagle"
        ],
        
        # Exterior categories
        "category_730_Exterior": [
            "tag_WearCategory0",  # Factory New
            "tag_WearCategory1",  # Minimal Wear
            "tag_WearCategory2",  # Field-Tested
            "tag_WearCategory3",  # Well-Worn
            "tag_WearCategory4"   # Battle-Scarred
        ]
    }
    
    return categories

def main():
    parser = argparse.ArgumentParser(description='Bulk update CS2 item prices in the database')
    parser.add_argument('--db', type=str, default='csgo_items.db', help='Path to SQLite database')
    parser.add_argument('--collections', type=str, nargs='+', help='List of collections to update in database')
    parser.add_argument('--max', type=int, help='Maximum number of items to fetch from Steam')
    parser.add_argument('--batch-size', type=int, default=100, help='Number of items to fetch per API call')
    parser.add_argument('--type', type=str, help='Filter by item type (weapon, container, sticker, etc.)')
    parser.add_argument('--quality', type=str, help='Filter by quality (normal, stattrak, souvenir, etc.)')
    parser.add_argument('--weapon', type=str, help='Filter by specific weapon (ak47, awp, etc.)')
    parser.add_argument('--exterior', type=str, help='Filter by exterior (factory-new, minimal-wear, etc.)')
    parser.add_argument('--query', type=str, help='Search query to filter items')
    parser.add_argument('--list-filters', action='store_true', help='List available filter options')
    
    args = parser.parse_args()
    
    # If list-filters flag is set, show available filters and exit
    if args.list_filters:
        categories = get_available_categories()
        print("Available CS2 Item Filters:")
        for category, values in categories.items():
            category_name = category.replace("category_730_", "")
            print(f"\n{category_name} filters:")
            for value in values:
                print(f"  - {value.replace('tag_', '').replace('CSGO_', '')}")
        return
    
    # Check if database exists
    if not os.path.exists(args.db):
        print(f"Database {args.db} not found. Please run create_database.py first.")
        return
    
    # Build filters from command line arguments
    filters = {}
    
    if args.type:
        if args.type.lower() == "knife":
            filters["category_730_Type"] = "tag_CSGO_Type_Knife"
        elif args.type.lower() == "pistol":
            filters["category_730_Type"] = "tag_CSGO_Type_Pistol"
        elif args.type.lower() == "rifle":
            filters["category_730_Type"] = "tag_CSGO_Type_Rifle"
        elif args.type.lower() == "sniper":
            filters["category_730_Type"] = "tag_CSGO_Type_SniperRifle"
        elif args.type.lower() == "smg":
            filters["category_730_Type"] = "tag_CSGO_Type_SMG"
        elif args.type.lower() == "container" or args.type.lower() == "case":
            filters["category_730_Type"] = "tag_CSGO_Type_Container"
        elif args.type.lower() == "sticker":
            filters["category_730_Type"] = "tag_CSGO_Tool_Sticker"
        
    if args.quality:
        if args.quality.lower() == "stattrak":
            filters["category_730_Quality"] = "tag_strange"
        elif args.quality.lower() == "souvenir":
            filters["category_730_Quality"] = "tag_tournament"
        elif args.quality.lower() == "normal":
            filters["category_730_Quality"] = "tag_normal"
        elif args.quality.lower() == "knife" or args.quality.lower() == "star":
            filters["category_730_Quality"] = "tag_unusual"
        
    if args.weapon:
        if args.weapon.lower() == "ak47" or args.weapon.lower() == "ak-47":
            filters["category_730_Weapon"] = "tag_weapon_ak47"
        elif args.weapon.lower() == "awp":
            filters["category_730_Weapon"] = "tag_weapon_awp"
        elif args.weapon.lower() == "m4a4":
            filters["category_730_Weapon"] = "tag_weapon_m4a1"
        elif args.weapon.lower() == "m4a1s" or args.weapon.lower() == "m4a1-s":
            filters["category_730_Weapon"] = "tag_weapon_m4a1_silencer"
        elif args.weapon.lower() == "knife":
            filters["category_730_Weapon"] = "tag_weapon_knife"
    
    if args.exterior:
        if args.exterior.lower() == "fn" or args.exterior.lower() == "factory-new":
            filters["category_730_Exterior"] = "tag_WearCategory0"
        elif args.exterior.lower() == "mw" or args.exterior.lower() == "minimal-wear":
            filters["category_730_Exterior"] = "tag_WearCategory1"
        elif args.exterior.lower() == "ft" or args.exterior.lower() == "field-tested":
            filters["category_730_Exterior"] = "tag_WearCategory2"
        elif args.exterior.lower() == "ww" or args.exterior.lower() == "well-worn":
            filters["category_730_Exterior"] = "tag_WearCategory3"
        elif args.exterior.lower() == "bs" or args.exterior.lower() == "battle-scarred":
            filters["category_730_Exterior"] = "tag_WearCategory4"
    
    # Fetch all prices in bulk with filters
    start_time = time.time()
    price_data = fetch_all_prices(args.max, args.batch_size, filters, args.query)
    fetch_time = time.time() - start_time
    
    print(f"Fetched prices for {len(price_data)} items in {fetch_time:.2f} seconds")
    
    # Update database with fetched prices
    update_start = time.time()
    updated = update_database_prices(args.db, price_data, args.collections)
    update_time = time.time() - update_start
    
    print(f"Database updated: {updated} items in {update_time:.2f} seconds")
    print(f"Total operation time: {time.time() - start_time:.2f} seconds")

if __name__ == "__main__":
    main()

'''
# Documentation for cs2_bulk_update_prices.py

## Overview
This script provides a highly efficient way to update CS2 item prices in bulk by using
the Steam Market search API with specific filters. It allows you to narrow down the 
items you fetch based on type, quality, weapon, exterior, and search terms.

## Key Benefits
- Much faster than updating items one by one
- Filter specifically for CS2 items by type, quality, and more
- Control exactly what kinds of items to update
- Can update thousands of items in minutes rather than hours

## Usage Examples
1. Update all CS2 items:
   ```
   python cs2_bulk_update_prices.py
   ```

2. List all available filter options:
   ```
   python cs2_bulk_update_prices.py --list-filters
   ```

3. Update only AK-47 skins:
   ```
   python cs2_bulk_update_prices.py --weapon ak47
   ```

4. Update only StatTrak™ items:
   ```
   python cs2_bulk_update_prices.py --quality stattrak
   ```

5. Update only knife skins:
   ```
   python cs2_bulk_update_prices.py --type knife
   ```

6. Update only Factory New items:
   ```
   python cs2_bulk_update_prices.py --exterior fn
   ```

7. Search for specific items:
   ```
   python cs2_bulk_update_prices.py --query "Asiimov"
   ```

8. Combine multiple filters:
   ```
   python cs2_bulk_update_prices.py --type rifle --quality stattrak --exterior fn
   ```

## Command-line Arguments
- --db: Path to SQLite database (default: csgo_items.db)
- --collections: List of collections to update in database (space-separated)
- --max: Maximum number of items to fetch from Steam
- --batch-size: Number of items to fetch per API call (default: 100)
- --type: Filter by item type (weapon, container, sticker, etc.)
- --quality: Filter by quality (normal, stattrak, souvenir, etc.)
- --weapon: Filter by specific weapon (ak47, awp, etc.)
- --exterior: Filter by exterior (factory-new, minimal-wear, etc.)
- --query: Search query to filter items
- --list-filters: List available filter options

## Available Filters
- Types: pistol, rifle, sniper, smg, knife, container, sticker, etc.
- Qualities: normal, stattrak, souvenir, knife/star
- Weapons: ak47, awp, m4a4, m4a1s, knife, etc.
- Exteriors: fn (Factory New), mw (Minimal Wear), ft (Field-Tested), etc.

## Notes
- The Steam Market API has a limit on how many items you can request at once
- A batch size of 100 is generally reliable without hitting rate limits
- The script automatically waits between batches to avoid rate limiting
- If rate limited, the script will wait and retry
- Unlike the single-item API, this endpoint uses the lowest listing price only
'''
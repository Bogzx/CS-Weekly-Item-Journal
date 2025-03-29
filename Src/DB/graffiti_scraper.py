import requests
import json
import csv
import time
import urllib.parse
import argparse
import os
from datetime import datetime

def build_graffiti_search_url(start=0, count=100, sort_column='price', sort_dir='asc'):
    """
    Build a Steam Market URL for CS:GO/CS2 graffiti
    
    Parameters:
    - start (int): Starting index for pagination
    - count (int): Number of items to retrieve
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
        'sort_dir': sort_dir,
        'category_730_Type[]': 'tag_CSGO_Type_Spray'  # Filter for graffiti/sprays only
    }
    
    # Build URL with parameters
    base_url = "https://steamcommunity.com/market/search/render/"
    query_string = urllib.parse.urlencode(params, doseq=True)
    
    return f"{base_url}?{query_string}"

def fetch_graffiti_items(start=0, count=100, retries=3):
    """
    Fetch graffiti items from Steam Market
    
    Parameters:
    - start (int): Starting index for pagination
    - count (int): Number of items to retrieve
    - retries (int): Number of retry attempts
    
    Returns:
    - list: List of graffiti items
    """
    url = build_graffiti_search_url(start, count)
    
    for attempt in range(retries):
        try:
            print(f"Fetching graffiti items {start} to {start+count-1}...")
            response = requests.get(url)
            
            if response.status_code == 429:
                wait_time = 60  # Wait longer on rate limit
                print(f"Rate limited by Steam API. Waiting {wait_time} seconds before retry {attempt+1}/{retries}...")
                time.sleep(wait_time)
                continue
                
            if response.status_code == 200:
                data = response.json()
                
                if not data.get('success'):
                    print(f"Steam API returned unsuccessful response: {data}")
                    return []
                
                return data.get('results', [])
            
            print(f"Failed to get items: {response.status_code} - {response.text}")
            return []
            
        except Exception as e:
            print(f"Error fetching items: {e}")
            if attempt < retries - 1:
                time.sleep(30)  # Wait before retry
    
    return []

def get_total_graffiti_count():
    """
    Get the total number of CS2 graffiti items on the market
    
    Returns:
    - int: Total number of items, or a default value if request fails
    """
    url = build_graffiti_search_url(0, 1)
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            return data.get('total_count', 1000)
    except Exception as e:
        print(f"Error getting total item count: {e}")
    
    return 1000  # Default fallback value

def extract_graffiti_name_parts(full_name):
    """
    Extract collection and name parts from a graffiti full name
    
    Parameters:
    - full_name (str): Full graffiti name
    
    Returns:
    - tuple: (collection, name)
    """
    # Common graffiti collection identifiers
    collections = [
        "Graffiti Box", 
        "Graffiti Collection",
        "CS:GO Graffiti",
        "CS20 Collection",
        "Community Graffiti",
        "Tournament Collection"
    ]
    
    # Check if name contains a collection identifier
    collection = "Default Graffiti Collection"
    clean_name = full_name
    
    # Try to extract collection
    for coll in collections:
        if coll in full_name:
            collection = coll
            clean_name = full_name.replace(f"| {coll}", "").strip()
            break
    
    # Remove the "Sealed Graffiti" prefix if present
    if "Sealed Graffiti" in clean_name:
        clean_name = clean_name.replace("Sealed Graffiti", "").strip()
        if clean_name.startswith("|"):
            clean_name = clean_name[1:].strip()
    
    return collection, clean_name

def create_price_api_url(name):
    """
    Create a Steam Market API URL for price information
    
    Parameters:
    - name (str): Item name
    
    Returns:
    - str: API URL
    """
    encoded_name = urllib.parse.quote(name)
    return f"https://steamcommunity.com/market/priceoverview/?appid=730&market_hash_name={encoded_name}"

def fetch_all_graffiti(max_items=None, batch_size=100):
    """
    Fetch all available CS2 graffiti items in batches
    
    Parameters:
    - max_items (int): Maximum number of items to fetch (None for all)
    - batch_size (int): Number of items to fetch per request
    
    Returns:
    - list: List of processed graffiti items with extracted data
    """
    total_items = get_total_graffiti_count()
    print(f"Total graffiti items found on Steam Market: {total_items}")
    
    if max_items is not None:
        total_items = min(total_items, max_items)
        print(f"Limited to {total_items} items")
    
    all_graffiti = []
    
    for start in range(0, total_items, batch_size):
        # Adjust the final batch size if needed
        current_batch_size = min(batch_size, total_items - start)
        
        batch_items = fetch_graffiti_items(start, current_batch_size)
        
        for item in batch_items:
            try:
                name = item.get('hash_name', '')
                collection, clean_name = extract_graffiti_name_parts(name)
                
                graffiti_item = {
                    'Collection': collection,
                    'Name': clean_name,
                    'FullName': name,
                    'SteamMarketURL': create_price_api_url(name)
                }
                
                all_graffiti.append(graffiti_item)
            except Exception as e:
                print(f"Error processing item {item.get('hash_name', 'unknown')}: {e}")
        
        print(f"Fetched {len(batch_items)} items. Total collected: {len(all_graffiti)}")
        
        # Sleep between batches to avoid rate limiting
        if start + batch_size < total_items:
            time.sleep(5)  # 5 second delay between batches
    
    return all_graffiti

def save_to_csv(graffiti_items, output_file='cs_graffiti.csv'):
    """
    Save graffiti items to a CSV file
    
    Parameters:
    - graffiti_items (list): List of graffiti items
    - output_file (str): Path to save CSV file
    """
    if not graffiti_items:
        print("No items to save.")
        return
    
    # Define CSV headers to match the expected format for populate_database.py
    fieldnames = ['Collection', 'Name', 'FullName', 'SteamMarketURL']
    
    try:
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(graffiti_items)
        
        print(f"Successfully saved {len(graffiti_items)} graffiti items to {output_file}")
    except Exception as e:
        print(f"Error saving to CSV: {e}")

def main():
    parser = argparse.ArgumentParser(description='Extract CS2 graffiti items from Steam Market')
    parser.add_argument('--output', type=str, default='cs_graffiti.csv', help='Output CSV file path')
    parser.add_argument('--max', type=int, help='Maximum number of items to fetch')
    parser.add_argument('--batch-size', type=int, default=100, help='Number of items per API request')
    
    args = parser.parse_args()
    
    print(f"Extracting CS2 graffiti to {args.output}")
    start_time = time.time()
    
    # Fetch all graffiti items
    graffiti_items = fetch_all_graffiti(args.max, args.batch_size)
    
    # Save to CSV
    save_to_csv(graffiti_items, args.output)
    
    print(f"Completed in {time.time() - start_time:.2f} seconds")

if __name__ == "__main__":
    main()
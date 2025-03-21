import requests
import json
import time
import urllib.parse
import os
from datetime import datetime


def read_items_from_file(filename):
    """Read item names from a text file, one item per line."""
    with open(filename, 'r', encoding='utf-8') as file:
        return [line.strip() for line in file if line.strip()]


def get_steam_price(item_name):
    """
    Get the lowest price for an item from Steam Market API.

    Args:
        item_name: The name of the item to check

    Returns:
        tuple: (success, price or error message)
    """
    # Encode the item name for URL
    encoded_name = urllib.parse.quote(item_name)

    # Construct the URL (currency=3 for Euro)
    url = f"https://steamcommunity.com/market/priceoverview/?currency=3&appid=730&market_hash_name={encoded_name}"

    try:
        # Add a user agent to avoid blocking
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        # Make the request
        response = requests.get(url, headers=headers)

        # Check if request was successful
        if response.status_code == 200:
            data = response.json()

            if data.get('success'):
                return True, data.get('lowest_price', 'N/A')
            else:
                return False, "Item not found or no price data available"
        else:
            return False, f"HTTP Error: {response.status_code}"

    except requests.exceptions.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, "Invalid JSON response"
    except Exception as e:
        return False, f"Error: {str(e)}"


def write_results_to_file(results, filename):
    """Write price results to a text file."""
    with open(filename, 'w', encoding='utf-8') as file:
        # Write timestamp
        file.write(f"Price check completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        # Write header
        file.write("Item Name | Lowest Price | Status\n")
        file.write("-" * 60 + "\n")

        # Write data
        for item_name, (success, price_or_error) in results.items():
            status = "Success" if success else "Failed"
            file.write(f"{item_name} | {price_or_error} | {status}\n")


def main():
    # Configuration
    input_file = "steam_items.txt"
    output_file = "steam_prices.txt"
    check_interval = 24 * 60 * 60  # 24 hours in seconds

    print(f"Steam Price Scraper started. Checking prices every 24 hours.")
    print(f"Reading items from: {input_file}")
    print(f"Writing results to: {output_file}")

    while True:
        try:
            # Read items from file
            items = read_items_from_file(input_file)
            print(f"Found {len(items)} items to check.")

            # Check prices for each item
            results = {}
            for item in items:
                print(f"Checking price for: {item}")
                success, price_or_error = get_steam_price(item)
                results[item] = (success, price_or_error)

                # Add a small delay between requests to avoid rate limiting
                time.sleep(1)

            # Write results to file
            write_results_to_file(results, output_file)
            print(f"Price check completed. Results written to {output_file}")

            # Wait for next check
            print(f"Next check scheduled in 24 hours.")
            time.sleep(check_interval)

        except Exception as e:
            print(f"Error in main loop: {str(e)}")
            print("Retrying in 1 hour...")
            time.sleep(3600)  # Wait an hour and try again


if __name__ == "__main__":
    main()
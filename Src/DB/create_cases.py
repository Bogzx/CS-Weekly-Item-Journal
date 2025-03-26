import csv
import urllib.parse

def generate_cs_cases_csv(input_file='cs_skins.csv', output_file='cs_cases.csv'):
    """
    Generate a CSV file of CS:GO cases with their Steam Market API URLs
    
    Parameters:
    - input_file (str): Path to input CSV file with CS:GO skins data
    - output_file (str): Path to output CSV file for cases
    """
    # Set to store unique case collections
    case_collections = set()
    
    # Read the input CSV file
    print(f"Reading data from {input_file}...")
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            # Extract collections with "Case" in their name
            for row in reader:
                if 'Collection' in row and row['Collection'] and 'Case' in row['Collection']:
                    case_collections.add(row['Collection'])
    except FileNotFoundError:
        print(f"Error: File {input_file} not found.")
        return
    except Exception as e:
        print(f"Error reading input file: {e}")
        return
    
    # Create list of cases with their API URLs
    cases_data = []
    for case_name in sorted(case_collections):
        # Create Steam Market API URL
        url = f"https://steamcommunity.com/market/priceoverview/?appid=730&market_hash_name={urllib.parse.quote(case_name)}"
        cases_data.append({'Case': case_name, 'Steam Market API URL': url})
    
    # Write to output CSV
    print(f"Writing {len(cases_data)} cases to {output_file}...")
    try:
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['Case', 'Steam Market API URL'])
            writer.writeheader()
            writer.writerows(cases_data)
        print(f"Successfully created {output_file} with {len(cases_data)} cases.")
    except Exception as e:
        print(f"Error writing output file: {e}")
        return

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate a CSV file of CS:GO cases with their Steam Market API URLs')
    parser.add_argument('--input', type=str, default='cs_skins.csv', help='Path to input CSV file with CS:GO skins data')
    parser.add_argument('--output', type=str, default='cs_cases.csv', help='Path to output CSV file for cases')
    
    args = parser.parse_args()
    generate_cs_cases_csv(args.input, args.output)

"""
create_cases.py

Description:
This script generates a CSV file of CS:GO/CS2 cases with their Steam Market API URLs.
It extracts case names from the skins CSV data and creates price API URLs for each case.

Requirements:
- Python 3.6 or higher
- Input CSV file with CS:GO skin data (e.g., cs_skins.csv)

Usage:
python create_cases.py [options]

Options:
--input PATH    Path to input CSV file with CS:GO skins data (default: cs_skins.csv)
--output PATH   Path to output CSV file for cases (default: cs_cases.csv)

Examples:
python create_cases.py
python create_cases.py --input my_skins.csv --output my_cases.csv

Notes:
- The script identifies cases by looking for "Case" in the Collection field
- The output CSV will have columns: Case, Steam Market API URL
- The URLs use the format: https://steamcommunity.com/market/priceoverview/?appid=730&market_hash_name=CASE_NAME
- These URLs return JSON data with price information when accessed
"""
# CS:GO/CS2 Items Database - How to Use

This document explains how to use the provided scripts to create and maintain a database of CS:GO/CS2 items with their current market prices.

## System Requirements

* Python 3.6 or higher
* Node.js 12.0 or higher (for creating CS skins data)
* Required Python packages: `sqlite3`, `requests`
* Required Node.js packages: `node-html-parser` (for `create_cs_skins.js`)

## Quick Start

Here's the typical workflow to set up and use the database:

```bash
# 1. Create the database structure
python create_database.py

# 2. Generate CS:GO skins data
node create_cs_skins.js

# 3. Generate CS:GO cases data
python create_cases.py

# 4. Populate the database with items
python populate_database.py

# 5. Update item prices
python update_price.py  # For individual updates
# OR
python bulk_scraper.py  # For bulk updates (faster)

# 6. Verify database contents
python verify_database.py
```

## Detailed Instructions

### 1. Creating the Database

The first step is to create the SQLite database that will store all the CS:GO items and their prices.

```bash
python create_database.py
```

This will:

* Create a new file named `csgo_items.db` in the current directory
* Set up all required tables (items, collections, etc.)
* If a database already exists with this name, it will be deleted and recreated

### 2. Generating CS:GO Skins Data

Next, you need to generate a CSV file with CS:GO skins data.

```bash
node create_cs_skins.js
```

This will:

* Scrape CS:GO skins data from online sources
* Generate a `cs_skins.csv` file with columns for Collection, Weapon, Skin, Quality, and Steam Market API URL

### 3. Generating CS:GO Cases Data

You also need to generate a CSV file with CS:GO cases data.

```bash
python create_cases.py
```

This will:

* Extract case names from the CS:GO skins data
* Generate a `cs_cases.csv` file with case names and their Steam Market API URLs

### 4. Populating the Database

Now you can populate the database with items from the CSV files.

```bash
python populate_database.py
```

Options:

* `--db path/to/db.db`: Specify a custom database path
* `--skins path/to/skins.csv`: Specify a custom skins CSV file
* `--cases path/to/cases.csv`: Specify a custom cases CSV file
* `--collections "Collection1" "Collection2"`: Only add items from specific collections
* `--cases-only`: Only add cases (skip skins)
* `--skins-only`: Only add skins (skip cases)
* `--list-collections`: Show available collections without adding anything
* `--debug`: Show additional debugging information
* `--no-quality-variants`: Don't create multiple wear quality variants

By default, the script creates 5 variants of each skin (Factory New, Minimal Wear, Field-Tested, Well-Worn, Battle-Scarred).

### 5. Updating Item Prices

You have two options for updating item prices:

#### Option A: Individual Price Updates

```bash
python update_price.py
```

Options:

* `--db path/to/db.db`: Specify a custom database path
* `--collections "Collection1" "Collection2"`: Only update items from specific collections
* `--max 100`: Limit the number of items to update
* `--no-retry`: Disable automatic retry on rate limiting

#### Option B: Bulk Price Updates (Recommended for Efficiency)

```bash
python bulk_scraper.py
```

Options:

* `--db path/to/db.db`: Specify a custom database path
* `--collections "Collection1" "Collection2"`: Only update items from specific collections
* `--max 1000`: Maximum number of items to fetch from Steam
* `--batch-size 100`: Number of items per API request
* `--type rifle`: Filter by item type (rifle, pistol, knife, container, sticker)
* `--quality stattrak`: Filter by quality (normal, stattrak, souvenir)
* `--weapon ak47`: Filter by specific weapon (ak47, awp, m4a4)
* `--exterior fn`: Filter by exterior (fn, mw, ft, ww, bs)
* `--query "Asiimov"`: Search for specific items
* `--list-filters`: Show available filter options

The bulk updater is much faster as it fetches many items at once rather than one by one.

### 6. Verifying the Database

To check the contents of your database:

```bash
python verify_database.py
```

This will display:

* Database file information
* List of all tables
* Column information for each table
* Row count for each table
* Sample data (up to 5 rows) from each table

## Common Use Cases

### Adding New Cases or Collections

```bash
# Update your CSV files with new data
python create_cases.py

# Add only the new collections to the database
python populate_database.py --collections "New Collection Name"
```

### Updating Prices for Specific Collections

```bash
# Using individual updater
python update_price.py --collections "Clutch Case" "Chroma Case"

# Using bulk updater (faster)
python bulk_scraper.py --collections "Clutch Case" "Chroma Case"
```

### Finding the Most Valuable Items

After updating prices, you can query the database directly with SQL:

```bash
sqlite3 csgo_items.db "SELECT name, price FROM items WHERE price IS NOT NULL ORDER BY price DESC LIMIT 10;"
```

## Troubleshooting

### Rate Limiting

If you encounter rate limiting from Steam:

* Increase the delay between requests (`--delay` parameter in the relevant scripts)
* Use smaller batch sizes (`--batch-size` parameter in bulk_scraper.py)
* Try updating fewer items at a time (`--max` parameter)

### Database Errors

If you encounter database errors:

* Try recreating the database: `python create_database.py`
* Check file permissions
* Verify the CSV files have the correct format

### Getting Help

Run any script with `--help` to see available options:

```bash
python populate_database.py --help
python update_price.py --help
python bulk_scraper.py --help
```

## Advanced Usage

### Custom Database and CSV Paths

```bash
# Create database in custom location
python create_database.py my_custom_db.db

# Use custom paths for everything
python populate_database.py --db my_custom_db.db --skins my_skins.csv --cases my_cases.csv
```

### Filtering by Item Type and Quality

```bash
# Update only StatTrak Factory New AK-47 skins
python bulk_scraper.py --weapon ak47 --quality stattrak --exterior fn
```

### Debugging

```bash
# Enable debug output
python populate_database.py --debug
```

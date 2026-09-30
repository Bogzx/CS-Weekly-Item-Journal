# CS:GO/CS2 Items Database - How to Use

This document explains how to use the provided scripts to create and maintain a database of CS:GO/CS2 items with their current market prices.

## System Requirements

* Python 3.11, 3.12 or 3.13
* Required Python packages: `requests` (`sqlite3` ships with Python)

## Quick Start

> All commands below are written to be run **from the repository root**, which
> is why they are prefixed with `Src/DB/`. If you `cd Src/DB` first, drop the
> prefix.

Here's the typical workflow to set up and use the database:

```bash
# 1. Create the database structure
python Src/DB/create_database.py

# 2. Download the skin, case and graffiti lists
python Src/DB/fetch_item_lists.py

# 3. Populate the database with items
python Src/DB/populate_database.py

# 4. Update item prices.
#    Prefer bulk_scraper: it fetches a page of items per Steam request
#    (Steam currently caps pages at 10), so the full market is ~3,500
#    requests / ~10 hours at the 10 s delay. update_price.py sleeps 15 s
#    before EVERY item, so a full refresh of a 20k-row database takes over
#    three days. Use it only for a few items.
python Src/DB/bulk_scraper.py  # For bulk updates (use this)
# OR
python Src/DB/update_price.py  # One item at a time (very slow)

# 5. Verify database contents
python Src/DB/verify_database.py
```

## Detailed Instructions

### 1. Creating the Database

The first step is to create the SQLite database that will store all the CS:GO items and their prices.

```bash
python Src/DB/create_database.py
```

This will:

* Create a new file named `csgo_items.db` in the current directory
* Set up all required tables (items, collections, etc.)
* If a database already exists with this name it is left untouched. Pass
  `--force` to rebuild the item tables; user accounts and journals are kept

### 2. Downloading the Item Lists

```bash
python Src/DB/fetch_item_lists.py
```

This downloads `skins.json`, `crates.json` and `graffiti.json` from
[ByMykel/CSGO-API](https://github.com/ByMykel/CSGO-API) (MIT License, an
export of the CS2 game files kept up to date by its maintainer) and writes:

* `cs_skins.csv`: Collection, Weapon, Skin, Quality, Steam Market API URL and
  `Wears`, the wears the skin actually exists in (a quarter of all skins do
  not come in all five)
* `cs_cases.csv`: every marketable weapon case
* `cs_graffiti.csv`: every marketable sealed graffiti, one row per colour

Options:

* `--ref <branch|tag|commit>`: download a specific snapshot instead of `main`
* `--source-dir DIR`: read the three JSON files from a local directory (offline)
* `--out-dir DIR`: where to write the CSVs (default: current directory)
* `--include-knives-and-gloves`: also list ★ items. They are skipped by
  default because the weekly drop never offers them and their finish names
  collide with ordinary skins in fuzzy matching.

If a download fails or a list comes back empty, the script exits with status 1
and leaves any existing CSVs untouched.

> The previous source, `create_cs_skins.js` (a scraper for the
> counterstrike.fandom.com skin list), was removed after the wiki started
> answering it with HTTP 403. `create_cases.py`, which derived the case list
> from that CSV, went with it.

### 3. Populating the Database

Now you can populate the database with items from the CSV files.

```bash
python Src/DB/populate_database.py
```

Options:

* `--db path/to/db.db`: Specify a custom database path
* `--skins path/to/skins.csv`: Specify a custom skins CSV file
* `--cases path/to/cases.csv`: Specify a custom cases CSV file
* `--graffiti path/to/graffiti.csv`: Specify a custom graffiti CSV file
* `--collections "Collection1" "Collection2"`: Only add items from specific collections
* `--cases-only`: Only add cases (skip skins)
* `--skins-only`: Only add skins (skip cases)
* `--list-collections`: Show available collections without adding anything
* `--debug`: Show additional debugging information

Each skin gets one row per wear listed in its `Wears` column. A skins CSV
without that column (the old wiki format) gets all five wears. Re-running the
script is safe: existing rows are kept, so prices are not lost.

### 4. Updating Item Prices

You have two options for updating item prices:

#### Option A: Individual Price Updates

```bash
python Src/DB/update_price.py
```

Options:

* `--db path/to/db.db`: Specify a custom database path
* `--collections "Collection1" "Collection2"`: Only update items from specific collections
* `--max 100`: Limit the number of items to update
* `--no-retry`: Disable automatic retry on rate limiting

#### Option B: Bulk Price Updates (Recommended for Efficiency)

```bash
python Src/DB/bulk_scraper.py
```

Options:

* `--db path/to/db.db`: Specify a custom database path
* `--collections "Collection1" "Collection2"`: Only update items from specific collections
* `--max 1000`: Maximum number of items to fetch from Steam
* `--batch-size 100`: Items requested per API call (Steam currently returns at most 10)
* `--type rifle`: Filter by item type (rifle, pistol, knife, container, sticker)
* `--quality stattrak`: Filter by quality (normal, stattrak, souvenir)
* `--weapon ak47`: Filter by specific weapon (ak47, awp, m4a4)
* `--exterior fn`: Filter by exterior (fn, mw, ft, ww, bs)
* `--query "Asiimov"`: Search for specific items
* `--list-filters`: Show available filter options

The bulk updater is much faster as it fetches many items at once rather than one by one.

### 5. Verifying the Database

To check the contents of your database:

```bash
python Src/DB/verify_database.py
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
# Refresh the CSV files from the item source
python Src/DB/fetch_item_lists.py

# Add only the new collections to the database
python Src/DB/populate_database.py --collections "New Collection Name"
```

### Updating Prices for Specific Collections

```bash
# Using individual updater
python Src/DB/update_price.py --collections "Clutch Case" "The Clutch Collection"

# Using bulk updater (faster)
python Src/DB/bulk_scraper.py --collections "Clutch Case" "The Clutch Collection"
```

### Finding the Most Valuable Items

After updating prices, you can query the database directly with SQL:

```bash
sqlite3 csgo_items.db "SELECT name, price FROM items WHERE price IS NOT NULL ORDER BY price DESC LIMIT 10;"
```

## Troubleshooting

### Rate Limiting

If you encounter rate limiting from Steam:

* bulk_scraper.py backs off automatically (60 s, then 120 s, honouring any
  `Retry-After`). If Steam keeps refusing it stops, saves the prices it already
  fetched and exits with status 1 -- wait before running it again
* Try updating fewer items at a time (`--max`, or filters such as `--type case`)
* `--batch-size` does not help: Steam returns at most 10 items per request

### Database Errors

If you encounter database errors:

* Try rebuilding the item tables: `python Src/DB/create_database.py --force`
* Check file permissions
* Verify the CSV files have the correct format

### Getting Help

Run any script with `--help` to see available options:

```bash
python Src/DB/populate_database.py --help
python Src/DB/update_price.py --help
python Src/DB/bulk_scraper.py --help
```

## Advanced Usage

### Custom Database and CSV Paths

```bash
# Create database in custom location
python Src/DB/create_database.py --db my_custom_db.db

# Use custom paths for everything
python Src/DB/fetch_item_lists.py --out-dir data/
python Src/DB/populate_database.py --db my_custom_db.db --skins data/cs_skins.csv --cases data/cs_cases.csv --graffiti data/cs_graffiti.csv
```

### Filtering by Item Type and Quality

```bash
# Update only StatTrak Factory New AK-47 skins
python Src/DB/bulk_scraper.py --weapon ak47 --quality stattrak --exterior fn
```

### Debugging

```bash
# Enable debug output
python Src/DB/populate_database.py --debug
```

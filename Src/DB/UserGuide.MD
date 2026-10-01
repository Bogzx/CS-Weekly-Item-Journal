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

# 4. Update item prices. bulk_scraper fetches a page of items per Steam
#    request (Steam currently caps pages at 10) and waits 10 s between pages.
python Src/DB/bulk_scraper.py --drop-pool  # only what the weekly drop offers (~2.5 h)

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

This downloads `skins.json`, `crates.json`, `graffiti.json` and `tools.json` from
[ByMykel/CSGO-API](https://github.com/ByMykel/CSGO-API) (MIT License, an
export of the CS2 game files kept up to date by its maintainer) and writes:

* `cs_skins.csv`: Collection, Weapon, Skin, Quality, Steam Market API URL and
  `Wears`, the wears the skin actually exists in (a quarter of all skins do
  not come in all five)
* `cs_cases.csv`: every marketable weapon case
* `cs_graffiti.csv`: every marketable sealed graffiti, one row per colour
* `cs_tools.csv`: non-marketable items the weekly drop offers (currently only
  the Charm Detachment Pack, from `tools.json`), stored as not tradable, $0

`cs_cases.csv` holds every marketable weapon case and sticker capsule (a
sticker capsule was offered in a 2023 drop); capsules are stored with
item type `case`.

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

`graffiti_scraper.py` (which built the graffiti list from the Steam Market)
and `update_price.py` (which priced one item per request, 15 s apart) were
removed: `fetch_item_lists.py` writes the graffiti list, and
`bulk_scraper.py --query "<name>"` prices a single item.

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
* `--tools path/to/tools.csv`: Non-tradable drop items (optional; skipped if the file is missing)
* `--collections "Collection1" "Collection2"`: Only add items from specific collections
* `--cases-only`: Only add cases (skip skins)
* `--skins-only`: Only add skins (skip cases)
* `--list-collections`: Show available collections without adding anything
* `--debug`: Show additional debugging information

Each skin gets one row per wear listed in its `Wears` column. A skins CSV
without that column (the old wiki format) gets all five wears. Re-running the
script is safe: existing rows are kept, so prices are not lost.

### 4. Updating Item Prices

```bash
python Src/DB/bulk_scraper.py --drop-pool
```

Options:

* `--db path/to/db.db`: Specify a custom database path
* `--collections "Collection1" "Collection2"`: Only update items from specific collections
* `--max 1000`: Maximum number of items to fetch from Steam
* `--batch-size 100`: Items requested per API call (Steam currently returns at most 10)
* `--type rifle`: Filter by item type (rifle, pistol, smg, sniper, knife, case, graffiti, sticker)
* `--quality stattrak`: Filter by quality (normal, stattrak, souvenir)
* `--weapon ak47`: Filter by specific weapon (ak47, awp, m4a4)
* `--exterior fn`: Filter by exterior (fn, mw, ft, ww, bs)
* `--query "Asiimov"`: Search for specific items
* `--drop-pool`: Only normal-quality weapon skins, cases and graffiti, i.e. what
  the weekly drop offers and what `fetch_item_lists.py` puts in the database
  (~8,900 items, ~900 requests, ~2.5 hours instead of ~10)
* `--list-filters`: Show available filter options

The price stored is Steam's `sell_price` for the item: the lowest current
listing, i.e. what a buyer pays, in USD. A seller receives about 13% less
after fees; the results page shows both.

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
python Src/DB/bulk_scraper.py --collections "Clutch Case" "The Clutch Collection"
# or a single item
python Src/DB/bulk_scraper.py --query "Revolution Case"
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
python Src/DB/bulk_scraper.py --help
```

## Advanced Usage

### Custom Database and CSV Paths

```bash
# Create database in custom location
python Src/DB/create_database.py --db my_custom_db.db

# Use custom paths for everything
python Src/DB/fetch_item_lists.py --out-dir data/
python Src/DB/populate_database.py --db my_custom_db.db --skins data/cs_skins.csv --cases data/cs_cases.csv --graffiti data/cs_graffiti.csv --tools data/cs_tools.csv
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

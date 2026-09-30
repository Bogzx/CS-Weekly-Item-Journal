"""
fetch_item_lists.py

Build the item lists that populate_database.py reads -- cs_skins.csv,
cs_cases.csv, cs_graffiti.csv and cs_tools.csv -- from ByMykel's CSGO-API, an
MIT-licensed JSON export of the CS2 game files
(https://github.com/ByMykel/CSGO-API).

This replaces create_cs_skins.js, which scraped counterstrike.fandom.com and
has been answered with HTTP 403 since at least 2026-09. It is four HTTP GETs
to raw.githubusercontent.com (no Steam requests, no Node) and also fixes two
data problems the wiki scrape had:

- Wears: about a quarter of all skins only exist in some wears (e.g. Factory
  New and Minimal Wear only). The wiki list had no float ranges, so every skin
  was inserted in all five wears and the phantom ones could never get a price.
  The API lists the wears each skin actually comes in; they are written to a
  `Wears` column that populate_database.py honours.
- Names: item names are the exact Steam `market_hash_name`s, which is what
  bulk_scraper.py matches prices on.

Knives and gloves ("★ ...") are left out by default: the weekly care package
never offers them, and because they share finish names with ordinary skins
("★ Butterfly Knife | Forest DDPAT" vs "Sawed-Off | Forest DDPAT") they only
add wrong fuzzy-match candidates and ~3,000 extra rows to price. Pass
--include-knives-and-gloves to keep them.

Usage (from the repository root):
    python Src/DB/fetch_item_lists.py
    python Src/DB/fetch_item_lists.py --ref <commit-sha>     # pin a snapshot
    python Src/DB/fetch_item_lists.py --source-dir ./api/en  # offline copy

Exits 1 without touching existing CSVs if a download fails or a list comes
back empty.
"""

import argparse
import csv
import json
import os
import sys
import urllib.parse

import requests

API_REPO_URL = "https://raw.githubusercontent.com/ByMykel/CSGO-API/{ref}/public/api/en/"
DEFAULT_REF = "main"
SOURCE_FILES = ("skins.json", "crates.json", "graffiti.json", "tools.json")
REQUEST_TIMEOUT = 60

WEAR_ORDER = ["Factory New", "Minimal Wear", "Field-Tested", "Well-Worn", "Battle-Scarred"]

# Crate types that can show up in a weekly care package: weapon cases, and
# sticker capsules ("Sticker Capsule 2" was offered in a 2023 drop, see
# Training_Images/TEST FINAL.png). Autograph capsules, souvenir packages and
# music kit boxes are not offered by the weekly drop.
CASE_TYPES = ("Case", "Sticker Capsule")

# Non-marketable items the weekly drop offers, by ByMykel tools.json id, with
# the name the drop card shows (it differs from the API's inventory name).
# They cannot be sold, so they are stored as worth $0 and marked not
# tradable. Only items actually seen in a drop are listed: the other five
# tools (Name Tag, Storage Unit, StatTrak Swap Tool, Chicken Egg/Feed) are
# store or event items with no evidence of dropping.
DROP_TOOLS = {
    "tool-4": "Charm Detachment Pack",  # API name "Charm Detachments"; 3 of 20 labelled drops
}

SKIN_FIELDS = ["Collection", "Weapon", "Skin", "Quality", "Steam Market API URL", "Wears"]
CASE_FIELDS = ["Case", "Steam Market API URL"]
GRAFFITI_FIELDS = ["Collection", "Name", "FullName", "SteamMarketURL"]
TOOL_FIELDS = ["Name", "Source ID", "Tradable"]


class SourceError(RuntimeError):
    """The item source could not be read or returned nothing usable."""


def price_api_url(market_hash_name):
    """Steam priceoverview URL for one market item."""
    return ("https://steamcommunity.com/market/priceoverview/?appid=730&market_hash_name="
            + urllib.parse.quote(market_hash_name))


def load_source(source_dir=None, ref=DEFAULT_REF):
    """Return {file name: parsed JSON} for every file in SOURCE_FILES.

    Reads from `source_dir` when given (offline use and tests), otherwise
    downloads from the ByMykel/CSGO-API repository at `ref`.
    """
    data = {}
    for name in SOURCE_FILES:
        if source_dir:
            path = os.path.join(source_dir, name)
            try:
                with open(path, encoding="utf-8") as f:
                    data[name] = json.load(f)
            except (OSError, ValueError) as e:
                raise SourceError(f"could not read {path}: {e}") from e
            continue

        url = API_REPO_URL.format(ref=ref) + name
        print(f"Downloading {url}")
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            raise SourceError(f"could not download {url}: {e}") from e
        if response.status_code != 200:
            raise SourceError(f"{url} returned HTTP {response.status_code}")
        try:
            data[name] = response.json()
        except ValueError as e:
            raise SourceError(f"{url} did not return JSON: {e}") from e

    for name, value in data.items():
        if not isinstance(value, list):
            raise SourceError(f"{name}: expected a JSON list, got {type(value).__name__}")
    return data


def _first_name(entries):
    """Name of the first {id, name} entry in a list, or ''."""
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("name"):
            return entry["name"]
    return ""


def skin_rows(skins, include_knives_and_gloves=False):
    """Rows for cs_skins.csv.

    Skips entries that have no wear (vanilla knives, which drop without a
    finish) and de-duplicates by name: Doppler phases are separate entries in
    the API but share one market name.
    """
    rows = []
    seen = set()
    for skin in skins:
        name = skin.get("name") or ""
        if " | " not in name or name in seen:
            continue
        if name.startswith("★") and not include_knives_and_gloves:
            continue
        wears = [w.get("name") for w in skin.get("wears") or [] if isinstance(w, dict)]
        wears = [w for w in WEAR_ORDER if w in wears]
        if not wears:
            continue
        seen.add(name)

        weapon, finish = name.split(" | ", 1)
        rows.append({
            "Collection": _first_name(skin.get("collections")) or _first_name(skin.get("crates")),
            "Weapon": weapon,
            "Skin": finish,
            "Quality": (skin.get("rarity") or {}).get("name", ""),
            "Steam Market API URL": price_api_url(f"{name} ({wears[0]})"),
            "Wears": ";".join(wears),
        })
    return rows


def case_rows(crates):
    """Rows for cs_cases.csv: marketable weapon cases and sticker capsules."""
    rows = []
    seen = set()
    for crate in crates:
        name = crate.get("market_hash_name")
        if crate.get("type") not in CASE_TYPES or not name or name in seen:
            continue
        seen.add(name)
        rows.append({"Case": name, "Steam Market API URL": price_api_url(name)})
    return rows


def graffiti_rows(graffiti):
    """Rows for cs_graffiti.csv: every marketable (sealed) graffiti."""
    rows = []
    seen = set()
    for item in graffiti:
        full_name = item.get("market_hash_name")
        if not full_name or full_name in seen:
            continue
        seen.add(full_name)
        short_name = full_name.split(" | ", 1)[1] if " | " in full_name else full_name
        rows.append({
            "Collection": _first_name(item.get("crates")) or "Graffiti",
            "Name": short_name,
            "FullName": full_name,
            "SteamMarketURL": price_api_url(full_name),
        })
    return rows


def tool_rows(tools):
    """Rows for cs_tools.csv: the DROP_TOOLS the API still lists."""
    by_id = {tool.get("id"): tool for tool in tools if isinstance(tool, dict)}
    rows = []
    for tool_id, drop_name in DROP_TOOLS.items():
        if tool_id not in by_id:
            print(f"Warning: {tool_id} ({drop_name}) is no longer in tools.json; skipped")
            continue
        rows.append({"Name": drop_name, "Source ID": tool_id, "Tradable": "0"})
    return rows


def write_csv(path, fieldnames, rows):
    """Write rows via a temp file so a failure never leaves a half-written CSV."""
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_path, path)


def build_item_lists(data, include_knives_and_gloves=False):
    """Turn the loaded source into {csv file name: (fieldnames, rows)}."""
    lists = {
        "cs_skins.csv": (SKIN_FIELDS, skin_rows(data["skins.json"], include_knives_and_gloves)),
        "cs_cases.csv": (CASE_FIELDS, case_rows(data["crates.json"])),
        "cs_graffiti.csv": (GRAFFITI_FIELDS, graffiti_rows(data["graffiti.json"])),
    }
    empty = [name for name, (_, rows) in lists.items() if not rows]
    # The tool list is a short allowlist and may legitimately come back
    # empty; it is written anyway so a stale file does not linger.
    lists["cs_tools.csv"] = (TOOL_FIELDS, tool_rows(data["tools.json"]))
    if empty:
        # Same guard as the old scraper should have had: an empty list means
        # the source changed shape, and writing it would wipe a good CSV.
        raise SourceError(f"no rows for {', '.join(empty)}; the source format may have changed")
    return lists


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Write cs_skins.csv, cs_cases.csv, cs_graffiti.csv and cs_tools.csv from ByMykel's CSGO-API")
    parser.add_argument("--out-dir", default=".", help="Directory to write the CSV files to")
    parser.add_argument("--ref", default=DEFAULT_REF,
                        help="Git ref of ByMykel/CSGO-API to download (branch, tag or commit)")
    parser.add_argument("--source-dir",
                        help="Read skins.json, crates.json, graffiti.json and tools.json from this directory instead")
    parser.add_argument("--include-knives-and-gloves", action="store_true",
                        help="Also list ★ knives and gloves (never offered by the weekly drop)")
    args = parser.parse_args(argv)

    try:
        lists = build_item_lists(load_source(args.source_dir, args.ref), args.include_knives_and_gloves)
    except SourceError as e:
        print(f"Error: {e}. Existing CSV files were left untouched.", file=sys.stderr)
        return 1

    os.makedirs(args.out_dir, exist_ok=True)
    for file_name, (fieldnames, rows) in lists.items():
        path = os.path.join(args.out_dir, file_name)
        write_csv(path, fieldnames, rows)
        print(f"Wrote {len(rows)} rows to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

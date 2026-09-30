# CS-Weekly-Item-Journal

![CS2 Drop Analyzer](https://img.shields.io/badge/CS2-Drop_Analyzer-orange)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![YOLO](https://img.shields.io/badge/YOLO-11-green)
![OpenCV](https://img.shields.io/badge/OpenCV-4.9%2B-red)
![Flask](https://img.shields.io/badge/Flask-3.0%2B-lightgrey)

A web application that analyzes your CS2 weekly drop screenshots, identifies items with AI, compares prices, and helps you track your drops over time in a personal journal. It recommends which two of the four items to claim, based on stored Steam Market prices.

## 🚀 Features

* **AI-Powered Item Detection** : Custom-trained YOLO model detects weekly drop boxes in screenshots
* **Automatic Text Recognition** : Advanced OCR pipeline extracts item names from screenshots
* **Intelligent Item Matching** : Sophisticated fuzzy matching algorithms correctly identify items despite OCR imperfections
* **Price Comparison** : Values each of the four items and recommends the two worth claiming
* **Real-time Price Tracking** : Automatic Steam Market price monitoring and updates
* **User Journal System** : Track your drops over time and monitor your total collection value
* **Drop History & EV** : Per-week charts of value added, cumulative collection value and expected value per drop
* **Web Interface** : Easy-to-use Flask web application for uploading and analyzing screenshots

## 📋 Overview

This project combines computer vision, deep learning, and web technologies to solve the challenge of tracking weekly drops in Counter-Strike 2.

### AI Model Training

The system uses a custom-trained YOLO (You Only Look Once) object detection model to identify the weekly drop boxes in CS2 screenshots. The model was trained on a dataset of annotated CS2 weekly drop screenshots to accurately detect and segment the relevant regions regardless of resolution, aspect ratio, or in-game visual settings.

### Image Processing Pipeline

1. **Box Detection** : The YOLO model locates the region containing the weekly drops
2. **Grid Segmentation** : The detected region is divided into a 1x4 grid for individual item extraction
3. **Text Region Targeting** : The system targets the lower section of each item box where the name text appears
4. **OCR Processing** : Multiple OCR methods are applied for optimal text extraction

### Item Matching System

The extracted text is processed through a sophisticated matching system that:

* Cleans and normalizes OCR output
* Uses multiple matching strategies (token-based, sequence, containment)
* Calculates similarity scores with confidence levels
* Provides appropriate wear variants for matched skins
* Specially handles case and graffiti item types

### Database System

* Comprehensive SQLite database of CS2/CS
  items
* Includes skins, cases, and graffiti with price information
* Intelligent price update mechanisms (both individual and bulk)
* Support for different wear variations and quality types

### Web Application

* User registration and authentication
* Screenshot upload via file selection or paste
* Visual results display with confidence indicators
* Personal journal system for tracking drops
* Collection value monitoring
* Recommendation of the two most valuable items (the game lets you claim two)

## 🛠️ Technologies Used

* **Object Detection** : Ultralytics YOLO
* **Computer Vision** : OpenCV, PIL
* **OCR** : EasyOCR
* **Backend** : Python, Flask
* **Database** : SQLite
* **Text Processing** : Advanced fuzzy matching algorithms
* **API Integration** : Steam Market 
* **Task Scheduling** : APScheduler
* **Frontend** : Hand-written HTML, CSS and vanilla JavaScript (no framework, no CDN)

## 🔧 Setup and Installation

### Prerequisites

* **Python 3.11, 3.12 or 3.13.** The pipeline needs `ultralytics >= 8.3.94` to
  load the bundled YOLO11 weights, and `numpy >= 1.26` to install at all on
  3.12+.
* A GPU is **not** required. Detection runs on four small crops per screenshot
  and is fast enough on CPU.

### Install

```bash
# Clone the repository
git clone https://github.com/Bogzx/CS-Weekly-Item-Journal.git
cd CS-Weekly-Item-Journal

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# Install dependencies.
# The default PyPI torch build is the CUDA one (~2.5 GB on Linux). This app
# only ever runs inference on small crops, so the CPU build is plenty:
pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

# ...or just this, if you want whatever torch build pip picks by default:
# pip install -r requirements.txt
```

### Configure

```bash
cp .env.EXAMPLE .env

# Generate a real signing key and write it into .env
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
```

Open `.env` and replace the placeholder `SECRET_KEY` line with the generated
one. Everything else has a working default.

### Build the item database

The item list comes from [ByMykel/CSGO-API](https://github.com/ByMykel/CSGO-API),
an MIT-licensed JSON export of the CS2 game files: three downloads from
raw.githubusercontent.com, no Steam requests and no Node.js. Prices come from
the Steam Market and take longer (see below).

All database scripts live in `Src/DB/` and are run from the repository root:

```bash
# 1. Create the empty schema. Refuses to touch an existing database; use
#    --force to rebuild only the item tables (accounts and journals are kept).
python Src/DB/create_database.py

# 2. Download the skin, case and graffiti lists (a few seconds) and write
#    cs_skins.csv, cs_cases.csv and cs_graffiti.csv. Pin a snapshot with
#    --ref <commit>; add --include-knives-and-gloves if you want ★ items too.
python Src/DB/fetch_item_lists.py

# 3. Load them into the database (~6,800 skin/wear rows, 42 cases, ~1,800 graffiti)
python Src/DB/populate_database.py

# 4. Fetch prices. bulk_scraper pulls a page of items per request -- prefer it.
#    A full crawl is ~3,500 requests (~10 hours); see "Updating Prices".
python Src/DB/bulk_scraper.py
```

Steps 1–3 take seconds and are covered by an offline test
(`tests/test_item_db_build.py`). Until step 4 has run, uploads work but show
"no price data" and make no recommendation.

Knives and gloves are left out by default: the weekly drop never offers them,
and they share finish names with ordinary skins ("★ Butterfly Knife | Forest
DDPAT"), so they only add wrong match candidates and thousands of rows to price.

### Run

```bash
python app.py
```

Visit `http://127.0.0.1:5000`.

To expose it on a LAN or enable the debugger, use the environment variables
rather than editing the source:

```bash
FLASK_HOST=0.0.0.0 FLASK_PORT=5000 FLASK_DEBUG=1 python app.py
```

`FLASK_DEBUG` is off by default on purpose — Werkzeug's debugger hands out an
interactive Python console on any unhandled exception.

## 📊 Database Structure

The system uses a SQLite database with the following key tables:

* **items** : Stores information about CS2 items (skins, cases, graffiti)
* **collections** : Stores collection names for easier filtering
* **users** : User account information
* **user_journals** : Records of items in users' journals

## 🖼️ Usage

1. **Register/Login** : Create an account to track your drops over time
2. **Upload Screenshot** : Take a screenshot of your CS2 weekly drops screen and upload it
3. **Review Results** : The system identifies items and displays matching candidates with price information
4. **Select Items** : The two most valuable items are marked Pick 1 / Pick 2 and pre-selected (see [How items are valued](#-how-items-are-valued))
5. **Add to Journal** : Confirm the correct items to add to your personal journal
6. **Track Value** : Watch total value and per-drop expected value on the **History** page

## 💲 How items are valued

The care-package screen names each item but does not show a skin's wear, so a
skin slot matches up to five market items (Factory New … Battle-Scarred) whose
prices can differ by 100×. The app:

1. values a slot only over its **top match's own wear variants**, never over
   other items that happened to fuzzy-match the OCR text;
2. shows the price range (min–max over the priced wears) on each slot;
3. counts one price from that range according to `VALUATION_RULE` (in `.env`):

   | `VALUATION_RULE` | Slot value | Use it when |
   |---|---|---|
   | `lowest` (default) | cheapest wear | you want a floor: a pick is worth at least this |
   | `median` | middle wear price | you want a typical value |
   | `highest` | priciest wear (usually Factory New) | the old, optimistic behaviour |

4. recommends the **two** highest-valued slots (the game lets you claim 2 of
   the 4) and pre-selects the entry the value came from. Change it to the real
   wear once you have claimed the item, so the journal records the right price.

Cases and graffiti have a single price, so the rule only changes how skins
compare to them.

## 🔄 Updating Prices

The scheduler runs a daily bulk price update at 00:00 UTC once the app is
running, using the limits in `price_update_config.json` (default: the first
5,000 market items by name, ~500 requests, roughly 85 minutes). To update
manually:

```bash
# Bulk update. Steam returns at most 10 items per request and the scraper
# waits 10 s between pages, so the whole market (~35k items) takes ~10 hours.
python Src/DB/bulk_scraper.py

# Narrow it down: only cases, or a single search term
python Src/DB/bulk_scraper.py --type case
python Src/DB/bulk_scraper.py --query "Revolution Case"

# Only write prices for specific collections (Steam is still crawled in full)
python Src/DB/bulk_scraper.py --collections "Clutch Case" "The Clutch Collection"

# Cap the number of market items fetched
python Src/DB/bulk_scraper.py --max 5000
```

On HTTP 429 the scraper backs off (60 s, 120 s, honouring `Retry-After`). If
Steam keeps refusing it stops, keeps the prices it already fetched, and exits
with status 1 so the scheduled job logs a failure.

`Src/DB/update_price.py` also exists and updates items one at a time. It sleeps
15 seconds before **every** request, so a full refresh of a 20k-row database
takes over three days. Use it only for a handful of specific items.

### Database verification

```bash
python Src/DB/verify_database.py
```

## ✅ Tests

```bash
pip install pytest
pytest -q
```

`tests/test_golden_image.py` runs the real detection + OCR pipeline against a
committed screenshot and asserts the four item names still come out. It is slow
(it downloads EasyOCR weights on first run) but it catches model-load breakage,
`ultralytics` drift, EasyOCR changes and CS2 UI changes in one assertion.

The unit tests around the recommendation logic and history aggregation are fast
and need no model:

```bash
pytest -q -m "not slow"
```

## 🕳️ Known gaps

* **The YOLO model cannot currently be retrained.** No label files and no
  `data.yaml` were ever committed, and the training run's `args.yaml` (removed
  from the tree, still in git history) points at a Google Colab path that no
  longer exists. `Models/BOX_TRAINED.pt` (mAP50
  0.995) is therefore irreplaceable. Re-labelling is an owner task — see the
  pull request description for concrete steps.
* **No prebuilt `csgo_items.db` ships.** The item list builds in seconds,
  but a full price crawl is ~10 hours because Steam serves 10 items per
  request. A priced database published as a GitHub Release asset would make
  the first run instant.
* **Built for your own machine or LAN.** Logins are throttled per client IP
  (in memory) and every form POST carries a CSRF token, but there is no
  HTTPS, no password reset and no account deletion. Put it behind a TLS proxy
  (and set `SESSION_COOKIE_SECURE=True`) before exposing it more widely; note
  that the login throttle then sees the proxy's address unless you add
  Werkzeug's `ProxyFix`.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📜 License

This project is licensed under the MIT License - see the LICENSE file for details.

---

*Note: This project is not affiliated with Valve Corporation or the Counter-Strike franchise. All CS2/CS*

* item names and related data are property of their respective owners.*

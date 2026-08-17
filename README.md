# CS-Weekly-Item-Journal

![CS2 Drop Analyzer](https://img.shields.io/badge/CS2-Drop_Analyzer-orange)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![YOLO](https://img.shields.io/badge/YOLO-11-green)
![OpenCV](https://img.shields.io/badge/OpenCV-4.9%2B-red)
![Flask](https://img.shields.io/badge/Flask-3.0%2B-lightgrey)

A web application that analyzes your CS2 weekly drop screenshots, identifies items with AI, compares prices, and helps you track your drops over time in a personal journal. The system automatically recommends the highest-value item to select based on current Steam Market prices.

## 🚀 Features

* **AI-Powered Item Detection** : Custom-trained YOLO model detects weekly drop boxes in screenshots
* **Automatic Text Recognition** : Advanced OCR pipeline extracts item names from screenshots
* **Intelligent Item Matching** : Sophisticated fuzzy matching algorithms correctly identify items despite OCR imperfections
* **Price Comparison** : Automatically determines which item has the highest market value
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
* Recommendation of highest-value items

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
* **Node.js 18+** — only for `create_cs_skins.js`, which scrapes the skin list.
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

> **Heads up:** this is the slow part. `create_cs_skins.js` scrapes a wiki and
> the price steps make tens of thousands of Steam Market requests. Expect
> hours. See [Owner follow-ups](#-known-gaps) — a prebuilt `csgo_items.db`
> shipped as a Release asset would remove this step entirely.

All database scripts live in `Src/DB/`:

```bash
# Create the empty schema
python Src/DB/create_database.py

# Generate the CS2 skin list (Node)
node Src/DB/create_cs_skins.js

# Generate the CS2 case list
python Src/DB/create_cases.py

# Populate the database from the generated data
python Src/DB/populate_database.py

# Fetch prices. bulk_scraper pulls 100 items per request -- prefer it.
python Src/DB/bulk_scraper.py

# Optional: add graffiti
python Src/DB/graffiti_scraper.py
```

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
4. **Select Item** : The highest-priced item is highlighted as the recommended choice and pre-selected
5. **Add to Journal** : Confirm the correct items to add to your personal journal
6. **Track Value** : Watch total value and per-drop expected value on the **History** page

## 🔄 Updating Prices

The scheduler runs a daily bulk price update automatically once the app is
running. To update manually:

```bash
# Bulk update -- 100 items per Steam request. This is the fast path.
python Src/DB/bulk_scraper.py

# Restrict to specific collections
python Src/DB/bulk_scraper.py --collections "Clutch Case" "Chroma Case"

# Control how many items are fetched per request (default 100)
python Src/DB/bulk_scraper.py --batch-size 100 --max 5000
```

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
  `data.yaml` were ever committed, and `my_model/train/args.yaml:4` points at a
  Google Colab path that no longer exists. `Models/BOX_TRAINED.pt` (mAP50
  0.995) is therefore irreplaceable. Re-labelling is an owner task — see the
  pull request description for concrete steps.
* **No prebuilt `csgo_items.db` ships.** Every new user pays hours of scraping.
  Publishing one as a GitHub Release asset is the single biggest adoption
  unlock.

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

# CS-Weekly-Item-Journal



<img src="https://img.shields.io/badge/CS2-Drop_Analyzer-orange" alt="CS2 Drop Analyzer"> <img src="https://img.shields.io/badge/Python-3.6%2B-blue" alt="Python"> <img src="https://img.shields.io/badge/YOLO-v11-green" alt="YOLO"> <img src="https://img.shields.io/badge/OpenCV-4.5%2B-red" alt="OpenCV"> <img src="https://img.shields.io/badge/Flask-2.0%2B-lightgrey" alt="Flask">


A web application that analyzes your CS2 weekly drop screenshots, identifies items with AI, compares prices, and helps you track your drops over time in a personal journal. The system automatically recommends the highest-value item to select based on current Steam Market prices.

## 🚀 Features

* **AI-Powered Item Detection** : Custom-trained YOLO model detects weekly drop boxes in screenshots
* **Automatic Text Recognition** : Advanced OCR pipeline extracts item names from screenshots
* **Intelligent Item Matching** : Sophisticated fuzzy matching algorithms correctly identify items despite OCR imperfections
* **Price Comparison** : Automatically determines which item has the highest market value
* **Real-time Price Tracking** : Automatic Steam Market price monitoring and updates
* **User Journal System** : Track your drops over time and monitor your total collection value
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

* Comprehensive SQLite database of CS2/CS:GO items
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
* **OCR** : EasyOCR, PyTesseract
* **Backend** : Python, Flask
* **Database** : SQLite
* **Text Processing** : Advanced fuzzy matching algorithms
* **Task Scheduling** : APScheduler
* **Frontend** : HTML, CSS, and JavaScript with Bootstrap for responsive design

## 🔧 Setup and Installation

### Prerequisites

* Python 3.6 or higher
* CUDA-compatible GPU recommended for faster detection
* Node.js 12.0+ (for certain dataset scripts)

### Installation Steps

```bash
# Clone the repository
git clone https://github.com/yourusername/CS-Weekly-Item-Journal.git
cd CS-Weekly-Item-Journal

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create the database
python create_database.py

# Generate CS:GO skins data
node create_cs_skins.js

# Generate CS:GO cases data
python create_cases.py

# Populate the database
python populate_database.py

# Update item prices
python update_price.py

# Run the Flask application
python app.py
```

Visit `http://127.0.0.1:5000` in your browser to access the application.

## 📊 Database Structure

The system uses a SQLite database with the following key tables:

* **items** : Stores information about CS2 items (skins, cases, graffiti)
* **collections** : Stores collection names for easier filtering
* **users** : User account information
* **user_journals** : Records of items in users' journals

## 🖼️ Usage

1. **Register/Login** : Create an account to track your drops over time
2. **Upload Screenshot** : Take a screenshot of your CS2 weekly drops screen and upload it
3. **Review Results** : The system will identify items and display matching candidates with price information
4. **Select Item** : The highest-priced item will be highlighted as the recommended choice
5. **Add to Journal** : Select the correct items to add to your personal journal
6. **Track Value** : Monitor the total value of your collected items in your journal

## 🔄 Updating Prices

The system automatically updates prices on a daily schedule, but you can also manually update them:

```bash
# Update prices for all items
python update_price.py

# Update prices for specific collections
python update_price.py --collections "Clutch Case" "Chroma Case"

# Use bulk updater (faster)
python bulk_scraper.py --collections "Clutch Case" "Chroma Case"
```

## 🔍 Advanced Usage

### Database Verification

```bash
# Verify database structure and content
python verify_database.py
```

## 📜 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgements

* Ultralytics for the YOLO implementation
* EasyOCR and Tesseract projects for OCR capabilities
* Steam for market data
* The CS2 community for testing and feedback---

*Note: This project is not affiliated with Valve Corporation or the Counter-Strike franchise. All CS2/CS:GO item names and related data are property of their respective owners.*

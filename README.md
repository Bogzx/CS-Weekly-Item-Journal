# CS-Weekly-Item-Journal

<img src="https://img.shields.io/badge/CS2-Drop_Analyzer-orange" alt="CS2 Drop Analyzer"> <img src="https://img.shields.io/badge/Python-3.6%2B-blue" alt="Python"> <img src="https://img.shields.io/badge/YOLO-11%2B-green" alt="YOLO"> <img src="https://img.shields.io/badge/OpenCV-4.5%2B-red" alt="OpenCV"> <img src="https://img.shields.io/badge/Flask-2.0%2B-lightgrey" alt="Flask">

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
* **OCR** : EasyOCR, PyTesseract
* **Backend** : Python, Flask
* **Database** : SQLite
* **Text Processing** : Advanced fuzzy matching algorithms
* **API Integration** : Steam Market API
* **Task Scheduling** : APScheduler
* **Frontend** : HTML, CSS, and JavaScript with Bootstrap for responsive design

## 🔧 Setup and Installation

### Prerequisites

* Python 3.6 or higher
* CUDA-compatible GPU recommended for faster detection
* Node.js 12.0+ (for certain dataset scripts)

### Installation Steps

<pre><div class="relative flex flex-col rounded-lg"><div class="text-text-300 absolute pl-3 pt-2.5 text-xs">bash</div><div class="pointer-events-none sticky my-0.5 ml-0.5 flex items-center justify-end px-1.5 py-1 mix-blend-luminosity top-0"><div class="from-bg-300/90 to-bg-300/70 pointer-events-auto rounded-md bg-gradient-to-b p-0.5 backdrop-blur-md"><button class="flex flex-row items-center gap-1 rounded-md p-1 py-0.5 text-xs transition-opacity delay-100 text-text-300 active:scale-95 select-none hover:bg-bg-200 opacity-60 hover:opacity-100" data-state="closed"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" viewBox="0 0 256 256" class="text-text-500 mr-px -translate-y-[0.5px]"><path d="M200,32H163.74a47.92,47.92,0,0,0-71.48,0H56A16,16,0,0,0,40,48V216a16,16,0,0,0,16,16H200a16,16,0,0,0,16-16V48A16,16,0,0,0,200,32Zm-72,0a32,32,0,0,1,32,32H96A32,32,0,0,1,128,32Zm72,184H56V48H82.75A47.93,47.93,0,0,0,80,64v8a8,8,0,0,0,8,8h80a8,8,0,0,0,8-8V64a47.93,47.93,0,0,0-2.75-16H200Z"></path></svg><span class="text-text-200 pr-0.5">Copy</span></button></div></div><div><div class="prismjs code-block__code !my-0 !rounded-lg !text-sm !leading-relaxed"><code class="language-bash"><span class=""><span class="token comment"># Clone the repository</span><span class="">
</span></span><span class=""><span class=""></span><span class="token function">git</span><span class=""> clone https://github.com/yourusername/CS-Weekly-Item-Journal.git
</span></span><span class=""><span class=""></span><span class="token builtin class-name">cd</span><span class=""> CS-Weekly-Item-Journal
</span></span><span class="">
</span><span class=""><span class=""></span><span class="token comment"># Create and activate virtual environment</span><span class="">
</span></span><span class="">python -m venv venv
</span><span class=""><span class=""></span><span class="token builtin class-name">source</span><span class=""> venv/bin/activate  </span><span class="token comment"># On Windows: venv\Scripts\activate</span><span class="">
</span></span><span class="">
</span><span class=""><span class=""></span><span class="token comment"># Install dependencies</span><span class="">
</span></span><span class=""><span class="">pip </span><span class="token function">install</span><span class=""> -r requirements.txt
</span></span><span class="">
</span><span class=""><span class=""></span><span class="token comment"># Create the database</span><span class="">
</span></span><span class="">python create_database.py
</span><span class="">
</span><span class=""><span class=""></span><span class="token comment"># Generate CS:GO skins data</span><span class="">
</span></span><span class=""><span class=""></span><span class="token function">node</span><span class=""> create_cs_skins.js
</span></span><span class="">
</span><span class=""><span class=""></span><span class="token comment"># Generate CS:GO cases data</span><span class="">
</span></span><span class="">python create_cases.py
</span><span class="">
</span><span class=""><span class=""></span><span class="token comment"># Populate the database</span><span class="">
</span></span><span class="">python populate_database.py
</span><span class="">
</span><span class=""><span class=""></span><span class="token comment"># Update item prices</span><span class="">
</span></span><span class="">python update_price.py
</span><span class="">
</span><span class=""><span class=""></span><span class="token comment"># Run the Flask application</span><span class="">
</span></span><span class="">python app.py</span></code></div></div></div></pre>

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

<pre><div class="relative flex flex-col rounded-lg"><div class="text-text-300 absolute pl-3 pt-2.5 text-xs">bash</div><div class="pointer-events-none sticky my-0.5 ml-0.5 flex items-center justify-end px-1.5 py-1 mix-blend-luminosity top-0"><div class="from-bg-300/90 to-bg-300/70 pointer-events-auto rounded-md bg-gradient-to-b p-0.5 backdrop-blur-md"><button class="flex flex-row items-center gap-1 rounded-md p-1 py-0.5 text-xs transition-opacity delay-100 text-text-300 active:scale-95 select-none hover:bg-bg-200 opacity-60 hover:opacity-100" data-state="closed"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" viewBox="0 0 256 256" class="text-text-500 mr-px -translate-y-[0.5px]"><path d="M200,32H163.74a47.92,47.92,0,0,0-71.48,0H56A16,16,0,0,0,40,48V216a16,16,0,0,0,16,16H200a16,16,0,0,0,16-16V48A16,16,0,0,0,200,32Zm-72,0a32,32,0,0,1,32,32H96A32,32,0,0,1,128,32Zm72,184H56V48H82.75A47.93,47.93,0,0,0,80,64v8a8,8,0,0,0,8,8h80a8,8,0,0,0,8-8V64a47.93,47.93,0,0,0-2.75-16H200Z"></path></svg><span class="text-text-200 pr-0.5">Copy</span></button></div></div><div><div class="prismjs code-block__code !my-0 !rounded-lg !text-sm !leading-relaxed"><code class="language-bash"><span class=""><span class="token comment"># Update prices for all items</span><span class="">
</span></span><span class="">python update_price.py
</span><span class="">
</span><span class=""><span class=""></span><span class="token comment"># Update prices for specific collections</span><span class="">
</span></span><span class=""><span class="">python update_price.py --collections </span><span class="token string">"Clutch Case"</span><span class=""></span><span class="token string">"Chroma Case"</span><span class="">
</span></span><span class="">
</span><span class=""><span class=""></span><span class="token comment"># Use bulk updater (faster)</span><span class="">
</span></span><span class=""><span class="">python bulk_scraper.py --collections </span><span class="token string">"Clutch Case"</span><span class=""></span><span class="token string">"Chroma Case"</span></span></code></div></div></div></pre>

## 🔍 Advanced Usage

### Filtering by Item Properties

<pre><div class="relative flex flex-col rounded-lg"><div class="text-text-300 absolute pl-3 pt-2.5 text-xs">bash</div><div class="pointer-events-none sticky my-0.5 ml-0.5 flex items-center justify-end px-1.5 py-1 mix-blend-luminosity top-0"><div class="from-bg-300/90 to-bg-300/70 pointer-events-auto rounded-md bg-gradient-to-b p-0.5 backdrop-blur-md"><button class="flex flex-row items-center gap-1 rounded-md p-1 py-0.5 text-xs transition-opacity delay-100 text-text-300 active:scale-95 select-none hover:bg-bg-200 opacity-60 hover:opacity-100" data-state="closed"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" viewBox="0 0 256 256" class="text-text-500 mr-px -translate-y-[0.5px]"><path d="M200,32H163.74a47.92,47.92,0,0,0-71.48,0H56A16,16,0,0,0,40,48V216a16,16,0,0,0,16,16H200a16,16,0,0,0,16-16V48A16,16,0,0,0,200,32Zm-72,0a32,32,0,0,1,32,32H96A32,32,0,0,1,128,32Zm72,184H56V48H82.75A47.93,47.93,0,0,0,80,64v8a8,8,0,0,0,8,8h80a8,8,0,0,0,8-8V64a47.93,47.93,0,0,0-2.75-16H200Z"></path></svg><span class="text-text-200 pr-0.5">Copy</span></button></div></div><div><div class="prismjs code-block__code !my-0 !rounded-lg !text-sm !leading-relaxed"><code class="language-bash"><span class=""><span class="token comment"># Update only StatTrak Factory New AK-47 skins</span><span class="">
</span></span><span class="">python bulk_scraper.py --weapon ak47 --quality stattrak --exterior fn</span></code></div></div></div></pre>

### Database Verification

<pre><div class="relative flex flex-col rounded-lg"><div class="text-text-300 absolute pl-3 pt-2.5 text-xs">bash</div><div class="pointer-events-none sticky my-0.5 ml-0.5 flex items-center justify-end px-1.5 py-1 mix-blend-luminosity top-0"><div class="from-bg-300/90 to-bg-300/70 pointer-events-auto rounded-md bg-gradient-to-b p-0.5 backdrop-blur-md"><button class="flex flex-row items-center gap-1 rounded-md p-1 py-0.5 text-xs transition-opacity delay-100 text-text-300 active:scale-95 select-none hover:bg-bg-200 opacity-60 hover:opacity-100" data-state="closed"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" viewBox="0 0 256 256" class="text-text-500 mr-px -translate-y-[0.5px]"><path d="M200,32H163.74a47.92,47.92,0,0,0-71.48,0H56A16,16,0,0,0,40,48V216a16,16,0,0,0,16,16H200a16,16,0,0,0,16-16V48A16,16,0,0,0,200,32Zm-72,0a32,32,0,0,1,32,32H96A32,32,0,0,1,128,32Zm72,184H56V48H82.75A47.93,47.93,0,0,0,80,64v8a8,8,0,0,0,8,8h80a8,8,0,0,0,8-8V64a47.93,47.93,0,0,0-2.75-16H200Z"></path></svg><span class="text-text-200 pr-0.5">Copy</span></button></div></div><div><div class="prismjs code-block__code !my-0 !rounded-lg !text-sm !leading-relaxed"><code class="language-bash"><span class=""><span class="token comment"># Verify database structure and content</span><span class="">
</span></span><span class="">python verify_database.py</span></code></div></div></div></pre>

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📜 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgements

* Ultralytics for the YOLO implementation
* EasyOCR and Tesseract projects for OCR capabilities
* Steam for market data
* The CS2 community for testing and feedback

## 📞 Contact

If you have any questions or suggestions, please open an issue or contact the repository maintainer.

---

*Note: This project is not affiliated with Valve Corporation or the Counter-Strike franchise. All CS2/CS*

* item names and related data are property of their respective owners.*

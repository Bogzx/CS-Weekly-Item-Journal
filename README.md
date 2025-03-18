# CS-Weekly-Item-Journal
CS2 Weekly Drop Analyzer
A web application built with Python and Flask that analyzes your CS2 weekly drop. Simply upload a picture of your drop, and the app will automatically detect the items, compare their prices, and recommend the highest-priced item to choose. It also provides journaling functionality, allowing you to record your selected items and track the total value accumulated over time.

Features
Image Upload & Analysis
Upload a picture of your CS2 weekly drop. The app processes the image to detect and identify individual items.

Price Comparison
Automatically determines which item has the highest price and suggests that item for selection.

Journaling & Tracking
Save your chosen items into a database and view a running total of the accumulated item values.

User-Friendly Interface
A simple, intuitive web interface for seamless interaction.

Technologies Used
Backend: Python, Flask
Image Processing: Python libraries (e.g., OpenCV, Pillow) for analyzing uploaded images
Database: SQLite (or another preferred database) for journaling item selections
Frontend: HTML, CSS, and JavaScript (optionally with frameworks like Bootstrap for styling)
Installation
Prerequisites
Python 3.7 or higher
pip (Python package installer)
(Optional) Virtual environment tool (e.g., venv or virtualenv)
Steps
Clone the Repository

bash
Copy
Edit
git clone https://github.com/yourusername/cs2-weekly-drop-analyzer.git
cd cs2-weekly-drop-analyzer
Set Up a Virtual Environment

bash
Copy
Edit
python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
Install Dependencies

bash
Copy
Edit
pip install -r requirements.txt
Configure Environment Variables

For Flask development, set the following environment variables:

bash
Copy
Edit
export FLASK_APP=app.py
export FLASK_ENV=development
Run the Application

bash
Copy
Edit
flask run
Access the App

Open your browser and navigate to http://localhost:5000.

Usage
Upload an Image
On the home page, upload a picture of your CS2 weekly drop.

Automatic Analysis
The app will process the image to identify the items and determine which one has the highest price.

View Recommendation
The recommended item (with the highest price) will be highlighted.

Journal Your Selection
Optionally, save the item details to your journal. The app will update your total accumulated value accordingly.

Review Your Journal
Navigate to the journal page to view all saved items and your cumulative total.

Contributing
Contributions are welcome! Follow these steps to contribute:

Fork the Repository

Create a Feature Branch

bash
Copy
Edit
git checkout -b feature/YourFeatureName
Commit Your Changes

bash
Copy
Edit
git commit -m "Add: Description of your feature"
Push to Your Branch

bash
Copy
Edit
git push origin feature/YourFeatureName
Open a Pull Request

Ensure your pull request describes the changes and the purpose of the feature or fix.

License
This project is licensed under the MIT License.

Acknowledgments
Special thanks to the developers and open source community for their contributions.
Inspired by CS2 and its dynamic weekly drops.
Additional thanks to the libraries and frameworks that made this project possible.
Happy coding and may your drops always be valuable!








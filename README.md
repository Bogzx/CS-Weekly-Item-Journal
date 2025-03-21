# CS-Weekly-Item-Journal

**CS2 Weekly Drop Analyzer**

A web application built with Python and Flask that analyzes your CS2 weekly drop. Simply upload a picture of your drop, and the app will automatically detect the items, compare their prices, and recommend the highest-priced item to choose. It also provides journaling functionality, allowing you to record your selected items and track the total value accumulated over time.

## Features

### Image Upload & Analysis
- Upload a picture of your CS2 weekly drop.
- The app processes the image to detect and identify individual items.

### Price Comparison
- Automatically determines which item has the highest price.
- Suggests the highest-priced item for selection.

### Journaling & Tracking
- Save your chosen items into a database.
- View a running total of the accumulated item values.

### User-Friendly Interface
- A simple, intuitive web interface for seamless interaction.

## Technologies Used

- **Backend:** Python, Flask
- **Image Processing:** Python libraries (e.g., OpenCV, Pillow) for analyzing uploaded images
- **Database:** SQLite (or another preferred database) for journaling item selections
- **Frontend:** HTML, CSS, and JavaScript (optionally with frameworks like Bootstrap for styling)

## Usage

### Upload an Image
- On the home page, upload a picture of your CS2 weekly drop.

### Automatic Analysis
- The app will process the image to identify the items.
- It will determine which item has the highest price.

### View Recommendation
- The recommended item (with the highest price) will be highlighted.

### Journal Your Selection
- Optionally, save the item details to your journal.
- The app will update your total accumulated value accordingly.

### Review Your Journal
- Navigate to the journal page to view all saved items and your cumulative total.


## License

This project is licensed under the MIT License.

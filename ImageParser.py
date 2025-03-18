import cv2
import numpy as np
import pytesseract
from ultralytics import YOLO  # For object detection

def extract_weekly_items(screenshot_path):
    # Load image
    img = cv2.imread(screenshot_path)
    
    # Resize for consistency while maintaining aspect ratio
    height, width = img.shape[:2]
    scale_factor = 1000 / width  # Normalize width to 1000px
    img_resized = cv2.resize(img, (0, 0), fx=scale_factor, fy=scale_factor)
    
    # 1. Find the "WEEKLY CARE PACKAGE" header using template matching or text detection
    # This serves as our anchor point
    header = find_weekly_header(img_resized)
    if not header:
        # Try alternative detection methods
        header = detect_weekly_section_by_color_scheme(img_resized)
    
    if not header:
        return "Weekly care package section not found in image"
    
    # 2. Use the header location to define the search area for reward boxes
    search_area = define_search_area_from_header(img_resized, header)
    
    # 3. Detect box-like UI elements in the search area
    # Could use edge detection, contour finding, or a trained object detector
    boxes = detect_reward_boxes(search_area)
    
    # 4. For each detected box, extract and process text
    item_names = []
    for box in boxes:
        # Apply perspective correction if needed
        corrected_box = apply_perspective_correction(box)
        
        # Enhance text visibility
        processed_box = preprocess_for_ocr(corrected_box)
        
        # Apply OCR
        text = pytesseract.image_to_string(processed_box)
        cleaned_text = clean_ocr_result(text)
        
        if is_valid_item_name(cleaned_text):
            item_names.append(cleaned_text)
    
    return item_names

if __name__ == "__main__":
    screenshot_path = "weekly_care_package.png"
    items = extract_weekly_items(screenshot_path)
    print(items)
import os
import cv2
import numpy as np
import pytesseract
from ultralytics import YOLO
import matplotlib.pyplot as plt
from PIL import Image

class CS2WeeklyRewardExtractor:
    def __init__(self, model_path=None):
        """
        Initialize the CS2 weekly reward extractor.
        
        Args:
            model_path: Path to a pre-trained YOLO model. If None, will use YOLOv8n.
        """
        # Load YOLO model - if no custom model is provided, use a pre-trained one
        if model_path and os.path.exists(model_path):
            self.model = YOLO(model_path)
        else:
            # Use YOLOv8n as default
            self.model = YOLO('yolov8n.pt')
            print("Using default YOLOv8n model. For better results, train a custom model on CS2 UI elements.")
        
        # Configure pytesseract path if not in system PATH
        # pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'  # Uncomment and modify for Windows
    
    def detect_weekly_section(self, image):
        """
        Detect the weekly care package section in the image.
        
        Args:
            image: Input image (numpy array)
            
        Returns:
            Cropped image of the weekly care package section or None if not found
        """
        # Method 1: Try to detect text "WEEKLY CARE PACKAGE"
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Apply adaptive thresholding to handle different lighting conditions
        thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                      cv2.THRESH_BINARY_INV, 11, 2)
        
        # OCR to find "WEEKLY CARE PACKAGE" text
        results = pytesseract.image_to_data(thresh, output_type=pytesseract.Output.DICT)
        
        weekly_section = None
        y_min, y_max, x_min, x_max = None, None, None, None
        
        # Look for the weekly care package header
        for i in range(len(results["text"])):
            text = results["text"][i].strip().upper()
            if "WEEKLY" in text and ("CARE" in text or "PACKAGE" in text):
                x = results["left"][i]
                y = results["top"][i]
                w = results["width"][i]
                h = results["height"][i]
                
                # Expand the region to include items below the header
                y_min = max(0, y - 50)  # Add some margin above
                y_max = min(image.shape[0], y + h + 300)  # Extend below to include reward boxes
                x_min = max(0, x - 100)  # Add margin to the left
                x_max = min(image.shape[1], x + w + 400)  # Add margin to the right
                
                weekly_section = image[y_min:y_max, x_min:x_max]
                break
        
        # Method 2: If text detection failed, try color-based detection for orange/brown weekly care banner
        if weekly_section is None:
            # Convert to HSV for better color detection
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            
            # Define range for orange/brown color (adjust as needed for CS2's color scheme)
            lower_orange = np.array([10, 100, 100])
            upper_orange = np.array([30, 255, 255])
            
            # Create mask for orange colors
            mask = cv2.inRange(hsv, lower_orange, upper_orange)
            
            # Find contours in the mask
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if contours:
                # Find the largest orange contour (likely the weekly care package banner)
                largest_contour = max(contours, key=cv2.contourArea)
                x, y, w, h = cv2.boundingRect(largest_contour)
                
                # Adjust to include reward boxes below
                y_min = max(0, y)
                y_max = min(image.shape[0], y + h + 300)
                x_min = max(0, x - 50)
                x_max = min(image.shape[1], x + w + 50)
                
                weekly_section = image[y_min:y_max, x_min:x_max]
        
        return weekly_section, (y_min, y_max, x_min, x_max) if weekly_section is not None else None
    
    def detect_reward_boxes(self, weekly_section):
        """
        Detect the reward boxes in the weekly care package section.
        
        Args:
            weekly_section: Cropped image of weekly care package section
            
        Returns:
            List of cropped images of individual reward boxes
        """
        if weekly_section is None:
            return []
        
        # Use YOLO to detect rectangular objects that might be reward boxes
        results = self.model(weekly_section, classes=[0, 2, 73, 67])  # 0: person, 2: car, 73: laptop, 67: cell phone
                                                           # These general classes might detect rectangular UI elements
        
        reward_boxes = []
        detected_boxes = []
        
        # Extract all detected boxes
        if len(results) > 0:
            for result in results:
                boxes = result.boxes.xyxy.cpu().numpy()
                for box in boxes:
                    x1, y1, x2, y2 = box
                    detected_boxes.append((int(x1), int(y1), int(x2), int(y2)))
        
        # If YOLO detection doesn't work well, fall back to edge detection
        if not detected_boxes:
            gray = cv2.cvtColor(weekly_section, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            edges = cv2.Canny(blurred, 50, 150)
            
            # Dilate edges to connect broken lines
            kernel = np.ones((3, 3), np.uint8)
            dilated = cv2.dilate(edges, kernel, iterations=2)
            
            # Find contours
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Filter contours by size and shape
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                aspect_ratio = w / h
                
                # Look for rectangular contours with appropriate size and aspect ratio
                if w > 50 and h > 50 and 0.5 < aspect_ratio < 2.5:
                    detected_boxes.append((x, y, x + w, y + h))
        
        # Process detected boxes
        if detected_boxes:
            # Sort boxes by x-coordinate to get them from left to right
            detected_boxes.sort(key=lambda box: box[0])
            
            # Group overlapping boxes (non-maximum suppression)
            final_boxes = self.non_max_suppression(detected_boxes, 0.5)
            
            # Extract each box
            for (x1, y1, x2, y2) in final_boxes[:4]:  # Limit to 4 boxes (weekly rewards)
                box_img = weekly_section[int(y1):int(y2), int(x1):int(x2)]
                if box_img.size > 0:  # Ensure the box is not empty
                    reward_boxes.append(box_img)
        
        # If we still don't have boxes, try dividing the area into 4 equal parts
        if not reward_boxes:
            h, w = weekly_section.shape[:2]
            box_width = w // 4
            for i in range(4):
                x1 = i * box_width
                x2 = (i + 1) * box_width
                box_img = weekly_section[0:h, x1:x2]
                reward_boxes.append(box_img)
        
        return reward_boxes
    
    def non_max_suppression(self, boxes, overlap_threshold=0.5):
        """
        Apply non-maximum suppression to eliminate redundant overlapping boxes.
        
        Args:
            boxes: List of boxes in (x1, y1, x2, y2) format
            overlap_threshold: IoU threshold for suppression
            
        Returns:
            List of filtered boxes
        """
        if not boxes:
            return []
        
        # Convert to numpy array
        boxes = np.array(boxes)
        
        # Initialize the list of picked indexes
        pick = []
        
        # Calculate areas for all boxes
        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]
        area = (x2 - x1 + 1) * (y2 - y1 + 1)
        
        # Sort by bottom-right y-coordinate
        idxs = np.argsort(y2)
        
        while len(idxs) > 0:
            last = len(idxs) - 1
            i = idxs[last]
            pick.append(i)
            
            xx1 = np.maximum(x1[i], x1[idxs[:last]])
            yy1 = np.maximum(y1[i], y1[idxs[:last]])
            xx2 = np.minimum(x2[i], x2[idxs[:last]])
            yy2 = np.minimum(y2[i], y2[idxs[:last]])
            
            w = np.maximum(0, xx2 - xx1 + 1)
            h = np.maximum(0, yy2 - yy1 + 1)
            
            overlap = (w * h) / area[idxs[:last]]
            
            # Delete all indexes that overlap sufficiently
            idxs = np.delete(idxs, np.concatenate(([last], np.where(overlap > overlap_threshold)[0])))
        
        return boxes[pick].tolist()
    
    def extract_item_names(self, reward_boxes):
        """
        Extract item names from the reward boxes using OCR.
        
        Args:
            reward_boxes: List of cropped images of individual reward boxes
            
        Returns:
            List of extracted item names
        """
        item_names = []
        
        for i, box in enumerate(reward_boxes):
            if box is None or box.size == 0:
                item_names.append(f"Item {i+1}: [Detection failed]")
                continue
                
            # Preprocess image for better OCR
            # Convert to grayscale
            gray = cv2.cvtColor(box, cv2.COLOR_BGR2GRAY)
            
            # Apply adaptive thresholding
            thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                          cv2.THRESH_BINARY, 11, 2)
            
            # Invert colors if necessary (white text on dark background)
            if np.mean(gray) < 127:  # Dark background
                thresh = cv2.bitwise_not(thresh)
            
            # Remove noise using morphological operations
            kernel = np.ones((1, 1), np.uint8)
            opening = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
            
            # Apply OCR with different configurations
            # Set Tesseract configuration for single line of text
            custom_config = r'--oem 3 --psm 7 -c tessedit_char_whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -|"'
            
            # Try OCR with different preprocessed images
            text1 = pytesseract.image_to_string(box, config=custom_config)
            text2 = pytesseract.image_to_string(gray, config=custom_config)
            text3 = pytesseract.image_to_string(thresh, config=custom_config)
            text4 = pytesseract.image_to_string(opening, config=custom_config)
            
            # Choose the result with the most characters
            ocr_results = [text1, text2, text3, text4]
            text = max(ocr_results, key=len).strip()
            
            # Clean up the result
            text = text.replace('\n', ' ').strip()
            
            # If OCR failed completely
            if not text:
                text = f"Item {i+1}: [OCR failed]"
            
            item_names.append(text)
        
        return item_names
    
    def process_screenshot(self, image_path, visualize=True):
        """
        Process a CS2 screenshot to extract weekly reward items.
        
        Args:
            image_path: Path to the screenshot image
            visualize: Whether to show visualization of the detection process
            
        Returns:
            List of extracted item names
        """
        # Load image
        image = cv2.imread(image_path)
        if image is None:
            return ["Error: Could not load image"]
        
        # Resize if too large (keeping aspect ratio)
        if max(image.shape) > 1920:
            scale = 1920 / max(image.shape)
            image = cv2.resize(image, (0, 0), fx=scale, fy=scale)
        
        # 1. Detect weekly care package section
        weekly_section, section_coords = self.detect_weekly_section(image)
        
        # 2. Detect reward boxes within the section
        reward_boxes = self.detect_reward_boxes(weekly_section)
        
        # 3. Extract item names
        item_names = self.extract_item_names(reward_boxes)
        
        # 4. Visualize if requested
        if visualize:
            self.visualize_results(image, section_coords, reward_boxes, item_names, weekly_section)
        
        return item_names
    
    def visualize_results(self, image, section_coords, reward_boxes, item_names, weekly_section):
        """
        Visualize the detection results.
        
        Args:
            image: Original image
            section_coords: Coordinates of the weekly section
            reward_boxes: List of detected reward box images
            item_names: List of extracted item names
            weekly_section: Cropped weekly section image
        """
        # Create a figure with multiple subplots
        plt.figure(figsize=(15, 10))
        
        # Plot original image with weekly section highlighted
        plt.subplot(2, 2, 1)
        img_copy = image.copy()
        if section_coords:
            y_min, y_max, x_min, x_max = section_coords
            cv2.rectangle(img_copy, (x_min, y_min), (x_max, y_max), (0, 255, 0), 3)
        plt.imshow(cv2.cvtColor(img_copy, cv2.COLOR_BGR2RGB))
        plt.title("Original Image with Weekly Section")
        plt.axis('off')
        
        # Plot weekly section
        plt.subplot(2, 2, 2)
        if weekly_section is not None:
            plt.imshow(cv2.cvtColor(weekly_section, cv2.COLOR_BGR2RGB))
            plt.title("Weekly Care Package Section")
        else:
            plt.text(0.5, 0.5, "Weekly Section Not Found", ha='center', va='center')
        plt.axis('off')
        
        # Plot detected boxes and item names
        for i, (box, name) in enumerate(zip(reward_boxes, item_names)):
            if i >= 4:  # Only show up to 4 reward boxes
                break
                
            plt.subplot(2, 4, i+5)
            if box is not None and box.size > 0:
                plt.imshow(cv2.cvtColor(box, cv2.COLOR_BGR2RGB))
                plt.title(f"Box {i+1}: {name}")
            else:
                plt.text(0.5, 0.5, f"Box {i+1} Not Detected", ha='center', va='center')
            plt.axis('off')
        
        plt.tight_layout()
        plt.show()
        
        # Print the extracted item names
        print("Extracted Item Names:")
        for i, name in enumerate(item_names):
            print(f"{i+1}. {name}")


def main():
    """
    Main function to run the CS2 weekly reward extractor.
    """
    # Initialize the extractor
    extractor = CS2WeeklyRewardExtractor()
    
    # Get the image path from user input
    image_path = input("Enter the path to the CS2 screenshot: ")
    
    # Process the screenshot
    item_names = extractor.process_screenshot(image_path)
    
    # Print the results
    print("\nWeekly Reward Items:")
    for i, name in enumerate(item_names):
        print(f"{i+1}. {name}")


if __name__ == "__main__":
    main()
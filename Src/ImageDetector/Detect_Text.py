import cv2
import numpy as np
import easyocr
from ultralytics import YOLO
import os

class WeeklyDropProcessor:
    def __init__(self, yolo_model_path):
        """
        Initialize the weekly drop processor
        
        Args:
            yolo_model_path: Path to the pre-trained YOLO model
        """
        self.model = YOLO(yolo_model_path)
        # Initialize EasyOCR reader
        self.reader = easyocr.Reader(['en'])  # English language
        
    def process_image(self, image_path, output_dir="output"):
        """
        Process an image containing weekly drops
        
        Args:
            image_path: Path to the input image
            output_dir: Directory to save output images and results
            
        Returns:
            A list of dictionaries containing cropped images and detected text
        """
        # Create output directory if it doesn't exist
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        # Read the image
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError(f"Could not read image at {image_path}")
            
        # Run YOLO detection to get the main bounding box
        results = self.model(image)
        
        # Extract the bounding box coordinates (assuming the first detection is our target)
        if len(results[0].boxes) == 0:
            raise ValueError("No bounding box detected in the image")
            
        # Get the first box (main box containing all 4 weekly drops)
        main_box = results[0].boxes[0].xyxy.cpu().numpy()[0]
        x1, y1, x2, y2 = map(int, main_box)
        
        # Crop the main box
        main_crop = image[y1:y2, x1:x2]
        
        # Save the main crop
        main_crop_path = os.path.join(output_dir, "main_crop.jpg")
        cv2.imwrite(main_crop_path, main_crop)
        
        # Get dimensions of the main crop
        height, width = main_crop.shape[:2]
        
        # Calculate dimensions for each of the 4 boxes
        # Using a 1x4 grid layout (4 columns)
        box_width = width // 4
        box_height = height
        
        crops = []
        texts = []
        
        # Crop into 4 boxes (columns)
        for col in range(4):
            # Calculate coordinates for this crop
            crop_x1 = col * box_width
            crop_y1 = 0
            crop_x2 = crop_x1 + box_width
            crop_y2 = crop_y1 + box_height
            
            # Extract the crop
            crop = main_crop[crop_y1:crop_y2, crop_x1:crop_x2]
            
            # Save the crop
            crop_filename = f"crop_{col}.jpg"
            crop_path = os.path.join(output_dir, crop_filename)
            cv2.imwrite(crop_path, crop)
            
            # Only use the lower half for text detection
            crop_height = crop.shape[0]
            lower_half = crop[crop_height//2:, :]
            
            # Save the lower half for inspection
            lower_half_path = os.path.join(output_dir, f"lower_half_{col}.jpg")
            cv2.imwrite(lower_half_path, lower_half)
            
            # Use EasyOCR for text detection on the lower half
            results_ocr = self.reader.readtext(lower_half)
            
            # Extract text from OCR results
            text = " ".join([result[1] for result in results_ocr])
            
            # Store results
            crops.append(crop)
            texts.append(text.strip())
            
            # Save the text to a file
            text_path = os.path.join(output_dir, f"text_{col}.txt")
            with open(text_path, 'w') as f:
                f.write(text)
        
        # Compile results
        results = []
        for col, (crop, text) in enumerate(zip(crops, texts)):
            results.append({
                'position': f"col_{col}",
                'crop_path': os.path.join(output_dir, f"crop_{col}.jpg"),
                'text': text
            })
            
        return results

# Example usage
if __name__ == "__main__":
    # Initialize the processor
    processor = WeeklyDropProcessor("Models\BOX_TRAINED.pt")
    
    # Process an images
    results = processor.process_image("image.png")
    
    # Print the detected text for each box
    for result in results:
        print(f"Box {result['position']}: {result['text']}")
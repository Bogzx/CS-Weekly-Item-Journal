import cv2
import numpy as np
import easyocr
from ultralytics import YOLO
import os
import tempfile

class WeeklyDropProcessor:
    def __init__(self, yolo_model_path="Models/BOX_TRAINED.pt"):
        """
        Initialize the weekly drop processor
        
        Args:
            yolo_model_path: Path to the pre-trained YOLO model
        """
        self.model = YOLO(yolo_model_path)
        # Initialize EasyOCR reader
        self.reader = easyocr.Reader(['en'])  # English language
        
    def process_image(self, image_path, save_crops=False, output_dir=None):
        """
        Process an image containing weekly drops
        
        Args:
            image_path: Path to the input image
            save_crops: Whether to save the cropped images
            output_dir: Directory to save output images (used only if save_crops=True)
            
        Returns:
            A list of detected text for each item in the weekly drop
        """
        # Create temporary output directory if saving crops but no directory specified
        if save_crops and not output_dir:
            output_dir = tempfile.mkdtemp()
        
        # Create output directory if needed
        if save_crops and not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        # Read the image
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError(f"Could not read image at {image_path}")
            
        # Run YOLO detection to get the main bounding box
        results = self.model(image)
        
        # Extract the bounding box coordinates 
        if len(results[0].boxes) == 0:
            print("No bounding box detected in the image. Trying to process the full image.")
            # If no box is detected, use the full image
            main_crop = image
        else:
            # Get the first box (main box containing all 4 weekly drops)
            main_box = results[0].boxes[0].xyxy.cpu().numpy()[0]
            x1, y1, x2, y2 = map(int, main_box)
            
            # Crop the main box
            main_crop = image[y1:y2, x1:x2]
        
        # Save the main crop if requested
        if save_crops:
            main_crop_path = os.path.join(output_dir, "main_crop.jpg")
            cv2.imwrite(main_crop_path, main_crop)
        
        # Get dimensions of the main crop
        height, width = main_crop.shape[:2]
        
        # Calculate dimensions for each of the 4 boxes
        # Using a 1x4 grid layout (4 columns)
        box_width = width // 4
        box_height = height
        
        detected_texts = []
        
        # Crop into 4 boxes (columns)
        for col in range(4):
            # Calculate coordinates for this crop
            crop_x1 = col * box_width
            crop_y1 = 0
            crop_x2 = crop_x1 + box_width
            crop_y2 = crop_y1 + box_height
            
            # Extract the crop
            crop = main_crop[crop_y1:crop_y2, crop_x1:crop_x2]
            
            # Save the crop if requested
            if save_crops:
                crop_filename = f"crop_{col}.jpg"
                crop_path = os.path.join(output_dir, crop_filename)
                cv2.imwrite(crop_path, crop)
            
            # Only use the lower half for text detection
            crop_height = crop.shape[0]
            lower_half = crop[crop_height//2:, :]
            
            # Save the lower half for inspection if requested
            if save_crops:
                lower_half_path = os.path.join(output_dir, f"lower_half_{col}.jpg")
                cv2.imwrite(lower_half_path, lower_half)
            
            # Use EasyOCR for text detection on the lower half
            results_ocr = self.reader.readtext(lower_half)
            
            # Extract text from OCR results
            text = " ".join([result[1] for result in results_ocr])
            detected_texts.append(text.strip())
            
            # Save the text to a file if requested
            if save_crops:
                text_path = os.path.join(output_dir, f"text_{col}.txt")
                with open(text_path, 'w') as f:
                    f.write(text)
        
        return detected_texts

def main():
    # Get command line arguments if any
    import argparse
    parser = argparse.ArgumentParser(description='Process CS2 weekly drop images')
    parser.add_argument('image_path', type=str, help='Path to the input image')
    parser.add_argument('--model', type=str, default="Models/BOX_TRAINED.pt", help='Path to the YOLO model')
    parser.add_argument('--save-crops', action='store_true', help='Save cropped images')
    parser.add_argument('--output-dir', type=str, default="output", help='Output directory for crops')
    args = parser.parse_args()
    
    # Initialize the processor
    processor = WeeklyDropProcessor(args.model)
    
    # Process an image
    detected_texts = processor.process_image(args.image_path, args.save_crops, args.output_dir)
    
    # Print the detected text for each box
    for i, text in enumerate(detected_texts):
        print(f"Box {i+1}: {text}")

if __name__ == "__main__":
    main()
import cv2
import numpy as np
import easyocr
from ultralytics import YOLO
import os
import tempfile

# Minimum YOLO confidence for a box to count as the weekly-drop panel.
# Previously no threshold was passed at all, so ultralytics' permissive default
# let near-noise detections through and they were treated as a real panel.
DEFAULT_CONFIDENCE = 0.4


class DetectionError(RuntimeError):
    """Raised when the weekly-drop panel cannot be located in a screenshot.

    This exists so an undetectable image fails loudly. The previous behaviour
    was to silently fall back to slicing the *entire* screenshot into quarters,
    which always produced four plausible-looking strings of unrelated UI text
    and then fuzzy-matched them against the item database. The user got four
    confident, wrong item names with no indication anything had gone wrong.
    """


class WeeklyDropProcessor:
    def __init__(self, yolo_model_path="Models/BOX_TRAINED.pt",
                 confidence=DEFAULT_CONFIDENCE):
        """
        Initialize the weekly drop processor

        Args:
            yolo_model_path: Path to the pre-trained YOLO model
            confidence: Minimum detection confidence for the drop panel box
        """
        self.model = YOLO(yolo_model_path)
        self.confidence = confidence
        # Initialize EasyOCR reader
        self.reader = easyocr.Reader(['en'])  # English language

    def process_image(self, image_path, save_crops=False, output_dir=None,
                      allow_full_image_fallback=False):
        """
        Process an image containing weekly drops

        Args:
            image_path: Path to the input image
            save_crops: Whether to save the cropped images
            output_dir: Directory to save output images (used only if save_crops=True)
            allow_full_image_fallback: If the panel is not found, slice the whole
                image instead of raising. Off by default -- see DetectionError.

        Returns:
            A list of detected text for each item in the weekly drop

        Raises:
            ValueError: the image could not be read
            DetectionError: no drop panel was found above the confidence threshold
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
        results = self.model(image, conf=self.confidence, verbose=False)

        # Extract the bounding box coordinates
        boxes = results[0].boxes
        if len(boxes) == 0:
            if not allow_full_image_fallback:
                raise DetectionError(
                    f"No weekly-drop panel found in {os.path.basename(image_path)} "
                    f"at confidence >= {self.confidence}. Make sure the screenshot "
                    f"shows the full CS2 weekly care package screen."
                )
            print("No bounding box detected in the image. Trying to process the full image.")
            # If no box is detected, use the full image
            main_crop = image
        else:
            # Take the highest-confidence box, not simply the first one that
            # happened to come back. On busy screenshots the model can emit
            # several candidates and their order is not a ranking.
            confidences = boxes.conf.cpu().numpy()
            best_index = int(confidences.argmax())
            main_box = boxes[best_index].xyxy.cpu().numpy()[0]
            x1, y1, x2, y2 = map(int, main_box)

            # Crop the main box
            main_crop = image[y1:y2, x1:x2]

        if main_crop.size == 0:
            raise DetectionError(
                f"Detected panel in {os.path.basename(image_path)} is empty after cropping."
            )
        
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
            
            # First split the crop into upper and lower halves
            crop_height = crop.shape[0]
            
            # Extract the lower half
            lower_half = crop[crop_height//2:, :]
            
            # Now take only the upper portion of the lower half (where item names typically appear)
            lower_half_height = lower_half.shape[0]
            target_region = lower_half[:lower_half_height//2, :]  # Upper half of the lower half
            
            # Save the cropped regions for inspection if requested
            if save_crops:
                lower_half_path = os.path.join(output_dir, f"lower_half_{col}.jpg")
                cv2.imwrite(lower_half_path, lower_half)
                
                target_region_path = os.path.join(output_dir, f"target_region_{col}.jpg")
                cv2.imwrite(target_region_path, target_region)
            
            # Use EasyOCR for text detection on the target region
            results_ocr = self.reader.readtext(target_region)
            
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
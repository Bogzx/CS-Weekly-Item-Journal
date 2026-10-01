import os
import tempfile
from difflib import SequenceMatcher

# Both must be set before ultralytics is first imported; it reads them once.
#
# YOLO_AUTOINSTALL: importing ultralytics replaces PIL.Image.open with a
# wrapper that, whenever Pillow cannot open a file, runs
# check_requirements("pi-heif"). With the default (on) that is a
# `pip install pi-heif` inside the web process, triggered by any rejected
# upload. The app never needs HEIF (see ALLOWED_IMAGE_FORMATS in app.py).
#
# YOLO_OFFLINE: the model is a local file, so ultralytics has nothing to fetch.
# Offline also stops its anonymous usage analytics, which it otherwise sends
# on every prediction, i.e. on every upload.
os.environ.setdefault("YOLO_AUTOINSTALL", "false")
os.environ.setdefault("YOLO_OFFLINE", "true")

import cv2  # noqa: E402
import easyocr  # noqa: E402
from ultralytics import YOLO  # noqa: E402

# Minimum YOLO confidence for a box to count as the weekly-drop panel.
# Previously no threshold was passed at all, so ultralytics' permissive default
# let near-noise detections through and they were treated as a real panel.
DEFAULT_CONFIDENCE = 0.4

# Vertical band of each card, as fractions of the detected panel's height,
# that holds the item name. The name starts ~69% down and a second line (a
# graffiti's colour, or a long name) ends ~80% down; "Free" sits at ~92%.
# The band used to be 50%-75%, which cut the second line in half, so graffiti
# colours were never read. Tuned on the labelled Training_Images with
# tools/ocr_accuracy.py (see the review report for the numbers).
TEXT_BAND = (0.62, 0.86)

# EasyOCR reads text best at roughly 20-40 px cap height. Screenshots from
# video thumbnails or shrunken uploads have 8-10 px text, so a text band
# shorter than this many pixels is upscaled before OCR (at most MAX_UPSCALE x).
MIN_TEXT_BAND_HEIGHT = 120
MAX_UPSCALE = 4.0

# UI text that shares the band with item names: the case slot's "Requires a
# purchased key to open" box, and "Free" on some layouts. OCR garbles it
# ("Requlres a purchascd", "Kcy to opcn"), so a line is dropped when most of
# its words fuzzy-match these words, not only on an exact phrase.
UI_WORDS = ('requires', 'purchased', 'key', 'to', 'open', 'free', 'a')
UI_LINE_SHARE = 0.6


def _is_ui_word(word):
    word = word.lower().strip('!.,:;|')
    if len(word) <= 2:
        return word in UI_WORDS
    # Short words need a close match ("kcy"/"key"); long ones tolerate more
    # OCR damage but must not swallow real names ("operation" vs "open").
    threshold = 0.6 if len(word) <= 4 else 0.7
    return any(SequenceMatcher(None, word, ui).ratio() >= threshold
               for ui in UI_WORDS if len(ui) > 2 and abs(len(ui) - len(word)) <= 3)


def is_ui_text(line):
    """True if an OCR line is (mostly) card UI text rather than an item name.

    A single word only counts when it is exactly "Free": one-word fragments
    such as "Fire" or "Reef" are parts of real item names.
    """
    words = line.split()
    if not words:
        return True
    if len(words) == 1:
        return words[0].lower().strip('!.,:;') == 'free'
    return sum(_is_ui_word(word) for word in words) / len(words) >= UI_LINE_SHARE


def _ends_like_case(line):
    """The first line names a case ("Revolution Case", OCR'd as "Cose"/"Caso")."""
    words = line.split()
    return bool(words) and SequenceMatcher(None, words[-1].lower(), 'case').ratio() >= 0.5


class DetectionError(RuntimeError):
    """Raised when the weekly-drop panel cannot be located in a screenshot.

    This exists so an undetectable image fails loudly. The previous behaviour
    was to silently fall back to slicing the *entire* screenshot into quarters,
    which always produced four plausible-looking strings of unrelated UI text
    and then fuzzy-matched them against the item database. The user got four
    confident, wrong item names with no indication anything had gone wrong.
    """


def join_fragments(results_ocr):
    """Join EasyOCR fragments into one line of text in reading order.

    Fragments are grouped into lines top-to-bottom and read left-to-right.
    UI lines (see is_ui_text) are dropped, and on a case card everything
    under the name is dropped: that is where "Requires a purchased key to
    open" sits, and any garbled remainder of it would only confuse matching.
    """
    fragments = []
    for box, text, _confidence in results_ocr:
        ys = [point[1] for point in box]
        xs = [point[0] for point in box]
        fragments.append((min(ys), max(ys), min(xs), text))
    if not fragments:
        return ''

    # Group into lines: a fragment whose top lies above the middle of the
    # current line's first fragment belongs to that line.
    fragments.sort()
    lines = []
    for top, bottom, left, text in fragments:
        if lines and top < lines[-1]['mid']:
            lines[-1]['parts'].append((left, text))
        else:
            lines.append({'mid': (top + bottom) / 2, 'parts': [(left, text)]})

    texts = [" ".join(text for _left, text in sorted(line['parts'])).strip() for line in lines]
    texts = [text for text in texts if text and not is_ui_text(text)]
    if texts and _ends_like_case(texts[0]):
        texts = texts[:1]
    return " ".join(texts).strip()


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
        self.text_band = TEXT_BAND
        self.min_text_band_height = MIN_TEXT_BAND_HEIGHT
        self.max_upscale = MAX_UPSCALE
        # Initialize EasyOCR reader
        self.reader = easyocr.Reader(['en'])  # English language

    def _upscale(self, region):
        """Enlarge a short text band so EasyOCR sees legible glyphs."""
        height = region.shape[0]
        if height == 0 or height >= self.min_text_band_height:
            return region
        scale = min(self.min_text_band_height / height, self.max_upscale)
        return cv2.resize(region, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

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
            
            # The item-name band of this card
            crop_height = crop.shape[0]
            top, bottom = self.text_band
            target_region = crop[int(crop_height * top):int(crop_height * bottom), :]
            target_region = self._upscale(target_region)
            
            # Save the cropped region for inspection if requested
            if save_crops:
                target_region_path = os.path.join(output_dir, f"target_region_{col}.jpg")
                cv2.imwrite(target_region_path, target_region)
            
            # Use EasyOCR for text detection on the target region
            results_ocr = self.reader.readtext(target_region)
            
            # Extract text from OCR results
            text = join_fragments(results_ocr)
            detected_texts.append(text)
            
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
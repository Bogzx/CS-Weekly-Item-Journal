"""
render_pipeline.py

Draw what the recognition pipeline does to one screenshot, stage by stage,
into a single PNG (docs/pipeline.png in the README).

  1. the screenshot, with the panel box the YOLO model found
  2. the panel split into four cards, with the name band of each
  3. per card: the band EasyOCR reads, the text it returned and, with --db,
     the item the app matched and the confidence it showed

Every number in the figure comes from running the real pipeline
(WeeklyDropProcessor and app.match_items_in_database); nothing is typed in.

Usage (from the repository root):
    python tools/render_pipeline.py
    python tools/render_pipeline.py Training_Images/image.png --db csgo_items.db --out docs/pipeline.png
"""

import argparse
import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

WIDTH = 1600
MARGIN = 24
BACKGROUND = (24, 26, 31)
TEXT = (235, 235, 235)
MUTED = (150, 155, 165)
PANEL_BOX = (230, 57, 70)
SPLIT_LINE = (255, 214, 10)
BAND_BOX = (72, 202, 228)
WEARS = ('Factory New', 'Minimal Wear', 'Field-Tested', 'Well-Worn', 'Battle-Scarred')
CONFIDENCE_COLOURS = {'high': (82, 196, 108), 'medium': (255, 193, 7), 'low': (230, 57, 70)}


def font(size, bold=False):
    from PIL import ImageFont

    for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSans{}.ttf'.format('-Bold' if bold else ''),
                 'C:/Windows/Fonts/{}.ttf'.format('arialbd' if bold else 'arial')):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def fit(image, width):
    """Resize a PIL image to `width`, keeping its aspect ratio."""
    return image.resize((width, max(1, round(image.height * width / image.width))))


def wrap(draw, text, face, width):
    """Greedy word wrap to `width` pixels."""
    lines, line = [], ''
    for word in text.split():
        candidate = f'{line} {word}'.strip()
        if line and draw.textlength(candidate, font=face) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    return lines + [line] if line else lines or ['']


def run_pipeline(image_path, db_path=None):
    """Panel box, card crops, band crops, OCR texts and (optionally) matches."""
    from PIL import Image

    from Src.ImageDetector.modified_detect_text import WeeklyDropProcessor

    processor = WeeklyDropProcessor(os.path.join(REPO_ROOT, 'Models', 'BOX_TRAINED.pt'))
    with tempfile.TemporaryDirectory() as out_dir:
        texts = processor.process_image(image_path, save_crops=True, output_dir=out_dir)
        bands = [Image.open(os.path.join(out_dir, f'target_region_{i}.jpg')).convert('RGB') for i in range(4)]
        for band in bands:
            band.load()

    # The same detection call process_image() makes, for the box coordinates.
    boxes = processor.model(image_path, conf=processor.confidence, verbose=False)[0].boxes
    best = int(boxes.conf.cpu().numpy().argmax())
    box = [int(v) for v in boxes[best].xyxy.cpu().numpy()[0]]
    confidence = float(boxes.conf[best])

    matches = None
    if db_path:
        os.environ['DATABASE_PATH'] = os.path.abspath(db_path)
        os.environ.setdefault('SECRET_KEY', 'render-pipeline-not-a-real-key')
        import app
        matches = app.match_items_in_database(texts)
    return {'box': box, 'confidence': confidence, 'bands': bands, 'texts': texts,
            'matches': matches, 'text_band': processor.text_band}


def render(image_path, result, out_path):
    from PIL import Image, ImageDraw

    screenshot = Image.open(image_path).convert('RGB')
    x1, y1, x2, y2 = result['box']
    title_face, body_face, small_face = font(30, bold=True), font(22), font(19)
    column = (WIDTH - 5 * MARGIN) // 4

    # Stage 1: screenshot with the detected box, left; stage 2: the panel, right.
    shot = screenshot.copy()
    draw = ImageDraw.Draw(shot)
    stroke = max(3, shot.width // 300)
    draw.rectangle(result['box'], outline=PANEL_BOX, width=stroke)
    half = (WIDTH - 3 * MARGIN) // 2
    shot = fit(shot, half)

    panel = screenshot.crop(result['box'])
    draw = ImageDraw.Draw(panel)
    card_width = panel.width // 4
    top, bottom = result['text_band']
    line = max(2, panel.width // 400)
    for col in range(4):
        left = col * card_width
        if col:
            draw.line([(left, 0), (left, panel.height)], fill=SPLIT_LINE, width=line)
        draw.rectangle([left + line, int(panel.height * top), left + card_width - line,
                        int(panel.height * bottom)], outline=BAND_BOX, width=line)
    panel = fit(panel, half)

    stage_height = max(shot.height, panel.height)
    bands = [fit(band, column) for band in result['bands']]
    band_height = max(band.height for band in bands)

    canvas = Image.new('RGB', (WIDTH, 2000), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    y = MARGIN
    draw.text((MARGIN, y), '1. YOLO11s finds the card strip', font=title_face, fill=TEXT)
    draw.text((2 * MARGIN + half, y), '2. Split into 4 cards; read the name band', font=title_face, fill=TEXT)
    y += 46
    draw.text((MARGIN, y), f'panel box, confidence {result["confidence"]:.2f}', font=small_face, fill=MUTED)
    draw.text((2 * MARGIN + half, y),
              f'equal columns; band = {top:.0%} to {bottom:.0%} of the card height', font=small_face, fill=MUTED)
    y += 32
    canvas.paste(shot, (MARGIN, y))
    canvas.paste(panel, (2 * MARGIN + half, y))
    y += stage_height + MARGIN

    heading = '3. EasyOCR reads each band; the app matches it against the item database'
    if result['matches'] is None:
        heading = '3. EasyOCR reads each band'
    draw.text((MARGIN, y), heading, font=title_face, fill=TEXT)
    y += 50
    bottom_y = y
    for col, band in enumerate(bands):
        x = MARGIN + col * (column + MARGIN)
        canvas.paste(band, (x, y))
        cy = y + band_height + 12
        draw.text((x, cy), 'OCR text', font=small_face, fill=MUTED)
        cy += 26
        for text_line in wrap(draw, result['texts'][col] or '(nothing read)', body_face, column):
            draw.text((x, cy), text_line, font=body_face, fill=TEXT)
            cy += 28
        if result['matches'] is not None:
            cy += 10
            draw.text((x, cy), 'Matched item', font=small_face, fill=MUTED)
            cy += 26
            candidates = result['matches'][col].get('matches') or []
            if candidates:
                top_match = candidates[0]
                # The care-package screen never shows a skin's wear, so the
                # app values every wear of the matched skin (README "How items
                # are valued"); name the skin, not one arbitrary wear.
                name = top_match['name']
                wear = next((w for w in WEARS if name.endswith(f' ({w})')), None)
                if wear:
                    name = name[:-len(wear) - 3]
                for text_line in wrap(draw, name, body_face, column):
                    draw.text((x, cy), text_line, font=body_face, fill=TEXT)
                    cy += 28
                if wear:
                    draw.text((x, cy), 'wear not shown: valued over all wears', font=small_face, fill=MUTED)
                    cy += 26
                tier = top_match.get('confidence') or 'low'
                draw.text((x, cy + 4), f'{tier} confidence', font=small_face,
                          fill=CONFIDENCE_COLOURS.get(tier, MUTED))
                cy += 32
            else:
                draw.text((x, cy), 'no match', font=body_face, fill=PANEL_BOX)
                cy += 28
        bottom_y = max(bottom_y, cy)

    canvas = canvas.crop((0, 0, WIDTH, bottom_y + MARGIN))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    canvas.save(out_path, optimize=True)
    return canvas.size


def main(argv=None):
    parser = argparse.ArgumentParser(description='Render the pipeline stages for one screenshot')
    parser.add_argument('image', nargs='?', default=os.path.join(REPO_ROOT, 'Training_Images', 'image.png'))
    parser.add_argument('--db', help='Built item database; adds the matched items')
    parser.add_argument('--out', default=os.path.join(REPO_ROOT, 'docs', 'pipeline.png'))
    args = parser.parse_args(argv)

    result = run_pipeline(args.image, args.db)
    size = render(args.image, result, args.out)
    print(f'Wrote {args.out} ({size[0]}x{size[1]})')
    for col, text in enumerate(result['texts']):
        print(f'  card {col + 1}: {text!r}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

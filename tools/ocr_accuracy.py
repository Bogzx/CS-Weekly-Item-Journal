"""
ocr_accuracy.py

Measure the vision pipeline against the hand-labelled Training_Images.

For every scored slot in tests/fixtures/expected_names.json it runs the real
YOLO + EasyOCR pipeline (Src/ImageDetector/modified_detect_text.py) and
reports:

- exact:     the OCR text equals the label (case, spacing and bracket style
             ignored: the UI's "(" often comes back as "[" or "{")
- fuzzy:     character similarity to the label >= FUZZY_THRESHOLD
- similarity: mean character similarity (0-1), a smoother signal for tuning

With --db (a built item database) it also runs the app's own matching
(app.match_items_in_database) and reports how often the top candidate is the
right item, and, for graffiti, the right colour too.

Usage (from the repository root):
    python tools/ocr_accuracy.py
    python tools/ocr_accuracy.py --db csgo_items.db --json out.json
    python tools/ocr_accuracy.py --only image.png maxres2.jpg -v

Slow: the first run downloads EasyOCR weights; after that ~1-3 s per image on
CPU.
"""

import argparse
import json
import os
import re
import sys
import time
from difflib import SequenceMatcher

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

LABELS = os.path.join(REPO_ROOT, 'tests', 'fixtures', 'expected_names.json')
IMAGES = os.path.join(REPO_ROOT, 'Training_Images')
FUZZY_THRESHOLD = 0.9
WEARS = ("Factory New", "Minimal Wear", "Field-Tested", "Well-Worn", "Battle-Scarred")


def normalise(text):
    """Compare texts the way a reader would: case, spacing and bracket style ignored."""
    text = (text or '').lower()
    text = text.translate(str.maketrans('[{]}', '(())'))
    text = re.sub(r'\s*\|\s*', ' | ', text)
    text = re.sub(r'\s*\(\s*', ' (', text)
    text = re.sub(r'\s*\)\s*', ')', text)
    return re.sub(r'\s+', ' ', text).strip()


def similarity(a, b):
    return SequenceMatcher(None, normalise(a), normalise(b)).ratio()


def item_identity(name):
    """The item without a skin wear or graffiti colour: what the app can know."""
    name = name or ''
    for wear in WEARS:
        if name.endswith(f' ({wear})'):
            return name[:-len(wear) - 3]
    if name.startswith('Sealed Graffiti | '):
        return re.sub(r'\s*\([^()]*\)$', '', name)
    return name


def load_labels(only=None):
    with open(LABELS, encoding='utf-8') as f:
        images = json.load(f)['images']
    selected = []
    for file_name, entry in sorted(images.items()):
        if only and file_name not in only:
            continue
        if entry.get('duplicate_of') or entry.get('slots') is None:
            continue
        selected.append((file_name, entry))
    return selected


def slot_is_scored(entry, slot):
    return entry.get('scored', True) and 'shown' not in slot


def load_matcher(db_path):
    """Import app.py against `db_path` and return its match function."""
    os.environ['DATABASE_PATH'] = os.path.abspath(db_path)
    os.environ.setdefault('SECRET_KEY', 'ocr-accuracy-not-a-real-key')
    import app  # noqa: E402  (needs DATABASE_PATH set first)
    return app.match_items_in_database


def evaluate(processor, labels, match=None, verbose=False):
    rows = []
    for file_name, entry in labels:
        started = time.time()
        try:
            texts = processor.process_image(os.path.join(IMAGES, file_name), save_crops=False)
            error = None
        except Exception as e:  # DetectionError, unreadable image, ...
            texts, error = [''] * 4, f'{e.__class__.__name__}: {e}'
        elapsed = time.time() - started
        matched = match(texts) if match else None

        for index, slot in enumerate(entry['slots']):
            text = texts[index] if index < len(texts) else ''
            row = {
                'image': file_name,
                'slot': index,
                'expected': slot['name'],
                'ocr': text,
                'scored': slot_is_scored(entry, slot),
                'exact': normalise(text) == normalise(slot['name']),
                'similarity': round(similarity(text, slot['name']), 3),
                'error': error,
                'seconds': round(elapsed, 2),
            }
            row['fuzzy'] = row['similarity'] >= FUZZY_THRESHOLD
            if matched is not None:
                result = matched[index] if index < len(matched) else {}
                candidates = result.get('matches') or []
                top = candidates[0]['name'] if candidates else None
                row['matched'] = top
                row['match_status'] = result.get('status')
                row['match_confidence'] = candidates[0].get('confidence') if candidates else None
                row['match_score'] = candidates[0].get('score') if candidates else None
                row['item_ok'] = top is not None and item_identity(top) == item_identity(slot['name'])
                row['exact_item_ok'] = top == slot['name'] or (
                    # Skins: the app cannot know the wear; the right skin is the whole answer.
                    top is not None and not slot['name'].startswith('Sealed Graffiti')
                    and item_identity(top) == slot['name'])
            rows.append(row)
            if verbose:
                flag = 'OK ' if row['exact'] else ('~  ' if row['fuzzy'] else 'XX ')
                extra = f"  -> {row.get('matched')}" if match else ''
                print(f"{flag}{file_name[:28]:28} [{index}] {row['similarity']:.2f} "
                      f"{text!r} (want {slot['name']!r}){extra}"
                      + ('' if row['scored'] else '  [not scored]'))
    return rows


def summarise(rows):
    scored = [r for r in rows if r['scored']]
    n = len(scored) or 1
    summary = {
        'slots_scored': len(scored),
        'images': len({r['image'] for r in scored}),
        'exact': sum(r['exact'] for r in scored),
        'fuzzy': sum(r['fuzzy'] for r in scored),
        'mean_similarity': round(sum(r['similarity'] for r in scored) / n, 4),
        'panel_not_found': len({r['image'] for r in scored if r['error']}),
    }
    if scored and 'item_ok' in scored[0]:
        summary['item_ok'] = sum(r['item_ok'] for r in scored)
        summary['exact_item_ok'] = sum(r['exact_item_ok'] for r in scored)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description='OCR accuracy over the labelled Training_Images')
    parser.add_argument('--db', help='Built item database; adds item-match accuracy')
    parser.add_argument('--only', nargs='+', help='Only these image file names')
    parser.add_argument('--json', help='Write every slot result and the summary to this file')
    parser.add_argument('-v', '--verbose', action='store_true', help='Print every slot')
    args = parser.parse_args(argv)

    from Src.ImageDetector.modified_detect_text import WeeklyDropProcessor

    labels = load_labels(set(args.only) if args.only else None)
    match = load_matcher(args.db) if args.db else None
    processor = WeeklyDropProcessor(os.path.join(REPO_ROOT, 'Models', 'BOX_TRAINED.pt'))
    rows = evaluate(processor, labels, match, verbose=args.verbose)
    summary = summarise(rows)

    n = summary['slots_scored'] or 1
    print(f"\nScored slots: {summary['slots_scored']} over {summary['images']} images "
          f"(panel not found in {summary['panel_not_found']})")
    print(f"  exact OCR:        {summary['exact']:3d}  ({summary['exact'] / n:.1%})")
    print(f"  fuzzy OCR >= {FUZZY_THRESHOLD}: {summary['fuzzy']:3d}  ({summary['fuzzy'] / n:.1%})")
    print(f"  mean similarity:  {summary['mean_similarity']:.3f}")
    if 'item_ok' in summary:
        print(f"  right item:       {summary['item_ok']:3d}  ({summary['item_ok'] / n:.1%})")
        print(f"  right item+colour:{summary['exact_item_ok']:4d}  ({summary['exact_item_ok'] / n:.1%})")

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump({'summary': summary, 'slots': rows}, f, indent=1, ensure_ascii=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())

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
right item, and, for graffiti, the right colour too. It then breaks that down
by item type and by the confidence the app showed, which is what a user sees:
how often a "high" or "medium" match is right, and how many slots get one.

Every rate comes with a 95% interval: Wilson over slots, and a bootstrap over
images (slots in one screenshot share its resolution and blur, so they are not
independent; the image bootstrap is the more honest of the two).

Splits: each labelled image has a "split". "dev" is every image in
Training_Images/: the panel detector was trained on them and the text band,
UI filter and confidence thresholds were tuned on them, so dev numbers are
in-sample. "test" is for screenshots never used for training or tuning; there
are none yet (see README "Accuracy").

Usage (from the repository root):
    python tools/ocr_accuracy.py
    python tools/ocr_accuracy.py --db csgo_items.db --json out.json
    python tools/ocr_accuracy.py --split test --db csgo_items.db
    python tools/ocr_accuracy.py --only image.png maxres2.jpg -v

Slow: the first run downloads EasyOCR weights; after that ~1-3 s per image on
CPU.
"""

import argparse
import hashlib
import json
import math
import os
import platform
import random
import re
import sys
import time
from difflib import SequenceMatcher

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

LABELS = os.path.join(REPO_ROOT, 'tests', 'fixtures', 'expected_names.json')
IMAGES = os.path.join(REPO_ROOT, 'Training_Images')
MODEL = os.path.join(REPO_ROOT, 'Models', 'BOX_TRAINED.pt')
FUZZY_THRESHOLD = 0.9
SPLITS = ('dev', 'test')
CONFIDENCE_TIERS = ('high', 'medium', 'low', None)
BOOTSTRAP_ROUNDS = 2000
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


def item_type(name):
    """'graffiti', 'skin' or 'case/other' (cases, capsules, the charm pack)."""
    if name.startswith('Sealed Graffiti | '):
        return 'graffiti'
    return 'skin' if ' | ' in name else 'case/other'


def load_labels(only=None, split=None):
    """(file name, entry) for every labelled image, optionally one split only."""
    with open(LABELS, encoding='utf-8') as f:
        images = json.load(f)['images']
    selected = []
    for file_name, entry in sorted(images.items()):
        if only and file_name not in only:
            continue
        if split and entry.get('split') != split:
            continue
        if entry.get('duplicate_of') or entry.get('slots') is None:
            continue
        selected.append((file_name, entry))
    return selected


def image_path(file_name, entry):
    """Images live in Training_Images/ unless the label names another directory."""
    return os.path.join(REPO_ROOT, entry['dir'], file_name) if 'dir' in entry \
        else os.path.join(IMAGES, file_name)


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
            texts = processor.process_image(image_path(file_name, entry), save_crops=False)
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
                'type': item_type(slot['name']),
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


def wilson(successes, n, z=1.96):
    """95% Wilson score interval for a proportion, as (low, high)."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def image_bootstrap(rows, key, rounds=BOOTSTRAP_ROUNDS, seed=0):
    """95% interval for the slot rate of `key`, resampling whole images."""
    by_image = {}
    for row in rows:
        by_image.setdefault(row['image'], []).append(row[key])
    images = list(by_image.values())
    if not images:
        return (0.0, 0.0)
    rng = random.Random(seed)
    rates = []
    for _ in range(rounds):
        sample = [rng.choice(images) for _ in images]
        slots = sum(len(slot_flags) for slot_flags in sample)
        rates.append(sum(sum(slot_flags) for slot_flags in sample) / slots)
    rates.sort()
    return (rates[int(0.025 * rounds)], rates[int(0.975 * rounds) - 1])


def rate(rows, key):
    """Count, share and both 95% intervals of the slots where `key` is true."""
    n = len(rows)
    hits = sum(bool(r[key]) for r in rows)
    return {'hits': hits, 'n': n, 'rate': round(hits / n, 4) if n else 0.0,
            'wilson95': [round(v, 4) for v in wilson(hits, n)],
            'image_bootstrap95': [round(v, 4) for v in image_bootstrap(rows, key)]}


def by_type(rows, key):
    return {kind: rate([r for r in rows if r['type'] == kind], key)
            for kind in ('case/other', 'skin', 'graffiti')}


def by_confidence(rows):
    """Per confidence tier: slots, how many were the right item, and the
    running coverage and precision if the app only trusted tiers this high."""
    table, covered, right = [], 0, 0
    total = len(rows) or 1
    for tier in CONFIDENCE_TIERS:
        tier_rows = [r for r in rows if r.get('match_confidence') == tier]
        tier_right = sum(r['item_ok'] for r in tier_rows)
        covered += len(tier_rows)
        right += tier_right
        table.append({'tier': tier or 'no match', 'slots': len(tier_rows), 'right': tier_right,
                      'coverage_so_far': round(covered / total, 4),
                      'precision_so_far': round(right / covered, 4) if covered else None})
    return table


def environment(db_path=None):
    """What produced the numbers: library versions, model hash, item count."""
    import cv2
    import easyocr
    import torch
    import ultralytics

    with open(MODEL, 'rb') as f:
        model_sha256 = hashlib.sha256(f.read()).hexdigest()
    env = {'python': platform.python_version(), 'platform': platform.machine(),
           'torch': torch.__version__, 'ultralytics': ultralytics.__version__,
           'easyocr': easyocr.__version__, 'opencv': cv2.__version__,
           'model_sha256': model_sha256}
    if db_path:
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            env['db_items'] = conn.execute('SELECT COUNT(*) FROM items').fetchone()[0]
    return env


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


def report(rows):
    """Rates with intervals, per type and per confidence tier (scored slots)."""
    scored = [r for r in rows if r['scored']]
    keys = ['exact', 'fuzzy'] + (['item_ok', 'exact_item_ok'] if scored and 'item_ok' in scored[0] else [])
    result = {'rates': {key: rate(scored, key) for key in keys},
              'by_type': by_type(scored, 'item_ok' if 'item_ok' in keys else 'fuzzy')}
    if 'item_ok' in keys:
        result['by_confidence'] = by_confidence(scored)
    return result


def _fmt(entry):
    low, high = entry['wilson95']
    blow, bhigh = entry['image_bootstrap95']
    return (f"{entry['hits']:3d}/{entry['n']:<3d} {entry['rate']:6.1%}   "
            f"Wilson {low:.0%}-{high:.0%}, image bootstrap {blow:.0%}-{bhigh:.0%}")


def main(argv=None):
    parser = argparse.ArgumentParser(description='OCR accuracy over the labelled screenshots')
    parser.add_argument('--db', help='Built item database; adds item-match accuracy')
    parser.add_argument('--split', choices=SPLITS + ('all',), default='dev',
                        help='dev: the Training_Images (in-sample); test: held-out screenshots')
    parser.add_argument('--only', nargs='+', help='Only these image file names')
    parser.add_argument('--json', help='Write every slot result and the summary to this file')
    parser.add_argument('-v', '--verbose', action='store_true', help='Print every slot')
    args = parser.parse_args(argv)

    labels = load_labels(set(args.only) if args.only else None,
                         None if args.split == 'all' else args.split)
    if not labels:
        print(f"No labelled images in split {args.split!r}. Held-out screenshots go in "
              f"tests/fixtures/expected_names.json with \"split\": \"test\" (README \"Accuracy\").")
        return 1

    from Src.ImageDetector.modified_detect_text import WeeklyDropProcessor

    match = load_matcher(args.db) if args.db else None
    processor = WeeklyDropProcessor(MODEL)
    rows = evaluate(processor, labels, match, verbose=args.verbose)
    summary = summarise(rows)
    details = report(rows)
    env = environment(args.db)

    print(f"\nSplit {args.split}: {summary['slots_scored']} scored slots over {summary['images']} images "
          f"(panel not found in {summary['panel_not_found']})")
    print(f"  exact OCR:          {_fmt(details['rates']['exact'])}")
    print(f"  fuzzy OCR >= {FUZZY_THRESHOLD}:   {_fmt(details['rates']['fuzzy'])}")
    print(f"  mean similarity:    {summary['mean_similarity']:.3f}")
    if 'item_ok' in details['rates']:
        print(f"  right item:         {_fmt(details['rates']['item_ok'])}")
        print(f"  right item+colour:  {_fmt(details['rates']['exact_item_ok'])}")
        print("\n  Right item by type:")
        for kind, entry in details['by_type'].items():
            print(f"    {kind:11} {entry['hits']:3d}/{entry['n']:<3d} {entry['rate']:6.1%}")
        print("\n  By the confidence the app showed (cumulative from the top tier):")
        print("    tier       slots  right   coverage  precision")
        for row in details['by_confidence']:
            precision = '-' if row['precision_so_far'] is None else f"{row['precision_so_far']:.1%}"
            print(f"    {row['tier']:9} {row['slots']:6d} {row['right']:6d}   "
                  f"{row['coverage_so_far']:8.1%}  {precision:>9}")
    print("\n  " + ", ".join(f"{k} {v}" for k, v in env.items() if k != 'model_sha256')
          + f", model sha256 {env['model_sha256'][:12]}")

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump({'split': args.split, 'environment': env, 'summary': summary,
                       'report': details, 'slots': rows}, f, indent=1, ensure_ascii=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())

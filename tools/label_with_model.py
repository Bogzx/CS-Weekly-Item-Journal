"""
label_with_model.py

Write YOLO labels for the detector's training images by running the current
model, and draw every box so a person can check it.

The labels Models/BOX_TRAINED.pt was trained on were never committed (the
training ran on Colab against /content/data.yaml). This recreates them: the
model's own panel box per image, reviewed by eye, then committed to
dataset/labels/. tools/train_detector.py trains from those files.

Each label is one line, `0 cx cy w h`, normalised to the image size: class 0
is `Box`, the strip that holds the four item cards.

Usage (from the repository root):
    python tools/label_with_model.py                       # write dataset/labels/
    python tools/label_with_model.py --review build/label-review
    python tools/label_with_model.py --legacy-labels path/to/data/labels

--legacy-labels takes the per-card "Text" boxes from the March 2025 Label
Studio export (data.zip, in git history at commit 6480440; also attached to
the model-v1 release). Every card box must lie inside the panel box; the tool
reports any that do not.
"""

import argparse
import os
import re
import sys
from urllib.parse import unquote

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import yaml  # noqa: E402  (ultralytics depends on PyYAML)

MANIFEST = os.path.join(REPO_ROOT, 'dataset', 'dataset.yaml')


def load_manifest(path=MANIFEST):
    with open(path, encoding='utf-8') as f:
        manifest = yaml.safe_load(f)
    manifest['images_dir'] = os.path.join(REPO_ROOT, manifest['images_dir'])
    manifest['labels_dir'] = os.path.join(REPO_ROOT, manifest['labels_dir'])
    return manifest


def dataset_images(manifest):
    """Every image the detector is trained or validated on, sorted."""
    excluded = set(manifest.get('exclude') or {})
    return sorted(name for name in os.listdir(manifest['images_dir'])
                  if name not in excluded and not name.startswith('.'))


def label_path(manifest, image_name):
    return os.path.join(manifest['labels_dir'], os.path.splitext(image_name)[0] + '.txt')


def to_yolo(box, width, height):
    """(x1, y1, x2, y2) in pixels -> (cx, cy, w, h) normalised."""
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2 / width, (y1 + y2) / 2 / height,
            (x2 - x1) / width, (y2 - y1) / height)


def from_yolo(cxcywh, width, height):
    cx, cy, w, h = cxcywh
    return ((cx - w / 2) * width, (cy - h / 2) * height,
            (cx + w / 2) * width, (cy + h / 2) * height)


def read_label(path):
    """The single `0 cx cy w h` line of a label file, as floats."""
    with open(path, encoding='utf-8') as f:
        rows = [line.split() for line in f if line.strip()]
    if len(rows) != 1 or rows[0][0] != '0' or len(rows[0]) != 5:
        raise ValueError(f'{path}: expected exactly one "0 cx cy w h" line')
    return tuple(float(v) for v in rows[0][1:])


# Training_Images/ names whose Label Studio upload had another name
# (byte-identical files).
LEGACY_ALIASES = {'test': 'weekly-care-package-v0-kezy06qv6vqb1'}


def _legacy_key(stem):
    """Label Studio's form of a file stem: URL-quoted, "_" for spaces and brackets."""
    stem = unquote(LEGACY_ALIASES.get(stem, stem))
    return re.sub(r'[\s()]+', '_', stem).strip('_')


def legacy_card_boxes(legacy_dir, image_name):
    """Card boxes from the Label Studio export whose file is `<8 hex>-<name>.txt`."""
    wanted = _legacy_key(os.path.splitext(image_name)[0])
    for name in os.listdir(legacy_dir):
        # Uploads were prefixed with one or two "<8 hex>-" or "<8 hex>__" ids.
        legacy_stem = re.sub(r'^([0-9a-f]{8}(-|__))+', '', os.path.splitext(name)[0])
        if _legacy_key(legacy_stem) == wanted:
            with open(os.path.join(legacy_dir, name), encoding='utf-8') as f:
                return [tuple(float(v) for v in line.split()[1:]) for line in f if line.strip()]
    return None


def inside(inner, outer, tolerance=0.01):
    """Normalised (cx, cy, w, h) `inner` lies within `outer`, give or take."""
    ix1, iy1, ix2, iy2 = from_yolo(inner, 1, 1)
    ox1, oy1, ox2, oy2 = from_yolo(outer, 1, 1)
    return (ix1 >= ox1 - tolerance and iy1 >= oy1 - tolerance
            and ix2 <= ox2 + tolerance and iy2 <= oy2 + tolerance)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Pseudo-label the detector dataset with the current model')
    parser.add_argument('--model', default=os.path.join(REPO_ROOT, 'Models', 'BOX_TRAINED.pt'))
    parser.add_argument('--conf', type=float, default=0.25, help='Lowest confidence to accept')
    parser.add_argument('--review', help='Directory to write images with the box drawn on them')
    parser.add_argument('--legacy-labels', help='labels/ directory of the March 2025 Label Studio export')
    parser.add_argument('--keep-existing', action='store_true',
                        help='Do not overwrite labels that already exist (hand-corrected ones)')
    args = parser.parse_args(argv)

    # Same settings the app uses: no pip installs, no analytics.
    os.environ.setdefault('YOLO_AUTOINSTALL', 'false')
    os.environ.setdefault('YOLO_OFFLINE', 'true')
    import cv2
    from ultralytics import YOLO

    manifest = load_manifest()
    os.makedirs(manifest['labels_dir'], exist_ok=True)
    if args.review:
        os.makedirs(args.review, exist_ok=True)
    model = YOLO(args.model)

    problems = 0
    for name in dataset_images(manifest):
        image = cv2.imread(os.path.join(manifest['images_dir'], name))
        if image is None:
            print(f'UNREADABLE {name}')
            problems += 1
            continue
        height, width = image.shape[:2]
        path = label_path(manifest, name)

        if args.keep_existing and os.path.exists(path):
            label, source = read_label(path), 'kept'
        else:
            boxes = model(image, conf=args.conf, verbose=False)[0].boxes
            if len(boxes) == 0:
                print(f'NO BOX     {name}: label it by hand in {os.path.relpath(path, REPO_ROOT)}')
                problems += 1
                continue
            best = int(boxes.conf.cpu().numpy().argmax())
            label = to_yolo(boxes[best].xyxy.cpu().numpy()[0].tolist(), width, height)
            source = f'model conf {float(boxes.conf[best]):.2f}'
            with open(path, 'w', encoding='utf-8') as f:
                f.write('0 ' + ' '.join(f'{v:.6f}' for v in label) + '\n')

        note = ''
        if args.legacy_labels:
            cards = legacy_card_boxes(args.legacy_labels, name)
            if cards is None:
                note = '  (no legacy label)'
            else:
                outside = [card for card in cards if not inside(card, label)]
                note = f'  legacy cards inside: {len(cards) - len(outside)}/{len(cards)}'
                if outside:
                    problems += 1
                    note += '  <-- CHECK'
        print(f'{source:16} {name}{note}')

        if args.review:
            x1, y1, x2, y2 = (int(round(v)) for v in from_yolo(label, width, height))
            thickness = max(2, width // 400)
            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), thickness)
            for col in range(1, 4):  # where process_image() splits the cards
                x = x1 + (x2 - x1) * col // 4
                cv2.line(image, (x, y1), (x, y2), (0, 255, 255), max(1, thickness // 2))
            cv2.imwrite(os.path.join(args.review, os.path.splitext(name)[0] + '.jpg'), image)

    print(f'\n{len(dataset_images(manifest))} images, {problems} to check')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())

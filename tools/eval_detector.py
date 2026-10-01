"""
eval_detector.py

Score a panel-detector checkpoint against the labels in dataset/labels/.

For every image it reports the IoU between the highest-confidence predicted
box (what process_image() uses) and the labelled box, then the mean IoU and
how many images clear IoU 0.5 and 0.9. 0.9 matters here: the app splits the
box into four equal columns and crops a fixed band of each, so a box that is
roughly right but a few percent too wide shifts every card's crop.

The labels were made with Models/BOX_TRAINED.pt itself and then checked by
eye (dataset/README.md), so that model scores ~1.0 by construction. Use this
to compare a retrained model with the shipped one, not as an accuracy claim.

Usage (from the repository root):
    python tools/eval_detector.py
    python tools/eval_detector.py --model build/detector-runs/train/weights/best.pt --split val
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from label_with_model import dataset_images, from_yolo, label_path, load_manifest, read_label  # noqa: E402


def iou(a, b):
    """Intersection over union of two (x1, y1, x2, y2) boxes."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def main(argv=None):
    parser = argparse.ArgumentParser(description='IoU of a detector checkpoint against dataset/labels')
    parser.add_argument('--model', default=os.path.join(REPO_ROOT, 'Models', 'BOX_TRAINED.pt'))
    parser.add_argument('--split', choices=('train', 'val', 'all'), default='all')
    parser.add_argument('--conf', type=float, default=0.4, help='Same default as the app')
    args = parser.parse_args(argv)

    os.environ.setdefault('YOLO_AUTOINSTALL', 'false')
    os.environ.setdefault('YOLO_OFFLINE', 'true')
    import cv2
    from ultralytics import YOLO

    manifest = load_manifest()
    val = set(manifest.get('val') or [])
    names = [n for n in dataset_images(manifest)
             if args.split == 'all' or (n in val) == (args.split == 'val')]
    model = YOLO(args.model)

    scores = []
    for name in names:
        image = cv2.imread(os.path.join(manifest['images_dir'], name))
        height, width = image.shape[:2]
        truth = from_yolo(read_label(label_path(manifest, name)), width, height)
        boxes = model(image, conf=args.conf, verbose=False)[0].boxes
        if len(boxes) == 0:
            score = 0.0
        else:
            best = int(boxes.conf.cpu().numpy().argmax())
            score = iou(boxes[best].xyxy.cpu().numpy()[0].tolist(), truth)
        scores.append(score)
        print(f"{score:5.3f}  {'val  ' if name in val else 'train'}  {name}")

    n = len(scores) or 1
    print(f'\n{len(scores)} images ({args.split}): mean IoU {sum(scores) / n:.3f}, '
          f'IoU >= 0.5: {sum(s >= 0.5 for s in scores)}, IoU >= 0.9: {sum(s >= 0.9 for s in scores)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

"""
train_detector.py

Retrain the weekly-drop panel detector (Models/BOX_TRAINED.pt) from the
committed dataset (dataset/dataset.yaml, dataset/labels/, Training_Images/).

It builds the images/ + labels/ + data.yaml layout ultralytics expects under
build/detector-dataset/ (copies, ~10 MB), then trains with the settings of the
March 2025 run that produced the shipped model (recovered from that run's
args.yaml): yolo11s.pt, 80 epochs, imgsz 1024, batch 16, seed 0,
deterministic.

Usage (from the repository root):
    python tools/train_detector.py --prepare-only        # just build the layout
    python tools/train_detector.py                       # full run
    python tools/train_detector.py --epochs 3 --batch 4  # smoke test

The first run downloads yolo11s.pt (~19 MB) from the ultralytics releases, so
it needs the network. On CPU a full run takes a while; a GPU (or Colab) is the
practical choice. The result lands in build/detector-runs/<name>/weights/.
Compare it with the shipped model before replacing anything:

    python tools/eval_detector.py --model build/detector-runs/train/weights/best.pt
    pytest -m slow
"""

import argparse
import os
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from label_with_model import dataset_images, label_path, load_manifest, read_label  # noqa: E402

BUILD_DIR = os.path.join(REPO_ROOT, 'build', 'detector-dataset')
RUNS_DIR = os.path.join(REPO_ROOT, 'build', 'detector-runs')

# From the March 2025 run's train/args.yaml (my_model.zip in git history).
ORIGINAL_ARGS = {'model': 'yolo11s.pt', 'epochs': 80, 'imgsz': 1024, 'batch': 16,
                 'seed': 0, 'deterministic': True, 'patience': 100}


def split_of(manifest, image_name):
    return 'val' if image_name in set(manifest.get('val') or []) else 'train'


def prepare(manifest=None, out_dir=BUILD_DIR):
    """Copy images and labels into `out_dir` and write its data.yaml.

    Returns the data.yaml path. Every image must have a valid label file.
    """
    import yaml

    manifest = manifest or load_manifest()
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    counts = {'train': 0, 'val': 0}
    for name in dataset_images(manifest):
        split = split_of(manifest, name)
        label = label_path(manifest, name)
        read_label(label)  # fails loudly on a missing or malformed label
        for kind, source, target_name in (
                ('images', os.path.join(manifest['images_dir'], name), name),
                ('labels', label, os.path.basename(label))):
            target_dir = os.path.join(out_dir, kind, split)
            os.makedirs(target_dir, exist_ok=True)
            shutil.copyfile(source, os.path.join(target_dir, target_name))
        counts[split] += 1

    missing_val = set(manifest.get('val') or []) - set(dataset_images(manifest))
    if missing_val:
        raise ValueError(f'val images not in the dataset: {sorted(missing_val)}')

    data_yaml = os.path.join(out_dir, 'data.yaml')
    with open(data_yaml, 'w', encoding='utf-8') as f:
        yaml.safe_dump({'path': out_dir, 'train': 'images/train', 'val': 'images/val',
                        'names': manifest['names']}, f, sort_keys=False)
    print(f"Dataset: {counts['train']} train, {counts['val']} val images -> {data_yaml}")
    return data_yaml


def main(argv=None):
    parser = argparse.ArgumentParser(description='Retrain the weekly-drop panel detector')
    parser.add_argument('--prepare-only', action='store_true', help='Build the dataset layout and stop')
    parser.add_argument('--model', default=ORIGINAL_ARGS['model'], help='Starting weights')
    parser.add_argument('--epochs', type=int, default=ORIGINAL_ARGS['epochs'])
    parser.add_argument('--imgsz', type=int, default=ORIGINAL_ARGS['imgsz'])
    parser.add_argument('--batch', type=int, default=ORIGINAL_ARGS['batch'])
    parser.add_argument('--device', default=None, help='e.g. cpu, 0 (default: ultralytics picks)')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--name', default='train', help='Run name under build/detector-runs/')
    args = parser.parse_args(argv)

    data_yaml = prepare()
    if args.prepare_only:
        return 0

    # Never pip-install anything from inside a training run either.
    os.environ.setdefault('YOLO_AUTOINSTALL', 'false')
    from ultralytics import YOLO

    model = YOLO(args.model)
    model.train(data=data_yaml, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                seed=ORIGINAL_ARGS['seed'], deterministic=ORIGINAL_ARGS['deterministic'],
                patience=ORIGINAL_ARGS['patience'], device=args.device, workers=args.workers,
                project=RUNS_DIR, name=args.name, exist_ok=True)
    print(f'Weights: {os.path.join(RUNS_DIR, args.name, "weights")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

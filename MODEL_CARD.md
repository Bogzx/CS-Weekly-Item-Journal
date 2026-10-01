# Model card: weekly-drop panel detector

`Models/BOX_TRAINED.pt`: the only learned model in this repository. EasyOCR
(text recognition) is used as published and is not covered here.

| | |
|---|---|
| Task | Object detection, one class: `Box`, the strip that holds the four item cards on the CS2 weekly care-package screen |
| Architecture | YOLO11s (9.4 M parameters, 21.4 GFLOPs at 640 px), fine-tuned from the COCO-pretrained `yolo11s.pt` |
| Framework | Ultralytics 8.3.94 at training time. Loading it needs `ultralytics>=8.3.94` (YOLO11 modules `C3k2`, `C2PSA`) |
| Trained | 2025-03-20 on Google Colab (the run's data path was `/content/data.yaml`), 134 s for 80 epochs |
| File | 19.3 MB, sha256 `189723c293a7f9b01ea2dbf5c59584f55c687318dae9e1c36ef05bcaa7cc1f67` (`Models/SHA256SUMS`) |
| Licence | Fine-tuned from Ultralytics' `yolo11s.pt`, which Ultralytics publishes under AGPL-3.0; check that licence before shipping the model in a closed product. The repository's own code is MIT |
| Also published as | release asset `model-v1` (with the training run and the old labels) |

## Intended use

The model finds the four-card strip in a screenshot of the CS2 weekly
care-package screen, so the app can cut it into four cards and OCR their
names (`Src/ImageDetector/modified_detect_text.py`). The app keeps the
highest-confidence box at confidence ≥ 0.4 and refuses the screenshot
(`DetectionError`) when there is none.

It is not a general CS2 UI detector. It has never seen the main menu, the
inventory, or other reward screens, and nothing guarantees what it does on
them.

## Training data

- 22 screenshots, one box each, 19 for training and 3 for validation (the
  training run's `labels.jpg` and `val_batch0_labels.jpg`).
- They are public posts (Reddit, X, YouTube thumbnails) plus a few in-game
  captures: English, German and Finnish clients; 640 to 2560 px wide; some
  are phone photos of a monitor.
- Settings: imgsz 1024, batch 16, 80 epochs, seed 0, deterministic, default
  augmentation (mosaic, HSV jitter, translate 0.1, scale 0.5, horizontal flip).
- The original labels were never committed. Labels that reproduce the dataset
  (21 of the 22 images; the exact original list is not recoverable) are in
  [`dataset/`](dataset/README.md), with `tools/train_detector.py` to retrain.

## Evaluation

**Detector, March 2025 validation split.** 3 images, best epoch (76; the
weights shipped are `best.pt`): precision 0.986, recall 1.0, mAP50 0.995,
mAP50-95 0.995 (from the run's `results.csv`). Three images cannot support a
generalisation claim. Read this as "it fits its own data", not as a measured
accuracy.

**Whole pipeline (detector + EasyOCR + matcher), dev split.** Measured
2026-10-01 with `tools/ocr_accuracy.py --db <db> --split dev` on the 77 labelled
item slots in 20 screenshots. These are the detector's own training and
validation images, and the OCR band and matcher thresholds were tuned on them.
The numbers are in-sample.

| | slots | rate | 95 % interval (image bootstrap) |
|---|---|---|---|
| panel found | 20 / 20 images | 100 % | |
| right item | 62 / 77 | 80.5 % | 66–92 % (Wilson over slots: 70–88 %) |
| exact OCR text | 21 / 77 | 27.3 % | 14–41 % |

By the confidence the app shows next to each match:

| shown confidence | slots | right item |
|---|---|---|
| high | 36 | 36 |
| medium | 22 | 21 |
| low (never recommended) | 9 | 5 |
| no match | 10 | 0 |

Above the "low" tier, the app named the right item in 57 of 58 slots and
covered 75 % of all slots.

**Held-out test set.** None yet. The tooling is ready: label new screenshots
with `"split": "test"` in `tests/fixtures/expected_names.json`, then run
`tools/ocr_accuracy.py --split test`. This is the number to quote once it
exists.

## Known limitations

- **Small text.** In thumbnails and screenshots narrower than about 700 px,
  the panel is still found, but OCR fails. `hq720.jpg` (686 px) gets 0 of 4
  slots right, and the 640 px `wow-i-got-a-blue…webp` gets 1 of 4.
- **Perspective.** Phone photos at a steep angle are not axis-aligned. A
  box cannot isolate the cards, and the equal four-way split then cuts across
  them.
- **Fixed layout assumptions.** The pipeline assumes exactly four cards of
  equal width and the item name 62–86 % of the way down each card. A CS2 UI
  change would break this; `tests/test_golden_image.py` is the tripwire.
- **Non-English clients.** The detector works on them. OCR is English-only,
  and names are matched against English market names, so a German or Finnish
  screenshot finds its panel but rarely its items.
- **Dataset size.** 22 images is very little. All of them are from 2023–2025
  versions of the screen.

## Reproduce

```bash
sha256sum -c Models/SHA256SUMS
python tools/eval_detector.py                         # IoU vs dataset/labels (1.0 by construction)
python Src/DB/create_database.py --db build/eval.db
python Src/DB/fetch_item_lists.py --ref 45dbe29036ace44df46b81659820eb49953d72c3 --out-dir build/eval-lists
python Src/DB/populate_database.py --db build/eval.db --skins build/eval-lists/cs_skins.csv \
    --cases build/eval-lists/cs_cases.csv --graffiti build/eval-lists/cs_graffiti.csv \
    --tools build/eval-lists/cs_tools.csv
python tools/ocr_accuracy.py --db build/eval.db --split dev --json build/accuracy-dev.json
```

The `--ref` pins the item list to the ByMykel/CSGO-API commit these numbers
were measured with, because new items change which candidates the matcher sees.
Prices are not needed. Environment for the numbers above: Python 3.12, Linux
aarch64, CPU, torch 2.14.1, ultralytics 8.4.171, easyocr 1.7.2, opencv 4.14.0.

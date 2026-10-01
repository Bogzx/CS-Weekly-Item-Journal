# Panel detector dataset

What `Models/BOX_TRAINED.pt` detects, and what you need to retrain it.

| | |
|---|---|
| Class | `0: Box`, the strip holding the four item cards on the weekly care-package screen (not the "Weekly Care Package" title or the Claim button) |
| Images | 21 screenshots in `Training_Images/`, listed by `dataset.yaml` (18 train, 3 val) |
| Labels | `labels/<image name>.txt`, one line `0 cx cy w h`, normalised |
| Split | `val` = the three validation images of the March 2025 run that produced the shipped model |

## Where the labels came from

The labels the shipped model was trained on were never committed: it was
trained on Google Colab against `/content/data.yaml`, and only the weights and
the run's plots reached git. The training run is attached to the
[`model-v1` release](https://github.com/Bogzx/CS-Weekly-Item-Journal/releases)
as `training-run-2025-03-20.zip`. These labels were rebuilt on 2026-10-01:

1. `python tools/label_with_model.py --review build/label-review` ran the
   shipped model on every image and wrote its highest-confidence box (0.89 to
   0.96 on all 21 images).
2. Every box was checked by eye on the review images: it encloses the four
   cards and the 1×4 split falls on the card borders.
3. As an independent check, the boxes were compared with an older Label Studio
   export from March 2025 (`data.zip`, removed from the tree in commit 74a4f89;
   attached to the same release as `legacy-text-labels-2025-03-20.zip`). It
   labels the item-name text of each card (4 boxes per image, 18 images).
   `--legacy-labels` reports that all 72 of those boxes lie inside the panel
   boxes.

So these labels agree with the shipped model by construction. They make it
possible to retrain and to compare a new model with the old one. They are not
an independent measure of the shipped model's accuracy.

Not in the dataset (`exclude` in `dataset.yaml`):

- `TEST FINAL.png`: the German main menu photographed at a steep angle. The
  care package is shown there, but it is not the care-package screen. No
  axis-aligned box isolates the four cards, and the shipped model finds none
  (best guess 0.17).
- `high_res_output.jpg`: not a care-package screenshot.
- `pythjonm.jpeg`: duplicate of `n51265 (1).jpeg`.

The March 2025 run had 22 instances (19 train, 3 val; its `labels.jpg`). The
exact image list is not recoverable, so this dataset has 21.

## Retrain

```bash
python tools/train_detector.py --prepare-only   # build/detector-dataset/ + data.yaml
python tools/train_detector.py                  # yolo11s.pt, 80 epochs, imgsz 1024, seed 0
python tools/eval_detector.py --model build/detector-runs/train/weights/best.pt
pytest -m slow                                  # with the new weights in Models/
```

The defaults are the March 2025 run's settings (its `args.yaml`). That run
took about two minutes on a Colab GPU. On a CPU, expect hours at imgsz 1024.
`--epochs 1 --imgsz 320` is enough to check that the setup works.

Swap `Models/BOX_TRAINED.pt` only if the new model does at least as well on
`tools/eval_detector.py` and `tools/ocr_accuracy.py`, and `pytest -m slow`
passes. Update `Models/SHA256SUMS` and `MODEL_CARD.md` with it.

## Adding images

Add the screenshot to `Training_Images/` (or list it under `exclude`). Then run
`python tools/label_with_model.py --keep-existing --review build/label-review`.
This labels only the new images. Check the review image, and fix the label by
hand if the box is wrong: open the image in any labelling tool and write
`0 cx cy w h`. If the model finds nothing, the tool says which file to write.
To score the new image's OCR too, label its four item names in
`tests/fixtures/expected_names.json`.

"""Golden-image regression test for the detection + OCR pipeline.

This single test is the tripwire for the whole vision stack. It catches, in one
assertion:

  * model-load breakage -- e.g. ultralytics < 8.3.94 cannot unpickle the
    YOLO11 modules (C3k2, C2PSA) in Models/BOX_TRAINED.pt and dies with
    "AttributeError: Can't get attribute 'C3k2'". That is exactly the state
    requirements.txt shipped in before this branch.
  * ultralytics API drift in the detection call
  * EasyOCR output changes
  * CS2 UI changes that move the item-name text out of the sampled region

It is marked `slow` because the first run downloads EasyOCR's detection and
recognition weights (~100 MB). Run just the fast tests with:

    pytest -m "not slow"

FIXTURE NOTE
------------
The fixture is `Training_Images/image.png`, a 2560x1440 English screenshot.

`Training_Images/TEST FINAL.png` looks like the obvious candidate but is a
*German* client screenshot -- it OCRs to 'Mauf Kostenlos',
'Versiegeltes ... Graffito' and so on, and would need German EasyOCR weights.

The expectations below are what the pipeline produces, verified by running
it. They are substring assertions so a harmless OCR tweak does not fail the
build while a real regression still does. Since the text band was moved to
cover both lines of a card (round 3 of the 2026-09-30 review), the graffiti
colours and the fourth slot's name are read too; before, slots 2 and 3 came
back as just "Sealed Graffiti | Sorry" and "Sealed Graffiti".

test_accuracy_over_all_labelled_screenshots runs the same pipeline over every
labelled Training_Image (tests/fixtures/expected_names.json) and fails if the
aggregate drops below the level measured when the band was tuned.
"""

import os

import pytest

pytestmark = pytest.mark.slow

FIXTURE = os.path.join('Training_Images', 'image.png')

# Each entry: substrings that must all appear in that slot's OCR text.
EXPECTED_SLOTS = [
    ['Revolution Case'],
    ['Sawed-Off', 'Forest DDPAT'],
    ['Sealed Graffiti', 'Sorry', 'Bazooka Pink'],
    ['Sealed Graffiti', 'Speechless', 'Princess Pink'],
]


@pytest.fixture(scope='module')
def detected_texts(repo_root):
    from Src.ImageDetector.modified_detect_text import WeeklyDropProcessor

    image_path = os.path.join(repo_root, FIXTURE)
    assert os.path.exists(image_path), (
        f"Golden fixture missing: {image_path}. It must stay committed -- "
        f"this test is the only regression guard on the vision pipeline."
    )

    model_path = os.path.join(repo_root, 'Models', 'BOX_TRAINED.pt')
    processor = WeeklyDropProcessor(model_path)
    return processor.process_image(image_path, save_crops=False)


def test_model_loads_and_exposes_the_box_class():
    """Fastest possible check that the weights still deserialize.

    If this fails with AttributeError mentioning C3k2 or C2PSA, ultralytics has
    been downgraded below 8.3.94.
    """
    from ultralytics import YOLO

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    model = YOLO(os.path.join(repo_root, 'Models', 'BOX_TRAINED.pt'))

    assert 'Box' in model.names.values()


def test_detects_exactly_four_slots(detected_texts):
    """A CS2 care package always offers four choices."""
    assert len(detected_texts) == 4


@pytest.mark.parametrize('index,fragments', list(enumerate(EXPECTED_SLOTS)))
def test_slot_text_still_recognised(detected_texts, index, fragments):
    actual = detected_texts[index]
    for fragment in fragments:
        assert fragment.lower() in actual.lower(), (
            f"Slot {index} lost the expected text {fragment!r}. Got {actual!r}. "
            f"Either OCR regressed or the CS2 drop UI changed."
        )


def test_undetectable_image_raises_rather_than_guessing(repo_root, tmp_path):
    """A screenshot with no drop panel must fail loudly.

    The old code silently fell back to slicing the entire image into quarters,
    which produced four confident but completely wrong item names.
    """
    import numpy as np
    import cv2

    from Src.ImageDetector.modified_detect_text import (
        WeeklyDropProcessor, DetectionError,
    )

    blank = np.zeros((720, 1280, 3), dtype=np.uint8)
    blank_path = str(tmp_path / 'blank.png')
    cv2.imwrite(blank_path, blank)

    processor = WeeklyDropProcessor(os.path.join(repo_root, 'Models', 'BOX_TRAINED.pt'))

    with pytest.raises(DetectionError):
        processor.process_image(blank_path, save_crops=False)


def test_accuracy_over_all_labelled_screenshots(repo_root):
    """Aggregate OCR accuracy must not fall below the tuned level.

    Measured 2026-09-30 over 77 scored slots in 20 images: mean similarity
    0.642 and 20 fuzzy matches with the old 50-75% text band; 0.818 and 42
    with the current band, upscaling and UI-line filtering. The floors leave a
    little room for OCR noise across EasyOCR/torch versions.
    """
    import sys

    sys.path.insert(0, os.path.join(repo_root, 'tools'))
    import ocr_accuracy

    from Src.ImageDetector.modified_detect_text import WeeklyDropProcessor

    processor = WeeklyDropProcessor(os.path.join(repo_root, 'Models', 'BOX_TRAINED.pt'))
    summary = ocr_accuracy.summarise(
        ocr_accuracy.evaluate(processor, ocr_accuracy.load_labels(split='dev')))

    assert summary['slots_scored'] == 77
    assert summary['mean_similarity'] >= 0.79, summary
    assert summary['fuzzy'] >= 38, summary

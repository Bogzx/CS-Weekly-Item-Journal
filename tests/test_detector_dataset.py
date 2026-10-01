"""The committed detector dataset (dataset/) is complete and well formed.

No model needed: these check the files tools/train_detector.py trains from.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))

import eval_detector  # noqa: E402
import label_with_model  # noqa: E402
import train_detector  # noqa: E402


@pytest.fixture(scope='module')
def manifest():
    return label_with_model.load_manifest()


def test_every_dataset_image_has_one_valid_box(manifest):
    images = label_with_model.dataset_images(manifest)

    assert len(images) == 21
    for name in images:
        cx, cy, w, h = label_with_model.read_label(label_with_model.label_path(manifest, name))
        assert 0 < w <= 1 and 0 < h <= 1, name
        assert 0 <= cx - w / 2 and cx + w / 2 <= 1 + 1e-6, name
        assert 0 <= cy - h / 2 and cy + h / 2 <= 1 + 1e-6, name


def test_no_stray_label_files(manifest):
    expected = {os.path.basename(label_with_model.label_path(manifest, name))
                for name in label_with_model.dataset_images(manifest)}

    assert set(os.listdir(manifest['labels_dir'])) == expected


def test_excluded_and_val_images_exist(manifest):
    present = set(os.listdir(manifest['images_dir']))

    assert set(manifest['exclude']) <= present
    assert set(manifest['val']) <= set(label_with_model.dataset_images(manifest))


def test_prepare_builds_the_ultralytics_layout(manifest, tmp_path):
    data_yaml = train_detector.prepare(manifest, str(tmp_path / 'ds'))

    assert os.path.exists(data_yaml)
    for split, count in (('train', 18), ('val', 3)):
        images = os.listdir(tmp_path / 'ds' / 'images' / split)
        labels = os.listdir(tmp_path / 'ds' / 'labels' / split)
        assert len(images) == len(labels) == count
        assert {os.path.splitext(n)[0] for n in images} == {os.path.splitext(n)[0] for n in labels}


def test_yolo_box_round_trip():
    box = (100.0, 50.0, 500.0, 250.0)

    assert label_with_model.from_yolo(label_with_model.to_yolo(box, 800, 400), 800, 400) == pytest.approx(box)


@pytest.mark.parametrize('a, b, expected', [
    ((0, 0, 10, 10), (0, 0, 10, 10), 1.0),
    ((0, 0, 10, 10), (5, 0, 15, 10), 50 / 150),
    ((0, 0, 10, 10), (20, 20, 30, 30), 0.0),
])
def test_iou(a, b, expected):
    assert eval_detector.iou(a, b) == pytest.approx(expected)


def test_legacy_label_names_match_their_screenshots(tmp_path):
    """The March 2025 export renamed files: URL-quoted Cyrillic, (1) -> _1, a new name."""
    for legacy in ('2d9a8925__3bfc2e99-3051505611_preview_%D0%91%D0%B5%D0%B7_%D0%B8%D0%BC%D0%B5%D0%BD%D0%B8-4.txt',
                   '89f58f5b-n51265_1.txt', 'a6dafe90-weekly-care-package-v0-kezy06qv6vqb1.txt'):
        (tmp_path / legacy).write_text('1 0.5 0.5 0.1 0.1\n')

    for image in ('3051505611_preview_Без имени-4.png', 'n51265 (1).jpeg', 'test.webp'):
        assert label_with_model.legacy_card_boxes(str(tmp_path), image) == [(0.5, 0.5, 0.1, 0.1)], image
    assert label_with_model.legacy_card_boxes(str(tmp_path), 'image.png') is None

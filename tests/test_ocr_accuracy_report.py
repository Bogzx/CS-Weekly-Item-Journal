"""The statistics tools/ocr_accuracy.py reports, checked without the model."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))

import ocr_accuracy  # noqa: E402


def row(image, item_ok, confidence='high', name='AK-47 | Redline', scored=True):
    return {'image': image, 'item_ok': item_ok, 'exact_item_ok': item_ok, 'exact': item_ok,
            'fuzzy': item_ok, 'match_confidence': confidence, 'type': ocr_accuracy.item_type(name),
            'scored': scored}


class TestWilson:
    def test_matches_the_published_formula(self):
        # 62 of 77, the dev-set figure: 95% interval 70.3% to 87.8%.
        low, high = ocr_accuracy.wilson(62, 77)

        assert low == pytest.approx(0.703, abs=0.001)
        assert high == pytest.approx(0.878, abs=0.001)

    def test_all_right_still_has_a_lower_bound_below_one(self):
        low, high = ocr_accuracy.wilson(10, 10)

        assert high == 1.0
        assert low < 0.75

    def test_no_slots(self):
        assert ocr_accuracy.wilson(0, 0) == (0.0, 0.0)


class TestImageBootstrap:
    def test_is_deterministic_and_brackets_the_rate(self):
        rows = [row(f'img{i}', i % 3 != 0) for i in range(30)]

        first = ocr_accuracy.image_bootstrap(rows, 'item_ok')
        second = ocr_accuracy.image_bootstrap(rows, 'item_ok')

        assert first == second
        assert first[0] <= 20 / 30 <= first[1]

    def test_clustered_failures_widen_the_interval(self):
        """Four failures in one image are less evidence than four spread out."""
        spread = [row(f'img{i}', not (i % 4 == 0 and i < 16), name=str(i)) for i in range(40)]
        clustered = [row(f'img{i // 4}', i >= 4) for i in range(40)]

        spread_low, spread_high = ocr_accuracy.image_bootstrap(spread, 'item_ok')
        clustered_low, clustered_high = ocr_accuracy.image_bootstrap(clustered, 'item_ok')

        assert sum(r['item_ok'] for r in spread) == sum(r['item_ok'] for r in clustered)
        assert clustered_high - clustered_low > spread_high - spread_low


class TestBreakdowns:
    def test_item_type(self):
        assert ocr_accuracy.item_type('Sealed Graffiti | QQ (Violent Violet)') == 'graffiti'
        assert ocr_accuracy.item_type('Nova | Predator') == 'skin'
        assert ocr_accuracy.item_type('Recoil Case') == 'case/other'
        assert ocr_accuracy.item_type('Charm Detachment Pack') == 'case/other'

    def test_confidence_table_is_cumulative_from_the_top_tier(self):
        rows = ([row('a', True, 'high')] * 4 + [row('b', True, 'medium'), row('b', False, 'medium')]
                + [row('c', False, 'low'), row('d', False, None)])

        table = ocr_accuracy.by_confidence(rows)

        assert [t['tier'] for t in table] == ['high', 'medium', 'low', 'no match']
        assert [t['slots'] for t in table] == [4, 2, 1, 1]
        assert table[0]['precision_so_far'] == 1.0
        assert table[1]['coverage_so_far'] == 0.75
        assert table[1]['precision_so_far'] == pytest.approx(5 / 6, abs=1e-4)
        assert table[3]['coverage_so_far'] == 1.0

    def test_report_ignores_unscored_slots(self):
        rows = [row('a', True), row('a', False, scored=False)]

        result = ocr_accuracy.report(rows)

        assert result['rates']['item_ok']['n'] == 1


class TestSplits:
    def test_every_labelled_image_has_a_known_split(self):
        labels = ocr_accuracy.load_labels()

        assert labels
        assert {entry['split'] for _name, entry in labels} <= set(ocr_accuracy.SPLITS)

    def test_dev_is_the_77_slot_tuning_set(self):
        dev = ocr_accuracy.load_labels(split='dev')
        scored = sum(1 for _name, entry in dev for slot in entry['slots']
                     if ocr_accuracy.slot_is_scored(entry, slot))

        assert scored == 77

    def test_dev_images_all_exist(self):
        for name, entry in ocr_accuracy.load_labels(split='dev'):
            assert os.path.exists(ocr_accuracy.image_path(name, entry)), name

"""Tests for the highest-value recommendation.

README.md:9 and :16 have always advertised that the app "automatically
recommends the highest-value item". Until this branch there was no implementing
code at all -- the results page listed candidates ordered by OCR match score
(Src/ImageDetector/item_matcher.py:327), which is unrelated to price. These
tests pin the behaviour so the headline feature cannot quietly regress again.
"""

import pytest


def slot(*prices, status='found'):
    """Build a detected-slot dict with one candidate match per price."""
    return {
        'original': 'detected text',
        'cleaned': 'detected text',
        'status': status,
        'matches': [
            {'id': i, 'name': f'Item {i}', 'price': p, 'score': 0.9, 'confidence': 'high'}
            for i, p in enumerate(prices)
        ],
    }


class TestAsPrice:
    @pytest.mark.parametrize('raw,expected', [
        (1.5, 1.5),
        ('2.25', 2.25),
        (0, 0.0),
        (None, None),
        ('', None),
        ('N/A', None),
        (-3, None),          # negative prices are data corruption, not a bargain
    ])
    def test_coercion(self, appmod, raw, expected):
        assert appmod._as_price(raw) == expected


class TestAnnotateRecommendation:
    def test_picks_the_highest_priced_slot(self, appmod):
        results = [slot(1.00), slot(42.50), slot(7.25)]

        recommended = appmod.annotate_recommendation(results)

        assert recommended is results[1]
        assert results[1]['recommended'] is True
        assert results[1]['best_price'] == 42.50
        assert results[1]['best_match']['recommended'] is True

    def test_only_one_slot_is_tagged(self, appmod):
        results = [slot(1.00), slot(42.50), slot(7.25)]

        appmod.annotate_recommendation(results)

        tagged = [r for r in results if r.get('recommended')]
        assert len(tagged) == 1

    def test_picks_highest_price_within_a_slot_not_best_match_score(self, appmod):
        """The priciest candidate wins even when it is not the top OCR match.

        This is the exact bug the feature exists to fix: matches arrive sorted
        by similarity score, so matches[0] is the closest *string*, not the
        most valuable item.
        """
        results = [slot(3.00, 99.00, 5.00)]

        appmod.annotate_recommendation(results)

        assert results[0]['best_match']['price'] == 99.00
        assert results[0]['best_match']['id'] == 1

    def test_unpriced_candidates_are_ignored_not_treated_as_zero(self, appmod):
        results = [slot(None, 4.00), slot(None, None)]

        recommended = appmod.annotate_recommendation(results)

        assert recommended is results[0]
        assert results[0]['best_price'] == 4.00
        # The slot where nothing has a price gets no recommendation at all.
        assert results[1]['best_match'] is None
        assert results[1]['best_price'] is None

    def test_returns_none_when_nothing_has_a_price(self, appmod):
        """A freshly-built database has no prices yet; that must not crash."""
        results = [slot(None), slot(None, None)]

        assert appmod.annotate_recommendation(results) is None
        assert not any(r.get('recommended') for r in results)

    def test_handles_slots_with_no_matches(self, appmod):
        results = [
            {'original': 'x', 'cleaned': 'x', 'status': 'not_found', 'matches': []},
            slot(12.00),
        ]

        recommended = appmod.annotate_recommendation(results)

        assert recommended is results[1]

    def test_empty_input(self, appmod):
        assert appmod.annotate_recommendation([]) is None

    def test_price_value_is_populated_for_the_template(self, appmod):
        """results.html formats match.price_value, so it must always be set."""
        results = [slot(1.00, None, '3.50')]

        appmod.annotate_recommendation(results)

        values = [m['price_value'] for m in results[0]['matches']]
        assert values == [1.00, None, 3.50]

    def test_zero_priced_item_still_counts_as_priced(self, appmod):
        results = [slot(0.0)]

        recommended = appmod.annotate_recommendation(results)

        assert recommended is results[0]
        assert results[0]['best_price'] == 0.0

"""Tests for slot valuation and the two recommended picks.

The care-package screen shows the item but not a skin's wear, so a skin slot
matches several wear variants at very different prices. The app used to value
a slot at the priciest candidate in its list -- usually Factory New, and
sometimes a different item that merely fuzzy-matched -- and recommended one
item although the game lets you claim two. These tests pin the replacement:
value over the top match's own wears with a configurable rule (default: the
cheapest wear), and recommend the two most valuable slots.
"""

import pytest

from Src.Web import matching, valuation

WEARS = ['Factory New', 'Minimal Wear', 'Field-Tested', 'Well-Worn', 'Battle-Scarred']


def match(name, price, score=0.9, confidence='high', id_=None):
    return {'id': id_ if id_ is not None else name, 'name': name, 'price': price,
            'score': score, 'confidence': confidence}


def slot(*matches, status='found'):
    return {'original': 'detected text', 'cleaned': 'detected text',
            'status': status, 'matches': list(matches)}


def skin_slot(base, prices, extra=()):
    """A skin slot: the top match plus its wear variants, one price per wear."""
    variants = [match(f'{base} ({wear})', price) for wear, price in zip(WEARS, prices)]
    return slot(*variants, *extra)


def priced(*prices):
    """One distinct item per price (like the case slot or a graffiti)."""
    return slot(*(match(f'Item {i}', p, id_=i) for i, p in enumerate(prices)))


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
        assert valuation.as_price(raw) == expected


class TestBaseItemName:
    @pytest.mark.parametrize('name,expected', [
        ('AK-47 | Redline (Field-Tested)', 'AK-47 | Redline'),
        ('Sawed-Off | Forest DDPAT (Battle-Scarred)', 'Sawed-Off | Forest DDPAT'),
        ('Revolution Case', 'Revolution Case'),
        # OCR usually loses a graffiti's colour, so colours group like wears.
        ('Sealed Graffiti | Sorry (Tiger Orange)', 'Sealed Graffiti | Sorry'),
        ('Sealed Graffiti | Sorry', 'Sealed Graffiti | Sorry'),
        # Other parentheses are part of the name.
        ('Some Item (Holo)', 'Some Item (Holo)'),
        (None, ''),
    ])
    def test_strips_only_wears(self, appmod, name, expected):
        assert valuation.base_item_name(name) == expected


class TestSlotValue:
    def test_default_rule_values_a_skin_at_its_cheapest_wear(self, appmod):
        results = [skin_slot('P250 | Sand Dune', [5.00, 1.00, 0.20, 0.50, 0.10])]

        appmod.annotate_recommendation(results)

        r = results[0]
        assert r['value'] == 0.10
        assert r['value_match']['name'] == 'P250 | Sand Dune (Battle-Scarred)'
        assert (r['price_min'], r['price_max']) == (0.10, 5.00)
        assert r['priced_variants'] == 5
        assert r['display_name'] == 'P250 | Sand Dune'

    @pytest.mark.parametrize('rule,expected', [
        ('lowest', 0.10),
        ('median', 0.50),
        ('highest', 5.00),
    ])
    def test_rule_switch(self, appmod, rule, expected):
        results = [skin_slot('P250 | Sand Dune', [5.00, 1.00, 0.20, 0.50, 0.10])]

        appmod.annotate_recommendation(results, rule=rule)

        assert results[0]['value'] == expected

    def test_median_of_an_even_count_is_a_real_price(self, appmod):
        results = [skin_slot('P250 | Sand Dune', [4.00, 3.00, 2.00, 1.00])]

        appmod.annotate_recommendation(results, rule='median')

        assert results[0]['value'] == 2.00
        assert results[0]['value_match']['price_value'] == 2.00

    def test_other_items_in_the_list_do_not_count(self, appmod):
        """The regression H5 was about: a pricier *different* item that only
        fuzzy-matched the OCR text used to set the slot's value."""
        results = [skin_slot('Sawed-Off | Forest DDPAT', [0.40, 0.10, 0.05],
                             extra=[match('★ Butterfly Knife | Forest DDPAT (Field-Tested)', 300.0, score=0.6)])]

        appmod.annotate_recommendation(results, rule='highest')

        assert results[0]['value'] == 0.40
        assert results[0]['price_max'] == 0.40

    def test_case_slot_is_valued_at_its_top_match_only(self, appmod):
        results = [priced(0.55, 12.00)]  # Item 1 is a different case

        appmod.annotate_recommendation(results)

        assert results[0]['value'] == 0.55
        assert results[0]['value_match']['id'] == 0

    def test_unpriced_wears_are_ignored_not_treated_as_zero(self, appmod):
        results = [skin_slot('P250 | Sand Dune', [None, 2.00, None, 3.00])]

        appmod.annotate_recommendation(results)

        assert results[0]['value'] == 2.00
        assert results[0]['priced_variants'] == 2
        assert results[0]['variant_count'] == 4

    def test_unpriced_top_match_leaves_the_slot_unvalued(self, appmod):
        results = [priced(None, 4.00)]

        assert appmod.annotate_recommendation(results) == []
        assert results[0]['value'] is None
        assert results[0]['value_match'] is None

    def test_price_value_is_populated_for_the_template(self, appmod):
        """results.html formats match.price_value, so it must always be set."""
        results = [priced(1.00, None, '3.50')]

        appmod.annotate_recommendation(results)

        values = [m['price_value'] for m in results[0]['matches']]
        assert values == [1.00, None, 3.50]

    def test_zero_priced_item_still_counts_as_priced(self, appmod):
        results = [priced(0.0)]

        recommended = appmod.annotate_recommendation(results)

        assert recommended == [results[0]]
        assert results[0]['value'] == 0.0


    def test_graffiti_colours_form_one_family(self, appmod):
        results = [slot(match('Sealed Graffiti | Sorry (Brick Red)', 0.09),
                        match('Sealed Graffiti | Sorry (Shark White)', 0.03),
                        match('Sealed Graffiti | Sorry (Tiger Orange)', 0.05))]

        appmod.annotate_recommendation(results)

        assert results[0]['value'] == 0.03
        assert results[0]['variant_kind'] == 'colours'
        assert results[0]['display_name'] == 'Sealed Graffiti | Sorry'


class TestRecommendedPicks:
    def test_recommends_the_two_most_valuable_slots_in_order(self, appmod):
        results = [priced(1.00), priced(42.50), priced(7.25), priced(3.00)]

        recommended = appmod.annotate_recommendation(results)

        assert recommended == [results[1], results[2]]
        assert [r.get('pick_rank') for r in results] == [None, 1, 2, None]
        assert [bool(r.get('recommended')) for r in results] == [False, True, True, False]

    def test_the_valued_candidate_is_the_one_pre_selected(self, appmod):
        results = [skin_slot('P250 | Sand Dune', [5.00, 1.00, 0.20]), priced(0.01)]

        appmod.annotate_recommendation(results)

        flagged = [m['name'] for m in results[0]['matches'] if m.get('recommended')]
        assert flagged == ['P250 | Sand Dune (Field-Tested)']
        # Two slots recommended -> exactly two pre-selected checkboxes.
        flagged_total = sum(bool(m.get('recommended')) for r in results for m in r['matches'])
        assert flagged_total == 2

    def test_cheapest_wear_rule_changes_the_ranking(self, appmod):
        """A skin that is only valuable in Factory New no longer outranks a case."""
        results = [priced(0.60), skin_slot('P250 | Sand Dune', [9.00, 0.30]), priced(0.40)]

        lowest = appmod.annotate_recommendation(results, rule='lowest')

        assert lowest == [results[0], results[2]]
        assert results[1]['value'] == 0.30

    def test_optimistic_rule_restores_the_old_ranking(self, appmod):
        results = [priced(0.60), skin_slot('P250 | Sand Dune', [9.00, 0.30]), priced(0.40)]

        highest = appmod.annotate_recommendation(results, rule='highest')

        assert highest == [results[1], results[0]]

    def test_low_confidence_slot_is_valued_but_never_picked(self, appmod):
        """Low-confidence top matches were right only 5 times in 10 on the
        labelled screenshots."""
        shaky = slot(match('Item X', 50.0, score=0.45, confidence='low'))
        results = [priced(1.00), shaky, priced(0.50)]

        recommended = appmod.annotate_recommendation(results)

        assert recommended == [results[0], results[2]]
        assert results[1]['value'] == 50.0
        assert results[1]['uncertain'] is True

    def test_non_tradable_slot_is_never_picked(self, appmod):
        charm = slot(dict(match('Charm Detachment Pack', 0.0), tradable=False))
        results = [charm, priced(0.03), priced(None)]

        recommended = appmod.annotate_recommendation(results)

        assert recommended == [results[1]]           # not the $0 tool, even as pick 2
        assert results[0]['not_tradable'] is True
        assert results[0]['value'] == 0.0
        assert not results[0].get('recommended')

    def test_non_tradable_is_not_picked_even_when_nothing_else_is_priced(self, appmod):
        charm = slot(dict(match('Charm Detachment Pack', 0.0), tradable=False))

        assert appmod.annotate_recommendation([charm, priced(None)]) == []

    def test_candidates_default_to_tradable(self, appmod):
        """Rows from a database built before the tradable column existed."""
        entry = matching.candidate_entry({'id': 1, 'name': 'Revolution Case'}, 1.0, 'high')

        assert entry['tradable'] is True
        assert matching.candidate_entry({'tradable': 0}, 1.0, 'high')['tradable'] is False

    def test_ties_keep_screen_order(self, appmod):
        results = [priced(1.00), priced(1.00), priced(1.00)]

        assert appmod.annotate_recommendation(results) == [results[0], results[1]]

    def test_single_priced_slot_gives_a_single_pick(self, appmod):
        results = [priced(None), priced(2.00),
                   {'original': 'x', 'cleaned': 'x', 'status': 'not_found', 'matches': []}]

        assert appmod.annotate_recommendation(results) == [results[1]]

    def test_returns_empty_when_nothing_has_a_price(self, appmod):
        """A freshly built database has no prices yet; that must not crash."""
        results = [priced(None), priced(None, None)]

        assert appmod.annotate_recommendation(results) == []
        assert not any(r.get('recommended') for r in results)

    def test_empty_input(self, appmod):
        assert appmod.annotate_recommendation([]) == []


class TestValuationConfig:
    @pytest.mark.parametrize('raw,expected', [
        (None, 'lowest'),
        ('', 'lowest'),
        ('median', 'median'),
        (' HIGHEST ', 'highest'),
        ('max', 'lowest'),      # unknown -> conservative default, with a warning
    ])
    def test_resolve(self, appmod, raw, expected):
        assert appmod.resolve_valuation_rule(raw) == expected

    def test_app_default_is_conservative(self, appmod):
        assert appmod.app.config['VALUATION_RULE'] == 'lowest'


class TestResultsPage:
    def test_upload_shows_two_picks_with_ranges(self, appmod, logged_in, monkeypatch):
        import io

        from PIL import Image

        results = [
            priced(0.55),
            skin_slot('Sawed-Off | Forest DDPAT', [0.90, 0.20, 0.05, 0.04, 0.03]),
            priced(0.04),
            priced(0.02),
        ]
        monkeypatch.setattr(appmod, 'process_image', lambda path: ['a', 'b', 'c', 'd'])
        monkeypatch.setattr(appmod, 'match_items_in_database', lambda names: results)
        buf = io.BytesIO()
        Image.new('RGB', (4, 4)).save(buf, format='PNG')
        buf.seek(0)

        resp = logged_in.post('/upload', data={'file': (buf, 'shot.png')},
                              content_type='multipart/form-data')

        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert 'Pick 1' in html and 'Pick 2' in html
        assert 'you can claim 2 of the 4 items' in html
        # The skin is worth $0.03 at its cheapest wear, so the case ($0.55)
        # and the $0.04 item are the picks; its range is still shown.
        assert 'range $0.03–$0.90 over 5 priced wears' in html
        assert [r.get('pick_rank') for r in results] == [1, None, 2, None]
        assert 'VALUATION_RULE=lowest' in html
        assert html.count(' checked>') == 2


class TestGraffitiMatching:
    @pytest.fixture
    def graffiti_matcher(self, appmod, tmp_path, monkeypatch):
        import sqlite3

        from Src.ImageDetector.item_matcher import ItemMatcher

        db = str(tmp_path / 'items.db')
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, collection TEXT, "
                     "price REAL, price_type TEXT, item_type TEXT)")
        for colour, price in [('Brick Red', 0.09), ('Shark White', 0.03), ('Tiger Orange', 0.05)]:
            conn.execute("INSERT INTO items (name, collection, price, item_type) VALUES (?, ?, ?, 'graffiti')",
                         (f'Sealed Graffiti | Sorry ({colour})', 'Community Graffiti Box 1', price))
        conn.execute("INSERT INTO items (name, collection, item_type) VALUES ('Revolution Case', 'Revolution Case', 'case')")
        conn.commit()
        conn.close()
        monkeypatch.setattr(appmod, 'matcher', ItemMatcher(db))

    def test_colour_lost_by_ocr_lists_every_colour(self, appmod, graffiti_matcher):
        results = appmod.match_items_in_database(['Revolution Case', 'Sealed Graffiti | Sorry'])

        names = sorted(m['name'] for m in results[1]['matches'])
        assert names == ['Sealed Graffiti | Sorry (Brick Red)', 'Sealed Graffiti | Sorry (Shark White)',
                         'Sealed Graffiti | Sorry (Tiger Orange)']
        appmod.annotate_recommendation(results)
        assert (results[1]['price_min'], results[1]['price_max']) == (0.03, 0.09)

    def test_colour_read_by_ocr_selects_that_colour(self, appmod, graffiti_matcher):
        results = appmod.match_items_in_database(['Revolution Case', 'Sealed Graffiti | Sorry (Tiger 0range)'])

        assert [m['name'] for m in results[1]['matches']] == ['Sealed Graffiti | Sorry (Tiger Orange)']
        assert results[1]['matches'][0]['price'] == 0.05

    def test_type_only_text_is_not_matched_to_an_arbitrary_graffiti(self, appmod, graffiti_matcher):
        """The golden screenshot's 4th slot OCRs as just 'Sealed Graffiti'.
        That scored 1.0 ('high') against every graffiti, and the arbitrary
        pick could become a recommendation."""
        results = appmod.match_items_in_database(['Revolution Case', 'Sealed Graffiti'])

        assert results[1]['status'] == 'name_missing'
        assert results[1]['matches'] == []
        appmod.annotate_recommendation(results)
        assert results[1]['value'] is None

    def test_slot_order_does_not_decide_the_item_type(self, appmod, graffiti_matcher):
        """Slot 0 used to be searched for cases only, whatever it said."""
        results = appmod.match_items_in_database(['Sealed Graffiti | Sorry (Tiger Orange)', 'Revolution Case'])

        assert [m['name'] for m in results[0]['matches']] == ['Sealed Graffiti | Sorry (Tiger Orange)']
        assert results[1]['matches'][0]['name'] == 'Revolution Case'


def test_results_page_shows_not_tradable(appmod, logged_in, monkeypatch):
    import io

    from PIL import Image

    results = [
        priced(0.55),
        slot(dict(match('Charm Detachment Pack', 0.0), tradable=False)),
        priced(0.04),
        priced(0.02),
    ]
    monkeypatch.setattr(appmod, 'process_image', lambda path: ['a', 'b', 'c', 'd'])
    monkeypatch.setattr(appmod, 'match_items_in_database', lambda names: results)
    buf = io.BytesIO()
    Image.new('RGB', (4, 4)).save(buf, format='PNG')
    buf.seek(0)

    html = logged_in.post('/upload', data={'file': (buf, 'shot.png')},
                          content_type='multipart/form-data').get_data(as_text=True)

    assert 'Not tradable — $0' in html
    assert [r.get('pick_rank') for r in results] == [1, None, 2, None]


def test_charm_pack_flows_from_the_database_to_not_tradable(appmod, tmp_path, monkeypatch):
    import sqlite3

    from Src.DB import create_database, populate_database
    from Src.ImageDetector.item_matcher import ItemMatcher

    db = str(tmp_path / 'items.db')
    create_database.create_csgo_database(db)
    conn = sqlite3.connect(db)
    populate_database.populate_cases(conn, [{'Case': 'Revolution Case', 'Steam Market API URL': 'x'}])
    populate_database.populate_tools(conn, [{'Name': 'Charm Detachment Pack', 'Tradable': '0'}])
    conn.execute("UPDATE items SET price = 0.55 WHERE name = 'Revolution Case'")
    conn.commit()
    conn.close()
    monkeypatch.setattr(appmod, 'matcher', ItemMatcher(db))

    results = appmod.match_items_in_database(['Revolution Case', 'Charm Detachment Pack'])
    recommended = appmod.annotate_recommendation(results)

    assert results[1]['matches'][0]['tradable'] is False
    assert results[1]['not_tradable'] is True
    assert recommended == [results[0]]

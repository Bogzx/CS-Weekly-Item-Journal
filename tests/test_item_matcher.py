"""ItemMatcher text normalisation and matching (L3)."""

import sqlite3

import pytest

from Src.ImageDetector.item_matcher import ItemMatcher

WEARS = ['Factory New', 'Minimal Wear', 'Field-Tested', 'Well-Worn', 'Battle-Scarred']


@pytest.fixture
def matcher():
    return ItemMatcher(':memory:')


class TestNormalizeText:
    @pytest.mark.parametrize('wear', WEARS)
    def test_every_wear_is_stripped(self, matcher, wear):
        assert matcher.normalize_text(f'AK-47 | Redline ({wear})') == \
            matcher.normalize_text('AK-47 | Redline')

    @pytest.mark.parametrize('text', ['field tested', 'FIELD-TESTED', 'Battle Scarred', 'well - worn'])
    def test_wear_spelling_variants(self, matcher, text):
        assert matcher.normalize_text(f'P250 | Sand Dune {text}') == 'p2so sand dune'

    def test_filler_words_are_removed_as_whole_words_only(self, matcher):
        assert matcher.normalize_text('Revolution Case') == 'revolution'
        assert matcher.normalize_text('Showcase') == 'showcase'
        assert matcher.normalize_text('Snakeskin') == 'snakeskin'
        assert matcher.normalize_text('Glitem') == 'glitem'

    def test_empty(self, matcher):
        assert matcher.normalize_text('') == ''
        assert matcher.normalize_text(None) == ''


@pytest.fixture
def db_matcher(tmp_path):
    db = str(tmp_path / 'items.db')
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, collection TEXT, "
                 "price REAL, price_type TEXT, item_type TEXT)")
    rows = [(f'Sawed-Off | Forest DDPAT ({w})', 'The Bank Collection', 'skin') for w in WEARS]
    rows += [(f'P250 | Sand Dune ({w})', 'The Dust 2 Collection', 'skin') for w in WEARS]
    rows += [('Revolution Case', 'Revolution Case', 'case'), ('Revolver Case', 'Revolver Case', 'case')]
    conn.executemany("INSERT INTO items (name, collection, item_type) VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return ItemMatcher(db)


class TestMatching:
    def test_ocr_text_with_a_wear_matches_the_skin(self, db_matcher):
        result = db_matcher.match_with_confidence('Sawed-Off | Forest DDPAT (Field-Tested)')

        assert result['status'] == 'matched'
        assert result['best_match']['base_name'] == 'Sawed-Off | Forest DDPAT'
        assert result['confidence'] == 'high'
        assert len(result['all_wear_variations']) == 5

    def test_every_wear_variant_normalises_identically(self, db_matcher):
        items = db_matcher.load_items_cache()
        sawed = {item['normalized'] for item in items if item['name'].startswith('Sawed-Off')}

        assert sawed == {'sawed off forest ddpat'}

    def test_similar_case_names_are_told_apart(self, db_matcher):
        assert db_matcher.match_with_confidence('Revolution Case')['best_match']['name'] == 'Revolution Case'
        assert db_matcher.match_with_confidence('Revolver Case')['best_match']['name'] == 'Revolver Case'

    def test_unrelated_text_does_not_match(self, db_matcher):
        assert db_matcher.match_with_confidence('zzzz qqqq')['status'] == 'no_match'


class TestCacheRefresh:
    def test_new_prices_are_picked_up_without_a_restart(self, db_matcher):
        """The cache used to live for the whole process, so the daily price
        job's writes never reached the recommendations."""
        assert db_matcher.match_with_confidence('Revolution Case')['best_match']['price'] is None

        conn = sqlite3.connect(db_matcher.db_path)
        conn.execute("UPDATE items SET price = 0.55 WHERE name = 'Revolution Case'")
        conn.commit()
        conn.close()
        # Make sure the change is visible even on filesystems with coarse mtimes.
        import os
        stat = os.stat(db_matcher.db_path)
        os.utime(db_matcher.db_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

        assert db_matcher.match_with_confidence('Revolution Case')['best_match']['price'] == 0.55

    def test_unchanged_database_is_not_reloaded(self, db_matcher):
        first = db_matcher.load_items_cache()

        assert db_matcher.load_items_cache() is first

    def test_missing_item_table_gives_a_clear_error(self, tmp_path):
        from Src.ImageDetector.item_matcher import ItemDatabaseNotReady

        db = str(tmp_path / 'app_only.db')
        sqlite3.connect(db).execute("CREATE TABLE users (id INTEGER PRIMARY KEY)").connection.close()

        with pytest.raises(ItemDatabaseNotReady, match='Build the item database'):
            ItemMatcher(db).match_with_confidence('Revolution Case')

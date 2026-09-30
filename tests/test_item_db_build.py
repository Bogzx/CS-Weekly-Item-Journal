"""Build the item database from a fresh clone, offline.

Runs the real setup steps -- fetch_item_lists.py (against committed ByMykel
fixtures instead of the network), create_database.py and populate_database.py
-- and checks that the result is priceable by bulk_scraper.py and matchable by
the ItemMatcher. This is the path that was completely blocked while the skin
list came from counterstrike.fandom.com (HTTP 403).
"""

import csv
import os
import sqlite3

import pytest

from Src.DB import bulk_scraper, create_database, fetch_item_lists, populate_database
from Src.ImageDetector.item_matcher import ItemMatcher

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'bymykel')


def read_csv(path):
    with open(path, encoding='utf-8') as f:
        return list(csv.DictReader(f))


@pytest.fixture
def source():
    return fetch_item_lists.load_source(FIXTURES)


class TestItemLists:
    def test_skins_keep_only_the_wears_they_come_in(self, source):
        rows = {f"{r['Weapon']} | {r['Skin']}": r for r in fetch_item_lists.skin_rows(source['skins.json'])}

        assert rows['Sawed-Off | Forest DDPAT']['Wears'] == (
            'Factory New;Minimal Wear;Field-Tested;Well-Worn;Battle-Scarred')
        assert rows['AUG | Anodized Navy']['Wears'] == 'Factory New;Minimal Wear'
        assert rows['Sawed-Off | Forest DDPAT']['Collection'] == 'The Bank Collection'

    def test_doppler_phases_collapse_to_one_market_name(self, source):
        rows = fetch_item_lists.skin_rows(source['skins.json'])

        names = [f"{r['Weapon']} | {r['Skin']}" for r in rows]
        assert names.count('Glock-18 | Gamma Doppler') == 1

    def test_knives_and_gloves_are_opt_in(self, source):
        default = fetch_item_lists.skin_rows(source['skins.json'])
        assert not any(r['Weapon'].startswith('★') for r in default)

        full = fetch_item_lists.skin_rows(source['skins.json'], include_knives_and_gloves=True)
        weapons = {r['Weapon'] for r in full}
        assert '★ Butterfly Knife' in weapons
        # A vanilla knife has no finish and no wear, so it is never a skin row.
        assert not any(r['Skin'] == '' for r in full)
        bayonet = next(r for r in full if r['Weapon'] == '★ Bayonet')
        assert bayonet['Wears'] == 'Well-Worn;Battle-Scarred'

    def test_price_url_uses_the_market_hash_name(self, source):
        row = next(r for r in fetch_item_lists.skin_rows(source['skins.json'])
                   if r['Skin'] == 'Anodized Navy')

        assert row['Steam Market API URL'].endswith(
            'market_hash_name=AUG%20%7C%20Anodized%20Navy%20%28Factory%20New%29')

    def test_weapon_cases_and_sticker_capsules_are_listed(self, source):
        """Souvenir packages and the gift package are not drop items."""
        rows = fetch_item_lists.case_rows(source['crates.json'])

        assert [r['Case'] for r in rows] == ['Revolution Case', 'Kilowatt Case', 'Sticker Capsule']

    def test_only_drop_tools_are_listed_under_their_drop_name(self, source):
        rows = fetch_item_lists.tool_rows(source['tools.json'])

        assert rows == [{'Name': 'Charm Detachment Pack', 'Source ID': 'tool-4', 'Tradable': '0'}]

    def test_missing_drop_tool_is_skipped_not_fatal(self, capsys):
        assert fetch_item_lists.tool_rows([{'id': 'tool-1', 'name': 'Name Tag'}]) == []
        assert 'tool-4' in capsys.readouterr().out

    def test_graffiti_needs_a_market_name(self, source):
        rows = fetch_item_lists.graffiti_rows(source['graffiti.json'])

        assert [r['FullName'] for r in rows] == [
            'Sealed Graffiti | Sorry (Tiger Orange)',
            'Sealed Graffiti | Sorry (Shark White)',
        ]
        assert rows[0]['Name'] == 'Sorry (Tiger Orange)'


class TestFetchCli:
    def test_writes_all_four_csvs(self, tmp_path):
        assert fetch_item_lists.main(['--source-dir', FIXTURES, '--out-dir', str(tmp_path)]) == 0

        assert len(read_csv(tmp_path / 'cs_skins.csv')) == 3
        assert len(read_csv(tmp_path / 'cs_cases.csv')) == 3
        assert len(read_csv(tmp_path / 'cs_graffiti.csv')) == 2
        assert len(read_csv(tmp_path / 'cs_tools.csv')) == 1
        assert not list(tmp_path.glob('*.tmp'))

    def test_empty_source_leaves_existing_csvs_alone(self, tmp_path):
        src = tmp_path / 'src'
        src.mkdir()
        for name in fetch_item_lists.SOURCE_FILES:
            (src / name).write_text('[]')
        out = tmp_path / 'out'
        out.mkdir()
        (out / 'cs_skins.csv').write_text('keep me')

        assert fetch_item_lists.main(['--source-dir', str(src), '--out-dir', str(out)]) == 1
        assert (out / 'cs_skins.csv').read_text() == 'keep me'

    def test_http_error_is_reported_not_written(self, tmp_path, monkeypatch):
        class Response:
            status_code = 403

        requested = []

        def fake_get(url, timeout):
            requested.append(url)
            return Response()

        monkeypatch.setattr(fetch_item_lists.requests, 'get', fake_get)

        assert fetch_item_lists.main(['--out-dir', str(tmp_path), '--ref', 'abc123']) == 1
        assert requested == [
            'https://raw.githubusercontent.com/ByMykel/CSGO-API/abc123/public/api/en/skins.json']
        assert not list(tmp_path.iterdir())

    def test_downloads_every_file_from_the_ref(self, tmp_path, monkeypatch):
        import json

        class Response:
            status_code = 200

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        def fake_get(url, timeout):
            name = url.rsplit('/', 1)[1]
            with open(os.path.join(FIXTURES, name), encoding='utf-8') as f:
                return Response(json.load(f))

        monkeypatch.setattr(fetch_item_lists.requests, 'get', fake_get)

        assert fetch_item_lists.main(['--out-dir', str(tmp_path)]) == 0
        assert (tmp_path / 'cs_cases.csv').exists()


@pytest.fixture
def built_db(tmp_path):
    """Run the README setup steps end to end against the fixtures."""
    assert fetch_item_lists.main(['--source-dir', FIXTURES, '--out-dir', str(tmp_path)]) == 0
    db = str(tmp_path / 'items.db')
    assert create_database.create_csgo_database(db) is True
    assert populate_database.main([
        '--db', db,
        '--skins', str(tmp_path / 'cs_skins.csv'),
        '--cases', str(tmp_path / 'cs_cases.csv'),
        '--graffiti', str(tmp_path / 'cs_graffiti.csv'),
        '--tools', str(tmp_path / 'cs_tools.csv'),
    ]) == 0
    return db


def item_names(db):
    conn = sqlite3.connect(db)
    try:
        return {r[0]: r[1] for r in conn.execute("SELECT name, item_type FROM items")}
    finally:
        conn.close()


class TestEndToEnd:
    def test_database_holds_every_item_once(self, built_db):
        items = item_names(built_db)

        assert items['Revolution Case'] == 'case'
        assert items['Sealed Graffiti | Sorry (Tiger Orange)'] == 'graffiti'
        assert items['Sawed-Off | Forest DDPAT (Battle-Scarred)'] == 'skin'
        assert items['AUG | Anodized Navy (Minimal Wear)'] == 'skin'
        assert items['Sticker Capsule'] == 'case'
        assert items['Charm Detachment Pack'] == 'tool'
        # 5 + 2 + 5 skin rows, 2 cases + 1 capsule, 2 graffiti, 1 tool
        assert len(items) == 18

    def test_wears_a_skin_does_not_come_in_are_not_created(self, built_db):
        assert 'AUG | Anodized Navy (Field-Tested)' not in item_names(built_db)

    def test_item_names_are_what_the_price_scraper_matches_on(self, built_db):
        prices = {
            'Revolution Case': {'price': 0.55, 'price_type': 'lowest', 'listings': 1},
            'Sawed-Off | Forest DDPAT (Field-Tested)': {'price': 0.03, 'price_type': 'lowest', 'listings': 1},
            'Sealed Graffiti | Sorry (Tiger Orange)': {'price': 0.04, 'price_type': 'lowest', 'listings': 1},
        }

        assert bulk_scraper.update_database_prices(built_db, prices) == 3

    def test_matcher_finds_the_drop_and_its_wears(self, built_db):
        result = ItemMatcher(built_db).match_with_confidence('Sawed-Off | Forest DDPAT')

        assert result['status'] == 'matched'
        assert result['best_match']['name'].startswith('Sawed-Off | Forest DDPAT')
        assert len(result['all_wear_variations']) == 5

    def test_populate_is_idempotent(self, built_db, tmp_path):
        before = item_names(built_db)
        assert populate_database.main([
            '--db', built_db,
            '--skins', str(tmp_path / 'cs_skins.csv'),
            '--cases', str(tmp_path / 'cs_cases.csv'),
            '--graffiti', str(tmp_path / 'cs_graffiti.csv'),
            '--tools', str(tmp_path / 'cs_tools.csv'),
        ]) == 0
        assert item_names(built_db) == before


def test_old_csv_without_wears_column_still_gets_all_five():
    assert populate_database.skin_wears({'Weapon': 'AK-47', 'Skin': 'Redline'}) == (
        populate_database.WEAR_QUALITIES)


def test_verify_database_reports_the_built_db(built_db, capsys):
    from Src.DB import verify_database

    assert verify_database.verify_database(built_db) is True
    assert 'Row count: 18' in capsys.readouterr().out


def test_verify_database_fails_for_a_missing_file(tmp_path):
    from Src.DB import verify_database

    assert verify_database.verify_database(str(tmp_path / 'nope.db')) is False


class TestNonTradableTools:
    def row(self, db, name):
        conn = sqlite3.connect(db)
        try:
            return conn.execute("SELECT price, price_type, tradable, item_type FROM items WHERE name = ?",
                                (name,)).fetchone()
        finally:
            conn.close()

    def test_tool_is_stored_as_not_tradable_and_worth_nothing(self, built_db):
        assert self.row(built_db, 'Charm Detachment Pack') == (0.0, 'not_tradable', 0, 'tool')
        assert self.row(built_db, 'Revolution Case')[2] == 1

    def test_price_scraper_leaves_the_tool_alone(self, built_db):
        bulk_scraper.update_database_prices(
            built_db, {'Revolution Case': {'price': 0.5, 'price_type': 'lowest', 'listings': 1}})

        assert self.row(built_db, 'Charm Detachment Pack')[:2] == (0.0, 'not_tradable')

    def test_ocr_text_matches_the_tool(self, built_db):
        for text in ('Charm Detachment Pack', 'rharm Detachmont Pack'):
            result = ItemMatcher(built_db).match_with_confidence(text)
            assert result['best_match']['name'] == 'Charm Detachment Pack', text

    def test_database_from_before_the_flag_is_upgraded(self, tmp_path):
        db = str(tmp_path / 'old.db')
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
                     "collection TEXT, market_api_url TEXT NOT NULL, price REAL, price_type TEXT, "
                     "last_updated TIMESTAMP, item_type TEXT, UNIQUE(name, collection))")
        conn.execute("CREATE TABLE collections (id INTEGER PRIMARY KEY, name TEXT UNIQUE)")
        conn.commit()
        conn.close()
        assert fetch_item_lists.main(['--source-dir', FIXTURES, '--out-dir', str(tmp_path)]) == 0

        assert populate_database.main(['--db', db, '--skins', str(tmp_path / 'cs_skins.csv'),
                                       '--cases', str(tmp_path / 'cs_cases.csv'),
                                       '--graffiti', str(tmp_path / 'cs_graffiti.csv'),
                                       '--tools', str(tmp_path / 'cs_tools.csv')]) == 0
        assert self.row(db, 'Charm Detachment Pack')[2] == 0


@pytest.fixture(scope='module')
def container_matcher(tmp_path_factory):
    """Every weapon case and sticker capsule ByMykel lists, as the DB holds them."""
    import json

    with open(os.path.join(FIXTURES, 'containers.json'), encoding='utf-8') as f:
        rows = fetch_item_lists.case_rows(json.load(f))
    db = str(tmp_path_factory.mktemp('containers') / 'items.db')
    create_database.create_csgo_database(db)
    conn = sqlite3.connect(db)
    populate_database.populate_cases(conn, rows)
    conn.close()
    return ItemMatcher(db), [r['Case'] for r in rows]


class TestCapsuleCollisions:
    def test_counts(self, container_matcher):
        _, names = container_matcher
        assert len(names) == 42 + 91

    def test_every_case_and_capsule_matches_itself(self, container_matcher):
        """91 capsules include near-twins ('Sticker Capsule' / 'Sticker
        Capsule 2', Legends/Challengers/Contenders triples)."""
        matcher, names = container_matcher
        wrong = {}
        for name in names:
            result = matcher.match_with_confidence(name, item_type=matcher.detect_item_type(name))
            if result['best_match']['name'] != name or result['confidence'] != 'high':
                wrong[name] = (result['best_match']['name'], round(result['score'], 3))
        assert not wrong

    @pytest.mark.parametrize('ocr,expected', [
        # Case OCR from the labelled Training_Images (round 3)
        ('Revolution Cose', 'Revolution Case'),
        ('Revolution Caao', 'Revolution Case'),
        ('Recdii Case', 'Recoil Case'),
        ('Rccoil Cato', 'Recoil Case'),
        ('RevosJlion Coso', 'Revolution Case'),
        ('Fracture Cose', 'Fracture Case'),
        ('cS:G0 Weapon Cose', 'CS:GO Weapon Case'),
        ('Dreams & Nightrare s Cese', 'Dreams & Nightmares Case'),
        ('Dronms 8 Nighunaros Caza', 'Dreams & Nightmares Case'),
        ('Snakebite Cose', 'Snakebite Case'),
        # and capsules read with typical slips
        ('Sticker Capsule 2', 'Sticker Capsule 2'),
        ('Sticker Capsu1e', 'Sticker Capsule'),
        ('Copenhagen 2024 Legends Sticker Capsule', 'Copenhagen 2024 Legends Sticker Capsule'),
    ])
    def test_ocr_of_cases_is_not_captured_by_a_capsule(self, container_matcher, ocr, expected):
        matcher, _ = container_matcher
        result = matcher.match_with_confidence(ocr, item_type=matcher.detect_item_type(ocr))

        assert result['best_match']['name'] == expected

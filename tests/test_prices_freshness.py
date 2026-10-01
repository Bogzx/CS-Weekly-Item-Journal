"""What the results page says about prices: their age and the seller's cut."""

import io
import sqlite3
from datetime import datetime, timedelta

import pytest
from PIL import Image

from Src.Web import valuation


class TestSellerProceeds:
    @pytest.mark.parametrize('price, received', [
        (1.00, 0.88),   # 0.88 + 0.04 Steam + 0.08 game = 1.00
        (0.26, 0.23),   # 0.23 + 0.01 + 0.02
        (1.15, 1.00),   # 1.00 + 0.05 + 0.10
        (10.00, 8.70),
        (0.03, 0.01),   # both fees have a 1-cent minimum
        (0.02, 0.0),    # cannot cover the minimum fees
        (0.0, 0.0),
    ])
    def test_matches_steams_fee_schedule(self, price, received):
        assert valuation.seller_proceeds(price) == pytest.approx(received)

    @pytest.mark.parametrize('price', [None, '', 'N/A', -1])
    def test_no_price(self, price):
        assert valuation.seller_proceeds(price) is None

    def test_price_plus_fees_never_exceeds_the_listing(self):
        for cents in range(3, 2000):
            received = round(valuation.seller_proceeds(cents / 100) * 100)
            assert received + valuation._fees_cents(received) <= cents
            assert received + 1 + valuation._fees_cents(received + 1) > cents


def make_items_db(path, rows):
    """An items table with (name, price, tradable, last_updated) rows."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, price REAL, "
                 "tradable INTEGER NOT NULL DEFAULT 1, last_updated TIMESTAMP)")
    conn.executemany("INSERT INTO items (name, price, tradable, last_updated) VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def stamp(hours_ago):
    return (datetime.now() - timedelta(hours=hours_ago)).isoformat(sep=' ')


@pytest.fixture
def items_db(appmod, tmp_path, monkeypatch):
    path = str(tmp_path / 'items.db')
    monkeypatch.setitem(appmod.app.config, 'DATABASE', path)
    return path


class TestPriceFreshness:
    def freshness(self, appmod, hours=48):
        from Src.Web.db import price_freshness

        with appmod.app.app_context():
            return price_freshness(hours)

    def test_reports_newest_and_oldest_fetch(self, appmod, items_db):
        make_items_db(items_db, [('A', 0.5, 1, stamp(30)), ('B', 0.2, 1, stamp(5)), ('C', None, 1, None)])

        info = self.freshness(appmod)

        assert info['priced_items'] == 2
        assert 4.9 < info['newest_age_hours'] < 5.1
        assert 29.9 < info['oldest_age_hours'] < 30.1
        assert info['newest_at'] > info['oldest_at']
        assert info['stale'] is False

    def test_stale_follows_the_newest_price(self, appmod, items_db):
        """One old leftover price is not a stopped crawl; no new price at all is."""
        make_items_db(items_db, [('A', 0.5, 1, stamp(500)), ('B', 0.2, 1, stamp(2))])

        assert self.freshness(appmod)['stale'] is False

    def test_old_prices_are_stale(self, appmod, items_db):
        make_items_db(items_db, [('A', 0.5, 1, stamp(72))])

        assert self.freshness(appmod)['stale'] is True
        assert self.freshness(appmod, hours=100)['stale'] is False

    def test_non_tradable_items_do_not_count(self, appmod, items_db):
        """Their $0 is written when the database is built, not by a crawl."""
        make_items_db(items_db, [('Charm Detachment Pack', 0.0, 0, stamp(0)), ('A', None, 1, None)])

        assert self.freshness(appmod) is None

    def test_database_without_items(self, appmod, items_db):
        sqlite3.connect(items_db).close()

        assert self.freshness(appmod) is None


def upload(client):
    buf = io.BytesIO()
    Image.new('RGB', (4, 4)).save(buf, format='PNG')
    buf.seek(0)
    return client.post('/upload', data={'file': (buf, 'shot.png')}, content_type='multipart/form-data')


def priced_slot(name, price):
    return {'original': name, 'cleaned': name, 'status': 'found',
            'matches': [{'id': 1, 'name': name, 'price': price, 'confidence': 'high',
                         'score': 1.0, 'tradable': True}]}


class TestResultsPage:
    @pytest.fixture
    def stub_pipeline(self, appmod, monkeypatch):
        slots = [priced_slot('Revolution Case', 0.26), priced_slot('Recoil Case', 1.00),
                 priced_slot('Fracture Case', 0.10), priced_slot('Dreams Case', 0.05)]
        monkeypatch.setattr(appmod, 'process_image', lambda path: ['a', 'b', 'c', 'd'])
        monkeypatch.setattr(appmod, 'match_items_in_database', lambda names: slots)

    def test_shows_price_age_and_what_a_seller_gets(self, appmod, logged_in, stub_pipeline, monkeypatch):
        monkeypatch.setattr(appmod, 'price_freshness', lambda hours: {
            'newest_at': datetime(2026, 10, 1, 12, 28), 'oldest_at': datetime(2026, 9, 29, 0, 5),
            'newest_age_hours': 3.0, 'oldest_age_hours': 63.0, 'stale': False, 'priced_items': 42})

        html = ' '.join(upload(logged_in).get_data(as_text=True).split())

        assert ('Steam prices for 42 items: the newest was fetched 2026-10-01 12:28, '
                'the oldest 2026-09-29 00:05 (server time).') in html
        assert 'you would get $0.88 selling it' in html   # Recoil Case at $1.00
        assert 'you would get $0.23 selling it' in html   # Revolution Case at $0.26
        assert 'price-stale' not in html

    def test_warns_when_prices_are_stale(self, appmod, logged_in, stub_pipeline, monkeypatch):
        monkeypatch.setattr(appmod, 'price_freshness', lambda hours: {
            'newest_at': datetime(2026, 9, 25, 0, 0), 'oldest_at': datetime(2026, 9, 20, 0, 0),
            'newest_age_hours': 24 * 6.5, 'oldest_age_hours': 24 * 11.5, 'stale': True, 'priced_items': 42})

        html = ' '.join(upload(logged_in).get_data(as_text=True).split())

        assert 'Even the newest price is 6.5 days old' in html
        assert 'PRICE_STALE_HOURS' in html

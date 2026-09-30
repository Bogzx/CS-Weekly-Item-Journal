"""Tests for the Steam Market bulk price scraper.

No test here touches the network: requests.get and time.sleep are patched.
The fake Steam below mimics what the live search/render endpoint did when this
was written (2026-09-30): it ignores `count` above 10 and reports
`pagesize: 10`, and it reads the search term from `query`, not `q`.
"""

import sqlite3
import urllib.parse

import pytest

from Src.DB import bulk_scraper


def params_of(url):
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=''):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text or repr(payload)

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def market_page(start, names):
    return {
        'success': True,
        'start': start,
        'pagesize': 10,
        'total_count': 999,
        'results': [
            {'hash_name': n, 'sell_price': 100 + i, 'sell_listings': 5}
            for i, n in enumerate(names)
        ],
    }


class FakeSteam:
    """A market of `total` items that returns at most 10 per page."""

    def __init__(self, total):
        self.names = [f'Item {i:05d}' for i in range(total)]
        self.requested_starts = []

    def get(self, url, headers=None, timeout=None):
        p = params_of(url)
        start, count = int(p['start'][0]), int(p['count'][0])
        page = self.names[start:start + min(count, 10)]
        if count == 1:  # get_total_item_count probe
            return FakeResponse(payload={**market_page(0, page), 'total_count': len(self.names)})
        self.requested_starts.append(start)
        return FakeResponse(payload=market_page(start, page))


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(bulk_scraper.time, 'sleep', sleeps.append)
    return sleeps


class TestBuildSteamMarketUrl:
    def test_search_term_uses_query_param(self):
        url = bulk_scraper.build_steam_market_url(query='Revolution Case')

        params = params_of(url)
        assert params['query'] == ['Revolution Case']
        assert 'q' not in params

    def test_list_filter_keeps_every_value(self):
        url = bulk_scraper.build_steam_market_url(
            filters={'category_730_Type': ['tag_CSGO_Type_Pistol', 'tag_CSGO_Type_Rifle']}
        )

        assert params_of(url)['category_730_Type[]'] == [
            'tag_CSGO_Type_Pistol', 'tag_CSGO_Type_Rifle',
        ]

    def test_scalar_filter(self):
        url = bulk_scraper.build_steam_market_url(filters={'category_730_Exterior': 'tag_WearCategory0'})

        assert params_of(url)['category_730_Exterior[]'] == ['tag_WearCategory0']

    def test_pagination_and_app_id(self):
        params = params_of(bulk_scraper.build_steam_market_url(start=40, count=10))

        assert params['appid'] == ['730']
        assert params['norender'] == ['1']
        assert params['start'] == ['40']
        assert params['count'] == ['10']


class TestParsePriceResults:
    def test_converts_cents_to_currency_units(self):
        data = bulk_scraper.parse_price_results(
            [{'hash_name': 'Revolution Case', 'sell_price': 123, 'sell_listings': 7}]
        )

        assert data == {'Revolution Case': {'price': 1.23, 'price_type': 'lowest', 'listings': 7}}

    def test_skips_items_without_a_listing_price(self):
        data = bulk_scraper.parse_price_results([
            {'hash_name': 'No listings', 'sell_price': 0},
            {'hash_name': 'Missing price'},
            {'sell_price': 5},
        ])

        assert data == {}

    def test_tolerates_none(self):
        assert bulk_scraper.parse_price_results(None) == {}


class TestFetchAllPrices:
    def test_paginates_by_what_steam_returned_not_by_batch_size(self, monkeypatch, no_sleep):
        """Steam returns 10 per page; stepping by 100 used to skip 90% of items."""
        steam = FakeSteam(total=35)
        monkeypatch.setattr(bulk_scraper.requests, 'get', steam.get)

        prices, complete = bulk_scraper.fetch_all_prices(batch_size=100)

        assert complete is True
        assert steam.requested_starts == [0, 10, 20, 30]
        assert set(prices) == set(steam.names)

    def test_respects_max_items(self, monkeypatch, no_sleep):
        steam = FakeSteam(total=100)
        monkeypatch.setattr(bulk_scraper.requests, 'get', steam.get)

        prices, complete = bulk_scraper.fetch_all_prices(max_items=25, batch_size=100)

        assert complete is True
        assert steam.requested_starts == [0, 10, 20]
        assert len(prices) == 25

    def test_stops_when_a_page_comes_back_empty(self, monkeypatch, no_sleep):
        """total_count can overstate the listing; an empty page ends the crawl."""
        steam = FakeSteam(total=12)
        monkeypatch.setattr(bulk_scraper, 'get_total_item_count', lambda *a: 10000)
        monkeypatch.setattr(bulk_scraper.requests, 'get', steam.get)

        prices, complete = bulk_scraper.fetch_all_prices()

        assert complete is True
        assert steam.requested_starts == [0, 10, 12]
        assert len(prices) == 12

    def test_persistent_rate_limit_stops_and_keeps_partial_data(self, monkeypatch, no_sleep):
        steam = FakeSteam(total=50)

        def get(url, **kwargs):
            if int(params_of(url)['start'][0]) >= 20:
                return FakeResponse(status_code=429)
            return steam.get(url, **kwargs)

        monkeypatch.setattr(bulk_scraper.requests, 'get', get)

        prices, complete = bulk_scraper.fetch_all_prices()

        assert complete is False
        assert len(prices) == 20

    def test_rate_limit_backs_off_exponentially(self, monkeypatch, no_sleep):
        monkeypatch.setattr(bulk_scraper.requests, 'get', lambda url, **kw: FakeResponse(status_code=429))

        with pytest.raises(bulk_scraper.SteamRateLimited):
            bulk_scraper.fetch_prices_in_bulk(0, 10, retries=3)

        base = bulk_scraper.RATE_LIMIT_BACKOFF
        assert no_sleep == [base, base * 2]

    def test_rate_limit_honours_longer_retry_after(self, monkeypatch, no_sleep):
        responses = iter([
            FakeResponse(status_code=429, headers={'Retry-After': '600'}),
            FakeResponse(payload=market_page(0, ['A'])),
        ])
        monkeypatch.setattr(bulk_scraper.requests, 'get', lambda url, **kw: next(responses))

        prices, returned = bulk_scraper.fetch_prices_in_bulk(0, 10)

        assert no_sleep == [600.0]
        assert returned == 1
        assert 'A' in prices

    def test_null_body_is_retried_not_treated_as_end_of_listing(self, monkeypatch, no_sleep):
        """Steam answers some throttled requests with 200 and `null`."""
        responses = iter([
            FakeResponse(payload=None, text='null'),
            FakeResponse(payload=market_page(0, ['A', 'B'])),
        ])
        monkeypatch.setattr(bulk_scraper.requests, 'get', lambda url, **kw: next(responses))

        prices, returned = bulk_scraper.fetch_prices_in_bulk(0, 10)

        assert returned == 2
        assert set(prices) == {'A', 'B'}

    def test_non_json_body_raises_after_retries(self, monkeypatch, no_sleep):
        monkeypatch.setattr(
            bulk_scraper.requests, 'get',
            lambda url, **kw: FakeResponse(payload=ValueError('not json'), text='<html>'),
        )

        with pytest.raises(bulk_scraper.SteamFetchError):
            bulk_scraper.fetch_prices_in_bulk(0, 10, retries=2)


class TestUpdateDatabasePrices:
    @pytest.fixture
    def db(self, tmp_path):
        path = str(tmp_path / 'items.db')
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, collection TEXT, "
            "market_api_url TEXT, price REAL, last_updated TIMESTAMP, item_type TEXT)"
        )
        conn.executemany(
            "INSERT INTO items (name, collection, market_api_url) VALUES (?, ?, '')",
            [
                ('Revolution Case', 'Revolution Case'),
                ('AK-47 | Redline (Field-Tested)', 'The Phoenix Collection'),
                ('Not On Market', 'Nowhere'),
            ],
        )
        conn.commit()
        conn.close()
        return path

    def test_updates_matching_rows_by_market_hash_name(self, db):
        updated = bulk_scraper.update_database_prices(db, {
            'Revolution Case': {'price': 0.45, 'price_type': 'lowest', 'listings': 1},
            'AK-47 | Redline (Field-Tested)': {'price': 30.0, 'price_type': 'lowest', 'listings': 1},
            'Something Else': {'price': 9.0, 'price_type': 'lowest', 'listings': 1},
        })

        rows = dict(sqlite3.connect(db).execute("SELECT name, price FROM items").fetchall())
        assert updated == 2
        assert rows == {
            'Revolution Case': 0.45,
            'AK-47 | Redline (Field-Tested)': 30.0,
            'Not On Market': None,
        }

    def test_collection_filter(self, db):
        updated = bulk_scraper.update_database_prices(
            db,
            {
                'Revolution Case': {'price': 0.45, 'price_type': 'lowest', 'listings': 1},
                'AK-47 | Redline (Field-Tested)': {'price': 30.0, 'price_type': 'lowest', 'listings': 1},
            },
            collection_filter=['Revolution Case'],
        )

        assert updated == 1


def test_missing_database_exits_non_zero(monkeypatch, tmp_path):
    monkeypatch.setattr('sys.argv', ['bulk_scraper.py', '--db', str(tmp_path / 'nope.db')])

    assert bulk_scraper.main() == 1

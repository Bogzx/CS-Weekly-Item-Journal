"""Pure helpers used by the single-item and graffiti scrapers."""

import pytest

from Src.DB import graffiti_scraper, update_price


class TestParseSteamPrice:
    @pytest.mark.parametrize('raw,expected', [
        ('$0.03', 0.03),
        ('$1.23', 1.23),
        ('$1,234.56', 1234.56),
        ('$12', 12.0),
        ('$ 4.50', 4.50),
        ('$0.45 USD', 0.45),
    ])
    def test_usd_amounts(self, raw, expected):
        assert update_price.parse_steam_price(raw) == pytest.approx(expected)

    @pytest.mark.parametrize('raw', [
        None, '', 'N/A', '1,23€', '£1.00', '12.00 pуб.', '$1,23', '$',
    ])
    def test_anything_else_is_refused_not_misread(self, raw):
        assert update_price.parse_steam_price(raw) is None


class TestFetchPrice:
    class Resp:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code
            self.text = str(payload)

        def json(self):
            return self._payload

    @pytest.fixture(autouse=True)
    def no_sleep(self, monkeypatch):
        monkeypatch.setattr(update_price.time, 'sleep', lambda s: None)

    def test_prefers_lowest_price(self, monkeypatch):
        payload = {'success': True, 'lowest_price': '$0.50', 'median_price': '$0.40'}
        monkeypatch.setattr(update_price.requests, 'get', lambda *a, **k: self.Resp(payload))

        assert update_price.fetch_price('url') == (0.50, 'lowest')

    def test_falls_back_to_median(self, monkeypatch):
        payload = {'success': True, 'median_price': '$0.40'}
        monkeypatch.setattr(update_price.requests, 'get', lambda *a, **k: self.Resp(payload))

        assert update_price.fetch_price('url') == (0.40, 'median')

    def test_unparseable_prices_give_none(self, monkeypatch):
        payload = {'success': True, 'lowest_price': '1,23€'}
        monkeypatch.setattr(update_price.requests, 'get', lambda *a, **k: self.Resp(payload))

        assert update_price.fetch_price('url') == (None, None)

    def test_null_body_gives_none(self, monkeypatch):
        monkeypatch.setattr(update_price.requests, 'get', lambda *a, **k: self.Resp(None))

        assert update_price.fetch_price('url') == (None, None)


class TestGraffitiNames:
    def test_sealed_graffiti_prefix_is_stripped(self):
        collection, name = graffiti_scraper.extract_graffiti_name_parts(
            'Sealed Graffiti | Sorry (Tracer Yellow)'
        )

        assert collection == 'Default Graffiti Collection'
        assert name == 'Sorry (Tracer Yellow)'

    def test_price_url_encodes_the_hash_name(self):
        url = graffiti_scraper.create_price_api_url('Sealed Graffiti | Sorry (Tracer Yellow)')

        assert url.endswith('market_hash_name=Sealed%20Graffiti%20%7C%20Sorry%20%28Tracer%20Yellow%29')
        assert 'appid=730' in url

"""graffiti_scraper.py pagination against a fake Steam that serves 10 per page."""

from Src.DB import graffiti_scraper

TOTAL = 35


def fake_page(start, count):
    end = min(start + min(count, 10), TOTAL)
    return [{'hash_name': f'Sealed Graffiti | Tag {i:02d} (Shark White)'} for i in range(start, end)]


def test_every_graffiti_is_fetched_despite_the_10_item_page_cap(monkeypatch):
    requested = []

    def fetch(start, count):
        requested.append(start)
        return fake_page(start, count)

    monkeypatch.setattr(graffiti_scraper, 'get_total_graffiti_count', lambda: TOTAL)
    monkeypatch.setattr(graffiti_scraper, 'fetch_graffiti_items', fetch)

    items = graffiti_scraper.fetch_all_graffiti(delay=0)

    assert len(items) == TOTAL
    assert requested == [0, 10, 20, 30]


def test_stops_on_an_empty_page_instead_of_hammering(monkeypatch):
    requested = []

    def fetch(start, count):
        requested.append(start)
        return fake_page(start, count) if start == 0 else []

    monkeypatch.setattr(graffiti_scraper, 'get_total_graffiti_count', lambda: TOTAL)
    monkeypatch.setattr(graffiti_scraper, 'fetch_graffiti_items', fetch)

    items = graffiti_scraper.fetch_all_graffiti(delay=0)

    assert len(items) == 10
    assert requested == [0, 10]


def test_max_items_caps_the_crawl(monkeypatch):
    monkeypatch.setattr(graffiti_scraper, 'get_total_graffiti_count', lambda: TOTAL)
    monkeypatch.setattr(graffiti_scraper, 'fetch_graffiti_items', fake_page)

    assert len(graffiti_scraper.fetch_all_graffiti(max_items=15, delay=0)) == 15

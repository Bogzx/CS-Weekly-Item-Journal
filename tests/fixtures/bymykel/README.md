Trimmed excerpts of `public/api/en/{skins,crates,graffiti,tools}.json` from
[ByMykel/CSGO-API](https://github.com/ByMykel/CSGO-API) (MIT License,
Copyright (c) 2023 ByMykel), commit `cee33b1c`, 2026-09-30. Images,
descriptions and most fields are removed; only what `fetch_item_lists.py` reads
is kept.

The entries were picked for their edge cases: a skin in all five wears, one in
Factory New/Minimal Wear only, a duplicated Doppler name, knives (with and
without a finish), an entry with no `wears` key, non-case crates, and a graffiti
with no market name.

`tools.json` is the complete tool list (6 entries), trimmed to id/name/def_index.
`containers.json` holds every weapon case and sticker capsule from `crates.json`
(142 entries, id/name/type/market name only); `tests/test_item_db_build.py`
uses it to check that the 91 marketable capsules do not collide with cases.

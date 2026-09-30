Trimmed excerpts of `public/api/en/{skins,crates,graffiti}.json` from
[ByMykel/CSGO-API](https://github.com/ByMykel/CSGO-API) (MIT License,
Copyright (c) 2023 ByMykel), commit `cee33b1c`, 2026-09-30. Images,
descriptions and most fields are removed; only what `fetch_item_lists.py` reads
is kept.

The entries were picked for their edge cases: a skin in all five wears, one in
Factory New/Minimal Wear only, a duplicated Doppler name, knives (with and
without a finish), an entry with no `wears` key, non-case crates, and a graffiti
with no market name.

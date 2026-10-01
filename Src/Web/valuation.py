"""What each drop slot is worth, and which two of the four to claim."""

import logging
import re

logger = logging.getLogger(__name__)

# Skin wears, best first. The care-package screen does not show which one
# you would get.
WEAR_NAMES = ("Factory New", "Minimal Wear", "Field-Tested", "Well-Worn", "Battle-Scarred")

# How a slot is valued when its exact item is unknown (a skin of unknown
# wear). Only the top match's own wear variants are considered; the rule picks
# which of their prices counts. Set with VALUATION_RULE in .env.
#   lowest  - the cheapest wear: a floor on what the drop is worth (default)
#   median  - the middle wear price
#   highest - the priciest wear, usually Factory New (the old behaviour)
VALUATION_RULES = {
    'lowest': 'lowest price',
    'median': 'median price',
    'highest': 'highest price',
}
DEFAULT_VALUATION_RULE = 'lowest'

# The weekly care package lets you claim this many of its four items.
RECOMMENDED_PICKS = 2


def resolve_valuation_rule(raw):
    """Validate VALUATION_RULE, falling back to the conservative default."""
    rule = (raw or DEFAULT_VALUATION_RULE).strip().lower()
    if rule not in VALUATION_RULES:
        logger.warning(
            "Unknown VALUATION_RULE %r; using %r. Valid values: %s",
            raw, DEFAULT_VALUATION_RULE, ', '.join(VALUATION_RULES))
        return DEFAULT_VALUATION_RULE
    return rule


def as_price(value):
    """Coerce a stored price into a float, tolerating None and junk strings.

    Prices arrive from SQLite and from the Steam scrapers, so a column can hold
    a REAL, a string like "1.23", or NULL for an item that has never been
    priced. Anything that is not a usable non-negative number becomes None so
    that it is simply excluded from the comparison rather than crashing it.
    """
    if value is None:
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price < 0:
        return None
    return price


GRAFFITI_PREFIX = 'Sealed Graffiti | '


def base_item_name(name):
    """The item without the variant the drop screen does not reliably show.

    'AK-47 | Redline (Field-Tested)' -> 'AK-47 | Redline' (the screen never
    shows wear) and 'Sealed Graffiti | Sorry (Tiger Orange)' ->
    'Sealed Graffiti | Sorry' (the OCR crop usually cuts the colour off).
    Anything else is returned unchanged.
    """
    name = name or ''
    for wear in WEAR_NAMES:
        suffix = f' ({wear})'
        if name.endswith(suffix):
            return name[:-len(suffix)]
    if name.startswith(GRAFFITI_PREFIX):
        return re.sub(r'\s*\([^()]*\)$', '', name)
    return name


def _pick_by_rule(priced, rule):
    """The candidate a slot is valued at, from a price-sorted list."""
    if rule == 'highest':
        return priced[-1]
    if rule == 'median':
        # Lower median, so the value is always a real candidate's price
        # (statistics.median_low semantics) and it can be pre-selected.
        return priced[(len(priced) - 1) // 2]
    return priced[0]


def annotate_recommendation(item_results, rule=DEFAULT_VALUATION_RULE, picks=RECOMMENDED_PICKS):
    """Value each detected slot and flag the most valuable ones to claim.

    The care-package screen names the item but not a skin's wear, so a skin
    slot matches several items at very different prices. It used to be valued
    at the priciest candidate in its list -- usually Factory New, and
    sometimes a *different item* that merely fuzzy-matched the OCR text -- so
    skins were systematically overvalued against cases and graffiti.

    Now a slot is valued only over its **top match's own variants** (same
    item once the wear -- or a graffiti's colour, when OCR lost it -- is
    stripped; see base_item_name). `rule` decides which of those
    prices counts; see VALUATION_RULES. The full min-max range is kept for
    the template.

    The game lets you claim up to `picks` (2) of the four items, so the
    `picks` highest-valued slots are recommended, each with the candidate the
    value came from pre-selected.

    Sets on every slot: `value`, `value_match`, `price_min`, `price_max`,
    `priced_variants`, `variant_count`, `variant_kind` and `display_name`;
    on every match:
    `price_value`. Recommended slots and their `value_match` also get
    `recommended = True`, and slots get `pick_rank` (1-based). A slot whose
    top match has 'low' confidence is valued but marked `uncertain`, and one
    whose top match cannot be traded is valued at $0 and marked
    `not_tradable`; neither is ever recommended.

    Returns the recommended slots, best first ([] when nothing has a price --
    the common state of a freshly built database).
    """
    valued = []

    for result in item_results:
        matches = result.get('matches') or []
        for match in matches:
            # Keep the parsed value so the template can format it without
            # re-parsing, and so unpriced rows stay visually distinct.
            match['price_value'] = as_price(match.get('price'))

        result.update(value=None, value_match=None, price_min=None, price_max=None,
                      priced_variants=0, variant_count=0, display_name=None,
                      variant_kind='wears')
        if not matches:
            continue

        family_name = base_item_name(matches[0].get('name'))
        family = [m for m in matches if base_item_name(m.get('name')) == family_name]
        priced = sorted((m for m in family if m['price_value'] is not None),
                        key=lambda m: m['price_value'])

        result['display_name'] = family_name
        if family_name.startswith(GRAFFITI_PREFIX):
            result['variant_kind'] = 'colours'
        result['variant_count'] = len(family)
        result['priced_variants'] = len(priced)
        if not priced:
            continue

        chosen = _pick_by_rule(priced, rule)
        result['value_match'] = chosen
        result['value'] = chosen['price_value']
        result['price_min'] = priced[0]['price_value']
        result['price_max'] = priced[-1]['price_value']
        # Non-tradable drops (Charm Detachment Pack) are worth $0 on the
        # market and are never recommended over anything.
        if not matches[0].get('tradable', True):
            result['not_tradable'] = True
            continue
        # A low-confidence top match was the right item only half the time on
        # the labelled screenshots, so it is valued but never recommended.
        if matches[0].get('confidence') == 'low':
            result['uncertain'] = True
            continue
        valued.append(result)

    # sorted() is stable, so equal values keep their on-screen order.
    ranked = sorted(valued, key=lambda r: r['value'], reverse=True)[:picks]
    for rank, result in enumerate(ranked, start=1):
        result['recommended'] = True
        result['pick_rank'] = rank
        result['value_match']['recommended'] = True
    return ranked


# Steam Community Market fees, charged on top of what the seller receives:
# 5% to Steam and 10% to the game (CS2), each rounded down to the cent and at
# least 1 cent. A listing's price is what the buyer pays, so a seller gets
# about 13% less than the price shown here (Steam's own "You receive" figure).
STEAM_FEE = 0.05
GAME_FEE = 0.10


def _fees_cents(received_cents):
    return (max(int(received_cents * STEAM_FEE), 1)
            + max(int(received_cents * GAME_FEE), 1))


def seller_proceeds(price):
    """What a seller receives when an item sells at `price` (USD), after fees.

    The largest amount whose price including both fees is still at most
    `price`; None for no price, 0.0 when the price cannot even cover the
    minimum fees.
    """
    price = as_price(price)
    if price is None:
        return None
    buyer_cents = round(price * 100)
    received = max(0, int(buyer_cents / (1 + STEAM_FEE + GAME_FEE)))
    while received > 0 and received + _fees_cents(received) > buyer_cents:
        received -= 1
    while received + 1 + _fees_cents(received + 1) <= buyer_cents:
        received += 1
    return received / 100

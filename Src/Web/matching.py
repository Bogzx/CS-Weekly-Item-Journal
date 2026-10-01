"""OCR text -> candidate items for each of the four drop slots."""

import re

def clean_item_name(name):
    """Clean up the detected item name for better database matching."""
    # Remove OCR artifacts, normalize spacing, etc.
    cleaned = re.sub(r'\s+', ' ', name).strip()
    # Remove common OCR errors or prefixes like "Item X:" if they exist
    cleaned = re.sub(r'^Item \d+:\s*', '', cleaned)
    # Remove [OCR failed] or [Detection failed] markers
    cleaned = re.sub(r'\[.*?\]', '', cleaned).strip()
    return cleaned

def ensure_dict(obj):
    """Ensure an object is converted to a dictionary."""
    if obj is None:
        return {}
    
    if isinstance(obj, dict):
        return obj
    
    # Handle sqlite3.Row objects
    if hasattr(obj, 'keys') and callable(obj.keys):
        try:
            return dict(obj)
        except (TypeError, ValueError):
            pass
    
    # Handle objects with __dict__ attribute
    if hasattr(obj, '__dict__'):
        return obj.__dict__
    
    # Handle objects with __slots__
    if hasattr(obj, '__slots__'):
        return {slot: getattr(obj, slot, None) for slot in obj.__slots__}
    
    # If it's an iterable but not a string
    if hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
        try:
            return {i: v for i, v in enumerate(obj)}
        except TypeError:
            pass
    
    # If all else fails, just wrap it in a dictionary
    return {'value': obj}

def closest_graffiti_colour(ocr_colour, variations):
    """The graffiti variation whose '(Colour)' best matches the OCR'd colour.

    Returns None when nothing is reasonably close (an OCR fragment rather
    than a colour), so the caller keeps the matcher's own pick.
    """
    from difflib import SequenceMatcher

    wanted = ocr_colour.strip().lower()
    best, best_ratio = None, 0.0
    for variation in variations or []:
        variation = ensure_dict(variation)
        found = re.search(r'\(([^()]*)\)$', variation.get('name') or '')
        if not found:
            continue
        ratio = SequenceMatcher(None, wanted, found.group(1).lower()).ratio()
        if ratio > best_ratio:
            best, best_ratio = variation, ratio
    return best if best_ratio >= 0.6 else None


def candidate_entry(item, score, confidence):
    """One candidate for the results page, from an item row."""
    tradable = item.get('tradable')
    return {
        'id': item.get('id'),
        'name': item.get('name', 'Unknown Item'),
        'collection': item.get('collection', ''),
        'price': item.get('price'),
        'price_type': item.get('price_type', 'unknown'),
        'item_type': item.get('item_type', ''),
        # Databases built before the column existed count as tradable.
        'tradable': tradable is None or bool(tradable),
        'score': score,
        'confidence': confidence,
    }


# Normalised OCR texts that name only an item type, not an item.
TYPE_ONLY_TEXTS = {'sealed graffiti', 'graffiti', 'sealed', ''}


def match_items_in_database(item_names, matcher):
    """Match each detected item name against the database with `matcher`
    (an ItemMatcher). Returns one result per name, in order."""
    results = []
    
    for name in item_names:
        cleaned_name = clean_item_name(name)
        if not cleaned_name:
            results.append({
                'original': name,
                'cleaned': cleaned_name,
                'status': 'empty',
                'matches': []
            })
            continue

        # Text that is only an item-type prefix ("Sealed Graffiti" with the
        # name cut off by the crop) scores 1.0 against *every* graffiti, so
        # the "match" was an arbitrary one at an arbitrary price -- and could
        # even become a recommended pick. Say what happened instead.
        if matcher.normalize_text(cleaned_name) in TYPE_ONLY_TEXTS:
            results.append({
                'original': name,
                'cleaned': cleaned_name,
                'status': 'name_missing',
                'matches': []
            })
            continue
        
        # Use the ItemMatcher to match the item with confidence. The item
        # type is read from the text itself; this used to assume the first of
        # the four slots is always a case and searched only cases there.
        item_type = matcher.detect_item_type(cleaned_name)
        match_result = matcher.match_with_confidence(cleaned_name, item_type=item_type)
        
        if match_result['status'] == 'matched':
            best_match = ensure_dict(match_result['best_match'])
            best_match_entry = candidate_entry(best_match, match_result['score'],
                                               match_result['confidence'])
            best_type = best_match.get('item_type')
            
            # Cases (and capsules) and non-tradable tools: the best match plus
            # the other candidates of the same type
            if best_type in ('case', 'tool'):
                match_list = [best_match_entry]
                for match_data in match_result['matches'][1:]:
                    match_item = ensure_dict(match_data.get('item', {}))
                    if match_item.get('item_type') != best_type:
                        continue
                    score = match_data.get('score', 0)
                    match_list.append(candidate_entry(match_item, score, matcher.confidence_label(score)))
            
            # For graffiti items, only show the best match -- unless the OCR
            # text lost the colour in brackets (the crop usually cuts it off),
            # in which case the best match is an arbitrary colour and every
            # colour is listed, like the wears of a skin.
            elif best_type == 'graffiti':
                colour = re.search(r'\(([^)]*)\)\s*$', cleaned_name)
                if colour:
                    # Every colour normalises to the same name, so the
                    # matcher's top hit is an arbitrary one; use the colour
                    # that was actually read.
                    chosen = closest_graffiti_colour(colour.group(1), match_result['all_wear_variations'])
                    if chosen is not None:
                        best_match_entry = candidate_entry(chosen, best_match_entry['score'],
                                                           best_match_entry['confidence'])
                match_list = [best_match_entry]
                if not colour:
                    for variation in match_result['all_wear_variations']:
                        variation = ensure_dict(variation)
                        if variation.get('id') == best_match.get('id'):
                            continue
                        match_list.append(candidate_entry(variation, 0.0, 'variation'))
            
            # Skins: the best match, the other candidates, then every wear of
            # the best match
            else:
                match_list = [best_match_entry]
                for match_data in match_result['matches'][1:]:
                    match_item = ensure_dict(match_data.get('item', {}))
                    score = match_data.get('score', 0)
                    match_list.append(candidate_entry(match_item, score, matcher.confidence_label(score)))
                
                for variation in match_result['all_wear_variations']:
                    variation = ensure_dict(variation)
                    if not any(match['id'] == variation.get('id') for match in match_list):
                        match_list.append(candidate_entry(variation, 0.0, 'variation'))
            
            results.append({
                'original': name,
                'cleaned': cleaned_name,
                'status': 'found',
                'matches': match_list
            })
        else:
            # No matches found
            results.append({
                'original': name,
                'cleaned': cleaned_name,
                'status': 'not_found',
                'matches': []
            })
    
    return results

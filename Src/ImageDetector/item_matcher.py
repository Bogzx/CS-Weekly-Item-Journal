import os
import sqlite3
import re
from difflib import SequenceMatcher
from functools import lru_cache


@lru_cache(maxsize=200_000)
def _word_ratio(a, b):
    """Character similarity of two words. Cached: the item vocabulary is small
    and repetitive (weapon names, "sealed graffiti", colours), and a full scan
    compares the same few OCR words against it thousands of times."""
    return SequenceMatcher(None, a, b).ratio()


class ItemDatabaseNotReady(RuntimeError):
    """The database has no items table yet (the item DB was never built)."""

# Minimum similarity for a candidate to be returned at all.
MATCH_THRESHOLD = 0.4

# Below this best score from the word-filtered candidates, every item is
# scored too (the filter can miss when OCR mangled the first words).
FALLBACK_BELOW = 0.75

# A detected item type is kept unless an item of another type scores more than
# this much higher.
TYPE_MARGIN = 0.1

# Match score -> confidence label, calibrated 2026-09-30 on the 77 labelled
# English slots of Training_Images (tools/ocr_accuracy.py --db, 60 matched):
#   score >= 0.75: 38 of 38 top matches were the right item   -> 'high'
#   0.50 - 0.75:   17 of 18                                   -> 'medium'
#   0.40 - 0.50:    5 of 10                                   -> 'low'
# (The old 0.85/0.65 cut-offs were set for a scorer that boosted by 1.2.)
CONFIDENCE_THRESHOLDS = {'high': 0.75, 'medium': 0.5}


class ItemMatcher:
    def __init__(self, db_path="csgo_items.db"):
        """
        Initialize the item matcher.
        
        Args:
            db_path: Path to the SQLite database
        """
        self.db_path = db_path
        self.wear_conditions = [
            "Factory New", 
            "Minimal Wear", 
            "Field-Tested", 
            "Well-Worn", 
            "Battle-Scarred"
        ]
        
        # Cache of all items for faster matching, and the database file
        # signature it was loaded from (see _db_signature)
        self.items_cache = None
        self._cache_signature = None
        
        # Pre-compile regex patterns
        self.clean_pattern = re.compile(r'[^\w\s]')
        # Wears, with the hyphen optional ("Field-Tested", "field tested").
        self.wear_pattern = re.compile(
            r'\b(?:' + '|'.join(
                r'[\s-]*'.join(re.escape(part) for part in re.split(r'[\s-]+', wear.lower()))
                for wear in self.wear_conditions
            ) + r')\b'
        )
        # Filler words, matched as whole words only.
        self.noise_pattern = re.compile(r'\b(?:skin|weapon|case|item|collection)\b')
        
    def get_db_connection(self):
        """Get a connection to the SQLite database."""
        conn = sqlite3.connect(self.db_path)
        # Set row_factory to return dictionaries instead of Row objects
        conn.row_factory = lambda cursor, row: {
            column[0]: row[idx] for idx, column in enumerate(cursor.description)
        }
        return conn
    
    def _db_signature(self):
        """(mtime, size) of the database file and its WAL, or None.

        The cache used to be loaded once per process and never refreshed, so
        prices written by the daily price job (or a manual bulk_scraper run)
        never reached the recommendations until the app was restarted.
        Writes in WAL mode land in the -wal file first, so it counts too.
        """
        signature = []
        for path in (self.db_path, self.db_path + '-wal'):
            try:
                stat = os.stat(path)
            except OSError:
                signature.append(None)
            else:
                signature.append((stat.st_mtime_ns, stat.st_size))
        return tuple(signature)

    def load_items_cache(self):
        """Load all items into a cache, reloading when the database changed."""
        signature = self._db_signature()
        if self.items_cache is not None and signature == self._cache_signature:
            return self.items_cache
            
        conn = self.get_db_connection()
        try:
            # Get columns dynamically to handle different database schemas
            cursor = conn.execute("PRAGMA table_info(items)")
            # Fix for KeyError: 1 - access columns by index as they are now dictionaries
            columns_info = cursor.fetchall()
            columns = [col['name'] for col in columns_info]
            if not columns:
                raise ItemDatabaseNotReady(
                    f"{self.db_path} has no item table yet. Build the item database first "
                    f"(README: 'Build the item database')."
                )
            
            # Construct query based on available columns
            select_cols = ", ".join(columns)
            
            cursor = conn.execute(f"SELECT {select_cols} FROM items")
            
            # Explicitly convert ALL sqlite3.Row objects to regular dictionaries
            items = []
            for row in cursor.fetchall():
                # Convert to regular dictionary
                item = dict(row)
                
                # Extract weapon and skin name for easier matching
                full_name = item.get('name', '')
                parts = self.parse_item_name(full_name)
                item['weapon'] = parts.get('weapon', '')
                item['skin_name'] = parts.get('skin', '')
                item['wear'] = parts.get('wear', '')
                item['normalized'] = self.normalize_text(full_name)
                
                # Extract just the weapon and skin part without wear
                base_name = f"{item['weapon']} | {item['skin_name']}"
                item['base_name'] = base_name
                item['base_normalized'] = self.normalize_text(base_name)
                
                items.append(item)
            
            # Swap in the complete list at once so a concurrent request never
            # sees a half-built cache.
            self.items_cache = items
            self._cache_signature = signature
            return self.items_cache
        finally:
            conn.close()
    
    def normalize_text(self, text):
        """Normalize text for better matching."""
        if not text:
            return ""
        
        # Convert to lowercase
        text = text.lower()
        
        # Replace common OCR errors
        text = text.replace('0', 'o')  # Replace zero with letter o
        text = text.replace('1', 'l')  # Replace 1 with letter l
        text = text.replace('5', 's')  # Replace 5 with letter s
        text = text.replace('8', 'b')  # Replace 8 with letter b
        
        # Remove the wear first. Punctuation used to be replaced before this,
        # so "field-tested", "well-worn" and "battle-scarred" had already
        # become "field tested" etc. and were never stripped -- three of the
        # five wear variants of every skin kept extra words that skewed the
        # similarity towards Factory New / Minimal Wear.
        text = self.wear_pattern.sub(' ', text)
        
        # Replace special characters with spaces
        text = self.clean_pattern.sub(' ', text)
        
        # Remove other common words that might confuse matching. As whole
        # words: plain substring removal turned e.g. "showcase" into "show".
        text = self.noise_pattern.sub(' ', text)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def parse_item_name(self, name):
        """
        Parse a CS:GO item name into its components.
        
        Args:
            name: Full item name (e.g., "Negev | Bulkhead (Factory New)")
            
        Returns:
            Dict with weapon, skin, and wear components
        """
        if not name:
            return {}
            
        parts = {}
        
        # Extract wear condition if present
        wear_match = re.search(r'\((.*?)\)$', name)
        if wear_match:
            parts['wear'] = wear_match.group(1)
            name = name[:wear_match.start()].strip()
        
        # Split weapon and skin
        if '|' in name:
            weapon, skin = name.split('|', 1)
            parts['weapon'] = weapon.strip()
            parts['skin'] = skin.strip()
        else:
            # Try to intelligently split based on known weapon names
            # For simplicity, just split on the first space as a fallback
            space_pos = name.find(' ')
            if space_pos > 0:
                parts['weapon'] = name[:space_pos].strip()
                parts['skin'] = name[space_pos:].strip()
            else:
                parts['weapon'] = name
                parts['skin'] = ""
        
        return parts
    
    @staticmethod
    def _soft_token_overlap(tokens, others):
        """Mean over `tokens` of the best similarity to any of `others`."""
        total = 0.0
        for token in tokens:
            best = max(_word_ratio(token, other) for other in others)
            total += best if best >= 0.5 else 0.0
        return total / len(tokens)

    def similarity_score(self, text1, text2):
        """
        Calculate string similarity score between 0 and 1.
        Uses a combination of approaches for better matching.
        """
        if not text1 or not text2:
            return 0
            
        # Direct sequence matching (character by character comparison)
        seq_score = SequenceMatcher(None, text1, text2).ratio()
        
        # Word similarity. Each word counts by its best character similarity
        # to a word on the other side (below 0.5 counts as no match), so an
        # OCR-damaged word ("recdii" for "recoil") still contributes. With
        # exact-only word matching a single misread letter zeroed this part.
        tokens1 = text1.split()
        tokens2 = text2.split()
        if not tokens1 or not tokens2:
            token_score = 0
        else:
            token_score = (self._soft_token_overlap(tokens1, tokens2)
                           + self._soft_token_overlap(tokens2, tokens1)) / 2
        
        # Containment score (is one text contained in the other?)
        containment_score = 0
        if text1 in text2 or text2 in text1:
            min_len = min(len(text1), len(text2))
            max_len = max(len(text1), len(text2))
            # Normalized containment score
            containment_score = min_len / max_len if max_len > 0 else 0
        
        # Weighted combination of the scores (adjust weights as needed)
        combined_score = (seq_score * 0.50) + (token_score * 0.30) + (containment_score * 0.20)
        
        return combined_score
    
    def detect_item_type(self, extracted_text):
        """Guess the item type from the OCR text: 'graffiti', 'case', 'skin' or None.

        Replaces the old assumption that the first of the four slots is always
        a case. Graffiti say "Sealed Graffiti", cases end in "Case" (OCR'd as
        "Cose", "Caso", ...), and skins are "Weapon | Finish". None means
        "search everything". match_item treats the type as a preference, not a
        filter, so a misread type ("FAMAS | Roll Cage" looks like a case when
        OCR drops the bar) cannot hide the right item.
        """
        words = re.findall(r'[a-z0-9-]+', (extracted_text or '').lower())
        if not words:
            return None
        # "Sealed Graffiti" leads every graffiti name; OCR often damages it
        # ("Sopled Grettid"). Measured over every non-graffiti name in the
        # database, the first two words never reach 0.6 against it (max 0.53).
        if SequenceMatcher(None, ' '.join(words[:2]), 'sealed graffiti').ratio() >= 0.6:
            return 'graffiti'
        if len(words) >= 2 and SequenceMatcher(None, words[-1], 'case').ratio() >= 0.75:
            return 'case'
        if '|' in extracted_text:
            return 'skin'
        return None

    @staticmethod
    def confidence_label(score):
        """'high', 'medium' or 'low' for a match score (see CONFIDENCE_THRESHOLDS)."""
        if score >= CONFIDENCE_THRESHOLDS['high']:
            return 'high'
        if score >= CONFIDENCE_THRESHOLDS['medium']:
            return 'medium'
        return 'low'

    def match_item(self, extracted_text, max_results=5, threshold=MATCH_THRESHOLD, item_type=None):
        """
        Match extracted text to database items.
        
        Every candidate is scored the same way: similarity_score() between the
        normalised OCR text and the item's full normalised name (wear removed,
        graffiti colour kept, so a colour that was read picks that colour).
        This replaced three code paths whose scores were not comparable, one
        of which multiplied by 1.2 and capped at 1.0 -- so any text containing
        two of an item's words ("Sealed Graffiti") scored a "high" 1.00.
        
        Args:
            extracted_text: Text extracted from image
            max_results: Maximum number of distinct items to return
            threshold: Minimum similarity score to consider a match
            item_type: Preferred item type ('case', 'skin', 'graffiti'), e.g.
                from detect_item_type. Items of other types still win when
                they score more than TYPE_MARGIN higher.
            
        Returns:
            List of {'item', 'score'}, best first, one per distinct item name
            (the wears of a skin count as one; get_all_wear_variations lists them)
        """
        if not extracted_text or extracted_text.strip() == "":
            return []
            
        normalized_text = self.normalize_text(extracted_text)
        if not normalized_text:
            return []
        
        items = self.load_items_cache()
        matches = self._rank(normalized_text, items, threshold)
        if item_type:
            typed = self._rank(normalized_text,
                               [item for item in items if item.get('item_type') == item_type],
                               threshold)
            # Prefer the detected type unless another type matches clearly better.
            if typed and (not matches or typed[0]['score'] >= matches[0]['score'] - TYPE_MARGIN):
                matches = typed
        return matches[:max_results]

    def _rank(self, normalized_text, items, threshold):
        """Score items against the text; best first, one entry per distinct name."""
        # Fast path: items containing the first two significant OCR words.
        # It only narrows the search; a weak best score falls back to all.
        significant = [token for token in normalized_text.split() if len(token) > 2][:2]
        candidates = [item for item in items
                      if significant and all(token in item['normalized'] for token in significant)]
        
        def score_all(pool):
            best = {}
            for item in pool:
                score = self.similarity_score(normalized_text, item['normalized'])
                key = item['normalized']
                if score >= threshold and (key not in best or score > best[key]['score']):
                    best[key] = {'item': item, 'score': score}
            return best
        
        scored = score_all(candidates)
        if not scored or max(m['score'] for m in scored.values()) < FALLBACK_BELOW:
            for key, match in score_all(items).items():
                if key not in scored or match['score'] > scored[key]['score']:
                    scored[key] = match
        
        return sorted(scored.values(), key=lambda m: m['score'], reverse=True)
    
    def get_all_wear_variations(self, base_item):
        """
        Get all wear variations of an item.
        
        Args:
            base_item: A matched item
            
        Returns:
            List of items with the same weapon and skin but different wear
        """
        if not base_item:
            return []
        
        # Convert base_item to dict if it's a sqlite3.Row
        if isinstance(base_item, sqlite3.Row):
            base_item = dict(base_item)
            
        # Get weapon and skin components
        weapon = base_item.get('weapon', '')
        skin = base_item.get('skin_name', '')
        
        if not weapon or not skin:
            return [base_item]
            
        # Load all items from cache
        items = self.load_items_cache()
        
        variations = []
        
        # Find all items with the same weapon and skin
        for item in items:
            if (item.get('weapon') == weapon and 
                item.get('skin_name') == skin):
                variations.append(item)
        
        # If no variations found, return the original item
        if not variations:
            return [base_item]
            
        # Sort by wear condition order
        def wear_sort_key(item):
            wear = item.get('wear', '')
            try:
                return self.wear_conditions.index(wear)
            except ValueError:
                return len(self.wear_conditions)  # Put unknown wear at the end
        
        variations.sort(key=wear_sort_key)
        
        return variations
    
    def match_with_confidence(self, extracted_text, threshold=MATCH_THRESHOLD, item_type=None):
        """
        Match extracted text to database items with confidence levels.
        
        Args:
            extracted_text: Text extracted from image
            threshold: Minimum similarity score to consider a match
            
        Returns:
            Dict with status, matches, and best match
        """
        matches = self.match_item(extracted_text, threshold=threshold, item_type=item_type)
        
        if not matches:
            return {
                'status': 'no_match',
                'matches': [],
                'best_match': None,
                'all_wear_variations': []
            }
        
        best_match = matches[0]['item']
        all_variations = self.get_all_wear_variations(best_match)
        
        score = matches[0]['score']
        confidence = self.confidence_label(score)
        
        # Convert all items to regular dictionaries to ensure they have .get() method
        all_variations_dicts = []
        for var in all_variations:
            if isinstance(var, sqlite3.Row):
                all_variations_dicts.append(dict(var))
            else:
                all_variations_dicts.append(var)
        
        return {
            'status': 'matched',
            'confidence': confidence,
            'score': score,
            'matches': matches,
            'best_match': best_match,
            'all_wear_variations': all_variations_dicts
        }

# Example usage
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Match extracted text to CS:GO items')
    parser.add_argument('text', help='Text to match')
    parser.add_argument('--db', default='csgo_items.db', help='Path to database')
    args = parser.parse_args()
    
    matcher = ItemMatcher(args.db)
    result = matcher.match_with_confidence(args.text)
    
    print(f"Input text: {args.text}")
    print(f"Match status: {result['status']}")
    
    if result['status'] == 'matched':
        print(f"Confidence: {result['confidence']} (score: {result['score']:.2f})")
        print(f"Best match: {result['best_match']['name']}")
        
        print("\nAll wear variations:")
        for item in result['all_wear_variations']:
            price = item.get('price')
            price_str = f"${price:.2f}" if price is not None else "N/A"
            print(f"- {item['name']} ({price_str})")
    else:
        print("No matches found")
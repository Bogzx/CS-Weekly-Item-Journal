import sqlite3
import re
from difflib import SequenceMatcher
import os

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
        
        # Cache of all items for faster matching
        self.items_cache = None
        
        # Pre-compile regex patterns
        self.clean_pattern = re.compile(r'[^\w\s]')
        
    def get_db_connection(self):
        """Get a connection to the SQLite database."""
        conn = sqlite3.connect(self.db_path)
        # Set row_factory to return dictionaries instead of Row objects
        conn.row_factory = lambda cursor, row: {
            column[0]: row[idx] for idx, column in enumerate(cursor.description)
        }
        return conn
    
    def load_items_cache(self):
        """Load all items from the database into a cache for faster matching."""
        if self.items_cache is not None:
            return self.items_cache
            
        conn = self.get_db_connection()
        try:
            # Get columns dynamically to handle different database schemas
            cursor = conn.execute("PRAGMA table_info(items)")
            columns = [col[1] for col in cursor.fetchall()]
            
            # Construct query based on available columns
            select_cols = ", ".join(columns)
            
            cursor = conn.execute(f"SELECT {select_cols} FROM items")
            
            # Explicitly convert ALL sqlite3.Row objects to regular dictionaries
            self.items_cache = []
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
                
                self.items_cache.append(item)
            
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
        
        # Replace special characters with spaces
        text = self.clean_pattern.sub(' ', text)
        
        # Remove wear condition for better base matching
        for wear in self.wear_conditions:
            text = text.replace(wear.lower(), '')
        
        # Remove other common words that might confuse matching
        for word in ['skin', 'weapon', 'case', 'item', 'collection']:
            text = text.replace(word, '')
        
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
    
    def similarity_score(self, text1, text2):
        """
        Calculate string similarity score between 0 and 1.
        Uses a combination of approaches for better matching.
        """
        if not text1 or not text2:
            return 0
            
        # Direct sequence matching (character by character comparison)
        seq_score = SequenceMatcher(None, text1, text2).ratio()
        
        # Token-based similarity (word matching)
        tokens1 = set(text1.split())
        tokens2 = set(text2.split())
        
        # Avoid division by zero
        if not tokens1 or not tokens2:
            token_score = 0
        else:
            # Jaccard similarity: intersection over union
            intersection = tokens1.intersection(tokens2)
            union = tokens1.union(tokens2)
            token_score = len(intersection) / len(union)
            
            # Dice coefficient: 2 * intersection / total tokens
            dice_score = 2 * len(intersection) / (len(tokens1) + len(tokens2))
            
            # Take the better of the two token scores
            token_score = max(token_score, dice_score)
        
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
    
    def match_item(self, extracted_text, max_results=5, threshold=0.4):
        """
        Match extracted text to database items.
        
        Args:
            extracted_text: Text extracted from image
            max_results: Maximum number of matches to return
            threshold: Minimum similarity score to consider a match
            
        Returns:
            List of matches with similarity scores
        """
        if not extracted_text or extracted_text.strip() == "":
            return []
            
        # Normalize the extracted text
        normalized_text = self.normalize_text(extracted_text)
        parts = self.parse_item_name(extracted_text)
        
        # Load all items from cache
        items = self.load_items_cache()
        
        matches = []
        
        # Check for token-based matches (individual words)
        if normalized_text:
            tokens = normalized_text.split()
            
            # If we have at least 2 tokens, try matching on them
            if len(tokens) >= 2:
                # Get the two most significant tokens (usually weapon name and skin name)
                significant_tokens = []
                
                # Skip very short tokens (1-2 chars) as they're often noise or OCR errors
                for token in tokens:
                    if len(token) > 2:
                        significant_tokens.append(token)
                        if len(significant_tokens) >= 2:
                            break
                            
                # If we found significant tokens, try matching on them
                if significant_tokens:
                    for item in items:
                        # Check if all significant tokens appear in the base name
                        base_name = item.get('base_normalized', '')
                        token_match = all(token in base_name for token in significant_tokens)
                        
                        if token_match:
                            # Calculate similarity to the base name
                            base_similarity = self.similarity_score(
                                normalized_text, 
                                base_name
                            )
                            
                            # Boost the score for token matches
                            adjusted_score = base_similarity * 1.2
                            
                            if adjusted_score >= threshold:
                                matches.append({
                                    'item': item,
                                    'score': min(adjusted_score, 1.0)  # Cap at 1.0
                                })
        
        # Fast pre-filtering using parts if available and we don't have matches yet
        if not matches and parts.get('weapon') and parts.get('skin'):
            weapon_norm = self.normalize_text(parts['weapon'])
            skin_norm = self.normalize_text(parts['skin'])
            
            # First pass: check for items that contain both weapon and skin terms
            for item in items:
                if (weapon_norm in item.get('base_normalized', '') and 
                    skin_norm in item.get('base_normalized', '')):
                    # Calculate similarity to the base name (without wear)
                    base_similarity = self.similarity_score(
                        normalized_text, 
                        item.get('base_normalized', '')
                    )
                    
                    if base_similarity >= threshold:
                        matches.append({
                            'item': item,
                            'score': base_similarity
                        })
        
        # If no good matches found, try approximate matching with each item
        if not matches:
            for item in items:
                # Get the best similarity score - either to the full name or base name
                full_similarity = self.similarity_score(
                    normalized_text, 
                    item.get('normalized', '')
                )
                base_similarity = self.similarity_score(
                    normalized_text, 
                    item.get('base_normalized', '')
                )
                
                # Also try matching just the weapon part or skin part
                weapon_match = 0
                skin_match = 0
                
                if parts.get('weapon'):
                    weapon_norm = self.normalize_text(parts['weapon'])
                    item_weapon = item.get('weapon', '')
                    if item_weapon:
                        weapon_match = self.similarity_score(
                            weapon_norm,
                            self.normalize_text(item_weapon)
                        )
                
                if parts.get('skin'):
                    skin_norm = self.normalize_text(parts['skin'])
                    item_skin = item.get('skin_name', '')
                    if item_skin:
                        skin_match = self.similarity_score(
                            skin_norm,
                            self.normalize_text(item_skin)
                        )
                
                # Calculate a weighted average if both weapon and skin matches exist
                component_match = 0
                if weapon_match > 0 and skin_match > 0:
                    component_match = (weapon_match * 0.4 + skin_match * 0.6)
                
                # Take the best matching approach
                max_similarity = max(full_similarity, base_similarity, component_match)
                
                if max_similarity >= threshold:
                    matches.append({
                        'item': item,
                        'score': max_similarity
                    })
        
        # Sort by score in descending order
        matches.sort(key=lambda x: x['score'], reverse=True)
        
        # Return top N matches
        return matches[:max_results]
    
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
    
    def match_with_confidence(self, extracted_text, threshold=0.4):
        """
        Match extracted text to database items with confidence levels.
        
        Args:
            extracted_text: Text extracted from image
            threshold: Minimum similarity score to consider a match
            
        Returns:
            Dict with status, matches, and best match
        """
        matches = self.match_item(extracted_text, threshold=threshold)
        
        if not matches:
            return {
                'status': 'no_match',
                'matches': [],
                'best_match': None,
                'all_wear_variations': []
            }
        
        best_match = matches[0]['item']
        all_variations = self.get_all_wear_variations(best_match)
        
        # Determine confidence level based on score
        score = matches[0]['score']
        if score > 0.85:
            confidence = 'high'
        elif score > 0.65:
            confidence = 'medium'
        else:
            confidence = 'low'
        
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
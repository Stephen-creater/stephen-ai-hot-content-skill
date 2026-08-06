import json
import os
from datetime import datetime, timedelta
import re
from difflib import SequenceMatcher

def load_content():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, '..', 'resources', 'fetched_content.json')
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("fetched_content.json not found.")
        return []

def parse_date(date_str):
    if not date_str:
        return None
    # Try common formats
    formats = [
        '%Y-%m-%dT%H:%M:%S', 
        '%Y-%m-%dT%H:%M:%S%z',
        '%a, %d %b %Y %H:%M:%S %z',
        '%Y-%m-%d %H:%M:%S'
    ]
    for fmt in formats:
        try:
            # Handle Z for UTC
            if date_str.endswith('Z'):
                date_str = date_str[:-1]
            # Remove timezone info for simple comparison if needed, or handle it properly
            # For simplicity, let's try to parse and return a naive datetime or aware one
            dt = datetime.strptime(date_str.split('+')[0].split('-')[0] if 'T' in date_str and len(date_str) > 19 else date_str, fmt) 
            return dt
        except ValueError:
            continue
    return None

def is_relevant(item):
    text = (item.get('title', '') + ' ' + item.get('summary', '')).lower()
    keywords = ['ai', 'artificial intelligence', 'gpt', 'llm', 'model', 'tech', 'startup', 'growth', 'productivity', 'learning', 'cognitive', 'future', 'china', 'money', 'business', 'code', 'programming', 'agent', 'deepseek', 'openai', 'anthropic', 'google', 'microsoft', 'apple']
    
    # Exclude keywords
    exclude_keywords = ['politics', 'religion', 'sex', 'violence', 'murder', 'crime', 'gossip', 'celebrity', 'sport', 'football', 'basketball']
    
    if any(k in text for k in exclude_keywords):
        return False
        
    if any(k in text for k in keywords):
        return True
    
    return False

def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

def filter_items(items):
    filtered = []
    seen_titles = []
    
    # Current time for date comparison
    now = datetime.now()
    
    for item in items:
        # 1. Relevance Check
        if not is_relevant(item):
            continue
            
        # 2. Date Check (Bonus for recent items)
        # For now, we trust the fetcher got recent items, but let's try to prioritize
        # If no date, assume it's okay but lower priority? Or maybe fetched_at is enough?
        # The fetcher adds 'fetched_at' which is NOW. 'published' is from the source.
        
        # 3. Deduplication
        title = item.get('title', '')
        is_dup = False
        for seen in seen_titles:
            if similar(title, seen) > 0.8: # 80% similarity
                is_dup = True
                break
        if is_dup:
            continue
            
        seen_titles.append(title)
        filtered.append(item)
        
    return filtered

def main():
    items = load_content()
    print(f"Loaded {len(items)} items.")
    
    filtered = filter_items(items)
    print(f"Filtered down to {len(filtered)} items.")
    
    # Sort roughly by length of content or some other metric? 
    # For now, just take top 40.
    
    print("\n--- Top Candidates ---")
    for i, item in enumerate(filtered[:40]):
        print(f"{i+1}. {item.get('title', 'No Title')}")
        print(f"   Link: {item.get('link', 'No Link')}")
        # print(f"   Summary: {item.get('summary', '')[:100]}...")
        print("")

if __name__ == "__main__":
    main()

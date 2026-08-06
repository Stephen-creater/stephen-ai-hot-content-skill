import json
import os
from datetime import datetime
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

def is_relevant(item):
    text = (item.get('title', '') + ' ' + item.get('summary', '')).lower()
    keywords = ['ai', 'artificial intelligence', 'gpt', 'llm', 'model', 'tech', 'startup', 'growth', 'productivity', 'learning', 'cognitive', 'future', 'china', 'money', 'business', 'code', 'programming', 'agent', 'deepseek', 'openai', 'anthropic', 'google', 'microsoft', 'apple']
    exclude_keywords = ['politics', 'religion', 'sex', 'violence', 'murder', 'crime', 'gossip', 'celebrity', 'sport', 'football', 'basketball']
    if any(k in text for k in exclude_keywords): return False
    if any(k in text for k in keywords): return True
    return False

def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

def filter_items(items):
    filtered = []
    seen_titles = []
    for item in items:
        if not is_relevant(item): continue
        title = item.get('title', '')
        is_dup = False
        for seen in seen_titles:
            if similar(title, seen) > 0.8:
                is_dup = True
                break
        if is_dup: continue
        seen_titles.append(title)
        filtered.append(item)
    return filtered

def main():
    items = load_content()
    filtered = filter_items(items)
    
    # Selected indices (1-based): 4, 8, 12
    # 0-based: 3, 7, 11
    selected_indices = [3, 7, 11]
    
    selected_items = []
    for idx in selected_indices:
        if idx < len(filtered):
            selected_items.append(filtered[idx])
            
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'resources', 'selected_topics.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(selected_items, f, ensure_ascii=False, indent=2)
    
    print(f"Saved {len(selected_items)} topics to {output_path}")

if __name__ == "__main__":
    main()

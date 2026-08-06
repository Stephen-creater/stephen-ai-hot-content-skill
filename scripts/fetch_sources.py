import json
import os
import requests
import feedparser
import trafilatura
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# User-Agent to avoid being blocked
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
TIMEOUT = 10

def load_config():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, '..', 'resources', 'content_curator_sources.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Config file not found at: {config_path}")
        return {"sources": []}

def fetch_rss_item_content(entry, category):
    """Worker to fetch full text for a single RSS entry."""
    item = {
        'title': entry.get('title', ''),
        'link': entry.get('link', ''),
        'published': entry.get('published', entry.get('updated', '')),
        'summary': entry.get('summary', ''),
        'category': category,
        'source_type': 'RSS',
        'content_source': 'rss_summary',
        'fetched_at': datetime.now().isoformat()
    }
    
    try:
        # trafilatura.fetch_url uses requests internally but we want to ensure timeout and 200 check
        # However, for simplicity and explicit control, we use requests first
        response = requests.get(item['link'], headers=HEADERS, timeout=TIMEOUT)
        if response.status_code == 200:
            text = trafilatura.extract(response.text)
            if text:
                item['full_text'] = text
                item['content_source'] = 'web_extraction'
                return item
    except Exception:
        pass
    
    # If we couldn't get full text, we return the item with summary (RSS entries are generally "valid" if they exist in feed)
    return item

def process_rss_source(url, category):
    print(f"Fetching RSS: {url}")
    try:
        # Use requests with timeout to fetch the RSS XML itself first
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if response.status_code != 200:
            return []
        
        feed = feedparser.parse(response.text)
        results = []
        
        # Parallelize fetching full text for entries
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(fetch_rss_item_content, entry, category) for entry in feed.entries[:15]]
            for future in as_completed(futures):
                res = future.result()
                if res:
                    results.append(res)
        return results
    except Exception as e:
        print(f"Error processing RSS {url}: {e}")
        return []

def fetch_web_source(url, category):
    print(f"Fetching Web Source: {url}")
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if response.status_code == 200:
            return {
                'url': url,
                'html_source': response.text,
                'category': category,
                'source_type': 'Web',
                'content_source': 'landing_page_html',
                'fetched_at': datetime.now().isoformat()
            }
    except Exception as e:
        print(f"Error fetching Web {url}: {e}")
    return None

def main():
    print("Starting optimized parallel content fetch...")
    config = load_config()
    all_results = []
    
    tasks = []
    sources = config.get('sources', [])
    
    # Prepare flat list of tasks for parallel execution
    # Note: RSS involves a two-stage fetch (feed then items), we process feeds sequentially 
    # but items internally in parallel, OR we can parallelize the feed processing too.
    # Let's parallelize the high-level source processing.
    
    with ThreadPoolExecutor(max_workers=40) as source_executor:
        future_to_url = {}
        
        for source_group in sources:
            stype = source_group.get('type')
            urls = source_group.get('urls', [])
            category = source_group.get('category', 'Uncategorized')
            
            for url in urls:
                if stype == 'RSS':
                    future = source_executor.submit(process_rss_source, url, category)
                else:
                    future = source_executor.submit(fetch_web_source, url, category)
                future_to_url[future] = url

        for future in as_completed(future_to_url):
            result = future.result()
            if result:
                if isinstance(result, list):
                    all_results.extend(result)
                else:
                    all_results.append(result)
            
    # Save results
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(script_dir, '..', 'resources', 'fetched_content.json')
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    print(f"\nCompleted. Saved {len(all_results)} items to {output_path}")

if __name__ == "__main__":
    main()


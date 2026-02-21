import json
import logging
from datetime import datetime, timedelta
import feedparser
import newspaper
from newspaper import Article
import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# We'll try to use RSS feeds first for efficiency and reliability, falling back to newspaper3k site builder
OUTLETS = {
    "NewsFirst": {
        "rss_feeds": [
            "https://english.newsfirst.lk/feed",
        ],
        "url": "https://english.newsfirst.lk/"
    },
    "AdaDerana": {
        "rss_feeds": [
            "http://www.adaderana.lk/rss.php",
        ],
        "url": "https://www.adaderana.lk/"
    }
}

def collect_articles_from_rss(outlet_name, feeds, days_back=90):
    articles_data = []
    cutoff_date = datetime.now() - timedelta(days=days_back)
    
    for feed_url in feeds:
        logging.info(f"Parsing RSS feed for {outlet_name}: {feed_url}")
        feed = feedparser.parse(feed_url)
        
        for entry in feed.entries:
            try:
                # Try to parse published date. RSS formats can vary.
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                     dt = datetime(*entry.published_parsed[:6])
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                     dt = datetime(*entry.updated_parsed[:6])
                else:
                    logging.warning(f"Could not parse date for entry: {entry.get('title', 'Unknown')}")
                    continue
                
                # check if it's within our time window (e.g., last 3 months)
                # Note: RSS feeds rarely go back 3 months, they usually only have the latest 50-100 items.
                if dt >= cutoff_date:
                    articles_data.append({
                        "outlet": outlet_name,
                        "date": dt.strftime('%Y-%m-%d %H:%M:%S'),
                        "title": entry.title,
                        "url": entry.link
                    })
            except Exception as e:
                logging.error(f"Error parsing entry in {outlet_name}: {e}")
                
    return articles_data

def scrape_article_content(url):
    try:
        article = Article(url)
        article.download()
        article.parse()
        return article.text
    except Exception as e:
        logging.error(f"Failed to scrape content from {url}: {e}")
        return ""

def collect_data(days_back=90):
    all_articles = []
    
    # 1. Gather URLs and metadata from RSS feeds
    for outlet_name, info in OUTLETS.items():
        logging.info(f"Starting data collection for {outlet_name}")
        if "rss_feeds" in info and info["rss_feeds"]:
             articles = collect_articles_from_rss(outlet_name, info["rss_feeds"], days_back)
             all_articles.extend(articles)
             logging.info(f"Found {len(articles)} articles in RSS for {outlet_name}")
    
    # 2. Scrape full content for gathered URLs
    logging.info(f"Scraping full content for {len(all_articles)} articles...")
    for idx, article in enumerate(all_articles):
        if idx % 10 == 0:
            logging.info(f"Scraping progress: {idx}/{len(all_articles)}")
        
        content = scrape_article_content(article['url'])
        article['text'] = content
        
    # Filter out articles where we couldn't get text
    valid_articles = [a for a in all_articles if a.get('text') and len(a['text'].strip()) > 50]
    
    # 3. Save to DataFrame
    df = pd.DataFrame(valid_articles)
    
    if not df.empty:
        # Save to CSV
        output_file = "data/raw_articles.csv"
        df.to_csv(output_file, index=False)
        logging.info(f"Saved {len(df)} articles to {output_file}")
    else:
        logging.warning("No valid articles collected.")

if __name__ == "__main__":
    # For MVP, try to collect what's available now
    # Note: RSS only gives recent articles. To get 3 months, we'd need to scrape archives
    # Let's start with RSS to ensure the pipeline works, then we can augment with archive scraping or a provided dataset.
    collect_data(days_back=90)

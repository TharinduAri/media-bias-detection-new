import json
import logging
from datetime import datetime, timedelta
try:
    from dateutil import parser as date_parser
except Exception:
    date_parser = None
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
                dt = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    dt = datetime(*entry.published_parsed[:6])
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    dt = datetime(*entry.updated_parsed[:6])
                else:
                    # Some feeds provide only a string (entry.published / entry.updated)
                    pub_str = entry.get('published') or entry.get('updated') or entry.get('pubDate')
                    if pub_str and date_parser is not None:
                        try:
                            dt = date_parser.parse(pub_str)
                        except Exception:
                            logging.debug(f"dateutil failed to parse published string for entry: {entry.get('title', 'Unknown')}")

                if dt is None:
                    # As a last resort include the article but mark with current time
                    logging.warning(f"Missing/unknown date for entry; including anyway: {entry.get('title', 'Unknown')}")
                    dt = datetime.now()
                
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


def collect_articles_from_site(outlet_name, site_url, days_back=90, max_articles=50):
    """Fallback: build the site with newspaper and extract recent article URLs.
    This helps when RSS feeds are missing or empty for an outlet.
    """
    articles_data = []
    cutoff_date = datetime.now() - timedelta(days=days_back)
    try:
        logging.info(f"Falling back to site scraping for {outlet_name}: {site_url}")
        site = newspaper.build(site_url, memoize_articles=False)
        count = 0
        for art in site.articles:
            if count >= max_articles:
                break
            try:
                a = Article(art.url)
                a.download()
                a.parse()
                pub = a.publish_date
                if pub is None:
                    pub = datetime.now()
                if pub >= cutoff_date:
                    articles_data.append({
                        "outlet": outlet_name,
                        "date": pub.strftime('%Y-%m-%d %H:%M:%S'),
                        "title": a.title or art.url,
                        "url": art.url
                    })
                    count += 1
            except Exception as e:
                logging.debug(f"site fallback failed for {art.url}: {e}")
    except Exception as e:
        logging.warning(f"Site scraping fallback failed for {outlet_name}: {e}")

    return articles_data

def collect_data(days_back=90):
    all_articles = []
    
    # 1. Gather URLs and metadata from RSS feeds
    for outlet_name, info in OUTLETS.items():
        logging.info(f"Starting data collection for {outlet_name}")
        if "rss_feeds" in info and info["rss_feeds"]:
             articles = collect_articles_from_rss(outlet_name, info["rss_feeds"], days_back)
             all_articles.extend(articles)
             logging.info(f"Found {len(articles)} articles in RSS for {outlet_name}")
             # If RSS returned nothing, try site scraping fallback
             if len(articles) == 0 and info.get("url"):
                 fallback = collect_articles_from_site(outlet_name, info.get("url"), days_back)
                 if fallback:
                     all_articles.extend(fallback)
                     logging.info(f"Fallback site scraping found {len(fallback)} articles for {outlet_name}")
    
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

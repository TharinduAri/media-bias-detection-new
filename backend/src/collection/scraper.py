import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any
try:
    from dateutil import parser as date_parser
except Exception:
    date_parser = None
import feedparser
import newspaper
from newspaper import Article
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

SCRAPE_MAX_RETRIES = 3
SCRAPE_BACKOFF_SECONDS = 1.5

def _newspaper_config(timeout_seconds=12):
    config = newspaper.Config()
    config.request_timeout = timeout_seconds
    config.browser_user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )
    return config

def load_outlets_from_db():
    from prisma import Prisma

    db = Prisma()
    db.connect()
    try:
        outlets = db.outlet.find_many()
        outlet_configs = []

        for outlet in outlets:
            feeds = outlet.rss_feeds
            if isinstance(feeds, str):
                try:
                    feeds = json.loads(feeds)
                except Exception:
                    feeds = []

            if not isinstance(feeds, list):
                feeds = []

            outlet_configs.append(
                {
                    "name": outlet.name,
                    "url": outlet.url,
                    "rss_feeds": [f.strip() for f in feeds if isinstance(f, str) and f.strip()],
                }
            )

        return outlet_configs
    finally:
        db.disconnect()

def _to_datetime_from_struct_time(value: Any):
    if isinstance(value, time.struct_time):
        return datetime(*value[:6])
    return None

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
                    dt = _to_datetime_from_struct_time(entry.published_parsed)
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    dt = _to_datetime_from_struct_time(entry.updated_parsed)
                else:
                    # Some feeds provide only a string (entry.published / entry.updated)
                    pub_str = entry.get('published') or entry.get('updated') or entry.get('pubDate')
                    if isinstance(pub_str, str) and pub_str and date_parser is not None:
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
    for attempt in range(1, SCRAPE_MAX_RETRIES + 1):
        try:
            article = Article(url, config=_newspaper_config())
            article.download()
            article.parse()
            return article.text
        except Exception as e:
            is_last_attempt = attempt == SCRAPE_MAX_RETRIES
            if is_last_attempt:
                logging.error(f"Failed to scrape content from {url} after {attempt} attempts: {e}")
                return ""

            backoff = SCRAPE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            logging.warning(
                f"Scrape attempt {attempt}/{SCRAPE_MAX_RETRIES} failed for {url}: {e}. "
                f"Retrying in {backoff:.1f}s"
            )
            time.sleep(backoff)

    return ""


def collect_articles_from_site(outlet_name, site_url, days_back=90, max_articles=50):
    """Fallback: build the site with newspaper and extract recent article URLs.
    This helps when RSS feeds are missing or empty for an outlet.
    """
    articles_data = []
    cutoff_date = datetime.now() - timedelta(days=days_back)
    try:
        logging.info(f"Falling back to site scraping for {outlet_name}: {site_url}")
        site = newspaper.build(site_url, memoize_articles=False, config=_newspaper_config())
        count = 0
        for art in site.articles:
            if count >= max_articles:
                break
            try:
                a = Article(art.url, config=_newspaper_config())
                a.download()
                a.parse()
                pub = a.publish_date
                if pub is None:
                    pub = datetime.now()
                elif isinstance(pub, str):
                    if date_parser is not None:
                        try:
                            pub = date_parser.parse(pub)
                        except Exception:
                            pub = datetime.now()
                    else:
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
    outlets = load_outlets_from_db()

    if not outlets:
        logging.warning("No outlets configured in DB. Add outlets before running scraper.")
        return
    
    # 1. Gather URLs and metadata from RSS feeds
    for outlet in outlets:
        outlet_name = outlet["name"]
        info = {
            "rss_feeds": outlet.get("rss_feeds", []),
            "url": outlet.get("url"),
        }
        logging.info(f"Starting data collection for {outlet_name}")
        articles = []
        rss_feeds = info.get("rss_feeds") or []

        if rss_feeds:
            articles = collect_articles_from_rss(outlet_name, rss_feeds, days_back)
            all_articles.extend(articles)
            logging.info(f"Found {len(articles)} articles in RSS for {outlet_name}")
        else:
            logging.info(f"No RSS feeds configured for {outlet_name}; trying site fallback")

        # If RSS was not configured or returned nothing, try site scraping fallback.
        if len(articles) == 0 and info.get("url"):
            fallback = collect_articles_from_site(outlet_name, info.get("url"), days_back)
            if fallback:
                all_articles.extend(fallback)
                logging.info(f"Fallback site scraping found {len(fallback)} articles for {outlet_name}")
            else:
                logging.warning(f"No articles found for {outlet_name} from RSS or site fallback")
        elif len(articles) == 0:
            logging.warning(f"Outlet {outlet_name} has no URL configured for site fallback")
    
    # 2. Scrape full content for gathered URLs
    logging.info(f"Scraping full content for {len(all_articles)} articles concurrently...")
    
    # We will process in parallel using threads (newspaper3k makes network requests, so threads are great)
    def process_article(article):
        content = scrape_article_content(article['url'])
        article['text'] = content
        return article

    processed_articles = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all tasks
        future_to_article = {executor.submit(process_article, art): art for art in all_articles}
        
        # As they complete, add them to our processed list
        for idx, future in enumerate(as_completed(future_to_article)):
            if (idx + 1) % 10 == 0:
                logging.info(f"Scraping progress: {idx + 1}/{len(all_articles)}")
            processed_articles.append(future.result())

    # Replace all_articles with the processed ones
    all_articles = processed_articles
        
    # Filter out articles where we couldn't get text
    valid_articles = [a for a in all_articles if a.get('text') and len(a['text'].strip()) > 50]
    
    # 3. Save to DB
    if not valid_articles:
        logging.warning("No valid articles collected.")
        return

    try:
        from prisma import Prisma
        db = Prisma()
        db.connect()
        
        for article in valid_articles:
            # We must convert date string to datetime to avoid Prisma validation error
            dt = datetime.strptime(article['date'], '%Y-%m-%d %H:%M:%S')
            
            db.article.upsert(
                where={'url': article['url']},
                data={
                    'create': {
                        'outlet': article['outlet'],
                        'date': dt,
                        'title': article['title'],
                        'url': article['url'],
                        'text': article['text']
                    },
                    'update': {
                        'text': article['text'],
                        'title': article['title']
                    }
                }
            )
        logging.info(f"Saved {len(valid_articles)} articles to DB")
        db.disconnect()
    except Exception as e:
        logging.error(f"DB Error while saving articles: {e}")

if __name__ == "__main__":
    # For MVP, try to collect what's available now
    # Note: RSS only gives recent articles. To get 3 months, we'd need to scrape archives
    # Let's start with RSS to ensure the pipeline works, then we can augment with archive scraping or a provided dataset.
    collect_data(days_back=90)

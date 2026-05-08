from fastapi import APIRouter

router = APIRouter(
    prefix="/api/v1/outlets",
    tags=["outlets"],
)

_REGISTRY_META = [
    {
        "domain": "adaderana.lk",
        "scraper_class": "AdaDeranaOutlet",
        "discovery": "Sitemap → Wayback CDX",
        "extraction": "trafilatura (follows 301 redirects)",
        "notes": "Beautified URL redirect: news.php?nid=X → canonical slug",
    },
    {
        "domain": "ceylontoday.lk",
        "scraper_class": "CeylonTodayOutlet",
        "discovery": "Sitemap (follows 301) → RSS",
        "extraction": "trafilatura",
        "notes": "Sitemap moved via 301 redirect; httpx follows automatically",
    },
    {
        "domain": "ft.lk",
        "scraper_class": "DailyFTOutlet",
        "discovery": "Paginated /sitemaps/english-{N} (concurrent, auto-stop)",
        "extraction": "trafilatura",
        "notes": "Custom CMS pagination; 300 articles/page; stops on partial page",
    },
    {
        "domain": "economynext.com",
        "scraper_class": "EconomyNextOutlet",
        "discovery": "WordPress sitemap (posts-post shards only) → RSS",
        "extraction": "trafilatura + browser headers + 500-byte ghost guard",
        "notes": "403 on /culture; ghost responses common; browser headers reduce 500 rate",
    },
    {
        "domain": "lbo.lk",
        "scraper_class": "LBOOutlet",
        "discovery": "WordPress REST API → sitemap shards",
        "extraction": "WP REST API JSON (full content, no HTML scraping required)",
        "notes": "API returns full article content; sitemap shards used as fallback only",
    },
    {
        "domain": "english.newsfirst.lk",
        "scraper_class": "NewsfirstOutlet",
        "discovery": "RSS → sitemap.xml → homepage regex link-scrape",
        "extraction": "trafilatura",
        "notes": "JS-rendered SPA — focused_crawler permanently bypassed",
    },
]


@router.get("/registry")
def get_registry():
    return _REGISTRY_META

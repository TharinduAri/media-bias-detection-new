"""Single source of truth for configured news-outlet scrapers."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from urllib.parse import urlparse

from .outlets import (
    AdaDeranaOutlet,
    BaseOutletScraper,
    CeylonTodayOutlet,
    ColomboGazetteOutlet,
    DailyFTOutlet,
    DailyMirrorOutlet,
    DailyNewsOutlet,
    EconomyNextOutlet,
    LBOOutlet,
    NewsfirstOutlet,
    NewsLKOutlet,
    SundayObserverOutlet,
    TheIslandOutlet,
    TheMorningOutlet,
)


@dataclass(frozen=True)
class OutletDefinition:
    name: str
    url: str
    domains: tuple[str, ...]
    scraper_class: type[BaseOutletScraper]

    @property
    def domain(self) -> str:
        return (urlparse(self.url).hostname or "").removeprefix("www.")


OUTLET_DEFINITIONS: tuple[OutletDefinition, ...] = (
    OutletDefinition("Ada Derana", "https://www.adaderana.lk", ("adaderana.lk",), AdaDeranaOutlet),
    OutletDefinition("Ceylon Today", "https://www.ceylontoday.lk", ("ceylontoday.lk",), CeylonTodayOutlet),
    OutletDefinition("Daily FT", "https://www.ft.lk", ("ft.lk", "dailyft.lk"), DailyFTOutlet),
    OutletDefinition("Economy Next", "https://economynext.com", ("economynext.com",), EconomyNextOutlet),
    OutletDefinition(
        "LBO",
        "https://www.lankabusinessonline.com",
        ("lbo.lk", "lankabusinessonline.com"),
        LBOOutlet,
    ),
    OutletDefinition(
        "Newsfirst",
        "https://english.newsfirst.lk",
        ("newsfirst.lk", "english.newsfirst.lk"),
        NewsfirstOutlet,
    ),
    OutletDefinition("Daily Mirror", "https://www.dailymirror.lk", ("dailymirror.lk",), DailyMirrorOutlet),
    OutletDefinition("The Morning", "https://www.themorning.lk", ("themorning.lk",), TheMorningOutlet),
    OutletDefinition("Daily News", "https://www.dailynews.lk", ("dailynews.lk",), DailyNewsOutlet),
    OutletDefinition("The Island", "https://island.lk", ("island.lk",), TheIslandOutlet),
    OutletDefinition(
        "Sunday Observer",
        "https://www.sundayobserver.lk",
        ("sundayobserver.lk",),
        SundayObserverOutlet,
    ),
    OutletDefinition(
        "Colombo Gazette",
        "https://colombogazette.com",
        ("colombogazette.com",),
        ColomboGazetteOutlet,
    ),
    OutletDefinition("News LK", "https://www.news.lk", ("news.lk",), NewsLKOutlet),
)


def resolve_outlet_class(url: str) -> type[BaseOutletScraper] | None:
    domain = (urlparse(url).hostname or "").removeprefix("www.").lower()
    for definition in OUTLET_DEFINITIONS:
        if any(domain == suffix or domain.endswith(f".{suffix}") for suffix in definition.domains):
            return definition.scraper_class
    return None


def get_outlet_registry_metadata() -> list[dict[str, str]]:
    """Generate public registry metadata from the active scraper catalog."""
    entries: list[dict[str, str]] = []
    for definition in OUTLET_DEFINITIONS:
        scraper_class = definition.scraper_class
        class_doc = inspect.getdoc(scraper_class) or "Dedicated outlet-specific discovery."
        summary = " ".join(class_doc.split()).split(".", 1)[0].strip()
        custom_extraction = scraper_class.extract_content is not BaseOutletScraper.extract_content
        entries.append(
            {
                "name": definition.name,
                "domain": definition.domain,
                "scraper_class": scraper_class.__name__,
                "discovery": summary,
                "extraction": (
                    "Outlet-specific content extraction"
                    if custom_extraction
                    else "Shared HTTP and trafilatura extraction"
                ),
                "notes": f"Active scraper configured for {definition.url}",
            }
        )
    return entries

"""Outlet-specific scraper registry."""
from .adaderana import AdaDeranaOutlet
from .ceylontoday import CeylonTodayOutlet
from .dailyft import DailyFTOutlet
from .economynext import EconomyNextOutlet
from .lbo import LBOOutlet
from .newsfirst import NewsfirstOutlet
from .themorning import TheMorningOutlet
from .colombogazette import ColomboGazetteOutlet
from .theisland import TheIslandOutlet
from .dailymirror import DailyMirrorOutlet
from .colombopage import ColomboPageOutlet
from .dailynews import DailyNewsOutlet
from .sundayobserver import SundayObserverOutlet
from .newslk import NewsLKOutlet
from .base import BaseOutletScraper

__all__ = [
    "BaseOutletScraper",
    "AdaDeranaOutlet",
    "CeylonTodayOutlet",
    "DailyFTOutlet",
    "EconomyNextOutlet",
    "LBOOutlet",
    "NewsfirstOutlet",
    "TheMorningOutlet",
    "ColomboGazetteOutlet",
    "TheIslandOutlet",
    "DailyMirrorOutlet",
    "ColomboPageOutlet",
    "DailyNewsOutlet",
    "SundayObserverOutlet",
    "NewsLKOutlet",
]

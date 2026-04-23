"""Outlet-specific scraper registry."""
from .adaderana import AdaDeranaOutlet
from .ceylontoday import CeylonTodayOutlet
from .dailyft import DailyFTOutlet
from .economynext import EconomyNextOutlet
from .lbo import LBOOutlet
from .newsfirst import NewsfirstOutlet
from .base import BaseOutletScraper

__all__ = [
    "BaseOutletScraper",
    "AdaDeranaOutlet",
    "CeylonTodayOutlet",
    "DailyFTOutlet",
    "EconomyNextOutlet",
    "LBOOutlet",
    "NewsfirstOutlet",
]

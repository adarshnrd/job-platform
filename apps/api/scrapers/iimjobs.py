"""
iimjobs scraper — India management/leadership job board (Info Edge).

Same gladiator JSON search API as Hirist; runs browserless. Note: iimjobs is a
management/consulting board, so hands-on engineering queries (e.g. "Node.js")
legitimately return few results — it shines for senior/leadership searches.
See scrapers/infoedge_base.py for the shared implementation.
"""
from scrapers.infoedge_base import InfoEdgeGladiatorScraper
from models.job import Platform


class IimjobsScraper(InfoEdgeGladiatorScraper):
    platform = Platform.iimjobs
    SITE_HOST = "www.iimjobs.com"
    GLADIATOR_HOST = "gladiator.iimjobs.com"

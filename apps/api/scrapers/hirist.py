"""
Hirist scraper — India tech/IT job board (Info Edge).

React SPA backed by the public gladiator JSON search API; runs browserless.
See scrapers/infoedge_base.py for the shared implementation.
"""
from scrapers.infoedge_base import InfoEdgeGladiatorScraper
from models.job import Platform


class HiristScraper(InfoEdgeGladiatorScraper):
    platform = Platform.hirist
    SITE_HOST = "www.hirist.tech"
    GLADIATOR_HOST = "gladiator.hirist.tech"

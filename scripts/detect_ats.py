#!/usr/bin/env python3
"""Detect which ATS an employer's careers page runs on and print ready-to-paste
board dicts for scrapers/ats.py MENA_SEED_BOARDS.

This is how the employer registry grows without a model in the loop: feed it a
CSV of `name,url` careers pages, and it prints one seed line per board that
resolves to real jobs, plus the vendors we cannot ingest yet (SuccessFactors,
iCIMS, ...) so Phase 3 knows what is waiting. Taleo, Phenom and Avature are
ingestible since Phase 3: their ids are not in apply URLs, so they are derived
from the careers page here (see detect_composite).

    apps/api/venv/Scripts/python.exe scripts/detect_ats.py --in docs/mena/employers_seed.csv

Pages that answer 401/403/429/503, a bot challenge, or time out are reported as
blocked and left alone — this tool never tries to get past a bot wall
(docs/mena/README.md §5.1). Output is for human review; nothing is written to
the seed list or the harvested-board store.
"""
import argparse
import asyncio
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

import httpx

API_DIR = Path(__file__).resolve().parent.parent / "apps" / "api"
sys.path.insert(0, str(API_DIR))
# scrapers.* import config.settings, which wants these set. No DB call is made.
for _k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
    os.environ.setdefault(_k, "http://unused")

from services import ats_harvester as harvester  # noqa: E402

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CONCURRENCY = 10
TIMEOUT = 25
_URL = re.compile(r"""https?://[^"' <>]+""")
_BLOCK_STATUSES = {401, 403, 429, 503}
_BLOCK_MARKERS = ("cf-chl", "challenge-platform", "just a moment...", "attention required! | cloudflare")

# Vendors we recognise but cannot always ingest. Matched case-insensitively
# against the page HTML and every URL on it. taleo/phenom/avature are printed
# as UNSUPPORTED only when detect_composite could not build a valid board.
UNSUPPORTED = {
    "successfactors": ("sapsf.com", "successfactors"),
    "taleo": ("taleo.net", "/careersection/"),
    "avature": ("avature.net",),
    "phenom": ("phenompeople", "/global/en/search-results"),
    "icims": ("icims.com",),
    "eightfold": ("eightfold.ai",),
    "zoho": ("zohorecruit",),
}


_TALEO_SECTION = re.compile(r"https?://([a-z0-9.-]+)/careersection/([A-Za-z0-9_]+)/", re.I)
_TALEO_INFRA = {"rest", "images", "theme", "iam", "sitemap"}   # not career sections
_TALEO_PORTAL = re.compile(r"portal=(\d{6,})")
_PHENOM_LOCALE = re.compile(r"^[a-z]{2}(?:[-_][a-zA-Z]{2})?$")


def taleo_candidates(urls: list[str]) -> list[tuple[str, str]]:
    """(host, career section) pairs named by `/careersection/<section>/` links."""
    seen: list[tuple[str, str]] = []
    for u in urls:
        for host, section in _TALEO_SECTION.findall(u):
            pair = (host.lower(), section)
            if section.lower() not in _TALEO_INFRA and pair not in seen:
                seen.append(pair)
    return seen


def find_portal(html: str) -> str | None:
    """Taleo's numeric portal id, which only appears in page HTML."""
    m = _TALEO_PORTAL.search(html or "")
    return m.group(1) if m else None


def phenom_site(final_url: str, html: str) -> str | None:
    """`global/en` from a Phenom People page: the first two path segments of the
    page URL when the second looks like a locale, else from a
    /<a>/<b>/search-results link on the page."""
    segs = [x for x in urlsplit(final_url).path.split("/") if x]
    if len(segs) >= 2 and _PHENOM_LOCALE.match(segs[1]):
        return f"{segs[0]}/{segs[1]}"
    m = re.search(r"/([a-z0-9-]+/[a-z]{2}(?:[-_][a-zA-Z]{2})?)/(?:search-results|job/)", html or "")
    return m.group(1) if m else None


async def detect_composite(client: httpx.AsyncClient, final_url: str, html: str, urls: list[str]) -> set[tuple[str, str]]:
    """Taleo / Phenom / Avature boards named by a careers page.

    Their ids are not in apply URLs, so the harvester has no pattern for them.
    Taleo: host + section from a /careersection/ link; the portal id comes from
    the page, or else from that section's own job-search page (one extra GET).
    Phenom: host + the locale path of the page. Avature: host + first path
    segment. harvester._validate then proves each guess against the live site
    (Avature needs a declared sitemap, so a robots-restricted portal like
    Emirates fails validation).
    """
    pairs: set[tuple[str, str]] = set()
    low = html.lower()
    host = urlsplit(final_url).netloc.lower()

    for t_host, section in taleo_candidates(urls)[:2]:
        portal = find_portal(html)
        if not portal:
            try:
                r = await client.get(f"https://{t_host}/careersection/{section}/jobsearch.ftl?lang=en")
                portal = find_portal(r.text) if r.status_code == 200 else None
            except Exception:
                portal = None
        if portal:
            pairs.add(("taleo", f"{t_host}|{section}|{portal}"))

    if "phenompeople" in low or "phapp.ddo" in low:
        site = phenom_site(final_url, html)
        if site:
            pairs.add(("phenom", f"{host}|{site}"))

    if "avature" in low or "avacdn.net" in low:
        segs = [x for x in urlsplit(final_url).path.split("/") if x]
        if segs:
            pairs.add(("avature", f"{host}|{segs[0]}"))
    return pairs


def read_employers(path: Path) -> list[tuple[str, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "," not in line:
            continue
        name, url = line.split(",", 1)
        rows.append((name.strip(), url.strip()))
    return rows


def seeded_keys() -> set[tuple]:
    """Identity of boards already in the seed lists, so reruns flag them instead
    of listing them as discoveries. Composite vendors compare on host+site."""
    from scrapers.ats import MENA_SEED_BOARDS, SEED_BOARDS
    keys = set()
    for b in [*SEED_BOARDS, *MENA_SEED_BOARDS]:
        parts = harvester.board_from_pair(b["ats"], b["token"])
        keys.add((b["ats"], b["token"]))
        keys.add((b["ats"], b.get("host") or parts.get("host"), b.get("site") or parts.get("site")))
    return keys


async def probe(client: httpx.AsyncClient, name: str, url: str) -> dict:
    """Fetch one careers page. Returns {name, url, status, pairs, unsupported}."""
    res = {"name": name, "url": url, "status": None, "pairs": set(), "unsupported": set(), "blocked": None}
    try:
        r = await client.get(url)
    except Exception as e:  # timeouts, DNS, TLS
        res["blocked"] = f"{type(e).__name__}"
        return res
    res["status"] = r.status_code
    if r.status_code in _BLOCK_STATUSES:
        res["blocked"] = f"HTTP {r.status_code}"
        return res
    if r.status_code >= 400:
        res["blocked"] = f"HTTP {r.status_code}"
        return res
    html = r.text
    low = html.lower()
    if any(m in low for m in _BLOCK_MARKERS):
        res["blocked"] = "bot challenge"
        return res

    # The requested URL is scanned too: a Taleo "/careersection/" link redirects
    # to an SSO path that no longer carries the signature.
    urls = [url, str(r.url), *_URL.findall(html)]
    for u in urls:
        res["pairs"] |= harvester.extract_tokens(u)
    # Teamtailor career sites on a custom domain (careers.chalhoubgroup.com)
    # never mention *.teamtailor.com, but always load Teamtailor's CDN assets;
    # the site itself then serves /jobs.json, which _validate confirms.
    if "teamtailor-cdn.com" in low and not any(a == "teamtailor" for a, _ in res["pairs"]):
        res["pairs"].add(("teamtailor", r.url.host.lower()))
    res["pairs"] |= await detect_composite(client, str(r.url), html, urls)
    haystack = low + " " + " ".join(u.lower() for u in urls)
    for vendor, sigs in UNSUPPORTED.items():
        if any(sig in haystack for sig in sigs):
            res["unsupported"].add(vendor)
    return res


async def main(path: Path) -> int:
    employers = read_employers(path)
    if not employers:
        print(f"No employers found in {path}", file=sys.stderr)
        return 1
    seeded = seeded_keys()
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                 headers={"User-Agent": BROWSER_UA,
                                          "Accept": "text/html,application/xhtml+xml"}) as page_client, \
            httpx.AsyncClient(timeout=15, follow_redirects=True,
                              headers={"User-Agent": "Mozilla/5.0 (compatible; JobPlatformBot/1.0)"}) as api_client:

        async def run(name, url):
            async with sem:
                res = await probe(page_client, name, url)
                # Validate while still holding the slot so API calls stay polite.
                res["valid"] = {}
                for pair in sorted(res["pairs"]):
                    res["valid"][pair] = await harvester._validate(api_client, *pair)
                return res

        results = await asyncio.gather(*[run(n, u) for n, u in employers])

    valid_count = 0
    unsupported_by_vendor: dict[str, list[str]] = defaultdict(list)
    blocked: list[str] = []
    no_ats: list[str] = []
    print("# Candidate boards (review, then paste into scrapers/ats.py MENA_SEED_BOARDS)")
    for res in results:
        name = res["name"]
        if res["blocked"]:
            blocked.append(f"{name} ({res['blocked']}) {res['url']}")
            continue
        # A vendor with a validated board is supported, not "waiting".
        supported_here = {a for (a, _t), info in res["valid"].items() if info}
        for vendor in sorted(res["unsupported"] - supported_here):
            unsupported_by_vendor[vendor].append(name)
            print(f"UNSUPPORTED {vendor}  # {name}")
        found_any = False
        for (ats, token), info in sorted(res["valid"].items()):
            if not info:
                continue
            found_any = True
            board = harvester.board_from_pair(ats, token)
            already = (ats, token) in seeded or (ats, board.get("host"), board.get("site")) in seeded
            extras = "".join(f', "{k}": "{board[k]}"' for k in ("host", "tenant", "site", "portal") if k in board)
            line = (f'{{"ats": "{ats}", "token": "{token}", "company": "{name}"{extras}, '
                    f'"regions": ("mena",)}},  # {info["jobs"]} jobs')
            print(("# already seeded: " if already else "") + line)
            if not already:
                valid_count += 1
        if not found_any and not res["unsupported"]:
            no_ats.append(name)

    print("\n# ── Summary ──")
    print(f"employers scanned:           {len(employers)}")
    print(f"supported & valid (new):     {valid_count}")
    print("unsupported vendors:         "
          + (", ".join(f"{v}={len(ns)} ({', '.join(ns)})" for v, ns in sorted(unsupported_by_vendor.items())) or "none"))
    print(f"blocked (403/WAF/timeout):   {len(blocked)}")
    for b in blocked:
        print(f"    {b}")
    print(f"reachable, no known ATS:     {len(no_ats)}" + (f" ({', '.join(no_ats)})" if no_ats else ""))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--in", dest="infile", required=True, help="CSV of name,url careers pages")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(Path(args.infile))))

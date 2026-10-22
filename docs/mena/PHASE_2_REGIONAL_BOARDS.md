# Phase 2: Regional and Country Job Boards

> **Goal:** add MENA job boards that are reachable over plain HTTP and allow crawling, plus MENA eligibility on the remote boards we already scrape.
> **Depends on:** Phase 0 merged (`services/geo/mena.py`, `_get_text`, `jsonld.map_job_posting`, `annualize`). It does **not** depend on Phase 1.
> **Estimated size:** 3 PRs. PR-A covers 2.1–2.2 (foundit Gulf and Sabbar), PR-B covers 2.3–2.5 (Emploitic, Keejob, ReKrute), PR-C covers 2.6–2.7 (remote boards and keyed aggregators).
> **Every board below was probed on 2026-10-17** (README §3.2). Boards that wall plain HTTP (WUZZUF, Bayt, GulfTalent, Jobs.ps, Jadarat, …) or disallow everything in robots.txt (Akhtaboot, Jobzella) are **not** in this phase.

---

## Common pattern for a new board scraper

Every board in 2.2–2.5 follows this shape. Copy it from `scrapers/foundit.py` (an API source with a bounded detail fetch) and `scrapers/welcometothejungle.py` (sitemap plus JSON-LD).

```python
class XScraper(APIBaseScraper):
    platform = Platform.x
    requires_key = False
    regions = {"mena"}
    rate_limit_per_minute = 20          # boards: keep ≤ 30
    DETAIL_FETCH_LIMIT = 12             # detail pages per search() call
    HTML_HEADERS = {"Accept": "text/html,application/xhtml+xml"}
    COUNTRY = "XX"                      # ISO-2 the board serves

    async def search_jobs(self, query, location="", max_results=50, credentials=None, region="mena"):
        # 1. A board serving one country returns [] for a location in another
        #    MENA country (a Tunisia board must not answer a "Dubai" search).
        if location and mena.is_mena(location) and mena.country_of(location) != self.COUNTRY:
            return []
        # 2. list → candidate detail URLs (filtered/ranked), 3. fetch ≤ DETAIL_FETCH_LIMIT
        #    details, parse JSON-LD with jsonld.parse_job_posting, 4. map to JobListingCreate
```

`JobListingCreate` mapping rules for every board:
- `salary_currency = mena.currency_for(location) or <board default>`, and `salary_min/max = mena.annualize(value, fields.get("salary_unit"))`.
- `source_url` is the board's canonical job URL. `apply_url` is the same URL unless the board exposes an external apply link.
- `source_job_id` comes from the JSON-LD `identifier.value` when present, otherwise from the numeric or UUID id in the URL.
- When the board only gives a city, append `", <Country name>"` so `mena.is_mena` and the dedup/ranking stages see the country.
- Skip a job whose `validThrough` lies in the past.
- Pop `salary_unit` (and any other key `JobListingCreate` does not know) out of the `parse_job_posting` dict before you build the model.

For each new board you also add:
1. A `Platform` enum value in `models/job.py`, under a new comment `# MENA sources (docs/mena/)`.
2. The value in **`database/18_mena_sources.sql`**: `ALTER TYPE platform ADD VALUE IF NOT EXISTS '<name>';`, with the same header notes as `15_global_sources.sql`. Until it is applied, rows fall back to `'other'` (`job_pipeline.py:185`), so nothing breaks.
3. A `SOURCE_REGISTRY` entry: `Source("<name>", XScraper, True, False, {"mena"})`.
4. A `services/portals.py` entry: tier `"C"`, `regions=("mena",)`, `anti_bot="low"`, with notes naming the data path (e.g. "sitemap + JSON-LD").
5. Offline tests with a trimmed fixture: one list page and one detail page.

---

## 2.1 foundit Gulf (extend the existing `FounditScraper`)

**File:** `apps/api/scrapers/foundit.py`

`www.founditgulf.com/middleware/jobsearch` is the **same JSON API** the scraper already calls on foundit.in/sg/id/hk. Verified on 2026-10-17: a "software engineer" query returned 182 Gulf jobs (KSA, UAE, ...) with `currencyCode: "AED"`, and the same response shape that `_to_listing` already maps.

> ⚠ **Owner decision.** founditgulf's robots.txt disallows `/middleware/`. foundit.in's robots.txt disallows it too, and the repo already calls it for India. To stay consistent with README §5.1, this phase puts the Gulf deployment **behind a flag that is off by default**: `MENA_FOUNDIT_GULF_ENABLED: bool = False` in `config.py`. The owner can flip it.

Changes:
1. `COUNTRY_SITES["gulf"] = ("www.founditgulf.com", "United Arab Emirates", "AED")`.
2. `_site_for(location, region)`: if `region == "mena"` or `mena.is_mena(location)`, return `COUNTRY_SITES["gulf"]`. Do this only when the flag is on; otherwise `search_jobs` returns `[]` for MENA.
3. **The location parameter does not filter by Gulf city.** Verified: `locations=Dubai` returned "Remote, India" INR jobs first, and `location=` and `countries=` were ignored. For the Gulf site, therefore:
   - send `"locations": ""`
   - filter the results client-side: keep an item only if `mena.is_mena(item["locations"])` and (`not mena.is_mena(location)` or `mena.same_country(item["locations"], location)`)
   - drop any item whose `currencyCode == "INR"` or whose location contains "India" (cross-posted Indian remote roles)
4. Currency: keep `item["currencyCode"]` when salary is shown, else `mena.currency_for(location)`. foundit Gulf labels Riyadh jobs AED, so prefer `currency_for(location)` whenever `country_of(location)` is not AE.
5. Registry: `"foundit": Source("foundit", FounditScraper, True, False, {"india", "global", "mena"})`, and `regions` on the class too. `PORTALS["foundit"].regions` gains `"mena"`.
6. Tests in `tests/test_foundit_scraper.py`: `_site_for("Dubai", "mena")` returns the gulf site when the flag is on. The client-side filter drops a `"Remote, India"` item and keeps `"Saudi Arabia, Riyadh"` for location "Saudi Arabia". Build the fixture as described above: one Gulf response trimmed to 4 items (2 Gulf, 2 "Remote, India").

---

## 2.2 Sabbar (Saudi Arabia), new `scrapers/sabbar.py`

**Verified facts:**
- robots.txt allows crawling and lists sitemaps: `https://sabbar.com/en/jobs/sitemaps/job-details.xml` (English) and `/ar/jobs/sitemaps/job-details.xml` (Arabic). The English sitemap held **16,090** `<url>` entries, each with `<lastmod>` (e.g. `2026-10-15`).
- URL shape: `https://sabbar.com/en/jobs/c-{city}-r-{role-slug}/id-{uuid}`, e.g. `/en/jobs/c-riyadh-r-it-project-manager/id-c22dd6a7-2651-4666-aafa-2ed42349ea66`.
- The detail page (about 600 KB of HTML) carries one JSON-LD `JobPosting` with these keys: `title, description (HTML, often Arabic), datePosted, validThrough, employmentType (e.g. PART_TIME), identifier {name, value=uuid}, hiringOrganization {name, description}, jobLocation.address {addressCountry: "SA", addressLocality: "Riyadh"}, directApply`. There was no `baseSalary` on the sample, but handle it if present.
- About 510 of the 16k slugs looked tech-related. Most of the catalogue is sales, HR and other non-tech roles, so **slug pre-filtering is essential**.

**Algorithm:**
1. Load the English sitemap **once per scraper instance** (cache it on `self`; one instance spans one run). Use `self._get_text(url, headers={"Accept": "application/xml,text/xml"})`. Parse with `re.findall(r"<url>\s*<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>", xml)`, and handle a missing `lastmod` with a second, looser regex. If the root is a `<sitemapindex>`, follow the child sitemaps (at most 5).
2. Parse each URL into `(city_slug, role_slug, uuid)` with `re.compile(r"/en/jobs/c-([a-z0-9-]+)-r-([a-z0-9-]+)/id-([0-9a-f-]{36})")`.
3. **Candidate filter:** keep a URL if its `role_slug` contains any of `SABBAR_TECH_SLUGS`, then rank it higher if it also contains a query token.

```python
SABBAR_TECH_SLUGS = (
    "software", "developer", "programmer", "full-stack", "fullstack", "backend", "back-end",
    "frontend", "front-end", "devops", "data-engineer", "data-scientist", "data-analyst",
    "machine-learning", "ai-", "-ai", "mobile", "android", "ios", "flutter", "web-",
    "cloud", "cyber", "security-engineer", "qa-", "test-automation", "sre", "it-",
    "odoo", "sap-", "oracle-", "salesforce", "erp", "system-admin", "network-engineer",
    "solution-architect", "technical-lead", "tech-lead", "product-manager",
)
```

   Query tokens are the user's search words, lowercased and split on non-alphanumerics, keeping those of 3 or more characters, joined with `-` matching.
4. **Location filter:** `city_slug` is e.g. `riyadh`, `jeddah` or `al-khobar`. If `location` is a KSA city (via `mena.country_of(location) == "SA"` and the location's city token is present in the slug with `-` mapped to a space), keep matching cities first. A country-level "Saudi Arabia" search keeps all cities.
5. Sort by `(query_match, lastmod)` descending and take the top `DETAIL_FETCH_LIMIT = 15`. Skip URLs already seen with `self._is_new`.
6. For each detail: `html = await self._get_text(url, headers=HTML_HEADERS)`, then `fields = jsonld.parse_job_posting(html)`. If it is `None`, skip the URL. Build the listing as follows:
   - `title = fields["title"]`, `company = fields.get("company") or "Company (via Sabbar)"`
   - `location = fields.get("location") or f"{city}, Saudi Arabia"`. `_location_str` yields "Riyadh, SA", which `is_mena` resolves, but normalize it to `"Riyadh, Saudi Arabia"` via `mena.MENA_COUNTRIES[iso]["name"]` when the last part is a bare ISO code.
   - `jd_text = fields.get("jd_text") or title`. Arabic text is fine; the AI parse handles it.
   - `salary_currency="SAR"`, `source_job_id=uuid`, `posted_at=fields.get("posted_at")`
   - Skip the job if the JSON-LD `validThrough` is before now. `map_job_posting` does not return it today, so either extend it to emit `valid_through` or read it from `jsonld.find_job_posting(html)`.
7. `regions = {"mena"}`, `rate_limit_per_minute = 20`. The single sitemap call plus 15 details per query keeps a run small.

**Arabic sitemap:** skip it in this phase. The `/en/` pages carry English titles, which suits the prefilter and dedup. Arabic-only postings are a Phase 3 item.

**Tests** (`tests/test_sabbar_scraper.py`): build a fixture sitemap with 6 URLs (2 tech, 4 non-tech, mixed cities) and save one real detail page trimmed to its `<head>` plus the ld+json script. Assert that:
- slug filtering picks the two tech URLs
- a "Jeddah" search ranks Jeddah first
- a "Dubai" search returns `[]` (wrong country)
- a detail maps to a listing with `salary_currency == "SAR"` and an `is_mena` location
- an expired `validThrough` is skipped

---

## 2.3 Emploitic (Algeria), new `scrapers/emploitic.py`

**Verified facts:**
- robots.txt only disallows `/partenaires/`.
- `GET https://emploitic.com/offres-d-emploi?search=developpeur` returns a Next.js page whose `<script id="__NEXT_DATA__">` JSON has `props.pageProps.searchResult = {data: [...], totalPages, currentPage, total, aggregateCount}`. That query returned `total=320` across `totalPages=16`. The page also has `canonicalUrl` (`https://emploitic.com/offres-d-emploi/q-developpeur`) and a JSON-LD `SearchResultsPage` whose `ItemList.itemListElement[].url` gives the job URLs.
- Each item in `data[]` has `id, title, alias, description (HTML, full JD), location [objects], contractType [objects], workMode ("onsite"...), jobLevel [objects], educationLevel [objects], profession [objects], experienceYears [objects], isAnonymous, tags [str], company {sector, ...}, publishedAt (ISO), sort_timestamp`.
- **The full JD is in the list response**, so no detail fetches are needed.

**To verify while building** (save the fixture first, then read it):
- The label field inside the `location[]`, `contractType[]` and `experienceYears[]` objects. They carry `id` and `arn`; look for `name`, `label` or `title`.
- The company name key inside `company` (and `isAnonymous: true` means no name, so use "Confidential (via Emploitic)").
- The job page URL, which is probably `https://emploitic.com/offres-d-emploi/{alias}`. Confirm it against the JSON-LD `ItemList` URLs on the same page, then use whatever pattern those URLs show.
- The page parameter. Try `&page=2` and check that `currentPage == 2`. Fetch at most 3 pages per query.

**Mapping:**
- `location = "<label>, Algeria"`
- `work_mode` from `workMode`, using the `WorkMode` values
- `job_type` from the `contractType` label. Map French `CDI` to full_time, `CDD` to contract, `Stage` to internship and `Freelance` to freelance, using `BaseScraper.match_terms`.
- `min/max_experience` from the `experienceYears` label: `r"(\d+)\s*(?:à|-)\s*(\d+)"`, and `"plus de (\d+)"` gives `(n, None)`
- `required_skills = tags[:12]`, `salary_currency="DZD"`, `posted_at = parse_posted_at(publishedAt)`, `source_job_id = id`

Use the HTML `Accept` header. Parse `__NEXT_DATA__` with `re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)` and then `json.loads`.

**Tests** (`tests/test_emploitic_scraper.py`): use a fixture with `__NEXT_DATA__` trimmed to 3 items. Test the contract (keys), the mapping, the experience parsing and the anonymous company case.

---

## 2.4 Keejob (Tunisia), new `scrapers/keejob.py`

**Verified facts:**
- robots.txt disallows `/api/`, `/recruiter/*`, `/jobseeker/account/` and similar. **Do not call `/api/`.** Listing and job pages are allowed.
- `GET https://www.keejob.com/offres-emploi/?keywords=developpeur` returns HTML with about 30 links shaped like `/offres-emploi/{id}/{slug}/?source=search`. Strip the query string, then dedupe.
- The detail page carries `JobPosting` JSON-LD: `title, identifier {name: "Keejob", value: "248558"}, url, employmentType (FULL_TIME), directApply, datePosted, validThrough, hiringOrganization {name, sameAs}, jobLocation.address {addressLocality: "La Medina", addressRegion: "Tunis", ...}, jobLocationType (TELECOMMUTE for remote), applicantLocationRequirements {name: "TN"}`, plus `description`.

**Algorithm:**
1. List URL: `https://www.keejob.com/offres-emploi/?keywords={quote(query)}`. Pagination: verify `&page=2` on the fixture. Use at most 2 pages.
2. Extract job paths with `re.findall(r'href="(/offres-emploi/(\d+)/[^"/?]+/)', html)`, dedupe by id, and keep the first `DETAIL_FETCH_LIMIT = 12`.
3. Fetch each detail and run `parse_job_posting`. Location = `fields["location"]`, plus `", Tunisia"` if no country is present. `salary_currency="TND"`. `remote` comes from `jobLocationType`, which `map_job_posting` already sets.

**Tests:** list fixture link extraction, detail mapping, and the remote flag.

---

## 2.5 ReKrute (Morocco), new `scrapers/rekrute.py`

**Verified facts:**
- robots.txt has no disallows.
- `GET https://www.rekrute.com/offres.html?s=1&p=1&o=1&query=developpeur` returns HTML with about 20 links like `/offre-emploi-developpeur-python-ia-recrutement-alten-maroc-fes-187569.html`. The trailing number is the job id.
- The detail page carries `JobPosting` JSON-LD with `url, title, datePosted ("2026-10-15 14:30:02", space separator), experienceRequirements ("Confirmé (5 à 10 ans)"), industry, employmentType ("CDI"), jobLocation.address.addressLocality ("Fes"), hiringOrganization {name, logo}, validThrough`.
- **This JSON-LD has no `description`.** The JD must come from the HTML body. Open the saved detail fixture, find the container holding the job text (look for headings like "Poste", "Profil recherché" or "Description"), and extract it with a regex on that container's id or class. Use the meta description as a fallback (`<meta name="description" content="...">`). Keep the extraction in one small function with a clear docstring, and test it against the fixture.

**Algorithm:**
1. List URL: `https://www.rekrute.com/offres.html?s=1&p={page}&o=1&query={quote(query)}`, at most 2 pages.
2. Links: `re.findall(r'href="(/offre-emploi-[^"#?]+-(\d+)\.html)', html)`, deduped by id. Detail cap 12.
3. Map: `location = f"{addressLocality}, Morocco"`. ReKrute also lists Tunisia, Algeria and other African countries; if `addressCountry` is present, use it. Drop non-MENA locations when `region == "mena"`. Experience comes from `experienceRequirements` with `r"(\d+)\s*à\s*(\d+)\s*ans"`, and `"plus de (\d+) ans"` gives `(n, None)`. `job_type` comes from `CDI`, which the Phase 0 jsonld map handles. `salary_currency="MAD"`.
4. Set `self.COUNTRY = "MA"`, but allow the TN and DZ locations that ReKrute carries (README: "Morocco and francophone Africa"). The single-country early return in the common pattern therefore becomes "return `[]` if the location is a MENA country other than MA, TN or DZ".

**Tests:** link extraction, JD extraction from the fixture, experience parsing, and the date with a space separator.

---

## 2.6 Remote boards: MENA eligibility

These existing scrapers gain `"mena"` in `regions`, both on the class and in `SOURCE_REGISTRY`. Each one keeps only roles a MENA-based candidate can take, using `mena.remote_ok_for_mena`. Do not change their india or global behaviour.

| File | Current India filter | Add for `region == "mena"` |
|---|---|---|
| `scrapers/himalayas.py` | `if region == "india" and restrictions and "india" not in restrictions` | `if region == "mena" and not mena.remote_ok_for_mena(item.get("locationRestrictions") or [])` then `continue`. A live sample was mostly `["United States"]`, `["United Kingdom"]` or `[]`, so expect a low yield. |
| `scrapers/jobicy.py` | `_INDIA_OK` tuple on `jobGeo` | `if region == "mena" and geo and not mena.remote_ok_for_mena(geo)` then `continue` |
| `scrapers/remoteok.py` | none (region unused) | `if region == "mena" and not mena.remote_ok_for_mena(item.get("location") or "")` then `continue`. An empty location counts as worldwide, which is RemoteOK's convention. |
| `scrapers/remotive.py` | **`search_jobs` has no `region` parameter** | Add `region: str = "global"` to the signature (`_call_search` only passes it when declared), then `if region == "mena" and not mena.remote_ok_for_mena(item.get("candidate_required_location") or "")` then `continue` |

All four set `salary_currency="USD"` where they set salaries (Himalayas and Remotive currently inherit the model's INR default; fix that in passing, since USD is what these boards quote).

Tests: one case per scraper with a two-item fixture (one US-only and one Worldwide/EMEA). The `mena` region keeps only the second.

---

## 2.7 Keyed aggregators: MENA routing (dormant until keys are set)

These sources only run when their key is configured (`requires_key=True`). Add `"mena"` to their regions with country routing. **Verify each one against the live API once a key exists.** The parameter values below are best guesses, not verified (README §2.2).

| File | Change | Unverified assumption |
|---|---|---|
| `scrapers/careerjet.py` | `_REGION_LOCALE["mena"]` becomes per location: AE `en_AE`, SA `en_SA`, EG `en_EG`, KW `en_KW`, QA `en_QA`, default `en_AE`. Send `location` through for mena, like india. Set `salary_currency` from `mena.currency_for(location)`. | Careerjet runs careerjet.ae, .com.sa, .com.eg and .com.kw (verified that the domains resolve). The API locale codes are not confirmed. If the API answers with an error or 0 results for a locale, log it once and return `[]`. |
| `scrapers/jsearch.py` | `country = mena.country_of(location).lower()` for mena (`"ae"`, `"sa"`, …). Pass `location` in the query string as JSearch does today for other regions. | JSearch's `country` parameter accepting MENA ISO-2 codes is not confirmed. |
| `scrapers/jooble.py` | `where = location` for mena, so a country or city name goes through. | Jooble's single API endpoint geocodes free-text locations; the regional subdomains (ae.jooble.org, …) are Cloudflare-walled for HTML but irrelevant to the API. |
| `scrapers/adzuna.py` | **No change.** Adzuna covers no MENA country. | none |

---

## 2.8 Migration `database/18_mena_sources.sql`

```sql
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'sabbar';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'emploitic';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'keejob';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'rekrute';
```

Add the header comment explaining that this file must run on its own (the enum-in-transaction note from file 15). foundit already exists in the enum.

---

## 2.9 Acceptance checklist

- [ ] A MENA run with locations `["Saudi Arabia", "Egypt"]` and skills `["python", "react"]` shows `sabbar` with more than 0 results for Saudi Arabia, and `emploitic`, `keejob` and `rekrute` each correctly return 0 for those locations (wrong country).
- [ ] A MENA run with location `["Morocco"]` shows ReKrute results; `["Tunisia"]` gives Keejob; `["Algeria"]` gives Emploitic.
- [ ] Every stored MENA listing has a non-INR `salary_currency` and an `is_mena` location.
- [ ] No request goes to a robots-disallowed path (grep the logs for `/api/` on keejob and `/partenaires/` on emploitic). foundit Gulf runs only when `MENA_FOUNDIT_GULF_ENABLED=true`.
- [ ] The source-health panel on the Activity page lists the new sources under the `mena` region (the coverage endpoint is generic and needs no change).
- [ ] All tests pass offline.

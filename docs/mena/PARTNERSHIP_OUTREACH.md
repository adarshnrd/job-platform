# MENA partnership outreach

> **What this is:** the owner's checklist for the job boards that carry most of the MENA volume but cannot be collected with plain HTTP. They are Cloudflare-walled (confirmed 403 on 2026-10-17) or their terms restrict automated collection. We do **not** bypass either. The route is a feed or a written agreement.
> **Source:** PHASE_3_LONG_TAIL.md §3.9. When a feed is granted, implement it as a Phase 2 board scraper (`scrapers/<board>.py`, `mena_common` helpers) that reads the feed.

## Email template

Fill in the board name, the contact route from the table, and your details before sending. Keep it short; one ask per email.

```text
Subject: Job feed / distribution partnership request: <Board name>

Hello <Board name> team,

I'm <name>, <role> at <product name>, a job search tool that helps candidates in the
Middle East and North Africa find and apply to roles that fit their profile. We would
like to include <Board name> vacancies and would rather do it with your agreement than
by scraping.

What we do with a feed:
- We link every listing back to your canonical posting; applicants apply on your site.
- We store vacancy data only (title, company, location, description, posting date, link).
  We never collect or store candidate data from your platform, or recruiter and contact
  personal details.
- We honour takedown and removal requests promptly and refresh expired or removed
  postings on each sync.
- We follow whatever rate limits and attribution rules you set.

What we are asking for:
- A job feed in any format (XML, JSON, RSS or a partner API), with your rate limits and
  terms of use, or
- Written approval of a snippet-and-link model, if you prefer that.

Happy to jump on a call or sign your standard partner terms.

Thank you,
<name>
<contact email> | <website>
```

## Status

| Board | Ask for | Contact route | Status |
|---|---|---|---|
| Bayt | XML/JSON job feed or a distribution/affiliate agreement | bayt.com, "Contact us / Partnerships" | not contacted |
| Naukrigulf | Written consent and a feed (their terms name a legal contact) | naukrigulf.com terms page | not contacted |
| GulfTalent | Feed, or written approval of a snippet-and-link model | gulftalent.com terms page | not contacted |
| WUZZUF / Forasna | Partner API or feed (WUZZUF has no public API; only third-party scrapers exist) | wuzzuf.net business contact | not contacted |
| Qureos | Partner API. Its robots.txt disallows `/api/` and query URLs but publishes `sitemap-hire/*.xml`. Ask whether detail-page indexing is acceptable before using it. | qureos.com | not contacted |
| Tanqeeb | Feed. It is itself an aggregator, so prefer the original sources it links to. | tanqeeb.com | not contacted |
| Jobs.ps, Jadarat, Mihnati, Daleel Madani | Feed or partnership | site contacts | not contacted |

Update the Status column with the date and outcome after each contact (for example `sent 2026-11-02`, `replied: feed offered`, `declined`, `feed live`).

## Also waiting on the owner

- **ReliefWeb** (Phase 3 §3.7): the v2 API needs an approved `appname`. Request one free at apidoc.reliefweb.int, then build the scraper.

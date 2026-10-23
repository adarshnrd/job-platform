"""Tests for the ATS token harvester — extraction, validation gating, persistence."""
import pytest

from services import ats_harvester as h


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "_STORE", tmp_path / "ats_boards.json")
    yield


# ── Extraction ──

@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/figma/jobs/12345", {("greenhouse", "figma")}),
    ("https://job-boards.greenhouse.io/notion/jobs/9", {("greenhouse", "notion")}),
    ("https://boards-api.greenhouse.io/v1/boards/stripe/jobs", {("greenhouse", "stripe")}),
    ("https://boards.greenhouse.io/embed/job_board?for=airbnb", {("greenhouse", "airbnb")}),
    ("https://jobs.lever.co/mixpanel/abc-def-ghi", {("lever", "mixpanel")}),
    ("https://api.lever.co/v0/postings/meesho", {("lever", "meesho")}),
    ("https://jobs.ashbyhq.com/ramp/role-id", {("ashby", "ramp")}),
    ("https://api.ashbyhq.com/posting-api/job-board/linear", {("ashby", "linear")}),
])
def test_extract_valid_tokens(url, expected):
    assert h.extract_tokens(url) == expected


@pytest.mark.parametrize("url", [
    "https://remoteok.com/remote-jobs/12345",
    "https://www.naukri.com/job-listings-x",
    "https://linkedin.com/jobs/view/999",
    "",
    None,
])
def test_extract_ignores_non_ats(url):
    assert h.extract_tokens(url) == set()


def test_blocklisted_tokens_rejected():
    # Infra path segments must not be mistaken for company tokens.
    assert ("greenhouse", "embed") not in h.extract_tokens("https://boards.greenhouse.io/embed/foo")


# ── Persistence + known_pairs ──

def test_persistence_roundtrip(monkeypatch):
    boards = [{"ats": "greenhouse", "token": "acme", "company": "Acme",
               "discovered_at": "now", "source": "harvest"}]
    h._save(boards)
    assert h.load_harvested() == boards


def test_known_pairs_includes_seed_and_harvested():
    h._save([{"ats": "lever", "token": "harvested_co", "company": "H", "discovered_at": "n", "source": "harvest"}])
    pairs = h.known_pairs()
    assert ("lever", "harvested_co") in pairs
    assert ("greenhouse", "postman") in pairs  # from SEED_BOARDS


# ── Harvest: validation gating + persistence ──

@pytest.mark.asyncio
async def test_harvest_only_persists_validated(monkeypatch):
    async def fake_validate(client, ats, token):
        return {"company": token.title(), "jobs": 10} if token == "goodco" else None

    monkeypatch.setattr(h, "_validate", fake_validate)
    added = await h.harvest_urls([
        "https://boards.greenhouse.io/goodco/jobs/1",
        "https://boards.greenhouse.io/badco/jobs/2",
    ])
    tokens = {b["token"] for b in added}
    assert tokens == {"goodco"}
    assert {b["token"] for b in h.load_harvested()} == {"goodco"}


@pytest.mark.asyncio
async def test_harvest_skips_already_known(monkeypatch):
    calls = []

    async def fake_validate(client, ats, token):
        calls.append(token)
        return {"company": token, "jobs": 5}

    monkeypatch.setattr(h, "_validate", fake_validate)
    # postman is a seed board → must not be re-validated.
    added = await h.harvest_urls(["https://boards.greenhouse.io/postman/jobs/1"])
    assert added == []
    assert "postman" not in calls


@pytest.mark.asyncio
async def test_harvest_respects_max_new(monkeypatch):
    async def fake_validate(client, ats, token):
        return {"company": token, "jobs": 1}

    monkeypatch.setattr(h, "_validate", fake_validate)
    urls = [f"https://boards.greenhouse.io/co{i}/jobs/1" for i in range(20)]
    added = await h.harvest_urls(urls, max_new=5)
    assert len(added) == 5


@pytest.mark.asyncio
async def test_harvest_dedupes_within_batch(monkeypatch):
    seen = []

    async def fake_validate(client, ats, token):
        seen.append(token)
        return {"company": token, "jobs": 1}

    monkeypatch.setattr(h, "_validate", fake_validate)
    added = await h.harvest_urls([
        "https://boards.greenhouse.io/dupco/jobs/1",
        "https://boards.greenhouse.io/dupco/jobs/2",
        "https://job-boards.greenhouse.io/dupco/jobs/3",
    ])
    assert len(added) == 1
    assert seen.count("dupco") == 1


# ── Composite tokens (Oracle HCM / Workday / BambooHR / Teamtailor) ──

@pytest.mark.parametrize("url,expected", [
    ("https://ehpv.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs",
     {("oracle_hcm", "ehpv.fa.em2.oraclecloud.com|CX_1")}),
    ("https://EHJD.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en-GB/sites/fabCareers/job/5",
     {("oracle_hcm", "ehjd.fa.em2.oraclecloud.com|fabCareers")}),   # host lowercased, site case kept
    ("https://murex.wd3.myworkdayjobs.com/en-US/MurexCareerPage1/job/Beirut/X_JR1",
     {("workday", "murex.wd3.myworkdayjobs.com|murex|MurexCareerPage1")}),
    ("https://murex.wd3.myworkdayjobs.com/MurexCareerPage1",
     {("workday", "murex.wd3.myworkdayjobs.com|murex|MurexCareerPage1")}),
    ("https://toters.bamboohr.com/careers/59", {("bamboohr", "toters")}),
    ("https://acme.teamtailor.com/jobs/123-x", {("teamtailor", "acme.teamtailor.com")}),
])
def test_extract_composite_tokens(url, expected):
    assert h.extract_tokens(url) == expected


@pytest.mark.parametrize("url", [
    "https://resources.bamboohr.com/x",
    "https://www.bamboohr.com/careers",
    "https://www.teamtailor.com/en/",
    "https://app.teamtailor.com/jobs",
    "https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/site/jobs",   # API path, not a site name
    "https://example.oraclecloud.com/other/path",
])
def test_composite_extraction_rejects_infrastructure(url):
    assert h.extract_tokens(url) == set()


@pytest.mark.parametrize("ats,token,parts", [
    ("oracle_hcm", "ehpv.fa.em2.oraclecloud.com|CX_1", {"host": "ehpv.fa.em2.oraclecloud.com", "site": "CX_1"}),
    ("workday", "murex.wd3.myworkdayjobs.com|murex|MurexCareerPage1",
     {"host": "murex.wd3.myworkdayjobs.com", "tenant": "murex", "site": "MurexCareerPage1"}),
    ("teamtailor", "acme.teamtailor.com", {"host": "acme.teamtailor.com"}),
    ("bamboohr", "toters", {}),
    ("greenhouse", "postman", {}),
    ("oracle_hcm", "dpworld", {}),   # a seed's plain token carries no parts
])
def test_board_from_pair_round_trips(ats, token, parts):
    board = h.board_from_pair(ats, token)
    assert board == {"ats": ats, "token": token, **parts}
    assert h.split_token(ats, token) == parts


@pytest.mark.parametrize("url", [
    "https://ehpv.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs",
    "https://murex.wd3.myworkdayjobs.com/en-US/MurexCareerPage1/job/Beirut/X_JR1",
    "https://acme.teamtailor.com/jobs/123-x",
])
def test_extract_then_board_from_pair_is_lossless(url):
    ((ats, token),) = h.extract_tokens(url)
    board = h.board_from_pair(ats, token)
    assert h.split_token(ats, board["token"]) == {k: board[k] for k in ("host", "tenant", "site") if k in board}


def test_known_pairs_includes_mena_seeds():
    pairs = h.known_pairs()
    assert ("greenhouse", "tamara") in pairs
    assert ("oracle_hcm", "dpworld") in pairs


@pytest.mark.asyncio
async def test_harvest_stores_composite_boards_like_seeds(monkeypatch):
    async def fake_validate(client, ats, token):
        return {"company": "Acme", "jobs": 3}

    monkeypatch.setattr(h, "_validate", fake_validate)
    added = await h.harvest_urls(["https://newco.wd5.myworkdayjobs.com/en-US/Careers/job/X"])
    assert added[0]["host"] == "newco.wd5.myworkdayjobs.com"
    assert added[0]["tenant"] == "newco" and added[0]["site"] == "Careers"
    assert h.load_harvested()[0]["token"] == "newco.wd5.myworkdayjobs.com|newco|Careers"

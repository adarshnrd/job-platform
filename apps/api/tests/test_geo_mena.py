"""MENA geo helpers — services/geo/mena.py."""
import pytest

from services.geo import mena


@pytest.mark.parametrize("loc,iso", [
    ("Dubai, United Arab Emirates", "AE"),
    ("Riyadh", "SA"),
    ("الرياض", "SA"),
    ("Casablanca, Maroc", "MA"),
    ("SA", "SA"),
    ("ae", "AE"),
    ("Saudi Arabia, Riyadh", "SA"),
    ("Abu Dhabi", "AE"),
    ("Tunis, Tunisie", "TN"),
    ("دبي", "AE"),
])
def test_country_of_matches(loc, iso):
    assert mena.country_of(loc) == iso


@pytest.mark.parametrize("loc", [
    "Woman's Health, London", "Romania", "Bangalore", "", None, "USA", "Pune, India",
])
def test_country_of_rejects_non_mena(loc):
    assert mena.country_of(loc) is None


def test_bare_iso_code_only_matches_whole_string():
    assert mena.country_of("Texas, USA") is None
    assert mena.country_of("sa") == "SA"


def test_regions_are_not_countries():
    for text in ("EMEA", "Middle East", "GCC", "MENA", "Gulf"):
        assert mena.country_of(text) is None


def test_is_mena_and_same_country():
    assert mena.is_mena("Doha") is True
    assert mena.is_mena("London") is False
    assert mena.same_country("Dubai", "Abu Dhabi, UAE") is True
    assert mena.same_country("Dubai", "Riyadh") is False
    assert mena.same_country("London", "Paris") is False


def test_currency_for():
    assert mena.currency_for("Doha") == "QAR"
    assert mena.currency_for("EG") == "EGP"
    assert mena.currency_for("London", default="USD") == "USD"
    assert mena.currency_for("London") is None


def test_tokens_are_lowercase_and_not_shared_between_countries():
    seen = {}
    for iso, c in mena.MENA_COUNTRIES.items():
        for tok in (*c["aliases"], *c["cities"]):
            assert tok == tok.lower()
            assert seen.setdefault(tok, iso) == iso, f"{tok!r} claimed by {seen[tok]} and {iso}"


@pytest.mark.parametrize("loc,iso", [
    ("Émirats Arabes Unis", "AE"),
    ("Emirats", "AE"),
    ("Koweït", "KW"),
    ("koweit", "KW"),
    ("Bahreïn", "BH"),
    ("Bahrein", "BH"),
    ("Irak", "IQ"),
])
def test_french_country_spellings(loc, iso):
    assert mena.country_of(loc) == iso


@pytest.mark.parametrize("text", ["Kirakos Ltd", "Pirakis Group", "Sirak Street, London"])
def test_irak_alias_needs_letter_boundaries(text):
    assert mena.country_of(text) is None


def test_names_mena_region():
    assert mena.names_mena_region("Remote - EMEA")
    assert mena.names_mena_region("remote, middle-east")
    assert mena.names_mena_region("Gulf region")
    assert mena.names_mena_region("MENA")
    assert not mena.names_mena_region("Remote - US")
    assert not mena.names_mena_region("Cinemas")   # no "mena" inside a word
    assert not mena.names_mena_region("")
    assert not mena.names_mena_region(None)


def test_annualize():
    assert mena.annualize(10000, "MONTH") == 120000
    assert mena.annualize(None, "MONTH") is None
    assert mena.annualize(50, "HOUR") == 104000
    assert mena.annualize(500, "DAY") == 130000
    assert mena.annualize(2000, "WEEK") == 104000
    assert mena.annualize(90000, "YEAR") == 90000
    assert mena.annualize(90000, None) == 90000


def test_nationals_only_title():
    assert mena.nationals_only("Assistant Manager - Credit Risk (UAE National)")
    assert mena.nationals_only("Associate Director - Emiratized Role")
    assert mena.nationals_only("Saudization Programme Lead")
    assert mena.nationals_only("Analyst - Nationals Only")
    assert mena.nationals_only("مهندس - للسعوديين فقط")


def test_nationals_only_jd_needs_exclusivity_word():
    assert not mena.nationals_only("Senior Backend Engineer", "We value Emirati culture")
    assert mena.nationals_only("Engineer", "Open exclusively for Saudi nationals.")
    assert mena.nationals_only("Engineer", "Candidates must be a UAE national")
    assert not mena.nationals_only("Senior Backend Engineer", None)
    # Only the first 3000 chars of the JD are scanned.
    assert not mena.nationals_only("Engineer", "x" * 3001 + " Saudi nationals only")


def test_remote_ok_for_mena():
    assert mena.remote_ok_for_mena([]) is True
    assert mena.remote_ok_for_mena(None) is True
    assert mena.remote_ok_for_mena("") is True
    assert mena.remote_ok_for_mena(["United States"]) is False
    assert mena.remote_ok_for_mena(["EMEA"]) is True
    assert mena.remote_ok_for_mena("Saudi Arabia") is True
    assert mena.remote_ok_for_mena(["Worldwide"]) is True
    assert mena.remote_ok_for_mena(["Middle East"]) is True
    assert mena.remote_ok_for_mena(["United States", "United Arab Emirates"]) is True


def test_country_name_beats_a_city_from_another_country():
    # "medina" is a Saudi city; the Tunisian address must still resolve to TN.
    assert mena.country_of("La Medina, Tunis, Tunisia") == "TN"
    assert mena.country_of("La Medina, Tunis") == "TN"      # cities only: last one wins
    assert mena.country_of("Medina") == "SA"
    assert mena.country_of("Amman, Jordan") == "JO"


# ── Phase 3 B1: trailing ", XX" ISO segment ──

@pytest.mark.parametrize("loc,iso", [
    ("Al Abageyah, EG", "EG"),
    ("Maadi as Sarayat Al Gharbeyah, EG", "EG"),
    ("Riyadh, SA", "SA"),
    ("La Medina, Tunis, TN", "TN"),
])
def test_trailing_iso_segment_resolves_country(loc, iso):
    assert mena.country_of(loc) == iso


@pytest.mark.parametrize("loc", ["Hörby, SE", "Austin, US", "Visa, USA", "Lahore, PK"])
def test_trailing_non_mena_code_is_not_matched(loc):
    assert mena.country_of(loc) is None

"""Content-fingerprint dedup — services/dedup.py."""
from services.dedup import job_fingerprint, normalize_company, normalize_title


def test_fingerprint_case_and_punctuation_insensitive():
    assert job_fingerprint("Custom Software Engineer", "Accenture") == \
        job_fingerprint("custom  software engineer!", "ACCENTURE")


def test_fingerprint_strips_company_legal_suffixes():
    # The observed Naukri repost pattern: same role, company spelled with and
    # without its legal suffix.
    assert normalize_company("Accenture Solutions Pvt. Ltd.") == "accenture solutions"
    assert normalize_company("Sportism") == "sportism"
    assert job_fingerprint("SDE II", "Foo Pvt Ltd") == job_fingerprint("SDE-II", "Foo")


def test_fingerprint_distinguishes_different_roles_and_companies():
    a = job_fingerprint("Software Engineer", "Accenture")
    assert a != job_fingerprint("Senior Software Engineer", "Accenture")
    assert a != job_fingerprint("Software Engineer", "Infosys")
    # Suffix stripping must not conflate distinct employers.
    assert normalize_company("Oracle Financial Services") != normalize_company("Oracle")


def test_company_of_only_noise_words_does_not_collapse_to_empty():
    assert normalize_company("Co Inc") == "co inc"


def test_handles_none_and_empty():
    assert job_fingerprint(None, None) == "::"
    assert normalize_title("") == ""

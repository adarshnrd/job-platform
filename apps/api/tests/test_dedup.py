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


# ── Unicode-safe normalization (docs/mena/PHASE_0_FOUNDATIONS.md §0.4) ──

def test_arabic_titles_are_not_collapsed_to_one_key():
    a = job_fingerprint("مهندس برمجيات", "شركة علم")
    b = job_fingerprint("محاسب", "شركة علم")
    assert a != b
    assert not a.startswith("::") and not b.startswith("::")
    assert a == "مهندس برمجيات::علم"


def test_arabic_diacritics_are_ignored():
    assert job_fingerprint("مُهندس برمجيات", "علم") == job_fingerprint("مهندس برمجيات", "علم")


def test_arabic_indic_digits_survive_normalization():
    assert normalize_title("مطور ٢") != normalize_title("مطور ٣")


def test_latin_accents_are_kept_and_words_not_split():
    assert job_fingerprint("Développeur Full-Stack", "X") == "développeur full stack::x"


def test_mena_company_suffixes():
    assert normalize_company("Careem Networks FZ-LLC") == "careem networks"
    assert normalize_company("Gulf Bank W.L.L.") == "gulf bank"
    assert normalize_company("شركة علم") == "علم"
    # Names that are entirely noise must still not collapse to "".
    assert normalize_company("SAE") == "sae"


def test_ascii_normalization_is_unchanged():
    """Hard-coded outputs of the pre-Unicode implementation: India/global keys
    must not move."""
    cases = [
        (("Custom Software Engineer", "Accenture"), "custom software engineer::accenture"),
        (("custom  software engineer!", "ACCENTURE"), "custom software engineer::accenture"),
        (("SDE II", "Foo Pvt Ltd"), "sde ii::foo"),
        (("SDE-II", "Foo"), "sde ii::foo"),
        (("Senior Node.js Developer (Remote)", "Acme Corp."), "senior node js developer remote::acme"),
        (("C++ / Rust Engineer", "Tech & Co Inc"), "c rust engineer::tech"),
        (("Full-Stack Developer", "Sportism"), "full stack developer::sportism"),
        (("Software Engineer", "Accenture Solutions Pvt. Ltd."), "software engineer::accenture solutions"),
        (("Data  Scientist - ML", "Co Inc"), "data scientist ml::co inc"),
        (("  QA Lead  ", "  Foo_Bar  LLP "), "qa lead::foo bar"),
        (("", ""), "::"),
    ]
    for (title, company), expected in cases:
        assert job_fingerprint(title, company) == expected, (title, company)

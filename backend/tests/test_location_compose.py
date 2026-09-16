"""`location` holds a place, `country` holds the country, and one string carries both.

Indeed reads the country from `country_indeed` only. LinkedIn, ZipRecruiter and
Google read no country parameter at all: `location` is their only geography
signal. So a search for "Toronto" with country "usa" used to return 20 jobs from
Pittsburgh, PA and store them as new — no exception, no warning, wrong country.

The scraper now composes one location string, "<place>, <country label>", and
sends it to every board. These tests pin the composition, pin that both call
sites build the same string, and pin the migration that removes the country from
the stored location text.
"""
import logging

import pytest

from backend.models.db import Search


def _search(db, **kw):
    kw.setdefault("sources", ["indeed"])
    kw.setdefault("title_include_keywords", [])
    kw.setdefault("title_exclude_keywords", [])
    kw.setdefault("company_filter", [])
    kw.setdefault("company_exclude", [])
    kw.setdefault("country", "usa")
    s = Search(name="Location probe", search_mode="keyword", active=True,
               search_term="program manager", **kw)
    db.add(s)
    db.commit()
    return s


def _record_kwargs(monkeypatch, calls):
    """Replace the real scrape_jobs and keep every kwargs dict it receives."""
    import jobspy
    import pandas as pd

    def scrape_jobs(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame([])

    monkeypatch.setattr(jobspy, "scrape_jobs", scrape_jobs)


def _first_run_auth(db):
    """Empty dashboard_api_key triggers the middleware's first-run bypass."""
    from backend.models.db import Setting
    db.add(Setting(key="dashboard_api_key", value=""))
    db.commit()


# ── the composition ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("location,country,expected", [
    # A plain city gets the country spelled out. This is the case LinkedIn got
    # wrong: "Austin" alone resolved to Austin, Colorado.
    ("Austin", "usa", "Austin, United States"),
    ("Toronto", "canada", "Toronto, Canada"),
    # A city that already carries its country does not carry it twice.
    ("Toronto, Canada", "canada", "Toronto, Canada"),
    ("Cambridge, United Kingdom", "uk", "Cambridge, United Kingdom"),
    # `country` wins over the text, because the user picked that field.
    ("Toronto, Canada", "usa", "Toronto, United States"),
    # A region is not a country, so it survives. "ON" matches no jobspy alias.
    ("Toronto, ON", "canada", "Toronto, ON, Canada"),
    # An empty place gives the label alone: "Canada" is a valid query and
    # ", Canada" is not.
    ("", "canada", "Canada"),
    (None, "usa", "United States"),
    ("   ", "poland", "Poland"),
    # A location that is only a country name carries no place, so the text goes
    # and the country field decides. "United States" is the column default.
    ("United States", "usa", "United States"),
    ("US", "usa", "United States"),
    ("Canada", "usa", "United States"),
    # Text that names no place still receives the country. Measured on LinkedIn:
    # a bare "Remote" returns Taiwan, Japan, India, Canada and Ireland, and
    # "Remote, United States" returns Remote, Oregon. Neither is a remote search,
    # so the country stays and the forms point at the `is_remote` field.
    ("Remote", "usa", "Remote, United States"),
    ("Bay Area", "usa", "Bay Area, United States"),
    # An unknown or missing country falls back the way `country_indeed` does.
    ("Austin", None, "Austin, United States"),
    ("Austin", "Atlantis", "Austin, United States"),
])
def test_compose_location(location, country, expected):
    from backend.countries import compose_location
    assert compose_location(location, country) == expected


@pytest.mark.parametrize("location,expected", [
    ("Toronto, Canada", ("Toronto", "canada")),
    ("Toronto, ON", ("Toronto, ON", None)),
    ("Toronto, ON, Canada", ("Toronto, ON", "canada")),
    ("Canada", ("", "canada")),
    ("  Warsaw ,  Poland  ", ("Warsaw", "poland")),
    ("Remote", ("Remote", None)),
    ("", ("", None)),
    (None, ("", None)),
])
def test_split_country_suffix(location, expected):
    from backend.countries import split_country_suffix
    assert split_country_suffix(location) == expected


# ── both call sites compose the same string ──────────────────────────────────

@pytest.mark.parametrize("location,country", [
    ("Austin", "usa"),
    ("Toronto", "canada"),
    ("Toronto, Canada", "usa"),
    ("Toronto, ON", "canada"),
    ("", "canada"),
    ("Remote", "uk"),
])
def test_the_scraper_and_the_test_preview_send_the_same_location(
    api_client, test_db, monkeypatch, location, country
):
    """One composition, two callers. This test fails if either side drifts."""
    from backend.scraper.sources.jobspy import _run_sync

    _first_run_auth(test_db)
    search = _search(test_db, location=location, country=country)

    calls = []
    _record_kwargs(monkeypatch, calls)

    _run_sync(search)
    resp = api_client.post(f"/api/searches/{search.id}/test")
    assert resp.status_code == 200, f"Unexpected {resp.status_code}: {resp.text}"

    assert len(calls) == 2, f"expected one call per site, got {len(calls)}"
    scraper_loc, preview_loc = calls[0]["location"], calls[1]["location"]
    assert scraper_loc == preview_loc, \
        f"the two call sites drifted: {scraper_loc!r} vs {preview_loc!r}"

    from backend.countries import compose_location
    assert scraper_loc == compose_location(location, country)


def test_the_scraper_sends_the_country_to_indeed_and_to_the_location(test_db, monkeypatch):
    """`country_indeed` still reaches Indeed, and the composed string reaches the rest."""
    from backend.scraper.sources.jobspy import _run_sync

    calls = []
    _record_kwargs(monkeypatch, calls)
    _run_sync(_search(test_db, location="Austin", country="usa",
                      sources=["indeed", "linkedin", "zip_recruiter", "google"]))

    assert calls[0]["country_indeed"] == "usa"
    assert calls[0]["location"] == "Austin, United States"


def test_an_empty_location_does_not_send_a_leading_comma(test_db, monkeypatch):
    """", Canada" is not a query. "Canada" is, and it returns rows."""
    from backend.scraper.sources.jobspy import _run_sync

    calls = []
    _record_kwargs(monkeypatch, calls)
    _run_sync(_search(test_db, location="", country="canada"))

    assert calls[0]["location"] == "Canada"


# ── the migration that removes the country from the stored text ──────────────

def test_the_migration_removes_only_a_country_segment(test_db):
    from backend.seed import _strip_country_from_search_location

    with_country = _search(test_db, location="Toronto, Canada", country="canada")
    with_region = _search(test_db, location="Toronto, ON", country="canada")
    plain = _search(test_db, location="Austin", country="usa")
    only_country = _search(test_db, location="United States", country="usa")

    _strip_country_from_search_location(test_db)

    for row in (with_country, with_region, plain, only_country):
        test_db.refresh(row)
    assert with_country.location == "Toronto"
    assert with_region.location == "Toronto, ON", "a region is not a country"
    assert plain.location == "Austin"
    assert only_country.location == "", "a country name carries no place"


def test_the_migration_keeps_the_country_field_when_the_text_disagrees(test_db, caplog):
    """`country` is the field the user picked, so the text loses."""
    from backend.seed import _strip_country_from_search_location

    search = _search(test_db, location="Toronto, Canada", country="usa")

    with caplog.at_level(logging.WARNING):
        _strip_country_from_search_location(test_db)

    test_db.refresh(search)
    assert search.country == "usa", "the explicitly chosen field must survive"
    assert search.location == "Toronto"
    assert any("keeping country" in r.getMessage() for r in caplog.records), \
        "a contradicting row must be logged"


def test_the_migration_is_idempotent(test_db):
    from backend.seed import _strip_country_from_search_location

    rows = [
        _search(test_db, location="Toronto, Canada", country="canada"),
        _search(test_db, location="Toronto, ON", country="canada"),
        _search(test_db, location="United States", country="usa"),
        _search(test_db, location="Remote", country="usa"),
    ]
    _strip_country_from_search_location(test_db)
    for row in rows:
        test_db.refresh(row)
    after_first = [r.location for r in rows]

    _strip_country_from_search_location(test_db)
    for row in rows:
        test_db.refresh(row)
    assert [r.location for r in rows] == after_first, "a second run must change nothing"


def test_run_migrations_calls_the_location_strip(test_db, monkeypatch):
    """Without this pin, deleting the call leaves the country in every stored location."""
    import backend.seed as seed

    called = []
    monkeypatch.setattr(seed, "_strip_country_from_search_location",
                        lambda db: called.append(db))
    # SQLite rejects `ADD COLUMN IF NOT EXISTS`, so the guard would skip the data
    # migrations for a reason this test is not about. Report a clean list.
    monkeypatch.setattr(seed, "run_migration_statements", lambda db, statements: [])

    seed.run_migrations(test_db)

    assert called, "run_migrations must call the location strip"


def test_the_strip_runs_after_the_country_backfill(test_db, monkeypatch):
    """The backfill reads the country out of the location text the strip removes."""
    import backend.seed as seed

    order = []
    monkeypatch.setattr(seed, "_backfill_search_country",
                        lambda db: order.append("backfill"))
    monkeypatch.setattr(seed, "_strip_country_from_search_location",
                        lambda db: order.append("strip"))
    monkeypatch.setattr(seed, "run_migration_statements", lambda db, statements: [])

    seed.run_migrations(test_db)

    assert order == ["backfill", "strip"]


def test_the_strip_is_skipped_when_the_country_column_was_not_added(test_db, monkeypatch):
    """It reads searches.country. Without the column it raises out of the lifespan."""
    import backend.seed as seed

    called = []
    monkeypatch.setattr(seed, "_strip_country_from_search_location",
                        lambda db: called.append(db))
    monkeypatch.setattr(seed, "run_migration_statements",
                        lambda db, statements: [seed._ADD_COUNTRY_COLUMN])

    seed.run_migrations(test_db)

    assert called == [], "a missing column must not reach the strip"


def test_a_raising_strip_does_not_abort_the_migration(test_db, monkeypatch):
    """run_seeds() runs inside the FastAPI lifespan — no step may take the container down."""
    import backend.seed as seed

    def boom(db):
        raise RuntimeError("column vanished")

    monkeypatch.setattr(seed, "_strip_country_from_search_location", boom)
    monkeypatch.setattr(seed, "run_migration_statements", lambda db, statements: [])

    seed.run_migrations(test_db)      # raises if the guard is missing

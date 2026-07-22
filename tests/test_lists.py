"""Tests for research list parsing and IMDb->TMDb resolution."""

import pytest

from emby_collection_creator.lists import (
    ListEntry,
    parse_list_file,
    resolve_entries,
)


TABLE = """\
# IMDb IDs for movies based on video games

Some prose that mentions no ids at all.

| # | Movie Title | Year | IMDb ID |
|---|------------|------|---------|
| 1 | Mortal Kombat | 1995 | tt0113855 |
| 2 | Double Dragon | 1994 | tt0106761 |
"""


def test_parse_extracts_entries_and_ignores_prose():
    entries = parse_list_file(TABLE)

    assert entries == [
        ListEntry(imdb_id="tt0113855", title="Mortal Kombat", year=1995),
        ListEntry(imdb_id="tt0106761", title="Double Dragon", year=1994),
    ]


def test_parse_dedupes_repeated_ids():
    text = "| A | 1990 | tt1234567 |\n| A again | 1990 | tt1234567 |"

    entries = parse_list_file(text)

    assert len(entries) == 1


@pytest.mark.parametrize(
    "line,expected_title,expected_year",
    [
        pytest.param(
            "| 3 | Street Fighter (JCVD) | 1994 | tt0111301 |",
            "Street Fighter (JCVD)",
            1994,
            id="annotated-title",
        ),
        pytest.param(
            "| tt0111301 | 1994 | Street Fighter |",
            "Street Fighter",
            1994,
            id="reordered-columns",
        ),
        pytest.param(
            "- Some Movie tt0111301",
            "- Some Movie tt0111301".strip("- ").replace(" tt0111301", ""),
            None,
            id="no-year-plain-line",
        ),
    ],
)
def test_parse_handles_layout_variations(line, expected_title, expected_year):
    entries = parse_list_file(line)

    assert entries[0].year == expected_year
    assert expected_title.split("(")[0].strip() in entries[0].title


def test_parse_returns_empty_without_ids():
    assert parse_list_file("no ids here\n| just | a | table |") == []


@pytest.fixture
def mock_tmdb(mocker):
    tmdb = mocker.MagicMock()
    tmdb.find_by_imdb_id = mocker.AsyncMock()
    return tmdb


async def test_resolve_maps_imdb_to_tmdb(mock_tmdb):
    mock_tmdb.find_by_imdb_id.return_value = {
        "id": 9312,
        "title": "Mortal Kombat",
        "release_date": "1995-08-18",
    }

    report = await resolve_entries(
        mock_tmdb, [ListEntry("tt0113855", "Mortal Kombat", 1995)]
    )

    assert report["resolved"] == [{"imdb_id": "tt0113855", "tmdb_id": "9312"}]
    assert report["unresolved"] == []
    assert report["mismatched"] == []


async def test_resolve_reports_unresolved(mock_tmdb):
    mock_tmdb.find_by_imdb_id.return_value = None

    report = await resolve_entries(
        mock_tmdb, [ListEntry("tt9999999", "Bogus", 2001)]
    )

    assert report["resolved"] == []
    assert report["unresolved"] == [{"imdb_id": "tt9999999", "title": "Bogus"}]


async def test_resolve_flags_year_mismatch(mock_tmdb):
    mock_tmdb.find_by_imdb_id.return_value = {
        "id": 5,
        "title": "Oldboy",
        "release_date": "2013-11-27",
    }

    report = await resolve_entries(mock_tmdb, [ListEntry("tt0364569", "Oldboy", 2003)])

    assert len(report["mismatched"]) == 1
    assert report["mismatched"][0]["expected"] == "Oldboy (2003)"
    assert report["mismatched"][0]["tmdb_says"] == "Oldboy (2013)"
    # still resolved, just flagged for review
    assert len(report["resolved"]) == 1


@pytest.mark.parametrize(
    "entry_year,release_date,is_flagged",
    [
        pytest.param(1995, "1995-01-01", False, id="exact-match"),
        pytest.param(1995, "1996-01-01", False, id="off-by-one-tolerated"),
        pytest.param(1995, "1998-01-01", True, id="off-by-three-flagged"),
        pytest.param(None, "1995-01-01", False, id="no-year-in-file"),
        pytest.param(1995, None, False, id="no-release-date"),
    ],
)
async def test_year_mismatch_tolerance(
    mock_tmdb, entry_year, release_date, is_flagged
):
    mock_tmdb.find_by_imdb_id.return_value = {
        "id": 1,
        "title": "X",
        "release_date": release_date,
    }

    report = await resolve_entries(mock_tmdb, [ListEntry("tt1111111", "X", entry_year)])

    assert bool(report["mismatched"]) is is_flagged

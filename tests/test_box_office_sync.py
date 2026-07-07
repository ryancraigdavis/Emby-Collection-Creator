"""Tests for top-box-office criteria-based collection sync."""

import pytest

from emby_collection_creator.mcp.server import (
    _collect_top_box_office_tmdb_ids,
    _match_emby_movies_by_tmdb_ids,
    sync_collection_by_criteria,
)
from emby_collection_creator.models.emby import Movie


@pytest.fixture
def mock_tmdb(mocker):
    tmdb = mocker.MagicMock()
    tmdb.discover_movies = mocker.AsyncMock()
    return tmdb


@pytest.fixture
def mock_emby(mocker):
    emby = mocker.MagicMock()
    emby.get_movies = mocker.AsyncMock()
    emby.get_collection_items = mocker.AsyncMock(return_value=[])
    emby.add_to_collection = mocker.AsyncMock()
    return emby


@pytest.mark.parametrize(
    "min_year,max_year,per_year,expected_calls,expected_ids",
    [
        pytest.param(2020, 2020, 3, 1, {"100", "101", "102"}, id="single-year"),
        pytest.param(2018, 2020, 2, 3, {"100", "101"}, id="three-year-range"),
        pytest.param(2020, 2020, 0, 1, set(), id="zero-per-year"),
    ],
)
async def test_collect_top_box_office_tmdb_ids(
    mock_tmdb, min_year, max_year, per_year, expected_calls, expected_ids
):
    mock_tmdb.discover_movies.return_value = [
        {"tmdb_id": 100, "title": "A"},
        {"tmdb_id": 101, "title": "B"},
        {"tmdb_id": 102, "title": "C"},
    ][:per_year]

    result = await _collect_top_box_office_tmdb_ids(
        mock_tmdb, min_year, max_year, per_year
    )

    assert result == expected_ids
    assert mock_tmdb.discover_movies.call_count == expected_calls


async def test_collect_skips_missing_tmdb_id(mock_tmdb):
    mock_tmdb.discover_movies.return_value = [
        {"tmdb_id": 100, "title": "A"},
        {"tmdb_id": None, "title": "B"},
        {"title": "C"},
    ]

    result = await _collect_top_box_office_tmdb_ids(mock_tmdb, 2020, 2020, 3)

    assert result == {"100"}


async def test_match_emby_movies_empty_input(mock_emby):
    result = await _match_emby_movies_by_tmdb_ids(mock_emby, set())

    assert result == set()
    mock_emby.get_movies.assert_not_called()


async def test_match_emby_movies_filters_by_tmdb_id(mock_emby):
    mock_emby.get_movies.return_value = (
        [
            Movie(id="m1", name="One", tmdb_id="100"),
            Movie(id="m2", name="Two", tmdb_id="999"),
            Movie(id="m3", name="Three", tmdb_id="101"),
            Movie(id="m4", name="Four", tmdb_id=None),
        ],
        4,
    )

    result = await _match_emby_movies_by_tmdb_ids(mock_emby, {"100", "101"})

    assert result == {"m1", "m3"}


async def test_match_emby_movies_paginates(mock_emby):
    mock_emby.get_movies.side_effect = [
        ([Movie(id="m1", name="One", tmdb_id="100")], 250),
        ([Movie(id="m2", name="Two", tmdb_id="200")], 250),
        ([], 250),
    ]

    result = await _match_emby_movies_by_tmdb_ids(mock_emby, {"100", "200"})

    assert result == {"m1", "m2"}


async def test_sync_with_box_office_criteria(mock_tmdb, mock_emby):
    mock_tmdb.discover_movies.return_value = [
        {"tmdb_id": 100, "title": "A"},
        {"tmdb_id": 200, "title": "B"},
    ]
    mock_emby.get_movies.return_value = (
        [
            Movie(id="m1", name="A", tmdb_id="100"),
            Movie(id="m2", name="B", tmdb_id="200"),
        ],
        2,
    )

    result = await sync_collection_by_criteria(
        emby=mock_emby,
        tmdb=mock_tmdb,
        collection_id="c1",
        collection_name="Box Office 2020",
        criteria={
            "top_box_office_min_year": 2020,
            "top_box_office_max_year": 2020,
            "top_box_office_per_year": 2,
        },
    )

    mock_emby.add_to_collection.assert_awaited_once_with("c1", mocker_listish_or_set())
    assert "Box Office 2020" in result
    assert "2 movies match" in result
    assert "+2 added" in result


def mocker_listish_or_set():
    """Match either list or set since add_to_collection takes a list of IDs in any order."""

    class _Match:
        def __eq__(self, other):
            return isinstance(other, list) and set(other) == {"m1", "m2"}

    return _Match()


async def test_sync_box_office_default_per_year(mock_tmdb, mock_emby):
    mock_tmdb.discover_movies.return_value = []
    mock_emby.get_movies.return_value = ([], 0)

    await sync_collection_by_criteria(
        emby=mock_emby,
        tmdb=mock_tmdb,
        collection_id="c1",
        collection_name="X",
        criteria={
            "top_box_office_min_year": 2020,
            "top_box_office_max_year": 2020,
        },
    )

    mock_tmdb.discover_movies.assert_awaited_once()
    assert mock_tmdb.discover_movies.call_args.kwargs["limit"] == 10

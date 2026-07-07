"""Tests for TMDb-list criteria-based collection sync."""

import pytest

from emby_collection_creator.mcp.server import sync_collection_by_criteria
from emby_collection_creator.models.emby import Movie


@pytest.fixture
def mock_tmdb(mocker):
    tmdb = mocker.MagicMock()
    tmdb.get_list_movie_ids = mocker.AsyncMock()
    return tmdb


@pytest.fixture
def mock_emby(mocker):
    emby = mocker.MagicMock()
    emby.get_movies = mocker.AsyncMock()
    emby.get_collection_items = mocker.AsyncMock(return_value=[])
    emby.add_to_collection = mocker.AsyncMock()
    return emby


async def test_sync_with_tmdb_list_criteria(mock_tmdb, mock_emby):
    mock_tmdb.get_list_movie_ids.return_value = {"100", "200"}
    mock_emby.get_movies.return_value = (
        [
            Movie(id="m1", name="A", tmdb_id="100"),
            Movie(id="m2", name="B", tmdb_id="200"),
            Movie(id="m3", name="C", tmdb_id="999"),
        ],
        3,
    )

    result = await sync_collection_by_criteria(
        emby=mock_emby,
        tmdb=mock_tmdb,
        collection_id="c1",
        collection_name="Park Chan-wook",
        criteria={"tmdb_list_id": "8291234"},
    )

    mock_tmdb.get_list_movie_ids.assert_awaited_once_with("8291234")
    assert "Park Chan-wook" in result
    assert "from TMDb list" in result
    assert "2 movies match" in result
    assert "+2 added" in result


async def test_sync_tmdb_list_only_adds_new(mock_tmdb, mock_emby):
    mock_tmdb.get_list_movie_ids.return_value = {"100", "200"}
    mock_emby.get_collection_items.return_value = ["m1"]
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
        collection_name="X",
        criteria={"tmdb_list_id": "42"},
    )

    mock_emby.add_to_collection.assert_awaited_once_with("c1", ["m2"])
    assert "+1 added" in result


async def test_sync_tmdb_list_no_matches_adds_nothing(mock_tmdb, mock_emby):
    mock_tmdb.get_list_movie_ids.return_value = set()
    mock_emby.get_movies.return_value = ([], 0)

    result = await sync_collection_by_criteria(
        emby=mock_emby,
        tmdb=mock_tmdb,
        collection_id="c1",
        collection_name="Empty",
        criteria={"tmdb_list_id": "42"},
    )

    mock_emby.add_to_collection.assert_not_awaited()
    assert "0 movies match" in result
    assert "+0 added" in result

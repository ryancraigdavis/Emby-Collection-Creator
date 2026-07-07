"""Tests for TMDbService list read/write and auth methods."""

import pytest

from emby_collection_creator.services.tmdb import TMDbService


@pytest.fixture
def service(mocker):
    tmdb = TMDbService(api_key="k", read_access_token="read")
    tmdb._client = mocker.MagicMock()
    tmdb._client.get = mocker.AsyncMock()
    tmdb._client.post = mocker.AsyncMock()
    return tmdb


def _resp(mocker, payload, status=200):
    resp = mocker.MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


async def test_get_list_movie_ids_paginates_and_filters_tv(service, mocker):
    service._client.get.side_effect = [
        _resp(mocker, {
            "page": 1,
            "total_pages": 2,
            "results": [
                {"id": 100, "media_type": "movie"},
                {"id": 555, "media_type": "tv"},
            ],
        }),
        _resp(mocker, {
            "page": 2,
            "total_pages": 2,
            "results": [{"id": 200, "media_type": "movie"}],
        }),
    ]

    result = await service.get_list_movie_ids("42")

    assert result == {"100", "200"}
    assert service._client.get.call_count == 2


async def test_write_headers_requires_auth(service):
    with pytest.raises(ValueError, match="TMDb authentication required"):
        service._write_headers()


async def test_complete_auth_sets_user_token(service, mocker):
    service._client.post.return_value = _resp(
        mocker, {"access_token": "user-tok", "account_id": "acct"}
    )

    data = await service.complete_auth("req-tok")

    assert data["access_token"] == "user-tok"
    assert service.user_access_token == "user-tok"


async def test_complete_auth_returns_none_on_failure(service, mocker):
    service._client.post.return_value = _resp(mocker, {}, status=401)

    result = await service.complete_auth("bad-tok")

    assert result is None
    assert service.user_access_token is None


async def test_create_list_requires_auth(service):
    with pytest.raises(ValueError, match="TMDb authentication required"):
        await service.create_list("My List")


async def test_create_list_returns_id_when_authed(service, mocker):
    service.user_access_token = "user-tok"
    service._client.post.return_value = _resp(
        mocker, {"id": 8291234, "success": True}
    )

    data = await service.create_list("Park Chan-wook", "desc", public=True)

    assert data["id"] == 8291234


async def test_add_to_list_counts_successes(service, mocker):
    service.user_access_token = "user-tok"
    service._client.post.return_value = _resp(
        mocker,
        {"results": [{"success": True}, {"success": True}, {"success": False}]},
    )

    result = await service.add_to_list("42", ["100", "200", "300"])

    assert result == {"added": 2, "requested": 3}

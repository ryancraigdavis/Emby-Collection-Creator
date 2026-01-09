"""Trakt.tv API service for trending, popular, and list data."""

import httpx
from attrs import define

from ..models.trakt import (
    TraktMovie,
    TraktTrendingMovie,
    TraktList,
    TraktListItem,
    TraktRecommendation,
)


@define
class TraktService:
    """Client for Trakt.tv API."""

    client_id: str
    client_secret: str
    _client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://api.trakt.tv",
                headers={
                    "Content-Type": "application/json",
                    "trakt-api-version": "2",
                    "trakt-api-key": self.client_id,
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _parse_movie(self, movie_data: dict) -> TraktMovie:
        """Parse movie data from Trakt API response."""
        ids = movie_data.get("ids", {})
        return TraktMovie(
            title=movie_data.get("title", ""),
            year=movie_data.get("year"),
            trakt_id=ids.get("trakt", 0),
            slug=ids.get("slug", ""),
            imdb_id=ids.get("imdb"),
            tmdb_id=ids.get("tmdb"),
        )

    async def get_trending_movies(self, limit: int = 20) -> list[TraktTrendingMovie]:
        """Get currently trending movies."""
        client = await self._get_client()
        resp = await client.get(
            "/movies/trending",
            params={"limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()

        return [
            TraktTrendingMovie(
                movie=self._parse_movie(item.get("movie", {})),
                watchers=item.get("watchers", 0),
            )
            for item in data
        ]

    async def get_popular_movies(self, limit: int = 20) -> list[TraktMovie]:
        """Get popular movies."""
        client = await self._get_client()
        resp = await client.get(
            "/movies/popular",
            params={"limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()

        return [self._parse_movie(item) for item in data]

    async def get_most_watched_movies(
        self, period: str = "weekly", limit: int = 20
    ) -> list[TraktMovie]:
        """Get most watched movies for a period (weekly, monthly, yearly, all)."""
        client = await self._get_client()
        resp = await client.get(
            f"/movies/watched/{period}",
            params={"limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()

        return [self._parse_movie(item.get("movie", {})) for item in data]

    async def get_most_collected_movies(
        self, period: str = "weekly", limit: int = 20
    ) -> list[TraktMovie]:
        """Get most collected movies for a period (weekly, monthly, yearly, all)."""
        client = await self._get_client()
        resp = await client.get(
            f"/movies/collected/{period}",
            params={"limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()

        return [self._parse_movie(item.get("movie", {})) for item in data]

    async def get_anticipated_movies(self, limit: int = 20) -> list[TraktMovie]:
        """Get most anticipated upcoming movies."""
        client = await self._get_client()
        resp = await client.get(
            "/movies/anticipated",
            params={"limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()

        return [self._parse_movie(item.get("movie", {})) for item in data]

    async def get_box_office_movies(self) -> list[TraktMovie]:
        """Get current box office movies."""
        client = await self._get_client()
        resp = await client.get("/movies/boxoffice")
        resp.raise_for_status()
        data = resp.json()

        return [self._parse_movie(item.get("movie", {})) for item in data]

    async def search_lists(
        self, query: str, limit: int = 10
    ) -> list[TraktList]:
        """Search for public lists by name."""
        client = await self._get_client()
        resp = await client.get(
            "/search/list",
            params={"query": query, "limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()

        lists = []
        for item in data:
            list_data = item.get("list", {})
            user_data = list_data.get("user", {})
            ids = list_data.get("ids", {})
            lists.append(
                TraktList(
                    name=list_data.get("name", ""),
                    description=list_data.get("description"),
                    item_count=list_data.get("item_count", 0),
                    likes=list_data.get("likes", 0),
                    user=user_data.get("username", ""),
                    list_id=str(ids.get("trakt", "")),
                    slug=ids.get("slug", ""),
                )
            )
        return lists

    async def get_list_items(
        self, username: str, list_slug: str, limit: int = 100, offset: int = 0
    ) -> tuple[list[TraktListItem], int]:
        """Get items from a public list (movies only) with pagination.

        Returns tuple of (items, total_count).
        Note: Trakt uses page-based pagination internally.
        """
        client = await self._get_client()
        # Trakt uses page/limit, so we calculate page from offset
        page = (offset // limit) + 1 if limit > 0 else 1

        resp = await client.get(
            f"/users/{username}/lists/{list_slug}/items/movies",
            params={"limit": limit, "page": page},
        )
        resp.raise_for_status()
        data = resp.json()

        # Get total count from headers (Trakt returns this in X-Pagination-Item-Count)
        total_count = int(resp.headers.get("X-Pagination-Item-Count", len(data)))

        items = []
        for idx, item in enumerate(data):
            movie_data = item.get("movie", {})
            if movie_data:
                items.append(
                    TraktListItem(
                        rank=item.get("rank", offset + idx + 1),
                        movie=self._parse_movie(movie_data),
                        listed_at=item.get("listed_at"),
                    )
                )
        return items, total_count

    async def get_related_movies(
        self, trakt_id: int, limit: int = 20
    ) -> list[TraktMovie]:
        """Get movies related to a specific movie."""
        client = await self._get_client()
        resp = await client.get(
            f"/movies/{trakt_id}/related",
            params={"limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()

        return [self._parse_movie(item) for item in data]

    async def search_movie(self, query: str) -> TraktMovie | None:
        """Search for a movie by title and return the first result."""
        client = await self._get_client()
        resp = await client.get(
            "/search/movie",
            params={"query": query, "limit": 1},
        )
        resp.raise_for_status()
        data = resp.json()

        if data:
            return self._parse_movie(data[0].get("movie", {}))
        return None

"""TasteDive API service for movie recommendations."""

import httpx
from attrs import define

from ..models.tastedive import TasteDiveItem, TasteDiveResponse


@define
class TasteDiveService:
    """Client for TasteDive API."""

    api_key: str
    _client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://tastedive.com/api",
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_similar(
        self,
        titles: list[str],
        media_type: str = "movie",
        limit: int = 20,
        include_info: bool = True,
    ) -> TasteDiveResponse:
        """Get similar movies based on one or more titles."""
        client = await self._get_client()

        params = {
            "q": ",".join(titles),
            "type": media_type,
            "limit": limit,
            "info": 1 if include_info else 0,
            "k": self.api_key,
        }

        resp = await client.get("/similar", params=params)
        resp.raise_for_status()
        data = resp.json()

        similar_data = data.get("Similar", {})

        query_items = [
            self._parse_item(item) for item in similar_data.get("Info", [])
        ]
        recommendations = [
            self._parse_item(item) for item in similar_data.get("Results", [])
        ]

        return TasteDiveResponse(
            query_items=query_items,
            recommendations=recommendations,
        )

    def _parse_item(self, item: dict) -> TasteDiveItem:
        """Parse a TasteDive item from API response."""
        return TasteDiveItem(
            name=item.get("Name", ""),
            type=item.get("Type", ""),
            description=item.get("wTeaser"),
            wikipedia_url=item.get("wUrl"),
            youtube_url=item.get("yUrl"),
            youtube_id=item.get("yID"),
        )

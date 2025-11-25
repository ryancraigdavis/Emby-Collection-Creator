"""Emby API service."""

import httpx
from attrs import define

from ..models.emby import Movie, Collection


@define
class EmbyService:
    """Client for Emby REST API."""

    base_url: str
    api_key: str
    _client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"X-Emby-Token": self.api_key},
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_user_id(self) -> str:
        """Get the first admin user ID."""
        client = await self._get_client()
        resp = await client.get("/Users")
        resp.raise_for_status()
        users = resp.json()
        for user in users:
            if user.get("Policy", {}).get("IsAdministrator"):
                return user["Id"]
        return users[0]["Id"]

    async def get_movies(self, user_id: str | None = None) -> list[Movie]:
        """Fetch all movies from the library."""
        if user_id is None:
            user_id = await self.get_user_id()

        client = await self._get_client()
        resp = await client.get(
            f"/Users/{user_id}/Items",
            params={
                "IncludeItemTypes": "Movie",
                "Recursive": "true",
                "Fields": "Genres,Tags,Overview,ProviderIds,Studios,CommunityRating,CriticRating,ProductionYear",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        movies = []
        for item in data.get("Items", []):
            provider_ids = item.get("ProviderIds", {})
            movies.append(
                Movie(
                    id=item["Id"],
                    name=item["Name"],
                    year=item.get("ProductionYear"),
                    genres=item.get("Genres", []),
                    tags=item.get("Tags", []),
                    community_rating=item.get("CommunityRating"),
                    critic_rating=item.get("CriticRating"),
                    overview=item.get("Overview"),
                    tmdb_id=provider_ids.get("Tmdb"),
                    imdb_id=provider_ids.get("Imdb"),
                    production_year=item.get("ProductionYear"),
                    studios=[s.get("Name", "") for s in item.get("Studios", [])],
                )
            )
        return movies

    async def get_collections(self, user_id: str | None = None) -> list[Collection]:
        """Fetch all collections (BoxSets)."""
        if user_id is None:
            user_id = await self.get_user_id()

        client = await self._get_client()
        resp = await client.get(
            f"/Users/{user_id}/Items",
            params={
                "IncludeItemTypes": "BoxSet",
                "Recursive": "true",
                "Fields": "Overview",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        collections = []
        for item in data.get("Items", []):
            collections.append(
                Collection(
                    id=item["Id"],
                    name=item["Name"],
                    overview=item.get("Overview"),
                )
            )
        return collections

    async def get_collection(self, collection_id: str) -> dict:
        """Get full collection item data."""
        client = await self._get_client()
        resp = await client.get(f"/Items/{collection_id}")
        resp.raise_for_status()
        return resp.json()

    async def update_collection_overview(
        self, collection_id: str, overview: str
    ) -> None:
        """Update the overview/description of a collection."""
        client = await self._get_client()
        item_data = await self.get_collection(collection_id)
        item_data["Overview"] = overview
        resp = await client.post(f"/Items/{collection_id}", json=item_data)
        resp.raise_for_status()

    async def get_collection_items(
        self, collection_id: str, user_id: str | None = None
    ) -> list[str]:
        """Get item IDs in a collection."""
        if user_id is None:
            user_id = await self.get_user_id()

        client = await self._get_client()
        resp = await client.get(
            f"/Users/{user_id}/Items",
            params={
                "ParentId": collection_id,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["Id"] for item in data.get("Items", [])]

    async def create_collection(
        self, name: str, item_ids: list[str] | None = None
    ) -> Collection:
        """Create a new collection."""
        client = await self._get_client()
        params = {"Name": name}
        if item_ids:
            params["Ids"] = ",".join(item_ids)

        resp = await client.post("/Collections", params=params)
        resp.raise_for_status()
        data = resp.json()

        return Collection(
            id=data["Id"],
            name=name,
            item_ids=item_ids or [],
        )

    async def add_to_collection(
        self, collection_id: str, item_ids: list[str]
    ) -> None:
        """Add items to an existing collection."""
        client = await self._get_client()
        resp = await client.post(
            f"/Collections/{collection_id}/Items",
            params={"Ids": ",".join(item_ids)},
        )
        resp.raise_for_status()

    async def remove_from_collection(
        self, collection_id: str, item_ids: list[str]
    ) -> None:
        """Remove items from a collection."""
        client = await self._get_client()
        resp = await client.delete(
            f"/Collections/{collection_id}/Items",
            params={"Ids": ",".join(item_ids)},
        )
        resp.raise_for_status()

    async def delete_collection(self, collection_id: str) -> None:
        """Delete a collection."""
        client = await self._get_client()
        resp = await client.delete(f"/Items/{collection_id}")
        resp.raise_for_status()

    async def search_movies(
        self,
        user_id: str | None = None,
        genres: list[str] | None = None,
        years: tuple[int, int] | None = None,
        search_term: str | None = None,
    ) -> list[Movie]:
        """Search movies with filters."""
        if user_id is None:
            user_id = await self.get_user_id()

        client = await self._get_client()
        params = {
            "IncludeItemTypes": "Movie",
            "Recursive": "true",
            "Fields": "Genres,Tags,Overview,ProviderIds,Studios,CommunityRating,CriticRating,ProductionYear",
        }

        if genres:
            params["Genres"] = "|".join(genres)
        if years:
            params["MinYear"] = years[0]
            params["MaxYear"] = years[1]
        if search_term:
            params["SearchTerm"] = search_term

        resp = await client.get(f"/Users/{user_id}/Items", params=params)
        resp.raise_for_status()
        data = resp.json()

        movies = []
        for item in data.get("Items", []):
            provider_ids = item.get("ProviderIds", {})
            movies.append(
                Movie(
                    id=item["Id"],
                    name=item["Name"],
                    year=item.get("ProductionYear"),
                    genres=item.get("Genres", []),
                    tags=item.get("Tags", []),
                    community_rating=item.get("CommunityRating"),
                    critic_rating=item.get("CriticRating"),
                    overview=item.get("Overview"),
                    tmdb_id=provider_ids.get("Tmdb"),
                    imdb_id=provider_ids.get("Imdb"),
                    production_year=item.get("ProductionYear"),
                    studios=[s.get("Name", "") for s in item.get("Studios", [])],
                )
            )
        return movies

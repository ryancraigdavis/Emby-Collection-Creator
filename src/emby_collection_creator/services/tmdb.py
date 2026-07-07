"""TMDb API service for metadata enrichment."""

import httpx
from attrs import define

from ..models.tmdb import TMDbMovie, TMDbKeyword


B_MOVIE_STUDIOS = {
    "troma",
    "full moon features",
    "the asylum",
    "cannon films",
    "american international pictures",
    "new world pictures",
    "crown international pictures",
    "empire pictures",
    "pm entertainment",
}

CAMPY_KEYWORDS = {
    "slasher",
    "gore",
    "b-movie",
    "campy",
    "cult film",
    "splatter film",
    "exploitation",
    "grindhouse",
    "video nasty",
    "low budget",
    "final girl",
    "scream queen",
}


@define
class TMDbService:
    """Client for TMDb API."""

    api_key: str
    read_access_token: str
    user_access_token: str | None = None
    _client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://api.themoviedb.org/3",
                headers={
                    "Authorization": f"Bearer {self.read_access_token}",
                    "Accept": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_movie(self, tmdb_id: str) -> TMDbMovie | None:
        """Fetch movie details including keywords and budget."""
        client = await self._get_client()
        try:
            resp = await client.get(
                f"/movie/{tmdb_id}",
                params={"append_to_response": "keywords"},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            return None

        data = resp.json()
        keywords_data = data.get("keywords", {}).get("keywords", [])

        return TMDbMovie(
            id=data["id"],
            title=data["title"],
            budget=data.get("budget"),
            revenue=data.get("revenue"),
            keywords=[
                TMDbKeyword(id=k["id"], name=k["name"]) for k in keywords_data
            ],
            vote_average=data.get("vote_average"),
            vote_count=data.get("vote_count"),
            production_companies=[
                c["name"] for c in data.get("production_companies", [])
            ],
            release_date=data.get("release_date"),
            tagline=data.get("tagline"),
        )

    async def search_movie(self, title: str, year: int | None = None) -> int | None:
        """Search for a movie and return its TMDb ID."""
        client = await self._get_client()
        params = {"query": title}
        if year:
            params["year"] = year

        resp = await client.get("/search/movie", params=params)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if results:
            return results[0]["id"]
        return None

    async def discover_movies(
        self,
        genres: list[int] | None = None,
        keywords: list[int] | None = None,
        max_vote_average: float | None = None,
        min_vote_average: float | None = None,
        year_gte: int | None = None,
        year_lte: int | None = None,
        sort_by: str = "popularity.desc",
        limit: int = 20,
    ) -> list[dict]:
        """Discover movies matching criteria, returns list of movie dicts."""
        client = await self._get_client()
        params = {"sort_by": sort_by}

        if genres:
            params["with_genres"] = ",".join(str(g) for g in genres)
        if keywords:
            params["with_keywords"] = "|".join(str(k) for k in keywords)
        if max_vote_average is not None:
            params["vote_average.lte"] = max_vote_average
        if min_vote_average is not None:
            params["vote_average.gte"] = min_vote_average
        if year_gte:
            params["primary_release_date.gte"] = f"{year_gte}-01-01"
        if year_lte:
            params["primary_release_date.lte"] = f"{year_lte}-12-31"

        results = []
        page = 1
        while len(results) < limit:
            params["page"] = page
            resp = await client.get("/discover/movie", params=params)
            resp.raise_for_status()
            data = resp.json()
            page_results = data.get("results", [])
            if not page_results:
                break
            results.extend(page_results)
            page += 1

        return [
            {
                "tmdb_id": m["id"],
                "title": m.get("title", ""),
                "release_date": m.get("release_date"),
                "revenue": m.get("revenue"),
            }
            for m in results[:limit]
        ]

    async def get_list_movie_ids(self, list_id: str) -> set[str]:
        """Fetch all movie TMDb IDs from a public TMDb (v4) list."""
        client = await self._get_client()
        tmdb_ids: set[str] = set()
        page = 1
        while True:
            resp = await client.get(
                f"https://api.themoviedb.org/4/list/{list_id}",
                params={"page": page},
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("results", []):
                if item.get("media_type") == "movie" and item.get("id"):
                    tmdb_ids.add(str(item["id"]))
            if page >= data.get("total_pages", 1):
                break
            page += 1
        return tmdb_ids

    async def start_auth(self) -> dict:
        """Create a v4 request token. Returns the token and its approval URL."""
        client = await self._get_client()
        resp = await client.post("https://api.themoviedb.org/4/auth/request_token")
        resp.raise_for_status()
        token = resp.json()["request_token"]
        return {
            "request_token": token,
            "verification_url": (
                f"https://www.themoviedb.org/auth/access?request_token={token}"
            ),
        }

    async def complete_auth(self, request_token: str) -> dict | None:
        """Exchange an approved request token for a user access token."""
        client = await self._get_client()
        resp = await client.post(
            "https://api.themoviedb.org/4/auth/access_token",
            json={"request_token": request_token},
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        self.user_access_token = data["access_token"]
        return data

    def _write_headers(self) -> dict:
        if not self.user_access_token:
            raise ValueError("TMDb authentication required. Use tmdb_start_auth first.")
        return {"Authorization": f"Bearer {self.user_access_token}"}

    async def create_list(
        self, name: str, description: str = "", public: bool = True
    ) -> dict:
        """Create a new v4 list on the authenticated user's account."""
        client = await self._get_client()
        resp = await client.post(
            "https://api.themoviedb.org/4/list",
            json={
                "name": name,
                "description": description,
                "iso_639_1": "en",
                "public": public,
            },
            headers=self._write_headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def add_to_list(self, list_id: str, tmdb_ids: list[str]) -> dict:
        """Add movies to a v4 list by TMDb IDs."""
        client = await self._get_client()
        headers = self._write_headers()
        added = 0
        for i in range(0, len(tmdb_ids), 100):
            batch = tmdb_ids[i : i + 100]
            resp = await client.post(
                f"https://api.themoviedb.org/4/list/{list_id}/items",
                json={
                    "items": [
                        {"media_type": "movie", "media_id": int(mid)} for mid in batch
                    ]
                },
                headers=headers,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            added += sum(1 for r in results if r.get("success"))
        return {"added": added, "requested": len(tmdb_ids)}

    def is_b_movie_studio(self, companies: list[str]) -> bool:
        """Check if any production company is a known b-movie studio."""
        return any(c.lower() in B_MOVIE_STUDIOS for c in companies)

    def has_campy_keywords(self, keywords: list[TMDbKeyword]) -> bool:
        """Check if movie has keywords indicating campy/cult status."""
        keyword_names = {k.name.lower() for k in keywords}
        return bool(keyword_names & CAMPY_KEYWORDS)

    def calculate_b_movie_score(self, movie: TMDbMovie) -> float:
        """Calculate a 0-1 score for how 'b-movie' a film likely is."""
        score = 0.0
        factors = 0

        # Budget factor (lower = more likely b-movie)
        if movie.budget is not None and movie.budget > 0:
            factors += 1
            if movie.budget < 1_000_000:
                score += 1.0
            elif movie.budget < 5_000_000:
                score += 0.7
            elif movie.budget < 15_000_000:
                score += 0.3

        # Vote average factor (mid-range suggests cult appeal)
        if movie.vote_average is not None:
            factors += 1
            if 4.0 <= movie.vote_average <= 6.5:
                score += 0.8
            elif 3.0 <= movie.vote_average < 4.0:
                score += 0.6
            elif movie.vote_average < 3.0:
                score += 0.4

        # Keywords factor
        if movie.keywords:
            factors += 1
            if self.has_campy_keywords(movie.keywords):
                score += 1.0

        # Production company factor
        if movie.production_companies:
            factors += 1
            if self.is_b_movie_studio(movie.production_companies):
                score += 1.0

        return score / factors if factors > 0 else 0.0

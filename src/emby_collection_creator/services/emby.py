"""Emby API service."""

import httpx
from attrs import define

from ..models.emby import AudioStream, MediaInfo, Movie, MovieSummary, Collection, VideoStream


# Minimal fields for list views - excludes heavy data like Overview, MediaSources
MINIMAL_FIELDS = "Genres,Tags,ProviderIds,CommunityRating,ProductionYear"

# Full fields for detailed views
FULL_FIELDS = "Genres,Tags,Overview,ProviderIds,Studios,CommunityRating,CriticRating,ProductionYear,MediaSources"


def _parse_video_stream(stream: dict) -> VideoStream:
    """Parse video stream data from Emby MediaStream."""
    width = stream.get("Width")
    height = stream.get("Height")
    video_range = stream.get("VideoRange", "SDR")
    video_range_type = stream.get("VideoRangeType") or "SDR"
    dv_profile = stream.get("DvProfile")
    dv_el_present = stream.get("DvElPresent", False)

    # Determine HDR type
    hdr_type = "SDR"
    if "Dolby Vision" in video_range_type or dv_profile is not None:
        hdr_type = "Dolby Vision"
    elif "HDR10+" in video_range_type:
        hdr_type = "HDR10+"
    elif "HDR10" in video_range_type or video_range == "HDR":
        hdr_type = "HDR10"
    elif "HLG" in video_range_type:
        hdr_type = "HLG"

    # Determine DV layer type (FEL vs MEL)
    dv_layer_type = None
    if dv_profile is not None:
        if dv_el_present:
            dv_layer_type = "FEL"
        else:
            dv_layer_type = "MEL"

    return VideoStream(
        codec=stream.get("Codec"),
        codec_tag=stream.get("CodecTag"),
        width=width,
        height=height,
        bit_depth=stream.get("BitDepth"),
        bitrate=stream.get("BitRate"),
        hdr_type=hdr_type,
        video_range=video_range,
        color_space=stream.get("ColorSpace"),
        color_transfer=stream.get("ColorTransfer"),
        color_primaries=stream.get("ColorPrimaries"),
        dv_profile=dv_profile,
        dv_level=stream.get("DvLevel"),
        dv_bl_present=stream.get("DvBlPresent", False),
        dv_el_present=dv_el_present,
        dv_rpu_present=stream.get("DvRpuPresent", False),
        is_4k=width is not None and width >= 3840,
        is_hdr=video_range == "HDR" or hdr_type != "SDR",
        is_dolby_vision=hdr_type == "Dolby Vision",
        is_hdr10_plus=hdr_type == "HDR10+",
        dv_layer_type=dv_layer_type,
    )


def _parse_audio_stream(stream: dict) -> AudioStream:
    """Parse audio stream data from Emby MediaStream."""
    codec = (stream.get("Codec") or "").lower()
    profile = (stream.get("Profile") or "").lower()
    display_title = (stream.get("DisplayTitle") or "").lower()

    is_atmos = "atmos" in profile or "atmos" in display_title
    is_dts_x = "dts:x" in profile or "dts-x" in profile or "dts:x" in display_title
    is_lossless = (
        codec in ("truehd", "flac", "mlp")
        or "dts-hd ma" in profile
        or "dts-hd.ma" in codec
        or "ma" in profile
        and "dts" in codec
    )

    return AudioStream(
        codec=stream.get("Codec"),
        channels=stream.get("Channels"),
        channel_layout=stream.get("ChannelLayout"),
        bitrate=stream.get("BitRate"),
        sample_rate=stream.get("SampleRate"),
        language=stream.get("Language"),
        is_default=stream.get("IsDefault", False),
        is_atmos=is_atmos,
        is_dts_x=is_dts_x,
        is_lossless=is_lossless,
    )


def _parse_single_media_source(source: dict) -> MediaInfo:
    """Parse a single media source into MediaInfo."""
    video_stream = None
    audio_streams = []

    for stream in source.get("MediaStreams", []):
        if stream.get("Type") == "Video" and video_stream is None:
            video_stream = _parse_video_stream(stream)
        elif stream.get("Type") == "Audio":
            audio_streams.append(_parse_audio_stream(stream))

    # Find primary audio (default or first)
    primary_audio = None
    for audio in audio_streams:
        if audio.is_default:
            primary_audio = audio
            break
    if primary_audio is None and audio_streams:
        primary_audio = audio_streams[0]

    return MediaInfo(
        container=source.get("Container"),
        file_size=source.get("Size"),
        total_bitrate=source.get("Bitrate"),
        video=video_stream,
        audio_streams=audio_streams,
        primary_audio=primary_audio,
    )


def _parse_all_media_sources(item: dict) -> list[MediaInfo]:
    """Extract all media sources from Emby item."""
    media_sources = item.get("MediaSources", [])
    return [_parse_single_media_source(source) for source in media_sources]


def _parse_media_info(item: dict) -> MediaInfo | None:
    """Extract primary media info from Emby item's MediaSources.

    Returns the highest resolution source as the primary.
    """
    all_sources = _parse_all_media_sources(item)
    if not all_sources:
        return None

    # Return the highest resolution source as primary
    def resolution_score(info: MediaInfo) -> int:
        if not info.video or not info.video.width:
            return 0
        return info.video.width

    return max(all_sources, key=resolution_score)


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

    async def get_movies_minimal(
        self,
        user_id: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> tuple[list[MovieSummary], int]:
        """Fetch movies with minimal fields for list views."""
        if user_id is None:
            user_id = await self.get_user_id()

        client = await self._get_client()
        params = {
            "IncludeItemTypes": "Movie",
            "Recursive": "true",
            "Fields": MINIMAL_FIELDS,
        }
        if offset is not None:
            params["StartIndex"] = offset
        if limit is not None:
            params["Limit"] = limit

        resp = await client.get(f"/Users/{user_id}/Items", params=params)
        resp.raise_for_status()
        data = resp.json()
        total_count = data.get("TotalRecordCount", 0)

        movies = []
        for item in data.get("Items", []):
            provider_ids = item.get("ProviderIds", {})
            movies.append(
                MovieSummary(
                    id=item["Id"],
                    name=item["Name"],
                    year=item.get("ProductionYear"),
                    genres=item.get("Genres", []),
                    tmdb_id=provider_ids.get("Tmdb"),
                    imdb_id=provider_ids.get("Imdb"),
                    community_rating=item.get("CommunityRating"),
                )
            )
        return movies, total_count

    async def get_movie_by_id(
        self,
        movie_id: str,
        user_id: str | None = None,
    ) -> Movie | None:
        """Fetch a single movie by ID with full metadata."""
        if user_id is None:
            user_id = await self.get_user_id()

        client = await self._get_client()
        resp = await client.get(
            f"/Users/{user_id}/Items/{movie_id}",
            params={"Fields": FULL_FIELDS},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        item = resp.json()

        if item.get("Type") != "Movie":
            return None

        provider_ids = item.get("ProviderIds", {})
        return Movie(
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
            media_info=_parse_media_info(item),
            all_media_sources=_parse_all_media_sources(item),
        )

    async def get_movies(
        self,
        user_id: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> tuple[list[Movie], int]:
        """Fetch movies from the library with optional pagination.

        Returns tuple of (movies, total_count).
        """
        if user_id is None:
            user_id = await self.get_user_id()

        client = await self._get_client()
        params = {
            "IncludeItemTypes": "Movie",
            "Recursive": "true",
            "Fields": FULL_FIELDS,
        }
        if offset is not None:
            params["StartIndex"] = offset
        if limit is not None:
            params["Limit"] = limit

        resp = await client.get(f"/Users/{user_id}/Items", params=params)
        resp.raise_for_status()
        data = resp.json()
        total_count = data.get("TotalRecordCount", 0)

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
                    media_info=_parse_media_info(item),
                    all_media_sources=_parse_all_media_sources(item),
                )
            )
        return movies, total_count

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

    async def get_collection(self, collection_id: str, user_id: str | None = None) -> dict:
        """Get full collection item data."""
        if user_id is None:
            user_id = await self.get_user_id()
        client = await self._get_client()
        resp = await client.get(
            f"/Users/{user_id}/Items/{collection_id}",
            params={"Fields": "Overview"},
        )
        resp.raise_for_status()
        return resp.json()

    async def update_collection_overview(
        self, collection_id: str, overview: str
    ) -> None:
        """Update the overview/description of a collection."""
        client = await self._get_client()
        item_data = await self.get_collection(collection_id)
        item_data["Overview"] = overview
        # Emby uses POST /Items/{id} for updating item metadata
        resp = await client.post(
            f"/Items/{collection_id}",
            json=item_data,
            params={"reqformat": "json"},
        )
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

    async def set_item_image(
        self,
        item_id: str,
        image_data: bytes,
        image_type: str = "Primary",
        content_type: str = "image/png",
    ) -> None:
        """Upload an image for an item (collection, movie, etc)."""
        client = await self._get_client()
        resp = await client.post(
            f"/Items/{item_id}/Images/{image_type}",
            content=image_data,
            headers={"Content-Type": content_type},
        )
        resp.raise_for_status()

    async def search_movies(
        self,
        user_id: str | None = None,
        genres: list[str] | None = None,
        years: tuple[int, int] | None = None,
        search_term: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
        minimal: bool = False,
    ) -> tuple[list[Movie] | list[MovieSummary], int]:
        """Search movies with filters. Returns (movies, total_count)."""
        if user_id is None:
            user_id = await self.get_user_id()

        client = await self._get_client()
        params = {
            "IncludeItemTypes": "Movie",
            "Recursive": "true",
            "Fields": MINIMAL_FIELDS if minimal else FULL_FIELDS,
        }

        if genres:
            params["Genres"] = "|".join(genres)
        if years:
            params["MinYear"] = years[0]
            params["MaxYear"] = years[1]
        if search_term:
            params["SearchTerm"] = search_term
        if offset is not None:
            params["StartIndex"] = offset
        if limit is not None:
            params["Limit"] = limit

        resp = await client.get(f"/Users/{user_id}/Items", params=params)
        resp.raise_for_status()
        data = resp.json()
        total_count = data.get("TotalRecordCount", 0)

        movies = []
        for item in data.get("Items", []):
            provider_ids = item.get("ProviderIds", {})
            if minimal:
                movies.append(
                    MovieSummary(
                        id=item["Id"],
                        name=item["Name"],
                        year=item.get("ProductionYear"),
                        genres=item.get("Genres", []),
                        tmdb_id=provider_ids.get("Tmdb"),
                        imdb_id=provider_ids.get("Imdb"),
                        community_rating=item.get("CommunityRating"),
                    )
                )
            else:
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
                        media_info=_parse_media_info(item),
                        all_media_sources=_parse_all_media_sources(item),
                    )
                )
        return movies, total_count

    async def get_movies_by_ids(
        self,
        movie_ids: list[str],
        user_id: str | None = None,
        minimal: bool = True,
    ) -> list[Movie] | list[MovieSummary]:
        """Fetch specific movies by their IDs."""
        if not movie_ids:
            return []
        if user_id is None:
            user_id = await self.get_user_id()

        client = await self._get_client()
        params = {
            "Ids": ",".join(movie_ids),
            "Fields": MINIMAL_FIELDS if minimal else FULL_FIELDS,
        }

        resp = await client.get(f"/Users/{user_id}/Items", params=params)
        resp.raise_for_status()
        data = resp.json()

        movies = []
        for item in data.get("Items", []):
            if item.get("Type") != "Movie":
                continue
            provider_ids = item.get("ProviderIds", {})
            if minimal:
                movies.append(
                    MovieSummary(
                        id=item["Id"],
                        name=item["Name"],
                        year=item.get("ProductionYear"),
                        genres=item.get("Genres", []),
                        tmdb_id=provider_ids.get("Tmdb"),
                        imdb_id=provider_ids.get("Imdb"),
                        community_rating=item.get("CommunityRating"),
                    )
                )
            else:
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
                        media_info=_parse_media_info(item),
                        all_media_sources=_parse_all_media_sources(item),
                    )
                )
        return movies

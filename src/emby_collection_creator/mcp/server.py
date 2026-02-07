"""MCP server implementation for Emby collection management."""

import asyncio
import json
import re
import shutil
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from ..config import get_settings
from ..services.comfyui import ComfyUIService
from ..services.emby import EmbyService
from ..services.tmdb import TMDbService
from ..services.tastedive import TasteDiveService
from ..services.trakt import TraktService


CRITERIA_MARKER = "<!-- SYNC_CRITERIA:"
CRITERIA_END = ":END_CRITERIA -->"


def encode_criteria(criteria: dict) -> str:
    """Encode criteria as a hidden comment in the overview."""
    return f"{CRITERIA_MARKER}{json.dumps(criteria)}{CRITERIA_END}"


def decode_criteria(overview: str | None) -> dict | None:
    """Extract criteria from overview if present."""
    if not overview:
        return None
    match = re.search(
        rf"{re.escape(CRITERIA_MARKER)}(.+?){re.escape(CRITERIA_END)}",
        overview,
        re.DOTALL,
    )
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    return None


def strip_criteria(overview: str | None) -> str:
    """Remove criteria marker from overview for display."""
    if not overview:
        return ""
    return re.sub(
        rf"{re.escape(CRITERIA_MARKER)}.*?{re.escape(CRITERIA_END)}",
        "",
        overview,
        flags=re.DOTALL,
    ).strip()


def _get_resolution_label(width: int | None) -> str:
    """Get human-readable resolution label."""
    if width is None:
        return "Unknown"
    if width >= 3840:
        return "4K"
    if width >= 1920:
        return "1080p"
    if width >= 1280:
        return "720p"
    if width >= 720:
        return "480p"
    return "SD"


def _get_audio_format_label(media_info) -> str | None:
    """Get primary audio format label."""
    if not media_info or not media_info.primary_audio:
        return None
    audio = media_info.primary_audio
    codec = (audio.codec or "").upper()

    if audio.is_atmos:
        if "TRUEHD" in codec:
            return "TrueHD Atmos"
        return "Atmos"
    if audio.is_dts_x:
        return "DTS:X"
    if audio.is_lossless:
        if "TRUEHD" in codec:
            return "TrueHD"
        if "DTS" in codec:
            return "DTS-HD MA"
        if "FLAC" in codec:
            return "FLAC"
    if "DTS" in codec:
        return "DTS"
    if "AC3" in codec or "EAC3" in codec:
        return "DD+" if "EAC3" in codec else "DD"
    if "AAC" in codec:
        return "AAC"
    return codec or None


def _serialize_media_info(media_info) -> dict | None:
    """Serialize MediaInfo to dict for JSON response."""
    if not media_info:
        return None

    video = None
    if media_info.video:
        v = media_info.video
        video = {
            "codec": v.codec,
            "width": v.width,
            "height": v.height,
            "resolution": _get_resolution_label(v.width),
            "bit_depth": v.bit_depth,
            "bitrate": v.bitrate,
            "hdr_type": v.hdr_type,
            "is_4k": v.is_4k,
            "is_hdr": v.is_hdr,
            "is_dolby_vision": v.is_dolby_vision,
            "is_hdr10_plus": v.is_hdr10_plus,
            "dv_profile": v.dv_profile,
            "dv_layer_type": v.dv_layer_type,
            "color_space": v.color_space,
            "color_transfer": v.color_transfer,
            "color_primaries": v.color_primaries,
        }

    audio_streams = []
    for a in media_info.audio_streams:
        audio_streams.append({
            "codec": a.codec,
            "channels": a.channels,
            "channel_layout": a.channel_layout,
            "language": a.language,
            "is_default": a.is_default,
            "is_atmos": a.is_atmos,
            "is_dts_x": a.is_dts_x,
            "is_lossless": a.is_lossless,
            "bitrate": a.bitrate,
        })

    return {
        "container": media_info.container,
        "file_size": media_info.file_size,
        "total_bitrate": media_info.total_bitrate,
        "video": video,
        "audio_streams": audio_streams,
        "audio_format": _get_audio_format_label(media_info),
    }


def _movie_matches_audio_criteria(media_info, audio_formats: list, require_lossless: bool) -> bool:
    """Check if movie's audio matches the criteria."""
    if not media_info:
        return False

    if require_lossless:
        if not any(a.is_lossless for a in media_info.audio_streams):
            return False

    if audio_formats:
        audio_match = False
        for audio in media_info.audio_streams:
            audio_label = _get_audio_format_label(media_info)
            if audio_label and any(fmt.lower() in audio_label.lower() for fmt in audio_formats):
                audio_match = True
                break
            if "lossless" in [f.lower() for f in audio_formats] and audio.is_lossless:
                audio_match = True
                break
            if "atmos" in [f.lower() for f in audio_formats] and audio.is_atmos:
                audio_match = True
                break
            if "dts:x" in [f.lower() for f in audio_formats] and audio.is_dts_x:
                audio_match = True
                break
        if not audio_match:
            return False

    return True


def _source_matches_video_criteria(
    media_info,
    resolution: str | None,
    hdr_types: list | None,
    dv_profiles: list | None,
    dv_layer: str | None,
) -> bool:
    """Check if a single media source matches video quality criteria."""
    if not media_info or not media_info.video:
        return False

    v = media_info.video

    if resolution:
        source_res = _get_resolution_label(v.width)
        if source_res != resolution:
            return False

    if hdr_types and v.hdr_type not in hdr_types:
        return False

    if dv_profiles and v.dv_profile not in dv_profiles:
        return False

    if dv_layer and v.dv_layer_type != dv_layer:
        return False

    return True


def _movie_matches_quality_criteria(
    movie,
    resolution: str | None,
    hdr_types: list | None,
    dv_profiles: list | None,
    dv_layer: str | None,
    audio_formats: list | None,
    require_lossless: bool,
) -> bool:
    """Check if ANY media source of a movie matches the quality criteria."""
    sources = movie.all_media_sources if movie.all_media_sources else []
    if movie.media_info and movie.media_info not in sources:
        sources = [movie.media_info] + list(sources)

    if not sources:
        return False

    # Check if ANY source matches video criteria
    video_match = False
    matching_source = None
    for source in sources:
        if _source_matches_video_criteria(source, resolution, hdr_types, dv_profiles, dv_layer):
            video_match = True
            matching_source = source
            break

    if not video_match:
        return False

    # For audio, check the matching source (or any source if no video criteria)
    if audio_formats or require_lossless:
        if matching_source:
            return _movie_matches_audio_criteria(matching_source, audio_formats or [], require_lossless)
        return any(
            _movie_matches_audio_criteria(s, audio_formats or [], require_lossless)
            for s in sources
        )

    return True


async def sync_collection_by_criteria(
    emby: "EmbyService",
    tmdb: "TMDbService",
    collection_id: str,
    collection_name: str,
    criteria: dict,
    trakt: "TraktService | None" = None,
) -> str:
    """Sync a collection based on criteria. Returns a summary string."""
    current_ids = set(await emby.get_collection_items(collection_id))
    matching_ids = set()

    # Handle Trakt list-based sync
    trakt_username = criteria.get("trakt_username")
    trakt_list_slug = criteria.get("trakt_list_slug")
    if trakt_username and trakt_list_slug and trakt:
        # Fetch all Trakt list items (may need pagination for large lists)
        all_trakt_items = []
        trakt_offset = 0
        while True:
            trakt_items, trakt_total = await trakt.get_list_items(
                trakt_username, trakt_list_slug, limit=100, offset=trakt_offset
            )
            all_trakt_items.extend(trakt_items)
            trakt_offset += 100
            if trakt_offset >= trakt_total:
                break

        # Build a lookup of TMDb IDs from the Trakt list
        trakt_tmdb_ids = {str(item.movie.tmdb_id) for item in all_trakt_items if item.movie.tmdb_id}

        # Get all movies from Emby and match by TMDb ID
        batch_size = 200
        offset = 0
        while True:
            movies, total_count = await emby.get_movies(offset=offset, limit=batch_size)
            if not movies:
                break

            for movie in movies:
                if movie.tmdb_id and movie.tmdb_id in trakt_tmdb_ids:
                    matching_ids.add(movie.id)

            offset += batch_size
            if offset >= total_count:
                break

        # Calculate and apply changes (add only, never remove)
        to_add = matching_ids - current_ids

        if to_add:
            await emby.add_to_collection(collection_id, list(to_add))

        return (
            f"Synced '{collection_name}' from Trakt list: "
            f"{len(matching_ids)} movies match, "
            f"+{len(to_add)} added"
        )

    genres = criteria.get("genres", [])
    min_year = criteria.get("min_year")
    max_year = criteria.get("max_year")
    min_rating = criteria.get("min_rating")
    max_rating = criteria.get("max_rating")
    min_b_movie_score = criteria.get("min_b_movie_score")
    required_tags = set(t.lower() for t in criteria.get("tags", []))
    required_keywords = set(k.lower() for k in criteria.get("keywords", []))

    # Quality filters
    resolution = criteria.get("resolution")
    hdr_types = criteria.get("hdr_types", [])
    dv_profiles = criteria.get("dv_profiles", [])
    dv_layer = criteria.get("dv_layer")
    audio_formats = criteria.get("audio_formats", [])
    require_lossless = criteria.get("require_lossless_audio", False)

    # Check if quality filtering is needed - requires individual fetch for merged versions
    # Batch fetches only return 1 MediaSource per item, missing merged versions
    has_quality_filters = bool(
        resolution or hdr_types or dv_profiles or dv_layer or audio_formats or require_lossless
    )

    # Concurrency limit for individual fetches
    semaphore = asyncio.Semaphore(20)

    async def fetch_and_check_quality(movie_id: str) -> str | None:
        """Fetch full movie and check quality criteria. Returns ID if matches."""
        async with semaphore:
            full_movie = await emby.get_movie_by_id(movie_id)
            if not full_movie:
                return None
            if _movie_matches_quality_criteria(
                full_movie, resolution, hdr_types, dv_profiles, dv_layer, audio_formats, require_lossless
            ):
                return movie_id
            return None

    # Process movies in batches
    batch_size = 200
    offset = 0

    while True:
        movies, total_count = await emby.get_movies(offset=offset, limit=batch_size)
        if not movies:
            break

        # First pass: apply non-quality filters
        candidates = []
        for movie in movies:
            # Genre filter
            if genres:
                if not any(g in movie.genres for g in genres):
                    continue

            # Year filter
            if min_year and (not movie.year or movie.year < min_year):
                continue
            if max_year and (not movie.year or movie.year > max_year):
                continue

            # Rating filter
            if min_rating and (not movie.community_rating or movie.community_rating < min_rating):
                continue
            if max_rating and (not movie.community_rating or movie.community_rating > max_rating):
                continue

            # Tag filter
            if required_tags:
                movie_tags = set(t.lower() for t in movie.tags)
                if not required_tags.issubset(movie_tags):
                    continue

            candidates.append(movie)

        # Second pass: quality filters with concurrent fetching
        if has_quality_filters and candidates:
            tasks = [fetch_and_check_quality(m.id) for m in candidates]
            results = await asyncio.gather(*tasks)
            quality_matched_ids = {r for r in results if r is not None}

            # Filter candidates to only those that matched quality
            candidates = [m for m in candidates if m.id in quality_matched_ids]

        # Third pass: TMDb-based filters
        for movie in candidates:
            if min_b_movie_score is not None or required_keywords:
                if not movie.tmdb_id:
                    continue
                tmdb_data = await tmdb.get_movie(movie.tmdb_id)
                if not tmdb_data:
                    continue

                if min_b_movie_score is not None:
                    score = tmdb.calculate_b_movie_score(tmdb_data)
                    if score < min_b_movie_score:
                        continue

                if required_keywords:
                    movie_keywords = set(k.name.lower() for k in tmdb_data.keywords)
                    if not required_keywords.intersection(movie_keywords):
                        continue

            matching_ids.add(movie.id)

        offset += batch_size
        if offset >= total_count:
            break

    # Calculate changes (add only, never remove)
    to_add = matching_ids - current_ids

    # Apply changes
    if to_add:
        await emby.add_to_collection(collection_id, list(to_add))

    return (
        f"Synced '{collection_name}': "
        f"{len(matching_ids)} movies match, "
        f"+{len(to_add)} added"
    )


def create_mcp_server() -> Server:
    """Create and configure the MCP server."""
    server = Server("emby-collection-creator")
    settings = get_settings()

    # Setup artwork directories
    artwork_generated = Path(settings.artwork_generated_dir)
    artwork_chosen = Path(settings.artwork_chosen_dir)
    artwork_generated.mkdir(parents=True, exist_ok=True)
    artwork_chosen.mkdir(parents=True, exist_ok=True)

    emby = EmbyService(
        base_url=settings.emby_server_url,
        api_key=settings.emby_api_key,
    )
    tmdb = TMDbService(
        api_key=settings.tmdb_api_key,
        read_access_token=settings.tmdb_read_access_token,
    )
    tastedive = TasteDiveService(
        api_key=settings.tastedive_api_key,
    )
    trakt = TraktService(
        client_id=settings.trakt_client_id,
        client_secret=settings.trakt_client_secret,
    )
    comfyui = ComfyUIService(
        base_url=settings.comfyui_url,
        output_dir=artwork_generated,
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="get_library_movies",
                description="Get movies from the Emby library with metadata. Supports pagination to avoid truncation with large libraries.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "offset": {
                            "type": "integer",
                            "description": "Number of items to skip (default 0)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of items to return (default 100, use smaller values for large libraries)",
                        },
                    },
                },
            ),
            Tool(
                name="search_movies",
                description="Search movies by genre, year range, or search term. Returns compact results with pagination.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "genres": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by genres (e.g., ['Horror', 'Comedy'])",
                        },
                        "min_year": {
                            "type": "integer",
                            "description": "Minimum production year",
                        },
                        "max_year": {
                            "type": "integer",
                            "description": "Maximum production year",
                        },
                        "search_term": {
                            "type": "string",
                            "description": "Search term for movie title",
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Number of items to skip (default 0)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of items to return (default 100)",
                        },
                    },
                },
            ),
            Tool(
                name="search_movies_by_quality",
                description="Search movies by video/audio quality criteria (resolution, HDR type, Dolby Vision, audio format). Supports pagination.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "resolution": {
                            "type": "string",
                            "enum": ["4K", "1080p", "720p", "480p", "SD"],
                            "description": "Filter by resolution",
                        },
                        "hdr_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by HDR type(s): 'Dolby Vision', 'HDR10+', 'HDR10', 'HLG', 'SDR'",
                        },
                        "dv_profile": {
                            "type": "integer",
                            "description": "Filter by Dolby Vision profile (5, 7, 8, etc.)",
                        },
                        "dv_layer": {
                            "type": "string",
                            "enum": ["FEL", "MEL"],
                            "description": "Filter by DV layer type: FEL (Full Enhancement Layer) or MEL (Minimum Enhancement Layer)",
                        },
                        "audio_formats": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by audio format(s): 'Atmos', 'DTS:X', 'TrueHD', 'DTS-HD MA', 'lossless'",
                        },
                        "require_lossless_audio": {
                            "type": "boolean",
                            "description": "Only return movies with lossless audio (TrueHD, DTS-HD MA, FLAC)",
                        },
                        "min_bitrate": {
                            "type": "integer",
                            "description": "Minimum video bitrate in Mbps",
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Number of items to skip (default 0)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of items to return (default 100)",
                        },
                    },
                },
            ),
            Tool(
                name="get_movie_details",
                description="Get detailed metadata for a movie, including TMDb enrichment",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "movie_id": {
                            "type": "string",
                            "description": "Emby movie ID",
                        },
                    },
                    "required": ["movie_id"],
                },
            ),
            Tool(
                name="list_collections",
                description="List all collections in Emby",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="get_collection_items",
                description="Get movies in a specific collection",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "collection_id": {
                            "type": "string",
                            "description": "Collection ID",
                        },
                    },
                    "required": ["collection_id"],
                },
            ),
            Tool(
                name="create_collection",
                description="Create a new collection with optional initial movies",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Collection name",
                        },
                        "movie_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Initial movie IDs to add",
                        },
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="add_to_collection",
                description="Add movies to an existing collection",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "collection_id": {
                            "type": "string",
                            "description": "Collection ID",
                        },
                        "movie_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Movie IDs to add",
                        },
                    },
                    "required": ["collection_id", "movie_ids"],
                },
            ),
            Tool(
                name="remove_from_collection",
                description="Remove movies from a collection",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "collection_id": {
                            "type": "string",
                            "description": "Collection ID",
                        },
                        "movie_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Movie IDs to remove",
                        },
                    },
                    "required": ["collection_id", "movie_ids"],
                },
            ),
            Tool(
                name="delete_collection",
                description="Delete a collection (does not delete the movies)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "collection_id": {
                            "type": "string",
                            "description": "Collection ID to delete",
                        },
                    },
                    "required": ["collection_id"],
                },
            ),
            Tool(
                name="enrich_movie_metadata",
                description="Fetch TMDb metadata for a movie and calculate b-movie score",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tmdb_id": {
                            "type": "string",
                            "description": "TMDb ID of the movie",
                        },
                    },
                    "required": ["tmdb_id"],
                },
            ),
            Tool(
                name="set_collection_criteria",
                description="Set sync criteria for a collection. Criteria are stored in the collection's metadata and used by sync_collection to automatically update membership.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "collection_id": {
                            "type": "string",
                            "description": "Collection ID",
                        },
                        "genres": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Required genres (e.g., ['Horror'])",
                        },
                        "min_year": {
                            "type": "integer",
                            "description": "Minimum production year",
                        },
                        "max_year": {
                            "type": "integer",
                            "description": "Maximum production year",
                        },
                        "min_rating": {
                            "type": "number",
                            "description": "Minimum community rating (0-10)",
                        },
                        "max_rating": {
                            "type": "number",
                            "description": "Maximum community rating (0-10)",
                        },
                        "min_b_movie_score": {
                            "type": "number",
                            "description": "Minimum b-movie score (0-1, requires TMDb lookup)",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Required tags in Emby",
                        },
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Required TMDb keywords",
                        },
                        "resolution": {
                            "type": "string",
                            "enum": ["4K", "1080p", "720p", "480p", "SD"],
                            "description": "Required resolution",
                        },
                        "hdr_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Required HDR type(s): 'Dolby Vision', 'HDR10+', 'HDR10', 'HLG', 'SDR'",
                        },
                        "dv_profiles": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Required Dolby Vision profile(s) (5, 7, 8, etc.)",
                        },
                        "dv_layer": {
                            "type": "string",
                            "enum": ["FEL", "MEL"],
                            "description": "Required DV layer type: FEL or MEL",
                        },
                        "audio_formats": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Required audio format(s): 'Atmos', 'DTS:X', 'TrueHD', 'DTS-HD MA', 'lossless'",
                        },
                        "require_lossless_audio": {
                            "type": "boolean",
                            "description": "Require lossless audio (TrueHD, DTS-HD MA, FLAC)",
                        },
                        "trakt_username": {
                            "type": "string",
                            "description": "Trakt username for list-based sync",
                        },
                        "trakt_list_slug": {
                            "type": "string",
                            "description": "Trakt list slug for list-based sync",
                        },
                        "description": {
                            "type": "string",
                            "description": "Human-readable description of the collection criteria",
                        },
                    },
                    "required": ["collection_id"],
                },
            ),
            Tool(
                name="get_collection_criteria",
                description="Get the sync criteria for a collection",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "collection_id": {
                            "type": "string",
                            "description": "Collection ID",
                        },
                    },
                    "required": ["collection_id"],
                },
            ),
            Tool(
                name="sync_collection",
                description="Sync a collection based on its stored criteria. Adds matching movies and removes non-matching ones.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "collection_id": {
                            "type": "string",
                            "description": "Collection ID to sync",
                        },
                    },
                    "required": ["collection_id"],
                },
            ),
            Tool(
                name="sync_all_collections",
                description="Sync all collections that have stored criteria",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            # TasteDive tools
            Tool(
                name="get_similar_movies",
                description="Get movie recommendations similar to given titles using TasteDive",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "titles": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Movie titles to find similar movies for (e.g., ['The Matrix', 'Blade Runner'])",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of recommendations (default 20)",
                        },
                    },
                    "required": ["titles"],
                },
            ),
            # Trakt tools
            Tool(
                name="get_trending_movies",
                description="Get currently trending movies from Trakt",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results (default 20)",
                        },
                    },
                },
            ),
            Tool(
                name="get_popular_movies_trakt",
                description="Get popular movies from Trakt",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results (default 20)",
                        },
                    },
                },
            ),
            Tool(
                name="get_most_watched_movies",
                description="Get most watched movies from Trakt for a time period",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "period": {
                            "type": "string",
                            "enum": ["weekly", "monthly", "yearly", "all"],
                            "description": "Time period (default: weekly)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results (default 20)",
                        },
                    },
                },
            ),
            Tool(
                name="get_anticipated_movies",
                description="Get most anticipated upcoming movies from Trakt",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results (default 20)",
                        },
                    },
                },
            ),
            Tool(
                name="get_box_office",
                description="Get current box office movies from Trakt",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="search_trakt_lists",
                description="Search for public Trakt lists by name",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search term for list names (e.g., 'best horror', 'oscar winners')",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of lists to return (default 10)",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="get_trakt_list_items",
                description="Get movies from a specific Trakt list. Supports pagination to avoid truncation with large lists.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "username": {
                            "type": "string",
                            "description": "Trakt username who owns the list",
                        },
                        "list_slug": {
                            "type": "string",
                            "description": "List slug/ID",
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Number of items to skip (default 0)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of items to return (default 100)",
                        },
                    },
                    "required": ["username", "list_slug"],
                },
            ),
            Tool(
                name="get_related_movies_trakt",
                description="Get movies related to a specific movie from Trakt",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "movie_title": {
                            "type": "string",
                            "description": "Movie title to find related movies for",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results (default 20)",
                        },
                    },
                    "required": ["movie_title"],
                },
            ),
            # Artwork generation tools
            Tool(
                name="generate_collection_poster",
                description="Generate AI artwork for a collection poster using Flux Dev. Include any desired title text in the prompt for the AI to generate.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "collection_id": {
                            "type": "string",
                            "description": "Emby collection ID to generate poster for",
                        },
                        "prompt": {
                            "type": "string",
                            "description": "Detailed prompt describing the desired poster artwork. Include title text in the prompt if desired.",
                        },
                        "width": {
                            "type": "integer",
                            "description": "Image width in pixels (default 1024)",
                        },
                        "height": {
                            "type": "integer",
                            "description": "Image height in pixels (default 1024)",
                        },
                        "steps": {
                            "type": "integer",
                            "description": "Number of diffusion steps (default 20)",
                        },
                        "guidance": {
                            "type": "number",
                            "description": "Guidance scale (default 3.5)",
                        },
                    },
                    "required": ["collection_id", "prompt"],
                },
            ),
            Tool(
                name="list_generated_artwork",
                description="List all generated artwork images in the generated folder",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "collection_filter": {
                            "type": "string",
                            "description": "Optional filter to show only images for a specific collection",
                        },
                    },
                },
            ),
            Tool(
                name="list_chosen_artwork",
                description="List all selected artwork images in the chosen folder",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="select_artwork",
                description="Move a generated image to the chosen folder for use as collection art",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Filename of the generated image to select",
                        },
                        "new_name": {
                            "type": "string",
                            "description": "Optional new filename for the chosen image",
                        },
                    },
                    "required": ["filename"],
                },
            ),
            Tool(
                name="apply_collection_poster",
                description="Upload a chosen artwork image as the poster for an Emby collection",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "collection_id": {
                            "type": "string",
                            "description": "Emby collection ID",
                        },
                        "filename": {
                            "type": "string",
                            "description": "Filename of the image in the chosen folder",
                        },
                    },
                    "required": ["collection_id", "filename"],
                },
            ),
            Tool(
                name="check_comfyui_status",
                description="Check if ComfyUI is running and available for image generation",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            if name == "get_library_movies":
                offset = arguments.get("offset", 0)
                limit = arguments.get("limit", 100)
                movies, total_count = await emby.get_movies_minimal(offset=offset, limit=limit)

                movie_list = [
                    {
                        "id": m.id,
                        "name": m.name,
                        "year": m.year,
                        "genres": m.genres,
                        "rating": m.community_rating,
                        "tmdb_id": m.tmdb_id,
                    }
                    for m in movies
                ]

                result = {
                    "total_count": total_count,
                    "offset": offset,
                    "limit": limit,
                    "returned": len(movies),
                    "movies": movie_list,
                }
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "search_movies":
                years = None
                if arguments.get("min_year") or arguments.get("max_year"):
                    years = (
                        arguments.get("min_year", 1900),
                        arguments.get("max_year", 2100),
                    )
                offset = arguments.get("offset", 0)
                limit = arguments.get("limit", 100)
                movies, total_count = await emby.search_movies(
                    genres=arguments.get("genres"),
                    years=years,
                    search_term=arguments.get("search_term"),
                    offset=offset,
                    limit=limit,
                    minimal=True,
                )
                movie_list = [
                    {
                        "id": m.id,
                        "name": m.name,
                        "year": m.year,
                        "genres": m.genres,
                        "rating": m.community_rating,
                        "tmdb_id": m.tmdb_id,
                    }
                    for m in movies
                ]
                result = {
                    "total_count": total_count,
                    "offset": offset,
                    "limit": limit,
                    "returned": len(movies),
                    "movies": movie_list,
                }
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "search_movies_by_quality":
                offset = arguments.get("offset", 0)
                limit = arguments.get("limit", 100)

                resolution = arguments.get("resolution")
                hdr_types = arguments.get("hdr_types")
                dv_profile = arguments.get("dv_profile")
                dv_layer = arguments.get("dv_layer")
                audio_formats = arguments.get("audio_formats")
                require_lossless = arguments.get("require_lossless_audio", False)
                min_bitrate = arguments.get("min_bitrate")

                # Concurrency limit for individual fetches
                semaphore = asyncio.Semaphore(20)
                dv_profiles_list = [dv_profile] if dv_profile is not None else None

                async def fetch_and_check(movie_id: str):
                    """Fetch full movie and check quality. Returns movie if matches."""
                    async with semaphore:
                        full_movie = await emby.get_movie_by_id(movie_id)
                        if not full_movie:
                            return None

                        if not _movie_matches_quality_criteria(
                            full_movie, resolution, hdr_types, dv_profiles_list, dv_layer, audio_formats, require_lossless
                        ):
                            return None

                        if min_bitrate and full_movie.media_info and full_movie.media_info.video and full_movie.media_info.video.bitrate:
                            if full_movie.media_info.video.bitrate < min_bitrate * 1_000_000:
                                return None

                        return full_movie

                # Fetch in batches to avoid loading entire library at once
                batch_size = 200
                filtered = []
                current_offset = 0

                while True:
                    movies, total_count = await emby.get_movies(
                        offset=current_offset, limit=batch_size
                    )
                    if not movies:
                        break

                    # Fetch all movies in this batch concurrently
                    tasks = [fetch_and_check(m.id) for m in movies]
                    results = await asyncio.gather(*tasks)
                    filtered.extend([m for m in results if m is not None])

                    current_offset += batch_size

                    # Stop if we have enough results after applying offset
                    if len(filtered) >= offset + limit:
                        break
                    if current_offset >= total_count:
                        break

                # Apply pagination to filtered results
                paginated = filtered[offset:offset + limit]

                result = []
                for m in paginated:
                    v = m.media_info.video
                    result.append({
                        "id": m.id,
                        "name": m.name,
                        "year": m.year,
                        "resolution": _get_resolution_label(v.width),
                        "hdr_type": v.hdr_type,
                        "dv_profile": v.dv_profile,
                        "dv_layer": v.dv_layer_type,
                        "audio_format": _get_audio_format_label(m.media_info),
                    })

                return [TextContent(type="text", text=json.dumps({
                    "total_matching": len(filtered),
                    "offset": offset,
                    "limit": limit,
                    "returned": len(result),
                    "movies": result,
                }, indent=2))]

            elif name == "get_movie_details":
                movie = await emby.get_movie_by_id(arguments["movie_id"])
                if not movie:
                    return [TextContent(type="text", text="Movie not found")]

                result = {
                    "id": movie.id,
                    "name": movie.name,
                    "year": movie.year,
                    "genres": movie.genres,
                    "tags": movie.tags,
                    "overview": movie.overview,
                    "community_rating": movie.community_rating,
                    "tmdb_id": movie.tmdb_id,
                    "imdb_id": movie.imdb_id,
                    "studios": movie.studios,
                    "media_info": _serialize_media_info(movie.media_info),
                    "all_media_sources": [
                        _serialize_media_info(src) for src in movie.all_media_sources
                    ],
                }

                if movie.tmdb_id:
                    tmdb_data = await tmdb.get_movie(movie.tmdb_id)
                    if tmdb_data:
                        result["tmdb"] = {
                            "budget": tmdb_data.budget,
                            "revenue": tmdb_data.revenue,
                            "keywords": [k.name for k in tmdb_data.keywords],
                            "vote_average": tmdb_data.vote_average,
                            "production_companies": tmdb_data.production_companies,
                            "b_movie_score": tmdb.calculate_b_movie_score(tmdb_data),
                        }

                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "list_collections":
                collections = await emby.get_collections()
                result = [{"id": c.id, "name": c.name} for c in collections]
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "get_collection_items":
                item_ids = await emby.get_collection_items(arguments["collection_id"])
                if not item_ids:
                    return [TextContent(type="text", text=json.dumps([], indent=2))]
                movies = await emby.get_movies_by_ids(item_ids, minimal=True)
                result = [
                    {"id": m.id, "name": m.name, "year": m.year} for m in movies
                ]
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "create_collection":
                collection = await emby.create_collection(
                    name=arguments["name"],
                    item_ids=arguments.get("movie_ids"),
                )
                return [
                    TextContent(
                        type="text",
                        text=f"Created collection '{collection.name}' with ID: {collection.id}",
                    )
                ]

            elif name == "add_to_collection":
                await emby.add_to_collection(
                    collection_id=arguments["collection_id"],
                    item_ids=arguments["movie_ids"],
                )
                return [
                    TextContent(
                        type="text",
                        text=f"Added {len(arguments['movie_ids'])} movies to collection",
                    )
                ]

            elif name == "remove_from_collection":
                await emby.remove_from_collection(
                    collection_id=arguments["collection_id"],
                    item_ids=arguments["movie_ids"],
                )
                return [
                    TextContent(
                        type="text",
                        text=f"Removed {len(arguments['movie_ids'])} movies from collection",
                    )
                ]

            elif name == "delete_collection":
                await emby.delete_collection(arguments["collection_id"])
                return [TextContent(type="text", text="Collection deleted")]

            elif name == "enrich_movie_metadata":
                tmdb_data = await tmdb.get_movie(arguments["tmdb_id"])
                if not tmdb_data:
                    return [TextContent(type="text", text="Movie not found on TMDb")]

                result = {
                    "id": tmdb_data.id,
                    "title": tmdb_data.title,
                    "budget": tmdb_data.budget,
                    "revenue": tmdb_data.revenue,
                    "keywords": [k.name for k in tmdb_data.keywords],
                    "vote_average": tmdb_data.vote_average,
                    "vote_count": tmdb_data.vote_count,
                    "production_companies": tmdb_data.production_companies,
                    "b_movie_score": tmdb.calculate_b_movie_score(tmdb_data),
                    "is_b_movie_studio": tmdb.is_b_movie_studio(
                        tmdb_data.production_companies
                    ),
                    "has_campy_keywords": tmdb.has_campy_keywords(tmdb_data.keywords),
                }
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "set_collection_criteria":
                collection_id = arguments["collection_id"]
                criteria = {
                    k: v
                    for k, v in arguments.items()
                    if k != "collection_id" and v is not None
                }

                collections = await emby.get_collections()
                collection = next(
                    (c for c in collections if c.id == collection_id), None
                )
                if not collection:
                    return [TextContent(type="text", text="Collection not found")]

                description = criteria.pop("description", "")
                overview = description + "\n\n" + encode_criteria(criteria) if description else encode_criteria(criteria)
                await emby.update_collection_overview(collection_id, overview)

                return [
                    TextContent(
                        type="text",
                        text=f"Set criteria for '{collection.name}': {json.dumps(criteria, indent=2)}",
                    )
                ]

            elif name == "get_collection_criteria":
                collection_id = arguments["collection_id"]
                collections = await emby.get_collections()
                collection = next(
                    (c for c in collections if c.id == collection_id), None
                )
                if not collection:
                    return [TextContent(type="text", text="Collection not found")]

                criteria = decode_criteria(collection.overview)
                if not criteria:
                    return [
                        TextContent(
                            type="text",
                            text=f"No sync criteria set for '{collection.name}'",
                        )
                    ]

                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {"name": collection.name, "criteria": criteria}, indent=2
                        ),
                    )
                ]

            elif name == "sync_collection":
                collection_id = arguments["collection_id"]
                collections = await emby.get_collections()
                collection = next(
                    (c for c in collections if c.id == collection_id), None
                )
                if not collection:
                    return [TextContent(type="text", text="Collection not found")]

                criteria = decode_criteria(collection.overview)
                if not criteria:
                    return [
                        TextContent(
                            type="text",
                            text=f"No sync criteria set for '{collection.name}'",
                        )
                    ]

                result = await sync_collection_by_criteria(
                    emby, tmdb, collection_id, collection.name, criteria, trakt
                )
                return [TextContent(type="text", text=result)]

            elif name == "sync_all_collections":
                collections = await emby.get_collections()
                results = []

                for collection in collections:
                    criteria = decode_criteria(collection.overview)
                    if criteria:
                        result = await sync_collection_by_criteria(
                            emby, tmdb, collection.id, collection.name, criteria, trakt
                        )
                        results.append(result)

                if not results:
                    return [
                        TextContent(
                            type="text",
                            text="No collections have sync criteria set",
                        )
                    ]

                return [TextContent(type="text", text="\n\n".join(results))]

            # TasteDive tools
            elif name == "get_similar_movies":
                titles = arguments["titles"]
                limit = arguments.get("limit", 20)
                response = await tastedive.get_similar(
                    titles=titles,
                    media_type="movie",
                    limit=limit,
                )
                result = {
                    "query": [
                        {"name": item.name, "type": item.type}
                        for item in response.query_items
                    ],
                    "recommendations": [
                        {
                            "name": item.name,
                            "type": item.type,
                            "description": item.description,
                            "wikipedia_url": item.wikipedia_url,
                        }
                        for item in response.recommendations
                    ],
                }
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            # Trakt tools
            elif name == "get_trending_movies":
                limit = arguments.get("limit", 20)
                movies = await trakt.get_trending_movies(limit=limit)
                result = [
                    {
                        "title": m.movie.title,
                        "year": m.movie.year,
                        "watchers": m.watchers,
                        "trakt_id": m.movie.trakt_id,
                        "imdb_id": m.movie.imdb_id,
                        "tmdb_id": m.movie.tmdb_id,
                    }
                    for m in movies
                ]
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "get_popular_movies_trakt":
                limit = arguments.get("limit", 20)
                movies = await trakt.get_popular_movies(limit=limit)
                result = [
                    {
                        "title": m.title,
                        "year": m.year,
                        "trakt_id": m.trakt_id,
                        "imdb_id": m.imdb_id,
                        "tmdb_id": m.tmdb_id,
                    }
                    for m in movies
                ]
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "get_most_watched_movies":
                period = arguments.get("period", "weekly")
                limit = arguments.get("limit", 20)
                movies = await trakt.get_most_watched_movies(period=period, limit=limit)
                result = [
                    {
                        "title": m.title,
                        "year": m.year,
                        "trakt_id": m.trakt_id,
                        "imdb_id": m.imdb_id,
                        "tmdb_id": m.tmdb_id,
                    }
                    for m in movies
                ]
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "get_anticipated_movies":
                limit = arguments.get("limit", 20)
                movies = await trakt.get_anticipated_movies(limit=limit)
                result = [
                    {
                        "title": m.title,
                        "year": m.year,
                        "trakt_id": m.trakt_id,
                        "imdb_id": m.imdb_id,
                        "tmdb_id": m.tmdb_id,
                    }
                    for m in movies
                ]
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "get_box_office":
                movies = await trakt.get_box_office_movies()
                result = [
                    {
                        "title": m.title,
                        "year": m.year,
                        "trakt_id": m.trakt_id,
                        "imdb_id": m.imdb_id,
                        "tmdb_id": m.tmdb_id,
                    }
                    for m in movies
                ]
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "search_trakt_lists":
                query = arguments["query"]
                limit = arguments.get("limit", 10)
                lists = await trakt.search_lists(query=query, limit=limit)
                result = [
                    {
                        "name": lst.name,
                        "description": lst.description,
                        "item_count": lst.item_count,
                        "likes": lst.likes,
                        "user": lst.user,
                        "slug": lst.slug,
                    }
                    for lst in lists
                ]
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "get_trakt_list_items":
                username = arguments["username"]
                list_slug = arguments["list_slug"]
                offset = arguments.get("offset", 0)
                limit = arguments.get("limit", 100)
                items, total_count = await trakt.get_list_items(
                    username=username, list_slug=list_slug, limit=limit, offset=offset
                )
                result = {
                    "total_count": total_count,
                    "offset": offset,
                    "limit": limit,
                    "returned": len(items),
                    "items": [
                        {
                            "rank": item.rank,
                            "title": item.movie.title,
                            "year": item.movie.year,
                            "trakt_id": item.movie.trakt_id,
                            "imdb_id": item.movie.imdb_id,
                            "tmdb_id": item.movie.tmdb_id,
                        }
                        for item in items
                    ],
                }
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "get_related_movies_trakt":
                movie_title = arguments["movie_title"]
                limit = arguments.get("limit", 20)
                # First search for the movie to get its Trakt ID
                movie = await trakt.search_movie(movie_title)
                if not movie:
                    return [
                        TextContent(
                            type="text",
                            text=f"Movie '{movie_title}' not found on Trakt",
                        )
                    ]
                related = await trakt.get_related_movies(
                    trakt_id=movie.trakt_id, limit=limit
                )
                result = [
                    {
                        "title": m.title,
                        "year": m.year,
                        "trakt_id": m.trakt_id,
                        "imdb_id": m.imdb_id,
                        "tmdb_id": m.tmdb_id,
                    }
                    for m in related
                ]
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            # Artwork generation tools
            elif name == "check_comfyui_status":
                available = await comfyui.is_available()
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({
                            "available": available,
                            "url": settings.comfyui_url,
                            "generated_dir": str(artwork_generated.absolute()),
                            "chosen_dir": str(artwork_chosen.absolute()),
                        }, indent=2),
                    )
                ]

            elif name == "generate_collection_poster":
                if not await comfyui.is_available():
                    return [
                        TextContent(
                            type="text",
                            text="ComfyUI is not running. Please start ComfyUI first.",
                        )
                    ]

                collection_id = arguments["collection_id"]
                prompt = arguments["prompt"]
                width = arguments.get("width", 1024)
                height = arguments.get("height", 1024)
                steps = arguments.get("steps", 20)
                guidance = arguments.get("guidance", 3.5)

                # Look up collection to get name
                collections = await emby.get_collections()
                collection = next(
                    (c for c in collections if c.id == collection_id), None
                )
                if not collection:
                    return [TextContent(type="text", text="Collection not found")]

                collection_name = collection.name

                # Generate poster
                path = await comfyui.generate_poster(
                    prompt=prompt,
                    collection_name=collection_name,
                    width=width,
                    height=height,
                    steps=steps,
                    guidance=guidance,
                )

                # Copy to chosen folder and apply to collection
                dest_name = f"{collection_name}.png"
                dest = artwork_chosen / dest_name
                shutil.copy2(path, dest)

                # Read PNG and apply to collection
                png_data = dest.read_bytes()
                await emby.set_item_image(collection_id, png_data, content_type="image/png")

                return [
                    TextContent(
                        type="text",
                        text=json.dumps({
                            "success": True,
                            "collection_id": collection_id,
                            "collection_name": collection_name,
                            "image": str(path.absolute()),
                            "message": f"Generated and applied poster for '{collection_name}'",
                        }, indent=2),
                    )
                ]

            elif name == "list_generated_artwork":
                collection_filter = arguments.get("collection_filter")
                images = []
                for img in artwork_generated.glob("*.png"):
                    if collection_filter:
                        if collection_filter.lower() not in img.name.lower():
                            continue
                    stat = img.stat()
                    images.append({
                        "filename": img.name,
                        "path": str(img.absolute()),
                        "size_kb": round(stat.st_size / 1024, 1),
                        "modified": stat.st_mtime,
                    })
                images.sort(key=lambda x: x["modified"], reverse=True)
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({
                            "count": len(images),
                            "directory": str(artwork_generated.absolute()),
                            "images": images,
                        }, indent=2),
                    )
                ]

            elif name == "list_chosen_artwork":
                images = []
                for img in artwork_chosen.glob("*.png"):
                    stat = img.stat()
                    images.append({
                        "filename": img.name,
                        "path": str(img.absolute()),
                        "size_kb": round(stat.st_size / 1024, 1),
                        "modified": stat.st_mtime,
                    })
                images.sort(key=lambda x: x["modified"], reverse=True)
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({
                            "count": len(images),
                            "directory": str(artwork_chosen.absolute()),
                            "images": images,
                        }, indent=2),
                    )
                ]

            elif name == "select_artwork":
                filename = arguments["filename"]
                new_name = arguments.get("new_name")

                source = artwork_generated / filename
                if not source.exists():
                    return [
                        TextContent(
                            type="text",
                            text=f"File not found: {filename}",
                        )
                    ]

                dest_name = new_name if new_name else filename
                if not dest_name.endswith(".png"):
                    dest_name += ".png"
                dest = artwork_chosen / dest_name

                shutil.copy2(source, dest)
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({
                            "success": True,
                            "source": str(source.absolute()),
                            "destination": str(dest.absolute()),
                            "message": f"Copied '{filename}' to chosen folder as '{dest_name}'",
                        }, indent=2),
                    )
                ]

            elif name == "apply_collection_poster":
                collection_id = arguments["collection_id"]
                filename = arguments["filename"]

                image_path = artwork_chosen / filename
                if not image_path.exists():
                    return [
                        TextContent(
                            type="text",
                            text=f"File not found in chosen folder: {filename}",
                        )
                    ]

                # Verify collection exists
                collections = await emby.get_collections()
                collection = next(
                    (c for c in collections if c.id == collection_id), None
                )
                if not collection:
                    return [TextContent(type="text", text="Collection not found")]

                # Convert to JPEG for Emby (better compatibility)
                img = Image.open(image_path)
                jpeg_buffer = io.BytesIO()
                img.convert("RGB").save(jpeg_buffer, "JPEG", quality=95)
                jpeg_data = jpeg_buffer.getvalue()

                await emby.set_item_image(collection_id, jpeg_data, content_type="image/jpeg")

                return [
                    TextContent(
                        type="text",
                        text=json.dumps({
                            "success": True,
                            "collection_id": collection_id,
                            "collection_name": collection.name,
                            "image": filename,
                            "message": f"Applied '{filename}' as poster for '{collection.name}'",
                        }, indent=2),
                    )
                ]

            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

        except Exception as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    return server


async def main():
    """Run the MCP server."""
    server = create_mcp_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

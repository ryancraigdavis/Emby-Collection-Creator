"""MCP server implementation for Emby collection management."""

import asyncio
import json
import re
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from ..config import get_settings
from ..services.emby import EmbyService
from ..services.tmdb import TMDbService


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


async def sync_collection_by_criteria(
    emby: "EmbyService",
    tmdb: "TMDbService",
    collection_id: str,
    collection_name: str,
    criteria: dict,
) -> str:
    """Sync a collection based on criteria. Returns a summary string."""
    movies = await emby.get_movies()
    current_ids = set(await emby.get_collection_items(collection_id))
    matching_ids = set()

    genres = criteria.get("genres", [])
    min_year = criteria.get("min_year")
    max_year = criteria.get("max_year")
    min_rating = criteria.get("min_rating")
    max_rating = criteria.get("max_rating")
    min_b_movie_score = criteria.get("min_b_movie_score")
    required_tags = set(t.lower() for t in criteria.get("tags", []))
    required_keywords = set(k.lower() for k in criteria.get("keywords", []))

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

        # TMDb-based filters (b-movie score, keywords)
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

    # Calculate changes
    to_add = matching_ids - current_ids
    to_remove = current_ids - matching_ids

    # Apply changes
    if to_add:
        await emby.add_to_collection(collection_id, list(to_add))
    if to_remove:
        await emby.remove_from_collection(collection_id, list(to_remove))

    return (
        f"Synced '{collection_name}': "
        f"{len(matching_ids)} movies match, "
        f"+{len(to_add)} added, -{len(to_remove)} removed"
    )


def create_mcp_server() -> Server:
    """Create and configure the MCP server."""
    server = Server("emby-collection-creator")
    settings = get_settings()

    emby = EmbyService(
        base_url=settings.emby_server_url,
        api_key=settings.emby_api_key,
    )
    tmdb = TMDbService(
        api_key=settings.tmdb_api_key,
        read_access_token=settings.tmdb_read_access_token,
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="get_library_movies",
                description="Get all movies from the Emby library with metadata",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="search_movies",
                description="Search movies by genre, year range, or search term",
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
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            if name == "get_library_movies":
                movies = await emby.get_movies()
                result = [
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
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "search_movies":
                years = None
                if arguments.get("min_year") or arguments.get("max_year"):
                    years = (
                        arguments.get("min_year", 1900),
                        arguments.get("max_year", 2100),
                    )
                movies = await emby.search_movies(
                    genres=arguments.get("genres"),
                    years=years,
                    search_term=arguments.get("search_term"),
                )
                result = [
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
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "get_movie_details":
                movies = await emby.get_movies()
                movie = next((m for m in movies if m.id == arguments["movie_id"]), None)
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
                movies = await emby.get_movies()
                items = [m for m in movies if m.id in item_ids]
                result = [
                    {"id": m.id, "name": m.name, "year": m.year} for m in items
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
                    emby, tmdb, collection_id, collection.name, criteria
                )
                return [TextContent(type="text", text=result)]

            elif name == "sync_all_collections":
                collections = await emby.get_collections()
                results = []

                for collection in collections:
                    criteria = decode_criteria(collection.overview)
                    if criteria:
                        result = await sync_collection_by_criteria(
                            emby, tmdb, collection.id, collection.name, criteria
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

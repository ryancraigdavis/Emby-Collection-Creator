# Emby Collection Creator

MCP server for AI-powered movie collection management in Emby. Use natural language with Claude to curate and organize your movie library.

## Features

- **Natural language collection creation** - "Create a collection of campy 80s slashers"
- **TMDb enrichment** - Fetches budget, keywords, and production company data
- **B-movie scoring** - Automatically identifies cult/camp films based on budget, keywords, and studio
- **Full collection management** - Create, modify, and delete collections via Claude
- **Smart sync** - Set criteria on collections and sync them to automatically add/remove matching movies

## Setup

### Prerequisites

- Python 3.12+
- [UV](https://docs.astral.sh/uv/) package manager
- [Doppler](https://www.doppler.com/) CLI (or use `.env` file)
- Emby server with API access
- TMDb API key (free at themoviedb.org)

### Environment Variables

Set these in Doppler or a `.env` file:

```
EMBY_SERVER_URL=http://your-emby-server:8096
EMBY_SERVER_API=your-emby-api-key
TMDB_API=your-tmdb-api-key
TMDB_READ_ACCESS_TOKEN=your-tmdb-read-access-token
```

### Install

```bash
uv sync
```

### Configure Claude Code

Add the MCP server to Claude Code:

```bash
claude mcp add --transport stdio emby-collection-creator \
  -- doppler run -- uv run python -m emby_collection_creator.mcp.server
```

Or without Doppler (using `.env`):

```bash
claude mcp add --transport stdio emby-collection-creator \
  -- uv run python -m emby_collection_creator.mcp.server
```

## Usage

After configuring, restart Claude Code and use `/mcp` to verify the server is connected.

Then just ask Claude:

- "Show me all my horror movies"
- "What horror movies do I have from the 1980s?"
- "Create a collection called 'Campy Slashers' with horror movies that have a high b-movie score"
- "Add Friday the 13th to the Campy Slashers collection"
- "What collections do I have?"
- "Set up the Campy Slashers collection to auto-sync horror movies from 1980-1992 with a b-movie score above 0.5"
- "Sync all my collections"

## MCP Tools

| Tool | Description |
|------|-------------|
| `get_library_movies` | List all movies in Emby |
| `search_movies` | Filter by genre, year, or search term |
| `get_movie_details` | Full metadata with TMDb enrichment |
| `enrich_movie_metadata` | Get TMDb data and b-movie score |
| `list_collections` | Show all collections |
| `get_collection_items` | Movies in a collection |
| `create_collection` | Create a new collection |
| `add_to_collection` | Add movies to a collection |
| `remove_from_collection` | Remove movies from a collection |
| `delete_collection` | Delete a collection |
| `set_collection_criteria` | Set sync criteria (genres, years, b-movie score, etc.) |
| `get_collection_criteria` | View criteria for a collection |
| `sync_collection` | Sync a collection based on its criteria |
| `sync_all_collections` | Sync all collections with criteria |

## Collection Sync

Collections can have sync criteria stored in their metadata. When you sync, the server:

1. Evaluates all movies against the criteria
2. Adds movies that match but aren't in the collection
3. Removes movies that no longer match

**Supported criteria:**
- `genres` - Required genres (e.g., Horror, Comedy)
- `min_year` / `max_year` - Year range
- `min_rating` / `max_rating` - Community rating range
- `min_b_movie_score` - Minimum b-movie score (0-1)
- `tags` - Required Emby tags
- `keywords` - Required TMDb keywords

The criteria is stored as a hidden comment in the collection's overview field in Emby, so it persists with your library.

## B-Movie Scoring

The TMDb service calculates a 0-1 "b-movie score" based on:

- **Budget** - Under $5M scores higher
- **Vote average** - Mid-range ratings (4-6.5) suggest cult appeal
- **Keywords** - "slasher", "gore", "campy", "cult film", etc.
- **Production companies** - Troma, Full Moon Features, The Asylum, etc.

## Development

```bash
# Run tests
uv run pytest

# Run MCP server directly (for debugging)
doppler run -- uv run python -m emby_collection_creator.mcp.server
```

## License

MIT

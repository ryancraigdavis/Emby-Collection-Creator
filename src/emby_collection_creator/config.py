"""Configuration management from a local .env file or environment variables."""

import os
from functools import lru_cache
from pathlib import Path

from attrs import define
from dotenv import load_dotenv

# Load secrets from the repo-root .env, which is authoritative — its values
# override anything already in the environment (e.g. a stale MCP env block).
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)


@define
class Settings:
    """Application settings."""

    emby_server_url: str
    emby_api_key: str
    tmdb_api_key: str
    tmdb_read_access_token: str
    tastedive_api_key: str
    trakt_client_id: str
    trakt_client_secret: str
    tmdb_user_access_token: str | None = None
    trakt_access_token: str | None = None
    claude_api_key: str | None = None
    comfyui_url: str = "http://127.0.0.1:8188"
    artwork_generated_dir: str = "./artwork/generated"
    artwork_chosen_dir: str = "./artwork/chosen"


@lru_cache
def get_settings() -> Settings:
    """Load settings from environment (Doppler injects these)."""
    return Settings(
        emby_server_url=os.environ["EMBY_SERVER_URL"],
        emby_api_key=os.environ["EMBY_SERVER_API"],
        tmdb_api_key=os.environ["TMDB_API"],
        tmdb_read_access_token=os.environ["TMDB_READ_ACCESS_TOKEN"],
        tastedive_api_key=os.environ["TASTEDIVE_API"],
        trakt_client_id=os.environ["TRAKT_TV_CLIENT_ID"],
        trakt_client_secret=os.environ["TRAKT_TV_CLIENT_SECRET"],
        tmdb_user_access_token=os.environ.get("TMDB_USER_ACCESS_TOKEN"),
        trakt_access_token=os.environ.get("TRAKT_ACCESS_TOKEN"),
        claude_api_key=os.environ.get("CLAUDE_API"),
    )

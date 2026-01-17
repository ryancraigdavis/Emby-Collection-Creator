"""Configuration management using Doppler or environment variables."""

import os
from functools import lru_cache

from attrs import define


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
        claude_api_key=os.environ.get("CLAUDE_API"),
    )

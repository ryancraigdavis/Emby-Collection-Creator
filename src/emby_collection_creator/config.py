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
    claude_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Load settings from environment (Doppler injects these)."""
    return Settings(
        emby_server_url=os.environ["EMBY_SERVER_URL"],
        emby_api_key=os.environ["EMBY_SERVER_API"],
        tmdb_api_key=os.environ["TMDB_API"],
        tmdb_read_access_token=os.environ["TMDB_READ_ACCESS_TOKEN"],
        claude_api_key=os.environ.get("CLAUDE_API"),
    )

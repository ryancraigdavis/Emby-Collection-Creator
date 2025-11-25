"""Emby data models."""

from attrs import define, field


@define
class LibraryItem:
    """Base class for Emby library items."""

    id: str
    name: str
    type: str


@define
class Movie:
    """Represents a movie in the Emby library."""

    id: str
    name: str
    year: int | None = None
    genres: list[str] = field(factory=list)
    tags: list[str] = field(factory=list)
    community_rating: float | None = None
    critic_rating: float | None = None
    overview: str | None = None
    tmdb_id: str | None = None
    imdb_id: str | None = None
    production_year: int | None = None
    studios: list[str] = field(factory=list)


@define
class Collection:
    """Represents a collection (BoxSet) in Emby."""

    id: str
    name: str
    item_ids: list[str] = field(factory=list)
    overview: str | None = None

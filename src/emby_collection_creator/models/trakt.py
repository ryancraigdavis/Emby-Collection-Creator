"""Trakt.tv data models."""

from attrs import define, field


@define
class TraktMovie:
    """Represents a movie from Trakt."""

    title: str
    year: int | None
    trakt_id: int
    slug: str
    imdb_id: str | None = None
    tmdb_id: int | None = None


@define
class TraktTrendingMovie:
    """Represents a trending movie with watcher count."""

    movie: TraktMovie
    watchers: int


@define
class TraktPopularMovie:
    """Represents a popular movie (just the movie data)."""

    movie: TraktMovie


@define
class TraktListItem:
    """Represents an item in a Trakt list."""

    rank: int
    movie: TraktMovie
    listed_at: str | None = None


@define
class TraktList:
    """Represents a Trakt list."""

    name: str
    description: str | None
    item_count: int
    likes: int
    user: str
    list_id: str
    slug: str
    items: list[TraktListItem] = field(factory=list)


@define
class TraktRecommendation:
    """Represents a Trakt recommendation."""

    movie: TraktMovie

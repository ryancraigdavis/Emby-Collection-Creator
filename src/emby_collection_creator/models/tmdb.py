"""TMDb data models."""

from attrs import define, field


@define
class TMDbKeyword:
    """Represents a TMDb keyword."""

    id: int
    name: str


@define
class TMDbMovie:
    """Represents enriched movie data from TMDb."""

    id: int
    title: str
    budget: int | None = None
    revenue: int | None = None
    keywords: list[TMDbKeyword] = field(factory=list)
    vote_average: float | None = None
    vote_count: int | None = None
    production_companies: list[str] = field(factory=list)
    release_date: str | None = None
    tagline: str | None = None

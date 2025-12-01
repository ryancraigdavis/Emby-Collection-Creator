"""TasteDive data models."""

from attrs import define


@define
class TasteDiveItem:
    """Represents a TasteDive recommendation item."""

    name: str
    type: str
    description: str | None = None
    wikipedia_url: str | None = None
    youtube_url: str | None = None
    youtube_id: str | None = None


@define
class TasteDiveResponse:
    """Represents a TasteDive API response."""

    query_items: list[TasteDiveItem]
    recommendations: list[TasteDiveItem]

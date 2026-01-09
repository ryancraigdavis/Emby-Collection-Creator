"""Emby data models."""

from attrs import define, field


@define
class LibraryItem:
    """Base class for Emby library items."""

    id: str
    name: str
    type: str


@define
class VideoStream:
    """Video stream metadata."""

    codec: str | None = None
    codec_tag: str | None = None
    width: int | None = None
    height: int | None = None
    bit_depth: int | None = None
    bitrate: int | None = None

    # HDR Info
    hdr_type: str | None = None
    video_range: str | None = None
    color_space: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None

    # Dolby Vision
    dv_profile: int | None = None
    dv_level: int | None = None
    dv_bl_present: bool = False
    dv_el_present: bool = False
    dv_rpu_present: bool = False

    # Computed
    is_4k: bool = False
    is_hdr: bool = False
    is_dolby_vision: bool = False
    is_hdr10_plus: bool = False
    dv_layer_type: str | None = None


@define
class AudioStream:
    """Audio stream metadata."""

    codec: str | None = None
    channels: int | None = None
    channel_layout: str | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    language: str | None = None
    is_default: bool = False
    is_atmos: bool = False
    is_dts_x: bool = False
    is_lossless: bool = False


@define
class MediaInfo:
    """Container for video/audio stream metadata."""

    container: str | None = None
    file_size: int | None = None
    total_bitrate: int | None = None
    video: VideoStream | None = None
    audio_streams: list[AudioStream] = field(factory=list)
    primary_audio: AudioStream | None = None


@define
class MovieSummary:
    """Lightweight movie representation for list views."""

    id: str
    name: str
    year: int | None = None
    genres: list[str] = field(factory=list)
    tmdb_id: str | None = None
    imdb_id: str | None = None
    community_rating: float | None = None


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
    media_info: MediaInfo | None = None
    all_media_sources: list[MediaInfo] = field(factory=list)


@define
class Collection:
    """Represents a collection (BoxSet) in Emby."""

    id: str
    name: str
    item_ids: list[str] = field(factory=list)
    overview: str | None = None

"""Tests for data models."""

import pytest
from emby_collection_creator.models.emby import Movie, Collection
from emby_collection_creator.models.tmdb import TMDbMovie, TMDbKeyword


class TestMovie:
    """Tests for Movie model."""

    def test_movie_creation(self):
        """Test basic movie creation."""
        movie = Movie(id="123", name="Test Movie", year=2020)
        assert movie.id == "123"
        assert movie.name == "Test Movie"
        assert movie.year == 2020
        assert movie.genres == []

    def test_movie_with_all_fields(self):
        """Test movie with all fields populated."""
        movie = Movie(
            id="456",
            name="Full Movie",
            year=1985,
            genres=["Horror", "Comedy"],
            tags=["campy", "cult"],
            community_rating=7.5,
            tmdb_id="789",
        )
        assert movie.genres == ["Horror", "Comedy"]
        assert movie.tags == ["campy", "cult"]
        assert movie.community_rating == 7.5


class TestCollection:
    """Tests for Collection model."""

    def test_collection_creation(self):
        """Test basic collection creation."""
        collection = Collection(id="c1", name="My Collection")
        assert collection.id == "c1"
        assert collection.name == "My Collection"
        assert collection.item_ids == []


class TestTMDbModels:
    """Tests for TMDb models."""

    def test_keyword_creation(self):
        """Test keyword creation."""
        keyword = TMDbKeyword(id=1, name="slasher")
        assert keyword.id == 1
        assert keyword.name == "slasher"

    def test_tmdb_movie_creation(self):
        """Test TMDb movie creation."""
        movie = TMDbMovie(
            id=123,
            title="Horror Film",
            budget=500000,
            keywords=[TMDbKeyword(id=1, name="gore")],
        )
        assert movie.id == 123
        assert movie.budget == 500000
        assert len(movie.keywords) == 1

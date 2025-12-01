"""Tests for data models."""

import pytest
from emby_collection_creator.models.emby import Movie, Collection
from emby_collection_creator.models.tmdb import TMDbMovie, TMDbKeyword
from emby_collection_creator.models.tastedive import TasteDiveItem, TasteDiveResponse
from emby_collection_creator.models.trakt import TraktMovie, TraktTrendingMovie, TraktList, TraktListItem


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


class TestTasteDiveModels:
    """Tests for TasteDive models."""

    def test_tastedive_item_creation(self):
        """Test TasteDive item creation."""
        item = TasteDiveItem(
            name="The Matrix",
            type="movie",
            description="A computer hacker learns...",
        )
        assert item.name == "The Matrix"
        assert item.type == "movie"
        assert item.description == "A computer hacker learns..."

    def test_tastedive_response_creation(self):
        """Test TasteDive response creation."""
        query_item = TasteDiveItem(name="Blade Runner", type="movie")
        rec_item = TasteDiveItem(name="Ghost in the Shell", type="movie")
        response = TasteDiveResponse(
            query_items=[query_item],
            recommendations=[rec_item],
        )
        assert len(response.query_items) == 1
        assert len(response.recommendations) == 1
        assert response.recommendations[0].name == "Ghost in the Shell"


class TestTraktModels:
    """Tests for Trakt models."""

    def test_trakt_movie_creation(self):
        """Test Trakt movie creation."""
        movie = TraktMovie(
            title="Inception",
            year=2010,
            trakt_id=16662,
            slug="inception-2010",
            imdb_id="tt1375666",
            tmdb_id=27205,
        )
        assert movie.title == "Inception"
        assert movie.year == 2010
        assert movie.trakt_id == 16662
        assert movie.tmdb_id == 27205

    def test_trakt_trending_movie_creation(self):
        """Test Trakt trending movie creation."""
        movie = TraktMovie(
            title="Dune",
            year=2021,
            trakt_id=12345,
            slug="dune-2021",
        )
        trending = TraktTrendingMovie(movie=movie, watchers=1500)
        assert trending.watchers == 1500
        assert trending.movie.title == "Dune"

    def test_trakt_list_creation(self):
        """Test Trakt list creation."""
        lst = TraktList(
            name="Best Horror Movies",
            description="A curated list of horror films",
            item_count=50,
            likes=1200,
            user="horror_fan",
            list_id="123456",
            slug="best-horror-movies",
        )
        assert lst.name == "Best Horror Movies"
        assert lst.item_count == 50
        assert lst.likes == 1200

    def test_trakt_list_item_creation(self):
        """Test Trakt list item creation."""
        movie = TraktMovie(
            title="The Shining",
            year=1980,
            trakt_id=999,
            slug="the-shining-1980",
        )
        item = TraktListItem(rank=1, movie=movie, listed_at="2023-01-01")
        assert item.rank == 1
        assert item.movie.title == "The Shining"

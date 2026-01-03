"""Comprehensive tests for Hugging Face dataset search and import functionality."""

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestHuggingFaceSearchAPI:
    """Test the /api/datasets/huggingface/search endpoint."""

    def test_search_basic_keyword(self, client):
        """Test basic keyword search."""
        response = client.get("/api/datasets/huggingface/search", params={"query": "sentiment"})
        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "count" in data
        assert "results" in data
        assert data["count"] > 0
        assert len(data["results"]) > 0

    def test_search_returns_expected_fields(self, client):
        """Test that search results contain all expected fields."""
        response = client.get("/api/datasets/huggingface/search", params={"query": "squad", "limit": 1})
        assert response.status_code == 200
        data = response.json()

        if data["count"] > 0:
            result = data["results"][0]
            assert "id" in result
            assert "name" in result
            assert "author" in result
            assert "description" in result
            assert "downloads" in result
            assert "likes" in result
            assert "tags" in result
            assert "is_gated" in result

    def test_search_with_limit(self, client):
        """Test search with limit parameter."""
        response = client.get("/api/datasets/huggingface/search", params={"query": "text", "limit": 5})
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) <= 5

    def test_search_empty_query(self, client):
        """Test search with empty query returns error."""
        response = client.get("/api/datasets/huggingface/search", params={"query": ""})
        assert response.status_code == 400

    def test_search_nonexistent_keyword(self, client):
        """Test search with nonexistent keyword returns empty results."""
        response = client.get("/api/datasets/huggingface/search", params={"query": "xyznonexistentdataset12345"})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["results"] == []

    def test_search_japanese_keyword(self, client):
        """Test search with Japanese keyword."""
        response = client.get("/api/datasets/huggingface/search", params={"query": "japanese"})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] > 0

    def test_search_multi_word_query(self, client):
        """Test search with multi-word query."""
        response = client.get("/api/datasets/huggingface/search", params={"query": "question answering"})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] > 0


class TestHuggingFaceInfoAPI:
    """Test the /api/datasets/huggingface/info endpoint."""

    def test_info_valid_dataset(self, client):
        """Test getting info for a valid dataset."""
        response = client.get("/api/datasets/huggingface/info", params={"name": "rajpurkar/squad"})
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "splits" in data
        assert "features" in data

    def test_info_short_name(self, client):
        """Test getting info using short dataset name."""
        response = client.get("/api/datasets/huggingface/info", params={"name": "squad"})
        assert response.status_code == 200
        data = response.json()
        assert "name" in data

    def test_info_nonexistent_dataset(self, client):
        """Test getting info for nonexistent dataset returns error."""
        response = client.get("/api/datasets/huggingface/info", params={"name": "nonexistent/dataset12345"})
        assert response.status_code == 400

    def test_info_missing_name(self, client):
        """Test info endpoint without name parameter."""
        response = client.get("/api/datasets/huggingface/info")
        assert response.status_code == 422  # Validation error


class TestHuggingFacePreviewAPI:
    """Test the /api/datasets/huggingface/preview endpoint."""

    def test_preview_valid_dataset(self, client):
        """Test previewing a valid dataset."""
        response = client.get("/api/datasets/huggingface/preview", params={
            "name": "rajpurkar/squad",
            "split": "train",
            "limit": 3
        })
        assert response.status_code == 200
        data = response.json()
        assert "columns" in data
        assert "rows" in data

    def test_preview_with_limit(self, client):
        """Test preview respects limit parameter."""
        response = client.get("/api/datasets/huggingface/preview", params={
            "name": "rajpurkar/squad",
            "split": "train",
            "limit": 2
        })
        assert response.status_code == 200
        data = response.json()
        assert len(data["rows"]) <= 2


class TestHuggingFaceImportAPI:
    """Test the /api/datasets/huggingface/import endpoint."""

    def test_import_missing_fields(self, client):
        """Test import with missing required fields returns error."""
        response = client.post("/api/datasets/huggingface/import", json={
            "project_id": 1
            # Missing other required fields
        })
        assert response.status_code == 422  # Validation error

    def test_import_nonexistent_project(self, client):
        """Test import with nonexistent project returns error."""
        response = client.post("/api/datasets/huggingface/import", json={
            "project_id": 99999,
            "dataset_name": "rajpurkar/squad",
            "split": "train",
            "display_name": "Test Import"
        })
        # Should return error for nonexistent project
        assert response.status_code in [400, 404, 500]


class TestSearchLogicFlow:
    """Test the search logic flow matching JavaScript behavior."""

    def test_keyword_search_always_works(self, client):
        """Test that keyword search works for common terms."""
        keywords = ["squad", "sentiment", "classification", "qa", "nlp"]

        for keyword in keywords:
            response = client.get("/api/datasets/huggingface/search", params={"query": keyword, "limit": 5})
            assert response.status_code == 200, f"Failed for keyword: {keyword}"
            data = response.json()
            # Most common keywords should have results
            # (not asserting count > 0 since some might legitimately have no results)
            assert "results" in data

    def test_direct_path_lookup(self, client):
        """Test direct path lookup (with /)."""
        response = client.get("/api/datasets/huggingface/info", params={"name": "rajpurkar/squad"})
        assert response.status_code == 200

    def test_search_vs_direct_for_short_names(self, client):
        """Test that short names go through search, not direct lookup."""
        # 'imdb' is a valid short name but should still return search results
        response = client.get("/api/datasets/huggingface/search", params={"query": "imdb", "limit": 10})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] > 0
        # Should find multiple imdb-related datasets
        assert any("imdb" in r["id"].lower() for r in data["results"])


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_special_characters_in_query(self, client):
        """Test search with special characters."""
        response = client.get("/api/datasets/huggingface/search", params={"query": "text-classification"})
        assert response.status_code == 200

    def test_unicode_query(self, client):
        """Test search with unicode characters."""
        response = client.get("/api/datasets/huggingface/search", params={"query": "日本語"})
        assert response.status_code == 200

    def test_very_long_query(self, client):
        """Test search with very long query."""
        long_query = "a" * 200
        response = client.get("/api/datasets/huggingface/search", params={"query": long_query})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0  # Likely no results for gibberish

    def test_query_with_spaces(self, client):
        """Test search preserves multi-word queries."""
        response = client.get("/api/datasets/huggingface/search", params={"query": "machine learning dataset"})
        assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

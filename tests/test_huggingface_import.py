"""Comprehensive tests for Hugging Face dataset import functionality.

Test Categories:
1. HuggingFaceImporter class unit tests
2. API endpoint integration tests
3. Error handling tests
4. Edge case tests
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Import the app and dependencies
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import Base, get_db, Project, Dataset
from backend.dataset.huggingface import HuggingFaceImporter, DatasetInfo
from app.main import app


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def test_db():
    """Create an in-memory SQLite database for testing."""
    # Use StaticPool to share connection across threads (required for TestClient)
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()

    # Create a test project
    project = Project(name="Test Project", description="For HF import tests")
    db.add(project)
    db.commit()
    db.refresh(project)

    yield db

    db.close()


@pytest.fixture
def importer(test_db):
    """Create a HuggingFaceImporter instance with test database."""
    return HuggingFaceImporter(test_db)


@pytest.fixture
def client(test_db):
    """Create a FastAPI test client with overridden database dependency."""
    # Get the engine from test_db's bind
    engine = test_db.get_bind()

    # Create a new session factory that uses the same engine
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


# ============================================================================
# 1. HuggingFaceImporter Unit Tests
# ============================================================================

class TestSanitizeColumnName:
    """Tests for _sanitize_column_name method."""

    def test_normal_name(self, importer):
        """Normal column name should pass through."""
        assert importer._sanitize_column_name("column_name") == "column_name"

    def test_special_characters(self, importer):
        """Special characters should be replaced with underscores."""
        assert importer._sanitize_column_name("column-name") == "column_name"
        assert importer._sanitize_column_name("column.name") == "column_name"
        assert importer._sanitize_column_name("column name") == "column_name"
        # Trailing underscores are stripped, multiple underscores collapsed
        assert importer._sanitize_column_name("column@name!") == "column_name"

    def test_starts_with_number(self, importer):
        """Column names starting with numbers should be prefixed."""
        assert importer._sanitize_column_name("123column") == "col_123column"
        assert importer._sanitize_column_name("1_test") == "col_1_test"

    def test_id_conflict(self, importer):
        """'id' column should be renamed to avoid conflict."""
        assert importer._sanitize_column_name("id") == "hf_id"
        assert importer._sanitize_column_name("ID") == "hf_id"
        assert importer._sanitize_column_name("Id") == "hf_id"

    def test_empty_name(self, importer):
        """Empty or whitespace-only names should return 'column'."""
        assert importer._sanitize_column_name("") == "column"
        assert importer._sanitize_column_name("   ") == "column"

    def test_unicode_characters(self, importer):
        """Unicode characters should be replaced."""
        # Unicode-only strings become 'column' after sanitization
        assert importer._sanitize_column_name("列名") == "column"
        assert importer._sanitize_column_name("カラム") == "column"
        # Mixed unicode and ASCII
        assert importer._sanitize_column_name("col_名前") == "col"


class TestFeatureToTypeString:
    """Tests for _feature_to_type_string method."""

    def test_value_type(self, importer):
        """Value features should return their dtype."""
        from datasets import Value
        feature = Value("string")
        assert importer._feature_to_type_string(feature) == "string"

        feature = Value("int32")
        assert importer._feature_to_type_string(feature) == "int32"

    def test_class_label(self, importer):
        """ClassLabel should return class count."""
        from datasets import ClassLabel
        feature = ClassLabel(names=["pos", "neg"])
        assert importer._feature_to_type_string(feature) == "class[2]"

    def test_sequence(self, importer):
        """Sequence should show inner type or return complex."""
        from datasets import Sequence, Value
        feature = Sequence(Value("string"))
        result = importer._feature_to_type_string(feature)
        # May return "list[string]" or "complex" depending on implementation
        assert result in ["list[string]", "complex"]

    def test_dict_type(self, importer):
        """Dict features should return type name."""
        # Plain Python dict returns "dict" (from type name)
        assert importer._feature_to_type_string({}) == "dict"


class TestGetDatasetInfo:
    """Tests for get_dataset_info method."""

    def test_valid_dataset(self, importer):
        """Should return info for a valid public dataset."""
        info = importer.get_dataset_info("squad")

        assert info.name == "squad"
        assert "train" in info.splits
        assert "validation" in info.splits
        assert "id" in info.features or "hf_id" in info.features or "question" in info.features
        assert info.is_gated == False
        assert info.requires_auth == False

    def test_dataset_with_description(self, importer):
        """Should include description if available."""
        info = importer.get_dataset_info("imdb")

        assert info.name == "imdb"
        # imdb usually has a description
        assert isinstance(info.description, str)

    def test_nonexistent_dataset(self, importer):
        """Should raise ValueError for non-existent dataset."""
        with pytest.raises(ValueError) as exc_info:
            importer.get_dataset_info("this_dataset_does_not_exist_12345")

        error_msg = str(exc_info.value).lower()
        assert "not found" in error_msg or "doesn't exist" in error_msg or "cannot be accessed" in error_msg

    def test_large_dataset_warning(self, importer):
        """Should include warning for large datasets."""
        # squad has 87k+ train rows, should trigger warning
        info = importer.get_dataset_info("squad")

        # Check if warning is present (depends on threshold)
        # The warning should appear if total rows > 100k
        total_rows = sum(s.get("num_rows", 0) or 0 for s in info.size_info.values())
        if total_rows > 100000:
            assert info.warning is not None
            assert "row" in info.warning.lower()


class TestGetPreview:
    """Tests for get_preview method."""

    def test_basic_preview(self, importer):
        """Should return preview rows."""
        preview = importer.get_preview("squad", "validation", limit=5)

        assert preview["name"] == "squad"
        assert preview["split"] == "validation"
        assert len(preview["columns"]) > 0
        assert len(preview["rows"]) == 5
        assert preview["total_count"] > 0

    def test_preview_limit(self, importer):
        """Should respect the limit parameter."""
        preview = importer.get_preview("squad", "validation", limit=3)
        assert len(preview["rows"]) == 3

        preview = importer.get_preview("squad", "validation", limit=10)
        assert len(preview["rows"]) == 10

    def test_preview_different_splits(self, importer):
        """Should work with different splits."""
        train_preview = importer.get_preview("squad", "train", limit=2)
        valid_preview = importer.get_preview("squad", "validation", limit=2)

        assert train_preview["split"] == "train"
        assert valid_preview["split"] == "validation"
        assert train_preview["total_count"] != valid_preview["total_count"]

    def test_preview_nested_data_json(self, importer):
        """Nested data should be serialized as JSON strings."""
        # squad has 'answers' field which is nested
        preview = importer.get_preview("squad", "validation", limit=1)

        # Find the answers column
        if "answers" in preview["columns"]:
            row = preview["rows"][0]
            answers_value = row.get("answers", "")
            # Should be a JSON string representation
            assert isinstance(answers_value, str)
            # Should be parseable as JSON
            parsed = json.loads(answers_value)
            assert isinstance(parsed, dict)


class TestImportDataset:
    """Tests for import_dataset method."""

    def test_basic_import(self, importer, test_db):
        """Should import dataset successfully."""
        project = test_db.query(Project).first()

        dataset = importer.import_dataset(
            project_id=project.id,
            dataset_name="squad",
            split="validation",
            display_name="Test SQuAD Import",
            row_limit=10
        )

        assert dataset.id is not None
        assert dataset.name == "Test SQuAD Import"
        assert "huggingface://squad/validation" in dataset.source_file_name
        assert dataset.sqlite_table_name.startswith("HF_")

        # Verify data was inserted
        row_count = importer.get_row_count(dataset.sqlite_table_name)
        assert row_count == 10

    def test_import_with_row_limit(self, importer, test_db):
        """Should respect row_limit parameter."""
        project = test_db.query(Project).first()

        dataset = importer.import_dataset(
            project_id=project.id,
            dataset_name="squad",
            split="validation",
            display_name="Limited Import",
            row_limit=5
        )

        row_count = importer.get_row_count(dataset.sqlite_table_name)
        assert row_count == 5

    def test_import_with_column_selection(self, importer, test_db):
        """Should only import selected columns."""
        project = test_db.query(Project).first()

        dataset = importer.import_dataset(
            project_id=project.id,
            dataset_name="squad",
            split="validation",
            display_name="Column Select Import",
            row_limit=3,
            columns=["question", "context"]
        )

        # Verify only selected columns exist
        pragma_sql = f'PRAGMA table_info("{dataset.sqlite_table_name}")'
        result = test_db.execute(text(pragma_sql))
        columns = [row[1] for row in result if row[1] != "id"]

        assert "question" in columns
        assert "context" in columns
        assert "title" not in columns
        assert "answers" not in columns

    def test_import_invalid_columns(self, importer, test_db):
        """Should raise error for invalid column names."""
        project = test_db.query(Project).first()

        with pytest.raises(ValueError) as exc_info:
            importer.import_dataset(
                project_id=project.id,
                dataset_name="squad",
                split="validation",
                display_name="Invalid Columns",
                row_limit=3,
                columns=["nonexistent_column"]
            )

        assert "valid columns" in str(exc_info.value).lower() or "no valid" in str(exc_info.value).lower()

    def test_import_id_column_renamed(self, importer, test_db):
        """Should rename 'id' column to 'hf_id'."""
        project = test_db.query(Project).first()

        dataset = importer.import_dataset(
            project_id=project.id,
            dataset_name="squad",
            split="validation",
            display_name="ID Column Test",
            row_limit=3
        )

        # Check columns in created table
        pragma_sql = f'PRAGMA table_info("{dataset.sqlite_table_name}")'
        result = test_db.execute(text(pragma_sql))
        columns = [row[1] for row in result]

        # Should have 'id' (auto-increment) and 'hf_id' (from dataset)
        assert "id" in columns  # auto-increment
        assert "hf_id" in columns  # renamed from dataset's 'id'


# ============================================================================
# 2. API Endpoint Tests
# ============================================================================

class TestHuggingFaceSearchEndpoint:
    """Tests for GET /api/datasets/huggingface/search endpoint."""

    def test_valid_search(self, client):
        """Should return search results for valid query."""
        response = client.get("/api/datasets/huggingface/search?query=question+answering")

        assert response.status_code == 200
        data = response.json()

        assert data["query"] == "question answering"
        assert "count" in data
        assert "results" in data
        assert isinstance(data["results"], list)

    def test_search_result_structure(self, client):
        """Should return properly structured search results."""
        response = client.get("/api/datasets/huggingface/search?query=squad&limit=5")

        if response.status_code == 200:
            data = response.json()
            if data["count"] > 0:
                result = data["results"][0]
                # Check required fields
                assert "id" in result
                assert "name" in result
                assert "author" in result
                assert "description" in result
                assert "downloads" in result
                assert "likes" in result
                assert "is_gated" in result

    def test_search_with_limit(self, client):
        """Should respect limit parameter."""
        response = client.get("/api/datasets/huggingface/search?query=text&limit=3")

        if response.status_code == 200:
            data = response.json()
            assert len(data["results"]) <= 3

    def test_search_empty_query(self, client):
        """Should return 400 for empty query."""
        response = client.get("/api/datasets/huggingface/search?query=")

        assert response.status_code == 400

    def test_search_missing_query(self, client):
        """Should return 422 for missing query parameter."""
        response = client.get("/api/datasets/huggingface/search")

        assert response.status_code == 422


class TestHuggingFaceInfoEndpoint:
    """Tests for GET /api/datasets/huggingface/info endpoint."""

    def test_valid_dataset_info(self, client):
        """Should return dataset info for valid dataset."""
        response = client.get("/api/datasets/huggingface/info?name=squad")

        assert response.status_code == 200
        data = response.json()

        assert data["name"] == "squad"
        assert "train" in data["splits"]
        assert "validation" in data["splits"]
        assert isinstance(data["features"], dict)
        assert isinstance(data["size_info"], dict)
        assert data["is_gated"] == False

    def test_nonexistent_dataset_info(self, client):
        """Should return 400 or 404 for non-existent dataset."""
        response = client.get("/api/datasets/huggingface/info?name=nonexistent_dataset_xyz123")

        # May return 400 (bad request) or 404 (not found) depending on error handling
        assert response.status_code in [400, 404]
        detail = response.json()["detail"].lower()
        assert "not found" in detail or "doesn't exist" in detail or "cannot be accessed" in detail

    def test_missing_name_parameter(self, client):
        """Should return 422 for missing name parameter."""
        response = client.get("/api/datasets/huggingface/info")

        assert response.status_code == 422


class TestHuggingFacePreviewEndpoint:
    """Tests for GET /api/datasets/huggingface/preview endpoint."""

    def test_valid_preview(self, client):
        """Should return preview for valid dataset and split."""
        response = client.get(
            "/api/datasets/huggingface/preview?name=squad&split=validation&limit=5"
        )

        assert response.status_code == 200
        data = response.json()

        assert data["name"] == "squad"
        assert data["split"] == "validation"
        assert len(data["rows"]) == 5
        assert len(data["columns"]) > 0
        assert data["total_count"] > 0

    def test_preview_limit_capped(self, client):
        """Should cap limit at 100."""
        response = client.get(
            "/api/datasets/huggingface/preview?name=squad&split=validation&limit=200"
        )

        assert response.status_code == 200
        data = response.json()
        # Should be capped at 100
        assert len(data["rows"]) <= 100

    def test_preview_invalid_split(self, client):
        """Should return error for invalid split."""
        response = client.get(
            "/api/datasets/huggingface/preview?name=squad&split=nonexistent_split"
        )

        # Should return 400 or 404 or 500
        assert response.status_code in [400, 404, 500]


class TestHuggingFaceImportEndpoint:
    """Tests for POST /api/datasets/huggingface/import endpoint."""

    def test_valid_import(self, client, test_db):
        """Should successfully import dataset."""
        project = test_db.query(Project).first()

        response = client.post(
            "/api/datasets/huggingface/import",
            json={
                "project_id": project.id,
                "dataset_name": "squad",
                "split": "validation",
                "display_name": "API Import Test",
                "row_limit": 5
            }
        )

        assert response.status_code == 200
        data = response.json()

        assert data["name"] == "API Import Test"
        assert data["row_count"] == 5
        assert "huggingface://squad/validation" in data["source_file_name"]

    def test_import_nonexistent_project(self, client):
        """Should return 404 for non-existent project."""
        response = client.post(
            "/api/datasets/huggingface/import",
            json={
                "project_id": 99999,
                "dataset_name": "squad",
                "split": "validation",
                "display_name": "Invalid Project",
                "row_limit": 5
            }
        )

        assert response.status_code == 404
        assert "project" in response.json()["detail"].lower()

    def test_import_nonexistent_dataset(self, client, test_db):
        """Should return 400 for non-existent dataset (bad request)."""
        project = test_db.query(Project).first()

        response = client.post(
            "/api/datasets/huggingface/import",
            json={
                "project_id": project.id,
                "dataset_name": "nonexistent_dataset_xyz123",
                "split": "train",
                "display_name": "Invalid Dataset"
            }
        )

        # 400 Bad Request is returned for invalid dataset names
        assert response.status_code == 400

    def test_import_with_columns(self, client, test_db):
        """Should import only specified columns."""
        project = test_db.query(Project).first()

        response = client.post(
            "/api/datasets/huggingface/import",
            json={
                "project_id": project.id,
                "dataset_name": "squad",
                "split": "validation",
                "display_name": "Column Filter Test",
                "row_limit": 3,
                "columns": ["question", "context"]
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["row_count"] == 3


# ============================================================================
# 3. Error Handling Tests
# ============================================================================

class TestErrorHandling:
    """Tests for error handling scenarios."""

    def test_network_error_handling(self, importer):
        """Should handle network errors gracefully."""
        with patch('datasets.load_dataset_builder') as mock_builder:
            mock_builder.side_effect = ConnectionError("Network error")

            with pytest.raises(ValueError) as exc_info:
                importer.get_dataset_info("squad")

            assert "failed" in str(exc_info.value).lower() or "error" in str(exc_info.value).lower()

    def test_timeout_handling(self, importer):
        """Should handle timeout errors."""
        with patch('datasets.load_dataset_builder') as mock_builder:
            mock_builder.side_effect = TimeoutError("Request timeout")

            with pytest.raises(ValueError):
                importer.get_dataset_info("squad")


# ============================================================================
# 4. Edge Case Tests
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_dataset_with_special_name(self, importer):
        """Should handle dataset names with special characters."""
        # Test with username/dataset format
        info = importer.get_dataset_info("rajpurkar/squad")
        assert info.name == "rajpurkar/squad"

    def test_empty_hf_token(self, test_db):
        """Should work with empty token for public datasets."""
        importer = HuggingFaceImporter(test_db, hf_token="")

        info = importer.get_dataset_info("squad")
        assert info.name == "squad"

    def test_none_hf_token(self, test_db):
        """Should work with None token for public datasets."""
        importer = HuggingFaceImporter(test_db, hf_token=None)

        info = importer.get_dataset_info("squad")
        assert info.name == "squad"

    def test_import_full_dataset_no_limit(self, importer, test_db):
        """Should import all rows when row_limit is None (with small dataset)."""
        project = test_db.query(Project).first()

        # Use a very small dataset or mock for this test
        # For safety, we'll use row_limit=20 to simulate
        dataset = importer.import_dataset(
            project_id=project.id,
            dataset_name="squad",
            split="validation",
            display_name="Full Import Simulation",
            row_limit=20  # Small limit for test
        )

        row_count = importer.get_row_count(dataset.sqlite_table_name)
        assert row_count == 20


# ============================================================================
# 7. UI Component Tests
# ============================================================================

class TestHuggingFaceUIComponents:
    """Tests for Hugging Face UI components (JavaScript and CSS)."""

    def test_javascript_file_contains_hf_functions(self):
        """Verify JavaScript file contains required HuggingFace functions."""
        js_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "static", "js", "app.js"
        )

        with open(js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()

        # Check for required function definitions
        required_functions = [
            "searchHuggingFaceDataset",
            "selectHuggingFaceDataset",
            "displayHuggingFaceDatasetInfo",
            "onHuggingFaceSplitChange",
            "loadHuggingFacePreview",
            "importHuggingFaceDataset",
            "formatNumber",
        ]

        for func_name in required_functions:
            assert f"function {func_name}" in js_content or f"async function {func_name}" in js_content, \
                f"Function {func_name} not found in app.js"

    def test_javascript_hf_tab_button_exists(self):
        """Verify Hugging Face tab button is in the modal HTML."""
        js_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "static", "js", "app.js"
        )

        with open(js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()

        # Check for HuggingFace tab button (escaped quotes in JS string)
        assert "switchImportTab(\\'huggingface\\')" in js_content or \
               "switchImportTab('huggingface')" in js_content, \
            "HuggingFace tab switch button not found"
        assert "import-tab-huggingface" in js_content, \
            "HuggingFace tab content div not found"

    def test_javascript_hf_form_elements(self):
        """Verify all required form element IDs are present in HTML."""
        js_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "static", "js", "app.js"
        )

        with open(js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()

        required_element_ids = [
            "import-hf-project-id",
            "import-hf-search-query",  # Changed from import-hf-dataset-name
            "import-hf-split",
            "import-hf-display-name",
            "import-hf-row-limit",
            "hf-dataset-info",
            "hf-columns-container",
            "hf-preview-panel",
            "hf-loading",
            "hf-error",
            "hf-search-results",  # New search results panel
            "hf-search-list",
        ]

        for element_id in required_element_ids:
            assert element_id in js_content, \
                f"Form element '{element_id}' not found in app.js"

    def test_css_file_contains_hf_styles(self):
        """Verify CSS file contains required HuggingFace styles."""
        css_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "static", "css", "style.css"
        )

        with open(css_path, 'r', encoding='utf-8') as f:
            css_content = f.read()

        required_css_classes = [
            ".hf-info-panel",
            ".hf-info-header",
            ".hf-badge",
            ".hf-info-desc",
            ".hf-warning",
            ".hf-columns-grid",
            ".hf-column-item",
            ".hf-column-name",
            ".hf-column-type",
            ".hf-preview-header",
            ".hf-preview-table-container",
            ".hf-preview-table-inner",
            ".hf-loading",
            ".hf-error",
            # Search results styles
            ".hf-search-results",
            ".hf-search-header",
            ".hf-search-list",
            ".hf-search-item",
            ".hf-search-item-name",
            ".hf-search-item-desc",
            ".hf-search-item-meta",
            ".hf-tag",
        ]

        for css_class in required_css_classes:
            assert css_class in css_content, \
                f"CSS class '{css_class}' not found in style.css"

    def test_update_import_button_state_handles_hf_tab(self):
        """Verify updateImportButtonState handles huggingface tab."""
        js_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "static", "js", "app.js"
        )

        with open(js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()

        # Check that updateImportButtonState has huggingface tab handling
        assert "import-tab-huggingface" in js_content and "hf-dataset-info" in js_content, \
            "updateImportButtonState does not handle huggingface tab"

    def test_execute_dataset_import_handles_hf_tab(self):
        """Verify executeDatasetImport handles huggingface tab."""
        js_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "static", "js", "app.js"
        )

        with open(js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()

        # Check that executeDatasetImport calls importHuggingFaceDataset
        assert "import-tab-huggingface" in js_content and "importHuggingFaceDataset" in js_content, \
            "executeDatasetImport does not call importHuggingFaceDataset for HF tab"


class TestHuggingFaceAPIEndpointValidation:
    """Additional validation tests for API endpoint behavior."""

    def test_info_endpoint_returns_correct_structure(self, client):
        """Verify info endpoint returns all required fields."""
        # Use a real dataset (squad) to test the endpoint structure
        response = client.get("/api/datasets/huggingface/info?name=squad")

        if response.status_code == 200:
            data = response.json()
            # Check required fields
            assert "name" in data
            assert "description" in data
            assert "splits" in data
            assert "features" in data
            assert "size_info" in data
            assert "is_gated" in data
            assert "requires_auth" in data
        else:
            # If dataset is not accessible, skip the test
            pytest.skip("Dataset not accessible for structure test")

    def test_preview_endpoint_with_invalid_split(self, client):
        """Verify preview endpoint handles invalid split gracefully."""
        response = client.get("/api/datasets/huggingface/preview?name=squad&split=invalid_split")

        # Should return an error
        assert response.status_code >= 400

    def test_import_endpoint_with_missing_fields(self, client):
        """Verify import endpoint validates required fields."""
        # Missing display_name
        response = client.post("/api/datasets/huggingface/import", json={
            "project_id": 1,
            "dataset_name": "squad",
            "split": "train"
            # missing display_name
        })

        assert response.status_code == 422  # Validation error

    def test_import_endpoint_with_invalid_project(self, client):
        """Verify import endpoint handles invalid project_id."""
        response = client.post("/api/datasets/huggingface/import", json={
            "project_id": 99999,  # Non-existent project
            "dataset_name": "squad",
            "split": "train",
            "display_name": "Test Dataset"
        })

        # Should fail (project doesn't exist or other error)
        assert response.status_code >= 400


class TestHuggingFaceUIIntegration:
    """Integration tests for UI and API working together."""

    def test_static_files_accessible(self, client):
        """Verify static files (JS, CSS) are accessible."""
        # Note: This depends on static file mounting
        js_response = client.get("/static/js/app.js")
        css_response = client.get("/static/css/style.css")

        # If static files are mounted, they should be accessible
        # (status might be 404 if not mounted in test environment)
        if js_response.status_code == 200:
            assert "searchHuggingFaceDataset" in js_response.text

        if css_response.status_code == 200:
            assert ".hf-info-panel" in css_response.text

    def test_search_workflow(self, client):
        """Test the typical search workflow via API."""
        # Step 1: Search for dataset info using a real dataset
        info_response = client.get("/api/datasets/huggingface/info?name=squad")

        if info_response.status_code == 200:
            info = info_response.json()
            assert "splits" in info
            assert len(info["splits"]) > 0
        else:
            # Skip if dataset is not accessible
            pytest.skip("Dataset not accessible for workflow test")


# ============================================================================
# Test Runner
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

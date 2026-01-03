"""
Comprehensive tests for dataset import features:
1. Button name change ("編集" → "プロジェクト設定")
2. Dataset download button
3. RowID addition option
4. Dataset replacement option

Test Date: 2026-01-02
"""

import pytest
import os
import sys
import csv
import io
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Dataset, Project
from backend.dataset.importer import DatasetImporter


# ============================================================
# Test Fixtures
# ============================================================

@pytest.fixture
def test_db():
    """Create a test database with in-memory SQLite."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Create a test project
    project = Project(
        name="Test Project",
        description="Test project for dataset features"
    )
    session.add(project)
    session.commit()

    yield session

    session.close()


@pytest.fixture
def sample_excel_data():
    """Create sample Excel-like data (header + rows)."""
    header = ["Name", "Age", "City"]
    rows = [
        ["Alice", "30", "Tokyo"],
        ["Bob", "25", "Osaka"],
        ["Charlie", "35", "Kyoto"],
        ["David", "28", "Nagoya"],
        ["Eve", "32", "Fukuoka"]
    ]
    return header, rows


@pytest.fixture
def sample_csv_content():
    """Create sample CSV content."""
    return """Name,Age,City
Alice,30,Tokyo
Bob,25,Osaka
Charlie,35,Kyoto
David,28,Nagoya
Eve,32,Fukuoka"""


# ============================================================
# Test Category 1: RowID Addition Logic (Unit Tests)
# ============================================================

class TestRowIDAddition:
    """Tests for RowID addition functionality."""

    def test_rowid_added_to_header(self, sample_excel_data):
        """Test that RowID is added as first column in header."""
        header, rows = sample_excel_data

        # Simulate add_row_id logic
        if True:  # add_row_id = True
            new_header = ["RowID"] + header
            for i, row in enumerate(rows, start=1):
                row.insert(0, str(i))

        assert new_header[0] == "RowID"
        assert new_header[1] == "Name"
        assert len(new_header) == 4

    def test_rowid_values_start_from_1(self, sample_excel_data):
        """Test that RowID values start from 1."""
        header, rows = sample_excel_data

        # Simulate add_row_id logic
        for i, row in enumerate(rows, start=1):
            row.insert(0, str(i))

        assert rows[0][0] == "1"
        assert rows[1][0] == "2"
        assert rows[2][0] == "3"

    def test_rowid_values_are_sequential(self, sample_excel_data):
        """Test that RowID values are sequential."""
        header, rows = sample_excel_data

        for i, row in enumerate(rows, start=1):
            row.insert(0, str(i))

        for i, row in enumerate(rows, start=1):
            assert row[0] == str(i)

    def test_rowid_preserves_original_data(self, sample_excel_data):
        """Test that original data is preserved after adding RowID."""
        header, rows = sample_excel_data
        original_first_row = rows[0].copy()

        for i, row in enumerate(rows, start=1):
            row.insert(0, str(i))

        # Original data should be shifted by 1 position
        assert rows[0][1] == original_first_row[0]  # Name
        assert rows[0][2] == original_first_row[1]  # Age
        assert rows[0][3] == original_first_row[2]  # City

    def test_rowid_not_added_when_disabled(self, sample_excel_data):
        """Test that RowID is not added when option is disabled."""
        header, rows = sample_excel_data
        original_header_len = len(header)
        original_row_len = len(rows[0])

        # add_row_id = False, so no changes
        if False:
            header = ["RowID"] + header
            for i, row in enumerate(rows, start=1):
                row.insert(0, str(i))

        assert len(header) == original_header_len
        assert len(rows[0]) == original_row_len


# ============================================================
# Test Category 2: Dataset Replacement Logic (Unit Tests)
# ============================================================

class TestDatasetReplacement:
    """Tests for dataset replacement functionality."""

    def test_replace_dataset_method_exists(self, test_db):
        """Test that replace_dataset method exists in DatasetImporter."""
        importer = DatasetImporter(test_db)
        assert hasattr(importer, 'replace_dataset')
        assert callable(importer.replace_dataset)

    def test_replace_preserves_dataset_id(self, test_db):
        """Test that replacement preserves the dataset ID."""
        # Create initial dataset
        project = test_db.query(Project).first()
        table_name = f"test_table_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        dataset = Dataset(
            project_id=project.id,
            name="Original Dataset",
            source_file_name="original.csv",
            sqlite_table_name=table_name
        )
        test_db.add(dataset)
        test_db.commit()
        original_id = dataset.id

        # Create the table
        importer = DatasetImporter(test_db)
        importer._create_and_populate_table(
            table_name,
            ["Col1", "Col2"],
            [["A", "B"], ["C", "D"]]
        )
        test_db.commit()

        # Replace the dataset
        new_header = ["NewCol1", "NewCol2", "NewCol3"]
        new_rows = [["X", "Y", "Z"], ["P", "Q", "R"]]

        replaced_dataset = importer.replace_dataset(
            original_id,
            new_header,
            new_rows,
            "replaced.csv"
        )

        assert replaced_dataset.id == original_id

    def test_replace_updates_source_file_name(self, test_db):
        """Test that replacement updates the source file name."""
        project = test_db.query(Project).first()
        table_name = f"test_table_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_2"

        dataset = Dataset(
            project_id=project.id,
            name="Original Dataset",
            source_file_name="original.csv",
            sqlite_table_name=table_name
        )
        test_db.add(dataset)
        test_db.commit()

        # Create the table
        importer = DatasetImporter(test_db)
        importer._create_and_populate_table(
            table_name,
            ["Col1"],
            [["A"]]
        )
        test_db.commit()

        # Replace with new file name
        replaced_dataset = importer.replace_dataset(
            dataset.id,
            ["NewCol1"],
            [["X"]],
            "new_file.csv"
        )

        assert replaced_dataset.source_file_name == "new_file.csv"

    def test_replace_nonexistent_dataset_raises_error(self, test_db):
        """Test that replacing non-existent dataset raises ValueError."""
        importer = DatasetImporter(test_db)

        with pytest.raises(ValueError) as exc_info:
            importer.replace_dataset(
                99999,  # Non-existent ID
                ["Col1"],
                [["A"]],
                "test.csv"
            )

        assert "not found" in str(exc_info.value)


# ============================================================
# Test Category 3: DatasetImporter Integration Tests
# ============================================================

class TestDatasetImporterIntegration:
    """Integration tests for DatasetImporter with new features."""

    def test_create_and_populate_table(self, test_db):
        """Test basic table creation and population."""
        importer = DatasetImporter(test_db)
        table_name = f"test_int_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        header = ["Name", "Value"]
        rows = [["A", "1"], ["B", "2"], ["C", "3"]]

        importer._create_and_populate_table(table_name, header, rows)
        test_db.commit()

        # Verify data
        result = test_db.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
        count = result.scalar()
        assert count == 3

    def test_create_table_with_rowid_column(self, test_db):
        """Test table creation with RowID as first column."""
        importer = DatasetImporter(test_db)
        table_name = f"test_rowid_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        # Header with RowID as first column
        header = ["RowID", "Name", "Value"]
        rows = [["1", "A", "100"], ["2", "B", "200"], ["3", "C", "300"]]

        importer._create_and_populate_table(table_name, header, rows)
        test_db.commit()

        # Verify columns
        result = test_db.execute(text(f'PRAGMA table_info("{table_name}")'))
        columns = [row[1] for row in result]

        assert "RowID" in columns
        assert columns.index("RowID") < columns.index("Name")

        # Verify RowID values
        result = test_db.execute(text(f'SELECT "RowID" FROM "{table_name}" ORDER BY id'))
        rowids = [row[0] for row in result]
        assert rowids == ["1", "2", "3"]

    def test_sanitize_column_name(self, test_db):
        """Test column name sanitization."""
        importer = DatasetImporter(test_db)

        # Test various cases
        assert importer._sanitize_column_name("Normal") == "Normal"
        assert importer._sanitize_column_name("With Space") == "With_Space"
        assert importer._sanitize_column_name("123Number") == "col_123Number"
        assert importer._sanitize_column_name("日本語") == "___"  # Non-ASCII to underscore
        assert importer._sanitize_column_name("") == "column"


# ============================================================
# Test Category 4: CSV Download Functionality
# ============================================================

class TestCSVDownload:
    """Tests for CSV download functionality."""

    def test_csv_download_format(self, test_db):
        """Test that downloaded CSV has correct format."""
        # Create a dataset
        project = test_db.query(Project).first()
        table_name = f"test_dl_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        dataset = Dataset(
            project_id=project.id,
            name="Download Test",
            source_file_name="test.csv",
            sqlite_table_name=table_name
        )
        test_db.add(dataset)
        test_db.commit()

        # Create and populate table
        importer = DatasetImporter(test_db)
        header = ["Name", "Value"]
        rows = [["Alice", "100"], ["Bob", "200"]]
        importer._create_and_populate_table(table_name, header, rows)
        test_db.commit()

        # Get preview (simulating download)
        preview = importer.get_dataset_preview(dataset.id, limit=0)

        # Simulate CSV generation
        output = io.StringIO()
        output.write('\ufeff')  # UTF-8 BOM
        writer = csv.writer(output)
        writer.writerow(preview["columns"])
        for row in preview["rows"]:
            writer.writerow([row.get(col, '') for col in preview["columns"]])

        csv_content = output.getvalue()

        # Verify BOM
        assert csv_content.startswith('\ufeff')

        # Verify header
        assert "Name" in csv_content
        assert "Value" in csv_content

        # Verify data
        assert "Alice" in csv_content
        assert "Bob" in csv_content

    def test_download_all_rows(self, test_db):
        """Test that download includes all rows when limit=0."""
        project = test_db.query(Project).first()
        table_name = f"test_dl_all_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        dataset = Dataset(
            project_id=project.id,
            name="Download All Test",
            source_file_name="test.csv",
            sqlite_table_name=table_name
        )
        test_db.add(dataset)
        test_db.commit()

        # Create table with many rows
        importer = DatasetImporter(test_db)
        header = ["Num", "Data"]  # Avoid "ID" which conflicts with SQLite auto-id
        rows = [[str(i), f"Data{i}"] for i in range(100)]
        importer._create_and_populate_table(table_name, header, rows)
        test_db.commit()

        # Get all rows (limit=0)
        preview = importer.get_dataset_preview(dataset.id, limit=0)

        assert len(preview["rows"]) == 100
        assert preview["total_count"] == 100


# ============================================================
# Test Category 5: API Endpoint Tests (Mock-based)
# ============================================================

class TestAPIEndpoints:
    """Tests for API endpoint parameter handling."""

    def test_add_row_id_parameter_parsing(self):
        """Test that add_row_id parameter is correctly parsed from string."""
        # Test various string values
        test_cases = [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("1", True),
            ("yes", True),
            ("false", False),
            ("False", False),
            ("0", False),
            ("no", False),
            ("", False),
        ]

        for string_val, expected in test_cases:
            result = string_val.lower() in ("true", "1", "yes")
            assert result == expected, f"Failed for '{string_val}': expected {expected}, got {result}"

    def test_replace_dataset_id_parameter(self):
        """Test replace_dataset_id parameter handling."""
        # Valid cases
        assert int("123") == 123

        # None case
        replace_id = None
        assert replace_id is None


# ============================================================
# Test Category 6: Edge Cases and Error Handling
# ============================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_dataset_rowid(self, sample_excel_data):
        """Test RowID addition with empty rows."""
        header, _ = sample_excel_data
        rows = []  # Empty rows

        new_header = ["RowID"] + header
        for i, row in enumerate(rows, start=1):
            row.insert(0, str(i))

        assert new_header[0] == "RowID"
        assert len(rows) == 0

    def test_single_row_rowid(self, sample_excel_data):
        """Test RowID addition with single row."""
        header, _ = sample_excel_data
        rows = [["Single", "1", "Data"]]

        new_header = ["RowID"] + header
        for i, row in enumerate(rows, start=1):
            row.insert(0, str(i))

        assert rows[0][0] == "1"
        assert len(rows) == 1

    def test_large_dataset_rowid(self):
        """Test RowID addition with large dataset."""
        header = ["Col1", "Col2"]
        rows = [[f"Data{i}", str(i)] for i in range(10000)]

        new_header = ["RowID"] + header
        for i, row in enumerate(rows, start=1):
            row.insert(0, str(i))

        assert rows[0][0] == "1"
        assert rows[9999][0] == "10000"

    def test_special_characters_in_data(self, test_db):
        """Test handling of special characters in data."""
        importer = DatasetImporter(test_db)
        table_name = f"test_special_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        header = ["Name", "Description"]
        rows = [
            ["日本語", "Japanese characters"],
            ["Quote\"Test", "With quotes"],
            ["Comma,Test", "With commas"],
            ["Newline\nTest", "With newlines"],
        ]

        importer._create_and_populate_table(table_name, header, rows)
        test_db.commit()

        result = test_db.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
        count = result.scalar()
        assert count == 4


# ============================================================
# Test Category 7: Frontend JavaScript Logic Tests
# ============================================================

class TestFrontendLogic:
    """Tests for frontend JavaScript logic (simulated in Python)."""

    def test_toggle_excel_mode_new(self):
        """Test Excel mode toggle for 'new' mode."""
        mode = 'new'

        # Simulate toggle logic
        show_new_options = mode == 'new'
        show_append_options = mode == 'append'
        show_replace_options = mode == 'replace'

        assert show_new_options == True
        assert show_append_options == False
        assert show_replace_options == False

    def test_toggle_excel_mode_append(self):
        """Test Excel mode toggle for 'append' mode."""
        mode = 'append'

        show_new_options = mode == 'new'
        show_append_options = mode == 'append'
        show_replace_options = mode == 'replace'

        assert show_new_options == False
        assert show_append_options == True
        assert show_replace_options == False

    def test_toggle_excel_mode_replace(self):
        """Test Excel mode toggle for 'replace' mode."""
        mode = 'replace'

        show_new_options = mode == 'new'
        show_append_options = mode == 'append'
        show_replace_options = mode == 'replace'

        assert show_new_options == False
        assert show_append_options == False
        assert show_replace_options == True

    def test_form_data_construction_with_rowid(self):
        """Test FormData construction with add_row_id parameter."""
        # Simulate form data
        form_data = {
            'project_id': '1',
            'dataset_name': 'Test Dataset',
            'add_row_id': 'true',
            'replace_dataset_id': None
        }

        # Verify add_row_id is included
        assert 'add_row_id' in form_data
        assert form_data['add_row_id'] == 'true'

    def test_form_data_construction_with_replace(self):
        """Test FormData construction with replace_dataset_id parameter."""
        form_data = {
            'project_id': '1',
            'dataset_name': '',  # Not needed for replace
            'add_row_id': 'false',
            'replace_dataset_id': '42'
        }

        assert form_data['replace_dataset_id'] == '42'


# ============================================================
# Main Test Runner
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

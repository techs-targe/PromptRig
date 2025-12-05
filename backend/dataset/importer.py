"""Excel dataset import functionality.

Based on specification in docs/req.txt section 4.6 (データセット)
"""

import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text
import openpyxl
from openpyxl.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from backend.database.models import Dataset


class DatasetImporter:
    """Importer for Excel datasets.

    Specification: docs/req.txt section 4.6.2
    """

    def __init__(self, db: Session):
        """Initialize importer with database session."""
        self.db = db

    def import_from_excel(
        self,
        project_id: int,
        file_path: str,
        dataset_name: str,
        range_name: str = "DSRange"
    ) -> Dataset:
        """Import dataset from Excel file.

        Args:
            project_id: Target project ID
            file_path: Path to Excel file
            dataset_name: Name for the dataset
            range_name: Named range in Excel (default: "DSRange")

        Returns:
            Created Dataset object

        Raises:
            ValueError: If file not found, range not found, or invalid data

        Specification: docs/req.txt section 4.6.2
        """
        # Load workbook
        if not os.path.exists(file_path):
            raise ValueError(f"File not found: {file_path}")

        try:
            workbook = openpyxl.load_workbook(file_path, data_only=True)
        except Exception as e:
            raise ValueError(f"Failed to load Excel file: {str(e)}")

        # Find named range
        if range_name not in workbook.defined_names:
            raise ValueError(f"Named range '{range_name}' not found in workbook")

        # Get data from named range
        data_rows = self._extract_data_from_range(workbook, range_name)

        if not data_rows:
            raise ValueError("No data found in named range")

        # Validate data structure
        if len(data_rows) < 2:
            raise ValueError("Dataset must have at least header row and one data row")

        header = data_rows[0]
        data_rows = data_rows[1:]

        # Create unique table name
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        table_name = f"Dataset_PJ{project_id}_{timestamp}"

        # Create dataset record
        dataset = Dataset(
            project_id=project_id,
            name=dataset_name,
            source_file_name=os.path.basename(file_path),
            sqlite_table_name=table_name
        )
        self.db.add(dataset)
        self.db.flush()

        # Create table and insert data
        self._create_and_populate_table(table_name, header, data_rows)

        self.db.commit()
        self.db.refresh(dataset)

        return dataset

    def _extract_data_from_range(
        self,
        workbook: Workbook,
        range_name: str
    ) -> List[List[Any]]:
        """Extract data from named range.

        Args:
            workbook: Openpyxl workbook
            range_name: Name of range to extract

        Returns:
            List of rows, each row is a list of cell values
        """
        # Get defined name
        defined_name = workbook.defined_names[range_name]

        # Get destinations (can be multiple for multi-sheet ranges)
        destinations = list(defined_name.destinations)

        if not destinations:
            return []

        # Use first destination
        sheet_name, cell_range = destinations[0]
        sheet = workbook[sheet_name]

        # Parse range
        rows = []
        for row in sheet[cell_range]:
            row_data = []
            for cell in row:
                value = cell.value
                # Convert None to empty string
                if value is None:
                    value = ""
                # Convert to string
                row_data.append(str(value))
            rows.append(row_data)

        return rows

    def _create_and_populate_table(
        self,
        table_name: str,
        header: List[str],
        data_rows: List[List[Any]]
    ):
        """Create SQLite table and populate with data.

        Args:
            table_name: Name of table to create
            header: Column names
            data_rows: List of data rows

        Specification: docs/req.txt section 4.6.3
        """
        # Sanitize column names
        columns = [self._sanitize_column_name(col) for col in header]

        # Create table SQL
        column_defs = ", ".join([f'"{col}" TEXT' for col in columns])
        create_sql = f"""
            CREATE TABLE IF NOT EXISTS "{table_name}" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {column_defs}
            )
        """

        self.db.execute(text(create_sql))

        # Insert data
        # Use named placeholders for SQLAlchemy text()
        placeholders = ", ".join([f":param{i}" for i in range(len(columns))])
        column_list = ", ".join([f'"{col}"' for col in columns])
        insert_sql = f'INSERT INTO "{table_name}" ({column_list}) VALUES ({placeholders})'

        for row in data_rows:
            # Pad or trim row to match column count
            row_data = row[:len(columns)]
            while len(row_data) < len(columns):
                row_data.append("")

            # Execute with named parameters as dict
            params = {f"param{i}": value for i, value in enumerate(row_data)}
            self.db.execute(text(insert_sql), params)

    def _sanitize_column_name(self, name: str) -> str:
        """Sanitize column name for SQL.

        Args:
            name: Original column name

        Returns:
            Sanitized name (alphanumeric + underscore)
        """
        # Replace spaces and special chars with underscore
        import re
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', str(name))
        # Ensure doesn't start with number
        if sanitized and sanitized[0].isdigit():
            sanitized = f"col_{sanitized}"
        return sanitized or "column"

    def get_dataset_preview(
        self,
        dataset_id: int,
        limit: int = 10
    ) -> Dict[str, Any]:
        """Get preview of dataset.

        Args:
            dataset_id: Dataset ID
            limit: Number of rows to preview

        Returns:
            Dictionary with columns and preview rows
        """
        dataset = self.db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            raise ValueError(f"Dataset {dataset_id} not found")

        table_name = dataset.sqlite_table_name

        # Get column names
        pragma_sql = f'PRAGMA table_info("{table_name}")'
        result = self.db.execute(text(pragma_sql))
        columns = [row[1] for row in result if row[1] != "id"]

        # Get preview data
        select_sql = f'SELECT * FROM "{table_name}" LIMIT {limit}'
        result = self.db.execute(text(select_sql))
        rows = [dict(row._mapping) for row in result]

        return {
            "dataset_id": dataset_id,
            "name": dataset.name,
            "columns": columns,
            "rows": rows,
            "total_count": self._get_row_count(table_name)
        }

    def _get_row_count(self, table_name: str) -> int:
        """Get total row count in dataset table."""
        count_sql = f'SELECT COUNT(*) FROM "{table_name}"'
        result = self.db.execute(text(count_sql))
        return result.scalar()


def import_excel_dataset(
    db: Session,
    project_id: int,
    file_path: str,
    dataset_name: str,
    range_name: str = "DSRange"
) -> Dataset:
    """Convenience function to import Excel dataset.

    Args:
        db: Database session
        project_id: Target project ID
        file_path: Path to Excel file
        dataset_name: Name for the dataset
        range_name: Named range in Excel (default: "DSRange")

    Returns:
        Created Dataset object

    Specification: docs/req.txt section 4.6.2
    """
    importer = DatasetImporter(db)
    return importer.import_from_excel(project_id, file_path, dataset_name, range_name)

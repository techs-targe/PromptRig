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
        range_name: str = "DSRange",
        add_row_id: bool = False,
        replace_dataset_id: Optional[int] = None
    ) -> Dataset:
        """Import dataset from Excel file.

        Args:
            project_id: Target project ID
            file_path: Path to Excel file
            dataset_name: Name for the dataset
            range_name: Named range in Excel (default: "DSRange")
            add_row_id: If True, add a RowID column as the first column (starting from 1)
            replace_dataset_id: If provided, replace the existing dataset (keep same ID)

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

        # Add RowID column if requested
        if add_row_id:
            header = ["RowID"] + header
            for i, row in enumerate(data_rows, start=1):
                row.insert(0, str(i))

        # Handle replace mode
        if replace_dataset_id:
            dataset = self.replace_dataset(replace_dataset_id, header, data_rows, os.path.basename(file_path))
        else:
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

    def replace_dataset(
        self,
        dataset_id: int,
        header: List[str],
        data_rows: List[List[Any]],
        source_file_name: Optional[str] = None
    ) -> Dataset:
        """Replace an existing dataset's data while keeping the same ID.

        Args:
            dataset_id: ID of the dataset to replace
            header: Column names for the new data
            data_rows: Data rows to insert
            source_file_name: Optional new source file name

        Returns:
            Updated Dataset object

        Raises:
            ValueError: If dataset not found
        """
        dataset = self.db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            raise ValueError(f"Dataset {dataset_id} not found")

        table_name = dataset.sqlite_table_name

        # Drop existing table
        drop_sql = f'DROP TABLE IF EXISTS "{table_name}"'
        self.db.execute(text(drop_sql))

        # Recreate table with new data
        self._create_and_populate_table(table_name, header, data_rows)

        # Update source file name if provided
        if source_file_name:
            dataset.source_file_name = source_file_name

        self.db.commit()
        self.db.refresh(dataset)

        return dataset

    def rename_columns(
        self,
        dataset_id: int,
        column_mapping: Dict[str, str]
    ) -> List[str]:
        """Rename columns in a dataset.

        Since SQLite doesn't support ALTER COLUMN RENAME, we need to:
        1. Get current table structure
        2. Create temporary table with new column names
        3. Copy data from old table
        4. Drop old table
        5. Rename temporary table

        Args:
            dataset_id: Dataset ID
            column_mapping: Dict mapping old column names to new names
                           e.g., {"old_name": "new_name", ...}

        Returns:
            List of new column names

        Raises:
            ValueError: If dataset not found or invalid column names
        """
        import re

        dataset = self.db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            raise ValueError(f"Dataset {dataset_id} not found")

        table_name = dataset.sqlite_table_name

        # 1. Get current columns
        pragma_sql = f'PRAGMA table_info("{table_name}")'
        result = self.db.execute(text(pragma_sql))
        current_columns = [row[1] for row in result if row[1] != "id"]

        if not current_columns:
            raise ValueError("No columns found in dataset")

        # 2. Build new column list
        new_columns = []
        for old_col in current_columns:
            if old_col in column_mapping:
                new_name = column_mapping[old_col]
                # Validate and sanitize new name
                new_name = self._sanitize_column_name(new_name)
                if not new_name:
                    raise ValueError(f"Invalid column name for '{old_col}'")
                new_columns.append((old_col, new_name))
            else:
                new_columns.append((old_col, old_col))

        # Check for duplicate new names
        new_names = [new for old, new in new_columns]
        if len(new_names) != len(set(new_names)):
            raise ValueError("Duplicate column names are not allowed")

        # 3. Create temporary table with new column names
        temp_table = f"{table_name}_rename_temp"

        # Drop temp table if exists (cleanup from previous failed attempt)
        self.db.execute(text(f'DROP TABLE IF EXISTS "{temp_table}"'))

        col_defs = ", ".join([f'"{new}" TEXT' for old, new in new_columns])
        create_sql = f'CREATE TABLE "{temp_table}" (id INTEGER PRIMARY KEY, {col_defs})'
        self.db.execute(text(create_sql))

        # 4. Copy data
        old_cols = ", ".join([f'"{old}"' for old, new in new_columns])
        new_cols = ", ".join([f'"{new}"' for old, new in new_columns])
        insert_sql = f'''
            INSERT INTO "{temp_table}" (id, {new_cols})
            SELECT id, {old_cols} FROM "{table_name}"
        '''
        self.db.execute(text(insert_sql))

        # 5. Swap tables
        self.db.execute(text(f'DROP TABLE "{table_name}"'))
        self.db.execute(text(f'ALTER TABLE "{temp_table}" RENAME TO "{table_name}"'))

        self.db.commit()

        return new_names

    def restructure_columns(
        self,
        dataset_id: int,
        new_column_list: List[str],
        column_renames: Dict[str, str] = None
    ) -> List[str]:
        """Restructure columns: add, delete, reorder, and rename in one operation.

        Since SQLite doesn't support full column operations, we need to:
        1. Get current table structure
        2. Build new column definitions based on new_column_list
        3. Create temporary table with new structure
        4. Copy data from old table (only columns that exist in both)
        5. Drop old table and rename temp table

        Args:
            dataset_id: Dataset ID
            new_column_list: Ordered list of final column names
                - Columns in this list but not in original: will be added (empty values)
                - Columns in original but not in this list: will be deleted
                - Order = order of this list
            column_renames: Optional dict mapping old names to new names
                e.g., {"old_name": "new_name"}

        Returns:
            List of new column names

        Raises:
            ValueError: If dataset not found or invalid column names
        """
        dataset = self.db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            raise ValueError(f"Dataset {dataset_id} not found")

        table_name = dataset.sqlite_table_name
        column_renames = column_renames or {}

        # 1. Get current columns
        pragma_sql = f'PRAGMA table_info("{table_name}")'
        result = self.db.execute(text(pragma_sql))
        current_columns = [row[1] for row in result if row[1] != "id"]

        if not new_column_list:
            raise ValueError("At least one column is required")

        # 2. Sanitize new column names
        sanitized_columns = []
        for col in new_column_list:
            sanitized = self._sanitize_column_name(col)
            if not sanitized:
                raise ValueError(f"Invalid column name: '{col}'")
            sanitized_columns.append(sanitized)

        # Check for duplicate names
        if len(sanitized_columns) != len(set(sanitized_columns)):
            raise ValueError("Duplicate column names are not allowed")

        # 3. Build column mapping: new_col -> old_col (for data copying)
        # Apply renames: old_name -> new_name
        reverse_renames = {v: k for k, v in column_renames.items()}

        # For each new column, find the source column
        column_sources = []  # [(new_col, old_col or None)]
        for new_col in sanitized_columns:
            # Check if this is a renamed column
            if new_col in reverse_renames:
                old_col = reverse_renames[new_col]
                if old_col in current_columns:
                    column_sources.append((new_col, old_col))
                else:
                    column_sources.append((new_col, None))  # Source doesn't exist
            elif new_col in current_columns:
                column_sources.append((new_col, new_col))
            else:
                column_sources.append((new_col, None))  # New column

        # 4. Create temporary table with new column definitions
        temp_table = f"{table_name}_restructure_temp"

        # Drop temp table if exists (cleanup from previous failed attempt)
        self.db.execute(text(f'DROP TABLE IF EXISTS "{temp_table}"'))

        col_defs = ", ".join([f'"{new_col}" TEXT' for new_col, _ in column_sources])
        create_sql = f'CREATE TABLE "{temp_table}" (id INTEGER PRIMARY KEY, {col_defs})'
        self.db.execute(text(create_sql))

        # 5. Copy data
        # Build INSERT INTO ... SELECT query
        # For new columns (no source), use empty string
        select_parts = []
        for new_col, old_col in column_sources:
            if old_col:
                select_parts.append(f'"{old_col}"')
            else:
                select_parts.append("''")  # Empty string for new columns

        new_cols = ", ".join([f'"{new_col}"' for new_col, _ in column_sources])
        select_cols = ", ".join(select_parts)

        insert_sql = f'''
            INSERT INTO "{temp_table}" (id, {new_cols})
            SELECT id, {select_cols} FROM "{table_name}"
        '''
        self.db.execute(text(insert_sql))

        # 6. Swap tables
        self.db.execute(text(f'DROP TABLE "{table_name}"'))
        self.db.execute(text(f'ALTER TABLE "{temp_table}" RENAME TO "{table_name}"'))

        self.db.commit()

        return sanitized_columns

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

        # Get preview data (limit=0 means no limit, show all)
        if limit > 0:
            select_sql = f'SELECT * FROM "{table_name}" LIMIT {limit}'
        else:
            select_sql = f'SELECT * FROM "{table_name}"'
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

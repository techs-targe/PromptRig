"""Hugging Face dataset import functionality.

Provides functionality to search, preview, and import datasets from Hugging Face Hub.
"""

import os
import re
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.database.models import Dataset

logger = logging.getLogger(__name__)


@dataclass
class DatasetInfo:
    """Information about a Hugging Face dataset."""
    name: str
    description: str
    splits: List[str]
    features: Dict[str, str]
    size_info: Dict[str, Dict[str, Any]]
    is_gated: bool
    requires_auth: bool
    warning: Optional[str] = None


class HuggingFaceImporter:
    """Importer for Hugging Face datasets.

    Supports searching, previewing, and importing datasets from Hugging Face Hub.
    Uses streaming mode for memory-efficient handling of large datasets.
    """

    def __init__(self, db: Session, hf_token: Optional[str] = None):
        """Initialize importer with database session.

        Args:
            db: SQLAlchemy database session
            hf_token: Optional Hugging Face token for accessing gated datasets
        """
        self.db = db
        self.hf_token = hf_token or os.environ.get("HF_TOKEN")

    def search_datasets(
        self,
        query: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Search for datasets on Hugging Face Hub by keyword.

        Args:
            query: Search keyword (e.g., "question answering", "sentiment")
            limit: Maximum number of results to return (default 20, max 100)

        Returns:
            List of dataset info dictionaries with name, description, downloads, etc.
        """
        try:
            from huggingface_hub import list_datasets
        except ImportError as e:
            raise ValueError(f"Required packages not installed: {e}")

        # Cap limit at 100
        limit = min(limit, 100)

        try:
            results = []
            # Search datasets using HF Hub API
            datasets_iter = list_datasets(
                search=query,
                limit=limit,
                token=self.hf_token
            )

            for ds in datasets_iter:
                # Extract basic info
                result = {
                    "id": ds.id,  # Full dataset ID (e.g., "username/dataset-name")
                    "name": ds.id.split("/")[-1] if "/" in ds.id else ds.id,
                    "author": ds.author if hasattr(ds, 'author') and ds.author else (ds.id.split("/")[0] if "/" in ds.id else ""),
                    "description": "",
                    "downloads": ds.downloads if hasattr(ds, 'downloads') else 0,
                    "likes": ds.likes if hasattr(ds, 'likes') else 0,
                    "tags": ds.tags if hasattr(ds, 'tags') else [],
                    "is_gated": ds.gated is not None and ds.gated != False if hasattr(ds, 'gated') else False,
                    "last_modified": ds.last_modified.isoformat() if hasattr(ds, 'last_modified') and ds.last_modified else None
                }

                # Try to get description from card_data
                if hasattr(ds, 'card_data') and ds.card_data:
                    if hasattr(ds.card_data, 'description'):
                        result["description"] = ds.card_data.description or ""

                results.append(result)

            logger.info(f"Found {len(results)} datasets for query: {query}")
            return results

        except Exception as e:
            logger.error(f"Error searching datasets for '{query}': {e}")
            raise ValueError(f"Failed to search datasets: {str(e)}")

    def get_dataset_info(self, dataset_name: str) -> DatasetInfo:
        """Get dataset information without downloading the data.

        Args:
            dataset_name: Hugging Face dataset name (e.g., "squad", "imdb", "user/dataset")

        Returns:
            DatasetInfo with metadata about the dataset

        Raises:
            ValueError: If dataset not found or access denied
        """
        try:
            from datasets import load_dataset_builder
            from huggingface_hub import dataset_info as hf_dataset_info
            from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError
        except ImportError as e:
            raise ValueError(f"Required packages not installed: {e}")

        try:
            # Get dataset info from Hub API
            try:
                hub_info = hf_dataset_info(dataset_name, token=self.hf_token)
                is_gated = hub_info.gated is not None and hub_info.gated != False
                description = hub_info.description or ""
            except Exception:
                is_gated = False
                description = ""

            # Get dataset builder for splits and features
            builder = load_dataset_builder(dataset_name, token=self.hf_token)

            # Extract splits
            splits = list(builder.info.splits.keys()) if builder.info.splits else []

            # Extract features as simplified type strings
            features = {}
            if builder.info.features:
                for name, feature in builder.info.features.items():
                    features[name] = self._feature_to_type_string(feature)

            # Extract size info
            size_info = {}
            if builder.info.splits:
                for split_name, split_info in builder.info.splits.items():
                    size_info[split_name] = {
                        "num_rows": split_info.num_examples,
                        "size_bytes": split_info.num_bytes
                    }

            # Check for large dataset warning
            warning = None
            total_rows = sum(s.get("num_rows", 0) or 0 for s in size_info.values())
            if total_rows > 100000:
                warning = f"Large dataset ({total_rows:,} rows). Consider using row_limit."

            return DatasetInfo(
                name=dataset_name,
                description=description[:500] if description else "",
                splits=splits,
                features=features,
                size_info=size_info,
                is_gated=is_gated,
                requires_auth=is_gated and not self.hf_token,
                warning=warning
            )

        except RepositoryNotFoundError:
            raise ValueError(f"Dataset '{dataset_name}' not found on Hugging Face Hub")
        except GatedRepoError:
            raise ValueError(
                f"Dataset '{dataset_name}' requires authentication. "
                "Please set HF_TOKEN environment variable."
            )
        except Exception as e:
            logger.error(f"Error getting dataset info for {dataset_name}: {e}")
            raise ValueError(f"Failed to get dataset info: {str(e)}")

    def _feature_to_type_string(self, feature) -> str:
        """Convert a datasets Feature to a simple type string."""
        type_name = type(feature).__name__

        if type_name == "Value":
            return feature.dtype
        elif type_name == "ClassLabel":
            return f"class[{feature.num_classes}]"
        elif type_name == "Sequence":
            inner = self._feature_to_type_string(feature.feature)
            return f"list[{inner}]"
        elif type_name == "dict":
            return "dict"
        elif type_name in ("Image", "Audio"):
            return type_name.lower()
        else:
            return "complex"

    def get_preview(
        self,
        dataset_name: str,
        split: str,
        limit: int = 10
    ) -> Dict[str, Any]:
        """Get a preview of dataset rows using streaming.

        Args:
            dataset_name: Hugging Face dataset name
            split: Dataset split (e.g., "train", "validation")
            limit: Maximum number of rows to preview

        Returns:
            Dictionary with columns, rows, and total_count
        """
        try:
            from datasets import load_dataset
        except ImportError as e:
            raise ValueError(f"Required packages not installed: {e}")

        try:
            # Load dataset in streaming mode for efficiency
            ds = load_dataset(
                dataset_name,
                split=split,
                streaming=True,
                token=self.hf_token
            )

            # Get column names from features
            columns = list(ds.features.keys()) if hasattr(ds, 'features') else []

            # Collect preview rows
            rows = []
            for i, example in enumerate(ds):
                if i >= limit:
                    break
                # Convert complex values to JSON strings for display
                row = {}
                for col in columns:
                    value = example.get(col)
                    if isinstance(value, (dict, list)):
                        row[col] = json.dumps(value, ensure_ascii=False)
                    else:
                        row[col] = str(value) if value is not None else ""
                rows.append(row)

            # Get total count from dataset info
            info = self.get_dataset_info(dataset_name)
            total_count = info.size_info.get(split, {}).get("num_rows", 0) or 0

            return {
                "name": dataset_name,
                "split": split,
                "columns": columns,
                "rows": rows,
                "total_count": total_count
            }

        except Exception as e:
            logger.error(f"Error previewing dataset {dataset_name}/{split}: {e}")
            raise ValueError(f"Failed to preview dataset: {str(e)}")

    def import_dataset(
        self,
        project_id: int,
        dataset_name: str,
        split: str,
        display_name: str,
        row_limit: Optional[int] = None,
        columns: Optional[List[str]] = None,
        add_row_id: bool = False
    ) -> Dataset:
        """Import a Hugging Face dataset into SQLite.

        Args:
            project_id: Target project ID
            dataset_name: Hugging Face dataset name
            split: Dataset split to import
            display_name: Display name for the dataset
            row_limit: Maximum rows to import (None for all)
            columns: Columns to import (None for all)
            add_row_id: If True, add a RowID column as the first column (starting from 1)

        Returns:
            Created Dataset object

        Raises:
            ValueError: If import fails
        """
        try:
            from datasets import load_dataset
        except ImportError as e:
            raise ValueError(f"Required packages not installed: {e}")

        logger.info(f"Starting import of {dataset_name}/{split} for project {project_id}")

        try:
            # Load dataset in streaming mode
            ds = load_dataset(
                dataset_name,
                split=split,
                streaming=True,
                token=self.hf_token
            )

            # Get all columns or filter
            all_columns = list(ds.features.keys()) if hasattr(ds, 'features') else []
            if columns:
                selected_columns = [c for c in columns if c in all_columns]
                if not selected_columns:
                    raise ValueError(f"No valid columns specified. Available: {all_columns}")
            else:
                selected_columns = all_columns

            # Create unique table name
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_name = re.sub(r'[^a-zA-Z0-9]', '_', dataset_name)[:30]
            table_name = f"HF_{safe_name}_{split}_{timestamp}"

            # Create dataset record
            source_file = f"huggingface://{dataset_name}/{split}"
            dataset = Dataset(
                project_id=project_id,
                name=display_name,
                source_file_name=source_file,
                sqlite_table_name=table_name
            )
            self.db.add(dataset)
            self.db.flush()

            # Create table (with RowID if requested)
            sanitized_columns = [self._sanitize_column_name(col) for col in selected_columns]
            if add_row_id:
                sanitized_columns = ["RowID"] + sanitized_columns
            column_defs = ", ".join([f'"{col}" TEXT' for col in sanitized_columns])
            create_sql = f'''
                CREATE TABLE IF NOT EXISTS "{table_name}" (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    {column_defs}
                )
            '''
            self.db.execute(text(create_sql))

            # Prepare insert statement
            placeholders = ", ".join([f":param{i}" for i in range(len(sanitized_columns))])
            column_list = ", ".join([f'"{col}"' for col in sanitized_columns])
            insert_sql = f'INSERT INTO "{table_name}" ({column_list}) VALUES ({placeholders})'

            # Import data row by row
            row_count = 0
            for example in ds:
                if row_limit and row_count >= row_limit:
                    break

                # Build row data
                params = {}
                param_offset = 0

                # Add RowID if requested
                if add_row_id:
                    params["param0"] = str(row_count + 1)
                    param_offset = 1

                for i, col in enumerate(selected_columns):
                    value = example.get(col)
                    if isinstance(value, (dict, list)):
                        params[f"param{i + param_offset}"] = json.dumps(value, ensure_ascii=False)
                    elif value is not None:
                        params[f"param{i + param_offset}"] = str(value)
                    else:
                        params[f"param{i + param_offset}"] = ""

                self.db.execute(text(insert_sql), params)
                row_count += 1

                # Log progress for large imports
                if row_count % 1000 == 0:
                    logger.info(f"Imported {row_count} rows...")

            self.db.commit()
            self.db.refresh(dataset)

            logger.info(f"Successfully imported {row_count} rows into {table_name}")

            return dataset

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error importing dataset {dataset_name}/{split}: {e}")
            raise ValueError(f"Failed to import dataset: {str(e)}")

    def _sanitize_column_name(self, name: str) -> str:
        """Sanitize column name for SQL.

        Args:
            name: Original column name

        Returns:
            Sanitized name (alphanumeric + underscore)
        """
        # Handle empty/whitespace-only names
        if not name or not name.strip():
            return "column"

        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', str(name))

        # Remove leading/trailing underscores and collapse multiple underscores
        sanitized = re.sub(r'_+', '_', sanitized).strip('_')

        # If result is empty after sanitization, return default
        if not sanitized:
            return "column"

        if sanitized[0].isdigit():
            sanitized = f"col_{sanitized}"
        # Avoid conflict with auto-increment id column
        if sanitized.lower() == "id":
            sanitized = "hf_id"
        return sanitized

    def get_row_count(self, table_name: str) -> int:
        """Get total row count in dataset table."""
        count_sql = f'SELECT COUNT(*) FROM "{table_name}"'
        result = self.db.execute(text(count_sql))
        return result.scalar()

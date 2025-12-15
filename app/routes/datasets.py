"""Dataset management API endpoints.

Based on specification in docs/req.txt section 4.6 (データセット)
Phase 2 implementation.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from datetime import datetime
import os
import tempfile
import csv
import io
import json

from backend.database import get_db, Dataset, Job, JobItem
from backend.dataset import DatasetImporter

router = APIRouter()


class DatasetResponse(BaseModel):
    """Dataset response model."""
    id: int
    project_id: int
    name: str
    source_file_name: str
    sqlite_table_name: str
    created_at: str
    row_count: int = 0


class DatasetPreviewResponse(BaseModel):
    """Dataset preview response model."""
    dataset_id: int
    name: str
    columns: List[str]
    rows: List[Dict[str, Any]]
    total_count: int


@router.get("/api/datasets", response_model=List[DatasetResponse])
def list_datasets(project_id: int = None, db: Session = Depends(get_db)):
    """List datasets, optionally filtered by project.

    Specification: docs/req.txt section 4.6.1
    Phase 2
    """
    query = db.query(Dataset)
    if project_id:
        query = query.filter(Dataset.project_id == project_id)

    datasets = query.order_by(Dataset.created_at.desc()).all()

    result = []
    for dataset in datasets:
        # Get row count from importer
        importer = DatasetImporter(db)
        row_count = importer._get_row_count(dataset.sqlite_table_name)

        result.append(DatasetResponse(
            id=dataset.id,
            project_id=dataset.project_id,
            name=dataset.name,
            source_file_name=dataset.source_file_name,
            sqlite_table_name=dataset.sqlite_table_name,
            created_at=dataset.created_at,
            row_count=row_count
        ))

    return result


@router.post("/api/datasets/import", response_model=DatasetResponse)
async def import_dataset(
    project_id: int = Form(...),
    dataset_name: str = Form(...),
    range_name: str = Form("DSRange"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Import dataset from Excel file.

    Specification: docs/req.txt section 4.6.2
    Phase 2
    """
    # Validate file type
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(
            status_code=400,
            detail="Only Excel files (.xlsx, .xls) are supported"
        )

    # Save uploaded file to temporary location
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
        content = await file.read()
        tmp_file.write(content)
        tmp_file_path = tmp_file.name

    try:
        # Import dataset
        importer = DatasetImporter(db)
        dataset = importer.import_from_excel(
            project_id=project_id,
            file_path=tmp_file_path,
            dataset_name=dataset_name,
            range_name=range_name
        )

        # Get row count
        row_count = importer._get_row_count(dataset.sqlite_table_name)

        return DatasetResponse(
            id=dataset.id,
            project_id=dataset.project_id,
            name=dataset.name,
            source_file_name=dataset.source_file_name,
            sqlite_table_name=dataset.sqlite_table_name,
            created_at=dataset.created_at,
            row_count=row_count
        )

    except HTTPException:
        raise  # Re-raise HTTPException as-is
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")
    finally:
        # Clean up temporary file
        if os.path.exists(tmp_file_path):
            os.unlink(tmp_file_path)


@router.get("/api/datasets/{dataset_id}", response_model=DatasetResponse)
def get_dataset(dataset_id: int, db: Session = Depends(get_db)):
    """Get dataset details.

    Specification: docs/req.txt section 4.6
    Phase 2
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    importer = DatasetImporter(db)
    row_count = importer._get_row_count(dataset.sqlite_table_name)

    return DatasetResponse(
        id=dataset.id,
        project_id=dataset.project_id,
        name=dataset.name,
        source_file_name=dataset.source_file_name,
        sqlite_table_name=dataset.sqlite_table_name,
        created_at=dataset.created_at,
        row_count=row_count
    )


@router.get("/api/datasets/{dataset_id}/preview", response_model=DatasetPreviewResponse)
def preview_dataset(
    dataset_id: int,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Get preview of dataset.

    Specification: docs/req.txt section 4.6 (implied)
    Phase 2
    """
    try:
        importer = DatasetImporter(db)
        preview = importer.get_dataset_preview(dataset_id, limit)

        return DatasetPreviewResponse(**preview)

    except HTTPException:
        raise  # Re-raise HTTPException as-is
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preview failed: {str(e)}")


@router.delete("/api/datasets/{dataset_id}")
def delete_dataset(dataset_id: int, db: Session = Depends(get_db)):
    """Delete dataset.

    Specification: docs/req.txt section 4.6.1
    Phase 2
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Drop the SQLite table
    from sqlalchemy import text
    try:
        db.execute(text(f'DROP TABLE IF EXISTS "{dataset.sqlite_table_name}"'))
    except Exception:
        pass  # Continue even if table drop fails

    # Delete dataset record
    db.delete(dataset)
    db.commit()

    return {"success": True, "message": f"Dataset {dataset_id} deleted"}


# ========== Extended Import Endpoints ==========

class ImportFromJobRequest(BaseModel):
    """Request model for importing from job results."""
    job_id: int
    project_id: int
    dataset_name: Optional[str] = None
    target_dataset_id: Optional[int] = None


@router.post("/api/datasets/import/append", response_model=DatasetResponse)
async def append_excel_to_dataset(
    target_dataset_id: int = Form(...),
    range_name: str = Form("DSRange"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Append data from Excel file to existing dataset."""
    # Validate file type
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(
            status_code=400,
            detail="Only Excel files (.xlsx, .xls) are supported"
        )

    # Get target dataset
    dataset = db.query(Dataset).filter(Dataset.id == target_dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Target dataset not found")

    # Save uploaded file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
        content = await file.read()
        tmp_file.write(content)
        tmp_file_path = tmp_file.name

    try:
        importer = DatasetImporter(db)

        # Extract data from Excel
        import openpyxl
        workbook = openpyxl.load_workbook(tmp_file_path, data_only=True)

        if range_name not in workbook.defined_names:
            raise HTTPException(status_code=400, detail=f"Named range '{range_name}' not found in workbook")

        data_rows = importer._extract_data_from_range(workbook, range_name)
        if not data_rows or len(data_rows) < 2:
            raise HTTPException(status_code=400, detail="No data found in named range")

        header = data_rows[0]
        data_rows = data_rows[1:]

        # Get existing columns
        pragma_sql = f'PRAGMA table_info("{dataset.sqlite_table_name}")'
        result = db.execute(text(pragma_sql))
        existing_columns = [row[1] for row in result if row[1] != "id"]

        # Sanitize and map columns
        columns = [importer._sanitize_column_name(col) for col in header]

        # Insert data
        for row in data_rows:
            row_data = row[:len(columns)]
            while len(row_data) < len(columns):
                row_data.append("")

            # Build insert for existing columns only
            insert_cols = []
            insert_vals = {}
            for i, col in enumerate(columns):
                if col in existing_columns:
                    insert_cols.append(col)
                    insert_vals[f"param{i}"] = row_data[i]

            if insert_cols:
                placeholders = ", ".join([f":param{i}" for i, col in enumerate(columns) if col in existing_columns])
                column_list = ", ".join([f'"{col}"' for col in insert_cols])
                insert_sql = f'INSERT INTO "{dataset.sqlite_table_name}" ({column_list}) VALUES ({placeholders})'
                db.execute(text(insert_sql), insert_vals)

        db.commit()

        row_count = importer._get_row_count(dataset.sqlite_table_name)

        return DatasetResponse(
            id=dataset.id,
            project_id=dataset.project_id,
            name=dataset.name,
            source_file_name=dataset.source_file_name,
            sqlite_table_name=dataset.sqlite_table_name,
            created_at=dataset.created_at,
            row_count=row_count
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Append failed: {str(e)}")
    finally:
        if os.path.exists(tmp_file_path):
            os.unlink(tmp_file_path)


@router.post("/api/datasets/import/csv", response_model=DatasetResponse)
async def import_csv_dataset(
    project_id: int = Form(...),
    encoding: str = Form("utf-8"),
    delimiter: str = Form(","),
    quotechar: str = Form('"'),
    has_header: str = Form("1"),
    dataset_name: Optional[str] = Form(None),
    target_dataset_id: Optional[int] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Import dataset from CSV file."""
    # Validate inputs
    if not dataset_name and not target_dataset_id:
        raise HTTPException(status_code=400, detail="Either dataset_name or target_dataset_id is required")

    # Read file content
    content = await file.read()

    # Decode with specified encoding
    try:
        text_content = content.decode(encoding)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to decode file with encoding {encoding}: {str(e)}")

    # Parse CSV
    try:
        reader = csv.reader(
            io.StringIO(text_content),
            delimiter=delimiter,
            quotechar=quotechar if quotechar else '"'
        )
        rows = list(reader)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {str(e)}")

    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty")

    # Handle header
    if has_header == "1":
        header = rows[0]
        data_rows = rows[1:]
    else:
        # Generate column names
        col_count = len(rows[0]) if rows else 0
        header = [f"col_{i+1}" for i in range(col_count)]
        data_rows = rows

    if not data_rows:
        raise HTTPException(status_code=400, detail="No data rows found")

    importer = DatasetImporter(db)

    try:
        if target_dataset_id:
            # Append to existing dataset
            dataset = db.query(Dataset).filter(Dataset.id == target_dataset_id).first()
            if not dataset:
                raise HTTPException(status_code=404, detail="Target dataset not found")

            # Get existing columns
            pragma_sql = f'PRAGMA table_info("{dataset.sqlite_table_name}")'
            result = db.execute(text(pragma_sql))
            existing_columns = [row[1] for row in result if row[1] != "id"]

            # Sanitize columns
            columns = [importer._sanitize_column_name(col) for col in header]

            # Insert data
            for row in data_rows:
                row_data = row[:len(columns)]
                while len(row_data) < len(columns):
                    row_data.append("")

                insert_cols = []
                insert_vals = {}
                for i, col in enumerate(columns):
                    if col in existing_columns:
                        insert_cols.append(col)
                        insert_vals[f"param{i}"] = row_data[i]

                if insert_cols:
                    placeholders = ", ".join([f":param{i}" for i, col in enumerate(columns) if col in existing_columns])
                    column_list = ", ".join([f'"{col}"' for col in insert_cols])
                    insert_sql = f'INSERT INTO "{dataset.sqlite_table_name}" ({column_list}) VALUES ({placeholders})'
                    db.execute(text(insert_sql), insert_vals)

            db.commit()

        else:
            # Create new dataset
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            table_name = f"Dataset_PJ{project_id}_{timestamp}"

            dataset = Dataset(
                project_id=project_id,
                name=dataset_name,
                source_file_name=file.filename or "import.csv",
                sqlite_table_name=table_name
            )
            db.add(dataset)
            db.flush()

            # Create table and insert data
            importer._create_and_populate_table(table_name, header, data_rows)
            db.commit()
            db.refresh(dataset)

        row_count = importer._get_row_count(dataset.sqlite_table_name)

        return DatasetResponse(
            id=dataset.id,
            project_id=dataset.project_id,
            name=dataset.name,
            source_file_name=dataset.source_file_name,
            sqlite_table_name=dataset.sqlite_table_name,
            created_at=dataset.created_at,
            row_count=row_count
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


@router.post("/api/datasets/import/from-job", response_model=DatasetResponse)
async def import_from_job(
    request: ImportFromJobRequest,
    db: Session = Depends(get_db)
):
    """Import dataset from job execution results.

    IMPORTANT: Header and data order consistency
    - First try job.merged_csv_output (most reliable)
    - If csv_header exists: use csv_header + csv_output (same source, safe)
    - If csv_header missing: regenerate BOTH from fields (ignore csv_output)
    """
    # Get job
    job = db.query(Job).filter(Job.id == request.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    all_rows = []
    header = None

    # First, try to use job.merged_csv_output if available (most reliable)
    if job.merged_csv_output:
        lines = [line.strip() for line in job.merged_csv_output.strip().split("\n") if line.strip()]
        if lines:
            # First line is header
            header = lines[0].split(",")
            # Remaining lines are data
            for line in lines[1:]:
                try:
                    reader = csv.reader(io.StringIO(line))
                    row = next(reader)
                    all_rows.append(row)
                except:
                    all_rows.append([line])
    else:
        # Fall back to building from job_items
        job_items = db.query(JobItem).filter(
            JobItem.job_id == request.job_id,
            JobItem.status == "done"
        ).all()

        if not job_items:
            raise HTTPException(status_code=400, detail="No completed job items found")

        for item in job_items:
            if not item.parsed_response:
                continue

            try:
                parsed = json.loads(item.parsed_response)
            except:
                continue

            csv_output = parsed.get("csv_output", "")
            csv_header = parsed.get("csv_header", "")
            fields = parsed.get("fields", {})

            # SAFETY: Ensure header and data come from the same source
            if csv_header:
                # csv_header exists: use csv_header + csv_output (same source, order matches)
                if header is None:
                    header = csv_header.split(",")
                if csv_output:
                    for line in csv_output.strip().split("\n"):
                        if line.strip():
                            try:
                                reader = csv.reader(io.StringIO(line))
                                row = next(reader)
                                all_rows.append(row)
                            except:
                                all_rows.append([line])
            elif fields:
                # csv_header missing: generate BOTH from fields (ignore csv_output)
                if header is None:
                    header = list(fields.keys())
                # Always use fields.values() in the order of header keys
                row = [str(fields.get(h, "")) for h in header]
                all_rows.append(row)

    if not all_rows:
        raise HTTPException(status_code=400, detail="No CSV data found in job results")

    # Generate header if not found (last resort)
    if header is None:
        col_count = len(all_rows[0]) if all_rows else 1
        header = [f"col_{i+1}" for i in range(col_count)]

    importer = DatasetImporter(db)

    try:
        if request.target_dataset_id:
            # Append to existing
            dataset = db.query(Dataset).filter(Dataset.id == request.target_dataset_id).first()
            if not dataset:
                raise HTTPException(status_code=404, detail="Target dataset not found")

            # Get existing columns
            pragma_sql = f'PRAGMA table_info("{dataset.sqlite_table_name}")'
            result = db.execute(text(pragma_sql))
            existing_columns = [row[1] for row in result if row[1] != "id"]

            columns = [importer._sanitize_column_name(col) for col in header]

            for row in all_rows:
                row_data = row[:len(columns)]
                while len(row_data) < len(columns):
                    row_data.append("")

                insert_cols = []
                insert_vals = {}
                for i, col in enumerate(columns):
                    if col in existing_columns:
                        insert_cols.append(col)
                        insert_vals[f"param{i}"] = row_data[i]

                if insert_cols:
                    placeholders = ", ".join([f":param{i}" for i, col in enumerate(columns) if col in existing_columns])
                    column_list = ", ".join([f'"{col}"' for col in insert_cols])
                    insert_sql = f'INSERT INTO "{dataset.sqlite_table_name}" ({column_list}) VALUES ({placeholders})'
                    db.execute(text(insert_sql), insert_vals)

            db.commit()

        else:
            # Create new
            if not request.dataset_name:
                raise HTTPException(status_code=400, detail="dataset_name is required for new dataset")

            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            table_name = f"Dataset_PJ{request.project_id}_{timestamp}"

            dataset = Dataset(
                project_id=request.project_id,
                name=request.dataset_name,
                source_file_name=f"job_{request.job_id}_results",
                sqlite_table_name=table_name
            )
            db.add(dataset)
            db.flush()

            importer._create_and_populate_table(table_name, header, all_rows)
            db.commit()
            db.refresh(dataset)

        row_count = importer._get_row_count(dataset.sqlite_table_name)

        return DatasetResponse(
            id=dataset.id,
            project_id=dataset.project_id,
            name=dataset.name,
            source_file_name=dataset.source_file_name,
            sqlite_table_name=dataset.sqlite_table_name,
            created_at=dataset.created_at,
            row_count=row_count
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")

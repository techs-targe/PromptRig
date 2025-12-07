"""Dataset management API endpoints.

Based on specification in docs/req.txt section 4.6 (データセット)
Phase 2 implementation.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from pydantic import BaseModel
import os
import tempfile

from backend.database import get_db, Dataset
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

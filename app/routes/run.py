"""Execution API endpoints.

Based on specification in docs/req.txt section 3.2, 3.3, 4.2.3, 4.3
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any

from backend.database import get_db, ProjectRevision, JobItem
from backend.job import JobManager
from app.schemas.requests import RunSingleRequest
from app.schemas.responses import RunSingleResponse, JobResponse, JobItemResponse

router = APIRouter()


class RunBatchRequest(BaseModel):
    """Request body for POST /api/run/batch.

    Specification: docs/req.txt section 3.3 (バッチ実行通信フロー)
    Phase 2
    """
    project_id: int
    dataset_id: int
    model_name: str = None


@router.post("/api/run/single", response_model=RunSingleResponse)
def run_single(request: RunSingleRequest, db: Session = Depends(get_db)):
    """Execute single/repeated prompt execution.

    Phase 2 update:
    - Supports multiple projects via project_id in request
    - Uses latest revision for specified project
    - Executes synchronously
    - Repeat count limited to 1-10

    Specification: docs/req.txt section 3.2 (通信フロー step 4-6), 4.2.3
    """
    try:
        # Get latest project revision for specified project
        revision = db.query(ProjectRevision).filter(
            ProjectRevision.project_id == request.project_id
        ).order_by(ProjectRevision.revision.desc()).first()

        if not revision:
            raise HTTPException(
                status_code=404,
                detail="Project revision not found. Please run database initialization."
            )

        # Create job manager
        job_manager = JobManager(db)

        # Create job with job items
        job = job_manager.create_single_job(
            project_revision_id=revision.id,
            input_params=request.input_params,
            repeat=request.repeat
        )

        # Execute job
        job = job_manager.execute_job(
            job_id=job.id,
            model_name=request.model_name,
            include_csv_header=request.include_csv_header,
            temperature=request.temperature
        )

        # Load job items for response
        job_items = db.query(JobItem).filter(JobItem.job_id == job.id).all()
        items = [
            JobItemResponse(
                id=item.id,
                created_at=item.created_at,
                input_params=item.input_params,
                raw_prompt=item.raw_prompt,
                raw_response=item.raw_response,
                parsed_response=item.parsed_response,
                status=item.status,
                error_message=item.error_message,
                turnaround_ms=item.turnaround_ms
            )
            for item in job_items
        ]

        job_response = JobResponse(
            id=job.id,
            job_type=job.job_type,
            status=job.status,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            turnaround_ms=job.turnaround_ms,
            merged_csv_output=job.merged_csv_output,
            items=items
        )

        return RunSingleResponse(
            success=True,
            job_id=job.id,
            job=job_response,
            message=f"Successfully executed {len(items)} item(s)"
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


class RunBatchRequestWithHeader(BaseModel):
    """Request body for batch with CSV header option."""
    project_id: int
    dataset_id: int
    model_name: str = None
    include_csv_header: bool = True  # Include header for 1st row
    temperature: float = 0.7  # Temperature for LLM


@router.post("/api/run/batch", response_model=RunSingleResponse)
def run_batch(request: RunBatchRequestWithHeader, db: Session = Depends(get_db)):
    """Execute batch job from dataset.

    Phase 2 implementation: Creates batch job and executes synchronously

    Specification: docs/req.txt section 3.3 (バッチ実行通信フロー), 4.3.2
    """
    try:
        # Get latest revision for project
        revision = db.query(ProjectRevision).filter(
            ProjectRevision.project_id == request.project_id
        ).order_by(ProjectRevision.revision.desc()).first()

        if not revision:
            raise HTTPException(
                status_code=404,
                detail="Project revision not found"
            )

        # Create job manager
        job_manager = JobManager(db)

        # Create batch job
        job = job_manager.create_batch_job(
            project_revision_id=revision.id,
            dataset_id=request.dataset_id
        )

        # Execute job with CSV header option
        job = job_manager.execute_job(
            job_id=job.id,
            model_name=request.model_name,
            include_csv_header=request.include_csv_header,
            temperature=request.temperature
        )

        # Load job items for response
        job_items = db.query(JobItem).filter(JobItem.job_id == job.id).all()
        items = [
            JobItemResponse(
                id=item.id,
                created_at=item.created_at,
                input_params=item.input_params,
                raw_prompt=item.raw_prompt,
                raw_response=item.raw_response,
                parsed_response=item.parsed_response,
                status=item.status,
                error_message=item.error_message,
                turnaround_ms=item.turnaround_ms
            )
            for item in job_items
        ]

        job_response = JobResponse(
            id=job.id,
            job_type=job.job_type,
            status=job.status,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            turnaround_ms=job.turnaround_ms,
            merged_csv_output=job.merged_csv_output,
            items=items
        )

        return RunSingleResponse(
            success=True,
            job_id=job.id,
            job=job_response,
            message=f"Batch job executed: {len([i for i in items if i.status=='done'])} completed, {len([i for i in items if i.status=='error'])} errors"
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch execution failed: {str(e)}")


@router.get("/api/jobs/{job_id}", response_model=Dict[str, Any])
def get_job_status(job_id: int, db: Session = Depends(get_db)):
    """Get job status and progress.

    Specification: docs/req.txt section 3.3 (バッチ実行通信フロー step 6)
    Phase 2
    """
    try:
        job_manager = JobManager(db)
        progress = job_manager.get_job_progress(job_id)

        return progress

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get job status: {str(e)}")

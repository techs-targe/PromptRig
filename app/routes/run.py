"""Execution API endpoints.

Based on specification in docs/req.txt section 3.2, 3.3, 4.2.3, 4.3
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any

from backend.database import get_db, ProjectRevision, JobItem, SessionLocal
from backend.job import JobManager
from app.schemas.requests import RunSingleRequest
from app.schemas.responses import RunSingleResponse, JobResponse, JobItemResponse

router = APIRouter()


def execute_job_background(job_id: int, model_name: str, include_csv_header: bool, temperature: float):
    """Execute job in background task.

    Creates new database session for background execution.
    """
    db = SessionLocal()
    try:
        job_manager = JobManager(db)
        job_manager.execute_job(
            job_id=job_id,
            model_name=model_name,
            include_csv_header=include_csv_header,
            temperature=temperature
        )
    finally:
        db.close()


class RunBatchRequest(BaseModel):
    """Request body for POST /api/run/batch.

    Specification: docs/req.txt section 3.3 (バッチ実行通信フロー)
    Phase 2
    """
    project_id: int
    dataset_id: int
    model_name: str = None


@router.post("/api/run/single", response_model=RunSingleResponse)
def run_single(request: RunSingleRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Execute single/repeated prompt execution.

    Phase 2 update:
    - Supports multiple projects via project_id in request
    - Uses latest revision for specified project
    - Executes asynchronously in background
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

        # Create job with job items (but don't execute yet)
        job = job_manager.create_single_job(
            project_revision_id=revision.id,
            input_params=request.input_params,
            repeat=request.repeat,
            model_name=request.model_name
        )

        # Start execution in background
        background_tasks.add_task(
            execute_job_background,
            job.id,
            request.model_name,
            request.include_csv_header,
            request.temperature
        )

        # Load job items for immediate response (will be in pending state)
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
            model_name=job.model_name,
            items=items
        )

        return RunSingleResponse(
            success=True,
            job_id=job.id,
            job=job_response,
            message=f"Job started with {len(items)} item(s)"
        )

    except HTTPException:
        raise  # Re-raise HTTPException as-is (preserve 404, etc.)
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
def run_batch(request: RunBatchRequestWithHeader, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Execute batch job from dataset.

    Phase 2 implementation: Creates batch job and executes asynchronously

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

        # Create batch job (but don't execute yet)
        job = job_manager.create_batch_job(
            project_revision_id=revision.id,
            dataset_id=request.dataset_id,
            model_name=request.model_name
        )

        # Start execution in background
        background_tasks.add_task(
            execute_job_background,
            job.id,
            request.model_name,
            request.include_csv_header,
            request.temperature
        )

        # Load job items for immediate response (will be in pending state)
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
            model_name=job.model_name,
            items=items
        )

        return RunSingleResponse(
            success=True,
            job_id=job.id,
            job=job_response,
            message=f"Batch job started with {len(items)} item(s)"
        )

    except HTTPException:
        raise  # Re-raise HTTPException as-is (preserve 404, etc.)
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

    except HTTPException:
        raise  # Re-raise HTTPException as-is
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get job status: {str(e)}")


@router.post("/api/jobs/{job_id}/cancel", response_model=Dict[str, Any])
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    """Cancel all pending items in a job.

    Args:
        job_id: ID of job to cancel

    Returns:
        Cancellation results

    Note:
        This only cancels pending items. Running items cannot be stopped
        as they are already executing LLM API calls.

    Phase 3 feature for job control
    """
    try:
        job_manager = JobManager(db)
        result = job_manager.cancel_pending_items(job_id)

        return result

    except HTTPException:
        raise  # Re-raise HTTPException as-is
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel job: {str(e)}")

"""Execution API endpoints.

Based on specification in docs/req.txt section 3.2, 3.3, 4.2.3, 4.3

Background Job Execution:
- Jobs are executed in a SEQUENTIAL queue (not parallel)
- Browser connection is NOT required after job submission
- Jobs continue running even if browser is closed
- Server restart will mark running jobs as 'error' (recovery on startup)
"""

import logging
import threading
import queue
import urllib.parse
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import json

from backend.database import get_db, ProjectRevision, PromptRevision, JobItem, SessionLocal
from backend.database.models import Prompt, Job
from backend.job import JobManager
from app.schemas.requests import RunSingleRequest, RunBatchAllRequest
from app.schemas.responses import RunSingleResponse, JobResponse, JobItemResponse

router = APIRouter()
logger = logging.getLogger(__name__)

# Global job queue for sequential execution
_job_queue = queue.Queue()
_worker_thread = None
_worker_lock = threading.Lock()


def _job_queue_worker():
    """Background worker that processes jobs sequentially from the queue."""
    logger.info("[QUEUE-WORKER] Job queue worker started")

    while True:
        try:
            # Get next job from queue (blocks until available)
            job_config = _job_queue.get(timeout=30)  # 30 second timeout

            if job_config is None:  # Shutdown signal
                logger.info("[QUEUE-WORKER] Received shutdown signal")
                break

            job_id = job_config['job_id']
            model_name = job_config['model_name']
            include_csv_header = job_config['include_csv_header']
            temperature = job_config['temperature']

            logger.info(f"[QUEUE-WORKER] Processing job {job_id} from queue")

            db = SessionLocal()
            try:
                job_manager = JobManager(db)
                job = job_manager.execute_job(
                    job_id=job_id,
                    model_name=model_name,
                    include_csv_header=include_csv_header,
                    temperature=temperature
                )
                logger.info(f"[QUEUE-WORKER] Job {job_id} completed with status={job.status}")
            except Exception as e:
                logger.error(f"[QUEUE-WORKER] Job {job_id} failed: {e}")
            finally:
                db.close()
                _job_queue.task_done()

        except queue.Empty:
            # No jobs for 30 seconds, check if we should continue
            if _job_queue.empty():
                logger.info("[QUEUE-WORKER] Queue empty for 30s, worker exiting")
                break

    logger.info("[QUEUE-WORKER] Job queue worker stopped")


def _ensure_worker_running():
    """Ensure the job queue worker thread is running."""
    global _worker_thread

    with _worker_lock:
        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(target=_job_queue_worker, daemon=True)
            _worker_thread.start()
            logger.info("[QUEUE] Started new job queue worker thread")


def enqueue_job(job_id: int, model_name: str, include_csv_header: bool, temperature: float):
    """Add a job to the sequential execution queue."""
    job_config = {
        'job_id': job_id,
        'model_name': model_name,
        'include_csv_header': include_csv_header,
        'temperature': temperature
    }
    _job_queue.put(job_config)
    queue_size = _job_queue.qsize()
    logger.info(f"[QUEUE] Job {job_id} added to queue (queue size: {queue_size})")

    # Ensure worker is running
    _ensure_worker_running()

    return queue_size


def execute_job_background(job_id: int, model_name: str, include_csv_header: bool, temperature: float):
    """Execute job in background task.

    This function runs INDEPENDENTLY of the HTTP connection.
    Even if the browser is closed, this task continues executing on the server.

    Creates new database session for background execution.
    """
    start_time = datetime.utcnow()
    logger.info(f"[BACKGROUND] Starting job {job_id} (model={model_name}, temp={temperature})")

    db = SessionLocal()
    try:
        job_manager = JobManager(db)
        job = job_manager.execute_job(
            job_id=job_id,
            model_name=model_name,
            include_csv_header=include_csv_header,
            temperature=temperature
        )

        elapsed = (datetime.utcnow() - start_time).total_seconds()
        logger.info(f"[BACKGROUND] Job {job_id} completed with status={job.status} in {elapsed:.2f}s")

    except Exception as e:
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        logger.error(f"[BACKGROUND] Job {job_id} failed after {elapsed:.2f}s: {e}")
        # Note: The job status is already updated in execute_job on error
        raise
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

    NEW ARCHITECTURE (v3.0):
    - If prompt_id is provided, uses PromptRevision
    - Otherwise falls back to ProjectRevision for backward compatibility

    Specification: docs/req.txt section 3.2 (通信フロー step 4-6), 4.2.3
    """
    try:
        project_revision_id = None
        prompt_revision_id = None

        # NEW ARCHITECTURE: Check if prompt_id is provided
        if request.prompt_id:
            # Use PromptRevision (new architecture)
            prompt_revision = db.query(PromptRevision).filter(
                PromptRevision.prompt_id == request.prompt_id
            ).order_by(PromptRevision.revision.desc()).first()

            if not prompt_revision:
                raise HTTPException(
                    status_code=404,
                    detail="Prompt revision not found. Please check the prompt_id."
                )
            prompt_revision_id = prompt_revision.id
        else:
            # Fall back to ProjectRevision (backward compatibility)
            revision = db.query(ProjectRevision).filter(
                ProjectRevision.project_id == request.project_id
            ).order_by(ProjectRevision.revision.desc()).first()

            if not revision:
                raise HTTPException(
                    status_code=404,
                    detail="Project revision not found. Please run database initialization."
                )
            project_revision_id = revision.id

        # Create job manager
        job_manager = JobManager(db)

        # Create job with job items (but don't execute yet)
        job = job_manager.create_single_job(
            project_revision_id=project_revision_id,
            prompt_revision_id=prompt_revision_id,
            input_params=request.input_params,
            repeat=request.repeat,
            model_name=request.model_name
        )

        # Add job to sequential execution queue
        queue_size = enqueue_job(
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
    prompt_id: int = None  # NEW ARCHITECTURE: Optional prompt_id for specific prompt execution


@router.post("/api/run/batch", response_model=RunSingleResponse)
def run_batch(request: RunBatchRequestWithHeader, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Execute batch job from dataset.

    Phase 2 implementation: Creates batch job and executes asynchronously
    NEW ARCHITECTURE (v3.0): Supports prompt_id for specific prompt execution

    Specification: docs/req.txt section 3.3 (バッチ実行通信フロー), 4.3.2
    """
    try:
        project_revision_id = None
        prompt_revision_id = None

        # NEW ARCHITECTURE: Check if prompt_id is provided
        if request.prompt_id:
            # Use PromptRevision (new architecture)
            prompt_revision = db.query(PromptRevision).filter(
                PromptRevision.prompt_id == request.prompt_id
            ).order_by(PromptRevision.revision.desc()).first()

            if not prompt_revision:
                raise HTTPException(
                    status_code=404,
                    detail="Prompt revision not found. Please check the prompt_id."
                )
            prompt_revision_id = prompt_revision.id
        else:
            # Fall back to ProjectRevision (backward compatibility)
            revision = db.query(ProjectRevision).filter(
                ProjectRevision.project_id == request.project_id
            ).order_by(ProjectRevision.revision.desc()).first()

            if not revision:
                raise HTTPException(
                    status_code=404,
                    detail="Project revision not found"
                )
            project_revision_id = revision.id

        # Create job manager
        job_manager = JobManager(db)

        # Create batch job (but don't execute yet)
        job = job_manager.create_batch_job(
            project_revision_id=project_revision_id,
            prompt_revision_id=prompt_revision_id,
            dataset_id=request.dataset_id,
            model_name=request.model_name
        )

        # Add job to sequential execution queue
        queue_size = enqueue_job(
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


@router.get("/api/jobs/{job_id}/details", response_model=JobResponse)
def get_job_details(job_id: int, db: Session = Depends(get_db)):
    """Get job with all items and details.

    Returns the full job data including all job items for display in history.
    """
    from backend.database.models import Prompt
    from backend.database import PromptRevision

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Load job items
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

    # Get prompt_id, prompt name and project name from prompt_revision relationship
    prompt_id_val = None
    prompt_name = None
    project_name = None
    if job.prompt_revision_id:
        # NEW architecture: get from prompt_revision
        prompt_revision = db.query(PromptRevision).filter(
            PromptRevision.id == job.prompt_revision_id
        ).first()
        if prompt_revision:
            prompt = db.query(Prompt).filter(Prompt.id == prompt_revision.prompt_id).first()
            if prompt:
                prompt_id_val = prompt.id
                prompt_name = prompt.name
                if prompt.project:
                    project_name = prompt.project.name
    elif job.project_revision_id:
        # OLD architecture fallback: get from project_revision
        from backend.database import ProjectRevision, Project
        project_revision = db.query(ProjectRevision).filter(
            ProjectRevision.id == job.project_revision_id
        ).first()
        if project_revision:
            project = db.query(Project).filter(Project.id == project_revision.project_id).first()
            if project:
                project_name = project.name

    return JobResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        turnaround_ms=job.turnaround_ms,
        merged_csv_output=job.merged_csv_output,
        model_name=job.model_name,
        prompt_id=prompt_id_val,
        prompt_name=prompt_name,
        project_name=project_name,
        items=items
    )


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


def execute_batch_all_background(job_configs: List[Dict], include_csv_header: bool):
    """Execute multiple batch jobs sequentially in background.

    This runs INDEPENDENTLY of the HTTP connection.
    All jobs are created upfront, so they will all execute even if browser is closed.

    Args:
        job_configs: List of dicts with job_id, model_name, temperature
        include_csv_header: Whether to include CSV header
    """
    logger.info(f"[BATCH-ALL] Starting execution of {len(job_configs)} batch jobs")

    for i, config in enumerate(job_configs):
        job_id = config['job_id']
        model_name = config['model_name']
        temperature = config['temperature']

        logger.info(f"[BATCH-ALL] Executing job {i+1}/{len(job_configs)}: job_id={job_id}")

        db = SessionLocal()
        try:
            job_manager = JobManager(db)
            job = job_manager.execute_job(
                job_id=job_id,
                model_name=model_name,
                include_csv_header=include_csv_header,
                temperature=temperature
            )
            logger.info(f"[BATCH-ALL] Job {job_id} completed with status={job.status}")

        except Exception as e:
            logger.error(f"[BATCH-ALL] Job {job_id} failed: {e}")
            # Continue with next job even if one fails
        finally:
            db.close()

    logger.info(f"[BATCH-ALL] All {len(job_configs)} jobs completed")


@router.post("/api/run/batch-all", response_model=Dict[str, Any])
def run_batch_all(request: RunBatchAllRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Execute batch for ALL prompts in a project.

    Creates all batch jobs upfront on the server, then queues them all in background.
    This ensures all jobs will execute even if the browser is closed.

    If there are already running/pending batch jobs for this project and force=false,
    returns an error with running_jobs info so the client can ask user for confirmation.

    Returns:
        - job_ids: List of created job IDs
        - prompt_count: Number of prompts
        - message: Status message
    """
    try:
        # Get all prompts for the project
        prompts = db.query(Prompt).filter(
            Prompt.project_id == request.project_id
        ).order_by(Prompt.id).all()

        if not prompts:
            raise HTTPException(
                status_code=404,
                detail="No prompts found for this project"
            )

        # Check for running/pending OR recent batch jobs if force=false
        if not request.force:
            prompt_ids = [p.id for p in prompts]
            prompt_revision_ids = []
            for pid in prompt_ids:
                revs = db.query(PromptRevision).filter(PromptRevision.prompt_id == pid).all()
                prompt_revision_ids.extend([r.id for r in revs])

            if prompt_revision_ids:
                # Check for running/pending jobs
                running_jobs = db.query(Job).filter(
                    Job.prompt_revision_id.in_(prompt_revision_ids),
                    Job.job_type == 'batch',
                    Job.status.in_(['pending', 'running'])
                ).all()

                if running_jobs:
                    running_job_info = [
                        {'job_id': j.id, 'status': j.status, 'created_at': str(j.created_at)}
                        for j in running_jobs
                    ]
                    return {
                        "success": False,
                        "has_running_jobs": True,
                        "running_jobs_count": len(running_jobs),
                        "running_jobs": running_job_info,
                        "message": f"既に {len(running_jobs)} 件の実行中/待機中ジョブがあります。追加しますか？"
                    }

                # Also check for recently created jobs (within last 5 minutes)
                # Note: SQLite stores datetime as ISO format strings, so we compare as strings
                from datetime import timedelta
                five_minutes_ago = datetime.utcnow() - timedelta(minutes=5)
                five_minutes_ago_str = five_minutes_ago.isoformat()
                recent_jobs = db.query(Job).filter(
                    Job.prompt_revision_id.in_(prompt_revision_ids),
                    Job.job_type == 'batch',
                    Job.created_at >= five_minutes_ago_str
                ).order_by(Job.created_at.desc()).all()

                if recent_jobs:
                    recent_job_info = [
                        {'job_id': j.id, 'status': j.status, 'created_at': str(j.created_at)}
                        for j in recent_jobs
                    ]
                    return {
                        "success": False,
                        "has_recent_jobs": True,
                        "recent_jobs_count": len(recent_jobs),
                        "recent_jobs": recent_job_info,
                        "message": f"過去5分以内に {len(recent_jobs)} 件のジョブが作成されています。追加しますか？"
                    }

        job_manager = JobManager(db)
        created_jobs = []
        job_configs = []

        # Create ALL jobs upfront
        for prompt in prompts:
            # Get latest revision for this prompt
            prompt_revision = db.query(PromptRevision).filter(
                PromptRevision.prompt_id == prompt.id
            ).order_by(PromptRevision.revision.desc()).first()

            if not prompt_revision:
                logger.warning(f"[BATCH-ALL] No revision found for prompt {prompt.id}, skipping")
                continue

            # Create batch job
            job = job_manager.create_batch_job(
                project_revision_id=None,
                prompt_revision_id=prompt_revision.id,
                dataset_id=request.dataset_id,
                model_name=request.model_name
            )

            created_jobs.append({
                'job_id': job.id,
                'prompt_id': prompt.id,
                'prompt_name': prompt.name
            })

            job_configs.append({
                'job_id': job.id,
                'model_name': request.model_name,
                'temperature': request.temperature
            })

            logger.info(f"[BATCH-ALL] Created job {job.id} for prompt '{prompt.name}'")

        if not created_jobs:
            raise HTTPException(
                status_code=400,
                detail="No jobs could be created (no valid prompt revisions)"
            )

        # Add ALL jobs to the sequential execution queue
        for config in job_configs:
            enqueue_job(
                config['job_id'],
                config['model_name'],
                request.include_csv_header,
                config['temperature']
            )

        queue_size = _job_queue.qsize()
        logger.info(f"[BATCH-ALL] Enqueued {len(job_configs)} jobs (total queue size: {queue_size})")

        return {
            "success": True,
            "job_ids": [j['job_id'] for j in created_jobs],
            "jobs": created_jobs,
            "prompt_count": len(created_jobs),
            "queue_size": queue_size,
            "message": f"Created and queued {len(created_jobs)} batch jobs for execution"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[BATCH-ALL] Failed to create jobs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create batch jobs: {str(e)}")


# ========== Job List and Preview Endpoints ==========

class JobListResponse(BaseModel):
    """Job list item response."""
    id: int
    job_type: str
    status: str
    created_at: str
    item_count: int = 0
    prompt_name: Optional[str] = None
    project_name: Optional[str] = None
    model_name: Optional[str] = None
    is_workflow_job: bool = False  # NEW: distinguish workflow jobs


@router.get("/api/jobs", response_model=List[JobListResponse])
def list_jobs(
    project_id: Optional[int] = None,
    prompt_id: Optional[int] = None,
    workflow_id: Optional[int] = None,  # NEW: filter by workflow
    job_type: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """List jobs with optional filters. Supports both regular jobs and workflow jobs."""
    from backend.database.models import WorkflowJob, WorkflowJobStep, Workflow

    result = []

    # If workflow_id is specified, query workflow_jobs table
    if workflow_id:
        wf_query = db.query(WorkflowJob).filter(WorkflowJob.workflow_id == workflow_id)

        # Get workflow name
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        workflow_name = f"[WF] {workflow.name}" if workflow else None

        wf_jobs = wf_query.order_by(WorkflowJob.created_at.desc()).limit(limit).all()

        for wf_job in wf_jobs:
            # Count steps as item_count
            step_count = db.query(WorkflowJobStep).filter(
                WorkflowJobStep.workflow_job_id == wf_job.id
            ).count()

            result.append(JobListResponse(
                id=wf_job.id,
                job_type="workflow",
                status=wf_job.status,
                created_at=wf_job.created_at,
                item_count=step_count,
                prompt_name=workflow_name,
                model_name=wf_job.model_name,
                is_workflow_job=True
            ))

        return result

    # Regular jobs query
    query = db.query(Job)

    # Filter by project_id through prompt revision
    if project_id:
        from backend.database.models import PromptRevision as PRev
        prompt_revision_ids = db.query(PRev.id).join(Prompt).filter(
            Prompt.project_id == project_id
        ).subquery()
        query = query.filter(Job.prompt_revision_id.in_(prompt_revision_ids))

    # Filter by prompt_id
    if prompt_id:
        from backend.database.models import PromptRevision as PRev
        prompt_revision_ids = db.query(PRev.id).filter(
            PRev.prompt_id == prompt_id
        ).subquery()
        query = query.filter(Job.prompt_revision_id.in_(prompt_revision_ids))

    # Filter by job type
    if job_type:
        query = query.filter(Job.job_type == job_type)

    jobs = query.order_by(Job.created_at.desc()).limit(limit).all()

    for job in jobs:
        # Get item count
        item_count = db.query(JobItem).filter(JobItem.job_id == job.id).count()

        # Get prompt name and project name
        prompt_name = None
        project_name = None
        if job.prompt_revision_id:
            # NEW architecture: get from prompt_revision
            from backend.database.models import PromptRevision as PRev
            prev = db.query(PRev).filter(PRev.id == job.prompt_revision_id).first()
            if prev and prev.prompt:
                prompt_name = prev.prompt.name
                if prev.prompt.project:
                    project_name = prev.prompt.project.name
        elif job.project_revision_id:
            # OLD architecture fallback: get from project_revision
            from backend.database import ProjectRevision, Project
            project_revision = db.query(ProjectRevision).filter(
                ProjectRevision.id == job.project_revision_id
            ).first()
            if project_revision:
                project = db.query(Project).filter(Project.id == project_revision.project_id).first()
                if project:
                    project_name = project.name

        result.append(JobListResponse(
            id=job.id,
            job_type=job.job_type,
            status=job.status,
            created_at=job.created_at,
            item_count=item_count,
            prompt_name=prompt_name,
            project_name=project_name,
            model_name=job.model_name,
            is_workflow_job=False
        ))

    return result


@router.get("/api/jobs/{job_id}/csv-preview")
def get_job_csv_preview(
    job_id: int,
    db: Session = Depends(get_db)
):
    """Get CSV preview of job results.

    IMPORTANT: Header and data order consistency
    - If csv_header exists: use csv_header + csv_output (same source, safe)
    - If csv_header missing but csv_output exists: regenerate BOTH from fields
      (csv_output order may differ from fields order)
    - If only fields exists: generate both from fields
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # First, try to use job.merged_csv_output if available (most reliable)
    if job.merged_csv_output:
        lines = [line for line in job.merged_csv_output.strip().split("\n") if line.strip()]
        return {
            "job_id": job_id,
            "csv_data": job.merged_csv_output.strip() if lines else None,
            "row_count": len(lines) - 1 if len(lines) > 1 else 0  # -1 for header
        }

    # Fall back to building from job_items
    job_items = db.query(JobItem).filter(
        JobItem.job_id == job_id,
        JobItem.status == "done"
    ).all()

    csv_lines = []
    header = None

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
                header = csv_header
                csv_lines.insert(0, header)
            if csv_output:
                for line in csv_output.strip().split("\n"):
                    if line.strip():
                        csv_lines.append(line)
        elif fields:
            # csv_header missing: generate BOTH header and data from fields
            # This ensures order consistency (ignore csv_output which may have different order)
            if header is None:
                header = ",".join(fields.keys())
                csv_lines.insert(0, header)
            # Always regenerate data from fields to match header order
            csv_lines.append(",".join([str(v) for v in fields.values()]))

    return {
        "job_id": job_id,
        "csv_data": "\n".join(csv_lines) if csv_lines else None,
        "row_count": len(csv_lines) - 1 if header and csv_lines else len(csv_lines)
    }


@router.get("/api/jobs/{job_id}/csv")
def download_job_csv(
    job_id: int,
    db: Session = Depends(get_db)
):
    """Download job results as CSV file.

    Returns a downloadable CSV file with Content-Disposition header.
    This endpoint can be used as a direct download link.

    Example: http://localhost:9200/api/jobs/123/csv
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    csv_data = None

    # First, try to use job.merged_csv_output if available
    if job.merged_csv_output:
        csv_data = job.merged_csv_output.strip()
    else:
        # Fall back to building from job_items
        job_items = db.query(JobItem).filter(
            JobItem.job_id == job_id,
            JobItem.status == "done"
        ).all()

        csv_lines = []
        header = None

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

            if csv_header:
                if header is None:
                    header = csv_header
                    csv_lines.insert(0, header)
                if csv_output:
                    for line in csv_output.strip().split("\n"):
                        if line.strip():
                            csv_lines.append(line)
            elif fields:
                if header is None:
                    header = ",".join(fields.keys())
                    csv_lines.insert(0, header)
                csv_lines.append(",".join([str(v) for v in fields.values()]))

        if csv_lines:
            csv_data = "\n".join(csv_lines)

    if not csv_data:
        raise HTTPException(status_code=404, detail="No CSV data available for this job")

    # Get project name for filename
    project_name = "job"
    # Access project through prompt_revision chain
    if job.prompt_revision and job.prompt_revision.prompt and job.prompt_revision.prompt.project:
        project = job.prompt_revision.prompt.project
        # Sanitize project name for filename - ASCII only to avoid HTTP header encoding issues
        project_name = "".join(c for c in project.name if c.isascii() and (c.isalnum() or c in "._- ")).strip()
        project_name = project_name.replace(" ", "_")[:50]
        if not project_name:  # If all characters were non-ASCII, use project ID
            project_name = f"project_{project.id}"

    filename = f"{project_name}_job_{job_id}.csv"
    # Use RFC 5987 encoding for non-ASCII filename support
    filename_encoded = urllib.parse.quote(filename)

    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{filename_encoded}",
            "Content-Type": "text/csv; charset=utf-8"
        }
    )


@router.get("/api/workflow-jobs/{job_id}/csv")
def download_workflow_job_csv(
    job_id: int,
    db: Session = Depends(get_db)
):
    """Download workflow job results as CSV file.

    Returns a downloadable CSV file with Content-Disposition header.

    Example: http://localhost:9200/api/workflow-jobs/123/csv
    """
    from backend.database.models import WorkflowJob, Workflow

    wf_job = db.query(WorkflowJob).filter(WorkflowJob.id == job_id).first()
    if not wf_job:
        raise HTTPException(status_code=404, detail="Workflow job not found")

    csv_data = None

    # Primary: use merged_csv_output if available
    if wf_job.merged_csv_output:
        csv_data = wf_job.merged_csv_output.strip()
    # Fallback: generate CSV from merged_output vars
    elif wf_job.merged_output:
        try:
            output = json.loads(wf_job.merged_output)
            vars_data = output.get("vars", {})
            if vars_data:
                # Extract flat values (exclude nested objects like ROW)
                flat_vars = {}
                for k, v in vars_data.items():
                    if isinstance(v, (str, int, float, bool)):
                        flat_vars[k] = str(v)
                    elif v is None:
                        flat_vars[k] = ""
                    # Skip dict/list (iterator variables like ROW)

                if flat_vars:
                    csv_lines = []
                    csv_lines.append(",".join(flat_vars.keys()))  # header
                    csv_lines.append(",".join(flat_vars.values()))  # data
                    csv_data = "\n".join(csv_lines)
        except (json.JSONDecodeError, Exception):
            pass  # Fall through to error

    if not csv_data:
        raise HTTPException(status_code=404, detail="No CSV data available for this workflow job")

    # Get workflow name for filename
    workflow_name = "workflow"
    if wf_job.workflow_id:
        workflow = db.query(Workflow).filter(Workflow.id == wf_job.workflow_id).first()
        if workflow:
            # ASCII only to avoid HTTP header encoding issues
            workflow_name = "".join(c for c in workflow.name if c.isascii() and (c.isalnum() or c in "._- ")).strip()
            workflow_name = workflow_name.replace(" ", "_")[:50]
            if not workflow_name:  # If all characters were non-ASCII, use workflow ID
                workflow_name = f"workflow_{workflow.id}"

    filename = f"{workflow_name}_job_{job_id}.csv"
    # Use RFC 5987 encoding for non-ASCII filename support
    filename_encoded = urllib.parse.quote(filename)

    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{filename_encoded}",
            "Content-Type": "text/csv; charset=utf-8"
        }
    )


@router.get("/api/workflow-jobs/{job_id}/csv-preview")
def get_workflow_job_csv_preview(
    job_id: int,
    db: Session = Depends(get_db)
):
    """Get CSV preview of workflow job results.

    Workflow jobs store merged CSV output directly in the workflow_jobs table.
    """
    from backend.database.models import WorkflowJob

    wf_job = db.query(WorkflowJob).filter(WorkflowJob.id == job_id).first()
    if not wf_job:
        raise HTTPException(status_code=404, detail="Workflow job not found")

    csv_data = None

    # Primary: use merged_csv_output if available
    if wf_job.merged_csv_output:
        csv_data = wf_job.merged_csv_output.strip()
    # Fallback: generate CSV from merged_output vars
    elif wf_job.merged_output:
        try:
            output = json.loads(wf_job.merged_output)
            vars_data = output.get("vars", {})
            if vars_data:
                flat_vars = {}
                for k, v in vars_data.items():
                    if isinstance(v, (str, int, float, bool)):
                        flat_vars[k] = str(v)
                    elif v is None:
                        flat_vars[k] = ""

                if flat_vars:
                    csv_lines = []
                    csv_lines.append(",".join(flat_vars.keys()))
                    csv_lines.append(",".join(flat_vars.values()))
                    csv_data = "\n".join(csv_lines)
        except (json.JSONDecodeError, Exception):
            pass

    if csv_data:
        lines = [line for line in csv_data.split("\n") if line.strip()]
        return {
            "job_id": job_id,
            "csv_data": csv_data,
            "row_count": len(lines) - 1 if len(lines) > 1 else 0,  # -1 for header
            "is_workflow_job": True
        }

    return {
        "job_id": job_id,
        "csv_data": None,
        "row_count": 0,
        "is_workflow_job": True
    }

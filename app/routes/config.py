"""Configuration API endpoint.

Based on specification in docs/req.txt section 3.2 (通信フロー step 2)
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db, Project, ProjectRevision, Job, JobItem
from backend.prompt import PromptTemplateParser
from app.schemas.responses import (
    ConfigResponse,
    ParameterDefinitionResponse,
    JobResponse,
    JobItemResponse
)

router = APIRouter()


@router.get("/api/config", response_model=ConfigResponse)
def get_config(project_id: int = 1, db: Session = Depends(get_db)):
    """Get initial configuration for the UI.

    Args:
        project_id: Project ID to load (default: 1)

    Returns:
    - Project information (Phase 1: fixed project ID=1)
    - Prompt template
    - Extracted parameter definitions
    - Recent execution history

    Specification: docs/req.txt section 3.2 step 2
    """
    # Get project (default project ID=1, or specified)
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError(f"Project with ID {project_id} not found. Please run database initialization.")

    # Get latest project revision
    revision = db.query(ProjectRevision).filter(
        ProjectRevision.project_id == project.id
    ).order_by(ProjectRevision.revision.desc()).first()

    if not revision:
        raise ValueError("No project revision found. Please run database initialization.")

    # Parse prompt template to extract parameters
    parser = PromptTemplateParser()
    param_defs = parser.parse_template(revision.prompt_template)

    # Convert to response format
    parameters = [
        ParameterDefinitionResponse(
            name=p.name,
            type=p.type,
            html_type=p.html_type,
            rows=p.rows,
            accept=p.accept,
            placeholder=p.placeholder,
            required=p.required,
            default=p.default
        )
        for p in param_defs
    ]

    # Get recent jobs
    recent_jobs_data = db.query(Job).filter(
        Job.project_revision_id == revision.id
    ).order_by(Job.created_at.desc()).limit(20).all()

    recent_jobs = []
    for job in recent_jobs_data:
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

        recent_jobs.append(JobResponse(
            id=job.id,
            job_type=job.job_type,
            status=job.status,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            turnaround_ms=job.turnaround_ms,
            items=items
        ))

    return ConfigResponse(
        project_id=project.id,
        project_name=project.name,
        project_revision_id=revision.id,
        revision=revision.revision,
        prompt_template=revision.prompt_template,
        parameters=parameters,
        recent_jobs=recent_jobs,
        available_models=["azure-gpt-4.1", "openai-gpt-4.1-nano"]
    )

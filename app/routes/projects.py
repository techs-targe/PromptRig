"""Project management API endpoints.

Based on specification in docs/req.txt section 4.4 (プロジェクト設定)
Phase 2 implementation.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel

from backend.database import get_db, Project, ProjectRevision, Job, JobItem
from backend.parser import create_default_parser_config
from app.schemas.responses import JobResponse, JobItemResponse

router = APIRouter()


class ProjectCreate(BaseModel):
    """Request to create new project."""
    name: str
    description: str = ""


class ProjectUpdate(BaseModel):
    """Request to update project."""
    name: str
    description: str = ""


class ProjectResponse(BaseModel):
    """Project response model."""
    id: int
    name: str
    description: str
    created_at: str
    revision_count: int = 0
    prompt_template: str = ""
    parser_config: str = ""


class RevisionCreate(BaseModel):
    """Request to create new revision."""
    prompt_template: str = ""
    parser_config: str = ""


class RevisionUpdate(BaseModel):
    """Request to update existing revision."""
    prompt_template: str = ""
    parser_config: str = ""


class RevisionResponse(BaseModel):
    """Revision response model."""
    id: int
    project_id: int
    revision: int
    prompt_template: str
    parser_config: str
    created_at: str


@router.get("/api/projects", response_model=List[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    """List all projects.

    Specification: docs/req.txt section 4.4.1
    Phase 2
    """
    projects = db.query(Project).order_by(Project.created_at.desc()).all()

    result = []
    for project in projects:
        revision_count = db.query(ProjectRevision).filter(
            ProjectRevision.project_id == project.id
        ).count()

        # Get latest revision
        latest_revision = db.query(ProjectRevision).filter(
            ProjectRevision.project_id == project.id
        ).order_by(ProjectRevision.revision.desc()).first()

        result.append(ProjectResponse(
            id=project.id,
            name=project.name,
            description=project.description or "",
            created_at=project.created_at,
            revision_count=revision_count,
            prompt_template=latest_revision.prompt_template if latest_revision else "",
            parser_config=latest_revision.parser_config if latest_revision else ""
        ))

    return result


@router.post("/api/projects", response_model=ProjectResponse)
def create_project(request: ProjectCreate, db: Session = Depends(get_db)):
    """Create new project.

    Specification: docs/req.txt section 4.4.1
    Phase 2
    """
    project = Project(
        name=request.name,
        description=request.description
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    # Create initial revision
    initial_revision = ProjectRevision(
        project_id=project.id,
        revision=1,
        prompt_template="プロンプトを入力してください / Enter your prompt here",
        parser_config=create_default_parser_config()
    )
    db.add(initial_revision)
    db.commit()
    db.refresh(initial_revision)

    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description or "",
        created_at=project.created_at,
        revision_count=1,
        prompt_template=initial_revision.prompt_template,
        parser_config=initial_revision.parser_config
    )


@router.get("/api/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, db: Session = Depends(get_db)):
    """Get project details.

    Specification: docs/req.txt section 4.4
    Phase 2
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    revision_count = db.query(ProjectRevision).filter(
        ProjectRevision.project_id == project.id
    ).count()

    # Get latest revision
    latest_revision = db.query(ProjectRevision).filter(
        ProjectRevision.project_id == project.id
    ).order_by(ProjectRevision.revision.desc()).first()

    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description or "",
        created_at=project.created_at,
        revision_count=revision_count,
        prompt_template=latest_revision.prompt_template if latest_revision else "",
        parser_config=latest_revision.parser_config if latest_revision else ""
    )


@router.put("/api/projects/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    request: ProjectUpdate,
    db: Session = Depends(get_db)
):
    """Update project.

    Specification: docs/req.txt section 4.4.1
    Phase 2
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project.name = request.name
    project.description = request.description
    db.commit()
    db.refresh(project)

    revision_count = db.query(ProjectRevision).filter(
        ProjectRevision.project_id == project.id
    ).count()

    # Get latest revision
    latest_revision = db.query(ProjectRevision).filter(
        ProjectRevision.project_id == project.id
    ).order_by(ProjectRevision.revision.desc()).first()

    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description or "",
        created_at=project.created_at,
        revision_count=revision_count,
        prompt_template=latest_revision.prompt_template if latest_revision else "",
        parser_config=latest_revision.parser_config if latest_revision else ""
    )


@router.delete("/api/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    """Delete project.

    Specification: docs/req.txt section 4.4.1
    Phase 2
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    db.delete(project)
    db.commit()

    return {"success": True, "message": f"Project {project_id} deleted"}


@router.get("/api/projects/{project_id}/revisions", response_model=List[RevisionResponse])
def list_revisions(project_id: int, db: Session = Depends(get_db)):
    """List all revisions for a project.

    Specification: docs/req.txt section 4.4.3
    Phase 2
    """
    revisions = db.query(ProjectRevision).filter(
        ProjectRevision.project_id == project_id
    ).order_by(ProjectRevision.revision.desc()).all()

    return [
        RevisionResponse(
            id=rev.id,
            project_id=rev.project_id,
            revision=rev.revision,
            prompt_template=rev.prompt_template,
            parser_config=rev.parser_config or "",
            created_at=rev.created_at
        )
        for rev in revisions
    ]


@router.post("/api/projects/{project_id}/revisions", response_model=RevisionResponse)
def create_revision(
    project_id: int,
    request: RevisionCreate,
    db: Session = Depends(get_db)
):
    """Create new revision for project (Rebuild button).

    Specification: docs/req.txt section 4.4.3 - リビルドボタン
    Phase 2
    """
    # Get latest revision number
    latest = db.query(ProjectRevision).filter(
        ProjectRevision.project_id == project_id
    ).order_by(ProjectRevision.revision.desc()).first()

    next_revision = (latest.revision + 1) if latest else 1

    revision = ProjectRevision(
        project_id=project_id,
        revision=next_revision,
        prompt_template=request.prompt_template,
        parser_config=request.parser_config or create_default_parser_config()
    )
    db.add(revision)
    db.commit()
    db.refresh(revision)

    return RevisionResponse(
        id=revision.id,
        project_id=revision.project_id,
        revision=revision.revision,
        prompt_template=revision.prompt_template,
        parser_config=revision.parser_config or "",
        created_at=revision.created_at
    )


@router.put("/api/projects/{project_id}/revisions/latest", response_model=RevisionResponse)
def update_latest_revision(
    project_id: int,
    request: RevisionUpdate,
    db: Session = Depends(get_db)
):
    """Update latest revision for project (Save button).

    Specification: docs/req.txt section 4.4.3 - 保存ボタン
    Phase 2
    """
    # Get latest revision
    latest = db.query(ProjectRevision).filter(
        ProjectRevision.project_id == project_id
    ).order_by(ProjectRevision.revision.desc()).first()

    if not latest:
        raise HTTPException(status_code=404, detail="No revision found for this project")

    # Update existing revision
    if request.prompt_template:
        latest.prompt_template = request.prompt_template
    if request.parser_config:
        latest.parser_config = request.parser_config

    db.commit()
    db.refresh(latest)

    return RevisionResponse(
        id=latest.id,
        project_id=latest.project_id,
        revision=latest.revision,
        prompt_template=latest.prompt_template,
        parser_config=latest.parser_config or "",
        created_at=latest.created_at
    )


@router.get("/api/projects/{project_id}/jobs", response_model=List[JobResponse])
def get_project_jobs(project_id: int, limit: int = 50, db: Session = Depends(get_db)):
    """Get job history for a specific project.

    Args:
        project_id: ID of the project
        limit: Maximum number of jobs to return (default 50)

    Returns:
        List of jobs with their items, ordered by creation time (newest first)

    Phase 2: Support for multiple projects with job history
    """
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get all revisions for this project
    revisions = db.query(ProjectRevision).filter(
        ProjectRevision.project_id == project_id
    ).all()

    if not revisions:
        return []

    revision_ids = [r.id for r in revisions]

    # Get recent jobs for all revisions of this project
    recent_jobs_data = db.query(Job).filter(
        Job.project_revision_id.in_(revision_ids)
    ).order_by(Job.created_at.desc()).limit(limit).all()

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
            merged_csv_output=job.merged_csv_output,
            items=items
        ))

    return recent_jobs

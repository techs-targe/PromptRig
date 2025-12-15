"""Project management API endpoints.

Based on specification in docs/req.txt section 4.4 (プロジェクト設定)
Phase 2 implementation.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from backend.database import get_db, Project, ProjectRevision, Job, JobItem, Prompt, PromptRevision
from backend.parser import create_default_parser_config
from backend.prompt import PromptTemplateParser
from app.schemas.responses import JobResponse, JobItemResponse, ParameterDefinitionResponse

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
    parameters: List[ParameterDefinitionResponse] = []


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
    is_new: bool = False  # Indicates if a new revision was created


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
    NEW ARCHITECTURE: Also creates a default Prompt with initial revision.
    """
    from datetime import datetime

    project = Project(
        name=request.name,
        description=request.description
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    now = datetime.utcnow().isoformat()
    initial_template = "プロンプトを入力してください / Enter your prompt here"
    initial_parser_config = create_default_parser_config()

    # Create initial revision (OLD - for backward compatibility)
    initial_revision = ProjectRevision(
        project_id=project.id,
        revision=1,
        prompt_template=initial_template,
        parser_config=initial_parser_config
    )
    db.add(initial_revision)
    db.commit()
    db.refresh(initial_revision)

    # NEW ARCHITECTURE: Create default Prompt and PromptRevision
    default_prompt = Prompt(
        project_id=project.id,
        name=f"{request.name} - Default",
        description="Default prompt for this project",
        created_at=now,
        updated_at=now
    )
    db.add(default_prompt)
    db.commit()
    db.refresh(default_prompt)

    prompt_revision = PromptRevision(
        prompt_id=default_prompt.id,
        revision=1,
        prompt_template=initial_template,
        parser_config=initial_parser_config,
        created_at=now
    )
    db.add(prompt_revision)
    db.commit()

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

    NOTE: Prefers PromptRevision (new architecture) over ProjectRevision (old)
    when a project has associated prompts. This ensures optional parameter
    markers (|) are correctly recognized.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    revision_count = db.query(ProjectRevision).filter(
        ProjectRevision.project_id == project.id
    ).count()

    # NEW: Check for prompts (new architecture) first
    # This ensures the latest template with optional markers is used
    default_prompt = db.query(Prompt).filter(
        Prompt.project_id == project_id,
        Prompt.is_deleted == 0
    ).order_by(Prompt.created_at.asc()).first()

    prompt_template = ""
    parser_config = ""
    parameters = []

    if default_prompt:
        # Use PromptRevision (new architecture)
        latest_prompt_revision = db.query(PromptRevision).filter(
            PromptRevision.prompt_id == default_prompt.id
        ).order_by(PromptRevision.revision.desc()).first()

        if latest_prompt_revision:
            prompt_template = latest_prompt_revision.prompt_template
            parser_config = latest_prompt_revision.parser_config or ""

            parser = PromptTemplateParser()
            param_defs = parser.parse_template(prompt_template)
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

    # Fallback to ProjectRevision (old architecture) if no prompts
    if not parameters:
        latest_revision = db.query(ProjectRevision).filter(
            ProjectRevision.project_id == project.id
        ).order_by(ProjectRevision.revision.desc()).first()

        if latest_revision:
            prompt_template = latest_revision.prompt_template
            parser_config = latest_revision.parser_config or ""

            parser = PromptTemplateParser()
            param_defs = parser.parse_template(prompt_template)
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

    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description or "",
        created_at=project.created_at,
        revision_count=revision_count,
        prompt_template=prompt_template,
        parser_config=parser_config,
        parameters=parameters
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

    # Normalize parser config to prevent double-encoding
    parser_config = request.parser_config or create_default_parser_config()
    normalized_parser = normalize_json_for_comparison(parser_config)
    parser_to_store = normalized_parser if normalized_parser else parser_config

    revision = ProjectRevision(
        project_id=project_id,
        revision=next_revision,
        prompt_template=request.prompt_template,
        parser_config=parser_to_store
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


@router.post("/api/projects/{project_id}/revisions/{revision_number}/restore", response_model=RevisionResponse)
def restore_revision(
    project_id: int,
    revision_number: int,
    db: Session = Depends(get_db)
):
    """Restore a past revision by creating a new revision with its content.

    Example: If current is revision 10, restoring revision 7 creates revision 11
    with the content of revision 7.

    Specification: Enhanced revision management
    Phase 2
    """
    # Find the revision to restore
    target_revision = db.query(ProjectRevision).filter(
        ProjectRevision.project_id == project_id,
        ProjectRevision.revision == revision_number
    ).first()

    if not target_revision:
        raise HTTPException(
            status_code=404,
            detail=f"Revision {revision_number} not found for this project"
        )

    # Get latest revision number
    latest = db.query(ProjectRevision).filter(
        ProjectRevision.project_id == project_id
    ).order_by(ProjectRevision.revision.desc()).first()

    next_revision = (latest.revision + 1) if latest else 1

    # Normalize parser config when restoring (in case old revision had double-encoded data)
    normalized_parser = normalize_json_for_comparison(target_revision.parser_config or "")
    parser_to_store = normalized_parser if normalized_parser else target_revision.parser_config

    # Create new revision with content from target revision
    new_revision = ProjectRevision(
        project_id=project_id,
        revision=next_revision,
        prompt_template=target_revision.prompt_template,
        parser_config=parser_to_store
    )
    db.add(new_revision)
    db.commit()
    db.refresh(new_revision)

    return RevisionResponse(
        id=new_revision.id,
        project_id=new_revision.project_id,
        revision=new_revision.revision,
        prompt_template=new_revision.prompt_template,
        parser_config=new_revision.parser_config or "",
        created_at=new_revision.created_at,
        is_new=True
    )


def unwrap_json_string(value):
    """Recursively unwrap a JSON value until we get a dict/list or non-JSON string.

    This handles cases where JSON was double/triple encoded:
    - '{"type":"none"}' -> {"type": "none"} (dict)
    - '"{\\"type\\":\\"none\\"}"' -> {"type": "none"} (dict)
    """
    import json as json_module

    # If it's already a dict or list, we're done
    if isinstance(value, (dict, list)):
        return value

    # If it's not a string, return as-is
    if not isinstance(value, str):
        return value

    # Try to parse as JSON
    try:
        parsed = json_module.loads(value)
        # If we got a string, it might be double-encoded, try again
        if isinstance(parsed, str):
            return unwrap_json_string(parsed)
        # If we got a dict or list, we're done
        return parsed
    except (json_module.JSONDecodeError, TypeError):
        # Not valid JSON, return original string
        return value


def normalize_json_for_comparison(json_str: str) -> str:
    """Normalize JSON string for comparison by parsing and re-serializing.

    This ensures consistent formatting regardless of whitespace or key order.
    Also handles double/triple encoded JSON strings.
    Returns empty string if parsing fails or input is empty.
    """
    import json
    if not json_str or not json_str.strip():
        return ""
    try:
        # Unwrap any double/triple encoding first
        unwrapped = unwrap_json_string(json_str)

        # If we got a dict or list, serialize it consistently
        if isinstance(unwrapped, (dict, list)):
            return json.dumps(unwrapped, sort_keys=True, ensure_ascii=False)

        # If it's still a string (non-JSON content), return as-is
        return str(unwrapped)
    except (json.JSONDecodeError, TypeError):
        return json_str  # Return as-is if not valid JSON


@router.put("/api/projects/{project_id}/revisions/latest", response_model=RevisionResponse)
def update_latest_revision(
    project_id: int,
    request: RevisionUpdate,
    db: Session = Depends(get_db)
):
    """Smart save for project revision.

    Behavior:
    - If content is different from latest revision, create NEW revision
    - If content is identical, return existing revision without changes

    Specification: docs/req.txt section 4.4.3 - 保存ボタン (enhanced)
    Phase 2
    """
    # Get latest revision
    latest = db.query(ProjectRevision).filter(
        ProjectRevision.project_id == project_id
    ).order_by(ProjectRevision.revision.desc()).first()

    if not latest:
        raise HTTPException(status_code=404, detail="No revision found for this project")

    # Determine new values (use existing if not provided)
    new_prompt = request.prompt_template if request.prompt_template else latest.prompt_template
    new_parser = request.parser_config if request.parser_config else latest.parser_config

    # Normalize parser configs for comparison (handles double-encoding and formatting differences)
    normalized_new_parser = normalize_json_for_comparison(new_parser or "")
    normalized_existing_parser = normalize_json_for_comparison(latest.parser_config or "")

    # Check if there are any changes
    # For prompt: direct string comparison
    has_prompt_change = new_prompt != latest.prompt_template

    # For parser: compare normalized versions
    has_parser_change = normalized_new_parser != normalized_existing_parser

    if not has_prompt_change and not has_parser_change:
        # No changes - return existing revision
        return RevisionResponse(
            id=latest.id,
            project_id=latest.project_id,
            revision=latest.revision,
            prompt_template=latest.prompt_template,
            parser_config=latest.parser_config or "",
            created_at=latest.created_at,
            is_new=False
        )

    # Changes detected - create new revision
    # Store the normalized parser config to prevent double-encoding
    parser_to_store = normalized_new_parser if normalized_new_parser else (
        normalized_existing_parser if normalized_existing_parser else ""
    )

    new_revision = ProjectRevision(
        project_id=project_id,
        revision=latest.revision + 1,
        prompt_template=new_prompt,
        parser_config=parser_to_store
    )
    db.add(new_revision)
    db.commit()
    db.refresh(new_revision)

    return RevisionResponse(
        id=new_revision.id,
        project_id=new_revision.project_id,
        revision=new_revision.revision,
        prompt_template=new_revision.prompt_template,
        parser_config=new_revision.parser_config or "",
        created_at=new_revision.created_at,
        is_new=True
    )


@router.get("/api/projects/{project_id}/jobs", response_model=List[JobResponse])
def get_project_jobs(project_id: int, limit: int = 50, offset: int = 0, job_type: str = None, db: Session = Depends(get_db)):
    """Get job history for a specific project.

    Args:
        project_id: ID of the project
        limit: Maximum number of jobs to return (default 50)
        offset: Number of jobs to skip (default 0, for pagination)
        job_type: Filter by job type ('single' or 'batch'). If None, returns all.

    Returns:
        List of jobs with their items, ordered by creation time (newest first)

    Phase 2: Support for multiple projects with job history
    NEW ARCHITECTURE: Also includes jobs created with prompt_revision_id
    """
    from sqlalchemy import or_, and_

    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get all project revision IDs (old architecture)
    project_revisions = db.query(ProjectRevision).filter(
        ProjectRevision.project_id == project_id
    ).all()
    project_revision_ids = [r.id for r in project_revisions]

    # Get all prompt revision IDs for prompts in this project (new architecture)
    prompts = db.query(Prompt).filter(Prompt.project_id == project_id).all()
    prompt_ids = [p.id for p in prompts]

    prompt_revision_ids = []
    if prompt_ids:
        prompt_revisions = db.query(PromptRevision).filter(
            PromptRevision.prompt_id.in_(prompt_ids)
        ).all()
        prompt_revision_ids = [pr.id for pr in prompt_revisions]

    # Build filter conditions
    conditions = []
    if project_revision_ids:
        conditions.append(Job.project_revision_id.in_(project_revision_ids))
    if prompt_revision_ids:
        conditions.append(Job.prompt_revision_id.in_(prompt_revision_ids))

    # If no revisions at all, return empty
    if not conditions:
        return []

    # Build the main filter
    main_filter = or_(*conditions)

    # Add job_type filter if specified
    if job_type in ('single', 'batch'):
        main_filter = and_(main_filter, Job.job_type == job_type)

    # Get recent jobs matching the conditions
    recent_jobs_data = db.query(Job).filter(
        main_filter
    ).order_by(Job.created_at.desc()).offset(offset).limit(limit).all()

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

        # Get prompt name from prompt_revision relationship
        prompt_name = None
        if job.prompt_revision_id:
            prompt_revision = db.query(PromptRevision).filter(
                PromptRevision.id == job.prompt_revision_id
            ).first()
            if prompt_revision:
                prompt = db.query(Prompt).filter(Prompt.id == prompt_revision.prompt_id).first()
                if prompt:
                    prompt_name = prompt.name

        recent_jobs.append(JobResponse(
            id=job.id,
            job_type=job.job_type,
            status=job.status,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            turnaround_ms=job.turnaround_ms,
            merged_csv_output=job.merged_csv_output,
            model_name=job.model_name,
            prompt_name=prompt_name,
            items=items
        ))

    return recent_jobs

"""Prompt management API endpoints.

NEW ARCHITECTURE (v3.0): A project can have multiple prompts.
Each prompt has its own revisions (versions).
"""

import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from backend.database import get_db, Project, Prompt, PromptRevision, Workflow, WorkflowStep
from backend.parser import create_default_parser_config
from backend.prompt import PromptTemplateParser
from app.schemas.responses import ParameterDefinitionResponse

router = APIRouter()


# ========== Request/Response Models ==========

class PromptCreate(BaseModel):
    """Request to create new prompt."""
    name: str
    description: str = ""
    prompt_template: str = ""
    parser_config: str = ""


class PromptUpdate(BaseModel):
    """Request to update prompt metadata."""
    name: Optional[str] = None
    description: Optional[str] = None


class PromptRevisionCreate(BaseModel):
    """Request to create new prompt revision."""
    prompt_template: str = ""
    parser_config: str = ""


class PromptRevisionUpdate(BaseModel):
    """Request to update existing prompt revision."""
    prompt_template: str = ""
    parser_config: str = ""


class PromptCloneRequest(BaseModel):
    """Request to clone a prompt."""
    new_name: str
    copy_revisions: bool = True  # If True, copy all revisions; if False, only copy latest


class PromptRevisionResponse(BaseModel):
    """Prompt revision response model."""
    id: int
    prompt_id: int
    revision: int
    prompt_template: str
    parser_config: str
    created_at: str
    is_new: bool = False


class PromptResponse(BaseModel):
    """Prompt response model."""
    id: int
    project_id: int
    name: str
    description: str
    is_deleted: bool = False
    deleted_at: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None
    revision_count: int = 0
    prompt_template: str = ""
    parser_config: str = ""
    parameters: List[ParameterDefinitionResponse] = []
    is_new: bool = False  # True if prompt has no revisions yet


class ProjectPromptsWorkflowsResponse(BaseModel):
    """Response model for project's prompts and workflows."""
    project_id: int
    project_name: str
    prompts: List[PromptResponse] = []
    workflows: List[dict] = []


# ========== Helper Functions ==========

def unwrap_json_string(value):
    """Recursively unwrap a JSON value until we get a dict/list or non-JSON string."""
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    try:
        parsed = json.loads(value)
        if isinstance(parsed, str):
            return unwrap_json_string(parsed)
        return parsed
    except (json.JSONDecodeError, TypeError):
        return value


def normalize_json_for_comparison(json_str: str) -> str:
    """Normalize JSON string for comparison by parsing and re-serializing."""
    if not json_str or not json_str.strip():
        return ""
    try:
        unwrapped = unwrap_json_string(json_str)
        if isinstance(unwrapped, (dict, list)):
            return json.dumps(unwrapped, sort_keys=True, ensure_ascii=False)
        return str(unwrapped)
    except (json.JSONDecodeError, TypeError):
        return json_str


def _prompt_to_response(prompt: Prompt, db: Session, include_parameters: bool = False) -> PromptResponse:
    """Convert Prompt model to response."""
    revision_count = db.query(PromptRevision).filter(
        PromptRevision.prompt_id == prompt.id
    ).count()

    latest_revision = db.query(PromptRevision).filter(
        PromptRevision.prompt_id == prompt.id
    ).order_by(PromptRevision.revision.desc()).first()

    parameters = []
    if include_parameters and latest_revision:
        parser = PromptTemplateParser()
        param_defs = parser.parse_template(latest_revision.prompt_template)
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

    # Prompt is "new" if it has no revisions yet
    is_new = revision_count == 0

    return PromptResponse(
        id=prompt.id,
        project_id=prompt.project_id,
        name=prompt.name,
        description=prompt.description or "",
        is_deleted=bool(prompt.is_deleted),
        deleted_at=prompt.deleted_at,
        created_at=prompt.created_at,
        updated_at=prompt.updated_at,
        revision_count=revision_count,
        prompt_template=latest_revision.prompt_template if latest_revision else "",
        parser_config=latest_revision.parser_config if latest_revision else "",
        parameters=parameters,
        is_new=is_new  # True if no revisions exist yet
    )


# ========== Prompt CRUD Endpoints ==========

@router.get("/api/projects/{project_id}/prompts", response_model=List[PromptResponse])
def list_prompts(
    project_id: int,
    include_deleted: bool = False,
    db: Session = Depends(get_db)
):
    """List all prompts for a project.

    Args:
        project_id: The project ID
        include_deleted: If True, include soft-deleted prompts (for workflow editing)
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    query = db.query(Prompt).filter(Prompt.project_id == project_id)

    if not include_deleted:
        query = query.filter(Prompt.is_deleted == 0)

    prompts = query.order_by(Prompt.created_at.asc()).all()

    return [_prompt_to_response(p, db, include_parameters=False) for p in prompts]


@router.post("/api/projects/{project_id}/prompts", response_model=PromptResponse)
def create_prompt(
    project_id: int,
    request: PromptCreate,
    db: Session = Depends(get_db)
):
    """Create new prompt within a project.

    NEW: Prompt is created without an initial revision.
    First save will create revision 1.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    now = datetime.utcnow().isoformat()
    prompt = Prompt(
        project_id=project_id,
        name=request.name,
        description=request.description,
        created_at=now,
        updated_at=now
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)

    # Store initial template/parser in a temporary way for the response
    # but do NOT create a revision - first explicit save will create revision 1
    initial_template = request.prompt_template or "プロンプトを入力してください / Enter your prompt here"
    parser_config = request.parser_config or create_default_parser_config()

    # Return response with the initial template (even though no revision exists yet)
    # The UI will show revision_count=0 and "新規 / New"
    return PromptResponse(
        id=prompt.id,
        project_id=prompt.project_id,
        name=prompt.name,
        description=prompt.description or "",
        created_at=prompt.created_at,
        revision_count=0,  # No revisions yet
        prompt_template=initial_template,  # For UI display
        parser_config=normalize_json_for_comparison(parser_config) or parser_config,
        parameters=[],  # No parameters yet since no revision
        is_new=True  # Flag to indicate this is a brand new prompt
    )


class PromptWorkflowListItem(BaseModel):
    """Simple list item for prompts/workflows."""
    id: int
    name: str
    type: str  # "prompt" or "workflow"


@router.get("/api/prompts", response_model=List[PromptWorkflowListItem])
def list_prompts_and_workflows(
    project_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """List prompts and workflows, optionally filtered by project_id."""
    result = []

    from sqlalchemy import or_

    # Get prompts (filter deleted prompts and prompts from deleted projects)
    prompt_query = db.query(Prompt).filter(Prompt.is_deleted == 0)
    prompt_query = prompt_query.outerjoin(Project, Prompt.project_id == Project.id)
    prompt_query = prompt_query.filter(Project.is_deleted == 0)
    if project_id:
        prompt_query = prompt_query.filter(Prompt.project_id == project_id)
    prompts = prompt_query.order_by(Prompt.name).all()

    for p in prompts:
        result.append(PromptWorkflowListItem(
            id=p.id,
            name=p.name,
            type="prompt"
        ))

    # Get workflows (filter deleted workflows and workflows with deleted parent project)
    workflow_query = db.query(Workflow).filter(Workflow.is_deleted == 0)
    workflow_query = workflow_query.outerjoin(Project, Workflow.project_id == Project.id)
    workflow_query = workflow_query.filter(
        or_(Workflow.project_id == None, Project.is_deleted == 0)
    )
    if project_id:
        workflow_query = workflow_query.filter(Workflow.project_id == project_id)
    workflows = workflow_query.order_by(Workflow.name).all()

    for w in workflows:
        result.append(PromptWorkflowListItem(
            id=w.id,
            name=f"[WF] {w.name}",
            type="workflow"
        ))

    return result


@router.get("/api/prompts/{prompt_id}", response_model=PromptResponse)
def get_prompt(prompt_id: int, db: Session = Depends(get_db)):
    """Get prompt details with parameters."""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    return _prompt_to_response(prompt, db, include_parameters=True)


@router.put("/api/prompts/{prompt_id}", response_model=PromptResponse)
def update_prompt(
    prompt_id: int,
    request: PromptUpdate,
    db: Session = Depends(get_db)
):
    """Update prompt metadata."""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    if request.name is not None:
        prompt.name = request.name
    if request.description is not None:
        prompt.description = request.description

    prompt.updated_at = datetime.utcnow().isoformat()
    db.commit()
    db.refresh(prompt)

    return _prompt_to_response(prompt, db, include_parameters=False)


class PromptUsageResponse(BaseModel):
    """Response for prompt usage check."""
    prompt_id: int
    prompt_name: str
    is_used: bool
    workflow_count: int
    workflows: List[dict] = []


@router.get("/api/prompts/{prompt_id}/usage", response_model=PromptUsageResponse)
def check_prompt_usage(prompt_id: int, db: Session = Depends(get_db)):
    """Check if a prompt is used in any workflows."""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # Find all workflow steps that use this prompt
    steps = db.query(WorkflowStep).filter(
        WorkflowStep.prompt_id == prompt_id
    ).all()

    # Get unique workflows
    workflow_ids = set(step.workflow_id for step in steps)
    workflows = db.query(Workflow).filter(Workflow.id.in_(workflow_ids)).all() if workflow_ids else []

    workflow_list = []
    for wf in workflows:
        # Find which steps in this workflow use the prompt
        step_names = [step.step_name for step in steps if step.workflow_id == wf.id]
        workflow_list.append({
            "id": wf.id,
            "name": wf.name,
            "step_names": step_names
        })

    return PromptUsageResponse(
        prompt_id=prompt_id,
        prompt_name=prompt.name,
        is_used=len(workflows) > 0,
        workflow_count=len(workflows),
        workflows=workflow_list
    )


@router.post("/api/prompts/{prompt_id}/clone", response_model=PromptResponse)
def clone_prompt(
    prompt_id: int,
    request: PromptCloneRequest,
    db: Session = Depends(get_db)
):
    """Clone a prompt with all its revisions (including parser config).

    Creates a new prompt with the same content as the source prompt.
    """
    source = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Prompt not found")

    if source.is_deleted:
        raise HTTPException(status_code=400, detail="Cannot clone a deleted prompt")

    now = datetime.utcnow().isoformat()

    # Create new prompt
    new_prompt = Prompt(
        project_id=source.project_id,
        name=request.new_name,
        description=source.description,
        created_at=now,
        updated_at=now
    )
    db.add(new_prompt)
    db.flush()  # Get the ID

    # Copy revisions
    source_revisions = db.query(PromptRevision).filter(
        PromptRevision.prompt_id == prompt_id
    ).order_by(PromptRevision.revision).all()

    if source_revisions:
        if request.copy_revisions:
            # Copy all revisions, resetting revision numbers from 1
            for i, rev in enumerate(source_revisions, start=1):
                new_rev = PromptRevision(
                    prompt_id=new_prompt.id,
                    revision=i,
                    prompt_template=rev.prompt_template,
                    parser_config=rev.parser_config,
                    created_at=now
                )
                db.add(new_rev)
        else:
            # Copy only the latest revision as revision 1
            latest = source_revisions[-1]
            new_rev = PromptRevision(
                prompt_id=new_prompt.id,
                revision=1,
                prompt_template=latest.prompt_template,
                parser_config=latest.parser_config,
                created_at=now
            )
            db.add(new_rev)

    db.commit()
    db.refresh(new_prompt)

    return _prompt_to_response(new_prompt, db, include_parameters=True)


@router.delete("/api/prompts/{prompt_id}")
def delete_prompt(prompt_id: int, db: Session = Depends(get_db)):
    """Soft delete a prompt.

    The prompt is marked as deleted but remains in the database.
    Workflows using this prompt will continue to work.
    """
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # Already deleted?
    if prompt.is_deleted:
        raise HTTPException(status_code=400, detail="Prompt is already deleted")

    # Check if this is the last active prompt in the project
    active_prompt_count = db.query(Prompt).filter(
        Prompt.project_id == prompt.project_id,
        Prompt.is_deleted == 0
    ).count()
    if active_prompt_count <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the last prompt in a project"
        )

    # Soft delete: mark as deleted instead of physical delete
    prompt.is_deleted = 1
    prompt.deleted_at = datetime.utcnow().isoformat()
    db.commit()

    return {"success": True, "message": f"Prompt {prompt_id} deleted"}


# ========== Prompt Revision Endpoints ==========

@router.get("/api/prompts/{prompt_id}/revisions", response_model=List[PromptRevisionResponse])
def list_prompt_revisions(prompt_id: int, db: Session = Depends(get_db)):
    """List all revisions for a prompt."""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    revisions = db.query(PromptRevision).filter(
        PromptRevision.prompt_id == prompt_id
    ).order_by(PromptRevision.revision.desc()).all()

    return [
        PromptRevisionResponse(
            id=rev.id,
            prompt_id=rev.prompt_id,
            revision=rev.revision,
            prompt_template=rev.prompt_template,
            parser_config=rev.parser_config or "",
            created_at=rev.created_at
        )
        for rev in revisions
    ]


@router.post("/api/prompts/{prompt_id}/revisions", response_model=PromptRevisionResponse)
def create_prompt_revision(
    prompt_id: int,
    request: PromptRevisionCreate,
    db: Session = Depends(get_db)
):
    """Create new revision for a prompt."""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    latest = db.query(PromptRevision).filter(
        PromptRevision.prompt_id == prompt_id
    ).order_by(PromptRevision.revision.desc()).first()

    next_revision = (latest.revision + 1) if latest else 1

    parser_config = request.parser_config or create_default_parser_config()
    normalized_parser = normalize_json_for_comparison(parser_config)

    revision = PromptRevision(
        prompt_id=prompt_id,
        revision=next_revision,
        prompt_template=request.prompt_template,
        parser_config=normalized_parser if normalized_parser else parser_config,
        created_at=datetime.utcnow().isoformat()
    )
    db.add(revision)
    db.commit()
    db.refresh(revision)

    # Update prompt's updated_at
    prompt.updated_at = datetime.utcnow().isoformat()
    db.commit()

    return PromptRevisionResponse(
        id=revision.id,
        prompt_id=revision.prompt_id,
        revision=revision.revision,
        prompt_template=revision.prompt_template,
        parser_config=revision.parser_config or "",
        created_at=revision.created_at,
        is_new=True
    )


@router.put("/api/prompts/{prompt_id}/revisions/latest", response_model=PromptRevisionResponse)
def update_latest_prompt_revision(
    prompt_id: int,
    request: PromptRevisionUpdate,
    db: Session = Depends(get_db)
):
    """Smart save for prompt revision.

    - If no revision exists (new prompt), create revision 1
    - If content is different from latest revision, create NEW revision
    - If content is identical, return existing revision without changes
    """
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    latest = db.query(PromptRevision).filter(
        PromptRevision.prompt_id == prompt_id
    ).order_by(PromptRevision.revision.desc()).first()

    now = datetime.utcnow().isoformat()

    # Case 1: No revision exists - this is the first save, create revision 1
    if not latest:
        new_prompt_template = request.prompt_template or "プロンプトを入力してください / Enter your prompt here"
        new_parser = request.parser_config or create_default_parser_config()
        normalized_parser = normalize_json_for_comparison(new_parser or "")

        new_revision = PromptRevision(
            prompt_id=prompt_id,
            revision=1,  # First revision
            prompt_template=new_prompt_template,
            parser_config=normalized_parser if normalized_parser else new_parser,
            created_at=now
        )
        db.add(new_revision)

        # Update prompt's updated_at
        prompt.updated_at = now

        db.commit()
        db.refresh(new_revision)

        return PromptRevisionResponse(
            id=new_revision.id,
            prompt_id=new_revision.prompt_id,
            revision=new_revision.revision,
            prompt_template=new_revision.prompt_template,
            parser_config=new_revision.parser_config or "",
            created_at=new_revision.created_at,
            is_new=True
        )

    # Case 2: Revision exists - compare and decide whether to create new revision
    new_prompt_template = request.prompt_template if request.prompt_template else latest.prompt_template
    new_parser = request.parser_config if request.parser_config else latest.parser_config

    # Normalize for comparison
    normalized_new_parser = normalize_json_for_comparison(new_parser or "")
    normalized_existing_parser = normalize_json_for_comparison(latest.parser_config or "")

    has_prompt_change = new_prompt_template != latest.prompt_template
    has_parser_change = normalized_new_parser != normalized_existing_parser

    if not has_prompt_change and not has_parser_change:
        return PromptRevisionResponse(
            id=latest.id,
            prompt_id=latest.prompt_id,
            revision=latest.revision,
            prompt_template=latest.prompt_template,
            parser_config=latest.parser_config or "",
            created_at=latest.created_at,
            is_new=False
        )

    # Create new revision
    parser_to_store = normalized_new_parser if normalized_new_parser else normalized_existing_parser

    new_revision = PromptRevision(
        prompt_id=prompt_id,
        revision=latest.revision + 1,
        prompt_template=new_prompt_template,
        parser_config=parser_to_store,
        created_at=now
    )
    db.add(new_revision)

    # Update prompt's updated_at
    prompt.updated_at = now

    db.commit()
    db.refresh(new_revision)

    return PromptRevisionResponse(
        id=new_revision.id,
        prompt_id=new_revision.prompt_id,
        revision=new_revision.revision,
        prompt_template=new_revision.prompt_template,
        parser_config=new_revision.parser_config or "",
        created_at=new_revision.created_at,
        is_new=True
    )


@router.post("/api/prompts/{prompt_id}/revisions/{revision_number}/restore", response_model=PromptRevisionResponse)
def restore_prompt_revision(
    prompt_id: int,
    revision_number: int,
    db: Session = Depends(get_db)
):
    """Restore a past revision by creating a new revision with its content."""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    target_revision = db.query(PromptRevision).filter(
        PromptRevision.prompt_id == prompt_id,
        PromptRevision.revision == revision_number
    ).first()

    if not target_revision:
        raise HTTPException(
            status_code=404,
            detail=f"Revision {revision_number} not found for this prompt"
        )

    latest = db.query(PromptRevision).filter(
        PromptRevision.prompt_id == prompt_id
    ).order_by(PromptRevision.revision.desc()).first()

    next_revision = (latest.revision + 1) if latest else 1

    normalized_parser = normalize_json_for_comparison(target_revision.parser_config or "")

    new_revision = PromptRevision(
        prompt_id=prompt_id,
        revision=next_revision,
        prompt_template=target_revision.prompt_template,
        parser_config=normalized_parser if normalized_parser else target_revision.parser_config,
        created_at=datetime.utcnow().isoformat()
    )
    db.add(new_revision)

    prompt.updated_at = datetime.utcnow().isoformat()

    db.commit()
    db.refresh(new_revision)

    return PromptRevisionResponse(
        id=new_revision.id,
        prompt_id=new_revision.prompt_id,
        revision=new_revision.revision,
        prompt_template=new_revision.prompt_template,
        parser_config=new_revision.parser_config or "",
        created_at=new_revision.created_at,
        is_new=True
    )


# ========== Combined Endpoints for UI ==========

@router.get("/api/projects/{project_id}/execution-targets", response_model=ProjectPromptsWorkflowsResponse)
def get_project_execution_targets(
    project_id: int,
    include_deleted: bool = False,
    db: Session = Depends(get_db)
):
    """Get prompts and workflows for a project (used for execution target selection).

    Returns all prompts and workflows belonging to a project,
    used by the UI for the two-step selection (Project -> Prompt/Workflow).

    Args:
        project_id: The project ID
        include_deleted: If True, include soft-deleted prompts (for workflow editing)
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get prompts (exclude deleted unless requested)
    query = db.query(Prompt).filter(Prompt.project_id == project_id)
    if not include_deleted:
        query = query.filter(Prompt.is_deleted == 0)
    prompts = query.order_by(Prompt.created_at.asc()).all()

    prompt_responses = [_prompt_to_response(p, db, include_parameters=True) for p in prompts]

    # Get workflows
    workflows = db.query(Workflow).filter(
        Workflow.project_id == project_id
    ).order_by(Workflow.created_at.desc()).all()

    workflow_list = []
    for wf in workflows:
        workflow_list.append({
            "id": wf.id,
            "name": wf.name,
            "description": wf.description or "",
            "step_count": len(wf.steps) if wf.steps else 0,
            "validated": bool(wf.validated)
        })

    return ProjectPromptsWorkflowsResponse(
        project_id=project_id,
        project_name=project.name,
        prompts=prompt_responses,
        workflows=workflow_list
    )

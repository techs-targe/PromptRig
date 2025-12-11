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

from backend.database import get_db, Project, Prompt, PromptRevision, Workflow
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
    created_at: str
    updated_at: str
    revision_count: int = 0
    prompt_template: str = ""
    parser_config: str = ""
    parameters: List[ParameterDefinitionResponse] = []


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

    return PromptResponse(
        id=prompt.id,
        project_id=prompt.project_id,
        name=prompt.name,
        description=prompt.description or "",
        created_at=prompt.created_at,
        updated_at=prompt.updated_at,
        revision_count=revision_count,
        prompt_template=latest_revision.prompt_template if latest_revision else "",
        parser_config=latest_revision.parser_config if latest_revision else "",
        parameters=parameters
    )


# ========== Prompt CRUD Endpoints ==========

@router.get("/api/projects/{project_id}/prompts", response_model=List[PromptResponse])
def list_prompts(project_id: int, db: Session = Depends(get_db)):
    """List all prompts for a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    prompts = db.query(Prompt).filter(
        Prompt.project_id == project_id
    ).order_by(Prompt.created_at.asc()).all()

    return [_prompt_to_response(p, db, include_parameters=False) for p in prompts]


@router.post("/api/projects/{project_id}/prompts", response_model=PromptResponse)
def create_prompt(
    project_id: int,
    request: PromptCreate,
    db: Session = Depends(get_db)
):
    """Create new prompt within a project."""
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

    # Create initial revision
    initial_template = request.prompt_template or "プロンプトを入力してください / Enter your prompt here"
    parser_config = request.parser_config or create_default_parser_config()

    initial_revision = PromptRevision(
        prompt_id=prompt.id,
        revision=1,
        prompt_template=initial_template,
        parser_config=normalize_json_for_comparison(parser_config) or parser_config,
        created_at=now
    )
    db.add(initial_revision)
    db.commit()
    db.refresh(initial_revision)

    return _prompt_to_response(prompt, db, include_parameters=True)


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


@router.delete("/api/prompts/{prompt_id}")
def delete_prompt(prompt_id: int, db: Session = Depends(get_db)):
    """Delete a prompt."""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # Check if this is the last prompt in the project
    prompt_count = db.query(Prompt).filter(Prompt.project_id == prompt.project_id).count()
    if prompt_count <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the last prompt in a project"
        )

    db.delete(prompt)
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

    - If content is different from latest revision, create NEW revision
    - If content is identical, return existing revision without changes
    """
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    latest = db.query(PromptRevision).filter(
        PromptRevision.prompt_id == prompt_id
    ).order_by(PromptRevision.revision.desc()).first()

    if not latest:
        raise HTTPException(status_code=404, detail="No revision found for this prompt")

    # Determine new values
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
        created_at=datetime.utcnow().isoformat()
    )
    db.add(new_revision)

    # Update prompt's updated_at
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
def get_project_execution_targets(project_id: int, db: Session = Depends(get_db)):
    """Get prompts and workflows for a project (used for execution target selection).

    Returns all prompts and workflows belonging to a project,
    used by the UI for the two-step selection (Project -> Prompt/Workflow).
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get prompts
    prompts = db.query(Prompt).filter(
        Prompt.project_id == project_id
    ).order_by(Prompt.created_at.asc()).all()

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
            "step_count": len(wf.steps) if wf.steps else 0
        })

    return ProjectPromptsWorkflowsResponse(
        project_id=project_id,
        project_name=project.name,
        prompts=prompt_responses,
        workflows=workflow_list
    )

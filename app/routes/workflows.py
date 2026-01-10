"""Workflow management API endpoints.

Provides CRUD operations for workflows and workflow execution.
"""

import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Dict, Optional, Any

from backend.database import get_db, SessionLocal, Workflow, WorkflowStep, WorkflowJob, Project, Prompt, Dataset
from backend.workflow import WorkflowManager
from backend.workflow_validator import validate_workflow, get_available_variables_at_step, get_dataset_columns

router = APIRouter()


# ========== Request/Response Models ==========

class WorkflowStepCreate(BaseModel):
    """Request model for creating a workflow step."""
    step_name: str
    step_type: str = "prompt"  # prompt/set/if/elif/else/endif/loop/endloop/foreach/endforeach/break/continue
    project_id: Optional[int] = None  # Optional for non-prompt steps
    prompt_id: Optional[int] = None
    step_order: Optional[int] = None
    input_mapping: Optional[Dict[str, str]] = None
    condition_config: Optional[Dict[str, Any]] = None  # Control flow configuration
    execution_mode: str = "sequential"


class WorkflowStepUpdate(BaseModel):
    """Request model for updating a workflow step."""
    step_name: Optional[str] = None
    step_type: Optional[str] = None  # prompt/set/if/elif/else/endif/loop/endloop/foreach/endforeach/break/continue
    project_id: Optional[int] = None
    prompt_id: Optional[int] = None
    step_order: Optional[int] = None
    input_mapping: Optional[Dict[str, str]] = None
    condition_config: Optional[Dict[str, Any]] = None  # Control flow configuration


class WorkflowCreate(BaseModel):
    """Request model for creating a workflow."""
    name: str
    description: str = ""
    project_id: Optional[int] = None
    auto_context: bool = False  # Auto-generate CONTEXT from previous steps
    steps: List[WorkflowStepCreate] = []


class WorkflowUpdate(BaseModel):
    """Request model for updating a workflow."""
    name: Optional[str] = None
    description: Optional[str] = None
    project_id: Optional[int] = None
    auto_context: Optional[bool] = None  # Auto-generate CONTEXT from previous steps


class WorkflowStepResponse(BaseModel):
    """Response model for a workflow step."""
    id: int
    step_order: int
    step_name: str
    step_type: str = "prompt"  # prompt/set/if/elif/else/endif/loop/endloop/foreach/endforeach/break/continue
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    prompt_id: Optional[int] = None
    prompt_name: Optional[str] = None
    execution_mode: str
    input_mapping: Optional[Dict[str, Any]] = None  # Can contain nested dicts for 'set' steps
    condition_config: Optional[Dict[str, Any]] = None  # Control flow configuration


class WorkflowResponse(BaseModel):
    """Response model for a workflow."""
    id: int
    name: str
    description: str
    project_id: Optional[int] = None
    auto_context: bool = False  # Auto-generate CONTEXT from previous steps
    validated: bool = False  # True if workflow passed validation (0 errors)
    created_at: str
    updated_at: str
    steps: List[WorkflowStepResponse] = []


class WorkflowJobStepResponse(BaseModel):
    """Response model for a workflow job step result."""
    id: int
    step_name: str
    step_order: int
    status: str
    input_params: Optional[Dict[str, Any]] = None
    output_fields: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    turnaround_ms: Optional[int] = None


class WorkflowJobResponse(BaseModel):
    """Response model for a workflow job."""
    id: int
    workflow_id: int
    workflow_name: str
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    status: str
    input_params: Optional[Dict[str, Any]] = None
    merged_output: Optional[Dict[str, Any]] = None
    merged_csv_output: Optional[str] = None  # CSV output merged from all steps
    model_name: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    turnaround_ms: Optional[int] = None
    step_results: List[WorkflowJobStepResponse] = []


class RunWorkflowRequest(BaseModel):
    """Request model for running a workflow."""
    input_params: Dict[str, str]
    model_name: Optional[str] = None
    temperature: float = 0.7


# ========== Helper Functions ==========

def _workflow_to_response(workflow: Workflow, db: Session) -> WorkflowResponse:
    """Convert Workflow model to response."""
    return WorkflowResponse(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description or "",
        project_id=workflow.project_id,
        auto_context=bool(workflow.auto_context),
        validated=bool(workflow.validated),
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
        steps=[_step_to_response(s, db) for s in workflow.steps]
    )


def _step_to_response(step: WorkflowStep, db: Session) -> WorkflowStepResponse:
    """Convert WorkflowStep model to response."""
    prompt = db.query(Prompt).filter(Prompt.id == step.prompt_id).first() if step.prompt_id else None

    # Determine project_id: use step's project_id, or derive from prompt if not set
    effective_project_id = step.project_id
    if not effective_project_id and prompt and prompt.project_id:
        effective_project_id = prompt.project_id

    project = db.query(Project).filter(Project.id == effective_project_id).first() if effective_project_id else None

    input_mapping = None
    if step.input_mapping:
        try:
            input_mapping = json.loads(step.input_mapping)
        except:
            pass
    condition_config = None
    if step.condition_config:
        try:
            condition_config = json.loads(step.condition_config)
        except:
            pass
    return WorkflowStepResponse(
        id=step.id,
        step_order=step.step_order,
        step_name=step.step_name,
        step_type=step.step_type or "prompt",
        project_id=effective_project_id,
        project_name=project.name if project else None,
        prompt_id=step.prompt_id,
        prompt_name=prompt.name if prompt else None,
        execution_mode=step.execution_mode,
        input_mapping=input_mapping,
        condition_config=condition_config
    )


def _job_to_response(job: WorkflowJob, db: Session) -> WorkflowJobResponse:
    """Convert WorkflowJob model to response."""
    workflow = db.query(Workflow).filter(Workflow.id == job.workflow_id).first()

    # Get project info from workflow
    project_id = None
    project_name = None
    if workflow and workflow.project_id:
        project_id = workflow.project_id
        project = db.query(Project).filter(Project.id == workflow.project_id).first()
        if project:
            project_name = project.name

    step_results = []
    for step_result in job.step_results:
        step = step_result.workflow_step
        step_results.append(WorkflowJobStepResponse(
            id=step_result.id,
            step_name=step.step_name if step else f"step{step_result.step_order}",
            step_order=step_result.step_order,
            status=step_result.status,
            input_params=json.loads(step_result.input_params) if step_result.input_params else None,
            output_fields=json.loads(step_result.output_fields) if step_result.output_fields else None,
            error_message=step_result.error_message,
            turnaround_ms=step_result.turnaround_ms
        ))

    return WorkflowJobResponse(
        id=job.id,
        workflow_id=job.workflow_id,
        workflow_name=workflow.name if workflow else "Unknown",
        project_id=project_id,
        project_name=project_name,
        status=job.status,
        input_params=json.loads(job.input_params) if job.input_params else None,
        merged_output=json.loads(job.merged_output) if job.merged_output else None,
        merged_csv_output=job.merged_csv_output,
        model_name=job.model_name,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        turnaround_ms=job.turnaround_ms,
        step_results=step_results
    )


# ========== Background Execution ==========

def execute_workflow_background(
    workflow_job_id: int,
    workflow_id: int,
    input_params: Dict[str, str],
    model_name: str = None,
    temperature: float = 0.7
):
    """Execute workflow in background task."""
    db = SessionLocal()
    try:
        manager = WorkflowManager(db)

        # Execute workflow with existing job ID
        manager.execute_workflow(
            workflow_id,
            input_params,
            model_name,
            temperature,
            workflow_job_id=workflow_job_id
        )
    except Exception as e:
        # Update job with error
        job = db.query(WorkflowJob).filter(WorkflowJob.id == workflow_job_id).first()
        if job:
            job.status = "error"
            job.merged_output = json.dumps({"_error": str(e)}, ensure_ascii=False)
            job.finished_at = datetime.utcnow().isoformat()
            db.commit()
    finally:
        db.close()


# ========== Workflow CRUD Endpoints ==========

@router.get("/api/workflows", response_model=List[WorkflowResponse])
def list_workflows(project_id: Optional[int] = None, db: Session = Depends(get_db)):
    """List workflows, optionally filtered by project.

    Excludes soft-deleted workflows and workflows whose parent project is deleted.
    """
    from sqlalchemy import or_

    query = db.query(Workflow).filter(Workflow.is_deleted == 0)

    # Exclude workflows whose parent project is deleted
    query = query.outerjoin(Project, Workflow.project_id == Project.id)
    query = query.filter(
        or_(Workflow.project_id == None, Project.is_deleted == 0)
    )

    if project_id is not None:
        query = query.filter(Workflow.project_id == project_id)
    workflows = query.order_by(Workflow.created_at.desc()).all()
    return [_workflow_to_response(w, db) for w in workflows]


@router.post("/api/workflows", response_model=WorkflowResponse)
def create_workflow(request: WorkflowCreate, db: Session = Depends(get_db)):
    """Create a new workflow with steps.

    Validates the workflow after creation. If validation fails with errors,
    the workflow is rolled back and not saved.
    """
    try:
        manager = WorkflowManager(db)
        workflow = manager.create_workflow(
            request.name,
            request.description,
            request.project_id,
            auto_context=request.auto_context
        )

        for step_data in request.steps:
            manager.add_step(
                workflow_id=workflow.id,
                step_name=step_data.step_name,
                project_id=step_data.project_id,
                prompt_id=step_data.prompt_id,
                step_order=step_data.step_order,
                input_mapping=step_data.input_mapping,
                execution_mode=step_data.execution_mode,
                step_type=step_data.step_type,
                condition_config=step_data.condition_config
            )

        # Validate workflow control flow before final commit (don't update flag yet)
        db.flush()  # Ensure all steps are in DB for validation
        validation = validate_workflow(db, workflow.id, update_flag=False)
        if validation.errors > 0:
            db.rollback()
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Workflow validation failed",
                    "valid": False,
                    "errors": validation.errors,
                    "warnings": validation.warnings,
                    "issues": [issue.to_dict() for issue in validation.issues
                              if issue.severity.value == "error"],
                    "all_issues": [issue.to_dict() for issue in validation.issues]
                }
            )

        # Validation passed - set validated flag and commit
        workflow.validated = 1
        db.commit()
        db.refresh(workflow)
        return _workflow_to_response(workflow, db)

    except HTTPException:
        raise
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create workflow: {str(e)}")


# ========== Workflow Functions Reference API ==========

@router.get("/api/workflows/functions")
async def get_workflow_functions():
    """Get all available workflow functions with documentation.

    Returns function definitions from STRING_FUNCTIONS for use in UI.
    Organized by category for better presentation.
    """
    from backend.workflow import WorkflowManager

    # Get STRING_FUNCTIONS from WorkflowManager
    functions = WorkflowManager.STRING_FUNCTIONS

    # Organize by category
    categories = {
        "text": {
            "name": "文字列操作 / Text Operations",
            "functions": []
        },
        "search": {
            "name": "検索・判定 / Search & Check",
            "functions": []
        },
        "math": {
            "name": "計算 / Math",
            "functions": []
        },
        "json": {
            "name": "JSON処理 / JSON Processing",
            "functions": []
        },
        "dataset": {
            "name": "データセット / Dataset",
            "functions": []
        },
        "datetime": {
            "name": "日時 / Date & Time",
            "functions": []
        },
        "array": {
            "name": "配列 / Array",
            "functions": []
        },
        "utility": {
            "name": "ユーティリティ / Utility",
            "functions": []
        }
    }

    # Categorize functions
    text_funcs = ['upper', 'lower', 'trim', 'lstrip', 'rstrip', 'capitalize', 'title', 'reverse',
                  'length', 'len', 'slice', 'left', 'right', 'replace', 'repeat', 'concat', 'split', 'join']
    search_funcs = ['contains', 'startswith', 'endswith', 'count']
    math_funcs = ['sum', 'calc']
    json_funcs = ['json_parse', 'json_zip', 'format_choices']
    dataset_funcs = ['dataset_filter', 'dataset_join']
    datetime_funcs = ['now', 'today', 'time']
    array_funcs = ['array_push', 'shuffle']
    utility_funcs = ['default', 'ifempty', 'debug', 'getprompt', 'getparser']

    for func_name, func_info in functions.items():
        func_data = {
            "name": func_name,
            "args": func_info.get("args", 1),
            "desc": func_info.get("desc", ""),
            "example": func_info.get("example", f"{func_name}()"),
            "usage": func_info.get("usage", [])
        }

        if func_name in text_funcs:
            categories["text"]["functions"].append(func_data)
        elif func_name in search_funcs:
            categories["search"]["functions"].append(func_data)
        elif func_name in math_funcs:
            categories["math"]["functions"].append(func_data)
        elif func_name in json_funcs:
            categories["json"]["functions"].append(func_data)
        elif func_name in dataset_funcs:
            categories["dataset"]["functions"].append(func_data)
        elif func_name in datetime_funcs:
            categories["datetime"]["functions"].append(func_data)
        elif func_name in array_funcs:
            categories["array"]["functions"].append(func_data)
        else:
            categories["utility"]["functions"].append(func_data)

    # Remove empty categories and sort functions
    result = {}
    for cat_key, cat_data in categories.items():
        if cat_data["functions"]:
            cat_data["functions"].sort(key=lambda x: x["name"])
            result[cat_key] = cat_data

    return {
        "categories": result,
        "total_count": len(functions)
    }


@router.get("/api/workflows/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(workflow_id: int, db: Session = Depends(get_db)):
    """Get workflow details."""
    workflow = db.query(Workflow).filter(
        Workflow.id == workflow_id,
        Workflow.is_deleted != 1  # Exclude soft-deleted workflows
    ).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _workflow_to_response(workflow, db)


class ValidationResponse(BaseModel):
    """Response model for workflow validation."""
    valid: bool
    workflow_id: int
    workflow_name: str
    errors: int
    warnings: int
    info: int
    issues: List[Dict[str, Any]]
    summary: str


@router.get("/api/workflows/{workflow_id}/validate", response_model=ValidationResponse)
def validate_workflow_endpoint(workflow_id: int, db: Session = Depends(get_db)):
    """Validate a workflow and return detailed validation results.

    Checks for:
    - Control flow integrity (IF/ENDIF, LOOP/ENDLOOP, FOREACH/ENDFOREACH pairs)
    - Formula/function syntax validation
    - Variable and step reference validation
    - Required parameter and configuration validation
    - Prompt step configuration
    - Input parameter usage

    Returns validation result with any errors or warnings found.
    """
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    validation = validate_workflow(db, workflow_id)

    return ValidationResponse(
        valid=validation.valid,
        workflow_id=validation.workflow_id,
        workflow_name=validation.workflow_name,
        errors=validation.errors,
        warnings=validation.warnings,
        info=validation.info,
        issues=[issue.to_dict() for issue in validation.issues],
        summary=validation.get_summary()
    )


@router.get("/api/workflows/{workflow_id}/steps/{step_order}/available-variables")
def get_step_available_variables(
    workflow_id: int,
    step_order: int,
    db: Session = Depends(get_db)
):
    """Get all available variables and functions at a specific workflow step.

    Returns variables that can be used in this step's input_mapping or condition_config:
    - Initial input variables
    - SET variables defined before this step
    - FOREACH item_var and index_var (if inside a FOREACH loop)
    - Dataset columns (if FOREACH uses a dataset source)
    - Previous step outputs (parser fields)
    - Available functions

    This endpoint is useful for:
    - UI variable picker to show context-aware options
    - AI agents building workflow steps

    Args:
        workflow_id: The ID of the workflow
        step_order: The step order (1-based) to get variables for
    """
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    result = get_available_variables_at_step(db, workflow_id, step_order)
    return result


@router.get("/api/datasets/{dataset_id}/columns")
def get_dataset_columns_endpoint(
    dataset_id: int,
    db: Session = Depends(get_db)
):
    """Get column names for a dataset.

    Returns a list of column names in the dataset's data table.
    Used by the variable picker to show available columns for FOREACH loops.

    Args:
        dataset_id: The ID of the dataset
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

    columns = get_dataset_columns(db, dataset_id)
    return {
        "dataset_id": dataset_id,
        "dataset_name": dataset.name,
        "columns": columns
    }


class WorkflowJsonValidationRequest(BaseModel):
    """Request model for validating workflow JSON without saving."""
    workflow_json: Dict[str, Any]
    workflow_id: Optional[int] = None  # Optional: existing workflow ID for context


@router.post("/api/workflows/validate-json", response_model=ValidationResponse)
def validate_workflow_json(request: WorkflowJsonValidationRequest, db: Session = Depends(get_db)):
    """Validate workflow JSON without saving.

    This endpoint validates the workflow structure and configuration
    without persisting changes. Used by the UI to validate current form data.

    For existing workflows, pass workflow_id to provide context for validation.
    For new workflows, omit workflow_id.
    """
    wf_dict = request.workflow_json
    workflow_id = request.workflow_id

    # Create temporary in-memory workflow structure for validation
    # We need to temporarily insert into DB for the validator to work
    from datetime import datetime

    try:
        # Create temporary workflow
        temp_workflow = Workflow(
            name=wf_dict.get("name", "temp_validation"),
            description=wf_dict.get("description", ""),
            project_id=wf_dict.get("project_id"),
            auto_context=1 if wf_dict.get("auto_context") else 0,
            validated=0,
            is_deleted=0,
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat()
        )
        db.add(temp_workflow)
        db.flush()  # Get the ID without committing

        # Create temporary steps
        for step_dict in wf_dict.get("steps", []):
            # Get prompt_id from step (already resolved by client)
            prompt_id = step_dict.get("prompt_id")
            project_id = step_dict.get("project_id")

            # Also support prompt_name resolution (for API compatibility)
            if not prompt_id and step_dict.get("prompt_name"):
                prompt = db.query(Prompt).filter(Prompt.name == step_dict["prompt_name"]).first()
                if prompt:
                    prompt_id = prompt.id

            input_mapping = step_dict.get("input_mapping")
            condition_config = step_dict.get("condition_config")

            step = WorkflowStep(
                workflow_id=temp_workflow.id,
                step_order=step_dict.get("step_order", 0),
                step_name=step_dict.get("step_name", ""),
                step_type=step_dict.get("step_type", "prompt"),
                prompt_id=prompt_id,
                project_id=project_id,
                execution_mode=step_dict.get("execution_mode"),
                input_mapping=json.dumps(input_mapping) if input_mapping else None,
                condition_config=json.dumps(condition_config) if condition_config else None
            )
            db.add(step)

        db.flush()  # Ensure all steps are visible to validator

        # Run validation (don't update flag since we'll rollback)
        validation = validate_workflow(db, temp_workflow.id, update_flag=False)

        # Rollback to discard temporary data
        db.rollback()

        return ValidationResponse(
            valid=validation.valid,
            workflow_id=workflow_id or 0,  # Return original workflow_id if provided
            workflow_name=wf_dict.get("name", ""),
            errors=validation.errors,
            warnings=validation.warnings,
            info=validation.info,
            issues=[issue.to_dict() for issue in validation.issues],
            summary=validation.get_summary()
        )

    except Exception as e:
        db.rollback()
        # Return error as validation issue
        return ValidationResponse(
            valid=False,
            workflow_id=workflow_id or 0,
            workflow_name=wf_dict.get("name", ""),
            errors=1,
            warnings=0,
            info=0,
            issues=[{
                "severity": "error",
                "step_id": None,
                "step_name": None,
                "step_order": None,
                "category": "validation",
                "message": f"Validation error: {str(e)}",
                "message_ja": f"バリデーションエラー: {str(e)}",
                "suggestion": None,
                "suggestion_ja": None
            }],
            summary=f"Validation failed: {str(e)}"
        )


@router.put("/api/workflows/{workflow_id}", response_model=WorkflowResponse)
def update_workflow(
    workflow_id: int,
    request: WorkflowUpdate,
    db: Session = Depends(get_db)
):
    """Update workflow metadata."""
    try:
        manager = WorkflowManager(db)
        workflow = manager.update_workflow(
            workflow_id,
            name=request.name,
            description=request.description,
            project_id=request.project_id,
            auto_context=request.auto_context
        )
        return _workflow_to_response(workflow, db)

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update workflow: {str(e)}")


@router.delete("/api/workflows/{workflow_id}")
def delete_workflow(workflow_id: int, db: Session = Depends(get_db)):
    """Soft delete a workflow (mark as deleted instead of physical removal)."""
    from datetime import datetime

    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    if workflow.is_deleted:
        raise HTTPException(status_code=400, detail="Workflow is already deleted")

    # Soft delete: mark as deleted instead of physical delete
    workflow.is_deleted = 1
    workflow.deleted_at = datetime.utcnow().isoformat()
    workflow.updated_at = datetime.utcnow().isoformat()
    db.commit()

    return {"success": True, "message": f"Workflow {workflow_id} deleted"}


class WorkflowCloneRequest(BaseModel):
    """Request model for cloning a workflow."""
    new_name: str


@router.post("/api/workflows/{workflow_id}/clone", response_model=WorkflowResponse)
def clone_workflow(
    workflow_id: int,
    request: WorkflowCloneRequest,
    db: Session = Depends(get_db)
):
    """Clone a workflow with a new name (Save As).

    Creates a copy of the workflow including all steps.
    """
    # Get source workflow
    source_workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not source_workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    try:
        manager = WorkflowManager(db)

        # Create new workflow with same settings
        new_workflow = manager.create_workflow(
            name=request.new_name,
            description=source_workflow.description,
            project_id=source_workflow.project_id,
            auto_context=source_workflow.auto_context
        )

        # Copy all steps
        for step in source_workflow.steps:
            input_mapping = None
            if step.input_mapping:
                try:
                    input_mapping = json.loads(step.input_mapping)
                except:
                    pass

            condition_config = None
            if step.condition_config:
                try:
                    condition_config = json.loads(step.condition_config)
                except:
                    pass

            manager.add_step(
                workflow_id=new_workflow.id,
                step_name=step.step_name,
                project_id=step.project_id,
                prompt_id=step.prompt_id,
                step_order=step.step_order,
                input_mapping=input_mapping,
                execution_mode=step.execution_mode,
                step_type=step.step_type,
                condition_config=condition_config
            )

        db.refresh(new_workflow)
        return _workflow_to_response(new_workflow, db)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clone workflow: {str(e)}")


# ========== Workflow Step Endpoints ==========

@router.post("/api/workflows/{workflow_id}/steps", response_model=WorkflowStepResponse)
def add_workflow_step(
    workflow_id: int,
    request: WorkflowStepCreate,
    validate: bool = False,
    db: Session = Depends(get_db)
):
    """Add a step to a workflow.

    Args:
        validate: If True, validate the entire workflow after adding the step.
                  If validation fails, the step addition is rolled back.

    Note: Adding a step resets the workflow's validated flag to false.
          Run validate_workflow to re-validate after modifications.
    """
    try:
        # Reset validated flag when modifying steps
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if workflow:
            workflow.validated = 0

        manager = WorkflowManager(db)
        step = manager.add_step(
            workflow_id=workflow_id,
            step_name=request.step_name,
            project_id=request.project_id,
            prompt_id=request.prompt_id,
            step_order=request.step_order,
            input_mapping=request.input_mapping,
            execution_mode=request.execution_mode,
            step_type=request.step_type,
            condition_config=request.condition_config
        )

        # If validate=true, validate entire workflow and rollback on errors
        if validate:
            db.flush()
            validation = validate_workflow(db, workflow_id)
            if validation.errors > 0:
                db.rollback()
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Workflow validation failed",
                        "valid": False,
                        "errors": validation.errors,
                        "warnings": validation.warnings,
                        "issues": [issue.to_dict() for issue in validation.issues
                                  if issue.severity.value == "error"],
                        "all_issues": [issue.to_dict() for issue in validation.issues]
                    }
                )

        return _step_to_response(step, db)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add step: {str(e)}")


@router.put("/api/workflows/{workflow_id}/steps/{step_id}", response_model=WorkflowStepResponse)
def update_workflow_step(
    workflow_id: int,
    step_id: int,
    request: WorkflowStepUpdate,
    db: Session = Depends(get_db)
):
    """Update a workflow step.

    Note: Updating a step resets the workflow's validated flag to false.
          Run validate_workflow to re-validate after modifications.
    """
    try:
        # Verify step belongs to workflow
        step = db.query(WorkflowStep).filter(
            WorkflowStep.id == step_id,
            WorkflowStep.workflow_id == workflow_id
        ).first()
        if not step:
            raise HTTPException(status_code=404, detail="Step not found")

        # Reset validated flag when modifying steps
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if workflow:
            workflow.validated = 0

        manager = WorkflowManager(db)
        updated_step = manager.update_step(
            step_id=step_id,
            step_name=request.step_name,
            project_id=request.project_id,
            prompt_id=request.prompt_id,
            step_order=request.step_order,
            input_mapping=request.input_mapping,
            step_type=request.step_type,
            condition_config=request.condition_config
        )
        return _step_to_response(updated_step, db)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update step: {str(e)}")


@router.delete("/api/workflows/{workflow_id}/steps/{step_id}")
def remove_workflow_step(
    workflow_id: int,
    step_id: int,
    db: Session = Depends(get_db)
):
    """Remove a step from a workflow.

    Note: Removing a step resets the workflow's validated flag to false.
          Run validate_workflow to re-validate after modifications.
    """
    try:
        # Verify step belongs to workflow
        step = db.query(WorkflowStep).filter(
            WorkflowStep.id == step_id,
            WorkflowStep.workflow_id == workflow_id
        ).first()
        if not step:
            raise HTTPException(status_code=404, detail="Step not found")

        # Reset validated flag when modifying steps
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if workflow:
            workflow.validated = 0

        manager = WorkflowManager(db)
        manager.remove_step(step_id)
        return {"success": True}

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to remove step: {str(e)}")


# ========== Workflow Execution Endpoints ==========

@router.post("/api/workflows/{workflow_id}/run", response_model=WorkflowJobResponse)
def run_workflow(
    workflow_id: int,
    request: RunWorkflowRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Execute a workflow asynchronously.

    Requires the workflow to be validated (0 errors) before execution.
    Use GET /api/workflows/{id}/validate to validate the workflow first.
    """
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if not workflow.steps:
        raise HTTPException(status_code=400, detail="Workflow has no steps")

    # Check if workflow is validated
    if not workflow.validated:
        raise HTTPException(
            status_code=422,
            detail="Workflow must be validated before execution. Run validate_workflow first (GET /api/workflows/{id}/validate)."
        )

    try:
        # Create pending job
        workflow_job = WorkflowJob(
            workflow_id=workflow_id,
            status="pending",
            input_params=json.dumps(request.input_params, ensure_ascii=False),
            model_name=request.model_name
        )
        db.add(workflow_job)
        db.commit()
        db.refresh(workflow_job)

        # Execute in background
        background_tasks.add_task(
            execute_workflow_background,
            workflow_job.id,
            workflow_id,
            request.input_params,
            request.model_name,
            request.temperature
        )

        return _job_to_response(workflow_job, db)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start workflow: {str(e)}")


@router.get("/api/workflow-jobs/{job_id}", response_model=WorkflowJobResponse)
def get_workflow_job(job_id: int, db: Session = Depends(get_db)):
    """Get workflow job status and results."""
    job = db.query(WorkflowJob).filter(WorkflowJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Workflow job not found")
    return _job_to_response(job, db)


@router.get("/api/workflows/{workflow_id}/jobs", response_model=List[WorkflowJobResponse])
def list_workflow_jobs(
    workflow_id: int,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """List jobs for a workflow."""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    jobs = db.query(WorkflowJob).filter(
        WorkflowJob.workflow_id == workflow_id
    ).order_by(WorkflowJob.created_at.desc()).limit(limit).all()

    return [_job_to_response(j, db) for j in jobs]


@router.post("/api/workflow-jobs/{job_id}/cancel")
def cancel_workflow_job(job_id: int, db: Session = Depends(get_db)):
    """Cancel a workflow job that is stuck in running/pending state.

    This marks the job as 'cancelled' and is useful for cleaning up
    jobs that were orphaned due to server restart.
    """
    job = db.query(WorkflowJob).filter(WorkflowJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Workflow job not found")

    if job.status not in ["pending", "running"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status '{job.status}'. Only pending/running jobs can be cancelled."
        )

    job.status = "cancelled"
    job.finished_at = datetime.utcnow().isoformat()
    job.merged_output = json.dumps({"_error": "Job cancelled by user"}, ensure_ascii=False)
    db.commit()

    return {"success": True, "message": f"Workflow job {job_id} cancelled"}


# ========== Variable Picker API ==========

class VariableInfo(BaseModel):
    """Variable information for picker."""
    name: str
    variable: str  # e.g., "{{step1.answer}}" or "{{input.query}}"
    type: str  # "input" or "output"
    source: str  # e.g., "初期入力" or "Step 1: summarize"


class VariableCategory(BaseModel):
    """Category of variables."""
    category_id: str
    category_name: str
    variables: List[VariableInfo]


class WorkflowVariablesResponse(BaseModel):
    """Response with available variables for workflow building."""
    categories: List[VariableCategory]


def _extract_template_params(prompt_template: str) -> List[str]:
    """Extract parameter names from prompt template.

    Args:
        prompt_template: Template with {{PARAM}} or {{PARAM:TYPE}} syntax

    Returns:
        List of parameter names
    """
    import re
    # Support Unicode characters (Japanese, etc.) in parameter names
    # \w matches [a-zA-Z0-9_] plus Unicode word characters
    pattern = r'\{\{([\w]+)(?::[A-Z0-9]+)?\}\}'
    matches = re.findall(pattern, prompt_template or "", re.UNICODE)
    # Remove duplicates while preserving order
    seen = set()
    result = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            result.append(m)
    return result


def _extract_parser_fields(parser_config_str: str) -> List[str]:
    """Extract output field names from parser config.

    Args:
        parser_config_str: JSON string with parser configuration

    Returns:
        List of field names that the parser outputs
    """
    if not parser_config_str:
        return []

    try:
        config = parser_config_str
        # Handle multi-level JSON encoding (unwrap until we get a dict)
        max_depth = 5
        while isinstance(config, str) and max_depth > 0:
            try:
                config = json.loads(config)
                max_depth -= 1
            except (json.JSONDecodeError, TypeError):
                break

        # If still not a dict, give up
        if not isinstance(config, dict):
            return []

        parser_type = config.get("type", "none")

        if parser_type == "json_path":
            paths = config.get("paths", {})
            return list(paths.keys())
        elif parser_type == "regex":
            patterns = config.get("patterns", {})
            return list(patterns.keys())
        else:
            return []
    except (json.JSONDecodeError, TypeError, AttributeError):
        return []


@router.get("/api/workflow-variables", response_model=WorkflowVariablesResponse)
def get_workflow_variables(db: Session = Depends(get_db)):
    """Get available variables for workflow building.

    Returns categorized variables:
    - Initial input parameters (from all projects' prompt templates)
    - Output fields from each project's parser (for step references)
    """
    from backend.database import Project, ProjectRevision, Prompt, PromptRevision

    categories = []

    # Category 1: Initial Input (common placeholder)
    initial_vars = [
        VariableInfo(
            name="(入力パラメータ名)",
            variable="{{input.パラメータ名}}",
            type="input",
            source="プロンプトで定義した入力パラメータ"
        )
    ]
    categories.append(VariableCategory(
        category_id="input",
        category_name="初期入力 / Initial Input",
        variables=initial_vars
    ))

    # Get all active prompts with their latest revisions (NEW ARCHITECTURE)
    # Filter out deleted prompts and prompts from deleted projects
    prompts = db.query(Prompt).filter(
        Prompt.is_deleted == 0
    ).outerjoin(Project, Prompt.project_id == Project.id).filter(
        Project.is_deleted == 0
    ).all()

    for prompt in prompts:
        # Get latest revision
        latest_rev = db.query(PromptRevision).filter(
            PromptRevision.prompt_id == prompt.id
        ).order_by(PromptRevision.revision.desc()).first()

        if not latest_rev:
            continue

        # Extract input parameters from prompt template
        input_params = _extract_template_params(latest_rev.prompt_template)

        # Extract output fields from parser config
        output_fields = _extract_parser_fields(latest_rev.parser_config)

        # Create category for this prompt's outputs
        if output_fields:
            vars_list = []
            for field in output_fields:
                vars_list.append(VariableInfo(
                    name=field,
                    variable=f"{{{{ステップ名.{field}}}}}",
                    type="output",
                    source=f"Prompt: {prompt.name}"
                ))

            categories.append(VariableCategory(
                category_id=f"prompt_{prompt.id}",
                category_name=f"📤 {prompt.name} の出力",
                variables=vars_list
            ))

        # Also show input parameters (for reference)
        if input_params:
            input_vars = []
            for param in input_params:
                input_vars.append(VariableInfo(
                    name=param,
                    variable=f"{{{{input.{param}}}}}",
                    type="input",
                    source=f"Prompt: {prompt.name}"
                ))

            # Add to initial input category or create separate
            categories.append(VariableCategory(
                category_id=f"prompt_{prompt.id}_input",
                category_name=f"📥 {prompt.name} の入力パラメータ",
                variables=input_vars
            ))

    # Also check old architecture (ProjectRevision) for backward compatibility
    # Filter out deleted projects
    projects = db.query(Project).filter(Project.is_deleted == 0).all()
    for project in projects:
        latest_rev = db.query(ProjectRevision).filter(
            ProjectRevision.project_id == project.id
        ).order_by(ProjectRevision.revision.desc()).first()

        if not latest_rev:
            continue

        output_fields = _extract_parser_fields(latest_rev.parser_config)

        if output_fields:
            vars_list = []
            for field in output_fields:
                vars_list.append(VariableInfo(
                    name=field,
                    variable=f"{{{{ステップ名.{field}}}}}",
                    type="output",
                    source=f"Project: {project.name} (Legacy)"
                ))

            # Only add if not already covered by Prompt
            existing_ids = [c.category_id for c in categories]
            cat_id = f"project_{project.id}_output"
            if cat_id not in existing_ids:
                categories.append(VariableCategory(
                    category_id=cat_id,
                    category_name=f"📤 {project.name} の出力 (Legacy)",
                    variables=vars_list
                ))

    return WorkflowVariablesResponse(categories=categories)


# ========== String Functions Endpoint ==========

class FunctionInfo(BaseModel):
    """Information about a string function."""
    name: str
    args: str  # Number or range of arguments (e.g., "1", "2", "2-3", "2+")
    description: str
    example: str


@router.get("/functions")
async def get_string_functions():
    """Get available string manipulation functions for workflow formulas.

    Returns a list of all available functions that can be used in
    variable assignments and value fields.
    """
    functions = []

    for func_name, info in WorkflowManager.STRING_FUNCTIONS.items():
        functions.append(FunctionInfo(
            name=func_name,
            args=str(info['args']),
            description=info['desc'],
            example=info['example']
        ))

    # Sort by function name
    functions.sort(key=lambda f: f.name)

    return {"functions": functions}


# ========== JSON Export/Import Endpoints ==========

class WorkflowExportStep(BaseModel):
    """Exported workflow step structure."""
    step_order: int
    step_name: str
    step_type: str = "prompt"
    prompt_name: Optional[str] = None  # Reference by name instead of ID
    project_name: Optional[str] = None  # For backward compatibility
    execution_mode: str = "sequential"
    input_mapping: Optional[Dict[str, str]] = None
    condition_config: Optional[Dict[str, Any]] = None


class WorkflowExport(BaseModel):
    """Exported workflow structure."""
    version: str = "1.0"
    name: str
    description: str = ""
    auto_context: bool = False
    steps: List[WorkflowExportStep] = []


class WorkflowImportRequest(BaseModel):
    """Request model for importing a workflow from JSON."""
    workflow_json: dict  # Accept as dict for flexibility, validate internally
    new_name: Optional[str] = None  # Override name if provided


@router.get("/api/workflows/{workflow_id}/export", response_model=WorkflowExport)
def export_workflow(workflow_id: int, db: Session = Depends(get_db)):
    """Export a workflow as JSON.

    Exports the workflow structure with prompt references by name,
    making it portable for import into other instances.
    """
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    exported_steps = []
    for step in workflow.steps:
        # Get prompt name if exists
        prompt_name = None
        if step.prompt_id:
            prompt = db.query(Prompt).filter(Prompt.id == step.prompt_id).first()
            if prompt:
                prompt_name = prompt.name

        # Get project name if exists (backward compatibility)
        project_name = None
        if step.project_id:
            project = db.query(Project).filter(Project.id == step.project_id).first()
            if project:
                project_name = project.name

        # Parse JSON fields
        input_mapping = None
        if step.input_mapping:
            try:
                input_mapping = json.loads(step.input_mapping)
            except:
                pass

        condition_config = None
        if step.condition_config:
            try:
                condition_config = json.loads(step.condition_config)
            except:
                pass

        exported_steps.append(WorkflowExportStep(
            step_order=step.step_order,
            step_name=step.step_name,
            step_type=step.step_type or "prompt",
            prompt_name=prompt_name,
            project_name=project_name,
            execution_mode=step.execution_mode,
            input_mapping=input_mapping,
            condition_config=condition_config
        ))

    return WorkflowExport(
        version="1.0",
        name=workflow.name,
        description=workflow.description or "",
        auto_context=bool(workflow.auto_context),
        steps=exported_steps
    )


@router.post("/api/workflows/import", response_model=WorkflowResponse)
def import_workflow(request: WorkflowImportRequest, db: Session = Depends(get_db)):
    """Import a workflow from JSON.

    Creates a new workflow from the exported JSON structure.
    Resolves prompt references by name.
    """
    try:
        wf_dict = request.workflow_json

        # Use override name or original name
        workflow_name = request.new_name or wf_dict.get("name", "Imported Workflow")

        # Create workflow
        workflow = Workflow(
            name=workflow_name,
            description=wf_dict.get("description", ""),
            auto_context=1 if wf_dict.get("auto_context") else 0,
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat()
        )
        db.add(workflow)
        db.flush()  # Get workflow ID

        # Create steps
        for step_dict in wf_dict.get("steps", []):
            # Resolve prompt by name
            prompt_id = None
            prompt_name = step_dict.get("prompt_name")
            if prompt_name:
                prompt = db.query(Prompt).filter(Prompt.name == prompt_name).first()
                if prompt:
                    prompt_id = prompt.id

            # Resolve project by name (backward compatibility)
            project_id = None
            project_name = step_dict.get("project_name")
            if project_name:
                project = db.query(Project).filter(Project.name == project_name).first()
                if project:
                    project_id = project.id

            input_mapping = step_dict.get("input_mapping")
            condition_config = step_dict.get("condition_config")

            step = WorkflowStep(
                workflow_id=workflow.id,
                step_order=step_dict.get("step_order", 0),
                step_name=step_dict.get("step_name", ""),
                step_type=step_dict.get("step_type", "prompt"),
                prompt_id=prompt_id,
                project_id=project_id,
                execution_mode=step_dict.get("execution_mode"),
                input_mapping=json.dumps(input_mapping) if input_mapping else None,
                condition_config=json.dumps(condition_config) if condition_config else None
            )
            db.add(step)

        # Validate workflow control flow before commit (don't update flag yet)
        db.flush()  # Ensure all steps are in DB for validation
        validation = validate_workflow(db, workflow.id, update_flag=False)
        if validation.errors > 0:
            db.rollback()
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Workflow validation failed",
                    "valid": False,
                    "errors": validation.errors,
                    "warnings": validation.warnings,
                    "issues": [issue.to_dict() for issue in validation.issues
                              if issue.severity.value == "error"],
                    "all_issues": [issue.to_dict() for issue in validation.issues]
                }
            )

        # Validation passed - set validated flag and commit
        workflow.validated = 1
        db.commit()
        db.refresh(workflow)

        return _workflow_to_response(workflow, db)

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Import failed: {str(e)}")


@router.put("/api/workflows/{workflow_id}/json", response_model=WorkflowResponse)
def update_workflow_json(workflow_id: int, request: WorkflowImportRequest, db: Session = Depends(get_db)):
    """Update an existing workflow from JSON.

    Updates the workflow's basic info and replaces all steps with the provided JSON structure.
    Resolves prompt references by name.
    """
    try:
        # Check workflow exists
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        wf_dict = request.workflow_json

        # Update basic info
        workflow.name = wf_dict.get("name", workflow.name)
        workflow.description = wf_dict.get("description", workflow.description or "")
        workflow.auto_context = 1 if wf_dict.get("auto_context") else 0
        workflow.updated_at = datetime.utcnow().isoformat()

        # Delete existing steps
        db.query(WorkflowStep).filter(WorkflowStep.workflow_id == workflow_id).delete()

        # Create new steps from JSON
        for step_dict in wf_dict.get("steps", []):
            # Get prompt_id: accept direct ID from UI, or resolve by name for API/import
            prompt_id = step_dict.get("prompt_id")
            if not prompt_id:
                prompt_name = step_dict.get("prompt_name")
                if prompt_name:
                    prompt = db.query(Prompt).filter(Prompt.name == prompt_name).first()
                    if prompt:
                        prompt_id = prompt.id

            # Get project_id: accept direct ID from UI, or resolve by name for API/import
            project_id = step_dict.get("project_id")
            if not project_id:
                project_name = step_dict.get("project_name")
                if project_name:
                    project = db.query(Project).filter(Project.name == project_name).first()
                    if project:
                        project_id = project.id

            input_mapping = step_dict.get("input_mapping")
            condition_config = step_dict.get("condition_config")

            step = WorkflowStep(
                workflow_id=workflow.id,
                step_order=step_dict.get("step_order", 0),
                step_name=step_dict.get("step_name", ""),
                step_type=step_dict.get("step_type", "prompt"),
                prompt_id=prompt_id,
                project_id=project_id,
                execution_mode=step_dict.get("execution_mode"),
                input_mapping=json.dumps(input_mapping) if input_mapping else None,
                condition_config=json.dumps(condition_config) if condition_config else None
            )
            db.add(step)

        # Validate workflow control flow before commit (don't update flag yet)
        db.flush()  # Ensure all steps are in DB for validation
        validation = validate_workflow(db, workflow.id, update_flag=False)
        if validation.errors > 0:
            db.rollback()
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Workflow validation failed",
                    "valid": False,
                    "errors": validation.errors,
                    "warnings": validation.warnings,
                    "issues": [issue.to_dict() for issue in validation.issues
                              if issue.severity.value == "error"],
                    "all_issues": [issue.to_dict() for issue in validation.issues]
                }
            )

        # Validation passed - set validated flag and commit
        workflow.validated = 1
        db.commit()
        db.refresh(workflow)

        return _workflow_to_response(workflow, db)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"JSON update failed: {str(e)}")


# ========== Workflow Output File Download Endpoints ==========

@router.get("/api/workflow-outputs/{filename}")
async def download_workflow_output(filename: str):
    """Download a workflow output file.

    Files are stored in uploads/workflow_outputs/ directory.
    """
    import os
    from fastapi.responses import FileResponse

    # Sanitize filename to prevent directory traversal
    safe_filename = os.path.basename(filename)

    # Build path
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    filepath = os.path.join(base_dir, "uploads", "workflow_outputs", safe_filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"Output file not found: {safe_filename}")

    # Determine media type based on extension
    media_type = "application/octet-stream"
    if safe_filename.endswith('.csv'):
        media_type = "text/csv"
    elif safe_filename.endswith('.json'):
        media_type = "application/json"
    elif safe_filename.endswith('.txt'):
        media_type = "text/plain"

    return FileResponse(
        path=filepath,
        filename=safe_filename,
        media_type=media_type
    )


@router.get("/api/workflow-outputs")
async def list_workflow_outputs():
    """List all workflow output files.

    Returns list of available output files with metadata.
    """
    import os
    from datetime import datetime

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    outputs_dir = os.path.join(base_dir, "uploads", "workflow_outputs")

    if not os.path.exists(outputs_dir):
        return {"files": []}

    files = []
    for filename in os.listdir(outputs_dir):
        filepath = os.path.join(outputs_dir, filename)
        if os.path.isfile(filepath):
            stat = os.stat(filepath)
            files.append({
                "filename": filename,
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "download_url": f"/api/workflow-outputs/{filename}"
            })

    # Sort by modification time (newest first)
    files.sort(key=lambda x: x["modified_at"], reverse=True)

    return {"files": files}


@router.delete("/api/workflow-outputs/{filename}")
async def delete_workflow_output(filename: str):
    """Delete a workflow output file.

    Only deletes files from the workflow_outputs directory.
    """
    import os

    # Sanitize filename to prevent directory traversal
    safe_filename = os.path.basename(filename)

    # Build path
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    filepath = os.path.join(base_dir, "uploads", "workflow_outputs", safe_filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"Output file not found: {safe_filename}")

    try:
        os.remove(filepath)
        return {"success": True, "message": f"Deleted {safe_filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")

"""System settings API endpoints.

Based on specification in docs/req.txt section 4.5 (システム設定)
Phase 2 implementation.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Optional, Union, Any
from pydantic import BaseModel
import json

from backend.database import get_db, SystemSetting
from backend.llm import get_available_models

router = APIRouter()


class SettingUpdate(BaseModel):
    """Request to update setting."""
    key: str
    value: str


class SettingResponse(BaseModel):
    """Setting response model."""
    key: str
    value: str


@router.get("/api/settings", response_model=List[SettingResponse])
def list_settings(db: Session = Depends(get_db)):
    """List all system settings.

    Specification: docs/req.txt section 4.5
    Phase 2
    """
    settings = db.query(SystemSetting).all()

    return [
        SettingResponse(key=s.key, value=s.value or "")
        for s in settings
    ]


@router.get("/api/settings/default-project")
def get_default_project(db: Session = Depends(get_db)):
    """Get default project ID for single execution.

    Returns:
        Dictionary with project_id (None if not set)
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "default_project_id").first()

    return {
        "project_id": int(setting.value) if setting and setting.value else None
    }


@router.put("/api/settings/default-project")
def set_default_project(project_id: int, db: Session = Depends(get_db)):
    """Set default project ID for single execution.

    Args:
        project_id: Project ID to set as default

    Returns:
        Success message with project_id
    """
    # Verify project exists
    from backend.database import Project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project with ID {project_id} not found")

    # Update or create setting
    setting = db.query(SystemSetting).filter(SystemSetting.key == "default_project_id").first()

    if setting:
        setting.value = str(project_id)
    else:
        setting = SystemSetting(key="default_project_id", value=str(project_id))
        db.add(setting)

    db.commit()
    db.refresh(setting)

    return {
        "project_id": project_id,
        "project_name": project.name,
        "message": f"Default project set to '{project.name}'"
    }


@router.get("/api/settings/job-parallelism")
def get_job_parallelism(db: Session = Depends(get_db)):
    """Get job parallelism setting.

    Returns:
        Dictionary with parallelism value (1-99, default 1)

    Phase 3 feature for job control
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "job_parallelism").first()

    if setting and setting.value:
        try:
            parallelism = int(setting.value)
            # Clamp to valid range
            parallelism = max(1, min(parallelism, 99))
        except ValueError:
            parallelism = 1
    else:
        parallelism = 1

    return {"parallelism": parallelism}


@router.put("/api/settings/job-parallelism")
def set_job_parallelism(parallelism: int, db: Session = Depends(get_db)):
    """Set job parallelism setting.

    Args:
        parallelism: Number of parallel workers (1-99)

    Returns:
        Updated parallelism value

    Phase 3 feature for job control
    """
    # Validate range
    if parallelism < 1 or parallelism > 99:
        raise HTTPException(
            status_code=400,
            detail="Parallelism must be between 1 and 99"
        )

    # Update or create setting
    setting = db.query(SystemSetting).filter(SystemSetting.key == "job_parallelism").first()

    if setting:
        setting.value = str(parallelism)
    else:
        setting = SystemSetting(key="job_parallelism", value=str(parallelism))
        db.add(setting)

    db.commit()
    db.refresh(setting)

    return {
        "parallelism": parallelism,
        "message": f"Job parallelism set to {parallelism}"
    }


@router.get("/api/settings/{key}", response_model=SettingResponse)
def get_setting(key: str, db: Session = Depends(get_db)):
    """Get specific setting value.

    Specification: docs/req.txt section 4.5.3
    Phase 2
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if not setting:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    return SettingResponse(key=setting.key, value=setting.value or "")


@router.put("/api/settings/{key}", response_model=SettingResponse)
def update_setting(key: str, request: SettingUpdate, db: Session = Depends(get_db)):
    """Update or create setting.

    Specification: docs/req.txt section 4.5.3
    Phase 2
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()

    if setting:
        setting.value = request.value
    else:
        setting = SystemSetting(key=key, value=request.value)
        db.add(setting)

    db.commit()
    db.refresh(setting)

    return SettingResponse(key=setting.key, value=setting.value or "")


@router.delete("/api/settings/{key}")
def delete_setting(key: str, db: Session = Depends(get_db)):
    """Delete setting.

    Specification: docs/req.txt section 4.5
    Phase 2
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if not setting:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    db.delete(setting)
    db.commit()

    return {"success": True, "message": f"Setting '{key}' deleted"}


class ModelInfo(BaseModel):
    """Model information response model."""
    name: str
    display_name: str
    default_parameters: Dict[str, Union[float, int, str]]


class ModelParametersUpdate(BaseModel):
    """Request to update model parameters.

    Parameters can be float (temperature, max_tokens, top_p) or
    string (verbosity, reasoning_effort for GPT-5 models).

    Note: model_name is optional since it's also provided in the URL path.
    If provided in both, the URL path takes precedence.

    Simple usage (just the parameters):
      {"max_output_tokens": 16384}

    Full usage:
      {"model_name": "azure-gpt-5-mini", "parameters": {"max_output_tokens": 16384}}
    """
    model_name: Optional[str] = None
    parameters: Optional[Dict[str, Union[float, int, str]]] = None
    # Allow arbitrary extra fields for simple parameter passing
    model_config = {"extra": "allow"}


@router.get("/api/settings/models/available")
def get_available_models_info(db: Session = Depends(get_db)):
    """Get list of available LLM models with their information.

    Specification: docs/req.txt section 4.5.1
    Phase 2 - Extended to include GPT-5 models

    Returns only enabled models. If no enabled models are configured,
    all models are considered enabled by default.
    """
    all_models = get_available_models()

    # Check which models are enabled
    enabled_models = []
    for model in all_models:
        setting_key = f"model_enabled_{model['name']}"
        setting = db.query(SystemSetting).filter(SystemSetting.key == setting_key).first()

        # If no setting exists, model is enabled by default
        # If setting exists, check if value is "true"
        is_enabled = setting is None or setting.value == "true"

        if is_enabled:
            enabled_models.append(model)

    return enabled_models


@router.get("/api/settings/models/default")
def get_default_model(db: Session = Depends(get_db)):
    """Get the default LLM model.

    Returns the model name set as default, or 'azure-gpt-4.1' if not set.
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "default_model").first()
    default_model = setting.value if setting else "azure-gpt-4.1"

    return {"default_model": default_model}


@router.put("/api/settings/models/default")
def set_default_model(model_name: str, db: Session = Depends(get_db)):
    """Set the default LLM model.

    Args:
        model_name: The model name to set as default
    """
    # Validate model exists
    available = [m["name"] for m in get_available_models()]
    if model_name not in available:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid model name. Available models: {', '.join(available)}"
        )

    setting = db.query(SystemSetting).filter(SystemSetting.key == "default_model").first()

    if setting:
        setting.value = model_name
    else:
        setting = SystemSetting(key="default_model", value=model_name)
        db.add(setting)

    db.commit()
    db.refresh(setting)

    return {"default_model": setting.value}


@router.get("/api/settings/models/{model_name}/parameters")
def get_model_parameters(model_name: str, db: Session = Depends(get_db)):
    """Get parameters for a specific model.

    Returns custom parameters if set, otherwise returns default parameters.
    """
    # Get custom parameters from database
    setting_key = f"model_params_{model_name}"
    setting = db.query(SystemSetting).filter(SystemSetting.key == setting_key).first()

    if setting and setting.value:
        custom_params = json.loads(setting.value)
    else:
        custom_params = None

    # Get default parameters from model
    models = get_available_models()
    model_info = next((m for m in models if m["name"] == model_name), None)

    if not model_info:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    return {
        "model_name": model_name,
        "custom_parameters": custom_params,
        "default_parameters": model_info["default_parameters"],
        "active_parameters": custom_params if custom_params else model_info["default_parameters"]
    }


@router.put("/api/settings/models/{model_name}/parameters")
def update_model_parameters(
    model_name: str,
    request: ModelParametersUpdate,
    db: Session = Depends(get_db)
):
    """Update default parameters for a specific model.

    Args:
        model_name: The model name (from URL path)
        request: New parameter values. Supports two formats:
            1. Simple: {"max_output_tokens": 16384}
            2. Full: {"parameters": {"max_output_tokens": 16384}}
    """
    # Validate model exists
    models = get_available_models()
    model_info = next((m for m in models if m["name"] == model_name), None)

    if not model_info:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    # Handle both request formats
    # If parameters is provided explicitly, use it
    # Otherwise, collect all extra fields as parameters
    if request.parameters:
        params_to_save = request.parameters
    else:
        # Get all fields except model_name and parameters (which are None)
        extra_data = request.model_dump(exclude={"model_name", "parameters"}, exclude_none=True)
        if extra_data:
            params_to_save = extra_data
        else:
            raise HTTPException(status_code=400, detail="No parameters provided")

    # Store custom parameters (merge with existing if any)
    setting_key = f"model_params_{model_name}"
    setting = db.query(SystemSetting).filter(SystemSetting.key == setting_key).first()

    # Load existing params and merge
    existing_params = {}
    if setting and setting.value:
        try:
            existing_params = json.loads(setting.value)
        except json.JSONDecodeError:
            existing_params = {}

    # Merge new params with existing
    merged_params = {**existing_params, **params_to_save}
    params_json = json.dumps(merged_params)

    if setting:
        setting.value = params_json
    else:
        setting = SystemSetting(key=setting_key, value=params_json)
        db.add(setting)

    db.commit()
    db.refresh(setting)

    return {
        "model_name": model_name,
        "parameters": merged_params
    }


@router.delete("/api/settings/models/{model_name}/parameters")
def reset_model_parameters(model_name: str, db: Session = Depends(get_db)):
    """Reset model parameters to defaults.

    Args:
        model_name: The model name
    """
    setting_key = f"model_params_{model_name}"
    setting = db.query(SystemSetting).filter(SystemSetting.key == setting_key).first()

    if setting:
        db.delete(setting)
        db.commit()

    # Get default parameters
    models = get_available_models()
    model_info = next((m for m in models if m["name"] == model_name), None)

    if not model_info:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    return {
        "model_name": model_name,
        "parameters": model_info["default_parameters"],
        "message": "Parameters reset to defaults"
    }


class ModelEnableStatus(BaseModel):
    """Model enable/disable status."""
    name: str
    display_name: str
    enabled: bool


@router.get("/api/settings/models/all", response_model=List[ModelEnableStatus])
def get_all_models_with_status(db: Session = Depends(get_db)):
    """Get all available models with their enabled/disabled status.

    Returns all models discovered by the system, along with their
    enabled/disabled status. Used for model management UI.
    """
    all_models = get_available_models()
    result = []

    for model in all_models:
        setting_key = f"model_enabled_{model['name']}"
        setting = db.query(SystemSetting).filter(SystemSetting.key == setting_key).first()

        # If no setting exists, model is enabled by default
        is_enabled = setting is None or setting.value == "true"

        result.append(ModelEnableStatus(
            name=model["name"],
            display_name=model["display_name"],
            enabled=is_enabled
        ))

    return result


@router.put("/api/settings/models/{model_name}/enable")
def set_model_enabled(model_name: str, enabled: bool, db: Session = Depends(get_db)):
    """Enable or disable a specific model.

    Args:
        model_name: The model name to enable/disable
        enabled: True to enable, False to disable
    """
    # Validate model exists
    all_models = get_available_models()
    model_info = next((m for m in all_models if m["name"] == model_name), None)

    if not model_info:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    setting_key = f"model_enabled_{model_name}"
    setting = db.query(SystemSetting).filter(SystemSetting.key == setting_key).first()

    value = "true" if enabled else "false"

    if setting:
        setting.value = value
    else:
        setting = SystemSetting(key=setting_key, value=value)
        db.add(setting)

    db.commit()
    db.refresh(setting)

    return {
        "model_name": model_name,
        "enabled": enabled,
        "message": f"Model '{model_name}' {'enabled' if enabled else 'disabled'}"
    }

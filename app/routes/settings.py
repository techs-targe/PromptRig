"""System settings API endpoints.

Based on specification in docs/req.txt section 4.5 (システム設定)
Phase 2 implementation.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Optional
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
    default_parameters: Dict[str, float]


class ModelParametersUpdate(BaseModel):
    """Request to update model parameters."""
    model_name: str
    parameters: Dict[str, float]


@router.get("/api/settings/models/available")
def get_available_models_info():
    """Get list of available LLM models with their information.

    Specification: docs/req.txt section 4.5.1
    Phase 2 - Extended to include GPT-5 models
    """
    return get_available_models()


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
        model_name: The model name
        request: New parameter values
    """
    # Validate model exists
    models = get_available_models()
    model_info = next((m for m in models if m["name"] == model_name), None)

    if not model_info:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    # Store custom parameters
    setting_key = f"model_params_{model_name}"
    setting = db.query(SystemSetting).filter(SystemSetting.key == setting_key).first()

    params_json = json.dumps(request.parameters)

    if setting:
        setting.value = params_json
    else:
        setting = SystemSetting(key=setting_key, value=params_json)
        db.add(setting)

    db.commit()
    db.refresh(setting)

    return {
        "model_name": model_name,
        "parameters": request.parameters
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

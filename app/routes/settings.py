"""System settings API endpoints.

Based on specification in docs/req.txt section 4.5 (システム設定)
Phase 2 implementation.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Optional, Union, Any
from pydantic import BaseModel
import json

from backend.database import get_db, SystemSetting
from backend.llm import get_available_models
from backend.llm.factory import get_all_models_env_status

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


# Default agent max iterations
DEFAULT_AGENT_MAX_ITERATIONS = 30

# Default agent stream timeout (seconds)
DEFAULT_AGENT_STREAM_TIMEOUT = 300  # 5 minutes

# Default agent max completion tokens (for reasoning models like GPT-5/o4)
# Reasoning models use many tokens for internal thinking, so this needs to be higher
DEFAULT_AGENT_MAX_TOKENS = 16384

# Default agent LLM timeout (seconds) - how long to wait for OpenAI API response
DEFAULT_AGENT_LLM_TIMEOUT = 600  # 10 minutes


@router.get("/api/settings/agent-max-iterations")
def get_agent_max_iterations(db: Session = Depends(get_db)):
    """Get agent maximum iterations setting.

    Returns:
        Dictionary with max_iterations value (10-99, default 30)

    Controls how many tool-calling iterations the AI agent can perform
    before stopping. Higher values allow more complex multi-step tasks.
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "agent_max_iterations").first()

    if setting and setting.value:
        try:
            max_iterations = int(setting.value)
            # Clamp to valid range
            max_iterations = max(10, min(max_iterations, 99))
        except ValueError:
            max_iterations = DEFAULT_AGENT_MAX_ITERATIONS
    else:
        max_iterations = DEFAULT_AGENT_MAX_ITERATIONS

    return {
        "max_iterations": max_iterations,
        "default": DEFAULT_AGENT_MAX_ITERATIONS
    }


@router.put("/api/settings/agent-max-iterations")
def set_agent_max_iterations(max_iterations: int, db: Session = Depends(get_db)):
    """Set agent maximum iterations setting.

    Args:
        max_iterations: Maximum number of agent iterations (10-99)

    Returns:
        Updated max_iterations value

    Higher values allow more complex multi-step tasks but increase
    potential cost and execution time.
    """
    # Validate range
    if max_iterations < 10 or max_iterations > 99:
        raise HTTPException(
            status_code=400,
            detail="Agent max iterations must be between 10 and 99"
        )

    # Update or create setting
    setting = db.query(SystemSetting).filter(SystemSetting.key == "agent_max_iterations").first()

    if setting:
        setting.value = str(max_iterations)
    else:
        setting = SystemSetting(key="agent_max_iterations", value=str(max_iterations))
        db.add(setting)

    db.commit()
    db.refresh(setting)

    return {
        "max_iterations": max_iterations,
        "message": f"Agent max iterations set to {max_iterations}"
    }


@router.get("/api/settings/agent-stream-timeout")
def get_agent_stream_timeout(db: Session = Depends(get_db)):
    """Get agent stream timeout setting.

    Returns:
        Dictionary with timeout value (60-1800 seconds, default 300)

    Controls how long the SSE stream stays open for agent task updates.
    After this timeout, the stream closes but the task continues running.
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "agent_stream_timeout").first()

    if setting and setting.value:
        try:
            timeout = int(setting.value)
            # Clamp to valid range (1 minute to 30 minutes)
            timeout = max(60, min(timeout, 1800))
        except ValueError:
            timeout = DEFAULT_AGENT_STREAM_TIMEOUT
    else:
        timeout = DEFAULT_AGENT_STREAM_TIMEOUT

    return {
        "timeout": timeout,
        "default": DEFAULT_AGENT_STREAM_TIMEOUT
    }


@router.put("/api/settings/agent-stream-timeout")
def set_agent_stream_timeout(timeout: int = Query(..., ge=60, le=1800), db: Session = Depends(get_db)):
    """Set agent stream timeout setting.

    Args:
        timeout: Stream timeout in seconds (60-1800, i.e., 1-30 minutes)

    Returns:
        Updated timeout value

    Higher values allow monitoring longer-running tasks but consume more
    server resources. The task continues running even after stream timeout.
    """
    # Validate range (1 minute to 30 minutes)
    if timeout < 60 or timeout > 1800:
        raise HTTPException(
            status_code=400,
            detail="Agent stream timeout must be between 60 and 1800 seconds (1-30 minutes)"
        )

    # Update or create setting
    setting = db.query(SystemSetting).filter(SystemSetting.key == "agent_stream_timeout").first()

    if setting:
        setting.value = str(timeout)
    else:
        setting = SystemSetting(key="agent_stream_timeout", value=str(timeout))
        db.add(setting)

    db.commit()
    db.refresh(setting)

    return {
        "timeout": timeout,
        "message": f"Agent stream timeout set to {timeout} seconds ({timeout // 60} minutes)"
    }


@router.get("/api/settings/agent-max-tokens")
def get_agent_max_tokens(db: Session = Depends(get_db)):
    """Get agent max completion tokens setting.

    Returns:
        Dictionary with max_tokens value (1024-65536, default 16384)

    Controls the maximum number of tokens the agent's LLM can generate per call.
    Reasoning models (GPT-5, o4-mini) use many tokens for internal thinking,
    so this value needs to be higher than traditional models.

    If you see empty agent responses with finish_reason=length, increase this value.
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "agent_max_tokens").first()

    if setting and setting.value:
        try:
            max_tokens = int(setting.value)
            # Clamp to valid range
            max_tokens = max(1024, min(max_tokens, 65536))
        except ValueError:
            max_tokens = DEFAULT_AGENT_MAX_TOKENS
    else:
        max_tokens = DEFAULT_AGENT_MAX_TOKENS

    return {
        "max_tokens": max_tokens,
        "default": DEFAULT_AGENT_MAX_TOKENS
    }


@router.put("/api/settings/agent-max-tokens")
def set_agent_max_tokens(max_tokens: int = Query(..., ge=1024, le=65536), db: Session = Depends(get_db)):
    """Set agent max completion tokens setting.

    Args:
        max_tokens: Maximum completion tokens (1024-65536)

    Returns:
        Updated max_tokens value

    Reasoning models (GPT-5, o4-mini) require higher values because they use
    tokens for internal reasoning before generating the visible output.

    Recommended values:
    - 4096: Traditional models (GPT-4, GPT-4o)
    - 16384: Reasoning models with simple tasks
    - 32768: Reasoning models with complex multi-tool tasks
    - 65536: Maximum for very complex reasoning chains
    """
    # Validate range
    if max_tokens < 1024 or max_tokens > 65536:
        raise HTTPException(
            status_code=400,
            detail="Agent max tokens must be between 1024 and 65536"
        )

    # Update or create setting
    setting = db.query(SystemSetting).filter(SystemSetting.key == "agent_max_tokens").first()

    if setting:
        setting.value = str(max_tokens)
    else:
        setting = SystemSetting(key="agent_max_tokens", value=str(max_tokens))
        db.add(setting)

    db.commit()
    db.refresh(setting)

    return {
        "max_tokens": max_tokens,
        "message": f"Agent max tokens set to {max_tokens}"
    }


@router.get("/api/settings/agent-llm-timeout")
def get_agent_llm_timeout(db: Session = Depends(get_db)):
    """Get agent LLM timeout setting.

    Returns:
        Dictionary with timeout value (60-1800 seconds, default 600)

    Controls how long the agent waits for OpenAI API responses.
    If the API doesn't respond within this time, the request times out.

    Default is 10 minutes (600 seconds) to handle slow API responses,
    especially during high load periods.
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "agent_llm_timeout").first()

    if setting and setting.value:
        try:
            timeout = int(setting.value)
            # Clamp to valid range (1-30 minutes)
            timeout = max(60, min(timeout, 1800))
        except ValueError:
            timeout = DEFAULT_AGENT_LLM_TIMEOUT
    else:
        timeout = DEFAULT_AGENT_LLM_TIMEOUT

    return {
        "timeout": timeout,
        "default": DEFAULT_AGENT_LLM_TIMEOUT,
        "timeout_minutes": timeout / 60
    }


@router.put("/api/settings/agent-llm-timeout")
def set_agent_llm_timeout(timeout: int = Query(..., ge=60, le=1800), db: Session = Depends(get_db)):
    """Set agent LLM timeout setting.

    Args:
        timeout: LLM API timeout in seconds (60-1800, i.e., 1-30 minutes)

    Returns:
        Updated timeout value

    This controls how long the agent waits for each OpenAI API call.
    If you experience frequent timeouts, increase this value.
    If you want faster failure detection, decrease it.

    Recommended values:
    - 60-120: Fast failure detection, may timeout on complex reasoning
    - 300-600: Balanced (default 600 = 10 minutes)
    - 900-1800: Very patient, for complex reasoning tasks
    """
    # Validate range
    if timeout < 60 or timeout > 1800:
        raise HTTPException(
            status_code=400,
            detail="Agent LLM timeout must be between 60 and 1800 seconds (1-30 minutes)"
        )

    # Update or create setting
    setting = db.query(SystemSetting).filter(SystemSetting.key == "agent_llm_timeout").first()

    if setting:
        setting.value = str(timeout)
    else:
        setting = SystemSetting(key="agent_llm_timeout", value=str(timeout))
        db.add(setting)

    db.commit()
    db.refresh(setting)

    return {
        "timeout": timeout,
        "timeout_minutes": timeout / 60,
        "message": f"Agent LLM timeout set to {timeout} seconds ({timeout / 60:.1f} minutes)"
    }


# Default text file extensions (common text file types)
DEFAULT_TEXT_FILE_EXTENSIONS = "txt,csv,md,json,xml,yaml,yml,log,ini,cfg,conf,html,htm,css,js,ts,py,java,c,cpp,h,hpp,cs,go,rs,rb,php,sql,sh,bash,zsh,ps1,bat,cmd"


@router.get("/api/settings/text-file-extensions")
def get_text_file_extensions(db: Session = Depends(get_db)):
    """Get text file extensions for FILEPATH auto-expansion.

    Files with these extensions will have their content embedded in the prompt
    instead of being sent as images to the Vision API.

    Returns:
        Dictionary with extensions (comma-separated) and parsed list
        If empty, no auto-expansion occurs (all files sent to LLM as-is)
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "text_file_extensions").first()

    if setting is not None:
        extensions = setting.value
    else:
        extensions = DEFAULT_TEXT_FILE_EXTENSIONS

    # Parse into list (lowercase, trimmed)
    if extensions:
        ext_list = [ext.strip().lower() for ext in extensions.split(",") if ext.strip()]
    else:
        ext_list = []

    return {
        "extensions": extensions,
        "extensions_list": ext_list,
        "default": DEFAULT_TEXT_FILE_EXTENSIONS
    }


@router.put("/api/settings/text-file-extensions")
def set_text_file_extensions(extensions: str, db: Session = Depends(get_db)):
    """Set text file extensions for FILEPATH auto-expansion.

    Args:
        extensions: Comma-separated list of extensions (e.g., "txt,csv,md")
                   Empty string disables auto-expansion

    Returns:
        Updated extensions setting
    """
    # Normalize: lowercase, remove dots, trim whitespace
    if extensions:
        ext_list = [ext.strip().lower().lstrip('.') for ext in extensions.split(",") if ext.strip()]
        normalized = ",".join(ext_list)
    else:
        normalized = ""

    # Update or create setting
    setting = db.query(SystemSetting).filter(SystemSetting.key == "text_file_extensions").first()

    if setting:
        setting.value = normalized
    else:
        setting = SystemSetting(key="text_file_extensions", value=normalized)
        db.add(setting)

    db.commit()
    db.refresh(setting)

    return {
        "extensions": normalized,
        "extensions_list": [ext.strip() for ext in normalized.split(",") if ext.strip()] if normalized else [],
        "message": f"Text file extensions updated"
    }


@router.delete("/api/settings/text-file-extensions")
def reset_text_file_extensions(db: Session = Depends(get_db)):
    """Reset text file extensions to default value.

    Returns:
        Default extensions setting
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "text_file_extensions").first()

    if setting:
        db.delete(setting)
        db.commit()

    ext_list = [ext.strip().lower() for ext in DEFAULT_TEXT_FILE_EXTENSIONS.split(",") if ext.strip()]

    return {
        "extensions": DEFAULT_TEXT_FILE_EXTENSIONS,
        "extensions_list": ext_list,
        "message": "Text file extensions reset to default"
    }


# =============================================================================
# Guardrail Chain Settings
# =============================================================================

DEFAULT_GUARDRAIL_MODEL = "openai-gpt-4.1-nano"


@router.get("/api/settings/guardrail-model")
def get_guardrail_model(db: Session = Depends(get_db)):
    """Get the model used for guardrail chain checks.

    The guardrail chain uses a lightweight LLM to validate requests
    before they reach the main agent. This setting controls which model
    is used for these validation checks.

    Returns:
        Dictionary with current guardrail model and available options
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "guardrail_model").first()
    current_model = setting.value if setting else DEFAULT_GUARDRAIL_MODEL

    # Get lightweight models suitable for guardrail (fast, cheap)
    all_models = get_available_models()
    lightweight_models = [
        m["name"] for m in all_models
        if any(kw in m["name"].lower() for kw in ["mini", "nano", "haiku", "4o-mini"])
    ]

    # Add current model if not in list
    if current_model not in lightweight_models:
        lightweight_models.append(current_model)

    return {
        "model": current_model,
        "default": DEFAULT_GUARDRAIL_MODEL,
        "available_models": sorted(lightweight_models)
    }


@router.put("/api/settings/guardrail-model")
def set_guardrail_model(model: str, db: Session = Depends(get_db)):
    """Set the model used for guardrail chain checks.

    Args:
        model: Model name to use for guardrail checks.
               Recommended: lightweight models like 'azure-gpt-4o-mini',
               'azure-gpt-5-nano', 'claude-3.5-haiku'

    Returns:
        Updated guardrail model setting
    """
    # Validate model exists
    all_models = get_available_models()
    model_info = next((m for m in all_models if m["name"] == model), None)

    if not model_info:
        raise HTTPException(status_code=404, detail=f"Model '{model}' not found")

    # Update or create setting
    setting = db.query(SystemSetting).filter(SystemSetting.key == "guardrail_model").first()

    if setting:
        setting.value = model
    else:
        setting = SystemSetting(key="guardrail_model", value=model)
        db.add(setting)

    db.commit()
    db.refresh(setting)

    # Reset guardrail chain singleton to use new model
    try:
        from backend.agent.guardrail_chain import reset_guardrail_chain
        reset_guardrail_chain()
    except ImportError:
        pass

    return {
        "model": model,
        "message": f"Guardrail model set to '{model}'"
    }


@router.delete("/api/settings/guardrail-model")
def reset_guardrail_model(db: Session = Depends(get_db)):
    """Reset guardrail model to default.

    Returns:
        Default guardrail model setting
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "guardrail_model").first()

    if setting:
        db.delete(setting)
        db.commit()

    # Reset guardrail chain singleton
    try:
        from backend.agent.guardrail_chain import reset_guardrail_chain
        reset_guardrail_chain()
    except ImportError:
        pass

    return {
        "model": DEFAULT_GUARDRAIL_MODEL,
        "message": "Guardrail model reset to default"
    }


@router.get("/api/settings/guardrail-enabled")
def get_guardrail_enabled(db: Session = Depends(get_db)):
    """Get whether guardrail chain is enabled.

    Returns:
        Dictionary with enabled status
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "guardrail_enabled").first()
    enabled = setting is None or setting.value != "false"  # Enabled by default

    return {
        "enabled": enabled,
        "default": True
    }


@router.put("/api/settings/guardrail-enabled")
def set_guardrail_enabled(enabled: bool, db: Session = Depends(get_db)):
    """Enable or disable the guardrail chain.

    Args:
        enabled: True to enable guardrail checks, False to disable

    Returns:
        Updated enabled status
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "guardrail_enabled").first()
    value = "true" if enabled else "false"

    if setting:
        setting.value = value
    else:
        setting = SystemSetting(key="guardrail_enabled", value=value)
        db.add(setting)

    db.commit()
    db.refresh(setting)

    return {
        "enabled": enabled,
        "message": f"Guardrail chain {'enabled' if enabled else 'disabled'}"
    }


# =============================================================================
# Feature Flags
# =============================================================================

def is_feature_enabled(feature_name: str) -> bool:
    """Check if a feature is enabled via environment variable.

    Feature flags are read from .env file. Default is False (disabled).

    Args:
        feature_name: The feature name (e.g., "huggingface_import")

    Returns:
        True if feature is enabled, False otherwise
    """
    import os
    env_key = f"{feature_name.upper()}_ENABLED"
    value = os.getenv(env_key, "false").lower()
    return value in ("true", "1", "yes", "on")


@router.get("/api/settings/features")
def get_feature_flags():
    """Get all feature flags and their status.

    Returns feature flags configured via environment variables.
    These control optional functionality that can be enabled/disabled.

    Returns:
        Dictionary with feature flags and their enabled status
    """
    return {
        "features": {
            "huggingface_import": is_feature_enabled("huggingface_import")
        }
    }


@router.get("/api/settings/features/{feature_name}")
def get_feature_flag(feature_name: str):
    """Get a specific feature flag status.

    Args:
        feature_name: The feature name to check

    Returns:
        Dictionary with feature enabled status
    """
    valid_features = ["huggingface_import"]

    if feature_name not in valid_features:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown feature: {feature_name}. Valid features: {', '.join(valid_features)}"
        )

    return {
        "feature": feature_name,
        "enabled": is_feature_enabled(feature_name)
    }


# =============================================================================
# Generic Settings (must be last due to {key} path parameter)
# =============================================================================

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


@router.get("/api/settings/models/env-status")
def get_models_env_status():
    """Get environment variable configuration status for all discovered models.

    Returns all models (including unconfigured ones) with their environment
    variable settings. Models without required env vars will have
    available=False.

    Used by UI to:
    - Show which models are properly configured
    - Display which env vars are missing
    - Show masked values of configured API keys

    Returns:
        List of model env status dicts with:
        - name: Model identifier
        - available: True if all required env vars are set
        - env_vars: List of env var status (key, required, is_set, masked_value)
    """
    return get_all_models_env_status()


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

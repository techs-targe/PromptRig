"""LLM client factory with auto-discovery.

Plugin Architecture:
- Add a new .py file in backend/llm/ directory
- Define a class that extends LLMClient with MODEL_NAME and DISPLAY_NAME
- The factory will auto-discover and register it at startup

Example:
    class MyNewClient(LLMClient):
        MODEL_NAME = "my-model-v1"
        DISPLAY_NAME = "my-model"  # Used as the model identifier

        def call(self, prompt: str, **kwargs) -> LLMResponse:
            ...

No changes to factory.py required when adding new models.
"""

import os
import importlib
import inspect
import logging
from pathlib import Path
from typing import List, Dict
from dotenv import load_dotenv

from .base import LLMClient, EnvVarConfig

load_dotenv()

logger = logging.getLogger(__name__)

# Cache for discovered models
_discovered_models: Dict[str, type] = {}
_discovery_done = False


def _discover_models():
    """Scan LLM directory and discover all LLMClient subclasses.

    Scans:
    - backend/llm/*.py (public models)
    - backend/llm/private/*.py (private models, not tracked by git)
    """
    global _discovered_models, _discovery_done

    if _discovery_done:
        return

    llm_dir = Path(__file__).parent

    # Scan all .py files in llm directory (excluding system files)
    exclude_files = {'__init__.py', 'base.py', 'factory.py'}

    for py_file in llm_dir.glob('*.py'):
        if py_file.name in exclude_files:
            continue

        module_name = py_file.stem
        try:
            module = importlib.import_module(f'.{module_name}', package='backend.llm')

            # Find all LLMClient subclasses with required attributes
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if (issubclass(obj, LLMClient) and
                    obj is not LLMClient and
                    hasattr(obj, 'DISPLAY_NAME')):

                    model_id = getattr(obj, 'DISPLAY_NAME', None)
                    if model_id and model_id not in _discovered_models:
                        _discovered_models[model_id] = obj
                        logger.debug(f"Discovered LLM model: {model_id} ({name})")
        except Exception as e:
            logger.warning(f"Failed to load LLM module {module_name}: {e}")

    # Also scan private directory for non-public models
    private_dir = llm_dir / 'private'
    if private_dir.exists():
        for py_file in private_dir.glob('*.py'):
            if py_file.name == '__init__.py':
                continue

            module_name = py_file.stem
            try:
                module = importlib.import_module(
                    f'.private.{module_name}', package='backend.llm'
                )

                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, LLMClient) and
                        obj is not LLMClient and
                        hasattr(obj, 'DISPLAY_NAME')):

                        model_id = getattr(obj, 'DISPLAY_NAME', None)
                        if model_id and model_id not in _discovered_models:
                            _discovered_models[model_id] = obj
                            logger.debug(f"Discovered private LLM model: {model_id} ({name})")
            except Exception as e:
                logger.warning(f"Failed to load private LLM module {module_name}: {e}")

    _discovery_done = True
    logger.info(f"LLM discovery complete: {len(_discovered_models)} models found")


def get_llm_client(model_name: str = None) -> LLMClient:
    """Get LLM client instance based on model name.

    Args:
        model_name: Model identifier (DISPLAY_NAME). If None, uses ACTIVE_LLM_MODEL from env.

    Returns:
        LLMClient instance

    Raises:
        ValueError: If model_name is not found in discovered models
    """
    _discover_models()

    if model_name is None:
        model_name = os.getenv("ACTIVE_LLM_MODEL", "azure-gpt-4.1")

    if model_name in _discovered_models:
        return _discovered_models[model_name]()

    raise ValueError(
        f"Unsupported model: {model_name}. "
        f"Available models: {sorted(_discovered_models.keys())}"
    )


def get_available_models() -> List[Dict[str, any]]:
    """Get list of all available LLM models with their default parameters.

    Returns:
        List of dictionaries containing model information:
        - name: Model identifier (DISPLAY_NAME)
        - display_name: Human-readable name
        - default_parameters: Dictionary of default parameter values
        - is_private: True if model is in private directory

    Note:
        Only returns models that can be successfully instantiated.
        Models with invalid configuration (e.g., missing API keys) are skipped.
    """
    _discover_models()

    models = []
    for model_id, client_class in _discovered_models.items():
        try:
            client = client_class()
            is_private = 'private' in client_class.__module__
            models.append({
                "name": model_id,
                "display_name": getattr(client_class, 'DISPLAY_NAME', model_id),
                "default_parameters": client.get_default_parameters(),
                "is_private": is_private
            })
        except Exception:
            # Skip models with invalid configuration (missing API keys, etc.)
            pass

    return models


def get_discovered_model_names() -> List[str]:
    """Get list of all discovered model names (for debugging).

    Returns all discovered models regardless of configuration status.
    """
    _discover_models()
    return sorted(_discovered_models.keys())


def get_model_parameter_schema(model_name: str) -> List[Dict]:
    """Get the configurable parameter schema for a specific model.

    Args:
        model_name: The model identifier (DISPLAY_NAME)

    Returns:
        List of parameter schema dicts with name, type, default, etc.

    Raises:
        ValueError: If model is not found or cannot be instantiated
    """
    _discover_models()

    if model_name not in _discovered_models:
        raise ValueError(f"Model not found: {model_name}")

    try:
        client = _discovered_models[model_name]()
        schema = client.get_parameter_schema()
        # Convert to dict format for API/JSON serialization
        return [
            {
                "name": p.name,
                "type": p.type,
                "default": p.default,
                "description": p.description,
                "min_value": p.min_value,
                "max_value": p.max_value,
                "options": p.options,
                "required": p.required
            }
            for p in schema
        ]
    except Exception as e:
        raise ValueError(f"Failed to get schema for {model_name}: {e}")


def get_model_info(model_name: str) -> Dict:
    """Get metadata about a specific model.

    Args:
        model_name: The model identifier (DISPLAY_NAME)

    Returns:
        Dict with model metadata (name, display_name, provider, etc.)

    Raises:
        ValueError: If model is not found or cannot be instantiated
    """
    _discover_models()

    if model_name not in _discovered_models:
        raise ValueError(f"Model not found: {model_name}")

    try:
        client = _discovered_models[model_name]()
        info = client.get_model_info()
        return {
            "name": info.name,
            "display_name": info.display_name,
            "provider": info.provider,
            "description": info.description,
            "supports_vision": info.supports_vision,
            "supports_streaming": info.supports_streaming,
            "is_private": info.is_private
        }
    except Exception as e:
        raise ValueError(f"Failed to get info for {model_name}: {e}")


def get_all_models_with_schema() -> List[Dict]:
    """Get all available models with their parameter schemas.

    Returns:
        List of dicts with model info and parameter schema

    This is the main API for dynamic configuration UI.
    """
    _discover_models()

    result = []
    for model_id, client_class in _discovered_models.items():
        try:
            client = client_class()
            info = client.get_model_info()
            schema = client.get_parameter_schema()

            result.append({
                "name": info.name,
                "display_name": info.display_name,
                "provider": info.provider,
                "description": info.description,
                "supports_vision": info.supports_vision,
                "supports_streaming": info.supports_streaming,
                "is_private": info.is_private,
                "parameters": [
                    {
                        "name": p.name,
                        "type": p.type,
                        "default": p.default,
                        "description": p.description,
                        "min_value": p.min_value,
                        "max_value": p.max_value,
                        "options": p.options,
                        "required": p.required
                    }
                    for p in schema
                ]
            })
        except Exception:
            # Skip models that fail to initialize
            pass

    return result


def _mask_value(value: str) -> str:
    """Mask sensitive value for display.

    Shows first 4 and last 4 chars only.
    """
    if not value:
        return None
    if len(value) <= 8:
        return "****"
    return value[:4] + "****" + value[-4:]


def get_all_models_env_status() -> List[Dict]:
    """Get environment variable status for all discovered models.

    Returns all models with their environment variable configuration status,
    regardless of whether they can be instantiated.

    Returns:
        List of dicts with:
        - name: Model identifier (DISPLAY_NAME)
        - available: True if all required env vars are set
        - env_vars: List of env var status dicts
    """
    _discover_models()

    result = []
    for model_id, client_class in _discovered_models.items():
        try:
            # Get ENV_VARS from class (don't need to instantiate)
            env_vars = getattr(client_class, 'ENV_VARS', [])
            env_status = []
            is_configured = True

            for config in env_vars:
                # Check both model-specific and common env vars
                model_specific_value = os.getenv(config.model_specific)
                common_value = os.getenv(config.common)
                value = model_specific_value or common_value or config.default

                is_set = value is not None and value != ""
                if config.required and not is_set:
                    is_configured = False

                # Determine which env var was used
                used_var = None
                if model_specific_value:
                    used_var = config.model_specific
                elif common_value:
                    used_var = config.common

                env_status.append({
                    "key": config.key,
                    "model_specific": config.model_specific,
                    "common": config.common,
                    "required": config.required,
                    "is_set": is_set,
                    "used_var": used_var,
                    "masked_value": _mask_value(value) if is_set else None
                })

            result.append({
                "name": model_id,
                "available": is_configured,
                "env_vars": env_status
            })
        except Exception as e:
            logger.warning(f"Failed to get env status for {model_id}: {e}")

    return result

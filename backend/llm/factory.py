"""LLM client factory.

Based on specification in docs/req.txt section 8 (Phase 1).
Provides factory function to create appropriate LLM client.
"""

import os
from dotenv import load_dotenv
from typing import List, Dict

from .base import LLMClient
from .azure_gpt_4_1 import AzureGPT41Client
from .azure_gpt_4o import AzureGPT4oClient
from .azure_gpt_4o_mini import AzureGPT4oMiniClient
from .azure_gpt_5_mini import AzureGPT5MiniClient
from .azure_gpt_5_nano import AzureGPT5NanoClient
from .openai_gpt_4_nano import OpenAIGPT4NanoClient
from .openai_gpt_5_nano import OpenAIGPT5NanoClient
from .anthropic_claude import (
    ClaudeSonnet4Client,
    Claude35SonnetClient,
    Claude35HaikuClient,
    Claude3OpusClient
)

# Load private models if available (not tracked by git)
try:
    from .private import PRIVATE_MODELS
except ImportError:
    PRIVATE_MODELS = {}

# Load environment variables
load_dotenv()


def get_llm_client(model_name: str = None) -> LLMClient:
    """Get LLM client instance based on model name.

    Args:
        model_name: Model identifier. If None, uses ACTIVE_LLM_MODEL from env.
                   Options: 'azure-gpt-4.1', 'azure-gpt-4o', 'azure-gpt-4o-mini',
                           'azure-gpt-5-mini', 'azure-gpt-5-nano',
                           'openai-gpt-4.1-nano', 'openai-gpt-5-nano',
                           'claude-sonnet-4', 'claude-3.5-sonnet', 'claude-3.5-haiku', 'claude-3-opus'

    Returns:
        LLMClient instance

    Raises:
        ValueError: If model_name is not supported

    Specification: docs/req.txt section 8 (Phase 1)
    Extended to support Azure GPT-4o, GPT-4o-mini, GPT-5-mini, GPT-5-nano, OpenAI and Anthropic Claude models
    """
    if model_name is None:
        model_name = os.getenv("ACTIVE_LLM_MODEL", "azure-gpt-4.1")

    if model_name == "azure-gpt-4.1":
        return AzureGPT41Client()
    elif model_name == "azure-gpt-4o":
        return AzureGPT4oClient()
    elif model_name == "azure-gpt-4o-mini":
        return AzureGPT4oMiniClient()
    elif model_name == "azure-gpt-5-mini":
        return AzureGPT5MiniClient()
    elif model_name == "azure-gpt-5-nano":
        return AzureGPT5NanoClient()
    elif model_name == "openai-gpt-4.1-nano":
        return OpenAIGPT4NanoClient()
    elif model_name == "openai-gpt-5-nano":
        return OpenAIGPT5NanoClient()
    elif model_name == "claude-sonnet-4":
        return ClaudeSonnet4Client()
    elif model_name == "claude-3.5-sonnet":
        return Claude35SonnetClient()
    elif model_name == "claude-3.5-haiku":
        return Claude35HaikuClient()
    elif model_name == "claude-3-opus":
        return Claude3OpusClient()
    elif model_name in PRIVATE_MODELS:
        # Load private model
        _, client_class = PRIVATE_MODELS[model_name]
        return client_class()
    else:
        # Build supported models list including private models
        private_model_names = list(PRIVATE_MODELS.keys())
        private_str = f", {', '.join(repr(m) for m in private_model_names)}" if private_model_names else ""
        raise ValueError(
            f"Unsupported model: {model_name}. "
            f"Supported models: 'azure-gpt-4.1', 'azure-gpt-4o', 'azure-gpt-4o-mini', "
            f"'azure-gpt-5-mini', 'azure-gpt-5-nano', "
            f"'openai-gpt-4.1-nano', 'openai-gpt-5-nano', "
            f"'claude-sonnet-4', 'claude-3.5-sonnet', 'claude-3.5-haiku', 'claude-3-opus'"
            f"{private_str}"
        )


def get_available_models() -> List[Dict[str, any]]:
    """Get list of all available LLM models with their default parameters.

    Returns:
        List of dictionaries containing model information:
        - name: Model identifier
        - display_name: Human-readable name
        - default_parameters: Dictionary of default parameter values

    Note:
        Only returns models that have valid environment configuration.
        Models with missing configuration are skipped.
    """
    models = []

    # Try each model, skip if configuration is incomplete
    model_definitions = [
        ("azure-gpt-4.1", "Azure GPT-4.1", AzureGPT41Client),
        ("azure-gpt-4o", "Azure GPT-4o (2024-08-06)", AzureGPT4oClient),
        ("azure-gpt-4o-mini", "Azure GPT-4o-mini (2024-07-18)", AzureGPT4oMiniClient),
        ("azure-gpt-5-mini", "Azure GPT-5-mini", AzureGPT5MiniClient),
        ("azure-gpt-5-nano", "Azure GPT-5-nano", AzureGPT5NanoClient),
        ("openai-gpt-4.1-nano", "OpenAI GPT-4.1-nano", OpenAIGPT4NanoClient),
        ("openai-gpt-5-nano", "OpenAI GPT-5-nano", OpenAIGPT5NanoClient),
        ("claude-sonnet-4", "Claude Sonnet 4 (Latest)", ClaudeSonnet4Client),
        ("claude-3.5-sonnet", "Claude 3.5 Sonnet", Claude35SonnetClient),
        ("claude-3.5-haiku", "Claude 3.5 Haiku (Fast)", Claude35HaikuClient),
        ("claude-3-opus", "Claude 3 Opus (Most Capable)", Claude3OpusClient),
    ]

    for name, display_name, client_class in model_definitions:
        try:
            client = client_class()
            models.append({
                "name": name,
                "display_name": display_name,
                "default_parameters": client.get_default_parameters(),
                "is_private": False
            })
        except (ValueError, Exception) as e:
            # Skip models with incomplete configuration
            # This allows the system to work even if some models are not configured
            pass

    # Add private models (not tracked by git)
    for name, (display_name, client_class) in PRIVATE_MODELS.items():
        try:
            client = client_class()
            models.append({
                "name": name,
                "display_name": display_name,
                "default_parameters": client.get_default_parameters(),
                "is_private": True
            })
        except (ValueError, Exception) as e:
            # Skip models with incomplete configuration
            pass

    return models

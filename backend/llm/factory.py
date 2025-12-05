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

# Load environment variables
load_dotenv()


def get_llm_client(model_name: str = None) -> LLMClient:
    """Get LLM client instance based on model name.

    Args:
        model_name: Model identifier. If None, uses ACTIVE_LLM_MODEL from env.
                   Options: 'azure-gpt-4.1', 'azure-gpt-4o', 'azure-gpt-4o-mini',
                           'azure-gpt-5-mini', 'azure-gpt-5-nano',
                           'openai-gpt-4.1-nano', 'openai-gpt-5-nano'

    Returns:
        LLMClient instance

    Raises:
        ValueError: If model_name is not supported

    Specification: docs/req.txt section 8 (Phase 1)
    Extended to support Azure GPT-4o, GPT-4o-mini, GPT-5-mini, GPT-5-nano and OpenAI models
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
    else:
        raise ValueError(
            f"Unsupported model: {model_name}. "
            f"Supported models: 'azure-gpt-4.1', 'azure-gpt-4o', 'azure-gpt-4o-mini', "
            f"'azure-gpt-5-mini', 'azure-gpt-5-nano', "
            f"'openai-gpt-4.1-nano', 'openai-gpt-5-nano'"
        )


def get_available_models() -> List[Dict[str, any]]:
    """Get list of all available LLM models with their default parameters.

    Returns:
        List of dictionaries containing model information:
        - name: Model identifier
        - display_name: Human-readable name
        - default_parameters: Dictionary of default parameter values
    """
    models = [
        {
            "name": "azure-gpt-4.1",
            "display_name": "Azure GPT-4.1",
            "default_parameters": AzureGPT41Client().get_default_parameters()
        },
        {
            "name": "azure-gpt-4o",
            "display_name": "Azure GPT-4o (2024-08-06)",
            "default_parameters": AzureGPT4oClient().get_default_parameters()
        },
        {
            "name": "azure-gpt-4o-mini",
            "display_name": "Azure GPT-4o-mini (2024-07-18)",
            "default_parameters": AzureGPT4oMiniClient().get_default_parameters()
        },
        {
            "name": "azure-gpt-5-mini",
            "display_name": "Azure GPT-5-mini",
            "default_parameters": AzureGPT5MiniClient().get_default_parameters()
        },
        {
            "name": "azure-gpt-5-nano",
            "display_name": "Azure GPT-5-nano",
            "default_parameters": AzureGPT5NanoClient().get_default_parameters()
        },
        {
            "name": "openai-gpt-4.1-nano",
            "display_name": "OpenAI GPT-4.1-nano",
            "default_parameters": OpenAIGPT4NanoClient().get_default_parameters()
        },
        {
            "name": "openai-gpt-5-nano",
            "display_name": "OpenAI GPT-5-nano",
            "default_parameters": OpenAIGPT5NanoClient().get_default_parameters()
        }
    ]
    return models

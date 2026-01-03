"""Base LLM client interface.

Based on specification in docs/req.txt section 6 (LLM 呼び出し仕様)

Plugin Architecture:
- Each LLM client defines its own configurable parameters via get_parameter_schema()
- Parameters are self-contained within each plugin
- The system dynamically builds UI/API from the schema
- Environment variables are defined as metadata via ENV_VARS class attribute
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Union, Any


@dataclass
class LLMResponse:
    """Standard response from LLM execution."""
    success: bool
    response_text: Optional[str] = None
    error_message: Optional[str] = None
    turnaround_ms: Optional[int] = None


@dataclass
class ParameterSchema:
    """Schema for a configurable parameter.

    Used by plugins to define their configurable parameters.
    The system uses this to build dynamic configuration UI.
    """
    name: str
    type: str  # "float", "int", "str", "bool"
    default: Any
    description: str = ""
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    options: Optional[List[Any]] = None  # For enum-like parameters
    required: bool = True


@dataclass
class ModelInfo:
    """Metadata about an LLM model.

    Returned by get_model_info() for UI/API purposes.
    """
    name: str  # Unique identifier (DISPLAY_NAME)
    display_name: str  # Human-readable name
    provider: str  # e.g., "azure", "openai", "anthropic"
    description: str = ""
    supports_vision: bool = False
    supports_streaming: bool = False
    is_private: bool = False


@dataclass
class EnvVarConfig:
    """Configuration for an environment variable.

    Used by plugins to define their required environment variables.
    Supports model-specific variables with fallback to common variables.

    Example:
        EnvVarConfig(
            key="api_key",
            model_specific="AZURE_GPT41_API_KEY",
            common="AZURE_OPENAI_API_KEY"
        )
    """
    key: str                    # Internal key name (e.g., "api_key", "endpoint")
    model_specific: str         # Model-specific env var name (e.g., "AZURE_GPT41_API_KEY")
    common: str                 # Common/fallback env var name (e.g., "AZURE_OPENAI_API_KEY")
    required: bool = True       # Whether this env var is required
    default: Optional[str] = None  # Default value if not found


# Type alias for message format
# Each message is a dict with 'role' and 'content' keys
# role: 'system', 'user', or 'assistant'
# content: str or list (for multimodal content)
Message = Dict[str, Union[str, list]]


class LLMClient(ABC):
    """Abstract base class for LLM clients.

    Plugin Requirements:
    - Define DISPLAY_NAME class attribute for auto-discovery
    - Define ENV_VARS list for environment variable configuration
    - Implement all abstract methods
    - Optionally override get_parameter_schema() for configurable params
    - Optionally override get_model_info() for metadata

    Environment Variable Management:
    - Define ENV_VARS as a list of EnvVarConfig objects
    - Use _get_env_var(key) to get values with fallback
    - Use _validate_env_vars() in __init__ to check required vars
    """

    # Override in subclasses with list of EnvVarConfig
    ENV_VARS: List[EnvVarConfig] = []

    def _get_env_var(self, key: str) -> Optional[str]:
        """Get environment variable value with fallback.

        Checks model-specific var first, then falls back to common var.

        Args:
            key: Internal key name (e.g., "api_key")

        Returns:
            Environment variable value or None
        """
        for config in self.ENV_VARS:
            if config.key == key:
                # Try model-specific first
                value = os.getenv(config.model_specific)
                if value:
                    return value
                # Fallback to common
                value = os.getenv(config.common)
                if value:
                    return value
                # Return default if exists
                return config.default
        return None

    def _validate_env_vars(self) -> None:
        """Validate that all required environment variables are set.

        Raises:
            ValueError: If any required env var is missing
        """
        missing = []
        for config in self.ENV_VARS:
            if config.required:
                value = self._get_env_var(config.key)
                if not value:
                    missing.append(f"{config.model_specific} or {config.common}")
        if missing:
            raise ValueError(
                f"Environment variable configuration incomplete. "
                f"Please set: {', '.join(missing)}"
            )

    def is_configured(self) -> bool:
        """Check if all required environment variables are set.

        Returns:
            True if all required env vars are set
        """
        for config in self.ENV_VARS:
            if config.required:
                value = self._get_env_var(config.key)
                if not value:
                    return False
        return True

    def get_env_status(self) -> List[Dict]:
        """Get environment variable status for UI display.

        Returns:
            List of dicts with env var status (masked values for security)
        """
        result = []
        for config in self.ENV_VARS:
            value = self._get_env_var(config.key)
            # Determine which env var was used
            used_var = None
            if os.getenv(config.model_specific):
                used_var = config.model_specific
            elif os.getenv(config.common):
                used_var = config.common

            result.append({
                "key": config.key,
                "model_specific": config.model_specific,
                "common": config.common,
                "required": config.required,
                "is_set": value is not None and value != "",
                "used_var": used_var,
                "masked_value": self._mask_value(value) if value else None
            })
        return result

    @staticmethod
    def _mask_value(value: str) -> str:
        """Mask sensitive value for display.

        Shows first 4 and last 4 chars only.

        Args:
            value: The value to mask

        Returns:
            Masked value (e.g., "sk-a****1234")
        """
        if not value:
            return None
        if len(value) <= 8:
            return "****"
        return value[:4] + "****" + value[-4:]

    @abstractmethod
    def call(
        self,
        prompt: str = None,
        messages: List[Message] = None,
        images: list = None,
        **kwargs
    ) -> LLMResponse:
        """Execute LLM call with given prompt/messages and optional images.

        Supports two modes:
        1. Simple mode: Pass a single prompt string (backward compatible)
        2. Messages mode: Pass a list of messages with roles

        Args:
            prompt: The prompt text to send to LLM (simple mode, treated as 'user' role)
            messages: List of message dicts with 'role' and 'content' keys
                      Example: [
                          {"role": "system", "content": "You are a helpful assistant."},
                          {"role": "user", "content": "Hello!"}
                      ]
            images: Optional list of base64-encoded image strings for Vision API
                    (attached to the last user message)
            **kwargs: Additional parameters (temperature, max_tokens, etc.)

        Returns:
            LLMResponse object with result or error

        Note:
            - If both prompt and messages are provided, messages takes precedence
            - If only prompt is provided, it's treated as a single user message
            - Images are attached to the last user message in the messages list

        Specification: docs/req.txt section 6.1, docs/image_parameter_spec.md
        """
        pass

    @abstractmethod
    def get_default_parameters(self) -> dict:
        """Get default parameters for this LLM client.

        Returns:
            Dictionary of default parameter values
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Get the model name identifier.

        Returns:
            Model name string (e.g., 'azure-gpt-4.1')
        """
        pass

    def get_parameter_schema(self) -> List[ParameterSchema]:
        """Get the configurable parameters schema for this model.

        Override this method to define custom configurable parameters.
        The system uses this schema to dynamically build settings UI.

        Returns:
            List of ParameterSchema objects defining configurable params

        Default implementation returns common LLM parameters.
        """
        return [
            ParameterSchema(
                name="temperature",
                type="float",
                default=0.7,
                description="Controls randomness. Higher = more creative.",
                min_value=0.0,
                max_value=2.0
            ),
            ParameterSchema(
                name="max_tokens",
                type="int",
                default=4096,
                description="Maximum tokens in response.",
                min_value=1,
                max_value=128000
            ),
            ParameterSchema(
                name="top_p",
                type="float",
                default=1.0,
                description="Nucleus sampling parameter.",
                min_value=0.0,
                max_value=1.0
            ),
        ]

    def get_model_info(self) -> ModelInfo:
        """Get metadata about this model.

        Override this method to provide model-specific metadata.
        Used by UI and API to display model information.

        Returns:
            ModelInfo object with model metadata
        """
        display_name = getattr(self, 'DISPLAY_NAME', 'unknown')
        return ModelInfo(
            name=display_name,
            display_name=display_name,
            provider="unknown",
            description="",
            supports_vision=False,
            supports_streaming=False,
            is_private=False
        )

    def _normalize_messages(
        self,
        prompt: str = None,
        messages: List[Message] = None,
        images: list = None
    ) -> List[Message]:
        """Normalize input to a list of messages.

        Helper method to convert prompt/messages/images to a unified format.

        Args:
            prompt: Simple prompt string
            messages: List of message dicts
            images: Optional images to attach

        Returns:
            List of normalized messages
        """
        # Use messages if provided, otherwise create from prompt
        if messages:
            result = [msg.copy() for msg in messages]
        elif prompt:
            result = [{"role": "user", "content": prompt}]
        else:
            result = []

        # Attach images to the last user message if provided
        if images and result:
            # Find the last user message
            for i in range(len(result) - 1, -1, -1):
                if result[i].get("role") == "user":
                    content = result[i].get("content", "")
                    # Convert to multimodal format if not already
                    if isinstance(content, str):
                        result[i]["content"] = [{"type": "text", "text": content}]
                    # Images will be added by the specific client implementation
                    result[i]["_images"] = images
                    break

        return result

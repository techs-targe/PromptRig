"""Base LLM client interface.

Based on specification in docs/req.txt section 6 (LLM 呼び出し仕様)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List, Dict, Union


@dataclass
class LLMResponse:
    """Standard response from LLM execution."""
    success: bool
    response_text: Optional[str] = None
    error_message: Optional[str] = None
    turnaround_ms: Optional[int] = None


# Type alias for message format
# Each message is a dict with 'role' and 'content' keys
# role: 'system', 'user', or 'assistant'
# content: str or list (for multimodal content)
Message = Dict[str, Union[str, list]]


class LLMClient(ABC):
    """Abstract base class for LLM clients."""

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

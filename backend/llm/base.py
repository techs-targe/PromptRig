"""Base LLM client interface.

Based on specification in docs/req.txt section 6 (LLM 呼び出し仕様)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResponse:
    """Standard response from LLM execution."""
    success: bool
    response_text: Optional[str] = None
    error_message: Optional[str] = None
    turnaround_ms: Optional[int] = None


class LLMClient(ABC):
    """Abstract base class for LLM clients."""

    @abstractmethod
    def call(self, prompt: str, **kwargs) -> LLMResponse:
        """Execute LLM call with given prompt.

        Args:
            prompt: The prompt text to send to LLM
            **kwargs: Additional parameters (temperature, max_tokens, etc.)

        Returns:
            LLMResponse object with result or error

        Specification: docs/req.txt section 6.1
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

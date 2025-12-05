"""Azure OpenAI GPT-5-nano client implementation.

Based on Azure OpenAI API specification.
"""

import os
import time
from typing import Optional
from openai import AzureOpenAI
from dotenv import load_dotenv

from .base import LLMClient, LLMResponse

# Load environment variables
load_dotenv()


class AzureGPT5NanoClient(LLMClient):
    """Azure OpenAI GPT-5-nano client.

    Configuration from environment variables:
    - AZURE_OPENAI_ENDPOINT
    - AZURE_OPENAI_API_KEY
    - AZURE_OPENAI_GPT5_NANO_DEPLOYMENT_NAME (defaults to AZURE_OPENAI_DEPLOYMENT_NAME)
    - AZURE_OPENAI_API_VERSION
    """

    def __init__(self):
        """Initialize Azure OpenAI GPT-5-nano client with environment configuration."""
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
        # Use GPT-5-nano specific deployment name, or fall back to default
        self.deployment_name = os.getenv(
            "AZURE_OPENAI_GPT5_NANO_DEPLOYMENT_NAME",
            os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        )
        # GPT-5 requires API version 2025-01-01-preview or later
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

        # Validate configuration
        if not all([self.endpoint, self.api_key, self.deployment_name]):
            raise ValueError(
                "Azure OpenAI configuration incomplete. "
                "Please set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, "
                "and AZURE_OPENAI_GPT5_NANO_DEPLOYMENT_NAME (or AZURE_OPENAI_DEPLOYMENT_NAME) in .env file."
            )

        # Initialize client
        self.client = AzureOpenAI(
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
            api_version=self.api_version
        )

    def call(self, prompt: str, **kwargs) -> LLMResponse:
        """Execute Azure OpenAI GPT-5-nano call.

        Args:
            prompt: The prompt text to send
            **kwargs: Optional parameters
                - temperature (float): 0.0-2.0, controls randomness (default: 0.7)
                - verbosity (str): "low", "medium", "high" - output detail level (default: "medium")
                - reasoning_effort (str): "minimal", "low", "medium", "high" - reasoning depth (default: "medium")
                - max_tokens (int): Maximum completion tokens (default: 4096)

        Note:
            GPT-5 models use chat.completions.create() API.
            API version must be 2025-01-01-preview or later.
            Reference: Azure OpenAI GPT-5 documentation

        Returns:
            LLMResponse with result or error
        """
        start_time = time.time()

        try:
            # Get parameters with defaults
            # Note: GPT-5 has temperature fixed at 1.0 - attempting to set it will cause an error
            verbosity = kwargs.get("verbosity", "medium")
            reasoning_effort = kwargs.get("reasoning_effort", "medium")
            max_tokens = kwargs.get("max_tokens", 4096)

            # Prepare messages with system and user roles
            messages = [
                {"role": "system", "content": "You are a helpful AI assistant."},
                {"role": "user", "content": prompt}
            ]

            # Call Azure OpenAI GPT-5 API using chat.completions.create()
            # Reference: Azure OpenAI GPT-5 SDK documentation
            # Note: Do NOT set temperature - it's fixed at 1.0 for GPT-5 models
            completion = self.client.chat.completions.create(
                model=self.deployment_name,
                messages=messages,
                verbosity=verbosity,
                reasoning_effort=reasoning_effort,
                max_completion_tokens=max_tokens,
                stop=None,
                stream=False
            )

            # Calculate turnaround time
            turnaround_ms = int((time.time() - start_time) * 1000)

            # Extract response text
            output_text = completion.choices[0].message.content

            return LLMResponse(
                success=True,
                response_text=output_text,
                error_message=None,
                turnaround_ms=turnaround_ms
            )

        except Exception as e:
            turnaround_ms = int((time.time() - start_time) * 1000)

            return LLMResponse(
                success=False,
                response_text=None,
                error_message=str(e),
                turnaround_ms=turnaround_ms
            )

    def get_default_parameters(self) -> dict:
        """Get default parameters for Azure GPT-5-nano.

        Returns:
            Dictionary of default parameter values

        Note:
            GPT-5 models have temperature FIXED at 1.0 (cannot be changed).
            Supported parameters:
            - verbosity: "low", "medium", "high" (default: "medium")
            - reasoning_effort: "minimal", "low", "medium", "high" (default: "medium")
            - max_tokens: Maximum completion tokens (default: 4096)
        """
        return {
            "verbosity": "medium",
            "reasoning_effort": "medium",
            "max_tokens": 4096
        }

    def get_model_name(self) -> str:
        """Get model name identifier.

        Returns:
            'azure-gpt-5-nano'
        """
        return "azure-gpt-5-nano"

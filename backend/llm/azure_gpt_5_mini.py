"""Azure OpenAI GPT-5-mini client implementation.

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


class AzureGPT5MiniClient(LLMClient):
    """Azure OpenAI GPT-5-mini client.

    Configuration from environment variables:
    - AZURE_OPENAI_ENDPOINT
    - AZURE_OPENAI_API_KEY
    - AZURE_OPENAI_GPT5_MINI_DEPLOYMENT_NAME (defaults to AZURE_OPENAI_DEPLOYMENT_NAME)
    - AZURE_OPENAI_API_VERSION
    """

    def __init__(self):
        """Initialize Azure OpenAI GPT-5-mini client with environment configuration."""
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
        # Use GPT-5-mini specific deployment name, or fall back to default
        self.deployment_name = os.getenv(
            "AZURE_OPENAI_GPT5_MINI_DEPLOYMENT_NAME",
            os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        )
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

        # Validate configuration
        if not all([self.endpoint, self.api_key, self.deployment_name]):
            raise ValueError(
                "Azure OpenAI configuration incomplete. "
                "Please set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, "
                "and AZURE_OPENAI_GPT5_MINI_DEPLOYMENT_NAME (or AZURE_OPENAI_DEPLOYMENT_NAME) in .env file."
            )

        # Initialize client
        self.client = AzureOpenAI(
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
            api_version=self.api_version
        )

    def call(self, prompt: str, **kwargs) -> LLMResponse:
        """Execute Azure OpenAI GPT-5-mini call.

        Args:
            prompt: The prompt text to send
            **kwargs: Optional parameters
                - temperature (float): Default 0.5
                - max_tokens (int): Default 8000
                - top_p (float): Default 1.0
                - verbosity (str): Default "medium" - Controls output expansiveness ("low", "medium", "high")
                - reasoning_effort (str): Default "medium" - Controls reasoning tokens ("minimal", "medium")

        Returns:
            LLMResponse with result or error
        """
        start_time = time.time()

        try:
            # Get parameters with defaults
            temperature = kwargs.get("temperature", 0.5)
            max_tokens = kwargs.get("max_tokens", 8000)
            top_p = kwargs.get("top_p", 1.0)
            verbosity = kwargs.get("verbosity", "medium")
            reasoning_effort = kwargs.get("reasoning_effort", "medium")

            # Build API call parameters
            api_params = {
                "model": self.deployment_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
                "verbosity": verbosity,
                "reasoning_effort": reasoning_effort
            }

            # Call Azure OpenAI API
            response = self.client.chat.completions.create(**api_params)

            # Calculate turnaround time
            turnaround_ms = int((time.time() - start_time) * 1000)

            # Extract response text
            response_text = response.choices[0].message.content

            return LLMResponse(
                success=True,
                response_text=response_text,
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
        """Get default parameters for Azure GPT-5-mini.

        Returns:
            Dictionary of default parameter values
        """
        return {
            "temperature": 0.5,
            "max_tokens": 8000,
            "top_p": 1.0,
            "verbosity": "medium",
            "reasoning_effort": "medium"
        }

    def get_model_name(self) -> str:
        """Get model name identifier.

        Returns:
            'azure-gpt-5-mini'
        """
        return "azure-gpt-5-mini"

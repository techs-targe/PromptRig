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
        # GPT-5 requires API version 2025-01-01-preview or later
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

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
            **kwargs: Optional parameters (Note: GPT-5 has fixed parameters)

        Note:
            GPT-5 models use chat.completions.create() API.
            API version must be 2025-01-01-preview or later.
            Temperature is fixed at 1.0 and cannot be changed.
            Reference: Azure AI Foundry GPT-5 documentation

        Returns:
            LLMResponse with result or error
        """
        start_time = time.time()

        try:
            # Prepare messages with developer role
            messages = [
                {
                    "role": "developer",
                    "content": [
                        {
                            "type": "text",
                            "text": "You are a helpful AI assistant."
                        }
                    ]
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]

            # Call Azure OpenAI GPT-5 API using chat.completions.create()
            # Reference: Azure AI Foundry sample code (2025-01-01-preview)
            completion = self.client.chat.completions.create(
                model=self.deployment_name,
                messages=messages,
                max_completion_tokens=4096,
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
        """Get default parameters for Azure GPT-5-mini.

        Returns:
            Dictionary of default parameter values

        Note:
            GPT-5 models have fixed parameters.
            Temperature is fixed at 1.0 and cannot be changed.
            max_completion_tokens is set to 4096 by default.
        """
        return {}

    def get_model_name(self) -> str:
        """Get model name identifier.

        Returns:
            'azure-gpt-5-mini'
        """
        return "azure-gpt-5-mini"

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
        # GPT-5 requires API version 2025-03-01-preview
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-03-01-preview")

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
                - verbosity (str): Default "medium" - Controls output expansiveness ("low", "medium", "high")
                - reasoning_effort (str): Default "minimal" - Controls reasoning tokens ("minimal", "medium")

        Note:
            GPT-5 models use responses.create() API (not chat.completions.create()).
            API version must be 2025-03-01-preview or later.
            Reference: Azure AI Foundry GPT-5 documentation

        Returns:
            LLMResponse with result or error
        """
        start_time = time.time()

        try:
            # Get GPT-5 specific parameters
            verbosity = kwargs.get("verbosity", "medium")
            reasoning_effort = kwargs.get("reasoning_effort", "minimal")  # nano defaults to minimal

            # Call Azure OpenAI GPT-5 API using responses.create()
            # Reference: Azure AI Foundry sample code
            response = self.client.responses.create(
                model=self.deployment_name,
                input=prompt,
                text={"verbosity": verbosity}
                # Note: reasoning_effort may not be supported in Azure OpenAI GPT-5
                # Only verbosity is confirmed in the sample code
            )

            # Calculate turnaround time
            turnaround_ms = int((time.time() - start_time) * 1000)

            # Extract response text from response.output
            output_text = ""
            for item in response.output:
                if hasattr(item, "content") and item.content:
                    for content in item.content:
                        if hasattr(content, "text") and content.text:
                            output_text += content.text

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
            GPT-5 models only support verbosity and reasoning_effort.
            Temperature is fixed at 1.0 and cannot be changed.
        """
        return {
            "verbosity": "medium",
            "reasoning_effort": "minimal"
        }

    def get_model_name(self) -> str:
        """Get model name identifier.

        Returns:
            'azure-gpt-5-nano'
        """
        return "azure-gpt-5-nano"

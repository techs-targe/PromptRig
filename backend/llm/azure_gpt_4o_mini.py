"""Azure OpenAI GPT-4o-mini client implementation.

GPT-4o-mini (2024-07-18) with Vision API support.
"""

import os
import time
from typing import Optional
from openai import AzureOpenAI
from dotenv import load_dotenv

from .base import LLMClient, LLMResponse

# Load environment variables
load_dotenv()


class AzureGPT4oMiniClient(LLMClient):
    """Azure OpenAI GPT-4o-mini client.

    Configuration from environment variables:
    - AZURE_OPENAI_ENDPOINT
    - AZURE_OPENAI_API_KEY
    - AZURE_OPENAI_GPT4O_MINI_DEPLOYMENT_NAME
    - AZURE_OPENAI_API_VERSION

    Model: gpt-4o-mini (version: 2024-07-18)
    Supports: Vision API, multimodal inputs
    """

    def __init__(self):
        """Initialize Azure OpenAI GPT-4o-mini client with environment configuration."""
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
        # Use GPT-4o-mini specific deployment name
        self.deployment_name = os.getenv("AZURE_OPENAI_GPT4O_MINI_DEPLOYMENT_NAME")
        # GPT-4o-mini supports API version 2024-02-15-preview or later
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

        # Validate configuration
        if not all([self.endpoint, self.api_key, self.deployment_name]):
            raise ValueError(
                "Azure OpenAI GPT-4o-mini configuration incomplete. "
                "Please set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, "
                "and AZURE_OPENAI_GPT4O_MINI_DEPLOYMENT_NAME in .env file."
            )

        # Initialize client
        self.client = AzureOpenAI(
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
            api_version=self.api_version
        )

    def call(self, prompt: str, images: list = None, **kwargs) -> LLMResponse:
        """Execute Azure OpenAI GPT-4o-mini call.

        Args:
            prompt: The prompt text to send
            images: Optional list of base64-encoded image strings for Vision API
            **kwargs: Optional parameters
                - temperature (float): Default 0.7 (range: 0.0-2.0)
                - max_tokens (int): Default 4096
                - top_p (float): Default 1.0

        Returns:
            LLMResponse with result or error

        Note:
            GPT-4o-mini (2024-07-18) supports Vision API for multimodal inputs.
            Specification: docs/image_parameter_spec.md
        """
        start_time = time.time()

        try:
            # Get parameters with defaults
            temperature = kwargs.get("temperature", 0.7)
            max_tokens = kwargs.get("max_tokens", 4096)
            top_p = kwargs.get("top_p", 1.0)

            # Build user content (text + optional images for Vision API)
            if images:
                # Multimodal content with images
                user_content = [{"type": "text", "text": prompt}]
                for img_base64 in images:
                    user_content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{img_base64}"
                        }
                    })
            else:
                # Text-only content
                user_content = prompt

            # Call Azure OpenAI API
            response = self.client.chat.completions.create(
                model=self.deployment_name,
                messages=[
                    {"role": "user", "content": user_content}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p
            )

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
        """Get default parameters for Azure GPT-4o-mini.

        Returns:
            Dictionary of default parameter values
        """
        return {
            "temperature": 0.7,
            "max_tokens": 4096,
            "top_p": 1.0
        }

    def get_model_name(self) -> str:
        """Get model name identifier.

        Returns:
            'azure-gpt-4o-mini'
        """
        return "azure-gpt-4o-mini"

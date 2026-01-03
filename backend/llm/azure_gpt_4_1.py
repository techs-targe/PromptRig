"""Azure OpenAI GPT-4.1 client implementation.

Based on specification in docs/req.txt section 6.1 (Azure OpenAI GPT-4.1)
"""

import os
import time
from typing import Optional, List
from openai import AzureOpenAI
from dotenv import load_dotenv

from .base import LLMClient, LLMResponse, Message, EnvVarConfig

# Load environment variables
load_dotenv()


class AzureGPT41Client(LLMClient):
    """Azure OpenAI GPT-4.1 client.

    Configuration from environment variables:
    - AZURE_GPT41_ENDPOINT or AZURE_OPENAI_ENDPOINT
    - AZURE_GPT41_API_KEY or AZURE_OPENAI_API_KEY
    - AZURE_GPT41_DEPLOYMENT_NAME or AZURE_OPENAI_DEPLOYMENT_NAME
    - AZURE_GPT41_API_VERSION or AZURE_OPENAI_API_VERSION

    Specification: docs/req.txt section 6.1
    """

    # Model identifier for auto-discovery
    DISPLAY_NAME = "azure-gpt-4.1"

    # Environment variable configuration
    ENV_VARS = [
        EnvVarConfig("endpoint", "AZURE_GPT41_ENDPOINT", "AZURE_OPENAI_ENDPOINT"),
        EnvVarConfig("api_key", "AZURE_GPT41_API_KEY", "AZURE_OPENAI_API_KEY"),
        EnvVarConfig("deployment", "AZURE_GPT41_DEPLOYMENT_NAME", "AZURE_OPENAI_DEPLOYMENT_NAME"),
        EnvVarConfig("api_version", "AZURE_GPT41_API_VERSION", "AZURE_OPENAI_API_VERSION",
                     required=False, default="2024-02-15-preview"),
    ]

    def __init__(self):
        """Initialize Azure OpenAI client with environment configuration."""
        self._validate_env_vars()

        self.endpoint = self._get_env_var("endpoint")
        self.api_key = self._get_env_var("api_key")
        self.deployment_name = self._get_env_var("deployment")
        self.api_version = self._get_env_var("api_version")

        # Initialize client
        self.client = AzureOpenAI(
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
            api_version=self.api_version
        )

    def call(
        self,
        prompt: str = None,
        messages: List[Message] = None,
        images: list = None,
        **kwargs
    ) -> LLMResponse:
        """Execute Azure OpenAI GPT-4.1 call.

        Args:
            prompt: The prompt text to send (simple mode, treated as 'user' role)
            messages: List of message dicts with 'role' and 'content' keys
            images: Optional list of base64-encoded image strings for Vision API
            **kwargs: Optional parameters
                - temperature (float): Default 0.2
                - max_tokens (int): Default 4000
                - top_p (float): Default 1.0

        Returns:
            LLMResponse with result or error

        Specification: docs/req.txt section 6.1, docs/image_parameter_spec.md
        """
        start_time = time.time()

        try:
            # Get parameters with defaults
            temperature = kwargs.get("temperature", 0.2)
            max_tokens = kwargs.get("max_tokens", 4000)
            top_p = kwargs.get("top_p", 1.0)

            # Normalize input to messages list
            normalized_messages = self._normalize_messages(prompt, messages, images)

            # Build API messages format
            api_messages = []
            for msg in normalized_messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                msg_images = msg.get("_images")

                # Handle multimodal content (images)
                if msg_images and role == "user":
                    if isinstance(content, str):
                        api_content = [{"type": "text", "text": content}]
                    else:
                        api_content = content.copy() if isinstance(content, list) else [content]

                    for img_data_uri in msg_images:
                        api_content.append({
                            "type": "image_url",
                            "image_url": {"url": img_data_uri}
                        })
                    api_messages.append({"role": role, "content": api_content})
                else:
                    # Text-only content
                    if isinstance(content, list):
                        # Extract text from list format
                        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                        api_messages.append({"role": role, "content": "".join(text_parts)})
                    else:
                        api_messages.append({"role": role, "content": content})

            # Call Azure OpenAI API
            response = self.client.chat.completions.create(
                model=self.deployment_name,
                messages=api_messages,
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
        """Get default parameters for Azure GPT-4.1.

        Returns:
            Dictionary of default parameter values
        """
        return {
            "temperature": 0.2,
            "max_tokens": 4000,
            "top_p": 1.0
        }

    def get_model_name(self) -> str:
        """Get model name identifier.

        Returns:
            'azure-gpt-4.1'
        """
        return "azure-gpt-4.1"

"""OpenAI GPT-5-nano client implementation.

Based on OpenAI API specification for GPT-5 models.
"""

import os
import time
from typing import Optional, List
from openai import OpenAI
from dotenv import load_dotenv

from .base import LLMClient, LLMResponse, Message, EnvVarConfig

# Load environment variables
load_dotenv()


class OpenAIGPT5NanoClient(LLMClient):
    """OpenAI GPT-5-nano client.

    Configuration from environment variables:
    - OPENAI_GPT5_NANO_API_KEY or OPENAI_API_KEY
    """

    # Model identifier for gpt-5-nano
    MODEL_NAME = "gpt-5-nano"
    DISPLAY_NAME = "openai-gpt-5-nano"

    # Environment variable configuration
    ENV_VARS = [
        EnvVarConfig("api_key", "OPENAI_GPT5_NANO_API_KEY", "OPENAI_API_KEY"),
    ]

    def __init__(self):
        """Initialize OpenAI client with environment configuration."""
        self._validate_env_vars()

        self.api_key = self._get_env_var("api_key")

        # Initialize client
        self.client = OpenAI(api_key=self.api_key)

    def call(
        self,
        prompt: str = None,
        messages: List[Message] = None,
        images: list = None,
        **kwargs
    ) -> LLMResponse:
        """Execute OpenAI GPT-5-nano call.

        Args:
            prompt: The prompt text to send (simple mode, treated as 'user' role)
            messages: List of message dicts with 'role' and 'content' keys
            images: Optional list of base64-encoded image strings for Vision API
            **kwargs: Optional parameters
                - verbosity (str): Default "medium" - Controls output expansiveness ("low", "medium", "high")
                - reasoning_effort (str): Default "minimal" - Controls reasoning tokens ("minimal", "medium")

        Note:
            GPT-5 models only support temperature=1.0 (fixed).
            Other sampling parameters (top_p, max_tokens, frequency_penalty, etc.) are not supported.
            Reference: https://community.openai.com/t/temperature-in-gpt-5-models/1337133

        Returns:
            LLMResponse with result or error

        Specification: docs/image_parameter_spec.md
        """
        start_time = time.time()

        try:
            # Get GPT-5 specific parameters
            verbosity = kwargs.get("verbosity", "medium")
            reasoning_effort = kwargs.get("reasoning_effort", "minimal")

            # Normalize input to messages list
            normalized_messages = self._normalize_messages(prompt, messages, images)

            # Build API messages format
            api_messages = []

            # Check if system message exists, if not add default
            has_system = any(msg.get("role") == "system" for msg in normalized_messages)
            if not has_system:
                api_messages.append({"role": "system", "content": "You are a helpful AI assistant."})

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
                            "image_url": {"url": img_data_uri, "detail": "high"}
                        })
                    api_messages.append({"role": role, "content": api_content})
                else:
                    # Text-only content
                    if isinstance(content, list):
                        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                        api_messages.append({"role": role, "content": "".join(text_parts)})
                    else:
                        api_messages.append({"role": role, "content": content})

            # Get max tokens parameter (GPT-5 uses max_completion_tokens, not max_tokens)
            max_tokens = kwargs.get("max_output_tokens", kwargs.get("max_tokens", None))

            # Build API call parameters
            create_params = {
                "model": self.MODEL_NAME,
                "messages": api_messages
            }

            # Add max_completion_tokens if specified (GPT-5 models require this instead of max_tokens)
            if max_tokens:
                create_params["max_completion_tokens"] = max_tokens

            # Call OpenAI GPT-5 API
            response = self.client.chat.completions.create(**create_params)

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
        """Get default parameters for OpenAI GPT-5-nano.

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
            'openai-gpt-5-nano'
        """
        return "openai-gpt-5-nano"

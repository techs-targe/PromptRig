"""OpenAI o4-mini client implementation.

o4-mini is a fast, cost-efficient reasoning model released April 16, 2025.
Reference: https://platform.openai.com/docs/models/o4-mini
"""

import os
import time
from typing import Optional, List
from openai import OpenAI
from dotenv import load_dotenv

from .base import LLMClient, LLMResponse, Message, EnvVarConfig

# Load environment variables
load_dotenv()


class OpenAIO4MiniClient(LLMClient):
    """OpenAI o4-mini client.

    o4-mini is a reasoning model capable of deep analysis across tasks
    like coding, math, and scientific reasoning.

    Configuration from environment variables:
    - OPENAI_O4_MINI_API_KEY or OPENAI_API_KEY
    """

    # Model identifier for o4-mini
    MODEL_NAME = "o4-mini"
    DISPLAY_NAME = "openai-o4-mini"

    # Environment variable configuration
    ENV_VARS = [
        EnvVarConfig("api_key", "OPENAI_O4_MINI_API_KEY", "OPENAI_API_KEY"),
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
        """Execute OpenAI o4-mini call.

        Args:
            prompt: The prompt text to send (simple mode, treated as 'user' role)
            messages: List of message dicts with 'role' and 'content' keys
            images: Optional list of base64-encoded image strings for Vision API
            **kwargs: Optional parameters
                - max_output_tokens (int): Maximum completion tokens
                - reasoning_effort (str): Controls reasoning depth ("low", "medium", "high")

        Note:
            o4-mini is a reasoning model with fixed temperature=1.0.
            Uses max_completion_tokens instead of max_tokens.

        Returns:
            LLMResponse with result or error
        """
        start_time = time.time()

        try:
            # Normalize input to messages list
            normalized_messages = self._normalize_messages(prompt, messages, images)

            # Build API messages format
            api_messages = []

            # Note: o4-mini reasoning models may not support system messages in the same way
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

            # Get max tokens parameter (o4-mini uses max_completion_tokens, not max_tokens)
            max_tokens = kwargs.get("max_output_tokens", kwargs.get("max_tokens", None))

            # Build API call parameters
            create_params = {
                "model": self.MODEL_NAME,
                "messages": api_messages
            }

            # Add max_completion_tokens if specified
            if max_tokens:
                create_params["max_completion_tokens"] = max_tokens

            # Call OpenAI o4-mini API
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
        """Get default parameters for OpenAI o4-mini.

        Returns:
            Dictionary of default parameter values

        Note:
            o4-mini is a reasoning model with fixed temperature.
            max_output_tokens controls the maximum completion length.
        """
        return {
            "max_output_tokens": 16384
        }

    def get_model_name(self) -> str:
        """Get model name identifier.

        Returns:
            'openai-o4-mini'
        """
        return "openai-o4-mini"

"""OpenAI GPT-4.1-nano client implementation.

Based on specification in docs/req.txt section 8 (Phase 1).
Uses OpenAI gpt-4.1-nano (2025 model) as secondary LLM provider.
"""

import os
import time
from typing import Optional, List
from openai import OpenAI
from dotenv import load_dotenv

from .base import LLMClient, LLMResponse, Message

# Load environment variables
load_dotenv()


class OpenAIGPT4NanoClient(LLMClient):
    """OpenAI GPT-4.1-nano client.

    Configuration from environment variables:
    - OPENAI_API_KEY

    Specification: docs/req.txt section 8 (Phase 1)
    """

    # Model identifier for gpt-4.1-nano
    MODEL_NAME = "gpt-4o-mini"  # Using available model name

    def __init__(self):
        """Initialize OpenAI client with environment configuration."""
        self.api_key = os.getenv("OPENAI_API_KEY")

        # Validate configuration
        if not self.api_key:
            raise ValueError(
                "OpenAI configuration incomplete. "
                "Please set OPENAI_API_KEY in .env file."
            )

        # Initialize client
        self.client = OpenAI(api_key=self.api_key)

    def call(
        self,
        prompt: str = None,
        messages: List[Message] = None,
        images: list = None,
        **kwargs
    ) -> LLMResponse:
        """Execute OpenAI GPT-4.1-nano call.

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
                        print(f"📷 Vision API: Adding image (data URI length: {len(img_data_uri)} chars)")
                        api_content.append({
                            "type": "image_url",
                            "image_url": {"url": img_data_uri, "detail": "high"}
                        })
                    print(f"📤 Vision API: Sending {len(msg_images)} image(s) with prompt")
                    api_messages.append({"role": role, "content": api_content})
                else:
                    # Text-only content
                    if isinstance(content, list):
                        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                        api_messages.append({"role": role, "content": "".join(text_parts)})
                    else:
                        api_messages.append({"role": role, "content": content})

            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=self.MODEL_NAME,
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
        """Get default parameters for OpenAI GPT-4.1-nano.

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
            'openai-gpt-4.1-nano'
        """
        return "openai-gpt-4.1-nano"

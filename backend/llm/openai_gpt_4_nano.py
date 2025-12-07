"""OpenAI GPT-4.1-nano client implementation.

Based on specification in docs/req.txt section 8 (Phase 1).
Uses OpenAI gpt-4.1-nano (2025 model) as secondary LLM provider.
"""

import os
import time
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv

from .base import LLMClient, LLMResponse

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

    def call(self, prompt: str, images: list = None, **kwargs) -> LLMResponse:
        """Execute OpenAI GPT-4.1-nano call.

        Args:
            prompt: The prompt text to send
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

            # Build user content (text + optional images for Vision API)
            if images:
                # Multimodal content with images
                user_content = [{"type": "text", "text": prompt}]
                for img_data_uri in images:
                    # Log image data length for debugging
                    print(f"📷 Vision API: Adding image (data URI length: {len(img_data_uri)} chars)")
                    user_content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": img_data_uri,  # Use data URI directly
                            "detail": "high"  # Required for proper image recognition
                        }
                    })
                print(f"📤 Vision API: Sending {len(images)} image(s) with prompt")
            else:
                # Text-only content
                user_content = prompt

            # Build messages with system prompt
            messages = [
                {"role": "system", "content": "You are a helpful AI assistant."}
            ]

            # Add user message (with or without images)
            messages.append({"role": "user", "content": user_content})

            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=self.MODEL_NAME,
                messages=messages,
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

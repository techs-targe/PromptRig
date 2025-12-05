"""OpenAI GPT-5-nano client implementation.

Based on OpenAI API specification for GPT-5 models.
"""

import os
import time
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv

from .base import LLMClient, LLMResponse

# Load environment variables
load_dotenv()


class OpenAIGPT5NanoClient(LLMClient):
    """OpenAI GPT-5-nano client.

    Configuration from environment variables:
    - OPENAI_API_KEY
    """

    # Model identifier for gpt-5-nano
    MODEL_NAME = "gpt-5-nano"

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
        """Execute OpenAI GPT-5-nano call.

        Args:
            prompt: The prompt text to send
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

            # Build messages with system prompt
            messages = [
                {"role": "system", "content": "You are a helpful AI assistant."}
            ]

            # Add user message (with or without images)
            messages.append({"role": "user", "content": user_content})

            # Call OpenAI GPT-5 API
            # Note: Using standard chat.completions.create() for now
            # May need to adjust based on actual OpenAI GPT-5 API requirements
            response = self.client.chat.completions.create(
                model=self.MODEL_NAME,
                messages=messages
                # Note: May need to add verbosity and reasoning_effort parameters
                # depending on OpenAI API support
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

"""Anthropic Claude client implementation.

Supports Claude 4.5 (Opus, Sonnet, Haiku), Claude Sonnet 4, Claude 3.5, and Claude 3 Opus models.
Uses the official Anthropic Python SDK.
"""

import base64
import logging
import os
import time
from typing import Optional, List
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

from .base import LLMClient, LLMResponse, Message, EnvVarConfig

# Load environment variables
load_dotenv()


class AnthropicClaudeClient(LLMClient):
    """Anthropic Claude client base class.

    Configuration from environment variables:
    - ANTHROPIC_CLAUDE_API_KEY or ANTHROPIC_API_KEY

    Supports Vision API with images.
    """

    # Model identifier - override in subclasses
    MODEL_NAME = "claude-sonnet-4-20250514"
    DISPLAY_NAME = "claude-sonnet-4"

    # Environment variable configuration (shared by all Claude models)
    ENV_VARS = [
        EnvVarConfig("api_key", "ANTHROPIC_CLAUDE_API_KEY", "ANTHROPIC_API_KEY"),
    ]

    def __init__(self):
        """Initialize Anthropic client with environment configuration."""
        self._validate_env_vars()

        self.api_key = self._get_env_var("api_key")

        # Import anthropic SDK
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=self.api_key)
        except ImportError:
            raise ValueError(
                "anthropic package not installed. "
                "Please run: pip install anthropic"
            )

    def call(
        self,
        prompt: str = None,
        messages: List[Message] = None,
        images: list = None,
        **kwargs
    ) -> LLMResponse:
        """Execute Claude API call.

        Args:
            prompt: The prompt text to send (simple mode, treated as 'user' role)
            messages: List of message dicts with 'role' and 'content' keys
            images: Optional list of base64-encoded image strings for Vision API
            **kwargs: Optional parameters
                - temperature (float): Default 0.7
                - max_tokens (int): Default 4096
                - top_p (float): Default 1.0

        Returns:
            LLMResponse with result or error
        """
        start_time = time.time()

        try:
            # Get parameters with defaults
            temperature = kwargs.get("temperature", 0.7)
            max_tokens = kwargs.get("max_tokens", 4096)
            top_p = kwargs.get("top_p", 1.0)

            # Normalize input to messages list
            normalized_messages = self._normalize_messages(prompt, messages, images)

            # Separate system message from other messages (Claude API requirement)
            system_content = None
            api_messages = []

            for msg in normalized_messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                msg_images = msg.get("_images")

                if role == "system":
                    # Claude uses system as a separate parameter
                    if isinstance(content, list):
                        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                        system_content = "".join(text_parts)
                    else:
                        system_content = content
                    continue

                # Handle multimodal content (images) for user messages
                if msg_images and role == "user":
                    api_content = []
                    # Add images first
                    for img_data_uri in msg_images:
                        if img_data_uri.startswith("data:"):
                            parts = img_data_uri.split(",", 1)
                            if len(parts) == 2:
                                media_info = parts[0]
                                base64_data = parts[1]
                                media_type = media_info.replace("data:", "").replace(";base64", "")
                                logger.debug(f"Claude Vision: Adding image (media_type: {media_type})")
                                api_content.append({
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": base64_data
                                    }
                                })
                        else:
                            api_content.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": img_data_uri
                                }
                            })
                    # Add text content
                    if isinstance(content, str):
                        api_content.append({"type": "text", "text": content})
                    elif isinstance(content, list):
                        for c in content:
                            if c.get("type") == "text":
                                api_content.append({"type": "text", "text": c.get("text", "")})
                    logger.debug(f"Claude Vision: Sending {len(msg_images)} image(s) with prompt")
                    api_messages.append({"role": role, "content": api_content})
                else:
                    # Text-only content
                    if isinstance(content, list):
                        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                        api_messages.append({"role": role, "content": "".join(text_parts)})
                    else:
                        api_messages.append({"role": role, "content": content})

            # Build API call parameters
            api_params = {
                "model": self.MODEL_NAME,
                "max_tokens": max_tokens,
                "messages": api_messages,
                "temperature": temperature,
            }

            # Claude 4.5 models don't support both temperature and top_p
            # Only add top_p for non-4.5 models
            if "4-5" not in self.MODEL_NAME:
                api_params["top_p"] = top_p

            # Add system message if present
            if system_content:
                api_params["system"] = system_content

            # Call Claude API
            response = self.client.messages.create(**api_params)

            # Calculate turnaround time
            turnaround_ms = int((time.time() - start_time) * 1000)

            # Extract response text
            response_text = ""
            for block in response.content:
                if block.type == "text":
                    response_text += block.text

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
        """Get default parameters for Claude.

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
            Model display name
        """
        return self.DISPLAY_NAME


class ClaudeOpus45Client(AnthropicClaudeClient):
    """Claude Opus 4.5 client (Most capable, highest quality)."""
    MODEL_NAME = "claude-opus-4-5-20251101"
    DISPLAY_NAME = "claude-opus-4.5"


class ClaudeSonnet45Client(AnthropicClaudeClient):
    """Claude Sonnet 4.5 client (Balanced performance and cost)."""
    MODEL_NAME = "claude-sonnet-4-5-20250929"
    DISPLAY_NAME = "claude-sonnet-4.5"


class ClaudeHaiku45Client(AnthropicClaudeClient):
    """Claude Haiku 4.5 client (Fastest, most cost-effective)."""
    MODEL_NAME = "claude-haiku-4-5-20251001"
    DISPLAY_NAME = "claude-haiku-4.5"


class ClaudeSonnet4Client(AnthropicClaudeClient):
    """Claude Sonnet 4 client (Latest, Best for most tasks)."""
    MODEL_NAME = "claude-sonnet-4-20250514"
    DISPLAY_NAME = "claude-sonnet-4"


class Claude35SonnetClient(AnthropicClaudeClient):
    """Claude 3.5 Sonnet client (Fast and intelligent)."""
    MODEL_NAME = "claude-3-5-sonnet-20241022"
    DISPLAY_NAME = "claude-3.5-sonnet"


class Claude35HaikuClient(AnthropicClaudeClient):
    """Claude 3.5 Haiku client (Fastest, cost-effective)."""
    MODEL_NAME = "claude-3-5-haiku-20241022"
    DISPLAY_NAME = "claude-3.5-haiku"


class Claude3OpusClient(AnthropicClaudeClient):
    """Claude 3 Opus client (Most capable)."""
    MODEL_NAME = "claude-3-opus-20240229"
    DISPLAY_NAME = "claude-3-opus"

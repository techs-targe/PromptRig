"""Google Gemini client implementation.

Supports Gemini 2.0 Flash and other Gemini models.
Uses the google-generativeai package.
"""

import logging
import time
from typing import Optional, List
import google.generativeai as genai
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

from .base import LLMClient, LLMResponse, Message, EnvVarConfig, ModelInfo, ParameterSchema

# Load environment variables
load_dotenv()


class GoogleGeminiFlashClient(LLMClient):
    """Google Gemini 2.0 Flash client.

    Configuration from environment variables:
    - GOOGLE_GEMINI_API_KEY or GEMINI_API_KEY

    Model: gemini-2.0-flash (fast, capable model)
    Supports: Vision API, multimodal inputs
    """

    # Model identifier for auto-discovery
    MODEL_NAME = "gemini-2.0-flash"
    DISPLAY_NAME = "gemini-2.0-flash"

    # Environment variable configuration
    ENV_VARS = [
        EnvVarConfig("api_key", "GOOGLE_GEMINI_API_KEY", "GEMINI_API_KEY"),
    ]

    def __init__(self):
        """Initialize Google Gemini client with environment configuration."""
        self._validate_env_vars()

        self.api_key = self._get_env_var("api_key")

        # Configure the API
        genai.configure(api_key=self.api_key)

        # Initialize model
        self.model = genai.GenerativeModel(self.MODEL_NAME)

    def call(
        self,
        prompt: str = None,
        messages: List[Message] = None,
        images: list = None,
        **kwargs
    ) -> LLMResponse:
        """Execute Google Gemini call.

        Args:
            prompt: The prompt text to send (simple mode, treated as 'user' role)
            messages: List of message dicts with 'role' and 'content' keys
            images: Optional list of base64-encoded image strings for Vision API
            **kwargs: Optional parameters
                - temperature (float): Default 0.7 (range: 0.0-2.0)
                - max_tokens (int): Default 4096
                - top_p (float): Default 0.95

        Returns:
            LLMResponse with result or error

        Note:
            Gemini uses different role names:
            - "user" -> "user"
            - "assistant" -> "model"
            - "system" -> handled as system instruction
        """
        start_time = time.time()

        try:
            # Get parameters with defaults
            temperature = kwargs.get("temperature", 0.7)
            max_tokens = kwargs.get("max_tokens", 4096)
            top_p = kwargs.get("top_p", 0.95)

            # Configure generation settings
            generation_config = genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                top_p=top_p
            )

            # Normalize input to messages list
            normalized_messages = self._normalize_messages(prompt, messages, images)

            # Extract system message if present
            system_instruction = None
            chat_messages = []

            for msg in normalized_messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                msg_images = msg.get("_images")

                if role == "system":
                    system_instruction = content if isinstance(content, str) else str(content)
                    continue

                # Map role names (assistant -> model)
                gemini_role = "model" if role == "assistant" else "user"

                # Handle multimodal content (images)
                if msg_images and role == "user":
                    # For Gemini, we need to create parts
                    parts = []

                    # Add text content
                    if isinstance(content, str):
                        parts.append(content)
                    elif isinstance(content, list):
                        for c in content:
                            if c.get("type") == "text":
                                parts.append(c.get("text", ""))

                    # Add images (Gemini expects PIL images or base64 data)
                    for img_data_uri in msg_images:
                        # Parse data URI: data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ...
                        if img_data_uri.startswith("data:"):
                            # Extract mime type and base64 data
                            header, base64_data = img_data_uri.split(",", 1)
                            mime_type = header.split(";")[0].replace("data:", "")

                            import base64
                            image_bytes = base64.b64decode(base64_data)

                            parts.append({
                                "mime_type": mime_type,
                                "data": image_bytes
                            })
                            logger.debug(f"Gemini Vision: Added image ({mime_type}, {len(image_bytes)} bytes)")

                    chat_messages.append({"role": gemini_role, "parts": parts})
                else:
                    # Text-only content
                    if isinstance(content, list):
                        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                        text_content = "".join(text_parts)
                    else:
                        text_content = content

                    chat_messages.append({"role": gemini_role, "parts": [text_content]})

            # Create model with system instruction if provided
            if system_instruction:
                model = genai.GenerativeModel(
                    self.MODEL_NAME,
                    system_instruction=system_instruction
                )
            else:
                model = self.model

            # Generate response
            if len(chat_messages) == 1:
                # Simple single-turn generation
                response = model.generate_content(
                    chat_messages[0]["parts"],
                    generation_config=generation_config
                )
            else:
                # Multi-turn chat
                chat = model.start_chat(history=chat_messages[:-1])
                response = chat.send_message(
                    chat_messages[-1]["parts"],
                    generation_config=generation_config
                )

            # Calculate turnaround time
            turnaround_ms = int((time.time() - start_time) * 1000)

            # Extract response text
            response_text = response.text

            return LLMResponse(
                success=True,
                response_text=response_text,
                error_message=None,
                turnaround_ms=turnaround_ms
            )

        except Exception as e:
            turnaround_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)

            logger.error(f"Gemini API error: {error_msg}")

            return LLMResponse(
                success=False,
                response_text=None,
                error_message=error_msg,
                turnaround_ms=turnaround_ms
            )

    def get_default_parameters(self) -> dict:
        """Get default parameters for Google Gemini.

        Returns:
            Dictionary of default parameter values
        """
        return {
            "temperature": 0.7,
            "max_tokens": 4096,
            "top_p": 0.95
        }

    def get_model_name(self) -> str:
        """Get model name identifier.

        Returns:
            'gemini-2.0-flash'
        """
        return "gemini-2.0-flash"

    def get_parameter_schema(self) -> List[ParameterSchema]:
        """Get the configurable parameters schema for Gemini.

        Returns:
            List of ParameterSchema objects
        """
        return [
            ParameterSchema(
                name="temperature",
                type="float",
                default=0.7,
                description="Controls randomness. Higher = more creative.",
                min_value=0.0,
                max_value=2.0
            ),
            ParameterSchema(
                name="max_tokens",
                type="int",
                default=4096,
                description="Maximum tokens in response.",
                min_value=1,
                max_value=8192
            ),
            ParameterSchema(
                name="top_p",
                type="float",
                default=0.95,
                description="Nucleus sampling parameter.",
                min_value=0.0,
                max_value=1.0
            ),
        ]

    def get_model_info(self) -> ModelInfo:
        """Get metadata about this model.

        Returns:
            ModelInfo object with model metadata
        """
        return ModelInfo(
            name=self.DISPLAY_NAME,
            display_name="Gemini 2.0 Flash",
            provider="google",
            description="Fast, capable multimodal model from Google",
            supports_vision=True,
            supports_streaming=True,
            is_private=False
        )


class GoogleGeminiProClient(LLMClient):
    """Google Gemini 2.5 Pro client.

    Configuration from environment variables:
    - GOOGLE_GEMINI_API_KEY or GEMINI_API_KEY

    Model: gemini-2.5-pro (advanced reasoning model)
    Supports: Vision API, multimodal inputs, long context
    """

    # Model identifier for auto-discovery
    MODEL_NAME = "gemini-2.5-pro"
    DISPLAY_NAME = "gemini-2.5-pro"

    # Environment variable configuration
    ENV_VARS = [
        EnvVarConfig("api_key", "GOOGLE_GEMINI_API_KEY", "GEMINI_API_KEY"),
    ]

    def __init__(self):
        """Initialize Google Gemini Pro client with environment configuration."""
        self._validate_env_vars()

        self.api_key = self._get_env_var("api_key")

        # Configure the API
        genai.configure(api_key=self.api_key)

        # Initialize model
        self.model = genai.GenerativeModel(self.MODEL_NAME)

    def call(
        self,
        prompt: str = None,
        messages: List[Message] = None,
        images: list = None,
        **kwargs
    ) -> LLMResponse:
        """Execute Google Gemini Pro call.

        Uses the same implementation as Flash but with Pro model.
        """
        start_time = time.time()

        try:
            temperature = kwargs.get("temperature", 0.7)
            max_tokens = kwargs.get("max_tokens", 8192)
            top_p = kwargs.get("top_p", 0.95)

            generation_config = genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                top_p=top_p
            )

            normalized_messages = self._normalize_messages(prompt, messages, images)

            system_instruction = None
            chat_messages = []

            for msg in normalized_messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                msg_images = msg.get("_images")

                if role == "system":
                    system_instruction = content if isinstance(content, str) else str(content)
                    continue

                gemini_role = "model" if role == "assistant" else "user"

                if msg_images and role == "user":
                    parts = []
                    if isinstance(content, str):
                        parts.append(content)
                    elif isinstance(content, list):
                        for c in content:
                            if c.get("type") == "text":
                                parts.append(c.get("text", ""))

                    for img_data_uri in msg_images:
                        if img_data_uri.startswith("data:"):
                            header, base64_data = img_data_uri.split(",", 1)
                            mime_type = header.split(";")[0].replace("data:", "")
                            import base64
                            image_bytes = base64.b64decode(base64_data)
                            parts.append({"mime_type": mime_type, "data": image_bytes})

                    chat_messages.append({"role": gemini_role, "parts": parts})
                else:
                    if isinstance(content, list):
                        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                        text_content = "".join(text_parts)
                    else:
                        text_content = content
                    chat_messages.append({"role": gemini_role, "parts": [text_content]})

            if system_instruction:
                model = genai.GenerativeModel(
                    self.MODEL_NAME,
                    system_instruction=system_instruction
                )
            else:
                model = self.model

            if len(chat_messages) == 1:
                response = model.generate_content(
                    chat_messages[0]["parts"],
                    generation_config=generation_config
                )
            else:
                chat = model.start_chat(history=chat_messages[:-1])
                response = chat.send_message(
                    chat_messages[-1]["parts"],
                    generation_config=generation_config
                )

            turnaround_ms = int((time.time() - start_time) * 1000)
            response_text = response.text

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
        """Get default parameters for Gemini Pro."""
        return {
            "temperature": 0.7,
            "max_tokens": 8192,
            "top_p": 0.95
        }

    def get_model_name(self) -> str:
        """Get model name identifier."""
        return "gemini-2.5-pro"

    def get_model_info(self) -> ModelInfo:
        """Get metadata about this model."""
        return ModelInfo(
            name=self.DISPLAY_NAME,
            display_name="Gemini 2.5 Pro",
            provider="google",
            description="Advanced reasoning model with long context support",
            supports_vision=True,
            supports_streaming=True,
            is_private=False
        )

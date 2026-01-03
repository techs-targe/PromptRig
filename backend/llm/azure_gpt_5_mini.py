"""Azure OpenAI GPT-5-mini client implementation.

Based on Azure OpenAI API specification.
"""

import logging
import os
import time
from typing import Optional, List
from openai import AzureOpenAI, Timeout
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

from .base import LLMClient, LLMResponse, Message, EnvVarConfig

# Load environment variables
load_dotenv()


class AzureGPT5MiniClient(LLMClient):
    """Azure OpenAI GPT-5-mini client.

    Configuration from environment variables:
    - AZURE_GPT5_MINI_ENDPOINT or AZURE_OPENAI_ENDPOINT
    - AZURE_GPT5_MINI_API_KEY or AZURE_OPENAI_API_KEY
    - AZURE_GPT5_MINI_DEPLOYMENT_NAME or AZURE_OPENAI_DEPLOYMENT_NAME
    - AZURE_GPT5_MINI_API_VERSION or AZURE_OPENAI_API_VERSION
    """

    # Model identifier for auto-discovery
    DISPLAY_NAME = "azure-gpt-5-mini"

    # Environment variable configuration
    ENV_VARS = [
        EnvVarConfig("endpoint", "AZURE_GPT5_MINI_ENDPOINT", "AZURE_OPENAI_ENDPOINT"),
        EnvVarConfig("api_key", "AZURE_GPT5_MINI_API_KEY", "AZURE_OPENAI_API_KEY"),
        EnvVarConfig("deployment", "AZURE_GPT5_MINI_DEPLOYMENT_NAME", "AZURE_OPENAI_DEPLOYMENT_NAME"),
        EnvVarConfig("api_version", "AZURE_GPT5_MINI_API_VERSION", "AZURE_OPENAI_API_VERSION",
                     required=False, default="2025-01-01-preview"),
    ]

    def __init__(self):
        """Initialize Azure OpenAI GPT-5-mini client with environment configuration."""
        self._validate_env_vars()

        self.endpoint = self._get_env_var("endpoint")
        self.api_key = self._get_env_var("api_key")
        self.deployment_name = self._get_env_var("deployment")
        self.api_version = self._get_env_var("api_version")

        # Initialize client with detailed timeout configuration
        # Heavy processing can take up to 10 minutes, so set 15 minutes timeout
        # Use Timeout object for granular control over different timeout types
        timeout_config = Timeout(
            900.0,         # Default timeout (15 minutes)
            connect=60.0,  # 60 seconds to establish connection
            read=900.0,    # 15 minutes to read response (important for long processing)
            write=60.0,    # 60 seconds to write request
            pool=60.0      # 60 seconds for pool timeout
        )

        self.client = AzureOpenAI(
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
            api_version=self.api_version,
            timeout=timeout_config,
            max_retries=2
        )

    def call(
        self,
        prompt: str = None,
        messages: List[Message] = None,
        images: list = None,
        **kwargs
    ) -> LLMResponse:
        """Execute Azure OpenAI GPT-5-mini call with retry logic.

        Args:
            prompt: The prompt text to send (simple mode, treated as 'user' role)
            messages: List of message dicts with 'role' and 'content' keys
            images: Optional list of base64-encoded image strings for Vision API
            **kwargs: Optional parameters
                - max_output_tokens (int): Maximum completion tokens (default: 8192)

        Note:
            GPT-5 models use chat.completions.create() API.
            API version must be 2025-01-01-preview or later.
            Temperature, verbosity, and reasoning_effort are not used.
            Reference: Azure OpenAI GPT-5 documentation

            Retry Logic:
            - Retries up to 4 times on errors or empty responses
            - Retry delays: 15s → 30s → 60s → 60s (exponential backoff)
            - Retries on: rate limits, timeouts, empty responses

        Returns:
            LLMResponse with result or error

        Specification: docs/image_parameter_spec.md
        """
        max_retries = 4
        retry_delays = [15, 30, 60, 60]  # seconds for each retry attempt
        start_time = time.time()

        for attempt in range(max_retries):
            attempt_start = time.time()

            try:
                # Get parameters with defaults
                # Support both max_output_tokens (GPT-5 style) and max_tokens (legacy)
                max_tokens = kwargs.get("max_output_tokens", kwargs.get("max_tokens", 8192))

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
                                "image_url": {"url": img_data_uri}
                            })
                        api_messages.append({"role": role, "content": api_content})
                    else:
                        # Text-only content
                        if isinstance(content, list):
                            text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                            api_messages.append({"role": role, "content": "".join(text_parts)})
                        else:
                            api_messages.append({"role": role, "content": content})

                # Call Azure OpenAI GPT-5 API using chat.completions.create()
                # Reference: Azure OpenAI GPT-5 SDK documentation
                completion = self.client.chat.completions.create(
                    model=self.deployment_name,
                    messages=api_messages,
                    max_completion_tokens=max_tokens,
                    stop=None,
                    stream=False
                )

                # Calculate turnaround time for this attempt
                attempt_ms = int((time.time() - attempt_start) * 1000)

                # Extract response text with validation
                output_text = completion.choices[0].message.content

                # Check for empty response (None)
                if output_text is None:
                    if attempt < max_retries - 1:
                        delay = retry_delays[attempt]
                        logger.warning(f"GPT-5-mini: API returned None response (attempt {attempt + 1}/{max_retries}, turnaround: {attempt_ms}ms)")
                        logger.warning(f"   Completion ID: {completion.id if hasattr(completion, 'id') else 'N/A'}")
                        logger.warning(f"   Retrying in {delay} seconds...")
                        time.sleep(delay)
                        continue
                    else:
                        # Last attempt failed
                        total_ms = int((time.time() - start_time) * 1000)
                        logger.error(f"GPT-5-mini: API returned None response after {max_retries} attempts (total: {total_ms}ms)")
                        return LLMResponse(
                            success=False,
                            response_text=None,
                            error_message=f"API returned None response after {max_retries} retry attempts. Check Azure OpenAI quota and rate limits.",
                            turnaround_ms=total_ms
                        )

                # Check for empty response (whitespace only)
                if not output_text.strip():
                    if attempt < max_retries - 1:
                        delay = retry_delays[attempt]
                        finish_reason = completion.choices[0].finish_reason if completion.choices else 'N/A'
                        logger.warning(f"GPT-5-mini: API returned empty response (attempt {attempt + 1}/{max_retries}, turnaround: {attempt_ms}ms)")
                        logger.warning(f"   Completion ID: {completion.id if hasattr(completion, 'id') else 'N/A'}")
                        logger.warning(f"   Finish reason: {finish_reason}")
                        logger.warning(f"   Retrying in {delay} seconds...")
                        time.sleep(delay)
                        continue
                    else:
                        # Last attempt failed
                        total_ms = int((time.time() - start_time) * 1000)
                        finish_reason = completion.choices[0].finish_reason if completion.choices else 'unknown'
                        logger.error(f"GPT-5-mini: API returned empty response after {max_retries} attempts (total: {total_ms}ms)")
                        return LLMResponse(
                            success=False,
                            response_text=None,
                            error_message=f"API returned empty response after {max_retries} retry attempts. Finish reason: {finish_reason}. Check rate limits or reduce parallelism.",
                            turnaround_ms=total_ms
                        )

                # Success!
                total_ms = int((time.time() - start_time) * 1000)
                if attempt > 0:
                    logger.info(f"GPT-5-mini: Success on attempt {attempt + 1}/{max_retries} (total: {total_ms}ms)")

                return LLMResponse(
                    success=True,
                    response_text=output_text,
                    error_message=None,
                    turnaround_ms=total_ms
                )

            except Exception as e:
                attempt_ms = int((time.time() - attempt_start) * 1000)

                # Detailed error message for debugging
                error_type = type(e).__name__
                error_msg = str(e)

                # Check if error is retryable
                is_rate_limit = "rate" in error_msg.lower() or "quota" in error_msg.lower() or "429" in error_msg
                is_timeout = "timeout" in error_msg.lower()
                should_retry = is_rate_limit or is_timeout

                # Tag error type
                if is_rate_limit:
                    error_tag = "[RATE_LIMIT]"
                elif is_timeout:
                    error_tag = "[TIMEOUT]"
                else:
                    error_tag = "[ERROR]"

                if should_retry and attempt < max_retries - 1:
                    delay = retry_delays[attempt]
                    logger.warning(f"GPT-5-mini {error_tag}: {error_type} (attempt {attempt + 1}/{max_retries}, turnaround: {attempt_ms}ms)")
                    logger.warning(f"   Error: {error_msg}")
                    logger.warning(f"   Retrying in {delay} seconds...")
                    time.sleep(delay)
                    continue
                else:
                    # Last attempt or non-retryable error
                    total_ms = int((time.time() - start_time) * 1000)
                    if should_retry:
                        logger.error(f"GPT-5-mini {error_tag}: Failed after {max_retries} attempts (total: {total_ms}ms)")
                    else:
                        logger.error(f"GPT-5-mini {error_tag}: Non-retryable error [{error_type}]: {error_msg}")

                    return LLMResponse(
                        success=False,
                        response_text=None,
                        error_message=f"{error_type}: {error_tag} {error_msg}",
                        turnaround_ms=total_ms
                    )

        # Should never reach here, but just in case
        total_ms = int((time.time() - start_time) * 1000)
        return LLMResponse(
            success=False,
            response_text=None,
            error_message=f"Failed after {max_retries} retry attempts",
            turnaround_ms=total_ms
        )

    def get_default_parameters(self) -> dict:
        """Get default parameters for Azure GPT-5-mini.

        Returns:
            Dictionary of default parameter values

        Note:
            GPT-5 models have simplified parameters.
            max_output_tokens controls the maximum response length.
            Temperature is fixed at 1.0 by default.

            Reference: OpenAI GPT-5 documentation
            - max_output_tokens: 1-65536 (recommended: 4096-16384)
        """
        return {
            "max_output_tokens": 8192  # Increased default for longer responses
        }

    def get_model_name(self) -> str:
        """Get model name identifier.

        Returns:
            'azure-gpt-5-mini'
        """
        return "azure-gpt-5-mini"

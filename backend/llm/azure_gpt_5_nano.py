"""Azure OpenAI GPT-5-nano client implementation.

Based on Azure OpenAI API specification.
"""

import os
import time
from typing import Optional
from openai import AzureOpenAI, Timeout
from dotenv import load_dotenv

from .base import LLMClient, LLMResponse

# Load environment variables
load_dotenv()


class AzureGPT5NanoClient(LLMClient):
    """Azure OpenAI GPT-5-nano client.

    Configuration from environment variables:
    - AZURE_OPENAI_ENDPOINT
    - AZURE_OPENAI_API_KEY
    - AZURE_OPENAI_GPT5_NANO_DEPLOYMENT_NAME (defaults to AZURE_OPENAI_DEPLOYMENT_NAME)
    - AZURE_OPENAI_API_VERSION
    """

    def __init__(self):
        """Initialize Azure OpenAI GPT-5-nano client with environment configuration."""
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
        # Use GPT-5-nano specific deployment name, or fall back to default
        self.deployment_name = os.getenv(
            "AZURE_OPENAI_GPT5_NANO_DEPLOYMENT_NAME",
            os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        )
        # GPT-5 requires API version 2025-01-01-preview or later
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

        # Validate configuration
        if not all([self.endpoint, self.api_key, self.deployment_name]):
            raise ValueError(
                "Azure OpenAI configuration incomplete. "
                "Please set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, "
                "and AZURE_OPENAI_GPT5_NANO_DEPLOYMENT_NAME (or AZURE_OPENAI_DEPLOYMENT_NAME) in .env file."
            )

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

    def call(self, prompt: str, images: list = None, **kwargs) -> LLMResponse:
        """Execute Azure OpenAI GPT-5-nano call with retry logic.

        Args:
            prompt: The prompt text to send
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

                # Build user content (text + optional images for Vision API)
                if images:
                    # Multimodal content with images
                    user_content = [{"type": "text", "text": prompt}]
                    for idx, img_data_uri in enumerate(images, 1):
                        # Images now come as complete data URIs with correct MIME type
                        # Extract MIME type for logging
                        mime_type = img_data_uri.split(';')[0].replace('data:', '') if img_data_uri.startswith('data:') else 'unknown'
                        base64_len = len(img_data_uri.split(',')[1]) if ',' in img_data_uri else 0

                        print(f"🖼️  [GPT-5-nano] Image #{idx}: {mime_type}, Base64: {base64_len} chars")
                        print(f"   Data URI prefix (first 80 chars): {img_data_uri[:80]}")

                        user_content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": img_data_uri  # Use data URI directly
                            }
                        })
                    print(f"📤 [GPT-5-nano] Sending {len(images)} image(s) to Vision API")
                else:
                    # Text-only content
                    user_content = prompt

                # Prepare messages with system and user roles
                messages = [
                    {"role": "system", "content": "You are a helpful AI assistant."},
                    {"role": "user", "content": user_content}
                ]

                # Call Azure OpenAI GPT-5 API using chat.completions.create()
                # Reference: Azure OpenAI GPT-5 SDK documentation
                completion = self.client.chat.completions.create(
                    model=self.deployment_name,
                    messages=messages,
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
                        print(f"⚠️ GPT-5-nano: API returned None response (attempt {attempt + 1}/{max_retries}, turnaround: {attempt_ms}ms)")
                        print(f"   Completion ID: {completion.id if hasattr(completion, 'id') else 'N/A'}")
                        print(f"   Retrying in {delay} seconds...")
                        time.sleep(delay)
                        continue
                    else:
                        # Last attempt failed
                        total_ms = int((time.time() - start_time) * 1000)
                        print(f"❌ GPT-5-nano: API returned None response after {max_retries} attempts (total: {total_ms}ms)")
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
                        print(f"⚠️ GPT-5-nano: API returned empty response (attempt {attempt + 1}/{max_retries}, turnaround: {attempt_ms}ms)")
                        print(f"   Completion ID: {completion.id if hasattr(completion, 'id') else 'N/A'}")
                        print(f"   Finish reason: {finish_reason}")
                        print(f"   Retrying in {delay} seconds...")
                        time.sleep(delay)
                        continue
                    else:
                        # Last attempt failed
                        total_ms = int((time.time() - start_time) * 1000)
                        finish_reason = completion.choices[0].finish_reason if completion.choices else 'unknown'
                        print(f"❌ GPT-5-nano: API returned empty response after {max_retries} attempts (total: {total_ms}ms)")
                        return LLMResponse(
                            success=False,
                            response_text=None,
                            error_message=f"API returned empty response after {max_retries} retry attempts. Finish reason: {finish_reason}. Check rate limits or reduce parallelism.",
                            turnaround_ms=total_ms
                        )

                # Success!
                total_ms = int((time.time() - start_time) * 1000)
                if attempt > 0:
                    print(f"✅ GPT-5-nano: Success on attempt {attempt + 1}/{max_retries} (total: {total_ms}ms)")

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
                    print(f"⚠️ GPT-5-nano {error_tag}: {error_type} (attempt {attempt + 1}/{max_retries}, turnaround: {attempt_ms}ms)")
                    print(f"   Error: {error_msg}")
                    print(f"   Retrying in {delay} seconds...")
                    time.sleep(delay)
                    continue
                else:
                    # Last attempt or non-retryable error
                    total_ms = int((time.time() - start_time) * 1000)
                    if should_retry:
                        print(f"❌ GPT-5-nano {error_tag}: Failed after {max_retries} attempts (total: {total_ms}ms)")
                    else:
                        print(f"❌ GPT-5-nano {error_tag}: Non-retryable error [{error_type}]: {error_msg}")

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
        """Get default parameters for Azure GPT-5-nano.

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
            'azure-gpt-5-nano'
        """
        return "azure-gpt-5-nano"

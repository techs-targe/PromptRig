"""Job management logic for executing LLM prompts.

Based on specification in docs/req.txt section 4.2.3 (実行処理) and 3.2 (通信フロー).
"""

import json
import logging
import os
import re
import base64
from datetime import datetime
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
import io

from .database.models import Job, JobItem, ProjectRevision, PromptRevision, Dataset, SystemSetting, Prompt
from .prompt import PromptTemplateParser, get_message_parser
from .llm import get_llm_client, LLMClient
from .parser import ResponseParser
from sqlalchemy import text

# Import tag validation (lazy import to avoid circular dependencies)
def validate_prompt_tags(prompt_id: int, model_name: str, db: Session) -> tuple:
    """Validate prompt tags against model's allowed tags.

    Returns:
        tuple: (is_valid, error_message)
    """
    from app.routes.tags import validate_prompt_tags_for_model
    return validate_prompt_tags_for_model(prompt_id, model_name, db)


def extract_csv_template_field_order(csv_template: str) -> List[str]:
    """Extract field names from csv_template in their defined order.

    Args:
        csv_template: Template string like "$field1$,$field2$,$field3$"

    Returns:
        List of field names in template order, e.g., ["field1", "field2", "field3"]
    """
    if not csv_template:
        return []
    # Match $fieldname$ patterns and extract field names in order
    pattern = r'\$([^$]+)\$'
    return re.findall(pattern, csv_template)

logger = logging.getLogger(__name__)


class JobManager:
    """Manages job creation and execution.

    Specification: docs/req.txt section 3.2, 4.2.3
    """

    # Default text file extensions (must match settings.py)
    DEFAULT_TEXT_FILE_EXTENSIONS = "txt,csv,md,json,xml,yaml,yml,log,ini,cfg,conf,html,htm,css,js,ts,py,java,c,cpp,h,hpp,cs,go,rs,rb,php,sql,sh,bash,zsh,ps1,bat,cmd"

    def __init__(self, db: Session):
        """Initialize job manager.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.parser = PromptTemplateParser()

    def _get_text_file_extensions(self) -> List[str]:
        """Get list of text file extensions from system settings.

        Returns:
            List of extensions (lowercase, without dots) that should be treated as text.
            Empty list if setting is explicitly empty (disables auto-expansion).
        """
        setting = self.db.query(SystemSetting).filter(
            SystemSetting.key == "text_file_extensions"
        ).first()

        if setting is not None:
            extensions = setting.value
        else:
            extensions = self.DEFAULT_TEXT_FILE_EXTENSIONS

        # Parse into list (lowercase, trimmed)
        if extensions:
            return [ext.strip().lower() for ext in extensions.split(",") if ext.strip()]
        else:
            return []  # Empty list disables text expansion

    def create_single_job(
        self,
        project_revision_id: int = None,
        prompt_revision_id: int = None,
        input_params: Dict[str, str] = None,
        repeat: int = 1,
        model_name: str = None,
        template_override: str = None
    ) -> Job:
        """Create a single execution job.

        Args:
            project_revision_id: ID of project revision to use (OLD architecture, for backward compatibility)
            prompt_revision_id: ID of prompt revision to use (NEW architecture v3.0)
            input_params: Dictionary of parameter name -> value
            repeat: Number of times to repeat execution (default 1, max 10)
            model_name: LLM model name to use
            template_override: Override template (used for workflow step ref substitution)

        Returns:
            Created Job object (not yet executed)

        Specification: docs/req.txt section 4.2.3
        Phase 1: repeat は最大10程度に制限
        NEW ARCHITECTURE: If prompt_revision_id is provided, uses PromptRevision.
        """
        input_params = input_params or {}

        # Validate and normalize repeat count
        repeat = max(1, min(repeat, 10))

        # Create job
        job = Job(
            project_revision_id=project_revision_id,
            prompt_revision_id=prompt_revision_id,
            job_type="single",
            status="pending",
            model_name=model_name
        )
        self.db.add(job)
        self.db.flush()  # Get job.id

        # Get revision to access prompt template
        # NEW ARCHITECTURE: Use PromptRevision if prompt_revision_id is provided
        if prompt_revision_id:
            revision = self.db.query(PromptRevision).filter(
                PromptRevision.id == prompt_revision_id
            ).first()
            if not revision:
                raise ValueError(f"Prompt revision {prompt_revision_id} not found")
        elif project_revision_id:
            revision = self.db.query(ProjectRevision).filter(
                ProjectRevision.id == project_revision_id
            ).first()
            if not revision:
                raise ValueError(f"Project revision {project_revision_id} not found")
        else:
            raise ValueError("Either project_revision_id or prompt_revision_id must be provided")

        # Create job items (one per repeat)
        allowed_dirs = self._get_allowed_image_directories()  # Also used for TEXTFILEPATH
        text_extensions = self._get_text_file_extensions()  # For FILEPATH text expansion

        # Use template_override if provided (for workflow step ref substitution)
        prompt_template = template_override if template_override else revision.prompt_template

        for i in range(repeat):
            # Substitute parameters into template
            raw_prompt = self.parser.substitute_parameters(
                prompt_template,
                input_params,
                allowed_dirs,
                text_extensions
            )

            job_item = JobItem(
                job_id=job.id,
                input_params=json.dumps(input_params, ensure_ascii=False),
                raw_prompt=raw_prompt,
                status="pending"
            )
            self.db.add(job_item)

        self.db.commit()
        self.db.refresh(job)

        return job

    def execute_job(self, job_id: int, model_name: str = None, include_csv_header: bool = True, temperature: float = 0.7) -> Job:
        """Execute all pending items in a job.

        Args:
            job_id: ID of job to execute
            model_name: LLM model to use (defaults to ACTIVE_LLM_MODEL from env)
            include_csv_header: For batch jobs, include CSV header only in first row (default True)
            temperature: Temperature for LLM (0-2, default 0.7)

        Returns:
            Updated Job object with execution results

        Specification: docs/req.txt section 3.2 (通信フロー)
        Phase 1: 同期直列実行
        Phase 2: CSV merging for batch jobs, temperature control
        Phase 3: Parallel execution based on system settings
        """
        # Get job
        job = self.db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Record start time for accurate turnaround calculation
        start_time = datetime.utcnow()

        # Check if job was already cancelled before starting execution
        # IMPORTANT: Must use a NEW session to see changes from other sessions (cancel request)
        from backend.database import SessionLocal
        pre_check_db = SessionLocal()
        try:
            pre_status_result = pre_check_db.execute(
                text("SELECT status FROM jobs WHERE id = :job_id"),
                {"job_id": job.id}
            ).fetchone()
            pre_status = pre_status_result[0] if pre_status_result else None
        finally:
            pre_check_db.close()

        if pre_status == "cancelled":
            # Job was cancelled before execution started - preserve cancelled status
            logger.info(f"[JOB-SKIP] Job {job.id} already cancelled, skipping execution")
            job.status = "cancelled"  # Ensure status is set (in-memory object may have stale status)
            job.finished_at = start_time.isoformat()
            job.turnaround_ms = 0
            self.db.commit()
            self.db.refresh(job)
            return job

        # Tag validation: Check if prompt tags match model's allowed tags
        actual_model_name = model_name or os.getenv("ACTIVE_LLM_MODEL", "azure-gpt-4.1")
        prompt_id = None

        # Get prompt_id from job's prompt_revision
        if job.prompt_revision_id:
            prompt_revision = self.db.query(PromptRevision).filter(
                PromptRevision.id == job.prompt_revision_id
            ).first()
            if prompt_revision:
                prompt_id = prompt_revision.prompt_id
        elif job.project_revision_id:
            # Old architecture: Get default prompt for project
            project_revision = self.db.query(ProjectRevision).filter(
                ProjectRevision.id == job.project_revision_id
            ).first()
            if project_revision:
                default_prompt = self.db.query(Prompt).filter(
                    Prompt.project_id == project_revision.project_id,
                    Prompt.is_deleted == 0
                ).order_by(Prompt.created_at.asc()).first()
                if default_prompt:
                    prompt_id = default_prompt.id

        if prompt_id:
            is_valid, error_msg = validate_prompt_tags(prompt_id, actual_model_name, self.db)
            if not is_valid:
                logger.warning(f"[TAG-BLOCKED] Job {job.id}: {error_msg}")
                job.status = "error"
                job.finished_at = datetime.utcnow().isoformat()
                job.turnaround_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                self.db.commit()

                # Set error message on all pending items
                pending_items = self.db.query(JobItem).filter(
                    JobItem.job_id == job_id,
                    JobItem.status == "pending"
                ).all()
                for item in pending_items:
                    item.status = "error"
                    item.error_message = error_msg
                self.db.commit()
                self.db.refresh(job)
                return job

        # Update job status
        job.status = "running"
        job.started_at = start_time.isoformat()
        self.db.commit()

        # Get LLM client
        try:
            llm_client = get_llm_client(model_name)
        except Exception as e:
            job.status = "error"
            job.finished_at = datetime.utcnow().isoformat()
            self.db.commit()
            raise e

        # Get parallelism setting (default: 1)
        parallelism = self._get_parallelism_setting()

        # Get model parameters from system settings (for max_output_tokens, etc.)
        actual_model_name = model_name or llm_client.get_model_name()
        model_params = self._get_model_parameters(actual_model_name)

        # Execute all pending job items
        job_items = self.db.query(JobItem).filter(
            JobItem.job_id == job_id,
            JobItem.status == "pending"
        ).all()

        error_count = 0

        # Get revision for parser (fetch once, use for all items)
        # NEW ARCHITECTURE: Use PromptRevision if prompt_revision_id is set
        if job.prompt_revision_id:
            revision = self.db.query(PromptRevision).filter(
                PromptRevision.id == job.prompt_revision_id
            ).first()
        else:
            revision = self.db.query(ProjectRevision).filter(
                ProjectRevision.id == job.project_revision_id
            ).first()

        if parallelism == 1:
            # Serial execution (original behavior)
            error_count = self._execute_items_serial(job_items, llm_client, revision, temperature, model_params)
        else:
            # Parallel execution
            error_count = self._execute_items_parallel(job_items, llm_client, revision, temperature, parallelism, model_params)

        # Merge CSV outputs for batch jobs and single executions
        # Phase 2: batch and repeated single executions
        # Phase 3: Also for single item when include_csv_header is True (to show header)
        should_merge_csv = (
            job.job_type == "batch" or
            (job.job_type == "single" and len(job_items) > 1) or
            (job.job_type == "single" and include_csv_header)  # Include header even for 1 item
        )
        if should_merge_csv:
            # Expire session cache to ensure we get fresh data from database
            self.db.expire_all()
            # Re-fetch job items to get updated status and parsed_response after execution
            job_items_for_csv = self.db.query(JobItem).filter(JobItem.job_id == job_id).all()
            merged_csv = self._merge_csv_outputs(job_items_for_csv, include_csv_header)
            job.merged_csv_output = merged_csv

        # Calculate actual wall-clock time for job execution
        end_time = datetime.utcnow()
        actual_turnaround_ms = int((end_time - start_time).total_seconds() * 1000)

        # Check if job was cancelled during execution
        # (cancel_pending_items may have set status to "cancelled" in another session/thread)
        # IMPORTANT: Must use a NEW session to see changes from other sessions
        # SQLite transaction isolation prevents seeing uncommitted changes from other sessions
        from backend.database import SessionLocal
        check_db = SessionLocal()
        try:
            current_status_result = check_db.execute(
                text("SELECT status FROM jobs WHERE id = :job_id"),
                {"job_id": job.id}
            ).fetchone()
            current_status = current_status_result[0] if current_status_result else None
        finally:
            check_db.close()
        logger.info(f"[JOB-STATUS] Job {job.id} current DB status: {current_status}")

        # Update job completion info
        job.finished_at = end_time.isoformat()
        job.turnaround_ms = actual_turnaround_ms  # Real elapsed time, not sum of individual times

        # Preserve "cancelled" status if job was cancelled during execution
        if current_status != "cancelled":
            job.status = "error" if error_count > 0 else "done"
            logger.info(f"[JOB-STATUS] Job {job.id} setting status to: {job.status}")
        else:
            logger.info(f"[JOB-STATUS] Job {job.id} preserving cancelled status")

        self.db.commit()
        self.db.refresh(job)

        return job

    def _get_model_parameters(self, model_name: str) -> dict:
        """Get custom model parameters from system settings.

        Args:
            model_name: Name of the LLM model

        Returns:
            Dictionary of model parameters (empty if not customized)
            Filtered to only include parameters applicable to the model type.
        """
        import json as json_module
        setting_key = f"model_params_{model_name}"
        setting = self.db.query(SystemSetting).filter(
            SystemSetting.key == setting_key
        ).first()

        if setting and setting.value:
            try:
                params = json_module.loads(setting.value)
            except (json_module.JSONDecodeError, TypeError):
                return {}
        else:
            return {}

        # Filter parameters based on model type
        # This prevents conflicts like "temperature" being passed to GPT-5 models
        is_gpt5 = "gpt-5" in model_name or "gpt5" in model_name
        is_azure_gpt5 = is_gpt5 and "azure" in model_name
        is_openai_gpt5 = is_gpt5 and "openai" in model_name

        if is_azure_gpt5:
            # Azure GPT-5: Only allow max_output_tokens
            allowed_keys = {"max_output_tokens"}
        elif is_openai_gpt5:
            # OpenAI GPT-5: Allow verbosity and reasoning_effort
            allowed_keys = {"verbosity", "reasoning_effort", "max_output_tokens"}
        else:
            # GPT-4 and other models: Allow temperature, max_tokens, top_p
            allowed_keys = {"temperature", "max_tokens", "top_p"}

        # Filter to only allowed parameters
        filtered_params = {k: v for k, v in params.items() if k in allowed_keys}
        return filtered_params

    def _get_parallelism_setting(self) -> int:
        """Get job parallelism setting from system settings.

        Returns:
            Parallelism value (1-99), defaults to 1
        """
        setting = self.db.query(SystemSetting).filter(
            SystemSetting.key == "job_parallelism"
        ).first()

        if setting and setting.value:
            try:
                parallelism = int(setting.value)
                return max(1, min(parallelism, 99))  # Clamp to 1-99
            except ValueError:
                return 1
        return 1

    def _process_image_parameters(
        self,
        input_params: Dict[str, str],
        prompt_template: str
    ) -> List[str]:
        """Process FILE and FILEPATH parameters into Base64 image data.

        Args:
            input_params: Dictionary of parameter name -> value
            prompt_template: Prompt template string with {{}} syntax

        Returns:
            List of data URI strings (with MIME type and Base64 data)
            Format: "data:image/png;base64,iVBORw0KGgo..."
            Empty list if no image parameters found

        Specification: docs/image_parameter_spec.md

        Security considerations:
        - FILEPATH type validates paths against allowed directories
        - Images are automatically resized if > 2048px
        - Only JPEG, PNG, GIF, WebP formats supported
        """
        print(f"🔍 Processing image parameters from input_params: {list(input_params.keys())}")

        # Parse template to identify FILE and FILEPATH parameters
        param_defs = self.parser.parse_template(prompt_template)

        images = []
        allowed_dirs = self._get_allowed_image_directories()
        print(f"📁 Allowed image directories: {allowed_dirs}")

        for param_def in param_defs:
            param_name = param_def.name
            param_type = param_def.type

            # Skip non-image parameters
            if param_type not in ["FILE", "FILEPATH"]:
                continue

            print(f"🖼️  Found image parameter: {param_name} (type={param_type})")

            # Get parameter value
            param_value = input_params.get(param_name)
            if not param_value:
                print(f"⚠️  Parameter '{param_name}' has no value, skipping")
                continue

            try:
                if param_type == "FILE":
                    # FILE type: Keep original data URI with MIME type
                    # Expected format: "data:image/jpeg;base64,/9j/4AAQ..."
                    print(f"📤 Processing FILE parameter '{param_name}' (data length: {len(param_value)} chars)")

                    # Extract MIME type from data URI
                    mime_type = self._extract_mime_type_from_data_uri(param_value)
                    base64_data = self._extract_base64_from_file_param(param_value)

                    # Reconstruct data URI with correct MIME type
                    data_uri = f"data:{mime_type};base64,{base64_data}"
                    print(f"✅ FILE '{param_name}' → {mime_type}, Base64: {len(base64_data)} chars")
                    images.append(data_uri)

                elif param_type == "FILEPATH":
                    # FILEPATH type: Load file and create data URI with correct MIME type
                    print(f"📂 Processing FILEPATH parameter '{param_name}': {param_value}")
                    data_uri = self._load_image_from_filepath(param_value, allowed_dirs)
                    print(f"✅ FILEPATH '{param_name}' → {len(data_uri)} chars")
                    images.append(data_uri)

            except Exception as e:
                logger.error(f"Error processing image parameter '{param_name}': {e}")
                print(f"❌ Error processing '{param_name}': {e}")
                # Continue processing other images, but log the error
                # The LLM call may fail if image is critical, but that's expected

        print(f"📊 Total images processed: {len(images)}")
        return images

    def _get_allowed_image_directories(self) -> List[str]:
        """Get list of allowed directories for FILEPATH type.

        Returns:
            List of absolute paths to allowed directories
        """
        # Get from environment variable or use defaults
        env_dirs = os.getenv("ALLOWED_IMAGE_DIRS", "")
        if env_dirs:
            dirs = [d.strip() for d in env_dirs.split(",") if d.strip()]
        else:
            # Default allowed directories
            dirs = [
                "/var/data/images",
                "./uploads",
                os.path.expanduser("~/images")
            ]

        # Resolve to absolute paths
        return [os.path.abspath(os.path.expanduser(d)) for d in dirs]

    def _extract_mime_type_from_data_uri(self, data_uri: str) -> str:
        """Extract MIME type from data URI.

        Args:
            data_uri: Data URI string like "data:image/png;base64,..."

        Returns:
            MIME type string (e.g., "image/png")

        Raises:
            ValueError: If format is invalid
        """
        if not data_uri.startswith("data:"):
            raise ValueError("Invalid data URI: missing 'data:' prefix")

        # Extract MIME type from "data:image/png;base64,..."
        if ";base64," in data_uri:
            mime_part = data_uri.split(";base64,")[0]
            mime_type = mime_part.replace("data:", "")
            return mime_type
        else:
            raise ValueError("Invalid data URI format: missing ';base64,' separator")

    def _extract_base64_from_file_param(self, param_value: str) -> str:
        """Extract Base64 data from FILE parameter value.

        Args:
            param_value: Data URI string like "data:image/jpeg;base64,/9j/..."

        Returns:
            Base64-encoded image string (without data URI prefix)

        Raises:
            ValueError: If format is invalid
        """
        # Check if already just Base64 (no data URI prefix)
        if not param_value.startswith("data:"):
            return param_value

        # Extract Base64 from data URI
        if ";base64," in param_value:
            _, base64_data = param_value.split(";base64,", 1)
            return base64_data
        else:
            raise ValueError("Invalid FILE parameter format: missing ';base64,' separator")

    def _load_image_from_filepath(self, file_path: str, allowed_dirs: List[str]) -> str:
        """Load image from file path and convert to data URI.

        Args:
            file_path: Path to image file on server
            allowed_dirs: List of allowed directory paths

        Returns:
            Data URI string (e.g., "data:image/png;base64,iVBORw0...")

        Raises:
            ValueError: If path is invalid or not allowed
            FileNotFoundError: If file doesn't exist
            IOError: If file cannot be read

        Specification: docs/image_parameter_spec.md (Security considerations)
        """
        # Validate and sanitize file path
        real_path = os.path.realpath(os.path.expanduser(file_path))

        # Check if path is in allowed directories
        allowed = any(
            real_path.startswith(allowed_dir)
            for allowed_dir in allowed_dirs
        )

        if not allowed:
            raise ValueError(
                f"Access denied: '{file_path}' is not in allowed directories. "
                f"Allowed: {', '.join(allowed_dirs)}"
            )

        # Check if file exists
        if not os.path.exists(real_path):
            raise FileNotFoundError(f"Image file not found: {file_path}")

        # Check if it's a file (not directory)
        if not os.path.isfile(real_path):
            raise ValueError(f"Path is not a file: {file_path}")

        # Read file directly without PIL re-encoding (preserves all metadata)
        # This ensures LLM compatibility - PIL re-encoding can cause recognition failures
        try:
            # First, validate format with PIL
            with Image.open(real_path) as img:
                if img.format not in ["JPEG", "PNG", "GIF", "WEBP"]:
                    raise ValueError(
                        f"Unsupported image format: {img.format}. "
                        "Supported: JPEG, PNG, GIF, WEBP"
                    )

                detected_format = img.format

                # Check if resizing is needed
                needs_resize = max(img.size) > 2048

            # If resizing is needed, use PIL
            if needs_resize:
                with Image.open(real_path) as img:
                    img = self._resize_image_if_needed(img)
                    buffer = io.BytesIO()
                    save_format = img.format if img.format in ["JPEG", "PNG", "GIF", "WEBP"] else "JPEG"
                    img.save(buffer, format=save_format)
                    image_bytes = buffer.getvalue()
                    detected_format = save_format
            else:
                # Read file directly for best LLM compatibility
                with open(real_path, 'rb') as f:
                    image_bytes = f.read()

            # Encode to Base64
            base64_data = base64.b64encode(image_bytes).decode("utf-8")

            # Create MIME type from format
            mime_type_map = {
                "JPEG": "image/jpeg",
                "PNG": "image/png",
                "GIF": "image/gif",
                "WEBP": "image/webp"
            }
            mime_type = mime_type_map.get(detected_format, "image/jpeg")

            # Return data URI
            data_uri = f"data:{mime_type};base64,{base64_data}"
            return data_uri

        except Exception as e:
            raise IOError(f"Failed to load image from '{file_path}': {e}")

    def _resize_image_if_needed(self, img: Image.Image) -> Image.Image:
        """Resize image if dimensions exceed maximum.

        Args:
            img: PIL Image object

        Returns:
            Resized image (or original if within limits)

        Specification: docs/image_parameter_spec.md (Performance optimization)
        """
        max_dim = 2048

        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            logger.info(f"Resizing image from {img.size} to {new_size}")
            return img.resize(new_size, Image.Resampling.LANCZOS)

        return img

    def _execute_items_serial(
        self,
        job_items: List[JobItem],
        llm_client: LLMClient,
        revision: ProjectRevision,
        temperature: float,
        model_params: dict = None
    ) -> int:
        """Execute job items serially (one at a time).

        Args:
            job_items: List of job items to execute
            llm_client: LLM client instance
            revision: Project revision for parser
            temperature: LLM temperature
            model_params: Additional model parameters (e.g., max_output_tokens)

        Returns:
            Number of errors encountered
        """
        error_count = 0
        model_params = model_params or {}

        for item in job_items:
            # Check if item was cancelled
            self.db.refresh(item)
            if item.status == "cancelled":
                continue

            # Update item status
            item.status = "running"
            self.db.commit()

            # Execute LLM call
            try:
                # Process image parameters (FILE and FILEPATH types)
                images = []
                if revision and revision.prompt_template:
                    try:
                        input_params = json.loads(item.input_params)
                        images = self._process_image_parameters(
                            input_params,
                            revision.prompt_template
                        )
                    except Exception as e:
                        logger.error(f"Error processing images for item {item.id}: {e}")
                        # Continue without images if processing fails

                # Call LLM with prompt, optional images, and model parameters
                # Parse prompt for [SYSTEM]/[USER]/[ASSISTANT] role markers
                message_parser = get_message_parser()
                if message_parser.has_role_markers(item.raw_prompt):
                    # Use messages mode for structured prompts
                    messages = message_parser.to_messages_list(item.raw_prompt)
                    prompt_arg = None
                else:
                    # Use simple prompt mode (backward compatible)
                    messages = None
                    prompt_arg = item.raw_prompt

                # GPT-5 models don't use temperature parameter
                model_name = llm_client.get_model_name()
                is_gpt5 = "gpt-5" in model_name or "gpt5" in model_name

                if is_gpt5:
                    # GPT-5: Don't pass temperature
                    response = llm_client.call(
                        prompt=prompt_arg,
                        messages=messages,
                        images=images if images else None,
                        **model_params
                    )
                else:
                    # GPT-4 and other models: Pass temperature
                    response = llm_client.call(
                        prompt=prompt_arg,
                        messages=messages,
                        images=images if images else None,
                        temperature=temperature,
                        **model_params
                    )

                if response.success:
                    item.status = "done"
                    item.raw_response = response.response_text
                    item.turnaround_ms = response.turnaround_ms

                    # Apply parser (Phase 2)
                    if revision and revision.parser_config:
                        parser = ResponseParser(revision.parser_config)
                        parsed_result = parser.parse(response.response_text)
                        item.parsed_response = json.dumps(parsed_result, ensure_ascii=False)
                    else:
                        item.parsed_response = json.dumps({"raw": response.response_text, "parsed": False})
                else:
                    item.status = "error"
                    item.error_message = response.error_message
                    item.turnaround_ms = response.turnaround_ms
                    error_count += 1

            except Exception as e:
                item.status = "error"
                item.error_message = str(e)
                error_count += 1

            self.db.commit()

        return error_count

    def _execute_items_parallel(
        self,
        job_items: List[JobItem],
        llm_client: LLMClient,
        revision: ProjectRevision,
        temperature: float,
        max_workers: int,
        model_params: dict = None
    ) -> int:
        """Execute job items in parallel using ThreadPoolExecutor.

        Args:
            job_items: List of job items to execute
            llm_client: LLM client instance
            revision: Project revision for parser
            temperature: LLM temperature
            max_workers: Maximum number of parallel workers
            model_params: Additional model parameters (e.g., max_output_tokens)

        Returns:
            Number of errors encountered
        """
        from backend.database import SessionLocal

        error_count = 0
        model_params = model_params or {}

        def execute_single_item(
            item_id: int,
            raw_prompt: str,
            input_params_json: str,
            prompt_template: str,
            parser_config: str
        ) -> int:
            """Execute a single job item with its own database session.

            Args:
                item_id: JobItem ID to process
                raw_prompt: The prompt text to send to LLM
                input_params_json: JSON string of input parameters
                prompt_template: Prompt template for image processing
                parser_config: Parser configuration JSON

            Returns:
                1 if error, 0 if success
            """
            # Create new session for this thread
            db = SessionLocal()
            try:
                # Get fresh item from database
                item = db.query(JobItem).filter(JobItem.id == item_id).first()
                if not item:
                    return 1

                # Check if item was cancelled
                if item.status == "cancelled":
                    return 0

                # Update item status
                item.status = "running"
                db.commit()

                # Execute LLM call
                try:
                    # Process image parameters (FILE and FILEPATH types)
                    images = []
                    if prompt_template:
                        try:
                            input_params = json.loads(input_params_json)
                            # Create temporary parser for this thread
                            temp_parser = PromptTemplateParser()
                            param_defs = temp_parser.parse_template(prompt_template)

                            # Process images using helper methods
                            # Note: We need to reimplement image processing here
                            # since we can't access self methods in parallel threads
                            allowed_dirs = self._get_allowed_image_directories()

                            for param_def in param_defs:
                                param_name = param_def.name
                                param_type = param_def.type

                                if param_type not in ["FILE", "FILEPATH"]:
                                    continue

                                param_value = input_params.get(param_name)
                                if not param_value:
                                    continue

                                try:
                                    if param_type == "FILE":
                                        # FILE type: Reconstruct data URI with MIME type
                                        mime_type = self._extract_mime_type_from_data_uri(param_value)
                                        base64_data = self._extract_base64_from_file_param(param_value)
                                        data_uri = f"data:{mime_type};base64,{base64_data}"
                                        images.append(data_uri)
                                    elif param_type == "FILEPATH":
                                        # FILEPATH type: _load_image_from_filepath now returns data URI
                                        data_uri = self._load_image_from_filepath(param_value, allowed_dirs)
                                        images.append(data_uri)
                                except Exception as e:
                                    logger.error(f"Error processing image parameter '{param_name}' in item {item_id}: {e}")

                        except Exception as e:
                            logger.error(f"Error processing images for item {item_id}: {e}")

                    # Call LLM with prompt, optional images, and model parameters
                    # Parse prompt for [SYSTEM]/[USER]/[ASSISTANT] role markers
                    message_parser = get_message_parser()
                    if message_parser.has_role_markers(raw_prompt):
                        # Use messages mode for structured prompts
                        messages = message_parser.to_messages_list(raw_prompt)
                        prompt_arg = None
                    else:
                        # Use simple prompt mode (backward compatible)
                        messages = None
                        prompt_arg = raw_prompt

                    # GPT-5 models don't use temperature parameter
                    model_name = llm_client.get_model_name()
                    is_gpt5 = "gpt-5" in model_name or "gpt5" in model_name

                    if is_gpt5:
                        # GPT-5: Don't pass temperature
                        response = llm_client.call(
                            prompt=prompt_arg,
                            messages=messages,
                            images=images if images else None,
                            **model_params
                        )
                    else:
                        # GPT-4 and other models: Pass temperature
                        response = llm_client.call(
                            prompt=prompt_arg,
                            messages=messages,
                            images=images if images else None,
                            temperature=temperature,
                            **model_params
                        )

                    if response.success:
                        item.status = "done"
                        item.raw_response = response.response_text
                        item.turnaround_ms = response.turnaround_ms

                        # Apply parser
                        if parser_config:
                            parser = ResponseParser(parser_config)
                            parsed_result = parser.parse(response.response_text)
                            item.parsed_response = json.dumps(parsed_result, ensure_ascii=False)
                        else:
                            item.parsed_response = json.dumps({"raw": response.response_text, "parsed": False})

                        db.commit()
                        return 0
                    else:
                        item.status = "error"
                        item.error_message = response.error_message
                        item.turnaround_ms = response.turnaround_ms
                        db.commit()
                        return 1

                except Exception as e:
                    item.status = "error"
                    item.error_message = str(e)
                    db.commit()
                    return 1

            finally:
                # Always close session
                db.close()

        # Prepare data for parallel execution
        parser_config = revision.parser_config if revision else None
        prompt_template = revision.prompt_template if revision else None

        # Execute items in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all items with their data (not the ORM objects)
            future_to_item = {
                executor.submit(
                    execute_single_item,
                    item.id,
                    item.raw_prompt,
                    item.input_params,
                    prompt_template,
                    parser_config
                ): item
                for item in job_items
            }

            # Wait for completion and collect errors
            for future in as_completed(future_to_item):
                error_count += future.result()

        return error_count

    def _merge_csv_outputs(self, job_items: List[JobItem], include_csv_header: bool) -> str:
        """Merge CSV outputs from multiple job items.

        Args:
            job_items: List of job items with parsed responses
            include_csv_header: If True, include header from first item

        Returns:
            Merged CSV string with newline-separated rows

        Specification: Phase 2 batch CSV merge feature
        Phase 3: Enhanced for parallel execution - maintains order by item ID
        """
        csv_lines = []
        header_added = False
        csv_template_field_order = None

        # Sort job_items by ID to ensure consistent order, especially for parallel execution
        # This guarantees that CSV rows appear in the same order as they were created
        sorted_items = sorted(job_items, key=lambda x: x.id)

        logger.info(f"CSV merge: Processing {len(sorted_items)} items, include_header={include_csv_header}")

        # Try to get csv_template field order from the job's revision
        if sorted_items:
            first_item = sorted_items[0]
            job = self.db.query(Job).filter(Job.id == first_item.job_id).first()
            if job:
                parser_config_str = None
                # Try prompt revision first (new architecture)
                if job.prompt_revision_id:
                    prompt_rev = self.db.query(PromptRevision).filter(
                        PromptRevision.id == job.prompt_revision_id
                    ).first()
                    if prompt_rev:
                        parser_config_str = prompt_rev.parser_config
                # Fall back to project revision (old architecture)
                elif job.project_revision_id:
                    project_rev = self.db.query(ProjectRevision).filter(
                        ProjectRevision.id == job.project_revision_id
                    ).first()
                    if project_rev:
                        parser_config_str = project_rev.parser_config

                if parser_config_str:
                    try:
                        parser_config = json.loads(parser_config_str)
                        # Handle double-encoded JSON
                        if isinstance(parser_config, str):
                            parser_config = json.loads(parser_config)
                        csv_template = parser_config.get("csv_template", "")
                        if csv_template:
                            csv_template_field_order = extract_csv_template_field_order(csv_template)
                            logger.info(f"CSV merge: Extracted field order from csv_template: {csv_template_field_order}")
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(f"CSV merge: Could not parse parser_config: {e}")

        for item in sorted_items:
            # Skip items that are not successfully completed
            if item.status != "done" or not item.parsed_response:
                logger.debug(f"CSV merge: Skipping item {item.id} - status={item.status}, has_parsed={bool(item.parsed_response)}")
                continue

            try:
                parsed = json.loads(item.parsed_response)

                # Handle double-encoded JSON (string instead of dict)
                if isinstance(parsed, str):
                    try:
                        parsed = json.loads(parsed)
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(f"CSV merge: Item {item.id} has double-encoded JSON that couldn't be parsed")
                        continue

                # Ensure parsed is a dictionary
                if not isinstance(parsed, dict):
                    logger.warning(f"CSV merge: Item {item.id} parsed_response is not a dict: {type(parsed)}")
                    continue

                csv_output = parsed.get("csv_output", "")

                logger.debug(f"CSV merge: Item {item.id} - has_csv_output={bool(csv_output)}, parsed_keys={list(parsed.keys())}")

                if not csv_output:
                    logger.warning(f"CSV merge: Item {item.id} has no csv_output field in parsed response")
                    continue

                # Add header from first successful item (only once)
                if not header_added and include_csv_header:
                    fields = parsed.get("fields", {})
                    if fields:
                        # Use csv_template field order if available, otherwise fall back to fields.keys()
                        if csv_template_field_order:
                            # Filter to only include fields that actually exist
                            ordered_fields = [f for f in csv_template_field_order if f in fields]
                            header_line = ",".join(ordered_fields)
                        else:
                            # Fallback: use fields.keys() order (may not match csv_template)
                            header_line = ",".join(fields.keys())
                        csv_lines.append(header_line)
                        header_added = True
                        logger.info(f"CSV merge: Added header: {header_line}")

                # Add data line
                csv_lines.append(csv_output)
                logger.debug(f"CSV merge: Added line from item {item.id}: {csv_output[:100]}")

            except (json.JSONDecodeError, KeyError, AttributeError, TypeError) as e:
                # Skip items with invalid parsed response
                logger.error(f"CSV merge: Error parsing item {item.id}: {e}")
                continue

        result = "\n".join(csv_lines)
        logger.info(f"CSV merge: Completed with {len(csv_lines)} lines (including header if present)")
        return result

    def get_job_with_items(self, job_id: int) -> Optional[Job]:
        """Get job with all its items loaded.

        Args:
            job_id: ID of job to retrieve

        Returns:
            Job object with job_items relationship loaded, or None if not found
        """
        job = self.db.query(Job).filter(Job.id == job_id).first()
        if job:
            # Force load job_items relationship
            _ = job.job_items
        return job

    def get_recent_jobs(
        self,
        project_revision_id: int,
        limit: int = 20
    ) -> List[Job]:
        """Get recent jobs for a project revision.

        Args:
            project_revision_id: ID of project revision
            limit: Maximum number of jobs to return

        Returns:
            List of Job objects, ordered by creation time (newest first)

        Specification: docs/req.txt section 4.2.3 (実行履歴)
        """
        jobs = self.db.query(Job).filter(
            Job.project_revision_id == project_revision_id
        ).order_by(
            Job.created_at.desc()
        ).limit(limit).all()

        return jobs

    def create_batch_job(
        self,
        project_revision_id: int = None,
        prompt_revision_id: int = None,
        dataset_id: int = None,
        model_name: str = None
    ) -> Job:
        """Create a batch execution job from dataset.

        Args:
            project_revision_id: ID of project revision to use (old architecture)
            prompt_revision_id: ID of prompt revision to use (new architecture)
            dataset_id: ID of dataset to process
            model_name: Name of LLM model to use (optional)

        Returns:
            Created Job object (not yet executed)

        Specification: docs/req.txt section 4.3.2 (バッチ実行フロー)
        Phase 2, NEW ARCHITECTURE v3.0
        """
        # Get dataset
        dataset = self.db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            raise ValueError(f"Dataset {dataset_id} not found")

        # Get revision (new architecture first, then fallback)
        prompt_template = None
        if prompt_revision_id:
            # NEW ARCHITECTURE: Use PromptRevision
            revision = self.db.query(PromptRevision).filter(
                PromptRevision.id == prompt_revision_id
            ).first()
            if not revision:
                raise ValueError(f"Prompt revision {prompt_revision_id} not found")
            prompt_template = revision.prompt_template
        elif project_revision_id:
            # Fallback: Use ProjectRevision (backward compatibility)
            revision = self.db.query(ProjectRevision).filter(
                ProjectRevision.id == project_revision_id
            ).first()
            if not revision:
                raise ValueError(f"Project revision {project_revision_id} not found")
            prompt_template = revision.prompt_template
        else:
            raise ValueError("Either project_revision_id or prompt_revision_id must be provided")

        # Create job
        job = Job(
            project_revision_id=project_revision_id,
            prompt_revision_id=prompt_revision_id,
            job_type="batch",
            status="pending",
            dataset_id=dataset_id,
            model_name=model_name
        )
        self.db.add(job)
        self.db.flush()

        # Get data from dataset table
        table_name = dataset.sqlite_table_name
        select_sql = f'SELECT * FROM "{table_name}"'
        result = self.db.execute(text(select_sql))

        # Fetch all rows first
        rows = result.fetchall()
        if not rows:
            self.db.commit()
            self.db.refresh(job)
            return job  # No data to process

        # Get column names from first row's mapping (excluding id)
        columns = [col for col in rows[0]._mapping.keys() if col != "id"]

        # Get allowed directories and text extensions
        allowed_dirs = self._get_allowed_image_directories()
        text_extensions = self._get_text_file_extensions()

        # Create job items for each row
        for row in rows:
            # Build input_params from row data using _mapping
            input_params = {}
            for col in columns:
                value = row._mapping.get(col)
                input_params[col] = str(value) if value is not None else ""

            # Substitute parameters into template
            raw_prompt = self.parser.substitute_parameters(
                prompt_template,
                input_params,
                allowed_dirs,
                text_extensions
            )

            job_item = JobItem(
                job_id=job.id,
                input_params=json.dumps(input_params, ensure_ascii=False),
                raw_prompt=raw_prompt,
                status="pending"
            )
            self.db.add(job_item)

        self.db.commit()
        self.db.refresh(job)

        return job

    def get_job_progress(self, job_id: int) -> Dict[str, any]:
        """Get execution progress for a job.

        Args:
            job_id: ID of job to check

        Returns:
            Dictionary with progress information

        Specification: docs/req.txt section 3.3 (バッチ実行通信フロー step 6)
        Phase 2
        """
        job = self.db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Count items by status
        all_items = self.db.query(JobItem).filter(JobItem.job_id == job_id).all()
        total = len(all_items)
        completed = sum(1 for item in all_items if item.status == "done")
        errors = sum(1 for item in all_items if item.status == "error")
        pending = sum(1 for item in all_items if item.status == "pending")
        running = sum(1 for item in all_items if item.status == "running")
        cancelled = sum(1 for item in all_items if item.status == "cancelled")

        return {
            "job_id": job.id,
            "job_type": job.job_type,
            "status": job.status,
            "total_items": total,
            "completed": completed,
            "errors": errors,
            "pending": pending,
            "running": running,
            "cancelled": cancelled,
            "progress_percent": int((completed + errors + cancelled) / total * 100) if total > 0 else 0,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "turnaround_ms": job.turnaround_ms
        }

    def cancel_pending_items(self, job_id: int) -> Dict[str, any]:
        """Cancel all pending job items in a job.

        Args:
            job_id: ID of job to cancel

        Returns:
            Dictionary with cancellation results

        Note:
            This only cancels pending items. Running items cannot be stopped
            as they are already executing LLM API calls.
        """
        job = self.db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Get all pending items
        pending_items = self.db.query(JobItem).filter(
            JobItem.job_id == job_id,
            JobItem.status == "pending"
        ).all()

        # Mark as cancelled
        cancelled_count = 0
        for item in pending_items:
            item.status = "cancelled"
            item.error_message = "Cancelled by user"
            cancelled_count += 1

        self.db.commit()

        # Update job status
        remaining_pending = self.db.query(JobItem).filter(
            JobItem.job_id == job_id,
            JobItem.status == "pending"
        ).count()

        remaining_running = self.db.query(JobItem).filter(
            JobItem.job_id == job_id,
            JobItem.status == "running"
        ).count()

        # Always mark job as cancelled when cancel is requested
        # Running items will complete, but job status remains cancelled
        job.status = "cancelled"
        logger.info(f"[JOB-CANCEL] Job {job_id} status set to 'cancelled' (running={remaining_running}, pending={remaining_pending})")

        # Only set finished_at if no items are still running
        if remaining_pending == 0 and remaining_running == 0:
            job.finished_at = datetime.utcnow().isoformat()

        self.db.commit()

        return {
            "job_id": job_id,
            "cancelled_count": cancelled_count,
            "job_status": job.status,
            "message": f"Cancelled {cancelled_count} pending item(s)"
        }

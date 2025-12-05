"""Job management logic for executing LLM prompts.

Based on specification in docs/req.txt section 4.2.3 (実行処理) and 3.2 (通信フロー).
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from concurrent.futures import ThreadPoolExecutor, as_completed

from .database.models import Job, JobItem, ProjectRevision, Dataset, SystemSetting
from .prompt import PromptTemplateParser
from .llm import get_llm_client, LLMClient
from .parser import ResponseParser
from sqlalchemy import text

logger = logging.getLogger(__name__)


class JobManager:
    """Manages job creation and execution.

    Specification: docs/req.txt section 3.2, 4.2.3
    """

    def __init__(self, db: Session):
        """Initialize job manager.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.parser = PromptTemplateParser()

    def create_single_job(
        self,
        project_revision_id: int,
        input_params: Dict[str, str],
        repeat: int = 1,
        model_name: str = None
    ) -> Job:
        """Create a single execution job.

        Args:
            project_revision_id: ID of project revision to use
            input_params: Dictionary of parameter name -> value
            repeat: Number of times to repeat execution (default 1, max 10)

        Returns:
            Created Job object (not yet executed)

        Specification: docs/req.txt section 4.2.3
        Phase 1: repeat は最大10程度に制限
        """
        # Validate and normalize repeat count
        repeat = max(1, min(repeat, 10))

        # Create job
        job = Job(
            project_revision_id=project_revision_id,
            job_type="single",
            status="pending",
            model_name=model_name
        )
        self.db.add(job)
        self.db.flush()  # Get job.id

        # Get project revision to access prompt template
        revision = self.db.query(ProjectRevision).filter(
            ProjectRevision.id == project_revision_id
        ).first()

        if not revision:
            raise ValueError(f"Project revision {project_revision_id} not found")

        # Create job items (one per repeat)
        for i in range(repeat):
            # Substitute parameters into template
            raw_prompt = self.parser.substitute_parameters(
                revision.prompt_template,
                input_params
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

        # Execute all pending job items
        job_items = self.db.query(JobItem).filter(
            JobItem.job_id == job_id,
            JobItem.status == "pending"
        ).all()

        error_count = 0

        # Get revision for parser (fetch once, use for all items)
        revision = self.db.query(ProjectRevision).filter(
            ProjectRevision.id == job.project_revision_id
        ).first()

        if parallelism == 1:
            # Serial execution (original behavior)
            error_count = self._execute_items_serial(job_items, llm_client, revision, temperature)
        else:
            # Parallel execution
            error_count = self._execute_items_parallel(job_items, llm_client, revision, temperature, parallelism)

        # Merge CSV outputs for batch jobs and repeated single executions (Phase 2)
        if job.job_type == "batch" or (job.job_type == "single" and len(job_items) > 1):
            # Expire session cache to ensure we get fresh data from database
            self.db.expire_all()
            # Re-fetch job items to get updated status and parsed_response after execution
            job_items_for_csv = self.db.query(JobItem).filter(JobItem.job_id == job_id).all()
            merged_csv = self._merge_csv_outputs(job_items_for_csv, include_csv_header)
            job.merged_csv_output = merged_csv

        # Calculate actual wall-clock time for job execution
        end_time = datetime.utcnow()
        actual_turnaround_ms = int((end_time - start_time).total_seconds() * 1000)

        # Update job status
        job.finished_at = end_time.isoformat()
        job.turnaround_ms = actual_turnaround_ms  # Real elapsed time, not sum of individual times
        job.status = "error" if error_count > 0 else "done"
        self.db.commit()
        self.db.refresh(job)

        return job

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

    def _execute_items_serial(
        self,
        job_items: List[JobItem],
        llm_client: LLMClient,
        revision: ProjectRevision,
        temperature: float
    ) -> int:
        """Execute job items serially (one at a time).

        Args:
            job_items: List of job items to execute
            llm_client: LLM client instance
            revision: Project revision for parser
            temperature: LLM temperature

        Returns:
            Number of errors encountered
        """
        error_count = 0

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
                response = llm_client.call(item.raw_prompt, temperature=temperature)

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
        max_workers: int
    ) -> int:
        """Execute job items in parallel using ThreadPoolExecutor.

        Args:
            job_items: List of job items to execute
            llm_client: LLM client instance
            revision: Project revision for parser
            temperature: LLM temperature
            max_workers: Maximum number of parallel workers

        Returns:
            Number of errors encountered
        """
        from backend.database import SessionLocal

        error_count = 0

        def execute_single_item(item_id: int, raw_prompt: str, parser_config: str) -> int:
            """Execute a single job item with its own database session.

            Args:
                item_id: JobItem ID to process
                raw_prompt: The prompt text to send to LLM
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
                    response = llm_client.call(raw_prompt, temperature=temperature)

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

        # Execute items in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all items with their data (not the ORM objects)
            future_to_item = {
                executor.submit(execute_single_item, item.id, item.raw_prompt, parser_config): item
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

        # Sort job_items by ID to ensure consistent order, especially for parallel execution
        # This guarantees that CSV rows appear in the same order as they were created
        sorted_items = sorted(job_items, key=lambda x: x.id)

        logger.info(f"CSV merge: Processing {len(sorted_items)} items, include_header={include_csv_header}")

        for item in sorted_items:
            # Skip items that are not successfully completed
            if item.status != "done" or not item.parsed_response:
                logger.debug(f"CSV merge: Skipping item {item.id} - status={item.status}, has_parsed={bool(item.parsed_response)}")
                continue

            try:
                parsed = json.loads(item.parsed_response)
                csv_output = parsed.get("csv_output", "")

                logger.debug(f"CSV merge: Item {item.id} - has_csv_output={bool(csv_output)}, parsed_keys={list(parsed.keys())}")

                if not csv_output:
                    logger.warning(f"CSV merge: Item {item.id} has no csv_output field in parsed response")
                    continue

                # Add header from first successful item (only once)
                if not header_added and include_csv_header:
                    fields = parsed.get("fields", {})
                    if fields:
                        # Generate header from field names in order
                        header_line = ",".join(fields.keys())
                        csv_lines.append(header_line)
                        header_added = True
                        logger.info(f"CSV merge: Added header: {header_line}")

                # Add data line
                csv_lines.append(csv_output)
                logger.debug(f"CSV merge: Added line from item {item.id}: {csv_output[:100]}")

            except (json.JSONDecodeError, KeyError) as e:
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
        project_revision_id: int,
        dataset_id: int,
        model_name: str = None
    ) -> Job:
        """Create a batch execution job from dataset.

        Args:
            project_revision_id: ID of project revision to use
            dataset_id: ID of dataset to process
            model_name: Name of LLM model to use (optional)

        Returns:
            Created Job object (not yet executed)

        Specification: docs/req.txt section 4.3.2 (バッチ実行フロー)
        Phase 2
        """
        # Get dataset
        dataset = self.db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            raise ValueError(f"Dataset {dataset_id} not found")

        # Get project revision
        revision = self.db.query(ProjectRevision).filter(
            ProjectRevision.id == project_revision_id
        ).first()
        if not revision:
            raise ValueError(f"Project revision {project_revision_id} not found")

        # Create job
        job = Job(
            project_revision_id=project_revision_id,
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

        # Create job items for each row
        for row in rows:
            # Build input_params from row data using _mapping
            input_params = {}
            for col in columns:
                value = row._mapping.get(col)
                input_params[col] = str(value) if value is not None else ""

            # Substitute parameters into template
            raw_prompt = self.parser.substitute_parameters(
                revision.prompt_template,
                input_params
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

        # Update job status if needed
        remaining_pending = self.db.query(JobItem).filter(
            JobItem.job_id == job_id,
            JobItem.status == "pending"
        ).count()

        remaining_running = self.db.query(JobItem).filter(
            JobItem.job_id == job_id,
            JobItem.status == "running"
        ).count()

        # If no more pending or running items, mark job as done
        if remaining_pending == 0 and remaining_running == 0 and job.status == "running":
            job.finished_at = datetime.utcnow().isoformat()
            self.db.commit()

        return {
            "job_id": job_id,
            "cancelled_count": cancelled_count,
            "message": f"Cancelled {cancelled_count} pending item(s)"
        }

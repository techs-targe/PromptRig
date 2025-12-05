"""Job management logic for executing LLM prompts.

Based on specification in docs/req.txt section 4.2.3 (実行処理) and 3.2 (通信フロー).
"""

import json
from datetime import datetime
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from .database.models import Job, JobItem, ProjectRevision, Dataset
from .prompt import PromptTemplateParser
from .llm import get_llm_client, LLMClient
from .parser import ResponseParser
from sqlalchemy import text


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
        repeat: int = 1
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
            status="pending"
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

        # Execute all pending job items
        job_items = self.db.query(JobItem).filter(
            JobItem.job_id == job_id,
            JobItem.status == "pending"
        ).all()

        error_count = 0

        for item in job_items:
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
                    revision = self.db.query(ProjectRevision).filter(
                        ProjectRevision.id == job.project_revision_id
                    ).first()
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

        # Merge CSV outputs for batch jobs and repeated single executions (Phase 2)
        if job.job_type == "batch" or (job.job_type == "single" and len(job_items) > 1):
            merged_csv = self._merge_csv_outputs(job_items, include_csv_header)
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

    def _merge_csv_outputs(self, job_items: List[JobItem], include_csv_header: bool) -> str:
        """Merge CSV outputs from multiple job items.

        Args:
            job_items: List of job items with parsed responses
            include_csv_header: If True, include header from first item

        Returns:
            Merged CSV string with newline-separated rows

        Specification: Phase 2 batch CSV merge feature
        """
        csv_lines = []
        header_line = None

        for idx, item in enumerate(job_items):
            if not item.parsed_response:
                continue

            try:
                parsed = json.loads(item.parsed_response)
                csv_output = parsed.get("csv_output", "")

                if not csv_output:
                    continue

                # For first item, extract potential header
                if idx == 0 and include_csv_header:
                    # Check if parser config has csv_template
                    # The csv_output should be the data line
                    # We need to generate header from field names
                    fields = parsed.get("fields", {})
                    if fields:
                        # Generate header from field names in order they appear in csv_template
                        # For now, use field names directly as header
                        header_line = ",".join(fields.keys())
                        csv_lines.append(header_line)

                # Add data line
                csv_lines.append(csv_output)

            except (json.JSONDecodeError, KeyError):
                # Skip items with invalid parsed response
                continue

        return "\n".join(csv_lines)

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
        dataset_id: int
    ) -> Job:
        """Create a batch execution job from dataset.

        Args:
            project_revision_id: ID of project revision to use
            dataset_id: ID of dataset to process

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
            dataset_id=dataset_id
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

        return {
            "job_id": job.id,
            "job_type": job.job_type,
            "status": job.status,
            "total_items": total,
            "completed": completed,
            "errors": errors,
            "pending": pending,
            "running": running,
            "progress_percent": int((completed + errors) / total * 100) if total > 0 else 0,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "turnaround_ms": job.turnaround_ms
        }

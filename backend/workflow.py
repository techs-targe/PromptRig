"""Workflow execution engine for multi-step prompt pipelines.

Allows chaining multiple projects (prompts) together,
with output from one step feeding into the next.
"""

import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session

from .database.models import (
    Workflow, WorkflowStep, WorkflowJob, WorkflowJobStep,
    Project, ProjectRevision, Prompt, PromptRevision, Job, JobItem
)
from .job import JobManager
from .prompt import PromptTemplateParser

logger = logging.getLogger(__name__)


class WorkflowManager:
    """Manages workflow creation and execution.

    Supports sequential execution with step output passing:
    - {{step1.field}} - Reference output from step named "step1"
    - {{input.param}} - Reference initial input parameter
    """

    # Pattern to match step references: {{step_name.field_name}}
    STEP_REF_PATTERN = re.compile(r'\{\{(\w+)\.(\w+)\}\}')

    def __init__(self, db: Session):
        """Initialize workflow manager.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.job_manager = JobManager(db)
        self.prompt_parser = PromptTemplateParser()

    def create_workflow(self, name: str, description: str = "", project_id: int = None) -> Workflow:
        """Create a new workflow.

        Args:
            name: Workflow name
            description: Optional description
            project_id: Optional project ID to associate this workflow with

        Returns:
            Created Workflow object
        """
        workflow = Workflow(name=name, description=description, project_id=project_id)
        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)
        logger.info(f"Created workflow: {workflow.id} - {name} (project_id={project_id})")
        return workflow

    def update_workflow(self, workflow_id: int, name: str = None, description: str = None) -> Workflow:
        """Update workflow metadata.

        Args:
            workflow_id: Workflow ID
            name: New name (optional)
            description: New description (optional)

        Returns:
            Updated Workflow object
        """
        workflow = self.db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        if name is not None:
            workflow.name = name
        if description is not None:
            workflow.description = description
        workflow.updated_at = datetime.utcnow().isoformat()

        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    def delete_workflow(self, workflow_id: int) -> bool:
        """Delete a workflow and all its steps.

        Args:
            workflow_id: Workflow ID

        Returns:
            True if deleted
        """
        workflow = self.db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        self.db.delete(workflow)
        self.db.commit()
        logger.info(f"Deleted workflow: {workflow_id}")
        return True

    def add_step(
        self,
        workflow_id: int,
        step_name: str,
        project_id: int,
        prompt_id: int = None,
        step_order: int = None,
        input_mapping: Dict[str, str] = None,
        execution_mode: str = "sequential"
    ) -> WorkflowStep:
        """Add a step to a workflow.

        Args:
            workflow_id: Workflow ID
            step_name: Unique name for this step (e.g., "step1", "summarize")
            project_id: Project to use for this step
            prompt_id: Prompt to use for this step (NEW ARCHITECTURE)
            step_order: Execution order (auto-assigned if None)
            input_mapping: Parameter mapping {"param": "{{step1.field}}"}
            execution_mode: "sequential" (default) or "parallel" (future)

        Returns:
            Created WorkflowStep object
        """
        # Validate workflow exists
        workflow = self.db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        # Validate project exists
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"Project {project_id} not found")

        # Validate prompt exists if provided
        if prompt_id:
            prompt = self.db.query(Prompt).filter(Prompt.id == prompt_id).first()
            if not prompt:
                raise ValueError(f"Prompt {prompt_id} not found")

        # Auto-assign step order if not provided
        if step_order is None:
            max_order = self.db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == workflow_id
            ).count()
            step_order = max_order + 1

        step = WorkflowStep(
            workflow_id=workflow_id,
            step_order=step_order,
            step_name=step_name,
            project_id=project_id,
            prompt_id=prompt_id,
            execution_mode=execution_mode,
            input_mapping=json.dumps(input_mapping or {}, ensure_ascii=False)
        )
        self.db.add(step)
        self.db.commit()
        self.db.refresh(step)

        logger.info(f"Added step to workflow {workflow_id}: {step_name} (order={step_order}, prompt_id={prompt_id})")
        return step

    def update_step(
        self,
        step_id: int,
        step_name: str = None,
        project_id: int = None,
        prompt_id: int = None,
        step_order: int = None,
        input_mapping: Dict[str, str] = None
    ) -> WorkflowStep:
        """Update a workflow step.

        Args:
            step_id: Step ID
            step_name: New step name (optional)
            project_id: New project ID (optional)
            prompt_id: New prompt ID (optional, NEW ARCHITECTURE)
            step_order: New order (optional)
            input_mapping: New input mapping (optional)

        Returns:
            Updated WorkflowStep object
        """
        step = self.db.query(WorkflowStep).filter(WorkflowStep.id == step_id).first()
        if not step:
            raise ValueError(f"Step {step_id} not found")

        if step_name is not None:
            step.step_name = step_name
        if project_id is not None:
            step.project_id = project_id
        if prompt_id is not None:
            step.prompt_id = prompt_id
        if step_order is not None:
            step.step_order = step_order
        if input_mapping is not None:
            step.input_mapping = json.dumps(input_mapping, ensure_ascii=False)

        self.db.commit()
        self.db.refresh(step)
        return step

    def remove_step(self, step_id: int) -> bool:
        """Remove a step from a workflow.

        Args:
            step_id: Step ID

        Returns:
            True if removed
        """
        step = self.db.query(WorkflowStep).filter(WorkflowStep.id == step_id).first()
        if not step:
            raise ValueError(f"Step {step_id} not found")

        workflow_id = step.workflow_id
        self.db.delete(step)
        self.db.commit()

        # Renumber remaining steps
        self._renumber_steps(workflow_id)
        return True

    def _renumber_steps(self, workflow_id: int):
        """Renumber steps after deletion to maintain order."""
        steps = self.db.query(WorkflowStep).filter(
            WorkflowStep.workflow_id == workflow_id
        ).order_by(WorkflowStep.step_order).all()

        for i, step in enumerate(steps, 1):
            step.step_order = i
        self.db.commit()

    def get_workflow(self, workflow_id: int) -> Optional[Workflow]:
        """Get a workflow by ID.

        Args:
            workflow_id: Workflow ID

        Returns:
            Workflow object or None
        """
        return self.db.query(Workflow).filter(Workflow.id == workflow_id).first()

    def list_workflows(self) -> List[Workflow]:
        """List all workflows.

        Returns:
            List of Workflow objects
        """
        return self.db.query(Workflow).order_by(Workflow.created_at.desc()).all()

    def execute_workflow(
        self,
        workflow_id: int,
        input_params: Dict[str, str],
        model_name: str = None,
        temperature: float = 0.7,
        workflow_job_id: int = None
    ) -> WorkflowJob:
        """Execute a workflow with given input parameters.

        Args:
            workflow_id: Workflow ID
            input_params: Initial input parameters
            model_name: LLM model to use
            temperature: Temperature for LLM
            workflow_job_id: Existing workflow job ID to use (optional)

        Returns:
            WorkflowJob with execution results
        """
        workflow = self.db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        start_time = datetime.utcnow()

        # Use existing job or create new one
        if workflow_job_id:
            workflow_job = self.db.query(WorkflowJob).filter(WorkflowJob.id == workflow_job_id).first()
            if not workflow_job:
                raise ValueError(f"WorkflowJob {workflow_job_id} not found")
            workflow_job.status = "running"
            workflow_job.started_at = start_time.isoformat()
        else:
            # Create workflow job
            workflow_job = WorkflowJob(
                workflow_id=workflow_id,
                status="running",
                input_params=json.dumps(input_params, ensure_ascii=False),
                model_name=model_name,
                started_at=start_time.isoformat()
            )
            self.db.add(workflow_job)
        self.db.flush()

        logger.info(f"Starting workflow execution: {workflow_id}, job={workflow_job.id}")

        # Get steps ordered by step_order
        steps = self.db.query(WorkflowStep).filter(
            WorkflowStep.workflow_id == workflow_id
        ).order_by(WorkflowStep.step_order).all()

        if not steps:
            workflow_job.status = "error"
            workflow_job.merged_output = json.dumps({"error": "No steps in workflow"}, ensure_ascii=False)
            workflow_job.finished_at = datetime.utcnow().isoformat()
            self.db.commit()
            raise ValueError("Workflow has no steps")

        # Context to store step outputs
        step_context: Dict[str, Dict[str, Any]] = {}

        # Add initial input params to context (accessible as {{input.field}})
        step_context["input"] = input_params

        error_occurred = False
        error_message = None

        for step in steps:
            step_start_time = datetime.utcnow()

            # Create job step record
            job_step = WorkflowJobStep(
                workflow_job_id=workflow_job.id,
                workflow_step_id=step.id,
                step_order=step.step_order,
                status="running",
                started_at=step_start_time.isoformat()
            )
            self.db.add(job_step)
            self.db.flush()

            try:
                logger.info(f"Executing step {step.step_order}: {step.step_name}")

                # Resolve input parameters for this step
                step_input_params = self._resolve_step_inputs(
                    step, input_params, step_context
                )
                job_step.input_params = json.dumps(step_input_params, ensure_ascii=False)

                # Execute the step using existing JobManager
                output_fields, job_id = self._execute_step(
                    step, step_input_params, model_name, temperature
                )

                # Store output in context for next step
                step_context[step.step_name] = output_fields

                # Update job step
                step_end_time = datetime.utcnow()
                job_step.job_id = job_id
                job_step.status = "done"
                job_step.output_fields = json.dumps(output_fields, ensure_ascii=False)
                job_step.finished_at = step_end_time.isoformat()
                job_step.turnaround_ms = int((step_end_time - step_start_time).total_seconds() * 1000)

                logger.info(f"Step {step.step_name} completed: {job_step.turnaround_ms}ms")

            except Exception as e:
                logger.error(f"Step {step.step_name} failed: {str(e)}")
                job_step.status = "error"
                job_step.error_message = str(e)
                job_step.finished_at = datetime.utcnow().isoformat()
                error_occurred = True
                error_message = f"Step {step.step_name} failed: {str(e)}"
                break  # Stop on first error for sequential execution

            self.db.commit()

        # Merge all step outputs
        merged_output = self._merge_outputs(step_context)
        if error_occurred:
            merged_output["_error"] = error_message

        # Update workflow job
        end_time = datetime.utcnow()
        workflow_job.status = "error" if error_occurred else "done"
        workflow_job.merged_output = json.dumps(merged_output, ensure_ascii=False)
        workflow_job.finished_at = end_time.isoformat()
        workflow_job.turnaround_ms = int((end_time - start_time).total_seconds() * 1000)

        self.db.commit()
        self.db.refresh(workflow_job)

        logger.info(f"Workflow execution finished: {workflow_job.status}, {workflow_job.turnaround_ms}ms")
        return workflow_job

    def _resolve_step_inputs(
        self,
        step: WorkflowStep,
        initial_params: Dict[str, str],
        step_context: Dict[str, Dict[str, Any]]
    ) -> Dict[str, str]:
        """Resolve input parameters for a step, substituting step references.

        Args:
            step: WorkflowStep to resolve inputs for
            initial_params: Initial input parameters
            step_context: Context with outputs from previous steps

        Returns:
            Resolved input parameters
        """
        # For first step, use initial params
        if step.step_order == 1:
            return dict(initial_params)

        # Start with empty dict for subsequent steps
        resolved = {}

        # Apply input mapping if defined
        if step.input_mapping:
            mapping = json.loads(step.input_mapping)
            for param_name, ref_pattern in mapping.items():
                resolved[param_name] = self._substitute_step_refs(
                    ref_pattern, step_context
                )

        return resolved

    def _substitute_step_refs(
        self,
        template: str,
        step_context: Dict[str, Dict[str, Any]]
    ) -> str:
        """Substitute {{step_name.field}} references with actual values.

        Args:
            template: Template string with {{step.field}} references
            step_context: Context with step outputs

        Returns:
            String with substituted values
        """
        def replacer(match):
            step_name = match.group(1)
            field_name = match.group(2)

            if step_name in step_context:
                value = step_context[step_name].get(field_name, "")
                return str(value) if value is not None else ""
            return match.group(0)  # Keep original if not found

        return self.STEP_REF_PATTERN.sub(replacer, template)

    def _execute_step(
        self,
        step: WorkflowStep,
        input_params: Dict[str, str],
        model_name: str = None,
        temperature: float = 0.7
    ) -> tuple[Dict[str, Any], int]:
        """Execute a single step and return parsed output fields.

        Args:
            step: WorkflowStep to execute
            input_params: Input parameters for this step
            model_name: LLM model to use
            temperature: Temperature for LLM

        Returns:
            Tuple of (output_fields dict, job_id)
        """
        revision = None
        prompt_revision = None

        # NEW ARCHITECTURE: Use PromptRevision if prompt_id is set
        if step.prompt_id:
            prompt_revision = self.db.query(PromptRevision).filter(
                PromptRevision.prompt_id == step.prompt_id
            ).order_by(PromptRevision.revision.desc()).first()

            if not prompt_revision:
                raise ValueError(f"No revision found for prompt {step.prompt_id}")
        else:
            # OLD ARCHITECTURE: Fall back to ProjectRevision
            revision = self.db.query(ProjectRevision).filter(
                ProjectRevision.project_id == step.project_id
            ).order_by(ProjectRevision.revision.desc()).first()

            if not revision:
                raise ValueError(f"No revision found for project {step.project_id}")

        # Create and execute job using existing JobManager
        if prompt_revision:
            # NEW ARCHITECTURE: Use prompt_revision_id
            job = self.job_manager.create_single_job(
                prompt_revision_id=prompt_revision.id,
                input_params=input_params,
                repeat=1,
                model_name=model_name
            )
        else:
            # OLD ARCHITECTURE: Use project_revision_id
            job = self.job_manager.create_single_job(
                project_revision_id=revision.id,
                input_params=input_params,
                repeat=1,
                model_name=model_name
            )

        # Execute the job
        executed_job = self.job_manager.execute_job(
            job_id=job.id,
            model_name=model_name,
            include_csv_header=True,
            temperature=temperature
        )

        # Extract parsed fields from first job item
        job_items = self.db.query(JobItem).filter(
            JobItem.job_id == executed_job.id
        ).all()

        if not job_items:
            raise ValueError(f"No job items created for step {step.step_name}")

        job_item = job_items[0]
        if job_item.status != "done":
            raise ValueError(f"Step execution failed: {job_item.error_message}")

        # Parse response
        parsed = {}
        if job_item.parsed_response:
            parsed = json.loads(job_item.parsed_response)

        # Return fields plus raw response
        return {
            "raw": job_item.raw_response,
            "parsed": parsed.get("parsed", False),
            **parsed.get("fields", {})
        }, executed_job.id

    def _merge_outputs(
        self,
        step_context: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Merge all step outputs into final result.

        Args:
            step_context: Context with all step outputs

        Returns:
            Merged output dictionary
        """
        merged = {}
        for step_name, fields in step_context.items():
            if step_name == "input":
                continue  # Skip input params
            merged[step_name] = fields
        return merged

    def get_workflow_job(self, job_id: int) -> Optional[WorkflowJob]:
        """Get a workflow job by ID.

        Args:
            job_id: WorkflowJob ID

        Returns:
            WorkflowJob object or None
        """
        return self.db.query(WorkflowJob).filter(WorkflowJob.id == job_id).first()

    def list_workflow_jobs(self, workflow_id: int, limit: int = 50) -> List[WorkflowJob]:
        """List jobs for a workflow.

        Args:
            workflow_id: Workflow ID
            limit: Maximum number of jobs to return

        Returns:
            List of WorkflowJob objects
        """
        return self.db.query(WorkflowJob).filter(
            WorkflowJob.workflow_id == workflow_id
        ).order_by(WorkflowJob.created_at.desc()).limit(limit).all()

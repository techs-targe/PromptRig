"""SQLAlchemy models for Prompt Evaluation System.

Based on specification in docs/req.txt section 5 (DB設計).
"""

from datetime import datetime
from sqlalchemy import Column, Integer, Text, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Project(Base):
    """Project table - stores project metadata.

    Specification: docs/req.txt section 5.2
    NEW ARCHITECTURE: Project contains multiple Prompts and Workflows
    """
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    description = Column(Text)
    created_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())

    # Relationships - OLD (for backward compatibility during migration)
    revisions = relationship("ProjectRevision", back_populates="project", cascade="all, delete-orphan")
    datasets = relationship("Dataset", back_populates="project", cascade="all, delete-orphan")

    # Relationships - NEW (for new architecture)
    prompts = relationship("Prompt", back_populates="project", cascade="all, delete-orphan")
    project_workflows = relationship("Workflow", back_populates="project", foreign_keys="Workflow.project_id")


class ProjectRevision(Base):
    """Project revision table - stores prompt template and parser versions.

    Specification: docs/req.txt section 5.3
    DEPRECATED: Use PromptRevision instead. Kept for backward compatibility.
    """
    __tablename__ = "project_revisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    revision = Column(Integer, nullable=False)
    prompt_template = Column(Text, nullable=False)  # Contains {{}} syntax
    parser_config = Column(Text)  # JSON format
    created_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())

    # Relationships
    project = relationship("Project", back_populates="revisions")
    jobs = relationship("Job", back_populates="project_revision", cascade="all, delete-orphan")

    # Index for efficient querying
    __table_args__ = (
        Index("idx_project_revision", "project_id", "revision"),
    )


# ========== NEW ARCHITECTURE MODELS (v3.0) ==========

class Prompt(Base):
    """Prompt definition within a project.

    NEW ARCHITECTURE: A project can have multiple prompts.
    Each prompt has its own revisions (versions).
    Each prompt can have multiple tags for access control.
    """
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text)
    is_deleted = Column(Integer, nullable=False, default=0)  # 0=active, 1=deleted (soft delete)
    deleted_at = Column(Text, nullable=True)  # Timestamp when deleted
    created_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())
    updated_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())

    # Relationships
    project = relationship("Project", back_populates="prompts")
    revisions = relationship("PromptRevision", back_populates="prompt", cascade="all, delete-orphan")
    workflow_steps = relationship("WorkflowStep", back_populates="prompt", foreign_keys="WorkflowStep.prompt_id")
    tags = relationship("PromptTag", back_populates="prompt", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_prompts_project", "project_id"),
        Index("idx_prompts_deleted", "is_deleted"),
    )


class PromptRevision(Base):
    """Prompt revision - stores prompt template and parser versions.

    NEW ARCHITECTURE: Replaces ProjectRevision.
    Each prompt can have multiple revisions for version control.
    """
    __tablename__ = "prompt_revisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prompt_id = Column(Integer, ForeignKey("prompts.id"), nullable=False)
    revision = Column(Integer, nullable=False)
    prompt_template = Column(Text, nullable=False)  # Contains {{}} syntax
    parser_config = Column(Text)  # JSON format
    created_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())

    # Relationships
    prompt = relationship("Prompt", back_populates="revisions")
    prompt_jobs = relationship("Job", back_populates="prompt_revision", foreign_keys="Job.prompt_revision_id")

    __table_args__ = (
        Index("idx_prompt_revision", "prompt_id", "revision"),
        # Unique constraint to prevent duplicate revisions
        # (prompt_id, revision) must be unique
    )


class Job(Base):
    """Job table - stores execution job metadata.

    Specification: docs/req.txt section 5.4
    NEW ARCHITECTURE: Uses prompt_revision_id (project_revision_id kept for backward compatibility)
    """
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # OLD: kept for backward compatibility during migration
    project_revision_id = Column(Integer, ForeignKey("project_revisions.id"), nullable=True)
    # NEW: reference to prompt revision
    prompt_revision_id = Column(Integer, ForeignKey("prompt_revisions.id"), nullable=True)
    job_type = Column(Text, nullable=False)  # 'single' or 'batch'
    status = Column(Text, nullable=False, default="pending")  # pending/running/done/error
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=True)  # Only for batch jobs
    model_name = Column(Text, nullable=True)  # LLM model used (e.g., 'azure-gpt-5-mini')
    created_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())
    started_at = Column(Text, nullable=True)
    finished_at = Column(Text, nullable=True)
    turnaround_ms = Column(Integer, nullable=True)
    merged_csv_output = Column(Text, nullable=True)  # Merged CSV output for batch jobs

    # Relationships - OLD (backward compatibility)
    project_revision = relationship("ProjectRevision", back_populates="jobs")
    # Relationships - NEW
    prompt_revision = relationship("PromptRevision", back_populates="prompt_jobs", foreign_keys=[prompt_revision_id])
    job_items = relationship("JobItem", back_populates="job", cascade="all, delete-orphan")
    dataset = relationship("Dataset", foreign_keys=[dataset_id])

    # Index for efficient querying
    __table_args__ = (
        Index("idx_job_status", "status"),
        Index("idx_job_created", "created_at"),
    )


class JobItem(Base):
    """Job item table - stores individual execution results.

    Specification: docs/req.txt section 5.5
    """
    __tablename__ = "job_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    created_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())
    input_params = Column(Text, nullable=False)  # JSON format
    raw_prompt = Column(Text, nullable=False)  # Prompt after {{}} substitution
    raw_response = Column(Text, nullable=True)  # LLM response
    parsed_response = Column(Text, nullable=True)  # JSON format
    status = Column(Text, nullable=False, default="pending")  # pending/running/done/error
    error_message = Column(Text, nullable=True)
    turnaround_ms = Column(Integer, nullable=True)

    # Relationships
    job = relationship("Job", back_populates="job_items")

    # Index for efficient querying
    __table_args__ = (
        Index("idx_job_item_job", "job_id"),
        Index("idx_job_item_status", "status"),
    )


class Dataset(Base):
    """Dataset table - stores imported dataset metadata.

    Specification: docs/req.txt section 5.6
    Phase 2 feature, but table structure defined for completeness.
    """
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name = Column(Text, nullable=False)
    source_file_name = Column(Text, nullable=False)
    sqlite_table_name = Column(Text, nullable=False)  # e.g., Dataset_PJ1_20241205_001
    created_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())

    # Relationships
    project = relationship("Project", back_populates="datasets")


class SystemSetting(Base):
    """System settings table - key-value configuration storage.

    Specification: docs/req.txt section 5.7
    """
    __tablename__ = "system_settings"

    key = Column(Text, primary_key=True)
    value = Column(Text)


# ========== TAG SYSTEM TABLES (v3.1) ==========

class Tag(Base):
    """Tag table - defines tags for prompt access control.

    Tags are used to control which prompts can be sent to which LLM models.
    - Each prompt can have multiple tags
    - Each LLM model has a list of allowed tags
    - Request is blocked if prompt tags don't match model's allowed tags
    - "ALL" tag is the default tag for all prompts (backward compatibility)
    """
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False, unique=True)
    color = Column(Text, nullable=False, default="#6b7280")  # Hex color code
    description = Column(Text)
    is_system = Column(Integer, nullable=False, default=0)  # 1 = system tag (cannot delete)
    created_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())

    # Relationships
    prompt_tags = relationship("PromptTag", back_populates="tag", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_tags_name", "name"),
    )


class PromptTag(Base):
    """Junction table for prompt-tag many-to-many relationship."""
    __tablename__ = "prompt_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prompt_id = Column(Integer, ForeignKey("prompts.id"), nullable=False)
    tag_id = Column(Integer, ForeignKey("tags.id"), nullable=False)
    created_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())

    # Relationships
    prompt = relationship("Prompt", back_populates="tags")
    tag = relationship("Tag", back_populates="prompt_tags")

    __table_args__ = (
        Index("idx_prompt_tags_prompt", "prompt_id"),
        Index("idx_prompt_tags_tag", "tag_id"),
        # Unique constraint to prevent duplicate tag assignments
        Index("idx_prompt_tags_unique", "prompt_id", "tag_id", unique=True),
    )


# ========== WORKFLOW TABLES (v2.0) ==========

class Workflow(Base):
    """Workflow table - defines multi-step prompt pipelines.

    NEW ARCHITECTURE: Workflows belong to a project and chain prompts together.
    """
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # NEW: workflow belongs to a project
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    name = Column(Text, nullable=False)
    description = Column(Text)
    # Auto-context: automatically include previous steps' USER/ASSISTANT in CONTEXT field
    auto_context = Column(Integer, nullable=False, default=0)  # 0=disabled, 1=enabled
    created_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())
    updated_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())

    # Relationships
    project = relationship("Project", back_populates="project_workflows", foreign_keys=[project_id])
    steps = relationship("WorkflowStep", back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowStep.step_order")
    workflow_jobs = relationship("WorkflowJob", back_populates="workflow", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_workflows_project", "project_id"),
    )


class WorkflowStep(Base):
    """Workflow step - references a prompt within the workflow's project.

    NEW ARCHITECTURE: Steps now reference prompts (not projects).
    Each step can map inputs from previous step outputs using
    the {{step_name.field}} syntax in input_mapping.

    CONTROL FLOW: step_type determines the step behavior:
    - prompt: Execute LLM prompt (default)
    - set: Set/modify variables
    - if/elif/else/endif: Conditional branching
    - loop/endloop: Loop with condition
    - foreach/endforeach: Iterate over list
    - break/continue: Loop control
    """
    __tablename__ = "workflow_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    step_order = Column(Integer, nullable=False)
    step_name = Column(Text, nullable=False)  # e.g., "step1", "summarize"
    # Step type for control flow
    step_type = Column(Text, nullable=False, default="prompt")  # prompt/set/if/elif/else/endif/loop/endloop/foreach/endforeach/break/continue
    # OLD: kept for backward compatibility during migration
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    # NEW: reference to prompt within the project
    prompt_id = Column(Integer, ForeignKey("prompts.id"), nullable=True)
    execution_mode = Column(Text, nullable=False, default="sequential")  # sequential/parallel (future)
    condition_config = Column(Text)  # JSON for control flow settings (conditions, assignments, etc.)
    input_mapping = Column(Text)  # JSON: {"param_name": "{{step1.field_name}}"}
    created_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())

    # Relationships - OLD (backward compatibility)
    workflow = relationship("Workflow", back_populates="steps")
    project = relationship("Project")
    # Relationships - NEW
    prompt = relationship("Prompt", back_populates="workflow_steps", foreign_keys=[prompt_id])

    __table_args__ = (
        Index("idx_workflow_steps_workflow", "workflow_id"),
        Index("idx_workflow_steps_prompt", "prompt_id"),
    )


class WorkflowJob(Base):
    """Workflow job - execution instance of a workflow.

    Tracks overall workflow execution status and merged results.
    """
    __tablename__ = "workflow_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    status = Column(Text, nullable=False, default="pending")  # pending/running/done/error
    input_params = Column(Text)  # JSON: initial input parameters
    merged_output = Column(Text)  # JSON: merged results from all steps
    merged_csv_output = Column(Text)  # Merged CSV output from all steps with csv_template parser
    model_name = Column(Text)
    created_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())
    started_at = Column(Text)
    finished_at = Column(Text)
    turnaround_ms = Column(Integer)

    # Relationships
    workflow = relationship("Workflow", back_populates="workflow_jobs")
    step_results = relationship("WorkflowJobStep", back_populates="workflow_job", cascade="all, delete-orphan", order_by="WorkflowJobStep.step_order")

    __table_args__ = (
        Index("idx_workflow_jobs_workflow", "workflow_id"),
        Index("idx_workflow_jobs_status", "status"),
    )


class WorkflowJobStep(Base):
    """Individual step result within a workflow job.

    Tracks execution of each step and stores output for next step.
    """
    __tablename__ = "workflow_job_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_job_id = Column(Integer, ForeignKey("workflow_jobs.id"), nullable=False)
    workflow_step_id = Column(Integer, ForeignKey("workflow_steps.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"))  # Links to regular Job for execution
    step_order = Column(Integer, nullable=False)
    status = Column(Text, nullable=False, default="pending")  # pending/running/done/error/skipped
    input_params = Column(Text)  # JSON: input params after substitution
    output_fields = Column(Text)  # JSON: parsed fields for next step
    error_message = Column(Text)
    created_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())
    started_at = Column(Text)
    finished_at = Column(Text)
    turnaround_ms = Column(Integer)

    # Relationships
    workflow_job = relationship("WorkflowJob", back_populates="step_results")
    workflow_step = relationship("WorkflowStep")
    job = relationship("Job")

    __table_args__ = (
        Index("idx_workflow_job_steps_job", "workflow_job_id"),
    )

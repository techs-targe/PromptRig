"""Database module for Prompt Evaluation System."""

from .models import (
    Base, Project, ProjectRevision, Job, JobItem, SystemSetting, Dataset,
    Workflow, WorkflowStep, WorkflowJob, WorkflowJobStep,
    # NEW ARCHITECTURE (v3.0)
    Prompt, PromptRevision,
    # TAG SYSTEM (v3.1)
    Tag, PromptTag
)
from .database import engine, SessionLocal, get_db, init_db

__all__ = [
    "Base",
    "Project",
    "ProjectRevision",  # DEPRECATED: use PromptRevision
    "Job",
    "JobItem",
    "SystemSetting",
    "Dataset",
    # Workflow models (v2.0)
    "Workflow",
    "WorkflowStep",
    "WorkflowJob",
    "WorkflowJobStep",
    # NEW ARCHITECTURE (v3.0)
    "Prompt",
    "PromptRevision",
    # TAG SYSTEM (v3.1)
    "Tag",
    "PromptTag",
    # Database utilities
    "engine",
    "SessionLocal",
    "get_db",
    "init_db",
]

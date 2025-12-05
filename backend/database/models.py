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
    """
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    description = Column(Text)
    created_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())

    # Relationships
    revisions = relationship("ProjectRevision", back_populates="project", cascade="all, delete-orphan")
    datasets = relationship("Dataset", back_populates="project", cascade="all, delete-orphan")


class ProjectRevision(Base):
    """Project revision table - stores prompt template and parser versions.

    Specification: docs/req.txt section 5.3
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


class Job(Base):
    """Job table - stores execution job metadata.

    Specification: docs/req.txt section 5.4
    """
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_revision_id = Column(Integer, ForeignKey("project_revisions.id"), nullable=False)
    job_type = Column(Text, nullable=False)  # 'single' or 'batch'
    status = Column(Text, nullable=False, default="pending")  # pending/running/done/error
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=True)  # Only for batch jobs
    created_at = Column(Text, nullable=False, default=lambda: datetime.utcnow().isoformat())
    started_at = Column(Text, nullable=True)
    finished_at = Column(Text, nullable=True)
    turnaround_ms = Column(Integer, nullable=True)
    merged_csv_output = Column(Text, nullable=True)  # Merged CSV output for batch jobs

    # Relationships
    project_revision = relationship("ProjectRevision", back_populates="jobs")
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

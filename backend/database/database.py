"""Database connection and session management.

Based on specification in docs/req.txt section 2.3 and 3.1
"""

import logging
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

from .models import (
    Base, Project, ProjectRevision, Prompt, PromptRevision,
    Job, JobItem, Dataset, SystemSetting,
    Tag, PromptTag,
    Workflow, WorkflowStep, WorkflowJob, WorkflowJobStep
)

# Load environment variables
load_dotenv()

# Get database path from environment
DATABASE_PATH = os.getenv("DATABASE_PATH", "database/app.db")

# Ensure database directory exists
db_path = Path(DATABASE_PATH)
db_path.parent.mkdir(parents=True, exist_ok=True)

# Create SQLite engine
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # Needed for SQLite
    echo=False  # Set to True for SQL debugging
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """Dependency for FastAPI routes to get database session.

    Usage:
        @app.get("/")
        def route(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_db():
    """Apply database migrations for schema changes.

    Adds any missing columns to existing tables.
    """
    from sqlalchemy import text, inspect

    db = SessionLocal()
    try:
        inspector = inspect(engine)

        # Check if jobs table exists
        if 'jobs' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('jobs')]

            # Migration: Add merged_csv_output column
            if 'merged_csv_output' not in columns:
                logger.info("Adding merged_csv_output column to jobs table...")
                db.execute(text('ALTER TABLE jobs ADD COLUMN merged_csv_output TEXT'))
                db.commit()
                logger.info("Migration: merged_csv_output column added")

            # Migration: Add model_name column
            if 'model_name' not in columns:
                logger.info("Adding model_name column to jobs table...")
                db.execute(text('ALTER TABLE jobs ADD COLUMN model_name TEXT'))
                db.commit()
                logger.info("Migration: model_name column added")

        # Check if workflow_jobs table exists
        if 'workflow_jobs' in inspector.get_table_names():
            wf_columns = [col['name'] for col in inspector.get_columns('workflow_jobs')]

            # Migration: Add merged_csv_output column to workflow_jobs
            if 'merged_csv_output' not in wf_columns:
                logger.info("Adding merged_csv_output column to workflow_jobs table...")
                db.execute(text('ALTER TABLE workflow_jobs ADD COLUMN merged_csv_output TEXT'))
                db.commit()
                logger.info("Migration: workflow_jobs.merged_csv_output column added")

        # Migration: Add soft delete columns to projects table
        if 'projects' in inspector.get_table_names():
            proj_columns = [col['name'] for col in inspector.get_columns('projects')]

            if 'is_deleted' not in proj_columns:
                logger.info("Adding is_deleted column to projects table...")
                db.execute(text('ALTER TABLE projects ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0'))
                db.commit()
                logger.info("Migration: projects.is_deleted column added")

            if 'deleted_at' not in proj_columns:
                logger.info("Adding deleted_at column to projects table...")
                db.execute(text('ALTER TABLE projects ADD COLUMN deleted_at TEXT'))
                db.commit()
                logger.info("Migration: projects.deleted_at column added")

        # Migration: Add soft delete columns to workflows table
        if 'workflows' in inspector.get_table_names():
            wflow_columns = [col['name'] for col in inspector.get_columns('workflows')]

            if 'is_deleted' not in wflow_columns:
                logger.info("Adding is_deleted column to workflows table...")
                db.execute(text('ALTER TABLE workflows ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0'))
                db.commit()
                logger.info("Migration: workflows.is_deleted column added")

            if 'deleted_at' not in wflow_columns:
                logger.info("Adding deleted_at column to workflows table...")
                db.execute(text('ALTER TABLE workflows ADD COLUMN deleted_at TEXT'))
                db.commit()
                logger.info("Migration: workflows.deleted_at column added")

    except Exception as e:
        db.rollback()
        logger.warning(f"Migration warning: {str(e)}")
    finally:
        db.close()


def init_db():
    """Initialize database: create all tables and default data.

    For Phase 1 (MVP), creates:
    - All tables
    - Default project (ID=1, fixed for Phase 1)
    - Initial project revision
    - Default "ALL" tag for access control

    Based on specification: docs/req.txt section 8 (Phase 1 要件)
    """
    # Create all tables
    Base.metadata.create_all(bind=engine)

    # Apply migrations
    migrate_db()

    # Create default project for Phase 1 (1 project fixed)
    db = SessionLocal()
    try:
        # Check if default project exists
        default_project = db.query(Project).filter(Project.id == 1).first()

        if not default_project:
            # Create default project
            default_project = Project(
                id=1,
                name="Default Project",
                description="Phase 1 固定プロジェクト / Phase 1 Fixed Project"
            )
            db.add(default_project)
            db.commit()
            db.refresh(default_project)

            # Create initial revision with sample prompt template (legacy table)
            initial_revision = ProjectRevision(
                project_id=default_project.id,
                revision=1,
                prompt_template=(
                    "以下の情報に基づいて回答してください。\n\n"
                    "質問: {{question:TEXT5}}\n"
                    "コンテキスト: {{context:TEXT10}}\n"
                ),
                parser_config="{}"  # Empty for Phase 1
            )
            db.add(initial_revision)
            db.commit()

            # Create sample prompt in new Prompt table
            sample_prompt = Prompt(
                name="Sample Prompt",
                project_id=default_project.id,
                is_deleted=0
            )
            db.add(sample_prompt)
            db.commit()
            db.refresh(sample_prompt)

            # Create initial revision for the sample prompt
            sample_revision = PromptRevision(
                prompt_id=sample_prompt.id,
                revision=1,
                prompt_template=(
                    "以下の情報に基づいて回答してください。\n\n"
                    "質問: {{question:TEXT5}}\n"
                    "コンテキスト: {{context:TEXT10}}\n"
                ),
                parser_config="{}"
            )
            db.add(sample_revision)
            db.commit()

            logger.info(f"Created default project (ID={default_project.id})")
            logger.info(f"Created initial revision (ID={initial_revision.id})")
            logger.info(f"Created sample prompt (ID={sample_prompt.id}) with revision")
        else:
            logger.info(f"Default project already exists (ID={default_project.id})")

            # Check if Default Project has any prompts (migration for existing DBs)
            existing_prompt = db.query(Prompt).filter(
                Prompt.project_id == default_project.id,
                Prompt.is_deleted == 0
            ).first()
            if not existing_prompt:
                # Create sample prompt for existing Default Project
                sample_prompt = Prompt(
                    name="Sample Prompt",
                    project_id=default_project.id,
                    is_deleted=0
                )
                db.add(sample_prompt)
                db.commit()
                db.refresh(sample_prompt)

                # Create initial revision
                sample_revision = PromptRevision(
                    prompt_id=sample_prompt.id,
                    revision=1,
                    prompt_template=(
                        "以下の情報に基づいて回答してください。\n\n"
                        "質問: {{question:TEXT5}}\n"
                        "コンテキスト: {{context:TEXT10}}\n"
                    ),
                    parser_config="{}"
                )
                db.add(sample_revision)
                db.commit()
                logger.info(f"Created sample prompt for existing Default Project (ID={sample_prompt.id})")

        # Initialize default "ALL" tag for access control
        init_default_tags(db)

    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def init_default_tags(db: Session):
    """Initialize default tags for access control system.

    Creates:
    - "ALL" tag: Default tag for all prompts (system tag, cannot be deleted)

    All LLM models have "ALL" in their allowed tags by default.
    """
    # Check if "ALL" tag exists
    all_tag = db.query(Tag).filter(Tag.name == "ALL").first()

    if not all_tag:
        all_tag = Tag(
            name="ALL",
            color="#22c55e",  # Green color
            description="デフォルトタグ - すべてのモデルで実行可能 / Default tag - executable on all models",
            is_system=1  # System tag, cannot be deleted
        )
        db.add(all_tag)
        db.commit()
        logger.info("Created default 'ALL' tag")
    else:
        logger.info("Default 'ALL' tag already exists")

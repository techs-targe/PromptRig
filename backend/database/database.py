"""Database connection and session management.

Based on specification in docs/req.txt section 2.3 and 3.1
"""

import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

from .models import Base, Project, ProjectRevision

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
                print("⚙ Adding merged_csv_output column to jobs table...")
                db.execute(text('ALTER TABLE jobs ADD COLUMN merged_csv_output TEXT'))
                db.commit()
                print("✓ Migration: merged_csv_output column added")

            # Migration: Add model_name column
            if 'model_name' not in columns:
                print("⚙ Adding model_name column to jobs table...")
                db.execute(text('ALTER TABLE jobs ADD COLUMN model_name TEXT'))
                db.commit()
                print("✓ Migration: model_name column added")

    except Exception as e:
        db.rollback()
        print(f"⚠ Migration warning: {str(e)}")
    finally:
        db.close()


def init_db():
    """Initialize database: create all tables and default data.

    For Phase 1 (MVP), creates:
    - All tables
    - Default project (ID=1, fixed for Phase 1)
    - Initial project revision

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

            # Create initial revision with sample prompt template
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

            print(f"✓ Created default project (ID={default_project.id})")
            print(f"✓ Created initial revision (ID={initial_revision.id})")
        else:
            print(f"✓ Default project already exists (ID={default_project.id})")

    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

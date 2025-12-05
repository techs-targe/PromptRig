"""Test database initialization and basic operations.

Based on specification in docs/req.txt section 5 (DB設計)
"""

import os
import sys
from pathlib import Path

# Set test database path
os.environ["DATABASE_PATH"] = "test_app.db"

from backend.database import init_db, SessionLocal, Project, ProjectRevision


def test_database_init():
    """Test database initialization."""
    print("Testing database initialization...")

    # Remove test database if exists
    test_db = Path("test_app.db")
    if test_db.exists():
        test_db.unlink()

    # Initialize database
    init_db()

    # Verify tables were created and default data exists
    db = SessionLocal()
    try:
        # Check default project exists
        project = db.query(Project).filter(Project.id == 1).first()
        assert project is not None, "Default project not created"
        assert project.name == "Default Project"
        print(f"✓ Default project created: {project.name}")

        # Check initial revision exists
        revision = db.query(ProjectRevision).filter(
            ProjectRevision.project_id == 1,
            ProjectRevision.revision == 1
        ).first()
        assert revision is not None, "Initial revision not created"
        assert "{{" in revision.prompt_template, "Prompt template missing {{}} syntax"
        print(f"✓ Initial revision created (revision={revision.revision})")
        print(f"✓ Prompt template contains {{}} syntax")

        # Verify prompt template structure
        from backend.prompt import PromptTemplateParser
        parser = PromptTemplateParser()
        params = parser.parse_template(revision.prompt_template)
        print(f"✓ Template has {len(params)} parameters: {[p.name for p in params]}")

    finally:
        db.close()

    print("✓ Database initialization test passed")


def test_job_creation():
    """Test job creation without execution."""
    print("\nTesting job creation...")

    from backend.job import JobManager

    db = SessionLocal()
    try:
        job_manager = JobManager(db)

        # Get project revision
        revision = db.query(ProjectRevision).filter(
            ProjectRevision.project_id == 1
        ).first()

        # Create a job
        job = job_manager.create_single_job(
            project_revision_id=revision.id,
            input_params={
                "question": "What is Python?",
                "context": "Python is a programming language."
            },
            repeat=3
        )

        assert job.id is not None, "Job ID not assigned"
        assert job.job_type == "single", "Job type incorrect"
        assert job.status == "pending", "Job status should be pending"
        assert len(job.job_items) == 3, "Should have 3 job items"

        print(f"✓ Job created (ID={job.id}) with {len(job.job_items)} items")

        # Verify job items have correct prompt
        for i, item in enumerate(job.job_items):
            assert "What is Python?" in item.raw_prompt, "Parameter not substituted"
            assert "{{" not in item.raw_prompt, "Template not fully substituted"
            print(f"✓ Job item {i+1}: prompt substituted correctly")

    finally:
        db.close()

    print("✓ Job creation test passed")


def cleanup():
    """Clean up test database."""
    test_db = Path("test_app.db")
    if test_db.exists():
        test_db.unlink()
    print("\n✓ Test database cleaned up")


if __name__ == "__main__":
    print("Running database tests...")
    print("=" * 60)

    try:
        test_database_init()
        test_job_creation()
        print("=" * 60)
        print("✅ All database tests passed!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cleanup()

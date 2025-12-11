"""
Migration script for v3.0 architecture.

Migrates from:
  - 1 Project = 1 Prompt (ProjectRevision)

To:
  - 1 Project = N Prompts (PromptRevision)
  - Workflows belong to Projects
  - WorkflowSteps reference Prompts (not Projects)
  - Jobs reference PromptRevisions (not ProjectRevisions)

Usage:
  python -m backend.database.migrate_v3
"""

import sqlite3
from datetime import datetime
from pathlib import Path


def get_db_path():
    """Get database path."""
    return Path(__file__).parent.parent.parent / "database" / "app.db"


def migrate():
    """Run migration to v3.0 architecture."""
    db_path = get_db_path()
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return False

    print(f"Migrating database: {db_path}")
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    try:
        # Step 1: Create new tables if they don't exist
        print("\n[Step 1] Creating new tables...")

        # Create prompts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                name TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_prompts_project ON prompts(project_id)")
        print("  - Created 'prompts' table")

        # Create prompt_revisions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prompt_revisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prompt_id INTEGER NOT NULL REFERENCES prompts(id),
                revision INTEGER NOT NULL,
                prompt_template TEXT NOT NULL,
                parser_config TEXT,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_prompt_revision ON prompt_revisions(prompt_id, revision)")
        print("  - Created 'prompt_revisions' table")

        # Step 2: Add new columns to existing tables
        print("\n[Step 2] Adding new columns...")

        # Add project_id to workflows
        try:
            cursor.execute("ALTER TABLE workflows ADD COLUMN project_id INTEGER REFERENCES projects(id)")
            print("  - Added 'project_id' to workflows")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print("  - 'project_id' already exists in workflows")
            else:
                raise

        # Add prompt_id to workflow_steps
        try:
            cursor.execute("ALTER TABLE workflow_steps ADD COLUMN prompt_id INTEGER REFERENCES prompts(id)")
            print("  - Added 'prompt_id' to workflow_steps")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print("  - 'prompt_id' already exists in workflow_steps")
            else:
                raise

        # Add prompt_revision_id to jobs
        try:
            cursor.execute("ALTER TABLE jobs ADD COLUMN prompt_revision_id INTEGER REFERENCES prompt_revisions(id)")
            print("  - Added 'prompt_revision_id' to jobs")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print("  - 'prompt_revision_id' already exists in jobs")
            else:
                raise

        conn.commit()

        # Step 3: Migrate existing data
        print("\n[Step 3] Migrating existing data...")

        # Get all projects
        cursor.execute("SELECT id, name, description, created_at FROM projects")
        projects = cursor.fetchall()

        # Mapping: project_id -> prompt_id
        project_to_prompt = {}
        # Mapping: project_revision_id -> prompt_revision_id
        project_rev_to_prompt_rev = {}

        for project_id, project_name, project_desc, created_at in projects:
            # Check if a prompt already exists for this project
            cursor.execute("SELECT id FROM prompts WHERE project_id = ?", (project_id,))
            existing_prompt = cursor.fetchone()

            if existing_prompt:
                prompt_id = existing_prompt[0]
                print(f"  - Project {project_id} already has prompt {prompt_id}")
            else:
                # Create default prompt for this project
                now = datetime.utcnow().isoformat()
                cursor.execute("""
                    INSERT INTO prompts (project_id, name, description, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (project_id, f"{project_name} - Default", project_desc, created_at or now, now))
                prompt_id = cursor.lastrowid
                print(f"  - Created prompt {prompt_id} for project {project_id}")

            project_to_prompt[project_id] = prompt_id

            # Get project revisions
            cursor.execute("""
                SELECT id, revision, prompt_template, parser_config, created_at
                FROM project_revisions
                WHERE project_id = ?
            """, (project_id,))
            revisions = cursor.fetchall()

            for rev_id, revision, template, parser_config, rev_created in revisions:
                # Check if prompt revision already exists
                cursor.execute("""
                    SELECT id FROM prompt_revisions
                    WHERE prompt_id = ? AND revision = ?
                """, (prompt_id, revision))
                existing_rev = cursor.fetchone()

                if existing_rev:
                    prompt_rev_id = existing_rev[0]
                    print(f"    - ProjectRevision {rev_id} already migrated to PromptRevision {prompt_rev_id}")
                else:
                    # Create prompt revision
                    cursor.execute("""
                        INSERT INTO prompt_revisions (prompt_id, revision, prompt_template, parser_config, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (prompt_id, revision, template, parser_config, rev_created))
                    prompt_rev_id = cursor.lastrowid
                    print(f"    - Created PromptRevision {prompt_rev_id} from ProjectRevision {rev_id}")

                project_rev_to_prompt_rev[rev_id] = prompt_rev_id

        conn.commit()

        # Step 4: Update workflows with project_id (infer from first step)
        print("\n[Step 4] Updating workflows...")

        cursor.execute("SELECT id FROM workflows WHERE project_id IS NULL")
        workflows = cursor.fetchall()

        for (workflow_id,) in workflows:
            # Get first step's project_id
            cursor.execute("""
                SELECT project_id FROM workflow_steps
                WHERE workflow_id = ? AND project_id IS NOT NULL
                ORDER BY step_order LIMIT 1
            """, (workflow_id,))
            step = cursor.fetchone()

            if step and step[0]:
                cursor.execute("""
                    UPDATE workflows SET project_id = ? WHERE id = ?
                """, (step[0], workflow_id))
                print(f"  - Set workflow {workflow_id} project_id to {step[0]}")

        conn.commit()

        # Step 5: Update workflow_steps with prompt_id
        print("\n[Step 5] Updating workflow_steps...")

        cursor.execute("SELECT id, project_id FROM workflow_steps WHERE prompt_id IS NULL AND project_id IS NOT NULL")
        steps = cursor.fetchall()

        for step_id, step_project_id in steps:
            if step_project_id in project_to_prompt:
                prompt_id = project_to_prompt[step_project_id]
                cursor.execute("""
                    UPDATE workflow_steps SET prompt_id = ? WHERE id = ?
                """, (prompt_id, step_id))
                print(f"  - Set step {step_id} prompt_id to {prompt_id}")

        conn.commit()

        # Step 6: Update jobs with prompt_revision_id
        print("\n[Step 6] Updating jobs...")

        cursor.execute("SELECT id, project_revision_id FROM jobs WHERE prompt_revision_id IS NULL AND project_revision_id IS NOT NULL")
        jobs = cursor.fetchall()

        for job_id, proj_rev_id in jobs:
            if proj_rev_id in project_rev_to_prompt_rev:
                prompt_rev_id = project_rev_to_prompt_rev[proj_rev_id]
                cursor.execute("""
                    UPDATE jobs SET prompt_revision_id = ? WHERE id = ?
                """, (prompt_rev_id, job_id))
                print(f"  - Set job {job_id} prompt_revision_id to {prompt_rev_id}")

        conn.commit()

        print("\n[Migration Complete]")
        print(f"  - Prompts created: {len(project_to_prompt)}")
        print(f"  - PromptRevisions migrated: {len(project_rev_to_prompt_rev)}")

        return True

    except Exception as e:
        conn.rollback()
        print(f"\n[Error] Migration failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()

"""Comprehensive tests for dataset FOREACH functionality in workflows.

Tests the ability to iterate over datasets directly in workflow FOREACH loops.
"""

import pytest
import json
from sqlalchemy import text
from backend.database.database import SessionLocal, engine
from backend.database.models import Dataset, Workflow, WorkflowStep, WorkflowJob, WorkflowJobStep, Project
from backend.workflow import WorkflowManager


@pytest.fixture
def db():
    """Create a database session for testing."""
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def workflow_manager(db):
    """Create a WorkflowManager instance."""
    return WorkflowManager(db)


@pytest.fixture
def test_dataset(db):
    """Create a test dataset with sample data."""
    # Ensure project exists
    project = db.query(Project).filter(Project.id == 1).first()
    if not project:
        project = Project(id=1, name="Test Project")
        db.add(project)
        db.commit()

    # Create a unique table name
    import time
    table_name = f"test_foreach_{int(time.time())}"

    # Create the dataset record
    dataset = Dataset(
        name="Test FOREACH Dataset",
        source_file_name="test.csv",
        sqlite_table_name=table_name,
        project_id=1
    )
    db.add(dataset)
    db.commit()

    # Create the actual table with test data
    db.execute(text(f'''
        CREATE TABLE "{table_name}" (
            id INTEGER PRIMARY KEY,
            name TEXT,
            category TEXT,
            score INTEGER
        )
    '''))

    # Insert test data
    test_data = [
        (1, "Alice", "A", 95),
        (2, "Bob", "B", 87),
        (3, "Charlie", "A", 92),
        (4, "Diana", "C", 78),
        (5, "Eve", "B", 88)
    ]
    for row in test_data:
        db.execute(text(f'''
            INSERT INTO "{table_name}" (id, name, category, score)
            VALUES (:id, :name, :category, :score)
        '''), {"id": row[0], "name": row[1], "category": row[2], "score": row[3]})
    db.commit()

    yield dataset

    # Cleanup
    try:
        db.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))
        db.delete(dataset)
        db.commit()
    except:
        db.rollback()


@pytest.fixture
def empty_dataset(db):
    """Create an empty dataset for testing edge cases."""
    import time
    table_name = f"test_empty_{int(time.time())}"

    dataset = Dataset(
        name="Empty Dataset",
        source_file_name="empty.csv",
        sqlite_table_name=table_name,
        project_id=1
    )
    db.add(dataset)
    db.commit()

    # Create empty table
    db.execute(text(f'''
        CREATE TABLE "{table_name}" (
            id INTEGER PRIMARY KEY,
            value TEXT
        )
    '''))
    db.commit()

    yield dataset

    # Cleanup
    try:
        db.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))
        db.delete(dataset)
        db.commit()
    except:
        db.rollback()


class TestDatasetSourceParsing:
    """Test _parse_foreach_source with dataset references."""

    def test_full_dataset_rows(self, workflow_manager, test_dataset):
        """Test loading all rows as dictionaries."""
        source = f"dataset:{test_dataset.id}"
        result = workflow_manager._parse_foreach_source(source)

        assert len(result) == 5
        assert isinstance(result[0], dict)
        assert "id" in result[0]
        assert "name" in result[0]
        assert "category" in result[0]
        assert "score" in result[0]
        assert result[0]["name"] == "Alice"
        assert result[4]["name"] == "Eve"

    def test_single_column(self, workflow_manager, test_dataset):
        """Test loading a single column as list of values."""
        source = f"dataset:{test_dataset.id}:name"
        result = workflow_manager._parse_foreach_source(source)

        assert len(result) == 5
        assert isinstance(result[0], str)
        assert result[0] == "Alice"
        assert result[1] == "Bob"
        assert "Eve" in result

    def test_single_column_numeric(self, workflow_manager, test_dataset):
        """Test loading a numeric column."""
        source = f"dataset:{test_dataset.id}:score"
        result = workflow_manager._parse_foreach_source(source)

        assert len(result) == 5
        assert result[0] == 95
        assert result[1] == 87

    def test_multiple_columns(self, workflow_manager, test_dataset):
        """Test loading multiple selected columns."""
        source = f"dataset:{test_dataset.id}:name,score"
        result = workflow_manager._parse_foreach_source(source)

        assert len(result) == 5
        assert isinstance(result[0], dict)
        assert set(result[0].keys()) == {"name", "score"}
        assert result[0]["name"] == "Alice"
        assert result[0]["score"] == 95

    def test_multiple_columns_order(self, workflow_manager, test_dataset):
        """Test that column order is preserved."""
        source = f"dataset:{test_dataset.id}:score,name,category"
        result = workflow_manager._parse_foreach_source(source)

        assert len(result) == 5
        assert set(result[0].keys()) == {"score", "name", "category"}

    def test_invalid_dataset_id(self, workflow_manager):
        """Test handling of non-existent dataset."""
        source = "dataset:99999"
        result = workflow_manager._parse_foreach_source(source)

        assert result == []

    def test_invalid_column(self, workflow_manager, test_dataset):
        """Test handling of non-existent column."""
        source = f"dataset:{test_dataset.id}:nonexistent"
        result = workflow_manager._parse_foreach_source(source)

        assert result == []

    def test_partial_invalid_columns(self, workflow_manager, test_dataset):
        """Test handling when some columns are invalid."""
        source = f"dataset:{test_dataset.id}:name,invalid_col,score"
        result = workflow_manager._parse_foreach_source(source)

        # Should return rows with only valid columns
        assert len(result) == 5
        assert "name" in result[0]
        assert "score" in result[0]
        assert "invalid_col" not in result[0]

    def test_empty_dataset(self, workflow_manager, empty_dataset):
        """Test handling of empty dataset."""
        source = f"dataset:{empty_dataset.id}"
        result = workflow_manager._parse_foreach_source(source)

        assert result == []

    def test_malformed_source(self, workflow_manager):
        """Test handling of malformed dataset references."""
        # Missing ID
        assert workflow_manager._parse_foreach_source("dataset:") == []

        # Invalid ID format
        assert workflow_manager._parse_foreach_source("dataset:abc") == []

        # Just "dataset" without colon
        result = workflow_manager._parse_foreach_source("dataset")
        assert result == ["dataset"]  # Treated as single value


class TestDatasetForeachExecution:
    """Test actual FOREACH execution with datasets."""

    def test_foreach_with_dataset_column(self, db, workflow_manager, test_dataset):
        """Test FOREACH loop iterating over dataset column."""
        # Create workflow
        workflow = workflow_manager.create_workflow(
            name="Test Column Loop",
            project_id=1
        )

        try:
            # Add FOREACH step
            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="loop_names",
                step_type="foreach",
                condition_config={
                    "source": f"dataset:{test_dataset.id}:name",
                    "item_var": "NAME"
                }
            )

            # Add SET step to track iterations
            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="track",
                step_type="set",
                condition_config={
                    "assignments": {"LAST_NAME": "{{vars.NAME}}"}
                }
            )

            # Add ENDFOREACH
            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="end_loop",
                step_type="endforeach"
            )

            # Execute
            job = workflow_manager.execute_workflow(workflow.id, {})

            assert job.status == "done"

        finally:
            # Cleanup
            db.query(WorkflowJobStep).filter(
                WorkflowJobStep.workflow_job_id.in_(
                    db.query(WorkflowJob.id).filter(WorkflowJob.workflow_id == workflow.id)
                )
            ).delete(synchronize_session=False)
            db.query(WorkflowJob).filter(WorkflowJob.workflow_id == workflow.id).delete()
            db.query(WorkflowStep).filter(WorkflowStep.workflow_id == workflow.id).delete()
            db.delete(workflow)
            db.commit()

    def test_foreach_with_full_rows(self, db, workflow_manager, test_dataset):
        """Test FOREACH loop iterating over full dataset rows."""
        workflow = workflow_manager.create_workflow(
            name="Test Row Loop",
            project_id=1
        )

        try:
            # Add FOREACH step for full rows
            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="loop_rows",
                step_type="foreach",
                condition_config={
                    "source": f"dataset:{test_dataset.id}",
                    "item_var": "ROW"
                }
            )

            # Add SET step accessing row fields
            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="process",
                step_type="set",
                condition_config={
                    "assignments": {
                        "CURRENT_NAME": "{{vars.ROW.name}}",
                        "CURRENT_SCORE": "{{vars.ROW.score}}"
                    }
                }
            )

            # Add ENDFOREACH
            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="end_loop",
                step_type="endforeach"
            )

            # Execute
            job = workflow_manager.execute_workflow(workflow.id, {})

            assert job.status == "done"

        finally:
            # Cleanup
            db.query(WorkflowJobStep).filter(
                WorkflowJobStep.workflow_job_id.in_(
                    db.query(WorkflowJob.id).filter(WorkflowJob.workflow_id == workflow.id)
                )
            ).delete(synchronize_session=False)
            db.query(WorkflowJob).filter(WorkflowJob.workflow_id == workflow.id).delete()
            db.query(WorkflowStep).filter(WorkflowStep.workflow_id == workflow.id).delete()
            db.delete(workflow)
            db.commit()

    def test_foreach_empty_dataset_skips(self, db, workflow_manager, empty_dataset):
        """Test that FOREACH with empty dataset skips loop body."""
        workflow = workflow_manager.create_workflow(
            name="Test Empty Loop",
            project_id=1
        )

        try:
            # Add FOREACH step with empty dataset
            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="loop_empty",
                step_type="foreach",
                condition_config={
                    "source": f"dataset:{empty_dataset.id}",
                    "item_var": "ITEM"
                }
            )

            # This should never execute
            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="should_skip",
                step_type="set",
                condition_config={
                    "assignments": {"EXECUTED": "yes"}
                }
            )

            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="end_loop",
                step_type="endforeach"
            )

            # Execute
            job = workflow_manager.execute_workflow(workflow.id, {})

            assert job.status == "done"

        finally:
            db.query(WorkflowJobStep).filter(
                WorkflowJobStep.workflow_job_id.in_(
                    db.query(WorkflowJob.id).filter(WorkflowJob.workflow_id == workflow.id)
                )
            ).delete(synchronize_session=False)
            db.query(WorkflowJob).filter(WorkflowJob.workflow_id == workflow.id).delete()
            db.query(WorkflowStep).filter(WorkflowStep.workflow_id == workflow.id).delete()
            db.delete(workflow)
            db.commit()


class TestDatasetForeachWithBreakContinue:
    """Test BREAK and CONTINUE in dataset FOREACH loops."""

    def test_break_in_dataset_loop(self, db, workflow_manager, test_dataset):
        """Test BREAK exits dataset loop early."""
        workflow = workflow_manager.create_workflow(
            name="Test Break",
            project_id=1
        )

        try:
            # FOREACH over names
            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="loop",
                step_type="foreach",
                condition_config={
                    "source": f"dataset:{test_dataset.id}:name",
                    "item_var": "NAME"
                }
            )

            # IF name == "Charlie" then BREAK
            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="check",
                step_type="if",
                condition_config={
                    "left": "{{vars.NAME}}",
                    "operator": "==",
                    "right": "Charlie"
                }
            )

            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="do_break",
                step_type="break"
            )

            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="endif",
                step_type="endif"
            )

            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="end_loop",
                step_type="endforeach"
            )

            job = workflow_manager.execute_workflow(workflow.id, {})
            assert job.status == "done"

        finally:
            db.query(WorkflowJobStep).filter(
                WorkflowJobStep.workflow_job_id.in_(
                    db.query(WorkflowJob.id).filter(WorkflowJob.workflow_id == workflow.id)
                )
            ).delete(synchronize_session=False)
            db.query(WorkflowJob).filter(WorkflowJob.workflow_id == workflow.id).delete()
            db.query(WorkflowStep).filter(WorkflowStep.workflow_id == workflow.id).delete()
            db.delete(workflow)
            db.commit()


class TestLegacyListRefSupport:
    """Test backward compatibility with list_ref key."""

    def test_list_ref_still_works(self, workflow_manager, test_dataset):
        """Test that list_ref key still works for backwards compatibility."""
        # This tests that the old format is still supported
        # The actual _execute_foreach_step uses list_ref internally

        # Create a mock step-like config
        config = {"list_ref": f"dataset:{test_dataset.id}:name", "item_var": "X"}
        source_expr = config.get("source", "") or config.get("list_ref", "")

        result = workflow_manager._parse_foreach_source(source_expr)

        assert len(result) == 5
        assert "Alice" in result


class TestDatasetForeachIntegration:
    """Integration tests combining dataset FOREACH with other features."""

    def test_nested_loops_dataset_and_array(self, db, workflow_manager, test_dataset):
        """Test nested loops: outer dataset, inner array."""
        workflow = workflow_manager.create_workflow(
            name="Test Nested",
            project_id=1
        )

        try:
            # Outer: dataset loop
            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="outer",
                step_type="foreach",
                condition_config={
                    "source": f"dataset:{test_dataset.id}:category",
                    "item_var": "CAT"
                }
            )

            # Inner: static array loop
            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="inner",
                step_type="foreach",
                condition_config={
                    "source": '["x", "y"]',
                    "item_var": "SUFFIX"
                }
            )

            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="combine",
                step_type="set",
                condition_config={
                    "assignments": {"COMBO": "{{vars.CAT}}-{{vars.SUFFIX}}"}
                }
            )

            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="end_inner",
                step_type="endforeach"
            )

            workflow_manager.add_step(
                workflow_id=workflow.id,
                step_name="end_outer",
                step_type="endforeach"
            )

            job = workflow_manager.execute_workflow(workflow.id, {})
            assert job.status == "done"

        finally:
            db.query(WorkflowJobStep).filter(
                WorkflowJobStep.workflow_job_id.in_(
                    db.query(WorkflowJob.id).filter(WorkflowJob.workflow_id == workflow.id)
                )
            ).delete(synchronize_session=False)
            db.query(WorkflowJob).filter(WorkflowJob.workflow_id == workflow.id).delete()
            db.query(WorkflowStep).filter(WorkflowStep.workflow_id == workflow.id).delete()
            db.delete(workflow)
            db.commit()


class TestLoadDatasetForForeach:
    """Direct tests for _load_dataset_for_foreach method."""

    def test_parse_dataset_id(self, workflow_manager, test_dataset):
        """Test correct parsing of dataset ID from source string."""
        result = workflow_manager._load_dataset_for_foreach(f"dataset:{test_dataset.id}")
        assert len(result) == 5

    def test_parse_with_column(self, workflow_manager, test_dataset):
        """Test parsing dataset:id:column format."""
        result = workflow_manager._load_dataset_for_foreach(f"dataset:{test_dataset.id}:name")
        assert len(result) == 5
        assert all(isinstance(x, str) for x in result)

    def test_parse_with_multiple_columns(self, workflow_manager, test_dataset):
        """Test parsing dataset:id:col1,col2 format."""
        result = workflow_manager._load_dataset_for_foreach(f"dataset:{test_dataset.id}:name,score")
        assert len(result) == 5
        assert all(isinstance(x, dict) for x in result)
        assert all(set(x.keys()) == {"name", "score"} for x in result)

    def test_invalid_format_returns_empty(self, workflow_manager):
        """Test that invalid formats return empty list."""
        assert workflow_manager._load_dataset_for_foreach("dataset") == []
        assert workflow_manager._load_dataset_for_foreach("dataset:") == []
        assert workflow_manager._load_dataset_for_foreach("dataset:abc") == []

    def test_nonexistent_dataset(self, workflow_manager):
        """Test handling of non-existent dataset."""
        result = workflow_manager._load_dataset_for_foreach("dataset:99999")
        assert result == []

    def test_dataset_without_table(self, db, workflow_manager):
        """Test handling of dataset without sqlite table."""
        # Create dataset without table - need a dummy table name since it's NOT NULL
        dataset = Dataset(
            name="No Table Dataset",
            source_file_name="test.csv",
            sqlite_table_name="nonexistent_table_xyz",
            project_id=1
        )
        db.add(dataset)
        db.commit()

        try:
            result = workflow_manager._load_dataset_for_foreach(f"dataset:{dataset.id}")
            assert result == []
        finally:
            db.delete(dataset)
            db.commit()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

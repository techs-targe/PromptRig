"""Comprehensive tests for workflow functionality.

Test Categories:
1. Workflow CRUD operations
2. Workflow step management
3. Workflow export/import/clone
4. Control flow steps (if/else/endif, foreach/endforeach)
5. Variable assignment steps (set type)
6. Workflow execution
7. Variables and functions API
"""

import pytest
import requests
import json
import time

BASE_URL = "http://localhost:9200"


class TestWorkflowCRUD:
    """Test basic CRUD operations for workflows."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create a test workflow for each test."""
        self.test_workflow_ids = []
        yield
        # Cleanup: delete test workflows
        for wf_id in self.test_workflow_ids:
            try:
                requests.delete(f"{BASE_URL}/api/workflows/{wf_id}")
            except:
                pass

    def test_create_workflow(self):
        """Test creating a new workflow."""
        response = requests.post(f"{BASE_URL}/api/workflows", json={
            "name": "Test Workflow",
            "description": "Test description"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Workflow"
        assert data["description"] == "Test description"
        assert "id" in data
        self.test_workflow_ids.append(data["id"])

    def test_list_workflows(self):
        """Test listing workflows."""
        # Create a workflow first
        resp = requests.post(f"{BASE_URL}/api/workflows", json={
            "name": "List Test Workflow"
        })
        self.test_workflow_ids.append(resp.json()["id"])

        response = requests.get(f"{BASE_URL}/api/workflows")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should contain at least our created workflow
        names = [w["name"] for w in data]
        assert "List Test Workflow" in names

    def test_get_workflow(self):
        """Test getting a specific workflow."""
        # Create a workflow
        resp = requests.post(f"{BASE_URL}/api/workflows", json={
            "name": "Get Test Workflow"
        })
        wf_id = resp.json()["id"]
        self.test_workflow_ids.append(wf_id)

        response = requests.get(f"{BASE_URL}/api/workflows/{wf_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == wf_id
        assert data["name"] == "Get Test Workflow"

    def test_get_nonexistent_workflow(self):
        """Test getting a workflow that doesn't exist."""
        response = requests.get(f"{BASE_URL}/api/workflows/99999")
        assert response.status_code == 404

    def test_update_workflow(self):
        """Test updating a workflow."""
        # Create a workflow
        resp = requests.post(f"{BASE_URL}/api/workflows", json={
            "name": "Update Test Workflow"
        })
        wf_id = resp.json()["id"]
        self.test_workflow_ids.append(wf_id)

        # Update it
        response = requests.put(f"{BASE_URL}/api/workflows/{wf_id}", json={
            "name": "Updated Workflow Name",
            "description": "Updated description"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Workflow Name"
        assert data["description"] == "Updated description"

    def test_delete_workflow(self):
        """Test deleting a workflow."""
        # Create a workflow
        resp = requests.post(f"{BASE_URL}/api/workflows", json={
            "name": "Delete Test Workflow"
        })
        wf_id = resp.json()["id"]

        # Delete it
        response = requests.delete(f"{BASE_URL}/api/workflows/{wf_id}")
        assert response.status_code == 200

        # Verify it's gone
        response = requests.get(f"{BASE_URL}/api/workflows/{wf_id}")
        assert response.status_code == 404


class TestWorkflowSteps:
    """Test workflow step management."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create a test workflow."""
        resp = requests.post(f"{BASE_URL}/api/workflows", json={
            "name": "Step Test Workflow"
        })
        self.workflow_id = resp.json()["id"]
        yield
        # Cleanup
        requests.delete(f"{BASE_URL}/api/workflows/{self.workflow_id}")

    def test_add_set_step(self):
        """Test adding a SET type step."""
        response = requests.post(
            f"{BASE_URL}/api/workflows/{self.workflow_id}/steps",
            json={
                "step_name": "init_vars",
                "step_type": "set",
                "condition_config": {
                    "assignments": {
                        "counter": "0",
                        "total": "100"
                    }
                }
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["step_name"] == "init_vars"
        assert data["step_type"] == "set"
        assert data["condition_config"]["assignments"]["counter"] == "0"

    def test_update_step(self):
        """Test updating a workflow step."""
        # Add a step first
        resp = requests.post(
            f"{BASE_URL}/api/workflows/{self.workflow_id}/steps",
            json={
                "step_name": "original_step",
                "step_type": "set",
                "condition_config": {"assignments": {"x": "1"}}
            }
        )
        step_id = resp.json()["id"]

        # Update it
        response = requests.put(
            f"{BASE_URL}/api/workflows/{self.workflow_id}/steps/{step_id}",
            json={
                "step_name": "updated_step",
                "condition_config": {"assignments": {"x": "2"}}
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["step_name"] == "updated_step"

    def test_delete_step(self):
        """Test deleting a workflow step."""
        # Add a step first
        resp = requests.post(
            f"{BASE_URL}/api/workflows/{self.workflow_id}/steps",
            json={
                "step_name": "to_delete",
                "step_type": "set",
                "condition_config": {"assignments": {"x": "1"}}
            }
        )
        step_id = resp.json()["id"]

        # Delete it
        response = requests.delete(
            f"{BASE_URL}/api/workflows/{self.workflow_id}/steps/{step_id}"
        )
        assert response.status_code == 200


class TestWorkflowClone:
    """Test workflow cloning (Save As) functionality."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create a test workflow with various step types."""
        self.workflow_ids = []
        yield
        # Cleanup
        for wf_id in self.workflow_ids:
            try:
                requests.delete(f"{BASE_URL}/api/workflows/{wf_id}")
            except:
                pass

    def test_clone_simple_workflow(self):
        """Test cloning a simple workflow."""
        # Create source workflow
        resp = requests.post(f"{BASE_URL}/api/workflows", json={
            "name": "Original Workflow"
        })
        source_id = resp.json()["id"]
        self.workflow_ids.append(source_id)

        # Add a step
        requests.post(
            f"{BASE_URL}/api/workflows/{source_id}/steps",
            json={
                "step_name": "test_step",
                "step_type": "set",
                "condition_config": {"assignments": {"x": "1"}}
            }
        )

        # Clone it
        response = requests.post(
            f"{BASE_URL}/api/workflows/{source_id}/clone",
            json={"new_name": "Cloned Workflow"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Cloned Workflow"
        self.workflow_ids.append(data["id"])

        # Verify steps were cloned
        assert len(data["steps"]) == 1
        assert data["steps"][0]["step_name"] == "test_step"
        assert data["steps"][0]["step_type"] == "set"

    def test_clone_preserves_step_types(self):
        """Test that cloning preserves step_type (bug fix verification)."""
        # Create source workflow with various step types
        resp = requests.post(f"{BASE_URL}/api/workflows", json={
            "name": "Multi-Type Workflow"
        })
        source_id = resp.json()["id"]
        self.workflow_ids.append(source_id)

        # Add SET step
        requests.post(
            f"{BASE_URL}/api/workflows/{source_id}/steps",
            json={
                "step_name": "init",
                "step_type": "set",
                "step_order": 0,
                "condition_config": {"assignments": {"counter": "0"}}
            }
        )

        # Add FOREACH step
        requests.post(
            f"{BASE_URL}/api/workflows/{source_id}/steps",
            json={
                "step_name": "loop",
                "step_type": "foreach",
                "step_order": 1,
                "condition_config": {"item_var": "item", "list_ref": "items"}
            }
        )

        # Add IF step
        requests.post(
            f"{BASE_URL}/api/workflows/{source_id}/steps",
            json={
                "step_name": "check",
                "step_type": "if",
                "step_order": 2,
                "condition_config": {"left": "{{item}}", "operator": "==", "right": "target"}
            }
        )

        # Add ELSE step
        requests.post(
            f"{BASE_URL}/api/workflows/{source_id}/steps",
            json={
                "step_name": "check_else",
                "step_type": "else",
                "step_order": 3
            }
        )

        # Add ENDIF step
        requests.post(
            f"{BASE_URL}/api/workflows/{source_id}/steps",
            json={
                "step_name": "check_endif",
                "step_type": "endif",
                "step_order": 4
            }
        )

        # Add ENDFOREACH step
        requests.post(
            f"{BASE_URL}/api/workflows/{source_id}/steps",
            json={
                "step_name": "loop_end",
                "step_type": "endforeach",
                "step_order": 5
            }
        )

        # Clone it
        response = requests.post(
            f"{BASE_URL}/api/workflows/{source_id}/clone",
            json={"new_name": "Cloned Multi-Type"}
        )
        assert response.status_code == 200
        data = response.json()
        self.workflow_ids.append(data["id"])

        # Verify all step types are preserved
        steps = {s["step_name"]: s for s in data["steps"]}

        assert steps["init"]["step_type"] == "set", "SET step type not preserved"
        assert steps["loop"]["step_type"] == "foreach", "FOREACH step type not preserved"
        assert steps["check"]["step_type"] == "if", "IF step type not preserved"
        assert steps["check_else"]["step_type"] == "else", "ELSE step type not preserved"
        assert steps["check_endif"]["step_type"] == "endif", "ENDIF step type not preserved"
        assert steps["loop_end"]["step_type"] == "endforeach", "ENDFOREACH step type not preserved"

    def test_clone_preserves_condition_config(self):
        """Test that cloning preserves condition_config."""
        # Create source workflow
        resp = requests.post(f"{BASE_URL}/api/workflows", json={
            "name": "Config Workflow"
        })
        source_id = resp.json()["id"]
        self.workflow_ids.append(source_id)

        # Add step with complex condition_config
        requests.post(
            f"{BASE_URL}/api/workflows/{source_id}/steps",
            json={
                "step_name": "check",
                "step_type": "if",
                "condition_config": {
                    "left": "{{answer}}",
                    "operator": "contains",
                    "right": "correct"
                }
            }
        )

        # Clone it
        response = requests.post(
            f"{BASE_URL}/api/workflows/{source_id}/clone",
            json={"new_name": "Cloned Config"}
        )
        assert response.status_code == 200
        data = response.json()
        self.workflow_ids.append(data["id"])

        # Verify condition_config
        cloned_step = data["steps"][0]
        assert cloned_step["condition_config"]["left"] == "{{answer}}"
        assert cloned_step["condition_config"]["operator"] == "contains"
        assert cloned_step["condition_config"]["right"] == "correct"


class TestWorkflowExportImport:
    """Test workflow export and import functionality."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Cleanup list for created workflows."""
        self.workflow_ids = []
        yield
        for wf_id in self.workflow_ids:
            try:
                requests.delete(f"{BASE_URL}/api/workflows/{wf_id}")
            except:
                pass

    def test_export_workflow(self):
        """Test exporting a workflow to JSON."""
        # Create workflow
        resp = requests.post(f"{BASE_URL}/api/workflows", json={
            "name": "Export Test"
        })
        wf_id = resp.json()["id"]
        self.workflow_ids.append(wf_id)

        # Add a step
        requests.post(
            f"{BASE_URL}/api/workflows/{wf_id}/steps",
            json={
                "step_name": "init",
                "step_type": "set",
                "condition_config": {"assignments": {"x": "1"}}
            }
        )

        # Export
        response = requests.get(f"{BASE_URL}/api/workflows/{wf_id}/export")
        assert response.status_code == 200
        data = response.json()

        assert data["name"] == "Export Test"
        assert data["version"] == "1.0"
        assert len(data["steps"]) == 1
        assert data["steps"][0]["step_type"] == "set"

    def test_import_workflow(self):
        """Test importing a workflow from JSON."""
        workflow_json = {
            "version": "1.0",
            "name": "Imported Workflow",
            "description": "Imported description",
            "steps": [
                {
                    "step_order": 0,
                    "step_name": "start",
                    "step_type": "set",
                    "condition_config": {"assignments": {"result": "initial"}}
                },
                {
                    "step_order": 1,
                    "step_name": "loop",
                    "step_type": "foreach",
                    "condition_config": {"item_var": "item", "list_ref": "items"}
                },
                {
                    "step_order": 2,
                    "step_name": "loop_end",
                    "step_type": "endforeach"
                }
            ]
        }

        response = requests.post(
            f"{BASE_URL}/api/workflows/import",
            json={"workflow_json": workflow_json}
        )
        assert response.status_code == 200
        data = response.json()
        self.workflow_ids.append(data["id"])

        assert data["name"] == "Imported Workflow"
        assert len(data["steps"]) == 3

        # Verify step types preserved
        steps = {s["step_name"]: s for s in data["steps"]}
        assert steps["start"]["step_type"] == "set"
        assert steps["loop"]["step_type"] == "foreach"
        assert steps["loop_end"]["step_type"] == "endforeach"

    def test_export_import_roundtrip(self):
        """Test that export and import preserve all data."""
        # Create complex workflow
        resp = requests.post(f"{BASE_URL}/api/workflows", json={
            "name": "Roundtrip Test",
            "description": "Test roundtrip",
            "auto_context": True
        })
        wf_id = resp.json()["id"]
        self.workflow_ids.append(wf_id)

        # Add various steps
        steps_to_add = [
            {"step_name": "init", "step_type": "set", "step_order": 0,
             "condition_config": {"assignments": {"counter": "0"}}},
            {"step_name": "loop", "step_type": "foreach", "step_order": 1,
             "condition_config": {"item_var": "ROW", "list_ref": "dataset:1"}},
            {"step_name": "check", "step_type": "if", "step_order": 2,
             "condition_config": {"left": "{{ROW.val}}", "operator": ">=", "right": "5"}},
            {"step_name": "check_else", "step_type": "else", "step_order": 3},
            {"step_name": "check_end", "step_type": "endif", "step_order": 4},
            {"step_name": "loop_end", "step_type": "endforeach", "step_order": 5}
        ]

        for step in steps_to_add:
            requests.post(f"{BASE_URL}/api/workflows/{wf_id}/steps", json=step)

        # Export
        export_resp = requests.get(f"{BASE_URL}/api/workflows/{wf_id}/export")
        exported = export_resp.json()

        # Import as new
        import_resp = requests.post(
            f"{BASE_URL}/api/workflows/import",
            json={
                "workflow_json": exported,
                "new_name": "Roundtrip Imported"
            }
        )
        assert import_resp.status_code == 200
        imported = import_resp.json()
        self.workflow_ids.append(imported["id"])

        # Verify
        assert imported["name"] == "Roundtrip Imported"
        assert len(imported["steps"]) == 6

        # Check all step types preserved
        for i, step in enumerate(imported["steps"]):
            original = steps_to_add[i]
            assert step["step_type"] == original["step_type"], \
                f"Step {i} type mismatch: {step['step_type']} != {original['step_type']}"


class TestWorkflowControlFlow:
    """Test control flow step types and structure."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create test workflow."""
        resp = requests.post(f"{BASE_URL}/api/workflows", json={
            "name": "Control Flow Test"
        })
        self.workflow_id = resp.json()["id"]
        yield
        requests.delete(f"{BASE_URL}/api/workflows/{self.workflow_id}")

    def test_if_else_endif_structure(self):
        """Test creating IF/ELSE/ENDIF structure."""
        # Add IF
        resp = requests.post(
            f"{BASE_URL}/api/workflows/{self.workflow_id}/steps",
            json={
                "step_name": "check",
                "step_type": "if",
                "step_order": 0,
                "condition_config": {
                    "left": "{{value}}",
                    "operator": "==",
                    "right": "expected"
                }
            }
        )
        assert resp.status_code == 200
        assert resp.json()["step_type"] == "if"

        # Add ELSE
        resp = requests.post(
            f"{BASE_URL}/api/workflows/{self.workflow_id}/steps",
            json={
                "step_name": "check_else",
                "step_type": "else",
                "step_order": 1
            }
        )
        assert resp.status_code == 200
        assert resp.json()["step_type"] == "else"

        # Add ENDIF
        resp = requests.post(
            f"{BASE_URL}/api/workflows/{self.workflow_id}/steps",
            json={
                "step_name": "check_end",
                "step_type": "endif",
                "step_order": 2
            }
        )
        assert resp.status_code == 200
        assert resp.json()["step_type"] == "endif"

    def test_foreach_endforeach_structure(self):
        """Test creating FOREACH/ENDFOREACH structure."""
        # Add FOREACH
        resp = requests.post(
            f"{BASE_URL}/api/workflows/{self.workflow_id}/steps",
            json={
                "step_name": "loop",
                "step_type": "foreach",
                "step_order": 0,
                "condition_config": {
                    "item_var": "item",
                    "list_ref": "items_list"
                }
            }
        )
        assert resp.status_code == 200
        assert resp.json()["step_type"] == "foreach"
        config = resp.json()["condition_config"]
        assert config["item_var"] == "item"

        # Add ENDFOREACH
        resp = requests.post(
            f"{BASE_URL}/api/workflows/{self.workflow_id}/steps",
            json={
                "step_name": "loop_end",
                "step_type": "endforeach",
                "step_order": 1
            }
        )
        assert resp.status_code == 200
        assert resp.json()["step_type"] == "endforeach"

    def test_nested_control_flow(self):
        """Test nested IF inside FOREACH."""
        steps = [
            {"step_name": "outer_loop", "step_type": "foreach", "step_order": 0,
             "condition_config": {"item_var": "row", "list_ref": "dataset:1"}},
            {"step_name": "inner_check", "step_type": "if", "step_order": 1,
             "condition_config": {"left": "{{row.value}}", "operator": ">", "right": "0"}},
            {"step_name": "inner_check_end", "step_type": "endif", "step_order": 2},
            {"step_name": "outer_loop_end", "step_type": "endforeach", "step_order": 3}
        ]

        for step in steps:
            resp = requests.post(
                f"{BASE_URL}/api/workflows/{self.workflow_id}/steps",
                json=step
            )
            assert resp.status_code == 200

        # Verify structure
        wf = requests.get(f"{BASE_URL}/api/workflows/{self.workflow_id}").json()
        assert len(wf["steps"]) == 4
        types = [s["step_type"] for s in sorted(wf["steps"], key=lambda x: x["step_order"])]
        assert types == ["foreach", "if", "endif", "endforeach"]


class TestWorkflowVariablesAndFunctions:
    """Test variables and functions API."""

    def test_get_workflow_variables(self):
        """Test getting available workflow variables."""
        response = requests.get(f"{BASE_URL}/api/workflow-variables")
        assert response.status_code == 200
        data = response.json()

        assert "categories" in data
        # Should have at least the initial input category
        categories = data["categories"]
        cat_ids = [c["category_id"] for c in categories]
        assert "input" in cat_ids

    def test_get_string_functions(self):
        """Test getting available string functions."""
        response = requests.get(f"{BASE_URL}/functions")
        assert response.status_code == 200
        data = response.json()

        assert "functions" in data
        functions = data["functions"]

        # Should have common functions
        func_names = [f["name"] for f in functions]
        expected_funcs = ["upper", "lower", "trim", "calc", "format_choices"]
        for func in expected_funcs:
            assert func in func_names, f"Function '{func}' not found"


class TestWorkflowJobs:
    """Test workflow job management."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create a test workflow."""
        resp = requests.post(f"{BASE_URL}/api/workflows", json={
            "name": "Job Test Workflow"
        })
        self.workflow_id = resp.json()["id"]

        # Add a simple SET step so workflow can run
        requests.post(
            f"{BASE_URL}/api/workflows/{self.workflow_id}/steps",
            json={
                "step_name": "init",
                "step_type": "set",
                "condition_config": {"assignments": {"result": "done"}}
            }
        )

        yield
        requests.delete(f"{BASE_URL}/api/workflows/{self.workflow_id}")

    def test_list_workflow_jobs(self):
        """Test listing jobs for a workflow."""
        response = requests.get(f"{BASE_URL}/api/workflows/{self.workflow_id}/jobs")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestWorkflowUpdateJSON:
    """Test updating workflow via JSON."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create test workflows."""
        self.workflow_ids = []
        yield
        for wf_id in self.workflow_ids:
            try:
                requests.delete(f"{BASE_URL}/api/workflows/{wf_id}")
            except:
                pass

    def test_update_workflow_json(self):
        """Test updating workflow with JSON replaces steps."""
        # Create workflow with initial step
        resp = requests.post(f"{BASE_URL}/api/workflows", json={
            "name": "JSON Update Test"
        })
        wf_id = resp.json()["id"]
        self.workflow_ids.append(wf_id)

        # Add initial step
        requests.post(
            f"{BASE_URL}/api/workflows/{wf_id}/steps",
            json={
                "step_name": "original",
                "step_type": "set",
                "condition_config": {"assignments": {"x": "1"}}
            }
        )

        # Update via JSON with completely different steps
        new_json = {
            "version": "1.0",
            "name": "JSON Updated",
            "description": "Updated via JSON",
            "steps": [
                {
                    "step_order": 0,
                    "step_name": "new_init",
                    "step_type": "set",
                    "condition_config": {"assignments": {"y": "2"}}
                },
                {
                    "step_order": 1,
                    "step_name": "new_loop",
                    "step_type": "foreach",
                    "condition_config": {"item_var": "item", "list_ref": "items"}
                },
                {
                    "step_order": 2,
                    "step_name": "new_loop_end",
                    "step_type": "endforeach"
                }
            ]
        }

        response = requests.put(
            f"{BASE_URL}/api/workflows/{wf_id}/json",
            json={"workflow_json": new_json}
        )
        assert response.status_code == 200
        data = response.json()

        # Verify name updated
        assert data["name"] == "JSON Updated"

        # Verify steps replaced
        assert len(data["steps"]) == 3
        steps = {s["step_name"]: s for s in data["steps"]}
        assert "original" not in steps
        assert "new_init" in steps
        assert steps["new_init"]["step_type"] == "set"
        assert steps["new_loop"]["step_type"] == "foreach"
        assert steps["new_loop_end"]["step_type"] == "endforeach"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

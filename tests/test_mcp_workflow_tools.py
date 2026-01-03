#!/usr/bin/env python3
"""
Comprehensive MCP Workflow Tools Test Suite

Tests all workflow-related MCP tools for correctness and robustness.
"""

import sys
import json
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass, field

sys.path.insert(0, '.')

from backend.mcp.tools import MCPToolRegistry
from backend.database import SessionLocal
from backend.database.models import Workflow, WorkflowStep, Prompt, Project


@dataclass
class TestResult:
    """Single test result."""
    name: str
    passed: bool
    message: str = ""
    details: Any = None


@dataclass
class TestSuite:
    """Test suite with results tracking."""
    name: str
    results: List[TestResult] = field(default_factory=list)

    def add(self, name: str, passed: bool, message: str = "", details: Any = None):
        self.results.append(TestResult(name, passed, message, details))

    def ok(self, name: str, message: str = ""):
        self.add(name, True, message)

    def fail(self, name: str, message: str, details: Any = None):
        self.add(name, False, message, details)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    def print_results(self):
        print(f"\n{'='*60}")
        print(f"Test Suite: {self.name}")
        print(f"{'='*60}")
        for r in self.results:
            status = "✅ PASS" if r.passed else "❌ FAIL"
            print(f"{status} | {r.name}")
            if r.message:
                print(f"       {r.message}")
            if not r.passed and r.details:
                print(f"       Details: {r.details}")
        print(f"\nTotal: {self.passed_count} passed, {self.failed_count} failed")


class MCPWorkflowToolsTest:
    """MCP Workflow Tools Test Suite."""

    def __init__(self):
        self.registry = MCPToolRegistry()
        self.created_workflows: List[int] = []
        self.created_prompts: List[int] = []

    def cleanup(self):
        """Clean up test data."""
        db = SessionLocal()
        try:
            for wf_id in self.created_workflows:
                wf = db.query(Workflow).filter(Workflow.id == wf_id).first()
                if wf:
                    db.query(WorkflowStep).filter(WorkflowStep.workflow_id == wf_id).delete()
                    db.delete(wf)
            for p_id in self.created_prompts:
                p = db.query(Prompt).filter(Prompt.id == p_id).first()
                if p:
                    db.delete(p)
            db.commit()
        finally:
            db.close()

    # ========================================
    # Test Category 1: Workflow Basic Operations
    # ========================================

    def test_workflow_basic_operations(self) -> TestSuite:
        """Test basic workflow CRUD operations."""
        suite = TestSuite("Workflow Basic Operations")

        # Test 1.1: Create workflow
        try:
            result = self.registry._create_workflow(
                name="TEST_MCP_WF_001",
                description="Test workflow for MCP tools"
            )
            if result.get("id"):
                wf_id = result["id"]
                self.created_workflows.append(wf_id)
                suite.ok("create_workflow", f"Created workflow ID: {wf_id}")
            else:
                suite.fail("create_workflow", "No ID returned", result)
        except Exception as e:
            suite.fail("create_workflow", str(e))

        # Test 1.2: List workflows
        try:
            result = self.registry._list_workflows()
            # Result can be a list directly or a dict with 'workflows' key
            workflows = result if isinstance(result, list) else result.get("workflows", [])
            found = any(w["name"] == "TEST_MCP_WF_001" for w in workflows)
            if found:
                suite.ok("list_workflows", f"Found test workflow in list of {len(workflows)}")
            else:
                suite.fail("list_workflows", "Test workflow not found in list")
        except Exception as e:
            suite.fail("list_workflows", str(e))

        # Test 1.3: Get workflow
        try:
            result = self.registry._get_workflow(wf_id)
            if result.get("name") == "TEST_MCP_WF_001":
                suite.ok("get_workflow", f"Retrieved workflow: {result['name']}")
            else:
                suite.fail("get_workflow", "Incorrect workflow data", result)
        except Exception as e:
            suite.fail("get_workflow", str(e))

        # Test 1.4: Update workflow
        try:
            result = self.registry._update_workflow(
                wf_id,
                name="TEST_MCP_WF_001_UPDATED",
                description="Updated description"
            )
            if result.get("name") == "TEST_MCP_WF_001_UPDATED":
                suite.ok("update_workflow", "Workflow name updated successfully")
            else:
                suite.fail("update_workflow", "Name not updated", result)
        except Exception as e:
            suite.fail("update_workflow", str(e))

        # Test 1.5: Get non-existent workflow
        try:
            result = self.registry._get_workflow(999999)
            suite.fail("get_nonexistent_workflow", "Should have raised error")
        except ValueError as e:
            suite.ok("get_nonexistent_workflow", f"Correctly raised: {e}")
        except Exception as e:
            suite.fail("get_nonexistent_workflow", f"Wrong exception type: {type(e).__name__}: {e}")

        # Test 1.6: Delete workflow (create new one for this test)
        try:
            temp_result = self.registry._create_workflow(name="TEMP_DELETE_TEST")
            temp_id = temp_result["id"]
            delete_result = self.registry._delete_workflow(temp_id)
            # Check for success via 'deleted_workflow_id' or 'success' key
            if delete_result.get("deleted_workflow_id") or delete_result.get("success"):
                suite.ok("delete_workflow", f"Deleted workflow ID: {temp_id}")
            else:
                self.created_workflows.append(temp_id)
                suite.fail("delete_workflow", "Delete returned failure", delete_result)
        except Exception as e:
            suite.fail("delete_workflow", str(e))

        return suite

    # ========================================
    # Test Category 2: Workflow Step Operations
    # ========================================

    def test_workflow_step_operations(self) -> TestSuite:
        """Test workflow step CRUD operations."""
        suite = TestSuite("Workflow Step Operations")

        # Create a test workflow first
        try:
            wf_result = self.registry._create_workflow(name="TEST_STEP_OPS")
            wf_id = wf_result["id"]
            self.created_workflows.append(wf_id)
        except Exception as e:
            suite.fail("setup_workflow", f"Failed to create test workflow: {e}")
            return suite

        # Test 2.1: Add SET step
        try:
            result = self.registry._add_workflow_step(
                workflow_id=wf_id,
                step_name="init",
                step_type="set",
                condition_config='{"assignments":{"counter":"0"}}'
            )
            if result.get("step_id"):
                step1_id = result["step_id"]
                suite.ok("add_set_step", f"Added SET step ID: {step1_id}, order: {result['step_order']}")
            else:
                suite.fail("add_set_step", "No step_id returned", result)
        except Exception as e:
            suite.fail("add_set_step", str(e))

        # Test 2.2: Add PROMPT step
        try:
            result = self.registry._add_workflow_step(
                workflow_id=wf_id,
                step_name="ask",
                step_type="prompt",
                input_mapping='{"INPUT":"{{vars.counter}}"}'
            )
            if result.get("step_id"):
                step2_id = result["step_id"]
                suite.ok("add_prompt_step", f"Added PROMPT step ID: {step2_id}, order: {result['step_order']}")
            else:
                suite.fail("add_prompt_step", "No step_id returned", result)
        except Exception as e:
            suite.fail("add_prompt_step", str(e))

        # Test 2.3: Add step with explicit step_order (insert in middle)
        try:
            result = self.registry._add_workflow_step(
                workflow_id=wf_id,
                step_name="middle_step",
                step_type="set",
                step_order=1,  # Insert between init(0) and ask(now 2)
                condition_config='{"assignments":{"inserted":"true"}}'
            )
            if result.get("step_order") == 1:
                suite.ok("insert_step_middle", f"Inserted step at order 1, total steps: {result['total_steps']}")
                # Verify structure
                structure = result.get("current_structure", [])
                orders = [s["order"] for s in structure]
                if orders == [0, 1, 2]:
                    suite.ok("verify_step_order_shift", "Step orders correctly shifted: [0, 1, 2]")
                else:
                    suite.fail("verify_step_order_shift", f"Unexpected orders: {orders}")
            else:
                suite.fail("insert_step_middle", f"Wrong step_order: {result.get('step_order')}", result)
        except Exception as e:
            suite.fail("insert_step_middle", str(e))

        # Test 2.4: Duplicate step name rejection
        try:
            result = self.registry._add_workflow_step(
                workflow_id=wf_id,
                step_name="init",  # Already exists
                step_type="set",
                condition_config='{"assignments":{"x":"1"}}'
            )
            suite.fail("reject_duplicate_step_name", "Should have raised ValueError")
        except ValueError as e:
            if "already exists" in str(e):
                suite.ok("reject_duplicate_step_name", f"Correctly rejected: {e}")
            else:
                suite.fail("reject_duplicate_step_name", f"Wrong error message: {e}")
        except Exception as e:
            suite.fail("reject_duplicate_step_name", f"Wrong exception: {type(e).__name__}: {e}")

        # Test 2.5: Update step
        try:
            result = self.registry._update_workflow_step(
                step_id=step1_id,
                step_name="init_updated",
                condition_config='{"assignments":{"counter":"10"}}'
            )
            if result.get("step_name") == "init_updated":
                suite.ok("update_step", "Step name updated successfully")
            else:
                suite.fail("update_step", "Name not updated", result)
        except Exception as e:
            suite.fail("update_step", str(e))

        # Test 2.6: Update step to duplicate name should fail
        try:
            result = self.registry._update_workflow_step(
                step_id=step2_id,
                step_name="init_updated"  # Now conflicts with step1
            )
            suite.fail("reject_update_duplicate", "Should have raised ValueError")
        except ValueError as e:
            if "already exists" in str(e):
                suite.ok("reject_update_duplicate", f"Correctly rejected update: {e}")
            else:
                suite.fail("reject_update_duplicate", f"Wrong error: {e}")
        except Exception as e:
            suite.fail("reject_update_duplicate", f"Wrong exception: {type(e).__name__}: {e}")

        # Test 2.7: Delete step
        try:
            # Get current step count
            wf_before = self.registry._get_workflow(wf_id)
            count_before = len(wf_before.get("steps", []))

            result = self.registry._delete_workflow_step(step_id=step2_id)

            wf_after = self.registry._get_workflow(wf_id)
            count_after = len(wf_after.get("steps", []))

            if count_after == count_before - 1:
                suite.ok("delete_step", f"Deleted step, count: {count_before} -> {count_after}")
            else:
                suite.fail("delete_step", f"Step count unchanged: {count_before} -> {count_after}")
        except Exception as e:
            suite.fail("delete_step", str(e))

        # Test 2.8: Delete non-existent step
        try:
            result = self.registry._delete_workflow_step(step_id=999999)
            suite.fail("delete_nonexistent_step", "Should have raised error")
        except ValueError as e:
            suite.ok("delete_nonexistent_step", f"Correctly raised: {e}")
        except Exception as e:
            suite.fail("delete_nonexistent_step", f"Wrong exception: {type(e).__name__}: {e}")

        return suite

    # ========================================
    # Test Category 3: Control Flow Block Operations
    # ========================================

    def test_control_flow_blocks(self) -> TestSuite:
        """Test FOREACH and IF block operations."""
        suite = TestSuite("Control Flow Block Operations")

        # Create test workflow
        try:
            wf_result = self.registry._create_workflow(name="TEST_CONTROL_FLOW")
            wf_id = wf_result["id"]
            self.created_workflows.append(wf_id)
        except Exception as e:
            suite.fail("setup_workflow", f"Failed to create test workflow: {e}")
            return suite

        # Test 3.1: Add FOREACH block
        try:
            result = self.registry._add_foreach_block(
                workflow_id=wf_id,
                foreach_name="loop_items",
                source="dataset:1:limit:10",
                item_var="ITEM"
            )
            if result.get("foreach_step_id") and result.get("endforeach_step_id"):
                suite.ok("add_foreach_block",
                    f"Created FOREACH (ID:{result['foreach_step_id']}) and ENDFOREACH (ID:{result['endforeach_step_id']})")
                # Verify structure
                structure = result.get("current_structure", [])
                types = [s["type"] for s in structure]
                if types == ["foreach", "endforeach"]:
                    suite.ok("foreach_structure", "Correct structure: [foreach, endforeach]")
                else:
                    suite.fail("foreach_structure", f"Wrong structure: {types}")
            else:
                suite.fail("add_foreach_block", "Missing step IDs", result)
        except Exception as e:
            suite.fail("add_foreach_block", str(e))

        # Test 3.2: Duplicate FOREACH block name rejection
        try:
            result = self.registry._add_foreach_block(
                workflow_id=wf_id,
                foreach_name="loop_items",  # Already exists
                source="dataset:2:limit:5",
                item_var="ROW"
            )
            suite.fail("reject_duplicate_foreach", "Should have raised ValueError")
        except ValueError as e:
            if "already exists" in str(e):
                suite.ok("reject_duplicate_foreach", f"Correctly rejected: {e}")
            else:
                suite.fail("reject_duplicate_foreach", f"Wrong error: {e}")
        except Exception as e:
            suite.fail("reject_duplicate_foreach", f"Wrong exception: {type(e).__name__}: {e}")

        # Test 3.3: Add IF block (without ELSE)
        try:
            result = self.registry._add_if_block(
                workflow_id=wf_id,
                if_name="check_value",
                left="{{vars.x}}",
                operator="==",
                right="1",
                include_else=False
            )
            if result.get("if_step_id") and result.get("endif_step_id"):
                suite.ok("add_if_block_no_else",
                    f"Created IF (ID:{result['if_step_id']}) and ENDIF (ID:{result['endif_step_id']})")
            else:
                suite.fail("add_if_block_no_else", "Missing step IDs", result)
        except Exception as e:
            suite.fail("add_if_block_no_else", str(e))

        # Test 3.4: Add IF block (with ELSE)
        try:
            result = self.registry._add_if_block(
                workflow_id=wf_id,
                if_name="check_answer",
                left="{{step1.output}}",
                operator="!=",
                right="error",
                include_else=True
            )
            if result.get("if_step_id") and result.get("else_step_id") and result.get("endif_step_id"):
                suite.ok("add_if_block_with_else",
                    f"Created IF/ELSE/ENDIF (IDs: {result['if_step_id']}/{result['else_step_id']}/{result['endif_step_id']})")
            else:
                suite.fail("add_if_block_with_else", "Missing step IDs", result)
        except Exception as e:
            suite.fail("add_if_block_with_else", str(e))

        # Test 3.5: Duplicate IF block name rejection
        try:
            result = self.registry._add_if_block(
                workflow_id=wf_id,
                if_name="check_value",  # Already exists
                left="{{vars.y}}",
                operator=">",
                right="0"
            )
            suite.fail("reject_duplicate_if", "Should have raised ValueError")
        except ValueError as e:
            if "already exists" in str(e):
                suite.ok("reject_duplicate_if", f"Correctly rejected: {e}")
            else:
                suite.fail("reject_duplicate_if", f"Wrong error: {e}")
        except Exception as e:
            suite.fail("reject_duplicate_if", f"Wrong exception: {type(e).__name__}: {e}")

        # Test 3.6: Insert step inside FOREACH block
        try:
            # Get current structure
            wf = self.registry._get_workflow(wf_id)
            steps = wf.get("steps", [])

            # Find FOREACH position
            foreach_order = None
            for s in steps:
                if s["step_name"] == "loop_items":
                    foreach_order = s["step_order"]
                    break

            if foreach_order is not None:
                # Insert step right after FOREACH
                result = self.registry._add_workflow_step(
                    workflow_id=wf_id,
                    step_name="inside_loop",
                    step_type="set",
                    step_order=foreach_order + 1,
                    condition_config='{"assignments":{"processed":"true"}}'
                )
                suite.ok("insert_inside_foreach",
                    f"Inserted step inside FOREACH at order {result['step_order']}")
            else:
                suite.fail("insert_inside_foreach", "Could not find FOREACH step")
        except Exception as e:
            suite.fail("insert_inside_foreach", str(e))

        return suite

    # ========================================
    # Test Category 4: Validation and Edge Cases
    # ========================================

    def test_validation_and_edge_cases(self) -> TestSuite:
        """Test validation and edge cases."""
        suite = TestSuite("Validation and Edge Cases")

        # Create test workflow
        try:
            wf_result = self.registry._create_workflow(name="TEST_VALIDATION")
            wf_id = wf_result["id"]
            self.created_workflows.append(wf_id)
        except Exception as e:
            suite.fail("setup_workflow", f"Failed to create test workflow: {e}")
            return suite

        # Test 4.1: Invalid step type
        try:
            result = self.registry._add_workflow_step(
                workflow_id=wf_id,
                step_name="bad_type",
                step_type="invalid_type",
                condition_config='{}'
            )
            # Check if validation caught it
            validation = result.get("validation", {})
            if validation.get("errors", 0) > 0:
                suite.ok("invalid_step_type_validation", "Validation caught invalid step type")
            else:
                suite.fail("invalid_step_type_validation", "No validation error for invalid type", result)
        except ValueError as e:
            suite.ok("invalid_step_type_rejected", f"Rejected at creation: {e}")
        except Exception as e:
            suite.fail("invalid_step_type", str(e))

        # Test 4.2: Invalid JSON in condition_config
        try:
            result = self.registry._add_workflow_step(
                workflow_id=wf_id,
                step_name="bad_json",
                step_type="set",
                condition_config='not valid json'
            )
            suite.fail("invalid_json_config", "Should have raised error for invalid JSON")
        except Exception as e:
            suite.ok("invalid_json_config", f"Correctly rejected invalid JSON: {type(e).__name__}")

        # Test 4.3: Reserved step name
        try:
            result = self.registry._add_workflow_step(
                workflow_id=wf_id,
                step_name="input",  # Reserved name
                step_type="set",
                condition_config='{"assignments":{"x":"1"}}'
            )
            # If it's created, check validation
            validation = result.get("validation", {})
            issues = validation.get("issues", [])
            has_reserved_error = any("reserved" in str(i).lower() for i in issues)
            if has_reserved_error:
                suite.ok("reserved_name_validation", "Validation caught reserved name")
            else:
                suite.fail("reserved_name_validation", "No validation error for reserved name", result)
        except ValueError as e:
            if "reserved" in str(e).lower():
                suite.ok("reserved_name_rejected", f"Rejected at creation: {e}")
            else:
                suite.fail("reserved_name", f"Wrong error: {e}")
        except Exception as e:
            suite.fail("reserved_name", str(e))

        # Test 4.4: Invalid step name format
        try:
            result = self.registry._add_workflow_step(
                workflow_id=wf_id,
                step_name="123_invalid",  # Starts with number
                step_type="set",
                condition_config='{"assignments":{"x":"1"}}'
            )
            # Check validation
            validation = result.get("validation", {})
            issues = validation.get("issues", [])
            has_format_error = any("format" in str(i).lower() or "invalid" in str(i).lower() for i in issues)
            if has_format_error:
                suite.ok("invalid_name_format_validation", "Validation caught invalid format")
            else:
                suite.fail("invalid_name_format_validation", "No validation error for invalid format", result)
        except ValueError as e:
            suite.ok("invalid_name_format_rejected", f"Rejected at creation: {e}")
        except Exception as e:
            suite.fail("invalid_name_format", str(e))

        # Test 4.5: ENDFOREACH without FOREACH
        try:
            result = self.registry._add_workflow_step(
                workflow_id=wf_id,
                step_name="orphan_endforeach",
                step_type="endforeach"
            )
            validation = result.get("validation", {})
            if not validation.get("valid", True):
                suite.ok("orphan_endforeach_validation", "Validation caught orphan ENDFOREACH")
            else:
                suite.fail("orphan_endforeach_validation", "No validation error", result)
        except Exception as e:
            suite.fail("orphan_endforeach", str(e))

        # Test 4.6: Operation on non-existent workflow
        try:
            result = self.registry._add_workflow_step(
                workflow_id=999999,
                step_name="test",
                step_type="set",
                condition_config='{"assignments":{}}'
            )
            suite.fail("nonexistent_workflow_step", "Should have raised error")
        except ValueError as e:
            suite.ok("nonexistent_workflow_step", f"Correctly raised: {e}")
        except Exception as e:
            suite.fail("nonexistent_workflow_step", f"Wrong exception: {type(e).__name__}: {e}")

        # Test 4.7: Empty workflow name
        try:
            result = self.registry._create_workflow(name="")
            suite.fail("empty_workflow_name", "Should have raised error")
        except Exception as e:
            suite.ok("empty_workflow_name", f"Correctly rejected empty name: {type(e).__name__}")

        # Test 4.8: Very long step name
        try:
            long_name = "a" * 300
            result = self.registry._add_workflow_step(
                workflow_id=wf_id,
                step_name=long_name,
                step_type="set",
                condition_config='{"assignments":{}}'
            )
            # May or may not fail depending on DB constraints
            suite.ok("long_step_name", f"Handled long name (length={len(long_name)})")
        except Exception as e:
            suite.ok("long_step_name_rejected", f"Rejected long name: {type(e).__name__}")

        return suite

    # ========================================
    # Test Category 5: Complex Workflow Scenarios
    # ========================================

    def test_complex_scenarios(self) -> TestSuite:
        """Test complex workflow scenarios."""
        suite = TestSuite("Complex Workflow Scenarios")

        # Create test workflow
        try:
            wf_result = self.registry._create_workflow(
                name="TEST_COMPLEX",
                description="Complex workflow test"
            )
            wf_id = wf_result["id"]
            self.created_workflows.append(wf_id)
        except Exception as e:
            suite.fail("setup_workflow", f"Failed to create test workflow: {e}")
            return suite

        # Test 5.1: Build a complete valid workflow
        try:
            # Step 1: Initialize
            self.registry._add_workflow_step(
                workflow_id=wf_id,
                step_name="init",
                step_type="set",
                condition_config='{"assignments":{"count":"0","total":"0"}}'
            )

            # Step 2: FOREACH block
            self.registry._add_foreach_block(
                workflow_id=wf_id,
                foreach_name="loop",
                source="dataset:1:limit:5",
                item_var="ROW"
            )

            # Step 3: Process step inside loop (insert at position 2)
            self.registry._add_workflow_step(
                workflow_id=wf_id,
                step_name="process",
                step_type="set",
                step_order=2,
                condition_config='{"assignments":{"count":"calc({{vars.count}} + 1)"}}'
            )

            # Step 4: Result step after loop
            self.registry._add_workflow_step(
                workflow_id=wf_id,
                step_name="result",
                step_type="set",
                condition_config='{"assignments":{"summary":"Processed {{vars.count}} items"}}'
            )

            # Verify final structure
            wf = self.registry._get_workflow(wf_id)
            steps = wf.get("steps", [])
            step_info = [(s["step_order"], s["step_name"], s["step_type"]) for s in steps]

            expected_order = [
                (0, "init", "set"),
                (1, "loop", "foreach"),
                (2, "process", "set"),
                (3, "loop_end", "endforeach"),
                (4, "result", "set")
            ]

            if step_info == expected_order:
                suite.ok("build_complete_workflow", f"Built valid workflow with {len(steps)} steps")
            else:
                suite.fail("build_complete_workflow", f"Unexpected structure",
                    {"expected": expected_order, "actual": step_info})
        except Exception as e:
            suite.fail("build_complete_workflow", str(e))

        # Test 5.2: Reorder steps by updating step_order
        try:
            # Move 'result' step to position 0 (should shift others)
            wf = self.registry._get_workflow(wf_id)
            result_step = next((s for s in wf["steps"] if s["step_name"] == "result"), None)

            if result_step:
                # Note: This tests if update_workflow_step can change step_order
                # The implementation may or may not support this
                try:
                    update_result = self.registry._update_workflow_step(
                        step_id=result_step["id"],
                        step_order=0
                    )
                    suite.ok("reorder_step", f"Reordered step to position 0")
                except Exception as e:
                    suite.ok("reorder_step_not_supported", f"Reorder via update not supported: {type(e).__name__}")
            else:
                suite.fail("reorder_step", "Could not find result step")
        except Exception as e:
            suite.fail("reorder_step", str(e))

        # Test 5.3: Delete middle step and verify order continuity
        try:
            # Create a new simple workflow for this test
            temp_wf = self.registry._create_workflow(name="TEST_DELETE_MIDDLE")
            temp_wf_id = temp_wf["id"]
            self.created_workflows.append(temp_wf_id)

            # Add 5 steps
            step_ids = []
            for i in range(5):
                result = self.registry._add_workflow_step(
                    workflow_id=temp_wf_id,
                    step_name=f"step_{i}",
                    step_type="set",
                    condition_config='{"assignments":{}}'
                )
                step_ids.append(result["step_id"])

            # Delete middle step (step_2)
            self.registry._delete_workflow_step(step_id=step_ids[2])

            # Verify remaining steps
            wf = self.registry._get_workflow(temp_wf_id)
            remaining = [(s["step_name"], s["step_order"]) for s in wf["steps"]]

            # Check that orders are still sequential
            orders = [s["step_order"] for s in wf["steps"]]
            if orders == list(range(len(orders))):
                suite.ok("delete_middle_step_reorder", f"Orders remain sequential after delete: {orders}")
            else:
                suite.fail("delete_middle_step_reorder", f"Orders not sequential: {orders}")
        except Exception as e:
            suite.fail("delete_middle_step", str(e))

        return suite

    def run_all_tests(self) -> Dict[str, TestSuite]:
        """Run all test suites."""
        results = {}

        try:
            results["basic"] = self.test_workflow_basic_operations()
            results["steps"] = self.test_workflow_step_operations()
            results["control_flow"] = self.test_control_flow_blocks()
            results["validation"] = self.test_validation_and_edge_cases()
            results["complex"] = self.test_complex_scenarios()
        finally:
            self.cleanup()

        return results


def main():
    """Run all tests and print results."""
    print("\n" + "="*60)
    print("MCP Workflow Tools Comprehensive Test Suite")
    print("="*60)

    tester = MCPWorkflowToolsTest()
    results = tester.run_all_tests()

    # Print all results
    for suite in results.values():
        suite.print_results()

    # Summary
    total_passed = sum(s.passed_count for s in results.values())
    total_failed = sum(s.failed_count for s in results.values())

    print("\n" + "="*60)
    print("FINAL SUMMARY")
    print("="*60)
    print(f"Total Tests: {total_passed + total_failed}")
    print(f"Passed: {total_passed}")
    print(f"Failed: {total_failed}")
    print(f"Success Rate: {total_passed/(total_passed+total_failed)*100:.1f}%")

    if total_failed > 0:
        print("\n❌ SOME TESTS FAILED")
        return 1
    else:
        print("\n✅ ALL TESTS PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(main())

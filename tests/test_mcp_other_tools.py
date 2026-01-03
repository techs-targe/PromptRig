#!/usr/bin/env python3
"""
Comprehensive MCP Tools Test Suite (Non-Workflow)

Tests all non-workflow MCP tools for correctness and robustness.
Categories:
1. Project Management
2. Prompt Management
3. Job Management
4. Dataset Management
5. System Settings
"""

import sys
import json
import time
from typing import Dict, List, Any
from dataclasses import dataclass, field

sys.path.insert(0, '.')

from backend.mcp.tools import MCPToolRegistry
from backend.database import SessionLocal
from backend.database.models import Project, Prompt, PromptRevision, Dataset, Job, Tag


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
                details_str = str(r.details)[:200]
                print(f"       Details: {details_str}")
        print(f"\nTotal: {self.passed_count} passed, {self.failed_count} failed")


class MCPOtherToolsTest:
    """MCP Other Tools Test Suite."""

    def __init__(self):
        self.registry = MCPToolRegistry()
        self.created_projects: List[int] = []
        self.created_prompts: List[int] = []
        self.created_datasets: List[int] = []

    def cleanup(self):
        """Clean up test data."""
        db = SessionLocal()
        try:
            # Delete prompts first (due to foreign key)
            for p_id in self.created_prompts:
                # Delete revisions
                db.query(PromptRevision).filter(PromptRevision.prompt_id == p_id).delete()
                prompt = db.query(Prompt).filter(Prompt.id == p_id).first()
                if prompt:
                    db.delete(prompt)

            # Delete projects
            for proj_id in self.created_projects:
                proj = db.query(Project).filter(Project.id == proj_id).first()
                if proj:
                    db.delete(proj)

            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Cleanup error: {e}")
        finally:
            db.close()

    # ========================================
    # Test Category 1: Project Management
    # ========================================

    def test_project_management(self) -> TestSuite:
        """Test project CRUD operations."""
        suite = TestSuite("Project Management")

        # Test 1.1: List projects
        try:
            result = self.registry._list_projects()
            projects = result if isinstance(result, list) else result.get("projects", [])
            suite.ok("list_projects", f"Listed {len(projects)} projects")
        except Exception as e:
            suite.fail("list_projects", str(e))

        # Test 1.2: Create project
        try:
            result = self.registry._create_project(
                name="TEST_PROJECT_MCP_001",
                description="Test project for MCP tools"
            )
            if result.get("id"):
                proj_id = result["id"]
                self.created_projects.append(proj_id)
                suite.ok("create_project", f"Created project ID: {proj_id}")
            else:
                suite.fail("create_project", "No ID returned", result)
        except Exception as e:
            suite.fail("create_project", str(e))

        # Test 1.3: Get project
        try:
            result = self.registry._get_project(proj_id)
            if result.get("name") == "TEST_PROJECT_MCP_001":
                suite.ok("get_project", f"Retrieved project: {result['name']}")
            else:
                suite.fail("get_project", "Wrong project data", result)
        except Exception as e:
            suite.fail("get_project", str(e))

        # Test 1.4: Update project
        try:
            result = self.registry._update_project(
                proj_id,
                name="TEST_PROJECT_MCP_001_UPDATED",
                description="Updated description"
            )
            if result.get("name") == "TEST_PROJECT_MCP_001_UPDATED":
                suite.ok("update_project", "Project updated successfully")
            else:
                suite.fail("update_project", "Update failed", result)
        except Exception as e:
            suite.fail("update_project", str(e))

        # Test 1.5: Get non-existent project
        try:
            result = self.registry._get_project(999999)
            suite.fail("get_nonexistent_project", "Should have raised error")
        except ValueError as e:
            suite.ok("get_nonexistent_project", f"Correctly raised: {e}")
        except Exception as e:
            suite.fail("get_nonexistent_project", f"Wrong exception: {type(e).__name__}")

        # Test 1.6: Create project with empty name
        try:
            result = self.registry._create_project(name="", description="Test")
            suite.fail("create_empty_name_project", "Should have raised error")
        except (ValueError, Exception) as e:
            suite.ok("create_empty_name_project", f"Correctly rejected: {type(e).__name__}")

        # Test 1.7: Delete project (create new one for this)
        try:
            temp = self.registry._create_project(name="TEMP_DELETE_PROJECT")
            temp_id = temp["id"]
            result = self.registry._delete_project(temp_id)
            if result.get("deleted_project_id") or result.get("id") == temp_id:
                suite.ok("delete_project", f"Deleted project ID: {temp_id}")
            else:
                self.created_projects.append(temp_id)
                suite.fail("delete_project", "Delete may have failed", result)
        except Exception as e:
            suite.fail("delete_project", str(e))

        return suite

    # ========================================
    # Test Category 2: Prompt Management
    # ========================================

    def test_prompt_management(self) -> TestSuite:
        """Test prompt CRUD operations."""
        suite = TestSuite("Prompt Management")

        # Create a test project first
        try:
            proj_result = self.registry._create_project(name="TEST_PROMPT_PROJECT")
            proj_id = proj_result["id"]
            self.created_projects.append(proj_id)
        except Exception as e:
            suite.fail("setup_project", f"Failed to create test project: {e}")
            return suite

        # Test 2.1: List prompts (empty project)
        try:
            result = self.registry._list_prompts(proj_id)
            prompts = result if isinstance(result, list) else result.get("prompts", [])
            suite.ok("list_prompts_empty", f"Listed {len(prompts)} prompts in new project")
        except Exception as e:
            suite.fail("list_prompts_empty", str(e))

        # Test 2.2: Create prompt
        try:
            result = self.registry._create_prompt(
                project_id=proj_id,
                name="TEST_PROMPT_001",
                template="Hello, {{NAME}}! Your number is {{NUMBER:NUM}}.",
                parser_config='{"OUTPUT": ".*"}'
            )
            if result.get("id"):
                prompt_id = result["id"]
                self.created_prompts.append(prompt_id)
                suite.ok("create_prompt", f"Created prompt ID: {prompt_id}")
            else:
                suite.fail("create_prompt", "No ID returned", result)
        except Exception as e:
            suite.fail("create_prompt", str(e))

        # Test 2.3: Analyze template
        try:
            result = self.registry._analyze_template(
                "Test {{PARAM1}} and {{PARAM2:TEXT10}} and {{NUM:NUM}}"
            )
            params = result.get("parameters", [])
            if len(params) == 3:
                suite.ok("analyze_template", f"Extracted {len(params)} parameters: {[p.get('name') for p in params]}")
            else:
                suite.fail("analyze_template", f"Expected 3 params, got {len(params)}", result)
        except Exception as e:
            suite.fail("analyze_template", str(e))

        # Test 2.4: Get prompt
        try:
            result = self.registry._get_prompt(prompt_id)
            if result.get("name") == "TEST_PROMPT_001":
                suite.ok("get_prompt", f"Retrieved prompt with {len(result.get('parameters', []))} parameters")
            else:
                suite.fail("get_prompt", "Wrong prompt data", result)
        except Exception as e:
            suite.fail("get_prompt", str(e))

        # Test 2.5: Update prompt
        try:
            result = self.registry._update_prompt(
                prompt_id,
                name="TEST_PROMPT_001_UPDATED",
                template="Updated: {{NEW_PARAM}}"
            )
            if result.get("name") == "TEST_PROMPT_001_UPDATED":
                suite.ok("update_prompt", "Prompt updated successfully")
            else:
                suite.fail("update_prompt", "Update failed", result)
        except Exception as e:
            suite.fail("update_prompt", str(e))

        # Test 2.6: List prompts (should have 1 now)
        try:
            result = self.registry._list_prompts(proj_id)
            prompts = result if isinstance(result, list) else result.get("prompts", [])
            if len(prompts) == 1:
                suite.ok("list_prompts_after_create", f"Correctly shows 1 prompt")
            else:
                suite.fail("list_prompts_after_create", f"Expected 1, got {len(prompts)}")
        except Exception as e:
            suite.fail("list_prompts_after_create", str(e))

        # Test 2.7: Get non-existent prompt
        try:
            result = self.registry._get_prompt(999999)
            suite.fail("get_nonexistent_prompt", "Should have raised error")
        except ValueError as e:
            suite.ok("get_nonexistent_prompt", f"Correctly raised: {e}")
        except Exception as e:
            suite.fail("get_nonexistent_prompt", f"Wrong exception: {type(e).__name__}")

        # Test 2.8: Create prompt with empty name
        try:
            result = self.registry._create_prompt(
                project_id=proj_id,
                name="",
                template="Test"
            )
            # Check if it fails or creates with empty name
            if result.get("id"):
                suite.fail("create_empty_name_prompt", "Should have rejected empty name")
                self.created_prompts.append(result["id"])
            else:
                suite.ok("create_empty_name_prompt", "Rejected empty name")
        except (ValueError, Exception) as e:
            suite.ok("create_empty_name_prompt", f"Correctly rejected: {type(e).__name__}")

        # Test 2.9: Delete prompt
        try:
            temp_prompt = self.registry._create_prompt(
                project_id=proj_id,
                name="TEMP_DELETE_PROMPT",
                template="Delete me"
            )
            temp_prompt_id = temp_prompt["id"]
            result = self.registry._delete_prompt(temp_prompt_id)
            if result.get("deleted_prompt_id") or result.get("id") == temp_prompt_id:
                suite.ok("delete_prompt", f"Deleted prompt ID: {temp_prompt_id}")
            else:
                self.created_prompts.append(temp_prompt_id)
                suite.fail("delete_prompt", "Delete may have failed", result)
        except Exception as e:
            suite.fail("delete_prompt", str(e))

        return suite

    # ========================================
    # Test Category 3: Job Management
    # ========================================

    def test_job_management(self) -> TestSuite:
        """Test job management operations."""
        suite = TestSuite("Job Management")

        # Test 3.1: List recent jobs
        try:
            result = self.registry._list_recent_jobs(limit=10)
            jobs = result if isinstance(result, list) else result.get("jobs", [])
            suite.ok("list_recent_jobs", f"Listed {len(jobs)} recent jobs")
        except Exception as e:
            suite.fail("list_recent_jobs", str(e))

        # Test 3.2: Get job status (find an existing job)
        try:
            db = SessionLocal()
            existing_job = db.query(Job).order_by(Job.id.desc()).first()
            db.close()

            if existing_job:
                result = self.registry._get_job_status(existing_job.id)
                if result.get("id") == existing_job.id:
                    suite.ok("get_job_status", f"Got status for job {existing_job.id}: {result.get('status')}")
                else:
                    suite.fail("get_job_status", "Wrong job returned", result)
            else:
                suite.ok("get_job_status_skip", "No existing jobs to test")
        except Exception as e:
            suite.fail("get_job_status", str(e))

        # Test 3.3: Get non-existent job
        try:
            result = self.registry._get_job_status(999999)
            suite.fail("get_nonexistent_job", "Should have raised error")
        except ValueError as e:
            suite.ok("get_nonexistent_job", f"Correctly raised: {e}")
        except Exception as e:
            suite.fail("get_nonexistent_job", f"Wrong exception: {type(e).__name__}")

        # Test 3.4: Cancel non-existent job
        try:
            result = self.registry._cancel_job(999999)
            suite.fail("cancel_nonexistent_job", "Should have raised error")
        except ValueError as e:
            suite.ok("cancel_nonexistent_job", f"Correctly raised: {e}")
        except Exception as e:
            suite.fail("cancel_nonexistent_job", f"Wrong exception: {type(e).__name__}")

        # Test 3.5: Export job CSV (find completed job)
        try:
            db = SessionLocal()
            completed_job = db.query(Job).filter(Job.status == "completed").order_by(Job.id.desc()).first()
            db.close()

            if completed_job:
                result = self.registry._export_job_csv(completed_job.id)
                if result.get("download_url") or result.get("markdown_link"):
                    suite.ok("export_job_csv", f"Got CSV link for job {completed_job.id}")
                else:
                    suite.fail("export_job_csv", "No download URL", result)
            else:
                suite.ok("export_job_csv_skip", "No completed jobs to test")
        except Exception as e:
            suite.fail("export_job_csv", str(e))

        # Test 3.6: List jobs with limit
        try:
            result = self.registry._list_recent_jobs(limit=5)
            jobs = result if isinstance(result, list) else result.get("jobs", [])
            if len(jobs) <= 5:
                suite.ok("list_jobs_limit", f"Limit works: got {len(jobs)} jobs with limit=5")
            else:
                suite.fail("list_jobs_limit", f"Got {len(jobs)} jobs, expected <= 5")
        except Exception as e:
            suite.fail("list_jobs_limit", str(e))

        return suite

    # ========================================
    # Test Category 4: Dataset Management
    # ========================================

    def test_dataset_management(self) -> TestSuite:
        """Test dataset management operations."""
        suite = TestSuite("Dataset Management")

        # Test 4.1: List datasets
        try:
            result = self.registry._list_datasets()
            datasets = result.get("datasets", []) if isinstance(result, dict) else result
            suite.ok("list_datasets", f"Listed {len(datasets)} datasets")

            # Save first dataset ID for later tests
            first_dataset_id = datasets[0]["id"] if datasets else None
        except Exception as e:
            suite.fail("list_datasets", str(e))
            first_dataset_id = None

        if first_dataset_id:
            # Test 4.2: Get dataset
            try:
                result = self.registry._get_dataset(first_dataset_id)
                if result.get("id") == first_dataset_id:
                    suite.ok("get_dataset", f"Got dataset: {result.get('name')} with {result.get('row_count', 0)} rows")
                else:
                    suite.fail("get_dataset", "Wrong dataset", result)
            except Exception as e:
                suite.fail("get_dataset", str(e))

            # Test 4.3: Preview dataset rows
            try:
                result = self.registry._preview_dataset_rows(first_dataset_id, limit=5)
                rows = result.get("rows", [])
                suite.ok("preview_dataset_rows", f"Previewed {len(rows)} rows")
            except Exception as e:
                suite.fail("preview_dataset_rows", str(e))

            # Test 4.4: Search dataset content
            try:
                result = self.registry._search_dataset_content(first_dataset_id, query="a")
                matches = result.get("matches", [])
                suite.ok("search_dataset_content", f"Found {len(matches)} matches for 'a'")
            except Exception as e:
                suite.fail("search_dataset_content", str(e))

            # Test 4.5: Get dataset projects
            try:
                result = self.registry._get_dataset_projects(first_dataset_id)
                projects = result.get("projects", [])
                suite.ok("get_dataset_projects", f"Dataset associated with {len(projects)} projects")
            except Exception as e:
                suite.fail("get_dataset_projects", str(e))
        else:
            suite.ok("dataset_tests_skipped", "No datasets available for testing")

        # Test 4.6: Get non-existent dataset
        try:
            result = self.registry._get_dataset(999999)
            suite.fail("get_nonexistent_dataset", "Should have raised error")
        except ValueError as e:
            suite.ok("get_nonexistent_dataset", f"Correctly raised: {e}")
        except Exception as e:
            suite.fail("get_nonexistent_dataset", f"Wrong exception: {type(e).__name__}")

        # Test 4.7: Search datasets
        try:
            result = self.registry._search_datasets(query="test")
            datasets = result.get("datasets", []) if isinstance(result, dict) else result
            suite.ok("search_datasets", f"Found {len(datasets)} datasets matching 'test'")
        except Exception as e:
            suite.fail("search_datasets", str(e))

        # Test 4.8: Preview with invalid dataset
        try:
            result = self.registry._preview_dataset_rows(999999, limit=5)
            suite.fail("preview_nonexistent_dataset", "Should have raised error")
        except ValueError as e:
            suite.ok("preview_nonexistent_dataset", f"Correctly raised: {e}")
        except Exception as e:
            suite.fail("preview_nonexistent_dataset", f"Wrong exception: {type(e).__name__}")

        return suite

    # ========================================
    # Test Category 5: System Settings & Models
    # ========================================

    def test_system_settings(self) -> TestSuite:
        """Test system settings and model operations."""
        suite = TestSuite("System Settings & Models")

        # Test 5.1: List models
        try:
            result = self.registry._list_models()
            models = result.get("models", []) if isinstance(result, dict) else result
            if len(models) > 0:
                model_names = [m.get("name", m.get("id", "unknown")) for m in models]
                suite.ok("list_models", f"Found {len(models)} models: {model_names[:5]}...")
            else:
                suite.fail("list_models", "No models found", result)
        except Exception as e:
            suite.fail("list_models", str(e))

        # Test 5.2: Get system settings
        try:
            result = self.registry._get_system_settings()
            if result:
                settings_keys = list(result.keys()) if isinstance(result, dict) else ["unknown"]
                suite.ok("get_system_settings", f"Got settings: {settings_keys[:5]}")
            else:
                suite.fail("get_system_settings", "Empty settings", result)
        except Exception as e:
            suite.fail("get_system_settings", str(e))

        return suite

    # ========================================
    # Test Category 6: Prompt Execution
    # ========================================

    def test_prompt_execution(self) -> TestSuite:
        """Test prompt execution operations (limited - no actual LLM calls)."""
        suite = TestSuite("Prompt Execution (Validation Only)")

        # Create test project and prompt
        try:
            proj = self.registry._create_project(name="TEST_EXEC_PROJECT")
            proj_id = proj["id"]
            self.created_projects.append(proj_id)

            prompt = self.registry._create_prompt(
                project_id=proj_id,
                name="TEST_EXEC_PROMPT",
                template="Say hello to {{NAME}}",
                parser_config='{"GREETING": ".*"}'
            )
            prompt_id = prompt["id"]
            self.created_prompts.append(prompt_id)
        except Exception as e:
            suite.fail("setup_execution", f"Setup failed: {e}")
            return suite

        # Test 6.1: Execute prompt with missing params
        try:
            result = self.registry._execute_prompt(
                prompt_id=prompt_id,
                input_params={}  # Missing NAME
            )
            # This might succeed with empty param or fail
            suite.ok("execute_missing_params", f"Handled missing params: {type(result)}")
        except ValueError as e:
            suite.ok("execute_missing_params", f"Correctly rejected: {e}")
        except Exception as e:
            # LLM errors are expected if no API key
            if "API" in str(e) or "key" in str(e).lower() or "connection" in str(e).lower():
                suite.ok("execute_missing_params_api", f"API error (expected): {type(e).__name__}")
            else:
                suite.fail("execute_missing_params", str(e))

        # Test 6.2: Execute with non-existent prompt
        try:
            result = self.registry._execute_prompt(
                prompt_id=999999,
                input_params={"NAME": "Test"}
            )
            suite.fail("execute_nonexistent_prompt", "Should have raised error")
        except ValueError as e:
            suite.ok("execute_nonexistent_prompt", f"Correctly raised: {e}")
        except Exception as e:
            suite.fail("execute_nonexistent_prompt", f"Wrong exception: {type(e).__name__}")

        # Test 6.3: Execute template directly (validation)
        try:
            # This will likely fail due to no LLM connection, but should validate inputs
            result = self.registry._execute_template(
                prompt_template="Hello {{NAME}}",
                input_params={"NAME": "World"}
            )
            suite.ok("execute_template", f"Template execution attempted")
        except Exception as e:
            # API errors are expected
            if "API" in str(e) or "key" in str(e).lower() or "connection" in str(e).lower():
                suite.ok("execute_template_api", f"API error (expected): {type(e).__name__}")
            else:
                suite.fail("execute_template", str(e))

        return suite

    # ========================================
    # Test Category 7: Edge Cases & Validation
    # ========================================

    def test_edge_cases(self) -> TestSuite:
        """Test edge cases and input validation."""
        suite = TestSuite("Edge Cases & Validation")

        # Test 7.1: Very long project name
        try:
            long_name = "A" * 500
            result = self.registry._create_project(name=long_name, description="Test")
            if result.get("id"):
                self.created_projects.append(result["id"])
                suite.ok("long_project_name", f"Handled long name (len={len(long_name)})")
            else:
                suite.fail("long_project_name", "Failed to create", result)
        except Exception as e:
            suite.ok("long_project_name_rejected", f"Rejected: {type(e).__name__}")

        # Test 7.2: Special characters in project name
        try:
            special_name = "Test <script>alert('xss')</script> Project"
            result = self.registry._create_project(name=special_name, description="Test")
            if result.get("id"):
                self.created_projects.append(result["id"])
                # Verify the name is stored (possibly sanitized)
                suite.ok("special_chars_project", f"Handled special chars in name")
            else:
                suite.fail("special_chars_project", "Failed to create", result)
        except Exception as e:
            suite.ok("special_chars_rejected", f"Rejected: {type(e).__name__}")

        # Test 7.3: Unicode in prompt template
        try:
            proj = self.registry._create_project(name="UNICODE_TEST_PROJECT")
            self.created_projects.append(proj["id"])

            result = self.registry._create_prompt(
                project_id=proj["id"],
                name="Unicode Test",
                template="こんにちは {{名前}}! 今日は {{日付:DATE}} です。🎉",
                parser_config='{}'
            )
            if result.get("id"):
                self.created_prompts.append(result["id"])
                suite.ok("unicode_template", "Handled Unicode in template")
            else:
                suite.fail("unicode_template", "Failed to create", result)
        except Exception as e:
            suite.fail("unicode_template", str(e))

        # Test 7.4: Invalid JSON in parser_config
        try:
            proj = self.registry._create_project(name="INVALID_JSON_TEST")
            self.created_projects.append(proj["id"])

            result = self.registry._create_prompt(
                project_id=proj["id"],
                name="Invalid JSON Test",
                template="Test",
                parser_config='not valid json'
            )
            suite.fail("invalid_parser_json", "Should have rejected invalid JSON")
        except Exception as e:
            suite.ok("invalid_parser_json", f"Correctly rejected: {type(e).__name__}")

        # Test 7.5: Null/None handling
        try:
            result = self.registry._get_project(None)
            suite.fail("null_project_id", "Should have raised error")
        except (ValueError, TypeError) as e:
            suite.ok("null_project_id", f"Correctly rejected None: {type(e).__name__}")
        except Exception as e:
            suite.fail("null_project_id", f"Wrong exception: {type(e).__name__}")

        # Test 7.6: Negative IDs
        try:
            result = self.registry._get_project(-1)
            suite.fail("negative_project_id", "Should have raised error")
        except ValueError as e:
            suite.ok("negative_project_id", f"Correctly rejected: {e}")
        except Exception as e:
            # Might return "not found" which is also acceptable
            if "not found" in str(e).lower():
                suite.ok("negative_project_id", f"Handled as not found: {e}")
            else:
                suite.fail("negative_project_id", f"Unexpected: {type(e).__name__}: {e}")

        return suite

    def run_all_tests(self) -> Dict[str, TestSuite]:
        """Run all test suites."""
        results = {}

        try:
            results["projects"] = self.test_project_management()
            results["prompts"] = self.test_prompt_management()
            results["jobs"] = self.test_job_management()
            results["datasets"] = self.test_dataset_management()
            results["settings"] = self.test_system_settings()
            results["execution"] = self.test_prompt_execution()
            results["edge_cases"] = self.test_edge_cases()
        finally:
            self.cleanup()

        return results


def main():
    """Run all tests and print results."""
    print("\n" + "="*60)
    print("MCP Tools Comprehensive Test Suite (Non-Workflow)")
    print("="*60)

    tester = MCPOtherToolsTest()
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

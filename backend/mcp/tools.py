"""MCP Tool Definitions for Prompt Evaluation System.

Defines all tools available to AI agents for interacting with the system.
Each tool has:
- name: Unique identifier
- description: What the tool does (shown to LLM)
- parameters: JSON Schema for inputs
- handler: Function that executes the tool
"""

import json
import logging
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from backend.database.database import SessionLocal
from backend.database.models import (
    Project, Prompt, PromptRevision, Workflow, WorkflowStep,
    Job, JobItem, WorkflowJob, SystemSetting, Dataset, ProjectDataset
)
from backend.job import JobManager
from backend.workflow import WorkflowManager
from backend.workflow_validator import validate_workflow, ValidationResult, get_available_variables_at_step
from backend.llm.factory import get_llm_client, get_available_models
from backend.prompt import PromptTemplateParser

logger = logging.getLogger(__name__)


@dataclass
class ToolParameter:
    """Definition of a tool parameter."""
    name: str
    type: str  # string, number, boolean, array, object
    description: str
    required: bool = True
    enum: Optional[List[str]] = None
    default: Any = None
    items: Optional[Dict[str, str]] = None  # For array types: {"type": "string"} or {"type": "integer"}


@dataclass
class ToolDefinition:
    """Definition of an MCP tool."""
    name: str
    description: str
    parameters: List[ToolParameter] = field(default_factory=list)
    handler: Optional[Callable] = None

    def to_json_schema(self) -> Dict[str, Any]:
        """Convert to JSON Schema format for LLM tool calling."""
        properties = {}
        required = []

        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default
            # Add items for array types (required by OpenAI function calling)
            if param.type == "array":
                if param.items:
                    prop["items"] = param.items
                else:
                    # Default to string items if not specified
                    prop["items"] = {"type": "string"}
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }


class MCPToolRegistry:
    """Registry for all MCP tools available to agents."""

    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}
        self._default_model: Optional[str] = None  # Model set by agent session
        self._register_all_tools()

    def _register_all_tools(self):
        """Register all available tools."""
        # Project Management
        self._register_tool(ToolDefinition(
            name="list_projects",
            description="List all projects in the system. Returns project IDs, names, and descriptions.",
            parameters=[],
            handler=self._list_projects
        ))

        self._register_tool(ToolDefinition(
            name="get_project",
            description="Get details of a specific project including its prompts.",
            parameters=[
                ToolParameter("project_id", "number", "The ID of the project to retrieve")
            ],
            handler=self._get_project
        ))

        self._register_tool(ToolDefinition(
            name="create_project",
            description="Create a new project.",
            parameters=[
                ToolParameter("name", "string", "Name of the project"),
                ToolParameter("description", "string", "Description of the project", required=False, default="")
            ],
            handler=self._create_project
        ))

        # Prompt Management
        self._register_tool(ToolDefinition(
            name="list_prompts",
            description="Search for prompts in a project. Returns prompt IDs and names. Use this to FIND prompts BEFORE calling execute_prompt() to run them. This is a search tool, not execution.",
            parameters=[
                ToolParameter("project_id", "number", "The ID of the project")
            ],
            handler=self._list_prompts
        ))

        self._register_tool(ToolDefinition(
            name="get_prompt",
            description="Get details of a specific prompt including its template, parameters, and parser config.",
            parameters=[
                ToolParameter("prompt_id", "number", "The ID of the prompt to retrieve")
            ],
            handler=self._get_prompt
        ))

        self._register_tool(ToolDefinition(
            name="create_prompt",
            description="Create a new prompt in a project. For regular prompts: Use {{PARAM_NAME}} or {{PARAM_NAME:TYPE}} syntax. Types: TEXT5, TEXT10, NUM, DATE, DATETIME, FILE, FILEPATH. For FOREACH loop prompts: Use {{vars.ROW.column_name}} to reference dataset values. Example: {{vars.ROW.question_stem}}, {{vars.ROW.choices}}. IMPORTANT: Never use {{PARAM:TYPE}} in FOREACH prompts - always use {{vars.ROW.xxx}}!",
            parameters=[
                ToolParameter("project_id", "number", "The ID of the project"),
                ToolParameter("name", "string", "Name of the prompt"),
                ToolParameter("template", "string", "The prompt template with {{}} parameters"),
                ToolParameter("parser_config", "object", "Parser configuration as dict. Example: {\"type\": \"regex\", \"patterns\": {\"ANSWER\": \"[A-D]\"}}. Pass as dict, NOT as JSON string, to avoid escaping issues.", required=False),
                ToolParameter("upsert", "boolean", "If True, update existing prompt with same name instead of failing. Useful for retrying after errors.", required=False, default=False)
            ],
            handler=self._create_prompt
        ))

        self._register_tool(ToolDefinition(
            name="analyze_template",
            description="Analyze a prompt template to extract parameter definitions. Returns parameter names, types, and whether they are required.",
            parameters=[
                ToolParameter("template", "string", "The prompt template to analyze")
            ],
            handler=self._analyze_template
        ))

        # Project Update/Delete
        self._register_tool(ToolDefinition(
            name="update_project",
            description="Update a project's name and/or description.",
            parameters=[
                ToolParameter("project_id", "number", "The ID of the project to update"),
                ToolParameter("name", "string", "New name for the project", required=False),
                ToolParameter("description", "string", "New description for the project", required=False)
            ],
            handler=self._update_project
        ))

        self._register_tool(ToolDefinition(
            name="delete_project",
            description="Soft delete a project (marks as deleted, can be restored later with restore_project).",
            parameters=[
                ToolParameter("project_id", "number", "The ID of the project to delete")
            ],
            handler=self._delete_project
        ))

        self._register_tool(ToolDefinition(
            name="delete_projects",
            description="Soft delete multiple projects at once (marks as deleted, can be restored later).",
            parameters=[
                ToolParameter("project_ids", "array", "List of project IDs to delete", items={"type": "integer"})
            ],
            handler=self._delete_projects
        ))

        self._register_tool(ToolDefinition(
            name="list_deleted_projects",
            description="List all soft-deleted projects. Use this to find projects that can be restored.",
            parameters=[],
            handler=self._list_deleted_projects
        ))

        self._register_tool(ToolDefinition(
            name="restore_project",
            description="Restore a soft-deleted project. The project becomes active again.",
            parameters=[
                ToolParameter("project_id", "number", "The ID of the deleted project to restore")
            ],
            handler=self._restore_project
        ))

        # Prompt Update/Delete
        self._register_tool(ToolDefinition(
            name="update_prompt",
            description="""Update a prompt's name, template, or parser config. Creates a new revision.

PARSER CONFIG FORMATS:
1. JSON extraction: "json" - Parse entire response as JSON
2. JSON path: "json_path:$.field.name" - Extract specific field from JSON
3. Regex: "regex:(?P<name>pattern)" - Named groups become output fields
4. CSV template: "csv_template:$field1,$field2" - Extract fields for CSV output
5. None/empty: Raw response, no parsing

EXAMPLES:
- parser_config="json" -> Parse as JSON, all keys become fields
- parser_config="json_path:$.result" -> Extract 'result' from JSON
- parser_config="regex:Score: (?P<score>\\d+)" -> Extract 'score' field
- parser_config="csv_template:$topic,$summary" -> CSV with topic,summary columns

Use get_prompt to see current parser_config before updating.""",
            parameters=[
                ToolParameter("prompt_id", "number", "The ID of the prompt to update"),
                ToolParameter("name", "string", "New name for the prompt", required=False),
                ToolParameter("template", "string", "New template content", required=False),
                ToolParameter("parser_config", "string", "New parser configuration (see description for formats)", required=False)
            ],
            handler=self._update_prompt
        ))

        self._register_tool(ToolDefinition(
            name="delete_prompt",
            description="Delete a prompt and all its revisions. WARNING: This is irreversible.",
            parameters=[
                ToolParameter("prompt_id", "number", "The ID of the prompt to delete")
            ],
            handler=self._delete_prompt
        ))

        self._register_tool(ToolDefinition(
            name="clone_prompt",
            description="Clone a prompt with all its revisions (including parser config). Creates a new prompt with the same content.",
            parameters=[
                ToolParameter("prompt_id", "number", "The ID of the prompt to clone"),
                ToolParameter("new_name", "string", "Name for the cloned prompt"),
                ToolParameter("copy_revisions", "boolean", "If True, copy all revisions; if False, only copy latest", required=False, default=True)
            ],
            handler=self._clone_prompt
        ))

        self._register_tool(ToolDefinition(
            name="set_parser_csvoutput",
            description="""Auto-configure parser for CSV output based on JSON structure.
Detects JSON example in prompt template and generates json_path parser config automatically.

How it works:
1. Get latest revision for prompt_id
2. If json_sample not provided, auto-detect JSON from prompt template
3. Extract all leaf paths from JSON structure
4. Save parser config as new revision

Example output:
{
  "type": "json_path",
  "paths": {"answer": "$.answer", "reason": "$.reason"},
  "csv_template": "\\"$answer$\\",\\"$reason$\\""
}

Use this after creating a prompt that outputs JSON to automatically set up CSV-compatible parsing.""",
            parameters=[
                ToolParameter("prompt_id", "number", "The ID of the prompt to configure"),
                ToolParameter("json_sample", "string", "JSON example (auto-detected from template if not provided)", required=False)
            ],
            handler=self._set_parser_csvoutput
        ))

        self._register_tool(ToolDefinition(
            name="clone_workflow",
            description="Clone a workflow with all its steps. Creates a new workflow with the same configuration.",
            parameters=[
                ToolParameter("workflow_id", "number", "The ID of the workflow to clone"),
                ToolParameter("new_name", "string", "Name for the cloned workflow")
            ],
            handler=self._clone_workflow
        ))

        # Prompt Execution
        self._register_tool(ToolDefinition(
            name="execute_prompt",
            description="Execute a prompt with given input parameters. Returns the LLM response and parsed output.",
            parameters=[
                ToolParameter("prompt_id", "number", "The ID of the prompt to execute"),
                ToolParameter("input_params", "object", "Dictionary of parameter name -> value"),
                ToolParameter("model_name", "string", "LLM model to use", required=False),
                ToolParameter("temperature", "number", "Temperature for LLM (0.0-2.0)", required=False, default=0.7),
                ToolParameter("repeat", "number", "Number of times to repeat execution (1-10)", required=False, default=1)
            ],
            handler=self._execute_prompt
        ))

        self._register_tool(ToolDefinition(
            name="execute_template",
            description="Execute a prompt template directly without saving. Useful for one-off executions.",
            parameters=[
                ToolParameter("template", "string", "The prompt template to execute"),
                ToolParameter("input_params", "object", "Dictionary of parameter name -> value"),
                ToolParameter("model_name", "string", "LLM model to use", required=False),
                ToolParameter("temperature", "number", "Temperature for LLM (0.0-2.0)", required=False, default=0.7)
            ],
            handler=self._execute_template
        ))

        self._register_tool(ToolDefinition(
            name="execute_batch",
            description="Execute a prompt with a dataset (batch execution). Each row in the dataset becomes input parameters for the prompt. Returns job_id for tracking progress.",
            parameters=[
                ToolParameter("prompt_id", "number", "The ID of the prompt to execute"),
                ToolParameter("dataset_id", "number", "The ID of the dataset to use for batch execution"),
                ToolParameter("model_name", "string", "LLM model to use", required=False),
                ToolParameter("temperature", "number", "Temperature for LLM (0.0-2.0)", required=False, default=0.7)
            ],
            handler=self._execute_batch
        ))

        # Workflow Management
        self._register_tool(ToolDefinition(
            name="list_workflows",
            description="Search for workflows in the system. Use this to FIND workflows BEFORE calling execute_workflow() to run them. This is a search tool, not execution.",
            parameters=[],
            handler=self._list_workflows
        ))

        self._register_tool(ToolDefinition(
            name="get_workflow",
            description="Get details of a workflow including its steps, configuration, and required_params (list of input parameter names needed for execution). Always call this before execute_workflow.",
            parameters=[
                ToolParameter("workflow_id", "number", "The ID of the workflow")
            ],
            handler=self._get_workflow
        ))

        self._register_tool(ToolDefinition(
            name="execute_workflow",
            description="""Execute a workflow with given input parameters. Returns all step outputs including csv_markdown_link for clickable download.

CRITICAL REQUIREMENTS:
1. ALWAYS call get_workflow FIRST to get required_params list
2. If required_params is NOT empty, provide ALL of them in input_params
3. If required_params IS empty (e.g., FOREACH-based workflows), you can omit input_params or pass {}
4. If user says 'use any input' or 'appropriate input', YOU MUST generate meaningful sample data
5. Use substantial Japanese text (3-5 sentences) for text parameters

EXAMPLE - If required_params=['INPUT_TEXT']:
input_params={"INPUT_TEXT": "人工知能と機械学習は現代のテクノロジーの中核となっています。自然言語処理、画像認識、自動運転など多くの分野で活用されています。これらの技術は日々進化し続けており、私たちの生活を大きく変えています。"}

EXAMPLE - If required_params=[] (FOREACH-based workflow):
Just call: execute_workflow(workflow_id=130) - NO input_params needed

When presenting results to user, use csv_markdown_link field for clickable CSV download link.""",
            parameters=[
                ToolParameter("workflow_id", "number", "The ID of the workflow to execute"),
                ToolParameter("input_params", "object", "Dictionary of parameter name -> value. Provide ALL required_params from get_workflow. Can be empty {} or omitted for workflows without input parameters (e.g., FOREACH-based workflows).", required=False),
                ToolParameter("model_name", "string", "LLM model to use", required=False),
                ToolParameter("temperature", "number", "Temperature for LLM (0.0-2.0)", required=False, default=0.7)
            ],
            handler=self._execute_workflow
        ))

        # Workflow CRUD
        self._register_tool(ToolDefinition(
            name="create_workflow",
            description="Create a new workflow. If project_id is not specified, the first available project will be automatically assigned as the default.",
            parameters=[
                ToolParameter("name", "string", "Name of the workflow"),
                ToolParameter("description", "string", "Description of the workflow", required=False, default=""),
                ToolParameter("project_id", "number", "Associated project ID (auto-assigned to first project if not specified)", required=False)
            ],
            handler=self._create_workflow
        ))

        self._register_tool(ToolDefinition(
            name="update_workflow",
            description="Update a workflow's name, description, or associated project.",
            parameters=[
                ToolParameter("workflow_id", "number", "The ID of the workflow to update"),
                ToolParameter("name", "string", "New name for the workflow", required=False),
                ToolParameter("description", "string", "New description", required=False),
                ToolParameter("project_id", "number", "New associated project ID", required=False)
            ],
            handler=self._update_workflow
        ))

        self._register_tool(ToolDefinition(
            name="delete_workflow",
            description="Soft delete a workflow (marks as deleted, can be restored later with restore_workflow).",
            parameters=[
                ToolParameter("workflow_id", "number", "The ID of the workflow to delete")
            ],
            handler=self._delete_workflow
        ))

        self._register_tool(ToolDefinition(
            name="list_deleted_workflows",
            description="List all soft-deleted workflows. Use this to find workflows that can be restored.",
            parameters=[],
            handler=self._list_deleted_workflows
        ))

        self._register_tool(ToolDefinition(
            name="restore_workflow",
            description="Restore a soft-deleted workflow. Note: Cannot restore if parent project is deleted.",
            parameters=[
                ToolParameter("workflow_id", "number", "The ID of the deleted workflow to restore")
            ],
            handler=self._restore_workflow
        ))

        # Workflow Step Management
        self._register_tool(ToolDefinition(
            name="add_workflow_step",
            description="Add a new step to a workflow. IMPORTANT: Use 'insert_after' instead of 'step_order' when adding steps inside IF/ELSE/FOREACH blocks. For set/loop/if steps, condition_config is also REQUIRED.",
            parameters=[
                ToolParameter("workflow_id", "number", "The ID of the workflow"),
                ToolParameter("step_name", "string", "Name for the step"),
                ToolParameter("step_type", "string", "REQUIRED. Type: prompt, set, if, elif, else, endif, loop, endloop, foreach, endforeach, break, continue"),
                ToolParameter("prompt_id", "number", "Prompt ID (required for prompt type steps)", required=False),
                ToolParameter("insert_after", "string", "RECOMMENDED for control flow. Step name to insert after. Use for: then-branch (insert_after='{if_name}'), else-branch (insert_after='{if_name}_else'), loop body (insert_after='{foreach_name}')", required=False),
                ToolParameter("step_order", "number", "Direct position (use insert_after instead for control flow blocks)", required=False),
                ToolParameter("input_mapping", "object", "Maps prompt parameters to values. Example: {\"INPUT\":\"{{step1.FIELD}}\",\"THEME\":\"{{vars.theme}}\"}", required=False),
                ToolParameter("condition_config", "object", "REQUIRED for set/loop/if/foreach steps. Pass as dict. set: {\"assignments\":{\"var\":\"value\"}}. loop: {\"left\":\"{{vars.counter}}\",\"operator\":\"<\",\"right\":\"10\"}", required=False)
            ],
            handler=self._add_workflow_step
        ))

        self._register_tool(ToolDefinition(
            name="update_workflow_step",
            description="Update an existing workflow step.",
            parameters=[
                ToolParameter("step_id", "number", "The ID of the step to update"),
                ToolParameter("step_name", "string", "New name for the step", required=False),
                ToolParameter("step_type", "string", "New step type", required=False),
                ToolParameter("prompt_id", "number", "New prompt ID", required=False),
                ToolParameter("step_order", "number", "New position", required=False),
                ToolParameter("input_mapping", "object", "Maps prompt parameters to values", required=False),
                ToolParameter("condition_config", "string", "New control flow configuration (JSON string)", required=False)
            ],
            handler=self._update_workflow_step
        ))

        self._register_tool(ToolDefinition(
            name="delete_workflow_step",
            description="""Delete a step from a workflow. No confirmation required - deletion is immediate.

IMPORTANT: Use the step's 'id' field (database ID), NOT 'step_order'.

Example workflow:
1. get_workflow(workflow_id=5) -> returns steps like:
   {"steps": [{"id": 45, "step_order": 0, "step_name": "init"}, {"id": 46, "step_order": 1, ...}]}
2. delete_workflow_step(step_id=45) -> deletes the step with id=45

After deletion, remaining steps are automatically renumbered.""",
            parameters=[
                ToolParameter("step_id", "number", "The 'id' field of the step to delete (from get_workflow, NOT step_order)")
            ],
            handler=self._delete_workflow_step
        ))

        # Control Flow Block Tools (automatically create matching open/close pairs)
        self._register_tool(ToolDefinition(
            name="add_foreach_block",
            description="""Add a FOREACH loop block to a workflow. This automatically creates both FOREACH and ENDFOREACH steps.

You can add steps inside the loop by specifying step_order between the FOREACH and ENDFOREACH positions.

Example usage:
  add_foreach_block(workflow_id=5, foreach_name="loop_rows", source="dataset:6:limit:10", item_var="ROW")
  -> Creates: [foreach_name] (FOREACH) and [foreach_name]_end (ENDFOREACH)

After calling this, add steps inside the loop using add_workflow_step with step_order between the FOREACH and ENDFOREACH.""",
            parameters=[
                ToolParameter("workflow_id", "number", "The ID of the workflow"),
                ToolParameter("foreach_name", "string", "Base name for the FOREACH step (e.g., 'loop_rows'). ENDFOREACH will be named '<name>_end'"),
                ToolParameter("source", "string", "Data source. Format: 'dataset:ID:limit:N' for datasets, or '{{stepName.FIELD}}' for step output"),
                ToolParameter("item_var", "string", "Variable name for each item (e.g., 'ROW'). Access fields via {{vars.ROW.fieldName}}"),
                ToolParameter("step_order", "number", "Position for FOREACH step (0-based). If not specified, appends to end.", required=False)
            ],
            handler=self._add_foreach_block
        ))

        self._register_tool(ToolDefinition(
            name="add_if_block",
            description="""Add an IF block to a workflow. This automatically creates IF, optional ELSE, and ENDIF steps.

Example usage:
  add_if_block(workflow_id=5, if_name="check_answer", left="{{ask.parsed.ANSWER}}", operator="==", right="{{vars.ROW.answerKey}}", include_else=True)
  -> Creates: [if_name] (IF), [if_name]_else (ELSE), [if_name]_end (ENDIF)

After calling this, add steps inside the IF/ELSE blocks using add_workflow_step with appropriate step_order.

IMPORTANT: Replace 'ask' in the example with YOUR ACTUAL STEP NAME that you created!""",
            parameters=[
                ToolParameter("workflow_id", "number", "The ID of the workflow"),
                ToolParameter("if_name", "string", "Base name for the IF step (e.g., 'check_answer'). ELSE will be '<name>_else', ENDIF will be '<name>_end'"),
                ToolParameter("left", "string", "Left side of condition (e.g., '{{stepName.parsed.ANSWER}}')"),
                ToolParameter("operator", "string", "Comparison operator: ==, !=, <, <=, >, >=, contains, startswith, endswith"),
                ToolParameter("right", "string", "Right side of condition (e.g., '{{vars.ROW.answerKey}}')"),
                ToolParameter("include_else", "boolean", "If true, creates ELSE block between IF and ENDIF", required=False),
                ToolParameter("step_order", "number", "Position for IF step (0-based). If not specified, appends to end.", required=False)
            ],
            handler=self._add_if_block
        ))

        # Workflow Validation
        self._register_tool(ToolDefinition(
            name="validate_workflow",
            description="""Validate a workflow's integrity and configuration.

Checks for:
- Control flow integrity (IF/ENDIF, LOOP/ENDLOOP, FOREACH/ENDFOREACH pairs)
- Formula/function syntax validation
- Variable and step reference validation
- Required parameter and configuration validation
- Prompt step configuration

Returns validation result with any errors or warnings found.
If validation fails, the issues must be fixed before workflow execution will succeed.""",
            parameters=[
                ToolParameter("workflow_id", "number", "The ID of the workflow to validate")
            ],
            handler=self._validate_workflow
        ))

        # Get Available Variables at Step
        self._register_tool(ToolDefinition(
            name="get_available_variables",
            description="""Get all available variables and functions at a specific workflow step.

Use this tool before building workflow steps to understand what variables can be referenced
in input_mapping or condition_config.

Returns:
- Input variables (from workflow initial input)
- Workflow variables (from SET steps before this step)
- FOREACH context (item_var, index_var, and dataset columns if inside a FOREACH loop)
- Previous step outputs (parser fields from earlier prompt steps)
- Available functions

Example: get_available_variables(workflow_id=5, step_order=3)

If inside a FOREACH loop with source="dataset:6" and item_var="ROW":
- {{vars.ROW}} - full row object
- {{vars.ROW.question}} - question column from dataset
- {{vars.ROW.choices}} - choices column from dataset
- {{vars.i}} - loop index (0-based)

This helps you correctly configure input_mapping with valid variable references.""",
            parameters=[
                ToolParameter("workflow_id", "number", "The ID of the workflow"),
                ToolParameter("step_order", "number", "The step order (1-based) to check variables for")
            ],
            handler=self._get_available_variables
        ))

        # Job Management
        self._register_tool(ToolDefinition(
            name="get_job_status",
            description="Get the status and results of a job.",
            parameters=[
                ToolParameter("job_id", "number", "The ID of the job")
            ],
            handler=self._get_job_status
        ))

        self._register_tool(ToolDefinition(
            name="list_recent_jobs",
            description="List recent jobs with their status and basic info.",
            parameters=[
                ToolParameter("limit", "number", "Maximum number of jobs to return", required=False, default=10),
                ToolParameter("project_id", "number", "Filter by project ID", required=False)
            ],
            handler=self._list_recent_jobs
        ))

        self._register_tool(ToolDefinition(
            name="cancel_job",
            description="Cancel a running job. Only pending items can be cancelled.",
            parameters=[
                ToolParameter("job_id", "number", "The ID of the job to cancel")
            ],
            handler=self._cancel_job
        ))

        self._register_tool(ToolDefinition(
            name="export_job_csv",
            description="Get a CSV download link for job results. Auto-detects workflow vs regular jobs. IMPORTANT: When presenting the result to users, use the 'markdown_link' field which contains a clickable hyperlink format like [CSVダウンロード](http://...).",
            parameters=[
                ToolParameter("job_id", "number", "The ID of the job to export (auto-detects if workflow or regular job)"),
                ToolParameter("is_workflow_job", "boolean", "Optional: True if this is a workflow job. If not specified, auto-detection is used.", required=False, default=False)
            ],
            handler=self._export_job_csv
        ))

        # Dataset Management
        self._register_tool(ToolDefinition(
            name="list_datasets",
            description="List all datasets in the system. Returns dataset IDs, names, project associations, and source file names.",
            parameters=[
                ToolParameter("project_id", "number", "Filter by project ID (optional)", required=False)
            ],
            handler=self._list_datasets
        ))

        self._register_tool(ToolDefinition(
            name="get_dataset",
            description="Get details of a specific dataset including column information and row count.",
            parameters=[
                ToolParameter("dataset_id", "number", "The ID of the dataset to retrieve")
            ],
            handler=self._get_dataset
        ))

        self._register_tool(ToolDefinition(
            name="search_datasets",
            description="Search datasets by name or source file name. Returns matching datasets.",
            parameters=[
                ToolParameter("query", "string", "Search query to match against dataset name or source file name")
            ],
            handler=self._search_datasets
        ))

        self._register_tool(ToolDefinition(
            name="search_dataset_content",
            description="Search within a dataset's data rows. Searches all columns for the query string and returns matching rows.",
            parameters=[
                ToolParameter("dataset_id", "number", "The ID of the dataset to search in"),
                ToolParameter("query", "string", "Search query to find in any column"),
                ToolParameter("column", "string", "Specific column to search (optional, searches all if not specified)", required=False),
                ToolParameter("limit", "number", "Maximum number of rows to return (default: 20)", required=False)
            ],
            handler=self._search_dataset_content
        ))

        self._register_tool(ToolDefinition(
            name="preview_dataset_rows",
            description="Preview rows from a dataset with pagination. Useful for viewing specific records by offset and limit.",
            parameters=[
                ToolParameter("dataset_id", "number", "The ID of the dataset to preview"),
                ToolParameter("offset", "number", "Starting row index (0-based, default: 0)", required=False),
                ToolParameter("limit", "number", "Number of rows to return (default: 10, max: 100)", required=False)
            ],
            handler=self._preview_dataset_rows
        ))

        self._register_tool(ToolDefinition(
            name="execute_batch_with_filter",
            description="Execute a prompt with filtered dataset rows. Only rows containing the filter query will be used for execution.",
            parameters=[
                ToolParameter("prompt_id", "number", "The ID of the prompt to execute"),
                ToolParameter("dataset_id", "number", "The ID of the dataset to use"),
                ToolParameter("filter_query", "string", "Filter query - only rows containing this text in any column will be used"),
                ToolParameter("filter_column", "string", "Specific column to filter (optional, searches all if not specified)", required=False),
                ToolParameter("model_name", "string", "LLM model to use", required=False),
                ToolParameter("temperature", "number", "Temperature for LLM (0.0-2.0)", required=False, default=0.7)
            ],
            handler=self._execute_batch_with_filter
        ))

        # Dataset-Project Association Management
        self._register_tool(ToolDefinition(
            name="get_dataset_projects",
            description="Get list of projects associated with a dataset. Returns owner and all associated projects.",
            parameters=[
                ToolParameter("dataset_id", "number", "The ID of the dataset")
            ],
            handler=self._get_dataset_projects
        ))

        self._register_tool(ToolDefinition(
            name="update_dataset_projects",
            description="Update the list of projects associated with a dataset. Replaces all associations (owner is always included).",
            parameters=[
                ToolParameter("dataset_id", "number", "The ID of the dataset"),
                ToolParameter("project_ids", "array", "List of project IDs to associate with the dataset", items={"type": "integer"})
            ],
            handler=self._update_dataset_projects
        ))

        self._register_tool(ToolDefinition(
            name="add_dataset_to_project",
            description="Add a dataset to a project (create association). Dataset can belong to multiple projects.",
            parameters=[
                ToolParameter("dataset_id", "number", "The ID of the dataset"),
                ToolParameter("project_id", "number", "The ID of the project to add the dataset to")
            ],
            handler=self._add_dataset_to_project
        ))

        self._register_tool(ToolDefinition(
            name="remove_dataset_from_project",
            description="Remove a dataset from a project (remove association). Cannot remove owner project.",
            parameters=[
                ToolParameter("dataset_id", "number", "The ID of the dataset"),
                ToolParameter("project_id", "number", "The ID of the project to remove the dataset from")
            ],
            handler=self._remove_dataset_from_project
        ))

        # Hugging Face Dataset Tools
        self._register_tool(ToolDefinition(
            name="search_huggingface_datasets",
            description="""Search for datasets on Hugging Face Hub by keyword.

Examples:
- query="japanese" → 日本語データセット
- query="question answering" → QAデータセット
- query="sentiment analysis" → 感情分析データセット

Returns: List of matching datasets with name, description, downloads, likes.""",
            parameters=[
                ToolParameter("query", "string", "Search keyword (e.g., 'question answering', 'japanese nlp')"),
                ToolParameter("limit", "number", "Max results (default: 10, max: 50)", required=False, default=10)
            ],
            handler=self._search_huggingface_datasets
        ))

        self._register_tool(ToolDefinition(
            name="get_huggingface_dataset_info",
            description="""Get detailed information about a Hugging Face dataset.

Use this after search to get:
- Available splits (train, validation, test)
- Column names and types
- Row counts per split
- Whether authentication is required (gated)

Example: name="squad" or name="username/dataset-name" """,
            parameters=[
                ToolParameter("name", "string", "Dataset name (e.g., 'squad', 'username/dataset')")
            ],
            handler=self._get_huggingface_dataset_info
        ))

        self._register_tool(ToolDefinition(
            name="preview_huggingface_dataset",
            description="Preview sample rows from a Hugging Face dataset before importing.",
            parameters=[
                ToolParameter("name", "string", "Dataset name"),
                ToolParameter("split", "string", "Split to preview (e.g., 'train', 'validation')"),
                ToolParameter("limit", "number", "Number of rows to preview", required=False, default=5)
            ],
            handler=self._preview_huggingface_dataset
        ))

        self._register_tool(ToolDefinition(
            name="import_huggingface_dataset",
            description="""Import a Hugging Face dataset into the system.

WORKFLOW:
1. Use search_huggingface_datasets to find datasets
2. Use get_huggingface_dataset_info to check splits and columns
3. Use preview_huggingface_dataset to verify data
4. Use import_huggingface_dataset to import

Parameters:
- project_id: Target project (use list_projects to find)
- dataset_name: HuggingFace dataset ID (e.g., 'squad', 'imdb')
- split: Which split to import (e.g., 'train', 'validation')
- display_name: Name for the imported dataset
- row_limit: Optional limit (None = import all)
- columns: Optional list of columns (None = all columns)""",
            parameters=[
                ToolParameter("project_id", "number", "Target project ID"),
                ToolParameter("dataset_name", "string", "HuggingFace dataset name"),
                ToolParameter("split", "string", "Split to import (train, validation, test)"),
                ToolParameter("display_name", "string", "Display name for imported dataset"),
                ToolParameter("row_limit", "number", "Max rows to import (None for all)", required=False),
                ToolParameter("columns", "array", "Columns to import (None for all)", required=False)
            ],
            handler=self._import_huggingface_dataset
        ))

        # System Information
        self._register_tool(ToolDefinition(
            name="list_models",
            description="List all available LLM models with their default parameters.",
            parameters=[],
            handler=self._list_models
        ))

        self._register_tool(ToolDefinition(
            name="get_system_settings",
            description="Get current system settings.",
            parameters=[],
            handler=self._get_system_settings
        ))

        self._register_tool(ToolDefinition(
            name="set_default_model",
            description="Set the default LLM model for execute_workflow and execute_prompt. This model will be used when no model is explicitly specified.",
            parameters=[
                ToolParameter("model_name", "string", "The model name to use as default (e.g., 'azure-gpt-4.1', 'gpt-4o-mini')")
            ],
            handler=self._set_default_model
        ))

        # Help Tool
        self._register_tool(ToolDefinition(
            name="help",
            description="""Display help for MCP tools and system rules.

Usage:
- help() - Show all tools and topic list
- help(topic="tool_name") - Show details of a specific tool
- help(topic="workflow") - Show workflow rules overview
- help(topic="workflow", entry="foreach") - Show FOREACH step details

Available topics:
- workflow: Step types, variables, operators
- functions: Workflow functions (28 types)
- prompt: Prompt template syntax
- parser: Parser configuration
- dataset_ref: Dataset reference syntax

Examples:
- help() → All tools and topics
- help(topic="create_workflow") → Details of create_workflow tool
- help(topic="functions", entry="calc") → How to use calc function""",
            parameters=[
                ToolParameter("topic", "string", "Tool name or topic name (workflow, functions, prompt, parser, dataset_ref)", required=False),
                ToolParameter("entry", "string", "Entry name within topic (e.g., foreach, calc, TEXT)", required=False)
            ],
            handler=self._help
        ))

    def _register_tool(self, tool: ToolDefinition):
        """Register a tool in the registry."""
        self.tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool by name."""
        return self.tools.get(name)

    def get_all_tools(self) -> List[ToolDefinition]:
        """Get all registered tools."""
        return list(self.tools.values())

    def get_tools_json_schema(self) -> List[Dict[str, Any]]:
        """Get all tools in JSON Schema format for LLM tool calling."""
        return [tool.to_json_schema() for tool in self.tools.values()]

    async def execute_tool(self, name: str, arguments: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute a tool by name with given arguments.

        Args:
            name: Tool name to execute
            arguments: Tool arguments
            context: Optional context with session info (e.g., {"default_model": "azure-gpt-5-mini"})
        """
        tool = self.get_tool(name)
        if not tool:
            return {"error": f"Tool '{name}' not found"}

        if not tool.handler:
            return {"error": f"Tool '{name}' has no handler"}

        # Store context for tool handlers to access
        self._current_context = context or {}

        try:
            result = tool.handler(**arguments)
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
        finally:
            self._current_context = {}

    def _get_default_model(self) -> Optional[str]:
        """Get default model from stored value, current context, or None."""
        # First check stored default model (set by set_default_model tool)
        if self._default_model:
            return self._default_model
        # Fall back to context (if passed through execute_tool)
        return getattr(self, '_current_context', {}).get('default_model')

    def _set_default_model(self, model_name: str) -> Dict:
        """Set the default model for execute_workflow and execute_prompt."""
        # Validate model exists
        available_models = get_available_models()
        model_names = [m['name'] for m in available_models]

        if model_name not in model_names:
            return {
                "success": False,
                "error": f"Model '{model_name}' not found. Available models: {', '.join(model_names)}"
            }

        self._default_model = model_name
        logger.info(f"Default model set to: {model_name}")
        return {
            "success": True,
            "message": f"Default model set to '{model_name}'. This model will be used for execute_workflow and execute_prompt when no model is explicitly specified."
        }

    # ============== Tool Handlers ==============

    def _list_projects(self) -> List[Dict]:
        """List all active projects (excluding soft-deleted)."""
        db = SessionLocal()
        try:
            projects = db.query(Project).filter(
                Project.is_deleted == 0
            ).order_by(Project.id.desc()).all()
            result = []
            for p in projects:
                created_at = p.created_at
                if created_at:
                    # Handle both datetime objects and strings
                    if hasattr(created_at, 'isoformat'):
                        created_at = created_at.isoformat()
                    else:
                        created_at = str(created_at)
                result.append({
                    "id": p.id,
                    "name": p.name,
                    "description": p.description or "",
                    "created_at": created_at
                })
            return result
        finally:
            db.close()

    def _get_project(self, project_id: int) -> Dict:
        """Get project details."""
        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise ValueError(f"Project {project_id} not found")

            prompts = db.query(Prompt).filter(
                Prompt.project_id == project_id,
                Prompt.is_deleted == 0
            ).all()

            prompt_list = []
            for p in prompts:
                # Get latest revision for template preview
                latest_rev = db.query(PromptRevision).filter(
                    PromptRevision.prompt_id == p.id
                ).order_by(PromptRevision.revision.desc()).first()
                template = latest_rev.prompt_template if latest_rev else ""
                prompt_list.append({
                    "id": p.id,
                    "name": p.name,
                    "template_preview": template[:100] + "..." if len(template) > 100 else template
                })

            return {
                "id": project.id,
                "name": project.name,
                "description": project.description or "",
                "prompts": prompt_list
            }
        finally:
            db.close()

    def _create_project(self, name: str, description: str = "") -> Dict:
        """Create a new project."""
        # Validate project name
        if not name or not name.strip():
            raise ValueError("Project name cannot be empty")

        db = SessionLocal()
        try:
            project = Project(name=name, description=description)
            db.add(project)
            db.commit()
            db.refresh(project)
            return {"id": project.id, "name": project.name}
        finally:
            db.close()

    def _list_prompts(self, project_id: int) -> List[Dict]:
        """List prompts in a project."""
        db = SessionLocal()
        try:
            prompts = db.query(Prompt).filter(
                Prompt.project_id == project_id,
                Prompt.is_deleted == 0
            ).all()
            result = []
            for p in prompts:
                # Get latest revision for template preview
                latest_rev = db.query(PromptRevision).filter(
                    PromptRevision.prompt_id == p.id
                ).order_by(PromptRevision.revision.desc()).first()
                template = latest_rev.prompt_template if latest_rev else ""
                result.append({
                    "id": p.id,
                    "name": p.name,
                    "template_preview": template[:100] + "..." if len(template) > 100 else template
                })
            return result
        finally:
            db.close()

    def _get_prompt(self, prompt_id: int) -> Dict:
        """Get prompt details."""
        db = SessionLocal()
        try:
            prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
            if not prompt:
                raise ValueError(f"Prompt {prompt_id} not found")

            # Get latest revision
            latest_rev = db.query(PromptRevision).filter(
                PromptRevision.prompt_id == prompt_id
            ).order_by(PromptRevision.revision.desc()).first()

            template = latest_rev.prompt_template if latest_rev else ""
            parser_config = latest_rev.parser_config if latest_rev else ""

            # Parse parameters from template
            parser = PromptTemplateParser()
            params = parser.parse_template(template)

            return {
                "id": prompt.id,
                "name": prompt.name,
                "template": template,
                "parser_config": parser_config,
                "revision": latest_rev.revision if latest_rev else 0,
                "parameters": [{
                    "name": p.name,
                    "type": p.type,
                    "required": p.required
                } for p in params]
            }
        finally:
            db.close()

    def _create_prompt(self, project_id: int, name: str, template: str,
                       parser_config: Any = None, upsert: bool = False) -> Dict:
        """Create a new prompt.

        Parameters:
            project_id: Project ID to create the prompt in
            name: Name of the prompt
            template: Prompt template text
            parser_config: Parser configuration. Can be:
                          - Dict: {"type": "regex", "patterns": {"ANSWER": "[A-D]"}}
                          - JSON string: '{"type": "regex", ...}'
                          - Empty/None: No parsing
            upsert: If True, update existing prompt with same name instead of failing
                   Useful when retrying after errors.

        Returns:
            Dict with id, name, revision_id, and created (True) or updated (False)
        """
        # Validate prompt name
        if not name or not name.strip():
            raise ValueError("Prompt name cannot be empty")

        # Normalize parser_config: accept dict, JSON string, or shorthand format
        parser_config_str = ""
        if parser_config is not None and parser_config != "":
            if isinstance(parser_config, dict):
                parser_config_str = json.dumps(parser_config, ensure_ascii=False)
            elif isinstance(parser_config, str) and parser_config.strip():
                # First try to convert shorthand format
                converted = self._convert_parser_config_shorthand(parser_config)
                # Validate it's valid JSON
                try:
                    json.loads(converted)
                    parser_config_str = converted
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"Invalid parser_config: {e}. "
                        f"TIP: Use shorthand formats like 'json', 'json_path:$.field', 'regex:pattern', "
                        f"or pass parser_config as a dict. "
                        f"Example: parser_config={{\"type\": \"regex\", \"patterns\": {{\"ANSWER\": \"[A-D]\"}}}}"
                    )

        db = SessionLocal()
        try:
            # Verify project exists
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # Check if prompt with same name exists
            existing_prompt = db.query(Prompt).filter(
                Prompt.project_id == project_id,
                Prompt.name == name
            ).first()

            if existing_prompt:
                if not upsert:
                    raise ValueError(
                        f"Prompt '{name}' already exists in project {project_id} (id: {existing_prompt.id}). "
                        f"Use upsert=True to update it, or use a different name."
                    )
                # Update existing prompt with new revision
                prompt = existing_prompt
                # Get latest revision number
                latest_rev = db.query(PromptRevision).filter(
                    PromptRevision.prompt_id == prompt.id
                ).order_by(PromptRevision.revision.desc()).first()
                new_rev_num = (latest_rev.revision + 1) if latest_rev else 1

                revision = PromptRevision(
                    prompt_id=prompt.id,
                    revision=new_rev_num,
                    prompt_template=template,
                    parser_config=parser_config_str
                )
                db.add(revision)
                db.commit()

                return {
                    "id": prompt.id,
                    "name": prompt.name,
                    "revision_id": revision.id,
                    "created": False,
                    "message": f"Updated existing prompt '{name}' with new revision {new_rev_num}"
                }
            else:
                # Create new prompt
                prompt = Prompt(
                    project_id=project_id,
                    name=name
                )
                db.add(prompt)
                db.commit()
                db.refresh(prompt)

                # Create initial revision with template and parser_config
                revision = PromptRevision(
                    prompt_id=prompt.id,
                    revision=1,
                    prompt_template=template,
                    parser_config=parser_config_str
                )
                db.add(revision)
                db.commit()

                return {
                    "id": prompt.id,
                    "name": prompt.name,
                    "revision_id": revision.id,
                    "created": True
                }
        finally:
            db.close()

    def _analyze_template(self, template: str) -> Dict:
        """Analyze a prompt template."""
        parser = PromptTemplateParser()
        params = parser.parse_template(template)
        return {
            "parameters": [{
                "name": p.name,
                "type": p.type,
                "html_type": p.html_type,
                "required": p.required
            } for p in params],
            "parameter_count": len(params)
        }

    def _execute_prompt(self, prompt_id: int, input_params: Dict[str, Any],
                       model_name: str = None, temperature: float = 0.7,
                       repeat: int = 1) -> Dict:
        """Execute a prompt."""
        db = SessionLocal()
        try:
            # Get prompt and latest revision
            prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
            if not prompt:
                raise ValueError(f"Prompt {prompt_id} not found")

            revision = db.query(PromptRevision).filter(
                PromptRevision.prompt_id == prompt_id
            ).order_by(PromptRevision.revision.desc()).first()

            if not revision:
                raise ValueError(f"No revision found for prompt {prompt_id}")

            # Get default model: 1) context (agent session) 2) system setting 3) fallback
            if not model_name:
                model_name = self._get_default_model()
            if not model_name:
                setting = db.query(SystemSetting).filter(
                    SystemSetting.key == "active_llm_model"
                ).first()
                model_name = setting.value if setting else "azure-gpt-4.1"

            # Create and execute job
            job_manager = JobManager(db)
            job = job_manager.create_single_job(
                prompt_revision_id=revision.id,
                input_params=input_params,
                repeat=min(repeat, 10)
            )

            executed_job = job_manager.execute_job(
                job_id=job.id,
                model_name=model_name,
                temperature=temperature
            )

            # Collect results
            results = []
            for item in executed_job.job_items:
                results.append({
                    "status": item.status,
                    "raw_response": item.raw_response,
                    "parsed_response": item.parsed_response,
                    "turnaround_ms": item.turnaround_ms,
                    "error_message": item.error_message
                })

            return {
                "job_id": executed_job.id,
                "status": executed_job.status,
                "model_name": model_name,
                "results": results
            }
        finally:
            db.close()

    def _execute_template(self, template: str, input_params: Dict[str, Any],
                         model_name: str = None, temperature: float = 0.7) -> Dict:
        """Execute a template directly without saving."""
        db = SessionLocal()
        try:
            # Get default model: 1) context (agent session) 2) system setting 3) fallback
            if not model_name:
                model_name = self._get_default_model()
            if not model_name:
                setting = db.query(SystemSetting).filter(
                    SystemSetting.key == "active_llm_model"
                ).first()
                model_name = setting.value if setting else "azure-gpt-4.1"

            # Parse and fill template
            parser = PromptTemplateParser()
            params = parser.parse_template(template)

            filled_template = template
            for param in params:
                placeholder = "{{" + param.name + "}}"
                if param.type != "TEXT5":
                    placeholder = "{{" + param.name + ":" + param.type + "}}"
                value = input_params.get(param.name, "")
                filled_template = filled_template.replace(placeholder, str(value))
                # Also try simple placeholder
                filled_template = filled_template.replace("{{" + param.name + "}}", str(value))

            # Execute with LLM
            client = get_llm_client(model_name)
            response = client.call(
                prompt=filled_template,
                temperature=temperature
            )

            return {
                "success": response.success,
                "response": response.response_text,
                "error": response.error_message,
                "turnaround_ms": response.turnaround_ms,
                "model_name": model_name
            }
        finally:
            db.close()

    def _execute_batch(self, prompt_id: int, dataset_id: int,
                       model_name: str = None, temperature: float = 0.7) -> Dict:
        """Execute batch job using dataset."""
        db = SessionLocal()
        try:
            # Verify prompt exists and get latest revision
            prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
            if not prompt:
                raise ValueError(f"Prompt {prompt_id} not found")

            revision = db.query(PromptRevision).filter(
                PromptRevision.prompt_id == prompt_id
            ).order_by(PromptRevision.revision.desc()).first()

            if not revision:
                raise ValueError(f"No revision found for prompt {prompt_id}")

            # Verify dataset exists
            dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
            if not dataset:
                raise ValueError(f"Dataset {dataset_id} not found")

            # Get default model: 1) context (agent session) 2) system setting 3) fallback
            if not model_name:
                model_name = self._get_default_model()
            if not model_name:
                setting = db.query(SystemSetting).filter(
                    SystemSetting.key == "active_llm_model"
                ).first()
                model_name = setting.value if setting else "azure-gpt-4.1"

            # Create batch job
            job_manager = JobManager(db)
            job = job_manager.create_batch_job(
                prompt_revision_id=revision.id,
                dataset_id=dataset_id,
                model_name=model_name
            )

            # Execute the batch job
            executed_job = job_manager.execute_job(
                job_id=job.id,
                model_name=model_name,
                temperature=temperature
            )

            # Get item count
            item_count = len(executed_job.job_items) if executed_job.job_items else 0
            success_count = sum(1 for item in executed_job.job_items if item.status == "completed")
            error_count = sum(1 for item in executed_job.job_items if item.status == "error")

            return {
                "job_id": executed_job.id,
                "status": executed_job.status,
                "model_name": model_name,
                "dataset_id": dataset_id,
                "dataset_name": dataset.name,
                "item_count": item_count,
                "success_count": success_count,
                "error_count": error_count,
                "csv_link": f"http://localhost:9200/api/jobs/{executed_job.id}/csv"
            }
        finally:
            db.close()

    def _list_workflows(self) -> List[Dict]:
        """List all active workflows (excluding soft-deleted and those with deleted parent project)."""
        from sqlalchemy import or_

        db = SessionLocal()
        try:
            query = db.query(Workflow).filter(Workflow.is_deleted == 0)
            # Also exclude workflows whose parent project is deleted
            query = query.outerjoin(Project, Workflow.project_id == Project.id)
            query = query.filter(
                or_(Workflow.project_id == None, Project.is_deleted == 0)
            )
            workflows = query.order_by(Workflow.id.desc()).all()
            return [{
                "id": w.id,
                "name": w.name,
                "description": w.description or "",
                "project_id": w.project_id,
                "step_count": len(w.steps) if w.steps else 0
            } for w in workflows]
        finally:
            db.close()

    def _get_workflow(self, workflow_id: int) -> Dict:
        """Get workflow details including required input parameters."""
        db = SessionLocal()
        try:
            workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")

            steps = db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == workflow_id
            ).order_by(WorkflowStep.step_order).all()

            # Extract required parameters from first step's prompt
            required_params = []
            if steps and steps[0].prompt_id:
                # Get the latest revision of the first step's prompt
                first_prompt_revision = db.query(PromptRevision).filter(
                    PromptRevision.prompt_id == steps[0].prompt_id
                ).order_by(PromptRevision.id.desc()).first()

                if first_prompt_revision and first_prompt_revision.prompt_template:
                    # Extract {{PARAM_NAME}} or {{PARAM_NAME:TYPE}} patterns
                    import re
                    pattern = r'\{\{([A-Za-z_][A-Za-z0-9_]*)(?::[A-Za-z0-9]+)?\}\}'
                    matches = re.findall(pattern, first_prompt_revision.prompt_template)
                    # Remove duplicates while preserving order
                    seen = set()
                    for m in matches:
                        if m not in seen:
                            required_params.append(m)
                            seen.add(m)

            return {
                "id": workflow.id,
                "name": workflow.name,
                "description": workflow.description or "",
                "required_params": required_params,  # List of required parameter names
                "steps": [{
                    "id": s.id,  # Database ID for delete_workflow_step
                    "step_order": s.step_order,
                    "step_name": s.step_name,
                    "step_type": s.step_type or "prompt",
                    "prompt_id": s.prompt_id,
                    "input_mapping": json.loads(s.input_mapping) if s.input_mapping else {}
                } for s in steps]
            }
        finally:
            db.close()

    def _execute_workflow(self, workflow_id: int, input_params: Dict[str, Any] = None,
                         model_name: str = None, temperature: float = 0.7) -> Dict:
        """Execute a workflow."""
        # Default to empty dict if not provided
        if input_params is None:
            input_params = {}

        db = SessionLocal()
        try:
            workflow_manager = WorkflowManager(db)

            # VALIDATION: Check that required params are provided
            workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")

            # Check if workflow is validated
            if not workflow.validated:
                raise ValueError(
                    f"Workflow '{workflow.name}' (ID={workflow_id}) is not validated. "
                    "Run validate_workflow first. After validation with 0 errors, the workflow can be executed."
                )

            # Get required params from first step's prompt template
            steps = db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == workflow_id
            ).order_by(WorkflowStep.step_order).all()

            if steps and steps[0].prompt_id:
                first_prompt_rev = db.query(PromptRevision).filter(
                    PromptRevision.prompt_id == steps[0].prompt_id
                ).order_by(PromptRevision.revision.desc()).first()

                if first_prompt_rev and first_prompt_rev.prompt_template:
                    # Extract {{PARAM}} or {{PARAM:TYPE}} patterns (excluding step refs like {{stepA.field}})
                    import re
                    param_pattern = re.compile(r'\{\{([a-zA-Z0-9_]+)(?::[^}|]+)?(?:\|[^}]*)?\}\}')
                    template_params = set(param_pattern.findall(first_prompt_rev.prompt_template))
                    # Filter out step references (those containing dots are step refs)
                    required_params = [p for p in template_params if '.' not in p and p != 'CONTEXT']

                    if required_params:
                        missing_params = [p for p in required_params if p not in input_params or not input_params[p]]
                        if missing_params:
                            raise ValueError(
                                f"MISSING REQUIRED PARAMETERS: {missing_params}. "
                                f"You MUST provide values for these parameters. "
                                f"Example: input_params={{'{missing_params[0]}': '人工知能と機械学習は現代のテクノロジーの中核となっています。自然言語処理、画像認識、自動運転など多くの分野で活用されています。'}}"
                            )

            # Get default model: 1) context (agent session) 2) system setting 3) fallback
            if not model_name:
                model_name = self._get_default_model()
            if not model_name:
                setting = db.query(SystemSetting).filter(
                    SystemSetting.key == "active_llm_model"
                ).first()
                model_name = setting.value if setting else "azure-gpt-4.1"

            workflow_job = workflow_manager.execute_workflow(
                workflow_id=workflow_id,
                input_params=input_params,
                model_name=model_name,
                temperature=temperature
            )

            # Parse merged_output to get execution trace
            merged_output = {}
            execution_trace = []
            if workflow_job.merged_output:
                try:
                    merged_output = json.loads(workflow_job.merged_output)
                    execution_trace = merged_output.pop("_execution_trace", [])
                except (json.JSONDecodeError, TypeError):
                    pass

            # Build CSV download link with markdown format
            csv_url = f"http://localhost:9200/api/workflow-jobs/{workflow_job.id}/csv"
            csv_markdown_link = f"[CSVダウンロード]({csv_url})"

            return {
                "workflow_job_id": workflow_job.id,
                "status": workflow_job.status,
                "merged_output": merged_output,
                "execution_trace": execution_trace,
                "csv_link": csv_url,
                "csv_markdown_link": csv_markdown_link
            }
        finally:
            db.close()

    def _get_job_status(self, job_id: int) -> Dict:
        """Get job status and results."""
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job:
                raise ValueError(f"Job {job_id} not found")

            items = db.query(JobItem).filter(JobItem.job_id == job_id).all()

            return {
                "id": job.id,
                "status": job.status,
                "job_type": job.job_type,
                "created_at": job.created_at if isinstance(job.created_at, str) else (job.created_at.isoformat() if job.created_at else None),
                "items": [{
                    "id": item.id,
                    "status": item.status,
                    "raw_response": item.raw_response,
                    "parsed_response": item.parsed_response,
                    "turnaround_ms": item.turnaround_ms
                } for item in items]
            }
        finally:
            db.close()

    def _list_recent_jobs(self, limit: int = 10, project_id: int = None) -> List[Dict]:
        """List recent jobs."""
        db = SessionLocal()
        try:
            query = db.query(Job).order_by(Job.id.desc())

            if project_id:
                # Filter by project through prompt revision
                query = query.join(PromptRevision).join(Prompt).filter(
                    Prompt.project_id == project_id
                )

            jobs = query.limit(limit).all()

            return [{
                "id": j.id,
                "status": j.status,
                "job_type": j.job_type,
                "created_at": j.created_at if isinstance(j.created_at, str) else (j.created_at.isoformat() if j.created_at else None),
                "item_count": len(j.job_items) if j.job_items else 0
            } for j in jobs]
        finally:
            db.close()

    def _cancel_job(self, job_id: int) -> Dict:
        """Cancel a job."""
        db = SessionLocal()
        try:
            job_manager = JobManager(db)
            cancelled_count = job_manager.cancel_pending_items(job_id)
            return {
                "job_id": job_id,
                "cancelled_items": cancelled_count
            }
        finally:
            db.close()

    def _export_job_csv(self, job_id: int, is_workflow_job: bool = False) -> Dict:
        """Get CSV download link for job results.

        Returns a URL that can be used to download the CSV file directly.
        The URL is relative and should be prefixed with the server base URL.

        Auto-detection: If is_workflow_job is not specified (False), the function
        will first check if job_id exists in WorkflowJob table. If found, it will
        return the workflow job CSV URL. Otherwise, it will check the regular Job table.
        """
        db = SessionLocal()
        try:
            from backend.database.models import WorkflowJob, Workflow

            # Auto-detect: First check if this is a workflow job
            wf_job = db.query(WorkflowJob).filter(WorkflowJob.id == job_id).first()

            if wf_job or is_workflow_job:
                # Handle as workflow job
                if not wf_job:
                    raise ValueError(f"Workflow job {job_id} not found")

                if not wf_job.merged_csv_output:
                    raise ValueError(f"No CSV data available for workflow job {job_id}")

                # Get workflow name for display
                workflow_name = "Workflow"
                if wf_job.workflow_id:
                    workflow = db.query(Workflow).filter(Workflow.id == wf_job.workflow_id).first()
                    if workflow:
                        workflow_name = workflow.name

                full_url = f"http://localhost:9200/api/workflow-jobs/{job_id}/csv"
                return {
                    "job_id": job_id,
                    "job_type": "workflow",
                    "download_url": f"/api/workflow-jobs/{job_id}/csv",
                    "full_url": full_url,
                    "workflow_name": workflow_name,
                    "markdown_link": f"[CSVダウンロード]({full_url})",
                    "message": f"CSVダウンロードリンク: [ダウンロード]({full_url})"
                }
            else:
                # Handle as regular job
                job = db.query(Job).filter(Job.id == job_id).first()
                if not job:
                    raise ValueError(f"Job {job_id} not found")

                # Check if CSV data exists
                has_csv = bool(job.merged_csv_output)
                if not has_csv:
                    # Check job items
                    items_with_csv = db.query(JobItem).filter(
                        JobItem.job_id == job_id,
                        JobItem.status == "done"
                    ).count()
                    has_csv = items_with_csv > 0

                if not has_csv:
                    raise ValueError(f"No CSV data available for job {job_id}")

                # Get project name for display (via prompt_revision -> prompt -> project)
                project_name = "Project"
                if job.prompt_revision_id:
                    prompt_revision = db.query(PromptRevision).filter(
                        PromptRevision.id == job.prompt_revision_id
                    ).first()
                    if prompt_revision:
                        prompt = db.query(Prompt).filter(Prompt.id == prompt_revision.prompt_id).first()
                        if prompt:
                            project = db.query(Project).filter(Project.id == prompt.project_id).first()
                            if project:
                                project_name = project.name

                full_url = f"http://localhost:9200/api/jobs/{job_id}/csv"
                return {
                    "job_id": job_id,
                    "job_type": "single",
                    "download_url": f"/api/jobs/{job_id}/csv",
                    "full_url": full_url,
                    "project_name": project_name,
                    "markdown_link": f"[CSVダウンロード]({full_url})",
                    "message": f"CSVダウンロードリンク: [ダウンロード]({full_url})"
                }
        finally:
            db.close()

    def _list_models(self) -> List[Dict]:
        """List available LLM models."""
        models = get_available_models()
        return [{
            "name": m["name"],
            "default_temperature": m.get("default_temperature", 0.7),
            "default_max_tokens": m.get("default_max_tokens", 4096)
        } for m in models]

    def _get_system_settings(self) -> Dict:
        """Get system settings."""
        db = SessionLocal()
        try:
            settings = db.query(SystemSetting).all()
            return {s.key: s.value for s in settings}
        finally:
            db.close()

    # ============== Project/Prompt Update/Delete Handlers ==============

    def _update_project(self, project_id: int, name: str = None, description: str = None) -> Dict:
        """Update a project."""
        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise ValueError(f"Project {project_id} not found")

            if name is not None:
                project.name = name
            if description is not None:
                project.description = description

            db.commit()
            return {"id": project.id, "name": project.name, "description": project.description}
        finally:
            db.close()

    def _delete_project(self, project_id: int) -> Dict:
        """Soft delete a project (mark as deleted instead of physical removal)."""
        from datetime import datetime

        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise ValueError(f"Project {project_id} not found")

            if project.is_deleted:
                raise ValueError(f"Project {project_id} is already deleted")

            # Soft delete: mark as deleted instead of physical delete
            project.is_deleted = 1
            project.deleted_at = datetime.utcnow().isoformat()
            db.commit()
            return {"deleted_project_id": project_id, "name": project.name, "message": "Project soft deleted"}
        finally:
            db.close()

    def _delete_projects(self, project_ids: List[int]) -> Dict:
        """Soft delete multiple projects."""
        from datetime import datetime

        db = SessionLocal()
        try:
            deleted = []
            failed = []
            now = datetime.utcnow().isoformat()

            for project_id in project_ids:
                project = db.query(Project).filter(Project.id == project_id).first()
                if not project:
                    failed.append({"id": project_id, "error": "Not found"})
                    continue
                if project.is_deleted:
                    failed.append({"id": project_id, "error": "Already deleted"})
                    continue

                # Soft delete: mark as deleted
                project.is_deleted = 1
                project.deleted_at = now
                deleted.append(project_id)

            db.commit()
            return {
                "deleted_project_ids": deleted,
                "failed": failed
            }
        finally:
            db.close()

    def _list_deleted_projects(self) -> List[Dict]:
        """List all soft-deleted projects."""
        db = SessionLocal()
        try:
            projects = db.query(Project).filter(
                Project.is_deleted == 1
            ).order_by(Project.deleted_at.desc()).all()
            return [{
                "id": p.id,
                "name": p.name,
                "description": p.description or "",
                "deleted_at": p.deleted_at
            } for p in projects]
        finally:
            db.close()

    def _restore_project(self, project_id: int) -> Dict:
        """Restore a soft-deleted project."""
        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise ValueError(f"Project {project_id} not found")

            if not project.is_deleted:
                raise ValueError(f"Project {project_id} is not deleted")

            project.is_deleted = 0
            project.deleted_at = None
            db.commit()
            return {"restored_project_id": project_id, "name": project.name, "message": "Project restored"}
        finally:
            db.close()

    def _convert_parser_config_shorthand(self, parser_config: str) -> str:
        """Convert shorthand parser config format to full JSON format.

        Shorthand formats:
        - "json" -> {"type": "json"}
        - "json_path:$.field" -> {"type": "json_path", "paths": {"ANSWER": "$.field"}}
        - "regex:pattern" -> {"type": "regex", "patterns": {"ANSWER": "pattern"}}
        - "csv_template:$f1,$f2" -> {"type": "csv_template", "csv_template": "$f1,$f2"}
        - Already JSON -> return as-is
        """
        if not parser_config:
            return parser_config

        # Try to parse as JSON first - if valid, return as-is
        try:
            parsed = json.loads(parser_config)
            if isinstance(parsed, dict):
                return parser_config
        except (json.JSONDecodeError, TypeError):
            pass

        # Handle shorthand formats
        if parser_config == "json":
            return json.dumps({"type": "json"})
        elif parser_config == "none":
            return json.dumps({"type": "none"})
        elif parser_config.startswith("json_path:"):
            path = parser_config[10:]  # Remove "json_path:"
            return json.dumps({"type": "json_path", "paths": {"ANSWER": path}})
        elif parser_config.startswith("regex:"):
            pattern = parser_config[6:]  # Remove "regex:"
            return json.dumps({"type": "regex", "patterns": {"ANSWER": pattern}})
        elif parser_config.startswith("csv_template:"):
            template = parser_config[13:]  # Remove "csv_template:"
            return json.dumps({"type": "csv_template", "csv_template": template})

        # Unknown format, return as-is (might be a raw JSON string)
        return parser_config

    def _update_prompt(self, prompt_id: int, name: str = None, template: str = None, parser_config: str = None) -> Dict:
        """Update a prompt and create a new revision."""
        db = SessionLocal()
        try:
            prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
            if not prompt:
                raise ValueError(f"Prompt {prompt_id} not found")

            if name is not None:
                prompt.name = name

            # Create new revision if template or parser changed
            if template is not None or parser_config is not None:
                latest_revision = db.query(PromptRevision).filter(
                    PromptRevision.prompt_id == prompt_id
                ).order_by(PromptRevision.revision.desc()).first()

                new_revision_number = (latest_revision.revision + 1) if latest_revision else 1

                # Use new values or keep from latest revision
                new_template = template if template is not None else (latest_revision.prompt_template if latest_revision else "")

                # Convert shorthand parser_config format to full JSON
                if parser_config is not None:
                    new_parser_config = self._convert_parser_config_shorthand(parser_config)
                else:
                    new_parser_config = latest_revision.parser_config if latest_revision else ""

                revision = PromptRevision(
                    prompt_id=prompt.id,
                    revision=new_revision_number,
                    prompt_template=new_template,
                    parser_config=new_parser_config
                )
                db.add(revision)

            db.commit()
            return {"id": prompt.id, "name": prompt.name}
        finally:
            db.close()

    def _delete_prompt(self, prompt_id: int) -> Dict:
        """Delete a prompt and all its revisions."""
        db = SessionLocal()
        try:
            prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
            if not prompt:
                raise ValueError(f"Prompt {prompt_id} not found")

            # Delete all revisions
            revision_count = db.query(PromptRevision).filter(PromptRevision.prompt_id == prompt_id).delete()

            prompt_name = prompt.name
            db.delete(prompt)
            db.commit()
            return {"deleted_prompt_id": prompt_id, "name": prompt_name, "deleted_revisions": revision_count}
        finally:
            db.close()

    def _clone_prompt(self, prompt_id: int, new_name: str, copy_revisions: bool = True) -> Dict:
        """Clone a prompt with all its revisions (including parser config)."""
        import requests
        try:
            response = requests.post(
                f"http://localhost:9200/api/prompts/{prompt_id}/clone",
                json={"new_name": new_name, "copy_revisions": copy_revisions}
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "cloned_prompt_id": data["id"],
                    "name": data["name"],
                    "revision_count": data.get("revision_count", 0),
                    "source_prompt_id": prompt_id
                }
            else:
                error = response.json().get("detail", "Clone failed")
                raise ValueError(f"Clone failed: {error}")
        except requests.RequestException as e:
            raise ValueError(f"Clone request failed: {str(e)}")

    def _set_parser_csvoutput(self, prompt_id: int, json_sample: str = None) -> Dict:
        """プロンプトのパーサーをCSV出力用に自動設定"""
        import re
        db = SessionLocal()
        try:
            # 1. プロンプトと最新リビジョン取得
            prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
            if not prompt:
                raise ValueError(f"Prompt {prompt_id} not found")

            latest_rev = db.query(PromptRevision).filter(
                PromptRevision.prompt_id == prompt_id
            ).order_by(PromptRevision.revision.desc()).first()

            if not latest_rev:
                raise ValueError(f"No revision found for prompt {prompt_id}")

            # 2. JSON取得（指定またはテンプレートから検出）
            if json_sample:
                json_text = json_sample
            else:
                json_text = self._extract_json_from_template(latest_rev.prompt_template)
                if not json_text:
                    raise ValueError("JSON not found in prompt template. Please provide json_sample parameter.")

            # 3. JSONパースしてパス抽出
            cleaned_json = self._clean_json_placeholders(json_text)
            json_data = json.loads(cleaned_json)
            paths, field_names = self._extract_json_paths(json_data)

            if not field_names:
                raise ValueError("No fields found in JSON. Check JSON structure.")

            # 4. CSV用パーサー設定生成
            csv_template = ','.join([f'"${name}$"' for name in field_names])
            parser_config = {
                "type": "json_path",
                "paths": paths,
                "csv_template": csv_template
            }
            parser_config_str = json.dumps(parser_config, ensure_ascii=False)

            # 5. 新リビジョン作成
            new_rev = PromptRevision(
                prompt_id=prompt.id,
                revision=latest_rev.revision + 1,
                prompt_template=latest_rev.prompt_template,
                parser_config=parser_config_str
            )
            db.add(new_rev)
            db.commit()

            return {
                "prompt_id": prompt_id,
                "prompt_name": prompt.name,
                "revision": new_rev.revision,
                "parser_config": parser_config,
                "csv_header": ','.join(field_names),
                "message": f"CSV parser configured with {len(field_names)} fields"
            }
        finally:
            db.close()

    def _extract_json_from_template(self, template: str) -> Optional[str]:
        """テンプレートからJSON例を抽出"""
        import re
        if not template:
            return None
        # ```json ... ``` ブロックを探す
        json_block = re.search(r'```json\s*([\s\S]*?)\s*```', template)
        if json_block:
            return json_block.group(1)
        # { で始まり } で終わる部分を探す（最後のJSONブロック）
        json_matches = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', template)
        if json_matches:
            return json_matches[-1]  # 最後のJSONブロックを返す
        return None

    def _clean_json_placeholders(self, json_text: str) -> str:
        """<...>プレースホルダーをサンプル値に置換"""
        import re
        cleaned = re.sub(r'"<[^>]+>"', '"sample"', json_text)
        cleaned = re.sub(r'<[^>]+>', '"sample"', cleaned)
        cleaned = re.sub(r',\s*}', '}', cleaned)
        cleaned = re.sub(r',\s*]', ']', cleaned)
        return cleaned

    def _extract_json_paths(self, obj, current_path: str = '$', paths: dict = None, field_names: list = None):
        """JSONオブジェクトからリーフパスを再帰的に抽出"""
        if paths is None:
            paths = {}
        if field_names is None:
            field_names = []

        if obj is None:
            return paths, field_names

        if isinstance(obj, dict):
            for key in obj:
                new_path = f"$.{key}" if current_path == '$' else f"{current_path}.{key}"
                self._extract_json_paths(obj[key], new_path, paths, field_names)
        elif isinstance(obj, list):
            pass  # 配列はスキップ（CSV向けには複雑すぎる）
        else:
            # リーフ値（文字列、数値、ブール）
            field_name = current_path.replace('$.', '').replace('.', '_')
            paths[field_name] = current_path
            field_names.append(field_name)

        return paths, field_names

    def _clone_workflow(self, workflow_id: int, new_name: str) -> Dict:
        """Clone a workflow with all its steps."""
        import requests
        try:
            response = requests.post(
                f"http://localhost:9200/api/workflows/{workflow_id}/clone",
                json={"new_name": new_name}
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "cloned_workflow_id": data["id"],
                    "name": data["name"],
                    "step_count": len(data.get("steps", [])),
                    "source_workflow_id": workflow_id
                }
            else:
                error = response.json().get("detail", "Clone failed")
                raise ValueError(f"Clone failed: {error}")
        except requests.RequestException as e:
            raise ValueError(f"Clone request failed: {str(e)}")

    # ============== Workflow CRUD Handlers ==============

    def _create_workflow(self, name: str, description: str = "", project_id: int = None) -> Dict:
        """Create a new workflow.

        If project_id is not specified, the first available project will be used as default.
        """
        # Validate workflow name
        if not name or not name.strip():
            raise ValueError("Workflow name cannot be empty")

        db = SessionLocal()
        try:
            # Check for duplicate workflow name
            existing = db.query(Workflow).filter(Workflow.name == name).first()
            if existing:
                return {
                    "success": False,
                    "error": f"Workflow '{name}' already exists (id={existing.id}). Use get_workflow({existing.id}) to view, or update_workflow/update_workflow_step to modify.",
                    "existing_workflow_id": existing.id,
                    "hint": "To create a new workflow with a different name, use a unique name. If modifying existing workflow, use update tools instead."
                }

            # If no project_id specified, use the first available project as default
            if project_id is None:
                first_project = db.query(Project).order_by(Project.id).first()
                if first_project:
                    project_id = first_project.id
                    logger.info(f"Auto-assigned default project_id={project_id} ({first_project.name}) for workflow '{name}'")

            workflow = Workflow(name=name, description=description, project_id=project_id)
            db.add(workflow)
            db.commit()
            db.refresh(workflow)

            # Get project name for response
            project_name = None
            if workflow.project_id:
                project = db.query(Project).filter(Project.id == workflow.project_id).first()
                if project:
                    project_name = project.name

            return {
                "id": workflow.id,
                "name": workflow.name,
                "project_id": workflow.project_id,
                "project_name": project_name
            }
        finally:
            db.close()

    def _update_workflow(self, workflow_id: int, name: str = None, description: str = None, project_id: int = None) -> Dict:
        """Update a workflow."""
        db = SessionLocal()
        try:
            workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")

            if name is not None:
                workflow.name = name
            if description is not None:
                workflow.description = description
            if project_id is not None:
                workflow.project_id = project_id

            db.commit()

            # Validate workflow after update
            validation = validate_workflow(db, workflow_id)
            result = {"id": workflow.id, "name": workflow.name, "description": workflow.description}

            if not validation.valid or validation.warnings > 0:
                result["validation"] = validation.to_dict()
                if not validation.valid:
                    result["validation_warning"] = f"Workflow has {validation.errors} validation error(s) that must be fixed"

            return result
        finally:
            db.close()

    def _delete_workflow(self, workflow_id: int) -> Dict:
        """Soft delete a workflow (mark as deleted instead of physical removal)."""
        from datetime import datetime

        db = SessionLocal()
        try:
            workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")

            if workflow.is_deleted:
                raise ValueError(f"Workflow {workflow_id} is already deleted")

            # Soft delete: mark as deleted instead of physical delete
            workflow.is_deleted = 1
            workflow.deleted_at = datetime.utcnow().isoformat()
            workflow.updated_at = datetime.utcnow().isoformat()
            db.commit()
            return {"deleted_workflow_id": workflow_id, "name": workflow.name, "message": "Workflow soft deleted"}
        finally:
            db.close()

    def _list_deleted_workflows(self) -> List[Dict]:
        """List all soft-deleted workflows."""
        db = SessionLocal()
        try:
            workflows = db.query(Workflow).filter(
                Workflow.is_deleted == 1
            ).order_by(Workflow.deleted_at.desc()).all()
            return [{
                "id": w.id,
                "name": w.name,
                "description": w.description or "",
                "project_id": w.project_id,
                "deleted_at": w.deleted_at
            } for w in workflows]
        finally:
            db.close()

    def _restore_workflow(self, workflow_id: int) -> Dict:
        """Restore a soft-deleted workflow."""
        from datetime import datetime

        db = SessionLocal()
        try:
            workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")

            if not workflow.is_deleted:
                raise ValueError(f"Workflow {workflow_id} is not deleted")

            # Check if parent project is deleted
            if workflow.project_id:
                project = db.query(Project).filter(Project.id == workflow.project_id).first()
                if project and project.is_deleted:
                    raise ValueError(f"Cannot restore workflow - parent project {workflow.project_id} is deleted. Restore the project first.")

            workflow.is_deleted = 0
            workflow.deleted_at = None
            workflow.updated_at = datetime.utcnow().isoformat()
            db.commit()
            return {"restored_workflow_id": workflow_id, "name": workflow.name, "message": "Workflow restored"}
        finally:
            db.close()

    # ============== Workflow Step Handlers ==============

    def _add_workflow_step(self, workflow_id: int, step_name: str, step_type: str = "prompt",
                          prompt_id: int = None, step_order: int = None,
                          input_mapping: Any = None, condition_config: Any = None,
                          insert_after: str = None) -> Dict:
        """Add a step to a workflow.

        IMPORTANT: Use 'insert_after' instead of 'step_order' when adding steps
        inside control flow blocks (IF/ELSE/FOREACH). This automatically calculates
        the correct position based on the current workflow structure.

        Parameters:
            insert_after: Step name to insert after. The new step will be placed
                         immediately after this step. Use this for:
                         - then-branch: insert_after="{if_name}"
                         - else-branch: insert_after="{if_name}_else"
                         - loop body: insert_after="{foreach_name}"

            step_order: Direct position (use insert_after instead when possible).
                       If specified and conflicts with existing steps,
                       existing steps at that position and beyond are shifted up by 1.

        If prompt_id is provided, the step's project_id is automatically set
        from the prompt's project_id.

        Note: input_mapping and condition_config can be either Dict or JSON string.
        """
        # Validate: Control flow steps must use dedicated tools
        control_flow_types = {"if", "foreach"}
        control_flow_end_types = {"else", "endif", "endforeach"}

        if step_type in control_flow_types:
            tool_name = f"add_{step_type}_block"
            raise ValueError(
                f"Control flow step '{step_type}' must be created using the '{tool_name}' tool. "
                f"This ensures proper block structure (e.g., IF/ENDIF pairs). "
                f"Use '{tool_name}' instead of 'add_workflow_step'."
            )

        if step_type in control_flow_end_types:
            parent_type = {
                "else": "if",
                "endif": "if",
                "endforeach": "foreach"
            }[step_type]
            raise ValueError(
                f"Control flow step '{step_type}' cannot be created individually. "
                f"It is automatically created as part of 'add_{parent_type}_block'. "
                f"Use 'add_{parent_type}_block' to create a complete control flow block."
            )

        # Validate: Prompt steps require prompt_id
        if step_type == "prompt" or step_type is None:
            if not prompt_id:
                raise ValueError(
                    "Prompt step requires 'prompt_id'. "
                    "First create a prompt using 'create_prompt', then use its ID here. "
                    "Example: add_workflow_step(workflow_id=1, step_name='ask', prompt_id=123)"
                )

        db = SessionLocal()
        try:
            workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")

            # Reset validated flag when modifying steps
            workflow.validated = 0

            # Check for duplicate step name within the workflow
            existing_step = db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == workflow_id,
                WorkflowStep.step_name == step_name
            ).first()
            if existing_step:
                raise ValueError(f"Step name '{step_name}' already exists in this workflow (step_id: {existing_step.id}, order: {existing_step.step_order})")

            # Handle insert_after: find the step and calculate step_order
            if insert_after is not None:
                if step_order is not None:
                    raise ValueError(
                        "Cannot specify both 'insert_after' and 'step_order'. "
                        "Use 'insert_after' for control flow blocks (recommended) or 'step_order' for direct positioning."
                    )
                reference_step = db.query(WorkflowStep).filter(
                    WorkflowStep.workflow_id == workflow_id,
                    WorkflowStep.step_name == insert_after
                ).first()
                if not reference_step:
                    raise ValueError(
                        f"Step '{insert_after}' not found in workflow. "
                        f"Check the step name in 'insert_after' parameter."
                    )
                step_order = reference_step.step_order + 1
                logger.info(f"insert_after='{insert_after}' resolved to step_order={step_order}")

            # Normalize input_mapping: accept both dict and JSON string
            input_mapping_str = None
            if input_mapping is not None:
                if isinstance(input_mapping, str):
                    # Validate it's valid JSON
                    json.loads(input_mapping)  # Will raise if invalid
                    input_mapping_str = input_mapping
                else:
                    input_mapping_str = json.dumps(input_mapping)

            # Normalize condition_config: accept both dict and JSON string
            # Empty string or None is treated as no config (valid for ELSE, ENDIF, ENDFOREACH)
            condition_config_str = None
            if condition_config is not None and condition_config != "":
                if isinstance(condition_config, str):
                    # Validate it's valid JSON
                    json.loads(condition_config)  # Will raise if invalid
                    condition_config_str = condition_config
                else:
                    condition_config_str = json.dumps(condition_config)

            # Determine project_id from prompt if prompt_id is provided
            project_id = None
            if prompt_id:
                prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
                if prompt:
                    project_id = prompt.project_id
                    logger.info(f"Auto-assigned project_id={project_id} from prompt {prompt_id} for step '{step_name}'")

            # Determine step order if not provided
            if step_order is None:
                max_order = db.query(WorkflowStep).filter(
                    WorkflowStep.workflow_id == workflow_id
                ).count()
                step_order = max_order
            else:
                # Shift existing steps at this position and beyond
                existing_steps = db.query(WorkflowStep).filter(
                    WorkflowStep.workflow_id == workflow_id,
                    WorkflowStep.step_order >= step_order
                ).order_by(WorkflowStep.step_order.desc()).all()

                for existing_step in existing_steps:
                    existing_step.step_order += 1
                db.flush()

            step = WorkflowStep(
                workflow_id=workflow_id,
                step_name=step_name,
                step_type=step_type,
                prompt_id=prompt_id,
                project_id=project_id,
                step_order=step_order,
                input_mapping=input_mapping_str,
                condition_config=condition_config_str
            )
            db.add(step)
            db.commit()
            db.refresh(step)

            # Validate workflow after adding step
            validation = validate_workflow(db, workflow_id)

            # Get current structure of all steps for agent visibility
            all_steps = db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == workflow_id
            ).order_by(WorkflowStep.step_order).all()

            result = {
                "step_id": step.id,
                "id": step.id,
                "step_name": step.step_name,
                "step_order": step.step_order,
                "current_structure": [
                    {"order": s.step_order, "name": s.step_name, "type": s.step_type}
                    for s in all_steps
                ],
                "total_steps": len(all_steps)
            }

            if not validation.valid or validation.warnings > 0:
                result["validation"] = validation.to_dict()
                if not validation.valid:
                    result["validation_warning"] = f"Workflow has {validation.errors} validation error(s) that must be fixed"

            return result
        finally:
            db.close()

    def _add_foreach_block(self, workflow_id: int, foreach_name: str, source: str, item_var: str,
                           step_order: int = None) -> Dict:
        """Add a FOREACH block (FOREACH + ENDFOREACH) to a workflow.

        This creates both the FOREACH and ENDFOREACH steps atomically,
        preventing incomplete control flow blocks.
        """
        db = SessionLocal()
        try:
            workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")

            # Reset validated flag when modifying steps
            workflow.validated = 0

            # Check for duplicate step names (both foreach_name and foreach_name_end)
            endforeach_name = f"{foreach_name}_end"
            for name in [foreach_name, endforeach_name]:
                existing_step = db.query(WorkflowStep).filter(
                    WorkflowStep.workflow_id == workflow_id,
                    WorkflowStep.step_name == name
                ).first()
                if existing_step:
                    raise ValueError(f"Step name '{name}' already exists in this workflow (step_id: {existing_step.id}, order: {existing_step.step_order})")

            # Determine step order if not provided
            if step_order is None:
                max_order = db.query(WorkflowStep).filter(
                    WorkflowStep.workflow_id == workflow_id
                ).count()
                step_order = max_order

            # Shift existing steps at this position and beyond by 2
            existing_steps = db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == workflow_id,
                WorkflowStep.step_order >= step_order
            ).order_by(WorkflowStep.step_order.desc()).all()

            for existing_step in existing_steps:
                existing_step.step_order += 2
            db.flush()

            # Resolve dataset name if source references a dataset
            resolved_dataset_name = None
            if source.startswith("dataset:"):
                parts = source.split(":")
                if len(parts) >= 2:
                    try:
                        dataset_id = int(parts[1])
                        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
                        if dataset:
                            resolved_dataset_name = dataset.name
                            logger.info(f"Resolved dataset ID {dataset_id} to '{resolved_dataset_name}'")
                        else:
                            logger.warning(f"Dataset ID {dataset_id} not found")
                    except ValueError:
                        pass

            # Create FOREACH step
            foreach_config = json.dumps({"source": source, "item_var": item_var})
            foreach_step = WorkflowStep(
                workflow_id=workflow_id,
                step_name=foreach_name,
                step_type="foreach",
                step_order=step_order,
                condition_config=foreach_config
            )
            db.add(foreach_step)

            # Create ENDFOREACH step
            endforeach_step = WorkflowStep(
                workflow_id=workflow_id,
                step_name=f"{foreach_name}_end",
                step_type="endforeach",
                step_order=step_order + 1
            )
            db.add(endforeach_step)

            db.commit()
            db.refresh(foreach_step)
            db.refresh(endforeach_step)

            # Validate workflow after adding steps
            validation = validate_workflow(db, workflow_id)

            # Get current structure
            all_steps = db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == workflow_id
            ).order_by(WorkflowStep.step_order).all()

            # Build message with dataset name if resolved
            if resolved_dataset_name:
                message = f"Created FOREACH block iterating over dataset '{resolved_dataset_name}'. Use insert_after='{foreach_name}' to add loop body steps."
            else:
                message = f"Created FOREACH block with source='{source}'. Use insert_after='{foreach_name}' to add loop body steps."

            result = {
                "foreach_step_id": foreach_step.id,
                "endforeach_step_id": endforeach_step.id,
                "foreach_order": foreach_step.step_order,
                "endforeach_order": endforeach_step.step_order,
                "source": source,
                "dataset_name": resolved_dataset_name,
                "item_var": item_var,
                "message": message,
                "current_structure": [
                    {"order": s.step_order, "name": s.step_name, "type": s.step_type}
                    for s in all_steps
                ],
                "total_steps": len(all_steps),
                # Helper: step name for insert_after
                "insert_after_hints": {
                    "loop_body": foreach_name
                }
            }

            if not validation.valid or validation.warnings > 0:
                result["validation"] = validation.to_dict()
                if not validation.valid:
                    result["validation_warning"] = f"Workflow has {validation.errors} validation error(s) that must be fixed"

            return result
        finally:
            db.close()

    def _add_if_block(self, workflow_id: int, if_name: str, left: str, operator: str, right: str,
                      include_else: bool = False, step_order: int = None) -> Dict:
        """Add an IF block (IF + optional ELSE + ENDIF) to a workflow.

        This creates all required control flow steps atomically,
        preventing incomplete control flow blocks.
        """
        db = SessionLocal()
        try:
            workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")

            # Reset validated flag when modifying steps
            workflow.validated = 0

            # Check for duplicate step names (if_name, if_name_else, if_name_end)
            names_to_check = [if_name, f"{if_name}_end"]
            if include_else:
                names_to_check.append(f"{if_name}_else")
            for name in names_to_check:
                existing_step = db.query(WorkflowStep).filter(
                    WorkflowStep.workflow_id == workflow_id,
                    WorkflowStep.step_name == name
                ).first()
                if existing_step:
                    raise ValueError(f"Step name '{name}' already exists in this workflow (step_id: {existing_step.id}, order: {existing_step.step_order})")

            # Determine step order if not provided
            if step_order is None:
                max_order = db.query(WorkflowStep).filter(
                    WorkflowStep.workflow_id == workflow_id
                ).count()
                step_order = max_order

            # Calculate how many steps we're adding
            num_steps = 3 if include_else else 2  # IF + [ELSE] + ENDIF

            # Shift existing steps at this position and beyond
            existing_steps = db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == workflow_id,
                WorkflowStep.step_order >= step_order
            ).order_by(WorkflowStep.step_order.desc()).all()

            for existing_step in existing_steps:
                existing_step.step_order += num_steps
            db.flush()

            # Create IF step
            if_config = json.dumps({"left": left, "operator": operator, "right": right})
            if_step = WorkflowStep(
                workflow_id=workflow_id,
                step_name=if_name,
                step_type="if",
                step_order=step_order,
                condition_config=if_config
            )
            db.add(if_step)

            created_steps = [if_step]
            else_step = None
            current_order = step_order + 1

            # Create ELSE step if requested
            if include_else:
                else_step = WorkflowStep(
                    workflow_id=workflow_id,
                    step_name=f"{if_name}_else",
                    step_type="else",
                    step_order=current_order
                )
                db.add(else_step)
                created_steps.append(else_step)
                current_order += 1

            # Create ENDIF step
            endif_step = WorkflowStep(
                workflow_id=workflow_id,
                step_name=f"{if_name}_end",
                step_type="endif",
                step_order=current_order
            )
            db.add(endif_step)
            created_steps.append(endif_step)

            db.commit()
            for s in created_steps:
                db.refresh(s)

            # Validate workflow after adding steps
            validation = validate_workflow(db, workflow_id)

            # Get current structure
            all_steps = db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == workflow_id
            ).order_by(WorkflowStep.step_order).all()

            if include_else:
                message = (
                    f"Created IF block with ELSE. "
                    f"Use insert_after='{if_name}' for then-branch, "
                    f"insert_after='{if_name}_else' for else-branch."
                )
            else:
                message = (
                    f"Created IF block. "
                    f"Use insert_after='{if_name}' for then-branch."
                )

            result = {
                "if_step_id": if_step.id,
                "endif_step_id": endif_step.id,
                "if_order": if_step.step_order,
                "endif_order": endif_step.step_order,
                "message": message,
                "current_structure": [
                    {"order": s.step_order, "name": s.step_name, "type": s.step_type}
                    for s in all_steps
                ],
                "total_steps": len(all_steps),
                # Helper: step names for insert_after
                "insert_after_hints": {
                    "then_branch": if_name,
                    "else_branch": f"{if_name}_else" if include_else else None
                }
            }

            if else_step:
                result["else_step_id"] = else_step.id
                result["else_order"] = else_step.step_order

            if not validation.valid or validation.warnings > 0:
                result["validation"] = validation.to_dict()
                if not validation.valid:
                    result["validation_warning"] = f"Workflow has {validation.errors} validation error(s) that must be fixed"

            return result
        finally:
            db.close()

    def _update_workflow_step(self, step_id: int, step_name: str = None, step_type: str = None,
                             prompt_id: int = None, step_order: int = None,
                             input_mapping: Any = None, condition_config: Any = None) -> Dict:
        """Update a workflow step.

        If prompt_id is updated, the step's project_id is automatically updated
        from the prompt's project_id.

        Note: input_mapping and condition_config can be either Dict or JSON string.
        """
        db = SessionLocal()
        try:
            step = db.query(WorkflowStep).filter(WorkflowStep.id == step_id).first()
            if not step:
                raise ValueError(f"Step {step_id} not found")

            # Reset validated flag when modifying steps
            workflow = db.query(Workflow).filter(Workflow.id == step.workflow_id).first()
            if workflow:
                workflow.validated = 0

            if step_name is not None:
                # Check for duplicate step name within the workflow (excluding current step)
                if step_name != step.step_name:
                    existing_step = db.query(WorkflowStep).filter(
                        WorkflowStep.workflow_id == step.workflow_id,
                        WorkflowStep.step_name == step_name,
                        WorkflowStep.id != step_id
                    ).first()
                    if existing_step:
                        raise ValueError(f"Step name '{step_name}' already exists in this workflow (step_id: {existing_step.id}, order: {existing_step.step_order})")
                step.step_name = step_name
            if step_type is not None:
                step.step_type = step_type
            if prompt_id is not None:
                step.prompt_id = prompt_id
                # Also update project_id from prompt
                prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
                if prompt:
                    step.project_id = prompt.project_id
                    logger.info(f"Auto-updated project_id={prompt.project_id} from prompt {prompt_id} for step {step_id}")
            if step_order is not None:
                step.step_order = step_order
            if input_mapping is not None:
                # Accept both dict and JSON string
                if isinstance(input_mapping, str):
                    json.loads(input_mapping)  # Validate
                    step.input_mapping = input_mapping
                else:
                    step.input_mapping = json.dumps(input_mapping)
            if condition_config is not None and condition_config != "":
                # Accept both dict and JSON string
                if isinstance(condition_config, str):
                    json.loads(condition_config)  # Validate
                    step.condition_config = condition_config
                else:
                    step.condition_config = json.dumps(condition_config)

            workflow_id = step.workflow_id
            db.commit()

            # Validate workflow after update
            validation = validate_workflow(db, workflow_id)

            # Get current structure of all steps for agent visibility
            all_steps = db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == workflow_id
            ).order_by(WorkflowStep.step_order).all()

            result = {
                "id": step.id,
                "step_name": step.step_name,
                "step_order": step.step_order,
                "current_structure": [
                    {"order": s.step_order, "name": s.step_name, "type": s.step_type}
                    for s in all_steps
                ],
                "total_steps": len(all_steps)
            }

            if not validation.valid or validation.warnings > 0:
                result["validation"] = validation.to_dict()
                if not validation.valid:
                    result["validation_warning"] = f"Workflow has {validation.errors} validation error(s) that must be fixed"

            return result
        finally:
            db.close()

    def _delete_workflow_step(self, step_id: int) -> Dict:
        """Delete a workflow step.

        After deletion, remaining steps are renumbered to maintain
        consecutive step_order values (0, 1, 2, ...).
        """
        db = SessionLocal()
        try:
            step = db.query(WorkflowStep).filter(WorkflowStep.id == step_id).first()
            if not step:
                raise ValueError(f"Step {step_id} not found")

            step_name = step.step_name
            workflow_id = step.workflow_id
            deleted_order = step.step_order

            # Reset validated flag when modifying steps
            workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
            if workflow:
                workflow.validated = 0

            db.delete(step)
            db.flush()

            # Renumber remaining steps: shift down all steps after the deleted one
            remaining_steps = db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == workflow_id,
                WorkflowStep.step_order > deleted_order
            ).order_by(WorkflowStep.step_order.asc()).all()

            for remaining_step in remaining_steps:
                remaining_step.step_order -= 1

            db.commit()

            # Validate workflow after deletion
            validation = validate_workflow(db, workflow_id)

            # Get current structure of all steps for agent visibility
            all_steps = db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == workflow_id
            ).order_by(WorkflowStep.step_order).all()

            result = {
                "deleted_step_id": step_id,
                "step_name": step_name,
                "workflow_id": workflow_id,
                "current_structure": [
                    {"order": s.step_order, "name": s.step_name, "type": s.step_type}
                    for s in all_steps
                ],
                "total_steps": len(all_steps)
            }

            if not validation.valid or validation.warnings > 0:
                result["validation"] = validation.to_dict()
                if not validation.valid:
                    result["validation_warning"] = f"Workflow has {validation.errors} validation error(s) that must be fixed"

            return result
        finally:
            db.close()

    def _validate_workflow(self, workflow_id: int) -> Dict:
        """Validate workflow integrity and configuration.

        Updates the workflow's validated flag based on validation results:
        - validated = true if 0 errors (warnings are allowed)
        - validated = false if any errors exist

        The workflow must be validated (0 errors) before it can be executed.
        """
        db = SessionLocal()
        try:
            validation = validate_workflow(db, workflow_id)
            result = validation.to_dict()

            # Add execution readiness info
            workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
            if workflow:
                result["validated"] = bool(workflow.validated)
                result["execution_ready"] = bool(workflow.validated)
                if not workflow.validated:
                    result["execution_blocked_reason"] = "Workflow has validation errors. Fix all errors before execution."

            return result
        finally:
            db.close()

    def _get_available_variables(self, workflow_id: int, step_order: int) -> Dict:
        """Get available variables and functions at a specific workflow step.

        Returns categorized variables that can be used in the step's input_mapping
        or condition_config, including FOREACH context with dataset columns.
        """
        db = SessionLocal()
        try:
            result = get_available_variables_at_step(db, workflow_id, step_order)
            return result
        finally:
            db.close()

    def _run_workflow_validation(self, db, workflow_id: int) -> Optional[Dict]:
        """Run validation and return dict if there are issues.

        Returns None if validation passed with no warnings.
        """
        validation = validate_workflow(db, workflow_id)
        if not validation.valid or validation.warnings > 0:
            return validation.to_dict()
        return None

    def _list_datasets(self, project_id: int = None) -> Dict:
        """List all datasets in the system."""
        db = SessionLocal()
        try:
            query = db.query(Dataset)
            if project_id is not None:
                query = query.filter(Dataset.project_id == project_id)

            datasets = query.order_by(Dataset.created_at.desc()).all()

            result = []
            for ds in datasets:
                project_name = None
                if ds.project:
                    project_name = ds.project.name

                result.append({
                    "id": ds.id,
                    "name": ds.name,
                    "project_id": ds.project_id,
                    "project_name": project_name,
                    "source_file_name": ds.source_file_name,
                    "sqlite_table_name": ds.sqlite_table_name,
                    "created_at": ds.created_at
                })

            return {
                "datasets": result,
                "total": len(result)
            }
        finally:
            db.close()

    def _get_dataset(self, dataset_id: int) -> Dict:
        """Get details of a specific dataset including column info and row count."""
        db = SessionLocal()
        try:
            dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
            if not dataset:
                raise ValueError(f"Dataset {dataset_id} not found")

            project_name = None
            if dataset.project:
                project_name = dataset.project.name

            # Get column info and row count from the actual SQLite table
            columns = []
            row_count = 0
            sample_rows = []

            try:
                from sqlalchemy import text
                # Get column names
                result = db.execute(text(f'PRAGMA table_info("{dataset.sqlite_table_name}")'))
                columns = [{"name": row[1], "type": row[2]} for row in result]

                # Get row count
                count_result = db.execute(text(f'SELECT COUNT(*) FROM "{dataset.sqlite_table_name}"'))
                row_count = count_result.scalar() or 0

                # Get sample rows (first 3)
                if columns:
                    col_names = [c["name"] for c in columns]
                    sample_result = db.execute(text(f'SELECT * FROM "{dataset.sqlite_table_name}" LIMIT 3'))
                    for row in sample_result:
                        sample_rows.append(dict(zip(col_names, row)))
            except Exception as e:
                logger.warning(f"Failed to get dataset table info: {e}")

            return {
                "id": dataset.id,
                "name": dataset.name,
                "project_id": dataset.project_id,
                "project_name": project_name,
                "source_file_name": dataset.source_file_name,
                "sqlite_table_name": dataset.sqlite_table_name,
                "created_at": dataset.created_at,
                "columns": columns,
                "row_count": row_count,
                "sample_rows": sample_rows
            }
        finally:
            db.close()

    def _search_datasets(self, query: str) -> Dict:
        """Search datasets by name or source file name."""
        db = SessionLocal()
        try:
            search_pattern = f"%{query}%"
            datasets = db.query(Dataset).filter(
                (Dataset.name.ilike(search_pattern)) |
                (Dataset.source_file_name.ilike(search_pattern))
            ).order_by(Dataset.created_at.desc()).all()

            result = []
            for ds in datasets:
                project_name = None
                if ds.project:
                    project_name = ds.project.name

                result.append({
                    "id": ds.id,
                    "name": ds.name,
                    "project_id": ds.project_id,
                    "project_name": project_name,
                    "source_file_name": ds.source_file_name,
                    "created_at": ds.created_at
                })

            return {
                "query": query,
                "datasets": result,
                "total": len(result)
            }
        finally:
            db.close()

    def _search_dataset_content(self, dataset_id: int, query: str,
                                 column: str = None, limit: int = 20) -> Dict:
        """Search within a dataset's data rows."""
        db = SessionLocal()
        try:
            from sqlalchemy import text

            dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
            if not dataset:
                raise ValueError(f"Dataset {dataset_id} not found")

            table_name = dataset.sqlite_table_name

            # Get column names
            col_result = db.execute(text(f'PRAGMA table_info("{table_name}")'))
            columns = [row[1] for row in col_result]

            if not columns:
                return {
                    "dataset_id": dataset_id,
                    "dataset_name": dataset.name,
                    "query": query,
                    "rows": [],
                    "total": 0,
                    "message": "Dataset has no columns"
                }

            # Build search query
            search_pattern = f"%{query}%"
            if column:
                # Search specific column
                if column not in columns:
                    raise ValueError(f"Column '{column}' not found in dataset. Available columns: {columns}")
                where_clause = f'"{column}" LIKE :pattern'
            else:
                # Search all columns
                conditions = [f'CAST("{col}" AS TEXT) LIKE :pattern' for col in columns]
                where_clause = " OR ".join(conditions)

            sql = f'SELECT rowid, * FROM "{table_name}" WHERE {where_clause} LIMIT :limit'
            result = db.execute(text(sql), {"pattern": search_pattern, "limit": limit})

            rows = []
            for row in result:
                row_data = {"_rowid": row[0]}
                for i, col_name in enumerate(columns):
                    row_data[col_name] = row[i + 1]
                rows.append(row_data)

            # Get total count
            count_sql = f'SELECT COUNT(*) FROM "{table_name}" WHERE {where_clause}'
            total = db.execute(text(count_sql), {"pattern": search_pattern}).scalar() or 0

            return {
                "dataset_id": dataset_id,
                "dataset_name": dataset.name,
                "query": query,
                "column_filter": column,
                "columns": columns,
                "rows": rows,
                "returned": len(rows),
                "total": total
            }
        finally:
            db.close()

    def _preview_dataset_rows(self, dataset_id: int, offset: int = 0, limit: int = 10) -> Dict:
        """Preview rows from a dataset with pagination."""
        db = SessionLocal()
        try:
            from sqlalchemy import text

            # Validate parameters
            offset = max(0, int(offset or 0))
            limit = min(100, max(1, int(limit or 10)))  # Clamp between 1 and 100

            # Verify dataset exists
            dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
            if not dataset:
                raise ValueError(f"Dataset {dataset_id} not found")

            table_name = dataset.sqlite_table_name

            # Get column names
            col_result = db.execute(text(f'PRAGMA table_info("{table_name}")'))
            columns = [row[1] for row in col_result]

            if not columns:
                return {
                    "dataset_id": dataset_id,
                    "dataset_name": dataset.name,
                    "columns": [],
                    "rows": [],
                    "offset": offset,
                    "limit": limit,
                    "returned": 0,
                    "total": 0
                }

            # Get total row count
            count_result = db.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
            total = count_result.scalar() or 0

            # Get rows with pagination
            sql = f'SELECT * FROM "{table_name}" LIMIT :limit OFFSET :offset'
            result = db.execute(text(sql), {"limit": limit, "offset": offset})

            # Convert rows to dicts
            rows = []
            for row in result:
                row_dict = {}
                for i, col in enumerate(columns):
                    row_dict[col] = row[i]
                rows.append(row_dict)

            return {
                "dataset_id": dataset_id,
                "dataset_name": dataset.name,
                "columns": columns,
                "rows": rows,
                "offset": offset,
                "limit": limit,
                "returned": len(rows),
                "total": total,
                "has_more": offset + len(rows) < total
            }
        finally:
            db.close()

    def _execute_batch_with_filter(self, prompt_id: int, dataset_id: int,
                                    filter_query: str, filter_column: str = None,
                                    model_name: str = None, temperature: float = 0.7) -> Dict:
        """Execute batch job with filtered dataset rows."""
        db = SessionLocal()
        try:
            from sqlalchemy import text

            # Verify prompt exists and get latest revision
            prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
            if not prompt:
                raise ValueError(f"Prompt {prompt_id} not found")

            revision = db.query(PromptRevision).filter(
                PromptRevision.prompt_id == prompt_id
            ).order_by(PromptRevision.revision.desc()).first()

            if not revision:
                raise ValueError(f"No revision found for prompt {prompt_id}")

            # Verify dataset exists
            dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
            if not dataset:
                raise ValueError(f"Dataset {dataset_id} not found")

            table_name = dataset.sqlite_table_name

            # Get column names
            col_result = db.execute(text(f'PRAGMA table_info("{table_name}")'))
            columns = [row[1] for row in col_result]

            if not columns:
                raise ValueError("Dataset has no columns")

            # Build filter query
            search_pattern = f"%{filter_query}%"
            if filter_column:
                if filter_column not in columns:
                    raise ValueError(f"Column '{filter_column}' not found. Available: {columns}")
                where_clause = f'"{filter_column}" LIKE :pattern'
            else:
                conditions = [f'CAST("{col}" AS TEXT) LIKE :pattern' for col in columns]
                where_clause = " OR ".join(conditions)

            # Get matching row count
            count_sql = f'SELECT COUNT(*) FROM "{table_name}" WHERE {where_clause}'
            matching_count = db.execute(text(count_sql), {"pattern": search_pattern}).scalar() or 0

            if matching_count == 0:
                return {
                    "error": f"No rows match filter '{filter_query}'",
                    "dataset_id": dataset_id,
                    "dataset_name": dataset.name,
                    "filter_query": filter_query,
                    "matching_rows": 0
                }

            # Get default model: 1) context (agent session) 2) system setting 3) fallback
            if not model_name:
                model_name = self._get_default_model()
            if not model_name:
                setting = db.query(SystemSetting).filter(
                    SystemSetting.key == "active_llm_model"
                ).first()
                model_name = setting.value if setting else "azure-gpt-4.1"

            # Create a filtered batch job by creating job items only for matching rows
            from backend.prompt import PromptTemplateParser
            parser = PromptTemplateParser()
            template_params = parser.parse_template(revision.template)
            param_names = [p.name for p in template_params]

            # Get matching rows
            sql = f'SELECT * FROM "{table_name}" WHERE {where_clause}'
            matching_rows = db.execute(text(sql), {"pattern": search_pattern}).fetchall()

            # Create job manually with filtered items
            job = Job(
                job_type="batch",
                status="pending",
                prompt_revision_id=revision.id,
                model_name=model_name
            )
            db.add(job)
            db.flush()

            # Create job items for each matching row
            for row in matching_rows:
                input_params = {}
                for i, col_name in enumerate(columns):
                    if col_name in param_names:
                        input_params[col_name] = str(row[i]) if row[i] is not None else ""

                # Fill template
                filled_template = revision.template
                for param in template_params:
                    placeholder = "{{" + param.name + "}}"
                    if param.type != "TEXT5":
                        placeholder = "{{" + param.name + ":" + param.type + "}}"
                    value = input_params.get(param.name, "")
                    filled_template = filled_template.replace(placeholder, str(value))
                    filled_template = filled_template.replace("{{" + param.name + "}}", str(value))

                job_item = JobItem(
                    job_id=job.id,
                    input_params=input_params,
                    raw_prompt=filled_template,
                    status="pending"
                )
                db.add(job_item)

            db.commit()

            # Execute the job
            job_manager = JobManager(db)
            executed_job = job_manager.execute_job(
                job_id=job.id,
                model_name=model_name,
                temperature=temperature
            )

            # Get results
            item_count = len(executed_job.job_items) if executed_job.job_items else 0
            success_count = sum(1 for item in executed_job.job_items if item.status == "completed")
            error_count = sum(1 for item in executed_job.job_items if item.status == "error")

            return {
                "job_id": executed_job.id,
                "status": executed_job.status,
                "model_name": model_name,
                "dataset_id": dataset_id,
                "dataset_name": dataset.name,
                "filter_query": filter_query,
                "filter_column": filter_column,
                "matching_rows": matching_count,
                "item_count": item_count,
                "success_count": success_count,
                "error_count": error_count,
                "csv_link": f"http://localhost:9200/api/jobs/{executed_job.id}/csv"
            }
        finally:
            db.close()

    def _get_dataset_projects(self, dataset_id: int) -> Dict:
        """Get list of projects associated with a dataset."""
        db = SessionLocal()
        try:
            dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
            if not dataset:
                raise ValueError(f"Dataset {dataset_id} not found")

            # Get owner project
            owner = db.query(Project).filter(Project.id == dataset.project_id).first()

            # Get associated projects
            associations = db.query(ProjectDataset).filter(
                ProjectDataset.dataset_id == dataset_id
            ).all()
            associated_project_ids = [a.project_id for a in associations]

            # Build result with all projects
            all_project_ids = list(set([dataset.project_id] + associated_project_ids))
            projects = db.query(Project).filter(Project.id.in_(all_project_ids)).all()

            result = []
            for project in projects:
                result.append({
                    "id": project.id,
                    "name": project.name,
                    "is_owner": (project.id == dataset.project_id)
                })

            # Sort: owner first, then by name
            result.sort(key=lambda p: (not p["is_owner"], p["name"]))

            return {
                "dataset_id": dataset_id,
                "dataset_name": dataset.name,
                "projects": result,
                "total": len(result)
            }
        finally:
            db.close()

    def _update_dataset_projects(self, dataset_id: int, project_ids: List[int]) -> Dict:
        """Update the list of projects associated with a dataset."""
        db = SessionLocal()
        try:
            dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
            if not dataset:
                raise ValueError(f"Dataset {dataset_id} not found")

            # Validate all project IDs exist
            for project_id in project_ids:
                project = db.query(Project).filter(Project.id == project_id).first()
                if not project:
                    raise ValueError(f"Project {project_id} not found")

            # Remove all existing associations
            db.query(ProjectDataset).filter(ProjectDataset.dataset_id == dataset_id).delete()

            # Add new associations (excluding owner project)
            for project_id in project_ids:
                if project_id != dataset.project_id:
                    association = ProjectDataset(
                        project_id=project_id,
                        dataset_id=dataset_id
                    )
                    db.add(association)

            db.commit()

            # Return updated project list
            return self._get_dataset_projects(dataset_id)
        finally:
            db.close()

    def _add_dataset_to_project(self, dataset_id: int, project_id: int) -> Dict:
        """Add a dataset to a project."""
        db = SessionLocal()
        try:
            dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
            if not dataset:
                raise ValueError(f"Dataset {dataset_id} not found")

            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # Check if already associated (including owner)
            if project_id == dataset.project_id:
                return {
                    "success": True,
                    "message": "Project is already the owner",
                    "dataset_id": dataset_id,
                    "project_id": project_id
                }

            existing = db.query(ProjectDataset).filter(
                ProjectDataset.dataset_id == dataset_id,
                ProjectDataset.project_id == project_id
            ).first()

            if existing:
                return {
                    "success": True,
                    "message": "Association already exists",
                    "dataset_id": dataset_id,
                    "project_id": project_id
                }

            # Create new association
            association = ProjectDataset(
                project_id=project_id,
                dataset_id=dataset_id
            )
            db.add(association)
            db.commit()

            return {
                "success": True,
                "message": f"Dataset {dataset_id} added to project {project_id}",
                "dataset_id": dataset_id,
                "project_id": project_id,
                "project_name": project.name
            }
        finally:
            db.close()

    def _remove_dataset_from_project(self, dataset_id: int, project_id: int) -> Dict:
        """Remove a dataset from a project."""
        db = SessionLocal()
        try:
            dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
            if not dataset:
                raise ValueError(f"Dataset {dataset_id} not found")

            # Cannot remove owner
            if project_id == dataset.project_id:
                raise ValueError("Cannot remove owner project")

            # Find and delete association
            association = db.query(ProjectDataset).filter(
                ProjectDataset.dataset_id == dataset_id,
                ProjectDataset.project_id == project_id
            ).first()

            if not association:
                raise ValueError("Association not found")

            db.delete(association)
            db.commit()

            return {
                "success": True,
                "message": f"Dataset {dataset_id} removed from project {project_id}",
                "dataset_id": dataset_id,
                "project_id": project_id
            }
        finally:
            db.close()

    # ============== Hugging Face Dataset Handlers ==============

    def _search_huggingface_datasets(self, query: str, limit: int = 10) -> Dict:
        """Search HuggingFace datasets by keyword."""
        from backend.dataset.huggingface import HuggingFaceImporter
        db = SessionLocal()
        try:
            importer = HuggingFaceImporter(db)
            results = importer.search_datasets(query, limit=min(limit, 50))
            return {
                "query": query,
                "count": len(results),
                "datasets": results
            }
        finally:
            db.close()

    def _get_huggingface_dataset_info(self, name: str) -> Dict:
        """Get HuggingFace dataset info."""
        from backend.dataset.huggingface import HuggingFaceImporter
        db = SessionLocal()
        try:
            importer = HuggingFaceImporter(db)
            info = importer.get_dataset_info(name)
            return {
                "name": info.name,
                "description": info.description,
                "splits": info.splits,
                "features": info.features,
                "size_info": info.size_info,
                "is_gated": info.is_gated,
                "requires_auth": info.requires_auth,
                "warning": info.warning
            }
        finally:
            db.close()

    def _preview_huggingface_dataset(self, name: str, split: str, limit: int = 5) -> Dict:
        """Preview HuggingFace dataset rows."""
        from backend.dataset.huggingface import HuggingFaceImporter
        db = SessionLocal()
        try:
            importer = HuggingFaceImporter(db)
            return importer.get_preview(name, split, limit=limit)
        finally:
            db.close()

    def _import_huggingface_dataset(self, project_id: int, dataset_name: str,
                                     split: str, display_name: str,
                                     row_limit: int = None, columns: list = None) -> Dict:
        """Import HuggingFace dataset."""
        from backend.dataset.huggingface import HuggingFaceImporter
        db = SessionLocal()
        try:
            # Verify project exists
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise ValueError(f"Project {project_id} not found")

            importer = HuggingFaceImporter(db)
            dataset = importer.import_dataset(
                project_id=project_id,
                dataset_name=dataset_name,
                split=split,
                display_name=display_name,
                row_limit=row_limit,
                columns=columns
            )

            row_count = importer.get_row_count(dataset.sqlite_table_name)

            return {
                "success": True,
                "dataset_id": dataset.id,
                "name": dataset.name,
                "source": f"huggingface://{dataset_name}/{split}",
                "row_count": row_count,
                "project_id": project_id,
                "project_name": project.name
            }
        finally:
            db.close()

    # =========================================================================
    # Help Tool Handler
    # =========================================================================

    def _help(self, topic: str = None, entry: str = None) -> Dict[str, Any]:
        """
        MCPツールとシステムルールのヘルプを提供します。

        3つのモード:
        1. 引数なし: 全ツール・トピックの一覧
        2. topicのみ: ツールまたはトピックの詳細
        3. topic + entry: トピック内の特定項目の詳細

        Args:
            topic: ツール名またはトピック名
            entry: トピック内の項目名

        Returns:
            ヘルプ情報の辞書
        """
        from backend.mcp.help_data import (
            HELP_TOPICS,
            get_help_index,
            get_tool_help,
            get_topic_help,
            get_entry_help
        )

        # モード1: 引数なし → インデックス表示
        if topic is None:
            return get_help_index(self.tools)

        # ツール名かどうかチェック
        if topic in self.tools:
            # モード2a: ツールの詳細
            return get_tool_help(topic, self.tools)

        # トピック名かどうかチェック
        if topic in HELP_TOPICS:
            if entry is None:
                # モード2b: トピックの概要
                return get_topic_help(topic)
            else:
                # モード3: トピック内の項目詳細
                return get_entry_help(topic, entry)

        # 不明なトピック
        return {
            "error": f"不明なトピック: '{topic}'",
            "hint": "help() で利用可能なツールとトピックを確認してください",
            "available_topics": list(HELP_TOPICS.keys()),
            "example_tools": ["list_projects", "create_workflow", "execute_prompt"]
        }


# Singleton registry
_tool_registry: Optional[MCPToolRegistry] = None


def get_tool_registry() -> MCPToolRegistry:
    """Get the singleton tool registry."""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = MCPToolRegistry()
    return _tool_registry

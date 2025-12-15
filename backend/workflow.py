"""Workflow execution engine for multi-step prompt pipelines.

Allows chaining multiple projects (prompts) together,
with output from one step feeding into the next.

Supports control flow statements:
- SET: Variable assignment
- IF/ELIF/ELSE/ENDIF: Conditional branching
- LOOP/ENDLOOP: Loop with condition
- FOREACH/ENDFOREACH: Iterate over list
- BREAK/CONTINUE: Loop control
"""

import json
import logging
import random
import re
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from sqlalchemy.orm import Session

from .database.models import (
    Workflow, WorkflowStep, WorkflowJob, WorkflowJobStep,
    Project, ProjectRevision, Prompt, PromptRevision, Job, JobItem
)
from .job import JobManager
from .prompt import PromptTemplateParser, get_message_parser

logger = logging.getLogger(__name__)


class WorkflowManager:
    """Manages workflow creation and execution.

    Supports sequential execution with step output passing:
    - {{step1.field}} - Reference output from step named "step1"
    - {{input.param}} - Reference initial input parameter
    - {{vars.variable}} - Reference workflow variable
    - sum({{step1.score}}, {{step2.score}}) - Calculate sum of referenced values

    Control flow support:
    - SET: Variable assignment ({{vars.name}})
    - IF/ELIF/ELSE/ENDIF: Conditional branching
    - LOOP/ENDLOOP: Loop with condition
    - FOREACH/ENDFOREACH: Iterate over list
    - BREAK/CONTINUE: Loop control
    """

    # Pattern to match step references: {{step_name.field_name}}
    STEP_REF_PATTERN = re.compile(r'\{\{(\w+)\.(\w+)\}\}')

    # Pattern to match formula expressions: func_name(args)
    # Supported functions: sum, upper, lower, trim, length, slice, replace,
    # split, join, concat, default, contains, startswith, endswith, count,
    # left, right, repeat, reverse, capitalize, title, lstrip, rstrip
    FORMULA_PATTERN = re.compile(
        r'^(sum|upper|lower|trim|length|len|slice|substr|substring|replace|'
        r'split|join|concat|default|ifempty|contains|startswith|endswith|'
        r'count|left|right|repeat|reverse|capitalize|title|lstrip|rstrip|'
        r'shuffle|debug|calc)\((.+)\)$',
        re.IGNORECASE
    )

    # Available string functions for documentation/UI
    STRING_FUNCTIONS = {
        'upper': {'args': 1, 'desc': '大文字変換 / Convert to uppercase', 'example': 'upper({{step.text}})'},
        'lower': {'args': 1, 'desc': '小文字変換 / Convert to lowercase', 'example': 'lower({{step.text}})'},
        'trim': {'args': 1, 'desc': '前後空白削除 / Remove leading/trailing whitespace', 'example': 'trim({{step.text}})'},
        'lstrip': {'args': 1, 'desc': '先頭空白削除 / Remove leading whitespace', 'example': 'lstrip({{step.text}})'},
        'rstrip': {'args': 1, 'desc': '末尾空白削除 / Remove trailing whitespace', 'example': 'rstrip({{step.text}})'},
        'length': {'args': 1, 'desc': '文字数 / String length', 'example': 'length({{step.text}})'},
        'capitalize': {'args': 1, 'desc': '先頭大文字 / Capitalize first letter', 'example': 'capitalize({{step.text}})'},
        'title': {'args': 1, 'desc': '各単語先頭大文字 / Title case', 'example': 'title({{step.text}})'},
        'reverse': {'args': 1, 'desc': '文字列反転 / Reverse string', 'example': 'reverse({{step.text}})'},
        'slice': {'args': '2-3', 'desc': '部分文字列 / Extract substring', 'example': 'slice({{step.text}}, 0, 10)'},
        'left': {'args': 2, 'desc': '先頭N文字 / Left N characters', 'example': 'left({{step.text}}, 5)'},
        'right': {'args': 2, 'desc': '末尾N文字 / Right N characters', 'example': 'right({{step.text}}, 5)'},
        'replace': {'args': 3, 'desc': '置換 / Replace substring', 'example': 'replace({{step.text}}, old, new)'},
        'repeat': {'args': 2, 'desc': '繰り返し / Repeat N times', 'example': 'repeat({{step.text}}, 3)'},
        'split': {'args': 2, 'desc': '分割(JSON配列) / Split into array', 'example': 'split({{step.text}}, ,)'},
        'join': {'args': 2, 'desc': '結合 / Join array elements', 'example': 'join({{step.items}}, ,)'},
        'concat': {'args': '2+', 'desc': '連結 / Concatenate strings', 'example': 'concat({{step1.a}}, -, {{step2.b}})'},
        'default': {'args': 2, 'desc': '空の場合のデフォルト値 / Default if empty', 'example': 'default({{step.text}}, N/A)'},
        'contains': {'args': 2, 'desc': '含むか / Check if contains', 'example': 'contains({{step.text}}, word)'},
        'startswith': {'args': 2, 'desc': '先頭一致 / Check if starts with', 'example': 'startswith({{step.text}}, prefix)'},
        'endswith': {'args': 2, 'desc': '末尾一致 / Check if ends with', 'example': 'endswith({{step.text}}, suffix)'},
        'count': {'args': 2, 'desc': '出現回数 / Count occurrences', 'example': 'count({{step.text}}, a)'},
        'sum': {'args': '2+', 'desc': '合計 / Sum of numbers', 'example': 'sum({{step1.score}}, {{step2.score}})'},
        'shuffle': {'args': '1-2', 'desc': 'シャッフル / Shuffle (1引数:文字, 2引数:デリミタ分割)', 'example': 'shuffle({{step.items}}, ;)'},
        'calc': {'args': 1, 'desc': '計算式評価 / Evaluate arithmetic expression', 'example': 'calc({{vars.x}} + 1)'},
        'debug': {'args': '1+', 'desc': 'デバッグ出力 / Debug output to log', 'example': 'debug({{step.result}})'},
    }

    # Step types for control flow
    CONTROL_FLOW_TYPES = {'set', 'if', 'elif', 'else', 'endif', 'loop', 'endloop', 'foreach', 'endforeach', 'break', 'continue'}
    BLOCK_START_TYPES = {'if', 'loop', 'foreach'}
    BLOCK_END_TYPES = {'endif', 'endloop', 'endforeach'}

    # Default max iterations for loops to prevent infinite loops
    DEFAULT_MAX_ITERATIONS = 100

    def __init__(self, db: Session):
        """Initialize workflow manager.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.job_manager = JobManager(db)
        self.prompt_parser = PromptTemplateParser()

    def create_workflow(self, name: str, description: str = "", project_id: int = None, auto_context: bool = False) -> Workflow:
        """Create a new workflow.

        Args:
            name: Workflow name
            description: Optional description
            project_id: Optional project ID to associate this workflow with
            auto_context: If True, automatically include previous steps' USER/ASSISTANT in CONTEXT

        Returns:
            Created Workflow object
        """
        workflow = Workflow(name=name, description=description, project_id=project_id, auto_context=1 if auto_context else 0)
        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)
        logger.info(f"Created workflow: {workflow.id} - {name} (project_id={project_id}, auto_context={auto_context})")
        return workflow

    def update_workflow(self, workflow_id: int, name: str = None, description: str = None, project_id: int = None, auto_context: bool = None) -> Workflow:
        """Update workflow metadata.

        Args:
            workflow_id: Workflow ID
            name: New name (optional)
            description: New description (optional)
            project_id: Project ID to associate (optional)
            auto_context: Auto-context setting (optional)

        Returns:
            Updated Workflow object
        """
        workflow = self.db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        if name is not None:
            workflow.name = name
        if description is not None:
            workflow.description = description
        if project_id is not None:
            workflow.project_id = project_id
        if auto_context is not None:
            workflow.auto_context = 1 if auto_context else 0
        workflow.updated_at = datetime.utcnow().isoformat()

        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    def delete_workflow(self, workflow_id: int) -> bool:
        """Delete a workflow and all its steps.

        Args:
            workflow_id: Workflow ID

        Returns:
            True if deleted
        """
        workflow = self.db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        self.db.delete(workflow)
        self.db.commit()
        logger.info(f"Deleted workflow: {workflow_id}")
        return True

    def add_step(
        self,
        workflow_id: int,
        step_name: str,
        project_id: int = None,
        prompt_id: int = None,
        step_order: int = None,
        input_mapping: Dict[str, str] = None,
        execution_mode: str = "sequential",
        step_type: str = "prompt",
        condition_config: Dict[str, Any] = None
    ) -> WorkflowStep:
        """Add a step to a workflow.

        Args:
            workflow_id: Workflow ID
            step_name: Unique name for this step (e.g., "step1", "summarize")
            project_id: Project to use for this step (required for prompt steps)
            prompt_id: Prompt to use for this step (NEW ARCHITECTURE)
            step_order: Execution order (auto-assigned if None)
            input_mapping: Parameter mapping {"param": "{{step1.field}}"}
            execution_mode: "sequential" (default) or "parallel" (future)
            step_type: Step type (prompt/set/if/elif/else/endif/loop/endloop/foreach/endforeach/break/continue)
            condition_config: Control flow configuration (for non-prompt steps)

        Returns:
            Created WorkflowStep object

        Raises:
            ValueError: If step_name is invalid, reserved, or duplicate
        """
        # Validate step name format (must start with letter, alphanumeric + underscore)
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', step_name):
            raise ValueError(f"Invalid step name '{step_name}': must start with a letter and contain only alphanumeric characters and underscores")

        # Check for reserved names
        reserved_names = ['input', 'vars']  # 'input' and 'vars' are reserved in step context
        if step_name.lower() in reserved_names:
            raise ValueError(f"Step name '{step_name}' is reserved and cannot be used")

        # Validate workflow exists
        workflow = self.db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        # Check for duplicate step name within the workflow
        existing_step = self.db.query(WorkflowStep).filter(
            WorkflowStep.workflow_id == workflow_id,
            WorkflowStep.step_name == step_name
        ).first()
        if existing_step:
            raise ValueError(f"Step name '{step_name}' already exists in this workflow")

        # For prompt steps, validate project and prompt exist
        if step_type == "prompt" or step_type is None:
            if project_id:
                project = self.db.query(Project).filter(Project.id == project_id).first()
                if not project:
                    raise ValueError(f"Project {project_id} not found")

            if prompt_id:
                prompt = self.db.query(Prompt).filter(Prompt.id == prompt_id).first()
                if not prompt:
                    raise ValueError(f"Prompt {prompt_id} not found")

        # Auto-assign step order if not provided
        if step_order is None:
            max_order = self.db.query(WorkflowStep).filter(
                WorkflowStep.workflow_id == workflow_id
            ).count()
            step_order = max_order + 1

        step = WorkflowStep(
            workflow_id=workflow_id,
            step_order=step_order,
            step_name=step_name,
            step_type=step_type or "prompt",
            project_id=project_id,
            prompt_id=prompt_id,
            execution_mode=execution_mode,
            input_mapping=json.dumps(input_mapping or {}, ensure_ascii=False),
            condition_config=json.dumps(condition_config or {}, ensure_ascii=False) if condition_config else None
        )
        self.db.add(step)
        self.db.commit()
        self.db.refresh(step)

        logger.info(f"Added step to workflow {workflow_id}: {step_name} (order={step_order}, type={step_type}, prompt_id={prompt_id})")
        return step

    def update_step(
        self,
        step_id: int,
        step_name: str = None,
        project_id: int = None,
        prompt_id: int = None,
        step_order: int = None,
        input_mapping: Dict[str, str] = None,
        step_type: str = None,
        condition_config: Dict[str, Any] = None
    ) -> WorkflowStep:
        """Update a workflow step.

        Args:
            step_id: Step ID
            step_name: New step name (optional)
            project_id: New project ID (optional)
            prompt_id: New prompt ID (optional, NEW ARCHITECTURE)
            step_order: New order (optional)
            input_mapping: New input mapping (optional)
            step_type: New step type (optional)
            condition_config: New control flow config (optional)

        Returns:
            Updated WorkflowStep object
        """
        step = self.db.query(WorkflowStep).filter(WorkflowStep.id == step_id).first()
        if not step:
            raise ValueError(f"Step {step_id} not found")

        if step_name is not None:
            step.step_name = step_name
        if project_id is not None:
            step.project_id = project_id
        if prompt_id is not None:
            step.prompt_id = prompt_id
        if step_order is not None:
            step.step_order = step_order
        if input_mapping is not None:
            step.input_mapping = json.dumps(input_mapping, ensure_ascii=False)
        if step_type is not None:
            step.step_type = step_type
        if condition_config is not None:
            step.condition_config = json.dumps(condition_config, ensure_ascii=False)

        self.db.commit()
        self.db.refresh(step)
        return step

    def remove_step(self, step_id: int) -> bool:
        """Remove a step from a workflow.

        Args:
            step_id: Step ID

        Returns:
            True if removed
        """
        step = self.db.query(WorkflowStep).filter(WorkflowStep.id == step_id).first()
        if not step:
            raise ValueError(f"Step {step_id} not found")

        workflow_id = step.workflow_id
        self.db.delete(step)
        self.db.commit()

        # Renumber remaining steps
        self._renumber_steps(workflow_id)
        return True

    def _renumber_steps(self, workflow_id: int):
        """Renumber steps after deletion to maintain order."""
        steps = self.db.query(WorkflowStep).filter(
            WorkflowStep.workflow_id == workflow_id
        ).order_by(WorkflowStep.step_order).all()

        for i, step in enumerate(steps, 1):
            step.step_order = i
        self.db.commit()

    def get_workflow(self, workflow_id: int) -> Optional[Workflow]:
        """Get a workflow by ID.

        Args:
            workflow_id: Workflow ID

        Returns:
            Workflow object or None
        """
        return self.db.query(Workflow).filter(Workflow.id == workflow_id).first()

    def list_workflows(self) -> List[Workflow]:
        """List all workflows.

        Returns:
            List of Workflow objects
        """
        return self.db.query(Workflow).order_by(Workflow.created_at.desc()).all()

    def execute_workflow(
        self,
        workflow_id: int,
        input_params: Dict[str, str],
        model_name: str = None,
        temperature: float = 0.7,
        workflow_job_id: int = None
    ) -> WorkflowJob:
        """Execute a workflow with given input parameters.

        Supports control flow statements:
        - SET: Variable assignment
        - IF/ELIF/ELSE/ENDIF: Conditional branching
        - LOOP/ENDLOOP: Loop with condition
        - FOREACH/ENDFOREACH: Iterate over list
        - BREAK/CONTINUE: Loop control

        Args:
            workflow_id: Workflow ID
            input_params: Initial input parameters
            model_name: LLM model to use
            temperature: Temperature for LLM
            workflow_job_id: Existing workflow job ID to use (optional)

        Returns:
            WorkflowJob with execution results
        """
        workflow = self.db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        start_time = datetime.utcnow()

        # Use existing job or create new one
        if workflow_job_id:
            workflow_job = self.db.query(WorkflowJob).filter(WorkflowJob.id == workflow_job_id).first()
            if not workflow_job:
                raise ValueError(f"WorkflowJob {workflow_job_id} not found")
            workflow_job.status = "running"
            workflow_job.started_at = start_time.isoformat()
        else:
            # Create workflow job
            workflow_job = WorkflowJob(
                workflow_id=workflow_id,
                status="running",
                input_params=json.dumps(input_params, ensure_ascii=False),
                model_name=model_name,
                started_at=start_time.isoformat()
            )
            self.db.add(workflow_job)
        self.db.flush()

        logger.info(f"Starting workflow execution: {workflow_id}, job={workflow_job.id}")

        # Get steps ordered by step_order
        steps = list(self.db.query(WorkflowStep).filter(
            WorkflowStep.workflow_id == workflow_id
        ).order_by(WorkflowStep.step_order).all())

        if not steps:
            workflow_job.status = "error"
            workflow_job.merged_output = json.dumps({"error": "No steps in workflow"}, ensure_ascii=False)
            workflow_job.finished_at = datetime.utcnow().isoformat()
            self.db.commit()
            raise ValueError("Workflow has no steps")

        # Context to store step outputs
        step_context: Dict[str, Dict[str, Any]] = {}

        # Add initial input params to context (accessible as {{input.field}})
        step_context["input"] = input_params

        # Variables store for control flow (accessible as {{vars.name}})
        variables: Dict[str, Any] = {}
        step_context["vars"] = variables

        # Loop state tracking: stack of (loop_start_ip, iteration_count, max_iterations)
        loop_stack: List[Tuple[int, int, int]] = []

        # FOREACH state tracking: stack of (foreach_ip, items_list, current_index, item_var, index_var)
        foreach_stack: List[Tuple[int, List[Any], int, str, str]] = []

        # IF block tracking: stack of (took_branch) - True if a branch was taken in current IF block
        if_block_stack: List[bool] = []

        # Execution trace for debugging/visibility
        execution_trace: List[Dict[str, Any]] = []

        error_occurred = False
        error_message = None

        # Instruction pointer based execution
        ip = 0
        total_iterations = 0  # Safety counter for all loops combined

        while ip < len(steps):
            step = steps[ip]
            step_type = step.step_type or "prompt"
            step_start_time = datetime.utcnow()

            # Safety check for runaway loops
            total_iterations += 1
            if total_iterations > self.DEFAULT_MAX_ITERATIONS * 10:
                error_occurred = True
                error_message = f"Workflow exceeded maximum total iterations ({self.DEFAULT_MAX_ITERATIONS * 10})"
                logger.error(error_message)
                break

            try:
                logger.info(f"Executing step {step.step_order} ({step_type}): {step.step_name}")

                if step_type == "prompt":
                    # Execute prompt step (original behavior)
                    ip = self._execute_prompt_step(
                        step, steps, ip, input_params, step_context, workflow_job,
                        model_name, temperature, workflow
                    )
                    execution_trace.append({
                        "step_order": step.step_order,
                        "step_name": step.step_name,
                        "step_type": "prompt",
                        "action": "executed",
                        "prompt_name": step.prompt.name if step.prompt_id else None
                    })

                elif step_type == "set":
                    # Execute SET step
                    config = json.loads(step.condition_config or "{}")
                    assignments = config.get("assignments", {})
                    ip = self._execute_set_step(step, steps, ip, step_context, variables, workflow_job)
                    execution_trace.append({
                        "step_order": step.step_order,
                        "step_name": step.step_name,
                        "step_type": "set",
                        "action": "executed",
                        "assignments": {k: variables.get(k) for k in assignments.keys()}
                    })

                elif step_type == "if":
                    # Execute IF step
                    config = json.loads(step.condition_config or "{}")
                    ip, took_branch = self._execute_if_step(step, steps, ip, step_context)
                    if_block_stack.append(took_branch)
                    execution_trace.append({
                        "step_order": step.step_order,
                        "step_name": step.step_name,
                        "step_type": "if",
                        "action": "branch_taken" if took_branch else "branch_skipped",
                        "condition": f"{config.get('left', '')} {config.get('operator', '')} {config.get('right', '')}",
                        "result": took_branch
                    })

                elif step_type == "elif":
                    # Execute ELIF step
                    config = json.loads(step.condition_config or "{}")
                    if if_block_stack and if_block_stack[-1]:
                        # Previous branch was taken, skip to ENDIF
                        ip = self._find_matching_endif(steps, ip)
                        execution_trace.append({
                            "step_order": step.step_order,
                            "step_name": step.step_name,
                            "step_type": "elif",
                            "action": "skipped",
                            "reason": "previous_branch_taken"
                        })
                    else:
                        ip, took_branch = self._execute_if_step(step, steps, ip, step_context)
                        if if_block_stack:
                            if_block_stack[-1] = took_branch
                        execution_trace.append({
                            "step_order": step.step_order,
                            "step_name": step.step_name,
                            "step_type": "elif",
                            "action": "branch_taken" if took_branch else "branch_skipped",
                            "condition": f"{config.get('left', '')} {config.get('operator', '')} {config.get('right', '')}",
                            "result": took_branch
                        })

                elif step_type == "else":
                    # Execute ELSE step
                    if if_block_stack and if_block_stack[-1]:
                        # Previous branch was taken, skip to ENDIF
                        ip = self._find_matching_endif(steps, ip)
                        execution_trace.append({
                            "step_order": step.step_order,
                            "step_name": step.step_name,
                            "step_type": "else",
                            "action": "skipped",
                            "reason": "previous_branch_taken"
                        })
                    else:
                        ip += 1  # Continue into ELSE block
                        execution_trace.append({
                            "step_order": step.step_order,
                            "step_name": step.step_name,
                            "step_type": "else",
                            "action": "branch_taken"
                        })

                elif step_type == "endif":
                    # End of IF block
                    if if_block_stack:
                        if_block_stack.pop()
                    ip += 1
                    execution_trace.append({
                        "step_order": step.step_order,
                        "step_name": step.step_name,
                        "step_type": "endif",
                        "action": "executed"
                    })

                elif step_type == "loop":
                    # Execute LOOP step
                    config = json.loads(step.condition_config or "{}")
                    old_ip = ip
                    ip = self._execute_loop_step(step, steps, ip, step_context, loop_stack)
                    # Determine if loop was entered or exited
                    entered_loop = (ip == old_ip + 1)
                    iteration = 0
                    for loop_ip, count, _ in loop_stack:
                        if loop_ip == old_ip:
                            iteration = count
                            break
                    execution_trace.append({
                        "step_order": step.step_order,
                        "step_name": step.step_name,
                        "step_type": "loop",
                        "action": "loop_enter" if entered_loop else "loop_exit",
                        "condition": f"{config.get('left', '')} {config.get('operator', '')} {config.get('right', '')}",
                        "iteration": iteration
                    })

                elif step_type == "endloop":
                    # End of LOOP - go back to loop start
                    if loop_stack:
                        loop_start_ip, iteration_count, max_iterations = loop_stack[-1]
                        loop_stack[-1] = (loop_start_ip, iteration_count + 1, max_iterations)
                        ip = loop_start_ip  # Go back to LOOP to check condition
                        execution_trace.append({
                            "step_order": step.step_order,
                            "step_name": step.step_name,
                            "step_type": "endloop",
                            "action": "loop_continue",
                            "iteration": iteration_count + 1
                        })
                    else:
                        logger.warning(f"ENDLOOP without matching LOOP at step {step.step_order}")
                        ip += 1
                        execution_trace.append({
                            "step_order": step.step_order,
                            "step_name": step.step_name,
                            "step_type": "endloop",
                            "action": "executed",
                            "warning": "no_matching_loop"
                        })

                elif step_type == "foreach":
                    # Execute FOREACH step
                    config = json.loads(step.condition_config or "{}")
                    old_stack_len = len(foreach_stack)
                    ip = self._execute_foreach_step(step, steps, ip, step_context, variables, foreach_stack)
                    if len(foreach_stack) > old_stack_len:
                        # New foreach started
                        _, items, _, item_var, _ = foreach_stack[-1]
                        execution_trace.append({
                            "step_order": step.step_order,
                            "step_name": step.step_name,
                            "step_type": "foreach",
                            "action": "foreach_start",
                            "item_var": item_var,
                            "total_items": len(items),
                            "current_item": variables.get(item_var)
                        })
                    else:
                        # Empty list - skipped
                        execution_trace.append({
                            "step_order": step.step_order,
                            "step_name": step.step_name,
                            "step_type": "foreach",
                            "action": "foreach_skip",
                            "reason": "empty_list"
                        })

                elif step_type == "endforeach":
                    # End of FOREACH - process next item or exit
                    old_stack_len = len(foreach_stack)
                    current_idx = foreach_stack[-1][2] if foreach_stack else -1
                    ip = self._execute_endforeach_step(steps, ip, step_context, variables, foreach_stack)
                    if len(foreach_stack) < old_stack_len:
                        # Foreach completed
                        execution_trace.append({
                            "step_order": step.step_order,
                            "step_name": step.step_name,
                            "step_type": "endforeach",
                            "action": "foreach_complete",
                            "iterations_completed": current_idx + 1
                        })
                    elif foreach_stack:
                        # Continue to next item
                        _, items, idx, item_var, _ = foreach_stack[-1]
                        execution_trace.append({
                            "step_order": step.step_order,
                            "step_name": step.step_name,
                            "step_type": "endforeach",
                            "action": "foreach_next",
                            "current_index": idx,
                            "current_item": variables.get(item_var)
                        })

                elif step_type == "break":
                    # BREAK - exit innermost loop
                    if loop_stack:
                        loop_stack.pop()
                        ip = self._find_matching_endloop(steps, ip) + 1
                        execution_trace.append({
                            "step_order": step.step_order,
                            "step_name": step.step_name,
                            "step_type": "break",
                            "action": "break_loop"
                        })
                    elif foreach_stack:
                        foreach_stack.pop()
                        ip = self._find_matching_endforeach(steps, ip) + 1
                        execution_trace.append({
                            "step_order": step.step_order,
                            "step_name": step.step_name,
                            "step_type": "break",
                            "action": "break_foreach"
                        })
                    else:
                        logger.warning(f"BREAK outside of loop at step {step.step_order}")
                        ip += 1
                        execution_trace.append({
                            "step_order": step.step_order,
                            "step_name": step.step_name,
                            "step_type": "break",
                            "action": "break_no_loop",
                            "warning": "outside_of_loop"
                        })

                elif step_type == "continue":
                    # CONTINUE - go to end of innermost loop
                    if loop_stack:
                        ip = self._find_matching_endloop(steps, ip)
                        execution_trace.append({
                            "step_order": step.step_order,
                            "step_name": step.step_name,
                            "step_type": "continue",
                            "action": "continue_loop"
                        })
                    elif foreach_stack:
                        ip = self._find_matching_endforeach(steps, ip)
                        execution_trace.append({
                            "step_order": step.step_order,
                            "step_name": step.step_name,
                            "step_type": "continue",
                            "action": "continue_foreach"
                        })
                    else:
                        logger.warning(f"CONTINUE outside of loop at step {step.step_order}")
                        ip += 1
                        execution_trace.append({
                            "step_order": step.step_order,
                            "step_name": step.step_name,
                            "step_type": "continue",
                            "action": "continue_no_loop",
                            "warning": "outside_of_loop"
                        })

                else:
                    logger.warning(f"Unknown step type '{step_type}' at step {step.step_order}, treating as prompt")
                    ip = self._execute_prompt_step(
                        step, steps, ip, input_params, step_context, workflow_job,
                        model_name, temperature, workflow
                    )

            except Exception as e:
                logger.error(f"Step {step.step_name} failed: {str(e)}")
                error_occurred = True
                error_message = f"Step {step.step_name} failed: {str(e)}"
                break

            self.db.commit()

        # Merge all step outputs
        merged_output = self._merge_outputs(step_context)
        if error_occurred:
            merged_output["_error"] = error_message

        # Add execution trace for debugging/visibility
        merged_output["_execution_trace"] = execution_trace

        # Merge CSV outputs from all steps
        merged_csv = self._merge_csv_outputs(step_context)

        # Update workflow job
        end_time = datetime.utcnow()
        workflow_job.status = "error" if error_occurred else "done"
        workflow_job.merged_output = json.dumps(merged_output, ensure_ascii=False)
        workflow_job.merged_csv_output = merged_csv if merged_csv else None
        workflow_job.finished_at = end_time.isoformat()
        workflow_job.turnaround_ms = int((end_time - start_time).total_seconds() * 1000)

        self.db.commit()
        self.db.refresh(workflow_job)

        logger.info(f"Workflow execution finished: {workflow_job.status}, {workflow_job.turnaround_ms}ms")
        return workflow_job

    def _execute_prompt_step(
        self,
        step: WorkflowStep,
        steps: List[WorkflowStep],
        ip: int,
        input_params: Dict[str, str],
        step_context: Dict[str, Dict[str, Any]],
        workflow_job: WorkflowJob,
        model_name: str,
        temperature: float,
        workflow: Workflow
    ) -> int:
        """Execute a prompt step and return next instruction pointer.

        Args:
            step: Current step
            steps: All steps
            ip: Current instruction pointer
            input_params: Initial input parameters
            step_context: Step context with outputs
            workflow_job: WorkflowJob object
            model_name: LLM model name
            temperature: Temperature for LLM
            workflow: Workflow object

        Returns:
            Next instruction pointer
        """
        step_start_time = datetime.utcnow()

        # Resolve input parameters for this step
        step_input_params = self._resolve_step_inputs(step, input_params, step_context)

        # Create job step record
        job_step = WorkflowJobStep(
            workflow_job_id=workflow_job.id,
            workflow_step_id=step.id,
            step_order=step.step_order,
            status="running",
            input_params=json.dumps(step_input_params, ensure_ascii=False),
            started_at=step_start_time.isoformat()
        )
        self.db.add(job_step)
        self.db.flush()

        # Execute the step using existing JobManager
        output_fields, job_id = self._execute_step(
            step, step_input_params, model_name, temperature, step_context,
            auto_context=bool(workflow.auto_context)
        )

        # Store output in context for next step
        step_context[step.step_name] = output_fields

        # Update job step
        step_end_time = datetime.utcnow()
        job_step.job_id = job_id
        job_step.status = "done"
        job_step.output_fields = json.dumps(output_fields, ensure_ascii=False)
        job_step.finished_at = step_end_time.isoformat()
        job_step.turnaround_ms = int((step_end_time - step_start_time).total_seconds() * 1000)

        logger.info(f"Step {step.step_name} completed: {job_step.turnaround_ms}ms")

        return ip + 1

    def _execute_set_step(
        self,
        step: WorkflowStep,
        steps: List[WorkflowStep],
        ip: int,
        step_context: Dict[str, Dict[str, Any]],
        variables: Dict[str, Any],
        workflow_job: WorkflowJob
    ) -> int:
        """Execute a SET step to assign variables.

        Args:
            step: Current step
            steps: All steps
            ip: Current instruction pointer
            step_context: Step context with outputs
            variables: Variables store
            workflow_job: WorkflowJob object

        Returns:
            Next instruction pointer
        """
        config = json.loads(step.condition_config or "{}")
        assignments = config.get("assignments", {})

        for var_name, value_expr in assignments.items():
            # Resolve any variable references in the value
            resolved_value = self._substitute_step_refs(str(value_expr), step_context)

            # Try to parse as number if it looks like one
            try:
                if '.' in resolved_value:
                    variables[var_name] = float(resolved_value)
                else:
                    variables[var_name] = int(resolved_value)
            except ValueError:
                # Keep as string
                variables[var_name] = resolved_value

            logger.info(f"SET {var_name} = {variables[var_name]}")

        # Store SET results in step context
        step_context[step.step_name] = {"assigned": dict(variables)}

        return ip + 1

    def _execute_if_step(
        self,
        step: WorkflowStep,
        steps: List[WorkflowStep],
        ip: int,
        step_context: Dict[str, Dict[str, Any]]
    ) -> Tuple[int, bool]:
        """Execute an IF or ELIF step.

        Args:
            step: Current step
            steps: All steps
            ip: Current instruction pointer
            step_context: Step context with outputs

        Returns:
            Tuple of (next instruction pointer, whether condition was true)
        """
        condition_result = self._evaluate_condition(step, step_context)

        if condition_result:
            logger.info(f"IF/ELIF condition TRUE at step {step.step_order}")
            return ip + 1, True  # Continue into IF block
        else:
            logger.info(f"IF/ELIF condition FALSE at step {step.step_order}")
            # Skip to matching ELIF, ELSE, or ENDIF
            return self._find_matching_else_or_endif(steps, ip), False

    def _execute_loop_step(
        self,
        step: WorkflowStep,
        steps: List[WorkflowStep],
        ip: int,
        step_context: Dict[str, Dict[str, Any]],
        loop_stack: List[Tuple[int, int, int]]
    ) -> int:
        """Execute a LOOP step.

        Args:
            step: Current step
            steps: All steps
            ip: Current instruction pointer
            step_context: Step context with outputs
            loop_stack: Loop state stack

        Returns:
            Next instruction pointer
        """
        config = json.loads(step.condition_config or "{}")
        max_iterations = config.get("max_iterations", self.DEFAULT_MAX_ITERATIONS)

        # Check if we're returning to this LOOP (loop_stack has entry for this ip)
        current_loop = None
        for i, (loop_ip, count, max_iter) in enumerate(loop_stack):
            if loop_ip == ip:
                current_loop = i
                break

        if current_loop is not None:
            # Returning to loop - check iteration count
            _, iteration_count, _ = loop_stack[current_loop]
            if iteration_count >= max_iterations:
                logger.warning(f"LOOP reached max iterations ({max_iterations}) at step {step.step_order}")
                loop_stack.pop(current_loop)
                return self._find_matching_endloop(steps, ip) + 1
        else:
            # First entry into loop
            loop_stack.append((ip, 0, max_iterations))

        # Evaluate loop condition
        condition_result = self._evaluate_condition(step, step_context)

        if condition_result:
            logger.info(f"LOOP condition TRUE at step {step.step_order}")
            return ip + 1  # Enter loop body
        else:
            logger.info(f"LOOP condition FALSE at step {step.step_order}")
            # Remove from stack and skip to after ENDLOOP
            for i, (loop_ip, _, _) in enumerate(loop_stack):
                if loop_ip == ip:
                    loop_stack.pop(i)
                    break
            return self._find_matching_endloop(steps, ip) + 1

    def _execute_foreach_step(
        self,
        step: WorkflowStep,
        steps: List[WorkflowStep],
        ip: int,
        step_context: Dict[str, Dict[str, Any]],
        variables: Dict[str, Any],
        foreach_stack: List[Tuple[int, List[Any], int, str, str]]
    ) -> int:
        """Execute a FOREACH step.

        Args:
            step: Current step
            steps: All steps
            ip: Current instruction pointer
            step_context: Step context with outputs
            variables: Variables store
            foreach_stack: FOREACH state stack

        Returns:
            Next instruction pointer
        """
        config = json.loads(step.condition_config or "{}")

        # Check if we're returning to this FOREACH
        current_foreach = None
        for i, (foreach_ip, _, _, _, _) in enumerate(foreach_stack):
            if foreach_ip == ip:
                current_foreach = i
                break

        if current_foreach is not None:
            # This shouldn't happen - ENDFOREACH handles iteration
            # If we're here, something went wrong
            logger.warning(f"Unexpected return to FOREACH at step {step.step_order}")
            return ip + 1

        # First entry into FOREACH - parse source list
        source_expr = config.get("source", "")
        item_var = config.get("item_var", "item")
        index_var = config.get("index_var", "i")

        # Resolve the source expression
        resolved_source = self._substitute_step_refs(source_expr, step_context)

        # Parse as list
        items = self._parse_foreach_source(resolved_source)

        if not items:
            logger.info(f"FOREACH empty list at step {step.step_order}, skipping")
            return self._find_matching_endforeach(steps, ip) + 1

        # Initialize FOREACH state
        foreach_stack.append((ip, items, 0, item_var, index_var))

        # Set first item
        variables[item_var] = items[0]
        variables[index_var] = 0
        logger.info(f"FOREACH starting: {item_var}={items[0]}, {index_var}=0")

        return ip + 1

    def _execute_endforeach_step(
        self,
        steps: List[WorkflowStep],
        ip: int,
        step_context: Dict[str, Dict[str, Any]],
        variables: Dict[str, Any],
        foreach_stack: List[Tuple[int, List[Any], int, str, str]]
    ) -> int:
        """Execute an ENDFOREACH step.

        Args:
            steps: All steps
            ip: Current instruction pointer
            step_context: Step context with outputs
            variables: Variables store
            foreach_stack: FOREACH state stack

        Returns:
            Next instruction pointer
        """
        if not foreach_stack:
            logger.warning(f"ENDFOREACH without matching FOREACH at step {ip}")
            return ip + 1

        foreach_ip, items, current_index, item_var, index_var = foreach_stack[-1]
        next_index = current_index + 1

        if next_index >= len(items):
            # Finished all items
            foreach_stack.pop()
            logger.info(f"FOREACH completed all {len(items)} items")
            return ip + 1
        else:
            # Move to next item
            foreach_stack[-1] = (foreach_ip, items, next_index, item_var, index_var)
            variables[item_var] = items[next_index]
            variables[index_var] = next_index
            logger.info(f"FOREACH next: {item_var}={items[next_index]}, {index_var}={next_index}")
            return foreach_ip + 1  # Go back to first step after FOREACH

    def _parse_foreach_source(self, source: str) -> List[Any]:
        """Parse FOREACH source into a list.

        Args:
            source: Source string (JSON array or comma-separated values)

        Returns:
            List of items
        """
        source = source.strip()

        # Try parsing as JSON array first
        if source.startswith('['):
            try:
                return json.loads(source)
            except json.JSONDecodeError:
                pass

        # Try splitting by comma
        if ',' in source:
            return [item.strip() for item in source.split(',') if item.strip()]

        # Single value or empty
        if source:
            return [source]
        return []

    def _evaluate_condition(self, step: WorkflowStep, step_context: Dict[str, Dict[str, Any]]) -> bool:
        """Evaluate condition for IF/ELIF/LOOP steps.

        Args:
            step: Step with condition_config
            step_context: Step context with outputs

        Returns:
            Boolean result of condition evaluation
        """
        config = json.loads(step.condition_config or "{}")

        left = config.get("left", "")
        right = config.get("right", "")
        operator = config.get("operator", "==")

        # Resolve variable references
        left_resolved = self._substitute_step_refs(str(left), step_context)
        right_resolved = self._substitute_step_refs(str(right), step_context)

        logger.debug(f"Condition: '{left_resolved}' {operator} '{right_resolved}'")

        try:
            if operator == "==":
                return str(left_resolved) == str(right_resolved)
            elif operator == "!=":
                return str(left_resolved) != str(right_resolved)
            elif operator == ">":
                return float(left_resolved) > float(right_resolved)
            elif operator == "<":
                return float(left_resolved) < float(right_resolved)
            elif operator == ">=":
                return float(left_resolved) >= float(right_resolved)
            elif operator == "<=":
                return float(left_resolved) <= float(right_resolved)
            elif operator == "contains":
                return str(right_resolved) in str(left_resolved)
            elif operator == "empty":
                return not left_resolved or str(left_resolved).strip() == ""
            elif operator == "not_empty":
                return bool(left_resolved) and str(left_resolved).strip() != ""
            else:
                logger.warning(f"Unknown operator '{operator}', defaulting to ==")
                return str(left_resolved) == str(right_resolved)
        except (ValueError, TypeError) as e:
            logger.warning(f"Condition evaluation error: {e}")
            return False

    def _find_matching_else_or_endif(self, steps: List[WorkflowStep], ip: int) -> int:
        """Find matching ELIF, ELSE, or ENDIF for IF/ELIF at ip.

        Args:
            steps: All steps
            ip: Current instruction pointer (at IF or ELIF)

        Returns:
            Instruction pointer of matching ELIF, ELSE, or ENDIF
        """
        depth = 1
        i = ip + 1

        while i < len(steps):
            step_type = steps[i].step_type or "prompt"

            if step_type == "if":
                depth += 1
            elif step_type == "endif":
                depth -= 1
                if depth == 0:
                    return i
            elif depth == 1 and step_type in ("elif", "else"):
                return i

            i += 1

        return len(steps)  # End of workflow if no match

    def _find_matching_endif(self, steps: List[WorkflowStep], ip: int) -> int:
        """Find matching ENDIF for current IF block.

        Args:
            steps: All steps
            ip: Current instruction pointer

        Returns:
            Instruction pointer of matching ENDIF
        """
        depth = 1
        i = ip + 1

        while i < len(steps):
            step_type = steps[i].step_type or "prompt"

            if step_type == "if":
                depth += 1
            elif step_type == "endif":
                depth -= 1
                if depth == 0:
                    return i

            i += 1

        return len(steps)

    def _find_matching_endloop(self, steps: List[WorkflowStep], ip: int) -> int:
        """Find matching ENDLOOP for LOOP at ip.

        Args:
            steps: All steps
            ip: Current instruction pointer

        Returns:
            Instruction pointer of matching ENDLOOP
        """
        depth = 1
        i = ip + 1

        while i < len(steps):
            step_type = steps[i].step_type or "prompt"

            if step_type == "loop":
                depth += 1
            elif step_type == "endloop":
                depth -= 1
                if depth == 0:
                    return i

            i += 1

        return len(steps)

    def _find_matching_endforeach(self, steps: List[WorkflowStep], ip: int) -> int:
        """Find matching ENDFOREACH for FOREACH at ip.

        Args:
            steps: All steps
            ip: Current instruction pointer

        Returns:
            Instruction pointer of matching ENDFOREACH
        """
        depth = 1
        i = ip + 1

        while i < len(steps):
            step_type = steps[i].step_type or "prompt"

            if step_type == "foreach":
                depth += 1
            elif step_type == "endforeach":
                depth -= 1
                if depth == 0:
                    return i

            i += 1

        return len(steps)

    def _resolve_step_inputs(
        self,
        step: WorkflowStep,
        initial_params: Dict[str, str],
        step_context: Dict[str, Dict[str, Any]]
    ) -> Dict[str, str]:
        """Resolve input parameters for a step, substituting step references.

        Args:
            step: WorkflowStep to resolve inputs for
            initial_params: Initial input parameters
            step_context: Context with outputs from previous steps

        Returns:
            Resolved input parameters
        """
        # For first step, use initial params
        if step.step_order == 1:
            return dict(initial_params)

        # Start with empty dict for subsequent steps
        resolved = {}

        # Apply input mapping if defined
        if step.input_mapping:
            mapping = json.loads(step.input_mapping)
            for param_name, ref_pattern in mapping.items():
                resolved[param_name] = self._substitute_step_refs(
                    ref_pattern, step_context
                )

        return resolved

    def _substitute_step_refs(
        self,
        template: str,
        step_context: Dict[str, Dict[str, Any]]
    ) -> str:
        """Substitute {{step_name.field}} references and evaluate formulas.

        Args:
            template: Template string with {{step.field}} references or formulas
            step_context: Context with step outputs

        Returns:
            String with substituted values and evaluated formulas
        """
        # First check if it's a formula (e.g., sum(...), upper(...), etc.)
        formula_match = self.FORMULA_PATTERN.match(template.strip())
        if formula_match:
            func_name = formula_match.group(1).lower()
            args_str = formula_match.group(2)
            return str(self._evaluate_formula(func_name, args_str, step_context))

        # Otherwise, do normal variable substitution
        def replacer(match):
            step_name = match.group(1)
            field_name = match.group(2)

            if step_name in step_context:
                value = step_context[step_name].get(field_name, "")
                return str(value) if value is not None else ""
            return match.group(0)  # Keep original if not found

        return self.STEP_REF_PATTERN.sub(replacer, template)

    def _evaluate_formula(
        self,
        func_name: str,
        args_str: str,
        step_context: Dict[str, Dict[str, Any]]
    ) -> Any:
        """Evaluate a formula function with its arguments.

        Args:
            func_name: Function name (lowercase)
            args_str: Comma-separated arguments string
            step_context: Context with step outputs

        Returns:
            Result of the function evaluation
        """
        # Parse arguments
        args = self._parse_function_args(args_str, step_context)

        try:
            # Numeric functions
            if func_name == "sum":
                return self._evaluate_sum(args_str, step_context)

            # Single-argument string functions
            if func_name == "upper":
                return str(args[0]).upper() if args else ""

            if func_name == "lower":
                return str(args[0]).lower() if args else ""

            if func_name == "trim":
                return str(args[0]).strip() if args else ""

            if func_name == "lstrip":
                return str(args[0]).lstrip() if args else ""

            if func_name == "rstrip":
                return str(args[0]).rstrip() if args else ""

            if func_name in ("length", "len"):
                return len(str(args[0])) if args else 0

            if func_name == "capitalize":
                return str(args[0]).capitalize() if args else ""

            if func_name == "title":
                return str(args[0]).title() if args else ""

            if func_name == "reverse":
                return str(args[0])[::-1] if args else ""

            # Two-argument functions
            if func_name in ("slice", "substr", "substring"):
                if len(args) >= 2:
                    text = str(args[0])
                    start = int(args[1])
                    end = int(args[2]) if len(args) >= 3 else None
                    return text[start:end]
                return str(args[0]) if args else ""

            if func_name == "left":
                if len(args) >= 2:
                    text = str(args[0])
                    n = int(args[1])
                    return text[:n]
                return str(args[0]) if args else ""

            if func_name == "right":
                if len(args) >= 2:
                    text = str(args[0])
                    n = int(args[1])
                    return text[-n:] if n > 0 else ""
                return str(args[0]) if args else ""

            if func_name == "repeat":
                if len(args) >= 2:
                    text = str(args[0])
                    n = int(args[1])
                    return text * max(0, min(n, 1000))  # Limit repetition
                return str(args[0]) if args else ""

            if func_name == "replace":
                if len(args) >= 3:
                    text = str(args[0])
                    old = str(args[1])
                    new = str(args[2])
                    return text.replace(old, new)
                return str(args[0]) if args else ""

            if func_name == "split":
                if len(args) >= 2:
                    text = str(args[0])
                    delimiter = str(args[1])
                    result = text.split(delimiter)
                    return json.dumps(result, ensure_ascii=False)
                return json.dumps([str(args[0])], ensure_ascii=False) if args else "[]"

            if func_name == "join":
                if len(args) >= 2:
                    items = args[0]
                    delimiter = str(args[1])
                    # Handle JSON array string or list
                    if isinstance(items, str):
                        try:
                            items = json.loads(items)
                        except json.JSONDecodeError:
                            items = [items]
                    if isinstance(items, list):
                        return delimiter.join(str(item) for item in items)
                    return str(items)
                return str(args[0]) if args else ""

            if func_name == "concat":
                return "".join(str(arg) for arg in args)

            if func_name in ("default", "ifempty"):
                if len(args) >= 2:
                    value = str(args[0]).strip() if args[0] else ""
                    default_val = str(args[1])
                    return value if value else default_val
                return str(args[0]) if args else ""

            if func_name == "contains":
                if len(args) >= 2:
                    text = str(args[0])
                    substring = str(args[1])
                    return "true" if substring in text else "false"
                return "false"

            if func_name == "startswith":
                if len(args) >= 2:
                    text = str(args[0])
                    prefix = str(args[1])
                    return "true" if text.startswith(prefix) else "false"
                return "false"

            if func_name == "endswith":
                if len(args) >= 2:
                    text = str(args[0])
                    suffix = str(args[1])
                    return "true" if text.endswith(suffix) else "false"
                return "false"

            if func_name == "count":
                if len(args) >= 2:
                    text = str(args[0])
                    substring = str(args[1])
                    return text.count(substring)
                return 0

            if func_name == "shuffle":
                if args:
                    text = str(args[0])
                    if len(args) >= 2:
                        # Shuffle with delimiter
                        delimiter = str(args[1])
                        if not delimiter:
                            return text
                        parts = text.split(delimiter)
                        random.shuffle(parts)
                        return delimiter.join(parts)
                    else:
                        # Shuffle characters
                        chars = list(text)
                        random.shuffle(chars)
                        return "".join(chars)
                return ""

            if func_name == "calc":
                # Evaluate simple arithmetic expressions
                if args:
                    expr = str(args[0])
                    # Only allow safe characters for arithmetic
                    safe_expr = ''.join(c for c in expr if c in '0123456789+-*/.() ')
                    try:
                        # Use eval with restricted globals for safety
                        result = eval(safe_expr, {"__builtins__": {}}, {})
                        # Return integer if result is whole number
                        if isinstance(result, float) and result.is_integer():
                            return int(result)
                        return result
                    except Exception as e:
                        logger.warning(f"calc() evaluation error: {e}, expr: {safe_expr}")
                        return 0
                return 0

            if func_name == "debug":
                # Debug output - logs all arguments and returns them concatenated
                debug_output = " | ".join(str(arg) for arg in args)
                logger.info(f"[DEBUG] {debug_output}")
                return debug_output

            # Unknown function - return empty string
            logger.warning(f"Unknown formula function: {func_name}")
            return ""

        except Exception as e:
            logger.error(f"Error evaluating formula {func_name}({args_str}): {e}")
            return ""

    def _parse_function_args(
        self,
        args_str: str,
        step_context: Dict[str, Dict[str, Any]]
    ) -> List[Any]:
        """Parse function arguments with proper handling of commas and braces.

        Args:
            args_str: Comma-separated arguments string
            step_context: Context with step outputs

        Returns:
            List of resolved argument values
        """
        args = []
        current_arg = ""
        brace_depth = 0

        for char in args_str:
            if char == '{':
                brace_depth += 1
                current_arg += char
            elif char == '}':
                brace_depth -= 1
                current_arg += char
            elif char == ',' and brace_depth == 0:
                args.append(current_arg.strip())
                current_arg = ""
            else:
                current_arg += char

        if current_arg.strip():
            args.append(current_arg.strip())

        # Resolve variable references in each argument
        resolved_args = []
        for arg in args:
            resolved = self._substitute_single_ref(arg, step_context)
            resolved_args.append(resolved)

        return resolved_args

    def _get_unmapped_params_content(
        self,
        template: str,
        input_params: Dict[str, str]
    ) -> Optional[str]:
        """Get content for input parameters that are not in the template.

        This allows workflow-defined parameters (especially CONTEXT) to be
        automatically prepended to the prompt even if the template doesn't
        have a corresponding {{PARAM}} placeholder.

        Args:
            template: The prompt template
            input_params: Input parameters from input_mapping

        Returns:
            String content to prepend, or None if no unmapped params
        """
        if not template or not input_params:
            return None

        # Find all {{PARAM}} or {{PARAM:TYPE}} patterns in template
        # Pattern matches: {{NAME}} or {{NAME:TYPE}} or {{NAME:TYPE|...}}
        param_pattern = re.compile(r'\{\{([a-zA-Z0-9_]+)(?::[^}|]+)?(?:\|[^}]*)?\}\}')
        template_params = set(param_pattern.findall(template))

        # Find params in input_params that are not in template
        unmapped_params = []
        for param_name, param_value in input_params.items():
            if param_name not in template_params and param_value:
                unmapped_params.append((param_name, param_value))

        if not unmapped_params:
            return None

        # Build content from unmapped params
        # For now, just concatenate values (CONTEXT typically has [USER]/[ASSISTANT] markers)
        contents = []
        for param_name, param_value in unmapped_params:
            # Just use the value directly - it should already be formatted
            # (e.g., CONTEXT has [USER]/[ASSISTANT] markers)
            contents.append(str(param_value))

        return "\n".join(contents) if contents else None

    def _evaluate_sum(
        self,
        args_str: str,
        step_context: Dict[str, Dict[str, Any]]
    ) -> float:
        """Evaluate sum function with variable references.

        Args:
            args_str: Comma-separated arguments with {{step.field}} references
            step_context: Context with step outputs

        Returns:
            Sum of all numeric values

        Examples:
            sum({{step1.score}}, {{step2.score}})
            sum({{step1.count}}, 10, {{step2.count}})
        """
        # Split by comma, but handle nested references carefully
        # Simple split for now (works with {{step.field}}, literal numbers)
        args = []
        current_arg = ""
        brace_depth = 0

        for char in args_str:
            if char == '{':
                brace_depth += 1
                current_arg += char
            elif char == '}':
                brace_depth -= 1
                current_arg += char
            elif char == ',' and brace_depth == 0:
                args.append(current_arg.strip())
                current_arg = ""
            else:
                current_arg += char

        if current_arg.strip():
            args.append(current_arg.strip())

        total = 0.0

        for arg in args:
            # Substitute variable references
            resolved = self._substitute_single_ref(arg, step_context)

            # Try to convert to number
            try:
                value = float(resolved)
                total += value
            except (ValueError, TypeError):
                logger.warning(f"sum(): Cannot convert '{resolved}' (from '{arg}') to number, skipping")
                continue

        logger.debug(f"sum() evaluated: args={args} -> {total}")
        return total

    def _substitute_single_ref(
        self,
        template: str,
        step_context: Dict[str, Dict[str, Any]]
    ) -> str:
        """Substitute all {{step.field}} references in template.

        Args:
            template: Template string that may contain references
            step_context: Context with step outputs

        Returns:
            String with all references resolved
        """
        def replacer(match):
            step_name = match.group(1)
            field_name = match.group(2)

            if step_name in step_context:
                value = step_context[step_name].get(field_name, "")
                return str(value) if value is not None else ""
            return match.group(0)  # Keep original if not found

        # Replace all {{step.field}} references in the template
        return self.STEP_REF_PATTERN.sub(replacer, template)

    def _execute_step(
        self,
        step: WorkflowStep,
        input_params: Dict[str, str],
        model_name: str = None,
        temperature: float = 0.7,
        step_context: Dict[str, Dict[str, Any]] = None,
        auto_context: bool = False
    ) -> tuple[Dict[str, Any], int]:
        """Execute a single step and return parsed output fields.

        Args:
            step: WorkflowStep to execute
            input_params: Input parameters for this step
            model_name: LLM model to use
            temperature: Temperature for LLM
            step_context: Context with outputs from previous steps (for template substitution)
            auto_context: If True, automatically build CONTEXT from previous steps' conversation

        Returns:
            Tuple of (output_fields dict, job_id)
        """
        revision = None
        prompt_revision = None

        # NEW ARCHITECTURE: Use PromptRevision if prompt_id is set
        if step.prompt_id:
            # Refresh session to ensure we get the latest data
            self.db.expire_all()

            prompt_revision = self.db.query(PromptRevision).filter(
                PromptRevision.prompt_id == step.prompt_id
            ).order_by(PromptRevision.revision.desc()).first()

            if not prompt_revision:
                raise ValueError(f"No revision found for prompt {step.prompt_id}")

            logger.info(f"Step {step.step_name}: Using prompt {step.prompt_id} revision {prompt_revision.revision} (id={prompt_revision.id})")
        else:
            # OLD ARCHITECTURE: Fall back to ProjectRevision
            self.db.expire_all()

            revision = self.db.query(ProjectRevision).filter(
                ProjectRevision.project_id == step.project_id
            ).order_by(ProjectRevision.revision.desc()).first()

            if not revision:
                raise ValueError(f"No revision found for project {step.project_id}")

            logger.info(f"Step {step.step_name}: Using project {step.project_id} revision {revision.revision} (id={revision.id})")

        # Substitute {{step.field}} references in prompt template if step_context is provided
        template_override = None
        if prompt_revision:
            original_template = prompt_revision.prompt_template
        elif revision:
            original_template = revision.prompt_template
        else:
            original_template = None

        working_template = original_template

        if step_context and original_template:
            substituted_template = self._substitute_step_refs(original_template, step_context)
            if substituted_template != original_template:
                logger.info(f"Step {step.step_name}: Substituted step references in template")
                working_template = substituted_template

        # Auto-prepend input_mapping parameters that are not in the template
        # This allows workflow-defined parameters (like CONTEXT) to be sent to LLM
        # even if the prompt template doesn't have {{CONTEXT}} placeholder
        if working_template and input_params:
            logger.debug(f"Step {step.step_name}: Checking for unmapped params. input_params keys: {list(input_params.keys())}")
            prepend_content = self._get_unmapped_params_content(working_template, input_params)
            logger.debug(f"Step {step.step_name}: prepend_content = {prepend_content[:100] if prepend_content else None}...")
            if prepend_content:
                working_template = prepend_content + "\n\n" + working_template
                logger.info(f"Step {step.step_name}: Auto-prepended unmapped parameters to template")

        if working_template and working_template != original_template:
            template_override = working_template

        # Create and execute job using existing JobManager
        if prompt_revision:
            # NEW ARCHITECTURE: Use prompt_revision_id
            job = self.job_manager.create_single_job(
                prompt_revision_id=prompt_revision.id,
                input_params=input_params,
                repeat=1,
                model_name=model_name,
                template_override=template_override
            )
        else:
            # OLD ARCHITECTURE: Use project_revision_id
            job = self.job_manager.create_single_job(
                project_revision_id=revision.id,
                input_params=input_params,
                repeat=1,
                model_name=model_name,
                template_override=template_override
            )

        # Execute the job
        executed_job = self.job_manager.execute_job(
            job_id=job.id,
            model_name=model_name,
            include_csv_header=True,
            temperature=temperature
        )

        # Extract parsed fields from first job item
        job_items = self.db.query(JobItem).filter(
            JobItem.job_id == executed_job.id
        ).all()

        if not job_items:
            raise ValueError(f"No job items created for step {step.step_name}")

        job_item = job_items[0]
        if job_item.status != "done":
            raise ValueError(f"Step execution failed: {job_item.error_message}")

        # Parse response
        parsed = {}
        if job_item.parsed_response:
            parsed = json.loads(job_item.parsed_response)

        # Return fields plus raw response (include csv_output if present)
        result = {
            "raw": job_item.raw_response,
            "parsed": parsed.get("parsed", False),
            **parsed.get("fields", {})
        }
        # Include csv_output and csv_header if present (from csv_template parser)
        if "csv_output" in parsed:
            result["csv_output"] = parsed["csv_output"]
        if "csv_header" in parsed:
            result["csv_header"] = parsed["csv_header"]

        # Extract SYSTEM/USER/ASSISTANT content from raw_prompt using message parser
        message_parser = get_message_parser()
        if message_parser.has_role_markers(job_item.raw_prompt):
            parsed_messages = message_parser.parse_messages(job_item.raw_prompt)
            for msg in parsed_messages:
                role_upper = msg.role.upper()
                # Store each role's content (last one if multiple)
                result[role_upper] = msg.content
        else:
            # No markers - treat entire prompt as USER
            result["USER"] = job_item.raw_prompt

        # Store ASSISTANT response (LLM's reply)
        result["ASSISTANT"] = job_item.raw_response or ""

        # Build CONTEXT for this step's output
        # This allows subsequent steps to reference {{step.CONTEXT}} and get the conversation history
        # If input_params contains CONTEXT from previous step, include it for cumulative context
        this_step_context_parts = []

        # First, include previous CONTEXT if provided (cumulative conversation history)
        prev_context = input_params.get("CONTEXT", "") if input_params else ""
        if prev_context:
            this_step_context_parts.append(prev_context)
            # Add this step's USER and ASSISTANT (SYSTEM is already in prev_context)
            if result.get("USER"):
                this_step_context_parts.append(f"[USER]\n{result['USER']}")
            if result.get("ASSISTANT"):
                this_step_context_parts.append(f"[ASSISTANT]\n{result['ASSISTANT']}")
        else:
            # No previous context - build from this step's own conversation
            if result.get("SYSTEM"):
                this_step_context_parts.append(f"[SYSTEM]\n{result['SYSTEM']}")
            if result.get("USER"):
                this_step_context_parts.append(f"[USER]\n{result['USER']}")
            if result.get("ASSISTANT"):
                this_step_context_parts.append(f"[ASSISTANT]\n{result['ASSISTANT']}")

        result["CONTEXT"] = "\n\n".join(this_step_context_parts)
        logger.debug(f"Step {step.step_name}: Generated CONTEXT (cumulative={bool(prev_context)})")

        return result, executed_job.id

    def _merge_outputs(
        self,
        step_context: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Merge all step outputs into final result.

        Args:
            step_context: Context with all step outputs

        Returns:
            Merged output dictionary
        """
        merged = {}
        for step_name, fields in step_context.items():
            if step_name == "input":
                continue  # Skip input params
            merged[step_name] = fields
        return merged

    def _merge_csv_outputs(
        self,
        step_context: Dict[str, Dict[str, Any]]
    ) -> Optional[str]:
        """Get CSV output from the last step that has csv_template parser.

        For workflow execution, we only use the final step's CSV output,
        not a merge of all steps. This is the expected behavior since
        the final step typically produces the workflow's final result.

        Args:
            step_context: Context with all step outputs

        Returns:
            CSV string with header from the last step, or None if no CSV output
        """
        # Get step names sorted by order (step1, step2, etc.)
        step_names = [name for name in step_context.keys() if name != "input"]
        # Sort by step number (assuming format "stepN" or alphabetically)
        step_names.sort(key=lambda x: (len(x), x))

        # Find the last step with CSV output
        last_csv_output = None
        last_csv_header = None
        last_step_name = None

        for step_name in step_names:
            fields = step_context.get(step_name, {})
            csv_output = fields.get("csv_output")
            csv_header = fields.get("csv_header")

            if csv_output:
                last_csv_output = csv_output
                last_csv_header = csv_header
                last_step_name = step_name

        if not last_csv_output:
            return None

        # Build CSV with header and data from the last step only
        result_lines = []
        if last_csv_header:
            result_lines.append(last_csv_header)
        result_lines.append(last_csv_output)

        merged = "\n".join(result_lines)
        logger.debug(f"CSV output from last step ({last_step_name}): {len(result_lines)} lines")
        return merged

    def get_workflow_job(self, job_id: int) -> Optional[WorkflowJob]:
        """Get a workflow job by ID.

        Args:
            job_id: WorkflowJob ID

        Returns:
            WorkflowJob object or None
        """
        return self.db.query(WorkflowJob).filter(WorkflowJob.id == job_id).first()

    def list_workflow_jobs(self, workflow_id: int, limit: int = 50) -> List[WorkflowJob]:
        """List jobs for a workflow.

        Args:
            workflow_id: Workflow ID
            limit: Maximum number of jobs to return

        Returns:
            List of WorkflowJob objects
        """
        return self.db.query(WorkflowJob).filter(
            WorkflowJob.workflow_id == workflow_id
        ).order_by(WorkflowJob.created_at.desc()).limit(limit).all()

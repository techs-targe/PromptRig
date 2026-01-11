"""Workflow Integrity Validator.

Validates workflow structure and configuration for:
- Control flow integrity (IF/ENDIF, LOOP/ENDLOOP, FOREACH/ENDFOREACH pairs)
- Formula/function syntax validation
- Variable and step reference validation
- Required parameter validation
- Step configuration validation
"""

import difflib
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy.orm import Session

from sqlalchemy import text
from .database.models import Workflow, WorkflowStep, Prompt, PromptRevision, Dataset
from .formula_parser import FormulaParser, validate_formula, TokenizerError, ParseError

logger = logging.getLogger(__name__)


class ValidationSeverity(str, Enum):
    """Severity level of validation issues."""
    ERROR = "error"       # Must be fixed before execution
    WARNING = "warning"   # May cause issues but workflow can run
    INFO = "info"         # Informational notice


@dataclass
class ValidationIssue:
    """A single validation issue found in the workflow."""
    severity: ValidationSeverity
    step_id: Optional[int]
    step_name: Optional[str]
    step_order: Optional[int]
    category: str          # e.g., "control_flow", "formula", "reference", "config"
    message: str           # Human-readable message
    message_ja: str        # Japanese message
    suggestion: Optional[str] = None  # How to fix
    suggestion_ja: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity.value,
            "step_id": self.step_id,
            "step_name": self.step_name,
            "step_order": self.step_order,
            "category": self.category,
            "message": self.message,
            "message_ja": self.message_ja,
            "suggestion": self.suggestion,
            "suggestion_ja": self.suggestion_ja,
        }


@dataclass
class ValidationResult:
    """Result of workflow validation."""
    valid: bool                           # True if no errors (warnings OK)
    workflow_id: int
    workflow_name: str
    issues: List[ValidationIssue] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0
    info: int = 0

    def add_issue(self, issue: ValidationIssue):
        self.issues.append(issue)
        if issue.severity == ValidationSeverity.ERROR:
            self.errors += 1
            self.valid = False
        elif issue.severity == ValidationSeverity.WARNING:
            self.warnings += 1
        else:
            self.info += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def get_summary(self) -> str:
        """Get a summary string for display."""
        if self.valid and self.warnings == 0:
            return f"Workflow '{self.workflow_name}' validation passed."

        parts = []
        if self.errors > 0:
            parts.append(f"{self.errors} error(s)")
        if self.warnings > 0:
            parts.append(f"{self.warnings} warning(s)")

        status = "FAILED" if not self.valid else "PASSED with warnings"
        return f"Workflow '{self.workflow_name}' validation {status}: {', '.join(parts)}"


class WorkflowValidator:
    """Validates workflow integrity and configuration."""

    # Valid step types
    VALID_STEP_TYPES = {
        'prompt', 'set', 'if', 'elif', 'else', 'endif',
        'loop', 'endloop', 'foreach', 'endforeach', 'break', 'continue',
        'output'
    }

    # Control flow pairs
    BLOCK_PAIRS = {
        'if': 'endif',
        'loop': 'endloop',
        'foreach': 'endforeach',
    }

    # Valid condition operators
    VALID_OPERATORS = {'==', '!=', '>', '<', '>=', '<=', 'contains', 'empty', 'not_empty'}

    # Valid formula functions (from WorkflowManager)
    VALID_FUNCTIONS = {
        'sum', 'upper', 'lower', 'trim', 'length', 'len', 'slice', 'substr', 'substring',
        'replace', 'split', 'join', 'concat', 'default', 'ifempty', 'contains',
        'startswith', 'endswith', 'count', 'left', 'right', 'repeat', 'reverse',
        'capitalize', 'title', 'lstrip', 'rstrip', 'shuffle', 'debug', 'calc',
        'getprompt', 'getparser'
    }

    # Function argument requirements: function_name -> (min_args, max_args or None for unlimited)
    FUNCTION_ARGS = {
        'sum': (2, None),
        'upper': (1, 1),
        'lower': (1, 1),
        'trim': (1, 1),
        'lstrip': (1, 1),
        'rstrip': (1, 1),
        'length': (1, 1),
        'len': (1, 1),
        'capitalize': (1, 1),
        'title': (1, 1),
        'reverse': (1, 1),
        'slice': (2, 3),
        'substr': (2, 3),
        'substring': (2, 3),
        'left': (2, 2),
        'right': (2, 2),
        'repeat': (2, 2),
        'replace': (3, 3),
        'split': (2, 2),
        'join': (2, 2),
        'concat': (2, None),
        'default': (2, 2),
        'ifempty': (2, 2),
        'contains': (2, 2),
        'startswith': (2, 2),
        'endswith': (2, 2),
        'count': (2, 2),
        'shuffle': (1, 2),
        'debug': (1, None),
        'calc': (1, 1),
        'getprompt': (1, 3),
        'getparser': (1, 3),
    }

    # Reserved step names
    RESERVED_NAMES = {'input', 'vars', '_meta', '_error', '_execution_trace'}

    # Patterns for parsing
    # Updated to support nested properties: {{vars.question.column}}, {{ROW.column}}, {{step.field.subfield}}
    STEP_REF_PATTERN = re.compile(r'\{\{(\w+)\.(\w+(?:\.\w+)*)\}\}')
    # Pattern for simple {{PARAM}} references (no dot) - for detecting undefined variables
    SIMPLE_VAR_PATTERN = re.compile(r'\{\{(\w+)\}\}')
    FORMULA_PATTERN = re.compile(
        r'^(sum|upper|lower|trim|length|len|slice|substr|substring|replace|'
        r'split|join|concat|default|ifempty|contains|startswith|endswith|'
        r'count|left|right|repeat|reverse|capitalize|title|lstrip|rstrip|'
        r'shuffle|debug|calc|getprompt|getparser)\((.+)\)$',
        re.IGNORECASE
    )

    def __init__(self, db: Session):
        """Initialize validator with database session."""
        self.db = db

    def validate_workflow(self, workflow_id: int) -> ValidationResult:
        """Validate a complete workflow.

        Args:
            workflow_id: ID of the workflow to validate

        Returns:
            ValidationResult with all issues found
        """
        workflow = self.db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            result = ValidationResult(
                valid=False,
                workflow_id=workflow_id,
                workflow_name="Unknown"
            )
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=None,
                step_name=None,
                step_order=None,
                category="workflow",
                message=f"Workflow {workflow_id} not found",
                message_ja=f"ワークフロー {workflow_id} が見つかりません"
            ))
            return result

        result = ValidationResult(
            valid=True,
            workflow_id=workflow_id,
            workflow_name=workflow.name
        )

        # Get all steps ordered
        steps = list(self.db.query(WorkflowStep).filter(
            WorkflowStep.workflow_id == workflow_id
        ).order_by(WorkflowStep.step_order).all())

        if not steps:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                step_id=None,
                step_name=None,
                step_order=None,
                category="workflow",
                message="Workflow has no steps",
                message_ja="ワークフローにステップがありません"
            ))
            return result

        # Run all validation checks
        self._validate_step_names(steps, result)
        self._validate_control_flow(steps, result)
        self._validate_step_configs(steps, result)
        self._validate_references(steps, result)
        self._validate_formulas(steps, result)
        self._validate_prompt_steps(steps, result)
        self._validate_input_mappings(steps, result)  # Check all steps for input_mapping issues

        return result

    def _validate_step_names(self, steps: List[WorkflowStep], result: ValidationResult):
        """Validate step names for uniqueness and reserved words."""
        seen_names: Dict[str, int] = {}  # name -> step_id

        for step in steps:
            name = step.step_name

            # Check for reserved names
            if name.lower() in self.RESERVED_NAMES:
                result.add_issue(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    step_id=step.id,
                    step_name=name,
                    step_order=step.step_order,
                    category="step_name",
                    message=f"Step name '{name}' is reserved",
                    message_ja=f"ステップ [{step.step_order}] '{name}': 予約語のため使用できません",
                    suggestion=f"Use a different name like '{name}_step'",
                    suggestion_ja=f"'{name}_step' などの別名を使用してください"
                ))

            # Check for duplicates
            if name in seen_names:
                result.add_issue(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    step_id=step.id,
                    step_name=name,
                    step_order=step.step_order,
                    category="step_name",
                    message=f"Duplicate step name '{name}' (also used by step ID {seen_names[name]})",
                    message_ja=f"ステップ [{step.step_order}] '{name}': ステップ名が重複しています (ステップID {seen_names[name]} でも使用)",
                    suggestion="Each step must have a unique name",
                    suggestion_ja="各ステップは一意の名前を持つ必要があります"
                ))
            else:
                seen_names[name] = step.id

            # Check name format
            if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', name):
                result.add_issue(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    step_id=step.id,
                    step_name=name,
                    step_order=step.step_order,
                    category="step_name",
                    message=f"Invalid step name format: '{name}'",
                    message_ja=f"ステップ [{step.step_order}] '{name}': ステップ名の形式が不正です（スペースや日本語は使用不可）",
                    suggestion="Step names must start with a letter and contain only alphanumeric characters and underscores",
                    suggestion_ja="ステップ名は英字で始まり、英数字とアンダースコア(_)のみ使用可能です。例: generate_question"
                ))

    def _validate_control_flow(self, steps: List[WorkflowStep], result: ValidationResult):
        """Validate control flow structure (IF/ENDIF, LOOP/ENDLOOP, etc.)."""
        # Stack for tracking open blocks: (step_type, step_id, step_order)
        block_stack: List[Tuple[str, int, int, str]] = []

        for step in steps:
            step_type = step.step_type or "prompt"

            # Handle block starters
            if step_type in self.BLOCK_PAIRS:
                block_stack.append((step_type, step.id, step.step_order, step.step_name))

            # Handle ELIF and ELSE (must be inside IF block)
            elif step_type in ('elif', 'else'):
                if not block_stack or block_stack[-1][0] != 'if':
                    result.add_issue(ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        step_id=step.id,
                        step_name=step.step_name,
                        step_order=step.step_order,
                        category="control_flow",
                        message=f"{step_type.upper()} without matching IF",
                        message_ja=f"ステップ [{step.step_order}] '{step.step_name}': {step_type.upper()} に対応する IF がありません",
                        suggestion="Add an IF step before this or remove this step",
                        suggestion_ja="前に IF ステップを追加するか、このステップを削除してください"
                    ))

            # Handle block enders
            elif step_type in ('endif', 'endloop', 'endforeach'):
                expected_starter = {v: k for k, v in self.BLOCK_PAIRS.items()}.get(step_type)

                if not block_stack:
                    result.add_issue(ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        step_id=step.id,
                        step_name=step.step_name,
                        step_order=step.step_order,
                        category="control_flow",
                        message=f"{step_type.upper()} without matching {expected_starter.upper() if expected_starter else 'block starter'}",
                        message_ja=f"ステップ [{step.step_order}] '{step.step_name}': {step_type.upper()} に対応する {expected_starter.upper() if expected_starter else '開始ブロック'} がありません",
                        suggestion=f"Add a {expected_starter.upper()} step or remove this {step_type.upper()}",
                        suggestion_ja=f"{expected_starter.upper()} ステップを追加するか、この {step_type.upper()} を削除してください"
                    ))
                elif block_stack[-1][0] != expected_starter:
                    opener = block_stack[-1]
                    result.add_issue(ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        step_id=step.id,
                        step_name=step.step_name,
                        step_order=step.step_order,
                        category="control_flow",
                        message=f"{step_type.upper()} does not match {opener[0].upper()} at step {opener[2]} ('{opener[3]}')",
                        message_ja=f"ステップ [{step.step_order}] '{step.step_name}': {step_type.upper()} が ステップ [{opener[2]}] '{opener[3]}' の {opener[0].upper()} と一致しません",
                        suggestion=f"Expected {self.BLOCK_PAIRS[opener[0]].upper()} to close {opener[0].upper()}",
                        suggestion_ja=f"{opener[0].upper()} を閉じるには {self.BLOCK_PAIRS[opener[0]].upper()} が必要です"
                    ))
                else:
                    block_stack.pop()

            # Handle BREAK and CONTINUE (must be inside LOOP or FOREACH)
            elif step_type in ('break', 'continue'):
                in_loop = any(s[0] in ('loop', 'foreach') for s in block_stack)
                if not in_loop:
                    result.add_issue(ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        step_id=step.id,
                        step_name=step.step_name,
                        step_order=step.step_order,
                        category="control_flow",
                        message=f"{step_type.upper()} outside of LOOP or FOREACH",
                        message_ja=f"ステップ [{step.step_order}] '{step.step_name}': {step_type.upper()} が LOOP または FOREACH の外にあります",
                        suggestion=f"Move this step inside a LOOP or FOREACH block, or remove it",
                        suggestion_ja=f"このステップを LOOP または FOREACH ブロック内に移動するか、削除してください"
                    ))

        # Check for unclosed blocks
        for opener in block_stack:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=opener[1],
                step_name=opener[3],
                step_order=opener[2],
                category="control_flow",
                message=f"Unclosed {opener[0].upper()} block",
                message_ja=f"ステップ [{opener[2]}] '{opener[3]}': {opener[0].upper()} ブロックが閉じられていません",
                suggestion=f"Add {self.BLOCK_PAIRS[opener[0]].upper()} after this block",
                suggestion_ja=f"このブロックの後に {self.BLOCK_PAIRS[opener[0]].upper()} を追加してください"
            ))

    def _validate_step_configs(self, steps: List[WorkflowStep], result: ValidationResult):
        """Validate step configurations based on step type."""
        for step in steps:
            step_type = step.step_type or "prompt"

            # Validate step type
            if step_type not in self.VALID_STEP_TYPES:
                result.add_issue(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    step_id=step.id,
                    step_name=step.step_name,
                    step_order=step.step_order,
                    category="config",
                    message=f"Invalid step type: '{step_type}'",
                    message_ja=f"無効なステップタイプ: '{step_type}'",
                    suggestion=f"Valid types: {', '.join(sorted(self.VALID_STEP_TYPES))}",
                    suggestion_ja=f"有効なタイプ: {', '.join(sorted(self.VALID_STEP_TYPES))}"
                ))
                continue

            # Validate condition_config for control flow steps
            if step_type in ('if', 'elif', 'loop'):
                self._validate_condition_config(step, result)
            elif step_type == 'set':
                self._validate_set_config(step, result)
            elif step_type == 'foreach':
                self._validate_foreach_config(step, result)

    def _validate_condition_config(self, step: WorkflowStep, result: ValidationResult):
        """Validate condition_config for IF/ELIF/LOOP steps."""
        if not step.condition_config:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="config",
                message=f"{step.step_type.upper()} step requires condition_config",
                message_ja=f"{step.step_type.upper()} ステップには condition_config が必要です",
                suggestion="Set condition_config with 'left', 'operator', and 'right' fields",
                suggestion_ja="'left', 'operator', 'right' フィールドを持つ condition_config を設定してください"
            ))
            return

        try:
            config = json.loads(step.condition_config)
        except json.JSONDecodeError as e:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="config",
                message=f"Invalid JSON in condition_config: {e}",
                message_ja=f"condition_config の JSON が無効です: {e}"
            ))
            return

        # Check required fields
        operator = config.get('operator')
        if not operator:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="config",
                message="Missing 'operator' in condition_config",
                message_ja="condition_config に 'operator' がありません"
            ))
        elif operator not in self.VALID_OPERATORS:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="config",
                message=f"Invalid operator: '{operator}'",
                message_ja=f"無効な演算子: '{operator}'",
                suggestion=f"Valid operators: {', '.join(sorted(self.VALID_OPERATORS))}",
                suggestion_ja=f"有効な演算子: {', '.join(sorted(self.VALID_OPERATORS))}"
            ))

        # Check 'left' field (always required)
        if 'left' not in config:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="config",
                message="Missing 'left' in condition_config",
                message_ja="condition_config に 'left' がありません"
            ))

        # Check 'right' field (required unless operator is 'empty' or 'not_empty')
        if operator not in ('empty', 'not_empty') and 'right' not in config:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="config",
                message="Missing 'right' in condition_config (will compare with empty string)",
                message_ja="condition_config に 'right' がありません (空文字列と比較されます)"
            ))

        # LOOP-specific: check max_iterations
        if step.step_type == 'loop':
            max_iter = config.get('max_iterations', 100)
            if not isinstance(max_iter, int) or max_iter <= 0:
                result.add_issue(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    step_id=step.id,
                    step_name=step.step_name,
                    step_order=step.step_order,
                    category="config",
                    message=f"Invalid max_iterations: {max_iter} (using default 100)",
                    message_ja=f"max_iterations が無効です: {max_iter} (デフォルト 100 を使用)"
                ))
            elif max_iter > 1000:
                result.add_issue(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    step_id=step.id,
                    step_name=step.step_name,
                    step_order=step.step_order,
                    category="config",
                    message=f"max_iterations ({max_iter}) is very high, may cause long execution",
                    message_ja=f"max_iterations ({max_iter}) が非常に大きく、実行時間が長くなる可能性があります"
                ))

    def _validate_set_config(self, step: WorkflowStep, result: ValidationResult):
        """Validate condition_config for SET steps."""
        if not step.condition_config:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="config",
                message="SET step requires condition_config with 'assignments'",
                message_ja="SET ステップには 'assignments' を含む condition_config が必要です",
                suggestion='Set condition_config to {"assignments": {"var_name": "value"}}',
                suggestion_ja='condition_config を {"assignments": {"変数名": "値"}} に設定してください'
            ))
            return

        try:
            config = json.loads(step.condition_config)
        except json.JSONDecodeError as e:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="config",
                message=f"Invalid JSON in condition_config: {e}",
                message_ja=f"condition_config の JSON が無効です: {e}"
            ))
            return

        assignments = config.get('assignments', {})
        if not assignments:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="config",
                message="SET step has no assignments",
                message_ja="SET ステップに代入がありません"
            ))

        # Validate assignment variable names
        for var_name in assignments.keys():
            if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', var_name):
                result.add_issue(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    step_id=step.id,
                    step_name=step.step_name,
                    step_order=step.step_order,
                    category="config",
                    message=f"Invalid variable name in SET: '{var_name}'",
                    message_ja=f"SET の変数名が無効です: '{var_name}'",
                    suggestion="Variable names must start with a letter and contain only alphanumeric characters and underscores",
                    suggestion_ja="変数名は英字で始まり、英数字とアンダースコアのみ使用可能です"
                ))

    def _validate_foreach_config(self, step: WorkflowStep, result: ValidationResult):
        """Validate condition_config for FOREACH steps."""
        if not step.condition_config:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="config",
                message="FOREACH step requires condition_config with 'source' and 'item_var'",
                message_ja="FOREACH ステップには 'source' と 'item_var' を含む condition_config が必要です"
            ))
            return

        try:
            config = json.loads(step.condition_config)
        except json.JSONDecodeError as e:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="config",
                message=f"Invalid JSON in condition_config: {e}",
                message_ja=f"condition_config の JSON が無効です: {e}"
            ))
            return

        # Support both "source" (new) and "list_ref" (legacy) keys
        if 'source' not in config and 'list_ref' not in config:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="config",
                message="FOREACH missing 'source' or 'list_ref' in condition_config",
                message_ja="FOREACH の condition_config に 'source' または 'list_ref' がありません"
            ))

        item_var = config.get('item_var', 'item')
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', item_var):
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="config",
                message=f"Invalid item_var name: '{item_var}'",
                message_ja=f"item_var の名前が無効です: '{item_var}'"
            ))

    def _validate_references(self, steps: List[WorkflowStep], result: ValidationResult):
        """Validate step and variable references in input_mapping and condition_config."""
        # Build set of available step names and defined variables at each step
        step_names_by_order: Dict[int, Set[str]] = {}
        vars_by_order: Dict[int, Set[str]] = {}
        cumulative_names: Set[str] = set()
        cumulative_vars: Set[str] = set()
        # Stack to track FOREACH item_vars for scope management
        foreach_var_stack: List[str] = []
        # Track FOREACH context with dataset columns for validation
        # Format: {step_order: {item_var: str, index_var: str, dataset_id: int, columns: Set[str]}}
        foreach_context_by_order: Dict[int, Dict[str, Any]] = {}
        current_foreach_context: List[Dict[str, Any]] = []
        # Track custom parameters from prompt steps
        # Format: {step_order: Dict[step_name, Set[str]]} - all custom params available at this step
        custom_params_by_order: Dict[int, Dict[str, Set[str]]] = {}
        cumulative_custom_params: Dict[str, Set[str]] = {}
        # Track steps with JSON parsers (dynamic output fields - skip field validation)
        json_parser_steps: Set[str] = set()

        for step in steps:
            step_names_by_order[step.step_order] = cumulative_names.copy()
            vars_by_order[step.step_order] = cumulative_vars.copy()
            # Store the current FOREACH context for this step
            foreach_context_by_order[step.step_order] = current_foreach_context[-1].copy() if current_foreach_context else None
            # Store custom params available at this step (deep copy)
            custom_params_by_order[step.step_order] = {k: v.copy() for k, v in cumulative_custom_params.items()}
            cumulative_names.add(step.step_name)

            # Track variables defined in SET steps
            if step.step_type == 'set' and step.condition_config:
                try:
                    config = json.loads(step.condition_config)
                    assignments = config.get('assignments', {})
                    for var_name in assignments.keys():
                        cumulative_vars.add(var_name)
                except json.JSONDecodeError:
                    pass

            # Track FOREACH item_var as a defined variable (available inside FOREACH block)
            elif step.step_type == 'foreach' and step.condition_config:
                try:
                    config = json.loads(step.condition_config)
                    item_var = config.get('item_var', 'item')
                    index_var = config.get('index_var', 'i')
                    source = config.get('source', config.get('list_ref', ''))
                    cumulative_vars.add(item_var)
                    cumulative_vars.add(index_var)
                    foreach_var_stack.append(item_var)

                    # Parse dataset source and get columns
                    dataset_id = None
                    columns: Set[str] = set()
                    if source.startswith('dataset:'):
                        match = re.match(r'^dataset:(\d+)', source)
                        if match:
                            dataset_id = int(match.group(1))
                            columns = set(get_dataset_columns(self.db, dataset_id))

                    current_foreach_context.append({
                        "item_var": item_var,
                        "index_var": index_var,
                        "dataset_id": dataset_id,
                        "columns": columns,
                        "step_name": step.step_name
                    })
                except json.JSONDecodeError:
                    pass

            # Remove FOREACH item_var from scope when exiting FOREACH block
            elif step.step_type == 'endforeach':
                if foreach_var_stack:
                    foreach_var_stack.pop()
                if current_foreach_context:
                    current_foreach_context.pop()
                # Note: We keep the variable in cumulative_vars for simplicity
                # since most workflows don't reuse the same variable name outside

            # Track custom parameters from prompt steps and detect JSON parsers
            # Custom params are available for subsequent steps to reference
            # A custom parameter is any input_mapping key NOT in the prompt template
            if step.step_type == 'prompt':
                # Check for JSON parser (dynamic output fields)
                if step.prompt_id:
                    revision = self.db.query(PromptRevision).filter(
                        PromptRevision.prompt_id == step.prompt_id
                    ).order_by(PromptRevision.revision.desc()).first()
                    if revision:
                        # Check if parser_config uses JSON type
                        if revision.parser_config:
                            try:
                                parser_cfg = json.loads(revision.parser_config)
                                if parser_cfg.get('type') == 'json':
                                    json_parser_steps.add(step.step_name)
                            except json.JSONDecodeError:
                                pass

                        # Track custom params from input_mapping
                        if step.input_mapping:
                            try:
                                mapping = json.loads(step.input_mapping)
                                step_custom_params: Set[str] = set()

                                # Get prompt template parameters if available
                                template_params = set()
                                if revision.prompt_template:
                                    param_pattern = re.compile(r'\{\{([^}:]+)(?::[^}]*)?\}\}')
                                    for match in param_pattern.finditer(revision.prompt_template):
                                        template_params.add(match.group(1).strip())

                                # Any input_mapping key NOT in template is a custom param
                                for key in mapping.keys():
                                    if key not in template_params:
                                        step_custom_params.add(key)

                                if step_custom_params:
                                    cumulative_custom_params[step.step_name] = step_custom_params
                            except json.JSONDecodeError:
                                pass

        for step in steps:
            available_steps = step_names_by_order.get(step.step_order, set())
            available_vars = vars_by_order.get(step.step_order, set())
            foreach_context = foreach_context_by_order.get(step.step_order)
            custom_params = custom_params_by_order.get(step.step_order, {})

            # Check input_mapping
            if step.input_mapping:
                try:
                    mapping = json.loads(step.input_mapping)
                    for param_name, ref_pattern in mapping.items():
                        self._validate_reference_string(
                            ref_pattern, available_steps, available_vars, step, result,
                            f"input_mapping['{param_name}']", foreach_context, custom_params,
                            json_parser_steps
                        )
                except json.JSONDecodeError:
                    result.add_issue(ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        step_id=step.id,
                        step_name=step.step_name,
                        step_order=step.step_order,
                        category="config",
                        message="Invalid JSON in input_mapping",
                        message_ja="input_mapping の JSON が無効です"
                    ))

            # Check condition_config
            if step.condition_config:
                try:
                    config = json.loads(step.condition_config)

                    # Check 'left' and 'right' in conditions
                    for field in ('left', 'right'):
                        if field in config:
                            self._validate_reference_string(
                                str(config[field]), available_steps, available_vars, step, result,
                                f"condition_config['{field}']", foreach_context, custom_params,
                                json_parser_steps
                            )

                    # Check 'source' in FOREACH
                    if 'source' in config:
                        self._validate_reference_string(
                            str(config['source']), available_steps, available_vars, step, result,
                            "condition_config['source']", foreach_context, custom_params,
                            json_parser_steps
                        )

                    # Check 'assignments' in SET
                    if 'assignments' in config:
                        for var_name, value_expr in config['assignments'].items():
                            self._validate_reference_string(
                                str(value_expr), available_steps, available_vars, step, result,
                                f"assignments['{var_name}']", foreach_context, custom_params,
                                json_parser_steps
                            )
                except json.JSONDecodeError:
                    pass  # Already handled above

    # Pattern to extract variable names from {{vars.X}} references
    VARS_REF_PATTERN = re.compile(r'\{\{vars\.(\w+)\}\}')

    def _validate_reference_string(
        self,
        ref_string: str,
        available_steps: Set[str],
        available_vars: Set[str],
        step: WorkflowStep,
        result: ValidationResult,
        context: str,
        foreach_context: Optional[Dict[str, Any]] = None,
        custom_params_by_step: Optional[Dict[str, Set[str]]] = None,
        json_parser_steps: Optional[Set[str]] = None
    ):
        """Validate step and variable references in a string.

        Args:
            ref_string: The string containing references to validate
            available_steps: Set of step names available at this point
            available_vars: Set of variable names available at this point
            step: The current step being validated
            result: ValidationResult to add issues to
            context: Description of where this reference is (e.g., "input_mapping['QUESTION']")
            foreach_context: Optional FOREACH context with item_var, index_var, columns, etc.
            custom_params_by_step: Optional dict mapping step_name -> set of custom param names
            json_parser_steps: Optional set of step names that use JSON parsers (skip field validation)
        """
        # Find all {{step.field}} references
        for match in self.STEP_REF_PATTERN.finditer(ref_string):
            ref_step = match.group(1)
            ref_field = match.group(2)

            # 'input' is always available
            if ref_step == 'input':
                continue

            # Check 'vars' references against defined variables
            if ref_step == 'vars':
                # ref_field may be nested like "question.column" or simple like "counter"
                # Extract the base variable name (first part before any dot)
                var_parts = ref_field.split('.')
                base_var_name = var_parts[0]

                if base_var_name not in available_vars:
                    # Show the full path in error message for clarity
                    full_ref = f"vars.{ref_field}"
                    result.add_issue(ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        step_id=step.id,
                        step_name=step.step_name,
                        step_order=step.step_order,
                        category="reference",
                        message=f"Reference to undefined variable '{{{{{full_ref}}}}}' in {context}",
                        message_ja=f"{context} で未定義の変数 '{{{{{full_ref}}}}}' を参照しています",
                        suggestion=f"Define '{base_var_name}' in a SET step before this step, or use {{{{input.{base_var_name}}}}} for workflow input",
                        suggestion_ja=f"このステップより前に SET ステップで '{base_var_name}' を定義するか、ワークフロー入力として {{{{input.{base_var_name}}}}} を使用してください"
                    ))
                else:
                    # Variable exists. If it's a FOREACH item_var and has nested property,
                    # validate the property against dataset columns
                    if foreach_context and len(var_parts) > 1:
                        item_var = foreach_context.get("item_var")
                        columns = foreach_context.get("columns", set())

                        if base_var_name == item_var and columns:
                            # This is a FOREACH item variable with nested property access
                            # e.g., {{vars.question.question_stem}}
                            nested_property = var_parts[1]  # First nested property (column name)

                            if nested_property not in columns:
                                full_ref = f"vars.{ref_field}"
                                available_cols = ', '.join(sorted(columns)) if columns else "(none)"

                                # Try to find a similar column name
                                close_matches = difflib.get_close_matches(nested_property, columns, n=1, cutoff=0.4)
                                if close_matches:
                                    suggestion = f"Available columns: {available_cols}. Did you mean '{close_matches[0]}'?"
                                    suggestion_ja = f"利用可能なカラム: {available_cols}。'{close_matches[0]}' のことですか？"
                                else:
                                    suggestion = f"Available columns: {available_cols}"
                                    suggestion_ja = f"利用可能なカラム: {available_cols}"

                                result.add_issue(ValidationIssue(
                                    severity=ValidationSeverity.ERROR,
                                    step_id=step.id,
                                    step_name=step.step_name,
                                    step_order=step.step_order,
                                    category="reference",
                                    message=f"Invalid column '{nested_property}' in '{{{{{full_ref}}}}}' - column does not exist in dataset",
                                    message_ja=f"'{{{{{full_ref}}}}}' のカラム '{nested_property}' はデータセットに存在しません",
                                    suggestion=suggestion,
                                    suggestion_ja=suggestion_ja
                                ))
                continue

            # Check if ref_step is a FOREACH item_var (e.g., {{ROW.field}})
            # These are defined variables that can be referenced directly without 'vars.' prefix
            if ref_step in available_vars:
                continue  # Valid FOREACH item variable reference

            # If step exists, validate that the field is a valid output for that step
            if ref_step in available_steps:
                # Skip field validation for steps with JSON parsers (dynamic output fields)
                if json_parser_steps and ref_step in json_parser_steps:
                    continue  # JSON parser: any field is valid

                # For prompt steps, valid outputs are: 'raw' and custom parameters
                # Build the set of valid fields for this step
                valid_fields = {'raw', 'OUTPUT'}  # Base fields for prompt steps

                # Add custom parameters from that step
                if custom_params_by_step and ref_step in custom_params_by_step:
                    valid_fields.update(custom_params_by_step[ref_step])

                # Get the base field name (before any dot, e.g., 'TIMPO' from 'TIMPO.something')
                base_field = ref_field.split('.')[0]

                if base_field not in valid_fields:
                    # Unknown field for this step
                    available_fields = ', '.join(sorted(valid_fields))
                    close_matches = difflib.get_close_matches(base_field, valid_fields, n=1, cutoff=0.4)

                    if close_matches:
                        suggestion = f"Did you mean '{{{{{ref_step}.{close_matches[0]}}}}}'? Available outputs: {available_fields}"
                        suggestion_ja = f"'{{{{{ref_step}.{close_matches[0]}}}}}' のことですか？利用可能な出力: {available_fields}"
                    else:
                        suggestion = f"Available outputs from '{ref_step}': {available_fields}"
                        suggestion_ja = f"'{ref_step}' の利用可能な出力: {available_fields}"

                    result.add_issue(ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        step_id=step.id,
                        step_name=step.step_name,
                        step_order=step.step_order,
                        category="reference",
                        message=f"Step '{ref_step}' has no output field '{base_field}' in {context}",
                        message_ja=f"{context} でステップ '{ref_step}' には出力フィールド '{base_field}' がありません",
                        suggestion=suggestion,
                        suggestion_ja=suggestion_ja
                    ))
                continue  # Step exists, either valid or error already reported

            if ref_step not in available_steps:
                # Find closest matching step name for better suggestions
                close_matches = difflib.get_close_matches(ref_step, available_steps, n=1, cutoff=0.4)

                if close_matches:
                    closest = close_matches[0]
                    suggestion = f"Available steps: {', '.join(sorted(available_steps)) or '(none)'}. Did you mean '{closest}'? Replace {{{{{ref_step}.{ref_field}}}}} with {{{{{closest}.{ref_field}}}}}"
                    suggestion_ja = f"利用可能なステップ: {', '.join(sorted(available_steps)) or '(なし)'}。'{closest}' のことですか？ {{{{{ref_step}.{ref_field}}}}} を {{{{{closest}.{ref_field}}}}} に置き換えてください"
                else:
                    suggestion = f"Available steps: {', '.join(sorted(available_steps)) or '(none)'}"
                    suggestion_ja = f"利用可能なステップ: {', '.join(sorted(available_steps)) or '(なし)'}"

                result.add_issue(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    step_id=step.id,
                    step_name=step.step_name,
                    step_order=step.step_order,
                    category="reference",
                    message=f"Reference to undefined step '{ref_step}' in {context}",
                    message_ja=f"{context} で未定義のステップ '{ref_step}' を参照しています",
                    suggestion=suggestion,
                    suggestion_ja=suggestion_ja
                ))

        # Validate simple {{PARAM}} references (no dot)
        # These could be undefined variables or incorrectly formatted references
        for match in self.SIMPLE_VAR_PATTERN.finditer(ref_string):
            param_name = match.group(1)
            match_start = match.start()
            match_end = match.end()

            # Skip if this is part of a {{step.field}} pattern (already validated above)
            # Check the character right after the match - if it's part of {{step.field}},
            # STEP_REF_PATTERN would have matched starting at this position
            # We check if there's a {{name.field}} pattern starting at this position
            remaining = ref_string[match_start:]
            if self.STEP_REF_PATTERN.match(remaining):
                continue

            # Skip known reserved prefixes that require dot notation
            if param_name in ('input', 'vars'):
                # These are incomplete references - should have .field
                result.add_issue(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    step_id=step.id,
                    step_name=step.step_name,
                    step_order=step.step_order,
                    category="reference",
                    message=f"Incomplete reference '{{{{{param_name}}}}}' in {context} - missing field after '{param_name}.'",
                    message_ja=f"{context} の参照 '{{{{{param_name}}}}}' は不完全です - '{param_name}.' の後にフィールドが必要です",
                    suggestion=f"Use '{{{{{param_name}.FIELD}}}}' format",
                    suggestion_ja=f"'{{{{{param_name}.フィールド名}}}}' 形式を使用してください"
                ))
                continue

            # Skip known function names (these are handled in formula validation)
            if param_name.lower() in ('calc', 'sum', 'upper', 'lower', 'trim', 'length', 'len',
                                       'slice', 'substr', 'substring', 'replace', 'split', 'join',
                                       'concat', 'default', 'ifempty', 'contains', 'startswith',
                                       'endswith', 'count', 'left', 'right', 'repeat', 'reverse',
                                       'capitalize', 'title', 'lstrip', 'rstrip', 'shuffle', 'debug',
                                       'getprompt', 'getparser'):
                continue

            # Check if it's a known variable (defined in SET or FOREACH)
            if param_name in available_vars:
                # Valid variable reference (though {{vars.X}} is preferred)
                continue

            # Check if it's a known step name (might be missing .field)
            if param_name in available_steps:
                result.add_issue(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    step_id=step.id,
                    step_name=step.step_name,
                    step_order=step.step_order,
                    category="reference",
                    message=f"'{{{{{param_name}}}}}' in {context} is a step name - did you mean to access a field?",
                    message_ja=f"{context} の '{{{{{param_name}}}}}' はステップ名です。フィールドを指定しましたか？",
                    suggestion=f"Use '{{{{{param_name}.FIELD}}}}' to access step outputs",
                    suggestion_ja=f"ステップ出力にアクセスするには '{{{{{param_name}.フィールド名}}}}' を使用してください"
                ))
                continue

            # Check if it's a custom parameter from a previous step
            if custom_params_by_step:
                found_step = None
                for step_name, params in custom_params_by_step.items():
                    if param_name in params:
                        found_step = step_name
                        break
                if found_step:
                    result.add_issue(ValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        step_id=step.id,
                        step_name=step.step_name,
                        step_order=step.step_order,
                        category="reference",
                        message=f"'{{{{{param_name}}}}}' in {context} is a custom parameter from step '{found_step}'",
                        message_ja=f"{context} の '{{{{{param_name}}}}}' はステップ '{found_step}' のカスタムパラメータです",
                        suggestion=f"Use '{{{{{found_step}.{param_name}}}}}' to reference it correctly",
                        suggestion_ja=f"正しく参照するには '{{{{{found_step}.{param_name}}}}}' を使用してください"
                    ))
                    continue

            # Unknown reference - this is an error
            all_known: Set[str] = available_vars | available_steps | {'input', 'vars'}
            if custom_params_by_step:
                for params in custom_params_by_step.values():
                    all_known |= params

            close_matches = difflib.get_close_matches(param_name, all_known, n=1, cutoff=0.4)
            if close_matches:
                suggestion = f"Did you mean '{close_matches[0]}'?"
                suggestion_ja = f"'{close_matches[0]}' のことですか？"
            else:
                available_list = ', '.join(sorted(list(all_known)[:10]))
                suggestion = f"Available: {available_list}" if available_list else "No variables defined yet"
                suggestion_ja = f"利用可能: {available_list}" if available_list else "変数がまだ定義されていません"

            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="reference",
                message=f"Undefined reference '{{{{{param_name}}}}}' in {context}",
                message_ja=f"{context} で未定義の参照 '{{{{{param_name}}}}}' があります",
                suggestion=suggestion,
                suggestion_ja=suggestion_ja
            ))

    def _validate_formulas(self, steps: List[WorkflowStep], result: ValidationResult):
        """Validate formula/function syntax in references."""
        for step in steps:
            # Check input_mapping
            if step.input_mapping:
                try:
                    mapping = json.loads(step.input_mapping)
                    for param_name, ref_pattern in mapping.items():
                        self._validate_formula_string(
                            str(ref_pattern), step, result, f"input_mapping['{param_name}']"
                        )
                except json.JSONDecodeError:
                    pass

            # Check condition_config
            if step.condition_config:
                try:
                    config = json.loads(step.condition_config)
                    for field in ('left', 'right', 'source'):
                        if field in config:
                            self._validate_formula_string(
                                str(config[field]), step, result, f"condition_config['{field}']"
                            )
                    if 'assignments' in config:
                        for var_name, value_expr in config['assignments'].items():
                            self._validate_formula_string(
                                str(value_expr), step, result, f"assignments['{var_name}']"
                            )
                except json.JSONDecodeError:
                    pass

    def _validate_formula_string(
        self,
        formula_str: str,
        step: WorkflowStep,
        result: ValidationResult,
        context: str
    ):
        """Validate formula function syntax using the Interpreter pattern parser.

        Uses the new FormulaParser for robust syntax validation including:
        - Proper tokenization
        - Nested function support
        - Operator precedence checking
        - Detailed error messages with position info
        """
        formula_str = formula_str.strip()

        # Check if it's a formula
        match = self.FORMULA_PATTERN.match(formula_str)
        if not match:
            return  # Not a formula, nothing to validate

        # Use the new parser for comprehensive validation
        is_valid, errors = validate_formula(formula_str)

        if not is_valid:
            for error in errors:
                # Extract position info if available
                error_msg = str(error)

                result.add_issue(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    step_id=step.id,
                    step_name=step.step_name,
                    step_order=step.step_order,
                    category="formula",
                    message=f"Formula syntax error in {context}: {error_msg}",
                    message_ja=f"{context} の数式構文エラー: {error_msg}",
                    suggestion="Check parentheses, quotes, and function arguments",
                    suggestion_ja="括弧、引用符、関数の引数を確認してください"
                ))
            return

        # Check for invalid function chaining (e.g., json_parse(...).field)
        # This pattern is NOT supported but commonly mistaken
        func_chain_pattern = re.compile(r'(json_parse|concat|upper|lower|trim)\s*\([^)]+\)\s*\.\s*\w+')
        if func_chain_pattern.search(formula_str):
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="formula",
                message=f"Function chaining is not supported in {context}: '{formula_str}'",
                message_ja=f"{context} で関数チェーンは非対応: '{formula_str}'",
                suggestion="Use: 1) {{step.field}} directly if parser extracts it, or 2) Set to variable first (parsed = json_parse(...)), then access {{vars.parsed.field}}",
                suggestion_ja="正解: 1) パーサーが抽出済みなら {{step.field}} を直接使用、2) setで変数に格納後 {{vars.parsed.field}} でアクセス"
            ))
            return

        # Additional semantic validation using old method for arg count
        func_name = match.group(1).lower()
        args_str = match.group(2)

        # Count arguments (simple parsing)
        arg_count = self._count_formula_args(args_str)
        min_args, max_args = self.FUNCTION_ARGS.get(func_name, (1, None))

        if arg_count < min_args:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="formula",
                message=f"Function '{func_name}' requires at least {min_args} argument(s), got {arg_count}",
                message_ja=f"関数 '{func_name}' は最低 {min_args} 個の引数が必要ですが、{arg_count} 個しかありません"
            ))

        if max_args is not None and arg_count > max_args:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="formula",
                message=f"Function '{func_name}' accepts at most {max_args} argument(s), got {arg_count}",
                message_ja=f"関数 '{func_name}' は最大 {max_args} 個の引数を受け取りますが、{arg_count} 個あります"
            ))

    def _count_formula_args(self, args_str: str) -> int:
        """Count the number of arguments in a formula argument string."""
        if not args_str.strip():
            return 0

        count = 1
        brace_depth = 0
        paren_depth = 0
        in_quote = False
        quote_char = None

        for char in args_str:
            if char in ('"', "'") and not in_quote:
                in_quote = True
                quote_char = char
            elif char == quote_char and in_quote:
                in_quote = False
                quote_char = None
            elif not in_quote:
                if char == '{':
                    brace_depth += 1
                elif char == '}':
                    brace_depth -= 1
                elif char == '(':
                    paren_depth += 1
                elif char == ')':
                    paren_depth -= 1
                elif char == ',' and brace_depth == 0 and paren_depth == 0:
                    count += 1

        return count

    # Pattern to extract prompt template parameters {{PARAM}} or {{PARAM:TYPE}} or {{PARAM|default}}
    PROMPT_PARAM_PATTERN = re.compile(r'\{\{(\w+)(?::\w+)?(?:\|[^}]*)?\}\}')

    # Pattern to detect workflow variables in prompt template (not allowed)
    VARS_IN_TEMPLATE_PATTERN = re.compile(r'\{\{vars\.')

    def _validate_prompt_steps(self, steps: List[WorkflowStep], result: ValidationResult):
        """Validate prompt steps have valid prompt_id."""
        for step in steps:
            step_type = step.step_type or "prompt"

            if step_type != "prompt":
                continue

            # Check if prompt_id is set (required for prompt steps)
            if not step.prompt_id:
                result.add_issue(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    step_id=step.id,
                    step_name=step.step_name,
                    step_order=step.step_order,
                    category="config",
                    message=f"Prompt step '{step.step_name}' (order {step.step_order}) requires prompt_id",
                    message_ja=f"ステップ [{step.step_order}] '{step.step_name}': プロンプトが選択されていません",
                    suggestion="Select a prompt for this step or use 'set' step type for variable assignment",
                    suggestion_ja="このステップにプロンプトを選択するか、変数設定には 'set' ステップタイプを使用してください"
                ))
                continue

            # Validate prompt_id exists and has revision
            if step.prompt_id:
                prompt = self.db.query(Prompt).filter(
                    Prompt.id == step.prompt_id,
                    Prompt.is_deleted == 0
                ).first()

                if not prompt:
                    result.add_issue(ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        step_id=step.id,
                        step_name=step.step_name,
                        step_order=step.step_order,
                        category="config",
                        message=f"Prompt ID {step.prompt_id} not found or deleted",
                        message_ja=f"ステップ [{step.step_order}] '{step.step_name}': プロンプト (ID={step.prompt_id}) が見つからないか削除されています",
                        suggestion="Select an existing prompt or create a new one",
                        suggestion_ja="既存のプロンプトを選択するか、新しいプロンプトを作成してください"
                    ))
                else:
                    revision = self.db.query(PromptRevision).filter(
                        PromptRevision.prompt_id == step.prompt_id
                    ).order_by(PromptRevision.revision.desc()).first()

                    if not revision:
                        result.add_issue(ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            step_id=step.id,
                            step_name=step.step_name,
                            step_order=step.step_order,
                            category="config",
                            message=f"No revision found for prompt ID {step.prompt_id}",
                            message_ja=f"ステップ [{step.step_order}] '{step.step_name}': プロンプト (ID={step.prompt_id}) のリビジョンがありません",
                            suggestion="Save the prompt to create a revision",
                            suggestion_ja="プロンプトを保存してリビジョンを作成してください"
                        ))
                    else:
                        # Validate input_mapping matches prompt parameters
                        self._validate_input_mapping_matches_prompt(step, revision, result)
                        # Check for {{vars.xxx}} in prompt template
                        self._validate_no_vars_in_template(step, revision, result)
                        # Validate prompt/parser consistency
                        self._validate_prompt_parser_consistency(step, revision, steps, result)

    def _validate_input_mappings(self, steps: List[WorkflowStep], result: ValidationResult):
        """Validate input_mapping for all steps - check for fixed text and misuse."""
        for step in steps:
            self._check_input_mapping_fixed_text(step, result)

    def _check_input_mapping_fixed_text(self, step: WorkflowStep, result: ValidationResult):
        """Check for fixed text in input_mapping and warn about it."""
        if not step.input_mapping:
            return

        step_type = step.step_type or "prompt"

        # SET steps should not use input_mapping at all
        if step_type == "set":
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="config",
                message=f"SET step should not have input_mapping - use condition_config.assignments instead",
                message_ja=f"SET ステップは input_mapping を使用しません - condition_config.assignments を使用してください",
                suggestion="Remove input_mapping and define variables in condition_config.assignments",
                suggestion_ja="input_mapping を削除し、condition_config.assignments で変数を定義してください"
            ))
            return

        try:
            mapping = json.loads(step.input_mapping)
            for param_name, value in mapping.items():
                value_str = str(value)
                # Check if value contains any {{...}} reference
                if not self.STEP_REF_PATTERN.search(value_str):
                    # No reference found - this is a fixed text
                    if len(value_str) > 20:
                        display_value = value_str[:20] + "..."
                    else:
                        display_value = value_str
                    result.add_issue(ValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        step_id=step.id,
                        step_name=step.step_name,
                        step_order=step.step_order,
                        category="config",
                        message=f"Fixed text in input_mapping['{param_name}']: '{display_value}' - consider using {{{{input.{param_name}}}}} for reusability",
                        message_ja=f"input_mapping['{param_name}'] に固定テキストが設定されています: '{display_value}' - 再利用性のため {{{{input.{param_name}}}}} の使用を検討してください",
                        suggestion=f"Use {{{{input.{param_name}}}}} to accept workflow input, or {{{{stepName.result}}}} to use previous step's result",
                        suggestion_ja=f"ワークフロー入力を受け取る場合は {{{{input.{param_name}}}}}、前ステップの結果を使う場合は {{{{stepName.result}}}} を使用してください"
                    ))
        except json.JSONDecodeError:
            pass  # Already handled elsewhere

    def _validate_input_mapping_matches_prompt(
        self,
        step: WorkflowStep,
        revision: PromptRevision,
        result: ValidationResult
    ):
        """Validate that input_mapping keys match prompt template parameters.

        This catches common mistakes like:
        - Missing input_mapping for prompt parameters
        - Case mismatch between prompt {{PARAM}} and input_mapping key
        """
        if not revision.prompt_template:
            return

        # Extract parameters from prompt template (e.g., {{QUESTION}}, {{CHOICES:TEXT5}})
        template_params = set()
        for match in self.PROMPT_PARAM_PATTERN.finditer(revision.prompt_template):
            param_name = match.group(1)
            # Skip reserved/special names
            if param_name.lower() not in ('vars', 'input', 'step'):
                template_params.add(param_name)

        if not template_params:
            return  # No parameters in template

        # Get input_mapping keys
        mapping_keys = set()
        if step.input_mapping:
            try:
                mapping = json.loads(step.input_mapping)
                mapping_keys = set(mapping.keys())
            except json.JSONDecodeError:
                return  # JSON error is handled elsewhere

        # Find missing parameters (in template but not in mapping)
        missing_in_mapping = template_params - mapping_keys

        # Check for case-insensitive matches (likely typos)
        for missing_param in list(missing_in_mapping):
            for key in mapping_keys:
                if missing_param.lower() == key.lower() and missing_param != key:
                    # Case mismatch found
                    result.add_issue(ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        step_id=step.id,
                        step_name=step.step_name,
                        step_order=step.step_order,
                        category="input_mapping",
                        message=f"Case mismatch: prompt has '{{{{{missing_param}}}}}', but input_mapping has '{key}'",
                        message_ja=f"大文字小文字の不一致: プロンプトは '{{{{{missing_param}}}}}' ですが、input_mapping は '{key}' です",
                        suggestion=f"Change input_mapping key from '{key}' to '{missing_param}' to match the prompt parameter",
                        suggestion_ja=f"input_mapping のキー '{key}' を '{missing_param}' に変更してプロンプトのパラメータと一致させてください"
                    ))
                    missing_in_mapping.discard(missing_param)

        # Report truly missing parameters
        if missing_in_mapping:
            missing_list = ', '.join(sorted(missing_in_mapping))
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="input_mapping",
                message=f"Prompt parameters '{{{{{missing_list}}}}}' not found in input_mapping",
                message_ja=f"プロンプトのパラメータ '{{{{{missing_list}}}}}' が input_mapping に存在しません",
                suggestion=f"Add these keys to input_mapping or the parameters will be empty. See help(topic='workflow', entry='input_mapping')",
                suggestion_ja=f"これらのキーを input_mapping に追加してください。追加しないとパラメータが空になります。help(topic='workflow', entry='input_mapping') を参照"
            ))

    def _validate_no_vars_in_template(
        self,
        step: WorkflowStep,
        revision: PromptRevision,
        result: ValidationResult
    ):
        """Check for {{vars.xxx}} in prompt template - this is a common mistake.

        Prompt templates should use {{PARAM}} syntax, not workflow variables directly.
        Workflow variables should be passed via input_mapping.
        """
        if not revision.prompt_template:
            return

        if self.VARS_IN_TEMPLATE_PATTERN.search(revision.prompt_template):
            # Find the actual vars references for better error message
            vars_refs = re.findall(r'\{\{vars\.(\w+(?:\.\w+)*)\}\}', revision.prompt_template)
            vars_examples = ', '.join([f'{{{{vars.{ref}}}}}' for ref in vars_refs[:3]])
            if len(vars_refs) > 3:
                vars_examples += ', ...'

            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="prompt_template",
                message=f"Prompt template contains workflow variables ({vars_examples}) - use {{{{PARAM}}}} and input_mapping instead",
                message_ja=f"プロンプトテンプレートにワークフロー変数 ({vars_examples}) が含まれています - {{{{PARAM}}}} と input_mapping を使用してください",
                suggestion="Replace {{vars.xxx}} with {{PARAM_NAME}} in the prompt template, then add input_mapping: {\"PARAM_NAME\": \"{{vars.xxx}}\"}",
                suggestion_ja="プロンプトテンプレートの {{vars.xxx}} を {{PARAM_NAME}} に置き換え、input_mapping: {\"PARAM_NAME\": \"{{vars.xxx}}\"} を追加してください"
            ))

    # ===== Prompt/Parser Consistency Validation =====

    # Patterns indicating JSON output is expected in the prompt
    JSON_OUTPUT_PATTERNS = [
        r'\bJSON\b',                    # Explicit "JSON" mention
        r'\bjson\b',                    # Lowercase "json"
        r'```json',                     # JSON code block
        r'\{[\s\n]*"[^"]+"\s*:',        # JSON object pattern like {"key":
        r'以下の(JSON|形式|フォーマット)で',  # Japanese: "in the following JSON/format"
        r'(JSON|json)(形式|フォーマット)',    # Japanese: "JSON format"
        r'following\s+(JSON|format)',   # English: "following JSON/format"
        r'出力.*JSON',                   # Japanese: "output...JSON"
        r'response.*JSON',              # English: response as JSON
    ]

    # Patterns indicating single letter answer is expected (A/B/C/D style)
    SINGLE_LETTER_PATTERNS = [
        r'[A-D]のいずれか',               # Japanese: "one of A-D"
        r'[（\(]?[A-D][）\)]?から選',     # Japanese: "choose from (A)-(D)"
        r'\b[A-D]\s*[/／]\s*[A-D]\s*[/／]\s*[A-D]',  # A/B/C or A/B/C/D
        r'(one|single)\s*(letter|character)',  # English: "single letter"
        r'1文字',                         # Japanese: "one character"
        r'(A|B|C|D)のみ',                 # Japanese: "only A/B/C/D"
        r'選択肢.*[（\(][A-D][）\)]',      # Japanese: "choices...(A)"
        r'answer.*[（\(]?[A-D][）\)]',    # English: answer with letter
    ]

    def _prompt_expects_json(self, template: str) -> bool:
        """Check if prompt instructs JSON output.

        Args:
            template: Prompt template text

        Returns:
            True if prompt appears to expect JSON output
        """
        if not template:
            return False

        for pattern in self.JSON_OUTPUT_PATTERNS:
            if re.search(pattern, template, re.IGNORECASE):
                return True
        return False

    def _prompt_expects_single_letter(self, template: str) -> bool:
        """Check if prompt expects single letter answer (A/B/C/D style).

        Args:
            template: Prompt template text

        Returns:
            True if prompt appears to expect a single letter answer
        """
        if not template:
            return False

        for pattern in self.SINGLE_LETTER_PATTERNS:
            if re.search(pattern, template, re.IGNORECASE):
                return True
        return False

    def _parse_parser_config(self, parser_config_str: Optional[str]) -> Tuple[str, Set[str]]:
        """Parse parser config and extract type and field names.

        Args:
            parser_config_str: JSON string of parser configuration

        Returns:
            Tuple of (parser_type, set of field names)
        """
        if not parser_config_str:
            return ("none", set())

        try:
            config = json.loads(parser_config_str)
        except json.JSONDecodeError:
            return ("none", set())

        parser_type = config.get("type", "none")
        fields: Set[str] = set()

        if parser_type == "json_path":
            # json_path has paths dict: {"fieldName": "$.path.to.value"}
            fields = set(config.get("paths", {}).keys())
        elif parser_type == "regex":
            # regex has patterns dict: {"fieldName": "pattern"}
            fields = set(config.get("patterns", {}).keys())
        elif parser_type == "json":
            # json type extracts specified fields, or any field if not specified
            specified_fields = config.get("fields", [])
            if specified_fields:
                fields = set(specified_fields)
            else:
                # No specific fields = can extract any field (wildcard)
                fields = {"*"}

        return (parser_type, fields)

    def _extract_step_field_refs(self, text: str, step_name: str) -> Set[str]:
        """Extract field references for a specific step name from text.

        Args:
            text: Text that may contain {{step_name.FIELD}} references
            step_name: Name of the step to look for

        Returns:
            Set of field names referenced
        """
        if not text:
            return set()

        # Match {{step_name.FIELD}} or {{ step_name.FIELD }}
        pattern = rf'\{{\{{\s*{re.escape(step_name)}\.(\w+)\s*\}}\}}'
        return set(re.findall(pattern, text))

    def _validate_parser_field_references(
        self,
        prompt_step: WorkflowStep,
        parser_type: str,
        parser_fields: Set[str],
        all_steps: List[WorkflowStep],
        result: ValidationResult
    ):
        """Check if subsequent steps reference parser fields correctly.

        Args:
            prompt_step: The prompt step being validated
            parser_type: The parser type (json, regex, etc.)
            parser_fields: Set of field names defined in parser config
            all_steps: All steps in workflow
            result: ValidationResult to add issues to
        """
        step_name = prompt_step.step_name

        # Find all references to this step's fields in subsequent steps
        for step in all_steps:
            if step.step_order <= prompt_step.step_order:
                continue

            # Collect references from input_mapping and condition_config
            refs: Set[str] = set()
            if step.input_mapping:
                refs.update(self._extract_step_field_refs(step.input_mapping, step_name))
            if step.condition_config:
                refs.update(self._extract_step_field_refs(step.condition_config, step_name))

            for field_ref in refs:
                # Skip if parser can extract any field (wildcard)
                if "*" in parser_fields:
                    continue

                # Skip if parser type is 'none' - separate warning is issued
                if parser_type == "none":
                    result.add_issue(ValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        step_id=step.id,
                        step_name=step.step_name,
                        step_order=step.step_order,
                        category="parser",
                        message=f"References {{{{{step_name}.{field_ref}}}}} but step '{step_name}' has no parser configured",
                        message_ja=f"{{{{{step_name}.{field_ref}}}}} を参照していますが、ステップ '{step_name}' にパーサーが設定されていません",
                        suggestion=f"Add a parser to step '{step_name}' to extract field '{field_ref}'",
                        suggestion_ja=f"ステップ '{step_name}' にフィールド '{field_ref}' を抽出するパーサーを追加してください"
                    ))
                    continue

                # Check if field exists in parser
                if field_ref not in parser_fields:
                    available_fields = ', '.join(sorted(parser_fields)) if parser_fields else "(none)"
                    result.add_issue(ValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        step_id=step.id,
                        step_name=step.step_name,
                        step_order=step.step_order,
                        category="parser",
                        message=f"References {{{{{step_name}.{field_ref}}}}} but field '{field_ref}' not found in parser config",
                        message_ja=f"{{{{{step_name}.{field_ref}}}}} を参照していますが、フィールド '{field_ref}' がパーサー設定に存在しません",
                        suggestion=f"Available parser fields: {available_fields}. Add '{field_ref}' to parser config or fix the reference.",
                        suggestion_ja=f"利用可能なパーサーフィールド: {available_fields}。'{field_ref}' をパーサー設定に追加するか、参照を修正してください"
                    ))

    def _validate_prompt_parser_consistency(
        self,
        step: WorkflowStep,
        revision: PromptRevision,
        all_steps: List[WorkflowStep],
        result: ValidationResult
    ):
        """Validate that prompt output format matches parser configuration.

        Checks:
        1. If prompt expects JSON output, parser should be json/json_path
        2. If parser expects JSON, prompt should instruct JSON output
        3. If prompt expects single letter (A/B/C/D), json parser may be inappropriate
        4. If subsequent steps reference parser fields, they should exist

        Args:
            step: The prompt step being validated
            revision: The prompt revision with template and parser config
            all_steps: All steps in workflow
            result: ValidationResult to add issues to
        """
        if not revision.prompt_template:
            return

        # Analyze prompt content
        expects_json = self._prompt_expects_json(revision.prompt_template)
        expects_single_letter = self._prompt_expects_single_letter(revision.prompt_template)

        # Parse parser configuration
        parser_type, parser_fields = self._parse_parser_config(revision.parser_config)

        # Check 1: Prompt expects JSON but parser is not JSON-capable
        if expects_json and parser_type in ("none", "regex"):
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="parser",
                message="Prompt expects JSON output but parser is not configured for JSON",
                message_ja="プロンプトでJSON出力を指示していますが、パーサーがJSON対応ではありません",
                suggestion="Use parser type 'json' or 'json_path' to parse JSON output",
                suggestion_ja="JSON出力をパースするには 'json' または 'json_path' パーサーを使用してください"
            ))

        # Check 2: Parser expects JSON but prompt doesn't instruct JSON output
        if parser_type in ("json", "json_path") and not expects_json:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="parser",
                message="Parser expects JSON but prompt does not appear to instruct JSON output",
                message_ja="パーサーがJSON形式を期待していますが、プロンプトでJSON出力を指示していないようです",
                suggestion="Add JSON output instructions to the prompt, or change parser type to 'regex' or 'none'",
                suggestion_ja="プロンプトにJSON出力指示を追加するか、パーサータイプを 'regex' または 'none' に変更してください"
            ))

        # Check 3: Single letter answer expected but using JSON parser
        if expects_single_letter and parser_type in ("json", "json_path"):
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="parser",
                message="Prompt expects single letter answer (A/B/C/D) but parser is configured for JSON",
                message_ja="プロンプトは単一文字回答（A/B/C/D）を期待していますが、パーサーがJSON用に設定されています",
                suggestion="Use 'regex' parser with pattern like '[A-D]' for single letter extraction",
                suggestion_ja="単一文字抽出には 'regex' パーサーとパターン '[A-D]' の使用を推奨します"
            ))

        # Check 4: Validate parser field references in subsequent steps
        self._validate_parser_field_references(step, parser_type, parser_fields, all_steps, result)


def validate_workflow(db: Session, workflow_id: int, update_flag: bool = True) -> ValidationResult:
    """Convenience function to validate a workflow.

    Args:
        db: Database session
        workflow_id: Workflow ID to validate
        update_flag: If True, update the workflow's validated flag based on results.
                     Set to True if errors=0, False otherwise. Warnings are allowed.

    Returns:
        ValidationResult with all issues found
    """
    from backend.database.models import Workflow

    validator = WorkflowValidator(db)
    result = validator.validate_workflow(workflow_id)

    # Update the validated flag if requested
    if update_flag:
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if workflow:
            # validated = 1 if no errors (warnings are OK)
            workflow.validated = 1 if result.errors == 0 else 0
            db.commit()

    return result


def get_dataset_columns(db: Session, dataset_id: int) -> List[str]:
    """Get column names for a dataset.

    Args:
        db: Database session
        dataset_id: The ID of the dataset

    Returns:
        List of column names in the dataset
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset or not dataset.sqlite_table_name:
        return []

    try:
        col_result = db.execute(text(f'PRAGMA table_info("{dataset.sqlite_table_name}")'))
        return [row[1] for row in col_result]
    except Exception as e:
        logger.error(f"Failed to get columns for dataset {dataset_id}: {e}")
        return []


def get_available_variables_at_step(
    db: Session,
    workflow_id: int,
    step_order: int
) -> Dict[str, Any]:
    """Get all available variables and functions at a specific workflow step.

    This function calculates what variables are available for use in a step's
    input_mapping or condition_config based on:
    - Input variables (from workflow initial input)
    - SET variables defined before this step
    - FOREACH item_var and index_var (if inside a FOREACH loop)
    - Dataset columns (if FOREACH uses a dataset source)
    - Previous step outputs (parser fields)
    - Available functions

    Args:
        db: Database session
        workflow_id: The ID of the workflow
        step_order: The step order (1-based) to check variables for

    Returns:
        Dict containing:
        - workflow_id: The workflow ID
        - step_order: The requested step order
        - step_name: Name of the step (if exists)
        - categories: List of variable categories with variables
        - functions: List of available functions
        - foreach_context: Info about enclosing FOREACH (if any)
    """
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        return {
            "error": f"Workflow {workflow_id} not found",
            "workflow_id": workflow_id,
            "step_order": step_order
        }

    # Get all steps ordered
    steps = list(db.query(WorkflowStep).filter(
        WorkflowStep.workflow_id == workflow_id
    ).order_by(WorkflowStep.step_order).all())

    if not steps:
        return {
            "workflow_id": workflow_id,
            "workflow_name": workflow.name,
            "step_order": step_order,
            "step_name": None,
            "categories": [],
            "functions": _get_available_functions(),
            "foreach_context": None
        }

    # Find the current step
    current_step = None
    for s in steps:
        if s.step_order == step_order:
            current_step = s
            break

    categories = []

    # Track variables and FOREACH context
    set_variables = []  # Variables defined by SET steps
    foreach_stack = []  # Stack of FOREACH contexts
    previous_step_outputs = []  # Outputs from prompt steps
    custom_params = []  # Custom parameters from prompt steps

    # Process steps before current step
    for step in steps:
        if step.step_order >= step_order:
            break

        step_type = step.step_type or "prompt"

        # Track SET variables
        if step_type == 'set' and step.condition_config:
            try:
                config = json.loads(step.condition_config)
                assignments = config.get('assignments', {})
                for var_name in assignments.keys():
                    set_variables.append({
                        "name": var_name,
                        "variable": f"{{{{vars.{var_name}}}}}",
                        "type": "wf_var",
                        "source": f"Step {step.step_order}: {step.step_name} (SET)"
                    })
            except json.JSONDecodeError:
                pass

        # Track FOREACH variables
        elif step_type == 'foreach' and step.condition_config:
            try:
                config = json.loads(step.condition_config)
                item_var = config.get('item_var', 'item')
                index_var = config.get('index_var', 'i')
                source = config.get('source', config.get('list_ref', ''))

                foreach_stack.append({
                    "step_order": step.step_order,
                    "step_name": step.step_name,
                    "item_var": item_var,
                    "index_var": index_var,
                    "source": source
                })
            except json.JSONDecodeError:
                pass

        # Pop FOREACH when encountering ENDFOREACH
        elif step_type == 'endforeach' and foreach_stack:
            foreach_stack.pop()

        # Track prompt step outputs
        elif step_type == 'prompt' and step.prompt_id:
            prompt = db.query(Prompt).filter(
                Prompt.id == step.prompt_id,
                Prompt.is_deleted == 0
            ).first()

            if prompt:
                # Get parser fields from latest revision
                revision = db.query(PromptRevision).filter(
                    PromptRevision.prompt_id == step.prompt_id
                ).order_by(PromptRevision.revision.desc()).first()

                step_outputs = []

                # Always add raw output
                step_outputs.append({
                    "name": "raw",
                    "variable": f"{{{{{step.step_name}.raw}}}}",
                    "type": "output",
                    "source": "LLM生の出力"
                })

                # Add parser fields if configured
                if revision and revision.parser_config:
                    try:
                        parser_config = json.loads(revision.parser_config)
                        parser_type = parser_config.get('type', 'none')

                        if parser_type == 'json_path':
                            paths = parser_config.get('paths', {})
                            for field_name in paths.keys():
                                step_outputs.append({
                                    "name": field_name,
                                    "variable": f"{{{{{step.step_name}.{field_name}}}}}",
                                    "type": "output",
                                    "source": f"パーサー ({parser_type})"
                                })
                        elif parser_type == 'regex':
                            patterns = parser_config.get('patterns', {})
                            for field_name in patterns.keys():
                                step_outputs.append({
                                    "name": field_name,
                                    "variable": f"{{{{{step.step_name}.{field_name}}}}}",
                                    "type": "output",
                                    "source": f"パーサー ({parser_type})"
                                })
                        elif parser_type == 'json':
                            fields = parser_config.get('fields', [])
                            if fields:
                                for field_name in fields:
                                    step_outputs.append({
                                        "name": field_name,
                                        "variable": f"{{{{{step.step_name}.{field_name}}}}}",
                                        "type": "output",
                                        "source": f"パーサー ({parser_type})"
                                    })
                    except json.JSONDecodeError:
                        pass

                if step_outputs:
                    previous_step_outputs.append({
                        "step_order": step.step_order,
                        "step_name": step.step_name,
                        "prompt_name": prompt.name,
                        "outputs": step_outputs
                    })

            # Track custom parameters from input_mapping
            # A custom parameter is any key NOT in the prompt template
            if step.input_mapping:
                try:
                    mapping = json.loads(step.input_mapping)

                    # Get prompt template parameters
                    template_params = set()
                    if revision and revision.prompt_template:
                        # Parse template to extract parameter names
                        import re
                        param_pattern = re.compile(r'\{\{([^}:]+)(?::[^}]*)?\}\}')
                        for match in param_pattern.finditer(revision.prompt_template):
                            template_params.add(match.group(1).strip())

                    # Any input_mapping key NOT in template is a custom param
                    for key, value in mapping.items():
                        if key not in template_params:
                            custom_params.append({
                                "name": key,
                                "variable": f"{{{{{step.step_name}.{key}}}}}",
                                "type": "custom_param",
                                "source": f"Step {step.step_order}: {step.step_name}"
                            })
                except json.JSONDecodeError:
                    pass

    # Category 1: Initial Input
    categories.append({
        "category_id": "input",
        "category_name": "📥 初期入力 / Initial Input",
        "variables": [{
            "name": "パラメータ名",
            "variable": "{{input.パラメータ名}}",
            "type": "input",
            "source": "ワークフロー初期入力（実際のパラメータ名に置き換え）"
        }]
    })

    # Category 2: Workflow Variables (SET)
    if set_variables:
        categories.append({
            "category_id": "wf_variables",
            "category_name": "🏷️ ワークフロー変数 / WF Variables",
            "variables": set_variables
        })

    # Category 3: FOREACH Context (if inside a FOREACH loop)
    foreach_context = None
    if foreach_stack:
        # Use the innermost FOREACH
        current_foreach = foreach_stack[-1]
        foreach_context = current_foreach.copy()

        item_var = current_foreach["item_var"]
        index_var = current_foreach["index_var"]
        source = current_foreach["source"]

        foreach_vars = []

        # Add item variable (full row)
        foreach_vars.append({
            "name": f"{item_var} (行全体)",
            "variable": f"{{{{vars.{item_var}}}}}",
            "type": "foreach_item",
            "source": f"FOREACH: {current_foreach['step_name']}"
        })

        # Add index variable
        foreach_vars.append({
            "name": f"{index_var} (インデックス)",
            "variable": f"{{{{vars.{index_var}}}}}",
            "type": "foreach_index",
            "source": "0から始まるループインデックス"
        })

        # If source is a dataset, get columns
        dataset_id = None
        dataset_name = None
        if source.startswith('dataset:'):
            # Parse dataset:ID[:...] format
            match = re.match(r'^dataset:(\d+)', source)
            if match:
                dataset_id = int(match.group(1))
                dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
                if dataset:
                    dataset_name = dataset.name
                    columns = get_dataset_columns(db, dataset_id)
                    for col in columns:
                        foreach_vars.append({
                            "name": col,
                            "variable": f"{{{{vars.{item_var}.{col}}}}}",
                            "type": "foreach_column",
                            "source": f"Dataset: {dataset_name}"
                        })

        if foreach_vars:
            categories.append({
                "category_id": "foreach_context",
                "category_name": f"🔄 FOREACH: {item_var}",
                "variables": foreach_vars
            })

        # Update foreach_context with dataset info
        foreach_context["dataset_id"] = dataset_id
        foreach_context["dataset_name"] = dataset_name

    # Category: Custom Parameters from prompt steps
    if custom_params:
        categories.append({
            "category_id": "custom_params",
            "category_name": "🔧 カスタムパラメータ / Custom Params",
            "variables": custom_params
        })

    # Category 4+: Previous Step Outputs
    for step_output in previous_step_outputs:
        categories.append({
            "category_id": f"step_{step_output['step_order']}",
            "category_name": f"📤 Step {step_output['step_order']}: {step_output['step_name']} の出力",
            "variables": step_output["outputs"]
        })

    return {
        "workflow_id": workflow_id,
        "workflow_name": workflow.name,
        "step_order": step_order,
        "step_name": current_step.step_name if current_step else None,
        "categories": categories,
        "functions": _get_available_functions(),
        "foreach_context": foreach_context
    }


def _get_available_functions() -> List[Dict[str, str]]:
    """Get list of available workflow functions."""
    return [
        {"name": "calc", "example": "calc({{vars.x}} + 1)", "desc": "算術計算"},
        {"name": "upper", "example": "upper({{vars.text}})", "desc": "大文字変換"},
        {"name": "lower", "example": "lower({{vars.text}})", "desc": "小文字変換"},
        {"name": "trim", "example": "trim({{vars.text}})", "desc": "前後の空白削除"},
        {"name": "length", "example": "length({{vars.text}})", "desc": "文字数取得"},
        {"name": "slice", "example": "slice({{vars.text}}, 0, 10)", "desc": "部分文字列"},
        {"name": "replace", "example": "replace({{vars.text}}, old, new)", "desc": "文字列置換"},
        {"name": "split", "example": "split({{vars.text}}, ,)", "desc": "文字列分割"},
        {"name": "join", "example": "join({{vars.list}}, ,)", "desc": "配列結合"},
        {"name": "concat", "example": "concat(a, b, c)", "desc": "文字列連結"},
        {"name": "default", "example": "default({{vars.x}}, fallback)", "desc": "デフォルト値"},
        {"name": "ifempty", "example": "ifempty({{vars.x}}, fallback)", "desc": "空なら代替値"},
        {"name": "contains", "example": "contains({{vars.text}}, search)", "desc": "含むか判定"},
        {"name": "startswith", "example": "startswith({{vars.text}}, prefix)", "desc": "前方一致"},
        {"name": "endswith", "example": "endswith({{vars.text}}, suffix)", "desc": "後方一致"},
        {"name": "format_choices", "example": "format_choices({{vars.ROW.choices}})", "desc": "選択肢JSON→テキスト"},
        {"name": "json_parse", "example": "json_parse({{vars.json_str}})", "desc": "JSONパース"},
        {"name": "json_zip", "example": "json_zip(keys, values)", "desc": "キーと値をJSON化"},
        {"name": "now", "example": "now()", "desc": "現在日時"},
        {"name": "today", "example": "today()", "desc": "今日の日付"},
        {"name": "debug", "example": "debug({{vars.x}})", "desc": "デバッグ出力"},
    ]

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

from .database.models import Workflow, WorkflowStep, Prompt, PromptRevision

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
    STEP_REF_PATTERN = re.compile(r'\{\{(\w+)\.(\w+)\}\}')
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
                    message_ja=f"ステップ名 '{name}' は予約語です",
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
                    message_ja=f"ステップ名 '{name}' が重複しています (ステップID {seen_names[name]} でも使用)",
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
                    message_ja=f"ステップ名の形式が無効です: '{name}'",
                    suggestion="Step names must start with a letter and contain only alphanumeric characters and underscores",
                    suggestion_ja="ステップ名は英字で始まり、英数字とアンダースコアのみ使用可能です"
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
                        message_ja=f"{step_type.upper()} に対応する IF がありません",
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
                        message_ja=f"{step_type.upper()} に対応する {expected_starter.upper() if expected_starter else '開始ブロック'} がありません",
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
                        message_ja=f"{step_type.upper()} がステップ {opener[2]} ('{opener[3]}') の {opener[0].upper()} と一致しません",
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
                        message_ja=f"{step_type.upper()} が LOOP または FOREACH の外にあります",
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
                message_ja=f"{opener[0].upper()} ブロックが閉じられていません",
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

        for step in steps:
            step_names_by_order[step.step_order] = cumulative_names.copy()
            vars_by_order[step.step_order] = cumulative_vars.copy()
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
                    cumulative_vars.add(item_var)
                    foreach_var_stack.append(item_var)
                except json.JSONDecodeError:
                    pass

            # Remove FOREACH item_var from scope when exiting FOREACH block
            elif step.step_type == 'endforeach' and foreach_var_stack:
                exited_var = foreach_var_stack.pop()
                # Note: We keep the variable in cumulative_vars for simplicity
                # since most workflows don't reuse the same variable name outside

        for step in steps:
            available_steps = step_names_by_order.get(step.step_order, set())
            available_vars = vars_by_order.get(step.step_order, set())

            # Check input_mapping
            if step.input_mapping:
                try:
                    mapping = json.loads(step.input_mapping)
                    for param_name, ref_pattern in mapping.items():
                        self._validate_reference_string(
                            ref_pattern, available_steps, available_vars, step, result, f"input_mapping['{param_name}']"
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
                                str(config[field]), available_steps, available_vars, step, result, f"condition_config['{field}']"
                            )

                    # Check 'source' in FOREACH
                    if 'source' in config:
                        self._validate_reference_string(
                            str(config['source']), available_steps, available_vars, step, result, "condition_config['source']"
                        )

                    # Check 'assignments' in SET
                    if 'assignments' in config:
                        for var_name, value_expr in config['assignments'].items():
                            self._validate_reference_string(
                                str(value_expr), available_steps, available_vars, step, result, f"assignments['{var_name}']"
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
        context: str
    ):
        """Validate step and variable references in a string."""
        # Find all {{step.field}} references
        for match in self.STEP_REF_PATTERN.finditer(ref_string):
            ref_step = match.group(1)
            ref_field = match.group(2)

            # 'input' is always available
            if ref_step == 'input':
                continue

            # Check 'vars' references against defined variables
            if ref_step == 'vars':
                var_name = ref_field
                if var_name not in available_vars:
                    result.add_issue(ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        step_id=step.id,
                        step_name=step.step_name,
                        step_order=step.step_order,
                        category="reference",
                        message=f"Reference to undefined variable '{{{{vars.{var_name}}}}}' in {context}",
                        message_ja=f"{context} で未定義の変数 '{{{{vars.{var_name}}}}}' を参照しています",
                        suggestion=f"Define '{var_name}' in a SET step before this step, or use {{{{input.{var_name}}}}} for workflow input",
                        suggestion_ja=f"このステップより前に SET ステップで '{var_name}' を定義するか、ワークフロー入力として {{{{input.{var_name}}}}} を使用してください"
                    ))
                continue

            # Check if ref_step is a FOREACH item_var (e.g., {{ROW.field}})
            # These are defined variables that can be referenced directly without 'vars.' prefix
            if ref_step in available_vars:
                continue  # Valid FOREACH item variable reference

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
        """Validate formula function syntax."""
        formula_str = formula_str.strip()

        # Check if it's a formula
        match = self.FORMULA_PATTERN.match(formula_str)
        if not match:
            return  # Not a formula, nothing to validate

        func_name = match.group(1).lower()
        args_str = match.group(2)

        # Validate function name
        if func_name not in self.VALID_FUNCTIONS:
            result.add_issue(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                step_id=step.id,
                step_name=step.step_name,
                step_order=step.step_order,
                category="formula",
                message=f"Unknown function '{func_name}' in {context}",
                message_ja=f"{context} で不明な関数 '{func_name}' を使用しています",
                suggestion=f"Valid functions: {', '.join(sorted(self.VALID_FUNCTIONS))}",
                suggestion_ja=f"有効な関数: {', '.join(sorted(self.VALID_FUNCTIONS))}"
            ))
            return

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
        """Validate prompt steps have valid prompt_id or project_id."""
        for step in steps:
            step_type = step.step_type or "prompt"

            if step_type != "prompt":
                continue

            # Check if prompt_id or project_id is set
            if not step.prompt_id and not step.project_id:
                result.add_issue(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    step_id=step.id,
                    step_name=step.step_name,
                    step_order=step.step_order,
                    category="config",
                    message="Prompt step requires prompt_id or project_id",
                    message_ja="プロンプトステップには prompt_id または project_id が必要です"
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
                        message_ja=f"プロンプト ID {step.prompt_id} が見つからないか削除されています"
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
                            message_ja=f"プロンプト ID {step.prompt_id} のリビジョンが見つかりません"
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


def validate_workflow(db: Session, workflow_id: int) -> ValidationResult:
    """Convenience function to validate a workflow.

    Args:
        db: Database session
        workflow_id: Workflow ID to validate

    Returns:
        ValidationResult with all issues found
    """
    validator = WorkflowValidator(db)
    return validator.validate_workflow(workflow_id)

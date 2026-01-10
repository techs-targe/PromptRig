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
    Project, ProjectRevision, Prompt, PromptRevision, Job, JobItem,
    Dataset
)
from .job import JobManager
from .prompt import PromptTemplateParser, get_message_parser
from .formula_parser import (
    FormulaParser, validate_formula, TokenizerError, ParseError, EvaluationError
)

logger = logging.getLogger(__name__)


def _decode_escape_sequences(text: str) -> str:
    """Decode common escape sequences in text.

    Converts literal escape sequences to actual characters:
    - \\n → newline
    - \\t → tab
    - \\r → carriage return
    - \\" → double quote
    - \\' → single quote
    - \\\\ → backslash

    Args:
        text: String potentially containing escape sequences

    Returns:
        String with escape sequences decoded
    """
    if not text:
        return text

    # Replace escape sequences in order (backslash must be last to avoid double processing)
    replacements = [
        ('\\n', '\n'),
        ('\\t', '\t'),
        ('\\r', '\r'),
        ('\\"', '"'),
        ("\\'", "'"),
        ('\\\\', '\\'),
    ]

    result = text
    for escaped, actual in replacements:
        result = result.replace(escaped, actual)

    return result


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

    Dataset iteration (FOREACH):
    - dataset:ID - Iterate over all rows as dict objects
    - dataset:ID:column - Iterate over values from specific column
    - dataset:ID:col1,col2 - Iterate over rows with selected columns only
    """

    # Pattern to match step references: {{step_name.field_name}} or nested {{a.b.c.d}}
    # Supports unlimited nesting depth for JSON field access
    STEP_REF_PATTERN = re.compile(r'\{\{(\w+(?:\.\w+)+)\}\}')

    # Pattern to match formula expressions: func_name(args)
    # Supported functions: sum, upper, lower, trim, length, slice, replace,
    # split, join, concat, default, contains, startswith, endswith, count,
    # left, right, repeat, reverse, capitalize, title, lstrip, rstrip,
    # getprompt, getparser
    FORMULA_PATTERN = re.compile(
        r'^(sum|upper|lower|trim|length|len|slice|substr|substring|replace|'
        r'split|join|concat|default|ifempty|contains|startswith|endswith|'
        r'count|left|right|repeat|reverse|capitalize|title|lstrip|rstrip|'
        r'shuffle|debug|calc|getprompt|getparser|json_parse|json_zip|format_choices|'
        r'dataset_filter|dataset_join|array_push)\((.+)\)$',
        re.IGNORECASE
    )

    # Available string functions for documentation/UI
    STRING_FUNCTIONS = {
        # 文字列操作 / Text Operations
        'upper': {
            'args': 1, 'desc': '大文字変換 / Convert to uppercase',
            'example': 'upper({{step.text}})',
            'usage': ['upper("hello") → "HELLO"', 'upper("Tokyo") → "TOKYO"']
        },
        'lower': {
            'args': 1, 'desc': '小文字変換 / Convert to lowercase',
            'example': 'lower({{step.text}})',
            'usage': ['lower("HELLO") → "hello"', 'lower("Tokyo") → "tokyo"']
        },
        'trim': {
            'args': 1, 'desc': '前後空白削除 / Remove leading/trailing whitespace',
            'example': 'trim({{step.text}})',
            'usage': ['trim("  hello  ") → "hello"', 'trim("\\n text \\n") → "text"']
        },
        'lstrip': {
            'args': 1, 'desc': '先頭空白削除 / Remove leading whitespace',
            'example': 'lstrip({{step.text}})',
            'usage': ['lstrip("  hello") → "hello"', 'lstrip("\\t text") → "text"']
        },
        'rstrip': {
            'args': 1, 'desc': '末尾空白削除 / Remove trailing whitespace',
            'example': 'rstrip({{step.text}})',
            'usage': ['rstrip("hello  ") → "hello"', 'rstrip("text\\n") → "text"']
        },
        'length': {
            'args': 1, 'desc': '文字数 / String length',
            'example': 'length({{step.text}})',
            'usage': ['length("hello") → 5', 'length("日本語") → 3']
        },
        'len': {
            'args': 1, 'desc': '文字数 (lengthのエイリアス) / String length (alias)',
            'example': 'len({{step.text}})',
            'usage': ['len("hello") → 5', 'len("") → 0']
        },
        'capitalize': {
            'args': 1, 'desc': '先頭大文字 / Capitalize first letter',
            'example': 'capitalize({{step.text}})',
            'usage': ['capitalize("hello world") → "Hello world"', 'capitalize("HELLO") → "Hello"']
        },
        'title': {
            'args': 1, 'desc': '各単語先頭大文字 / Title case',
            'example': 'title({{step.text}})',
            'usage': ['title("hello world") → "Hello World"', 'title("the quick fox") → "The Quick Fox"']
        },
        'reverse': {
            'args': 1, 'desc': '文字列反転 / Reverse string',
            'example': 'reverse({{step.text}})',
            'usage': ['reverse("hello") → "olleh"', 'reverse("12345") → "54321"']
        },
        'slice': {
            'args': '2-3', 'desc': '部分文字列 / Extract substring',
            'example': 'slice({{step.text}}, 0, 10)',
            'usage': ['slice("hello world", 0, 5) → "hello"', 'slice("hello", 2) → "llo"', 'slice("hello", -2) → "lo"']
        },
        'left': {
            'args': 2, 'desc': '先頭N文字 / Left N characters',
            'example': 'left({{step.text}}, 5)',
            'usage': ['left("hello world", 5) → "hello"', 'left("abc", 10) → "abc"']
        },
        'right': {
            'args': 2, 'desc': '末尾N文字 / Right N characters',
            'example': 'right({{step.text}}, 5)',
            'usage': ['right("hello world", 5) → "world"', 'right("abc", 10) → "abc"']
        },
        'replace': {
            'args': 3, 'desc': '置換 / Replace substring',
            'example': 'replace({{step.text}}, old, new)',
            'usage': ['replace("hello", "l", "L") → "heLLo"', 'replace("a-b-c", "-", "_") → "a_b_c"']
        },
        'repeat': {
            'args': 2, 'desc': '繰り返し / Repeat N times',
            'example': 'repeat({{step.text}}, 3)',
            'usage': ['repeat("ab", 3) → "ababab"', 'repeat("-", 10) → "----------"']
        },
        'split': {
            'args': 2, 'desc': '分割(JSON配列) / Split into array',
            'example': 'split({{step.text}}, ,)',
            'usage': ['split("a,b,c", ",") → ["a","b","c"]', 'split("1;2;3", ";") → ["1","2","3"]']
        },
        'join': {
            'args': 2, 'desc': '結合 / Join array elements',
            'example': 'join({{step.items}}, ,)',
            'usage': ['join(["a","b","c"], "-") → "a-b-c"', 'join(["1","2"], "") → "12"']
        },
        'concat': {
            'args': '2+', 'desc': '連結 / Concatenate strings',
            'example': 'concat({{step1.a}}, -, {{step2.b}})',
            'usage': ['concat("Hello", " ", "World") → "Hello World"', 'concat({{vars.first}}, {{vars.last}}) → 名前結合']
        },
        'default': {
            'args': 2, 'desc': '空の場合のデフォルト値 / Default if empty',
            'example': 'default({{step.text}}, N/A)',
            'usage': ['default("", "N/A") → "N/A"', 'default("value", "N/A") → "value"', 'default(null, "未設定") → "未設定"']
        },
        'ifempty': {
            'args': 2, 'desc': '空の場合のデフォルト値 (defaultのエイリアス) / Default if empty (alias)',
            'example': 'ifempty({{step.text}}, N/A)',
            'usage': ['ifempty("", "デフォルト") → "デフォルト"', 'ifempty({{step.result}}, "結果なし")']
        },
        # 検索・判定 / Search & Check
        'contains': {
            'args': 2, 'desc': '含むか / Check if contains',
            'example': 'contains({{step.text}}, word)',
            'usage': ['contains("hello world", "world") → true', 'contains("abc", "x") → false']
        },
        'startswith': {
            'args': 2, 'desc': '先頭一致 / Check if starts with',
            'example': 'startswith({{step.text}}, prefix)',
            'usage': ['startswith("hello", "he") → true', 'startswith("world", "he") → false']
        },
        'endswith': {
            'args': 2, 'desc': '末尾一致 / Check if ends with',
            'example': 'endswith({{step.text}}, suffix)',
            'usage': ['endswith("hello.txt", ".txt") → true', 'endswith("file.pdf", ".txt") → false']
        },
        'count': {
            'args': 2, 'desc': '出現回数 / Count occurrences',
            'example': 'count({{step.text}}, a)',
            'usage': ['count("banana", "a") → 3', 'count("hello", "l") → 2']
        },
        # 計算 / Math
        'sum': {
            'args': '2+', 'desc': '合計 / Sum of numbers',
            'example': 'sum({{step1.score}}, {{step2.score}})',
            'usage': ['sum(1, 2, 3) → 6', 'sum({{vars.a}}, {{vars.b}}) → 2つの変数の合計']
        },
        'calc': {
            'args': 1, 'desc': '計算式評価 / Evaluate arithmetic expression',
            'example': 'calc({{vars.x}} + 1)',
            'usage': ['calc(10 + 5) → 15', 'calc({{vars.score}} * 2) → スコアを2倍', 'calc(100 / 4) → 25', 'calc({{vars.correct}} / {{vars.total}} * 100) → 正解率%']
        },
        # JSON処理 / JSON Processing
        'json_parse': {
            'args': 1, 'desc': 'JSON文字列をパース / Parse JSON string for nested access',
            'example': 'json_parse({{step.result}})',
            'usage': ['json_parse(\'{"name":"太郎"}\').name → "太郎"', 'json_parse({{step.json}}).items[0] → 最初の要素']
        },
        'json_zip': {
            'args': '2+', 'desc': '複数キーの配列をzip / Zip arrays from JSON into list of dicts',
            'example': 'json_zip({{step.json}}, text, label)',
            'usage': ['json_zip({"a":[1,2],"b":["x","y"]}, a, b) → [{"a":1,"b":"x"},{"a":2,"b":"y"}]', 'FOREACHで複数配列を同時処理する場合に使用']
        },
        'format_choices': {
            'args': 1, 'desc': '選択肢JSONをフォーマット / Format choices JSON as A:text, B:text...',
            'example': 'format_choices({{step.choices}})',
            'usage': ['format_choices({"A":"りんご","B":"みかん"}) → "A: りんご\\nB: みかん"', 'クイズの選択肢表示に使用']
        },
        # データセット / Dataset
        'dataset_filter': {
            'args': 2, 'desc': 'データセット絞り込み (AND/OR/数値比較/LIKE対応) / Filter dataset rows',
            'example': "dataset_filter(dataset:6, \"score>80 AND category='a'\")",
            'usage': [
                "dataset_filter(dataset:6, \"category='A'\") → カテゴリAの行のみ",
                "dataset_filter(dataset:6, \"score>=80\") → 80点以上",
                "dataset_filter(dataset:6, \"name LIKE 'test%'\") → test始まり",
                "dataset_filter(dataset:6, \"status='done' OR status='skip'\") → OR条件",
                "dataset_filter(dataset:6, \"score>50 AND category='math'\") → AND条件",
                "dataset_filter(dataset:6, \"comment IS NULL\") → NULLの行のみ",
                "dataset_filter(dataset:6, \"comment IS NOT NULL\") → NULLでない行のみ",
                "【FOREACHソース】source: dataset_filter(...) → 条件に合う行をイテレート"
            ]
        },
        'dataset_join': {
            'args': '2-3', 'desc': 'データセットカラム値を結合 / Join column values with separator',
            'example': "dataset_join(dataset:6, \"value\", \"\\n\")",
            'usage': ['dataset_join(dataset:6, "name", ", ") → "田中, 鈴木, 佐藤"', 'dataset_join(dataset:6, "id") → "1,2,3" (デフォルト区切り)']
        },
        # 配列操作関数 / Array manipulation functions
        'array_push': {
            'args': 2, 'desc': '配列に要素を追加 / Push element to array',
            'example': 'array_push({{vars.items}}, {{step.value}})',
            'usage': ['array_push({{vars.results}}, {{step.answer}}) → ループで結果を蓄積', 'array_push([], "first") → ["first"]']
        },
        'shuffle': {
            'args': '1-2', 'desc': 'シャッフル / Shuffle (1引数:文字, 2引数:デリミタ分割)',
            'example': 'shuffle({{step.items}}, ;)',
            'usage': ['shuffle("abc") → "bca" (文字単位)', 'shuffle("A;B;C", ";") → "C;A;B" (デリミタ分割)']
        },
        # 日時関数 / Date and time functions
        'now': {
            'args': '0-1', 'desc': '現在日時 / Current datetime',
            'example': 'now(%Y-%m-%d %H:%M:%S)',
            'usage': ['now() → "2024-01-15 14:30:00"', 'now(%Y年%m月%d日) → "2024年01月15日"']
        },
        'today': {
            'args': '0-1', 'desc': '今日の日付 / Today\'s date',
            'example': 'today(%Y-%m-%d)',
            'usage': ['today() → "2024-01-15"', 'today(%m/%d) → "01/15"']
        },
        'time': {
            'args': '0-1', 'desc': '現在時刻 / Current time',
            'example': 'time(%H:%M:%S)',
            'usage': ['time() → "14:30:00"', 'time(%H時%M分) → "14時30分"']
        },
        # ユーティリティ / Utility
        'debug': {
            'args': '1+', 'desc': 'デバッグ出力 / Debug output to log',
            'example': 'debug({{step.result}})',
            'usage': ['debug({{vars.counter}}) → サーバーログに値を出力', 'debug("checkpoint", {{step.data}}) → ラベル付きデバッグ']
        },
        'getprompt': {
            'args': '1-3', 'desc': 'プロンプト内容取得 / Get prompt content',
            'example': 'getprompt(プロンプト名, CURRENT, CURRENT)',
            'usage': ['getprompt(質問プロンプト) → プロンプトテンプレート取得', 'getprompt(プロンプト名, プロジェクト名, リビジョン) → 特定バージョン取得']
        },
        'getparser': {
            'args': '1-3', 'desc': 'パーサー設定取得 / Get parser config',
            'example': 'getparser(プロンプト名, CURRENT, CURRENT)',
            'usage': ['getparser(質問プロンプト) → パーサー設定取得', 'getparser(プロンプト名, CURRENT, CURRENT) → 現在のプロジェクトから']
        },
    }

    # Special constants for getprompt/getparser functions
    SPECIAL_CONSTANTS = {
        'CURRENT': 'Use current project (workflow\'s project) or latest revision',
    }

    # Step types for control flow
    CONTROL_FLOW_TYPES = {'set', 'if', 'elif', 'else', 'endif', 'loop', 'endloop', 'foreach', 'endforeach', 'break', 'continue', 'output'}
    BLOCK_START_TYPES = {'if', 'loop', 'foreach'}
    BLOCK_END_TYPES = {'endif', 'endloop', 'endforeach'}

    # Output types for output step
    OUTPUT_TYPES = {'screen', 'file'}
    OUTPUT_FORMATS = {'text', 'csv', 'json'}

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

        # Add workflow metadata to context (for getprompt/getparser functions)
        step_context["_meta"] = {
            "workflow_id": workflow_id,
            "project_id": workflow.project_id,
            "project_name": workflow.project.name if workflow.project else None,
        }

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

                elif step_type == "output":
                    # Execute OUTPUT step
                    config = json.loads(step.condition_config or "{}")
                    output_result = self._execute_output_step(
                        step, steps, ip, step_context, variables, workflow_job
                    )
                    ip += 1
                    execution_trace.append({
                        "step_order": step.step_order,
                        "step_name": step.step_name,
                        "step_type": "output",
                        "action": "output_executed",
                        "output_type": config.get("output_type", "screen"),
                        "format": config.get("format", "text"),
                        "result": output_result.get("preview", "")[:100] if output_result else ""
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

    def _execute_output_step(
        self,
        step: WorkflowStep,
        steps: List[WorkflowStep],
        ip: int,
        step_context: Dict[str, Dict[str, Any]],
        variables: Dict[str, Any],
        workflow_job: WorkflowJob
    ) -> Dict[str, Any]:
        """Execute an OUTPUT step to output variables to screen or file.

        Args:
            step: Current step
            steps: All steps
            ip: Current instruction pointer
            step_context: Step context with outputs
            variables: Variables store
            workflow_job: WorkflowJob object

        Returns:
            Dict with output result info (preview, filename, etc.)

        Condition Config Schema:
            {
                "output_type": "screen" | "file",    // Output destination
                "format": "text" | "csv" | "json",   // Output format
                "content": "{{vars.x}}",             // For text format
                "columns": ["col1", "col2"],         // For CSV format (header names)
                "values": ["{{vars.a}}", "{{step.b}}"], // For CSV format (data values)
                "fields": {"key": "{{vars.x}}"},     // For JSON format
                "filename": "result.csv",            // For file output
                "append": true                       // Append mode (for foreach loops)
            }
        """
        import os
        import csv
        import io

        config = json.loads(step.condition_config or "{}")

        output_type = config.get("output_type", "screen")
        output_format = config.get("format", "text")
        append_mode = config.get("append", False)
        filename = config.get("filename", "")

        result = {
            "output_type": output_type,
            "format": output_format,
            "preview": "",
            "filename": None,
            "filepath": None
        }

        # Resolve filename if provided (may contain variables)
        if filename:
            filename = self._substitute_step_refs(filename, step_context)

        # Build output content based on format
        if output_format == "text":
            # Simple text output
            content = config.get("content", "")
            resolved_content = self._substitute_step_refs(str(content), step_context)
            result["content"] = resolved_content
            result["preview"] = resolved_content[:200]
            logger.info(f"OUTPUT (text): {resolved_content[:100]}...")

        elif output_format == "csv":
            # CSV output with columns and values
            columns = config.get("columns", [])
            values = config.get("values", [])

            # Resolve column names if they contain variables (usually static)
            resolved_columns = [self._substitute_step_refs(str(c), step_context) for c in columns]

            # Resolve values and strip surrounding quotes
            # (prevents triple-quoting when user accidentally adds literal quotes)
            resolved_values = []
            for v in values:
                resolved = self._substitute_step_refs(str(v), step_context)
                # Strip leading/trailing quotes if value is entirely quoted
                if len(resolved) >= 2 and resolved.startswith('"') and resolved.endswith('"'):
                    resolved = resolved[1:-1]
                resolved_values.append(resolved)

            # Build CSV row
            output_buffer = io.StringIO()
            writer = csv.writer(output_buffer, lineterminator='\n')
            writer.writerow(resolved_values)
            csv_row = output_buffer.getvalue().strip()

            result["columns"] = resolved_columns
            result["values"] = resolved_values
            result["csv_row"] = csv_row
            result["preview"] = csv_row[:200]

            # Add fields for _merge_csv_outputs() compatibility
            result["csv_output"] = csv_row
            result["csv_header"] = ",".join(resolved_columns) if resolved_columns else None

            logger.info(f"OUTPUT (csv): {csv_row[:100]}...")

        elif output_format == "json":
            # JSON output with fields
            fields = config.get("fields", {})
            resolved_fields = {}
            for key, value_expr in fields.items():
                resolved_value = self._substitute_step_refs(str(value_expr), step_context)
                # Try to parse as JSON if it looks like it
                try:
                    if resolved_value.startswith('{') or resolved_value.startswith('['):
                        resolved_fields[key] = json.loads(resolved_value)
                    else:
                        resolved_fields[key] = resolved_value
                except json.JSONDecodeError:
                    resolved_fields[key] = resolved_value

            result["fields"] = resolved_fields
            json_str = json.dumps(resolved_fields, ensure_ascii=False, indent=2)
            result["content"] = json_str
            result["preview"] = json_str[:200]
            logger.info(f"OUTPUT (json): {json_str[:100]}...")

        # Handle file output
        if output_type == "file" and filename:
            # Ensure uploads directory exists
            uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "workflow_outputs")
            os.makedirs(uploads_dir, exist_ok=True)

            # Sanitize filename
            safe_filename = "".join(c for c in filename if c.isalnum() or c in '._-')
            if not safe_filename:
                safe_filename = f"output_{workflow_job.id}_{step.step_name}"

            # Add extension if not present
            if output_format == "csv" and not safe_filename.endswith('.csv'):
                safe_filename += '.csv'
            elif output_format == "json" and not safe_filename.endswith('.json'):
                safe_filename += '.json'
            elif output_format == "text" and not safe_filename.endswith('.txt'):
                safe_filename += '.txt'

            filepath = os.path.join(uploads_dir, safe_filename)

            # Handle append mode for CSV (used in foreach loops)
            if output_format == "csv" and append_mode:
                file_exists = os.path.exists(filepath)
                with open(filepath, 'a', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f, lineterminator='\n')
                    # Write header only if file is new
                    if not file_exists and resolved_columns:
                        writer.writerow(resolved_columns)
                    writer.writerow(resolved_values)
                logger.info(f"OUTPUT (file/append): {filepath}")
            else:
                # Overwrite mode
                with open(filepath, 'w', encoding='utf-8', newline='') as f:
                    if output_format == "csv":
                        writer = csv.writer(f, lineterminator='\n')
                        if resolved_columns:
                            writer.writerow(resolved_columns)
                        writer.writerow(resolved_values)
                    elif output_format == "json":
                        f.write(result.get("content", "{}"))
                    else:
                        # Decode escape sequences for text format (e.g., \n → actual newline)
                        content = _decode_escape_sequences(result.get("content", ""))
                        f.write(content)
                logger.info(f"OUTPUT (file/write): {filepath}")

            result["filename"] = safe_filename
            result["filepath"] = filepath

        # Store output in step context
        # For CSV format, accumulate rows across foreach loop iterations
        if output_format == "csv":
            existing = step_context.get(step.step_name, {})
            existing_csv = existing.get("csv_output", "")
            new_csv = result.get("csv_output", "")

            if existing_csv and new_csv:
                # Append new row to existing rows
                result["csv_output"] = existing_csv + "\n" + new_csv
                # Keep header from first iteration
                result["csv_header"] = existing.get("csv_header") or result.get("csv_header")

        step_context[step.step_name] = result

        # Also store accumulated CSV data for merged output
        if output_format == "csv" and output_type == "file":
            # Track CSV outputs in a special context key
            if "_csv_outputs" not in step_context:
                step_context["_csv_outputs"] = {}

            output_key = step.step_name
            if output_key not in step_context["_csv_outputs"]:
                step_context["_csv_outputs"][output_key] = {
                    "columns": resolved_columns,
                    "rows": [],
                    "filename": result.get("filename"),
                    "filepath": result.get("filepath")
                }
            step_context["_csv_outputs"][output_key]["rows"].append(resolved_values)

        return result

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
        # Support both "source" (new) and "list_ref" (legacy) keys
        source_expr = config.get("source", "") or config.get("list_ref", "")
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
            source: Source string. Supported formats:
                - JSON array: ["a", "b", "c"]
                - Comma-separated: a, b, c
                - Dataset reference: dataset:ID (all rows as dicts)
                - Dataset column: dataset:ID:column (values from specific column)
                - Dataset columns: dataset:ID:col1,col2 (rows with selected columns)

        Returns:
            List of items
        """
        source = source.strip()

        # Check for dataset reference: dataset:ID or dataset:ID:columns
        if source.startswith('dataset:'):
            return self._load_dataset_for_foreach(source)

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

    def _evaluate_filter_condition(self, condition: str, row: dict) -> bool:
        """Evaluate a filter condition against a row.

        Supports:
        - column = 'value' or column == 'value' (equality)
        - column != 'value' or column <> 'value' (inequality)
        - column < 100, column > 50, column <= 80, column >= 20 (numeric)
        - column LIKE 'pattern%' (SQL-like pattern matching)
        - column contains 'text' (substring matching)
        - column IS NULL, column IS NOT NULL
        - column IS EMPTY, column IS NOT EMPTY
        - condition1 AND condition2
        - condition1 OR condition2

        Args:
            condition: Condition string
            row: Row dictionary to evaluate

        Returns:
            True if condition matches, False otherwise
        """
        condition = condition.strip()
        if not condition:
            return True

        # Handle OR first (lower precedence)
        # Split on ' OR ' (case insensitive) but not inside quotes
        or_parts = self._split_condition_by_operator(condition, ' OR ')
        if len(or_parts) > 1:
            return any(self._evaluate_filter_condition(part, row) for part in or_parts)

        # Handle AND (higher precedence)
        and_parts = self._split_condition_by_operator(condition, ' AND ')
        if len(and_parts) > 1:
            return all(self._evaluate_filter_condition(part, row) for part in and_parts)

        # Single condition - parse and evaluate
        return self._evaluate_single_condition(condition, row)

    def _split_condition_by_operator(self, condition: str, operator: str) -> List[str]:
        """Split condition by operator, respecting quoted strings.

        Args:
            condition: Condition string
            operator: Operator to split by (e.g., ' AND ', ' OR ')

        Returns:
            List of condition parts
        """
        # Simple split that handles quoted strings
        parts = []
        current = ""
        in_single_quote = False
        in_double_quote = False
        i = 0
        op_upper = operator.upper()
        cond_upper = condition.upper()

        while i < len(condition):
            char = condition[i]

            # Track quote state
            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
            elif char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote

            # Check for operator (case-insensitive) when not in quotes
            if not in_single_quote and not in_double_quote:
                if cond_upper[i:i+len(operator)] == op_upper:
                    if current.strip():
                        parts.append(current.strip())
                    current = ""
                    i += len(operator)
                    continue

            current += char
            i += 1

        if current.strip():
            parts.append(current.strip())

        return parts if len(parts) > 1 else [condition]

    def _evaluate_single_condition(self, condition: str, row: dict) -> bool:
        """Evaluate a single condition (no AND/OR).

        Args:
            condition: Single condition string
            row: Row dictionary

        Returns:
            True if condition matches
        """
        condition = condition.strip()

        # IS NULL / IS NOT NULL
        is_null_match = re.match(r"(\w+)\s+IS\s+(NOT\s+)?NULL", condition, re.IGNORECASE)
        if is_null_match:
            col_name = is_null_match.group(1)
            is_not = is_null_match.group(2) is not None
            row_value = row.get(col_name)
            is_null = row_value is None
            return not is_null if is_not else is_null

        # IS EMPTY / IS NOT EMPTY
        is_empty_match = re.match(r"(\w+)\s+IS\s+(NOT\s+)?EMPTY", condition, re.IGNORECASE)
        if is_empty_match:
            col_name = is_empty_match.group(1)
            is_not = is_empty_match.group(2) is not None
            row_value = row.get(col_name)
            is_empty = row_value is None or str(row_value).strip() == ""
            return not is_empty if is_not else is_empty

        # LIKE pattern matching
        like_match = re.match(r"(\w+)\s+LIKE\s+['\"](.+?)['\"]", condition, re.IGNORECASE)
        if like_match:
            col_name = like_match.group(1)
            pattern = like_match.group(2)
            row_value = str(row.get(col_name, ""))
            # Convert SQL LIKE pattern to regex: % -> .*, _ -> .
            regex_pattern = "^" + pattern.replace("%", ".*").replace("_", ".") + "$"
            try:
                return bool(re.match(regex_pattern, row_value, re.IGNORECASE))
            except re.error:
                return False

        # Standard comparison: column operator value
        # Operators: = == != <> < > <= >= contains
        comp_match = re.match(
            r"(\w+)\s*(<=|>=|<>|!=|==|=|<|>|contains)\s*['\"]?([^'\"]*)['\"]?",
            condition,
            re.IGNORECASE
        )
        if comp_match:
            col_name = comp_match.group(1)
            operator = comp_match.group(2).lower()
            value = comp_match.group(3)
            row_value = row.get(col_name)

            # Handle None values
            if row_value is None:
                row_value = ""

            row_value_str = str(row_value)

            # Equality operators
            if operator in ("=", "=="):
                return row_value_str == value
            elif operator in ("!=", "<>"):
                return row_value_str != value
            elif operator == "contains":
                return value.lower() in row_value_str.lower()

            # Numeric comparisons
            try:
                row_num = float(row_value_str) if row_value_str else 0
                val_num = float(value) if value else 0

                if operator == "<":
                    return row_num < val_num
                elif operator == ">":
                    return row_num > val_num
                elif operator == "<=":
                    return row_num <= val_num
                elif operator == ">=":
                    return row_num >= val_num
            except (ValueError, TypeError):
                # Fall back to string comparison for non-numeric values
                if operator == "<":
                    return row_value_str < value
                elif operator == ">":
                    return row_value_str > value
                elif operator == "<=":
                    return row_value_str <= value
                elif operator == ">=":
                    return row_value_str >= value

        # Unknown condition format - log and return False (exclude row)
        logger.warning(f"dataset_filter: Unknown condition format: {condition}")
        return False

    def _load_dataset_for_foreach(self, source: str) -> List[Any]:
        """Load dataset rows for FOREACH iteration.

        Args:
            source: Dataset reference string. Formats:
                - dataset:ID - All rows as dict objects
                - dataset:ID:column - Values from specific column as list
                - dataset:ID:col1,col2 - Rows with only selected columns
                - dataset:ID::limit:N - First N rows (all columns)
                - dataset:ID:column:limit:N - First N rows from specific column
                - dataset:ID:col1,col2:limit:N - First N rows with selected columns

        Returns:
            List of rows (dicts) or column values (strings)
        """
        from sqlalchemy import text
        import random as rand_module

        # Extract RANDOM clause if present (:random:N or :random:N:seed:S)
        limit_clause = None
        use_random = False
        random_seed = None

        if ':random:' in source:
            random_parts = source.split(':random:')
            source = random_parts[0]
            remaining = random_parts[1] if len(random_parts) > 1 else ""

            if ':seed:' in remaining:
                seed_parts = remaining.split(':seed:')
                try:
                    limit_clause = int(seed_parts[0])
                    random_seed = int(seed_parts[1])
                    use_random = True
                    logger.debug(f"FOREACH random: limit={limit_clause}, seed={random_seed}")
                except (ValueError, IndexError):
                    logger.warning(f"Invalid random/seed format: {remaining}")
                    return []  # Invalid syntax = 0 rows
            else:
                try:
                    limit_clause = int(remaining)
                    use_random = True
                    logger.debug(f"FOREACH random: limit={limit_clause}, no seed")
                except ValueError:
                    logger.warning(f"Invalid random limit: {remaining}")
                    return []  # Invalid syntax = 0 rows

        # Extract LIMIT clause if present (:limit:N or :limit:N:seed:S) - only if not using random
        elif ':limit:' in source:
            limit_parts = source.split(':limit:')
            source = limit_parts[0]
            remaining = limit_parts[1] if len(limit_parts) > 1 else ""

            if ':seed:' in remaining:
                # :limit:N:seed:S format
                seed_parts = remaining.split(':seed:')
                try:
                    limit_clause = int(seed_parts[0])
                    random_seed = int(seed_parts[1])
                    use_random = True  # Apply random shuffle with seed
                    logger.debug(f"FOREACH limit with seed: limit={limit_clause}, seed={random_seed}")
                except (ValueError, IndexError):
                    logger.warning(f"Invalid limit/seed format: {remaining}")
                    return []  # Invalid syntax = 0 rows
            else:
                # :limit:N format
                try:
                    limit_clause = int(remaining)
                    logger.debug(f"FOREACH limit: {limit_clause}")
                except (ValueError, IndexError):
                    logger.warning(f"Invalid limit value in source: {limit_parts}")
                    return []  # Invalid syntax = 0 rows

        parts = source.split(':', 2)  # Split into max 3 parts
        if len(parts) < 2:
            logger.warning(f"Invalid dataset reference: {source}")
            return []

        try:
            dataset_id = int(parts[1])
        except ValueError:
            logger.warning(f"Invalid dataset ID in: {source}")
            return []

        # Get dataset from database
        dataset = self.db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            logger.warning(f"Dataset {dataset_id} not found")
            return []

        table_name = dataset.sqlite_table_name
        if not table_name:
            logger.warning(f"Dataset {dataset_id} has no table")
            return []

        # Get column names from table
        try:
            col_result = self.db.execute(text(f'PRAGMA table_info("{table_name}")'))
            all_columns = [row[1] for row in col_result]
        except Exception as e:
            logger.error(f"Failed to get columns for dataset {dataset_id}: {e}")
            return []

        if not all_columns:
            logger.warning(f"Dataset {dataset_id} has no columns")
            return []

        # Determine which columns to select
        selected_columns = all_columns
        single_column = None

        if len(parts) == 3 and parts[2]:
            column_spec = parts[2].strip()
            if ',' in column_spec:
                # Multiple columns specified: dataset:ID:col1,col2
                selected_columns = [c.strip() for c in column_spec.split(',') if c.strip()]
                # Validate columns exist
                invalid_cols = [c for c in selected_columns if c not in all_columns]
                if invalid_cols:
                    logger.warning(f"Invalid columns {invalid_cols} in dataset {dataset_id}")
                    selected_columns = [c for c in selected_columns if c in all_columns]
                    if not selected_columns:
                        logger.warning(f"All specified columns are invalid for dataset {dataset_id}")
                        return []  # All columns invalid = 0 rows
            else:
                # Single column specified: dataset:ID:column
                if column_spec in all_columns:
                    single_column = column_spec
                    selected_columns = [column_spec]
                else:
                    logger.warning(f"Column '{column_spec}' not found in dataset {dataset_id}")
                    return []

        # Build and execute query
        cols_sql = ', '.join([f'"{c}"' for c in selected_columns])
        sql = f'SELECT {cols_sql} FROM "{table_name}"'

        # Handle random ordering
        if use_random:
            if random_seed is not None:
                # Seed specified: fetch all then use Python shuffle for reproducibility
                pass  # Don't add ORDER BY RANDOM() - will shuffle in Python
            else:
                # No seed: use SQL RANDOM() for efficiency
                sql += ' ORDER BY RANDOM()'

        if limit_clause and not (use_random and random_seed is not None):
            # Apply LIMIT in SQL (except when using seed - need to shuffle first)
            sql += f' LIMIT {limit_clause}'

        try:
            result = self.db.execute(text(sql))
            rows = result.fetchall()
        except Exception as e:
            logger.error(f"Failed to load dataset {dataset_id}: {e}")
            return []

        # Apply Python-level random with seed if specified (for reproducibility)
        if use_random and random_seed is not None:
            rand_module.seed(random_seed)
            rows = list(rows)
            rand_module.shuffle(rows)
            if limit_clause:
                rows = rows[:limit_clause]

        # Return data in appropriate format
        if single_column:
            # Return list of values from single column
            return [row[0] if row[0] is not None else "" for row in rows]
        else:
            # Return list of dicts
            return [dict(zip(selected_columns, row)) for row in rows]

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
        # For first step (step_order=0), use initial params
        if step.step_order == 0:
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

    def _evaluate_with_new_parser(
        self,
        formula: str,
        step_context: Dict[str, Dict[str, Any]]
    ) -> Any:
        """Evaluate a formula using the new Interpreter pattern parser.

        This method bridges the new parser to the existing function implementations,
        providing proper support for nested functions like calc(length(x) + 10).

        Args:
            formula: Formula string like "upper(trim({{step.text}}))"
            step_context: Context with step outputs

        Returns:
            Evaluated result
        """
        # Create function handler that calls existing implementations
        def function_handler(func_name: str, args: List[Any]) -> Any:
            """Adapter to use existing _evaluate_formula implementations."""
            # For simple functions, use built-in implementations
            if func_name == 'upper':
                return str(args[0]).upper() if args else ""
            if func_name == 'lower':
                return str(args[0]).lower() if args else ""
            if func_name == 'trim':
                return str(args[0]).strip() if args else ""
            if func_name == 'lstrip':
                return str(args[0]).lstrip() if args else ""
            if func_name == 'rstrip':
                return str(args[0]).rstrip() if args else ""
            if func_name in ('length', 'len'):
                return len(str(args[0])) if args else 0
            if func_name == 'capitalize':
                return str(args[0]).capitalize() if args else ""
            if func_name == 'title':
                return str(args[0]).title() if args else ""
            if func_name == 'reverse':
                return str(args[0])[::-1] if args else ""
            if func_name in ('slice', 'substr', 'substring'):
                if len(args) >= 2:
                    text = str(args[0])
                    start = int(args[1])
                    end = int(args[2]) if len(args) >= 3 else None
                    return text[start:end]
                return str(args[0]) if args else ""
            if func_name == 'left':
                if len(args) >= 2:
                    return str(args[0])[:int(args[1])]
                return str(args[0]) if args else ""
            if func_name == 'right':
                if len(args) >= 2:
                    n = int(args[1])
                    return str(args[0])[-n:] if n > 0 else ""
                return str(args[0]) if args else ""
            if func_name == 'repeat':
                if len(args) >= 2:
                    return str(args[0]) * max(0, min(int(args[1]), 1000))
                return str(args[0]) if args else ""
            if func_name == 'replace':
                if len(args) >= 3:
                    return str(args[0]).replace(str(args[1]), str(args[2]))
                return str(args[0]) if args else ""
            if func_name == 'concat':
                return "".join(str(arg) for arg in args)
            if func_name == 'split':
                if len(args) >= 2:
                    delimiter = str(args[1]) or ","
                    return json.dumps(str(args[0]).split(delimiter), ensure_ascii=False)
                return "[]"
            if func_name == 'join':
                if len(args) >= 2:
                    items = args[0]
                    delimiter = str(args[1])
                    if isinstance(items, str):
                        try:
                            items = json.loads(items)
                        except json.JSONDecodeError:
                            items = [items]
                    if isinstance(items, list):
                        return delimiter.join(str(item) for item in items)
                return str(args[0]) if args else ""
            if func_name in ('default', 'ifempty'):
                if len(args) >= 2:
                    value = str(args[0]).strip() if args[0] else ""
                    return value if value else str(args[1])
                return str(args[0]) if args else ""
            if func_name == 'contains':
                if len(args) >= 2:
                    return "true" if str(args[1]) in str(args[0]) else "false"
                return "false"
            if func_name == 'startswith':
                if len(args) >= 2:
                    return "true" if str(args[0]).startswith(str(args[1])) else "false"
                return "false"
            if func_name == 'endswith':
                if len(args) >= 2:
                    return "true" if str(args[0]).endswith(str(args[1])) else "false"
                return "false"
            if func_name == 'count':
                if len(args) >= 2:
                    return str(args[0]).count(str(args[1]))
                return 0
            if func_name == 'sum':
                return sum(float(arg) for arg in args)
            if func_name == 'calc':
                # calc receives already-evaluated arguments from nested functions
                # Just return the first argument (which should be a number after evaluation)
                if args:
                    val = args[0]
                    if isinstance(val, (int, float)):
                        return val
                    # If it's a string, try to convert
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        return 0
                return 0
            if func_name == 'shuffle':
                if args:
                    input_val = args[0]

                    # Handle list input (from nested function like split())
                    if isinstance(input_val, list):
                        shuffled = list(input_val)
                        random.shuffle(shuffled)
                        return json.dumps(shuffled, ensure_ascii=False)

                    text = str(input_val)

                    # Handle delimiter-based shuffling (2 arguments)
                    if len(args) >= 2:
                        delimiter = str(args[1])
                        if delimiter:
                            parts = text.split(delimiter)
                            random.shuffle(parts)
                            return delimiter.join(parts)

                    # Try to parse as JSON array first
                    try:
                        items = json.loads(text)
                        if isinstance(items, list):
                            random.shuffle(items)
                            return json.dumps(items, ensure_ascii=False)
                    except json.JSONDecodeError:
                        pass

                    # Fallback: shuffle characters
                    chars = list(text)
                    random.shuffle(chars)
                    return "".join(chars)
                return ""
            if func_name == 'debug':
                debug_output = " | ".join(str(arg) for arg in args)
                logger.info(f"[DEBUG] {debug_output}")
                return debug_output
            if func_name == 'now':
                fmt = str(args[0]) if args else "%Y-%m-%d %H:%M:%S"
                return datetime.now().strftime(fmt)
            if func_name == 'today':
                fmt = str(args[0]) if args else "%Y-%m-%d"
                return datetime.now().strftime(fmt)
            if func_name == 'time':
                fmt = str(args[0]) if args else "%H:%M:%S"
                return datetime.now().strftime(fmt)
            if func_name == 'json_parse':
                if args:
                    try:
                        return json.loads(str(args[0]))
                    except json.JSONDecodeError:
                        return args[0]
                return ""
            if func_name == 'format_choices':
                if args:
                    choices = args[0]
                    if isinstance(choices, str):
                        try:
                            choices = json.loads(choices)
                        except json.JSONDecodeError:
                            return str(choices)
                    if isinstance(choices, dict):
                        return "\n".join(f"{k}: {v}" for k, v in choices.items())
                return ""
            if func_name == 'array_push':
                if len(args) >= 2:
                    arr = args[0]
                    if isinstance(arr, str):
                        try:
                            arr = json.loads(arr)
                        except json.JSONDecodeError:
                            arr = [] if not arr else [arr]
                    if not isinstance(arr, list):
                        arr = [arr] if arr else []
                    arr.append(args[1])
                    return json.dumps(arr, ensure_ascii=False)
                return "[]"

            # For complex functions, fall back to old implementation
            # Build args_str and call _evaluate_formula
            args_str = ", ".join(json.dumps(arg, ensure_ascii=False) if isinstance(arg, (dict, list)) else str(arg) for arg in args)
            return self._evaluate_formula(func_name, args_str, step_context)

        # Create parser and evaluate
        parser = FormulaParser(function_handler)
        return parser.evaluate(formula, step_context)

    def _substitute_step_refs(
        self,
        template: str,
        step_context: Dict[str, Dict[str, Any]]
    ) -> str:
        """Substitute {{step_name.field}} references and evaluate formulas.

        Uses the new Interpreter pattern parser for proper nested function support.

        Args:
            template: Template string with {{step.field}} references or formulas
            step_context: Context with step outputs

        Returns:
            String with substituted values and evaluated formulas
        """
        # Try the new parser first for formula expressions
        stripped = template.strip()
        if self.FORMULA_PATTERN.match(stripped):
            try:
                result = self._evaluate_with_new_parser(stripped, step_context)
                return str(result)
            except (TokenizerError, ParseError, EvaluationError) as e:
                # Log the error and fall back to old parser
                logger.warning(f"New parser failed, falling back: {e}")
                # Fall through to old implementation
            except Exception as e:
                logger.warning(f"Unexpected parser error: {e}")
                # Fall through to old implementation

        # Fallback: Old implementation for non-formula templates or parser failures
        formula_match = self.FORMULA_PATTERN.match(stripped)
        if formula_match:
            func_name = formula_match.group(1).lower()
            args_str = formula_match.group(2)
            return str(self._evaluate_formula(func_name, args_str, step_context))

        # Otherwise, do normal variable substitution with nested access support
        def replacer(match):
            full_path = match.group(1)  # "vars.item.text" or "step.field"
            parts = full_path.split('.')

            # Handle "step.STEPNAME.field" format - skip the "step" prefix
            # This allows {{step.ask.answer}} to resolve to step_context["ask"]["answer"]
            if parts[0] == "step" and len(parts) >= 3:
                parts = parts[1:]  # Remove "step" prefix

            # First part must be in step_context
            if parts[0] not in step_context:
                return match.group(0)  # Keep original if not found

            # Start with the top-level context value
            value = step_context[parts[0]]

            # Navigate through nested fields
            for part in parts[1:]:
                if isinstance(value, dict):
                    value = value.get(part, "")
                elif isinstance(value, str):
                    # Try to parse as JSON for nested access
                    try:
                        parsed = json.loads(value)
                        if isinstance(parsed, dict):
                            value = parsed.get(part, "")
                        else:
                            # Can't access field on non-dict
                            return match.group(0)
                    except (json.JSONDecodeError, TypeError):
                        return match.group(0)
                else:
                    # Can't navigate further
                    return match.group(0)

                if value is None:
                    return ""

            # Convert result to string
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return str(value) if value is not None else ""

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
                    # Handle empty delimiter (common when user writes split(text, ,) without quotes)
                    if not delimiter:
                        delimiter = ","  # Default to comma if delimiter is empty
                    result = text.split(delimiter)
                    return json.dumps(result, ensure_ascii=False)
                elif len(args) == 1:
                    # Only 1 arg provided - use comma as default delimiter
                    # This handles cases like split({{vars.list}}, ,) where the comma
                    # delimiter was consumed by the argument parser
                    text = str(args[0])
                    if "," in text:
                        result = text.split(",")
                        return json.dumps(result, ensure_ascii=False)
                    return json.dumps([text], ensure_ascii=False)
                return "[]"

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

            if func_name == "array_push":
                if len(args) >= 2:
                    arr = args[0]
                    new_item = args[1]
                    # Handle JSON array string or list
                    if isinstance(arr, str):
                        try:
                            arr = json.loads(arr)
                        except json.JSONDecodeError:
                            arr = [] if not arr else [arr]
                    if not isinstance(arr, list):
                        arr = [arr] if arr else []
                    arr.append(new_item)
                    return json.dumps(arr, ensure_ascii=False)
                return "[]"

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
                        # Try to parse as JSON array first
                        try:
                            items = json.loads(text)
                            if isinstance(items, list):
                                random.shuffle(items)
                                return json.dumps(items, ensure_ascii=False)
                        except json.JSONDecodeError:
                            pass
                        # Fallback: shuffle characters
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

            # Date and time functions
            if func_name == "now":
                # Current datetime with optional format
                fmt = str(args[0]) if args else "%Y-%m-%d %H:%M:%S"
                return datetime.now().strftime(fmt)

            if func_name == "today":
                # Today's date with optional format
                fmt = str(args[0]) if args else "%Y-%m-%d"
                return datetime.now().strftime(fmt)

            if func_name == "time":
                # Current time with optional format
                fmt = str(args[0]) if args else "%H:%M:%S"
                return datetime.now().strftime(fmt)

            if func_name == "getprompt":
                # Get prompt content: getprompt(prompt_name, [project_name], [revision])
                return self._get_prompt_or_parser(args, step_context, get_parser=False)

            if func_name == "getparser":
                # Get parser config: getparser(prompt_name, [project_name], [revision])
                return self._get_prompt_or_parser(args, step_context, get_parser=True)

            # JSON parse function - parses JSON string for nested field access
            if func_name == "json_parse":
                try:
                    json_str = str(args[0]) if args else ""
                    parsed = json.loads(json_str)
                    if isinstance(parsed, (dict, list)):
                        return json.dumps(parsed, ensure_ascii=False)
                    return str(parsed)
                except (json.JSONDecodeError, TypeError):
                    # Return original if not valid JSON
                    return args[0] if args else ""

            # JSON zip function - zip multiple arrays from JSON object into list of dicts
            if func_name == "json_zip":
                if len(args) < 2:
                    logger.warning("json_zip requires at least 2 arguments: json_string and key names")
                    return "[]"

                json_str = str(args[0])
                keys = [str(k).strip() for k in args[1:]]

                try:
                    data = json.loads(json_str)
                    if not isinstance(data, dict):
                        logger.warning("json_zip: First argument must be a JSON object")
                        return "[]"

                    # Extract arrays for each key
                    arrays = []
                    for key in keys:
                        val = data.get(key, [])
                        if not isinstance(val, list):
                            val = [val]  # Wrap non-list values
                        arrays.append(val)

                    # Find minimum length (zip to shortest)
                    if not arrays:
                        return "[]"
                    min_len = min(len(arr) for arr in arrays)

                    # Build result list of dicts
                    result = []
                    for i in range(min_len):
                        row = {keys[j]: arrays[j][i] for j in range(len(keys))}
                        result.append(row)

                    return json.dumps(result, ensure_ascii=False)

                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"json_zip: Failed to parse JSON: {e}")
                    return "[]"

            # Format choices JSON - {"text": [...], "label": [...]} -> "A:text1\nB:text2\n..."
            if func_name == "format_choices":
                json_str = str(args[0]) if args else ""
                try:
                    data = json.loads(json_str)
                    if not isinstance(data, dict):
                        logger.warning("format_choices: Input must be a JSON object")
                        return json_str  # Return as-is if not valid

                    labels = data.get("label", [])
                    texts = data.get("text", [])

                    if not labels or not texts:
                        logger.warning("format_choices: Missing 'label' or 'text' array")
                        return json_str

                    # Build formatted choices
                    lines = []
                    for label, text in zip(labels, texts):
                        lines.append(f"{label}:{text}")

                    return "\n".join(lines)

                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"format_choices: Failed to parse JSON: {e}")
                    return json_str  # Return original if parsing fails

            # Dataset filter - filter rows by condition (extended version)
            # Supports: AND, OR, <, >, <=, >=, LIKE, IS NULL, IS EMPTY
            if func_name == "dataset_filter":
                if len(args) < 2:
                    logger.warning("dataset_filter: Requires 2 arguments (dataset_ref, condition)")
                    return "[]"

                dataset_ref = str(args[0]).strip()
                condition = str(args[1]).strip().strip('"').strip("'")

                try:
                    # Load dataset rows
                    rows = self._load_dataset_for_foreach(dataset_ref)
                    if not rows:
                        return "[]"

                    # Filter rows using extended condition evaluator
                    filtered = []
                    for row in rows:
                        if self._evaluate_filter_condition(condition, row):
                            filtered.append(row)

                    return json.dumps(filtered, ensure_ascii=False)

                except Exception as e:
                    logger.warning(f"dataset_filter: Error - {e}")
                    return "[]"

            # Dataset join - join column values with separator
            if func_name == "dataset_join":
                if len(args) < 2:
                    logger.warning("dataset_join: Requires at least 2 arguments (source, column)")
                    return ""

                source = str(args[0]).strip()
                column = str(args[1]).strip().strip('"').strip("'")
                separator = str(args[2]).strip().strip('"').strip("'") if len(args) > 2 else "\n"

                # Handle escape sequences
                separator = separator.replace("\\n", "\n").replace("\\t", "\t")

                try:
                    # Determine if source is dataset reference or JSON array
                    if source.startswith("dataset:"):
                        rows = self._load_dataset_for_foreach(source)
                    else:
                        # Try to parse as JSON array (from dataset_filter result)
                        rows = json.loads(source)

                    if not rows or not isinstance(rows, list):
                        return ""

                    # Extract column values
                    values = []
                    for row in rows:
                        if isinstance(row, dict):
                            val = row.get(column, "")
                            if val is not None:
                                values.append(str(val))

                    return separator.join(values)

                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"dataset_join: Error - {e}")
                    return ""

            # Unknown function - return empty string
            logger.warning(f"Unknown formula function: {func_name}")
            return ""

        except Exception as e:
            logger.error(f"Error evaluating formula {func_name}({args_str}): {e}")
            return ""

    def _get_prompt_or_parser(
        self,
        args: List[Any],
        step_context: Dict[str, Dict[str, Any]],
        get_parser: bool = False
    ) -> str:
        """Get prompt content or parser config from database.

        Args:
            args: [prompt_name, project_name (optional), revision (optional)]
                  - prompt_name: Name of the prompt to retrieve
                  - project_name: Project name or "CURRENT" (default: CURRENT = workflow's project)
                  - revision: Revision number or "CURRENT" (default: CURRENT = latest revision)
            step_context: Context with step outputs (includes _meta with workflow info)
            get_parser: If True, return parser_config; if False, return prompt_template

        Returns:
            Prompt template or parser config string
        """
        if not args:
            logger.warning("getprompt/getparser: No prompt name provided")
            return ""

        prompt_name = str(args[0]).strip()
        project_arg = str(args[1]).strip() if len(args) > 1 else "CURRENT"
        revision_arg = str(args[2]).strip() if len(args) > 2 else "CURRENT"

        # Get workflow metadata from context
        meta = step_context.get("_meta", {})
        workflow_project_id = meta.get("project_id")

        logger.info(f"[getprompt/getparser] prompt_name={prompt_name}, project_arg={project_arg}, revision_arg={revision_arg}")

        try:
            # Resolve project
            target_project_id = None
            if project_arg.upper() == "CURRENT":
                # Use workflow's project
                target_project_id = workflow_project_id
                if not target_project_id:
                    logger.warning("getprompt/getparser: CURRENT project requested but workflow has no project")
                    return ""
            else:
                # Look up project by name
                project = self.db.query(Project).filter(Project.name == project_arg).first()
                if not project:
                    logger.warning(f"getprompt/getparser: Project '{project_arg}' not found")
                    return ""
                target_project_id = project.id

            # Find prompt by name within the project
            prompt = self.db.query(Prompt).filter(
                Prompt.project_id == target_project_id,
                Prompt.name == prompt_name,
                Prompt.is_deleted == 0
            ).first()

            if not prompt:
                logger.warning(f"getprompt/getparser: Prompt '{prompt_name}' not found in project {target_project_id}")
                return ""

            # Resolve revision
            prompt_revision = None
            if revision_arg.upper() == "CURRENT":
                # Get latest revision
                prompt_revision = self.db.query(PromptRevision).filter(
                    PromptRevision.prompt_id == prompt.id
                ).order_by(PromptRevision.revision.desc()).first()
            else:
                # Get specific revision
                try:
                    revision_num = int(revision_arg)
                    prompt_revision = self.db.query(PromptRevision).filter(
                        PromptRevision.prompt_id == prompt.id,
                        PromptRevision.revision == revision_num
                    ).first()
                except ValueError:
                    logger.warning(f"getprompt/getparser: Invalid revision number '{revision_arg}'")
                    return ""

            if not prompt_revision:
                logger.warning(f"getprompt/getparser: No revision found for prompt '{prompt_name}'")
                return ""

            # Return the requested content
            if get_parser:
                result = prompt_revision.parser_config or ""
                logger.info(f"[getparser] Retrieved parser config for '{prompt_name}' (rev {prompt_revision.revision})")
            else:
                result = prompt_revision.prompt_template or ""
                logger.info(f"[getprompt] Retrieved prompt template for '{prompt_name}' (rev {prompt_revision.revision})")

            return result

        except Exception as e:
            logger.error(f"Error in getprompt/getparser: {e}")
            return ""

    def _parse_function_args(
        self,
        args_str: str,
        step_context: Dict[str, Dict[str, Any]]
    ) -> List[Any]:
        """Parse function arguments with proper handling of commas, braces, parentheses, and quotes.

        Args:
            args_str: Comma-separated arguments string
            step_context: Context with step outputs

        Returns:
            List of resolved argument values
        """
        args = []
        current_arg = ""
        brace_depth = 0
        paren_depth = 0
        bracket_depth = 0  # Track square brackets for JSON arrays
        in_double_quote = False
        in_single_quote = False

        for char in args_str:
            # Track quotes (only toggle if not inside the other quote type)
            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                current_arg += char
            elif char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                current_arg += char
            elif char == '{' and not in_double_quote and not in_single_quote:
                brace_depth += 1
                current_arg += char
            elif char == '}' and not in_double_quote and not in_single_quote:
                brace_depth -= 1
                current_arg += char
            elif char == '(' and not in_double_quote and not in_single_quote:
                paren_depth += 1
                current_arg += char
            elif char == ')' and not in_double_quote and not in_single_quote:
                paren_depth -= 1
                current_arg += char
            elif char == '[' and not in_double_quote and not in_single_quote:
                bracket_depth += 1
                current_arg += char
            elif char == ']' and not in_double_quote and not in_single_quote:
                bracket_depth -= 1
                current_arg += char
            elif char == ',' and brace_depth == 0 and paren_depth == 0 and bracket_depth == 0 and not in_double_quote and not in_single_quote:
                args.append(current_arg.strip())
                current_arg = ""
            else:
                current_arg += char

        if current_arg.strip():
            args.append(current_arg.strip())

        # Resolve variable references and nested function calls in each argument
        resolved_args = []
        for arg in args:
            # First check if the ORIGINAL argument (before substitution) is a function call
            formula_match = self.FORMULA_PATTERN.match(arg.strip())
            if formula_match:
                # It's a nested function - evaluate using the full _substitute_step_refs
                # This ensures proper argument parsing before variable substitution
                resolved = self._substitute_step_refs(arg, step_context)
            else:
                # Not a function - substitute variable references
                resolved = self._substitute_single_ref(arg, step_context)
                # Strip quotes from string literals
                resolved = self._strip_string_quotes(resolved)

            resolved_args.append(resolved)

        return resolved_args

    def _strip_string_quotes(self, value: str) -> str:
        """Strip surrounding quotes from a string literal.

        Handles both single and double quotes.
        E.g., '"hello"' -> 'hello', "'world'" -> 'world'
        Does NOT strip whitespace from the content.
        """
        # Only check the stripped version for quote detection,
        # but if stripping quotes, strip the original value's quotes only
        stripped = value.strip()
        if len(stripped) >= 2:
            if (stripped.startswith('"') and stripped.endswith('"')):
                # Return content between quotes (preserving internal whitespace)
                return stripped[1:-1]
            elif (stripped.startswith("'") and stripped.endswith("'")):
                return stripped[1:-1]
        return value

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
            full_path = match.group(1)  # "vars.incorrect" or "step.field.nested"
            parts = full_path.split('.')

            # Handle "step.STEPNAME.field" format - skip the "step" prefix
            # This allows {{step.ask.answer}} to resolve to step_context["ask"]["answer"]
            if parts[0] == "step" and len(parts) >= 3:
                parts = parts[1:]  # Remove "step" prefix

            # First part must be in step_context
            if parts[0] not in step_context:
                return match.group(0)  # Keep original if not found

            # Start with the top-level context value
            value = step_context[parts[0]]

            # Navigate through nested fields
            for part in parts[1:]:
                if isinstance(value, dict):
                    value = value.get(part, "")
                elif isinstance(value, str):
                    # Try to parse as JSON for nested access
                    try:
                        parsed = json.loads(value)
                        if isinstance(parsed, dict):
                            value = parsed.get(part, "")
                        else:
                            return match.group(0)
                    except (json.JSONDecodeError, TypeError):
                        return match.group(0)
                else:
                    return match.group(0)

                if value is None:
                    return ""

            # Convert result to string
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return str(value) if value is not None else ""

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
        # Note: parsed_fields is stored both under "parsed" key (for {{step.parsed.FIELD}} syntax)
        # and spread at top level (for {{step.FIELD}} syntax) for backward compatibility
        parsed_fields = parsed.get("fields", {})
        result = {
            "raw": job_item.raw_response,
            "_is_parsed": parsed.get("parsed", False),  # Metadata renamed to avoid conflict
            "parsed": parsed_fields,                     # Parser output as dict for nested access
            **parsed_fields                              # Also spread for direct access
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
        # Skip special keys: "input", "vars", and any key starting with "_" (like "_meta", "_csv_outputs")
        step_names = [name for name in step_context.keys()
                      if name != "input" and name != "vars" and not name.startswith("_")]
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

            # Only accept string csv_output (not dicts from other structures)
            if csv_output and isinstance(csv_output, str):
                last_csv_output = csv_output
                last_csv_header = csv_header if isinstance(csv_header, str) else None
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

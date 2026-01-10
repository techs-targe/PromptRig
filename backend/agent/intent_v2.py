"""Intent Extraction Layer v2 - LLM-based + Hierarchical Intent Classification.

This module provides a hybrid intent extraction system:
1. Fast rule-based pre-filtering for security (blocks obvious threats)
2. LLM-based classification for flexible intent understanding
3. Hierarchical intent structure (Domain + Action) for precise permission mapping
4. Rule-based fallback when LLM is unavailable

Design Principles:
- Domain: What resource/area the user wants to interact with
- Action: What operation the user wants to perform
- Clear mapping to permission levels (READ_ONLY, WRITE_SAFE, DESTRUCTIVE)
- Language-agnostic: Works with Japanese, English, and mixed input
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from backend.utils import get_app_name

logger = logging.getLogger(__name__)


# =============================================================================
# Hierarchical Intent Structure
# =============================================================================

class Domain(str, Enum):
    """Domain of user intent - what resource/area they want to interact with."""
    PROJECT = "project"          # Project management
    PROMPT = "prompt"            # Prompt management
    WORKFLOW = "workflow"        # Workflow management
    JOB = "job"                  # Job monitoring/management
    TEMPLATE = "template"        # Template analysis
    SETTINGS = "settings"        # System settings
    MODEL = "model"              # LLM model selection
    DATASET = "dataset"          # Dataset management (local + Huggingface)
    HELP = "help"                # Help/usage information
    OUT_OF_SCOPE = "out_of_scope"  # Not related to system


class Action(str, Enum):
    """Action type - what operation the user wants to perform."""
    LIST = "list"                # List/enumerate resources
    GET = "get"                  # Get details of a specific resource
    CREATE = "create"            # Create a new resource
    UPDATE = "update"            # Update an existing resource
    DELETE = "delete"            # Delete a resource
    EXECUTE = "execute"          # Execute a prompt/workflow
    ANALYZE = "analyze"          # Analyze template
    CANCEL = "cancel"            # Cancel a job
    EXPORT = "export"            # Export data (CSV, download link)
    SWITCH = "switch"            # Switch/select (model, settings)
    SHOW = "show"                # Show help/info
    CONFIRM = "confirm"          # Confirm previous action (yes/no)
    FOLLOWUP = "followup"        # Follow-up request referring to previous context
    IMPORT = "import"            # Import data (dataset, Huggingface)
    SEARCH = "search"            # Search for resources
    PREVIEW = "preview"          # Preview data
    UNKNOWN = "unknown"          # Cannot determine action


class PermissionLevel(str, Enum):
    """Permission level for the intent."""
    READ_ONLY = "read_only"      # Safe, no side effects
    WRITE_SAFE = "write_safe"    # Creates/updates, but reversible
    DESTRUCTIVE = "destructive"  # Deletes or has major side effects
    BLOCKED = "blocked"          # Security: should be rejected


# Permission mapping: (Domain, Action) -> PermissionLevel
# Policy: Only DELETE requires confirmation. CREATE, UPDATE, EXECUTE, CANCEL are all READ_ONLY.
PERMISSION_MAP: Dict[Tuple[Domain, Action], PermissionLevel] = {
    # Project operations
    (Domain.PROJECT, Action.LIST): PermissionLevel.READ_ONLY,
    (Domain.PROJECT, Action.GET): PermissionLevel.READ_ONLY,
    (Domain.PROJECT, Action.CREATE): PermissionLevel.READ_ONLY,  # 確認不要
    (Domain.PROJECT, Action.UPDATE): PermissionLevel.READ_ONLY,  # 確認不要
    (Domain.PROJECT, Action.DELETE): PermissionLevel.DESTRUCTIVE,  # 削除のみ確認必要

    # Prompt operations
    (Domain.PROMPT, Action.LIST): PermissionLevel.READ_ONLY,
    (Domain.PROMPT, Action.GET): PermissionLevel.READ_ONLY,
    (Domain.PROMPT, Action.CREATE): PermissionLevel.READ_ONLY,  # 確認不要
    (Domain.PROMPT, Action.UPDATE): PermissionLevel.READ_ONLY,  # 確認不要
    (Domain.PROMPT, Action.DELETE): PermissionLevel.DESTRUCTIVE,  # 削除のみ確認必要
    (Domain.PROMPT, Action.EXECUTE): PermissionLevel.READ_ONLY,  # 確認不要

    # Workflow operations
    (Domain.WORKFLOW, Action.LIST): PermissionLevel.READ_ONLY,
    (Domain.WORKFLOW, Action.GET): PermissionLevel.READ_ONLY,
    (Domain.WORKFLOW, Action.CREATE): PermissionLevel.READ_ONLY,  # 確認不要
    (Domain.WORKFLOW, Action.UPDATE): PermissionLevel.READ_ONLY,  # 確認不要
    (Domain.WORKFLOW, Action.DELETE): PermissionLevel.DESTRUCTIVE,  # 削除のみ確認必要
    (Domain.WORKFLOW, Action.EXECUTE): PermissionLevel.READ_ONLY,  # 確認不要

    # Job operations
    (Domain.JOB, Action.LIST): PermissionLevel.READ_ONLY,
    (Domain.JOB, Action.GET): PermissionLevel.READ_ONLY,
    (Domain.JOB, Action.EXPORT): PermissionLevel.READ_ONLY,
    (Domain.JOB, Action.CANCEL): PermissionLevel.READ_ONLY,  # 確認不要
    (Domain.JOB, Action.FOLLOWUP): PermissionLevel.READ_ONLY,

    # Template operations
    (Domain.TEMPLATE, Action.ANALYZE): PermissionLevel.READ_ONLY,
    (Domain.TEMPLATE, Action.GET): PermissionLevel.READ_ONLY,

    # Settings operations
    (Domain.SETTINGS, Action.LIST): PermissionLevel.READ_ONLY,
    (Domain.SETTINGS, Action.GET): PermissionLevel.READ_ONLY,
    (Domain.SETTINGS, Action.UPDATE): PermissionLevel.READ_ONLY,  # 確認不要
    (Domain.SETTINGS, Action.SWITCH): PermissionLevel.READ_ONLY,  # 確認不要

    # Model operations
    (Domain.MODEL, Action.LIST): PermissionLevel.READ_ONLY,
    (Domain.MODEL, Action.GET): PermissionLevel.READ_ONLY,
    (Domain.MODEL, Action.SWITCH): PermissionLevel.READ_ONLY,  # 確認不要

    # Help
    (Domain.HELP, Action.SHOW): PermissionLevel.READ_ONLY,

    # Dataset operations
    (Domain.DATASET, Action.LIST): PermissionLevel.READ_ONLY,
    (Domain.DATASET, Action.GET): PermissionLevel.READ_ONLY,
    (Domain.DATASET, Action.SEARCH): PermissionLevel.READ_ONLY,
    (Domain.DATASET, Action.PREVIEW): PermissionLevel.READ_ONLY,
    (Domain.DATASET, Action.IMPORT): PermissionLevel.READ_ONLY,  # 確認不要
    (Domain.DATASET, Action.DELETE): PermissionLevel.DESTRUCTIVE,  # 削除のみ確認必要

    # Out of scope
    (Domain.OUT_OF_SCOPE, Action.UNKNOWN): PermissionLevel.BLOCKED,

    # Confirmation (continue previous action)
    (Domain.HELP, Action.CONFIRM): PermissionLevel.READ_ONLY,  # 確認不要
}


def get_permission_level(domain: Domain, action: Action) -> PermissionLevel:
    """Get permission level for a domain-action pair.

    Policy: Only DELETE requires confirmation.
    CREATE, UPDATE, EXECUTE, CANCEL are all READ_ONLY (no confirmation needed).
    """
    key = (domain, action)
    if key in PERMISSION_MAP:
        return PERMISSION_MAP[key]

    # Default behavior by action type
    # Only DELETE is DESTRUCTIVE (confirmation required)
    if action == Action.DELETE:
        return PermissionLevel.DESTRUCTIVE
    elif action == Action.UNKNOWN:
        return PermissionLevel.BLOCKED
    else:
        # Everything else is READ_ONLY (no confirmation needed)
        return PermissionLevel.READ_ONLY


# Tool mapping: (Domain, Action) -> list of tool names
TOOL_MAP: Dict[Tuple[Domain, Action], List[str]] = {
    # Project
    (Domain.PROJECT, Action.LIST): ["list_projects"],
    (Domain.PROJECT, Action.GET): ["get_project"],
    (Domain.PROJECT, Action.CREATE): ["create_project"],
    (Domain.PROJECT, Action.UPDATE): ["update_project"],
    (Domain.PROJECT, Action.DELETE): ["delete_project"],

    # Prompt
    (Domain.PROMPT, Action.LIST): ["list_prompts"],
    (Domain.PROMPT, Action.GET): ["get_prompt"],
    (Domain.PROMPT, Action.CREATE): ["create_prompt"],
    (Domain.PROMPT, Action.UPDATE): ["update_prompt"],
    (Domain.PROMPT, Action.DELETE): ["delete_prompt"],
    (Domain.PROMPT, Action.EXECUTE): ["execute_prompt", "execute_template"],

    # Workflow
    (Domain.WORKFLOW, Action.LIST): ["list_workflows"],
    (Domain.WORKFLOW, Action.GET): ["get_workflow"],
    (Domain.WORKFLOW, Action.CREATE): ["create_workflow"],
    (Domain.WORKFLOW, Action.UPDATE): ["update_workflow"],
    (Domain.WORKFLOW, Action.DELETE): ["delete_workflow"],
    (Domain.WORKFLOW, Action.EXECUTE): ["execute_workflow"],

    # Job
    (Domain.JOB, Action.LIST): ["list_recent_jobs"],
    (Domain.JOB, Action.GET): ["get_job_status"],
    (Domain.JOB, Action.EXPORT): ["export_job_csv"],
    (Domain.JOB, Action.CANCEL): ["cancel_job"],
    (Domain.JOB, Action.FOLLOWUP): ["export_job_csv", "get_job_status"],

    # Template
    (Domain.TEMPLATE, Action.ANALYZE): ["analyze_template"],
    (Domain.TEMPLATE, Action.GET): ["analyze_template"],

    # Settings
    (Domain.SETTINGS, Action.LIST): ["get_system_settings"],
    (Domain.SETTINGS, Action.GET): ["get_system_settings"],
    (Domain.SETTINGS, Action.UPDATE): ["update_system_setting"],
    (Domain.SETTINGS, Action.SWITCH): ["update_system_setting"],

    # Model
    (Domain.MODEL, Action.LIST): ["list_models"],
    (Domain.MODEL, Action.GET): ["get_active_model"],
    (Domain.MODEL, Action.SWITCH): ["set_active_model"],

    # Dataset (local + Huggingface)
    (Domain.DATASET, Action.LIST): ["list_datasets"],
    (Domain.DATASET, Action.GET): ["get_dataset"],
    (Domain.DATASET, Action.SEARCH): ["search_datasets", "search_huggingface_datasets"],
    (Domain.DATASET, Action.PREVIEW): ["preview_dataset_rows", "preview_huggingface_dataset"],
    (Domain.DATASET, Action.IMPORT): ["import_dataset", "import_huggingface_dataset"],
    (Domain.DATASET, Action.DELETE): ["delete_dataset"],

    # Help - エージェントが「helpを参照して」指示に対応できるようにする
    (Domain.HELP, Action.SHOW): ["help"],
}


def get_suggested_tools(domain: Domain, action: Action) -> List[str]:
    """Get suggested tools for a domain-action pair."""
    key = (domain, action)
    return TOOL_MAP.get(key, [])


# =============================================================================
# Intent Data Class
# =============================================================================

@dataclass
class IntentV2:
    """Hierarchical intent extracted from user message."""
    domain: Domain
    action: Action
    confidence: float  # 0.0 - 1.0
    target_id: Optional[int] = None  # Specific resource ID if mentioned
    target_name: Optional[str] = None  # Resource name if mentioned
    parameters: Dict[str, Any] = field(default_factory=dict)  # Additional params
    suggested_tools: List[str] = field(default_factory=list)
    permission_level: PermissionLevel = PermissionLevel.READ_ONLY
    rejection_reason: Optional[str] = None
    classification_method: str = "unknown"  # "llm", "rule", "security"
    raw_llm_response: Optional[str] = None  # For debugging

    def __post_init__(self):
        """Auto-populate derived fields."""
        if not self.suggested_tools:
            self.suggested_tools = get_suggested_tools(self.domain, self.action)
        self.permission_level = get_permission_level(self.domain, self.action)

    def is_allowed(self) -> bool:
        """Check if this intent is allowed to proceed."""
        return self.permission_level != PermissionLevel.BLOCKED

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/debugging."""
        return {
            "domain": self.domain.value,
            "action": self.action.value,
            "confidence": self.confidence,
            "target_id": self.target_id,
            "target_name": self.target_name,
            "parameters": self.parameters,
            "suggested_tools": self.suggested_tools,
            "permission_level": self.permission_level.value,
            "classification_method": self.classification_method,
        }


# =============================================================================
# Security Pre-Filter (Rule-based, Fast)
# =============================================================================

class SecurityPreFilter:
    """Fast rule-based security filter that runs BEFORE LLM classification.

    This catches obvious security threats without incurring LLM latency/cost.
    """

    # Patterns that indicate security threats - BLOCK immediately
    SECURITY_PATTERNS = [
        # System prompt disclosure attempts
        (r"(?i)(システム|内部|隠し).*(プロンプト|指示|設定).*(見せ|教え|表示|出力|全文)", "disclosure"),
        (r"(?i)(show|tell|reveal|display|output|print).*(system|internal|hidden).*(prompt|instruction)", "disclosure"),
        (r"(?i)your.*(original|initial|system|internal)\s*(prompt|instruction)", "disclosure"),
        (r"(?i)(指示|instruction).*(そのまま|verbatim|全文|完全)", "disclosure"),
        (r"(?i)developer\s*message", "disclosure"),

        # Tool enumeration attempts
        (r"(?i)(全部|すべて|一覧|列挙).*(ツール|機能|API)\s*(名|name)", "enumeration"),
        (r"(?i)list\s+(all\s+)?(available\s+)?(tool|function|api)", "enumeration"),
        (r"(?i)what\s+tools?\s+(do\s+you\s+have|are\s+available)", "enumeration"),
        (r"(?i)internal\s*api", "enumeration"),

        # Indirect command injection attempts
        (r"(?i)(ログ|内容|結果|データ).*に(従って|基づいて).*(実行|キャンセル|削除)", "injection"),
        (r"(?i)follow.*instruction.*in.*(log|content|data|result)", "injection"),
        (r"(?i)execute.*command.*in.*(log|content|result)", "injection"),
    ]

    # Compiled patterns (lazy initialization)
    _compiled_patterns: Optional[List[Tuple[re.Pattern, str]]] = None

    @classmethod
    def _get_compiled_patterns(cls) -> List[Tuple[re.Pattern, str]]:
        """Get compiled regex patterns (lazy initialization)."""
        if cls._compiled_patterns is None:
            cls._compiled_patterns = [
                (re.compile(pattern), category)
                for pattern, category in cls.SECURITY_PATTERNS
            ]
        return cls._compiled_patterns

    @classmethod
    def check(cls, message: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """Check message for security threats.

        Args:
            message: User input message

        Returns:
            Tuple of (is_threat, threat_category, rejection_message)
        """
        for pattern, category in cls._get_compiled_patterns():
            if pattern.search(message):
                logger.warning(f"[Security] Blocked input, category: {category}")

                if category == "disclosure":
                    rejection = (
                        "申し訳ございませんが、内部指示やシステム設定の内容を開示することはできません。\n"
                        "このシステムでできることについては「ヘルプ」とお尋ねください。"
                    )
                elif category == "enumeration":
                    rejection = (
                        "内部のツール名やAPI名を列挙することはできません。\n"
                        "具体的な操作をご希望の場合は、何をしたいかお伝えください。"
                    )
                elif category == "injection":
                    rejection = (
                        "外部コンテンツ内の指示を実行することはできません。\n"
                        "具体的に何をされたいか、直接お伝えください。"
                    )
                else:
                    rejection = "この要求は処理できません。"

                return True, category, rejection

        return False, None, None


# =============================================================================
# LLM-based Intent Classifier
# =============================================================================

class LLMIntentClassifier:
    """LLM-based intent classifier using lightweight models.

    Uses Claude 3.5 Haiku or GPT-4o-mini for fast, flexible intent classification.
    """

    # Classification prompt template
    CLASSIFICATION_PROMPT = """あなたはユーザーの意図を分類するシステムです。

以下のユーザーメッセージを分析し、JSON形式で意図を返してください。

## 直近の会話履歴（文脈判断用）:
{conversation_history}

## 分類対象

**Domain (どのリソース/領域か):**
- project: プロジェクト管理
- prompt: プロンプト管理
- workflow: ワークフロー管理
- job: ジョブ監視・管理
- template: テンプレート分析
- settings: システム設定
- model: LLMモデル選択
- dataset: データセット管理（ローカル/Huggingface）
- help: ヘルプ・使い方
- out_of_scope: システムに関係ない質問 ★厳格に判定★

**Action (どんな操作か):**
- list: 一覧表示
- get: 詳細取得
- create: 新規作成
- update: 更新・編集
- delete: 削除
- execute: 実行（プロンプト/ワークフロー）
- analyze: 分析（テンプレート）
- cancel: キャンセル（ジョブ）
- export: CSV出力・ダウンロード・リンク取得
- switch: 切り替え（モデル/設定）
- show: 表示（ヘルプ）
- followup: 前の操作に関する追加リクエスト
- import: インポート（データセット、Huggingface）
- search: 検索（データセット、Huggingface）
- preview: プレビュー（データセット）
- unknown: 判定不能

## ユーザーメッセージ:
{message}

## ★★★ OUT_OF_SCOPE判定基準（最重要・厳格適用）★★★

以下は **必ず out_of_scope** として判定してください:

1. **プログラミング言語でのコード記述依頼**:
   - 「C#で〜書いて」「Pythonで〜作って」「JavaScriptで〜実装して」
   - 「HELLO WORLD」「FizzBuzz」「フィボナッチ」などの典型例
   - 「関数を書いて」「クラスを作って」「APIを実装して」

2. **一般的な質問・依頼**:
   - 天気、ニュース、株価の質問
   - 計算（1+1、sin、cos等）
   - 翻訳依頼
   - 歴史、地理、科学の質問
   - レシピ、健康、恋愛相談
   - 物語、詩、歌詞の創作

3. **システム機能と無関係な「なぜ」「どうして」質問**:
   - 一般的な理由の説明依頼
   - 哲学的・抽象的な質問

★このシステムの機能は以下のみ:
- プロジェクト/プロンプト/ワークフローの管理（一覧、作成、更新、削除、実行）
- ジョブの監視、CSV出力
- テンプレート分析
- システム設定、モデル切り替え
- データセット管理（一覧、検索、インポート、プレビュー、Huggingface連携）

上記以外の依頼は全て out_of_scope です。

## 出力形式 (JSON のみ):
```json
{{
  "domain": "...",
  "action": "...",
  "confidence": 0.0-1.0,
  "target_id": null または数値,
  "target_name": null または文字列,
  "reasoning": "判定理由（1文）"
}}
```

重要:
- JSONのみを出力してください。説明文は不要です。
- confidence は確信度（0.0-1.0）
- target_id は「ID 123」「プロンプト1」など数値が明示されている場合のみ
- 「CSVリンク」「CSVください」「ダウンロード」などはjob+exportに分類
- 短い依頼（「〜ください」「〜お願い」）も、内容に応じて適切なdomain/actionに分類
- helpは「使い方」「ヘルプ」「何ができる」など、本当にヘルプを求めている場合のみ

## 短いメッセージの文脈依存分類:
- 「修正してください」「更新して」「直して」などの短いメッセージは、会話履歴から対象を判断
- 会話履歴でworkflow/prompt/stepについて話していれば、そのドメインのupdate操作と解釈
- 会話履歴がない場合のみout_of_scopeを検討
- 直前の会話でエラーや問題が報告されていれば、その修正を意図していると判断
"""

    def __init__(self, model_name: str = "openai-gpt-4.1-nano"):
        """Initialize the classifier.

        Args:
            model_name: Model to use for classification.
                       Recommended: 'openai-gpt-4.1-nano' or 'azure-gpt-5-nano'
        """
        self.model_name = model_name
        self._client = None

    def _check_execution_pattern(self, message: str) -> Optional[IntentV2]:
        """Check for clear execution patterns that don't need LLM classification.

        Patterns like "〇〇を実行して", "execute 〇〇", "run 〇〇" are clear
        execution requests that should be handled as prompt/workflow execute.

        Also handles help requests like "help(topic='execution')" or "ヘルプ".

        Returns:
            IntentV2 if pattern matches, None otherwise
        """
        import re

        # Help pattern check first
        help_patterns = [
            r'help\s*\(\s*topic\s*=\s*["\'](\w+)["\']\s*\)',  # help(topic='xxx')
            r'^ヘルプ$',  # Simple help
            r'^help$',  # Simple help
            r'使い方',  # Usage
        ]
        for pattern in help_patterns:
            if re.search(pattern, message, re.IGNORECASE):
                logger.info(f"[Intent] Help pattern matched")
                return IntentV2(
                    domain=Domain.HELP,
                    action=Action.SHOW,
                    confidence=1.0,
                    classification_method="rule_help_pattern"
                )

        # Execution patterns with name capture
        execution_patterns = [
            # Japanese: 「〇〇を実行して」「〇〇を実行」「〇〇実行して」
            r'(.+?)(?:を)?(?:実行して|実行する|実行|を走らせて|を動かして)',
            # English: "execute 〇〇", "run 〇〇"
            r'(?:execute|run)\s+(.+)',
        ]

        for pattern in execution_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                target_name = match.group(1).strip()
                # Skip if target looks like a programming keyword
                programming_keywords = ['python', 'c#', 'java', 'javascript', 'code',
                                        'コード', 'プログラム', 'function', '関数']
                if any(kw in target_name.lower() for kw in programming_keywords):
                    continue

                # Skip if target is empty or too short
                if not target_name or len(target_name) < 2:
                    continue

                # Check for explicit workflow/prompt indicators
                is_workflow = 'ワークフロー' in message or 'workflow' in message.lower()
                is_prompt = 'プロンプト' in message or 'prompt' in message.lower()

                # Determine domain (default to prompt, let agent figure it out)
                domain = Domain.WORKFLOW if is_workflow else Domain.PROMPT

                logger.info(f"[Intent] Execution pattern matched: '{target_name}' -> {domain.value}/execute")

                return IntentV2(
                    domain=domain,
                    action=Action.EXECUTE,
                    target_name=target_name,
                    confidence=0.9,  # High but not 100% to allow override
                    classification_method="rule_execution_pattern"
                )

        return None

    def _get_client(self):
        """Lazy initialization of LLM client."""
        if self._client is None:
            from backend.llm.factory import get_llm_client
            try:
                self._client = get_llm_client(self.model_name)
            except Exception as e:
                logger.warning(f"Failed to initialize LLM client '{self.model_name}': {e}")
                # Try fallback models
                for fallback in ["openai-gpt-4.1-nano", "openai-gpt-5-nano", "azure-gpt-5-nano"]:
                    try:
                        self._client = get_llm_client(fallback)
                        self.model_name = fallback
                        logger.info(f"Using fallback model: {fallback}")
                        break
                    except Exception:
                        continue
        return self._client

    def classify(self, message: str, conversation_history: str = "") -> Optional[IntentV2]:
        """Classify user message using LLM.

        Args:
            message: User input message
            conversation_history: Recent conversation history for context

        Returns:
            IntentV2 object or None if classification fails
        """
        # Check for clear execution patterns first (no LLM needed)
        execution_intent = self._check_execution_pattern(message)
        if execution_intent:
            return execution_intent

        client = self._get_client()
        if client is None:
            logger.warning("No LLM client available for intent classification")
            return None

        try:
            # Use conversation history or placeholder
            history_text = conversation_history if conversation_history else "(なし)"
            prompt = self.CLASSIFICATION_PROMPT.format(
                message=message,
                conversation_history=history_text
            )
            start_time = time.time()

            response = client.call(prompt=prompt, temperature=0.0)

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[Intent-LLM] Classification took {elapsed_ms}ms using {self.model_name}")

            if not response.success:
                logger.warning(f"LLM classification failed: {response.error_message}")
                return None

            # Parse JSON response
            intent = self._parse_response(response.response_text, message)
            if intent:
                intent.classification_method = "llm"
                intent.raw_llm_response = response.response_text
            return intent

        except Exception as e:
            logger.error(f"Error in LLM classification: {e}", exc_info=True)
            return None

    def _parse_response(self, response_text: str, original_message: str) -> Optional[IntentV2]:
        """Parse LLM response into IntentV2 object."""
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response_text)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find raw JSON
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    json_str = json_match.group()
                else:
                    logger.warning(f"No JSON found in LLM response: {response_text[:200]}")
                    return None

            data = json.loads(json_str)

            # Parse domain
            domain_str = data.get("domain", "out_of_scope")
            try:
                domain = Domain(domain_str)
            except ValueError:
                domain = Domain.OUT_OF_SCOPE

            # Parse action
            action_str = data.get("action", "unknown")
            try:
                action = Action(action_str)
            except ValueError:
                action = Action.UNKNOWN

            # Parse other fields
            confidence = float(data.get("confidence", 0.5))
            target_id = data.get("target_id")
            target_name = data.get("target_name")

            # Validate target_id is numeric
            if target_id is not None:
                try:
                    target_id = int(target_id)
                except (ValueError, TypeError):
                    target_id = None

            return IntentV2(
                domain=domain,
                action=action,
                confidence=confidence,
                target_id=target_id,
                target_name=target_name,
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from LLM response: {e}")
            return None
        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}", exc_info=True)
            return None


# =============================================================================
# Rule-based Fallback Classifier
# =============================================================================

class RuleBasedClassifier:
    """Rule-based fallback classifier when LLM is unavailable.

    Uses keyword matching with improved scoring and context awareness.
    """

    # Domain keywords (Japanese and English)
    DOMAIN_KEYWORDS = {
        Domain.PROJECT: [
            "プロジェクト", "project", "projects",
        ],
        Domain.PROMPT: [
            "プロンプト", "prompt", "prompts",
        ],
        Domain.WORKFLOW: [
            "ワークフロー", "フロー", "workflow", "flow", "バッチ", "batch", "一括",
            "WF", "wf",  # WF abbreviation support
        ],
        Domain.JOB: [
            "ジョブ", "job", "jobs", "実行状態", "実行結果", "履歴", "history",
            "結果", "result", "status", "CSV", "csv", "ダウンロード", "download",
            "エクスポート", "export", "リンク", "link", "URL", "url",
        ],
        Domain.TEMPLATE: [
            "テンプレート", "template", "パラメータ", "parameter", "変数", "variable",
            "構文", "syntax",
        ],
        Domain.SETTINGS: [
            "設定", "setting", "settings", "configuration", "config",
            "並列", "parallel", "パラレル",
        ],
        Domain.MODEL: [
            "モデル", "model", "LLM", "GPT", "Claude", "使用モデル",
        ],
        Domain.HELP: [
            "ヘルプ", "使い方", "操作方法", "できること", "機能",
            "何ができ", "how to", "what can",
            # "help" は削除: "helpを参照して" 等はエージェントへの指示であり、ユーザーのヘルプ要求ではない
        ],
        Domain.DATASET: [
            "データセット", "dataset", "datasets", "データ",
            "Huggingface", "huggingface", "HF", "hf", "ハギングフェイス",
            "インポート", "import", "取り込み",
            "スプリット", "split", "train", "test", "validation",
        ],
    }

    # Action keywords
    ACTION_KEYWORDS = {
        Action.LIST: [
            "一覧", "リスト", "list", "全部", "すべて", "all", "表示", "見せ", "show",
        ],
        Action.GET: [
            "詳細", "detail", "情報", "info", "取得", "get", "確認", "check",
        ],
        Action.CREATE: [
            "作成", "create", "新規", "new", "追加", "add",
        ],
        Action.UPDATE: [
            "更新", "update", "編集", "edit", "変更", "change", "修正", "modify",
        ],
        Action.DELETE: [
            "削除", "delete", "remove", "消去", "消す",
        ],
        Action.EXECUTE: [
            "実行", "execute", "run", "送信", "send", "試す", "試し", "テスト", "test", "評価", "evaluate",
        ],
        Action.ANALYZE: [
            "分析", "analyze", "解析", "parse", "抽出", "extract",
        ],
        Action.CANCEL: [
            "キャンセル", "cancel", "停止", "stop", "中止", "abort",
        ],
        Action.EXPORT: [
            "CSV", "csv", "ダウンロード", "download", "エクスポート", "export",
            "リンク", "link", "URL", "url", "出力", "取得",
        ],
        Action.SWITCH: [
            "切り替え", "switch", "変更", "change", "選択", "select",
        ],
        Action.SHOW: [
            "教えて", "説明", "explain", "ガイド", "guide",
        ],
        Action.IMPORT: [
            "インポート", "import", "取り込", "読み込", "ロード", "load",
        ],
        Action.SEARCH: [
            "検索", "search", "探", "find", "さがす",
        ],
        Action.PREVIEW: [
            "プレビュー", "preview", "確認", "見", "表示", "show",
        ],
    }

    # Out-of-scope patterns - COMPREHENSIVE list of off-topic requests
    OUT_OF_SCOPE_PATTERNS = [
        # 天気・ニュース・一般情報
        r"(?i)(天気|weather|forecast|予報)",
        r"(?i)(ニュース|news|時事|芸能|スポーツ|株価|stock)",

        # 計算・数学
        r"(?i)\d+\s*[\+\-\*\/\%\^]\s*\d+",  # Math expressions: 1+1, 2*3, etc.
        r"(?i)(計算|calculate|math|算数|数学)",
        r"(?i)(sin|cos|tan|log|sqrt|平方根)",

        # プログラミング言語でのコード記述依頼
        r"(?i)(c#|c\#|csharp).*(書|write|作|create|実装|implement|コード|code)",
        r"(?i)(c\+\+|cpp).*(書|write|作|create|実装|implement|コード|code)",
        r"(?i)(java|javascript|typescript|js|ts).*(書|write|作|create|実装|implement|コード|code)",
        r"(?i)(python|パイソン|py).*(書|write|作|create|実装|implement|コード|code)",
        r"(?i)(ruby|ルビー).*(書|write|作|create|実装|implement|コード|code)",
        r"(?i)(go|golang|rust|swift|kotlin).*(書|write|作|create|実装|implement|コード|code)",
        r"(?i)(php|perl|scala|r言語).*(書|write|作|create|実装|implement|コード|code)",
        r"(?i)(html|css|sql).*(書|write|作|create|実装|implement|コード|code)",
        r"(?i)(shell|bash|powershell|sh).*(書|write|作|create|実装|implement|コード|code)",

        # 一般的なプログラミング依頼
        r"(?i)hello\s*world",
        r"(?i)ハロー\s*ワールド",
        r"(?i)(プログラム|コード|code|スクリプト|script).*(書|write|作|create)",
        r"(?i)(関数|function|クラス|class|メソッド|method).*(書|write|作|create|実装|implement)",
        r"(?i)(アルゴリズム|algorithm|ソート|sort|検索|search).*(書|write|作|create|実装|implement)",
        r"(?i)(API|エーピーアイ).*(書|write|作|create|実装|implement)",
        r"(?i)FizzBuzz",
        r"(?i)(フィボナッチ|fibonacci)",
        r"(?i)(素数|prime).*(判定|計算|求|find)",

        # 翻訳
        r"(?i)(翻訳|translate|訳して)",
        r"(?i)(英語|日本語|中国語|韓国語).*(に|to|へ).*(翻訳|訳|translate)",

        # 一般知識質問
        r"(?i)(歴史|history|地理|geography)",
        r"(?i)(首都|capital|人口|population)",
        r"(?i)(誰|who).*(発明|invent|作った|created)",
        r"(?i)(何年|when|いつ).*(起き|happen|発生)",
        r"(?i)(説明|explain|教えて).*(仕組み|how.*work|mechanism)",

        # 料理・レシピ
        r"(?i)(レシピ|recipe|料理|cooking|作り方)",

        # 物語・創作
        r"(?i)(物語|story|小説|novel|詩|poem).*(書|write|作|create)",
        r"(?i)(歌詞|lyrics|俳句|haiku).*(書|write|作|create)",

        # 占い・ジョーク
        r"(?i)(占い|fortune|horoscope|星座)",
        r"(?i)(ジョーク|joke|面白い話|funny)",

        # アドバイス（非システム関連）
        r"(?i)(恋愛|dating|人間関係|relationship).*(相談|advice|アドバイス)",
        r"(?i)(健康|health|ダイエット|diet).*(相談|advice|アドバイス)",
    ]

    # Confirmation patterns (yes/no responses)
    CONFIRMATION_PATTERNS = [
        r"^(yes|はい|うん|ok|okay|オーケー|了解|承知|お願い|実行して|やって|進めて)$",
        r"^(yes|はい|うん|ok|okay)[!！。、\s]*$",
        r"^(no|いいえ|いや|やめ|キャンセル|中止|停止)$",
        r"^(no|いいえ|いや)[!！。、\s]*$",
    ]

    def __init__(self):
        self._out_of_scope_compiled = [re.compile(p) for p in self.OUT_OF_SCOPE_PATTERNS]
        self._confirmation_compiled = [re.compile(p, re.IGNORECASE) for p in self.CONFIRMATION_PATTERNS]

    def _is_confirmation(self, message: str) -> Optional[bool]:
        """Check if message is a confirmation (yes/no) response.

        Returns:
            True for positive confirmation (yes), False for negative (no), None if not a confirmation
        """
        message_stripped = message.strip()

        # Positive confirmations (include common typos like "ye", "yea", "yep")
        positive_patterns = [
            r"^(yes|yea|yep|ye|はい|うん|ok|okay|オーケー|了解|承知|お願い|実行して|やって|進めて|する)[!！。、\s]*$",
            # Combined confirmations like "はい、お願いします", "はい、やってください"
            r"^(はい|うん|ok)[、,\s]*(お願い|やって|進めて|実行|頼む|頼みます)[しますください!！。]*$",
            # Short polite requests as confirmations
            r"^お願いします[!！。]*$",
            r"^よろしくお願いします[!！。]*$",
        ]
        for pattern in positive_patterns:
            if re.match(pattern, message_stripped, re.IGNORECASE):
                return True

        # Negative confirmations
        negative_patterns = [
            r"^(no|nope|いいえ|いや|やめ|キャンセル|中止|停止|しない)[!！。、\s]*$",
        ]
        for pattern in negative_patterns:
            if re.match(pattern, message_stripped, re.IGNORECASE):
                return False

        return None

    def classify(self, message: str) -> IntentV2:
        """Classify message using rule-based approach.

        Args:
            message: User input message

        Returns:
            IntentV2 object
        """
        message_lower = message.lower()

        # Check for confirmation responses first (yes/no)
        confirmation = self._is_confirmation(message)
        if confirmation is not None:
            return IntentV2(
                domain=Domain.HELP,  # Special domain for confirmations
                action=Action.CONFIRM,
                confidence=0.95,
                classification_method="rule",
                parameters={"confirmed": confirmation},
            )

        # Check for out-of-scope patterns
        for pattern in self._out_of_scope_compiled:
            if pattern.search(message):
                return IntentV2(
                    domain=Domain.OUT_OF_SCOPE,
                    action=Action.UNKNOWN,
                    confidence=0.8,
                    classification_method="rule",
                    rejection_reason="この質問はシステムの対応範囲外です。",
                )

        # Score domains
        domain_scores: Dict[Domain, float] = {}
        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            score = 0.0
            for kw in keywords:
                if kw.lower() in message_lower:
                    score += len(kw) / len(message_lower)
            if score > 0:
                domain_scores[domain] = min(score * 3, 1.0)

        # Score actions
        action_scores: Dict[Action, float] = {}
        for action, keywords in self.ACTION_KEYWORDS.items():
            score = 0.0
            for kw in keywords:
                if kw.lower() in message_lower:
                    score += len(kw) / len(message_lower)
            if score > 0:
                action_scores[action] = min(score * 3, 1.0)

        # Get best domain and action
        if domain_scores:
            best_domain = max(domain_scores.items(), key=lambda x: x[1])
            domain = best_domain[0]
            domain_conf = best_domain[1]
        else:
            # Check for help-related questions
            if self._is_help_question(message_lower):
                domain = Domain.HELP
                domain_conf = 0.6
            else:
                domain = Domain.OUT_OF_SCOPE
                domain_conf = 0.5

        if action_scores:
            best_action = max(action_scores.items(), key=lambda x: x[1])
            action = best_action[0]
            action_conf = best_action[1]
        else:
            # Default action based on domain
            if domain == Domain.HELP:
                action = Action.SHOW
                action_conf = 0.7
            else:
                action = Action.LIST  # Most common default
                action_conf = 0.3

        # Calculate overall confidence
        confidence = (domain_conf + action_conf) / 2

        # Extract target ID if present
        target_id = self._extract_target_id(message)

        # Create rejection reason if out of scope
        rejection_reason = None
        if domain == Domain.OUT_OF_SCOPE:
            rejection_reason = self._get_rejection_message()

        return IntentV2(
            domain=domain,
            action=action,
            confidence=confidence,
            target_id=target_id,
            classification_method="rule",
            rejection_reason=rejection_reason,
        )

    def _is_help_question(self, message: str) -> bool:
        """Check if message is asking for help.

        Note: "helpを参照して" (look at help) is NOT a help question -
        it's an instruction to the agent to use the help tool.
        """
        message_lower = message.lower()

        # First, check if there are action keywords indicating the user wants to DO something
        # In that case, "help" is likely an instruction to use the help tool, not a request for help
        action_keywords = ["修正", "作成", "実行", "更新", "削除", "表示", "追加", "変更",
                          "create", "update", "delete", "execute", "run", "modify", "fix", "add"]
        has_action = any(kw in message_lower for kw in action_keywords)

        # Check if "help" is used as an instruction to the agent
        # e.g., "helpを参照して", "helpを見て", "helpを確認して"
        agent_instruction_patterns = [
            r"help.*を.*[参見確]",  # helpを参照/見て/確認
            r"help.*[参見確].*て",  # help参照して, help見て
            r"[参見確].*help",      # helpを参照, helpを見る
        ]
        is_agent_instruction = any(re.search(p, message_lower) for p in agent_instruction_patterns)

        # If there's an action keyword or it's an agent instruction, not a help question
        if has_action or is_agent_instruction:
            return False

        # Check traditional help question patterns
        help_patterns = [
            r"このシステム", r"このエージェント", r"あなた(は|に|の)",
            r"何ができ", r"どんなこと.*でき", r"使い方",
            r"what can you", r"how do i", r"how to use",
        ]
        for pattern in help_patterns:
            if re.search(pattern, message, re.IGNORECASE):
                return True
        return False

    def _extract_target_id(self, message: str) -> Optional[int]:
        """Extract target resource ID from message."""
        # Patterns like "ID 123", "プロンプト1", "workflow 42"
        patterns = [
            r"(?:ID|id|Id)\s*[:：]?\s*(\d+)",
            r"(?:プロンプト|ワークフロー|プロジェクト|ジョブ)\s*(\d+)",
            r"(?:prompt|workflow|project|job)\s*(\d+)",
            r"#(\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue
        return None

    def _get_rejection_message(self) -> str:
        """Get rejection message for out-of-scope requests."""
        app_name = get_app_name()
        return f"""申し訳ございませんが、その要求は本システムの対応範囲外です。

このエージェントは**{app_name}**の操作支援専用です。
以下の操作をサポートしています：

**リソース管理:**
- プロジェクト: 一覧、作成、更新、削除
- プロンプト: 一覧、作成、更新、削除、実行
- ワークフロー: 一覧、作成、更新、削除、実行

**データセット管理:**
- ローカルデータセット: 一覧、検索、プレビュー
- Huggingface連携: 検索、プレビュー、インポート

**実行・監視:**
- プロンプト/ワークフローの実行
- ジョブ状態確認、キャンセル
- テンプレート分析

**設定:**
- システム設定の確認・変更
- LLMモデルの切り替え

「ヘルプ」と入力すると詳細な使い方を確認できます。"""


# =============================================================================
# Main Intent Extractor (Hybrid)
# =============================================================================

class IntentExtractorV2:
    """Hybrid intent extractor combining security filter, LLM, and rule-based fallback.

    Processing order:
    1. Security pre-filter (rule-based, blocks threats)
    2. LLM-based classification (flexible, context-aware)
    3. Rule-based fallback (if LLM fails)
    """

    @staticmethod
    def _get_help_message() -> str:
        """Get help message with dynamic app name."""
        app_name = get_app_name()
        return f"""## {app_name} エージェント

このエージェントは{app_name}の操作を支援します。

### 使用例

**プロジェクト操作:**
- 「プロジェクト一覧を表示して」
- 「新しいプロジェクトを作成して」

**プロンプト操作:**
- 「プロンプト一覧を見せて」
- 「プロンプトID 1を実行して」
- 「このテンプレートを分析して: {{名前:TEXT5}}」

**ワークフロー操作:**
- 「ワークフロー一覧を表示」
- 「ワークフローID 1を実行」

**データセット操作:**
- 「データセット一覧を表示」
- 「Huggingfaceでopenbookqaを検索して」
- 「allenai/openbookqaのtestスプリットをインポート」

**ジョブ管理:**
- 「最新のジョブ状態を確認」
- 「ジョブID 123をキャンセル」

**設定:**
- 「現在の設定を表示」
- 「使用可能なモデル一覧」

何をお手伝いしましょうか？"""

    def __init__(
        self,
        classifier_model: str = "openai-gpt-4.1-nano",
        use_llm: bool = True,
        fallback_to_rules: bool = True,
    ):
        """Initialize the intent extractor.

        Args:
            classifier_model: Model to use for LLM-based classification
            use_llm: Whether to use LLM for classification
            fallback_to_rules: Whether to fall back to rule-based if LLM fails
        """
        self.use_llm = use_llm
        self.fallback_to_rules = fallback_to_rules

        if use_llm:
            self.llm_classifier = LLMIntentClassifier(classifier_model)
        else:
            self.llm_classifier = None

        self.rule_classifier = RuleBasedClassifier()

    def _check_confirmation(self, message: str) -> Optional[bool]:
        """Check if message is a confirmation (yes/no) response.

        This bypasses LLM classification for short confirmation responses
        that require conversation context rather than intent classification.

        Args:
            message: User input message

        Returns:
            True for positive confirmation (yes), False for negative (no), None if not a confirmation
        """
        message_stripped = message.strip()

        # Only check short messages (confirmations are typically short)
        if len(message_stripped) > 30:
            return None

        # Positive confirmations (include common typos like "ye", "yea", "yep")
        positive_patterns = [
            r"^(yes|yea|yep|ye|はい|うん|ok|okay|オーケー|了解|承知|お願い|実行して|やって|進めて|する)[!！。、\s]*$",
            r"^(y|ん)[!！。、\s]*$",
            # Combined confirmations like "はい、お願いします", "はい、やってください"
            r"^(はい|うん|ok)[、,\s]*(お願い|やって|進めて|実行|頼む|頼みます)[しますください!！。]*$",
            # Short polite requests as confirmations
            r"^お願いします[!！。]*$",
            r"^よろしくお願いします[!！。]*$",
        ]
        for pattern in positive_patterns:
            if re.match(pattern, message_stripped, re.IGNORECASE):
                return True

        # Negative confirmations
        negative_patterns = [
            r"^(no|いいえ|いや|やめ|キャンセル|中止|停止)[!！。、\s]*$",
            r"^(n)[!！。、\s]*$",
        ]
        for pattern in negative_patterns:
            if re.match(pattern, message_stripped, re.IGNORECASE):
                return False

        return None

    def extract(self, user_message: str, conversation_history: str = "") -> IntentV2:
        """Extract intent from user message.

        Args:
            user_message: The user's input message
            conversation_history: Recent conversation history for context

        Returns:
            IntentV2 object with domain, action, and metadata
        """
        # Step 1: Security pre-filter
        is_threat, threat_category, rejection = SecurityPreFilter.check(user_message)
        if is_threat:
            return IntentV2(
                domain=Domain.OUT_OF_SCOPE,
                action=Action.UNKNOWN,
                confidence=1.0,
                classification_method="security",
                rejection_reason=rejection,
            )

        # Step 2: Check for confirmation responses (yes/no) - bypass LLM for these
        # Short responses like "yes", "はい", "no" should not go through LLM classification
        # because they need conversation context, not intent classification
        confirmation = self._check_confirmation(user_message)
        if confirmation is not None:
            logger.info(f"[Intent] Confirmation detected: {'positive' if confirmation else 'negative'}")
            return IntentV2(
                domain=Domain.HELP,  # Special domain for confirmations
                action=Action.CONFIRM,
                confidence=0.95,
                classification_method="rule",
                parameters={"confirmed": confirmation},
            )

        # Step 3: Try LLM-based classification
        intent = None
        if self.use_llm and self.llm_classifier:
            intent = self.llm_classifier.classify(user_message, conversation_history)

        # Step 4: Fall back to rule-based if needed
        if intent is None and self.fallback_to_rules:
            logger.info("[Intent] Using rule-based fallback")
            intent = self.rule_classifier.classify(user_message)

        # Step 5: Final fallback
        if intent is None:
            intent = IntentV2(
                domain=Domain.OUT_OF_SCOPE,
                action=Action.UNKNOWN,
                confidence=0.0,
                classification_method="none",
                rejection_reason="意図を判定できませんでした。",
            )

        logger.info(
            f"[Intent] Extracted: domain={intent.domain.value}, "
            f"action={intent.action.value}, confidence={intent.confidence:.2f}, "
            f"method={intent.classification_method}"
        )

        return intent

    def is_allowed(self, intent: IntentV2) -> bool:
        """Check if the intent is allowed to proceed."""
        return intent.is_allowed()

    def get_rejection_message(self, intent: IntentV2) -> str:
        """Get rejection message for blocked intents."""
        if intent.rejection_reason:
            return intent.rejection_reason
        return self.rule_classifier._get_rejection_message()

    def get_help_message(self) -> str:
        """Get help message for the system."""
        return self._get_help_message()


# =============================================================================
# Singleton Instance
# =============================================================================

_intent_extractor_v2: Optional[IntentExtractorV2] = None


def get_intent_extractor_v2(
    classifier_model: str = "openai-gpt-4.1-nano",
    use_llm: bool = True,
) -> IntentExtractorV2:
    """Get or create the singleton intent extractor instance.

    Args:
        classifier_model: Model to use for LLM classification
        use_llm: Whether to use LLM (set to False for testing/debugging)
    """
    global _intent_extractor_v2
    if _intent_extractor_v2 is None:
        _intent_extractor_v2 = IntentExtractorV2(
            classifier_model=classifier_model,
            use_llm=use_llm,
        )
    return _intent_extractor_v2


def reset_intent_extractor_v2():
    """Reset the singleton instance (for testing)."""
    global _intent_extractor_v2
    _intent_extractor_v2 = None

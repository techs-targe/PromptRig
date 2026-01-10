"""Intent Extraction Layer for AI Agent.

This module provides rule-based intent extraction WITHOUT LLM dependency.
Only system operation requests are allowed; all other requests are rejected.
"""

import re
import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Set, Tuple

from backend.utils import get_app_name

logger = logging.getLogger(__name__)


class IntentType(str, Enum):
    """Types of user intent."""
    # Allowed intents (system operations)
    PROJECT_MANAGE = "project_manage"      # Project CRUD
    PROMPT_MANAGE = "prompt_manage"        # Prompt CRUD
    PROMPT_EXECUTE = "prompt_execute"      # Execute prompt
    WORKFLOW_MANAGE = "workflow_manage"    # Workflow CRUD
    WORKFLOW_EXECUTE = "workflow_execute"  # Execute workflow
    JOB_MANAGE = "job_manage"              # Job status/cancel
    TEMPLATE_ANALYZE = "template_analyze"  # Analyze template
    SETTINGS_MANAGE = "settings_manage"    # System settings
    MODEL_MANAGE = "model_manage"          # LLM model selection
    HELP = "help"                          # System usage help

    # Rejected intent
    OUT_OF_SCOPE = "out_of_scope"          # Not related to system


@dataclass
class Intent:
    """Extracted intent from user message."""
    intent_type: IntentType
    confidence: float  # 0.0 - 1.0
    matched_keywords: List[str]
    suggested_tools: List[str]
    rejection_reason: Optional[str] = None


class IntentExtractor:
    """Rule-based intent extractor.

    Extracts user intent from natural language without LLM dependency.
    Only allows system operation requests; rejects everything else.
    """

    # Keywords for each intent type (Japanese and English)
    INTENT_KEYWORDS = {
        IntentType.PROJECT_MANAGE: {
            "keywords": [
                # Japanese
                "プロジェクト", "プロジェクト一覧", "プロジェクト作成", "プロジェクト削除",
                "プロジェクト更新", "プロジェクト取得", "プロジェクト情報",
                # English
                "project", "projects", "create project", "delete project",
                "update project", "list project", "get project",
            ],
            "tools": ["list_projects", "get_project", "create_project", "update_project", "delete_project"],
        },
        IntentType.PROMPT_MANAGE: {
            "keywords": [
                # Japanese
                "プロンプト", "プロンプト一覧", "プロンプト作成", "プロンプト削除",
                "プロンプト更新", "プロンプト取得", "プロンプト情報", "プロンプト編集",
                # English
                "prompt", "prompts", "create prompt", "delete prompt",
                "update prompt", "list prompt", "get prompt", "edit prompt",
                "show prompt", "show prompts",
            ],
            "tools": ["list_prompts", "get_prompt", "create_prompt", "update_prompt", "delete_prompt"],
        },
        IntentType.PROMPT_EXECUTE: {
            "keywords": [
                # Japanese
                "プロンプト実行", "プロンプトを実行", "実行して", "送信して",
                "テスト実行", "試して", "評価して", "評価実行",
                # English
                "execute prompt", "run prompt", "run the prompt",
                "test prompt", "send prompt", "evaluate", "evaluation",
            ],
            "tools": ["execute_prompt", "execute_template"],
        },
        IntentType.WORKFLOW_MANAGE: {
            "keywords": [
                # Japanese
                "ワークフロー", "ワークフロー一覧", "ワークフロー作成", "ワークフロー削除",
                "ワークフロー更新", "ワークフロー取得", "ワークフロー情報", "ワークフロー編集",
                "フロー", "フロー一覧",
                # English
                "workflow", "workflows", "create workflow", "delete workflow",
                "update workflow", "list workflow", "get workflow", "flow",
            ],
            "tools": ["list_workflows", "get_workflow", "create_workflow", "update_workflow", "delete_workflow"],
        },
        IntentType.WORKFLOW_EXECUTE: {
            "keywords": [
                # Japanese
                "ワークフロー実行", "ワークフローを実行", "フロー実行", "フローを実行",
                "バッチ実行", "一括実行", "フロー実行して", "一括実行して",
                # English
                "execute workflow", "run workflow", "batch execute",
            ],
            "tools": ["execute_workflow"],
        },
        IntentType.JOB_MANAGE: {
            "keywords": [
                # Japanese
                "ジョブ", "ジョブ一覧", "ジョブ状態", "ジョブ確認", "ジョブキャンセル",
                "ジョブ停止", "実行状態", "実行結果", "結果確認", "履歴",
                # English
                "job", "jobs", "job status", "job list", "cancel job",
                "stop job", "execution status", "execution result", "history",
            ],
            "tools": ["list_jobs", "get_job", "cancel_job"],
        },
        IntentType.TEMPLATE_ANALYZE: {
            "keywords": [
                # Japanese
                "テンプレート", "テンプレート分析", "パラメータ抽出", "パラメータ確認",
                "構文解析", "変数抽出", "変数確認", "パラメータを抽出", "変数を抽出",
                # English
                "template", "analyze template", "extract parameters",
                "parse template", "template variables",
            ],
            "tools": ["analyze_template"],
        },
        IntentType.SETTINGS_MANAGE: {
            "keywords": [
                # Japanese
                "設定", "システム設定", "設定変更", "設定確認", "設定一覧",
                "並列数", "パラレル", "並列実行",
                # English
                "setting", "settings", "system settings", "configuration",
                "parallelism", "parallel",
            ],
            "tools": ["get_system_settings", "update_system_setting"],
        },
        IntentType.MODEL_MANAGE: {
            "keywords": [
                # Japanese
                "モデル", "LLMモデル", "モデル一覧", "モデル切り替え", "モデル変更",
                "GPT", "Claude", "使用モデル",
                # English
                "model", "llm model", "list models", "switch model", "change model",
            ],
            "tools": ["list_llm_models", "get_active_model", "set_active_model"],
        },
        IntentType.HELP: {
            "keywords": [
                # Japanese - specific help keywords, not generic "教えて"
                "ヘルプ", "使い方", "操作方法", "何ができる", "どうやって",
                "機能一覧", "コマンド一覧", "できること",
                "このシステム", "システムの使い方", "操作説明",
                "使い方を教えて", "操作方法を教えて", "できることを教えて",
                # English - specific help keywords
                "help", "usage", "what can you do", "features",
                "commands", "guide", "tutorial", "how to use this",
            ],
            "tools": [],  # Help doesn't need tools
        },
    }

    @staticmethod
    def _get_rejection_message() -> str:
        """Get rejection message for out-of-scope requests with dynamic app name."""
        app_name = get_app_name()
        return f"""申し訳ございませんが、その要求は本システムの対応範囲外です。

このエージェントは**{app_name}**の操作支援専用です。
以下の操作をサポートしています：

**リソース管理:**
- プロジェクト: 一覧、作成、更新、削除
- プロンプト: 一覧、作成、更新、削除、実行
- ワークフロー: 一覧、作成、更新、削除、実行

**実行・監視:**
- プロンプト/ワークフローの実行
- ジョブ状態確認、キャンセル
- テンプレート分析

**設定:**
- システム設定の確認・変更
- LLMモデルの切り替え

「ヘルプ」と入力すると詳細な使い方を確認できます。"""

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

**ジョブ管理:**
- 「最新のジョブ状態を確認」
- 「ジョブID 123をキャンセル」

**設定:**
- 「現在の設定を表示」
- 「使用可能なモデル一覧」

何をお手伝いしましょうか？"""

    def __init__(self):
        """Initialize the intent extractor."""
        # Build keyword index for fast lookup
        self._keyword_to_intent: dict[str, List[IntentType]] = {}
        for intent_type, config in self.INTENT_KEYWORDS.items():
            for keyword in config["keywords"]:
                keyword_lower = keyword.lower()
                if keyword_lower not in self._keyword_to_intent:
                    self._keyword_to_intent[keyword_lower] = []
                self._keyword_to_intent[keyword_lower].append(intent_type)

    # Patterns that should always be rejected (security/out-of-scope)
    REJECTION_PATTERNS = [
        # System prompt disclosure attempts
        r"(指示|instruction).*?(教|見せ|表示|show|display|reveal)",
        r"(教|見せ|表示|show|display|reveal).*?(指示|instruction)",
        r"system\s*prompt",
        r"システム\s*プロンプト",
        r"内部.*?(指示|設定)",
        r"秘密.*?(教|見せ)",
        r"reveal.*?(prompt|your)",  # "Reveal your prompt" etc.
        r"your.*?(prompt|instruction)",  # "your prompt", "your instructions"
        # Note: "show prompt" and "show prompts" are valid commands, not disclosure attempts
        # General knowledge questions (not system-related)
        r"(天気|weather)",
        r"(?<![a-z])(日付|today)(?![a-z])",  # Avoid matching "update"
        r"what.*date",  # "what's the date" but not "update"
        r"(計算|calculate|math)",
        r"\d+\s*[\+\-\*\/]\s*\d+",  # Math expressions
        # Programming questions (not about this system)
        r"(言語|language).*?(書|write|code)",
        r"(コード|code).*?(書|write)",
        r"(プログラム|program).*?(書|write|作)",
        r"hello\s*world",  # Programming exercise
    ]

    def extract(self, user_message: str) -> Intent:
        """Extract intent from user message.

        Args:
            user_message: The user's input message

        Returns:
            Intent object with type, confidence, and related info
        """
        message_lower = user_message.lower().strip()
        message_normalized = self._normalize_message(user_message)

        # First check rejection patterns (highest priority)
        for pattern in self.REJECTION_PATTERNS:
            if re.search(pattern, message_normalized, re.IGNORECASE):
                logger.info(f"[Intent] Matched rejection pattern: {pattern}")
                return Intent(
                    intent_type=IntentType.OUT_OF_SCOPE,
                    confidence=1.0,
                    matched_keywords=[f"rejection_pattern:{pattern}"],
                    suggested_tools=[],
                    rejection_reason=self._get_rejection_message(),
                )

        # Count keyword matches for each intent type
        intent_scores: dict[IntentType, Tuple[float, List[str]]] = {}

        for intent_type, config in self.INTENT_KEYWORDS.items():
            matched_keywords = []
            for keyword in config["keywords"]:
                keyword_lower = keyword.lower()
                if keyword_lower in message_normalized:
                    matched_keywords.append(keyword)

            if matched_keywords:
                # Score based on number of matches and keyword length
                score = sum(len(kw) for kw in matched_keywords) / len(message_normalized)
                score = min(score * 2, 1.0)  # Normalize to 0-1

                # Priority boost for EXECUTE intents when "実行" is in the message
                # This ensures "プロンプト実行" -> PROMPT_EXECUTE, not PROMPT_MANAGE
                if "実行" in message_normalized or "execute" in message_normalized or "run" in message_normalized:
                    if intent_type in (IntentType.PROMPT_EXECUTE, IntentType.WORKFLOW_EXECUTE):
                        score += 0.5  # Significant boost for execute intents

                # Priority boost for WORKFLOW intents when "フロー" or "ワークフロー" or "バッチ" or "一括" is in the message
                # This ensures "フロー実行して" -> WORKFLOW_EXECUTE, not PROMPT_EXECUTE
                if any(kw in message_normalized for kw in ["フロー", "ワークフロー", "バッチ", "一括", "workflow", "batch"]):
                    if intent_type in (IntentType.WORKFLOW_MANAGE, IntentType.WORKFLOW_EXECUTE):
                        score += 0.6  # Higher boost for workflow intents

                intent_scores[intent_type] = (score, matched_keywords)

        # If no matches, check if it's a greeting or very short message
        if not intent_scores:
            # Check for system-related question patterns
            if self._is_system_question(message_normalized):
                return Intent(
                    intent_type=IntentType.HELP,
                    confidence=0.7,
                    matched_keywords=["システム関連質問"],
                    suggested_tools=[],
                )

            # Out of scope
            return Intent(
                intent_type=IntentType.OUT_OF_SCOPE,
                confidence=1.0,
                matched_keywords=[],
                suggested_tools=[],
                rejection_reason=self._get_rejection_message(),
            )

        # Get the highest scoring intent
        best_intent = max(intent_scores.items(), key=lambda x: x[1][0])
        intent_type = best_intent[0]
        score, matched_keywords = best_intent[1]

        # Get suggested tools
        suggested_tools = self.INTENT_KEYWORDS[intent_type]["tools"]

        logger.info(f"[Intent] Extracted: {intent_type.value}, confidence: {score:.2f}, keywords: {matched_keywords}")

        return Intent(
            intent_type=intent_type,
            confidence=score,
            matched_keywords=matched_keywords,
            suggested_tools=suggested_tools,
        )

    def _normalize_message(self, message: str) -> str:
        """Normalize message for keyword matching."""
        # Convert to lowercase
        normalized = message.lower()

        # Normalize Japanese characters (full-width to half-width for alphanumeric)
        # Keep Japanese characters as-is

        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)

        return normalized.strip()

    def _is_system_question(self, message: str) -> bool:
        """Check if the message is asking about this system."""
        system_question_patterns = [
            r"このシステム",
            r"このエージェント",
            r"あなた(は|に|の)",
            r"何ができ",
            r"どんなこと.*でき",
            r"使い方",
            r"操作方法",
            r"this system",
            r"this agent",
            r"what can you",
            r"how do i",
            r"how to use",
        ]

        for pattern in system_question_patterns:
            if re.search(pattern, message, re.IGNORECASE):
                return True

        return False

    def is_allowed(self, intent: Intent) -> bool:
        """Check if the intent is allowed.

        Args:
            intent: The extracted intent

        Returns:
            True if allowed, False if should be rejected
        """
        return intent.intent_type != IntentType.OUT_OF_SCOPE

    def get_rejection_message(self, intent: Intent) -> str:
        """Get rejection message for out-of-scope intent.

        Args:
            intent: The extracted intent

        Returns:
            Rejection message string
        """
        if intent.rejection_reason:
            return intent.rejection_reason
        return self._get_rejection_message()

    def get_help_message(self) -> str:
        """Get help message for the system.

        Returns:
            Help message string
        """
        return self._get_help_message()


# Singleton instance
_intent_extractor: Optional[IntentExtractor] = None


def get_intent_extractor() -> IntentExtractor:
    """Get the singleton intent extractor instance."""
    global _intent_extractor
    if _intent_extractor is None:
        _intent_extractor = IntentExtractor()
    return _intent_extractor

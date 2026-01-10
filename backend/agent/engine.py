"""AI Agent Execution Engine.

The agent can:
- Receive user instructions in natural language
- Use MCP tools to interact with the system via real MCP protocol
- Reason over multiple steps to achieve goals
- Return structured results

MCP Integration:
- Tools are accessed via MCP server (stdio transport)
- MCPClient spawns server subprocess and communicates via JSON-RPC
- Fallback to direct tool registry if MCP is unavailable
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

from backend.mcp.tools import get_tool_registry, MCPToolRegistry
from backend.mcp.client import MCPClient
from backend.llm.factory import get_llm_client
from backend.database.database import SessionLocal
from backend.database.models import SystemSetting
from backend.agent.policy import (
    PolicyLayer, PolicyDecision, PolicyResult, InputCategory,
    get_policy_layer, wrap_untrusted_content
)
# Legacy intent extractor (rule-based only)
from backend.agent.intent import (
    IntentExtractor, IntentType, Intent, get_intent_extractor
)
# New intent extractor v2 (LLM-based + hierarchical)
from backend.agent.intent_v2 import (
    IntentExtractorV2, IntentV2, Domain, Action, PermissionLevel,
    get_intent_extractor_v2, reset_intent_extractor_v2
)
# Multi-stage LLM guardrail chain
from backend.agent.guardrail_chain import (
    GuardrailChain, GuardrailChainResult, GuardrailDecision, GuardrailStage,
    get_guardrail_chain, reset_guardrail_chain
)
from backend.utils import get_app_name

logger = logging.getLogger(__name__)


class MessageRole(str, Enum):
    """Role of a message in the conversation."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    """A tool call made by the agent."""
    id: str
    name: str
    arguments: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None


@dataclass
class AgentMessage:
    """A message in the agent conversation."""
    role: MessageRole
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None  # For tool response messages
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class PendingConfirmation:
    """Stores info about a tool call awaiting user confirmation."""
    tool_name: str
    arguments: Dict[str, Any]


@dataclass
class AgentSession:
    """Session state for an agent conversation."""
    id: str
    messages: List[AgentMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    model_name: str = "claude-3.5-sonnet"
    temperature: float = 0.7
    max_iterations: int = 10
    current_iteration: int = 0
    status: str = "active"  # active, completed, error, cancelled, terminated
    current_intent: Optional[IntentV2] = None  # Current intent (v2) for the session
    terminated: bool = False  # Session terminated by security guardrail
    pending_confirmation: Optional[PendingConfirmation] = None  # Tool call awaiting confirmation

    def add_message(self, message: AgentMessage):
        """Add a message to the session."""
        self.messages.append(message)

    def get_conversation_history(self) -> List[Dict[str, Any]]:
        """Get conversation history in LLM format."""
        history = []
        for msg in self.messages:
            if msg.role == MessageRole.SYSTEM:
                history.append({"role": "system", "content": msg.content})
            elif msg.role == MessageRole.USER:
                history.append({"role": "user", "content": msg.content})
            elif msg.role == MessageRole.ASSISTANT:
                if msg.tool_calls:
                    # Message with tool calls
                    content = msg.content if msg.content else ""
                    tool_calls_data = []
                    for tc in msg.tool_calls:
                        tool_calls_data.append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments)
                            }
                        })
                    history.append({
                        "role": "assistant",
                        "content": content,
                        "tool_calls": tool_calls_data
                    })
                else:
                    history.append({"role": "assistant", "content": msg.content})
            elif msg.role == MessageRole.TOOL:
                history.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content
                })
        return history


class AgentEngine:
    """Engine for running AI agents with tool calling.

    Supports two modes:
    - MCP mode (default): Uses real MCP server via stdio transport
    - Direct mode: Uses in-process tool registry (fallback)
    """

    @staticmethod
    def _get_system_prompt() -> str:
        """Generate system prompt with dynamic app name."""
        app_name = get_app_name()
        # Note: Using string concatenation to avoid f-string brace escaping issues
        # since the prompt contains many literal {{ and }} for template examples
        return "あなたは" + app_name + """の運用エージェントです。
MCPツールを使用してプロンプト、ワークフロー、データセットを管理します。

## ⚡ 必須: ワークフロー作成前にhelpを確認

**ワークフローを作成・編集する前に、必ず以下を実行してください：**

```python
help(topic="workflow")    # ステップタイプ、変数構文、演算子
help(topic="functions")   # calc, format_choices等の関数
```

これを省略すると、変数構文エラー・関数エラーで失敗します。

## 🚫 絶対遵守ルール

1. **ステップ名は英語のみ** - 日本語は100%エラー
   - ✅ `generate_words`, `check_answer`  ❌ `問題文構築`, `回答抽出`

2. **condition_config, parser_config は辞書型** - JSON文字列は不可
   - ✅ `condition_config={"assignments": {"x": "0"}}`
   - ❌ `condition_config='{"assignments": {"x": "0"}}'`

3. **データセットIDは必ず確認** - 推測禁止
   - ✅ `search_datasets("名前")` → IDを確認してから使用

4. **FOREACH/IFブロックはペアで閉じる** - 専用ツールを使用
   - ✅ `add_foreach_block`, `add_if_block` （自動でペア作成）

5. **FOREACH変数は必ず `{{vars.ROW.column}}` で参照**
   - ✅ `{{vars.ROW.answerKey}}`  ❌ `{{ROW.answerKey}}`

6. **カウンタ加算は `calc()` 必須**
   - ✅ `calc({{vars.correct}} + 1)`  ❌ `{{vars.correct}} + 1`

7. **`output` ステップは存在しない** - 結果は `set` で変数に格納
   - ✅ `step_type="set", condition_config={"assignments": {"result": "..."}}`

8. **choices等のJSONは `format_choices()` で整形**
   - ✅ `format_choices({{vars.ROW.choices}})`

9. **ワークフロー作成後は必ずテスト** - `help(topic="validation")` 参照
   - ✅ `validate_workflow` (エラー0件必須) → `execute_workflow`
   - ⚠️ **validate_workflow が成功(エラー0件)しないと execute_workflow は実行不可**

## 🔄 ワークフロー/プロンプトの作成 vs 修正の判断

**ユーザーが「修正」「更新」「変更」「直して」と言った場合:**

1. **まず既存リソースを確認**
   - ワークフロー → `list_workflows()` で検索、または `get_workflow(id)` で確認
   - プロンプト → `list_prompts()` で検索

2. **既存が見つかった場合 → 更新ツールを使用**
   - ワークフロー修正 → `update_workflow`, `update_workflow_step`, `add_workflow_step`
   - プロンプト修正 → `update_prompt`

3. **存在しない場合のみ作成**
   - `create_workflow`, `create_prompt`

**よくある間違い:**
- ❌ 「修正」と言われたのに `create_workflow` を呼ぶ → 重複ワークフローが発生
- ✅ 「修正」なら `get_workflow` → `update_workflow_step` / `add_workflow_step`

## 📚 MCPツール一覧（49個）

| カテゴリ | 主要ツール |
|---------|-----------|
| project | list_projects, get_project, create_project, update_project, delete_project, delete_projects |
| prompt | list_prompts, get_prompt, create_prompt, update_prompt, delete_prompt, **clone_prompt** |
| workflow | create_workflow, add_workflow_step, add_foreach_block, add_if_block, remove_workflow_step, get_workflow, list_workflows, validate_workflow, **clone_workflow** |
| execution | execute_prompt, execute_workflow |
| job | get_job_status, list_recent_jobs, download_job_csv |
| dataset | list_datasets, get_dataset, preview_dataset_rows, search_datasets |
| huggingface | import_huggingface_dataset, list_huggingface_datasets, search_huggingface |
| system | list_models, get_system_settings |
| **help** | **help()** でツール・ルールのヘルプを表示 |

**「〜を実行して」と言われたら `help(topic="execution")` を確認してから対応**

## 💡 helpツールの使い方

```python
help()                              # 全ツール・トピック一覧
help(topic="workflow")              # ステップタイプ、変数、演算子
help(topic="functions")             # 35個の関数 (calc, dataset_filter, dataset_join等)
help(topic="prompt")                # プロンプトテンプレート構文
help(topic="parser")                # パーサー設定 (json, regex等)
help(topic="dataset_ref")           # データセット参照構文
help(topic="functions", entry="dataset_filter")  # dataset_filter 関数の詳細
```

## 🔧 基本ワークフロー構築手順

1. **help(topic="workflow") と help(topic="functions") を確認**
2. `create_workflow` でワークフロー作成
3. `add_workflow_step` で `set` ステップ（変数初期化）
4. `add_foreach_block` でループ開始（自動でENDFOREACH追加）
5. `add_workflow_step` で `prompt` ステップ（LLM呼び出し）
6. `add_if_block` で条件分岐（自動でELSE/ENDIF追加）
7. `insert_after` パラメータで挿入位置を指定
8. 最終結果は `set` ステップで変数に格納

### 重要ポイント
- `insert_after` で挿入位置を指定（step_orderより安全）
- `current_structure` でステップ構成を確認
- **promptステップにはinput_mapping必須** - これがないとプロンプトのパラメータが空になる
  - ✅ `input_mapping={"QUESTION": "{{vars.ROW.question}}"}`
- **パーサーを使う場合、プロンプトで出力形式を指示**
  - JSONパーサー → 「JSON形式で出力してください」と指示
  - 正規表現パーサー → 抽出対象の形式で出力するよう指示

## 🔧 既存ワークフローの修正手順

1. `list_workflows()` または `get_workflow(id)` で対象を特定
2. 構造を確認し、修正が必要な箇所を特定
3. 適切なツールを選択:

| 修正内容 | 使用ツール |
|---------|-----------|
| 名前・説明変更 | `update_workflow` |
| ステップ追加 | `add_workflow_step`, `add_foreach_block`, `add_if_block` |
| ステップ変更 | `update_workflow_step` |
| ステップ削除 | `delete_workflow_step` |
| プロンプト修正 | `update_prompt` (プロンプト側を修正) |

4. `validate_workflow` で検証

**注意**: 既存ワークフローの構造を変更する場合でも、`create_workflow` は使用しない

## 📋 プロンプトテンプレート vs ワークフロー変数

**重要**: プロンプトテンプレートとワークフロー変数は異なる構文を使用します。

| コンテキスト | 構文 | 例 |
|-------------|------|-----|
| プロンプトテンプレート | `{{PARAM}}` | `{{QUESTION}}`, `{{CHOICES}}` |
| ワークフロー (input_mapping, set等) | `{{vars.ROW.xxx}}`, `{{ステップ名.xxx}}` | `{{vars.ROW.question}}`, `{{ask.ANSWER}}` |

**よくある間違い**:
- ❌ プロンプトテンプレート: `{{vars.ROW.question}}`
- ✅ プロンプトテンプレート: `{{QUESTION}}` + input_mapping: `{"QUESTION": "{{vars.ROW.question}}"}`

**迷ったら**: `help(topic="prompt")` と `help(topic="workflow", entry="input_mapping")` を確認

## 🔴 よくあるエラーと対処

| エラー | 原因 | 対処 |
|--------|------|------|
| Unclosed block | endforeach/endifが不足 | `add_foreach_block`/`add_if_block`を使用 |
| Invalid step_type | 未知のステップタイプ | `help(topic="workflow")` で確認 |
| Unknown function | 未知の関数名 | `help(topic="functions")` で確認 |
| 変数が空 | `{{ROW.x}}`を使用 | `{{vars.ROW.x}}`に修正 |
| 計算されない | calc()を使っていない | `calc(式)` で囲む |
| プロンプトパラメータが空 | input_mappingがない or キー不一致 | `help(topic="workflow", entry="input_mapping")` を参照 |
| パーサーが抽出できない | LLM出力が形式に合わない | プロンプトで出力形式を明示的に指示 |
| テンプレートで{{vars.xxx}} | テンプレート構文の誤り | `help(topic="prompt")`で確認。テンプレートは`{{PARAM}}`、値は`input_mapping`で渡す |
| parsed.xxx が undefined | パーサーフィールド名の大文字小文字不一致 | `help(topic="workflow", entry="case_sensitivity")` を参照 |
| 同名WFが複数存在 | 修正時に新規作成した | `list_workflows`で確認、不要なものを`delete_workflow` |
| 修正したのに反映されない | 別のWF IDを操作した | `get_workflow(id)`で確認してから修正 |
| 関数チェーンエラー | `json_parse(x).field`形式を使用 | `help(topic="workflow", entry="common_mistakes")` を参照 |

## 🔤 大文字小文字の厳密なルール（重要）

**大文字小文字は常に厳密に一致させる必要があります。不一致は動作しません。**

| 定義場所 | 参照方法 | 例 |
|---------|----------|-----|
| パーサー | ステップ参照 | パーサー: `{"ANSWER": "[A-D]"}` → 参照: `{{ask.ANSWER}}` (askはステップ名、大文字で一致) |
| プロンプト | input_mapping | プロンプト: `{{QUESTION}}` → input_mapping: `{"QUESTION": "..."}` (大文字で一致) |
| FOREACH | 変数参照 | item_var: `"ROW"` → 参照: `{{vars.ROW.column}}` (ROWは大文字固定) |

**よくある間違い:**
- ❌ パーサー `{"ANSWER": ...}` に対して `{{ask.answer}}` (小文字)
- ✅ パーサー `{"ANSWER": ...}` に対して `{{ask.ANSWER}}` (大文字で一致、askはステップ名)
- ❌ プロンプト `{{QUESTION}}` に対して `input_mapping: {"question": ...}` (小文字)
- ✅ プロンプト `{{QUESTION}}` に対して `input_mapping: {"QUESTION": ...}` (大文字で一致)

## 🔍 プロンプトステップ作成前チェックリスト

promptステップを作成する前に、必ず以下を確認してください:

1. **プロンプトテンプレートを確認**: `{{PARAM}}` 形式のパラメータ名をすべて確認
2. **input_mappingでキーを一致させる**: プロンプトのパラメータ名と完全一致（大文字小文字含む）
3. **パーサーフィールド名を確認**: パーサーで定義した名前で後続ステップから参照
4. **テンプレートにワークフロー変数を直接書かない**: `{{vars.xxx}}` はinput_mappingで渡す

**例:**
```
プロンプトテンプレート: "質問: {{QUESTION}}\n選択肢: {{CHOICES}}"
↓
input_mapping: {"QUESTION": "{{vars.ROW.question}}", "CHOICES": "format_choices({{vars.ROW.choices}})"}
```

## 📝 変数参照構文

```
{{input.param}}             - 初期入力パラメータ
{{vars.name}}               - ワークフロー変数
{{ステップ名.field}}        - ステップ出力 (例: {{ask.text}})
{{ステップ名.parsed.FIELD}} - パースされた出力 (例: {{ask.ANSWER}})
{{vars.ROW.column}}         - FOREACHの現在行カラム (vars必須!)
```

**注意**: `step`はキーワードではありません。実際のステップ名を使用してください。
例: ステップ名が `ask` なら `{{ask.ANSWER}}`、ステップ名が `generate` なら `{{generate.text}}`

## ⚠️ エラー発生時のhelp参照ルール

エラーが発生したら、**必ず対応するhelpを参照**してから修正を試みてください:

| エラーの種類 | 参照するhelp |
|-------------|-------------|
| プロンプトパラメータが空/不正 | `help(topic="prompt")`, `help(topic="workflow", entry="input_mapping")` |
| 変数構文エラー | `help(topic="workflow", entry="variables")` |
| 関数エラー | `help(topic="functions")` |
| ステップタイプエラー | `help(topic="workflow")` |
| パーサー抽出失敗 | `help(topic="parser", entry="prompt_design")` |

**手順**:
1. エラーメッセージを読む
2. 対応するhelpを呼び出して正しい構文を確認
3. helpの例に従って修正

## 🆘 ユーザーからの「help参照」指示への対応

ユーザーが「helpを参照して」「helpを見て」「helpで確認して」と指示した場合:

1. **必ず help() ツールを呼び出す** - デフォルトメッセージを返さない
2. 適切なトピックを選択:
   - プロンプト関連 → `help(topic="prompt")`
   - ワークフロー関連 → `help(topic="workflow")`
   - input_mapping関連 → `help(topic="workflow", entry="input_mapping")`
   - 関数関連 → `help(topic="functions")`
3. helpの内容を参照して問題を解決する

**例**:
- ユーザー: 「input_mappingが空なので値が入らない。helpを参照して」
- エージェント: `help(topic="workflow", entry="input_mapping")` を呼び出し → 結果を基に修正提案

## ⚠️ その他の注意事項

- **ワークフロー作成前に help(topic="workflow") と help(topic="functions") を必ず確認**
- URLはプレーンテキストで出力（Markdown形式禁止）

バックアップ: backend/agent/system_prompt_backup.py に旧プロンプトを保存済み"""

    def __init__(
        self,
        model_name: str = None,
        temperature: float = 0.7,
        use_mcp: bool = True,
        use_intent_v2: bool = True,
        intent_classifier_model: str = "openai-gpt-4.1-nano",
        use_guardrail_chain: bool = True,
        guardrail_model: str = None,
    ):
        """Initialize the agent engine.

        Args:
            model_name: LLM model to use for agent responses
            temperature: Temperature for LLM
            use_mcp: Whether to use real MCP server (True) or direct tool registry (False)
            use_intent_v2: Whether to use new LLM-based intent classification (True)
                          or legacy rule-based only (False)
            intent_classifier_model: Model to use for intent classification
                                    (e.g., 'openai-gpt-4.1-nano', 'azure-gpt-5-nano')
            use_guardrail_chain: Whether to use multi-stage LLM guardrail chain
            guardrail_model: Model for guardrail checks (uses system setting if None)
        """
        self.use_mcp = use_mcp
        self.use_intent_v2 = use_intent_v2
        self.use_guardrail_chain = use_guardrail_chain
        self.tool_registry = get_tool_registry()  # Keep for fallback and tool schema
        self.mcp_client: Optional[MCPClient] = MCPClient() if use_mcp else None
        self.model_name = model_name or self._get_default_model()
        self.temperature = temperature
        self.sessions: Dict[str, AgentSession] = {}
        self.policy_layer = get_policy_layer()  # Security policy layer
        self.event_callback: Optional[callable] = None  # Callback for real-time event streaming

        # Multi-stage LLM guardrail chain
        if use_guardrail_chain:
            self.guardrail_chain = get_guardrail_chain(guardrail_model)
            logger.info(f"[Agent] Using guardrail chain with model: {self.guardrail_chain.model_name}")
        else:
            self.guardrail_chain = None
            logger.info("[Agent] Guardrail chain disabled")

        # Intent extraction layer (v2 = LLM-based + hierarchical, v1 = rule-based only)
        if use_intent_v2:
            self.intent_extractor_v2 = get_intent_extractor_v2(
                classifier_model=intent_classifier_model,
                use_llm=True,
            )
            self.intent_extractor = None  # Not used in v2 mode
            logger.info(f"[Agent] Using intent v2 with classifier: {intent_classifier_model}")
        else:
            self.intent_extractor = get_intent_extractor()  # Legacy
            self.intent_extractor_v2 = None
            logger.info("[Agent] Using legacy intent extractor (rule-based only)")

    def _get_default_model(self) -> str:
        """Get default model from system settings."""
        db = SessionLocal()
        try:
            setting = db.query(SystemSetting).filter(
                SystemSetting.key == "active_llm_model"
            ).first()
            return setting.value if setting else "claude-3.5-sonnet"
        finally:
            db.close()

    def _get_max_iterations(self) -> int:
        """Get max iterations from system settings."""
        db = SessionLocal()
        try:
            setting = db.query(SystemSetting).filter(
                SystemSetting.key == "agent_max_iterations"
            ).first()
            if setting and setting.value:
                try:
                    max_iter = int(setting.value)
                    # Clamp to valid range (10-99)
                    return max(10, min(max_iter, 99))
                except ValueError:
                    pass
            return 30  # Default value
        finally:
            db.close()

    def _get_max_tokens(self) -> int:
        """Get max completion tokens from system settings.

        Reasoning models (GPT-5, o4-mini) use many tokens for internal
        thinking before generating output. If agents return empty responses
        with finish_reason=length, this value needs to be increased.
        """
        db = SessionLocal()
        try:
            setting = db.query(SystemSetting).filter(
                SystemSetting.key == "agent_max_tokens"
            ).first()
            if setting and setting.value:
                try:
                    max_tokens = int(setting.value)
                    # Clamp to valid range (1024-65536)
                    return max(1024, min(max_tokens, 65536))
                except ValueError:
                    pass
            return 16384  # Default value for reasoning models
        finally:
            db.close()

    def _get_llm_timeout(self) -> float:
        """Get LLM API timeout from system settings.

        Controls how long to wait for OpenAI API responses before timing out.
        Default is 600 seconds (10 minutes) to handle slow API responses.
        """
        db = SessionLocal()
        try:
            setting = db.query(SystemSetting).filter(
                SystemSetting.key == "agent_llm_timeout"
            ).first()
            if setting and setting.value:
                try:
                    timeout = int(setting.value)
                    # Clamp to valid range (60-1800 seconds = 1-30 minutes)
                    return float(max(60, min(timeout, 1800)))
                except ValueError:
                    pass
            return 600.0  # Default: 10 minutes
        finally:
            db.close()

    def create_session(self, session_id: str = None,
                       model_name: str = None,
                       temperature: float = None,
                       max_iterations: int = None) -> AgentSession:
        """Create a new agent session.

        Args:
            session_id: Session identifier (auto-generated if not provided)
            model_name: LLM model to use
            temperature: LLM temperature
            max_iterations: Maximum iterations (overrides system setting if provided)
        """
        if session_id is None:
            session_id = f"agent_{int(time.time() * 1000)}"

        # Get max_iterations from parameter or system settings
        if max_iterations is None:
            max_iterations = self._get_max_iterations()
        else:
            # Clamp to valid range
            max_iterations = max(10, min(max_iterations, 99))

        session = AgentSession(
            id=session_id,
            model_name=model_name or self.model_name,
            temperature=temperature if temperature is not None else self.temperature,
            max_iterations=max_iterations
        )

        # Add system prompt
        session.add_message(AgentMessage(
            role=MessageRole.SYSTEM,
            content=self._get_system_prompt()
        ))

        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        """Get an existing session."""
        return self.sessions.get(session_id)

    def _emit_event(self, event_type: str, message: str, data: Optional[Dict] = None) -> None:
        """Emit an event to the callback if registered."""
        if self.event_callback:
            try:
                self.event_callback(event_type, message, data)
            except Exception as e:
                logger.warning(f"Event callback error: {e}")

    async def run(self, session: AgentSession, user_message: str) -> str:
        """Run the agent with a user message.

        Args:
            session: The agent session
            user_message: The user's message

        Returns:
            The agent's final response
        """
        # Check if session is terminated (security guardrail)
        if session.terminated:
            return "このセッションはセキュリティ上の理由により終了しています。新しいセッションを開始してください。"

        # MULTI-STAGE LLM GUARDRAIL CHAIN (runs BEFORE intent extraction)
        if self.use_guardrail_chain and self.guardrail_chain:
            # Build conversation history for security check
            conversation_history = self._get_recent_conversation_text(session, limit=5)

            guardrail_result = self.guardrail_chain.check(
                user_message=user_message,
                conversation_history=conversation_history
            )

            logger.info(
                f"[Guardrail] Session {session.id}: passed={guardrail_result.passed}, "
                f"latency={guardrail_result.total_latency_ms}ms"
            )

            if not guardrail_result.passed:
                # Guardrail rejected the request
                rejection_message = guardrail_result.rejection_message

                # Log stage results for debugging
                for stage_result in guardrail_result.stage_results:
                    logger.info(
                        f"[Guardrail] Stage {stage_result.stage.value}: "
                        f"{stage_result.decision.value} - {stage_result.reason}"
                    )

                # Handle session termination (security threat)
                if guardrail_result.terminate_session:
                    session.terminated = True
                    session.status = "terminated"
                    logger.warning(f"[Guardrail] Session {session.id} TERMINATED due to security threat")

                # Add messages to session
                session.add_message(AgentMessage(
                    role=MessageRole.USER,
                    content=user_message
                ))
                session.add_message(AgentMessage(
                    role=MessageRole.ASSISTANT,
                    content=rejection_message
                ))

                return rejection_message

        # Use intent v2 (LLM-based) or legacy (rule-based only)
        if self.use_intent_v2:
            return await self._run_with_intent_v2(session, user_message)
        else:
            return await self._run_with_legacy_intent(session, user_message)

    def _get_recent_conversation_text(self, session: AgentSession, limit: int = 5) -> str:
        """Get recent conversation as text for security check."""
        recent_messages = []
        count = 0
        for msg in reversed(session.messages):
            if msg.role in (MessageRole.USER, MessageRole.ASSISTANT):
                role_label = "User" if msg.role == MessageRole.USER else "Assistant"
                recent_messages.append(f"{role_label}: {msg.content[:500]}")
                count += 1
                if count >= limit:
                    break
        recent_messages.reverse()
        return "\n".join(recent_messages) if recent_messages else "(会話履歴なし)"

    async def _run_with_intent_v2(self, session: AgentSession, user_message: str) -> str:
        """Run agent with new LLM-based intent classification (v2).

        Intent v2 handles security filtering internally with SecurityPreFilter.
        """
        # Build conversation history for context-aware intent classification
        conversation_history = self._get_recent_conversation_text(session, limit=5)

        # INTENT EXTRACTION v2: Security + LLM-based classification + Rule fallback
        intent = self.intent_extractor_v2.extract(user_message, conversation_history)

        logger.info(
            f"[Intent-v2] Session {session.id}: "
            f"domain={intent.domain.value}, action={intent.action.value}, "
            f"confidence={intent.confidence:.2f}, method={intent.classification_method}, "
            f"permission={intent.permission_level.value}"
        )

        # Check if intent is allowed
        if not intent.is_allowed():
            # Out-of-scope or security threat - reject immediately
            rejection_response = self.intent_extractor_v2.get_rejection_message(intent)
            logger.info(f"[Intent-v2] Rejected request in session {session.id}: {intent.domain.value}")
            session.add_message(AgentMessage(
                role=MessageRole.USER,
                content=user_message
            ))
            session.add_message(AgentMessage(
                role=MessageRole.ASSISTANT,
                content=rejection_response
            ))
            return rejection_response

        # HELP intent: LLMに処理させてhelp MCPツールを呼び出せるようにする
        # ユーザーが「helpを参照して」と言った場合、help() ツールを呼び出すために
        # 通常のLLM処理フローに移行させる（特別扱いを削除）
        # Note: 純粋なhelp質問（「何ができる？」など）もLLMが適切に処理する

        # Handle CONFIRM action - auto-execute confirmed tool immediately
        if intent.action == Action.CONFIRM:
            logger.info(f"[Intent-v2] Confirmation detected in session {session.id}: {intent.parameters}")
            pending = self.policy_layer.get_pending_confirmation(session.id)

            if pending and intent.parameters.get("confirmed", True):
                tool_name, arguments = pending

                # Clear pending confirmation first
                self.policy_layer.clear_pending_confirmation(session.id)

                # Add user message
                session.add_message(AgentMessage(
                    role=MessageRole.USER,
                    content=user_message
                ))

                # AUTO-EXECUTE the confirmed tool immediately (bypass LLM loop)
                logger.info(f"[Intent-v2] Auto-executing confirmed tool: {tool_name}")
                self._emit_event("tool_start", f"確認済みツール実行中: {tool_name}", {
                    "tool_name": tool_name,
                    "arguments": arguments
                })

                try:
                    if self.use_mcp and self.mcp_client:
                        # Establish MCP connection for confirmed tool execution
                        async with self.mcp_client.connect():
                            result = await self.mcp_client.call_tool(tool_name, arguments)
                    else:
                        tool_context = {"default_model": session.model_name}
                        result = await self.tool_registry.execute_tool(
                            tool_name, arguments, context=tool_context
                        )

                    self._emit_event("tool_end", f"ツール完了: {tool_name}", {
                        "tool_name": tool_name,
                        "success": result.get("success", False) if isinstance(result, dict) else True
                    })

                    # Format and return result
                    if isinstance(result, dict) and result.get("success"):
                        response = f"実行完了: {tool_name}\n結果: {json.dumps(result.get('result', result), ensure_ascii=False, indent=2)}"
                    else:
                        error = result.get("error", "Unknown error") if isinstance(result, dict) else str(result)
                        response = f"実行失敗: {tool_name}\nエラー: {error}"

                except Exception as e:
                    logger.error(f"[Intent-v2] Error executing confirmed tool: {e}", exc_info=True)
                    response = f"実行エラー: {tool_name}\nエラー: {str(e)}"

                session.add_message(AgentMessage(
                    role=MessageRole.ASSISTANT,
                    content=response
                ))
                session.status = "completed"
                return response

            elif pending and not intent.parameters.get("confirmed", True):
                # User said "no" - clear pending and inform
                self.policy_layer.clear_pending_confirmation(session.id)
                session.add_message(AgentMessage(
                    role=MessageRole.USER,
                    content=user_message
                ))
                response = "操作をキャンセルしました。"
                session.add_message(AgentMessage(
                    role=MessageRole.ASSISTANT,
                    content=response
                ))
                return response

        # Add user message
        session.add_message(AgentMessage(
            role=MessageRole.USER,
            content=user_message
        ))

        # Store intent in session for potential use by tools
        session.current_intent = intent

        # Get LLM client
        client = get_llm_client(session.model_name)

        # Run with MCP or direct mode
        if self.use_mcp and self.mcp_client:
            response = await self._run_with_mcp(session, client)
        else:
            response = await self._run_direct(session, client)

        # Apply output filter to prevent system prompt leakage
        filtered_response, was_filtered = self.policy_layer.filter_output(response, user_message)
        if was_filtered:
            logger.warning(f"Output filtered for session {session.id}")
            if session.messages and session.messages[-1].role == MessageRole.ASSISTANT:
                session.messages[-1].content = filtered_response

        return filtered_response

    async def _run_with_legacy_intent(self, session: AgentSession, user_message: str) -> str:
        """Run agent with legacy rule-based intent classification (v1)."""
        # SECURITY: Input filtering at the entry point (BEFORE LLM sees anything)
        # This is the PRIMARY security gate - if blocked here, LLM never sees the request
        should_block, rejection_msg, category = self.policy_layer.filter_user_input(user_message)

        if should_block:
            logger.warning(f"[Security] Blocked input in session {session.id}, category: {category.value}")
            session.add_message(AgentMessage(
                role=MessageRole.USER,
                content=user_message
            ))
            session.add_message(AgentMessage(
                role=MessageRole.ASSISTANT,
                content=rejection_msg
            ))
            return rejection_msg

        # INTENT EXTRACTION: Determine if request is within scope (WITHOUT LLM)
        # Only system operation requests are allowed; all others are rejected immediately
        intent = self.intent_extractor.extract(user_message)
        logger.info(f"[Intent] Session {session.id}: type={intent.intent_type.value}, "
                   f"confidence={intent.confidence:.2f}, keywords={intent.matched_keywords}")

        if not self.intent_extractor.is_allowed(intent):
            # Out-of-scope request - reject immediately without LLM
            rejection_response = self.intent_extractor.get_rejection_message(intent)
            logger.info(f"[Intent] Rejected out-of-scope request in session {session.id}")
            session.add_message(AgentMessage(
                role=MessageRole.USER,
                content=user_message
            ))
            session.add_message(AgentMessage(
                role=MessageRole.ASSISTANT,
                content=rejection_response
            ))
            return rejection_response

        # Handle HELP intent directly (no LLM needed)
        if intent.intent_type == IntentType.HELP:
            help_response = self.intent_extractor.get_help_message()
            logger.info(f"[Intent] Providing help response in session {session.id}")
            session.add_message(AgentMessage(
                role=MessageRole.USER,
                content=user_message
            ))
            session.add_message(AgentMessage(
                role=MessageRole.ASSISTANT,
                content=help_response
            ))
            return help_response

        # Add user message
        session.add_message(AgentMessage(
            role=MessageRole.USER,
            content=user_message
        ))

        # Get LLM client
        client = get_llm_client(session.model_name)

        # Run with MCP or direct mode
        if self.use_mcp and self.mcp_client:
            response = await self._run_with_mcp(session, client)
        else:
            response = await self._run_direct(session, client)

        # Apply output filter to prevent system prompt leakage
        filtered_response, was_filtered = self.policy_layer.filter_output(response, user_message)
        if was_filtered:
            logger.warning(f"Output filtered for session {session.id}")
            # Update the last assistant message with filtered content
            if session.messages and session.messages[-1].role == MessageRole.ASSISTANT:
                session.messages[-1].content = filtered_response

        return filtered_response

    async def _run_with_mcp(self, session: AgentSession, client) -> str:
        """Run agent loop using real MCP server.

        Tools are executed via MCP protocol (stdio transport, JSON-RPC).
        """
        logger.info("Running agent in MCP mode")

        async with self.mcp_client.connect():
            # Set default model for execute_workflow/execute_prompt
            if session.model_name:
                logger.info(f"[MCP] Setting default model to: {session.model_name}")
                await self.mcp_client.call_tool("set_default_model", {"model_name": session.model_name})

            # Get tool schemas from MCP server
            mcp_tools = await self.mcp_client.list_tools()

            # Convert to OpenAI function calling format
            tools = []
            for tool in mcp_tools:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["inputSchema"]
                    }
                })

            # Run agent loop
            while session.current_iteration < session.max_iterations:
                session.current_iteration += 1
                self._emit_event("iteration", f"イテレーション {session.current_iteration}/{session.max_iterations}", {
                    "current": session.current_iteration,
                    "max": session.max_iterations
                })

                # Build messages for LLM
                messages = session.get_conversation_history()

                # Call LLM with tools
                self._emit_event("llm_call", "LLMに問い合わせ中...")
                response = await self._call_llm_with_tools(
                    client, messages, tools, session.temperature
                )

                if response is None:
                    session.status = "error"
                    self._emit_event("error", "LLMからの応答取得に失敗しました")
                    return "Error: Failed to get response from LLM"

                # Check if we have tool calls
                if response.get("tool_calls"):
                    # Process tool calls
                    assistant_msg = AgentMessage(
                        role=MessageRole.ASSISTANT,
                        content=response.get("content", ""),
                        tool_calls=[]
                    )

                    for tc in response["tool_calls"]:
                        tool_call = ToolCall(
                            id=tc["id"],
                            name=tc["function"]["name"],
                            arguments=json.loads(tc["function"]["arguments"])
                        )

                        # Policy Layer evaluation before execution
                        policy_result = self.policy_layer.evaluate(
                            tool_call.name,
                            tool_call.arguments,
                            session.id
                        )

                        if policy_result.decision == PolicyDecision.DENY:
                            # Tool execution denied by policy
                            logger.warning(f"[Policy] DENIED tool: {tool_call.name} - {policy_result.reason}")
                            tool_call.result = {
                                "success": False,
                                "error": f"Policy denied: {policy_result.reason}",
                                "policy_decision": "denied"
                            }
                        elif policy_result.decision == PolicyDecision.NEEDS_CONFIRMATION:
                            # Tool requires user confirmation - return confirmation request
                            logger.info(f"[Policy] Tool {tool_call.name} needs user confirmation")
                            # Store pending confirmation in policy layer (persists across requests)
                            self.policy_layer.set_pending_confirmation(
                                session.id, tool_call.name, tool_call.arguments
                            )
                            confirmation_prompt = self.policy_layer.get_confirmation_prompt(
                                tool_call.name, tool_call.arguments
                            )
                            tool_call.result = {
                                "success": False,
                                "error": "User confirmation required",
                                "policy_decision": "needs_confirmation",
                                "confirmation_prompt": confirmation_prompt
                            }
                            # Add tool call to message history before returning
                            assistant_msg.tool_calls.append(tool_call)
                            session.add_message(assistant_msg)
                            session.add_message(AgentMessage(
                                role=MessageRole.TOOL,
                                content=json.dumps(tool_call.result, ensure_ascii=False),
                                tool_call_id=tool_call.id
                            ))
                            # Exit loop and return confirmation prompt to user
                            session.status = "waiting_confirmation"
                            return confirmation_prompt
                        else:
                            # Tool execution allowed
                            logger.info(f"[MCP] Executing tool: {tool_call.name} with args: {tool_call.arguments}")
                            self._emit_event("tool_start", f"ツール実行中: {tool_call.name}", {
                                "tool_name": tool_call.name,
                                "arguments": tool_call.arguments
                            })
                            result = await self.mcp_client.call_tool(
                                tool_call.name,
                                tool_call.arguments
                            )
                            # Wrap tool output as untrusted content for LLM
                            tool_call.result = result
                            self._emit_event("tool_end", f"ツール完了: {tool_call.name}", {
                                "tool_name": tool_call.name,
                                "success": result.get("success", False) if isinstance(result, dict) else True
                            })

                        assistant_msg.tool_calls.append(tool_call)

                    session.add_message(assistant_msg)

                    # Add tool results as messages
                    for tc in assistant_msg.tool_calls:
                        session.add_message(AgentMessage(
                            role=MessageRole.TOOL,
                            content=json.dumps(tc.result, ensure_ascii=False),
                            tool_call_id=tc.id
                        ))

                else:
                    # No tool calls - final response
                    final_content = response.get("content", "")
                    self._emit_event("llm_response", "LLMからの応答を受信しました", {
                        "response_length": len(final_content)
                    })
                    session.add_message(AgentMessage(
                        role=MessageRole.ASSISTANT,
                        content=final_content
                    ))
                    session.status = "completed"
                    return final_content

            # Max iterations reached
            session.status = "completed"
            self._emit_event("max_iterations", "最大イテレーション数に達しました")
            return "I've reached the maximum number of steps. Please let me know if you'd like me to continue."

    async def _run_direct(self, session: AgentSession, client) -> str:
        """Run agent loop using direct tool registry (fallback mode).

        Tools are executed directly in-process without MCP protocol.
        """
        logger.info("Running agent in direct mode (fallback)")

        # Run agent loop
        while session.current_iteration < session.max_iterations:
            session.current_iteration += 1
            self._emit_event("iteration", f"イテレーション {session.current_iteration}/{session.max_iterations}", {
                "current": session.current_iteration,
                "max": session.max_iterations
            })

            # Build messages for LLM
            messages = session.get_conversation_history()

            # Get tool schemas from local registry
            tools = self.tool_registry.get_tools_json_schema()

            # Call LLM with tools
            self._emit_event("llm_call", "LLMに問い合わせ中...")
            response = await self._call_llm_with_tools(
                client, messages, tools, session.temperature
            )

            if response is None:
                session.status = "error"
                self._emit_event("error", "LLMからの応答取得に失敗しました")
                return "Error: Failed to get response from LLM"

            # Check if we have tool calls
            if response.get("tool_calls"):
                # Process tool calls
                assistant_msg = AgentMessage(
                    role=MessageRole.ASSISTANT,
                    content=response.get("content", ""),
                    tool_calls=[]
                )

                for tc in response["tool_calls"]:
                    tool_call = ToolCall(
                        id=tc["id"],
                        name=tc["function"]["name"],
                        arguments=json.loads(tc["function"]["arguments"])
                    )

                    # Policy Layer evaluation before execution
                    policy_result = self.policy_layer.evaluate(
                        tool_call.name,
                        tool_call.arguments,
                        session.id
                    )

                    if policy_result.decision == PolicyDecision.DENY:
                        # Tool execution denied by policy
                        logger.warning(f"[Policy] DENIED tool: {tool_call.name} - {policy_result.reason}")
                        tool_call.result = {
                            "success": False,
                            "error": f"Policy denied: {policy_result.reason}",
                            "policy_decision": "denied"
                        }
                    elif policy_result.decision == PolicyDecision.NEEDS_CONFIRMATION:
                        # Tool requires user confirmation
                        logger.info(f"[Policy] Tool {tool_call.name} needs user confirmation")
                        # Store pending confirmation in policy layer (persists across requests)
                        self.policy_layer.set_pending_confirmation(
                            session.id, tool_call.name, tool_call.arguments
                        )
                        confirmation_prompt = self.policy_layer.get_confirmation_prompt(
                            tool_call.name, tool_call.arguments
                        )
                        tool_call.result = {
                            "success": False,
                            "error": "User confirmation required",
                            "policy_decision": "needs_confirmation",
                            "confirmation_prompt": confirmation_prompt
                        }
                        # Add tool call to message history before returning
                        assistant_msg.tool_calls.append(tool_call)
                        session.add_message(assistant_msg)
                        session.add_message(AgentMessage(
                            role=MessageRole.TOOL,
                            content=json.dumps(tool_call.result, ensure_ascii=False),
                            tool_call_id=tool_call.id
                        ))
                        # Exit loop and return confirmation prompt to user
                        session.status = "waiting_confirmation"
                        return confirmation_prompt
                    else:
                        # Tool execution allowed
                        logger.info(f"[Direct] Executing tool: {tool_call.name} with args: {tool_call.arguments}")
                        self._emit_event("tool_start", f"ツール実行中: {tool_call.name}", {
                            "tool_name": tool_call.name,
                            "arguments": tool_call.arguments
                        })
                        # Pass session model as context so tools use the correct model
                        tool_context = {"default_model": session.model_name}
                        result = await self.tool_registry.execute_tool(
                            tool_call.name,
                            tool_call.arguments,
                            context=tool_context
                        )
                        tool_call.result = result
                        self._emit_event("tool_end", f"ツール完了: {tool_call.name}", {
                            "tool_name": tool_call.name,
                            "success": result.get("success", False) if isinstance(result, dict) else True
                        })

                    assistant_msg.tool_calls.append(tool_call)

                session.add_message(assistant_msg)

                # Add tool results as messages
                for tc in assistant_msg.tool_calls:
                    session.add_message(AgentMessage(
                        role=MessageRole.TOOL,
                        content=json.dumps(tc.result, ensure_ascii=False),
                        tool_call_id=tc.id
                    ))

            else:
                # No tool calls - final response
                final_content = response.get("content", "")
                self._emit_event("llm_response", "LLMからの応答を受信しました", {
                    "response_length": len(final_content)
                })
                session.add_message(AgentMessage(
                    role=MessageRole.ASSISTANT,
                    content=final_content
                ))
                session.status = "completed"
                return final_content

        # Max iterations reached
        session.status = "completed"
        self._emit_event("max_iterations", "最大イテレーション数に達しました")
        return "I've reached the maximum number of steps. Please let me know if you'd like me to continue."

    async def _call_llm_with_tools(self, client, messages: List[Dict],
                                   tools: List[Dict], temperature: float) -> Optional[Dict]:
        """Call LLM with tool support.

        This method handles the tool calling protocol for different LLM providers.
        """
        try:
            # For Claude models, we need to format differently
            if "claude" in client.__class__.__name__.lower() or "anthropic" in client.__class__.__name__.lower():
                return await self._call_claude_with_tools(client, messages, tools, temperature)
            else:
                # For OpenAI-compatible models
                return await self._call_openai_with_tools(client, messages, tools, temperature)
        except Exception as e:
            logger.error(f"Error calling LLM: {e}", exc_info=True)
            return None

    async def _call_claude_with_tools(self, client, messages: List[Dict],
                                      tools: List[Dict], temperature: float) -> Dict:
        """Call Claude with native tool use.

        Uses the passed client's anthropic SDK instance and model name.
        """
        # Convert tools to Claude format
        claude_tools = []
        for tool in tools:
            func = tool["function"]
            claude_tools.append({
                "name": func["name"],
                "description": func["description"],
                "input_schema": func["parameters"]
            })

        # Separate system message
        system_content = ""
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            elif msg["role"] == "tool":
                # Convert tool response to Claude format
                api_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": msg["content"]
                    }]
                })
            elif msg["role"] == "assistant" and msg.get("tool_calls"):
                # Convert tool calls to Claude format
                content = []
                if msg.get("content"):
                    content.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    content.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": json.loads(tc["function"]["arguments"])
                    })
                api_messages.append({"role": "assistant", "content": content})
            else:
                api_messages.append(msg)

        # Use the client's anthropic instance and model name
        # The client is an AnthropicClaudeClient with a 'client' attribute (anthropic.Anthropic)
        # and a MODEL_NAME attribute
        # Get max tokens from system settings
        max_tokens = self._get_max_tokens()
        response = client.client.messages.create(
            model=client.MODEL_NAME,
            max_tokens=max_tokens,
            system=system_content,
            messages=api_messages,
            tools=claude_tools,
            temperature=temperature
        )

        # Parse response
        result = {"content": "", "tool_calls": []}

        for block in response.content:
            if block.type == "text":
                result["content"] += block.text
            elif block.type == "tool_use":
                result["tool_calls"].append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input)
                    }
                })

        return result

    async def _call_openai_with_tools(self, client, messages: List[Dict],
                                       tools: List[Dict], temperature: float) -> Dict:
        """Call OpenAI-compatible API with native tool calling."""
        # Use native OpenAI tool calling API
        # The client has a .client attribute which is the OpenAI SDK client

        try:
            # Build API messages - convert our format to OpenAI format
            api_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    api_messages.append({"role": "system", "content": msg["content"]})
                elif msg["role"] == "user":
                    api_messages.append({"role": "user", "content": msg["content"]})
                elif msg["role"] == "assistant":
                    if msg.get("tool_calls"):
                        # Assistant message with tool calls
                        api_msg = {
                            "role": "assistant",
                            "content": msg.get("content") or None,
                            "tool_calls": [
                                {
                                    "id": tc["id"],
                                    "type": "function",
                                    "function": {
                                        "name": tc["function"]["name"],
                                        "arguments": tc["function"]["arguments"]
                                    }
                                }
                                for tc in msg["tool_calls"]
                            ]
                        }
                        api_messages.append(api_msg)
                    else:
                        api_messages.append({"role": "assistant", "content": msg.get("content", "")})
                elif msg["role"] == "tool":
                    api_messages.append({
                        "role": "tool",
                        "tool_call_id": msg["tool_call_id"],
                        "content": msg["content"]
                    })

            # Get model name from client
            model_name = getattr(client, 'MODEL_NAME', 'gpt-4o-mini')

            # Check if this is a GPT-5 or o4 model (fixed temperature, uses max_completion_tokens)
            is_fixed_temp_model = "gpt-5" in model_name or "o4-mini" in model_name or "o4" in model_name

            # Build API call parameters
            call_params = {
                "model": model_name,
                "messages": api_messages,
                "tools": tools,
            }

            # GPT-5/o4 models: fixed temperature=1, use max_completion_tokens
            # Other models: configurable temperature, use max_tokens
            # Note: Reasoning models (o4, gpt-5) need higher token limits because they
            # use many tokens for internal reasoning before generating output.
            # If finish_reason=length with 0 content, increase this value.
            # Get max tokens from system settings
            max_tokens = self._get_max_tokens()

            if is_fixed_temp_model:
                call_params["max_completion_tokens"] = max_tokens
                # Don't pass temperature - GPT-5/o4 only supports default (1.0)
            else:
                call_params["temperature"] = temperature
                call_params["max_tokens"] = max_tokens

            # Get LLM timeout from system settings
            llm_timeout = self._get_llm_timeout()

            # Call OpenAI API with native tool calling and timeout
            logger.info(f"[Agent] Calling OpenAI API with model={call_params.get('model')}, messages={len(call_params.get('messages', []))}, tools={len(call_params.get('tools', []))}, timeout={llm_timeout}s")
            response = client.client.chat.completions.create(**call_params, timeout=llm_timeout)

            # Debug: Log full response details
            logger.info(f"[Agent] OpenAI raw response: id={response.id}, model={response.model}, choices={len(response.choices)}")
            if response.choices:
                choice = response.choices[0]
                logger.info(f"[Agent] Choice[0]: finish_reason={choice.finish_reason}, content_len={len(choice.message.content) if choice.message.content else 0}, tool_calls={len(choice.message.tool_calls) if choice.message.tool_calls else 0}")

                # Check for refusal (o4-mini specific)
                if hasattr(choice.message, 'refusal') and choice.message.refusal:
                    logger.warning(f"[Agent] Model refused: {choice.message.refusal}")
                    return {"content": f"Model refused: {choice.message.refusal}", "tool_calls": []}
            else:
                logger.error(f"[Agent] No choices in response!")
                return {"content": "Error: No response from model", "tool_calls": []}

            # Parse response
            result = {"content": "", "tool_calls": []}

            if choice.message.content:
                result["content"] = choice.message.content

            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    result["tool_calls"].append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    })

            logger.info(f"[Agent] OpenAI response: content={len(result['content'])} chars, tool_calls={len(result['tool_calls'])}")
            return result

        except Exception as e:
            error_type = type(e).__name__
            # Check for timeout errors (openai.APITimeoutError or similar)
            if "Timeout" in error_type or "timeout" in str(e).lower():
                llm_timeout = self._get_llm_timeout()
                logger.error(f"[Agent] OpenAI API timeout after {llm_timeout}s: {e}")
                return {"content": f"Error: LLM API timeout ({llm_timeout}秒). システム設定でタイムアウト値を増やすか、再試行してください。", "tool_calls": []}
            logger.error(f"[Agent] OpenAI tool call error: {e}", exc_info=True)
            return {"content": f"Error: {str(e)}", "tool_calls": []}

    def run_sync(self, session: AgentSession, user_message: str) -> str:
        """Synchronous wrapper for run()."""
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.run(session, user_message))
        finally:
            loop.close()


# Convenience functions
def create_agent(model_name: str = None, temperature: float = 0.7) -> Tuple[AgentEngine, AgentSession]:
    """Create an agent engine and session.

    Returns:
        Tuple of (engine, session)
    """
    engine = AgentEngine(model_name=model_name, temperature=temperature)
    session = engine.create_session()
    return engine, session


async def run_agent(instruction: str, model_name: str = None,
                    temperature: float = 0.7) -> str:
    """Run an agent with a single instruction.

    Args:
        instruction: The task for the agent
        model_name: LLM model to use
        temperature: Temperature for LLM

    Returns:
        The agent's response
    """
    engine, session = create_agent(model_name, temperature)
    return await engine.run(session, instruction)

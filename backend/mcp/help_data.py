"""
MCP Help Tool Data - AIエージェント向けヘルプコンテンツ

このモジュールはhelpツールで使用するヘルプデータを定義します。
システム名は環境変数 APP_NAME で設定可能（デフォルト: PromptRig）
"""

import os
from typing import Dict, List, Any


def get_app_name() -> str:
    """Get application name from environment."""
    return os.getenv("APP_NAME", "PromptRig")

# =============================================================================
# ツールカテゴリ分類
# =============================================================================

TOOL_CATEGORIES: Dict[str, List[str]] = {
    "project": [
        "list_projects",
        "get_project",
        "create_project",
        "update_project",
        "delete_project",
        "delete_projects",
        "list_deleted_projects",
        "restore_project"
    ],
    "prompt": [
        "list_prompts",
        "get_prompt",
        "create_prompt",
        "update_prompt",
        "delete_prompt",
        "clone_prompt",
        "analyze_template",
        "set_parser_csvoutput"
    ],
    "workflow": [
        "list_workflows",
        "get_workflow",
        "create_workflow",
        "update_workflow",
        "delete_workflow",
        "clone_workflow",
        "add_workflow_step",
        "update_workflow_step",
        "delete_workflow_step",
        "add_foreach_block",
        "add_if_block",
        "validate_workflow",
        "get_available_variables",
        "list_deleted_workflows",
        "restore_workflow"
    ],
    "execution": [
        "execute_prompt",
        "execute_template",
        "execute_batch",
        "execute_workflow"
    ],
    "job": [
        "get_job_status",
        "list_recent_jobs",
        "cancel_job",
        "export_job_csv"
    ],
    "dataset": [
        "list_datasets",
        "get_dataset",
        "search_datasets",
        "search_dataset_content",
        "preview_dataset_rows",
        "execute_batch_with_filter",
        "get_dataset_projects",
        "update_dataset_projects",
        "add_dataset_to_project",
        "remove_dataset_from_project"
    ],
    "huggingface": [
        "search_huggingface_datasets",
        "get_huggingface_dataset_info",
        "preview_huggingface_dataset",
        "import_huggingface_dataset"
    ],
    "system": [
        "list_models",
        "get_system_settings",
        "set_default_model"
    ]
}

# カテゴリ説明
CATEGORY_DESCRIPTIONS: Dict[str, str] = {
    "project": "プロジェクト管理 - プロジェクトの作成・更新・削除",
    "prompt": "プロンプト管理 - プロンプトテンプレートの作成・編集",
    "workflow": "ワークフロー管理 - マルチステップワークフローの構築",
    "execution": "実行 - プロンプト・ワークフローの実行",
    "job": "ジョブ管理 - 実行ジョブの監視・制御",
    "dataset": "データセット管理 - データセットの検索・プレビュー",
    "huggingface": "Hugging Face連携 - データセットのインポート",
    "system": "システム - モデル・設定の取得"
}

# =============================================================================
# ルールトピック
# =============================================================================

HELP_TOPICS: Dict[str, Dict[str, Any]] = {
    # =========================================================================
    # execution トピック - 実行ツールの選び方
    # =========================================================================
    "execution": {
        "description": "実行ツールの選び方 - プロンプト実行 vs ワークフロー実行",
        "overview": """ユーザーが「〇〇を実行して」と言った場合の対応手順:

1. まず list_prompts() でプロンプト名を検索
2. 見つかれば execute_prompt(prompt_id, input_params) で実行
3. なければ list_workflows() でワークフロー名を検索
4. 見つかれば execute_workflow(workflow_id, input_params) で実行
5. 両方なければユーザーに確認

【重要】list_prompts() や list_workflows() は検索用であり、実行ツールではありません。""",
        "entries": {
            "prompt_vs_workflow": {
                "summary": "プロンプト実行とワークフロー実行の違い",
                "description": "execute_prompt と execute_workflow の使い分け基準",
                "examples": [
                    "【プロンプト実行】単一のLLM呼び出し → execute_prompt",
                    "【ワークフロー実行】複数ステップ（FOREACH, IF等） → execute_workflow"
                ],
                "notes": [
                    "プロンプト: シンプルなテンプレート実行",
                    "ワークフロー: マルチステップ処理（LLM + 条件分岐 + 結果集計など）"
                ]
            },
            "search_then_execute": {
                "summary": "検索してから実行",
                "description": "list_* は検索、execute_* は実行。両者は別物です。",
                "examples": [
                    "❌ list_workflows() を呼んで終わり → 実行していない",
                    "✅ list_prompts() → 見つかった → execute_prompt(id, params)",
                    "✅ list_workflows() → 見つかった → execute_workflow(id, params)"
                ],
                "notes": [
                    "list_prompts() / list_workflows() は検索用",
                    "execute_prompt() / execute_workflow() が実行ツール"
                ]
            }
        }
    },

    # =========================================================================
    # workflow トピック
    # =========================================================================
    "workflow": {
        "description": "ワークフローシステム - マルチステッププロンプト実行パイプライン",
        "overview": """ワークフローは複数のステップを順番に実行し、変数を使ってデータを受け渡します。
主なステップタイプ: prompt(LLM実行), set(変数設定), output(出力), if/foreach(制御フロー)""",
        "entries": {
            # ステップタイプ
            "prompt": {
                "summary": "LLMプロンプト実行ステップ",
                "description": "登録済みのプロンプトを実行し、結果を取得します。【重要】input_mappingを指定しないとプロンプトのパラメータに値が渡されません。",
                "syntax": """add_workflow_step(
    workflow_id=ID,
    step_name="ask",
    step_type="prompt",
    prompt_name="質問プロンプト",
    input_mapping={"QUESTION": "{{vars.ROW.question}}"}  # ←必須！
)""",
                "examples": [
                    '{"step_type": "prompt", "prompt_name": "分析プロンプト", "input_mapping": {"TEXT": "{{input.text}}"}}',
                    '{"step_type": "prompt", "prompt_name": "評価", "input_mapping": {"Q": "{{vars.ROW.question}}", "A": "{{vars.ROW.choices}}"}}',
                    "【間違い例 - input_mappingなし】\n{\"step_type\": \"prompt\", \"prompt_name\": \"質問\"}\n→ プロンプトの {{QUESTION}} が空のままになる！",
                    "【正しい例】\n{\"step_type\": \"prompt\", \"prompt_name\": \"質問\", \"input_mapping\": {\"QUESTION\": \"{{vars.ROW.question}}\"}}\n→ プロンプトの {{QUESTION}} に値が入る"
                ],
                "notes": [
                    "【必須】input_mapping でプロンプトの各パラメータに値を渡す",
                    "input_mapping がないとプロンプトテンプレートの {{PARAM}} が空になる",
                    "プロンプトテンプレートに {{QUESTION}} があれば input_mapping に \"QUESTION\": \"値\" が必要",
                    "prompt_name は事前に作成したプロンプトの名前 (prompt_idではない)",
                    "結果は {{step_name.FIELD}} で参照 (例: {{ask.ANSWER}})",
                    "パーサー設定がある場合、パースされたフィールドにアクセス可能 (例: {{ask.ANSWER}})",
                    "生の応答は {{step_name.RAW_RESPONSE}} で取得"
                ]
            },
            "input_mapping": {
                "summary": "【重要】プロンプトステップへの値の渡し方",
                "description": "ワークフロー内のpromptステップでは、input_mappingを使ってプロンプトのパラメータに値を渡します。これがないとプロンプトは空のパラメータで実行されます。",
                "syntax": 'input_mapping={"PARAM_NAME": "{{vars.xxx}}", "PARAM2": "{{input.yyy}}"}',
                "examples": [
                    "【プロンプトテンプレート】\n質問: {{QUESTION}}\n選択肢:\n{{CHOICES}}\n\n回答を選んでください。",
                    "【input_mapping】\n{\"QUESTION\": \"{{vars.ROW.question}}\", \"CHOICES\": \"format_choices({{vars.ROW.choices}})\"}",
                    "【結果】\nQUESTION → データセットの question カラムの値\nCHOICES → format_choices関数で整形された選択肢"
                ],
                "notes": [
                    "プロンプトの {{PARAM}} ごとに対応する input_mapping が必要",
                    "input_mapping のキーはプロンプトのパラメータ名と完全一致させる",
                    "値には変数参照 ({{vars.xxx}}) や関数 (format_choices等) が使用可能",
                    "input_mapping がないパラメータは空文字になる",
                    "オプショナルパラメータ ({{PARAM|}}) は省略可能"
                ]
            },
            "set": {
                "summary": "変数設定ステップ",
                "description": "ワークフロー変数を設定または更新します",
                "syntax": """add_workflow_step(
    workflow_id=ID,
    step_name="init",
    step_type="set",
    condition_config={"assignments": {"counter": "0", "total": "0"}}
)""",
                "examples": [
                    '{"step_type": "set", "condition_config": {"assignments": {"correct": "0", "incorrect": "0"}}}',
                    '{"step_type": "set", "condition_config": {"assignments": {"total": "calc({{vars.total}} + 1)"}}}',
                    '{"step_type": "set", "condition_config": {"assignments": {"result": "{{ask.ANSWER}}"}}}'
                ],
                "notes": [
                    "assignments に変数名と値のペアを指定",
                    "値には関数が使用可能 (calc, upper, format_choices等)",
                    "複数の変数を同時に設定可能",
                    "変数は {{vars.変数名}} で参照"
                ]
            },
            "output": {
                "summary": "出力ステップ (画面/ファイル)",
                "description": "結果を画面に表示またはファイルに出力します",
                "syntax": """add_workflow_step(
    workflow_id=ID,
    step_name="result",
    step_type="output",
    condition_config={
        "output_type": "screen",  # または "file"
        "format": "text",         # text, json, csv
        "content": "結果: {{vars.correct}}/{{vars.total}}"
    }
)""",
                "examples": [
                    '{"step_type": "output", "condition_config": {"output_type": "screen", "format": "text", "content": "正解率: {{vars.correct}}/{{vars.total}}"}}',
                    '{"step_type": "output", "condition_config": {"output_type": "screen", "format": "json", "fields": {"answer": "{{ask.ANSWER}}", "score": "{{ask.SCORE}}"}}}',
                    '{"step_type": "output", "condition_config": {"output_type": "file", "format": "csv", "filename": "results.csv", "columns": ["ID", "Answer"], "values": ["{{vars.i}}", "{{ask.ANSWER}}"], "append": true}}'
                ],
                "notes": [
                    "output_type: 'screen' (画面表示) または 'file' (ファイル出力)",
                    "format: 'text', 'json', 'csv' から選択",
                    "CSV出力時は columns と values を配列で指定",
                    "append: true でファイルに追記",
                    "【CSVクォート】values に手動で引用符を付けないこと",
                    "  ❌ values: [\"\\\"id\\\"\", ...]  (手動引用符 → 三重引用符になる)",
                    "  ✅ values: [\"id\", ...]  (CSVフォーマッタが自動処理)"
                ]
            },
            "foreach": {
                "summary": "データセット/配列のイテレーション",
                "description": "データセットまたは配列の各要素に対してループ処理を実行します",
                "syntax": """add_foreach_block(
    workflow_id=ID,
    step_name="loop",
    item_var="ROW",
    list_ref="dataset:6:limit:10"
)""",
                "examples": [
                    '{"step_type": "foreach", "condition_config": {"item_var": "ROW", "list_ref": "dataset:6"}}',
                    '{"step_type": "foreach", "condition_config": {"item_var": "ROW", "list_ref": "dataset:6:question,answer:limit:10"}}',
                    '{"step_type": "foreach", "condition_config": {"item_var": "ROW", "list_ref": "dataset:6:limit:3:seed:42"}}',
                    '{"step_type": "foreach", "condition_config": {"item_var": "ROW", "list_ref": "dataset:6:random:5:seed:123"}}',
                    '{"step_type": "foreach", "condition_config": {"item_var": "item", "list_ref": "{{generate.items}}"}}'
                ],
                "notes": [
                    "item_var で指定した変数で現在行にアクセス: {{vars.ROW.column}}",
                    "インデックスは {{vars.i}} で参照 (0始まり)",
                    "必ず endforeach でペアを閉じる",
                    "list_ref にデータセット参照または配列を指定",
                    "【データセット参照構文】",
                    "  dataset:ID - 全行",
                    "  dataset:ID:column - 特定カラム",
                    "  dataset:ID:col1,col2 - 複数カラム",
                    "  dataset:ID:limit:N - N行に制限",
                    "  dataset:ID:limit:N:seed:S - ランダムN行（シード指定）",
                    "  dataset:ID:random:N - ランダムN行",
                    "  dataset:ID:random:N:seed:S - ランダムN行（シード指定）",
                    "【単一カラム vs 複数カラム】",
                    "  source: dataset:6:text → {{vars.ROW}} で値を参照 ({{vars.ROW.text}} は無効)",
                    "  source: dataset:6 → {{vars.ROW.column}} で各カラムを参照"
                ]
            },
            "endforeach": {
                "summary": "FOREACHブロックの終了",
                "description": "FOREACHループを閉じます",
                "syntax": '{"step_type": "endforeach"}',
                "notes": ["対応する foreach と必ずペアで使用"]
            },
            "if": {
                "summary": "条件分岐の開始",
                "description": "条件に基づいて処理を分岐します",
                "syntax": """add_if_block(
    workflow_id=ID,
    step_name="check",
    left="{{ask.ANSWER}}",
    operator="==",
    right="{{vars.ROW.answerKey}}"
)""",
                "examples": [
                    '{"step_type": "if", "condition_config": {"left": "{{ask.ANSWER}}", "operator": "==", "right": "A"}}',
                    '{"step_type": "if", "condition_config": {"left": "{{vars.score}}", "operator": ">=", "right": "80"}}',
                    '{"step_type": "if", "condition_config": {"left": "{{api_call.result}}", "operator": "contains", "right": "success"}}'
                ],
                "notes": [
                    "演算子: ==, !=, >, <, >=, <=, contains, empty, not_empty",
                    "必ず endif でペアを閉じる",
                    "elif, else と組み合わせ可能"
                ]
            },
            "elif": {
                "summary": "追加の条件分岐",
                "description": "前のifまたはelifが偽の場合に追加の条件を評価します",
                "syntax": '{"step_type": "elif", "condition_config": {"left": "{{ask.ANSWER}}", "operator": "==", "right": "B"}}',
                "notes": ["if の後、endif の前に配置"]
            },
            "else": {
                "summary": "デフォルト分岐",
                "description": "すべての条件が偽の場合に実行されるブロック",
                "syntax": '{"step_type": "else"}',
                "notes": ["if/elif の後、endif の前に配置"]
            },
            "endif": {
                "summary": "IF ブロックの終了",
                "description": "条件分岐ブロックを閉じます",
                "syntax": '{"step_type": "endif"}',
                "notes": ["対応する if と必ずペアで使用"]
            },
            "loop": {
                "summary": "条件ループ (while)",
                "description": "条件が真の間、繰り返し処理を実行します",
                "syntax": """add_workflow_step(
    workflow_id=ID,
    step_name="retry",
    step_type="loop",
    condition_config={
        "left": "{{vars.retry}}",
        "operator": "<",
        "right": "3",
        "max_iterations": 100
    }
)""",
                "examples": [
                    '{"step_type": "loop", "condition_config": {"left": "{{vars.i}}", "operator": "<", "right": "10", "max_iterations": 100}}'
                ],
                "notes": [
                    "max_iterations で無限ループを防止 (デフォルト: 100)",
                    "必ず endloop でペアを閉じる",
                    "break でループを抜ける"
                ]
            },
            "endloop": {
                "summary": "LOOP ブロックの終了",
                "description": "LOOPを閉じます",
                "syntax": '{"step_type": "endloop"}',
                "notes": ["対応する loop と必ずペアで使用"]
            },
            "break": {
                "summary": "ループの即座終了",
                "description": "現在のループ (loop/foreach) を即座に抜けます",
                "syntax": '{"step_type": "break"}',
                "notes": ["loop または foreach 内でのみ使用可能"]
            },
            "continue": {
                "summary": "次のイテレーションへスキップ",
                "description": "残りの処理をスキップして次のイテレーションに進みます",
                "syntax": '{"step_type": "continue"}',
                "notes": ["loop または foreach 内でのみ使用可能"]
            },
            # 変数・演算子
            "variables": {
                "summary": "変数参照構文",
                "description": "ワークフロー内で変数を参照する方法",
                "syntax": "{{namespace.field}} または {{namespace.field.nested}}",
                "examples": [
                    "{{input.query}} - 初期入力パラメータ",
                    "{{vars.counter}} - ワークフロー変数 (setで設定)",
                    "{{step_name.FIELD}} - ステップ出力 (例: {{ask.ANSWER}})",
                    "{{vars.ROW.column}} - FOREACH現在行のカラム値",
                    "{{vars.i}} - FOREACHのインデックス (0始まり)"
                ],
                "notes": [
                    "input - ワークフロー実行時の入力パラメータ",
                    "vars - setステップで設定した変数",
                    "step_name - 各ステップの出力 (step_nameはステップ名)"
                ]
            },
            "prompt_output_fields": {
                "summary": "【重要】PROMPTステップの出力フィールド一覧",
                "description": "PROMPTステップ実行後に参照可能なフィールド。.textは存在しません！",
                "syntax": "{{step_name.field}}",
                "examples": [
                    "{{generate.raw}} - LLM応答の生テキスト（パーサー不要で常に利用可能）",
                    "{{generate.ASSISTANT}} - LLM応答（rawと同じ内容）",
                    "{{ask.ANSWER}} - JSONパーサー設定時の解析済みフィールド",
                    "{{step.parsed.key}} - ネストされた解析済みデータ"
                ],
                "notes": [
                    "【重要】.text は存在しない！必ず .raw を使用すること",
                    "パーサー未設定時: .raw と .ASSISTANT のみ利用可能",
                    "JSONパーサー設定時: 解析結果がトップレベルに展開される（例: .ANSWER）",
                    "CSVやOUTPUTステップで参照する場合は {{step.raw}} が安全"
                ]
            },
            "operators": {
                "summary": "条件演算子",
                "description": "IF/LOOP ステップで使用可能な演算子一覧",
                "syntax": '{"left": "値1", "operator": "演算子", "right": "値2"}',
                "examples": [
                    "== (等しい): {{ask.ANSWER}} == A",
                    "!= (等しくない): {{vars.status}} != error",
                    "> (大きい): {{vars.score}} > 80",
                    "< (小さい): {{vars.count}} < 10",
                    ">= (以上): {{vars.total}} >= 100",
                    "<= (以下): {{vars.retry}} <= 3",
                    "contains (含む): {{generate.raw}} contains 'keyword'",
                    "empty (空): {{vars.result}} empty (rightは無視)",
                    "not_empty (空でない): {{vars.result}} not_empty"
                ],
                "notes": [
                    "数値比較は文字列として比較される場合があるため注意",
                    "empty/not_empty は right の値は無視される"
                ]
            },
            "common_mistakes": {
                "summary": "【よくある間違い】ワークフロー作成でのミスパターン",
                "description": "ワークフロー作成時によくある間違いと正しい書き方をまとめました。この知識がないとほぼ確実にエラーになります。",
                "syntax": "なし（参照用エントリ）",
                "examples": [
                    "【間違い1: プロンプトテンプレートにワークフロー変数を直接書く】",
                    "❌ プロンプトに {{vars.ROW.question}} を直接書く",
                    "✅ プロンプトに {{QUESTION}} を書く + input_mapping: {\"QUESTION\": \"{{vars.ROW.question}}\"}",
                    "",
                    "【間違い2: input_mappingのキーが小文字】",
                    "❌ input_mapping: {\"question\": \"{{vars.ROW.question}}\"} (小文字)",
                    "✅ input_mapping: {\"QUESTION\": \"{{vars.ROW.question}}\"} (プロンプトの{{QUESTION}}と一致)",
                    "",
                    "【間違い3: パーサーフィールドの参照で大文字小文字が不一致】",
                    "❌ パーサー {\"ANSWER\": \"[A-D]\"} に対して {{ask.answer}} (小文字)",
                    "✅ パーサー {\"ANSWER\": \"[A-D]\"} に対して {{ask.ANSWER}} (大文字で一致)",
                    "",
                    "【間違い4: データセットカラム名の間違い】",
                    "❌ {{vars.ROW.question}} (実際のカラム名は question_stem)",
                    "✅ preview_dataset_rows でカラム名を確認してから使用",
                    "",
                    "【間違い5: パーサーのjson_pathが間違い】",
                    "❌ json_path: {\"ANSWER\": \"$.choices\"} (配列が返る)",
                    "✅ json_path: {\"ANSWER\": \"$.label[0]\"} (単一値が返る)",
                    "",
                    "【間違い6: 関数チェーン（致命的エラー）】",
                    "❌ fact1 = json_parse({{run1.OUTPUT}}).fact ← 動作しません！",
                    "→ json_parse() は辞書を返すが、.fact は無視される",
                    "→ 結果: fact1 に辞書全体が格納され、後続の文字列処理で TypeError",
                    "✅ 正解1: {{run1.fact}} を直接使用（パーサーがfactフィールドを抽出済みの場合）",
                    "✅ 正解2: 2段階アプローチ",
                    "   setステップ: parsed = json_parse({{run1.OUTPUT}})",
                    "   次のステップ: {{vars.parsed.fact}} でアクセス"
                ],
                "notes": [
                    "プロンプトテンプレート: {{PARAM}} 形式のみ使用",
                    "ワークフロー変数: {{vars.xxx}}, {{ステップ名.xxx}} はinput_mappingで渡す",
                    "大文字小文字は常に厳密に一致させる",
                    "データセットカラム名は preview_dataset_rows で確認",
                    "パーサーの出力形式はLLMの応答に依存するため、プロンプトで出力形式を指示"
                ]
            },
            "case_sensitivity": {
                "summary": "【重要】大文字小文字の厳密なルール",
                "description": "ワークフローでは大文字小文字が区別されます。不一致はエラーの原因になります。",
                "syntax": "なし（参照用エントリ）",
                "examples": [
                    "【パーサー → ステップ参照】",
                    "パーサー: {\"ANSWER\": \"[A-D]\"}",
                    "参照: {{generate.ANSWER}} ✅ (大文字で一致)",
                    "参照: {{generate.answer}} ❌ (小文字は不一致→undefined)",
                    "",
                    "【プロンプト → input_mapping】",
                    "プロンプト: {{QUESTION}}",
                    "input_mapping: {\"QUESTION\": \"...\"} ✅ (大文字で一致)",
                    "input_mapping: {\"question\": \"...\"} ❌ (小文字は不一致→パラメータが空)",
                    "",
                    "【FOREACH変数】",
                    "item_var: \"ROW\"",
                    "参照: {{vars.ROW.column}} ✅",
                    "参照: {{vars.row.column}} ❌ (小文字は不一致→undefined)",
                    "",
                    "【条件分岐での参照】",
                    "IF left: {{ask.ANSWER}} ✅",
                    "IF left: {{ask.answer}} ❌ (パーサーがANSWERを出力する場合)"
                ],
                "notes": [
                    "大文字小文字の不一致は最も多いエラー原因の1つ",
                    "パーサーのフィールド名は定義時のケースで参照",
                    "プロンプトのパラメータ名は {{PARAM}} のケースと一致させる",
                    "FOREACHのitem_varは慣例的に大文字 (ROW)",
                    "デバッグ時は変数の実際のケースを確認"
                ]
            },
            "testing": {
                "summary": "【必須】ワークフロー作成後のテスト手順",
                "description": "ワークフロー作成後は必ずテストを実行してください。本番データで失敗すると大量のエラーが発生します。",
                "syntax": "なし（参照用エントリ）",
                "examples": [
                    "【テスト手順】",
                    "1. validate_workflow(workflow_id) で構文検証",
                    "   → エラーがあれば修正",
                    "",
                    "2. execute_workflow(workflow_id) で少量テスト実行",
                    "   → FOREACHのlist_refに limit:1〜3 を指定",
                    "   → 例: dataset:6:limit:2",
                    "",
                    "3. 結果を確認",
                    "   → パーサーが正しく抽出しているか",
                    "   → 変数の値が期待通りか",
                    "   → エラーがないか",
                    "",
                    "4. 問題があれば修正して再テスト",
                    "",
                    "5. 本番実行 (limit解除)",
                    "",
                    "【よくある問題】",
                    "- パーサーフィールド名の大文字小文字不一致",
                    "- input_mappingのキー不一致",
                    "- データセットカラム名の間違い",
                    "- LLM出力がパーサー形式に合わない"
                ],
                "notes": [
                    "validate_workflow: 構文エラー、未閉じブロック、不正な参照を検出",
                    "limit:1〜3 で少量テスト → 問題なければlimit解除",
                    "テストなしで本番実行すると、全行でエラーが発生する可能性",
                    "エラー発生時はログを確認して原因特定"
                ]
            },
            "get_available_variables": {
                "summary": "【ツール】指定ステップで利用可能な変数・関数を取得",
                "description": "ワークフローの特定ステップで参照可能な変数と関数の一覧を取得します。FOREACHループ内ではデータセットのカラム名も表示されます。",
                "syntax": "get_available_variables(workflow_id=ID, step_order=N)",
                "examples": [
                    "【基本使用】",
                    "get_available_variables(workflow_id=161, step_order=2)",
                    "",
                    "【返却例 - FOREACH内のステップ】",
                    "categories: [",
                    "  {category: '📥 初期入力', variables: [{name: 'param', variable: '{{input.param}}'}]},",
                    "  {category: '🔄 FOREACH: question', variables: [",
                    "    {name: 'question (行全体)', variable: '{{vars.question}}'},",
                    "    {name: 'i (インデックス)', variable: '{{vars.i}}'},",
                    "    {name: 'question', variable: '{{vars.question.question}}'},",
                    "    {name: 'choices', variable: '{{vars.question.choices}}'},",
                    "    {name: 'answerKey', variable: '{{vars.question.answerKey}}'}",
                    "  ]},",
                    "  {category: '📊 変数', variables: [{name: 'correct', variable: '{{vars.correct}}'}]}",
                    "]",
                    "",
                    "【用途】",
                    "- input_mapping を作成する前に利用可能な変数を確認",
                    "- FOREACHループ内でデータセットのカラム名を確認",
                    "- 条件式で参照可能な変数を確認"
                ],
                "notes": [
                    "step_order は0始まり（最初のステップが0）",
                    "FOREACH内のステップでは、データセットソースからカラム名を自動取得",
                    "validate_workflow と組み合わせてワークフロー構築を効率化",
                    "返却されるfunctionsには使用可能な関数一覧も含まれる"
                ]
            },
            "array_pattern": {
                "summary": "【推奨】ループで結果を蓄積するパターン",
                "description": "concat() での文字列連結より、array_push + join パターンを推奨します。データの整合性とCSV出力の互換性が向上します。",
                "syntax": """# 1. 初期化
{"step_type": "set", "condition_config": {"assignments": {"rows": "[]"}}}

# 2. ループ内で追加
{"step_type": "set", "condition_config": {"assignments": {
  "rows": "array_push({{vars.rows}}, \\"値\\")"
}}}

# 3. 最後にJOIN（必要に応じて）
{"step_type": "set", "condition_config": {"assignments": {
  "output": "join({{vars.rows}}, \\"\\\\n\\")"
}}}""",
                "examples": [
                    "【初期化】rows = \"[]\" で空配列を作成",
                    "【追加】array_push({{vars.rows}}, {{ask.ANSWER}}) でJSON配列に追加",
                    "【出力】join({{vars.rows}}, \"\\n\") で改行区切り文字列に変換",
                    "【CSV】array_push で蓄積 → output step の csv format で出力"
                ],
                "notes": [
                    "concat() より array_push + join が推奨される理由:",
                    "1. CSV出力時に正しくエスケープされる",
                    "2. 配列として扱えるため後処理が柔軟",
                    "3. 空配列 [] から始められる",
                    "4. join() で任意の区切り文字に変換可能"
                ]
            }
        }
    },

    # =========================================================================
    # functions トピック
    # =========================================================================
    "functions": {
        "description": "ワークフローで使用可能な関数 (28種類)",
        "overview": """ワークフローのset/outputステップやinput_mapping内で使用できる関数です。
構文: function_name(引数1, 引数2, ...)

【重要】関数チェーン（function().property）は一切サポートされていません。
❌ 禁止: json_parse({{x}}).field, concat(a,b).length
✅ 正解: setステップで変数に格納してから別途アクセス
詳細は help workflow common_mistakes を参照""",
        "entries": {
            # 文字列操作
            "upper": {
                "summary": "大文字変換",
                "args": 1,
                "syntax": "upper(text)",
                "examples": ["upper({{generate.raw}}) → HELLO", "upper(abc) → ABC"],
                "notes": []
            },
            "lower": {
                "summary": "小文字変換",
                "args": 1,
                "syntax": "lower(text)",
                "examples": ["lower({{generate.raw}}) → hello", "lower(ABC) → abc"],
                "notes": []
            },
            "trim": {
                "summary": "前後の空白を除去",
                "args": 1,
                "syntax": "trim(text)",
                "examples": ["trim(  hello  ) → hello"],
                "notes": []
            },
            "lstrip": {
                "summary": "先頭の空白を除去",
                "args": 1,
                "syntax": "lstrip(text)",
                "examples": ["lstrip(  hello) → hello"],
                "notes": []
            },
            "rstrip": {
                "summary": "末尾の空白を除去",
                "args": 1,
                "syntax": "rstrip(text)",
                "examples": ["rstrip(hello  ) → hello"],
                "notes": []
            },
            "capitalize": {
                "summary": "先頭を大文字に",
                "args": 1,
                "syntax": "capitalize(text)",
                "examples": ["capitalize(hello world) → Hello world"],
                "notes": []
            },
            "title": {
                "summary": "各単語の先頭を大文字に",
                "args": 1,
                "syntax": "title(text)",
                "examples": ["title(hello world) → Hello World"],
                "notes": []
            },
            "reverse": {
                "summary": "文字列を反転",
                "args": 1,
                "syntax": "reverse(text)",
                "examples": ["reverse(hello) → olleh"],
                "notes": []
            },
            # 長さ・切り出し
            "length": {
                "summary": "文字列の長さ",
                "args": 1,
                "syntax": "length(text)",
                "examples": ["length(hello) → 5"],
                "notes": ["len も同じ動作"]
            },
            "len": {
                "summary": "文字列の長さ (lengthのエイリアス)",
                "args": 1,
                "syntax": "len(text)",
                "examples": ["len(hello) → 5"],
                "notes": []
            },
            "slice": {
                "summary": "部分文字列の切り出し",
                "args": "2-3",
                "syntax": "slice(text, start, [end])",
                "examples": [
                    "slice(hello, 1, 3) → el",
                    "slice(hello, 2) → llo"
                ],
                "notes": ["インデックスは0始まり", "substr, substring も同じ動作"]
            },
            "left": {
                "summary": "先頭からN文字",
                "args": 2,
                "syntax": "left(text, n)",
                "examples": ["left(hello, 3) → hel"],
                "notes": []
            },
            "right": {
                "summary": "末尾からN文字",
                "args": 2,
                "syntax": "right(text, n)",
                "examples": ["right(hello, 3) → llo"],
                "notes": []
            },
            # 変換
            "replace": {
                "summary": "文字列の置換",
                "args": 3,
                "syntax": "replace(text, old, new)",
                "examples": ["replace(hello world, world, there) → hello there"],
                "notes": ["すべての出現箇所を置換"]
            },
            "repeat": {
                "summary": "文字列の繰り返し",
                "args": 2,
                "syntax": "repeat(text, n)",
                "examples": ["repeat(ab, 3) → ababab"],
                "notes": []
            },
            "concat": {
                "summary": "文字列の連結",
                "args": "2+",
                "syntax": "concat(str1, str2, ...)",
                "examples": [
                    "concat(a, b, c) → abc",
                    "concat({{vars.x}}, -, {{vars.y}}) → x-y"
                ],
                "notes": ["2つ以上の引数を連結"]
            },
            "split": {
                "summary": "文字列を配列に分割",
                "args": 2,
                "syntax": "split(text, delimiter)",
                "examples": ["split(a:b:c, :) → [\"a\", \"b\", \"c\"]"],
                "notes": ["結果はJSON配列文字列"]
            },
            "join": {
                "summary": "配列を文字列に結合",
                "args": 2,
                "syntax": "join(array, delimiter)",
                "examples": ["join([\"a\", \"b\"], -) → a-b"],
                "notes": ["入力はJSON配列またはリスト"]
            },
            "array_push": {
                "summary": "配列に要素を追加",
                "args": 2,
                "syntax": "array_push(array, element)",
                "examples": [
                    "array_push({{vars.items}}, {{extract.value}}) → [\"既存\", \"新規\"]",
                    "array_push([], first) → [\"first\"]"
                ],
                "notes": [
                    "空配列は [] または空文字列で初期化",
                    "結果はJSON配列文字列として返される",
                    "join() と組み合わせて文字列に変換可能"
                ]
            },
            "shuffle": {
                "summary": "文字または要素をシャッフル",
                "args": "1-2",
                "syntax": "shuffle(text, [delimiter])",
                "examples": [
                    "shuffle(abc) → cba (ランダム)",
                    "shuffle(a,b,c, ,) → b,c,a (ランダム)"
                ],
                "notes": ["デリミタ指定時は分割してシャッフル"]
            },
            # 判定
            "contains": {
                "summary": "部分文字列の存在確認",
                "args": 2,
                "syntax": "contains(text, search)",
                "examples": ["contains(hello world, world) → true"],
                "notes": ["true/false を返す"]
            },
            "startswith": {
                "summary": "先頭一致確認",
                "args": 2,
                "syntax": "startswith(text, prefix)",
                "examples": ["startswith(hello, hel) → true"],
                "notes": ["true/false を返す"]
            },
            "endswith": {
                "summary": "末尾一致確認",
                "args": 2,
                "syntax": "endswith(text, suffix)",
                "examples": ["endswith(hello, lo) → true"],
                "notes": ["true/false を返す"]
            },
            "count": {
                "summary": "部分文字列の出現回数",
                "args": 2,
                "syntax": "count(text, search)",
                "examples": ["count(hello, l) → 2"],
                "notes": []
            },
            # 条件
            "default": {
                "summary": "空の場合のデフォルト値",
                "args": 2,
                "syntax": "default(value, fallback)",
                "examples": [
                    "default({{vars.x}}, N/A) → N/A (xが空の場合)",
                    "default(, default_value) → default_value"
                ],
                "notes": ["ifempty も同じ動作"]
            },
            "ifempty": {
                "summary": "空の場合のデフォルト値 (defaultのエイリアス)",
                "args": 2,
                "syntax": "ifempty(value, fallback)",
                "examples": ["ifempty({{vars.x}}, fallback)"],
                "notes": []
            },
            # 計算
            "calc": {
                "summary": "算術計算",
                "args": 1,
                "syntax": "calc(expression)",
                "examples": [
                    "calc(1 + 2) → 3",
                    "calc({{vars.x}} + 1)",
                    "calc({{vars.total}} / {{vars.count}} * 100)"
                ],
                "notes": [
                    "四則演算 (+, -, *, /) をサポート",
                    "括弧 () も使用可能",
                    "結果は数値または小数"
                ]
            },
            "sum": {
                "summary": "数値の合計",
                "args": "2+",
                "syntax": "sum(num1, num2, ...)",
                "examples": ["sum(1, 2, 3) → 6"],
                "notes": ["2つ以上の数値を合計"]
            },
            # 日時関数
            "now": {
                "summary": "現在日時を取得",
                "args": "0-1",
                "syntax": "now(format)",
                "examples": [
                    "now() → 2025-01-15 14:30:45",
                    "now(%Y-%m-%d) → 2025-01-15",
                    "now(%H:%M:%S) → 14:30:45",
                    "now(%Y年%m月%d日) → 2025年01月15日"
                ],
                "notes": [
                    "デフォルトフォーマット: %Y-%m-%d %H:%M:%S",
                    "Python strftime形式を使用",
                    "主なフォーマット指定子: %Y(年4桁), %m(月), %d(日), %H(時), %M(分), %S(秒)"
                ]
            },
            "today": {
                "summary": "今日の日付を取得",
                "args": "0-1",
                "syntax": "today(format)",
                "examples": [
                    "today() → 2025-01-15",
                    "today(%Y/%m/%d) → 2025/01/15",
                    "today(%Y年%m月%d日) → 2025年01月15日"
                ],
                "notes": [
                    "デフォルトフォーマット: %Y-%m-%d",
                    "now()の日付部分のみを取得するショートカット"
                ]
            },
            "time": {
                "summary": "現在時刻を取得",
                "args": "0-1",
                "syntax": "time(format)",
                "examples": [
                    "time() → 14:30:45",
                    "time(%H:%M) → 14:30",
                    "time(%H時%M分%S秒) → 14時30分45秒"
                ],
                "notes": [
                    "デフォルトフォーマット: %H:%M:%S",
                    "now()の時刻部分のみを取得するショートカット"
                ]
            },
            # JSON
            "json_parse": {
                "summary": "JSON文字列をパースしてオブジェクトに変換",
                "args": 1,
                "syntax": "json_parse(json_string)",
                "examples": [
                    "json_parse({{generate.json_output}}) → JSONオブジェクトに変換",
                    "json_parse({\"name\": \"test\", \"value\": 123}) → パース後にフィールドアクセス可能",
                    "【ワークフロー例】\nステップ1: LLMがJSON出力 → {{ask.RAW_RESPONSE}} = '{\"answer\": \"A\", \"score\": 95}'\nステップ2: set で parsed = json_parse({{ask.RAW_RESPONSE}})\nステップ3: {{vars.parsed.answer}} で 'A' を取得"
                ],
                "notes": [
                    "【禁止】json_parse()の戻り値に直接.propertyをチェーンすることは不可",
                    "❌ 絶対禁止: json_parse({{step.OUTPUT}}).field ← これは動作しません！",
                    "✅ 正解1: プロンプトパーサーが既にフィールドを抽出済みなら {{step.field}} を直接使用",
                    "✅ 正解2: setステップで parsed = json_parse({{step.OUTPUT}}) → その後 {{vars.parsed.field}}",
                    "関数チェーン（func().prop）は一切サポートされていない",
                    "JSON文字列をパースしてネストしたフィールドにアクセス可能にする",
                    "パース後は {{vars.変数名.フィールド名}} でアクセス",
                    "ネストしたアクセス: {{vars.parsed.data.items[0].name}}",
                    "配列アクセス: {{vars.parsed.items[0]}}",
                    "パース失敗時はエラーになるため、LLM出力が正しいJSONか確認"
                ]
            },
            "json_zip": {
                "summary": "複数のJSON配列を要素ごとに結合",
                "args": "2+",
                "syntax": "json_zip(json_object, key1, key2, ...)",
                "examples": [
                    'json_zip({"a": [1,2], "b": [3,4]}, a, b) → [[1,3], [2,4]]',
                    "【実用例: ARC形式の選択肢を行ごとに処理】\nデータ: {\"text\": [\"選択肢A\", \"選択肢B\"], \"label\": [\"A\", \"B\"]}\njson_zip({{vars.ROW.choices}}, label, text) → [[\"A\", \"選択肢A\"], [\"B\", \"選択肢B\"]]",
                    "【ワークフローでの使用】\nset: zipped = json_zip({{vars.ROW.choices}}, label, text)\nforeach: item_var=CHOICE, list_ref={{vars.zipped}}\n  → {{vars.CHOICE[0]}} = ラベル, {{vars.CHOICE[1]}} = テキスト"
                ],
                "notes": [
                    "複数の配列を要素ごとにペアにして結合",
                    "ARC/SciQなどのデータセットで選択肢を処理する際に有用",
                    "結果は2次元配列: [[key1[0], key2[0]], [key1[1], key2[1]], ...]"
                ]
            },
            "format_choices": {
                "summary": "選択肢JSONをLLM向けテキスト形式に変換",
                "args": 1,
                "syntax": "format_choices(choices_json)",
                "examples": [
                    'format_choices({"text": ["りんご", "みかん", "ぶどう"], "label": ["A", "B", "C"]}) → "A: りんご\\nB: みかん\\nC: ぶどう"',
                    "【ワークフローでの使用例】\nデータセット列: choices = {\"text\": [...], \"label\": [...]}\nプロンプト input_mapping: {\"CHOICES\": \"format_choices({{vars.ROW.choices}})\"}",
                    "【プロンプト例】\n以下の選択肢から正しいものを選んでください:\n{{CHOICES}}\n\n回答はA/B/C/Dのいずれか1文字で答えてください。"
                ],
                "notes": [
                    "ARC/OpenBookQA/SciQ等のデータセット形式に対応",
                    "入力: {\"text\": [\"選択肢1\", ...], \"label\": [\"A\", ...]}",
                    "出力: \"A: 選択肢1\\nB: 選択肢2\\n...\" (改行区切りテキスト)",
                    "LLMへの選択肢提示に最適化された形式",
                    "labelキーがない場合は自動でA, B, C, D...を付与"
                ]
            },
            "dataset_filter": {
                "summary": "データセット行を条件でフィルタ（複合条件対応）",
                "args": 2,
                "syntax": "dataset_filter(dataset:ID, \"condition\")",
                "examples": [
                    "dataset_filter(dataset:6, \"category='a'\") → categoryがaの行のみ",
                    "dataset_filter(dataset:6, \"score>80\") → スコアが80を超える行",
                    "dataset_filter(dataset:6, \"score>=60 AND category='a'\") → AND条件",
                    "dataset_filter(dataset:6, \"status='done' OR status='skip'\") → OR条件",
                    "dataset_filter(dataset:6, \"name LIKE 'test%'\") → 'test'で始まる名前",
                    "dataset_filter(dataset:6, \"comment IS NULL\") → コメントがNULLの行",
                    "dataset_filter(dataset:6, \"comment IS NOT NULL\") → コメントがある行のみ",
                    "dataset_filter(dataset:6, \"field IS EMPTY\") → fieldが空文字の行",
                    "dataset_filter(dataset:6, \"text contains keyword\") → textにkeywordを含む行"
                ],
                "notes": [
                    "結果はJSON配列で返る（[{row1}, {row2}, ...]）",
                    "dataset_join()と組み合わせてFOREACHなしでデータ抽出可能",
                    "比較演算子: = == != <> < > <= >=",
                    "文字列演算子: contains, LIKE (% = 任意文字列, _ = 1文字)",
                    "NULL判定: IS NULL, IS NOT NULL",
                    "空文字判定: IS EMPTY, IS NOT EMPTY",
                    "論理演算子: AND, OR (大文字小文字不問)",
                    "AND/ORの優先順位: AND > OR (括弧は非対応)",
                    "条件値はシングル/ダブルクォートで囲む（数値比較時は不要）",
                    "【FOREACHソースとして使用】",
                    "  source: dataset_filter(dataset:6, \"score>80\") → 条件に合う行のみイテレート",
                    "  source: dataset_filter(dataset:6, \"field IS NOT NULL\") → NULLでない行のみ"
                ]
            },
            "dataset_join": {
                "summary": "データセットカラム値を区切り文字で結合",
                "args": "2-3",
                "syntax": "dataset_join(source, \"column\", \"separator\")",
                "examples": [
                    "dataset_join(dataset:6, \"value\", \"\\n\") → 全行のvalueカラムを改行で結合",
                    "dataset_join(dataset:6, \"name\", \", \") → 全行のnameをカンマ区切りで結合",
                    "dataset_join(dataset_filter(dataset:6, \"category='a'\"), \"value\", \"\\n\") → フィルタ結果を結合"
                ],
                "notes": [
                    "FOREACHなしでデータセットのカラム値を取り出せる",
                    "dataset_filter()の結果を第1引数に渡せる",
                    "区切り文字省略時は改行（\\n）",
                    "\\n = 改行, \\t = タブ として解釈"
                ]
            },
            # デバッグ
            "debug": {
                "summary": "デバッグ出力",
                "args": "1+",
                "syntax": "debug(value, ...)",
                "examples": ["debug({{vars.x}}, {{ask.result}})"],
                "notes": [
                    "ログに出力される (画面には表示されない)",
                    "デバッグ目的で変数の値を確認"
                ]
            },
            # その他
            "getprompt": {
                "summary": "プロンプト内容を取得",
                "args": "1-3",
                "syntax": "getprompt(name, [project], [revision])",
                "examples": ["getprompt(質問プロンプト)"],
                "notes": ["CURRENT で現在のプロジェクト/リビジョンを指定"]
            },
            "getparser": {
                "summary": "パーサー設定を取得",
                "args": "1-3",
                "syntax": "getparser(name, [project], [revision])",
                "examples": ["getparser(回答パーサー)"],
                "notes": ["CURRENT で現在のプロジェクト/リビジョンを指定"]
            }
        }
    },

    # =========================================================================
    # prompt トピック
    # =========================================================================
    "prompt": {
        "description": "プロンプトテンプレート構文とパラメータ型",
        "overview": """プロンプトテンプレートは {{PARAM_NAME}} 形式でパラメータを定義します。
型指定、オプショナル指定、デフォルト値が設定可能です。""",
        "entries": {
            "TEXT": {
                "summary": "テキスト入力 (デフォルト)",
                "description": "複数行テキスト入力。数字で行数を指定。",
                "syntax": "{{PARAM_NAME}} または {{PARAM_NAME:TEXTn}}",
                "examples": [
                    "{{CONTENT}} - デフォルト (TEXT5 = 5行)",
                    "{{DESCRIPTION:TEXT10}} - 10行テキストエリア",
                    "{{LONG_TEXT:TEXT20}} - 20行テキストエリア"
                ],
                "notes": ["デフォルトは TEXT5 (5行)"]
            },
            "NUM": {
                "summary": "数値入力",
                "description": "数値のみを受け付ける入力フィールド",
                "syntax": "{{PARAM_NAME:NUM}}",
                "examples": ["{{COUNT:NUM}}", "{{TEMPERATURE:NUM}}"],
                "notes": ["整数・小数ともに受け付け"]
            },
            "DATE": {
                "summary": "日付入力",
                "description": "日付選択 (YYYY-MM-DD形式)",
                "syntax": "{{PARAM_NAME:DATE}}",
                "examples": ["{{START_DATE:DATE}}"],
                "notes": ["形式: YYYY-MM-DD"]
            },
            "DATETIME": {
                "summary": "日時入力",
                "description": "日時選択",
                "syntax": "{{PARAM_NAME:DATETIME}}",
                "examples": ["{{MEETING_TIME:DATETIME}}"],
                "notes": ["形式: YYYY-MM-DDTHH:MM:SS"]
            },
            "FILE": {
                "summary": "画像ファイルアップロード (Vision API用)",
                "description": "ブラウザから画像ファイルをアップロード。Vision APIで処理。",
                "syntax": "{{PARAM_NAME:FILE}}",
                "examples": ["{{SCREENSHOT:FILE}}", "{{IMAGE:FILE}}"],
                "notes": [
                    "JPEG, PNG, GIF, WebP対応",
                    "Base64エンコードされてLLMに送信",
                    "単発実行で使用"
                ]
            },
            "FILEPATH": {
                "summary": "サーバーファイルパス",
                "description": "サーバー上のファイルパスを指定。バッチ処理で使用。",
                "syntax": "{{PARAM_NAME:FILEPATH}}",
                "examples": [
                    "{{IMAGE_PATH:FILEPATH}}",
                    "{{DOCUMENT:FILEPATH}}"
                ],
                "notes": [
                    "uploads/ ディレクトリ内のファイルを参照",
                    "画像ファイルはVision APIで処理",
                    "テキストファイルは内容がプロンプトに埋め込まれる",
                    "バッチ実行でデータセットのパス列を使用"
                ]
            },
            "TEXTFILEPATH": {
                "summary": "テキストファイル埋め込み",
                "description": "テキストファイルの内容をプロンプトに直接埋め込む",
                "syntax": "{{PARAM_NAME:TEXTFILEPATH}}",
                "examples": ["{{CONFIG:TEXTFILEPATH}}", "{{README:TEXTFILEPATH}}"],
                "notes": [
                    "ファイル内容がそのままプロンプトに展開",
                    "UTF-8, Shift_JIS, EUC-JP等の文字コードに対応"
                ]
            },
            "optional": {
                "summary": "オプショナルパラメータ構文",
                "description": "パラメータを省略可能にする",
                "syntax": "{{PARAM|}} または {{PARAM|default=値}} または {{PARAM:TYPE|default=値}}",
                "examples": [
                    "{{CONTEXT|}} - 省略可能、デフォルトなし",
                    "{{LANGUAGE|default=日本語}} - デフォルト値あり",
                    "{{COUNT:NUM|default=5}} - 型指定とデフォルト値"
                ],
                "notes": [
                    "| を付けると省略可能",
                    "default= でデフォルト値を指定"
                ]
            },
            "roles": {
                "summary": "ロールマーカー (マルチターン会話)",
                "description": "プロンプト内でロール (SYSTEM/USER/ASSISTANT) を指定",
                "syntax": "[SYSTEM], [USER], [ASSISTANT]",
                "examples": [
                    "[SYSTEM]あなたは翻訳者です。\\n[USER]{{TEXT}}を翻訳してください。",
                    "[SYSTEM]JSONで応答してください。\\n[USER]{{QUESTION}}\\n[ASSISTANT]{{PREVIOUS_ANSWER}}\\n[USER]続きを教えて。"
                ],
                "notes": [
                    "ロールマーカーがない場合は全体がUSERメッセージ",
                    "大文字小文字は区別しない ([system] も可)",
                    "マルチターン会話のシミュレーションに使用"
                ]
            }
        }
    },

    # =========================================================================
    # parser トピック
    # =========================================================================
    "parser": {
        "description": "レスポンスパーサー設定とプロンプト連携",
        "overview": """パーサーはLLMの応答からフィールドを抽出します。
プロンプトに parser_config を設定して使用します。

【重要】パーサーが正しく動作するには、プロンプトでLLMに適切な出力形式を指示する必要があります。
- JSONパーサー → プロンプトで「JSON形式で出力」と指示
- 正規表現パーサー → 抽出対象の形式で出力するよう指示""",
        "entries": {
            "prompt_design": {
                "summary": "【重要】パーサーと連携するプロンプトの書き方",
                "description": "パーサーが正しくフィールドを抽出できるよう、プロンプトでLLMに出力形式を指示する必要があります。",
                "syntax": "プロンプト内で出力形式を明示的に指示する",
                "examples": [
                    "【JSONパーサー用プロンプト例】\n以下の質問に答えてください。\n質問: {{QUESTION}}\n\n必ず以下のJSON形式で回答してください:\n{\"answer\": \"A/B/C/Dのいずれか\", \"confidence\": 0-100の数値, \"reasoning\": \"理由\"}",
                    "【正規表現パーサー用プロンプト例】\n以下の選択肢から正解を選んでください。\n{{QUESTION}}\n\n回答は A, B, C, D のいずれか1文字のみを出力してください。",
                    "【json_pathパーサー用プロンプト例】\n分析結果をJSON形式で出力してください:\n{\"result\": {\"score\": 数値, \"category\": \"カテゴリ名\"}, \"metadata\": {\"processed\": true}}"
                ],
                "notes": [
                    "パーサーはLLM出力を後処理するだけ - LLMが正しい形式で出力しなければ抽出できない",
                    "JSONパーサー使用時は「JSON形式で出力」「以下のフォーマットで」等を必ず指示",
                    "正規表現パーサー使用時は抽出対象が明確に出力されるよう指示",
                    "LLMが余計な説明を付加しないよう「〜のみを出力」と指示すると効果的",
                    "抽出フィールドは {{step_name.FIELD_NAME}} で後続ステップから参照可能"
                ]
            },
            "json": {
                "summary": "JSON全体をパース",
                "description": "LLM応答がJSON形式の場合、全フィールドを抽出。プロンプトで必ずJSON出力を指示すること。",
                "syntax": '{"type": "json"} または {"type": "json", "fields": ["field1", "field2"]}',
                "examples": [
                    '{"type": "json"}',
                    '{"type": "json", "fields": ["answer", "confidence"]}',
                    "【対応するプロンプト例】\n回答をJSON形式で出力してください: {\"answer\": \"回答\", \"confidence\": 0-100}"
                ],
                "notes": [
                    "fields を指定すると特定フィールドのみ抽出",
                    "Markdownコードブロック (```json) も自動処理",
                    "プロンプトでJSON出力を指示しないとパースに失敗する"
                ]
            },
            "json_path": {
                "summary": "JSONPath で特定フィールドを抽出",
                "description": "ネストしたJSONから特定パスの値を抽出",
                "syntax": '{"type": "json_path", "paths": {"FIELD_NAME": "$.path.to.field"}}',
                "examples": [
                    '{"type": "json_path", "paths": {"answer": "$.answer"}}',
                    '{"type": "json_path", "paths": {"result": "$.data.result", "score": "$.metadata.score"}}'
                ],
                "notes": [
                    "パス構文: $.field, $.nested.field",
                    "抽出したフィールドは {{step_name.FIELD_NAME}} で参照"
                ]
            },
            "regex": {
                "summary": "正規表現で抽出",
                "description": "正規表現パターンにマッチした部分を抽出",
                "syntax": '{"type": "regex", "patterns": {"FIELD_NAME": "pattern"}}',
                "examples": [
                    '{"type": "regex", "patterns": {"ANSWER": "[A-D]"}}',
                    '{"type": "regex", "patterns": {"ANSWER": "(?:Answer:|^)\\\\s*([A-D])"}}',
                    '{"type": "regex", "patterns": {"SCORE": "(\\\\d+)", "STATUS": "(PASS|FAIL)"}}'
                ],
                "notes": [
                    "キャプチャグループ () がある場合はその部分を抽出",
                    "キャプチャグループがない場合はマッチ全体を抽出",
                    "複数パターンで複数フィールドを抽出可能"
                ]
            },
            "csv_output": {
                "summary": "CSV出力用追加設定",
                "description": "パース結果をCSV形式で出力する設定",
                "syntax": '"csv_template": "$FIELD1$,$FIELD2$", "csv_header": "列1,列2"',
                "examples": [
                    '{"type": "regex", "patterns": {"ANSWER": "[A-D]"}, "csv_template": "$ID$,$ANSWER$", "csv_header": "ID,回答"}',
                    '{"type": "json_path", "paths": {"answer": "$.answer"}, "csv_template": "\\"$answer$\\"", "csv_header": "Answer"}'
                ],
                "notes": [
                    "$FIELD$ でパースしたフィールドを参照",
                    "csv_header でCSVのヘッダー行を指定",
                    "結果は {{step_name.csv_output}} で参照"
                ]
            }
        }
    },

    # =========================================================================
    # dataset_ref トピック
    # =========================================================================
    "dataset_ref": {
        "description": "データセット参照構文",
        "overview": """FOREACHステップでデータセットを参照する構文です。
データセットIDはlist_datasetsツールで確認できます。""",
        "entries": {
            "basic": {
                "summary": "基本構文 (全行)",
                "description": "データセットの全行を取得",
                "syntax": "dataset:ID",
                "examples": ["dataset:6", "dataset:15"],
                "notes": ["全カラム、全行を取得"]
            },
            "column": {
                "summary": "特定カラムのみ",
                "description": "指定したカラムのみを取得",
                "syntax": "dataset:ID:column_name",
                "examples": [
                    "dataset:6:question",
                    "dataset:6:answer"
                ],
                "notes": [
                    "カラム名は大文字小文字を区別",
                    "【重要】単一カラム指定時、item_var には値が直接格納される",
                    "  → 参照: {{vars.ROW}}  ✅ (値そのもの)",
                    "  → 参照: {{vars.ROW.column}} ❌ (オブジェクトではない)",
                    "複数カラムまたは全カラム指定時のみ {{vars.ROW.column}} が有効"
                ]
            },
            "multiple_columns": {
                "summary": "複数カラム",
                "description": "複数のカラムを指定して取得",
                "syntax": "dataset:ID:col1,col2,col3",
                "examples": [
                    "dataset:6:question,answer",
                    "dataset:6:id,text,label"
                ],
                "notes": ["カンマ区切りで複数カラム指定"]
            },
            "limit": {
                "summary": "行数制限",
                "description": "取得する行数を制限",
                "syntax": "dataset:ID::limit:N または dataset:ID:column:limit:N",
                "examples": [
                    "dataset:6::limit:10 - 最初の10行 (全カラム)",
                    "dataset:6:question:limit:5 - 最初の5行 (questionカラム)",
                    "dataset:6:q,a:limit:20 - 最初の20行 (q,aカラム)"
                ],
                "notes": [
                    "テスト時は limit を使用して少量でテスト",
                    "全カラム制限の場合は :: を使用"
                ]
            },
            "random": {
                "summary": "ランダムn件取得",
                "description": "データセットからランダムにN件を取得。seedを指定すると同じ結果を再現可能",
                "syntax": "dataset:ID:random:N または dataset:ID:random:N:seed:42",
                "examples": [
                    "dataset:6:random:10 - ランダム10件 (毎回異なる順序)",
                    "dataset:6:random:10:seed:42 - ランダム10件 (seed指定で再現可能)",
                    "dataset:6:question:random:5 - questionカラムのみランダム5件",
                    "dataset:6:q,a:random:20:seed:123 - 複数カラムでランダム20件"
                ],
                "notes": [
                    "seed指定で同じ結果を再現可能（テスト/評価時に便利）",
                    "seed省略時は毎回異なるランダム順序",
                    ":limit: と :random: の同時使用は不可"
                ]
            }
        }
    },

    # =========================================================================
    # validation トピック - validate_workflow の警告・エラー対処法
    # =========================================================================
    "validation": {
        "description": "validate_workflow の警告・エラーと対処法",
        "overview": """validate_workflow はワークフローの構文・設定を検証し、問題点を報告します。

重要度:
- ERROR: 実行前に修正必須。ワークフローが動作しません。
- WARNING: 実行可能だが問題が発生する可能性。修正を推奨。
- INFO: 情報のみ。必要に応じて対応。

カテゴリ別にエントリがあります。各エントリで対処法を確認してください。""",
        "entries": {
            "control_flow": {
                "summary": "制御フローエラー (IF/ENDIF, FOREACH/ENDFOREACH等)",
                "description": "制御ブロックのペアが不一致、または不正なネスト構造",
                "syntax": "なし（エラーカテゴリ）",
                "examples": [
                    "【エラー例1: ENDIF without matching IF】",
                    "原因: ENDIF があるが対応する IF がない",
                    "対処: IF ステップを追加するか、不要な ENDIF を削除",
                    "",
                    "【エラー例2: Unclosed IF block】",
                    "原因: IF ブロックが閉じられていない",
                    "対処: ENDIF ステップを追加してブロックを閉じる",
                    "",
                    "【エラー例3: ELSE without matching IF】",
                    "原因: ELSE が IF ブロック外にある",
                    "対処: ELSE を IF...ENDIF ブロック内に移動",
                    "",
                    "【エラー例4: BREAK outside of LOOP or FOREACH】",
                    "原因: BREAK がループ外で使用されている",
                    "対処: BREAK を LOOP/FOREACH ブロック内に移動、または削除"
                ],
                "notes": [
                    "IF/ENDIF, FOREACH/ENDFOREACH, LOOP/ENDLOOP は必ずペアで使用",
                    "ネスト順序を確認（IFの中にFOREACHがある場合、内側から閉じる）",
                    "ブロック構造を可視化すると分かりやすい"
                ]
            },
            "parser": {
                "summary": "パーサー設定エラー・警告",
                "description": "プロンプト出力形式とパーサー設定の不整合",
                "syntax": "なし（エラーカテゴリ）",
                "examples": [
                    "【警告1: Prompt expects JSON but parser is not configured for JSON】",
                    "原因: プロンプトでJSON出力を指示しているが、パーサーがJSON用でない",
                    "対処: パーサーを type: json または json_path に変更",
                    "例: {\"type\": \"json\"} または {\"type\": \"json_path\", \"paths\": {\"ANSWER\": \"$.answer\"}}",
                    "",
                    "【警告2: Parser expects JSON but prompt does not instruct JSON output】",
                    "原因: パーサーがJSON形式を期待しているが、プロンプトにJSON出力指示がない",
                    "対処A: プロンプトに「JSON形式で出力してください」等の指示を追加",
                    "対処B: パーサーを type: regex に変更",
                    "",
                    "【警告3: Prompt expects single letter answer but parser is JSON】",
                    "原因: A/B/C/D形式の回答を期待しているが、JSONパーサーを使用",
                    "対処: パーサーを type: regex, patterns: {\"ANSWER\": \"[A-D]\"} に変更",
                    "",
                    "【警告4: References {{ステップ名.FIELD}} but field not found in parser】",
                    "原因: 後続ステップがパーサーに存在しないフィールドを参照",
                    "対処A: パーサー設定にフィールドを追加",
                    "対処B: 参照を正しいフィールド名に修正",
                    "",
                    "【警告5: References {{ステップ名.FIELD}} but step has no parser】",
                    "原因: プロンプトステップにパーサー設定がないのにフィールドを参照",
                    "対処: プロンプトにパーサー設定を追加"
                ],
                "notes": [
                    "パーサータイプと期待される出力形式を一致させる",
                    "json: JSON全体をパース → プロンプトで JSON形式を指示",
                    "json_path: JSONの特定パスを抽出 → プロンプトで JSON形式を指示",
                    "regex: 正規表現で抽出 → プロンプトで特定パターンの出力を指示",
                    "none: パースしない → フィールド参照は使用不可"
                ]
            },
            "reference": {
                "summary": "変数・ステップ参照エラー",
                "description": "未定義の変数やステップへの参照",
                "syntax": "なし（エラーカテゴリ）",
                "examples": [
                    "【エラー1: Reference to undefined step 'xxx'】",
                    "原因: 存在しないステップ名を参照",
                    "対処A: ステップ名のスペルを確認・修正",
                    "対処B: 参照先のステップが参照元より前に存在するか確認",
                    "",
                    "【エラー2: Reference to undefined variable '{{vars.xxx}}'】",
                    "原因: SET ステップで定義されていない変数を参照",
                    "対処A: 参照より前に SET ステップで変数を定義",
                    "対処B: 変数名のスペルを確認・修正",
                    "対処C: ワークフロー入力の場合は {{input.xxx}} を使用",
                    "",
                    "【提案例: Did you mean 'ask'?】",
                    "→ スペルミスの可能性。提案された名前を確認"
                ],
                "notes": [
                    "ステップは定義順に参照可能（後のステップから前のステップを参照）",
                    "変数は SET ステップで定義後に参照可能",
                    "FOREACH の item_var は FOREACH ブロック内でのみ有効",
                    "大文字小文字は区別される"
                ]
            },
            "input_mapping": {
                "summary": "input_mapping エラー・警告",
                "description": "プロンプトパラメータと input_mapping の不一致",
                "syntax": "なし（エラーカテゴリ）",
                "examples": [
                    "【エラー: Case mismatch - prompt has '{{QUESTION}}' but input_mapping has 'question'】",
                    "原因: プロンプトのパラメータ名と input_mapping のキーで大文字小文字が不一致",
                    "対処: input_mapping のキーをプロンプトのパラメータ名と一致させる",
                    "修正例: {\"question\": \"...\"} → {\"QUESTION\": \"...\"}",
                    "",
                    "【警告: Prompt parameters '{{QUESTION}}' not found in input_mapping】",
                    "原因: プロンプトにパラメータがあるが input_mapping に対応するキーがない",
                    "対処: input_mapping にキーを追加",
                    "追加例: {\"QUESTION\": \"{{vars.ROW.question}}\"}",
                    "",
                    "【警告: Fixed text in input_mapping】",
                    "原因: input_mapping に固定テキストが設定されている",
                    "対処: 再利用性のため変数参照に変更を検討",
                    "例: \"テスト\" → \"{{input.text}}\""
                ],
                "notes": [
                    "プロンプトの {{PARAM}} と input_mapping のキーは完全一致が必要",
                    "大文字小文字の不一致は最も多いエラー原因",
                    "プロンプトのパラメータは get_prompt で確認可能"
                ]
            },
            "config": {
                "summary": "ステップ設定エラー",
                "description": "ステップタイプや condition_config の設定不備",
                "syntax": "なし（エラーカテゴリ）",
                "examples": [
                    "【エラー: Invalid step type 'xxx'】",
                    "原因: 無効なステップタイプを指定",
                    "対処: 有効なタイプ (prompt, set, if, foreach, output等) を使用",
                    "",
                    "【エラー: IF step requires condition_config】",
                    "原因: IF ステップに条件設定がない",
                    "対処: condition_config を追加",
                    "例: {\"left\": \"{{ask.ANSWER}}\", \"operator\": \"==\", \"right\": \"A\"}",
                    "",
                    "【エラー: SET step requires 'assignments' in condition_config】",
                    "原因: SET ステップに代入設定がない",
                    "対処: assignments を追加",
                    "例: {\"assignments\": {\"counter\": \"0\"}}",
                    "",
                    "【エラー: FOREACH missing 'source' or 'list_ref'】",
                    "原因: FOREACH にデータソースが指定されていない",
                    "対処: list_ref を追加",
                    "例: {\"item_var\": \"ROW\", \"list_ref\": \"dataset:6\"}"
                ],
                "notes": [
                    "各ステップタイプに必要な設定を確認",
                    "help(topic='workflow', entry='if') 等で詳細を確認"
                ]
            },
            "step_name": {
                "summary": "ステップ名エラー",
                "description": "ステップ名の重複や予約語との衝突",
                "syntax": "なし（エラーカテゴリ）",
                "examples": [
                    "【エラー: Duplicate step name 'xxx'】",
                    "原因: 同じ名前のステップが複数存在",
                    "対処: ユニークな名前に変更",
                    "",
                    "【エラー: Step name 'input' is reserved】",
                    "原因: 予約語 (input, vars) をステップ名に使用",
                    "対処: 別の名前を使用 (例: input_step, init等)",
                    "",
                    "【エラー: Invalid step name format】",
                    "原因: ステップ名に無効な文字が含まれる",
                    "対処: 英字で始まり、英数字とアンダースコアのみ使用"
                ],
                "notes": [
                    "予約語: input, vars, _meta, _error, _execution_trace",
                    "ステップ名は英字始まり、英数字とアンダースコアのみ"
                ]
            },
            "formula": {
                "summary": "関数・数式エラー",
                "description": "関数名や引数の誤り",
                "syntax": "なし（エラーカテゴリ）",
                "examples": [
                    "【エラー: Unknown function 'xxx'】",
                    "原因: 存在しない関数名を使用",
                    "対処: 正しい関数名を使用",
                    "参照: help(topic='functions') で利用可能な関数を確認",
                    "",
                    "【エラー: Function 'replace' requires at least 3 arguments】",
                    "原因: 関数に必要な引数が不足",
                    "対処: 必要な引数をすべて指定",
                    "例: replace(text, old, new)"
                ],
                "notes": [
                    "利用可能な関数: calc, upper, lower, trim, concat, replace等",
                    "help(topic='functions') で全関数を確認"
                ]
            },
            "prompt_template": {
                "summary": "プロンプトテンプレートエラー",
                "description": "プロンプトテンプレートの構文問題",
                "syntax": "なし（エラーカテゴリ）",
                "examples": [
                    "【エラー: Prompt template contains workflow variables {{vars.xxx}}】",
                    "原因: プロンプトテンプレート内でワークフロー変数を直接参照",
                    "対処: プロンプトは {{PARAM}} 形式、input_mapping で値を渡す",
                    "",
                    "【修正前（NG）】",
                    "プロンプト: 質問: {{vars.ROW.question}}",
                    "",
                    "【修正後（OK）】",
                    "プロンプト: 質問: {{QUESTION}}",
                    "input_mapping: {\"QUESTION\": \"{{vars.ROW.question}}\"}"
                ],
                "notes": [
                    "プロンプトテンプレートは {{PARAM}} 形式のみ",
                    "ワークフロー変数は input_mapping で渡す",
                    "これによりプロンプトの再利用性が向上"
                ]
            }
        }
    },

    # =========================================================================
    # validation トピック - ワークフロー実行前の必須バリデーション
    # =========================================================================
    "validation": {
        "description": "ワークフロー実行前の必須バリデーション - エラー0件必須",
        "overview": """ワークフローは実行前にバリデーションが必須です。
validated=true でないと execute_workflow は実行できません。

【厳格ルール】
- エラー0件 → validated=true → 実行可能
- エラー1件以上 → validated=false → 実行不可
- 警告は無視（警告があっても実行可能）

【フラグがリセットされる操作】
- add_workflow_step
- update_workflow_step
- delete_workflow_step
- add_if_block
- add_foreach_block

ステップ変更後は必ず validate_workflow を再実行してください。""",
        "entries": {
            "lifecycle": {
                "summary": "ワークフローのライフサイクル",
                "description": "作成から実行までの validated フラグの状態遷移",
                "examples": [
                    "1. create_workflow() → validated=false",
                    "2. add_workflow_step() → validated=false (リセット)",
                    "3. add_if_block() → validated=false (リセット)",
                    "4. validate_workflow() → エラー0件なら validated=true",
                    "5. execute_workflow() → validated=true の場合のみ実行可能"
                ],
                "notes": [
                    "ステップを変更するたびに validated=false にリセットされる",
                    "最終的に validate_workflow を実行して validated=true にする必要がある",
                    "validate_workflow の結果で execution_ready を確認可能"
                ]
            },
            "required_flow": {
                "summary": "実行前の必須フロー",
                "description": "execute_workflow を呼ぶ前に必ず行うこと",
                "syntax": """# 正しいフロー
1. ワークフロー作成・ステップ追加
2. validate_workflow(workflow_id)  ← 必須
3. errors=0 を確認
4. execute_workflow(workflow_id, input_params)

# validate_workflow の結果例
{
  "valid": true,
  "errors": 0,
  "warnings": 1,  # 警告があっても実行可能
  "validated": true,
  "execution_ready": true
}""",
                "examples": [
                    "【成功例】\nvalidate_workflow(workflow_id=10)\n→ {\"valid\": true, \"errors\": 0, \"validated\": true}\n→ execute_workflow(workflow_id=10) 実行可能",
                    "【失敗例】\nvalidate_workflow(workflow_id=10)\n→ {\"valid\": false, \"errors\": 2}\n→ execute_workflow(workflow_id=10) はエラーで失敗",
                    "【よくあるエラー】\n\"Workflow 'xxx' (ID=10) is not validated. Run validate_workflow first.\"\n→ validate_workflow を実行してエラーを修正する"
                ],
                "notes": [
                    "validate_workflow はエラーチェックと同時に validated フラグを更新",
                    "エラーがあれば修正してから再度 validate_workflow を実行",
                    "GUIで保存成功した場合は自動で validated=true になる"
                ]
            },
            "common_errors": {
                "summary": "よくあるバリデーションエラー",
                "description": "validate_workflow で検出されるエラーと対処法",
                "examples": [
                    "【IF without ENDIF】\nIF ブロックに対応する ENDIF がない\n→ add_if_block を使用して IF/ENDIF ペアを作成",
                    "【FOREACH without ENDFOREACH】\nFOREACH ブロックに対応する ENDFOREACH がない\n→ add_foreach_block を使用して FOREACH/ENDFOREACH ペアを作成",
                    "【Unknown step reference】\n存在しないステップを参照している\n→ {{step_name.field}} のステップ名を確認",
                    "【Prompt not found】\nprompt_name で指定したプロンプトが存在しない\n→ list_prompts で確認し、正しい名前を設定"
                ],
                "notes": [
                    "制御フロー (IF/FOREACH) は専用ツールで作成する",
                    "参照エラーはステップ名のタイポを確認",
                    "help(topic='troubleshooting') で詳細な対処法を確認"
                ]
            }
        }
    }
}

# =============================================================================
# ツール使用例 (主要なツールのみ)
# =============================================================================

TOOL_EXAMPLES: Dict[str, List[str]] = {
    "list_projects": [
        "list_projects() - 全プロジェクト一覧を取得"
    ],
    "create_project": [
        '{"name": "評価プロジェクト", "description": "LLM評価用"}',
    ],
    "delete_projects": [
        '{"project_ids": [1, 2, 3]}  # 複数プロジェクトを一括論理削除',
    ],
    "list_deleted_projects": [
        "list_deleted_projects() - 削除済みプロジェクト一覧を取得",
    ],
    "restore_project": [
        '{"project_id": 5}  # プロジェクトID 5を復元',
    ],
    "list_deleted_workflows": [
        "list_deleted_workflows() - 削除済みワークフロー一覧を取得",
    ],
    "restore_workflow": [
        '{"workflow_id": 10}  # ワークフローID 10を復元（親プロジェクトが削除済みの場合はエラー）',
    ],
    "create_prompt": [
        '{"project_id": 1, "name": "質問プロンプト", "content": "質問: {{QUESTION}}\\n回答を選択: {{CHOICES}}", "parser_config": {"type": "regex", "patterns": {"ANSWER": "[A-D]"}}}',
    ],
    "create_workflow": [
        '{"project_id": 1, "name": "評価ワークフロー", "description": "データセット評価"}',
    ],
    "add_workflow_step": [
        '{"workflow_id": 1, "step_name": "init", "step_type": "set", "condition_config": {"assignments": {"correct": "0"}}}',
        '{"workflow_id": 1, "step_name": "ask", "step_type": "prompt", "prompt_name": "質問プロンプト", "input_mapping": {"QUESTION": "{{vars.ROW.question}}"}}',
    ],
    "add_foreach_block": [
        '{"workflow_id": 1, "step_name": "loop", "item_var": "ROW", "list_ref": "dataset:6:limit:10"}',
    ],
    "add_if_block": [
        '{"workflow_id": 1, "step_name": "check", "left": "{{ask.ANSWER}}", "operator": "==", "right": "{{vars.ROW.answerKey}}"}',
    ],
    "execute_workflow": [
        '{"workflow_id": 1}  # FOREACHベースのワークフロー (input_params不要)',
        '{"workflow_id": 1, "input_params": {}}  # input_paramsを明示的に空で渡す',
        '{"workflow_id": 1, "input_params": {"QUERY": "テスト質問"}}  # 入力パラメータを指定',
        '# 注: get_workflow の required_params が空ならinput_params省略可能',
    ],
    "list_datasets": [
        "list_datasets() - 全データセット一覧を取得"
    ],
    "preview_dataset_rows": [
        '{"dataset_id": 6, "limit": 5}',
    ],
    "import_huggingface_dataset": [
        '{"dataset_id": "allenai/openbookqa", "split": "train", "name": "openbookqa_train", "limit": 100}',
    ],
}


def get_help_index(tools_dict: dict) -> dict:
    """
    ヘルプインデックスを生成

    Args:
        tools_dict: MCPToolRegistry.tools (tool_name -> ToolDefinition)

    Returns:
        インデックス情報の辞書
    """
    # ツール一覧をカテゴリ別に整理
    tools_by_category = {}
    for category, tool_names in TOOL_CATEGORIES.items():
        category_tools = []
        for name in tool_names:
            if name in tools_dict:
                tool = tools_dict[name]
                # 説明の最初の1文を取得
                desc = tool.description.split('\n')[0][:100]
                category_tools.append({
                    "name": name,
                    "description": desc
                })
        if category_tools:
            tools_by_category[category] = {
                "description": CATEGORY_DESCRIPTIONS.get(category, ""),
                "tools": category_tools
            }

    # トピック一覧
    topics = {}
    for topic_name, topic_data in HELP_TOPICS.items():
        topics[topic_name] = {
            "description": topic_data["description"],
            "entries": list(topic_data.get("entries", {}).keys())
        }

    return {
        "tools": tools_by_category,
        "topics": topics,
        "usage": {
            "tool_help": "help(topic='ツール名') でツールの詳細を表示",
            "topic_help": "help(topic='workflow') でトピックの概要を表示",
            "entry_help": "help(topic='workflow', entry='foreach') で項目の詳細を表示"
        },
        "available_topics": list(HELP_TOPICS.keys())
    }


def get_tool_help(tool_name: str, tools_dict: dict) -> dict:
    """
    ツールのヘルプを取得

    Args:
        tool_name: ツール名
        tools_dict: MCPToolRegistry.tools

    Returns:
        ツールヘルプ情報
    """
    if tool_name not in tools_dict:
        return {
            "error": f"ツール '{tool_name}' が見つかりません",
            "available_tools": list(tools_dict.keys())
        }

    tool = tools_dict[tool_name]

    # カテゴリを特定
    category = None
    for cat, tool_names in TOOL_CATEGORIES.items():
        if tool_name in tool_names:
            category = cat
            break

    return {
        "name": tool_name,
        "category": category,
        "description": tool.description,
        "parameters": [
            {
                "name": p.name,
                "type": p.type,
                "description": p.description,
                "required": p.required,
                "default": p.default,
                "enum": p.enum
            }
            for p in tool.parameters
        ],
        "examples": TOOL_EXAMPLES.get(tool_name, [])
    }


def get_topic_help(topic: str) -> dict:
    """
    トピックの概要ヘルプを取得

    Args:
        topic: トピック名

    Returns:
        トピックヘルプ情報
    """
    if topic not in HELP_TOPICS:
        return {
            "error": f"トピック '{topic}' が見つかりません",
            "available_topics": list(HELP_TOPICS.keys())
        }

    topic_data = HELP_TOPICS[topic]
    entries = topic_data.get("entries", {})

    return {
        "topic": topic,
        "description": topic_data["description"],
        "overview": topic_data.get("overview", ""),
        "entries": {
            name: entry.get("summary", "")
            for name, entry in entries.items()
        },
        "usage": f"help(topic='{topic}', entry='項目名') で詳細を表示"
    }


def get_entry_help(topic: str, entry: str) -> dict:
    """
    トピック内の特定項目のヘルプを取得

    Args:
        topic: トピック名
        entry: 項目名

    Returns:
        項目ヘルプ情報
    """
    if topic not in HELP_TOPICS:
        return {
            "error": f"トピック '{topic}' が見つかりません",
            "available_topics": list(HELP_TOPICS.keys())
        }

    topic_data = HELP_TOPICS[topic]
    entries = topic_data.get("entries", {})

    if entry not in entries:
        return {
            "error": f"トピック '{topic}' に項目 '{entry}' が見つかりません",
            "available_entries": list(entries.keys())
        }

    entry_data = entries[entry]

    return {
        "topic": topic,
        "entry": entry,
        **entry_data
    }

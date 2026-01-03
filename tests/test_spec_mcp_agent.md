# MCP Server & Agent Mode テスト仕様書

## 概要

本ドキュメントはMCPサーバーおよびエージェントモードのテスト仕様を定義する。
TDD（テスト駆動開発）アプローチに基づき、実装前にテストを作成する。

---

## MCPツール一覧（全27ツール）

### コア機能（実行系）
| ツール名 | 説明 | 対応API |
|---------|------|---------|
| `execute_prompt` | プロンプト実行 | POST /api/run/single |
| `get_job_status` | ジョブ状態取得 | GET /api/jobs/{id} |
| `execute_workflow` | ワークフロー実行 | POST /api/workflows/{id}/run |
| `get_workflow_job_status` | WFジョブ状態取得 | GET /api/workflow-jobs/{id} |
| `wait_for_job_completion` | 完了待機ヘルパー | （ポーリング） |
| `execute_batch` | バッチ実行 | POST /api/run/batch |
| `get_job_csv_results` | CSV結果取得 | GET /api/jobs/{id}/csv-preview |

### プロンプト管理（CRUD）
| ツール名 | 説明 | 対応API |
|---------|------|---------|
| `list_prompts` | プロンプト一覧 | GET /api/prompts |
| `get_prompt_details` | プロンプト詳細 | GET /api/prompts/{id} |
| `create_prompt` | プロンプト作成 | POST /api/projects/{id}/prompts |
| `update_prompt` | プロンプト更新 | PUT /api/prompts/{id} |
| `delete_prompt` | プロンプト削除 | DELETE /api/prompts/{id} |
| `get_prompt_revisions` | リビジョン一覧 | GET /api/prompts/{id}/revisions |
| `restore_prompt_revision` | リビジョン復元 | POST /api/prompts/{id}/revisions/{n}/restore |

### ワークフロー管理（CRUD）
| ツール名 | 説明 | 対応API |
|---------|------|---------|
| `list_workflows` | ワークフロー一覧 | GET /api/workflows |
| `create_workflow` | ワークフロー作成 | POST /api/workflows |
| `update_workflow` | ワークフロー更新 | PUT /api/workflows/{id} |
| `delete_workflow` | ワークフロー削除 | DELETE /api/workflows/{id} |
| `clone_workflow` | ワークフロー複製 | POST /api/workflows/{id}/clone |
| `add_workflow_step` | ステップ追加 | POST /api/workflows/{id}/steps |
| `update_workflow_step` | ステップ更新 | PUT /api/workflows/{id}/steps/{step_id} |
| `delete_workflow_step` | ステップ削除 | DELETE /api/workflows/{id}/steps/{step_id} |
| `import_workflow` | JSONインポート | POST /api/workflows/import |
| `export_workflow` | JSONエクスポート | GET /api/workflows/{id}/export |

### データ管理
| ツール名 | 説明 | 対応API |
|---------|------|---------|
| `list_projects` | プロジェクト一覧 | GET /api/projects |
| `list_datasets` | データセット一覧 | GET /api/datasets |
| `get_dataset_preview` | データセットプレビュー | GET /api/datasets/{id}/preview |

---

## 1. MCP Server テスト

### 1.1 API Client テスト (`test_mcp_api_client.py`)

FastAPI バックエンドへのHTTP通信を担当するクライアントのテスト。

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| AC-001 | test_client_initialization | APIクライアント初期化 | base_url が正しく設定される |
| AC-002 | test_client_connection_success | 正常接続テスト | 200 OK でレスポンス取得 |
| AC-003 | test_client_connection_failure | 接続失敗テスト | 適切な例外が発生 |
| AC-004 | test_client_timeout_handling | タイムアウト処理 | タイムアウト例外が発生 |
| AC-005 | test_client_retry_logic | リトライロジック | 指定回数リトライ後に失敗 |

### 1.2 MCP Tool テスト - コア機能

#### 1.2.1 execute_prompt ツール (`test_mcp_tool_execute_prompt.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| EP-001 | test_execute_prompt_success | プロンプト正常実行 | job_id が返される |
| EP-002 | test_execute_prompt_with_params | パラメータ付き実行 | パラメータが正しく渡される |
| EP-003 | test_execute_prompt_invalid_prompt_id | 無効なプロンプトID | エラーメッセージ返却 |
| EP-004 | test_execute_prompt_missing_required_param | 必須パラメータ欠落 | バリデーションエラー |
| EP-005 | test_execute_prompt_with_repeat | 繰り返し実行 | repeat回数分のジョブアイテム作成 |
| EP-006 | test_execute_prompt_with_model_selection | モデル指定実行 | 指定モデルで実行 |
| EP-007 | test_execute_prompt_schema_validation | 入力スキーマ検証 | JSON Schema に準拠 |

#### 1.2.2 get_job_status ツール (`test_mcp_tool_get_job_status.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| GJ-001 | test_get_job_status_pending | pending状態のジョブ取得 | status="pending" |
| GJ-002 | test_get_job_status_running | running状態のジョブ取得 | status="running" |
| GJ-003 | test_get_job_status_done | 完了ジョブ取得 | status="done", results含む |
| GJ-004 | test_get_job_status_error | エラージョブ取得 | status="error", error_message含む |
| GJ-005 | test_get_job_status_not_found | 存在しないジョブID | エラーメッセージ返却 |
| GJ-006 | test_get_job_status_with_items | ジョブアイテム詳細取得 | items配列が返される |

#### 1.2.3 list_prompts ツール (`test_mcp_tool_list_prompts.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| LP-001 | test_list_prompts_all | 全プロンプト一覧 | プロンプト配列が返される |
| LP-002 | test_list_prompts_by_project | プロジェクト絞り込み | 該当プロジェクトのみ |
| LP-003 | test_list_prompts_empty | プロンプトなし | 空配列 |
| LP-004 | test_list_prompts_with_parameters | パラメータ情報付き | parameters フィールド含む |

#### 1.2.4 get_prompt_details ツール (`test_mcp_tool_get_prompt_details.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| PD-001 | test_get_prompt_details_success | プロンプト詳細取得 | name, template, parameters 含む |
| PD-002 | test_get_prompt_details_not_found | 存在しないID | エラーメッセージ |
| PD-003 | test_get_prompt_details_with_revisions | リビジョン情報付き | revision_number 含む |

#### 1.2.5 execute_workflow ツール (`test_mcp_tool_execute_workflow.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| EW-001 | test_execute_workflow_success | ワークフロー正常実行 | workflow_job_id 返却 |
| EW-002 | test_execute_workflow_with_params | パラメータ付き実行 | 初期パラメータが渡される |
| EW-003 | test_execute_workflow_invalid_id | 無効なワークフローID | エラーメッセージ |
| EW-004 | test_execute_workflow_with_model | モデル指定実行 | 指定モデルで全ステップ実行 |

#### 1.2.6 get_workflow_job_status ツール (`test_mcp_tool_get_workflow_job_status.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| WJ-001 | test_get_workflow_job_pending | pending状態取得 | status="pending" |
| WJ-002 | test_get_workflow_job_running | running状態取得 | current_step 情報含む |
| WJ-003 | test_get_workflow_job_done | 完了状態取得 | 全ステップ結果含む |
| WJ-004 | test_get_workflow_job_error | エラー状態取得 | 失敗ステップ情報含む |
| WJ-005 | test_get_workflow_job_not_found | 存在しないID | エラーメッセージ |

#### 1.2.7 wait_for_job_completion ツール (`test_mcp_tool_wait_for_job.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| WC-001 | test_wait_job_immediate_complete | 即時完了ジョブ | 結果が即座に返る |
| WC-002 | test_wait_job_polling | ポーリング待機 | 指定間隔でポーリング |
| WC-003 | test_wait_job_timeout | タイムアウト | タイムアウトエラー |
| WC-004 | test_wait_job_error_result | エラー完了 | エラー結果が返る |

### 1.3 MCP Tool テスト - プロンプト管理

#### 1.3.1 create_prompt ツール (`test_mcp_tool_create_prompt.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| CP-001 | test_create_prompt_success | プロンプト作成 | prompt_id 返却 |
| CP-002 | test_create_prompt_with_template | テンプレート付き | template保存 |
| CP-003 | test_create_prompt_with_parser | パーサー付き | parser_config保存 |
| CP-004 | test_create_prompt_invalid_project | 無効プロジェクト | エラーメッセージ |
| CP-005 | test_create_prompt_empty_name | 空の名前 | バリデーションエラー |

#### 1.3.2 update_prompt ツール (`test_mcp_tool_update_prompt.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| UP-001 | test_update_prompt_name | 名前更新 | name変更 |
| UP-002 | test_update_prompt_template | テンプレート更新 | template変更、リビジョン作成 |
| UP-003 | test_update_prompt_parser | パーサー更新 | parser_config変更 |
| UP-004 | test_update_prompt_not_found | 存在しないID | エラーメッセージ |
| UP-005 | test_update_prompt_no_change | 変更なし | リビジョン作成されない |

#### 1.3.3 delete_prompt ツール (`test_mcp_tool_delete_prompt.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| DP-001 | test_delete_prompt_success | プロンプト削除 | soft delete |
| DP-002 | test_delete_prompt_not_found | 存在しないID | エラーメッセージ |
| DP-003 | test_delete_prompt_in_workflow | WFで使用中 | 警告メッセージ |

#### 1.3.4 get_prompt_revisions ツール (`test_mcp_tool_get_prompt_revisions.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| PR-001 | test_get_revisions_success | リビジョン一覧 | revisions配列 |
| PR-002 | test_get_revisions_empty | リビジョンなし | 空配列 |
| PR-003 | test_get_revisions_not_found | 存在しないID | エラーメッセージ |

#### 1.3.5 restore_prompt_revision ツール (`test_mcp_tool_restore_prompt_revision.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| RPR-001 | test_restore_revision_success | リビジョン復元 | 新リビジョン作成 |
| RPR-002 | test_restore_revision_not_found | 存在しないリビジョン | エラーメッセージ |
| RPR-003 | test_restore_revision_same | 同じリビジョン | 変更なし |

### 1.4 MCP Tool テスト - ワークフロー管理

#### 1.4.1 create_workflow ツール (`test_mcp_tool_create_workflow.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| CW-001 | test_create_workflow_success | ワークフロー作成 | workflow_id 返却 |
| CW-002 | test_create_workflow_with_steps | ステップ付き | steps配列保存 |
| CW-003 | test_create_workflow_empty_name | 空の名前 | バリデーションエラー |
| CW-004 | test_create_workflow_invalid_project | 無効プロジェクト | エラーメッセージ |

#### 1.4.2 update_workflow ツール (`test_mcp_tool_update_workflow.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| UW-001 | test_update_workflow_name | 名前更新 | name変更 |
| UW-002 | test_update_workflow_description | 説明更新 | description変更 |
| UW-003 | test_update_workflow_not_found | 存在しないID | エラーメッセージ |

#### 1.4.3 delete_workflow ツール (`test_mcp_tool_delete_workflow.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| DW-001 | test_delete_workflow_success | ワークフロー削除 | 削除成功 |
| DW-002 | test_delete_workflow_not_found | 存在しないID | エラーメッセージ |
| DW-003 | test_delete_workflow_cascade | 関連ステップ削除 | stepsも削除 |

#### 1.4.4 clone_workflow ツール (`test_mcp_tool_clone_workflow.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| CLW-001 | test_clone_workflow_success | ワークフロー複製 | 新workflow_id |
| CLW-002 | test_clone_workflow_with_new_name | 新名前指定 | 指定名で作成 |
| CLW-003 | test_clone_workflow_not_found | 存在しないID | エラーメッセージ |

#### 1.4.5 add_workflow_step ツール (`test_mcp_tool_add_workflow_step.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| AWS-001 | test_add_step_success | ステップ追加 | step_id 返却 |
| AWS-002 | test_add_step_with_prompt | プロンプト指定 | prompt_id関連付け |
| AWS-003 | test_add_step_with_mapping | 変数マッピング | input_mapping保存 |
| AWS-004 | test_add_step_invalid_workflow | 無効WF ID | エラーメッセージ |
| AWS-005 | test_add_step_invalid_prompt | 無効プロンプトID | エラーメッセージ |
| AWS-006 | test_add_step_control_flow | 制御フロー追加 | IF/ELSE/SET/GOTO |

#### 1.4.6 update_workflow_step ツール (`test_mcp_tool_update_workflow_step.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| UWS-001 | test_update_step_name | ステップ名更新 | name変更 |
| UWS-002 | test_update_step_mapping | マッピング更新 | input_mapping変更 |
| UWS-003 | test_update_step_order | 順序更新 | step_order変更 |
| UWS-004 | test_update_step_not_found | 存在しないID | エラーメッセージ |

#### 1.4.7 delete_workflow_step ツール (`test_mcp_tool_delete_workflow_step.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| DWS-001 | test_delete_step_success | ステップ削除 | 削除成功 |
| DWS-002 | test_delete_step_not_found | 存在しないID | エラーメッセージ |
| DWS-003 | test_delete_step_reorder | 順序再調整 | 残りstepの順序更新 |

#### 1.4.8 import_workflow ツール (`test_mcp_tool_import_workflow.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| IW-001 | test_import_workflow_success | JSONインポート | workflow_id 返却 |
| IW-002 | test_import_workflow_invalid_json | 不正JSON | バリデーションエラー |
| IW-003 | test_import_workflow_missing_prompts | プロンプト欠落 | エラーまたは作成 |

#### 1.4.9 export_workflow ツール (`test_mcp_tool_export_workflow.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| XW-001 | test_export_workflow_success | JSONエクスポート | JSON文字列 |
| XW-002 | test_export_workflow_not_found | 存在しないID | エラーメッセージ |
| XW-003 | test_export_workflow_with_prompts | プロンプト含む | prompts配列含む |

### 1.5 MCP Tool テスト - データ管理

#### 1.5.1 list_projects ツール (`test_mcp_tool_list_projects.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| LPJ-001 | test_list_projects_all | 全プロジェクト一覧 | プロジェクト配列 |
| LPJ-002 | test_list_projects_empty | プロジェクトなし | 空配列 |
| LPJ-003 | test_list_projects_with_stats | 統計情報付き | prompt_count, job_count 含む |

#### 1.5.2 list_datasets ツール (`test_mcp_tool_list_datasets.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| LD-001 | test_list_datasets_all | 全データセット一覧 | データセット配列 |
| LD-002 | test_list_datasets_by_project | プロジェクト絞り込み | 該当プロジェクトのみ |
| LD-003 | test_list_datasets_with_row_count | 行数情報付き | row_count 含む |

#### 1.5.3 get_dataset_preview ツール (`test_mcp_tool_get_dataset_preview.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| DP-001 | test_get_dataset_preview_default | デフォルト行数 | 10行返却 |
| DP-002 | test_get_dataset_preview_limit | 行数指定 | 指定行数返却 |
| DP-003 | test_get_dataset_preview_not_found | 存在しないID | エラーメッセージ |
| DP-004 | test_get_dataset_preview_columns | カラム情報 | columns 配列含む |

#### 1.5.4 execute_batch ツール (`test_mcp_tool_execute_batch.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| EB-001 | test_execute_batch_success | バッチ正常実行 | job_id 返却 |
| EB-002 | test_execute_batch_invalid_prompt | 無効プロンプト | エラーメッセージ |
| EB-003 | test_execute_batch_invalid_dataset | 無効データセット | エラーメッセージ |
| EB-004 | test_execute_batch_with_model | モデル指定 | 指定モデルで実行 |

#### 1.5.5 get_job_csv_results ツール (`test_mcp_tool_get_job_csv.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| CSV-001 | test_get_csv_results_success | CSV結果取得 | CSV形式データ |
| CSV-002 | test_get_csv_results_not_found | 存在しないジョブ | エラーメッセージ |
| CSV-003 | test_get_csv_results_pending_job | 未完了ジョブ | 適切なエラー |
| CSV-004 | test_get_csv_results_truncation | 大量データ | 50行に切り詰め |

#### 1.5.6 list_workflows ツール (`test_mcp_tool_list_workflows.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| LW-001 | test_list_workflows_all | 全ワークフロー一覧 | ワークフロー配列 |
| LW-002 | test_list_workflows_by_project | プロジェクト絞り込み | 該当プロジェクトのみ |
| LW-003 | test_list_workflows_with_steps | ステップ数情報 | step_count 含む |

### 1.6 MCP Server 統合テスト (`test_mcp_integration.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| INT-001 | test_server_startup | サーバー起動 | 正常起動 |
| INT-002 | test_tool_discovery | ツール検出 | 全ツールがリスト |
| INT-003 | test_tool_schema_valid | スキーマ検証 | 全ツールのスキーマが有効 |
| INT-004 | test_execute_and_wait_flow | 実行→待機フロー | 結果取得まで正常動作 |
| INT-005 | test_workflow_full_flow | ワークフロー全体フロー | WF実行→完了まで |
| INT-006 | test_batch_full_flow | バッチ全体フロー | バッチ実行→CSV取得 |
| INT-007 | test_concurrent_tool_calls | 並行ツール呼び出し | 競合なく処理 |

---

## 2. Agent Mode テスト

### 2.1 Database Model テスト (`test_agent_models.py`)

#### 2.1.1 AgentSession モデル

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| AS-001 | test_create_session | セッション作成 | ID自動生成、タイムスタンプ設定 |
| AS-002 | test_session_title_update | タイトル更新 | title変更、updated_at更新 |
| AS-003 | test_session_delete | セッション削除 | 関連メッセージも削除（CASCADE） |
| AS-004 | test_session_list_order | 一覧取得順序 | updated_at降順 |

#### 2.1.2 AgentMessage モデル

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| AM-001 | test_create_user_message | ユーザーメッセージ作成 | role="user" |
| AM-002 | test_create_agent_message | エージェントメッセージ作成 | role="agent" |
| AM-003 | test_create_system_message | システムメッセージ作成 | role="system" |
| AM-004 | test_message_with_job_id | Job ID関連付け | job_id設定 |
| AM-005 | test_message_with_workflow_job_id | WF Job ID関連付け | workflow_job_id設定 |
| AM-006 | test_message_approval_pending | 承認待ち状態 | approval_status="pending" |
| AM-007 | test_message_approval_approved | 承認済み状態 | approval_status="approved" |
| AM-008 | test_message_approval_rejected | 拒否状態 | approval_status="rejected" |
| AM-009 | test_messages_order_in_session | セッション内順序 | created_at昇順 |

### 2.2 Agent API エンドポイントテスト (`test_agent_api.py`)

#### 2.2.1 セッション管理 API

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| API-S01 | test_create_session | POST /api/agent/sessions | 201, session_id返却 |
| API-S02 | test_list_sessions | GET /api/agent/sessions | 200, セッション配列 |
| API-S03 | test_get_session | GET /api/agent/sessions/{id} | 200, セッション詳細 |
| API-S04 | test_update_session_title | PUT /api/agent/sessions/{id} | 200, タイトル更新 |
| API-S05 | test_delete_session | DELETE /api/agent/sessions/{id} | 204, 削除成功 |
| API-S06 | test_get_session_not_found | GET /api/agent/sessions/{invalid} | 404 |

#### 2.2.2 メッセージ管理 API

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| API-M01 | test_send_message | POST /api/agent/sessions/{id}/messages | 201, message_id返却 |
| API-M02 | test_list_messages | GET /api/agent/sessions/{id}/messages | 200, メッセージ配列 |
| API-M03 | test_list_messages_pagination | GET .../messages?limit=10&offset=0 | ページネーション動作 |
| API-M04 | test_send_message_empty | POST (空メッセージ) | 400, バリデーションエラー |
| API-M05 | test_send_message_invalid_session | POST (無効セッション) | 404 |

#### 2.2.3 承認管理 API

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| API-A01 | test_list_pending_approvals | GET /api/agent/approvals/pending | 200, 承認待ち一覧 |
| API-A02 | test_approve_action | POST /api/agent/approvals/{id}/approve | 200, 承認実行 |
| API-A03 | test_reject_action | POST /api/agent/approvals/{id}/reject | 200, 拒否実行 |
| API-A04 | test_approve_not_found | POST /api/agent/approvals/{invalid}/approve | 404 |
| API-A05 | test_approve_already_processed | POST (処理済み) | 400, 重複処理エラー |

#### 2.2.4 エージェント実行 API

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| API-E01 | test_execute_agent_request | POST /api/agent/execute | 200, 実行開始 |
| API-E02 | test_execute_with_prompt | POST (プロンプト実行) | job_id含むレスポンス |
| API-E03 | test_execute_with_workflow | POST (WF実行) | workflow_job_id含むレスポンス |
| API-E04 | test_execute_batch_requires_approval | POST (大量バッチ) | approval_required=true |
| API-E05 | test_execute_status_polling | GET /api/agent/execute/{id}/status | 実行状態取得 |

### 2.3 承認システムテスト (`test_agent_approval.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| APR-001 | test_batch_threshold_check | バッチ閾値チェック | 10件以上で承認要求 |
| APR-002 | test_batch_under_threshold | 閾値未満バッチ | 承認不要で即時実行 |
| APR-003 | test_approval_timeout | 承認タイムアウト | 一定時間で自動キャンセル |
| APR-004 | test_approval_executes_job | 承認後実行 | ジョブが開始される |
| APR-005 | test_rejection_cancels_job | 拒否後キャンセル | ジョブがキャンセル |
| APR-006 | test_multiple_pending_approvals | 複数承認待ち | 全て正しく管理 |

### 2.4 チャット機能テスト (`test_agent_chat.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| CHAT-001 | test_new_chat_creates_session | 新規チャット | セッション自動作成 |
| CHAT-002 | test_message_stored_correctly | メッセージ保存 | DB正しく保存 |
| CHAT-003 | test_auto_title_generation | タイトル自動生成 | 最初のメッセージから生成 |
| CHAT-004 | test_session_switch | セッション切替 | 履歴正しく表示 |
| CHAT-005 | test_session_delete_cascade | セッション削除 | メッセージも削除 |
| CHAT-006 | test_message_with_job_result | ジョブ結果メッセージ | Job結果が関連付け |

### 2.5 UI機能テスト（E2E）(`test_agent_ui_e2e.py`)

| テストID | テスト名 | 説明 | 期待結果 |
|----------|----------|------|----------|
| UI-001 | test_agent_tab_visible | エージェントタブ表示 | タブが表示される |
| UI-002 | test_chat_sidebar_visible | サイドバー表示 | 履歴リスト表示 |
| UI-003 | test_new_chat_button | 新規チャットボタン | クリックでセッション作成 |
| UI-004 | test_message_input_send | メッセージ送信 | 入力→送信→表示 |
| UI-005 | test_agent_response_display | エージェント応答表示 | 応答が正しく表示 |
| UI-006 | test_approval_buttons_visible | 承認ボタン表示 | 承認/拒否ボタン表示 |
| UI-007 | test_approval_button_click | 承認ボタンクリック | API呼び出し、状態更新 |
| UI-008 | test_session_history_click | 履歴クリック | セッション切替 |
| UI-009 | test_session_delete_button | 削除ボタン | 確認ダイアログ→削除 |
| UI-010 | test_loading_indicator | ローディング表示 | 処理中表示 |

---

## 3. テスト環境・前提条件

### 3.1 テスト用フィクスチャ

```python
# conftest.py で定義

@pytest.fixture
def test_db():
    """テスト用SQLiteデータベース（インメモリ）"""

@pytest.fixture
def test_client():
    """FastAPI TestClient"""

@pytest.fixture
def sample_project():
    """サンプルプロジェクト"""

@pytest.fixture
def sample_prompt():
    """サンプルプロンプト（パラメータ付き）"""

@pytest.fixture
def sample_workflow():
    """サンプルワークフロー（3ステップ）"""

@pytest.fixture
def sample_dataset():
    """サンプルデータセット（10行）"""

@pytest.fixture
def sample_agent_session():
    """サンプルエージェントセッション"""

@pytest.fixture
def mock_llm_response():
    """LLMレスポンスモック"""
```

### 3.2 モック対象

| 対象 | モック方法 | 理由 |
|------|-----------|------|
| LLM API呼び出し | `unittest.mock.patch` | 外部依存排除、テスト高速化 |
| 時間関連 | `freezegun` | タイムスタンプテスト |
| ファイルシステム | `tmp_path` fixture | 分離環境 |

### 3.3 テスト実行コマンド

```bash
# 全テスト実行
pytest tests/ -v

# MCPサーバーテストのみ
pytest tests/test_mcp_*.py -v

# Agentモードテストのみ
pytest tests/test_agent_*.py -v

# カバレッジ付き
pytest tests/ --cov=mcp_server --cov=app/routes/agent --cov-report=html

# 特定テストID
pytest tests/ -k "EP-001 or GJ-001"
```

---

## 4. テスト優先度

### 4.1 Phase 1（必須・ブロッカー）

| 優先度 | テストファイル | 理由 |
|--------|---------------|------|
| P0 | test_mcp_api_client.py | 全ツールの基盤 |
| P0 | test_mcp_tool_execute_prompt.py | コア機能 |
| P0 | test_mcp_tool_get_job_status.py | コア機能 |
| P0 | test_agent_models.py | DB基盤 |
| P0 | test_agent_api.py (セッション) | UI基盤 |

### 4.2 Phase 2（重要）

| 優先度 | テストファイル | 理由 |
|--------|---------------|------|
| P1 | test_mcp_tool_list_prompts.py | ツール探索 |
| P1 | test_mcp_tool_execute_workflow.py | WF機能 |
| P1 | test_agent_api.py (メッセージ) | チャット機能 |
| P1 | test_agent_approval.py | 承認機能 |

### 4.3 Phase 3（推奨）

| 優先度 | テストファイル | 理由 |
|--------|---------------|------|
| P2 | test_mcp_tool_*.py (残り) | 管理ツール |
| P2 | test_mcp_integration.py | 統合テスト |
| P2 | test_agent_chat.py | チャットUX |
| P2 | test_agent_ui_e2e.py | E2Eテスト |

---

## 5. 受け入れ基準

### 5.1 MCPサーバー

- [ ] 全12ツールが正常動作
- [ ] ツールスキーマがMCP仕様準拠
- [ ] エラーハンドリングが適切
- [ ] 出力サイズが10Kトークン以下
- [ ] Claude Code/Desktopから接続可能

### 5.2 エージェントモード

- [ ] セッション作成・一覧・削除が動作
- [ ] メッセージ送受信が動作
- [ ] 承認フローが動作
- [ ] ChatGPT風UIが表示
- [ ] 履歴切替が動作

---

## 6. テストコード実装ファイル一覧

```
tests/
├── conftest.py                           # 共通フィクスチャ
│
├── # MCP APIクライアント
├── test_mcp_api_client.py
│
├── # MCP コア機能（実行系）
├── test_mcp_tool_execute_prompt.py
├── test_mcp_tool_get_job_status.py
├── test_mcp_tool_execute_workflow.py
├── test_mcp_tool_get_workflow_job_status.py
├── test_mcp_tool_wait_for_job.py
├── test_mcp_tool_execute_batch.py
├── test_mcp_tool_get_job_csv.py
│
├── # MCP プロンプト管理
├── test_mcp_tool_list_prompts.py
├── test_mcp_tool_get_prompt_details.py
├── test_mcp_tool_create_prompt.py        # NEW
├── test_mcp_tool_update_prompt.py        # NEW
├── test_mcp_tool_delete_prompt.py        # NEW
├── test_mcp_tool_get_prompt_revisions.py # NEW
├── test_mcp_tool_restore_prompt_revision.py # NEW
│
├── # MCP ワークフロー管理
├── test_mcp_tool_list_workflows.py
├── test_mcp_tool_create_workflow.py      # NEW
├── test_mcp_tool_update_workflow.py      # NEW
├── test_mcp_tool_delete_workflow.py      # NEW
├── test_mcp_tool_clone_workflow.py       # NEW
├── test_mcp_tool_add_workflow_step.py    # NEW
├── test_mcp_tool_update_workflow_step.py # NEW
├── test_mcp_tool_delete_workflow_step.py # NEW
├── test_mcp_tool_import_workflow.py      # NEW
├── test_mcp_tool_export_workflow.py      # NEW
│
├── # MCP データ管理
├── test_mcp_tool_list_projects.py
├── test_mcp_tool_list_datasets.py
├── test_mcp_tool_get_dataset_preview.py
│
├── # MCP 統合テスト
├── test_mcp_integration.py
│
├── # Agent Mode
├── test_agent_models.py                  # DBモデル
├── test_agent_api.py                     # APIエンドポイント
├── test_agent_approval.py                # 承認システム
├── test_agent_chat.py                    # チャット機能
└── test_agent_ui_e2e.py                  # E2Eテスト
```

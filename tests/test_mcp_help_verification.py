"""
MCP Help Tool Content Verification Tests
MCPヘルプツールの記載内容が正しいかを検証するテスト

試験カテゴリ:
1. ツールカテゴリ検証 - 記載ツールがMCPToolRegistryに存在するか
2. ワークフローステップタイプ検証 - 記載ステップタイプがCONTROL_FLOW_TYPESに存在するか
3. 関数検証 - 記載関数がSTRING_FUNCTIONSに存在し動作するか
4. プロンプトパラメータ検証 - 記載パラメータタイプが動作するか
5. パーサー検証 - 記載パーサータイプが動作するか
6. 条件演算子検証 - 記載演算子が動作するか
7. データセット参照構文検証 - 記載構文がパースできるか
8. ヘルプ出力整合性検証 - ヘルプ出力が期待通りか
"""

import pytest
import json
import sys
import os
import re

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.mcp.tools import get_tool_registry, MCPToolRegistry
from backend.mcp.help_data import (
    TOOL_CATEGORIES,
    CATEGORY_DESCRIPTIONS,
    HELP_TOPICS,
    TOOL_EXAMPLES
)
from backend.workflow import WorkflowManager
from backend.prompt import PromptTemplateParser
from backend.parser import ResponseParser, ParserType


class TestToolCategoriesVerification:
    """1. ツールカテゴリ検証 - 記載ツールがMCPToolRegistryに存在するか"""

    @pytest.fixture
    def registry(self):
        return get_tool_registry()

    def test_all_categories_have_description(self):
        """全カテゴリに説明があること"""
        for category in TOOL_CATEGORIES.keys():
            assert category in CATEGORY_DESCRIPTIONS, \
                f"カテゴリ '{category}' に説明がありません"

    def test_all_listed_tools_exist_in_registry(self, registry):
        """TOOL_CATEGORIESに記載された全ツールがレジストリに存在すること"""
        missing_tools = []
        for category, tool_names in TOOL_CATEGORIES.items():
            for tool_name in tool_names:
                if tool_name not in registry.tools:
                    missing_tools.append(f"{category}/{tool_name}")

        assert not missing_tools, \
            f"以下のツールがレジストリに存在しません: {missing_tools}"

    def test_tool_count_matches(self, registry):
        """記載ツール数とレジストリのツール数が一致すること (helpツールを除く)"""
        listed_count = sum(len(tools) for tools in TOOL_CATEGORIES.values())
        # helpツールは除外
        registry_count = len([t for t in registry.tools.keys() if t != 'help'])

        assert listed_count == registry_count, \
            f"記載ツール数({listed_count}) != レジストリ({registry_count})"

    def test_no_duplicate_tools_across_categories(self):
        """カテゴリ間でツールの重複がないこと"""
        all_tools = []
        for tools in TOOL_CATEGORIES.values():
            all_tools.extend(tools)

        duplicates = [t for t in all_tools if all_tools.count(t) > 1]
        assert not duplicates, f"重複ツール: {set(duplicates)}"


class TestWorkflowStepTypesVerification:
    """2. ワークフローステップタイプ検証"""

    def test_documented_step_types_exist(self):
        """ヘルプに記載されたステップタイプがCONTROL_FLOW_TYPESに存在すること"""
        workflow_entries = HELP_TOPICS["workflow"]["entries"]
        control_flow_types = WorkflowManager.CONTROL_FLOW_TYPES

        # ヘルプに記載されているステップタイプ (promptは除く、variablesとoperatorsも除く)
        step_type_entries = [
            "set", "foreach", "endforeach", "if", "elif", "else", "endif",
            "loop", "endloop", "break", "continue", "output"
        ]

        for step_type in step_type_entries:
            assert step_type in workflow_entries, \
                f"ステップタイプ '{step_type}' がヘルプに記載されていません"
            assert step_type in control_flow_types, \
                f"ステップタイプ '{step_type}' がCONTROL_FLOW_TYPESに存在しません"

    def test_prompt_step_type_documented(self):
        """promptステップタイプがヘルプに記載されていること"""
        workflow_entries = HELP_TOPICS["workflow"]["entries"]
        assert "prompt" in workflow_entries, \
            "promptステップタイプがヘルプに記載されていません"

    def test_variables_entry_documented(self):
        """変数参照構文がヘルプに記載されていること"""
        workflow_entries = HELP_TOPICS["workflow"]["entries"]
        assert "variables" in workflow_entries, \
            "変数参照構文(variables)がヘルプに記載されていません"

        variables_entry = workflow_entries["variables"]
        assert "examples" in variables_entry, "変数参照の例がありません"

        # 必須パターンが記載されているか
        examples_text = str(variables_entry["examples"])
        assert "input." in examples_text, "{{input.}} パターンが記載されていません"
        assert "vars." in examples_text, "{{vars.}} パターンが記載されていません"

    def test_operators_entry_documented(self):
        """条件演算子がヘルプに記載されていること"""
        workflow_entries = HELP_TOPICS["workflow"]["entries"]
        assert "operators" in workflow_entries, \
            "条件演算子(operators)がヘルプに記載されていません"


class TestFunctionsVerification:
    """3. 関数検証 - 記載関数がSTRING_FUNCTIONSに存在し動作するか"""

    @pytest.fixture
    def workflow_manager(self):
        wm = WorkflowManager.__new__(WorkflowManager)
        wm.step_context = {}
        wm.variables = {}
        wm.input_params = {}
        return wm

    def test_all_documented_functions_exist(self):
        """ヘルプに記載された全関数がSTRING_FUNCTIONSに存在すること"""
        functions_entries = HELP_TOPICS["functions"]["entries"]
        string_functions = WorkflowManager.STRING_FUNCTIONS

        missing_functions = []
        for func_name in functions_entries.keys():
            if func_name not in string_functions:
                missing_functions.append(func_name)

        assert not missing_functions, \
            f"以下の関数がSTRING_FUNCTIONSに存在しません: {missing_functions}"

    def test_function_upper(self, workflow_manager):
        """upper関数が正しく動作すること"""
        result = workflow_manager._evaluate_formula("upper", "hello", {})
        assert result == "HELLO", f"upper(hello) = {result}, expected HELLO"

    def test_function_lower(self, workflow_manager):
        """lower関数が正しく動作すること"""
        result = workflow_manager._evaluate_formula("lower", "HELLO", {})
        assert result == "hello", f"lower(HELLO) = {result}, expected hello"

    def test_function_trim(self, workflow_manager):
        """trim関数が正しく動作すること"""
        result = workflow_manager._evaluate_formula("trim", "  hello  ", {})
        assert result == "hello", f"trim() = '{result}', expected 'hello'"

    def test_function_length(self, workflow_manager):
        """length関数が正しく動作すること"""
        result = workflow_manager._evaluate_formula("length", "hello", {})
        assert str(result) == "5", f"length(hello) = {result}, expected 5"

    def test_function_calc(self, workflow_manager):
        """calc関数が正しく動作すること"""
        result = workflow_manager._evaluate_formula("calc", "1 + 2", {})
        assert result in ["3", 3, "3.0"], f"calc(1+2) = {result}, expected 3"

    def test_function_concat(self, workflow_manager):
        """concat関数が正しく動作すること"""
        result = workflow_manager._evaluate_formula("concat", "a, -, b", {})
        assert result == "a-b", f"concat(a, -, b) = {result}, expected a-b"

    def test_function_default(self, workflow_manager):
        """default関数が正しく動作すること"""
        result = workflow_manager._evaluate_formula("default", ", fallback", {})
        assert result == "fallback", f"default(, fallback) = {result}, expected fallback"

    def test_function_contains(self, workflow_manager):
        """contains関数が正しく動作すること"""
        result = workflow_manager._evaluate_formula("contains", "hello world, world", {})
        assert result in [True, "true", "True"], f"contains = {result}, expected true"

    def test_function_split(self, workflow_manager):
        """split関数が正しく動作すること"""
        step_context = {"step": {"text": "a:b:c"}}
        result = workflow_manager._evaluate_formula("split", "{{step.text}}, :", step_context)
        if isinstance(result, str):
            parsed = json.loads(result)
            assert parsed == ["a", "b", "c"], f"split = {parsed}"
        else:
            assert result == ["a", "b", "c"], f"split = {result}"

    def test_function_format_choices(self, workflow_manager):
        """format_choices関数が正しく動作すること"""
        choices_json = '{"label": ["A", "B"], "text": ["Option 1", "Option 2"]}'
        result = workflow_manager._evaluate_formula("format_choices", choices_json, {})
        assert "A" in str(result) and "Option" in str(result), \
            f"format_choices result: {result}"

    def test_all_functions_have_required_fields(self):
        """全関数エントリに必須フィールドがあること"""
        functions_entries = HELP_TOPICS["functions"]["entries"]
        required_fields = ["summary", "syntax"]

        for func_name, func_data in functions_entries.items():
            for field in required_fields:
                assert field in func_data, \
                    f"関数 '{func_name}' に '{field}' フィールドがありません"


class TestPromptParameterTypesVerification:
    """4. プロンプトパラメータ検証 - 記載パラメータタイプが動作するか"""

    def test_all_parameter_types_documented(self):
        """全パラメータタイプがヘルプに記載されていること"""
        prompt_entries = HELP_TOPICS["prompt"]["entries"]

        expected_types = ["TEXT", "NUM", "DATE", "DATETIME", "FILE", "FILEPATH", "TEXTFILEPATH"]
        for param_type in expected_types:
            assert param_type in prompt_entries, \
                f"パラメータタイプ '{param_type}' がヘルプに記載されていません"

    def test_optional_syntax_documented(self):
        """オプショナル構文がヘルプに記載されていること"""
        prompt_entries = HELP_TOPICS["prompt"]["entries"]
        assert "optional" in prompt_entries, \
            "オプショナル構文がヘルプに記載されていません"

    def test_roles_documented(self):
        """ロールマーカーがヘルプに記載されていること"""
        prompt_entries = HELP_TOPICS["prompt"]["entries"]
        assert "roles" in prompt_entries, \
            "ロールマーカーがヘルプに記載されていません"

        roles_entry = prompt_entries["roles"]
        examples_text = str(roles_entry.get("examples", []))
        assert "[SYSTEM]" in examples_text, "[SYSTEM]マーカーが記載されていません"
        assert "[USER]" in examples_text, "[USER]マーカーが記載されていません"

    def test_text5_default_parsing(self):
        """デフォルトパラメータタイプ(TEXT5)が正しく解析されること"""
        parser = PromptTemplateParser()
        params = parser.parse_template("{{PARAM}}")
        assert len(params) == 1
        assert params[0].type == "TEXT5", f"デフォルトタイプ: {params[0].type}"

    def test_textn_parsing(self):
        """TEXTnパラメータタイプが正しく解析されること"""
        parser = PromptTemplateParser()
        params = parser.parse_template("{{PARAM:TEXT10}}")
        assert params[0].type == "TEXT10"

    def test_num_parsing(self):
        """NUMパラメータタイプが正しく解析されること"""
        parser = PromptTemplateParser()
        params = parser.parse_template("{{PARAM:NUM}}")
        assert params[0].type == "NUM"

    def test_file_parsing(self):
        """FILEパラメータタイプが正しく解析されること"""
        parser = PromptTemplateParser()
        params = parser.parse_template("{{PARAM:FILE}}")
        assert params[0].type == "FILE"

    def test_filepath_parsing(self):
        """FILEPATHパラメータタイプが正しく解析されること"""
        parser = PromptTemplateParser()
        params = parser.parse_template("{{PARAM:FILEPATH}}")
        assert params[0].type == "FILEPATH"

    def test_optional_parsing(self):
        """オプショナルパラメータが正しく解析されること"""
        parser = PromptTemplateParser()
        params = parser.parse_template("{{PARAM|}}")
        assert params[0].required == False, "| ありはオプショナル"

    def test_optional_with_default_parsing(self):
        """デフォルト値付きオプショナルパラメータが正しく解析されること"""
        parser = PromptTemplateParser()
        params = parser.parse_template("{{PARAM|default=test}}")
        assert params[0].required == False
        assert params[0].default == "test"


class TestParserTypesVerification:
    """5. パーサー検証 - 記載パーサータイプが動作するか"""

    def test_all_parser_types_documented(self):
        """全パーサータイプがヘルプに記載されていること"""
        parser_entries = HELP_TOPICS["parser"]["entries"]

        expected_types = ["json", "json_path", "regex", "csv_output"]
        for parser_type in expected_types:
            assert parser_type in parser_entries, \
                f"パーサータイプ '{parser_type}' がヘルプに記載されていません"

    def test_json_parser_works(self):
        """JSONパーサーが正しく動作すること"""
        config = {"type": "json", "fields": ["answer", "score"]}
        parser = ResponseParser(config)
        response = '{"answer": "A", "score": 85}'
        result = parser.parse(response)
        assert result["parsed"] == True
        assert "answer" in result.get("fields", result)

    def test_json_path_parser_works(self):
        """JSON Pathパーサーが正しく動作すること"""
        config = {
            "type": "json_path",
            "paths": {"answer": "$.answer", "nested": "$.data.value"}
        }
        parser = ResponseParser(config)
        response = '{"answer": "B", "data": {"value": 100}}'
        result = parser.parse(response)
        assert result["parsed"] == True

    def test_regex_parser_works(self):
        """正規表現パーサーが正しく動作すること"""
        config = {
            "type": "regex",
            "patterns": {"ANSWER": "[A-D]"}
        }
        parser = ResponseParser(config)
        response = "The answer is B."
        result = parser.parse(response)
        assert result["parsed"] == True
        fields = result.get("fields", result)
        assert fields.get("ANSWER") == "B"

    def test_csv_output_documented(self):
        """CSV出力設定がヘルプに記載されていること"""
        parser_entries = HELP_TOPICS["parser"]["entries"]
        csv_entry = parser_entries["csv_output"]
        assert "csv_template" in str(csv_entry), "csv_templateが記載されていません"
        assert "csv_header" in str(csv_entry), "csv_headerが記載されていません"


class TestOperatorsVerification:
    """6. 条件演算子検証 - 記載演算子が動作するか"""

    def test_operators_documented(self):
        """全演算子がヘルプに記載されていること"""
        operators_entry = HELP_TOPICS["workflow"]["entries"]["operators"]
        examples_text = str(operators_entry.get("examples", []))

        expected_operators = ["==", "!=", ">", "<", ">=", "<=", "contains", "empty", "not_empty"]
        for op in expected_operators:
            assert op in examples_text, f"演算子 '{op}' がヘルプに記載されていません"

    def test_operators_count(self):
        """演算子の数が正しいこと (9種類)"""
        operators_entry = HELP_TOPICS["workflow"]["entries"]["operators"]
        examples = operators_entry.get("examples", [])
        assert len(examples) >= 9, f"演算子の数: {len(examples)}, expected >= 9"


class TestDatasetRefVerification:
    """7. データセット参照構文検証 - 記載構文がパースできるか"""

    def test_all_dataset_ref_patterns_documented(self):
        """全データセット参照パターンがヘルプに記載されていること"""
        dataset_entries = HELP_TOPICS["dataset_ref"]["entries"]

        expected_patterns = ["basic", "column", "multiple_columns", "limit"]
        for pattern in expected_patterns:
            assert pattern in dataset_entries, \
                f"データセット参照パターン '{pattern}' がヘルプに記載されていません"

    def test_basic_pattern_example(self):
        """基本パターン(dataset:ID)の例が正しいこと"""
        basic_entry = HELP_TOPICS["dataset_ref"]["entries"]["basic"]
        examples = basic_entry.get("examples", [])
        assert any("dataset:" in ex for ex in examples), \
            "基本パターンの例がありません"

    def test_limit_pattern_example(self):
        """制限パターン(limit:N)の例が正しいこと"""
        limit_entry = HELP_TOPICS["dataset_ref"]["entries"]["limit"]
        examples = limit_entry.get("examples", [])
        assert any("limit:" in ex for ex in examples), \
            "制限パターンの例がありません"


class TestHelpOutputConsistency:
    """8. ヘルプ出力整合性検証 - ヘルプ出力が期待通りか"""

    @pytest.fixture
    def registry(self):
        return get_tool_registry()

    def test_help_index_contains_all_categories(self, registry):
        """help()がすべてのカテゴリを返すこと"""
        result = registry._help()

        tools = result.get("tools", {})
        for category in TOOL_CATEGORIES.keys():
            assert category in tools, \
                f"カテゴリ '{category}' がhelp()の結果に含まれていません"

    def test_help_index_contains_all_topics(self, registry):
        """help()がすべてのトピックを返すこと"""
        result = registry._help()

        topics = result.get("topics", {})
        for topic in HELP_TOPICS.keys():
            assert topic in topics, \
                f"トピック '{topic}' がhelp()の結果に含まれていません"

    def test_help_tool_returns_valid_structure(self, registry):
        """help(topic=ツール名)が正しい構造を返すこと"""
        result = registry._help(topic="list_projects")

        assert "name" in result
        assert "description" in result
        assert "parameters" in result
        assert result["name"] == "list_projects"

    def test_help_topic_returns_valid_structure(self, registry):
        """help(topic=トピック名)が正しい構造を返すこと"""
        result = registry._help(topic="workflow")

        assert "topic" in result
        assert "description" in result
        assert "entries" in result
        assert result["topic"] == "workflow"

    def test_help_entry_returns_valid_structure(self, registry):
        """help(topic, entry)が正しい構造を返すこと"""
        result = registry._help(topic="workflow", entry="foreach")

        assert "topic" in result
        assert "entry" in result
        assert "summary" in result
        assert result["entry"] == "foreach"

    def test_help_unknown_topic_returns_error(self, registry):
        """不明なトピックでエラーが返ること"""
        result = registry._help(topic="unknown_topic")

        assert "error" in result
        assert "available_topics" in result

    def test_help_unknown_entry_returns_error(self, registry):
        """不明なエントリでエラーが返ること"""
        result = registry._help(topic="workflow", entry="unknown_entry")

        assert "error" in result
        assert "available_entries" in result


class TestHelpContentCompleteness:
    """9. ヘルプコンテンツ網羅性検証"""

    def test_all_workflow_entries_have_summary(self):
        """workflowトピックの全エントリにsummaryがあること"""
        entries = HELP_TOPICS["workflow"]["entries"]
        for name, data in entries.items():
            assert "summary" in data, f"workflow/{name} に summary がありません"

    def test_all_functions_entries_have_syntax(self):
        """functionsトピックの全エントリにsyntaxがあること"""
        entries = HELP_TOPICS["functions"]["entries"]
        for name, data in entries.items():
            assert "syntax" in data, f"functions/{name} に syntax がありません"

    def test_all_prompt_entries_have_syntax(self):
        """promptトピックの全エントリにsyntaxがあること"""
        entries = HELP_TOPICS["prompt"]["entries"]
        for name, data in entries.items():
            assert "syntax" in data, f"prompt/{name} に syntax がありません"

    def test_all_parser_entries_have_syntax(self):
        """parserトピックの全エントリにsyntaxがあること"""
        entries = HELP_TOPICS["parser"]["entries"]
        for name, data in entries.items():
            assert "syntax" in data, f"parser/{name} に syntax がありません"

    def test_step_type_entries_have_examples(self):
        """主要ステップタイプエントリにexamplesがあること"""
        step_types = ["set", "foreach", "if", "output", "prompt"]
        entries = HELP_TOPICS["workflow"]["entries"]

        for step_type in step_types:
            assert "examples" in entries[step_type], \
                f"workflow/{step_type} に examples がありません"


class TestToolExamplesVerification:
    """10. ツール使用例検証"""

    def test_key_tools_have_examples(self):
        """主要ツールに使用例があること"""
        key_tools = [
            "create_workflow",
            "add_workflow_step",
            "add_foreach_block",
            "execute_workflow"
        ]

        for tool_name in key_tools:
            assert tool_name in TOOL_EXAMPLES, \
                f"ツール '{tool_name}' に使用例がありません"
            assert len(TOOL_EXAMPLES[tool_name]) > 0, \
                f"ツール '{tool_name}' の使用例が空です"


# =============================================================================
# テスト実行用のメイン
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

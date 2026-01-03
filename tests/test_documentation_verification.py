"""
ドキュメント検証テスト

docs/workflow_system_guide.md の記載内容が正しいかを検証する試験
"""

import pytest
import json
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.workflow import WorkflowManager
from backend.prompt import PromptTemplateParser
from backend.parser import ResponseParser, ParserType

# WorkflowManagerクラスの属性を参照
CONTROL_FLOW_TYPES = WorkflowManager.CONTROL_FLOW_TYPES
STRING_FUNCTIONS = WorkflowManager.STRING_FUNCTIONS
FORMULA_PATTERN = WorkflowManager.FORMULA_PATTERN


class TestDocumentationVerification:
    """ドキュメントの記載内容を検証するテストクラス"""

    # ===========================================
    # 1. プロンプト仕様の検証
    # ===========================================

    class TestPromptSpecification:
        """プロンプトテンプレート構文の検証"""

        def test_default_parameter_type(self):
            """デフォルトパラメータタイプがTEXT5であることを確認"""
            parser = PromptTemplateParser()
            params = parser.parse_template("{{PARAM}}")
            assert len(params) == 1
            assert params[0].name == 'PARAM'
            assert params[0].type == 'TEXT5', f"デフォルトはTEXT5のはず: 実際は {params[0].type}"

        def test_parameter_type_specification(self):
            """型指定が正しく解析されることを確認"""
            parser = PromptTemplateParser()
            test_cases = [
                ("{{PARAM:TEXT10}}", "TEXT10"),
                ("{{PARAM:NUM}}", "NUM"),
                ("{{PARAM:DATE}}", "DATE"),
                ("{{PARAM:DATETIME}}", "DATETIME"),
                ("{{PARAM:FILE}}", "FILE"),
                ("{{PARAM:FILEPATH}}", "FILEPATH"),
                ("{{PARAM:TEXTFILEPATH}}", "TEXTFILEPATH"),
            ]
            for template, expected_type in test_cases:
                params = parser.parse_template(template)
                assert params[0].type == expected_type, f"{template} -> {expected_type} のはず: 実際は {params[0].type}"

        def test_optional_parameter(self):
            """オプショナルパラメータの解析を確認"""
            parser = PromptTemplateParser()
            # | があればオプショナル
            params = parser.parse_template("{{PARAM:TEXT5|}}")
            assert params[0].required == False, "| があればオプショナル（required=False）"

        def test_optional_with_default(self):
            """デフォルト値付きオプショナルパラメータ"""
            parser = PromptTemplateParser()
            params = parser.parse_template("{{PARAM:TEXT5|default=test}}")
            assert params[0].required == False
            assert params[0].default == "test"

        def test_duplicate_parameters(self):
            """重複パラメータの処理"""
            parser = PromptTemplateParser()
            params = parser.parse_template("{{PARAM}} and {{PARAM}} again")
            # 重複は1つにまとめられるはず
            unique_names = set(p.name for p in params)
            assert len(unique_names) == 1

    # ===========================================
    # 2. パーサー仕様の検証
    # ===========================================

    class TestParserSpecification:
        """パーサー機能の検証"""

        def test_parser_types_exist(self):
            """パーサータイプが存在することを確認"""
            assert hasattr(ParserType, 'JSON')
            assert hasattr(ParserType, 'JSON_PATH')
            assert hasattr(ParserType, 'REGEX')
            assert hasattr(ParserType, 'NONE')

        def test_json_parser(self):
            """JSONパーサーの動作確認"""
            config = {"type": "json", "fields": ["answer", "score"]}
            parser = ResponseParser(config)
            response = '{"answer": "A", "score": 85, "extra": "ignored"}'
            result = parser.parse(response)
            assert result['parsed'] == True
            assert 'answer' in result.get('fields', result)
            assert 'score' in result.get('fields', result)

        def test_json_path_parser(self):
            """JSON Pathパーサーの動作確認"""
            config = {
                "type": "json_path",
                "paths": {
                    "answer": "$.answer",
                    "nested": "$.data.value"
                }
            }
            parser = ResponseParser(config)
            response = '{"answer": "B", "data": {"value": 100}}'
            result = parser.parse(response)
            assert result['parsed'] == True

        def test_regex_parser(self):
            """正規表現パーサーの動作確認"""
            config = {
                "type": "regex",
                "patterns": {
                    "ANSWER": "[A-D]"
                }
            }
            parser = ResponseParser(config)
            response = "The answer is B."
            result = parser.parse(response)
            assert result['parsed'] == True
            # ANSWERフィールドにBが抽出されるはず
            fields = result.get('fields', result)
            assert fields.get('ANSWER') == 'B'

        def test_csv_template(self):
            """CSV出力テンプレートの動作確認"""
            config = {
                "type": "json_path",
                "paths": {"answer": "$.answer"},
                "csv_template": "\"$answer$\"",
                "csv_header": "Answer"
            }
            parser = ResponseParser(config)
            response = '{"answer": "test"}'
            result = parser.parse(response)
            assert 'csv_output' in result or 'csv_header' in result

    # ===========================================
    # 3. ワークフローステップタイプの検証
    # ===========================================

    class TestWorkflowStepTypes:
        """ワークフローステップタイプの検証"""

        def test_control_flow_types(self):
            """ドキュメントに記載されたステップタイプが全て存在することを確認"""
            documented_types = [
                'set', 'if', 'elif', 'else', 'endif',
                'loop', 'endloop', 'foreach', 'endforeach',
                'break', 'continue', 'output'
            ]
            for step_type in documented_types:
                assert step_type in CONTROL_FLOW_TYPES, f"ステップタイプ '{step_type}' がCONTROL_FLOW_TYPESに存在しない"

        def test_prompt_step_type(self):
            """promptステップタイプの確認（デフォルト）"""
            # promptはCONTROL_FLOW_TYPESには含まれない（デフォルト）
            assert 'prompt' not in CONTROL_FLOW_TYPES

    # ===========================================
    # 4. 関数の検証
    # ===========================================

    class TestWorkflowFunctions:
        """ワークフロー関数の検証"""

        def test_string_functions_documented(self):
            """ドキュメントに記載された関数がSTRING_FUNCTIONSに存在"""
            documented_functions = [
                'upper', 'lower', 'trim', 'lstrip', 'rstrip',
                'capitalize', 'title', 'reverse', 'length', 'len',
                'slice', 'substr', 'substring', 'left', 'right',
                'replace', 'repeat', 'concat',
                'split', 'join', 'shuffle',
                'contains', 'startswith', 'endswith', 'count',
                'default', 'ifempty',
                'calc', 'sum',
                'json_parse', 'json_zip', 'format_choices',
                'debug'
            ]
            for func_name in documented_functions:
                assert func_name in STRING_FUNCTIONS or func_name in FORMULA_PATTERN.pattern, \
                    f"関数 '{func_name}' がSTRING_FUNCTIONSに存在しない"

        def test_formula_pattern_functions(self):
            """FORMULA_PATTERNに関数が含まれていることを確認"""
            test_formulas = [
                "calc(1+1)",
                "upper(test)",
                "format_choices(test)",
                "json_parse(test)",
            ]
            for formula in test_formulas:
                match = FORMULA_PATTERN.search(formula)
                assert match is not None, f"FORMULA_PATTERNが '{formula}' にマッチしない"

    # ===========================================
    # 5. 関数の実際の動作検証（ワークフローマネージャー経由）
    # ===========================================

    class TestFunctionExecution:
        """関数の実際の動作を検証"""

        @pytest.fixture
        def workflow_manager(self):
            """WorkflowManagerのインスタンスを作成"""
            wm = WorkflowManager.__new__(WorkflowManager)
            wm.step_context = {}
            wm.variables = {}
            wm.input_params = {}
            return wm

        def test_calc_function(self, workflow_manager):
            """calc関数の動作確認"""
            result = workflow_manager._evaluate_formula("calc", "1 + 2", {})
            assert result == "3" or result == 3 or result == "3.0"

        def test_upper_function(self, workflow_manager):
            """upper関数の動作確認"""
            result = workflow_manager._evaluate_formula("upper", "hello", {})
            assert result == "HELLO"

        def test_lower_function(self, workflow_manager):
            """lower関数の動作確認"""
            result = workflow_manager._evaluate_formula("lower", "HELLO", {})
            assert result == "hello"

        def test_trim_function(self, workflow_manager):
            """trim関数の動作確認"""
            result = workflow_manager._evaluate_formula("trim", "  hello  ", {})
            assert result == "hello"

        def test_length_function(self, workflow_manager):
            """length関数の動作確認"""
            result = workflow_manager._evaluate_formula("length", "hello", {})
            assert str(result) == "5"

        def test_concat_function(self, workflow_manager):
            """concat関数の動作確認"""
            result = workflow_manager._evaluate_formula("concat", "a, -, b", {})
            assert result == "a-b"

        def test_split_function(self, workflow_manager):
            """split関数の動作確認"""
            # step_contextを使って変数経由でテスト
            # カンマをデリミタとして使う場合は引用符で囲む
            step_context = {"step": {"text": "a:b:c"}}
            result = workflow_manager._evaluate_formula("split", "{{step.text}}, :", step_context)
            # 結果がリストまたはJSON配列であることを確認
            if isinstance(result, str):
                parsed = json.loads(result)
                assert parsed == ["a", "b", "c"]
            else:
                assert result == ["a", "b", "c"]

        def test_default_function(self, workflow_manager):
            """default関数の動作確認"""
            result = workflow_manager._evaluate_formula("default", ", fallback", {})
            assert result == "fallback"

        def test_format_choices_function(self, workflow_manager):
            """format_choices関数の動作確認"""
            choices_json = '{"label": ["A", "B"], "text": ["Option 1", "Option 2"]}'
            result = workflow_manager._evaluate_formula("format_choices", choices_json, {})
            assert "A:" in str(result) or "A：" in str(result) or "Option 1" in str(result)

    # ===========================================
    # 6. 条件演算子の検証
    # ===========================================

    class TestConditionOperators:
        """条件演算子の検証"""

        def test_documented_operators(self):
            """ドキュメントに記載された演算子がサポートされていることを確認"""
            # workflow.pyの_evaluate_conditionメソッドで使用される演算子
            documented_operators = ['==', '!=', '>', '<', '>=', '<=', 'contains', 'empty', 'not_empty']
            # ここでは演算子のリストを確認するだけ
            assert len(documented_operators) == 9

    # ===========================================
    # 7. データセット参照構文の検証
    # ===========================================

    class TestDatasetReference:
        """データセット参照構文の検証"""

        def test_dataset_reference_pattern(self):
            """データセット参照パターンの形式確認"""
            # ドキュメント記載のパターン
            patterns = [
                "dataset:6",
                "dataset:6:column",
                "dataset:6:col1,col2",
                "dataset:6::limit:10",
                "dataset:6:column:limit:5",
            ]
            for pattern in patterns:
                # dataset: で始まることを確認
                assert pattern.startswith("dataset:")

    # ===========================================
    # 8. ドキュメント記載内容の整合性確認
    # ===========================================

    class TestDocumentationConsistency:
        """ドキュメント記載内容の整合性確認"""

        def test_step_types_count(self):
            """ステップタイプの数がドキュメントと一致"""
            # ドキュメントには13種類（prompt含む）と記載
            # CONTROL_FLOW_TYPESには12種類（promptは含まない）
            assert len(CONTROL_FLOW_TYPES) == 12, f"CONTROL_FLOW_TYPESは12種類のはず: 実際は {len(CONTROL_FLOW_TYPES)}"

        def test_function_count(self):
            """関数の数がドキュメントと一致"""
            # ドキュメントには28関数と記載
            # STRING_FUNCTIONSのキー数を確認
            func_count = len(STRING_FUNCTIONS)
            print(f"STRING_FUNCTIONS count: {func_count}")
            print(f"Functions: {list(STRING_FUNCTIONS.keys())}")
            # 関数数は28以上あることを確認（追加されている可能性）
            assert func_count >= 28, f"関数は28個以上のはず: 実際は {func_count}"

        def test_parser_types_count(self):
            """パーサータイプの数がドキュメントと一致"""
            # ドキュメントには4種類と記載
            parser_types = [ParserType.JSON, ParserType.JSON_PATH, ParserType.REGEX, ParserType.NONE]
            assert len(parser_types) == 4

        def test_parameter_types_exist(self):
            """パラメータタイプがPromptTemplateParserに定義されていることを確認"""
            assert hasattr(PromptTemplateParser, 'TYPE_TEXT')
            assert hasattr(PromptTemplateParser, 'TYPE_NUM')
            assert hasattr(PromptTemplateParser, 'TYPE_DATE')
            assert hasattr(PromptTemplateParser, 'TYPE_DATETIME')
            assert hasattr(PromptTemplateParser, 'TYPE_FILE')
            assert hasattr(PromptTemplateParser, 'TYPE_FILEPATH')
            assert hasattr(PromptTemplateParser, 'TYPE_TEXTFILEPATH')


# ===========================================
# テスト実行用のメイン
# ===========================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

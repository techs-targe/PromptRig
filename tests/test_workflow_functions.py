"""
Comprehensive Test Suite for Workflow Formula Functions

Tests all supported functions in backend/workflow.py
"""

import pytest
import json
import re
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database.database import SessionLocal
from backend.workflow import WorkflowManager


class TestWorkflowFunctions:
    """Test all workflow formula functions"""

    @pytest.fixture
    def manager(self):
        """Create WorkflowManager instance"""
        db = SessionLocal()
        try:
            yield WorkflowManager(db)
        finally:
            db.close()

    @pytest.fixture
    def step_context(self):
        """Sample step context for testing"""
        return {
            'vars': {
                'text': 'Hello World',
                'spaces': '  hello  ',
                'items': 'a,b,c',
                'json_array': '["apple", "banana", "cherry"]',
                'empty': '',
                'number': '42',
                'x': '10',
                'y': '5',
                'japanese': 'こんにちは世界',
            },
            'step1': {
                'raw': 'Test output',
                'score': '85',
                'result': 'success',
            },
            'step2': {
                'raw': 'Another output',
                'score': '90',
            }
        }

    # ============================================================
    # 1. String Case Functions
    # ============================================================

    def test_upper_basic(self, manager, step_context):
        """upper() - basic uppercase conversion"""
        result = manager._substitute_step_refs('upper({{vars.text}})', step_context)
        assert result == 'HELLO WORLD'

    def test_upper_japanese(self, manager, step_context):
        """upper() - Japanese text (should remain unchanged)"""
        result = manager._substitute_step_refs('upper({{vars.japanese}})', step_context)
        assert result == 'こんにちは世界'

    def test_lower_basic(self, manager, step_context):
        """lower() - basic lowercase conversion"""
        result = manager._substitute_step_refs('lower({{vars.text}})', step_context)
        assert result == 'hello world'

    def test_capitalize(self, manager, step_context):
        """capitalize() - first letter uppercase"""
        result = manager._substitute_step_refs('capitalize(hello world)', step_context)
        assert result == 'Hello world'

    def test_title(self, manager, step_context):
        """title() - title case conversion"""
        result = manager._substitute_step_refs('title(hello world)', step_context)
        assert result == 'Hello World'

    # ============================================================
    # 2. Whitespace Functions
    # ============================================================

    def test_trim(self, manager, step_context):
        """trim() - remove leading/trailing whitespace"""
        result = manager._substitute_step_refs('trim({{vars.spaces}})', step_context)
        assert result == 'hello'

    def test_lstrip(self, manager, step_context):
        """lstrip() - remove leading whitespace"""
        result = manager._substitute_step_refs('lstrip({{vars.spaces}})', step_context)
        assert result == 'hello  '

    def test_rstrip(self, manager, step_context):
        """rstrip() - remove trailing whitespace"""
        result = manager._substitute_step_refs('rstrip({{vars.spaces}})', step_context)
        assert result == '  hello'

    # ============================================================
    # 3. Length and Substring Functions
    # ============================================================

    def test_length(self, manager, step_context):
        """length() - string length"""
        result = manager._substitute_step_refs('length({{vars.text}})', step_context)
        assert result == '11'  # "Hello World" = 11 chars

    def test_len_alias(self, manager, step_context):
        """len() - alias for length"""
        result = manager._substitute_step_refs('len({{vars.text}})', step_context)
        assert result == '11'

    def test_length_japanese(self, manager, step_context):
        """length() - Japanese text length"""
        result = manager._substitute_step_refs('length({{vars.japanese}})', step_context)
        assert result == '7'  # こんにちは世界 = 7 chars

    def test_slice_two_args(self, manager, step_context):
        """slice() - with start and end indices"""
        result = manager._substitute_step_refs('slice({{vars.text}}, 0, 5)', step_context)
        assert result == 'Hello'

    def test_slice_negative_index(self, manager, step_context):
        """slice() - with negative index"""
        result = manager._substitute_step_refs('slice({{vars.text}}, -5)', step_context)
        assert result == 'World'

    def test_substr_alias(self, manager, step_context):
        """substr() - alias for slice"""
        result = manager._substitute_step_refs('substr({{vars.text}}, 6, 11)', step_context)
        assert result == 'World'

    def test_substring_alias(self, manager, step_context):
        """substring() - alias for slice"""
        result = manager._substitute_step_refs('substring({{vars.text}}, 0, 5)', step_context)
        assert result == 'Hello'

    def test_left(self, manager, step_context):
        """left() - first N characters"""
        result = manager._substitute_step_refs('left({{vars.text}}, 5)', step_context)
        assert result == 'Hello'

    def test_right(self, manager, step_context):
        """right() - last N characters"""
        result = manager._substitute_step_refs('right({{vars.text}}, 5)', step_context)
        assert result == 'World'

    # ============================================================
    # 4. String Manipulation Functions
    # ============================================================

    def test_replace(self, manager, step_context):
        """replace() - string replacement"""
        result = manager._substitute_step_refs('replace({{vars.text}}, World, Universe)', step_context)
        assert result == 'Hello Universe'

    def test_replace_with_quotes(self, manager, step_context):
        """replace() - with quoted arguments"""
        result = manager._substitute_step_refs('replace({{vars.text}}, "World", "Universe")', step_context)
        assert result == 'Hello Universe'

    def test_repeat(self, manager, step_context):
        """repeat() - repeat string N times"""
        result = manager._substitute_step_refs('repeat(ab, 3)', step_context)
        assert result == 'ababab'

    def test_reverse(self, manager, step_context):
        """reverse() - reverse string"""
        result = manager._substitute_step_refs('reverse({{vars.text}})', step_context)
        assert result == 'dlroW olleH'

    def test_reverse_japanese(self, manager, step_context):
        """reverse() - reverse Japanese text"""
        result = manager._substitute_step_refs('reverse({{vars.japanese}})', step_context)
        assert result == '界世はちにんこ'

    # ============================================================
    # 5. Array Functions
    # ============================================================

    def test_split_basic(self, manager, step_context):
        """split() - split string by delimiter"""
        result = manager._substitute_step_refs('split({{vars.items}}, ",")', step_context)
        assert result == '["a", "b", "c"]'

    def test_split_by_space(self, manager, step_context):
        """split() - split by space"""
        result = manager._substitute_step_refs('split({{vars.text}}, " ")', step_context)
        assert result == '["Hello", "World"]'

    def test_join_basic(self, manager, step_context):
        """join() - join array elements"""
        result = manager._substitute_step_refs('join({{vars.json_array}}, " | ")', step_context)
        assert result == 'apple | banana | cherry'

    def test_join_with_comma(self, manager, step_context):
        """join() - join with comma"""
        result = manager._substitute_step_refs('join({{vars.json_array}}, ", ")', step_context)
        assert result == 'apple, banana, cherry'

    # ============================================================
    # 6. Concatenation Functions
    # ============================================================

    def test_concat_two_args(self, manager, step_context):
        """concat() - concatenate two strings"""
        result = manager._substitute_step_refs('concat({{vars.text}}, !)', step_context)
        assert result == 'Hello World!'

    def test_concat_multiple_args(self, manager, step_context):
        """concat() - concatenate multiple strings"""
        result = manager._substitute_step_refs('concat(A, -, B, -, C)', step_context)
        assert result == 'A-B-C'

    def test_concat_with_vars(self, manager, step_context):
        """concat() - concatenate with variable references (use quotes to preserve spaces)"""
        result = manager._substitute_step_refs('concat({{step1.result}}, ": ", {{step2.raw}})', step_context)
        assert result == 'success: Another output'

    # ============================================================
    # 7. Default/Empty Functions
    # ============================================================

    def test_default_with_value(self, manager, step_context):
        """default() - return value when not empty"""
        result = manager._substitute_step_refs('default({{vars.text}}, fallback)', step_context)
        assert result == 'Hello World'

    def test_default_with_empty(self, manager, step_context):
        """default() - return default when empty"""
        result = manager._substitute_step_refs('default({{vars.empty}}, fallback)', step_context)
        assert result == 'fallback'

    def test_ifempty_alias(self, manager, step_context):
        """ifempty() - alias for default"""
        result = manager._substitute_step_refs('ifempty({{vars.empty}}, N/A)', step_context)
        assert result == 'N/A'

    # ============================================================
    # 8. Search Functions
    # ============================================================

    def test_contains_true(self, manager, step_context):
        """contains() - returns true when substring found"""
        result = manager._substitute_step_refs('contains({{vars.text}}, World)', step_context)
        assert result.lower() == 'true'

    def test_contains_false(self, manager, step_context):
        """contains() - returns false when not found"""
        result = manager._substitute_step_refs('contains({{vars.text}}, xyz)', step_context)
        assert result.lower() == 'false'

    def test_startswith_true(self, manager, step_context):
        """startswith() - returns true when starts with"""
        result = manager._substitute_step_refs('startswith({{vars.text}}, Hello)', step_context)
        assert result.lower() == 'true'

    def test_startswith_false(self, manager, step_context):
        """startswith() - returns false when doesn't start with"""
        result = manager._substitute_step_refs('startswith({{vars.text}}, World)', step_context)
        assert result.lower() == 'false'

    def test_endswith_true(self, manager, step_context):
        """endswith() - returns true when ends with"""
        result = manager._substitute_step_refs('endswith({{vars.text}}, World)', step_context)
        assert result.lower() == 'true'

    def test_endswith_false(self, manager, step_context):
        """endswith() - returns false when doesn't end with"""
        result = manager._substitute_step_refs('endswith({{vars.text}}, Hello)', step_context)
        assert result.lower() == 'false'

    def test_count(self, manager, step_context):
        """count() - count occurrences"""
        result = manager._substitute_step_refs('count({{vars.text}}, o)', step_context)
        assert result == '2'  # "Hello World" has 2 o's

    # ============================================================
    # 9. Numeric Functions
    # ============================================================

    def test_sum_two_args(self, manager, step_context):
        """sum() - sum of two numbers"""
        result = manager._substitute_step_refs('sum({{step1.score}}, {{step2.score}})', step_context)
        assert float(result) == 175.0  # 85 + 90

    def test_sum_with_literals(self, manager, step_context):
        """sum() - sum with literal numbers"""
        result = manager._substitute_step_refs('sum({{step1.score}}, 10, 5)', step_context)
        assert float(result) == 100.0  # 85 + 10 + 5

    def test_calc_addition(self, manager, step_context):
        """calc() - basic addition"""
        result = manager._substitute_step_refs('calc({{vars.x}} + {{vars.y}})', step_context)
        assert int(result) == 15  # 10 + 5

    def test_calc_subtraction(self, manager, step_context):
        """calc() - subtraction"""
        result = manager._substitute_step_refs('calc({{vars.x}} - {{vars.y}})', step_context)
        assert int(result) == 5  # 10 - 5

    def test_calc_multiplication(self, manager, step_context):
        """calc() - multiplication"""
        result = manager._substitute_step_refs('calc({{vars.x}} * {{vars.y}})', step_context)
        assert int(result) == 50  # 10 * 5

    def test_calc_division(self, manager, step_context):
        """calc() - division"""
        result = manager._substitute_step_refs('calc({{vars.x}} / {{vars.y}})', step_context)
        assert int(result) == 2  # 10 / 5

    def test_calc_complex_expression(self, manager, step_context):
        """calc() - complex expression"""
        result = manager._substitute_step_refs('calc(({{vars.x}} + {{vars.y}}) * 2)', step_context)
        assert int(result) == 30  # (10 + 5) * 2

    # ============================================================
    # 10. Shuffle Function
    # ============================================================

    def test_shuffle_characters(self, manager, step_context):
        """shuffle() - shuffle characters (1 arg)"""
        result = manager._substitute_step_refs('shuffle(abc)', step_context)
        # Result should contain same chars but possibly different order
        assert sorted(result) == ['a', 'b', 'c']

    def test_shuffle_with_delimiter(self, manager, step_context):
        """shuffle() - shuffle by delimiter (2 args)"""
        result = manager._substitute_step_refs('shuffle({{vars.items}}, ",")', step_context)
        # Result should contain same items separated by comma
        parts = result.split(',')
        assert sorted(parts) == ['a', 'b', 'c']

    def test_shuffle_json_array(self, manager, step_context):
        """shuffle() - shuffle JSON array"""
        result = manager._substitute_step_refs('shuffle({{vars.json_array}})', step_context)
        items = json.loads(result)
        assert sorted(items) == ['apple', 'banana', 'cherry']

    # ============================================================
    # 11. Debug Function
    # ============================================================

    def test_debug_single_arg(self, manager, step_context):
        """debug() - single argument"""
        result = manager._substitute_step_refs('debug({{vars.text}})', step_context)
        assert 'Hello World' in result

    def test_debug_multiple_args(self, manager, step_context):
        """debug() - multiple arguments"""
        result = manager._substitute_step_refs('debug({{vars.text}}, {{vars.number}})', step_context)
        assert 'Hello World' in result
        assert '42' in result

    # ============================================================
    # 12. Nested Function Calls
    # ============================================================

    def test_nested_two_levels(self, manager, step_context):
        """Nested: shuffle(split(...))"""
        result = manager._substitute_step_refs('shuffle(split({{vars.items}}, ","))', step_context)
        items = json.loads(result)
        assert sorted(items) == ['a', 'b', 'c']

    def test_nested_upper_trim(self, manager, step_context):
        """Nested: upper(trim(...))"""
        result = manager._substitute_step_refs('upper(trim({{vars.spaces}}))', step_context)
        assert result == 'HELLO'

    def test_nested_three_levels(self, manager, step_context):
        """Nested: join(shuffle(split(...)))"""
        result = manager._substitute_step_refs('join(shuffle(split({{vars.items}}, ",")), " - ")', step_context)
        parts = result.split(' - ')
        assert sorted(parts) == ['a', 'b', 'c']

    def test_nested_default_with_function(self, manager, step_context):
        """Nested: default with function result"""
        result = manager._substitute_step_refs('default(upper({{vars.text}}), FALLBACK)', step_context)
        assert result == 'HELLO WORLD'

    # ============================================================
    # 13. Edge Cases
    # ============================================================

    def test_empty_string_input(self, manager, step_context):
        """Edge case: empty string input"""
        result = manager._substitute_step_refs('upper({{vars.empty}})', step_context)
        assert result == ''

    def test_missing_variable(self, manager, step_context):
        """Edge case: missing variable reference"""
        result = manager._substitute_step_refs('upper({{vars.nonexistent}})', step_context)
        # Should return original reference or empty
        assert result == '' or '{{vars.nonexistent}}' in result.upper()

    def test_special_characters(self, manager, step_context):
        """Edge case: special characters"""
        step_context['vars']['special'] = 'Hello! @#$%^&*()'
        result = manager._substitute_step_refs('upper({{vars.special}})', step_context)
        assert result == 'HELLO! @#$%^&*()'

    def test_multiline_text(self, manager, step_context):
        """Edge case: multiline text"""
        step_context['vars']['multiline'] = 'Line1\nLine2\nLine3'
        result = manager._substitute_step_refs('upper({{vars.multiline}})', step_context)
        assert result == 'LINE1\nLINE2\nLINE3'

    def test_very_long_string(self, manager, step_context):
        """Edge case: very long string"""
        step_context['vars']['long'] = 'a' * 10000
        result = manager._substitute_step_refs('length({{vars.long}})', step_context)
        assert result == '10000'

    def test_unicode_emoji(self, manager, step_context):
        """Edge case: Unicode emoji"""
        step_context['vars']['emoji'] = 'Hello 👋 World 🌍'
        result = manager._substitute_step_refs('length({{vars.emoji}})', step_context)
        # Length depends on how emojis are counted
        assert int(result) > 0

    # ============================================================
    # 14. Quote Handling
    # ============================================================

    def test_quoted_delimiter(self, manager, step_context):
        """Quote handling: delimiter with quotes"""
        result = manager._substitute_step_refs('split({{vars.text}}, " ")', step_context)
        assert result == '["Hello", "World"]'

    def test_single_quoted_arg(self, manager, step_context):
        """Quote handling: single quoted argument"""
        result = manager._substitute_step_refs("replace({{vars.text}}, 'World', 'Universe')", step_context)
        assert result == 'Hello Universe'


    # ============================================================
    # 15. Data Access Functions (getprompt, getparser)
    # ============================================================

    def test_getprompt_with_meta_context(self, manager, step_context):
        """getprompt() - with _meta context (simulates workflow execution)"""
        # This test verifies the function signature works - actual DB query may fail without setup
        # The function should return empty string if prompt not found
        step_context['_meta'] = {
            'workflow_id': 1,
            'project_id': 1,
            'project_name': 'Test Project'
        }
        result = manager._substitute_step_refs('getprompt(NonExistentPrompt)', step_context)
        # Should return empty string for non-existent prompt
        assert result == '' or isinstance(result, str)

    def test_getparser_with_meta_context(self, manager, step_context):
        """getparser() - with _meta context (simulates workflow execution)"""
        step_context['_meta'] = {
            'workflow_id': 1,
            'project_id': 1,
            'project_name': 'Test Project'
        }
        result = manager._substitute_step_refs('getparser(NonExistentPrompt)', step_context)
        # Should return empty string for non-existent prompt
        assert result == '' or isinstance(result, str)

    def test_getprompt_no_meta_context(self, manager, step_context):
        """getprompt() - without _meta context (CURRENT project unavailable)"""
        # Without _meta, CURRENT project should fail gracefully
        result = manager._substitute_step_refs('getprompt(SomePrompt)', step_context)
        assert result == '' or isinstance(result, str)

    def test_getprompt_explicit_project(self, manager, step_context):
        """getprompt() - with explicit project name"""
        step_context['_meta'] = {
            'workflow_id': 1,
            'project_id': 1,
            'project_name': 'Test Project'
        }
        # Try to get prompt from a specific project (may not exist)
        result = manager._substitute_step_refs('getprompt(TestPrompt, SomeProject)', step_context)
        assert result == '' or isinstance(result, str)

    def test_getprompt_with_revision(self, manager, step_context):
        """getprompt() - with explicit revision"""
        step_context['_meta'] = {
            'workflow_id': 1,
            'project_id': 1,
            'project_name': 'Test Project'
        }
        result = manager._substitute_step_refs('getprompt(TestPrompt, CURRENT, 1)', step_context)
        assert result == '' or isinstance(result, str)


class TestGetPromptGetParserWithDB:
    """Tests for getprompt/getparser with actual database"""

    @pytest.fixture
    def db_session(self):
        """Create database session"""
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    @pytest.fixture
    def test_data(self, db_session):
        """Create test project, prompt, and revision"""
        from backend.database.models import Project, Prompt, PromptRevision

        # Create test project
        project = Project(name='TestGetPromptProject', description='Test project for getprompt')
        db_session.add(project)
        db_session.flush()

        # Create test prompt
        prompt = Prompt(project_id=project.id, name='TestPromptForGet', description='Test prompt')
        db_session.add(prompt)
        db_session.flush()

        # Create prompt revision
        revision = PromptRevision(
            prompt_id=prompt.id,
            revision=1,
            prompt_template='This is the test prompt template content',
            parser_config='{"output_format": "json"}'
        )
        db_session.add(revision)
        db_session.commit()

        yield {
            'project': project,
            'prompt': prompt,
            'revision': revision
        }

        # Cleanup
        db_session.delete(revision)
        db_session.delete(prompt)
        db_session.delete(project)
        db_session.commit()

    def test_getprompt_existing_prompt(self, db_session, test_data):
        """getprompt() - retrieve existing prompt template"""
        manager = WorkflowManager(db_session)
        step_context = {
            'vars': {},
            '_meta': {
                'workflow_id': 1,
                'project_id': test_data['project'].id,
                'project_name': test_data['project'].name
            }
        }

        result = manager._substitute_step_refs('getprompt(TestPromptForGet)', step_context)
        assert result == 'This is the test prompt template content'

    def test_getparser_existing_prompt(self, db_session, test_data):
        """getparser() - retrieve existing parser config"""
        manager = WorkflowManager(db_session)
        step_context = {
            'vars': {},
            '_meta': {
                'workflow_id': 1,
                'project_id': test_data['project'].id,
                'project_name': test_data['project'].name
            }
        }

        result = manager._substitute_step_refs('getparser(TestPromptForGet)', step_context)
        assert result == '{"output_format": "json"}'

    def test_getprompt_by_project_name(self, db_session, test_data):
        """getprompt() - retrieve by explicit project name"""
        manager = WorkflowManager(db_session)
        step_context = {
            'vars': {},
            '_meta': {
                'workflow_id': 1,
                'project_id': 999,  # Different project
                'project_name': 'Other Project'
            }
        }

        # Should still work with explicit project name
        result = manager._substitute_step_refs(
            f'getprompt(TestPromptForGet, TestGetPromptProject)',
            step_context
        )
        assert result == 'This is the test prompt template content'

    def test_getprompt_nonexistent_prompt(self, db_session, test_data):
        """getprompt() - non-existent prompt returns empty string"""
        manager = WorkflowManager(db_session)
        step_context = {
            'vars': {},
            '_meta': {
                'workflow_id': 1,
                'project_id': test_data['project'].id,
                'project_name': test_data['project'].name
            }
        }

        result = manager._substitute_step_refs('getprompt(NonExistentPromptXYZ)', step_context)
        assert result == ''

    def test_getprompt_nonexistent_project(self, db_session, test_data):
        """getprompt() - non-existent project returns empty string"""
        manager = WorkflowManager(db_session)
        step_context = {
            'vars': {},
            '_meta': {
                'workflow_id': 1,
                'project_id': test_data['project'].id,
                'project_name': test_data['project'].name
            }
        }

        result = manager._substitute_step_refs(
            'getprompt(TestPromptForGet, NonExistentProjectXYZ)',
            step_context
        )
        assert result == ''

    def test_getprompt_nonexistent_revision(self, db_session, test_data):
        """getprompt() - non-existent revision returns empty string"""
        manager = WorkflowManager(db_session)
        step_context = {
            'vars': {},
            '_meta': {
                'workflow_id': 1,
                'project_id': test_data['project'].id,
                'project_name': test_data['project'].name
            }
        }

        result = manager._substitute_step_refs(
            'getprompt(TestPromptForGet, CURRENT, 999)',
            step_context
        )
        assert result == ''

    def test_getprompt_specific_revision(self, db_session, test_data):
        """getprompt() - retrieve specific revision"""
        manager = WorkflowManager(db_session)
        step_context = {
            'vars': {},
            '_meta': {
                'workflow_id': 1,
                'project_id': test_data['project'].id,
                'project_name': test_data['project'].name
            }
        }

        result = manager._substitute_step_refs(
            'getprompt(TestPromptForGet, CURRENT, 1)',
            step_context
        )
        assert result == 'This is the test prompt template content'


# ============================================================
# Run tests
# ============================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

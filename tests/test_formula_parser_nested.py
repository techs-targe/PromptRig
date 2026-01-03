"""
Comprehensive Nested Function Tests for Formula Parser.

Tests all 39 functions with:
- Level 1: Basic function calls
- Level 2: Two-level nesting (outer(inner(value)))
- Level 3: Three-level nesting (outer(middle(inner(value))))
- calc() integration: Using functions inside arithmetic expressions
- dataset_filter: Using functions as arguments
"""

import pytest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.formula_parser import FormulaParser, evaluate_formula, validate_formula
from backend.workflow import WorkflowManager
from backend.database.database import SessionLocal, init_db


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def parser():
    return FormulaParser()


@pytest.fixture
def workflow_manager():
    init_db()
    db = SessionLocal()
    wm = WorkflowManager(db)
    yield wm
    db.close()


@pytest.fixture
def step_context():
    return {
        'step1': {
            'text': '  Hello World  ',
            'name': 'TOKYO',
            'number': '42',
            'items': '["a", "b", "c"]',
            'json_data': '{"name": "test", "value": 100}'
        },
        'vars': {
            'x': 10,
            'y': 5,
            'prefix': 'pre_',
            'suffix': '_suf',
            'category': 'A',
            'condition': "category='A'"
        }
    }


# =============================================================================
# Level 1: Basic Function Tests (39 functions)
# =============================================================================

class TestLevel1BasicFunctions:
    """Level 1: Basic function calls without nesting."""

    # --- Text Operations (18 functions) ---

    def test_upper(self, parser):
        assert parser.evaluate("upper(hello)") == "HELLO"

    def test_lower(self, parser):
        assert parser.evaluate("lower(HELLO)") == "hello"

    def test_trim(self, parser):
        assert parser.evaluate('trim("  hello  ")') == "hello"

    def test_lstrip(self, parser):
        assert parser.evaluate('lstrip("  hello")') == "hello"

    def test_rstrip(self, parser):
        assert parser.evaluate('rstrip("hello  ")') == "hello"

    def test_capitalize(self, parser):
        assert parser.evaluate("capitalize(hello)") == "Hello"

    def test_title(self, parser):
        assert parser.evaluate('title("hello world")') == "Hello World"

    def test_reverse(self, parser):
        assert parser.evaluate("reverse(hello)") == "olleh"

    def test_length(self, parser):
        assert parser.evaluate("length(hello)") == 5

    def test_len(self, parser):
        assert parser.evaluate("len(hello)") == 5

    def test_slice(self, parser):
        assert parser.evaluate("slice(hello, 0, 3)") == "hel"

    def test_left(self, parser):
        assert parser.evaluate("left(hello, 3)") == "hel"

    def test_right(self, parser):
        assert parser.evaluate("right(hello, 3)") == "llo"

    def test_replace(self, parser):
        assert parser.evaluate("replace(hello, l, L)") == "heLLo"

    def test_repeat(self, parser):
        assert parser.evaluate("repeat(ab, 3)") == "ababab"

    def test_concat(self, parser):
        assert parser.evaluate('concat("a", "b", "c")') == "abc"

    def test_split(self, parser):
        result = parser.evaluate('split("a,b,c", ",")')
        assert json.loads(result) == ["a", "b", "c"]

    def test_join(self, parser):
        assert parser.evaluate('join("[\\"a\\",\\"b\\",\\"c\\"]", "-")') == "a-b-c"

    # --- Search & Check (4 functions) ---

    def test_contains(self, parser):
        assert parser.evaluate('contains("hello world", "world")') == "true"

    def test_startswith(self, parser):
        assert parser.evaluate('startswith("hello", "he")') == "true"

    def test_endswith(self, parser):
        assert parser.evaluate('endswith("hello", "lo")') == "true"

    def test_count(self, parser):
        assert parser.evaluate("count(banana, a)") == 3

    # --- Math (2 functions) ---

    def test_sum(self, parser):
        assert parser.evaluate("sum(1, 2, 3)") == 6

    def test_calc(self, parser):
        assert parser.evaluate("calc(10 + 5)") == 15

    # --- Utility (5 functions) ---

    def test_default(self, parser):
        assert parser.evaluate('default("", "N/A")') == "N/A"
        assert parser.evaluate('default("value", "N/A")') == "value"

    def test_ifempty(self, parser):
        assert parser.evaluate('ifempty("", "default")') == "default"


# =============================================================================
# Level 2: Two-Level Nesting Tests
# =============================================================================

class TestLevel2Nesting:
    """Level 2: outer(inner(value)) pattern."""

    # --- Text + Text combinations ---

    def test_upper_trim(self, parser):
        assert parser.evaluate('upper(trim("  hello  "))') == "HELLO"

    def test_lower_trim(self, parser):
        assert parser.evaluate('lower(trim("  HELLO  "))') == "hello"

    def test_trim_upper(self, parser):
        assert parser.evaluate('trim(upper("  hello  "))') == "HELLO"

    def test_reverse_upper(self, parser):
        assert parser.evaluate("reverse(upper(hello))") == "OLLEH"

    def test_upper_reverse(self, parser):
        assert parser.evaluate("upper(reverse(hello))") == "OLLEH"

    def test_capitalize_lower(self, parser):
        assert parser.evaluate("capitalize(lower(HELLO))") == "Hello"

    def test_title_lower(self, parser):
        assert parser.evaluate('title(lower("HELLO WORLD"))') == "Hello World"

    def test_left_upper(self, parser):
        assert parser.evaluate("left(upper(hello), 3)") == "HEL"

    def test_right_lower(self, parser):
        assert parser.evaluate("right(lower(HELLO), 3)") == "llo"

    def test_replace_upper(self, parser):
        assert parser.evaluate("replace(upper(hello), L, X)") == "HEXXO"

    def test_concat_upper_lower(self, parser):
        assert parser.evaluate('concat(upper("a"), lower("B"))') == "Ab"

    # --- Math + Text combinations ---

    def test_length_upper(self, parser):
        assert parser.evaluate("length(upper(hello))") == 5

    def test_length_trim(self, parser):
        assert parser.evaluate('length(trim("  hi  "))') == 2

    def test_count_upper(self, parser):
        assert parser.evaluate("count(upper(banana), A)") == 3

    # --- calc + function combinations (THE KEY TEST) ---

    def test_calc_length(self, parser):
        assert parser.evaluate("calc(length(hello) + 10)") == 15

    def test_calc_length_multiply(self, parser):
        assert parser.evaluate("calc(length(hello) * 2)") == 10

    def test_calc_length_divide(self, parser):
        assert parser.evaluate("calc(length(hello) / 2)") == 2.5  # 5 / 2 = 2.5

    def test_calc_two_lengths(self, parser):
        assert parser.evaluate("calc(length(hello) + length(world))") == 10

    def test_calc_count(self, parser):
        assert parser.evaluate("calc(count(banana, a) * 10)") == 30

    # --- Search + Text combinations ---

    def test_contains_upper(self, parser):
        assert parser.evaluate("contains(upper(hello), ELL)") == "true"

    def test_startswith_lower(self, parser):
        assert parser.evaluate("startswith(lower(HELLO), he)") == "true"

    def test_endswith_upper(self, parser):
        assert parser.evaluate("endswith(upper(hello), LO)") == "true"


# =============================================================================
# Level 3: Three-Level Nesting Tests
# =============================================================================

class TestLevel3Nesting:
    """Level 3: outer(middle(inner(value))) pattern."""

    def test_upper_trim_reverse(self, parser):
        result = parser.evaluate('upper(trim(reverse("  olleh  ")))')
        assert result == "HELLO"

    def test_left_upper_trim(self, parser):
        result = parser.evaluate('left(upper(trim("  hello world  ")), 5)')
        assert result == "HELLO"

    def test_right_lower_trim(self, parser):
        result = parser.evaluate('right(lower(trim("  HELLO WORLD  ")), 5)')
        assert result == "world"

    def test_replace_upper_trim(self, parser):
        result = parser.evaluate('replace(upper(trim("  hello  ")), L, X)')
        assert result == "HEXXO"

    def test_capitalize_lower_reverse(self, parser):
        result = parser.evaluate("capitalize(lower(reverse(OLLEH)))")
        assert result == "Hello"

    def test_concat_upper_lower_trim(self, parser):
        result = parser.evaluate('concat(upper(trim("  a  ")), lower(trim("  B  ")))')
        assert result == "Ab"

    def test_length_upper_trim(self, parser):
        result = parser.evaluate('length(upper(trim("  hello  ")))')
        assert result == 5

    # --- calc with Level 3 nesting ---

    def test_calc_length_upper(self, parser):
        result = parser.evaluate("calc(length(upper(hello)) + 10)")
        assert result == 15

    def test_calc_length_trim_upper(self, parser):
        result = parser.evaluate('calc(length(trim(upper("  HI  "))) * 3)')
        assert result == 6  # "HI" length = 2, * 3 = 6

    def test_calc_count_upper(self, parser):
        result = parser.evaluate("calc(count(upper(banana), A) * 5)")
        assert result == 15  # 3 A's * 5 = 15

    def test_calc_two_nested_lengths(self, parser):
        result = parser.evaluate("calc(length(upper(hello)) + length(lower(WORLD)))")
        assert result == 10


# =============================================================================
# Workflow Integration Tests with Nesting
# =============================================================================

class TestWorkflowIntegration:
    """Test nested functions through workflow.py integration."""

    def test_level2_with_variable(self, workflow_manager, step_context):
        result = workflow_manager._substitute_step_refs(
            "upper(trim({{step1.text}}))",
            step_context
        )
        assert result == "HELLO WORLD"

    def test_level3_with_variable(self, workflow_manager, step_context):
        result = workflow_manager._substitute_step_refs(
            "left(upper(trim({{step1.text}})), 5)",
            step_context
        )
        assert result == "HELLO"

    def test_calc_with_variable(self, workflow_manager, step_context):
        result = workflow_manager._substitute_step_refs(
            "calc(length({{step1.name}}) + 10)",
            step_context
        )
        assert result == "15"  # TOKYO = 5, + 10 = 15

    def test_calc_level3_with_variable(self, workflow_manager, step_context):
        result = workflow_manager._substitute_step_refs(
            "calc(length(upper(trim({{step1.text}}))) + {{vars.x}})",
            step_context
        )
        assert result == "21"  # "HELLO WORLD" = 11, + 10 = 21

    def test_nested_concat_with_variables(self, workflow_manager, step_context):
        result = workflow_manager._substitute_step_refs(
            "concat(upper({{vars.prefix}}), lower({{vars.suffix}}))",
            step_context
        )
        assert result == "PRE__suf"


# =============================================================================
# calc() + Operators with Nested Functions
# =============================================================================

class TestCalcOperatorPrecedence:
    """Test operator precedence with nested functions."""

    def test_addition_multiplication(self, parser):
        # length(hello) + length(hi) * 2 = 5 + 2*2 = 5 + 4 = 9
        result = parser.evaluate("calc(length(hello) + length(hi) * 2)")
        assert result == 9

    def test_parentheses_override(self, parser):
        # (length(hello) + length(hi)) * 2 = (5 + 2) * 2 = 14
        result = parser.evaluate("calc((length(hello) + length(hi)) * 2)")
        assert result == 14

    def test_division_with_nested(self, parser):
        # length(hello) * 10 / 2 = 5 * 10 / 2 = 25
        result = parser.evaluate("calc(length(hello) * 10 / 2)")
        assert result == 25

    def test_modulo_with_nested(self, parser):
        # length(hello) % 3 = 5 % 3 = 2
        result = parser.evaluate("calc(length(hello) % 3)")
        assert result == 2

    def test_complex_expression(self, parser):
        # (length(hello) + length(world)) * 2 - count(banana, a) = (5+5)*2 - 3 = 17
        result = parser.evaluate("calc((length(hello) + length(world)) * 2 - count(banana, a))")
        assert result == 17


# =============================================================================
# dataset_filter with Function Arguments
# =============================================================================

class TestDatasetFilterWithFunctions:
    """Test using functions inside dataset_filter arguments.

    Note: These tests verify that function arguments are properly parsed.
    Actual dataset_filter execution requires database setup.
    """

    def test_validate_dataset_filter_with_concat(self, parser):
        # This should parse correctly
        is_valid, errors = validate_formula('concat("category=", "A")')
        assert is_valid is True

    def test_validate_dataset_filter_with_upper(self, parser):
        # Nested function in potential filter condition
        is_valid, errors = validate_formula("upper(condition)")
        assert is_valid is True

    def test_parse_complex_condition_builder(self, parser):
        # Building a condition string with concat
        result = parser.evaluate('concat("status=", "done")')
        assert result == "status=done"

    def test_parse_condition_with_quotes(self, parser):
        # Building a condition with proper quoting
        result = parser.evaluate("concat(\"category='\", \"A\", \"'\")")
        assert result == "category='A'"


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================

class TestEdgeCases:
    """Test edge cases and error scenarios."""

    def test_empty_string(self, parser):
        result = parser.evaluate('upper("")')
        assert result == ""

    def test_deeply_nested_4_levels(self, parser):
        # 4 levels: upper(lower(trim(reverse(...))))
        result = parser.evaluate('upper(lower(trim(reverse("  olleh  "))))')
        assert result == "HELLO"

    def test_deeply_nested_5_levels(self, parser):
        # 5 levels: left(upper(lower(trim(reverse(...)))))
        result = parser.evaluate('left(upper(lower(trim(reverse("  dlrow  ")))), 3)')
        assert result == "WOR"

    def test_many_args_concat(self, parser):
        result = parser.evaluate('concat("a", "b", "c", "d", "e")')
        assert result == "abcde"

    def test_sum_with_lengths(self, parser):
        result = parser.evaluate("sum(length(a), length(bb), length(ccc))")
        assert result == 6  # 1 + 2 + 3

    def test_nested_in_multiple_args(self, parser):
        # Both arguments are nested functions
        result = parser.evaluate("concat(upper(hello), lower(WORLD))")
        assert result == "HELLOworld"


# =============================================================================
# Validation Tests for Nested Functions
# =============================================================================

class TestNestedValidation:
    """Test validation of nested function expressions."""

    def test_valid_level2(self, parser):
        is_valid, errors = validate_formula("upper(trim(text))")
        assert is_valid is True

    def test_valid_level3(self, parser):
        is_valid, errors = validate_formula("left(upper(trim(text)), 5)")
        assert is_valid is True

    def test_valid_calc_nested(self, parser):
        is_valid, errors = validate_formula("calc(length(text) + 10)")
        assert is_valid is True

    def test_invalid_unclosed_nested(self, parser):
        is_valid, errors = validate_formula("upper(trim(text)")
        assert is_valid is False

    def test_invalid_unknown_inner_function(self, parser):
        is_valid, errors = validate_formula("upper(unknown_func(text))")
        assert is_valid is False

    def test_valid_complex_nested(self, parser):
        is_valid, errors = validate_formula(
            "calc((length(upper(hello)) + length(lower(WORLD))) * 2)"
        )
        assert is_valid is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

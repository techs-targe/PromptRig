#!/usr/bin/env python3
"""Unit tests for workflow string manipulation functions.

Tests all string functions available in workflow formulas:
- upper, lower, trim, lstrip, rstrip
- length, capitalize, title, reverse
- slice, left, right, replace, repeat
- split, join, concat
- default, contains, startswith, endswith, count
- sum (numeric)
"""

import json
import sys
import os

# Add the project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.database.database import SessionLocal, engine
from backend.database.models import Base
from backend.workflow import WorkflowManager

def log(msg: str, level: str = "INFO"):
    """Print formatted log message."""
    prefix = {"INFO": "ℹ️", "PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(level, "")
    print(f"{prefix} {msg}")

test_results = []

def test(name: str, condition: bool, details: str = ""):
    """Record test result."""
    result = {"name": name, "passed": condition, "details": details}
    test_results.append(result)
    if condition:
        log(f"PASS: {name}", "PASS")
    else:
        log(f"FAIL: {name} - {details}", "FAIL")
    return condition


def test_single_arg_functions():
    """Test single-argument string functions."""
    log("\n" + "="*60)
    log("TEST: Single-Argument String Functions")
    log("="*60)

    db = SessionLocal()
    try:
        manager = WorkflowManager(db)

        # Test context with variables
        step_context = {
            "vars": {
                "text": "  Hello World  ",
                "mixed": "hElLo WoRlD"
            },
            "step1": {
                "result": "Test String"
            }
        }

        # Test cases: (template, expected_result, description)
        test_cases = [
            # upper
            ("upper({{vars.mixed}})", "HELLO WORLD", "upper: mixed case"),
            ("upper(hello)", "HELLO", "upper: literal"),

            # lower
            ("lower({{vars.mixed}})", "hello world", "lower: mixed case"),
            ("lower(HELLO)", "hello", "lower: literal"),

            # trim
            ("trim({{vars.text}})", "Hello World", "trim: whitespace"),
            ("trim(  abc  )", "abc", "trim: literal"),

            # lstrip
            ("lstrip({{vars.text}})", "Hello World  ", "lstrip: left whitespace"),

            # rstrip
            ("rstrip({{vars.text}})", "  Hello World", "rstrip: right whitespace"),

            # length / len
            ("length({{step1.result}})", "11", "length: string"),
            ("len(hello)", "5", "len: alias"),

            # capitalize
            ("capitalize({{vars.mixed}})", "Hello world", "capitalize: first letter"),

            # title
            ("title({{vars.mixed}})", "Hello World", "title: each word"),

            # reverse
            ("reverse(hello)", "olleh", "reverse: string"),
            ("reverse({{step1.result}})", "gnirtS tseT", "reverse: variable"),
        ]

        for template, expected, desc in test_cases:
            result = manager._substitute_step_refs(template, step_context)
            test(f"Single-arg: {desc}", str(result) == str(expected),
                 f"Expected '{expected}', got '{result}'")

    finally:
        db.close()


def test_slice_functions():
    """Test slice/substring functions."""
    log("\n" + "="*60)
    log("TEST: Slice/Substring Functions")
    log("="*60)

    db = SessionLocal()
    try:
        manager = WorkflowManager(db)

        step_context = {
            "vars": {
                "text": "Hello World"
            }
        }

        test_cases = [
            # slice (start, end)
            ("slice({{vars.text}}, 0, 5)", "Hello", "slice: 0 to 5"),
            ("slice({{vars.text}}, 6)", "World", "slice: 6 to end"),
            ("slice({{vars.text}}, -5)", "World", "slice: negative start"),

            # substr alias
            ("substr({{vars.text}}, 0, 5)", "Hello", "substr: alias"),
            ("substring({{vars.text}}, 0, 5)", "Hello", "substring: alias"),

            # left
            ("left({{vars.text}}, 5)", "Hello", "left: first 5"),
            ("left({{vars.text}}, 20)", "Hello World", "left: more than length"),

            # right
            ("right({{vars.text}}, 5)", "World", "right: last 5"),
            ("right({{vars.text}}, 20)", "Hello World", "right: more than length"),
        ]

        for template, expected, desc in test_cases:
            result = manager._substitute_step_refs(template, step_context)
            test(f"Slice: {desc}", str(result) == str(expected),
                 f"Expected '{expected}', got '{result}'")

    finally:
        db.close()


def test_replace_repeat_functions():
    """Test replace and repeat functions."""
    log("\n" + "="*60)
    log("TEST: Replace/Repeat Functions")
    log("="*60)

    db = SessionLocal()
    try:
        manager = WorkflowManager(db)

        step_context = {
            "vars": {
                "text": "Hello World"
            }
        }

        test_cases = [
            # replace
            ("replace({{vars.text}}, World, Universe)", "Hello Universe", "replace: basic"),
            ("replace({{vars.text}}, l, L)", "HeLLo WorLd", "replace: all occurrences"),
            ("replace({{vars.text}}, xyz, abc)", "Hello World", "replace: not found"),

            # repeat
            ("repeat(ab, 3)", "ababab", "repeat: 3 times"),
            ("repeat({{vars.text}}, 0)", "", "repeat: 0 times"),
            ("repeat(x, 5)", "xxxxx", "repeat: single char"),
        ]

        for template, expected, desc in test_cases:
            result = manager._substitute_step_refs(template, step_context)
            test(f"Replace/Repeat: {desc}", str(result) == str(expected),
                 f"Expected '{expected}', got '{result}'")

    finally:
        db.close()


def test_split_join_concat():
    """Test split, join, and concat functions."""
    log("\n" + "="*60)
    log("TEST: Split/Join/Concat Functions")
    log("="*60)

    db = SessionLocal()
    try:
        manager = WorkflowManager(db)

        step_context = {
            "vars": {
                "csv": "a;b;c",  # Use semicolon to avoid conflict with arg separator
                "dashlist": "a-b-c",
                "array": '["x", "y", "z"]'
            },
            "step1": {
                "a": "Hello",
                "b": "World"
            }
        }

        test_cases = [
            # split - Note: comma delimiter is tricky because comma is arg separator
            # Using semicolon or other delimiters is recommended
            ("split({{vars.csv}}, ;)", '["a", "b", "c"]', "split: semicolon"),
            ("split({{vars.dashlist}}, -)", '["a", "b", "c"]', "split: dash"),

            # join
            ("join({{vars.array}}, -)", "x-y-z", "join: array to dash"),
            ("join({{vars.array}}, |)", "x|y|z", "join: array to pipe"),

            # concat
            ("concat(a, b, c)", "abc", "concat: multiple"),
            ("concat({{step1.a}}, !, !)", "Hello!!", "concat: with symbols"),
            ("concat({{step1.a}}, {{step1.b}})", "HelloWorld", "concat: two vars"),
        ]

        for template, expected, desc in test_cases:
            result = manager._substitute_step_refs(template, step_context)
            test(f"Split/Join/Concat: {desc}", str(result) == str(expected),
                 f"Expected '{expected}', got '{result}'")

    finally:
        db.close()


def test_conditional_functions():
    """Test default, contains, startswith, endswith, count functions."""
    log("\n" + "="*60)
    log("TEST: Conditional/Check Functions")
    log("="*60)

    db = SessionLocal()
    try:
        manager = WorkflowManager(db)

        step_context = {
            "vars": {
                "text": "Hello World",
                "empty": "",
                "blank": "   "
            }
        }

        test_cases = [
            # default / ifempty
            ("default({{vars.text}}, fallback)", "Hello World", "default: non-empty"),
            ("default({{vars.empty}}, fallback)", "fallback", "default: empty string"),
            ("default({{vars.blank}}, fallback)", "fallback", "default: blank string"),
            ("ifempty({{vars.empty}}, N/A)", "N/A", "ifempty: alias"),

            # contains
            ("contains({{vars.text}}, World)", "true", "contains: found"),
            ("contains({{vars.text}}, xyz)", "false", "contains: not found"),
            ("contains({{vars.text}}, llo)", "true", "contains: partial"),

            # startswith
            ("startswith({{vars.text}}, Hello)", "true", "startswith: match"),
            ("startswith({{vars.text}}, World)", "false", "startswith: no match"),

            # endswith
            ("endswith({{vars.text}}, World)", "true", "endswith: match"),
            ("endswith({{vars.text}}, Hello)", "false", "endswith: no match"),

            # count
            ("count({{vars.text}}, l)", "3", "count: character"),
            ("count({{vars.text}}, o)", "2", "count: multiple"),
            ("count({{vars.text}}, xyz)", "0", "count: not found"),
        ]

        for template, expected, desc in test_cases:
            result = manager._substitute_step_refs(template, step_context)
            test(f"Conditional: {desc}", str(result) == str(expected),
                 f"Expected '{expected}', got '{result}'")

    finally:
        db.close()


def test_sum_function():
    """Test sum function (numeric)."""
    log("\n" + "="*60)
    log("TEST: Sum Function (Numeric)")
    log("="*60)

    db = SessionLocal()
    try:
        manager = WorkflowManager(db)

        step_context = {
            "step1": {"score": 10},
            "step2": {"score": 20},
            "step3": {"score": 30}
        }

        test_cases = [
            ("sum({{step1.score}}, {{step2.score}})", "30.0", "sum: two values"),
            ("sum({{step1.score}}, {{step2.score}}, {{step3.score}})", "60.0", "sum: three values"),
            ("sum(5, 10, 15)", "30.0", "sum: literals"),
            ("sum({{step1.score}}, 5)", "15.0", "sum: mixed"),
        ]

        for template, expected, desc in test_cases:
            result = manager._substitute_step_refs(template, step_context)
            test(f"Sum: {desc}", str(result) == str(expected),
                 f"Expected '{expected}', got '{result}'")

    finally:
        db.close()


def test_nested_variable_refs():
    """Test functions with nested variable references."""
    log("\n" + "="*60)
    log("TEST: Nested Variable References")
    log("="*60)

    db = SessionLocal()
    try:
        manager = WorkflowManager(db)

        step_context = {
            "step1": {
                "name": "john doe",
                "items": "apple;banana;cherry"  # Use semicolon as delimiter
            },
            "vars": {
                "prefix": "Hello ",  # Include trailing space
                "suffix": "!"
            }
        }

        test_cases = [
            # Nested refs in functions
            ("upper({{step1.name}})", "JOHN DOE", "nested: upper with ref"),
            ("split({{step1.items}}, ;)", '["apple", "banana", "cherry"]', "nested: split with ref"),
            ("concat({{vars.prefix}}, {{step1.name}}, {{vars.suffix}})", "Hello john doe!", "nested: concat multiple refs"),
            ("length({{step1.items}})", "19", "nested: length of items"),  # "apple;banana;cherry" = 19 chars
        ]

        for template, expected, desc in test_cases:
            result = manager._substitute_step_refs(template, step_context)
            test(f"Nested: {desc}", str(result) == str(expected),
                 f"Expected '{expected}', got '{result}'")

    finally:
        db.close()


def test_edge_cases():
    """Test edge cases and error handling."""
    log("\n" + "="*60)
    log("TEST: Edge Cases")
    log("="*60)

    db = SessionLocal()
    try:
        manager = WorkflowManager(db)

        step_context = {
            "vars": {
                "empty": "",
                "unicode": "こんにちは世界"
            }
        }

        test_cases = [
            # Empty strings
            ("upper({{vars.empty}})", "", "edge: upper empty"),
            ("length({{vars.empty}})", "0", "edge: length empty"),
            ("trim(   )", "", "edge: trim only spaces"),

            # Unicode support
            ("length({{vars.unicode}})", "7", "edge: unicode length"),
            ("reverse({{vars.unicode}})", "界世はちにんこ", "edge: unicode reverse"),
            ("left({{vars.unicode}}, 3)", "こんに", "edge: unicode left"),

            # Missing references
            ("upper({{nonexistent.field}})", "{{NONEXISTENT.FIELD}}", "edge: missing ref (kept)"),

            # Function without args - regex requires at least one character, so not processed
            ("upper()", "upper()", "edge: no args (not matched)"),
        ]

        for template, expected, desc in test_cases:
            result = manager._substitute_step_refs(template, step_context)
            test(f"Edge: {desc}", str(result) == str(expected),
                 f"Expected '{expected}', got '{result}'")

    finally:
        db.close()


def test_case_insensitive():
    """Test that function names are case-insensitive."""
    log("\n" + "="*60)
    log("TEST: Case Insensitivity")
    log("="*60)

    db = SessionLocal()
    try:
        manager = WorkflowManager(db)

        step_context = {
            "vars": {"text": "hello"}
        }

        test_cases = [
            ("UPPER({{vars.text}})", "HELLO", "case: UPPER"),
            ("Upper({{vars.text}})", "HELLO", "case: Upper"),
            ("LENGTH({{vars.text}})", "5", "case: LENGTH"),
            ("Length({{vars.text}})", "5", "case: Length"),
            ("TRIM(  x  )", "x", "case: TRIM"),
        ]

        for template, expected, desc in test_cases:
            result = manager._substitute_step_refs(template, step_context)
            test(f"Case: {desc}", str(result) == str(expected),
                 f"Expected '{expected}', got '{result}'")

    finally:
        db.close()


def test_shuffle_function():
    """Test shuffle function."""
    log("\n" + "="*60)
    log("TEST: Shuffle Function")
    log("="*60)

    db = SessionLocal()
    try:
        manager = WorkflowManager(db)

        step_context = {
            "vars": {
                "items": "apple;banana;cherry;date;elderberry",
                "words": "hello world my name is taro"
            }
        }

        # Test 1: Shuffle with semicolon delimiter
        result1 = manager._substitute_step_refs("shuffle({{vars.items}}, ;)", step_context)
        parts1 = result1.split(";")
        expected_parts1 = ["apple", "banana", "cherry", "date", "elderberry"]
        # Check all parts are present (order may vary)
        test("Shuffle: contains all items",
             sorted(parts1) == sorted(expected_parts1),
             f"Expected {sorted(expected_parts1)}, got {sorted(parts1)}")

        # Test 2: Shuffle with space delimiter
        result2 = manager._substitute_step_refs("shuffle({{vars.words}},  )", step_context)
        parts2 = result2.split(" ")
        expected_parts2 = ["hello", "world", "my", "name", "is", "taro"]
        test("Shuffle: space delimiter",
             sorted(parts2) == sorted(expected_parts2),
             f"Expected {sorted(expected_parts2)}, got {sorted(parts2)}")

        # Test 3: Shuffle preserves number of items
        test("Shuffle: preserves item count",
             len(parts1) == 5 and len(parts2) == 6,
             f"Expected 5 and 6 items, got {len(parts1)} and {len(parts2)}")

        # Test 4: Single item (no change possible)
        result3 = manager._substitute_step_refs("shuffle(single, ;)", step_context)
        test("Shuffle: single item",
             result3 == "single",
             f"Expected 'single', got '{result3}'")

        # Test 5: Two items
        result4 = manager._substitute_step_refs("shuffle(a;b, ;)", step_context)
        parts4 = result4.split(";")
        test("Shuffle: two items",
             sorted(parts4) == ["a", "b"],
             f"Expected ['a', 'b'], got {sorted(parts4)}")

    finally:
        db.close()


def test_debug_function():
    """Test debug output function."""
    log("\n" + "="*60)
    log("TEST: Debug Function")
    log("="*60)

    db = SessionLocal()
    try:
        manager = WorkflowManager(db)

        step_context = {
            "step1": {
                "result": "Hello World",
                "score": 85
            },
            "vars": {
                "name": "Test User"
            }
        }

        # Test 1: Single argument
        result1 = manager._substitute_step_refs("debug({{step1.result}})", step_context)
        test("Debug: single arg",
             result1 == "Hello World",
             f"Expected 'Hello World', got '{result1}'")

        # Test 2: Multiple arguments
        result2 = manager._substitute_step_refs("debug({{step1.result}}, {{step1.score}}, {{vars.name}})", step_context)
        test("Debug: multiple args",
             result2 == "Hello World | 85 | Test User",
             f"Expected 'Hello World | 85 | Test User', got '{result2}'")

        # Test 3: Literal values
        result3 = manager._substitute_step_refs("debug(test value, 123)", step_context)
        test("Debug: literals",
             result3 == "test value | 123",
             f"Expected 'test value | 123', got '{result3}'")

        # Test 4: Mixed literals and variables
        result4 = manager._substitute_step_refs("debug(Name:, {{vars.name}}, Score:, {{step1.score}})", step_context)
        test("Debug: mixed",
             result4 == "Name: | Test User | Score: | 85",
             f"Expected 'Name: | Test User | Score: | 85', got '{result4}'")

    finally:
        db.close()


def main():
    """Run all unit tests."""
    log("\n" + "="*60)
    log("STRING FUNCTION UNIT TESTS")
    log("="*60)

    test_single_arg_functions()
    test_slice_functions()
    test_replace_repeat_functions()
    test_split_join_concat()
    test_conditional_functions()
    test_sum_function()
    test_nested_variable_refs()
    test_edge_cases()
    test_case_insensitive()
    test_shuffle_function()
    test_debug_function()

    # Summary
    log("\n" + "="*60)
    log("TEST SUMMARY")
    log("="*60)

    passed = sum(1 for r in test_results if r["passed"])
    failed = sum(1 for r in test_results if not r["passed"])
    total = len(test_results)

    log(f"Total:  {total}")
    log(f"Passed: {passed} ({100*passed/total:.1f}%)" if total else "Passed: 0")
    log(f"Failed: {failed}")

    if failed > 0:
        log("\nFailed tests:")
        for r in test_results:
            if not r["passed"]:
                log(f"  - {r['name']}: {r['details']}", "FAIL")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

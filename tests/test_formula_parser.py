"""
Comprehensive tests for the Formula Parser (Interpreter Pattern).

Tests cover:
1. Tokenization
2. AST generation (Shunting-yard algorithm)
3. Evaluation (Stack-based)
4. Nested function support
5. Operator precedence
6. Error handling and validation
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.formula_parser import (
    Tokenizer, TokenType, Token, TokenizerError,
    Parser, ParseError, ASTNode, NumberNode, StringNode, VariableNode,
    IdentifierNode, BinaryOpNode, FunctionCallNode,
    FormulaEvaluator, EvaluationError,
    FormulaParser, validate_formula, parse_formula, evaluate_formula
)


# =============================================================================
# Tokenizer Tests
# =============================================================================

class TestTokenizer:
    """Tests for the lexical analyzer (tokenizer)."""

    def test_tokenize_number(self):
        """Test tokenizing numbers."""
        tokenizer = Tokenizer("123")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.NUMBER
        assert tokens[0].value == 123

    def test_tokenize_float(self):
        """Test tokenizing floating-point numbers."""
        tokenizer = Tokenizer("45.67")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.NUMBER
        assert tokens[0].value == 45.67

    def test_tokenize_negative_number(self):
        """Test tokenizing negative numbers."""
        tokenizer = Tokenizer("-5")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.NUMBER
        assert tokens[0].value == -5

    def test_tokenize_string_double_quote(self):
        """Test tokenizing double-quoted strings."""
        tokenizer = Tokenizer('"hello world"')
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == "hello world"

    def test_tokenize_string_single_quote(self):
        """Test tokenizing single-quoted strings."""
        tokenizer = Tokenizer("'hello'")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == "hello"

    def test_tokenize_string_escape(self):
        """Test tokenizing strings with escape sequences."""
        tokenizer = Tokenizer(r'"hello\nworld"')
        tokens = tokenizer.tokenize()
        assert tokens[0].value == "hello\nworld"

    def test_tokenize_variable(self):
        """Test tokenizing variable references."""
        tokenizer = Tokenizer("{{step.text}}")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.VARIABLE
        assert tokens[0].value == "{{step.text}}"

    def test_tokenize_function(self):
        """Test tokenizing function names."""
        tokenizer = Tokenizer("upper(x)")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.FUNCTION
        assert tokens[0].value == "upper"

    def test_tokenize_operators(self):
        """Test tokenizing operators."""
        tokenizer = Tokenizer("+ - * / %")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.PLUS
        assert tokens[1].type == TokenType.MINUS
        assert tokens[2].type == TokenType.MULTIPLY
        assert tokens[3].type == TokenType.DIVIDE
        assert tokens[4].type == TokenType.MODULO

    def test_tokenize_delimiters(self):
        """Test tokenizing delimiters."""
        tokenizer = Tokenizer("( ) [ ] ,")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.LPAREN
        assert tokens[1].type == TokenType.RPAREN
        assert tokens[2].type == TokenType.LBRACKET
        assert tokens[3].type == TokenType.RBRACKET
        assert tokens[4].type == TokenType.COMMA

    def test_tokenize_identifier(self):
        """Test tokenizing bareword identifiers."""
        tokenizer = Tokenizer("hello")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "hello"

    def test_tokenize_complex_expression(self):
        """Test tokenizing a complex expression."""
        tokenizer = Tokenizer('upper(trim({{step.text}}))')
        tokens = tokenizer.tokenize()

        assert tokens[0].type == TokenType.FUNCTION
        assert tokens[0].value == "upper"
        assert tokens[1].type == TokenType.LPAREN
        assert tokens[2].type == TokenType.FUNCTION
        assert tokens[2].value == "trim"
        assert tokens[3].type == TokenType.LPAREN
        assert tokens[4].type == TokenType.VARIABLE
        assert tokens[5].type == TokenType.RPAREN
        assert tokens[6].type == TokenType.RPAREN

    def test_tokenize_unclosed_variable_error(self):
        """Test error on unclosed variable reference."""
        tokenizer = Tokenizer("{{step.text")
        with pytest.raises(TokenizerError):
            tokenizer.tokenize()

    def test_tokenize_unclosed_string_error(self):
        """Test error on unclosed string literal."""
        tokenizer = Tokenizer('"hello')
        with pytest.raises(TokenizerError):
            tokenizer.tokenize()

    def test_tokenize_unknown_function_error(self):
        """Test error on unknown function name."""
        tokenizer = Tokenizer("unknown_func(x)")
        with pytest.raises(TokenizerError):
            tokenizer.tokenize()


# =============================================================================
# Parser Tests
# =============================================================================

class TestParser:
    """Tests for the syntax analyzer (parser)."""

    def test_parse_number(self):
        """Test parsing a number."""
        parser = FormulaParser()
        ast = parser.parse("42")
        assert isinstance(ast, NumberNode)
        assert ast.value == 42

    def test_parse_string(self):
        """Test parsing a string."""
        parser = FormulaParser()
        ast = parser.parse('"hello"')
        assert isinstance(ast, StringNode)
        assert ast.value == "hello"

    def test_parse_variable(self):
        """Test parsing a variable reference."""
        parser = FormulaParser()
        ast = parser.parse("{{step.text}}")
        assert isinstance(ast, VariableNode)
        assert ast.name == "{{step.text}}"

    def test_parse_function_call(self):
        """Test parsing a function call."""
        parser = FormulaParser()
        ast = parser.parse("upper(hello)")
        assert isinstance(ast, FunctionCallNode)
        assert ast.name == "upper"
        assert len(ast.args) == 1
        assert isinstance(ast.args[0], IdentifierNode)

    def test_parse_nested_function(self):
        """Test parsing nested function calls."""
        parser = FormulaParser()
        ast = parser.parse("upper(trim(text))")
        assert isinstance(ast, FunctionCallNode)
        assert ast.name == "upper"
        assert isinstance(ast.args[0], FunctionCallNode)
        assert ast.args[0].name == "trim"

    def test_parse_binary_operation(self):
        """Test parsing a binary operation."""
        parser = FormulaParser()
        ast = parser.parse("10 + 5")
        assert isinstance(ast, BinaryOpNode)
        assert ast.operator == "+"

    def test_parse_operator_precedence(self):
        """Test operator precedence (* before +)."""
        parser = FormulaParser()
        ast = parser.parse("10 + 5 * 2")
        # Should be parsed as: 10 + (5 * 2)
        assert isinstance(ast, BinaryOpNode)
        assert ast.operator == "+"
        assert isinstance(ast.right, BinaryOpNode)
        assert ast.right.operator == "*"

    def test_parse_parentheses(self):
        """Test parentheses override precedence."""
        parser = FormulaParser()
        ast = parser.parse("(10 + 5) * 2")
        # Should be parsed as: (10 + 5) * 2
        assert isinstance(ast, BinaryOpNode)
        assert ast.operator == "*"
        assert isinstance(ast.left, BinaryOpNode)
        assert ast.left.operator == "+"

    def test_parse_function_with_multiple_args(self):
        """Test parsing function with multiple arguments."""
        parser = FormulaParser()
        ast = parser.parse('concat("a", "b", "c")')
        assert isinstance(ast, FunctionCallNode)
        assert len(ast.args) == 3

    def test_parse_unclosed_paren_error(self):
        """Test error on unclosed parenthesis."""
        parser = FormulaParser()
        errors = parser.validate("upper(hello")
        assert len(errors) > 0

    def test_parse_empty_expression_error(self):
        """Test error on empty expression."""
        parser = FormulaParser()
        errors = parser.validate("")
        assert len(errors) > 0


# =============================================================================
# Evaluator Tests
# =============================================================================

class TestEvaluator:
    """Tests for the expression evaluator."""

    def test_evaluate_number(self):
        """Test evaluating a number."""
        result = evaluate_formula("42")
        assert result == 42

    def test_evaluate_string(self):
        """Test evaluating a string."""
        result = evaluate_formula('"hello"')
        assert result == "hello"

    def test_evaluate_addition(self):
        """Test evaluating addition."""
        result = evaluate_formula("10 + 5")
        assert result == 15

    def test_evaluate_subtraction(self):
        """Test evaluating subtraction."""
        result = evaluate_formula("10 - 3")
        assert result == 7

    def test_evaluate_multiplication(self):
        """Test evaluating multiplication."""
        result = evaluate_formula("6 * 7")
        assert result == 42

    def test_evaluate_division(self):
        """Test evaluating division."""
        result = evaluate_formula("20 / 4")
        assert result == 5

    def test_evaluate_modulo(self):
        """Test evaluating modulo."""
        result = evaluate_formula("17 % 5")
        assert result == 2

    def test_evaluate_precedence(self):
        """Test operator precedence."""
        result = evaluate_formula("10 + 5 * 2")
        assert result == 20  # Not 30

    def test_evaluate_parentheses(self):
        """Test parentheses."""
        result = evaluate_formula("(10 + 5) * 2")
        assert result == 30

    def test_evaluate_upper(self):
        """Test upper() function."""
        result = evaluate_formula("upper(hello)")
        assert result == "HELLO"

    def test_evaluate_lower(self):
        """Test lower() function."""
        result = evaluate_formula("lower(WORLD)")
        assert result == "world"

    def test_evaluate_trim(self):
        """Test trim() function."""
        result = evaluate_formula('trim("  hello  ")')
        assert result == "hello"

    def test_evaluate_length(self):
        """Test length() function."""
        result = evaluate_formula("length(hello)")
        assert result == 5

    def test_evaluate_concat(self):
        """Test concat() function."""
        result = evaluate_formula('concat("a", "b", "c")')
        assert result == "abc"

    def test_evaluate_nested_functions(self):
        """Test nested function evaluation."""
        result = evaluate_formula("upper(trim(hello))")
        assert result == "HELLO"

    def test_evaluate_calc_with_nested(self):
        """Test calc with nested function - THE KEY TEST."""
        result = evaluate_formula("calc(length(hello) + 10)")
        assert result == 15

    def test_evaluate_calc_with_multiple_nested(self):
        """Test calc with multiple nested functions."""
        result = evaluate_formula("calc(length(hello) + length(world))")
        assert result == 10

    def test_evaluate_calc_with_precedence(self):
        """Test calc with operator precedence."""
        result = evaluate_formula("calc(length(hello) * 2 + 3)")
        assert result == 13  # (5 * 2) + 3 = 13

    def test_evaluate_variable_resolution(self):
        """Test variable resolution."""
        context = {'step': {'text': 'HELLO'}}
        result = evaluate_formula("lower({{step.text}})", context)
        assert result == "hello"

    def test_evaluate_nested_variable(self):
        """Test nested variable access."""
        context = {'vars': {'data': {'name': 'test'}}}
        result = evaluate_formula("upper({{vars.data.name}})", context)
        assert result == "TEST"


# =============================================================================
# Validation Tests
# =============================================================================

class TestValidation:
    """Tests for formula validation."""

    def test_validate_valid_formula(self):
        """Test validation of valid formula."""
        is_valid, errors = validate_formula("upper(hello)")
        assert is_valid is True
        assert len(errors) == 0

    def test_validate_nested_formula(self):
        """Test validation of nested formula."""
        is_valid, errors = validate_formula("calc(length(hello) + 10)")
        assert is_valid is True

    def test_validate_complex_formula(self):
        """Test validation of complex formula."""
        is_valid, errors = validate_formula('concat(upper(a), "-", lower(B))')
        assert is_valid is True

    def test_validate_unclosed_paren(self):
        """Test validation catches unclosed parenthesis."""
        is_valid, errors = validate_formula("upper(hello")
        assert is_valid is False
        assert len(errors) > 0

    def test_validate_unknown_function(self):
        """Test validation catches unknown function."""
        is_valid, errors = validate_formula("unknown_func(x)")
        assert is_valid is False

    def test_validate_unclosed_variable(self):
        """Test validation catches unclosed variable."""
        is_valid, errors = validate_formula("{{step.text")
        assert is_valid is False

    def test_validate_unclosed_string(self):
        """Test validation catches unclosed string."""
        is_valid, errors = validate_formula('upper("hello)')
        assert is_valid is False

    def test_validate_incomplete_expression(self):
        """Test validation catches incomplete expression."""
        is_valid, errors = validate_formula("calc(10 +)")
        assert is_valid is False


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests with workflow.py."""

    def test_workflow_integration(self):
        """Test integration with WorkflowManager."""
        from backend.workflow import WorkflowManager
        from backend.database.database import SessionLocal, init_db

        init_db()
        db = SessionLocal()
        wm = WorkflowManager(db)

        step_context = {
            'step1': {'text': '  HELLO  '},
            'vars': {'x': 10}
        }

        # Test basic function
        result = wm._substitute_step_refs("upper(world)", step_context)
        assert result == "WORLD"

        # Test nested function
        result = wm._substitute_step_refs("lower(trim({{step1.text}}))", step_context)
        assert result == "hello"

        # Test calc with nested function (was broken before)
        result = wm._substitute_step_refs("calc(length(hello) + 10)", step_context)
        assert result == "15"

        db.close()


# =============================================================================
# Helper Function Tests
# =============================================================================

class TestHelperFunctions:
    """Tests for helper/utility functions."""

    def test_get_variables(self):
        """Test extracting variables from formula."""
        parser = FormulaParser()
        variables = parser.get_variables("upper({{step.text}}) + {{vars.x}}")
        assert "{{step.text}}" in variables
        assert "{{vars.x}}" in variables

    def test_get_functions(self):
        """Test extracting function names from formula."""
        parser = FormulaParser()
        functions = parser.get_functions("upper(trim(text))")
        assert "upper" in functions
        assert "trim" in functions


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

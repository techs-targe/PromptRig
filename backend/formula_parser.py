"""
Formula Parser with Reverse Polish Notation (RPN) and Stack Evaluation.

This module provides a robust parser for workflow formulas that supports:
- Nested function calls: upper(trim({{step.text}}))
- Mixed expressions: calc(length(x) + 10 * 2)
- Operator precedence: * / before + -
- Proper error messages with position information

Architecture:
1. Tokenizer: Breaks input into tokens
2. Shunting-yard: Converts infix to RPN (postfix)
3. Stack evaluator: Evaluates RPN using a stack
"""

import re
import json
import logging
from enum import Enum, auto
from dataclasses import dataclass
from typing import List, Any, Dict, Optional, Callable, Union, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Token Types and Definitions
# =============================================================================

class TokenType(Enum):
    """Token types for the formula lexer."""
    # Literals
    NUMBER = auto()       # 123, 45.67
    STRING = auto()       # "hello", 'world'
    VARIABLE = auto()     # {{step.text}}, {{vars.x}}
    IDENTIFIER = auto()   # bareword like hello, test

    # Functions
    FUNCTION = auto()     # upper, lower, calc, etc.

    # Operators
    PLUS = auto()         # +
    MINUS = auto()        # -
    MULTIPLY = auto()     # *
    DIVIDE = auto()       # /
    MODULO = auto()       # %

    # Delimiters
    LPAREN = auto()       # (
    RPAREN = auto()       # )
    LBRACKET = auto()     # [
    RBRACKET = auto()     # ]
    COMMA = auto()        # ,

    # Special
    EOF = auto()          # End of input


@dataclass
class Token:
    """A token with type, value, and position information."""
    type: TokenType
    value: Any
    position: int  # Character position in original input
    length: int    # Length of the token in original input

    def __repr__(self):
        return f"Token({self.type.name}, {self.value!r}, pos={self.position})"


# Operator precedence and associativity
OPERATORS = {
    '+': {'precedence': 1, 'associativity': 'left', 'type': TokenType.PLUS},
    '-': {'precedence': 1, 'associativity': 'left', 'type': TokenType.MINUS},
    '*': {'precedence': 2, 'associativity': 'left', 'type': TokenType.MULTIPLY},
    '/': {'precedence': 2, 'associativity': 'left', 'type': TokenType.DIVIDE},
    '%': {'precedence': 2, 'associativity': 'left', 'type': TokenType.MODULO},
}

# Supported function names (must match STRING_FUNCTIONS in workflow.py)
SUPPORTED_FUNCTIONS = {
    # Text operations
    'upper', 'lower', 'trim', 'lstrip', 'rstrip', 'capitalize', 'title', 'reverse',
    'length', 'len', 'slice', 'substr', 'substring', 'left', 'right',
    'replace', 'repeat', 'concat', 'split', 'join',
    # Search & check
    'contains', 'startswith', 'endswith', 'count',
    # Math
    'sum', 'calc',
    # JSON
    'json_parse', 'json_zip', 'format_choices',
    # Dataset
    'dataset_filter', 'dataset_join',
    # Array
    'array_push', 'shuffle',
    # Date/time
    'now', 'today', 'time',
    # Utility
    'default', 'ifempty', 'debug', 'getprompt', 'getparser',
}


# =============================================================================
# Tokenizer (Lexical Analyzer)
# =============================================================================

class TokenizerError(Exception):
    """Error during tokenization with position info."""
    def __init__(self, message: str, position: int, input_text: str):
        self.position = position
        self.input_text = input_text
        # Create error message with context
        context_start = max(0, position - 10)
        context_end = min(len(input_text), position + 10)
        context = input_text[context_start:context_end]
        pointer_pos = position - context_start
        super().__init__(f"{message} at position {position}: ...{context}...\n" +
                        " " * (len(message) + 17 + pointer_pos) + "^")


class Tokenizer:
    """Tokenizes a formula string into a list of tokens."""

    def __init__(self, input_text: str):
        self.input = input_text
        self.pos = 0
        self.tokens: List[Token] = []

    def tokenize(self) -> List[Token]:
        """Tokenize the entire input and return a list of tokens."""
        self.tokens = []
        self.pos = 0

        while self.pos < len(self.input):
            self._skip_whitespace()
            if self.pos >= len(self.input):
                break

            token = self._next_token()
            if token:
                self.tokens.append(token)

        # Add EOF token
        self.tokens.append(Token(TokenType.EOF, None, self.pos, 0))
        return self.tokens

    def _skip_whitespace(self):
        """Skip whitespace characters."""
        while self.pos < len(self.input) and self.input[self.pos] in ' \t\n\r':
            self.pos += 1

    def _next_token(self) -> Optional[Token]:
        """Parse and return the next token."""
        if self.pos >= len(self.input):
            return None

        char = self.input[self.pos]
        start_pos = self.pos

        # Variable reference: {{...}}
        if self._match('{{'):
            return self._parse_variable(start_pos)

        # String literal: "..." or '...'
        if char in '"\'':
            return self._parse_string(start_pos)

        # Number: 123, 45.67, -5
        if char.isdigit() or (char == '-' and self._peek_digit()):
            return self._parse_number(start_pos)

        # Operators
        if char in OPERATORS:
            self.pos += 1
            return Token(OPERATORS[char]['type'], char, start_pos, 1)

        # Delimiters
        if char == '(':
            self.pos += 1
            return Token(TokenType.LPAREN, '(', start_pos, 1)
        if char == ')':
            self.pos += 1
            return Token(TokenType.RPAREN, ')', start_pos, 1)
        if char == '[':
            self.pos += 1
            return Token(TokenType.LBRACKET, '[', start_pos, 1)
        if char == ']':
            self.pos += 1
            return Token(TokenType.RBRACKET, ']', start_pos, 1)
        if char == ',':
            self.pos += 1
            return Token(TokenType.COMMA, ',', start_pos, 1)

        # Identifier or function name
        if char.isalpha() or char == '_':
            return self._parse_identifier(start_pos)

        raise TokenizerError(f"Unexpected character '{char}'", self.pos, self.input)

    def _match(self, expected: str) -> bool:
        """Check if input matches expected string at current position."""
        return self.input[self.pos:self.pos + len(expected)] == expected

    def _peek_digit(self) -> bool:
        """Check if next character is a digit (for negative numbers)."""
        next_pos = self.pos + 1
        return next_pos < len(self.input) and self.input[next_pos].isdigit()

    def _parse_variable(self, start_pos: int) -> Token:
        """Parse a variable reference {{...}}."""
        self.pos += 2  # Skip {{

        # Find closing }}
        end_pos = self.input.find('}}', self.pos)
        if end_pos == -1:
            raise TokenizerError("Unclosed variable reference", start_pos, self.input)

        var_name = self.input[self.pos:end_pos]
        self.pos = end_pos + 2  # Skip }}

        return Token(TokenType.VARIABLE, f"{{{{{var_name}}}}}", start_pos, self.pos - start_pos)

    def _parse_string(self, start_pos: int) -> Token:
        """Parse a string literal "..." or '...'."""
        quote_char = self.input[self.pos]
        self.pos += 1  # Skip opening quote

        value = ""
        while self.pos < len(self.input):
            char = self.input[self.pos]
            if char == quote_char:
                self.pos += 1  # Skip closing quote
                return Token(TokenType.STRING, value, start_pos, self.pos - start_pos)
            elif char == '\\' and self.pos + 1 < len(self.input):
                # Escape sequence
                self.pos += 1
                next_char = self.input[self.pos]
                if next_char == 'n':
                    value += '\n'
                elif next_char == 't':
                    value += '\t'
                elif next_char == '\\':
                    value += '\\'
                elif next_char == quote_char:
                    value += quote_char
                else:
                    value += next_char
                self.pos += 1
            else:
                value += char
                self.pos += 1

        raise TokenizerError("Unclosed string literal", start_pos, self.input)

    def _parse_number(self, start_pos: int) -> Token:
        """Parse a number (integer or float)."""
        value = ""

        # Handle negative sign
        if self.input[self.pos] == '-':
            value += '-'
            self.pos += 1

        # Integer part
        while self.pos < len(self.input) and self.input[self.pos].isdigit():
            value += self.input[self.pos]
            self.pos += 1

        # Decimal part
        if self.pos < len(self.input) and self.input[self.pos] == '.':
            value += '.'
            self.pos += 1
            while self.pos < len(self.input) and self.input[self.pos].isdigit():
                value += self.input[self.pos]
                self.pos += 1

        # Convert to number
        num_value = float(value) if '.' in value else int(value)
        return Token(TokenType.NUMBER, num_value, start_pos, self.pos - start_pos)

    def _parse_identifier(self, start_pos: int) -> Token:
        """Parse an identifier or function name."""
        value = ""
        while self.pos < len(self.input):
            char = self.input[self.pos]
            if char.isalnum() or char == '_':
                value += char
                self.pos += 1
            else:
                break

        # Check if it's a function (followed by opening paren)
        self._skip_whitespace()
        if self.pos < len(self.input) and self.input[self.pos] == '(':
            if value.lower() in SUPPORTED_FUNCTIONS:
                return Token(TokenType.FUNCTION, value.lower(), start_pos, len(value))
            else:
                raise TokenizerError(f"Unknown function '{value}'", start_pos, self.input)

        # It's a plain identifier (bareword)
        return Token(TokenType.IDENTIFIER, value, start_pos, len(value))


# =============================================================================
# Parser (Syntax Analyzer) - Shunting-yard Algorithm
# =============================================================================

class ParseError(Exception):
    """Error during parsing with position info."""
    def __init__(self, message: str, token: Optional[Token] = None):
        self.token = token
        if token:
            super().__init__(f"{message} at position {token.position}")
        else:
            super().__init__(message)


@dataclass
class ASTNode:
    """Base class for AST nodes."""
    pass


@dataclass
class NumberNode(ASTNode):
    """A numeric literal."""
    value: Union[int, float]


@dataclass
class StringNode(ASTNode):
    """A string literal."""
    value: str


@dataclass
class VariableNode(ASTNode):
    """A variable reference {{...}}."""
    name: str  # Full reference like "{{step.text}}"


@dataclass
class IdentifierNode(ASTNode):
    """A bareword identifier."""
    name: str


@dataclass
class BinaryOpNode(ASTNode):
    """A binary operation (e.g., a + b)."""
    operator: str
    left: ASTNode
    right: ASTNode


@dataclass
class FunctionCallNode(ASTNode):
    """A function call with arguments."""
    name: str
    args: List[ASTNode]


class Parser:
    """
    Parser using the Shunting-yard algorithm.

    Converts infix notation to an Abstract Syntax Tree (AST).
    """

    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def parse(self) -> ASTNode:
        """Parse the tokens into an AST."""
        if not self.tokens or self.tokens[0].type == TokenType.EOF:
            raise ParseError("Empty expression")

        result = self._parse_expression()

        if self.current().type != TokenType.EOF:
            raise ParseError("Unexpected token after expression", self.current())

        return result

    def current(self) -> Token:
        """Get current token."""
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return Token(TokenType.EOF, None, -1, 0)

    def advance(self) -> Token:
        """Advance to next token and return current."""
        token = self.current()
        self.pos += 1
        return token

    def expect(self, token_type: TokenType) -> Token:
        """Expect a specific token type, raise error if not matched."""
        if self.current().type != token_type:
            raise ParseError(f"Expected {token_type.name}, got {self.current().type.name}",
                           self.current())
        return self.advance()

    def _parse_expression(self, min_precedence: int = 0) -> ASTNode:
        """
        Parse an expression using precedence climbing.

        This handles operator precedence correctly:
        - Higher precedence operators bind tighter
        - Left associativity means we parse left-to-right
        """
        left = self._parse_primary()

        while True:
            token = self.current()
            if token.type not in (TokenType.PLUS, TokenType.MINUS,
                                 TokenType.MULTIPLY, TokenType.DIVIDE,
                                 TokenType.MODULO):
                break

            op_info = OPERATORS.get(token.value)
            if not op_info or op_info['precedence'] < min_precedence:
                break

            self.advance()  # Consume operator

            # For left associativity, use precedence + 1 for right side
            # For right associativity, use same precedence
            next_min_prec = op_info['precedence']
            if op_info['associativity'] == 'left':
                next_min_prec += 1

            right = self._parse_expression(next_min_prec)
            left = BinaryOpNode(token.value, left, right)

        return left

    def _parse_primary(self) -> ASTNode:
        """Parse a primary expression (literal, variable, function call, parenthesized)."""
        token = self.current()

        if token.type == TokenType.NUMBER:
            self.advance()
            return NumberNode(token.value)

        if token.type == TokenType.STRING:
            self.advance()
            return StringNode(token.value)

        if token.type == TokenType.VARIABLE:
            self.advance()
            return VariableNode(token.value)

        if token.type == TokenType.IDENTIFIER:
            self.advance()
            return IdentifierNode(token.value)

        if token.type == TokenType.FUNCTION:
            return self._parse_function_call()

        if token.type == TokenType.LPAREN:
            self.advance()  # Skip (
            expr = self._parse_expression()
            self.expect(TokenType.RPAREN)
            return expr

        if token.type == TokenType.MINUS:
            # Unary minus
            self.advance()
            operand = self._parse_primary()
            return BinaryOpNode('-', NumberNode(0), operand)

        raise ParseError(f"Unexpected token {token.type.name}", token)

    def _parse_function_call(self) -> FunctionCallNode:
        """Parse a function call: func_name(arg1, arg2, ...)."""
        func_token = self.advance()
        func_name = func_token.value

        self.expect(TokenType.LPAREN)

        args = []
        if self.current().type != TokenType.RPAREN:
            args.append(self._parse_expression())

            while self.current().type == TokenType.COMMA:
                self.advance()  # Skip comma
                args.append(self._parse_expression())

        self.expect(TokenType.RPAREN)

        return FunctionCallNode(func_name, args)


# =============================================================================
# Evaluator (Stack-based)
# =============================================================================

class EvaluationError(Exception):
    """Error during evaluation."""
    pass


class FormulaEvaluator:
    """
    Evaluates an AST using a context for variable resolution.

    The context should be a dict with:
    - 'vars': Dict of workflow variables
    - Step names as keys with their output dicts as values
    """

    def __init__(self, context: Dict[str, Any] = None,
                 function_handler: Callable[[str, List[Any]], Any] = None):
        self.context = context or {}
        self.function_handler = function_handler

    def evaluate(self, node: ASTNode) -> Any:
        """Evaluate an AST node and return the result."""
        if isinstance(node, NumberNode):
            return node.value

        if isinstance(node, StringNode):
            return node.value

        if isinstance(node, IdentifierNode):
            # Bareword - treat as string
            return node.name

        if isinstance(node, VariableNode):
            return self._resolve_variable(node.name)

        if isinstance(node, BinaryOpNode):
            return self._evaluate_binary_op(node)

        if isinstance(node, FunctionCallNode):
            return self._evaluate_function(node)

        raise EvaluationError(f"Unknown node type: {type(node).__name__}")

    def _resolve_variable(self, var_ref: str) -> Any:
        """Resolve a variable reference like {{step.field}} or {{vars.x}}."""
        # Extract the path from {{...}}
        match = re.match(r'\{\{(.+?)\}\}', var_ref)
        if not match:
            return var_ref  # Not a variable reference

        path = match.group(1)
        parts = path.split('.')

        # Navigate the context
        current = self.context
        for part in parts:
            if isinstance(current, dict):
                if part in current:
                    current = current[part]
                else:
                    logger.warning(f"Variable path not found: {path}")
                    return ""
            elif isinstance(current, list):
                try:
                    index = int(part)
                    current = current[index]
                except (ValueError, IndexError):
                    logger.warning(f"Invalid list access: {path}")
                    return ""
            else:
                # Try attribute access
                if hasattr(current, part):
                    current = getattr(current, part)
                else:
                    logger.warning(f"Cannot access {part} on {type(current)}")
                    return ""

        return current

    def _evaluate_binary_op(self, node: BinaryOpNode) -> Any:
        """Evaluate a binary operation."""
        left = self.evaluate(node.left)
        right = self.evaluate(node.right)

        # Try numeric operation
        try:
            left_num = float(left) if not isinstance(left, (int, float)) else left
            right_num = float(right) if not isinstance(right, (int, float)) else right

            if node.operator == '+':
                result = left_num + right_num
            elif node.operator == '-':
                result = left_num - right_num
            elif node.operator == '*':
                result = left_num * right_num
            elif node.operator == '/':
                if right_num == 0:
                    raise EvaluationError("Division by zero")
                result = left_num / right_num
            elif node.operator == '%':
                if right_num == 0:
                    raise EvaluationError("Modulo by zero")
                result = left_num % right_num
            else:
                raise EvaluationError(f"Unknown operator: {node.operator}")

            # Return integer if result is whole number
            if isinstance(result, float) and result.is_integer():
                return int(result)
            return result

        except (ValueError, TypeError):
            # Fall back to string concatenation for +
            if node.operator == '+':
                return str(left) + str(right)
            raise EvaluationError(f"Cannot apply {node.operator} to non-numeric values")

    def _evaluate_function(self, node: FunctionCallNode) -> Any:
        """Evaluate a function call."""
        # Evaluate all arguments first
        args = [self.evaluate(arg) for arg in node.args]

        # Use external handler if provided
        if self.function_handler:
            return self.function_handler(node.name, args)

        # Built-in fallback implementations
        return self._builtin_function(node.name, args)

    def _builtin_function(self, name: str, args: List[Any]) -> Any:
        """Built-in function implementations."""
        if name == 'upper':
            return str(args[0]).upper() if args else ""
        if name == 'lower':
            return str(args[0]).lower() if args else ""
        if name == 'trim':
            return str(args[0]).strip() if args else ""
        if name == 'length' or name == 'len':
            return len(str(args[0])) if args else 0
        if name == 'concat':
            return "".join(str(arg) for arg in args)
        if name == 'sum':
            return sum(float(arg) for arg in args)
        if name == 'calc':
            # For calc, the argument should already be evaluated
            return args[0] if args else 0

        raise EvaluationError(f"Function '{name}' not implemented in built-in evaluator")


# =============================================================================
# High-level API
# =============================================================================

class FormulaParser:
    """
    High-level API for parsing and evaluating formulas.

    Usage:
        parser = FormulaParser()

        # Validate a formula
        errors = parser.validate("upper(trim({{step.text}}))")

        # Parse and evaluate
        result = parser.evaluate("upper(hello)", context={})
    """

    def __init__(self, function_handler: Callable[[str, List[Any]], Any] = None):
        self.function_handler = function_handler

    def tokenize(self, formula: str) -> List[Token]:
        """Tokenize a formula string."""
        tokenizer = Tokenizer(formula)
        return tokenizer.tokenize()

    def parse(self, formula: str) -> ASTNode:
        """Parse a formula string into an AST."""
        tokens = self.tokenize(formula)
        parser = Parser(tokens)
        return parser.parse()

    def evaluate(self, formula: str, context: Dict[str, Any] = None) -> Any:
        """Parse and evaluate a formula."""
        ast = self.parse(formula)
        evaluator = FormulaEvaluator(context, self.function_handler)
        return evaluator.evaluate(ast)

    def validate(self, formula: str) -> List[str]:
        """
        Validate a formula and return a list of errors.

        Returns an empty list if the formula is valid.
        """
        errors = []

        try:
            tokens = self.tokenize(formula)
            parser = Parser(tokens)
            parser.parse()
        except TokenizerError as e:
            errors.append(f"Tokenization error: {e}")
        except ParseError as e:
            errors.append(f"Parse error: {e}")
        except Exception as e:
            errors.append(f"Unexpected error: {e}")

        return errors

    def get_variables(self, formula: str) -> List[str]:
        """Extract all variable references from a formula."""
        variables = []
        try:
            tokens = self.tokenize(formula)
            for token in tokens:
                if token.type == TokenType.VARIABLE:
                    variables.append(token.value)
        except Exception:
            pass
        return variables

    def get_functions(self, formula: str) -> List[str]:
        """Extract all function names used in a formula."""
        functions = []
        try:
            tokens = self.tokenize(formula)
            for token in tokens:
                if token.type == TokenType.FUNCTION:
                    functions.append(token.value)
        except Exception:
            pass
        return functions


# =============================================================================
# Convenience Functions
# =============================================================================

def validate_formula(formula: str) -> Tuple[bool, List[str]]:
    """
    Validate a formula string.

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    parser = FormulaParser()
    errors = parser.validate(formula)
    return len(errors) == 0, errors


def parse_formula(formula: str) -> ASTNode:
    """Parse a formula string into an AST."""
    parser = FormulaParser()
    return parser.parse(formula)


def evaluate_formula(formula: str, context: Dict[str, Any] = None,
                    function_handler: Callable[[str, List[Any]], Any] = None) -> Any:
    """Parse and evaluate a formula."""
    parser = FormulaParser(function_handler)
    return parser.evaluate(formula, context)

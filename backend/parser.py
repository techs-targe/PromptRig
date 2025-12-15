"""Response parser for LLM outputs.

Based on specification in docs/req.txt section 6.2 (パーサー)
Phase 2 implementation with JSON Path and regex support.
"""

import json
import re
from typing import Any, Dict, Optional
from enum import Enum


class ParserType(str, Enum):
    """Parser types supported."""
    JSON = "json"  # Simple JSON with fields list
    JSON_PATH = "json_path"  # JSON with path expressions
    REGEX = "regex"
    NONE = "none"


class ResponseParser:
    """Parser for LLM response text.

    Specification: docs/req.txt section 6.2
    """

    def __init__(self, parser_config: Optional[str] = None):
        """Initialize parser with configuration.

        Args:
            parser_config: JSON string with parser configuration
                Example: {
                    "type": "json_path",
                    "paths": {
                        "answer": "$.answer",
                        "confidence": "$.confidence"
                    }
                }
                or {
                    "type": "regex",
                    "patterns": {
                        "answer": "Answer: (.+)",
                        "score": "Score: (\\d+)"
                    }
                }
        """
        self.config = {}
        self.parser_type = ParserType.NONE

        if parser_config:
            try:
                self.config = self._unwrap_json(parser_config)
                if isinstance(self.config, dict):
                    self.parser_type = ParserType(self.config.get("type", "none"))
                else:
                    # If unwrap failed to produce a dict, reset
                    self.config = {}
                    self.parser_type = ParserType.NONE
            except (json.JSONDecodeError, ValueError):
                self.parser_type = ParserType.NONE

    def _unwrap_json(self, value: Any, max_depth: int = 10) -> Any:
        """Recursively unwrap JSON-encoded strings until we get the actual value.

        Handles multi-encoded JSON like: '"\\"{\\\\\\"type\\\\\\":\\\\\\"json_path\\\\\\"}"'

        Args:
            value: The value to unwrap (string or already decoded)
            max_depth: Maximum recursion depth to prevent infinite loops

        Returns:
            The unwrapped value (dict, list, or primitive)
        """
        if max_depth <= 0:
            return value

        # If it's already a dict or list, return as-is
        if isinstance(value, (dict, list)):
            return value

        # If it's not a string, return as-is
        if not isinstance(value, str):
            return value

        # Try to parse as JSON
        try:
            parsed = json.loads(value)
            # If the result is still a string, it might be double-encoded
            if isinstance(parsed, str):
                return self._unwrap_json(parsed, max_depth - 1)
            return parsed
        except (json.JSONDecodeError, TypeError):
            return value

    def parse(self, raw_response: str) -> Dict[str, Any]:
        """Parse raw LLM response according to configuration.

        Args:
            raw_response: Raw text response from LLM

        Returns:
            Dictionary with parsed fields and optional CSV output

        Specification: docs/req.txt section 6.2
        """
        if not raw_response:
            return {"raw": raw_response, "parsed": False}

        if self.parser_type == ParserType.JSON:
            result = self._parse_json(raw_response)
        elif self.parser_type == ParserType.JSON_PATH:
            result = self._parse_json_path(raw_response)
        elif self.parser_type == ParserType.REGEX:
            result = self._parse_regex(raw_response)
        else:
            # No parsing, return raw
            return {"raw": raw_response, "parsed": False}

        # Apply CSV template if configured
        if result.get("parsed") and "csv_template" in self.config:
            csv_result = self._apply_csv_template(result.get("fields", {}))
            result["csv_output"] = csv_result.get("data", "")
            result["csv_header"] = csv_result.get("header", "")

        return result

    def _extract_json_from_response(self, raw_response: str) -> Optional[str]:
        """Extract JSON from response, handling Markdown code blocks.

        Handles:
        - Pure JSON response
        - JSON inside ```json ... ``` code blocks
        - JSON inside ``` ... ``` code blocks
        """
        # First, try to extract from Markdown code block
        code_block_pattern = r'```(?:json)?\s*\n?([\s\S]*?)\n?```'
        match = re.search(code_block_pattern, raw_response)
        if match:
            return match.group(1).strip()

        # Try direct JSON parse
        return raw_response.strip()

    def _parse_json(self, raw_response: str) -> Dict[str, Any]:
        """Parse JSON response with fields extraction.

        Configuration:
            {
                "type": "json",
                "fields": ["field1", "field2", ...]  # Optional: specific fields to extract
            }

        If fields is specified, only those fields are extracted.
        If fields is empty or not specified, all JSON fields are extracted.
        """
        result = {"raw": raw_response, "parsed": True, "fields": {}}

        try:
            # Extract JSON from response (handles Markdown code blocks)
            json_str = self._extract_json_from_response(raw_response)
            json_data = json.loads(json_str)

            if not isinstance(json_data, dict):
                return {
                    "raw": raw_response,
                    "parsed": False,
                    "error": "Response is not a JSON object"
                }

            # Get fields to extract
            fields_to_extract = self.config.get("fields", [])

            if fields_to_extract:
                # Extract only specified fields
                for field_name in fields_to_extract:
                    if field_name in json_data:
                        result["fields"][field_name] = json_data[field_name]
            else:
                # Extract all fields
                result["fields"] = json_data.copy()

            return result

        except json.JSONDecodeError:
            return {
                "raw": raw_response,
                "parsed": False,
                "error": "Response is not valid JSON"
            }

    def _parse_json_path(self, raw_response: str) -> Dict[str, Any]:
        """Parse using JSON path expressions.

        Simplified JSON path implementation for Phase 2.
        Supports basic $.field and $.nested.field syntax.
        """
        result = {"raw": raw_response, "parsed": True, "fields": {}}

        try:
            # Extract JSON from response (handles Markdown code blocks)
            json_str = self._extract_json_from_response(raw_response)
            json_data = json.loads(json_str)

            # Extract fields according to paths
            paths = self.config.get("paths", {})
            for field_name, path in paths.items():
                value = self._extract_json_path(json_data, path)
                if value is not None:
                    result["fields"][field_name] = value

            return result

        except json.JSONDecodeError:
            return {
                "raw": raw_response,
                "parsed": False,
                "error": "Response is not valid JSON"
            }

    def _extract_json_path(self, data: Any, path: str) -> Any:
        """Extract value from JSON data using simple path.

        Supports:
        - $.field
        - $.field.nested
        - $.field.nested.deep
        """
        if not path.startswith("$."):
            return None

        # Remove $. prefix
        path = path[2:]

        # Split by dots
        parts = path.split(".")

        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None

        return current

    def _parse_regex(self, raw_response: str) -> Dict[str, Any]:
        """Parse using regex patterns.

        Args:
            raw_response: Raw text to parse

        Returns:
            Dictionary with extracted fields
        """
        result = {"raw": raw_response, "parsed": True, "fields": {}}

        patterns = self.config.get("patterns", {})
        for field_name, pattern in patterns.items():
            match = re.search(pattern, raw_response, re.DOTALL)
            if match:
                # Use first group if available, otherwise full match
                value = match.group(1) if match.groups() else match.group(0)
                result["fields"][field_name] = value

        return result

    def _csv_escape_value(self, value: str, force_quote: bool = False) -> str:
        """Escape a value for CSV output according to RFC 4180.

        Args:
            value: The string value to escape
            force_quote: If True, always wrap in double quotes

        Returns:
            Properly escaped CSV value

        Rules (RFC 4180):
        - If value contains comma, newline, or double quote, wrap in double quotes
        - Double quotes within value are escaped by doubling them ("")
        - If force_quote is True, always wrap in double quotes
        """
        if value is None:
            return '""' if force_quote else ""

        str_value = str(value)

        # Check if quoting is needed
        needs_quoting = force_quote or any(c in str_value for c in [',', '\n', '\r', '"'])

        if needs_quoting:
            # Escape double quotes by doubling them
            escaped = str_value.replace('"', '""')
            return f'"{escaped}"'

        return str_value

    def _apply_csv_template(self, fields: Dict[str, Any]) -> Dict[str, str]:
        """Apply CSV template to extracted fields with proper CSV escaping.

        Args:
            fields: Dictionary of extracted fields

        Returns:
            Dictionary with 'header' and 'data' keys for CSV output

        Example:
            Template: "$field1$,$field2$,$field3$"
            Fields: {"field1": "A", "field2": "B, with comma", "field3": "C"}
            Result: {"header": "field1,field2,field3", "data": "A,\"B, with comma\",C"}

            Template with quotes: "\"$field1$\",\"$field2$\""
            Fields: {"field1": "A", "field2": "B, with \"quote\""}
            Result: {"header": "field1,field2", "data": "\"A\",\"B, with \"\"quote\"\"\""}

        Config options:
            csv_template: Template string with $field$ placeholders
            csv_header: Custom header string (optional)
            csv_quote_all: If true, quote all values regardless of content (optional)
        """
        import re

        template = self.config.get("csv_template", "")
        if not template:
            return {"header": "", "data": ""}

        # Check if we should quote all values
        quote_all = self.config.get("csv_quote_all", False)

        # Extract field names from template (in order of appearance)
        placeholders = re.findall(r'\$([^$]+)\$', template)

        # Use custom csv_header if specified, otherwise generate from placeholder names
        custom_header = self.config.get("csv_header")
        if custom_header:
            header = custom_header
        else:
            header = ",".join(placeholders)

        # Replace $field_name$ with properly escaped field values for data row
        data = template
        for field_name, value in fields.items():
            placeholder = f"${field_name}$"
            quoted_placeholder = f'"{placeholder}"'

            # Check if placeholder is already wrapped in double quotes in template
            if quoted_placeholder in data:
                # Template has quotes around placeholder: "$field$"
                # Only escape internal double quotes (by doubling them), don't add outer quotes
                str_value = str(value) if value is not None else ""
                escaped_value = str_value.replace('"', '""')
                data = data.replace(quoted_placeholder, f'"{escaped_value}"')
            else:
                # Bare placeholder: $field$
                # Apply full CSV escaping (add quotes if needed)
                escaped_value = self._csv_escape_value(value, force_quote=quote_all)
                data = data.replace(placeholder, escaped_value)

        return {"header": header, "data": data}


def create_default_parser_config() -> str:
    """Create default parser configuration (no parsing).

    Returns:
        JSON string with default config
    """
    return json.dumps({"type": "none"})


def create_json_parser_config(paths: Dict[str, str]) -> str:
    """Create JSON path parser configuration.

    Args:
        paths: Dictionary mapping field names to JSON paths

    Returns:
        JSON string with parser config

    Example:
        create_json_parser_config({
            "answer": "$.answer",
            "confidence": "$.metadata.confidence"
        })
    """
    return json.dumps({
        "type": "json_path",
        "paths": paths
    })


def create_regex_parser_config(patterns: Dict[str, str]) -> str:
    r"""Create regex parser configuration.

    Args:
        patterns: Dictionary mapping field names to regex patterns

    Returns:
        JSON string with parser config

    Example:
        create_regex_parser_config({
            "answer": r"Answer: (.+)",
            "score": r"Score: (\d+)"
        })
    """
    return json.dumps({
        "type": "regex",
        "patterns": patterns
    })

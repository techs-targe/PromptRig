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
    JSON_PATH = "json_path"
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
                self.config = json.loads(parser_config)
                self.parser_type = ParserType(self.config.get("type", "none"))
            except (json.JSONDecodeError, ValueError):
                self.parser_type = ParserType.NONE

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

        if self.parser_type == ParserType.JSON_PATH:
            result = self._parse_json_path(raw_response)
        elif self.parser_type == ParserType.REGEX:
            result = self._parse_regex(raw_response)
        else:
            # No parsing, return raw
            return {"raw": raw_response, "parsed": False}

        # Apply CSV template if configured
        if result.get("parsed") and "csv_template" in self.config:
            csv_line = self._apply_csv_template(result.get("fields", {}))
            result["csv_output"] = csv_line

        return result

    def _parse_json_path(self, raw_response: str) -> Dict[str, Any]:
        """Parse using JSON path expressions.

        Simplified JSON path implementation for Phase 2.
        Supports basic $.field and $.nested.field syntax.
        """
        result = {"raw": raw_response, "parsed": True, "fields": {}}

        try:
            # Try to parse as JSON
            json_data = json.loads(raw_response)

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

    def _apply_csv_template(self, fields: Dict[str, Any]) -> str:
        """Apply CSV template to extracted fields.

        Args:
            fields: Dictionary of extracted fields

        Returns:
            CSV-formatted string with field values substituted

        Example:
            Template: "$field1$,$field2$,$field3$"
            Fields: {"field1": "A", "field2": "B", "field3": "C"}
            Result: "A,B,C"
        """
        template = self.config.get("csv_template", "")
        if not template:
            return ""

        # Replace $field_name$ with field values
        result = template
        for field_name, value in fields.items():
            placeholder = f"${field_name}$"
            # Convert value to string, handle None
            str_value = str(value) if value is not None else ""
            result = result.replace(placeholder, str_value)

        return result


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
    """Create regex parser configuration.

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

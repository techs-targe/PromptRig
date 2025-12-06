"""Prompt template parser with {{}} syntax support.

Based on specification in docs/req.txt section 4.2.2 (フォーム自動生成ロジック)

Syntax:
    {{PARAM_NAME}}          - Default: TEXT5 (5-line textarea)
    {{PARAM_NAME:TEXT10}}   - 10-line textarea
    {{PARAM_NAME:NUM}}      - Number input
    {{PARAM_NAME:DATE}}     - Date input
    {{PARAM_NAME:DATETIME}} - DateTime input

Rules:
- Duplicate parameter names use the same value across all occurrences
- Form generates one input per unique parameter name
"""

import re
from typing import Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class ParameterDefinition:
    """Definition of a single parameter extracted from template."""
    name: str
    type: str  # TEXTn, NUM, DATE, DATETIME, FILE, FILEPATH
    html_type: str  # textarea, number, date, datetime-local, file, text
    rows: int = 5  # Only for textarea
    accept: str = None  # Only for file input (e.g., "image/*")
    placeholder: str = None  # For text inputs


class PromptTemplateParser:
    """Parser for prompt templates with {{}} syntax."""

    # Pattern to match {{PARAM_NAME[:TYPE]}}
    PARAM_PATTERN = re.compile(r'\{\{([a-zA-Z0-9_]+)(?::([a-zA-Z0-9]+))?\}\}')

    # Supported types
    TYPE_TEXT = "TEXT"  # TEXT5, TEXT10, etc.
    TYPE_NUM = "NUM"
    TYPE_DATE = "DATE"
    TYPE_DATETIME = "DATETIME"
    TYPE_FILE = "FILE"  # Image file upload (Vision API)
    TYPE_FILEPATH = "FILEPATH"  # Server-accessible file path

    # Default type
    DEFAULT_TYPE = "TEXT5"

    def parse_template(self, template: str) -> List[ParameterDefinition]:
        """Extract all parameter definitions from template.

        Args:
            template: Prompt template string with {{}} syntax

        Returns:
            List of ParameterDefinition objects (deduplicated by name)

        Specification: docs/req.txt section 4.2.2
        """
        # Find all matches
        matches = self.PARAM_PATTERN.findall(template)

        # Deduplicate by parameter name (keep first occurrence)
        seen = set()
        params = []

        for name, type_spec in matches:
            if name in seen:
                continue
            seen.add(name)

            # Parse type specification
            param_def = self._parse_type(name, type_spec)
            params.append(param_def)

        return params

    def _parse_type(self, name: str, type_spec: str) -> ParameterDefinition:
        """Parse type specification into ParameterDefinition.

        Args:
            name: Parameter name
            type_spec: Type specification (empty for default, or TEXT10, NUM, etc.)

        Returns:
            ParameterDefinition object
        """
        if not type_spec:
            type_spec = self.DEFAULT_TYPE

        # Handle TEXTn format
        if type_spec.startswith(self.TYPE_TEXT):
            # Extract row count (default 5)
            rows_str = type_spec[len(self.TYPE_TEXT):]
            rows = int(rows_str) if rows_str.isdigit() else 5

            return ParameterDefinition(
                name=name,
                type=type_spec,
                html_type="textarea",
                rows=rows
            )

        # Handle NUM
        elif type_spec == self.TYPE_NUM:
            return ParameterDefinition(
                name=name,
                type=type_spec,
                html_type="number",
                rows=0
            )

        # Handle DATE
        elif type_spec == self.TYPE_DATE:
            return ParameterDefinition(
                name=name,
                type=type_spec,
                html_type="date",
                rows=0
            )

        # Handle DATETIME
        elif type_spec == self.TYPE_DATETIME:
            return ParameterDefinition(
                name=name,
                type=type_spec,
                html_type="datetime-local",
                rows=0
            )

        # Handle FILE (image upload for Vision API)
        elif type_spec == self.TYPE_FILE:
            return ParameterDefinition(
                name=name,
                type=type_spec,
                html_type="file",
                rows=0,
                accept="image/*"
            )

        # Handle FILEPATH (server-accessible file path)
        elif type_spec == self.TYPE_FILEPATH:
            return ParameterDefinition(
                name=name,
                type=type_spec,
                html_type="text",
                rows=0,
                placeholder="/path/to/image.jpg"
            )

        # Unknown type, default to TEXT5
        else:
            return ParameterDefinition(
                name=name,
                type=self.DEFAULT_TYPE,
                html_type="textarea",
                rows=5
            )

    def substitute_parameters(self, template: str, params: Dict[str, str]) -> str:
        """Substitute all {{}} placeholders with actual values.

        Args:
            template: Prompt template string with {{}} syntax
            params: Dictionary mapping parameter names to values

        Returns:
            Template with all placeholders replaced

        Specification: docs/req.txt section 4.2.2
        Note: Same parameter name used multiple times gets same value
        Note: FILE and FILEPATH parameters are excluded from prompt text
              (they are sent separately as images to Vision API)
        """
        # Parse template to get parameter types
        param_defs = self.parse_template(template)
        image_params = {p.name for p in param_defs if p.type in [self.TYPE_FILE, self.TYPE_FILEPATH]}

        def replacer(match):
            param_name = match.group(1)

            # Exclude FILE/FILEPATH parameters from prompt text
            # (they are sent separately as images to Vision API)
            if param_name in image_params:
                return ""  # Remove image parameters from prompt text

            # Return the value if exists, otherwise keep the placeholder
            return params.get(param_name, match.group(0))

        return self.PARAM_PATTERN.sub(replacer, template)

    def extract_parameter_names(self, template: str) -> List[str]:
        """Extract all unique parameter names from template.

        Args:
            template: Prompt template string with {{}} syntax

        Returns:
            List of unique parameter names (in order of first appearance)
        """
        matches = self.PARAM_PATTERN.findall(template)
        seen = set()
        names = []

        for name, _ in matches:
            if name not in seen:
                seen.add(name)
                names.append(name)

        return names

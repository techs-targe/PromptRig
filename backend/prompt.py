"""Prompt template parser with {{}} syntax support.

Based on specification in docs/req.txt section 4.2.2 (フォーム自動生成ロジック)

Syntax:
    {{PARAM_NAME}}                    - Default: TEXT5 (5-line textarea), required
    {{PARAM_NAME:TEXT10}}             - 10-line textarea, required
    {{PARAM_NAME:NUM}}                - Number input, required
    {{PARAM_NAME:DATE}}               - Date input, required
    {{PARAM_NAME:DATETIME}}           - DateTime input, required
    {{PARAM_NAME:TYPE|}}              - Optional parameter (no default value)
    {{PARAM_NAME:TYPE|default=値}}    - Optional parameter with default value

Rules:
- Duplicate parameter names use the same value across all occurrences
- Form generates one input per unique parameter name
- Parameters without | are required (HTML5 validation)
- Parameters with | are optional (no HTML5 required attribute)
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
    required: bool = True  # True if parameter is required (no | pipe in template)
    default: str = None  # Default value if optional (from |default=...)


class PromptTemplateParser:
    """Parser for prompt templates with {{}} syntax."""

    # Pattern to match {{PARAM_NAME[:TYPE][|[default=VALUE]]}}
    # Groups: (1)name, (2)type, (3)pipe, (4)default_value
    PARAM_PATTERN = re.compile(r'\{\{([a-zA-Z0-9_]+)(?::([a-zA-Z0-9]+))?(\|)?(?:default=([^}]*))?\}\}')

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

        for name, type_spec, pipe, default_value in matches:
            if name in seen:
                continue
            seen.add(name)

            # Determine if parameter is optional (has | pipe)
            is_optional = (pipe == '|')
            default = default_value if default_value else None

            # Parse type specification
            param_def = self._parse_type(name, type_spec, is_optional, default)
            params.append(param_def)

        return params

    def _parse_type(self, name: str, type_spec: str, is_optional: bool, default_value: str) -> ParameterDefinition:
        """Parse type specification into ParameterDefinition.

        Args:
            name: Parameter name
            type_spec: Type specification (empty for default, or TEXT10, NUM, etc.)
            is_optional: True if parameter has | pipe (optional)
            default_value: Default value if specified with |default=...

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
                rows=rows,
                required=not is_optional,
                default=default_value
            )

        # Handle NUM
        elif type_spec == self.TYPE_NUM:
            return ParameterDefinition(
                name=name,
                type=type_spec,
                html_type="number",
                rows=0,
                required=not is_optional,
                default=default_value
            )

        # Handle DATE
        elif type_spec == self.TYPE_DATE:
            return ParameterDefinition(
                name=name,
                type=type_spec,
                html_type="date",
                rows=0,
                required=not is_optional,
                default=default_value
            )

        # Handle DATETIME
        elif type_spec == self.TYPE_DATETIME:
            return ParameterDefinition(
                name=name,
                type=type_spec,
                html_type="datetime-local",
                rows=0,
                required=not is_optional,
                default=default_value
            )

        # Handle FILE (image upload for Vision API)
        elif type_spec == self.TYPE_FILE:
            return ParameterDefinition(
                name=name,
                type=type_spec,
                html_type="file",
                rows=0,
                accept="image/*",
                required=not is_optional,
                default=default_value
            )

        # Handle FILEPATH (server-accessible file path)
        elif type_spec == self.TYPE_FILEPATH:
            return ParameterDefinition(
                name=name,
                type=type_spec,
                html_type="text",
                rows=0,
                placeholder="/path/to/image.jpg",
                required=not is_optional,
                default=default_value
            )

        # Unknown type, default to TEXT5
        else:
            return ParameterDefinition(
                name=name,
                type=self.DEFAULT_TYPE,
                html_type="textarea",
                rows=5,
                required=not is_optional,
                default=default_value
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
        Note: Optional parameters use default value if not provided, or empty string
        """
        # Parse template to get parameter types, defaults, and required status
        param_defs = self.parse_template(template)
        image_params = {p.name for p in param_defs if p.type in [self.TYPE_FILE, self.TYPE_FILEPATH]}
        defaults = {p.name: p.default for p in param_defs if p.default is not None}
        optional_params = {p.name for p in param_defs if not p.required}

        def replacer(match):
            param_name = match.group(1)

            # Exclude FILE/FILEPATH parameters from prompt text
            # (they are sent separately as images to Vision API)
            if param_name in image_params:
                return ""  # Remove image parameters from prompt text

            # Get user-provided value (may be empty string)
            user_value = params.get(param_name, None)

            # If user provided non-empty value, use it
            if user_value:
                return user_value
            # If parameter has default value, use it (for empty or missing values)
            elif param_name in defaults:
                return defaults[param_name]
            # If parameter is optional, return empty string
            elif param_name in optional_params:
                return ""  # Optional parameter without value → empty string
            # Required parameter without value → keep placeholder (error case)
            else:
                return match.group(0)

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

        for name, _, _, _ in matches:  # name, type, pipe, default
            if name not in seen:
                seen.add(name)
                names.append(name)

        return names

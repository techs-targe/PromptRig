"""Unit test for prompt template parser.

Tests the {{}} syntax parsing functionality.
Based on specification in docs/req.txt section 4.2.2
"""

from backend.prompt import PromptTemplateParser


def test_basic_parsing():
    """Test basic parameter extraction."""
    parser = PromptTemplateParser()

    template = "質問: {{question}} コンテキスト: {{context}}"
    params = parser.parse_template(template)

    assert len(params) == 2
    assert params[0].name == "question"
    assert params[0].type == "TEXT5"
    assert params[0].html_type == "textarea"
    assert params[0].rows == 5

    assert params[1].name == "context"
    print("✓ Basic parsing test passed")


def test_type_specifications():
    """Test different type specifications."""
    parser = PromptTemplateParser()

    template = """
    {{text_field:TEXT10}}
    {{number_field:NUM}}
    {{date_field:DATE}}
    {{datetime_field:DATETIME}}
    """
    params = parser.parse_template(template)

    assert len(params) == 4

    # TEXT10
    assert params[0].name == "text_field"
    assert params[0].type == "TEXT10"
    assert params[0].rows == 10

    # NUM
    assert params[1].name == "number_field"
    assert params[1].type == "NUM"
    assert params[1].html_type == "number"

    # DATE
    assert params[2].name == "date_field"
    assert params[2].type == "DATE"
    assert params[2].html_type == "date"

    # DATETIME
    assert params[3].name == "datetime_field"
    assert params[3].type == "DATETIME"
    assert params[3].html_type == "datetime-local"

    print("✓ Type specifications test passed")


def test_duplicate_parameters():
    """Test that duplicate parameters are deduplicated."""
    parser = PromptTemplateParser()

    template = "First: {{param}} Second: {{param}} Third: {{other}}"
    params = parser.parse_template(template)

    # Should only have 2 unique parameters
    assert len(params) == 2
    assert params[0].name == "param"
    assert params[1].name == "other"

    print("✓ Duplicate parameters test passed")


def test_parameter_substitution():
    """Test parameter substitution into template."""
    parser = PromptTemplateParser()

    template = "Hello {{name}}, you are {{age:NUM}} years old."
    params_dict = {
        "name": "Alice",
        "age": "30"
    }

    result = parser.substitute_parameters(template, params_dict)
    expected = "Hello Alice, you are 30 years old."

    assert result == expected
    print("✓ Parameter substitution test passed")


def test_duplicate_substitution():
    """Test that duplicate parameters get same value."""
    parser = PromptTemplateParser()

    template = "{{word}} is a {{word}}"
    params_dict = {"word": "test"}

    result = parser.substitute_parameters(template, params_dict)
    expected = "test is a test"

    assert result == expected
    print("✓ Duplicate substitution test passed")


def test_extract_parameter_names():
    """Test extracting parameter names only."""
    parser = PromptTemplateParser()

    template = "{{a:TEXT10}} {{b:NUM}} {{a}} {{c}}"
    names = parser.extract_parameter_names(template)

    # Should maintain order and deduplicate
    assert names == ["a", "b", "c"]
    print("✓ Extract parameter names test passed")


if __name__ == "__main__":
    print("Running prompt parser tests...")
    print("=" * 60)

    test_basic_parsing()
    test_type_specifications()
    test_duplicate_parameters()
    test_parameter_substitution()
    test_duplicate_substitution()
    test_extract_parameter_names()

    print("=" * 60)
    print("✅ All tests passed!")

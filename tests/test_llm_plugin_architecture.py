#!/usr/bin/env python3
"""LLM Plugin Architecture Tests

Tests the auto-discovery plugin system for LLM models.
"""

import sys
import unittest
from pathlib import Path


class TestLLMPluginArchitecture(unittest.TestCase):
    """Test cases for LLM plugin auto-discovery system."""

    def setUp(self):
        """Clear module cache before each test."""
        # Clear any cached modules to ensure fresh discovery
        modules_to_remove = [k for k in sys.modules if k.startswith('backend.llm')]
        for mod in modules_to_remove:
            del sys.modules[mod]

    def test_discover_models_returns_all_expected_models(self):
        """Test that auto-discovery finds all expected models."""
        from backend.llm.factory import get_discovered_model_names

        names = get_discovered_model_names()

        # Expected models (with DISPLAY_NAME defined)
        expected_models = [
            # Azure models
            "azure-gpt-4.1",
            "azure-gpt-4o",
            "azure-gpt-4o-mini",
            "azure-gpt-5-mini",
            "azure-gpt-5-nano",
            # OpenAI models
            "openai-gpt-4.1-nano",
            "openai-gpt-5-nano",
            "openai-o4-mini",
            # Claude models (claude-3.5-sonnet and claude-3-opus disabled due to 404)
            "claude-sonnet-4",
            "claude-3.5-haiku",
            # Claude 4.5 models
            "claude-haiku-4.5",
            "claude-opus-4.5",
            "claude-sonnet-4.5",
        ]

        for model in expected_models:
            self.assertIn(model, names, f"Model '{model}' should be discovered")

    def test_discover_private_models(self):
        """Test that private models are discovered."""
        from backend.llm.factory import get_discovered_model_names

        names = get_discovered_model_names()

        # Check that at least one private model is discovered
        # (Claude Neptune v7 should be in private/)
        self.assertIn("Claude Neptune v7", names,
                     "Private model 'Claude Neptune v7' should be discovered")

    def test_get_available_models_returns_only_configured(self):
        """Test that get_available_models only returns properly configured models."""
        from backend.llm.factory import get_available_models

        models = get_available_models()

        # Each model should have required fields
        for model in models:
            self.assertIn("name", model)
            self.assertIn("display_name", model)
            self.assertIn("default_parameters", model)
            self.assertIn("is_private", model)

            # default_parameters should be a dict
            self.assertIsInstance(model["default_parameters"], dict)

    def test_get_llm_client_returns_correct_client(self):
        """Test that get_llm_client returns working clients."""
        from backend.llm.factory import get_llm_client, get_available_models
        from backend.llm.base import LLMClient

        models = get_available_models()

        for model_info in models[:3]:  # Test first 3 available models
            model_name = model_info["name"]
            client = get_llm_client(model_name)

            # Should return an LLMClient instance
            self.assertIsInstance(client, LLMClient,
                                 f"{model_name} should return LLMClient instance")

            # Should have required methods
            self.assertTrue(hasattr(client, 'call'))
            self.assertTrue(hasattr(client, 'get_default_parameters'))
            self.assertTrue(hasattr(client, 'get_model_name'))

    def test_get_llm_client_raises_for_unknown_model(self):
        """Test that get_llm_client raises ValueError for unknown models."""
        from backend.llm.factory import get_llm_client

        with self.assertRaises(ValueError) as context:
            get_llm_client("nonexistent-model-xyz")

        self.assertIn("Unsupported model", str(context.exception))

    def test_discovery_caches_results(self):
        """Test that discovery is cached (only runs once)."""
        from backend.llm import factory

        # Reset cache
        factory._discovered_models = {}
        factory._discovery_done = False

        # First call should discover
        factory._discover_models()
        count1 = len(factory._discovered_models)
        done1 = factory._discovery_done

        # Add a fake model to cache
        factory._discovered_models["fake-model"] = None

        # Second call should not re-discover (cache should be used)
        factory._discover_models()
        count2 = len(factory._discovered_models)

        self.assertTrue(done1, "Discovery should mark as done")
        self.assertEqual(count2, count1 + 1, "Fake model should remain (cache used)")

    def test_private_models_marked_correctly(self):
        """Test that private models have is_private=True."""
        from backend.llm.factory import get_available_models

        models = get_available_models()

        for model in models:
            if "Neptune" in model["name"] or "neptune" in model["name"].lower():
                self.assertTrue(model["is_private"],
                              f"{model['name']} should be marked as private")

    def test_display_name_consistency(self):
        """Test that DISPLAY_NAME matches the model identifier."""
        from backend.llm.factory import get_available_models

        models = get_available_models()

        for model in models:
            # name should equal display_name (by design)
            self.assertEqual(model["name"], model["display_name"],
                           f"Model name and display_name should match for {model['name']}")


class TestLLMClientBase(unittest.TestCase):
    """Test base LLMClient interface."""

    def test_all_clients_have_display_name(self):
        """Test that all client classes have DISPLAY_NAME."""
        from backend.llm.factory import _discover_models, _discovered_models

        _discover_models()

        for name, client_class in _discovered_models.items():
            self.assertTrue(hasattr(client_class, 'DISPLAY_NAME'),
                          f"{client_class.__name__} should have DISPLAY_NAME")

    def test_normalize_messages_helper(self):
        """Test _normalize_messages helper method."""
        from backend.llm.base import LLMClient

        # Create a minimal mock client to test the helper
        class MockClient(LLMClient):
            DISPLAY_NAME = "mock"

            def call(self, prompt=None, messages=None, images=None, **kwargs):
                pass

            def get_default_parameters(self):
                return {}

            def get_model_name(self):
                return "mock"

        client = MockClient()

        # Test with prompt only
        result = client._normalize_messages(prompt="Hello")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["role"], "user")
        self.assertEqual(result[0]["content"], "Hello")

        # Test with messages
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"}
        ]
        result = client._normalize_messages(messages=messages)
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

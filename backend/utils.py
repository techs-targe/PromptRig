"""Utility functions for the backend."""

import os


def get_app_name() -> str:
    """Get the application name from environment variable.

    Returns:
        str: Application name from APP_NAME environment variable,
             defaults to "PromptRig" if not set.
    """
    return os.getenv("APP_NAME", "PromptRig")

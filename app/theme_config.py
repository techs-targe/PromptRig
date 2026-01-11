"""Theme and branding configuration from environment variables.

Loads app name and theme colors from .env with sensible defaults.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Load .env file
load_dotenv()


@dataclass
class ThemeConfig:
    """Application theme configuration."""

    # App branding
    app_name: str
    app_version: str

    # Primary colors
    color_primary: str
    color_primary_dark: str
    color_primary_light: str

    # Status colors
    color_success: str
    color_success_dark: str
    color_danger: str
    color_danger_dark: str
    color_warning: str
    color_warning_dark: str
    color_info: str
    color_info_dark: str

    # Neutral colors
    color_text: str
    color_text_light: str
    color_text_muted: str
    color_border: str
    color_border_light: str
    color_background: str
    color_background_alt: str

    def to_css_vars(self) -> str:
        """Generate CSS custom properties string."""
        return f"""
    --color-primary: {self.color_primary};
    --color-primary-dark: {self.color_primary_dark};
    --color-primary-light: {self.color_primary_light};
    --color-success: {self.color_success};
    --color-success-dark: {self.color_success_dark};
    --color-danger: {self.color_danger};
    --color-danger-dark: {self.color_danger_dark};
    --color-warning: {self.color_warning};
    --color-warning-dark: {self.color_warning_dark};
    --color-info: {self.color_info};
    --color-info-dark: {self.color_info_dark};
    --color-text: {self.color_text};
    --color-text-light: {self.color_text_light};
    --color-text-muted: {self.color_text_muted};
    --color-border: {self.color_border};
    --color-border-light: {self.color_border_light};
    --color-background: {self.color_background};
    --color-background-alt: {self.color_background_alt};
"""


def get_theme_config() -> ThemeConfig:
    """Load theme configuration from environment variables.

    All settings have defaults, so .env entries are optional.
    """
    return ThemeConfig(
        # App branding
        app_name=os.getenv("APP_NAME", "PromptRig"),
        app_version=os.getenv("APP_VERSION", "3.0.0"),

        # Primary colors (blue by default)
        color_primary=os.getenv("THEME_COLOR_PRIMARY", "#3b82f6"),
        color_primary_dark=os.getenv("THEME_COLOR_PRIMARY_DARK", "#2563eb"),
        color_primary_light=os.getenv("THEME_COLOR_PRIMARY_LIGHT", "#60a5fa"),

        # Status colors
        color_success=os.getenv("THEME_COLOR_SUCCESS", "#22c55e"),
        color_success_dark=os.getenv("THEME_COLOR_SUCCESS_DARK", "#16a34a"),
        color_danger=os.getenv("THEME_COLOR_DANGER", "#ef4444"),
        color_danger_dark=os.getenv("THEME_COLOR_DANGER_DARK", "#dc2626"),
        color_warning=os.getenv("THEME_COLOR_WARNING", "#f59e0b"),
        color_warning_dark=os.getenv("THEME_COLOR_WARNING_DARK", "#d97706"),
        color_info=os.getenv("THEME_COLOR_INFO", "#06b6d4"),
        color_info_dark=os.getenv("THEME_COLOR_INFO_DARK", "#0891b2"),

        # Neutral colors
        color_text=os.getenv("THEME_COLOR_TEXT", "#1e293b"),
        color_text_light=os.getenv("THEME_COLOR_TEXT_LIGHT", "#475569"),
        color_text_muted=os.getenv("THEME_COLOR_TEXT_MUTED", "#64748b"),
        color_border=os.getenv("THEME_COLOR_BORDER", "#e2e8f0"),
        color_border_light=os.getenv("THEME_COLOR_BORDER_LIGHT", "#f1f5f9"),
        color_background=os.getenv("THEME_COLOR_BACKGROUND", "#ffffff"),
        color_background_alt=os.getenv("THEME_COLOR_BACKGROUND_ALT", "#f8fafc"),
    )


# Singleton instance
_theme_config: ThemeConfig = None


def get_config() -> ThemeConfig:
    """Get or create singleton theme config."""
    global _theme_config
    if _theme_config is None:
        _theme_config = get_theme_config()
    return _theme_config

"""Main page route with HTML template rendering.

Based on specification in docs/req.txt section 3.2 (通信フロー step 1)
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.theme_config import get_config

router = APIRouter()

# Configure Jinja2 templates
templates = Jinja2Templates(directory="app/templates")


def get_template_context(request: Request) -> dict:
    """Get common template context with theme configuration."""
    theme = get_config()
    return {
        "request": request,
        "app_name": theme.app_name,
        "app_version": theme.app_version,
        "theme": theme,
        "css_vars": theme.to_css_vars(),
    }


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Render main page with single execution UI.

    Phase 1 implementation: Single execution mode only

    Specification: docs/req.txt section 3.2 step 1, 4.2.1
    """
    return templates.TemplateResponse("index.html", get_template_context(request))

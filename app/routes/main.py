"""Main page route with HTML template rendering.

Based on specification in docs/req.txt section 3.2 (通信フロー step 1)
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

# Configure Jinja2 templates
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Render main page with single execution UI.

    Phase 1 implementation: Single execution mode only

    Specification: docs/req.txt section 3.2 step 1, 4.2.1
    """
    return templates.TemplateResponse("index.html", {"request": request})
